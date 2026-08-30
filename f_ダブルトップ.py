# 最新更新日時: 2026-08-30 17:44 JST
"""共有CandleAnalysisからDoubleTopを検出し、trial注文を組み立てる。

本番固有の責務は、固定ポリシーの選択、現在価格・換算価格の取得、Order生成
だけに限定する。T1・N・T2、ネックライン割れ、TP・LC価格の意味は
``fDoubleTopCore`` の明示的なv1関数へ固定する。
"""

import math

import classOrderCreate as OCreate
import fCandleDataQuality as candle_quality
import fDoubleTopCore as double_top_core


ORIGIN = "double_top"
VERSION = "trial_v1"
CORE_VERSION = double_top_core.CORE_VERSION_V1
FALLBACK_USD_JPY_RATE = 160.0

DoubleTopTrialPolicy = double_top_core.DoubleTopPolicyV1
DoubleTopCandidate = double_top_core.DoubleTopCandidateV1


# 本番再起動時も検証結果を自動採用しない、明示的に固定したtrialポリシー。
LIVE_TRIAL_POLICY_V1 = DoubleTopTrialPolicy(
    policy_id="live_trial_v1",
    min_top_foot_count=2,
    min_height_pips=6.0,
    max_height_pips=60.0,
    min_t1_t2_minutes=15.0,
    max_t1_t2_minutes=360.0,
    base_top_tolerance_pips=3.0,
    top_tolerance_height_ratio=0.20,
    neckline_break_buffer_pips=0.0,
    target_height_multiplier=1.0,
    stop_buffer_pips=1.0,
    min_order_distance_pips=1.0,
    risk_yen=50.0,
    priority=5,
    trade_timeout_min=240,
)
# 旧コードからの参照互換用。実体は上の固定ポリシーだけにする。
TRIAL_POLICY = LIVE_TRIAL_POLICY_V1


def detect_candidate(context, policy=None):
    """共有contextの完成M5とPeaksを、固定v1コアで判定する。"""
    active_policy = LIVE_TRIAL_POLICY_V1 if policy is None else policy
    peaks = list(
        getattr(context.m5_peaks_class, "peaks_original", ()) or ()
    )
    completed_df_r = context.m5_completed_df_r
    if len(peaks) < 4 or completed_df_r is None or len(completed_df_r) < 2:
        return None
    return double_top_core.detect_candidate_v1(
        peaks,
        completed_df_r.iloc[0],
        completed_df_r.iloc[1],
        context.pair,
        active_policy,
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
                # 軽度な通信エラーでは通知せず、このサイクルの安全な既定値へ退避。
                print("[double_top] USD_JPYレート取得失敗、既定値を使用:", error)
    return FALLBACK_USD_JPY_RATE


def _candidate_metadata(candidate, policy):
    return {
        "source": ORIGIN,
        "double_top_version": VERSION,
        "double_top_core_version": CORE_VERSION,
        "double_top_policy_id": policy.policy_id,
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
        "double_top_n_foot_count": candidate.neckline_foot_count,
        "double_top_t2_foot_count": candidate.t2_foot_count,
        "double_top_decline_foot_count": candidate.decline_foot_count,
        "double_top_top_gap_pips": candidate.top_gap_pips,
        "double_top_top_gap_ratio": candidate.top_gap_ratio,
        "double_top_top_tolerance_pips": candidate.top_tolerance_pips,
        "double_top_height_price": candidate.height_price,
        "double_top_height_pips": candidate.height_pips,
        "double_top_t1_t2_minutes": candidate.t1_t2_minutes,
        "double_top_t2_break_minutes": candidate.t2_break_minutes,
        "double_top_projection_target": candidate.projected_target_price,
    }


def build_order(
        candidate,
        context,
        candle_analysis_class,
        mode,
        policy=None,
):
    """確定したDoubleTopを、共通v1価格計算で一件の売り注文へ変換する。"""
    active_policy = LIVE_TRIAL_POLICY_V1 if policy is None else policy
    levels = double_top_core.build_short_order_levels_v1(
        candidate,
        context.pair,
        context.current_price,
        active_policy,
    )
    if levels is None:
        # N-Hへ到達済み、またはトップ付近まで戻りすぎなら注文しない。
        return None

    decision_time = context.decision_time.strftime("%Y/%m/%d %H:%M:%S")
    order_class = OCreate.Order({
        "name": "DoubleTopTrial",
        "pair": context.pair_name,
        "origin": ORIGIN,
        "current_price": levels.entry_price,
        "target": levels.entry_price,
        "direction": -1,
        "type": "MARKET",
        "order_permission": True,
        "tp": levels.target_price,
        "lc": levels.stop_price,
        "lc_change": [],
        "risk_yen": active_policy.risk_yen,
        "usd_jpy_rate": _usd_jpy_rate_for(
            context.pair_name,
            candle_analysis_class,
            mode,
        ),
        "priority": active_policy.priority,
        "decision_time": decision_time,
        "order_timeout_min": 0,
        "trade_timeout_min": active_policy.trade_timeout_min,
        "candle_analysis_class": candle_analysis_class,
        "memo": (
            f"double top trial: H={candidate.height_pips:.1f}p, "
            f"top gap={candidate.top_gap_pips:.1f}p, "
            f"TP={levels.tp_pips:.1f}p, LC={levels.lc_pips:.1f}p"
        ),
    })
    order_class.exe_order_plan.update(
        _candidate_metadata(candidate, active_policy)
    )
    order_class.exe_order_plan["risk_yen"] = active_policy.risk_yen
    order_class.exe_order_plan["double_top_entry_price"] = levels.entry_price
    order_class.exe_order_plan["double_top_tp_pips"] = levels.tp_pips
    order_class.exe_order_plan["double_top_lc_pips"] = levels.lc_pips
    return order_class


def build_orders_for_decision(
        candle_analysis_class,
        mode="inspection",
        policy=None,
):
    """共有スナップショットから注文候補を一件返す。該当なしは空リスト。"""
    active_policy = LIVE_TRIAL_POLICY_V1 if policy is None else policy
    try:
        context = candle_analysis_class.require_basic_analysis()
    except candle_quality.CandleHistoryNotReady:
        # 市場の確定待ちなど軽度な状態。通知せず次のサイクルへ回す。
        return []
    candidate = detect_candidate(context, active_policy)
    if candidate is None:
        return []
    order_class = build_order(
        candidate,
        context,
        candle_analysis_class,
        mode,
        active_policy,
    )
    return [order_class] if order_class is not None else []
