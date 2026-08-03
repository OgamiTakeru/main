"""EUR_USD next-count2 resistance prediction validation entry point."""

import datetime

from count2_resistance_sweep import main


PAIR = "EUR_USD"

# ===== 取得・検証期間（START以上、END未満） =====
START_TIME = datetime.datetime(2023, 7, 30, 0, 0, 0)
END_TIME = datetime.datetime(2025, 7, 30, 0, 0, 0)


if __name__ == "__main__":
    main(
        PAIR,
        default_start=START_TIME,
        default_end=END_TIME,
    )
