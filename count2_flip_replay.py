# 最新更新日時: 2026-08-25 14:59 JST
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
    EARLY_PATH_METRICS,
    EARLY_PATH_MINUTES,
    FLIP_VERSION,
    RANGE_FILTER_FRACTION_A,
    STRETCH_PROFIT_LOCK_B,
    STRETCH_PROFIT_LOCK_TP_FRACTION,
    STRETCH_PROFIT_TARGET_B,
    STRETCH_PROFIT_TRIGGER_B,
    STRETCH_PROFIT_TRIGGER_TP_FRACTION,
    FlipPathConfig,
    FlipWatchEntryConfig,
    LineWickLcConfig,
    PolicyCondition,
    RankedPolicyCondition,
    TierExecutionConfig,
    TimedHalfLcConfig,
)
from count2_flip_workflow import (
    archive_file,
    atomic_csv,
    atomic_json,
    candidate_source_path,
    file_stat,
    four_period_metrics,
    inspect_line_wick_lc_grid_paths,
    inspect_tiered_paths,
    inspect_timed_half_lc_grid_paths,
    load_candidates,
    load_path_inspector,
    line_holding_early_path_dataset,
    monthly_summary,
    performance_from_frame,
    period_stem,
    replay_condition,
    scan_line_wick_lc_grid,
    scan_timed_half_lc_grid,
    s5_source_path,
    select_top_condition_policy_candidates,
    target_distance_filter_mask,
    stretch_profit_lock_inspector,
    stretch_profit_lock_tier_configs,
    summarize_watch_entry_branches,
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
        "oos_watch_entry_trades": output_dir
        / f"{prefix}_oos_watch_entry_trades.csv",
        "oos_watch_entry_paths": output_dir
        / f"{prefix}_oos_watch_entry_paths.csv",
        "oos_watch_entry_replay_list": output_dir
        / f"{prefix}_oos_watch_entry_replay_list.csv",
        "oos_watch_entry_monthly": output_dir
        / f"{prefix}_oos_watch_entry_monthly.csv",
        "oos_watch_entry_branches": output_dir
        / f"{prefix}_oos_watch_entry_branches.csv",
        "oos_watch_entry_comparison": output_dir
        / f"{prefix}_oos_watch_entry_comparison.csv",
        "oos_line_holding_early_path": output_dir
        / f"{prefix}_oos_line_holding_early_path.csv",
        "oos_stretch_profit_lock_trades": output_dir
        / f"{prefix}_oos_stretch_profit_lock_trades.csv",
        "oos_stretch_profit_lock_replay_list": output_dir
        / f"{prefix}_oos_stretch_profit_lock_replay_list.csv",
        "oos_stretch_profit_lock_monthly": output_dir
        / f"{prefix}_oos_stretch_profit_lock_monthly.csv",
        "oos_stretch_profit_lock_comparison": output_dir
        / f"{prefix}_oos_stretch_profit_lock_comparison.csv",
        "oos_timed_half_lc_grid": output_dir
        / f"{prefix}_oos_timed_half_lc_grid.csv",
        "oos_timed_half_lc_trades": output_dir
        / f"{prefix}_oos_timed_half_lc_trades.csv",
        "oos_timed_half_lc_replay_list": output_dir
        / f"{prefix}_oos_timed_half_lc_replay_list.csv",
        "oos_timed_half_lc_monthly": output_dir
        / f"{prefix}_oos_timed_half_lc_monthly.csv",
        "oos_line_wick_lc_grid": output_dir
        / f"{prefix}_oos_line_wick_lc_grid.csv",
        "oos_line_wick_lc_trades": output_dir
        / f"{prefix}_oos_line_wick_lc_trades.csv",
        "oos_line_wick_lc_replay_list": output_dir
        / f"{prefix}_oos_line_wick_lc_replay_list.csv",
        "oos_line_wick_lc_monthly": output_dir
        / f"{prefix}_oos_line_wick_lc_monthly.csv",
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


def _finite_matches(value: Any, expected: float) -> bool:
    try:
        actual = float(value)
    except (TypeError, ValueError):
        return False
    return bool(np.isfinite(actual) and abs(actual - float(expected)) <= 1e-12)


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
                "watch_order_name",
                "watch_entry_mode",
                "watch_initial_touch_deadline",
                "watch_line_touch_time",
                "watch_line_touch_known_time",
                "watch_observation_known_time",
                "watch_order_placed_time",
                "watch_order_release_time",
                "watch_observation_close",
                "watch_observation_high",
                "watch_observation_low",
                "watch_breakout_distance_pips",
                "watch_breakout_distance_a",
                "watch_observed_extreme_price",
                "watch_entry_trigger_price",
                "watch_actual_entry_distance_from_line_a",
                "watch_entry_gap_from_trigger_a",
                "watch_entry_gap_filtered",
                "watch_stop_fill_bar_adverse_censored",
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
                "available_range_filter_pips",
                "tier_min_range_filter_pips",
                "configured_tp_a",
                "configured_lc_a",
                "configured_rr",
                "effective_rr",
                "tp_pips",
                "lc_pips",
                "original_tp_first_reached_time",
                "minutes_to_original_tp",
                "original_lc_first_reached_time",
                "minutes_to_original_lc",
                "profit_lock_trigger_pips",
                "profit_lock_result_pips",
                "profit_lock_result_tp_fraction",
                "profit_lock_effective_result_pips",
                "profit_lock_trigger_reached",
                "profit_lock_activated",
                "profit_lock_active_from",
                "half_tp_trigger_pips",
                "half_tp_reached",
                "half_tp_first_reached_time",
                "minutes_to_half_tp",
                "fill_bar_half_tp_ambiguous",
                "timed_half_lc_config_id",
                "timed_half_lc_trigger_minutes",
                "timed_half_lc_check_time",
                "timed_half_lc_activated",
                "timed_half_lc_suppressed_by_fill_bar_ambiguity",
                "timed_half_lc_active_from",
                "timed_half_lc_effective_pips",
                "timed_half_lc_exit",
                "timed_half_lc_exit_mode",
                "minutes_from_timed_activation_to_exit",
                "line_wick_lc_config_id",
                "line_wick_lc_width_a",
                "line_wick_lc_effective_pips",
                "line_wick_lc_exit",
                "line_wick_lc_exit_mode",
                "line_wick_lc_same_s5_tp_assumed_first",
                "order_fill_time",
                "actual_entry_price",
                "exit_time",
                "exit_effective_time",
                "actual_exit_price",
                "exit_execution_mode",
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
            "watch_order_name": trades.get("watch_order_name"),
            "watch_entry_mode": trades.get("watch_entry_mode"),
            "watch_initial_touch_deadline": trades.get(
                "watch_initial_touch_deadline"
            ),
            "watch_line_touch_time": trades.get("watch_line_touch_time"),
            "watch_line_touch_known_time": trades.get(
                "watch_line_touch_known_time"
            ),
            "watch_observation_known_time": trades.get(
                "watch_observation_known_time"
            ),
            "watch_order_placed_time": trades.get("watch_order_placed_time"),
            "watch_order_release_time": trades.get("watch_order_release_time"),
            "watch_observation_close": trades.get("watch_observation_close"),
            "watch_observation_high": trades.get("watch_observation_high"),
            "watch_observation_low": trades.get("watch_observation_low"),
            "watch_breakout_distance_a": trades.get(
                "watch_breakout_distance_a"
            ),
            "watch_breakout_distance_pips": trades.get(
                "watch_breakout_distance_pips"
            ),
            "watch_entry_trigger_price": trades.get(
                "watch_entry_trigger_price"
            ),
            "watch_observed_extreme_price": trades.get(
                "watch_observed_extreme_price"
            ),
            "watch_actual_entry_distance_from_line_a": trades.get(
                "watch_actual_entry_distance_from_line_a"
            ),
            "watch_entry_gap_from_trigger_a": trades.get(
                "watch_entry_gap_from_trigger_a"
            ),
            "watch_entry_gap_filtered": trades.get(
                "watch_entry_gap_filtered"
            ),
            "watch_stop_fill_bar_adverse_censored": trades.get(
                "watch_stop_fill_bar_adverse_censored"
            ),
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
            "available_range_filter_pips": trades[
                "available_range_filter_pips"
            ],
            "tier_min_range_filter_pips": trades[
                "tier_min_range_filter_pips"
            ],
            "configured_tp_a": trades["tp_a"],
            "configured_lc_a": trades["lc_a"],
            "configured_rr": trades["configured_rr"],
            "effective_rr": trades["effective_rr"],
            "tp_pips": trades["tp_pips"],
            "lc_pips": trades["lc_pips"],
            "original_tp_first_reached_time": trades[
                "original_tp_first_reached_time"
            ],
            "minutes_to_original_tp": trades["minutes_to_original_tp"],
            "original_lc_first_reached_time": trades[
                "original_lc_first_reached_time"
            ],
            "minutes_to_original_lc": trades["minutes_to_original_lc"],
            "profit_lock_trigger_pips": trades[
                "profit_lock_trigger_pips"
            ],
            "profit_lock_result_pips": trades["profit_lock_result_pips"],
            "profit_lock_result_tp_fraction": trades[
                "profit_lock_result_tp_fraction"
            ],
            "profit_lock_effective_result_pips": trades[
                "profit_lock_effective_result_pips"
            ],
            "profit_lock_trigger_reached": trades[
                "profit_lock_trigger_reached"
            ],
            "profit_lock_activated": trades["profit_lock_activated"],
            "profit_lock_active_from": trades["profit_lock_active_from"],
            "half_tp_trigger_pips": trades["half_tp_trigger_pips"],
            "half_tp_reached": trades["half_tp_reached"],
            "half_tp_first_reached_time": trades[
                "half_tp_first_reached_time"
            ],
            "minutes_to_half_tp": trades["minutes_to_half_tp"],
            "fill_bar_half_tp_ambiguous": trades[
                "fill_bar_half_tp_ambiguous"
            ],
            "timed_half_lc_config_id": trades[
                "timed_half_lc_config_id"
            ],
            "timed_half_lc_trigger_minutes": trades[
                "timed_half_lc_trigger_minutes"
            ],
            "timed_half_lc_check_time": trades[
                "timed_half_lc_check_time"
            ],
            "timed_half_lc_activated": trades[
                "timed_half_lc_activated"
            ],
            "timed_half_lc_suppressed_by_fill_bar_ambiguity": trades[
                "timed_half_lc_suppressed_by_fill_bar_ambiguity"
            ],
            "timed_half_lc_active_from": trades[
                "timed_half_lc_active_from"
            ],
            "timed_half_lc_effective_pips": trades[
                "timed_half_lc_effective_pips"
            ],
            "timed_half_lc_exit": trades["timed_half_lc_exit"],
            "timed_half_lc_exit_mode": trades[
                "timed_half_lc_exit_mode"
            ],
            "minutes_from_timed_activation_to_exit": trades[
                "minutes_from_timed_activation_to_exit"
            ],
            "line_wick_lc_config_id": trades[
                "line_wick_lc_config_id"
            ],
            "line_wick_lc_width_a": trades["line_wick_lc_width_a"],
            "line_wick_lc_effective_pips": trades[
                "line_wick_lc_effective_pips"
            ],
            "line_wick_lc_exit": trades["line_wick_lc_exit"],
            "line_wick_lc_exit_mode": trades["line_wick_lc_exit_mode"],
            "line_wick_lc_same_s5_tp_assumed_first": trades[
                "line_wick_lc_same_s5_tp_assumed_first"
            ],
            "order_fill_time": trades["fill_time"],
            "actual_entry_price": trades["actual_entry_price"],
            "exit_time": trades["exit_time"],
            "exit_effective_time": trades["exit_effective_time"],
            "actual_exit_price": trades["actual_exit_price"],
            "exit_execution_mode": trades["exit_execution_mode"],
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
    range_lc_search = artifact.get("range_lc_search", {})
    if (
        range_lc_search.get("range_source")
        != "recent_m5_avg_range_pips"
        or float(range_lc_search.get("fraction_a", float("nan")))
        != RANGE_FILTER_FRACTION_A
        or range_lc_search.get("selection_period") != "analysis_period_only"
        or range_lc_search.get("oos_reselection_allowed") is not False
    ):
        raise ValueError("flip_predict artifact range/TP/LC search mismatch")
    timed_half_lc_search = artifact.get("timed_half_lc_search", {})
    if (
        timed_half_lc_search.get("selection_period")
        != "analysis_period_only"
        or timed_half_lc_search.get("oos_reselection_allowed") is not False
        or "selected_config" not in timed_half_lc_search
        or "selected_configs" not in timed_half_lc_search
        or "replay_configs" not in timed_half_lc_search
    ):
        raise ValueError("flip_predict artifact timed half-LC search mismatch")
    primary_timed_half_lc_config = TimedHalfLcConfig.from_dict(
        timed_half_lc_search["selected_config"]
    )
    selected_timed_half_lc_configs = tuple(
        TimedHalfLcConfig.from_dict(value)
        for value in timed_half_lc_search["selected_configs"]
    )
    replay_timed_half_lc_configs = tuple(
        TimedHalfLcConfig.from_dict(value)
        for value in timed_half_lc_search["replay_configs"]
    )
    replay_ids = [config.config_id for config in replay_timed_half_lc_configs]
    if (
        not replay_timed_half_lc_configs
        or replay_ids[0] != "baseline"
        or len(replay_ids) != len(set(replay_ids))
        or len(selected_timed_half_lc_configs) > 5
    ):
        raise ValueError("frozen timed half-LC replay config list is invalid")
    selected_ids = [config.config_id for config in selected_timed_half_lc_configs]
    if selected_ids != replay_ids[1:]:
        raise ValueError("selected timed half-LC configs do not match replay order")
    expected_primary = (
        selected_timed_half_lc_configs[0]
        if selected_timed_half_lc_configs
        else replay_timed_half_lc_configs[0]
    )
    if primary_timed_half_lc_config != expected_primary:
        raise ValueError("primary timed half-LC config mismatch")
    candidate_timed_ids = {
        TimedHalfLcConfig.from_dict(value).config_id
        for value in timed_half_lc_search.get("candidate_configs", [])
    }
    if not set(replay_ids).issubset(candidate_timed_ids):
        raise ValueError("replay timed half-LC config was not in the train grid")
    line_wick_search = artifact.get("line_wick_lc_search", {})
    if (
        line_wick_search.get("selection_period") != "analysis_period_only"
        or line_wick_search.get("oos_reselection_allowed") is not False
        or line_wick_search.get("used_for_primary_execution") is not True
        or "selected_config" not in line_wick_search
        or "replay_configs" not in line_wick_search
    ):
        raise ValueError("flip_predict artifact line-wick LC search mismatch")
    selected_line_wick_lc_config = LineWickLcConfig.from_dict(
        line_wick_search["selected_config"]
    )
    replay_line_wick_lc_configs = tuple(
        LineWickLcConfig.from_dict(value)
        for value in line_wick_search["replay_configs"]
    )
    line_wick_replay_ids = [
        config.config_id for config in replay_line_wick_lc_configs
    ]
    if (
        not replay_line_wick_lc_configs
        or line_wick_replay_ids[0] != "baseline"
        or len(line_wick_replay_ids) != len(set(line_wick_replay_ids))
        or len(replay_line_wick_lc_configs) > 2
    ):
        raise ValueError("frozen line-wick LC replay list is invalid")
    expected_line_primary = (
        replay_line_wick_lc_configs[-1]
        if selected_line_wick_lc_config.enabled
        else replay_line_wick_lc_configs[0]
    )
    if selected_line_wick_lc_config != expected_line_primary:
        raise ValueError("primary line-wick LC config mismatch")
    candidate_line_wick_ids = {
        LineWickLcConfig.from_dict(value).config_id
        for value in line_wick_search.get("candidate_configs", [])
    }
    if not set(line_wick_replay_ids).issubset(candidate_line_wick_ids):
        raise ValueError("replay line-wick LC config was not in train grid")
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
    frozen_execution = artifact.get("execution", {})
    if "min_target_distance_pips" not in frozen_execution:
        raise ValueError("frozen target-distance filter is incomplete")
    min_target_distance_pips = float(
        frozen_execution["min_target_distance_pips"]
    )
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
                        "- frozen decision-time target-line distance filter: "
                        f">= {min_target_distance_pips:g}p"
                    ),
                    "- tier A-width filters and TP/LC widths are frozen from training",
                    (
                        "- timed half-LC configs frozen from training: "
                        + ",".join(replay_ids)
                    ),
                    "- each timed half-LC config is replayed independently",
                    (
                        "- line-wick LC configs frozen from training: "
                        + ",".join(line_wick_replay_ids)
                    ),
                    "- each line-wick LC config is replayed independently",
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
    candidates = candidates.loc[
        target_distance_filter_mask(candidates, min_target_distance_pips)
    ].copy()
    if candidates.empty:
        raise ValueError("target-distance filter removed every OOS candidate")
    execution = artifact["execution"]
    if not {
        "line_wick_lc",
        "line_wick_lc_replay_configs",
    }.issubset(execution):
        raise ValueError("frozen line-wick LC execution settings are incomplete")
    try:
        execution_timed_half_lc = TimedHalfLcConfig.from_dict(
            execution.get("timed_half_lc", {})
        )
        execution_replay_configs = tuple(
            TimedHalfLcConfig.from_dict(value)
            for value in execution.get("timed_half_lc_replay_configs", [])
        )
        execution_line_wick_lc = LineWickLcConfig.from_dict(
            execution.get("line_wick_lc", {})
        )
        execution_line_wick_replay_configs = tuple(
            LineWickLcConfig.from_dict(value)
            for value in execution.get("line_wick_lc_replay_configs", [])
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(
            "frozen timed half-LC execution settings are incomplete"
        ) from exc
    if (
        execution_timed_half_lc != primary_timed_half_lc_config
        or execution_replay_configs != replay_timed_half_lc_configs
        or execution_line_wick_lc != selected_line_wick_lc_config
        or execution_line_wick_replay_configs
        != replay_line_wick_lc_configs
    ):
        raise ValueError("frozen exit-overlay execution mismatch")
    profit_lock = execution.get("profit_lock", {})
    required_profit_lock_fields = {
        "enabled",
        "minimum_effective_tp_pips",
        "trigger_tp_fraction",
        "locked_result_pips",
    }
    if not required_profit_lock_fields.issubset(profit_lock):
        raise ValueError("frozen profit-lock settings are incomplete")
    if bool(profit_lock["enabled"]):
        raise ValueError(
            f"legacy fixed-pips profit lock must be disabled for {FLIP_VERSION}"
        )
    path_inspector, s5_metadata = load_path_inspector(
        s5_cache,
        pair_name=pair,
        start=oos_start,
        end=oos_end,
        spread_pips=float(execution["spread_pips"]),
        position_horizon_minutes=int(execution["position_horizon_minutes"]),
        min_width_pips=float(execution["min_width_pips"]),
        risk_yen=float(execution["risk_yen"]),
        profit_lock_enabled=bool(profit_lock["enabled"]),
        profit_lock_min_tp_pips=float(
            profit_lock["minimum_effective_tp_pips"]
        ),
        profit_lock_trigger_tp_fraction=float(
            profit_lock["trigger_tp_fraction"]
        ),
        profit_lock_result_pips=float(profit_lock["locked_result_pips"]),
    )
    path_config = FlipPathConfig(**artifact["selected_path_config"])
    if (
        execution.get("unfilled_candidate_replaced_by_next_foot_count2")
        is not path_config.replace_unfilled_on_next_count2
    ):
        raise ValueError("frozen next-FC2 replacement flag mismatch")
    ranked_conditions = tuple(
        RankedPolicyCondition.from_dict(value)
        for value in artifact["selected_top_conditions"]
    )
    tier_configs = tuple(
        TierExecutionConfig.from_dict(value)
        for value in artifact["tier_execution_configs"]
    )
    frozen_tier_rows = {
        str(value["tier"]): value
        for value in range_lc_search.get("selected_tier_rows", [])
    }
    if len(frozen_tier_rows) != len(tier_configs):
        raise ValueError("frozen tier range/TP/LC selections are incomplete")
    for config in tier_configs:
        frozen = frozen_tier_rows.get(config.tier, {})
        if (
            not _finite_matches(
                frozen.get("min_range_filter_pips"),
                config.min_range_filter_pips,
            )
            or not _finite_matches(
                frozen.get("lc_a"), config.trade_combo.lc_a
            )
            or not _finite_matches(frozen.get("tp_a"), config.tp_a)
            or config.rr + 1e-12 < 1.0
        ):
            raise ValueError("frozen tier range/TP/LC selection mismatch")
    watch_policy = artifact.get("watch_entry_policy", {})
    required_watch_fields = {
        "enabled",
        "config",
        "selection_period",
        "oos_reselection_allowed",
        "line_holding_order_name",
        "near_line_order_name",
        "breakout_order_name",
        "line_holding_early_path",
    }
    if not required_watch_fields.issubset(watch_policy):
        raise ValueError("frozen watch-entry policy is incomplete")
    if "watch_entry" not in execution:
        raise ValueError("frozen watch-entry execution is incomplete")
    watch_entry_config = FlipWatchEntryConfig.from_dict(
        watch_policy["config"]
    )
    execution_watch_config = FlipWatchEntryConfig.from_dict(
        execution.get("watch_entry", {})
    )
    early_path_policy = watch_policy.get("line_holding_early_path", {})
    required_early_path_fields = {
        "anchor",
        "elapsed_minutes",
        "snapshot_metrics",
        "price_source",
        "snapshot_availability",
        "interval_mfe_mae_reference",
        "interval_net_reference",
        "final_mfe_window",
        "exit_s5_opposite_extreme",
        "final_labels_not_policy_inputs",
    }
    if (
        watch_policy["enabled"] is not True
        or watch_policy["selection_period"] != "none_fixed_user_design"
        or watch_policy["oos_reselection_allowed"] is not False
        or watch_policy["line_holding_order_name"]
        != "FlipPredict_LineHolding"
        or watch_policy["near_line_order_name"]
        != "FlipPredict_NearLineConsolidation"
        or watch_policy["breakout_order_name"] != "FlipPredict_Breakout"
        or execution_watch_config != watch_entry_config
        or not required_early_path_fields.issubset(early_path_policy)
        or early_path_policy["anchor"] != "actual_fill_timer_anchor"
        or early_path_policy["elapsed_minutes"] != list(EARLY_PATH_MINUTES)
        or early_path_policy["snapshot_metrics"]
        != list(EARLY_PATH_METRICS)
        or early_path_policy["price_source"] != "completed_S5_only"
        or early_path_policy["snapshot_availability"]
        != "only_while_position_open_at_checkpoint"
        or early_path_policy["interval_mfe_mae_reference"]
        != "actual_entry_price"
        or early_path_policy["interval_net_reference"] != "interval_open"
        or early_path_policy["final_mfe_window"]
        != "actual_entry_through_causally_observable_exit_boundary"
        or early_path_policy["exit_s5_opposite_extreme"]
        != "censored_to_open_and_exit"
        or early_path_policy["final_labels_not_policy_inputs"] is not True
    ):
        raise ValueError("frozen watch-entry policy mismatch")
    stretch_policy = artifact.get("stretch_profit_lock", {})
    required_stretch_fields = {
        "enabled",
        "base_width_definition",
        "target_b",
        "trigger_b",
        "locked_result_b",
        "trigger_final_tp_fraction",
        "locked_result_final_tp_fraction",
        "hard_lc",
        "tier_execution_configs",
        "line_wick_lc_config",
        "selection_period",
        "oos_reselection_allowed",
    }
    if not required_stretch_fields.issubset(stretch_policy):
        raise ValueError("frozen stretch-profit policy is incomplete")
    frozen_stretch_tier_configs = tuple(
        TierExecutionConfig.from_dict(value)
        for value in stretch_policy["tier_execution_configs"]
    )
    expected_stretch_tier_configs = stretch_profit_lock_tier_configs(
        tier_configs
    )
    if (
        stretch_policy["enabled"] is not True
        or stretch_policy["base_width_definition"]
        != "1B=frozen_tier_take_profit"
        or not _finite_matches(
            stretch_policy["target_b"], STRETCH_PROFIT_TARGET_B
        )
        or not _finite_matches(
            stretch_policy["trigger_b"], STRETCH_PROFIT_TRIGGER_B
        )
        or not _finite_matches(
            stretch_policy["locked_result_b"], STRETCH_PROFIT_LOCK_B
        )
        or not _finite_matches(
            stretch_policy["trigger_final_tp_fraction"],
            STRETCH_PROFIT_TRIGGER_TP_FRACTION,
        )
        or not _finite_matches(
            stretch_policy["locked_result_final_tp_fraction"],
            STRETCH_PROFIT_LOCK_TP_FRACTION,
        )
        or stretch_policy["hard_lc"] != "frozen_tier_lc_unchanged"
        or frozen_stretch_tier_configs != expected_stretch_tier_configs
        or LineWickLcConfig.from_dict(stretch_policy["line_wick_lc_config"])
        != selected_line_wick_lc_config
        or stretch_policy["selection_period"] != "none_fixed_user_design"
        or stretch_policy["oos_reselection_allowed"] is not False
    ):
        raise ValueError("frozen stretch-profit policy mismatch")
    tier_ranges_text = ", ".join(
        f"{config.tier}={config.first_rank}-{config.last_rank}"
        for config in tier_configs
    )
    tier_settings_text = ", ".join(
        (
            f"{config.tier}=filter{config.min_range_filter_pips:g}p/"
            f"TP{config.tp_a:g}A/RR{config.rr:g}/"
            f"LC{config.trade_combo.lc_a:g}A"
        )
        for config in tier_configs
    )
    expected_top_count = int(artifact["top_condition_limit"])
    if len(ranked_conditions) != expected_top_count:
        raise ValueError("frozen top-condition count does not match artifact")
    policy_candidates = select_top_condition_policy_candidates(
        candidates, ranked_conditions, tier_configs
    )
    watch_entry_paths = inspect_tiered_paths(
        policy_candidates,
        path_inspector,
        path_config,
        tier_configs,
        pair=pair,
        phase="fixed_one_year_watch_entry_replay",
        period_start=oos_start,
        progress_file=progress_file,
        started=started,
        notify=None,
        watch_entry_config=watch_entry_config,
    )
    watch_entry_trades, watch_entry_performance = replay_condition(
        watch_entry_paths,
        PolicyCondition("ALL", "Frozen three-branch watch entry"),
    )
    watch_entry_performance.update(
        four_period_metrics(watch_entry_trades, oos_start, oos_end)
    )
    watch_entry_monthly = monthly_summary(watch_entry_trades)
    watch_entry_branches = summarize_watch_entry_branches(
        watch_entry_paths, watch_entry_trades
    )
    line_holding_early_path_oos = line_holding_early_path_dataset(
        watch_entry_trades,
        phase="fixed_one_year_replay",
    )
    watch_entry_readable = _readable_trade_list(watch_entry_trades)
    stretch_paths = inspect_tiered_paths(
        policy_candidates,
        stretch_profit_lock_inspector(path_inspector),
        path_config,
        frozen_stretch_tier_configs,
        pair=pair,
        phase="fixed_one_year_stretch_profit_lock_replay",
        period_start=oos_start,
        progress_file=progress_file,
        started=started,
        notify=notifier,
        line_wick_lc_config=selected_line_wick_lc_config,
    )
    stretch_trades, stretch_performance = replay_condition(
        stretch_paths,
        PolicyCondition("ALL", "Frozen stretch-profit policy"),
    )
    stretch_monthly = monthly_summary(stretch_trades)
    stretch_readable = _readable_trade_list(stretch_trades)
    replay_paths = inspect_timed_half_lc_grid_paths(
        policy_candidates,
        path_inspector,
        path_config,
        tier_configs,
        replay_timed_half_lc_configs,
        pair=pair,
        phase="fixed_one_year_multi_policy_replay",
        period_start=oos_start,
        progress_file=progress_file,
        started=started,
        notify=notifier,
    )
    oos_timed_half_lc_grid, oos_timed_half_lc_trades = (
        scan_timed_half_lc_grid(
            replay_paths,
            replay_timed_half_lc_configs,
            period_start=oos_start,
            period_end=oos_end,
        )
    )
    train_rank_by_id = {
        config.config_id: rank
        for rank, config in enumerate(
            selected_timed_half_lc_configs, start=1
        )
    }
    oos_timed_half_lc_grid["selected_on_train"] = (
        oos_timed_half_lc_grid["config_id"].isin(train_rank_by_id)
    )
    oos_timed_half_lc_grid["train_selection_rank"] = (
        oos_timed_half_lc_grid["config_id"].map(train_rank_by_id)
    )
    oos_timed_half_lc_grid["baseline_comparison"] = (
        oos_timed_half_lc_grid["config_id"].eq("baseline")
    )
    oos_timed_half_lc_grid["oos_used_for_selection"] = False
    primary_rows = oos_timed_half_lc_grid.loc[
        oos_timed_half_lc_grid["config_id"].eq(
            primary_timed_half_lc_config.config_id
        )
    ]
    if len(primary_rows) != 1:
        raise ValueError("primary OOS timed half-LC result is ambiguous")
    performance = {
        str(key): value
        for key, value in primary_rows.iloc[0].items()
        if key not in {
            "timed_half_lc_policy_order",
            "config_id",
            "enabled",
            "trigger_minutes",
            "lc_fraction",
            "tp_fraction",
        }
    }
    trades = oos_timed_half_lc_trades.loc[
        oos_timed_half_lc_trades["timed_half_lc_config_id"].eq(
            primary_timed_half_lc_config.config_id
        )
    ].copy()
    primary_paths = replay_paths.loc[
        replay_paths["timed_half_lc_config_id"].eq(
            primary_timed_half_lc_config.config_id
        )
    ].copy()
    fixed_policy_counterfactual = performance_from_frame(
        primary_paths, np.ones(len(primary_paths), dtype=bool)
    )
    monthly = monthly_summary(trades)
    readable = _readable_trade_list(trades)
    timed_all_readable = _readable_trade_list(oos_timed_half_lc_trades)
    policy_monthly_frames = []
    for config in replay_timed_half_lc_configs:
        config_trades = oos_timed_half_lc_trades.loc[
            oos_timed_half_lc_trades["timed_half_lc_config_id"].eq(
                config.config_id
            )
        ]
        config_monthly = monthly_summary(config_trades)
        config_monthly.insert(0, "config_id", config.config_id)
        policy_monthly_frames.append(config_monthly)
    policy_monthly = (
        pd.concat(policy_monthly_frames, ignore_index=True)
        if policy_monthly_frames
        else pd.DataFrame()
    )
    line_wick_paths = inspect_line_wick_lc_grid_paths(
        policy_candidates,
        path_inspector,
        path_config,
        tier_configs,
        replay_line_wick_lc_configs,
        pair=pair,
        phase="fixed_one_year_line_wick_lc_replay",
        period_start=oos_start,
        progress_file=progress_file,
        started=started,
        notify=notifier,
    )
    oos_line_wick_lc_grid, oos_line_wick_lc_trades = (
        scan_line_wick_lc_grid(
            line_wick_paths,
            replay_line_wick_lc_configs,
            period_start=oos_start,
            period_end=oos_end,
        )
    )
    oos_line_wick_lc_grid["selected_on_train"] = (
        oos_line_wick_lc_grid["config_id"].eq(
            selected_line_wick_lc_config.config_id
        )
    )
    oos_line_wick_lc_grid["baseline_comparison"] = (
        oos_line_wick_lc_grid["config_id"].eq("baseline")
    )
    oos_line_wick_lc_grid["oos_used_for_selection"] = False
    line_primary_rows = oos_line_wick_lc_grid.loc[
        oos_line_wick_lc_grid["config_id"].eq(
            selected_line_wick_lc_config.config_id
        )
    ]
    if len(line_primary_rows) != 1:
        raise ValueError("primary OOS line-wick LC result is ambiguous")
    direct_entry_baseline_rows = oos_line_wick_lc_grid.loc[
        oos_line_wick_lc_grid["config_id"].eq("baseline")
    ]
    if len(direct_entry_baseline_rows) != 1:
        raise ValueError("direct-entry OOS baseline is ambiguous")
    direct_entry_baseline_performance = {
        str(key): value
        for key, value in direct_entry_baseline_rows.iloc[0].items()
        if key
        not in {
            "line_wick_lc_policy_order",
            "config_id",
            "enabled",
            "width_a",
            "trigger_source",
        }
    }
    performance = {
        str(key): value
        for key, value in line_primary_rows.iloc[0].items()
        if key not in {
            "line_wick_lc_policy_order",
            "config_id",
            "enabled",
            "width_a",
            "trigger_source",
        }
    }
    trades = oos_line_wick_lc_trades.loc[
        oos_line_wick_lc_trades["line_wick_lc_config_id"].eq(
            selected_line_wick_lc_config.config_id
        )
    ].copy()
    primary_paths = line_wick_paths.loc[
        line_wick_paths["line_wick_lc_config_id"].eq(
            selected_line_wick_lc_config.config_id
        )
    ].copy()
    fixed_policy_counterfactual = performance_from_frame(
        primary_paths, np.ones(len(primary_paths), dtype=bool)
    )
    monthly = monthly_summary(trades)
    readable = _readable_trade_list(trades)
    line_wick_all_readable = _readable_trade_list(oos_line_wick_lc_trades)
    line_wick_monthly_frames = []
    for config in replay_line_wick_lc_configs:
        config_trades = oos_line_wick_lc_trades.loc[
            oos_line_wick_lc_trades["line_wick_lc_config_id"].eq(
                config.config_id
            )
        ]
        config_monthly = monthly_summary(config_trades)
        config_monthly.insert(0, "config_id", config.config_id)
        line_wick_monthly_frames.append(config_monthly)
    line_wick_monthly = pd.concat(
        line_wick_monthly_frames, ignore_index=True
    )
    stretch_comparison = pd.DataFrame(
        (
            {"policy": "current_1B_take_profit", **performance},
            {
                "policy": "target_2B_trigger_1p2B_lock_1B",
                **stretch_performance,
            },
        )
    )
    watch_entry_comparison = pd.DataFrame(
        (
            {
                "policy": "current_first_touch_reversal",
                **direct_entry_baseline_performance,
            },
            {
                "policy": "three_branch_watch_entry",
                **watch_entry_performance,
            },
        )
    )
    atomic_csv(paths["oos_trades"], trades)
    atomic_csv(paths["oos_replay_list"], readable)
    atomic_csv(paths["oos_monthly"], monthly)
    atomic_csv(paths["oos_watch_entry_paths"], watch_entry_paths)
    atomic_csv(paths["oos_watch_entry_trades"], watch_entry_trades)
    atomic_csv(
        paths["oos_watch_entry_replay_list"], watch_entry_readable
    )
    atomic_csv(paths["oos_watch_entry_monthly"], watch_entry_monthly)
    atomic_csv(paths["oos_watch_entry_branches"], watch_entry_branches)
    atomic_csv(paths["oos_watch_entry_comparison"], watch_entry_comparison)
    atomic_csv(
        paths["oos_line_holding_early_path"],
        line_holding_early_path_oos,
    )
    atomic_csv(paths["oos_stretch_profit_lock_trades"], stretch_trades)
    atomic_csv(
        paths["oos_stretch_profit_lock_replay_list"], stretch_readable
    )
    atomic_csv(
        paths["oos_stretch_profit_lock_monthly"], stretch_monthly
    )
    atomic_csv(
        paths["oos_stretch_profit_lock_comparison"], stretch_comparison
    )
    atomic_csv(paths["oos_timed_half_lc_grid"], oos_timed_half_lc_grid)
    atomic_csv(
        paths["oos_timed_half_lc_trades"], oos_timed_half_lc_trades
    )
    atomic_csv(paths["oos_timed_half_lc_replay_list"], timed_all_readable)
    atomic_csv(paths["oos_timed_half_lc_monthly"], policy_monthly)
    atomic_csv(paths["oos_line_wick_lc_grid"], oos_line_wick_lc_grid)
    atomic_csv(paths["oos_line_wick_lc_trades"], oos_line_wick_lc_trades)
    atomic_csv(
        paths["oos_line_wick_lc_replay_list"], line_wick_all_readable
    )
    atomic_csv(paths["oos_line_wick_lc_monthly"], line_wick_monthly)
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
        "top15_or_candidate_rows": len(policy_candidates),
        "selected_path_config": artifact["selected_path_config"],
        "condition_ranking_trade_combo": artifact[
            "condition_ranking_trade_combo"
        ],
        "top_condition_limit": expected_top_count,
        "selected_top_conditions": artifact["selected_top_conditions"],
        "tier_execution_configs": artifact["tier_execution_configs"],
        "watch_entry_policy": watch_policy,
        "watch_entry_performance": watch_entry_performance,
        "watch_entry_branches": watch_entry_branches.to_dict(
            orient="records"
        ),
        "watch_entry_monthly": watch_entry_monthly.to_dict(
            orient="records"
        ),
        "line_holding_early_path": {
            "row_count": len(line_holding_early_path_oos),
            "evaluable_row_count": int(
                line_holding_early_path_oos[
                    "checkpoint_evaluable"
                ].fillna(False).astype(bool).sum()
                if not line_holding_early_path_oos.empty
                else 0
            ),
            "evaluable_count_by_minute": {
                str(minute): int(
                    line_holding_early_path_oos.loc[
                        line_holding_early_path_oos[
                            "elapsed_minute"
                        ].eq(minute),
                        "checkpoint_evaluable",
                    ].fillna(False).astype(bool).sum()
                )
                for minute in EARLY_PATH_MINUTES
            },
            "trade_count": int(
                line_holding_early_path_oos["event_id"].nunique()
                if not line_holding_early_path_oos.empty
                else 0
            ),
            "loaded_design_from_training_artifact": True,
            "reselected_on_oos": False,
        },
        "stretch_profit_lock": stretch_policy,
        "stretch_profit_lock_performance": stretch_performance,
        "stretch_profit_lock_monthly": stretch_monthly.to_dict(
            orient="records"
        ),
        "range_lc_search": range_lc_search,
        "timed_half_lc_search": timed_half_lc_search,
        "timed_half_lc_config": primary_timed_half_lc_config.to_dict(),
        "timed_half_lc_replay_configs": [
            config.to_dict() for config in replay_timed_half_lc_configs
        ],
        "timed_half_lc_oos_performance": oos_timed_half_lc_grid.to_dict(
            orient="records"
        ),
        "line_wick_lc_search": line_wick_search,
        "line_wick_lc_config": selected_line_wick_lc_config.to_dict(),
        "line_wick_lc_replay_configs": [
            config.to_dict() for config in replay_line_wick_lc_configs
        ],
        "line_wick_lc_oos_performance": oos_line_wick_lc_grid.to_dict(
            orient="records"
        ),
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
            "range_filter_tp_and_lc_not_reselected_on_oos": True,
            "target_distance_filter_loaded_from_training_artifact": True,
            "target_distance_filter_uses_decision_time_only": True,
            "profit_lock_loaded_from_training_artifact": True,
            "profit_lock_disabled": not bool(profit_lock["enabled"]),
            "profit_lock_uses_completed_trigger_s5_only": bool(
                profit_lock["enabled"]
            ),
            "stretch_profit_lock_loaded_from_training_artifact": True,
            "stretch_profit_lock_not_reselected_on_oos": True,
            "stretch_profit_lock_uses_completed_trigger_s5_only": True,
            "watch_entry_loaded_from_training_artifact": True,
            "watch_entry_not_reselected_on_oos": True,
            "watch_entry_observation_uses_completed_s5_only": True,
            "line_holding_early_snapshots_use_completed_s5_only": True,
            "line_holding_early_final_fields_are_labels_only": True,
            "line_holding_early_prices_stop_at_actual_exit": True,
            "line_holding_exit_s5_opposite_extreme_censored": True,
            "timed_half_lc_loaded_from_training_artifact": True,
            "timed_half_lc_not_reselected_on_oos": True,
            "timed_half_lc_configs_replayed_independently": True,
            "oos_metrics_not_used_to_rank_configs": True,
            "timed_half_lc_activation_uses_checkpoint_open_only": True,
            "timed_half_lc_half_tp_is_diagnostic_only": True,
            "line_wick_lc_loaded_from_training_artifact": True,
            "line_wick_lc_not_reselected_on_oos": True,
            "line_wick_lc_configs_replayed_independently": True,
            "line_wick_lc_uses_decision_time_a": True,
            "line_wick_lc_uses_spread_aware_s5_wick": True,
            "line_wick_lc_original_hard_lc_retained": True,
            "direct_first_touch_order_without_breakout": True,
            "three_branch_watch_entry_replayed_for_comparison": True,
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
                    (
                        "- timed half-LC OOS configs: "
                        + ",".join(replay_ids)
                    ),
                    (
                        "- selected line-wick LC result: "
                        f"{selected_line_wick_lc_config.config_id}"
                    ),
                    f"- top-15 OR candidate events: {len(policy_candidates)}",
                    f"- policy order fill rate: {fixed_policy_counterfactual['order_fill_rate']:.2%}",
                    f"- trades: {performance['completed_trade_count']}",
                    f"- wins: {performance['win_count']}",
                    f"- win rate: {performance['win_rate']:.2%}",
                    f"- average win: {performance['average_win_pips']:.2f} pips",
                    f"- profit locks: {performance['profit_lock_count']}",
                    f"- gross profit: {performance['gross_profit_yen']:.0f} yen",
                    f"- gross loss: {performance['gross_loss_yen']:.0f} yen",
                    f"- net profit: {performance['sum_yen']:.0f} yen",
                    f"- total pips: {performance['sum_pips']:.2f}",
                    (
                        "- watch entry: 60s / LineHolding<0.1A / "
                        "NearLine<=1A / Breakout>1A"
                    ),
                    (
                        "- watch trades: "
                        f"{watch_entry_performance['completed_trade_count']}"
                    ),
                    (
                        "- watch win rate: "
                        f"{watch_entry_performance['win_rate']:.2%}"
                    ),
                    (
                        "- watch net profit: "
                        f"{watch_entry_performance['sum_yen']:.0f} yen"
                    ),
                    (
                        "- watch comparison: "
                        f"{paths['oos_watch_entry_comparison']}"
                    ),
                    (
                        "- stretch profit lock: target 2B / trigger 1.2B / "
                        "lock +1B"
                    ),
                    (
                        "- stretch trades: "
                        f"{stretch_performance['completed_trade_count']}"
                    ),
                    (
                        "- stretch win rate: "
                        f"{stretch_performance['win_rate']:.2%}"
                    ),
                    (
                        "- stretch net profit: "
                        f"{stretch_performance['sum_yen']:.0f} yen"
                    ),
                    (
                        "- stretch comparison: "
                        f"{paths['oos_stretch_profit_lock_comparison']}"
                    ),
                    f"- replay list: {paths['oos_replay_list']}",
                    (
                        "- all-config OOS grid: "
                        f"{paths['oos_timed_half_lc_grid']}"
                    ),
                    (
                        "- all-config replay list: "
                        f"{paths['oos_timed_half_lc_replay_list']}"
                    ),
                    (
                        "- line-wick LC OOS grid: "
                        f"{paths['oos_line_wick_lc_grid']}"
                    ),
                    (
                        "- line-wick LC replay list: "
                        f"{paths['oos_line_wick_lc_replay_list']}"
                    ),
                )
            )
        )
    return {
        "summary": summary,
        "paths": paths,
        "trades": trades,
        "watch_entry_trades": watch_entry_trades,
        "watch_entry_performance": watch_entry_performance,
        "watch_entry_branches": watch_entry_branches,
        "line_holding_early_path_oos": line_holding_early_path_oos,
        "stretch_profit_lock_trades": stretch_trades,
        "stretch_profit_lock_performance": stretch_performance,
        "progress_archive": archived_progress,
    }


if __name__ == "__main__":
    raise SystemExit("Run a test_kick_<pair>_flip_predict.py launcher")
