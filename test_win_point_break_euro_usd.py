"""EUR_USD peaks[0].count==2 失敗ブレイク検証。設定は共通本体に固定。"""

import test_win_point_usd_aud as win_point

win_point.PAIR = "EUR_USD"
win_point.TP_MULTIPLIER = 3.0

if __name__ == "__main__":
    win_point.run(
        win_point.parse_args(),
        pair_name="EUR_USD",
        entry_mode="peak0-failure-break",
    )
