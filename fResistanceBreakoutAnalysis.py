# 最新更新日時: 2026-09-08 08:09 JST
"""共有CandleAnalysisから抵抗線ブレイクのtrial注文を作る。

ここはCandleAnalysisと純粋関数コアをOrderへつなぐ薄いアダプタ。
Peaksの再計算、ローソク足の再取得、Discord通知、OANDA発注は行わない。
"""

from __future__ import annotations

import contextlib
from dataclasses import replace
import io
from typing import Any

import classOrderCreate as OCreate
import fCandleDataQuality as candle_quality
import fGeneric as gene
import fResistanceBreakoutCore as breakout_core


ORIGIN = "resistance_breakout"
VERSION = breakout_core.ADAPTER_VERSION
# 出自タグはコアに一本化してある。検証側（count2_resistance_sweep）と
# 同じ値でなければ同等性テストが落ちるので、ここで別に定義しないこと。
OWNER_TAG = breakout_core.OWNER_TAG
FALLBACK_USD_JPY_RATE = 160.0


# 監視コードと同じ条件を固定。検証結果から自動で書き換えない。
LIVE_TRIAL_POLICY_V1 = breakout_core.ResistanceBreakoutPolicy(
    policy_id="live_m30_v1",
    # 2026-09-09: M5 を外した。2年検証で M5 は R −0.042/回と有意にマイナス、
    # M30 は R −0.001 でゼロ。M5 はどの軸（時間帯・A帯・向きの比率・距離・
    # 強度・peaks数）で切っても不利で、逆張りに反転しても悪化した。
    # M30 が良いと確認できたわけではない（一度も有意になっていない）が、
    # 負けると分かっている側を外す判断。
    timeframes=("M30",),
    trigger_foot_count=2,
    target_lookback=6,
    target_multiplier=3.0,
    rr=1.2,
    stop_offset_pips=1.0,
    assumed_stop_slippage_pips=0.5,
    spread_pips=0.8,
    min_tp_spread_ratio=3.0,
    line_history_bars=60,
    peak_history_bars=180,
    group_threshold_a=0.5,
    enforce_peak_strength_filter=True,
    min_line_peak_count=2,
    min_line_total_strength=0.0,
    min_line_direction_ratio=0.7,
    min_distance_a=0.0,
    exclude_flipped_recent=False,
    risk_yen=500.0,
    max_units=3000,
    priority=5,
    order_timeout_min=60,
    trade_timeout_min=60,
)


def _expected_bundle_unavailable(error: ValueError) -> bool:
    message = str(error)
    return (
        "timeframe analysis is unavailable" in message
        or "requires native candles" in message
    )


def _line_class_for_bundle(
    candle_analysis_class: Any,
    timeframe: str,
    bundle: Any,
    line_average_range_pips: float,
    policy: breakout_core.ResistanceBreakoutPolicy,
) -> Any:
    """旧MainAnalysisは使わず、既存の抵抗線計算部品だけを再利用する。"""
    # LineStrengthCalは現時点でfLineAnalysisにある。モジュール起動時に
    # 旧MainAnalysisを読み込まず、count2成立時のみ計算クラスを参照する。
    from fLineAnalysis import LineStrengthCal

    group_threshold_pips = (
        float(policy.group_threshold_a) * float(line_average_range_pips)
    )
    with contextlib.redirect_stdout(io.StringIO()):
        return LineStrengthCal(
            candle_analysis_class,
            timeframe,
            policy.line_history_bars,
            enforce_peak_strength_filter=(
                policy.enforce_peak_strength_filter
            ),
            separate_line_directions=False,
            min_line_peak_count=policy.min_line_peak_count,
            group_threshold_pips=group_threshold_pips,
            min_line_total_strength=policy.min_line_total_strength,
            min_line_direction_ratio=policy.min_line_direction_ratio,
            timeframe_bundle=bundle,
        )


def _risk_rate(pair_name: str) -> tuple[float | None, str]:
    """trial用のunits換算値。ここから追加通信は行わない。"""
    if str(pair_name).upper() == "USD_JPY":
        return None, "jpy_quote"
    return FALLBACK_USD_JPY_RATE, "fixed_trial_fallback"


def _actual_risk_yen(
    pair: gene.CurrencyPair,
    units: int,
    lc_pips: float,
    usd_jpy_rate: float | None,
) -> float:
    yen_per_pip_per_unit = pair.pip_value
    if pair.name != "USD_JPY":
        yen_per_pip_per_unit *= float(usd_jpy_rate)
    return float(units) * float(lc_pips) * yen_per_pip_per_unit


def _cap_order_units(order_class: OCreate.Order, max_units: int) -> tuple[int, bool]:
    uncapped_units = int(order_class.units)
    capped_units = min(uncapped_units, int(max_units))
    if capped_units < 1:
        raise ValueError("resistance breakout units must be positive")
    was_capped = capped_units < uncapped_units
    if was_capped:
        order_class.units = capped_units
        order_class.exe_order_plan["units"] = capped_units
        order_class.data["order"]["units"] = str(
            capped_units * int(order_class.direction)
        )
        order_class.exe_order_plan["for_api_json"] = order_class.data
    return uncapped_units, was_capped


def _line_metadata(
    *,
    candidate: dict[str, Any],
    line_class: Any,
    timeframe: str,
    source_granularity: str,
    line_average_range_pips: float,
    target: dict[str, Any],
    trigger: dict[str, Any],
    levels: breakout_core.ResistanceBreakoutOrderLevels,
    policy: breakout_core.ResistanceBreakoutPolicy,
    units_uncapped: int,
    units_capped: bool,
    actual_risk_yen: float,
    risk_rate_source: str,
) -> dict[str, Any]:
    line = candidate["line"]
    native_direction = 1 if candidate["line_side"] == "upper" else -1
    direction_ratio = breakout_core.native_direction_ratio(
        line,
        native_direction,
    )
    m5_average_range = float(target["recent_m5_avg_range_pips"])
    return {
        "source": ORIGIN,
        "resistance_breakout_version": VERSION,
        "resistance_breakout_core_version": breakout_core.CORE_VERSION,
        "resistance_breakout_policy_id": policy.policy_id,
        "resistance_breakout_timeframe": timeframe,
        "line_timeframe": timeframe,
        "line_source_granularity": str(source_granularity).upper(),
        "line_history_bars": int(policy.line_history_bars),
        "peak_history_bars": int(
            getattr(line_class.peaks_class, "analysis_num", policy.peak_history_bars)
        ),
        "configured_peak_history_bars": int(policy.peak_history_bars),
        "trigger_timeframe": "M5",
        "trigger_foot_count": trigger["trigger_foot_count"],
        "trigger_peak_direction": trigger["peak_direction"],
        "trigger_peak_time": trigger["peak_time"],
        "entry_mode": "stop",
        "line_side": candidate["line_side"],
        "line_price": levels.line_price,
        "line_raw_median_price": candidate.get("raw_line_price"),
        "line_core_price": line.get("core_median_price"),
        "line_peak_signature": breakout_core.line_peak_signature(line),
        "resistance_breakout_trigger_price": levels.trigger_price,
        "stop_offset_pips": levels.stop_offset_pips,
        "assumed_stop_slippage_pips": float(
            policy.assumed_stop_slippage_pips
        ),
        "candidate_rank": int(candidate["candidate_rank"]),
        "distance_rank": int(candidate["distance_rank"]),
        "distance_pips": float(candidate["distance_pips"]),
        "distance_m5_a": float(candidate["distance_pips"]) / m5_average_range,
        "distance_line_a": (
            float(candidate["distance_pips"])
            / float(line_average_range_pips)
        ),
        # peak countはラインを構成するピーク数。foot countと混ぜない。
        "line_peaks_count": int(line.get("count") or 0),
        "line_core_peak_count": int(line.get("core_count") or 0),
        # 既存Inspection列との互換名。意味は上のpeaks/core peakと同じ。
        "line_count": int(line.get("count") or 0),
        "core_count": int(line.get("core_count") or 0),
        "line_total_strength": line.get("total_strength"),
        "line_ave_strength": line.get("ave_strength"),
        # 線の値幅（構成ピークの最高と最安の差、pips）。
        # 同じ peaks 数でも、狭く集まった線と散らばった線では意味が違う。
        # グループ化幅が 0.5A なので上限は 0.5A。
        "line_price_gap_pips": line.get("price_gap"),
        "line_core_total_strength": line.get("core_total_strength"),
        "core_total_strength": line.get("core_total_strength"),
        "line_is_flipped": line.get("is_flipped_line"),
        "line_direction_ratio": direction_ratio,
        "line_average_range_pips": float(line_average_range_pips),
        "group_threshold_pips": float(line_class.threshold),
        "line_newest_peak_time": line.get("newest_time"),
        "line_oldest_peak_time": line.get("oldest_time"),
        "m5_average_range_pips": m5_average_range,
        "tp_pips": levels.tp_pips,
        "lc_pips": levels.lc_pips,
        "configured_risk_yen": float(policy.risk_yen),
        "actual_risk_yen": round(float(actual_risk_yen), 1),
        "max_units": int(policy.max_units),
        "units_uncapped": int(units_uncapped),
        "units_capped": bool(units_capped),
        "risk_rate_source": risk_rate_source,
    }


def build_order(
    *,
    candidate: dict[str, Any],
    line_class: Any,
    timeframe: str,
    source_granularity: str,
    line_average_range_pips: float,
    target: dict[str, Any],
    trigger: dict[str, Any],
    context: Any,
    candle_analysis_class: Any,
    policy: breakout_core.ResistanceBreakoutPolicy,
) -> OCreate.Order:
    """一本の前方ラインをSTOPのtrial注文へ変換する。"""
    levels = breakout_core.build_stop_order_levels(
        candidate["line_price"],
        candidate["trade_direction"],
        target["tp_pips"],
        target["lc_pips"],
        context.pair,
        policy.stop_offset_pips,
    )
    decision_time = context.decision_time.strftime("%Y/%m/%d %H:%M:%S")
    usd_jpy_rate, risk_rate_source = _risk_rate(context.pair_name)
    order_class = OCreate.Order({
        "name": (
            "ResistanceBreakout_"
            + timeframe
            + "_"
            + str(candidate["candidate_rank"])
        ),
        "pair": context.pair_name,
        "origin": ORIGIN,
        "owner_tag": OWNER_TAG,
        "current_price": float(context.current_price),
        "target": levels.trigger_price,
        "direction": levels.trade_direction,
        "type": "STOP",
        # 発注可否もコアに一本化してある（理由はコア側のコメント）。
        "order_permission": breakout_core.ORDER_PERMISSION,
        "tp": levels.tp_price,
        "lc": levels.lc_price,
        "lc_change": [],
        "risk_yen": float(policy.risk_yen),
        "usd_jpy_rate": usd_jpy_rate,
        "priority": int(policy.priority),
        "decision_time": decision_time,
        "order_timeout_min": int(policy.order_timeout_min),
        "trade_timeout_min": int(policy.trade_timeout_min),
        "candle_analysis_class": candle_analysis_class,
        "memo": (
            "resistance breakout trial "
            + timeframe
            + " rank"
            + str(candidate["candidate_rank"])
            + " line="
            + str(levels.line_price)
            + " stop="
            + str(levels.trigger_price)
        ),
    })
    units_uncapped, units_capped = _cap_order_units(
        order_class,
        policy.max_units,
    )
    actual_risk = _actual_risk_yen(
        context.pair,
        order_class.units,
        levels.lc_pips,
        usd_jpy_rate,
    )
    order_class.exe_order_plan.update(_line_metadata(
        candidate=candidate,
        line_class=line_class,
        timeframe=timeframe,
        source_granularity=source_granularity,
        line_average_range_pips=line_average_range_pips,
        target=target,
        trigger=trigger,
        levels=levels,
        policy=policy,
        units_uncapped=units_uncapped,
        units_capped=units_capped,
        actual_risk_yen=actual_risk,
        risk_rate_source=risk_rate_source,
    ))
    return order_class


def build_orders_for_decision(
    candle_analysis_class: Any,
    mode: str = "inspection",
    policy: breakout_core.ResistanceBreakoutPolicy | None = None,
) -> list[OCreate.Order]:
    """共有スナップショットから前方ライン全件のtrial注文を返す。"""
    normalized_mode = str(mode).strip().lower()
    if normalized_mode not in ("inspection", "live"):
        raise ValueError("mode must be inspection or live")
    active_policy = LIVE_TRIAL_POLICY_V1 if policy is None else policy
    try:
        context = candle_analysis_class.require_basic_analysis()
    except candle_quality.CandleHistoryNotReady:
        if normalized_mode == "inspection":
            raise
        return []

    trigger = breakout_core.evaluate_breakout_trigger(
        context.newest_m5_peak,
        active_policy.trigger_foot_count,
    )
    if not trigger["trigger_valid"]:
        return []
    target = breakout_core.target_parameters(
        context.m5_completed_df_r,
        context.decision_time,
        context.pair,
        active_policy.target_lookback,
        active_policy.target_multiplier,
        active_policy.rr,
    )
    if not target["target_valid"]:
        if normalized_mode == "inspection":
            raise candle_quality.CandleHistoryIntegrityError(
                "M5 target parameters are unavailable: "
                + str(target.get("target_skip_reason"))
            )
        return []
    if not breakout_core.live_target_is_wide_enough(
        target["tp_pips"],
        active_policy.spread_pips,
        active_policy.min_tp_spread_ratio,
    ):
        return []

    orders: list[OCreate.Order] = []
    for timeframe in active_policy.timeframes:
        try:
            bundle = candle_analysis_class.get_timeframe_bundle(
                timeframe,
                require_native=True,
            )
        except candle_quality.CandleHistoryNotReady:
            if normalized_mode == "inspection":
                raise
            continue
        except ValueError as error:
            if _expected_bundle_unavailable(error):
                if normalized_mode == "inspection":
                    raise
                continue
            raise

        # nativeであることに加え、対象区間の半分以上が欠ける履歴は使わない。
        # 直近足の多少の遅れ・欠損は共通品質関数の方針どおり許容する。
        required_history_bars = max(
            int(active_policy.line_history_bars),
            int(
                getattr(
                    bundle.peaks_class,
                    "analysis_num",
                    active_policy.peak_history_bars,
                )
            ),
        )
        try:
            validated_completed_df_r = (
                candle_analysis_class.validate_completed_history_for_context(
                    bundle.completed_df_r,
                    context.decision_time,
                    bundle.duration,
                    required_history_bars,
                    timeframe,
                    latest_boundary=timeframe,
                )
            )
        except (
            candle_quality.CandleHistoryNotReady,
            candle_quality.CandleHistoryIntegrityError,
        ):
            if normalized_mode == "inspection":
                raise
            if timeframe == "M5":
                return []
            continue
        bundle = replace(
            bundle,
            completed_df_r=validated_completed_df_r,
        )
        if not getattr(bundle.peaks_class, "peaks_original", None):
            if normalized_mode == "inspection":
                raise candle_quality.CandleHistoryIntegrityError(
                    timeframe + " Peaks is unavailable"
                )
            if timeframe == "M5":
                return []
            continue
        line_average_range = (
            breakout_core.average_range_pips_from_completed_df_r(
                bundle.completed_df_r,
                context.pair,
                active_policy.target_lookback,
            )
        )
        if line_average_range is None:
            if normalized_mode == "inspection":
                raise candle_quality.CandleHistoryIntegrityError(
                    timeframe + " average range is unavailable"
                )
            if timeframe == "M5":
                return []
            continue
        line_class = _line_class_for_bundle(
            candle_analysis_class,
            timeframe,
            bundle,
            line_average_range,
            active_policy,
        )
        candidates = breakout_core.select_ahead_lines(
            trigger["peak_direction"],
            context.current_price,
            line_class.upper_lines,
            line_class.lower_lines,
            context.pair,
            entry_mode="stop",
            average_range_pips=line_average_range,
            min_distance_a=active_policy.min_distance_a,
            exclude_flipped_recent=(
                active_policy.exclude_flipped_recent
            ),
        )
        for candidate in candidates:
            orders.append(build_order(
                candidate=candidate,
                line_class=line_class,
                timeframe=timeframe,
                source_granularity=bundle.source_granularity,
                line_average_range_pips=line_average_range,
                target=target,
                trigger=trigger,
                context=context,
                candle_analysis_class=candle_analysis_class,
                policy=active_policy,
            ))
    return orders
