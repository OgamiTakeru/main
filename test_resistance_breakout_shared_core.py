# 最新更新日時: 2026-09-08 08:20 JST
"""抵抗線ブレイクの検証候補と本番Trial注文の横断契約テスト。"""

from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import patch

import pandas as pd

from classCandleAnalysis import CandleTimeframeBundle, candleAnalysis
import count2_resistance_sweep as sweep
import fGeneric as gene
import fResistanceBreakoutAnalysis as live_breakout


class ResistanceBreakoutProductionEquivalenceTest(unittest.TestCase):
    def setUp(self):
        self.pair_name = "USD_JPY"
        self.pair = gene.currency_pair(self.pair_name)
        self.decision_time = pd.Timestamp("2026-09-08 12:00:00")
        self.m5 = self._frame(
            pd.date_range(
                end=self.decision_time,
                periods=181,
                freq="5min",
            ),
            width_pips=10.0,
        )
        self.m30 = self._frame(
            pd.date_range(
                end=self.decision_time - pd.Timedelta(minutes=30),
                periods=240,
                freq="30min",
            ),
            width_pips=20.0,
        )
        self.h1 = self._frame(
            pd.date_range(
                end=self.decision_time - pd.Timedelta(hours=1),
                periods=240,
                freq="h",
            ),
            width_pips=30.0,
        )
        self.decision_index = len(self.m5) - 1
        self.emit_lines = True
        self.suppressed_timeframes: set[str] = set()
        self.line_calls: list[dict] = []
        self.context, self.fake_ca, self.m30_bundle = self._analysis_objects()

    def _frame(self, times: pd.DatetimeIndex, width_pips: float) -> pd.DataFrame:
        center = 150.0
        half_width = self.pair.pips_to_price(width_pips) / 2
        return pd.DataFrame({
            "time_jp": times.strftime("%Y/%m/%d %H:%M:%S"),
            "time_jp_dt": times,
            "open": center,
            "close": center,
            "high": center + half_width,
            "low": center - half_width,
        })

    @staticmethod
    def _completed_df_r(
        frame: pd.DataFrame,
        decision_time: pd.Timestamp,
        duration: pd.Timedelta,
    ) -> pd.DataFrame:
        return (
            frame.loc[frame["time_jp_dt"] + duration <= decision_time]
            .sort_values("time_jp_dt", ascending=False, kind="stable")
            .reset_index(drop=True)
        )

    def _analysis_objects(self):
        m5_completed_df_r = self._completed_df_r(
            self.m5,
            self.decision_time,
            pd.Timedelta(minutes=5),
        )
        m30_completed_df_r = self._completed_df_r(
            self.m30,
            self.decision_time,
            pd.Timedelta(minutes=30),
        )
        h1_completed_df_r = self._completed_df_r(
            self.h1,
            self.decision_time,
            pd.Timedelta(hours=1),
        )
        newest_m5_peak = {
            "count": 2,
            "direction": 1,
            "latest_time_jp": (
                self.decision_time - pd.Timedelta(minutes=5)
            ).strftime("%Y/%m/%d %H:%M:%S"),
            "oldest_time_jp": (
                self.decision_time - pd.Timedelta(minutes=10)
            ).strftime("%Y/%m/%d %H:%M:%S"),
            "peak": 150.0,
            "latest_body_peak_price": 150.0,
            "peak_strength": 5,
            "gap": self.pair.pips_to_price(10),
        }
        m5_peaks = SimpleNamespace(
            analysis_num=180,
            source_granularity="M5",
            peaks_original=[newest_m5_peak],
        )
        m30_peaks = SimpleNamespace(
            analysis_num=240,
            source_granularity="M30",
            peaks_original=[{
                "count": 4,
                "direction": 1,
                "latest_time_jp": (
                    self.decision_time - pd.Timedelta(minutes=30)
                ).strftime("%Y/%m/%d %H:%M:%S"),
            }],
        )
        h1_peaks = SimpleNamespace(
            analysis_num=240,
            source_granularity="H1",
            peaks_original=[{
                "count": 4,
                "direction": 1,
                "latest_time_jp": (
                    self.decision_time - pd.Timedelta(hours=1)
                ).strftime("%Y/%m/%d %H:%M:%S"),
            }],
        )
        context = SimpleNamespace(
            pair_name=self.pair_name,
            pair=self.pair,
            decision_time=self.decision_time,
            current_price=150.0,
            newest_m5_peak=newest_m5_peak,
            m5_original_df_r=self.m5.iloc[::-1].reset_index(drop=True),
            m5_completed_df_r=m5_completed_df_r,
            m5_peaks_class=m5_peaks,
            m5_foot_count2_shape={},
            h1_original_df_r=self.h1.iloc[::-1].reset_index(drop=True),
            h1_completed_df_r=h1_completed_df_r,
            h1_peaks_class=h1_peaks,
            rsi_info={},
            h1_shape_for_direction=lambda direction: {},
        )
        m5_bundle = CandleTimeframeBundle(
            timeframe="M5",
            duration=pd.Timedelta(minutes=5),
            original_df_r=context.m5_original_df_r,
            completed_df_r=m5_completed_df_r,
            peaks_class=m5_peaks,
            source_granularity="M5",
        )
        m30_bundle = CandleTimeframeBundle(
            timeframe="M30",
            duration=pd.Timedelta(minutes=30),
            original_df_r=self.m30.iloc[::-1].reset_index(drop=True),
            completed_df_r=m30_completed_df_r,
            peaks_class=m30_peaks,
            source_granularity="M30",
        )

        class FakeCandleAnalysis:
            pair = self.pair_name
            analysis_mode = "inspection"
            decision_time = self.decision_time
            current_price = 150.0
            candle_meta_class = SimpleNamespace(
                cal_move_ave=lambda _: 0.10,
            )

            def require_basic_analysis(fake_self):
                return context

            def get_timeframe_bundle(
                fake_self,
                timeframe,
                require_native=False,
            ):
                bundles = {"M5": m5_bundle, "M30": m30_bundle}
                bundle = bundles[str(timeframe).upper()]
                if require_native and not bundle.is_native:
                    raise ValueError("non-native test bundle")
                return bundle

            def validate_completed_history_for_context(
                fake_self,
                completed_df_r,
                *args,
                **kwargs,
            ):
                return completed_df_r

        return context, FakeCandleAnalysis(), m30_bundle

    def _fake_line_class(self):
        calls = self.line_calls
        decision_time = self.decision_time

        class FakeLineStrengthCal:
            def __init__(
                fake_self,
                owner,
                timeframe,
                line_history_bars,
                **options,
            ):
                normalized = str(timeframe).upper()
                bundle = options["timeframe_bundle"]
                calls.append({
                    "timeframe": normalized,
                    "line_history_bars": int(line_history_bars),
                    "peak_history_bars": int(bundle.peaks_class.analysis_num),
                    "enforce_peak_strength_filter": bool(
                        options["enforce_peak_strength_filter"]
                    ),
                    "min_line_peak_count": int(
                        options["min_line_peak_count"]
                    ),
                    "min_line_direction_ratio": float(
                        options["min_line_direction_ratio"]
                    ),
                    "group_threshold_pips": float(
                        options["group_threshold_pips"]
                    ),
                })
                fake_self.peaks_class = bundle.peaks_class
                fake_self.threshold = float(options["group_threshold_pips"])
                trigger_direction = int(
                    self.context.newest_m5_peak["direction"]
                )
                distance = 0.20 if normalized == "M5" else 0.40
                line_price = 150.0 + trigger_direction * distance
                count = 2 if normalized == "M5" else 3
                peak_times = [
                    decision_time - pd.Timedelta(minutes=30 * (index + 1))
                    for index in range(count)
                ]
                line = {
                    "median_price": line_price,
                    "count": count,
                    "core_count": 2,
                    "total_strength": count * 5,
                    "ave_strength": 5.0,
                    "core_total_strength": 10.0,
                    "dirs": [trigger_direction] * count,
                    "prices_info": [
                        {
                            "latest_time_jp": timestamp.strftime(
                                "%Y/%m/%d %H:%M:%S"
                            ),
                            "direction": trigger_direction,
                            "latest_body_peak_price": line_price,
                            "peak_strength": 5,
                        }
                        for timestamp in peak_times
                    ],
                    "is_flipped_line": False,
                    "newest_time": (
                        decision_time - pd.Timedelta(minutes=30)
                    ).strftime("%Y/%m/%d %H:%M:%S"),
                    "oldest_time": (
                        decision_time - pd.Timedelta(hours=3)
                    ).strftime("%Y/%m/%d %H:%M:%S"),
                }
                fake_self.upper_lines = (
                    [line]
                    if (
                        self.emit_lines
                        and normalized not in self.suppressed_timeframes
                        and trigger_direction == 1
                    )
                    else []
                )
                fake_self.lower_lines = (
                    [line]
                    if (
                        self.emit_lines
                        and normalized not in self.suppressed_timeframes
                        and trigger_direction == -1
                    )
                    else []
                )

        return FakeLineStrengthCal

    def _common_patches(self):
        fake_lines = self._fake_line_class()
        profile = SimpleNamespace(
            is_m5_reversal_target=lambda side, line: True,
        )
        return (
            patch.object(
                sweep,
                "_build_equivalence_candle_analysis",
                return_value=self.fake_ca,
            ),
            patch.object(
                sweep,
                "_build_event_decision_context",
                return_value=self.context,
            ),
            patch.object(
                sweep,
                "_native_m30_bundle",
                return_value=self.m30_bundle,
            ),
            patch.object(sweep, "LineStrengthCal", fake_lines),
            patch("fLineAnalysis.LineStrengthCal", fake_lines),
            patch.object(
                sweep,
                "line_strategy_profile",
                return_value=profile,
            ),
            patch.object(sweep, "_detect_m5_stair_once", return_value={}),
            patch.object(sweep, "detect_h1_stair_trend", return_value={}),
        )

    def _validate(self, require_candidates=True):
        patches = self._common_patches()
        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            patches[4],
            patches[5],
            patches[6],
            patches[7],
        ):
            return sweep.validate_production_context_equivalence(
                self.pair_name,
                self.m5,
                self.m30,
                self.h1,
                [self.decision_index],
                sample_count=1,
                require_candidates=require_candidates,
            )

    def test_sweep_candidates_match_production_orders_for_m5_and_m30(self):
        result = self._validate()

        self.assertEqual(result["checked_decisions"], 1)
        self.assertEqual(result["checked_candidates"], 2)
        self.assertEqual(result["mismatches"], 0)
        self.assertTrue(result["fully_exercised"])
        self.assertEqual(
            result["candidate_evidence_by_timeframe"],
            {"M5": "candidate_compared", "M30": "candidate_compared"},
        )
        self.assertEqual(
            result["peak_history_bars_by_timeframe"],
            {"M5": 180, "M30": 240},
        )
        self.assertEqual(result["policy_id"], "live_trial_m5_m30_v1")
        self.assertEqual(len(self.line_calls), 4)
        for call in self.line_calls:
            self.assertEqual(call["line_history_bars"], 60)
            self.assertTrue(call["enforce_peak_strength_filter"])
            self.assertEqual(call["min_line_peak_count"], 2)
            self.assertEqual(call["min_line_direction_ratio"], 0.7)
        observed_bundles = sorted(
            (
                call["timeframe"],
                call["peak_history_bars"],
                # 平均レンジからの浮動小数点演算を経由するため、
                # 厳密一致ではなく丸めて比較する。
                round(call["group_threshold_pips"], 6),
            )
            for call in self.line_calls
        )
        self.assertEqual(
            observed_bundles,
            sorted([
                ("M5", 180, 5.0),
                ("M5", 180, 5.0),
                ("M30", 240, 10.0),
                ("M30", 240, 10.0),
            ]),
        )

    def test_sell_stop_side_also_matches(self):
        self.context.newest_m5_peak["direction"] = -1

        result = self._validate()

        self.assertEqual(result["checked_candidates"], 2)
        self.assertEqual(result["mismatches"], 0)

    def test_empty_sets_are_equal_but_not_counted_as_evidence(self):
        self.emit_lines = False

        result = self._validate(require_candidates=False)

        self.assertEqual(result["checked_decisions"], 1)
        self.assertEqual(result["checked_candidates"], 0)
        self.assertEqual(
            result["checked_candidates_by_timeframe"],
            {"M5": 0, "M30": 0},
        )
        self.assertFalse(result["fully_exercised"])
        self.assertEqual(
            result["candidate_evidence_by_timeframe"],
            {"M5": "empty_only", "M30": "empty_only"},
        )

    def test_candidate_evidence_is_required_for_each_live_timeframe(self):
        self.suppressed_timeframes.add("M30")

        with self.assertRaisesRegex(ValueError, "M30"):
            self._validate(require_candidates=True)

    def test_equivalence_check_fails_when_production_stop_price_drifts(self):
        original_builder = live_breakout.build_orders_for_decision

        def drifted_builder(*args, **kwargs):
            orders = original_builder(*args, **kwargs)
            orders[0].exe_order_plan["target_price"] += self.pair.pip_value
            return orders

        patches = self._common_patches()
        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            patches[4],
            patches[5],
            patches[6],
            patches[7],
            patch.object(
                live_breakout,
                "build_orders_for_decision",
                side_effect=drifted_builder,
            ),
        ):
            with self.assertRaisesRegex(ValueError, "field=target_price"):
                sweep.validate_production_context_equivalence(
                    self.pair_name,
                    self.m5,
                    self.m30,
                    self.h1,
                    [self.decision_index],
                    sample_count=1,
                )

    def test_forming_and_future_rows_are_not_completed_input(self):
        cases = (
            ("M5", self.m5, pd.Timedelta(minutes=5)),
            ("M30", self.m30, pd.Timedelta(minutes=30)),
            ("H1", self.h1, pd.Timedelta(hours=1)),
        )
        for label, frame, duration in cases:
            with self.subTest(timeframe=label):
                forming = self._frame(
                    pd.DatetimeIndex([self.decision_time]),
                    width_pips=999.0,
                )
                future = self._frame(
                    pd.DatetimeIndex([self.decision_time + duration]),
                    width_pips=999.0,
                )
                source = pd.concat(
                    [frame, forming, future],
                    ignore_index=True,
                ).drop_duplicates("time_jp_dt", keep="last")
                causal = sweep._causal_frame_for_equivalence(
                    source,
                    self.decision_time,
                    label,
                )
                completed_df_r = candleAnalysis.select_completed_df_r(
                    causal,
                    self.decision_time,
                    duration,
                )

                self.assertEqual(
                    causal["time_jp_dt"].max(),
                    self.decision_time,
                )
                self.assertEqual(
                    completed_df_r.iloc[0]["time_jp_dt"],
                    self.decision_time - duration,
                )
                self.assertFalse(
                    (
                        completed_df_r["time_jp_dt"] + duration
                        > self.decision_time
                    ).any()
                )

    def test_causal_row_limit_keeps_latest_rows_for_any_input_order(self):
        source = self._frame(
            pd.date_range(
                end=self.decision_time,
                periods=6,
                freq="5min",
            ),
            width_pips=10.0,
        )
        expected_times = source["time_jp_dt"].tail(3).tolist()
        input_orders = (
            source,
            source.iloc[::-1],
            source.iloc[[2, 5, 0, 4, 1, 3]],
        )

        for case_number, input_frame in enumerate(input_orders, start=1):
            with self.subTest(case_number=case_number):
                causal = sweep._causal_frame_for_equivalence(
                    input_frame,
                    self.decision_time,
                    "M5",
                    row_limit=3,
                )

                self.assertEqual(causal["time_jp_dt"].tolist(), expected_times)


if __name__ == "__main__":
    unittest.main()
