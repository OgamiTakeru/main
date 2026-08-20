"""Replay a frozen lifecycle-training artifact on the following period.

The selection artifact is the sole policy input.  This process never loads a
training ranking, training candidate ledger, or training S5 cache, and it has
no code path that can re-rank either conditions or exit management on the
following period.  The following window is always treated as half-open and
starts from a flat simulated portfolio.

The configured 2025-07-30--2026-07-30 window has already been inspected during
development, so its result is labelled diagnostic rather than pristine OOS.
Future unused windows can reuse the same runner by changing only the four
boundaries in the thin launcher.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd

import fGeneric as gene
import test_win_point_usd_aud as win_point
import tokens as tk
from count2_prior2y_oos_replay import (
    DEFAULT_OOS_END,
    DEFAULT_OOS_START,
    DEFAULT_TRAIN_END,
    DEFAULT_TRAIN_START,
    ExitManagementPolicy,
    Policy,
    _archive_file,
    _monthly_summary,
    _validate_s5_timeline,
    _validate_source_headers,
    build_intents,
    exit_management_policy_from_dict,
    load_event_times,
    replay_metric,
)
from count2_target_grid_search import (
    _load_typed_s5_inspector,
    _s5_coverage_errors,
)


TRAIN_ARTIFACT_VERSION = "count2_lifecycle_train_v1"
FIXED_REPLAY_VERSION = "count2_lifecycle_fixed_replay_v1"
KNOWN_REVIEWED_FOLLOWING_START = dt.datetime(2025, 7, 30)
KNOWN_REVIEWED_FOLLOWING_END = dt.datetime(2026, 7, 30)
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
    "order_delay_min",
    "holding_min",
    "profit_lock_done",
    "profit_lock_step_index",
    "trade_timeout_evaluated",
    "loss_cap_done",
    "loss_cap_r",
    "loss_stage_applied_count",
    "loss_stage_index",
    "loss_stage_name",
    "loss_stage_action",
    "loss_stage_action_time",
    "loss_stage_action_r",
    "loss_stage_result_r",
    "loss_stage_history",
    "final_lc_price",
    "final_lc_pips",
    "max_favorable_pips",
    "max_adverse_pips",
    "risk_yen",
    "management_policy",
    "cumulative_yen",
)


def _period_stem(args: argparse.Namespace) -> str:
    return (
        f"{args.pair}_{args.train_start:%Y%m%d}_{args.train_end:%Y%m%d}"
        f"_to_{args.following_start:%Y%m%d}_{args.following_end:%Y%m%d}"
    )


def _default_artifact_path(args: argparse.Namespace) -> Path:
    return Path(args.output_dir) / (
        f"{TRAIN_ARTIFACT_VERSION}_artifact_{_period_stem(args)}.json"
    )


def _following_candidate_path(args: argparse.Namespace, spread_pips: float) -> Path:
    stem = (
        f"{args.pair}_{args.following_start:%Y%m%d}_{args.following_end:%Y%m%d}"
        f"_m5line60_range6x3_rr1.2_sp{spread_pips:g}_60m"
    )
    return Path(tk.folder_path) / f"resistance_sweep_candidates_{stem}.csv"


def _following_event_path(args: argparse.Namespace, spread_pips: float) -> Path:
    stem = (
        f"{args.pair}_{args.following_start:%Y%m%d}_{args.following_end:%Y%m%d}"
        f"_m5line60_range6x3_rr1.2_sp{spread_pips:g}_60m"
    )
    return Path(tk.folder_path) / f"resistance_sweep_events_{stem}.csv"


def _following_s5_path(args: argparse.Namespace) -> Path:
    stem = (
        f"{args.pair}_{args.following_start:%Y%m%d%H%M%S}_"
        f"{args.following_end:%Y%m%d%H%M%S}"
    )
    return Path(tk.folder_path) / f"s5_{stem}.csv"


def parse_args(
    argv: list[str] | None = None,
    *,
    default_pair: str = "USD_JPY",
    default_train_start: dt.datetime = DEFAULT_TRAIN_START,
    default_train_end: dt.datetime = DEFAULT_TRAIN_END,
    default_following_start: dt.datetime = DEFAULT_OOS_START,
    default_following_end: dt.datetime = DEFAULT_OOS_END,
) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Replay one frozen count2 lifecycle artifact on its following window"
    )
    parser.add_argument("--pair", default=default_pair, choices=tuple(gene.CURRENCY_PAIRS))
    parser.add_argument("--train-start", default=default_train_start.isoformat(" "))
    parser.add_argument("--train-end", default=default_train_end.isoformat(" "))
    parser.add_argument(
        "--following-start", default=default_following_start.isoformat(" ")
    )
    parser.add_argument("--following-end", default=default_following_end.isoformat(" "))
    parser.add_argument("--artifact", type=Path)
    parser.add_argument("--source-candidates", type=Path)
    parser.add_argument("--source-events", type=Path)
    parser.add_argument("--s5-cache", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path(tk.folder_path))
    parser.add_argument("--read-chunk-size", type=int, default=1000)
    args = parser.parse_args(argv)

    for field in ("train_start", "train_end", "following_start", "following_end"):
        setattr(args, field, pd.Timestamp(getattr(args, field)).to_pydatetime())
    if args.train_start >= args.train_end:
        parser.error("--train-start must be earlier than --train-end")
    if args.following_start >= args.following_end:
        parser.error("--following-start must be earlier than --following-end")
    if args.train_end != args.following_start:
        parser.error("--train-end must equal --following-start")
    if args.read_chunk_size <= 0:
        parser.error("--read-chunk-size must be positive")

    args.artifact = args.artifact or _default_artifact_path(args)
    # Compatibility aliases used by the audited causal event/replay helpers.
    args.selection_start = args.train_start
    args.selection_end = args.train_end
    args.oos_start = args.following_start
    args.oos_end = args.following_end
    args.start = args.following_start
    args.end = args.following_end
    return args


def _output_paths(args: argparse.Namespace) -> dict[str, Path]:
    prefix = f"{FIXED_REPLAY_VERSION}_{_period_stem(args)}"
    folder = Path(args.output_dir)
    return {
        "trades": folder / f"{prefix}_trades.csv",
        "monthly": folder / f"{prefix}_monthly.csv",
        "summary_csv": folder / f"{prefix}_summary.csv",
        "summary_json": folder / f"{prefix}_summary.json",
        "progress": folder / f"{prefix}_progress.json",
    }


def _following_role(args: argparse.Namespace) -> str:
    if (
        args.following_start == KNOWN_REVIEWED_FOLLOWING_START
        and args.following_end == KNOWN_REVIEWED_FOLLOWING_END
    ):
        return "diagnostic_not_pristine_oos_for_previously_reviewed_2025_2026"
    return "fixed_following_validation_pristine_status_not_inferred"


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


def _sha256_payload(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("ascii")).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def _file_fingerprint(path: Path) -> dict[str, Any]:
    resolved = Path(path).resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"Required following input is missing: {resolved}")
    stat = resolved.stat()
    return {
        "resolved_path": str(resolved),
        "size": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
    }


def _assert_fingerprints_unchanged(fingerprints: Mapping[str, Any]) -> None:
    for fingerprint in fingerprints.values():
        if _file_fingerprint(Path(str(fingerprint["resolved_path"]))) != fingerprint:
            raise RuntimeError(
                "A following-period source changed during replay: "
                f"{fingerprint['resolved_path']}"
            )


def _policy_from_dict(payload: Mapping[str, Any], metric: str) -> Policy:
    required = {
        "rank",
        "metric",
        "order_name",
        "condition_id",
        "entry_rank",
        "offset_multiplier",
        "tp_multiplier",
        "lc_multiplier",
    }
    if set(payload) != required:
        raise ValueError("Frozen Policy fields do not match the expected schema")
    policy = Policy(**dict(payload))
    if policy.metric != metric or policy.entry_rank not in (1, 2, 3):
        raise ValueError(f"Frozen Policy identity is invalid for {metric}")
    numeric = (policy.offset_multiplier, policy.tp_multiplier, policy.lc_multiplier)
    if not all(math.isfinite(value) for value in numeric):
        raise ValueError(f"Frozen Policy has a non-finite parameter for {metric}")
    if policy.tp_multiplier <= 0 or policy.lc_multiplier <= 0:
        raise ValueError(f"Frozen Policy has a non-positive TP/LC for {metric}")
    return policy


def _timestamp_equals(value: Any, expected: dt.datetime) -> bool:
    try:
        return pd.Timestamp(value) == pd.Timestamp(expected)
    except (TypeError, ValueError):
        return False


def _load_and_validate_artifact(
    path: Path,
    args: argparse.Namespace,
) -> tuple[
    dict[str, Any],
    dict[str, list[Policy]],
    dict[str, ExitManagementPolicy],
]:
    path = Path(path).resolve()
    if not path.is_file():
        train_launcher = (
            f"test_long_inspection_lifecycle_train_{args.pair.lower()}.py"
        )
        raise FileNotFoundError(
            "Completed lifecycle selection artifact is missing: "
            f"{path}. Run {train_launcher} first and wait for its completion notice."
        )
    artifact = json.loads(path.read_text(encoding="utf-8"))
    required_keys = {
        "version",
        "status",
        "pair",
        "selection",
        "following",
        "settings",
        "config",
        "config_sha256",
        "fingerprints",
        "management_candidates",
        "selected_condition_rows",
        "selected_policies",
        "selected_management_policies",
        "train_verified",
        "selection_sha256",
        "future_safety",
    }
    missing = required_keys.difference(artifact)
    if missing:
        raise ValueError("Lifecycle artifact lacks keys: " + ", ".join(sorted(missing)))
    if artifact.get("version") != TRAIN_ARTIFACT_VERSION:
        raise ValueError("Lifecycle artifact version mismatch")
    if artifact.get("status") != "complete":
        raise ValueError("Lifecycle artifact status is not complete")
    if artifact.get("pair") != args.pair:
        raise ValueError("Lifecycle artifact pair mismatch")
    if not isinstance(artifact.get("fingerprints"), dict) or not artifact["fingerprints"]:
        raise ValueError("Lifecycle artifact selection fingerprints are missing")
    source_modules = artifact["fingerprints"].get("source_modules")
    required_engines = {
        "lifecycle_replay": Path(__file__).with_name(
            "count2_prior2y_oos_replay.py"
        ),
        "target_grid": Path(__file__).with_name("count2_target_grid_search.py"),
    }
    if not isinstance(source_modules, dict) or any(
        not isinstance(source_modules.get(name), dict)
        for name in required_engines
    ):
        raise ValueError("Lifecycle artifact engine fingerprints are missing")
    changed_engines = [
        name
        for name, current_path in required_engines.items()
        if _file_fingerprint(current_path) != source_modules[name]
    ]
    if changed_engines:
        train_launcher = (
            f"test_long_inspection_lifecycle_train_{args.pair.lower()}.py"
        )
        raise ValueError(
            "Lifecycle replay engine changed after condition selection: "
            f"{', '.join(changed_engines)}. Rerun {train_launcher} before the "
            "fixed following-period replay."
        )

    selection = artifact.get("selection")
    following = artifact.get("following")
    if not isinstance(selection, dict) or not isinstance(following, dict):
        raise ValueError("Lifecycle artifact boundaries are malformed")
    boundary_checks = (
        _timestamp_equals(selection.get("start_inclusive"), args.train_start),
        _timestamp_equals(selection.get("end_exclusive"), args.train_end),
        _timestamp_equals(following.get("start_inclusive"), args.following_start),
        _timestamp_equals(following.get("end_exclusive"), args.following_end),
    )
    if not all(boundary_checks):
        raise ValueError("Lifecycle artifact does not match all four requested boundaries")
    if args.train_end != args.following_start:
        raise ValueError("Selection and following windows must be contiguous")

    config = artifact.get("config")
    if not isinstance(config, dict):
        raise ValueError("Lifecycle artifact config is malformed")
    if _sha256_payload(config) != artifact.get("config_sha256"):
        raise ValueError("Lifecycle artifact config SHA256 mismatch")
    if config.get("pair") != args.pair:
        raise ValueError("Lifecycle artifact config pair mismatch")
    config_boundaries = (
        _timestamp_equals(config.get("selection_start_inclusive"), args.train_start),
        _timestamp_equals(config.get("selection_end_exclusive"), args.train_end),
        _timestamp_equals(config.get("following_start_inclusive"), args.following_start),
        _timestamp_equals(config.get("following_end_exclusive"), args.following_end),
    )
    if not all(config_boundaries):
        raise ValueError("Lifecycle artifact config boundary mismatch")
    if _canonical_json(config.get("settings", {})) != _canonical_json(
        artifact.get("settings", {})
    ):
        raise ValueError("Lifecycle artifact settings/config mismatch")

    safety = artifact.get("future_safety")
    required_safety = {
        "following_boundary_only_no_following_paths": True,
        "following_files_read": False,
        "management_selected_only_on_selection_window": True,
        "conditions_selected_only_on_selection_window": True,
        "selected_subset_replayed_with_full_portfolio_lifecycle": True,
        "s5_upper_bound_searchsorted_exclusive": True,
    }
    if not isinstance(safety, dict) or any(
        safety.get(key) is not expected for key, expected in required_safety.items()
    ):
        raise ValueError("Lifecycle artifact future-safety contract is incomplete")

    metrics = selection.get("metrics")
    if not isinstance(metrics, list) or not metrics or set(metrics).difference({"yen", "pips"}):
        raise ValueError("Lifecycle artifact metrics are invalid")
    if len(metrics) != len(set(metrics)):
        raise ValueError("Lifecycle artifact metrics are duplicated")
    if config.get("metrics") != metrics:
        raise ValueError("Lifecycle artifact metric/config mismatch")

    selected_raw = artifact.get("selected_policies")
    management_raw = artifact.get("selected_management_policies")
    condition_rows = artifact.get("selected_condition_rows")
    train_verified = artifact.get("train_verified")
    if not all(
        isinstance(value, dict)
        for value in (selected_raw, management_raw, condition_rows, train_verified)
    ):
        raise ValueError("Lifecycle artifact selection payload is malformed")
    expected_metric_set = set(metrics)
    for value in (selected_raw, management_raw, condition_rows, train_verified):
        if set(value) != expected_metric_set:
            raise ValueError("Lifecycle artifact selection metric keys mismatch")

    integrity_payload = {
        "pair": args.pair,
        "selection_start_inclusive": selection["start_inclusive"],
        "selection_end_exclusive": selection["end_exclusive"],
        "following_start_inclusive": following["start_inclusive"],
        "following_end_exclusive": following["end_exclusive"],
        "config_sha256": artifact["config_sha256"],
        "selected_management_policies": management_raw,
        "selected_policies": selected_raw,
        "train_verified": train_verified,
    }
    if _sha256_payload(integrity_payload) != artifact.get("selection_sha256"):
        raise ValueError("Lifecycle artifact fixed-selection SHA256 mismatch")

    immutable = config.get("immutable_top15")
    candidates = artifact.get("management_candidates")
    if not isinstance(immutable, dict) or not isinstance(candidates, list):
        raise ValueError("Lifecycle artifact candidate catalog is malformed")
    if _canonical_json(candidates) != _canonical_json(
        config.get("management_candidates", [])
    ):
        raise ValueError("Lifecycle artifact management catalog/config mismatch")
    if not all(isinstance(item, dict) for item in candidates):
        raise ValueError("Lifecycle artifact management candidate is malformed")
    candidate_identities = {_canonical_json(item) for item in candidates}
    if len(candidate_identities) != len(candidates):
        raise ValueError("Lifecycle artifact management candidates are duplicated")

    policies_by_metric: dict[str, list[Policy]] = {}
    management_by_metric: dict[str, ExitManagementPolicy] = {}
    for metric in metrics:
        raw_policies = selected_raw[metric]
        if not isinstance(raw_policies, list) or not raw_policies:
            raise ValueError(f"Lifecycle artifact selected_policies is empty for {metric}")
        policies = [_policy_from_dict(item, metric) for item in raw_policies]
        identities = [(policy.order_name, policy.condition_id) for policy in policies]
        if len(identities) != len(set(identities)):
            raise ValueError(f"Lifecycle artifact has duplicate policies for {metric}")
        metric_condition_rows = condition_rows[metric]
        if not isinstance(metric_condition_rows, list):
            raise ValueError(f"Selected condition rows are malformed for {metric}")
        row_identities = {
            (str(row.get("order_name")), str(row.get("condition_id")))
            for row in metric_condition_rows
            if isinstance(row, dict)
        }
        if row_identities != set(identities) or len(metric_condition_rows) != len(
            identities
        ):
            raise ValueError(f"Selected condition rows/policies mismatch for {metric}")
        immutable_rows = immutable.get(metric)
        if not isinstance(immutable_rows, list):
            raise ValueError(f"Lifecycle artifact immutable Top15 is missing for {metric}")
        immutable_identities = {_canonical_json(item) for item in immutable_rows}
        if any(_canonical_json(asdict(policy)) not in immutable_identities for policy in policies):
            raise ValueError(f"Selected policy is not part of immutable Top15 for {metric}")

        raw_management = management_raw[metric]
        if not isinstance(raw_management, dict):
            raise ValueError(f"Selected management is malformed for {metric}")
        if _canonical_json(raw_management) not in candidate_identities:
            raise ValueError(f"Selected management is absent from candidates for {metric}")
        management = exit_management_policy_from_dict(raw_management)
        verified = train_verified[metric]
        if (
            not isinstance(verified, dict)
            or verified.get("management_policy") != management.name
            or int(verified.get("selected_policy_count", -1)) != len(policies)
        ):
            raise ValueError(f"Train-verified selection mismatch for {metric}")
        policies_by_metric[metric] = policies
        management_by_metric[metric] = management
    return artifact, policies_by_metric, management_by_metric


def _apply_frozen_settings(args: argparse.Namespace, artifact: Mapping[str, Any]) -> None:
    settings = artifact.get("settings")
    if not isinstance(settings, dict):
        raise ValueError("Lifecycle artifact settings are malformed")
    required = (
        "spread_pips",
        "min_target_pips",
        "risk_yen",
        "trade_timeout_min",
        "profit_lock_ratio",
        "duplicate_threshold_pips",
    )
    for key in required:
        try:
            value = float(settings[key])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"Lifecycle artifact setting is invalid: {key}") from error
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"Lifecycle artifact setting must be positive: {key}")
        setattr(args, key, int(value) if key == "trade_timeout_min" else value)
    args.source_candidates = args.source_candidates or _following_candidate_path(
        args, args.spread_pips
    )
    args.source_events = args.source_events or _following_event_path(
        args, args.spread_pips
    )
    args.s5_cache = args.s5_cache or _following_s5_path(args)


def _slice_inspector_window(
    inspector: Any,
    start_inclusive: pd.Timestamp,
    end_exclusive: pd.Timestamp,
) -> Any:
    start_index = int(
        np.searchsorted(
            inspector.times,
            np.datetime64(pd.Timestamp(start_inclusive), "ns"),
            side="left",
        )
    )
    end_index = int(
        np.searchsorted(
            inspector.times,
            np.datetime64(pd.Timestamp(end_exclusive), "ns"),
            side="left",
        )
    )
    for attribute in ("times", "opens", "closes", "highs", "lows"):
        values = getattr(inspector, attribute)
        setattr(inspector, attribute, values[start_index:end_index])
    return inspector


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(_json_safe(payload), ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    temporary.replace(path)


def _archive_generation(paths: Mapping[str, Path]) -> list[Path]:
    """Archive completed outputs and every known temporary residual."""
    candidates: list[Path] = []
    for raw_path in paths.values():
        path = Path(raw_path)
        candidates.extend(
            [
                path,
                path.with_suffix(path.suffix + ".tmp"),
                path.with_suffix(path.suffix + ".part"),
            ]
        )
    archived: list[Path] = []
    seen: set[Path] = set()
    for path in candidates:
        if path in seen:
            continue
        seen.add(path)
        if path.exists():
            archived.append(_archive_file(path))
    return archived


def _write_progress(
    path: Path,
    *,
    args: argparse.Namespace,
    status: str,
    phase: str,
    started: float,
    artifact_sha256: str | None = None,
    metric: str | None = None,
    management_policy: str | None = None,
    completed_replays: int = 0,
    total_replays: int = 0,
    replay_percent: int | None = None,
    counters: Mapping[str, int] | None = None,
    error: str | None = None,
) -> None:
    fraction = (
        (completed_replays + (replay_percent or 0) / 100.0) / total_replays
        if total_replays
        else 0.0
    )
    _write_json_atomic(
        path,
        {
            "version": FIXED_REPLAY_VERSION,
            "status": status,
            "phase": phase,
            "pair": args.pair,
            "train_start": args.train_start,
            "train_end": args.train_end,
            "following_start": args.following_start,
            "following_end": args.following_end,
            "artifact_sha256": artifact_sha256,
            "ranking_metric": metric,
            "management_policy": management_policy,
            "progress_percent": round(100.0 * fraction, 3),
            "current_replay_percent": replay_percent,
            "s5_rows_processed_in_current_replay": int(
                getattr(args, "lifecycle_s5_rows_total", 0)
                * int(replay_percent or 0)
                / 100
            ),
            "s5_rows_total_in_current_replay": int(
                getattr(args, "lifecycle_s5_rows_total", 0)
            ),
            "completed_replays": completed_replays,
            "total_replays": total_replays,
            "counters": dict(counters or {}),
            "elapsed_minutes": round((time.monotonic() - started) / 60.0, 2),
            "error": error,
            "updated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        },
    )


def _normalize_trades(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    for column in TRADE_COLUMNS:
        if column not in result.columns:
            result[column] = pd.Series(index=result.index, dtype="object")
    ordered = list(TRADE_COLUMNS)
    ordered.extend(column for column in result.columns if column not in ordered)
    return result.loc[:, ordered]


def _performance_row(
    args: argparse.Namespace,
    metric: str,
    management: ExitManagementPolicy,
    trades: pd.DataFrame,
    summary: Mapping[str, Any],
) -> dict[str, Any]:
    positive = trades[trades["result_r"] > 0] if not trades.empty else trades
    negative = trades[trades["result_r"] < 0] if not trades.empty else trades
    gross_profit = float(positive["result_r"].sum()) if len(positive) else 0.0
    gross_loss = float(-negative["result_r"].sum()) if len(negative) else 0.0
    monthly = _monthly_summary(trades)
    return {
        "pair": args.pair,
        "phase": "following_fixed",
        "ranking_metric": metric,
        "management_policy": management.name,
        "trades": int(len(trades)),
        "wins": int((trades["result_r"] > 0).sum()) if len(trades) else 0,
        "losses": int((trades["result_r"] < 0).sum()) if len(trades) else 0,
        "win_rate": float((trades["result_r"] > 0).mean()) if len(trades) else 0.0,
        "sum_yen": float(trades["result_yen"].sum()) if len(trades) else 0.0,
        "sum_pips": float(trades["result_pips"].sum()) if len(trades) else 0.0,
        "sum_r": float(trades["result_r"].sum()) if len(trades) else 0.0,
        "average_win_r": float(positive["result_r"].mean()) if len(positive) else 0.0,
        "average_loss_r": float(negative["result_r"].mean()) if len(negative) else 0.0,
        "profit_factor_r": gross_profit / gross_loss if gross_loss else math.inf if gross_profit else 0.0,
        "max_drawdown_yen": float(summary.get("max_drawdown_yen", 0.0)),
        "positive_months_yen": int((monthly["sum_yen"] > 0).sum()),
        "positive_months_pips": int((monthly["sum_pips"] > 0).sum()),
        "period_end_mark_count": int(summary.get("period_end_mark_count", 0)),
        "submitted": int(summary.get("submitted", 0)),
        "filled": int(summary.get("filled", 0)),
        "blocked_unprotected_position": int(
            summary.get("blocked_unprotected_position", 0)
        ),
    }


def _notice(message: str) -> None:
    print(message)
    win_point.send_inspection_notice(message)


def run(args: argparse.Namespace) -> dict[str, Path]:
    paths = _output_paths(args)
    Path(args.output_dir).mkdir(parents=True, exist_ok=True)
    _archive_generation(paths)
    started = time.monotonic()
    artifact_sha256: str | None = None
    try:
        artifact, policies_by_metric, management_by_metric = (
            _load_and_validate_artifact(Path(args.artifact), args)
        )
        artifact_sha256 = _sha256_file(Path(args.artifact))
        _apply_frozen_settings(args, artifact)
        metrics = list(policies_by_metric)
        following_role = _following_role(args)
        _notice(
            "\n".join(
                [
                    f"{args.pair} lifecycle following fixed replay 開始",
                    f"- selection: {args.train_start:%Y-%m-%d} 以上 ～ {args.train_end:%Y-%m-%d} 未満",
                    f"- following: {args.following_start:%Y-%m-%d} 以上 ～ {args.following_end:%Y-%m-%d} 未満",
                    f"- metric: {', '.join(metrics)}",
                    "- 条件とLC管理はartifactで固定済み、following内で再選択なし",
                    (
                        "- この既閲覧期間の結果はdiagnosticとして記録"
                        if following_role.startswith("diagnostic_")
                        else "- 未使用期間かどうかはコードでは推測せず、固定following検証として記録"
                    ),
                ]
            )
        )
        _write_progress(
            paths["progress"],
            args=args,
            status="running",
            phase="validating_following_sources",
            started=started,
            artifact_sha256=artifact_sha256,
            total_replays=len(metrics),
        )

        _validate_source_headers(args)
        event_times = load_event_times(args)
        following_fingerprints = {
            "candidates": _file_fingerprint(Path(args.source_candidates)),
            "events": _file_fingerprint(Path(args.source_events)),
            "s5": _file_fingerprint(Path(args.s5_cache)),
        }
        pair = gene.currency_pair(args.pair)
        inspector, s5_metadata = _load_typed_s5_inspector(Path(args.s5_cache), pair)
        inspector = _slice_inspector_window(
            inspector,
            pd.Timestamp(args.following_start),
            pd.Timestamp(args.following_end),
        )
        args.lifecycle_s5_rows_total = int(len(inspector.times))
        _validate_s5_timeline(inspector, s5_source=Path(args.s5_cache))
        coverage_args = argparse.Namespace(start=args.following_start, end=args.following_end)
        coverage_errors = _s5_coverage_errors(inspector.times, coverage_args)
        if coverage_errors:
            raise ValueError(
                "Following S5 coverage is incomplete: " + " | ".join(coverage_errors)
            )

        trade_frames: list[pd.DataFrame] = []
        monthly_frames: list[pd.DataFrame] = []
        summary_rows: list[dict[str, Any]] = []
        replay_summaries: dict[str, Any] = {}
        total_replays = len(metrics)
        for replay_index, metric in enumerate(metrics):
            policies = policies_by_metric[metric]
            management = management_by_metric[metric]
            intents = build_intents(args, policies, event_times)

            def progress_callback(
                percent: int,
                counters: dict[str, int],
                _open_positions: int,
                _pending: bool,
            ) -> None:
                _write_progress(
                    paths["progress"],
                    args=args,
                    status="running",
                    phase="following_fixed",
                    started=started,
                    artifact_sha256=artifact_sha256,
                    metric=metric,
                    management_policy=management.name,
                    completed_replays=replay_index,
                    total_replays=total_replays,
                    replay_percent=percent,
                    counters=counters,
                )

            trades, replay_summary = replay_metric(
                args,
                metric,
                policies,
                event_times,
                intents,
                inspector,
                management_policy=management,
                progress_callback=progress_callback,
            )
            trades = _normalize_trades(trades)
            exported = trades.copy()
            exported.insert(0, "ranking_metric", metric)
            exported.insert(0, "phase", "following_fixed")
            exported.insert(0, "pair", args.pair)
            trade_frames.append(exported)

            monthly = _monthly_summary(trades)
            monthly.insert(0, "management_policy", management.name)
            monthly.insert(0, "ranking_metric", metric)
            monthly.insert(0, "phase", "following_fixed")
            monthly.insert(0, "pair", args.pair)
            monthly_frames.append(monthly)
            summary_rows.append(
                _performance_row(args, metric, management, trades, replay_summary)
            )
            replay_summaries[metric] = replay_summary
            _write_progress(
                paths["progress"],
                args=args,
                status="running",
                phase="following_fixed",
                started=started,
                artifact_sha256=artifact_sha256,
                metric=metric,
                management_policy=management.name,
                completed_replays=replay_index + 1,
                total_replays=total_replays,
                replay_percent=0,
            )

        _assert_fingerprints_unchanged(following_fingerprints)
        trades_frame = pd.concat(trade_frames, ignore_index=True, sort=False)
        monthly_frame = pd.concat(monthly_frames, ignore_index=True, sort=False)
        summary_frame = pd.DataFrame(summary_rows)
        csv_frames = {
            "trades": trades_frame,
            "monthly": monthly_frame,
            "summary_csv": summary_frame,
        }
        temporaries: dict[str, Path] = {}
        for name, frame in csv_frames.items():
            temporary = paths[name].with_suffix(paths[name].suffix + ".tmp")
            frame.to_csv(temporary, index=False, encoding="utf-8-sig")
            temporaries[name] = temporary

        elapsed_seconds = time.monotonic() - started
        result_manifest = {
            "version": FIXED_REPLAY_VERSION,
            "status": "complete",
            "pair": args.pair,
            "selection": {
                "start_inclusive": args.train_start,
                "end_exclusive": args.train_end,
            },
            "following": {
                "start_inclusive": args.following_start,
                "end_exclusive": args.following_end,
                "role": following_role,
            },
            "selection_artifact": str(Path(args.artifact).resolve()),
            "selection_artifact_sha256": artifact_sha256,
            "selection_config_sha256": artifact["config_sha256"],
            "selection_sha256": artifact["selection_sha256"],
            "selected_policies": {
                metric: [asdict(policy) for policy in policies]
                for metric, policies in policies_by_metric.items()
            },
            "selected_management_policies": {
                metric: asdict(policy)
                for metric, policy in management_by_metric.items()
            },
            "settings": {
                "spread_pips": args.spread_pips,
                "min_target_pips": args.min_target_pips,
                "risk_yen": args.risk_yen,
                "trade_timeout_min": args.trade_timeout_min,
                "profit_lock_ratio": args.profit_lock_ratio,
                "duplicate_threshold_pips": args.duplicate_threshold_pips,
            },
            "following_sources": following_fingerprints,
            "s5_metadata": s5_metadata,
            "s5_window": {
                "row_count": int(len(inspector.times)),
                "first_time": pd.Timestamp(inspector.times[0]),
                "last_time": pd.Timestamp(inspector.times[-1]),
                "coverage_errors": coverage_errors,
            },
            "results": summary_rows,
            "replay_summaries": replay_summaries,
            "future_safety": {
                "following_is_fixed_replay": True,
                "selection_files_read_during_following": False,
                "ranking_or_policy_reselection_on_following": False,
                "all_four_artifact_boundaries_validated": True,
                "selection_payload_sha256_validated": True,
                "following_window_half_open": True,
                "s5_lower_bound_searchsorted": True,
                "s5_upper_bound_searchsorted_exclusive": True,
                "candidate_schema_and_decision_causality_validated": True,
                "unknown_s5_gaps_rejected": True,
                "residual_no_tick_gaps_require_causal_csv_proof": True,
                "decision_in_proven_no_tick_gap_waits_for_next_s5": True,
                "same_s5_lc_wins_and_lc_updates_are_nonretroactive": True,
            },
            "outputs": {
                key: str(path.resolve())
                for key, path in paths.items()
                if key != "progress"
            },
            "output_tables": {
                name: {"rows": int(len(frame)), "columns": list(frame.columns)}
                for name, frame in csv_frames.items()
            },
            "elapsed_seconds": elapsed_seconds,
            "created_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            "limitations": [
                "Each window starts flat and positions still open at the exclusive end are marked at the last in-period executable close.",
                "S5 OHLC cannot reveal tick order; the inherited replay assumes LC when TP and LC are both touched in one S5.",
            ]
            + (
                [
                    "The configured 2025-2026 following period was previously inspected and is therefore diagnostic rather than pristine OOS."
                ]
                if following_role.startswith("diagnostic_")
                else [
                    "Whether a different following period is pristine must be established outside this program."
                ]
            ),
        }
        summary_json_tmp = paths["summary_json"].with_suffix(
            paths["summary_json"].suffix + ".tmp"
        )
        summary_json_tmp.write_text(
            json.dumps(
                _json_safe(result_manifest),
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
            ),
            encoding="utf-8",
        )
        for name, temporary in temporaries.items():
            temporary.replace(paths[name])
        summary_json_tmp.replace(paths["summary_json"])

        _write_progress(
            paths["progress"],
            args=args,
            status="complete",
            phase="complete",
            started=started,
            artifact_sha256=artifact_sha256,
            completed_replays=total_replays,
            total_replays=total_replays,
            replay_percent=0,
        )
        paths["progress"] = _archive_file(paths["progress"])
        lines = [f"{args.pair} lifecycle following fixed replay 完了"]
        for row in summary_rows:
            lines.append(
                f"- {row['ranking_metric']}: {row['sum_yen']:.0f}円 / "
                f"{row['sum_pips']:.2f}pips / 勝率{100 * row['win_rate']:.1f}% / "
                f"PF{row['profit_factor_r']:.2f}"
            )
        lines.extend(
            [
                "- following期間内で条件・LC管理の再選択なし",
                (
                    "- この期間は既閲覧のためdiagnostic扱い"
                    if following_role.startswith("diagnostic_")
                    else "- 未使用期間かどうかは外部管理し、コード上は固定following検証扱い"
                ),
                f"- summary: {paths['summary_json']}",
            ]
        )
        _notice("\n".join(lines))
        return paths
    except Exception as error:
        try:
            _write_progress(
                paths["progress"],
                args=args,
                status="failed",
                phase="failed",
                started=started,
                artifact_sha256=artifact_sha256,
                error=f"{type(error).__name__}: {error}",
            )
        finally:
            _archive_generation(paths)
        _notice(
            "\n".join(
                [
                    f"{args.pair} lifecycle following fixed replay 失敗",
                    f"- error type: {type(error).__name__}",
                    f"- detail: {error}",
                    "- final/temp/part/progressはarchive済み",
                ]
            )
        )
        raise


def main(
    argv: list[str] | None = None,
    *,
    default_pair: str = "USD_JPY",
    default_train_start: dt.datetime = DEFAULT_TRAIN_START,
    default_train_end: dt.datetime = DEFAULT_TRAIN_END,
    default_following_start: dt.datetime = DEFAULT_OOS_START,
    default_following_end: dt.datetime = DEFAULT_OOS_END,
) -> dict[str, Path]:
    return run(
        parse_args(
            argv,
            default_pair=default_pair,
            default_train_start=default_train_start,
            default_train_end=default_train_end,
            default_following_start=default_following_start,
            default_following_end=default_following_end,
        )
    )


if __name__ == "__main__":
    main()
