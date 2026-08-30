# 最新更新日時: 2026-08-30 19:11 JST
"""AUD_USDのDoubleTop条件探索と翌年固定リプレイを起動する。"""

import datetime

from double_top_grid_validation import run_pair


PAIR = "AUD_USD"
TRAIN_START = datetime.datetime(2023, 7, 30, 0, 0, 0)
TRAIN_END = datetime.datetime(2025, 7, 30, 0, 0, 0)
OOS_START = datetime.datetime(2025, 7, 30, 0, 0, 0)
OOS_END = datetime.datetime(2026, 7, 30, 0, 0, 0)


if __name__ == "__main__":
    run_pair(
        PAIR,
        TRAIN_START,
        TRAIN_END,
        OOS_START,
        OOS_END,
    )
