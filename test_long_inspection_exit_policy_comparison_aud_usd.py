"""Compare fixed AUD/USD Top15 exit-management variants on following-year OOS."""

import datetime

from count2_exit_policy_comparison import main


if __name__ == "__main__":
    main(
        default_pair="AUD_USD",
        default_train_start=datetime.datetime(2023, 7, 30),
        default_train_end=datetime.datetime(2025, 7, 30),
        default_oos_start=datetime.datetime(2025, 7, 30),
        default_oos_end=datetime.datetime(2026, 7, 30),
    )
