"""Line strategy classes for AUD_USD."""

import copy

from fLineStrategyEurUsd import LineStrategyProfileEurUsd


class LineStrategyProfileAudUsd(LineStrategyProfileEurUsd):
    """AUD_USD line strategy."""

    pair = "AUD_USD"
    breakout_top_conditions = copy.deepcopy(LineStrategyProfileEurUsd.breakout_top_conditions)


for condition in LineStrategyProfileAudUsd.breakout_top_conditions:
    condition["label"] = condition["label"].replace("EUR", "AUD")
