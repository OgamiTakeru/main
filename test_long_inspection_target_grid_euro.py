"""Run the EUR/USD foot-count-2 entry/TP/LC grid for the cached prior two years.

Prerequisite: the matching causal resistance-sweep candidate/event CSVs and
S5 cache must already exist. It exhausts M5/H1 shape conditions and their
same-feature interactions. This launcher does not contact OANDA, change the
live strategy, rank conditions, or select a Top3/Top15.
"""

import datetime

from count2_target_grid_search import main


PAIR = "EUR_USD"
START_TIME = datetime.datetime(2023, 7, 30, 0, 0, 0)
END_TIME = datetime.datetime(2025, 7, 30, 0, 0, 0)


if __name__ == "__main__":
    main(
        default_start=START_TIME,
        default_end=END_TIME,
        default_pair=PAIR,
    )
