"""Past-only M5 stair-trend detection shared by pair profiles."""

import math

import fGeneric as gene


def detect_m5_stair_trend(
    peaks,
    pair,
    completed_m5=None,
    *,
    min_impulse_foot_count=3,
    min_latest_impulse_foot_count=2,
    max_pullback_foot_count=3,
    min_impulse_pips=3.0,
    volatility_lookback=12,
    volatility_multiplier=1.2,
    max_pullback_ratio=0.65,
    min_break_pips=0.5,
    min_dominance_ratio=1.5,
):
    """Detect U-D-U / D-U-D stairs from completed-M5 foot peaks.

    ``peaks`` must be newest first, matching ``PeaksClass.peaks_original``.
    The newest foot may still be extending, but every candle used to build it
    must already be complete.  Three alternating feet produce a candidate;
    five feet produce a confirmed stair.
    """
    result = {
        "state": "NONE",
        "direction": 0,
        "direction_label": None,
        "confirmed": False,
        "candidate_passed": False,
        "confirmed_passed": False,
        "analysis_leg_count": 0,
        "detected_leg_count": 0,
        "observed_direction": 0,
        "direction_sequence": [],
        "foot_count_sequence": [],
        "distance_pips_sequence": [],
        "impulse_foot_count_sequence": [],
        "pullback_foot_count_sequence": [],
        "impulse_distance_pips_sequence": [],
        "pullback_distance_pips_sequence": [],
        "pullback_ratio_sequence": [],
        "impulse_break_pips_sequence": [],
        "structure_progress_pips_sequence": [],
        "impulse_distance_pips": 0.0,
        "pullback_distance_pips": 0.0,
        "dominance_ratio": None,
        "first_impulse_foot_count": None,
        "first_impulse_pips": None,
        "first_pullback_foot_count": None,
        "first_pullback_pips": None,
        "first_pullback_ratio": None,
        "first_pullback_foot_ratio": None,
        "first_impulse_pips_per_foot": None,
        "first_pullback_pips_per_foot": None,
        "first_impulse_required_ratio": None,
        "second_impulse_foot_count": None,
        "second_impulse_pips": None,
        "second_pullback_foot_count": None,
        "second_pullback_pips": None,
        "second_pullback_ratio": None,
        "second_pullback_foot_ratio": None,
        "second_impulse_pips_per_foot": None,
        "second_pullback_pips_per_foot": None,
        "second_impulse_required_ratio": None,
        "third_impulse_foot_count": None,
        "third_impulse_pips": None,
        "third_impulse_pips_per_foot": None,
        "third_impulse_required_ratio": None,
        "net_progress_pips": None,
        "second_impulse_break_pips": None,
        "third_impulse_break_pips": None,
        "first_structure_progress_pips": None,
        "second_structure_progress_pips": None,
        "candidate_failed_conditions": [],
        "confirmed_failed_conditions": [],
        "required_impulse_pips": float(min_impulse_pips),
        "median_m5_range_pips": None,
        "threshold_min_impulse_foot_count": int(min_impulse_foot_count),
        "threshold_min_latest_impulse_foot_count": int(
            min_latest_impulse_foot_count
        ),
        "threshold_max_pullback_foot_count": int(max_pullback_foot_count),
        "threshold_min_impulse_pips": float(min_impulse_pips),
        "threshold_volatility_lookback": int(volatility_lookback),
        "threshold_volatility_multiplier": float(volatility_multiplier),
        "threshold_max_pullback_ratio": float(max_pullback_ratio),
        "threshold_min_break_pips": float(min_break_pips),
        "threshold_min_dominance_ratio": float(min_dominance_ratio),
        "oldest_time": None,
        "latest_time": None,
        "reason": "insufficient_alternating_feet",
    }
    pair_info = gene.currency_pair(pair) if isinstance(pair, str) else pair
    feet = [
        foot
        for foot in (peaks or [])
        if isinstance(foot, dict) and _direction(foot) in (-1, 1)
    ]

    median_range = _median_completed_m5_range_pips(
        completed_m5,
        pair_info,
        volatility_lookback,
    )
    required_impulse = float(min_impulse_pips)
    if median_range is not None:
        required_impulse = max(
            required_impulse,
            float(volatility_multiplier) * median_range,
        )
    result["required_impulse_pips"] = round(required_impulse, 3)
    result["median_m5_range_pips"] = (
        round(median_range, 3) if median_range is not None else None
    )

    if len(feet) < 3:
        return result

    candidate = _evaluate_stair_pattern(
        feet[:3],
        pair_info,
        required_impulse=required_impulse,
        min_impulse_foot_count=min_impulse_foot_count,
        min_latest_impulse_foot_count=min_latest_impulse_foot_count,
        max_pullback_foot_count=max_pullback_foot_count,
        max_pullback_ratio=max_pullback_ratio,
        min_break_pips=min_break_pips,
        min_dominance_ratio=min_dominance_ratio,
    )
    result["candidate_passed"] = bool(candidate["passes"])
    result["candidate_failed_conditions"] = candidate[
        "failed_conditions"
    ]

    analysis = candidate
    confirmed = None
    if len(feet) >= 5:
        confirmed = _evaluate_stair_pattern(
            feet[:5],
            pair_info,
            required_impulse=required_impulse,
            min_impulse_foot_count=min_impulse_foot_count,
            min_latest_impulse_foot_count=min_latest_impulse_foot_count,
            max_pullback_foot_count=max_pullback_foot_count,
            max_pullback_ratio=max_pullback_ratio,
            min_break_pips=min_break_pips,
            min_dominance_ratio=min_dominance_ratio,
        )
        analysis = confirmed
        result["confirmed_passed"] = bool(confirmed["passes"])
        result["confirmed_failed_conditions"] = confirmed[
            "failed_conditions"
        ]

    # Always expose the longest observable structure, even when a threshold
    # fails.  Validation can then compare the raw ratios/counts instead of
    # seeing only the structures already accepted by the detector.
    result.update(
        {
            key: value
            for key, value in analysis.items()
            if key not in ("passes", "failed_conditions")
        }
    )
    result["analysis_leg_count"] = len(analysis["foot_count_sequence"])

    if not candidate["passes"]:
        result["reason"] = "latest_three_feet_failed"
        return result

    is_confirmed = bool(confirmed and confirmed["passes"])
    selected = confirmed if is_confirmed else candidate
    direction = selected["observed_direction"]
    label = "UP" if direction == 1 else "DOWN"
    result.update({
        "state": label + ("_CONFIRMED" if is_confirmed else "_CANDIDATE"),
        "direction": direction,
        "direction_label": label,
        "confirmed": is_confirmed,
        "detected_leg_count": 5 if is_confirmed else 3,
        "reason": "five_foot_stair" if is_confirmed else "three_foot_stair",
    })
    return result


def _evaluate_stair_pattern(
    newest_first,
    pair_info,
    *,
    required_impulse,
    min_impulse_foot_count,
    min_latest_impulse_foot_count,
    max_pullback_foot_count,
    max_pullback_ratio,
    min_break_pips,
    min_dominance_ratio,
):
    chronological = list(reversed(newest_first))
    direction = _direction(chronological[0])
    expected = [direction if i % 2 == 0 else -direction for i in range(len(chronological))]
    directions = [_direction(foot) for foot in chronological]
    alternating_pass = (
        direction in (-1, 1)
        and directions == expected
    )

    impulses = chronological[::2]
    pullbacks = chronological[1::2]
    impulse_counts = [_foot_count(foot) for foot in impulses]
    pullback_counts = [_foot_count(foot) for foot in pullbacks]
    # PredictReversal is evaluated when the newest foot first reaches count 2.
    # Older impulse feet are complete and use the stricter threshold; only the
    # still-developing newest impulse is allowed to use its own threshold.
    completed_impulse_counts = impulse_counts[:-1]
    completed_impulse_count_pass = not any(
        count < int(min_impulse_foot_count)
        for count in completed_impulse_counts
    )
    latest_impulse_count_pass = bool(
        impulse_counts
        and impulse_counts[-1] >= int(min_latest_impulse_foot_count)
    )
    pullback_count_pass = not any(
        count > int(max_pullback_foot_count)
        for count in pullback_counts
    )

    impulse_distances = [_foot_distance_pips(foot, pair_info) for foot in impulses]
    pullback_distances = [_foot_distance_pips(foot, pair_info) for foot in pullbacks]
    impulse_distance_pass = not any(
        distance < required_impulse
        for distance in impulse_distances
    )
    pullback_ratios = [
        pullback / impulse_distances[index]
        if impulse_distances[index] > 0
        else math.inf
        for index, pullback in enumerate(pullback_distances)
    ]
    pullback_ratio_pass = not any(
        ratio > float(max_pullback_ratio)
        for ratio in pullback_ratios
    )

    break_price = pair_info.pips_to_price(float(min_break_pips))
    impulse_ends = [_end_price(foot) for foot in impulses]
    pullback_ends = [_end_price(foot) for foot in pullbacks]
    structure_anchors = [_start_price(impulses[0]), *pullback_ends]
    prices_available = not any(
        value is None
        for value in [*impulse_ends, *structure_anchors]
    )
    impulse_breaks = (
        _progression_pips(impulse_ends, direction, pair_info)
        if prices_available
        else []
    )
    structure_progress = (
        _progression_pips(structure_anchors, direction, pair_info)
        if prices_available
        else []
    )
    impulse_progression_pass = bool(
        prices_available
        and _strict_progression(impulse_ends, direction, break_price)
    )
    structure_progression_pass = bool(
        prices_available
        and _strict_progression(structure_anchors, direction, break_price)
    )

    impulse_total = sum(impulse_distances)
    pullback_total = sum(pullback_distances)
    dominance = impulse_total / max(pullback_total, 1e-9)
    dominance_pass = dominance >= float(min_dominance_ratio)

    criteria = {
        "alternating": alternating_pass,
        "completed_impulse_foot_count": completed_impulse_count_pass,
        "latest_impulse_foot_count": latest_impulse_count_pass,
        "pullback_foot_count": pullback_count_pass,
        "impulse_distance": impulse_distance_pass,
        "pullback_ratio": pullback_ratio_pass,
        "impulse_progression": impulse_progression_pass,
        "structure_progression": structure_progression_pass,
        "dominance": dominance_pass,
    }
    failed_conditions = [
        name for name, passed in criteria.items() if not passed
    ]

    signed_distances = [
        round(_foot_distance_pips(foot, pair_info) * _direction(foot), 3)
        for foot in chronological
    ]
    return {
        "passes": not failed_conditions,
        "failed_conditions": failed_conditions,
        "criteria": criteria,
        "observed_direction": direction if direction in (-1, 1) else 0,
        "direction_sequence": directions,
        "foot_count_sequence": [_foot_count(foot) for foot in chronological],
        "distance_pips_sequence": signed_distances,
        "impulse_foot_count_sequence": impulse_counts,
        "pullback_foot_count_sequence": pullback_counts,
        "impulse_distance_pips_sequence": [
            round(value, 3) for value in impulse_distances
        ],
        "pullback_distance_pips_sequence": [
            round(value, 3) for value in pullback_distances
        ],
        "pullback_ratio_sequence": [
            round(value, 4) if math.isfinite(value) else None
            for value in pullback_ratios
        ],
        "impulse_break_pips_sequence": [
            round(value, 3) for value in impulse_breaks
        ],
        "structure_progress_pips_sequence": [
            round(value, 3) for value in structure_progress
        ],
        "impulse_distance_pips": round(impulse_total, 3),
        "pullback_distance_pips": round(pullback_total, 3),
        "dominance_ratio": round(dominance, 3),
        "first_impulse_foot_count": _at(impulse_counts, 0),
        "first_impulse_pips": _rounded_at(impulse_distances, 0),
        "first_pullback_foot_count": _at(pullback_counts, 0),
        "first_pullback_pips": _rounded_at(pullback_distances, 0),
        "first_pullback_ratio": _rounded_at(pullback_ratios, 0, 4),
        "first_pullback_foot_ratio": _ratio_at(
            pullback_counts,
            impulse_counts,
            0,
            4,
        ),
        "first_impulse_pips_per_foot": _ratio_at(
            impulse_distances,
            impulse_counts,
            0,
        ),
        "first_pullback_pips_per_foot": _ratio_at(
            pullback_distances,
            pullback_counts,
            0,
        ),
        "first_impulse_required_ratio": _value_ratio_at(
            impulse_distances,
            required_impulse,
            0,
        ),
        "second_impulse_foot_count": _at(impulse_counts, 1),
        "second_impulse_pips": _rounded_at(impulse_distances, 1),
        "second_pullback_foot_count": _at(pullback_counts, 1),
        "second_pullback_pips": _rounded_at(pullback_distances, 1),
        "second_pullback_ratio": _rounded_at(pullback_ratios, 1, 4),
        "second_pullback_foot_ratio": _ratio_at(
            pullback_counts,
            impulse_counts,
            1,
            4,
        ),
        "second_impulse_pips_per_foot": _ratio_at(
            impulse_distances,
            impulse_counts,
            1,
        ),
        "second_pullback_pips_per_foot": _ratio_at(
            pullback_distances,
            pullback_counts,
            1,
        ),
        "second_impulse_required_ratio": _value_ratio_at(
            impulse_distances,
            required_impulse,
            1,
        ),
        "third_impulse_foot_count": _at(impulse_counts, 2),
        "third_impulse_pips": _rounded_at(impulse_distances, 2),
        "third_impulse_pips_per_foot": _ratio_at(
            impulse_distances,
            impulse_counts,
            2,
        ),
        "third_impulse_required_ratio": _value_ratio_at(
            impulse_distances,
            required_impulse,
            2,
        ),
        "net_progress_pips": _net_progress_pips(
            chronological,
            direction,
            pair_info,
        ),
        "second_impulse_break_pips": _rounded_at(impulse_breaks, 0),
        "third_impulse_break_pips": _rounded_at(impulse_breaks, 1),
        "first_structure_progress_pips": _rounded_at(
            structure_progress,
            0,
        ),
        "second_structure_progress_pips": _rounded_at(
            structure_progress,
            1,
        ),
        "oldest_time": chronological[0].get("oldest_time_jp"),
        "latest_time": chronological[-1].get("latest_time_jp"),
    }


def _progression_pips(values, direction, pair_info):
    return [
        pair_info.price_to_pips((current - previous) * direction)
        for previous, current in zip(values, values[1:])
    ]


def _at(values, index):
    return values[index] if len(values) > index else None


def _rounded_at(values, index, digits=3):
    value = _at(values, index)
    if value is None or not math.isfinite(value):
        return None
    return round(value, digits)


def _ratio_at(numerators, denominators, index, digits=3):
    numerator = _at(numerators, index)
    denominator = _at(denominators, index)
    if numerator is None or denominator in (None, 0):
        return None
    return round(float(numerator) / float(denominator), digits)


def _value_ratio_at(values, denominator, index, digits=4):
    value = _at(values, index)
    if value is None or denominator in (None, 0):
        return None
    return round(float(value) / float(denominator), digits)


def _net_progress_pips(chronological, direction, pair_info):
    start = _start_price(chronological[0])
    end = _end_price(chronological[-1])
    if start is None or end is None or direction not in (-1, 1):
        return None
    return round(pair_info.price_to_pips((end - start) * direction), 3)


def _median_completed_m5_range_pips(frame, pair_info, lookback):
    if frame is None or getattr(frame, "empty", True):
        return None
    if "high" not in frame or "low" not in frame:
        return None
    ranges = []
    for high, low in zip(frame["high"].head(lookback), frame["low"].head(lookback)):
        high = _finite_float(high)
        low = _finite_float(low)
        if high is None or low is None or high < low:
            continue
        ranges.append(pair_info.price_to_pips(high - low))
    if not ranges:
        return None
    ranges.sort()
    middle = len(ranges) // 2
    if len(ranges) % 2:
        return float(ranges[middle])
    return float((ranges[middle - 1] + ranges[middle]) / 2)


def _strict_progression(values, direction, minimum_gap):
    for previous, current in zip(values, values[1:]):
        if direction == 1 and current < previous + minimum_gap:
            return False
        if direction == -1 and current > previous - minimum_gap:
            return False
    return True


def _foot_distance_pips(foot, pair_info):
    gap = _finite_float(foot.get("gap"))
    if gap is None:
        start = _start_price(foot)
        end = _end_price(foot)
        if start is None or end is None:
            return 0.0
        gap = abs(end - start)
    return float(pair_info.price_to_pips(abs(gap)))


def _direction(foot):
    try:
        direction = int(float(foot.get("direction")))
    except (AttributeError, TypeError, ValueError):
        return 0
    return direction if direction in (-1, 1) else 0


def _foot_count(foot):
    try:
        return int(foot.get("count") or 0)
    except (AttributeError, TypeError, ValueError):
        return 0


def _start_price(foot):
    return _finite_float(foot.get("oldest_body_peak_price"))


def _end_price(foot):
    return _finite_float(foot.get("latest_body_peak_price"))


def _finite_float(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None
