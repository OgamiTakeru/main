import datetime
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from classStrategyRegime import StrategyRegime
from fLineStrategyUsdJpy import LineStrategyProfileUsdJpy


class CandleStub:
    def __init__(self, rows):
        self.h1_df_r = pd.DataFrame(rows)


class StrategyRegimeTest(unittest.TestCase):
    @staticmethod
    def h1_rows(closes, start="2026/01/01 12:00:00"):
        times = pd.date_range(start, periods=len(closes), freq="h")
        rows = []
        previous = closes[0]
        for timestamp, close in zip(times, closes):
            open_price = previous
            rows.append(
                {
                    "time_jp": timestamp,
                    "open": open_price,
                    "close": close,
                    "high": max(open_price, close) + 0.0002,
                    "low": min(open_price, close) - 0.0002,
                    "bb_range": 0.001,
                }
            )
            previous = close
        return rows

    def test_inspection_result_is_hidden_until_close_time(self):
        regime = StrategyRegime("EUR_USD", mode="inspection")
        regime.record_inspection_result(
            {
                "actual_order_result": "tp",
                "actual_res": 5,
                "direction": 1,
                "close_time": "2026/01/01 12:00:00",
            }
        )

        before = regime.current_snapshot("2026/01/01 11:59:59")
        after = regime.current_snapshot("2026/01/01 12:00:00")

        self.assertEqual(before["buy"]["last_15"]["decided"], 0)
        self.assertEqual(after["buy"]["last_15"]["decided"], 1)
        self.assertEqual(after["buy"]["last_15"]["win_rate"], 1)

    def test_market_snapshot_uses_only_completed_h1_candles(self):
        regime = StrategyRegime("EUR_USD", mode="inspection")
        candles = CandleStub(
            [
                {
                    "time_jp": "2026/01/01 12:00:00",
                    "open": 1.1,
                    "close": 1.2,
                    "high": 1.3,
                    "low": 1.0,
                    "bb_range": 0.2,
                },
                {
                    "time_jp": "2026/01/01 11:00:00",
                    "open": 1.0,
                    "close": 1.1,
                    "high": 1.2,
                    "low": 0.9,
                    "bb_range": 0.1,
                },
            ]
        )

        snapshot = regime.current_snapshot(
            datetime.datetime(2026, 1, 1, 12, 30),
            candle_analysis=candles,
        )

        self.assertEqual(snapshot["market"]["completed_h1_bars"], 1)
        self.assertEqual(
            snapshot["market"]["latest_h1_time"],
            "2026/01/01 11:00:00",
        )

    def test_live_history_is_filtered_by_pair_and_decision_time(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "history.csv"
            pd.DataFrame(
                [
                    {
                        "pair": "USD_JPY",
                        "tradeID": 1,
                        "take_price": 150,
                        "end_time": "2026/01/01 10:00:00",
                        "units": 100,
                        "pl_per_units": 4,
                    },
                    {
                        "pair": "USD_JPY",
                        "tradeID": 2,
                        "take_price": 150,
                        "end_time": "2026/01/01 12:00:00",
                        "units": -100,
                        "pl_per_units": -3,
                    },
                    {
                        "pair": "EUR_USD",
                        "tradeID": 3,
                        "take_price": 1.1,
                        "end_time": "2026/01/01 09:00:00",
                        "units": 100,
                        "pl_per_units": 9,
                    },
                ]
            ).to_csv(path, index=False)
            regime = StrategyRegime(
                "USD_JPY",
                mode="live",
                history_path=path,
            )

            snapshot = regime.current_snapshot("2026/01/01 11:00:00")

            self.assertEqual(snapshot["all"]["last_15"]["decided"], 1)
            self.assertEqual(snapshot["buy"]["last_15"]["average_pips"], 4)
            self.assertEqual(snapshot["sell"]["last_15"]["decided"], 0)

    def test_six_hour_directional_move_is_up_trend(self):
        regime = StrategyRegime("EUR_USD", mode="inspection")
        closes = [1.1000 + (index * 0.0010) for index in range(12)]
        snapshot = regime.current_snapshot(
            "2026/01/02 00:00:00",
            candle_analysis=CandleStub(self.h1_rows(closes)),
        )

        market = snapshot["market"]
        self.assertEqual(market["regime"], StrategyRegime.REGIME_UP_TREND)
        self.assertEqual(market["trend_direction"], 1)
        self.assertTrue(market["is_trend"])

    def test_low_efficiency_six_hour_move_is_range(self):
        regime = StrategyRegime("EUR_USD", mode="inspection")
        closes = [1.1000, 1.1010] * 6
        snapshot = regime.current_snapshot(
            "2026/01/02 00:00:00",
            candle_analysis=CandleStub(self.h1_rows(closes)),
        )

        market = snapshot["market"]
        self.assertEqual(market["regime"], StrategyRegime.REGIME_RANGE)
        self.assertEqual(market["trend_direction"], 0)
        self.assertTrue(market["is_range"])

    def test_regime_policy_blocks_incompatible_orders(self):
        profile = LineStrategyProfileUsdJpy()
        breakout = SimpleNamespace(entry_type="breakout")
        reversal = SimpleNamespace(entry_type="reversal")

        profile.regime_snapshot = {
            "market": {"regime": "RANGE", "trend_direction": 0}
        }
        range_policy = profile.regime_order_policy(
            {"strategy": breakout, "direction": 1}
        )
        range_reversal = profile.regime_order_policy(
            {"strategy": reversal, "direction": -1}
        )
        self.assertFalse(range_policy["permission"])
        self.assertTrue(range_reversal["permission"])

        profile.regime_snapshot = {
            "market": {"regime": "UP_TREND", "trend_direction": 1}
        }
        aligned = profile.regime_order_policy(
            {"strategy": breakout, "direction": 1}
        )
        opposite = profile.regime_order_policy(
            {"strategy": reversal, "direction": -1}
        )
        self.assertTrue(aligned["permission"])
        self.assertFalse(opposite["permission"])


if __name__ == "__main__":
    unittest.main()
