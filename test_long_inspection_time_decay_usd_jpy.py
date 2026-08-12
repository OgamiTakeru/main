"""Kick the USD/JPY count2 time-decay analysis using existing artifacts only.

The default window is the latest completed research year.  Override it with
``--start`` and ``--end`` to analyze the preceding two-year window.  This
launcher never contacts OANDA and never changes the live strategy.
"""

import datetime

from count2_time_decay_analysis import main


PAIR = "USD_JPY"
START_TIME = datetime.datetime(2025, 7, 30, 0, 0, 0)
END_TIME = datetime.datetime(2026, 7, 30, 0, 0, 0)


if __name__ == "__main__":
    main(
        default_pair=PAIR,
        default_start=START_TIME,
        default_end=END_TIME,
    )
