import copy

import fGeneric as gene
import sys
from pympler import asizeof
import pandas as pd
import classCandleAnalysis as ca
import classOrderCreate as OCreate
import tokens as tk
import send_notice as notice
from datetime import datetime, timedelta
import requests
from statistics import median
from collections import defaultdict
import math
from pathlib import Path
from fLineStrategyAudUsd import LineStrategyProfileAudUsd
from fLineStrategyEurUsd import LineStrategyProfileEurUsd
from fLineStrategyUsdJpy import (
    LineStrategyProfileUsdJpy,
    UsdJpyH1LineOrderStrategy,
    UsdJpyM5BreakoutLineOrderStrategy,
    UsdJpyM5LineOrderStrategy,
)
import statistics
from collections import Counter

this_file_line_send = False
gl_previous_exe_df60_row = None
gl_previous_exe_df60_order_time = None
gl_previous_bb_h1_class = None
gl_latest_trend_trigger_time = None
gl_risk_yen = 50


def line_strategy_profile(pair):
    """Return the line strategy profile for each currency pair."""
    if pair == "AUD_USD":
        return LineStrategyProfileAudUsd()
    if pair == "EUR_USD":
        return LineStrategyProfileEurUsd()
    return LineStrategyProfileUsdJpy()


class LineOrderCoordinator:
    fallback_usd_jpy_rate = 160.0
    inspection_usd_jpy_max_gap = pd.Timedelta(days=31)
    _inspection_usd_jpy_close = None
    duplicate_threshold_pips = 3
    timeout_by_distance_pips = (
        (3, 15),
        (7, 30),
        (12, 45),
    )
    timeout_cap_by_timeframe = {
        "m5": 45,
        "h1": 60,
    }

    def __init__(self, analysis):
        self.analysis = analysis
        self.pair = getattr(analysis, "pair", "USD_JPY")
        self.p = gene.currency_pair(self.pair)
        self.profile = getattr(
            analysis,
            "each_pair_line_strategy_profile",
            line_strategy_profile(self.pair),
        )
        self.duplicate_threshold_pips = self.profile.duplicate_threshold_pips
        self._live_usd_jpy_rate = None

    @classmethod
    def order_timeout_min_for_distance(cls, distance_pips, timeframe, default_timeout_min):
        timeout_min = 60
        for border_pips, candidate_timeout_min in cls.timeout_by_distance_pips:
            if distance_pips <= border_pips:
                timeout_min = candidate_timeout_min
                break

        cap = cls.timeout_cap_by_timeframe.get(str(timeframe).lower(), default_timeout_min)
        return min(timeout_min, cap)

    def create_orders(
        self,
        strategy_lines,
        current_price,
        decision_time,
        rsi_info=None,
        h1_line_class=None,
        m5_line_class=None,
    ):
        return self.create_limit_orders_from_strategy_lines(
            strategy_lines,
            current_price,
            decision_time,
            rsi_info,
            h1_line_class=h1_line_class,
            m5_line_class=m5_line_class,
        )

    def create_limit_orders_from_strategy_lines(
        self,
        strategy_lines,
        current_price,
        decision_time,
        rsi_info=None,
        h1_line_class=None,
        m5_line_class=None,
    ):
        return self._create_orders_from_strategy_lines(
            strategy_lines,
            current_price,
            decision_time,
            rsi_info,
            h1_line_class=h1_line_class,
            m5_line_class=m5_line_class,
            order_mode="limit",
        )

    def create_immediate_orders_from_near_lines(
        self,
        strategy_lines,
        current_price,
        decision_time,
        rsi_info=None,
        h1_line_class=None,
        m5_line_class=None,
    ):
        return self._create_orders_from_strategy_lines(
            strategy_lines,
            current_price,
            decision_time,
            rsi_info,
            h1_line_class=h1_line_class,
            m5_line_class=m5_line_class,
            order_mode="immediate",
        )

    def _create_orders_from_strategy_lines(
        self,
        strategy_lines,
        current_price,
        decision_time,
        rsi_info=None,
        h1_line_class=None,
        m5_line_class=None,
        order_mode="limit",
    ):
        candidates = self.build_line_candidates(
            strategy_lines,
            current_price,
            h1_line_class=h1_line_class,
            m5_line_class=m5_line_class,
            order_mode=order_mode,
        )
        candidates = self._filter_recommended_candidates(
            candidates,
            rsi_info,
            decision_time,
            order_mode,
        )
        return self.create_orders_from_candidates(
            candidates,
            current_price,
            decision_time,
            rsi_info,
            order_mode,
        )

    def build_line_candidates(
        self,
        strategy_lines,
        current_price,
        h1_line_class=None,
        m5_line_class=None,
        order_mode="limit",
    ):
        candidates = []
        for strategy, line_class in strategy_lines:
            strategy.pair = self.pair
            candidates.extend(strategy.build_candidates(line_class, current_price))
        if order_mode == "immediate":
            self._prepare_immediate_candidates(candidates, current_price)
        if h1_line_class is not None:
            self._add_h1_context(candidates, h1_line_class)
        if m5_line_class is not None:
            self._add_previous_peak_line_context(candidates, m5_line_class, "m5_previous_peak_line")
        if h1_line_class is not None:
            self._add_previous_peak_line_context(candidates, h1_line_class, "h1_previous_peak_line")
        return candidates

    def select_line_candidates(
        self,
        candidates,
        rsi_info,
        decision_time,
        order_mode,
        reason_func,
    ):
        filtered = []
        for candidate in candidates:
            latest_peak_info = self.attach_candidate_decision_context(
                candidate,
                decision_time,
                order_mode,
            )
            reasons = reason_func(candidate, rsi_info, latest_peak_info)
            if not reasons:
                print(
                    "Skip line order by condition:",
                    order_mode,
                    candidate["timeframe"],
                    candidate["line_strategy"],
                    candidate["line_side"],
                    candidate["line_price"],
                )
                continue

            candidate["order_mode"] = order_mode
            candidate["recommended_reasons"] = reasons
            candidate["memo"] = self._build_condition_memo(candidate, rsi_info, reasons)
            filtered.append(candidate)
        return filtered

    def attach_candidate_decision_context(self, candidate, decision_time, order_mode):
        session_info = self.get_session_info(decision_time)
        candidate["session_name"] = session_info["session_name"]
        candidate["session_hour"] = session_info["session_hour"]
        candidate["session_time"] = session_info["session_time"]
        latest_peak_info = self._latest_peak_info(candidate["timeframe"])
        candidate["latest_peak_dir"] = latest_peak_info["direction"]
        candidate["latest_peak_count"] = latest_peak_info["count"]
        candidate["latest_peak_gap"] = latest_peak_info["gap"]
        candidate["latest_peak_time"] = latest_peak_info["time"]
        candidate["latest_peak_strength"] = latest_peak_info["strength"]
        candidate["latest_peak_price"] = latest_peak_info["price"]
        candidate["latest_peak_rsi"] = latest_peak_info["rsi"]
        candidate["previous_peak_dir"] = latest_peak_info["previous_direction"]
        candidate["previous_peak_count"] = latest_peak_info["previous_count"]
        candidate["previous_peak_gap"] = latest_peak_info["previous_gap"]
        candidate["previous_peak_time"] = latest_peak_info["previous_time"]
        candidate["previous_peak_strength"] = latest_peak_info["previous_strength"]
        candidate["previous_peak_price"] = latest_peak_info["previous_price"]
        candidate["previous_peak_rsi"] = latest_peak_info["previous_rsi"]
        candidate["order_mode"] = order_mode
        return latest_peak_info

    def create_orders_from_candidates(
        self,
        candidates,
        current_price,
        decision_time,
        rsi_info,
        order_mode,
    ):
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
                order_mode,
            )
            order_class = self.adjust_order_by_session(order_class, decision_time)
            if order_class is None:
                continue
            self._apply_path_short_tp(order_class)
            self._attach_tp_last_touch_context(order_class, decision_time)

            orders.append(order_class)

        if orders:
            timeframe_counts = Counter(
                order.exe_order_plan.get("line_timeframe") for order in orders
            )
            print(order_mode.capitalize() + " line orders:", dict(timeframe_counts))
            self.analysis.add_order_to_this_class(orders)
        return orders

    def _prepare_immediate_candidates(self, candidates, current_price):
        for candidate in candidates:
            candidate["line_target_price"] = candidate["target_price"]
            candidate["line_distance_pips"] = candidate.get("distance_pips")
            candidate["target_price"] = self.p.round_price(float(current_price))
            candidate["order_type_override"] = "MARKET"

    def _filter_recommended_candidates(self, candidates, rsi_info, decision_time, order_mode):
        filtered = []
        for candidate in candidates:
            reasons = self._recommended_reasons(candidate, rsi_info, decision_time, order_mode)
            if not reasons:
                print(
                    "Skip line order by condition:",
                    order_mode,
                    candidate["timeframe"],
                    candidate["line_strategy"],
                    candidate["line_side"],
                    candidate["line_price"],
                )
                continue

            candidate["order_mode"] = order_mode
            candidate["recommended_reasons"] = reasons
            candidate["memo"] = self._build_condition_memo(candidate, rsi_info, reasons)
            filtered.append(candidate)
        return filtered

    def _recommended_reasons(self, candidate, rsi_info, decision_time, order_mode="limit"):
        latest_peak_info = self.attach_candidate_decision_context(
            candidate,
            decision_time,
            order_mode,
        )
        if order_mode == "immediate":
            return self.profile.immediate_recommended_reasons(
                candidate,
                rsi_info,
                latest_peak_info,
            )
        return self.profile.limit_recommended_reasons(
            candidate,
            rsi_info,
            latest_peak_info,
        )

    def _latest_peak_info(self, timeframe):
        try:
            if timeframe == "h1":
                peaks = self.analysis.peaks_class_hour.peaks_original
            else:
                peaks = self.analysis.peaks_class.peaks_original
            latest_peak = peaks[0]
            previous_peak = peaks[1] if len(peaks) > 1 else {}
            return {
                "direction": int(float(latest_peak.get("direction"))),
                "count": int(latest_peak.get("count") or 0),
                "gap": latest_peak.get("gap"),
                "time": latest_peak.get("latest_time_jp"),
                "strength": latest_peak.get("peak_strength"),
                "price": latest_peak.get("latest_body_peak_price"),
                "rsi": latest_peak.get("rsi"),
                "previous_direction": previous_peak.get("direction"),
                "previous_count": previous_peak.get("count"),
                "previous_gap": previous_peak.get("gap"),
                "previous_time": previous_peak.get("latest_time_jp"),
                "previous_strength": previous_peak.get("peak_strength"),
                "previous_price": previous_peak.get("latest_body_peak_price"),
                "previous_rsi": previous_peak.get("rsi"),
            }
        except (AttributeError, IndexError, TypeError, ValueError):
            return {
                "direction": 0,
                "count": 0,
                "gap": None,
                "time": None,
                "strength": None,
                "price": None,
                "rsi": None,
                "previous_direction": None,
                "previous_count": None,
                "previous_gap": None,
                "previous_time": None,
                "previous_strength": None,
                "previous_price": None,
                "previous_rsi": None,
            }

    @staticmethod
    def _build_condition_memo(candidate, rsi_info, reasons):
        line = candidate["line"]
        h1_context = candidate.get("h1_context", {})
        parts = [
            str(candidate.get("order_mode", "line")),
            candidate["timeframe"],
            candidate["line_side"],
            candidate["strategy"].entry_type,
            "peak_dir=" + str(candidate.get("latest_peak_dir")),
            "peak_count=" + str(candidate.get("latest_peak_count")),
            "peak_rsi=" + str(candidate.get("latest_peak_rsi")),
            "prev_peak_rsi=" + str(candidate.get("previous_peak_rsi")),
            "strength=" + str(line.get("total_strength")),
            "count=" + str(line.get("count")),
            "price_gap=" + str(line.get("price_gap")),
            "core_count=" + str(line.get("core_count")),
            "core_strength=" + str(line.get("core_total_strength")),
            "line_rsi_avg=" + str(line.get("line_peak_rsi_avg")),
            "line_rsi_latest=" + str(line.get("line_peak_rsi_latest")),
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
        h1_lines = self._line_items(h1_line_class)

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
            path_base_price = float(candidate["target_price"])
            path_ahead_lines = self._sorted_ahead_lines(
                h1_lines,
                path_base_price,
                direction,
            )

            context = {}
            context.update(self._h1_line_fields("h1_upper", nearest_upper, base_price))
            context.update(self._h1_line_fields("h1_lower", nearest_lower, base_price))
            context.update(self._h1_line_fields("h1_nearest", nearest_any, base_price))
            context.update(self._h1_line_fields("h1_ahead", nearest_ahead, base_price))
            context.update(self._h1_line_fields("h1_behind", nearest_behind, base_price))
            context.update(self._h1_line_fields(
                "h1_path_ahead_1",
                path_ahead_lines[0] if len(path_ahead_lines) >= 1 else None,
                path_base_price,
            ))
            context.update(self._h1_line_fields(
                "h1_path_ahead_2",
                path_ahead_lines[1] if len(path_ahead_lines) >= 2 else None,
                path_base_price,
            ))
            if len(path_ahead_lines) >= 2:
                context["h1_path_ahead_1_to_2_distance_pips"] = abs(
                    p.price_to_pips(
                        float(path_ahead_lines[1]["price"])
                        - float(path_ahead_lines[0]["price"])
                    )
                )
            else:
                context["h1_path_ahead_1_to_2_distance_pips"] = None
            nearest_gap = context.get("h1_nearest_distance_pips")
            context["h1_near_same_line"] = (
                nearest_gap is not None and nearest_gap <= self.duplicate_threshold_pips
            )
            context["h1_blocks_trade_direction"] = (
                context.get("h1_ahead_total_strength") is not None
                and context["h1_ahead_total_strength"] >= 10
            )
            candidate["h1_context"] = context

    def _add_previous_peak_line_context(self, candidates, line_class, prefix):
        lines = self._line_items(line_class)
        for candidate in candidates:
            previous_peak_price = candidate.get("previous_peak_price")
            context = candidate.setdefault("h1_context", {})
            if previous_peak_price is None:
                context.update(self._previous_peak_line_fields(prefix, None, None))
                continue

            nearest_line = self._nearest_h1_line(lines, float(previous_peak_price))
            context.update(self._previous_peak_line_fields(
                prefix,
                nearest_line,
                float(previous_peak_price),
            ))

    def _line_items(self, line_class):
        p = self.p
        line_items = []
        for line_side, lines in (
            ("upper", line_class.upper_lines),
            ("lower", line_class.lower_lines),
        ):
            for line in lines:
                line_items.append({
                    "side": line_side,
                    "price": p.round_price(line["median_price"]),
                    "line": line,
                })
        return line_items

    def _previous_peak_line_fields(self, prefix, item, previous_peak_price):
        if item is None or previous_peak_price is None:
            return {
                prefix + "_side": None,
                prefix + "_price": None,
                prefix + "_distance_pips": None,
                prefix + "_total_strength": None,
                prefix + "_count": None,
                prefix + "_core_total_strength": None,
                prefix + "_is_flipped": None,
                prefix + "_contains_peak": False,
                prefix + "_is_near": False,
                prefix + "_is_near_strong": False,
            }

        p = self.p
        line = item["line"]
        distance_pips = abs(
            p.price_to_pips(float(item["price"]) - previous_peak_price)
        )
        total_strength = line.get("total_strength")
        contains_peak = self._line_contains_peak(line, previous_peak_price)
        return {
            prefix + "_side": item["side"],
            prefix + "_price": item["price"],
            prefix + "_distance_pips": distance_pips,
            prefix + "_total_strength": total_strength,
            prefix + "_count": line.get("count"),
            prefix + "_core_total_strength": line.get("core_total_strength"),
            prefix + "_is_flipped": line.get("is_flipped_line"),
            prefix + "_contains_peak": contains_peak,
            prefix + "_is_near": distance_pips <= self.duplicate_threshold_pips,
            prefix + "_is_near_strong": (
                distance_pips <= self.duplicate_threshold_pips
                and float(total_strength or 0) >= 10
            ),
        }

    def _line_contains_peak(self, line, peak_price):
        p = self.p
        for peak in line.get("prices_info", []):
            price = peak.get("latest_body_peak_price")
            if price is None:
                continue
            if abs(p.price_to_pips(float(price) - peak_price)) <= 0.1:
                return True
        return False

    @staticmethod
    def _nearest_h1_line(lines, base_price):
        if not lines:
            return None
        return min(lines, key=lambda x: abs(float(x["price"]) - base_price))

    @staticmethod
    def _sorted_ahead_lines(lines, base_price, direction):
        ahead_lines = [
            x
            for x in lines
            if (float(x["price"]) - base_price) * direction > 0
        ]
        return sorted(
            ahead_lines,
            key=lambda x: abs(float(x["price"]) - base_price),
        )

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

    def _get_risk_multiplier(self, candidate, decision_time):
        session_name = self.get_session_info(decision_time)["session_name"]
        session_policy = self.session_order_policy(session_name)
        return (
            candidate["strategy"].timeframe_risk_multiplier
            * session_policy["risk_multiplier"]
        )

    def _get_usd_jpy_rate(self, decision_time):
        if self.pair == "USD_JPY":
            return None
        if getattr(self.analysis, "mode", "inspection") == "live":
            if self._live_usd_jpy_rate is not None:
                return self._live_usd_jpy_rate
            candle_analysis = getattr(self.analysis, "candle_analysis_all", None)
            oa = getattr(candle_analysis, "base_oa", None)
            if oa is not None:
                response = oa.NowPrice_exe("USD_JPY")
                if response.get("error") == 0:
                    self._live_usd_jpy_rate = float(response["data"]["mid"])
                    return self._live_usd_jpy_rate
            self._live_usd_jpy_rate = self.fallback_usd_jpy_rate
            return self._live_usd_jpy_rate

        close_series = self._load_inspection_usd_jpy_close()
        if close_series.empty:
            return self.fallback_usd_jpy_rate

        decision_time = pd.Timestamp(decision_time)
        nearest_index = close_series.index.get_indexer([decision_time], method="nearest")[0]
        if nearest_index < 0:
            return self.fallback_usd_jpy_rate
        rate_time = close_series.index[nearest_index]
        if abs(rate_time - decision_time) > self.inspection_usd_jpy_max_gap:
            return self.fallback_usd_jpy_rate
        return float(close_series.iloc[nearest_index])

    @classmethod
    def _load_inspection_usd_jpy_close(cls):
        if cls._inspection_usd_jpy_close is not None:
            return cls._inspection_usd_jpy_close

        frames = []
        for path in Path(tk.folder_path).glob("m5_USD_JPY_*.csv"):
            df = pd.read_csv(path, usecols=["time_jp", "close"])
            frames.append(df)
        if not frames:
            cls._inspection_usd_jpy_close = pd.Series(dtype=float)
            return cls._inspection_usd_jpy_close

        rates = pd.concat(frames, ignore_index=True)
        rates["time_jp"] = pd.to_datetime(rates["time_jp"])
        rates.dropna(subset=["time_jp", "close"], inplace=True)
        rates.drop_duplicates(subset=["time_jp"], keep="last", inplace=True)
        rates.sort_values("time_jp", inplace=True)
        cls._inspection_usd_jpy_close = rates.set_index("time_jp")["close"].astype(float)
        return cls._inspection_usd_jpy_close

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
        policies = self.profile.session_policies
        return policies.get(session_name, policies["night"])

    def adjust_order_by_session(self, order_class, decision_time):
        session_info = self.get_session_info(decision_time)
        policy = self.session_order_policy(session_info["session_name"])

        order_plan = order_class.exe_order_plan
        order_plan["session_name"] = session_info["session_name"]
        order_plan["session_hour"] = session_info["session_hour"]
        order_plan["session_time"] = session_info["session_time"]
        # Keep this key for inspection CSV compatibility. The multiplier now
        # changes risk_yen before units are calculated.
        order_plan["session_units_multiplier"] = policy["risk_multiplier"]
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

        if policy["rr"] is not None:
            self._apply_rr_to_tp(order_class, policy["rr"])

        return order_class

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

    def _apply_tp_lc_pips(self, order_class, tp_pips, lc_pips, label):
        p = self.p
        order_plan = order_class.exe_order_plan
        direction = int(order_plan.get("direction") or 1)
        target_price = float(order_plan["target_price"])
        old_tp_range = order_plan.get("tp_range")
        old_lc_range = order_plan.get("lc_range")
        tp_range = p.pips_to_price(tp_pips)
        tp_price = p.round_price(target_price + (tp_range * direction))
        lc_range = p.pips_to_price(lc_pips)
        lc_price = p.round_price(target_price - (lc_range * direction))

        order_class.tp_range = tp_range
        order_class.tp_price = tp_price
        order_class.lc_range = lc_range
        order_class.lc_price = lc_price
        if old_tp_range is not None:
            order_plan["path_tp_original_pips"] = p.price_to_pips(float(old_tp_range))
        if old_lc_range is not None:
            order_plan["path_lc_original_pips"] = p.price_to_pips(float(old_lc_range))
        order_plan["tp_range"] = tp_range
        order_plan["tp_price"] = tp_price
        order_plan["lc_range"] = lc_range
        order_plan["lc_price"] = lc_price
        order_plan["path_tp_adjusted"] = True
        order_plan["path_tp_adjusted_label"] = label
        order_plan["path_tp_pips"] = tp_pips
        order_plan["path_lc_pips"] = lc_pips
        order_plan["path_tp_rr"] = tp_pips / lc_pips if lc_pips else None

        for_api_json = order_plan.get("for_api_json")
        if for_api_json and "order" in for_api_json:
            take_profit = for_api_json["order"].get("takeProfitOnFill")
            if take_profit is not None:
                take_profit["price"] = str(tp_price)
            stop_loss = for_api_json["order"].get("stopLossOnFill")
            if stop_loss is not None:
                stop_loss["price"] = str(lc_price)
        order_class.recalculate_units_from_risk()

    def _apply_path_short_tp(self, order_class):
        order_plan = order_class.exe_order_plan
        path_distance = order_plan.get("h1_path_ahead_1_distance_pips")
        if path_distance is None:
            return

        try:
            path_distance = float(path_distance)
        except (TypeError, ValueError):
            return

        tp_pips = self._path_short_tp_pips(path_distance)
        if self._should_expand_usd_jpy_path_short_tp(order_plan, path_distance):
            tp_pips = 5
        if tp_pips is None:
            return

        current_tp_range = order_plan.get("tp_range")
        current_tp_pips = None
        if current_tp_range is not None:
            current_tp_pips = self.p.price_to_pips(float(current_tp_range))
        if current_tp_pips is not None and current_tp_pips <= tp_pips:
            return

        self._apply_tp_lc_pips(
            order_class,
            tp_pips,
            tp_pips,
            self.pair + " path1 H1 line short TP",
        )

    def _attach_tp_last_touch_context(self, order_class, decision_time):
        """Store the latest completed H1 candle that touched the finalized TP."""
        order_plan = order_class.exe_order_plan
        order_plan["tp_last_touch_time"] = None
        order_plan["tp_last_touch_elapsed_minutes"] = None
        order_plan["tp_last_touch_found"] = False
        order_plan["tp_last_touch_elapsed_bin"] = "no_touch_in_history"
        order_plan["tp_touch_history_oldest_time"] = None
        order_plan["tp_touch_history_coverage_minutes"] = None

        candle_analysis = getattr(self.analysis, "candle_analysis_all", None)
        h1_df_r = getattr(candle_analysis, "h1_df_r", None)
        if h1_df_r is None or h1_df_r.empty:
            return

        try:
            decision_dt = pd.Timestamp(decision_time).to_pydatetime()
            tp_price = float(order_plan["tp_price"])
            direction = int(order_plan.get("direction") or 0)
        except (KeyError, TypeError, ValueError):
            return
        if direction not in (-1, 1):
            return

        candles = h1_df_r.copy()
        if "time_jp_dt" in candles.columns:
            candle_times = pd.to_datetime(candles["time_jp_dt"], errors="coerce")
        elif "time_jp" in candles.columns:
            candle_times = pd.to_datetime(candles["time_jp"], errors="coerce")
        else:
            return
        candles = candles.assign(tp_touch_candle_time=candle_times)

        # Only completed candles are valid in inspection mode. The cached H1
        # candle containing decision_time has future high/low values.
        completed_before = decision_dt - pd.Timedelta(hours=1)
        candles = candles[
            candles["tp_touch_candle_time"] <= completed_before
        ]
        if candles.empty:
            return

        oldest_dt = candles["tp_touch_candle_time"].min().to_pydatetime()
        order_plan["tp_touch_history_oldest_time"] = oldest_dt.strftime("%Y/%m/%d %H:%M:%S")
        order_plan["tp_touch_history_coverage_minutes"] = max(
            int((decision_dt - oldest_dt).total_seconds() // 60),
            0,
        )

        price_column = "high" if direction == 1 else "low"
        if price_column not in candles.columns:
            return
        prices = pd.to_numeric(candles[price_column], errors="coerce")
        touched = candles[prices >= tp_price] if direction == 1 else candles[prices <= tp_price]
        if touched.empty:
            return

        last_touch_dt = touched["tp_touch_candle_time"].max().to_pydatetime()
        elapsed_minutes = max(int((decision_dt - last_touch_dt).total_seconds() // 60), 0)
        order_plan["tp_last_touch_time"] = last_touch_dt.strftime("%Y/%m/%d %H:%M:%S")
        order_plan["tp_last_touch_elapsed_minutes"] = elapsed_minutes
        order_plan["tp_last_touch_found"] = True
        order_plan["tp_last_touch_elapsed_bin"] = self._tp_last_touch_elapsed_bin(elapsed_minutes)

    @staticmethod
    def _tp_last_touch_elapsed_bin(elapsed_minutes):
        for upper, label in (
            (30, "0-30m"),
            (60, "31-60m"),
            (180, "61-180m"),
            (360, "181-360m"),
            (720, "361-720m"),
            (1440, "721-1440m"),
            (2880, "1441-2880m"),
            (4320, "2881-4320m"),
            (7200, "4321-7200m"),
            (10080, "7201-10080m"),
            (15000, "10081-15000m"),
        ):
            if elapsed_minutes <= upper:
                return label
        return "15001m+"

    def _path_short_tp_pips(self, path_distance):
        if self.pair not in ("EUR_USD", "USD_JPY", "AUD_USD"):
            return None
        if self.pair == "AUD_USD":
            if 0 < path_distance <= 6:
                return 5
            return None
        if 0 < path_distance <= 3:
            return 3
        if 3 < path_distance <= 6:
            return 5
        return None

    def _should_expand_usd_jpy_path_short_tp(self, order_plan, path_distance):
        if self.pair != "USD_JPY":
            return False
        if not (0 < path_distance <= 3):
            return False
        try:
            rsi_1 = float(order_plan.get("rsi_1"))
        except (TypeError, ValueError):
            return False
        return 60 < rsi_1 <= 67.5

    def _create_order(
        self,
        candidate,
        selected_candidates,
        current_price,
        decision_time,
        rsi_info,
        order_mode="limit",
    ):
        p = self.p
        strategy = candidate["strategy"]
        line = candidate["line"]
        if order_mode == "immediate":
            order_timeout_min = 0
            order_type = "MARKET"
            target_price = p.round_price(float(current_price))
        else:
            order_timeout_min = self.order_timeout_min_for_distance(
                candidate.get("distance_pips", 0),
                strategy.timeframe,
                strategy.order_timeout_min,
            )
            order_type = strategy.order_type
            target_price = candidate["target_price"]
        lc_range = p.pips_to_price(strategy.lc_pips)
        tp_range = p.pips_to_price(strategy.get_tp_pips())
        risk_multiplier = self._get_risk_multiplier(candidate, decision_time)
        risk_yen = gl_risk_yen * risk_multiplier
        usd_jpy_rate = self._get_usd_jpy_rate(decision_time)

        order_class = OCreate.Order({
            "name": (
                strategy.name_prefix
                + ("Immediate" if order_mode == "immediate" else "")
                + "_"
                + candidate["line_side"]
                + "_"
                + str(candidate["line_index"])
            ),
            "current_price": current_price,
            "target": target_price,
            "direction": candidate["direction"],
            "type": order_type,
            "tp": tp_range,
            "lc": lc_range,
            "lc_change": [],
            "risk_yen": risk_yen,
            "usd_jpy_rate": usd_jpy_rate,
            "priority": int(line.get("total_strength", 0)),
            "decision_time": decision_time,
            "pair": self.pair,
            "candle_analysis_class": self.analysis.candle_analysis_all,
            "lc_change_candle_type": "M5",
            "order_timeout_min": order_timeout_min,
            "memo": candidate.get("memo", ""),
        })
        order_plan = order_class.exe_order_plan
        order_plan["decision_price"] = current_price
        order_plan["target_distance_pips"] = candidate.get("distance_pips")
        order_plan["line_distance_pips"] = candidate.get("line_distance_pips", candidate.get("distance_pips"))
        order_plan["line_target_price"] = candidate.get("line_target_price", candidate.get("target_price"))
        order_plan["source"] = "line"
        order_plan["base_risk_yen"] = gl_risk_yen
        order_plan["risk_timeframe"] = strategy.timeframe
        order_plan["timeframe_risk_multiplier"] = strategy.timeframe_risk_multiplier
        order_plan["risk_multiplier"] = risk_multiplier
        order_plan["risk_yen"] = risk_yen
        order_plan["usd_jpy_rate"] = usd_jpy_rate
        order_plan["line_order_mode"] = order_mode
        order_plan["line_timeframe"] = strategy.timeframe
        order_plan["line_entry_type"] = strategy.entry_type
        order_plan["line_entry_offset_pips"] = strategy.entry_offset_pips
        order_plan["latest_peak_dir"] = candidate.get("latest_peak_dir")
        order_plan["latest_peak_count"] = candidate.get("latest_peak_count")
        order_plan["latest_peak_gap"] = candidate.get("latest_peak_gap")
        order_plan["latest_peak_time"] = candidate.get("latest_peak_time")
        order_plan["latest_peak_strength"] = candidate.get("latest_peak_strength")
        order_plan["latest_peak_price"] = candidate.get("latest_peak_price")
        order_plan["latest_peak_rsi"] = candidate.get("latest_peak_rsi")
        order_plan["previous_peak_dir"] = candidate.get("previous_peak_dir")
        order_plan["previous_peak_count"] = candidate.get("previous_peak_count")
        order_plan["previous_peak_gap"] = candidate.get("previous_peak_gap")
        order_plan["previous_peak_time"] = candidate.get("previous_peak_time")
        order_plan["previous_peak_strength"] = candidate.get("previous_peak_strength")
        order_plan["previous_peak_price"] = candidate.get("previous_peak_price")
        order_plan["previous_peak_rsi"] = candidate.get("previous_peak_rsi")
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
        for key in (
            "line_break_threshold_pips",
            "line_origin_peak_dir",
            "line_origin_role",
            "line_current_role",
            "line_history_is_flipped",
            "line_flip_count",
            "line_latest_flip_time",
            "line_latest_flip_elapsed_minutes",
            "line_latest_flip_bars",
            "line_latest_touch_peak_dir",
            "line_latest_touch_time",
            "line_latest_touch_elapsed_minutes",
            "line_latest_touch_bars",
            "line_touch_count",
            "line_single_role",
            "line_single_role_last_touch_time",
            "line_single_role_last_touch_elapsed_minutes",
            "line_single_role_last_touch_bars",
            "line_peak_rsi_avg",
            "line_peak_rsi_latest",
            "line_peak_rsi_count",
        ):
            order_plan[key] = line.get(key)
        order_plan["line_behavior"] = candidate.get("line_behavior", line.get("behavior"))
        order_plan["line_break_score"] = candidate.get("line_break_score", line.get("break_score"))
        order_plan["line_resist_score"] = candidate.get("line_resist_score", line.get("resist_score"))
        order_plan["line_behavior_reasons"] = " / ".join(
            candidate.get("line_behavior_reasons", line.get("behavior_reasons", []))
        )
        order_plan["line_break_reasons"] = " / ".join(
            candidate.get("line_break_reasons", line.get("break_reasons", []))
        )
        order_plan["line_resist_reasons"] = " / ".join(
            candidate.get("line_resist_reasons", line.get("resist_reasons", []))
        )
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
        self.pair = getattr(candle_analysis, "pair", "USD_JPY")
        self.p = gene.currency_pair(self.pair)
        self.each_pair_line_strategy_profile = line_strategy_profile(self.pair)
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
        requests.post(notice.webhook_url_for_pair(self.pair), json=data)
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

        p = self.p
        spread_pips = 0.8
        lc_pips = 15
        rr = 1.65
        tp_pips = round(rr * (lc_pips + spread_pips) + spread_pips, 1)
        lc_range = p.pips_to_price(lc_pips)
        tp_range = p.pips_to_price(tp_pips)
        risk_yen = gl_risk_yen * 2.0
        usd_jpy_rate = LineOrderCoordinator(self)._get_usd_jpy_rate(decision_time)

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
            order_timeout_min = LineOrderCoordinator.order_timeout_min_for_distance(
                candidate["distance_pips"],
                "h1",
                60,
            )

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
                "risk_yen": risk_yen,
                "usd_jpy_rate": usd_jpy_rate,
                "priority": int(line.get("total_strength", 0)),
                "decision_time": decision_time,
                "pair": self.pair,
                "candle_analysis_class": self.candle_analysis_all,
                "lc_change_candle_type": "M5",
                "order_timeout_min": order_timeout_min,
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
        risk_yen = gl_risk_yen
        usd_jpy_rate = LineOrderCoordinator(self)._get_usd_jpy_rate(decision_time)

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
            order_timeout_min = LineOrderCoordinator.order_timeout_min_for_distance(
                candidate["distance_pips"],
                "m5",
                15,
            )

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
                "risk_yen": risk_yen,
                "usd_jpy_rate": usd_jpy_rate,
                "priority": int(line.get("total_strength", 0)),
                "decision_time": decision_time,
                "pair": self.pair,
                "candle_analysis_class": self.candle_analysis_all,
                "lc_change_candle_type": "M5",
                "order_timeout_min": order_timeout_min,
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
                (UsdJpyM5LineOrderStrategy(self.each_pair_line_strategy_profile), line_class_m5),
                (UsdJpyM5BreakoutLineOrderStrategy(self.each_pair_line_strategy_profile), line_class_m5),
                (UsdJpyH1LineOrderStrategy(self.each_pair_line_strategy_profile), line_class_h1),
            ],
            current_price,
            decision_time,
            rsi_info,
            h1_line_class=line_class_h1,
        )

    def create_line_orders_from_strategy_lines(
        self,
        strategy_lines,
        current_price,
        decision_time,
        rsi_info=None,
        h1_line_class=None,
        m5_line_class=None,
    ):
        return self.create_limit_orders_from_strategy_lines(
            strategy_lines,
            current_price,
            decision_time,
            rsi_info,
            h1_line_class=h1_line_class,
            m5_line_class=m5_line_class,
        )

    def create_limit_orders_from_strategy_lines(
        self,
        strategy_lines,
        current_price,
        decision_time,
        rsi_info=None,
        h1_line_class=None,
        m5_line_class=None,
    ):
        coordinator = LineOrderCoordinator(self)
        return coordinator.create_limit_orders_from_strategy_lines(
            strategy_lines,
            current_price,
            decision_time,
            rsi_info,
            h1_line_class=h1_line_class,
            m5_line_class=m5_line_class,
        )

    def create_immediate_orders_from_near_lines(
        self,
        strategy_lines,
        current_price,
        decision_time,
        rsi_info=None,
        h1_line_class=None,
        m5_line_class=None,
    ):
        coordinator = LineOrderCoordinator(self)
        return coordinator.create_immediate_orders_from_near_lines(
            strategy_lines,
            current_price,
            decision_time,
            rsi_info,
            h1_line_class=h1_line_class,
            m5_line_class=m5_line_class,
        )

    def line_order_coordinator(self):
        return LineOrderCoordinator(self)

    def add_h1_line_limit_orders(self, line_class, current_price, decision_time, rsi_info=None):
        coordinator = LineOrderCoordinator(self)
        return coordinator.create_orders(
            [(UsdJpyH1LineOrderStrategy(self.each_pair_line_strategy_profile), line_class)],
            current_price,
            decision_time,
            rsi_info,
        )

    def add_m5_line_limit_orders(self, line_class, current_price, decision_time, rsi_info=None):
        coordinator = LineOrderCoordinator(self)
        return coordinator.create_orders(
            [(UsdJpyM5LineOrderStrategy(self.each_pair_line_strategy_profile), line_class)],
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
                (UsdJpyM5LineOrderStrategy(self.each_pair_line_strategy_profile), line_class),
                (UsdJpyM5BreakoutLineOrderStrategy(self.each_pair_line_strategy_profile), line_class),
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
        return UsdJpyH1LineOrderStrategy(self.each_pair_line_strategy_profile).is_target(line_side, line)

    def is_m5_line_limit_order_target(self, line_side, line):
        return UsdJpyM5LineOrderStrategy(self.each_pair_line_strategy_profile).is_target(line_side, line)

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
        self.line_analysis()

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
        return self.line_analysis()

    def line_analysis(self):
        # ターン時以外でも実行される
        print("■予測オーダー")
        s = self.s
        p = self.p
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
            if self.mode != "inspection":
                return 0
        elif  f_low['RSI'] >= upper_border and s_low['RSI'] <= upper_border and t_low['RSI'] >= upper_border:
            print("    直近と2個前は越えているが、中央は越えていない⇒継続して越えていきそう？")
            if self.mode != "inspection":
                return 0
        elif f_low['RSI'] <= lower_border and s_low['RSI'] >= lower_border and t_low['RSI'] <= lower_border:
            print("    直近と2個前は30切っているが、中央は切っていない⇒継続して30切っていきそう？")
            if self.mode != "inspection":
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
        rsi_info.update(self.build_timeframe_rsi_info(
            "h1",
            self.candle_analysis_all.h1_df_r,
            upper_border,
            lower_border,
        ))
        m5_line_orders = self.each_pair_line_strategy_profile.create_orders_from_lines(
            self,
            line_class_m5_l,
            line_class_m5_s,
            line_class_h1_l,
            line_class_h1_s,
            current_price,
            df.iloc[0]['time_jp'],
            rsi_info,
        )
        result = self.compare_lines(line_class_h1_l, line_class_h1_s, threshold=0.5)
        peaks_h1 = self.candle_analysis_all.peaks_class_hour.peaks_original
        # gene.print_peaks(peaks_h1)

        # ■RSI と Line 総強度による追加判定
        order_pattern = 0

        before_legacy_rsi_order_count = len(self.exe_order_classes)
        print("Legacy RSI line orders are disabled. Use top7 M5 line orders.")
        # No-order line notices are intentionally disabled for both USD_JPY and EUR_USD.
        # self.notify_count2_line_no_order(
        #     peaks[0],
        #     line_class_m5_l,
        #     line_class_m5_s,
        #     line_class_h1_l,
        #     rsi_info,
        #     order_pattern,
        #     before_legacy_rsi_order_count,
        #     current_price,
        #     df.iloc[0]['time_jp'],
        #     m5_line_orders,
        # )
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
        # No-order line notices are intentionally disabled for both USD_JPY and EUR_USD.
        # notice.line_send(message)

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
        self.s = "     "
        self.foot = foot
        self.max_line_price_gap_pips = None
        self.pair = getattr(candle_analysis_class, "pair", "USD_JPY")
        self.p = gene.currency_pair(self.pair)
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
            self.add_line_role_history(item)
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

    def add_line_role_history(self, line):
        break_threshold_pips = 2
        peaks = line.get("prices_info") or []
        line_price = float(line.get("median_price") or 0)
        line["line_break_threshold_pips"] = break_threshold_pips
        line["line_origin_peak_dir"] = None
        line["line_origin_role"] = None
        line["line_current_role"] = None
        line["line_history_is_flipped"] = False
        line["line_flip_count"] = 0
        line["line_latest_flip_time"] = None
        line["line_latest_flip_elapsed_minutes"] = None
        line["line_latest_flip_bars"] = None
        line["line_latest_touch_peak_dir"] = None
        line["line_latest_touch_time"] = None
        line["line_latest_touch_elapsed_minutes"] = None
        line["line_latest_touch_bars"] = None
        line["line_touch_count"] = len(peaks)
        line["line_single_role"] = None
        line["line_single_role_last_touch_time"] = None
        line["line_single_role_last_touch_elapsed_minutes"] = None
        line["line_single_role_last_touch_bars"] = None
        if not peaks or not line_price or self.df_r is None or self.df_r.empty:
            return

        time_format = "%Y/%m/%d %H:%M:%S"
        current_time = datetime.strptime(self.current_time, time_format)
        origin_peak = peaks[-1]
        latest_peak = peaks[0]
        origin_dir = int(origin_peak["direction"])
        origin_time = datetime.strptime(origin_peak["latest_time_jp"], time_format)
        latest_touch_time = datetime.strptime(latest_peak["latest_time_jp"], time_format)
        origin_role = "resistance" if origin_dir == 1 else "support"

        line["line_origin_peak_dir"] = origin_dir
        line["line_origin_role"] = origin_role
        line["line_latest_touch_peak_dir"] = int(latest_peak["direction"])
        line["line_latest_touch_time"] = latest_touch_time.strftime(time_format)
        line["line_latest_touch_elapsed_minutes"] = round(
            max((current_time - latest_touch_time).total_seconds(), 0) / 60,
            1,
        )

        candles = self.df_r.copy()
        candle_times = pd.to_datetime(candles["time_jp"], format=time_format)
        candles = candles.assign(line_event_time=candle_times)
        candles = candles[
            (candles["line_event_time"] > origin_time)
            & (candles["line_event_time"] <= current_time)
        ].sort_values("line_event_time")
        line["line_latest_touch_bars"] = int(
            (candles["line_event_time"] > latest_touch_time).sum()
        )

        threshold_price = self.p.pips_to_price(break_threshold_pips)
        stable_side = -1 if origin_role == "resistance" else 1
        flip_times = []
        for candle in candles.itertuples(index=False):
            close = float(candle.close)
            if close > line_price + threshold_price:
                close_side = 1
            elif close < line_price - threshold_price:
                close_side = -1
            else:
                continue
            if close_side != stable_side:
                flip_times.append(candle.line_event_time)
                stable_side = close_side

        flip_count = len(flip_times)
        current_role = origin_role
        if flip_count % 2 == 1:
            current_role = "support" if origin_role == "resistance" else "resistance"
        line["line_current_role"] = current_role
        line["line_history_is_flipped"] = current_role != origin_role
        line["line_flip_count"] = flip_count
        if flip_count == 0:
            line["line_single_role"] = origin_role
            line["line_single_role_last_touch_time"] = line["line_latest_touch_time"]
            line["line_single_role_last_touch_elapsed_minutes"] = line[
                "line_latest_touch_elapsed_minutes"
            ]
            line["line_single_role_last_touch_bars"] = line[
                "line_latest_touch_bars"
            ]
        if flip_times:
            latest_flip_time = flip_times[-1]
            line["line_latest_flip_time"] = latest_flip_time.strftime(time_format)
            line["line_latest_flip_elapsed_minutes"] = round(
                max((current_time - latest_flip_time).total_seconds(), 0) / 60,
                1,
            )
            line["line_latest_flip_bars"] = int(
                (candles["line_event_time"] > latest_flip_time).sum()
            )

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
        peak_rsi_values = [
            float(x["rsi"]) for x in sorted_group_items
            if x.get("rsi") is not None and not pd.isna(x.get("rsi"))
        ]
        result["line_peak_rsi_count"] = len(peak_rsi_values)
        result["line_peak_rsi_avg"] = round(sum(peak_rsi_values) / len(peak_rsi_values), 1) if peak_rsi_values else None
        result["line_peak_rsi_latest"] = peak_rsi_values[0] if peak_rsi_values else None

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
