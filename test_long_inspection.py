"""Build the USD/JPY causal count2 source artifacts for the prior two years.

This is the causal resistance sweep used by the entry/TP/LC grid.  It emits
the event and candidate ledgers, including completed M5 foot-count-2 shape,
latest-two-completed-H1 shape, and M5/H1 staircase context.

Run without options to reuse compatible caches and fetch only missing or
incompatible frames from OANDA.  Add ``--existing-data`` to prohibit network
fetching and require every cache to be reusable.
"""

import datetime

from count2_resistance_sweep import main


PAIR = "USD_JPY"
START_TIME = datetime.datetime(2023, 7, 30, 0, 0, 0)
END_TIME = datetime.datetime(2025, 7, 30, 0, 0, 0)


if __name__ == "__main__":
    main(
        PAIR,
        default_start=START_TIME,
        default_end=END_TIME,
    )
