# 最新更新日時: 2026-08-30 13:46 JST
"""共有 CandleAnalysis だけを使う、ダブルトップ試行版。

T1 は時間的に古い高値、N はその後の安値（ネックライン）、T2 は新しい
高値とする。T2 を付けただけでは未完成で、判断時刻までに完成した M5 の
終値が N を初めて下抜けた時点でダブルトップを確定する。

検出と注文生成を別ファイルへ分けず、このファイル内にまとめる。データ取得や
Peaks の再計算は行わず、CandleAnalysis.require_basic_analysis() が保証した
完成足と ca.basic_analysis.m5_peaks_class だけを利用する。
"""

from dataclasses import dataclass
import math

import pandas as pd

import classOrderCreate as OCreate
import fCandleDataQuality as candle_quality


ORIGIN = "double_top"
VERSION = "trial_v1"
FALLBACK_USD_JPY_RATE = 160.0


@dataclass(frozen=True)
class DoubleTopTrialPolicy:
    """未検証の初期候補。検証後はこの値だけを入れ替えられるようにする。"""

    min_top_foot_count: int = 2
    min_height_pips: float = 6.0
    max_height_pips: float = 60.0
    min_t1_t2_minutes: float = 15.0
    max_t1_t2_minutes: float = 360.0
    base_top_tolerance_pips: float = 3.0
    top_tolerance_height_ratio: float = 0.20
    neckline_break_buffer_pips: float = 0.0
    stop_buffer_pips: float = 1.0
    min_order_distance_pips: float = 1.0
    risk_yen: float = 50.0
    priority: int = 5
    trade_timeout_min: int = 240


TRIAL_POLICY = DoubleTopTrialPolicy()


@dataclass(frozen=True)
class DoubleTopCandidate:
    t1_time: pd.Timestamp
    neckline_time: pd.Timestamp
    t2_time: pd.Timestamp
    break_time: pd.Timestamp
    t1_price: float
    neckline_price: float
    t2_price: float
    break_close: float
    previous_close: float
    t1_foot_count: int
    t2_foot_count: int
    decline_foot_count: int
    top_gap_pips: float
    top_tolerance_pips: float
    height_pips: float
    t1_t2_minutes: float
    projected_target_price: float


def _local_timestamp(value):
    stamp = pd.Timestamp(value)
    if pd.isna(stamp):
        raise ValueError("double top contains an invalid time")
    if stamp.tzinfo is not None:
        stamp = stamp.tz_convert("Asia/Tokyo").tz_localize(None)
    return stamp.floor("s")


def _peak_time(peak):
    return _local_timestamp(
        peak.get("latest_time_jp", peak.get("time"))
    )


def _peak_price(peak):
    return float(peak.get("peak", peak.get("latest_body_peak_price")))


def _foot_count(peak):
    return int(float(peak.get("count") or 0))


def _direction(peak):
    return int(float(peak.get("direction") or 0))


def _row_time(row):
    value = row.get("time_jp_dt")
    if value is None or pd.isna(value):
        value = row.get("time_jp")
    return _local_timestamp(value)


def detect_candidate(context, policy=TRIAL_POLICY):
    """共有済みの完成足と M5 Peaks から、確定直後の一件だけを返す。

    peaks_original は最新側から並ぶ。ネックライン割れ直後は、先頭から
    ``T2後の下落(-1), T2(+1), N(-1), T1(+1)`` という並びになる。
    最新完成足とその一つ前の終値を比べ、過去の割れを再通知しない。
    """
    peaks_class = context.m5_peaks_class
    peaks = list(getattr(peaks_class, "peaks_original", ()) or ())
    completed_df_r = context.m5_completed_df_r
    if len(peaks) < 4 or completed_df_r is None or len(completed_df_r) < 2:
        return None

    decline, t2, neckline, t1 = peaks[:4]
    if tuple(map(_direction, (decline, t2, neckline, t1))) != (-1, 1, -1, 1):
        return None

    t1_foot_count = _foot_count(t1)
    t2_foot_count = _foot_count(t2)
    if (
            t1_foot_count < policy.min_top_foot_count
            or t2_foot_count < policy.min_top_foot_count
    ):
        return None

    t1_time = _peak_time(t1)
    neckline_time = _peak_time(neckline)
    t2_time = _peak_time(t2)
    latest_row = completed_df_r.iloc[0]
    previous_row = completed_df_r.iloc[1]
    break_time = _row_time(latest_row)
    if not (t1_time < neckline_time < t2_time < break_time):
        return None

    t1_t2_minutes = (t2_time - t1_time).total_seconds() / 60.0
    if not (
            policy.min_t1_t2_minutes
            <= t1_t2_minutes
            <= policy.max_t1_t2_minutes
    ):
        return None

    t1_price = _peak_price(t1)
    neckline_price = _peak_price(neckline)
    t2_price = _peak_price(t2)
    values = (t1_price, neckline_price, t2_price)
    if not all(math.isfinite(value) for value in values):
        raise ValueError("double top contains an invalid peak price")
    if neckline_price >= min(t1_price, t2_price):
        return None

    pair = context.pair
    top_reference_price = (t1_price + t2_price) / 2.0
    height_price = top_reference_price - neckline_price
    height_pips = pair.price_to_pips(height_price)
    if not policy.min_height_pips <= height_pips <= policy.max_height_pips:
        return None

    top_gap_pips = pair.price_to_pips(abs(t1_price - t2_price))
    top_tolerance_pips = max(
        policy.base_top_tolerance_pips,
        height_pips * policy.top_tolerance_height_ratio,
    )
    if top_gap_pips > top_tolerance_pips:
        return None

    break_close = float(latest_row["close"])
    previous_close = float(previous_row["close"])
    if not math.isfinite(break_close) or not math.isfinite(previous_close):
        raise ValueError("double top contains an invalid completed close")
    break_threshold = neckline_price - pair.pips_to_price(
        policy.neckline_break_buffer_pips
    )
    if not (break_close < break_threshold <= previous_close):
        return None

    projected_target_price = pair.round_price(
        neckline_price - height_price
    )
    return DoubleTopCandidate(
        t1_time=t1_time,
        neckline_time=neckline_time,
        t2_time=t2_time,
        break_time=break_time,
        t1_price=t1_price,
        neckline_price=neckline_price,
        t2_price=t2_price,
        break_close=break_close,
        previous_close=previous_close,
        t1_foot_count=t1_foot_count,
        t2_foot_count=t2_foot_count,
        decline_foot_count=_foot_count(decline),
        top_gap_pips=top_gap_pips,
        top_tolerance_pips=round(top_tolerance_pips, 2),
        height_pips=height_pips,
        t1_t2_minutes=t1_t2_minutes,
        projected_target_price=projected_target_price,
    )


def _usd_jpy_rate_for(pair, candle_analysis_class, mode):
    """クロス通貨のリスク計算用。検証時には現在の相場を参照しない。"""
    if str(pair).upper() == "USD_JPY":
        return None
    if str(mode) == "live":
        oa = getattr(candle_analysis_class, "base_oa", None)
        if oa is not None:
            try:
                response = oa.NowPrice_exe("USD_JPY")
                if response.get("error") == 0:
                    rate = float(response["data"]["mid"])
                    if math.isfinite(rate) and rate > 0:
                        return rate
            except Exception as error:
                # 軽度な通信エラーでは通知せず、このサイクルだけ既定値へ退避する。
                print("[double_top] USD_JPYレート取得失敗、既定値を使用:", error)
    return FALLBACK_USD_JPY_RATE


def _candidate_metadata(candidate):
    return {
        "source": ORIGIN,
        "double_top_version": VERSION,
        "double_top_t1_time": candidate.t1_time.strftime("%Y/%m/%d %H:%M:%S"),
        "double_top_n_time": candidate.neckline_time.strftime("%Y/%m/%d %H:%M:%S"),
        "double_top_t2_time": candidate.t2_time.strftime("%Y/%m/%d %H:%M:%S"),
        "double_top_break_time": candidate.break_time.strftime("%Y/%m/%d %H:%M:%S"),
        "double_top_t1_price": candidate.t1_price,
        "double_top_n_price": candidate.neckline_price,
        "double_top_t2_price": candidate.t2_price,
        "double_top_break_close": candidate.break_close,
        "double_top_previous_close": candidate.previous_close,
        "double_top_t1_foot_count": candidate.t1_foot_count,
        "double_top_t2_foot_count": candidate.t2_foot_count,
        "double_top_decline_foot_count": candidate.decline_foot_count,
        "double_top_top_gap_pips": candidate.top_gap_pips,
        "double_top_top_tolerance_pips": candidate.top_tolerance_pips,
        "double_top_height_pips": candidate.height_pips,
        "double_top_t1_t2_minutes": candidate.t1_t2_minutes,
        "double_top_projection_target": candidate.projected_target_price,
    }


def build_order(
        candidate,
        context,
        candle_analysis_class,
        mode,
        policy=TRIAL_POLICY,
):
    """確定したダブルトップを、N-Hを狙う成行売りへ変換する。"""
    pair = context.pair
    pair_name = context.pair_name
    entry_price = pair.round_price(float(context.current_price))
    target_price = pair.round_price(candidate.projected_target_price)
    stop_price = pair.round_price(
        max(candidate.t1_price, candidate.t2_price)
        + pair.pips_to_price(policy.stop_buffer_pips)
    )
    if not all(
            math.isfinite(value)
            for value in (entry_price, target_price, stop_price)
    ):
        raise ValueError("double top order contains an invalid price")

    tp_pips = pair.price_to_pips(entry_price - target_price)
    lc_pips = pair.price_to_pips(stop_price - entry_price)
    if (
            tp_pips < policy.min_order_distance_pips
            or lc_pips < policy.min_order_distance_pips
    ):
        # N-Hへ既に到達済み、またはトップ上まで戻った後なら追いかけない。
        return None

    decision_time = context.decision_time.strftime("%Y/%m/%d %H:%M:%S")
    order_class = OCreate.Order({
        "name": "DoubleTopTrial",
        "pair": pair_name,
        "origin": ORIGIN,
        "current_price": entry_price,
        "target": entry_price,
        "direction": -1,
        "type": "MARKET",
        "order_permission": True,
        "tp": target_price,
        "lc": stop_price,
        "lc_change": [],
        "risk_yen": policy.risk_yen,
        "usd_jpy_rate": _usd_jpy_rate_for(
            pair_name,
            candle_analysis_class,
            mode,
        ),
        "priority": policy.priority,
        "decision_time": decision_time,
        "order_timeout_min": 0,
        "trade_timeout_min": policy.trade_timeout_min,
        "candle_analysis_class": candle_analysis_class,
        "memo": (
            f"double top trial: H={candidate.height_pips:.1f}p, "
            f"top gap={candidate.top_gap_pips:.1f}p, "
            f"TP={tp_pips:.1f}p, LC={lc_pips:.1f}p"
        ),
    })
    # Order の標準項目以外も検証結果へ残し、条件変更時に比較できるようにする。
    order_class.exe_order_plan.update(_candidate_metadata(candidate))
    order_class.exe_order_plan["risk_yen"] = policy.risk_yen
    order_class.exe_order_plan["double_top_entry_price"] = entry_price
    order_class.exe_order_plan["double_top_tp_pips"] = tp_pips
    order_class.exe_order_plan["double_top_lc_pips"] = lc_pips
    return order_class


def build_orders_for_decision(
        candle_analysis_class,
        mode="inspection",
        policy=TRIAL_POLICY,
):
    """共有スナップショットから注文を一件作る。該当なしは空リスト。"""
    try:
        context = candle_analysis_class.require_basic_analysis()
    except candle_quality.CandleHistoryNotReady:
        # 足確定の公開待ちや正規休場は軽度な状態。通知せず次の周期へ回す。
        return []
    candidate = detect_candidate(context, policy)
    if candidate is None:
        return []
    order_class = build_order(
        candidate,
        context,
        candle_analysis_class,
        mode,
        policy,
    )
    return [order_class] if order_class is not None else []
