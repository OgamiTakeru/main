import itertools

import pandas as pd
import requests

import tokens as tk


PATH = r"C:\Users\taker\OneDrive\Desktop\oanda_logs\result_20251224000000_20260624000000.csv"


def pct(x):
    return f"{x * 100:.1f}%"


def add_bins(df):
    df = df.copy()
    df["session"] = pd.cut(
        pd.to_datetime(df["target_time"]).dt.hour,
        bins=[-1, 5, 8, 14, 20, 23],
        labels=["00-05時", "06-08時", "09-14時", "15-20時", "21-23時"],
    )
    df["line_strength_bin"] = pd.cut(
        df["line_total_strength"],
        bins=[-0.1, 5, 10, 15, 20, 999],
        labels=["line強度<=5", "line強度6-10", "line強度11-15", "line強度16-20", "line強度21+"],
    )
    df["core_strength_bin"] = pd.cut(
        df["core_total_strength"],
        bins=[-0.1, 5, 10, 15, 20, 999],
        labels=["core強度<=5", "core強度6-10", "core強度11-15", "core強度16-20", "core強度21+"],
    )
    df["line_count_bin"] = pd.cut(
        df["line_count"],
        bins=[0, 1, 2, 3, 5, 999],
        labels=["line数1", "line数2", "line数3", "line数4-5", "line数6+"],
    )
    df["core_count_bin"] = pd.cut(
        df["core_count"],
        bins=[0, 1, 2, 3, 5, 999],
        labels=["core数1", "core数2", "core数3", "core数4-5", "core数6+"],
    )
    df["latest_peak_count_bin"] = pd.cut(
        df["latest_peak_count"],
        bins=[-0.1, 1, 2, 3, 5, 999],
        labels=["直近peak数<=1", "直近peak数2", "直近peak数3", "直近peak数4-5", "直近peak数6+"],
    )
    df["m5_rsi_bin"] = pd.cut(
        df["rsi_1"],
        bins=[-0.1, 30, 40, 50, 60, 67.5, 100],
        labels=["M5 RSI<=30", "M5 RSI31-40", "M5 RSI41-50", "M5 RSI51-60", "M5 RSI61-67.5", "M5 RSI>67.5"],
    )
    df["h1_rsi_bin"] = pd.cut(
        df["h1_rsi_1"],
        bins=[-0.1, 30, 40, 50, 60, 67.5, 100],
        labels=["H1 RSI<=30", "H1 RSI31-40", "H1 RSI41-50", "H1 RSI51-60", "H1 RSI61-67.5", "H1 RSI>67.5"],
    )
    return df


def summarize_group(group):
    decided = group[group["order_result"].isin(["tp", "lc"])]
    if len(decided) == 0:
        return None
    tp = decided["order_result"].eq("tp").sum()
    lc = decided["order_result"].eq("lc").sum()
    return {
        "n": len(group),
        "decided_n": len(decided),
        "tp": int(tp),
        "lc": int(lc),
        "not_filled": int(group["order_result"].eq("not_filled").sum()),
        "not_closed": int(group["order_result"].eq("not_closed").sum()),
        "win_rate": tp / len(decided),
        "fill_rate": group["order_result"].ne("not_filled").mean(),
        "avg_res": decided["res"].mean(),
        "avg_max_plus": group.loc[group["order_result"].ne("not_filled"), "max_plus_pips"].mean(),
        "avg_max_minus": group.loc[group["order_result"].ne("not_filled"), "max_minus_pips"].mean(),
    }


def condition_text(filters):
    names = []
    for key, value in filters:
        if key == "line_side":
            names.append("下ライン反発" if value == "lower" else "上ライン反落")
        elif key == "line_is_flipped":
            names.append("非flipped" if value is False else "flipped")
        elif key == "latest_peak_dir":
            names.append("直近H1ピーク方向: 下" if int(value) == -1 else "直近H1ピーク方向: 上")
        else:
            names.append(str(value))
    return " / ".join(names)


def build_rank(df, direction, min_decided):
    side_df = df[(df["source"].eq("line")) & (df["direction"].eq(direction))].copy()
    fields = [
        "line_side",
        "line_is_flipped",
        "latest_peak_dir",
        "session",
        "line_strength_bin",
        "core_strength_bin",
        "core_count_bin",
        "latest_peak_count_bin",
        "m5_rsi_bin",
        "h1_rsi_bin",
    ]
    rows = []
    for size in [2, 3]:
        for combo in itertools.combinations(fields, size):
            grouped = side_df.groupby(list(combo), dropna=False, observed=True)
            for values, group in grouped:
                if not isinstance(values, tuple):
                    values = (values,)
                if any(pd.isna(v) for v in values):
                    continue
                summary = summarize_group(group)
                if summary is None or summary["decided_n"] < min_decided:
                    continue
                filters = list(zip(combo, values))
                score = summary["win_rate"] * 100 + summary["avg_res"] * 2 + min(summary["decided_n"], 300) / 300
                rows.append({**summary, "filters": filters, "condition": condition_text(filters), "score": score})
    rank = pd.DataFrame(rows)
    rank = rank.sort_values(
        ["win_rate", "avg_res", "decided_n", "fill_rate"],
        ascending=[False, False, False, False],
    )

    selected = []
    seen_conditions = []
    for row in rank.to_dict("records"):
        condition_set = set(row["filters"])
        if any(condition_set.issuperset(prev) and abs(row["win_rate"] - prev_wr) < 0.02 for prev, prev_wr in seen_conditions):
            continue
        selected.append(row)
        seen_conditions.append((condition_set, row["win_rate"]))
        if len(selected) >= 7:
            break
    return selected, side_df


def make_section(title, rows):
    lines = [title]
    for i, r in enumerate(rows, 1):
        lines.append(f"＜No{i}＞")
        lines.append(f"勝率：{pct(r['win_rate'])}  ({r['tp']}勝/{r['decided_n']}決着)")
        lines.append(f"平均TP：{r['avg_res']:.2f}pips")
        lines.append(f"件数：全{r['n']} / 約定率{pct(r['fill_rate'])} / 未約定{r['not_filled']}")
        lines.append("条件：" + r["condition"])
    return "\n".join(lines)


def main():
    df = pd.read_csv(PATH)
    df = add_bins(df)
    closed = df[df["order_result"].isin(["tp", "lc"])]
    overall = closed.groupby("direction")["order_result"].value_counts().unstack(fill_value=0)

    sell_rows, sell_df = build_rank(df, -1, min_decided=30)
    buy_rows, buy_df = build_rank(df, 1, min_decided=30)

    header = [
        "【H1ライン半年検証 TOP条件】",
        "対象: result_20251224000000_20260624000000.csv",
        "集計: source=line、TP/LC決着済みで勝率算出。条件ランキングは最低30決着以上。",
        "",
        "全体:",
    ]
    for direction, label in [(-1, "売り"), (1, "買い")]:
        tp = int(overall.loc[direction].get("tp", 0)) if direction in overall.index else 0
        lc = int(overall.loc[direction].get("lc", 0)) if direction in overall.index else 0
        total = tp + lc
        header.append(f"{label}: 勝率{tp / total * 100:.1f}% ({tp}勝/{total}決着)")

    message = "\n".join(header) + "\n\n" + make_section("【売り TOP7】", sell_rows)
    message += "\n\n" + make_section("【買い TOP7】", buy_rows)

    print(message)
    for start in range(0, len(message), 1800):
        data = {
            "content": "@everyone " + "inspection H1 line TOP7\n" + message[start:start + 1800],
            "allowed_mentions": {"parse": ["everyone"]},
        }
        res = requests.post(tk.WEBHOOK_URL_inspection, json=data, timeout=15)
        print("Discord status:", res.status_code)


if __name__ == "__main__":
    main()
