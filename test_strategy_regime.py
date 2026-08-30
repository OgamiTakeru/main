# 最新更新日時: 2026-08-29 15:38 JST

import datetime
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from classStrategyRegime import StrategyRegime
from fLineAnalysis import LineOrderCoordinator
from fLineStrategyAudUsd import LineStrategyProfileAudUsd
from fLineStrategyUsdJpy import LineStrategyProfileUsdJpy


class CandleStub:
    def __init__(self, rows):
        completed_df_r = pd.DataFrame(rows).copy()
        completed_df_r["_sort_time"] = pd.to_datetime(
            completed_df_r["time_jp"],
            errors="raise",
        )
        self.h1_completed_df_r = completed_df_r.sort_values(
            "_sort_time",
            ascending=False,
            kind="stable",
        ).drop(columns="_sort_time").reset_index(drop=True)


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

    def test_aud_immediate_top10_match_does_not_bypass_strict_break_score(self):
        profile = LineStrategyProfileAudUsd()
        candidate = {
            "direction": -1,
            "line_side": "lower",
            "distance_pips": 1,
            "line_behavior": "break",
            "line_break_score": 0.60,
            "line_break_reasons": ["one", "two", "three"],
            "core_total_strength": 5,
            "strategy": SimpleNamespace(entry_type="breakout"),
            "line": {},
        }

        reasons = profile.immediate_recommended_reasons(
            candidate,
            {"rsi_1": 50, "rsi_2": 55},
            {"direction": -1},
        )

        self.assertEqual(reasons, [])

    def test_aud_immediate_accepts_candidate_that_passes_full_strict_gate(self):
        profile = LineStrategyProfileAudUsd()
        candidate = {
            "direction": -1,
            "line_side": "lower",
            "distance_pips": 1,
            "line_behavior": "break",
            "line_break_score": 0.80,
            "line_break_reasons": ["one", "two", "three"],
            "previous_peak_strength": 5,
            "strategy": SimpleNamespace(entry_type="breakout"),
            "h1_context": {
                "h1_path_ahead_1_distance_pips": 5,
                "h1_path_ahead_1_total_strength": 5,
            },
            "line": {
                "is_flipped_line": False,
                "line_current_role": "support",
                "line_latest_touch_peak_dir": -1,
                "count": 2,
                "core_count": 2,
                "total_strength": 10,
                "line_peak_rsi_latest": 45,
            },
        }

        reasons = profile.immediate_recommended_reasons(
            candidate,
            {"rsi_1": 50, "rsi_2": 55},
            {"direction": -1},
        )

        self.assertTrue(reasons)

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

    def test_regime_block_is_only_enforced_live(self):
        coordinator = LineOrderCoordinator.__new__(LineOrderCoordinator)

        coordinator.analysis = SimpleNamespace(mode="inspection")
        self.assertFalse(coordinator._regime_block_is_enforced())

        coordinator.analysis = SimpleNamespace(mode="live")
        self.assertTrue(coordinator._regime_block_is_enforced())

    def test_inspection_keeps_would_block_metadata(self):
        coordinator = LineOrderCoordinator.__new__(LineOrderCoordinator)
        coordinator.analysis = SimpleNamespace(mode="inspection")
        profile = LineStrategyProfileUsdJpy()
        profile.regime_snapshot = {
            "market": {"regime": "RANGE", "trend_direction": 0}
        }
        coordinator.profile = profile
        candidate = {
            "strategy": SimpleNamespace(entry_type="breakout"),
            "direction": 1,
        }

        policy = coordinator._regime_order_policy(candidate)

        self.assertFalse(policy["permission"])
        self.assertTrue(candidate["regime_would_block"])
        self.assertFalse(candidate["regime_order_enforced"])
        self.assertIn("inspection would block", coordinator._regime_reason_text(policy))


if __name__ == "__main__":
    unittest.main()
