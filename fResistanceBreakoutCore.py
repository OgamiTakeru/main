# 最新更新日時: 2026-09-08 08:09 JST
"""抵抗線ブレイクの共通判定・価格計算。

OANDA通信、Discord通知、注文生成は行わない。検証と本番はこの
純粋関数を共用し、「同じ条件名だが中身が違う」状態を防ぐ。
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Mapping

import numpy as np
import pandas as pd

import fGeneric as gene


CORE_VERSION = "resistance_breakout_v1"
TIME_FORMAT = "%Y/%m/%d %H:%M:%S"
# OANDA の clientExtensions に付く出自タグ。実注文・建玉の身元になり、
# 再起動後の復元にも使われる。検証側（count2_resistance_sweep）と
# 本番側（fResistanceBreakoutAnalysis）で必ず同じ値を使う必要があるため、
# ここ一箇所で定義する。片方だけ変えると同等性テストが落ちる。
OWNER_TAG = "resistance_breakout"
# 注文の記録に残す版数。これも検証と本番で同じでなければ同等性テストが落ちる。
# 2026-09-08: trial を外して実発注に切り替えたため trial_v1 から改称。
ADAPTER_VERSION = "live_v1"
# 注文をそのまま発注してよいか。flip は「タッチ→観測」の見張りがあるので
# False で待機させるが、抵抗線ブレイクに見張りは無く、検証も「判断時刻に
# 逆指値を置いて次の count2 まで待つ」形だった。True が検証と同じ挙動。
# 検証側と本番側で違う値になっていると同等性テストが落ちる。
ORDER_PERMISSION = True


@dataclass(frozen=True)
class ResistanceBreakoutPolicy:
    """検証済みの抵抗線定義とtrial執行条件。"""

    policy_id: str = "resistance_breakout_trial_v1"
    timeframes: tuple[str, ...] = ("M5", "M30")
    trigger_foot_count: int = 2
    target_lookback: int = 6
    target_multiplier: float = 3.0
    rr: float = 1.2
    stop_offset_pips: float = 1.0
    assumed_stop_slippage_pips: float = 0.5
    spread_pips: float = 0.8
    min_tp_spread_ratio: float = 3.0
    line_history_bars: int = 60
    peak_history_bars: int = 180
    group_threshold_a: float = 0.5
    enforce_peak_strength_filter: bool = True
    min_line_peak_count: int = 2
    min_line_total_strength: float = 0.0
    min_line_direction_ratio: float = 0.7
    min_distance_a: float = 0.0
    exclude_flipped_recent: bool = False
    risk_yen: float = 500.0
    max_units: int = 3000
    priority: int = 5
    order_timeout_min: int = 60
    trade_timeout_min: int = 60

    def __post_init__(self) -> None:
        normalized_timeframes = tuple(
            str(value).strip().upper() for value in self.timeframes
        )
        if not normalized_timeframes:
            raise ValueError("timeframes must not be empty")
        if any(value not in ("M5", "M30", "H1") for value in normalized_timeframes):
            raise ValueError("timeframes must contain only M5, M30 or H1")
        if len(set(normalized_timeframes)) != len(normalized_timeframes):
            raise ValueError("timeframes must not contain duplicates")
        object.__setattr__(self, "timeframes", normalized_timeframes)
        if int(self.trigger_foot_count) < 1:
            raise ValueError("trigger_foot_count must be positive")
        if int(self.target_lookback) < 1:
            raise ValueError("target_lookback must be positive")
        if float(self.target_multiplier) <= 0 or float(self.rr) <= 0:
            raise ValueError("target_multiplier and rr must be positive")
        if float(self.stop_offset_pips) < 0:
            raise ValueError("stop_offset_pips must not be negative")
        if float(self.assumed_stop_slippage_pips) < 0:
            raise ValueError("assumed_stop_slippage_pips must not be negative")
        if float(self.spread_pips) < 0 or float(self.min_tp_spread_ratio) < 0:
            raise ValueError("spread settings must not be negative")
        if int(self.line_history_bars) < 1:
            raise ValueError("line_history_bars must be positive")
        if int(self.peak_history_bars) < int(self.line_history_bars):
            raise ValueError("peak_history_bars must be at least line_history_bars")
        if float(self.group_threshold_a) <= 0:
            raise ValueError("group_threshold_a must be positive")
        if int(self.min_line_peak_count) < 1:
            raise ValueError("min_line_peak_count must be positive")
        if not 0 <= float(self.min_line_direction_ratio) <= 1:
            raise ValueError("min_line_direction_ratio must be between 0 and 1")
        if float(self.risk_yen) <= 0 or int(self.max_units) < 1:
            raise ValueError("risk_yen and max_units must be positive")
        if int(self.priority) < 0:
            raise ValueError("priority must not be negative")
        if int(self.order_timeout_min) < 1 or int(self.trade_timeout_min) < 1:
            raise ValueError("order and trade timeout must be positive")


@dataclass(frozen=True)
class ResistanceBreakoutOrderLevels:
    line_price: float
    trigger_price: float
    tp_price: float
    lc_price: float
    trade_direction: int
    tp_pips: float
    lc_pips: float
    stop_offset_pips: float


def _pair_info(pair: gene.CurrencyPair | str) -> gene.CurrencyPair:
    if isinstance(pair, str):
        return gene.currency_pair(pair)
    return pair


def _time_series(frame: pd.DataFrame) -> pd.Series | None:
    if "time_jp_dt" in frame.columns:
        return pd.to_datetime(frame["time_jp_dt"], errors="coerce")
    if "time_jp" in frame.columns:
        return pd.to_datetime(frame["time_jp"], errors="coerce")
    return None


def _invalid_target(base: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        **base,
        "target_valid": False,
        "target_skip_reason": reason,
    }


def target_parameters(
    m5_completed_df_r: pd.DataFrame,
    decision_time: Any,
    pair: gene.CurrencyPair | str,
    lookback: int = 6,
    multiplier: float = 3.0,
    rr: float = 1.2,
) -> dict[str, Any]:
    """M5の判断前完成足だけからTP・LCを計算する。

    ``m5_completed_df_r`` は新しい足が0行目のDataFrame。開始時刻+
    5分が判断時刻以下の足だけを対象にする。途中欠損はここでは
    エラーにせず、取得できた直近の完成足を使う。
    """
    pair_info = _pair_info(pair)
    lookback = int(lookback)
    multiplier = float(multiplier)
    rr = float(rr)
    base = {
        "tp_lookback": lookback,
        "tp_multiplier": multiplier,
        "rr": rr,
    }
    if lookback < 1:
        return _invalid_target(base, "invalid_target_lookback")
    if multiplier <= 0 or rr <= 0:
        return _invalid_target(base, "invalid_target_multiplier_or_rr")
    if m5_completed_df_r is None or not isinstance(m5_completed_df_r, pd.DataFrame):
        return _invalid_target(base, "missing_completed_m5")
    if "high" not in m5_completed_df_r or "low" not in m5_completed_df_r:
        return _invalid_target(base, "missing_m5_range_columns")

    frame = m5_completed_df_r.copy()
    times = _time_series(frame)
    try:
        decision_timestamp = pd.Timestamp(decision_time)
    except (TypeError, ValueError):
        return _invalid_target(base, "invalid_m5_time")
    if times is None:
        return _invalid_target(base, "missing_m5_time_column")
    if pd.isna(decision_timestamp):
        return _invalid_target(base, "invalid_m5_time")
    if decision_timestamp.tzinfo is not None:
        decision_timestamp = decision_timestamp.tz_convert("Asia/Tokyo").tz_localize(None)
    series_timezone = getattr(times.dt, "tz", None)
    if series_timezone is not None:
        times = times.dt.tz_convert("Asia/Tokyo").dt.tz_localize(None)
    # 古い履歴に壊れた時刻が混ざっていても、利用する直近6本が正常なら
    # 見送らない。時刻不明の行だけを候補から外す。
    frame = frame.assign(_target_time=times)
    frame = frame[frame["_target_time"].notna()]
    frame = frame[
        frame["_target_time"] + pd.Timedelta(minutes=5)
        <= decision_timestamp
    ].sort_values("_target_time", ascending=False)
    completed = frame.iloc[:lookback].copy()
    if len(completed) != lookback:
        return _invalid_target(base, "insufficient_completed_m5")
    if (
        completed["_target_time"] + pd.Timedelta(minutes=5)
        > decision_timestamp
    ).any():
        return _invalid_target(base, "non_past_m5_in_target_window")

    high = pd.to_numeric(completed["high"], errors="coerce")
    low = pd.to_numeric(completed["low"], errors="coerce")
    ranges = (high - low) / pair_info.pip_value
    range_values = ranges.to_numpy(dtype=float)
    if not np.isfinite(range_values).all():
        return _invalid_target(base, "invalid_m5_range")
    average_range = float(ranges.mean())
    tp_pips = float(average_range * multiplier)
    if not math.isfinite(tp_pips) or tp_pips <= 0:
        return _invalid_target(base, "non_positive_target")
    chronological = completed.sort_values("_target_time")
    return {
        **base,
        "target_valid": True,
        "target_skip_reason": None,
        "target_source_first_time": pd.Timestamp(
            chronological.iloc[0]["_target_time"]
        ),
        "target_source_last_time": pd.Timestamp(
            chronological.iloc[-1]["_target_time"]
        ),
        "recent_m5_avg_range_pips": average_range,
        "recent_m5_median_range_pips": float(ranges.median()),
        "recent_m5_min_range_pips": float(ranges.min()),
        "recent_m5_max_range_pips": float(ranges.max()),
        "tp_pips": tp_pips,
        "lc_pips": float(tp_pips / rr),
    }


def average_range_pips_from_completed_df_r(
    completed_df_r: pd.DataFrame,
    pair: gene.CurrencyPair | str,
    lookback: int = 6,
) -> float | None:
    """新しい順の完成足から直近Aを返す。"""
    if completed_df_r is None or not isinstance(completed_df_r, pd.DataFrame):
        return None
    if "high" not in completed_df_r or "low" not in completed_df_r:
        return None
    recent = completed_df_r.iloc[: int(lookback)]
    if len(recent) != int(lookback):
        return None
    pair_info = _pair_info(pair)
    ranges = (
        pd.to_numeric(recent["high"], errors="coerce")
        - pd.to_numeric(recent["low"], errors="coerce")
    ) / pair_info.pip_value
    values = ranges.to_numpy(dtype=float)
    if not np.isfinite(values).all():
        return None
    average = float(ranges.mean())
    return average if math.isfinite(average) and average > 0 else None


def evaluate_breakout_trigger(
    newest_m5_peak: Mapping[str, Any] | None,
    required_foot_count: int = 2,
) -> dict[str, Any]:
    """最新M5ピークだけでブレイク解析の起動可否を決める。"""
    result = {
        "trigger_valid": False,
        "trigger_skip_reason": None,
        "trigger_foot_count": None,
        "peak_direction": None,
        "line_side": None,
        "trade_direction": None,
        "trade_side": None,
        "peak_time": None,
    }
    if not newest_m5_peak:
        result["trigger_skip_reason"] = "no_m5_peak"
        return result
    try:
        foot_count = int(newest_m5_peak.get("count", 0))
    except (TypeError, ValueError):
        result["trigger_skip_reason"] = "invalid_m5_peak_foot_count"
        return result
    result["trigger_foot_count"] = foot_count
    result["peak_time"] = (
        newest_m5_peak.get("latest_time_jp")
        or newest_m5_peak.get("time_jp")
    )
    if foot_count != int(required_foot_count):
        result["trigger_skip_reason"] = "m5_peak_foot_count_not_target"
        return result
    try:
        peak_direction = int(newest_m5_peak.get("direction", 0))
    except (TypeError, ValueError):
        peak_direction = 0
    if peak_direction not in (-1, 1):
        result["trigger_skip_reason"] = "invalid_m5_peak_direction"
        return result
    result.update({
        "trigger_valid": True,
        "trigger_skip_reason": None,
        "peak_direction": peak_direction,
        "line_side": "upper" if peak_direction == 1 else "lower",
        "trade_direction": peak_direction,
        "trade_side": "BUY" if peak_direction == 1 else "SELL",
    })
    return result


def native_direction_ratio(
    line: Mapping[str, Any],
    native_direction: int,
) -> float | None:
    """ラインの側に合う向きのピーク比率を返す。"""
    if int(native_direction) not in (-1, 1):
        raise ValueError("native_direction must be -1 or 1")
    values = []
    for value in line.get("dirs") or []:
        try:
            direction = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(direction) and direction != 0:
            values.append(direction)
    if not values:
        return None
    same = sum(1 for value in values if value * int(native_direction) > 0)
    return same / len(values)


def line_peak_signature(
    line: Mapping[str, Any],
) -> tuple[tuple[str | None, int | None, float | None, float | None], ...]:
    """Return the ordered source-peak identity of one grouped line."""
    signature = []
    for peak in line.get("prices_info") or []:
        raw_time = peak.get("latest_time_jp") or peak.get("time_jp")
        try:
            timestamp = pd.Timestamp(raw_time)
            time_text = (
                None
                if pd.isna(timestamp)
                else timestamp.isoformat()
            )
        except (TypeError, ValueError):
            time_text = str(raw_time) if raw_time is not None else None

        try:
            direction = int(float(peak.get("direction")))
        except (TypeError, ValueError):
            direction = None

        raw_price = (
            peak.get("latest_body_peak_price")
            if peak.get("latest_body_peak_price") is not None
            else peak.get("peak")
        )
        try:
            price = float(raw_price)
            if not math.isfinite(price):
                price = None
        except (TypeError, ValueError):
            price = None

        try:
            strength = float(peak.get("peak_strength"))
            if not math.isfinite(strength):
                strength = None
        except (TypeError, ValueError):
            strength = None
        signature.append((time_text, direction, price, strength))
    return tuple(signature)


def select_ahead_lines(
    peak_direction: int,
    current_price: float,
    upper_lines: list[dict[str, Any]],
    lower_lines: list[dict[str, Any]],
    pair: gene.CurrencyPair | str,
    profile: Any | None = None,
    entry_mode: str = "limit",
    average_range_pips: float | None = None,
    min_distance_a: float = 0.0,
    exclude_flipped_recent: bool = False,
) -> list[dict[str, Any]]:
    """最新ピークの進行方向の前方にある全ラインを近い順で返す。"""
    if int(peak_direction) not in (-1, 1):
        raise ValueError("peak_direction must be -1 or 1")
    mode = str(entry_mode).lower()
    if mode not in ("limit", "stop"):
        raise ValueError("entry_mode must be 'limit' or 'stop'")
    pair_info = _pair_info(pair)
    side = "upper" if int(peak_direction) == 1 else "lower"
    trade_direction = (
        int(peak_direction) if mode == "stop" else -int(peak_direction)
    )
    source = upper_lines if side == "upper" else lower_lines
    selected: list[dict[str, Any]] = []
    for line in source:
        try:
            raw_line_price = float(line["median_price"])
        except (KeyError, TypeError, ValueError):
            continue
        line_price = pair_info.round_price(raw_line_price)
        distance_pips = (
            (line_price - float(current_price))
            * int(peak_direction)
            / pair_info.pip_value
        )
        if not math.isfinite(distance_pips) or distance_pips <= 0:
            continue
        current_target: bool | None = None
        if profile is not None:
            try:
                current_target = bool(
                    profile.is_m5_reversal_target(side, line)
                )
            except (AttributeError, KeyError, TypeError, ValueError):
                current_target = None
        if min_distance_a > 0.0 and average_range_pips:
            if distance_pips < min_distance_a * float(average_range_pips):
                continue
        if exclude_flipped_recent:
            info = line.get("prices_info") or []
            if info:
                try:
                    newest_direction = int(
                        float(info[0].get("direction") or 0)
                    )
                except (TypeError, ValueError):
                    newest_direction = 0
                native = 1 if side == "upper" else -1
                if newest_direction != 0 and newest_direction != native:
                    continue
        selected.append({
            "line": line,
            "line_side": side,
            "trade_direction": trade_direction,
            "trade_side": "BUY" if trade_direction == 1 else "SELL",
            "approach_side": int(peak_direction),
            "entry_mode": mode,
            "raw_line_price": raw_line_price,
            "line_price": line_price,
            "distance_pips": float(distance_pips),
            "current_policy_reversal_target": current_target,
        })
    selected.sort(key=lambda item: (item["distance_pips"], item["line_price"]))
    for rank, item in enumerate(selected, start=1):
        item["candidate_rank"] = rank
        item["distance_rank"] = rank
    return selected


def stop_trigger_price(
    line_price: float,
    trade_direction: int,
    pair: gene.CurrencyPair | str,
    stop_offset_pips: float = 1.0,
) -> float:
    """ラインを突破する側のSTOP起動価格を返す。"""
    if int(trade_direction) not in (-1, 1):
        raise ValueError("trade_direction must be -1 or 1")
    line_price = float(line_price)
    stop_offset_pips = float(stop_offset_pips)
    if not math.isfinite(line_price):
        raise ValueError("line_price must be finite")
    if not math.isfinite(stop_offset_pips) or stop_offset_pips < 0:
        raise ValueError("stop_offset_pips must be finite and non-negative")
    pair_info = _pair_info(pair)
    return pair_info.round_price(
        line_price
        + int(trade_direction) * pair_info.pips_to_price(stop_offset_pips)
    )


def stop_actual_entry_price(
    trigger_price: float,
    trade_direction: int,
    pair: gene.CurrencyPair | str,
    slippage_pips: float = 0.0,
) -> float:
    """検証用に、STOP起動後の不利側スリッページを加える。"""
    if int(trade_direction) not in (-1, 1):
        raise ValueError("trade_direction must be -1 or 1")
    slippage_pips = float(slippage_pips)
    if not math.isfinite(slippage_pips) or slippage_pips < 0:
        raise ValueError("slippage_pips must be finite and non-negative")
    pair_info = _pair_info(pair)
    return pair_info.round_price(
        float(trigger_price)
        + int(trade_direction) * pair_info.pips_to_price(slippage_pips)
    )


def build_stop_order_levels(
    line_price: float,
    trade_direction: int,
    tp_pips: float,
    lc_pips: float,
    pair: gene.CurrencyPair | str,
    stop_offset_pips: float = 1.0,
) -> ResistanceBreakoutOrderLevels:
    """STOP、TP、LCの絶対価格をまとめて返す。"""
    if int(trade_direction) not in (-1, 1):
        raise ValueError("trade_direction must be -1 or 1")
    tp_pips = float(tp_pips)
    lc_pips = float(lc_pips)
    if (
        not math.isfinite(tp_pips)
        or not math.isfinite(lc_pips)
        or tp_pips <= 0
        or lc_pips <= 0
    ):
        raise ValueError("tp_pips and lc_pips must be finite and positive")
    pair_info = _pair_info(pair)
    rounded_line = pair_info.round_price(float(line_price))
    trigger = stop_trigger_price(
        rounded_line,
        trade_direction,
        pair_info,
        stop_offset_pips,
    )
    tp_price = pair_info.round_price(
        trigger + int(trade_direction) * pair_info.pips_to_price(tp_pips)
    )
    lc_price = pair_info.round_price(
        trigger - int(trade_direction) * pair_info.pips_to_price(lc_pips)
    )
    return ResistanceBreakoutOrderLevels(
        line_price=rounded_line,
        trigger_price=trigger,
        tp_price=tp_price,
        lc_price=lc_price,
        trade_direction=int(trade_direction),
        tp_pips=tp_pips,
        lc_pips=lc_pips,
        stop_offset_pips=float(stop_offset_pips),
    )


def live_target_is_wide_enough(
    tp_pips: float,
    spread_pips: float = 0.8,
    min_ratio: float = 3.0,
) -> bool:
    """利確幅が固定スプレッドに対して十分かを返す。"""
    try:
        tp_pips = float(tp_pips)
        spread_pips = float(spread_pips)
        min_ratio = float(min_ratio)
    except (TypeError, ValueError):
        return False
    if not all(math.isfinite(value) for value in (tp_pips, spread_pips, min_ratio)):
        return False
    if tp_pips <= 0 or spread_pips < 0 or min_ratio < 0:
        return False
    return tp_pips >= spread_pips * min_ratio
