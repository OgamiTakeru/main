# 最新更新日時: 2026-08-25 14:59 JST
import datetime as dt
import json
import tempfile
import time
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
    FlipWatchEntryConfig,
    LineWickLcConfig,
    PolicyCondition,
    RankedPolicyCondition,
    TierExecutionConfig,
    TimedHalfLcConfig,
    TradeCombo,
    _is_expected_market_closed_gap,
    add_feature_buckets,
    classify_flip_watch_entry,
    condition_mask,
    default_timed_half_lc_configs,
    default_line_wick_lc_configs,
    default_tier_execution_configs,
    effective_trade_widths,
    enumerate_conditions,
    validate_causal_candidate,
)
from count2_flip_pipeline import parse_args
from count2_flip_workflow import (
    atomic_json,
    choose_timed_half_lc_policy,
    choose_line_wick_lc_policy,
    inspect_line_wick_lc_grid_paths,
    inspect_timed_half_lc_grid_paths,
    line_holding_early_path_dataset,
    load_candidates,
    range_filter_mask,
    replay_condition,
    scan_global_grid,
    scan_timed_half_lc_grid,
    scan_line_wick_lc_grid,
    select_timed_half_lc_policies,
    select_top_condition_policy_candidates,
    select_top_ranked_conditions,
    stretch_profit_lock_inspector,
    stretch_profit_lock_tier_configs,
    target_distance_filter_mask,
    write_progress,
)
from count2_flip_workflow import SOURCE_COLUMNS


def make_inspector(
    rows,
    pair_name="USD_JPY",
    end="2025-01-06 01:00:00",
    *,
    profit_lock_enabled=False,
):
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
        profit_lock_enabled=profit_lock_enabled,
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
    def test_watch_classifier_has_stable_boundary_names_and_directions(self):
        config = FlipWatchEntryConfig()
        holding = classify_flip_watch_entry(0.099, 1, config)
        near = classify_flip_watch_entry(0.10, 1, config)
        breakout = classify_flip_watch_entry(1.001, -1, config)
        self.assertEqual(holding["watch_order_name"], "FlipPredict_LineHolding")
        self.assertEqual(holding["order_direction"], -1)
        self.assertEqual(
            near["watch_order_name"], "FlipPredict_NearLineConsolidation"
        )
        self.assertEqual(near["order_direction"], 1)
        self.assertEqual(breakout["watch_order_name"], "FlipPredict_Breakout")
        self.assertEqual(breakout["order_direction"], -1)

    def test_watch_line_holding_enters_reversal_market_after_completed_minute(self):
        rows = base_s5_rows()
        rows[20].update(open=149.995, close=149.999, high=150.005, low=149.994)
        for index in range(21, 34):
            rows[index].update(
                open=149.999, close=149.999, high=150.001, low=149.997
            )
        inspector = make_inspector(rows)
        result = inspector.inspect(
            decision_time=pd.Timestamp("2025-01-06 00:00:00"),
            line_price=150.0,
            order_direction=-1,
            average_range_pips=2.0,
            path_config=FlipPathConfig(20),
            trade_combos=(TradeCombo(1.5, 1.0),),
            watch_entry_config=FlipWatchEntryConfig(),
        )
        self.assertEqual(result["watch_order_name"], "FlipPredict_LineHolding")
        self.assertEqual(result["watch_entry_mode"], "MARKET")
        self.assertEqual(result["order_direction"], -1)
        self.assertEqual(
            result["watch_line_touch_known_time"],
            pd.Timestamp("2025-01-06 00:01:45"),
        )
        self.assertEqual(
            result["watch_observation_known_time"],
            pd.Timestamp("2025-01-06 00:02:45"),
        )
        self.assertEqual(result["fill_time"], pd.Timestamp("2025-01-06 00:02:45"))
        self.assertTrue(result["fill_at_bar_open"])
        outcome = next(iter(result["outcomes"].values()))
        self.assertEqual(
            outcome["early_m1_checkpoint_time"],
            pd.Timestamp("2025-01-06 00:03:45"),
        )
        self.assertTrue(outcome["early_m1_checkpoint_evaluable"])
        self.assertTrue(outcome["early_m1_position_open"])
        self.assertTrue(np.isfinite(outcome["early_m1_cumulative_mfe_pips"]))

        source = {
            "event_id": "line-holding-1",
            "pair": "USD_JPY",
            "decision_time": pd.Timestamp("2025-01-06 00:00:00"),
            "recent_m5_avg_range_pips": 2.0,
            **{key: value for key, value in result.items() if key != "outcomes"},
            **outcome,
        }
        early = line_holding_early_path_dataset(
            pd.DataFrame((source,)),
            phase="analysis_two_years",
        )
        self.assertEqual(early["elapsed_minute"].tolist(), [1, 2, 3, 4, 5])
        self.assertTrue(
            early["snapshot_known_time"].eq(early["checkpoint_time"]).all()
        )
        self.assertTrue(early["snapshot_fields_are_causal"].all())
        self.assertTrue(early["final_fields_are_labels_only"].all())
        self.assertFalse(
            early["final_exit_s5_opposite_extreme_censored"].any()
        )
        incomplete = pd.DataFrame((source,)).drop(
            columns="early_m1_current_close_pips"
        )
        with self.assertRaisesRegex(
            ValueError, "early-path source columns are incomplete"
        ):
            line_holding_early_path_dataset(
                incomplete,
                phase="analysis_two_years",
            )

    def test_early_path_does_not_use_prices_after_lc(self):
        rows = base_s5_rows()
        rows[20].update(open=149.995, close=149.999, high=150.005, low=149.994)
        for index in range(21, 34):
            rows[index].update(
                open=149.999, close=149.999, high=150.001, low=149.997
            )
        rows[34].update(
            open=149.999, close=150.030, high=150.050, low=149.900
        )
        inspector = make_inspector(rows)
        result = inspector.inspect(
            decision_time=pd.Timestamp("2025-01-06 00:00:00"),
            line_price=150.0,
            order_direction=-1,
            average_range_pips=2.0,
            path_config=FlipPathConfig(20),
            trade_combos=(TradeCombo(1.5, 1.0),),
            watch_entry_config=FlipWatchEntryConfig(),
        )
        outcome = next(iter(result["outcomes"].values()))
        self.assertIn(outcome["trade_result"], {"lc", "both_same_s5_lc_assumed"})
        self.assertTrue(outcome["exit_s5_opposite_extreme_censored"])
        self.assertLess(outcome["max_favorable_pips"], 0.0)
        for minute in range(1, 6):
            self.assertFalse(outcome[f"early_m{minute}_position_open"])
            self.assertFalse(outcome[f"early_m{minute}_checkpoint_evaluable"])
            self.assertTrue(
                pd.isna(outcome[f"early_m{minute}_current_close_pips"])
            )

    def test_watch_near_line_places_breakout_direction_retest_limit(self):
        rows = base_s5_rows()
        rows[20].update(open=149.995, close=150.002, high=150.006, low=149.994)
        for index in range(21, 40):
            rows[index].update(
                open=150.010, close=150.010, high=150.012, low=150.006
            )
        rows[40].update(
            open=150.006, close=150.004, high=150.008, low=149.995
        )
        inspector = make_inspector(rows)
        result = inspector.inspect(
            decision_time=pd.Timestamp("2025-01-06 00:00:00"),
            line_price=150.0,
            order_direction=-1,
            average_range_pips=2.0,
            path_config=FlipPathConfig(20),
            trade_combos=(TradeCombo(1.5, 1.0),),
            watch_entry_config=FlipWatchEntryConfig(),
        )
        self.assertEqual(
            result["watch_order_name"],
            "FlipPredict_NearLineConsolidation",
        )
        self.assertEqual(result["watch_entry_mode"], "LIMIT_RETEST")
        self.assertEqual(result["order_direction"], 1)
        self.assertEqual(result["fill_time"], pd.Timestamp("2025-01-06 00:03:20"))

    def test_watch_near_line_is_direction_symmetric_for_down_break(self):
        rows = base_s5_rows(price=150.02)
        rows[20].update(open=150.005, close=149.998, high=150.006, low=149.994)
        for index in range(21, 40):
            rows[index].update(
                open=149.990, close=149.990, high=149.994, low=149.988
            )
        rows[40].update(
            open=149.994, close=149.996, high=150.005, low=149.992
        )
        inspector = make_inspector(rows)
        result = inspector.inspect(
            decision_time=pd.Timestamp("2025-01-06 00:00:00"),
            line_price=150.0,
            order_direction=1,
            average_range_pips=2.0,
            path_config=FlipPathConfig(20),
            trade_combos=(TradeCombo(1.5, 1.0),),
            watch_entry_config=FlipWatchEntryConfig(),
        )
        self.assertEqual(
            result["watch_order_name"],
            "FlipPredict_NearLineConsolidation",
        )
        self.assertEqual(result["order_direction"], -1)
        self.assertEqual(result["fill_time"], pd.Timestamp("2025-01-06 00:03:20"))

    def test_watch_breakout_requires_continuation_stop_after_observation(self):
        rows = base_s5_rows()
        rows[20].update(open=149.995, close=150.004, high=150.006, low=149.994)
        for index in range(21, 40):
            rows[index].update(
                open=150.030, close=150.030, high=150.031, low=150.027
            )
        rows[40].update(
            open=150.030, close=150.034, high=150.033, low=150.028
        )
        inspector = make_inspector(rows)
        result = inspector.inspect(
            decision_time=pd.Timestamp("2025-01-06 00:00:00"),
            line_price=150.0,
            order_direction=-1,
            average_range_pips=2.0,
            path_config=FlipPathConfig(20),
            trade_combos=(TradeCombo(1.5, 1.0),),
            watch_entry_config=FlipWatchEntryConfig(),
        )
        self.assertEqual(result["watch_order_name"], "FlipPredict_Breakout")
        self.assertEqual(result["watch_entry_mode"], "STOP_CONTINUATION")
        self.assertEqual(result["order_direction"], 1)
        self.assertEqual(result["fill_time"], pd.Timestamp("2025-01-06 00:03:20"))
        self.assertAlmostEqual(result["watch_entry_trigger_price"], 150.036)

    def test_watch_stop_fill_bar_uses_only_post_trigger_provable_prices(self):
        cases = (
            {
                "pair_name": "USD_JPY",
                "price": 149.98,
                "signal_direction": -1,
                "touch": dict(
                    open=149.995, close=150.004, high=150.006, low=149.994
                ),
                "observation": dict(
                    open=150.030, close=150.030, high=150.031, low=150.027
                ),
                "fill": dict(
                    open=150.030, close=150.050, high=150.071, low=149.980
                ),
                "expected_direction": 1,
            },
            {
                "pair_name": "USD_JPY",
                "price": 150.02,
                "signal_direction": 1,
                "touch": dict(
                    open=150.005, close=149.996, high=150.006, low=149.994
                ),
                "observation": dict(
                    open=149.970, close=149.970, high=149.973, low=149.969
                ),
                "fill": dict(
                    open=149.970, close=149.950, high=150.020, low=149.929
                ),
                "expected_direction": -1,
            },
        )
        for case in cases:
            with self.subTest(direction=case["expected_direction"]):
                rows = base_s5_rows(price=case["price"])
                rows[20].update(**case["touch"])
                for index in range(21, 40):
                    rows[index].update(**case["observation"])
                rows[40].update(**case["fill"])
                inspector = make_inspector(rows, pair_name=case["pair_name"])
                result = inspector.inspect(
                    decision_time=pd.Timestamp("2025-01-06 00:00:00"),
                    line_price=150.0,
                    order_direction=case["signal_direction"],
                    average_range_pips=2.0,
                    path_config=FlipPathConfig(20),
                    trade_combos=(TradeCombo(1.5, 1.0),),
                    watch_entry_config=FlipWatchEntryConfig(),
                )
                self.assertEqual(result["order_direction"], case["expected_direction"])
                self.assertFalse(result["fill_at_bar_open"])
                self.assertTrue(result["watch_stop_fill_bar_adverse_censored"])
                outcome = result["outcomes"]["tp1p5A_lc1A"]
                self.assertEqual(outcome["trade_result"], "tp")

    def test_watch_pending_order_gets_full_wait_after_observation(self):
        rows = base_s5_rows(periods=900)
        rows[228].update(
            open=149.995, close=150.002, high=150.005, low=149.994
        )
        for index in range(229, 241):
            rows[index].update(
                open=150.010, close=150.010, high=150.012, low=150.006
            )
        for index in range(241, len(rows)):
            rows[index].update(
                open=150.020, close=150.020, high=150.021, low=150.019
            )
        inspector = make_inspector(rows)
        result = inspector.inspect(
            decision_time=pd.Timestamp("2025-01-06 00:00:00"),
            line_price=150.0,
            order_direction=-1,
            average_range_pips=2.0,
            path_config=FlipPathConfig(20),
            trade_combos=(TradeCombo(1.5, 1.0),),
            watch_entry_config=FlipWatchEntryConfig(),
        )
        self.assertEqual(result["path_status"], "watch_retest_no_fill")
        self.assertEqual(
            result["watch_initial_touch_deadline"],
            pd.Timestamp("2025-01-06 00:20:00"),
        )
        self.assertEqual(
            result["watch_observation_known_time"],
            pd.Timestamp("2025-01-06 00:20:05"),
        )
        self.assertEqual(
            result["order_deadline"],
            pd.Timestamp("2025-01-06 00:40:05"),
        )

    def test_watch_line_holding_skips_late_market_chase(self):
        rows = base_s5_rows()
        rows[20].update(open=149.995, close=149.998, high=150.005, low=149.994)
        for index in range(21, 34):
            rows[index].update(
                open=149.990, close=149.990, high=149.992, low=149.988
            )
        inspector = make_inspector(rows)
        result = inspector.inspect(
            decision_time=pd.Timestamp("2025-01-06 00:00:00"),
            line_price=150.0,
            order_direction=-1,
            average_range_pips=2.0,
            path_config=FlipPathConfig(20),
            trade_combos=(TradeCombo(1.5, 1.0),),
            watch_entry_config=FlipWatchEntryConfig(),
        )
        self.assertEqual(result["path_status"], "watch_line_holding_chase_filtered")
        self.assertTrue(result["watch_chase_filtered"])
        self.assertFalse(result["order_filled"])

    def test_watch_line_holding_rechecks_the_actual_market_quote(self):
        rows = base_s5_rows()
        rows[20].update(open=149.995, close=149.999, high=150.005, low=149.994)
        for index in range(21, 33):
            rows[index].update(
                open=149.999, close=149.999, high=150.001, low=149.997
            )
        rows[33].update(
            open=149.990, close=149.990, high=149.992, low=149.988
        )
        result = make_inspector(rows).inspect(
            decision_time=pd.Timestamp("2025-01-06 00:00:00"),
            line_price=150.0,
            order_direction=-1,
            average_range_pips=2.0,
            path_config=FlipPathConfig(20),
            trade_combos=(TradeCombo(1.5, 1.0),),
            watch_entry_config=FlipWatchEntryConfig(),
        )
        self.assertEqual(
            result["path_status"],
            "watch_line_holding_entry_quote_filtered",
        )
        self.assertTrue(result["watch_entry_gap_filtered"])
        self.assertFalse(result["order_filled"])
        self.assertEqual(
            result["watch_order_release_time"],
            pd.Timestamp("2025-01-06 00:02:45"),
        )

    def test_watch_line_holding_chase_limit_includes_spread(self):
        rows = base_s5_rows()
        rows[20].update(open=149.995, close=149.999, high=150.005, low=149.994)
        for index in range(21, 33):
            rows[index].update(
                open=149.999, close=149.999, high=150.001, low=149.997
            )
        # Mid open is -0.2A, but the executable SELL bid is -0.4A after
        # spread and must not pass the -0.3A chase limit.
        rows[33].update(
            open=149.996, close=149.996, high=149.998, low=149.994
        )
        result = make_inspector(rows).inspect(
            decision_time=pd.Timestamp("2025-01-06 00:00:00"),
            line_price=150.0,
            order_direction=-1,
            average_range_pips=2.0,
            path_config=FlipPathConfig(20),
            trade_combos=(TradeCombo(1.5, 1.0),),
            watch_entry_config=FlipWatchEntryConfig(),
        )
        self.assertEqual(
            result["path_status"],
            "watch_line_holding_entry_quote_filtered",
        )
        self.assertFalse(result["order_filled"])

    def test_watch_pending_entry_rejects_large_open_gap(self):
        rows = base_s5_rows()
        rows[20].update(open=149.995, close=150.002, high=150.006, low=149.994)
        for index in range(21, 33):
            rows[index].update(
                open=150.010, close=150.010, high=150.012, low=150.006
            )
        rows[33].update(
            open=149.990, close=149.990, high=150.002, low=149.988
        )
        result = make_inspector(rows).inspect(
            decision_time=pd.Timestamp("2025-01-06 00:00:00"),
            line_price=150.0,
            order_direction=-1,
            average_range_pips=2.0,
            path_config=FlipPathConfig(20),
            trade_combos=(TradeCombo(1.5, 1.0),),
            watch_entry_config=FlipWatchEntryConfig(),
        )
        self.assertEqual(result["watch_entry_mode"], "LIMIT_RETEST")
        self.assertEqual(result["path_status"], "watch_entry_gap_filtered")
        self.assertGreater(result["watch_entry_gap_from_trigger_a"], 0.10)
        self.assertFalse(result["order_filled"])

    def test_watch_rejects_gap_between_touch_and_observation(self):
        rows = base_s5_rows()
        rows[20].update(open=149.995, close=149.999, high=150.005, low=149.994)
        del rows[21]
        result = make_inspector(rows).inspect(
            decision_time=pd.Timestamp("2025-01-06 00:00:00"),
            line_price=150.0,
            order_direction=-1,
            average_range_pips=2.0,
            path_config=FlipPathConfig(20),
            trade_combos=(TradeCombo(1.5, 1.0),),
            watch_entry_config=FlipWatchEntryConfig(),
        )
        self.assertEqual(result["path_status"], "incomplete_watch_observation")
        self.assertFalse(result["order_filled"])

    def test_watch_never_observes_or_fills_across_period_end(self):
        rows = base_s5_rows()
        rows[23].update(open=149.995, close=149.999, high=150.005, low=149.994)
        inspector = make_inspector(rows, end="2025-01-06 00:02:00")
        result = inspector.inspect(
            decision_time=pd.Timestamp("2025-01-06 00:00:00"),
            line_price=150.0,
            order_direction=-1,
            average_range_pips=2.0,
            path_config=FlipPathConfig(20),
            trade_combos=(TradeCombo(1.5, 1.0),),
            watch_entry_config=FlipWatchEntryConfig(),
        )
        self.assertEqual(result["path_status"], "incomplete_watch_observation")
        self.assertFalse(result["order_filled"])
        self.assertTrue(pd.isna(result["watch_observation_known_time"]))

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
            path_config=FlipPathConfig(
                20, replace_unfilled_on_next_count2=True
            ),
            trade_combos=(TradeCombo(1.5, 1.0),),
            next_count2_time=pd.Timestamp("2025-01-06 00:05:00"),
        )
        self.assertEqual(result["path_status"], "replaced_before_fill")
        self.assertTrue(result["replaced_before_fill"])
        self.assertEqual(result["order_deadline"], pd.Timestamp("2025-01-06 00:05:00"))

    def test_next_foot_count2_does_not_replace_when_flag_is_off(self):
        inspector = make_inspector(base_s5_rows())
        result = inspector.inspect(
            decision_time=pd.Timestamp("2025-01-06 00:00:00"),
            line_price=150.0,
            order_direction=-1,
            average_range_pips=2.0,
            path_config=FlipPathConfig(
                20, replace_unfilled_on_next_count2=False
            ),
            trade_combos=(TradeCombo(1.5, 1.0),),
            next_count2_time=pd.Timestamp("2025-01-06 00:05:00"),
        )
        self.assertEqual(result["path_status"], "no_fill")
        self.assertFalse(result["replaced_before_fill"])
        self.assertEqual(
            result["order_deadline"], pd.Timestamp("2025-01-06 00:20:00")
        )

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

    def test_profit_lock_activates_on_s5_after_half_tp_trigger(self):
        rows = base_s5_rows(price=150.02)
        rows[20].update(open=150.01, close=150.005, high=150.015, low=149.995)
        rows[21].update(open=150.02, close=150.05, high=150.064, low=150.02)
        rows[22].update(open=150.03, close=150.015, high=150.04, low=150.01)
        inspector = make_inspector(rows, profit_lock_enabled=True)
        result = inspector.inspect(
            decision_time=pd.Timestamp("2025-01-06 00:00:00"),
            line_price=150.0,
            order_direction=1,
            average_range_pips=10.0,
            path_config=FlipPathConfig(20),
            trade_combos=(TradeCombo(1.0, 1.0),),
        )
        outcome = result["outcomes"]["tp1A_lc1A"]
        self.assertTrue(outcome["profit_lock_enabled"])
        self.assertAlmostEqual(outcome["profit_lock_trigger_pips"], 5.0)
        self.assertTrue(outcome["profit_lock_trigger_reached"])
        self.assertTrue(outcome["profit_lock_activated"])
        self.assertEqual(
            outcome["profit_lock_active_from"],
            pd.Timestamp("2025-01-06 00:01:50"),
        )
        self.assertEqual(outcome["trade_result"], "profit_lock")
        self.assertAlmostEqual(outcome["trade_result_pips"], 1.0)

    def test_profit_lock_is_disabled_by_default(self):
        rows = base_s5_rows(price=150.02)
        rows[20].update(open=150.01, close=150.005, high=150.015, low=149.995)
        rows[21].update(open=150.02, close=150.05, high=150.064, low=150.02)
        rows[22].update(open=150.03, close=150.015, high=150.04, low=150.01)
        inspector = make_inspector(rows)
        result = inspector.inspect(
            decision_time=pd.Timestamp("2025-01-06 00:00:00"),
            line_price=150.0,
            order_direction=1,
            average_range_pips=10.0,
            path_config=FlipPathConfig(20),
            trade_combos=(TradeCombo(1.0, 1.0),),
        )
        outcome = result["outcomes"]["tp1A_lc1A"]
        self.assertFalse(outcome["profit_lock_enabled"])
        self.assertFalse(outcome["profit_lock_trigger_reached"])
        self.assertNotEqual(outcome["trade_result"], "profit_lock")

    def test_stretch_profit_lock_uses_frozen_tp_as_one_b(self):
        rows = base_s5_rows(price=150.02)
        rows[20].update(open=150.01, close=150.005, high=150.015, low=149.995)
        rows[21].update(open=150.10, close=150.12, high=150.125, low=150.10)
        rows[22].update(open=150.11, close=150.10, high=150.115, low=150.095)
        base_inspector = make_inspector(rows)
        inspector = stretch_profit_lock_inspector(base_inspector)
        base_config = TierExecutionConfig("HIGH", 1, 5, 1.0, 1.0, 0.0)
        stretch_config = stretch_profit_lock_tier_configs((base_config,))[0]
        self.assertAlmostEqual(stretch_config.tp_a, 2.0)
        self.assertAlmostEqual(stretch_config.trade_combo.lc_a, 1.0)
        result = inspector.inspect(
            decision_time=pd.Timestamp("2025-01-06 00:00:00"),
            line_price=150.0,
            order_direction=1,
            average_range_pips=10.0,
            path_config=FlipPathConfig(20),
            trade_combos=(stretch_config.trade_combo,),
        )
        outcome = result["outcomes"][stretch_config.trade_combo.combo_id]
        self.assertAlmostEqual(outcome["tp_pips"], 20.0)
        self.assertAlmostEqual(outcome["lc_pips"], 10.0)
        self.assertAlmostEqual(outcome["profit_lock_trigger_pips"], 12.0)
        self.assertAlmostEqual(
            outcome["profit_lock_effective_result_pips"], 10.0
        )
        self.assertEqual(outcome["trade_result"], "profit_lock")
        self.assertAlmostEqual(outcome["trade_result_pips"], 10.0)

    def test_timed_half_lc_activates_at_exact_checkpoint_and_uses_open(self):
        rows = base_s5_rows(price=150.01)
        rows[12].update(
            open=150.03,
            close=150.03,
            high=150.031,
            low=150.029,
        )
        inspector = make_inspector(rows)
        combo = TradeCombo(1.0, 1.0)
        timer = TimedHalfLcConfig(1)
        result = inspector.inspect(
            decision_time=pd.Timestamp("2025-01-06 00:00:00"),
            line_price=150.0,
            order_direction=-1,
            average_range_pips=4.0,
            path_config=FlipPathConfig(20),
            trade_combos=(combo,),
            timed_half_lc_configs=(TimedHalfLcConfig(None), timer),
        )
        baseline = result["outcomes"][combo.combo_id]
        timed = result["outcomes"][
            f"{combo.combo_id}__{timer.config_id}"
        ]
        self.assertEqual(baseline["timed_half_lc_config_id"], "baseline")
        self.assertEqual(
            timed["timed_half_lc_check_time"],
            pd.Timestamp("2025-01-06 00:01:00"),
        )
        self.assertTrue(timed["timed_half_lc_activated"])
        self.assertTrue(timed["timed_half_lc_activation_already_breached"])
        self.assertEqual(timed["trade_result"], "timed_half_lc")
        self.assertEqual(
            timed["timed_half_lc_exit_mode"], "activation_or_gap_open"
        )
        self.assertAlmostEqual(timed["trade_result_pips"], -3.4)

    def test_prior_half_tp_does_not_block_checkpoint_loss_cut(self):
        rows = base_s5_rows(price=150.01)
        rows[6].update(
            open=149.98,
            close=149.98,
            high=149.99,
            low=149.97,
        )
        rows[12].update(
            open=150.03,
            close=150.03,
            high=150.031,
            low=150.029,
        )
        inspector = make_inspector(rows)
        combo = TradeCombo(1.0, 1.0)
        timer = TimedHalfLcConfig(1)
        result = inspector.inspect(
            decision_time=pd.Timestamp("2025-01-06 00:00:00"),
            line_price=150.0,
            order_direction=-1,
            average_range_pips=4.0,
            path_config=FlipPathConfig(20),
            trade_combos=(combo,),
            timed_half_lc_configs=(timer,),
        )
        timed = result["outcomes"][
            f"{combo.combo_id}__{timer.config_id}"
        ]
        self.assertTrue(timed["half_tp_reached_before_timed_checkpoint"])
        self.assertTrue(timed["timed_half_lc_activation_already_breached"])
        self.assertTrue(timed["timed_half_lc_activated"])
        self.assertEqual(timed["trade_result"], "timed_half_lc")

    def test_checkpoint_loss_above_half_lc_does_not_activate(self):
        inspector = make_inspector(base_s5_rows(price=150.01))
        combo = TradeCombo(1.0, 1.0)
        timer = TimedHalfLcConfig(1)
        result = inspector.inspect(
            decision_time=pd.Timestamp("2025-01-06 00:00:00"),
            line_price=150.0,
            order_direction=-1,
            average_range_pips=4.0,
            path_config=FlipPathConfig(20),
            trade_combos=(combo,),
            timed_half_lc_configs=(timer,),
        )
        timed = result["outcomes"][
            f"{combo.combo_id}__{timer.config_id}"
        ]
        self.assertTrue(timed["timed_half_lc_position_open_at_checkpoint"])
        self.assertAlmostEqual(
            timed["timed_half_lc_activation_open_pips"], -1.4
        )
        self.assertFalse(timed["timed_half_lc_activation_already_breached"])
        self.assertFalse(timed["timed_half_lc_activated"])
        self.assertNotEqual(timed["trade_result"], "timed_half_lc")

    def test_intrabar_fill_timer_starts_after_fill_s5_closes(self):
        rows = base_s5_rows(price=149.99)
        rows[2].update(
            open=149.99,
            close=149.995,
            high=150.005,
            low=149.985,
        )
        inspector = make_inspector(rows)
        combo = TradeCombo(1.0, 1.0)
        timer = TimedHalfLcConfig(1)
        result = inspector.inspect(
            decision_time=pd.Timestamp("2025-01-06 00:00:00"),
            line_price=150.0,
            order_direction=-1,
            average_range_pips=4.0,
            path_config=FlipPathConfig(20),
            trade_combos=(combo,),
            timed_half_lc_configs=(timer,),
        )
        timed = result["outcomes"][
            f"{combo.combo_id}__{timer.config_id}"
        ]
        self.assertFalse(result["fill_at_bar_open"])
        self.assertEqual(
            timed["timed_half_lc_timer_anchor"],
            pd.Timestamp("2025-01-06 00:00:15"),
        )
        self.assertEqual(
            timed["timed_half_lc_check_time"],
            pd.Timestamp("2025-01-06 00:01:15"),
        )

    def test_fill_bar_half_tp_ambiguity_suppresses_timed_lc(self):
        rows = base_s5_rows(price=149.99)
        rows[2].update(
            open=149.99,
            close=149.995,
            high=150.005,
            low=149.97,
        )
        rows[15].update(
            open=150.03,
            close=150.03,
            high=150.031,
            low=150.029,
        )
        inspector = make_inspector(rows)
        combo = TradeCombo(1.0, 1.0)
        timer = TimedHalfLcConfig(1)
        result = inspector.inspect(
            decision_time=pd.Timestamp("2025-01-06 00:00:00"),
            line_price=150.0,
            order_direction=-1,
            average_range_pips=4.0,
            path_config=FlipPathConfig(20),
            trade_combos=(combo,),
            timed_half_lc_configs=(timer,),
        )
        outcome = result["outcomes"][
            f"{combo.combo_id}__{timer.config_id}"
        ]
        self.assertTrue(outcome["fill_bar_half_tp_ambiguous"])
        self.assertTrue(
            outcome["timed_half_lc_suppressed_by_fill_bar_ambiguity"]
        )
        self.assertFalse(outcome["timed_half_lc_activated"])

    def test_profit_lock_gap_uses_spread_aware_open_result(self):
        rows = base_s5_rows(price=149.99)
        rows[1].update(
            open=150.04,
            close=150.05,
            high=150.061,
            low=150.04,
        )
        rows[2].update(
            open=149.90,
            close=149.90,
            high=149.901,
            low=149.899,
        )
        inspector = make_inspector(rows, profit_lock_enabled=True)
        result = inspector.inspect(
            decision_time=pd.Timestamp("2025-01-06 00:00:00"),
            line_price=150.0,
            order_direction=1,
            average_range_pips=10.0,
            path_config=FlipPathConfig(20),
            trade_combos=(TradeCombo(1.0, 1.0),),
        )
        outcome = result["outcomes"]["tp1A_lc1A"]
        self.assertEqual(outcome["trade_result"], "profit_lock")
        self.assertTrue(outcome["profit_lock_exit_at_bar_open"])
        self.assertEqual(
            outcome["exit_effective_time"],
            pd.Timestamp("2025-01-06 00:00:10"),
        )
        self.assertAlmostEqual(outcome["trade_result_pips"], -10.4)

    def test_original_lc_gap_uses_spread_aware_open_result(self):
        rows = base_s5_rows(price=149.99)
        rows[2].update(
            open=149.94,
            close=149.94,
            high=149.941,
            low=149.939,
        )
        inspector = make_inspector(rows)
        result = inspector.inspect(
            decision_time=pd.Timestamp("2025-01-06 00:00:00"),
            line_price=150.0,
            order_direction=1,
            average_range_pips=4.0,
            path_config=FlipPathConfig(20),
            trade_combos=(TradeCombo(1.0, 1.0),),
        )
        outcome = result["outcomes"]["tp1A_lc1A"]
        self.assertEqual(outcome["trade_result"], "lc")
        self.assertTrue(outcome["original_lc_exit_at_bar_open"])
        self.assertAlmostEqual(outcome["trade_result_pips"], -6.4)

    def test_default_grid_builds_all_time_fraction_outcomes(self):
        rows = base_s5_rows(price=150.01)
        inspector = make_inspector(rows)
        combo = TradeCombo(1.0, 1.0)
        result = inspector.inspect(
            decision_time=pd.Timestamp("2025-01-06 00:00:00"),
            line_price=150.0,
            order_direction=-1,
            average_range_pips=4.0,
            path_config=FlipPathConfig(20),
            trade_combos=(combo,),
            timed_half_lc_configs=default_timed_half_lc_configs(),
        )
        self.assertEqual(
            len(result["outcomes"]), len(default_timed_half_lc_configs())
        )
        self.assertEqual(
            {
                outcome["timed_half_lc_config_id"]
                for outcome in result["outcomes"].values()
            },
            {config.config_id for config in default_timed_half_lc_configs()},
        )

    def test_line_wick_lc_uses_adverse_wick_and_keeps_original_lc(self):
        rows = base_s5_rows(price=149.99)
        rows[0].update(
            open=149.99,
            close=150.0,
            high=150.005,
            low=149.98,
        )
        inspector = make_inspector(rows)
        combo = TradeCombo(1.0, 1.0)
        policy = LineWickLcConfig(0.1)
        result = inspector.inspect(
            decision_time=pd.Timestamp("2025-01-06 00:00:00"),
            line_price=150.0,
            order_direction=-1,
            average_range_pips=4.0,
            path_config=FlipPathConfig(20),
            trade_combos=(combo,),
            line_wick_lc_configs=(policy,),
        )
        outcome = result["outcomes"][
            f"{combo.combo_id}__{policy.config_id}"
        ]
        self.assertEqual(outcome["trade_result"], "line_wick_lc")
        self.assertTrue(outcome["line_wick_lc_exit"])
        self.assertEqual(
            outcome["line_wick_lc_exit_mode"], "intrabar_wick_touch"
        )
        self.assertAlmostEqual(outcome["line_wick_lc_requested_pips"], 0.4)
        self.assertAlmostEqual(outcome["trade_result_pips"], -0.4)
        self.assertAlmostEqual(outcome["lc_pips"], 4.0)

    def test_default_line_wick_grid_contains_baseline_and_four_widths(self):
        configs = default_line_wick_lc_configs()
        self.assertEqual(len(configs), 5)
        self.assertEqual(configs[0].config_id, "baseline")
        self.assertEqual(
            [config.width_a for config in configs[1:]],
            [0.05, 0.10, 0.15, 0.20],
        )

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
                "recent_m5_avg_range_pips": [2.0, 2.0],
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

    def test_unfilled_order_blocks_later_fc2_until_its_deadline(self):
        frame = pd.DataFrame(
            {
                "event_id": ["a", "b", "c"],
                "decision_time": pd.to_datetime(
                    [
                        "2025-01-06 09:00",
                        "2025-01-06 09:05",
                        "2025-01-06 09:30",
                    ]
                ),
                "distance_rank": [1, 1, 1],
                "distance_pips": [2.0, 2.0, 2.0],
                "recent_m5_avg_range_pips": [2.0, 2.0, 2.0],
                "line_price": [150.0, 150.1, 150.2],
                "order_filled": [False, True, True],
                "replaced_before_fill": [False, False, False],
                "order_deadline": pd.to_datetime(
                    [
                        "2025-01-06 09:30",
                        "2025-01-06 09:20",
                        "2025-01-06 09:45",
                    ]
                ),
                "path_status": ["watch_retest_no_fill", "trade", "trade"],
                "fill_time": pd.to_datetime(
                    [None, "2025-01-06 09:07", "2025-01-06 09:31"]
                ),
                "exit_time": pd.to_datetime(
                    [None, "2025-01-06 09:10", "2025-01-06 09:35"]
                ),
                "exit_effective_time": pd.to_datetime(
                    [None, "2025-01-06 09:10:05", "2025-01-06 09:35:05"]
                ),
                "trade_result_pips": [np.nan, 2.0, 2.0],
                "result_yen": [np.nan, 50.0, 50.0],
            }
        )
        trades, summary = replay_condition(frame, PolicyCondition("ALL", "all"))
        self.assertEqual(trades["event_id"].tolist(), ["c"])
        self.assertEqual(summary["pending_order_lock_count"], 1)
        self.assertEqual(summary["skipped_while_locked_count"], 1)
        self.assertEqual(summary["selected_lifecycle_count"], 2)

    def test_global_grid_uses_the_same_pending_order_lock(self):
        frame = pd.DataFrame(
            {
                "event_id": ["a", "b", "c"],
                "decision_time": pd.to_datetime(
                    [
                        "2025-01-06 09:00",
                        "2025-01-06 09:05",
                        "2025-01-06 09:30",
                    ]
                ),
                "distance_rank": [1, 1, 1],
                "distance_pips": [2.0, 2.0, 2.0],
                "line_price": [150.0, 150.1, 150.2],
                "trade_direction": [-1, -1, -1],
                "recent_m5_avg_range_pips": [8.0, 8.0, 8.0],
                "next_count2_time": pd.to_datetime(
                    [
                        "2025-01-06 09:05",
                        "2025-01-06 09:30",
                        "2025-01-06 10:00",
                    ]
                ),
            }
        )

        class PendingInspector:
            def __init__(self):
                self.calls = []

            def inspect(self, **kwargs):
                decision = pd.Timestamp(kwargs["decision_time"])
                self.calls.append(decision)
                return {
                    "order_filled": False,
                    "replaced_before_fill": False,
                    "order_deadline": decision + pd.Timedelta(minutes=30),
                    "path_status": "no_fill",
                    "outcomes": {},
                }

        inspector = PendingInspector()
        with tempfile.TemporaryDirectory() as folder:
            summary = scan_global_grid(
                frame,
                inspector,
                (FlipPathConfig(30),),
                (TradeCombo(1.5, 1.0),),
                (1.5,),
                pair="USD_JPY",
                phase="test_global_pending_lock",
                period_start=dt.datetime(2025, 1, 1),
                period_end=dt.datetime(2025, 2, 1),
                progress_file=Path(folder) / "progress.json",
                started=time.monotonic(),
                notify=None,
            )
        self.assertEqual(
            inspector.calls,
            [
                pd.Timestamp("2025-01-06 09:00"),
                pd.Timestamp("2025-01-06 09:30"),
            ],
        )
        self.assertEqual(int(summary.iloc[0]["selected_lifecycle_count"]), 2)
        self.assertEqual(int(summary.iloc[0]["skipped_while_locked_count"]), 1)
        self.assertEqual(int(summary.iloc[0]["pending_order_lock_count"]), 2)

    def test_required_causal_source_times_cannot_be_missing(self):
        valid = {
            "decision_time": "2025-01-06 09:05:00",
            "target_source_last_time": "2025-01-06 09:00:00",
            "fc2_source_last_time": "2025-01-06 09:00:00",
            "h1_pair_source_last_time": "2025-01-06 08:00:00",
            "line_newest_source_time": "2025-01-06 08:55:00",
        }
        validate_causal_candidate(valid)
        for field in (
            "target_source_last_time",
            "fc2_source_last_time",
            "h1_pair_source_last_time",
            "line_newest_source_time",
        ):
            with self.subTest(field=field):
                invalid = dict(valid)
                invalid[field] = None
                with self.assertRaisesRegex(ValueError, "missing causal"):
                    validate_causal_candidate(invalid)

    def test_loader_rejects_missing_required_causal_source_time(self):
        row = {column: 0 for column in SOURCE_COLUMNS}
        row.update(
            {
                "event_id": "missing_target_time",
                "pair": "USD_JPY",
                "decision_time": "2025-01-06 09:05:00",
                "next_count2_time": "2025-01-06 09:10:00",
                "counterfactual_candidates": True,
                "target_valid": True,
                "target_source_last_time": "",
                "recent_m5_avg_range_pips": 4.0,
                "peak_count": 2,
                "peak_direction": 1,
                "trade_direction": -1,
                "fc2_valid": True,
                "fc2_source_last_time": "2025-01-06 09:00:00",
                "line_price": 150.0,
                "distance_rank": 1,
                "distance_pips": 2.0,
                "line_newest_source_time": "2025-01-06 08:55:00",
                "line_source_directions": "-1",
            }
        )
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "candidates.csv"
            pd.DataFrame([row]).to_csv(source, index=False)
            with self.assertRaisesRegex(ValueError, "missing causal feature"):
                load_candidates(
                    source,
                    pair="USD_JPY",
                    start=dt.datetime(2025, 1, 1),
                    end=dt.datetime(2025, 2, 1),
                )

    def test_open_exit_unlocks_event_at_same_effective_timestamp(self):
        frame = pd.DataFrame(
            {
                "event_id": ["a", "b"],
                "decision_time": pd.to_datetime(
                    ["2025-01-06 09:00", "2025-01-06 09:05"]
                ),
                "distance_rank": [1, 1],
                "distance_pips": [2.0, 2.0],
                "line_price": [150.0, 150.1],
                "recent_m5_avg_range_pips": [2.0, 2.0],
                "order_filled": [True, True],
                "path_status": ["trade", "trade"],
                "fill_time": pd.to_datetime(
                    ["2025-01-06 09:00", "2025-01-06 09:05"]
                ),
                "exit_time": pd.to_datetime(
                    ["2025-01-06 09:05", "2025-01-06 09:06"]
                ),
                "exit_effective_time": pd.to_datetime(
                    ["2025-01-06 09:05:00", "2025-01-06 09:06:05"]
                ),
                "trade_result": ["timed_half_lc", "tp"],
                "trade_result_pips": [-1.0, 2.0],
                "result_yen": [-25.0, 50.0],
            }
        )
        trades, summary = replay_condition(
            frame, PolicyCondition("ALL", "all")
        )
        self.assertEqual(trades["event_id"].tolist(), ["a", "b"])
        self.assertEqual(summary["completed_trade_count"], 2)


class Top15TierPolicyTest(unittest.TestCase):
    def test_no_fill_remains_in_every_timed_policy_universe(self):
        frame = pd.DataFrame(
            {
                "event_id": ["e1"],
                "decision_time": pd.to_datetime(["2025-01-06 00:00:00"]),
                "next_count2_time": pd.to_datetime(["2025-01-06 00:30:00"]),
                "signal_tier": ["HIGH"],
                "distance_rank": [1],
                "distance_pips": [2.0],
                "line_price": [150.0],
                "trade_direction": [-1],
                "recent_m5_avg_range_pips": [6.0],
            }
        )
        inspector = make_inspector(base_s5_rows(price=149.98))
        policies = default_timed_half_lc_configs()
        with tempfile.TemporaryDirectory() as folder:
            grid = inspect_timed_half_lc_grid_paths(
                frame,
                inspector,
                FlipPathConfig(20),
                default_tier_execution_configs(),
                policies,
                pair="USD_JPY",
                phase="test",
                period_start=dt.datetime(2025, 1, 6),
                progress_file=Path(folder) / "progress.json",
                started=time.monotonic(),
                notify=None,
            )
        self.assertEqual(len(grid), len(policies))
        self.assertEqual(grid["order_filled"].fillna(False).sum(), 0)
        self.assertEqual(
            set(grid["timed_half_lc_config_id"]),
            {config.config_id for config in policies},
        )
        summary, trades = scan_timed_half_lc_grid(
            grid,
            policies,
            period_start=dt.datetime(2025, 1, 6),
            period_end=dt.datetime(2025, 1, 7),
        )
        self.assertEqual(
            summary["candidate_count"].tolist(), [1] * len(policies)
        )
        self.assertTrue(trades.empty)

    def test_range_filter_boundary_is_consistent(self):
        frame = pd.DataFrame({"recent_m5_avg_range_pips": [6.0, 5.999999999996]})
        self.assertEqual(range_filter_mask(frame, 1.5).tolist(), [True, True])

    def test_target_distance_filter_uses_decision_time_distance(self):
        frame = pd.DataFrame(
            {"distance_pips": [2.0, 1.9999999999, 1.999, np.nan]}
        )
        self.assertEqual(
            target_distance_filter_mask(frame, 2.0).tolist(),
            [True, True, False, False],
        )

    def test_atomic_json_converts_infinity_to_null(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "summary.json"
            atomic_json(path, {"pf": float("inf"), "nested": [np.nan]})
            payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertIsNone(payload["pf"])
        self.assertIsNone(payload["nested"][0])

    def test_default_timed_half_lc_grid_crosses_time_and_fraction(self):
        configs = default_timed_half_lc_configs()
        self.assertEqual(len(configs), 31)
        self.assertEqual(configs[0].config_id, "baseline")
        enabled = configs[1:]
        self.assertEqual(
            sorted({config.trigger_minutes for config in enabled}),
            [3, 6, 9, 12, 15, 18],
        )
        self.assertEqual(
            sorted({config.lc_fraction for config in enabled}),
            [0.3, 0.4, 0.5, 0.6, 0.7],
        )

    def test_timed_half_lc_selector_uses_strict_train_metrics(self):
        rows = []
        for order, config in enumerate(default_timed_half_lc_configs()):
            rows.append(
                {
                    **config.to_dict(),
                    "timed_half_lc_policy_order": order,
                    "completed_trade_count": 120,
                    "sum_yen": (
                        200.0
                        if config.trigger_minutes == 9
                        and config.lc_fraction == 0.5
                        else 100.0
                    ),
                    "sum_pips": 20.0,
                    "profit_factor_yen": 1.2,
                    "positive_period_count": 3,
                    "max_positive_period_profit_share": 0.5,
                }
            )
        selected = choose_timed_half_lc_policy(pd.DataFrame(rows))
        self.assertEqual(selected["config_id"], "timed_9m_lc0p5")
        self.assertEqual(selected["selection_stage"], "strict_stability")

    def test_timed_half_lc_selector_falls_back_only_to_baseline(self):
        rows = []
        for order, config in enumerate(default_timed_half_lc_configs()[:2]):
            rows.append(
                {
                    **config.to_dict(),
                    "timed_half_lc_policy_order": order,
                    "completed_trade_count": 20,
                    "sum_yen": -1.0,
                    "sum_pips": -1.0,
                    "profit_factor_yen": 0.9,
                    "positive_period_count": 1,
                    "max_positive_period_profit_share": 1.0,
                }
            )
        selected = choose_timed_half_lc_policy(pd.DataFrame(rows))
        self.assertEqual(selected["config_id"], "baseline")
        self.assertEqual(
            selected["selection_stage"], "baseline_no_strict_candidate"
        )

    def test_multi_timed_selector_requires_strict_metrics_and_deduplicates(self):
        policies = (
            TimedHalfLcConfig(None),
            TimedHalfLcConfig(3, lc_fraction=0.3),
            TimedHalfLcConfig(6, lc_fraction=0.4),
            TimedHalfLcConfig(9, lc_fraction=0.7),
        )
        summary_rows = []
        for order, config in enumerate(policies):
            strict = config.enabled
            summary_rows.append(
                {
                    **config.to_dict(),
                    "timed_half_lc_policy_order": order,
                    "completed_trade_count": 120,
                    "timed_half_lc_activation_count": 40 if strict else 0,
                    "sum_yen": 300.0 if strict else 100.0,
                    "sum_pips": 20.0,
                    "profit_factor_yen": 1.2 if strict else 1.0,
                    "positive_period_count": 3 if strict else 2,
                    "max_positive_period_profit_share": 0.5,
                    "delta_vs_baseline_sum_yen": 200.0 if strict else 0.0,
                }
            )
        trades = pd.DataFrame(
            {
                "timed_half_lc_config_id": (
                    [policies[1].config_id] * 4
                    + [policies[2].config_id] * 4
                    + [policies[3].config_id] * 4
                ),
                "event_id": ["a", "b", "c", "d"] * 2
                + ["w", "x", "y", "z"],
                "timed_half_lc_exit": [True] * 12,
            }
        )
        selected_configs, selected_rows = select_timed_half_lc_policies(
            pd.DataFrame(summary_rows),
            trades,
            policies,
            minimum_trades=30,
            minimum_activations=30,
            limit=5,
            maximum_trigger_jaccard=0.85,
        )
        self.assertEqual(
            [config.config_id for config in selected_configs],
            [policies[1].config_id, policies[3].config_id],
        )
        self.assertEqual(selected_rows["selection_rank"].tolist(), [1, 2])

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
                "recent_m5_avg_range_pips": [8.0] * 6,
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
            TierExecutionConfig("HIGH", 1, 1, 1.7, 1.5, 2.0),
            TierExecutionConfig("MIDDLE", 2, 2, 1.7, 1.3, 1.5),
            TierExecutionConfig("LOW", 3, 3, 1.7, 1.1, 1.0),
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
                "recent_m5_avg_range_pips": [8.0, 6.0, 4.0],
                "f_tier": ["h", "m", "l"],
            }
        )
        selected = select_top_condition_policy_candidates(frame, ranked, configs)
        self.assertEqual(selected["signal_tier"].tolist(), ["HIGH", "MIDDLE", "LOW"])
        self.assertEqual(selected["tier_rr"].tolist(), [1.5, 1.3, 1.1])
        self.assertEqual(
            selected["tier_min_range_filter_pips"].tolist(), [2.0, 1.5, 1.0]
        )
        self.assertTrue(selected["range_filter_passed"].all())
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
