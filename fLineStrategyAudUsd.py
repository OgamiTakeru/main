"""Line strategy classes for AUD_USD."""

import copy
import math

from fLineStrategyEurUsd import LineStrategyProfileEurUsd, _grid_policy
from fLineStrategyUsdJpy import LineStrategyProfileUsdJpy


class LineStrategyProfileAudUsd(LineStrategyProfileEurUsd):
    """AUD_USD line strategy."""

    pair = "AUD_USD"
    # Flip to False to restore this pair's non-PredictReversal line orders.
    predict_reversal_only = True
    predict_reversal_ranking_version = "pair_v2_aud_rsi_strength_reach"
    predict_reversal_distance_ratio_cap = 0.75
    predict_reversal_distance_cap_fallback = "nearest"
    # Pair-specific union of the causal 2025-07-30 through 2026-07-30
    # risk-normalized-yen Top15 and raw-pips Top15.  Selection required at
    # least 100 completed paths, positive rate >= 40%, and RR >= 1.2.
    # The equivalent M5 candidate_passed/detected/would_block cohorts are
    # represented once so later duplicate policies cannot become dead code.
    predict_reversal_filter_policy_version = "count2_grid_aud_1y_win40_v1"
    predict_reversal_grid_conditions = (
        _grid_policy(
            label="BOTH H1 third impulse pace 8.00+ pips per foot",
            ranking_source="BOTH", selected_parameter_source="YEN",
            timeframe="h1", field="third_impulse_pips_per_foot",
            operator="at_least", minimum=8.0,
            entry_rank=2, offset=0.25, tp=4.0, lc=1.5,
            positive_rate=0.4574468085106383,
            sum_yen=1080.56, sum_pips=106.7,
        ),
        _grid_policy(
            label="BOTH M5 first pullback foot ratio 0.65-0.79",
            ranking_source="BOTH", selected_parameter_source="YEN",
            timeframe="m5", field="first_pullback_foot_ratio",
            operator="range", minimum=0.65, maximum=0.80,
            entry_rank=3, offset=0.25, tp=4.0, lc=3.0,
            positive_rate=0.5247524752475248,
            sum_yen=805.32, sum_pips=108.4,
        ),
        _grid_policy(
            label="BOTH H1 confirmed failure impulse distance",
            ranking_source="BOTH", selected_parameter_source="YEN",
            timeframe="h1", field="confirmed_failed_conditions",
            operator="sequence_equals", value=("impulse_distance",),
            entry_rank=1, offset=0.0, tp=2.5, lc=1.25,
            positive_rate=0.424,
            sum_yen=609.39, sum_pips=56.0,
        ),
        _grid_policy(
            label="BOTH H1 candidate failure signature A",
            ranking_source="BOTH", selected_parameter_source="YEN",
            timeframe="h1", field="candidate_failed_conditions",
            operator="sequence_equals",
            value=("pullback_foot_count", "impulse_distance",
                   "pullback_ratio", "impulse_progression",
                   "structure_progression", "dominance"),
            entry_rank=3, offset=0.25, tp=5.0, lc=2.0,
            positive_rate=0.45689655172413796,
            sum_yen=606.66, sum_pips=73.3,
        ),
        _grid_policy(
            label="BOTH M5 second pullback ratio below 0.25",
            ranking_source="BOTH", selected_parameter_source="YEN",
            timeframe="m5", field="second_pullback_ratio",
            operator="less_than", maximum=0.25,
            entry_rank=2, offset=0.0, tp=2.0, lc=1.25,
            positive_rate=0.4672897196261682,
            sum_yen=598.44, sum_pips=76.0,
        ),
        _grid_policy(
            label="BOTH M5 staircase candidate passed",
            ranking_source="BOTH", selected_parameter_source="YEN",
            timeframe="m5", field="candidate_passed",
            operator="equals", value=True,
            entry_rank=1, offset=0.0, tp=6.0, lc=4.0,
            positive_rate=0.5321100917431193,
            sum_yen=459.01, sum_pips=51.8,
        ),
        _grid_policy(
            label="BOTH M5 impulse progression criterion passed",
            ranking_source="BOTH", selected_parameter_source="YEN",
            timeframe="m5", field="criteria.impulse_progression",
            operator="equals", value=True,
            entry_rank=2, offset=0.0, tp=5.0, lc=2.0,
            positive_rate=0.504950495049505,
            sum_yen=448.80, sum_pips=59.1,
        ),
        _grid_policy(
            label="BOTH M5 third impulse pace 3.00-3.99 pips per foot",
            ranking_source="BOTH", selected_parameter_source="PIPS",
            timeframe="m5", field="third_impulse_pips_per_foot",
            operator="range", minimum=3.0, maximum=4.0,
            entry_rank=1, offset=0.0, tp=6.0, lc=2.0,
            positive_rate=0.4767932489451477,
            sum_yen=429.30, sum_pips=109.7,
        ),
        _grid_policy(
            label="BOTH H1 confirmed failure signature A",
            ranking_source="BOTH", selected_parameter_source="YEN",
            timeframe="h1", field="confirmed_failed_conditions",
            operator="sequence_equals",
            value=("pullback_foot_count", "pullback_ratio",
                   "impulse_progression", "structure_progression",
                   "dominance"),
            entry_rank=1, offset=-0.25, tp=6.0, lc=2.5,
            positive_rate=0.5247524752475248,
            sum_yen=389.80, sum_pips=54.8,
        ),
        _grid_policy(
            label="BOTH M5 candidate failure signature A",
            ranking_source="BOTH", selected_parameter_source="YEN",
            timeframe="m5", field="candidate_failed_conditions",
            operator="sequence_equals",
            value=("pullback_foot_count", "impulse_distance",
                   "pullback_ratio", "impulse_progression"),
            entry_rank=2, offset=-0.25, tp=4.0, lc=3.0,
            positive_rate=0.48214285714285715,
            sum_yen=388.29, sum_pips=63.2,
        ),
        _grid_policy(
            label="M5 first pullback foot ratio 0.80-0.99",
            ranking_source="YEN", timeframe="m5",
            field="first_pullback_foot_ratio", operator="range",
            minimum=0.80, maximum=1.0,
            entry_rank=2, offset=-0.25, tp=2.0, lc=1.5,
            positive_rate=0.4700854700854701,
            sum_yen=404.66, sum_pips=41.9,
        ),
        _grid_policy(
            label="M5 confirmed failure signature B",
            ranking_source="YEN", timeframe="m5",
            field="confirmed_failed_conditions", operator="sequence_equals",
            value=("pullback_foot_count", "impulse_distance",
                   "pullback_ratio", "impulse_progression",
                   "structure_progression"),
            entry_rank=2, offset=-0.25, tp=5.0, lc=4.0,
            positive_rate=0.4913294797687861,
            sum_yen=313.01, sum_pips=31.6,
        ),
        _grid_policy(
            label="H1 first structure progress 3.00-4.99 pips",
            ranking_source="YEN", timeframe="h1",
            field="first_structure_progress_pips", operator="range",
            minimum=3.0, maximum=5.0,
            entry_rank=2, offset=0.0, tp=6.0, lc=2.5,
            positive_rate=0.45774647887323944,
            sum_yen=284.93, sum_pips=16.2,
        ),
        _grid_policy(
            label="H1 staircase would block PredictReversal",
            ranking_source="PIPS", timeframe="h1",
            field="would_block_predict_reversal", operator="equals",
            value=True,
            entry_rank=1, offset=0.25, tp=6.0, lc=4.0,
            positive_rate=0.49246231155778897,
            sum_yen=62.83, sum_pips=244.6,
        ),
        _grid_policy(
            label="H1 third impulse pace 5.00-7.99 pips per foot",
            ranking_source="PIPS", timeframe="h1",
            field="third_impulse_pips_per_foot", operator="range",
            minimum=5.0, maximum=8.0,
            entry_rank=3, offset=-0.25, tp=2.5, lc=1.5,
            positive_rate=0.43023255813953487,
            sum_yen=106.29, sum_pips=72.7,
        ),
        _grid_policy(
            label="H1 candidate failure pullback foot count",
            ranking_source="PIPS", timeframe="h1",
            field="candidate_failed_conditions", operator="sequence_equals",
            value=("pullback_foot_count",),
            entry_rank=1, offset=-0.25, tp=5.0, lc=4.0,
            positive_rate=0.5136986301369864,
            sum_yen=263.48, sum_pips=61.5,
        ),
        _grid_policy(
            label="M5 first impulse pace 2.00-2.99 pips per foot",
            ranking_source="PIPS", timeframe="m5",
            field="first_impulse_pips_per_foot", operator="range",
            minimum=2.0, maximum=3.0,
            entry_rank=2, offset=0.25, tp=2.0, lc=1.5,
            positive_rate=0.4785276073619632,
            sum_yen=207.68, sum_pips=54.3,
        ),
        _grid_policy(
            label="H1 dominance ratio 1.50-1.99",
            ranking_source="PIPS", timeframe="h1",
            field="dominance_ratio", operator="range",
            minimum=1.5, maximum=2.0,
            entry_rank=3, offset=-0.25, tp=4.0, lc=2.5,
            positive_rate=0.4765625,
            sum_yen=141.77, sum_pips=53.6,
        ),
    )
    predict_reversal_top15_conditions = predict_reversal_grid_conditions
    predict_reversal_m5_stair_enabled = True

    def _predict_reversal_pair_score_components(self, features):
        """AUD/USD score selected on train/validation before OOS review."""
        distance_log = math.log1p(features["distance_ratio"])
        last_elapsed = features["last_reach_elapsed_minutes"]
        elapsed_log = (
            math.log1p(max(last_elapsed, 0.0) / 60.0)
            if last_elapsed is not None
            else 0.0
        )
        directional_rsi = features["directional_rsi"] / 20.0
        return {
            "distance": -0.50 * distance_log,
            "line_average_strength_target": (
                -0.30 * abs(features["average_strength"] - 6.5)
            ),
            "line_core_total_strength": (
                0.10 * math.log1p(features["core_total_strength"])
            ),
            "line_count": -0.10 * math.log1p(features["line_count"]),
            "effective_last_reach": 0.05 * elapsed_log,
            "prior_retouch_count": (
                -0.05 * math.log1p(features["prior_retouch_count"])
            ),
            "decision_rsi_x_distance": (
                0.10 * directional_rsi * distance_log
            ),
        }
    top10_conditions = [
        {
            "label": "AUD WF1 sell H1RSI30-40",
            "filters": {
                "direction_label": "sell",
                "h1_rsi_bin": "30-40",
            },
        },
        {
            "label": "AUD WF2 sell session00-05 M5RSI40-50",
            "filters": {
                "direction_label": "sell",
                "session_bucket": "00-05",
                "m5_rsi_bin": "40-50",
            },
        },
        {
            "label": "AUD WF3 sell peakRSI40-50 lineStr5-8",
            "filters": {
                "direction_label": "sell",
                "latest_peak_rsi_bin": "40-50",
                "line_strength_bin": "5-8",
            },
        },
        {
            "label": "AUD WF4 sell coreStr0-5",
            "filters": {
                "direction_label": "sell",
                "core_strength_bin": "0-5",
            },
        },
        {
            "label": "AUD WF5 H1RSI40-50 coreStr0-5 H1Str0-5",
            "filters": {
                "h1_rsi_bin": "40-50",
                "core_strength_bin": "0-5",
                "h1_nearest_strength_bin": "0-5",
            },
        },
        {
            "label": "AUD WF6 lower prevPeakRSI50-60 pathStr5-8",
            "filters": {
                "line_side": "lower",
                "previous_peak_rsi_bin": "50-60",
                "path1_strength_bin": "5-8",
            },
        },
        {
            "label": "AUD WF7 M5RSI40-50 lineStr5-8 coreStr0-5",
            "filters": {
                "m5_rsi_bin": "40-50",
                "line_strength_bin": "5-8",
                "core_strength_bin": "0-5",
            },
        },
        {
            "label": "AUD WF8 buy session09-14 H1Str5-8",
            "filters": {
                "direction_label": "buy",
                "session_bucket": "09-14",
                "h1_nearest_strength_bin": "5-8",
            },
        },
        {
            "label": "AUD WF9 session09-14 prevPeakRSI50-60",
            "filters": {
                "session_bucket": "09-14",
                "previous_peak_rsi_bin": "50-60",
            },
        },
        {
            "label": "AUD WF10 lower lineStr0-5",
            "filters": {
                "line_side": "lower",
                "line_strength_bin": "0-5",
            },
        },
    ]
    breakout_top_conditions = copy.deepcopy(LineStrategyProfileEurUsd.breakout_top_conditions)

    def immediate_recommended_reasons(self, candidate, rsi_info, latest_peak_info):
        """Apply the strict base breakout gate instead of EUR's Top10-only gate.

        AUD/USD used to inherit LineStrategyProfileEurUsd's implementation,
        which accepted immediate market entries on an AUD Top10 match alone.
        That bypassed the break score, reason count, line history, peak, and
        H1 path checks implemented by the base line strategy.
        """
        return LineStrategyProfileUsdJpy.immediate_recommended_reasons(
            self,
            candidate,
            rsi_info,
            latest_peak_info,
        )


for condition in LineStrategyProfileAudUsd.breakout_top_conditions:
    condition["label"] = condition["label"].replace("EUR", "AUD")
