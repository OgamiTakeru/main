import os

import pandas as pd
import requests

import tokens as tk


HISTORY_DIR = r"C:\Users\taker\OneDrive\Desktop\oanda_logs\history"
NORMALIZED_FROM = pd.Timestamp("2026-07-11 15:47:38")


def load_history():
    frames = []
    for filename, priority in (("history古.csv", 0), ("history.csv", 1)):
        path = os.path.join(HISTORY_DIR, filename)
        frame = pd.read_csv(path)
        frame["_source"] = filename
        frame["_priority"] = priority
        frames.append(frame)
    rows = pd.concat(frames, ignore_index=True, sort=False)
    rows["order_dt"] = pd.to_datetime(rows["order_time"], errors="coerce")
    for column in (
        "tradeID", "take_price", "target_price", "pl_per_units", "max_plus",
        "max_minus", "tp_range", "lc_range", "res",
    ):
        rows[column] = pd.to_numeric(rows[column], errors="coerce")

    # history.csv overlaps the end of history古.csv. Prefer the newer copy.
    valid_id = rows["tradeID"].gt(0)
    with_id = rows[valid_id].sort_values("_priority").drop_duplicates("tradeID", keep="last")
    without_id = rows[~valid_id]
    rows = pd.concat([with_id, without_id], ignore_index=True, sort=False)

    # A real filled trade has a positive trade ID, take price, and nonzero units.
    units = pd.to_numeric(rows["units"], errors="coerce")
    rows = rows[rows["tradeID"].gt(0) & rows["take_price"].gt(0) & units.ne(0)].copy()

    # Before the normalization commit these fields were stored as price deltas.
    old_format = rows["order_dt"].lt(NORMALIZED_FROM)
    pip_factor = rows["target_price"].where(rows["target_price"].notna(), rows["take_price"])
    pip_factor = pip_factor.apply(lambda price: 100.0 if price > 20 else 10000.0)
    for column in ("pl_per_units", "max_plus", "max_minus", "tp_range", "lc_range"):
        rows[column + "_pips"] = rows[column]
        rows.loc[old_format, column + "_pips"] = (
            rows.loc[old_format, column] * pip_factor.loc[old_format]
        )

    # NoOrderClass/legacy rows can contain prices or sums in tp_range. They are
    # unsuitable for a TP-width study, so retain only plausible positive widths.
    rows = rows[
        rows["tp_range_pips"].between(0.1, 100)
        & rows["pl_per_units_pips"].between(-100, 100)
        & rows["max_plus_pips"].between(0, 100)
    ].copy()
    rows["loss"] = rows["pl_per_units_pips"] < 0
    rows["max_plus_tp_ratio"] = rows["max_plus_pips"] / rows["tp_range_pips"]
    rows["line"] = rows["name"].fillna("").str.contains("Line", case=False)
    return rows


def one_scope(rows, label):
    losses = rows[rows["loss"]].copy()
    lines = [f"【{label}】 対象取引 {len(rows):,}件 / 負け {len(losses):,}件"]
    for threshold in (10, 15, 20):
        group = losses[losses["tp_range_pips"] >= threshold]
        if group.empty:
            continue
        pct_losses = len(group) / len(losses) * 100 if len(losses) else 0
        plus5 = group["max_plus_pips"].ge(5).sum()
        halfway = group["max_plus_tp_ratio"].ge(0.5).sum()
        near = group["max_plus_tp_ratio"].ge(0.8).sum()
        lines.append(
            f"TP{threshold}p以上の負け: {len(group):,}件（負けの{pct_losses:.1f}%） / "
            f"一時+5p以上 {plus5:,}件（{plus5/len(group)*100:.1f}%） / "
            f"TPの50%以上到達 {halfway:,}件（{halfway/len(group)*100:.1f}%） / "
            f"80%以上到達 {near:,}件（{near/len(group)*100:.1f}%）"
        )

    large = losses[losses["tp_range_pips"] >= 10]
    if not large.empty:
        lines.append(
            "TP10p以上負けの中央値: "
            f"TP {large['tp_range_pips'].median():.1f}p / 最大プラス "
            f"{large['max_plus_pips'].median():.1f}p / 最終 "
            f"{large['pl_per_units_pips'].median():.1f}p"
        )
    return lines


def main():
    rows = load_history()
    losses = rows[rows["loss"]].copy()
    message = [
        "実取引：大きい利確幅のまま負けたパターン調査",
        f"期間: {rows['order_dt'].min():%Y/%m/%d}〜{rows['order_dt'].max():%Y/%m/%d}",
        "旧履歴の価格差は通貨別にpips換算。重複、未約定、キャンセル、異常TP値は除外。",
        "最大プラスは定期観測値なので、瞬間的な高値/安値は取り逃す可能性あり。",
        "",
    ]
    message += one_scope(rows, "全戦略")
    message.append("")
    message += one_scope(rows[rows["line"]], "ライン系")

    large = losses[losses["tp_range_pips"] >= 10]
    bands = pd.cut(
        large["max_plus_tp_ratio"],
        bins=[-0.001, 0, 0.25, 0.5, 0.8, 1, float("inf")],
        labels=["0%", "0-25%", "25-50%", "50-80%", "80-100%", "100%+"],
        include_lowest=True,
    ).value_counts(sort=False)
    message.append("")
    message.append("TP10p以上で負けた時の最大到達率（最大プラス÷TP幅）:")
    message.append(" / ".join(f"{key} {value}件" for key, value in bands.items()))

    top = large.sort_values("max_plus_tp_ratio", ascending=False).head(8)
    message.append("")
    message.append("TPへかなり近づいてから負けた上位例:")
    for _, row in top.iterrows():
        message.append(
            f"{row['order_dt']:%m/%d %H:%M} {str(row['name'])[:35]} "
            f"TP{row['tp_range_pips']:.1f}p 最大+{row['max_plus_pips']:.1f}p "
            f"({row['max_plus_tp_ratio']*100:.0f}%) 最終{row['pl_per_units_pips']:.1f}p"
        )

    text = "\n".join(message)
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
