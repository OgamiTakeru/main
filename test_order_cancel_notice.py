import unittest
from unittest.mock import Mock

from classPosition import order_information


class OrderCancelNoticeTest(unittest.TestCase):
    @staticmethod
    def slot(state="PENDING"):
        item = order_information.__new__(order_information)
        item.life = True
        item.name = "PredictReversal_upper_1_12:00"
        item.pair = "EUR_USD"
        item.o_id = "123"
        item.o_state = state
        item.positions_information = {
            "open_positions": [],
            "pending_positions": [],
        }
        item.oa = Mock()
        item.oa.OrderDetails_exe.return_value = {
            "error": 0,
            "data": {"order": {"state": state}},
        }
        item.oa.OrderCancel_exe.return_value = {"error": 0}
        item.send_line = Mock()
        return item

    def test_pending_cancel_sends_pair_name_id_and_reason(self):
        item = self.slot()

        item.close_order(
            reason="他オーダー輻輳",
            detail="旧PredictReversal",
        )

        self.assertFalse(item.life)
        self.assertEqual(item.o_state, "CANCELLED")
        item.oa.OrderCancel_exe.assert_called_once_with("123")
        item.send_line.assert_called_once_with(
            "オーダー解消(他オーダー輻輳)",
            "PredictReversal_upper_1_12:00",
            "通貨:EUR_USD",
            "OrderID:123",
            "詳細:旧PredictReversal",
        )

    def test_watching_cancel_also_sends_notice(self):
        item = self.slot(state="Watching")
        item.o_id = -1

        item.close_order(reason="時間切れ/ウォッチング")

        self.assertFalse(item.life)
        self.assertEqual(item.o_state, "CANCELLED")
        item.oa.OrderDetails_exe.assert_not_called()
        item.send_line.assert_called_once_with(
            "オーダー解消(時間切れ/ウォッチング)",
            "PredictReversal_upper_1_12:00",
            "通貨:EUR_USD",
            "OrderID:-1",
            "詳細:未発行Watching",
        )

    def test_already_cancelled_server_order_is_reported(self):
        item = self.slot(state="CANCELLED")

        item.close_order()

        item.oa.OrderCancel_exe.assert_not_called()
        item.send_line.assert_called_once_with(
            "オーダー解消(OANDA側取消確認)",
            "PredictReversal_upper_1_12:00",
            "通貨:EUR_USD",
            "OrderID:123",
        )


if __name__ == "__main__":
    unittest.main()
