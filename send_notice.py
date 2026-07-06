import datetime

import requests
import tokens as tk
import fGeneric as gene


line_send_last_message = ""
line_send_last_message_count = 0
LINE_SEND_DUPLICATE_LIMIT = 2


def is_live_notice_message(message):
    stripped = message.strip()
    return (
        stripped.startswith("★★★オーダー発行") or
        stripped.startswith("■■■解消：") or
        stripped.startswith("■■■解消:") or
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
    if "EUR_USD" in message:
        return "EUR_USD"
    if "USD_JPY" in message:
        return "USD_JPY"
    return getattr(gene.currentPair, "name", "USD_JPY")


def webhook_url_for_pair(pair):
    if pair == "EUR_USD":
        return getattr(tk, "WEBHOOK_URL_eurousd", getattr(tk, "WEBHOOK_URL_friend", ""))
    return getattr(tk, "WEBHOOK_URL_usdyen", getattr(tk, "WEBHOOK_URL_main", ""))


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

    if is_inspection_notice_message(raw_message) and not is_live_notice_message(raw_message):
        webhook_url = tk.WEBHOOK_URL_inspection
    else:
        webhook_url = webhook_url_for_pair(notice_pair(raw_message))

    if not webhook_url:
        print("     [Disc skip no webhook]", message)
        return 0

    data = {
        "content": "@everyone " + message,
        "allowed_mentions": {"parse": ["everyone"]},
    }
    requests.post(webhook_url, json=data)
    print("     [Disc]", message)
