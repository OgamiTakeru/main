"""Build causal AUD/USD source ledgers for the following one-year OOS replay."""

import datetime

from count2_resistance_sweep import main


PAIR = "AUD_USD"
START_TIME = datetime.datetime(2025, 7, 30)
END_TIME = datetime.datetime(2026, 7, 30)


if __name__ == "__main__":
    main(PAIR, default_start=START_TIME, default_end=END_TIME)
