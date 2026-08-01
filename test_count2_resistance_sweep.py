import datetime as dt
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pandas as pd

import classOanda
import fGeneric as gene
import test_win_point_resistance_euro_usd as eur_entry
import test_win_point_resistance_usd_aud as aud_entry
import test_win_point_resistance_usd_jpy as jpy_entry
from count2_resistance_sweep import (
    LimitPathInspector,
    data_coverage_errors,
    line_touch_features,
    prepare_m5,
    prepare_s5,
    parse_args,
    rebuild_candidates_at,
    select_ahead_lines,
    s5_cache_has_no_tick_completion,
    target_parameters,
)


class ResistanceEntryPointPeriodTest(unittest.TestCase):
    def test_all_pair_entry_points_show_the_same_requested_period(self):
        expected = {
            "AUD_USD": aud_entry,
            "USD_JPY": jpy_entry,
            "EUR_USD": eur_entry,
        }
        for pair_name, entry in expected.items():
            with self.subTest(pair=pair_name):
                self.assertEqual(entry.PAIR, pair_name)
                self.assertEqual(
                    entry.START_TIME,
                    dt.datetime(2025, 7, 30),
                )
                self.assertEqual(
                    entry.END_TIME,
                    dt.datetime(2026, 7, 30),
                )


class S5CacheFormatTest(unittest.TestCase):
    def test_legacy_sparse_cache_is_not_reused(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "legacy.csv"
            pd.DataFrame(
                [{"time_jp": "2026/01/01 00:00:00", "close": 1.0}]
            ).to_csv(path, index=False)

            self.assertFalse(s5_cache_has_no_tick_completion(path))

    def test_completed_cache_is_reusable(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "completed.csv"
            pd.DataFrame(
                [
                    {
                        "time_jp": "2026/01/01 00:00:00",
                        "close": 1.0,
                        classOanda.S5_SYNTHETIC_COLUMN: False,
                        classOanda.S5_ELAPSED_COLUMN: np.nan,
                        classOanda.S5_COMPLETION_VERSION_COLUMN: True,
                    }
                ]
            ).to_csv(path, index=False)

            self.assertTrue(s5_cache_has_no_tick_completion(path))

    def test_pre_causal_completion_cache_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "old_completion.csv"
            pd.DataFrame(
                [
                    {
                        "time_jp": "2026/01/01 00:00:00",
                        "close": 1.0,
                        classOanda.S5_SYNTHETIC_COLUMN: False,
                        "synthetic_source_gap_seconds": np.nan,
                    }
                ]
            ).to_csv(path, index=False)

            self.assertFalse(s5_cache_has_no_tick_completion(path))


def m5_with_ranges(pair, range_pips):
    start = pd.Timestamp("2025-01-06 09:00:00")
    rows = []
    base = 150.0 if pair.name == "USD_JPY" else 1.0
    for index, width_pips in enumerate(range_pips):
        half_width = width_pips * pair.pip_value / 2
        rows.append(
            {
                "time_jp": (start + pd.Timedelta(minutes=5 * index)).strftime(
                    "%Y/%m/%d %H:%M:%S"
                ),
                "open": base,
                "close": base,
                "high": base + half_width,
                "low": base - half_width,
            }
        )
    return prepare_m5(pd.DataFrame(rows))


def s5_frame(rows):
    return prepare_s5(
        pd.DataFrame(
            [
                {
                    "time_jp": pd.Timestamp(timestamp).strftime(
                        "%Y/%m/%d %H:%M:%S"
                    ),
                    "open": open_price,
                    "close": close,
                    "high": high,
                    "low": low,
                }
                for timestamp, open_price, close, high, low in rows
            ]
        )
    )


class TargetParameterTest(unittest.TestCase):
    def test_default_period_is_2025_07_30_to_2026_07_30(self):
        args = parse_args("AUD_USD", [])
        self.assertEqual(args.start, pd.Timestamp("2025-07-30").to_pydatetime())
        self.assertEqual(args.end, pd.Timestamp("2026-07-30").to_pydatetime())

    def test_pair_entry_point_period_can_be_supplied_as_visible_defaults(self):
        args = parse_args(
            "EUR_USD",
            [],
            default_start=dt.datetime(2025, 7, 30),
            default_end=dt.datetime(2026, 7, 30),
        )
        self.assertEqual(args.start, dt.datetime(2025, 7, 30))
        self.assertEqual(args.end, dt.datetime(2026, 7, 30))

    def test_command_line_period_overrides_visible_pair_defaults(self):
        args = parse_args(
            "USD_JPY",
            ["--start", "2026-01-01", "--end", "2026-02-01"],
            default_start=dt.datetime(2025, 7, 30),
            default_end=dt.datetime(2026, 7, 30),
        )
        self.assertEqual(args.start, dt.datetime(2026, 1, 1))
        self.assertEqual(args.end, dt.datetime(2026, 2, 1))

    def test_exactly_six_completed_bars_for_all_pairs(self):
        expected_average = np.mean([1, 2, 3, 4, 5, 6])
        for pair_name in ("AUD_USD", "USD_JPY", "EUR_USD"):
            with self.subTest(pair=pair_name):
                pair = gene.currency_pair(pair_name)
                m5 = m5_with_ranges(pair, [1, 2, 3, 4, 5, 6, 500, 900])
                result = target_parameters(
                    m5,
                    6,
                    pair,
                    lookback=6,
                    multiplier=3,
                    rr=1.2,
                )
                self.assertTrue(result["target_valid"])
                self.assertAlmostEqual(
                    result["recent_m5_avg_range_pips"],
                    expected_average,
                    places=7,
                )
                self.assertAlmostEqual(
                    result["tp_pips"],
                    expected_average * 3,
                    places=7,
                )
                self.assertAlmostEqual(
                    result["lc_pips"],
                    expected_average * 3 / 1.2,
                    places=7,
                )

    def test_future_candle_does_not_change_target(self):
        pair = gene.currency_pair("AUD_USD")
        first = m5_with_ranges(pair, [2, 2, 2, 2, 2, 2, 3])
        second = m5_with_ranges(pair, [2, 2, 2, 2, 2, 2, 999])
        first_result = target_parameters(first, 6, pair)
        second_result = target_parameters(second, 6, pair)
        self.assertEqual(first_result["tp_pips"], second_result["tp_pips"])
        self.assertEqual(first_result["lc_pips"], second_result["lc_pips"])


class CandidateDirectionTest(unittest.TestCase):
    def test_up_peak_uses_all_upper_lines_as_sell(self):
        pair = gene.currency_pair("USD_JPY")
        selected = select_ahead_lines(
            1,
            150.0,
            [
                {"median_price": 150.05},
                {"median_price": 149.99},
                {"median_price": 150.02},
            ],
            [{"median_price": 149.95}],
            pair,
        )
        self.assertEqual([row["candidate_rank"] for row in selected], [1, 2])
        self.assertEqual([row["line_price"] for row in selected], [150.02, 150.05])
        self.assertTrue(all(row["trade_side"] == "SELL" for row in selected))
        self.assertTrue(all(row["line_side"] == "upper" for row in selected))

    def test_down_peak_uses_all_lower_lines_as_buy(self):
        pair = gene.currency_pair("EUR_USD")
        selected = select_ahead_lines(
            -1,
            1.1000,
            [{"median_price": 1.1010}],
            [
                {"median_price": 1.0980},
                {"median_price": 1.0995},
                {"median_price": 1.1001},
            ],
            pair,
        )
        self.assertEqual([row["line_price"] for row in selected], [1.0995, 1.098])
        self.assertTrue(all(row["trade_side"] == "BUY" for row in selected))
        self.assertTrue(all(row["line_side"] == "lower" for row in selected))


class TouchFeatureTest(unittest.TestCase):
    def test_future_touch_is_not_counted_as_prior_retouch(self):
        pair = gene.currency_pair("EUR_USD")
        start = pd.Timestamp("2025-01-06 09:00:00")
        raw = pd.DataFrame(
            [
                {
                    "time_jp": (start + pd.Timedelta(minutes=offset)).strftime(
                        "%Y/%m/%d %H:%M:%S"
                    ),
                    "open": 1.0,
                    "close": 1.0,
                    "high": high,
                    "low": low,
                }
                for offset, high, low in (
                    (0, 1.0001, 0.9999),
                    (5, 1.0001, 0.9999),
                    (10, 1.0020, 1.0015),
                    (20, 1.0001, 0.9999),
                )
            ]
        )
        history = prepare_m5(raw)
        line = {
            "median_price": 1.0,
            "newest_time": start.strftime("%Y/%m/%d %H:%M:%S"),
            "oldest_time": start.strftime("%Y/%m/%d %H:%M:%S"),
            "count": 1,
        }
        decision = start + pd.Timedelta(minutes=15)
        result = line_touch_features(history, line, decision, pair, 0.5)
        self.assertTrue(result["prior_retouch_exists"])
        self.assertEqual(result["prior_retouch_count"], 1)
        self.assertEqual(
            result["prior_retouch_last_time"],
            start + pd.Timedelta(minutes=5),
        )
        self.assertEqual(result["minutes_since_prior_retouch"], 10)


class FutureLeakGuardTest(unittest.TestCase):
    def test_line_snapshot_excludes_decision_and_future_prices(self):
        start = pd.Timestamp("2025-01-06 09:00:00")
        raw = pd.DataFrame(
            [
                {
                    "time_jp": (start + pd.Timedelta(minutes=5 * index)).strftime(
                        "%Y/%m/%d %H:%M:%S"
                    ),
                    "open": 1.0 + index * 0.00001,
                    "close": 1.0 + index * 0.00001,
                    "high": 1.0002 + index * 0.00001,
                    "low": 0.9998 + index * 0.00001,
                }
                for index in range(185)
            ]
        )
        first = prepare_m5(raw)
        second = first.copy()
        second.loc[180:, ["open", "close", "high", "low"]] = [
            9.0,
            9.0,
            9.1,
            8.9,
        ]
        captured = []

        class FakePeaks:
            def __init__(self, snapshot, granularity, current_price, pair=None):
                captured.append(snapshot.copy())
                self.peaks_original = [
                    {
                        "count": 2,
                        "direction": 1,
                        "latest_time_jp": snapshot.iloc[1]["time_jp"],
                        "oldest_time_jp": snapshot.iloc[2]["time_jp"],
                        "peak": current_price,
                        "latest_body_peak_price": current_price,
                        "peak_strength": 5,
                        "gap": pair.pips_to_price(2),
                    }
                ]

        class FakeLines:
            def __init__(self, analysis, foot, history_bars):
                pair = gene.currency_pair(analysis.pair)
                price = analysis.current_price + pair.pips_to_price(5)
                self.upper_lines = [
                    {
                        "median_price": price,
                        "count": 1,
                        "prices_info": [],
                    }
                ]
                self.lower_lines = []

        profile = SimpleNamespace(
            is_m5_reversal_target=lambda side, line: True
        )
        with (
            patch("count2_resistance_sweep.PeaksClass", FakePeaks),
            patch("count2_resistance_sweep.LineStrengthCal", FakeLines),
            patch(
                "count2_resistance_sweep.line_strategy_profile",
                return_value=profile,
            ),
        ):
            first_result = rebuild_candidates_at(first, 180, "EUR_USD")
            second_result = rebuild_candidates_at(second, 180, "EUR_USD")

        self.assertEqual(
            first_result["current_price"],
            second_result["current_price"],
        )
        self.assertEqual(
            first_result["candidates"][0]["line_price"],
            second_result["candidates"][0]["line_price"],
        )
        decision_time = first.iloc[180]["time_jp_dt"]
        for snapshot in captured:
            self.assertEqual(snapshot.iloc[0]["time_jp_dt"], decision_time)
            self.assertTrue(
                (snapshot.iloc[1:]["time_jp_dt"] < decision_time).all()
            )
            self.assertFalse(
                np.isclose(
                    pd.to_numeric(snapshot.iloc[1:]["close"]),
                    9.0,
                ).any()
            )


class DataCoverageTest(unittest.TestCase):
    def test_truncated_cache_edges_are_rejected(self):
        start = pd.Timestamp("2025-01-06 09:00:00")
        end = pd.Timestamp("2025-01-06 10:00:00")
        m5_times = pd.date_range(
            start - pd.Timedelta(minutes=180 * 5),
            end - pd.Timedelta(minutes=5),
            freq="5min",
        )
        s5_times = pd.date_range(
            start,
            end + pd.Timedelta(minutes=60) - pd.Timedelta(seconds=5),
            freq="5s",
        )
        m5 = pd.DataFrame({"time_jp_dt": m5_times})
        s5 = pd.DataFrame({"time_jp_dt": s5_times})
        self.assertEqual(
            data_coverage_errors(m5, s5, start, end, 60),
            {},
        )

        errors = data_coverage_errors(
            m5.iloc[:-1],
            s5.iloc[:-1],
            start,
            end,
            60,
        )
        self.assertIn("M5", errors)
        self.assertIn("S5", errors)
        self.assertTrue(
            any("truncated_end" in item for item in errors["M5"])
        )
        self.assertTrue(
            any("truncated_end" in item for item in errors["S5"])
        )

    def test_m5_requires_full_peak_prehistory(self):
        start = pd.Timestamp("2025-01-06 09:00:00")
        end = pd.Timestamp("2025-01-06 10:00:00")
        m5 = pd.DataFrame(
            {
                "time_jp_dt": pd.date_range(
                    start - pd.Timedelta(minutes=179 * 5),
                    end - pd.Timedelta(minutes=5),
                    freq="5min",
                )
            }
        )
        s5 = pd.DataFrame(
            {
                "time_jp_dt": pd.date_range(
                    start,
                    end
                    + pd.Timedelta(minutes=60)
                    - pd.Timedelta(seconds=5),
                    freq="5s",
                )
            }
        )
        errors = data_coverage_errors(m5, s5, start, end, 60)
        self.assertIn("M5", errors)
        self.assertTrue(
            any("prehistory_rows=179" in item for item in errors["M5"])
        )


class LimitPathInspectorTest(unittest.TestCase):
    def setUp(self):
        self.start = pd.Timestamp("2025-01-06 09:00:00")
        self.jpy = gene.currency_pair("USD_JPY")
        self.eur = gene.currency_pair("EUR_USD")

    def test_known_daily_oanda_pause_is_accepted_in_summer_and_winter(self):
        for times in (
            np.array(
                ["2026-07-02T05:58:55", "2026-07-02T06:05:00"],
                dtype="datetime64[ns]",
            ),
            np.array(
                ["2026-01-08T06:58:55", "2026-01-08T07:05:00"],
                dtype="datetime64[ns]",
            ),
        ):
            with self.subTest(times=times):
                self.assertTrue(
                    LimitPathInspector._is_contiguous(
                        times,
                        pd.Timestamp(times[0]),
                    )
                )

    def test_unknown_intraday_gap_is_not_accepted_as_daily_pause(self):
        times = np.array(
            ["2026-07-02T10:00:00", "2026-07-02T10:06:05"],
            dtype="datetime64[ns]",
        )

        self.assertFalse(
            LimitPathInspector._is_contiguous(
                times,
                pd.Timestamp(times[0]),
            )
        )

    def test_expiry_time_is_exclusive(self):
        rows = [
            (self.start, 99.99, 99.99, 100.003, 99.98),
            (
                self.start + pd.Timedelta(seconds=5),
                99.99,
                99.99,
                100.003,
                99.98,
            ),
            (
                self.start + pd.Timedelta(seconds=10),
                100.0,
                100.0,
                100.004,
                99.98,
            ),
        ]
        inspector = LimitPathInspector(s5_frame(rows), self.jpy)
        result = inspector.inspect(
            self.start,
            self.start + pd.Timedelta(seconds=10),
            direction=-1,
            line_price=100.0,
            tp_pips=20,
            lc_pips=20,
            horizon_minutes=1,
            spread_pips=0.8,
        )
        self.assertFalse(result["filled"])
        self.assertEqual(result["candidate_result"], "not_filled")

    def test_touch_immediately_before_expiry_can_fill(self):
        rows = [
            (self.start, 99.99, 99.99, 100.003, 99.98),
            (
                self.start + pd.Timedelta(seconds=5),
                100.0,
                100.0,
                100.004,
                99.98,
            ),
            (
                self.start + pd.Timedelta(seconds=10),
                100.0,
                100.0,
                100.004,
                99.98,
            ),
        ]
        inspector = LimitPathInspector(s5_frame(rows), self.jpy)
        result = inspector.inspect(
            self.start,
            self.start + pd.Timedelta(seconds=10),
            direction=-1,
            line_price=100.0,
            tp_pips=20,
            lc_pips=20,
            horizon_minutes=1,
            spread_pips=0.8,
        )
        self.assertTrue(result["filled"])
        self.assertEqual(
            result["fill_time"],
            self.start + pd.Timedelta(seconds=5),
        )

    def test_buy_and_sell_use_half_spread_fill_thresholds(self):
        cases = (
            (
                1,
                [
                    (self.start, 100.0, 100.0, 100.01, 99.997),
                    (
                        self.start + pd.Timedelta(seconds=5),
                        100.0,
                        100.0,
                        100.01,
                        99.996,
                    ),
                    (
                        self.start + pd.Timedelta(seconds=10),
                        100.0,
                        100.0,
                        100.01,
                        99.996,
                    ),
                ],
            ),
            (
                -1,
                [
                    (self.start, 100.0, 100.0, 100.003, 99.99),
                    (
                        self.start + pd.Timedelta(seconds=5),
                        100.0,
                        100.0,
                        100.004,
                        99.99,
                    ),
                    (
                        self.start + pd.Timedelta(seconds=10),
                        100.0,
                        100.0,
                        100.004,
                        99.99,
                    ),
                ],
            ),
        )
        for direction, rows in cases:
            with self.subTest(direction=direction):
                result = LimitPathInspector(
                    s5_frame(rows),
                    self.jpy,
                ).inspect(
                    self.start,
                    self.start + pd.Timedelta(seconds=15),
                    direction=direction,
                    line_price=100.0,
                    tp_pips=20,
                    lc_pips=20,
                    horizon_minutes=1,
                    spread_pips=0.8,
                )
                self.assertTrue(result["filled"])
                self.assertEqual(
                    result["fill_time"],
                    self.start + pd.Timedelta(seconds=5),
                )

    def test_fill_bar_tp_is_held_when_ordering_is_ambiguous(self):
        rows = [
            (self.start, 1.0002, 1.0002, 1.0012, 1.0000),
            (
                self.start + pd.Timedelta(seconds=5),
                1.0002,
                1.0010,
                1.0011,
                1.0001,
            ),
        ]
        result = LimitPathInspector(s5_frame(rows), self.eur).inspect(
            self.start,
            self.start + pd.Timedelta(seconds=30),
            direction=1,
            line_price=1.0,
            tp_pips=10,
            lc_pips=10,
            horizon_minutes=1,
            spread_pips=0,
        )
        self.assertTrue(result["fill_bar_tp_ambiguous"])
        self.assertEqual(result["candidate_result"], "tp")
        self.assertEqual(
            result["exit_time"],
            self.start + pd.Timedelta(seconds=5),
        )

    def test_fill_bar_lc_wins_same_bar_ambiguity(self):
        rows = [
            (self.start, 1.0002, 1.0002, 1.0012, 0.9985),
            (
                self.start + pd.Timedelta(seconds=5),
                1.0000,
                1.0000,
                1.0002,
                0.9998,
            ),
        ]
        result = LimitPathInspector(s5_frame(rows), self.eur).inspect(
            self.start,
            self.start + pd.Timedelta(seconds=30),
            direction=1,
            line_price=1.0,
            tp_pips=10,
            lc_pips=10,
            horizon_minutes=1,
            spread_pips=0,
        )
        self.assertTrue(result["lc_hit"])
        self.assertEqual(
            result["candidate_result"],
            "both_same_s5_lc_assumed",
        )

    def test_missing_position_horizon_is_not_timeout(self):
        rows = [
            (self.start, 1.0000, 1.0000, 1.0002, 1.0000),
            (
                self.start + pd.Timedelta(seconds=5),
                1.0000,
                1.0000,
                1.0002,
                0.9999,
            ),
            (
                self.start + pd.Timedelta(seconds=10),
                1.0000,
                1.0000,
                1.0002,
                0.9999,
            ),
        ]
        result = LimitPathInspector(s5_frame(rows), self.eur).inspect(
            self.start,
            self.start + pd.Timedelta(seconds=30),
            direction=1,
            line_price=1.0,
            tp_pips=20,
            lc_pips=20,
            horizon_minutes=1,
            spread_pips=0,
        )
        self.assertTrue(result["filled"])
        self.assertEqual(result["candidate_result"], "incomplete_horizon")
        self.assertNotEqual(result["candidate_result"], "timeout")

    def test_internal_pending_gap_is_incomplete_not_not_filled(self):
        rows = [
            (self.start, 1.0010, 1.0010, 1.0011, 1.0005),
            (
                self.start + pd.Timedelta(seconds=55),
                1.0010,
                1.0010,
                1.0011,
                1.0005,
            ),
            (
                self.start + pd.Timedelta(seconds=60),
                1.0010,
                1.0010,
                1.0011,
                1.0005,
            ),
        ]
        result = LimitPathInspector(s5_frame(rows), self.eur).inspect(
            self.start,
            self.start + pd.Timedelta(seconds=60),
            direction=1,
            line_price=1.0,
            tp_pips=20,
            lc_pips=20,
            horizon_minutes=1,
            spread_pips=0,
        )
        self.assertFalse(result["filled"])
        self.assertEqual(result["candidate_result"], "incomplete_pending")

    def test_internal_position_gap_is_incomplete_not_timeout(self):
        rows = [
            (self.start, 1.0000, 1.0000, 1.0002, 1.0000),
            (
                self.start + pd.Timedelta(seconds=55),
                1.0000,
                1.0000,
                1.0002,
                0.9999,
            ),
            (
                self.start + pd.Timedelta(seconds=60),
                1.0000,
                1.0000,
                1.0002,
                0.9999,
            ),
        ]
        result = LimitPathInspector(s5_frame(rows), self.eur).inspect(
            self.start,
            self.start + pd.Timedelta(seconds=120),
            direction=1,
            line_price=1.0,
            tp_pips=20,
            lc_pips=20,
            horizon_minutes=1,
            spread_pips=0,
        )
        self.assertTrue(result["filled"])
        self.assertEqual(result["candidate_result"], "incomplete_horizon")

    def test_known_weekend_closure_gap_is_allowed(self):
        times = np.array(
            [
                np.datetime64("2025-01-11T06:59:55"),
                np.datetime64("2025-01-13T07:00:00"),
            ],
            dtype="datetime64[ns]",
        )
        self.assertTrue(
            LimitPathInspector._is_contiguous(
                times,
                pd.Timestamp("2025-01-11 06:59:55"),
            )
        )

    def test_fill_at_open_tp_only_is_confirmed_on_fill_bar(self):
        rows = [
            (self.start, 0.9999, 1.0002, 1.0012, 0.9999),
        ]
        result = LimitPathInspector(s5_frame(rows), self.eur).inspect(
            self.start,
            self.start + pd.Timedelta(seconds=30),
            direction=1,
            line_price=1.0,
            tp_pips=10,
            lc_pips=20,
            horizon_minutes=1,
            spread_pips=0,
        )
        self.assertTrue(result["fill_at_bar_open"])
        self.assertFalse(result["fill_bar_tp_ambiguous"])
        self.assertEqual(result["candidate_result"], "tp")

    def test_intrabar_fill_mfe_uses_post_fill_close_lower_bound(self):
        rows = [
            (self.start, 1.0005, 1.0002, 1.0015, 1.0000),
        ]
        result = LimitPathInspector(s5_frame(rows), self.eur).inspect(
            self.start,
            self.start + pd.Timedelta(seconds=30),
            direction=1,
            line_price=1.0,
            tp_pips=20,
            lc_pips=20,
            horizon_minutes=1,
            spread_pips=0,
        )
        self.assertFalse(result["fill_at_bar_open"])
        self.assertEqual(result["candidate_result"], "incomplete_horizon")
        self.assertAlmostEqual(
            result["max_favorable_pips_before_exit"],
            2.0,
            places=7,
        )


if __name__ == "__main__":
    unittest.main()
