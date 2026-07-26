import unittest

import numpy as np
import pandas as pd

from classCandlePeaks import PeaksClass
from classInspection import Inspection


class InspectionOptimizationTest(unittest.TestCase):
    @staticmethod
    def legacy_large_body_result(frame, large_threshold, very_large_threshold):
        sorted_frame = frame.sort_values(by="body_abs", ascending=False)
        max_body = sorted_frame["body_abs"].max()
        include_very_large = False
        for _, row in sorted_frame.iterrows():
            if row["body"] >= very_large_threshold:
                include_very_large = True
                break
            include_very_large = False

        counter = 0
        for _, _row in sorted_frame.iterrows():
            if max_body > large_threshold:
                counter += 1
        include_large = counter / len(sorted_frame) >= 0.65
        return {
            "include_large": include_large,
            "include_very_large": include_very_large,
            "highest": sorted_frame["high"].max(),
            "lowest": sorted_frame["low"].min(),
        }

    def test_numpy_large_body_result_matches_legacy_loop(self):
        generator = np.random.default_rng(42)
        peak_class = PeaksClass.__new__(PeaksClass)
        peak_class.dependence_large_body_criteria = 0.001
        peak_class.dependence_very_large_body_criteria = 0.002
        peak_class.minimum = 0.0000001

        for size in (1, 2, 5, 20, 100):
            body = generator.normal(0, 0.0015, size)
            frame = pd.DataFrame(
                {
                    "body": body,
                    "body_abs": np.abs(body),
                    "high": 1.1 + generator.random(size) * 0.01,
                    "low": 1.1 - generator.random(size) * 0.01,
                }
            )
            expected = self.legacy_large_body_result(
                frame,
                peak_class.dependence_large_body_criteria,
                peak_class.dependence_very_large_body_criteria,
            )
            actual = peak_class.check_large_body_in_peak({"data": frame})
            self.assertEqual(actual["include_large"], expected["include_large"])
            self.assertEqual(
                actual["include_very_large"],
                expected["include_very_large"],
            )
            self.assertEqual(actual["highest"], expected["highest"])
            self.assertEqual(actual["lowest"], expected["lowest"])

    def test_higher_timeframe_cache_key_changes_only_with_candle_set(self):
        frame = pd.DataFrame(
            {
                "time_jp_dt": pd.to_datetime(
                    ["2026/01/01 12:00:00", "2026/01/01 11:00:00"]
                )
            }
        )
        key = Inspection.analysis_cache_key(frame)
        cached_value = ("peaks", "meta")
        cache = (key, cached_value)

        self.assertIs(
            Inspection.cached_analysis_value(cache, key),
            cached_value,
        )
        next_frame = frame.copy()
        next_frame.loc[0, "time_jp_dt"] = pd.Timestamp("2026/01/01 13:00:00")
        self.assertIsNone(
            Inspection.cached_analysis_value(
                cache,
                Inspection.analysis_cache_key(next_frame),
            )
        )


if __name__ == "__main__":
    unittest.main()
