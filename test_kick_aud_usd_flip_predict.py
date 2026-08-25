# 最新更新日時: 2026-08-25 15:35 JST
# 正解バージョン
"""Analyze AUD/USD flip_predict, then run the frozen following-year replay."""

import datetime

from count2_flip_pipeline import main


if __name__ == "__main__":
    main(
        default_pair="AUD_USD",
        default_train_start=datetime.datetime(2023, 7, 30),
        default_train_end=datetime.datetime(2025, 7, 30),
        default_oos_start=datetime.datetime(2025, 7, 30),
        default_oos_end=datetime.datetime(2026, 7, 30),
    )
