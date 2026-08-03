import os

import pandas as pd
import requests

import tokens as tk


ROOT = r"C:\Users\taker\OneDrive\Desktop\oanda_logs"
PAIRS = ("USD_JPY", "EUR_USD", "AUD_USD")
CUTOFF = pd.Timestamp("2026-03-24 00:00:00")
BINS = [
    "31-60m", "61-180m", "181-360m", "361-720m", "721-1440m",
    "1441-2880m", "2881-4320m", "4321-7200m", "7201-10080m",
    "10081-15000m", "15001m+", "no_touch_in_history",
]


def metrics(group):
    decided = group[group["decided"]]
    return pd.Series(
        {
            "orders": len(group),
            "filled": int(group["filled"].sum()),
            "decided": len(decided),
            "wins": int(decided["win"].sum()),
            "fill_rate": group["filled"].mean(),
            "win_rate": decided["win"].mean(),
            "avg_pips": decided["actual_res"].mean(),
            "ev_signal": decided["actual_res"].sum() / len(group) if len(group) else None,
        }
    )


def load(pair):
    path = os.path.join(ROOT, f"result_{pair}_20250624000000_20260624000000.csv")
    cols = [
        "source", "target_time", "direction", "line_order_mode",
        "actual_order_result", "actual_res", "tp_last_touch_elapsed_bin",
    ]
    rows = pd.read_csv(path, usecols=cols)
    rows = rows[rows["source"].eq("line")].copy()
    rows["dt"] = pd.to_datetime(rows["target_time"], errors="coerce")
    rows["elapsed_bin"] = pd.Categorical(
        rows["tp_last_touch_elapsed_bin"].fillna("no_touch_in_history"),
        categories=BINS,
        ordered=True,
    )
    rows["actual_res"] = pd.to_numeric(rows["actual_res"], errors="coerce")
    rows["filled"] = ~rows["actual_order_result"].eq("not_filled")
    rows["decided"] = rows["actual_order_result"].isin(["tp", "lc"])
    rows["win"] = rows["actual_order_result"].eq("tp")
    rows["period"] = rows["dt"].ge(CUTOFF).map({False: "train", True: "test"})
    return rows


def main():
    all_rows = []
    detail_rows = []
    message = [
        "TP最終到達経過時間 walk-forward解析",
        "期間 2025/06/24〜2026/06/24、後半開始 2026/03/24",
        "採用候補=前後ともEV/signal>0、後半100注文・30決着以上。",
    ]
    for pair in PAIRS:
        rows = load(pair)
        table = (
            rows.groupby(["elapsed_bin", "period"], observed=True)
            .apply(metrics, include_groups=False)
            .reset_index()
        )
        table.insert(0, "pair", pair)
        all_rows.append(table)

        direction_table = (
            rows.groupby(["elapsed_bin", "direction", "period"], observed=True)
            .apply(metrics, include_groups=False)
            .reset_index()
        )
        direction_table.insert(0, "pair", pair)
        detail_rows.append(direction_table)

        pivot = table.pivot(index="elapsed_bin", columns="period")
        message += ["", f"【{pair}】"]
        for elapsed_bin in BINS:
            if elapsed_bin not in pivot.index:
                continue
            try:
                train_ev = pivot.loc[elapsed_bin, ("ev_signal", "train")]
                test_ev = pivot.loc[elapsed_bin, ("ev_signal", "test")]
                test_n = int(pivot.loc[elapsed_bin, ("orders", "test")])
                test_decided = int(pivot.loc[elapsed_bin, ("decided", "test")])
                test_fill = pivot.loc[elapsed_bin, ("fill_rate", "test")]
                test_win = pivot.loc[elapsed_bin, ("win_rate", "test")]
                test_avg = pivot.loc[elapsed_bin, ("avg_pips", "test")]
            except KeyError:
                continue
            stable = (
                train_ev > 0 and test_ev > 0 and test_n >= 100 and test_decided >= 30
            )
            mark = "◎" if stable else "×"
            message.append(
                f"{mark}{elapsed_bin}: test n={test_n} fill={test_fill*100:.1f}% "
                f"win={test_win*100:.1f}% avg={test_avg:+.2f}p "
                f"EV train/test={train_ev:+.3f}/{test_ev:+.3f}"
            )

    summary = pd.concat(all_rows, ignore_index=True)
    detail = pd.concat(detail_rows, ignore_index=True)
    summary.to_csv("tp_touch_walk_forward_summary.csv", index=False, encoding="utf-8-sig")
    detail.to_csv("tp_touch_walk_forward_direction.csv", index=False, encoding="utf-8-sig")

    text = "\n".join(message)
    print(text)
    for start in range(0, len(text), 1800):
        response = requests.post(
            tk.WEBHOOK_URL_inspection,
            json={"content": text[start : start + 1800]},
            timeout=15,
        )
        response.raise_for_status()
        print("Discord status:", response.status_code)


if __name__ == "__main__":
    main()
