# 最新更新日時: 2026-08-30 17:44 JST

import dataclasses
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

import double_top_grid_validation as grid_validation
import fAnalysis_order_Main as analysis_main
import fDoubleTopCore as core
import fGeneric as gene
import f_ダブルトップ as live_double_top


class DoubleTopSharedCoreTest(unittest.TestCase):
    def setUp(self):
        self.pair = gene.currency_pair("USD_JPY")
        self.peaks = [
            {
                "direction": -1,
                "count": 3,
                "latest_time": pd.Timestamp("2026-08-27 11:30:00"),
                "peak": 149.98,
            },
            {
                "direction": 1,
                "count": 2,
                "latest_time": pd.Timestamp("2026-08-27 11:00:00"),
                "peak": 150.19,
            },
            {
                "direction": -1,
                "count": 4,
                "latest_time": pd.Timestamp("2026-08-27 10:30:00"),
                "peak": 150.00,
            },
            {
                "direction": 1,
                "count": 3,
                "latest_time": pd.Timestamp("2026-08-27 10:00:00"),
                "peak": 150.20,
            },
        ]
        self.completed_df_r = pd.DataFrame(
            [
                {
                    "time_jp_dt": pd.Timestamp("2026-08-27 11:30:00"),
                    "close": 149.98,
                },
                {
                    "time_jp_dt": pd.Timestamp("2026-08-27 11:25:00"),
                    "close": 150.01,
                },
            ]
        )
        self.context = SimpleNamespace(
            pair=self.pair,
            pair_name="USD_JPY",
            decision_time=pd.Timestamp("2026-08-27 11:35:00"),
            current_price=149.98,
            m5_peaks_class=SimpleNamespace(peaks_original=self.peaks),
            m5_completed_df_r=self.completed_df_r,
        )

    def test_live_adapter_is_explicitly_pinned_to_v1(self):
        self.assertEqual(live_double_top.CORE_VERSION, core.CORE_VERSION_V1)
        self.assertEqual(
            live_double_top.LIVE_TRIAL_POLICY_V1.policy_id,
            "live_trial_v1",
        )
        self.assertIs(
            live_double_top.TRIAL_POLICY,
            live_double_top.LIVE_TRIAL_POLICY_V1,
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            live_double_top.LIVE_TRIAL_POLICY_V1.priority = 30

    def test_live_adapter_and_core_return_the_same_candidate(self):
        direct = core.detect_candidate_v1(
            self.peaks,
            self.completed_df_r.iloc[0],
            self.completed_df_r.iloc[1],
            self.pair,
            live_double_top.LIVE_TRIAL_POLICY_V1,
        )
        through_live = live_double_top.detect_candidate(self.context)
        self.assertIsNotNone(direct)
        self.assertEqual(direct, through_live)
        self.assertEqual(through_live.core_version, core.CORE_VERSION_V1)
        self.assertAlmostEqual(through_live.height_pips, 19.5)
        self.assertAlmostEqual(through_live.top_gap_pips, 1.0)

    def test_shared_order_level_formula(self):
        candidate = live_double_top.detect_candidate(self.context)
        levels = core.build_short_order_levels_v1(
            candidate,
            self.pair,
            self.context.current_price,
            live_double_top.LIVE_TRIAL_POLICY_V1,
        )
        self.assertIsNotNone(levels)
        self.assertEqual(levels.entry_price, 149.98)
        self.assertEqual(levels.target_price, 149.805)
        self.assertEqual(levels.stop_price, 150.21)
        self.assertAlmostEqual(levels.tp_pips, 17.5)
        self.assertAlmostEqual(levels.lc_pips, 23.0)

    def test_live_order_adapter_uses_shared_levels(self):
        candidate = live_double_top.detect_candidate(self.context)
        candle_analysis = SimpleNamespace(
            candle_meta_class=SimpleNamespace(cal_move_ave=lambda _: 0.10),
            base_oa=None,
        )
        order = live_double_top.build_order(
            candidate,
            self.context,
            candle_analysis,
            "inspection",
        )
        self.assertIsNotNone(order)
        plan = order.exe_order_plan
        self.assertEqual(plan["double_top_core_version"], core.CORE_VERSION_V1)
        self.assertEqual(plan["double_top_policy_id"], "live_trial_v1")
        self.assertEqual(plan["double_top_entry_price"], 149.98)
        self.assertAlmostEqual(plan["double_top_tp_pips"], 17.5)
        self.assertAlmostEqual(plan["double_top_lc_pips"], 23.0)

    def test_vectorized_policy_mask_matches_scalar_candidate(self):
        candidate = live_double_top.detect_candidate(self.context)
        frame = pd.DataFrame(
            [
                {
                    "pair": "USD_JPY",
                    "t1_foot_count": candidate.t1_foot_count,
                    "t2_foot_count": candidate.t2_foot_count,
                    "formation_minutes": candidate.t1_t2_minutes,
                    "height_pips": candidate.height_pips,
                    "top_gap_pips": candidate.top_gap_pips,
                    "neckline_price": candidate.neckline_price,
                    "break_close": candidate.break_close,
                    "previous_close": candidate.previous_close,
                },
                {
                    "pair": "USD_JPY",
                    "t1_foot_count": candidate.t1_foot_count,
                    "t2_foot_count": candidate.t2_foot_count,
                    "formation_minutes": candidate.t1_t2_minutes,
                    "height_pips": candidate.height_pips,
                    "top_gap_pips": 20.0,
                    "neckline_price": candidate.neckline_price,
                    "break_close": candidate.break_close,
                    "previous_close": candidate.previous_close,
                },
            ]
        )
        mask = core.frame_policy_mask_v1(
            frame,
            self.pair,
            live_double_top.LIVE_TRIAL_POLICY_V1,
        )
        self.assertEqual(mask.tolist(), [True, False])

    def test_live_import_path_does_not_reference_grid_validation(self):
        root = Path(__file__).resolve().parent
        for name in ("fAnalysis_order_Main.py", "f_ダブルトップ.py"):
            source = (root / name).read_text(encoding="utf-8")
            self.assertNotIn("double_top_grid_validation", source)

    def test_live_double_top_orders_remain_isolated_as_trial(self):
        wrapper = object.__new__(analysis_main.wrap_all_analysis)
        wrapper.mode = "live"
        wrapper.exe_order_classes = []
        wrapper.trial_order_classes = []
        wrapper.notify_trial_orders = lambda *_: None
        order = SimpleNamespace(
            order_permission=True,
            order_json={"order_permission": True},
            exe_order_plan={"order_permission": True},
        )
        wrapper.orders_add_from_analysis("double_top", [order])
        self.assertEqual(wrapper.exe_order_classes, [])
        self.assertEqual(wrapper.trial_order_classes, [order])
        self.assertFalse(order.order_permission)
        self.assertFalse(order.order_json["order_permission"])
        self.assertFalse(order.exe_order_plan["order_permission"])
        self.assertEqual(order.exe_order_plan["execution_mode"], "trial")


class DoubleTopValidationContextTest(unittest.TestCase):
    @staticmethod
    def _frame(times, values):
        frame = pd.DataFrame(
            {
                "time_jp_dt": times,
                "time_jp": times.strftime("%Y/%m/%d %H:%M:%S"),
                "open": values,
                "close": values,
                "high": values + 0.005,
                "low": values - 0.005,
            }
        )
        frame["middle_price"] = values
        frame["inner_high"] = values
        frame["inner_low"] = values
        frame["body"] = 0.0
        frame["body_abs"] = 0.0
        frame["moves"] = 0.01
        frame["direction"] = 0
        frame["RSI"] = 50.0
        return frame

    def test_fast_candidate_matches_real_candle_analysis_context(self):
        m5_times = pd.date_range(
            end="2026-08-27 11:30:00",
            periods=300,
            freq="5min",
        )
        values = np.linspace(149.80, 150.10, len(m5_times))
        values[250:261] = np.linspace(150.10, 150.20, 11)
        values[260:271] = np.linspace(150.20, 150.00, 11)
        values[270:281] = np.linspace(150.00, 150.19, 11)
        values[280:299] = np.linspace(150.19, 150.01, 19)
        values[299] = 149.98
        m5 = self._frame(m5_times, values)

        h1_times = pd.date_range(
            end="2026-08-27 10:00:00",
            periods=300,
            freq="h",
        )
        h1_values = np.linspace(149.50, 150.00, len(h1_times))
        h1 = self._frame(h1_times, h1_values)
        decision = pd.Timestamp("2026-08-27 11:35:00")

        with patch.object(grid_validation, "_notify"):
            events, diagnostics = grid_validation.generate_events(
                "USD_JPY",
                decision.to_pydatetime(),
                (decision + pd.Timedelta(minutes=5)).to_pydatetime(),
                m5,
                h1,
                "unit",
            )
        self.assertEqual(diagnostics["rows_scanned"], 1)
        self.assertEqual(len(events), 1)
        self.assertEqual(
            events.iloc[0]["core_version"],
            core.CORE_VERSION_V1,
        )
        check = grid_validation.validate_production_context_equivalence(
            "USD_JPY",
            m5,
            h1,
            events,
            sample_count=1,
        )
        self.assertEqual(check["checked"], 1)
        self.assertEqual(check["mismatches"], 0)
        self.assertEqual(check["core_version"], core.CORE_VERSION_V1)

    def test_validation_baseline_comes_from_fixed_live_policy(self):
        policy = live_double_top.LIVE_TRIAL_POLICY_V1
        combo = grid_validation.live_trial_execution_combo()
        self.assertEqual(
            combo.tp_height_multiplier,
            policy.target_height_multiplier,
        )
        self.assertEqual(combo.stop_buffer_pips, policy.stop_buffer_pips)
        self.assertEqual(combo.trade_timeout_minutes, policy.trade_timeout_min)
        self.assertEqual(grid_validation.RISK_YEN, policy.risk_yen)


if __name__ == "__main__":
    unittest.main()
