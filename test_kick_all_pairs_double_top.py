# 最新更新日時: 2026-08-30 17:44 JST
"""3通貨ペアのDoubleTop条件探索と翌年固定リプレイを一本で起動する。"""

import datetime

from double_top_grid_validation import run_all_pairs


PAIRS = ("USD_JPY", "EUR_USD", "AUD_USD")
TRAIN_START = datetime.datetime(2023, 7, 30, 0, 0, 0)
TRAIN_END = datetime.datetime(2025, 7, 30, 0, 0, 0)
OOS_START = datetime.datetime(2025, 7, 30, 0, 0, 0)
OOS_END = datetime.datetime(2026, 7, 30, 0, 0, 0)


if __name__ == "__main__":
    run_all_pairs(
        PAIRS,
        TRAIN_START,
        TRAIN_END,
        OOS_START,
        OOS_END,
    )
