"""Compare causal 60-minute exit-management policies on fixed OOS Top15 orders.

This module is inspection-only.  It never mutates the live strategy profile.
The prior-two-year yen/pips Top15 policies remain fixed, and every management
variant is replayed on the same following-year causal inputs.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pandas as pd

import fGeneric as gene
import test_win_point_usd_aud as win_point
from count2_prior2y_oos_replay import (
    DEFAULT_OOS_END,
    DEFAULT_OOS_START,
    DEFAULT_TRAIN_END,
    DEFAULT_TRAIN_START,
    EXIT_COMPARISON_POLICIES,
    _archive_file,
    _monthly_summary,
    _validate_s5_timeline,
    _validate_source_headers,
    build_intents,
    load_event_times,
    load_policies,
    parse_args as parse_replay_args,
    replay_metric,
)
from count2_target_grid_search import (
    _bound_inspector_before,
    _load_typed_s5_inspector,
    _s5_coverage_errors,
)


COMPARISON_VERSION = "count2_exit_policy_comparison_v2"
BASELINE_KEYS = (
    "events",
    "matched_intents",
    "submitted",
    "filled",
    "not_filled_timeout",
    "cancelled_period_end",
    "cancelled_next_count2",
    "blocked_unprotected_position",
    "blocked_duplicate",
    "blocked_slot_capacity",
    "blocked_opposite",
    "opposite_profit_closed",
    "profit_locks",
    "decisions_activated_at_next_s5_after_closure",
    "completed_trades",
    "wins",
    "losses",
    "sum_yen",
    "sum_pips",
    "max_drawdown_yen",
    "period_end_mark_count",
)


def parse_args(
    argv: list[str] | None = None,
    *,
    default_pair: str = "USD_JPY",
    default_train_start: dt.datetime = DEFAULT_TRAIN_START,
    default_train_end: dt.datetime = DEFAULT_TRAIN_END,
    default_oos_start: dt.datetime = DEFAULT_OOS_START,
    default_oos_end: dt.datetime = DEFAULT_OOS_END,
) -> argparse.Namespace:
    return parse_replay_args(
        argv,
        default_pair=default_pair,
        default_train_start=default_train_start,
        default_train_end=default_train_end,
        default_oos_start=default_oos_start,
        default_oos_end=default_oos_end,
    )


def _stem(args: argparse.Namespace) -> str:
    return (
        f"{args.pair}_{args.train_start:%Y%m%d}_{args.train_end:%Y%m%d}"
        f"_to_{args.oos_start:%Y%m%d}_{args.oos_end:%Y%m%d}"
        f"_tm{args.trade_timeout_min}m"
    )


def _paths(args: argparse.Namespace) -> dict[str, Path]:
    stem = _stem(args)
    return {
        "summary_csv": args.output_dir / f"count2_exit_policy_comparison_v2_{stem}.csv",
        "summary_json": args.output_dir / f"count2_exit_policy_comparison_v2_{stem}.json",
        "monthly": args.output_dir / f"count2_exit_policy_monthly_v2_{stem}.csv",
        "trades": args.output_dir / f"count2_exit_policy_trades_v2_{stem}.csv",
        "progress": args.output_dir / f"count2_exit_policy_progress_v2_{stem}.json",
    }


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    temporary.replace(path)


def _prepare_outputs(args: argparse.Namespace) -> dict[str, Path]:
    paths = _paths(args)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for path in paths.values():
        if path.exists():
            _archive_file(path)
        temporary = path.with_suffix(path.suffix + ".tmp")
        if temporary.exists():
            _archive_file(temporary)
    return paths


def _write_progress(
    path: Path,
    *,
    args: argparse.Namespace,
    status: str,
    metric: str,
    policy: str,
    global_percent: float,
    replay_percent: int,
    started: float,
    counters: dict[str, int] | None = None,
    error: str | None = None,
) -> None:
    _write_json_atomic(
        path,
        {
            "version": COMPARISON_VERSION,
            "status": status,
            "pair": args.pair,
            "metric": metric,
            "management_policy": policy,
            "progress_percent": round(global_percent, 3),
            "current_replay_percent": replay_percent,
            "elapsed_minutes": round((time.monotonic() - started) / 60.0, 2),
            "counters": counters or {},
            "error": error,
            "updated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        },
    )


def _baseline_summary_path(args: argparse.Namespace, metric: str) -> Path:
    stem = (
        f"{metric}_{args.pair}_{args.train_start:%Y%m%d}_{args.train_end:%Y%m%d}"
        f"_to_{args.oos_start:%Y%m%d}_{args.oos_end:%Y%m%d}"
    )
    return args.output_dir / f"count2_prior2y_oos_summary_{stem}.json"


def _assert_current_matches_reference(
    args: argparse.Namespace,
    metric: str,
    summary: dict[str, Any],
) -> str:
    path = _baseline_summary_path(args, metric)
    if not path.is_file():
        return "reference_missing"
    reference = json.loads(path.read_text(encoding="utf-8"))["result"]
    mismatches: list[str] = []
    for key in BASELINE_KEYS:
        actual = summary.get(key)
        expected = reference.get(key)
        if isinstance(expected, float) or isinstance(actual, float):
            if not math.isclose(float(actual), float(expected), rel_tol=0.0, abs_tol=1e-6):
                mismatches.append(f"{key}: {actual} != {expected}")
        elif actual != expected:
            mismatches.append(f"{key}: {actual} != {expected}")
    if mismatches:
        raise RuntimeError(
            "Current management no longer reproduces the completed baseline: "
            + " | ".join(mismatches)
        )
    return "matched"


def _result_row(
    args: argparse.Namespace,
    metric: str,
    policy_name: str,
    trades: pd.DataFrame,
    summary: dict[str, Any],
) -> dict[str, Any]:
    positive = trades[trades["result_r"] > 0]
    negative = trades[trades["result_r"] < 0]
    gross_profit_r = float(positive["result_r"].sum())
    gross_loss_r = float(-negative["result_r"].sum())
    monthly = _monthly_summary(trades)
    return {
        "pair": args.pair,
        "ranking_metric": metric,
        "management_policy": policy_name,
        "trades": int(len(trades)),
        "wins": int((trades["result_r"] > 0).sum()),
        "losses": int((trades["result_r"] < 0).sum()),
        "flat": int((trades["result_r"] == 0).sum()),
        "win_rate": float((trades["result_r"] > 0).mean()) if len(trades) else 0.0,
        "sum_yen": float(trades["result_yen"].sum()),
        "sum_pips": float(trades["result_pips"].sum()),
        "sum_r": float(trades["result_r"].sum()),
        "average_r": float(trades["result_r"].mean()) if len(trades) else 0.0,
        "average_win_r": float(positive["result_r"].mean()) if len(positive) else 0.0,
        "average_loss_r": float(negative["result_r"].mean()) if len(negative) else 0.0,
        "profit_factor_r": gross_profit_r / gross_loss_r if gross_loss_r else math.inf,
        "max_drawdown_yen": float(summary.get("max_drawdown_yen", 0.0)),
        "positive_months_yen": int((monthly["sum_yen"] > 0).sum()),
        "positive_months_pips": int((monthly["sum_pips"] > 0).sum()),
        "profit_locks": int(summary.get("profit_locks", 0)),
        "profit_lock_updates": int(summary.get("profit_lock_updates", 0)),
        "loss_caps": int(summary.get("loss_caps", 0)),
        "loss_cap_immediate_exits": int(summary.get("loss_cap_immediate_exits", 0)),
        "loss_timeout_market_exits": int(summary.get("loss_timeout_market_exits", 0)),
        "submitted": int(summary.get("submitted", 0)),
        "filled": int(summary.get("filled", 0)),
        "blocked_unprotected_position": int(
            summary.get("blocked_unprotected_position", 0)
        ),
    }


def _notice_start(args: argparse.Namespace) -> None:
    win_point.send_inspection_notice(
        "\n".join(
            [
                f"{args.pair} 60分後LC管理 比較検証 開始",
                f"- 学習条件固定: {args.train_start:%Y-%m-%d} ～ {args.train_end:%Y-%m-%d}未満",
                f"- OOS: {args.oos_start:%Y-%m-%d} ～ {args.oos_end:%Y-%m-%d}未満",
                "- 対象: 円Top15 / pips Top15",
                "- 比較: "
                + " / ".join(policy.name for policy in EXIT_COMPARISON_POLICIES),
                f"- 段階式LC: {args.trade_timeout_min}分後からTP幅20/40/60/80%で発動し、各到達幅の50%を確保",
                "- 60分時点の判断には、その時点までに確定したS5だけを使用",
            ]
        )
    )


def _notice_complete(args: argparse.Namespace, frame: pd.DataFrame, path: Path) -> None:
    lines = [f"{args.pair} 60分後LC管理 比較検証 完了"]
    for row in frame.to_dict("records"):
        lines.append(
            "- "
            f"{row['ranking_metric']} / {row['management_policy']}: "
            f"{row['sum_yen']:.0f}円, {row['sum_pips']:.1f}pips, "
            f"{row['sum_r']:.2f}R, 勝率{100 * row['win_rate']:.1f}%, "
            f"PF{row['profit_factor_r']:.2f}, DD{row['max_drawdown_yen']:.0f}円"
        )
    lines.append(f"- 集計: {path}")
    win_point.send_inspection_notice("\n".join(lines))


def run(args: argparse.Namespace) -> dict[str, Path]:
    paths = _prepare_outputs(args)
    started = time.monotonic()
    _notice_start(args)
    try:
        _validate_source_headers(args)
        event_times = load_event_times(args)
        pair = gene.currency_pair(args.pair)
        inspector, metadata = _load_typed_s5_inspector(Path(args.s5_cache), pair)
        inspector = _bound_inspector_before(inspector, pd.Timestamp(args.oos_end))
        _validate_s5_timeline(inspector, s5_source=Path(args.s5_cache))
        coverage_args = argparse.Namespace(start=args.oos_start, end=args.oos_end)
        coverage_errors = _s5_coverage_errors(inspector.times, coverage_args)
        if coverage_errors:
            raise ValueError("OOS S5 coverage is incomplete: " + " | ".join(coverage_errors))

        result_rows: list[dict[str, Any]] = []
        all_trades: list[pd.DataFrame] = []
        all_monthly: list[pd.DataFrame] = []
        baseline_checks: dict[str, str] = {}
        total_replays = len(args.metrics) * len(EXIT_COMPARISON_POLICIES)
        replay_number = 0

        for metric in args.metrics:
            policies, ranking_path, ranking_manifest = load_policies(args, metric)
            intents = build_intents(args, policies, event_times)
            for management_policy in EXIT_COMPARISON_POLICIES:
                current_number = replay_number

                def progress_callback(
                    percent: int,
                    counters: dict[str, int],
                    _open_positions: int,
                    _pending: bool,
                ) -> None:
                    global_percent = 100.0 * (
                        current_number + percent / 100.0
                    ) / total_replays
                    _write_progress(
                        paths["progress"],
                        args=args,
                        status="running",
                        metric=metric,
                        policy=management_policy.name,
                        global_percent=global_percent,
                        replay_percent=percent,
                        started=started,
                        counters=counters,
                    )

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
                if management_policy.name == "current":
                    baseline_checks[metric] = _assert_current_matches_reference(
                        args, metric, summary
                    )
                trades = trades.copy()
                trades.insert(0, "ranking_metric", metric)
                all_trades.append(trades)
                monthly = _monthly_summary(trades)
                monthly.insert(0, "management_policy", management_policy.name)
                monthly.insert(0, "ranking_metric", metric)
                all_monthly.append(monthly)
                result_rows.append(
                    _result_row(
                        args,
                        metric,
                        management_policy.name,
                        trades,
                        summary,
                    )
                )
                replay_number += 1

        result_frame = pd.DataFrame(result_rows)
        current_by_metric = result_frame[
            result_frame["management_policy"] == "current"
        ].set_index("ranking_metric")
        result_frame["delta_yen_vs_current"] = result_frame.apply(
            lambda row: row["sum_yen"]
            - current_by_metric.loc[row["ranking_metric"], "sum_yen"],
            axis=1,
        )
        result_frame["delta_pips_vs_current"] = result_frame.apply(
            lambda row: row["sum_pips"]
            - current_by_metric.loc[row["ranking_metric"], "sum_pips"],
            axis=1,
        )
        result_frame["delta_r_vs_current"] = result_frame.apply(
            lambda row: row["sum_r"]
            - current_by_metric.loc[row["ranking_metric"], "sum_r"],
            axis=1,
        )

        trades_frame = pd.concat(
            [frame.dropna(axis=1, how="all") for frame in all_trades],
            ignore_index=True,
        )
        monthly_frame = pd.concat(all_monthly, ignore_index=True)
        result_frame.to_csv(paths["summary_csv"].with_suffix(".csv.tmp"), index=False, encoding="utf-8-sig")
        monthly_frame.to_csv(paths["monthly"].with_suffix(".csv.tmp"), index=False, encoding="utf-8-sig")
        trades_frame.to_csv(paths["trades"].with_suffix(".csv.tmp"), index=False, encoding="utf-8-sig")
        payload = {
            "status": "complete",
            "version": COMPARISON_VERSION,
            "pair": args.pair,
            "train_start_inclusive": args.train_start,
            "train_end_exclusive": args.train_end,
            "oos_start_inclusive": args.oos_start,
            "oos_end_exclusive": args.oos_end,
            "metrics": list(args.metrics),
            "management_policies": [asdict(policy) for policy in EXIT_COMPARISON_POLICIES],
            "baseline_reference_checks": baseline_checks,
            "settings": {
                "trade_timeout_min": args.trade_timeout_min,
                "profit_lock_ratio_for_current": args.profit_lock_ratio,
                "spread_pips": args.spread_pips,
                "min_target_pips": args.min_target_pips,
                "risk_yen": args.risk_yen,
                "duplicate_threshold_pips": args.duplicate_threshold_pips,
                "step_profit_lock_progression": "at_most_one_stage_per_completed_s5",
            },
            "future_safety": {
                "ranking_fixed_before_oos": True,
                "management_decision_uses_current_or_prior_s5_only": True,
                "loss_cap_never_applied_retroactively_inside_current_s5": True,
                "step_profit_lock_uses_completed_s5_close_only": True,
                "step_profit_lock_becomes_effective_from_following_s5": True,
                "step_profit_lock_does_not_use_pre_timeout_mfe": True,
                "step_profit_lock_advances_at_most_one_stage_per_s5": True,
                "future_path_used_only_for_subsequent_outcome": True,
                "residual_no_tick_gaps_require_causal_csv_proof": True,
                "decision_in_proven_no_tick_gap_waits_for_next_s5": True,
                "oos_end_exclusive": True,
            },
            "s5_cache": str(Path(args.s5_cache).resolve()),
            "s5_metadata": metadata,
            "results": result_frame.to_dict("records"),
            "elapsed_seconds": time.monotonic() - started,
            "outputs": {key: str(path) for key, path in paths.items()},
        }
        paths["summary_json"].with_suffix(".json.tmp").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        paths["summary_csv"].with_suffix(".csv.tmp").replace(paths["summary_csv"])
        paths["monthly"].with_suffix(".csv.tmp").replace(paths["monthly"])
        paths["trades"].with_suffix(".csv.tmp").replace(paths["trades"])
        paths["summary_json"].with_suffix(".json.tmp").replace(paths["summary_json"])
        _write_progress(
            paths["progress"],
            args=args,
            status="complete",
            metric="all",
            policy="all",
            global_percent=100.0,
            replay_percent=100,
            started=started,
        )
        _archive_file(paths["progress"])
        _notice_complete(args, result_frame, paths["summary_csv"])
        return paths
    except Exception as error:
        if paths["progress"].exists():
            _archive_file(paths["progress"])
        for path in paths.values():
            temporary = path.with_suffix(path.suffix + ".tmp")
            if temporary.exists():
                _archive_file(temporary)
        win_point.send_inspection_notice(
            "\n".join(
                [
                    f"{args.pair} 60分後LC管理 比較検証 異常終了",
                    f"- エラー種別: {type(error).__name__}",
                    f"- 内容: {error}",
                    "- temp/progress: archiveへ移動済み",
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
    default_oos_start: dt.datetime = DEFAULT_OOS_START,
    default_oos_end: dt.datetime = DEFAULT_OOS_END,
) -> dict[str, Path]:
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
