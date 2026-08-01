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


if __name__ == "__main__":
    unittest.main()
