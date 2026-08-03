import datetime

import numpy as np
import pandas as pd
import requests

import classOanda
import fGeneric as gene
import tokens as tk


START = pd.Timestamp("2026-07-20 00:00:00")
PAIRS = ("USD_JPY", "EUR_USD", "AUD_USD")
HISTORY_PATH = r"C:\Users\taker\OneDrive\Desktop\oanda_logs\history\history.csv"


def trade_summary():
    rows = pd.read_csv(HISTORY_PATH)
    rows["order_dt"] = pd.to_datetime(rows["order_time"], errors="coerce")
    for col in ("tradeID", "take_price", "pl_per_units", "res"):
        rows[col] = pd.to_numeric(rows[col], errors="coerce")
    rows = rows[
        rows["order_dt"].ge(START)
        & rows["tradeID"].gt(0)
        & rows["take_price"].gt(0)
        & rows["pair"].isin(PAIRS)
    ].copy()
    rows = rows.sort_values("order_dt").drop_duplicates("tradeID", keep="last")
    return rows.groupby("pair").agg(
        trades=("tradeID", "size"),
        wins=("pl_per_units", lambda s: int((s > 0).sum())),
        losses=("pl_per_units", lambda s: int((s < 0).sum())),
        total_pips=("pl_per_units", "sum"),
        average_pips=("pl_per_units", "mean"),
        total_yen=("res", "sum"),
    )


def candle_summary(oa, pair):
    # 180 H1 bars is only 7.5 days. Filter again to this week and discard the
    # current incomplete candle so no future/incomplete range is used.
    response = oa.InstrumentsCandles_exe(pair, {"granularity": "H1", "count": 180})
    if response.get("error") != 0:
        raise RuntimeError(f"{pair} candle fetch failed: {response}")
    frame = response["data"].copy()
    frame["dt"] = pd.to_datetime(frame["time_jp"], errors="coerce")
    current_hour = pd.Timestamp.now().floor("h")
    frame = frame[frame["dt"].ge(START) & frame["dt"].lt(current_hour)].sort_values("dt")
    for col in ("open", "high", "low", "close"):
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    p = gene.currency_pair(pair)
    factor = 1 / p.pips_to_price(1)
    first_open = frame.iloc[0]["open"]
    last_close = frame.iloc[-1]["close"]
    net_pips = (last_close - first_open) * factor
    gross_range_pips = (frame["high"].max() - frame["low"].min()) * factor
    close_moves = frame["close"].diff().dropna() * factor
    travel = close_moves.abs().sum()
    efficiency = abs(net_pips) / travel if travel else np.nan
    direction = np.sign(net_pips)
    aligned = (np.sign(close_moves) == direction).mean() if direction else np.nan
    signs = np.sign(close_moves.replace(0, np.nan)).dropna()
    flips = int((signs != signs.shift()).sum() - 1) if len(signs) > 1 else 0
    body_sum = (frame["close"] - frame["open"]).abs().sum() * factor
    wick_range_sum = (frame["high"] - frame["low"]).sum() * factor
    body_ratio = body_sum / wick_range_sum if wick_range_sum else np.nan
    return {
        "bars": len(frame),
        "from": frame.iloc[0]["dt"],
        "to": frame.iloc[-1]["dt"] + pd.Timedelta(hours=1),
        "net_pips": net_pips,
        "range_pips": gross_range_pips,
        "efficiency_pct": efficiency * 100,
        "aligned_pct": aligned * 100,
        "direction_flips": flips,
        "body_ratio_pct": body_ratio * 100,
    }


def main():
    trades = trade_summary()
    oa = classOanda.Oanda(tk.accountIDl, tk.access_tokenl, tk.environmentl)
    regimes = pd.DataFrame({pair: candle_summary(oa, pair) for pair in PAIRS}).T

    lines = [
        "今週の実取引と相場レジーム比較（7/20〜現在、確定H1のみ）",
        "",
        "【実取引】",
    ]
    for pair in PAIRS:
        row = trades.loc[pair]
        decided = row["wins"] + row["losses"]
        lines.append(
            f"{pair}: {int(row['trades'])}件 勝率{row['wins']/decided*100:.1f}% "
            f"合計{row['total_pips']:+.1f}p 平均{row['average_pips']:+.2f}p "
            f"{row['total_yen']:+.0f}円"
        )
    lines += ["", "【確定H1の値動き】"]
    for pair in PAIRS:
        row = regimes.loc[pair]
        lines.append(
            f"{pair}: 週間変化{row['net_pips']:+.1f}p / 全値幅{row['range_pips']:.1f}p / "
            f"方向効率{row['efficiency_pct']:.1f}% / 同方向H1 {row['aligned_pct']:.1f}% / "
            f"方向反転{int(row['direction_flips'])}回 / 実体比{row['body_ratio_pct']:.1f}%"
        )

    usd = regimes.loc["USD_JPY"]
    eur = regimes.loc["EUR_USD"]
    aud = regimes.loc["AUD_USD"]
    lines += [
        "",
        "判定:",
        (
            "USD_JPYはEUR/USDより方向効率が高く、USD用のブレイク・継続条件と今週の値動きが比較的合った。"
            if usd["efficiency_pct"] > eur["efficiency_pct"]
            else "USD_JPYがEUR/USDより明確にトレンド的だったとは、この指標では言えない。"
        ),
        (
            "EUR/USDは週間変化が全値幅に比べて小さく往復が多いため、広い意味でレンジ寄りという感覚は妥当。"
            if abs(eur["net_pips"]) / eur["range_pips"] < 0.45
            else "EUR/USDは週間変化も大きく、単純なレンジ相場とは言いにくい。"
        ),
        (
            "AUD/USDもUSD/JPYより方向効率が低く、USD条件の横展開による不適合の可能性がある。"
            if aud["efficiency_pct"] < usd["efficiency_pct"]
            else "AUD/USDの方向効率はUSD/JPY以上で、悪化をレンジだけでは説明しにくい。"
        ),
        "ただし1週間だけなので、原因の確定ではなく整合的な状況証拠。",
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
