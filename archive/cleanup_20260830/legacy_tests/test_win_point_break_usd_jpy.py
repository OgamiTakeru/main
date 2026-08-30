"""USD_JPY peaks[0].count==2 失敗ブレイク検証。設定は共通本体に固定。"""

import test_win_point_usd_aud as win_point

win_point.PAIR = "USD_JPY"
win_point.TP_MULTIPLIER = 1.5

if __name__ == "__main__":
    win_point.run(
        win_point.parse_args(),
        pair_name="USD_JPY",
        entry_mode="peak0-failure-break",
    )
