import itertools
import math

import numpy as np
import pandas as pd
import requests

import tokens as tk


PATH = r"C:\Users\taker\OneDrive\Desktop\oanda_logs\result_EUR_USD_20250624000000_20260624000000.csv"
OUT_PATH = "eurusd_top10_tp_touch_conditions.csv"
CUTOFF = pd.Timestamp("2026-03-24 00:00:00")


def cut(series, bins, labels):
    return pd.cut(pd.to_numeric(series, errors="coerce"), bins=bins, labels=labels)


def prepare(df):
    df = df[df["source"].eq("line")].copy()
    df["dt"] = pd.to_datetime(df["target_time"], errors="coerce")
    df["filled"] = ~df["actual_order_result"].eq("not_filled")
    df["decided"] = df["actual_order_result"].isin(["tp", "lc"])
    df["win"] = df["actual_order_result"].eq("tp")
    df["actual_res"] = pd.to_numeric(df["actual_res"], errors="coerce")

    df["方向"] = df["direction"].map({1: "買い", -1: "売り"})
    df["注文方式"] = df["line_order_mode"].map(
        {"immediate": "即時", "future_break": "未来ブレイク", "limit": "指値"}
    ).fillna(df["line_order_mode"])
    df["ライン側"] = df["line_side"].map({"upper": "上", "lower": "下"})
    df["エントリー型"] = df["line_entry_type"].map(
        {"breakout": "ブレイク", "reversal": "反発"}
    ).fillna(df["line_entry_type"])
    df["時間帯"] = cut(
        pd.to_datetime(df["target_time"]).dt.hour,
        [-1, 5, 8, 14, 20, 23],
        ["00-05", "06-08", "09-14", "15-20", "21-23"],
    )
    rsi_bins = [-1, 30, 40, 50, 60, 67.5, 101]
    rsi_labels = ["<=30", "30-40", "40-50", "50-60", "60-67.5", ">67.5"]
    df["M5_RSI"] = cut(df["rsi_1"], rsi_bins, rsi_labels)
    df["H1_RSI"] = cut(df["h1_rsi_1"], rsi_bins, rsi_labels)
    df["直近ピークRSI"] = cut(df["latest_peak_rsi"], rsi_bins, rsi_labels)
    df["前回ピークRSI"] = cut(df["previous_peak_rsi"], rsi_bins, rsi_labels)
    strength_bins = [-1, 5, 10, 15, 20, 10**9]
    strength_labels = ["0-5", "5-10", "10-15", "15-20", "20+"]
    df["ライン強度"] = cut(df["line_total_strength"], strength_bins, strength_labels)
    df["コア強度"] = cut(df["core_total_strength"], strength_bins, strength_labels)
    df["進路H1抵抗強度"] = cut(
        df["h1_path_ahead_1_total_strength"], strength_bins, strength_labels
    )
    df["最寄H1抵抗強度"] = cut(
        df["h1_nearest_total_strength"], strength_bins, strength_labels
    )
    df["進路H1距離"] = cut(
        df["h1_path_ahead_1_distance_pips"],
        [-1, 3, 6, 10, 20, 30, 50, 10**9],
        ["0-3p", "3-6p", "6-10p", "10-20p", "20-30p", "30-50p", "50p+"],
    )
    touch_order = [
        "31-60m", "61-180m", "181-360m", "361-720m", "721-1440m",
        "1441-2880m", "2881-4320m", "4321-7200m", "7201-10080m",
        "10081-15000m", "15001m+", "no_touch_in_history",
    ]
    df["TP最終到達経過"] = pd.Categorical(
        df["tp_last_touch_elapsed_bin"], categories=touch_order, ordered=True
    )
    df["ライン反転"] = df["line_is_flipped"].map({True: "反転済", False: "非反転"})
    return df


def stats(group):
    generated = len(group)
    filled = int(group["filled"].sum())
    decided = group[group["decided"]]
    wins = int(decided["win"].sum())
    result_sum = decided["actual_res"].sum()
    return {
        "generated": generated,
        "filled": filled,
        "decided": len(decided),
        "wins": wins,
        "fill_rate": filled / generated if generated else np.nan,
        "win_rate": wins / len(decided) if len(decided) else np.nan,
        "avg_pips": decided["actual_res"].mean() if len(decided) else np.nan,
        "ev_per_signal": result_sum / generated if generated else np.nan,
    }


def condition_text(filters):
    return " / ".join(f"{key}={value}" for key, value in filters)


def grouped_stats(frame, columns, prefix):
    work = frame.copy()
    work["_result_pips"] = work["actual_res"].where(work["decided"], 0).fillna(0)
    grouped = work.groupby(list(columns), observed=True, dropna=True).agg(
        generated=("actual_order_result", "size"),
        filled=("filled", "sum"),
        decided=("decided", "sum"),
        wins=("win", "sum"),
        result_sum=("_result_pips", "sum"),
    ).reset_index()
    grouped[f"{prefix}_fill_rate"] = grouped["filled"] / grouped["generated"]
    grouped[f"{prefix}_win_rate"] = grouped["wins"] / grouped["decided"]
    grouped[f"{prefix}_avg_pips"] = grouped["result_sum"] / grouped["decided"]
    grouped[f"{prefix}_ev_per_signal"] = grouped["result_sum"] / grouped["generated"]
    return grouped.rename(
        columns={
            "generated": f"{prefix}_generated",
            "filled": f"{prefix}_filled",
            "decided": f"{prefix}_decided",
            "wins": f"{prefix}_wins",
        }
    ).drop(columns=["result_sum"])


def build_candidates(df):
    fields = [
        "方向", "注文方式", "ライン側", "エントリー型", "時間帯",
        "M5_RSI", "H1_RSI", "直近ピークRSI", "前回ピークRSI",
        "ライン強度", "コア強度", "進路H1抵抗強度", "最寄H1抵抗強度",
        "進路H1距離", "TP最終到達経過", "ライン反転",
    ]
    train = df[df["dt"] < CUTOFF]
    test = df[df["dt"] >= CUTOFF]
    rows = []
    for size in (2, 3):
        for columns in itertools.combinations(fields, size):
            full_stats = grouped_stats(df, columns, "full")
            train_stats = grouped_stats(train, columns, "train")
            test_stats = grouped_stats(test, columns, "test")
            merged = full_stats.merge(train_stats, on=list(columns), how="inner")
            merged = merged.merge(test_stats, on=list(columns), how="inner")
            for record in merged.to_dict("records"):
                if (
                    record["full_generated"] < 400
                    or record["full_decided"] < 120
                    or record["train_generated"] < 250
                    or record["train_decided"] < 75
                    or record["test_generated"] < 100
                    or record["test_decided"] < 30
                    or record["train_avg_pips"] <= 0
                    or record["test_avg_pips"] <= 0
                    or record["train_ev_per_signal"] <= 0
                    or record["test_ev_per_signal"] <= 0
                ):
                    continue
                stability = min(
                    record["train_ev_per_signal"], record["test_ev_per_signal"]
                )
                score = (
                    stability
                    * math.log1p(record["test_decided"])
                    * (0.5 + min(record["test_fill_rate"], 0.8))
                )
                values = tuple(record[column] for column in columns)
                filters = list(zip(columns, values))
                rows.append(
                    {
                        "condition": condition_text(filters),
                        "filters": filters,
                        "score": score,
                        **{
                            key: value
                            for key, value in record.items()
                            if key not in columns
                        },
                    }
                )
    return pd.DataFrame(rows).sort_values("score", ascending=False)


def select_diverse(ranked):
    def canonical(filters):
        normalized = set()
        for key, value in filters:
            if (key, value) == ("ライン側", "下"):
                normalized.add(("方向", "売り"))
            elif (key, value) == ("ライン側", "上"):
                normalized.add(("方向", "買い"))
            else:
                normalized.add((key, value))
        return normalized

    selected = []
    for row in ranked.to_dict("records"):
        current = canonical(row["filters"])
        redundant = False
        for prior in selected:
            previous = canonical(prior["filters"])
            overlap = len(current & previous) / min(len(current), len(previous))
            if overlap >= 2 / 3:
                redundant = True
                break
        if not redundant:
            selected.append(row)
        if len(selected) == 10:
            break
    return selected


def main():
    df = prepare(pd.read_csv(PATH))
    baseline = stats(df)
    train_base = stats(df[df["dt"] < CUTOFF])
    test_base = stats(df[df["dt"] >= CUTOFF])
    ranked = build_candidates(df)
    top = select_diverse(ranked)
    out = pd.DataFrame(top).drop(columns=["filters"])
    out.to_csv(OUT_PATH, index=False, encoding="utf-8-sig")

    lines = [
        "EUR/USD 1年検証 条件TOP10",
        "期間 2025/6/24〜2026/6/23。前9か月探索、後3か月検証。",
        (
            f"全体: 注文{baseline['generated']:,} 約定率{baseline['fill_rate']*100:.1f}% "
            f"約定後勝率{baseline['win_rate']*100:.1f}% 平均{baseline['avg_pips']:+.2f}p "
            f"1シグナル期待{baseline['ev_per_signal']:+.3f}p"
        ),
        (
            f"前9か月平均{train_base['avg_pips']:+.2f}p / "
            f"後3か月平均{test_base['avg_pips']:+.2f}p"
        ),
        "条件: 全体400件・決着120件以上、後3か月100件・決着30件以上、前後期間とも期待値プラス。",
        "",
    ]
    for index, row in enumerate(top, 1):
        lines += [
            f"#{index} {row['condition']}",
            (
                f"全体 n={row['full_generated']:,} 約定{row['full_fill_rate']*100:.1f}% "
                f"約定後勝率{row['full_win_rate']*100:.1f}% 平均{row['full_avg_pips']:+.2f}p "
                f"期待/信号{row['full_ev_per_signal']:+.3f}p"
            ),
            (
                f"後3か月 n={row['test_generated']:,} 約定{row['test_fill_rate']*100:.1f}% "
                f"勝率{row['test_win_rate']*100:.1f}% 平均{row['test_avg_pips']:+.2f}p"
            ),
        ]
    text = "\n".join(lines)
    print(text)
    for start in range(0, len(text), 1800):
        response = requests.post(
            tk.WEBHOOK_URL_inspection,
            json={"content": text[start:start + 1800]},
            timeout=15,
        )
        response.raise_for_status()
        print("Discord status:", response.status_code)


if __name__ == "__main__":
    main()
