# 最新更新日時: 2026-09-09 16:11 JST
"""時間足別dispatchの回帰テスト。注文生成/APIはmockし、本番起動しない。"""
import _bootstrap

from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import fAnalysis_order_Main as analysis
from fAnalysisSchedule import AnalysisRunLedger
import fResistanceBreakoutAnalysis as breakout


class TimeframeDispatchTest(unittest.TestCase):
    def wrapper(self, now, ledger):
        instance = analysis.wrap_all_analysis.__new__(analysis.wrap_all_analysis)
        instance.mode = "live"
        instance.ca = SimpleNamespace(pair="USD_JPY")
        instance.analysis_time_utc = now
        instance.decision_time_utc = now.replace(second=0, microsecond=0)
        instance.run_ledger = ledger
        instance.resistance_breakout_order_classes = []
        instance.orders_add_from_analysis = Mock()
        instance.notify_analysis_failure = Mock()
        return instance

    def test_m30_is_not_called_between_half_hour_boundaries(self):
        instance = self.wrapper(
            datetime(2026, 9, 9, 10, 35, 6, tzinfo=timezone.utc),
            AnalysisRunLedger(),
        )
        with patch.object(breakout, "build_orders_for_decision") as build:
            instance.wrap_resistance_breakout_analysis()
        build.assert_not_called()

    def test_same_completed_m30_is_consumed_even_without_signal(self):
        ledger = AnalysisRunLedger()
        now = datetime(2026, 9, 9, 10, 30, 6, tzinfo=timezone.utc)
        with patch.object(breakout, "build_orders_for_decision", return_value=[]) as build:
            self.wrapper(now, ledger).wrap_resistance_breakout_analysis()
            self.wrapper(now.replace(second=20), ledger).wrap_resistance_breakout_analysis()
        self.assertEqual(build.call_count, 1)

    def test_both_timeframes_are_independent_at_half_hour(self):
        policy = replace(breakout.LIVE_TRIAL_POLICY_V1, timeframes=("M5", "M30"))
        instance = self.wrapper(
            datetime(2026, 9, 9, 10, 30, 6, tzinfo=timezone.utc),
            AnalysisRunLedger(),
        )
        orders = [SimpleNamespace(), SimpleNamespace()]
        with (
            patch.object(breakout, "LIVE_TRIAL_POLICY_V1", policy),
            patch.object(breakout, "build_orders_for_decision", side_effect=[[orders[0]], [orders[1]]]) as build,
        ):
            instance.wrap_resistance_breakout_analysis()
        self.assertEqual(
            [call.kwargs["policy"].timeframes for call in build.call_args_list],
            [("M5",), ("M30",)],
        )
        self.assertEqual(instance.resistance_breakout_order_classes, orders)

    def test_one_timeframe_failure_does_not_discard_other_orders(self):
        policy = replace(breakout.LIVE_TRIAL_POLICY_V1, timeframes=("M5", "M30"))
        instance = self.wrapper(
            datetime(2026, 9, 9, 10, 30, 6, tzinfo=timezone.utc),
            AnalysisRunLedger(),
        )
        order = SimpleNamespace()
        with (
            patch.object(breakout, "LIVE_TRIAL_POLICY_V1", policy),
            patch.object(breakout, "build_orders_for_decision", side_effect=[[order], ValueError("M30 unavailable")]),
        ):
            instance.wrap_resistance_breakout_analysis()
        instance.orders_add_from_analysis.assert_called_once_with("resistance_breakout", [order])
        instance.notify_analysis_failure.assert_called_once()

    def test_startup_before_six_seconds_does_not_analyze(self):
        instance = self.wrapper(
            datetime(2026, 9, 9, 10, 30, 5, tzinfo=timezone.utc),
            AnalysisRunLedger(),
        )
        with patch.object(breakout, "build_orders_for_decision") as build:
            instance.wrap_resistance_breakout_analysis()
        build.assert_not_called()

    def test_h1_only_runs_at_hour_boundary_and_once_per_completed_bar(self):
        policy = replace(breakout.LIVE_TRIAL_POLICY_V1, timeframes=("H1",))
        ledger = AnalysisRunLedger()
        with (
            patch.object(breakout, "LIVE_TRIAL_POLICY_V1", policy),
            patch.object(breakout, "build_orders_for_decision", return_value=[]) as build,
        ):
            for minute in (5, 15, 30, 55):
                self.wrapper(
                    datetime(2026, 9, 9, 10, minute, 6, tzinfo=timezone.utc), ledger,
                ).wrap_resistance_breakout_analysis()
            build.assert_not_called()
            now = datetime(2026, 9, 9, 11, 0, 6, tzinfo=timezone.utc)
            self.wrapper(now, ledger).wrap_resistance_breakout_analysis()
            self.wrapper(now.replace(second=20), ledger).wrap_resistance_breakout_analysis()
            self.assertEqual(build.call_count, 1)
            self.assertEqual(build.call_args.kwargs["policy"].timeframes, ("H1",))

    def test_all_three_timeframes_are_independent_at_hour_boundary(self):
        policy = replace(breakout.LIVE_TRIAL_POLICY_V1, timeframes=("M5", "M30", "H1"))
        instance = self.wrapper(
            datetime(2026, 9, 9, 10, 0, 6, tzinfo=timezone.utc),
            AnalysisRunLedger(),
        )
        orders = [SimpleNamespace(), SimpleNamespace(), SimpleNamespace()]
        with (
            patch.object(breakout, "LIVE_TRIAL_POLICY_V1", policy),
            patch.object(breakout, "build_orders_for_decision", side_effect=[[item] for item in orders]) as build,
        ):
            instance.wrap_resistance_breakout_analysis()
        self.assertEqual(
            [call.kwargs["policy"].timeframes for call in build.call_args_list],
            [("M5",), ("M30",), ("H1",)],
        )
        self.assertEqual(instance.resistance_breakout_order_classes, orders)


if __name__ == "__main__":
    unittest.main()
