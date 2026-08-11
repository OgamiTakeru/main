"""Run the current USD/JPY count2 win40 grid policy over the latest full year.

This is the same causal resistance sweep used for the 2026 YTD inspection,
but the requested window is 2025-07-30 through 2026-07-30.  The active
USD/JPY applies the full-year positive-rate-40% conditions as an OR gate and
uses each selected raw line rank, entry offset and TP/LC grid parameters.

Run without options to reuse compatible caches and fetch only missing or
incompatible frames from OANDA.  Add ``--existing-data`` to prohibit network
fetching and require every cache to be reusable.
"""

import datetime

from count2_resistance_sweep import main


PAIR = "USD_JPY"
START_TIME = datetime.datetime(2025, 7, 30, 0, 0, 0)
END_TIME = datetime.datetime(2026, 7, 30, 0, 0, 0)


if __name__ == "__main__":
    main(
        PAIR,
        default_start=START_TIME,
        default_end=END_TIME,
    )
