"""Causal, volatility-normalized shape features for the newest M5 foot-count 2.

``A`` is the mean high-low range of the six completed M5 candles immediately
before the decision.  Callers may pass the already calculated value so live
orders and inspection CSVs use exactly the same normalization base.
"""

from __future__ import annotations

import math
from typing import Any

import pandas as pd


FOOT_COUNT2_SHAPE_VERSION = "foot_count2_shape_a_v1"
REJECTION_MIN_A = 0.25
STALL_MAX_MEAN_BODY_A = 0.35
STALL_MAX_NET_PROGRESS_A = 0.35

FOOT_COUNT2_SHAPE_FIELDS = (
    "version",
    "valid",
    "reason",
    "shape",
    "direction",
    "source_first_time",
    "source_last_time",
    "prior_source_time",
    "a_range_pips",
    "approach_impulse_A",
    "reversal_strength_A",
    "prior_impulse_retrace_ratio",
    "second_close_pushback_A",
    "second_wick_A",
    "mean_body_A",
    "pattern_range_A",
    "directional_progress_A",
    "engulfing",
    "rejection",
    "stall",
    "continuation",
    "pattern_extreme_price",
    "pattern_body_edge_price",
    "second_body_edge_price",
    "line_wick_overshoot_pips",
    "line_wick_overshoot_A",
    "line_body_break_pips",
    "line_body_break_A",
    "line_shape",
    "line_crossed_by_wick",
    "line_crossed_by_body",
    "line_rejection",
)


def _timestamp(value: Any) -> pd.Timestamp | None:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    parsed = pd.Timestamp(parsed)
    if parsed.tzinfo is not None:
        parsed = parsed.tz_convert("Asia/Tokyo").tz_localize(None)
    return parsed


def _time_column(frame: pd.DataFrame) -> str | None:
    if "time_jp_dt" in frame.columns:
        return "time_jp_dt"
    if "time_jp" in frame.columns:
        return "time_jp"
    return None


def _invalid(reason: str) -> dict[str, Any]:
    result = {field: None for field in FOOT_COUNT2_SHAPE_FIELDS}
    result.update({
        "version": FOOT_COUNT2_SHAPE_VERSION,
        "valid": False,
        "reason": reason,
    })
    return result


def foot_count2_shape_context(
    frame: pd.DataFrame | None,
    peak: dict[str, Any] | None,
    decision_time: Any,
    pair: Any,
    *,
    average_range_pips: float | None = None,
    lookback: int = 6,
) -> dict[str, Any]:
    """Describe the newest count2 using completed M5 candles only.

    The two foot candles are selected by the peak's oldest/latest timestamps,
    not by positional assumptions.  The preceding close is also required for
    the approach impulse and retrace ratio.
    """
    if frame is None or frame.empty or not peak:
        return _invalid("missing_frame_or_peak")
    try:
        direction = int(float(peak.get("direction")))
        count = int(float(peak.get("count")))
    except (TypeError, ValueError):
        return _invalid("invalid_peak_identity")
    if count != 2 or direction not in (-1, 1):
        return _invalid("not_foot_count2")

    time_column = _time_column(frame)
    required = {"open", "close", "high", "low"}
    if time_column is None or not required.issubset(frame.columns):
        return _invalid("missing_candle_columns")
    decision = _timestamp(decision_time)
    oldest = _timestamp(peak.get("oldest_time_jp") or peak.get("time_old"))
    latest = _timestamp(
        peak.get("latest_time_jp") or peak.get("time") or peak.get("latest_time")
    )
    if decision is None or oldest is None or latest is None or oldest > latest:
        return _invalid("invalid_peak_timestamps")

    work = frame[[time_column, *sorted(required)]].copy()
    work["_time"] = pd.to_datetime(work[time_column], errors="coerce")
    if getattr(work["_time"].dt, "tz", None) is not None:
        work["_time"] = work["_time"].dt.tz_convert(
            "Asia/Tokyo"
        ).dt.tz_localize(None)
    for column in required:
        work[column] = pd.to_numeric(work[column], errors="coerce")
    work.dropna(subset=["_time", *required], inplace=True)
    work = work[
        work["_time"] + pd.Timedelta(minutes=5) <= decision
    ].sort_values("_time")
    work.drop_duplicates("_time", keep="last", inplace=True)
    work.reset_index(drop=True, inplace=True)
    if work.empty or (work["_time"] >= decision).any():
        return _invalid("no_completed_m5")

    foot = work[(work["_time"] >= oldest) & (work["_time"] <= latest)]
    if len(foot) != 2:
        return _invalid("peak_does_not_map_to_exactly_two_m5")
    foot_positions = [int(value) for value in foot.index]
    first_position = foot_positions[0]
    if first_position <= 0 or foot_positions != [first_position, first_position + 1]:
        return _invalid("foot_candles_are_not_contiguous")
    previous = work.iloc[first_position - 1]
    first = foot.iloc[0]
    second = foot.iloc[1]
    source_values = [
        float(row[column])
        for row in (previous, first, second)
        for column in required
    ]
    if not all(math.isfinite(value) for value in source_values):
        return _invalid("non_finite_foot_candle")

    if average_range_pips is None:
        completed_for_a = work[work["_time"] < decision].tail(int(lookback))
        if len(completed_for_a) != int(lookback):
            return _invalid("insufficient_a_lookback")
        ranges = (
            completed_for_a["high"] - completed_for_a["low"]
        ) / float(pair.pip_value)
        average_range_pips = float(ranges.mean())
    try:
        a_pips = float(average_range_pips)
        pip_value = float(pair.pip_value)
    except (TypeError, ValueError):
        return _invalid("invalid_a_range")
    if not math.isfinite(a_pips) or a_pips <= 0 or pip_value <= 0:
        return _invalid("invalid_a_range")
    a_price = a_pips * pip_value

    pattern_high = float(foot["high"].max())
    pattern_low = float(foot["low"].min())
    pattern_extreme = pattern_high if direction == 1 else pattern_low
    extreme_index = foot["high"].idxmax() if direction == 1 else foot["low"].idxmin()
    extreme_candle = foot.loc[extreme_index]
    pattern_body_edge = (
        max(float(extreme_candle["open"]), float(extreme_candle["close"]))
        if direction == 1
        else min(float(extreme_candle["open"]), float(extreme_candle["close"]))
    )
    second_extreme = float(second["high"] if direction == 1 else second["low"])
    second_close = float(second["close"])
    previous_close = float(previous["close"])
    approach_price = max(direction * (pattern_extreme - previous_close), 0.0)
    reversal_price = max(direction * (pattern_extreme - second_close), 0.0)
    second_pushback_price = max(
        direction * (second_extreme - second_close),
        0.0,
    )
    second_body_edge = max(float(second["open"]), second_close) if direction == 1 else min(
        float(second["open"]), second_close
    )
    second_wick_price = max(
        direction * (second_extreme - second_body_edge),
        0.0,
    )
    mean_body_a = float((foot["close"] - foot["open"]).abs().mean() / a_price)
    directional_progress_a = float(
        direction * (second_close - previous_close) / a_price
    )

    first_open = float(first["open"])
    first_close = float(first["close"])
    second_open = float(second["open"])
    if direction == 1:
        engulfing_detected = bool(
            second_close < second_open
            and second_open >= max(first_open, first_close)
            and second_close <= min(first_open, first_close)
        )
    else:
        engulfing_detected = bool(
            second_close > second_open
            and second_open <= min(first_open, first_close)
            and second_close >= max(first_open, first_close)
        )
    second_pushback_a = second_pushback_price / a_price
    second_wick_a = second_wick_price / a_price
    rejection_detected = bool(
        second_wick_a >= REJECTION_MIN_A
        and second_pushback_a >= REJECTION_MIN_A
    )
    stall_detected = bool(
        mean_body_a <= STALL_MAX_MEAN_BODY_A
        and abs(directional_progress_a) <= STALL_MAX_NET_PROGRESS_A
    )
    if engulfing_detected:
        shape = "ENGULFING"
    elif rejection_detected:
        shape = "REJECTION"
    elif stall_detected:
        shape = "STALL"
    else:
        shape = "CONTINUATION"

    result = _invalid("")
    result.update({
        "valid": True,
        "reason": None,
        "shape": shape,
        "direction": direction,
        "source_first_time": pd.Timestamp(first["_time"]),
        "source_last_time": pd.Timestamp(second["_time"]),
        "prior_source_time": pd.Timestamp(previous["_time"]),
        "a_range_pips": a_pips,
        "approach_impulse_A": approach_price / a_price,
        "reversal_strength_A": reversal_price / a_price,
        "prior_impulse_retrace_ratio": (
            reversal_price / approach_price if approach_price > 0 else None
        ),
        "second_close_pushback_A": second_pushback_a,
        "second_wick_A": second_wick_a,
        "mean_body_A": mean_body_a,
        "pattern_range_A": (pattern_high - pattern_low) / a_price,
        "directional_progress_A": directional_progress_a,
        # Classification flags are intentionally one-hot.  The priority
        # above resolves candles satisfying more than one raw predicate.
        "engulfing": shape == "ENGULFING",
        "rejection": shape == "REJECTION",
        "stall": shape == "STALL",
        "continuation": shape == "CONTINUATION",
        "pattern_extreme_price": pattern_extreme,
        "pattern_body_edge_price": pattern_body_edge,
        "second_body_edge_price": second_body_edge,
        "_foot_candles": [
            {
                "high": float(row["high"]),
                "low": float(row["low"]),
                "body_high": max(float(row["open"]), float(row["close"])),
                "body_low": min(float(row["open"]), float(row["close"])),
            }
            for _, row in foot.iterrows()
        ],
    })
    return result


def attach_line_wick_context(
    context: dict[str, Any],
    *,
    line_price: Any,
    line_side: str,
    pair: Any,
) -> dict[str, Any]:
    """Return a copy with candidate-line wick/body overshoot measurements."""
    result = dict(context)
    if not result.get("valid"):
        return result
    try:
        line = float(line_price)
        a_pips = float(result["a_range_pips"])
        pip_value = float(pair.pip_value)
    except (TypeError, ValueError, KeyError):
        return result
    candles = result.get("_foot_candles") or []
    if len(candles) != 2:
        return result
    if line_side == "upper":
        wick_price = max(
            max(float(candle["high"]) - max(line, float(candle["body_high"])), 0.0)
            for candle in candles
        )
        body_break_price = max(
            max(float(candle["body_high"]) - line, 0.0)
            for candle in candles
        )
        crossed_by_wick = any(float(candle["high"]) > line for candle in candles)
    elif line_side == "lower":
        wick_price = max(
            max(min(line, float(candle["body_low"])) - float(candle["low"]), 0.0)
            for candle in candles
        )
        body_break_price = max(
            max(line - float(candle["body_low"]), 0.0)
            for candle in candles
        )
        crossed_by_wick = any(float(candle["low"]) < line for candle in candles)
    else:
        return result
    wick_pips = wick_price / pip_value
    body_break_pips = body_break_price / pip_value
    line_rejection = bool(
        crossed_by_wick
        and wick_pips / a_pips >= REJECTION_MIN_A
        and body_break_price <= 0
    )
    if result.get("engulfing"):
        line_shape = "ENGULFING"
    elif line_rejection:
        line_shape = "REJECTION"
    elif result.get("stall"):
        line_shape = "STALL"
    else:
        line_shape = "CONTINUATION"
    result.update({
        "line_wick_overshoot_pips": wick_pips,
        "line_wick_overshoot_A": wick_pips / a_pips,
        "line_body_break_pips": body_break_pips,
        "line_body_break_A": body_break_pips / a_pips,
        "line_shape": line_shape,
        "line_crossed_by_wick": bool(crossed_by_wick),
        "line_crossed_by_body": bool(body_break_price > 0),
        "line_rejection": line_rejection,
    })
    return result


def flatten_foot_count2_shape(
    context: dict[str, Any] | None,
    prefix: str = "fc2_",
) -> dict[str, Any]:
    context = context or {}
    return {prefix + field: context.get(field) for field in FOOT_COUNT2_SHAPE_FIELDS}
