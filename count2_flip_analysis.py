# 最終更新: 2026-08-23 08:22 JST
"""Prior-two-year exhaustive analysis and frozen policy for flip_predict."""

from __future__ import annotations

import datetime as dt
import time
from pathlib import Path
from typing import Any

import pandas as pd

import test_win_point_usd_aud as win_point
import tokens as tk
from count2_flip_core import (
    FLIP_VERSION,
    TOP_CONDITION_LIMIT,
    FlipPathConfig,
    PolicyCondition,
    TradeCombo,
    default_path_configs,
    default_tier_execution_configs,
    default_trade_combos,
    enumerate_conditions,
    serialize_path_config,
    serialize_trade_combo,
)
from count2_flip_workflow import (
    MIN_TRADE_RANGE_FRACTION_A,
    MIN_TRADE_RANGE_FRACTION_PIPS,
    archive_file,
    atomic_csv,
    atomic_json,
    candidate_source_path,
    choose_global_policy,
    file_stat,
    inspect_selected_paths,
    inspect_tiered_paths,
    load_candidates,
    load_path_inspector,
    monthly_summary,
    period_stem,
    progress_path,
    rank_replay_conditions,
    replay_condition,
    s5_source_path,
    scan_global_grid,
    select_top_condition_policy_candidates,
    select_top_ranked_conditions,
    summarize_conditions,
    write_progress,
)


DEFAULT_TRAIN_START = dt.datetime(2023, 7, 30)
DEFAULT_TRAIN_END = dt.datetime(2025, 7, 30)
DEFAULT_OOS_START = dt.datetime(2025, 7, 30)
DEFAULT_OOS_END = dt.datetime(2026, 7, 30)


def analysis_output_paths(
    output_dir: Path,
    pair: str,
    train_start: dt.datetime,
    train_end: dt.datetime,
    oos_start: dt.datetime,
    oos_end: dt.datetime,
) -> dict[str, Path]:
    train = period_stem(pair, train_start, train_end)
    full = f"{train}_to_{oos_start:%Y%m%d}_{oos_end:%Y%m%d}"
    prefix = f"{FLIP_VERSION}_{full}"
    return {
        "global_grid": output_dir / f"{prefix}_global_grid.csv",
        "condition_counterfactual": output_dir
        / f"{prefix}_condition_counterfactual.csv",
        "condition_replay": output_dir / f"{prefix}_condition_train_replay.csv",
        "train_trades": output_dir / f"{prefix}_train_trades.csv",
        "train_monthly": output_dir / f"{prefix}_train_monthly.csv",
        "artifact": output_dir / f"{prefix}_artifact.json",
        "train_summary": output_dir / f"{prefix}_train_summary.json",
        "progress": progress_path(
            output_dir,
            pair,
            train_start,
            train_end,
            oos_start,
            oos_end,
        ),
    }


def _notice(message: str) -> None:
    win_point.send_inspection_notice(message)


def _safe_number(value: Any) -> Any:
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


def _row_payload(row: pd.Series) -> dict[str, Any]:
    return {str(key): _safe_number(value) for key, value in row.items()}


def run_analysis(
    pair: str,
    *,
    train_start: dt.datetime = DEFAULT_TRAIN_START,
    train_end: dt.datetime = DEFAULT_TRAIN_END,
    oos_start: dt.datetime = DEFAULT_OOS_START,
    oos_end: dt.datetime = DEFAULT_OOS_END,
    output_dir: Path | None = None,
    source_candidates: Path | None = None,
    s5_cache: Path | None = None,
    max_rows: int | None = None,
    notify: bool = True,
    minimum_global_trades: int = 100,
    minimum_condition_candidates: int = 100,
    spread_pips: float = 0.8,
    position_horizon_minutes: int = 60,
    min_width_pips: float = 1.6,
    risk_yen: float = 50.0,
) -> dict[str, Any]:
    pair = pair.upper()
    if max_rows is not None:
        raise ValueError(
            "partial row caps cannot write a formal full-period flip_predict artifact"
        )
    if train_end != oos_start:
        raise ValueError("train_end must equal oos_start")
    output_dir = Path(output_dir or tk.folder_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = analysis_output_paths(
        output_dir, pair, train_start, train_end, oos_start, oos_end
    )
    source_candidates = source_candidates or candidate_source_path(
        pair, train_start, train_end, output_dir
    )
    s5_cache = s5_cache or s5_source_path(pair, train_start, train_end, output_dir)
    for key, path in paths.items():
        if key != "progress":
            archive_file(path)
    archive_file(paths["progress"])
    started = time.monotonic()
    notifier = _notice if notify else None
    write_progress(
        paths["progress"],
        pair=pair,
        status="running",
        phase="loading_train",
        started=started,
    )
    if notifier:
        notifier(
            "\n".join(
                (
                    f"{pair} flip_predict inspection start",
                    f"- analysis: {train_start:%Y-%m-%d} <= time < {train_end:%Y-%m-%d}",
                    f"- fixed replay: {oos_start:%Y-%m-%d} <= time < {oos_end:%Y-%m-%d}",
                    "- lifecycle: foot count 2 registration -> first spread-aware line touch LIMIT",
                    "- direction: order = -foot count 2 direction; no breakout confirmation",
                    "- line condition: newest constituent peak direction = order direction",
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
        start=train_start,
        end=train_end,
        max_rows=max_rows,
    )
    path_inspector, s5_metadata = load_path_inspector(
        s5_cache,
        pair_name=pair,
        start=train_start,
        end=train_end,
        spread_pips=spread_pips,
        position_horizon_minutes=position_horizon_minutes,
        min_width_pips=min_width_pips,
        risk_yen=risk_yen,
    )
    path_configs = default_path_configs()
    trade_combos = default_trade_combos()
    global_grid = scan_global_grid(
        candidates,
        path_inspector,
        path_configs,
        trade_combos,
        pair=pair,
        phase="train_global_grid",
        period_start=train_start,
        progress_file=paths["progress"],
        started=started,
        notify=notifier,
    )
    global_grid.sort_values(
        ["sum_yen", "positive_month_rate", "profit_factor_yen"],
        ascending=[False, False, False],
        inplace=True,
        kind="stable",
    )
    atomic_csv(paths["global_grid"], global_grid)
    selected_global = choose_global_policy(
        global_grid, minimum_trades=minimum_global_trades
    )
    path_config = FlipPathConfig(
        order_wait_minutes=int(selected_global["order_wait_minutes"]),
    )
    trade_combo = TradeCombo(
        tp_a=float(selected_global["tp_a"]),
        lc_a=float(selected_global["lc_a"]),
    )
    selected_paths = inspect_selected_paths(
        candidates,
        path_inspector,
        path_config,
        trade_combo,
        pair=pair,
        phase="train_selected_paths",
        period_start=train_start,
        progress_file=paths["progress"],
        started=started,
        # The global chronological pass already emits the required two-month
        # notices.  This second deterministic pass must not duplicate them.
        notify=None,
    )
    conditions = enumerate_conditions(
        selected_paths,
        minimum_candidates=minimum_condition_candidates,
    )
    condition_summary = summarize_conditions(selected_paths, conditions)
    condition_summary.sort_values(
        ["sum_yen", "positive_month_rate", "profit_factor_yen"],
        ascending=[False, False, False],
        inplace=True,
        kind="stable",
    )
    atomic_csv(paths["condition_counterfactual"], condition_summary)
    # Every enumerated condition must be tested on the actual one-active-flip
    # lifecycle.  Counterfactual rank is not a safe pre-filter for that replay.
    shortlisted_conditions = conditions
    replay_summary, _ = rank_replay_conditions(
        selected_paths, shortlisted_conditions, keep_details=False
    )
    replay_summary.sort_values(
        [
            "sum_yen",
            "positive_month_rate",
            "profit_factor_yen",
            "sum_pips",
            "condition_id",
        ],
        ascending=[False, False, False, False, True],
        inplace=True,
        kind="stable",
    )
    tier_configs = default_tier_execution_configs()
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
    ranked_conditions = select_top_ranked_conditions(
        replay_summary,
        tier_configs,
        limit=TOP_CONDITION_LIMIT,
    )
    rank_by_condition = {
        item.condition.condition_id: item.rank for item in ranked_conditions
    }
    tier_by_condition = {
        item.condition.condition_id: item.tier for item in ranked_conditions
    }
    replay_summary["policy_rank"] = pd.array(
        replay_summary["condition_id"].map(rank_by_condition), dtype="Int64"
    )
    replay_summary["policy_tier"] = replay_summary["condition_id"].map(
        tier_by_condition
    )
    replay_summary["selected_for_top15_or"] = replay_summary[
        "policy_rank"
    ].notna()
    atomic_csv(paths["condition_replay"], replay_summary)
    replay_by_condition = replay_summary.set_index("condition_id", drop=False)
    selected_top_conditions = []
    for item in ranked_conditions:
        condition_id = item.condition.condition_id
        metrics = replay_by_condition.loc[condition_id].drop(
            labels=(
                "condition_id",
                "condition_label",
                "condition_json",
                "policy_rank",
                "policy_tier",
                "selected_for_top15_or",
            ),
            errors="ignore",
        )
        selected_top_conditions.append(
            {
                **item.to_dict(),
                "train_lifecycle_performance": _row_payload(metrics),
            }
        )
    policy_candidates = select_top_condition_policy_candidates(
        candidates,
        ranked_conditions,
        tier_configs,
    )
    policy_paths = inspect_tiered_paths(
        policy_candidates,
        path_inspector,
        path_config,
        tier_configs,
        pair=pair,
        phase="train_top15_or_policy",
        period_start=train_start,
        progress_file=paths["progress"],
        started=started,
        # The global chronological pass already emits the required two-month
        # notices.  This deterministic policy pass must not duplicate them.
        notify=None,
    )
    train_trades, train_performance = replay_condition(
        policy_paths,
        PolicyCondition("ALL", "Top-15 OR policy"),
    )
    atomic_csv(paths["train_trades"], train_trades)
    train_monthly = monthly_summary(train_trades)
    atomic_csv(paths["train_monthly"], train_monthly)
    elapsed_minutes = (time.monotonic() - started) / 60.0
    artifact = {
        "version": FLIP_VERSION,
        "status": "complete",
        "pair": pair,
        "created_at": dt.datetime.now().astimezone().isoformat(
            timespec="seconds"
        ),
        "analysis_period": {
            "start_inclusive": train_start,
            "end_exclusive": train_end,
        },
        "fixed_replay_period": {
            "start_inclusive": oos_start,
            "end_exclusive": oos_end,
        },
        "source_candidates": file_stat(source_candidates),
        "s5_cache": file_stat(s5_cache),
        "s5_typed_cache": s5_metadata,
        "candidate_rows": len(candidates),
        "path_grid_count": len(path_configs),
        "trade_grid_count": len(trade_combos),
        "condition_count": len(conditions),
        "minimum_condition_candidates": minimum_condition_candidates,
        "trade_eligibility": {
            "range_source": "recent_m5_avg_range_pips",
            "fraction_a": MIN_TRADE_RANGE_FRACTION_A,
            "minimum_fraction_pips": MIN_TRADE_RANGE_FRACTION_PIPS,
            "equivalent_minimum_a_pips": (
                MIN_TRADE_RANGE_FRACTION_PIPS
                / MIN_TRADE_RANGE_FRACTION_A
            ),
            "mandatory_before_condition_ranking": True,
            "causal_at_decision_time": True,
        },
        "feature_definitions": {
            "line_latest_constituent_peak_direction": {
                "source_column": "line_source_directions",
                "source_logic": "sign of newest-first dirs_grouped[0]",
                "mandatory_for_order": True,
                "required_relation": "value == trade_direction == -peak_direction",
                "origin_or_current_role_filter": False,
            },
            "f_flip_flag": {
                "source_column": "line_is_flipped",
                "source_logic": (
                    "existing LineStrengthCal.line_each_analysis/is_flipped_line "
                    "(unchanged)"
                ),
                "source_criteria": (
                    "line_count>=3; first two dirs_grouped have opposite signs; "
                    "latest peak_strength>2; abs(second dirs_grouped)>=2"
                ),
                "distinct_from": [
                    "line_history_is_flipped",
                    "line_flip_count",
                ],
                "values": ["yes", "no"],
                "mandatory_for_order": False,
            },
            "fc2_detailed_shape": {
                "shared_module": "fFootCountShape.py",
                "source_columns": [
                    "fc2_candle_sequence",
                    "fc2_relative_candle_sequence",
                    "fc2_second_wick_A",
                    "fc2_second_close_pushback_A",
                    "fc2_second_body_to_first_ratio",
                ],
                "source_logic": "completed M5 candles at decision_time only",
                "search_features": [
                    "f_fc2_relative_candle_sequence",
                    "f_fc2_second_wick_a",
                    "f_fc2_second_pushback_a",
                    "f_fc2_second_body_ratio",
                ],
                "bucket_semantics": "left-closed, right-open; missing is explicit",
                "direction_symmetry": (
                    "BULL/BEAR is stored for audit; automatic search uses "
                    "WITH/AGAINST relative to peak_direction"
                ),
                "mandatory_for_order": False,
            },
        },
        "selected_path_config": serialize_path_config(path_config),
        "condition_ranking_trade_combo": serialize_trade_combo(trade_combo),
        "top_condition_limit": TOP_CONDITION_LIMIT,
        "selected_top_conditions": selected_top_conditions,
        "tier_execution_configs": [
            config.to_dict() for config in tier_configs
        ],
        "top_condition_policy": {
            "operator": "OR",
            "all_baseline_excluded": True,
            "additional_top15_eligibility_filters": False,
            "ranking_order": [
                "sum_yen_desc",
                "positive_month_rate_desc",
                "profit_factor_yen_desc",
                "sum_pips_desc",
                "condition_id_asc",
            ],
            "tier_ranges": {
                config.tier: [config.first_rank, config.last_rank]
                for config in tier_configs
            },
            "same_event_line_selection": (
                "highest_signal_tier_then_nearest_line"
            ),
            "one_order_per_event": True,
        },
        "global_lifecycle_performance": _row_payload(selected_global),
        "train_portfolio_replay_performance": train_performance,
        "execution": {
            "spread_pips": spread_pips,
            "position_horizon_minutes": position_horizon_minutes,
            "min_width_pips": min_width_pips,
            "risk_yen": risk_yen,
            "one_active_flip_lifecycle_per_pair": True,
            "unfilled_candidate_replaced_by_next_foot_count2": True,
            "order_uses_first_spread_aware_s5_limit_touch": True,
            "order_direction_is_negative_peak_direction": True,
            "latest_line_peak_direction_must_equal_order_direction": True,
            "breakout_confirmation_used": False,
            "same_s5_tp_lc_is_loss": True,
            "position_outcome_requires_contiguous_s5_to_exit": True,
            "open_positions_at_period_end_are_censored": True,
            "tier_tp_rr_applied_after_top15_freeze": True,
            "minimum_width_floor_scales_tp_and_lc_together": True,
            "configured_rr_preserved_before_price_increment_rounding": True,
            "effective_rr_exported_after_price_increment_rounding": True,
        },
        "future_safety": {
            "decision_features_from_causal_candidate_ledger": True,
            "candidate_source_times_checked_not_after_decision": True,
            "fill_and_trade_fields_are_labels_only": True,
            "fixed_replay_not_used_for_selection": True,
            "top15_conditions_frozen_before_fixed_replay": True,
            "tier_settings_frozen_before_fixed_replay": True,
            "known_market_closures_accepted": True,
            "christmas_new_year_weekend_joins_accepted": True,
            "unknown_s5_gaps_rejected": True,
        },
        "outputs": {key: str(path.resolve()) for key, path in paths.items()},
        "elapsed_minutes": elapsed_minutes,
    }
    atomic_json(paths["artifact"], artifact)
    atomic_json(
        paths["train_summary"],
        {
            "pair": pair,
            "period": artifact["analysis_period"],
            "selected_top_conditions": selected_top_conditions,
            "tier_execution_configs": artifact["tier_execution_configs"],
            "performance": train_performance,
            "monthly": train_monthly.to_dict(orient="records"),
        },
    )
    write_progress(
        paths["progress"],
        pair=pair,
        status="running",
        phase="analysis_complete_waiting_fixed_replay",
        current_row=len(candidates),
        total_rows=len(candidates),
        current_time=train_end,
        started=started,
    )
    if notifier:
        notifier(
            "\n".join(
                (
                    f"{pair} flip_predict analysis complete",
                    f"- candidate lines: {len(candidates)}",
                    f"- selected order wait: {path_config.config_id}",
                    f"- order triggers: top {TOP_CONDITION_LIMIT} conditions (OR)",
                    f"- tiers: {tier_ranges_text}",
                    f"- tier settings: {tier_settings_text}",
                    f"- train trades: {train_performance['completed_trade_count']}",
                    f"- train win rate: {train_performance['win_rate']:.2%}",
                    f"- train average win: {train_performance['average_win_pips']:.2f} pips",
                    f"- train net: {train_performance['sum_yen']:.0f} yen",
                )
            )
        )
    return {
        "artifact": artifact,
        "artifact_path": paths["artifact"],
        "paths": paths,
        "train_trades": train_trades,
        "train_performance": train_performance,
    }


if __name__ == "__main__":
    raise SystemExit("Run a test_kick_<pair>_flip_predict.py launcher")
