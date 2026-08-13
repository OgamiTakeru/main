"""Line strategy classes for EUR_USD."""

import math

from fLineStrategyUsdJpy import LineStrategyProfileUsdJpy


def _grid_policy(
    *,
    label,
    ranking_source,
    timeframe,
    field,
    operator,
    entry_rank,
    offset,
    tp,
    lc,
    positive_rate,
    sum_yen,
    sum_pips,
    selected_parameter_source=None,
    **match,
):
    """Build one static, pair-specific count2 grid policy."""
    policy = {
        "label": label,
        "ranking_source": ranking_source,
        "timeframe": timeframe,
        "field": field,
        "operator": operator,
        "entry_rank": entry_rank,
        "entry_offset_range_multiplier": offset,
        "tp_range_multiplier": tp,
        "lc_range_multiplier": lc,
        "grid_positive_rate": positive_rate,
        "grid_sum_yen": sum_yen,
        "grid_sum_pips": sum_pips,
    }
    if selected_parameter_source is not None:
        policy["selected_parameter_source"] = selected_parameter_source
    policy.update(match)
    return policy


class LineStrategyProfileEurUsd(LineStrategyProfileUsdJpy):
    """EUR_USD line strategy."""

    pair = "EUR_USD"
    # Flip to False to restore this pair's non-PredictReversal line orders.
    predict_reversal_only = True
    predict_reversal_ranking_version = "pair_v2_eur_rsi_strength_reach"
    predict_reversal_distance_ratio_cap = 0.5
    predict_reversal_distance_cap_fallback = "nearest"
    # The trend-regime block is USD/JPY-specific.  Common peaks-count and RSI
    # filters remain inherited for EUR/USD and AUD/USD.
    predict_reversal_block_trend_regimes = False
    # Pair-specific policies selected from the causal 2025-07-30 through
    # 2026-07-30 grid.  Eligibility required at least 100 completed paths,
    # completed-path positive rate >= 40%, and configured RR >= 1.2.  These
    # are the union of risk-normalized-yen Top15 and raw-pips Top15; BOTH
    # marks conditions present in both rankings.
    predict_reversal_filter_policy_version = "count2_grid_eur_1y_win40_v1"
    predict_reversal_grid_conditions = (
        _grid_policy(
            label="BOTH M5 pullback foot count criterion passed",
            ranking_source="BOTH", selected_parameter_source="YEN",
            timeframe="m5", field="criteria.pullback_foot_count",
            operator="equals", value=True,
            entry_rank=3, offset=0.0, tp=6.0, lc=1.25,
            positive_rate=0.4125560538116592,
            sum_yen=2476.49, sum_pips=334.8,
        ),
        _grid_policy(
            label="BOTH H1 first impulse pace 4.00-4.99 pips per foot",
            ranking_source="BOTH", selected_parameter_source="YEN",
            timeframe="h1", field="first_impulse_pips_per_foot",
            operator="range", minimum=4.0, maximum=5.0,
            entry_rank=3, offset=-0.25, tp=4.0, lc=1.25,
            positive_rate=0.4027777777777778,
            sum_yen=1021.27, sum_pips=171.9,
        ),
        _grid_policy(
            label="BOTH H1 second pullback pace 4.00-4.99 pips per foot",
            ranking_source="BOTH", selected_parameter_source="YEN",
            timeframe="h1", field="second_pullback_pips_per_foot",
            operator="range", minimum=4.0, maximum=5.0,
            entry_rank=3, offset=0.0, tp=6.0, lc=1.5,
            positive_rate=0.4225352112676056,
            sum_yen=966.72, sum_pips=162.8,
        ),
        _grid_policy(
            label="BOTH H1 third impulse required ratio 1.00-1.24",
            ranking_source="BOTH", selected_parameter_source="YEN",
            timeframe="h1", field="third_impulse_required_ratio",
            operator="range", minimum=1.0, maximum=1.25,
            entry_rank=2, offset=0.0, tp=6.0, lc=2.5,
            positive_rate=0.5149501661129569,
            sum_yen=937.20, sum_pips=174.6,
        ),
        _grid_policy(
            label="BOTH M5 first impulse pace 2.00-2.99 pips per foot",
            ranking_source="BOTH", selected_parameter_source="YEN",
            timeframe="m5", field="first_impulse_pips_per_foot",
            operator="range", minimum=2.0, maximum=3.0,
            entry_rank=3, offset=-0.25, tp=4.0, lc=1.5,
            positive_rate=0.4114285714285714,
            sum_yen=919.84, sum_pips=187.8,
        ),
        _grid_policy(
            label="BOTH M5 third impulse required ratio 1.50-1.99",
            ranking_source="BOTH", selected_parameter_source="YEN",
            timeframe="m5", field="third_impulse_required_ratio",
            operator="range", minimum=1.5, maximum=2.0,
            entry_rank=1, offset=-0.25, tp=6.0, lc=1.5,
            positive_rate=0.43564356435643564,
            sum_yen=915.84, sum_pips=209.2,
        ),
        _grid_policy(
            label="BOTH H1 first pullback pace 2.00-2.99 pips per foot",
            ranking_source="BOTH", selected_parameter_source="YEN",
            timeframe="h1", field="first_pullback_pips_per_foot",
            operator="range", minimum=2.0, maximum=3.0,
            entry_rank=3, offset=0.25, tp=5.0, lc=1.5,
            positive_rate=0.4114285714285714,
            sum_yen=875.15, sum_pips=160.2,
        ),
        _grid_policy(
            label="BOTH M5 third impulse break 3.00-4.99 pips",
            ranking_source="BOTH", selected_parameter_source="YEN",
            timeframe="m5", field="third_impulse_break_pips",
            operator="range", minimum=3.0, maximum=5.0,
            entry_rank=1, offset=0.25, tp=5.0, lc=3.0,
            positive_rate=0.5174825174825175,
            sum_yen=804.66, sum_pips=218.0,
        ),
        _grid_policy(
            label="BOTH H1 second impulse pace 3.00-3.99 pips per foot",
            ranking_source="BOTH", selected_parameter_source="YEN",
            timeframe="h1", field="second_impulse_pips_per_foot",
            operator="range", minimum=3.0, maximum=4.0,
            entry_rank=3, offset=0.0, tp=6.0, lc=2.5,
            positive_rate=0.483695652173913,
            sum_yen=701.12, sum_pips=177.8,
        ),
        _grid_policy(
            label="M5 confirmed failure signature A",
            ranking_source="YEN", timeframe="m5",
            field="confirmed_failed_conditions", operator="sequence_equals",
            value=("completed_impulse_foot_count", "impulse_distance",
                   "pullback_ratio", "impulse_progression",
                   "structure_progression"),
            entry_rank=2, offset=-0.25, tp=6.0, lc=2.0,
            positive_rate=0.45161290322580644,
            sum_yen=928.30, sum_pips=130.3,
        ),
        _grid_policy(
            label="H1 third impulse pace 2.00-2.99 pips per foot",
            ranking_source="YEN", timeframe="h1",
            field="third_impulse_pips_per_foot", operator="range",
            minimum=2.0, maximum=3.0,
            entry_rank=3, offset=0.25, tp=4.0, lc=2.0,
            positive_rate=0.4819277108433735,
            sum_yen=738.77, sum_pips=148.4,
        ),
        _grid_policy(
            label="M5 first structure progress 1.00-1.99 pips",
            ranking_source="YEN", timeframe="m5",
            field="first_structure_progress_pips", operator="range",
            minimum=1.0, maximum=2.0,
            entry_rank=3, offset=-0.25, tp=3.0, lc=1.25,
            positive_rate=0.40186915887850466,
            sum_yen=719.20, sum_pips=46.8,
        ),
        _grid_policy(
            label="M5 first pullback foot ratio 0.65-0.79",
            ranking_source="YEN", timeframe="m5",
            field="first_pullback_foot_ratio", operator="range",
            minimum=0.65, maximum=0.80,
            entry_rank=3, offset=0.0, tp=5.0, lc=1.5,
            positive_rate=0.40764331210191085,
            sum_yen=619.39, sum_pips=134.1,
        ),
        _grid_policy(
            label="M5 candidate failure signature A",
            ranking_source="YEN", timeframe="m5",
            field="candidate_failed_conditions", operator="sequence_equals",
            value=("completed_impulse_foot_count", "impulse_distance",
                   "pullback_ratio", "structure_progression"),
            entry_rank=2, offset=-0.25, tp=2.5, lc=1.25,
            positive_rate=0.4067796610169492,
            sum_yen=614.97, sum_pips=70.5,
        ),
        _grid_policy(
            label="H1 first impulse foot count 5",
            ranking_source="YEN", timeframe="h1",
            field="first_impulse_foot_count", operator="equals_number",
            value=5,
            entry_rank=3, offset=0.0, tp=6.0, lc=1.5,
            positive_rate=0.4090909090909091,
            sum_yen=601.54, sum_pips=138.7,
        ),
        _grid_policy(
            label="H1 third impulse pace 8.00+ pips per foot",
            ranking_source="PIPS", timeframe="h1",
            field="third_impulse_pips_per_foot", operator="at_least",
            minimum=8.0,
            entry_rank=3, offset=-0.25, tp=6.0, lc=4.0,
            positive_rate=0.5310344827586206,
            sum_yen=240.11, sum_pips=217.5,
        ),
        _grid_policy(
            label="M5 first impulse foot count 4",
            ranking_source="PIPS", timeframe="m5",
            field="first_impulse_foot_count", operator="equals_number",
            value=4,
            entry_rank=3, offset=-0.25, tp=5.0, lc=3.0,
            positive_rate=0.46,
            sum_yen=64.89, sum_pips=198.4,
        ),
        _grid_policy(
            label="M5 first impulse required ratio 1.00-1.24",
            ranking_source="PIPS", timeframe="m5",
            field="first_impulse_required_ratio", operator="range",
            minimum=1.0, maximum=1.25,
            entry_rank=3, offset=-0.25, tp=6.0, lc=4.0,
            positive_rate=0.5285714285714286,
            sum_yen=425.57, sum_pips=181.0,
        ),
        _grid_policy(
            label="H1 third impulse required ratio 1.25-1.49",
            ranking_source="PIPS", timeframe="h1",
            field="third_impulse_required_ratio", operator="range",
            minimum=1.25, maximum=1.5,
            entry_rank=3, offset=-0.25, tp=6.0, lc=4.0,
            positive_rate=0.5045045045045045,
            sum_yen=201.32, sum_pips=158.0,
        ),
        _grid_policy(
            label="M5 second impulse foot count 2",
            ranking_source="PIPS", timeframe="m5",
            field="second_impulse_foot_count", operator="equals_number",
            value=2,
            entry_rank=3, offset=-0.25, tp=3.0, lc=1.5,
            positive_rate=0.4051724137931034,
            sum_yen=170.68, sum_pips=152.0,
        ),
        _grid_policy(
            label="H1 candidate failure signature A",
            ranking_source="PIPS", timeframe="h1",
            field="candidate_failed_conditions", operator="sequence_equals",
            value=("completed_impulse_foot_count", "impulse_distance",
                   "pullback_ratio", "structure_progression"),
            entry_rank=2, offset=0.0, tp=4.0, lc=3.0,
            positive_rate=0.5123456790123457,
            sum_yen=411.31, sum_pips=150.7,
        ),
    )
    predict_reversal_top15_conditions = predict_reversal_grid_conditions
    predict_reversal_m5_stair_enabled = True

    def _predict_reversal_pair_score_components(self, features):
        """EUR/USD score selected on train/validation before OOS review."""
        distance_log = math.log1p(features["distance_ratio"])
        count_log = math.log1p(features["line_count"])
        last_elapsed = features["last_reach_elapsed_minutes"]
        elapsed_log = (
            math.log1p(max(last_elapsed, 0.0) / 5.0)
            if last_elapsed is not None
            else 0.0
        )
        retouch_log = math.log1p(features["prior_retouch_count"])
        source_directional_rsi = features["directional_source_rsi"] / 10.0
        decision_directional_rsi = features["directional_rsi"] / 10.0
        return {
            "line_average_strength": features["average_strength"],
            "line_count": -0.50 * count_log,
            "line_core_average_strength": (
                0.10 * features["core_average_strength"]
            ),
            "distance": -0.25 * distance_log,
            "effective_last_reach": -0.05 * elapsed_log,
            "source_rsi": -0.05 * source_directional_rsi,
            "decision_rsi_x_distance": (
                0.05 * decision_directional_rsi * distance_log
            ),
            "prior_retouch_count": -0.05 * retouch_log,
        }
    # Selected from the 2025/06/24-2026/06/24 walk-forward inspection.
    # Each condition was profitable both before and after the 2026/03/24 split.
    # The former EUR conditions are intentionally replaced rather than combined.
    top10_conditions = [
        {
            "label": "EUR WF1 sell prevPeakRSI50-60 lineStr15-20",
            "filters": {
                "direction_label": "sell",
                "previous_peak_rsi_bin": "50-60",
                "line_strength_bin": "15-20",
            },
        },
        {
            "label": "EUR WF2 session15-20 M5RSI40-50 prevPeakRSI50-60",
            "filters": {
                "session_bucket": "15-20",
                "m5_rsi_bin": "40-50",
                "previous_peak_rsi_bin": "50-60",
            },
        },
        {
            "label": "EUR WF3 peakRSI40-50 prevPeakRSI50-60 H1Str10-15",
            "filters": {
                "latest_peak_rsi_bin": "40-50",
                "previous_peak_rsi_bin": "50-60",
                "h1_nearest_strength_bin": "10-15",
            },
        },
        {
            "label": "EUR WF4 coreStr0-5 H1Str10-15 path6-10",
            "filters": {
                "core_strength_bin": "0-5",
                "h1_nearest_strength_bin": "10-15",
                "path1_distance_bin": "6-10p",
            },
        },
        {
            "label": "EUR WF5 sell lower coreStr10-15",
            "filters": {
                "direction_label": "sell",
                "line_side": "lower",
                "core_strength_bin": "10-15",
            },
        },
        {
            "label": "EUR WF6 lower session15-20 pathStr5-10",
            "filters": {
                "line_side": "lower",
                "session_bucket": "15-20",
                "path1_strength_bin": ("5-8", "8-10"),
            },
        },
        {
            "label": "EUR WF7 session21-23 H1RSI40-50 prevPeakRSI60-67.5",
            "filters": {
                "session_bucket": "21-23",
                "h1_rsi_bin": "40-50",
                "previous_peak_rsi_bin": "60-67.5",
            },
        },
        {
            "label": "EUR WF8 buy H1RSI<=30 H1Str5-10",
            "filters": {
                "direction_label": "buy",
                "h1_rsi_bin": "<=30",
                "h1_nearest_strength_bin": ("5-8", "8-10"),
            },
        },
        {
            "label": "EUR WF9 sell H1RSI40-50 path6-10",
            "filters": {
                "direction_label": "sell",
                "h1_rsi_bin": "40-50",
                "path1_distance_bin": "6-10p",
            },
        },
    ]
    breakout_hours_jst = set(range(15, 24)) | {0, 1}
    breakout_top_conditions = [
        {
            "label": "EUR breakout upper c1 str0-10 H1same0-10 RSI45-75",
            "line_strategy": "m5_breakout_peakdir_allcount",
            "target_count": 1,
            "strength_range": (0, 10),
            "target_core_count": 1,
            "core_strength_range": (0, 10),
            "target_h1_same_side": True,
            "h1_distance_range": (0, 10),
            "target_h1_blocks": True,
            "rsi_range": (45, 75),
            "target_side": "upper",
            "target_peak_dir": 1,
        },
        {
            "label": "EUR breakout upper c2 str0-15 H1same0-15 RSI40-80",
            "line_strategy": "m5_breakout_peakdir_allcount",
            "target_count": 2,
            "strength_range": (0, 15),
            "target_core_count": 1,
            "core_strength_range": (0, 15),
            "target_h1_same_side": True,
            "h1_distance_range": (0, 15),
            "target_h1_blocks": True,
            "rsi_range": (40, 80),
            "target_side": "upper",
            "target_peak_dir": 1,
        },
        {
            "label": "EUR breakout lower c1 str0-10 H1same0-10 RSI25-55",
            "line_strategy": "m5_breakout_peakdir_allcount",
            "target_count": 1,
            "strength_range": (0, 10),
            "target_core_count": 1,
            "core_strength_range": (0, 10),
            "target_h1_same_side": True,
            "h1_distance_range": (0, 10),
            "target_h1_blocks": True,
            "rsi_range": (25, 55),
            "target_side": "lower",
            "target_peak_dir": -1,
        },
        {
            "label": "EUR breakout lower c2 str0-15 H1same0-15 RSI20-60",
            "line_strategy": "m5_breakout_peakdir_allcount",
            "target_count": 2,
            "strength_range": (0, 15),
            "target_core_count": 1,
            "core_strength_range": (0, 15),
            "target_h1_same_side": True,
            "h1_distance_range": (0, 15),
            "target_h1_blocks": True,
            "rsi_range": (20, 60),
            "target_side": "lower",
            "target_peak_dir": -1,
        },
    ]

    def recommended_reasons(self, candidate, rsi_info, latest_peak_info):
        top10_reasons = self._configured_top10_reasons(candidate, rsi_info)
        if top10_reasons:
            return top10_reasons
        return []

        session_hour = candidate.get("session_hour")
        if session_hour in self.breakout_hours_jst:
            if candidate["line_strategy"] != "m5_breakout_peakdir_allcount":
                return []
            return self._eurusd_breakout_reasons(candidate, rsi_info)

        return super().recommended_reasons(candidate, rsi_info, latest_peak_info)

    def immediate_recommended_reasons(self, candidate, rsi_info, latest_peak_info):
        """Use the same walk-forward conditions for EUR/USD market entries."""
        return self._configured_top10_reasons(candidate, rsi_info)

    def _eurusd_breakout_reasons(self, candidate, rsi_info):
        line = candidate["line"]
        h1_context = candidate.get("h1_context", {})
        count = int(line.get("count") or 0)
        strength = float(line.get("total_strength") or 0)
        core_count = int(line.get("core_count") or 0)
        core_strength = float(line.get("core_total_strength") or 0)
        h1_distance = h1_context.get("h1_nearest_distance_pips")
        h1_side = h1_context.get("h1_nearest_side")
        h1_blocks = h1_context.get("h1_blocks_trade_direction")
        rsi_1 = None if rsi_info is None else rsi_info.get("rsi_1")
        h1_same_side = h1_side == candidate["line_side"]

        return self._configured_top7_reasons(
            candidate,
            count,
            strength,
            core_count,
            core_strength,
            h1_same_side,
            h1_distance,
            h1_blocks,
            rsi_1,
            self.breakout_top_conditions,
        )
