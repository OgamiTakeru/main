# 最新更新日時: 2026-09-09 16:01 JST
"""Isolated launcher regression: importing the subject never loads credentials."""
import _bootstrap

from datetime import datetime, timezone
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch


class MainAnalysisBootstrapTest(unittest.TestCase):
    def test_failed_initial_candle_load_does_not_consume_scheduled_slot(self):
        # All application imports are stubs; the real account/broker constructors
        # and strategy modules are neither imported nor called by this test.
        stubs = {
            name: ModuleType(name)
            for name in (
                "tokens", "send_notice", "classOanda", "classPosition",
                "classOrderCreate", "fGeneric", "fAnalysis_order_Main",
                "classCandleAnalysis", "classPositionControl",
            )
        }
        broker_constructor = Mock(side_effect=AssertionError("unexpected broker construction"))
        stubs["classOanda"].Oanda = broker_constructor
        candle_constructor = Mock(side_effect=RuntimeError("candle publication unavailable"))
        stubs["classCandleAnalysis"].candleAnalysis = candle_constructor
        source = (Path(__file__).resolve().parents[1] / 'main_exe.py')
        spec = importlib.util.spec_from_file_location("isolated_main_schedule_subject", source)
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, stubs):
            spec.loader.exec_module(module)
            runner = module.main.__new__(module.main)
            runner.latest_analysis_slot_utc = None
            runner.first_exe = True
            runner.candleAnalysisClass = None
            runner.now = "test startup"
            runner.past_time_from_latest_mode1_exe = 0
            runner.positions_control_class = SimpleNamespace(refresh_startup_safety_state=Mock())
            runner.base_oa = object()
            runner.pair = "USD_JPY"
            scheduled_time = datetime(2026, 9, 9, 10, 30, 6, tzinfo=timezone.utc)

            for attempt in (1, 2):
                with self.subTest(attempt=attempt), self.assertRaisesRegex(
                    RuntimeError, "candle publication unavailable"
                ):
                    runner.mode1(analysis_time_utc=scheduled_time)
                self.assertIsNone(runner.latest_analysis_slot_utc)
                self.assertIsNone(runner.candleAnalysisClass)
                self.assertTrue(runner.first_exe)

        self.assertEqual(candle_constructor.call_count, 2)
        broker_constructor.assert_not_called()


if __name__ == "__main__":
    unittest.main()
