"""Replay fixed AUD/USD prior-two-year yen/pips Top15 on the following year."""

import datetime

from count2_prior2y_oos_replay import main


if __name__ == "__main__":
    main(
        default_pair="AUD_USD",
        default_train_start=datetime.datetime(2023, 7, 30),
        default_train_end=datetime.datetime(2025, 7, 30),
        default_oos_start=datetime.datetime(2025, 7, 30),
        default_oos_end=datetime.datetime(2026, 7, 30),
    )
