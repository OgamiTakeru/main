"""Kick the complete cached count2 stability workflow for AUD/USD."""

import datetime

from count2_stability_pipeline import main


PAIR = "AUD_USD"
SELECTION_START = datetime.datetime(2023, 7, 30, 0, 0, 0)
SELECTION_END = datetime.datetime(2025, 7, 30, 0, 0, 0)
FOLLOWING_START = datetime.datetime(2025, 7, 30, 0, 0, 0)
FOLLOWING_END = datetime.datetime(2026, 7, 30, 0, 0, 0)


if __name__ == "__main__":
    main(
        default_pair=PAIR,
        default_selection_start=SELECTION_START,
        default_selection_end=SELECTION_END,
        default_following_start=FOLLOWING_START,
        default_following_end=FOLLOWING_END,
    )
