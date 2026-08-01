import argparse
import itertools
from pathlib import Path

import pandas as pd

import fGeneric as gene
import tokens as tk


DEFAULT_PAIR = "EUR_USD"


def pct(value):
    if pd.isna(value):
        return ""
    return round(float(value) * 100, 2)


def find_latest_result(pair):
    folder = Path(tk.folder_path)
    paths = sorted(
        folder.glob(f"result_{pair}_*.csv"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not paths:
        raise FileNotFoundError(f"No result CSV found for {pair} in {folder}")
    return paths[0]


def ensure_columns(df, columns):
    for column in columns:
        if column not in df.columns:
            df[column] = pd.NA
    return df


def add_price_features(df, pair_name):
    pair_info = gene.currency_pair(pair_name)
    df = df.copy()
    if "pair" not in df.columns:
        df["pair"] = pair_name
    else:
        df["pair"] = df["pair"].fillna(pair_name)
    df = ensure_columns(df, ["target_price", "tp_price", "lc_price"])

    if "tp_pips" not in df.columns:
        df["tp_pips"] = pd.NA
    if "lc_pips" not in df.columns:
        df["lc_pips"] = pd.NA
    if "rr" not in df.columns:
        df["rr"] = pd.NA

    missing_tp = df["tp_pips"].isna()
    missing_lc = df["lc_pips"].isna()
    has_prices = df[["target_price", "tp_price", "lc_price"]].notna().all(axis=1)

    df.loc[missing_tp & has_prices, "tp_pips"] = df.loc[missing_tp & has_prices].apply(
        lambda row: abs(pair_info.price_to_pips(float(row["tp_price"]) - float(row["target_price"]))),
        axis=1,
    )
    df.loc[missing_lc & has_prices, "lc_pips"] = df.loc[missing_lc & has_prices].apply(
        lambda row: abs(pair_info.price_to_pips(float(row["target_price"]) - float(row["lc_price"]))),
        axis=1,
    )

    df["tp_pips"] = pd.to_numeric(df["tp_pips"], errors="coerce")
    df["lc_pips"] = pd.to_numeric(df["lc_pips"], errors="coerce")
    df["rr"] = pd.to_numeric(df["rr"], errors="coerce")
    missing_rr = df["rr"].isna() & df["lc_pips"].notna() & df["lc_pips"].ne(0)
    df.loc[missing_rr, "rr"] = df.loc[missing_rr, "tp_pips"] / df.loc[missing_rr, "lc_pips"]
    return df


def add_bins(df, pair_name):
    df = add_price_features(df, pair_name)
    df = ensure_columns(
        df,
        [
            "source",
            "direction",
            "order_result",
            "target_time",
            "line_entry_type",
            "line_strategy",
            "line_side",
            "latest_peak_dir",
            "line_total_strength",
            "line_count",
            "core_total_strength",
            "core_count",
            "h1_nearest_side",
            "h1_nearest_distance_pips",
            "h1_nearest_total_strength",
            "h1_ahead_side",
            "h1_ahead_distance_pips",
            "h1_ahead_total_strength",
            "h1_blocks_trade_direction",
            "rsi_1",
            "h1_rsi_1",
            "res",
            "max_plus_pips",
            "max_minus_pips",
            "elapsed_seconds",
        ],
    )

    df["target_dt"] = pd.to_datetime(df["target_time"], errors="coerce")
    numeric_columns = [
        "direction",
        "latest_peak_dir",
        "line_total_strength",
        "line_count",
        "core_total_strength",
        "core_count",
        "h1_nearest_distance_pips",
        "h1_nearest_total_strength",
        "h1_ahead_distance_pips",
        "h1_ahead_total_strength",
        "rsi_1",
        "h1_rsi_1",
        "res",
        "max_plus_pips",
        "max_minus_pips",
        "elapsed_seconds",
    ]
    for column in numeric_columns:
        df[column] = pd.to_numeric(df[column], errors="coerce")

    df["session_bucket"] = pd.cut(
        df["target_dt"].dt.hour,
        bins=[-1, 5, 8, 14, 20, 23],
        labels=["00-05", "06-08", "09-14", "15-20", "21-23"],
    )
    df["direction_label"] = df["direction"].map({-1: "sell", 1: "buy"})
    df["peak_to_line"] = (
        (df["latest_peak_dir"].eq(1) & df["line_side"].eq("upper"))
        | (df["latest_peak_dir"].eq(-1) & df["line_side"].eq("lower"))
    )

    strength_bins = [-0.1, 5, 10, 15, 20, 999]
    strength_labels = ["0-5", "5-10", "10-15", "15-20", "20+"]
    count_bins = [-0.1, 1, 2, 3, 5, 999]
    count_labels = ["1", "2", "3", "4-5", "6+"]
    distance_bins = [-0.1, 3, 6, 10, 15, 25, 999]
    distance_labels = ["0-3", "3-6", "6-10", "10-15", "15-25", "25+"]
    rsi_bins = [-0.1, 30, 40, 50, 60, 67.5, 100]
    rsi_labels = ["<=30", "30-40", "40-50", "50-60", "60-67.5", "67.5+"]

    df["line_strength_bin"] = pd.cut(df["line_total_strength"], strength_bins, labels=strength_labels)
    df["core_strength_bin"] = pd.cut(df["core_total_strength"], strength_bins, labels=strength_labels)
    df["line_count_bin"] = pd.cut(df["line_count"], count_bins, labels=count_labels)
    df["core_count_bin"] = pd.cut(df["core_count"], count_bins, labels=count_labels)
    df["h1_nearest_distance_bin"] = pd.cut(df["h1_nearest_distance_pips"], distance_bins, labels=distance_labels)
    df["h1_ahead_distance_bin"] = pd.cut(df["h1_ahead_distance_pips"], distance_bins, labels=distance_labels)
    df["h1_nearest_strength_bin"] = pd.cut(df["h1_nearest_total_strength"], strength_bins, labels=strength_labels)
    df["h1_ahead_strength_bin"] = pd.cut(df["h1_ahead_total_strength"], strength_bins, labels=strength_labels)
    df["m5_rsi_bin"] = pd.cut(df["rsi_1"], rsi_bins, labels=rsi_labels)
    df["h1_rsi_bin"] = pd.cut(df["h1_rsi_1"], rsi_bins, labels=rsi_labels)
    df["tp_pips_bin"] = pd.cut(df["tp_pips"], [-0.1, 5, 10, 15, 20, 30, 999], labels=["0-5", "5-10", "10-15", "15-20", "20-30", "30+"])
    df["lc_pips_bin"] = pd.cut(df["lc_pips"], [-0.1, 5, 7.5, 10, 15, 20, 999], labels=["0-5", "5-7.5", "7.5-10", "10-15", "15-20", "20+"])
    df["rr_bin"] = pd.cut(df["rr"], [-0.1, 1, 1.3, 1.6, 2, 999], labels=["<=1.0", "1.0-1.3", "1.3-1.6", "1.6-2.0", "2.0+"])
    return df


def summarize(group):
    filled = group[group["order_result"].ne("not_filled")]
    decided = group[group["order_result"].isin(["tp", "lc"])]
    tp = int(decided["order_result"].eq("tp").sum())
    lc = int(decided["order_result"].eq("lc").sum())
    decided_n = len(decided)
    return pd.Series({
        "orders": len(group),
        "filled": len(filled),
        "decided": decided_n,
        "tp": tp,
        "lc": lc,
        "fill_rate_pct": pct(len(filled) / len(group)) if len(group) else 0,
        "win_rate_pct": pct(tp / decided_n) if decided_n else pd.NA,
        "avg_res_pips": decided["res"].mean() if decided_n else pd.NA,
        "median_max_plus_pips": filled["max_plus_pips"].median() if len(filled) else pd.NA,
        "median_max_minus_pips": filled["max_minus_pips"].median() if len(filled) else pd.NA,
        "avg_elapsed_minutes": decided["elapsed_seconds"].mean() / 60 if decided_n else pd.NA,
    })


def summarize_by(df, fields, min_orders=1):
    if isinstance(fields, str):
        fields = [fields]

    work = df.copy()
    work["_filled"] = work["order_result"].ne("not_filled")
    work["_decided"] = work["order_result"].isin(["tp", "lc"])
    work["_tp"] = work["order_result"].eq("tp")
    work["_lc"] = work["order_result"].eq("lc")
    work["_res_decided"] = work["res"].where(work["_decided"])
    work["_elapsed_decided"] = work["elapsed_seconds"].where(work["_decided"])
    work["_max_plus_filled"] = work["max_plus_pips"].where(work["_filled"])
    work["_max_minus_filled"] = work["max_minus_pips"].where(work["_filled"])

    rows = (
        work.groupby(fields, dropna=False, observed=True)
        .agg(
            orders=("order_result", "size"),
            filled=("_filled", "sum"),
            decided=("_decided", "sum"),
            tp=("_tp", "sum"),
            lc=("_lc", "sum"),
            avg_res_pips=("_res_decided", "mean"),
            median_max_plus_pips=("_max_plus_filled", "median"),
            median_max_minus_pips=("_max_minus_filled", "median"),
            avg_elapsed_minutes=("_elapsed_decided", lambda x: x.mean() / 60),
        )
        .reset_index()
    )
    rows["fill_rate_pct"] = (rows["filled"] / rows["orders"] * 100).round(2)
    rows["win_rate_pct"] = (rows["tp"] / rows["decided"] * 100).round(2)
    rows.loc[rows["decided"].eq(0), "win_rate_pct"] = pd.NA
    rows = rows[rows["orders"] >= min_orders]
    return rows.sort_values(["win_rate_pct", "avg_res_pips", "decided"], ascending=[False, False, False])


def condition_rank(df, fields, min_decided, top=True):
    rows = []
    for size in (2, 3):
        for combo in itertools.combinations(fields, size):
            summary = summarize_by(df, list(combo), min_orders=1)
            summary = summary[summary["decided"] >= min_decided]
            for row in summary.to_dict("records"):
                condition = " / ".join(f"{field}={row[field]}" for field in combo)
                rows.append({
                    "condition": condition,
                    "fields": ",".join(combo),
                    **{k: row[k] for k in summary.columns if k not in combo},
                })

    rank = pd.DataFrame(rows)
    if rank.empty:
        return rank
    return rank.sort_values(
        ["win_rate_pct", "avg_res_pips", "decided"],
        ascending=[not top, not top, False],
    )


def save_report(df, result_path, out_dir, min_decided):
    line_df = df[df["source"].eq("line")].copy()
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = result_path.stem

    factor_fields = [
        "direction_label",
        "line_entry_type",
        "line_strategy",
        "line_side",
        "peak_to_line",
        "session_name",
        "session_bucket",
        "m5_rsi_bin",
        "h1_rsi_bin",
        "h1_nearest_side",
        "h1_nearest_distance_bin",
        "h1_nearest_strength_bin",
        "h1_ahead_side",
        "h1_ahead_distance_bin",
        "h1_ahead_strength_bin",
        "h1_blocks_trade_direction",
        "line_strength_bin",
        "core_strength_bin",
        "line_count_bin",
        "core_count_bin",
        "tp_pips_bin",
        "lc_pips_bin",
        "rr_bin",
    ]

    overview = summarize(line_df).to_frame().T
    by_factor = []
    for field in factor_fields:
        part = summarize_by(line_df, [field])
        part.insert(0, "factor", field)
        part.rename(columns={field: "value"}, inplace=True)
        by_factor.append(part)
    by_factor = pd.concat(by_factor, ignore_index=True) if by_factor else pd.DataFrame()

    combo_fields = [
        "direction_label",
        "line_entry_type",
        "line_side",
        "peak_to_line",
        "session_bucket",
        "m5_rsi_bin",
        "h1_rsi_bin",
        "h1_nearest_distance_bin",
        "h1_ahead_distance_bin",
        "h1_blocks_trade_direction",
        "line_strength_bin",
        "core_strength_bin",
        "line_count_bin",
        "core_count_bin",
        "tp_pips_bin",
        "lc_pips_bin",
        "rr_bin",
    ]
    top_conditions = condition_rank(line_df, combo_fields, min_decided, top=True)
    worst_conditions = condition_rank(line_df, combo_fields, min_decided, top=False)

    paths = {
        "overview": out_dir / f"{stem}_eurusd_line_overview.csv",
        "by_factor": out_dir / f"{stem}_eurusd_line_by_factor.csv",
        "top_conditions": out_dir / f"{stem}_eurusd_line_top_conditions.csv",
        "worst_conditions": out_dir / f"{stem}_eurusd_line_worst_conditions.csv",
    }
    overview.to_csv(paths["overview"], index=False, encoding="utf-8")
    by_factor.to_csv(paths["by_factor"], index=False, encoding="utf-8")
    top_conditions.head(100).to_csv(paths["top_conditions"], index=False, encoding="utf-8")
    worst_conditions.head(100).to_csv(paths["worst_conditions"], index=False, encoding="utf-8")
    return paths, overview, by_factor, top_conditions, worst_conditions


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pair", default=DEFAULT_PAIR)
    parser.add_argument("--path", default=None)
    parser.add_argument("--out-dir", default=None)
    parser.add_argument("--min-decided", type=int, default=30)
    args = parser.parse_args()

    result_path = Path(args.path) if args.path else find_latest_result(args.pair)
    out_dir = Path(args.out_dir) if args.out_dir else result_path.parent

    df = pd.read_csv(result_path)
    df = add_bins(df, args.pair)
    paths, overview, by_factor, top_conditions, worst_conditions = save_report(
        df,
        result_path,
        out_dir,
        args.min_decided,
    )

    print("Source:", result_path)
    print("Overview")
    print(overview.to_string(index=False))
    print("\nSaved reports:")
    for label, path in paths.items():
        print(label + ":", path)
    if not top_conditions.empty:
        print("\nTop conditions")
        print(top_conditions.head(10)[["condition", "orders", "decided", "win_rate_pct", "avg_res_pips"]].to_string(index=False))
    if not worst_conditions.empty:
        print("\nWorst conditions")
        print(worst_conditions.head(10)[["condition", "orders", "decided", "win_rate_pct", "avg_res_pips"]].to_string(index=False))


if __name__ == "__main__":
    main()
