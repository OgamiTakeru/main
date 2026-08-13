"""Kick the EUR/USD count2 time-decay analysis for the cached prior two years.

This launcher reads the matching completed event/candidate/grid/S5 artifacts,
never contacts OANDA, and never changes the live strategy.
"""

import datetime

from count2_time_decay_analysis import main


PAIR = "EUR_USD"
START_TIME = datetime.datetime(2023, 7, 30, 0, 0, 0)
END_TIME = datetime.datetime(2025, 7, 30, 0, 0, 0)


if __name__ == "__main__":
    main(
        default_pair=PAIR,
        default_start=START_TIME,
        default_end=END_TIME,
    )
