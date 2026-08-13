"""Future-safe count-2 entry/TP/LC grid search for supported pairs.

This module consumes the causal candidate CSV created by
``count2_resistance_sweep.py``, its foot2 event ledger, and the matching S5
cache.  It never rebuilds decision features from future candles and never
contacts OANDA.  S5 candles after each decision are used only to label
counterfactual order outcomes.

The output is normalized to avoid copying hundreds of condition columns into
every TP x LC combination:

* ``grid_paths`` stores one row per event, entry-line rank and entry offset,
  including the first reach of every TP and LC threshold.
* ``grid_aggregate`` stores condition x complete grid summaries.
* ``grid_monthly`` stores every condition x grid combination by month.

The condition catalog includes the causal A-normalized foot-count-2 shape
(REJECTION / ENGULFING / STALL / CONTINUATION), retrace/pushback strength and
candidate-line wick/body overshoot fields.

Policy/TOP15-derived fields are deliberately excluded from condition search.
Full-period outcomes use a common completed path cohort for every TP x LC
width; marketable and boundary-incomplete opportunities remain
visible in the denominators instead of selectively disappearing.

Every entry is counterfactual.  The three entry ranks are alternatives, not
three orders that may be executed simultaneously.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import math
import os
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

import fGeneric as gene
import test_win_point_usd_aud as win_point
import tokens as tk
from count2_resistance_sweep import (
    LimitPathInspector,
    S5_SECONDS,
    data_coverage_errors,
    s5_cache_has_no_tick_completion,
)


DEFAULT_PAIR_NAME = "USD_JPY"
GRID_VERSION = "count2_entry_tp_lc_grid_v8_fc2_shape"
S5_TYPED_CACHE_VERSION = "s5_ohlc_memmap_v1"
DEFAULT_START = dt.datetime(2025, 7, 30)
DEFAULT_END = dt.datetime(2026, 7, 30)
DEFAULT_ENTRY_RANKS = (1, 2, 3)
DEFAULT_ENTRY_OFFSET_RANGE_MULTIPLIERS = (-0.25, 0.0, 0.25)
DEFAULT_TP_RANGE_MULTIPLIERS = (1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0)
DEFAULT_LC_RANGE_MULTIPLIERS = (0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 4.0)
DEFAULT_SPREAD_PIPS = 0.8
DEFAULT_HORIZON_MINUTES = 60
DEFAULT_RISK_YEN = 50.0
DEFAULT_MIN_TARGET_PIPS = 1.6
DEFAULT_MIN_COMPLETED = 100
DEFAULT_MIN_RR = 1.2
DEFAULT_MIN_PROFIT_FACTOR = 1.10
DEFAULT_MIN_OUTCOME_COVERAGE = 0.95
DEFAULT_READ_CHUNK_SIZE = 1000
TIME_FORMAT = "%Y/%m/%d %H:%M:%S"
COMPLETED_RESULTS = {"tp", "lc", "both_same_s5_lc_assumed", "timeout"}
S5_RECORD_DTYPE = np.dtype(
    [
        ("time", "datetime64[ns]"),
        ("open", "<f8"),
        ("close", "<f8"),
        ("high", "<f8"),
        ("low", "<f8"),
    ]
)


def _number_list(
    value: str | Iterable[float | int],
    *,
    name: str,
    positive: bool = False,
    integer: bool = False,
) -> tuple[float | int, ...]:
    """Parse a deterministic, duplicate-free numeric CLI list."""
    raw_values = value.split(",") if isinstance(value, str) else list(value)
    parsed: list[float | int] = []
    for raw in raw_values:
        text = str(raw).strip()
        if not text:
            raise ValueError(f"{name} contains an empty value")
        try:
            number = int(text) if integer else float(text)
        except ValueError as error:
            raise ValueError(f"{name} contains a non-numeric value: {text}") from error
        if not math.isfinite(float(number)):
            raise ValueError(f"{name} must contain only finite values")
        if positive and float(number) <= 0:
            raise ValueError(f"{name} must contain only positive values")
        if number not in parsed:
            parsed.append(number)
    if not parsed:
        raise ValueError(f"{name} must not be empty")
    return tuple(parsed)


def _csv_value(values: Iterable[float | int]) -> str:
    return ",".join(f"{float(value):g}" for value in values)


def _pair_name(args: argparse.Namespace) -> str:
    return str(getattr(args, "pair", DEFAULT_PAIR_NAME))


def _grid_version(args: argparse.Namespace) -> str:
    return f"{_pair_name(args).lower()}_{GRID_VERSION}"


def _default_candidate_path(
    pair_name: str,
    start: dt.datetime,
    end: dt.datetime,
    spread_pips: float,
) -> Path:
    stem = (
        f"{pair_name}_{start:%Y%m%d}_{end:%Y%m%d}"
        f"_m5line60_range6x3_rr1.2_sp{spread_pips:g}_60m"
    )
    return Path(tk.folder_path) / f"resistance_sweep_candidates_{stem}.csv"


def _default_event_path(
    pair_name: str,
    start: dt.datetime,
    end: dt.datetime,
    spread_pips: float,
) -> Path:
    stem = (
        f"{pair_name}_{start:%Y%m%d}_{end:%Y%m%d}"
        f"_m5line60_range6x3_rr1.2_sp{spread_pips:g}_60m"
    )
    return Path(tk.folder_path) / f"resistance_sweep_events_{stem}.csv"


def _default_s5_path(
    pair_name: str,
    start: dt.datetime,
    end: dt.datetime,
) -> Path:
    name = f"{pair_name}_{start:%Y%m%d%H%M%S}_{end:%Y%m%d%H%M%S}"
    return Path(tk.folder_path) / f"s5_{name}.csv"


def parse_args(
    argv: list[str] | None = None,
    *,
    default_start: dt.datetime = DEFAULT_START,
    default_end: dt.datetime = DEFAULT_END,
    default_pair: str = DEFAULT_PAIR_NAME,
) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Foot count 2: entry line / TP / LC exhaustive grid "
            "using an existing causal resistance-sweep CSV"
        )
    )
    parser.add_argument(
        "--pair",
        default=default_pair,
        choices=tuple(gene.CURRENCY_PAIRS),
    )
    parser.add_argument("--start", default=default_start.isoformat(" "))
    parser.add_argument("--end", default=default_end.isoformat(" "))
    parser.add_argument("--source-candidates", type=Path, default=None)
    parser.add_argument("--source-events", type=Path, default=None)
    parser.add_argument("--s5-cache", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=Path(tk.folder_path))
    parser.add_argument(
        "--entry-ranks",
        default=_csv_value(DEFAULT_ENTRY_RANKS),
        help="Raw distance-ranked M5 lines. No TOP15/live gate is applied.",
    )
    parser.add_argument(
        "--entry-offset-range-multipliers",
        default=_csv_value(DEFAULT_ENTRY_OFFSET_RANGE_MULTIPLIERS),
        help=(
            "Offset from the line as a multiple of the preceding-six-M5 "
            "average range. Positive is farther in the count2 direction."
        ),
    )
    parser.add_argument(
        "--tp-range-multipliers",
        default=_csv_value(DEFAULT_TP_RANGE_MULTIPLIERS),
    )
    parser.add_argument(
        "--lc-range-multipliers",
        default=_csv_value(DEFAULT_LC_RANGE_MULTIPLIERS),
    )
    parser.add_argument("--spread-pips", type=float, default=DEFAULT_SPREAD_PIPS)
    parser.add_argument(
        "--horizon-minutes", type=int, default=DEFAULT_HORIZON_MINUTES
    )
    parser.add_argument(
        "--min-target-pips", type=float, default=DEFAULT_MIN_TARGET_PIPS
    )
    parser.add_argument("--risk-yen", type=float, default=DEFAULT_RISK_YEN)
    parser.add_argument(
        "--min-completed", type=int, default=DEFAULT_MIN_COMPLETED
    )
    parser.add_argument("--min-rr", type=float, default=DEFAULT_MIN_RR)
    parser.add_argument(
        "--min-profit-factor",
        type=float,
        default=DEFAULT_MIN_PROFIT_FACTOR,
    )
    parser.add_argument(
        "--min-outcome-coverage",
        type=float,
        default=DEFAULT_MIN_OUTCOME_COVERAGE,
    )
    parser.add_argument(
        "--read-chunk-size", type=int, default=DEFAULT_READ_CHUNK_SIZE
    )
    parser.add_argument(
        "--max-source-rows",
        type=int,
        default=None,
        help="Development-only row limit; omitted for a complete run.",
    )
    args = parser.parse_args(argv)
    args.start = pd.Timestamp(args.start).to_pydatetime()
    args.end = pd.Timestamp(args.end).to_pydatetime()
    if args.start >= args.end:
        parser.error("--start must be earlier than --end")
    try:
        args.entry_ranks = tuple(
            int(value)
            for value in _number_list(
                args.entry_ranks,
                name="--entry-ranks",
                positive=True,
                integer=True,
            )
        )
        args.entry_offset_range_multipliers = tuple(
            float(value)
            for value in _number_list(
                args.entry_offset_range_multipliers,
                name="--entry-offset-range-multipliers",
            )
        )
        args.tp_range_multipliers = tuple(
            float(value)
            for value in _number_list(
                args.tp_range_multipliers,
                name="--tp-range-multipliers",
                positive=True,
            )
        )
        args.lc_range_multipliers = tuple(
            float(value)
            for value in _number_list(
                args.lc_range_multipliers,
                name="--lc-range-multipliers",
                positive=True,
            )
        )
    except ValueError as error:
        parser.error(str(error))
    unsupported_ranks = sorted(
        set(args.entry_ranks).difference(DEFAULT_ENTRY_RANKS)
    )
    if unsupported_ranks:
        parser.error(
            "--entry-ranks is limited to raw distance ranks 1,2,3; "
            f"unsupported={unsupported_ranks}"
        )
    positive_fields = (
        "horizon_minutes",
        "min_target_pips",
        "risk_yen",
        "min_completed",
        "min_rr",
        "min_profit_factor",
        "read_chunk_size",
    )
    for field in positive_fields:
        if float(getattr(args, field)) <= 0:
            parser.error(f"--{field.replace('_', '-')} must be positive")
    if args.spread_pips < 0:
        parser.error("--spread-pips must be non-negative")
    if not 0 < args.min_outcome_coverage <= 1:
        parser.error("--min-outcome-coverage must be in (0, 1]")
    args.min_target_pips = max(
        float(args.min_target_pips),
        float(args.spread_pips) * 2.0,
    )
    if args.max_source_rows is not None and args.max_source_rows < 1:
        parser.error("--max-source-rows must be positive")
    args.source_candidates = args.source_candidates or _default_candidate_path(
        args.pair, args.start, args.end, args.spread_pips
    )
    args.source_events = args.source_events or _default_event_path(
        args.pair, args.start, args.end, args.spread_pips
    )
    args.s5_cache = args.s5_cache or _default_s5_path(
        args.pair, args.start, args.end
    )
    return args


def _grid_config(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "version": _grid_version(args),
        "pair": _pair_name(args),
        "start": args.start.isoformat(" "),
        "end": args.end.isoformat(" "),
        "entry_rank_source": "raw_distance_rank",
        "entry_ranks": list(args.entry_ranks),
        "entry_offset_range_multipliers": list(
            args.entry_offset_range_multipliers
        ),
        "tp_range_multipliers": list(args.tp_range_multipliers),
        "lc_range_multipliers": list(args.lc_range_multipliers),
        "spread_pips": args.spread_pips,
        "horizon_minutes": args.horizon_minutes,
        "min_target_pips": args.min_target_pips,
        "risk_yen": args.risk_yen,
        "yen_result_method": (
            "rounded_units_at_entry"
            if _pair_name(args) == "USD_JPY"
            else "fixed_risk_yen_times_result_r"
        ),
        "min_completed": args.min_completed,
        "min_rr": args.min_rr,
        "min_profit_factor": args.min_profit_factor,
        "min_outcome_coverage": args.min_outcome_coverage,
        "source_candidates": str(args.source_candidates),
        "source_events": str(args.source_events),
        "s5_cache": str(args.s5_cache),
        "max_source_rows": args.max_source_rows,
        "counterfactual_entries": True,
        "top15_pre_filter_applied": False,
        "policy_derived_conditions_in_search": False,
        "causal_stair_failed_condition_signatures_in_search": True,
        "target_width_floor_pips": args.min_target_pips,
        "target_price_normalization": "rounded_order_price_then_effective_pips",
        "s5_typed_cache_version": S5_TYPED_CACHE_VERSION,
    }


def output_paths(args: argparse.Namespace) -> dict[str, Path]:
    config_json = json.dumps(_grid_config(args), sort_keys=True, ensure_ascii=True)
    fingerprint = hashlib.sha256(config_json.encode("ascii")).hexdigest()[:10]
    stem = (
        f"{_pair_name(args)}_{args.start:%Y%m%d}_{args.end:%Y%m%d}"
        f"_g{fingerprint}"
    )
    folder = Path(args.output_dir)
    return {
        "paths": folder / f"count2_target_grid_paths_{stem}.csv",
        "aggregate": folder / f"count2_target_grid_aggregate_{stem}.csv",
        "monthly": folder / f"count2_target_grid_monthly_{stem}.csv",
        "manifest": folder / f"count2_target_grid_manifest_{stem}.json",
        "progress": folder / f"count2_target_grid_progress_{stem}.json",
    }


def _archive_file(path: Path) -> Path:
    if not path.exists():
        return path
    archive = path.parent / "archive"
    archive.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    destination = archive / f"{path.stem}_{stamp}{path.suffix}"
    number = 1
    while destination.exists():
        destination = archive / f"{path.stem}_{stamp}_{number}{path.suffix}"
        number += 1
    path.replace(destination)
    return destination


def _archive_generation(paths: dict[str, Path]) -> list[Path]:
    """Move every file from one prior output generation out of the live set."""
    archived: list[Path] = []
    seen: set[Path] = set()
    for path in paths.values():
        for candidate in (
            path,
            path.with_suffix(path.suffix + ".part"),
            path.with_suffix(path.suffix + ".tmp"),
        ):
            if candidate in seen:
                continue
            seen.add(candidate)
            if candidate.exists():
                archived.append(_archive_file(candidate))
    return archived


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    temporary.replace(path)


class PartCsvWriter:
    """Stream a CSV through a recoverable .part file."""

    def __init__(self, path: Path, fieldnames: list[str]):
        self.path = path
        self.part_path = path.with_suffix(path.suffix + ".part")
        self.fieldnames = fieldnames
        self.handle = None
        self.writer = None
        path.parent.mkdir(parents=True, exist_ok=True)
        if self.part_path.exists():
            _archive_file(self.part_path)
        self.handle = self.part_path.open("w", newline="", encoding="utf-8-sig")
        self.writer = csv.DictWriter(
            self.handle,
            fieldnames=fieldnames,
            extrasaction="ignore",
        )
        self.writer.writeheader()

    def writerow(self, row: dict[str, Any]) -> None:
        if self.writer is None:
            raise RuntimeError("CSV writer is closed")
        self.writer.writerow(row)

    def finalize(self) -> Path:
        if self.handle is not None:
            self.handle.flush()
            self.handle.close()
            self.handle = None
            self.writer = None
        if self.path.exists():
            _archive_file(self.path)
        self.part_path.replace(self.path)
        return self.path

    def abort(self) -> Path:
        if self.handle is not None:
            self.handle.flush()
            self.handle.close()
            self.handle = None
            self.writer = None
        return _archive_file(self.part_path)


def _count_csv_rows(path: Path) -> int:
    line_count = 0
    last_byte = b""
    with path.open("rb") as handle:
        while block := handle.read(8 * 1024 * 1024):
            line_count += block.count(b"\n")
            last_byte = block[-1:]
    if last_byte and last_byte != b"\n":
        line_count += 1
    return max(line_count - 1, 0)


def _typed_s5_paths(source: Path) -> tuple[Path, Path, Path]:
    stem = source.with_suffix(source.suffix + f".{S5_TYPED_CACHE_VERSION}")
    binary = stem.with_suffix(stem.suffix + ".bin")
    metadata = stem.with_suffix(stem.suffix + ".json")
    partial = binary.with_suffix(binary.suffix + ".part")
    return binary, metadata, partial


def _source_stat(path: Path) -> dict[str, int]:
    stat = path.stat()
    return {"size": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns)}


def _typed_s5_metadata_is_current(
    source: Path,
    binary: Path,
    metadata: Path,
) -> tuple[bool, dict[str, Any] | None]:
    if not binary.exists() or not metadata.exists():
        return False, None
    try:
        payload = json.loads(metadata.read_text(encoding="utf-8"))
        row_count = int(payload["row_count"])
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return False, None
    current = (
        payload.get("version") == S5_TYPED_CACHE_VERSION
        and payload.get("source") == str(source.resolve())
        and payload.get("source_stat") == _source_stat(source)
        and row_count > 0
        and binary.stat().st_size == row_count * S5_RECORD_DTYPE.itemsize
    )
    return bool(current), payload if current else None


def _archive_typed_s5_cache(source: Path) -> None:
    binary, metadata, partial = _typed_s5_paths(source)
    for path in (binary, metadata, partial, metadata.with_suffix(metadata.suffix + ".tmp")):
        if path.exists():
            _archive_file(path)


def _archive_typed_s5_residuals(source: Path) -> None:
    _binary, metadata, partial = _typed_s5_paths(source)
    for path in (partial, metadata.with_suffix(metadata.suffix + ".tmp")):
        if path.exists():
            _archive_file(path)


def _build_typed_s5_cache(
    source: Path,
    pair: gene.CurrencyPair,
    *,
    chunksize: int = 500_000,
) -> tuple[Path, dict[str, Any]]:
    """Convert the 1GB-class CSV to an append-only typed memmap sidecar."""
    binary, metadata, partial = _typed_s5_paths(source)
    _archive_typed_s5_cache(source)
    before = _source_stat(source)
    row_count = 0
    first_time: pd.Timestamp | None = None
    last_time: pd.Timestamp | None = None
    minimum_price = math.inf
    maximum_price = -math.inf
    try:
        with partial.open("wb") as handle:
            chunks = pd.read_csv(
                source,
                usecols=lambda column: column
                in {"time_jp", "open", "close", "high", "low"},
                dtype={
                    "time_jp": "string",
                    "open": "float64",
                    "close": "float64",
                    "high": "float64",
                    "low": "float64",
                },
                chunksize=chunksize,
            )
            for chunk in chunks:
                required = {"time_jp", "open", "close", "high", "low"}
                missing = required.difference(chunk.columns)
                if missing:
                    raise ValueError(
                        "S5 cache is missing required columns: "
                        + ", ".join(sorted(missing))
                    )
                times = pd.to_datetime(
                    chunk["time_jp"],
                    format=TIME_FORMAT,
                    errors="raise",
                ).to_numpy(dtype="datetime64[ns]", copy=False)
                if not len(times):
                    continue
                if np.any(np.diff(times) <= np.timedelta64(0, "ns")):
                    raise ValueError("S5 cache must be strictly time-ascending")
                current_first = pd.Timestamp(times[0])
                current_last = pd.Timestamp(times[-1])
                if last_time is not None and current_first <= last_time:
                    raise ValueError("S5 cache has duplicate or out-of-order chunks")
                values = {
                    column: pd.to_numeric(chunk[column], errors="coerce").to_numpy(
                        dtype=float,
                        copy=False,
                    )
                    for column in ("open", "close", "high", "low")
                }
                if not all(np.isfinite(value).all() for value in values.values()):
                    raise ValueError("S5 cache contains non-finite OHLC values")
                if (
                    (values["high"] < values["low"]).any()
                    or (values["high"] < values["open"]).any()
                    or (values["high"] < values["close"]).any()
                    or (values["low"] > values["open"]).any()
                    or (values["low"] > values["close"]).any()
                ):
                    raise ValueError("S5 cache contains invalid OHLC ordering")
                records = np.empty(len(chunk), dtype=S5_RECORD_DTYPE)
                records["time"] = times
                for column, value in values.items():
                    records[column] = value
                records.tofile(handle)
                row_count += len(records)
                if first_time is None:
                    first_time = current_first
                last_time = current_last
                minimum_price = min(minimum_price, float(values["low"].min()))
                maximum_price = max(maximum_price, float(values["high"].max()))
        if row_count <= 0 or first_time is None or last_time is None:
            raise ValueError("S5 cache is empty")
        after = _source_stat(source)
        if after != before:
            raise RuntimeError("S5 source changed while typed cache was built")
        if not pair.is_price(minimum_price) or not pair.is_price(maximum_price):
            raise ValueError(
                f"S5 price range does not look like {pair.name}: "
                f"{minimum_price}..{maximum_price}"
            )
        partial.replace(binary)
        payload = {
            "version": S5_TYPED_CACHE_VERSION,
            "source": str(source.resolve()),
            "source_stat": before,
            "row_count": row_count,
            "record_itemsize": S5_RECORD_DTYPE.itemsize,
            "first_time": first_time.isoformat(" "),
            "last_time": last_time.isoformat(" "),
            "minimum_price": minimum_price,
            "maximum_price": maximum_price,
            "created_at": dt.datetime.now().astimezone().isoformat(
                timespec="seconds"
            ),
        }
        _write_json_atomic(metadata, payload)
        return binary, payload
    except Exception:
        _archive_typed_s5_cache(source)
        raise


def _load_typed_s5_inspector(
    source: Path,
    pair: gene.CurrencyPair,
) -> tuple[LimitPathInspector, dict[str, Any]]:
    _archive_typed_s5_residuals(source)
    binary, metadata, _partial = _typed_s5_paths(source)
    current, payload = _typed_s5_metadata_is_current(source, binary, metadata)
    if not current or payload is None:
        binary, payload = _build_typed_s5_cache(source, pair)
    records = np.memmap(
        binary,
        dtype=S5_RECORD_DTYPE,
        mode="r",
        shape=(int(payload["row_count"]),),
    )
    inspector = object.__new__(LimitPathInspector)
    inspector.pair = pair
    inspector.times = records["time"]
    inspector.opens = records["open"]
    inspector.closes = records["close"]
    inspector.highs = records["high"]
    inspector.lows = records["low"]
    inspector._typed_s5_memmap = records
    return inspector, payload


def _s5_coverage_errors(
    times: np.ndarray,
    args: argparse.Namespace,
) -> list[str]:
    # Reuse the same OANDA-market edge rules as the source sweep.  The empty
    # M5 frame is deliberate; only the returned S5 diagnostics are relevant.
    s5_times = pd.DataFrame(
        {"time_jp_dt": pd.Series(times, copy=False)}
    )
    errors = data_coverage_errors(
        pd.DataFrame(),
        s5_times,
        args.start,
        args.end,
        0,
    )
    return list(errors.get("S5", []))


def _bound_inspector_before(
    inspector: LimitPathInspector,
    end_exclusive: pd.Timestamp,
) -> LimitPathInspector:
    """Prevent even diagnostic path inspection from reading past period end."""
    end_index = int(
        np.searchsorted(
            inspector.times,
            np.datetime64(pd.Timestamp(end_exclusive), "ns"),
            side="left",
        )
    )
    inspector.times = inspector.times[:end_index]
    inspector.opens = inspector.opens[:end_index]
    inspector.closes = inspector.closes[:end_index]
    inspector.highs = inspector.highs[:end_index]
    inspector.lows = inspector.lows[:end_index]
    return inspector


def _is_complete_market_window(
    times: np.ndarray,
    expected_start: pd.Timestamp,
    expected_end_exclusive: pd.Timestamp,
) -> bool:
    """Require every tradable S5 while allowing only known closed-market edges."""
    expected_start = pd.Timestamp(expected_start)
    expected_end_exclusive = pd.Timestamp(expected_end_exclusive)
    if expected_end_exclusive <= expected_start:
        return False
    step = pd.Timedelta(seconds=S5_SECONDS)
    if not len(times):
        return LimitPathInspector._is_expected_market_closed_gap(
            expected_start - step,
            expected_end_exclusive,
        )

    first_time = pd.Timestamp(times[0])
    last_time = pd.Timestamp(times[-1])
    if first_time < expected_start or last_time >= expected_end_exclusive:
        return False
    if not LimitPathInspector._is_contiguous(
        times,
        first_time,
        last_time + step,
    ):
        return False
    if first_time > expected_start and not (
        LimitPathInspector._is_expected_market_closed_gap(
            expected_start - step,
            first_time,
        )
    ):
        return False
    actual_end = last_time + step
    if actual_end < expected_end_exclusive and not (
        LimitPathInspector._is_expected_market_closed_gap(
            last_time,
            expected_end_exclusive,
        )
    ):
        return False
    return actual_end <= expected_end_exclusive


def inspect_common_entry_window(
    inspector: LimitPathInspector,
    *,
    decision_time: pd.Timestamp,
    expiry_time: pd.Timestamp,
    horizon_minutes: int,
) -> tuple[pd.Timestamp, bool]:
    """Check an outcome-independent window shared by every entry alternative."""
    decision_time = pd.Timestamp(decision_time)
    expiry_time = pd.Timestamp(expiry_time)
    common_end = expiry_time + pd.Timedelta(minutes=horizon_minutes)
    start_index = int(
        np.searchsorted(
            inspector.times,
            np.datetime64(decision_time, "ns"),
            side="left",
        )
    )
    end_index = int(
        np.searchsorted(
            inspector.times,
            np.datetime64(common_end, "ns"),
            side="left",
        )
    )
    times = inspector.times[start_index:end_index]
    complete = _is_complete_market_window(
        times,
        decision_time,
        common_end,
    )
    return common_end, bool(complete)


def _notify(message: str) -> None:
    win_point.send_inspection_notice(message)


def _write_progress(
    path: Path,
    *,
    args: argparse.Namespace,
    status: str,
    phase: str,
    started_at: dt.datetime,
    process_started: float,
    source_rows_total: int | None = None,
    source_rows_processed: int = 0,
    selected_line_rows: int = 0,
    grid_path_rows: int = 0,
    error: str | None = None,
) -> None:
    elapsed = max(time.monotonic() - process_started, 0.0)
    percent = (
        100.0 * source_rows_processed / source_rows_total
        if source_rows_total
        else None
    )
    remaining = (
        elapsed * (source_rows_total - source_rows_processed) / source_rows_processed
        if source_rows_total and source_rows_processed > 0
        else None
    )
    payload = {
        "pair": _pair_name(args),
        "pid": os.getpid(),
        "status": status,
        "phase": phase,
        "grid_version": _grid_version(args),
        "started_at": started_at.astimezone().isoformat(timespec="seconds"),
        "updated_at": dt.datetime.now().astimezone().isoformat(
            timespec="seconds"
        ),
        "source_rows_processed": source_rows_processed,
        "source_rows_total": source_rows_total,
        "progress_percent": round(percent, 3) if percent is not None else None,
        "entry_candidate_line_rows": selected_line_rows,
        "grid_path_rows": grid_path_rows,
        "entry_rank_count": len(args.entry_ranks),
        "entry_offset_count": len(args.entry_offset_range_multipliers),
        "tp_candidate_count": len(args.tp_range_multipliers),
        "lc_candidate_count": len(args.lc_range_multipliers),
        "combination_count": (
            len(args.entry_ranks)
            * len(args.entry_offset_range_multipliers)
            * len(args.tp_range_multipliers)
            * len(args.lc_range_multipliers)
        ),
        "elapsed_minutes": round(elapsed / 60.0, 2),
        "estimated_remaining_minutes": (
            round(remaining / 60.0, 2) if remaining is not None else None
        ),
        "error": error,
    }
    _write_json_atomic(path, payload)


@dataclass(frozen=True)
class Condition:
    condition_id: str
    source: str
    field: str
    value: str
    label: str


def _condition(
    source: str,
    field: str,
    value: Any,
    label: str | None = None,
) -> Condition | None:
    if value is None:
        return None
    try:
        if bool(pd.isna(value)):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, (float, np.floating)) and math.isnan(float(value)):
        return None
    if isinstance(value, (bool, np.bool_)):
        value_text = "true" if bool(value) else "false"
    elif isinstance(value, (int, np.integer)):
        value_text = str(int(value))
    elif isinstance(value, (float, np.floating)) and float(value).is_integer():
        value_text = str(int(value))
    else:
        value_text = str(value).strip()
    if not value_text or value_text.lower() in {"nan", "none", "nat"}:
        return None
    condition_id = f"{source}::{field}::{value_text}"
    return Condition(
        condition_id=condition_id,
        source=source,
        field=field,
        value=value_text,
        label=label or f"{field}={value_text}",
    )


def _bool_value(value: Any) -> bool | None:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, float, np.integer, np.floating)):
        number = float(value)
        if number == 1.0:
            return True
        if number == 0.0:
            return False
    text = str(value).strip().lower()
    if text in {"true", "1", "1.0", "yes"}:
        return True
    if text in {"false", "0", "0.0", "no"}:
        return False
    return None


def _numeric(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _bin_label(value: Any, edges: list[float], labels: list[str]) -> str | None:
    number = _numeric(value)
    if number is None:
        return None
    position = int(np.searchsorted(np.asarray(edges, dtype=float), number, side="right")) - 1
    if position < 0 or position >= len(labels):
        return None
    return labels[position]


RATIO_EDGES = [-np.inf, 0.25, 0.40, 0.55, 0.65, 0.80, 1.0, np.inf]
RATIO_LABELS = [
    "<0.25",
    "0.25-0.39",
    "0.40-0.54",
    "0.55-0.64",
    "0.65-0.79",
    "0.80-0.99",
    "1.00+",
]
DOMINANCE_EDGES = [-np.inf, 1.0, 1.25, 1.5, 2.0, 3.0, np.inf]
DOMINANCE_LABELS = [
    "<1.00",
    "1.00-1.24",
    "1.25-1.49",
    "1.50-1.99",
    "2.00-2.99",
    "3.00+",
]
PROGRESS_EDGES = [-np.inf, 0.0, 0.5, 1.0, 2.0, 3.0, 5.0, np.inf]
PROGRESS_LABELS = [
    "<0",
    "0-0.49",
    "0.50-0.99",
    "1.00-1.99",
    "2.00-2.99",
    "3.00-4.99",
    "5.00+",
]
PACE_EDGES = [-np.inf, 1.0, 2.0, 3.0, 4.0, 5.0, 8.0, np.inf]
PACE_LABELS = ["<1", "1-1.99", "2-2.99", "3-3.99", "4-4.99", "5-7.99", "8+"]
DISTANCE_EDGES = [-np.inf, 3, 5, 8, 12, 20, 30, 50, np.inf]
DISTANCE_LABELS = ["<3", "3-4", "5-7", "8-11", "12-19", "20-29", "30-49", "50+"]
RSI_EDGES = [-np.inf, 35, 45, 55, 65, np.inf]
RSI_LABELS = ["<35", "35-44", "45-54", "55-64", "65+"]
FC2_A_EDGES = [-np.inf, 0.0, 0.10, 0.25, 0.50, 0.75, 1.0, 1.5, 2.0, np.inf]
FC2_A_LABELS = [
    "<0",
    "0-0.09",
    "0.10-0.24",
    "0.25-0.49",
    "0.50-0.74",
    "0.75-0.99",
    "1.00-1.49",
    "1.50-1.99",
    "2.00+",
]


def condition_memberships(row: dict[str, Any]) -> list[Condition]:
    """Return single-factor decision-time conditions without outcome fields."""
    conditions: dict[str, Condition] = {}

    def add(
        source: str,
        field: str,
        value: Any,
        label: str | None = None,
    ) -> None:
        item = _condition(source, field, value, label)
        if item is not None:
            conditions[item.condition_id] = item

    add("ALL", "all", "all", "全条件")
    add("FOOT", "foot_count", row.get("peak_count"), "foot count")
    add("LINE", "peaks_count", row.get("line_count"), "peaks count")
    add("LINE", "core_peak", row.get("line_core_count"), "core peak")
    add("OTHER", "trade_side", row.get("trade_side"))
    add(
        "OTHER",
        "distance_pips_bin",
        _bin_label(row.get("distance_pips"), DISTANCE_EDGES, DISTANCE_LABELS),
    )
    add("OTHER", "prior_retouch_exists", _bool_value(row.get("prior_retouch_exists")))
    add("OTHER", "prior_retouch_count", row.get("prior_retouch_count"))
    add("LINE", "is_flipped", _bool_value(row.get("line_is_flipped")))
    add("LINE", "flip_count", row.get("line_flip_count"))
    add("LINE", "origin_role", row.get("line_origin_role"))
    add("LINE", "current_role", row.get("line_current_role"))
    # ``shape`` is the requested resistance-aware classification.  The
    # candidate-independent candle classification remains separately visible.
    add("FC2", "candle_shape", row.get("fc2_shape"))
    add("FC2", "shape", row.get("fc2_line_shape"))
    for field in ("engulfing", "rejection", "stall", "continuation"):
        add(
            "FC2",
            "candle_" + field,
            _bool_value(row.get("fc2_" + field)),
        )
    for field in (
        "approach_impulse_A",
        "reversal_strength_A",
        "second_close_pushback_A",
        "second_wick_A",
        "mean_body_A",
        "pattern_range_A",
        "directional_progress_A",
        "line_wick_overshoot_A",
        "line_body_break_A",
    ):
        add(
            "FC2",
            field + "_bin",
            _bin_label(row.get("fc2_" + field), FC2_A_EDGES, FC2_A_LABELS),
        )
    add(
        "FC2",
        "prior_impulse_retrace_ratio_bin",
        _bin_label(
            row.get("fc2_prior_impulse_retrace_ratio"),
            RATIO_EDGES,
            RATIO_LABELS,
        ),
    )
    for field in (
        "line_crossed_by_wick",
        "line_crossed_by_body",
        "line_rejection",
    ):
        add("FC2", field, _bool_value(row.get("fc2_" + field)))
    for rsi_name in ("rsi_1", "rsi_2", "rsi_3"):
        add(
            "OTHER",
            rsi_name + "_bin",
            _bin_label(row.get(rsi_name), RSI_EDGES, RSI_LABELS),
        )

    decision_time = pd.to_datetime(row.get("decision_time"), errors="coerce")
    if not pd.isna(decision_time):
        hour = int(decision_time.hour)
        if 7 <= hour < 15:
            session = "TOKYO"
        elif 15 <= hour < 21:
            session = "LONDON"
        elif hour >= 21 or hour < 2:
            session = "NEW_YORK"
        else:
            session = "OFF_HOURS"
        add("OTHER", "session", session)

    for prefix, source in (("m5_stair_", "M5"), ("h1_stair_", "H1")):
        for field in (
            "state",
            "direction",
            "observed_direction",
            "confirmed",
            "candidate_passed",
            "confirmed_passed",
            "detected",
            "would_block_predict_reversal",
            "candidate_failed_conditions",
            "confirmed_failed_conditions",
        ):
            value = row.get(prefix + field)
            if field in {
                "confirmed",
                "candidate_passed",
                "confirmed_passed",
                "detected",
                "would_block_predict_reversal",
            }:
                value = _bool_value(value)
            add(source, field, value)

        for ordinal in ("first", "second", "third"):
            add(
                source,
                f"{ordinal}_impulse_foot_count",
                row.get(prefix + f"{ordinal}_impulse_foot_count"),
            )
        for ordinal in ("first", "second"):
            add(
                source,
                f"{ordinal}_pullback_foot_count",
                row.get(prefix + f"{ordinal}_pullback_foot_count"),
            )
            for suffix in ("pullback_ratio", "pullback_foot_ratio"):
                add(
                    source,
                    f"{ordinal}_{suffix}_bin",
                    _bin_label(
                        row.get(prefix + f"{ordinal}_{suffix}"),
                        RATIO_EDGES,
                        RATIO_LABELS,
                    ),
                )
        add(
            source,
            "dominance_ratio_bin",
            _bin_label(
                row.get(prefix + "dominance_ratio"),
                DOMINANCE_EDGES,
                DOMINANCE_LABELS,
            ),
        )
        for field in (
            "first_impulse_pips_per_foot",
            "first_pullback_pips_per_foot",
            "second_impulse_pips_per_foot",
            "second_pullback_pips_per_foot",
            "third_impulse_pips_per_foot",
            "net_progress_pips",
        ):
            add(
                source,
                field + "_bin",
                _bin_label(row.get(prefix + field), PACE_EDGES, PACE_LABELS),
            )
        for field in (
            "first_impulse_required_ratio",
            "second_impulse_required_ratio",
            "third_impulse_required_ratio",
        ):
            add(
                source,
                field + "_bin",
                _bin_label(
                    row.get(prefix + field),
                    DOMINANCE_EDGES,
                    DOMINANCE_LABELS,
                ),
            )
        for field in (
            "second_impulse_break_pips",
            "third_impulse_break_pips",
            "first_structure_progress_pips",
            "second_structure_progress_pips",
        ):
            add(
                source,
                field + "_bin",
                _bin_label(
                    row.get(prefix + field),
                    PROGRESS_EDGES,
                    PROGRESS_LABELS,
                ),
            )
        for column, value in row.items():
            criterion_prefix = prefix + "criterion_"
            if column.startswith(criterion_prefix):
                add(source, column.removeprefix(prefix), _bool_value(value))

    m5_state = row.get("m5_stair_state")
    h1_state = row.get("h1_stair_state")
    if (
        m5_state is not None
        and h1_state is not None
        and not pd.isna(m5_state)
        and not pd.isna(h1_state)
    ):
        add("M5_X_H1", "state", f"{m5_state}|{h1_state}")
    m5_block = _bool_value(row.get("m5_stair_would_block_predict_reversal"))
    h1_block = _bool_value(row.get("h1_stair_would_block_predict_reversal"))
    if m5_block is not None and h1_block is not None:
        add("M5_X_H1", "would_block", f"M5={m5_block}|H1={h1_block}")

    return list(conditions.values())


def _first_invalid_gap_index(times: np.ndarray) -> int:
    """Return the first row after an unknown gap, or len(times)."""
    if len(times) <= 1:
        return len(times)
    gaps = np.diff(times)
    for index in np.flatnonzero(gaps != np.timedelta64(S5_SECONDS, "s")):
        previous = pd.Timestamp(times[int(index)])
        following = pd.Timestamp(times[int(index) + 1])
        if LimitPathInspector._is_expected_market_closed_gap(previous, following):
            continue
        return int(index) + 1
    return len(times)


def _threshold_first_indices(touches: np.ndarray) -> np.ndarray:
    if touches.ndim != 2:
        raise ValueError("touch matrix must be two-dimensional")
    reached = touches.any(axis=1)
    first = np.argmax(touches, axis=1).astype(int)
    first[~reached] = -1
    return first


def _times_at_indices(times: np.ndarray, indices: np.ndarray) -> np.ndarray:
    result = np.full(len(indices), np.datetime64("NaT", "ns"), dtype="datetime64[ns]")
    valid = indices >= 0
    if valid.any():
        result[valid] = times[indices[valid]]
    return result


def _empty_threshold_path(
    status: str,
    *,
    tp_count: int,
    lc_count: int,
) -> dict[str, Any]:
    empty_tp_index = np.full(tp_count, -1, dtype=int)
    empty_lc_index = np.full(lc_count, -1, dtype=int)
    empty_times = np.array([], dtype="datetime64[ns]")
    return {
        "path_status": status,
        "pending_path_complete": False,
        "filled": False,
        "fill_time": pd.NaT,
        "fill_delay_seconds": np.nan,
        "fill_at_bar_open": False,
        "horizon_end": pd.NaT,
        "horizon_complete": False,
        "timeout_exit_time": pd.NaT,
        "timeout_result_pips": np.nan,
        "pending_s5_rows": 0,
        "position_s5_rows": 0,
        "first_invalid_position_index": 0,
        "full_path_mfe_pips": np.nan,
        "full_path_mae_pips": np.nan,
        "tp_first_index": empty_tp_index.copy(),
        "tp_first_time": _times_at_indices(empty_times, empty_tp_index),
        "tp_raw_first_index": empty_tp_index.copy(),
        "tp_raw_first_time": _times_at_indices(empty_times, empty_tp_index),
        "tp_raw_reached": np.zeros(tp_count, dtype=bool),
        "tp_reached": np.zeros(tp_count, dtype=bool),
        "tp_touch_on_fill_bar": np.zeros(tp_count, dtype=bool),
        "tp_fill_confirmed": np.zeros(tp_count, dtype=bool),
        "lc_first_index": empty_lc_index.copy(),
        "lc_first_time": _times_at_indices(empty_times, empty_lc_index),
        "lc_raw_first_index": empty_lc_index.copy(),
        "lc_raw_first_time": _times_at_indices(empty_times, empty_lc_index),
        "lc_raw_reached": np.zeros(lc_count, dtype=bool),
        "lc_reached": np.zeros(lc_count, dtype=bool),
        "lc_touch_on_fill_bar": np.zeros(lc_count, dtype=bool),
    }


def inspect_entry_thresholds(
    inspector: LimitPathInspector,
    *,
    decision_time: pd.Timestamp,
    expiry_time: pd.Timestamp,
    direction: int,
    entry_price: float,
    tp_pips: np.ndarray,
    lc_pips: np.ndarray,
    horizon_minutes: int,
    spread_pips: float,
) -> dict[str, Any]:
    """Inspect one LIMIT entry once and retain every threshold first reach."""
    decision_time = pd.Timestamp(decision_time)
    expiry_time = pd.Timestamp(expiry_time)
    tp_pips = np.asarray(tp_pips, dtype=float)
    lc_pips = np.asarray(lc_pips, dtype=float)
    if expiry_time <= decision_time:
        raise ValueError("expiry_time must be after decision_time")
    if direction not in (-1, 1):
        raise ValueError("direction must be -1 or 1")
    if not np.isfinite(tp_pips).all() or (tp_pips <= 0).any():
        raise ValueError("TP thresholds must be finite and positive")
    if not np.isfinite(lc_pips).all() or (lc_pips <= 0).any():
        raise ValueError("LC thresholds must be finite and positive")
    tp_pips = executable_target_pips(
        tp_pips,
        minimum_pips=0.0,
        pair=inspector.pair,
    )
    lc_pips = executable_target_pips(
        lc_pips,
        minimum_pips=0.0,
        pair=inspector.pair,
    )

    def base(status: str) -> dict[str, Any]:
        return _empty_threshold_path(
            status,
            tp_count=len(tp_pips),
            lc_count=len(lc_pips),
        )

    start_i = int(
        np.searchsorted(
            inspector.times,
            np.datetime64(decision_time, "ns"),
            side="left",
        )
    )
    expiry_i = int(
        np.searchsorted(
            inspector.times,
            np.datetime64(expiry_time, "ns"),
            side="left",
        )
    )
    pending_times = inspector.times[start_i:expiry_i]
    if not len(pending_times):
        pending_complete = _is_complete_market_window(
            pending_times,
            decision_time,
            expiry_time,
        )
        result = base("not_filled" if pending_complete else "incomplete_pending")
        result["pending_path_complete"] = pending_complete
        return result
    half_spread = inspector.pair.pips_to_price(spread_pips / 2)
    if direction == 1:
        fill_touch = np.isfinite(inspector.lows[start_i:expiry_i]) & (
            inspector.lows[start_i:expiry_i] <= entry_price - half_spread
        )
    else:
        fill_touch = np.isfinite(inspector.highs[start_i:expiry_i]) & (
            inspector.highs[start_i:expiry_i] >= entry_price + half_spread
        )
    reached = np.flatnonzero(fill_touch)
    if not reached.size:
        result = base("not_filled")
        result["pending_s5_rows"] = len(pending_times)
        result["pending_path_complete"] = _is_complete_market_window(
            pending_times,
            decision_time,
            expiry_time,
        )
        if not result["pending_path_complete"]:
            result["path_status"] = "incomplete_pending"
        return result

    fill_offset = int(reached[0])
    fill_i = start_i + fill_offset
    fill_time = pd.Timestamp(inspector.times[fill_i])
    pending_complete = _is_complete_market_window(
        pending_times[: fill_offset + 1],
        decision_time,
        fill_time + pd.Timedelta(seconds=S5_SECONDS),
    )
    if not pending_complete:
        result = base("incomplete_pending")
        result["pending_s5_rows"] = fill_offset + 1
        return result

    open_mid = float(inspector.opens[fill_i])
    fill_at_open = (
        open_mid + half_spread <= entry_price
        if direction == 1
        else open_mid - half_spread >= entry_price
    )
    horizon_end = fill_time + pd.Timedelta(minutes=horizon_minutes)
    end_i = int(
        np.searchsorted(
            inspector.times,
            np.datetime64(horizon_end, "ns"),
            side="left",
        )
    )
    path_times = inspector.times[fill_i:end_i]
    if not len(path_times):
        result = base("incomplete_horizon")
        result.update(
            {
                "pending_path_complete": True,
                "filled": True,
                "fill_time": fill_time,
                "fill_delay_seconds": float(
                    (fill_time - decision_time).total_seconds()
                ),
                "fill_at_bar_open": bool(fill_at_open),
                "horizon_end": horizon_end,
                "pending_s5_rows": fill_offset + 1,
            }
        )
        return result

    high = inspector.highs[fill_i:end_i]
    low = inspector.lows[fill_i:end_i]
    close = inspector.closes[fill_i:end_i]
    tp_prices = entry_price + direction * np.asarray(
        [inspector.pair.pips_to_price(value) for value in tp_pips],
        dtype=float,
    )
    lc_prices = entry_price - direction * np.asarray(
        [inspector.pair.pips_to_price(value) for value in lc_pips],
        dtype=float,
    )
    if direction == 1:
        favorable_quote = high - half_spread
        adverse_quote = low - half_spread
        close_quote = close - half_spread
        favorable_pips = (favorable_quote - entry_price) / inspector.pair.pip_value
        adverse_pips = (adverse_quote - entry_price) / inspector.pair.pip_value
        tp_touch = favorable_quote[None, :] >= tp_prices[:, None]
        lc_touch = adverse_quote[None, :] <= lc_prices[:, None]
        tp_fill_confirmed = np.full(len(tp_pips), bool(fill_at_open)) | (
            float(close_quote[0]) >= tp_prices
        )
        timeout_result_pips = float(
            (float(close_quote[-1]) - entry_price) / inspector.pair.pip_value
        )
    else:
        favorable_quote = low + half_spread
        adverse_quote = high + half_spread
        close_quote = close + half_spread
        favorable_pips = (entry_price - favorable_quote) / inspector.pair.pip_value
        adverse_pips = (entry_price - adverse_quote) / inspector.pair.pip_value
        tp_touch = favorable_quote[None, :] <= tp_prices[:, None]
        lc_touch = adverse_quote[None, :] >= lc_prices[:, None]
        tp_fill_confirmed = np.full(len(tp_pips), bool(fill_at_open)) | (
            float(close_quote[0]) <= tp_prices
        )
        timeout_result_pips = float(
            (entry_price - float(close_quote[-1])) / inspector.pair.pip_value
        )

    raw_tp_touch = tp_touch.copy()
    raw_lc_touch = lc_touch.copy()
    tp_touch_on_fill = raw_tp_touch[:, 0].copy()
    lc_touch_on_fill = lc_touch[:, 0].copy()
    tp_touch[:, 0] &= tp_fill_confirmed
    tp_raw_first = _threshold_first_indices(raw_tp_touch)
    lc_raw_first = _threshold_first_indices(raw_lc_touch)
    tp_first = _threshold_first_indices(tp_touch)
    lc_first = _threshold_first_indices(lc_touch)
    first_invalid = _first_invalid_gap_index(path_times)
    tp_raw_reached = tp_raw_first >= 0
    lc_raw_reached = lc_raw_first >= 0
    tp_reached = (tp_first >= 0) & (tp_first < first_invalid)
    lc_reached = (lc_first >= 0) & (lc_first < first_invalid)
    horizon_complete = bool(
        first_invalid == len(path_times)
        and _is_complete_market_window(path_times, fill_time, horizon_end)
    )
    metric_favorable = favorable_pips.copy()
    if not fill_at_open:
        close_progress = float(
            direction
            * (float(close_quote[0]) - entry_price)
            / inspector.pair.pip_value
        )
        metric_favorable[0] = max(0.0, close_progress)

    return {
        "path_status": "filled",
        "pending_path_complete": True,
        "filled": True,
        "fill_time": fill_time,
        "fill_delay_seconds": float((fill_time - decision_time).total_seconds()),
        "fill_at_bar_open": bool(fill_at_open),
        "horizon_end": horizon_end,
        "horizon_complete": horizon_complete,
        "timeout_exit_time": pd.Timestamp(path_times[-1]),
        "timeout_result_pips": timeout_result_pips,
        "pending_s5_rows": fill_offset + 1,
        "position_s5_rows": len(path_times),
        "first_invalid_position_index": first_invalid,
        "full_path_mfe_pips": float(np.nanmax(metric_favorable)),
        "full_path_mae_pips": float(np.nanmin(adverse_pips)),
        "tp_first_index": tp_first,
        "tp_first_time": _times_at_indices(path_times, tp_first),
        "tp_raw_first_index": tp_raw_first,
        "tp_raw_first_time": _times_at_indices(path_times, tp_raw_first),
        "tp_raw_reached": tp_raw_reached,
        "tp_reached": tp_reached,
        "tp_touch_on_fill_bar": tp_touch_on_fill,
        "tp_fill_confirmed": tp_fill_confirmed,
        "lc_first_index": lc_first,
        "lc_first_time": _times_at_indices(path_times, lc_first),
        "lc_raw_first_index": lc_raw_first,
        "lc_raw_first_time": _times_at_indices(path_times, lc_raw_first),
        "lc_raw_reached": lc_raw_reached,
        "lc_reached": lc_reached,
        "lc_touch_on_fill_bar": lc_touch_on_fill,
    }


def _multiplier_tag(value: float) -> str:
    text = f"{abs(float(value)):g}".replace(".", "p")
    return ("m" if value < 0 else "p") + text


@dataclass(frozen=True)
class GridCombo:
    combo_index: int
    combo_id: str
    entry_rank: int
    offset_index: int
    offset_range_multiplier: float
    tp_index: int
    tp_range_multiplier: float
    lc_index: int
    lc_range_multiplier: float
    configured_rr: float


def build_grid_combos(args: argparse.Namespace) -> tuple[list[GridCombo], dict[tuple[int, int], np.ndarray]]:
    combos: list[GridCombo] = []
    prefix_indices: dict[tuple[int, int], np.ndarray] = {}
    for entry_rank in args.entry_ranks:
        for offset_index, offset_multiplier in enumerate(
            args.entry_offset_range_multipliers
        ):
            local: list[int] = []
            for tp_index, tp_multiplier in enumerate(args.tp_range_multipliers):
                for lc_index, lc_multiplier in enumerate(
                    args.lc_range_multipliers
                ):
                    combo_index = len(combos)
                    combo_id = (
                        f"rank{entry_rank}"
                        f"_off{_multiplier_tag(offset_multiplier)}A"
                        f"_tp{_multiplier_tag(tp_multiplier)}A"
                        f"_lc{_multiplier_tag(lc_multiplier)}A"
                    )
                    combos.append(
                        GridCombo(
                            combo_index=combo_index,
                            combo_id=combo_id,
                            entry_rank=entry_rank,
                            offset_index=offset_index,
                            offset_range_multiplier=offset_multiplier,
                            tp_index=tp_index,
                            tp_range_multiplier=tp_multiplier,
                            lc_index=lc_index,
                            lc_range_multiplier=lc_multiplier,
                            configured_rr=tp_multiplier / lc_multiplier,
                        )
                    )
                    local.append(combo_index)
            prefix_indices[(entry_rank, offset_index)] = np.asarray(local, dtype=int)
    return combos, prefix_indices


def adjusted_entry_parameters(
    *,
    line_price: float,
    decision_price: float,
    peak_direction: int,
    average_range_pips: float,
    offset_range_multiplier: float,
    pair: gene.CurrencyPair,
    spread_pips: float = 0.0,
) -> dict[str, Any]:
    """Build one symmetric offset and reject a marketable LIMIT price."""
    if peak_direction not in (-1, 1):
        raise ValueError("peak_direction must be -1 or 1")
    if not math.isfinite(average_range_pips) or average_range_pips <= 0:
        raise ValueError("average_range_pips must be finite and positive")
    if not math.isfinite(spread_pips) or spread_pips < 0:
        raise ValueError("spread_pips must be finite and non-negative")
    requested_offset_pips = average_range_pips * offset_range_multiplier
    entry_price = pair.round_price(
        float(line_price)
        + peak_direction * pair.pips_to_price(requested_offset_pips)
    )
    actual_offset_pips = (
        (entry_price - float(line_price)) * peak_direction / pair.pip_value
    )
    adjusted_distance_pips = (
        (entry_price - float(decision_price))
        * peak_direction
        / pair.pip_value
    )
    return {
        "entry_price": entry_price,
        "requested_entry_offset_pips": requested_offset_pips,
        "entry_offset_pips": actual_offset_pips,
        "adjusted_distance_pips": adjusted_distance_pips,
        # decision_price is the mid.  SELL LIMIT triggers on bid and BUY LIMIT
        # on ask, hence a small negative mid-distance can still be pending.
        "marketable_limit": adjusted_distance_pips <= -(spread_pips / 2.0),
    }


def executable_target_pips(
    requested: np.ndarray,
    *,
    minimum_pips: float,
    pair: gene.CurrencyPair,
) -> np.ndarray:
    """Apply the strategy floor and normalize to an executable price tick."""
    requested = np.asarray(requested, dtype=float)
    if not np.isfinite(requested).all() or (requested <= 0).any():
        raise ValueError("requested target widths must be finite and positive")
    floored = np.maximum(requested, float(minimum_pips))
    effective = np.asarray(
        [abs(pair.pips_to_price(value)) / pair.pip_value for value in floored],
        dtype=float,
    )
    if not np.isfinite(effective).all() or (effective <= 0).any():
        raise ValueError("effective target widths must be finite and positive")
    return effective


@dataclass
class GridRecord:
    event_id: str
    decision_time: pd.Timestamp
    expiry_time: pd.Timestamp
    entry_rank: int
    offset_index: int
    offset_range_multiplier: float
    offset_pips: float
    average_range_pips: float
    tp_pips: np.ndarray
    lc_pips: np.ndarray
    path: dict[str, Any]
    conditions: list[Condition]
    entry_eligible: bool = True
    common_path_end: pd.Timestamp | None = None
    common_path_complete: bool | None = None


METRIC_NAMES = (
    "signal_count",
    "eligible_count",
    "marketable_count",
    "known_count",
    "unresolved_count",
    "filled_count",
    "not_filled_count",
    "completed_count",
    "tp_count",
    "lc_count",
    "timeout_count",
    "positive_count",
    "same_s5_lc_count",
    "fill_bar_tp_ambiguous_count",
    "sum_pips",
    "sum_r",
    "sum_yen",
    "gross_profit_r",
    "gross_loss_r_abs",
    "positive_pips_sum",
    "positive_pips_count",
    "negative_pips_sum",
    "negative_pips_count",
    "tp_pips_sum",
    "lc_pips_sum",
    "effective_rr_sum",
    "entry_offset_pips_sum",
)
OPPORTUNITY_METRIC_NAMES = {
    "signal_count",
    "eligible_count",
    "marketable_count",
}
MONTHLY_METRIC_NAMES = (
    "signal_count",
    "eligible_count",
    "marketable_count",
    "known_count",
    "filled_count",
    "not_filled_count",
    "completed_count",
    "tp_count",
    "lc_count",
    "timeout_count",
    "positive_count",
    "sum_pips",
    "sum_r",
    "sum_yen",
    "positive_pips_sum",
)


def _new_metric_state(combo_count: int) -> dict[str, np.ndarray]:
    return {
        name: np.zeros(combo_count, dtype=float)
        for name in METRIC_NAMES
    }


def _new_monthly_state(combo_count: int) -> dict[str, np.ndarray]:
    return {
        name: np.zeros(combo_count, dtype=float)
        for name in MONTHLY_METRIC_NAMES
    }


def _outcome_matrices(
    records: list[GridRecord],
    args: argparse.Namespace,
    pair: gene.CurrencyPair,
) -> tuple[
    dict[str, np.ndarray],
    dict[str, np.ndarray],
    dict[str, np.ndarray],
]:
    """Build vectorized TP x LC metrics for records sharing rank and offset."""
    row_count = len(records)
    tp_count = len(args.tp_range_multipliers)
    lc_count = len(args.lc_range_multipliers)
    local_combo_count = tp_count * lc_count
    shapes = (row_count, local_combo_count)
    metrics = {name: np.zeros(shapes, dtype=float) for name in METRIC_NAMES}
    segment_masks = {"full": np.zeros(shapes, dtype=bool)}
    cohort_masks = {"full": np.zeros(shapes, dtype=bool)}
    start = pd.Timestamp(args.start)
    end = pd.Timestamp(args.end)

    for row_index, record in enumerate(records):
        path = record.path
        actual_tp = np.repeat(record.tp_pips, lc_count)
        actual_lc = np.tile(record.lc_pips, tp_count)
        valid_width = (
            np.isfinite(actual_tp)
            & np.isfinite(actual_lc)
            & (actual_tp > 0)
            & (actual_lc > 0)
        )
        metrics["signal_count"][row_index] = valid_width.astype(float)
        metrics["eligible_count"][row_index] = (
            valid_width & record.entry_eligible
        ).astype(float)
        metrics["marketable_count"][row_index] = (
            valid_width & (not record.entry_eligible)
        ).astype(float)
        if not valid_width.any():
            continue

        result = np.full(local_combo_count, "incomplete", dtype=object)
        result_pips = np.zeros(local_combo_count, dtype=float)
        same_s5 = np.zeros(local_combo_count, dtype=bool)
        fill_ambiguous = np.zeros(local_combo_count, dtype=bool)

        if (
            record.entry_eligible
            and path["path_status"] == "not_filled"
            and path["pending_path_complete"]
        ):
            result[valid_width] = "not_filled"
        elif record.entry_eligible and path["filled"]:
            tp_index = np.repeat(np.asarray(path["tp_first_index"], dtype=int), lc_count)
            lc_index = np.tile(np.asarray(path["lc_first_index"], dtype=int), tp_count)
            tp_valid = np.repeat(np.asarray(path["tp_reached"], dtype=bool), lc_count)
            lc_valid = np.tile(np.asarray(path["lc_reached"], dtype=bool), tp_count)
            sentinel = np.iinfo(np.int32).max
            tp_order = np.where(tp_valid, tp_index, sentinel)
            lc_order = np.where(lc_valid, lc_index, sentinel)
            any_hit = (tp_order < sentinel) | (lc_order < sentinel)
            lc_first = any_hit & (lc_order <= tp_order)
            tp_first = any_hit & ~lc_first
            tp_fill_touch = np.repeat(
                np.asarray(path["tp_touch_on_fill_bar"], dtype=bool),
                lc_count,
            )
            tp_fill_confirmed = np.repeat(
                np.asarray(path["tp_fill_confirmed"], dtype=bool),
                lc_count,
            )
            lc_fill_touch = np.tile(
                np.asarray(path["lc_touch_on_fill_bar"], dtype=bool),
                tp_count,
            )
            same_s5 = lc_first & lc_valid & (
                (tp_valid & (tp_index == lc_index))
                | ((lc_index == 0) & tp_fill_touch)
            )
            result[tp_first & valid_width] = "tp"
            result[lc_first & valid_width] = np.where(
                same_s5[lc_first & valid_width],
                "both_same_s5_lc_assumed",
                "lc",
            )
            result_pips[tp_first & valid_width] = actual_tp[tp_first & valid_width]
            result_pips[lc_first & valid_width] = -actual_lc[lc_first & valid_width]

            no_hit = valid_width & ~any_hit
            if path["horizon_complete"]:
                result[no_hit] = "timeout"
                result_pips[no_hit] = float(path["timeout_result_pips"])

            fill_ambiguous = (
                tp_fill_touch & ~lc_fill_touch & ~tp_fill_confirmed
            )

        known = valid_width & np.isin(
            result,
            ["not_filled", "tp", "lc", "both_same_s5_lc_assumed", "timeout"],
        )
        if (
            record.entry_eligible
            and record.common_path_complete is True
            and not bool(known[valid_width].all())
        ):
            raise RuntimeError(
                f"Common entry window is complete but outcome is unresolved: "
                f"{record.event_id}, rank={record.entry_rank}, "
                f"offset={record.offset_index}"
            )
        completed = valid_width & np.isin(result, list(COMPLETED_RESULTS))
        tp_hit = valid_width & (result == "tp")
        lc_hit = valid_width & np.isin(result, ["lc", "both_same_s5_lc_assumed"])
        timeout = valid_width & (result == "timeout")
        not_filled = valid_width & (result == "not_filled")
        positive = completed & (result_pips > 0)
        negative = completed & (result_pips < 0)
        result_r = np.divide(
            result_pips,
            actual_lc,
            out=np.zeros_like(result_pips),
            where=actual_lc > 0,
        )
        if pair.name == "USD_JPY":
            # Preserve the established USD/JPY result contract, including
            # order-unit rounding. USD-quoted pairs cannot use this formula
            # without a causal USD/JPY conversion series.
            units_by_lc = np.asarray(
                [
                    gene.calculate_units(
                        pair,
                        pair.pips_to_price(value),
                        risk_yen=args.risk_yen,
                        rounding_tag="l",
                    )
                    for value in record.lc_pips
                ],
                dtype=float,
            )
            units = np.tile(units_by_lc, tp_count)
            result_yen = result_pips * pair.pip_value * units
        else:
            # EUR/USD and AUD/USD use fixed-risk-normalized yen. A -1R stop is
            # exactly -risk_yen and every other outcome scales by its realized
            # R multiple. This avoids importing a future or constant FX rate.
            result_yen = result_r * float(args.risk_yen)

        metrics["known_count"][row_index] = known.astype(float)
        metrics["unresolved_count"][row_index] = (
            valid_width & ~known
        ).astype(float)
        metrics["filled_count"][row_index] = (
            valid_width & record.entry_eligible & bool(path["filled"])
        ).astype(float)
        metrics["not_filled_count"][row_index] = not_filled.astype(float)
        metrics["completed_count"][row_index] = completed.astype(float)
        metrics["tp_count"][row_index] = tp_hit.astype(float)
        metrics["lc_count"][row_index] = lc_hit.astype(float)
        metrics["timeout_count"][row_index] = timeout.astype(float)
        metrics["positive_count"][row_index] = positive.astype(float)
        metrics["same_s5_lc_count"][row_index] = (same_s5 & completed).astype(float)
        metrics["fill_bar_tp_ambiguous_count"][row_index] = (
            fill_ambiguous & completed
        ).astype(float)
        metrics["sum_pips"][row_index] = np.where(completed, result_pips, 0.0)
        metrics["sum_r"][row_index] = np.where(completed, result_r, 0.0)
        metrics["sum_yen"][row_index] = np.where(completed, result_yen, 0.0)
        metrics["gross_profit_r"][row_index] = np.where(
            completed & (result_r > 0), result_r, 0.0
        )
        metrics["gross_loss_r_abs"][row_index] = np.where(
            completed & (result_r < 0), -result_r, 0.0
        )
        metrics["positive_pips_sum"][row_index] = np.where(
            positive, result_pips, 0.0
        )
        metrics["positive_pips_count"][row_index] = positive.astype(float)
        metrics["negative_pips_sum"][row_index] = np.where(
            negative, result_pips, 0.0
        )
        metrics["negative_pips_count"][row_index] = negative.astype(float)
        metrics["tp_pips_sum"][row_index] = np.where(known, actual_tp, 0.0)
        metrics["lc_pips_sum"][row_index] = np.where(known, actual_lc, 0.0)
        metrics["effective_rr_sum"][row_index] = np.where(
            known,
            np.divide(
                actual_tp,
                actual_lc,
                out=np.zeros_like(actual_tp),
                where=actual_lc > 0,
            ),
            0.0,
        )
        metrics["entry_offset_pips_sum"][row_index] = np.where(
            known, record.offset_pips, 0.0
        )

        def common_complete(cutoff: pd.Timestamp) -> bool:
            if not record.entry_eligible:
                return False
            if record.common_path_complete is not None:
                return bool(
                    record.common_path_complete
                    and record.common_path_end is not None
                    and pd.Timestamp(record.common_path_end) <= cutoff
                )
            # Synthetic/unit callers created before the explicit common-entry
            # window may omit it; retain the path-local fallback for them.
            if path["path_status"] == "not_filled":
                return bool(
                    path["pending_path_complete"]
                    and record.expiry_time <= cutoff
                )
            if path["filled"]:
                return bool(
                    path["horizon_complete"]
                    and pd.Timestamp(path["horizon_end"]) <= cutoff
                )
            return False

        decision_time = pd.Timestamp(record.decision_time)
        period_membership = {"full": start <= decision_time < end}
        cutoffs = {"full": end}
        for segment, in_period in period_membership.items():
            opportunity = valid_width & bool(in_period)
            segment_masks[segment][row_index] = opportunity
            cohort_masks[segment][row_index] = (
                opportunity & common_complete(cutoffs[segment])
            )

    return metrics, segment_masks, cohort_masks


class GridAccumulator:
    def __init__(
        self,
        args: argparse.Namespace,
        pair: gene.CurrencyPair,
        combos: list[GridCombo],
        prefix_indices: dict[tuple[int, int], np.ndarray],
    ):
        self.args = args
        self.pair = pair
        self.combos = combos
        self.combo_count = len(combos)
        self.prefix_indices = prefix_indices
        self.states: dict[tuple[str, str], dict[str, np.ndarray]] = {}
        self.monthly_states: dict[
            tuple[str, str, str], dict[str, np.ndarray]
        ] = {}
        self.catalog: dict[str, Condition] = {}
        self.foot2_event_counts: dict[tuple[str, str], int] = {}

    def _state(self, segment: str, condition_id: str) -> dict[str, np.ndarray]:
        key = (segment, condition_id)
        if key not in self.states:
            self.states[key] = _new_metric_state(self.combo_count)
        return self.states[key]

    def _monthly_state(
        self,
        segment: str,
        month: str,
        condition_id: str,
    ) -> dict[str, np.ndarray]:
        key = (segment, month, condition_id)
        if key not in self.monthly_states:
            self.monthly_states[key] = _new_monthly_state(self.combo_count)
        return self.monthly_states[key]

    def add_records(self, records: list[GridRecord]) -> None:
        grouped: dict[tuple[int, int], list[GridRecord]] = defaultdict(list)
        for record in records:
            grouped[(record.entry_rank, record.offset_index)].append(record)
            for condition in record.conditions:
                self.catalog[condition.condition_id] = condition

        for prefix, prefix_records in grouped.items():
            local_indices = self.prefix_indices[prefix]
            metrics, segment_masks, cohort_masks = _outcome_matrices(
                prefix_records,
                self.args,
                self.pair,
            )
            metric_cube = np.stack(
                [metrics[name] for name in METRIC_NAMES],
                axis=2,
            )
            monthly_metric_positions = [
                METRIC_NAMES.index(name) for name in MONTHLY_METRIC_NAMES
            ]
            membership_rows: dict[str, list[int]] = defaultdict(list)
            for row_index, record in enumerate(prefix_records):
                for condition in record.conditions:
                    membership_rows[condition.condition_id].append(row_index)

            for condition_id, raw_indices in membership_rows.items():
                row_indices = np.asarray(raw_indices, dtype=int)
                months = np.asarray(
                    [prefix_records[index].decision_time.strftime("%Y-%m") for index in row_indices],
                    dtype=object,
                )
                for segment, segment_mask in segment_masks.items():
                    selected_segment = segment_mask[row_indices]
                    if not selected_segment.any():
                        continue
                    selected_cohort = cohort_masks[segment][row_indices]
                    state = self._state(segment, condition_id)
                    cohort_totals = (
                        metric_cube[row_indices]
                        * selected_cohort[:, :, None]
                    ).sum(axis=0)
                    opportunity_totals = (
                        metric_cube[row_indices]
                        * selected_segment[:, :, None]
                    ).sum(axis=0)
                    for metric_position, metric_name in enumerate(METRIC_NAMES):
                        totals = (
                            opportunity_totals
                            if metric_name in OPPORTUNITY_METRIC_NAMES
                            else cohort_totals
                        )
                        state[metric_name][local_indices] += totals[
                            :, metric_position
                        ]

                    for month in np.unique(months):
                        month_rows = row_indices[months == month]
                        month_segment_mask = segment_masks[segment][month_rows]
                        if not month_segment_mask.any():
                            continue
                        month_cohort_mask = cohort_masks[segment][month_rows]
                        monthly = self._monthly_state(segment, str(month), condition_id)
                        month_cohort_totals = (
                            metric_cube[month_rows]
                            * month_cohort_mask[:, :, None]
                        ).sum(axis=0)
                        month_opportunity_totals = (
                            metric_cube[month_rows]
                            * month_segment_mask[:, :, None]
                        ).sum(axis=0)
                        for metric_name, metric_position in zip(
                            MONTHLY_METRIC_NAMES,
                            monthly_metric_positions,
                        ):
                            totals = (
                                month_opportunity_totals
                                if metric_name in OPPORTUNITY_METRIC_NAMES
                                else month_cohort_totals
                            )
                            monthly[metric_name][local_indices] += totals[
                                :, metric_position
                            ]

    def monthly_summary(
        self,
    ) -> dict[tuple[str, str], dict[str, np.ndarray]]:
        summary: dict[tuple[str, str], dict[str, np.ndarray]] = {}
        for (segment, _month, condition_id), metrics in self.monthly_states.items():
            key = (segment, condition_id)
            if key not in summary:
                summary[key] = {
                    "active_month_count": np.zeros(self.combo_count),
                    "positive_month_count": np.zeros(self.combo_count),
                    "negative_month_count": np.zeros(self.combo_count),
                    "worst_month_r": np.full(self.combo_count, np.nan),
                }
            target = summary[key]
            active = metrics["completed_count"] > 0
            positive = active & (metrics["sum_r"] > 0)
            negative = active & (metrics["sum_r"] < 0)
            target["active_month_count"] += active.astype(float)
            target["positive_month_count"] += positive.astype(float)
            target["negative_month_count"] += negative.astype(float)
            current = target["worst_month_r"]
            values = np.where(active, metrics["sum_r"], np.nan)
            target["worst_month_r"] = np.where(
                np.isnan(current),
                values,
                np.where(np.isnan(values), current, np.minimum(current, values)),
            )
        return summary


FC2_EVENT_COLUMNS = {
    "fc2_version",
    "fc2_valid",
    "fc2_reason",
    "fc2_shape",
    "fc2_direction",
    "fc2_source_first_time",
    "fc2_source_last_time",
    "fc2_prior_source_time",
    "fc2_a_range_pips",
    "fc2_approach_impulse_A",
    "fc2_reversal_strength_A",
    "fc2_prior_impulse_retrace_ratio",
    "fc2_second_close_pushback_A",
    "fc2_second_wick_A",
    "fc2_mean_body_A",
    "fc2_pattern_range_A",
    "fc2_directional_progress_A",
    "fc2_engulfing",
    "fc2_rejection",
    "fc2_stall",
    "fc2_continuation",
}

FC2_LINE_COLUMNS = {
    "fc2_line_shape",
    "fc2_line_wick_overshoot_pips",
    "fc2_line_wick_overshoot_A",
    "fc2_line_body_break_pips",
    "fc2_line_body_break_A",
    "fc2_line_crossed_by_wick",
    "fc2_line_crossed_by_body",
    "fc2_line_rejection",
}

SOURCE_REQUIRED_COLUMNS = {
    "event_id",
    "pair",
    "decision_time",
    "next_count2_time",
    "tp_lookback",
    "tp_multiplier",
    "tp_pips",
    "target_valid",
    "target_source_first_time",
    "target_source_last_time",
    "recent_m5_avg_range_pips",
    "peak_count",
    "peak_direction",
    "decision_price",
    "candidate_rank",
    "line_price",
    "distance_pips",
    "trade_direction",
    "trade_side",
    "line_count",
    "line_core_count",
    "line_newest_source_time",
    "line_timeframe",
    "line_history_bars",
    "candidate_scope",
    "candidate_pruning_applied",
    "pending_expiry_exclusive",
    "peak_latest_time",
    "m5_stair_profile_enabled",
    "m5_stair_state",
    "h1_stair_profile_enabled",
    "h1_stair_state",
} | FC2_EVENT_COLUMNS | FC2_LINE_COLUMNS

SOURCE_BASIC_CONDITION_COLUMNS = {
    "rsi_1",
    "rsi_2",
    "rsi_3",
    "prior_retouch_exists",
    "prior_retouch_count",
    "prior_retouch_last_time",
    "line_is_flipped",
    "line_flip_count",
    "line_origin_role",
    "line_current_role",
}

EVENT_REQUIRED_COLUMNS = {
    "event_id",
    "pair",
    "decision_time",
    "next_count2_time",
    "tp_lookback",
    "tp_multiplier",
    "tp_pips",
    "target_valid",
    "target_source_first_time",
    "target_source_last_time",
    "recent_m5_avg_range_pips",
    "peak_count",
    "peak_direction",
    "peak_latest_time",
    "decision_price",
    "rsi_1",
    "rsi_2",
    "rsi_3",
    "m5_stair_profile_enabled",
    "m5_stair_state",
    "h1_stair_profile_enabled",
    "h1_stair_state",
    "event_status",
    "candidate_count",
} | FC2_EVENT_COLUMNS

EVENT_SIGNATURE_FIELDS = {
    "decision_time",
    "next_count2_time",
    "tp_lookback",
    "tp_multiplier",
    "tp_pips",
    "target_valid",
    "target_source_first_time",
    "target_source_last_time",
    "recent_m5_avg_range_pips",
    "peak_count",
    "peak_direction",
    "peak_latest_time",
    "decision_price",
    "rsi_1",
    "rsi_2",
    "rsi_3",
    "m5_stair_profile_enabled",
    "h1_stair_profile_enabled",
} | FC2_EVENT_COLUMNS

STAIR_CONDITION_SUFFIXES = {
    "state",
    "direction",
    "observed_direction",
    "confirmed",
    "candidate_passed",
    "confirmed_passed",
    "detected",
    "would_block_predict_reversal",
    "candidate_failed_conditions",
    "confirmed_failed_conditions",
    "first_impulse_foot_count",
    "second_impulse_foot_count",
    "third_impulse_foot_count",
    "first_pullback_foot_count",
    "second_pullback_foot_count",
    "first_pullback_ratio",
    "first_pullback_foot_ratio",
    "second_pullback_ratio",
    "second_pullback_foot_ratio",
    "dominance_ratio",
    "first_impulse_pips_per_foot",
    "first_pullback_pips_per_foot",
    "second_impulse_pips_per_foot",
    "second_pullback_pips_per_foot",
    "third_impulse_pips_per_foot",
    "net_progress_pips",
    "first_impulse_required_ratio",
    "second_impulse_required_ratio",
    "third_impulse_required_ratio",
    "second_impulse_break_pips",
    "third_impulse_break_pips",
    "first_structure_progress_pips",
    "second_structure_progress_pips",
}

STAIR_NUMERIC_SUFFIXES = {
    "first_impulse_foot_count",
    "second_impulse_foot_count",
    "third_impulse_foot_count",
    "first_pullback_foot_count",
    "second_pullback_foot_count",
    "first_pullback_ratio",
    "first_pullback_foot_ratio",
    "second_pullback_ratio",
    "second_pullback_foot_ratio",
    "dominance_ratio",
    "first_impulse_pips_per_foot",
    "first_pullback_pips_per_foot",
    "second_impulse_pips_per_foot",
    "second_pullback_pips_per_foot",
    "third_impulse_pips_per_foot",
    "net_progress_pips",
    "first_impulse_required_ratio",
    "second_impulse_required_ratio",
    "third_impulse_required_ratio",
    "second_impulse_break_pips",
    "third_impulse_break_pips",
    "first_structure_progress_pips",
    "second_structure_progress_pips",
}


def _is_stair_condition_column(column: str) -> bool:
    for prefix in ("m5_stair_", "h1_stair_"):
        if not column.startswith(prefix):
            continue
        suffix = column.removeprefix(prefix)
        return suffix in STAIR_CONDITION_SUFFIXES or suffix.startswith(
            "criterion_"
        )
    return False


def _signature_scalar(field: str, value: Any) -> Any:
    if value is None or bool(pd.isna(value)):
        return None
    if field in {
        "decision_time",
        "next_count2_time",
        "target_source_first_time",
        "target_source_last_time",
        "peak_latest_time",
        "fc2_source_first_time",
        "fc2_source_last_time",
        "fc2_prior_source_time",
    }:
        return _timestamp_text(value)
    stair_suffix = field.removeprefix("m5_stair_").removeprefix("h1_stair_")
    boolean_field = field in {
        "target_valid",
        "m5_stair_profile_enabled",
        "h1_stair_profile_enabled",
        "fc2_valid",
        "fc2_engulfing",
        "fc2_rejection",
        "fc2_stall",
        "fc2_continuation",
    } or (
        _is_stair_condition_column(field)
        and (
            stair_suffix
            in {
                "confirmed",
                "candidate_passed",
                "confirmed_passed",
                "detected",
                "would_block_predict_reversal",
            }
            or stair_suffix.startswith("criterion_")
        )
    )
    if boolean_field:
        parsed = _bool_value(value)
        if parsed is not None:
            return parsed
    numeric_field = field in {
        "tp_lookback",
        "tp_multiplier",
        "tp_pips",
        "recent_m5_avg_range_pips",
        "peak_count",
        "peak_direction",
        "decision_price",
        "rsi_1",
        "rsi_2",
        "rsi_3",
        "fc2_direction",
        "fc2_a_range_pips",
        "fc2_approach_impulse_A",
        "fc2_reversal_strength_A",
        "fc2_prior_impulse_retrace_ratio",
        "fc2_second_close_pushback_A",
        "fc2_second_wick_A",
        "fc2_mean_body_A",
        "fc2_pattern_range_A",
        "fc2_directional_progress_A",
    } or (_is_stair_condition_column(field) and stair_suffix in STAIR_NUMERIC_SUFFIXES)
    if numeric_field:
        parsed_number = _numeric(value)
        if parsed_number is not None:
            return round(parsed_number, 12)
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, float, np.integer, np.floating)):
        return round(float(value), 12)
    return str(value).strip()


def _event_snapshot_signature(row: dict[str, Any]) -> str:
    fields = set(EVENT_SIGNATURE_FIELDS)
    fields.update(column for column in row if _is_stair_condition_column(column))
    normalized = tuple(
        (field, _signature_scalar(field, row.get(field)))
        for field in sorted(fields)
    )
    payload = json.dumps(
        normalized,
        ensure_ascii=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _source_usecols(path: Path) -> list[str]:
    columns = list(pd.read_csv(path, nrows=0).columns)
    missing = SOURCE_REQUIRED_COLUMNS.difference(columns)
    if missing:
        raise ValueError(
            "Source candidate CSV is missing required columns: "
            + ", ".join(sorted(missing))
        )
    selected = set(SOURCE_REQUIRED_COLUMNS) | (
        SOURCE_BASIC_CONDITION_COLUMNS.intersection(columns)
    )
    selected.update(column for column in columns if _is_stair_condition_column(column))
    return [column for column in columns if column in selected]


def _threshold_columns(args: argparse.Namespace) -> list[str]:
    columns: list[str] = []
    for prefix, multipliers in (
        ("tp", args.tp_range_multipliers),
        ("lc", args.lc_range_multipliers),
    ):
        for multiplier in multipliers:
            stem = f"{prefix}_{_multiplier_tag(multiplier)}A"
            columns.extend(
                [
                    stem + "_requested_pips",
                    stem + "_effective_pips",
                    stem + "_pips",
                    stem + "_raw_reached",
                    stem + "_reached",
                    stem + "_raw_first_index",
                    stem + "_raw_first_time",
                    stem + "_first_index",
                    stem + "_first_time",
                ]
            )
            if prefix == "tp":
                columns.extend(
                    [
                        stem + "_touch_on_fill_bar",
                        stem + "_fill_confirmed",
                    ]
                )
            else:
                columns.append(stem + "_touch_on_fill_bar")
    return columns


def grid_path_fieldnames(args: argparse.Namespace) -> list[str]:
    return [
        "grid_version",
        "event_id",
        "grid_entry_id",
        "grid_path_id",
        "pair",
        "decision_time",
        "pending_expiry_time",
        "entry_rank_source",
        "entry_candidate_rank",
        "entry_offset_index",
        "entry_offset_range_multiplier",
        "requested_entry_offset_pips",
        "entry_offset_pips",
        "line_price",
        "entry_price",
        "decision_price",
        "adjusted_distance_pips",
        "trade_direction",
        "trade_side",
        "foot_count",
        "peaks_count",
        "core_peak",
        "recent_m5_avg_range_pips",
        "source_target_last_time",
        "conditions_json",
        "path_status",
        "pending_path_complete",
        "filled",
        "fill_time",
        "fill_delay_seconds",
        "fill_at_bar_open",
        "horizon_end",
        "horizon_complete",
        "common_entry_window_end",
        "common_entry_window_complete",
        "timeout_exit_time",
        "timeout_result_pips",
        "pending_s5_rows",
        "position_s5_rows",
        "first_invalid_position_index",
        "full_path_mfe_pips",
        "full_path_mae_pips",
        "fixed_spread_pips",
        "position_horizon_minutes",
        "counterfactual_entry",
        "marketable_limit_excluded",
        *_threshold_columns(args),
    ]


def _timestamp_text(value: Any) -> str | None:
    timestamp = pd.to_datetime(value, errors="coerce")
    if pd.isna(timestamp):
        return None
    return pd.Timestamp(timestamp).isoformat(" ")


def grid_path_row(
    source: dict[str, Any],
    record: GridRecord,
    *,
    line_price: float,
    entry_price: float,
    decision_price: float,
    adjusted_distance_pips: float,
    args: argparse.Namespace,
) -> dict[str, Any]:
    path = record.path
    grid_entry_id = f"{record.event_id}_rank{record.entry_rank}"
    grid_path_id = f"{grid_entry_id}_off{record.offset_index}"
    row: dict[str, Any] = {
        "grid_version": _grid_version(args),
        "event_id": record.event_id,
        "grid_entry_id": grid_entry_id,
        "grid_path_id": grid_path_id,
        "pair": _pair_name(args),
        "decision_time": record.decision_time.isoformat(" "),
        "pending_expiry_time": record.expiry_time.isoformat(" "),
        "entry_rank_source": "raw_distance_rank",
        "entry_candidate_rank": record.entry_rank,
        "entry_offset_index": record.offset_index,
        "entry_offset_range_multiplier": record.offset_range_multiplier,
        "requested_entry_offset_pips": (
            record.average_range_pips * record.offset_range_multiplier
        ),
        "entry_offset_pips": record.offset_pips,
        "line_price": line_price,
        "entry_price": entry_price,
        "decision_price": decision_price,
        "adjusted_distance_pips": adjusted_distance_pips,
        "trade_direction": int(float(source["trade_direction"])),
        "trade_side": source.get("trade_side"),
        "foot_count": int(float(source["peak_count"])),
        "peaks_count": source.get("line_count"),
        "core_peak": source.get("line_core_count"),
        "recent_m5_avg_range_pips": record.average_range_pips,
        "source_target_last_time": _timestamp_text(
            source.get("target_source_last_time")
        ),
        "conditions_json": json.dumps(
            [condition.condition_id for condition in record.conditions],
            ensure_ascii=False,
        ),
        "path_status": path["path_status"],
        "pending_path_complete": path["pending_path_complete"],
        "filled": path["filled"],
        "fill_time": _timestamp_text(path["fill_time"]),
        "fill_delay_seconds": path["fill_delay_seconds"],
        "fill_at_bar_open": path["fill_at_bar_open"],
        "horizon_end": _timestamp_text(path["horizon_end"]),
        "horizon_complete": path["horizon_complete"],
        "common_entry_window_end": _timestamp_text(record.common_path_end),
        "common_entry_window_complete": record.common_path_complete,
        "timeout_exit_time": _timestamp_text(path["timeout_exit_time"]),
        "timeout_result_pips": path["timeout_result_pips"],
        "pending_s5_rows": path["pending_s5_rows"],
        "position_s5_rows": path["position_s5_rows"],
        "first_invalid_position_index": path["first_invalid_position_index"],
        "full_path_mfe_pips": path["full_path_mfe_pips"],
        "full_path_mae_pips": path["full_path_mae_pips"],
        "fixed_spread_pips": args.spread_pips,
        "position_horizon_minutes": args.horizon_minutes,
        "counterfactual_entry": True,
        "marketable_limit_excluded": not record.entry_eligible,
    }
    for index, multiplier in enumerate(args.tp_range_multipliers):
        stem = f"tp_{_multiplier_tag(multiplier)}A"
        row[stem + "_requested_pips"] = record.average_range_pips * multiplier
        row[stem + "_effective_pips"] = record.tp_pips[index]
        row[stem + "_pips"] = record.tp_pips[index]
        row[stem + "_raw_reached"] = bool(path["tp_raw_reached"][index])
        row[stem + "_reached"] = bool(path["tp_reached"][index])
        row[stem + "_raw_first_index"] = int(
            path["tp_raw_first_index"][index]
        )
        row[stem + "_raw_first_time"] = _timestamp_text(
            path["tp_raw_first_time"][index]
        )
        row[stem + "_first_index"] = int(path["tp_first_index"][index])
        row[stem + "_first_time"] = _timestamp_text(path["tp_first_time"][index])
        row[stem + "_touch_on_fill_bar"] = bool(
            path["tp_touch_on_fill_bar"][index]
        )
        row[stem + "_fill_confirmed"] = bool(path["tp_fill_confirmed"][index])
    for index, multiplier in enumerate(args.lc_range_multipliers):
        stem = f"lc_{_multiplier_tag(multiplier)}A"
        row[stem + "_requested_pips"] = record.average_range_pips * multiplier
        row[stem + "_effective_pips"] = record.lc_pips[index]
        row[stem + "_pips"] = record.lc_pips[index]
        row[stem + "_raw_reached"] = bool(path["lc_raw_reached"][index])
        row[stem + "_reached"] = bool(path["lc_reached"][index])
        row[stem + "_raw_first_index"] = int(
            path["lc_raw_first_index"][index]
        )
        row[stem + "_raw_first_time"] = _timestamp_text(
            path["lc_raw_first_time"][index]
        )
        row[stem + "_first_index"] = int(path["lc_first_index"][index])
        row[stem + "_first_time"] = _timestamp_text(path["lc_first_time"][index])
        row[stem + "_touch_on_fill_bar"] = bool(
            path["lc_touch_on_fill_bar"][index]
        )
    return row


AGGREGATE_FIELDNAMES = [
    "grid_version",
    "segment",
    "condition_id",
    "condition_source",
    "condition_field",
    "condition_value",
    "condition_label",
    "combo_index",
    "combo_id",
    "entry_candidate_rank",
    "entry_offset_index",
    "entry_offset_range_multiplier",
    "tp_range_multiplier",
    "lc_range_multiplier",
    "configured_rr",
    "foot2_event_count",
    *METRIC_NAMES,
    "rank_line_availability_rate",
    "eligibility_rate",
    "outcome_coverage_rate",
    "fill_rate",
    "tp_rate_completed",
    "positive_rate_completed",
    "expectancy_r_trade",
    "expectancy_r_opportunity",
    "expectancy_r_per_line_opportunity",
    "expectancy_r_per_foot2",
    "profit_factor_r",
    "average_result_pips",
    "average_win_pips",
    "average_loss_pips",
    "average_tp_pips",
    "average_lc_pips",
    "average_effective_rr",
    "average_entry_offset_pips",
    "active_month_count",
    "positive_month_count",
    "negative_month_count",
    "positive_month_rate",
    "worst_month_r",
    "sample_guard_pass",
    "rr_guard_pass",
    "expectancy_guard_pass",
    "profit_factor_guard_pass",
    "yen_guard_pass",
    "pips_guard_pass",
    "monthly_guard_pass",
    "coverage_guard_pass",
    "guardrail_pass",
]


def _safe_ratio(numerator: float, denominator: float) -> float:
    return float(numerator / denominator) if denominator else np.nan


def aggregate_row(
    accumulator: GridAccumulator,
    *,
    segment: str,
    condition_id: str,
    combo_index: int,
    monthly_summary: dict[tuple[str, str], dict[str, np.ndarray]],
) -> dict[str, Any]:
    state = accumulator.states[(segment, condition_id)]
    condition = accumulator.catalog[condition_id]
    combo = accumulator.combos[combo_index]
    raw = {name: float(state[name][combo_index]) for name in METRIC_NAMES}
    raw["unresolved_count"] = max(
        raw["eligible_count"] - raw["known_count"],
        0.0,
    )
    known = raw["known_count"]
    completed = raw["completed_count"]
    gross_loss = raw["gross_loss_r_abs"]
    foot2_event_count = accumulator.foot2_event_counts.get(
        (segment, condition_id)
    )
    monthly = monthly_summary.get((segment, condition_id))
    if monthly is None:
        active_month_count = positive_month_count = negative_month_count = 0.0
        worst_month_r = np.nan
    else:
        active_month_count = float(monthly["active_month_count"][combo_index])
        positive_month_count = float(monthly["positive_month_count"][combo_index])
        negative_month_count = float(monthly["negative_month_count"][combo_index])
        worst_month_r = float(monthly["worst_month_r"][combo_index])
    profit_factor = (
        raw["gross_profit_r"] / gross_loss
        if gross_loss > 0
        else (np.inf if raw["gross_profit_r"] > 0 else np.nan)
    )
    positive_month_rate = _safe_ratio(positive_month_count, active_month_count)
    row = {
        "grid_version": _grid_version(accumulator.args),
        "segment": segment,
        "condition_id": condition_id,
        "condition_source": condition.source,
        "condition_field": condition.field,
        "condition_value": condition.value,
        "condition_label": condition.label,
        "combo_index": combo_index,
        "combo_id": combo.combo_id,
        "entry_candidate_rank": combo.entry_rank,
        "entry_offset_index": combo.offset_index,
        "entry_offset_range_multiplier": combo.offset_range_multiplier,
        "tp_range_multiplier": combo.tp_range_multiplier,
        "lc_range_multiplier": combo.lc_range_multiplier,
        "configured_rr": combo.configured_rr,
        "foot2_event_count": foot2_event_count,
        **raw,
        "rank_line_availability_rate": _safe_ratio(
            raw["signal_count"], float(foot2_event_count)
        )
        if foot2_event_count is not None
        else np.nan,
        "eligibility_rate": _safe_ratio(
            raw["eligible_count"], raw["signal_count"]
        ),
        "outcome_coverage_rate": _safe_ratio(known, raw["eligible_count"]),
        "fill_rate": _safe_ratio(raw["filled_count"], known),
        "tp_rate_completed": _safe_ratio(raw["tp_count"], completed),
        "positive_rate_completed": _safe_ratio(raw["positive_count"], completed),
        "expectancy_r_trade": _safe_ratio(raw["sum_r"], completed),
        "expectancy_r_opportunity": _safe_ratio(
            raw["sum_r"], raw["signal_count"]
        ),
        "expectancy_r_per_line_opportunity": _safe_ratio(
            raw["sum_r"], raw["signal_count"]
        ),
        "expectancy_r_per_foot2": _safe_ratio(
            raw["sum_r"], float(foot2_event_count)
        )
        if foot2_event_count is not None
        else np.nan,
        "profit_factor_r": profit_factor,
        "average_result_pips": _safe_ratio(raw["sum_pips"], completed),
        "average_win_pips": _safe_ratio(
            raw["positive_pips_sum"], raw["positive_pips_count"]
        ),
        "average_loss_pips": _safe_ratio(
            raw["negative_pips_sum"], raw["negative_pips_count"]
        ),
        "average_tp_pips": _safe_ratio(raw["tp_pips_sum"], known),
        "average_lc_pips": _safe_ratio(raw["lc_pips_sum"], known),
        "average_effective_rr": _safe_ratio(
            raw["effective_rr_sum"], known
        ),
        "average_entry_offset_pips": _safe_ratio(
            raw["entry_offset_pips_sum"], known
        ),
        "active_month_count": active_month_count,
        "positive_month_count": positive_month_count,
        "negative_month_count": negative_month_count,
        "positive_month_rate": positive_month_rate,
        "worst_month_r": worst_month_r,
    }
    row["sample_guard_pass"] = completed >= accumulator.args.min_completed
    row["rr_guard_pass"] = (
        row["average_effective_rr"] >= accumulator.args.min_rr
    )
    row["expectancy_guard_pass"] = row["expectancy_r_trade"] > 0
    row["profit_factor_guard_pass"] = (
        row["profit_factor_r"] >= accumulator.args.min_profit_factor
    )
    row["yen_guard_pass"] = raw["sum_yen"] > 0
    row["pips_guard_pass"] = raw["sum_pips"] > 0
    row["monthly_guard_pass"] = bool(
        active_month_count > 0
        and positive_month_count >= math.floor(active_month_count / 2) + 1
    )
    row["coverage_guard_pass"] = bool(
        row["outcome_coverage_rate"]
        >= accumulator.args.min_outcome_coverage
    )
    row["guardrail_pass"] = bool(
        row["sample_guard_pass"]
        and row["rr_guard_pass"]
        and row["expectancy_guard_pass"]
        and row["profit_factor_guard_pass"]
        and row["yen_guard_pass"]
        and row["pips_guard_pass"]
        and row["monthly_guard_pass"]
        and row["coverage_guard_pass"]
    )
    return row


MONTHLY_FIELDNAMES = [
    "grid_version",
    "segment",
    "month",
    "condition_id",
    "condition_source",
    "condition_field",
    "condition_value",
    "condition_label",
    "combo_index",
    "combo_id",
    "entry_candidate_rank",
    "entry_offset_range_multiplier",
    "tp_range_multiplier",
    "lc_range_multiplier",
    "configured_rr",
    *MONTHLY_METRIC_NAMES,
    "positive_rate_completed",
    "average_result_pips",
    "average_win_pips",
]


def write_aggregate_monthly(
    accumulator: GridAccumulator,
    paths: dict[str, Path],
) -> dict[str, Path]:
    monthly_summary = accumulator.monthly_summary()
    aggregate_writer = PartCsvWriter(paths["aggregate"], AGGREGATE_FIELDNAMES)

    def rows_for(segment: str, condition_id: str) -> Iterable[dict[str, Any]]:
        state = accumulator.states[(segment, condition_id)]
        for raw_index in np.flatnonzero(state["signal_count"] > 0):
            yield aggregate_row(
                accumulator,
                segment=segment,
                condition_id=condition_id,
                combo_index=int(raw_index),
                monthly_summary=monthly_summary,
            )

    try:
        for segment, condition_id in sorted(accumulator.states):
            for row in rows_for(segment, condition_id):
                aggregate_writer.writerow(row)
        aggregate_writer.finalize()
    except Exception:
        aggregate_writer.abort()
        raise

    monthly_writer = PartCsvWriter(paths["monthly"], MONTHLY_FIELDNAMES)
    try:
        for (segment, month, condition_id), metrics in sorted(
            accumulator.monthly_states.items()
        ):
            active_indices = np.flatnonzero(metrics["signal_count"] > 0)
            for combo_index in active_indices:
                combo_index = int(combo_index)
                combo = accumulator.combos[combo_index]
                condition = accumulator.catalog[condition_id]
                monthly_values = {
                    field: float(metrics[field][combo_index])
                    for field in MONTHLY_METRIC_NAMES
                }
                completed = monthly_values["completed_count"]
                monthly_writer.writerow(
                    {
                        "grid_version": _grid_version(accumulator.args),
                        "segment": segment,
                        "month": month,
                        "condition_id": condition_id,
                        "condition_source": condition.source,
                        "condition_field": condition.field,
                        "condition_value": condition.value,
                        "condition_label": condition.label,
                        "combo_index": combo_index,
                        "combo_id": combo.combo_id,
                        "entry_candidate_rank": combo.entry_rank,
                        "entry_offset_range_multiplier": combo.offset_range_multiplier,
                        "tp_range_multiplier": combo.tp_range_multiplier,
                        "lc_range_multiplier": combo.lc_range_multiplier,
                        "configured_rr": combo.configured_rr,
                        **monthly_values,
                        "positive_rate_completed": _safe_ratio(
                            monthly_values["positive_count"], completed
                        ),
                        "average_result_pips": _safe_ratio(
                            monthly_values["sum_pips"], completed
                        ),
                        "average_win_pips": _safe_ratio(
                            monthly_values["positive_pips_sum"],
                            monthly_values["positive_count"],
                        ),
                    }
                )
        monthly_writer.finalize()
    except Exception:
        monthly_writer.abort()
        raise
    return paths


def _source_row_dict(row: pd.Series) -> dict[str, Any]:
    return {column: row[column] for column in row.index}


def _has_stair_context(row: dict[str, Any], prefix: str) -> bool:
    """Return whether a staircase detector result is present.

    ``profile_enabled`` controls whether the live strategy uses that detector;
    it does not control whether its causal output may be researched.  The
    resistance sweep computes and stores the context even for a disabled live
    profile, so False is valid here.  Missing/malformed flags or states are not.
    """
    profile_enabled = _bool_value(row.get(f"{prefix}_stair_profile_enabled"))
    state = row.get(f"{prefix}_stair_state")
    state_text = "" if state is None else str(state).strip()
    return profile_enabled is not None and state_text.lower() not in {
        "",
        "nan",
    }


def _validate_fc2_context(
    row: dict[str, Any],
    *,
    decision_time: pd.Timestamp,
    average_range: float,
    peak_direction: float,
    include_line: bool,
) -> None:
    """Validate the causal/A-normalized foot-count-2 feature contract."""
    if _bool_value(row.get("fc2_valid")) is not True:
        raise ValueError(f"Invalid FC2 shape context at {decision_time}")
    if str(row.get("fc2_version")) != "foot_count2_shape_a_v1":
        raise ValueError(f"Unknown FC2 shape version at {decision_time}")
    if _numeric(row.get("fc2_direction")) != peak_direction:
        raise ValueError(f"FC2/peak direction mismatch at {decision_time}")
    shape = str(row.get("fc2_shape")).strip().upper()
    if shape not in {"REJECTION", "ENGULFING", "STALL", "CONTINUATION"}:
        raise ValueError(f"Invalid FC2 shape at {decision_time}: {shape}")
    shape_flag = _bool_value(row.get("fc2_" + shape.lower()))
    if shape_flag is not True:
        raise ValueError(f"FC2 shape flag mismatch at {decision_time}: {shape}")
    shape_flags = [
        _bool_value(row.get("fc2_" + value.lower()))
        for value in ("REJECTION", "ENGULFING", "STALL", "CONTINUATION")
    ]
    if any(value is None for value in shape_flags) or sum(shape_flags) != 1:
        raise ValueError(f"FC2 shape flags are not one-hot at {decision_time}")
    a_range = _numeric(row.get("fc2_a_range_pips"))
    if a_range is None or not math.isclose(
        a_range,
        average_range,
        rel_tol=1e-9,
        abs_tol=1e-9,
    ):
        raise ValueError(f"FC2 A width mismatch at {decision_time}")
    source_times = [
        pd.to_datetime(row.get(field), errors="coerce")
        for field in (
            "fc2_prior_source_time",
            "fc2_source_first_time",
            "fc2_source_last_time",
        )
    ]
    if any(pd.isna(value) for value in source_times):
        raise ValueError(f"FC2 source timestamps are missing at {decision_time}")
    prior, first, last = (pd.Timestamp(value) for value in source_times)
    if not prior < first <= last or last + pd.Timedelta(minutes=5) > decision_time:
        raise ValueError(f"FC2 source timestamps are not causal at {decision_time}")
    numeric_fields = {
        "fc2_approach_impulse_A",
        "fc2_reversal_strength_A",
        "fc2_second_close_pushback_A",
        "fc2_second_wick_A",
        "fc2_mean_body_A",
        "fc2_pattern_range_A",
        "fc2_directional_progress_A",
    }
    if include_line:
        numeric_fields.update(FC2_LINE_COLUMNS.intersection({
            "fc2_line_wick_overshoot_pips",
            "fc2_line_wick_overshoot_A",
            "fc2_line_body_break_pips",
            "fc2_line_body_break_A",
        }))
    missing_numeric = sorted(
        field for field in numeric_fields if _numeric(row.get(field)) is None
    )
    if missing_numeric:
        raise ValueError(
            f"FC2 numeric fields are missing at {decision_time}: "
            + ", ".join(missing_numeric)
        )
    if include_line:
        line_shape = str(row.get("fc2_line_shape")).strip().upper()
        if line_shape not in {
            "REJECTION",
            "ENGULFING",
            "STALL",
            "CONTINUATION",
        }:
            raise ValueError(
                f"Invalid FC2 line shape at {decision_time}: {line_shape}"
            )
        for field in (
            "fc2_line_wick_overshoot_pips",
            "fc2_line_wick_overshoot_A",
            "fc2_line_body_break_pips",
            "fc2_line_body_break_A",
        ):
            if float(row[field]) < 0:
                raise ValueError(f"Negative {field} at {decision_time}")


def _validate_source_decision(
    source: dict[str, Any],
    args: argparse.Namespace,
) -> tuple[pd.Timestamp, pd.Timestamp]:
    pair_name = _pair_name(args)
    if str(source.get("pair")) != pair_name:
        raise ValueError(
            f"Source row pair is not {pair_name}: {source.get('pair')}"
        )
    decision_time = pd.to_datetime(source.get("decision_time"), errors="raise")
    expiry_time = pd.to_datetime(source.get("next_count2_time"), errors="raise")
    if not pd.Timestamp(args.start) <= decision_time < pd.Timestamp(args.end):
        raise ValueError(f"Source decision is outside requested period: {decision_time}")
    expected_event_id = f"{pair_name}_{pd.Timestamp(decision_time):%Y%m%d%H%M%S}"
    if str(source.get("event_id")) != expected_event_id:
        raise ValueError(
            f"Source event_id/time mismatch: {source.get('event_id')} != "
            f"{expected_event_id}"
        )
    if expiry_time <= decision_time:
        raise ValueError(f"Invalid next count2 time at {decision_time}")
    target_last = pd.to_datetime(
        source.get("target_source_last_time"), errors="coerce"
    )
    target_first = pd.to_datetime(
        source.get("target_source_first_time"), errors="coerce"
    )
    if pd.isna(target_first) or pd.isna(target_last):
        raise ValueError(f"Target source timestamps are missing at {decision_time}")
    if target_first > target_last:
        raise ValueError(f"Target source window is reversed at {decision_time}")
    if target_last + pd.Timedelta(minutes=5) > decision_time:
        raise ValueError(
            "Future-safe target check failed at "
            f"{decision_time}: target_source_last_time={target_last}"
        )
    lookback = _numeric(source.get("tp_lookback"))
    if lookback != 6:
        raise ValueError(
            f"Source target is not the required preceding-six-M5 average: "
            f"tp_lookback={lookback} at {decision_time}"
        )
    if _bool_value(source.get("target_valid")) is not True:
        raise ValueError(f"Source target is not valid at {decision_time}")
    if (
        str(source.get("line_timeframe")) != "M5"
        or _numeric(source.get("line_history_bars")) != 60
        or str(source.get("candidate_scope"))
        != "all_raw_m5_line_groups_ahead"
        or _bool_value(source.get("candidate_pruning_applied")) is not False
        or _bool_value(source.get("pending_expiry_exclusive")) is not True
    ):
        raise ValueError(
            f"Source line/pending contract does not match the target grid "
            f"at {decision_time}"
        )
    if not _has_stair_context(source, "m5") or not _has_stair_context(
        source, "h1"
    ):
        raise ValueError(
            f"Source is missing valid M5/H1 staircase context at "
            f"{decision_time}"
        )
    average_range = _numeric(source.get("recent_m5_avg_range_pips"))
    source_multiplier = _numeric(source.get("tp_multiplier"))
    source_tp = _numeric(source.get("tp_pips"))
    if (
        average_range is None
        or source_multiplier is None
        or source_tp is None
        or not math.isclose(
            average_range * source_multiplier,
            source_tp,
            rel_tol=1e-9,
            abs_tol=1e-9,
        )
    ):
        raise ValueError(f"Source target width contract failed at {decision_time}")
    _validate_fc2_context(
        source,
        decision_time=pd.Timestamp(decision_time),
        average_range=float(average_range),
        peak_direction=_numeric(source.get("peak_direction")),
        include_line=True,
    )
    for field in ("peak_latest_time", "line_newest_source_time"):
        value = source.get(field)
        if value is None or bool(pd.isna(value)):
            raise ValueError(f"Missing required {field} at {decision_time}")
        timestamp = pd.to_datetime(value, errors="coerce")
        if pd.isna(timestamp):
            raise ValueError(f"Invalid {field} at {decision_time}: {value}")
        if timestamp + pd.Timedelta(minutes=5) > decision_time:
            raise ValueError(
                f"Future-safe {field} check failed at {decision_time}: "
                f"{timestamp}"
            )
    prior_retouch_time = source.get("prior_retouch_last_time")
    if prior_retouch_time is not None and not bool(pd.isna(prior_retouch_time)):
        timestamp = pd.to_datetime(prior_retouch_time, errors="coerce")
        if pd.isna(timestamp) or timestamp + pd.Timedelta(minutes=5) > decision_time:
            raise ValueError(
                f"Future-safe prior_retouch_last_time check failed at "
                f"{decision_time}: {prior_retouch_time}"
            )
    foot_count = _numeric(source.get("peak_count"))
    if foot_count != 2:
        raise ValueError(
            f"Source row is not foot count 2 at {decision_time}: {foot_count}"
        )
    return pd.Timestamp(decision_time), pd.Timestamp(expiry_time)


def _event_usecols(path: Path) -> list[str]:
    columns = list(pd.read_csv(path, nrows=0).columns)
    missing = EVENT_REQUIRED_COLUMNS.difference(columns)
    if missing:
        raise ValueError(
            "Source event CSV is missing required columns: "
            + ", ".join(sorted(missing))
        )
    selected = set(EVENT_REQUIRED_COLUMNS)
    selected.update(
        column for column in columns if _is_stair_condition_column(column)
    )
    return [column for column in columns if column in selected]


def _validate_event_decision(
    event: dict[str, Any],
    args: argparse.Namespace,
) -> tuple[pd.Timestamp, pd.Timestamp, int]:
    pair_name = _pair_name(args)
    if str(event.get("pair")) != pair_name:
        raise ValueError(
            f"Event ledger pair is not {pair_name}: {event.get('pair')}"
        )
    decision_time = pd.to_datetime(event.get("decision_time"), errors="raise")
    expiry_time = pd.to_datetime(event.get("next_count2_time"), errors="raise")
    if not pd.Timestamp(args.start) <= decision_time < pd.Timestamp(args.end):
        raise ValueError(
            f"Event ledger decision is outside requested period: {decision_time}"
        )
    expected_event_id = f"{pair_name}_{pd.Timestamp(decision_time):%Y%m%d%H%M%S}"
    if str(event.get("event_id")) != expected_event_id:
        raise ValueError(
            f"Event ledger id/time mismatch: {event.get('event_id')} != "
            f"{expected_event_id}"
        )
    if expiry_time <= decision_time:
        raise ValueError(f"Invalid event-ledger expiry at {decision_time}")
    if _numeric(event.get("peak_count")) != 2:
        raise ValueError(f"Event ledger row is not foot count 2 at {decision_time}")
    peak_direction = _numeric(event.get("peak_direction"))
    if peak_direction not in (-1, 1):
        raise ValueError(f"Invalid event peak direction at {decision_time}")
    if _numeric(event.get("tp_lookback")) != 6:
        raise ValueError(f"Event ledger target lookback is not 6 at {decision_time}")
    if _bool_value(event.get("target_valid")) is not True:
        raise ValueError(f"Event ledger target is not valid at {decision_time}")
    target_first = pd.to_datetime(
        event.get("target_source_first_time"), errors="coerce"
    )
    target_last = pd.to_datetime(
        event.get("target_source_last_time"), errors="coerce"
    )
    if (
        pd.isna(target_first)
        or pd.isna(target_last)
        or target_first > target_last
        or target_last + pd.Timedelta(minutes=5) > decision_time
    ):
        raise ValueError(
            f"Event ledger target timestamps are not causal at {decision_time}"
        )
    average_range = _numeric(event.get("recent_m5_avg_range_pips"))
    multiplier = _numeric(event.get("tp_multiplier"))
    source_tp = _numeric(event.get("tp_pips"))
    if (
        average_range is None
        or multiplier is None
        or source_tp is None
        or not math.isclose(
            average_range * multiplier,
            source_tp,
            rel_tol=1e-9,
            abs_tol=1e-9,
        )
    ):
        raise ValueError(f"Event ledger target width mismatch at {decision_time}")
    _validate_fc2_context(
        event,
        decision_time=pd.Timestamp(decision_time),
        average_range=float(average_range),
        peak_direction=float(peak_direction),
        include_line=False,
    )
    peak_latest = pd.to_datetime(event.get("peak_latest_time"), errors="coerce")
    if pd.isna(peak_latest) or peak_latest + pd.Timedelta(minutes=5) > decision_time:
        raise ValueError(f"Event ledger peak is not completed at {decision_time}")
    if not _has_stair_context(event, "m5") or not _has_stair_context(
        event, "h1"
    ):
        raise ValueError(
            f"Event ledger lacks valid M5/H1 staircase context at "
            f"{decision_time}"
        )
    candidate_count_value = _numeric(event.get("candidate_count"))
    if (
        candidate_count_value is None
        or candidate_count_value < 0
        or not float(candidate_count_value).is_integer()
    ):
        raise ValueError(f"Invalid event candidate_count at {decision_time}")
    return (
        pd.Timestamp(decision_time),
        pd.Timestamp(expiry_time),
        int(candidate_count_value),
    )


def load_foot2_event_ledger(
    args: argparse.Namespace,
) -> tuple[
    dict[tuple[str, str], int],
    dict[
        str,
        tuple[
            pd.Timestamp,
            pd.Timestamp,
            int,
            str,
        ],
    ],
    dict[str, Any],
]:
    """Load the fixed foot2 opportunity denominator from the event ledger."""
    if not args.source_events.exists():
        raise FileNotFoundError(f"Source event CSV not found: {args.source_events}")
    usecols = _event_usecols(args.source_events)
    counts: dict[tuple[str, str], int] = defaultdict(int)
    events: dict[
        str,
        tuple[
            pd.Timestamp,
            pd.Timestamp,
            int,
            str,
        ],
    ] = {}
    rows_seen = 0
    evaluated_rows = 0
    for chunk in pd.read_csv(
        args.source_events,
        usecols=usecols,
        chunksize=max(args.read_chunk_size, 1000),
        low_memory=False,
    ):
        rows_seen += len(chunk)
        for _, series in chunk.iterrows():
            event = _source_row_dict(series)
            if str(event.get("event_status")) not in {
                "evaluated",
                "no_candidates",
            }:
                continue
            decision_time, expiry_time, candidate_count = _validate_event_decision(
                event,
                args,
            )
            event_id = str(event["event_id"])
            if event_id in events:
                raise ValueError(f"Duplicate event in source ledger: {event_id}")
            peak_direction = int(float(event["peak_direction"]))
            event["trade_direction"] = -peak_direction
            event["trade_side"] = "BUY" if peak_direction == -1 else "SELL"
            memberships = condition_memberships(event)
            events[event_id] = (
                decision_time,
                expiry_time,
                candidate_count,
                _event_snapshot_signature(event),
            )
            evaluated_rows += 1
            segments = ["full"]
            for segment in segments:
                for condition in memberships:
                    counts[(segment, condition.condition_id)] += 1
    if not events:
        raise ValueError("Source event ledger has no evaluated foot count 2 rows")
    return (
        dict(counts),
        events,
        {
            "rows_seen": rows_seen,
            "valid_foot2_events_including_no_candidates": evaluated_rows,
            "source_stat": _source_stat(args.source_events),
        },
    )


def _coverage_manifest(accumulator: GridAccumulator) -> dict[str, Any]:
    result: dict[str, Any] = {}
    condition_id = "ALL::all::all"
    for segment in ("full",):
        state = accumulator.states.get((segment, condition_id))
        if state is None:
            result[segment] = {"combination_count": 0}
            continue
        active = state["signal_count"] > 0
        if not active.any():
            result[segment] = {"combination_count": 0}
            continue
        signal = state["signal_count"][active]
        eligible = state["eligible_count"][active]
        known = state["known_count"][active]
        result[segment] = {
            "combination_count": int(active.sum()),
            "valid_foot2_event_count": accumulator.foot2_event_counts.get(
                (segment, condition_id)
            ),
            "line_opportunity_count_min": float(signal.min()),
            "line_opportunity_count_max": float(signal.max()),
            "eligible_count_min": float(eligible.min()),
            "eligible_count_max": float(eligible.max()),
            "common_cohort_known_count_min": float(known.min()),
            "common_cohort_known_count_max": float(known.max()),
            "unresolved_eligible_count_max": float(
                np.maximum(eligible - known, 0).max()
            ),
        }
    return result


def run_grid_search(args: argparse.Namespace) -> dict[str, Path]:
    """Run a pair grid from existing causal outputs; never fetch data."""
    pair_name = _pair_name(args)
    if not args.source_candidates.exists():
        raise FileNotFoundError(
            "Causal candidate CSV not found. Run the matching pair's "
            "count2 resistance sweep first: "
            f"{args.source_candidates}"
        )
    if not args.source_events.exists():
        raise FileNotFoundError(
            f"Causal foot2 event ledger not found: {args.source_events}"
        )
    if not args.s5_cache.exists():
        raise FileNotFoundError(f"S5 cache not found: {args.s5_cache}")
    if not s5_cache_has_no_tick_completion(args.s5_cache):
        raise ValueError(
            "S5 cache predates auditable no-tick completion and cannot be used: "
            f"{args.s5_cache}"
        )

    paths = output_paths(args)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    _archive_generation(paths)
    process_started = time.monotonic()
    wall_started = dt.datetime.now().astimezone()
    source_rows_total = _count_csv_rows(args.source_candidates)
    if args.max_source_rows is not None:
        source_rows_total = min(source_rows_total, args.max_source_rows)
    _write_progress(
        paths["progress"],
        args=args,
        status="running",
        phase="loading_s5",
        started_at=wall_started,
        process_started=process_started,
        source_rows_total=source_rows_total,
    )
    _notify(
        "\n".join(
            [
                f"{pair_name} foot count 2 entry/TP/LC grid 開始",
                f"- 期間: {args.start:%Y-%m-%d} から {args.end:%Y-%m-%d} 未満",
                "- 出力: 1年全期間の全組み合わせ（順位付けなし）",
                f"- entry: 距離順位 {list(args.entry_ranks)} × offset {list(args.entry_offset_range_multipliers)}A",
                f"- TP: {list(args.tp_range_multipliers)}A",
                f"- LC: {list(args.lc_range_multipliers)}A",
                "- 条件: TOP15/live gateによる事前除外なし",
                "- 注記: 3つのentryは同時注文ではなく反実仮想の代替候補",
            ]
        )
    )

    try:
        pair = gene.currency_pair(pair_name)
        inspector, s5_metadata = _load_typed_s5_inspector(
            args.s5_cache,
            pair,
        )
        coverage_errors = _s5_coverage_errors(inspector.times, args)
        if coverage_errors:
            raise ValueError(
                "S5 cache coverage is incomplete for the requested signal "
                "period: "
                + "; ".join(coverage_errors)
            )
        inspector = _bound_inspector_before(inspector, pd.Timestamp(args.end))
        combos, prefix_indices = build_grid_combos(args)
        accumulator = GridAccumulator(args, pair, combos, prefix_indices)
        usecols = _source_usecols(args.source_candidates)
        (
            accumulator.foot2_event_counts,
            event_ledger,
            event_ledger_stats,
        ) = load_foot2_event_ledger(args)
        path_writer = PartCsvWriter(
            paths["paths"],
            grid_path_fieldnames(args),
        )
    except Exception as error:
        _write_progress(
            paths["progress"],
            args=args,
            status="failed",
            phase="startup_validation_failed",
            started_at=wall_started,
            process_started=process_started,
            source_rows_total=source_rows_total,
            error=f"{type(error).__name__}: {error}",
        )
        _archive_file(paths["progress"])
        _notify(
            "\n".join(
                [
                    f"{pair_name} foot count 2 entry/TP/LC grid 起動失敗",
                    f"- エラー種別: {type(error).__name__}",
                    f"- 内容: {error}",
                    "- progress/temp: archiveへ移動済み",
                ]
            )
        )
        raise

    source_rows_processed = 0
    selected_line_rows = 0
    grid_path_rows = 0
    marketable_excluded = 0
    invalid_width_rows = 0
    path_status_counts: dict[str, int] = defaultdict(int)
    future_safe_rows = 0
    notice_threshold = 25
    records_buffer: list[GridRecord] = []
    seen_selected_lines: set[tuple[str, int]] = set()
    common_window_cache: dict[str, tuple[pd.Timestamp, pd.Timestamp, bool]] = {}
    candidate_source_counts: dict[str, int] = defaultdict(int)
    event_signatures: dict[str, tuple[Any, ...]] = {}
    event_rank_distances: dict[str, dict[int, float]] = defaultdict(dict)

    try:
        chunks = pd.read_csv(
            args.source_candidates,
            usecols=usecols,
            chunksize=args.read_chunk_size,
            low_memory=False,
        )
        for chunk in chunks:
            if args.max_source_rows is not None:
                remaining = args.max_source_rows - source_rows_processed
                if remaining <= 0:
                    break
                chunk = chunk.iloc[:remaining]
            source_rows_processed += len(chunk)
            for event_id, count in chunk["event_id"].value_counts().items():
                candidate_source_counts[str(event_id)] += int(count)
            for raw_event_id, raw_rank, raw_distance in chunk[
                ["event_id", "candidate_rank", "distance_pips"]
            ].itertuples(index=False, name=None):
                rank_number = _numeric(raw_rank)
                distance_number = _numeric(raw_distance)
                if (
                    rank_number is None
                    or not float(rank_number).is_integer()
                    or rank_number < 1
                    or distance_number is None
                    or distance_number <= 0
                ):
                    raise ValueError(
                        f"Invalid raw rank/distance in candidate source: "
                        f"event={raw_event_id}, rank={raw_rank}, "
                        f"distance={raw_distance}"
                    )
                rank_integer = int(rank_number)
                rank_map = event_rank_distances[str(raw_event_id)]
                if rank_integer in rank_map:
                    raise ValueError(
                        f"Duplicate raw candidate rank: "
                        f"event={raw_event_id}, rank={rank_integer}"
                    )
                rank_map[rank_integer] = float(distance_number)
            ranks = pd.to_numeric(chunk["candidate_rank"], errors="coerce")
            selected_chunk = chunk[ranks.isin(args.entry_ranks)]

            for _, source_series in selected_chunk.iterrows():
                source = _source_row_dict(source_series)
                decision_time, expiry_time = _validate_source_decision(source, args)
                future_safe_rows += 1
                selected_line_rows += 1
                average_range = _numeric(source.get("recent_m5_avg_range_pips"))
                line_price = _numeric(source.get("line_price"))
                decision_price = _numeric(source.get("decision_price"))
                peak_direction = _numeric(source.get("peak_direction"))
                trade_direction = _numeric(source.get("trade_direction"))
                candidate_rank = _numeric(source.get("candidate_rank"))
                if (
                    average_range is None
                    or average_range <= 0
                    or line_price is None
                    or decision_price is None
                    or peak_direction not in (-1, 1)
                    or trade_direction not in (-1, 1)
                    or candidate_rank is None
                ):
                    invalid_width_rows += 1
                    continue
                if int(trade_direction) != -int(peak_direction):
                    raise ValueError(
                        "Source direction mismatch at "
                        f"{decision_time}: peak={peak_direction}, "
                        f"trade={trade_direction}"
                    )
                source_distance = _numeric(source.get("distance_pips"))
                calculated_distance = (
                    (line_price - decision_price)
                    * int(peak_direction)
                    / pair.pip_value
                )
                if (
                    source_distance is None
                    or source_distance <= 0
                    or not math.isclose(
                        calculated_distance,
                        source_distance,
                        rel_tol=1e-9,
                        abs_tol=1e-6,
                    )
                ):
                    raise ValueError(
                        f"Source line distance mismatch at {decision_time}: "
                        f"stored={source_distance}, calculated={calculated_distance}"
                    )
                expected_side = "BUY" if int(trade_direction) == 1 else "SELL"
                if str(source.get("trade_side")) != expected_side:
                    raise ValueError(
                        f"Source trade side mismatch at {decision_time}: "
                        f"{source.get('trade_side')} != {expected_side}"
                    )
                entry_rank = int(candidate_rank)
                event_id = str(source["event_id"])
                signature = (
                    decision_time,
                    expiry_time,
                    average_range,
                    decision_price,
                    int(peak_direction),
                    _timestamp_text(source.get("target_source_first_time")),
                    _timestamp_text(source.get("target_source_last_time")),
                    str(source.get("m5_stair_state")),
                    str(source.get("h1_stair_state")),
                )
                prior_signature = event_signatures.setdefault(event_id, signature)
                if prior_signature != signature:
                    raise ValueError(
                        f"Candidate ranks disagree on event snapshot: {event_id}"
                    )
                ledger_entry = event_ledger.get(event_id)
                if ledger_entry is None:
                    raise ValueError(
                        f"Candidate event is absent from event ledger: {event_id}"
                    )
                (
                    ledger_decision,
                    ledger_expiry,
                    _ledger_candidate_count,
                    ledger_snapshot_signature,
                ) = ledger_entry
                if (
                    ledger_decision != decision_time
                    or ledger_expiry != expiry_time
                ):
                    raise ValueError(
                        f"Candidate/event-ledger time mismatch: {event_id}"
                    )
                selected_line_key = (event_id, entry_rank)
                if selected_line_key in seen_selected_lines:
                    raise ValueError(
                        "Duplicate event/rank in source candidates: "
                        f"{selected_line_key}"
                    )
                seen_selected_lines.add(selected_line_key)
                cached_window = common_window_cache.get(event_id)
                if cached_window is None:
                    common_end, common_complete = inspect_common_entry_window(
                        inspector,
                        decision_time=decision_time,
                        expiry_time=expiry_time,
                        horizon_minutes=args.horizon_minutes,
                    )
                    common_window_cache[event_id] = (
                        expiry_time,
                        common_end,
                        common_complete,
                    )
                else:
                    cached_expiry, common_end, common_complete = cached_window
                    if cached_expiry != expiry_time:
                        raise ValueError(
                            f"Source event has inconsistent expiry: {event_id}"
                        )
                conditions = condition_memberships(source)
                candidate_snapshot_signature = _event_snapshot_signature(source)
                if candidate_snapshot_signature != ledger_snapshot_signature:
                    raise ValueError(
                        f"Candidate/event causal snapshot mismatch: {event_id}"
                    )
                tp_pips = executable_target_pips(
                    average_range
                    * np.asarray(args.tp_range_multipliers, dtype=float),
                    minimum_pips=args.min_target_pips,
                    pair=pair,
                )
                lc_pips = executable_target_pips(
                    average_range
                    * np.asarray(args.lc_range_multipliers, dtype=float),
                    minimum_pips=args.min_target_pips,
                    pair=pair,
                )

                for offset_index, offset_multiplier in enumerate(
                    args.entry_offset_range_multipliers
                ):
                    entry = adjusted_entry_parameters(
                        line_price=line_price,
                        decision_price=decision_price,
                        peak_direction=int(peak_direction),
                        average_range_pips=average_range,
                        offset_range_multiplier=offset_multiplier,
                        pair=pair,
                        spread_pips=args.spread_pips,
                    )
                    offset_pips = float(entry["entry_offset_pips"])
                    entry_price = float(entry["entry_price"])
                    adjusted_distance = float(entry["adjusted_distance_pips"])
                    entry_eligible = not bool(entry["marketable_limit"])
                    if not entry_eligible:
                        marketable_excluded += 1
                        path = _empty_threshold_path(
                            "marketable_limit_excluded",
                            tp_count=len(tp_pips),
                            lc_count=len(lc_pips),
                        )
                    else:
                        path = inspect_entry_thresholds(
                            inspector,
                            decision_time=decision_time,
                            expiry_time=expiry_time,
                            direction=int(trade_direction),
                            entry_price=entry_price,
                            tp_pips=tp_pips,
                            lc_pips=lc_pips,
                            horizon_minutes=args.horizon_minutes,
                            spread_pips=args.spread_pips,
                        )
                    record = GridRecord(
                        event_id=event_id,
                        decision_time=decision_time,
                        expiry_time=expiry_time,
                        entry_rank=entry_rank,
                        offset_index=offset_index,
                        offset_range_multiplier=offset_multiplier,
                        offset_pips=offset_pips,
                        average_range_pips=average_range,
                        tp_pips=tp_pips,
                        lc_pips=lc_pips,
                        path=path,
                        conditions=conditions,
                        entry_eligible=entry_eligible,
                        common_path_end=common_end,
                        common_path_complete=common_complete,
                    )
                    path_writer.writerow(
                        grid_path_row(
                            source,
                            record,
                            line_price=line_price,
                            entry_price=entry_price,
                            decision_price=decision_price,
                            adjusted_distance_pips=adjusted_distance,
                            args=args,
                        )
                    )
                    records_buffer.append(record)
                    grid_path_rows += 1
                    path_status_counts[str(path["path_status"])] += 1

            if records_buffer:
                accumulator.add_records(records_buffer)
                records_buffer.clear()
            _write_progress(
                paths["progress"],
                args=args,
                status="running",
                phase="processing_grid",
                started_at=wall_started,
                process_started=process_started,
                source_rows_total=source_rows_total,
                source_rows_processed=min(
                    source_rows_processed, source_rows_total
                ),
                selected_line_rows=selected_line_rows,
                grid_path_rows=grid_path_rows,
            )
            percent = (
                100 * source_rows_processed / source_rows_total
                if source_rows_total
                else 100
            )
            while percent >= notice_threshold and notice_threshold <= 75:
                elapsed_minutes = (time.monotonic() - process_started) / 60
                _notify(
                    "\n".join(
                        [
                            f"{pair_name} entry/TP/LC grid 進捗",
                            f"- 処理: {source_rows_processed}/{source_rows_total} ({percent:.1f}%)",
                            f"- entryライン: {selected_line_rows}",
                            f"- entry path: {grid_path_rows}",
                            f"- 経過: {elapsed_minutes:.1f}分",
                        ]
                    )
                )
                notice_threshold += 25
            if (
                args.max_source_rows is not None
                and source_rows_processed >= args.max_source_rows
            ):
                break

        if records_buffer:
            accumulator.add_records(records_buffer)
            records_buffer.clear()
        if args.max_source_rows is None:
            unexpected_events = sorted(
                set(candidate_source_counts).difference(event_ledger)
            )
            count_mismatches = [
                (event_id, candidate_source_counts.get(event_id, 0), expected[2])
                for event_id, expected in event_ledger.items()
                if candidate_source_counts.get(event_id, 0) != expected[2]
            ]
            if unexpected_events or count_mismatches:
                raise ValueError(
                    "Candidate/event ledger mismatch: "
                    f"unexpected={unexpected_events[:5]}, "
                    f"count_mismatches={count_mismatches[:5]}"
                )
            rank_contract_errors: list[tuple[str, list[int], list[float]]] = []
            for event_id, rank_map in event_rank_distances.items():
                ranks = sorted(rank_map)
                expected_ranks = list(range(1, max(ranks) + 1))
                distances = [rank_map[rank] for rank in ranks]
                if ranks != expected_ranks or any(
                    following + 1e-9 < previous
                    for previous, following in zip(distances, distances[1:])
                ):
                    rank_contract_errors.append((event_id, ranks, distances))
            if rank_contract_errors:
                raise ValueError(
                    "Raw distance-rank contract failed: "
                    f"{rank_contract_errors[:5]}"
                )
        path_writer.finalize()

        _write_progress(
            paths["progress"],
            args=args,
            status="running",
            phase="writing_aggregates",
            started_at=wall_started,
            process_started=process_started,
            source_rows_total=source_rows_total,
            source_rows_processed=min(source_rows_processed, source_rows_total),
            selected_line_rows=selected_line_rows,
            grid_path_rows=grid_path_rows,
        )
        paths = write_aggregate_monthly(accumulator, paths)

        elapsed_minutes = (time.monotonic() - process_started) / 60
        manifest = {
            **_grid_config(args),
            "status": "complete",
            "created_at": dt.datetime.now().astimezone().isoformat(
                timespec="seconds"
            ),
            "source_candidates": str(args.source_candidates),
            "source_candidates_size": args.source_candidates.stat().st_size,
            "source_candidates_stat": _source_stat(args.source_candidates),
            "source_events": str(args.source_events),
            "source_events_stat": _source_stat(args.source_events),
            "event_ledger": event_ledger_stats,
            "s5_cache": str(args.s5_cache),
            "s5_cache_size": args.s5_cache.stat().st_size,
            "s5_cache_stat": _source_stat(args.s5_cache),
            "s5_typed_cache": s5_metadata,
            "s5_coverage_errors": coverage_errors,
            "outputs": {name: str(path) for name, path in paths.items()},
            "source_rows_total": source_rows_total,
            "source_rows_processed": source_rows_processed,
            "entry_candidate_line_rows": selected_line_rows,
            "grid_path_rows": grid_path_rows,
            "marketable_limit_excluded": marketable_excluded,
            "invalid_source_width_rows": invalid_width_rows,
            "future_safe_source_rows": future_safe_rows,
            "path_status_counts": dict(sorted(path_status_counts.items())),
            "complete_grid_combination_count": len(combos),
            "elapsed_minutes": round(elapsed_minutes, 2),
            "common_cohort_audit": _coverage_manifest(accumulator),
            "future_safety": {
                "decision_features_source": "causal resistance sweep CSV",
                "target_preceding_six_completed_m5_enforced": True,
                "available_peak_line_retouch_m5_completion_enforced": True,
                "h1_stair_causality_inherited_from_source_generator": True,
                "fc2_shape_completed_m5_only_enforced": True,
                "fc2_a_equals_preceding_six_m5_average_enforced": True,
                "stair_profile_enablement_not_used_as_research_gate": True,
                "s5_used_only_for_outcome": True,
                "s5_signal_period_coverage_enforced": True,
                "s5_at_or_after_requested_end_excluded": True,
                "known_market_closure_edges_treated_as_complete": True,
                "unknown_s5_gaps_treated_as_incomplete": True,
                "chronological_split": False,
                "ranking_or_top3_selection_applied": False,
                "full_end_common_horizon_purge": True,
                "policy_or_top15_derived_conditions_excluded": True,
                "random_split": False,
            },
            "limitations": [
                "Counterfactual entry ranks are alternatives, not simultaneous orders.",
                "Overlapping event horizons are not converted to a one-position ledger.",
                "Per-foot2 expectancy includes unavailable ranks as zero only for event-level conditions; line-specific conditions have no definition when a line is absent.",
                "Boundary events without a next count2 and source-rebuild/target-invalid skipped events are censored from the valid-foot2 denominator.",
                "Existing non-policy condition definitions may themselves have prior research history.",
                "The source CSV has no standalone H1 feature-last-close column; H1 causality relies on the audited source generator contract.",
                "The source CSV records lookback=6 and first/last M5 times but not all six source timestamps; exact six-row membership relies on the source generator contract.",
                "Gap-through LIMIT fills are conservatively recorded at the limit price without price improvement.",
                "When a timeout horizon ends during a known market closure, the last tradable S5 close is used as the timeout mark.",
                (
                    "EUR/USD and AUD/USD yen results are fixed-risk-normalized "
                    "as realized R times risk_yen; no non-causal USD/JPY "
                    "conversion series is used."
                    if pair_name in ("EUR_USD", "AUD_USD")
                    else None
                ),
                "A max-source-rows run is incomplete and must not be used as final evidence."
                if args.max_source_rows is not None
                else None,
            ],
        }
        manifest["limitations"] = [
            value for value in manifest["limitations"] if value is not None
        ]
        if paths["manifest"].exists():
            _archive_file(paths["manifest"])
        _write_json_atomic(paths["manifest"], manifest)

        completion_lines = [
            f"期間: {args.start:%Y-%m-%d} から {args.end:%Y-%m-%d} 未満",
            "出力対象: 全条件・全組み合わせ（順位付けなし）",
            f"処理元候補行: {source_rows_processed}/{source_rows_total}",
            f"entry候補ライン行: {selected_line_rows}",
            f"entry path: {grid_path_rows}",
            f"総当たり設定数: {len(combos)}",
            f"marketable LIMIT除外: {marketable_excluded}",
            f"全期間集計: {paths['aggregate']}",
            f"月別結果: {paths['monthly']}",
            f"経過: {elapsed_minutes:.1f}分",
        ]
        print(f"{pair_name} foot count 2 entry/TP/LC grid complete")
        for line in completion_lines:
            print(f"- {line}")
        _notify(
            "\n".join(
                [
                    f"{pair_name} foot count 2 entry/TP/LC grid 完了",
                    *(f"- {line}" for line in completion_lines),
                ]
            )
        )
        _write_progress(
            paths["progress"],
            args=args,
            status="complete",
            phase="complete",
            started_at=wall_started,
            process_started=process_started,
            source_rows_total=source_rows_total,
            source_rows_processed=min(source_rows_processed, source_rows_total),
            selected_line_rows=selected_line_rows,
            grid_path_rows=grid_path_rows,
        )
        archived_progress = _archive_file(paths["progress"])
        manifest["outputs"]["progress"] = str(archived_progress)
        _write_json_atomic(paths["manifest"], manifest)
        return {**paths, "progress": archived_progress}
    except Exception as error:
        path_writer.abort()
        # Prior generation files were archived before the run, so every live
        # file now belongs to this failed generation and must leave together.
        _archive_generation(paths)
        try:
            _write_progress(
                paths["progress"],
                args=args,
                status="failed",
                phase="failed",
                started_at=wall_started,
                process_started=process_started,
                source_rows_total=source_rows_total,
                source_rows_processed=min(source_rows_processed, source_rows_total),
                selected_line_rows=selected_line_rows,
                grid_path_rows=grid_path_rows,
                error=f"{type(error).__name__}: {error}",
            )
            _archive_file(paths["progress"])
        finally:
            _notify(
                "\n".join(
                    [
                        f"{pair_name} foot count 2 entry/TP/LC grid 異常終了",
                        f"- エラー種別: {type(error).__name__}",
                        f"- 内容: {error}",
                    ]
                )
            )
        raise


def main(
    argv: list[str] | None = None,
    *,
    default_start: dt.datetime = DEFAULT_START,
    default_end: dt.datetime = DEFAULT_END,
    default_pair: str = DEFAULT_PAIR_NAME,
) -> dict[str, Path]:
    args = parse_args(
        argv,
        default_start=default_start,
        default_end=default_end,
        default_pair=default_pair,
    )
    try:
        return run_grid_search(args)
    except Exception as error:
        paths = output_paths(args)
        residual_found = False
        for path in paths.values():
            for residual in (
                path.with_suffix(path.suffix + ".part"),
                path.with_suffix(path.suffix + ".tmp"),
            ):
                if residual.exists():
                    residual_found = True
                    _archive_file(residual)
        if paths["progress"].exists():
            residual_found = True
            _archive_file(paths["progress"])
        if residual_found:
            _notify(
                "\n".join(
                    [
                        f"{_pair_name(args)} foot count 2 entry/TP/LC grid 起動失敗",
                        f"- エラー種別: {type(error).__name__}",
                        f"- 内容: {error}",
                        "- temp/progress: archiveへ移動済み",
                    ]
                )
            )
        raise


if __name__ == "__main__":
    main()
