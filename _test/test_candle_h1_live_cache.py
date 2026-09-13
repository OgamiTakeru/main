# 最新更新日時: 2026-09-09 16:13 JST
"""Offline contracts for native H1 cache and decision-relative peak metadata."""
import _bootstrap

from types import SimpleNamespace
import unittest
from unittest.mock import patch

import pandas as pd

from classCandleAnalysis import H1_ANALYSIS_BARS, candleAnalysis
import fCandleDataQuality as candle_quality
import fGeneric as gene


class LiveH1CacheTest(unittest.TestCase):
    def setUp(self):
        old_cache = candleAnalysis.latest_live_h1_cache
        self.addCleanup(setattr, candleAnalysis, "latest_live_h1_cache", old_cache)
        candleAnalysis.latest_live_h1_cache = None
        self.analysis = candleAnalysis.__new__(candleAnalysis)
        self.analysis.analysis_mode = "live"
        self.analysis.pair = "USD_JPY"
        self.analysis.base_oa = SimpleNamespace(accountID="offline", environment="practice")
        self.analysis.decision_time = pd.Timestamp("2026-09-09 12:00:00")
        self.analysis.current_price = 150.0
        times = pd.date_range(
            end="2026-09-09 11:00:00", periods=H1_ANALYSIS_BARS, freq="h",
        )[::-1]
        completed = pd.DataFrame({
            "time_jp": times.strftime("%Y/%m/%d %H:%M:%S"),
            "open": 150.0, "high": 150.1, "low": 149.9, "close": 150.0,
            "complete": True,
        })
        self.analysis.h1_original_df_r = completed.copy()
        self.analysis.peaks_class_hour = SimpleNamespace(
            source_granularity="H1", analysis_df_r=completed.copy(),
            current_price=150.0, pair=gene.currency_pair("USD_JPY"),
            latest_peak_price=150.0,
            peaks_original=[{"count": 2, "latest_time_jp": "2026/09/09 11:00:00"}],
        )
        self.analysis.candle_meta_class_hour = object()
        quality_patch = patch.object(
            candleAnalysis, "validate_completed_history_for_context",
            return_value=completed,
        )
        self.quality = quality_patch.start()
        self.addCleanup(quality_patch.stop)

    def test_one_snapshot_reused_through_55_minutes_not_next_hour(self):
        self.analysis.remember_live_h1_analysis()
        cached = candleAnalysis.latest_live_h1_cache
        self.assertIsNotNone(cached)
        for minute in range(0, 60, 5):
            self.analysis.decision_time = pd.Timestamp(f"2026-09-09 12:{minute:02}:00")
            self.assertIs(self.analysis.cached_live_h1_analysis(), cached)
        self.analysis.decision_time = pd.Timestamp("2026-09-09 13:00:00")
        self.assertIsNone(self.analysis.cached_live_h1_analysis())
        self.analysis.decision_time = pd.Timestamp("2026-09-09 11:55:00")
        self.assertIsNone(self.analysis.cached_live_h1_analysis())
        self.assertEqual(cached.completed_boundary, pd.Timestamp("2026-09-09 12:00:00"))

    def test_cache_does_not_cross_pair_source_account_environment_or_mode(self):
        self.analysis.remember_live_h1_analysis()
        for owner, attribute, changed in (
            (self.analysis, "pair", "EUR_USD"),
            (self.analysis, "base_oa", SimpleNamespace(accountID="offline", environment="practice")),
            (self.analysis.base_oa, "accountID", "other"),
            (self.analysis.base_oa, "environment", "live"),
            (self.analysis, "analysis_mode", "inspection"),
            (self.analysis.peaks_class_hour, "source_granularity", "M30"),
        ):
            original = getattr(owner, attribute)
            with self.subTest(attribute=attribute):
                setattr(owner, attribute, changed)
                self.assertIsNone(self.analysis.cached_live_h1_analysis())
                setattr(owner, attribute, original)

    def test_incomplete_latest_candle_not_cached_as_current_hour(self):
        self.analysis.h1_original_df_r.loc[0, "complete"] = False
        self.analysis.remember_live_h1_analysis()
        self.assertIsNone(candleAnalysis.latest_live_h1_cache)
        self.quality.assert_not_called()

    def test_mismatched_or_future_peak_history_not_cached(self):
        self.analysis.peaks_class_hour.analysis_df_r.loc[0, "time_jp"] = "2026/09/09 12:00:00"
        self.analysis.remember_live_h1_analysis()
        self.assertIsNone(candleAnalysis.latest_live_h1_cache)

    def test_invalid_history_not_cached(self):
        self.quality.side_effect = candle_quality.CandleHistoryIntegrityError("unknown gap")
        self.analysis.remember_live_h1_analysis()
        self.assertIsNone(candleAnalysis.latest_live_h1_cache)

    def test_missing_completion_flag_not_cached(self):
        self.analysis.h1_original_df_r.drop(columns="complete", inplace=True)
        self.analysis.remember_live_h1_analysis()
        self.assertIsNone(candleAnalysis.latest_live_h1_cache)

    def test_known_closure_quality_policy_kept_without_relabelling_stale_hour(self):
        self.analysis.remember_live_h1_analysis()
        self.assertTrue(self.quality.call_args.kwargs["allow_latest_known_closure"])
        cached = candleAnalysis.latest_live_h1_cache
        self.analysis.decision_time = pd.Timestamp("2026-09-09 13:00:00")
        self.analysis.remember_live_h1_analysis()
        self.assertIs(candleAnalysis.latest_live_h1_cache, cached)
        self.assertIsNone(self.analysis.cached_live_h1_analysis())

    def test_cached_h1_refreshes_price_and_decision_metadata_without_rebuilding_peaks(self):
        self.analysis.remember_live_h1_analysis()
        peak_analysis = candleAnalysis.latest_live_h1_cache.peaks_class
        self.analysis.current_price = 150.05
        self.analysis.decision_time = pd.Timestamp("2026-09-09 12:35:00")
        candleAnalysis.refresh_cached_peak_price(peak_analysis, self.analysis.current_price)
        candleAnalysis.normalize_peak_metadata(peak_analysis, self.analysis.decision_time)
        self.assertTrue(candleAnalysis.peaks_match_completed(
            peak_analysis, self.analysis.h1_original_df_r,
            self.analysis.current_price, gene.currency_pair("USD_JPY"),
        ))
        self.assertEqual(peak_analysis.decision_time, self.analysis.decision_time)
        self.assertEqual(peak_analysis.peaks_original[0]["latest_price"], 150.05)
        self.assertEqual(peak_analysis.peaks_original[0]["foot_count"], 2)
        self.assertEqual(peak_analysis.peaks_latest, [])
        self.assertIs(self.analysis.cached_live_h1_analysis().peaks_class, peak_analysis)


if __name__ == "__main__":
    unittest.main()
