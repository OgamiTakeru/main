# 最新更新日時: 2026-08-29 21:21 JST

import unittest

import pandas as pd

import fCandleDataQuality as quality


def _frame(*times):
    return pd.DataFrame({"time_jp_dt": pd.to_datetime(list(times))})


class CandleDataQualityTest(unittest.TestCase):
    def test_m5_boundary_uses_five_minute_floor(self):
        completed_df_r = _frame(
            "2026-08-27 01:45:00",
            "2026-08-27 01:40:00",
            "2026-08-27 01:35:00",
        )
        validated_df_r = quality.validate_completed_history(
            completed_df_r,
            pd.Timestamp("2026-08-27 01:50:06"),
            pd.Timedelta(minutes=5),
            3,
            "M5",
            latest_boundary="M5",
        )
        self.assertEqual(
            validated_df_r.iloc[0]["time_jp_dt"],
            pd.Timestamp("2026-08-27 01:45:00"),
        )

    def test_non_m5_minute_is_rejected(self):
        completed_df_r = _frame(
            "2026-08-27 01:45:00",
            "2026-08-27 01:40:00",
            "2026-08-27 01:35:00",
        )
        with self.assertRaises(quality.CandleHistoryIntegrityError):
            quality.validate_completed_history(
                completed_df_r,
                pd.Timestamp("2026-08-27 01:52:06"),
                pd.Timedelta(minutes=5),
                3,
                "M5",
                latest_boundary="M5",
            )

    def test_stale_latest_m5_is_accepted_and_counted(self):
        completed_df_r = _frame(
            "2026-08-27 01:40:00",
            "2026-08-27 01:35:00",
            "2026-08-27 01:30:00",
        )
        validated_df_r = quality.validate_completed_history(
            completed_df_r,
            pd.Timestamp("2026-08-27 01:50:06"),
            pd.Timedelta(minutes=5),
            3,
            "M5",
            latest_boundary="M5",
        )
        stats = validated_df_r.attrs["candle_quality"]
        self.assertEqual(stats["latest_missing_bars"], 1)
        self.assertEqual(stats["missing_bars"], 1)

    def test_small_internal_gap_is_accepted_and_counted(self):
        completed_df_r = _frame(
            "2026-08-27 01:45:00",
            "2026-08-27 01:35:00",
            "2026-08-27 01:30:00",
        )
        validated_df_r = quality.validate_completed_history(
            completed_df_r,
            pd.Timestamp("2026-08-27 01:50:00"),
            pd.Timedelta(minutes=5),
            3,
            "M5",
            latest_boundary="M5",
        )
        self.assertEqual(
            validated_df_r.attrs["candle_quality"]["missing_bars"],
            1,
        )

    def test_insufficient_history_is_integrity_error(self):
        completed_df_r = _frame(
            "2026-08-27 01:45:00",
            "2026-08-27 01:40:00",
        )
        with self.assertRaises(quality.CandleHistoryIntegrityError):
            quality.validate_completed_history(
                completed_df_r,
                pd.Timestamp("2026-08-27 01:50:00"),
                pd.Timedelta(minutes=5),
                3,
                "M5",
                latest_boundary="M5",
            )

    def test_christmas_weekend_join_is_known_closure(self):
        self.assertTrue(
            quality.is_expected_market_closed_gap(
                pd.Timestamp("2023-12-23 06:58:55"),
                pd.Timestamp("2023-12-26 07:03:00"),
            )
        )

    def test_annual_gap_cannot_hide_open_market_edges(self):
        self.assertFalse(
            quality.is_expected_annual_holiday_closure_gap(
                pd.Timestamp(
                    "2023-12-22 16:30:00",
                    tz="America/New_York",
                ),
                pd.Timestamp(
                    "2023-12-25 17:30:00",
                    tz="America/New_York",
                ),
            )
        )

    def test_annual_gap_rejects_one_open_s5_outside_each_edge(self):
        close_edge = pd.Timestamp(
            "2025-12-24 16:58:55",
            tz="America/New_York",
        )
        reopen_edge = pd.Timestamp(
            "2025-12-25 17:05:00",
            tz="America/New_York",
        )
        self.assertTrue(
            quality.is_expected_annual_holiday_closure_gap(
                close_edge,
                reopen_edge,
            )
        )
        self.assertFalse(
            quality.is_expected_annual_holiday_closure_gap(
                close_edge - pd.Timedelta(seconds=5),
                reopen_edge,
            )
        )
        self.assertTrue(
            quality.is_acceptable_analysis_gap(
                close_edge - pd.Timedelta(seconds=5),
                reopen_edge,
            )
        )
        self.assertFalse(
            quality.is_expected_annual_holiday_closure_gap(
                close_edge,
                reopen_edge + pd.Timedelta(seconds=5),
            )
        )
        self.assertTrue(
            quality.is_acceptable_analysis_gap(
                close_edge,
                reopen_edge + pd.Timedelta(seconds=5),
            )
        )

    def test_analysis_gap_allows_only_fifteen_minutes_at_closure_edges(self):
        close_edge = pd.Timestamp(
            "2025-12-24 16:58:55",
            tz="America/New_York",
        )
        reopen_edge = pd.Timestamp(
            "2025-12-25 17:05:00",
            tz="America/New_York",
        )
        self.assertTrue(
            quality.is_acceptable_analysis_gap(
                close_edge - pd.Timedelta(minutes=15),
                reopen_edge + pd.Timedelta(minutes=15),
            )
        )
        self.assertFalse(
            quality.is_acceptable_analysis_gap(
                close_edge - pd.Timedelta(minutes=15, seconds=5),
                reopen_edge,
            )
        )

    def test_analysis_gap_still_rejects_an_ordinary_weekday_hole(self):
        self.assertFalse(
            quality.is_acceptable_analysis_gap(
                pd.Timestamp("2026-08-27 01:30:00"),
                pd.Timestamp("2026-08-27 01:45:00"),
            )
        )

    def test_holiday_mask_is_separate_from_regular_market_hours(self):
        holiday_noon = pd.DatetimeIndex(
            [pd.Timestamp("2025-12-25 12:00:00", tz="America/New_York")]
        )
        self.assertTrue(quality.oanda_market_open_mask(holiday_noon)[0])
        self.assertFalse(quality.oanda_coverage_open_mask(holiday_noon)[0])

    def test_historical_open_market_staleness_is_not_an_error_below_half(self):
        completed_df_r = _frame(
            "2026-08-27 01:40:00",
            "2026-08-27 01:35:00",
            "2026-08-27 01:30:00",
        )
        validated_df_r = quality.validate_completed_history(
            completed_df_r,
            pd.Timestamp("2026-08-27 01:50:00"),
            pd.Timedelta(minutes=5),
            3,
            "M5",
            latest_boundary="M5",
            stale_is_integrity=True,
        )
        self.assertEqual(
            validated_df_r.attrs["candle_quality"]["missing_bars"],
            1,
        )

    def test_short_holiday_tail_is_not_misclassified_as_corruption(self):
        latest = _frame("2025-12-25 07:10:00")
        with self.assertRaises(quality.CandleHistoryNotReady):
            quality.validate_latest_boundary(
                latest,
                pd.Timestamp("2025-12-25 08:00:00"),
                pd.Timedelta(minutes=5),
                "M5",
                stale_is_integrity=True,
            )

    def test_half_missing_history_is_rejected(self):
        completed_df_r = _frame(
            "2026-08-27 01:35:00",
            "2026-08-27 01:25:00",
            "2026-08-27 01:20:00",
        )
        with self.assertRaisesRegex(
                quality.CandleHistoryIntegrityError,
                "too many missing bars",
        ):
            quality.validate_completed_history(
                completed_df_r,
                pd.Timestamp("2026-08-27 01:50:00"),
                pd.Timedelta(minutes=5),
                3,
                "M5",
                latest_boundary="M5",
            )

    def test_decision_at_weekly_close_is_not_ready(self):
        with self.assertRaises(quality.CandleHistoryNotReady):
            quality.validate_decision_market_open(
                pd.Timestamp(
                    "2026-08-28 17:00:00",
                    tz="America/New_York",
                )
            )

    def test_christmas_weekend_gap_is_valid_inside_m5_history(self):
        completed_df_r = _frame(
            "2023-12-26 07:05:00",
            "2023-12-23 06:55:00",
            "2023-12-23 06:50:00",
        )
        validated_df_r = quality.validate_completed_history(
            completed_df_r,
            pd.Timestamp("2023-12-26 07:10:00"),
            pd.Timedelta(minutes=5),
            3,
            "M5",
            latest_boundary="M5",
        )
        self.assertEqual(len(validated_df_r), 3)


if __name__ == "__main__":
    unittest.main()
