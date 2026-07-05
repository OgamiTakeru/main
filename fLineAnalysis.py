import copy

import fGeneric as gene
import sys
from pympler import asizeof
import pandas as pd
import classCandleAnalysis as ca
import classOrderCreate as OCreate
import tokens as tk
from datetime import datetime, timedelta
import requests
from statistics import median
from collections import defaultdict
import math
import statistics
from collections import Counter

this_file_line_send = False
gl_previous_exe_df60_row = None
gl_previous_exe_df60_order_time = None
gl_previous_bb_h1_class = None
gl_latest_trend_trigger_time = None

gl_unis_std = 0.1  # OrderCreate縺ｮ繝吶・繧ｷ繝・けUnit縺ｯ10000繝峨Ν縲ゅ◎繧後↓縺九￠繧句咲紫

class LineStrategyConfigBase:
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
    top7_conditions = (
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
            "target_side": "upper",
            "target_peak_dir": 1,
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
            "target_side": "upper",
            "target_peak_dir": 1,
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
            "target_side": "upper",
            "target_peak_dir": 1,
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
            "target_side": "upper",
            "target_peak_dir": 1,
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
            "target_side": "upper",
            "target_peak_dir": 1,
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
            "target_side": "upper",
            "target_peak_dir": 1,
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
            "target_side": "upper",
            "target_peak_dir": 1,
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
    )


class LineStrategyConfigUsdJpy(LineStrategyConfigBase):
    pair = "USD_JPY"


class LineStrategyConfigEurUsd(LineStrategyConfigBase):
    pair = "EUR_USD"


def line_strategy_config(pair):
    if pair == "EUR_USD":
        return LineStrategyConfigEurUsd()
    return LineStrategyConfigUsdJpy()


class LineOrderStrategy:
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

    def __init__(self, config=None):
        self.config = config or LineStrategyConfigUsdJpy()

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


class H1LineOrderStrategy(LineOrderStrategy):
    timeframe = "h1"
    name_prefix = "H1LineLimit"
    line_strategy = "h1_reversal_peakdir_allcount"
    entry_type = "reversal"
    order_type = "LIMIT"
    lc_pips = 15
    units_multiplier = 0.5
    order_timeout_min = 60

    def __init__(self, config=None):
        super().__init__(config)
        self.lc_pips = self.config.h1_lc_pips
        self.units_multiplier = self.config.h1_units_multiplier
        self.order_timeout_min = self.config.h1_order_timeout_min

    def get_tp_pips(self):
        spread_pips = self.config.h1_spread_pips
        rr = self.config.h1_rr
        return round(rr * (self.lc_pips + spread_pips) + spread_pips, 1)

    def is_target(self, line_side, line):
        is_flipped = line.get("is_flipped_line")
        core_count = int(line.get("core_count") or 0)
        core_total_strength = float(line.get("core_total_strength") or 0)
        return (
            is_flipped is False
            and line_side in ("upper", "lower")
            and core_count >= self.config.h1_core_count_min
            and core_total_strength >= self.config.h1_core_total_strength_min
        )


class M5LineOrderStrategy(LineOrderStrategy):
    timeframe = "m5"
    name_prefix = "M5LineReversal"
    line_strategy = "m5_reversal_peakdir_allcount"
    entry_type = "reversal"
    order_type = "LIMIT"
    lc_pips = 7.5
    tp_pips = 14.1
    units_multiplier = 0.25
    order_timeout_min = 15

    def __init__(self, config=None):
        super().__init__(config)
        self.lc_pips = self.config.m5_lc_pips
        self.tp_pips = self.config.m5_tp_pips
        self.units_multiplier = self.config.m5_units_multiplier
        self.order_timeout_min = self.config.m5_order_timeout_min

    def is_target(self, line_side, line):
        is_flipped = line.get("is_flipped_line")
        count = int(line.get("count") or 0)
        core_count = int(line.get("core_count") or 0)
        core_total_strength = float(line.get("core_total_strength") or 0)
        return (
            is_flipped is False
            and line_side in ("upper", "lower")
            and count >= self.config.m5_count_min
            and core_count >= self.config.m5_core_count_min
            and core_total_strength >= self.config.m5_core_total_strength_min
        )


class M5BreakoutLineOrderStrategy(M5LineOrderStrategy):
    name_prefix = "M5LineBreakout"
    line_strategy = "m5_breakout_peakdir_allcount"
    entry_type = "breakout"
    order_type = "STOP"
    entry_offset_pips = 1.5

    def __init__(self, config=None):
        super().__init__(config)
        self.entry_offset_pips = self.config.m5_breakout_entry_offset_pips

    def get_direction(self, line_side):
        return 1 if line_side == "upper" else -1

    def get_target_price(self, line_price, line_side):
        p = self.pair_info()
        direction = self.get_direction(line_side)
        return line_price + (
            direction * p.pips_to_price(self.entry_offset_pips)
        )


class LineOrderCoordinator:
    duplicate_threshold_pips = 3
    h1_strong_threshold = 10

    def __init__(self, analysis):
        self.analysis = analysis
        self.pair = getattr(analysis, "pair", "USD_JPY")
        self.p = gene.currency_pair(self.pair)
        self.config = getattr(analysis, "line_strategy_config", line_strategy_config(self.pair))
        self.duplicate_threshold_pips = self.config.duplicate_threshold_pips
        self.h1_strong_threshold = self.config.h1_strong_threshold

    def create_orders(
        self,
        strategy_lines,
        current_price,
        decision_time,
        rsi_info=None,
        h1_line_class=None,
    ):
        candidates = []
        for strategy, line_class in strategy_lines:
            strategy.pair = self.pair
            candidates.extend(strategy.build_candidates(line_class, current_price))
        if h1_line_class is not None:
            self._add_h1_context(candidates, h1_line_class)

        candidates = self._filter_recommended_candidates(
            candidates,
            rsi_info,
            decision_time,
        )
        selected_candidates = self._remove_near_candidates(candidates)
        orders = []
        for candidate in selected_candidates:
            if self.analysis.has_similar_order(
                candidate["direction"],
                candidate["target_price"],
                orders,
                self.duplicate_threshold_pips,
                source="line",
                line_strategy=candidate["line_strategy"],
            ):
                print(
                    "Skip similar line order:",
                    candidate["timeframe"],
                    candidate["strategy"].entry_type,
                    candidate["line_side"],
                    candidate["target_price"],
                    "direction",
                    candidate["direction"],
                )
                continue

            order_class = self._create_order(
                candidate,
                selected_candidates,
                current_price,
                decision_time,
                rsi_info,
            )
            order_class = self.adjust_order_by_session(order_class, decision_time)
            if order_class is None:
                continue

            orders.append(order_class)

        if orders:
            timeframe_counts = Counter(
                order.exe_order_plan.get("line_timeframe") for order in orders
            )
            print("Line orders:", dict(timeframe_counts))
            self.analysis.add_order_to_this_class(orders)
        return orders

    def _filter_recommended_candidates(self, candidates, rsi_info, decision_time):
        filtered = []
        for candidate in candidates:
            reasons = self._recommended_reasons(candidate, rsi_info, decision_time)
            if not reasons:
                print(
                    "Skip line order by condition:",
                    candidate["timeframe"],
                    candidate["line_strategy"],
                    candidate["line_side"],
                    candidate["line_price"],
                )
                continue

            candidate["recommended_reasons"] = reasons
            candidate["memo"] = self._build_condition_memo(candidate, rsi_info, reasons)
            filtered.append(candidate)
        return filtered

    def _recommended_reasons(self, candidate, rsi_info, decision_time):
        line_side = candidate["line_side"]
        latest_peak_info = self._latest_peak_info(candidate["timeframe"])
        latest_peak_dir = latest_peak_info["direction"]
        candidate["latest_peak_dir"] = latest_peak_dir
        candidate["latest_peak_count"] = latest_peak_info["count"]
        candidate["latest_peak_gap"] = latest_peak_info["gap"]
        candidate["latest_peak_time"] = latest_peak_info["time"]
        if latest_peak_dir == 1 and line_side != "upper":
            return []
        if latest_peak_dir == -1 and line_side != "lower":
            return []

        if candidate["timeframe"] == "h1":
            return ["H1 peak direction all count"]

        line = candidate["line"]
        h1_context = candidate.get("h1_context", {})
        count = int(line.get("count") or 0)
        strength = float(line.get("total_strength") or 0)
        core_count = int(line.get("core_count") or 0)
        core_strength = float(line.get("core_total_strength") or 0)
        h1_distance = h1_context.get("h1_nearest_distance_pips")
        h1_strength = h1_context.get("h1_nearest_total_strength")
        h1_side = h1_context.get("h1_nearest_side")
        h1_blocks = h1_context.get("h1_blocks_trade_direction")
        rsi_1 = None if rsi_info is None else rsi_info.get("rsi_1")

        h1_is_strong = (
            h1_strength is not None
            and float(h1_strength) >= self.h1_strong_threshold
        )
        h1_same_side = h1_side == line_side

        reasons = []
        top7_conditions = getattr(self.config, "top7_conditions", None)
        if top7_conditions is not None:
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
                top7_conditions,
            )

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
            "m5_reversal_peakdir_allcount",
            2,
            (5, 10),
            2,
            (5, 10),
            True,
            (0, 3),
            True,
            (30, 40),
        ):
            reasons.append("Top1 upper reversal c2 str5-10 core2 H1same0-3 RSI30-40")
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
            "m5_reversal_peakdir_allcount",
            1,
            (0, 5),
            1,
            (0, 5),
            True,
            (6, 10),
            True,
            (50, 60),
        ):
            reasons.append("Top2 upper reversal c1 str0-5 H1same6-10 RSI50-60")
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
            "m5_reversal_peakdir_allcount",
            1,
            (5, 10),
            1,
            (5, 10),
            False,
            (15, None),
            True,
            (50, 60),
        ):
            reasons.append("Top3 upper reversal c1 str5-10 H1far15+ RSI50-60")
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
            "m5_reversal_peakdir_allcount",
            1,
            (0, 5),
            1,
            (0, 5),
            True,
            (3, 6),
            True,
            (30, 40),
        ):
            reasons.append("Top4 upper reversal c1 str0-5 H1same3-6 RSI30-40")
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
            "m5_reversal_peakdir_allcount",
            1,
            (0, 5),
            1,
            (0, 5),
            True,
            (3, 6),
            False,
            (40, 50),
        ):
            reasons.append("Top5 upper reversal c1 str0-5 H1same3-6 noBlock RSI40-50")
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
            "m5_breakout_peakdir_allcount",
            1,
            (0, 5),
            1,
            (0, 5),
            True,
            (3, 6),
            True,
            (40, 50),
        ):
            reasons.append("Top6 upper breakout c1 str0-5 H1same3-6 RSI40-50")
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
            "m5_reversal_peakdir_allcount",
            1,
            (0, 5),
            1,
            (0, 5),
            True,
            (6, 10),
            True,
            (40, 50),
        ):
            reasons.append("Top7 upper reversal c1 str0-5 H1same6-10 RSI40-50")

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
            "m5_reversal_peakdir_allcount",
            2,
            (5, 10),
            2,
            (5, 10),
            True,
            (0, 3),
            True,
            (30, 40),
            "lower",
            -1,
        ):
            reasons.append("Top1 lower reversal c2 str5-10 core2 H1same0-3 RSI30-40")
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
            "m5_reversal_peakdir_allcount",
            1,
            (0, 5),
            1,
            (0, 5),
            True,
            (6, 10),
            True,
            (50, 60),
            "lower",
            -1,
        ):
            reasons.append("Top2 lower reversal c1 str0-5 H1same6-10 RSI50-60")
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
            "m5_reversal_peakdir_allcount",
            1,
            (5, 10),
            1,
            (5, 10),
            False,
            (15, None),
            True,
            (50, 60),
            "lower",
            -1,
        ):
            reasons.append("Top3 lower reversal c1 str5-10 H1far15+ RSI50-60")
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
            "m5_reversal_peakdir_allcount",
            1,
            (0, 5),
            1,
            (0, 5),
            True,
            (3, 6),
            True,
            (30, 40),
            "lower",
            -1,
        ):
            reasons.append("Top4 lower reversal c1 str0-5 H1same3-6 RSI30-40")
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
            "m5_reversal_peakdir_allcount",
            1,
            (0, 5),
            1,
            (0, 5),
            True,
            (3, 6),
            False,
            (40, 50),
            "lower",
            -1,
        ):
            reasons.append("Top5 lower reversal c1 str0-5 H1same3-6 noBlock RSI40-50")
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
            "m5_breakout_peakdir_allcount",
            1,
            (0, 5),
            1,
            (0, 5),
            True,
            (3, 6),
            True,
            (40, 50),
            "lower",
            -1,
        ):
            reasons.append("Top6 lower breakout c1 str0-5 H1same3-6 RSI40-50")
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
            "m5_reversal_peakdir_allcount",
            1,
            (0, 5),
            1,
            (0, 5),
            True,
            (6, 10),
            True,
            (40, 50),
            "lower",
            -1,
        ):
            reasons.append("Top7 lower reversal c1 str0-5 H1same6-10 RSI40-50")

        return reasons

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
            LineOrderCoordinator._in_range(strength, strength_range)
            and LineOrderCoordinator._in_range(core_strength, core_strength_range)
            and LineOrderCoordinator._in_range(float(h1_distance), h1_distance_range)
            and LineOrderCoordinator._in_range(float(rsi_1), rsi_range)
        )

    @staticmethod
    def _in_range(value, value_range):
        low, high = value_range
        if low is not None and value < low:
            return False
        if high is not None and value > high:
            return False
        return True

    def _latest_peak_info(self, timeframe):
        try:
            if timeframe == "h1":
                peaks = self.analysis.peaks_class_hour.peaks_original
            else:
                peaks = self.analysis.peaks_class.peaks_original
            latest_peak = peaks[0]
            return {
                "direction": int(float(latest_peak.get("direction"))),
                "count": int(latest_peak.get("count") or 0),
                "gap": latest_peak.get("gap"),
                "time": latest_peak.get("latest_time_jp"),
            }
        except (AttributeError, IndexError, TypeError, ValueError):
            return {
                "direction": 0,
                "count": 0,
                "gap": None,
                "time": None,
            }

    @staticmethod
    def _build_condition_memo(candidate, rsi_info, reasons):
        line = candidate["line"]
        h1_context = candidate.get("h1_context", {})
        parts = [
            "top7",
            candidate["timeframe"],
            candidate["line_side"],
            candidate["strategy"].entry_type,
            "peak_dir=" + str(candidate.get("latest_peak_dir")),
            "peak_count=" + str(candidate.get("latest_peak_count")),
            "strength=" + str(line.get("total_strength")),
            "count=" + str(line.get("count")),
            "price_gap=" + str(line.get("price_gap")),
            "core_count=" + str(line.get("core_count")),
            "core_strength=" + str(line.get("core_total_strength")),
        ]

        h1_distance = h1_context.get("h1_nearest_distance_pips")
        h1_strength = h1_context.get("h1_nearest_total_strength")
        h1_side = h1_context.get("h1_nearest_side")
        if h1_distance is not None:
            parts.append("H1_near=" + str(round(float(h1_distance), 1)) + "p")
        if h1_strength is not None:
            parts.append("H1_strength=" + str(h1_strength))
        if h1_side is not None:
            parts.append("H1_side=" + str(h1_side))

        if rsi_info is not None and rsi_info.get("rsi_1") is not None:
            parts.append("RSI=" + str(round(float(rsi_info["rsi_1"]), 1)))

        parts.append("reason=" + " / ".join(reasons))
        return "; ".join(parts)

    def _add_h1_context(self, candidates, h1_line_class):
        p = self.p
        h1_lines = []
        for line_side, lines in (
            ("upper", h1_line_class.upper_lines),
            ("lower", h1_line_class.lower_lines),
        ):
            for line in lines:
                h1_lines.append({
                    "side": line_side,
                    "price": p.round_price(line["median_price"]),
                    "line": line,
                })

        for candidate in candidates:
            base_price = float(candidate["line_price"])
            direction = int(candidate["direction"])
            upper_lines = [x for x in h1_lines if x["side"] == "upper"]
            lower_lines = [x for x in h1_lines if x["side"] == "lower"]
            ahead_lines = [
                x
                for x in h1_lines
                if (float(x["price"]) - base_price) * direction > 0
            ]
            behind_lines = [
                x
                for x in h1_lines
                if (float(x["price"]) - base_price) * direction < 0
            ]

            nearest_upper = self._nearest_h1_line(upper_lines, base_price)
            nearest_lower = self._nearest_h1_line(lower_lines, base_price)
            nearest_any = self._nearest_h1_line(h1_lines, base_price)
            nearest_ahead = self._nearest_h1_line(ahead_lines, base_price)
            nearest_behind = self._nearest_h1_line(behind_lines, base_price)

            context = {}
            context.update(self._h1_line_fields("h1_upper", nearest_upper, base_price))
            context.update(self._h1_line_fields("h1_lower", nearest_lower, base_price))
            context.update(self._h1_line_fields("h1_nearest", nearest_any, base_price))
            context.update(self._h1_line_fields("h1_ahead", nearest_ahead, base_price))
            context.update(self._h1_line_fields("h1_behind", nearest_behind, base_price))
            nearest_gap = context.get("h1_nearest_distance_pips")
            context["h1_near_same_line"] = (
                nearest_gap is not None and nearest_gap <= self.duplicate_threshold_pips
            )
            context["h1_blocks_trade_direction"] = (
                context.get("h1_ahead_total_strength") is not None
                and context["h1_ahead_total_strength"] >= 10
            )
            candidate["h1_context"] = context

    @staticmethod
    def _nearest_h1_line(lines, base_price):
        if not lines:
            return None
        return min(lines, key=lambda x: abs(float(x["price"]) - base_price))

    def _h1_line_fields(self, prefix, item, base_price):
        if item is None:
            return {
                prefix + "_side": None,
                prefix + "_price": None,
                prefix + "_distance_pips": None,
                prefix + "_total_strength": None,
                prefix + "_count": None,
                prefix + "_core_total_strength": None,
                prefix + "_is_flipped": None,
            }

        p = self.p
        line = item["line"]
        return {
            prefix + "_side": item["side"],
            prefix + "_price": item["price"],
            prefix + "_distance_pips": abs(
                p.price_to_pips(float(item["price"]) - base_price)
            ),
            prefix + "_total_strength": line.get("total_strength"),
            prefix + "_count": line.get("count"),
            prefix + "_core_total_strength": line.get("core_total_strength"),
            prefix + "_is_flipped": line.get("is_flipped_line"),
        }

    def _remove_near_candidates(self, candidates):
        p = self.p
        selected = []
        for candidate in sorted(candidates, key=lambda x: x["distance_pips"]):
            duplicate = None
            for other in selected:
                if int(other["direction"]) != int(candidate["direction"]):
                    continue
                if other["line_strategy"] != candidate["line_strategy"]:
                    continue
                gap_pips = abs(
                    p.price_to_pips(
                        float(candidate["line_price"]) - float(other["line_price"])
                    )
                )
                if gap_pips <= self.duplicate_threshold_pips:
                    duplicate = (other, gap_pips)
                    break

            if duplicate is None:
                selected.append(candidate)
                continue

            other, gap_pips = duplicate
            print(
                "Skip farther line candidate:",
                candidate["timeframe"],
                candidate["line_side"],
                candidate["line_price"],
                "near",
                other["line_price"],
                "gap_pips",
                round(gap_pips, 1),
            )
        return selected

    def _get_units_multiplier(self, candidate, selected_candidates):
        # Timeframe agreement rules will be added here after M5 validation.
        return candidate["strategy"].units_multiplier

    @staticmethod
    def get_session_info(decision_time):
        dt = pd.to_datetime(decision_time)
        hour = int(dt.hour)

        if 6 <= hour < 12:
            session_name = "morning"
        elif 12 <= hour < 18:
            session_name = "day"
        else:
            session_name = "night"

        return {
            "session_name": session_name,
            "session_hour": hour,
            "session_time": dt.strftime("%Y/%m/%d %H:%M:%S"),
        }

    def session_order_policy(self, session_name):
        policies = self.config.session_policies
        return policies.get(session_name, policies["night"])

    def adjust_order_by_session(self, order_class, decision_time):
        session_info = self.get_session_info(decision_time)
        policy = self.session_order_policy(session_info["session_name"])

        order_plan = order_class.exe_order_plan
        order_plan["session_name"] = session_info["session_name"]
        order_plan["session_hour"] = session_info["session_hour"]
        order_plan["session_time"] = session_info["session_time"]
        order_plan["session_units_multiplier"] = policy["units_multiplier"]
        order_plan["session_rr"] = policy["rr"]
        order_plan["session_tp_multiplier"] = policy["tp_multiplier"]
        order_plan["session_lc_multiplier"] = policy["lc_multiplier"]
        order_plan["session_skip_reason"] = None

        if not policy["order_permission"]:
            order_plan["order_permission"] = False
            order_plan["session_skip_reason"] = "session_order_permission_false"
            print(
                "Skip session order:",
                order_plan.get("name"),
                session_info["session_name"],
            )
            return None

        if policy["units_multiplier"] != 1.0:
            self._apply_units_multiplier(order_class, policy["units_multiplier"])

        if policy["rr"] is not None:
            self._apply_rr_to_tp(order_class, policy["rr"])

        return order_class

    @staticmethod
    def _apply_units_multiplier(order_class, units_multiplier):
        order_plan = order_class.exe_order_plan
        old_units = int(order_plan.get("units") or 0)
        new_units = int(old_units * units_multiplier)
        if new_units == 0 and old_units != 0:
            new_units = 1 if old_units > 0 else -1

        order_class.units = abs(new_units)
        order_plan["units"] = abs(new_units)
        for_api_json = order_plan.get("for_api_json")
        if for_api_json and "order" in for_api_json:
            direction = int(order_plan.get("direction") or 1)
            for_api_json["order"]["units"] = str(abs(new_units) * direction)

    def _apply_rr_to_tp(self, order_class, rr):
        p = self.p
        order_plan = order_class.exe_order_plan
        direction = int(order_plan.get("direction") or 1)
        target_price = float(order_plan["target_price"])
        lc_range = float(order_plan["lc_range"])
        lc_pips = p.price_to_pips(lc_range)
        tp_pips = round(lc_pips * rr, 1)
        tp_range = p.pips_to_price(tp_pips)
        tp_price = p.round_price(target_price + (tp_range * direction))

        order_class.tp_range = tp_range
        order_class.tp_price = tp_price
        order_plan["tp_range"] = tp_range
        order_plan["tp_price"] = tp_price
        order_plan["session_tp_pips"] = tp_pips

        for_api_json = order_plan.get("for_api_json")
        if for_api_json and "order" in for_api_json:
            take_profit = for_api_json["order"].get("takeProfitOnFill")
            if take_profit is not None:
                take_profit["price"] = str(tp_price)

    def _create_order(
        self,
        candidate,
        selected_candidates,
        current_price,
        decision_time,
        rsi_info,
    ):
        p = self.p
        strategy = candidate["strategy"]
        line = candidate["line"]
        lc_range = p.pips_to_price(strategy.lc_pips)
        tp_range = p.pips_to_price(strategy.get_tp_pips())
        units = int(
            self.analysis.cal_units(
                lc_range,
                tk.setting_json["l_units"],
                "l",
            )
            * self._get_units_multiplier(candidate, selected_candidates)
        )

        order_class = OCreate.Order({
            "name": (
                strategy.name_prefix
                + "_"
                + candidate["line_side"]
                + "_"
                + str(candidate["line_index"])
            ),
            "current_price": current_price,
            "target": candidate["target_price"],
            "direction": candidate["direction"],
            "type": strategy.order_type,
            "tp": tp_range,
            "lc": lc_range,
            "lc_change": [],
            "units": units,
            "priority": int(line.get("total_strength", 0)),
            "decision_time": decision_time,
            "pair": self.pair,
            "candle_analysis_class": self.analysis.candle_analysis_all,
            "lc_change_candle_type": "M5",
            "order_timeout_min": strategy.order_timeout_min,
            "memo": candidate.get("memo", ""),
        })
        order_plan = order_class.exe_order_plan
        order_plan["source"] = "line"
        order_plan["line_timeframe"] = strategy.timeframe
        order_plan["line_entry_type"] = strategy.entry_type
        order_plan["line_entry_offset_pips"] = strategy.entry_offset_pips
        order_plan["latest_peak_dir"] = candidate.get("latest_peak_dir")
        order_plan["latest_peak_count"] = candidate.get("latest_peak_count")
        order_plan["latest_peak_gap"] = candidate.get("latest_peak_gap")
        order_plan["latest_peak_time"] = candidate.get("latest_peak_time")
        order_plan["line_side"] = candidate["line_side"]
        order_plan["line_price"] = candidate["line_price"]
        order_plan["line_total_strength"] = line.get("total_strength")
        order_plan["line_count"] = line.get("count")
        order_plan["line_ave_strength"] = line.get("ave_strength")
        order_plan["line_is_flipped"] = line.get("is_flipped_line")
        order_plan["line_oldest_time"] = line.get("oldest_time")
        order_plan["core_median_price"] = line.get("core_median_price")
        order_plan["core_count"] = line.get("core_count")
        order_plan["core_total_strength"] = line.get("core_total_strength")
        order_plan["line_strategy"] = strategy.line_strategy
        order_plan.update(candidate.get("h1_context", {}))
        if rsi_info is not None:
            order_plan.update(rsi_info)
        return order_class


class MainAnalysis:
    def __init__(self, candle_analysis, position_control_class=None, mode="inspection"):
        print(" 笆繝｡繧､繝ｳ繧｢繝翫Μ繧ｷ繧ｹ", mode)

        # 笆笆笆蝓ｺ譛ｬ諠・ｱ縺ｮ蜿門ｾ・
        if mode == "live":
            from_i = 0
            self.mode = "live"
            from_i_price = 0  #
        else:
            from_i = 1
            self.mode = "inspection"
            from_i_price = 1
        self.position_control_class = position_control_class
        self.line_send_exe = this_file_line_send
        self.line_send_mes = ""
        self.s = "    "
        self.round_digit = 3
        self.oa = candle_analysis.base_oa

        self.candle_analysis_all = candle_analysis

        self.ca5 = candle_analysis.candle_meta_class  # peaks莉･螟悶・驛ｨ蛻・Ｄal_move_ave髢｢謨ｰ繧剃ｽｿ縺・畑
        self.peaks_class = candle_analysis.peaks_class  # peaks_class縺縺代ｒ謚ｽ蜃ｺ
        self.df_r_m5 = candle_analysis.d5_df_r[1:]  # 5蛻・ｶｳ縺ｯ縺ｲ縺ｨ縺､蜑阪・縺ｧ蝗ｺ螳夲ｼ・ｼ・ｼ・ive縺ｧ繧ゑｼ・

        self.ca60 = candle_analysis.candle_meta_class_hour
        self.peaks_class_hour = candle_analysis.peaks_class_hour
        self.df_r_h1 = candle_analysis.h1_df_r[from_i:]

        self.ca30 = candle_analysis.candle_meta_class_m30
        self.peaks_class_m30 = candle_analysis.peaks_class_m30
        self.df_r_m30 = candle_analysis.d30_df_r[from_i:]

        self.current_time = candle_analysis.d5_df_r.iloc[0]['time_jp']  # 5蛻・ｶｳ縺ｧ蛻､譁ｭ(0陦檎岼繧貞茜逕ｨ・・
        self.current_price = candle_analysis.current_price  # candleAnalysis縺九ｉ縺ｨ繧具ｼ域悽逡ｪ縺ｮ蝣ｴ蜷医・API縺ｧ譛譁ｰ縲∬ｧ｣譫舌・蝣ｴ蜷医・close萓｡譬ｼ)
        self.mode = mode  # 讀懆ｨｼ縺九←縺・°
        self.pair = getattr(candle_analysis, "pair", "USD_JPY")
        self.p = gene.currency_pair(self.pair)
        self.line_strategy_config = line_strategy_config(self.pair)
        print("current_price(main_analysis)", self.current_price, "move_ave", self.ca5.cal_move_ave(1))
        # 謚ｵ謚礼ｷ夐未菫・
        self.exist_strong_line = False
        # BB髢｢菫・
        self.latest_exe_bb_h1_row = None
        self.bb_h1_class = None
        self.bb_m5_class = None
        self.bb5_cross_pattern = 0  # 1縺悟ｼｷ繧√・縺悟ｼｷ縺・・縺ゅ▲縺溘′謚倥ｊ霑斐＠

        # 笆笆笆蝓ｺ譛ｬ邨先棡縺ｮ螟画焚縺ｮ螳｣險
        self.take_position_flag = False
        self.exe_order_classes = []
        self.send_message_at_last = ""

        # 笆笆笆縲迴ｾ蝨ｨ縺ｮ蜍昴■雋縺代・讒伜ｭ・
        if self.position_control_class is None:
            # print("驕主悉縺ｮ蜍昴■雋縺代・豌励↓縺励↑縺・ｼ亥腰逋ｺ縺ｮ繝・せ繝医・縺溘ａ諠・ｱ縺ｪ縺暦ｼ・)
            pass
        else:
            position_one = self.position_control_class.position_classes[0]  # position縺ｮ蜈磯ｭ繧貞叙蠕暦ｼ医←繧後〒繧ゅ＞縺・ｼ・
            p = position_one.history_plus_minus
            # print("驕主悉縺ｮ蜍昴■雋縺代・螻･豁ｴ", position_one.history_plus_minus)
            if len(p) >= 6:
                # print("蜍昴■雋縺代・逶ｴ霑台ｸ牙・, p[-1], p[-2], p[-3], p[-4], p[-5], p[-6])
                pass
            else:
                pass
                # print("蜍昴■雋縺代・逶ｴ霑台ｸ牙・, p[-1])
            # 繧ｯ繝ｩ繧ｹ縺梧ｼ邏阪＆繧後ｋ繧医≧縺ｫ螟画峩縺励◆縺ｮ縺ｧ縲√け繝ｩ繧ｹ縺ｮ繝・せ繝・
            for i, item in enumerate(self.position_control_class.result_class_arr):
                pass
                # print("繧ｯ繝ｩ繧ｹ縺ｮ繝・せ繝・", item.life, item.name, item.t_unrealize_pl, item.t_realize_pl, item.t_pl_u)

        # 笆笆笆蝓ｺ譛ｬ諠・ｱ縺ｮ陦ｨ遉ｺ
        # peaks = self.peaks_class.peaks_original
        # peaks_skip = self.peaks_class.skipped_peaks_hard
        peaks = self.peaks_class.peaks_original
        peaks_skip = self.peaks_class.skipped_peaks_hard
        print(self.s, "<SKIP蜑・", len(peaks), asizeof.asizeof(peaks))
        gene.print_peaks(peaks[:4])
        print("--")
        gene.print_peaks(peaks[-2:])
        print("")

        print(self.s, "<SKIP after>", len(peaks_skip), asizeof.asizeof(peaks_skip))
        gene.print_peaks(peaks_skip[:3])
        print("")

        # print(self.s, "<SKIP蜑・1h雜ｳ>", len(self.peaks_class_hour.peaks_original), asizeof.asizeof(self.peaks_class_hour.peaks_original))
        # gene.print_arr(self.peaks_class_hour.peaks_original[:3])
        # print("竊・)
        # gene.print_arr(self.peaks_class_hour.peaks_original[-2:])
        # print("")
        #
        # print(self.s, "<SKIP蠕・1h雜ｳ・・, len(self.peaks_class_hour.skipped_peaks), asizeof.asizeof(self.peaks_class_hour.skipped_peaks))
        # gene.print_arr(self.peaks_class_hour.skipped_peaks[:3])
        #
        # print(self.s, "<SKIP HARD蠕・1h雜ｳ・・, len(self.peaks_class_hour.skipped_peaks_hard), asizeof.asizeof(self.peaks_class_hour.skipped_peaks_hard))
        # gene.print_arr(self.peaks_class_hour.skipped_peaks_hard[:3])

        # 笆笆笆笆縲莉･荳九・隗｣譫仙､遲・
        # 笆笆笆邁｡譏鍋噪縺ｪ隗｣譫仙､
        peaks = self.peaks_class.peaks_original
        r = peaks[0]
        t = peaks[1]
        f = peaks[2]
        # River縺ｨTurn縺ｮ隗｣譫・
        # self.rt = TuneAnalysisInformation(self.peaks_class, 1, "rt")  # peak諠・ｱ貅千函謌・
        # # Flop縺ｨTurn
        # self.tf = TuneAnalysisInformation(self.peaks_class, 2, "tf")  # peak諠・ｱ貅千函謌・
        # # preFlop縺ｨflop縺ｮ隗｣譫・
        # self.fp = TuneAnalysisInformation(self.peaks_class, 2, "fp")  # peak諠・ｱ貅千函謌・
        # 蜷・ｾ｡譬ｼ縺ｫ菴ｿ縺・°繧ゅ＠繧後↑縺・黄
        self.latest_turn_resistance_gap = abs(t['latest_body_peak_price'] - self.current_price)
        self.latest_flop_resistance_gap = abs(f['latest_body_peak_price'] - self.current_price)

        # 隱ｿ謨ｴ逕ｨ縺ｮ菫よ焚縺溘■
        self.sp = 0.004  # 繧ｹ繝励Ξ繝・ラ閠・・逕ｨ
        self.base_lc_range = 1  # 縺薙％縺ｧ縺ｮ繝吶・繧ｹ縺ｨ縺ｪ繧記CRange
        self.base_tp_range = 1
        # 菫よ焚縺ｮ隱ｿ謨ｴ逕ｨ
        self.lc_adj = 0.7
        self.arrow_skip = 1
        # Unit隱ｿ謨ｴ逕ｨ
        self.units_mini = 0.1
        self.units_reg = 0.5
        self.units_str = 1 * gl_unis_std  #0.1
        self.units_hedge = self.units_str
        # 豎守畑諤ｧ鬮倥ａ
        self.lc_change_test = [
            {"exe": True, "time_after": 0, "trigger": 0.01, "ensure": -1},  # 竊舌→縺ｫ縺九￥縲´CCandle繧堤匱蜍輔＆縺帙◆縺・ｴ蜷・
        ]

        # 笘・・笘・ｪｿ譟ｻ螳溯｡・
        self.main()

    def line_comment_add(self, *msg):
        message = ""
        # 隍・焚縺ｮ蠑墓焚繧剃ｸ縺､縺ｫ縺吶ｋ・域焚蟄励′蜷ｫ縺ｾ繧後ｋ蝣ｴ蜷医′縺ゅｋ縺溘ａ縲ヾTR縺ｧ譁・ｭ怜喧縺励※縺翫￥・・
        for item in msg:
            message = message + " " + str(item)

        self.line_send_mes = "\n" + self.line_send_mes + message

    def line_send(self, *msg):
        # 髢｢謨ｰ縺ｯ蜿ｯ螟芽､・焚縺ｮ繧ｳ繝ｳ繝槫玄蛻・ｊ縺ｮ蠑墓焚繧貞女縺台ｻ倥￠繧・
        message = ""
        # 隍・焚縺ｮ蠑墓焚繧剃ｸ縺､縺ｫ縺吶ｋ・域焚蟄励′蜷ｫ縺ｾ繧後ｋ蝣ｴ蜷医′縺ゅｋ縺溘ａ縲ヾTR縺ｧ譁・ｭ怜喧縺励※縺翫￥・・
        for item in msg:
            message = message + " " + str(item)
        # 譎ょ綾縺ｮ陦ｨ遉ｺ繧剃ｽ懈・縺吶ｋ
        now_str = f'{datetime.now():%Y/%m/%d %H:%M:%S}'
        # 繝｡繝・そ繝ｼ繧ｸ縺ｮ譛蠕悟ｰｾ縺ｫ莉倥￠繧・
        message = message + " (" + now_str[5:10] + "_" + now_str[11:19] + ")"
        if len(message) >= 2000:
            print("@@譁・ｭ励が繝ｼ繝舌・")
            print(message)
            message = "Discord蜿嶺ｿ｡險ｱ螳ｹ譁・ｭ玲焚繧ｪ繝ｼ繝舌・" + str(len(message))
        if not self.line_send_exe:
            print("     [Disc(騾∽ｻ倡┌縺・]", message)  # 繧ｳ繝槭Φ繝峨Λ繧､繝ｳ縺ｫ繧り｡ｨ遉ｺ
            return 0
        # 笆笆笆  騾壼ｸｸ縺ｮDiscord騾∽ｿ｡縲笆笆笆縲縲譛謔ｪ縺薙ｌ莉･荳九□縺代≠繧後・縺・＞
        data = {"content": "@everyone " + message,
                "allowed_mentions": {
                    "parse": ["everyone"]
                }
                }
        requests.post(tk.WEBHOOK_URL_main, json=data)
        print("     [Disc]", message)  # 繧ｳ繝槭Φ繝峨Λ繧､繝ｳ縺ｫ繧り｡ｨ遉ｺ

    def add_order_to_this_class(self, order_class):
        """

        """
        self.take_position_flag = True
        if isinstance(order_class, (list, tuple)):
            self.exe_order_classes.extend(order_class)
        else:
            self.exe_order_classes.append(order_class)
        # self.exe_order_classes.extend(order_class)
        # print("逋ｺ陦後＠縺溘が繝ｼ繝繝ｼ2竊薙(turn255)")
        # print(order_class.exe_order)

    def _legacy_add_h1_line_limit_orders(self, line_class, current_price, decision_time, rsi_info=None):
        if self.mode != "inspection":
            return

        p = self.p
        spread_pips = 0.8
        lc_pips = 15
        rr = 1.65
        tp_pips = round(rr * (lc_pips + spread_pips) + spread_pips, 1)
        lc_range = p.pips_to_price(lc_pips)
        tp_range = p.pips_to_price(tp_pips)
        units = int(self.cal_units(lc_range, tk.setting_json['l_units'], "l") * 0.5)

        line_orders = []
        line_candidates = []
        duplicate_threshold_pips = 3
        for line_side, direction, lines in (
            ("upper", -1, line_class.upper_lines),
            ("lower", 1, line_class.lower_lines),
        ):
            for i, line in enumerate(lines):
                if not self.is_h1_line_limit_order_target(line_side, line):
                    continue

                line_price = p.round_price(line["median_price"])
                line_strategy = "lower_c3_core1or3"
                distance_pips = abs(p.price_to_pips(float(current_price) - float(line_price)))
                line_candidates.append({
                    "line_side": line_side,
                    "direction": direction,
                    "line": line,
                    "line_index": i,
                    "line_price": line_price,
                    "line_strategy": line_strategy,
                    "distance_pips": distance_pips,
                })

        selected_candidates = []
        for candidate in sorted(line_candidates, key=lambda x: x["distance_pips"]):
            is_duplicate = False
            for selected in selected_candidates:
                if int(selected["direction"]) != int(candidate["direction"]):
                    continue
                if selected["line_strategy"] != candidate["line_strategy"]:
                    continue
                gap_pips = abs(p.price_to_pips(float(candidate["line_price"]) - float(selected["line_price"])))
                if gap_pips <= duplicate_threshold_pips:
                    print(
                        "Skip farther H1 line candidate:",
                        candidate["line_side"],
                        candidate["line_price"],
                        "near",
                        selected["line_price"],
                        "gap_pips",
                        round(gap_pips, 1),
                    )
                    is_duplicate = True
                    break
            if not is_duplicate:
                selected_candidates.append(candidate)

        for candidate in selected_candidates:
            line_side = candidate["line_side"]
            direction = candidate["direction"]
            line = candidate["line"]
            i = candidate["line_index"]
            line_price = candidate["line_price"]
            line_strategy = candidate["line_strategy"]

            if self.has_similar_order(
                direction,
                line_price,
                [],
                duplicate_threshold_pips,
                source="line",
                line_strategy=line_strategy,
            ):
                print("Skip similar H1 line order:", line_side, line_price, "direction", direction)
                continue

            order_class = OCreate.Order({
                "name": "H1LineLimit_" + line_side + "_" + str(i),
                "current_price": current_price,
                "target": line_price,
                "direction": direction,
                "type": "LIMIT",
                "tp": tp_range,
                "lc": lc_range,
                "lc_change": [],
                "units": units,
                "priority": int(line.get("total_strength", 0)),
                "decision_time": decision_time,
                "pair": self.pair,
                "candle_analysis_class": self.candle_analysis_all,
                "lc_change_candle_type": "M5",
                "order_timeout_min": 60,
                "memo": "virtual H1 line limit order",
            })
            order_class.exe_order_plan["source"] = "line"
            order_class.exe_order_plan["line_timeframe"] = "h1"
            order_class.exe_order_plan["line_side"] = line_side
            order_class.exe_order_plan["line_price"] = line_price
            order_class.exe_order_plan["line_total_strength"] = line.get("total_strength")
            order_class.exe_order_plan["line_count"] = line.get("count")
            order_class.exe_order_plan["line_ave_strength"] = line.get("ave_strength")
            order_class.exe_order_plan["line_is_flipped"] = line.get("is_flipped_line")
            order_class.exe_order_plan["line_oldest_time"] = line.get("oldest_time")
            order_class.exe_order_plan["core_median_price"] = line.get("core_median_price")
            order_class.exe_order_plan["core_count"] = line.get("core_count")
            order_class.exe_order_plan["core_total_strength"] = line.get("core_total_strength")
            order_class.exe_order_plan["line_strategy"] = line_strategy
            if rsi_info is not None:
                order_class.exe_order_plan.update(rsi_info)
            line_orders.append(order_class)

        if line_orders:
            print("H1 line limit orders:", len(line_orders))
            self.add_order_to_this_class(line_orders)

    def _legacy_add_m5_line_limit_orders(self, line_class, current_price, decision_time, rsi_info=None):
        if self.mode != "inspection":
            return

        p = self.p
        lc_pips = 7.5
        tp_pips = 13
        lc_range = p.pips_to_price(lc_pips)
        tp_range = p.pips_to_price(tp_pips)
        units = int(self.cal_units(lc_range, tk.setting_json['l_units'], "l") * 0.25)

        line_orders = []
        line_candidates = []
        duplicate_threshold_pips = 3
        for line_side, direction, lines in (
            ("upper", -1, line_class.upper_lines),
            ("lower", 1, line_class.lower_lines),
        ):
            for i, line in enumerate(lines):
                if not self.is_m5_line_limit_order_target(line_side, line):
                    continue

                line_price = p.round_price(line["median_price"])
                line_strategy = "m5_line_test_c2_core"
                distance_pips = abs(p.price_to_pips(float(current_price) - float(line_price)))
                line_candidates.append({
                    "line_side": line_side,
                    "direction": direction,
                    "line": line,
                    "line_index": i,
                    "line_price": line_price,
                    "line_strategy": line_strategy,
                    "distance_pips": distance_pips,
                })

        selected_candidates = []
        for candidate in sorted(line_candidates, key=lambda x: x["distance_pips"]):
            is_duplicate = False
            for selected in selected_candidates:
                if int(selected["direction"]) != int(candidate["direction"]):
                    continue
                if selected["line_strategy"] != candidate["line_strategy"]:
                    continue
                gap_pips = abs(p.price_to_pips(float(candidate["line_price"]) - float(selected["line_price"])))
                if gap_pips <= duplicate_threshold_pips:
                    print(
                        "Skip farther M5 line candidate:",
                        candidate["line_side"],
                        candidate["line_price"],
                        "near",
                        selected["line_price"],
                        "gap_pips",
                        round(gap_pips, 1),
                    )
                    is_duplicate = True
                    break
            if not is_duplicate:
                selected_candidates.append(candidate)

        for candidate in selected_candidates:
            line_side = candidate["line_side"]
            direction = candidate["direction"]
            line = candidate["line"]
            i = candidate["line_index"]
            line_price = candidate["line_price"]
            line_strategy = candidate["line_strategy"]

            if self.has_similar_order(
                direction,
                line_price,
                [],
                duplicate_threshold_pips,
                source="line",
                line_strategy=line_strategy,
            ):
                print("Skip similar M5 line order:", line_side, line_price, "direction", direction)
                continue

            order_class = OCreate.Order({
                "name": "M5LineLimit_" + line_side + "_" + str(i),
                "current_price": current_price,
                "target": line_price,
                "direction": direction,
                "type": "LIMIT",
                "tp": tp_range,
                "lc": lc_range,
                "lc_change": [],
                "units": units,
                "priority": int(line.get("total_strength", 0)),
                "decision_time": decision_time,
                "pair": self.pair,
                "candle_analysis_class": self.candle_analysis_all,
                "lc_change_candle_type": "M5",
                "order_timeout_min": 15,
                "memo": "virtual M5 line limit order",
            })
            order_class.exe_order_plan["source"] = "line"
            order_class.exe_order_plan["line_timeframe"] = "m5"
            order_class.exe_order_plan["line_side"] = line_side
            order_class.exe_order_plan["line_price"] = line_price
            order_class.exe_order_plan["line_total_strength"] = line.get("total_strength")
            order_class.exe_order_plan["line_count"] = line.get("count")
            order_class.exe_order_plan["line_ave_strength"] = line.get("ave_strength")
            order_class.exe_order_plan["line_is_flipped"] = line.get("is_flipped_line")
            order_class.exe_order_plan["line_oldest_time"] = line.get("oldest_time")
            order_class.exe_order_plan["core_median_price"] = line.get("core_median_price")
            order_class.exe_order_plan["core_count"] = line.get("core_count")
            order_class.exe_order_plan["core_total_strength"] = line.get("core_total_strength")
            order_class.exe_order_plan["line_strategy"] = line_strategy
            if rsi_info is not None:
                order_class.exe_order_plan.update(rsi_info)
            line_orders.append(order_class)

        if line_orders:
            print("M5 line limit orders:", len(line_orders))
            self.add_order_to_this_class(line_orders)

    def add_line_limit_orders(
        self,
        line_class_m5,
        line_class_h1,
        current_price,
        decision_time,
        rsi_info=None,
    ):
        coordinator = LineOrderCoordinator(self)
        return coordinator.create_orders(
            [
                (M5LineOrderStrategy(self.line_strategy_config), line_class_m5),
                (M5BreakoutLineOrderStrategy(self.line_strategy_config), line_class_m5),
                (H1LineOrderStrategy(self.line_strategy_config), line_class_h1),
            ],
            current_price,
            decision_time,
            rsi_info,
            h1_line_class=line_class_h1,
        )

    def add_h1_line_limit_orders(self, line_class, current_price, decision_time, rsi_info=None):
        coordinator = LineOrderCoordinator(self)
        return coordinator.create_orders(
            [(H1LineOrderStrategy(self.line_strategy_config), line_class)],
            current_price,
            decision_time,
            rsi_info,
        )

    def add_m5_line_limit_orders(self, line_class, current_price, decision_time, rsi_info=None):
        coordinator = LineOrderCoordinator(self)
        return coordinator.create_orders(
            [(M5LineOrderStrategy(self.line_strategy_config), line_class)],
            current_price,
            decision_time,
            rsi_info,
        )

    def add_m5_line_test_orders(
        self,
        line_class,
        h1_line_class,
        current_price,
        decision_time,
        rsi_info=None,
    ):
        coordinator = LineOrderCoordinator(self)
        return coordinator.create_orders(
            [
                (M5LineOrderStrategy(self.line_strategy_config), line_class),
                (M5BreakoutLineOrderStrategy(self.line_strategy_config), line_class),
            ],
            current_price,
            decision_time,
            rsi_info,
            h1_line_class=h1_line_class,
        )

    def has_similar_order(self, direction, target_price, new_orders, threshold_pips=3, source=None, line_strategy=None):
        p = self.p
        for order_class in list(self.exe_order_classes) + list(new_orders):
            order_plan = getattr(order_class, "exe_order_plan", None)
            if not order_plan:
                continue
            if int(order_plan.get("direction", 0)) != int(direction):
                continue
            if source is not None and order_plan.get("source") != source:
                continue
            if line_strategy is not None and order_plan.get("line_strategy") != line_strategy:
                continue
            other_price = order_plan.get("target_price")
            if other_price is None:
                continue
            if abs(p.price_to_pips(float(target_price) - float(other_price))) <= threshold_pips:
                return True

        if self.position_control_class is not None and hasattr(self.position_control_class, "find_similar_active_order"):
            result = self.position_control_class.find_similar_active_order(
                direction,
                target_price,
                threshold_pips,
                source=source,
                line_strategy=line_strategy,
            )
            if result["is_exist"]:
                print(
                    "Skip similar active order:",
                    result.get("name"),
                    "target",
                    result.get("target_price"),
                    "gap_pips",
                    round(result.get("gap_pips", 0), 1),
                )
                return True
        return False

    def is_h1_line_limit_order_target(self, line_side, line):
        return H1LineOrderStrategy(self.line_strategy_config).is_target(line_side, line)

    def is_m5_line_limit_order_target(self, line_side, line):
        return M5LineOrderStrategy(self.line_strategy_config).is_target(line_side, line)

    @staticmethod
    def build_timeframe_rsi_info(prefix, df_r, upper_border, lower_border):
        keys = {
            f"{prefix}_rsi_1": None,
            f"{prefix}_rsi_2": None,
            f"{prefix}_rsi_3": None,
            f"{prefix}_rsi_time_1": None,
            f"{prefix}_rsi_time_2": None,
            f"{prefix}_rsi_time_3": None,
            f"{prefix}_rsi_is_high": None,
            f"{prefix}_rsi_is_low": None,
        }
        if df_r is None or len(df_r) <= 3 or "RSI" not in df_r.columns:
            return keys

        f_low = df_r.iloc[1]
        s_low = df_r.iloc[2]
        t_low = df_r.iloc[3]
        rsi_1 = f_low.get("RSI")
        keys.update({
            f"{prefix}_rsi_1": rsi_1,
            f"{prefix}_rsi_2": s_low.get("RSI"),
            f"{prefix}_rsi_3": t_low.get("RSI"),
            f"{prefix}_rsi_time_1": f_low.get("time_jp"),
            f"{prefix}_rsi_time_2": s_low.get("time_jp"),
            f"{prefix}_rsi_time_3": t_low.get("time_jp"),
            f"{prefix}_rsi_is_high": rsi_1 >= upper_border,
            f"{prefix}_rsi_is_low": rsi_1 <= lower_border,
        })
        return keys

    def main(self):
        """
        繧ｿ繝ｼ繝ｳ逶ｴ蠕後〒縺ｮ蛻､譁ｭ縲・
        """
        print("main")
        # 螟画焚蛹・
        global gl_previous_exe_df60_row
        global gl_previous_exe_df60_order_time
        global gl_previous_bb_h1_class

        s = self.s
        df_r = self.df_r_m5  # 蝣ｴ蜷医↓繧医▲縺ｦ0縺梧ｶ医＆繧後※縺・ｋdf_r
        candle_analysis = self.candle_analysis_all
        peaks = self.peaks_class.peaks_original
        peaks_skip = self.peaks_class.skipped_peaks_hard
        mode = self.mode
        # 螟画焚蛹厄ｼ・B・・
        df_h1_row = candle_analysis.h1_df_r.iloc[0]
        bb_h1_class = self.bb_h1_class
        bb_m5_class = self.bb_m5_class

        # 笆騾比ｸｭ邨ゆｺ・愛螳・
        # if peaks[1]['gap'] < 0.04:
        #     print("蟇ｾ雎｡縺悟ｰ上＆縺・, peaks[1]['gap'])

        # (4)螟ｧ譛ｬ蜻ｽ
        self.predict_analysis()

    def get_strongest_line(self, lines):
        """Return the strongest line by total_strength."""
        if not lines:
            return None
        return max(lines, key=lambda x: x['total_strength'])

    def compare_lines(self, line_l, line_s, line_type='tp', threshold=0.5):
        """隍・焚譎る俣霆ｸ縺ｮLINE繧呈ｯ碑ｼ・ｼ・P 縺ｾ縺溘・ LC・・
        
        Args:
            line_l: 繝ｭ繝ｳ繧ｰ縺ｮLINE
            line_s: 繧ｷ繝ｧ繝ｼ繝医・LINE
            line_type: 'tp' 縺ｾ縺溘・ 'lc'
            threshold: median縺ｮ蟾ｮ縺ｮ髢ｾ蛟､
        
        Returns:
            蛻､螳夂ｵ先棡繧定ｾ樊嶌縺ｧ霑斐☆
        """
        # line_type縺ｫ蠢懊§縺ｦ蟇ｾ雎｡繧帝∈謚・
        if line_type.lower() == 'tp':
            lines_3h = line_l.tp_lines
            lines_6h = line_s.tp_lines
        elif line_type.lower() == 'lc':
            lines_3h = line_l.lc_lines
            lines_6h = line_s.lc_lines
        else:
            raise ValueError("line_type 縺ｯ 'tp' 縺ｾ縺溘・ 'lc' 縺ｧ謖・ｮ壹＠縺ｦ縺上□縺輔＞")
        
        strongest_3h = self.get_strongest_line(lines_3h)
        strongest_6h = self.get_strongest_line(lines_6h)
        
        if strongest_3h is None or strongest_6h is None:
            return {
                'status': '荳崎ｶｳ',
                'reason': '繝・・繧ｿ縺御ｸ崎ｶｳ',
                'line_type': line_type,
            }
        
        median_3h = strongest_3h['median']
        median_6h = strongest_6h['median']
        median_diff = abs(median_3h - median_6h)
        
        status = 'same' if median_diff <= threshold else 'different'
        
        return {
            'status': status,
            'line_type': line_type,
            'median_diff': self.p.round_price(median_diff),
            'threshold': threshold,
            'median_3h': median_3h,
            'median_6h': median_6h,
            'strength_3h': strongest_3h['total_strength'],
            'strength_6h': strongest_6h['total_strength'],
            'price_3h': strongest_3h['median_price'],
            'price_6h': strongest_6h['median_price'],
        }


    def predict_analysis(self):
        # 繧ｿ繝ｼ繝ｳ譎ゆｻ･螟悶〒繧ょｮ溯｡後＆繧後ｋ
        print("笆莠域ｸｬ繧ｪ繝ｼ繝繝ｼ")
        s = self.s
        p = self.p
        current_price = self.current_price  # self.ca = candle_analysis
        foot = 5
        if foot == 5:
            # ・募・雜ｳ縺ｮ蝣ｴ蜷・
            peaks_class = self.peaks_class
            peaks = self.peaks_class.peaks_original
            df = self.peaks_class.df_r_original  # 縺薙ｌ縺ｯ
        else:
            # 30蛻・ｶｳ縺ｮ蝣ｴ蜷・
            peaks_class = self.peaks_class_m30
            peaks = self.peaks_class_m30.peaks_original  # self.peaks_class.peaks_original
            df = self.peaks_class_m30.df_r_original  # self.peaks_class.df_r_original  # 縺薙ｌ縺ｯ

            # ・難ｼ仙・雜ｳ縺ｮ蝣ｴ蜷医・縲・ｼ難ｼ仙・縺ｫ・大屓螳溯｡・
            dt = datetime.strptime(self.current_time, '%Y/%m/%d %H:%M:%S')
            minute = dt.minute
            if minute == 0 or minute == 30:  # or minute == 5 or minute == 35:  #minute % 30 == 0:
                pass
            else:
                print("skip non-30m timing")
                return 0
        # base_price = self.current_price
        base_price = peaks[0]['latest_body_peak_price']  # self.latest_price

        # 笆RSI
        upper_border = 67.5
        lower_border = 30
        # print(df[['time_jp', 'RSI']].head(15))
        f_low = df.iloc[1]
        s_low = df.iloc[2]  # 縺ｲ縺ｨ縺､蜑阪・雜ｳ
        t_low = df.iloc[3]  # 縺ｵ縺溘▽蜑阪・雜ｳ
        print("    RSI", f_low['time_jp'], f_low['RSI'], "-", s_low['time_jp'],s_low['RSI'] )
        if f_low['RSI'] >= upper_border and s_low['RSI'] >= upper_border:
            print("    RSI high continues")
        elif f_low['RSI'] <= lower_border and s_low['RSI'] <= lower_border:
            print("    RSI low continues")
            if self.mode != "inspection":
                return 0
        elif  f_low['RSI'] >= upper_border and s_low['RSI'] <= upper_border and t_low['RSI'] >= upper_border:
            print("    RSI high pattern continues")
            if self.mode != "inspection":
                return 0
        elif f_low['RSI'] <= lower_border and s_low['RSI'] >= lower_border and t_low['RSI'] <= lower_border:
            print("    RSI low pattern continues")
            if self.mode != "inspection":
                return 0
        
        # 笆繝ｩ繧､繝ｳ縺ｮ讀懆ｨｼ
        line_class_m5_l = LineStrengthCal(self.candle_analysis_all, "m5", 60)
        line_class_m5_s = LineStrengthCal(self.candle_analysis_all, "m5", 30)
        result = self.compare_lines(line_class_m5_l, line_class_m5_s, threshold=0.5)
        print(f"蛻､螳・ {result['status']}")
        print("1譎る俣雜ｳ")
        line_class_h1_l = LineStrengthCal(self.candle_analysis_all, "h1", 65)  # 逕ｻ髱｢蜈ｨ菴薙￥繧峨＞・育峩霑代・螟ｧ縺阪↑豬√ｌ繧定ｦ九ｌ繧具ｼ・
        line_class_h1_s = LineStrengthCal(self.candle_analysis_all, "h1", 30)  # 逕ｻ髱｢蜊雁・縺上ｉ縺・ｼ育峩霑代・繝ｬ繝ｳ繧ｸ繧定ｦ九ｌ繧具ｼ・
        self.line_class_h1_l = line_class_h1_l
        self.line_class_h1_s = line_class_h1_s
        rsi_info = {
            "rsi_1": f_low.get("RSI"),
            "rsi_2": s_low.get("RSI"),
            "rsi_3": t_low.get("RSI"),
            "rsi_time_1": f_low.get("time_jp"),
            "rsi_time_2": s_low.get("time_jp"),
            "rsi_time_3": t_low.get("time_jp"),
            "rsi_upper_border": upper_border,
            "rsi_lower_border": lower_border,
            "rsi_is_high": f_low.get("RSI") >= upper_border,
            "rsi_is_low": f_low.get("RSI") <= lower_border,
        }
        rsi_info.update(self.build_timeframe_rsi_info(
            "h1",
            self.candle_analysis_all.h1_df_r,
            upper_border,
            lower_border,
        ))
        m5_line_orders = self.add_m5_line_test_orders(
            line_class_m5_l,
            line_class_h1_l,
            current_price,
            df.iloc[0]['time_jp'],
            rsi_info,
        )
        result = self.compare_lines(line_class_h1_l, line_class_h1_s, threshold=0.5)
        peaks_h1 = self.candle_analysis_all.peaks_class_hour.peaks_original
        # gene.print_peaks(peaks_h1)

        order_pattern = 0

        before_legacy_rsi_order_count = len(self.exe_order_classes)
        print("Legacy RSI line orders are disabled. Use top7 M5 line orders.")
        self.notify_count2_line_no_order(
            peaks[0],
            line_class_m5_l,
            line_class_m5_s,
            line_class_h1_l,
            rsi_info,
            order_pattern,
            before_legacy_rsi_order_count,
            current_price,
            df.iloc[0]['time_jp'],
            m5_line_orders,
        )
        return 0

    def notify_count2_line_no_order(
        self,
        latest_peak,
        line_class_m5_l,
        line_class_m5_s,
        line_class_h1_l,
        rsi_info,
        order_pattern,
        before_order_count,
        current_price,
        decision_time,
        m5_line_orders,
    ):
        if self.mode == "inspection":
            return

        if int(latest_peak.get("count") or 0) != 2:
            return

        if len(self.exe_order_classes) > before_order_count:
            return

        has_m5_line = bool(line_class_m5_l.upper_lines or line_class_m5_l.lower_lines)
        if not has_m5_line:
            return

        if m5_line_orders:
            return

        message = self.build_count2_line_no_order_message(
            latest_peak,
            line_class_m5_l,
            line_class_m5_s,
            line_class_h1_l,
            rsi_info,
            order_pattern,
            current_price,
            decision_time,
        )
        tk.line_send(message)

    def build_count2_line_no_order_message(
        self,
        latest_peak,
        line_class_m5_l,
        line_class_m5_s,
        line_class_h1_l,
        rsi_info,
        order_pattern,
        current_price,
        decision_time,
    ):
        reason = "RSI_Line order_pattern=0"
        rsi_1 = rsi_info.get("rsi_1") if rsi_info else None
        if rsi_1 is not None:
            if rsi_info.get("rsi_lower_border") < rsi_1 < rsi_info.get("rsi_upper_border"):
                reason = "RSI is neutral"
            elif order_pattern == 0:
                reason = "RSI/line strength did not match order rule"

        m5_l_summary = self.line_summary_for_message("M5-60", line_class_m5_l, current_price)
        m5_s_summary = self.line_summary_for_message("M5-30", line_class_m5_s, current_price)
        h1_summary = self.line_summary_for_message("H1-65", line_class_h1_l, current_price)
        return (
            "[M5 count2 line no order]"
            + "\ntime: " + str(decision_time)
            + "\nreason: " + reason
            + "\nmode: " + str(self.mode)
            + "\ncurrent: " + str(current_price)
            + "\npeak_price: " + str(latest_peak.get("latest_body_peak_price"))
            + "\npeak_dir: " + str(latest_peak.get("direction"))
            + "\npeak_gap: " + str(latest_peak.get("gap"))
            + "\nRSI: " + str(rsi_1)
            + "\n" + m5_l_summary
            + "\n" + m5_s_summary
            + "\n" + h1_summary
            + "\nnote: top7 line order is active in live"
        )


    @staticmethod
    def line_summary_for_message(label, line_class, current_price):
        p = getattr(line_class, "p", gene.currency_pair(getattr(line_class, "pair", "USD_JPY")))
        lines = []
        for side, side_lines in (
            ("upper", line_class.upper_lines),
            ("lower", line_class.lower_lines),
        ):
            for line in side_lines[:3]:
                price = line.get("median_price")
                if price is None:
                    continue
                distance = abs(p.price_to_pips(float(price) - float(current_price)))
                lines.append({
                    "side": side,
                    "price": price,
                    "distance": distance,
                    "count": line.get("count"),
                    "strength": line.get("total_strength"),
                    "core_count": line.get("core_count"),
                    "core_strength": line.get("core_total_strength"),
                })

        if not lines:
            return label + ": no line"

        nearest = min(lines, key=lambda x: x["distance"])
        return (
            label
            + ": "
            + str(nearest["side"])
            + " price=" + str(p.round_price(float(nearest["price"])))
            + " gap=" + str(round(nearest["distance"], 1)) + "p"
            + " count=" + str(nearest["count"])
            + " strength=" + str(nearest["strength"])
            + " core_count=" + str(nearest["core_count"])
            + " core_strength=" + str(nearest["core_strength"])
        )

    def cal_units(self, lc_range, risk_yen=500, tag="s", yen_per_pip_per_lot=1000, ):
        """
        risk_yen縺ｯ譛螟ｧ縺ｮ雋縺鷹｡・
        tag縺ｯ豕ｨ譁・′繧｢繝励Μ縺九ｉ繧上°繧翫ｄ縺吶＞繧医≧縺ｫ縲∝ｼｷ蠑輔↓UNIT縺ｮ荳譯∫岼繧定ｪｿ謨ｴ縺吶ｋ縲Ｔ縺ｮ蝣ｴ蜷医・1縺具ｼ悶〕縺ｮ蝣ｴ蜷医・0縺具ｼ輔↓縺ｪ繧・
        yen_per_pip_per_lot:
            萓具ｼ峨ラ繝ｫ蜀・〒1繝ｭ繝・ヨ=1000騾夊ｲｨ縺ｪ繧臥ｴ・0蜀・pips
                1荳・夊ｲｨ縺ｪ繧臥ｴ・00蜀・pips
        """
        # 蝓ｺ譛ｬ逧・↑UNIT險育ｮ・
        doller_yen = 10000
        lc_pips = max(self.p.price_to_pips(lc_range), 0.000000001)  # 荳九・deveide0繧帝亟縺弱◆縺・
        # print("縲UNITS繧定ｨ育ｮ励☆繧・lc_range", lc_range, "pips", lc_pips, "險ｱ螳ｹ謳榊､ｱ", risk_yen)
        lot = risk_yen / (lc_pips * yen_per_pip_per_lot)
        units = int(lot * doller_yen)

        # 隱ｿ謨ｴ
        # 荳譯∫岼・・0縺ｧ蜑ｲ縺｣縺滉ｽ吶ｊ・峨ｒ蜿門ｾ・
        last_digit = units % 10
        # 荳譯∫岼繧帝勁縺・◆縲悟香縺ｮ菴堺ｻ･荳翫阪・繝吶・繧ｹ謨ｰ蛟､
        base = (units // 10) * 10
        if tag == "l":
            # 0縺・縲∬ｿ代＞譁ｹ縺ｫ蜷医ｏ縺帙ｋ
            if last_digit <= 2 or last_digit >= 8:
                # 0縺ｫ霑代＞蝣ｴ蜷茨ｼ・, 9, 0, 1, 2・・
                # 窶ｻ 8, 9縺ｮ蝣ｴ蜷医・谺｡縺ｮ譯√・0縺ｫ霑代＞縺ｮ縺ｧ縲∝屁謐ｨ莠泌・縺ｫ霑代＞蜃ｦ逅・
                new_units = round(units / 5) * 5
            else:
                # 5縺ｫ霑代＞蝣ｴ蜷茨ｼ・, 4, 5, 6, 7・・
                new_units = base + 5

            # 繧ｷ繝ｳ繝励Ν縺ｫ譖ｸ縺上↑繧会ｼ・units = 5 * round(units / 5)
            units = int(5 * round(units / 5))

        elif tag == "s":
            # 1縺・縲∬ｿ代＞譁ｹ縺ｫ蜷医ｏ縺帙ｋ
            # units縺九ｉ1繧貞ｼ輔￥縺ｨ縲・縺・縺ｫ蜷医ｏ縺帙ｋ蝠城｡後阪↓鄂ｮ縺肴鋤縺医ｉ繧後ｋ
            adjusted = 5 * round((units - 1) / 5) + 1
            units = int(adjusted)

        return units
    
    
class LineStrengthCal:
    def __init__(self, candle_analysis_class, foot, time_before_foot_count=30):
        print("  ")
        print("  LINE強度の探索", time_before_foot_count, "足", foot)
        mode = "live"
        if mode == "live":
            from_i = 0
            self.mode = "live"
        else:
            from_i = 1
            self.mode = "inspection"
        self.s = "     "
        self.foot = foot
        self.max_line_price_gap_pips = None
        self.pair = getattr(candle_analysis_class, "pair", "USD_JPY")
        self.p = gene.currency_pair(self.pair)
        self.candle_analysis_class = candle_analysis_class
        self.time_before_foot_count = time_before_foot_count

        self.candle_meta_m5 = candle_analysis_class.candle_meta_class  
        self.peaks_class_m5 = candle_analysis_class.peaks_class 
        self.peaks_m5 = self.peaks_class_m5.peaks_original
        self.df_r_m5 = candle_analysis_class.d5_df_r[1:]  

        self.candle_meta_h1 = candle_analysis_class.candle_meta_class_hour
        self.peaks_class_h1 = candle_analysis_class.peaks_class_hour
        self.peaks_h1 = candle_analysis_class.peaks_class_hour.peaks_original
        self.df_r_h1 = candle_analysis_class.h1_df_r[from_i:]

        self.candle_meta_m30 = candle_analysis_class.candle_meta_class_m30
        self.peaks_class_m30 = candle_analysis_class.peaks_class_m30
        self.peaks_m30 = candle_analysis_class.peaks_class_m30.peaks_original
        self.df_r_m30 = candle_analysis_class.d30_df_r[from_i:]

        if foot == "m5":
            self.peaks_class = self.peaks_class_m5
            self.peaks = self.peaks_m5
            self.df_r = self.df_r_m5
            self.threshold = 1
            self.max_line_price_gap_pips = 2
        elif foot == "h1":
            self.peaks_class = self.peaks_class_h1
            self.peaks = self.peaks_h1
            self.df_r = self.df_r_h1
            self.threshold = 2.5
        elif foot == "m30":
            self.peaks_class = self.peaks_class_m30
            self.peaks = self.peaks_m30
            self.df_r = self.df_r_m30
            self.threshold = 3

        self.min_line_peak_strength = 2
        self.current_time = candle_analysis_class.d5_df_r.iloc[0]['time_jp']  
        self.current_price = candle_analysis_class.current_price  # 検証の場合はdf[0]['close']を使用、それ以外は最新価格を使用
        self.latest_peak_dir = self.peaks[0]['direction']

        # lines_wrap
        self.filtered_peaks = []  # 変数作成
        self.filterd_df = None  # 変数作成
        self.upper_lines = []
        self.lower_lines = []
        self.tp_lines = []
        self.lc_lines = []
        self.all_lines = []  

        # lines_df_analysis
        self.max_inner_high = 0
        self.max_highest = 0
        self.min_inner_low = 99999
        self.min_lowest = 99999
        self.ratio = 0


        self.lines_wrap_up()  # 
        self.line_each_analysis()  #
        self.lines_df_analysis()  # 

        print("    All LINES", len(self.all_lines))
        for i, g in enumerate(self.all_lines):
            print(
                self.s,
                f"Group {i}: median_price = {g['median_price']:.3f}, "
                f"median = {g['median']:.3f}, "
                f"strength = {g['total_strength']}, "
                f"count = {g['count']}, "
                f"ave_strength = {g['ave_strength']}, "
                f"oldest_time = {g['oldest_time']}, " 
                # f"prices = {', '.join(map(str, g['prices']))}, "
                f"is_flipped_line = {g['is_flipped_line']},  "
                f"price_gap = {g['price_gap']}, "
                # f"dirs = {', '.join(map(str, g['dirs']))}, "
                f"dirs_grouped = {', '.join(map(str, g['dirs_grouped']))}"
                # f"is_flipped_line_st = {g['is_flipped_line_st']},  "
            )
            for j, info in enumerate(g['prices_info']):
                print(
                    self.s,
                    "  ",
                    f"time={info['latest_time_jp']}"
                    f"  [{j}] price={info['latest_body_peak_price']}, "
                    f"direction={info['direction']}, "
                    f"strength={info['peak_strength']}, "
                    f"time={info['latest_time_jp']}"
                )

    def line_each_analysis(self):
        print("    蛟句挨LINE蛻・梵")
        all_lines = self.all_lines  # 鄂ｮ縺肴鋤縺・
        # 邨先棡逕ｨ
        for i, item in enumerate(all_lines):
            # print("    K", item['median_price'])
            is_flipped_line = False
            # 蜷・Λ繧､繝ｳ繧貞腰蜩√〒隕九※縺・￥
            dirs = item['dirs_grouped']
            if item['count'] >= 3 and len(dirs) >= 2:
                # 3蛟倶ｻ･荳翫≠繧句ｴ蜷医∝髄縺咲ｭ峨ｒ讀懆ｨ弱＠縺ｦ縺・￥
                if dirs[0] * dirs[1] < 0 and item['prices_info'][0]["peak_strength"]>2:
                    # print("      K", item['median_price'], dirs[0], dirs[1])
                    # 豁｣雋縺ｮ謨ｰ縺檎焚縺ｪ縺｣縺ｦ縺・ｋ
                    if abs(dirs[1]) >= 2:
                        is_flipped_line = True
            # 邨先棡莉倅ｸ弱☆繧・
            item['is_flipped_line'] = is_flipped_line
            item['is_flipped_line_st'] = 0

    def lines_df_analysis(self):
        """
        邂怜・縺励◆繝ｩ繧､繝ｳ繧貞・譫舌☆繧九Ｍines_wrap_up髢｢謨ｰ縺ｧ邂怜・縺励◆繝ｩ繧､繝ｳ縺ｮ諠・ｱ繧偵∫峩霑代・萓｡譬ｼ縺ｮ蜍輔″縺ｪ縺ｩ縺ｨ邨・∩蜷医ｏ縺帙※蛻・梵縺励※縺ｿ繧・
        """
        # 萓九∴縺ｰ縲√Λ繧､繝ｳ縺ｮ霑代＆縺ｨ縲∫峩霑代・萓｡譬ｼ縺ｮ蜍輔″縺九ｉ縲√←縺ｮ繝ｩ繧､繝ｳ縺悟柑縺・※縺・ｋ縺九ｒ蛻・梵縺励※縺ｿ繧・
        # 逶ｴ霑代・萓｡譬ｼ縺ｮ蜍輔″縺ｯ縲∽ｾ九∴縺ｰ縲∫峩霑代・謨ｰ譛ｬ縺ｮ繝ｭ繝ｼ繧ｽ繧ｯ雜ｳ縺ｮ鬮伜､縺ｨ螳牙､縺九ｉ隕九※縺ｿ繧・
        print("    LINES蛻・梵")
        df_filterd = self.filterd_df
        all_lines = self.all_lines

        # peaks縺ｮ荳ｭ縺ｧ譛鬮伜､縲∵怙菴弱ｒ蜿門ｾ励☆繧・
        self.max_inner_high = df_filterd['inner_high'].max()
        self.max_highest = df_filterd['high'].max()
        self.min_inner_low = df_filterd['inner_low'].min()
        self.min_lowest = df_filterd['low'].min()
        self.df_high_low_range = self.p.price_to_pips(self.max_highest - self.min_lowest)  # 萓｡譬ｼ縺ｧ險育ｮ怜ｾ後｝ips縺ｧ菫晏ｭ倥☆繧・
        print("     譛鬮伜､", self.max_inner_high, "(", self.max_highest, ")", "譛菴主､", self.min_inner_low, "(", self.min_lowest, ")")
 
        # line縺ｧ縺ｮ譛鬮伜､縺ｨ譛菴主､縺ｮGap繧堤ｮ怜・
        if len(all_lines) == 0:
            print("ALL LINES is empty")
            return 0
        self.lines_high_low_range = self.p.round_price(abs(all_lines[0]['median'] - all_lines[-1]['median']))

        # 豈皮紫
        self.ratio = round(self.lines_high_low_range / self.df_high_low_range, 2)
        
        print("     line range ratio", self.ratio, "df_range", self.df_high_low_range, "line_range", self.lines_high_low_range)

        # 荳雁・縺ｮ隧ｰ縺ｾ繧雁・蜷医∽ｸ句・縺ｮ隧ｰ縺ｾ繧雁・蜷医ｒ邂怜・
        highest = self.max_inner_high  # max_highest縺ｨ蜈･繧梧崛縺医〒縺阪ｋ繧医≧縺ｫ
        lowest = self.min_inner_low
        dir = self.latest_peak_dir
        if dir == 1:  # 逶ｴ霑叢eak縺御ｸ雁髄縺阪・蝣ｴ蜷医〕ines縺ｮ荳逡ｪ荳翫′譛鬮伜､
            upper_gap = self.p.price_to_pips(highest - all_lines[0]['median_price'])
            lower_gap = self.p.price_to_pips(all_lines[-1]['median_price'] - lowest)
            print("     HIGH-LOW", highest, "-", lowest, "LINE_high_low", all_lines[0]['median_price'], "-", all_lines[-1]['median_price'])
        else:  # 逶ｴ霑叢eak縺御ｸ句髄縺阪・蝣ｴ蜷医・
            upper_gap = self.p.price_to_pips(highest - all_lines[-1]['median_price'])
            lower_gap = self.p.price_to_pips(all_lines[0]['median_price'] - lowest)
            # print("     HIGH", highest, "-", all_lines[-1]['median_price'], "LOW", all_lines[0]['median_price'], "-", lowest)
            print("     HIGH-LOW", highest, "-", lowest, "LINE_high_low", all_lines[-1]['median_price'], "-", all_lines[0]['median_price'])
        line_ratio = self.p.round_price(abs(all_lines[0]['median_price'] - all_lines[-1]['median_price']))
        upper_ratio = round(upper_gap / self.df_high_low_range, 2)
        lower_ratio = round(lower_gap / self.df_high_low_range, 2)
        print("     line_ratio", line_ratio, "gap_pips", self.p.price_to_pips(abs(all_lines[0]['median_price'] - all_lines[-1]['median_price'])))
        print("     upper_gap_pips", upper_gap, "lower_gap_pips", lower_gap)
        print("     upper_gap_ratio", upper_ratio, "lower_gap_ratio", lower_ratio) 

        # 迴ｾ蝨ｨ萓｡譬ｼ縺後←縺薙↓縺・ｋ縺九・遒ｺ隱・
        current_price = self.current_price
        upper_lines = self.upper_lines
        lower_lines = self.lower_lines
        highest = 0 if len(upper_lines) == 0 else self.p.round_price(upper_lines[0]['median_price'])
        lowest = 9999 if len(lower_lines) == 0 else self.p.round_price(lower_lines[-1]['median_price'])
        is_inner_lines = False
        if lowest <= current_price <= highest:
            is_inner_lines = True
        print("     current price is inner lines", is_inner_lines)

        # 蛻､螳・
        if is_inner_lines:
            # lines縺ｮ蜀・・竍偵Ξ繝ｳ繧ｸ縺ｮ蜿ｯ閭ｽ諤ｧ縺悟・縺ｦ縺上ｋ
            if upper_ratio <= 0.2 and lower_ratio >= 0.4:
                # 繝ｬ繝ｳ繧ｸ縺御ｸ企Κ縺ｫ縺ゅｋ
                print("      range is upper side")
                pass
            elif lower_ratio <= 0.2 and upper_ratio >= 0.4:
                # 繝ｬ繝ｳ繧ｸ縺御ｸ矩Κ縺ｫ縺ゅｋ
                print("      繝ｬ繝ｳ繧ｸ縺御ｸ矩Κ縺ｫ縺ゅｊ縲∫峩霑代ｂ縺昴・荳ｭ")
                pass
            elif upper_ratio <= 0.2 and lower_ratio <= 0.2:
                # 繝ｬ繝ｳ繧ｸ縺檎ｶ咏ｶ壹＠縺ｦ縺・ｋ
                print("      蜈ｨ菴鍋噪縺ｫ縺ｾ縺ｨ縺ｾ縺｣縺滓─縺倥∫峩霑代ｂ縺昴・荳ｭ")
                pass
            elif upper_ratio >= 0.4 and lower_ratio >= 0.4:
                # 闕偵ｌ縺ｦ縺・ｋ縲∵ｿ縺励ａ縺ｮ繝ｬ繝ｳ繧ｸ
                print("      蟆代＠豼縺励ａ縺ｮ蜍輔″縲∫峩霑代ｂ縺昴・荳ｭ")
                pass
        else:
            # lines縺ｮ螟門・縺ｫ縺ゅｋ
            print("      current price is outside lines")


    def lines_wrap_up(self):
        """
        Line繧呈爾邏｢縺吶ｋ
        """
        # 蠢・ｦ√↑諠・ｱ繧貞､画焚蛹・
        base_price = self.current_price
        time_before_foot_count = self.time_before_foot_count
        threshold = self.threshold if self.foot == "m5" else 3  # pips縺ｧ謖・ｮ・
        
        # 繝斐・繧ｯ縺ｮ蜿門ｾ・
        peaks = self.peaks_class.peaks_original  # 菴ｿ縺・ｶｳ縺ｮ驕ｸ謚・
        if threshold is None:
            threshold = self.threshold
        
        # 笘・eaks繧堤ｵ槭ｊ霎ｼ縺ｿ(謖・ｮ壹・逶ｴ霑代・雜ｳ謨ｰ縺ｧ繝輔ぅ繝ｫ繧ｿ縲ょ悄譌･謖溘・縺ｨ譎る俣謖・ｮ壹′縺翫°縺励￥縺ｪ繧九・縺ｧ雜ｳ謨ｰ縲りｶｳ謨ｰ縺九ｉ譎る俣繧堤ｮ怜・)
        df_filterd = self.df_r[0:time_before_foot_count]
        oldest_time = datetime.strptime(df_filterd.iloc[-1]['time_jp'], "%Y/%m/%d %H:%M:%S")
        current_time = datetime.strptime(self.df_r.iloc[0]['time_jp'], "%Y/%m/%d %H:%M:%S")
        time_diff = (current_time - oldest_time).total_seconds() / 3600  # 譎る俣蟾ｮ繧呈凾髢灘腰菴阪〒險育ｮ・
        border_time = datetime.strptime(self.current_time, '%Y/%m/%d %H:%M:%S') - timedelta(hours=time_diff)  # peak繧堤ｮ怜・縺吶ｋ縺溘ａ縺ｮ
        peaks = [  # peak繧呈凾髢薙〒邨槭ｋ・育ｵｶ蟇ｾ蠢・ｦ・ｼ・
            d for d in peaks
            if datetime.strptime(d['latest_time_jp'], '%Y/%m/%d %H:%M:%S') > border_time
        ]
        latest_peak = self.peaks[0]
        peaks = [
            d for d in peaks
            if not (
                d.get("latest_time_jp") == latest_peak.get("latest_time_jp")
                and d.get("latest_body_peak_price") == latest_peak.get("latest_body_peak_price")
                and d.get("direction") == latest_peak.get("direction")
            )
        ]
        peaks_before_strength_filter = len(peaks)
        peaks = [  # peak繧担trength縺ｧ1繧医ｊ螟ｧ縺阪＞繧ゅ・縺ｫ邨槭ｋ・医ユ繧ｹ繝茨ｼ・
            d for d in peaks
            if float(d.get('peak_strength', 0)) >= 0
        ]
        print("    Line peak strength filter", self.min_line_peak_strength, peaks_before_strength_filter, "->", len(peaks))
        self.filtered_peaks = peaks
        self.filterd_df = df_filterd

        # 繝ｩ繧､繝ｳ縺ｮ蜃ｦ逅・
        print("    Line search base", base_price, "latest_peak_dir", self.latest_peak_dir, "border_time", border_time, "time_DIFF", time_diff)
        # upper_base_price = base_price + (self.latest_peak_dir * self.p.pips_to_price(1))
        # print("     Upper蝓ｺ貅・, upper_base_price)
        # upper_lines = self.search_upper_lines(upper_base_price, peaks, threshold)  # target_price
        
        # lower_base_price = base_price - (self.latest_peak_dir * self.p.pips_to_price(1))
        # print("     Lower蝓ｺ貅・, lower_base_price)
        # lower_lines = self.search_lower_lines(lower_base_price, peaks, threshold)  # target_price

        if self.latest_peak_dir == 1:
            # 逶ｴ霑台ｾ｡譬ｼ・晄ｳｨ譁・ｾ｡譬ｼ縺ｮ蝣ｴ蜷・縺・★繧後ｂ逶ｴ霑台ｾ｡譬ｼ縺九ｉ霑代＞鬆・↓荳ｦ繧薙〒縺・ｋ縲・
            upper_base_price = base_price - (self.latest_peak_dir * self.p.pips_to_price(1))  # 蛻ｩ遒ｺ繧貞ｰ代＠謇句燕縺九ｉ
            print("     Upper base", upper_base_price)
            upper_lines = self.search_upper_lines(upper_base_price, peaks, threshold)  # target_price
            
            lower_base_price = base_price - (self.latest_peak_dir * self.p.pips_to_price(1))
            print("     Lower base", lower_base_price)
            lower_lines = self.search_lower_lines(lower_base_price, peaks, threshold)  # target_price
            self.tp_lines = upper_lines
            self.lc_lines = lower_lines
        else:
            # 逶ｴ霑台ｾ｡譬ｼ・晄ｳｨ譁・ｾ｡譬ｼ縺ｮ蝣ｴ蜷・
            upper_base_price = base_price - (self.latest_peak_dir * self.p.pips_to_price(1))  # 蛻ｩ遒ｺ繧貞ｰ代＠謇句燕縺九ｉ
            print("     Upper base", upper_base_price)
            upper_lines = self.search_upper_lines(upper_base_price, peaks, threshold)  # target_price
            
            lower_base_price = base_price - (self.latest_peak_dir * self.p.pips_to_price(1))
            print("     Lower base", lower_base_price)
            lower_lines = self.search_lower_lines(lower_base_price, peaks, threshold)  # target_price
            self.tp_lines = lower_lines
            self.lc_lines = upper_lines
        self.lower_lines = lower_lines
        self.upper_lines = upper_lines

        # ALL縺ｮ繝ｩ繧､繝ｳ繧剃ｽ懊ｋ
        if self.latest_peak_dir == 1:
            # upper_lines: median 縺昴・縺ｾ縺ｾ・域・鬆・竊・髯埼・↓蜿崎ｻ｢・・
            # lower_lines: median 縺ｫ - 繧偵▽縺代※・磯剄鬆・・縺ｾ縺ｾ・・
            reversed_upper = list(reversed(self.upper_lines))
            negated_lower = [
                {**line, 'median': -line['median']}
                for line in self.lower_lines
            ]
            combined = reversed_upper + negated_lower
        elif self.latest_peak_dir == -1:
            # lower_lines: median 縺昴・縺ｾ縺ｾ・域・鬆・竊・蜿崎ｻ｢縺励※髯埼・↓・・
            # upper_lines: median 縺ｫ - 繧偵▽縺代※・域・鬆・・縺ｾ縺ｾ蜿崎ｻ｢縺帙★縲√◎縺ｮ縺ｾ縺ｾ繝槭う繝翫せ・・
            reversed_lower = list(reversed(self.lower_lines))
            negated_upper = [
                {**line, 'median': -line['median']}
                for line in self.upper_lines
            ]
            combined = reversed_lower + negated_upper
        self.all_lines = combined


    def search_upper_lines(self, base_price, peaks, threshold=None):
        # print("    UpperLines讀懃ｴ｢")
        # 繧ｰ繝ｫ繝ｼ繝怜喧
        minus_groups = self.make_same_price_group_core_first(
            peaks=peaks,
            upper_lower=1,  # base_price繧医ｊ荳句・
            target_price=base_price,
            threshold=threshold,
            sort_direction=1  # 譏・・
        )
        # 蠑ｱ縺吶℃繧九げ繝ｫ繝ｼ繝励・謗帝勁縺吶ｋ
        # filtered = [d for d in minus_groups if (d["ave_strength"] >= 2 and d['count'] >= 2) or d["total_strength"] >= 10]
        filtered = [d for d in minus_groups if d["ave_strength"] >= 0 and d['count'] >= 1]
        return filtered

    def search_lower_lines(self, base_price, peaks, threshold=None):
        # print("    LowerLines讀懃ｴ｢")
        # 繧ｰ繝ｫ繝ｼ繝怜喧
        minus_groups = self.make_same_price_group_core_first(
            peaks=peaks,
            upper_lower=-1,  # base_price繧医ｊ荳句・
            target_price=base_price,
            threshold=threshold,
            sort_direction=-1  # 髯埼・
        )
        # 蠑ｱ縺吶℃繧九げ繝ｫ繝ｼ繝励・謗帝勁縺吶ｋ
        # filtered = [d for d in minus_groups if (d["ave_strength"] >= 2 and d['count'] >= 2) or d["total_strength"] >= 10]
        filtered = [d for d in minus_groups if d["ave_strength"] >= 0 and d['count'] >= 1]
        return filtered

    def make_same_price_group_core_first(self, peaks,
                            upper_lower,
                            target_price,
                            threshold=3,
                            direction_filter=None,
                            sort_direction=-1,
                            core_strength=5,
                            attach_strength=2,
                            ):
        if upper_lower == -1:
            filtered_peaks = [
                p for p in peaks
                if float(p['latest_body_peak_price']) < target_price
            ]
        else:
            filtered_peaks = [
                p for p in peaks
                if float(p['latest_body_peak_price']) >= target_price
            ]

        if direction_filter is not None:
            filtered_peaks = [
                p for p in filtered_peaks
                if p['direction'] == direction_filter
            ]

        if not filtered_peaks:
            return []

        core_peaks = [
            p for p in filtered_peaks
            if float(p.get('peak_strength', 0)) >= core_strength
        ]
        attach_peaks = [
            p for p in filtered_peaks
            if float(p.get('peak_strength', 0)) <= attach_strength
        ]

        if not core_peaks:
            return []

        results = self.make_same_price_group(
            peaks=core_peaks,
            upper_lower=upper_lower,
            target_price=target_price,
            threshold=threshold,
            direction_filter=direction_filter,
            sort_direction=sort_direction,
        )

        for result in results:
            result["core_median_price"] = result["median_price"]
            result["core_count"] = result["count"]
            result["core_total_strength"] = result["total_strength"]

        attached_peak_ids = set()
        for peak in attach_peaks:
            peak_price_pips = self.p.price_to_pips(float(peak['latest_body_peak_price']))
            nearest_result = None
            nearest_gap = None
            for result in results:
                core_price_pips = self.p.price_to_pips(float(result["core_median_price"]))
                gap = abs(peak_price_pips - core_price_pips)
                if gap <= threshold and (nearest_gap is None or gap < nearest_gap):
                    nearest_result = result
                    nearest_gap = gap

            if nearest_result is None:
                continue

            peak_id = (peak.get("latest_time_jp"), peak.get("latest_body_peak_price"), peak.get("direction"))
            if peak_id in attached_peak_ids:
                continue
            if not self.can_add_peak_to_line(nearest_result, peak):
                continue
            attached_peak_ids.add(peak_id)
            nearest_result["prices_info"].append(peak)
            self.refresh_line_group(nearest_result, target_price, threshold)

        results = sorted(
            results,
            key=lambda x: x['median_price'],
            reverse=(sort_direction == -1)
        )
        print(
            "    Core line grouping",
            "core>=", core_strength,
            "attach<=", attach_strength,
            "peaks", len(filtered_peaks),
            "core", len(core_peaks),
            "attach", len(attach_peaks),
            "lines", len(results),
        )
        return results

    def can_add_peak_to_line(self, result, peak):
        if self.max_line_price_gap_pips is None:
            return True

        prices = [
            float(x["latest_body_peak_price"])
            for x in result.get("prices_info", [])
        ]
        prices.append(float(peak["latest_body_peak_price"]))
        price_gap = self.p.price_to_pips(max(prices) - min(prices))
        return price_gap <= self.max_line_price_gap_pips

    def refresh_line_group(self, result, target_price, threshold):
        from itertools import groupby

        sorted_group_items = sorted(
            result["prices_info"],
            key=lambda x: datetime.strptime(x['latest_time_jp'], '%Y/%m/%d %H:%M:%S'),
            reverse=True
        )
        prices = [float(x['latest_body_peak_price']) for x in sorted_group_items]
        dirs = [x['direction'] for x in sorted_group_items]
        prices_pips = [self.p.price_to_pips(p) for p in prices]
        latest_times = [
            datetime.strptime(x['latest_time_jp'], '%Y/%m/%d %H:%M:%S')
            for x in sorted_group_items
        ]
        median_price = median(prices)
        median_price_pips = median(prices_pips)
        target_price_pips = self.p.price_to_pips(target_price)

        result["median_price"] = median_price
        result["median_p"] = self.p.price_to_pips(abs(target_price - median_price))
        result["median"] = abs(target_price_pips - median_price_pips)
        result["total_strength"] = sum(float(x['peak_strength']) for x in sorted_group_items)
        result["count"] = len(sorted_group_items)
        result["ave_strength"] = round(result["total_strength"] / result["count"] if result["count"] else 0, 1)
        result["prices"] = prices
        result["price_gap"] = self.p.price_to_pips(max(prices) - min(prices))
        result["prices_info"] = sorted_group_items
        result["dirs"] = dirs
        result["dirs_grouped"] = [sum(group) for key, group in groupby(dirs)]
        result["range_min"] = self.p.price_to_pips(median_price) - threshold
        result["range_max"] = self.p.price_to_pips(median_price) + threshold
        result["newest_time"] = max(latest_times).strftime('%Y/%m/%d %H:%M:%S')
        result["oldest_time"] = min(latest_times).strftime('%Y/%m/%d %H:%M:%S')

    def make_same_price_group(self, peaks,
                            upper_lower,
                            target_price,
                            threshold=3,  # pips蜊倅ｽ搾ｼ亥燕蠕後・遽・峇・・
                            direction_filter=None,
                            sort_direction=-1,
                            ):
        # target_price繧恥ips縺ｫ螟画鋤・亥渕貅也せ縺ｨ縺励※・・
        target_price_pips = self.p.price_to_pips(target_price)

        if upper_lower == -1:
            # 荳句・縺ｮ蝣ｴ蜷・
            filtered_peaks = [
                p for p in peaks
                if float(p['latest_body_peak_price']) < target_price
            ]
        else:
            # 荳雁・縺ｮ蝣ｴ蜷・
            filtered_peaks = [
                p for p in peaks
                if float(p['latest_body_peak_price']) >= target_price
            ]

        if direction_filter is not None:
            filtered_peaks = [
                p for p in filtered_peaks
                if p['direction'] == direction_filter
            ]

        if not filtered_peaks:
            return []

        # 萓｡譬ｼ縺ｧ繧ｽ繝ｼ繝茨ｼ磯剄鬆・ｼ・
        sorted_peaks = sorted(
            filtered_peaks,
            key=lambda x: float(x['latest_body_peak_price']),
            reverse=True
        )

        used_indices = set()  # 譌｢縺ｫ菴ｿ繧上ｌ縺溘う繝ｳ繝・ャ繧ｯ繧ｹ
        results = []

        for i, p in enumerate(sorted_peaks):
            if i in used_indices:
                continue

            center_price = float(p['latest_body_peak_price'])
            center_price_pips = self.p.price_to_pips(center_price)
            
            # 荳ｭ蠢・ｾ｡譬ｼ縺ｮ蜑榊ｾ荊hreshold縺ｮ遽・峇縺ｫ縺ゅｋ繧ゅ・繧帝寔繧√ｋ
            group_items = []
            group_indices = []

            for j, candidate in enumerate(sorted_peaks):
                if j not in used_indices:
                    candidate_price = float(candidate['latest_body_peak_price'])
                    candidate_price_pips = self.p.price_to_pips(candidate_price)
                    
                    # pips蜊倅ｽ阪〒蜑榊ｾ荊hreshold縺ｮ遽・峇蜀・°遒ｺ隱・
                    if abs(candidate_price_pips - center_price_pips) <= threshold:
                        group_items.append(candidate)
                        group_indices.append(j)

            if group_items:
                # 譎らｳｻ蛻鈴・↓謌ｻ繧・
                sorted_group_items = sorted(
                    group_items,
                    key=lambda x: datetime.strptime(x['latest_time_jp'], '%Y/%m/%d %H:%M:%S'),
                    reverse=True
                )
                
                prices = [float(x['latest_body_peak_price']) for x in sorted_group_items]
                dirs = [x['direction'] for x in sorted_group_items]
                prices_pips = [self.p.price_to_pips(p) for p in prices]

                latest_times = [
                    datetime.strptime(
                        x['latest_time_jp'],
                        '%Y/%m/%d %H:%M:%S'
                    )
                    for x in sorted_group_items
                ]

                median_price = median(prices)
                median_price_pips = median(prices_pips)
                median_diff_pips = abs(target_price_pips - median_price_pips)
                price_gap = self.p.price_to_pips(max(prices) - min(prices))

                results.append({
                    'median_price': median_price,
                    'median_p': self.p.price_to_pips(abs(target_price - median_price)),
                    'median': median_diff_pips,
                    "total_strength": sum(float(x['peak_strength']) for x in sorted_group_items),
                    'count': len(sorted_group_items),
                    "ave_strength": round(
                        sum(float(x['peak_strength']) for x in sorted_group_items) / len(sorted_group_items) 
                        if sorted_group_items else 0, 1
                    ),
                    'prices': prices,
                    'price_gap': price_gap,
                    'prices_info': sorted_group_items,
                    'dirs': dirs,
                    'range_min': center_price_pips - threshold,
                    'range_max': center_price_pips + threshold,
                    'newest_time': max(latest_times).strftime('%Y/%m/%d %H:%M:%S'),
                    'oldest_time': min(latest_times).strftime('%Y/%m/%d %H:%M:%S'),
                })
                
                # 縺薙・繧ｰ繝ｫ繝ｼ繝励↓螻槭☆繧九ｂ縺ｮ繧剃ｽｿ逕ｨ貂医∩縺ｫ
                used_indices.update(group_indices)

        # 騾｣邯壹＠縺溷酔縺伜､繧偵げ繝ｫ繝ｼ繝怜喧縺励※蜷郁ｨ・
        from itertools import groupby
        for r in results:
            r['dirs_grouped'] = [sum(group) for key, group in groupby(r['dirs'])]

        # 繧ｰ繝ｫ繝ｼ繝怜喧縺輔ｌ縺ｪ縺九▲縺溘ｂ縺ｮ繧・蛟九・繧ｰ繝ｫ繝ｼ繝励→縺励※霑ｽ蜉
        for i, peak in enumerate(sorted_peaks):
            if i not in used_indices:
                price = float(peak['latest_body_peak_price'])
                price_pips = self.p.price_to_pips(price)
                
                latest_time = datetime.strptime(
                    peak['latest_time_jp'],
                    '%Y/%m/%d %H:%M:%S'
                )
                
                results.append({
                    'median_price': price,
                    'median_p': self.p.price_to_pips(abs(target_price - price)),
                    'median': abs(target_price_pips - price_pips),
                    "total_strength": float(peak['peak_strength']),
                    'count': 1,
                    "ave_strength": float(peak['peak_strength']),
                    'prices': [price],
                    'price_gap': 0,
                    'prices_info': [peak],
                    'dirs': [peak['direction']],
                    'dirs_grouped': [peak['direction']],
                    'range_min': price_pips - threshold,
                    'range_max': price_pips + threshold,
                    'newest_time': latest_time.strftime('%Y/%m/%d %H:%M:%S'),
                    'oldest_time': latest_time.strftime('%Y/%m/%d %H:%M:%S'),
                })
        # print("TEST陦ｨ遉ｺ")
        # for i, item in enumerate(results):
        #     print(" ", item)

        results = sorted(
            results,
            key=lambda x: x['median_price'],  # 萓｡譬ｼ縺ｧ荳ｦ縺ｳ譖ｿ縺・
            reverse=(sort_direction == -1)
        )
        
        return results
