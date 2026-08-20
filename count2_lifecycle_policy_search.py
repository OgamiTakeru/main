"""Select loss-management and fixed count2 policies on one training window.

This inspection-only module deliberately reads only ``[selection_start,
selection_end)`` inputs.  Existing yen/pips Top15 shape, entry, TP, and initial
LC policies are immutable inputs.  Every loss-management candidate is replayed
through the complete portfolio lifecycle, after which a deterministic rule
selects one management policy and a condition subset.  That subset is replayed
once more on the same training window as ``train_verified``.

The resulting artifact is the only hand-off to the separate following-period
replay.  This module accepts following-period boundaries for that hand-off but
has no following-period data-path arguments and never reads following data.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import math
import re
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd

import fGeneric as gene
import fLineAnalysis as line_analysis
import test_win_point_usd_aud as win_point
import tokens as tk
import count2_prior2y_oos_replay as replay_source
import count2_target_grid_search as grid_source
from count2_prior2y_oos_replay import (
    DEFAULT_OOS_END,
    DEFAULT_OOS_START,
    DEFAULT_TRAIN_END,
    DEFAULT_TRAIN_START,
    LIFECYCLE_LOSS_POLICIES,
    ExitManagementPolicy,
    LossStage,
    Policy,
    _archive_file,
    _validate_s5_timeline,
    _validate_source_headers,
    build_intents,
    load_event_times,
    load_policies,
    replay_metric,
)
from count2_target_grid_search import (
    _load_typed_s5_inspector,
    _s5_coverage_errors,
)


LIFECYCLE_TRAIN_VERSION = "count2_lifecycle_train_v1"
DEFAULT_METRICS = ("yen", "pips")
DEFAULT_CONDITION_MIN_TRADES = 20
DEFAULT_CONDITION_TOP = 15

BASE_TRADE_COLUMNS = (
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
    "final_lc_price",
    "final_lc_pips",
    "max_favorable_pips",
    "max_adverse_pips",
    "risk_yen",
    "management_policy",
    "cumulative_yen",
)


def _selection_candidate_path(args: argparse.Namespace) -> Path:
    stem = (
        f"{args.pair}_{args.selection_start:%Y%m%d}_{args.selection_end:%Y%m%d}"
        f"_m5line60_range6x3_rr1.2_sp{args.spread_pips:g}_60m"
    )
    return Path(tk.folder_path) / f"resistance_sweep_candidates_{stem}.csv"


def _selection_event_path(args: argparse.Namespace) -> Path:
    stem = (
        f"{args.pair}_{args.selection_start:%Y%m%d}_{args.selection_end:%Y%m%d}"
        f"_m5line60_range6x3_rr1.2_sp{args.spread_pips:g}_60m"
    )
    return Path(tk.folder_path) / f"resistance_sweep_events_{stem}.csv"


def _selection_s5_path(args: argparse.Namespace) -> Path:
    stem = (
        f"{args.pair}_{args.selection_start:%Y%m%d%H%M%S}_"
        f"{args.selection_end:%Y%m%d%H%M%S}"
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
        description=(
            "Select count2 loss-management and condition policies using only "
            "the fixed prior training window"
        )
    )
    parser.add_argument("--pair", default=default_pair, choices=tuple(gene.CURRENCY_PAIRS))
    parser.add_argument(
        "--selection-start",
        "--train-start",
        dest="selection_start",
        default=default_train_start.isoformat(" "),
    )
    parser.add_argument(
        "--selection-end",
        "--train-end",
        dest="selection_end",
        default=default_train_end.isoformat(" "),
    )
    parser.add_argument(
        "--following-start",
        default=default_following_start.isoformat(" "),
    )
    parser.add_argument(
        "--following-end",
        default=default_following_end.isoformat(" "),
    )
    parser.add_argument("--metrics", default=",".join(DEFAULT_METRICS))
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
    parser.add_argument("--risk-yen", type=float, default=None)
    parser.add_argument("--read-chunk-size", type=int, default=1000)
    parser.add_argument(
        "--condition-min-trades",
        type=int,
        default=DEFAULT_CONDITION_MIN_TRADES,
    )
    parser.add_argument("--condition-top", type=int, default=DEFAULT_CONDITION_TOP)
    args = parser.parse_args(argv)

    for field in (
        "selection_start",
        "selection_end",
        "following_start",
        "following_end",
    ):
        setattr(args, field, pd.Timestamp(getattr(args, field)).to_pydatetime())
    if args.selection_start >= args.selection_end:
        parser.error("--selection-start must be earlier than --selection-end")
    if args.following_start >= args.following_end:
        parser.error("--following-start must be earlier than --following-end")
    if args.selection_end != args.following_start:
        parser.error("--selection-end must equal --following-start")

    metrics = tuple(
        dict.fromkeys(value.strip().lower() for value in args.metrics.split(",") if value.strip())
    )
    if not metrics or set(metrics).difference(DEFAULT_METRICS):
        parser.error("--metrics supports only yen,pips")
    args.metrics = metrics

    positive_fields = (
        "spread_pips",
        "min_target_pips",
        "trade_timeout_min",
        "profit_lock_ratio",
        "duplicate_threshold_pips",
        "read_chunk_size",
        "condition_min_trades",
        "condition_top",
    )
    for field in positive_fields:
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
    args.source_candidates = args.source_candidates or _selection_candidate_path(args)
    args.source_events = args.source_events or _selection_event_path(args)
    args.s5_cache = args.s5_cache or _selection_s5_path(args)

    # Compatibility aliases for the existing, already audited replay helpers.
    # Both helper windows intentionally point to selection; no following path is
    # represented anywhere in this process.
    args.train_start = args.selection_start
    args.train_end = args.selection_end
    args.oos_start = args.selection_start
    args.oos_end = args.selection_end
    args.start = args.selection_start
    args.end = args.selection_end
    return args


def _stem(args: argparse.Namespace) -> str:
    return (
        f"{args.pair}_{args.selection_start:%Y%m%d}_{args.selection_end:%Y%m%d}"
        f"_to_{args.following_start:%Y%m%d}_{args.following_end:%Y%m%d}"
    )


def artifact_path(args: argparse.Namespace) -> Path:
    """Return the stable hand-off path consumed by fixed following replay."""
    return (
        Path(args.output_dir)
        / f"{LIFECYCLE_TRAIN_VERSION}_artifact_{_stem(args)}.json"
    )


def _output_paths(args: argparse.Namespace) -> dict[str, Path]:
    stem = _stem(args)
    prefix = f"{LIFECYCLE_TRAIN_VERSION}_{stem}"
    folder = Path(args.output_dir)
    return {
        "artifact": artifact_path(args),
        "summary": folder / f"{prefix}_summary.csv",
        "monthly": folder / f"{prefix}_monthly.csv",
        "trades": folder / f"{prefix}_trades.csv",
        "conditions": folder / f"{prefix}_conditions.csv",
        "verified_trades": folder / f"{prefix}_train_verified_trades.csv",
        "verified_monthly": folder / f"{prefix}_train_verified_monthly.csv",
        "progress": folder / f"{prefix}_progress.json",
    }


def _safe_name(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value)).strip("._")
    return safe or "unnamed"


def _checkpoint_paths(
    args: argparse.Namespace,
    *,
    scope: str,
    metric: str,
    management_policy: str,
) -> tuple[Path, Path]:
    prefix = (
        f"{LIFECYCLE_TRAIN_VERSION}_checkpoint_{_safe_name(scope)}_"
        f"{_safe_name(metric)}_{_safe_name(management_policy)}_{_stem(args)}"
    )
    folder = Path(args.output_dir)
    return folder / f"{prefix}_trades.csv", folder / f"{prefix}.json"


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


def _canonical_json(payload: Mapping[str, Any]) -> str:
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
    with path.open("rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def _file_fingerprint(path: Path) -> dict[str, Any]:
    resolved = Path(path).resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"Required input is missing: {resolved}")
    stat = resolved.stat()
    return {
        "resolved_path": str(resolved),
        "size": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
    }


def _collect_fingerprints(
    args: argparse.Namespace,
    ranking_paths: Mapping[str, tuple[Path, Path]],
) -> dict[str, Any]:
    return {
        "source_modules": {
            "lifecycle_train": _file_fingerprint(Path(__file__)),
            "lifecycle_replay": _file_fingerprint(Path(replay_source.__file__)),
            "target_grid": _file_fingerprint(Path(grid_source.__file__)),
        },
        "rankings": {
            metric: {
                "csv": _file_fingerprint(paths[0]),
                "manifest": _file_fingerprint(paths[1]),
            }
            for metric, paths in ranking_paths.items()
        },
        "candidates": _file_fingerprint(Path(args.source_candidates)),
        "events": _file_fingerprint(Path(args.source_events)),
        "s5": _file_fingerprint(Path(args.s5_cache)),
    }


def _assert_fingerprints_unchanged(fingerprints: Mapping[str, Any]) -> None:
    def visit(value: Any) -> Iterable[Mapping[str, Any]]:
        if isinstance(value, Mapping):
            if {"resolved_path", "size", "mtime_ns"}.issubset(value):
                yield value
            else:
                for child in value.values():
                    yield from visit(child)

    for original in visit(fingerprints):
        current = _file_fingerprint(Path(str(original["resolved_path"])))
        if current != dict(original):
            raise RuntimeError(
                "An immutable source changed during lifecycle selection: "
                f"{original['resolved_path']}"
            )


def _selection_rules(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "management": {
            "primary": {
                "yen": "sum_yen_desc",
                "pips": "sum_pips_desc",
            },
            "eligibility": ["sum_yen>0", "sum_pips>0", "profit_factor_r>=1"],
            "tie_break": [
                "positive_halfyears_for_metric_desc",
                "worst_halfyear_for_metric_desc",
                "max_drawdown_yen_desc_closer_to_zero",
                "management_policy_asc",
            ],
        },
        "condition": {
            "min_trades": int(args.condition_min_trades),
            "min_win_rate": 0.40,
            "eligibility": ["sum_yen>0", "sum_pips>0", "profit_factor_r>=1"],
            "primary": {
                "yen": "sum_yen_desc",
                "pips": "sum_pips_desc",
            },
            "tie_break": ["policy_rank_asc", "order_name_asc", "condition_id_asc"],
            "top": int(args.condition_top),
        },
    }


def _settings(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "spread_pips": float(args.spread_pips),
        "min_target_pips": float(args.min_target_pips),
        "risk_yen": float(args.risk_yen),
        "order_timeout": "live distance-based 15/30/45 minutes",
        "trade_timeout_min": int(args.trade_timeout_min),
        "profit_lock_ratio": float(args.profit_lock_ratio),
        "allow_followup_order_before_lock": False,
        "duplicate_threshold_pips": float(args.duplicate_threshold_pips),
        "condition_min_trades": int(args.condition_min_trades),
        "condition_top": int(args.condition_top),
    }


def _config_payload(
    args: argparse.Namespace,
    policies_by_metric: Mapping[str, list[Policy]],
    fingerprints: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "version": LIFECYCLE_TRAIN_VERSION,
        "pair": args.pair,
        "selection_start_inclusive": args.selection_start,
        "selection_end_exclusive": args.selection_end,
        "following_start_inclusive": args.following_start,
        "following_end_exclusive": args.following_end,
        "metrics": list(args.metrics),
        "settings": _settings(args),
        "selection_rules": _selection_rules(args),
        "management_candidates": [asdict(policy) for policy in LIFECYCLE_LOSS_POLICIES],
        "immutable_top15": {
            metric: [asdict(policy) for policy in policies]
            for metric, policies in policies_by_metric.items()
        },
        "fingerprints": fingerprints,
    }


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            _json_safe(payload),
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        ),
        encoding="utf-8",
    )
    temporary.replace(path)


def _write_csv_temporary(frame: pd.DataFrame, path: Path) -> Path:
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_csv(temporary, index=False, encoding="utf-8-sig")
    return temporary


def _archive_paths(paths: Iterable[Path]) -> list[Path]:
    archived: list[Path] = []
    for path in paths:
        if path.exists():
            archived.append(_archive_file(path))
    return archived


def _prepare_outputs(paths: Mapping[str, Path]) -> None:
    Path(paths["artifact"]).parent.mkdir(parents=True, exist_ok=True)
    targets = list(paths.values())
    temporaries = [path.with_suffix(path.suffix + ".tmp") for path in targets]
    _archive_paths([*targets, *temporaries])


def _normalize_trades(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    for column in BASE_TRADE_COLUMNS:
        if column not in result.columns:
            result[column] = pd.Series(index=result.index, dtype="object")
    ordered = list(BASE_TRADE_COLUMNS)
    ordered.extend(column for column in result.columns if column not in ordered)
    return result.loc[:, ordered]


def _csv_header(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return next(csv.reader(handle), [])


def _invalidate_checkpoint(csv_path: Path, json_path: Path) -> None:
    _archive_paths(
        [
            csv_path,
            json_path,
            csv_path.with_suffix(csv_path.suffix + ".tmp"),
            json_path.with_suffix(json_path.suffix + ".tmp"),
        ]
    )


def _load_checkpoint(
    csv_path: Path,
    json_path: Path,
    *,
    checkpoint_fingerprint: str,
    metric: str,
    management_policy: ExitManagementPolicy,
) -> tuple[pd.DataFrame, dict[str, Any]] | None:
    residuals = [
        csv_path.with_suffix(csv_path.suffix + ".tmp"),
        json_path.with_suffix(json_path.suffix + ".tmp"),
    ]
    if any(path.exists() for path in residuals):
        _invalidate_checkpoint(csv_path, json_path)
        return None
    if not csv_path.exists() and not json_path.exists():
        return None
    if not csv_path.is_file() or not json_path.is_file():
        _invalidate_checkpoint(csv_path, json_path)
        return None
    try:
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        expected_policy = _json_safe(asdict(management_policy))
        if (
            payload.get("version") != LIFECYCLE_TRAIN_VERSION
            or payload.get("status") != "complete"
            or payload.get("checkpoint_fingerprint") != checkpoint_fingerprint
            or payload.get("ranking_metric") != metric
            or payload.get("management_policy") != expected_policy
        ):
            raise ValueError("checkpoint identity mismatch")
        expected_columns = [str(value) for value in payload["trade_columns"]]
        if _csv_header(csv_path) != expected_columns:
            raise ValueError("checkpoint header mismatch")
        if _sha256_file(csv_path) != payload.get("trades_sha256"):
            raise ValueError("checkpoint content fingerprint mismatch")
        trades = pd.read_csv(csv_path, low_memory=False)
        if len(trades) != int(payload["trade_rows"]):
            raise ValueError("checkpoint row-count mismatch")
        if list(trades.columns) != expected_columns:
            raise ValueError("checkpoint parsed-header mismatch")
        summary = payload.get("summary")
        if not isinstance(summary, dict):
            raise ValueError("checkpoint summary is missing")
        return trades, dict(summary)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError, pd.errors.ParserError):
        _invalidate_checkpoint(csv_path, json_path)
        return None


def _write_checkpoint(
    csv_path: Path,
    json_path: Path,
    *,
    checkpoint_fingerprint: str,
    scope: str,
    metric: str,
    management_policy: ExitManagementPolicy,
    trades: pd.DataFrame,
    summary: Mapping[str, Any],
) -> None:
    trades = _normalize_trades(trades)
    csv_tmp = csv_path.with_suffix(csv_path.suffix + ".tmp")
    json_tmp = json_path.with_suffix(json_path.suffix + ".tmp")
    _archive_paths([csv_tmp, json_tmp])
    try:
        trades.to_csv(csv_tmp, index=False, encoding="utf-8-sig")
        csv_sha256 = _sha256_file(csv_tmp)
        payload = {
            "version": LIFECYCLE_TRAIN_VERSION,
            "status": "complete",
            "checkpoint_fingerprint": checkpoint_fingerprint,
            "scope": scope,
            "ranking_metric": metric,
            "management_policy": asdict(management_policy),
            "trade_rows": int(len(trades)),
            "trade_columns": list(trades.columns),
            "trades_sha256": csv_sha256,
            "summary": summary,
            "created_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        json_tmp.write_text(
            json.dumps(
                _json_safe(payload),
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
            ),
            encoding="utf-8",
        )
        if csv_path.exists() or json_path.exists():
            _archive_paths([csv_path, json_path])
        csv_tmp.replace(csv_path)
        json_tmp.replace(json_path)
    except Exception:
        _invalidate_checkpoint(csv_path, json_path)
        raise


def _write_progress(
    path: Path,
    *,
    args: argparse.Namespace,
    status: str,
    phase: str,
    started: float,
    config_sha256: str | None = None,
    ranking_metric: str | None = None,
    management_policy: str | None = None,
    progress_percent: float = 0.0,
    replay_percent: int | None = None,
    completed_replays: int = 0,
    total_replays: int = 0,
    counters: Mapping[str, int] | None = None,
    checkpoint_reused: bool = False,
    error: str | None = None,
) -> None:
    _write_json_atomic(
        path,
        {
            "version": LIFECYCLE_TRAIN_VERSION,
            "status": status,
            "phase": phase,
            "pair": args.pair,
            "selection_start_inclusive": args.selection_start,
            "selection_end_exclusive": args.selection_end,
            "following_start_inclusive": args.following_start,
            "following_end_exclusive": args.following_end,
            "config_sha256": config_sha256,
            "ranking_metric": ranking_metric,
            "management_policy": management_policy,
            "progress_percent": round(float(progress_percent), 3),
            "replay_percent": replay_percent,
            "s5_rows_processed_in_current_replay": (
                int(
                    getattr(args, "lifecycle_s5_rows_total", 0)
                    * int(replay_percent or 0)
                    / 100
                )
            ),
            "s5_rows_total_in_current_replay": int(
                getattr(args, "lifecycle_s5_rows_total", 0)
            ),
            "completed_replays": int(completed_replays),
            "total_replays": int(total_replays),
            "counters": dict(counters or {}),
            "checkpoint_reused": bool(checkpoint_reused),
            "elapsed_minutes": round((time.monotonic() - started) / 60.0, 2),
            "error": error,
            "updated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        },
    )


def _slice_inspector_window(
    inspector: Any,
    start_inclusive: pd.Timestamp,
    end_exclusive: pd.Timestamp,
) -> Any:
    """Slice every S5 array to the exact half-open selection window."""
    times = inspector.times
    start_index = int(
        np.searchsorted(
            times,
            np.datetime64(pd.Timestamp(start_inclusive), "ns"),
            side="left",
        )
    )
    end_index = int(
        np.searchsorted(
            times,
            np.datetime64(pd.Timestamp(end_exclusive), "ns"),
            side="left",
        )
    )
    for attribute in ("times", "opens", "closes", "highs", "lows"):
        values = getattr(inspector, attribute)
        setattr(inspector, attribute, values[start_index:end_index])
    return inspector


def _core_performance(trades: pd.DataFrame) -> dict[str, Any]:
    if trades.empty:
        return {
            "trades": 0,
            "wins": 0,
            "losses": 0,
            "flat": 0,
            "win_rate": 0.0,
            "sum_yen": 0.0,
            "sum_pips": 0.0,
            "sum_r": 0.0,
            "average_r": 0.0,
            "average_win_r": 0.0,
            "average_loss_r": 0.0,
            "profit_factor_r": 0.0,
            "max_drawdown_yen": 0.0,
        }
    work = trades.copy()
    for column in ("result_yen", "result_pips", "result_r"):
        work[column] = pd.to_numeric(work[column], errors="raise")
    sort_columns = [column for column in ("exit_time", "fill_time") if column in work]
    if sort_columns:
        work = work.sort_values(sort_columns, kind="stable")
    positive = work[work["result_r"] > 0]
    negative = work[work["result_r"] < 0]
    gross_profit_r = float(positive["result_r"].sum())
    gross_loss_r = float(-negative["result_r"].sum())
    if gross_loss_r > 0:
        profit_factor = gross_profit_r / gross_loss_r
    elif gross_profit_r > 0:
        profit_factor = math.inf
    else:
        profit_factor = 0.0
    cumulative = work["result_yen"].cumsum()
    running_high = cumulative.cummax().clip(lower=0)
    drawdown = cumulative - running_high
    return {
        "trades": int(len(work)),
        "wins": int((work["result_r"] > 0).sum()),
        "losses": int((work["result_r"] < 0).sum()),
        "flat": int((work["result_r"] == 0).sum()),
        "win_rate": float((work["result_r"] > 0).mean()),
        "sum_yen": float(work["result_yen"].sum()),
        "sum_pips": float(work["result_pips"].sum()),
        "sum_r": float(work["result_r"].sum()),
        "average_r": float(work["result_r"].mean()),
        "average_win_r": float(positive["result_r"].mean()) if len(positive) else 0.0,
        "average_loss_r": float(negative["result_r"].mean()) if len(negative) else 0.0,
        "profit_factor_r": float(profit_factor),
        "max_drawdown_yen": float(drawdown.min()),
    }


def _period_labels(times: pd.Series, period: str) -> pd.Series:
    parsed = pd.to_datetime(times, errors="raise")
    if period == "month":
        return parsed.dt.strftime("%Y-%m")
    if period == "halfyear":
        half = ((parsed.dt.month - 1) // 6 + 1).astype(str)
        return parsed.dt.year.astype(str) + "-H" + half
    raise ValueError(f"Unsupported stability period: {period}")


def _period_performance_rows(trades: pd.DataFrame, period: str) -> list[dict[str, Any]]:
    if trades.empty:
        return []
    work = trades.copy()
    work["period"] = _period_labels(work["exit_time"], period)
    rows: list[dict[str, Any]] = []
    for label, group in work.groupby("period", sort=True):
        rows.append({"period_type": period, "period": label, **_core_performance(group)})
    return rows


def _performance(trades: pd.DataFrame) -> dict[str, Any]:
    result = _core_performance(trades)
    monthly = _period_performance_rows(trades, "month")
    halfyears = _period_performance_rows(trades, "halfyear")
    result.update(
        {
            "active_months": len(monthly),
            "positive_months_yen": sum(row["sum_yen"] > 0 for row in monthly),
            "positive_months_pips": sum(row["sum_pips"] > 0 for row in monthly),
            "worst_month_yen": min((row["sum_yen"] for row in monthly), default=0.0),
            "worst_month_pips": min((row["sum_pips"] for row in monthly), default=0.0),
            "active_halfyears": len(halfyears),
            "positive_halfyears_yen": sum(row["sum_yen"] > 0 for row in halfyears),
            "positive_halfyears_pips": sum(row["sum_pips"] > 0 for row in halfyears),
            "worst_halfyear_yen": min(
                (row["sum_yen"] for row in halfyears), default=0.0
            ),
            "worst_halfyear_pips": min(
                (row["sum_pips"] for row in halfyears), default=0.0
            ),
        }
    )
    return result


def _summary_row(
    args: argparse.Namespace,
    metric: str,
    management_policy: ExitManagementPolicy,
    trades: pd.DataFrame,
    replay_summary: Mapping[str, Any],
) -> dict[str, Any]:
    row = {
        "pair": args.pair,
        "ranking_metric": metric,
        "management_policy": management_policy.name,
        **_performance(trades),
    }
    for key, value in replay_summary.items():
        if key not in row:
            row[key] = value
    return row


def _monthly_rows(
    args: argparse.Namespace,
    metric: str,
    management_policy: ExitManagementPolicy,
    trades: pd.DataFrame,
    *,
    phase: str,
) -> list[dict[str, Any]]:
    return [
        {
            "pair": args.pair,
            "phase": phase,
            "ranking_metric": metric,
            "management_policy": management_policy.name,
            **row,
        }
        for row in _period_performance_rows(trades, "month")
    ]


def _condition_rows(
    args: argparse.Namespace,
    metric: str,
    management_policy: ExitManagementPolicy,
    policies: list[Policy],
    trades: pd.DataFrame,
) -> list[dict[str, Any]]:
    if trades.empty:
        return []
    policy_by_identity = {
        (policy.order_name, policy.condition_id): policy for policy in policies
    }
    rows: list[dict[str, Any]] = []
    for (order_name, condition_id), group in trades.groupby(
        ["order_name", "condition_id"], sort=False, dropna=False
    ):
        identity = (str(order_name), str(condition_id))
        policy = policy_by_identity.get(identity)
        if policy is None:
            raise RuntimeError(f"Trade refers to an unknown immutable policy: {identity}")
        rows.append(
            {
                "pair": args.pair,
                "ranking_metric": metric,
                "management_policy": management_policy.name,
                "order_name": policy.order_name,
                "condition_id": policy.condition_id,
                "policy_rank": policy.rank,
                "entry_rank": policy.entry_rank,
                "offset_multiplier": policy.offset_multiplier,
                "tp_multiplier": policy.tp_multiplier,
                "lc_multiplier": policy.lc_multiplier,
                **_performance(group),
            }
        )
    return rows


def _select_management(
    metric: str,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    primary = "sum_yen" if metric == "yen" else "sum_pips"
    positive_halfyears = (
        "positive_halfyears_yen" if metric == "yen" else "positive_halfyears_pips"
    )
    worst_halfyear = "worst_halfyear_yen" if metric == "yen" else "worst_halfyear_pips"
    eligible = [
        row
        for row in rows
        if row["sum_yen"] > 0
        and row["sum_pips"] > 0
        and row["profit_factor_r"] >= 1
    ]
    if not eligible:
        raise ValueError(f"No eligible lifecycle management policy for {metric}")
    frame = pd.DataFrame(eligible).sort_values(
        [primary, positive_halfyears, worst_halfyear, "max_drawdown_yen", "management_policy"],
        ascending=[False, False, False, False, True],
        kind="stable",
    )
    return dict(frame.iloc[0].to_dict())


def _select_conditions(
    args: argparse.Namespace,
    metric: str,
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    primary = "sum_yen" if metric == "yen" else "sum_pips"
    eligible = [
        row
        for row in rows
        if row["trades"] >= args.condition_min_trades
        and row["win_rate"] >= 0.40
        and row["sum_yen"] > 0
        and row["sum_pips"] > 0
        and row["profit_factor_r"] >= 1
    ]
    if not eligible:
        raise ValueError(f"No eligible lifecycle condition for {metric}")
    frame = pd.DataFrame(eligible).sort_values(
        [primary, "policy_rank", "order_name", "condition_id"],
        ascending=[False, True, True, True],
        kind="stable",
    )
    return [dict(row) for row in frame.head(args.condition_top).to_dict("records")]


def _validate_management_candidates() -> dict[str, ExitManagementPolicy]:
    if not LIFECYCLE_LOSS_POLICIES:
        raise ValueError("LIFECYCLE_LOSS_POLICIES is empty")
    by_name: dict[str, ExitManagementPolicy] = {}
    for policy in LIFECYCLE_LOSS_POLICIES:
        if not isinstance(policy, ExitManagementPolicy):
            raise TypeError("Every lifecycle loss candidate must be ExitManagementPolicy")
        if policy.name in by_name:
            raise ValueError(f"Duplicate lifecycle management policy name: {policy.name}")
        for stage in policy.loss_stages:
            if not isinstance(stage, LossStage):
                raise TypeError(f"Invalid LossStage in {policy.name}")
        by_name[policy.name] = policy
    return by_name


def _run_or_resume_replay(
    args: argparse.Namespace,
    *,
    scope: str,
    checkpoint_fingerprint: str,
    metric: str,
    policies: list[Policy],
    event_times: list[tuple[str, pd.Timestamp]],
    intents: dict[str, Any],
    inspector: Any,
    management_policy: ExitManagementPolicy,
    progress_callback: Any,
) -> tuple[pd.DataFrame, dict[str, Any], bool]:
    csv_path, json_path = _checkpoint_paths(
        args,
        scope=scope,
        metric=metric,
        management_policy=management_policy.name,
    )
    resumed = _load_checkpoint(
        csv_path,
        json_path,
        checkpoint_fingerprint=checkpoint_fingerprint,
        metric=metric,
        management_policy=management_policy,
    )
    if resumed is not None:
        trades, summary = resumed
        return _normalize_trades(trades), summary, True
    trades, summary = replay_metric(
        args,
        metric,
        policies,
        event_times,
        intents,
        inspector,
        management_policy=management_policy,
        progress_callback=progress_callback,
    )
    trades = _normalize_trades(trades)
    _write_checkpoint(
        csv_path,
        json_path,
        checkpoint_fingerprint=checkpoint_fingerprint,
        scope=scope,
        metric=metric,
        management_policy=management_policy,
        trades=trades,
        summary=summary,
    )
    return trades, summary, False


def _notify(message: str) -> None:
    print(message)
    win_point.send_inspection_notice(message)


def _start_notice(args: argparse.Namespace) -> None:
    _notify(
        "\n".join(
            [
                f"{args.pair} lifecycle train search 開始",
                f"- 選定期間: {args.selection_start:%Y-%m-%d} 以上 ～ {args.selection_end:%Y-%m-%d} 未満",
                f"- following境界: {args.following_start:%Y-%m-%d} 以上 ～ {args.following_end:%Y-%m-%d} 未満",
                "- 固定対象: 既存yen/pips Top15の形状・entry・TP・初期LC",
                f"- 管理候補: {len(LIFECYCLE_LOSS_POLICIES)}件",
                "- following期間の価格・event・candidateは読みません",
            ]
        )
    )


def _failure_cleanup(paths: Mapping[str, Path]) -> None:
    material: list[Path] = []
    for path in paths.values():
        material.extend([path, path.with_suffix(path.suffix + ".tmp")])
    _archive_paths(material)


def run(args: argparse.Namespace) -> dict[str, Path]:
    paths = _output_paths(args)
    started = time.monotonic()
    _prepare_outputs(paths)
    _start_notice(args)
    config_sha256: str | None = None
    try:
        _write_progress(
            paths["progress"],
            args=args,
            status="running",
            phase="validating_selection_sources",
            started=started,
        )
        _validate_source_headers(args)
        event_times = load_event_times(args)
        management_by_name = _validate_management_candidates()

        policies_by_metric: dict[str, list[Policy]] = {}
        ranking_paths: dict[str, tuple[Path, Path]] = {}
        for metric in args.metrics:
            policies, ranking_csv, ranking_manifest = load_policies(args, metric)
            policies_by_metric[metric] = list(policies)
            ranking_paths[metric] = (ranking_csv, ranking_manifest)

        fingerprints = _collect_fingerprints(args, ranking_paths)
        config = _config_payload(args, policies_by_metric, fingerprints)
        config_sha256 = _sha256_payload(config)
        _write_progress(
            paths["progress"],
            args=args,
            status="running",
            phase="loading_bounded_selection_s5",
            started=started,
            config_sha256=config_sha256,
        )

        pair = gene.currency_pair(args.pair)
        inspector, s5_metadata = _load_typed_s5_inspector(Path(args.s5_cache), pair)
        inspector = _slice_inspector_window(
            inspector,
            pd.Timestamp(args.selection_start),
            pd.Timestamp(args.selection_end),
        )
        args.lifecycle_s5_rows_total = int(len(inspector.times))
        _validate_s5_timeline(inspector, s5_source=Path(args.s5_cache))
        coverage_args = argparse.Namespace(start=args.selection_start, end=args.selection_end)
        coverage_errors = _s5_coverage_errors(inspector.times, coverage_args)
        if coverage_errors:
            raise ValueError(
                "Selection S5 coverage is incomplete: " + " | ".join(coverage_errors)
            )

        total_replays = len(args.metrics) * (len(LIFECYCLE_LOSS_POLICIES) + 1)
        completed_replays = 0
        last_discord_progress_bucket = 0

        def notice_global_progress(metric: str, policy_name: str) -> None:
            nonlocal last_discord_progress_bucket
            percent = 100.0 * completed_replays / total_replays
            bucket = int(percent // 25)
            if bucket <= last_discord_progress_bucket or completed_replays >= total_replays:
                return
            last_discord_progress_bucket = bucket
            _notify(
                "\n".join(
                    [
                        f"{args.pair} lifecycle train search 進捗",
                        f"- 処理: {completed_replays}/{total_replays} ({percent:.1f}%)",
                        f"- metric: {metric}",
                        f"- 完了候補: {policy_name}",
                        "- 完成済み候補はcheckpoint済み",
                    ]
                )
            )

        all_summary_rows: list[dict[str, Any]] = []
        all_monthly_rows: list[dict[str, Any]] = []
        all_condition_rows: list[dict[str, Any]] = []
        all_trade_frames: list[pd.DataFrame] = []
        verified_trade_frames: list[pd.DataFrame] = []
        verified_monthly_rows: list[dict[str, Any]] = []
        selected_management: dict[str, ExitManagementPolicy] = {}
        selected_condition_rows: dict[str, list[dict[str, Any]]] = {}
        selected_policies: dict[str, list[Policy]] = {}
        management_results: dict[str, list[dict[str, Any]]] = {}
        train_verified: dict[str, dict[str, Any]] = {}

        for metric in args.metrics:
            immutable_policies = policies_by_metric[metric]
            intents = build_intents(args, immutable_policies, event_times)
            metric_summaries: list[dict[str, Any]] = []
            metric_conditions: dict[str, list[dict[str, Any]]] = {}

            for management_policy in LIFECYCLE_LOSS_POLICIES:
                replay_number = completed_replays

                def progress_callback(
                    percent: int,
                    counters: dict[str, int],
                    _open_positions: int,
                    _pending: bool,
                ) -> None:
                    global_percent = 100.0 * (
                        replay_number + percent / 100.0
                    ) / total_replays
                    _write_progress(
                        paths["progress"],
                        args=args,
                        status="running",
                        phase="management_grid",
                        started=started,
                        config_sha256=config_sha256,
                        ranking_metric=metric,
                        management_policy=management_policy.name,
                        progress_percent=global_percent,
                        replay_percent=percent,
                        completed_replays=replay_number,
                        total_replays=total_replays,
                        counters=counters,
                    )

                trades, replay_summary, reused = _run_or_resume_replay(
                    args,
                    scope="all_top15",
                    checkpoint_fingerprint=config_sha256,
                    metric=metric,
                    policies=immutable_policies,
                    event_times=event_times,
                    intents=intents,
                    inspector=inspector,
                    management_policy=management_policy,
                    progress_callback=progress_callback,
                )
                summary_row = _summary_row(
                    args,
                    metric,
                    management_policy,
                    trades,
                    replay_summary,
                )
                condition_rows = _condition_rows(
                    args,
                    metric,
                    management_policy,
                    immutable_policies,
                    trades,
                )
                metric_summaries.append(summary_row)
                metric_conditions[management_policy.name] = condition_rows
                all_summary_rows.append(summary_row)
                all_condition_rows.extend(condition_rows)
                all_monthly_rows.extend(
                    _monthly_rows(
                        args,
                        metric,
                        management_policy,
                        trades,
                        phase="management_grid",
                    )
                )
                exported = trades.copy()
                exported.insert(0, "ranking_metric", metric)
                exported.insert(0, "phase", "management_grid")
                exported.insert(0, "pair", args.pair)
                all_trade_frames.append(exported)
                completed_replays += 1
                notice_global_progress(metric, management_policy.name)
                _write_progress(
                    paths["progress"],
                    args=args,
                    status="running",
                    phase="management_grid",
                    started=started,
                    config_sha256=config_sha256,
                    ranking_metric=metric,
                    management_policy=management_policy.name,
                    progress_percent=100.0 * completed_replays / total_replays,
                    replay_percent=100,
                    completed_replays=completed_replays,
                    total_replays=total_replays,
                    checkpoint_reused=reused,
                )

            management_results[metric] = metric_summaries
            winning_row = _select_management(metric, metric_summaries)
            winner = management_by_name[str(winning_row["management_policy"])]
            selected_management[metric] = winner
            chosen_conditions = _select_conditions(
                args,
                metric,
                metric_conditions[winner.name],
            )
            selected_condition_rows[metric] = chosen_conditions
            chosen_identities = {
                (str(row["order_name"]), str(row["condition_id"]))
                for row in chosen_conditions
            }
            chosen_policies = [
                policy
                for policy in immutable_policies
                if (policy.order_name, policy.condition_id) in chosen_identities
            ]
            if len(chosen_policies) != len(chosen_identities):
                raise RuntimeError(f"Selected condition identity mismatch for {metric}")
            selected_policies[metric] = chosen_policies

            verified_intents = build_intents(args, chosen_policies, event_times)
            verified_config = {
                "base_config_sha256": config_sha256,
                "ranking_metric": metric,
                "management_policy": asdict(winner),
                "selected_policies": [asdict(policy) for policy in chosen_policies],
            }
            verified_fingerprint = _sha256_payload(verified_config)
            replay_number = completed_replays

            def verified_progress_callback(
                percent: int,
                counters: dict[str, int],
                _open_positions: int,
                _pending: bool,
            ) -> None:
                global_percent = 100.0 * (
                    replay_number + percent / 100.0
                ) / total_replays
                _write_progress(
                    paths["progress"],
                    args=args,
                    status="running",
                    phase="train_verified",
                    started=started,
                    config_sha256=config_sha256,
                    ranking_metric=metric,
                    management_policy=winner.name,
                    progress_percent=global_percent,
                    replay_percent=percent,
                    completed_replays=replay_number,
                    total_replays=total_replays,
                    counters=counters,
                )

            verified_trades, verified_summary, verified_reused = _run_or_resume_replay(
                args,
                scope="train_verified",
                checkpoint_fingerprint=verified_fingerprint,
                metric=metric,
                policies=chosen_policies,
                event_times=event_times,
                intents=verified_intents,
                inspector=inspector,
                management_policy=winner,
                progress_callback=verified_progress_callback,
            )
            verified_performance = _performance(verified_trades)
            verified_monthly = _monthly_rows(
                args,
                metric,
                winner,
                verified_trades,
                phase="train_verified",
            )
            verified_monthly_rows.extend(verified_monthly)
            verified_export = verified_trades.copy()
            verified_export.insert(0, "ranking_metric", metric)
            verified_export.insert(0, "phase", "train_verified")
            verified_export.insert(0, "pair", args.pair)
            verified_trade_frames.append(verified_export)
            train_verified[metric] = {
                "management_policy": winner.name,
                "selected_policy_count": len(chosen_policies),
                "summary": verified_summary,
                "performance": verified_performance,
                "monthly_rows": verified_monthly,
                "checkpoint_fingerprint": verified_fingerprint,
                "checkpoint_reused": verified_reused,
            }
            completed_replays += 1
            notice_global_progress(metric, winner.name + " / train_verified")
            _write_progress(
                paths["progress"],
                args=args,
                status="running",
                phase="train_verified",
                started=started,
                config_sha256=config_sha256,
                ranking_metric=metric,
                management_policy=winner.name,
                progress_percent=100.0 * completed_replays / total_replays,
                replay_percent=100,
                completed_replays=completed_replays,
                total_replays=total_replays,
                checkpoint_reused=verified_reused,
            )
            _notify(
                "\n".join(
                    [
                        f"{args.pair} lifecycle train {metric} 選定",
                        f"- management: {winner.name}",
                        f"- condition: {len(chosen_policies)}件",
                        f"- train_verified: {verified_performance['sum_yen']:.0f}円 / {verified_performance['sum_pips']:.2f}pips",
                    ]
                )
            )

        if completed_replays != total_replays:
            raise RuntimeError(
                f"Replay accounting mismatch: {completed_replays} != {total_replays}"
            )
        _assert_fingerprints_unchanged(fingerprints)

        summary_frame = pd.DataFrame(all_summary_rows)
        monthly_frame = pd.DataFrame(all_monthly_rows)
        condition_frame = pd.DataFrame(all_condition_rows)
        trades_frame = pd.concat(all_trade_frames, ignore_index=True, sort=False)
        verified_trades_frame = pd.concat(
            verified_trade_frames, ignore_index=True, sort=False
        )
        verified_monthly_frame = pd.DataFrame(verified_monthly_rows)

        csv_frames = {
            "summary": summary_frame,
            "monthly": monthly_frame,
            "trades": trades_frame,
            "conditions": condition_frame,
            "verified_trades": verified_trades_frame,
            "verified_monthly": verified_monthly_frame,
        }
        csv_temporaries = {
            name: _write_csv_temporary(frame, paths[name])
            for name, frame in csv_frames.items()
        }
        elapsed_seconds = time.monotonic() - started
        durable_outputs = {
            name: str(path.resolve())
            for name, path in paths.items()
            if name != "progress"
        }
        selected_management_payload = {
            metric: asdict(policy)
            for metric, policy in selected_management.items()
        }
        selected_policies_payload = {
            metric: [asdict(policy) for policy in policies]
            for metric, policies in selected_policies.items()
        }
        selection_integrity_payload = {
            "pair": args.pair,
            "selection_start_inclusive": args.selection_start,
            "selection_end_exclusive": args.selection_end,
            "following_start_inclusive": args.following_start,
            "following_end_exclusive": args.following_end,
            "config_sha256": config_sha256,
            "selected_management_policies": selected_management_payload,
            "selected_policies": selected_policies_payload,
            "train_verified": train_verified,
        }
        artifact = {
            "version": LIFECYCLE_TRAIN_VERSION,
            "status": "complete",
            "pair": args.pair,
            "selection": {
                "start_inclusive": args.selection_start,
                "end_exclusive": args.selection_end,
                "metrics": list(args.metrics),
                "management_rule": _selection_rules(args)["management"],
                "condition_rule": _selection_rules(args)["condition"],
            },
            "following": {
                "start_inclusive": args.following_start,
                "end_exclusive": args.following_end,
            },
            "settings": _settings(args),
            "config": config,
            "config_sha256": config_sha256,
            "fingerprints": fingerprints,
            "s5_metadata": s5_metadata,
            "s5_window": {
                "start_inclusive": args.selection_start,
                "end_exclusive": args.selection_end,
                "row_count": int(len(inspector.times)),
                "first_time": pd.Timestamp(inspector.times[0]),
                "last_time": pd.Timestamp(inspector.times[-1]),
                "coverage_errors": coverage_errors,
            },
            "management_candidates": [
                asdict(policy) for policy in LIFECYCLE_LOSS_POLICIES
            ],
            "management_results": management_results,
            "selected_management_policies": selected_management_payload,
            "selected_condition_rows": selected_condition_rows,
            "selected_policies": selected_policies_payload,
            "train_verified": train_verified,
            "selection_sha256": _sha256_payload(selection_integrity_payload),
            "future_safety": {
                "selection_window_half_open": True,
                "following_boundary_only_no_following_paths": True,
                "following_files_read": False,
                "top15_shape_entry_tp_initial_lc_immutable": True,
                "management_selected_only_on_selection_window": True,
                "conditions_selected_only_on_selection_window": True,
                "selected_subset_replayed_with_full_portfolio_lifecycle": True,
                "candidate_schema_and_decision_causality_validated": True,
                "s5_lower_bound_searchsorted": True,
                "s5_upper_bound_searchsorted_exclusive": True,
                "unknown_s5_gaps_rejected": True,
                "residual_no_tick_gaps_require_causal_csv_proof": True,
                "decision_in_proven_no_tick_gap_waits_for_next_s5": True,
                "same_s5_and_nonretroactive_lc_rules_inherited_from_replay": True,
                "source_fingerprints_rechecked_before_commit": True,
                "fixed_selection_payload_sha256_recorded": True,
            },
            "outputs": durable_outputs,
            "output_tables": {
                name: {
                    "rows": int(len(frame)),
                    "columns": list(frame.columns),
                }
                for name, frame in csv_frames.items()
            },
            "created_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            "elapsed_seconds": elapsed_seconds,
        }
        artifact_tmp = paths["artifact"].with_suffix(paths["artifact"].suffix + ".tmp")
        artifact_tmp.write_text(
            json.dumps(
                _json_safe(artifact),
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
            ),
            encoding="utf-8",
        )
        for name, temporary in csv_temporaries.items():
            temporary.replace(paths[name])
        artifact_tmp.replace(paths["artifact"])

        _write_progress(
            paths["progress"],
            args=args,
            status="complete",
            phase="complete",
            started=started,
            config_sha256=config_sha256,
            progress_percent=100.0,
            replay_percent=100,
            completed_replays=completed_replays,
            total_replays=total_replays,
        )
        paths["progress"] = _archive_file(paths["progress"])
        completion_lines = [
            f"{args.pair} lifecycle train search 完了",
            f"- artifact: {paths['artifact']}",
            f"- config SHA256: {config_sha256}",
        ]
        for metric in args.metrics:
            verified = train_verified[metric]["performance"]
            completion_lines.append(
                f"- {metric}: {selected_management[metric].name}, "
                f"conditions={len(selected_policies[metric])}, "
                f"verified={verified['sum_yen']:.0f}円/{verified['sum_pips']:.2f}pips"
            )
        _notify("\n".join(completion_lines))
        return paths
    except Exception as error:
        try:
            _write_progress(
                paths["progress"],
                args=args,
                status="failed",
                phase="failed",
                started=started,
                config_sha256=config_sha256,
                error=f"{type(error).__name__}: {error}",
            )
        finally:
            _failure_cleanup(paths)
        _notify(
            "\n".join(
                [
                    f"{args.pair} lifecycle train search 失敗",
                    f"- error type: {type(error).__name__}",
                    f"- detail: {error}",
                    "- 完成済みcheckpoint shardは再開用に保持",
                    "- final/temp/progressはarchive済み",
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
