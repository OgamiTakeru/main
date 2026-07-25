"""Line strategy classes for EUR_USD."""

from fLineStrategyUsdJpy import LineStrategyProfileUsdJpy


class LineStrategyProfileEurUsd(LineStrategyProfileUsdJpy):
    """EUR_USD line strategy."""

    pair = "EUR_USD"
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
                "path1_strength_bin": "5-10",
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
                "h1_nearest_strength_bin": "5-10",
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
