import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fGeneric as gene
from classStrategyRegime import StrategyRegime


ROOT = r"C:\Users\taker\OneDrive\Desktop\oanda_logs"
PAIRS = ("EUR_USD", "USD_JPY", "AUD_USD")
FROM = "20250624000000"
TO = "20260624000000"


def regime_table(pair):
    path = os.path.join(ROOT, f"h1_{pair}_{FROM}_{TO}.csv")
    frame = pd.read_csv(
        path,
        usecols=["time_jp", "open", "close", "high", "low"],
    )
    frame["h1_time"] = pd.to_datetime(frame["time_jp"], errors="coerce")
    frame = frame.dropna(subset=["h1_time"]).sort_values("h1_time").reset_index(drop=True)
    for column in ("open", "close", "high", "low"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    factor = 1 / gene.currency_pair(pair).pips_to_price(1)
    rows = []
    for end in range(len(frame)):
        available = frame.iloc[max(0, end - 11) : end + 1]
        w3 = StrategyRegime._window_summary(available, 3, factor)
        w6 = StrategyRegime._window_summary(available, 6, factor)
        w12 = StrategyRegime._window_summary(available, 12, factor)
        result = StrategyRegime._classify_market_regime(w3, w6, w12)
        rows.append(
            {
                "available_time": frame.iloc[end]["h1_time"] + pd.Timedelta(hours=1),
                "offline_regime": result["regime"],
                "offline_trend_direction": result["trend_direction"],
                "offline_eff3": w3["direction_efficiency"],
                "offline_eff6": w6["direction_efficiency"],
                "offline_eff12": w12["direction_efficiency"],
                "offline_exp3": result.get("range_expansion_3_vs_12"),
                "offline_exp6": result.get("range_expansion_6_vs_12"),
            }
        )
    return pd.DataFrame(rows)


def metrics(frame):
    decided = frame[frame["decided"]]
    return {
        "signals": int(len(frame)),
        "filled": int(frame["filled"].sum()),
        "fill_rate": float(frame["filled"].mean()) if len(frame) else None,
        "decided": int(len(decided)),
        "wins": int(decided["win"].sum()),
        "win_rate": float(decided["win"].mean()) if len(decided) else None,
        "total_pips": float(decided["actual_res"].sum()),
        "avg_pips": float(decided["actual_res"].mean()) if len(decided) else None,
        "ev_signal": float(decided["actual_res"].sum() / len(frame)) if len(frame) else None,
    }


def grouped_metrics(frame, columns):
    output = []
    for key, group in frame.groupby(columns, dropna=False, observed=True):
        if not isinstance(key, tuple):
            key = (key,)
        row = dict(zip(columns, key))
        row.update(metrics(group))
        output.append(row)
    return output


def load_pair(pair):
    path = os.path.join(ROOT, f"result_{pair}_{FROM}_{TO}.csv")
    wanted = {
        "target_time", "name", "source", "direction", "line_order_mode",
        "line_entry_type", "actual_order_result", "actual_res",
        "regime_at_order", "regime_trend_direction", "regime_would_block",
        "regime_order_permission", "regime_order_reason",
    }
    trades = pd.read_csv(path, usecols=lambda column: column in wanted)
    trades["target_dt"] = pd.to_datetime(trades["target_time"], errors="coerce")
    trades["direction"] = pd.to_numeric(trades["direction"], errors="coerce")
    trades["actual_res"] = pd.to_numeric(trades["actual_res"], errors="coerce")
    trades["filled"] = ~trades["actual_order_result"].eq("not_filled")
    trades["decided"] = trades["actual_order_result"].isin(["tp", "lc"])
    trades["win"] = trades["actual_order_result"].eq("tp")

    has_saved = "regime_at_order" in trades and trades["regime_at_order"].notna().any()
    if has_saved:
        regime_agreement = None
        block_agreement = None
        trades["would_block"] = trades["regime_would_block"].astype(str).str.lower().eq("true")
        trades["regime"] = trades["regime_at_order"]
    else:
        offline = regime_table(pair)
        trades = pd.merge_asof(
            trades.sort_values("target_dt"),
            offline.sort_values("available_time"),
            left_on="target_dt",
            right_on="available_time",
            direction="backward",
        )
        trades["offline_would_block"] = (
            (trades["offline_regime"].eq("RANGE") & trades["line_entry_type"].eq("breakout"))
            | (
                trades["offline_regime"].isin(
                    ["UP_TREND", "DOWN_TREND", "UP_TREND_START", "DOWN_TREND_START"]
                )
                & trades["direction"].ne(trades["offline_trend_direction"])
            )
        )
        regime_agreement = None
        block_agreement = None
        trades["would_block"] = trades["offline_would_block"]
        trades["regime"] = trades["offline_regime"]

    result = {
        "pair": pair,
        "has_saved_regime": has_saved,
        "offline_saved_regime_agreement": regime_agreement,
        "offline_saved_block_agreement": block_agreement,
        "all": metrics(trades),
        "retained": metrics(trades[~trades["would_block"]]),
        "blocked": metrics(trades[trades["would_block"]]),
        "by_regime": grouped_metrics(trades, ["regime"]),
        "by_regime_entry": grouped_metrics(trades, ["regime", "line_entry_type"]),
        "by_regime_direction": grouped_metrics(trades, ["regime", "direction"]),
        "by_block": grouped_metrics(trades, ["would_block"]),
        "by_order_mode": grouped_metrics(trades, ["line_order_mode"]),
    }
    return result


def main():
    results = [load_pair(pair) for pair in PAIRS]
    print(json.dumps(results, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
