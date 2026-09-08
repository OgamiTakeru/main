# 最新更新日時: 2026-09-08 04:15 JST
"""抵抗線ブレイクで出るはずの注文を、リアルタイムに**表示する**。

## 何をするか

5分ごとに、3通貨（AUD_USD / EUR_USD / USD_JPY）について
M5 と M30 の抵抗線・支持線を組み立て、**検証（2023-2025の2年）と同じ条件**で
出すはずの逆指値注文を算出して表示する。

チャートを見ながら「今この線でこの注文が出るはず」を確かめるための道具。

## ★このモジュールは注文に一切触れない

**発注・取消・決済は行わない。** 以前ここから OANDA へ直接発注していたが、
`classPositionControl` を通らないため次の事故を起こす作りだった：

- 5分ごとに `OrderCancel_All_exe(pair)` を呼び、**flip や手動の注文まで
  巻き込んで取り消していた**
- 60分経過した建玉を、**どの戦略が建てたかを問わず決済していた**

原因は、自分が出した注文の身元を持っていなかったこと。
本番の経路では `classPosition` が注文オブジェクトと `o_id` を保持し、
自分のものだけを操作する。本番相当の解析・注文組み立ては
`fResistanceBreakoutAnalysis` を `fAnalysis_order_Main` の解析登録から呼ぶ。
現在はtrialなので、Discord通知までは行うが実発注はしない。

保有時間切れの決済（`classPosition.trade_timeout_hard_close`）も
未約定注文の期限切れ（`classPosition.waiting_order_expired`）も
既に本番側にあり、flip が同じ60分の形で使っている。作り直す必要はない。

**ユーザーは実行引数を使わない。** 起動は
``test_kick_resistance_watch.py`` から行い、設定はそのファイルの冒頭に
定数として書いてある。

## 検証と揃えている条件

| 項目 | 値 | 由来 |
|---|---|---|
| 起動 | M5 の最新ピークの foot count が 2 | `count2_resistance_sweep` と同じ |
| ライン足 | M5 と M30（H1 は対象外） | ユーザー指定 |
| ライン窓 | 60本（各足） | `LINE_HISTORY_BARS` |
| ピーク窓 | 180本（各足） | `PEAK_HISTORY_BARS` |
| ピーク強度 | 2以上に絞る | `--enforce-peak-strength` |
| グループ化幅 | 0.5A（その足自身のA） | `--group-threshold-a 0.5` |
| **向き** | **線の側に合うピークが7割以上** | **2年検証で確定したルール** |
| **peaks count** | **2以上** | **同上** |
| 注文 | 線から1.0pips先へ STOP | `--stop-offset-pips 1.0` |
| 利確 | 3.0 × A(M5直近6本) | `TP_MULTIPLIER` |
| 損切り | 利確 ÷ 1.2 | `RR` |
| 保有 | 60分で手仕舞い（※下記の注意） | `--horizon-minutes 60` |

A は「その足の直前6本の平均レンジ」。判断時刻までに**完成した足だけ**から
計算する（先読みを避けるため）。

## 検証結果についての注意（発注前に読むこと）

**2年間の検証では、この条件は儲かっていない。** リスク正規化した R で見ると：

| 足 | R/回 | 判定 | 500円リスクなら2年で |
|---|---|---|---|
| M5 | −0.042 | **有意にマイナス** | −353,184円 |
| M30 | −0.001 | 誤差の範囲 | −1,218円 |
| H1 | −0.037 | **有意にマイナス** | −79,742円 |

**M5 は期待値がマイナスと分かっている。** それでも実際の値動きと
突き合わせる価値があるため、両方を出せるようにしてある。
M30 だけに絞りたい場合は起動ファイルの ``TIMEFRAMES`` を ``("M30",)`` にする。

pips で見ると M5 −0.166 / M30 +0.438 で「誤差の範囲」に見えるが、
pips は建玉を考えないためボラティリティに引きずられて鈍い。
**判定は R、実額の確認は円**で行うこと。

## 建玉の表示について

表示する建玉は「許容損失500円」と「上限3,000ユニット」の厳しい方。
検証は1回50円リスク固定・上限なしだったので、**実運用の数字は
検証とそのまま一致しない**。上限に当たるのは損切りが狭い取引で、
それらは成績が悪いため（M30で −14.9円/回、当たらない方は +18.5円/回）、
上限は負けを小さくする方向に働く。戦略が良くなるわけではない。
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import contextlib
import json
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import classCandlePeaks as ccp
import classOanda
import fGeneric as gene
import fLineAnalysis as fla
import fResistanceBreakoutCore as breakout_core
import tokens as tk
from classCandleAnalysis import CandleTimeframeBundle

PAIRS = ("AUD_USD", "EUR_USD", "USD_JPY")
TIMEFRAME_MINUTES = {"M5": 5, "M30": 30}
LINE_HISTORY_BARS = 60
PEAK_HISTORY_BARS = 180
TP_LOOKBACK = 6
TP_MULTIPLIER = 3.0
RR = 1.2
STOP_OFFSET_PIPS = 1.0
GROUP_THRESHOLD_A = 0.5
MIN_LINE_DIRECTION_RATIO = 0.7
MIN_LINE_PEAK_COUNT = 2
RISK_YEN = 500.0
HORIZON_MINUTES = 60
SPREAD_PIPS = 0.8
# 利確がスプレッドに対して小さすぎる注文を出さないための下限。
# 検証（2年）では TP がスプレッドの3倍未満だった約定は 0.2% しかなく、
# ここを弾いても検証結果は実質変わらない。逆に、早朝など A が潰れた場面では
# TP 1.8pips のような注文が出てしまい、これは検証に存在しない領域になる。
MIN_TP_SPREAD_RATIO = 3.0
# 建玉の上限。損切りが狭いと、500円を埋めるのに数万ユニット必要になる。
# 実測で A=0.60pips のとき 21,332 ユニット（名目387万円）まで膨らんだ。
MAX_UNITS = 3000


class _PairNameHolder:
    """LineStrengthCal は candle_analysis_class.pair を通貨名の文字列として読む。

    PeaksClass の pair は CurrencyPair オブジェクトなので、そのままでは
    `gene.currency_pair()` に渡せず落ちる。名前だけ差し替えて他は委譲する。
    """

    def __init__(self, peaks_class: Any, pair_name: str) -> None:
        self._peaks_class = peaks_class
        self.pair = pair_name

    def __getattr__(self, name: str) -> Any:
        return getattr(self._peaks_class, name)


def average_range_pips(frame: pd.DataFrame, pair: gene.CurrencyPair) -> float | None:
    """直前 TP_LOOKBACK 本の平均レンジ（A）。完成足だけを渡すこと。"""
    completed_df_r = frame.iloc[::-1].reset_index(drop=True)
    return breakout_core.average_range_pips_from_completed_df_r(
        completed_df_r,
        pair,
        TP_LOOKBACK,
    )


def fetch_completed(
    oanda: classOanda.Oanda,
    pair_name: str,
    granularity: str,
    count: int,
) -> pd.DataFrame:
    """完成した足だけを新しい順ではなく時間昇順で返す。"""
    with contextlib.redirect_stdout(io.StringIO()):
        response = oanda.InstrumentsCandles_multi_exe(
            pair_name,
            {"granularity": granularity, "count": int(count)},
            1,
        )
    if response.get("error") != 0:
        raise RuntimeError(f"{pair_name} {granularity} の取得に失敗しました")
    frame = response["data"].copy()
    if "time_jp_dt" not in frame.columns:
        frame["time_jp_dt"] = pd.to_datetime(frame["time_jp"])
    frame = frame[frame["is_complete"] == True]  # noqa: E712
    return frame.reset_index(drop=True)


def build_lines(
    frame: pd.DataFrame,
    granularity: str,
    pair: gene.CurrencyPair,
    current_price: float,
) -> tuple[Any, float]:
    """検証と同じ設定でラインを組み立てる。戻り値は (LineStrengthCal, A)。"""
    minutes = TIMEFRAME_MINUTES[granularity]
    window = frame.iloc[-max(LINE_HISTORY_BARS, PEAK_HISTORY_BARS):]
    a_pips = average_range_pips(window, pair)
    if a_pips is None or a_pips <= 0:
        raise ValueError(f"{granularity} のAが計算できません")
    reversed_frame = window.iloc[::-1].reset_index(drop=True)
    decision_time = window["time_jp_dt"].iloc[-1] + dt.timedelta(minutes=minutes)
    with contextlib.redirect_stdout(io.StringIO()):
        peaks = ccp.PeaksClass(
            reversed_frame,
            granularity,
            current_price,
            pair=pair,
            completed_df_r=reversed_frame,
            decision_time=decision_time,
            analysis_num=PEAK_HISTORY_BARS,
        )
        bundle = CandleTimeframeBundle(
            timeframe=granularity,
            duration=pd.Timedelta(minutes=minutes),
            original_df_r=reversed_frame,
            completed_df_r=reversed_frame,
            peaks_class=peaks,
            source_granularity=granularity,
        )
        lines = fla.LineStrengthCal(
            _PairNameHolder(peaks, pair.name),
            granularity,
            LINE_HISTORY_BARS,
            enforce_peak_strength_filter=True,
            min_line_peak_count=MIN_LINE_PEAK_COUNT,
            group_threshold_pips=GROUP_THRESHOLD_A * a_pips,
            min_line_direction_ratio=MIN_LINE_DIRECTION_RATIO,
            timeframe_bundle=bundle,
        )
    return lines, a_pips


def newest_m5_peak(
    frame: pd.DataFrame,
    pair: gene.CurrencyPair,
    current_price: float,
) -> dict[str, Any] | None:
    """M5 の最新ピークを返す。起動判定（foot count == 2）に使う。"""
    window = frame.iloc[-PEAK_HISTORY_BARS:]
    reversed_frame = window.iloc[::-1].reset_index(drop=True)
    decision_time = window["time_jp_dt"].iloc[-1] + dt.timedelta(minutes=5)
    with contextlib.redirect_stdout(io.StringIO()):
        peaks = ccp.PeaksClass(
            reversed_frame,
            "M5",
            current_price,
            pair=pair,
            completed_df_r=reversed_frame,
            decision_time=decision_time,
            analysis_num=PEAK_HISTORY_BARS,
        )
    if not peaks.peaks_original:
        return None
    return peaks.peaks_original[0]


def plan_orders(
    pair_name: str,
    oanda: classOanda.Oanda,
    usd_jpy_rate: float | None,
    timeframes: tuple[str, ...],
) -> dict[str, Any]:
    """1通貨ぶんの注文案を作る。起動条件を満たさなければ空で返す。"""
    pair = gene.currency_pair(pair_name)
    m5 = fetch_completed(oanda, pair_name, "M5", PEAK_HISTORY_BARS + 20)
    current_price = float(m5.iloc[-1]["close"])
    result: dict[str, Any] = {
        "pair": pair_name,
        "current_price": current_price,
        "orders": [],
        "skip_reason": None,
    }

    peak = newest_m5_peak(m5, pair, current_price)
    trigger_decision = breakout_core.evaluate_breakout_trigger(peak, 2)
    result["m5_peak_foot_count"] = trigger_decision["trigger_foot_count"]
    result["m5_peak_time"] = str(trigger_decision["peak_time"])
    if not trigger_decision["trigger_valid"]:
        if trigger_decision["trigger_skip_reason"] == "no_m5_peak":
            result["skip_reason"] = "M5のピークが取れない"
        else:
            result["skip_reason"] = (
                "M5最新ピークの足数が"
                + str(trigger_decision["trigger_foot_count"])
                + "（起動は2のみ）"
            )
        return result

    peak_direction = int(trigger_decision["peak_direction"])
    result["peak_direction"] = peak_direction
    # 利確・損切りは M5 の A から決める（検証と同じ）。
    decision_time = pd.Timestamp(m5.iloc[-1]["time_jp_dt"]) + pd.Timedelta(
        minutes=5
    )
    target = breakout_core.target_parameters(
        m5.iloc[::-1].reset_index(drop=True),
        decision_time,
        pair,
        TP_LOOKBACK,
        TP_MULTIPLIER,
        RR,
    )
    if not target["target_valid"]:
        result["skip_reason"] = "M5のAが計算できない"
        return result
    a_m5 = float(target["recent_m5_avg_range_pips"])
    tp_pips = float(target["tp_pips"])
    lc_pips = float(target["lc_pips"])
    result["a_m5_pips"] = a_m5
    result["tp_pips"] = tp_pips
    result["lc_pips"] = lc_pips

    # 利確がスプレッドに対して小さすぎる場面は、検証にほぼ存在しない領域。
    # ここで見送らないと、細い損切りから巨大な建玉が生まれる。
    if not breakout_core.live_target_is_wide_enough(
        tp_pips,
        SPREAD_PIPS,
        MIN_TP_SPREAD_RATIO,
    ):
        result["skip_reason"] = (
            f"利確{tp_pips:.1f}pipsがスプレッド{SPREAD_PIPS}pipsの"
            f"{tp_pips / SPREAD_PIPS:.1f}倍しかない"
            f"（下限{MIN_TP_SPREAD_RATIO:g}倍）"
        )
        result["skip_kind"] = "narrow_tp"
        return result

    for granularity in timeframes:
        bars = fetch_completed(
            oanda,
            pair_name,
            granularity,
            max(LINE_HISTORY_BARS, PEAK_HISTORY_BARS) + 20,
        )
        try:
            lines, a_line = build_lines(bars, granularity, pair, current_price)
        except ValueError as error:
            result["orders"].append(
                {"timeframe": granularity, "skip_reason": str(error)}
            )
            continue
        candidates = breakout_core.select_ahead_lines(
            peak_direction,
            current_price,
            lines.upper_lines,
            lines.lower_lines,
            pair,
            entry_mode="stop",
            average_range_pips=a_line,
        )
        for candidate in candidates:
            line = candidate["line"]
            line_price = candidate["line_price"]
            trade_direction = candidate["trade_direction"]
            distance_pips = candidate["distance_pips"]
            levels = breakout_core.build_stop_order_levels(
                line_price,
                trade_direction,
                tp_pips,
                lc_pips,
                pair,
                STOP_OFFSET_PIPS,
            )
            risk_units = gene.calculate_units(
                pair,
                pair.pips_to_price(lc_pips),
                RISK_YEN,
                "l",
                usd_jpy_rate,
            )
            # 500円の許容損失と、建玉の上限。厳しい方を採る。
            units = min(risk_units, MAX_UNITS)
            capped = units < risk_units
            # 上限に当たった場合、実際に取るリスクは500円より小さくなる。
            yen_per_pip = pair.pip_value * (
                1.0 if pair.name == "USD_JPY" else float(usd_jpy_rate or 0)
            )
            actual_risk_yen = units * lc_pips * yen_per_pip
            ratio = breakout_core.native_direction_ratio(
                line,
                1 if candidate["line_side"] == "upper" else -1,
            )
            result["orders"].append(
                {
                    "timeframe": granularity,
                    "candidate_rank": candidate["candidate_rank"],
                    "line_side": candidate["line_side"],
                    "trade_side": candidate["trade_side"],
                    "line_price": line_price,
                    "trigger_price": levels.trigger_price,
                    "tp_price": levels.tp_price,
                    "lc_price": levels.lc_price,
                    "units": units,
                    "units_uncapped": risk_units,
                    "units_capped": capped,
                    "risk_yen": round(actual_risk_yen, 1),
                    "distance_pips": round(distance_pips, 1),
                    "distance_a": round(distance_pips / a_m5, 2),
                    "peaks_count": int(line.get("count", 0)),
                    "total_strength": line.get("total_strength"),
                    "direction_ratio": None if ratio is None else round(ratio, 2),
                    "line_a_pips": round(a_line, 2),
                    "newest_peak_time": str(line.get("newest_time"))[5:16],
                    "oldest_peak_time": str(line.get("oldest_time"))[5:16],
                }
            )
    return result


def render(plan: dict[str, Any]) -> None:
    pair_name = plan["pair"]
    price = plan["current_price"]
    if plan.get("skip_reason"):
        mark = "⚠ " if plan.get("skip_kind") == "narrow_tp" else ""
        print(
            f"  {pair_name}  {price:<10}  {mark}見送り: {plan['skip_reason']}"
        )
        return
    print(
        f"  {pair_name}  現在値 {price}  "
        f"A(M5)={plan['a_m5_pips']:.2f}pips  "
        f"TP={plan['tp_pips']:.1f}pips  LC={plan['lc_pips']:.1f}pips  "
        f"count2方向={'上' if plan['peak_direction'] == 1 else '下'}"
        f"（{plan['m5_peak_time']}）"
    )
    orders = [o for o in plan["orders"] if "skip_reason" not in o]
    if not orders:
        print("      条件を満たす線なし")
    for order in orders:
        print(
            f"      [{order['timeframe']:<3}] {order['trade_side']:<4} "
            f"STOP {order['trigger_price']}  "
            f"(線 {order['line_price']}, {order['distance_pips']:+.1f}pips "
            f"= {order['distance_a']}A)  "
            f"TP {order['tp_price']}  LC {order['lc_price']}  "
            f"{order['units']:,}ユニット"
            + (
                f"（上限{MAX_UNITS:,}で頭打ち。本来{order['units_uncapped']:,}／"
                f"実リスク{order['risk_yen']:.0f}円）"
                if order["units_capped"]
                else f"（リスク{order['risk_yen']:.0f}円）"
            )
            + f"  peaks={order['peaks_count']} 強度={order['total_strength']} "
            f"向き={order['direction_ratio']}"
        )


def run(
    *,
    timeframes: tuple[str, ...] = tuple(TIMEFRAME_MINUTES),
    pairs: tuple[str, ...] = PAIRS,
    risk_yen: float = RISK_YEN,
    max_units: int = MAX_UNITS,
    min_tp_spread_ratio: float = MIN_TP_SPREAD_RATIO,
    horizon_minutes: int = HORIZON_MINUTES,
    interval_seconds: int = 300,
    once: bool = False,
) -> None:
    """監視を開始する。**表示のみで、注文には一切触れない。**

    起動ファイルからは実行引数なしでこれを呼ぶ。
    実発注は `fResistanceOrder` を作って `classPositionControl` に載せる
    （このモジュールから直接 OANDA へ発注してはいけない）。
    """
    timeframes = tuple(timeframes)
    pairs = tuple(p.upper() for p in pairs)
    globals()["RISK_YEN"] = float(risk_yen)
    globals()["MAX_UNITS"] = int(max_units)
    globals()["MIN_TP_SPREAD_RATIO"] = float(min_tp_spread_ratio)

    # 価格の取得しかしないので、口座はどれでもよい。デモを使う。
    oanda = classOanda.Oanda(tk.accountID, tk.access_token, tk.environment)

    print("=" * 78)
    print(
        "抵抗線ブレイク 監視（表示のみ・注文には一切触れない）  "
        f"許容損失={RISK_YEN:.0f}円/回  建玉上限={MAX_UNITS:,}ユニット  "
        f"利確下限=スプレッドの{MIN_TP_SPREAD_RATIO:g}倍"
    )
    print(f"対象: {', '.join(pairs)}   ライン足: {', '.join(timeframes)}")
    print(
        "条件: M5最新ピークの足数=2 / 線窓60本 / ピーク強度2以上 / "
        "グループ化0.5A / 向き7割以上 / peaks2以上 / "
        f"STOP {STOP_OFFSET_PIPS}pips先 / TP {TP_MULTIPLIER}A / RR {RR}"
    )
    if "M5" in timeframes:
        print(
            "  ※ M5 は2年検証でランダムより有意に悪い（R −0.042/回）。"
        )
    print(
        f"  ※ 約定から{horizon_minutes}分で手仕舞いする（検証と同じ）。"
        "検証では約46%がこの時間切れで決着していた。"
    )
    print("=" * 78)

    while True:
        now = dt.datetime.now()
        print(f"\n--- {now:%Y-%m-%d %H:%M:%S} ---")
        usd_jpy_rate = None
        try:
            usd_jpy = fetch_completed(oanda, "USD_JPY", "M5", 3)
            usd_jpy_rate = float(usd_jpy.iloc[-1]["close"])
        except Exception as error:  # noqa: BLE001
            print(f"  USD_JPY価格の取得に失敗: {error}")

        for pair_name in pairs:
            try:
                plan = plan_orders(pair_name, oanda, usd_jpy_rate, timeframes)
            except Exception as error:  # noqa: BLE001
                print(f"  {pair_name}  エラー: {type(error).__name__}: {error}")
                continue
            render(plan)

        if once:
            break
        time.sleep(max(int(interval_seconds), 5))




if __name__ == "__main__":
    # 直接実行した場合は既定の設定で表示する。
    # 通常は test_kick_resistance_watch.py から起動すること。
    run()
