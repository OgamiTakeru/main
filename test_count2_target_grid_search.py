import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pandas as pd

import fGeneric as gene
from count2_resistance_sweep import LimitPathInspector, prepare_s5
from count2_target_grid_search import (
    Condition,
    GridAccumulator,
    GridRecord,
    _event_snapshot_signature,
    _is_complete_market_window,
    _new_metric_state,
    _new_monthly_state,
    _number_list,
    _outcome_matrices,
    adjusted_entry_parameters,
    aggregate_row,
    build_grid_combos,
    condition_memberships,
    inspect_common_entry_window,
    inspect_entry_thresholds,
    load_foot2_event_ledger,
    parse_args,
    run_grid_search,
    write_aggregate_monthly,
)


def _args(**overrides):
    values = {
        "entry_ranks": (1,),
        "entry_offset_range_multipliers": (0.0,),
        "tp_range_multipliers": (1.0, 2.0, 3.0, 5.0),
        "lc_range_multipliers": (1.0, 2.0, 3.0, 5.0),
        "min_target_pips": 0.1,
        "risk_yen": 50.0,
        "start": pd.Timestamp("2025-01-01 00:00:00"),
        "end": pd.Timestamp("2025-01-08 00:00:00"),
        "min_completed": 1,
        "min_rr": 0.1,
        "min_profit_factor": 0.1,
        "min_outcome_coverage": 0.1,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _s5_frame(rows):
    return prepare_s5(
        pd.DataFrame(
            [
                {
                    "time_jp": pd.Timestamp(timestamp).strftime(
                        "%Y/%m/%d %H:%M:%S"
                    ),
                    "open": open_price,
                    "close": close_price,
                    "high": high_price,
                    "low": low_price,
                }
                for (
                    timestamp,
                    open_price,
                    close_price,
                    high_price,
                    low_price,
                ) in rows
            ]
        )
    )


def _threshold_path_rows(direction, *, entry_price=100.0):
    """Build mirrored BUY/SELL paths expressed in favorable/adverse pips."""
    pair = gene.currency_pair("USD_JPY")
    start = pd.Timestamp("2025-01-06 09:00:00")
    shapes = [
        # open, close, favorable high, adverse low -- all in BUY pips.
        (0.0, 0.0, 0.5, 0.0),
        (0.0, 0.2, 1.5, -0.5),
        (0.2, 0.4, 2.5, -1.5),
        (0.4, 0.5, 3.5, -2.5),
        # Extra rows let a spread-aware intrabar fill at index 1 retain a
        # complete one-minute horizon. The zero-spread case ignores them.
        *((0.5, 0.5, 0.8, -0.2) for _ in range(10)),
    ]
    rows = []
    for index, (open_pips, close_pips, high_pips, low_pips) in enumerate(
        shapes
    ):
        if direction == 1:
            open_price = entry_price + pair.pips_to_price(open_pips)
            close_price = entry_price + pair.pips_to_price(close_pips)
            high_price = entry_price + pair.pips_to_price(high_pips)
            low_price = entry_price + pair.pips_to_price(low_pips)
        else:
            # Mirror the BUY candle about entry so favorable and adverse
            # threshold timing is identical for SELL.
            open_price = entry_price - pair.pips_to_price(open_pips)
            close_price = entry_price - pair.pips_to_price(close_pips)
            high_price = entry_price - pair.pips_to_price(low_pips)
            low_price = entry_price - pair.pips_to_price(high_pips)
        rows.append(
            (
                start + pd.Timedelta(seconds=5 * index),
                pair.round_price(open_price),
                pair.round_price(close_price),
                pair.round_price(high_price),
                pair.round_price(low_price),
            )
        )
    return start, rows


def _rows_from_pip_shapes(
    direction,
    timed_shapes,
    *,
    entry_price=100.0,
    start=pd.Timestamp("2025-01-06 09:00:00"),
):
    """Convert BUY-relative pip shapes into mirrored USD/JPY S5 rows."""
    pair = gene.currency_pair("USD_JPY")
    rows = []
    for seconds, (open_pips, close_pips, high_pips, low_pips) in timed_shapes:
        if direction == 1:
            open_price = entry_price + pair.pips_to_price(open_pips)
            close_price = entry_price + pair.pips_to_price(close_pips)
            high_price = entry_price + pair.pips_to_price(high_pips)
            low_price = entry_price + pair.pips_to_price(low_pips)
        else:
            open_price = entry_price - pair.pips_to_price(open_pips)
            close_price = entry_price - pair.pips_to_price(close_pips)
            high_price = entry_price - pair.pips_to_price(low_pips)
            low_price = entry_price - pair.pips_to_price(high_pips)
        rows.append(
            (
                start + pd.Timedelta(seconds=seconds),
                pair.round_price(open_price),
                pair.round_price(close_price),
                pair.round_price(high_price),
                pair.round_price(low_price),
            )
        )
    return start, rows


def _event_ledger_row(
    decision_time,
    *,
    event_status,
    candidate_count,
    peak_direction=1,
):
    decision_time = pd.Timestamp(decision_time)
    return {
        "event_id": f"USD_JPY_{decision_time:%Y%m%d%H%M%S}",
        "pair": "USD_JPY",
        "decision_time": decision_time,
        "next_count2_time": decision_time + pd.Timedelta(minutes=5),
        "tp_lookback": 6,
        "tp_multiplier": 3.0,
        "tp_pips": 6.0,
        "target_valid": True,
        "target_source_first_time": decision_time - pd.Timedelta(minutes=30),
        "target_source_last_time": decision_time - pd.Timedelta(minutes=5),
        "recent_m5_avg_range_pips": 2.0,
        "peak_count": 2,
        "peak_direction": peak_direction,
        "peak_latest_time": decision_time - pd.Timedelta(minutes=5),
        "decision_price": 100.0,
        "rsi_1": 45.0,
        "rsi_2": 50.0,
        "rsi_3": 55.0,
        "m5_stair_profile_enabled": True,
        "m5_stair_state": "NONE",
        "h1_stair_profile_enabled": True,
        "h1_stair_state": "NONE",
        "event_status": event_status,
        "candidate_count": candidate_count,
    }


class GridCliAndCombinationTest(unittest.TestCase):
    def test_number_lists_are_deduplicated_without_reordering(self):
        self.assertEqual(
            _number_list("3,1,3,2", name="ranks", positive=True, integer=True),
            (3, 1, 2),
        )
        self.assertEqual(
            _number_list("0.25,-0.25,0.25,0", name="offsets"),
            (0.25, -0.25, 0.0),
        )

    def test_cli_normalizes_lists_and_rejects_invalid_values(self):
        args = parse_args(
            [
                "--start",
                "2025-01-01",
                "--end",
                "2026-01-01",
                "--entry-ranks",
                "3,1,3",
                "--entry-offset-range-multipliers=0.25,-0.25,0.25",
                "--tp-range-multipliers",
                "1,2,1",
                "--lc-range-multipliers",
                "0.75,1.5,0.75",
            ]
        )
        self.assertEqual(args.entry_ranks, (3, 1))
        self.assertEqual(args.entry_offset_range_multipliers, (0.25, -0.25))
        self.assertEqual(args.tp_range_multipliers, (1.0, 2.0))
        self.assertEqual(args.lc_range_multipliers, (0.75, 1.5))

        invalid = (
            ("--entry-ranks", "0"),
            ("--entry-ranks", "1.5"),
            ("--entry-offset-range-multipliers", "0,,1"),
            ("--tp-range-multipliers", "0"),
            ("--lc-range-multipliers", "nan"),
        )
        for flag, value in invalid:
            with self.subTest(flag=flag, value=value):
                with (
                    contextlib.redirect_stderr(io.StringIO()),
                    self.assertRaises(SystemExit),
                ):
                    parse_args([flag, value])

    def test_build_grid_combos_is_complete_unique_and_prefix_addressable(self):
        args = _args(
            entry_ranks=(1, 3),
            entry_offset_range_multipliers=(-0.25, 0.0),
            tp_range_multipliers=(1.0, 2.0),
            lc_range_multipliers=(0.5, 1.0, 2.0),
        )
        combos, prefixes = build_grid_combos(args)

        self.assertEqual(len(combos), 2 * 2 * 2 * 3)
        self.assertEqual(
            [combo.combo_index for combo in combos], list(range(len(combos)))
        )
        self.assertEqual(len({combo.combo_id for combo in combos}), len(combos))
        self.assertEqual(set(prefixes), {(1, 0), (1, 1), (3, 0), (3, 1)})
        for indices in prefixes.values():
            self.assertEqual(len(indices), 2 * 3)
        target = next(
            combo
            for combo in combos
            if combo.entry_rank == 3
            and combo.offset_range_multiplier == -0.25
            and combo.tp_range_multiplier == 2.0
            and combo.lc_range_multiplier == 0.5
        )
        self.assertEqual(target.configured_rr, 4.0)


class ClosedMarketWindowCompletionTest(unittest.TestCase):
    @staticmethod
    def _inspector(times, price=148.47):
        inspector = object.__new__(LimitPathInspector)
        inspector.pair = gene.currency_pair("USD_JPY")
        inspector.times = np.asarray(times, dtype="datetime64[ns]")
        values = np.full(len(times), price, dtype=float)
        inspector.opens = values.copy()
        inspector.closes = values.copy()
        inspector.highs = values.copy()
        inspector.lows = values.copy()
        return inspector

    def test_daily_maintenance_tail_completes_unfilled_pending_order(self):
        decision = pd.Timestamp("2025-07-30 05:55:00")
        expiry = pd.Timestamp("2025-07-30 06:00:00")
        common_end = pd.Timestamp("2025-07-30 07:00:00")
        before_maintenance = pd.date_range(
            decision,
            pd.Timestamp("2025-07-30 05:59:05"),
            freq="5s",
        )
        after_maintenance = pd.date_range(
            pd.Timestamp("2025-07-30 06:04:55"),
            common_end - pd.Timedelta(seconds=5),
            freq="5s",
        )
        inspector = self._inspector(before_maintenance.append(after_maintenance))

        observed_common_end, common_complete = inspect_common_entry_window(
            inspector,
            decision_time=decision,
            expiry_time=expiry,
            horizon_minutes=60,
        )
        path = inspect_entry_thresholds(
            inspector,
            decision_time=decision,
            expiry_time=expiry,
            direction=-1,
            entry_price=148.49,
            tp_pips=np.asarray([2.0]),
            lc_pips=np.asarray([2.0]),
            horizon_minutes=60,
            spread_pips=0.8,
        )

        self.assertEqual(observed_common_end, common_end)
        self.assertTrue(common_complete)
        self.assertEqual(path["path_status"], "not_filled")
        self.assertTrue(path["pending_path_complete"])
        self.assertFalse(path["filled"])

    def test_unknown_open_market_tail_remains_incomplete(self):
        start = pd.Timestamp("2025-07-30 05:55:00")
        end = pd.Timestamp("2025-07-30 05:56:00")
        times = pd.date_range(
            start,
            pd.Timestamp("2025-07-30 05:55:45"),
            freq="5s",
        ).to_numpy(dtype="datetime64[ns]")
        self.assertFalse(_is_complete_market_window(times, start, end))


class CompactFirstHitGoldenTest(unittest.TestCase):
    def _compare_direction(self, direction, *, spread_pips=0.0):
        pair = gene.currency_pair("USD_JPY")
        decision_time, rows = _threshold_path_rows(direction)
        inspector = LimitPathInspector(_s5_frame(rows), pair)
        expiry_time = decision_time + pd.Timedelta(seconds=10)
        thresholds = np.asarray([1.0, 2.0, 3.0, 5.0])
        args = _args(
            tp_range_multipliers=tuple(thresholds),
            lc_range_multipliers=tuple(thresholds),
        )
        compact = inspect_entry_thresholds(
            inspector,
            decision_time=decision_time,
            expiry_time=expiry_time,
            direction=direction,
            entry_price=100.0,
            tp_pips=thresholds,
            lc_pips=thresholds,
            horizon_minutes=1,
            spread_pips=spread_pips,
        )
        record = GridRecord(
            event_id=f"golden_{direction}",
            decision_time=decision_time,
            expiry_time=expiry_time,
            entry_rank=1,
            offset_index=0,
            offset_range_multiplier=0.0,
            offset_pips=0.0,
            average_range_pips=1.0,
            tp_pips=thresholds,
            lc_pips=thresholds,
            path=compact,
            conditions=[Condition("ALL::all::all", "ALL", "all", "all", "all")],
        )
        metrics, masks, cohorts = _outcome_matrices([record], args, pair)

        combo_index = 0
        for tp_pips in thresholds:
            for lc_pips in thresholds:
                with self.subTest(
                    direction=direction, tp_pips=tp_pips, lc_pips=lc_pips
                ):
                    expected = inspector.inspect(
                        decision_time=decision_time,
                        expiry_time=expiry_time,
                        direction=direction,
                        line_price=100.0,
                        tp_pips=float(tp_pips),
                        lc_pips=float(lc_pips),
                        horizon_minutes=1,
                        spread_pips=spread_pips,
                    )
                    self.assertTrue(masks["full"][0, combo_index])
                    self.assertTrue(cohorts["full"][0, combo_index])
                    self.assertEqual(metrics["known_count"][0, combo_index], 1)
                    self.assertEqual(
                        metrics["completed_count"][0, combo_index], 1
                    )
                    self.assertEqual(
                        metrics["tp_count"][0, combo_index],
                        1 if expected["candidate_result"] == "tp" else 0,
                    )
                    self.assertEqual(
                        metrics["lc_count"][0, combo_index],
                        1
                        if expected["candidate_result"]
                        in {"lc", "both_same_s5_lc_assumed"}
                        else 0,
                    )
                    self.assertEqual(
                        metrics["timeout_count"][0, combo_index],
                        1 if expected["candidate_result"] == "timeout" else 0,
                    )
                    self.assertEqual(
                        metrics["same_s5_lc_count"][0, combo_index],
                        1
                        if expected["candidate_result"]
                        == "both_same_s5_lc_assumed"
                        else 0,
                    )
                    self.assertEqual(
                        metrics["fill_bar_tp_ambiguous_count"][
                            0, combo_index
                        ],
                        1 if expected["fill_bar_tp_ambiguous"] else 0,
                    )
                    self.assertAlmostEqual(
                        metrics["sum_pips"][0, combo_index],
                        expected["trade_result_pips"],
                        places=7,
                    )
                    self.assertAlmostEqual(
                        metrics["sum_r"][0, combo_index],
                        expected["result_r"],
                        places=7,
                    )
                    tp_index = combo_index // len(thresholds)
                    lc_index = combo_index % len(thresholds)
                    if expected["candidate_result"] == "tp":
                        self.assertEqual(
                            pd.Timestamp(expected["exit_time"]),
                            pd.Timestamp(compact["tp_first_time"][tp_index]),
                        )
                    elif expected["candidate_result"] in {
                        "lc",
                        "both_same_s5_lc_assumed",
                    }:
                        self.assertEqual(
                            pd.Timestamp(expected["exit_time"]),
                            pd.Timestamp(compact["lc_first_time"][lc_index]),
                        )
                    else:
                        self.assertEqual(
                            pd.Timestamp(expected["exit_time"]),
                            pd.Timestamp(compact["timeout_exit_time"]),
                        )
                    combo_index += 1

        # TP=2 and LC=1 first touch together on the third S5 candle. LC must win.
        same_s5_index = 1 * len(thresholds) + 0
        self.assertEqual(metrics["same_s5_lc_count"][0, same_s5_index], 1)
        self.assertEqual(metrics["lc_count"][0, same_s5_index], 1)
        self.assertEqual(metrics["tp_count"][0, same_s5_index], 0)

    def test_compact_first_hits_match_limit_inspector_for_every_buy_combo(self):
        self._compare_direction(1)

    def test_compact_first_hits_match_limit_inspector_for_every_sell_combo(self):
        self._compare_direction(-1)

    def test_spread_0_8_matches_limit_inspector_for_buy_and_sell(self):
        for direction in (1, -1):
            with self.subTest(direction=direction):
                self._compare_direction(direction, spread_pips=0.8)

    def test_intrabar_fill_tp_wick_without_close_confirmation_is_not_tp(self):
        pair = gene.currency_pair("USD_JPY")
        quiet = (0.0, 0.0, 0.5, -0.5)
        timed_shapes = [
            (0, (0.5, 0.0, 1.5, 0.0)),
            *((index * 5, quiet) for index in range(1, 12)),
        ]
        for direction in (1, -1):
            with self.subTest(direction=direction):
                decision_time, rows = _rows_from_pip_shapes(
                    direction, timed_shapes
                )
                inspector = LimitPathInspector(_s5_frame(rows), pair)
                expiry_time = decision_time + pd.Timedelta(seconds=10)
                tp_pips = np.asarray([1.0])
                lc_pips = np.asarray([5.0])
                compact = inspect_entry_thresholds(
                    inspector,
                    decision_time=decision_time,
                    expiry_time=expiry_time,
                    direction=direction,
                    entry_price=100.0,
                    tp_pips=tp_pips,
                    lc_pips=lc_pips,
                    horizon_minutes=1,
                    spread_pips=0.0,
                )
                expected = inspector.inspect(
                    decision_time=decision_time,
                    expiry_time=expiry_time,
                    direction=direction,
                    line_price=100.0,
                    tp_pips=1.0,
                    lc_pips=5.0,
                    horizon_minutes=1,
                    spread_pips=0.0,
                )
                record = GridRecord(
                    event_id=f"wick_only_{direction}",
                    decision_time=decision_time,
                    expiry_time=expiry_time,
                    entry_rank=1,
                    offset_index=0,
                    offset_range_multiplier=0.0,
                    offset_pips=0.0,
                    average_range_pips=1.0,
                    tp_pips=tp_pips,
                    lc_pips=lc_pips,
                    path=compact,
                    conditions=[],
                )
                metrics, _, _ = _outcome_matrices(
                    [record],
                    _args(
                        tp_range_multipliers=(1.0,),
                        lc_range_multipliers=(5.0,),
                    ),
                    pair,
                )

                self.assertFalse(compact["fill_at_bar_open"])
                self.assertTrue(compact["tp_touch_on_fill_bar"][0])
                self.assertFalse(compact["tp_fill_confirmed"][0])
                self.assertTrue(compact["tp_raw_reached"][0])
                self.assertEqual(compact["tp_raw_first_index"][0], 0)
                self.assertFalse(compact["tp_reached"][0])
                self.assertEqual(compact["tp_first_index"][0], -1)
                self.assertTrue(expected["fill_bar_tp_ambiguous"])
                self.assertEqual(expected["candidate_result"], "timeout")
                self.assertEqual(metrics["tp_count"][0, 0], 0)
                self.assertEqual(metrics["timeout_count"][0, 0], 1)
                self.assertEqual(
                    metrics["fill_bar_tp_ambiguous_count"][0, 0], 1
                )

    def test_raw_tp_and_lc_on_intrabar_fill_s5_is_lc_assumed(self):
        pair = gene.currency_pair("USD_JPY")
        quiet = (0.0, 0.0, 0.5, -0.5)
        timed_shapes = [
            (0, (0.5, 0.0, 1.5, -1.5)),
            *((index * 5, quiet) for index in range(1, 12)),
        ]
        for direction in (1, -1):
            with self.subTest(direction=direction):
                decision_time, rows = _rows_from_pip_shapes(
                    direction, timed_shapes
                )
                inspector = LimitPathInspector(_s5_frame(rows), pair)
                expiry_time = decision_time + pd.Timedelta(seconds=10)
                widths = np.asarray([1.0])
                compact = inspect_entry_thresholds(
                    inspector,
                    decision_time=decision_time,
                    expiry_time=expiry_time,
                    direction=direction,
                    entry_price=100.0,
                    tp_pips=widths,
                    lc_pips=widths,
                    horizon_minutes=1,
                    spread_pips=0.0,
                )
                expected = inspector.inspect(
                    decision_time=decision_time,
                    expiry_time=expiry_time,
                    direction=direction,
                    line_price=100.0,
                    tp_pips=1.0,
                    lc_pips=1.0,
                    horizon_minutes=1,
                    spread_pips=0.0,
                )
                record = GridRecord(
                    event_id=f"fill_both_{direction}",
                    decision_time=decision_time,
                    expiry_time=expiry_time,
                    entry_rank=1,
                    offset_index=0,
                    offset_range_multiplier=0.0,
                    offset_pips=0.0,
                    average_range_pips=1.0,
                    tp_pips=widths,
                    lc_pips=widths,
                    path=compact,
                    conditions=[],
                )
                metrics, _, _ = _outcome_matrices(
                    [record],
                    _args(
                        tp_range_multipliers=(1.0,),
                        lc_range_multipliers=(1.0,),
                    ),
                    pair,
                )

                self.assertFalse(compact["fill_at_bar_open"])
                self.assertTrue(compact["tp_touch_on_fill_bar"][0])
                self.assertTrue(compact["lc_touch_on_fill_bar"][0])
                self.assertEqual(compact["tp_raw_first_index"][0], 0)
                self.assertEqual(compact["lc_raw_first_index"][0], 0)
                self.assertEqual(
                    expected["candidate_result"],
                    "both_same_s5_lc_assumed",
                )
                self.assertEqual(metrics["same_s5_lc_count"][0, 0], 1)
                self.assertEqual(metrics["lc_count"][0, 0], 1)
                self.assertEqual(metrics["tp_count"][0, 0], 0)
                self.assertEqual(metrics["sum_pips"][0, 0], -1.0)

    def test_touch_after_unknown_s5_gap_is_not_reached(self):
        pair = gene.currency_pair("USD_JPY")
        timed_shapes = [
            (0, (0.0, 0.0, 0.5, 0.0)),
            (5, (0.0, 0.0, 0.5, -0.5)),
            # 10 seconds is missing. The TP touch after that unknown gap
            # must remain raw evidence only, not a usable outcome.
            (15, (0.0, 0.0, 2.5, -0.5)),
            (20, (0.0, 0.0, 0.5, -0.5)),
        ]
        for direction in (1, -1):
            with self.subTest(direction=direction):
                decision_time, rows = _rows_from_pip_shapes(
                    direction, timed_shapes
                )
                inspector = LimitPathInspector(_s5_frame(rows), pair)
                expiry_time = decision_time + pd.Timedelta(seconds=10)
                tp_pips = np.asarray([2.0])
                lc_pips = np.asarray([5.0])
                compact = inspect_entry_thresholds(
                    inspector,
                    decision_time=decision_time,
                    expiry_time=expiry_time,
                    direction=direction,
                    entry_price=100.0,
                    tp_pips=tp_pips,
                    lc_pips=lc_pips,
                    horizon_minutes=1,
                    spread_pips=0.0,
                )
                expected = inspector.inspect(
                    decision_time=decision_time,
                    expiry_time=expiry_time,
                    direction=direction,
                    line_price=100.0,
                    tp_pips=2.0,
                    lc_pips=5.0,
                    horizon_minutes=1,
                    spread_pips=0.0,
                )
                record = GridRecord(
                    event_id=f"unknown_gap_{direction}",
                    decision_time=decision_time,
                    expiry_time=expiry_time,
                    entry_rank=1,
                    offset_index=0,
                    offset_range_multiplier=0.0,
                    offset_pips=0.0,
                    average_range_pips=1.0,
                    tp_pips=tp_pips,
                    lc_pips=lc_pips,
                    path=compact,
                    conditions=[],
                )
                metrics, _, cohorts = _outcome_matrices(
                    [record],
                    _args(
                        tp_range_multipliers=(2.0,),
                        lc_range_multipliers=(5.0,),
                    ),
                    pair,
                )

                self.assertEqual(compact["first_invalid_position_index"], 2)
                self.assertTrue(compact["tp_raw_reached"][0])
                self.assertEqual(compact["tp_raw_first_index"][0], 2)
                self.assertFalse(compact["tp_reached"][0])
                self.assertEqual(expected["candidate_result"], "incomplete_horizon")
                self.assertEqual(metrics["known_count"][0, 0], 0)
                self.assertEqual(metrics["unresolved_count"][0, 0], 1)
                self.assertFalse(cohorts["full"][0, 0])

    def test_common_full_horizon_purges_every_tp_lc_combo(self):
        pair = gene.currency_pair("USD_JPY")
        decision_time, rows = _threshold_path_rows(1)
        inspector = LimitPathInspector(_s5_frame(rows), pair)
        expiry_time = decision_time + pd.Timedelta(seconds=10)
        thresholds = np.asarray([1.0, 2.0, 3.0, 5.0])
        compact = inspect_entry_thresholds(
            inspector,
            decision_time=decision_time,
            expiry_time=expiry_time,
            direction=1,
            entry_price=100.0,
            tp_pips=thresholds,
            lc_pips=thresholds,
            horizon_minutes=1,
            spread_pips=0.0,
        )
        record = GridRecord(
            event_id="boundary",
            decision_time=decision_time,
            expiry_time=expiry_time,
            entry_rank=1,
            offset_index=0,
            offset_range_multiplier=0.0,
            offset_pips=0.0,
            average_range_pips=1.0,
            tp_pips=thresholds,
            lc_pips=thresholds,
            path=compact,
            conditions=[],
        )

        crossing_args = _args(
            tp_range_multipliers=tuple(thresholds),
            lc_range_multipliers=tuple(thresholds),
            end=decision_time + pd.Timedelta(seconds=30),
        )
        _, crossing_masks, crossing_cohorts = _outcome_matrices(
            [record], crossing_args, pair
        )
        self.assertTrue(crossing_masks["full"].all())
        self.assertTrue(crossing_masks["full"].all())
        self.assertFalse(crossing_cohorts["full"].any())

        complete_args = _args(
            tp_range_multipliers=tuple(thresholds),
            lc_range_multipliers=tuple(thresholds),
            end=decision_time + pd.Timedelta(minutes=1),
        )
        _, complete_masks, complete_cohorts = _outcome_matrices(
            [record], complete_args, pair
        )
        self.assertTrue(complete_masks["full"].all())
        self.assertTrue(complete_cohorts["full"].all())

    def test_explicit_common_entry_window_unifies_offsets_and_fill_times(self):
        pair = gene.currency_pair("USD_JPY")
        timed_shapes = [
            (
                index * 5,
                (0.0, 0.0, 0.5, -2.0 if index == 1 else 0.0),
            )
            for index in range(14)
        ]
        decision_time, rows = _rows_from_pip_shapes(1, timed_shapes)
        inspector = LimitPathInspector(_s5_frame(rows), pair)
        expiry_time = decision_time + pd.Timedelta(seconds=10)
        common_end, common_complete = inspect_common_entry_window(
            inspector,
            decision_time=decision_time,
            expiry_time=expiry_time,
            horizon_minutes=1,
        )
        widths = np.asarray([20.0])
        records = []
        for offset_index, (entry_price, offset_pips) in enumerate(
            ((100.0, 0.0), (99.98, 2.0))
        ):
            path = inspect_entry_thresholds(
                inspector,
                decision_time=decision_time,
                expiry_time=expiry_time,
                direction=1,
                entry_price=entry_price,
                tp_pips=widths,
                lc_pips=widths,
                horizon_minutes=1,
                spread_pips=0.0,
            )
            records.append(
                GridRecord(
                    event_id="common_window",
                    decision_time=decision_time,
                    expiry_time=expiry_time,
                    entry_rank=1,
                    offset_index=offset_index,
                    offset_range_multiplier=float(offset_index),
                    offset_pips=offset_pips,
                    average_range_pips=2.0,
                    tp_pips=widths,
                    lc_pips=widths,
                    path=path,
                    conditions=[],
                    common_path_end=common_end,
                    common_path_complete=common_complete,
                )
            )

        self.assertTrue(common_complete)
        self.assertNotEqual(
            records[0].path["fill_time"], records[1].path["fill_time"]
        )
        self.assertEqual(
            records[0].common_path_end, records[1].common_path_end
        )

        crossing_args = _args(
            tp_range_multipliers=(20.0,),
            lc_range_multipliers=(20.0,),
            end=common_end - pd.Timedelta(seconds=5),
        )
        complete_args = _args(
            tp_range_multipliers=(20.0,),
            lc_range_multipliers=(20.0,),
            end=common_end,
        )
        for record in records:
            with self.subTest(offset_index=record.offset_index):
                _, crossing_segments, crossing_cohorts = _outcome_matrices(
                    [record], crossing_args, pair
                )
                self.assertTrue(crossing_segments["full"][0, 0])
                self.assertFalse(crossing_cohorts["full"][0, 0])
                _, complete_segments, complete_cohorts = _outcome_matrices(
                    [record], complete_args, pair
                )
                self.assertTrue(complete_segments["full"][0, 0])
                self.assertTrue(complete_cohorts["full"][0, 0])


class ConditionTerminologyTest(unittest.TestCase):
    def test_foot_peaks_and_core_peak_use_the_registered_meanings(self):
        conditions = {
            item.condition_id: item
            for item in condition_memberships(
                {
                    "decision_time": "2025-01-06 09:00:00",
                    "peak_count": 2,
                    "line_count": 5,
                    "line_core_count": 3,
                }
            )
        }

        foot = conditions["FOOT::foot_count::2"]
        peaks = conditions["LINE::peaks_count::5"]
        core = conditions["LINE::core_peak::3"]
        self.assertEqual(
            (foot.field, foot.value, foot.label),
            ("foot_count", "2", "foot count"),
        )
        self.assertEqual(
            (peaks.field, peaks.value, peaks.label),
            ("peaks_count", "5", "peaks count"),
        )
        self.assertEqual(
            (core.field, core.value, core.label),
            ("core_peak", "3", "core peak"),
        )

    def test_policy_and_top15_columns_are_not_search_conditions(self):
        supplied_policy_fields = {
            "current_policy_reversal_target": True,
            "current_policy_live_eligible": True,
            "current_policy_live_selected": True,
            "counterfactual_predict_candidate_rank": 1,
            "predict_reversal_top15_matches": "condition_a|condition_b",
            "predict_reversal_top15_match_count": 2,
        }
        conditions = condition_memberships(
            {
                "decision_time": "2025-01-06 09:00:00",
                "peak_count": 2,
                "line_count": 5,
                "line_core_count": 3,
                **supplied_policy_fields,
            }
        )
        condition_fields = {item.field for item in conditions}

        self.assertFalse(any(item.source == "USD_POLICY" for item in conditions))
        for field in supplied_policy_fields:
            with self.subTest(field=field):
                self.assertNotIn(field, condition_fields)


class EventLedgerDenominatorTest(unittest.TestCase):
    def test_no_candidates_counts_in_foot2_and_per_foot2_denominators(self):
        first = pd.Timestamp("2025-01-06 09:00:00")
        event_rows = [
            _event_ledger_row(
                first,
                event_status="evaluated",
                candidate_count=1,
                peak_direction=1,
            ),
            _event_ledger_row(
                first + pd.Timedelta(minutes=5),
                event_status="no_candidates",
                candidate_count=0,
                peak_direction=-1,
            ),
        ]
        with tempfile.TemporaryDirectory() as folder:
            event_path = Path(folder) / "events.csv"
            pd.DataFrame(event_rows).to_csv(event_path, index=False)
            args = _args(
                source_events=event_path,
                read_chunk_size=10,
                entry_ranks=(1,),
                entry_offset_range_multipliers=(0.0,),
                tp_range_multipliers=(1.0,),
                lc_range_multipliers=(1.0,),
            )
            counts, ledger, stats = load_foot2_event_ledger(args)

        all_id = "ALL::all::all"
        self.assertEqual(counts[("full", all_id)], 2)
        self.assertEqual(len(ledger), 2)
        self.assertEqual(ledger[event_rows[1]["event_id"]][2], 0)
        self.assertEqual(
            stats["valid_foot2_events_including_no_candidates"], 2
        )

        combos, prefixes = build_grid_combos(args)
        accumulator = GridAccumulator(
            args,
            gene.currency_pair("USD_JPY"),
            combos,
            prefixes,
        )
        accumulator.foot2_event_counts = counts
        condition = Condition(all_id, "ALL", "all", "all", "all")
        accumulator.catalog[all_id] = condition
        state = _new_metric_state(len(combos))
        state["signal_count"][0] = 1
        state["eligible_count"][0] = 1
        state["known_count"][0] = 1
        state["completed_count"][0] = 1
        state["positive_count"][0] = 1
        state["sum_r"][0] = 0.6
        state["sum_pips"][0] = 6.0
        state["sum_yen"][0] = 30.0
        state["gross_profit_r"][0] = 0.6
        state["positive_pips_sum"][0] = 6.0
        state["positive_pips_count"][0] = 1
        state["tp_pips_sum"][0] = 6.0
        state["lc_pips_sum"][0] = 10.0
        state["effective_rr_sum"][0] = 0.6
        accumulator.states[("full", all_id)] = state

        row = aggregate_row(
            accumulator,
            segment="full",
            condition_id=all_id,
            combo_index=0,
            monthly_summary={},
        )
        self.assertEqual(row["foot2_event_count"], 2)
        self.assertAlmostEqual(row["rank_line_availability_rate"], 0.5)
        self.assertAlmostEqual(
            row["expectancy_r_per_line_opportunity"], 0.6
        )
        self.assertAlmostEqual(row["expectancy_r_per_foot2"], 0.3)


class EventSnapshotDigestTest(unittest.TestCase):
    def test_bool_and_numeric_text_have_the_same_64_character_digest(self):
        decision_time = pd.Timestamp("2025-01-06 09:00:00")
        typed = _event_ledger_row(
            decision_time,
            event_status="evaluated",
            candidate_count=1,
        )
        typed.update(
            {
                "m5_stair_confirmed": True,
                "h1_stair_criterion_pullback_ratio": False,
                "m5_stair_first_pullback_ratio": 0.5,
            }
        )
        textual = dict(typed)
        textual.update(
            {
                "target_valid": "true",
                "m5_stair_profile_enabled": "1",
                "h1_stair_profile_enabled": "yes",
                "m5_stair_confirmed": "true",
                "h1_stair_criterion_pullback_ratio": "0",
                "tp_lookback": "6",
                "tp_multiplier": "3.0",
                "tp_pips": "6.000",
                "recent_m5_avg_range_pips": "2.0",
                "peak_count": "2",
                "peak_direction": "1",
                "decision_price": "100.000",
                "rsi_1": "45.0",
                "rsi_2": "50",
                "rsi_3": "55.000",
                "m5_stair_first_pullback_ratio": "0.500000",
            }
        )

        typed_digest = _event_snapshot_signature(typed)
        textual_digest = _event_snapshot_signature(textual)
        self.assertEqual(typed_digest, textual_digest)
        self.assertEqual(len(typed_digest), 64)
        self.assertTrue(
            all(character in "0123456789abcdef" for character in typed_digest)
        )

    def test_one_causal_field_change_produces_a_different_digest(self):
        decision_time = pd.Timestamp("2025-01-06 09:00:00")
        original = _event_ledger_row(
            decision_time,
            event_status="evaluated",
            candidate_count=1,
        )
        changed = dict(original)
        changed["target_source_last_time"] = (
            pd.Timestamp(original["target_source_last_time"])
            - pd.Timedelta(minutes=5)
        )

        original_digest = _event_snapshot_signature(original)
        changed_digest = _event_snapshot_signature(changed)
        self.assertEqual(len(original_digest), 64)
        self.assertEqual(len(changed_digest), 64)
        self.assertNotEqual(original_digest, changed_digest)


class AggregateMonthlyAllCombinationsTest(unittest.TestCase):
    @staticmethod
    def _populate_state(state, sums):
        for index, value in enumerate(sums):
            state["signal_count"][index] = 10
            state["eligible_count"][index] = 10
            state["known_count"][index] = 10
            state["filled_count"][index] = 10
            state["completed_count"][index] = 10
            state["tp_count"][index] = 5
            state["lc_count"][index] = 5
            state["positive_count"][index] = 5
            state["sum_pips"][index] = value * 10
            state["sum_r"][index] = value
            state["sum_yen"][index] = value * 50
            state["gross_profit_r"][index] = value + 2
            state["gross_loss_r_abs"][index] = 2
            state["positive_pips_sum"][index] = value * 10 + 5
            state["positive_pips_count"][index] = 5
            state["negative_pips_sum"][index] = -5
            state["negative_pips_count"][index] = 5
            state["tp_pips_sum"][index] = 100
            state["lc_pips_sum"][index] = 100
            state["effective_rr_sum"][index] = 10

    def test_every_combination_is_written_without_ranking(self):
        args = _args(
            entry_ranks=(1,),
            entry_offset_range_multipliers=(0.0, 0.25),
            tp_range_multipliers=(1.0,),
            lc_range_multipliers=(1.0,),
        )
        combos, prefixes = build_grid_combos(args)
        accumulator = GridAccumulator(
            args,
            gene.currency_pair("USD_JPY"),
            combos,
            prefixes,
        )
        condition = Condition("ALL::all::all", "ALL", "all", "all", "all")
        accumulator.catalog[condition.condition_id] = condition
        full_state = _new_metric_state(len(combos))
        self._populate_state(full_state, [10.0, 40.0])
        accumulator.states[("full", condition.condition_id)] = full_state
        monthly = _new_monthly_state(len(combos))
        monthly["signal_count"][:] = [2, 3]
        monthly["eligible_count"][:] = [2, 3]
        monthly["known_count"][:] = [2, 3]
        monthly["filled_count"][:] = [2, 3]
        monthly["completed_count"][:] = [2, 3]
        monthly["positive_count"][:] = [1, 2]
        monthly["sum_pips"][:] = [1.0, 4.0]
        monthly["sum_r"][:] = [0.1, 0.4]
        monthly["sum_yen"][:] = [5.0, 20.0]
        monthly["positive_pips_sum"][:] = [2.0, 6.0]
        accumulator.monthly_states[
            ("full", "2025-01", condition.condition_id)
        ] = monthly

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            paths = {
                "aggregate": root / "aggregate.csv",
                "monthly": root / "monthly.csv",
            }
            returned = write_aggregate_monthly(accumulator, paths)
            aggregate_rows = pd.read_csv(returned["aggregate"])
            monthly_rows = pd.read_csv(returned["monthly"])

        self.assertEqual(set(aggregate_rows["combo_index"]), {0, 1})
        self.assertEqual(set(monthly_rows["combo_index"]), {0, 1})
        self.assertNotIn("selection_metric", monthly_rows.columns)


class MarketableLimitSymmetryTest(unittest.TestCase):
    def test_spread_0_8_marketable_mid_distance_boundary_is_symmetric(self):
        pair = gene.currency_pair("USD_JPY")
        cases = (
            # peak direction +1 is the SELL-side resistance search.
            (1, 99.997, 99.995),
            # peak direction -1 is the BUY-side support search.
            (-1, 100.003, 100.005),
        )
        for peak_direction, pending_line, marketable_line in cases:
            with self.subTest(peak_direction=peak_direction):
                pending = adjusted_entry_parameters(
                    line_price=pending_line,
                    decision_price=100.0,
                    peak_direction=peak_direction,
                    average_range_pips=1.0,
                    offset_range_multiplier=0.0,
                    pair=pair,
                    spread_pips=0.8,
                )
                marketable = adjusted_entry_parameters(
                    line_price=marketable_line,
                    decision_price=100.0,
                    peak_direction=peak_direction,
                    average_range_pips=1.0,
                    offset_range_multiplier=0.0,
                    pair=pair,
                    spread_pips=0.8,
                )
                self.assertAlmostEqual(
                    pending["adjusted_distance_pips"], -0.3, places=7
                )
                self.assertFalse(pending["marketable_limit"])
                self.assertAlmostEqual(
                    marketable["adjusted_distance_pips"], -0.5, places=7
                )
                self.assertTrue(marketable["marketable_limit"])

    def test_adjusted_entry_parameters_are_buy_sell_symmetric(self):
        pair = gene.currency_pair("USD_JPY")
        cases = (
            (1, 100.05, -1.0, 99.95, -5.0, True),
            (-1, 99.95, -1.0, 100.05, -5.0, True),
            (1, 100.05, 0.0, 100.05, 5.0, False),
            (-1, 99.95, 0.0, 99.95, 5.0, False),
            (1, 100.05, 1.0, 100.15, 15.0, False),
            (-1, 99.95, 1.0, 99.85, 15.0, False),
        )
        for (
            peak_direction,
            line_price,
            multiplier,
            expected_entry,
            expected_distance,
            expected_marketable,
        ) in cases:
            with self.subTest(
                peak_direction=peak_direction, multiplier=multiplier
            ):
                result = adjusted_entry_parameters(
                    line_price=line_price,
                    decision_price=100.0,
                    peak_direction=peak_direction,
                    average_range_pips=10.0,
                    offset_range_multiplier=multiplier,
                    pair=pair,
                )
                self.assertEqual(result["entry_price"], expected_entry)
                self.assertAlmostEqual(
                    result["adjusted_distance_pips"], expected_distance
                )
                self.assertEqual(
                    result["marketable_limit"], expected_marketable
                )

    def test_buy_and_sell_offsets_are_symmetric_and_marketable_are_excluded(
        self,
    ):
        start = pd.Timestamp("2025-01-06 09:00:00")
        source_rows = [
            {
                "event_id": "USD_JPY_20250106090000",
                "pair": "USD_JPY",
                "decision_time": start,
                "next_count2_time": start + pd.Timedelta(seconds=10),
                "tp_lookback": 6,
                "tp_multiplier": 3.0,
                "tp_pips": 30.0,
                "target_valid": True,
                "target_source_first_time": start - pd.Timedelta(minutes=30),
                "target_source_last_time": start - pd.Timedelta(minutes=5),
                "recent_m5_avg_range_pips": 10.0,
                "peak_count": 2,
                "peak_direction": 1,
                "decision_price": 100.0,
                "candidate_rank": 1,
                "line_price": 100.05,
                "distance_pips": 5.0,
                "trade_direction": -1,
                "trade_side": "SELL",
                "line_count": 5,
                "line_core_count": 3,
                "line_newest_source_time": start - pd.Timedelta(minutes=5),
                "line_timeframe": "M5",
                "line_history_bars": 60,
                "candidate_scope": "all_raw_m5_line_groups_ahead",
                "candidate_pruning_applied": False,
                "pending_expiry_exclusive": True,
                "peak_latest_time": start - pd.Timedelta(minutes=5),
                "m5_stair_profile_enabled": True,
                "m5_stair_state": "NONE",
                "h1_stair_profile_enabled": True,
                "h1_stair_state": "NONE",
                "rsi_1": 50.0,
                "rsi_2": 50.0,
                "rsi_3": 50.0,
                "event_status": "evaluated",
                "candidate_count": 1,
            },
            {
                "event_id": "USD_JPY_20250106090500",
                "pair": "USD_JPY",
                "decision_time": start + pd.Timedelta(minutes=5),
                "next_count2_time": start + pd.Timedelta(minutes=5, seconds=10),
                "tp_lookback": 6,
                "tp_multiplier": 3.0,
                "tp_pips": 30.0,
                "target_valid": True,
                "target_source_first_time": start - pd.Timedelta(minutes=25),
                "target_source_last_time": start,
                "recent_m5_avg_range_pips": 10.0,
                "peak_count": 2,
                "peak_direction": -1,
                "decision_price": 100.0,
                "candidate_rank": 1,
                "line_price": 99.95,
                "distance_pips": 5.0,
                "trade_direction": 1,
                "trade_side": "BUY",
                "line_count": 5,
                "line_core_count": 3,
                "line_newest_source_time": start,
                "line_timeframe": "M5",
                "line_history_bars": 60,
                "candidate_scope": "all_raw_m5_line_groups_ahead",
                "candidate_pruning_applied": False,
                "pending_expiry_exclusive": True,
                "peak_latest_time": start,
                "m5_stair_profile_enabled": True,
                "m5_stair_state": "NONE",
                "h1_stair_profile_enabled": True,
                "h1_stair_state": "NONE",
                "rsi_1": 50.0,
                "rsi_2": 50.0,
                "rsi_3": 50.0,
                "event_status": "evaluated",
                "candidate_count": 1,
            },
        ]
        s5_rows = [
            {
                "time_jp": (start + pd.Timedelta(seconds=offset)).strftime(
                    "%Y/%m/%d %H:%M:%S"
                ),
                "open": 100.0,
                "close": 100.0,
                "high": 100.0,
                "low": 100.0,
            }
            for offset in (0, 5, 300, 305)
        ]

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source_path = root / "source.csv"
            event_path = root / "events.csv"
            s5_path = root / "s5.csv"
            output_dir = root / "output"
            pd.DataFrame(source_rows).to_csv(source_path, index=False)
            pd.DataFrame(source_rows).to_csv(event_path, index=False)
            pd.DataFrame(s5_rows).to_csv(s5_path, index=False)
            args = parse_args(
                [
                    "--start",
                    "2025-01-06",
                    "--end",
                    "2025-01-08",
                    "--source-candidates",
                    str(source_path),
                    "--source-events",
                    str(event_path),
                    "--s5-cache",
                    str(s5_path),
                    "--output-dir",
                    str(output_dir),
                    "--entry-ranks",
                    "1",
                    "--entry-offset-range-multipliers=-1,0,1",
                    "--tp-range-multipliers",
                    "1",
                    "--lc-range-multipliers",
                    "1",
                    "--spread-pips",
                    "0",
                    "--horizon-minutes",
                    "1",
                    "--min-target-pips",
                    "0.1",
                    "--min-completed",
                    "1",
                    "--read-chunk-size",
                    "10",
                ]
            )
            with (
                patch(
                    "count2_target_grid_search.s5_cache_has_no_tick_completion",
                    return_value=True,
                ),
                patch(
                    "count2_target_grid_search._s5_coverage_errors",
                    return_value=[],
                ),
                patch("count2_target_grid_search._notify"),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                paths = run_grid_search(args)

            path_rows = pd.read_csv(paths["paths"])
            manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))

        self.assertEqual(len(path_rows), 6)
        self.assertEqual(manifest["marketable_limit_excluded"], 2)
        self.assertEqual(manifest["source_events"], str(event_path))
        self.assertEqual(
            manifest["event_ledger"][
                "valid_foot2_events_including_no_candidates"
            ],
            2,
        )
        eligible_rows = path_rows[
            ~path_rows["marketable_limit_excluded"].astype(bool)
        ]
        self.assertEqual(
            set(eligible_rows["entry_offset_range_multiplier"]), {0.0, 1.0}
        )
        sell = eligible_rows[eligible_rows["trade_side"] == "SELL"].sort_values(
            "entry_offset_range_multiplier"
        )
        buy = eligible_rows[eligible_rows["trade_side"] == "BUY"].sort_values(
            "entry_offset_range_multiplier"
        )
        np.testing.assert_allclose(
            sell["entry_price"].to_numpy(), [100.05, 100.15]
        )
        np.testing.assert_allclose(
            buy["entry_price"].to_numpy(), [99.95, 99.85]
        )
        np.testing.assert_allclose(
            sell["adjusted_distance_pips"].to_numpy(), [5.0, 15.0]
        )
        np.testing.assert_allclose(
            buy["adjusted_distance_pips"].to_numpy(), [5.0, 15.0]
        )


if __name__ == "__main__":
    unittest.main()
