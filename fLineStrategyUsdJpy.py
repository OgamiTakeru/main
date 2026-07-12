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

    def recommended_reasons(self, candidate, rsi_info, latest_peak_info):
        """USD_JPY用のライン候補採用条件。現状はTOP7条件で選別する。"""
        line_side = candidate["line_side"]
        latest_peak_dir = latest_peak_info["direction"]
        if latest_peak_dir == 1 and line_side != "upper":
            return []
        if latest_peak_dir == -1 and line_side != "lower":
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
        reasons = []
        for condition in getattr(self, "top10_conditions", []):
            if self._is_top10_condition(candidate, rsi_info, condition):
                reasons.append(condition["label"])
        return reasons

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
        return analysis.create_line_orders_from_strategy_lines(
            [
                (UsdJpyM5LineOrderStrategy(self), line_class_m5_l),
                (UsdJpyM5BreakoutLineOrderStrategy(self), line_class_m5_l),
            ],
            current_price,
            decision_time,
            rsi_info,
            h1_line_class=line_class_h1_l,
            m5_line_class=line_class_m5_l,
        )


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
