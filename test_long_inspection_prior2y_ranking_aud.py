"""Create AUD/USD M5/H1 shape Top rankings from the prior-two-year grid."""

import datetime

from count2_prior2y_ranking import main


if __name__ == "__main__":
    main(
        default_pair="AUD_USD",
        default_start=datetime.datetime(2023, 7, 30),
        default_end=datetime.datetime(2025, 7, 30),
    )
