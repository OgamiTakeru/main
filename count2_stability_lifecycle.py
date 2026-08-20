"""Fixed-policy lifecycle A/B training and following replay for count2.

This module is inspection-only.  It consumes the completed stability-selection
artifact, never edits a live profile, and keeps the two chronological roles
strictly separate:

* ``train`` screens every grid-stable condition through the full prior-two-year
  portfolio lifecycle under A and B, replays each gate-passing subset, and
  freezes at most one condition-set/management combination;
* ``following`` replays both frozen A/B methods for diagnosis, but preserves
  the training winner (including ``None``) and never re-selects on following
  results.

All windows are half-open.  Candidate features are read from the causal
resistance-sweep ledger; S5 is used only after each decision by the existing
portfolio lifecycle engine.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import math
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd

import fGeneric as gene
import test_win_point_usd_aud as win_point
import tokens as tk
from count2_prior2y_oos_replay import (
    Policy,
    STABILITY_LC_CANDIDATE_A,
    STABILITY_LC_CANDIDATE_B,
    STABILITY_LC_POLICY_BY_CANDIDATE,
    STABILITY_LC_PROFIT_LOCK_RATIO,
    STABILITY_LC_TRADE_TIMEOUT_MIN,
    _validate_s5_timeline,
    _validate_source_headers,
    build_intents,
    load_event_times,
    replay_metric,
    stability_lc_contract_from_payload,
    stability_lc_contract_payload,
)
from count2_target_grid_search import (
    _archive_file,
    _load_typed_s5_inspector,
    _s5_coverage_errors,
)


VERSION = "count2_stability_lifecycle_v1"
TRAIN_ARTIFACT_VERSION = "count2_stability_lifecycle_train_v1"
FOLLOWING_RESULT_VERSION = "count2_stability_lifecycle_following_v1"
DEFAULT_SELECTION_START = dt.datetime(2023, 7, 30)
DEFAULT_SELECTION_END = dt.datetime(2025, 7, 30)
DEFAULT_FOLLOWING_START = dt.datetime(2025, 7, 30)
DEFAULT_FOLLOWING_END = dt.datetime(2026, 7, 30)
DEFAULT_MAX_DD_R = 20.0
DEFAULT_DUPLICATE_THRESHOLD_PIPS = 3.0

POLICY_FIELD_ALIASES: Mapping[str, tuple[str, ...]] = {
    "rank": ("rank", "selection_rank", "policy_rank"),
    "metric": ("metric", "ranking_metric"),
    "order_name": ("order_name", "name", "order"),
    "condition_id": ("condition_id", "condition"),
    "entry_rank": ("entry_rank", "entry_candidate_rank", "distance_rank"),
    "offset_multiplier": (
        "offset_multiplier",
        "entry_offset_range_multiplier",
        "entry_offset_multiplier",
    ),
    "tp_multiplier": ("tp_multiplier", "tp_range_multiplier"),
    "lc_multiplier": ("lc_multiplier", "lc_range_multiplier"),
}

TRADE_COLUMNS = (
    "event_id",
    "decision_time",
    "order_name",
    "policy_rank",
    "condition_id",
    "entry_rank",
    "direction",
    "entry_price",
    "fill_time",
    "exit_time",
    "exit_price",
    "result_type",
    "result_pips",
    "result_r",
    "result_yen",
    "tp_pips",
    "lc_pips",
    "management_policy",
    "cumulative_yen",
)


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
class SelectionContract:
    pair: str
    selection_start: pd.Timestamp
    selection_end: pd.Timestamp
    following_start: pd.Timestamp
    following_end: pd.Timestamp
    periods: tuple[PeriodWindow, ...]
    policies: tuple[Policy, ...]
    max_dd_r: float
    duplicate_threshold_pips: float
    grid_manifest_path: Path
    artifact_path: Path
    artifact: Mapping[str, Any]


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


def _canonical_json(payload: Any) -> str:
    return json.dumps(
        _json_safe(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _sha256_payload(payload: Any) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("ascii")).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _file_fingerprint(path: Path, *, include_sha256: bool = False) -> dict[str, Any]:
    resolved = Path(path).resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"Required file is missing: {resolved}")
    stat = resolved.stat()
    result: dict[str, Any] = {
        "resolved_path": str(resolved),
        "size": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
    }
    if include_sha256:
        result["sha256"] = _sha256_file(resolved)
    return result


def _assert_fingerprint(fingerprint: Mapping[str, Any]) -> None:
    if not isinstance(fingerprint, Mapping):
        raise ValueError("Frozen source fingerprint must be a mapping")
    path = Path(str(fingerprint.get("resolved_path", "")))
    current = _file_fingerprint(path, include_sha256="sha256" in fingerprint)
    if _canonical_json(current) != _canonical_json(fingerprint):
        raise ValueError(f"Frozen source fingerprint changed: {path}")


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
    for raw_path in paths:
        path = Path(raw_path)
        for candidate in (path, path.with_suffix(path.suffix + ".tmp")):
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


def _first(mapping: Mapping[str, Any], names: Sequence[str], default: Any = None) -> Any:
    if not isinstance(mapping, Mapping):
        return default
    for name in names:
        if name in mapping and mapping[name] is not None:
            return mapping[name]
    return default


def _timestamp(value: Any, label: str) -> pd.Timestamp:
    try:
        result = pd.Timestamp(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"Invalid {label}: {value!r}") from error
    if pd.isna(result):
        raise ValueError(f"Invalid {label}: {value!r}")
    if result.tzinfo is not None:
        result = result.tz_convert(None)
    return result


def _window_from_artifact(
    artifact: Mapping[str, Any],
    name: str,
) -> tuple[pd.Timestamp, pd.Timestamp]:
    section = artifact.get(name)
    if isinstance(section, Mapping):
        start = _first(section, ("start_inclusive", "start", f"{name}_start"))
        end = _first(section, ("end_exclusive", "end", f"{name}_end"))
    else:
        aliases = (name, "train") if name == "selection" else (name, "oos")
        start = _first(
            artifact,
            tuple(f"{alias}_start" for alias in aliases)
            + tuple(f"{alias}_start_inclusive" for alias in aliases),
        )
        end = _first(
            artifact,
            tuple(f"{alias}_end" for alias in aliases)
            + tuple(f"{alias}_end_exclusive" for alias in aliases),
        )
    return _timestamp(start, f"{name} start"), _timestamp(end, f"{name} end")


def _default_four_periods(start: pd.Timestamp, end: pd.Timestamp) -> tuple[PeriodWindow, ...]:
    expected = (
        pd.Timestamp("2023-07-30"),
        pd.Timestamp("2024-01-30"),
        pd.Timestamp("2024-07-30"),
        pd.Timestamp("2025-01-30"),
        pd.Timestamp("2025-07-30"),
    )
    if start != expected[0] or end != expected[-1]:
        raise ValueError(
            "Selection artifact must contain four explicit stability periods "
            "outside the canonical 2023-07-30--2025-07-30 window"
        )
    return tuple(
        PeriodWindow(f"P{index + 1}", expected[index], expected[index + 1])
        for index in range(4)
    )


def _periods_from_artifact(
    artifact: Mapping[str, Any],
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> tuple[PeriodWindow, ...]:
    selection = artifact.get("selection")
    raw_periods = selection.get("periods") if isinstance(selection, Mapping) else None
    if raw_periods is None:
        raw_periods = _first(artifact, ("periods", "stability_periods"))
    if raw_periods is None:
        return _default_four_periods(start, end)
    if not isinstance(raw_periods, list) or len(raw_periods) != 4:
        raise ValueError("Selection artifact must define exactly four periods")
    periods: list[PeriodWindow] = []
    for index, raw in enumerate(raw_periods):
        if not isinstance(raw, Mapping):
            raise ValueError("Each selection period must be a mapping")
        period_start = _timestamp(
            _first(raw, ("start_inclusive", "start")), f"period {index + 1} start"
        )
        period_end = _timestamp(
            _first(raw, ("end_exclusive", "end")), f"period {index + 1} end"
        )
        period_id = str(_first(raw, ("period_id", "id", "name"), f"P{index + 1}"))
        periods.append(PeriodWindow(period_id, period_start, period_end))
    if periods[0].start != start or periods[-1].end != end:
        raise ValueError("Four selection periods do not cover the full selection window")
    for previous, following in zip(periods, periods[1:]):
        if previous.end != following.start:
            raise ValueError("Four selection periods must be contiguous and non-overlapping")
    if any(period.start >= period.end for period in periods):
        raise ValueError("Each selection period must have positive duration")
    if len({period.period_id for period in periods}) != 4:
        raise ValueError("Selection period identifiers must be unique")
    return tuple(periods)


def _policy_value(payload: Mapping[str, Any], field: str, default: Any = None) -> Any:
    return _first(payload, POLICY_FIELD_ALIASES[field], default)


def _policy_from_payload(payload: Mapping[str, Any], ordinal: int) -> Policy:
    if not isinstance(payload, Mapping):
        raise ValueError("Every selected policy must be a mapping")
    try:
        rank = int(_policy_value(payload, "rank", ordinal))
        entry_rank = int(_policy_value(payload, "entry_rank"))
        offset = float(_policy_value(payload, "offset_multiplier"))
        tp = float(_policy_value(payload, "tp_multiplier"))
        lc = float(_policy_value(payload, "lc_multiplier"))
    except (TypeError, ValueError) as error:
        raise ValueError(f"Selected policy {ordinal} has malformed numeric fields") from error
    metric = str(_policy_value(payload, "metric", "stable"))
    order_name = str(_policy_value(payload, "order_name", "")).strip()
    condition_id = str(_policy_value(payload, "condition_id", "")).strip()
    if rank <= 0 or entry_rank not in (1, 2, 3):
        raise ValueError(f"Selected policy {ordinal} has an invalid rank")
    if not order_name or not condition_id:
        raise ValueError(f"Selected policy {ordinal} lacks identity")
    if not all(math.isfinite(value) for value in (offset, tp, lc)) or tp <= 0 or lc <= 0:
        raise ValueError(f"Selected policy {ordinal} has invalid entry/TP/LC")
    return Policy(
        rank=rank,
        metric=metric,
        order_name=order_name,
        condition_id=condition_id,
        entry_rank=entry_rank,
        offset_multiplier=offset,
        tp_multiplier=tp,
        lc_multiplier=lc,
    )


def _raw_selected_policies(artifact: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw = _first(artifact, ("selected_policies", "policies", "adopted_policies"), [])
    if isinstance(raw, Mapping):
        for key in ("stable", "selected", "all", "policies", "accepted"):
            if isinstance(raw.get(key), list):
                raw = raw[key]
                break
        else:
            lists = [value for value in raw.values() if isinstance(value, list)]
            if len(lists) == 1:
                raw = lists[0]
    if not isinstance(raw, list):
        raise ValueError("Selection artifact selected_policies must be a list")
    return raw


def _manifest_path_from_artifact(
    artifact: Mapping[str, Any], artifact_path: Path
) -> Path:
    raw = _first(
        artifact,
        ("source_grid_manifest", "grid_manifest", "source_manifest"),
    )
    if isinstance(raw, Mapping):
        raw = _first(raw, ("resolved_path", "path", "manifest"))
    if raw is None:
        fingerprints = artifact.get("fingerprints")
        if isinstance(fingerprints, Mapping):
            raw = _first(
                fingerprints,
                ("source_grid_manifest", "grid_manifest", "source_manifest"),
            )
            if isinstance(raw, Mapping):
                raw = _first(raw, ("resolved_path", "path"))
    if raw is None:
        for section_name in ("source", "sources", "inputs"):
            section = artifact.get(section_name)
            if not isinstance(section, Mapping):
                continue
            raw = _first(
                section,
                ("source_grid_manifest", "grid_manifest", "source_manifest"),
            )
            if isinstance(raw, Mapping):
                raw = _first(raw, ("resolved_path", "path", "manifest"))
            if raw is not None:
                break
    if raw is None:
        raise ValueError("Selection artifact lacks source_grid_manifest")
    path = Path(str(raw))
    if not path.is_absolute():
        path = artifact_path.parent / path
    return path.resolve()


def _validate_optional_config_hash(artifact: Mapping[str, Any]) -> None:
    if "config_sha256" not in artifact:
        return
    config = artifact.get("config")
    if not isinstance(config, Mapping):
        raise ValueError("Selection config_sha256 exists without a config mapping")
    if _sha256_payload(config) != artifact.get("config_sha256"):
        raise ValueError("Selection artifact config SHA256 mismatch")


def load_selection_contract(path: Path) -> SelectionContract:
    artifact_path = Path(path).resolve()
    if not artifact_path.is_file():
        raise FileNotFoundError(f"Completed stability selection artifact is missing: {path}")
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    if not isinstance(artifact, Mapping):
        raise ValueError("Selection artifact root must be a mapping")
    if artifact.get("status") != "complete":
        raise ValueError("Selection artifact status is not complete")
    _validate_optional_config_hash(artifact)
    pair = str(artifact.get("pair", ""))
    if pair not in gene.CURRENCY_PAIRS:
        raise ValueError(f"Selection artifact pair is invalid: {pair!r}")
    selection_start, selection_end = _window_from_artifact(artifact, "selection")
    following_start, following_end = _window_from_artifact(artifact, "following")
    if selection_start >= selection_end or following_start >= following_end:
        raise ValueError("Selection/following windows must have positive duration")
    if selection_end != following_start:
        raise ValueError("Selection end must equal following start")
    periods = _periods_from_artifact(artifact, selection_start, selection_end)
    policies = tuple(
        sorted(
            (
                _policy_from_payload(payload, ordinal)
                for ordinal, payload in enumerate(_raw_selected_policies(artifact), 1)
            ),
            key=lambda item: item.rank,
        )
    )
    identities = [(item.order_name, item.condition_id) for item in policies]
    if len(identities) != len(set(identities)):
        raise ValueError("Selection artifact contains duplicate policy identities")
    if len({item.rank for item in policies}) != len(policies):
        raise ValueError("Selection artifact contains duplicate policy ranks")
    config = artifact.get("config") if isinstance(artifact.get("config"), Mapping) else {}
    rule_candidates = (
        artifact.get("selection_rules"),
        artifact.get("gates"),
        config.get("selection_rules") if isinstance(config, Mapping) else None,
        config.get("gates") if isinstance(config, Mapping) else None,
        config,
        artifact,
    )
    raw_max_dd: Any = None
    for candidate_rules in rule_candidates:
        raw_max_dd = _first(
            candidate_rules,
            ("max_dd_r", "maximum_drawdown_r", "max_drawdown_r"),
        )
        if raw_max_dd is not None:
            break
    if raw_max_dd is None:
        raw_max_dd = DEFAULT_MAX_DD_R
    settings = artifact.get("settings")
    if not isinstance(settings, Mapping) and isinstance(config, Mapping):
        settings = config.get("settings")
    raw_duplicate = _first(
        settings if isinstance(settings, Mapping) else config,
        ("duplicate_threshold_pips",),
        DEFAULT_DUPLICATE_THRESHOLD_PIPS,
    )
    try:
        max_dd_r = float(raw_max_dd)
        duplicate_threshold = float(raw_duplicate)
    except (TypeError, ValueError) as error:
        raise ValueError("Selection risk/duplicate settings are malformed") from error
    if not math.isfinite(max_dd_r) or max_dd_r <= 0:
        raise ValueError("Selection max_dd_r must be finite and positive")
    if not math.isfinite(duplicate_threshold) or duplicate_threshold <= 0:
        raise ValueError("Selection duplicate threshold must be finite and positive")
    return SelectionContract(
        pair=pair,
        selection_start=selection_start,
        selection_end=selection_end,
        following_start=following_start,
        following_end=following_end,
        periods=periods,
        policies=policies,
        max_dd_r=max_dd_r,
        duplicate_threshold_pips=duplicate_threshold,
        grid_manifest_path=_manifest_path_from_artifact(artifact, artifact_path),
        artifact_path=artifact_path,
        artifact=artifact,
    )


def _load_grid_manifest(
    path: Path,
    *,
    pair: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    frozen_settings: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    resolved = Path(path).resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"Completed grid manifest is missing: {resolved}")
    manifest = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("status") != "complete":
        raise ValueError("Grid manifest is not complete")
    if manifest.get("pair") != pair:
        raise ValueError("Grid manifest pair mismatch")
    if _timestamp(manifest.get("start"), "grid start") != start or _timestamp(
        manifest.get("end"), "grid end"
    ) != end:
        raise ValueError("Grid manifest boundary mismatch")
    for key in ("spread_pips", "min_target_pips", "risk_yen"):
        try:
            value = float(manifest[key])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"Grid manifest setting is invalid: {key}") from error
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"Grid manifest setting must be positive: {key}")
        if frozen_settings is not None and not math.isclose(
            value, float(frozen_settings[key]), rel_tol=0.0, abs_tol=1e-12
        ):
            raise ValueError(f"Following grid changed frozen setting: {key}")
    safety = manifest.get("future_safety")
    if not isinstance(safety, Mapping) or any(
        safety.get(key) is not True
        for key in (
            "s5_used_only_for_outcome",
            "s5_at_or_after_requested_end_excluded",
        )
    ):
        raise ValueError("Grid manifest future-safety contract is incomplete")
    manifest["_resolved_path"] = str(resolved)
    return manifest


def _source_paths(manifest: Mapping[str, Any]) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for key in ("source_candidates", "source_events", "s5_cache"):
        raw = manifest.get(key)
        if not raw:
            raise ValueError(f"Grid manifest lacks {key}")
        path = Path(str(raw)).resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Grid source is missing: {path}")
        result[key] = path
    stat_keys = {
        "source_candidates": "source_candidates_stat",
        "source_events": "source_events_stat",
        "s5_cache": "s5_cache_stat",
    }
    for source_key, stat_key in stat_keys.items():
        expected = manifest.get(stat_key)
        if not isinstance(expected, Mapping):
            continue
        actual_stat = result[source_key].stat()
        if int(expected.get("size", -1)) != int(actual_stat.st_size) or int(
            expected.get("mtime_ns", -1)
        ) != int(actual_stat.st_mtime_ns):
            raise ValueError(f"Grid source changed after manifest completion: {result[source_key]}")
    return result


def _discover_grid_manifest(
    folder: Path,
    pair: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    frozen_settings: Mapping[str, Any],
) -> Path:
    pattern = (
        f"count2_target_grid_manifest_{pair}_{start:%Y%m%d}_{end:%Y%m%d}_*.json"
    )
    matches: list[Path] = []
    for path in Path(folder).glob(pattern):
        try:
            manifest = _load_grid_manifest(
                path,
                pair=pair,
                start=start,
                end=end,
                frozen_settings=frozen_settings,
            )
            # A manifest whose source ledger was regenerated is not a valid
            # immutable hand-off.  Skip it here so the caller can fall back to
            # the current standard causal ledgers without requiring a new
            # counterfactual following grid.
            _source_paths(manifest)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        matches.append(path.resolve())
    if not matches:
        raise FileNotFoundError(
            f"No complete matching following grid manifest found in {folder}: {pattern}"
        )
    return max(matches, key=lambda path: path.stat().st_mtime_ns)


def _standard_following_sources(
    folder: Path,
    *,
    pair: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    spread_pips: float,
) -> dict[str, Path]:
    """Resolve causal replay inputs without requiring a following grid run."""
    stem = (
        f"{pair}_{start:%Y%m%d}_{end:%Y%m%d}"
        f"_m5line60_range6x3_rr1.2_sp{spread_pips:g}_60m"
    )
    s5_stem = f"{pair}_{start:%Y%m%d%H%M%S}_{end:%Y%m%d%H%M%S}"
    result = {
        "source_candidates": Path(folder) / f"resistance_sweep_candidates_{stem}.csv",
        "source_events": Path(folder) / f"resistance_sweep_events_{stem}.csv",
        "s5_cache": Path(folder) / f"s5_{s5_stem}.csv",
    }
    missing = [str(path) for path in result.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            "Following causal source is missing; target-grid/ranking is not required, "
            "but the resistance-sweep candidates/events and S5 cache must exist: "
            + " | ".join(missing)
        )
    return {key: path.resolve() for key, path in result.items()}


def _engine_args(
    contract: SelectionContract,
    manifest: Mapping[str, Any],
    sources: Mapping[str, Path],
    *,
    start: pd.Timestamp,
    end: pd.Timestamp,
    read_chunk_size: int,
) -> argparse.Namespace:
    return argparse.Namespace(
        pair=contract.pair,
        oos_start=start.to_pydatetime(),
        oos_end=end.to_pydatetime(),
        start=start.to_pydatetime(),
        end=end.to_pydatetime(),
        source_candidates=sources["source_candidates"],
        source_events=sources["source_events"],
        s5_cache=sources["s5_cache"],
        spread_pips=float(manifest["spread_pips"]),
        min_target_pips=float(manifest["min_target_pips"]),
        risk_yen=float(manifest["risk_yen"]),
        trade_timeout_min=STABILITY_LC_TRADE_TIMEOUT_MIN,
        profit_lock_ratio=STABILITY_LC_PROFIT_LOCK_RATIO,
        duplicate_threshold_pips=contract.duplicate_threshold_pips,
        read_chunk_size=read_chunk_size,
    )


def _slice_inspector(inspector: Any, start: pd.Timestamp, end: pd.Timestamp) -> Any:
    left = int(np.searchsorted(inspector.times, np.datetime64(start, "ns"), side="left"))
    right = int(np.searchsorted(inspector.times, np.datetime64(end, "ns"), side="left"))
    for attribute in ("times", "opens", "closes", "highs", "lows"):
        setattr(inspector, attribute, getattr(inspector, attribute)[left:right])
    return inspector


def _load_replay_inputs(
    args: argparse.Namespace,
    policies: Sequence[Policy],
) -> tuple[list[tuple[str, pd.Timestamp]], dict[str, Any], Any, dict[str, Any]]:
    _validate_source_headers(args)
    event_times = load_event_times(args)
    intents = build_intents(args, list(policies), event_times)
    pair = gene.currency_pair(args.pair)
    inspector, metadata = _load_typed_s5_inspector(Path(args.s5_cache), pair)
    inspector = _slice_inspector(
        inspector, pd.Timestamp(args.oos_start), pd.Timestamp(args.oos_end)
    )
    _validate_s5_timeline(inspector, s5_source=Path(args.s5_cache))
    coverage = _s5_coverage_errors(
        inspector.times,
        argparse.Namespace(start=args.oos_start, end=args.oos_end),
    )
    if coverage:
        raise ValueError("S5 coverage is incomplete: " + " | ".join(coverage))
    args.lifecycle_s5_rows_total = int(len(inspector.times))
    return event_times, intents, inspector, metadata


def _empty_trades() -> pd.DataFrame:
    return pd.DataFrame(columns=TRADE_COLUMNS)


def _normalize_trades(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    for column in TRADE_COLUMNS:
        if column not in result.columns:
            result[column] = pd.Series(index=result.index, dtype="object")
    if not result.empty:
        for column in ("decision_time", "fill_time", "exit_time"):
            result[column] = pd.to_datetime(result[column], errors="raise")
        for column in ("result_yen", "result_pips", "result_r"):
            result[column] = pd.to_numeric(result[column], errors="raise")
        result = result.sort_values(["exit_time", "fill_time"], kind="stable")
    ordered = list(TRADE_COLUMNS) + [
        column for column in result.columns if column not in TRADE_COLUMNS
    ]
    return result.loc[:, ordered]


def _performance(trades: pd.DataFrame) -> dict[str, Any]:
    work = _normalize_trades(trades)
    if work.empty:
        return {
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "flat": 0,
            "win_rate": 0.0,
            "sum_yen": 0.0,
            "sum_pips": 0.0,
            "sum_r": 0.0,
            "gross_profit_r": 0.0,
            "gross_loss_r": 0.0,
            "profit_factor_r": 0.0,
            "profit_factor_r_infinite": False,
            "average_win_r": 0.0,
            "average_loss_r": 0.0,
            "realized_rr": None,
            "max_drawdown_r": 0.0,
            "max_drawdown_yen": 0.0,
        }
    positive = work[work["result_r"] > 0]
    negative = work[work["result_r"] < 0]
    gross_profit = float(positive["result_r"].sum())
    gross_loss = float(-negative["result_r"].sum())
    pf_infinite = gross_loss == 0 and gross_profit > 0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else None if pf_infinite else 0.0
    average_win = float(positive["result_r"].mean()) if len(positive) else 0.0
    average_loss = float(negative["result_r"].mean()) if len(negative) else 0.0
    realized_rr = average_win / abs(average_loss) if average_win > 0 and average_loss < 0 else None

    def drawdown(column: str) -> float:
        cumulative = work[column].cumsum()
        high = cumulative.cummax().clip(lower=0.0)
        return float((high - cumulative).max())

    return {
        "trades": int(len(work)),
        "wins": int(len(positive)),
        "losses": int(len(negative)),
        "flat": int((work["result_r"] == 0).sum()),
        "win_rate": float((work["result_r"] > 0).mean()),
        "sum_yen": float(work["result_yen"].sum()),
        "sum_pips": float(work["result_pips"].sum()),
        "sum_r": float(work["result_r"].sum()),
        "gross_profit_r": gross_profit,
        "gross_loss_r": gross_loss,
        "profit_factor_r": profit_factor,
        "profit_factor_r_infinite": pf_infinite,
        "average_win_r": average_win,
        "average_loss_r": average_loss,
        "realized_rr": realized_rr,
        "max_drawdown_r": drawdown("result_r"),
        "max_drawdown_yen": drawdown("result_yen"),
    }


def _between_exit_times(
    trades: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp
) -> pd.DataFrame:
    if trades.empty:
        return trades.copy()
    times = pd.to_datetime(trades["exit_time"], errors="raise")
    return trades.loc[(times >= start) & (times < end)].copy()


def _period_summaries(
    trades: pd.DataFrame, periods: Sequence[PeriodWindow]
) -> list[dict[str, Any]]:
    return [
        {
            **period.payload(),
            **_performance(_between_exit_times(trades, period.start, period.end)),
        }
        for period in periods
    ]


def _pf_value(summary: Mapping[str, Any]) -> float:
    if summary.get("profit_factor_r_infinite") is True:
        return math.inf
    value = summary.get("profit_factor_r")
    return float(value or 0.0)


def _positive_concentration(periods: Sequence[Mapping[str, Any]], field: str) -> float:
    positive = [float(item[field]) for item in periods if float(item[field]) > 0]
    return max(positive) / sum(positive) if positive else 1.0


def evaluate_acceptance(
    full: Mapping[str, Any],
    periods: Sequence[Mapping[str, Any]],
    *,
    max_dd_r: float,
) -> dict[str, Any]:
    if len(periods) != 4:
        raise ValueError("Acceptance requires exactly four periods")
    reasons: list[str] = []
    if sum(int(item["trades"]) for item in periods) != int(full["trades"]):
        reasons.append("period_trade_counts_do_not_reconcile_full")
    for field in ("sum_yen", "sum_pips", "sum_r"):
        period_total = sum(float(item[field]) for item in periods)
        if not math.isclose(
            period_total,
            float(full[field]),
            rel_tol=1e-9,
            abs_tol=1e-8,
        ):
            reasons.append(f"period_{field}_does_not_reconcile_full")
    for field in ("sum_yen", "sum_pips", "sum_r"):
        if float(full[field]) <= 0:
            reasons.append(f"full_{field}_not_positive")
    positive_periods = sum(
        float(item["sum_pips"]) > 0 and float(item["sum_r"]) > 0 for item in periods
    )
    if positive_periods < 3:
        reasons.append("positive_pips_and_r_periods_below_3")
    if any(int(item["trades"]) < 30 for item in periods):
        reasons.append("period_trade_count_below_30")
    if int(full["trades"]) < 120:
        reasons.append("full_trade_count_below_120")
    if _pf_value(full) < 1.10:
        reasons.append("full_pf_r_below_1.10")
    period_pf = [_pf_value(item) for item in periods]
    median_pf = float(statistics.median(period_pf))
    if median_pf < 1.0:
        reasons.append("period_pf_r_median_below_1.0")
    leave_one_out: list[dict[str, Any]] = []
    for omitted in range(4):
        row: dict[str, Any] = {"omitted_period_id": periods[omitted]["period_id"]}
        for field in ("sum_yen", "sum_pips", "sum_r"):
            row[field] = sum(
                float(item[field]) for index, item in enumerate(periods) if index != omitted
            )
        row["positive_all"] = all(row[field] > 0 for field in ("sum_yen", "sum_pips", "sum_r"))
        leave_one_out.append(row)
    if not all(item["positive_all"] for item in leave_one_out):
        reasons.append("leave_one_period_out_not_all_positive")
    if float(full["max_drawdown_r"]) > max_dd_r:
        reasons.append("max_drawdown_r_exceeds_limit")
    concentration = {
        field: _positive_concentration(periods, field)
        for field in ("sum_yen", "sum_pips", "sum_r")
    }
    # The user contract says "50%以上", so the boundary itself is rejected.
    if any(value >= 0.5 - 1e-12 for value in concentration.values()):
        reasons.append("positive_profit_concentration_exceeds_50pct")
    return {
        "accepted": not reasons,
        "rejection_reasons": reasons,
        "positive_pips_and_r_periods": positive_periods,
        "period_pf_r_median": None if math.isinf(median_pf) else median_pf,
        "period_pf_r_median_infinite": math.isinf(median_pf),
        "leave_one_period_out": leave_one_out,
        "positive_period_concentration": concentration,
        "max_dd_r_limit": max_dd_r,
    }


def choose_train_winner(results: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    a = results[STABILITY_LC_CANDIDATE_A]
    b = results[STABILITY_LC_CANDIDATE_B]
    a_accepted = bool(a["acceptance"]["accepted"])
    b_accepted = bool(b["acceptance"]["accepted"])
    b_period_wins = sum(
        float(b_period["sum_r"]) > float(a_period["sum_r"])
        for a_period, b_period in zip(a["periods"], b["periods"])
    )
    if (
        b_accepted
        and float(b["full"]["sum_r"]) > float(a["full"]["sum_r"])
        and b_period_wins >= 3
    ):
        winner: str | None = STABILITY_LC_CANDIDATE_B
        reason = "B_accepted_full_r_higher_and_period_r_wins_at_least_3"
    elif a_accepted:
        winner = STABILITY_LC_CANDIDATE_A
        reason = "A_accepted_and_conservative_B_promotion_rule_not_met"
    elif b_accepted:
        # If current management fails the declared stability gates while B
        # passes them, rejecting both would contradict the no-quota acceptance
        # contract.  The relative-improvement rule is only a tie-break between
        # two acceptable methods.
        winner = STABILITY_LC_CANDIDATE_B
        reason = "B_is_the_only_management_method_meeting_training_acceptance"
    else:
        winner = None
        reason = "no_management_method_met_conservative_training_acceptance"
    return {
        "candidate": winner,
        "reason": reason,
        "b_period_r_wins_over_a": b_period_wins,
        "following_results_must_not_change_this_value": True,
    }


def _month_periods(start: pd.Timestamp, end: pd.Timestamp) -> tuple[PeriodWindow, ...]:
    cursor = start.normalize().replace(day=1)
    periods: list[PeriodWindow] = []
    while cursor < end:
        following = cursor + pd.offsets.MonthBegin(1)
        left = max(start, cursor)
        right = min(end, following)
        if left < right:
            periods.append(PeriodWindow(cursor.strftime("%Y-%m"), left, right))
        cursor = following
    return tuple(periods)


def _settings_from_manifest(
    manifest: Mapping[str, Any], contract: SelectionContract
) -> dict[str, Any]:
    return {
        "spread_pips": float(manifest["spread_pips"]),
        "min_target_pips": float(manifest["min_target_pips"]),
        "risk_yen": float(manifest["risk_yen"]),
        "trade_timeout_min": STABILITY_LC_TRADE_TIMEOUT_MIN,
        "profit_lock_ratio": STABILITY_LC_PROFIT_LOCK_RATIO,
        "duplicate_threshold_pips": contract.duplicate_threshold_pips,
        "max_dd_r": contract.max_dd_r,
    }


def _train_prefix(contract: SelectionContract) -> str:
    return (
        f"{TRAIN_ARTIFACT_VERSION}_{contract.pair}_"
        f"{contract.selection_start:%Y%m%d}_{contract.selection_end:%Y%m%d}_to_"
        f"{contract.following_start:%Y%m%d}_{contract.following_end:%Y%m%d}"
    )


def _following_prefix(artifact: Mapping[str, Any]) -> str:
    pair = artifact["pair"]
    selection = artifact["selection"]
    following = artifact["following"]
    return (
        f"{FOLLOWING_RESULT_VERSION}_{pair}_"
        f"{pd.Timestamp(selection['start_inclusive']):%Y%m%d}_"
        f"{pd.Timestamp(selection['end_exclusive']):%Y%m%d}_to_"
        f"{pd.Timestamp(following['start_inclusive']):%Y%m%d}_"
        f"{pd.Timestamp(following['end_exclusive']):%Y%m%d}"
    )


def _train_paths(output_dir: Path, contract: SelectionContract) -> dict[str, Path]:
    prefix = _train_prefix(contract)
    folder = Path(output_dir)
    return {
        "artifact": folder / f"{prefix}_artifact.json",
        "full_summary": folder / f"{prefix}_full_summary.csv",
        "period_summary": folder / f"{prefix}_period_summary.csv",
        "condition_screen": folder / f"{prefix}_condition_screen.csv",
        "screen_A_trades": folder / f"{prefix}_screen_A_trades.csv",
        "screen_B_trades": folder / f"{prefix}_screen_B_trades.csv",
        "A_trades": folder / f"{prefix}_A_trades.csv",
        "B_trades": folder / f"{prefix}_B_trades.csv",
        "progress": folder / f"{prefix}_progress.json",
    }


def _following_paths(output_dir: Path, artifact: Mapping[str, Any]) -> dict[str, Path]:
    prefix = _following_prefix(artifact)
    folder = Path(output_dir)
    return {
        "result": folder / f"{prefix}_result.json",
        "full_summary": folder / f"{prefix}_full_summary.csv",
        "monthly_summary": folder / f"{prefix}_monthly_summary.csv",
        "A_trades": folder / f"{prefix}_A_trades.csv",
        "B_trades": folder / f"{prefix}_B_trades.csv",
        "progress": folder / f"{prefix}_progress.json",
    }


def _write_progress(
    path: Path,
    *,
    phase: str,
    pair: str,
    started: float,
    completed: int,
    total: int,
    current_candidate: str | None = None,
    current_percent: int | None = None,
    current_rows_processed: int | None = None,
    current_rows_total: int | None = None,
    error: str | None = None,
) -> None:
    fraction = (completed + float(current_percent or 0) / 100.0) / max(total, 1)
    _write_json_atomic(
        path,
        {
            "version": VERSION,
            "status": "failed" if error else "running",
            "phase": phase,
            "pair": pair,
            "completed_replays": completed,
            "total_replays": total,
            "current_candidate": current_candidate,
            "current_replay_percent": current_percent,
            "s5_rows_processed_in_current_replay": current_rows_processed,
            "s5_rows_total_in_current_replay": current_rows_total,
            "progress_percent": round(100.0 * fraction, 3),
            "elapsed_minutes": round((time.monotonic() - started) / 60.0, 2),
            "error": error,
            "updated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        },
    )


def _fingerprints_for_replay(
    selection_artifact: Path,
    grid_manifest: Path,
    sources: Mapping[str, Path],
) -> dict[str, Any]:
    return {
        "selection_artifact": _file_fingerprint(selection_artifact, include_sha256=True),
        "grid_manifest": _file_fingerprint(grid_manifest, include_sha256=True),
        "source_candidates": _file_fingerprint(sources["source_candidates"]),
        "source_events": _file_fingerprint(sources["source_events"]),
        "s5_cache": _file_fingerprint(sources["s5_cache"]),
        "lifecycle_engine": _file_fingerprint(
            Path(__file__).with_name("count2_prior2y_oos_replay.py"),
            include_sha256=True,
        ),
        "stability_lifecycle": _file_fingerprint(Path(__file__), include_sha256=True),
    }


def _assert_fingerprints_unchanged(fingerprints: Mapping[str, Any]) -> None:
    for fingerprint in fingerprints.values():
        _assert_fingerprint(fingerprint)


def _integrity_payload(artifact: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in artifact.items()
        if key not in {"lifecycle_integrity_sha256", "created_at"}
    }


def validate_lifecycle_artifact(path: Path) -> dict[str, Any]:
    resolved = Path(path).resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"Completed stability lifecycle artifact is missing: {resolved}")
    artifact = json.loads(resolved.read_text(encoding="utf-8"))
    required = {
        "version",
        "status",
        "pair",
        "selection",
        "following",
        "settings",
        "selected_policies",
        "lc_contract",
        "train_results",
        "frozen_train_winner",
        "fingerprints",
        "config_sha256",
        "lifecycle_integrity_sha256",
        "future_safety",
    }
    missing = required.difference(artifact)
    if missing:
        raise ValueError("Lifecycle artifact lacks keys: " + ", ".join(sorted(missing)))
    if artifact.get("version") != TRAIN_ARTIFACT_VERSION or artifact.get("status") != "complete":
        raise ValueError("Lifecycle artifact version/status mismatch")
    for key in ("selection", "following", "settings", "frozen_train_winner", "fingerprints"):
        if not isinstance(artifact.get(key), Mapping):
            raise ValueError(f"Lifecycle artifact {key} is malformed")
    if not isinstance(artifact.get("selected_policies"), list):
        raise ValueError("Lifecycle artifact selected_policies is malformed")
    if _sha256_payload(_integrity_payload(artifact)) != artifact["lifecycle_integrity_sha256"]:
        raise ValueError("Lifecycle artifact integrity SHA256 mismatch")
    stability_lc_contract_from_payload(artifact["lc_contract"])
    pair = str(artifact.get("pair", ""))
    if pair not in gene.CURRENCY_PAIRS:
        raise ValueError("Lifecycle artifact pair is invalid")
    selection_start = _timestamp(
        artifact["selection"].get("start_inclusive"), "selection start"
    )
    selection_end = _timestamp(
        artifact["selection"].get("end_exclusive"), "selection end"
    )
    following_start = _timestamp(
        artifact["following"].get("start_inclusive"), "following start"
    )
    following_end = _timestamp(
        artifact["following"].get("end_exclusive"), "following end"
    )
    if not (
        selection_start < selection_end == following_start < following_end
    ):
        raise ValueError("Lifecycle artifact boundaries are not contiguous half-open windows")
    settings = artifact.get("settings")
    if not isinstance(settings, Mapping):
        raise ValueError("Lifecycle artifact settings are malformed")
    if int(settings.get("trade_timeout_min", -1)) != STABILITY_LC_TRADE_TIMEOUT_MIN:
        raise ValueError("Lifecycle artifact trade timeout is not the frozen A/B value")
    if not math.isclose(
        float(settings.get("profit_lock_ratio", math.nan)),
        STABILITY_LC_PROFIT_LOCK_RATIO,
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        raise ValueError("Lifecycle artifact profit lock is not the frozen A/B value")
    for key in (
        "spread_pips",
        "min_target_pips",
        "risk_yen",
        "duplicate_threshold_pips",
        "max_dd_r",
    ):
        value = float(settings.get(key, math.nan))
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"Lifecycle artifact setting is invalid: {key}")
    config = {
        "pair": artifact["pair"],
        "selection": artifact["selection"],
        "following": artifact["following"],
        "settings": artifact["settings"],
        "selected_policies": artifact["selected_policies"],
        "lc_contract": artifact["lc_contract"],
    }
    for optional in ("grid_stable_policies", "candidate_gate_policies"):
        if optional in artifact:
            config[optional] = artifact[optional]
    if _sha256_payload(config) != artifact["config_sha256"]:
        raise ValueError("Lifecycle artifact config SHA256 mismatch")
    safety = artifact.get("future_safety")
    expected_safety = {
        "selection_and_following_half_open": True,
        "selection_uses_no_following_rows": True,
        "s5_used_only_after_decision": True,
        "following_never_reranks_conditions": True,
        "following_never_changes_frozen_train_winner": True,
    }
    if not isinstance(safety, Mapping) or any(
        safety.get(key) is not value for key, value in expected_safety.items()
    ):
        raise ValueError("Lifecycle artifact future-safety contract mismatch")
    winner = artifact["frozen_train_winner"].get("candidate")
    if winner not in (None, STABILITY_LC_CANDIDATE_A, STABILITY_LC_CANDIDATE_B):
        raise ValueError("Lifecycle artifact frozen winner is invalid")
    train_results = artifact.get("train_results")
    if not isinstance(train_results, Mapping) or set(train_results) != {"A", "B"}:
        raise ValueError("Lifecycle artifact train A/B results are malformed")
    if choose_train_winner(train_results) != artifact["frozen_train_winner"]:
        raise ValueError("Lifecycle artifact frozen winner does not match train results")
    candidate_sets = artifact.get("candidate_gate_policies")
    if candidate_sets is not None:
        if not isinstance(candidate_sets, Mapping) or set(candidate_sets) != {"A", "B"}:
            raise ValueError("Lifecycle artifact candidate policy sets are malformed")
        expected_selected = candidate_sets[winner] if winner is not None else []
        if _canonical_json(expected_selected) != _canonical_json(
            artifact["selected_policies"]
        ):
            raise ValueError("Frozen selected policies do not match the winning candidate")
    for fingerprint in artifact["fingerprints"].values():
        _assert_fingerprint(fingerprint)
    return artifact


def _policies_from_lifecycle_artifact(artifact: Mapping[str, Any]) -> list[Policy]:
    raw = artifact.get("selected_policies")
    if not isinstance(raw, list):
        raise ValueError("Lifecycle selected_policies must be a list")
    policies = [_policy_from_payload(item, index) for index, item in enumerate(raw, 1)]
    if len({policy.rank for policy in policies}) != len(policies):
        raise ValueError("Lifecycle selected policy ranks are duplicated")
    return sorted(policies, key=lambda item: item.rank)


def _run_pair_of_replays(
    *,
    args: argparse.Namespace,
    policies: Sequence[Policy],
    paths: Mapping[str, Path],
    progress_path: Path,
    progress_phase: str,
    pair: str,
    started: float,
    completed_offset: int = 0,
    total_replays: int = 2,
) -> tuple[dict[str, pd.DataFrame], dict[str, Mapping[str, Any]], dict[str, Any]]:
    if not policies:
        for candidate in ("A", "B"):
            _write_csv_atomic(_empty_trades(), paths[f"{candidate}_trades"])
        # An empty selection is a valid terminal result, not a skipped stage.
        # Emit a generation-local progress file so the orchestrator can archive
        # and resolve this run instead of accidentally finding an older archive.
        _write_progress(
            progress_path,
            phase=progress_phase,
            pair=pair,
            started=started,
            completed=completed_offset + 2,
            total=total_replays,
            current_candidate=None,
            current_percent=100,
            current_rows_processed=0,
            current_rows_total=0,
        )
        return (
            {candidate: _empty_trades() for candidate in ("A", "B")},
            {candidate: {} for candidate in ("A", "B")},
            {"empty_policy_set": True, "s5_loaded": False},
        )
    _write_progress(
        progress_path,
        phase=f"{progress_phase}:loading_causal_inputs",
        pair=pair,
        started=started,
        completed=completed_offset,
        total=total_replays,
        current_candidate=None,
        current_percent=0,
    )
    event_times, intents, inspector, metadata = _load_replay_inputs(args, policies)
    trades_by_candidate: dict[str, pd.DataFrame] = {}
    replay_summaries: dict[str, Mapping[str, Any]] = {}
    completed = completed_offset
    for candidate in (STABILITY_LC_CANDIDATE_A, STABILITY_LC_CANDIDATE_B):
        def progress_callback(
            percent: int,
            counters: Mapping[str, int],
            open_positions: int,
            pending: bool,
        ) -> None:
            del counters, open_positions, pending
            row_total = int(getattr(args, "lifecycle_s5_rows_total", 0))
            _write_progress(
                progress_path,
                phase=progress_phase,
                pair=pair,
                started=started,
                completed=completed,
                total=total_replays,
                current_candidate=candidate,
                current_percent=percent,
                current_rows_processed=int(row_total * percent / 100),
                current_rows_total=row_total,
            )

        trades, replay_summary = replay_metric(
            args,
            "stable",
            list(policies),
            event_times,
            intents,
            inspector,
            management_policy=STABILITY_LC_POLICY_BY_CANDIDATE[candidate],
            progress_callback=progress_callback,
        )
        normalized = _normalize_trades(trades)
        trades_by_candidate[candidate] = normalized
        replay_summaries[candidate] = replay_summary
        _write_csv_atomic(normalized, paths[f"{candidate}_trades"])
        completed += 1
        _write_progress(
            progress_path,
            phase=progress_phase,
            pair=pair,
            started=started,
            completed=completed,
            total=total_replays,
            current_candidate=candidate,
            current_percent=100,
            current_rows_processed=int(getattr(args, "lifecycle_s5_rows_total", 0)),
            current_rows_total=int(getattr(args, "lifecycle_s5_rows_total", 0)),
        )
    return trades_by_candidate, replay_summaries, {
        "empty_policy_set": False,
        "s5_loaded": True,
        "s5_metadata": metadata,
        "event_count": len(event_times),
        "matched_intent_count": len(intents),
    }


def _condition_screen_results(
    *,
    candidate: str,
    policies: Sequence[Policy],
    trades: pd.DataFrame,
    periods: Sequence[PeriodWindow],
    max_dd_r: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Apply the declared four-period gates to each executed policy."""
    normalized = _normalize_trades(trades)
    nested: list[dict[str, Any]] = []
    flat: list[dict[str, Any]] = []
    for policy in sorted(policies, key=lambda item: item.rank):
        if normalized.empty:
            policy_trades = _empty_trades()
        else:
            policy_trades = normalized.loc[
                normalized["order_name"].astype(str).eq(policy.order_name)
                & normalized["condition_id"].astype(str).eq(policy.condition_id)
            ].copy()
        full = _performance(policy_trades)
        period_rows = _period_summaries(policy_trades, periods)
        acceptance = evaluate_acceptance(full, period_rows, max_dd_r=max_dd_r)
        detail = {
            "candidate": candidate,
            "policy": asdict(policy),
            "full": full,
            "periods": period_rows,
            "acceptance": acceptance,
        }
        nested.append(detail)
        row: dict[str, Any] = {
            "candidate": candidate,
            **asdict(policy),
            "accepted": bool(acceptance["accepted"]),
            "rejection_reasons": "|".join(acceptance["rejection_reasons"]),
            **full,
        }
        for period in period_rows:
            prefix = str(period["period_id"])
            for field in (
                "trades",
                "sum_yen",
                "sum_pips",
                "sum_r",
                "profit_factor_r",
                "max_drawdown_r",
            ):
                row[f"{prefix}_{field}"] = period[field]
        flat.append(row)
    return nested, flat


def _accepted_screen_policies(
    policies: Sequence[Policy],
    screen: Sequence[Mapping[str, Any]],
) -> list[Policy]:
    accepted = {
        (
            str(item["policy"]["order_name"]),
            str(item["policy"]["condition_id"]),
        )
        for item in screen
        if bool(item["acceptance"]["accepted"])
    }
    return [
        policy
        for policy in sorted(policies, key=lambda item: item.rank)
        if (policy.order_name, policy.condition_id) in accepted
    ]


def _run_verified_candidate(
    *,
    args: argparse.Namespace,
    candidate: str,
    policies: Sequence[Policy],
    trades_path: Path,
    progress_path: Path,
    pair: str,
    started: float,
    completed_before: int,
    total_replays: int,
) -> tuple[pd.DataFrame, Mapping[str, Any], Mapping[str, Any]]:
    """Replay one management candidate with only its gate-passing policies."""
    if not policies:
        empty = _empty_trades()
        _write_csv_atomic(empty, trades_path)
        _write_progress(
            progress_path,
            phase="selection_lifecycle_verified_ab",
            pair=pair,
            started=started,
            completed=completed_before + 1,
            total=total_replays,
            current_candidate=candidate,
            current_percent=100,
            current_rows_processed=0,
            current_rows_total=0,
        )
        return empty, {}, {"empty_policy_set": True, "s5_loaded": False}

    _write_progress(
        progress_path,
        phase="selection_lifecycle_verified_ab:loading_causal_inputs",
        pair=pair,
        started=started,
        completed=completed_before,
        total=total_replays,
        current_candidate=candidate,
        current_percent=0,
    )
    event_times, intents, inspector, metadata = _load_replay_inputs(args, policies)

    def progress_callback(
        percent: int,
        counters: Mapping[str, int],
        open_positions: int,
        pending: bool,
    ) -> None:
        del counters, open_positions, pending
        row_total = int(getattr(args, "lifecycle_s5_rows_total", 0))
        _write_progress(
            progress_path,
            phase="selection_lifecycle_verified_ab",
            pair=pair,
            started=started,
            completed=completed_before,
            total=total_replays,
            current_candidate=candidate,
            current_percent=percent,
            current_rows_processed=int(row_total * percent / 100),
            current_rows_total=row_total,
        )

    trades, replay_summary = replay_metric(
        args,
        "stable",
        list(policies),
        event_times,
        intents,
        inspector,
        management_policy=STABILITY_LC_POLICY_BY_CANDIDATE[candidate],
        progress_callback=progress_callback,
    )
    normalized = _normalize_trades(trades)
    _write_csv_atomic(normalized, trades_path)
    row_total = int(getattr(args, "lifecycle_s5_rows_total", 0))
    _write_progress(
        progress_path,
        phase="selection_lifecycle_verified_ab",
        pair=pair,
        started=started,
        completed=completed_before + 1,
        total=total_replays,
        current_candidate=candidate,
        current_percent=100,
        current_rows_processed=row_total,
        current_rows_total=row_total,
    )
    return normalized, replay_summary, {
        "empty_policy_set": False,
        "s5_loaded": True,
        "s5_metadata": metadata,
        "event_count": len(event_times),
        "matched_intent_count": len(intents),
    }


def run_train(args: argparse.Namespace) -> dict[str, Path]:
    contract = load_selection_contract(Path(args.selection_artifact))
    if args.pair != contract.pair:
        raise ValueError("Requested pair does not match selection artifact")
    expected_boundaries = (
        pd.Timestamp(args.selection_start),
        pd.Timestamp(args.selection_end),
        pd.Timestamp(args.following_start),
        pd.Timestamp(args.following_end),
    )
    actual_boundaries = (
        contract.selection_start,
        contract.selection_end,
        contract.following_start,
        contract.following_end,
    )
    if expected_boundaries != actual_boundaries:
        raise ValueError("Requested boundaries do not match selection artifact")
    paths = _train_paths(Path(args.output_dir), contract)
    Path(args.output_dir).mkdir(parents=True, exist_ok=True)
    _archive_paths(paths.values())
    started = time.monotonic()
    _notice(
        [
            f"@everyone {contract.pair} count2 stability lifecycle 学習開始",
            f"選定期間: {contract.selection_start:%Y-%m-%d} 以上 ～ {contract.selection_end:%Y-%m-%d} 未満",
            f"grid安定領域の候補: {len(contract.policies)}件（Top15強制なし）",
            "LC比較: A=現在管理 / B=60分後に利益半分保護・損失-0.5R縮小",
            "各条件を実ライフサイクルで足切り後、候補集合を再リプレイします",
            "進捗: 条件screen A/B＋合格集合verified A/B の計4リプレイ",
            "following期間のデータは読みません",
        ]
    )
    try:
        manifest = _load_grid_manifest(
            contract.grid_manifest_path,
            pair=contract.pair,
            start=contract.selection_start,
            end=contract.selection_end,
        )
        sources = _source_paths(manifest)
        settings = _settings_from_manifest(manifest, contract)
        engine_args = _engine_args(
            contract,
            manifest,
            sources,
            start=contract.selection_start,
            end=contract.selection_end,
            read_chunk_size=args.read_chunk_size,
        )
        fingerprints = _fingerprints_for_replay(
            contract.artifact_path, contract.grid_manifest_path, sources
        )
        screen_trades, screen_replay_summaries, screen_replay_context = _run_pair_of_replays(
            args=engine_args,
            policies=contract.policies,
            paths={
                "A_trades": paths["screen_A_trades"],
                "B_trades": paths["screen_B_trades"],
            },
            progress_path=paths["progress"],
            progress_phase="selection_lifecycle_condition_screen_ab",
            pair=contract.pair,
            started=started,
            completed_offset=0,
            total_replays=4,
        )
        condition_screen: dict[str, list[dict[str, Any]]] = {}
        condition_screen_rows: list[dict[str, Any]] = []
        candidate_policies: dict[str, list[Policy]] = {}
        for candidate in (STABILITY_LC_CANDIDATE_A, STABILITY_LC_CANDIDATE_B):
            nested, flat = _condition_screen_results(
                candidate=candidate,
                policies=contract.policies,
                trades=screen_trades[candidate],
                periods=contract.periods,
                max_dd_r=contract.max_dd_r,
            )
            condition_screen[candidate] = nested
            condition_screen_rows.extend(flat)
            candidate_policies[candidate] = _accepted_screen_policies(
                contract.policies, nested
            )

        verified_trades: dict[str, pd.DataFrame] = {}
        verified_replay_summaries: dict[str, Mapping[str, Any]] = {}
        verified_replay_context: dict[str, Mapping[str, Any]] = {}
        for index, candidate in enumerate(
            (STABILITY_LC_CANDIDATE_A, STABILITY_LC_CANDIDATE_B)
        ):
            trades, replay_summary, context = _run_verified_candidate(
                args=engine_args,
                candidate=candidate,
                policies=candidate_policies[candidate],
                trades_path=paths[f"{candidate}_trades"],
                progress_path=paths["progress"],
                pair=contract.pair,
                started=started,
                completed_before=2 + index,
                total_replays=4,
            )
            verified_trades[candidate] = trades
            verified_replay_summaries[candidate] = replay_summary
            verified_replay_context[candidate] = context
        _assert_fingerprints_unchanged(fingerprints)
        results: dict[str, Any] = {}
        full_rows: list[dict[str, Any]] = []
        period_rows: list[dict[str, Any]] = []
        for candidate in (STABILITY_LC_CANDIDATE_A, STABILITY_LC_CANDIDATE_B):
            trades = verified_trades[candidate]
            full = _performance(trades)
            periods = _period_summaries(trades, contract.periods)
            acceptance = evaluate_acceptance(full, periods, max_dd_r=contract.max_dd_r)
            results[candidate] = {
                "management_policy": asdict(STABILITY_LC_POLICY_BY_CANDIDATE[candidate]),
                "gate_passing_policy_count": len(candidate_policies[candidate]),
                "gate_passing_policies": [
                    asdict(policy) for policy in candidate_policies[candidate]
                ],
                "full": full,
                "periods": periods,
                "acceptance": acceptance,
                "replay_counters": verified_replay_summaries[candidate],
            }
            full_rows.append(
                {
                    "pair": contract.pair,
                    "phase": "selection_train_verified",
                    "candidate": candidate,
                    "policy_count": len(candidate_policies[candidate]),
                    "accepted": acceptance["accepted"],
                    **full,
                }
            )
            period_rows.extend(
                {
                    "pair": contract.pair,
                    "phase": "selection_train_verified",
                    "candidate": candidate,
                    "policy_count": len(candidate_policies[candidate]),
                    **row,
                }
                for row in periods
            )
        winner = choose_train_winner(results)
        frozen_policies = (
            candidate_policies[str(winner["candidate"])]
            if winner["candidate"] is not None
            else []
        )
        selection_section = {
            "start_inclusive": contract.selection_start,
            "end_exclusive": contract.selection_end,
            "periods": [period.payload() for period in contract.periods],
        }
        following_section = {
            "start_inclusive": contract.following_start,
            "end_exclusive": contract.following_end,
            "role": "diagnostic_if_previously_reviewed; pristine_status_not_inferred",
        }
        grid_stable_policy_payload = [asdict(policy) for policy in contract.policies]
        selected_policy_payload = [asdict(policy) for policy in frozen_policies]
        candidate_policy_payload = {
            candidate: [asdict(policy) for policy in candidate_policies[candidate]]
            for candidate in (STABILITY_LC_CANDIDATE_A, STABILITY_LC_CANDIDATE_B)
        }
        config = {
            "pair": contract.pair,
            "selection": selection_section,
            "following": following_section,
            "settings": settings,
            "grid_stable_policies": grid_stable_policy_payload,
            "candidate_gate_policies": candidate_policy_payload,
            "selected_policies": selected_policy_payload,
            "lc_contract": stability_lc_contract_payload(),
        }
        artifact: dict[str, Any] = {
            "version": TRAIN_ARTIFACT_VERSION,
            "status": "complete",
            "pair": contract.pair,
            "selection": selection_section,
            "following": following_section,
            "settings": settings,
            "grid_stable_policies": grid_stable_policy_payload,
            "candidate_gate_policies": candidate_policy_payload,
            "selected_policies": selected_policy_payload,
            "lc_contract": stability_lc_contract_payload(),
            "condition_screen": condition_screen,
            "train_results": results,
            "frozen_train_winner": winner,
            "config_sha256": _sha256_payload(config),
            "fingerprints": fingerprints,
            "replay_context": {
                "condition_screen": screen_replay_context,
                "condition_screen_counters": screen_replay_summaries,
                "verified": verified_replay_context,
            },
            "future_safety": {
                "selection_and_following_half_open": True,
                "selection_uses_no_following_rows": True,
                "following_grid_not_read_during_training": True,
                "s5_used_only_after_decision": True,
                "condition_acceptance_uses_full_lifecycle_replay": True,
                "candidate_subsets_replayed_after_condition_screen": True,
                "following_never_reranks_conditions": True,
                "following_never_changes_frozen_train_winner": True,
            },
            "created_at": dt.datetime.now().astimezone(),
        }
        artifact["lifecycle_integrity_sha256"] = _sha256_payload(
            _integrity_payload(artifact)
        )
        _write_csv_atomic(pd.DataFrame(full_rows), paths["full_summary"])
        _write_csv_atomic(pd.DataFrame(period_rows), paths["period_summary"])
        _write_csv_atomic(
            pd.DataFrame(condition_screen_rows), paths["condition_screen"]
        )
        _write_json_atomic(paths["artifact"], artifact)
        validate_lifecycle_artifact(paths["artifact"])
        lines = [
            f"@everyone {contract.pair} count2 stability lifecycle 学習完了",
            f"選定期間: {contract.selection_start:%Y-%m-%d} 以上 ～ {contract.selection_end:%Y-%m-%d} 未満",
            f"grid安定領域の候補: {len(contract.policies)}件",
            f"実ライフサイクル条件合格: A={len(candidate_policies['A'])}件 / B={len(candidate_policies['B'])}件",
            f"最終固定条件数: {len(frozen_policies)}件",
        ]
        for candidate in ("A", "B"):
            full = results[candidate]["full"]
            accepted = results[candidate]["acceptance"]["accepted"]
            lines.append(
                f"学習 {candidate}: 損益 {full['sum_yen']:+,.0f}円 / {full['sum_pips']:+.2f}pips / {full['sum_r']:+.2f}R, "
                f"PF {_display_pf(full)}, DD {full['max_drawdown_r']:.2f}R, 勝率 {100*full['win_rate']:.1f}%, "
                f"条件 {len(candidate_policies[candidate])}件, 合格={accepted}"
            )
            for period in results[candidate]["periods"]:
                lines.append(
                    f"学習 {candidate} {period['period_id']}: {period['trades']}件, "
                    f"{period['sum_yen']:+,.0f}円 / {period['sum_pips']:+.2f}pips / {period['sum_r']:+.2f}R, PF {_display_pf(period)}"
                )
        lines.extend(
            [
                f"学習で固定したLC方式: {winner['candidate'] or '採用なし'}",
                f"理由: {winner['reason']}",
                f"条件別実ライフサイクル判定CSV: {paths['condition_screen']}",
                f"lifecycle artifact: {paths['artifact']}",
            ]
        )
        _notice(lines)
        return paths
    except Exception as error:
        _write_progress(
            paths["progress"],
            phase="failed",
            pair=contract.pair,
            started=started,
            completed=0,
            total=2,
            error=f"{type(error).__name__}: {error}",
        )
        _notice(
            [
                f"@everyone {contract.pair} count2 stability lifecycle 学習失敗",
                f"エラー種別: {type(error).__name__}",
                f"内容: {error}",
                "temp/progressはarchiveへ移動します",
            ]
        )
        _archive_paths(
            path for name, path in paths.items() if name != "progress"
        )
        raise
    finally:
        _archive_paths([paths["progress"]])


def _display_pf(summary: Mapping[str, Any]) -> str:
    if summary.get("profit_factor_r_infinite"):
        return "∞"
    return f"{float(summary.get('profit_factor_r') or 0):.3f}"


def run_following(args: argparse.Namespace) -> dict[str, Path]:
    artifact = validate_lifecycle_artifact(Path(args.lifecycle_artifact))
    if args.pair != artifact["pair"]:
        raise ValueError("Requested pair does not match lifecycle artifact")
    selection_start = _timestamp(artifact["selection"]["start_inclusive"], "selection start")
    selection_end = _timestamp(artifact["selection"]["end_exclusive"], "selection end")
    following_start = _timestamp(artifact["following"]["start_inclusive"], "following start")
    following_end = _timestamp(artifact["following"]["end_exclusive"], "following end")
    if (
        pd.Timestamp(args.selection_start),
        pd.Timestamp(args.selection_end),
        pd.Timestamp(args.following_start),
        pd.Timestamp(args.following_end),
    ) != (selection_start, selection_end, following_start, following_end):
        raise ValueError("Requested boundaries do not match lifecycle artifact")
    policies = _policies_from_lifecycle_artifact(artifact)
    selection_contract = SelectionContract(
        pair=artifact["pair"],
        selection_start=selection_start,
        selection_end=selection_end,
        following_start=following_start,
        following_end=following_end,
        periods=tuple(
            PeriodWindow(
                str(item["period_id"]),
                _timestamp(item["start_inclusive"], "period start"),
                _timestamp(item["end_exclusive"], "period end"),
            )
            for item in artifact["selection"]["periods"]
        ),
        policies=tuple(policies),
        max_dd_r=float(artifact["settings"]["max_dd_r"]),
        duplicate_threshold_pips=float(artifact["settings"]["duplicate_threshold_pips"]),
        grid_manifest_path=Path(artifact["fingerprints"]["grid_manifest"]["resolved_path"]),
        artifact_path=Path(args.lifecycle_artifact).resolve(),
        artifact=artifact,
    )
    paths = _following_paths(Path(args.output_dir), artifact)
    Path(args.output_dir).mkdir(parents=True, exist_ok=True)
    _archive_paths(paths.values())
    started = time.monotonic()
    frozen_winner = artifact["frozen_train_winner"]["candidate"]
    _notice(
        [
            f"@everyone {artifact['pair']} count2 stability following固定リプレイ開始",
            f"following期間: {following_start:%Y-%m-%d} 以上 ～ {following_end:%Y-%m-%d} 未満",
            f"固定条件数: {len(policies)}件",
            f"学習で固定したLC方式: {frozen_winner or '採用なし'}",
            "A/B両方を診断しますが、following結果では再選定しません",
        ]
    )
    try:
        if policies:
            manifest_path: Path | None
            if args.following_grid_manifest:
                manifest_path = Path(args.following_grid_manifest).resolve()
            else:
                try:
                    manifest_path = _discover_grid_manifest(
                        Path(args.grid_dir),
                        artifact["pair"],
                        following_start,
                        following_end,
                        artifact["settings"],
                    )
                except FileNotFoundError:
                    manifest_path = None
            if manifest_path is not None:
                manifest = _load_grid_manifest(
                    manifest_path,
                    pair=artifact["pair"],
                    start=following_start,
                    end=following_end,
                    frozen_settings=artifact["settings"],
                )
                sources = _source_paths(manifest)
            else:
                # A fixed following replay needs causal source ledgers and S5,
                # not a counterfactual target grid.  Do not create or rank a
                # following grid merely to obtain these standard paths.
                manifest = {
                    "spread_pips": float(artifact["settings"]["spread_pips"]),
                    "min_target_pips": float(artifact["settings"]["min_target_pips"]),
                    "risk_yen": float(artifact["settings"]["risk_yen"]),
                }
                sources = _standard_following_sources(
                    Path(args.grid_dir),
                    pair=artifact["pair"],
                    start=following_start,
                    end=following_end,
                    spread_pips=float(artifact["settings"]["spread_pips"]),
                )
            engine_args = _engine_args(
                selection_contract,
                manifest,
                sources,
                start=following_start,
                end=following_end,
                read_chunk_size=args.read_chunk_size,
            )
            following_fingerprints = {
                "source_candidates": _file_fingerprint(sources["source_candidates"]),
                "source_events": _file_fingerprint(sources["source_events"]),
                "s5_cache": _file_fingerprint(sources["s5_cache"]),
            }
            if manifest_path is not None:
                following_fingerprints["grid_manifest"] = _file_fingerprint(
                    manifest_path, include_sha256=True
                )
        else:
            manifest_path = None
            engine_args = argparse.Namespace()
            following_fingerprints = {}
        trades_by_candidate, replay_summaries, replay_context = _run_pair_of_replays(
            args=engine_args,
            policies=policies,
            paths=paths,
            progress_path=paths["progress"],
            progress_phase="following_fixed_ab_diagnostic",
            pair=artifact["pair"],
            started=started,
        )
        _assert_fingerprints_unchanged(following_fingerprints)
        full_rows: list[dict[str, Any]] = []
        monthly_rows: list[dict[str, Any]] = []
        results: dict[str, Any] = {}
        months = _month_periods(following_start, following_end)
        for candidate in ("A", "B"):
            full = _performance(trades_by_candidate[candidate])
            monthly = _period_summaries(trades_by_candidate[candidate], months)
            train_result = artifact["train_results"][candidate]
            results[candidate] = {
                "management_policy": asdict(STABILITY_LC_POLICY_BY_CANDIDATE[candidate]),
                "full": full,
                "monthly": monthly,
                "replay_counters": replay_summaries[candidate],
            }
            full_rows.append(
                {
                    "pair": artifact["pair"],
                    "phase": "selection_train_frozen",
                    "candidate": candidate,
                    "frozen_train_winner": frozen_winner,
                    "policy_count": int(train_result.get("gate_passing_policy_count", 0)),
                    "accepted": bool(train_result["acceptance"]["accepted"]),
                    **train_result["full"],
                }
            )
            full_rows.append(
                {
                    "pair": artifact["pair"],
                    "phase": "following_fixed_diagnostic",
                    "candidate": candidate,
                    "frozen_train_winner": frozen_winner,
                    "policy_count": len(policies),
                    **full,
                }
            )
            monthly_rows.extend(
                {
                    "pair": artifact["pair"],
                    "phase": "following_fixed_diagnostic",
                    "candidate": candidate,
                    "frozen_train_winner": frozen_winner,
                    **row,
                }
                for row in monthly
            )
        payload: dict[str, Any] = {
            "version": FOLLOWING_RESULT_VERSION,
            "status": "complete",
            "pair": artifact["pair"],
            "selection": artifact["selection"],
            "following": artifact["following"],
            "lifecycle_artifact": _file_fingerprint(
                Path(args.lifecycle_artifact), include_sha256=True
            ),
            "following_grid_manifest": str(manifest_path) if manifest_path else None,
            "following_fingerprints": following_fingerprints,
            "selected_policies": artifact["selected_policies"],
            "frozen_train_winner": artifact["frozen_train_winner"],
            "frozen_train_results": artifact["train_results"],
            "diagnostic_results": results,
            "following_selection_performed": False,
            "replay_context": replay_context,
            "future_safety": {
                "half_open_window": True,
                "fixed_training_policies_only": True,
                "fixed_ab_contract_only": True,
                "following_target_grid_required": False,
                "following_grid_or_ranking_executed": False,
                "following_selection_performed": False,
                "s5_used_only_after_decision": True,
            },
            "created_at": dt.datetime.now().astimezone(),
        }
        payload["result_sha256"] = _sha256_payload(
            {key: value for key, value in payload.items() if key not in {"result_sha256", "created_at"}}
        )
        _write_csv_atomic(pd.DataFrame(full_rows), paths["full_summary"])
        _write_csv_atomic(pd.DataFrame(monthly_rows), paths["monthly_summary"])
        _write_json_atomic(paths["result"], payload)
        lines = [
            f"@everyone {artifact['pair']} count2 stability following固定リプレイ完了",
            f"following期間: {following_start:%Y-%m-%d} 以上 ～ {following_end:%Y-%m-%d} 未満",
            f"学習で固定したLC方式: {frozen_winner or '採用なし'}",
            "学習A/Bは各方式で条件足切り後の集合、following A/Bは勝者の固定条件集合です",
            "following結果による条件・LC方式の再選定: なし",
        ]
        for candidate in ("A", "B"):
            train_result = artifact["train_results"][candidate]
            train_full = train_result["full"]
            full = results[candidate]["full"]
            lines.append(
                f"{candidate} 学習2年: 損益 {train_full['sum_yen']:+,.0f}円 / {train_full['sum_pips']:+.2f}pips / {train_full['sum_r']:+.2f}R, "
                f"PF {_display_pf(train_full)}, DD {train_full['max_drawdown_r']:.2f}R, 勝率 {100*train_full['win_rate']:.1f}%, "
                f"条件 {int(train_result.get('gate_passing_policy_count', 0))}件, 合格={bool(train_result['acceptance']['accepted'])}"
            )
            lines.append(
                f"{candidate} following1年: 損益 {full['sum_yen']:+,.0f}円 / {full['sum_pips']:+.2f}pips / {full['sum_r']:+.2f}R, "
                f"PF {_display_pf(full)}, DD {full['max_drawdown_r']:.2f}R, 勝率 {100*full['win_rate']:.1f}%, 条件 {len(policies)}件"
            )
        lines.extend(
            [
                f"学習artifact: {Path(args.lifecycle_artifact).resolve()}",
                f"学習2年/following1年 比較CSV: {paths['full_summary']}",
                f"following月別CSV: {paths['monthly_summary']}",
            ]
        )
        _notice(lines)
        return paths
    except Exception as error:
        _write_progress(
            paths["progress"],
            phase="failed",
            pair=artifact["pair"],
            started=started,
            completed=0,
            total=2,
            error=f"{type(error).__name__}: {error}",
        )
        _notice(
            [
                f"@everyone {artifact['pair']} count2 stability following固定リプレイ失敗",
                f"エラー種別: {type(error).__name__}",
                f"内容: {error}",
                "temp/progressはarchiveへ移動します",
            ]
        )
        _archive_paths(
            path for name, path in paths.items() if name != "progress"
        )
        raise
    finally:
        _archive_paths([paths["progress"]])


def _parse_datetime_args(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    for field in ("selection_start", "selection_end", "following_start", "following_end"):
        try:
            setattr(args, field, pd.Timestamp(getattr(args, field)).to_pydatetime())
        except (TypeError, ValueError) as error:
            parser.error(f"--{field.replace('_', '-')} is invalid: {error}")
    if args.selection_start >= args.selection_end:
        parser.error("--selection-start must be earlier than --selection-end")
    if args.selection_end != args.following_start:
        parser.error("--selection-end must equal --following-start")
    if args.following_start >= args.following_end:
        parser.error("--following-start must be earlier than --following-end")
    if args.read_chunk_size <= 0:
        parser.error("--read-chunk-size must be positive")


def _common_parser(
    description: str,
    *,
    default_pair: str,
    default_selection_start: dt.datetime,
    default_selection_end: dt.datetime,
    default_following_start: dt.datetime,
    default_following_end: dt.datetime,
) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--pair", default=default_pair, choices=tuple(gene.CURRENCY_PAIRS))
    parser.add_argument("--selection-start", default=default_selection_start.isoformat(" "))
    parser.add_argument("--selection-end", default=default_selection_end.isoformat(" "))
    parser.add_argument("--following-start", default=default_following_start.isoformat(" "))
    parser.add_argument("--following-end", default=default_following_end.isoformat(" "))
    parser.add_argument("--output-dir", type=Path, default=Path(tk.folder_path))
    parser.add_argument("--read-chunk-size", type=int, default=1000)
    return parser


def train_main(
    argv: list[str] | None = None,
    *,
    default_pair: str = "USD_JPY",
    default_selection_start: dt.datetime = DEFAULT_SELECTION_START,
    default_selection_end: dt.datetime = DEFAULT_SELECTION_END,
    default_following_start: dt.datetime = DEFAULT_FOLLOWING_START,
    default_following_end: dt.datetime = DEFAULT_FOLLOWING_END,
) -> dict[str, Path]:
    parser = _common_parser(
        "Train frozen count2 stability lifecycle A/B management",
        default_pair=default_pair,
        default_selection_start=default_selection_start,
        default_selection_end=default_selection_end,
        default_following_start=default_following_start,
        default_following_end=default_following_end,
    )
    parser.add_argument("--selection-artifact", type=Path, required=True)
    args = parser.parse_args(argv)
    _parse_datetime_args(args, parser)
    return run_train(args)


def following_main(
    argv: list[str] | None = None,
    *,
    default_pair: str = "USD_JPY",
    default_selection_start: dt.datetime = DEFAULT_SELECTION_START,
    default_selection_end: dt.datetime = DEFAULT_SELECTION_END,
    default_following_start: dt.datetime = DEFAULT_FOLLOWING_START,
    default_following_end: dt.datetime = DEFAULT_FOLLOWING_END,
) -> dict[str, Path]:
    parser = _common_parser(
        "Replay frozen count2 stability conditions and A/B LC on following data",
        default_pair=default_pair,
        default_selection_start=default_selection_start,
        default_selection_end=default_selection_end,
        default_following_start=default_following_start,
        default_following_end=default_following_end,
    )
    parser.add_argument("--lifecycle-artifact", type=Path, required=True)
    parser.add_argument("--following-grid-manifest", type=Path)
    parser.add_argument("--grid-dir", type=Path, default=Path(tk.folder_path))
    args = parser.parse_args(argv)
    _parse_datetime_args(args, parser)
    return run_following(args)


def main(argv: list[str] | None = None) -> dict[str, Path]:
    values = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(description="Count2 stability lifecycle A/B pipeline stage")
    parser.add_argument("phase", choices=("train", "following"))
    if not values or values[0] in {"-h", "--help"}:
        parser.parse_args(values)
        raise AssertionError("argparse --help should have exited")
    phase = values.pop(0)
    if phase == "train":
        return train_main(values)
    if phase == "following":
        return following_main(values)
    parser.error(f"invalid phase: {phase!r}")
    raise AssertionError("argparse error should have exited")


if __name__ == "__main__":
    main()
