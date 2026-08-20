"""Rebuild causal USD/JPY ledgers before the following-one-year OOS replay.

Run this after any M5/H1 condition-schema change, then run
``test_long_inspection_prior2y_oos_replay_usd_jpy.py``.
"""

import datetime

from count2_resistance_sweep import main


PAIR = "USD_JPY"
START_TIME = datetime.datetime(2025, 7, 30)
END_TIME = datetime.datetime(2026, 7, 30)


if __name__ == "__main__":
    main(PAIR, default_start=START_TIME, default_end=END_TIME)
