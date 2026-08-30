# 最新更新日時: 2026-08-29 21:21 JST
"""Causal, volatility-normalized two-candle shape features.

``A`` is the mean high-low range of the six completed candles of the selected
timeframe immediately before the decision.  Callers may pass the already
calculated value so live orders and inspection CSVs use exactly the same
normalization base.
"""

from __future__ import annotations

import math
from typing import Any

import pandas as pd

from fCandleDataQuality import (
    MAX_ANALYSIS_MISSING_RATIO,
    CandleHistoryError,
    analysis_missing_bar_stats,
)


FOOT_COUNT2_SHAPE_VERSION = "foot_count2_shape_a_v2"
REJECTION_MIN_A = 0.25
STALL_MAX_MEAN_BODY_A = 0.35
STALL_MAX_NET_PROGRESS_A = 0.35

# Shared search buckets for causal foot-count-2 morphology.  Strategy modules
# choose which of these fields to search; the feature definitions and their
# boundaries live here so live, analysis, and replay code cannot drift.
FC2_A_BUCKET_EDGES = (
    -math.inf,
    0.10,
    0.25,
    0.50,
    0.75,
    1.00,
    1.50,
    2.00,
    math.inf,
)
FC2_A_BUCKET_LABELS = (
    "lt0p10",
    "0p10to0p24",
    "0p25to0p49",
    "0p50to0p74",
    "0p75to0p99",
    "1p00to1p49",
    "1p50to1p99",
    "ge2p00",
)
FC2_RATIO_BUCKET_EDGES = (
    -math.inf,
    0.25,
    0.40,
    0.55,
    0.65,
    0.80,
    1.00,
    math.inf,
)
FC2_RATIO_BUCKET_LABELS = (
    "lt0p25",
    "0p25to0p39",
    "0p40to0p54",
    "0p55to0p64",
    "0p65to0p79",
    "0p80to0p99",
    "ge1p00",
)

FOOT_COUNT2_SHAPE_FIELDS = (
    "version",
    "valid",
    "reason",
    "shape",
    "direction",
    "timeframe_minutes",
    "actual_foot_count2",
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
    "first_range_A",
    "first_body_A",
    "first_upper_wick_A",
    "first_lower_wick_A",
    "second_range_A",
    "second_body_A",
    "second_upper_wick_A",
    "second_lower_wick_A",
    "first_direction",
    "second_direction",
    "candle_sequence",
    "relative_candle_sequence",
    "second_range_to_first_ratio",
    "second_body_to_first_ratio",
    "second_recovery_of_first_ratio",
    "formation_minutes",
    "age_at_decision_minutes",
    "bars_since_pattern",
    "reversal_speed_A_per_hour",
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


def relative_foot_count2_candle_sequence(
    candle_sequence: Any,
    direction: Any,
) -> str | None:
    """Express BULL/BEAR candles relative to the FC2 travel direction."""
    try:
        oriented_direction = int(float(direction))
    except (TypeError, ValueError):
        return None
    if oriented_direction not in (-1, 1):
        return None
    parts = str(candle_sequence).upper().split("_")
    if len(parts) != 2 or any(part not in {"BULL", "BEAR", "DOJI"} for part in parts):
        return None

    def orient(part: str) -> str:
        if part == "DOJI":
            return "DOJI"
        candle_sign = 1 if part == "BULL" else -1
        return "WITH" if candle_sign == oriented_direction else "AGAINST"

    return "_".join(orient(part) for part in parts)


def add_foot_count2_search_buckets(
    frame: pd.DataFrame,
    *,
    source_prefix: str = "fc2_",
    destination_prefix: str = "f_fc2_",
) -> pd.DataFrame:
    """Attach reusable finite buckets for completed-candle FC2 morphology."""
    result = frame.copy()

    def source(field: str) -> pd.Series:
        column = source_prefix + field
        if column in result.columns:
            return result[column]
        return pd.Series(pd.NA, index=result.index, dtype="object")

    def text_bucket(field: str) -> pd.Series:
        return source(field).astype("string").fillna("missing")

    def numeric_bucket(
        field: str,
        edges: tuple[float, ...],
        labels: tuple[str, ...],
    ) -> pd.Series:
        values = pd.to_numeric(source(field), errors="coerce")
        return pd.cut(
            values,
            bins=list(edges),
            labels=list(labels),
            include_lowest=True,
            right=False,
        ).astype("string").fillna("missing")

    result[destination_prefix + "shape"] = text_bucket("shape")
    result[destination_prefix + "candle_sequence"] = text_bucket(
        "candle_sequence"
    )
    relative_sequence = source("relative_candle_sequence").astype("string")
    direction_column = "peak_direction"
    if direction_column in result.columns:
        directions = result[direction_column]
    else:
        directions = source("direction")
    derived_relative = pd.Series(
        (
            relative_foot_count2_candle_sequence(sequence, direction)
            for sequence, direction in zip(source("candle_sequence"), directions)
        ),
        index=result.index,
        dtype="string",
    )
    result[destination_prefix + "relative_candle_sequence"] = (
        relative_sequence.fillna(derived_relative).fillna("missing")
    )
    result[destination_prefix + "second_wick_a"] = numeric_bucket(
        "second_wick_A", FC2_A_BUCKET_EDGES, FC2_A_BUCKET_LABELS
    )
    result[destination_prefix + "second_pushback_a"] = numeric_bucket(
        "second_close_pushback_A", FC2_A_BUCKET_EDGES, FC2_A_BUCKET_LABELS
    )
    result[destination_prefix + "second_body_ratio"] = numeric_bucket(
        "second_body_to_first_ratio",
        FC2_RATIO_BUCKET_EDGES,
        FC2_RATIO_BUCKET_LABELS,
    )
    return result


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


def _source_bars_are_contiguous(
    times: list[pd.Timestamp] | pd.Series,
    timeframe: pd.Timedelta,
) -> bool:
    """Allow causal source bars while rejecting half-missing histories."""
    ordered = [pd.Timestamp(value) for value in times]
    try:
        stats = analysis_missing_bar_stats(ordered, timeframe)
    except (CandleHistoryError, TypeError, ValueError):
        return False
    return bool(stats["missing_ratio"] < MAX_ANALYSIS_MISSING_RATIO)


def foot_count2_shape_context(
    frame: pd.DataFrame | None,
    peak: dict[str, Any] | None,
    decision_time: Any,
    pair: Any,
    *,
    average_range_pips: float | None = None,
    lookback: int = 6,
    timeframe_minutes: int = 5,
    require_actual_foot_count2: bool = True,
) -> dict[str, Any]:
    """Describe an oriented two-candle pattern using completed candles only.

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
    if (require_actual_foot_count2 and count != 2) or direction not in (-1, 1):
        return _invalid("not_foot_count2")
    if not isinstance(timeframe_minutes, int) or timeframe_minutes < 1:
        return _invalid("invalid_timeframe_minutes")

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
    timeframe = pd.Timedelta(minutes=timeframe_minutes)
    work = work[work["_time"] + timeframe <= decision].sort_values("_time")
    work.drop_duplicates("_time", keep="last", inplace=True)
    work.reset_index(drop=True, inplace=True)
    if work.empty or (work["_time"] >= decision).any():
        return _invalid("no_completed_candles")

    foot = work[(work["_time"] >= oldest) & (work["_time"] <= latest)]
    if len(foot) != 2:
        return _invalid("pattern_does_not_map_to_exactly_two_candles")
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

    source_times = [
        pd.Timestamp(previous["_time"]),
        pd.Timestamp(first["_time"]),
        pd.Timestamp(second["_time"]),
    ]
    if not _source_bars_are_contiguous(source_times, timeframe):
        return _invalid("unknown_gap_in_pattern_source")

    completed_for_a = work[work["_time"] < decision].tail(int(lookback))
    if len(completed_for_a) != int(lookback):
        return _invalid("insufficient_a_lookback")
    if not _source_bars_are_contiguous(
        completed_for_a["_time"].tolist(),
        timeframe,
    ):
        return _invalid("unknown_gap_in_a_lookback")
    if average_range_pips is None:
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
    first_high = float(first["high"])
    first_low = float(first["low"])
    second_high = float(second["high"])
    second_low = float(second["low"])
    first_body_price = abs(first_close - first_open)
    second_body_price = abs(second_close - second_open)
    first_range_price = first_high - first_low
    second_range_price = second_high - second_low
    first_body_high = max(first_open, first_close)
    first_body_low = min(first_open, first_close)
    second_body_high = max(second_open, second_close)
    second_body_low = min(second_open, second_close)

    def candle_direction(open_price: float, close_price: float) -> str:
        if close_price > open_price:
            return "BULL"
        if close_price < open_price:
            return "BEAR"
        return "DOJI"

    first_direction = candle_direction(first_open, first_close)
    second_direction = candle_direction(second_open, second_close)
    first_push_price = max(direction * (first_close - first_open), 0.0)
    second_recovery_price = max(
        -direction * (second_close - first_close),
        0.0,
    )
    # Active formation time is two bars.  A weekend/market closure between
    # bars must not make the pattern look artificially slow.
    formation_minutes = float(2 * timeframe_minutes)
    age_at_decision_minutes = float(
        (decision - (pd.Timestamp(second["_time"]) + timeframe)).total_seconds()
        / 60.0
    )
    bars_since_pattern = int(
        (work["_time"] > pd.Timestamp(second["_time"])).sum()
    )
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
        "timeframe_minutes": timeframe_minutes,
        "actual_foot_count2": bool(require_actual_foot_count2),
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
        "first_range_A": first_range_price / a_price,
        "first_body_A": first_body_price / a_price,
        "first_upper_wick_A": (first_high - first_body_high) / a_price,
        "first_lower_wick_A": (first_body_low - first_low) / a_price,
        "second_range_A": second_range_price / a_price,
        "second_body_A": second_body_price / a_price,
        "second_upper_wick_A": (second_high - second_body_high) / a_price,
        "second_lower_wick_A": (second_body_low - second_low) / a_price,
        "first_direction": first_direction,
        "second_direction": second_direction,
        "candle_sequence": f"{first_direction}_{second_direction}",
        "relative_candle_sequence": relative_foot_count2_candle_sequence(
            f"{first_direction}_{second_direction}", direction
        ),
        "second_range_to_first_ratio": (
            second_range_price / first_range_price if first_range_price > 0 else None
        ),
        "second_body_to_first_ratio": (
            second_body_price / first_body_price if first_body_price > 0 else None
        ),
        "second_recovery_of_first_ratio": (
            second_recovery_price / first_push_price if first_push_price > 0 else None
        ),
        "formation_minutes": formation_minutes,
        "age_at_decision_minutes": age_at_decision_minutes,
        "bars_since_pattern": bars_since_pattern,
        "reversal_speed_A_per_hour": (
            (reversal_price / a_price) * 60.0 / formation_minutes
            if formation_minutes > 0
            else None
        ),
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


def latest_two_candle_shape_context(
    frame: pd.DataFrame | None,
    decision_time: Any,
    pair: Any,
    *,
    direction: int,
    timeframe_minutes: int,
    lookback: int = 6,
) -> dict[str, Any]:
    """Describe the latest two completed candles as higher-timeframe context.

    This is deliberately not labelled as an H1 foot-count 2.  At an M5
    signal the latest H1 peak may have any foot count; the latest two completed
    H1 candles are nevertheless available macro context.  The orientation is
    the M5 peak direction so M5/H1 values have the same sign convention.
    """
    if frame is None or frame.empty:
        return _invalid("missing_frame")
    time_column = _time_column(frame)
    if time_column is None:
        return _invalid("missing_time_column")
    decision = _timestamp(decision_time)
    if decision is None:
        return _invalid("invalid_decision_time")
    times = pd.to_datetime(frame[time_column], errors="coerce")
    if getattr(times.dt, "tz", None) is not None:
        times = times.dt.tz_convert("Asia/Tokyo").dt.tz_localize(None)
    completed = frame.loc[
        times + pd.Timedelta(minutes=timeframe_minutes) <= decision
    ].copy()
    completed["_shape_time"] = times.loc[completed.index]
    completed.sort_values("_shape_time", inplace=True)
    completed.drop_duplicates("_shape_time", keep="last", inplace=True)
    if len(completed) < max(3, int(lookback)):
        return _invalid("insufficient_completed_candles")
    pair_rows = completed.tail(2)
    oldest = pd.Timestamp(pair_rows.iloc[0]["_shape_time"])
    latest = pd.Timestamp(pair_rows.iloc[1]["_shape_time"])
    peak = {
        "count": 2,
        "direction": direction,
        "oldest_time_jp": oldest,
        "latest_time_jp": latest,
    }
    return foot_count2_shape_context(
        frame,
        peak,
        decision,
        pair,
        lookback=lookback,
        timeframe_minutes=timeframe_minutes,
        require_actual_foot_count2=False,
    )


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
