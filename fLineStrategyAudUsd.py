"""Line strategy classes for AUD_USD."""

import copy
import math

from fLineStrategyEurUsd import LineStrategyProfileEurUsd
from fLineStrategyUsdJpy import LineStrategyProfileUsdJpy


class LineStrategyProfileAudUsd(LineStrategyProfileEurUsd):
    """AUD_USD line strategy."""

    pair = "AUD_USD"
    # Flip to False to restore this pair's non-PredictReversal line orders.
    predict_reversal_only = True
    predict_reversal_ranking_version = "pair_v2_aud_rsi_strength_reach"
    predict_reversal_distance_ratio_cap = 0.75
    predict_reversal_distance_cap_fallback = "nearest"

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
