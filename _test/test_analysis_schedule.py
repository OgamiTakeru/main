# 最新更新日時: 2026-09-09 16:11 JST
"""Offline scheduling/ledger checks; no broker, credentials, or market data."""
import _bootstrap

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fAnalysisSchedule import AnalysisRunLedger, AnalysisScheduleError, live_decision_time


def utc(minute=30, second=0, microsecond=0):
    return datetime(2026, 9, 9, 10, minute, second, microsecond, tzinfo=timezone.utc)


class LiveDecisionTimeTest(unittest.TestCase):
    def test_h1_only_dispatches_once_an_hour_after_six_seconds(self):
        self.assertIsNone(live_decision_time(utc(0, 5), "H1"))
        self.assertEqual(live_decision_time(utc(0, 6), "H1"), utc(0))
        self.assertEqual(live_decision_time(utc(0, 29), "H1"), utc(0))
        self.assertIsNone(live_decision_time(utc(0, 30), "H1"))
        for minute in (5, 15, 30, 55):
            self.assertIsNone(live_decision_time(utc(minute, 6), "H1"))

    def test_m30_only_at_half_hour_boundaries_after_six_seconds(self):
        for minute in (0, 30):
            with self.subTest(minute=minute):
                self.assertIsNone(live_decision_time(utc(minute, 5, 999999), "M30"))
                self.assertEqual(live_decision_time(utc(minute, 6), "M30"), utc(minute))
                self.assertEqual(live_decision_time(utc(minute, 29, 999999), "M30"), utc(minute))
                self.assertIsNone(live_decision_time(utc(minute, 30), "M30"))

    def test_m5_schedule_is_independent_and_both_are_due_at_half_hour(self):
        self.assertEqual(live_decision_time(utc(35, 6), "M5"), utc(35))
        self.assertIsNone(live_decision_time(utc(35, 6), "M30"))
        self.assertEqual(live_decision_time(utc(30, 6), "M5"), utc(30))
        self.assertEqual(live_decision_time(utc(30, 6), "M30"), utc(30))

    def test_missed_slots_do_not_catch_up(self):
        self.assertIsNone(live_decision_time(utc(31, 6), "M30"))
        self.assertIsNone(live_decision_time(utc(36, 6), "M5"))
        self.assertIsNone(live_decision_time(utc(30, 45), "M30"))

    def test_aware_jst_normalizes_to_utc_and_naive_fails(self):
        jst = utc(30, 6).astimezone(timezone(timedelta(hours=9)))
        self.assertEqual(live_decision_time(jst, "M30"), utc())
        with self.assertRaises(ValueError):
            live_decision_time(datetime(2026, 9, 9, 10, 30, 6), "M30")

    def test_invalid_window_or_timeframe_fails(self):
        for kwargs in ({"delay_seconds": -1}, {"window_end_seconds": 6}, {"window_end_seconds": 61}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                live_decision_time(utc(30, 6), **kwargs)
        with self.assertRaises(ValueError):
            live_decision_time(utc(30, 6), "M7")


class AnalysisRunLedgerTest(unittest.TestCase):
    def test_h1_claim_survives_restart_without_consuming_m5_or_m30(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.json"
            ledger = AnalysisRunLedger(path)
            self.assertTrue(ledger.claim("resistance", "H1", utc(0)))
            restarted = AnalysisRunLedger(path)
            self.assertFalse(restarted.claim("resistance", "H1", utc(0)))
            self.assertTrue(restarted.claim("resistance", "M30", utc(0)))
            self.assertTrue(restarted.claim("resistance", "M5", utc(0)))
            self.assertTrue(restarted.claim("resistance", "H1", utc(0) + timedelta(hours=1)))

    def test_repeat_and_clock_rollback_are_consumed(self):
        ledger = AnalysisRunLedger()
        self.assertFalse(ledger.is_processed("resistance", "M30", utc()))
        self.assertTrue(ledger.claim("resistance", "M30", utc()))
        self.assertTrue(ledger.is_processed("resistance", "M30", utc()))
        self.assertFalse(ledger.claim("resistance", "M30", utc()))
        self.assertFalse(ledger.claim("resistance", "M30", utc(0)))
        self.assertTrue(ledger.claim("resistance", "M30", utc() + timedelta(minutes=30)))

    def test_strategy_and_timeframe_are_independent(self):
        ledger = AnalysisRunLedger()
        self.assertTrue(ledger.claim("resistance", "M30", utc()))
        self.assertTrue(ledger.claim("resistance", "M5", utc()))
        self.assertTrue(ledger.claim("flip", "M5", utc()))
        self.assertFalse(ledger.claim("resistance", "m30", utc()))

    def test_timestamps_must_be_aware_exact_boundaries(self):
        ledger = AnalysisRunLedger()
        for decision in (utc(35), utc(30, 1), utc(30, 0, 1), utc().replace(tzinfo=None)):
            with self.subTest(decision=decision), self.assertRaises(ValueError):
                ledger.claim("resistance", "M30", decision)

    def test_persisted_claim_survives_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.json"
            self.assertTrue(AnalysisRunLedger(path).claim("resistance", "M30", utc()))
            restarted = AnalysisRunLedger(path)
            self.assertTrue(restarted.is_processed("resistance", "M30", utc()))
            self.assertFalse(restarted.claim("resistance", "M30", utc()))
            self.assertEqual(list(Path(directory).glob("*.tmp")), [])

    def test_existing_instances_reload_shared_state(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.json"
            first, second = AnalysisRunLedger(path), AnalysisRunLedger(path)
            self.assertTrue(first.claim("resistance", "M30", utc()))
            self.assertFalse(second.claim("resistance", "M30", utc()))

    def test_concurrent_instances_claim_once(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.json"
            ledgers = [AnalysisRunLedger(path) for _ in range(8)]
            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(lambda ledger: ledger.claim("resistance", "M30", utc()), ledgers))
            self.assertEqual(sum(results), 1)

    def test_corrupt_file_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.json"
            malformed = "{broken"
            path.write_text(malformed, encoding="utf-8")
            ledger = AnalysisRunLedger(path)
            with self.assertRaises(AnalysisScheduleError):
                ledger.is_processed("resistance", "M30", utc())
            with self.assertRaises(AnalysisScheduleError):
                ledger.claim("resistance", "M30", utc())
            self.assertEqual(path.read_text(encoding="utf-8"), malformed)

    def test_invalid_watermark_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.json"
            malformed = json.dumps({"version": 1, "watermarks": {"resistance|M30": utc(35).isoformat()}})
            path.write_text(malformed, encoding="utf-8")
            with self.assertRaises(AnalysisScheduleError):
                AnalysisRunLedger(path).claim("resistance", "M30", utc())
            self.assertEqual(path.read_text(encoding="utf-8"), malformed)

    def test_unreadable_state_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.json"
            path.mkdir()
            with self.assertRaises(AnalysisScheduleError):
                AnalysisRunLedger(path).claim("resistance", "M30", utc())
            self.assertTrue(path.is_dir())

    def test_failed_replace_does_not_claim_and_archives_temporary(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.json"
            ledger = AnalysisRunLedger(path)
            from fAnalysisSchedule import os as schedule_os

            real_replace = schedule_os.replace

            def replace_except_ledger(source, destination):
                if Path(destination) == path:
                    raise OSError("simulated failed commit")
                return real_replace(source, destination)

            with patch("fAnalysisSchedule.os.replace", side_effect=replace_except_ledger):
                with self.assertRaises(AnalysisScheduleError):
                    ledger.claim("resistance", "M30", utc())
            self.assertFalse(path.exists())
            self.assertFalse(ledger.is_processed("resistance", "M30", utc()))
            self.assertEqual(list(Path(directory).glob("*.tmp")), [])
            self.assertEqual(len(list((Path(directory) / "archive").iterdir())), 1)


if __name__ == "__main__":
    unittest.main()
