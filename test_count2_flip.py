import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pandas as pd

import fGeneric as gene
from count2_flip_core import (
    FlipPathConfig,
    FlipPathInspector,
    PolicyCondition,
    RankedPolicyCondition,
    TierExecutionConfig,
    TradeCombo,
    _is_expected_market_closed_gap,
    add_feature_buckets,
    condition_mask,
    default_tier_execution_configs,
    effective_trade_widths,
    enumerate_conditions,
)
from count2_flip_pipeline import parse_args
from count2_flip_workflow import (
    replay_condition,
    select_top_condition_policy_candidates,
    select_top_ranked_conditions,
    write_progress,
)


def make_inspector(rows, pair_name="USD_JPY", end="2025-01-06 01:00:00"):
    frame = pd.DataFrame(rows)
    inspector = SimpleNamespace(
        times=pd.to_datetime(frame["time"]).to_numpy(dtype="datetime64[ns]"),
        opens=frame["open"].to_numpy(dtype=float),
        closes=frame["close"].to_numpy(dtype=float),
        highs=frame["high"].to_numpy(dtype=float),
        lows=frame["low"].to_numpy(dtype=float),
    )
    pair = gene.currency_pair(pair_name)
    return FlipPathInspector(
        inspector,
        pair,
        period_end_exclusive=pd.Timestamp(end),
        spread_pips=0.8,
        position_horizon_minutes=10,
        min_width_pips=1.6,
        risk_yen=50,
    )


def base_s5_rows(start="2025-01-06 00:00:00", periods=480, price=149.98):
    times = pd.date_range(start, periods=periods, freq="5s")
    return [
        {
            "time": timestamp,
            "open": price,
            "close": price,
            "high": price + 0.001,
            "low": price - 0.001,
        }
        for timestamp in times
    ]


class FlipPathTest(unittest.TestCase):
    def test_up_approach_fills_sell_on_first_touch_without_breakout(self):
        rows = base_s5_rows()
        rows[20].update(open=149.99, close=149.995, high=150.005, low=149.985)
        rows[21].update(open=149.99, close=149.96, high=149.995, low=149.95)
        inspector = make_inspector(rows)
        result = inspector.inspect(
            decision_time=pd.Timestamp("2025-01-06 00:00:00"),
            line_price=150.0,
            order_direction=-1,
            average_range_pips=2.0,
            path_config=FlipPathConfig(20),
            trade_combos=(TradeCombo(1.5, 1.0),),
        )
        self.assertEqual(result["approach_direction"], 1)
        self.assertEqual(result["order_direction"], -1)
        self.assertTrue(result["order_filled"])
        self.assertEqual(result["fill_time"], pd.Timestamp("2025-01-06 00:01:40"))
        outcome = result["outcomes"]["tp1p5A_lc1A"]
        self.assertEqual(outcome["trade_result"], "tp")
        self.assertGreater(outcome["trade_result_pips"], 0)

    def test_down_approach_fills_buy_on_first_touch(self):
        rows = base_s5_rows(price=150.02)
        rows[20].update(open=150.01, close=150.005, high=150.015, low=149.995)
        rows[21].update(open=150.01, close=150.04, high=150.05, low=150.005)
        inspector = make_inspector(rows)
        result = inspector.inspect(
            decision_time=pd.Timestamp("2025-01-06 00:00:00"),
            line_price=150.0,
            order_direction=1,
            average_range_pips=2.0,
            path_config=FlipPathConfig(20),
            trade_combos=(TradeCombo(1.5, 1.0),),
        )
        self.assertEqual(result["approach_direction"], -1)
        self.assertEqual(result["order_direction"], 1)
        self.assertTrue(result["order_filled"])
        self.assertEqual(result["fill_time"], pd.Timestamp("2025-01-06 00:01:40"))

    def test_no_line_touch_places_no_trade(self):
        rows = base_s5_rows(periods=240)
        inspector = make_inspector(rows, end="2025-01-06 00:20:00")
        result = inspector.inspect(
            decision_time=pd.Timestamp("2025-01-06 00:00:00"),
            line_price=150.0,
            order_direction=-1,
            average_range_pips=2.0,
            path_config=FlipPathConfig(15),
            trade_combos=(TradeCombo(1.5, 1.0),),
        )
        self.assertFalse(result["order_filled"])
        self.assertEqual(result["path_status"], "no_fill")

    def test_next_foot_count2_replaces_unfilled_order(self):
        inspector = make_inspector(base_s5_rows())
        result = inspector.inspect(
            decision_time=pd.Timestamp("2025-01-06 00:00:00"),
            line_price=150.0,
            order_direction=-1,
            average_range_pips=2.0,
            path_config=FlipPathConfig(20),
            trade_combos=(TradeCombo(1.5, 1.0),),
            next_count2_time=pd.Timestamp("2025-01-06 00:05:00"),
        )
        self.assertEqual(result["path_status"], "replaced_before_fill")
        self.assertTrue(result["replaced_before_fill"])
        self.assertEqual(result["order_deadline"], pd.Timestamp("2025-01-06 00:05:00"))

    def test_same_s5_tp_lc_is_conservative_loss(self):
        rows = base_s5_rows()
        rows[20].update(open=150.01, close=150.0, high=150.03, low=149.95)
        inspector = make_inspector(rows)
        result = inspector.inspect(
            decision_time=pd.Timestamp("2025-01-06 00:00:00"),
            line_price=150.0,
            order_direction=-1,
            average_range_pips=2.0,
            path_config=FlipPathConfig(20),
            trade_combos=(TradeCombo(1.5, 1.0),),
        )
        outcome = result["outcomes"]["tp1p5A_lc1A"]
        self.assertEqual(outcome["trade_result"], "both_same_s5_lc_assumed")
        self.assertLess(outcome["trade_result_pips"], 0)

    def test_ambiguous_fill_bar_tp_is_not_carried_into_later_bars(self):
        rows = base_s5_rows()
        rows[20].update(open=149.98, close=149.995, high=150.005, low=149.95)
        inspector = make_inspector(rows)
        result = inspector.inspect(
            decision_time=pd.Timestamp("2025-01-06 00:00:00"),
            line_price=150.0,
            order_direction=-1,
            average_range_pips=2.0,
            path_config=FlipPathConfig(20),
            trade_combos=(TradeCombo(1.5, 1.0),),
        )
        outcome = result["outcomes"]["tp1p5A_lc1A"]
        self.assertEqual(outcome["trade_result"], "timeout")

    def test_christmas_weekend_join_is_a_known_market_closure(self):
        self.assertTrue(
            _is_expected_market_closed_gap(
                pd.Timestamp("2023-12-23 06:58:55"),
                pd.Timestamp("2023-12-26 07:03:00"),
            )
        )


class FeatureAndReplayTest(unittest.TestCase):
    def feature_frame(self):
        return pd.DataFrame(
            {
                "decision_time": pd.to_datetime(
                    ["2025-01-06 09:00", "2025-01-06 09:05", "2025-01-06 09:10"]
                ),
                "distance_rank": [1, 2, 1],
                "distance_pips": [2.0, 4.0, 3.0],
                "recent_m5_avg_range_pips": [2.0, 2.0, 2.0],
                "line_count": [2, 3, 2],
                "line_core_count": [1, 2, 1],
                "line_average_strength": [2.0, 2.5, 1.0],
                "line_total_strength": [4, 8, 2],
                "line_is_flipped": [True, False, True],
                "line_flip_count": [0, 1, 0],
                "line_history_is_flipped": [False, True, False],
                "line_age_minutes": [30, 300, 90],
                "prior_retouch_count": [0, 2, 1],
                "peak_strength": [3, 4, 2],
                "peak_direction": [1, -1, 1],
                "rsi_1": [55, 45, 70],
                "fc2_shape": ["STALL", "REJECTION", "STALL"],
                "fc2_candle_sequence": ["BULL_BEAR", "BEAR_BULL", "BULL_BEAR"],
                "fc2_second_wick_A": [0.30, 0.08, 0.45],
                "fc2_second_close_pushback_A": [0.40, 0.05, 0.55],
                "fc2_second_body_to_first_ratio": [0.50, 1.10, 0.60],
                "h1_pair_shape": ["CONTINUATION", "STALL", "CONTINUATION"],
                "m5_stair_observed_direction": [1, 1, 0],
                "h1_stair_observed_direction": [0, -1, 1],
            }
        )

    def test_feature_conditions_are_replayable(self):
        frame = add_feature_buckets(self.feature_frame())
        conditions = enumerate_conditions(frame, minimum_candidates=2)
        condition = next(
            item for item in conditions if item.condition_id == "f_distance_rank=1"
        )
        self.assertEqual(condition_mask(frame, condition).tolist(), [True, False, True])
        restored = PolicyCondition.from_dict(condition.to_dict())
        self.assertEqual(restored, condition)

    def test_flip_flag_uses_original_structural_flip_not_role_history(self):
        frame = add_feature_buckets(self.feature_frame())
        self.assertEqual(frame["f_flip_flag"].tolist(), ["yes", "no", "yes"])
        self.assertEqual(frame["f_history_flipped"].tolist(), ["no", "yes", "no"])
        conditions = enumerate_conditions(frame, minimum_candidates=2)
        condition = next(
            item for item in conditions if item.condition_id == "f_flip_flag=yes"
        )
        self.assertEqual(condition_mask(frame, condition).tolist(), [True, False, True])

    def test_detailed_fc2_shape_buckets_are_replayable(self):
        frame = add_feature_buckets(self.feature_frame())
        self.assertEqual(
            frame["f_fc2_second_wick_a"].tolist(),
            ["0p25to0p49", "lt0p10", "0p25to0p49"],
        )
        self.assertEqual(
            frame["f_fc2_second_body_ratio"].tolist(),
            ["0p40to0p54", "ge1p00", "0p55to0p64"],
        )
        self.assertEqual(
            frame["f_fc2_relative_candle_sequence"].tolist(),
            ["WITH_AGAINST", "WITH_AGAINST", "WITH_AGAINST"],
        )
        conditions = enumerate_conditions(frame, minimum_candidates=2)
        condition = next(
            item
            for item in conditions
            if item.condition_id
            == "f_fc2_relative_candle_sequence=WITH_AGAINST"
        )
        self.assertEqual(condition_mask(frame, condition).tolist(), [True, True, True])

    def test_unfilled_candidate_is_replaced_by_next_event(self):
        frame = pd.DataFrame(
            {
                "event_id": ["a", "b"],
                "decision_time": pd.to_datetime(["2025-01-06 09:00", "2025-01-06 09:05"]),
                "next_count2_time": pd.to_datetime(["2025-01-06 09:05", "2025-01-06 09:20"]),
                "distance_rank": [1, 1],
                "distance_pips": [2.0, 2.0],
                "line_price": [150.0, 150.1],
                "order_filled": [False, True],
                "replaced_before_fill": [True, False],
                "order_deadline": pd.to_datetime(["2025-01-06 09:05", "2025-01-06 09:20"]),
                "path_status": ["replaced_before_fill", "trade"],
                "fill_time": pd.to_datetime([None, "2025-01-06 09:07"]),
                "exit_time": pd.to_datetime([None, "2025-01-06 09:10"]),
                "trade_result_pips": [np.nan, 2.0],
                "result_yen": [np.nan, 50.0],
            }
        )
        trades, summary = replay_condition(frame, PolicyCondition("ALL", "all"))
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades.iloc[0]["event_id"], "b")
        self.assertEqual(summary["replaced_before_fill_count"], 1)
        self.assertEqual(summary["candidate_count"], 2)
        self.assertEqual(summary["order_fill_count"], 1)


class Top15TierPolicyTest(unittest.TestCase):
    def test_default_tiers_use_tp_1p7_and_rr_1p5(self):
        configs = default_tier_execution_configs()
        self.assertEqual(
            [(item.tier, item.first_rank, item.last_rank) for item in configs],
            [("HIGH", 1, 5), ("MIDDLE", 6, 10), ("LOW", 11, 15)],
        )
        for config in configs:
            self.assertAlmostEqual(config.tp_a, 1.7)
            self.assertAlmostEqual(config.rr, 1.5)
            self.assertAlmostEqual(config.trade_combo.lc_a, 1.7 / 1.5)
            self.assertAlmostEqual(config.trade_combo.configured_rr, 1.5)
            self.assertEqual(TierExecutionConfig.from_dict(config.to_dict()), config)

    def test_minimum_width_floor_scales_both_widths_before_tick_rounding(self):
        combo = TradeCombo.from_tp_rr(1.7, 1.5)
        tp_pips, lc_pips = effective_trade_widths(
            0.5,
            combo,
            gene.currency_pair("USD_JPY"),
            minimum_pips=1.6,
        )
        self.assertGreaterEqual(tp_pips, 1.6)
        self.assertGreaterEqual(lc_pips, 1.6)
        self.assertAlmostEqual(tp_pips / lc_pips, 1.5)

    def test_effective_widths_are_executable_price_increments(self):
        combo = TradeCombo.from_tp_rr(1.7, 1.5)
        pair = gene.currency_pair("USD_JPY")
        tp_pips, lc_pips = effective_trade_widths(
            52.0 / 17.0,
            combo,
            pair,
            minimum_pips=1.6,
        )
        tick_pips = (10.0 ** -pair.round_keta) / pair.pip_value
        self.assertAlmostEqual(tp_pips / tick_pips, round(tp_pips / tick_pips))
        self.assertAlmostEqual(lc_pips / tick_pips, round(lc_pips / tick_pips))
        self.assertAlmostEqual(tp_pips, 5.2)
        self.assertAlmostEqual(lc_pips, 3.5)
        self.assertAlmostEqual(tp_pips / lc_pips, 1.5, delta=0.02)

    def test_raw_top15_excludes_all_without_profit_or_trade_gates(self):
        rows = [
            {
                "condition_id": "ALL",
                "condition_label": "all",
                "condition_json": json.dumps(
                    PolicyCondition("ALL", "all").to_dict()
                ),
                "sum_yen": 99999.0,
                "positive_month_rate": 1.0,
                "profit_factor_yen": 99.0,
                "sum_pips": 999.0,
                "completed_trade_count": 999,
            }
        ]
        for number in range(1, 17):
            condition = PolicyCondition(
                f"C{number:02d}",
                f"condition {number:02d}",
                (("f_test", f"v{number:02d}"),),
            )
            rows.append(
                {
                    "condition_id": condition.condition_id,
                    "condition_label": condition.label,
                    "condition_json": json.dumps(condition.to_dict()),
                    "sum_yen": float(17 - number),
                    "positive_month_rate": 0.0,
                    "profit_factor_yen": 0.2,
                    "sum_pips": -float(number),
                    "completed_trade_count": 1,
                }
            )
        selected = select_top_ranked_conditions(
            pd.DataFrame(rows), default_tier_execution_configs(), limit=15
        )
        self.assertEqual(len(selected), 15)
        self.assertEqual(
            [item.condition.condition_id for item in selected],
            [f"C{number:02d}" for number in range(1, 16)],
        )
        self.assertEqual(
            [item.tier for item in selected],
            ["HIGH"] * 5 + ["MIDDLE"] * 5 + ["LOW"] * 5,
        )
        restored = RankedPolicyCondition.from_dict(
            {**selected[0].to_dict(), "train_lifecycle_performance": {"sum_yen": 1}}
        )
        self.assertEqual(restored, selected[0])

    def test_or_policy_deduplicates_event_and_prefers_tier_then_distance(self):
        configs = (
            TierExecutionConfig("HIGH", 1, 1, 1.7, 1.5),
            TierExecutionConfig("MIDDLE", 2, 2, 1.7, 1.5),
            TierExecutionConfig("LOW", 3, 3, 1.7, 1.5),
        )
        ranked = (
            RankedPolicyCondition(
                1, "HIGH", PolicyCondition("high", "high", (("f_high", "yes"),))
            ),
            RankedPolicyCondition(
                2,
                "MIDDLE",
                PolicyCondition("middle", "middle", (("f_middle", "yes"),)),
            ),
            RankedPolicyCondition(
                3, "LOW", PolicyCondition("low", "low", (("f_low", "yes"),))
            ),
        )
        frame = pd.DataFrame(
            {
                "event_id": ["e1", "e1", "e2", "e2", "e3", "e4"],
                "decision_time": pd.to_datetime(
                    [
                        "2025-01-06 09:00",
                        "2025-01-06 09:00",
                        "2025-01-06 09:05",
                        "2025-01-06 09:05",
                        "2025-01-06 09:10",
                        "2025-01-06 09:15",
                    ]
                ),
                "distance_rank": [4, 1, 3, 1, 1, 1],
                "distance_pips": [8.0, 1.0, 6.0, 2.0, 1.0, 1.0],
                "line_price": [150.4, 150.1, 150.3, 150.2, 150.1, 150.1],
                "f_high": ["yes", "no", "yes", "yes", "yes", "no"],
                "f_middle": ["no", "no", "no", "no", "yes", "no"],
                "f_low": ["no", "yes", "no", "no", "no", "no"],
            }
        )
        selected = select_top_condition_policy_candidates(frame, ranked, configs)
        self.assertEqual(selected["event_id"].tolist(), ["e1", "e2", "e3"])
        self.assertEqual(selected["line_price"].tolist(), [150.4, 150.2, 150.1])
        self.assertEqual(selected["signal_tier"].tolist(), ["HIGH"] * 3)
        overlap = selected[selected["event_id"].eq("e3")].iloc[0]
        self.assertEqual(overlap["matched_condition_count"], 2)
        self.assertEqual(json.loads(overlap["matched_condition_ids"]), ["high", "middle"])
        self.assertEqual(json.loads(overlap["matched_condition_ranks"]), [1, 2])
        self.assertEqual(overlap["highest_matched_rank"], 1)
        self.assertAlmostEqual(overlap["tier_tp_a"], 1.7)
        self.assertAlmostEqual(overlap["tier_rr"], 1.5)
        self.assertAlmostEqual(overlap["tier_lc_a"], 1.7 / 1.5)
        empty = select_top_condition_policy_candidates(
            frame[frame["event_id"].eq("e4")], ranked, configs
        )
        self.assertTrue(empty.empty)
        for column in (
            "tier_tp_a",
            "tier_rr",
            "tier_lc_a",
            "policy_line_selection",
        ):
            self.assertIn(column, empty.columns)

    def test_each_tier_rr_is_independently_editable(self):
        configs = (
            TierExecutionConfig("HIGH", 1, 1, 1.7, 1.5),
            TierExecutionConfig("MIDDLE", 2, 2, 1.7, 1.3),
            TierExecutionConfig("LOW", 3, 3, 1.7, 1.1),
        )
        ranked = (
            RankedPolicyCondition(
                1, "HIGH", PolicyCondition("high", "high", (("f_tier", "h"),))
            ),
            RankedPolicyCondition(
                2,
                "MIDDLE",
                PolicyCondition("middle", "middle", (("f_tier", "m"),)),
            ),
            RankedPolicyCondition(
                3, "LOW", PolicyCondition("low", "low", (("f_tier", "l"),))
            ),
        )
        frame = pd.DataFrame(
            {
                "event_id": ["h", "m", "l"],
                "decision_time": pd.to_datetime(
                    ["2025-01-06 09:00", "2025-01-06 09:05", "2025-01-06 09:10"]
                ),
                "distance_rank": [1, 1, 1],
                "distance_pips": [1.0, 1.0, 1.0],
                "line_price": [150.0, 150.1, 150.2],
                "f_tier": ["h", "m", "l"],
            }
        )
        selected = select_top_condition_policy_candidates(frame, ranked, configs)
        self.assertEqual(selected["signal_tier"].tolist(), ["HIGH", "MIDDLE", "LOW"])
        self.assertEqual(selected["tier_rr"].tolist(), [1.5, 1.3, 1.1])
        self.assertAlmostEqual(selected.iloc[0]["tier_lc_a"], 1.7 / 1.5)
        self.assertAlmostEqual(selected.iloc[1]["tier_lc_a"], 1.7 / 1.3)
        self.assertAlmostEqual(selected.iloc[2]["tier_lc_a"], 1.7 / 1.1)


class LauncherTest(unittest.TestCase):
    def test_default_periods_are_two_year_analysis_and_one_year_replay(self):
        args = parse_args([])
        self.assertEqual(args.train_start, dt.datetime(2023, 7, 30))
        self.assertEqual(args.train_end, dt.datetime(2025, 7, 30))
        self.assertEqual(args.oos_start, dt.datetime(2025, 7, 30))
        self.assertEqual(args.oos_end, dt.datetime(2026, 7, 30))

    def test_progress_lock_does_not_abort_analysis(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "progress.json"
            with patch(
                "count2_flip_workflow.atomic_json",
                side_effect=PermissionError("OneDrive lock"),
            ):
                payload = write_progress(
                    path,
                    pair="USD_JPY",
                    status="running",
                    phase="test",
                    current_row=5,
                    total_rows=10,
                    started=0.0,
                )
        self.assertEqual(payload["current_row"], 5)
        self.assertEqual(payload["total_rows"], 10)


if __name__ == "__main__":
    unittest.main()
