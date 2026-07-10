"""Line strategy classes for AUD_USD."""

import copy

from fLineStrategyEurUsd import LineStrategyProfileEurUsd


class LineStrategyProfileAudUsd(LineStrategyProfileEurUsd):
    """AUD_USD line strategy."""

    pair = "AUD_USD"
    top10_conditions = [
        {"label": "AUD Top1 RSI50-60 H1RSI67.5+", "filters": {"m5_rsi_bin": "50-60", "h1_rsi_bin": "67.5+"}},
        {"label": "AUD Top2 upper 0-3p session09-14", "filters": {"distance_bin": "0-3p", "line_side": "upper", "session_bucket": "09-14"}},
        {"label": "AUD Top3 5-8p RSI60-67.5", "filters": {"distance_bin": "5-8p", "m5_rsi_bin": "60-67.5"}},
        {"label": "AUD Top4 lower 15-20p lineStr0-5", "filters": {"distance_bin": "15-20p", "line_side": "lower", "line_strength_bin": "0-5"}},
        {"label": "AUD Top5 RSI60-67.5 H1RSI50-60", "filters": {"m5_rsi_bin": "60-67.5", "h1_rsi_bin": "50-60"}},
        {"label": "AUD Top6 upper 8-10p prevH1Str10-15", "filters": {"previous_h1_strength_bin": "10-15", "distance_bin": "8-10p", "line_side": "upper"}},
        {"label": "AUD Top7 upper H1nearStr15-20", "filters": {"h1_nearest_strength_bin": "15-20", "line_side": "upper"}},
        {"label": "AUD Top8 upper 0-3p prevH1Str5-8", "filters": {"previous_h1_strength_bin": "5-8", "distance_bin": "0-3p", "line_side": "upper"}},
        {"label": "AUD Top9 upper 0-3p session21-23", "filters": {"distance_bin": "0-3p", "line_side": "upper", "session_bucket": "21-23"}},
        {"label": "AUD Top10 buy 0-3p session21-23", "filters": {"distance_bin": "0-3p", "direction_label": "buy", "session_bucket": "21-23"}},
    ]
    breakout_top_conditions = copy.deepcopy(LineStrategyProfileEurUsd.breakout_top_conditions)


for condition in LineStrategyProfileAudUsd.breakout_top_conditions:
    condition["label"] = condition["label"].replace("EUR", "AUD")
