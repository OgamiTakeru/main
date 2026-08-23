# 正解バージョン
"""Analyze USD/JPY flip_predict, then run the frozen following-year replay."""

import datetime

from count2_flip_pipeline import main


if __name__ == "__main__":
    main(
        default_pair="USD_JPY",
        default_train_start=datetime.datetime(2023, 7, 30),
        default_train_end=datetime.datetime(2025, 7, 30),
        default_oos_start=datetime.datetime(2025, 7, 30),
        default_oos_end=datetime.datetime(2026, 7, 30),
    )
