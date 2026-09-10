"""Collect offline production-equivalence evidence without stopping a sweep.

This module performs no imports of trading code, I/O, or network requests.
The caller supplies a strict validator for one decision at a time.
"""

from collections.abc import Callable, Iterable, Mapping
from typing import Any


_MISMATCH_PREFIX = "resistance breakout production equivalence mismatch:"
_METADATA_KEYS = (
    "core_version",
    "policy_id",
    "current_price_source",
    "sweep_builder",
    "production_builder",
)


def _new_report(sample_count: int, timeframes: Iterable[str]) -> dict[str, Any]:
    frames = tuple(dict.fromkeys(str(frame) for frame in timeframes))
    return {
        "status": "incomplete",
        "requested_samples": max(int(sample_count), 1),
        "eligible_decisions": 0,
        "attempted_decisions": 0,
        "checked_decisions": 0,
        "skipped_decisions": 0,
        "skipped_decision_reasons": [],
        "checked_candidates": 0,
        "checked_candidates_by_timeframe": {frame: 0 for frame in frames},
        "candidate_evidence_by_timeframe": {frame: "empty_only" for frame in frames},
        "peak_history_bars_by_timeframe": {},
        "missing_candidate_timeframes": list(frames),
        "timeframes": frames,
        "fully_exercised": False,
        "empty_candidate_decisions": 0,
        "mismatches": 0,
        "errors": 0,
        "issues": [],
    }


def make_unavailable_equivalence_report(
    error: Exception,
    *,
    sample_count: int = 30,
    timeframes: Iterable[str] = (),
) -> dict[str, Any]:
    """Describe a preparation failure without presenting it as a passed check."""
    report = _new_report(sample_count, timeframes)
    report["errors"] = 1
    report["issues"].append({
        "index": None,
        "decision_time": None,
        "kind": "preparation_error",
        "error_type": type(error).__name__,
        "message": str(error),
    })
    return report


def _even_positions(length: int, count: int) -> list[int]:
    count = min(length, count)
    if count < 1:
        return []
    if count == 1:
        return [0]
    return [position * (length - 1) // (count - 1) for position in range(count)]


def _refresh_evidence(report: dict[str, Any]) -> None:
    counts = report["checked_candidates_by_timeframe"]
    report["timeframes"] = tuple(counts)
    report["missing_candidate_timeframes"] = [
        frame for frame, count in counts.items() if count < 1
    ]
    report["candidate_evidence_by_timeframe"] = {
        frame: "candidate_compared" if count > 0 else "empty_only"
        for frame, count in counts.items()
    }
    report["fully_exercised"] = (
        report["checked_candidates"] > 0
        and not report["missing_candidate_timeframes"]
    )


def _read_sample(sample: Mapping[str, Any]) -> tuple[int, dict[str, int], dict[str, int]]:
    """Validate the complete return value before adding any success counters."""
    if not isinstance(sample, Mapping):
        raise TypeError("production equivalence validator must return a mapping")
    if int(sample.get("checked_decisions", 0)) != 1:
        raise ValueError("production equivalence validator must compare exactly one decision")
    if int(sample.get("mismatches", 0)) or int(sample.get("errors", 0)):
        raise ValueError("production equivalence validator returned unresolved failures")
    candidates = int(sample.get("checked_candidates", 0))
    counts = {
        str(frame): int(count)
        for frame, count in sample.get("checked_candidates_by_timeframe", {}).items()
    }
    for frame in sample.get("timeframes", ()):
        counts.setdefault(str(frame), 0)
    histories = {
        str(frame): int(count)
        for frame, count in sample.get("peak_history_bars_by_timeframe", {}).items()
    }
    if candidates < 0 or any(count < 0 for count in counts.values()):
        raise ValueError("production equivalence validator returned negative candidate counts")
    return candidates, counts, histories


def collect_equivalence_report(
    indices: Iterable[int],
    validate_sample: Callable[[int], Mapping[str, Any]],
    *,
    sample_count: int = 30,
    timeframes: Iterable[str] = (),
    describe_index: Callable[[int], Any] | None = None,
) -> dict[str, Any]:
    """Compare distributed samples, retain failures, and return a report.

    Start with ``sample_count`` evenly spaced decisions. Failed comparisons or
    missing candidate evidence trigger distinct replacement samples, up to
    three times that many attempts. Empty-but-equal comparisons count as checked
    decisions, but cannot alone establish candidate equivalence. Replacements
    never erase earlier failures. ``KeyboardInterrupt`` and ``SystemExit`` are
    intentionally allowed to propagate.
    """
    report = _new_report(sample_count, timeframes)
    requested = report["requested_samples"]
    try:
        distinct_indices = list(dict.fromkeys(int(index) for index in indices))
    except Exception as error:
        return make_unavailable_equivalence_report(
            error, sample_count=requested, timeframes=report["timeframes"],
        )
    report["eligible_decisions"] = len(distinct_indices)
    attempt_limit = min(len(distinct_indices), requested * 3)
    positions = _even_positions(len(distinct_indices), requested)
    selected = set(positions)
    for position in _even_positions(len(distinct_indices), attempt_limit):
        if position not in selected:
            positions.append(position)
            selected.add(position)
        if len(positions) >= attempt_limit:
            break

    for position in positions:
        if report["checked_decisions"] >= requested and report["fully_exercised"]:
            break
        index = distinct_indices[position]
        report["attempted_decisions"] += 1
        try:
            sample = validate_sample(index)
            candidates, counts, histories = _read_sample(sample)
        except Exception as error:
            mismatch = isinstance(error, ValueError) and str(error).startswith(_MISMATCH_PREFIX)
            kind = "mismatch" if mismatch else "error"
            report["mismatches" if mismatch else "errors"] += 1
            report["skipped_decisions"] += 1
            decision_time = None
            if describe_index is not None:
                try:
                    decision_time = str(describe_index(index))
                except Exception as description_error:
                    report["errors"] += 1
                    report["issues"].append({
                        "index": index,
                        "decision_time": None,
                        "kind": "description_error",
                        "error_type": type(description_error).__name__,
                        "message": str(description_error),
                    })
            report["issues"].append({
                "index": index,
                "decision_time": decision_time,
                "kind": kind,
                "error_type": type(error).__name__,
                "message": str(error),
            })
            report["skipped_decision_reasons"].append(
                f"{decision_time if decision_time is not None else index}: {error}"
            )
            continue

        report["checked_decisions"] += 1
        report["checked_candidates"] += candidates
        if candidates == 0:
            report["empty_candidate_decisions"] += 1
        for frame, count in counts.items():
            accumulated = report["checked_candidates_by_timeframe"]
            accumulated[frame] = accumulated.get(frame, 0) + count
        for frame, bars in histories.items():
            accumulated = report["peak_history_bars_by_timeframe"]
            accumulated[frame] = max(accumulated.get(frame, 0), bars)
        for key in _METADATA_KEYS:
            if key in sample:
                report.setdefault(key, sample[key])
        _refresh_evidence(report)

    _refresh_evidence(report)
    if report["mismatches"]:
        report["status"] = "mismatch"
    elif (
        report["checked_decisions"] >= requested
        and report["fully_exercised"]
        and not report["errors"]
    ):
        report["status"] = "passed"
    return report
