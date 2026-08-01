import unittest
from unittest.mock import patch

import pandas as pd

from classOanda import (
    Oanda,
    S5_COMPLETION_VERSION_COLUMN,
    S5_ELAPSED_COLUMN,
    S5_SYNTHETIC_COLUMN,
    fill_s5_no_tick_candles,
)


def raw_candle(
        timestamp,
        open_price,
        close_price=None,
        *,
        complete=True,
        volume=1,
        time_format="%Y-%m-%dT%H:%M:%S.000000000Z"):
    close_price = open_price if close_price is None else close_price
    timestamp = pd.Timestamp(timestamp)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    return {
        "time_jp": timestamp.tz_convert("Asia/Tokyo").strftime(
            "%Y/%m/%d %H:%M:%S"
        ),
        "time": timestamp.strftime(time_format),
        "volume": volume,
        "complete": complete,
        "mid": {
            "o": str(open_price),
            "h": str(max(open_price, close_price)),
            "l": str(min(open_price, close_price)),
            "c": str(close_price),
        },
    }


class S5NoTickFillTest(unittest.TestCase):
    def test_short_internal_gap_uses_only_previous_close(self):
        frame = pd.DataFrame([
            raw_candle("2026-07-01T00:00:15Z", 150, 151),
            raw_candle("2026-07-01T00:00:00Z", 100, 101),
        ])

        result = fill_s5_no_tick_candles(frame)

        self.assertEqual(len(result), 4)
        self.assertEqual(
            result["time_jp"].tolist(),
            [
                "2026/07/01 09:00:00",
                "2026/07/01 09:00:05",
                "2026/07/01 09:00:10",
                "2026/07/01 09:00:15",
            ],
        )
        for index in (1, 2):
            self.assertEqual(
                result.loc[index, "mid"],
                {"o": "101", "h": "101", "l": "101", "c": "101"},
            )
            self.assertEqual(result.loc[index, "volume"], 0)
            self.assertTrue(result.loc[index, "complete"])
            self.assertTrue(result.loc[index, S5_SYNTHETIC_COLUMN])
        self.assertEqual(result.loc[1, S5_ELAPSED_COLUMN], 5.0)
        self.assertEqual(result.loc[2, S5_ELAPSED_COLUMN], 10.0)
        self.assertTrue(result[S5_COMPLETION_VERSION_COLUMN].all())
        self.assertEqual(
            result.attrs["s5_fill_stats"],
            {
                "actual_rows": 2,
                "synthetic_rows": 2,
                "long_gaps_kept": 0,
            },
        )

    def test_completion_is_idempotent_with_mixed_iso_precision(self):
        frame = pd.DataFrame([
            raw_candle(
                "2026-07-01T00:00:00Z",
                100,
                101,
                time_format="%Y-%m-%dT%H:%M:%SZ",
            ),
            raw_candle(
                "2026-07-01T00:00:10Z",
                110,
                111,
                time_format="%Y-%m-%dT%H:%M:%S.000000000Z",
            ),
        ])

        once = fill_s5_no_tick_candles(frame)
        twice = fill_s5_no_tick_candles(once)

        pd.testing.assert_frame_equal(once, twice)
        self.assertEqual(
            once.attrs["s5_fill_stats"],
            twice.attrs["s5_fill_stats"],
        )

    def test_daily_new_york_pause_is_not_filled_in_summer_or_winter(self):
        for previous, following in (
            (
                "2026-07-01T20:58:55Z",
                "2026-07-01T21:05:00Z",
            ),
            (
                "2026-01-07T21:58:55Z",
                "2026-01-07T22:05:00Z",
            ),
        ):
            with self.subTest(previous=previous):
                frame = pd.DataFrame([
                    raw_candle(previous, 100, 101),
                    raw_candle(following, 102, 103),
                ])

                result = fill_s5_no_tick_candles(frame)

                self.assertEqual(len(result), 2)
                self.assertEqual(
                    int(result[S5_SYNTHETIC_COLUMN].sum()),
                    0,
                )
                self.assertEqual(
                    result.attrs["s5_fill_stats"]["long_gaps_kept"],
                    1,
                )

    def test_weekend_is_not_filled(self):
        frame = pd.DataFrame([
            raw_candle("2026-07-03T20:59:55Z", 100, 101),
            raw_candle("2026-07-05T21:05:00Z", 102, 103),
        ])

        result = fill_s5_no_tick_candles(frame)

        self.assertEqual(len(result), 2)
        self.assertEqual(int(result[S5_SYNTHETIC_COLUMN].sum()), 0)

    def test_unknown_long_gap_keeps_same_causal_15_minute_prefix(self):
        short_frame = pd.DataFrame([
            raw_candle("2026-07-01T10:00:00Z", 100, 101),
            raw_candle("2026-07-01T10:15:00Z", 102, 103),
        ])
        long_frame = pd.DataFrame([
            raw_candle("2026-07-01T10:00:00Z", 100, 101),
            raw_candle("2026-07-01T10:20:00Z", 102, 103),
        ])

        short_result = fill_s5_no_tick_candles(short_frame)
        long_result = fill_s5_no_tick_candles(long_frame)

        short_prefix = short_result.iloc[:-1].reset_index(drop=True)
        long_prefix = long_result.iloc[:len(short_prefix)].reset_index(drop=True)
        pd.testing.assert_series_equal(
            short_prefix["time"],
            long_prefix["time"],
        )
        pd.testing.assert_series_equal(
            short_prefix["mid"],
            long_prefix["mid"],
        )
        self.assertEqual(
            long_result.attrs["s5_fill_stats"]["long_gaps_kept"],
            1,
        )

    def test_unknown_gap_prefix_does_not_depend_on_24_hour_boundary(self):
        frames = []
        for following in (
            "2026-07-02T09:59:55Z",
            "2026-07-02T10:00:00Z",
        ):
            frames.append(
                fill_s5_no_tick_candles(
                    pd.DataFrame([
                        raw_candle("2026-07-01T10:00:00Z", 100, 101),
                        raw_candle(following, 102, 103),
                    ])
                )
            )

        first_prefix = frames[0].iloc[:181].reset_index(drop=True)
        second_prefix = frames[1].iloc[:181].reset_index(drop=True)
        pd.testing.assert_series_equal(
            first_prefix["time"],
            second_prefix["time"],
        )
        pd.testing.assert_series_equal(
            first_prefix["mid"],
            second_prefix["mid"],
        )

    def test_exactly_15_minute_gap_is_filled(self):
        frame = pd.DataFrame([
            raw_candle("2026-07-01T10:00:00Z", 100, 101),
            raw_candle("2026-07-01T10:15:00Z", 102, 103),
        ])

        result = fill_s5_no_tick_candles(frame)

        self.assertEqual(len(result), 181)
        self.assertEqual(
            int(result[S5_SYNTHETIC_COLUMN].sum()),
            179,
        )

    def test_recompletion_does_not_treat_existing_synthetic_as_actual(self):
        first = fill_s5_no_tick_candles(
            pd.DataFrame([
                raw_candle("2026-07-01T00:00:00Z", 100, 101),
                raw_candle("2026-07-01T00:00:10Z", 110, 111),
            ])
        )
        partial = first.iloc[:2].copy()
        partial = pd.concat(
            [
                partial,
                pd.DataFrame([
                    raw_candle("2026-07-01T00:00:15Z", 115, 116),
                ]),
            ],
            ignore_index=True,
        )

        result = fill_s5_no_tick_candles(partial)

        elapsed = result.set_index("time_jp")[S5_ELAPSED_COLUMN]
        self.assertEqual(elapsed["2026/07/01 09:00:10"], 10.0)

    def test_completed_duplicate_is_preferred_over_incomplete_snapshot(self):
        incomplete = raw_candle(
            "2026-07-01T00:00:00Z",
            100,
            100,
            complete=False,
            volume=1,
        )
        completed = raw_candle(
            "2026-07-01T00:00:00Z",
            100,
            101,
            complete=True,
            volume=4,
        )

        result = fill_s5_no_tick_candles(
            pd.DataFrame([incomplete, completed])
        )

        self.assertEqual(len(result), 1)
        self.assertTrue(result.loc[0, "complete"])
        self.assertEqual(result.loc[0, "volume"], 4)
        self.assertEqual(result.loc[0, "mid"]["c"], "101")

    def test_conflicting_completed_duplicates_raise(self):
        first = raw_candle("2026-07-01T00:00:00Z", 100, 101)
        second = raw_candle("2026-07-01T00:00:00Z", 100, 102)

        with self.assertRaisesRegex(ValueError, "同一時刻に異なる"):
            fill_s5_no_tick_candles(pd.DataFrame([first, second]))

    def test_single_off_grid_row_raises(self):
        frame = pd.DataFrame([
            raw_candle("2026-07-01T00:00:03Z", 100, 101),
        ])

        with self.assertRaisesRegex(ValueError, "5秒グリッド"):
            fill_s5_no_tick_candles(frame)

    def test_missing_raw_oanda_metadata_raises(self):
        frame = pd.DataFrame([
            {
                "time": "2026-07-01T00:00:00Z",
                "mid": {"o": "1", "h": "1", "l": "1", "c": "1"},
            },
        ])

        with self.assertRaisesRegex(ValueError, "必要な列"):
            fill_s5_no_tick_candles(frame)


class MultiFetchS5FillIntegrationTest(unittest.TestCase):
    class FakeOanda(Oanda):
        def __init__(self, frames):
            self.frames = list(frames)

        def InstrumentsCandles_multi_support_exe(self, pair, params):
            return {"error": 0, "data": self.frames.pop(0)}

    def _run_multi(self, frames, granularity):
        fake = self.FakeOanda(frames)
        params = {
            "granularity": granularity,
            "count": 1,
            "to": "2026-07-01T00:00:20.000000000Z",
        }
        with (
            patch("classOanda.add_rsi", side_effect=lambda frame: frame),
            patch("classOanda.add_bb_data", side_effect=lambda frame, pair: frame),
        ):
            return Oanda.InstrumentsCandles_multi_exe(
                fake,
                "USD_JPY",
                params,
                len(frames),
            )["data"]

    def test_s5_fill_runs_after_all_chunks_are_concatenated(self):
        newer_chunk = pd.DataFrame([
            raw_candle("2026-07-01T00:00:15Z", 150, 151),
        ])
        older_chunk = pd.DataFrame([
            raw_candle("2026-07-01T00:00:00Z", 100, 101),
        ])

        result = self._run_multi(
            [newer_chunk, older_chunk],
            "S5",
        )

        self.assertEqual(len(result), 4)
        self.assertEqual(
            result["time_jp"].tolist(),
            [
                "2026/07/01 09:00:00",
                "2026/07/01 09:00:05",
                "2026/07/01 09:00:10",
                "2026/07/01 09:00:15",
            ],
        )
        self.assertEqual(
            result.loc[
                result[S5_SYNTHETIC_COLUMN],
                "close",
            ].tolist(),
            [101.0, 101.0],
        )

    def test_non_s5_multi_fetch_is_unchanged(self):
        newer_chunk = pd.DataFrame([
            raw_candle("2026-07-01T00:10:00Z", 150, 151),
        ])
        older_chunk = pd.DataFrame([
            raw_candle("2026-07-01T00:00:00Z", 100, 101),
        ])

        result = self._run_multi(
            [newer_chunk, older_chunk],
            "M5",
        )

        self.assertEqual(len(result), 2)
        self.assertNotIn(S5_SYNTHETIC_COLUMN, result.columns)

    def test_requested_range_stops_older_pages_and_keeps_fill_seed(self):
        newer_chunk = pd.DataFrame([
            raw_candle("2026-07-01T00:00:10Z", 110, 111),
        ])
        seed_chunk = pd.DataFrame([
            raw_candle("2026-07-01T00:00:00Z", 100, 101),
        ])
        unnecessary_chunk = pd.DataFrame([
            raw_candle("2026-06-30T23:59:50Z", 90, 91),
        ])
        fake = self.FakeOanda([
            newer_chunk,
            seed_chunk,
            unnecessary_chunk,
        ])
        params = {
            "granularity": "S5",
            "count": 1,
            "to": "2026-07-01T00:00:15.000000000Z",
        }

        with (
            patch("classOanda.add_rsi", side_effect=lambda frame: frame),
            patch("classOanda.add_bb_data", side_effect=lambda frame, pair: frame),
        ):
            result = fake.InstrumentsCandles_multi_exe(
                "USD_JPY",
                params,
                3,
                start_time=pd.Timestamp("2026-07-01 09:00:05"),
                end_time=pd.Timestamp("2026-07-01 09:00:10"),
            )["data"]

        self.assertEqual(len(fake.frames), 1)
        self.assertEqual(
            result["time_jp"].tolist(),
            ["2026/07/01 09:00:05", "2026/07/01 09:00:10"],
        )
        self.assertTrue(result.loc[0, S5_SYNTHETIC_COLUMN])
        self.assertEqual(result.loc[0, "close"], 101.0)

    def test_single_s5_fetch_is_completed_before_return(self):
        class FakeApi:
            @staticmethod
            def request(endpoint):
                return {
                    "candles": [
                        raw_candle(
                            "2026-07-01T00:00:00Z",
                            100,
                            101,
                        ),
                        raw_candle(
                            "2026-07-01T00:00:10Z",
                            110,
                            111,
                        ),
                    ]
                }

        fake = object.__new__(Oanda)
        fake.api = FakeApi()
        with (
            patch("classOanda.add_rsi", side_effect=lambda frame: frame),
            patch("classOanda.add_bb_data", side_effect=lambda frame, pair: frame),
        ):
            result = fake.InstrumentsCandles_exe(
                "USD_JPY",
                {"granularity": "S5", "count": 2},
            )["data"]

        self.assertEqual(len(result), 3)
        self.assertTrue(result.loc[1, S5_SYNTHETIC_COLUMN])
        self.assertEqual(result.loc[1, "close"], 101.0)


if __name__ == "__main__":
    unittest.main()
