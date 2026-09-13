# 最新更新日時: 2026-09-09 15:55 JST
"""Offline contracts for the live native-M30 cache; no broker construction."""
import _bootstrap

from types import SimpleNamespace
import unittest
from unittest.mock import patch

import pandas as pd

from classCandleAnalysis import M30_ANALYSIS_BARS, candleAnalysis
import fCandleDataQuality as candle_quality
import fGeneric as gene


class LiveM30CacheTest(unittest.TestCase):
    def setUp(self):
        old_cache = candleAnalysis.latest_live_m30_cache
        self.addCleanup(setattr, candleAnalysis, "latest_live_m30_cache", old_cache)
        candleAnalysis.latest_live_m30_cache = None
        self.analysis = candleAnalysis.__new__(candleAnalysis)
        self.analysis.analysis_mode = "live"
        self.analysis.pair = "USD_JPY"
        self.analysis.base_oa = SimpleNamespace(accountID="offline", environment="practice")
        self.analysis.decision_time = pd.Timestamp("2026-09-09 12:30:00")
        self.analysis.current_price = 150.0
        self.analysis.m30_uses_h1_fallback = False
        times = pd.date_range(
            end="2026-09-09 12:00:00", periods=M30_ANALYSIS_BARS, freq="30min",
        )[::-1]
        completed = pd.DataFrame({
            "time_jp": times.strftime("%Y/%m/%d %H:%M:%S"),
            "open": 150.0, "high": 150.1, "low": 149.9, "close": 150.0,
            "complete": True,
        })
        self.analysis.m30_original_df_r = completed.copy()
        self.analysis.peaks_class_m30 = SimpleNamespace(
            source_granularity="M30", analysis_df_r=completed.copy(),
            current_price=150.0, pair=gene.currency_pair("USD_JPY"),
        )
        self.analysis.candle_meta_class_m30 = object()
        # Test cache admission itself; history coverage has its own test module.
        quality_patch = patch.object(
            candleAnalysis, "validate_completed_history_for_context",
            return_value=completed,
        )
        self.quality = quality_patch.start()
        self.addCleanup(quality_patch.stop)

    def test_one_snapshot_reused_only_inside_its_half_hour(self):
        self.analysis.remember_live_m30_analysis()
        cached = candleAnalysis.latest_live_m30_cache
        self.assertIsNotNone(cached)
        for minute in (30, 35, 40, 45, 50, 55):
            self.analysis.decision_time = pd.Timestamp(f"2026-09-09 12:{minute}:00")
            self.assertIs(self.analysis.cached_live_m30_analysis(), cached)
        self.analysis.decision_time = pd.Timestamp("2026-09-09 13:00:00")
        self.assertIsNone(self.analysis.cached_live_m30_analysis())
        self.analysis.decision_time = pd.Timestamp("2026-09-09 12:00:00")
        self.assertIsNone(self.analysis.cached_live_m30_analysis())
        self.assertEqual(cached.completed_boundary, pd.Timestamp("2026-09-09 12:30:00"))

    def test_cache_does_not_cross_pair_client_account_environment_or_mode(self):
        self.analysis.remember_live_m30_analysis()
        for owner, attribute, changed in (
            (self.analysis, "pair", "EUR_USD"),
            (self.analysis, "base_oa", SimpleNamespace(accountID="offline", environment="practice")),
            (self.analysis.base_oa, "accountID", "other"),
            (self.analysis.base_oa, "environment", "live"),
            (self.analysis, "analysis_mode", "inspection"),
            (self.analysis.peaks_class_m30, "source_granularity", "H1"),
        ):
            original = getattr(owner, attribute)
            with self.subTest(attribute=attribute):
                setattr(owner, attribute, changed)
                self.assertIsNone(self.analysis.cached_live_m30_analysis())
                setattr(owner, attribute, original)

    def test_incomplete_latest_candle_is_not_cached_under_new_boundary(self):
        self.analysis.m30_original_df_r.loc[0, "complete"] = False
        self.analysis.remember_live_m30_analysis()
        self.assertIsNone(candleAnalysis.latest_live_m30_cache)
        self.quality.assert_not_called()

    def test_future_or_different_peak_history_is_not_cached(self):
        self.analysis.peaks_class_m30.analysis_df_r.loc[0, "time_jp"] = "2026/09/09 12:30:00"
        self.analysis.remember_live_m30_analysis()
        self.assertIsNone(candleAnalysis.latest_live_m30_cache)

    def test_missing_completion_flag_is_not_cached(self):
        self.analysis.m30_original_df_r.drop(columns="complete", inplace=True)
        self.analysis.remember_live_m30_analysis()
        self.assertIsNone(candleAnalysis.latest_live_m30_cache)

    def test_invalid_history_is_not_cached(self):
        self.quality.side_effect = candle_quality.CandleHistoryIntegrityError("unknown gap")
        self.analysis.remember_live_m30_analysis()
        self.assertIsNone(candleAnalysis.latest_live_m30_cache)

    def test_h1_fallback_is_not_cached_as_native_m30(self):
        self.analysis.m30_uses_h1_fallback = True
        self.analysis.remember_live_m30_analysis()
        self.assertIsNone(candleAnalysis.latest_live_m30_cache)

    def test_original_frame_is_saved_by_value(self):
        self.analysis.remember_live_m30_analysis()
        self.analysis.m30_original_df_r.loc[0, "close"] = 999.0
        self.assertEqual(candleAnalysis.latest_live_m30_cache.original_df_r.loc[0, "close"], 150.0)


if __name__ == "__main__":
    unittest.main()
