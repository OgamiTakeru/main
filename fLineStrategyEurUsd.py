"""Line strategy classes for EUR_USD."""

from fLineStrategyUsdJpy import LineStrategyProfileUsdJpy


class LineStrategyProfileEurUsd(LineStrategyProfileUsdJpy):
    """EUR_USD line strategy.

    For now this inherits the USD_JPY strategy.
    Override this class when EUR_USD needs different tactics.
    """

    pair = "EUR_USD"
