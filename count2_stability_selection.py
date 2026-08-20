"""Select robust count2 policies without a forced Top15.

This inspection-only stage consumes one completed entry/TP/LC grid for the
selection window.  It never reads following-period prices, never edits live
strategy code, and never fills a quota.  An empty selection is a valid result.

The large path ledger is processed in two bounded passes conceptually: the
aggregate first identifies plausible seeds, then only those seeds and their
one-step Cartesian neighbours are reconstructed from path rows.  Membership
and overlap use decision-time ``conditions_json`` and ``event_id`` only.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import math
import statistics
import time
from collections import defaultdict, deque
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd

import fGeneric as gene
import test_win_point_usd_aud as win_point
import tokens as tk
from count2_target_grid_search import (
    FC2_A_LABELS,
    RATIO_LABELS,
    SHAPE_TIME_LABELS,
    _archive_file,
    _multiplier_tag,
)


VERSION = "count2_stability_selection_v1"
DEFAULT_SELECTION_START = dt.datetime(2023, 7, 30)
DEFAULT_SELECTION_END = dt.datetime(2025, 7, 30)
DEFAULT_FOLLOWING_START = dt.datetime(2025, 7, 30)
DEFAULT_FOLLOWING_END = dt.datetime(2026, 7, 30)
DEFAULT_MAX_DD_R = 20.0
DEFAULT_MIN_NEIGHBOUR_R = -5.0
DEFAULT_READ_CHUNK_SIZE = 5_000
CONDITION_SCOPE = "all_decision_time_grid_conditions_with_ordered_shape_adjacency"

AGGREGATE_COLUMNS = (
    "segment",
    "condition_id",
    "condition_source",
    "condition_field",
    "condition_value",
    "condition_label",
    "entry_candidate_rank",
    "entry_offset_index",
    "entry_offset_range_multiplier",
    "tp_range_multiplier",
    "lc_range_multiplier",
    "completed_count",
    "sum_yen",
    "sum_pips",
    "sum_r",
    "gross_profit_r",
    "gross_loss_r_abs",
    "profit_factor_r",
)


@dataclass(frozen=True, order=True)
class CandidateKey:
    condition_id: str
    entry_rank: int
    offset_index: int
    tp_index: int
    lc_index: int


@dataclass(frozen=True)
class GridSpec:
    pair: str
    offsets: tuple[float, ...]
    tps: tuple[float, ...]
    lcs: tuple[float, ...]
    risk_yen: float

    @property
    def shape(self) -> tuple[int, int, int]:
        return len(self.offsets), len(self.tps), len(self.lcs)

    def coordinate(self, key: CandidateKey) -> tuple[int, int, int]:
        return key.offset_index, key.tp_index, key.lc_index

    def key(
        self,
        condition_id: str,
        entry_rank: int,
        coordinate: tuple[int, int, int],
    ) -> CandidateKey:
        return CandidateKey(condition_id, entry_rank, *coordinate)


@dataclass(frozen=True)
class PeriodWindow:
    period_id: str
    start: pd.Timestamp
    end: pd.Timestamp

    def payload(self) -> dict[str, str]:
        return {
            "period_id": self.period_id,
            "start_inclusive": self.start.isoformat(),
            "end_exclusive": self.end.isoformat(),
        }


@dataclass(frozen=True)
class Outcome:
    exit_ns: int
    result_yen: float
    result_pips: float
    result_r: float


def _periods(start: pd.Timestamp, end: pd.Timestamp) -> tuple[PeriodWindow, ...]:
    boundaries = (
        pd.Timestamp("2023-07-30"),
        pd.Timestamp("2024-01-30"),
        pd.Timestamp("2024-07-30"),
        pd.Timestamp("2025-01-30"),
        pd.Timestamp("2025-07-30"),
    )
    if start != boundaries[0] or end != boundaries[-1]:
        raise ValueError(
            "This stability contract requires selection "
            "[2023-07-30, 2025-07-30)"
        )
    return tuple(
        PeriodWindow(f"P{index + 1}", boundaries[index], boundaries[index + 1])
        for index in range(4)
    )


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, np.generic):
        return _json_safe(value.item())
    if isinstance(value, (pd.Timestamp, dt.datetime, dt.date)):
        return pd.Timestamp(value).isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return str(value)


def _canonical_json(value: Any) -> str:
    return json.dumps(
        _json_safe(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _sha256_payload(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("ascii")).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _fingerprint(path: Path, *, sha256: bool = False) -> dict[str, Any]:
    resolved = Path(path).resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"Required file is missing: {resolved}")
    stat = resolved.stat()
    result: dict[str, Any] = {
        "resolved_path": str(resolved),
        "size": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
    }
    if sha256:
        result["sha256"] = _sha256_file(resolved)
    return result


def _assert_fingerprints(values: Mapping[str, Mapping[str, Any]]) -> None:
    for item in values.values():
        current = _fingerprint(
            Path(str(item["resolved_path"])), sha256="sha256" in item
        )
        if _canonical_json(current) != _canonical_json(item):
            raise RuntimeError(
                f"Input changed during selection: {item['resolved_path']}"
            )


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(_json_safe(payload), ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    temporary.replace(path)


def _write_csv_atomic(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_csv(temporary, index=False, encoding="utf-8-sig")
    temporary.replace(path)


def _archive_paths(paths: Iterable[Path]) -> list[Path]:
    archived: list[Path] = []
    seen: set[Path] = set()
    for raw in paths:
        path = Path(raw)
        for candidate in (
            path,
            path.with_suffix(path.suffix + ".tmp"),
            path.with_suffix(path.suffix + ".part"),
        ):
            if candidate in seen:
                continue
            seen.add(candidate)
            if candidate.exists():
                archived.append(_archive_file(candidate))
    return archived


def _notice(lines: Sequence[str]) -> None:
    message = "\n".join(
        line if line.lstrip().startswith("-") else f"- {line}" for line in lines
    )
    print(message)
    win_point.send_inspection_notice(message)


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "1.0", "yes"}


def _float(value: Any, default: float = math.nan) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _nearest_index(value: Any, values: Sequence[float], label: str) -> int:
    number = _float(value)
    matches = [
        index
        for index, candidate in enumerate(values)
        if math.isclose(number, float(candidate), rel_tol=0.0, abs_tol=1e-9)
    ]
    if len(matches) != 1:
        raise ValueError(f"Unknown {label} multiplier: {value!r}")
    return matches[0]


def cartesian_neighbours(
    coordinate: tuple[int, int, int], shape: tuple[int, int, int]
) -> tuple[tuple[int, int, int], ...]:
    """Return the full one-step Cartesian cube, including its centre."""
    axes = [
        range(max(0, value - 1), min(size, value + 2))
        for value, size in zip(coordinate, shape)
    ]
    return tuple((a, b, c) for a in axes[0] for b in axes[1] for c in axes[2])


def axial_neighbours(
    coordinate: tuple[int, int, int], shape: tuple[int, int, int]
) -> tuple[tuple[int, int, int], ...]:
    result: list[tuple[int, int, int]] = []
    for axis, size in enumerate(shape):
        for delta in (-1, 1):
            values = list(coordinate)
            values[axis] += delta
            if 0 <= values[axis] < size:
                result.append(tuple(values))
    return tuple(result)


def connected_components(
    coordinates: Iterable[tuple[int, int, int]],
    shape: tuple[int, int, int],
) -> list[set[tuple[int, int, int]]]:
    remaining = set(coordinates)
    components: list[set[tuple[int, int, int]]] = []
    while remaining:
        start = min(remaining)
        remaining.remove(start)
        component = {start}
        queue = deque([start])
        while queue:
            current = queue.popleft()
            for neighbour in axial_neighbours(current, shape):
                if neighbour in remaining:
                    remaining.remove(neighbour)
                    component.add(neighbour)
                    queue.append(neighbour)
        components.append(component)
    return components


def component_medoid(
    component: Iterable[tuple[int, int, int]],
) -> tuple[int, int, int]:
    values = sorted(set(component))
    if not values:
        raise ValueError("Cannot choose a medoid from an empty component")

    def score(point: tuple[int, int, int]) -> tuple[int, int, tuple[int, int, int]]:
        distances = [sum(abs(a - b) for a, b in zip(point, other)) for other in values]
        return sum(distances), max(distances), point

    return min(values, key=score)


def jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0.0


RATIO_FIELDS = frozenset(
    {
        "prior_impulse_retrace_ratio_bin",
        "second_range_to_first_ratio_bin",
        "second_body_to_first_ratio_bin",
        "second_recovery_of_first_ratio_bin",
    }
)


def _ordered_labels(field: str) -> tuple[str, ...] | None:
    if field in RATIO_FIELDS:
        return tuple(RATIO_LABELS)
    if field == "age_at_decision_minutes_bin":
        return tuple(SHAPE_TIME_LABELS)
    if field.endswith("_A_bin"):
        return tuple(FC2_A_LABELS)
    return None


def adjacent_condition_ids(condition_id: str) -> tuple[str, ...] | None:
    """Return ordered-bin neighbours; ``None`` means categorical exemption."""
    parts = condition_id.split("::", 2)
    if len(parts) != 3:
        return None
    source, field, value = parts
    labels = _ordered_labels(field)
    if labels is None:
        return None

    def adjacent_values(current: str) -> list[str]:
        if current == "UNDEFINED" or current not in labels:
            return []
        index = labels.index(current)
        return [
            labels[position]
            for position in (index - 1, index + 1)
            if 0 <= position < len(labels)
        ]

    neighbours: list[str] = []
    if source == "M5_FC2_X_H1_PAIR":
        try:
            m5_part, h1_part = value.split("|", 1)
            m5_value = m5_part.removeprefix("M5=")
            h1_value = h1_part.removeprefix("H1=")
        except ValueError:
            return ()
        if m5_value == "UNDEFINED" or h1_value == "UNDEFINED":
            return ()
        for candidate in adjacent_values(m5_value):
            neighbours.append(
                f"{source}::{field}::M5={candidate}|H1={h1_value}"
            )
        for candidate in adjacent_values(h1_value):
            neighbours.append(
                f"{source}::{field}::M5={m5_value}|H1={candidate}"
            )
    else:
        neighbours.extend(
            f"{source}::{field}::{candidate}"
            for candidate in adjacent_values(value)
        )
    return tuple(neighbours)


def _performance(outcomes: Sequence[Outcome]) -> dict[str, Any]:
    if not outcomes:
        return {
            "completed_count": 0,
            "sum_yen": 0.0,
            "sum_pips": 0.0,
            "sum_r": 0.0,
            "gross_profit_r": 0.0,
            "gross_loss_r_abs": 0.0,
            "profit_factor_r": 0.0,
            "profit_factor_r_infinite": False,
            "max_drawdown_r": 0.0,
            "max_drawdown_yen": 0.0,
        }
    ordered = sorted(outcomes, key=lambda item: item.exit_ns)
    rs = np.asarray([item.result_r for item in ordered], dtype=float)
    pips = np.asarray([item.result_pips for item in ordered], dtype=float)
    yen = np.asarray([item.result_yen for item in ordered], dtype=float)
    gross_profit = float(rs[rs > 0].sum())
    gross_loss = float(-rs[rs < 0].sum())
    infinite = gross_loss == 0 and gross_profit > 0

    def drawdown(values: np.ndarray) -> float:
        cumulative = np.cumsum(values)
        running = np.maximum.accumulate(np.maximum(cumulative, 0.0))
        return float(np.max(running - cumulative))

    return {
        "completed_count": int(len(ordered)),
        "sum_yen": float(yen.sum()),
        "sum_pips": float(pips.sum()),
        "sum_r": float(rs.sum()),
        "gross_profit_r": gross_profit,
        "gross_loss_r_abs": gross_loss,
        "profit_factor_r": None if infinite else (gross_profit / gross_loss if gross_loss else 0.0),
        "profit_factor_r_infinite": infinite,
        "max_drawdown_r": drawdown(rs),
        "max_drawdown_yen": drawdown(yen),
    }


def _pf(metrics: Mapping[str, Any]) -> float:
    if metrics.get("profit_factor_r_infinite") is True:
        return math.inf
    return float(metrics.get("profit_factor_r") or 0.0)


def _positive_share(periods: Sequence[Mapping[str, Any]], field: str) -> float:
    positive = [float(item[field]) for item in periods if float(item[field]) > 0]
    return max(positive) / sum(positive) if positive else 1.0


def hard_gate(
    full: Mapping[str, Any],
    periods: Sequence[Mapping[str, Any]],
    *,
    max_dd_r: float,
) -> dict[str, Any]:
    """Apply the complete, predeclared four-period acceptance contract."""
    if len(periods) != 4:
        raise ValueError("Exactly four periods are required")
    reasons: list[str] = []
    for field in ("sum_yen", "sum_pips", "sum_r"):
        if float(full[field]) <= 0:
            reasons.append(f"full_{field}_not_positive")
    positive_periods = sum(
        float(item["sum_pips"]) > 0 and float(item["sum_r"]) > 0
        for item in periods
    )
    if positive_periods < 3:
        reasons.append("positive_pips_and_r_periods_below_3")
    if any(int(item["completed_count"]) < 30 for item in periods):
        reasons.append("period_completed_below_30")
    period_total = sum(int(item["completed_count"]) for item in periods)
    if period_total < 120:
        reasons.append("period_completed_total_below_120")
    if _pf(full) < 1.10:
        reasons.append("full_pf_below_1.10")
    median_pf = statistics.median(_pf(item) for item in periods)
    if median_pf < 1.0:
        reasons.append("period_pf_median_below_1.0")
    leave_one_out: list[dict[str, Any]] = []
    for omitted in range(4):
        row: dict[str, Any] = {"omitted_period_id": periods[omitted]["period_id"]}
        for field in ("sum_yen", "sum_pips", "sum_r"):
            row[field] = sum(
                float(item[field])
                for index, item in enumerate(periods)
                if index != omitted
            )
        row["positive_all"] = all(
            row[field] > 0 for field in ("sum_yen", "sum_pips", "sum_r")
        )
        leave_one_out.append(row)
    if not all(item["positive_all"] for item in leave_one_out):
        reasons.append("leave_one_out_not_all_positive")
    if float(full["max_drawdown_r"]) > max_dd_r:
        reasons.append("max_drawdown_r_exceeds_limit")
    concentration = {
        field: _positive_share(periods, field)
        for field in ("sum_yen", "sum_pips", "sum_r")
    }
    # The user's wording is 50% *or more*, so equality is rejected.
    if any(value >= 0.5 - 1e-12 for value in concentration.values()):
        reasons.append("positive_period_concentration_at_least_50pct")
    return {
        "accepted": not reasons,
        "rejection_reasons": reasons,
        "positive_pips_and_r_periods": positive_periods,
        "period_completed_total": period_total,
        "period_pf_median": None if math.isinf(median_pf) else float(median_pf),
        "period_pf_median_infinite": math.isinf(median_pf),
        "leave_one_out": leave_one_out,
        "positive_period_concentration": concentration,
        "max_dd_r_limit": max_dd_r,
    }


def update_event_memberships(
    memberships: dict[tuple[str, int], set[str]],
    *,
    event_id: str,
    entry_rank: int,
    conditions_json: str,
    allowed_condition_ids: set[str],
) -> None:
    """Update causal overlap sets without accepting any outcome argument."""
    raw = json.loads(conditions_json)
    if not isinstance(raw, list):
        raise ValueError("conditions_json must contain a list")
    for condition_id in set(map(str, raw)).intersection(allowed_condition_ids):
        memberships[(condition_id, entry_rank)].add(event_id)


def _read_header(path: Path) -> set[str]:
    with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
        return set(next(csv.reader(handle)))


def _manifest_outputs(manifest: Mapping[str, Any]) -> dict[str, Path]:
    raw = manifest.get("outputs")
    if not isinstance(raw, Mapping):
        raise ValueError("Grid manifest lacks outputs")
    return {
        str(name): Path(str(path)).resolve()
        for name, path in raw.items()
        if path is not None
    }


def _load_manifest(
    args: argparse.Namespace,
) -> tuple[dict[str, Any], dict[str, Path], GridSpec, dict[str, dict[str, Any]]]:
    path = Path(args.grid_manifest).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Completed grid manifest is missing: {path}")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("status") != "complete":
        raise ValueError("Grid manifest is not complete")
    if manifest.get("pair") != args.pair:
        raise ValueError("Grid manifest pair mismatch")
    if pd.Timestamp(manifest.get("start")) != pd.Timestamp(args.selection_start):
        raise ValueError("Grid manifest selection start mismatch")
    if pd.Timestamp(manifest.get("end")) != pd.Timestamp(args.selection_end):
        raise ValueError("Grid manifest selection end mismatch")
    if manifest.get("max_source_rows") is not None:
        raise ValueError("Development max-source-rows grid cannot be selected")
    if int(manifest.get("source_rows_processed", -1)) != int(
        manifest.get("source_rows_total", -2)
    ):
        raise ValueError("Grid manifest row counts are incomplete")
    if manifest.get("top15_pre_filter_applied") is not False:
        raise ValueError("Grid was prefiltered by Top15")
    safety = manifest.get("future_safety")
    if not isinstance(safety, Mapping) or any(
        safety.get(name) is not True
        for name in (
            "s5_used_only_for_outcome",
            "s5_at_or_after_requested_end_excluded",
            "full_end_common_horizon_purge",
        )
    ):
        raise ValueError("Grid future-safety contract is incomplete")
    outputs = _manifest_outputs(manifest)
    for name in ("aggregate", "paths"):
        if name not in outputs or not outputs[name].is_file():
            raise FileNotFoundError(f"Grid {name} output is missing")
    recorded_manifest = outputs.get("manifest")
    if recorded_manifest is not None and recorded_manifest != path:
        raise ValueError("Grid manifest self-path mismatch")
    try:
        spec = GridSpec(
            pair=args.pair,
            offsets=tuple(float(value) for value in manifest["entry_offset_range_multipliers"]),
            tps=tuple(float(value) for value in manifest["tp_range_multipliers"]),
            lcs=tuple(float(value) for value in manifest["lc_range_multipliers"]),
            risk_yen=float(manifest["risk_yen"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("Grid multiplier/risk contract is malformed") from error
    if (
        not spec.offsets
        or not spec.tps
        or not spec.lcs
        or not math.isfinite(spec.risk_yen)
        or spec.risk_yen <= 0
    ):
        raise ValueError("Grid multiplier/risk contract is invalid")
    fingerprints = {
        "source_grid_manifest": _fingerprint(path, sha256=True),
        "aggregate": _fingerprint(outputs["aggregate"]),
        "paths": _fingerprint(outputs["paths"]),
        "selector_module": _fingerprint(Path(__file__), sha256=True),
    }
    return manifest, outputs, spec, fingerprints


def _key_from_aggregate(row: Mapping[str, Any], spec: GridSpec) -> CandidateKey:
    offset_index = int(float(row["entry_offset_index"]))
    if not 0 <= offset_index < len(spec.offsets):
        raise ValueError(f"Invalid aggregate offset index: {offset_index}")
    offset = _float(row["entry_offset_range_multiplier"])
    if not math.isclose(offset, spec.offsets[offset_index], rel_tol=0.0, abs_tol=1e-9):
        raise ValueError("Aggregate offset index/multiplier mismatch")
    return CandidateKey(
        condition_id=str(row["condition_id"]),
        entry_rank=int(float(row["entry_candidate_rank"])),
        offset_index=offset_index,
        tp_index=_nearest_index(row["tp_range_multiplier"], spec.tps, "TP"),
        lc_index=_nearest_index(row["lc_range_multiplier"], spec.lcs, "LC"),
    )


def _aggregate_payload(row: Mapping[str, Any], key: CandidateKey) -> dict[str, Any]:
    gross_loss = _float(row["gross_loss_r_abs"], 0.0)
    gross_profit = _float(row["gross_profit_r"], 0.0)
    infinite = gross_loss == 0 and gross_profit > 0
    return {
        "key": key,
        "condition_id": key.condition_id,
        "condition_source": str(row["condition_source"]),
        "condition_field": str(row["condition_field"]),
        "condition_value": str(row["condition_value"]),
        "condition_label": str(row.get("condition_label", "")),
        "completed_count": int(round(_float(row["completed_count"], 0.0))),
        "sum_yen": _float(row["sum_yen"], 0.0),
        "sum_pips": _float(row["sum_pips"], 0.0),
        "sum_r": _float(row["sum_r"], 0.0),
        "gross_profit_r": gross_profit,
        "gross_loss_r_abs": gross_loss,
        "profit_factor_r": None if infinite else _float(row["profit_factor_r"], 0.0),
        "profit_factor_r_infinite": infinite,
    }


def _full_prefilter(payload: Mapping[str, Any]) -> bool:
    return (
        int(payload["completed_count"]) >= 120
        and float(payload["sum_yen"]) > 0
        and float(payload["sum_pips"]) > 0
        and float(payload["sum_r"]) > 0
        and _pf(payload) >= 1.10
    )


def _aggregate_chunks(path: Path, chunksize: int) -> Iterable[pd.DataFrame]:
    missing = set(AGGREGATE_COLUMNS).difference(_read_header(path))
    if missing:
        raise ValueError("Aggregate lacks columns: " + ", ".join(sorted(missing)))
    return pd.read_csv(
        path,
        usecols=list(AGGREGATE_COLUMNS),
        chunksize=max(int(chunksize), 5_000),
        low_memory=False,
    )


def _load_aggregate_candidates(
    path: Path,
    spec: GridSpec,
    chunksize: int,
) -> tuple[
    dict[CandidateKey, dict[str, Any]],
    dict[CandidateKey, dict[str, Any]],
]:
    """Load full-pass seeds, then only their Cartesian local neighbourhoods."""
    seeds: dict[CandidateKey, dict[str, Any]] = {}
    for chunk in _aggregate_chunks(path, chunksize):
        # The stability gates apply to every causal condition published by the
        # research grid.  Ordered shape bins receive the extra adjacency gate
        # below; categorical/stair/session/line conditions remain eligible.
        chunk = chunk[chunk["segment"].astype(str).eq("full")]
        for row in chunk.to_dict("records"):
            key = _key_from_aggregate(row, spec)
            payload = _aggregate_payload(row, key)
            if _full_prefilter(payload):
                if key in seeds:
                    raise ValueError(f"Duplicate aggregate seed: {key}")
                seeds[key] = payload
    if not seeds:
        return {}, {}

    wanted: dict[tuple[str, int], set[tuple[int, int, int]]] = defaultdict(set)
    for key in seeds:
        wanted[(key.condition_id, key.entry_rank)].update(
            cartesian_neighbours(spec.coordinate(key), spec.shape)
        )
    neighbours: dict[CandidateKey, dict[str, Any]] = {}
    for chunk in _aggregate_chunks(path, chunksize):
        chunk = chunk[chunk["segment"].astype(str).eq("full")]
        for row in chunk.to_dict("records"):
            prefix = (str(row["condition_id"]), int(float(row["entry_candidate_rank"])))
            coordinates = wanted.get(prefix)
            if not coordinates:
                continue
            key = _key_from_aggregate(row, spec)
            if spec.coordinate(key) not in coordinates:
                continue
            if key in neighbours:
                raise ValueError(f"Duplicate aggregate neighbour: {key}")
            neighbours[key] = _aggregate_payload(row, key)
    missing_seeds = set(seeds).difference(neighbours)
    if missing_seeds:
        raise ValueError(f"Aggregate seeds disappeared on second pass: {len(missing_seeds)}")
    return seeds, neighbours


def _threshold_prefix(kind: str, multiplier: float) -> str:
    return f"{kind}_{_multiplier_tag(multiplier)}A"


def _path_columns(spec: GridSpec) -> tuple[str, ...]:
    columns = [
        "event_id",
        "pair",
        "decision_time",
        "entry_candidate_rank",
        "entry_offset_index",
        "conditions_json",
        "path_status",
        "filled",
        "horizon_complete",
        "common_entry_window_end",
        "common_entry_window_complete",
        "timeout_exit_time",
        "timeout_result_pips",
    ]
    for multiplier in spec.tps:
        prefix = _threshold_prefix("tp", multiplier)
        columns.extend(
            (f"{prefix}_pips", f"{prefix}_reached", f"{prefix}_first_index", f"{prefix}_first_time")
        )
    for multiplier in spec.lcs:
        prefix = _threshold_prefix("lc", multiplier)
        columns.extend(
            (f"{prefix}_pips", f"{prefix}_reached", f"{prefix}_first_index", f"{prefix}_first_time")
        )
    return tuple(columns)


def _period_index(
    decision_time: pd.Timestamp,
    common_end: pd.Timestamp,
    periods: Sequence[PeriodWindow],
) -> int | None:
    for index, period in enumerate(periods):
        if period.start <= decision_time < period.end:
            return index if common_end <= period.end else None
    return None


def _time_ns(value: Any, label: str) -> int:
    timestamp = pd.to_datetime(value, errors="coerce")
    if pd.isna(timestamp):
        raise ValueError(f"Reached outcome lacks {label}")
    return int(pd.Timestamp(timestamp).value)


def _row_outcome(
    row: Mapping[str, Any],
    key: CandidateKey,
    spec: GridSpec,
    pair: gene.CurrencyPair,
    units_cache: dict[float, float],
) -> Outcome | None:
    if not _bool(row.get("filled")):
        return None
    tp_prefix = _threshold_prefix("tp", spec.tps[key.tp_index])
    lc_prefix = _threshold_prefix("lc", spec.lcs[key.lc_index])
    tp_reached = _bool(row.get(f"{tp_prefix}_reached"))
    lc_reached = _bool(row.get(f"{lc_prefix}_reached"))
    sentinel = 2**31 - 1
    tp_index = int(_float(row.get(f"{tp_prefix}_first_index"), -1))
    lc_index = int(_float(row.get(f"{lc_prefix}_first_index"), -1))
    tp_order = tp_index if tp_reached and tp_index >= 0 else sentinel
    lc_order = lc_index if lc_reached and lc_index >= 0 else sentinel
    tp_pips = _float(row.get(f"{tp_prefix}_pips"))
    lc_pips = _float(row.get(f"{lc_prefix}_pips"))
    if not math.isfinite(tp_pips) or not math.isfinite(lc_pips) or tp_pips <= 0 or lc_pips <= 0:
        raise ValueError(f"Invalid effective TP/LC in grid path: {key}")
    if tp_order < sentinel or lc_order < sentinel:
        # LC wins a same-S5 ambiguity, matching the source grid.
        if lc_order <= tp_order:
            result_pips = -lc_pips
            exit_ns = _time_ns(row.get(f"{lc_prefix}_first_time"), "LC time")
        else:
            result_pips = tp_pips
            exit_ns = _time_ns(row.get(f"{tp_prefix}_first_time"), "TP time")
    elif _bool(row.get("horizon_complete")):
        result_pips = _float(row.get("timeout_result_pips"))
        if not math.isfinite(result_pips):
            raise ValueError(f"Complete timeout lacks result pips: {key}")
        exit_ns = _time_ns(row.get("timeout_exit_time"), "timeout time")
    else:
        return None
    result_r = result_pips / lc_pips
    if spec.pair == "USD_JPY":
        cache_key = round(lc_pips, 10)
        units = units_cache.get(cache_key)
        if units is None:
            units = float(
                gene.calculate_units(
                    pair,
                    pair.pips_to_price(lc_pips),
                    risk_yen=spec.risk_yen,
                    rounding_tag="l",
                )
            )
            units_cache[cache_key] = units
        result_yen = result_pips * pair.pip_value * units
    else:
        result_yen = result_r * spec.risk_yen
    return Outcome(exit_ns, float(result_yen), float(result_pips), float(result_r))


def _write_progress(
    path: Path,
    *,
    args: argparse.Namespace,
    started: float,
    phase: str,
    rows_processed: int = 0,
    rows_total: int = 0,
    error: str | None = None,
) -> None:
    percent = 100.0 * rows_processed / rows_total if rows_total else 0.0
    _write_json_atomic(
        path,
        {
            "version": VERSION,
            "status": "failed" if error else "running",
            "phase": phase,
            "pair": args.pair,
            "rows_processed": rows_processed,
            "rows_total": rows_total,
            "progress_percent": round(percent, 3),
            "elapsed_minutes": round((time.monotonic() - started) / 60.0, 2),
            "error": error,
            "updated_at": dt.datetime.now().astimezone(),
        },
    )


def _reconstruct_metrics(
    args: argparse.Namespace,
    path: Path,
    spec: GridSpec,
    periods: Sequence[PeriodWindow],
    target_rows: Mapping[CandidateKey, Mapping[str, Any]],
    progress_path: Path,
    started: float,
    rows_total: int,
) -> tuple[
    dict[CandidateKey, dict[str, Any]],
    dict[CandidateKey, list[dict[str, Any]]],
    dict[tuple[str, int], set[str]],
]:
    columns = _path_columns(spec)
    missing = set(columns).difference(_read_header(path))
    if missing:
        raise ValueError("Grid paths lack columns: " + ", ".join(sorted(missing)))
    keys_by_prefix: dict[tuple[str, int, int], list[CandidateKey]] = defaultdict(list)
    for key in target_rows:
        keys_by_prefix[(key.condition_id, key.entry_rank, key.offset_index)].append(key)
    allowed_ids = {key.condition_id for key in target_rows}
    memberships: dict[tuple[str, int], set[str]] = defaultdict(set)
    full_outcomes: dict[CandidateKey, list[Outcome]] = defaultdict(list)
    period_outcomes: dict[tuple[CandidateKey, int], list[Outcome]] = defaultdict(list)
    units_cache: dict[float, float] = {}
    pair = gene.currency_pair(spec.pair)
    processed = 0
    for chunk in pd.read_csv(
        path,
        usecols=list(columns),
        chunksize=max(int(args.read_chunk_size), 1_000),
        low_memory=False,
    ):
        for row in chunk.to_dict("records"):
            if str(row.get("pair")) != spec.pair:
                raise ValueError("Grid paths contain another pair")
            event_id = str(row["event_id"])
            rank = int(float(row["entry_candidate_rank"]))
            offset_index = int(float(row["entry_offset_index"]))
            update_event_memberships(
                memberships,
                event_id=event_id,
                entry_rank=rank,
                conditions_json=str(row["conditions_json"]),
                allowed_condition_ids=allowed_ids,
            )
            raw_conditions = json.loads(str(row["conditions_json"]))
            matching = set(map(str, raw_conditions)).intersection(allowed_ids)
            if not matching:
                continue
            if not _bool(row.get("common_entry_window_complete")):
                continue
            decision = pd.Timestamp(row["decision_time"])
            common_end = pd.to_datetime(row.get("common_entry_window_end"), errors="coerce")
            if pd.isna(common_end):
                raise ValueError(f"Complete common window lacks end: {event_id}")
            common_end = pd.Timestamp(common_end)
            if not (pd.Timestamp(args.selection_start) <= decision < pd.Timestamp(args.selection_end)):
                raise ValueError(f"Grid path decision is outside selection: {decision}")
            full_safe = common_end <= pd.Timestamp(args.selection_end)
            period_index = _period_index(decision, common_end, periods)
            for condition_id in matching:
                for key in keys_by_prefix.get((condition_id, rank, offset_index), ()):
                    outcome = _row_outcome(row, key, spec, pair, units_cache)
                    if outcome is None:
                        continue
                    if full_safe:
                        full_outcomes[key].append(outcome)
                    if period_index is not None:
                        period_outcomes[(key, period_index)].append(outcome)
        processed += len(chunk)
        if processed == len(chunk) or processed >= rows_total or processed % 25_000 < len(chunk):
            _write_progress(
                progress_path,
                args=args,
                started=started,
                phase="reconstructing_selected_and_neighbour_paths",
                rows_processed=processed,
                rows_total=rows_total,
            )
    full_metrics = {key: _performance(full_outcomes.get(key, ())) for key in target_rows}
    period_metrics: dict[CandidateKey, list[dict[str, Any]]] = {}
    for key in target_rows:
        period_metrics[key] = [
            {
                **period.payload(),
                **_performance(period_outcomes.get((key, index), ())),
            }
            for index, period in enumerate(periods)
        ]
    return full_metrics, period_metrics, memberships


def _close_enough(actual: float, expected: float) -> bool:
    return math.isclose(actual, expected, rel_tol=1e-8, abs_tol=1e-6)


def _reconcile_full(
    aggregate: Mapping[CandidateKey, Mapping[str, Any]],
    reconstructed: Mapping[CandidateKey, Mapping[str, Any]],
) -> None:
    errors: list[str] = []
    for key, expected in aggregate.items():
        actual = reconstructed[key]
        if int(actual["completed_count"]) != int(expected["completed_count"]):
            errors.append(f"{key}: completed")
            continue
        for field in (
            "sum_yen",
            "sum_pips",
            "sum_r",
            "gross_profit_r",
            "gross_loss_r_abs",
        ):
            if not _close_enough(float(actual[field]), float(expected[field])):
                errors.append(f"{key}: {field}")
                break
        if len(errors) >= 10:
            break
    if errors:
        raise ValueError("Path/aggregate reconciliation failed: " + " | ".join(errors))


def _candidate_base(
    key: CandidateKey,
    metadata: Mapping[str, Any],
    spec: GridSpec,
) -> dict[str, Any]:
    return {
        "condition_id": key.condition_id,
        "condition_source": metadata["condition_source"],
        "condition_field": metadata["condition_field"],
        "condition_value": metadata["condition_value"],
        "condition_label": metadata.get("condition_label", ""),
        "entry_candidate_rank": key.entry_rank,
        "entry_offset_index": key.offset_index,
        "entry_offset_range_multiplier": spec.offsets[key.offset_index],
        "tp_index": key.tp_index,
        "tp_range_multiplier": spec.tps[key.tp_index],
        "lc_index": key.lc_index,
        "lc_range_multiplier": spec.lcs[key.lc_index],
    }


def _all_positive(metrics: Mapping[str, Any]) -> bool:
    return all(float(metrics[field]) > 0 for field in ("sum_yen", "sum_pips", "sum_r"))


def _shape_adjacency_pass(
    key: CandidateKey,
    hard_pass_keys: set[CandidateKey],
) -> tuple[bool, list[str]]:
    adjacent_ids = adjacent_condition_ids(key.condition_id)
    if adjacent_ids is None:
        return True, []  # categorical: no meaningful ordered neighbour
    if not adjacent_ids:
        return False, []  # ordered but undefined/malformed/edge without a neighbour
    matches = [
        condition_id
        for condition_id in adjacent_ids
        if CandidateKey(
            condition_id,
            key.entry_rank,
            key.offset_index,
            key.tp_index,
            key.lc_index,
        )
        in hard_pass_keys
    ]
    return bool(matches), matches


def _condition_complexity(condition_id: str) -> tuple[int, int]:
    source = condition_id.split("::", 1)[0]
    return (2 if source == "M5_FC2_X_H1_PAIR" else 1, len(condition_id))


def _safe_name(value: Any) -> str:
    text = "".join(character if str(character).isalnum() else "_" for character in str(value))
    return text.strip("_") or "condition"


def _select_stable_centres(
    *,
    seeds: Mapping[CandidateKey, Mapping[str, Any]],
    neighbours: Mapping[CandidateKey, Mapping[str, Any]],
    full_metrics: Mapping[CandidateKey, Mapping[str, Any]],
    period_metrics: Mapping[CandidateKey, Sequence[Mapping[str, Any]]],
    memberships: Mapping[tuple[str, int], set[str]],
    spec: GridSpec,
    max_dd_r: float,
    min_neighbour_sum_r: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    gates: dict[CandidateKey, dict[str, Any]] = {}
    rejection_reasons: dict[CandidateKey, list[str]] = defaultdict(list)
    for key in seeds:
        gate = hard_gate(full_metrics[key], period_metrics[key], max_dd_r=max_dd_r)
        gates[key] = gate
        rejection_reasons[key].extend(gate["rejection_reasons"])
    hard_pass_keys = {key for key, gate in gates.items() if gate["accepted"]}

    local_details: dict[CandidateKey, dict[str, Any]] = {}
    shape_details: dict[CandidateKey, tuple[bool, list[str]]] = {}
    stable_precomponent: set[CandidateKey] = set()
    for key in hard_pass_keys:
        expected_coordinates = cartesian_neighbours(spec.coordinate(key), spec.shape)
        metrics: list[Mapping[str, Any] | None] = []
        for coordinate in expected_coordinates:
            neighbour_key = spec.key(key.condition_id, key.entry_rank, coordinate)
            metrics.append(full_metrics.get(neighbour_key))
        positive_count = sum(item is not None and _all_positive(item) for item in metrics)
        positive_rate = positive_count / len(expected_coordinates)
        pfs = [_pf(item) if item is not None else 0.0 for item in metrics]
        median_pf = float(statistics.median(pfs))
        worst_r = min(
            (float(item["sum_r"]) if item is not None else -math.inf)
            for item in metrics
        )
        worst_dd = max(
            (float(item["max_drawdown_r"]) if item is not None else math.inf)
            for item in metrics
        )
        local_pass = (
            positive_rate >= 0.70 - 1e-12
            and median_pf >= 1.0
            and worst_r >= min_neighbour_sum_r
            and worst_dd <= max_dd_r
        )
        local_details[key] = {
            "neighbour_count": len(expected_coordinates),
            "positive_neighbour_count": positive_count,
            "positive_neighbour_rate": positive_rate,
            "neighbour_pf_median": None if math.isinf(median_pf) else median_pf,
            "neighbour_pf_median_infinite": math.isinf(median_pf),
            "worst_neighbour_sum_r": None if not math.isfinite(worst_r) else worst_r,
            "worst_neighbour_max_drawdown_r": None if not math.isfinite(worst_dd) else worst_dd,
            "local_plateau_pass": local_pass,
        }
        if not local_pass:
            rejection_reasons[key].append("local_plateau_failed")
            continue
        shape_pass, adjacent_matches = _shape_adjacency_pass(key, hard_pass_keys)
        shape_details[key] = (shape_pass, adjacent_matches)
        if not shape_pass:
            rejection_reasons[key].append("ordered_shape_adjacency_failed")
            continue
        stable_precomponent.add(key)

    component_id_by_key: dict[CandidateKey, str] = {}
    component_size_by_key: dict[CandidateKey, int] = {}
    centres: list[dict[str, Any]] = []
    prefixes = sorted({(key.condition_id, key.entry_rank) for key in stable_precomponent})
    for condition_id, entry_rank in prefixes:
        keys = {
            spec.coordinate(key): key
            for key in stable_precomponent
            if key.condition_id == condition_id and key.entry_rank == entry_rank
        }
        for ordinal, component in enumerate(connected_components(keys, spec.shape), 1):
            component_id = f"{_safe_name(condition_id)}_r{entry_rank}_c{ordinal}"
            for coordinate in component:
                component_id_by_key[keys[coordinate]] = component_id
                component_size_by_key[keys[coordinate]] = len(component)
            if len(component) < 4:
                for coordinate in component:
                    rejection_reasons[keys[coordinate]].append("plateau_component_below_4")
                continue
            medoid_coordinate = component_medoid(component)
            centre_key = keys[medoid_coordinate]
            centres.append(
                {
                    "key": centre_key,
                    "component_id": component_id,
                    "component_size": len(component),
                    "component_coordinates": sorted(component),
                    "min_period_r": min(
                        float(item["sum_r"]) for item in period_metrics[centre_key]
                    ),
                    "min_period_pips": min(
                        float(item["sum_pips"])
                        for item in period_metrics[centre_key]
                    ),
                    "min_period_yen": min(
                        float(item["sum_yen"])
                        for item in period_metrics[centre_key]
                    ),
                    "shape_adjacent_conditions": shape_details[centre_key][1],
                }
            )
            for coordinate in component:
                key = keys[coordinate]
                if key != centre_key:
                    rejection_reasons[key].append("not_plateau_component_medoid")

    # Overlap de-duplication is greedy with the exact requested priority.
    centres.sort(
        key=lambda item: (
            -float(item["min_period_r"]),
            -float(item["min_period_pips"]),
            -float(item["min_period_yen"]),
            -int(item["component_size"]),
            _condition_complexity(item["key"].condition_id),
            item["key"],
        )
    )
    kept: list[dict[str, Any]] = []
    overlap_rows: list[dict[str, Any]] = []
    for item in centres:
        key: CandidateKey = item["key"]
        events = set(memberships.get((key.condition_id, key.entry_rank), set()))
        rejected_by: dict[str, Any] | None = None
        for prior in kept:
            prior_key: CandidateKey = prior["key"]
            prior_events = set(
                memberships.get((prior_key.condition_id, prior_key.entry_rank), set())
            )
            score = jaccard(events, prior_events)
            overlap_rows.append(
                {
                    "left_condition_id": key.condition_id,
                    "left_entry_rank": key.entry_rank,
                    "right_condition_id": prior_key.condition_id,
                    "right_entry_rank": prior_key.entry_rank,
                    "intersection_count": len(events & prior_events),
                    "union_count": len(events | prior_events),
                    "jaccard": score,
                    "rejected": score >= 0.70 - 1e-12,
                }
            )
            if score >= 0.70 - 1e-12:
                rejected_by = prior
                break
        if rejected_by is not None:
            rejected_key: CandidateKey = rejected_by["key"]
            rejection_reasons[key].append(
                f"event_overlap_ge_0.70_with:{rejected_key.condition_id}:rank{rejected_key.entry_rank}"
            )
        else:
            item["event_count"] = len(events)
            kept.append(item)

    selected_rows: list[dict[str, Any]] = []
    for rank, item in enumerate(kept, 1):
        key: CandidateKey = item["key"]
        metadata = seeds[key]
        full = full_metrics[key]
        base = _candidate_base(key, metadata, spec)
        order_name = (
            f"STABLE_{rank:03d}_{_safe_name(metadata['condition_source'])}_"
            f"{_safe_name(metadata['condition_field'])}_r{key.entry_rank}_"
            f"o{key.offset_index}_t{key.tp_index}_l{key.lc_index}"
        )
        selected_rows.append(
            {
                "rank": rank,
                "metric": "stable",
                "order_name": order_name,
                **base,
                **full,
                "worst_period_r": item["min_period_r"],
                "worst_period_pips": item["min_period_pips"],
                "worst_period_yen": item["min_period_yen"],
                "plateau_component_id": item["component_id"],
                "plateau_component_size": item["component_size"],
                "shape_adjacent_conditions": json.dumps(
                    item["shape_adjacent_conditions"], ensure_ascii=False
                ),
                "decision_event_count": item["event_count"],
            }
        )

    plateau_rows: list[dict[str, Any]] = []
    for key in seeds:
        detail = local_details.get(key, {})
        shape_pass, adjacent = shape_details.get(key, (False, []))
        plateau_rows.append(
            {
                **_candidate_base(key, seeds[key], spec),
                "hard_gate_pass": gates[key]["accepted"],
                **detail,
                "shape_adjacency_pass": shape_pass,
                "shape_adjacent_conditions": json.dumps(adjacent, ensure_ascii=False),
                "component_id": component_id_by_key.get(key),
                "component_size": component_size_by_key.get(key, 0),
                "selected": any(item["key"] == key for item in kept),
            }
        )

    rejection_rows: list[dict[str, Any]] = []
    for key in seeds:
        reasons = rejection_reasons[key]
        if not reasons and not any(item["key"] == key for item in kept):
            reasons = ["not_selected"]
        rejection_rows.append(
            {
                **_candidate_base(key, seeds[key], spec),
                "rejected": bool(reasons),
                "rejection_reasons": "|".join(reasons),
            }
        )
    return selected_rows, plateau_rows, rejection_rows, overlap_rows


def _period_rows(
    seeds: Mapping[CandidateKey, Mapping[str, Any]],
    full_metrics: Mapping[CandidateKey, Mapping[str, Any]],
    period_metrics: Mapping[CandidateKey, Sequence[Mapping[str, Any]]],
    spec: GridSpec,
    max_dd_r: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key, metadata in seeds.items():
        gate = hard_gate(full_metrics[key], period_metrics[key], max_dd_r=max_dd_r)
        for period in period_metrics[key]:
            rows.append(
                {
                    **_candidate_base(key, metadata, spec),
                    **period,
                    "candidate_hard_gate_pass": gate["accepted"],
                }
            )
    return rows


def _output_paths(args: argparse.Namespace) -> dict[str, Path]:
    prefix = (
        f"{VERSION}_{args.pair}_{args.selection_start:%Y%m%d}_"
        f"{args.selection_end:%Y%m%d}_to_{args.following_end:%Y%m%d}"
    )
    folder = Path(args.output_dir)
    return {
        "period_metrics": folder / f"{prefix}_period_metrics.csv",
        "plateau": folder / f"{prefix}_plateau.csv",
        "rejections": folder / f"{prefix}_rejections.csv",
        "overlap": folder / f"{prefix}_overlap.csv",
        "selected": folder / f"{prefix}_selected.csv",
        "artifact": folder / f"{prefix}_artifact.json",
        "progress": folder / f"{prefix}_progress.json",
    }


def _artifact_payload(
    *,
    args: argparse.Namespace,
    periods: Sequence[PeriodWindow],
    manifest_path: Path,
    selected_rows: Sequence[Mapping[str, Any]],
    fingerprints: Mapping[str, Mapping[str, Any]],
    outputs: Mapping[str, Path],
    counts: Mapping[str, int],
) -> dict[str, Any]:
    selection_rules = {
        "full_yen_pips_r_positive": True,
        "positive_pips_and_r_periods_min": 3,
        "completed_per_period_min": 30,
        "completed_four_period_total_min": 120,
        "full_profit_factor_r_min": 1.10,
        "period_profit_factor_r_median_min": 1.0,
        "leave_one_period_out_yen_pips_r_positive": True,
        "max_dd_r": float(args.max_dd_r),
        "positive_period_concentration_strictly_below": 0.50,
        "local_cartesian_positive_rate_min": 0.70,
        "local_pf_median_min": 1.0,
        "local_worst_sum_r_min": float(args.min_neighbour_sum_r),
        "plateau_component_min": 4,
        "overlap_jaccard_reject_at_or_above": 0.70,
        "forced_selection_count": None,
    }
    selection_section = {
        "start_inclusive": pd.Timestamp(args.selection_start),
        "end_exclusive": pd.Timestamp(args.selection_end),
        "periods": [period.payload() for period in periods],
    }
    following_section = {
        "start_inclusive": pd.Timestamp(args.following_start),
        "end_exclusive": pd.Timestamp(args.following_end),
        "read_during_selection": False,
    }
    policies = [
        {
            "rank": int(row["rank"]),
            "metric": "stable",
            "order_name": str(row["order_name"]),
            "condition_id": str(row["condition_id"]),
            "entry_candidate_rank": int(row["entry_candidate_rank"]),
            "entry_offset_range_multiplier": float(row["entry_offset_range_multiplier"]),
            "tp_range_multiplier": float(row["tp_range_multiplier"]),
            "lc_range_multiplier": float(row["lc_range_multiplier"]),
        }
        for row in selected_rows
    ]
    config = {
        "version": VERSION,
        "pair": args.pair,
        "condition_scope": CONDITION_SCOPE,
        "selection": selection_section,
        "following": following_section,
        "selection_rules": selection_rules,
        "duplicate_threshold_pips": 3.0,
        "source_grid_manifest": str(manifest_path.resolve()),
    }
    return {
        "version": VERSION,
        "status": "complete",
        "complete": True,
        "pair": args.pair,
        "selection": selection_section,
        "following": following_section,
        "source_grid_manifest": str(manifest_path.resolve()),
        "condition_scope": CONDITION_SCOPE,
        "selection_rules": selection_rules,
        "config": config,
        "config_sha256": _sha256_payload(config),
        "selected_count": len(policies),
        "selected_policies": policies,
        "counts": dict(counts),
        "fingerprints": dict(fingerprints),
        "outputs": {name: str(path.resolve()) for name, path in outputs.items()},
        "future_safety": {
            "selection_and_following_non_overlapping": True,
            "following_data_read": False,
            "decision_membership_uses_conditions_json_only": True,
            "overlap_uses_decision_event_id_only": True,
            "outcome_fields_not_used_for_membership": True,
            "period_end_common_horizon_purge": True,
            "half_open_windows": True,
            "top15_forced": False,
            "live_code_modified": False,
        },
        "created_at": dt.datetime.now().astimezone(),
    }


def run(args: argparse.Namespace) -> dict[str, Path]:
    periods = _periods(pd.Timestamp(args.selection_start), pd.Timestamp(args.selection_end))
    paths = _output_paths(args)
    Path(args.output_dir).mkdir(parents=True, exist_ok=True)
    _archive_paths(paths.values())
    started = time.monotonic()
    _notice(
        [
            f"@everyone {args.pair} count2 stability selector 開始",
            f"選定期間: {args.selection_start:%Y-%m-%d} 以上～{args.selection_end:%Y-%m-%d} 未満",
            "Top15強制なし・合格件数だけ採用・0件も正常",
            "4期間gate・パラメータ台地・形状隣接・event重複を評価",
            "following期間のデータは読みません",
        ]
    )
    try:
        _write_progress(paths["progress"], args=args, started=started, phase="validating_grid")
        manifest, grid_outputs, spec, fingerprints = _load_manifest(args)
        seeds, neighbours = _load_aggregate_candidates(
            grid_outputs["aggregate"], spec, args.read_chunk_size
        )
        _write_progress(
            paths["progress"],
            args=args,
            started=started,
            phase="aggregate_prefilter_complete",
            rows_processed=len(seeds),
            rows_total=len(seeds),
        )
        if neighbours:
            full_metrics, period_metrics, memberships = _reconstruct_metrics(
                args,
                grid_outputs["paths"],
                spec,
                periods,
                neighbours,
                paths["progress"],
                started,
                int(manifest.get("grid_path_rows", 0)),
            )
            _reconcile_full(neighbours, full_metrics)
        else:
            full_metrics, period_metrics, memberships = {}, {}, {}
        selected, plateau, rejections, overlaps = _select_stable_centres(
            seeds=seeds,
            neighbours=neighbours,
            full_metrics=full_metrics,
            period_metrics=period_metrics,
            memberships=memberships,
            spec=spec,
            max_dd_r=float(args.max_dd_r),
            min_neighbour_sum_r=float(args.min_neighbour_sum_r),
        )
        period_rows = _period_rows(
            seeds, full_metrics, period_metrics, spec, float(args.max_dd_r)
        )
        _assert_fingerprints(fingerprints)
        _write_csv_atomic(pd.DataFrame(period_rows), paths["period_metrics"])
        _write_csv_atomic(pd.DataFrame(plateau), paths["plateau"])
        _write_csv_atomic(pd.DataFrame(rejections), paths["rejections"])
        _write_csv_atomic(pd.DataFrame(overlaps), paths["overlap"])
        _write_csv_atomic(pd.DataFrame(selected), paths["selected"])
        _write_progress(
            paths["progress"],
            args=args,
            started=started,
            phase="complete",
            rows_processed=int(manifest.get("grid_path_rows", 0)),
            rows_total=int(manifest.get("grid_path_rows", 0)),
        )
        archived_progress = _archive_file(paths["progress"])
        paths["progress"] = archived_progress
        artifact = _artifact_payload(
            args=args,
            periods=periods,
            manifest_path=Path(args.grid_manifest),
            selected_rows=selected,
            fingerprints=fingerprints,
            outputs=paths,
            counts={
                "full_prefilter_seeds": len(seeds),
                "reconstructed_seed_and_neighbour_points": len(neighbours),
                "plateau_rows": len(plateau),
                "pre_dedup_centres": len(selected)
                + sum(
                    "event_overlap_ge_0.70_with:" in str(
                        row.get("rejection_reasons", "")
                    )
                    for row in rejections
                ),
                "selected": len(selected),
            },
        )
        _write_json_atomic(paths["artifact"], artifact)
        lines = [
            f"@everyone {args.pair} count2 stability selector 完了",
            f"全期間prefilter: {len(seeds)}点",
            f"周辺を含む復元点: {len(neighbours)}点",
            f"最終採用: {len(selected)}件（Top15補充なし）",
        ]
        if selected:
            for row in selected:
                lines.append(
                    f"採用{row['rank']}: {row['condition_id']}, rank{row['entry_candidate_rank']}, "
                    f"offset {row['entry_offset_range_multiplier']:+g}A, "
                    f"TP {row['tp_range_multiplier']:g}A, LC {row['lc_range_multiplier']:g}A, "
                    f"2年 {row['sum_yen']:+,.0f}円 / {row['sum_pips']:+.2f}pips / {row['sum_r']:+.2f}R, "
                    f"PF {_pf(row):.3f}, DD {row['max_drawdown_r']:.2f}R"
                )
        else:
            lines.append("採用条件なし: lifecycle/followingは0注文として継続可能")
        lines.append(f"selection artifact: {paths['artifact']}")
        _notice(lines)
        return {name: Path(path).resolve() for name, path in paths.items()}
    except Exception as error:
        try:
            _write_progress(
                paths["progress"],
                args=args,
                started=started,
                phase="failed",
                error=f"{type(error).__name__}: {error}",
            )
        finally:
            _archive_paths(paths.values())
        _notice(
            [
                f"@everyone {args.pair} count2 stability selector 失敗",
                f"エラー種別: {type(error).__name__}",
                f"内容: {error}",
                "final/temp/progressはarchiveへ移動済み",
            ]
        )
        raise


def _parse_datetime(value: str, option: str, parser: argparse.ArgumentParser) -> dt.datetime:
    try:
        return pd.Timestamp(value).to_pydatetime()
    except (TypeError, ValueError) as error:
        parser.error(f"{option} is invalid: {error}")


def parse_args(
    argv: list[str] | None = None,
    *,
    default_pair: str = "USD_JPY",
    default_selection_start: dt.datetime = DEFAULT_SELECTION_START,
    default_selection_end: dt.datetime = DEFAULT_SELECTION_END,
    default_following_start: dt.datetime = DEFAULT_FOLLOWING_START,
    default_following_end: dt.datetime = DEFAULT_FOLLOWING_END,
) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Select stable count2 regions without a forced Top15"
    )
    parser.add_argument("--pair", default=default_pair, choices=tuple(gene.CURRENCY_PAIRS))
    parser.add_argument("--selection-start", default=default_selection_start.isoformat(" "))
    parser.add_argument("--selection-end", default=default_selection_end.isoformat(" "))
    parser.add_argument("--following-start", default=default_following_start.isoformat(" "))
    parser.add_argument("--following-end", default=default_following_end.isoformat(" "))
    parser.add_argument("--grid-manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path(tk.folder_path))
    parser.add_argument("--max-dd-r", type=float, default=DEFAULT_MAX_DD_R)
    parser.add_argument(
        "--min-neighbour-sum-r", type=float, default=DEFAULT_MIN_NEIGHBOUR_R
    )
    parser.add_argument("--read-chunk-size", type=int, default=DEFAULT_READ_CHUNK_SIZE)
    args = parser.parse_args(argv)
    for field in ("selection_start", "selection_end", "following_start", "following_end"):
        setattr(
            args,
            field,
            _parse_datetime(getattr(args, field), f"--{field.replace('_', '-')}", parser),
        )
    if args.selection_start >= args.selection_end:
        parser.error("--selection-start must be earlier than --selection-end")
    if args.selection_end != args.following_start:
        parser.error("--selection-end must equal --following-start")
    if args.following_start >= args.following_end:
        parser.error("--following-start must be earlier than --following-end")
    if not math.isfinite(args.max_dd_r) or args.max_dd_r <= 0:
        parser.error("--max-dd-r must be finite and positive")
    if not math.isfinite(args.min_neighbour_sum_r) or args.min_neighbour_sum_r >= 0:
        parser.error("--min-neighbour-sum-r must be finite and negative")
    if args.read_chunk_size <= 0:
        parser.error("--read-chunk-size must be positive")
    args.output_dir = Path(args.output_dir).resolve()
    args.grid_manifest = Path(args.grid_manifest).resolve()
    return args


def main(
    argv: list[str] | None = None,
    *,
    default_pair: str = "USD_JPY",
    default_selection_start: dt.datetime = DEFAULT_SELECTION_START,
    default_selection_end: dt.datetime = DEFAULT_SELECTION_END,
    default_following_start: dt.datetime = DEFAULT_FOLLOWING_START,
    default_following_end: dt.datetime = DEFAULT_FOLLOWING_END,
) -> dict[str, Path]:
    return run(
        parse_args(
            argv,
            default_pair=default_pair,
            default_selection_start=default_selection_start,
            default_selection_end=default_selection_end,
            default_following_start=default_following_start,
            default_following_end=default_following_end,
        )
    )


if __name__ == "__main__":
    main()
