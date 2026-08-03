import itertools
import math

import numpy as np
import pandas as pd
import requests

import tokens as tk


PATH = r"C:\Users\taker\OneDrive\Desktop\oanda_logs\result_AUD_USD_20250624000000_20260624000000.csv"
OUT_PATH = "audusd_walk_forward_top10.csv"
CUTOFF = pd.Timestamp("2026-03-24 00:00:00")


def value_bin(series, bins, labels):
    return pd.cut(
        pd.to_numeric(series, errors="coerce"),
        bins=bins,
        labels=labels,
    )


def prepare(rows):
    rows = rows[rows["source"].eq("line")].copy()
    rows["dt"] = pd.to_datetime(rows["target_time"], errors="coerce")
    rows["filled"] = ~rows["actual_order_result"].eq("not_filled")
    rows["decided"] = rows["actual_order_result"].isin(["tp", "lc"])
    rows["win"] = rows["actual_order_result"].eq("tp")
    rows["result_pips"] = pd.to_numeric(rows["actual_res"], errors="coerce").where(
        rows["decided"], 0
    ).fillna(0)

    rows["direction_label"] = rows["direction"].map({1: "buy", -1: "sell"})
    rows["line_side_filter"] = rows["line_side"]
    rows["line_entry_type_filter"] = rows["line_entry_type"]
    rows["session_bucket"] = value_bin(
        rows["dt"].dt.hour,
        [-1, 5, 8, 14, 20, 23],
        ["00-05", "06-08", "09-14", "15-20", "21-23"],
    )
    rsi_bins = [-0.1, 30, 40, 50, 60, 67.5, 100]
    rsi_labels = ["<=30", "30-40", "40-50", "50-60", "60-67.5", "67.5+"]
    for source, target in (
        ("rsi_1", "m5_rsi_bin"),
        ("h1_rsi_1", "h1_rsi_bin"),
        ("latest_peak_rsi", "latest_peak_rsi_bin"),
        ("previous_peak_rsi", "previous_peak_rsi_bin"),
    ):
        rows[target] = value_bin(rows[source], rsi_bins, rsi_labels)

    strength_bins = [-0.1, 5, 8, 10, 15, 20, 10**9]
    strength_labels = ["0-5", "5-8", "8-10", "10-15", "15-20", "20+"]
    for source, target in (
        ("line_total_strength", "line_strength_bin"),
        ("core_total_strength", "core_strength_bin"),
        ("h1_path_ahead_1_total_strength", "path1_strength_bin"),
        ("h1_nearest_total_strength", "h1_nearest_strength_bin"),
    ):
        rows[target] = value_bin(rows[source], strength_bins, strength_labels)

    rows["path1_distance_bin"] = value_bin(
        rows["h1_path_ahead_1_distance_pips"],
        [-0.1, 3, 6, 10, 15, 20, 30, 50, 10**9],
        ["0-3p", "3-6p", "6-10p", "10-15p", "15-20p", "20-30p", "30-50p", "50+p"],
    )
    rows["role_change"] = rows["line_is_flipped"].astype("boolean")
    return rows


FIELDS = [
    "direction_label",
    "line_side_filter",
    "line_entry_type_filter",
    "session_bucket",
    "m5_rsi_bin",
    "h1_rsi_bin",
    "latest_peak_rsi_bin",
    "previous_peak_rsi_bin",
    "line_strength_bin",
    "core_strength_bin",
    "path1_strength_bin",
    "h1_nearest_strength_bin",
    "path1_distance_bin",
    "role_change",
]

FILTER_NAMES = {
    "line_side_filter": "line_side",
    "line_entry_type_filter": "line_entry_type",
}


def baseline(rows):
    decided = rows[rows["decided"]]
    return {
        "generated": len(rows),
        "fill_rate": rows["filled"].mean(),
        "decided": len(decided),
        "win_rate": decided["win"].mean(),
        "avg_pips": decided["result_pips"].mean(),
        "ev_signal": decided["result_pips"].sum() / len(rows),
    }


def build_candidates(rows):
    train = rows["dt"] < CUTOFF
    test = ~train
    work = rows.copy()
    for period, mask in (("train", train), ("test", test)):
        work[f"{period}_generated"] = mask.astype("int8")
        work[f"{period}_filled"] = (mask & work["filled"]).astype("int8")
        work[f"{period}_decided"] = (mask & work["decided"]).astype("int8")
        work[f"{period}_wins"] = (mask & work["win"]).astype("int8")
        work[f"{period}_result"] = work["result_pips"].where(mask, 0)

    candidates = []
    aggregations = {
        "full_generated": ("actual_order_result", "size"),
        "full_filled": ("filled", "sum"),
        "full_decided": ("decided", "sum"),
        "full_wins": ("win", "sum"),
        "full_result": ("result_pips", "sum"),
    }
    for period in ("train", "test"):
        for metric in ("generated", "filled", "decided", "wins", "result"):
            aggregations[f"{period}_{metric}"] = (f"{period}_{metric}", "sum")

    for size in (2, 3):
        for columns in itertools.combinations(FIELDS, size):
            grouped = (
                work.groupby(list(columns), observed=True, dropna=True)
                .agg(**aggregations)
                .reset_index()
            )
            for period in ("full", "train", "test"):
                grouped[f"{period}_fill_rate"] = (
                    grouped[f"{period}_filled"] / grouped[f"{period}_generated"]
                )
                grouped[f"{period}_win_rate"] = (
                    grouped[f"{period}_wins"] / grouped[f"{period}_decided"]
                )
                grouped[f"{period}_avg_pips"] = (
                    grouped[f"{period}_result"] / grouped[f"{period}_decided"]
                )
                grouped[f"{period}_ev_signal"] = (
                    grouped[f"{period}_result"] / grouped[f"{period}_generated"]
                )
            qualified = grouped[
                (grouped["full_generated"] >= 400)
                & (grouped["full_decided"] >= 120)
                & (grouped["train_generated"] >= 250)
                & (grouped["train_decided"] >= 75)
                & (grouped["test_generated"] >= 100)
                & (grouped["test_decided"] >= 30)
                & (grouped["train_avg_pips"] > 0)
                & (grouped["test_avg_pips"] > 0)
                & (grouped["train_ev_signal"] > 0)
                & (grouped["test_ev_signal"] > 0)
            ].copy()
            if qualified.empty:
                continue
            qualified["score"] = (
                qualified[["train_ev_signal", "test_ev_signal"]].min(axis=1)
                * np.log1p(qualified["test_decided"])
                * (0.5 + qualified["test_fill_rate"].clip(upper=0.8))
            )
            for record in qualified.to_dict("records"):
                filters = [
                    (FILTER_NAMES.get(column, column), record[column])
                    for column in columns
                ]
                record["filters"] = filters
                record["condition"] = " / ".join(
                    f"{field}={value}" for field, value in filters
                )
                candidates.append(record)
    return sorted(candidates, key=lambda row: row["score"], reverse=True)


def select_diverse(ranked):
    def canonical(filters):
        normalized = set()
        for field, value in filters:
            if (field, value) == ("line_side", "lower"):
                normalized.add(("direction_label", "sell"))
            elif (field, value) == ("line_side", "upper"):
                normalized.add(("direction_label", "buy"))
            else:
                normalized.add((field, value))
        return normalized

    selected = []
    for row in ranked:
        current = canonical(row["filters"])
        if any(
            len(current & canonical(prior["filters"]))
            / min(len(current), len(canonical(prior["filters"])))
            >= 2 / 3
            for prior in selected
        ):
            continue
        selected.append(row)
        if len(selected) == 10:
            break
    return selected


def main():
    rows = prepare(pd.read_csv(PATH))
    train = rows[rows["dt"] < CUTOFF]
    test = rows[rows["dt"] >= CUTOFF]
    top = select_diverse(build_candidates(rows))
    output = pd.DataFrame(
        [
            {
                "rank": index,
                "condition": row["condition"],
                "score": row["score"],
                **{
                    key: row[key]
                    for key in row
                    if key.startswith(("full_", "train_", "test_"))
                    and not key.endswith("_result")
                },
            }
            for index, row in enumerate(top, 1)
        ]
    )
    output.to_csv(OUT_PATH, index=False, encoding="utf-8-sig")

    all_stats = baseline(rows)
    train_stats = baseline(train)
    test_stats = baseline(test)
    lines = [
        "AUD/USD 1年walk-forward条件 TOP10",
        "期間 2025/06/24〜2026/06/24、分割 2026/03/24",
        "実装と同一のRSI・強度・距離ビン。注文前に確定する情報のみ使用。",
        (
            f"全体: signal={all_stats['generated']:,} fill={all_stats['fill_rate']*100:.1f}% "
            f"win={all_stats['win_rate']*100:.1f}% avg={all_stats['avg_pips']:+.2f}p "
            f"EV/signal={all_stats['ev_signal']:+.3f}p"
        ),
        (
            f"前半avg={train_stats['avg_pips']:+.2f}p EV={train_stats['ev_signal']:+.3f}p / "
            f"後半avg={test_stats['avg_pips']:+.2f}p EV={test_stats['ev_signal']:+.3f}p"
        ),
        "",
    ]
    for index, row in enumerate(top, 1):
        lines += [
            f"#{index} {row['condition']}",
            (
                f"全体 n={int(row['full_generated']):,} fill={row['full_fill_rate']*100:.1f}% "
                f"win={row['full_win_rate']*100:.1f}% avg={row['full_avg_pips']:+.2f}p "
                f"EV={row['full_ev_signal']:+.3f}p"
            ),
            (
                f"後半 n={int(row['test_generated']):,} fill={row['test_fill_rate']*100:.1f}% "
                f"win={row['test_win_rate']*100:.1f}% avg={row['test_avg_pips']:+.2f}p "
                f"EV={row['test_ev_signal']:+.3f}p"
            ),
        ]
    message = "\n".join(lines)
    print(message)
    for start in range(0, len(message), 1800):
        response = requests.post(
            tk.WEBHOOK_URL_inspection,
            json={"content": message[start : start + 1800]},
            timeout=15,
        )
        response.raise_for_status()
        print("Discord status:", response.status_code)


if __name__ == "__main__":
    main()
