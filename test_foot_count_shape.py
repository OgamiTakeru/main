import unittest

import pandas as pd

import fGeneric as gene
from fFootCountShape import (
    attach_line_wick_context,
    foot_count2_shape_context,
    latest_two_candle_shape_context,
)


class FootCount2ShapeTest(unittest.TestCase):
    @staticmethod
    def _frame(future_high=999.0):
        times = pd.date_range("2025-01-06 09:00:00", periods=9, freq="5min")
        rows = []
        for timestamp in times:
            rows.append({
                "time_jp_dt": timestamp,
                "open": 100.000,
                "close": 100.000,
                "high": 100.010,
                "low": 99.990,
            })
        rows[6].update(
            open=100.000,
            close=100.010,
            high=100.015,
            low=99.995,
        )
        rows[7].update(
            open=100.010,
            close=100.005,
            high=100.020,
            low=100.000,
        )
        # The decision-time candle must never affect the features.
        rows[8].update(high=future_high, low=1.0, close=500.0)
        return pd.DataFrame(rows)

    @staticmethod
    def _peak():
        return {
            "count": 2,
            "direction": 1,
            "oldest_time_jp": "2025/01/06 09:30:00",
            "latest_time_jp": "2025/01/06 09:35:00",
        }

    def test_completed_m5_only_and_a_normalized_features(self):
        pair = gene.currency_pair("USD_JPY")
        decision = pd.Timestamp("2025-01-06 09:40:00")
        first = foot_count2_shape_context(
            self._frame(999.0), self._peak(), decision, pair
        )
        mutated_future = foot_count2_shape_context(
            self._frame(9999.0), self._peak(), decision, pair
        )
        self.assertTrue(first["valid"])
        self.assertEqual(first["shape"], "REJECTION")
        self.assertAlmostEqual(first["a_range_pips"], 2.0)
        self.assertAlmostEqual(first["reversal_strength_A"], 0.75)
        self.assertAlmostEqual(first["prior_impulse_retrace_ratio"], 0.75)
        self.assertEqual(
            first["reversal_strength_A"],
            mutated_future["reversal_strength_A"],
        )
        self.assertAlmostEqual(first["first_range_A"], 1.0)
        self.assertEqual(first["candle_sequence"], "BULL_BEAR")
        self.assertEqual(first["formation_minutes"], 10.0)

    def test_candidate_line_wick_overshoot_is_separate(self):
        pair = gene.currency_pair("USD_JPY")
        base = foot_count2_shape_context(
            self._frame(),
            self._peak(),
            pd.Timestamp("2025-01-06 09:40:00"),
            pair,
        )
        line = attach_line_wick_context(
            base,
            line_price=100.015,
            line_side="upper",
            pair=pair,
        )
        self.assertAlmostEqual(line["line_wick_overshoot_A"], 0.25)
        self.assertTrue(line["line_rejection"])
        self.assertEqual(line["line_shape"], "REJECTION")

    def test_h1_pair_uses_only_fully_completed_h1(self):
        pair = gene.currency_pair("USD_JPY")
        times = pd.date_range("2025-01-06 00:00:00", periods=8, freq="1h")
        rows = [
            {
                "time_jp_dt": timestamp,
                "open": 100.0,
                "close": 100.05,
                "high": 100.08,
                "low": 99.98,
            }
            for timestamp in times
        ]
        normal = latest_two_candle_shape_context(
            pd.DataFrame(rows),
            pd.Timestamp("2025-01-06 07:30:00"),
            pair,
            direction=1,
            timeframe_minutes=60,
        )
        # 07:00 is still forming at the 07:30 decision and must not affect A
        # or any public shape feature.
        rows[-1].update(open=1.0, close=999.0, high=999.0, low=1.0)
        mutated_future = latest_two_candle_shape_context(
            pd.DataFrame(rows),
            pd.Timestamp("2025-01-06 07:30:00"),
            pair,
            direction=1,
            timeframe_minutes=60,
        )
        self.assertTrue(normal["valid"])
        self.assertEqual(normal["source_last_time"], pd.Timestamp("2025-01-06 06:00:00"))
        for field in normal:
            if field.startswith("_"):
                continue
            self.assertEqual(normal[field], mutated_future[field], field)
        self.assertEqual(normal["timeframe_minutes"], 60)
        self.assertFalse(normal["actual_foot_count2"])

        just_before_close = latest_two_candle_shape_context(
            pd.DataFrame(rows),
            pd.Timestamp("2025-01-06 07:59:59"),
            pair,
            direction=1,
            timeframe_minutes=60,
        )
        at_close = latest_two_candle_shape_context(
            pd.DataFrame(rows),
            pd.Timestamp("2025-01-06 08:00:00"),
            pair,
            direction=1,
            timeframe_minutes=60,
        )
        self.assertEqual(just_before_close["source_last_time"], pd.Timestamp("2025-01-06 06:00:00"))
        self.assertEqual(at_close["source_last_time"], pd.Timestamp("2025-01-06 07:00:00"))

    def test_h1_pair_rejects_unknown_open_market_gap(self):
        pair = gene.currency_pair("USD_JPY")
        times = pd.date_range("2025-01-07 09:00:00", periods=8, freq="1h")
        frame = pd.DataFrame(
            {
                "time_jp_dt": times.delete(2),
                "open": 100.0,
                "close": 100.01,
                "high": 100.02,
                "low": 99.99,
            }
        )
        context = latest_two_candle_shape_context(
            frame,
            pd.Timestamp("2025-01-07 17:00:00"),
            pair,
            direction=1,
            timeframe_minutes=60,
        )
        self.assertFalse(context["valid"])
        self.assertEqual(context["reason"], "unknown_gap_in_a_lookback")

    def test_h1_daily_pause_label_is_not_treated_as_closed_bar(self):
        pair = gene.currency_pair("USD_JPY")
        # 07:00 JST is 17:00 New York on this date.  Although the H1 label
        # starts in the daily pause, most of that candle is tradable time, so
        # omitting the whole candle must be treated as an unknown data gap.
        times = pd.date_range("2025-01-08 02:00:00", periods=8, freq="1h")
        frame = pd.DataFrame(
            {
                "time_jp_dt": times.delete(5),
                "open": 100.0,
                "close": 100.01,
                "high": 100.02,
                "low": 99.99,
            }
        )
        context = latest_two_candle_shape_context(
            frame,
            pd.Timestamp("2025-01-08 10:00:00"),
            pair,
            direction=1,
            timeframe_minutes=60,
        )
        self.assertFalse(context["valid"])
        self.assertEqual(context["reason"], "unknown_gap_in_pattern_source")

    def test_h1_known_christmas_closure_is_allowed(self):
        pair = gene.currency_pair("USD_JPY")
        times = pd.DatetimeIndex(
            [
                "2025-12-25 03:00:00",
                "2025-12-25 04:00:00",
                "2025-12-25 05:00:00",
                "2025-12-25 06:00:00",
                "2025-12-25 07:00:00",
                "2025-12-26 07:00:00",
                "2025-12-26 08:00:00",
            ]
        )
        frame = pd.DataFrame(
            {
                "time_jp_dt": times,
                "open": 100.0,
                "close": 100.01,
                "high": 100.02,
                "low": 99.99,
            }
        )
        context = latest_two_candle_shape_context(
            frame,
            pd.Timestamp("2025-12-26 09:00:00"),
            pair,
            direction=1,
            timeframe_minutes=60,
        )
        self.assertTrue(context["valid"], context["reason"])

    def test_m5_known_christmas_closure_is_allowed(self):
        pair = gene.currency_pair("USD_JPY")
        times = pd.DatetimeIndex(
            [
                "2025-12-25 06:50:00",
                "2025-12-25 06:55:00",
                "2025-12-25 07:00:00",
                "2025-12-25 07:05:00",
                "2025-12-25 07:10:00",
                "2025-12-26 07:00:00",
                "2025-12-26 07:05:00",
            ]
        )
        frame = pd.DataFrame(
            {
                "time_jp_dt": times,
                "open": 100.0,
                "close": 100.01,
                "high": 100.02,
                "low": 99.99,
            }
        )
        peak = {
            "count": 2,
            "direction": 1,
            "oldest_time_jp": "2025-12-26 07:00:00",
            "latest_time_jp": "2025-12-26 07:05:00",
        }
        context = foot_count2_shape_context(
            frame,
            peak,
            pd.Timestamp("2025-12-26 07:10:00"),
            pair,
            timeframe_minutes=5,
        )
        self.assertTrue(context["valid"], context["reason"])

    def test_short_holiday_eve_open_market_gap_is_rejected(self):
        pair = gene.currency_pair("USD_JPY")
        times = pd.date_range("2025-12-25 06:10:00", periods=8, freq="5min")
        frame = pd.DataFrame(
            {
                "time_jp_dt": times.delete(4),
                "open": 100.0,
                "close": 100.01,
                "high": 100.02,
                "low": 99.99,
            }
        )
        context = latest_two_candle_shape_context(
            frame,
            pd.Timestamp("2025-12-25 06:50:00"),
            pair,
            direction=1,
            timeframe_minutes=5,
        )
        self.assertFalse(context["valid"])
        self.assertEqual(context["reason"], "unknown_gap_in_a_lookback")


if __name__ == "__main__":
    unittest.main()
