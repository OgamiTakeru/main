"""Line strategy classes for EUR_USD."""

from fLineStrategyUsdJpy import LineStrategyProfileUsdJpy


class LineStrategyProfileEurUsd(LineStrategyProfileUsdJpy):
    """EUR_USD line strategy."""

    pair = "EUR_USD"
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
        session_hour = candidate.get("session_hour")
        if session_hour in self.breakout_hours_jst:
            if candidate["line_strategy"] != "m5_breakout_peakdir_allcount":
                return []
            return self._eurusd_breakout_reasons(candidate, rsi_info)

        return super().recommended_reasons(candidate, rsi_info, latest_peak_info)

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
