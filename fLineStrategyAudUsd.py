"""Line strategy classes for AUD_USD."""

import copy

from fLineStrategyEurUsd import LineStrategyProfileEurUsd


class LineStrategyProfileAudUsd(LineStrategyProfileEurUsd):
    """AUD_USD line strategy."""

    pair = "AUD_USD"
    top10_conditions = [
        {
            "label": "AUD 1Y Top1 path20-30 session06-08",
            "filters": {"path1_distance_bin": "20-30p", "session_bucket": "06-08"},
        },
        {
            "label": "AUD 1Y Top2 path50+ breakout path1Str5-10",
            "filters": {
                "path1_distance_bin": "50+p",
                "line_entry_type": "breakout",
                "path1_strength_bin": "5-10",
            },
        },
        {
            "label": "AUD 1Y Top3 reversal sell session06-08 peakRSI-high",
            "filters": {
                "line_entry_type": "reversal",
                "direction_label": "sell",
                "session_bucket": "06-08",
                "peak_rsi_direction_ok": True,
            },
        },
        {
            "label": "AUD 1Y Top4 path3-6 coreStr10-15",
            "filters": {"path1_distance_bin": "3-6p", "core_strength_bin": "10-15"},
        },
        {
            "label": "AUD 1Y Top5 dist0-3 reversal session06-08 peakRSI-dir",
            "filters": {
                "distance_bin": "0-3p",
                "line_entry_type": "reversal",
                "session_bucket": "06-08",
                "peak_rsi_direction_ok": True,
            },
        },
        {
            "label": "AUD 1Y Top6 sell session06-08 peakRSI-high",
            "filters": {
                "direction_label": "sell",
                "session_bucket": "06-08",
                "peak_rsi_direction_ok": True,
            },
        },
        {
            "label": "AUD 1Y Top7 path50+ breakout session09-14",
            "filters": {
                "path1_distance_bin": "50+p",
                "line_entry_type": "breakout",
                "session_bucket": "09-14",
            },
        },
        {
            "label": "AUD 1Y Top8 session06-08 path1Str10-15",
            "filters": {"session_bucket": "06-08", "path1_strength_bin": "10-15"},
        },
        {
            "label": "AUD 1Y Top9 path3-6 dist15-20",
            "filters": {"path1_distance_bin": "3-6p", "distance_bin": "15-20p"},
        },
        {
            "label": "AUD 1Y Top10 path15-20 reversal path1Str10-15 peakRSI-dir",
            "filters": {
                "path1_distance_bin": "15-20p",
                "line_entry_type": "reversal",
                "path1_strength_bin": "10-15",
                "peak_rsi_direction_ok": True,
            },
        },
    ]
    breakout_top_conditions = copy.deepcopy(LineStrategyProfileEurUsd.breakout_top_conditions)


for condition in LineStrategyProfileAudUsd.breakout_top_conditions:
    condition["label"] = condition["label"].replace("EUR", "AUD")
