"""EUR_USD版の勝ち地点探索。

検証本体は test_win_point_usd_aud.py と共通。期間、固定/可変TPなど、
利用できるコマンドライン引数もAUD_USD版と同じ。
"""

import test_win_point_usd_aud as win_point

win_point.PAIR = "EUR_USD"

if __name__ == "__main__":
    win_point.run(win_point.parse_args(), pair_name="EUR_USD")
