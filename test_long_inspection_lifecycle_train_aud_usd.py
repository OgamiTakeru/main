"""Select AUD/USD lifecycle policies on the fixed prior-two-year window."""

import datetime

from count2_lifecycle_policy_search import main


PAIR = "AUD_USD"
TRAIN_START = datetime.datetime(2023, 7, 30)
TRAIN_END = datetime.datetime(2025, 7, 30)
FOLLOWING_START = datetime.datetime(2025, 7, 30)
FOLLOWING_END = datetime.datetime(2026, 7, 30)


if __name__ == "__main__":
    main(
        default_pair=PAIR,
        default_train_start=TRAIN_START,
        default_train_end=TRAIN_END,
        default_following_start=FOLLOWING_START,
        default_following_end=FOLLOWING_END,
    )
