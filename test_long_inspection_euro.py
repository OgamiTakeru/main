"""Build the EUR/USD causal count2 source artifacts for the prior two years.

The launcher reuses compatible M5/H1/S5 caches and emits event/candidate
ledgers with completed M5/H1 staircase context.  It does not change the live
strategy.  Add ``--existing-data`` to prohibit OANDA fallback fetching.
"""

import datetime

from count2_resistance_sweep import main


PAIR = "EUR_USD"
START_TIME = datetime.datetime(2023, 7, 30, 0, 0, 0)
END_TIME = datetime.datetime(2025, 7, 30, 0, 0, 0)


if __name__ == "__main__":
    main(
        PAIR,
        default_start=START_TIME,
        default_end=END_TIME,
    )
