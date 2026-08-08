import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pandas as pd

import fGeneric as gene
from fLineAnalysis import (
    LineOrderCoordinator,
    predict_reversal_last_reach_context,
)
from fLineStrategyAudUsd import LineStrategyProfileAudUsd
from fLineStrategyEurUsd import LineStrategyProfileEurUsd
from fLineStrategyUsdJpy import (
    LineStrategyProfileUsdJpy,
    UsdJpyM5LineOrderStrategy,
)


class LineClassStub:
    def __init__(self, pair, upper_lines=None, lower_lines=None):
        self.pair = pair
        self.upper_lines = list(upper_lines or [])
        self.lower_lines = list(lower_lines or [])


def reversal_line(price):
    return {
        "median_price": price,
        "is_flipped_line": False,
        "count": 1,
        "total_strength": 5,
        "ave_strength": 5,
        "core_count": 1,
        "core_total_strength": 5,
    }


class PredictReversalDirectionTest(unittest.TestCase):
    def test_near_positive_distance_is_kept_as_limit_candidate(self):
        strategy = UsdJpyM5LineOrderStrategy(LineStrategyProfileUsdJpy())
        lines = LineClassStub(
            "USD_JPY",
            upper_lines=[reversal_line(150.001)],
            lower_lines=[reversal_line(149.999)],
        )

        candidates = strategy.build_candidates(lines, 150.000)

        self.assertEqual(len(candidates), 2)
        upper = next(row for row in candidates if row["line_side"] == "upper")
        lower = next(row for row in candidates if row["line_side"] == "lower")
        self.assertAlmostEqual(upper["distance_pips"], 0.1)
        self.assertEqual(upper["direction"], -1)
        self.assertEqual(upper["target_price"], 150.001)
        self.assertAlmostEqual(lower["distance_pips"], 0.1)
        self.assertEqual(lower["direction"], 1)
        self.assertEqual(lower["target_price"], 149.999)

    def test_all_pair_profiles_share_count2_reversal_direction_contract(self):
        for profile_class in (
            LineStrategyProfileUsdJpy,
            LineStrategyProfileEurUsd,
            LineStrategyProfileAudUsd,
        ):
            profile = profile_class()
            strategy = SimpleNamespace(entry_type="reversal")
            with self.subTest(pair=profile.pair, side="upper"):
                reasons = profile.predict_reversal_recommended_reasons(
                    {
                        "strategy": strategy,
                        "timeframe": "m5",
                        "line_side": "upper",
                        "direction": -1,
                        "line": {"count": 2},
                        "m5_stair_context": {"state": "NONE"},
                    },
                    {},
                    {
                        "count": 2,
                        "direction": 1,
                        "rsi": 60,
                        "previous_rsi": 55,
                    },
                )
                self.assertTrue(reasons)
            with self.subTest(pair=profile.pair, side="lower"):
                reasons = profile.predict_reversal_recommended_reasons(
                    {
                        "strategy": strategy,
                        "timeframe": "m5",
                        "line_side": "lower",
                        "direction": 1,
                        "line": {"count": 2},
                        "m5_stair_context": {"state": "NONE"},
                    },
                    {},
                    {
                        "count": 2,
                        "direction": -1,
                        "rsi": 40,
                        "previous_rsi": 45,
                    },
                )
                self.assertTrue(reasons)
            with self.subTest(pair=profile.pair, count="not_count2"):
                reasons = profile.predict_reversal_recommended_reasons(
                    {
                        "strategy": strategy,
                        "timeframe": "m5",
                        "line_side": "upper",
                        "direction": -1,
                        "line": {"count": 2},
                        "m5_stair_context": {"state": "NONE"},
                    },
                    {},
                    {
                        "count": 1,
                        "direction": 1,
                        "rsi": 60,
                        "previous_rsi": 55,
                    },
                )
                self.assertEqual(reasons, [])


class PredictReversalTargetTest(unittest.TestCase):
    @staticmethod
    def m5_frame(forming_range_pips):
        rows = [
            {
                "time_jp_dt": pd.Timestamp("2026-08-02 12:00:00"),
                "high": 150 + forming_range_pips * 0.01,
                "low": 150,
            }
        ]
        for index, range_pips in enumerate((1, 2, 3, 4, 5, 6)):
            rows.append(
                {
                    "time_jp_dt": pd.Timestamp("2026-08-02 11:55:00")
                    - pd.Timedelta(minutes=5 * index),
                    "high": 150 + range_pips * 0.01,
                    "low": 150,
                }
            )
        rows.append(
            {
                "time_jp_dt": pd.Timestamp("2026-08-02 12:05:00"),
                "high": 160,
                "low": 140,
            }
        )
        return pd.DataFrame(rows)

    def coordinator(self, frame):
        coordinator = LineOrderCoordinator.__new__(LineOrderCoordinator)
        coordinator.pair = "USD_JPY"
        coordinator.p = gene.currency_pair("USD_JPY")
        coordinator.analysis = SimpleNamespace(
            candle_analysis_all=SimpleNamespace(d5_df_r=frame)
        )
        return coordinator

    def test_target_uses_only_six_completed_m5_candles(self):
        first = self.coordinator(self.m5_frame(1000)).predict_reversal_target_parameters(
            "2026-08-02 12:02:00",
            lookback=6,
            multiplier=3,
            rr=1.2,
        )
        second = self.coordinator(self.m5_frame(2000)).predict_reversal_target_parameters(
            "2026-08-02 12:02:00",
            lookback=6,
            multiplier=3,
            rr=1.2,
        )

        self.assertIsNotNone(first)
        self.assertAlmostEqual(first["predict_recent_m5_avg_range_pips"], 3.5)
        self.assertAlmostEqual(first["tp_pips"], 10.5)
        self.assertAlmostEqual(first["lc_pips"], 8.75)
        self.assertEqual(first["tp_pips"], second["tp_pips"])
        self.assertEqual(first["lc_pips"], second["lc_pips"])
        self.assertNotIn("next_count2_time", first)
        self.assertNotIn("pending_minutes", first)


class PredictReversalLastReachTest(unittest.TestCase):
    def test_later_completed_retouch_replaces_source_but_forming_touch_does_not(self):
        frame = pd.DataFrame(
            [
                {
                    "time_jp": "2026/08/02 12:00:00",
                    "high": 150.01,
                    "low": 149.99,
                },
                {
                    "time_jp": "2026/08/02 12:05:00",
                    "high": 149.95,
                    "low": 149.90,
                },
                {
                    "time_jp": "2026/08/02 12:10:00",
                    "high": 150.005,
                    "low": 149.995,
                },
                {
                    "time_jp": "2026/08/02 12:15:00",
                    "high": 150.005,
                    "low": 149.995,
                },
            ]
        )
        line = {
            "median_price": 150.0,
            "newest_time": "2026/08/02 12:00:00",
        }

        result = predict_reversal_last_reach_context(
            frame,
            line,
            "2026/08/02 12:17:00",
            "USD_JPY",
            tolerance_pips=0.5,
        )

        self.assertTrue(result["predict_last_reach_found"])
        self.assertEqual(
            result["predict_last_reach_time"],
            "2026/08/02 12:10:00",
        )
        self.assertEqual(result["predict_last_reach_elapsed_minutes"], 7)
        self.assertEqual(result["predict_last_reach_source"], "prior_retouch")
        self.assertEqual(result["predict_prior_retouch_count"], 1)

    def test_future_prices_do_not_change_last_reach(self):
        frame = pd.DataFrame(
            [
                {
                    "time_jp": "2026/08/02 11:55:00",
                    "high": 150.01,
                    "low": 149.99,
                },
                {
                    "time_jp": "2026/08/02 12:00:00",
                    "high": 149.90,
                    "low": 149.80,
                },
                {
                    "time_jp": "2026/08/02 12:05:00",
                    "high": 150.01,
                    "low": 149.99,
                },
            ]
        )
        changed = frame.copy()
        changed.loc[2, ["high", "low"]] = [999, -999]
        line = {
            "median_price": 150.0,
            "newest_time": "2026/08/02 11:55:00",
        }

        first = predict_reversal_last_reach_context(
            frame,
            line,
            "2026/08/02 12:07:00",
            "USD_JPY",
        )
        second = predict_reversal_last_reach_context(
            changed,
            line,
            "2026/08/02 12:07:00",
            "USD_JPY",
        )

        self.assertEqual(first, second)
        self.assertEqual(first["predict_last_reach_source"], "line_source")


class PredictReversalSelectionTest(unittest.TestCase):
    @staticmethod
    def rank_candidate(
        distance_pips=2,
        distance_ratio=0.2,
        elapsed_minutes=120,
        average_strength=6,
        line_count=1,
    ):
        return {
            "line_index": 0,
            "line_price": 150.02,
            "distance_pips": distance_pips,
            "predict_distance_to_tp_ratio": distance_ratio,
            "predict_source_reach_elapsed_minutes": elapsed_minutes,
            "predict_last_reach_elapsed_minutes": elapsed_minutes,
            "predict_last_reach_source": "line_source",
            "predict_prior_retouch_count": 0,
            "direction": -1,
            "line": {
                "ave_strength": average_strength,
                "count": line_count,
                "core_count": 1,
                "core_total_strength": 5,
                "line_peak_rsi_latest": 60,
            },
        }

    def test_all_pairs_have_distinct_rank_versions_and_rsi_changes_score(self):
        expected = {
            LineStrategyProfileUsdJpy: (
                "pair_v2_usd_rsi_strength_reach",
                0.5,
            ),
            LineStrategyProfileEurUsd: (
                "pair_v2_eur_rsi_strength_reach",
                0.5,
            ),
            LineStrategyProfileAudUsd: (
                "pair_v2_aud_rsi_strength_reach",
                0.75,
            ),
        }
        for profile_class, (version, cap) in expected.items():
            profile = profile_class()
            low = profile.rank_predict_reversal_candidates(
                [self.rank_candidate()],
                rsi_info={"rsi_1": 40, "rsi_2": 45, "rsi_3": 50},
                latest_peak_info={"direction": 1, "count": 2},
            )[0]
            high = profile.rank_predict_reversal_candidates(
                [self.rank_candidate()],
                rsi_info={"rsi_1": 60, "rsi_2": 55, "rsi_3": 50},
                latest_peak_info={"direction": 1, "count": 2},
            )[0]
            with self.subTest(pair=profile.pair):
                self.assertEqual(low["predict_ranking_version"], version)
                self.assertEqual(low["predict_rank_distance_ratio_cap"], cap)
                self.assertNotEqual(
                    low["predict_rank_score"],
                    high["predict_rank_score"],
                )

    def test_effective_last_reach_elapsed_changes_each_pair_score(self):
        for profile_class in (
            LineStrategyProfileUsdJpy,
            LineStrategyProfileEurUsd,
            LineStrategyProfileAudUsd,
        ):
            profile = profile_class()
            recent = profile.rank_predict_reversal_candidates(
                [self.rank_candidate(elapsed_minutes=20)],
                rsi_info={"rsi_1": 50, "rsi_2": 50, "rsi_3": 50},
                latest_peak_info={"direction": 1, "count": 2},
            )[0]
            older = profile.rank_predict_reversal_candidates(
                [self.rank_candidate(elapsed_minutes=120)],
                rsi_info={"rsi_1": 50, "rsi_2": 50, "rsi_3": 50},
                latest_peak_info={"direction": 1, "count": 2},
            )[0]
            with self.subTest(pair=profile.pair):
                self.assertNotEqual(
                    recent["predict_rank_score"],
                    older["predict_rank_score"],
                )

    def test_outside_cap_uses_nearest_fallback_and_records_it(self):
        profile = LineStrategyProfileUsdJpy()
        near = self.rank_candidate(distance_pips=8, distance_ratio=0.8)
        near["line_index"] = 0
        far = self.rank_candidate(
            distance_pips=12,
            distance_ratio=1.2,
            average_strength=8,
        )
        far["line_index"] = 1

        ranked = profile.rank_predict_reversal_candidates(
            [far, near],
            rsi_info={"rsi_1": 40, "rsi_2": 45, "rsi_3": 50},
            latest_peak_info={"direction": 1, "count": 2},
        )

        self.assertIs(ranked[0], near)
        self.assertEqual(
            ranked[0]["predict_rank_fallback"],
            "nearest_outside_ratio_cap",
        )
        self.assertFalse(ranked[0]["predict_rank_in_distance_cap"])

    def test_live_count2_without_candidate_emits_expiry_control(self):
        profile = LineStrategyProfileUsdJpy()

        class AnalysisStub:
            mode = "live"

            def __init__(self):
                self.added = None

            def add_order_to_this_class(self, orders):
                self.added = orders

        class CoordinatorStub:
            def __init__(self):
                self.analysis = AnalysisStub()

            @staticmethod
            def _latest_peak_info(timeframe):
                return {
                    "count": 2,
                    "direction": 1,
                    "time": "2026-08-02 12:00:00",
                }

            @staticmethod
            def select_line_candidates(*args, **kwargs):
                return []

        coordinator = CoordinatorStub()
        result = profile.predict_reversal_order(
            {
                "coordinator": coordinator,
                "future_resist_candidates": [],
                "rsi_info": {},
                "decision_time": "2026-08-02 12:00:00",
                "current_price": 150.0,
            }
        )

        self.assertEqual(len(result), 1)
        control_plan = result[0].exe_order_plan
        self.assertEqual(
            control_plan["line_order_mode"],
            "predict_reversal_count2_control",
        )
        self.assertEqual(
            control_plan["predict_signal_id"],
            "1:2026-08-02 12:00:00",
        )
        self.assertEqual(coordinator.analysis.added, result)

    def test_highest_pair_score_inside_distance_cap_becomes_predict_order(self):
        profile = LineStrategyProfileUsdJpy()
        close = {
            "distance_pips": 0.1,
            "target_price": 150.001,
            "line_side": "upper",
            "line_index": 0,
            "direction": -1,
            "line_price": 150.001,
            "line": {
                "ave_strength": 5,
                "count": 3,
                "line_flip_count": 0,
            },
        }
        far = {
            "distance_pips": 6,
            "target_price": 150.060,
            "line_side": "upper",
            "line_index": 1,
            "direction": -1,
            "line_price": 150.060,
            "line": {
                "ave_strength": 8,
                "count": 1,
                "line_flip_count": 0,
            },
        }

        class CoordinatorStub:
            def __init__(self):
                self.created_candidates = None
                self.created_mode = None
                self.analysis = SimpleNamespace(mode="inspection")

            @staticmethod
            def _latest_peak_info(timeframe):
                return {
                    "count": 2,
                    "direction": 1,
                    "time": "2026-08-02 12:00:00",
                }

            @staticmethod
            def select_line_candidates(*args, **kwargs):
                return [far, close]

            @staticmethod
            def predict_reversal_target_parameters(*args, **kwargs):
                return {"tp_pips": 15, "lc_pips": 12.5}

            def create_orders_from_candidates(
                self,
                candidates,
                current_price,
                decision_time,
                rsi_info,
                order_mode,
            ):
                self.created_candidates = candidates
                self.created_mode = order_mode
                return ["predict-order"]

        coordinator = CoordinatorStub()
        result = profile.predict_reversal_order(
            {
                "coordinator": coordinator,
                "future_resist_candidates": [far, close],
                "rsi_info": {"rsi_1": 40, "rsi_2": 45, "rsi_3": 50},
                "decision_time": "2026-08-02 12:00:00",
                "current_price": 150.000,
            }
        )

        self.assertEqual(result, ["predict-order"])
        self.assertEqual(coordinator.created_mode, "predict_reversal")
        self.assertEqual(coordinator.created_candidates, [far])
        self.assertEqual(far["predict_candidate_rank"], 1)
        self.assertEqual(far["predict_distance_rank"], 2)
        self.assertEqual(close["predict_candidate_rank"], 2)
        self.assertEqual(close["predict_distance_rank"], 1)
        self.assertEqual(far["predict_candidate_count"], 2)
        self.assertEqual(
            far["predict_ranking_version"],
            "pair_v2_usd_rsi_strength_reach",
        )
        self.assertGreater(far["predict_rank_score"], close["predict_rank_score"])
        self.assertEqual(
            far["predict_candidate_scope"],
            "m5_reversal_target_after_regime",
        )
        self.assertEqual(
            far["predict_pending_policy"],
            "next_count2_or_distance_ttl_15_30_45m",
        )
        self.assertEqual(
            far["predict_signal_id"],
            "1:2026-08-02 12:00:00",
        )
        self.assertTrue(far["preserve_strategy_tp_lc"])
        self.assertFalse(
            far["predict_pending_conflict_control_applied"]
        )
        self.assertEqual(
            far["predict_inspection_lifecycle_note"],
            "pending_conflict_control_not_simulated",
        )

    def test_quality_ranking_is_input_order_invariant_and_future_safe(self):
        profile = LineStrategyProfileUsdJpy()

        def candidates():
            return [
                {
                    "line_index": 0,
                    "line_price": 150.001,
                    "distance_pips": 0.1,
                    "predict_distance_to_tp_ratio": 0.01,
                    "direction": -1,
                    "candidate_result": "tp",
                    "fill_time": "2099-01-01 00:00:00",
                    "line": {
                        "ave_strength": 5,
                        "count": 2,
                        "line_flip_count": 0,
                    },
                },
                {
                    "line_index": 1,
                    "line_price": 150.080,
                    "distance_pips": 8,
                    "predict_distance_to_tp_ratio": 0.4,
                    "direction": -1,
                    "candidate_result": "lc",
                    "fill_time": "2000-01-01 00:00:00",
                    "line": {
                        "ave_strength": 7,
                        "count": 1,
                        "line_flip_count": 1,
                    },
                },
            ]

        rank_context = {
            "rsi_info": {"rsi_1": 40, "rsi_2": 45, "rsi_3": 50},
            "latest_peak_info": {"direction": 1, "count": 2},
        }
        first = profile.rank_predict_reversal_candidates(
            candidates(),
            **rank_context,
        )
        second = profile.rank_predict_reversal_candidates(
            list(reversed(candidates())),
            **rank_context,
        )
        self.assertEqual(
            [row["line_index"] for row in first],
            [1, 0],
        )
        self.assertEqual(
            [row["line_index"] for row in second],
            [1, 0],
        )
        self.assertEqual(
            [row["predict_rank_score"] for row in first],
            [row["predict_rank_score"] for row in second],
        )

    def test_unrankable_distance_is_rejected_but_near_positive_is_kept(self):
        profile = LineStrategyProfileUsdJpy()
        base_line = {
            "ave_strength": 5,
            "count": 1,
            "line_flip_count": 0,
        }
        ranked = profile.rank_predict_reversal_candidates(
            [
                {
                    "line_index": 0,
                    "distance_pips": 0,
                    "predict_distance_to_tp_ratio": 0.01,
                    "direction": -1,
                    "line": base_line,
                },
                {
                    "line_index": 1,
                    "distance_pips": float("nan"),
                    "predict_distance_to_tp_ratio": 0.01,
                    "direction": -1,
                    "line": base_line,
                },
                {
                    "line_index": 2,
                    "distance_pips": 0.1,
                    "predict_distance_to_tp_ratio": 0.01,
                    "direction": -1,
                    "line": base_line,
                },
            ],
            rsi_info={"rsi_1": 50, "rsi_2": 50, "rsi_3": 50},
            latest_peak_info={"direction": 1, "count": 2},
        )

        self.assertEqual([row["line_index"] for row in ranked], [2])
        self.assertEqual(ranked[0]["predict_distance_rank"], 1)

    def test_live_filtered_predict_order_still_emits_expiry_control(self):
        profile = LineStrategyProfileUsdJpy()
        candidate = {
            "distance_pips": 1,
            "target_price": 150.01,
            "line_side": "upper",
            "direction": -1,
        }

        class AnalysisStub:
            mode = "live"

            def __init__(self):
                self.added = None

            def add_order_to_this_class(self, orders):
                self.added = orders

        class CoordinatorStub:
            def __init__(self):
                self.analysis = AnalysisStub()

            @staticmethod
            def _latest_peak_info(timeframe):
                return {
                    "count": 2,
                    "direction": 1,
                    "time": "2026-08-02 12:00:00",
                }

            @staticmethod
            def select_line_candidates(*args, **kwargs):
                return [candidate]

            @staticmethod
            def predict_reversal_target_parameters(*args, **kwargs):
                return {"tp_pips": 15, "lc_pips": 12.5}

            @staticmethod
            def create_orders_from_candidates(*args, **kwargs):
                return []

        coordinator = CoordinatorStub()
        result = profile.predict_reversal_order(
            {
                "coordinator": coordinator,
                "future_resist_candidates": [candidate],
                "rsi_info": {},
                "decision_time": "2026-08-02 12:00:00",
                "current_price": 150.0,
            }
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(
            result[0].exe_order_plan["predict_control_reason"],
            "predict_order_creation_filtered",
        )

    def test_predict_order_has_priority_over_immediate_breakout(self):
        profile = LineStrategyProfileUsdJpy()
        coordinator = SimpleNamespace(
            _latest_peak_info=lambda timeframe: {"count": 2, "direction": 1}
        )
        profile.calculate_line_strength = lambda *args, **kwargs: {}
        profile.group_lines = lambda context: {"coordinator": coordinator}
        profile.predict_reversal_order = Mock(return_value=["predict-order"])
        profile.immediate_order = Mock(return_value=["immediate-order"])
        profile.future_line_order = Mock(return_value=["future-order"])

        result = profile.create_orders_from_lines(
            None,
            None,
            None,
            None,
            None,
            150,
            "2026-08-02 12:00:00",
            {},
        )

        self.assertEqual(result, ["predict-order"])
        profile.immediate_order.assert_not_called()
        profile.future_line_order.assert_not_called()

    def test_count2_without_predict_candidate_does_not_fallback_to_breakout(self):
        profile = LineStrategyProfileUsdJpy()
        coordinator = SimpleNamespace(
            _latest_peak_info=lambda timeframe: {"count": 2, "direction": -1}
        )
        profile.calculate_line_strength = lambda *args, **kwargs: {}
        profile.group_lines = lambda context: {"coordinator": coordinator}
        profile.predict_reversal_order = Mock(return_value=[])
        profile.immediate_order = Mock(return_value=["immediate-order"])
        profile.future_line_order = Mock(return_value=["future-order"])

        result = profile.create_orders_from_lines(
            None,
            None,
            None,
            None,
            None,
            150,
            "2026-08-02 12:00:00",
            {},
        )

        self.assertEqual(result, [])
        profile.immediate_order.assert_not_called()
        profile.future_line_order.assert_not_called()

    def test_live_predict_refresh_reaches_position_controller_before_dedupe(self):
        coordinator = LineOrderCoordinator.__new__(LineOrderCoordinator)
        coordinator.duplicate_threshold_pips = 3
        order = SimpleNamespace(
            exe_order_plan={"line_timeframe": "m5"}
        )

        class AnalysisStub:
            mode = "live"

            def __init__(self):
                self.include_position_control = None
                self.added = None

            def has_similar_order(self, *args, **kwargs):
                self.include_position_control = kwargs.get(
                    "include_position_control"
                )
                # Simulate a duplicate that exists only in PositionControl.
                return self.include_position_control

            def add_order_to_this_class(self, orders):
                self.added = orders

        analysis = AnalysisStub()
        coordinator.analysis = analysis
        coordinator._remove_near_candidates = lambda candidates: candidates
        coordinator._create_order = Mock(return_value=order)
        coordinator.adjust_order_by_session = Mock(return_value=order)
        coordinator._apply_path_short_tp = Mock()
        coordinator._attach_tp_last_touch_context = Mock()
        candidate = {
            "direction": -1,
            "target_price": 150.0,
            "line_strategy": "m5_reversal",
        }

        result = coordinator.create_orders_from_candidates(
            [candidate],
            149.99,
            "2026-08-02 12:00:00",
            {},
            "predict_reversal",
        )

        self.assertEqual(result, [order])
        self.assertFalse(analysis.include_position_control)
        self.assertEqual(analysis.added, [order])


class PredictReversalOrderPlanTest(unittest.TestCase):
    def coordinator(self):
        coordinator = LineOrderCoordinator.__new__(LineOrderCoordinator)
        coordinator.pair = "USD_JPY"
        coordinator.p = gene.currency_pair("USD_JPY")
        coordinator.profile = LineStrategyProfileUsdJpy()
        coordinator.analysis = SimpleNamespace(
            mode="inspection",
            candle_analysis_all=SimpleNamespace(),
            regime_order_context={},
        )
        return coordinator

    def test_candidate_tp_lc_override_reaches_limit_order_plan(self):
        coordinator = self.coordinator()
        strategy = UsdJpyM5LineOrderStrategy(coordinator.profile)
        candidate = {
            "strategy": strategy,
            "line": reversal_line(150.001),
            "line_side": "upper",
            "line_index": 0,
            "direction": -1,
            "target_price": 150.001,
            "line_price": 150.001,
            "distance_pips": 0.1,
            "line_strategy": strategy.line_strategy,
            "timeframe": "m5",
            "tp_pips": 10.5,
            "lc_pips": 8.75,
            "preserve_strategy_tp_lc": True,
            "predict_signal_id": "1:2026-08-02 12:00:00",
            "prediction_target": "next_count2_reversal",
            "predict_candidate_rank": 1,
            "predict_distance_rank": 2,
            "predict_ranking_version": "pair_v2_usd_rsi_strength_reach",
            "predict_rank_input_scope": (
                "decision_time_pair_distance_completed_m5_rsi_"
                "line_strength_last_reach"
            ),
            "predict_rank_score": 7.653426,
            "predict_rank_pair": "USD_JPY",
            "predict_distance_to_tp_ratio": 0.01,
            "predict_rank_distance_to_tp_ratio": 0.01,
            "predict_rank_rsi_1": 61.2,
            "predict_rank_last_reach_elapsed_minutes": 75.0,
            "predict_rank_last_reach_source": "prior_retouch",
            "predict_rank_prior_retouch_count": 2,
            "predict_rank_components": "distance_rsi=2.0 | reach=1.0",
            "predict_rank_in_distance_cap": True,
            "predict_rank_distance_ratio_cap": 0.5,
            "predict_rank_fallback": None,
            "predict_last_reach_found": True,
            "predict_last_reach_time": "2026/08/02 10:45:00",
            "predict_last_reach_elapsed_minutes": 75.0,
            "predict_last_reach_source": "prior_retouch",
            "predict_prior_retouch_count": 2,
            "predict_source_reach_time": "2026/08/02 08:00:00",
            "predict_source_reach_elapsed_minutes": 240.0,
            "predict_last_reach_tolerance_pips": 1.0,
            "predict_runner_up_score": 4.450694,
            "predict_score_gap": 3.202732,
            "predict_pending_conflict_control_applied": False,
            "predict_inspection_lifecycle_note": (
                "pending_conflict_control_not_simulated"
            ),
            "h1_context": {},
        }

        class CapturingOrder:
            payload = None

            def __init__(self, payload):
                type(self).payload = payload
                self.exe_order_plan = {
                    "direction": payload["direction"],
                    "target_price": payload["target"],
                    "tp_range": payload["tp"],
                    "lc_range": payload["lc"],
                    "name": payload["name"],
                    "for_api_json": {},
                }

        with patch("fLineAnalysis.OCreate.Order", CapturingOrder):
            order = coordinator._create_order(
                candidate,
                [candidate],
                150.000,
                "2026-08-02 12:00:00",
                {},
                "predict_reversal",
            )

        payload = CapturingOrder.payload
        self.assertEqual(payload["type"], "LIMIT")
        self.assertEqual(payload["direction"], -1)
        self.assertEqual(payload["target"], 150.001)
        self.assertEqual(payload["order_timeout_min"], 15)
        self.assertAlmostEqual(payload["tp"], 0.105)
        self.assertAlmostEqual(payload["lc"], 0.088)
        self.assertIn("PredictReversal", payload["name"])
        self.assertEqual(order.exe_order_plan["line_order_mode"], "predict_reversal")
        self.assertTrue(order.exe_order_plan["preserve_strategy_tp_lc"])
        self.assertEqual(
            order.exe_order_plan["predict_signal_id"],
            "1:2026-08-02 12:00:00",
        )
        self.assertFalse(
            order.exe_order_plan[
                "predict_pending_conflict_control_applied"
            ]
        )
        self.assertEqual(order.exe_order_plan["predict_candidate_rank"], 1)
        self.assertEqual(order.exe_order_plan["predict_distance_rank"], 2)
        self.assertEqual(
            order.exe_order_plan["predict_ranking_version"],
            "pair_v2_usd_rsi_strength_reach",
        )
        self.assertAlmostEqual(
            order.exe_order_plan["predict_rank_score"],
            7.653426,
        )
        self.assertAlmostEqual(order.exe_order_plan["predict_score_gap"], 3.202732)
        self.assertEqual(order.exe_order_plan["predict_rank_pair"], "USD_JPY")
        self.assertEqual(order.exe_order_plan["predict_rank_rsi_1"], 61.2)
        self.assertEqual(
            order.exe_order_plan["predict_rank_last_reach_source"],
            "prior_retouch",
        )
        self.assertEqual(order.exe_order_plan["predict_prior_retouch_count"], 2)
        self.assertTrue(order.exe_order_plan["predict_rank_in_distance_cap"])
        self.assertAlmostEqual(order.exe_order_plan["configured_lc_pips"], 8.75)

    def test_session_and_path_do_not_overwrite_predict_target(self):
        coordinator = self.coordinator()
        order = SimpleNamespace(
            exe_order_plan={
                "name": "predict",
                "preserve_strategy_tp_lc": True,
                "h1_path_ahead_1_distance_pips": 1,
            }
        )
        coordinator._apply_rr_to_tp = Mock()
        coordinator._apply_tp_lc_pips = Mock()

        kept = coordinator.adjust_order_by_session(
            order,
            "2026-08-02 08:00:00",
        )
        coordinator._apply_path_short_tp(order)

        self.assertIs(kept, order)
        coordinator._apply_rr_to_tp.assert_not_called()
        coordinator._apply_tp_lc_pips.assert_not_called()
        self.assertIn(
            "predict_reversal",
            order.exe_order_plan["session_tp_adjustment_skipped"],
        )
        self.assertIn(
            "predict_reversal",
            order.exe_order_plan["path_tp_adjustment_skipped"],
        )

    def test_distance_timeouts_are_causal_and_explicit(self):
        self.assertEqual(
            LineOrderCoordinator.order_timeout_min_for_distance(0.1, "m5", 15),
            15,
        )
        self.assertEqual(
            LineOrderCoordinator.order_timeout_min_for_distance(5, "m5", 15),
            30,
        )
        self.assertEqual(
            LineOrderCoordinator.order_timeout_min_for_distance(8, "m5", 15),
            45,
        )

    def test_non_jpy_inspection_conversion_uses_past_rate_only(self):
        coordinator = self.coordinator()
        coordinator.pair = "EUR_USD"
        coordinator.p = gene.currency_pair("EUR_USD")
        original = LineOrderCoordinator._inspection_usd_jpy_close
        try:
            LineOrderCoordinator._inspection_usd_jpy_close = pd.Series(
                [150.0, 200.0],
                index=pd.DatetimeIndex(
                    [
                        "2026-08-02 11:55:00",
                        "2026-08-02 12:05:00",
                    ]
                ),
            )

            rate = coordinator._get_usd_jpy_rate("2026-08-02 12:03:00")
        finally:
            LineOrderCoordinator._inspection_usd_jpy_close = original

        self.assertEqual(rate, 150.0)

    def test_non_jpy_conversion_excludes_equal_time_forming_m5_close(self):
        coordinator = self.coordinator()
        coordinator.pair = "AUD_USD"
        coordinator.p = gene.currency_pair("AUD_USD")
        original = LineOrderCoordinator._inspection_usd_jpy_close
        try:
            LineOrderCoordinator._inspection_usd_jpy_close = pd.Series(
                [150.0, 200.0],
                index=pd.DatetimeIndex(
                    [
                        "2026-08-02 11:55:00",
                        "2026-08-02 12:00:00",
                    ]
                ),
            )

            rate = coordinator._get_usd_jpy_rate(
                "2026-08-02 12:00:00"
            )
        finally:
            LineOrderCoordinator._inspection_usd_jpy_close = original

        self.assertEqual(rate, 150.0)


if __name__ == "__main__":
    unittest.main()
