import argparse
import datetime as dt
import unittest
from types import SimpleNamespace

import numpy as np
import pandas as pd

from count2_prior2y_oos_replay import (
    CURRENT_EXIT_POLICY,
    EXIT_COMPARISON_POLICIES,
    STEP_TP_FRACTION_EXIT_POLICY,
    ExitManagementPolicy,
    Intent,
    Policy,
    _is_expected_annual_holiday_closure_gap,
    _is_expected_annual_holiday_reopen_gap,
    _is_expected_no_quote_interval,
    _validate_s5_timeline,
    replay_metric,
)


class Count2Prior2yOosReplayTest(unittest.TestCase):
    @staticmethod
    def args(**overrides):
        values = {
            "pair": "USD_JPY",
            "spread_pips": 0.8,
            "min_target_pips": 1.6,
            "trade_timeout_min": 60,
            "profit_lock_ratio": 0.5,
            "duplicate_threshold_pips": 3.0,
            "risk_yen": 50.0,
            "output_dir": None,
            "train_start": dt.datetime(2023, 7, 30),
            "train_end": dt.datetime(2025, 7, 30),
            "oos_start": dt.datetime(2025, 7, 30),
            "oos_end": dt.datetime(2026, 7, 30),
        }
        values.update(overrides)
        return argparse.Namespace(**values)

    @staticmethod
    def policy():
        return Policy(
            rank=1,
            metric="yen",
            order_name="policy",
            condition_id="M5::criterion_alternating::true",
            entry_rank=1,
            offset_multiplier=0.0,
            tp_multiplier=1.0,
            lc_multiplier=1.0,
        )

    @staticmethod
    def intent(
        event_id,
        when,
        *,
        entry=100.0,
        direction=1,
        tp_pips=100.0,
        lc_pips=100.0,
    ):
        return Intent(
            event_id=event_id,
            decision_time=pd.Timestamp(when),
            decision_price=entry + direction * -0.01,
            policy_rank=1,
            order_name="policy",
            condition_id="M5::criterion_alternating::true",
            entry_rank=1,
            direction=direction,
            entry_price=entry,
            adjusted_distance_pips=1.0,
            entry_offset_pips=0.0,
            tp_pips=tp_pips,
            lc_pips=lc_pips,
            priority=5,
        )

    @staticmethod
    def inspector(start, minutes, *, price=100.0):
        count = minutes * 12
        times = pd.date_range(start=start, periods=count, freq="5s").to_numpy(
            dtype="datetime64[ns]"
        )
        opens = np.full(count, price, dtype=float)
        closes = np.full(count, price, dtype=float)
        highs = np.full(count, price + 0.005, dtype=float)
        lows = np.full(count, price - 0.01, dtype=float)
        return SimpleNamespace(
            times=times,
            opens=opens,
            closes=closes,
            highs=highs,
            lows=lows,
        )

    def test_new_count2_cancels_pending_before_replacement(self):
        start = pd.Timestamp("2025-07-30 00:00:00")
        inspector = self.inspector(start, 20, price=99.0)
        # A BUY limit at 100 would fill at 99, so use SELL limits well above.
        first = self.intent("e1", start, entry=101.0, direction=-1)
        second_time = start + pd.Timedelta(minutes=5)
        second = self.intent("e2", second_time, entry=102.0, direction=-1)
        _, summary = replay_metric(
            self.args(),
            "yen",
            [self.policy()],
            [("e1", start), ("e2", second_time)],
            {"e1": first, "e2": second},
            inspector,
        )
        self.assertEqual(summary["cancelled_next_count2"], 1)
        self.assertEqual(summary["submitted"], 2)
        self.assertEqual(summary["filled"], 0)

    def test_unprotected_position_blocks_followup(self):
        start = pd.Timestamp("2025-07-30 00:00:00")
        inspector = self.inspector(start, 40, price=100.0)
        second_time = start + pd.Timedelta(minutes=10)
        first = self.intent("e1", start, entry=100.0)
        second = self.intent("e2", second_time, entry=101.0)
        _, summary = replay_metric(
            self.args(),
            "yen",
            [self.policy()],
            [("e1", start), ("e2", second_time)],
            {"e1": first, "e2": second},
            inspector,
        )
        self.assertEqual(summary["filled"], 1)
        self.assertEqual(summary["blocked_unprotected_position"], 1)

    def test_profitable_timeout_lock_permits_later_followup(self):
        start = pd.Timestamp("2025-07-30 00:00:00")
        inspector = self.inspector(start, 80, price=100.0)
        after_55 = inspector.times >= np.datetime64(start + pd.Timedelta(minutes=55))
        inspector.opens[after_55] = 100.20
        inspector.closes[after_55] = 100.20
        inspector.highs[after_55] = 100.205
        inspector.lows[after_55] = 100.19
        blocked_time = start + pd.Timedelta(minutes=30)
        allowed_time = start + pd.Timedelta(minutes=65)
        first = self.intent("e1", start, entry=100.0)
        blocked = self.intent("e2", blocked_time, entry=101.0)
        allowed = self.intent("e3", allowed_time, entry=101.0)
        _, summary = replay_metric(
            self.args(),
            "yen",
            [self.policy()],
            [("e1", start), ("e2", blocked_time), ("e3", allowed_time)],
            {"e1": first, "e2": blocked, "e3": allowed},
            inspector,
        )
        self.assertEqual(summary["profit_locks"], 1)
        self.assertEqual(summary["blocked_unprotected_position"], 1)
        self.assertEqual(summary["submitted"], 2)

    def test_step_trail_starts_at_sixty_minute_close_without_retroactive_lc(self):
        start = pd.Timestamp("2025-07-30 00:00:00")
        inspector = self.inspector(start, 61, price=100.0)
        boundary = inspector.times == np.datetime64(
            start + pd.Timedelta(minutes=59, seconds=55)
        )
        inspector.opens[boundary] = 100.0
        inspector.highs[boundary] = 100.025
        inspector.lows[boundary] = 99.990
        inspector.closes[boundary] = 100.020
        following = inspector.times == np.datetime64(start + pd.Timedelta(minutes=60))
        inspector.opens[following] = 100.020
        inspector.highs[following] = 100.021
        inspector.lows[following] = 100.009
        inspector.closes[following] = 100.015
        intent = self.intent("e1", start, tp_pips=10.0, lc_pips=10.0)

        trades, summary = replay_metric(
            self.args(spread_pips=0.0),
            "yen",
            [self.policy()],
            [("e1", start)],
            {"e1": intent},
            inspector,
            management_policy=STEP_TP_FRACTION_EXIT_POLICY,
        )

        self.assertEqual(summary["profit_locks"], 1)
        self.assertEqual(summary["profit_lock_updates"], 1)
        self.assertEqual(pd.Timestamp(trades.iloc[0]["exit_time"]), start + pd.Timedelta(minutes=60))
        self.assertEqual(trades.iloc[0]["result_type"], "lc")
        self.assertEqual(int(trades.iloc[0]["profit_lock_step_index"]), 1)
        self.assertAlmostEqual(float(trades.iloc[0]["result_pips"]), 1.0)

    def test_step_trail_keeps_raw_fraction_until_the_next_price_tick(self):
        start = pd.Timestamp("2025-07-30 00:00:00")
        inspector = self.inspector(start, 61, price=100.0)
        boundary = inspector.times == np.datetime64(
            start + pd.Timedelta(minutes=59, seconds=55)
        )
        inspector.opens[boundary] = 100.003
        inspector.highs[boundary] = 100.004
        inspector.lows[boundary] = 99.990
        inspector.closes[boundary] = 100.003
        next_bar = inspector.times == np.datetime64(start + pd.Timedelta(minutes=60))
        inspector.opens[next_bar] = 100.004
        inspector.highs[next_bar] = 100.005
        inspector.lows[next_bar] = 100.001
        inspector.closes[next_bar] = 100.004
        after_lock = inspector.times >= np.datetime64(
            start + pd.Timedelta(minutes=60, seconds=5)
        )
        inspector.opens[after_lock] = 100.005
        inspector.highs[after_lock] = 100.006
        inspector.lows[after_lock] = 100.003
        inspector.closes[after_lock] = 100.005
        intent = self.intent("e1", start, tp_pips=1.6, lc_pips=10.0)

        trades, summary = replay_metric(
            self.args(spread_pips=0.0),
            "yen",
            [self.policy()],
            [("e1", start)],
            {"e1": intent},
            inspector,
            management_policy=STEP_TP_FRACTION_EXIT_POLICY,
        )

        self.assertEqual(summary["profit_lock_updates"], 1)
        self.assertEqual(int(trades.iloc[0]["profit_lock_step_index"]), 1)
        self.assertEqual(trades.iloc[0]["result_type"], "period_end_mark")
        self.assertAlmostEqual(float(trades.iloc[0]["final_lc_pips"]), 0.2)

    def test_step_trail_is_symmetric_for_sell_positions(self):
        start = pd.Timestamp("2025-07-30 00:00:00")
        inspector = self.inspector(start, 61, price=100.0)
        boundary = inspector.times == np.datetime64(
            start + pd.Timedelta(minutes=59, seconds=55)
        )
        inspector.opens[boundary] = 99.980
        inspector.highs[boundary] = 100.010
        inspector.lows[boundary] = 99.975
        inspector.closes[boundary] = 99.980
        following = inspector.times == np.datetime64(start + pd.Timedelta(minutes=60))
        inspector.opens[following] = 99.985
        inspector.highs[following] = 99.991
        inspector.lows[following] = 99.980
        inspector.closes[following] = 99.985
        intent = self.intent(
            "e1", start, direction=-1, tp_pips=10.0, lc_pips=10.0
        )

        trades, summary = replay_metric(
            self.args(spread_pips=0.0),
            "yen",
            [self.policy()],
            [("e1", start)],
            {"e1": intent},
            inspector,
            management_policy=STEP_TP_FRACTION_EXIT_POLICY,
        )

        self.assertEqual(summary["profit_lock_updates"], 1)
        self.assertEqual(trades.iloc[0]["result_type"], "lc")
        self.assertAlmostEqual(float(trades.iloc[0]["exit_price"]), 99.99)
        self.assertAlmostEqual(float(trades.iloc[0]["result_pips"]), 1.0)
        self.assertAlmostEqual(float(trades.iloc[0]["final_lc_pips"]), 1.0)

    def test_step_trail_ignores_pre_timeout_mfe_while_losing(self):
        start = pd.Timestamp("2025-07-30 00:00:00")
        inspector = self.inspector(start, 61, price=100.0)
        pre_boundary = inspector.times == np.datetime64(
            start + pd.Timedelta(minutes=59, seconds=50)
        )
        inspector.opens[pre_boundary] = 100.080
        inspector.highs[pre_boundary] = 100.081
        inspector.lows[pre_boundary] = 100.070
        inspector.closes[pre_boundary] = 100.080
        after_boundary = inspector.times >= np.datetime64(
            start + pd.Timedelta(minutes=59, seconds=55)
        )
        inspector.opens[after_boundary] = 99.990
        inspector.highs[after_boundary] = 99.995
        inspector.lows[after_boundary] = 99.985
        inspector.closes[after_boundary] = 99.990
        followup_time = start + pd.Timedelta(minutes=60)
        first = self.intent("e1", start, tp_pips=10.0, lc_pips=10.0)
        followup = self.intent(
            "e2", followup_time, entry=99.0, tp_pips=10.0, lc_pips=10.0
        )

        trades, summary = replay_metric(
            self.args(spread_pips=0.0),
            "yen",
            [self.policy()],
            [("e1", start), ("e2", followup_time)],
            {"e1": first, "e2": followup},
            inspector,
            management_policy=STEP_TP_FRACTION_EXIT_POLICY,
        )

        self.assertEqual(summary["profit_locks"], 0)
        self.assertEqual(summary["profit_lock_updates"], 0)
        self.assertEqual(summary["blocked_unprotected_position"], 1)
        self.assertEqual(summary["submitted"], 1)
        self.assertGreaterEqual(float(trades.iloc[0]["max_favorable_pips"]), 8.0)
        self.assertEqual(int(trades.iloc[0]["profit_lock_step_index"]), 0)
        self.assertAlmostEqual(float(trades.iloc[0]["final_lc_pips"]), -10.0)

    def test_step_trail_advances_one_stage_per_s5_and_never_lowers_lc(self):
        start = pd.Timestamp("2025-07-30 00:00:00")
        inspector = self.inspector(start, 62, price=100.0)
        boundary = inspector.times == np.datetime64(
            start + pd.Timedelta(minutes=59, seconds=55)
        )
        inspector.opens[boundary] = 99.990
        inspector.highs[boundary] = 99.995
        inspector.lows[boundary] = 99.985
        inspector.closes[boundary] = 99.990
        for seconds, low in ((0, 99.990), (5, 100.030), (10, 100.050), (15, 100.070)):
            timestamp = start + pd.Timedelta(minutes=60, seconds=seconds)
            mask = inspector.times == np.datetime64(timestamp)
            inspector.opens[mask] = 100.161
            inspector.highs[mask] = 100.165
            inspector.lows[mask] = low
            inspector.closes[mask] = 100.161
        after_steps = inspector.times >= np.datetime64(
            start + pd.Timedelta(minutes=60, seconds=20)
        )
        inspector.opens[after_steps] = 100.090
        inspector.highs[after_steps] = 100.095
        inspector.lows[after_steps] = 100.085
        inspector.closes[after_steps] = 100.090
        intent = self.intent("e1", start, tp_pips=20.0, lc_pips=20.0)

        trades, summary = replay_metric(
            self.args(spread_pips=0.0),
            "yen",
            [self.policy()],
            [("e1", start)],
            {"e1": intent},
            inspector,
            management_policy=STEP_TP_FRACTION_EXIT_POLICY,
        )

        self.assertEqual(summary["profit_locks"], 1)
        self.assertEqual(summary["profit_lock_updates"], 4)
        self.assertEqual(int(trades.iloc[0]["profit_lock_step_index"]), 4)
        self.assertAlmostEqual(float(trades.iloc[0]["final_lc_pips"]), 8.0)
        self.assertEqual(trades.iloc[0]["result_type"], "period_end_mark")

    def test_tp_on_timeout_boundary_wins_before_step_update(self):
        start = pd.Timestamp("2025-07-30 00:00:00")
        inspector = self.inspector(start, 61, price=100.0)
        boundary_time = start + pd.Timedelta(minutes=59, seconds=55)
        boundary = inspector.times == np.datetime64(boundary_time)
        inspector.opens[boundary] = 100.080
        inspector.highs[boundary] = 100.100
        inspector.lows[boundary] = 100.030
        inspector.closes[boundary] = 100.081
        intent = self.intent("e1", start, tp_pips=10.0, lc_pips=10.0)

        trades, summary = replay_metric(
            self.args(spread_pips=0.0),
            "yen",
            [self.policy()],
            [("e1", start)],
            {"e1": intent},
            inspector,
            management_policy=STEP_TP_FRACTION_EXIT_POLICY,
        )

        self.assertEqual(trades.iloc[0]["result_type"], "tp")
        self.assertEqual(pd.Timestamp(trades.iloc[0]["exit_time"]), boundary_time)
        self.assertAlmostEqual(float(trades.iloc[0]["result_pips"]), 10.0)
        self.assertEqual(summary["profit_locks"], 0)
        self.assertEqual(summary["profit_lock_updates"], 0)

    def test_step_trail_allows_followup_only_after_first_completed_stage(self):
        start = pd.Timestamp("2025-07-30 00:00:00")
        inspector = self.inspector(start, 61, price=100.0)
        after_boundary = inspector.times >= np.datetime64(
            start + pd.Timedelta(minutes=59, seconds=55)
        )
        inspector.opens[after_boundary] = 100.021
        inspector.highs[after_boundary] = 100.025
        inspector.lows[after_boundary] = 100.015
        inspector.closes[after_boundary] = 100.021
        locking_bar_time = start + pd.Timedelta(minutes=59, seconds=55)
        following_bar_time = start + pd.Timedelta(minutes=60)
        first = self.intent("e1", start, tp_pips=10.0, lc_pips=10.0)
        blocked = self.intent(
            "e2", locking_bar_time, entry=99.0, tp_pips=10.0, lc_pips=10.0
        )
        allowed = self.intent(
            "e3", following_bar_time, entry=98.0, tp_pips=10.0, lc_pips=10.0
        )

        _, summary = replay_metric(
            self.args(spread_pips=0.0),
            "yen",
            [self.policy()],
            [("e1", start), ("e2", locking_bar_time), ("e3", following_bar_time)],
            {"e1": first, "e2": blocked, "e3": allowed},
            inspector,
            management_policy=STEP_TP_FRACTION_EXIT_POLICY,
        )

        self.assertEqual(summary["blocked_unprotected_position"], 1)
        self.assertEqual(summary["submitted"], 2)
        self.assertEqual(summary["profit_locks"], 1)
        self.assertEqual(summary["profit_lock_updates"], 1)

    def test_step_profit_policy_rejects_invalid_fractions(self):
        with self.assertRaisesRegex(ValueError, "unique and increasing"):
            ExitManagementPolicy(
                name="invalid",
                step_trigger_tp_fractions=(0.4, 0.2),
                step_ensure_trigger_ratio=0.5,
            )

    def test_step_profit_policy_is_registered_once_for_comparison(self):
        names = [policy.name for policy in EXIT_COMPARISON_POLICIES]
        self.assertIn(STEP_TP_FRACTION_EXIT_POLICY, EXIT_COMPARISON_POLICIES)
        self.assertEqual(len(names), len(set(names)))

    def test_loss_cap_tightens_only_after_sixty_minutes(self):
        start = pd.Timestamp("2025-07-30 00:00:00")
        inspector = self.inspector(start, 80, price=100.0)
        after_55 = inspector.times >= np.datetime64(start + pd.Timedelta(minutes=55))
        inspector.opens[after_55] = 99.80
        inspector.closes[after_55] = 99.80
        inspector.highs[after_55] = 99.805
        inspector.lows[after_55] = 99.79
        after_61 = inspector.times >= np.datetime64(start + pd.Timedelta(minutes=61))
        inspector.opens[after_61] = 99.40
        inspector.closes[after_61] = 99.40
        inspector.highs[after_61] = 99.405
        inspector.lows[after_61] = 99.39
        intent = self.intent("e1", start, entry=100.0)
        cap_policy = next(
            policy for policy in EXIT_COMPARISON_POLICIES if policy.name == "loss_cap_0.5r"
        )
        trades, summary = replay_metric(
            self.args(),
            "yen",
            [self.policy()],
            [("e1", start)],
            {"e1": intent},
            inspector,
            management_policy=cap_policy,
        )
        self.assertEqual(summary["loss_caps"], 1)
        self.assertEqual(summary["loss_cap_immediate_exits"], 0)
        self.assertEqual(trades.iloc[0]["result_type"], "loss_cap_lc")
        self.assertAlmostEqual(float(trades.iloc[0]["result_r"]), -0.5)

    def test_loss_market_exit_uses_first_causal_close_at_sixty_minutes(self):
        start = pd.Timestamp("2025-07-30 00:00:00")
        inspector = self.inspector(start, 70, price=100.0)
        after_55 = inspector.times >= np.datetime64(start + pd.Timedelta(minutes=55))
        inspector.opens[after_55] = 99.80
        inspector.closes[after_55] = 99.80
        inspector.highs[after_55] = 99.805
        inspector.lows[after_55] = 99.79
        intent = self.intent("e1", start, entry=100.0)
        exit_policy = next(
            policy
            for policy in EXIT_COMPARISON_POLICIES
            if policy.name == "loss_market_exit_60m"
        )
        trades, summary = replay_metric(
            self.args(),
            "yen",
            [self.policy()],
            [("e1", start)],
            {"e1": intent},
            inspector,
            management_policy=exit_policy,
        )
        self.assertEqual(summary["loss_timeout_market_exits"], 1)
        self.assertEqual(trades.iloc[0]["result_type"], "loss_timeout_market_exit")
        self.assertEqual(pd.Timestamp(trades.iloc[0]["exit_time"]), start + pd.Timedelta(minutes=59, seconds=55))
        self.assertGreater(float(trades.iloc[0]["result_r"]), -1.0)

    def test_current_policy_remains_default(self):
        start = pd.Timestamp("2025-07-30 00:00:00")
        inspector_default = self.inspector(start, 80, price=100.0)
        inspector_explicit = self.inspector(start, 80, price=100.0)
        intent = self.intent("e1", start, entry=100.0)
        default_trades, default_summary = replay_metric(
            self.args(),
            "yen",
            [self.policy()],
            [("e1", start)],
            {"e1": intent},
            inspector_default,
        )
        explicit_trades, explicit_summary = replay_metric(
            self.args(),
            "yen",
            [self.policy()],
            [("e1", start)],
            {"e1": intent},
            inspector_explicit,
            management_policy=CURRENT_EXIT_POLICY,
        )
        pd.testing.assert_frame_equal(default_trades, explicit_trades)
        self.assertEqual(default_summary, explicit_summary)

    def test_known_full_day_holiday_gaps_are_allowed(self):
        self.assertTrue(
            _is_expected_annual_holiday_closure_gap(
                pd.Timestamp("2025-12-25 07:13:30"),
                pd.Timestamp("2025-12-26 07:04:55"),
            )
        )
        self.assertTrue(
            _is_expected_annual_holiday_closure_gap(
                pd.Timestamp("2026-01-01 07:14:00"),
                pd.Timestamp("2026-01-02 07:04:55"),
            )
        )

    def test_arbitrary_weekday_gap_is_still_rejected(self):
        times = np.array(
            [
                np.datetime64("2026-02-10T07:10:00", "ns"),
                np.datetime64("2026-02-11T07:10:00", "ns"),
            ]
        )
        inspector = SimpleNamespace(
            times=times,
            _is_expected_market_closed_gap=lambda _previous, _following: False,
        )
        with self.assertRaisesRegex(ValueError, "Unknown S5 gap"):
            _validate_s5_timeline(inspector)

    def test_short_new_year_reopen_gap_is_allowed(self):
        self.assertTrue(
            _is_expected_annual_holiday_reopen_gap(
                pd.Timestamp("2026-01-02 07:19:55"),
                pd.Timestamp("2026-01-02 07:26:50"),
            )
        )
        self.assertFalse(
            _is_expected_annual_holiday_reopen_gap(
                pd.Timestamp("2026-02-02 07:19:55"),
                pd.Timestamp("2026-02-02 07:26:50"),
            )
        )

    def test_decision_during_daily_pause_waits_for_next_actual_s5(self):
        inspector = SimpleNamespace(
            _is_expected_market_closed_gap=lambda _previous, _following: True,
        )
        self.assertTrue(
            _is_expected_no_quote_interval(
                inspector,
                pd.Timestamp("2025-07-30 06:00:00"),
                pd.Timestamp("2025-07-30 06:04:55"),
            )
        )

    def test_decision_during_unknown_gap_is_rejected(self):
        inspector = SimpleNamespace(
            _is_expected_market_closed_gap=lambda _previous, _following: False,
        )
        self.assertFalse(
            _is_expected_no_quote_interval(
                inspector,
                pd.Timestamp("2025-07-30 12:00:00"),
                pd.Timestamp("2025-07-30 12:04:55"),
            )
        )


if __name__ == "__main__":
    unittest.main()
