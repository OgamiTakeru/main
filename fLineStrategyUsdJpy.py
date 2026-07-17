"""Line strategy classes for USD_JPY."""

import fGeneric as gene


class LineStrategyProfileUsdJpy:
    """USD_JPY用のライン戦術。

    LineStrengthCalで作った4つのライン結果を受け取り、
    ドル円ではどの線を注文候補にするか、どの候補を採用するかを決める。
    """

    pair = "USD_JPY"
    duplicate_threshold_pips = 3
    h1_strong_threshold = 10

    h1_lc_pips = 15
    h1_spread_pips = 0.8
    h1_rr = 1.65
    h1_units_multiplier = 0.5
    h1_order_timeout_min = 60
    h1_core_count_min = 1
    h1_core_total_strength_min = 5

    m5_lc_pips = 7.5
    m5_tp_pips = 14.1
    m5_units_multiplier = 0.25
    m5_order_timeout_min = 15
    m5_count_min = 1
    m5_core_count_min = 1
    m5_core_total_strength_min = 5
    m5_breakout_entry_offset_pips = 1.5
    immediate_near_line_max_pips = 3
    immediate_min_path_ahead_pips = 3
    immediate_strong_path_block_strength = 10
    immediate_previous_peak_strength_min = 5
    immediate_line_count_min = 2
    immediate_line_core_count_min = 2
    immediate_line_strength_min = 10
    top10_conditions = [
        {
            "label": "USD 1Y Top1 path0-3 buy M5RSI60-67.5",
            "filters": {
                "path1_distance_bin": "0-3p",
                "direction_label": "buy",
                "m5_rsi_bin": "60-67.5",
            },
        },
        {
            "label": "USD 1Y Top2 path3-6 reversal path1Str0-5",
            "filters": {
                "path1_distance_bin": "3-6p",
                "line_entry_type": "reversal",
                "path1_strength_bin": "0-5",
            },
        },
        {
            "label": "USD 1Y Top3 path50+ M5RSI60-67.5",
            "filters": {
                "path1_distance_bin": "50+p",
                "m5_rsi_bin": "60-67.5",
            },
        },
        {
            "label": "USD 1Y Top4 path0-3 reversal path1Str5-10",
            "filters": {
                "path1_distance_bin": "0-3p",
                "line_entry_type": "reversal",
                "path1_strength_bin": "5-10",
            },
        },
        {
            "label": "USD 1Y Top5 path50+ breakout session00-05",
            "filters": {
                "path1_distance_bin": "50+p",
                "line_entry_type": "breakout",
                "session_bucket": "00-05",
            },
        },
        {
            "label": "USD 1Y Top6 session06-08 lineStr5-10",
            "filters": {
                "session_bucket": "06-08",
                "line_strength_bin": "5-10",
            },
        },
    ]
    top7_conditions = [
        {
            "label": "Top1 upper reversal c2 str5-10 core2 H1same0-3 RSI30-40",
            "line_strategy": "m5_reversal_peakdir_allcount",
            "target_count": 2,
            "strength_range": (5, 10),
            "target_core_count": 2,
            "core_strength_range": (5, 10),
            "target_h1_same_side": True,
            "h1_distance_range": (0, 3),
            "target_h1_blocks": True,
            "rsi_range": (30, 40),
        },
        {
            "label": "Top2 upper reversal c1 str0-5 H1same6-10 RSI50-60",
            "line_strategy": "m5_reversal_peakdir_allcount",
            "target_count": 1,
            "strength_range": (0, 5),
            "target_core_count": 1,
            "core_strength_range": (0, 5),
            "target_h1_same_side": True,
            "h1_distance_range": (6, 10),
            "target_h1_blocks": True,
            "rsi_range": (50, 60),
        },
        {
            "label": "Top3 upper reversal c1 str5-10 H1far15+ RSI50-60",
            "line_strategy": "m5_reversal_peakdir_allcount",
            "target_count": 1,
            "strength_range": (5, 10),
            "target_core_count": 1,
            "core_strength_range": (5, 10),
            "target_h1_same_side": False,
            "h1_distance_range": (15, None),
            "target_h1_blocks": True,
            "rsi_range": (50, 60),
        },
        {
            "label": "Top4 upper reversal c1 str0-5 H1same3-6 RSI30-40",
            "line_strategy": "m5_reversal_peakdir_allcount",
            "target_count": 1,
            "strength_range": (0, 5),
            "target_core_count": 1,
            "core_strength_range": (0, 5),
            "target_h1_same_side": True,
            "h1_distance_range": (3, 6),
            "target_h1_blocks": True,
            "rsi_range": (30, 40),
        },
        {
            "label": "Top5 upper reversal c1 str0-5 H1same3-6 noBlock RSI40-50",
            "line_strategy": "m5_reversal_peakdir_allcount",
            "target_count": 1,
            "strength_range": (0, 5),
            "target_core_count": 1,
            "core_strength_range": (0, 5),
            "target_h1_same_side": True,
            "h1_distance_range": (3, 6),
            "target_h1_blocks": False,
            "rsi_range": (40, 50),
        },
        {
            "label": "Top6 upper breakout c1 str0-5 H1same3-6 RSI40-50",
            "line_strategy": "m5_breakout_peakdir_allcount",
            "target_count": 1,
            "strength_range": (0, 5),
            "target_core_count": 1,
            "core_strength_range": (0, 5),
            "target_h1_same_side": True,
            "h1_distance_range": (3, 6),
            "target_h1_blocks": True,
            "rsi_range": (40, 50),
        },
        {
            "label": "Top7 upper reversal c1 str0-5 H1same6-10 RSI40-50",
            "line_strategy": "m5_reversal_peakdir_allcount",
            "target_count": 1,
            "strength_range": (0, 5),
            "target_core_count": 1,
            "core_strength_range": (0, 5),
            "target_h1_same_side": True,
            "h1_distance_range": (6, 10),
            "target_h1_blocks": True,
            "rsi_range": (40, 50),
        },
        {
            "label": "Top1 lower reversal c2 str5-10 core2 H1same0-3 RSI30-40",
            "line_strategy": "m5_reversal_peakdir_allcount",
            "target_count": 2,
            "strength_range": (5, 10),
            "target_core_count": 2,
            "core_strength_range": (5, 10),
            "target_h1_same_side": True,
            "h1_distance_range": (0, 3),
            "target_h1_blocks": True,
            "rsi_range": (30, 40),
            "target_side": "lower",
            "target_peak_dir": -1,
        },
        {
            "label": "Top2 lower reversal c1 str0-5 H1same6-10 RSI50-60",
            "line_strategy": "m5_reversal_peakdir_allcount",
            "target_count": 1,
            "strength_range": (0, 5),
            "target_core_count": 1,
            "core_strength_range": (0, 5),
            "target_h1_same_side": True,
            "h1_distance_range": (6, 10),
            "target_h1_blocks": True,
            "rsi_range": (50, 60),
            "target_side": "lower",
            "target_peak_dir": -1,
        },
        {
            "label": "Top3 lower reversal c1 str5-10 H1far15+ RSI50-60",
            "line_strategy": "m5_reversal_peakdir_allcount",
            "target_count": 1,
            "strength_range": (5, 10),
            "target_core_count": 1,
            "core_strength_range": (5, 10),
            "target_h1_same_side": False,
            "h1_distance_range": (15, None),
            "target_h1_blocks": True,
            "rsi_range": (50, 60),
            "target_side": "lower",
            "target_peak_dir": -1,
        },
        {
            "label": "Top4 lower reversal c1 str0-5 H1same3-6 RSI30-40",
            "line_strategy": "m5_reversal_peakdir_allcount",
            "target_count": 1,
            "strength_range": (0, 5),
            "target_core_count": 1,
            "core_strength_range": (0, 5),
            "target_h1_same_side": True,
            "h1_distance_range": (3, 6),
            "target_h1_blocks": True,
            "rsi_range": (30, 40),
            "target_side": "lower",
            "target_peak_dir": -1,
        },
        {
            "label": "Top5 lower reversal c1 str0-5 H1same3-6 noBlock RSI40-50",
            "line_strategy": "m5_reversal_peakdir_allcount",
            "target_count": 1,
            "strength_range": (0, 5),
            "target_core_count": 1,
            "core_strength_range": (0, 5),
            "target_h1_same_side": True,
            "h1_distance_range": (3, 6),
            "target_h1_blocks": False,
            "rsi_range": (40, 50),
            "target_side": "lower",
            "target_peak_dir": -1,
        },
        {
            "label": "Top6 lower breakout c1 str0-5 H1same3-6 RSI40-50",
            "line_strategy": "m5_breakout_peakdir_allcount",
            "target_count": 1,
            "strength_range": (0, 5),
            "target_core_count": 1,
            "core_strength_range": (0, 5),
            "target_h1_same_side": True,
            "h1_distance_range": (3, 6),
            "target_h1_blocks": True,
            "rsi_range": (40, 50),
            "target_side": "lower",
            "target_peak_dir": -1,
        },
        {
            "label": "Top7 lower reversal c1 str0-5 H1same6-10 RSI40-50",
            "line_strategy": "m5_reversal_peakdir_allcount",
            "target_count": 1,
            "strength_range": (0, 5),
            "target_core_count": 1,
            "core_strength_range": (0, 5),
            "target_h1_same_side": True,
            "h1_distance_range": (6, 10),
            "target_h1_blocks": True,
            "rsi_range": (40, 50),
            "target_side": "lower",
            "target_peak_dir": -1,
        },
    ]

    session_policies = {
        "morning": {
            "order_permission": True,
            "units_multiplier": 1.0,
            "rr": 1.3,
            "tp_multiplier": 1.0,
            "lc_multiplier": 1.0,
        },
        "day": {
            "order_permission": True,
            "units_multiplier": 1.0,
            "rr": None,
            "tp_multiplier": 1.0,
            "lc_multiplier": 1.0,
        },
        "night": {
            "order_permission": True,
            "units_multiplier": 1.0,
            "rr": None,
            "tp_multiplier": 1.0,
            "lc_multiplier": 1.0,
        },
    }

    def is_h1_reversal_target(self, line_side, line):
        is_flipped = line.get("is_flipped_line")
        core_count = int(line.get("core_count") or 0)
        core_total_strength = float(line.get("core_total_strength") or 0)
        return (
            is_flipped is False
            and line_side in ("upper", "lower")
            and core_count >= self.h1_core_count_min
            and core_total_strength >= self.h1_core_total_strength_min
        )

    def is_m5_reversal_target(self, line_side, line):
        is_flipped = line.get("is_flipped_line")
        count = int(line.get("count") or 0)
        core_count = int(line.get("core_count") or 0)
        core_total_strength = float(line.get("core_total_strength") or 0)
        return (
            is_flipped is False
            and line_side in ("upper", "lower")
            and count >= self.m5_count_min
            and core_count >= self.m5_core_count_min
            and core_total_strength >= self.m5_core_total_strength_min
        )

    def limit_recommended_reasons(self, candidate, rsi_info, latest_peak_info):
        return self.recommended_reasons(candidate, rsi_info, latest_peak_info)

    def recommended_reasons(self, candidate, rsi_info, latest_peak_info):
        """USD_JPY用のライン候補採用条件。現状はTOP7条件で選別する。"""
        line_side = candidate["line_side"]
        latest_peak_dir = latest_peak_info["direction"]
        if latest_peak_dir == 1 and line_side != "upper":
            return []
        if latest_peak_dir == -1 and line_side != "lower":
            return []
        if not self._reversal_peak_rsi_matches_direction(candidate):
            return []

        top10_reasons = self._configured_top10_reasons(candidate, rsi_info)
        if top10_reasons:
            return top10_reasons
        return []

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
        h1_same_side = h1_side == line_side

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
            self.top7_conditions,
        )

    def _configured_top10_reasons(self, candidate, rsi_info):
        if not self._reversal_peak_rsi_matches_direction(candidate):
            return []
        reasons = []
        for condition in getattr(self, "top10_conditions", []):
            if self._is_top10_condition(candidate, rsi_info, condition):
                reasons.append(condition["label"])
        return reasons

    def immediate_recommended_reasons(self, candidate, rsi_info, latest_peak_info):
        """Select market entries only when a nearby line looks likely to break."""
        distance_pips = candidate.get("line_distance_pips", candidate.get("distance_pips"))
        try:
            distance_pips = float(distance_pips)
        except (TypeError, ValueError):
            return []
        if distance_pips > self.immediate_near_line_max_pips:
            return []

        breakout_reason = self._immediate_breakout_context(candidate, latest_peak_info)
        if breakout_reason is None:
            return []

        if not self._current_rsi_matches_direction(candidate, rsi_info):
            return []

        previous_peak_reason = self._immediate_previous_peak_supports(candidate)
        if previous_peak_reason is None:
            return []

        line_history_reason = self._immediate_line_history_supports(candidate)
        if line_history_reason is None:
            return []

        peak_rsi_reason = self._immediate_peak_rsi_supports_direction(candidate)
        if peak_rsi_reason is None:
            return []

        h1_context = candidate.get("h1_context", {})
        path_distance = h1_context.get("h1_path_ahead_1_distance_pips")
        path_strength = h1_context.get("h1_path_ahead_1_total_strength")
        if self._immediate_path_is_blocked(path_distance, path_strength):
            return []

        reasons = [
            "Immediate strict RSI direction",
            breakout_reason,
            previous_peak_reason,
            line_history_reason,
            peak_rsi_reason,
        ]
        if path_distance is not None:
            reasons.append("H1 path ahead " + str(round(float(path_distance), 1)) + "p")
        return reasons

    def _immediate_breakout_context(self, candidate, latest_peak_info):
        strategy = candidate.get("strategy")
        if getattr(strategy, "entry_type", None) != "breakout":
            return None

        direction = int(candidate.get("direction") or 0)
        line_side = candidate.get("line_side")
        latest_peak_dir = latest_peak_info.get("direction")
        if direction == 1 and line_side != "upper":
            return None
        if direction == -1 and line_side != "lower":
            return None
        if latest_peak_dir != direction:
            return None

        line = candidate.get("line", {})
        if line.get("is_flipped_line") is True:
            return None

        role_reason = self._immediate_line_role_supports_breakout(candidate)
        if role_reason is None:
            return None

        latest_touch_dir = line.get("line_latest_touch_peak_dir")
        if latest_touch_dir is not None:
            try:
                latest_touch_dir = int(float(latest_touch_dir))
            except (TypeError, ValueError):
                latest_touch_dir = None
            if latest_touch_dir is not None and latest_touch_dir != direction:
                return None

        distance_pips = candidate.get("line_distance_pips", candidate.get("distance_pips"))
        try:
            distance_text = str(round(float(distance_pips), 1))
        except (TypeError, ValueError):
            distance_text = str(distance_pips)
        return "Near breakout " + role_reason + " " + distance_text + "p"

    @staticmethod
    def _immediate_line_role_supports_breakout(candidate):
        direction = int(candidate.get("direction") or 0)
        line = candidate.get("line", {})
        current_role = line.get("line_current_role")
        if direction == 1 and current_role == "resistance":
            return "resistance"
        if direction == -1 and current_role == "support":
            return "support"
        return None

    def _current_rsi_matches_direction(self, candidate, rsi_info):
        if rsi_info is None:
            return False
        direction = int(candidate.get("direction") or 0)
        entry_type = getattr(candidate.get("strategy"), "entry_type", None)
        rsi_values = []
        for key in ("rsi_1", "rsi_2", "rsi_3"):
            value = rsi_info.get(key)
            try:
                rsi = float(value)
            except (TypeError, ValueError):
                continue
            if rsi == rsi:
                rsi_values.append(rsi)
        if not rsi_values:
            return False

        rsi_1 = rsi_values[0]
        rsi_2 = rsi_values[1] if len(rsi_values) > 1 else rsi_1
        if entry_type == "breakout":
            if direction == 1:
                return 40 <= rsi_1 <= 67.5 and rsi_1 >= rsi_2
            if direction == -1:
                return 30 <= rsi_1 <= 60 and rsi_1 <= rsi_2
            return False

        if direction == 1:
            return rsi_1 <= 40 or min(rsi_values) <= 30
        if direction == -1:
            return rsi_1 >= 60 or max(rsi_values) >= 67.5
        return False

    def _immediate_previous_peak_supports(self, candidate):
        try:
            strength = float(candidate.get("previous_peak_strength"))
        except (TypeError, ValueError):
            return None
        if strength < self.immediate_previous_peak_strength_min:
            return None
        return "Previous peak strength " + str(round(strength, 1))

    def _immediate_line_history_supports(self, candidate):
        line = candidate.get("line", {})
        try:
            count = int(line.get("count") or 0)
            core_count = int(line.get("core_count") or 0)
            strength = float(line.get("total_strength") or 0)
        except (TypeError, ValueError):
            return None

        has_repeated_touch = count >= self.immediate_line_count_min
        has_core_history = core_count >= self.immediate_line_core_count_min
        has_strong_line = strength >= self.immediate_line_strength_min
        if not (has_repeated_touch or has_core_history or has_strong_line):
            return None

        return (
            "Known line history count="
            + str(count)
            + " core="
            + str(core_count)
            + " strength="
            + str(round(strength, 1))
        )

    def _immediate_peak_rsi_supports_direction(self, candidate):
        if getattr(candidate.get("strategy"), "entry_type", None) == "breakout":
            reason = self._breakout_peak_rsi_supports_direction(candidate)
            if reason is not None:
                return reason
            return self._breakout_line_peak_rsi_supports_direction(candidate)

        peak_reason = self._peak_rsi_supports_direction(candidate)
        if peak_reason is not None:
            return peak_reason

        line_reason = self._line_peak_rsi_supports_direction(candidate)
        if line_reason is not None:
            return line_reason
        return None

    def _immediate_path_is_blocked(self, path_distance, path_strength):
        if path_distance is None or path_strength is None:
            return False
        try:
            path_distance = float(path_distance)
            path_strength = float(path_strength)
        except (TypeError, ValueError):
            return False
        return (
            0 < path_distance < self.immediate_min_path_ahead_pips
            and path_strength >= self.immediate_strong_path_block_strength
        )

    def _line_peak_rsi_supports_direction(self, candidate):
        direction = int(candidate.get("direction") or 0)
        line = candidate.get("line", {})
        rsi_values = []
        for key in ("line_peak_rsi_latest", "line_peak_rsi_avg"):
            value = line.get(key)
            try:
                rsi = float(value)
            except (TypeError, ValueError):
                continue
            if rsi == rsi:
                rsi_values.append(rsi)
        if not rsi_values:
            return None
        if direction == 1 and min(rsi_values) <= 40:
            return "Line peak RSI supports buy"
        if direction == -1 and max(rsi_values) >= 60:
            return "Line peak RSI supports sell"
        return None

    def _peak_rsi_supports_direction(self, candidate):
        direction = int(candidate.get("direction") or 0)
        rsi_values = []
        for key in ("latest_peak_rsi", "previous_peak_rsi"):
            value = candidate.get(key)
            try:
                rsi = float(value)
            except (TypeError, ValueError):
                continue
            if rsi == rsi:
                rsi_values.append(rsi)
        if not rsi_values:
            return None
        if direction == 1 and min(rsi_values) <= 40:
            return "Recent peak RSI supports buy"
        if direction == -1 and max(rsi_values) >= 60:
            return "Recent peak RSI supports sell"
        return None

    def _breakout_peak_rsi_supports_direction(self, candidate):
        direction = int(candidate.get("direction") or 0)
        latest_rsi = self._float_or_none(candidate.get("latest_peak_rsi"))
        previous_rsi = self._float_or_none(candidate.get("previous_peak_rsi"))
        if latest_rsi is None:
            return None
        if direction == 1 and latest_rsi >= 50:
            if previous_rsi is None or latest_rsi >= previous_rsi - 5:
                return "Recent peak RSI supports buy breakout"
        if direction == -1 and latest_rsi <= 50:
            if previous_rsi is None or latest_rsi <= previous_rsi + 5:
                return "Recent peak RSI supports sell breakout"
        return None

    def _breakout_line_peak_rsi_supports_direction(self, candidate):
        direction = int(candidate.get("direction") or 0)
        line = candidate.get("line", {})
        latest_rsi = self._float_or_none(line.get("line_peak_rsi_latest"))
        avg_rsi = self._float_or_none(line.get("line_peak_rsi_avg"))
        if latest_rsi is None and avg_rsi is None:
            return None
        values = [value for value in (latest_rsi, avg_rsi) if value is not None]
        if direction == 1 and max(values) >= 50:
            return "Line peak RSI supports buy breakout"
        if direction == -1 and min(values) <= 50:
            return "Line peak RSI supports sell breakout"
        return None

    @staticmethod
    def _float_or_none(value):
        try:
            result = float(value)
        except (TypeError, ValueError):
            return None
        if result != result:
            return None
        return result

    @staticmethod
    def _reversal_peak_rsi_matches_direction(candidate):
        strategy = candidate.get("strategy")
        if getattr(strategy, "entry_type", None) != "reversal":
            return True
        return LineStrategyProfileUsdJpy._peak_rsi_matches_direction(candidate)

    @staticmethod
    def _peak_rsi_matches_direction(candidate):
        direction = int(candidate.get("direction") or 0)
        peak_rsi_values = []
        for value in (candidate.get("latest_peak_rsi"), candidate.get("previous_peak_rsi")):
            try:
                rsi = float(value)
            except (TypeError, ValueError):
                continue
            if rsi == rsi:
                peak_rsi_values.append(rsi)
        if not peak_rsi_values:
            return False
        if direction == 1:
            return min(peak_rsi_values) <= 30
        if direction == -1:
            return max(peak_rsi_values) >= 67.5
        return False

    def _is_top10_condition(self, candidate, rsi_info, condition):
        filters = condition.get("filters", {})
        return all(
            self._condition_value(candidate, rsi_info, field) == expected
            for field, expected in filters.items()
        )

    def _condition_value(self, candidate, rsi_info, field):
        line = candidate["line"]
        h1_context = candidate.get("h1_context", {})
        if field == "line_side":
            return candidate.get("line_side")
        if field == "direction_label":
            return "buy" if int(candidate.get("direction") or 0) == 1 else "sell"
        if field == "line_strategy":
            return candidate.get("line_strategy")
        if field == "line_entry_type":
            strategy = candidate.get("strategy")
            return getattr(strategy, "entry_type", None)
        if field == "session_bucket":
            return self._session_bucket(candidate.get("session_hour"))
        if field == "distance_bin":
            return self._pips_bin(candidate.get("distance_pips"))
        if field == "path1_distance_bin":
            return self._path_distance_bin(h1_context.get("h1_path_ahead_1_distance_pips"))
        if field == "line_strength_bin":
            return self._strength_bin(line.get("total_strength"))
        if field == "core_strength_bin":
            return self._strength_bin(line.get("core_total_strength"))
        if field == "path1_strength_bin":
            return self._strength_bin(h1_context.get("h1_path_ahead_1_total_strength"))
        if field == "h1_nearest_strength_bin":
            return self._strength_bin(h1_context.get("h1_nearest_total_strength"))
        if field == "previous_m5_strength_bin":
            return self._strength_bin(h1_context.get("m5_previous_peak_line_total_strength"))
        if field == "previous_h1_strength_bin":
            return self._strength_bin(h1_context.get("h1_previous_peak_line_total_strength"))
        if field == "m5_rsi_bin":
            return self._rsi_bin(None if rsi_info is None else rsi_info.get("rsi_1"))
        if field == "h1_rsi_bin":
            return self._rsi_bin(None if rsi_info is None else rsi_info.get("h1_rsi_1"))
        if field == "latest_peak_rsi_bin":
            return self._rsi_bin(candidate.get("latest_peak_rsi"))
        if field == "previous_peak_rsi_bin":
            return self._rsi_bin(candidate.get("previous_peak_rsi"))
        if field == "line_peak_rsi_latest_bin":
            return self._rsi_bin(line.get("line_peak_rsi_latest"))
        if field == "line_peak_rsi_avg_bin":
            return self._rsi_bin(line.get("line_peak_rsi_avg"))
        if field == "peak_rsi_direction_ok":
            return self._peak_rsi_matches_direction(candidate)
        if field == "role_change":
            return bool(line.get("line_history_is_flipped"))
        if field == "role_pair":
            return str(line.get("line_origin_role")) + "->" + str(line.get("line_current_role"))
        if field == "line_current_role":
            return line.get("line_current_role")
        return None

    @staticmethod
    def _bin_value(value, bins):
        if value is None:
            return None
        try:
            value = float(value)
        except (TypeError, ValueError):
            return None
        for low, high, label in bins:
            if value > low and value <= high:
                return label
        return None

    @classmethod
    def _pips_bin(cls, value):
        return cls._bin_value(value, [
            (-0.1, 3, "0-3p"),
            (3, 5, "3-5p"),
            (5, 8, "5-8p"),
            (8, 10, "8-10p"),
            (10, 15, "10-15p"),
            (15, 20, "15-20p"),
            (20, 30, "20-30p"),
            (30, 999999, "30p+"),
        ])

    @classmethod
    def _path_distance_bin(cls, value):
        return cls._bin_value(value, [
            (-0.1, 3, "0-3p"),
            (3, 6, "3-6p"),
            (6, 10, "6-10p"),
            (10, 15, "10-15p"),
            (15, 20, "15-20p"),
            (20, 30, "20-30p"),
            (30, 50, "30-50p"),
            (50, 999999, "50+p"),
        ])

    @classmethod
    def _strength_bin(cls, value):
        return cls._bin_value(value, [
            (-0.1, 5, "0-5"),
            (5, 8, "5-8"),
            (8, 10, "8-10"),
            (10, 15, "10-15"),
            (15, 20, "15-20"),
            (20, 999999, "20+"),
        ])

    @classmethod
    def _rsi_bin(cls, value):
        return cls._bin_value(value, [
            (-0.1, 30, "<=30"),
            (30, 40, "30-40"),
            (40, 50, "40-50"),
            (50, 60, "50-60"),
            (60, 67.5, "60-67.5"),
            (67.5, 100, "67.5+"),
        ])

    @staticmethod
    def _session_bucket(hour):
        if hour is None:
            return None
        try:
            hour = int(hour)
        except (TypeError, ValueError):
            return None
        if 0 <= hour <= 5:
            return "00-05"
        if 6 <= hour <= 8:
            return "06-08"
        if 9 <= hour <= 14:
            return "09-14"
        if 15 <= hour <= 20:
            return "15-20"
        if 21 <= hour <= 23:
            return "21-23"
        return None

    def _configured_top7_reasons(
        self,
        candidate,
        count,
        strength,
        core_count,
        core_strength,
        h1_same_side,
        h1_distance,
        h1_blocks,
        rsi_1,
        top7_conditions,
    ):
        reasons = []
        for condition in top7_conditions:
            if self._is_top7_condition(
                candidate,
                count,
                strength,
                core_count,
                core_strength,
                h1_same_side,
                h1_distance,
                h1_blocks,
                rsi_1,
                condition["line_strategy"],
                condition["target_count"],
                condition["strength_range"],
                condition["target_core_count"],
                condition["core_strength_range"],
                condition["target_h1_same_side"],
                condition["h1_distance_range"],
                condition["target_h1_blocks"],
                condition["rsi_range"],
                condition.get("target_side", "upper"),
                condition.get("target_peak_dir", 1),
            ):
                reasons.append(condition["label"])
        return reasons

    @staticmethod
    def _is_top7_condition(
        candidate,
        count,
        strength,
        core_count,
        core_strength,
        h1_same_side,
        h1_distance,
        h1_blocks,
        rsi_1,
        line_strategy,
        target_count,
        strength_range,
        target_core_count,
        core_strength_range,
        target_h1_same_side,
        h1_distance_range,
        target_h1_blocks,
        rsi_range,
        target_side="upper",
        target_peak_dir=1,
    ):
        if candidate["line_strategy"] != line_strategy:
            return False
        if candidate["line_side"] != target_side:
            return False
        if candidate.get("latest_peak_dir") != target_peak_dir:
            return False
        if count != target_count:
            return False
        if core_count != target_core_count:
            return False
        if h1_same_side != target_h1_same_side:
            return False
        if bool(h1_blocks) != target_h1_blocks:
            return False
        if h1_distance is None or rsi_1 is None:
            return False

        return (
            LineStrategyProfileUsdJpy._in_range(strength, strength_range)
            and LineStrategyProfileUsdJpy._in_range(core_strength, core_strength_range)
            and LineStrategyProfileUsdJpy._in_range(float(h1_distance), h1_distance_range)
            and LineStrategyProfileUsdJpy._in_range(float(rsi_1), rsi_range)
        )

    @staticmethod
    def _in_range(value, value_range):
        low, high = value_range
        if low is not None and value < low:
            return False
        if high is not None and value > high:
            return False
        return True

    def create_orders_from_lines(
        self,
        analysis,
        line_class_m5_l,
        line_class_m5_s,
        line_class_h1_l,
        line_class_h1_s,
        current_price,
        decision_time,
        rsi_info,
    ):
        line_context = self.calculate_line_strength(
            analysis,
            line_class_m5_l,
            line_class_m5_s,
            line_class_h1_l,
            line_class_h1_s,
            current_price,
            decision_time,
            rsi_info,
        )
        grouped_lines = self.group_lines(line_context)

        immediate_orders = self.immediate_order(grouped_lines)
        if immediate_orders:
            return immediate_orders

        future_orders = self.future_line_order(grouped_lines)
        return future_orders

    def calculate_line_strength(
        self,
        analysis,
        line_class_m5_l,
        line_class_m5_s,
        line_class_h1_l,
        line_class_h1_s,
        current_price,
        decision_time,
        rsi_info,
    ):
        return {
            "analysis": analysis,
            "coordinator": analysis.line_order_coordinator(),
            "line_class_m5_main": line_class_m5_l,
            "line_class_m5_sub": line_class_m5_s,
            "line_class_h1_main": line_class_h1_l,
            "line_class_h1_sub": line_class_h1_s,
            "current_price": current_price,
            "decision_time": decision_time,
            "rsi_info": rsi_info,
        }

    def group_lines(self, line_context):
        coordinator = line_context["coordinator"]
        current_price = line_context["current_price"]
        m5_line_class = line_context["line_class_m5_main"]
        h1_line_class = line_context["line_class_h1_main"]

        resist_strategy_lines = [
            (UsdJpyM5LineOrderStrategy(self), m5_line_class),
        ]
        break_strategy_lines = [
            (UsdJpyM5BreakoutLineOrderStrategy(self), m5_line_class),
        ]

        line_context["immediate_candidates"] = coordinator.build_line_candidates(
            break_strategy_lines,
            current_price,
            h1_line_class=h1_line_class,
            m5_line_class=m5_line_class,
            order_mode="immediate",
        )
        line_context["future_resist_candidates"] = coordinator.build_line_candidates(
            resist_strategy_lines,
            current_price,
            h1_line_class=h1_line_class,
            m5_line_class=m5_line_class,
            order_mode="limit",
        )
        line_context["future_break_candidates"] = coordinator.build_line_candidates(
            break_strategy_lines,
            current_price,
            h1_line_class=h1_line_class,
            m5_line_class=m5_line_class,
            order_mode="limit",
        )
        self.evaluate_grouped_line_behavior(line_context)
        return line_context

    def evaluate_grouped_line_behavior(self, line_context):
        """Attach reusable break/resist evidence to each grouped M5 line."""
        coordinator = line_context["coordinator"]
        rsi_info = line_context.get("rsi_info") or {}
        decision_time = line_context.get("decision_time")
        evaluated = {}
        evaluated_line_groups = []

        for candidate_key in (
            "immediate_candidates",
            "future_resist_candidates",
            "future_break_candidates",
        ):
            for candidate in line_context.get(candidate_key, []):
                line = candidate.get("line", {})
                line_key = (id(line), candidate.get("line_side"))
                evaluation = evaluated.get(line_key)
                if evaluation is None:
                    latest_peak_info = coordinator.attach_candidate_decision_context(
                        candidate,
                        decision_time,
                        "line_group",
                    )
                    evaluation = self.evaluate_line_behavior(
                        candidate,
                        rsi_info,
                        latest_peak_info,
                    )
                    evaluated[line_key] = evaluation
                    line.update(evaluation)
                    evaluated_line_groups.append({
                        "timeframe": candidate.get("timeframe"),
                        "line_side": candidate.get("line_side"),
                        "line_price": candidate.get("line_price"),
                        "line": line,
                        **evaluation,
                    })
                candidate.update({
                    "line_behavior": evaluation["behavior"],
                    "line_break_score": evaluation["break_score"],
                    "line_resist_score": evaluation["resist_score"],
                    "line_behavior_reasons": evaluation["behavior_reasons"],
                    "line_break_reasons": evaluation["break_reasons"],
                    "line_resist_reasons": evaluation["resist_reasons"],
                })

        line_context["evaluated_line_groups"] = evaluated_line_groups

    def evaluate_line_behavior(self, candidate, rsi_info, latest_peak_info):
        """Score whether the approaching price is more likely to break or resist."""
        line = candidate.get("line", {})
        line_side = candidate.get("line_side")
        approach_direction = 1 if line_side == "upper" else -1
        break_points = 1.0
        resist_points = 1.0
        break_reasons = []
        resist_reasons = []

        def add_break(points, reason):
            nonlocal break_points
            break_points += points
            break_reasons.append(reason)

        def add_resist(points, reason):
            nonlocal resist_points
            resist_points += points
            resist_reasons.append(reason)

        latest_peak_dir = self._int_or_none(latest_peak_info.get("direction"))
        if latest_peak_dir == approach_direction:
            add_break(2.0, "Latest peak direction approaches line")
        elif latest_peak_dir in (-1, 1):
            add_resist(2.0, "Latest peak direction moves away from line")

        current_rsi = self._float_or_none(rsi_info.get("rsi_1"))
        previous_rsi = self._float_or_none(latest_peak_info.get("previous_rsi"))
        if current_rsi is not None:
            if line_side == "upper":
                if 50 <= current_rsi <= 67.5:
                    add_break(1.0, "Current RSI supports upper approach")
                else:
                    add_resist(1.0, "Current RSI does not support upper approach")
            elif line_side == "lower":
                if 30 <= current_rsi <= 50:
                    add_break(1.0, "Current RSI supports lower approach")
                else:
                    add_resist(1.0, "Current RSI does not support lower approach")

        if current_rsi is not None and previous_rsi is not None:
            rsi_change = current_rsi - previous_rsi
            directional_change = rsi_change * approach_direction
            if directional_change >= 3:
                add_break(1.5, "RSI momentum strengthened toward line")
            elif directional_change <= -3:
                add_resist(1.5, "RSI momentum weakened before line")

        if line.get("line_history_is_flipped") is True:
            add_break(1.0, "Line role has flipped before")
        elif line.get("line_current_role") in ("resistance", "support"):
            add_resist(0.5, "Line keeps its original role")

        line_count = self._int_or_none(line.get("count")) or 0
        line_strength = self._float_or_none(line.get("total_strength")) or 0
        if line_count >= 3:
            add_break(0.5, "Repeated line tests may weaken line")
        if line_strength >= 10:
            add_resist(0.5, "Line has strong accumulated resistance")

        line_rsi_values = [
            self._float_or_none(line.get("line_peak_rsi_latest")),
            self._float_or_none(line.get("line_peak_rsi_avg")),
        ]
        line_rsi_values = [value for value in line_rsi_values if value is not None]
        if line_side == "upper" and any(value >= 67.5 for value in line_rsi_values):
            add_resist(1.0, "Line was formed with high RSI")
        if line_side == "lower" and any(value <= 30 for value in line_rsi_values):
            add_resist(1.0, "Line was formed with low RSI")

        total_points = break_points + resist_points
        break_score = round(break_points / total_points, 3)
        resist_score = round(resist_points / total_points, 3)
        score_gap = break_score - resist_score
        if score_gap >= 0.1:
            behavior = "break"
            behavior_reasons = list(break_reasons)
        elif score_gap <= -0.1:
            behavior = "resist"
            behavior_reasons = list(resist_reasons)
        else:
            behavior = "neutral"
            behavior_reasons = [
                "Break: " + reason for reason in break_reasons
            ] + [
                "Resist: " + reason for reason in resist_reasons
            ]

        return {
            "behavior": behavior,
            "break_score": break_score,
            "resist_score": resist_score,
            "behavior_reasons": behavior_reasons,
            "break_reasons": break_reasons,
            "resist_reasons": resist_reasons,
        }

    @staticmethod
    def _int_or_none(value):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None

    def immediate_order(self, grouped_lines):
        coordinator = grouped_lines["coordinator"]
        candidates = coordinator.select_line_candidates(
            grouped_lines["immediate_candidates"],
            grouped_lines["rsi_info"],
            grouped_lines["decision_time"],
            "immediate",
            self.immediate_recommended_reasons,
        )
        return coordinator.create_orders_from_candidates(
            candidates,
            grouped_lines["current_price"],
            grouped_lines["decision_time"],
            grouped_lines["rsi_info"],
            "immediate",
        )

    def future_line_order(self, grouped_lines):
        resist_orders = self.future_resist_order(grouped_lines)
        break_orders = self.future_break_order(grouped_lines)
        return resist_orders + break_orders

    def future_resist_order(self, grouped_lines):
        coordinator = grouped_lines["coordinator"]
        candidates = coordinator.select_line_candidates(
            grouped_lines["future_resist_candidates"],
            grouped_lines["rsi_info"],
            grouped_lines["decision_time"],
            "future_resist",
            self.future_resist_recommended_reasons,
        )
        return coordinator.create_orders_from_candidates(
            candidates,
            grouped_lines["current_price"],
            grouped_lines["decision_time"],
            grouped_lines["rsi_info"],
            "limit",
        )

    def future_break_order(self, grouped_lines):
        coordinator = grouped_lines["coordinator"]
        candidates = coordinator.select_line_candidates(
            grouped_lines["future_break_candidates"],
            grouped_lines["rsi_info"],
            grouped_lines["decision_time"],
            "future_break",
            self.future_break_recommended_reasons,
        )
        return coordinator.create_orders_from_candidates(
            candidates,
            grouped_lines["current_price"],
            grouped_lines["decision_time"],
            grouped_lines["rsi_info"],
            "limit",
        )

    def future_resist_recommended_reasons(self, candidate, rsi_info, latest_peak_info):
        strategy = candidate.get("strategy")
        if getattr(strategy, "entry_type", None) != "reversal":
            return []
        return self.limit_recommended_reasons(candidate, rsi_info, latest_peak_info)

    def future_break_recommended_reasons(self, candidate, rsi_info, latest_peak_info):
        strategy = candidate.get("strategy")
        if getattr(strategy, "entry_type", None) != "breakout":
            return []
        if not self._future_break_direction_is_valid(candidate, latest_peak_info):
            return []
        return self._configured_top10_reasons(candidate, rsi_info)

    @staticmethod
    def _future_break_direction_is_valid(candidate, latest_peak_info):
        direction = int(candidate.get("direction") or 0)
        line_side = candidate.get("line_side")
        latest_peak_dir = latest_peak_info.get("direction")
        if direction == 1 and line_side != "upper":
            return False
        if direction == -1 and line_side != "lower":
            return False
        return latest_peak_dir == direction


class UsdJpyLineOrderStrategy:
    timeframe = ""
    name_prefix = ""
    line_strategy = ""
    entry_type = ""
    order_type = "LIMIT"
    entry_offset_pips = 0
    lc_pips = 0
    tp_pips = 0
    units_multiplier = 1
    order_timeout_min = 0

    def __init__(self, profile=None):
        self.profile = profile or LineStrategyProfileUsdJpy()

    def pair_info(self):
        return gene.currency_pair(getattr(self, "pair", "USD_JPY"))

    def is_target(self, line_side, line):
        raise NotImplementedError

    def get_tp_pips(self):
        return self.tp_pips

    def get_direction(self, line_side):
        return -1 if line_side == "upper" else 1

    def get_target_price(self, line_price, line_side):
        return line_price

    def build_candidates(self, line_class, current_price):
        self.pair = getattr(line_class, "pair", getattr(self, "pair", "USD_JPY"))
        p = self.pair_info()
        candidates = []
        for line_side, lines in (
            ("upper", line_class.upper_lines),
            ("lower", line_class.lower_lines),
        ):
            for line_index, line in enumerate(lines):
                if not self.is_target(line_side, line):
                    continue

                line_price = p.round_price(line["median_price"])
                target_price = p.round_price(
                    self.get_target_price(line_price, line_side)
                )
                if line_side == "upper" and target_price <= float(current_price):
                    continue
                if line_side == "lower" and target_price >= float(current_price):
                    continue
                candidates.append({
                    "timeframe": self.timeframe,
                    "line_side": line_side,
                    "direction": self.get_direction(line_side),
                    "line": line,
                    "line_index": line_index,
                    "line_price": line_price,
                    "target_price": target_price,
                    "line_strategy": self.line_strategy,
                    "distance_pips": abs(
                        p.price_to_pips(float(current_price) - float(target_price))
                    ),
                    "strategy": self,
                })
        return candidates


class UsdJpyH1LineOrderStrategy(UsdJpyLineOrderStrategy):
    timeframe = "h1"
    name_prefix = "H1LineLimit"
    line_strategy = "h1_reversal_peakdir_allcount"
    entry_type = "reversal"
    order_type = "LIMIT"
    lc_pips = 15
    units_multiplier = 0.5
    order_timeout_min = 60

    def __init__(self, profile=None):
        super().__init__(profile)
        self.lc_pips = self.profile.h1_lc_pips
        self.units_multiplier = self.profile.h1_units_multiplier
        self.order_timeout_min = self.profile.h1_order_timeout_min

    def get_tp_pips(self):
        spread_pips = self.profile.h1_spread_pips
        rr = self.profile.h1_rr
        return round(rr * (self.lc_pips + spread_pips) + spread_pips, 1)

    def is_target(self, line_side, line):
        return self.profile.is_h1_reversal_target(line_side, line)


class UsdJpyM5LineOrderStrategy(UsdJpyLineOrderStrategy):
    timeframe = "m5"
    name_prefix = "M5LineReversal"
    line_strategy = "m5_reversal_peakdir_allcount"
    entry_type = "reversal"
    order_type = "LIMIT"
    lc_pips = 7.5
    tp_pips = 14.1
    units_multiplier = 0.25
    order_timeout_min = 15

    def __init__(self, profile=None):
        super().__init__(profile)
        self.lc_pips = self.profile.m5_lc_pips
        self.tp_pips = self.profile.m5_tp_pips
        self.units_multiplier = self.profile.m5_units_multiplier
        self.order_timeout_min = self.profile.m5_order_timeout_min

    def is_target(self, line_side, line):
        return self.profile.is_m5_reversal_target(line_side, line)


class UsdJpyM5BreakoutLineOrderStrategy(UsdJpyM5LineOrderStrategy):
    name_prefix = "M5LineBreakout"
    line_strategy = "m5_breakout_peakdir_allcount"
    entry_type = "breakout"
    order_type = "STOP"
    entry_offset_pips = 1.5

    def __init__(self, profile=None):
        super().__init__(profile)
        self.entry_offset_pips = self.profile.m5_breakout_entry_offset_pips

    def get_direction(self, line_side):
        return 1 if line_side == "upper" else -1

    def get_target_price(self, line_price, line_side):
        p = self.pair_info()
        direction = self.get_direction(line_side)
        return line_price + (
            direction * p.pips_to_price(self.entry_offset_pips)
        )


H1LineOrderStrategy = UsdJpyH1LineOrderStrategy
M5LineOrderStrategy = UsdJpyM5LineOrderStrategy
M5BreakoutLineOrderStrategy = UsdJpyM5BreakoutLineOrderStrategy
