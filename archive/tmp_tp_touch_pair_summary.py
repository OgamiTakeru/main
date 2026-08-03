import os

import pandas as pd
import requests

import tokens as tk


ROOT = r"C:\Users\taker\OneDrive\Desktop\oanda_logs"
PAIRS = ("USD_JPY", "EUR_USD", "AUD_USD")
BINS = [
    "31-60m",
    "61-180m",
    "181-360m",
    "361-720m",
    "721-1440m",
    "1441-2880m",
    "2881-4320m",
    "4321-7200m",
    "7201-10080m",
    "10081-15000m",
    "15001m+",
    "no_touch_in_history",
]


def summarize(pair):
    path = os.path.join(
        ROOT, f"result_{pair}_20250624000000_20260624000000.csv"
    )
    columns = [
        "source",
        "target_time",
        "actual_order_result",
        "actual_res",
        "tp_last_touch_elapsed_bin",
        "tp_last_touch_found",
        "tp_touch_history_coverage_minutes",
    ]
    rows = pd.read_csv(path, usecols=columns)
    rows = rows[rows["source"].eq("line")].copy()
    rows["actual_res"] = pd.to_numeric(rows["actual_res"], errors="coerce")
    rows["elapsed_bin"] = pd.Categorical(
        rows["tp_last_touch_elapsed_bin"].fillna("no_touch_in_history"),
        categories=BINS,
        ordered=True,
    )
    rows["filled"] = ~rows["actual_order_result"].eq("not_filled")
    rows["decided"] = rows["actual_order_result"].isin(["tp", "lc"])
    rows["win"] = rows["actual_order_result"].eq("tp")
    rows["result_pips"] = rows["actual_res"].where(rows["decided"])

    grouped = rows.groupby("elapsed_bin", observed=True).agg(
        orders=("actual_order_result", "size"),
        filled=("filled", "sum"),
        decided=("decided", "sum"),
        wins=("win", "sum"),
        average_pips=("result_pips", "mean"),
    )
    grouped["fill_rate"] = grouped["filled"] / grouped["orders"]
    grouped["win_rate_after_fill"] = grouped["wins"] / grouped["decided"]
    grouped["ev_per_signal"] = (
        grouped["average_pips"] * grouped["decided"] / grouped["orders"]
    )
    grouped.insert(0, "pair", pair)
    return rows, grouped.reset_index()


def main():
    summaries = []
    totals = []
    for pair in PAIRS:
        rows, summary = summarize(pair)
        summaries.append(summary)
        decided = rows[rows["decided"]]
        totals.append(
            {
                "pair": pair,
                "orders": len(rows),
                "fill_rate": rows["filled"].mean(),
                "decided": len(decided),
                "win_rate": decided["win"].mean(),
                "average_pips": decided["actual_res"].mean(),
            }
        )
    combined = pd.concat(summaries, ignore_index=True)
    combined.to_csv(
        "tp_last_touch_pair_summary.csv", index=False, encoding="utf-8-sig"
    )
    totals = pd.DataFrame(totals).set_index("pair")

    lines = [
        "TP価格の最終到達からの経過時間：通貨別1年集計",
        "期間 2025/06/24〜2026/06/24。actual結果・スプレッド込み。",
        "約定率=not_filled以外/全注文。約定後勝率=TP/(TP+LC)。",
        "",
        "【全体】",
    ]
    for pair, row in totals.iterrows():
        lines.append(
            f"{pair}: n={int(row['orders']):,} fill={row['fill_rate']*100:.1f}% "
            f"win={row['win_rate']*100:.1f}% avg={row['average_pips']:+.2f}p"
        )
    for pair in PAIRS:
        lines += ["", f"【{pair}】"]
        pair_rows = combined[combined["pair"].eq(pair)]
        for _, row in pair_rows.iterrows():
            lines.append(
                f"{row['elapsed_bin']}: n={int(row['orders']):,} "
                f"fill={row['fill_rate']*100:.1f}% "
                f"win={row['win_rate_after_fill']*100:.1f}% "
                f"avg={row['average_pips']:+.2f}p"
            )

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
