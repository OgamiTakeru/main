"""Create USD/JPY Top rankings from the completed prior-two-year grid."""

import datetime

from count2_prior2y_ranking import main


if __name__ == "__main__":
    main(
        default_pair="USD_JPY",
        default_start=datetime.datetime(2023, 7, 30),
        default_end=datetime.datetime(2025, 7, 30),
    )
