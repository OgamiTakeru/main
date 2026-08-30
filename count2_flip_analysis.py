# 最新更新日時: 2026-08-25 14:59 JST
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
    CONDITION_MINIMUM_POSITIVE_PERIODS,
    CONDITION_MULTIPLE_TESTING_ALPHA,
    DEFAULT_LC_A_GRID,
    DEFAULT_MIN_TARGET_DISTANCE_PIPS,
    DEFAULT_PROFIT_LOCK_ENABLED,
    DEFAULT_PROFIT_LOCK_MIN_TP_PIPS,
    DEFAULT_PROFIT_LOCK_RESULT_PIPS,
    DEFAULT_PROFIT_LOCK_TRIGGER_TP_FRACTION,
    DEFAULT_RANGE_FILTER_PIPS_GRID,
    DEFAULT_TP_A_GRID,
    EARLY_PATH_METRICS,
    EARLY_PATH_MINUTES,
    FLIP_VERSION,
    MINIMUM_CONDITION_TRADES,
    RANGE_FILTER_FRACTION_A,
    STRETCH_PROFIT_LOCK_B,
    STRETCH_PROFIT_LOCK_TP_FRACTION,
    STRETCH_PROFIT_TARGET_B,
    STRETCH_PROFIT_TRIGGER_B,
    STRETCH_PROFIT_TRIGGER_TP_FRACTION,
    TOP_CONDITION_LIMIT,
    FlipPathConfig,
    FlipWatchEntryConfig,
    LineWickLcConfig,
    PolicyCondition,
    TradeCombo,
    default_timed_half_lc_configs,
    default_line_wick_lc_configs,
    default_path_configs,
    default_tier_execution_configs,
    default_trade_combos,
    bucket_specs_for_pair,
    enumerate_conditions,
    excluded_feature_fields_for_pair,
    minimum_matched_conditions_for_pair,
    minimum_tier_rr_for_pair,
    risk_multiple_profit_lock_for_pair,
    serialize_path_config,
    serialize_trade_combo,
)
from count2_flip_workflow import (
    archive_file,
    atomic_csv,
    atomic_json,
    attach_bonferroni_diagnostics,
    candidate_source_path,
    choose_global_policy,
    choose_line_wick_lc_policy,
    choose_tier_execution_configs,
    file_stat,
    four_period_metrics,
    inspect_selected_paths,
    inspect_tiered_paths,
    inspect_line_wick_lc_grid_paths,
    risk_multiple_profit_lock_inspectors,
    inspect_trade_combo_grid_paths,
    inspect_timed_half_lc_grid_paths,
    load_candidates,
    load_path_inspector,
    line_holding_early_path_dataset,
    monthly_summary,
    period_stem,
    progress_path,
    rank_replay_conditions,
    range_filter_mask,
    replay_condition,
    s5_source_path,
    scan_global_grid,
    scan_line_wick_lc_grid,
    scan_portfolio_tp_lc_grid,
    scan_tier_filter_lc_grid,
    scan_timed_half_lc_grid,
    select_timed_half_lc_policies,
    timed_half_lc_strict_mask,
    select_top_condition_policy_candidates,
    select_top_ranked_conditions,
    summarize_conditions,
    target_distance_filter_mask,
    stretch_profit_lock_inspector,
    stretch_profit_lock_tier_configs,
    summarize_watch_entry_branches,
    write_progress,
)


DEFAULT_TRAIN_START = dt.datetime(2023, 7, 30)
DEFAULT_TRAIN_END = dt.datetime(2025, 7, 30)
DEFAULT_OOS_START = dt.datetime(2025, 7, 30)
DEFAULT_OOS_END = dt.datetime(2026, 7, 30)
TIMED_HALF_LC_MINIMUM_TRADES = 30
TIMED_HALF_LC_MINIMUM_ACTIVATIONS = 30
TIMED_HALF_LC_SELECTION_LIMIT = 5
TIMED_HALF_LC_MAXIMUM_TRIGGER_JACCARD = 0.85
LINE_WICK_LC_MINIMUM_TRADES = 30
LINE_WICK_LC_MINIMUM_EXITS = 30


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
        "tier_range_lc_grid": output_dir
        / f"{prefix}_tier_range_lc_grid.csv",
        "tp_lc_pips_matrix": output_dir
        / f"{prefix}_tp_lc_pips_matrix.csv",
        "tp_lc_a_matrix": output_dir / f"{prefix}_tp_lc_a_matrix.csv",
        "timed_half_lc_grid": output_dir
        / f"{prefix}_timed_half_lc_grid.csv",
        "timed_half_lc_paths": output_dir
        / f"{prefix}_timed_half_lc_paths.csv",
        "timed_half_lc_train_trades": output_dir
        / f"{prefix}_timed_half_lc_train_trades.csv",
        "line_wick_lc_grid": output_dir
        / f"{prefix}_line_wick_lc_grid.csv",
        "line_wick_lc_paths": output_dir
        / f"{prefix}_line_wick_lc_paths.csv",
        "line_wick_lc_train_trades": output_dir
        / f"{prefix}_line_wick_lc_train_trades.csv",
        "condition_counterfactual": output_dir
        / f"{prefix}_condition_counterfactual.csv",
        "condition_replay": output_dir / f"{prefix}_condition_train_replay.csv",
        "train_trades": output_dir / f"{prefix}_train_trades.csv",
        "train_monthly": output_dir / f"{prefix}_train_monthly.csv",
        "watch_entry_train_trades": output_dir
        / f"{prefix}_watch_entry_train_trades.csv",
        "watch_entry_train_paths": output_dir
        / f"{prefix}_watch_entry_train_paths.csv",
        "watch_entry_train_monthly": output_dir
        / f"{prefix}_watch_entry_train_monthly.csv",
        "watch_entry_train_branches": output_dir
        / f"{prefix}_watch_entry_train_branches.csv",
        "watch_entry_train_comparison": output_dir
        / f"{prefix}_watch_entry_train_comparison.csv",
        "line_holding_early_path_train": output_dir
        / f"{prefix}_line_holding_early_path_train.csv",
        "stretch_profit_lock_train_trades": output_dir
        / f"{prefix}_stretch_profit_lock_train_trades.csv",
        "stretch_profit_lock_train_monthly": output_dir
        / f"{prefix}_stretch_profit_lock_train_monthly.csv",
        "stretch_profit_lock_train_comparison": output_dir
        / f"{prefix}_stretch_profit_lock_train_comparison.csv",
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


def _tp_lc_matrix(summary: pd.DataFrame, value: str) -> pd.DataFrame:
    """Format TP vertically and LC horizontally; RR<1 cells remain blank."""
    matrix = summary.pivot(index="tp_a", columns="lc_a", values=value)
    matrix = matrix.reindex(
        index=list(DEFAULT_TP_A_GRID), columns=list(DEFAULT_LC_A_GRID)
    )
    matrix.index.name = "take_profit_A"
    matrix.columns = [
        f"loss_cut_{float(lc_a):g}A" for lc_a in matrix.columns
    ]
    return matrix.reset_index()


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
    min_target_distance_pips: float = DEFAULT_MIN_TARGET_DISTANCE_PIPS,
    profit_lock_enabled: bool = DEFAULT_PROFIT_LOCK_ENABLED,
    profit_lock_min_tp_pips: float = DEFAULT_PROFIT_LOCK_MIN_TP_PIPS,
    profit_lock_trigger_tp_fraction: float = (
        DEFAULT_PROFIT_LOCK_TRIGGER_TP_FRACTION
    ),
    profit_lock_result_pips: float = DEFAULT_PROFIT_LOCK_RESULT_PIPS,
) -> dict[str, Any]:
    pair = pair.upper()
    if profit_lock_enabled:
        raise ValueError(
            f"legacy fixed-pips profit lock is disabled for {FLIP_VERSION}"
        )
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
    minimum_matched_conditions = minimum_matched_conditions_for_pair(pair)
    minimum_tier_rr = minimum_tier_rr_for_pair(pair)
    risk_multiple_profit_lock = risk_multiple_profit_lock_for_pair(pair)
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
                        "- decision-time target-line distance filter: "
                        f">= {min_target_distance_pips:g}p"
                    ),
                    (
                        f"- train-only range grid: {RANGE_FILTER_FRACTION_A:g}A >= "
                        + ",".join(
                            f"{value:g}p"
                            for value in DEFAULT_RANGE_FILTER_PIPS_GRID
                        )
                    ),
                    (
                        "- train-only TP grid: "
                        + ",".join(
                            f"{value:g}A" for value in DEFAULT_TP_A_GRID
                        )
                    ),
                    (
                        "- train-only LC grid: "
                        + ",".join(f"{value:g}A" for value in DEFAULT_LC_A_GRID)
                        + " (configured RR >= 1 only)"
                    ),
                    "- profit lock: disabled",
                    (
                        "- stretch-profit comparison: 1B=frozen TP / "
                        "target 2B / trigger 1.2B / lock +1B"
                    ),
                    (
                        "- train-only timed half-LC grid: "
                        + ",".join(
                            config.config_id
                            for config in default_timed_half_lc_configs()
                        )
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
    candidates = candidates.loc[
        target_distance_filter_mask(candidates, min_target_distance_pips)
    ].copy()
    if candidates.empty:
        raise ValueError("target-distance filter removed every train candidate")
    path_inspector, s5_metadata = load_path_inspector(
        s5_cache,
        pair_name=pair,
        start=train_start,
        end=train_end,
        spread_pips=spread_pips,
        position_horizon_minutes=position_horizon_minutes,
        min_width_pips=min_width_pips,
        risk_yen=risk_yen,
        profit_lock_enabled=profit_lock_enabled,
        profit_lock_min_tp_pips=profit_lock_min_tp_pips,
        profit_lock_trigger_tp_fraction=profit_lock_trigger_tp_fraction,
        profit_lock_result_pips=profit_lock_result_pips,
    )
    path_configs = default_path_configs()
    trade_combos = default_trade_combos()
    global_grid = scan_global_grid(
        candidates,
        path_inspector,
        path_configs,
        trade_combos,
        DEFAULT_RANGE_FILTER_PIPS_GRID,
        pair=pair,
        phase="train_global_grid",
        period_start=train_start,
        period_end=train_end,
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
    selected_global = choose_global_policy(
        global_grid, minimum_trades=minimum_global_trades
    )
    global_grid["selected_for_condition_ranking"] = (
        global_grid["path_config_id"].eq(selected_global["path_config_id"])
        & global_grid["combo_id"].eq(selected_global["combo_id"])
        & global_grid["min_range_filter_pips"].eq(
            selected_global["min_range_filter_pips"]
        )
    )
    global_grid["selection_stage"] = ""
    global_grid.loc[
        global_grid["selected_for_condition_ranking"], "selection_stage"
    ] = selected_global["selection_stage"]
    atomic_csv(paths["global_grid"], global_grid)
    path_config = FlipPathConfig(
        order_wait_minutes=int(selected_global["order_wait_minutes"]),
        replace_unfilled_on_next_count2=bool(
            selected_global["replace_unfilled_on_next_count2"]
        ),
    )
    trade_combo = TradeCombo(
        tp_a=float(selected_global["tp_a"]),
        lc_a=float(selected_global["lc_a"]),
    )
    ranking_range_filter_pips = float(
        selected_global["min_range_filter_pips"]
    )
    ranking_candidates = candidates.loc[
        range_filter_mask(candidates, ranking_range_filter_pips)
    ].copy()
    if ranking_candidates.empty:
        raise ValueError("selected ranking range filter removed every candidate")
    selected_paths = inspect_selected_paths(
        ranking_candidates,
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
    excluded_fields = excluded_feature_fields_for_pair(pair)
    conditions = enumerate_conditions(
        selected_paths,
        minimum_candidates=minimum_condition_candidates,
        excluded_fields=excluded_fields,
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
        selected_paths,
        shortlisted_conditions,
        keep_details=False,
        period_start=train_start,
        period_end=train_end,
    )
    replay_summary = attach_bonferroni_diagnostics(
        replay_summary, len(shortlisted_conditions)
    )
    replay_summary.sort_values(
        [
            "avg_yen_per_trade",
            "positive_month_rate",
            "profit_factor_yen",
            "sum_pips",
            "condition_id",
        ],
        ascending=[False, False, False, False, True],
        inplace=True,
        kind="stable",
    )
    base_tier_configs = default_tier_execution_configs()
    tier_ranges_text = ", ".join(
        f"{config.tier}={config.first_rank}-{config.last_rank}"
        for config in base_tier_configs
    )
    ranked_conditions = select_top_ranked_conditions(
        replay_summary,
        base_tier_configs,
        limit=TOP_CONDITION_LIMIT,
        minimum_trades=MINIMUM_CONDITION_TRADES,
        minimum_positive_periods=CONDITION_MINIMUM_POSITIVE_PERIODS,
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
    grid_policy_candidates = select_top_condition_policy_candidates(
        candidates,
        ranked_conditions,
        base_tier_configs,
        minimum_matched_conditions=minimum_matched_conditions,
    )
    grid_policy_paths = inspect_trade_combo_grid_paths(
        grid_policy_candidates,
        path_inspector,
        path_config,
        trade_combos,
        pair=pair,
        phase="train_tier_range_lc_grid_paths",
        period_start=train_start,
        progress_file=paths["progress"],
        started=started,
        notify=None,
    )
    tier_range_lc_grid = scan_tier_filter_lc_grid(
        grid_policy_paths,
        base_tier_configs,
        trade_combos,
        DEFAULT_RANGE_FILTER_PIPS_GRID,
        period_start=train_start,
        period_end=train_end,
    )
    tier_range_lc_grid.sort_values(
        ["tier", "sum_yen", "positive_period_count", "profit_factor_yen"],
        ascending=[True, False, False, False],
        inplace=True,
        kind="stable",
    )
    tier_configs, selected_tier_grid = choose_tier_execution_configs(
        tier_range_lc_grid,
        base_tier_configs,
        minimum_trades=30,
        minimum_rr=minimum_tier_rr,
    )
    # Tier RRs are only known now, so the R-based raised stop is built here
    # and reused by every downstream pass that runs the frozen tier policy.
    tier_profit_lock_inspectors = (
        risk_multiple_profit_lock_inspectors(
            path_inspector, tier_configs, risk_multiple_profit_lock
        )
        if risk_multiple_profit_lock is not None
        else None
    )
    selected_keys = {
        (
            str(row.tier),
            str(row.combo_id),
            float(row.min_range_filter_pips),
        )
        for row in selected_tier_grid.itertuples(index=False)
    }
    tier_range_lc_grid["selected_for_frozen_tier"] = [
        (
            str(row.tier),
            str(row.combo_id),
            float(row.min_range_filter_pips),
        )
        in selected_keys
        for row in tier_range_lc_grid.itertuples(index=False)
    ]
    atomic_csv(paths["tier_range_lc_grid"], tier_range_lc_grid)
    matrix_policy_candidates = select_top_condition_policy_candidates(
        candidates,
        ranked_conditions,
        tier_configs,
        minimum_matched_conditions=minimum_matched_conditions,
    )
    matrix_grid_paths = inspect_trade_combo_grid_paths(
        matrix_policy_candidates,
        path_inspector,
        path_config,
        trade_combos,
        pair=pair,
        phase="train_portfolio_tp_lc_matrix_paths",
        period_start=train_start,
        progress_file=paths["progress"],
        started=started,
        notify=None,
    )
    portfolio_tp_lc_grid = scan_portfolio_tp_lc_grid(
        matrix_grid_paths,
        tier_configs,
        trade_combos,
    )
    tp_lc_pips_matrix = _tp_lc_matrix(
        portfolio_tp_lc_grid, "sum_pips"
    )
    tp_lc_a_matrix = _tp_lc_matrix(portfolio_tp_lc_grid, "sum_a")
    atomic_csv(paths["tp_lc_pips_matrix"], tp_lc_pips_matrix)
    atomic_csv(paths["tp_lc_a_matrix"], tp_lc_a_matrix)
    tier_settings_text = ", ".join(
        (
            f"{config.tier}=filter{config.min_range_filter_pips:g}p/"
            f"TP{config.tp_a:g}A/RR{config.rr:g}/"
            f"LC{config.trade_combo.lc_a:g}A"
        )
        for config in tier_configs
    )
    policy_candidates = select_top_condition_policy_candidates(
        candidates,
        ranked_conditions,
        tier_configs,
        minimum_matched_conditions=minimum_matched_conditions,
    )
    line_wick_lc_configs = default_line_wick_lc_configs()
    line_wick_lc_paths = inspect_line_wick_lc_grid_paths(
        policy_candidates,
        path_inspector,
        path_config,
        tier_configs,
        line_wick_lc_configs,
        pair=pair,
        phase="train_line_wick_lc_grid",
        period_start=train_start,
        progress_file=paths["progress"],
        started=started,
        notify=None,
        inspectors_by_tier=tier_profit_lock_inspectors,
    )
    atomic_csv(paths["line_wick_lc_paths"], line_wick_lc_paths)
    line_wick_lc_grid, line_wick_lc_train_trades = scan_line_wick_lc_grid(
        line_wick_lc_paths,
        line_wick_lc_configs,
        period_start=train_start,
        period_end=train_end,
    )
    selected_line_wick_lc_row = choose_line_wick_lc_policy(
        line_wick_lc_grid,
        minimum_trades=LINE_WICK_LC_MINIMUM_TRADES,
        minimum_exits=LINE_WICK_LC_MINIMUM_EXITS,
    )
    selected_line_wick_lc_config = LineWickLcConfig.from_dict(
        selected_line_wick_lc_row.to_dict()
    )
    baseline_line_wick_lc_config = next(
        config for config in line_wick_lc_configs if not config.enabled
    )
    replay_line_wick_lc_configs = (
        (baseline_line_wick_lc_config, selected_line_wick_lc_config)
        if selected_line_wick_lc_config.enabled
        else (baseline_line_wick_lc_config,)
    )
    line_wick_lc_grid["selected_for_primary_execution"] = (
        line_wick_lc_grid["config_id"].eq(
            selected_line_wick_lc_config.config_id
        )
    )
    line_wick_lc_grid["included_in_frozen_oos_replay"] = (
        line_wick_lc_grid["config_id"].isin(
            [config.config_id for config in replay_line_wick_lc_configs]
        )
    )
    line_wick_lc_grid["selection_stage"] = ""
    line_wick_lc_grid.loc[
        line_wick_lc_grid["selected_for_primary_execution"],
        "selection_stage",
    ] = str(selected_line_wick_lc_row["selection_stage"])
    atomic_csv(paths["line_wick_lc_grid"], line_wick_lc_grid)
    atomic_csv(
        paths["line_wick_lc_train_trades"], line_wick_lc_train_trades
    )
    timed_half_lc_configs = default_timed_half_lc_configs()
    timed_half_lc_paths = inspect_timed_half_lc_grid_paths(
        policy_candidates,
        path_inspector,
        path_config,
        tier_configs,
        timed_half_lc_configs,
        pair=pair,
        phase="train_timed_half_lc_grid",
        period_start=train_start,
        progress_file=paths["progress"],
        started=started,
        # The global chronological pass already emits the required two-month
        # notices.  This deterministic policy pass must not duplicate them.
        notify=None,
    )
    atomic_csv(paths["timed_half_lc_paths"], timed_half_lc_paths)
    timed_half_lc_grid, timed_half_lc_train_trades = scan_timed_half_lc_grid(
        timed_half_lc_paths,
        timed_half_lc_configs,
        period_start=train_start,
        period_end=train_end,
    )
    selected_timed_half_lc_configs, selected_timed_half_lc_rows = (
        select_timed_half_lc_policies(
            timed_half_lc_grid,
            timed_half_lc_train_trades,
            timed_half_lc_configs,
            minimum_trades=TIMED_HALF_LC_MINIMUM_TRADES,
            minimum_activations=TIMED_HALF_LC_MINIMUM_ACTIVATIONS,
            limit=TIMED_HALF_LC_SELECTION_LIMIT,
            maximum_trigger_jaccard=(
                TIMED_HALF_LC_MAXIMUM_TRIGGER_JACCARD
            ),
        )
    )
    baseline_timed_half_lc_config = next(
        config for config in timed_half_lc_configs if not config.enabled
    )
    primary_timed_half_lc_config = (
        selected_timed_half_lc_configs[0]
        if selected_timed_half_lc_configs
        else baseline_timed_half_lc_config
    )
    replay_timed_half_lc_configs = (
        baseline_timed_half_lc_config,
        *selected_timed_half_lc_configs,
    )
    timed_selection_stage = (
        "strict_stable_distinct_train"
        if selected_timed_half_lc_configs
        else "baseline_no_strict_candidate"
    )
    strict_timed_mask = timed_half_lc_strict_mask(
        timed_half_lc_grid,
        minimum_trades=TIMED_HALF_LC_MINIMUM_TRADES,
        minimum_activations=TIMED_HALF_LC_MINIMUM_ACTIVATIONS,
    )
    selected_rank_by_id = {
        str(row["config_id"]): int(row["selection_rank"])
        for _, row in selected_timed_half_lc_rows.iterrows()
    }
    selected_ids = set(selected_rank_by_id)
    replay_ids = {
        config.config_id for config in replay_timed_half_lc_configs
    }
    timed_half_lc_grid["passes_strict_train_selection"] = strict_timed_mask
    timed_half_lc_grid["selected_good_condition"] = (
        timed_half_lc_grid["config_id"].isin(selected_ids)
    )
    timed_half_lc_grid["selected_rank"] = timed_half_lc_grid["config_id"].map(
        selected_rank_by_id
    )
    timed_half_lc_grid["included_in_frozen_oos_replay"] = (
        timed_half_lc_grid["config_id"].isin(replay_ids)
    )
    # Backward-readable alias: every selected condition plus baseline is
    # replayed independently on OOS; this is not an OR-combined exit policy.
    timed_half_lc_grid["selected_for_frozen_replay"] = timed_half_lc_grid[
        "included_in_frozen_oos_replay"
    ]
    timed_half_lc_grid["selected_selection_stage"] = ""
    timed_half_lc_grid.loc[
        timed_half_lc_grid["selected_good_condition"],
        "selected_selection_stage",
    ] = timed_selection_stage
    timed_half_lc_grid.loc[
        timed_half_lc_grid["config_id"].eq("baseline"),
        "selected_selection_stage",
    ] = "baseline_comparison"
    atomic_csv(paths["timed_half_lc_grid"], timed_half_lc_grid)
    atomic_csv(
        paths["timed_half_lc_train_trades"], timed_half_lc_train_trades
    )
    policy_paths = line_wick_lc_paths.loc[
        line_wick_lc_paths["line_wick_lc_config_id"].eq(
            selected_line_wick_lc_config.config_id
        )
    ].copy()
    train_trades, train_performance = replay_condition(
        policy_paths,
        PolicyCondition("ALL", "Top-15 OR policy"),
    )
    train_performance.update(
        four_period_metrics(train_trades, train_start, train_end)
    )
    direct_entry_baseline_paths = line_wick_lc_paths.loc[
        line_wick_lc_paths["line_wick_lc_config_id"].eq("baseline")
    ].copy()
    direct_entry_baseline_trades, direct_entry_baseline_performance = replay_condition(
        direct_entry_baseline_paths,
        PolicyCondition("ALL", "Top-15 OR direct first-touch baseline"),
    )
    direct_entry_baseline_performance.update(
        four_period_metrics(
            direct_entry_baseline_trades,
            train_start,
            train_end,
        )
    )
    atomic_csv(paths["train_trades"], train_trades)
    train_monthly = monthly_summary(train_trades)
    atomic_csv(paths["train_monthly"], train_monthly)
    watch_entry_config = FlipWatchEntryConfig()
    watch_entry_paths = inspect_tiered_paths(
        policy_candidates,
        path_inspector,
        path_config,
        tier_configs,
        pair=pair,
        phase="train_flip_watch_entry",
        period_start=train_start,
        progress_file=paths["progress"],
        started=started,
        notify=None,
        watch_entry_config=watch_entry_config,
    )
    watch_entry_train_trades, watch_entry_train_performance = replay_condition(
        watch_entry_paths,
        PolicyCondition("ALL", "Top-15 OR three-branch watch entry"),
    )
    watch_entry_train_performance.update(
        four_period_metrics(watch_entry_train_trades, train_start, train_end)
    )
    watch_entry_train_monthly = monthly_summary(watch_entry_train_trades)
    watch_entry_train_branches = summarize_watch_entry_branches(
        watch_entry_paths, watch_entry_train_trades
    )
    line_holding_early_path_train = line_holding_early_path_dataset(
        watch_entry_train_trades,
        phase="analysis_two_years",
    )
    watch_entry_train_comparison = pd.DataFrame(
        (
            {
                "policy": "current_first_touch_reversal",
                **_row_payload(pd.Series(direct_entry_baseline_performance)),
            },
            {
                "policy": "three_branch_watch_entry",
                **_row_payload(pd.Series(watch_entry_train_performance)),
            },
        )
    )
    atomic_csv(
        paths["watch_entry_train_paths"], watch_entry_paths
    )
    atomic_csv(
        paths["watch_entry_train_trades"], watch_entry_train_trades
    )
    atomic_csv(
        paths["watch_entry_train_monthly"], watch_entry_train_monthly
    )
    atomic_csv(
        paths["watch_entry_train_branches"], watch_entry_train_branches
    )
    atomic_csv(
        paths["watch_entry_train_comparison"],
        watch_entry_train_comparison,
    )
    atomic_csv(
        paths["line_holding_early_path_train"],
        line_holding_early_path_train,
    )
    stretch_tier_configs = stretch_profit_lock_tier_configs(tier_configs)
    stretch_paths = inspect_tiered_paths(
        policy_candidates,
        stretch_profit_lock_inspector(path_inspector),
        path_config,
        stretch_tier_configs,
        pair=pair,
        phase="train_stretch_profit_lock",
        period_start=train_start,
        progress_file=paths["progress"],
        started=started,
        # The global chronological pass already sends the two-month notices.
        notify=None,
        line_wick_lc_config=selected_line_wick_lc_config,
    )
    stretch_train_trades, stretch_train_performance = replay_condition(
        stretch_paths,
        PolicyCondition("ALL", "Top-15 OR stretch-profit policy"),
    )
    stretch_train_performance.update(
        four_period_metrics(stretch_train_trades, train_start, train_end)
    )
    stretch_train_monthly = monthly_summary(stretch_train_trades)
    atomic_csv(
        paths["stretch_profit_lock_train_trades"], stretch_train_trades
    )
    atomic_csv(
        paths["stretch_profit_lock_train_monthly"], stretch_train_monthly
    )
    stretch_comparison_rows = []
    for policy_name, performance_row in (
        ("current_1B_take_profit", train_performance),
        ("target_2B_trigger_1p2B_lock_1B", stretch_train_performance),
    ):
        stretch_comparison_rows.append(
            {"policy": policy_name, **_row_payload(pd.Series(performance_row))}
        )
    stretch_train_comparison = pd.DataFrame(stretch_comparison_rows)
    atomic_csv(
        paths["stretch_profit_lock_train_comparison"],
        stretch_train_comparison,
    )
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
        "range_lc_search": {
            "range_source": "recent_m5_avg_range_pips",
            "fraction_a": RANGE_FILTER_FRACTION_A,
            "range_filter_pips_grid": list(DEFAULT_RANGE_FILTER_PIPS_GRID),
            "tp_a_grid": list(DEFAULT_TP_A_GRID),
            "lc_a_grid": list(DEFAULT_LC_A_GRID),
            "minimum_configured_rr": 1.0,
            "tp_lc_matrix": {
                "row_axis": "take_profit_A",
                "column_axis": "loss_cut_A",
                "pips_cell": "portfolio net pips",
                "a_cell": (
                    "sum of trade_result_pips / recent_m5_avg_range_pips"
                ),
                "tier_range_filters": "frozen train-selected values",
                "rr_below_one_cells": "blank",
            },
            "selection_period": "analysis_period_only",
            "selection_requirements": {
                "minimum_completed_trades_global": minimum_global_trades,
                "minimum_completed_trades_per_tier": 30,
                "minimum_profit_factor_yen": 1.1,
                "minimum_positive_four_periods": 3,
                "maximum_single_positive_period_profit_share": 0.60,
                "fallback_stage_is_exported": True,
                "minimum_tier_configured_rr": minimum_tier_rr,
                "minimum_tier_configured_rr_note": (
                    "per-tier TP/LC cells below this reward/risk are dropped "
                    "before selection; ignored when no cell clears it"
                ),
            },
            "selected_ranking_filter_pips": ranking_range_filter_pips,
            "selected_ranking_tp_a": trade_combo.tp_a,
            "selected_ranking_lc_a": trade_combo.lc_a,
            "selected_ranking_configured_rr": trade_combo.configured_rr,
            "selected_ranking_selection_stage": selected_global[
                "selection_stage"
            ],
            "ranking_candidate_rows": len(ranking_candidates),
            "selected_tier_rows": [
                _row_payload(row)
                for _, row in selected_tier_grid.iterrows()
            ],
            "causal_at_decision_time": True,
            "oos_reselection_allowed": False,
        },
        "line_wick_lc_search": {
            "selection_period": "analysis_period_only",
            "oos_reselection_allowed": False,
            "used_for_primary_execution": True,
            "candidate_configs": [
                config.to_dict() for config in line_wick_lc_configs
            ],
            "selected_config": selected_line_wick_lc_config.to_dict(),
            "replay_configs": [
                config.to_dict() for config in replay_line_wick_lc_configs
            ],
            "selected_selection_stage": str(
                selected_line_wick_lc_row["selection_stage"]
            ),
            "selected_train_metrics": _row_payload(
                selected_line_wick_lc_row
            ),
            "selection_requirements": {
                "minimum_completed_trades": LINE_WICK_LC_MINIMUM_TRADES,
                "minimum_line_wick_exits": LINE_WICK_LC_MINIMUM_EXITS,
                "minimum_sum_yen_exclusive": 0,
                "minimum_profit_factor_yen": 1.1,
                "minimum_positive_four_periods": 3,
                "maximum_single_positive_period_profit_share": 0.60,
                "minimum_delta_vs_baseline_sum_yen_exclusive": 0,
                "fallback": "baseline_if_no_strict_candidate",
            },
            "trigger_rule": (
                "spread-aware exit-side S5 wick reaches the line plus the "
                "decision-time A width in the adverse direction"
            ),
            "gap_rule": "exit at spread-aware S5 open when already beyond stop",
            "same_s5_tp_stop_policy": "line_wick_stop_assumed_first",
            "original_hard_lc_retained": True,
        },
        "timed_half_lc_search": {
            "selection_period": "analysis_period_only",
            "oos_reselection_allowed": False,
            "used_for_primary_execution": False,
            "candidate_configs": [
                config.to_dict() for config in timed_half_lc_configs
            ],
            "selected_config": primary_timed_half_lc_config.to_dict(),
            "selected_configs": [
                config.to_dict()
                for config in selected_timed_half_lc_configs
            ],
            "replay_configs": [
                config.to_dict() for config in replay_timed_half_lc_configs
            ],
            "selected_selection_stage": timed_selection_stage,
            "selected_train_metrics": [
                _row_payload(row)
                for _, row in selected_timed_half_lc_rows.iterrows()
            ],
            "selection_requirements": {
                "policy": "strict_train_multiple_distinct",
                "minimum_completed_trades": TIMED_HALF_LC_MINIMUM_TRADES,
                "minimum_activation_count": (
                    TIMED_HALF_LC_MINIMUM_ACTIVATIONS
                ),
                "minimum_sum_yen_exclusive": 0,
                "minimum_profit_factor_yen": 1.1,
                "minimum_positive_four_periods": 3,
                "maximum_single_positive_period_profit_share": 0.60,
                "minimum_delta_vs_baseline_sum_yen_exclusive": 0,
                "maximum_trigger_jaccard": (
                    TIMED_HALF_LC_MAXIMUM_TRIGGER_JACCARD
                ),
                "maximum_selected_conditions": TIMED_HALF_LC_SELECTION_LIMIT,
                "fallback": "baseline_only_if_no_strict_candidate",
                "baseline_always_replayed_for_comparison": True,
                "selected_conditions_replayed_independently": True,
            },
            "trigger_rule": (
                "at the checkpoint, exit only when spread-aware open P/L is "
                "at or below minus lc_fraction times the original LC width"
            ),
            "timer_anchor": (
                "S5 open when fill is marketable at open; otherwise end of "
                "the spread-aware first-touch fill S5"
            ),
            "checkpoint_data": "checkpoint_S5_open_only",
            "diagnostic_label_scope": {
                "ordinary_reached_fields": "while_position_open_only",
                "counterfactual_horizon_fields": (
                    "full 60-minute price path after fill, including after "
                    "the simulated exit; labels only and never selection inputs"
                ),
                "fill_s5_half_tp_ambiguity": (
                    "checkpoint exit is conservatively suppressed because "
                    "pre/post-fill intrabar ordering is unknowable"
                ),
            },
            "half_tp_fraction": (
                primary_timed_half_lc_config.tp_fraction
            ),
            "half_tp_role": "diagnostic recovery label only; not an activation input",
            "lc_fraction_grid": sorted(
                {
                    config.lc_fraction
                    for config in timed_half_lc_configs
                    if config.enabled
                }
            ),
            "activation_execution": (
                "first S5 at or after checkpoint; an opening threshold breach "
                "exits immediately at spread-aware S5 open P/L"
            ),
            "same_s5_tp_stop_policy": "stop_assumed_first",
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
        "watch_entry_policy": {
            "enabled": True,
            "config": watch_entry_config.to_dict(),
            "selection_period": "none_fixed_user_design",
            "oos_reselection_allowed": False,
            "line_touch_source": "spread_aware_first_S5_touch",
            "observation_data": "completed_S5_only",
            "initial_touch_wait_minutes": path_config.order_wait_minutes,
            "post_observation_order_wait_minutes": (
                path_config.order_wait_minutes
            ),
            "pending_entry_max_gap_a": watch_entry_config.max_entry_gap_a,
            "line_holding_quote_recheck": "spread_aware_actual_entry_price",
            "stop_fill_bar_adverse_rule": (
                "use_only_close-confirmed adverse movement"
            ),
            "line_holding_order_name": "FlipPredict_LineHolding",
            "near_line_order_name": "FlipPredict_NearLineConsolidation",
            "breakout_order_name": "FlipPredict_Breakout",
            "line_holding_entry": (
                "next_S5_open_market_in_reversal_direction"
            ),
            "near_line_entry": "line_price_LIMIT_in_breakout_direction",
            "breakout_entry": (
                "observation_extreme_plus_configured_A_STOP_in_"
                "breakout_direction"
            ),
            "analysis_performance": watch_entry_train_performance,
            "analysis_branches": watch_entry_train_branches.to_dict(
                orient="records"
            ),
            "analysis_monthly": watch_entry_train_monthly.to_dict(
                orient="records"
            ),
            "line_holding_early_path": {
                "anchor": "actual_fill_timer_anchor",
                "elapsed_minutes": list(EARLY_PATH_MINUTES),
                "snapshot_metrics": list(EARLY_PATH_METRICS),
                "price_source": "completed_S5_only",
                "snapshot_availability": (
                    "only_while_position_open_at_checkpoint"
                ),
                "interval_mfe_mae_reference": "actual_entry_price",
                "interval_net_reference": "interval_open",
                "final_mfe_window": (
                    "actual_entry_through_causally_observable_exit_boundary"
                ),
                "exit_s5_opposite_extreme": "censored_to_open_and_exit",
                "final_labels_not_policy_inputs": True,
                "analysis_row_count": len(line_holding_early_path_train),
                "analysis_evaluable_row_count": int(
                    line_holding_early_path_train[
                        "checkpoint_evaluable"
                    ].fillna(False).astype(bool).sum()
                    if not line_holding_early_path_train.empty
                    else 0
                ),
                "analysis_evaluable_count_by_minute": {
                    str(minute): int(
                        line_holding_early_path_train.loc[
                            line_holding_early_path_train[
                                "elapsed_minute"
                            ].eq(minute),
                            "checkpoint_evaluable",
                        ].fillna(False).astype(bool).sum()
                    )
                    for minute in EARLY_PATH_MINUTES
                },
                "analysis_trade_count": int(
                    line_holding_early_path_train["event_id"].nunique()
                    if not line_holding_early_path_train.empty
                    else 0
                ),
            },
        },
        "stretch_profit_lock": {
            "enabled": True,
            "base_width_definition": "1B=frozen_tier_take_profit",
            "target_b": STRETCH_PROFIT_TARGET_B,
            "trigger_b": STRETCH_PROFIT_TRIGGER_B,
            "locked_result_b": STRETCH_PROFIT_LOCK_B,
            "trigger_final_tp_fraction": (
                STRETCH_PROFIT_TRIGGER_TP_FRACTION
            ),
            "locked_result_final_tp_fraction": (
                STRETCH_PROFIT_LOCK_TP_FRACTION
            ),
            "hard_lc": "frozen_tier_lc_unchanged",
            "tier_execution_configs": [
                config.to_dict() for config in stretch_tier_configs
            ],
            "line_wick_lc_config": selected_line_wick_lc_config.to_dict(),
            "selection_period": "none_fixed_user_design",
            "oos_reselection_allowed": False,
            "analysis_performance": stretch_train_performance,
            "analysis_monthly": stretch_train_monthly.to_dict(
                orient="records"
            ),
        },
        "top_condition_policy": {
            "operator": "OR",
            "minimum_matched_conditions": minimum_matched_conditions,
            "risk_multiple_profit_lock": (
                risk_multiple_profit_lock.to_dict()
                if risk_multiple_profit_lock is not None
                else None
            ),
            "risk_multiple_profit_lock_tiers": sorted(
                tier_profit_lock_inspectors or ()
            ),
            "risk_multiple_profit_lock_note": (
                "raised stop in multiples of the trade's own risk: once the "
                "trade reaches trigger_r it can no longer finish below "
                "result_r.  Converted per tier into take-profit fractions, "
                "since tiers pick different RR.  null disables it.  A tier "
                "missing from risk_multiple_profit_lock_tiers ran unlocked "
                "because its RR was at or below trigger_r, so the lock could "
                "only have armed after the take-profit already closed it."
            ),
            "minimum_matched_conditions_note": (
                "how many ranked conditions must agree before an event is "
                "eligible; 1 is the plain OR.  Agreement behaves like "
                "confidence on AUD_USD (OOS single-match events averaged "
                "-14.1 yen, four-or-more averaged +22.1), so AUD_USD uses 3. "
                "USD_JPY stays at 1 because 75% of its matches are "
                "single-condition and a higher bar starves it."
            ),
            "minimum_target_distance_pips": min_target_distance_pips,
            "target_distance_source": "decision_time distance_pips",
            "all_baseline_excluded": True,
            "additional_top15_eligibility_filters": True,
            "eligibility_filters": {
                "minimum_trades": MINIMUM_CONDITION_TRADES,
                "minimum_positive_periods": CONDITION_MINIMUM_POSITIVE_PERIODS,
                "positive_periods_of": 4,
                "note": (
                    "per-trade ranking and a within-train four-quarter "
                    "stability gate replace the prior unfiltered raw "
                    "sum_yen ranking, which favored high-volume/low-edge "
                    "conditions and had no train-internal stability check"
                ),
            },
            "ranking_order": [
                "avg_yen_per_trade_desc",
                "positive_month_rate_desc",
                "profit_factor_yen_desc",
                "sum_pips_desc",
                "condition_id_asc",
            ],
            "multiple_testing_diagnostics": {
                "num_candidates_tested": len(shortlisted_conditions),
                "alpha": CONDITION_MULTIPLE_TESTING_ALPHA,
                "method": "bonferroni_two_sided_z",
                "enforced_as_hard_gate": False,
                "note": (
                    "yen_per_trade_z/bonferroni_z_threshold/"
                    "clears_bonferroni_bar are reported per condition as "
                    "diagnostics, not enforced — a strict Bonferroni bar "
                    "over this many candidates can plausibly reject every "
                    "candidate given this feature catalog's effect sizes"
                ),
            },
            "excluded_feature_fields": list(excluded_fields),
            "feature_bucket_specs": {
                name: {
                    "source_column": spec.source_column,
                    "edges": list(spec.edges),
                    "labels": list(spec.labels),
                }
                for name, spec in bucket_specs_for_pair(pair).items()
            },
            "tier_ranges": {
                config.tier: [config.first_rank, config.last_rank]
                for config in tier_configs
            },
            "same_event_line_selection": (
                "highest_signal_tier_then_apply_frozen_tier_range_filter_"
                "then_nearest_line"
            ),
            "one_order_per_event": True,
        },
        "global_lifecycle_performance": _row_payload(selected_global),
        "train_portfolio_replay_performance": train_performance,
        "watch_entry_train_performance": watch_entry_train_performance,
        "execution": {
            "spread_pips": spread_pips,
            "position_horizon_minutes": position_horizon_minutes,
            "min_width_pips": min_width_pips,
            "risk_yen": risk_yen,
            "min_target_distance_pips": min_target_distance_pips,
            "watch_entry": watch_entry_config.to_dict(),
            "profit_lock": {
                "enabled": profit_lock_enabled,
                "minimum_effective_tp_pips": profit_lock_min_tp_pips,
                "trigger_tp_fraction": profit_lock_trigger_tp_fraction,
                "locked_result_pips": profit_lock_result_pips,
                "active_from": "next_S5_after_trigger_bar",
                "same_trigger_s5_reversal_policy": (
                    "raised_stop_not_active; original TP/LC ordering policy"
                ),
            },
            "stretch_profit_lock": {
                "enabled": True,
                "base_width_definition": "1B=frozen_tier_take_profit",
                "target_b": STRETCH_PROFIT_TARGET_B,
                "trigger_b": STRETCH_PROFIT_TRIGGER_B,
                "locked_result_b": STRETCH_PROFIT_LOCK_B,
                "active_from": "next_S5_after_1p2B_trigger_bar",
                "same_trigger_s5_reversal_policy": (
                    "raised_stop_not_active; original TP/LC ordering policy"
                ),
                "hard_lc_unchanged": True,
            },
            "one_active_flip_lifecycle_per_pair": True,
            "unfilled_candidate_replaced_by_next_foot_count2": (
                path_config.replace_unfilled_on_next_count2
            ),
            "unfilled_order_kept_through_next_foot_count2": (
                not path_config.replace_unfilled_on_next_count2
            ),
            "order_uses_first_spread_aware_s5_limit_touch": True,
            "order_direction_is_negative_peak_direction": True,
            "latest_line_peak_direction_must_equal_order_direction": True,
            "target_distance_filter_uses_decision_time_only": True,
            "breakout_confirmation_used": False,
            "same_s5_tp_lc_is_loss": True,
            "profit_lock_uses_completed_trigger_s5_only": bool(
                profit_lock_enabled
            ),
            "stretch_profit_lock_uses_completed_trigger_s5_only": True,
            "stretch_profit_lock_design_fixed_before_oos": True,
            "position_outcome_requires_contiguous_s5_to_exit": True,
            "open_positions_at_period_end_are_censored": True,
            "tier_tp_rr_applied_after_top15_freeze": True,
            "range_filter_tp_and_lc_selected_on_analysis_only": True,
            "tier_specific_range_filter_tp_and_lc_supported": True,
            "timed_half_lc": primary_timed_half_lc_config.to_dict(),
            "timed_half_lc_replay_configs": [
                config.to_dict() for config in replay_timed_half_lc_configs
            ],
            "timed_half_lc_selection_period": "analysis_period_only",
            "timed_half_lc_activation_uses_checkpoint_open_only": True,
            "timed_half_lc_half_tp_is_diagnostic_only": True,
            "timed_half_lc_gap_or_activation_open_is_spread_aware": True,
            "line_wick_lc": selected_line_wick_lc_config.to_dict(),
            "line_wick_lc_replay_configs": [
                config.to_dict() for config in replay_line_wick_lc_configs
            ],
            "line_wick_lc_selection_period": "analysis_period_only",
            "line_wick_lc_uses_decision_time_a": True,
            "line_wick_lc_uses_spread_aware_s5_wick": True,
            "line_wick_lc_original_hard_lc_retained": True,
            "minimum_width_floor_scales_tp_and_lc_together": True,
            "configured_rr_preserved_before_price_increment_rounding": True,
            "effective_rr_exported_after_price_increment_rounding": True,
            "watch_entry_uses_completed_s5_only": True,
            "watch_initial_and_post_observation_waits_are_separate": True,
            "watch_pending_entry_gap_filter_is_causal": True,
            "watch_stop_fill_bar_pretrigger_wick_is_excluded": True,
        },
        "future_safety": {
            "decision_features_from_causal_candidate_ledger": True,
            "candidate_source_times_checked_not_after_decision": True,
            "required_candidate_source_times_must_be_present": True,
            "fill_and_trade_fields_are_labels_only": True,
            "fixed_replay_not_used_for_selection": True,
            "top15_conditions_frozen_before_fixed_replay": True,
            "tier_settings_frozen_before_fixed_replay": True,
            "range_filter_tp_and_lc_grid_not_selected_on_oos": True,
            "target_distance_filter_uses_decision_time_only": True,
            "target_distance_filter_frozen_before_fixed_replay": True,
            "watch_entry_frozen_before_fixed_replay": True,
            "watch_entry_not_selected_on_oos": True,
            "watch_observation_cannot_cross_period_end": True,
            "watch_unknown_s5_gaps_rejected": True,
            "line_holding_early_snapshots_use_completed_s5_only": True,
            "line_holding_early_final_fields_are_labels_only": True,
            "line_holding_early_prices_stop_at_actual_exit": True,
            "line_holding_exit_s5_opposite_extreme_censored": True,
            "stretch_profit_lock_fixed_before_fixed_replay": True,
            "stretch_profit_lock_not_selected_on_oos": True,
            "timed_half_lc_selected_on_analysis_only": True,
            "timed_half_lc_not_selected_on_oos": True,
            "line_wick_lc_selected_on_analysis_only": True,
            "line_wick_lc_not_selected_on_oos": True,
            "counterfactual_horizon_fields_are_labels_only": True,
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
            "range_lc_search": artifact["range_lc_search"],
            "line_wick_lc_search": artifact["line_wick_lc_search"],
            "timed_half_lc_search": artifact["timed_half_lc_search"],
            "watch_entry_policy": artifact["watch_entry_policy"],
            "stretch_profit_lock": artifact["stretch_profit_lock"],
            "performance": train_performance,
            "watch_entry_performance": watch_entry_train_performance,
            "watch_entry_branches": watch_entry_train_branches.to_dict(
                orient="records"
            ),
            "stretch_profit_lock_performance": stretch_train_performance,
            "monthly": train_monthly.to_dict(orient="records"),
            "stretch_profit_lock_monthly": stretch_train_monthly.to_dict(
                orient="records"
            ),
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
                    (
                        f"- ranking grid selected: filter "
                        f"{ranking_range_filter_pips:g} pips / "
                        f"TP{trade_combo.tp_a:g}A / "
                        f"LC{trade_combo.lc_a:g}A / "
                        f"stage {selected_global['selection_stage']}"
                    ),
                    f"- order triggers: top {TOP_CONDITION_LIMIT} conditions (OR)",
                    f"- tiers: {tier_ranges_text}",
                    f"- tier settings: {tier_settings_text}",
                    (
                        "- selected line-wick LC: "
                        f"{selected_line_wick_lc_config.config_id} / "
                        f"stage {selected_line_wick_lc_row['selection_stage']}"
                    ),
                    (
                        "- timed half-LC strict selections: "
                        + (
                            ",".join(
                                config.config_id
                                for config in selected_timed_half_lc_configs
                            )
                            if selected_timed_half_lc_configs
                            else "none (baseline replay only)"
                        )
                        + f" / stage {timed_selection_stage}"
                    ),
                    (
                        "- timed half-LC diagnostic primary: "
                        f"{primary_timed_half_lc_config.config_id}"
                    ),
                    f"- train trades: {train_performance['completed_trade_count']}",
                    f"- train win rate: {train_performance['win_rate']:.2%}",
                    f"- train average win: {train_performance['average_win_pips']:.2f} pips",
                    f"- train profit locks: {train_performance['profit_lock_count']}",
                    f"- train net: {train_performance['sum_yen']:.0f} yen",
                    (
                        "- watch entry: 60s / LineHolding<0.1A / "
                        "NearLine<=1A / Breakout>1A / post-watch wait "
                        f"{path_config.order_wait_minutes}m / max gap "
                        f"{watch_entry_config.max_entry_gap_a:g}A"
                    ),
                    (
                        "- watch train trades: "
                        f"{watch_entry_train_performance['completed_trade_count']}"
                    ),
                    (
                        "- watch train win rate: "
                        f"{watch_entry_train_performance['win_rate']:.2%}"
                    ),
                    (
                        "- watch train net: "
                        f"{watch_entry_train_performance['sum_yen']:.0f} yen"
                    ),
                    (
                        "- LineHolding early path data: "
                        f"{paths['line_holding_early_path_train']}"
                    ),
                    (
                        "- stretch profit lock: target 2B / trigger 1.2B / "
                        "lock +1B"
                    ),
                    (
                        "- stretch train trades: "
                        f"{stretch_train_performance['completed_trade_count']}"
                    ),
                    (
                        "- stretch train win rate: "
                        f"{stretch_train_performance['win_rate']:.2%}"
                    ),
                    (
                        "- stretch train net: "
                        f"{stretch_train_performance['sum_yen']:.0f} yen"
                    ),
                    f"- TP/LC pips matrix: {paths['tp_lc_pips_matrix']}",
                    f"- TP/LC A matrix: {paths['tp_lc_a_matrix']}",
                    f"- timed half-LC grid: {paths['timed_half_lc_grid']}",
                    f"- line-wick LC grid: {paths['line_wick_lc_grid']}",
                    (
                        "- line-wick LC trade detail: "
                        f"{paths['line_wick_lc_train_trades']}"
                    ),
                    (
                        "- timed half-LC trade detail: "
                        f"{paths['timed_half_lc_train_trades']}"
                    ),
                )
            )
        )
    return {
        "artifact": artifact,
        "artifact_path": paths["artifact"],
        "paths": paths,
        "train_trades": train_trades,
        "train_performance": train_performance,
        "watch_entry_train_trades": watch_entry_train_trades,
        "watch_entry_train_performance": watch_entry_train_performance,
        "watch_entry_train_branches": watch_entry_train_branches,
        "line_holding_early_path_train": line_holding_early_path_train,
        "stretch_profit_lock_train_trades": stretch_train_trades,
        "stretch_profit_lock_train_performance": (
            stretch_train_performance
        ),
    }


if __name__ == "__main__":
    raise SystemExit("Run a test_kick_<pair>_flip_predict.py launcher")
