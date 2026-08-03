import os

import numpy as np
import pandas as pd
import requests

import fGeneric as gene
import tokens as tk


ROOT = r"C:\Users\taker\OneDrive\Desktop\oanda_logs"
PAIRS = ("USD_JPY", "EUR_USD", "AUD_USD")
CUTOFF = pd.Timestamp("2026-03-24 00:00:00")


def market_metrics(pair, period, frame):
    p = gene.currency_pair(pair)
    factor = 1 / p.pips_to_price(1)
    frame = frame.sort_values("dt").copy()
    close_move = frame["close"].diff() * factor
    hourly_range = (frame["high"] - frame["low"]) * factor
    body = (frame["close"] - frame["open"]).abs() * factor
    signs = np.sign(close_move.replace(0, np.nan)).dropna()
    rolling_travel = close_move.abs().rolling(24, min_periods=12).sum()
    rolling_net = (frame["close"] - frame["close"].shift(24)).abs() * factor
    trend24 = (rolling_net / rolling_travel).replace([np.inf, -np.inf], np.nan)
    return {
        "pair": pair,
        "period": period,
        "h1_bars": len(frame),
        "net_pips": (frame.iloc[-1]["close"] - frame.iloc[0]["open"]) * factor,
        "avg_h1_range": hourly_range.mean(),
        "avg_h1_body": body.mean(),
        "body_ratio": body.sum() / hourly_range.sum(),
        "trend24": trend24.mean(),
        "flip_rate": (signs != signs.shift()).mean(),
        "rsi_extreme_rate": ((frame["RSI"] <= 30) | (frame["RSI"] >= 70)).mean(),
        "bb_range_pips": (frame["bb_range"] * factor).mean(),
    }


def trade_metrics(group):
    decided = group[group["decided"]]
    return pd.Series(
        {
            "orders": len(group),
            "fill_rate": group["filled"].mean(),
            "decided": len(decided),
            "win_rate": decided["win"].mean(),
            "avg_pips": decided["actual_res"].mean(),
            "ev_signal": decided["actual_res"].sum() / len(group),
        }
    )


def load_pair(pair):
    result_path = os.path.join(
        ROOT, f"result_{pair}_20250624000000_20260624000000.csv"
    )
    result_cols = [
        "source", "target_time", "direction", "line_order_mode",
        "actual_order_result", "actual_res", "tp_last_touch_elapsed_bin",
    ]
    trades = pd.read_csv(result_path, usecols=result_cols)
    trades = trades[trades["source"].eq("line")].copy()
    trades["dt"] = pd.to_datetime(trades["target_time"], errors="coerce")
    trades["period"] = trades["dt"].ge(CUTOFF).map({False: "前9か月", True: "後3か月"})
    trades["filled"] = ~trades["actual_order_result"].eq("not_filled")
    trades["decided"] = trades["actual_order_result"].isin(["tp", "lc"])
    trades["win"] = trades["actual_order_result"].eq("tp")
    trades["actual_res"] = pd.to_numeric(trades["actual_res"], errors="coerce")

    h1_path = os.path.join(
        ROOT, f"h1_{pair}_20250624000000_20260624000000.csv"
    )
    h1 = pd.read_csv(h1_path)
    h1["dt"] = pd.to_datetime(h1["time_jp"], errors="coerce")
    for col in ("open", "close", "high", "low", "RSI", "bb_range"):
        h1[col] = pd.to_numeric(h1[col], errors="coerce")
    return trades, h1


def main():
    market_rows = []
    trade_rows = []
    direction_rows = []
    touch_shift_rows = []
    for pair in PAIRS:
        trades, h1 = load_pair(pair)
        periods = {
            "前9か月": h1[h1["dt"] < CUTOFF],
            "後3か月": h1[h1["dt"] >= CUTOFF],
        }
        for period, frame in periods.items():
            market_rows.append(market_metrics(pair, period, frame))

        total = (
            trades.groupby("period", observed=True)
            .apply(trade_metrics, include_groups=False)
            .reset_index()
        )
        total.insert(0, "pair", pair)
        trade_rows.append(total)

        by_direction = (
            trades.groupby(["period", "direction"], observed=True)
            .apply(trade_metrics, include_groups=False)
            .reset_index()
        )
        by_direction.insert(0, "pair", pair)
        direction_rows.append(by_direction)

        touch = pd.crosstab(
            trades["tp_last_touch_elapsed_bin"],
            trades["period"],
            normalize="columns",
        )
        if {"前9か月", "後3か月"}.issubset(touch.columns):
            touch["shift"] = touch["後3か月"] - touch["前9か月"]
            for elapsed_bin, row in touch.iterrows():
                touch_shift_rows.append(
                    {
                        "pair": pair,
                        "elapsed_bin": elapsed_bin,
                        "train_share": row["前9か月"],
                        "test_share": row["後3か月"],
                        "shift": row["shift"],
                    }
                )

    market = pd.DataFrame(market_rows)
    trades = pd.concat(trade_rows, ignore_index=True)
    directions = pd.concat(direction_rows, ignore_index=True)
    shifts = pd.DataFrame(touch_shift_rows)
    market.to_csv("period_market_regime.csv", index=False, encoding="utf-8-sig")
    trades.to_csv("period_trade_results.csv", index=False, encoding="utf-8-sig")
    directions.to_csv("period_direction_results.csv", index=False, encoding="utf-8-sig")

    lines = [
        "前9か月 vs 後3か月：通貨別レジーム比較",
        "境界 2026/03/24。相場指標は確定H1。",
    ]
    for pair in PAIRS:
        lines += ["", f"【{pair}】"]
        for period in ("前9か月", "後3か月"):
            m = market[(market["pair"] == pair) & (market["period"] == period)].iloc[0]
            t = trades[(trades["pair"] == pair) & (trades["period"] == period)].iloc[0]
            lines.append(
                f"{period}: fill={t['fill_rate']*100:.1f}% win={t['win_rate']*100:.1f}% "
                f"avg={t['avg_pips']:+.2f}p EV={t['ev_signal']:+.3f}p / "
                f"H1幅={m['avg_h1_range']:.1f}p 24h方向効率={m['trend24']*100:.1f}% "
                f"反転率={m['flip_rate']*100:.1f}% BB幅={m['bb_range_pips']:.1f}p"
            )
        pair_dir = directions[directions["pair"] == pair]
        for direction, label in ((1, "買い"), (-1, "売り")):
            values = pair_dir[pair_dir["direction"] == direction].set_index("period")
            lines.append(
                f"{label}: avg 前{values.loc['前9か月','avg_pips']:+.2f}→"
                f"後{values.loc['後3か月','avg_pips']:+.2f}p / "
                f"win {values.loc['前9か月','win_rate']*100:.1f}→"
                f"{values.loc['後3か月','win_rate']*100:.1f}%"
            )
        changed = shifts[shifts["pair"] == pair].sort_values(
            "shift", key=lambda s: s.abs(), ascending=False
        ).head(3)
        lines.append(
            "TP経過構成変化: "
            + " / ".join(
                f"{row.elapsed_bin} {row.train_share*100:.1f}→{row.test_share*100:.1f}%"
                for row in changed.itertuples()
            )
        )

    text = "\n".join(lines)
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
