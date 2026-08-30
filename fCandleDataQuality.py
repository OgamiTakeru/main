# 最新更新日時: 2026-08-29 21:21 JST
"""判断時刻時点のローソク履歴について、鮮度と欠損を共通検査する。"""

from __future__ import annotations

import datetime as dt
import functools
from typing import Any

import numpy as np
import pandas as pd


JST_NAME = "Asia/Tokyo"
NY_NAME = "America/New_York"
S5_STEP = pd.Timedelta(seconds=5)
MAX_KNOWN_CLOSURE = pd.Timedelta(days=4)
ANALYSIS_CLOSURE_EDGE_TOLERANCE = pd.Timedelta(minutes=15)
MAX_ANALYSIS_MISSING_RATIO = 0.50
DAILY_PAUSE_START = dt.time(16, 59)
DAILY_PAUSE_END = dt.time(17, 5)


class CandleHistoryError(ValueError):
    """完成足履歴を安全な解析入力として使えない。"""


class CandleHistoryNotReady(CandleHistoryError):
    """最新完成足の公開待ち、または休場中で判断境界に届いていない。"""


class CandleHistoryIntegrityError(CandleHistoryError):
    """必要本数不足、未知欠損、境界超過など履歴の完全性に問題がある。"""


def _as_jst_timestamp(value: Any) -> pd.Timestamp:
    stamp = pd.Timestamp(value)
    if pd.isna(stamp):
        raise CandleHistoryIntegrityError("candle history contains an invalid time")
    if stamp.tzinfo is None:
        return stamp.tz_localize(JST_NAME)
    return stamp.tz_convert(JST_NAME)


def _as_jst_naive(value: Any) -> pd.Timestamp:
    return _as_jst_timestamp(value).tz_localize(None)


def _as_jst_index(values: Any) -> pd.DatetimeIndex:
    index = pd.DatetimeIndex(pd.to_datetime(values, errors="coerce"))
    if index.isna().any():
        raise CandleHistoryIntegrityError("candle history contains an invalid time")
    if index.tz is None:
        return index.tz_localize(JST_NAME)
    return index.tz_convert(JST_NAME)


def oanda_market_open_mask(times: Any) -> np.ndarray:
    """各5秒時刻が通常のOANDA FX営業時間内かを返す。"""
    index = _as_jst_index(times)
    if len(index) == 0:
        return np.zeros(0, dtype=bool)
    local = index.tz_convert(NY_NAME)
    weekday = local.weekday
    seconds = local.hour * 3600 + local.minute * 60 + local.second
    daily_pause_start = (
        DAILY_PAUSE_START.hour * 3600
        + DAILY_PAUSE_START.minute * 60
    )
    daily_pause_end = (
        DAILY_PAUSE_END.hour * 3600
        + DAILY_PAUSE_END.minute * 60
    )
    monday_to_thursday = weekday < 4
    friday = weekday == 4
    sunday = weekday == 6
    return np.asarray(
        (
            monday_to_thursday
            & ~(
                (seconds >= daily_pause_start)
                & (seconds < daily_pause_end)
            )
        )
        | (friday & (seconds < daily_pause_start))
        | (sunday & (seconds >= daily_pause_end)),
        dtype=bool,
    )


def _observed_annual_holiday(actual_day: dt.date) -> dt.date:
    """FX休場判定で使うChristmas/New-Yearの振替日。"""
    if actual_day.weekday() == 5:
        return actual_day - dt.timedelta(days=1)
    if actual_day.weekday() == 6:
        return actual_day + dt.timedelta(days=1)
    return actual_day


def annual_holiday_closed_mask(times: Any) -> np.ndarray:
    """Christmas/New-Yearの一取引日休場内かをNY時刻で返す。

    通常の日次休止が始まる休日前日16:59から、休日当日の
    17:05までを閉場とする。週末の祝日は金曜日または月曜日へ
    振り替える。このmaskは長時間ギャップとカバレッジ端点用であり、
    短時間のno-tick補完には使わない。
    """
    index = _as_jst_index(times)
    if len(index) == 0:
        return np.zeros(0, dtype=bool)
    local = index.tz_convert(NY_NAME)
    closed = np.zeros(len(local), dtype=bool)
    first_year = int(local.min().year) - 1
    last_year = int(local.max().year) + 1
    for year in range(first_year, last_year + 1):
        for month, day in ((1, 1), (12, 25)):
            observed = _observed_annual_holiday(dt.date(year, month, day))
            start = pd.Timestamp(
                dt.datetime.combine(
                    observed - dt.timedelta(days=1),
                    DAILY_PAUSE_START,
                ),
                tz=NY_NAME,
            )
            end = pd.Timestamp(
                dt.datetime.combine(observed, DAILY_PAUSE_END),
                tz=NY_NAME,
            )
            closed |= np.asarray((local >= start) & (local < end), dtype=bool)
    return closed


def oanda_coverage_open_mask(times: Any) -> np.ndarray:
    """通常休場と既知の年次休場を除いたカバレッジ用営業時間。"""
    return np.asarray(
        oanda_market_open_mask(times)
        & ~annual_holiday_closed_mask(times),
        dtype=bool,
    )


@functools.lru_cache(maxsize=4096)
def is_expected_annual_holiday_closure_gap(
        previous_time: pd.Timestamp,
        next_time: pd.Timestamp,
) -> bool:
    """Christmas/New-Yearが必要な長時間休場だけを認める。"""
    previous_jst = _as_jst_timestamp(previous_time)
    next_jst = _as_jst_timestamp(next_time)
    gap = next_jst - previous_jst
    if gap < pd.Timedelta(hours=12) or gap > pd.Timedelta(hours=96):
        return False
    missing_times = pd.date_range(
        start=previous_jst + S5_STEP,
        end=next_jst - S5_STEP,
        freq=S5_STEP,
    )
    if not len(missing_times):
        return False
    regular_open = oanda_market_open_mask(missing_times)
    annual_closed = annual_holiday_closed_mask(missing_times)
    holiday_effect = bool((regular_open & annual_closed).any())
    unexpected_open = bool((regular_open & ~annual_closed).any())
    return bool(holiday_effect and not unexpected_open)


@functools.lru_cache(maxsize=4096)
def is_expected_market_closed_gap(
        previous_time: pd.Timestamp,
        next_time: pd.Timestamp,
) -> bool:
    """欠けた全S5時刻が通常休場または既知の年次休場ならTrue。"""
    previous_jst = _as_jst_timestamp(previous_time)
    next_jst = _as_jst_timestamp(next_time)
    gap = next_jst - previous_jst
    if gap <= S5_STEP or gap > MAX_KNOWN_CLOSURE:
        return False

    missing_times = pd.date_range(
        start=previous_jst + S5_STEP,
        end=next_jst - S5_STEP,
        freq=S5_STEP,
    )
    if not len(missing_times):
        return False
    regular_closure = not bool(oanda_market_open_mask(missing_times).any())
    return bool(
        regular_closure
        or is_expected_annual_holiday_closure_gap(previous_jst, next_jst)
    )


@functools.lru_cache(maxsize=4096)
def is_expected_coverage_closed_gap(
        previous_time: pd.Timestamp,
        next_time: pd.Timestamp,
) -> bool:
    """最新端点までの全S5が休場スケジュール内かを返す。

    内部の短時間欠損を許容する関数ではない。最新足から判断境界
    までの公開待ち/休場を分類する場合と、データ取得範囲の端点
    計算に限って使う。
    """
    previous_jst = _as_jst_timestamp(previous_time)
    next_jst = _as_jst_timestamp(next_time)
    gap = next_jst - previous_jst
    if gap <= S5_STEP or gap > MAX_KNOWN_CLOSURE:
        return False
    missing_times = pd.date_range(
        start=previous_jst + S5_STEP,
        end=next_jst - S5_STEP,
        freq=S5_STEP,
    )
    return bool(
        len(missing_times)
        and not oanda_coverage_open_mask(missing_times).any()
    )


@functools.lru_cache(maxsize=4096)
def is_acceptable_analysis_gap(
        previous_time: pd.Timestamp,
        next_time: pd.Timestamp,
        edge_tolerance: pd.Timedelta = ANALYSIS_CLOSURE_EDGE_TOLERANCE,
) -> bool:
    """解析履歴に限り、休場の両端にある小さな欠損を認める。

    通常の営業時間内だけの欠損は認めない。欠損区間に既知休場が
    実際に含まれ、営業時間にはみ出した部分が先頭または末尾の
    各15分以内の場合だけ許容する。注文後のS5経路判定には使わない。
    """
    previous_jst = _as_jst_timestamp(previous_time)
    next_jst = _as_jst_timestamp(next_time)
    gap = next_jst - previous_jst
    tolerance = pd.Timedelta(edge_tolerance)
    if (
            gap <= S5_STEP
            or gap > MAX_KNOWN_CLOSURE
            or tolerance < pd.Timedelta(0)
    ):
        return False
    missing_times = pd.date_range(
        start=previous_jst + S5_STEP,
        end=next_jst - S5_STEP,
        freq=S5_STEP,
    )
    if not len(missing_times):
        return False

    scheduled_open = np.asarray(
        oanda_coverage_open_mask(missing_times),
        dtype=bool,
    )
    if not bool((~scheduled_open).any()):
        return False
    if not bool(scheduled_open.any()):
        return True

    leading_open = 0
    while leading_open < len(scheduled_open) and scheduled_open[leading_open]:
        leading_open += 1
    trailing_open = 0
    while (
            trailing_open < len(scheduled_open) - leading_open
            and scheduled_open[len(scheduled_open) - trailing_open - 1]
    ):
        trailing_open += 1

    middle_end = len(scheduled_open) - trailing_open
    if bool(scheduled_open[leading_open:middle_end].any()):
        return False
    tolerance_steps = int(tolerance // S5_STEP)
    return bool(
        leading_open <= tolerance_steps
        and trailing_open <= tolerance_steps
    )


def validate_decision_market_open(decision_time: Any) -> None:
    """判断時刻自体が通常のOANDA FX営業時間か確認する。

    年次休場は年ごとの実際の配信時刻に幅があるため、ここでは
    一律に閉場にしない。実データが止まっている場合は、最新M5の
    境界検査が既知休場としてNotReadyにする。
    """
    decision = _as_jst_timestamp(decision_time)
    if not bool(oanda_market_open_mask(pd.DatetimeIndex([decision]))[0]):
        raise CandleHistoryNotReady(
            "OANDA market is closed at the decision time"
        )


def _frame_times(frame: pd.DataFrame, label: str) -> pd.Series:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        raise CandleHistoryIntegrityError(label + " completed history is empty")
    time_column = (
        "time_jp_dt" if "time_jp_dt" in frame.columns else "time_jp"
    )
    if time_column not in frame.columns:
        raise CandleHistoryIntegrityError(label + " history has no time column")
    parsed = pd.to_datetime(frame[time_column], errors="coerce")
    if parsed.isna().any():
        raise CandleHistoryIntegrityError(label + " history has an invalid time")
    if getattr(parsed.dt, "tz", None) is not None:
        parsed = parsed.dt.tz_convert(JST_NAME).dt.tz_localize(None)
    return parsed


def analysis_missing_bar_stats(
        times: Any,
        candle_duration: Any,
        *,
        expected_end: Any | None = None,
) -> dict[str, Any]:
    """解析区間の営業時間内欠損本数を、休場を除外して数える。"""
    duration = pd.Timedelta(candle_duration)
    if duration <= pd.Timedelta(0):
        raise ValueError("candle_duration must be positive")
    ordered = sorted(_as_jst_naive(value) for value in list(times))
    if not ordered:
        raise CandleHistoryIntegrityError("analysis history is empty")
    if len(set(ordered)) != len(ordered):
        raise CandleHistoryIntegrityError(
            "analysis history contains duplicate times"
        )

    missing_bars = 0
    closure_gaps = 0

    def count_open_candles(starts: pd.DatetimeIndex) -> int:
        if not len(starts):
            return 0
        candle_ends = starts + duration - S5_STEP
        open_at_start = oanda_coverage_open_mask(starts)
        open_at_end = oanda_coverage_open_mask(candle_ends)
        return int(np.count_nonzero(open_at_start | open_at_end))

    for previous, following in zip(ordered, ordered[1:]):
        difference = following - previous
        if difference == duration:
            continue
        if difference <= duration or difference % duration != pd.Timedelta(0):
            raise CandleHistoryIntegrityError(
                "analysis history contains an off-grid gap"
            )
        missing_starts = pd.date_range(
            start=previous + duration,
            end=following - duration,
            freq=duration,
        )
        open_missing = count_open_candles(missing_starts)
        if open_missing < len(missing_starts):
            closure_gaps += 1
        missing_bars += open_missing

    latest_missing_bars = 0
    if expected_end is not None:
        expected = _as_jst_naive(expected_end)
        latest_end = ordered[-1] + duration
        if latest_end > expected:
            raise CandleHistoryIntegrityError(
                "analysis history extends beyond the decision boundary"
            )
        if latest_end < expected:
            difference = expected - latest_end
            if difference % duration != pd.Timedelta(0):
                raise CandleHistoryIntegrityError(
                    "analysis latest boundary is off-grid"
                )
            missing_starts = pd.date_range(
                start=latest_end,
                end=expected - duration,
                freq=duration,
            )
            latest_missing_bars = count_open_candles(missing_starts)
            if latest_missing_bars < len(missing_starts):
                closure_gaps += 1
            missing_bars += latest_missing_bars

    actual_bars = len(ordered)
    denominator = actual_bars + missing_bars
    missing_ratio = (
        float(missing_bars / denominator)
        if denominator
        else 1.0
    )
    return {
        "actual_bars": actual_bars,
        "missing_bars": int(missing_bars),
        "latest_missing_bars": int(latest_missing_bars),
        "missing_ratio": missing_ratio,
        "closure_gap_count": int(closure_gaps),
    }


def validate_history_coverage(
        frame: pd.DataFrame,
        required_bars: int,
        candle_duration: Any,
        label: str,
        *,
        expected_end: Any | None = None,
        max_missing_ratio: float = MAX_ANALYSIS_MISSING_RATIO,
) -> pd.DataFrame:
    """必要本数と欠損率を検査し、古い順の履歴を返す。"""
    required = int(required_bars)
    duration = pd.Timedelta(candle_duration)
    maximum_missing = float(max_missing_ratio)
    if (
            required < 1
            or duration <= pd.Timedelta(0)
            or not 0 <= maximum_missing < 1
    ):
        raise ValueError(
            "required_bars, candle_duration and max_missing_ratio are invalid"
        )

    work = frame.copy()
    work["_quality_time"] = _frame_times(work, label)
    work.sort_values("_quality_time", kind="stable", inplace=True)
    if work["_quality_time"].duplicated().any():
        raise CandleHistoryIntegrityError(label + " history contains duplicate times")
    if len(work) < required:
        raise CandleHistoryIntegrityError(
            f"insufficient {label} history: {len(work)}/{required}"
        )

    selected = work.tail(required).copy()
    times = selected["_quality_time"].tolist()
    stats = analysis_missing_bar_stats(
        times,
        duration,
        expected_end=expected_end,
    )
    if stats["missing_ratio"] >= maximum_missing:
        raise CandleHistoryIntegrityError(
            "too many missing bars in required "
            + label
            + " history: "
            + str(stats["missing_bars"])
            + "/"
            + str(stats["actual_bars"] + stats["missing_bars"])
        )

    selected.drop(columns="_quality_time", inplace=True)
    selected.reset_index(drop=True, inplace=True)
    selected.attrs["candle_quality"] = stats
    return selected


def validate_latest_boundary(
        frame: pd.DataFrame,
        expected_end: Any,
        candle_duration: Any,
        label: str,
        *,
        allow_known_closure: bool = False,
        stale_is_integrity: bool = False,
        allow_stale_missing: bool = False,
) -> pd.Timestamp:
    """最新完成足の終端が、その解析で必要な判断境界へ届いたか検査する。"""
    duration = pd.Timedelta(candle_duration)
    times = _frame_times(frame, label)
    latest_end = pd.Timestamp(times.max()) + duration
    expected = _as_jst_naive(expected_end)
    if latest_end == expected:
        return latest_end
    if latest_end > expected:
        raise CandleHistoryIntegrityError(
            label + " context extends beyond the decision boundary"
        )
    last_covered_time = latest_end - S5_STEP
    known_closure = is_acceptable_analysis_gap(
        last_covered_time,
        expected,
    )
    if allow_known_closure:
        if known_closure:
            return latest_end
    if allow_stale_missing:
        return latest_end
    if stale_is_integrity and not known_closure:
        raise CandleHistoryIntegrityError(
            label + " history is stale inside scheduled market hours"
        )
    raise CandleHistoryNotReady(
        "latest completed " + label + " is not ready at the decision boundary"
    )


def validate_completed_history(
        frame: pd.DataFrame,
        decision_time: Any,
        candle_duration: Any,
        required_bars: int,
        label: str,
        *,
        latest_boundary: str,
        allow_latest_known_closure: bool = False,
        stale_is_integrity: bool = False,
        require_market_open: bool = False,
) -> pd.DataFrame:
    """鮮度・本数・途中欠損を検査し、最新時刻が上の履歴を返す。"""
    decision = _as_jst_naive(decision_time)
    if latest_boundary == "M5":
        if decision.minute % 5 != 0:
            raise CandleHistoryIntegrityError(
                "M5 decision_time is not on a five-minute boundary"
            )
        expected_end = decision.floor("5min")
    elif latest_boundary == "H1":
        expected_end = decision.floor("h")
    else:
        raise ValueError("latest_boundary must be M5 or H1")

    ascending = validate_history_coverage(
        frame,
        required_bars,
        candle_duration,
        label,
        expected_end=expected_end,
    )
    quality_stats = dict(ascending.attrs.get("candle_quality") or {})
    validate_latest_boundary(
        ascending,
        expected_end,
        candle_duration,
        label,
        allow_known_closure=allow_latest_known_closure,
        stale_is_integrity=stale_is_integrity,
        allow_stale_missing=True,
    )
    if require_market_open:
        validate_decision_market_open(decision)
    validated_df_r = ascending.iloc[::-1].reset_index(drop=True)
    validated_df_r.attrs["candle_quality"] = quality_stats
    return validated_df_r
