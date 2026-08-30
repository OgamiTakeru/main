# 最新更新日時: 2026-08-30 17:53 JST
import datetime
from contextlib import contextmanager
from contextvars import ContextVar

import requests
import tokens as tk
import fGeneric as gene


line_send_last_message = ""
line_send_last_message_count = 0
LINE_SEND_DUPLICATE_LIMIT = 2
_notice_route = ContextVar("notice_route", default=None)
INSPECTION_NOTICE_MARKS = {
    "AUD_USD": "⭐︎",
    "USD_JPY": "●",
    "EUR_USD": "◽️",
}
INSPECTION_NOTICE_MARK_COUNT = 2
INSPECTION_COMPLETE_MARK_COUNT = 5
ALL_PAIRS_INSPECTION_COMPLETE_MARK = "●◽️⭐︎●◽️⭐︎"


def is_live_notice_message(message):
    stripped = message.strip()
    return (
        stripped.startswith("★★★オーダー発行") or
        stripped.startswith("■■■解消：") or
        stripped.startswith("■■■解消:") or
        stripped.startswith("■■■ 解消:") or
        stripped.startswith("■■■強制クローズ解消:") or
        stripped.startswith("■■■オーダー解消") or
        stripped.startswith("オーダー解消") or
        (stripped.startswith("【") and " no order】" in stripped)
    )


def is_inspection_notice_message(message):
    lower_message = message.lower()
    return (
        "inspection" in lower_message or
        "backtest" in lower_message or
        "検証" in message
    )


def notice_pair(message=""):
    if "AUD_USD" in message:
        return "AUD_USD"
    if "EUR_USD" in message:
        return "EUR_USD"
    if "USD_JPY" in message:
        return "USD_JPY"
    return getattr(gene.currentPair, "name", "USD_JPY")


def inspection_notice_mark(message):
    if (
            "全通貨" in message
            and ("完了" in message or "終了" in message)
    ):
        return ALL_PAIRS_INSPECTION_COMPLETE_MARK
    for pair, mark in INSPECTION_NOTICE_MARKS.items():
        if pair in message:
            mark_count = (
                INSPECTION_COMPLETE_MARK_COUNT
                if "完了" in message or "終了" in message
                else INSPECTION_NOTICE_MARK_COUNT
            )
            return mark * mark_count
    return ""


def webhook_url_for_pair(pair):
    if pair == "AUD_USD":
        return getattr(tk, "WEBHOOK_URL_audusd", "")
    if pair == "EUR_USD":
        return getattr(tk, "WEBHOOK_URL_eurousd", getattr(tk, "WEBHOOK_URL_friend", ""))
    return getattr(tk, "WEBHOOK_URL_usdyen", getattr(tk, "WEBHOOK_URL_main", ""))


@contextmanager
def inspection_notice_scope():
    """Force every notice in this validation scope to its Discord webhook."""
    token = _notice_route.set("inspection")
    try:
        yield
    finally:
        _notice_route.reset(token)


def send_inspection_notice(*msg):
    """Send one notice explicitly to the validation Discord webhook."""
    with inspection_notice_scope():
        return line_send(*msg)


def line_send(*msg):
    global line_send_last_message, line_send_last_message_count

    message = ""
    for item in msg:
        message = message + " " + str(item)
    raw_message = message

    now_str = f'{datetime.datetime.now():%Y/%m/%d %H:%M:%S}'
    day_time = " (" + now_str[5:10] + "_" + now_str[11:19] + ")"

    if raw_message == line_send_last_message:
        line_send_last_message_count += 1
    else:
        line_send_last_message = raw_message
        line_send_last_message_count = 1

    if line_send_last_message_count > LINE_SEND_DUPLICATE_LIMIT:
        print("     [Disc skip duplicate]", raw_message + day_time)
        return 0

    message = message + day_time
    if len(message) >= 2000:
        print("@@文字オーバー")
        message = "Discord受信許容文字数オーバー" + str(len(message)) + "@" + message[:50]

    is_inspection_notice = (
        _notice_route.get() == "inspection"
        or (
            is_inspection_notice_message(raw_message)
            and not is_live_notice_message(raw_message)
        )
    )
    notice_mark = ""
    if is_inspection_notice:
        webhook_url = tk.WEBHOOK_URL_inspection
        notice_mark = inspection_notice_mark(raw_message)
    else:
        webhook_url = webhook_url_for_pair(notice_pair(raw_message))

    if not webhook_url:
        print("     [Disc skip no webhook]", message)
        return 0

    content = "@everyone " + message
    if notice_mark:
        content = notice_mark + " " + content
    data = {
        "content": content,
        "allowed_mentions": {"parse": ["everyone"]},
    }
    try:
        response = requests.post(webhook_url, json=data, timeout=5)
        response.raise_for_status()
    except requests.RequestException as error:
        print("     [Disc error]", type(error).__name__, str(error))
        return -1
    print("     [Disc]", message)
    return 0
