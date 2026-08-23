# 最終更新: 2026-08-23 08:22 JST
"""Replay one frozen flip_predict artifact on the following one-year period."""

from __future__ import annotations

import datetime as dt
import json
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import test_win_point_usd_aud as win_point
import tokens as tk
from count2_flip_analysis import analysis_output_paths
from count2_flip_core import (
    FLIP_VERSION,
    FlipPathConfig,
    PolicyCondition,
    RankedPolicyCondition,
    TierExecutionConfig,
)
from count2_flip_workflow import (
    MIN_TRADE_RANGE_FRACTION_A,
    MIN_TRADE_RANGE_FRACTION_PIPS,
    archive_file,
    atomic_csv,
    atomic_json,
    candidate_source_path,
    file_stat,
    inspect_tiered_paths,
    load_candidates,
    load_path_inspector,
    monthly_summary,
    performance_from_frame,
    period_stem,
    replay_condition,
    s5_source_path,
    select_top_condition_policy_candidates,
    write_progress,
)


def replay_output_paths(
    output_dir: Path,
    pair: str,
    train_start: dt.datetime,
    train_end: dt.datetime,
    oos_start: dt.datetime,
    oos_end: dt.datetime,
) -> dict[str, Path]:
    stem = (
        f"{period_stem(pair, train_start, train_end)}"
        f"_to_{oos_start:%Y%m%d}_{oos_end:%Y%m%d}"
    )
    prefix = f"{FLIP_VERSION}_{stem}"
    return {
        "oos_trades": output_dir / f"{prefix}_oos_trades.csv",
        "oos_replay_list": output_dir / f"{prefix}_oos_replay_list.csv",
        "oos_monthly": output_dir / f"{prefix}_oos_monthly.csv",
        "oos_summary": output_dir / f"{prefix}_oos_summary.json",
    }


def _notice(message: str) -> None:
    win_point.send_inspection_notice(message)


def _load_artifact(path: Path, pair: str) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"flip_predict training artifact not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("version") != FLIP_VERSION or payload.get("status") != "complete":
        raise ValueError(
            "flip_predict training artifact is incomplete or incompatible"
        )
    if payload.get("pair") != pair:
        raise ValueError("flip_predict training artifact pair mismatch")
    return payload


def _timestamp_matches(value: Any, expected: dt.datetime) -> bool:
    return pd.Timestamp(value) == pd.Timestamp(expected)


def _readable_trade_list(trades: pd.DataFrame) -> pd.DataFrame:
    if trades.empty:
        return pd.DataFrame(
            columns=(
                "event_id",
                "decision_time",
                "approach_direction",
                "order_side",
                "predicted_role_transition",
                "line_price",
                "line_latest_constituent_peak_direction",
                "line_latest_touch_time",
                "peaks_count",
                "core_peak",
                "flip_flag",
                "signal_tier",
                "highest_matched_rank",
                "matched_condition_count",
                "matched_condition_ids",
                "matched_condition_ranks",
                "configured_tp_a",
                "configured_lc_a",
                "configured_rr",
                "effective_rr",
                "tp_pips",
                "lc_pips",
                "order_fill_time",
                "exit_time",
                "result",
                "result_pips",
                "result_yen",
                "cumulative_yen",
            )
        )
    result = pd.DataFrame(
        {
            "event_id": trades["event_id"],
            "decision_time": trades["decision_time"],
            "approach_direction": trades["peak_direction"].map(
                {1: "UP", -1: "DOWN"}
            ),
            "order_side": trades["order_direction"].map(
                {1: "BUY", -1: "SELL"}
            ),
            "predicted_role_transition": (
                trades["source_role"].astype(str)
                + "->"
                + trades["predicted_role"].astype(str)
            ),
            "line_price": trades["line_price"],
            "line_latest_constituent_peak_direction": trades[
                "line_latest_constituent_peak_direction"
            ],
            "line_latest_touch_time": trades["line_latest_touch_time"],
            "peaks_count": trades["line_count"],
            "core_peak": trades["line_core_count"],
            "flip_flag": trades["f_flip_flag"],
            "signal_tier": trades["signal_tier"],
            "highest_matched_rank": trades["highest_matched_rank"],
            "matched_condition_count": trades["matched_condition_count"],
            "matched_condition_ids": trades["matched_condition_ids"],
            "matched_condition_ranks": trades["matched_condition_ranks"],
            "configured_tp_a": trades["tier_tp_a"],
            "configured_lc_a": trades["tier_lc_a"],
            "configured_rr": trades["tier_rr"],
            "effective_rr": trades["effective_rr"],
            "tp_pips": trades["tp_pips"],
            "lc_pips": trades["lc_pips"],
            "order_fill_time": trades["fill_time"],
            "exit_time": trades["exit_time"],
            "result": trades["trade_result"],
            "result_pips": trades["trade_result_pips"],
            "result_yen": trades["result_yen"],
            "cumulative_yen": trades["cumulative_yen"],
        }
    )
    return result


def run_fixed_replay(
    pair: str,
    *,
    train_start: dt.datetime,
    train_end: dt.datetime,
    oos_start: dt.datetime,
    oos_end: dt.datetime,
    output_dir: Path | None = None,
    artifact_path: Path | None = None,
    source_candidates: Path | None = None,
    s5_cache: Path | None = None,
    max_rows: int | None = None,
    notify: bool = True,
    progress_file: Path | None = None,
    started: float | None = None,
) -> dict[str, Any]:
    pair = pair.upper()
    if max_rows is not None:
        raise ValueError(
            "partial row caps cannot write a formal full-period flip_predict replay"
        )
    if train_end != oos_start:
        raise ValueError("train_end must equal oos_start")
    output_dir = Path(output_dir or tk.folder_path)
    analysis_paths = analysis_output_paths(
        output_dir, pair, train_start, train_end, oos_start, oos_end
    )
    artifact_path = artifact_path or analysis_paths["artifact"]
    progress_file = progress_file or analysis_paths["progress"]
    artifact = _load_artifact(artifact_path, pair)
    analysis_period = artifact["analysis_period"]
    replay_period = artifact["fixed_replay_period"]
    period_checks = (
        _timestamp_matches(analysis_period["start_inclusive"], train_start),
        _timestamp_matches(analysis_period["end_exclusive"], train_end),
        _timestamp_matches(replay_period["start_inclusive"], oos_start),
        _timestamp_matches(replay_period["end_exclusive"], oos_end),
    )
    if not all(period_checks):
        raise ValueError("flip_predict artifact period mismatch")
    trade_eligibility = artifact.get("trade_eligibility", {})
    eligibility_matches = (
        trade_eligibility.get("range_source")
        == "recent_m5_avg_range_pips"
        and float(trade_eligibility.get("fraction_a", float("nan")))
        == MIN_TRADE_RANGE_FRACTION_A
        and float(
            trade_eligibility.get("minimum_fraction_pips", float("nan"))
        )
        == MIN_TRADE_RANGE_FRACTION_PIPS
        and trade_eligibility.get("mandatory_before_condition_ranking") is True
    )
    if not eligibility_matches:
        raise ValueError("flip_predict artifact trade eligibility mismatch")
    paths = replay_output_paths(
        output_dir, pair, train_start, train_end, oos_start, oos_end
    )
    for path in paths.values():
        archive_file(path)
    source_candidates = source_candidates or candidate_source_path(
        pair, oos_start, oos_end, output_dir
    )
    s5_cache = s5_cache or s5_source_path(pair, oos_start, oos_end, output_dir)
    started = started or time.monotonic()
    notifier = _notice if notify else None
    write_progress(
        progress_file,
        pair=pair,
        status="running",
        phase="loading_fixed_replay",
        started=started,
    )
    if notifier:
        notifier(
            "\n".join(
                (
                    f"{pair} flip_predict fixed replay start",
                    f"- period: {oos_start:%Y-%m-%d} <= time < {oos_end:%Y-%m-%d}",
                    "- training conditions are frozen; no reselection is allowed",
                    (
                        "- mandatory range: "
                        f"{MIN_TRADE_RANGE_FRACTION_A:g}A >= "
                        f"{MIN_TRADE_RANGE_FRACTION_PIPS:g} pips"
                    ),
                )
            )
        )
    candidates = load_candidates(
        source_candidates,
        pair=pair,
        start=oos_start,
        end=oos_end,
        max_rows=max_rows,
    )
    execution = artifact["execution"]
    path_inspector, s5_metadata = load_path_inspector(
        s5_cache,
        pair_name=pair,
        start=oos_start,
        end=oos_end,
        spread_pips=float(execution["spread_pips"]),
        position_horizon_minutes=int(execution["position_horizon_minutes"]),
        min_width_pips=float(execution["min_width_pips"]),
        risk_yen=float(execution["risk_yen"]),
    )
    path_config = FlipPathConfig(**artifact["selected_path_config"])
    ranked_conditions = tuple(
        RankedPolicyCondition.from_dict(value)
        for value in artifact["selected_top_conditions"]
    )
    tier_configs = tuple(
        TierExecutionConfig.from_dict(value)
        for value in artifact["tier_execution_configs"]
    )
    tier_ranges_text = ", ".join(
        f"{config.tier}={config.first_rank}-{config.last_rank}"
        for config in tier_configs
    )
    tier_settings_text = ", ".join(
        (
            f"{config.tier}=TP{config.tp_a:g}A/"
            f"RR{config.rr:g}/LC{config.trade_combo.lc_a:g}A"
        )
        for config in tier_configs
    )
    expected_top_count = int(artifact["top_condition_limit"])
    if len(ranked_conditions) != expected_top_count:
        raise ValueError("frozen top-condition count does not match artifact")
    policy_candidates = select_top_condition_policy_candidates(
        candidates, ranked_conditions, tier_configs
    )
    selected_paths = inspect_tiered_paths(
        policy_candidates,
        path_inspector,
        path_config,
        tier_configs,
        pair=pair,
        phase="fixed_one_year_replay",
        period_start=oos_start,
        progress_file=progress_file,
        started=started,
        notify=notifier,
    )
    trades, performance = replay_condition(
        selected_paths, PolicyCondition("ALL", "Top-15 OR policy")
    )
    fixed_policy_counterfactual = performance_from_frame(
        selected_paths, np.ones(len(selected_paths), dtype=bool)
    )
    monthly = monthly_summary(trades)
    readable = _readable_trade_list(trades)
    atomic_csv(paths["oos_trades"], trades)
    atomic_csv(paths["oos_replay_list"], readable)
    atomic_csv(paths["oos_monthly"], monthly)
    elapsed_minutes = (time.monotonic() - started) / 60.0
    summary = {
        "version": FLIP_VERSION,
        "status": "complete",
        "pair": pair,
        "analysis_period": analysis_period,
        "fixed_replay_period": replay_period,
        "source_candidates": file_stat(source_candidates),
        "s5_cache": file_stat(s5_cache),
        "s5_typed_cache": s5_metadata,
        "candidate_rows": len(candidates),
        "top15_or_candidate_rows": len(selected_paths),
        "selected_path_config": artifact["selected_path_config"],
        "condition_ranking_trade_combo": artifact[
            "condition_ranking_trade_combo"
        ],
        "top_condition_limit": expected_top_count,
        "selected_top_conditions": artifact["selected_top_conditions"],
        "tier_execution_configs": artifact["tier_execution_configs"],
        "top_condition_policy": artifact["top_condition_policy"],
        "performance": performance,
        "fixed_policy_counterfactual_performance": fixed_policy_counterfactual,
        "monthly": monthly.to_dict(orient="records"),
        "outputs": {key: str(path.resolve()) for key, path in paths.items()},
        "future_safety": {
            "artifact_frozen_before_replay": True,
            "oos_not_used_for_selection": True,
            "top15_conditions_not_reranked_on_oos": True,
            "tier_settings_loaded_from_training_artifact": True,
            "direct_first_touch_order_without_breakout": True,
            "s5_at_or_after_end_excluded": True,
        },
        "elapsed_minutes": elapsed_minutes,
    }
    atomic_json(paths["oos_summary"], summary)
    write_progress(
        progress_file,
        pair=pair,
        status="complete",
        phase="complete",
        current_row=len(candidates),
        total_rows=len(candidates),
        current_time=oos_end,
        started=started,
    )
    archived_progress = archive_file(progress_file)
    if notifier:
        notifier(
            "\n".join(
                (
                    f"{pair} flip_predict fixed replay complete",
                    f"- candidate lines: {len(candidates)}",
                    f"- order triggers: frozen top {expected_top_count} conditions (OR)",
                    f"- tiers: {tier_ranges_text}",
                    f"- tier settings: {tier_settings_text}",
                    f"- top-15 OR candidate events: {len(selected_paths)}",
                    f"- policy order fill rate: {fixed_policy_counterfactual['order_fill_rate']:.2%}",
                    f"- trades: {performance['completed_trade_count']}",
                    f"- wins: {performance['win_count']}",
                    f"- win rate: {performance['win_rate']:.2%}",
                    f"- average win: {performance['average_win_pips']:.2f} pips",
                    f"- gross profit: {performance['gross_profit_yen']:.0f} yen",
                    f"- gross loss: {performance['gross_loss_yen']:.0f} yen",
                    f"- net profit: {performance['sum_yen']:.0f} yen",
                    f"- total pips: {performance['sum_pips']:.2f}",
                    f"- replay list: {paths['oos_replay_list']}",
                )
            )
        )
    return {
        "summary": summary,
        "paths": paths,
        "trades": trades,
        "progress_archive": archived_progress,
    }


if __name__ == "__main__":
    raise SystemExit("Run a test_kick_<pair>_flip_predict.py launcher")
