# 最新更新日時: 2026-08-29 20:40 JST
"""Replay fixed prior-two-year FC2 Top15 policies on the following year.

This module is intentionally inspection-only.  It reads the completed ranking
CSVs created from ``[train_start, train_end)`` and applies those policies,
without reselection, to causal resistance-sweep rows in
``[oos_start, oos_end)``.  S5 is used only after each decision to simulate
pending orders and positions.

The replay models the live PredictReversal lifecycle that materially changes
portfolio results:

* one selected Top15 policy per count2 event, in ranking priority order;
* the distance-based live order timeout;
* replacement/cancellation of an older pending PredictReversal at a new
  count2 event;
* no follow-up order while a managed position has ``allow_followup_order``
  false;
* after ``trade_timeout_min``, a profitable position moves LC to the configured
  fraction of current profit and then permits follow-up orders;
* inspection variants may instead start a stepped LC after that timeout at
  20/40/60/80% of each order's TP, securing half of each reached threshold;
* duplicate active same-direction orders inside the live 3-pip threshold;
* the live normal/mid/high slot capacities.

No live strategy profile is mutated by this module.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Iterable, Mapping

import numpy as np
import pandas as pd

import fGeneric as gene
import fLineAnalysis as line_analysis
from fCandleDataQuality import (
    is_expected_annual_holiday_closure_gap as _is_expected_annual_holiday_closure_gap,
)
import test_win_point_usd_aud as win_point
import tokens as tk
from count2_target_grid_search import (
    FC2_EVENT_COLUMNS,
    FC2_LINE_COLUMNS,
    GRID_VERSION,
    H1_PAIR_COLUMNS,
    _archive_file,
    _bound_inspector_before,
    _load_typed_s5_inspector,
    _s5_coverage_errors,
    _validate_fc2_context,
    _validate_h1_pair_context,
    adjusted_entry_parameters,
    condition_memberships,
    executable_target_pips,
)


DEFAULT_TRAIN_START = dt.datetime(2023, 7, 30)
DEFAULT_TRAIN_END = dt.datetime(2025, 7, 30)
DEFAULT_OOS_START = dt.datetime(2025, 7, 30)
DEFAULT_OOS_END = dt.datetime(2026, 7, 30)
DEFAULT_METRICS = ("yen", "pips")
REQUIRED_RANKING_COLUMNS = {
    "rank",
    "ranking_metric",
    "order_name",
    "grid_version",
    "condition_id",
    "entry_candidate_rank",
    "entry_offset_range_multiplier",
    "tp_range_multiplier",
    "lc_range_multiplier",
}
REQUIRED_CANDIDATE_COLUMNS = {
    "event_id",
    "pair",
    "decision_time",
    "distance_rank",
    "peak_direction",
    "trade_direction",
    "line_price",
    "decision_price",
    "recent_m5_avg_range_pips",
    "line_total_strength",
    "fc2_version",
    "fc2_line_shape",
    "target_source_last_time",
    "fc2_source_last_time",
    "line_newest_source_time",
} | FC2_EVENT_COLUMNS | FC2_LINE_COLUMNS | H1_PAIR_COLUMNS


@dataclass(frozen=True)
class Policy:
    rank: int
    metric: str
    order_name: str
    condition_id: str
    entry_rank: int
    offset_multiplier: float
    tp_multiplier: float
    lc_multiplier: float


@dataclass(frozen=True)
class LossStage:
    after_min: float
    action: str
    cap_r: float | None = None
    trigger_r_max: float = 0.0
    evaluation: str = "armed"
    name: str | None = None

    def __post_init__(self) -> None:
        if (
            isinstance(self.after_min, bool)
            or not isinstance(self.after_min, (int, float))
            or not math.isfinite(float(self.after_min))
            or self.after_min <= 0
        ):
            raise ValueError("A loss stage requires a finite after_min > 0")
        if self.action not in {"cap", "market_exit"}:
            raise ValueError(f"Unsupported loss-stage action: {self.action}")
        if self.action == "cap":
            if (
                isinstance(self.cap_r, bool)
                or not isinstance(self.cap_r, (int, float))
                or not math.isfinite(float(self.cap_r))
                or not 0 < float(self.cap_r) < 1
            ):
                raise ValueError("A cap loss stage requires 0 < cap_r < 1")
        elif self.cap_r is not None:
            raise ValueError("cap_r is valid only for a cap loss stage")
        if (
            isinstance(self.trigger_r_max, bool)
            or not isinstance(self.trigger_r_max, (int, float))
            or not math.isfinite(float(self.trigger_r_max))
            or self.trigger_r_max > 0
        ):
            raise ValueError("A loss-stage trigger_r_max must be finite and <= 0")
        if self.evaluation not in {"armed", "boundary_once"}:
            raise ValueError(
                "A loss-stage evaluation must be 'armed' or 'boundary_once'"
            )
        if self.name is not None and not self.name.strip():
            raise ValueError("A loss-stage name must be non-empty when supplied")


@dataclass(frozen=True)
class ExitManagementPolicy:
    name: str
    profit_lock_enabled: bool = True
    loss_action: str = "none"
    loss_cap_r: float | None = None
    step_trigger_tp_fractions: tuple[float, ...] = ()
    step_ensure_trigger_ratio: float | None = None
    loss_stages: tuple[LossStage, ...] = ()

    def __post_init__(self) -> None:
        if self.loss_action not in {"none", "cap", "market_exit"}:
            raise ValueError(f"Unsupported loss action: {self.loss_action}")
        if self.loss_action == "cap":
            if self.loss_cap_r is None or not 0 < self.loss_cap_r < 1:
                raise ValueError("A loss-cap policy requires 0 < loss_cap_r < 1")
        elif self.loss_cap_r is not None:
            raise ValueError("loss_cap_r is valid only for a loss-cap policy")
        if self.loss_action != "none" and self.loss_stages:
            raise ValueError("Legacy loss_action and loss_stages cannot be combined")
        previous_after_min = 0.0
        previous_cap_r: float | None = None
        stage_names: set[str] = set()
        for index, stage in enumerate(self.loss_stages):
            if not isinstance(stage, LossStage):
                raise TypeError("loss_stages must contain only LossStage values")
            if stage.after_min <= previous_after_min:
                raise ValueError("Loss stages must have strictly increasing after_min")
            previous_after_min = float(stage.after_min)
            if stage.action == "market_exit" and index != len(self.loss_stages) - 1:
                raise ValueError("A market_exit loss stage must be terminal")
            if stage.action == "cap":
                assert stage.cap_r is not None
                if previous_cap_r is not None and stage.cap_r >= previous_cap_r:
                    raise ValueError("Successive cap loss stages must tighten cap_r")
                previous_cap_r = float(stage.cap_r)
            stage_name = stage.name or f"loss_stage_{index + 1}"
            if stage_name in stage_names:
                raise ValueError("Loss-stage names must be unique inside a policy")
            stage_names.add(stage_name)
        if self.step_trigger_tp_fractions:
            if not self.profit_lock_enabled:
                raise ValueError("A step-profit policy requires profit_lock_enabled")
            if self.step_ensure_trigger_ratio is None or not (
                math.isfinite(self.step_ensure_trigger_ratio)
                and 0 < self.step_ensure_trigger_ratio <= 1
            ):
                raise ValueError(
                    "A step-profit policy requires 0 < step_ensure_trigger_ratio <= 1"
                )
            fractions = self.step_trigger_tp_fractions
            if any(
                not math.isfinite(fraction) or not 0 < fraction < 1
                for fraction in fractions
            ):
                raise ValueError("Step-profit TP fractions must be finite inside (0, 1)")
            if tuple(sorted(set(fractions))) != fractions:
                raise ValueError("Step-profit TP fractions must be unique and increasing")
        elif self.step_ensure_trigger_ratio is not None:
            raise ValueError(
                "step_ensure_trigger_ratio requires step_trigger_tp_fractions"
            )


def exit_management_policy_from_dict(
    payload: Mapping[str, Any],
) -> ExitManagementPolicy:
    """Restore a policy (including nested stages) from JSON-like data."""
    values = dict(payload)
    raw_stages = values.get("loss_stages", ())
    if raw_stages is None:
        raw_stages = ()
    stages: list[LossStage] = []
    for raw_stage in raw_stages:
        if isinstance(raw_stage, LossStage):
            stages.append(raw_stage)
        elif isinstance(raw_stage, Mapping):
            stages.append(LossStage(**dict(raw_stage)))
        else:
            raise TypeError("Each loss_stages item must be a mapping or LossStage")
    values["loss_stages"] = tuple(stages)
    if "step_trigger_tp_fractions" in values:
        values["step_trigger_tp_fractions"] = tuple(
            values["step_trigger_tp_fractions"] or ()
        )
    return ExitManagementPolicy(**values)


CURRENT_EXIT_POLICY = ExitManagementPolicy(name="current")
STEP_TP_FRACTION_EXIT_POLICY = ExitManagementPolicy(
    name="step_tp20_40_60_80_lock50",
    step_trigger_tp_fractions=(0.2, 0.4, 0.6, 0.8),
    step_ensure_trigger_ratio=0.5,
)
EXIT_COMPARISON_POLICIES = (
    CURRENT_EXIT_POLICY,
    STEP_TP_FRACTION_EXIT_POLICY,
    ExitManagementPolicy(name="loss_cap_0.7r", loss_action="cap", loss_cap_r=0.7),
    ExitManagementPolicy(name="loss_cap_0.5r", loss_action="cap", loss_cap_r=0.5),
    ExitManagementPolicy(name="loss_market_exit_60m", loss_action="market_exit"),
    ExitManagementPolicy(name="no_profit_lock", profit_lock_enabled=False),
)


def _build_lifecycle_loss_policies() -> tuple[ExitManagementPolicy, ...]:
    policies: list[ExitManagementPolicy] = [CURRENT_EXIT_POLICY]
    for after_min in (30, 45, 60):
        for cap_r in (0.75, 0.5, 0.25):
            cap_text = f"{cap_r:.2f}".rstrip("0").rstrip(".")
            policies.append(
                ExitManagementPolicy(
                    name=f"loss_armed_{after_min}m_cap_{cap_text}r",
                    loss_stages=(
                        LossStage(
                            after_min=after_min,
                            action="cap",
                            cap_r=cap_r,
                            name=f"cap_{cap_text}r_after_{after_min}m",
                        ),
                    ),
                )
            )
        policies.append(
            ExitManagementPolicy(
                name=f"loss_armed_{after_min}m_market_exit",
                loss_stages=(
                    LossStage(
                        after_min=after_min,
                        action="market_exit",
                        name=f"market_exit_after_{after_min}m",
                    ),
                ),
            )
        )

    policies.extend(
        (
            ExitManagementPolicy(
                name="loss_armed_30m_cap_0.75r_then_45m_cap_0.5r",
                loss_stages=(
                    LossStage(30, "cap", 0.75, name="cap_0.75r_after_30m"),
                    LossStage(45, "cap", 0.5, name="cap_0.5r_after_45m"),
                ),
            ),
            ExitManagementPolicy(
                name="loss_armed_30m_cap_0.75r_then_60m_market_exit",
                loss_stages=(
                    LossStage(30, "cap", 0.75, name="cap_0.75r_after_30m"),
                    LossStage(60, "market_exit", name="market_exit_after_60m"),
                ),
            ),
            ExitManagementPolicy(
                name="loss_armed_30m_cap_0.75r_then_45m_cap_0.5r_then_60m_cap_0.25r",
                loss_stages=(
                    LossStage(30, "cap", 0.75, name="cap_0.75r_after_30m"),
                    LossStage(45, "cap", 0.5, name="cap_0.5r_after_45m"),
                    LossStage(60, "cap", 0.25, name="cap_0.25r_after_60m"),
                ),
            ),
        )
    )
    names = [policy.name for policy in policies]
    if len(names) != len(set(names)):
        raise RuntimeError("Lifecycle loss-policy names must be unique")
    return tuple(policies)


LIFECYCLE_LOSS_POLICIES = _build_lifecycle_loss_policies()


# Frozen A/B contract used only by the stability-selection pipeline.  Keep the
# broader 16-policy lifecycle catalog above intact for legacy inspection runs.
STABILITY_LC_CONTRACT_VERSION = "count2_stability_lc_ab_v1"
STABILITY_LC_CANDIDATE_A = "A"
STABILITY_LC_CANDIDATE_B = "B"
STABILITY_LC_TRADE_TIMEOUT_MIN = 60
STABILITY_LC_PROFIT_LOCK_RATIO = 0.5
STABILITY_LC_B_POLICY_NAME = "loss_armed_60m_cap_0.5r"

_stability_lc_b_matches = tuple(
    policy
    for policy in LIFECYCLE_LOSS_POLICIES
    if policy.name == STABILITY_LC_B_POLICY_NAME
)
if len(_stability_lc_b_matches) != 1:
    raise RuntimeError(
        "The stability LC B policy must exist exactly once in "
        "LIFECYCLE_LOSS_POLICIES"
    )
STABILITY_LC_B_EXIT_POLICY = _stability_lc_b_matches[0]
STABILITY_LC_POLICY_BY_CANDIDATE: Mapping[str, ExitManagementPolicy] = (
    MappingProxyType(
        {
            STABILITY_LC_CANDIDATE_A: CURRENT_EXIT_POLICY,
            STABILITY_LC_CANDIDATE_B: STABILITY_LC_B_EXIT_POLICY,
        }
    )
)


def stability_lc_policy(candidate_name: str) -> ExitManagementPolicy:
    """Return the canonical policy for one frozen stability candidate."""
    try:
        return STABILITY_LC_POLICY_BY_CANDIDATE[candidate_name]
    except (KeyError, TypeError) as error:
        raise ValueError(
            f"Unknown stability LC candidate: {candidate_name!r}"
        ) from error


def stability_lc_policy_payload(candidate_name: str) -> dict[str, Any]:
    """Return an artifact-safe payload for one canonical A/B policy."""
    return asdict(stability_lc_policy(candidate_name))


def _canonical_stability_lc_payload(payload: Any) -> str:
    try:
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise ValueError("Stability LC payload is not canonical JSON data") from error


def stability_lc_policy_from_payload(
    candidate_name: str,
    payload: Mapping[str, Any],
) -> ExitManagementPolicy:
    """Validate an artifact policy payload and return its canonical object."""
    expected_policy = stability_lc_policy(candidate_name)
    if not isinstance(payload, Mapping):
        raise ValueError(
            f"Stability LC {candidate_name} policy payload must be a mapping"
        )
    if _canonical_stability_lc_payload(payload) != (
        _canonical_stability_lc_payload(asdict(expected_policy))
    ):
        raise ValueError(
            f"Stability LC {candidate_name} policy payload mismatch"
        )
    try:
        restored_policy = exit_management_policy_from_dict(payload)
    except (TypeError, ValueError) as error:
        raise ValueError(
            f"Stability LC {candidate_name} policy payload is malformed"
        ) from error
    if _canonical_stability_lc_payload(asdict(restored_policy)) != (
        _canonical_stability_lc_payload(asdict(expected_policy))
    ):
        raise ValueError(
            f"Stability LC {candidate_name} policy payload mismatch"
        )
    return expected_policy


def stability_lc_contract_payload() -> dict[str, Any]:
    """Serialize the complete, versioned A/B contract for an artifact."""
    candidate_order = list(STABILITY_LC_POLICY_BY_CANDIDATE)
    return {
        "version": STABILITY_LC_CONTRACT_VERSION,
        "settings": {
            "trade_timeout_min": STABILITY_LC_TRADE_TIMEOUT_MIN,
            "profit_lock_ratio": STABILITY_LC_PROFIT_LOCK_RATIO,
        },
        "candidate_order": candidate_order,
        "policies": {
            name: stability_lc_policy_payload(name)
            for name in candidate_order
        },
    }


def stability_lc_contract_from_payload(
    payload: Mapping[str, Any],
) -> Mapping[str, ExitManagementPolicy]:
    """Hard-validate an artifact contract and restore the canonical mapping."""
    if not isinstance(payload, Mapping):
        raise ValueError("Stability LC contract payload must be a mapping")
    if payload.get("version") != STABILITY_LC_CONTRACT_VERSION:
        raise ValueError(
            "Unsupported stability LC contract version: "
            f"{payload.get('version')!r}"
        )
    expected = stability_lc_contract_payload()
    if payload.get("candidate_order") != expected["candidate_order"]:
        raise ValueError("Stability LC candidate names or order mismatch")
    raw_policies = payload.get("policies")
    if not isinstance(raw_policies, Mapping) or set(raw_policies) != set(
        STABILITY_LC_POLICY_BY_CANDIDATE
    ):
        raise ValueError("Stability LC policy mapping mismatch")
    for candidate_name in STABILITY_LC_POLICY_BY_CANDIDATE:
        stability_lc_policy_from_payload(
            candidate_name,
            raw_policies[candidate_name],
        )
    if _canonical_stability_lc_payload(payload) != (
        _canonical_stability_lc_payload(expected)
    ):
        raise ValueError("Stability LC contract payload mismatch")
    return STABILITY_LC_POLICY_BY_CANDIDATE


@dataclass(frozen=True)
class Intent:
    event_id: str
    decision_time: pd.Timestamp
    decision_price: float
    policy_rank: int
    order_name: str
    condition_id: str
    entry_rank: int
    direction: int
    entry_price: float
    adjusted_distance_pips: float
    entry_offset_pips: float
    tp_pips: float
    lc_pips: float
    priority: int


@dataclass
class PendingOrder:
    intent: Intent
    expiry_time: pd.Timestamp


@dataclass
class OpenPosition:
    intent: Intent
    fill_time: pd.Timestamp
    fill_at_open: bool
    original_lc_price: float
    current_lc_price: float
    tp_price: float
    risk_yen: float
    slot_class: str
    profit_lock_done: bool = False
    profit_lock_step_index: int = 0
    trade_timeout_evaluated: bool = False
    loss_cap_done: bool = False
    loss_cap_r: float | None = None
    loss_stage_next_index: int = 0
    loss_stage_applied_count: int = 0
    loss_stage_last_index: int | None = None
    loss_stage_last_name: str | None = None
    loss_stage_last_action: str | None = None
    loss_stage_last_action_time: pd.Timestamp | None = None
    loss_stage_last_action_r: float | None = None
    loss_stage_history: list[dict[str, Any]] = field(default_factory=list)
    allow_followup_order: bool = False
    max_favorable_pips: float = 0.0
    max_adverse_pips: float = 0.0


def parse_args(
    argv: list[str] | None = None,
    *,
    default_pair: str = "USD_JPY",
    default_train_start: dt.datetime = DEFAULT_TRAIN_START,
    default_train_end: dt.datetime = DEFAULT_TRAIN_END,
    default_oos_start: dt.datetime = DEFAULT_OOS_START,
    default_oos_end: dt.datetime = DEFAULT_OOS_END,
) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Replay fixed prior-2y FC2 Top15 policies on the following year"
    )
    parser.add_argument("--pair", default=default_pair, choices=tuple(gene.CURRENCY_PAIRS))
    parser.add_argument("--train-start", default=default_train_start.isoformat(" "))
    parser.add_argument("--train-end", default=default_train_end.isoformat(" "))
    parser.add_argument("--oos-start", default=default_oos_start.isoformat(" "))
    parser.add_argument("--oos-end", default=default_oos_end.isoformat(" "))
    parser.add_argument(
        "--metrics",
        default=",".join(DEFAULT_METRICS),
        help="Comma-separated ranking policies: yen,pips",
    )
    parser.add_argument("--ranking-dir", type=Path, default=Path(tk.folder_path))
    parser.add_argument("--source-candidates", type=Path)
    parser.add_argument("--source-events", type=Path)
    parser.add_argument("--s5-cache", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path(tk.folder_path))
    parser.add_argument("--spread-pips", type=float, default=0.8)
    parser.add_argument("--min-target-pips", type=float, default=1.6)
    parser.add_argument("--trade-timeout-min", type=int, default=60)
    parser.add_argument("--profit-lock-ratio", type=float, default=0.5)
    parser.add_argument("--duplicate-threshold-pips", type=float, default=3.0)
    parser.add_argument(
        "--risk-yen",
        type=float,
        default=None,
        help="Override live base risk. Omitted uses the pair's current live base risk.",
    )
    parser.add_argument("--read-chunk-size", type=int, default=1000)
    args = parser.parse_args(argv)

    for field in ("train_start", "train_end", "oos_start", "oos_end"):
        setattr(args, field, pd.Timestamp(getattr(args, field)).to_pydatetime())
    if args.train_start >= args.train_end or args.oos_start >= args.oos_end:
        parser.error("Each start must be earlier than its end")
    if args.train_end != args.oos_start:
        parser.error("--train-end must equal --oos-start (no overlap or gap)")
    metrics = tuple(dict.fromkeys(value.strip().lower() for value in args.metrics.split(",")))
    if not metrics or set(metrics).difference(DEFAULT_METRICS):
        parser.error("--metrics supports only yen,pips")
    args.metrics = metrics
    for field in (
        "spread_pips",
        "min_target_pips",
        "trade_timeout_min",
        "profit_lock_ratio",
        "duplicate_threshold_pips",
        "read_chunk_size",
    ):
        value = float(getattr(args, field))
        if not math.isfinite(value) or value <= 0:
            parser.error(f"--{field.replace('_', '-')} must be finite and positive")
    if args.risk_yen is not None and (
        not math.isfinite(args.risk_yen) or args.risk_yen <= 0
    ):
        parser.error("--risk-yen must be finite and positive")
    args.min_target_pips = max(args.min_target_pips, args.spread_pips * 2.0)
    args.risk_yen = float(
        args.risk_yen
        if args.risk_yen is not None
        else line_analysis.base_risk_yen(args.pair, "live")
    )

    stem = (
        f"{args.pair}_{args.oos_start:%Y%m%d}_{args.oos_end:%Y%m%d}"
        f"_m5line60_range6x3_rr1.2_sp{args.spread_pips:g}_60m"
    )
    args.source_candidates = args.source_candidates or (
        Path(tk.folder_path) / f"resistance_sweep_candidates_{stem}.csv"
    )
    args.source_events = args.source_events or (
        Path(tk.folder_path) / f"resistance_sweep_events_{stem}.csv"
    )
    s5_stem = f"{args.pair}_{args.oos_start:%Y%m%d%H%M%S}_{args.oos_end:%Y%m%d%H%M%S}"
    args.s5_cache = args.s5_cache or (Path(tk.folder_path) / f"s5_{s5_stem}.csv")
    return args


def _ranking_paths(args: argparse.Namespace, metric: str) -> tuple[Path, Path]:
    period = f"{args.pair}_{args.train_start:%Y%m%d}_{args.train_end:%Y%m%d}"
    csv_path = args.ranking_dir / f"count2_prior2y_top_{metric}_{period}.csv"
    manifest = args.ranking_dir / f"count2_prior2y_ranking_{period}.json"
    return csv_path, manifest


def load_policies(args: argparse.Namespace, metric: str) -> tuple[list[Policy], Path, Path]:
    path, manifest_path = _ranking_paths(args, metric)
    if not path.is_file() or not manifest_path.is_file():
        raise FileNotFoundError(f"Completed prior-two-year ranking is missing: {path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        manifest.get("pair") != args.pair
        or pd.Timestamp(manifest.get("start_inclusive")) != pd.Timestamp(args.train_start)
        or pd.Timestamp(manifest.get("end_exclusive")) != pd.Timestamp(args.train_end)
        or manifest.get("selection", {}).get("future_data_read") is not False
        or manifest.get("guards", {}).get("condition_scope") != "shape"
    ):
        raise ValueError(f"Ranking manifest does not match the fixed training window: {manifest_path}")
    frame = pd.read_csv(path, low_memory=False)
    missing = REQUIRED_RANKING_COLUMNS.difference(frame.columns)
    if missing:
        raise ValueError("Ranking CSV lacks columns: " + ", ".join(sorted(missing)))
    expected_version = f"{args.pair.lower()}_{GRID_VERSION}"
    if set(frame["grid_version"].astype(str)) != {expected_version}:
        raise ValueError(f"Ranking is not the latest causal FC2-shape grid: {path}")
    if len(frame) != 15 or list(pd.to_numeric(frame["rank"])) != list(range(1, 16)):
        raise ValueError(f"Ranking must contain exactly ordered Top15 rows: {path}")
    expected_metric = "sum_yen" if metric == "yen" else "sum_pips"
    if set(frame["ranking_metric"].astype(str)) != {expected_metric}:
        raise ValueError(f"Ranking metric mismatch in {path}")

    policies: list[Policy] = []
    for row in frame.to_dict("records"):
        policy = Policy(
            rank=int(row["rank"]),
            metric=metric,
            order_name=str(row["order_name"]),
            condition_id=str(row["condition_id"]),
            entry_rank=int(row["entry_candidate_rank"]),
            offset_multiplier=float(row["entry_offset_range_multiplier"]),
            tp_multiplier=float(row["tp_range_multiplier"]),
            lc_multiplier=float(row["lc_range_multiplier"]),
        )
        if policy.entry_rank not in (1, 2, 3):
            raise ValueError(f"Unsupported raw entry rank in {path}: {policy.entry_rank}")
        numeric = (policy.offset_multiplier, policy.tp_multiplier, policy.lc_multiplier)
        if not all(math.isfinite(value) for value in numeric):
            raise ValueError(f"Non-finite policy parameter in {path}")
        if policy.tp_multiplier <= 0 or policy.lc_multiplier <= 0:
            raise ValueError(f"Non-positive TP/LC policy parameter in {path}")
        policies.append(policy)
    return policies, path.resolve(), manifest_path.resolve()


def _validate_source_headers(args: argparse.Namespace) -> None:
    for path in (args.source_candidates, args.source_events, args.s5_cache):
        if not Path(path).is_file():
            raise FileNotFoundError(f"Required OOS source is missing: {path}")
    with Path(args.source_candidates).open("r", encoding="utf-8-sig", newline="") as handle:
        columns = set(next(csv.reader(handle)))
    missing = REQUIRED_CANDIDATE_COLUMNS.difference(columns)
    if missing:
        raise ValueError(
            "OOS candidate ledger predates the latest FC2-shape logic; rerun the "
            f"pair's OOS source launcher. Missing: {', '.join(sorted(missing))}"
        )


def _validate_decision_snapshot(row: dict[str, Any], decision_time: pd.Timestamp) -> None:
    """Reject rows whose advertised completed-candle inputs cross the decision."""
    try:
        average_range = float(row.get("recent_m5_avg_range_pips"))
        peak_direction = float(row.get("peak_direction"))
    except (TypeError, ValueError) as error:
        raise ValueError(
            f"Invalid M5/H1 shape identity at {decision_time}"
        ) from error
    _validate_fc2_context(
        row,
        decision_time=decision_time,
        average_range=average_range,
        peak_direction=peak_direction,
        include_line=True,
    )
    _validate_h1_pair_context(
        row,
        decision_time=decision_time,
        peak_direction=peak_direction,
    )
    target_last = pd.to_datetime(row.get("target_source_last_time"), errors="coerce")
    if pd.isna(target_last) or target_last + pd.Timedelta(minutes=5) > decision_time:
        raise ValueError(
            f"Target-width source is missing or not completed at {decision_time}: "
            f"{target_last}"
        )
    line_newest = pd.to_datetime(row.get("line_newest_source_time"), errors="coerce")
    if pd.isna(line_newest) or line_newest + pd.Timedelta(minutes=5) > decision_time:
        raise ValueError(
            f"Resistance-line source is missing or after the decision at {decision_time}: "
            f"{line_newest}"
        )


def load_event_times(args: argparse.Namespace) -> list[tuple[str, pd.Timestamp]]:
    frame = pd.read_csv(
        args.source_events,
        usecols=["event_id", "pair", "decision_time"],
        low_memory=False,
    )
    if frame.empty:
        raise ValueError("OOS event ledger is empty")
    if set(frame["pair"].astype(str)) != {args.pair}:
        raise ValueError("OOS event ledger contains another pair")
    frame["decision_time"] = pd.to_datetime(frame["decision_time"], errors="raise")
    start, end = pd.Timestamp(args.oos_start), pd.Timestamp(args.oos_end)
    if not frame["decision_time"].between(start, end, inclusive="left").all():
        raise ValueError("OOS event ledger contains a decision outside the requested year")
    if frame["event_id"].duplicated().any() or not frame["decision_time"].is_monotonic_increasing:
        raise ValueError("OOS event ledger must be unique and chronological")
    return list(zip(frame["event_id"].astype(str), frame["decision_time"]))


def _event_groups(path: Path, chunksize: int) -> Iterable[tuple[str, list[dict[str, Any]]]]:
    carry: list[dict[str, Any]] = []
    carry_id: str | None = None
    seen: set[str] = set()
    for chunk in pd.read_csv(path, chunksize=chunksize, low_memory=False):
        for row in chunk.to_dict("records"):
            event_id = str(row.get("event_id"))
            if carry_id is None:
                carry_id = event_id
            if event_id != carry_id:
                if carry_id in seen:
                    raise ValueError(f"Candidate event rows are not contiguous: {carry_id}")
                seen.add(carry_id)
                yield carry_id, carry
                carry = []
                carry_id = event_id
            carry.append(row)
    if carry_id is not None:
        if carry_id in seen:
            raise ValueError(f"Candidate event rows are not contiguous: {carry_id}")
        yield carry_id, carry


def build_intents(
    args: argparse.Namespace,
    policies: list[Policy],
    event_times: list[tuple[str, pd.Timestamp]],
) -> dict[str, Intent]:
    pair = gene.currency_pair(args.pair)
    event_time_by_id = dict(event_times)
    intents: dict[str, Intent] = {}
    previous_time: pd.Timestamp | None = None
    for event_id, rows in _event_groups(Path(args.source_candidates), args.read_chunk_size):
        if event_id not in event_time_by_id:
            raise ValueError(f"Candidate event is absent from OOS event ledger: {event_id}")
        ranks: dict[int, dict[str, Any]] = {}
        for row in rows:
            if str(row.get("pair")) != args.pair:
                raise ValueError(f"Candidate pair mismatch at {event_id}")
            decision_time = pd.Timestamp(row["decision_time"])
            if decision_time != event_time_by_id[event_id]:
                raise ValueError(f"Candidate/event decision mismatch at {event_id}")
            _validate_decision_snapshot(row, decision_time)
            rank = int(float(row["distance_rank"]))
            if rank in ranks:
                raise ValueError(f"Duplicate raw distance rank at {event_id}: {rank}")
            ranks[rank] = row
        decision_time = event_time_by_id[event_id]
        if previous_time is not None and decision_time < previous_time:
            raise ValueError("OOS candidate ledger is not chronological")
        previous_time = decision_time

        memberships_by_rank: dict[int, set[str]] = {}
        selected: tuple[Policy, dict[str, Any]] | None = None
        for policy in policies:
            row = ranks.get(policy.entry_rank)
            if row is None:
                continue
            memberships = memberships_by_rank.get(policy.entry_rank)
            if memberships is None:
                memberships = {
                    item.condition_id for item in condition_memberships(row)
                }
                memberships_by_rank[policy.entry_rank] = memberships
            if policy.condition_id in memberships:
                selected = (policy, row)
                break
        if selected is None:
            continue
        policy, row = selected
        average_range = float(row["recent_m5_avg_range_pips"])
        peak_direction = int(float(row["peak_direction"]))
        direction = int(float(row["trade_direction"]))
        if peak_direction not in (-1, 1) or direction != -peak_direction:
            raise ValueError(f"Invalid peak/trade direction at {event_id}")
        entry = adjusted_entry_parameters(
            line_price=float(row["line_price"]),
            decision_price=float(row["decision_price"]),
            peak_direction=peak_direction,
            average_range_pips=average_range,
            offset_range_multiplier=policy.offset_multiplier,
            pair=pair,
            spread_pips=args.spread_pips,
        )
        if entry["marketable_limit"]:
            continue
        target_pips = executable_target_pips(
            np.asarray(
                [average_range * policy.tp_multiplier, average_range * policy.lc_multiplier]
            ),
            minimum_pips=args.min_target_pips,
            pair=pair,
        )
        priority_value = row.get("line_total_strength")
        try:
            priority = int(float(priority_value))
        except (TypeError, ValueError, OverflowError):
            priority = 0
        intents[event_id] = Intent(
            event_id=event_id,
            decision_time=decision_time,
            decision_price=float(row["decision_price"]),
            policy_rank=policy.rank,
            order_name=policy.order_name,
            condition_id=policy.condition_id,
            entry_rank=policy.entry_rank,
            direction=direction,
            entry_price=float(entry["entry_price"]),
            adjusted_distance_pips=float(entry["adjusted_distance_pips"]),
            entry_offset_pips=float(entry["entry_offset_pips"]),
            tp_pips=float(target_pips[0]),
            lc_pips=float(target_pips[1]),
            priority=priority,
        )
    return intents


def _slot_class(priority: int) -> str:
    if priority >= 100:
        return "high"
    if priority >= 10:
        return "mid"
    return "normal"


def _order_timeout_min(intent: Intent) -> int:
    return line_analysis.LineOrderCoordinator.order_timeout_min_for_distance(
        intent.adjusted_distance_pips,
        "m5",
        15,
    )


def _close_quote(mid_price: float, direction: int, half_spread_price: float) -> float:
    return mid_price - half_spread_price if direction == 1 else mid_price + half_spread_price


def _is_expected_no_quote_interval(
    inspector: Any,
    start_time: pd.Timestamp,
    next_quote_time: pd.Timestamp,
) -> bool:
    """Return true only when no tradable S5 should exist before the next quote."""
    start_time = pd.Timestamp(start_time)
    next_quote_time = pd.Timestamp(next_quote_time)
    if next_quote_time <= start_time:
        return False
    previous = start_time - pd.Timedelta(seconds=5)
    if bool(
        inspector._is_expected_market_closed_gap(previous, next_quote_time)
        or _is_expected_annual_holiday_closure_gap(previous, next_quote_time)
    ):
        return True
    return any(
        gap_previous < start_time < gap_following
        and next_quote_time == gap_following
        for gap_previous, gap_following in getattr(
            inspector,
            "_causally_proven_no_tick_gaps",
            (),
        )
    )


def _csv_truth(value: Any) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    return str(value).strip().lower() in {"true", "1", "1.0"}


def _causally_proven_no_tick_gaps(
    source: Path,
    gaps: list[tuple[pd.Timestamp, pd.Timestamp]],
) -> set[tuple[pd.Timestamp, pd.Timestamp]]:
    """Prove bounded residual no-tick gaps from the causal S5 CSV metadata.

    The acquisition layer fills at most the first fifteen minutes of a raw
    no-tick interval from the last known close.  A remaining tail is accepted
    only when its exact source endpoints show the completed 15-minute causal
    prefix followed by a real, positive-volume candle.  No price is created
    for the tail; replay state simply waits for the next available S5.
    """
    if not gaps:
        return set()
    source = Path(source)
    required = {
        "time_jp",
        "volume",
        "is_synthetic_s5",
        "synthetic_seconds_since_previous_actual",
        "s5_completion_causal_v2",
    }
    try:
        with source.open("r", encoding="utf-8-sig", newline="") as handle:
            columns = set(next(csv.reader(handle)))
    except (OSError, StopIteration):
        return set()
    if not required.issubset(columns):
        return set()

    labels = {
        timestamp.strftime("%Y/%m/%d %H:%M:%S")
        for gap in gaps
        for timestamp in gap
    }
    rows: dict[str, dict[str, Any]] = {}
    for chunk in pd.read_csv(
        source,
        usecols=sorted(required),
        chunksize=250_000,
        low_memory=False,
    ):
        matches = chunk[chunk["time_jp"].astype(str).isin(labels)]
        for row in matches.to_dict("records"):
            rows[str(row["time_jp"])] = row
        if labels.issubset(rows):
            break

    proven: set[tuple[pd.Timestamp, pd.Timestamp]] = set()
    maximum_tail = pd.Timedelta(minutes=15)
    causal_prefix_seconds = 15 * 60
    for previous, following in gaps:
        gap = following - previous
        if (
            gap <= pd.Timedelta(seconds=5)
            or gap > maximum_tail
            or gap % pd.Timedelta(seconds=5) != pd.Timedelta(0)
        ):
            continue
        previous_row = rows.get(previous.strftime("%Y/%m/%d %H:%M:%S"))
        following_row = rows.get(following.strftime("%Y/%m/%d %H:%M:%S"))
        if previous_row is None or following_row is None:
            continue
        try:
            elapsed = float(
                previous_row["synthetic_seconds_since_previous_actual"]
            )
            previous_volume = float(previous_row["volume"])
            following_volume = float(following_row["volume"])
        except (TypeError, ValueError):
            continue
        if (
            _csv_truth(previous_row["s5_completion_causal_v2"])
            and _csv_truth(following_row["s5_completion_causal_v2"])
            and _csv_truth(previous_row["is_synthetic_s5"])
            and not _csv_truth(following_row["is_synthetic_s5"])
            and math.isclose(
                elapsed,
                causal_prefix_seconds,
                rel_tol=0.0,
                abs_tol=1e-9,
            )
            and previous_volume == 0
            and following_volume > 0
        ):
            proven.add((previous, following))
    return proven


def _validate_s5_timeline(
    inspector: Any,
    *,
    s5_source: Path | None = None,
) -> None:
    """Reject every unknown interior gap; weekends/known closures remain valid."""
    times = inspector.times
    if not len(times):
        raise ValueError("Replay S5 cache is empty")
    unexpected = np.flatnonzero(np.diff(times) != np.timedelta64(5, "s"))
    unresolved: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    for index in unexpected:
        previous = pd.Timestamp(times[int(index)])
        following = pd.Timestamp(times[int(index) + 1])
        if inspector._is_expected_market_closed_gap(previous, following):
            continue
        if _is_expected_annual_holiday_closure_gap(previous, following):
            continue
        unresolved.append((previous, following))
    proven = (
        _causally_proven_no_tick_gaps(Path(s5_source), unresolved)
        if s5_source is not None
        else set()
    )
    setattr(
        inspector,
        "_causally_proven_no_tick_gaps",
        tuple(sorted(proven)),
    )
    for previous, following in unresolved:
        if (previous, following) in proven:
            continue
        raise ValueError(
            f"Unknown S5 gap inside replay period: {previous} -> {following}"
        )


def _result_yen(pair: gene.CurrencyPair, result_pips: float, lc_pips: float, risk_yen: float) -> float:
    result_r = result_pips / lc_pips
    if pair.name != "USD_JPY":
        return result_r * risk_yen
    units = gene.calculate_units(
        pair,
        pair.pips_to_price(lc_pips),
        risk_yen=risk_yen,
        rounding_tag="l",
    )
    return result_pips * pair.pip_value * units


def _trade_row(
    pair: gene.CurrencyPair,
    position: OpenPosition,
    *,
    exit_time: pd.Timestamp,
    exit_price: float,
    result_type: str,
) -> dict[str, Any]:
    intent = position.intent
    result_pips = (
        intent.direction * (float(exit_price) - intent.entry_price) / pair.pip_value
    )
    result_r = result_pips / intent.lc_pips
    return {
        "event_id": intent.event_id,
        "decision_time": intent.decision_time,
        "order_name": intent.order_name,
        "policy_rank": intent.policy_rank,
        "condition_id": intent.condition_id,
        "entry_rank": intent.entry_rank,
        "direction": intent.direction,
        "entry_price": intent.entry_price,
        "fill_time": position.fill_time,
        "exit_time": exit_time,
        "exit_price": float(exit_price),
        "result_type": result_type,
        "result_pips": result_pips,
        "result_r": result_r,
        "result_yen": _result_yen(pair, result_pips, intent.lc_pips, position.risk_yen),
        "tp_pips": intent.tp_pips,
        "lc_pips": intent.lc_pips,
        "order_delay_min": (position.fill_time - intent.decision_time).total_seconds() / 60,
        "holding_min": (exit_time - position.fill_time).total_seconds() / 60,
        "profit_lock_done": position.profit_lock_done,
        "profit_lock_step_index": position.profit_lock_step_index,
        "trade_timeout_evaluated": position.trade_timeout_evaluated,
        "loss_cap_done": position.loss_cap_done,
        "loss_cap_r": position.loss_cap_r,
        "loss_stage_applied_count": position.loss_stage_applied_count,
        "loss_stage_index": position.loss_stage_last_index,
        "loss_stage_name": position.loss_stage_last_name,
        "loss_stage_action": position.loss_stage_last_action,
        "loss_stage_action_time": position.loss_stage_last_action_time,
        "loss_stage_action_r": position.loss_stage_last_action_r,
        "loss_stage_result_r": position.loss_stage_last_action_r,
        "loss_stage_history": json.dumps(
            position.loss_stage_history,
            ensure_ascii=False,
            default=str,
            separators=(",", ":"),
        ),
        "final_lc_price": position.current_lc_price,
        "final_lc_pips": (
            intent.direction
            * (position.current_lc_price - intent.entry_price)
            / pair.pip_value
        ),
        "max_favorable_pips": position.max_favorable_pips,
        "max_adverse_pips": position.max_adverse_pips,
        "risk_yen": position.risk_yen,
    }


def replay_metric(
    args: argparse.Namespace,
    metric: str,
    policies: list[Policy],
    event_times: list[tuple[str, pd.Timestamp]],
    intents: dict[str, Intent],
    inspector: Any,
    *,
    management_policy: ExitManagementPolicy = CURRENT_EXIT_POLICY,
    progress_callback: Callable[[int, dict[str, int], int, bool], None] | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    pair = gene.currency_pair(args.pair)
    half_spread = pair.pips_to_price(args.spread_pips / 2.0)
    event_index = 0
    pending: PendingOrder | None = None
    positions: list[OpenPosition] = []
    trades: list[dict[str, Any]] = []
    counters: dict[str, int] = {
        "events": len(event_times),
        "matched_intents": len(intents),
        "submitted": 0,
        "filled": 0,
        "not_filled_timeout": 0,
        "cancelled_period_end": 0,
        "cancelled_next_count2": 0,
        "blocked_unprotected_position": 0,
        "blocked_duplicate": 0,
        "blocked_slot_capacity": 0,
        "blocked_opposite": 0,
        "opposite_profit_closed": 0,
        "profit_locks": 0,
        "profit_lock_updates": 0,
        "loss_caps": 0,
        "loss_cap_immediate_exits": 0,
        "loss_timeout_market_exits": 0,
        "loss_stage_actions": 0,
        "loss_stage_caps": 0,
        "loss_stage_cap_updates": 0,
        "loss_stage_cap_immediate_exits": 0,
        "loss_stage_market_exits": 0,
        "loss_stage_boundary_skips": 0,
        "decisions_activated_at_next_s5_after_closure": 0,
    }
    slot_caps = {"normal": 6, "mid": 8, "high": 1}
    last_notice_percent = -1
    last_close = None
    last_time = None

    def close_position(position: OpenPosition, when: pd.Timestamp, price: float, kind: str) -> None:
        trades.append(
            _trade_row(pair, position, exit_time=when, exit_price=price, result_type=kind)
        )
        positions.remove(position)

    def apply_next_loss_stage(
        position: OpenPosition,
        *,
        bar_time: pd.Timestamp,
        close_quote: float,
        current_r: float,
    ) -> bool:
        """Apply at most one due stage using only this completed S5 close."""
        stages = management_policy.loss_stages
        while position.loss_stage_next_index < len(stages):
            stage_index = position.loss_stage_next_index
            stage = stages[stage_index]
            elapsed = (bar_time + pd.Timedelta(seconds=5)) - position.fill_time
            if elapsed < pd.Timedelta(minutes=stage.after_min):
                return False

            trigger_reached = current_r < stage.trigger_r_max or math.isclose(
                current_r,
                stage.trigger_r_max,
                rel_tol=0.0,
                abs_tol=1e-12,
            )
            if not trigger_reached:
                if stage.evaluation == "armed":
                    return False
                position.loss_stage_next_index += 1
                counters["loss_stage_boundary_skips"] += 1
                continue

            stage_name = stage.name or f"loss_stage_{stage_index + 1}"
            position.loss_stage_next_index += 1
            position.loss_stage_applied_count += 1
            position.loss_stage_last_index = stage_index
            position.loss_stage_last_name = stage_name
            position.loss_stage_last_action = stage.action
            position.loss_stage_last_action_time = bar_time
            position.loss_stage_last_action_r = current_r
            position.loss_stage_history.append(
                {
                    "index": stage_index,
                    "name": stage_name,
                    "action": stage.action,
                    "action_time": bar_time,
                    "current_r": current_r,
                    "cap_r": stage.cap_r,
                    "trigger_r_max": stage.trigger_r_max,
                    "evaluation": stage.evaluation,
                }
            )
            counters["loss_stage_actions"] += 1

            if stage.action == "market_exit":
                counters["loss_stage_market_exits"] += 1
                close_position(
                    position,
                    bar_time,
                    close_quote,
                    "loss_stage_market_exit",
                )
                return True

            assert stage.cap_r is not None
            cap_price = pair.round_price(
                position.intent.entry_price
                - position.intent.direction
                * pair.pips_to_price(position.intent.lc_pips * stage.cap_r)
            )
            counters["loss_stage_caps"] += 1
            position.loss_cap_done = True
            position.loss_cap_r = stage.cap_r
            if position.intent.direction * (close_quote - cap_price) <= 0:
                counters["loss_stage_cap_immediate_exits"] += 1
                counters["loss_cap_immediate_exits"] += 1
                close_position(
                    position,
                    bar_time,
                    close_quote,
                    "loss_stage_cap_immediate_exit",
                )
                return True
            if (
                position.intent.direction
                * (cap_price - position.current_lc_price)
                > 0
            ):
                position.current_lc_price = cap_price
                counters["loss_stage_cap_updates"] += 1
            counters["loss_caps"] += 1
            return False
        return False

    def process_event(event_id: str, event_time: pd.Timestamp) -> None:
        nonlocal pending
        if pending is not None:
            counters["cancelled_next_count2"] += 1
            pending = None
        intent = intents.get(event_id)
        if intent is None:
            return
        if any(not position.allow_followup_order for position in positions):
            counters["blocked_unprotected_position"] += 1
            return
        if any(
            position.intent.direction == intent.direction
            and abs(position.intent.entry_price - intent.entry_price) / pair.pip_value
            <= args.duplicate_threshold_pips
            for position in positions
        ):
            counters["blocked_duplicate"] += 1
            return

        opposite = [p for p in positions if p.intent.direction == -intent.direction]
        if opposite:
            profitable = []
            for position in opposite:
                quote = _close_quote(intent.decision_price, position.intent.direction, half_spread)
                pips = (
                    position.intent.direction
                    * (quote - position.intent.entry_price)
                    / pair.pip_value
                )
                if pips > 0:
                    profitable.append((position, quote))
            if profitable:
                for position, quote in profitable:
                    close_position(position, event_time, quote, "opposite_profit_close")
                    counters["opposite_profit_closed"] += 1
            counters["blocked_opposite"] += 1
            return

        slot = _slot_class(intent.priority)
        if sum(position.slot_class == slot for position in positions) >= slot_caps[slot]:
            counters["blocked_slot_capacity"] += 1
            return
        timeout_min = _order_timeout_min(intent)
        pending = PendingOrder(
            intent=intent,
            expiry_time=event_time + pd.Timedelta(minutes=timeout_min),
        )
        counters["submitted"] += 1

    total_bars = len(inspector.times)
    for bar_index in range(total_bars):
        bar_time = pd.Timestamp(inspector.times[bar_index])
        while event_index < len(event_times) and event_times[event_index][1] <= bar_time:
            event_id, event_time = event_times[event_index]
            # Preserve wall-clock ordering while several decisions wait for
            # the first S5 after a no-quote interval.  An already expired order
            # must time out before a later decision can cancel it.
            if pending is not None and event_time > pending.expiry_time:
                counters["not_filled_timeout"] += 1
                pending = None
            if event_time < bar_time:
                if not _is_expected_no_quote_interval(inspector, event_time, bar_time):
                    raise ValueError(
                        f"Decision-time S5 is missing at {event_time}; "
                        "replay cannot infer order state"
                    )
                counters["decisions_activated_at_next_s5_after_closure"] += 1
            process_event(event_id, event_time)
            event_index += 1

        # A decision inside a long closure can itself expire before the first
        # later S5.  Do not let that expired order fill on the reopening bar.
        if pending is not None and bar_time > pending.expiry_time:
            counters["not_filled_timeout"] += 1
            pending = None

        open_mid = float(inspector.opens[bar_index])
        high_mid = float(inspector.highs[bar_index])
        low_mid = float(inspector.lows[bar_index])
        close_mid = float(inspector.closes[bar_index])
        last_close = close_mid
        last_time = bar_time

        if pending is not None:
            intent = pending.intent
            fill_touch = (
                low_mid <= intent.entry_price - half_spread
                if intent.direction == 1
                else high_mid >= intent.entry_price + half_spread
            )
            if fill_touch:
                fill_at_open = (
                    open_mid + half_spread <= intent.entry_price
                    if intent.direction == 1
                    else open_mid - half_spread >= intent.entry_price
                )
                tp_price = pair.round_price(
                    intent.entry_price + intent.direction * pair.pips_to_price(intent.tp_pips)
                )
                lc_price = pair.round_price(
                    intent.entry_price - intent.direction * pair.pips_to_price(intent.lc_pips)
                )
                positions.append(
                    OpenPosition(
                        intent=intent,
                        fill_time=bar_time,
                        fill_at_open=bool(fill_at_open),
                        original_lc_price=lc_price,
                        current_lc_price=lc_price,
                        tp_price=tp_price,
                        risk_yen=args.risk_yen,
                        slot_class=_slot_class(intent.priority),
                    )
                )
                counters["filled"] += 1
                pending = None

        for position in list(positions):
            direction = position.intent.direction
            if direction == 1:
                favorable_quote = high_mid - half_spread
                adverse_quote = low_mid - half_spread
                close_quote = close_mid - half_spread
                tp_touch = favorable_quote >= position.tp_price
                lc_touch = adverse_quote <= position.current_lc_price
                close_confirms_tp = close_quote >= position.tp_price
            else:
                favorable_quote = low_mid + half_spread
                adverse_quote = high_mid + half_spread
                close_quote = close_mid + half_spread
                tp_touch = favorable_quote <= position.tp_price
                lc_touch = adverse_quote >= position.current_lc_price
                close_confirms_tp = close_quote <= position.tp_price
            favorable_pips = direction * (
                favorable_quote - position.intent.entry_price
            ) / pair.pip_value
            adverse_pips = direction * (
                adverse_quote - position.intent.entry_price
            ) / pair.pip_value
            position.max_favorable_pips = max(position.max_favorable_pips, favorable_pips)
            position.max_adverse_pips = min(position.max_adverse_pips, adverse_pips)

            fill_bar = bar_time == position.fill_time
            valid_tp_touch = bool(
                tp_touch and (not fill_bar or position.fill_at_open or close_confirms_tp)
            )
            if lc_touch:
                if valid_tp_touch:
                    kind = "both_same_s5_lc_assumed"
                elif (
                    position.loss_stage_applied_count > 0
                    and position.loss_stage_last_action == "cap"
                    and not position.profit_lock_done
                ):
                    kind = "loss_stage_cap_lc"
                elif position.loss_cap_done and not position.profit_lock_done:
                    kind = "loss_cap_lc"
                else:
                    kind = "lc"
                close_position(position, bar_time, position.current_lc_price, kind)
                continue
            if valid_tp_touch:
                close_position(position, bar_time, position.tp_price, "tp")
                continue

            current_pips = direction * (
                close_quote - position.intent.entry_price
            ) / pair.pip_value
            if management_policy.loss_stages:
                current_r = current_pips / position.intent.lc_pips
                if apply_next_loss_stage(
                    position,
                    bar_time=bar_time,
                    close_quote=close_quote,
                    current_r=current_r,
                ):
                    continue

            timeout_reached = (
                (bar_time + pd.Timedelta(seconds=5)) - position.fill_time
                >= pd.Timedelta(minutes=args.trade_timeout_min)
            )
            if timeout_reached:
                if not position.trade_timeout_evaluated:
                    position.trade_timeout_evaluated = True
                    if current_pips <= 0 and management_policy.loss_action == "market_exit":
                        counters["loss_timeout_market_exits"] += 1
                        close_position(
                            position,
                            bar_time,
                            close_quote,
                            "loss_timeout_market_exit",
                        )
                        continue
                    if current_pips <= 0 and management_policy.loss_action == "cap":
                        assert management_policy.loss_cap_r is not None
                        cap_price = pair.round_price(
                            position.intent.entry_price
                            - direction
                            * pair.pips_to_price(
                                position.intent.lc_pips * management_policy.loss_cap_r
                            )
                        )
                        if direction * (close_quote - cap_price) <= 0:
                            counters["loss_cap_immediate_exits"] += 1
                            close_position(
                                position,
                                bar_time,
                                close_quote,
                                "loss_cap_immediate_exit",
                            )
                            continue
                        if direction * (cap_price - position.current_lc_price) > 0:
                            position.current_lc_price = cap_price
                        position.loss_cap_done = True
                        position.loss_cap_r = management_policy.loss_cap_r
                        counters["loss_caps"] += 1

                if (
                    management_policy.profit_lock_enabled
                    and management_policy.step_trigger_tp_fractions
                ):
                    step_index = position.profit_lock_step_index
                    fractions = management_policy.step_trigger_tp_fractions
                    if step_index < len(fractions):
                        trigger_pips = position.intent.tp_pips * fractions[step_index]
                        trigger_reached = current_pips > trigger_pips or math.isclose(
                            current_pips,
                            trigger_pips,
                            rel_tol=0.0,
                            abs_tol=1e-9,
                        )
                        if trigger_reached:
                            assert (
                                management_policy.step_ensure_trigger_ratio is not None
                            )
                            ensure_pips = (
                                trigger_pips
                                * management_policy.step_ensure_trigger_ratio
                            )
                            lock_price = pair.round_price(
                                position.intent.entry_price
                                + direction * ensure_pips * pair.pip_value
                            )
                            position.profit_lock_step_index += 1
                            if (
                                direction
                                * (lock_price - position.current_lc_price)
                                > 0
                            ):
                                position.current_lc_price = lock_price
                                counters["profit_lock_updates"] += 1
                                if (
                                    not position.profit_lock_done
                                    and direction
                                    * (lock_price - position.intent.entry_price)
                                    > 0
                                ):
                                    position.profit_lock_done = True
                                    position.allow_followup_order = True
                                    counters["profit_locks"] += 1
                elif (
                    management_policy.profit_lock_enabled
                    and not position.profit_lock_done
                    and current_pips > 0
                ):
                    lock_price = pair.round_price(
                        position.intent.entry_price
                        + direction
                        * pair.pips_to_price(current_pips * args.profit_lock_ratio)
                    )
                    if direction * (lock_price - position.current_lc_price) > 0:
                        position.current_lc_price = lock_price
                    position.profit_lock_done = True
                    position.allow_followup_order = True
                    counters["profit_locks"] += 1
                    counters["profit_lock_updates"] += 1

        percent = int(100 * (bar_index + 1) / max(total_bars, 1))
        if percent // 25 > last_notice_percent // 25:
            last_notice_percent = percent
            if progress_callback is None:
                _write_progress(
                    args,
                    metric,
                    percent,
                    counters,
                    len(positions),
                    pending is not None,
                )
            else:
                progress_callback(percent, counters, len(positions), pending is not None)

    if event_index != len(event_times):
        raise ValueError("OOS S5 ends before the final causal decision")
    if pending is not None:
        counters["cancelled_period_end"] += 1
    if last_close is None or last_time is None:
        raise ValueError("OOS S5 replay contains no bars")
    for position in list(positions):
        quote = _close_quote(last_close, position.intent.direction, half_spread)
        close_position(position, last_time, quote, "period_end_mark")

    trades_frame = pd.DataFrame(trades)
    if trades_frame.empty:
        summary = {
            **counters,
            "management_policy": management_policy.name,
            "completed_trades": 0,
            "sum_yen": 0.0,
            "sum_pips": 0.0,
        }
        return trades_frame, summary
    trades_frame = trades_frame.sort_values(["exit_time", "fill_time"], kind="stable")
    trades_frame["management_policy"] = management_policy.name
    trades_frame["cumulative_yen"] = trades_frame["result_yen"].cumsum()
    running_high = trades_frame["cumulative_yen"].cummax().clip(lower=0)
    drawdown = trades_frame["cumulative_yen"] - running_high
    summary = {
        **counters,
        "management_policy": management_policy.name,
        "completed_trades": int(len(trades_frame)),
        "wins": int((trades_frame["result_pips"] > 0).sum()),
        "losses": int((trades_frame["result_pips"] < 0).sum()),
        "win_rate": float((trades_frame["result_pips"] > 0).mean()),
        "sum_yen": float(trades_frame["result_yen"].sum()),
        "sum_pips": float(trades_frame["result_pips"].sum()),
        "average_pips": float(trades_frame["result_pips"].mean()),
        "average_win_pips": float(
            trades_frame.loc[trades_frame["result_pips"] > 0, "result_pips"].mean()
        ),
        "average_loss_pips": float(
            trades_frame.loc[trades_frame["result_pips"] < 0, "result_pips"].mean()
        ),
        "max_drawdown_yen": float(drawdown.min()),
        "period_end_mark_count": int((trades_frame["result_type"] == "period_end_mark").sum()),
    }
    return trades_frame, summary


def _monthly_summary(trades: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "month",
        "trades",
        "wins",
        "win_rate",
        "sum_yen",
        "sum_pips",
        "average_pips",
        "average_win_pips",
        "average_loss_pips",
    ]
    if trades.empty:
        return pd.DataFrame(columns=columns)
    work = trades.copy()
    work["month"] = pd.to_datetime(work["exit_time"]).dt.strftime("%Y-%m")
    rows = []
    for month, group in work.groupby("month", sort=True):
        positive = group[group["result_pips"] > 0]
        negative = group[group["result_pips"] < 0]
        rows.append({
            "month": month,
            "trades": len(group),
            "wins": int((group["result_pips"] > 0).sum()),
            "win_rate": float((group["result_pips"] > 0).mean()),
            "sum_yen": float(group["result_yen"].sum()),
            "sum_pips": float(group["result_pips"].sum()),
            "average_pips": float(group["result_pips"].mean()),
            "average_win_pips": float(positive["result_pips"].mean()),
            "average_loss_pips": float(negative["result_pips"].mean()),
        })
    return pd.DataFrame(rows, columns=columns)


def _output_paths(args: argparse.Namespace, metric: str) -> dict[str, Path]:
    stem = (
        f"{metric}_{args.pair}_{args.train_start:%Y%m%d}_{args.train_end:%Y%m%d}"
        f"_to_{args.oos_start:%Y%m%d}_{args.oos_end:%Y%m%d}"
    )
    return {
        "trades": args.output_dir / f"count2_prior2y_oos_trades_{stem}.csv",
        "monthly": args.output_dir / f"count2_prior2y_oos_monthly_{stem}.csv",
        "summary": args.output_dir / f"count2_prior2y_oos_summary_{stem}.json",
        "progress": args.output_dir / f"count2_prior2y_oos_progress_{stem}.json",
    }


def _write_progress(
    args: argparse.Namespace,
    metric: str,
    percent: int,
    counters: dict[str, int],
    open_positions: int,
    pending: bool,
) -> None:
    if args.output_dir is None:
        return
    path = _output_paths(args, metric)["progress"]
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "pair": args.pair,
        "metric": metric,
        "status": "running",
        "progress_percent": percent,
        "counters": counters,
        "open_positions": open_positions,
        "pending_order": pending,
        "updated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _write_outputs(
    args: argparse.Namespace,
    metric: str,
    trades: pd.DataFrame,
    summary: dict[str, Any],
    policies: list[Policy],
    ranking_path: Path,
    ranking_manifest: Path,
    elapsed_seconds: float,
) -> dict[str, Path]:
    paths = _output_paths(args, metric)
    paths["trades"].parent.mkdir(parents=True, exist_ok=True)
    for path in paths.values():
        if path.exists():
            _archive_file(path)
        temporary = path.with_suffix(path.suffix + ".tmp")
        if temporary.exists():
            _archive_file(temporary)
    monthly = _monthly_summary(trades)
    trades_tmp = paths["trades"].with_suffix(".csv.tmp")
    monthly_tmp = paths["monthly"].with_suffix(".csv.tmp")
    summary_tmp = paths["summary"].with_suffix(".json.tmp")
    try:
        trades.to_csv(trades_tmp, index=False, encoding="utf-8-sig")
        monthly.to_csv(monthly_tmp, index=False, encoding="utf-8-sig")
        payload = {
            "status": "complete",
            "pair": args.pair,
            "ranking_metric": metric,
            "train_start_inclusive": args.train_start,
            "train_end_exclusive": args.train_end,
            "oos_start_inclusive": args.oos_start,
            "oos_end_exclusive": args.oos_end,
            "ranking_csv": str(ranking_path),
            "ranking_manifest": str(ranking_manifest),
            "ranking_reselected_on_oos": False,
            "policies": [asdict(policy) for policy in policies],
            "source_candidates": str(Path(args.source_candidates).resolve()),
            "source_events": str(Path(args.source_events).resolve()),
            "s5_cache": str(Path(args.s5_cache).resolve()),
            "settings": {
                "spread_pips": args.spread_pips,
                "min_target_pips": args.min_target_pips,
                "risk_yen": args.risk_yen,
                "order_timeout": "live distance-based 15/30/45 minutes",
                "trade_timeout_min": args.trade_timeout_min,
                "profit_lock_ratio": args.profit_lock_ratio,
                "allow_followup_order_before_lock": False,
                "duplicate_threshold_pips": args.duplicate_threshold_pips,
            },
            "future_safety": {
                "training_and_oos_non_overlapping": True,
                "ranking_fixed_before_oos_start": True,
                "decision_conditions_from_causal_sweep_only": True,
                "m5_h1_shape_schema_and_version_enforced": True,
                "h1_pair_completed_before_each_decision_enforced": True,
                "next_count2_time_not_read_at_decision": True,
                "s5_read_only_at_or_after_decision": True,
                "s5_at_or_after_oos_end_excluded": True,
                "unknown_s5_gaps_rejected": True,
                "residual_no_tick_gaps_require_causal_csv_proof": True,
                "decision_in_proven_no_tick_gap_waits_for_next_s5": True,
                "known_christmas_and_new_year_closures_allowed": True,
                "closed_market_decision_uses_next_actual_s5_for_first_path_bar": True,
            },
            "result": summary,
            "elapsed_seconds": elapsed_seconds,
            "outputs": {key: str(value) for key, value in paths.items()},
            "limitations": [
                "S5 OHLC cannot identify tick order inside one five-second bar; LC wins same-bar ambiguity.",
                "Profit-lock updates are approximated at the S5 close, while live polling can occur inside the bar.",
                "Cross-pair yen is fixed-risk normalized (result R times risk_yen), avoiding a future FX conversion rate.",
                "A profitable opposite position is closed and the new cycle blocked; other opposite positions block. Stop-and-reverse is not inferred without the live API trade payload.",
                "Positions still open at OOS end are marked at the final in-period executable close and labeled period_end_mark.",
                "Known Christmas/New-Year closures carry existing state to the next actual quote; no holiday price is synthesized.",
                "A bounded residual no-tick tail is carried only when causal-v2 CSV metadata proves a 15-minute synthetic prefix followed by a real positive-volume S5; no tail price is synthesized.",
                "A decision during a verified market closure keeps its original causal decision time and wall-clock order expiry; path evaluation starts at the next actual S5.",
            ],
        }
        summary_tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        trades_tmp.replace(paths["trades"])
        monthly_tmp.replace(paths["monthly"])
        summary_tmp.replace(paths["summary"])
        progress_payload = {
            "status": "complete",
            "pair": args.pair,
            "metric": metric,
            "progress_percent": 100,
            "updated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        paths["progress"].write_text(
            json.dumps(progress_payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        paths["progress"] = _archive_file(paths["progress"])
    except Exception:
        for path in list(paths.values()) + [trades_tmp, monthly_tmp, summary_tmp]:
            if path.exists():
                _archive_file(path)
        raise
    return paths


def _notice_result(args: argparse.Namespace, metric: str, summary: dict[str, Any], paths: dict[str, Path]) -> None:
    label = "円 Top15" if metric == "yen" else "pips Top15"
    lines = [
        f"{args.pair} prior-2y {label} / following-1y 仮想運用 完了",
        f"- 学習期間: {args.train_start:%Y-%m-%d} 以上 ～ {args.train_end:%Y-%m-%d} 未満",
        f"- OOS期間: {args.oos_start:%Y-%m-%d} 以上 ～ {args.oos_end:%Y-%m-%d} 未満",
        f"- 注文: {summary.get('submitted', 0)}件 / 約定: {summary.get('filled', 0)}件",
        f"- 完了取引: {summary.get('completed_trades', 0)}件",
        f"- 純損益: {summary.get('sum_yen', 0):.0f}円",
        f"- 損益pips: {summary.get('sum_pips', 0):.2f}pips",
        f"- 勝率: {100 * summary.get('win_rate', 0):.1f}%",
        f"- 最大DD: {summary.get('max_drawdown_yen', 0):.0f}円",
        f"- 月別: {paths['monthly']}",
        "- 条件は過去2年ランキングで固定し、OOS期間内では再選択していません",
    ]
    message = "\n".join(lines)
    print(message)
    win_point.send_inspection_notice(message)


def run(args: argparse.Namespace) -> dict[str, dict[str, Path]]:
    _validate_source_headers(args)
    event_times = load_event_times(args)
    pair = gene.currency_pair(args.pair)
    inspector, _metadata = _load_typed_s5_inspector(Path(args.s5_cache), pair)
    inspector = _bound_inspector_before(inspector, pd.Timestamp(args.oos_end))
    _validate_s5_timeline(inspector, s5_source=Path(args.s5_cache))
    coverage_args = argparse.Namespace(start=args.oos_start, end=args.oos_end)
    errors = _s5_coverage_errors(inspector.times, coverage_args)
    if errors:
        raise ValueError("OOS S5 coverage is incomplete: " + " | ".join(errors))

    outputs: dict[str, dict[str, Path]] = {}
    try:
        for metric in args.metrics:
            started = time.monotonic()
            policies, ranking_path, ranking_manifest = load_policies(args, metric)
            intents = build_intents(args, policies, event_times)
            trades, summary = replay_metric(
                args,
                metric,
                policies,
                event_times,
                intents,
                inspector,
            )
            paths = _write_outputs(
                args,
                metric,
                trades,
                summary,
                policies,
                ranking_path,
                ranking_manifest,
                time.monotonic() - started,
            )
            _notice_result(args, metric, summary, paths)
            outputs[metric] = paths
    except Exception as error:
        win_point.send_inspection_notice(
            "\n".join([
                f"{args.pair} prior-2y Top15 / following-1y 仮想運用 異常終了",
                f"- エラー種別: {type(error).__name__}",
                f"- 内容: {error}",
                "- temp/progress: archive移動対象",
            ])
        )
        for metric in args.metrics:
            paths = _output_paths(args, metric)
            for path in paths.values():
                temporary = path.with_suffix(path.suffix + ".tmp")
                if temporary.exists():
                    _archive_file(temporary)
                if path.name.startswith("count2_prior2y_oos_progress_") and path.exists():
                    _archive_file(path)
        raise
    return outputs


def main(
    argv: list[str] | None = None,
    *,
    default_pair: str = "USD_JPY",
    default_train_start: dt.datetime = DEFAULT_TRAIN_START,
    default_train_end: dt.datetime = DEFAULT_TRAIN_END,
    default_oos_start: dt.datetime = DEFAULT_OOS_START,
    default_oos_end: dt.datetime = DEFAULT_OOS_END,
) -> dict[str, dict[str, Path]]:
    return run(
        parse_args(
            argv,
            default_pair=default_pair,
            default_train_start=default_train_start,
            default_train_end=default_train_end,
            default_oos_start=default_oos_start,
            default_oos_end=default_oos_end,
        )
    )


if __name__ == "__main__":
    main()
