import unittest

import pandas as pd

import fGeneric as gene
from fFootCountShape import attach_line_wick_context, foot_count2_shape_context


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


if __name__ == "__main__":
    unittest.main()
