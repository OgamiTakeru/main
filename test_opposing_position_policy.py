import datetime
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import fGeneric as gene
from classOpposingPositionPolicy import OpposingPositionPolicy
from classPositionControl import position_control


NOW = datetime.datetime(2026, 7, 27, 3, 0, tzinfo=datetime.timezone.utc)


def trade(units, pl, minutes=90, trade_id="1"):
    return {
        "id": trade_id,
        "instrument": "AUD_USD",
        "currentUnits": str(units),
        "unrealizedPL": str(pl),
        "past_time_sec": minutes * 60,
    }


def order(direction=1, score=0.85, priority=5):
    return {
        "direction": direction,
        "line_entry_type": "breakout",
        "line_break_score": score,
        "priority": priority,
        "memo": "reason=condition one / condition two",
    }


class OpposingPositionPolicyTest(unittest.TestCase):
    def setUp(self):
        self.policy = OpposingPositionPolicy("AUD_USD", now=NOW)

    def test_allows_without_opposite_position(self):
        result = self.policy.evaluate(order(1), [trade(610, -20)])
        self.assertEqual(result["action"], "allow")

    def test_profitable_opposite_is_closed_and_new_order_blocked(self):
        result = self.policy.evaluate(order(1), [trade(-610, 12)])
        self.assertEqual(result["action"], "take_profit_and_block")
        self.assertEqual(result["close_trades"][0]["id"], "1")

    def test_young_losing_opposite_blocks_new_order(self):
        result = self.policy.evaluate(order(1), [trade(-610, -20, minutes=30)])
        self.assertEqual(result["action"], "block")
        self.assertEqual(result["reason"], "opposite_loss_is_not_stale")

    def test_stale_loss_with_weak_signal_blocks_new_order(self):
        result = self.policy.evaluate(
            order(1, score=0.7, priority=5),
            [trade(-610, -20)],
        )
        self.assertEqual(result["action"], "block")
        self.assertEqual(result["reason"], "new_signal_is_not_strong")

    def test_stale_loss_with_strong_signal_stops_and_reverses(self):
        result = self.policy.evaluate(order(1), [trade(-610, -20)])
        self.assertEqual(result["action"], "stop_and_reverse")

    def test_priority_and_multiple_conditions_are_strength_fallback(self):
        plan = order(1, score=None, priority=10)
        result = self.policy.evaluate(plan, [trade(-610, -20)])
        self.assertEqual(result["action"], "stop_and_reverse")

    def test_small_stale_loss_does_not_trigger_reverse(self):
        result = self.policy.evaluate(order(1), [trade(-610, -5)])
        self.assertEqual(result["action"], "block")
        self.assertEqual(
            result["reason"],
            "opposite_loss_not_large_enough_to_reverse",
        )


class OpposingPositionControllerTest(unittest.TestCase):
    @staticmethod
    def controller(open_trades, close_error=0):
        controller = position_control.__new__(position_control)
        controller.is_live = True
        controller.pair = "AUD_USD"
        controller.oa2 = Mock()
        controller.oa2.OpenTrades_exe.return_value = {
            "error": 0,
            "json": {"trades": open_trades},
        }
        controller.oa2.TradeClose_exe.return_value = {
            "error": close_error,
        }
        return controller

    @staticmethod
    def order_class(plan=None):
        return SimpleNamespace(exe_order_plan=plan or order())

    @patch("classPositionControl.notice.line_send")
    def test_profitable_opposite_closes_and_blocks_new_order(self, line_send):
        controller = self.controller([trade(-610, 12)])
        candidate = self.order_class()
        allowed = controller.apply_opposing_position_policy([candidate])
        self.assertEqual(allowed, [])
        controller.oa2.TradeClose_exe.assert_called_once_with("1", None)
        self.assertTrue(line_send.call_args.args[0].startswith("[阻止された]"))

    @patch("classPositionControl.notice.line_send")
    def test_stale_loss_closes_then_allows_strong_new_order(self, line_send):
        controller = self.controller([trade(-610, -20)])
        candidate = self.order_class()
        allowed = controller.apply_opposing_position_policy([candidate])
        self.assertEqual(allowed, [candidate])
        controller.oa2.TradeClose_exe.assert_called_once_with("1", None)
        line_send.assert_not_called()

    @patch("classPositionControl.notice.line_send")
    def test_close_failure_blocks_new_order(self, line_send):
        controller = self.controller([trade(-610, -20)], close_error=1)
        candidate = self.order_class()
        allowed = controller.apply_opposing_position_policy([candidate])
        self.assertEqual(allowed, [])
        self.assertIn("opposite_position_close_failed", line_send.call_args.args[0])

    @patch("classPositionControl.notice.line_send")
    def test_non_live_mode_does_not_read_or_change_positions(self, line_send):
        controller = self.controller([trade(-610, 12)])
        controller.is_live = False
        candidate = self.order_class()
        allowed = controller.apply_opposing_position_policy([candidate])
        self.assertEqual(allowed, [candidate])
        controller.oa2.OpenTrades_exe.assert_not_called()
        controller.oa2.TradeClose_exe.assert_not_called()
        line_send.assert_not_called()


class PredictPendingConflictTest(unittest.TestCase):
    @staticmethod
    def controller(is_live=True):
        controller = position_control.__new__(position_control)
        controller.is_live = is_live
        controller.pair = "USD_JPY"
        controller.p = gene.currency_pair("USD_JPY")
        controller.position_classes = []
        return controller

    @staticmethod
    def candidate(
        direction=-1,
        target_price=150.0,
        signal_id="-1:2026-08-02 12:00:00",
    ):
        return SimpleNamespace(
            exe_order_plan={
                "name": "predict reversal",
                "line_order_mode": "predict_reversal",
                "predict_signal_id": signal_id,
                "direction": direction,
                "target_price": target_price,
            }
        )

    @staticmethod
    def pending_breakout(
        direction=1,
        target_price=150.015,
        state="PENDING",
        order_id="42",
    ):
        api = Mock()
        api.OrderDetails_exe.return_value = {
            "error": 0,
            "data": {"order": {"state": state}},
        }
        api.OrderCancel_exe.return_value = {"error": 0, "data": {}}
        slot = SimpleNamespace(
            name="pending-" + str(order_id),
            life=True,
            o_state="PENDING",
            o_id=order_id,
            oa=api,
            notify_order_cancelled=Mock(),
            plan_json={
                "source": "line",
                "line_entry_type": "breakout",
                "direction": direction,
                "target_price": target_price,
            },
        )
        slot.life_set = Mock(
            side_effect=lambda value: setattr(slot, "life", value)
        )
        return slot

    def test_cancels_near_opposite_pending_breakout_then_allows_predict(self):
        controller = self.controller()
        slot = self.pending_breakout()
        controller.position_classes = [slot]
        candidate = self.candidate()

        allowed = controller.resolve_predict_reversal_pending_conflicts(
            [candidate]
        )

        self.assertEqual(allowed, [candidate])
        slot.oa.OrderDetails_exe.assert_called_once_with("42")
        slot.oa.OrderCancel_exe.assert_called_once_with("42")
        slot.notify_order_cancelled.assert_called_once_with(
            "他オーダー輻輳",
            "42",
            "競合Breakout",
        )
        self.assertFalse(slot.life)
        self.assertEqual(slot.o_state, "CANCELLED")
        self.assertEqual(
            candidate.exe_order_plan["pending_conflict_action"],
            "cancel_opposite_pending_breakout",
        )
        self.assertEqual(
            candidate.exe_order_plan["pending_conflict_cancelled_order_id"],
            "42",
        )
        self.assertEqual(
            candidate.exe_order_plan["pending_conflict_cancelled_order_ids"],
            ["42"],
        )

    def test_blocks_predict_when_pending_cancel_fails(self):
        controller = self.controller()
        slot = self.pending_breakout()
        slot.oa.OrderCancel_exe.return_value = {"error": 1}
        controller.position_classes = [slot]
        candidate = self.candidate()

        allowed = controller.resolve_predict_reversal_pending_conflicts(
            [candidate]
        )

        self.assertEqual(allowed, [])
        slot.notify_order_cancelled.assert_not_called()
        self.assertTrue(slot.life)
        self.assertEqual(
            candidate.exe_order_plan["pending_conflict_reason"],
            "pending_breakout_cancel_failed",
        )
        self.assertEqual(
            candidate.exe_order_plan["pending_conflict_action"],
            "block_predict_reversal",
        )

    def test_blocks_predict_when_breakout_already_filled(self):
        controller = self.controller()
        slot = self.pending_breakout(state="FILLED")
        controller.position_classes = [slot]
        candidate = self.candidate()

        allowed = controller.resolve_predict_reversal_pending_conflicts(
            [candidate]
        )

        self.assertEqual(allowed, [])
        slot.oa.OrderCancel_exe.assert_not_called()
        self.assertTrue(slot.life)
        self.assertEqual(
            candidate.exe_order_plan["pending_conflict_reason"],
            "pending_breakout_no_longer_cancellable:FILLED",
        )

    def test_far_or_same_direction_breakout_is_untouched(self):
        for slot in (
            self.pending_breakout(target_price=150.05),
            self.pending_breakout(direction=-1),
        ):
            with self.subTest(plan=slot.plan_json):
                controller = self.controller()
                controller.position_classes = [slot]
                candidate = self.candidate()
                allowed = controller.resolve_predict_reversal_pending_conflicts(
                    [candidate]
                )
                self.assertEqual(allowed, [candidate])
                slot.oa.OrderDetails_exe.assert_not_called()
                slot.oa.OrderCancel_exe.assert_not_called()

    def test_non_live_mode_does_not_query_or_cancel_pending_breakout(self):
        controller = self.controller(is_live=False)
        slot = self.pending_breakout()
        controller.position_classes = [slot]
        candidate = self.candidate()

        allowed = controller.resolve_predict_reversal_pending_conflicts(
            [candidate]
        )

        self.assertEqual(allowed, [candidate])
        slot.oa.OrderDetails_exe.assert_not_called()
        slot.oa.OrderCancel_exe.assert_not_called()

    def test_all_conflict_states_are_checked_before_first_cancel(self):
        controller = self.controller()
        first = self.pending_breakout(order_id="41")
        second = self.pending_breakout(order_id="42")
        second.oa.OrderDetails_exe.return_value = {"error": 1}
        controller.position_classes = [first, second]
        candidate = self.candidate()

        allowed = controller.resolve_predict_reversal_pending_conflicts(
            [candidate]
        )

        self.assertEqual(allowed, [])
        first.oa.OrderDetails_exe.assert_called_once_with("41")
        second.oa.OrderDetails_exe.assert_called_once_with("42")
        first.oa.OrderCancel_exe.assert_not_called()
        second.oa.OrderCancel_exe.assert_not_called()
        self.assertTrue(first.life)
        self.assertEqual(
            candidate.exe_order_plan["pending_conflict_failed_order_id"],
            "42",
        )

    def test_partial_cancel_failure_is_recorded_and_predict_is_blocked(self):
        controller = self.controller()
        first = self.pending_breakout(order_id="41")
        second = self.pending_breakout(order_id="42")
        second.oa.OrderCancel_exe.return_value = {"error": 1}
        controller.position_classes = [first, second]
        candidate = self.candidate()

        allowed = controller.resolve_predict_reversal_pending_conflicts(
            [candidate]
        )

        self.assertEqual(allowed, [])
        self.assertFalse(first.life)
        self.assertTrue(second.life)
        self.assertEqual(
            candidate.exe_order_plan["pending_conflict_cancelled_order_ids"],
            ["41"],
        )
        self.assertEqual(
            candidate.exe_order_plan["pending_conflict_failed_order_id"],
            "42",
        )

    def test_pending_conflict_blocks_before_opposing_trade_policy_runs(self):
        controller = self.controller()
        candidate = self.candidate()
        controller.filter_breakouts_near_pending_predict_reversals = Mock(
            return_value=[candidate]
        )
        controller.filter_similar_order_classes = Mock(
            return_value=[candidate]
        )
        controller.resolve_predict_reversal_pending_conflicts = Mock(
            return_value=[]
        )
        controller.apply_opposing_position_policy = Mock()

        result = controller.order_class_add([candidate])

        self.assertEqual(result, 0)
        controller.apply_opposing_position_policy.assert_not_called()

    def test_pending_predict_blocks_near_opposite_breakout(self):
        controller = self.controller()
        predict_slot = self.pending_breakout(
            direction=-1,
            target_price=150.0,
        )
        predict_slot.plan_json["line_entry_type"] = "reversal"
        predict_slot.plan_json["line_order_mode"] = "predict_reversal"
        controller.position_classes = [predict_slot]
        breakout = SimpleNamespace(
            exe_order_plan={
                "name": "breakout",
                "source": "line",
                "line_entry_type": "breakout",
                "direction": 1,
                "target_price": 150.015,
            }
        )

        allowed = controller.filter_breakouts_near_pending_predict_reversals(
            [breakout]
        )

        self.assertEqual(allowed, [])
        predict_slot.oa.OrderDetails_exe.assert_called_once_with("42")
        predict_slot.oa.OrderCancel_exe.assert_not_called()
        self.assertEqual(
            breakout.exe_order_plan["predict_pending_guard_reason"],
            "pending_predict_reversal_has_priority",
        )

    def test_cancelled_predict_does_not_block_new_breakout(self):
        controller = self.controller()
        predict_slot = self.pending_breakout(
            direction=-1,
            target_price=150.0,
            state="CANCELLED",
        )
        predict_slot.plan_json["line_entry_type"] = "reversal"
        predict_slot.plan_json["line_order_mode"] = "predict_reversal"
        controller.position_classes = [predict_slot]
        breakout = SimpleNamespace(
            exe_order_plan={
                "source": "line",
                "line_entry_type": "breakout",
                "direction": 1,
                "target_price": 150.015,
            }
        )

        allowed = controller.filter_breakouts_near_pending_predict_reversals(
            [breakout]
        )

        self.assertEqual(allowed, [breakout])
        self.assertFalse(predict_slot.life)
        predict_slot.notify_order_cancelled.assert_called_once_with(
            "OANDA側取消確認",
            "42",
            None,
        )

    def test_filled_predict_defers_local_transition_to_regular_update(self):
        controller = self.controller()
        predict_slot = self.pending_breakout(
            direction=-1,
            target_price=150.0,
            state="FILLED",
        )
        predict_slot.plan_json["line_entry_type"] = "reversal"
        predict_slot.plan_json["line_order_mode"] = "predict_reversal"
        controller.position_classes = [predict_slot]
        breakout = SimpleNamespace(
            exe_order_plan={
                "source": "line",
                "line_entry_type": "breakout",
                "direction": 1,
                "target_price": 150.015,
            }
        )

        allowed = controller.filter_breakouts_near_pending_predict_reversals(
            [breakout]
        )

        self.assertEqual(allowed, [breakout])
        self.assertEqual(predict_slot.o_state, "PENDING")
        self.assertTrue(predict_slot.life)

    def test_duplicate_predict_still_cleans_opposite_pending_breakout(self):
        controller = self.controller()
        existing_predict = self.pending_breakout(
            direction=-1,
            target_price=150.0,
            order_id="41",
        )
        existing_predict.plan_json["line_entry_type"] = "reversal"
        existing_predict.plan_json["line_order_mode"] = "predict_reversal"
        existing_predict.plan_json["predict_signal_id"] = (
            "-1:2026-08-02 12:00:00"
        )
        opposite_breakout = self.pending_breakout(
            direction=1,
            target_price=150.015,
            order_id="42",
        )
        controller.position_classes = [existing_predict, opposite_breakout]
        controller.apply_opposing_position_policy = Mock()
        candidate = self.candidate()
        candidate.current_price = 150.0

        result = controller.order_class_add([candidate])

        self.assertEqual(result, 0)
        self.assertFalse(opposite_breakout.life)
        opposite_breakout.oa.OrderCancel_exe.assert_called_once_with("42")
        self.assertTrue(existing_predict.life)
        controller.apply_opposing_position_policy.assert_not_called()

    def test_new_count2_replaces_previous_pending_predict_even_when_far(self):
        controller = self.controller()
        previous = self.pending_breakout(
            direction=-1,
            target_price=150.0,
            order_id="41",
        )
        previous.plan_json["line_entry_type"] = "reversal"
        previous.plan_json["line_order_mode"] = "predict_reversal"
        previous.plan_json["predict_signal_id"] = (
            "1:2026-08-02 11:30:00"
        )
        controller.position_classes = [previous]
        candidate = self.candidate(
            direction=1,
            target_price=149.8,
            signal_id="-1:2026-08-02 12:00:00",
        )

        allowed = controller.resolve_predict_reversal_pending_conflicts(
            [candidate]
        )

        self.assertEqual(allowed, [candidate])
        previous.oa.OrderDetails_exe.assert_called_once_with("41")
        previous.oa.OrderCancel_exe.assert_called_once_with("41")
        previous.notify_order_cancelled.assert_called_once_with(
            "他オーダー輻輳",
            "41",
            "旧PredictReversal",
        )
        self.assertFalse(previous.life)
        self.assertEqual(
            candidate.exe_order_plan["pending_conflict_action"],
            "replace_previous_count2_predict",
        )
        self.assertEqual(
            candidate.exe_order_plan[
                "pending_conflict_replaced_predict_order_ids"
            ],
            ["41"],
        )

    def test_same_count2_keeps_existing_predict_without_reissuing(self):
        controller = self.controller()
        existing = self.pending_breakout(
            direction=-1,
            target_price=150.0,
            order_id="41",
        )
        existing.plan_json["line_entry_type"] = "reversal"
        existing.plan_json["line_order_mode"] = "predict_reversal"
        existing.plan_json["predict_signal_id"] = (
            "-1:2026-08-02 12:00:00"
        )
        controller.position_classes = [existing]
        candidate = self.candidate(target_price=150.05)

        allowed = controller.resolve_predict_reversal_pending_conflicts(
            [candidate]
        )

        self.assertEqual(allowed, [])
        existing.oa.OrderDetails_exe.assert_called_once_with("41")
        existing.oa.OrderCancel_exe.assert_not_called()
        self.assertTrue(existing.life)
        self.assertEqual(
            candidate.exe_order_plan["pending_conflict_action"],
            "keep_existing_same_count2_predict",
        )

    def test_same_count2_keeps_one_pending_and_cancels_duplicates(self):
        controller = self.controller()
        first = self.pending_breakout(
            direction=-1,
            target_price=150.0,
            order_id="41",
        )
        second = self.pending_breakout(
            direction=-1,
            target_price=150.05,
            order_id="42",
        )
        for item in (first, second):
            item.plan_json["line_entry_type"] = "reversal"
            item.plan_json["line_order_mode"] = "predict_reversal"
            item.plan_json["predict_signal_id"] = (
                "-1:2026-08-02 12:00:00"
            )
        controller.position_classes = [first, second]
        candidate = self.candidate(target_price=150.1)

        allowed = controller.resolve_predict_reversal_pending_conflicts(
            [candidate]
        )

        self.assertEqual(allowed, [])
        self.assertTrue(first.life)
        self.assertFalse(second.life)
        first.oa.OrderCancel_exe.assert_not_called()
        second.oa.OrderCancel_exe.assert_called_once_with("42")
        second.notify_order_cancelled.assert_called_once_with(
            "他オーダー輻輳",
            "42",
            "同一count2重複",
        )
        self.assertEqual(
            candidate.exe_order_plan[
                "pending_conflict_cancelled_same_signal_order_ids"
            ],
            ["42"],
        )

    def test_same_count2_fill_cancels_every_other_pending_duplicate(self):
        controller = self.controller()
        filled = self.pending_breakout(
            direction=-1,
            target_price=150.0,
            state="FILLED",
            order_id="41",
        )
        pending = self.pending_breakout(
            direction=-1,
            target_price=150.05,
            order_id="42",
        )
        for item in (filled, pending):
            item.plan_json["line_entry_type"] = "reversal"
            item.plan_json["line_order_mode"] = "predict_reversal"
            item.plan_json["predict_signal_id"] = (
                "-1:2026-08-02 12:00:00"
            )
        controller.position_classes = [filled, pending]
        candidate = self.candidate(target_price=150.1)

        allowed = controller.resolve_predict_reversal_pending_conflicts(
            [candidate]
        )

        self.assertEqual(allowed, [])
        self.assertEqual(filled.o_state, "PENDING")
        self.assertTrue(filled.life)
        self.assertFalse(pending.life)
        pending.oa.OrderCancel_exe.assert_called_once_with("42")

    def test_filled_previous_predict_blocks_new_count2_without_local_rewrite(self):
        controller = self.controller()
        previous = self.pending_breakout(
            direction=-1,
            target_price=150.0,
            state="FILLED",
            order_id="41",
        )
        previous.plan_json["line_entry_type"] = "reversal"
        previous.plan_json["line_order_mode"] = "predict_reversal"
        previous.plan_json["predict_signal_id"] = (
            "1:2026-08-02 11:30:00"
        )
        controller.position_classes = [previous]
        candidate = self.candidate(
            direction=1,
            target_price=149.8,
            signal_id="-1:2026-08-02 12:00:00",
        )

        allowed = controller.resolve_predict_reversal_pending_conflicts(
            [candidate]
        )

        self.assertEqual(allowed, [])
        previous.oa.OrderCancel_exe.assert_not_called()
        self.assertEqual(previous.o_state, "PENDING")
        self.assertEqual(
            candidate.exe_order_plan["pending_conflict_reason"],
            "previous_predict_no_longer_cancellable:FILLED",
        )

    def test_count2_control_expires_previous_predict_without_new_candidate(self):
        controller = self.controller()
        previous = self.pending_breakout(
            direction=-1,
            target_price=150.0,
            order_id="41",
        )
        previous.plan_json["line_entry_type"] = "reversal"
        previous.plan_json["line_order_mode"] = "predict_reversal"
        previous.plan_json["predict_signal_id"] = (
            "1:2026-08-02 11:30:00"
        )
        controller.position_classes = [previous]
        control = SimpleNamespace(
            exe_order_plan={
                "name": "PredictReversalCount2Control",
                "line_order_mode": "predict_reversal_count2_control",
                "predict_signal_id": "-1:2026-08-02 12:00:00",
                "priority": 0,
            }
        )

        result = controller.order_class_add([control])

        self.assertEqual(result, 0)
        previous.oa.OrderDetails_exe.assert_called_once_with("41")
        previous.oa.OrderCancel_exe.assert_called_once_with("41")
        self.assertFalse(previous.life)
        self.assertEqual(
            control.exe_order_plan["pending_conflict_action"],
            "count2_expiry_processed",
        )


if __name__ == "__main__":
    unittest.main()
