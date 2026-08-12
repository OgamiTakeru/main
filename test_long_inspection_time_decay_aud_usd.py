"""Kick the AUD/USD count2 time-decay analysis using existing artifacts only.

The default window is the cached full research year. This launcher reads the
matching completed event/candidate/grid/S5 artifacts, never contacts OANDA,
and never changes the live strategy.
"""

import datetime

from count2_time_decay_analysis import main


PAIR = "AUD_USD"
START_TIME = datetime.datetime(2025, 7, 30, 0, 0, 0)
END_TIME = datetime.datetime(2026, 7, 30, 0, 0, 0)


if __name__ == "__main__":
    main(
        default_pair=PAIR,
        default_start=START_TIME,
        default_end=END_TIME,
    )
