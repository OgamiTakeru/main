import unittest
from unittest.mock import patch

import send_notice


class InspectionNoticeMarkTest(unittest.TestCase):
    def setUp(self):
        send_notice.line_send_last_message = ""
        send_notice.line_send_last_message_count = 0

    @patch("send_notice.requests.post")
    def test_pair_mark_is_first_in_each_inspection_notice(self, post):
        cases = (
            ("AUD_USD", "検証 終了", "⭐︎"),
            ("USD_JPY", "win-point inspection 終了", "●"),
            ("EUR_USD", "検証データ取得", "◽️"),
        )

        with patch.object(
            send_notice.tk,
            "WEBHOOK_URL_inspection",
            "inspection-webhook",
            create=True,
        ):
            for pair, message, expected_mark in cases:
                with self.subTest(pair=pair):
                    send_notice.line_send(pair, message)
                    payload = post.call_args.kwargs["json"]
                    self.assertTrue(
                        payload["content"].startswith(
                            expected_mark + " @everyone "
                        )
                    )

    @patch("send_notice.requests.post")
    def test_non_inspection_notice_does_not_get_pair_mark(self, post):
        with patch(
            "send_notice.webhook_url_for_pair",
            return_value="pair-webhook",
        ):
            send_notice.line_send("AUD_USD", "regular notice")

        payload = post.call_args.kwargs["json"]
        self.assertTrue(payload["content"].startswith("@everyone "))

    @patch("send_notice.requests.post")
    def test_inspection_scope_forces_order_shaped_notice_to_validation(self, post):
        with (
            patch.object(
                send_notice.tk,
                "WEBHOOK_URL_inspection",
                "inspection-webhook",
                create=True,
            ),
            patch(
                "send_notice.webhook_url_for_pair",
                return_value="pair-webhook",
            ),
        ):
            with send_notice.inspection_notice_scope():
                send_notice.line_send("★★★オーダー発行", "USD_JPY")

        self.assertEqual(post.call_args.args[0], "inspection-webhook")

    @patch("send_notice.requests.post")
    def test_inspection_scope_is_reset_after_validation(self, post):
        with (
            patch.object(
                send_notice.tk,
                "WEBHOOK_URL_inspection",
                "inspection-webhook",
                create=True,
            ),
            patch(
                "send_notice.webhook_url_for_pair",
                return_value="pair-webhook",
            ),
        ):
            with send_notice.inspection_notice_scope():
                send_notice.line_send("USD_JPY", "validation order")
            send_notice.line_send("USD_JPY", "live order")

        self.assertEqual(post.call_args_list[0].args[0], "inspection-webhook")
        self.assertEqual(post.call_args_list[1].args[0], "pair-webhook")

    @patch("send_notice.requests.post")
    def test_order_cancel_notice_routes_to_each_pair_webhook(self, post):
        webhook_by_pair = {
            "USD_JPY": "usd-webhook",
            "EUR_USD": "eur-webhook",
            "AUD_USD": "aud-webhook",
        }
        with (
            patch.object(send_notice.tk, "WEBHOOK_URL_usdyen", "usd-webhook"),
            patch.object(send_notice.tk, "WEBHOOK_URL_eurousd", "eur-webhook"),
            patch.object(send_notice.tk, "WEBHOOK_URL_audusd", "aud-webhook"),
        ):
            for pair in webhook_by_pair:
                send_notice.line_send(
                    "■■■オーダー解消(他オーダー輻輳)",
                    "order-name",
                    pair,
                    "OrderID:1",
                )

        self.assertEqual(
            [call.args[0] for call in post.call_args_list],
            list(webhook_by_pair.values()),
        )


if __name__ == "__main__":
    unittest.main()
