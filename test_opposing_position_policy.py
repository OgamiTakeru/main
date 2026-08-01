import datetime
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

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


if __name__ == "__main__":
    unittest.main()
