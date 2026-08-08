import unittest

import pandas as pd

from count2_resistance_sweep import make_stair_analysis, stair_analysis_columns
from fStairTrend import detect_m5_stair_trend


def foot(direction, count, start, end, oldest, latest):
    return {
        "direction": direction,
        "count": count,
        "gap": abs(end - start),
        "oldest_body_peak_price": start,
        "latest_body_peak_price": end,
        "oldest_time_jp": oldest,
        "latest_time_jp": latest,
    }


def completed_ranges(base=150.0):
    return pd.DataFrame(
        [
            {"high": base + 0.01, "low": base - 0.01}
            for _ in range(12)
        ]
    )


def confirmed_up_peaks():
    chronological = [
        foot(1, 5, 150.00, 150.08, "2026/08/07 16:10:00", "2026/08/07 16:35:00"),
        foot(-1, 2, 150.08, 150.05, "2026/08/07 16:35:00", "2026/08/07 16:40:00"),
        foot(1, 4, 150.05, 150.14, "2026/08/07 16:40:00", "2026/08/07 17:00:00"),
        foot(-1, 3, 150.14, 150.10, "2026/08/07 17:00:00", "2026/08/07 17:15:00"),
        foot(1, 2, 150.10, 150.18, "2026/08/07 17:15:00", "2026/08/07 17:20:00"),
    ]
    return list(reversed(chronological))


class StairTrendDetectionTest(unittest.TestCase):
    def setUp(self):
        self.peaks = confirmed_up_peaks()

    def test_confirmed_up_stair_exposes_each_leg_for_analysis(self):
        result = detect_m5_stair_trend(
            self.peaks,
            "USD_JPY",
            completed_ranges(),
        )

        self.assertEqual(result["state"], "UP_CONFIRMED")
        self.assertTrue(result["candidate_passed"])
        self.assertTrue(result["confirmed_passed"])
        self.assertEqual(result["foot_count_sequence"], [5, 2, 4, 3, 2])
        self.assertEqual(result["first_pullback_foot_count"], 2)
        self.assertEqual(result["second_pullback_foot_count"], 3)
        self.assertAlmostEqual(result["first_pullback_ratio"], 0.375)
        self.assertAlmostEqual(result["second_pullback_ratio"], 0.4444)
        self.assertAlmostEqual(result["second_impulse_break_pips"], 6.0)
        self.assertAlmostEqual(result["third_impulse_break_pips"], 4.0)
        self.assertAlmostEqual(result["first_structure_progress_pips"], 5.0)
        self.assertAlmostEqual(result["second_structure_progress_pips"], 5.0)

    def test_failed_threshold_still_keeps_raw_analysis_values(self):
        peaks = [dict(value) for value in self.peaks]
        first_pullback = peaks[-2]
        first_pullback["latest_body_peak_price"] = 150.01
        first_pullback["gap"] = 0.07

        result = detect_m5_stair_trend(
            peaks,
            "USD_JPY",
            completed_ranges(),
        )

        self.assertEqual(result["state"], "UP_CANDIDATE")
        self.assertTrue(result["candidate_passed"])
        self.assertFalse(result["confirmed_passed"])
        self.assertIn("pullback_ratio", result["confirmed_failed_conditions"])
        self.assertAlmostEqual(result["first_pullback_ratio"], 0.875)
        self.assertEqual(result["first_pullback_foot_count"], 2)

    def test_count2_latest_impulse_is_allowed_while_older_impulses_need_three(self):
        accepted = detect_m5_stair_trend(
            self.peaks,
            "USD_JPY",
            completed_ranges(),
        )
        rejected_peaks = [dict(value) for value in self.peaks]
        rejected_peaks[-1]["count"] = 2
        rejected = detect_m5_stair_trend(
            rejected_peaks,
            "USD_JPY",
            completed_ranges(),
        )

        self.assertTrue(accepted["confirmed_passed"])
        self.assertTrue(rejected["candidate_passed"])
        self.assertFalse(rejected["confirmed_passed"])
        self.assertIn(
            "completed_impulse_foot_count",
            rejected["confirmed_failed_conditions"],
        )


class StairValidationOutputTest(unittest.TestCase):
    def test_flat_columns_and_selected_event_summary_are_created(self):
        context = detect_m5_stair_trend(
            confirmed_up_peaks(),
            "USD_JPY",
            completed_ranges(),
        )
        # Use an explicit context so the CSV-shaping test stays independent
        # from unittest lifecycle details.
        context.update(
            {
                "state": "UP_CONFIRMED",
                "direction": 1,
                "first_pullback_ratio": 0.375,
                "second_pullback_ratio": 0.4444,
                "first_pullback_foot_count": 2,
                "second_pullback_foot_count": 3,
                "candidate_passed": True,
                "confirmed_passed": True,
                "dominance_ratio": 2.5,
                "criteria": {"pullback_ratio": True},
            }
        )
        columns = stair_analysis_columns(context, peak_direction=1)
        row = {
            "event_id": "USD_JPY_20260807172000",
            "current_policy_predict_selected": True,
            "candidate_result": "tp",
            "filled": True,
            "trade_result_pips": 8.0,
            "result_r": 1.2,
            "max_favorable_pips_before_exit": 9.0,
            "max_adverse_pips_before_exit": -2.0,
            **columns,
        }

        summary = make_stair_analysis(pd.DataFrame([row]), min_group_size=1)

        self.assertTrue(columns["m5_stair_would_block_predict_reversal"])
        all_row = summary[summary["group_type"] == "all_selected"].iloc[0]
        self.assertEqual(all_row["selected_event_count"], 1)
        self.assertEqual(all_row["tp_count"], 1)


if __name__ == "__main__":
    unittest.main()
