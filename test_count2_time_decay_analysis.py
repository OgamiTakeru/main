import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

import fGeneric as gene
from count2_resistance_sweep import LimitPathInspector
from count2_time_decay_analysis import (
    MetricState,
    _discover_grid_paths,
    _load_last_reach,
    _metrics_at_cutoffs,
    _policy_condition_id,
    _policy_condition_ids,
    fill_delay_bucket,
    last_reach_bucket,
)


def _inspector(rows):
    inspector = object.__new__(LimitPathInspector)
    inspector.pair = gene.currency_pair("USD_JPY")
    inspector.times = np.asarray([row[0] for row in rows], dtype="datetime64[ns]")
    inspector.opens = np.asarray([row[1] for row in rows], dtype=float)
    inspector.closes = np.asarray([row[2] for row in rows], dtype=float)
    inspector.highs = np.asarray([row[3] for row in rows], dtype=float)
    inspector.lows = np.asarray([row[4] for row in rows], dtype=float)
    return inspector


class TimeDecayMetricTest(unittest.TestCase):
    def test_metric_state_keeps_censored_out_of_expectancy(self):
        state = MetricState()
        state.add(complete=True, result_pips=2.0, mfe_pips=3.0, mae_pips=-1.0)
        state.add(complete=True, result_pips=-1.0, mfe_pips=1.0, mae_pips=-2.0)
        state.add(complete=False, result_pips=None)

        values = state.values()
        self.assertEqual(values["total_count"], 3)
        self.assertEqual(values["complete_count"], 2)
        self.assertEqual(values["censored_count"], 1)
        self.assertAlmostEqual(values["expectancy_pips"], 0.5)
        self.assertAlmostEqual(values["positive_rate"], 0.5)

    def test_metric_state_uses_separate_mfe_mae_denominators(self):
        state = MetricState()
        state.add(complete=True, result_pips=2.0, mfe_pips=None, mae_pips=-1.0)
        state.add(complete=True, result_pips=1.0, mfe_pips=None, mae_pips=None)

        values = state.values()
        self.assertEqual(values["mfe_count"], 0)
        self.assertEqual(values["mae_count"], 1)
        self.assertTrue(np.isnan(values["average_mfe_pips"]))
        self.assertAlmostEqual(values["average_mae_pips"], -1.0)

    def test_time_buckets_are_left_closed(self):
        self.assertEqual(fill_delay_bucket(0), "0-5m")
        self.assertEqual(fill_delay_bucket(5), "5-10m")
        self.assertEqual(fill_delay_bucket(60), "60m+")
        self.assertEqual(last_reach_bucket(120), "120-240m")
        self.assertEqual(last_reach_bucket(None), "UNKNOWN")


class FutureSafetyTest(unittest.TestCase):
    def test_cutoff_after_requested_end_is_censored(self):
        start = pd.Timestamp("2025-01-06 09:00:00")
        rows = []
        for seconds in range(0, 20 * 60, 5):
            timestamp = start + pd.Timedelta(seconds=seconds)
            price = 150.0 + seconds / 60000.0
            rows.append((timestamp, price, price, price + 0.001, price - 0.001))
        inspector = _inspector(rows)

        values = _metrics_at_cutoffs(
            inspector,
            start=start,
            cutoffs={5: start + pd.Timedelta(minutes=5), 15: start + pd.Timedelta(minutes=15)},
            entry_price=150.0,
            direction=1,
            spread_pips=0.0,
            requested_end=start + pd.Timedelta(minutes=10),
        )

        self.assertTrue(values[5][0])
        self.assertFalse(values[15][0])
        self.assertIsNone(values[15][1])

    def test_unknown_s5_gap_is_censored(self):
        start = pd.Timestamp("2025-01-06 09:00:00")
        rows = [
            (start, 150.0, 150.0, 150.001, 149.999),
            (start + pd.Timedelta(seconds=5), 150.0, 150.0, 150.001, 149.999),
            (start + pd.Timedelta(seconds=15), 150.0, 150.0, 150.001, 149.999),
        ]
        inspector = _inspector(rows)

        values = _metrics_at_cutoffs(
            inspector,
            start=start,
            cutoffs={1: start + pd.Timedelta(minutes=1)},
            entry_price=150.0,
            direction=1,
            spread_pips=0.0,
            requested_end=start + pd.Timedelta(minutes=2),
        )

        self.assertFalse(values[1][0])

    def test_non_open_fill_does_not_use_prefill_favorable_extreme(self):
        start = pd.Timestamp("2025-01-06 09:00:00")
        inspector = _inspector(
            [(start, 150.0, 150.01, 150.10, 149.99)]
        )

        values = _metrics_at_cutoffs(
            inspector,
            start=start,
            cutoffs={5: start + pd.Timedelta(seconds=5)},
            entry_price=150.0,
            direction=1,
            spread_pips=0.0,
            requested_end=start + pd.Timedelta(minutes=1),
            fill_at_bar_open=False,
        )

        self.assertTrue(values[5][0])
        self.assertAlmostEqual(values[5][2], 1.0)


class ArtifactDiscoveryTest(unittest.TestCase):
    def test_completed_manifest_selects_existing_grid_paths(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            grid = root / "count2_target_grid_paths_USD_JPY_20250101_20250102_gabc.csv"
            grid.write_text("event_id\n", encoding="utf-8")
            manifest = root / "count2_target_grid_manifest_USD_JPY_20250101_20250102_gabc.json"
            manifest.write_text(
                "{" +
                '"status":"complete","pair":"USD_JPY",' +
                '"start":"2025-01-01 00:00:00","end":"2025-01-02 00:00:00",' +
                '"outputs":{"paths":"' + str(grid).replace("\\", "\\\\") + '"}}',
                encoding="utf-8",
            )

            result = _discover_grid_paths(
                root,
                "USD_JPY",
                pd.Timestamp("2025-01-01").to_pydatetime(),
                pd.Timestamp("2025-01-02").to_pydatetime(),
            )

        self.assertEqual(result, grid)

    def test_unmanifested_grid_paths_are_not_used_as_fallback(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            grid = root / "count2_target_grid_paths_USD_JPY_20250101_20250102_gabc.csv"
            grid.write_text("event_id\nvalue\n", encoding="utf-8")

            with self.assertRaises(FileNotFoundError):
                _discover_grid_paths(
                    root,
                    "USD_JPY",
                    pd.Timestamp("2025-01-01").to_pydatetime(),
                    pd.Timestamp("2025-01-02").to_pydatetime(),
                )


class LastReachInputTest(unittest.TestCase):
    def test_rank_prefixed_last_reach_columns_are_primary(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "candidates.csv"
            pd.DataFrame(
                [
                    {
                        "event_id": "event-1",
                        "pair": "USD_JPY",
                        "decision_time": "2025-01-01 01:00:00",
                        "candidate_rank": 1,
                        "predict_rank_last_reach_elapsed_minutes": 45.0,
                        "predict_rank_last_reach_source": "line_source",
                        "predict_rank_prior_retouch_count": 0,
                    }
                ]
            ).to_csv(source, index=False)
            args = SimpleNamespace(
                source_candidates=source,
                pair="USD_JPY",
                start=pd.Timestamp("2025-01-01 00:00:00"),
                end=pd.Timestamp("2025-01-02 00:00:00"),
                read_chunk_size=1000,
            )

            values, stats = _load_last_reach(args)

        self.assertEqual(values[("event-1", 1)]["elapsed_minutes"], 45.0)
        self.assertEqual(values[("event-1", 1)]["retouch_count"], 0.0)
        self.assertEqual(stats["loaded"], 1)


class PolicyMappingTest(unittest.TestCase):
    def test_policy_range_maps_to_grid_condition_id(self):
        condition_id = _policy_condition_id(
            {
                "timeframe": "m5",
                "field": "second_pullback_pips_per_foot",
                "operator": "range",
                "minimum": 3.0,
                "maximum": 4.0,
            }
        )
        self.assertEqual(
            condition_id,
            "M5::second_pullback_pips_per_foot_bin::3-3.99",
        )

    def test_less_than_policy_maps_to_every_matching_bin(self):
        condition_ids = _policy_condition_ids(
            {
                "timeframe": "h1",
                "field": "net_progress_pips",
                "operator": "less_than",
                "maximum": 1.0,
            }
        )

        self.assertEqual(
            condition_ids,
            frozenset(
                {
                    "H1::net_progress_pips_bin::<1",
                }
            ),
        )


if __name__ == "__main__":
    unittest.main()
