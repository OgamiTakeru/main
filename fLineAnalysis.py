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

gl_unis_std = 0.1  # OrderCreateのベーシックUnitは10000ドル。それにかける倍率


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

    def is_target(self, line_side, line):
        raise NotImplementedError

    def get_tp_pips(self):
        return self.tp_pips

    def get_direction(self, line_side):
        return -1 if line_side == "upper" else 1

    def get_target_price(self, line_price, line_side):
        return line_price

    def build_candidates(self, line_class, current_price):
        p = gene.USD_JPY
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

    def get_tp_pips(self):
        spread_pips = 0.8
        rr = 1.65
        return round(rr * (self.lc_pips + spread_pips) + spread_pips, 1)

    def is_target(self, line_side, line):
        is_flipped = line.get("is_flipped_line")
        core_count = int(line.get("core_count") or 0)
        core_total_strength = float(line.get("core_total_strength") or 0)
        return (
            is_flipped is False
            and line_side in ("upper", "lower")
            and core_count >= 1
            and core_total_strength >= 5
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

    def is_target(self, line_side, line):
        is_flipped = line.get("is_flipped_line")
        count = int(line.get("count") or 0)
        core_count = int(line.get("core_count") or 0)
        core_total_strength = float(line.get("core_total_strength") or 0)
        return (
            is_flipped is False
            and line_side in ("upper", "lower")
            and count >= 1
            and core_count >= 1
            and core_total_strength >= 5
        )


class M5BreakoutLineOrderStrategy(M5LineOrderStrategy):
    name_prefix = "M5LineBreakout"
    line_strategy = "m5_breakout_peakdir_allcount"
    entry_type = "breakout"
    order_type = "STOP"
    entry_offset_pips = 1.5

    def get_direction(self, line_side):
        return 1 if line_side == "upper" else -1

    def get_target_price(self, line_price, line_side):
        p = gene.USD_JPY
        direction = self.get_direction(line_side)
        return line_price + (
            direction * p.pips_to_price(self.entry_offset_pips)
        )

class LineOrderCoordinator:
    duplicate_threshold_pips = 3
    h1_strong_threshold = 10

    def __init__(self, analysis):
        self.analysis = analysis

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
    ):
        if candidate["line_strategy"] != line_strategy:
            return False
        if candidate["line_side"] != "upper":
            return False
        if candidate.get("latest_peak_dir") != 1:
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
        p = gene.USD_JPY
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

    @staticmethod
    def _h1_line_fields(prefix, item, base_price):
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

        p = gene.USD_JPY
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
        p = gene.USD_JPY
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

    @staticmethod
    def session_order_policy(session_name):
        # Keep all sessions neutral for now. Change these values after validation.
        policies = {
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

    @staticmethod
    def _apply_rr_to_tp(order_class, rr):
        p = gene.USD_JPY
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
        p = gene.USD_JPY
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
        print(" ■メインアナリシス", mode)

        # ■■■基本情報の取得
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

        self.ca5 = candle_analysis.candle_meta_class  # peaks以外の部分。cal_move_ave関数を使う用
        self.peaks_class = candle_analysis.peaks_class  # peaks_classだけを抽出
        self.df_r_m5 = candle_analysis.d5_df_r[1:]  # 5分足はひとつ前ので固定！！（Liveでも）

        self.ca60 = candle_analysis.candle_meta_class_hour
        self.peaks_class_hour = candle_analysis.peaks_class_hour
        self.df_r_h1 = candle_analysis.h1_df_r[from_i:]

        self.ca30 = candle_analysis.candle_meta_class_m30
        self.peaks_class_m30 = candle_analysis.peaks_class_m30
        self.df_r_m30 = candle_analysis.d30_df_r[from_i:]

        self.current_time = candle_analysis.d5_df_r.iloc[0]['time_jp']  # 5分足で判断(0行目を利用）
        self.current_price = candle_analysis.current_price  # candleAnalysisからとる（本番の場合はAPIで最新、解析の場合はclose価格)
        self.mode = mode  # 検証かどうか
        self.pair = "USD_JPY"
        print("current_priceの確認(main_analysis)", self.current_price, "移動平均", self.ca5.cal_move_ave(1))
        # 抵抗線関係
        self.exist_strong_line = False
        # BB関係
        self.latest_exe_bb_h1_row = None
        self.bb_h1_class = None
        self.bb_m5_class = None
        self.bb5_cross_pattern = 0  # 1が強め、2が強いのあったが折り返し

        # ■■■基本結果の変数の宣言
        self.take_position_flag = False
        self.exe_order_classes = []
        self.send_message_at_last = ""

        # ■■■　現在の勝ち負けの様子
        if self.position_control_class is None:
            # print("過去の勝ち負けは気にしない（単発のテストのため情報なし）")
            pass
        else:
            position_one = self.position_control_class.position_classes[0]  # positionの先頭を取得（どれでもいい）
            p = position_one.history_plus_minus
            # print("過去の勝ち負けの履歴", position_one.history_plus_minus)
            if len(p) >= 6:
                # print("勝ち負けの直近三個", p[-1], p[-2], p[-3], p[-4], p[-5], p[-6])
                pass
            else:
                pass
                # print("勝ち負けの直近三個", p[-1])
            # クラスが格納されるように変更したので、クラスのテスト
            for i, item in enumerate(self.position_control_class.result_class_arr):
                pass
                # print("クラスのテスト:", item.life, item.name, item.t_unrealize_pl, item.t_realize_pl, item.t_pl_u)

        # ■■■基本情報の表示
        # peaks = self.peaks_class.peaks_original
        # peaks_skip = self.peaks_class.skipped_peaks_hard
        peaks = self.peaks_class.peaks_original
        peaks_skip = self.peaks_class.skipped_peaks_hard
        print(self.s, "<SKIP前>", len(peaks), asizeof.asizeof(peaks))
        gene.print_peaks(peaks[:4])
        print("↓")
        gene.print_peaks(peaks[-2:])
        print("")

        print(self.s, "<SKIP後＞", len(peaks_skip), asizeof.asizeof(peaks_skip))
        gene.print_peaks(peaks_skip[:3])
        print("")

        # print(self.s, "<SKIP前 1h足>", len(self.peaks_class_hour.peaks_original), asizeof.asizeof(self.peaks_class_hour.peaks_original))
        # gene.print_arr(self.peaks_class_hour.peaks_original[:3])
        # print("↓")
        # gene.print_arr(self.peaks_class_hour.peaks_original[-2:])
        # print("")
        #
        # print(self.s, "<SKIP後 1h足＞", len(self.peaks_class_hour.skipped_peaks), asizeof.asizeof(self.peaks_class_hour.skipped_peaks))
        # gene.print_arr(self.peaks_class_hour.skipped_peaks[:3])
        #
        # print(self.s, "<SKIP HARD後 1h足＞", len(self.peaks_class_hour.skipped_peaks_hard), asizeof.asizeof(self.peaks_class_hour.skipped_peaks_hard))
        # gene.print_arr(self.peaks_class_hour.skipped_peaks_hard[:3])

        # ■■■■　以下は解析値等
        # ■■■簡易的な解析値
        peaks = self.peaks_class.peaks_original
        r = peaks[0]
        t = peaks[1]
        f = peaks[2]
        # RiverとTurnの解析
        # self.rt = TuneAnalysisInformation(self.peaks_class, 1, "rt")  # peak情報源生成
        # # FlopとTurn
        # self.tf = TuneAnalysisInformation(self.peaks_class, 2, "tf")  # peak情報源生成
        # # preFlopとflopの解析
        # self.fp = TuneAnalysisInformation(self.peaks_class, 2, "fp")  # peak情報源生成
        # 各価格に使うかもしれない物
        self.latest_turn_resistance_gap = abs(t['latest_body_peak_price'] - self.current_price)
        self.latest_flop_resistance_gap = abs(f['latest_body_peak_price'] - self.current_price)

        # 調整用の係数たち
        self.sp = 0.004  # スプレッド考慮用
        self.base_lc_range = 1  # ここでのベースとなるLCRange
        self.base_tp_range = 1
        # 係数の調整用
        self.lc_adj = 0.7
        self.arrow_skip = 1
        # Unit調整用
        self.units_mini = 0.1
        self.units_reg = 0.5
        self.units_str = 1 * gl_unis_std  #0.1
        self.units_hedge = self.units_str
        # 汎用性高め
        self.lc_change_test = [
            {"exe": True, "time_after": 0, "trigger": 0.01, "ensure": -1},  # ←とにかく、LCCandleを発動させたい場合
        ]

        # ★★★調査実行
        self.main()

    def line_comment_add(self, *msg):
        message = ""
        # 複数の引数を一つにする（数字が含まれる場合があるため、STRで文字化しておく）
        for item in msg:
            message = message + " " + str(item)

        self.line_send_mes = "\n" + self.line_send_mes + message

    def line_send(self, *msg):
        # 関数は可変複数のコンマ区切りの引数を受け付ける
        message = ""
        # 複数の引数を一つにする（数字が含まれる場合があるため、STRで文字化しておく）
        for item in msg:
            message = message + " " + str(item)
        # 時刻の表示を作成する
        now_str = f'{datetime.now():%Y/%m/%d %H:%M:%S}'
        # メッセージの最後尾に付ける
        message = message + " (" + now_str[5:10] + "_" + now_str[11:19] + ")"
        if len(message) >= 2000:
            print("@@文字オーバー")
            print(message)
            message = "Discord受信許容文字数オーバー" + str(len(message))
        if not self.line_send_exe:
            print("     [Disc(送付無し)]", message)  # コマンドラインにも表示
            return 0
        # ■■■  通常のDiscord送信　■■■　　最悪これ以下だけあればいい
        data = {"content": "@everyone " + message,
                "allowed_mentions": {
                    "parse": ["everyone"]
                }
                }
        requests.post(tk.WEBHOOK_URL_main, json=data)
        print("     [Disc]", message)  # コマンドラインにも表示

    def add_order_to_this_class(self, order_class):
        """

        """
        self.take_position_flag = True
        if isinstance(order_class, (list, tuple)):
            self.exe_order_classes.extend(order_class)
        else:
            self.exe_order_classes.append(order_class)
        # self.exe_order_classes.extend(order_class)
        # print("発行したオーダー2↓　(turn255)")
        # print(order_class.exe_order)

    def _legacy_add_h1_line_limit_orders(self, line_class, current_price, decision_time, rsi_info=None):
        if self.mode != "inspection":
            return

        p = gene.USD_JPY
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

        p = gene.USD_JPY
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
                (M5LineOrderStrategy(), line_class_m5),
                (M5BreakoutLineOrderStrategy(), line_class_m5),
                (H1LineOrderStrategy(), line_class_h1),
            ],
            current_price,
            decision_time,
            rsi_info,
            h1_line_class=line_class_h1,
        )

    def add_h1_line_limit_orders(self, line_class, current_price, decision_time, rsi_info=None):
        coordinator = LineOrderCoordinator(self)
        return coordinator.create_orders(
            [(H1LineOrderStrategy(), line_class)],
            current_price,
            decision_time,
            rsi_info,
        )

    def add_m5_line_limit_orders(self, line_class, current_price, decision_time, rsi_info=None):
        coordinator = LineOrderCoordinator(self)
        return coordinator.create_orders(
            [(M5LineOrderStrategy(), line_class)],
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
                (M5LineOrderStrategy(), line_class),
                (M5BreakoutLineOrderStrategy(), line_class),
            ],
            current_price,
            decision_time,
            rsi_info,
            h1_line_class=h1_line_class,
        )

    def has_similar_order(self, direction, target_price, new_orders, threshold_pips=3, source=None, line_strategy=None):
        p = gene.USD_JPY
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

    @staticmethod
    def is_h1_line_limit_order_target(line_side, line):
        return H1LineOrderStrategy().is_target(line_side, line)

    @staticmethod
    def is_m5_line_limit_order_target(line_side, line):
        return M5LineOrderStrategy().is_target(line_side, line)

    def main(self):
        """
        ターン直後での判断。
        """
        print("main")
        # 変数化
        global gl_previous_exe_df60_row
        global gl_previous_exe_df60_order_time
        global gl_previous_bb_h1_class

        s = self.s
        df_r = self.df_r_m5  # 場合によって0が消されているdf_r
        candle_analysis = self.candle_analysis_all
        peaks = self.peaks_class.peaks_original
        peaks_skip = self.peaks_class.skipped_peaks_hard
        mode = self.mode
        # 変数化（BB）
        df_h1_row = candle_analysis.h1_df_r.iloc[0]
        bb_h1_class = self.bb_h1_class
        bb_m5_class = self.bb_m5_class

        # ■途中終了判定
        # if peaks[1]['gap'] < 0.04:
        #     print("対象が小さい", peaks[1]['gap'])

        # (4)大本命
        # (5)ターン時以外
        self.predict_analysis()

    def get_strongest_line(self, lines):
        """最強のLINEを取得"""
        if not lines:
            return None
        return max(lines, key=lambda x: x['total_strength'])

    def compare_lines(self, line_l, line_s, line_type='tp', threshold=0.5):
        """複数時間軸のLINEを比較（TP または LC）
        
        Args:
            line_l: ロングのLINE
            line_s: ショートのLINE
            line_type: 'tp' または 'lc'
            threshold: medianの差の閾値
        
        Returns:
            判定結果を辞書で返す
        """
        # line_typeに応じて対象を選択
        if line_type.lower() == 'tp':
            lines_3h = line_l.tp_lines
            lines_6h = line_s.tp_lines
        elif line_type.lower() == 'lc':
            lines_3h = line_l.lc_lines
            lines_6h = line_s.lc_lines
        else:
            raise ValueError("line_type は 'tp' または 'lc' で指定してください")
        
        strongest_3h = self.get_strongest_line(lines_3h)
        strongest_6h = self.get_strongest_line(lines_6h)
        
        if strongest_3h is None or strongest_6h is None:
            return {
                'status': '不足',
                'reason': 'データが不足',
                'line_type': line_type,
            }
        
        median_3h = strongest_3h['median']
        median_6h = strongest_6h['median']
        median_diff = abs(median_3h - median_6h)
        
        status = '変化なし' if median_diff <= threshold else '変化有'
        
        return {
            'status': status,
            'line_type': line_type,
            'median_diff': gene.USD_JPY.round_price(median_diff),
            'threshold': threshold,
            'median_3h': median_3h,
            'median_6h': median_6h,
            'strength_3h': strongest_3h['total_strength'],
            'strength_6h': strongest_6h['total_strength'],
            'price_3h': strongest_3h['median_price'],
            'price_6h': strongest_6h['median_price'],
        }


    def predict_analysis(self):
        # ターン時以外でも実行される
        print("■予測オーダー")
        s = self.s
        p = gene.USD_JPY
        current_price = self.current_price  # self.ca = candle_analysis
        foot = 5
        if foot == 5:
            # ５分足の場合
            peaks_class = self.peaks_class
            peaks = self.peaks_class.peaks_original
            df = self.peaks_class.df_r_original  # これは
        else:
            # 30分足の場合
            peaks_class = self.peaks_class_m30
            peaks = self.peaks_class_m30.peaks_original  # self.peaks_class.peaks_original
            df = self.peaks_class_m30.df_r_original  # self.peaks_class.df_r_original  # これは

            # ３０分足の場合は、３０分に１回実行
            dt = datetime.strptime(self.current_time, '%Y/%m/%d %H:%M:%S')
            minute = dt.minute
            if minute == 0 or minute == 30:  # or minute == 5 or minute == 35:  #minute % 30 == 0:
                pass
            else:
                print("30分足以外")
                return 0
        # base_price = self.current_price
        base_price = peaks[0]['latest_body_peak_price']  # self.latest_price

        # ■RSI
        upper_border = 67.5
        lower_border = 30
        # print(df[['time_jp', 'RSI']].head(15))
        f_low = df.iloc[1]
        s_low = df.iloc[2]  # ひとつ前の足
        t_low = df.iloc[3]  # ふたつ前の足
        print("    RSI", f_low['time_jp'], f_low['RSI'], "-", s_low['time_jp'],s_low['RSI'] )
        if f_low['RSI'] >= upper_border and s_low['RSI'] >= upper_border:
            print("    2個連続でRSI越えている")
        elif f_low['RSI'] <= lower_border and s_low['RSI'] <= lower_border:
            print("    2個連続でRSI30切っている")
            return 0
        elif  f_low['RSI'] >= upper_border and s_low['RSI'] <= upper_border and t_low['RSI'] >= upper_border:
            print("    直近と2個前は越えているが、中央は越えていない⇒継続して越えていきそう？")
            return 0
        elif f_low['RSI'] <= lower_border and s_low['RSI'] >= lower_border and t_low['RSI'] <= lower_border:
            print("    直近と2個前は30切っているが、中央は切っていない⇒継続して30切っていきそう？")
            return 0
        
        # ■ラインの検証
        line_class_m5_l = LineStrengthCal(self.candle_analysis_all, "m5", 60)
        line_class_m5_s = LineStrengthCal(self.candle_analysis_all, "m5", 30)
        result = self.compare_lines(line_class_m5_l, line_class_m5_s, threshold=0.5)
        print(f"判定: {result['status']}")
        print("1時間足")
        line_class_h1_l = LineStrengthCal(self.candle_analysis_all, "h1", 65)  # 画面全体くらい（直近の大きな流れを見れる）
        line_class_h1_s = LineStrengthCal(self.candle_analysis_all, "h1", 30)  # 画面半分くらい（直近のレンジを見れる）
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

        # ■RSI と Line 総強度による追加判定
        order_pattern = 0
        if f_low['RSI'] >= upper_border:
            upper3_strengths = [line['total_strength'] for line in line_class_m5_s.upper_lines]
            lower3_strengths = [
                line['total_strength'] 
                for line in line_class_m5_s.lower_lines 
                if line['median'] <= 4
            ]
            if len(upper3_strengths) == 0 and len(lower3_strengths) > 0 and max(lower3_strengths) >= 10:
                upper3_strengths = lower3_strengths
                print(" 近いLowerに強いのあり")
            max_upper3 = max(upper3_strengths) if upper3_strengths else 0

            upper6_strengths = [line['total_strength'] for line in line_class_m5_l.upper_lines]
            max_upper6 = max(upper6_strengths) if upper6_strengths else 0

            if max_upper3 <= 10 and max_upper6 <= 10:
                print("    RSI>=",  "かつ line_class3/line_class6 の upper_lines がともに弱い⇒突破予想")
                # tk.line_send("RSI>=70 かつ line_class3/line_class6 の upper_lines がともに弱い⇒突破予想")
                order_pattern = 1
            elif max_upper3 <= 10:
                print("    RSI>=70 かつ line_class3 の upper_lines だけが弱い⇒突破予想")
                # tk.line_send("RSI>=70 かつ line_class3/line_class6 の upper_lines がともに弱い⇒突破予想")
                order_pattern = 1
            elif max_upper3 >= 10 and max_upper6 >= 10:
                print("    RSI>=",  "かつ line_class3/line_class6 の upper_lines がともに強い⇒抵抗され下がる予想")
                # tk.line_send("RSI>=70 かつ line_class3/line_class6 の upper_lines がともに強い⇒抵抗され下がる予想")
                order_pattern = 2
            elif max_upper3 >= 10:
                print("    RSI>=70 かつ line_class3 の upper_lines だけが強い")
                # tk.line_send("RSI>=70 かつ line_class3がともに強い⇒抵抗され下がる予想")
                order_pattern = 2
        elif f_low['RSI'] <= lower_border:
            lower3_strengths = [line['total_strength'] for line in line_class_m5_s.lower_lines]
            upper3_strengths = [
                line['total_strength'] 
                for line in line_class_m5_s.upper_lines 
                if line['median'] <= 4
            ]
            if len(lower3_strengths) == 0 and len(upper3_strengths) > 0 and max(upper3_strengths) >= 10:
                lower3_strengths = upper3_strengths
                print(" 近いUpperに強いのあり")
            max_lower3 = max(lower3_strengths) if lower3_strengths else 0

            lower6_strengths = [line['total_strength'] for line in line_class_m5_l.lower_lines]
            max_lower6 = max(lower6_strengths) if lower6_strengths else 0
            if max_lower3 <= 10 and max_lower6 <= 10:
                print("    RSI<=",  "かつ line_class3/line_class6 の lower_lines がともに弱い⇒突破予想")
                # tk.line_send("RSI<=30 かつ line_class3/line_class6 の lower_lines がともに弱い⇒突破予想")
                order_pattern = 1
            elif max_lower3 <= 10:
                print("    RSI<=30 かつ line_class3 の lower_lines だけが弱い")
                # tk.line_send("RSI<=30 かつ line_class3/line_class6 の lower_lines がともに弱い⇒突破予想")
                order_pattern = 1
            elif max_lower3 >= 10 and max_lower6 >= 10:
                print("    RSI<=",  "かつ line_class3/line_class6 の lower_lines がともに強い⇒抵抗され上がる予想")
                # tk.line_send("RSI<=30 かつ line_class3/line_class6 の lower_lines がともに強い⇒抵抗され上がる予想")
                order_pattern = 2
            elif max_lower3 >= 10:
                print("    RSI<=30 かつ line_class3 の lower_lines だけが強い")
                # tk.line_send("RSI<=30 かつ line_class3が強い⇒抵抗され上がる予想")
                order_pattern = 2
        else:
            print("    RSIはどちらのラインも越えていない", f_low['RSI'])

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
            "【M5 count2 line no order】"
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

        return (
            "【M5 count2 line no order】"
            + "\n時刻: " + str(decision_time)
            + "\n理由: " + reason
            + "\nmode: " + str(self.mode)
            + "\ncurrent: " + str(current_price)
            + "\npeak_price: " + str(latest_peak.get("latest_body_peak_price"))
            + "\npeak_dir: " + str(latest_peak.get("direction"))
            + "\npeak_gap: " + str(latest_peak.get("gap"))
            + "\nRSI: " + str(rsi_1)
            + "\n" + m5_l_summary
            + "\n" + m5_s_summary
            + "\n" + h1_summary
            + "\n補足: top10 line order is inspection-only in live"
        )

    @staticmethod
    def line_summary_for_message(label, line_class, current_price):
        p = gene.USD_JPY
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
            + " price=" + str(gene.USD_JPY.round_price(float(nearest["price"])))
            + " gap=" + str(round(nearest["distance"], 1)) + "p"
            + " count=" + str(nearest["count"])
            + " strength=" + str(nearest["strength"])
            + " core_count=" + str(nearest["core_count"])
            + " core_strength=" + str(nearest["core_strength"])
        )

    def cal_units(self, lc_range, risk_yen=500, tag="s", yen_per_pip_per_lot=1000, ):
        """
        risk_yenは最大の負け額
        tagは注文がアプリからわかりやすいように、強引にUNITの一桁目を調整する。sの場合は1か６、lの場合は0か５になる
        yen_per_pip_per_lot:
            例）ドル円で1ロット=1000通貨なら約10円/pips
                1万通貨なら約100円/pips
        """
        # 基本的なUNIT計算
        doller_yen = 10000
        lc_pips = max(lc_range / 0.01, 0.000000001)  # 下のdeveide0を防ぎたい
        # print("　UNITSを計算する lc_range", lc_range, "pips", lc_pips, "許容損失", risk_yen)
        lot = risk_yen / (lc_pips * yen_per_pip_per_lot)
        units = int(lot * doller_yen)

        # 調整
        # 一桁目（10で割った余り）を取得
        last_digit = units % 10
        # 一桁目を除いた「十の位以上」のベース数値
        base = (units // 10) * 10
        if tag == "l":
            # 0か5、近い方に合わせる
            if last_digit <= 2 or last_digit >= 8:
                # 0に近い場合（8, 9, 0, 1, 2）
                # ※ 8, 9の場合は次の桁の0に近いので、四捨五入に近い処理
                new_units = round(units / 5) * 5
            else:
                # 5に近い場合（3, 4, 5, 6, 7）
                new_units = base + 5

            # シンプルに書くなら： units = 5 * round(units / 5)
            units = int(5 * round(units / 5))

        elif tag == "s":
            # 1か6、近い方に合わせる
            # unitsから1を引くと「0か5に合わせる問題」に置き換えられる
            adjusted = 5 * round((units - 1) / 5) + 1
            units = int(adjusted)

        return units
    
class LineStrengthCal:
    def __init__(self, candle_analysis_class, foot, time_before_foot_count=30):
        print("  ")
        print("  抵抗線計算クラス 時間範囲(足数)", time_before_foot_count, "足", foot)
        # ■■■基本情報の取得
        mode = "live"
        if mode == "live":
            from_i = 0
            self.mode = "live"
        else:
            from_i = 1
            self.mode = "inspection"
        self.p = gene.USD_JPY

        self.s = "     "
        self.foot = foot
        self.max_line_price_gap_pips = None
        self.pair = "USD_JPY"
        self.candle_analysis_class = candle_analysis_class  # ローソク情報の全て
        self.time_before_foot_count = time_before_foot_count

        # 各足でのローソク情報
        self.candle_meta_m5 = candle_analysis_class.candle_meta_class  # peaks以外の部分。cal_move_ave関数を使う用
        self.peaks_class_m5 = candle_analysis_class.peaks_class  # peaks_classだけを抽出
        self.peaks_m5 = self.peaks_class_m5.peaks_original
        self.df_r_m5 = candle_analysis_class.d5_df_r[1:]  # 5分足はひとつ前ので固定！！（Liveでも）

        self.candle_meta_h1 = candle_analysis_class.candle_meta_class_hour
        self.peaks_class_h1 = candle_analysis_class.peaks_class_hour
        self.peaks_h1 = candle_analysis_class.peaks_class_hour.peaks_original
        self.df_r_h1 = candle_analysis_class.h1_df_r[from_i:]

        self.candle_meta_m30 = candle_analysis_class.candle_meta_class_m30
        self.peaks_class_m30 = candle_analysis_class.peaks_class_m30
        self.peaks_m30 = candle_analysis_class.peaks_class_m30.peaks_original
        self.df_r_m30 = candle_analysis_class.d30_df_r[from_i:]


        # この関数で使う基本を入れておく
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
        self.current_time = candle_analysis_class.d5_df_r.iloc[0]['time_jp']  # 5分足で判断(0行目を利用）
        self.current_price = candle_analysis_class.current_price  # candleAnalysisからとる（本番の場合はAPIで最新、解析の場合はclose価格)
        self.latest_peak_dir = self.peaks[0]['direction']

        # lines_wrap_up関数で算出する変数
        self.filtered_peaks = []  # 指定の時間までのピークス
        self.filterd_df = None  # 指定の時間までのDF
        self.upper_lines = []
        self.lower_lines = []
        self.tp_lines = []
        self.lc_lines = []
        self.all_lines = []  # base_priceより上の場合medianがプラス値、下の場合はマイナス値（latestPeakのdirectionが1の場合）

        # lines_df_analysis関数で使う用の変数
        self.max_inner_high = 0
        self.max_highest = 0
        self.min_inner_low = 99999
        self.min_lowest = 99999
        self.ratio = 0


        # 関数の実行
        self.lines_wrap_up()  # linesの算出
        self.line_each_analysis()  # 各lineの分析
        self.lines_df_analysis()  # linesの分析(全体感)

        # lineの表示
        print("    All LINES @ 815行目付近", len(self.all_lines))
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
        print("    個別LINE分析")
        all_lines = self.all_lines  # 置き換え
        # 結果用
        for i, item in enumerate(all_lines):
            # print("    K", item['median_price'])
            is_flipped_line = False
            # 各ラインを単品で見ていく
            dirs = item['dirs_grouped']
            if item['count'] >= 3 and len(dirs) >= 2:
                # 3個以上ある場合、向き等を検討していく
                if dirs[0] * dirs[1] < 0 and item['prices_info'][0]["peak_strength"]>2:
                    # print("      K", item['median_price'], dirs[0], dirs[1])
                    # 正負の数が異なっている
                    if abs(dirs[1]) >= 2:
                        is_flipped_line = True
            # 結果付与する
            item['is_flipped_line'] = is_flipped_line
            item['is_flipped_line_st'] = 0

    def lines_df_analysis(self):
        """
        算出したラインを分析する。lines_wrap_up関数で算出したラインの情報を、直近の価格の動きなどと組み合わせて分析してみる
        """
        # 例えば、ラインの近さと、直近の価格の動きから、どのラインが効いているかを分析してみる
        # 直近の価格の動きは、例えば、直近の数本のローソク足の高値と安値から見てみる
        print("    LINES分析")
        df_filterd = self.filterd_df
        all_lines = self.all_lines

        # peaksの中で最高値、最低を取得する
        self.max_inner_high = df_filterd['inner_high'].max()
        self.max_highest = df_filterd['high'].max()
        self.min_inner_low = df_filterd['inner_low'].min()
        self.min_lowest = df_filterd['low'].min()
        self.df_high_low_range = self.p.price_to_pips(self.max_highest - self.min_lowest)  # 価格で計算後、pipsで保存する
        print("     最高値", self.max_inner_high, "(", self.max_highest, ")", "最低値", self.min_inner_low, "(", self.min_lowest, ")")
 
        # lineでの最高値と最低値のGapを算出
        if len(all_lines) == 0:
            print("ALL LINESが一本もない、イレギュラーな状態")
            return 0
        self.lines_high_low_range = self.p.round_price(abs(all_lines[0]['median'] - all_lines[-1]['median']))

        # 比率
        self.ratio = round(self.lines_high_low_range / self.df_high_low_range, 2)
        
        print("     LongラインのLinesの発散具合", self.ratio, "dfの高値と安値の差", self.df_high_low_range, "lineのmedianの高値と安値の差", self.lines_high_low_range)

        # 上側の詰まり具合、下側の詰まり具合を算出
        highest = self.max_inner_high  # max_highestと入れ替えできるように
        lowest = self.min_inner_low
        dir = self.latest_peak_dir
        if dir == 1:  # 直近peakが上向きの場合、linesの一番上が最高値
            upper_gap = self.p.price_to_pips(highest - all_lines[0]['median_price'])
            lower_gap = self.p.price_to_pips(all_lines[-1]['median_price'] - lowest)
            print("     HIGH-LOW", highest, "-", lowest, "LINE_high_low", all_lines[0]['median_price'], "-", all_lines[-1]['median_price'])
        else:  # 直近peakが下向きの場合、
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

        # 現在価格がどこにいるかの確認
        current_price = self.current_price
        upper_lines = self.upper_lines
        lower_lines = self.lower_lines
        highest = 0 if len(upper_lines) == 0 else self.p.round_price(upper_lines[0]['median_price'])
        lowest = 9999 if len(lower_lines) == 0 else self.p.round_price(lower_lines[-1]['median_price'])
        is_inner_lines = False
        if lowest <= current_price <= highest:
            is_inner_lines = True
        print("     直近価格がLINEの中に入っているか？", is_inner_lines)

        # 判定
        if is_inner_lines:
            # linesの内側⇒レンジの可能性が出てくる
            if upper_ratio <= 0.2 and lower_ratio >= 0.4:
                # レンジが上部にある
                print("      レンジが上部にあり、直近もその中")
                pass
            elif lower_ratio <= 0.2 and upper_ratio >= 0.4:
                # レンジが下部にある
                print("      レンジが下部にあり、直近もその中")
                pass
            elif upper_ratio <= 0.2 and lower_ratio <= 0.2:
                # レンジが継続している
                print("      全体的にまとまった感じ、直近もその中")
                pass
            elif upper_ratio >= 0.4 and lower_ratio >= 0.4:
                # 荒れている、激しめのレンジ
                print("      少し激しめの動き、直近もその中")
                pass
        else:
            # linesの外側にある
            print("      直近はレンジ外")


    def lines_wrap_up(self):
        """
        Lineを探索する
        """
        # 必要な情報を変数化
        base_price = self.current_price
        time_before_foot_count = self.time_before_foot_count
        threshold = self.threshold if self.foot == "m5" else 3  # pipsで指定
        
        # ピークの取得
        peaks = self.peaks_class.peaks_original  # 使う足の選択
        if threshold is None:
            threshold = self.threshold
        
        # ★Peaksを絞り込み(指定の直近の足数でフィルタ。土日挟むと時間指定がおかしくなるので足数。足数から時間を算出)
        df_filterd = self.df_r[0:time_before_foot_count]
        oldest_time = datetime.strptime(df_filterd.iloc[-1]['time_jp'], "%Y/%m/%d %H:%M:%S")
        current_time = datetime.strptime(self.df_r.iloc[0]['time_jp'], "%Y/%m/%d %H:%M:%S")
        time_diff = (current_time - oldest_time).total_seconds() / 3600  # 時間差を時間単位で計算
        border_time = datetime.strptime(self.current_time, '%Y/%m/%d %H:%M:%S') - timedelta(hours=time_diff)  # peakを算出するための
        peaks = [  # peakを時間で絞る（絶対必要）
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
        peaks = [  # peakをStrengthで1より大きいものに絞る（テスト）
            d for d in peaks
            if float(d.get('peak_strength', 0)) >= 0
        ]
        print("    Line peak strength filter", self.min_line_peak_strength, peaks_before_strength_filter, "->", len(peaks))
        self.filtered_peaks = peaks
        self.filterd_df = df_filterd

        # ラインの処理
        print("    Line探索の基準価格",base_price, "直近ピーク方向", self.latest_peak_dir, "時間最後", border_time, "time_DIFF", time_diff)
        # upper_base_price = base_price + (self.latest_peak_dir * self.p.pips_to_price(1))
        # print("     Upper基準", upper_base_price)
        # upper_lines = self.search_upper_lines(upper_base_price, peaks, threshold)  # target_price
        
        # lower_base_price = base_price - (self.latest_peak_dir * self.p.pips_to_price(1))
        # print("     Lower基準", lower_base_price)
        # lower_lines = self.search_lower_lines(lower_base_price, peaks, threshold)  # target_price

        if self.latest_peak_dir == 1:
            # 直近価格＝注文価格の場合 いずれも直近価格から近い順に並んでいる。
            upper_base_price = base_price - (self.latest_peak_dir * self.p.pips_to_price(1))  # 利確を少し手前から
            print("     Upper基準", upper_base_price)
            upper_lines = self.search_upper_lines(upper_base_price, peaks, threshold)  # target_price
            
            lower_base_price = base_price - (self.latest_peak_dir * self.p.pips_to_price(1))
            print("     Lower基準", lower_base_price)
            lower_lines = self.search_lower_lines(lower_base_price, peaks, threshold)  # target_price
            self.tp_lines = upper_lines
            self.lc_lines = lower_lines
        else:
            # 直近価格＝注文価格の場合
            upper_base_price = base_price - (self.latest_peak_dir * self.p.pips_to_price(1))  # 利確を少し手前から
            print("     Upper基準", upper_base_price)
            upper_lines = self.search_upper_lines(upper_base_price, peaks, threshold)  # target_price
            
            lower_base_price = base_price - (self.latest_peak_dir * self.p.pips_to_price(1))
            print("     Lower基準", lower_base_price)
            lower_lines = self.search_lower_lines(lower_base_price, peaks, threshold)  # target_price
            self.tp_lines = lower_lines
            self.lc_lines = upper_lines
        self.lower_lines = lower_lines
        self.upper_lines = upper_lines

        # ALLのラインを作る
        if self.latest_peak_dir == 1:
            # upper_lines: median そのまま（昇順 → 降順に反転）
            # lower_lines: median に - をつけて（降順のまま）
            reversed_upper = list(reversed(self.upper_lines))
            negated_lower = [
                {**line, 'median': -line['median']}
                for line in self.lower_lines
            ]
            combined = reversed_upper + negated_lower
        elif self.latest_peak_dir == -1:
            # lower_lines: median そのまま（昇順 → 反転して降順に）
            # upper_lines: median に - をつけて（昇順のまま反転せず、そのままマイナス）
            reversed_lower = list(reversed(self.lower_lines))
            negated_upper = [
                {**line, 'median': -line['median']}
                for line in self.upper_lines
            ]
            combined = reversed_lower + negated_upper
        self.all_lines = combined


    def search_upper_lines(self, base_price, peaks, threshold=None):
        # print("    UpperLines検索")
        # グループ化
        minus_groups = self.make_same_price_group_core_first(
            peaks=peaks,
            upper_lower=1,  # base_priceより下側
            target_price=base_price,
            threshold=threshold,
            sort_direction=1  # 昇順
        )
        # 弱すぎるグループは排除する
        # filtered = [d for d in minus_groups if (d["ave_strength"] >= 2 and d['count'] >= 2) or d["total_strength"] >= 10]
        filtered = [d for d in minus_groups if d["ave_strength"] >= 0 and d['count'] >= 1]
        return filtered

    def search_lower_lines(self, base_price, peaks, threshold=None):
        # print("    LowerLines検索")
        # グループ化
        minus_groups = self.make_same_price_group_core_first(
            peaks=peaks,
            upper_lower=-1,  # base_priceより下側
            target_price=base_price,
            threshold=threshold,
            sort_direction=-1  # 降順
        )
        # 弱すぎるグループは排除する
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
                            threshold=3,  # pips単位（前後の範囲）
                            direction_filter=None,
                            sort_direction=-1,
                            ):
        # target_priceをpipsに変換（基準点として）
        target_price_pips = self.p.price_to_pips(target_price)

        if upper_lower == -1:
            # 下側の場合
            filtered_peaks = [
                p for p in peaks
                if float(p['latest_body_peak_price']) < target_price
            ]
        else:
            # 上側の場合
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

        # 価格でソート（降順）
        sorted_peaks = sorted(
            filtered_peaks,
            key=lambda x: float(x['latest_body_peak_price']),
            reverse=True
        )

        used_indices = set()  # 既に使われたインデックス
        results = []

        for i, p in enumerate(sorted_peaks):
            if i in used_indices:
                continue

            center_price = float(p['latest_body_peak_price'])
            center_price_pips = self.p.price_to_pips(center_price)
            
            # 中心価格の前後thresholdの範囲にあるものを集める
            group_items = []
            group_indices = []

            for j, candidate in enumerate(sorted_peaks):
                if j not in used_indices:
                    candidate_price = float(candidate['latest_body_peak_price'])
                    candidate_price_pips = self.p.price_to_pips(candidate_price)
                    
                    # pips単位で前後thresholdの範囲内か確認
                    if abs(candidate_price_pips - center_price_pips) <= threshold:
                        group_items.append(candidate)
                        group_indices.append(j)

            if group_items:
                # 時系列順に戻る
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
                
                # このグループに属するものを使用済みに
                used_indices.update(group_indices)

        # 連続した同じ値をグループ化して合計
        from itertools import groupby
        for r in results:
            r['dirs_grouped'] = [sum(group) for key, group in groupby(r['dirs'])]

        # グループ化されなかったものを1個のグループとして追加
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
        # print("TEST表示")
        # for i, item in enumerate(results):
        #     print(" ", item)

        results = sorted(
            results,
            key=lambda x: x['median_price'],  # 価格で並び替え
            reverse=(sort_direction == -1)
        )
        
        return results
