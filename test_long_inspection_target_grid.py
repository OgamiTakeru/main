"""Run the USD/JPY foot-count-2 entry/TP/LC grid for the cached full year.

Prerequisite: ``test_long_inspection.py`` must already have produced the
causal resistance-sweep candidate CSV, foot2 event CSV, and matching S5
cache.  This script does not contact OANDA and does not alter the live
strategy.

The first run builds a reusable typed S5 sidecar beside the CSV to avoid
loading the 1GB-class text cache into memory.  Outcome inspection is hard
bounded before END_TIME; rows at or after END_TIME are never read as labels.

The complete requested year is emitted without ranking or condition selection:

* full-year grid output: 2025-07-30 through 2026-07-30 (exclusive)
* all condition and entry/TP/LC combinations are retained
* no Top3 selection or train/holdout split is applied
"""

import datetime

from count2_target_grid_search import main


PAIR = "USD_JPY"
START_TIME = datetime.datetime(2025, 7, 30, 0, 0, 0)
END_TIME = datetime.datetime(2026, 7, 30, 0, 0, 0)


if __name__ == "__main__":
    main(
        default_start=START_TIME,
        default_end=END_TIME,
    )
