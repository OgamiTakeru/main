import argparse
import itertools
from pathlib import Path

import numpy as np
import pandas as pd


PAIRS = ("USD_JPY", "EUR_USD", "AUD_USD")
DEFAULT_LOG_DIR = Path("C:/Users/taker/OneDrive/Desktop/oanda_logs")
REQUIRED_NEW_COLUMNS = {
    "latest_peak_rsi",
    "previous_peak_rsi",
    "line_peak_rsi_avg",
    "line_peak_rsi_latest",
}


def numeric(series, default=np.nan):
    if series is None:
        return default
    return pd.to_numeric(series, errors="coerce")


def col(df, name, default=np.nan):
    if name in df.columns:
        return df[name]
    return pd.Series(default, index=df.index)


def bin_series(series, bins, labels):
    values = numeric(series)
    return pd.cut(values, bins=bins, labels=labels, include_lowest=True).astype("object")


def rsi_bin(series):
    return bin_series(
        series,
        [-0.1, 30, 40, 50, 60, 67.5, 100],
        ["<=30", "30-40", "40-50", "50-60", "60-67.5", "67.5+"],
    )


def pips_bin(series):
    return bin_series(
        series,
        [-0.1, 3, 5, 8, 10, 15, 20, 30, 999999],
        ["0-3p", "3-5p", "5-8p", "8-10p", "10-15p", "15-20p", "20-30p", "30p+"],
    )


def path_pips_bin(series):
    return bin_series(
        series,
        [-0.1, 3, 6, 10, 15, 20, 30, 50, 999999],
        ["0-3p", "3-6p", "6-10p", "10-15p", "15-20p", "20-30p", "30-50p", "50+p"],
    )


def strength_bin(series):
    return bin_series(
        series,
        [-0.1, 5, 8, 10, 15, 20, 999999],
        ["0-5", "5-8", "8-10", "10-15", "15-20", "20+"],
    )


def count_bin(series):
    return bin_series(
        series,
        [-0.1, 1, 2, 3, 5, 999999],
        ["1", "2", "3", "4-5", "6+"],
    )


def session_bucket(series):
    hour = numeric(series)
    result = pd.Series(np.nan, index=series.index, dtype="object")
    result[(hour >= 0) & (hour <= 5)] = "00-05"
    result[(hour >= 6) & (hour <= 8)] = "06-08"
    result[(hour >= 9) & (hour <= 14)] = "09-14"
    result[(hour >= 15) & (hour <= 20)] = "15-20"
    result[(hour >= 21) & (hour <= 23)] = "21-23"
    return result


def direction_label(series):
    direction = numeric(series)
    result = pd.Series(np.nan, index=series.index, dtype="object")
    result[direction == 1] = "buy"
    result[direction == -1] = "sell"
    return result


def peak_rsi_direction_ok(df):
    direction = numeric(col(df, "direction"))
    latest = numeric(col(df, "latest_peak_rsi"))
    previous = numeric(col(df, "previous_peak_rsi"))
    low_rsi = pd.concat([latest, previous], axis=1).min(axis=1)
    high_rsi = pd.concat([latest, previous], axis=1).max(axis=1)
    return ((direction == 1) & (low_rsi <= 30)) | ((direction == -1) & (high_rsi >= 67.5))


def breakout_peak_rsi_ok(df):
    direction = numeric(col(df, "direction"))
    latest = numeric(col(df, "latest_peak_rsi"))
    previous = numeric(col(df, "previous_peak_rsi"))
    buy_ok = (direction == 1) & (latest >= 50) & (previous.isna() | (latest >= previous - 5))
    sell_ok = (direction == -1) & (latest <= 50) & (previous.isna() | (latest <= previous + 5))
    return buy_ok | sell_ok


def breakout_line_rsi_ok(df):
    direction = numeric(col(df, "direction"))
    latest = numeric(col(df, "line_peak_rsi_latest"))
    average = numeric(col(df, "line_peak_rsi_avg"))
    high = pd.concat([latest, average], axis=1).max(axis=1)
    low = pd.concat([latest, average], axis=1).min(axis=1)
    return ((direction == 1) & (high >= 50)) | ((direction == -1) & (low <= 50))


def current_rsi_breakout_ok(df):
    direction = numeric(col(df, "direction"))
    rsi1 = numeric(col(df, "rsi_1"))
    rsi2 = numeric(col(df, "rsi_2"))
    return ((direction == 1) & (rsi1 >= 40) & (rsi1 <= 67.5) & (rsi1 >= rsi2)) | (
        (direction == -1) & (rsi1 >= 30) & (rsi1 <= 60) & (rsi1 <= rsi2)
    )


def line_side_matches_direction(df):
    direction = numeric(col(df, "direction"))
    side = col(df, "line_side")
    return ((direction == 1) & (side == "upper")) | ((direction == -1) & (side == "lower"))


def immediate_path_blocked(df):
    distance = numeric(col(df, "h1_path_ahead_1_distance_pips"))
    strength = numeric(col(df, "h1_path_ahead_1_total_strength"))
    return (distance > 0) & (distance < 3) & (strength >= 10)


def add_new_flow_columns(df):
    df = df.copy()
    df = df[col(df, "source").eq("line")].copy()
    if "latest_peak_rsi" not in df.columns:
        df["latest_peak_rsi"] = col(df, "rsi_1")
    if "previous_peak_rsi" not in df.columns:
        df["previous_peak_rsi"] = col(df, "rsi_2")
    if "line_peak_rsi_avg" not in df.columns:
        df["line_peak_rsi_avg"] = np.nan
    if "line_peak_rsi_latest" not in df.columns:
        df["line_peak_rsi_latest"] = np.nan
    df["direction_label"] = direction_label(col(df, "direction"))
    df["session_bucket"] = session_bucket(col(df, "session_hour"))
    df["distance_bin"] = pips_bin(col(df, "target_distance_pips", col(df, "distance_pips")))
    df["path1_distance_bin"] = path_pips_bin(col(df, "h1_path_ahead_1_distance_pips"))
    df["line_strength_bin"] = strength_bin(col(df, "line_total_strength"))
    df["core_strength_bin"] = strength_bin(col(df, "core_total_strength"))
    df["path1_strength_bin"] = strength_bin(col(df, "h1_path_ahead_1_total_strength"))
    df["h1_nearest_strength_bin"] = strength_bin(col(df, "h1_nearest_total_strength"))
    df["previous_m5_strength_bin"] = strength_bin(col(df, "m5_previous_peak_line_total_strength"))
    df["previous_h1_strength_bin"] = strength_bin(col(df, "h1_previous_peak_line_total_strength"))
    df["latest_peak_rsi_bin"] = rsi_bin(col(df, "latest_peak_rsi"))
    df["previous_peak_rsi_bin"] = rsi_bin(col(df, "previous_peak_rsi"))
    df["line_peak_rsi_latest_bin"] = rsi_bin(col(df, "line_peak_rsi_latest"))
    df["line_peak_rsi_avg_bin"] = rsi_bin(col(df, "line_peak_rsi_avg"))
    df["m5_rsi_bin"] = rsi_bin(col(df, "rsi_1"))
    df["h1_rsi_bin"] = rsi_bin(col(df, "h1_rsi_1"))
    df["line_count_bin"] = count_bin(col(df, "line_count"))
    df["core_count_bin"] = count_bin(col(df, "core_count"))
    df["peak_rsi_direction_ok"] = peak_rsi_direction_ok(df)
    df["breakout_peak_rsi_ok"] = breakout_peak_rsi_ok(df)
    df["breakout_line_rsi_ok"] = breakout_line_rsi_ok(df)
    df["current_rsi_breakout_ok"] = current_rsi_breakout_ok(df)
    df["direction_side_ok"] = line_side_matches_direction(df)

    distance = numeric(col(df, "target_distance_pips", col(df, "distance_pips")))
    previous_strength = numeric(col(df, "previous_peak_strength"))
    line_count = numeric(col(df, "line_count"))
    core_count = numeric(col(df, "core_count"))
    line_strength = numeric(col(df, "line_total_strength"))
    latest_peak_dir = numeric(col(df, "latest_peak_dir"))
    direction = numeric(col(df, "direction"))
    entry_type = col(df, "line_entry_type")
    immediate = (
        entry_type.eq("breakout")
        & df["direction_side_ok"]
        & latest_peak_dir.eq(direction)
        & (distance <= 3)
        & df["current_rsi_breakout_ok"]
        & (previous_strength >= 5)
        & ((line_count >= 2) | (core_count >= 2) | (line_strength >= 10))
        & (df["breakout_peak_rsi_ok"] | df["breakout_line_rsi_ok"])
        & ~immediate_path_blocked(df)
    )
    future_resist = entry_type.eq("reversal") & df["peak_rsi_direction_ok"]
    future_break = (
        entry_type.eq("breakout")
        & df["direction_side_ok"]
        & latest_peak_dir.eq(direction)
        & (df["breakout_peak_rsi_ok"] | df["breakout_line_rsi_ok"])
    )

    df["new_flow_type"] = "filtered_out"
    df.loc[future_resist, "new_flow_type"] = "future_resist"
    df.loc[future_break & ~immediate, "new_flow_type"] = "future_break"
    df.loc[immediate, "new_flow_type"] = "immediate"
    return df


def summarise(group):
    order_result = group["order_result"].fillna("")
    filled = ~order_result.eq("not_filled")
    tp = order_result.eq("tp")
    lc = order_result.eq("lc")
    res = numeric(group.get("res")).fillna(0)
    closed_res = numeric(group.get("res")).dropna()
    return pd.Series(
        {
            "n": len(group),
            "filled": int(filled.sum()),
            "fill_rate": round(float(filled.mean()), 4),
            "tp_rate_all": round(float(tp.mean()), 4),
            "tp_rate_filled": round(float(tp[filled].mean()), 4) if filled.any() else np.nan,
            "lc_rate_filled": round(float(lc[filled].mean()), 4) if filled.any() else np.nan,
            "expectancy_all": round(float(res.mean()), 3),
            "avg_res_closed": round(float(closed_res.mean()), 3) if len(closed_res) else np.nan,
            "median_res_closed": round(float(closed_res.median()), 3) if len(closed_res) else np.nan,
            "avg_max_plus": round(float(numeric(group.get("max_plus_pips")).mean()), 3),
            "avg_max_minus": round(float(numeric(group.get("max_minus_pips")).mean()), 3),
        }
    )


def filter_text(fields, values):
    parts = []
    for field, value in zip(fields, values):
        parts.append(f"{field}={value}")
    return "; ".join(parts)


def mine_top_conditions(df, pair, flow_type, min_count, top_n):
    fields_by_flow = {
        "immediate": [
            "session_bucket",
            "direction_label",
            "line_side",
            "distance_bin",
            "line_strength_bin",
            "line_count_bin",
            "core_count_bin",
            "latest_peak_rsi_bin",
            "previous_peak_rsi_bin",
            "line_peak_rsi_latest_bin",
            "line_peak_rsi_avg_bin",
            "path1_distance_bin",
            "path1_strength_bin",
            "h1_nearest_strength_bin",
        ],
        "future_resist": [
            "session_bucket",
            "direction_label",
            "line_side",
            "distance_bin",
            "path1_distance_bin",
            "line_strength_bin",
            "core_strength_bin",
            "path1_strength_bin",
            "h1_nearest_strength_bin",
            "previous_m5_strength_bin",
            "previous_h1_strength_bin",
            "latest_peak_rsi_bin",
            "previous_peak_rsi_bin",
            "line_peak_rsi_latest_bin",
            "line_peak_rsi_avg_bin",
            "line_count_bin",
            "core_count_bin",
            "line_history_is_flipped",
            "h1_blocks_trade_direction",
        ],
        "future_break": [
            "session_bucket",
            "direction_label",
            "line_side",
            "distance_bin",
            "path1_distance_bin",
            "line_strength_bin",
            "core_strength_bin",
            "path1_strength_bin",
            "h1_nearest_strength_bin",
            "latest_peak_rsi_bin",
            "previous_peak_rsi_bin",
            "line_peak_rsi_latest_bin",
            "line_peak_rsi_avg_bin",
            "line_count_bin",
            "core_count_bin",
            "line_history_is_flipped",
            "h1_blocks_trade_direction",
        ],
    }
    work = df[df["new_flow_type"].eq(flow_type)].copy()
    if work.empty:
        return pd.DataFrame()

    fields = [field for field in fields_by_flow[flow_type] if field in work.columns]
    results = []
    for size in (1, 2, 3):
        for combo in itertools.combinations(fields, size):
            grouped_source = work.dropna(subset=list(combo))
            if grouped_source.empty:
                continue
            grouped = grouped_source.groupby(list(combo), dropna=False)
            summary = grouped.apply(summarise, include_groups=False).reset_index()
            if "n" not in summary.columns:
                continue
            summary = summary[summary["n"] >= min_count].copy()
            if summary.empty:
                continue
            summary["pair"] = pair
            summary["flow_type"] = flow_type
            summary["filters"] = [
                filter_text(combo, row)
                for row in summary[list(combo)].astype("object").itertuples(index=False, name=None)
            ]
            summary["condition_size"] = size
            results.append(
                summary[
                    [
                        "pair",
                        "flow_type",
                        "condition_size",
                        "filters",
                        "n",
                        "filled",
                        "fill_rate",
                        "tp_rate_all",
                        "tp_rate_filled",
                        "lc_rate_filled",
                        "expectancy_all",
                        "avg_res_closed",
                        "median_res_closed",
                        "avg_max_plus",
                        "avg_max_minus",
                    ]
                ]
            )

    if not results:
        return pd.DataFrame()

    mined = pd.concat(results, ignore_index=True)
    mined = mined.sort_values(
        ["expectancy_all", "tp_rate_filled", "n", "condition_size"],
        ascending=[False, False, False, True],
    )
    mined = mined.drop_duplicates(subset=["flow_type", "filters"]).head(top_n).copy()
    mined.insert(2, "rank", range(1, len(mined) + 1))
    mined["label"] = mined.apply(
        lambda row: f"{row['pair']} {row['flow_type']} Top{row['rank']} {row['filters']}",
        axis=1,
    )
    return mined


def latest_result_csv(log_dir, pair):
    candidates = sorted(
        log_dir.glob(f"result_{pair}_*.csv"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise FileNotFoundError(f"No result CSV found for {pair} in {log_dir}")
    for candidate in candidates:
        try:
            columns = set(pd.read_csv(candidate, nrows=0).columns)
        except Exception:
            continue
        if REQUIRED_NEW_COLUMNS.issubset(columns):
            return candidate
    return candidates[0]


def analyse_pair(pair, path, min_count, top_n):
    df = pd.read_csv(path)
    if "pair" in df.columns:
        df = df[df["pair"].eq(pair)].copy()
    df = add_new_flow_columns(df)

    summaries = []
    for flow_type in ("immediate", "future_resist", "future_break"):
        top = mine_top_conditions(df, pair, flow_type, min_count, top_n)
        if not top.empty:
            summaries.append(top)

    if not summaries:
        return pd.DataFrame(), df

    result = pd.concat(summaries, ignore_index=True)
    result.insert(0, "source_file", str(path))
    return result, df


def main():
    parser = argparse.ArgumentParser(description="Mine new-flow Top10 line-order conditions.")
    parser.add_argument("--pair", choices=PAIRS + ("ALL",), default="ALL")
    parser.add_argument("--csv", type=Path, help="Use a specific result CSV. Only valid with one pair.")
    parser.add_argument("--log-dir", type=Path, default=DEFAULT_LOG_DIR)
    parser.add_argument("--min-count", type=int, default=20)
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_LOG_DIR)
    args = parser.parse_args()

    pairs = PAIRS if args.pair == "ALL" else (args.pair,)
    if args.csv is not None and len(pairs) != 1:
        raise ValueError("--csv can be used only when --pair is one currency pair.")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    all_results = []
    for pair in pairs:
        path = args.csv if args.csv is not None else latest_result_csv(args.log_dir, pair)
        result, tagged = analyse_pair(pair, path, args.min_count, args.top)
        flow_counts = tagged["new_flow_type"].value_counts(dropna=False).to_dict()
        print(f"\n{pair}: {path}")
        print("new_flow_type counts:", flow_counts)
        if result.empty:
            print("No Top10 conditions. Try smaller --min-count.")
            continue

        output_path = args.output_dir / f"line_new_top10_{pair}_{path.stem.replace('result_' + pair + '_', '')}.csv"
        result.to_csv(output_path, index=False, encoding="utf-8-sig")
        print(result[["flow_type", "rank", "filters", "n", "tp_rate_filled", "expectancy_all"]].to_string(index=False))
        print("saved:", output_path)
        all_results.append(result)

    if all_results:
        combined = pd.concat(all_results, ignore_index=True)
        combined_path = args.output_dir / "line_new_top10_ALL.csv"
        combined.to_csv(combined_path, index=False, encoding="utf-8-sig")
        print("\ncombined saved:", combined_path)


if __name__ == "__main__":
    main()
