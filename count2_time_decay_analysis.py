"""Future-safe time-decay analysis for count-2 reversal opportunities.

The analyzer is intentionally separate from candidate generation, the TP/LC
grid, and live order creation.  It reads only completed artifacts:

* the causal foot-count-2 event ledger;
* the causal candidate CSV (for last-reach age);
* normalized grid paths (for LIMIT fills and barrier timestamps); and
* the matching S5 cache (outcomes only).

Decision-time features are never rebuilt from later candles.  Windows which
cross the requested end or an unknown S5 gap are censored rather than treated
as wins, losses, or zero returns.  Expected market-closure gaps use the same
audited completion rule as the target-grid engine.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

import fGeneric as gene
import test_win_point_usd_aud as win_point
import tokens as tk
from count2_resistance_sweep import s5_cache_has_no_tick_completion
from count2_target_grid_search import (
    DEFAULT_END,
    DEFAULT_PAIR_NAME,
    DEFAULT_SPREAD_PIPS,
    DEFAULT_START,
    DOMINANCE_EDGES,
    DOMINANCE_LABELS,
    PACE_EDGES,
    PACE_LABELS,
    PROGRESS_EDGES,
    PROGRESS_LABELS,
    RATIO_EDGES,
    RATIO_LABELS,
    GRID_VERSION,
    _archive_file,
    _bin_label,
    _bound_inspector_before,
    _condition,
    _is_complete_market_window,
    _load_typed_s5_inspector,
    _source_stat,
    _write_json_atomic,
)
from fLineStrategyUsdJpy import LineStrategyProfileUsdJpy


ANALYSIS_VERSION = "count2_time_decay_v1"
TIME_FORMAT = "%Y/%m/%d %H:%M:%S"
DEFAULT_HORIZONS = (5, 10, 15, 20, 30, 45, 60)
DEFAULT_FILL_DELAY_EDGES = (5, 10, 15, 30, 60)
DEFAULT_LAST_REACH_EDGES = (30, 60, 120, 240, 480, 1440)
DEFAULT_READ_CHUNK_SIZE = 2000
SUPPORTED_LEGACY_GRID_VERSIONS = {
    "USD_JPY": frozenset({
        "usd_jpy_count2_entry_tp_lc_grid_v6",
        "usd_jpy_count2_entry_tp_lc_grid_v8_fc2_shape",
    }),
    "EUR_USD": frozenset({"eur_usd_count2_entry_tp_lc_grid_v8_fc2_shape"}),
    "AUD_USD": frozenset({"aud_usd_count2_entry_tp_lc_grid_v8_fc2_shape"}),
}


def _notify(message: str) -> None:
    win_point.send_inspection_notice(message)


def _number_list(
    value: str | Iterable[int | float],
    *,
    name: str,
    integer: bool = False,
) -> tuple[int | float, ...]:
    raw = value.split(",") if isinstance(value, str) else list(value)
    result: list[int | float] = []
    for item in raw:
        text = str(item).strip()
        if not text:
            raise ValueError(f"{name} contains an empty value")
        number = int(text) if integer else float(text)
        if not math.isfinite(float(number)) or float(number) <= 0:
            raise ValueError(f"{name} must contain only positive finite values")
        if number not in result:
            result.append(number)
    if not result:
        raise ValueError(f"{name} must not be empty")
    return tuple(sorted(result))


def _default_stem(
    pair_name: str,
    start: dt.datetime,
    end: dt.datetime,
    spread_pips: float,
) -> str:
    return (
        f"{pair_name}_{start:%Y%m%d}_{end:%Y%m%d}"
        f"_m5line60_range6x3_rr1.2_sp{spread_pips:g}_60m"
    )


def _default_event_path(
    pair_name: str,
    start: dt.datetime,
    end: dt.datetime,
    spread_pips: float,
) -> Path:
    return Path(tk.folder_path) / (
        "resistance_sweep_events_"
        + _default_stem(pair_name, start, end, spread_pips)
        + ".csv"
    )


def _default_candidate_path(
    pair_name: str,
    start: dt.datetime,
    end: dt.datetime,
    spread_pips: float,
) -> Path:
    return Path(tk.folder_path) / (
        "resistance_sweep_candidates_"
        + _default_stem(pair_name, start, end, spread_pips)
        + ".csv"
    )


def _default_s5_path(pair_name: str, start: dt.datetime, end: dt.datetime) -> Path:
    name = f"{pair_name}_{start:%Y%m%d%H%M%S}_{end:%Y%m%d%H%M%S}"
    return Path(tk.folder_path) / f"s5_{name}.csv"


def _current_grid_version(pair_name: str) -> str:
    return f"{pair_name.lower()}_{GRID_VERSION}"


def _discover_grid_paths(
    output_dir: Path,
    pair_name: str,
    start: dt.datetime,
    end: dt.datetime,
    spread_pips: float | None = None,
) -> Path:
    pattern = (
        f"count2_target_grid_manifest_{pair_name}_{start:%Y%m%d}_"
        f"{end:%Y%m%d}_g*.json"
    )
    candidates: list[tuple[int, Path]] = []
    supported_versions = {
        _current_grid_version(pair_name),
        *SUPPORTED_LEGACY_GRID_VERSIONS.get(pair_name, frozenset()),
    }
    for manifest_path in output_dir.glob(pattern):
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            if payload.get("status") != "complete":
                continue
            if str(payload.get("pair")) != pair_name:
                continue
            if pd.Timestamp(payload.get("start")) != pd.Timestamp(start):
                continue
            if pd.Timestamp(payload.get("end")) != pd.Timestamp(end):
                continue
            manifest_spread = _finite(payload.get("spread_pips"))
            if spread_pips is not None and (
                manifest_spread is None
                or not math.isclose(
                    manifest_spread,
                    float(spread_pips),
                    rel_tol=0.0,
                    abs_tol=1e-9,
                )
            ):
                continue
            if (
                spread_pips is not None
                and str(payload.get("version")) not in supported_versions
            ):
                continue
            if payload.get("max_source_rows") is not None:
                continue
            raw_path = payload.get("outputs", {}).get("paths")
            if not raw_path:
                continue
            path = Path(raw_path)
            if path.exists():
                candidates.append((manifest_path.stat().st_mtime_ns, path))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
    if not candidates:
        raise FileNotFoundError(
            "A matching completed target-grid manifest was not found for "
            f"{pair_name} {start:%Y-%m-%d} to {end:%Y-%m-%d}"
        )
    return max(candidates, key=lambda item: item[0])[1]


def _same_path(left: Any, right: Path) -> bool:
    try:
        return Path(str(left)).resolve() == Path(right).resolve()
    except (OSError, TypeError, ValueError):
        return False


def _load_grid_manifest_for_path(
    grid_paths: Path,
    *,
    pair_name: str,
    start: dt.datetime,
    end: dt.datetime,
    spread_pips: float,
) -> tuple[Path, dict[str, Any]]:
    pattern = (
        f"count2_target_grid_manifest_{pair_name}_{start:%Y%m%d}_"
        f"{end:%Y%m%d}_g*.json"
    )
    matches: list[tuple[int, Path, dict[str, Any]]] = []
    for manifest_path in grid_paths.parent.glob(pattern):
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest_spread = _finite(payload.get("spread_pips"))
            if (
                payload.get("status") != "complete"
                or str(payload.get("pair")) != pair_name
                or pd.Timestamp(payload.get("start")) != pd.Timestamp(start)
                or pd.Timestamp(payload.get("end")) != pd.Timestamp(end)
                or manifest_spread is None
                or not math.isclose(
                    manifest_spread,
                    spread_pips,
                    rel_tol=0.0,
                    abs_tol=1e-9,
                )
                or payload.get("max_source_rows") is not None
                or not _same_path(payload.get("outputs", {}).get("paths"), grid_paths)
            ):
                continue
            matches.append((manifest_path.stat().st_mtime_ns, manifest_path, payload))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
    if not matches:
        raise ValueError(
            "Grid paths are not backed by a matching completed manifest: "
            f"{grid_paths}"
        )
    _, manifest_path, payload = max(matches, key=lambda item: item[0])
    return manifest_path, payload


def _validate_grid_manifest_inputs(
    payload: dict[str, Any],
    *,
    source_events: Path,
    source_candidates: Path,
    s5_cache: Path,
) -> None:
    contracts = (
        ("source_events", "source_events_stat", source_events),
        ("source_candidates", "source_candidates_stat", source_candidates),
        ("s5_cache", "s5_cache_stat", s5_cache),
    )
    for path_field, stat_field, actual_path in contracts:
        if not _same_path(payload.get(path_field), actual_path):
            raise ValueError(
                f"Grid manifest {path_field} does not match requested input: "
                f"{actual_path}"
            )
        expected_stat = payload.get(stat_field)
        if expected_stat != _source_stat(actual_path):
            raise ValueError(
                f"Grid manifest {stat_field} no longer matches the input file: "
                f"{actual_path}"
            )


def parse_args(
    argv: list[str] | None = None,
    *,
    default_pair: str = DEFAULT_PAIR_NAME,
    default_start: dt.datetime = DEFAULT_START,
    default_end: dt.datetime = DEFAULT_END,
) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Future-safe count2 signal/fill/exit time-decay analysis"
    )
    parser.add_argument("--pair", choices=tuple(gene.CURRENCY_PAIRS), default=default_pair)
    parser.add_argument("--start", default=default_start.isoformat(" "))
    parser.add_argument("--end", default=default_end.isoformat(" "))
    parser.add_argument("--source-events", type=Path, default=None)
    parser.add_argument("--source-candidates", type=Path, default=None)
    parser.add_argument("--grid-paths", type=Path, default=None)
    parser.add_argument("--s5-cache", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=Path(tk.folder_path))
    parser.add_argument(
        "--horizons-minutes",
        default=",".join(str(value) for value in DEFAULT_HORIZONS),
    )
    parser.add_argument("--spread-pips", type=float, default=DEFAULT_SPREAD_PIPS)
    parser.add_argument("--read-chunk-size", type=int, default=DEFAULT_READ_CHUNK_SIZE)
    parser.add_argument("--max-event-rows", type=int, default=None)
    parser.add_argument("--max-path-rows", type=int, default=None)
    parser.add_argument(
        "--include-retrospective-policy-scopes",
        action="store_true",
        help=(
            "Also group by research-selected live policies. This is a "
            "retrospective diagnostic, not a causal or out-of-sample test."
        ),
    )
    args = parser.parse_args(argv)
    args.start = pd.Timestamp(args.start).to_pydatetime()
    args.end = pd.Timestamp(args.end).to_pydatetime()
    if args.start >= args.end:
        parser.error("--start must be earlier than --end")
    try:
        args.horizons_minutes = tuple(
            int(value)
            for value in _number_list(
                args.horizons_minutes,
                name="--horizons-minutes",
                integer=True,
            )
        )
    except (TypeError, ValueError) as error:
        parser.error(str(error))
    if args.spread_pips < 0:
        parser.error("--spread-pips must be non-negative")
    if args.read_chunk_size < 1:
        parser.error("--read-chunk-size must be positive")
    for field in ("max_event_rows", "max_path_rows"):
        value = getattr(args, field)
        if value is not None and value < 1:
            parser.error(f"--{field.replace('_', '-')} must be positive")
    args.source_events = args.source_events or _default_event_path(
        args.pair, args.start, args.end, args.spread_pips
    )
    args.source_candidates = args.source_candidates or _default_candidate_path(
        args.pair, args.start, args.end, args.spread_pips
    )
    args.s5_cache = args.s5_cache or _default_s5_path(
        args.pair, args.start, args.end
    )
    return args


def _config(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "version": ANALYSIS_VERSION,
        "pair": args.pair,
        "start": args.start.isoformat(" "),
        "end": args.end.isoformat(" "),
        "horizons_minutes": list(args.horizons_minutes),
        "spread_pips": args.spread_pips,
        "source_events": str(args.source_events),
        "source_candidates": str(args.source_candidates),
        "grid_paths": str(args.grid_paths),
        "s5_cache": str(args.s5_cache),
        "max_event_rows": args.max_event_rows,
        "max_path_rows": args.max_path_rows,
        "include_retrospective_policy_scopes": (
            args.include_retrospective_policy_scopes
        ),
        "future_outcomes_only": True,
    }


def output_paths(args: argparse.Namespace) -> dict[str, Path]:
    encoded = json.dumps(_config(args), sort_keys=True, ensure_ascii=True)
    fingerprint = hashlib.sha256(encoded.encode("ascii")).hexdigest()[:10]
    stem = f"{args.pair}_{args.start:%Y%m%d}_{args.end:%Y%m%d}_t{fingerprint}"
    root = Path(args.output_dir)
    return {
        "event_horizon": root / f"count2_time_decay_event_horizon_{stem}.csv",
        "entry_horizon": root / f"count2_time_decay_entry_horizon_{stem}.csv",
        "fill_delay": root / f"count2_time_decay_fill_delay_{stem}.csv",
        "last_reach": root / f"count2_time_decay_last_reach_{stem}.csv",
        "barrier_times": root / f"count2_time_decay_barrier_times_{stem}.csv",
        "manifest": root / f"count2_time_decay_manifest_{stem}.json",
        "progress": root / f"count2_time_decay_progress_{stem}.json",
    }


def _archive_generation(paths: dict[str, Path]) -> None:
    for path in paths.values():
        if path.exists():
            _archive_file(path)
        for suffix in (".tmp", ".part"):
            residual = path.with_suffix(path.suffix + suffix)
            if residual.exists():
                _archive_file(residual)


def _write_progress(
    path: Path,
    *,
    args: argparse.Namespace,
    status: str,
    phase: str,
    started_at: dt.datetime,
    processed: int = 0,
    total: int | None = None,
    censored: int = 0,
    skipped: int = 0,
    error: str | None = None,
) -> None:
    percent = 100.0 * processed / total if total else None
    _write_json_atomic(
        path,
        {
            "version": ANALYSIS_VERSION,
            "pair": args.pair,
            "pid": os.getpid(),
            "status": status,
            "phase": phase,
            "started_at": started_at.isoformat(timespec="seconds"),
            "updated_at": dt.datetime.now().astimezone().isoformat(
                timespec="seconds"
            ),
            "processed_rows": processed,
            "total_rows": total,
            "progress_percent": round(percent, 3) if percent is not None else None,
            "censored_observations": censored,
            "skipped_rows": skipped,
            "error": error,
        },
    )


def _count_csv_rows(path: Path) -> int:
    if path.stat().st_size == 0:
        return 0
    with path.open("rb") as handle:
        newline_count = sum(
            block.count(b"\n")
            for block in iter(lambda: handle.read(8 << 20), b"")
        )
        handle.seek(-1, os.SEEK_END)
        has_unterminated_line = handle.read(1) not in {b"\r", b"\n"}
    logical_lines = newline_count + int(has_unterminated_line)
    return max(logical_lines - 1, 0)


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if value is None or bool(pd.isna(value)):
        return None
    text = str(value).strip().lower()
    if text in {"true", "1", "yes"}:
        return True
    if text in {"false", "0", "no"}:
        return False
    return None


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _timestamp(value: Any) -> pd.Timestamp | None:
    parsed = pd.to_datetime(value, errors="coerce")
    return None if pd.isna(parsed) else pd.Timestamp(parsed)


def _time_bucket(minutes: float | None, edges: tuple[int, ...]) -> str:
    if minutes is None or not math.isfinite(minutes) or minutes < 0:
        return "UNKNOWN"
    lower = 0
    for upper in edges:
        if minutes < upper:
            return f"{lower}-{upper}m"
        lower = upper
    return f"{lower}m+"


def fill_delay_bucket(minutes: float | None) -> str:
    return _time_bucket(minutes, DEFAULT_FILL_DELAY_EDGES)


def last_reach_bucket(minutes: float | None) -> str:
    return _time_bucket(minutes, DEFAULT_LAST_REACH_EDGES)


@dataclass
class MetricState:
    total_count: int = 0
    complete_count: int = 0
    censored_count: int = 0
    filled_count: int = 0
    positive_count: int = 0
    negative_count: int = 0
    zero_count: int = 0
    sum_pips: float = 0.0
    sum_mfe_pips: float = 0.0
    sum_mae_pips: float = 0.0
    mfe_count: int = 0
    mae_count: int = 0

    def add(
        self,
        *,
        complete: bool,
        result_pips: float | None = None,
        mfe_pips: float | None = None,
        mae_pips: float | None = None,
        filled: bool = False,
    ) -> None:
        self.total_count += 1
        self.filled_count += int(filled)
        if not complete or result_pips is None or not math.isfinite(result_pips):
            self.censored_count += 1
            return
        self.complete_count += 1
        self.sum_pips += result_pips
        if result_pips > 0:
            self.positive_count += 1
        elif result_pips < 0:
            self.negative_count += 1
        else:
            self.zero_count += 1
        if mfe_pips is not None and math.isfinite(mfe_pips):
            self.sum_mfe_pips += mfe_pips
            self.mfe_count += 1
        if mae_pips is not None and math.isfinite(mae_pips):
            self.sum_mae_pips += mae_pips
            self.mae_count += 1

    def values(self) -> dict[str, Any]:
        denominator = self.complete_count
        return {
            "total_count": self.total_count,
            "complete_count": self.complete_count,
            "censored_count": self.censored_count,
            "filled_count": self.filled_count,
            "positive_count": self.positive_count,
            "negative_count": self.negative_count,
            "zero_count": self.zero_count,
            "mfe_count": self.mfe_count,
            "mae_count": self.mae_count,
            "completion_rate": self.complete_count / self.total_count
            if self.total_count
            else np.nan,
            "positive_rate": self.positive_count / denominator
            if denominator
            else np.nan,
            "sum_pips": self.sum_pips,
            "expectancy_pips": self.sum_pips / denominator
            if denominator
            else np.nan,
            "average_mfe_pips": self.sum_mfe_pips / self.mfe_count
            if self.mfe_count
            else np.nan,
            "average_mae_pips": self.sum_mae_pips / self.mae_count
            if self.mae_count
            else np.nan,
        }


def _window_complete(inspector: Any, start: pd.Timestamp, end: pd.Timestamp) -> bool:
    if end <= start:
        return False
    start_index = int(
        np.searchsorted(inspector.times, np.datetime64(start, "ns"), side="left")
    )
    end_index = int(
        np.searchsorted(inspector.times, np.datetime64(end, "ns"), side="left")
    )
    times = inspector.times[start_index:end_index]
    return bool(len(times)) and _is_complete_market_window(times, start, end)


def _metrics_at_cutoffs(
    inspector: Any,
    *,
    start: pd.Timestamp,
    cutoffs: dict[Any, pd.Timestamp],
    entry_price: float,
    direction: int,
    spread_pips: float,
    requested_end: pd.Timestamp,
    fill_at_bar_open: bool = True,
) -> dict[Any, tuple[bool, float | None, float | None, float | None]]:
    result: dict[Any, tuple[bool, float | None, float | None, float | None]] = {}
    valid_cutoffs = {
        key: value for key, value in cutoffs.items() if value <= requested_end
    }
    for key in cutoffs:
        if key not in valid_cutoffs:
            result[key] = (False, None, None, None)
    if not valid_cutoffs:
        return result
    max_end = max(valid_cutoffs.values())
    start_index = int(
        np.searchsorted(inspector.times, np.datetime64(start, "ns"), side="left")
    )
    max_end_index = int(
        np.searchsorted(inspector.times, np.datetime64(max_end, "ns"), side="left")
    )
    times = inspector.times[start_index:max_end_index]
    if not len(times):
        for key in valid_cutoffs:
            result[key] = (False, None, None, None)
        return result
    half_spread = inspector.pair.pips_to_price(spread_pips / 2.0)
    highs = inspector.highs[start_index:max_end_index]
    lows = inspector.lows[start_index:max_end_index]
    closes = inspector.closes[start_index:max_end_index]
    if direction == 1:
        favorable = (highs - half_spread - entry_price) / inspector.pair.pip_value
        adverse = (lows - half_spread - entry_price) / inspector.pair.pip_value
        marks = (closes - half_spread - entry_price) / inspector.pair.pip_value
    else:
        favorable = (entry_price - (lows + half_spread)) / inspector.pair.pip_value
        adverse = (entry_price - (highs + half_spread)) / inspector.pair.pip_value
        marks = (entry_price - (closes + half_spread)) / inspector.pair.pip_value
    if not fill_at_bar_open:
        favorable = favorable.copy()
        favorable[0] = max(0.0, float(marks[0]))
    cumulative_mfe = np.maximum.accumulate(np.maximum(favorable, 0.0))
    cumulative_mae = np.minimum.accumulate(np.minimum(adverse, 0.0))
    for key, cutoff in valid_cutoffs.items():
        count = int(
            np.searchsorted(times, np.datetime64(cutoff, "ns"), side="left")
        )
        window_times = times[:count]
        complete = bool(window_times.size) and _is_complete_market_window(
            window_times, start, cutoff
        )
        if not complete:
            result[key] = (False, None, None, None)
            continue
        position = count - 1
        result[key] = (
            True,
            float(marks[position]),
            float(cumulative_mfe[position]),
            float(cumulative_mae[position]),
        )
    return result


def _policy_condition_ids(policy: dict[str, Any]) -> frozenset[str]:
    source = str(policy.get("timeframe", "")).upper()
    field = str(policy.get("field", ""))
    operator = str(policy.get("operator", ""))
    if field.startswith("criteria."):
        condition = _condition(
            source,
            "criterion_" + field.split(".", 1)[1],
            policy.get("value"),
        )
        return frozenset((condition.condition_id,)) if condition else frozenset()
    if operator in {"equals", "equals_number"}:
        condition = _condition(source, field, policy.get("value"))
        return frozenset((condition.condition_id,)) if condition else frozenset()
    if field.endswith("pullback_ratio") or field.endswith("pullback_foot_ratio"):
        edges, labels = RATIO_EDGES, RATIO_LABELS
    elif field == "dominance_ratio" or field.endswith("_required_ratio"):
        edges, labels = DOMINANCE_EDGES, DOMINANCE_LABELS
    elif field.endswith("_break_pips") or field.endswith("structure_progress_pips"):
        edges, labels = PROGRESS_EDGES, PROGRESS_LABELS
    else:
        edges, labels = PACE_EDGES, PACE_LABELS
    minimum = _finite(policy.get("minimum"))
    maximum = _finite(policy.get("maximum"))
    selected: list[str] = []
    for index, label in enumerate(labels):
        lower = float(edges[index])
        upper = float(edges[index + 1])
        if operator == "range":
            include = minimum is not None and maximum is not None and (
                lower >= minimum and upper <= maximum
            )
        elif operator == "less_than":
            include = maximum is not None and upper <= maximum
        elif operator == "at_least":
            include = minimum is not None and lower >= minimum
        else:
            return frozenset()
        if include:
            condition = _condition(source, field + "_bin", label)
            if condition:
                selected.append(condition.condition_id)
    return frozenset(selected)


def _policy_condition_id(policy: dict[str, Any]) -> str | None:
    """Compatibility helper for policies which map to exactly one grid condition."""
    condition_ids = _policy_condition_ids(policy)
    return next(iter(condition_ids)) if len(condition_ids) == 1 else None


def _policies(pair_name: str) -> list[dict[str, Any]]:
    if pair_name != "USD_JPY":
        return []
    result: list[dict[str, Any]] = []
    for priority, raw in enumerate(
        LineStrategyProfileUsdJpy.predict_reversal_grid_conditions, 1
    ):
        policy = dict(raw)
        policy["priority"] = priority
        policy["condition_ids"] = _policy_condition_ids(policy)
        if not policy["condition_ids"]:
            raise ValueError(
                f"Policy cannot be represented by grid conditions: {policy['label']}"
            )
        result.append(policy)
    return result


def _row_scopes(
    row: pd.Series,
    policies: list[dict[str, Any]],
) -> list[str]:
    scopes = ["ALL"]
    if not policies:
        return scopes
    try:
        conditions = set(json.loads(str(row.get("conditions_json") or "[]")))
    except (TypeError, ValueError, json.JSONDecodeError):
        return scopes
    rank = int(float(row["entry_candidate_rank"]))
    offset = float(row["entry_offset_range_multiplier"])
    for policy in policies:
        if not conditions.intersection(policy.get("condition_ids", frozenset())):
            continue
        if rank != int(policy["entry_rank"]):
            continue
        if not math.isclose(
            offset,
            float(policy["entry_offset_range_multiplier"]),
            abs_tol=1e-9,
        ):
            continue
        scopes.append(f"POLICY_{int(policy['priority']):02d}")
    return scopes


def _load_last_reach(
    args: argparse.Namespace,
) -> tuple[dict[tuple[str, int], dict[str, Any]], Counter[str]]:
    header = list(pd.read_csv(args.source_candidates, nrows=0).columns)
    base = ["event_id", "pair", "decision_time", "candidate_rank"]
    optional = [
        "predict_rank_last_reach_elapsed_minutes",
        "predict_rank_last_reach_source",
        "predict_rank_prior_retouch_count",
        "predict_last_reach_elapsed_minutes",
        "predict_last_reach_source",
        "predict_prior_retouch_count",
        "minutes_since_prior_retouch",
        "prior_retouch_last_time",
    ]
    missing = [column for column in base if column not in header]
    if missing:
        raise ValueError(
            "Candidate CSV lacks identity columns: " + ", ".join(missing)
        )
    usecols = base + [column for column in optional if column in header]
    result: dict[tuple[str, int], dict[str, Any]] = {}
    stats: Counter[str] = Counter()
    for chunk in pd.read_csv(
        args.source_candidates,
        usecols=usecols,
        chunksize=max(args.read_chunk_size, 1000),
    ):
        for _, row in chunk.iterrows():
            if str(row["pair"]) != args.pair:
                stats["wrong_pair"] += 1
                continue
            decision = _timestamp(row["decision_time"])
            if decision is None or not pd.Timestamp(args.start) <= decision < pd.Timestamp(args.end):
                stats["outside_period"] += 1
                continue
            try:
                rank = int(float(row["candidate_rank"]))
            except (TypeError, ValueError):
                stats["invalid_rank"] += 1
                continue
            elapsed = _finite(row.get("predict_rank_last_reach_elapsed_minutes"))
            source = row.get("predict_rank_last_reach_source")
            retouch_count = _finite(row.get("predict_rank_prior_retouch_count"))
            if elapsed is None:
                elapsed = _finite(row.get("predict_last_reach_elapsed_minutes"))
                if source is None or pd.isna(source):
                    source = row.get("predict_last_reach_source")
                if retouch_count is None:
                    retouch_count = _finite(row.get("predict_prior_retouch_count"))
            if elapsed is None:
                elapsed = _finite(row.get("minutes_since_prior_retouch"))
                if source is None or pd.isna(source):
                    source = "prior_retouch_fallback"
            if elapsed is None:
                prior = _timestamp(row.get("prior_retouch_last_time"))
                if prior is not None and prior <= decision:
                    elapsed = (decision - prior).total_seconds() / 60.0
                    if source is None or pd.isna(source):
                        source = "prior_retouch_time_fallback"
            if elapsed is not None and elapsed < 0:
                elapsed = None
                source = "invalid_future_last_reach"
                stats["invalid_future_last_reach"] += 1
            key = (str(row["event_id"]), rank)
            if key in result:
                raise ValueError(f"Duplicate candidate last-reach identity: {key}")
            source_text = (
                "unknown"
                if source is None or pd.isna(source)
                else str(source)
            )
            result[key] = {
                "elapsed_minutes": elapsed,
                "source": source_text,
                "retouch_count": retouch_count,
                "decision_time": decision,
            }
            stats["loaded"] += 1
    return result, stats


def _metric_rows(
    states: dict[tuple[Any, ...], MetricState],
    names: tuple[str, ...],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in sorted(states, key=lambda value: tuple(str(item) for item in value)):
        row = dict(zip(names, key))
        row.update(states[key].values())
        rows.append(row)
    return rows


def _write_csv_atomic(
    path: Path,
    rows: list[dict[str, Any]],
    *,
    columns: Iterable[str] | None = None,
) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    if temporary.exists():
        _archive_file(temporary)
    frame = pd.DataFrame(rows, columns=list(columns) if columns is not None else None)
    frame.to_csv(temporary, index=False)
    os.replace(temporary, path)


def _threshold_stems(columns: Iterable[str], prefix: str) -> list[str]:
    suffix = "_first_index"
    stems = {
        column[: -len(suffix)]
        for column in columns
        if column.startswith(prefix + "_")
        and column.endswith(suffix)
        and "_raw_" not in column
    }
    return sorted(stems)


def _multiplier_from_stem(stem: str) -> float:
    tag = stem.split("_", 1)[1].removesuffix("A").removeprefix("p")
    return float(tag.replace("p", ".").replace("m", "-"))


def _barrier_bucket(minutes: float | None) -> str:
    return _time_bucket(minutes, DEFAULT_FILL_DELAY_EDGES)


def run_analysis(args: argparse.Namespace) -> dict[str, Path]:
    args._generation_started = False
    if args.grid_paths is None:
        args.grid_paths = _discover_grid_paths(
            args.output_dir,
            args.pair,
            args.start,
            args.end,
            args.spread_pips,
        )
    for path in (
        args.source_events,
        args.source_candidates,
        args.grid_paths,
        args.s5_cache,
    ):
        if not Path(path).exists():
            raise FileNotFoundError(f"Required existing artifact was not found: {path}")
    grid_manifest_path, grid_manifest = _load_grid_manifest_for_path(
        args.grid_paths,
        pair_name=args.pair,
        start=args.start,
        end=args.end,
        spread_pips=args.spread_pips,
    )
    _validate_grid_manifest_inputs(
        grid_manifest,
        source_events=args.source_events,
        source_candidates=args.source_candidates,
        s5_cache=args.s5_cache,
    )
    if not s5_cache_has_no_tick_completion(args.s5_cache):
        raise ValueError(
            "S5 cache predates auditable no-tick completion and cannot be used: "
            f"{args.s5_cache}"
        )

    event_total = _count_csv_rows(args.source_events)
    path_total = _count_csv_rows(args.grid_paths)
    if event_total <= 0:
        raise ValueError(f"Event ledger has no data rows: {args.source_events}")
    if path_total <= 0:
        raise ValueError(f"Grid paths have no data rows: {args.grid_paths}")
    manifest_path_rows = grid_manifest.get("grid_path_rows")
    if manifest_path_rows is None or int(manifest_path_rows) != path_total:
        raise ValueError(
            "Grid path row count no longer matches its completed manifest: "
            f"manifest={manifest_path_rows}, actual={path_total}"
        )

    event_columns = [
        "event_id",
        "pair",
        "decision_time",
        "decision_price",
        "peak_direction",
        "peak_count",
        "event_status",
    ]
    event_header = list(pd.read_csv(args.source_events, nrows=0).columns)
    missing_event = [column for column in event_columns if column not in event_header]
    if missing_event:
        raise ValueError("Event ledger lacks columns: " + ", ".join(missing_event))

    path_header = list(pd.read_csv(args.grid_paths, nrows=0).columns)
    tp_stems = _threshold_stems(path_header, "tp")
    lc_stems = _threshold_stems(path_header, "lc")
    if not tp_stems or not lc_stems:
        raise ValueError("Grid paths lack TP or LC threshold columns")
    required_path_columns = [
        "grid_version",
        "grid_path_id",
        "entry_offset_index",
        "event_id",
        "pair",
        "decision_time",
        "pending_expiry_time",
        "entry_rank_source",
        "entry_candidate_rank",
        "entry_offset_range_multiplier",
        "entry_price",
        "trade_direction",
        "conditions_json",
        "pending_path_complete",
        "filled",
        "fill_time",
        "fill_delay_seconds",
        "fill_at_bar_open",
        "horizon_end",
        "horizon_complete",
        "timeout_result_pips",
        "fixed_spread_pips",
        "position_horizon_minutes",
        "marketable_limit_excluded",
    ]
    threshold_columns = [
        stem + suffix
        for stem in (*tp_stems, *lc_stems)
        for suffix in ("_reached", "_first_index", "_first_time")
    ]
    missing_path = [
        column
        for column in required_path_columns + threshold_columns
        if column not in path_header
    ]
    if missing_path:
        raise ValueError("Grid paths lack columns: " + ", ".join(missing_path))

    manifest_horizon = _finite(grid_manifest.get("horizon_minutes"))
    if manifest_horizon is None or manifest_horizon <= 0:
        raise ValueError("Grid manifest has an invalid horizon_minutes")
    manifest_version = str(grid_manifest.get("version") or "")
    if grid_manifest.get("entry_rank_source") != "raw_distance_rank":
        raise ValueError("Grid manifest does not use raw distance entry ranks")
    supported_grid_versions = {
        _current_grid_version(args.pair),
        *SUPPORTED_LEGACY_GRID_VERSIONS.get(args.pair, frozenset()),
    }
    if manifest_version not in supported_grid_versions:
        raise ValueError(
            "Grid manifest version does not match this analyzer: "
            f"manifest={manifest_version}, supported={sorted(supported_grid_versions)}"
        )
    expected_tp = sorted(float(value) for value in grid_manifest.get("tp_range_multipliers", []))
    expected_lc = sorted(float(value) for value in grid_manifest.get("lc_range_multipliers", []))
    actual_tp = sorted(_multiplier_from_stem(stem) for stem in tp_stems)
    actual_lc = sorted(_multiplier_from_stem(stem) for stem in lc_stems)
    if expected_tp != actual_tp or expected_lc != actual_lc:
        raise ValueError(
            "Grid threshold columns do not match the completed manifest"
        )

    paths = output_paths(args)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    args._generation_started = True
    _archive_generation(paths)
    started_at = dt.datetime.now().astimezone()
    process_started = time.monotonic()
    _write_progress(
        paths["progress"],
        args=args,
        status="running",
        phase="loading_existing_data",
        started_at=started_at,
    )
    _notify(
        "\n".join(
            [
                f"{args.pair} count2 time-decay analysis 開始",
                f"- 期間: {args.start:%Y-%m-%d} から {args.end:%Y-%m-%d} 未満",
                f"- 時点: {list(args.horizons_minutes)}分",
                "- 入力: 既存event/candidate/grid path/S5のみ",
                "- OANDA通信: なし",
                "- 期間末・未知のS5欠損: censoredとして除外",
                (
                    "- policy scope: 回顧診断として明示的に有効"
                    if args.include_retrospective_policy_scopes
                    else "- policy scope: 無効（因果的なALL/raw rankのみ）"
                ),
            ]
        )
    )

    pair = gene.currency_pair(args.pair)
    inspector, typed_metadata = _load_typed_s5_inspector(args.s5_cache, pair)
    inspector = _bound_inspector_before(inspector, pd.Timestamp(args.end))
    last_reach, last_reach_load_stats = _load_last_reach(args)
    policies = (
        _policies(args.pair)
        if args.include_retrospective_policy_scopes
        else []
    )
    policy_labels = {
        f"POLICY_{int(policy['priority']):02d}": policy["label"]
        for policy in policies
    }

    event_states: dict[tuple[Any, ...], MetricState] = defaultdict(MetricState)
    entry_states: dict[tuple[Any, ...], MetricState] = defaultdict(MetricState)
    reach_states: dict[tuple[Any, ...], MetricState] = defaultdict(MetricState)
    fill_states: dict[tuple[Any, ...], MetricState] = defaultdict(MetricState)
    barrier_counts: Counter[tuple[Any, ...]] = Counter()
    skipped: Counter[str] = Counter()
    requested_end = pd.Timestamp(args.end)

    if args.max_event_rows is not None:
        event_total = min(event_total, args.max_event_rows)
    event_processed = 0
    seen_events: set[str] = set()
    valid_event_ids: set[str] = set()
    valid_event_decisions: dict[str, pd.Timestamp] = {}
    for chunk in pd.read_csv(
        args.source_events,
        usecols=event_columns,
        chunksize=args.read_chunk_size,
    ):
        for _, row in chunk.iterrows():
            if args.max_event_rows is not None and event_processed >= args.max_event_rows:
                break
            event_processed += 1
            event_id = str(row["event_id"])
            if event_id in seen_events:
                raise ValueError(f"Duplicate event_id in event ledger: {event_id}")
            seen_events.add(event_id)
            decision = _timestamp(row["decision_time"])
            decision_price = _finite(row["decision_price"])
            peak_direction = _finite(row["peak_direction"])
            if (
                str(row["pair"]) != args.pair
                or decision is None
                or not pd.Timestamp(args.start) <= decision < requested_end
                or decision_price is None
                or peak_direction not in (-1.0, 1.0)
                or _finite(row["peak_count"]) != 2.0
            ):
                skipped["invalid_event"] += 1
                continue
            valid_event_ids.add(event_id)
            valid_event_decisions[event_id] = decision
            direction = -int(peak_direction)
            half_spread = pair.pips_to_price(args.spread_pips / 2.0)
            entry_price = decision_price + direction * half_spread
            cutoffs = {
                horizon: decision + pd.Timedelta(minutes=horizon)
                for horizon in args.horizons_minutes
            }
            metrics = _metrics_at_cutoffs(
                inspector,
                start=decision,
                cutoffs=cutoffs,
                entry_price=entry_price,
                direction=direction,
                spread_pips=args.spread_pips,
                requested_end=requested_end,
            )
            for horizon, (complete, mark, mfe, mae) in metrics.items():
                event_states[(horizon,)].add(
                    complete=complete,
                    result_pips=mark,
                    mfe_pips=mfe,
                    mae_pips=mae,
                    filled=True,
                )
        if args.max_event_rows is not None and event_processed >= args.max_event_rows:
            break
    if not valid_event_ids:
        raise ValueError("No valid foot-count-2 events remain in the requested period")
    _write_progress(
        paths["progress"],
        args=args,
        status="running",
        phase="analyzing_entry_paths",
        started_at=started_at,
        processed=0,
        total=None,
        censored=sum(state.censored_count for state in event_states.values()),
        skipped=sum(skipped.values()),
    )

    if args.max_path_rows is not None:
        path_total = min(path_total, args.max_path_rows)
    path_processed = 0
    valid_path_count = 0
    seen_grid_path_ids: set[str] = set()
    seen_grid_semantic_keys: set[tuple[str, int, int]] = set()
    expected_ranks = {int(value) for value in grid_manifest.get("entry_ranks", [])}
    expected_offsets = {
        index: float(value)
        for index, value in enumerate(
            grid_manifest.get("entry_offset_range_multipliers", [])
        )
    }
    next_notice = 25
    for chunk in pd.read_csv(
        args.grid_paths,
        usecols=required_path_columns + threshold_columns,
        chunksize=args.read_chunk_size,
    ):
        for _, row in chunk.iterrows():
            if args.max_path_rows is not None and path_processed >= args.max_path_rows:
                break
            path_processed += 1
            raw_grid_path_id = row["grid_path_id"]
            if raw_grid_path_id is None or pd.isna(raw_grid_path_id):
                raise ValueError("Grid paths contain an empty grid_path_id")
            grid_path_id = str(raw_grid_path_id)
            if grid_path_id in seen_grid_path_ids:
                raise ValueError(f"Duplicate grid_path_id: {grid_path_id}")
            seen_grid_path_ids.add(grid_path_id)

            row_spread = _finite(row["fixed_spread_pips"])
            row_horizon = _finite(row["position_horizon_minutes"])
            if (
                str(row["pair"]) != args.pair
                or str(row["grid_version"]) != manifest_version
                or str(row["entry_rank_source"]) != "raw_distance_rank"
                or row_spread is None
                or not math.isclose(
                    row_spread,
                    args.spread_pips,
                    rel_tol=0.0,
                    abs_tol=1e-9,
                )
                or row_horizon is None
                or not math.isclose(
                    row_horizon,
                    manifest_horizon,
                    rel_tol=0.0,
                    abs_tol=1e-9,
                )
            ):
                raise ValueError(
                    f"Grid path config does not match its manifest: {grid_path_id}"
                )

            marketable = _as_bool(row["marketable_limit_excluded"])
            if marketable is None:
                raise ValueError(
                    f"Grid path has an invalid marketable flag: {grid_path_id}"
                )
            if marketable:
                skipped["marketable_limit"] += 1
                continue

            decision = _timestamp(row["decision_time"])
            expiry = _timestamp(row["pending_expiry_time"])
            entry_price = _finite(row["entry_price"])
            direction_value = _finite(row["trade_direction"])
            try:
                rank = int(float(row["entry_candidate_rank"]))
                offset_index = int(float(row["entry_offset_index"]))
                offset = float(row["entry_offset_range_multiplier"])
            except (TypeError, ValueError):
                rank = 0
                offset_index = -1
                offset = math.nan
            event_id = str(row["event_id"])
            semantic_key = (event_id, rank, offset_index)
            expected_grid_path_id = f"{event_id}_rank{rank}_off{offset_index}"
            if (
                decision is None
                or expiry is None
                or expiry <= decision
                or entry_price is None
                or direction_value not in (-1.0, 1.0)
                or not pd.Timestamp(args.start) <= decision < requested_end
                or rank not in expected_ranks
                or offset_index not in expected_offsets
                or grid_path_id != expected_grid_path_id
                or not math.isclose(
                    offset,
                    expected_offsets.get(offset_index, math.inf),
                    rel_tol=0.0,
                    abs_tol=1e-9,
                )
                or (
                    args.max_event_rows is None
                    and event_id not in valid_event_ids
                )
                or (
                    event_id in valid_event_decisions
                    and valid_event_decisions[event_id] != decision
                )
            ):
                raise ValueError(f"Invalid grid path identity/timing: {grid_path_id}")
            if semantic_key in seen_grid_semantic_keys:
                raise ValueError(f"Duplicate grid path identity: {semantic_key}")
            seen_grid_semantic_keys.add(semantic_key)

            direction = int(direction_value)
            filled_value = _as_bool(row["filled"])
            pending_complete_source = _as_bool(row["pending_path_complete"])
            source_horizon_complete = _as_bool(row["horizon_complete"])
            if (
                filled_value is None
                or pending_complete_source is None
                or source_horizon_complete is None
            ):
                raise ValueError(f"Grid path has an invalid status flag: {grid_path_id}")
            filled = filled_value
            fill_time = _timestamp(row["fill_time"])
            fill_at_bar_open = _as_bool(row["fill_at_bar_open"])
            horizon_end = _timestamp(row["horizon_end"])
            if filled:
                expected_horizon_end = (
                    fill_time + pd.Timedelta(minutes=row_horizon)
                    if fill_time is not None
                    else None
                )
                recorded_delay = _finite(row["fill_delay_seconds"])
                if (
                    fill_time is None
                    or not decision <= fill_time < min(expiry, requested_end)
                    or not pending_complete_source
                    or fill_at_bar_open is None
                    or horizon_end is None
                    or horizon_end != expected_horizon_end
                    or recorded_delay is None
                    or not math.isclose(
                        recorded_delay,
                        (fill_time - decision).total_seconds(),
                        rel_tol=0.0,
                        abs_tol=1e-6,
                    )
                ):
                    raise ValueError(f"Invalid fill contract: {grid_path_id}")
                fill_index = int(
                    np.searchsorted(
                        inspector.times,
                        np.datetime64(fill_time, "ns"),
                        side="left",
                    )
                )
                if (
                    fill_index >= len(inspector.times)
                    or inspector.times[fill_index] != np.datetime64(fill_time, "ns")
                    or fill_time + pd.Timedelta(seconds=5) > requested_end
                    or not _window_complete(
                        inspector,
                        decision,
                        fill_time + pd.Timedelta(seconds=5),
                    )
                ):
                    raise ValueError(
                        f"Filled path lacks a complete causal pending window: {grid_path_id}"
                    )
            elif fill_time is not None or horizon_end is not None:
                raise ValueError(f"Unfilled path contains fill timestamps: {grid_path_id}")

            valid_path_count += 1
            scopes = _row_scopes(row, policies)
            reach = last_reach.get((event_id, rank), {})
            if reach and reach.get("decision_time") != decision:
                skipped["last_reach_decision_mismatch"] += 1
                reach = {}
            reach_bucket = last_reach_bucket(reach.get("elapsed_minutes"))
            fill_delay_minutes = (
                (fill_time - decision).total_seconds() / 60.0
                if fill_time is not None
                else None
            )
            delay_bucket = fill_delay_bucket(fill_delay_minutes)

            fill_metrics: dict[
                int, tuple[bool, float | None, float | None, float | None]
            ] = {}
            grid_metric = (False, None, None, None)
            if fill_time is not None and horizon_end is not None:
                fill_cutoffs: dict[Any, pd.Timestamp] = {
                    ("ANALYSIS", horizon): fill_time
                    + pd.Timedelta(minutes=horizon)
                    for horizon in args.horizons_minutes
                }
                fill_cutoffs[("GRID", 0)] = horizon_end
                all_fill_metrics = _metrics_at_cutoffs(
                    inspector,
                    start=fill_time,
                    cutoffs=fill_cutoffs,
                    entry_price=entry_price,
                    direction=direction,
                    spread_pips=args.spread_pips,
                    requested_end=requested_end,
                    fill_at_bar_open=bool(fill_at_bar_open),
                )
                fill_metrics = {
                    int(key[1]): value
                    for key, value in all_fill_metrics.items()
                    if key[0] == "ANALYSIS"
                }
                computed_grid_metric = all_fill_metrics[("GRID", 0)]
                computed_grid_complete = computed_grid_metric[0]
                if source_horizon_complete != computed_grid_complete:
                    skipped["source_horizon_disagreement"] += 1
                grid_complete = bool(
                    source_horizon_complete
                    and computed_grid_complete
                    and horizon_end <= requested_end
                )
                if grid_complete:
                    source_timeout = _finite(row["timeout_result_pips"])
                    computed_timeout = computed_grid_metric[1]
                    if (
                        source_timeout is None
                        or computed_timeout is None
                        or not math.isclose(
                            source_timeout,
                            computed_timeout,
                            rel_tol=0.0,
                            abs_tol=1e-6,
                        )
                    ):
                        raise ValueError(
                            f"Grid timeout result disagrees with bounded S5: {grid_path_id}"
                        )
                    grid_metric = computed_grid_metric

            if filled:
                fill_complete, fill_mark, fill_mfe, fill_mae = grid_metric
            else:
                pending_complete = bool(
                    pending_complete_source
                    and expiry <= requested_end
                    and _window_complete(inspector, decision, expiry)
                )
                fill_complete = pending_complete
                fill_mark = 0.0 if pending_complete else None
                fill_mfe = 0.0 if pending_complete else None
                fill_mae = 0.0 if pending_complete else None

            for scope in scopes:
                fill_key = (scope, rank, offset, delay_bucket if filled else "NOT_FILLED")
                fill_states[fill_key].add(
                    complete=fill_complete,
                    result_pips=fill_mark,
                    mfe_pips=fill_mfe,
                    mae_pips=fill_mae,
                    filled=filled,
                )

            signal_cutoffs = {
                horizon: decision + pd.Timedelta(minutes=horizon)
                for horizon in args.horizons_minutes
            }
            signal_metrics: dict[
                int, tuple[bool, float | None, float | None, float | None]
            ] = {}
            filled_signal_cutoffs = {
                horizon: cutoff
                for horizon, cutoff in signal_cutoffs.items()
                if fill_time is not None and fill_time < cutoff
            }
            if filled_signal_cutoffs and fill_time is not None:
                signal_metrics.update(
                    _metrics_at_cutoffs(
                        inspector,
                        start=fill_time,
                        cutoffs=filled_signal_cutoffs,
                        entry_price=entry_price,
                        direction=direction,
                        spread_pips=args.spread_pips,
                        requested_end=requested_end,
                        fill_at_bar_open=bool(fill_at_bar_open),
                    )
                )
            for horizon, cutoff in signal_cutoffs.items():
                if horizon in signal_metrics:
                    complete, mark, mfe, mae = signal_metrics[horizon]
                    filled_by_horizon = True
                else:
                    observation_end = min(cutoff, expiry, requested_end)
                    complete = cutoff <= requested_end and _window_complete(
                        inspector, decision, observation_end
                    )
                    mark = 0.0 if complete else None
                    mfe = 0.0 if complete else None
                    mae = 0.0 if complete else None
                    filled_by_horizon = False
                for scope in scopes:
                    entry_states[(scope, "SIGNAL", rank, offset, horizon)].add(
                        complete=complete,
                        result_pips=mark,
                        mfe_pips=mfe,
                        mae_pips=mae,
                        filled=filled_by_horizon,
                    )
                    reach_states[
                        (scope, "SIGNAL", rank, offset, reach_bucket, horizon)
                    ].add(
                        complete=complete,
                        result_pips=mark,
                        mfe_pips=mfe,
                        mae_pips=mae,
                        filled=filled_by_horizon,
                    )

            if fill_time is not None and horizon_end is not None:
                for horizon, (complete, mark, mfe, mae) in fill_metrics.items():
                    for scope in scopes:
                        entry_states[(scope, "FILL", rank, offset, horizon)].add(
                            complete=complete,
                            result_pips=mark,
                            mfe_pips=mfe,
                            mae_pips=mae,
                            filled=True,
                        )
                        reach_states[
                            (scope, "FILL", rank, offset, reach_bucket, horizon)
                        ].add(
                            complete=complete,
                            result_pips=mark,
                            mfe_pips=mfe,
                            mae_pips=mae,
                            filled=True,
                        )

                barrier_limit = min(horizon_end, requested_end)

                def validated_barrier(
                    stem: str,
                ) -> tuple[str, int, pd.Timestamp | None]:
                    reached_value = _as_bool(row.get(stem + "_reached"))
                    if reached_value is False:
                        index_value = _finite(row.get(stem + "_first_index"))
                        first_time = _timestamp(row.get(stem + "_first_time"))
                        if first_time is None and index_value in (None, -1.0):
                            return "NOT_REACHED", -1, None
                        if (
                            index_value is None
                            or not float(index_value).is_integer()
                            or index_value < 0
                            or first_time is None
                        ):
                            skipped["invalid_unreached_barrier"] += 1
                            return "INVALID", -1, None
                        first_position = int(
                            np.searchsorted(
                                inspector.times,
                                np.datetime64(first_time, "ns"),
                                side="left",
                            )
                        )
                        candle_end = first_time + pd.Timedelta(seconds=5)
                        if (
                            first_position >= len(inspector.times)
                            or inspector.times[first_position]
                            != np.datetime64(first_time, "ns")
                            or first_position - fill_index != int(index_value)
                            or first_time < fill_time
                        ):
                            skipped["invalid_unreached_barrier"] += 1
                            return "INVALID", -1, None
                        if candle_end > barrier_limit or not _window_complete(
                            inspector, fill_time, candle_end
                        ):
                            return "NOT_REACHED", -1, None
                        skipped["invalid_unreached_barrier"] += 1
                        return "INVALID", -1, None
                    if reached_value is None:
                        skipped["invalid_barrier_flag"] += 1
                        return "INVALID", -1, None
                    index_value = _finite(row.get(stem + "_first_index"))
                    first_time = _timestamp(row.get(stem + "_first_time"))
                    candle_end = (
                        first_time + pd.Timedelta(seconds=5)
                        if first_time is not None
                        else None
                    )
                    if (
                        index_value is None
                        or not float(index_value).is_integer()
                        or index_value < 0
                        or first_time is None
                        or candle_end is None
                        or not fill_time <= first_time
                        or candle_end > barrier_limit
                    ):
                        skipped["invalid_barrier_time"] += 1
                        return "INVALID", -1, None
                    first_position = int(
                        np.searchsorted(
                            inspector.times,
                            np.datetime64(first_time, "ns"),
                            side="left",
                        )
                    )
                    if (
                        first_position >= len(inspector.times)
                        or inspector.times[first_position]
                        != np.datetime64(first_time, "ns")
                        or first_position - fill_index != int(index_value)
                        or not _window_complete(inspector, fill_time, candle_end)
                    ):
                        skipped["invalid_barrier_index"] += 1
                        return "INVALID", -1, None
                    return "REACHED", int(index_value), first_time

                barrier_values = {
                    stem: validated_barrier(stem)
                    for stem in (*tp_stems, *lc_stems)
                }

                def record_barrier(
                    scope: str,
                    tp_stem: str,
                    lc_stem: str,
                ) -> None:
                    tp_status, tp_index, tp_time = barrier_values[tp_stem]
                    lc_status, lc_index, lc_time = barrier_values[lc_stem]
                    tp_reached = tp_status == "REACHED"
                    lc_reached = lc_status == "REACHED"
                    if "INVALID" in (tp_status, lc_status):
                        outcome = "CENSORED"
                        first_time = None
                    elif tp_reached and (not lc_reached or tp_index < lc_index):
                        outcome = "TP"
                        first_time = tp_time
                    elif lc_reached:
                        outcome = "LC"
                        first_time = lc_time
                    elif grid_metric[0]:
                        outcome = "TIMEOUT"
                        first_time = None
                    else:
                        outcome = "CENSORED"
                        first_time = None
                    elapsed = (
                        (first_time - fill_time).total_seconds() / 60.0
                        if first_time is not None
                        else None
                    )
                    bucket = (
                        _barrier_bucket(elapsed)
                        if elapsed is not None
                        else outcome
                    )
                    barrier_counts[
                        (
                            scope,
                            rank,
                            offset,
                            _multiplier_from_stem(tp_stem),
                            _multiplier_from_stem(lc_stem),
                            outcome,
                            bucket,
                        )
                    ] += 1

                for tp_stem in tp_stems:
                    for lc_stem in lc_stems:
                        record_barrier("ALL", tp_stem, lc_stem)
                for scope in scopes:
                    if scope == "ALL":
                        continue
                    policy = policies[int(scope.split("_")[1]) - 1]
                    tp_tag = next(
                        (
                            stem
                            for stem in tp_stems
                            if math.isclose(
                                _multiplier_from_stem(stem),
                                float(policy["tp_range_multiplier"]),
                                abs_tol=1e-9,
                            )
                        ),
                        None,
                    )
                    lc_tag = next(
                        (
                            stem
                            for stem in lc_stems
                            if math.isclose(
                                _multiplier_from_stem(stem),
                                float(policy["lc_range_multiplier"]),
                                abs_tol=1e-9,
                            )
                        ),
                        None,
                    )
                    if tp_tag and lc_tag:
                        record_barrier(scope, tp_tag, lc_tag)

        if path_total:
            percent = 100.0 * min(path_processed, path_total) / path_total
            if percent >= next_notice:
                censored = sum(state.censored_count for state in entry_states.values())
                _write_progress(
                    paths["progress"],
                    args=args,
                    status="running",
                    phase="analyzing_entry_paths",
                    started_at=started_at,
                    processed=min(path_processed, path_total),
                    total=path_total,
                    censored=censored,
                    skipped=sum(skipped.values()),
                )
                _notify(
                    "\n".join(
                        [
                            f"{args.pair} count2 time-decay 進捗",
                            f"- grid path: {min(path_processed, path_total)}/{path_total} ({percent:.1f}%)",
                            f"- censored: {censored}",
                            f"- skipped: {sum(skipped.values())}",
                        ]
                    )
                )
                next_notice += 25
        if args.max_path_rows is not None and path_processed >= args.max_path_rows:
            break

    if valid_path_count <= 0:
        raise ValueError("No valid non-marketable grid paths remain for analysis")

    _write_progress(
        paths["progress"],
        args=args,
        status="running",
        phase="writing_outputs",
        started_at=started_at,
        processed=min(path_processed, path_total),
        total=path_total,
        censored=sum(state.censored_count for state in entry_states.values()),
        skipped=sum(skipped.values()),
    )
    _write_csv_atomic(
        paths["event_horizon"],
        _metric_rows(event_states, ("horizon_minutes",)),
    )
    _write_csv_atomic(
        paths["entry_horizon"],
        _metric_rows(
            entry_states,
            ("scope", "origin", "entry_rank", "entry_offset", "horizon_minutes"),
        ),
    )
    _write_csv_atomic(
        paths["fill_delay"],
        _metric_rows(
            fill_states,
            ("scope", "entry_rank", "entry_offset", "fill_delay_bucket"),
        ),
    )
    _write_csv_atomic(
        paths["last_reach"],
        _metric_rows(
            reach_states,
            (
                "scope",
                "origin",
                "entry_rank",
                "entry_offset",
                "last_reach_bucket",
                "horizon_minutes",
            ),
        ),
    )
    barrier_rows = [
        {
            "scope": key[0],
            "entry_rank": key[1],
            "entry_offset": key[2],
            "tp_range_multiplier": key[3],
            "lc_range_multiplier": key[4],
            "outcome": key[5],
            "elapsed_bucket": key[6],
            "count": count,
        }
        for key, count in sorted(
            barrier_counts.items(), key=lambda item: tuple(str(value) for value in item[0])
        )
    ]
    _write_csv_atomic(
        paths["barrier_times"],
        barrier_rows,
        columns=(
            "scope",
            "entry_rank",
            "entry_offset",
            "tp_range_multiplier",
            "lc_range_multiplier",
            "outcome",
            "elapsed_bucket",
            "count",
        ),
    )

    elapsed_minutes = (time.monotonic() - process_started) / 60.0
    manifest = {
        **_config(args),
        "status": "complete",
        "created_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "inputs": {
            "source_events": _source_stat(args.source_events),
            "source_candidates": _source_stat(args.source_candidates),
            "grid_paths": _source_stat(args.grid_paths),
            "grid_manifest": {
                "path": str(grid_manifest_path),
                **_source_stat(grid_manifest_path),
            },
            "s5_cache": _source_stat(args.s5_cache),
            "s5_typed_cache": typed_metadata,
        },
        "outputs": {name: str(path) for name, path in paths.items()},
        "event_rows_processed": event_processed,
        "path_rows_processed": path_processed,
        "valid_event_count": len(valid_event_ids),
        "valid_non_marketable_path_count": valid_path_count,
        "last_reach_load_stats": dict(last_reach_load_stats),
        "skipped_rows": dict(skipped),
        "policy_labels": policy_labels,
        "elapsed_minutes": round(elapsed_minutes, 2),
        "future_safety": {
            "decision_features_from_causal_existing_csv": True,
            "s5_used_only_after_decision_or_fill": True,
            "requested_end_exclusive": True,
            "windows_crossing_end_censored": True,
            "unknown_s5_gaps_censored": True,
            "expected_market_closures_supported": True,
            "missing_last_reach_is_unknown_not_failure": True,
            "completed_grid_manifest_required": True,
            "grid_input_provenance_and_spread_verified": True,
            "grid_outcomes_rebounded_to_requested_end": True,
            "fill_and_barrier_timestamp_contracts_verified": True,
            "retrospective_policy_scopes_included": (
                args.include_retrospective_policy_scopes
            ),
        },
        "definitions": {
            "SIGNAL": "horizon measured from foot-count-2 decision time; unfilled eligible paths contribute zero when observable",
            "FILL": "horizon measured from LIMIT fill; only filled paths are included",
            "event_return": "spread-adjusted immediate-entry counterfactual in reversal direction",
            "entry_return": "barrier-free spread-adjusted mark-to-market from actual LIMIT entry",
            "fill_delay": (
                "grouped by signal-to-fill delay; result is the barrier-free "
                f"{manifest_horizon:g}-minute mark from the LIMIT fill, not a "
                "TP/LC-realized return"
            ),
            "barrier_tie": "LC assumed when TP and LC first touch the same S5 candle",
        },
        "limitations": [
            "Time-decay returns are counterfactual and do not enforce one simultaneous position.",
            "Barrier-free horizon returns ignore earlier TP/LC exits; barrier_times reports the configured first-barrier outcomes separately.",
            (
                "Current-policy scopes are standalone matches and do not apply "
                "cross-line live priority arbitration."
                if args.include_retrospective_policy_scopes
                else None
            ),
            (
                "Current-policy scopes reuse research-selected policies as "
                "retrospective diagnostics; they are not causal policy-selection "
                "or out-of-sample proof. ALL and raw entry-rank outputs do not "
                "use that policy filter."
                if args.include_retrospective_policy_scopes
                else None
            ),
            "A max-row run is incomplete and must not be used as final evidence."
            if args.max_event_rows is not None or args.max_path_rows is not None
            else None,
        ],
    }
    manifest["limitations"] = [value for value in manifest["limitations"] if value]
    _write_json_atomic(paths["manifest"], manifest)
    _write_progress(
        paths["progress"],
        args=args,
        status="complete",
        phase="complete",
        started_at=started_at,
        processed=min(path_processed, path_total),
        total=path_total,
        censored=sum(state.censored_count for state in entry_states.values()),
        skipped=sum(skipped.values()),
    )
    archived_progress = _archive_file(paths["progress"])
    manifest["outputs"]["progress"] = str(archived_progress)
    _write_json_atomic(paths["manifest"], manifest)
    completion = [
        f"期間: {args.start:%Y-%m-%d} から {args.end:%Y-%m-%d} 未満",
        f"foot count2 events: {event_processed}",
        f"grid paths: {path_processed}",
        f"censored: {sum(state.censored_count for state in entry_states.values())}",
        f"skipped: {sum(skipped.values())}",
        f"経過: {elapsed_minutes:.1f}分",
        f"manifest: {paths['manifest']}",
    ]
    print(f"{args.pair} count2 time-decay analysis complete")
    for line in completion:
        print(f"- {line}")
    _notify(
        "\n".join(
            [
                f"{args.pair} count2 time-decay analysis 完了",
                *(f"- {line}" for line in completion),
            ]
        )
    )
    return {**paths, "progress": archived_progress}


def main(
    argv: list[str] | None = None,
    *,
    default_pair: str = DEFAULT_PAIR_NAME,
    default_start: dt.datetime = DEFAULT_START,
    default_end: dt.datetime = DEFAULT_END,
) -> dict[str, Path]:
    args = parse_args(
        argv,
        default_pair=default_pair,
        default_start=default_start,
        default_end=default_end,
    )
    try:
        return run_analysis(args)
    except Exception as error:
        generation_started = bool(getattr(args, "_generation_started", False))
        if generation_started and args.grid_paths is not None:
            paths = output_paths(args)
            for path in paths.values():
                for residual in (
                    path,
                    path.with_suffix(path.suffix + ".tmp"),
                    path.with_suffix(path.suffix + ".part"),
                ):
                    if residual.exists():
                        _archive_file(residual)
        cleanup_line = (
            "- current generation progress/temp/output: archiveへ移動済み"
            if generation_started
            else "- 入力検査中の失敗: 既存の完了出力は保持"
        )
        _notify(
            "\n".join(
                [
                    f"{args.pair} count2 time-decay analysis 異常終了",
                    f"- エラー種別: {type(error).__name__}",
                    f"- 内容: {error}",
                    cleanup_line,
                ]
            )
        )
        raise


if __name__ == "__main__":
    main()
