"""Count-2 resistance-line exhaustive validation.

At every M5 decision point where the newest peak has count == 2, this module
rebuilds the M5 resistance/support candidates using only candles completed at
that time.  Every line ahead of the peak direction is then tested as an
independent, counterfactual LIMIT order.

The candidate rows are opportunities, not simultaneously executable orders.
Use ``event_id`` when comparing alternatives within the same decision.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import functools
import io
import json
import math
import os
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd

import classOanda
from classCandlePeaks import PeaksClass
import fGeneric as gene
from fLineAnalysis import (
    LineStrengthCal,
    line_strategy_profile,
    predict_reversal_last_reach_context,
)
from fStairTrend import detect_h1_stair_trend, detect_m5_stair_trend
import test_win_point_usd_aud as win_point
import tokens as tk


DEFAULT_START = dt.datetime(2025, 7, 30)
DEFAULT_END = dt.datetime(2026, 7, 30)
LINE_HISTORY_BARS = 60
PEAK_HISTORY_BARS = 180
H1_HISTORY_BARS = 240
H1_PREHISTORY_CALENDAR_HOURS = 24 * 21
TP_LOOKBACK = 6
TP_MULTIPLIER = 3.0
RR = 1.2
SPREAD_PIPS = 0.8
HORIZON_MINUTES = 60
RETOUCH_TOLERANCE_PIPS = 1.0
S5_SECONDS = 5
TIME_FORMAT = "%Y/%m/%d %H:%M:%S"


def parse_args(
    pair_name: str,
    argv: list[str] | None = None,
    *,
    default_start: dt.datetime | None = None,
    default_end: dt.datetime | None = None,
) -> argparse.Namespace:
    default_start = default_start or DEFAULT_START
    default_end = default_end or DEFAULT_END
    parser = argparse.ArgumentParser(
        description=(
            f"{pair_name}: count2時点の進行方向先にあるM5抵抗線候補を"
            "LIMIT注文として総当たり検証する"
        )
    )
    parser.add_argument("--start", default=default_start.isoformat(" "))
    parser.add_argument("--end", default=default_end.isoformat(" "))
    parser.add_argument("--tp-lookback", type=int, default=TP_LOOKBACK)
    parser.add_argument("--tp-multiplier", type=float, default=TP_MULTIPLIER)
    parser.add_argument("--rr", type=float, default=RR)
    parser.add_argument(
        "--spread-pips",
        type=float,
        default=SPREAD_PIPS,
        help="S5約定・決済判定に使う固定スプレッド",
    )
    parser.add_argument(
        "--horizon-minutes",
        type=int,
        default=HORIZON_MINUTES,
        help="約定後の評価時間",
    )
    parser.add_argument(
        "--retouch-tolerance-pips",
        type=float,
        default=RETOUCH_TOLERANCE_PIPS,
        help="ライン形成後の再到達を数える価格帯の片側幅",
    )
    parser.add_argument(
        "--existing-data",
        action="store_true",
        help="既存キャッシュだけを使用し、不足時はエラーにする",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(tk.folder_path),
    )
    parser.add_argument(
        "--min-group-size",
        type=int,
        default=30,
        help="ランキングに残す候補数の下限",
    )
    parser.add_argument(
        "--max-events",
        type=int,
        default=None,
        help="開発用。先頭から評価するcount2イベント数を制限する",
    )
    args = parser.parse_args(argv)
    args.start = pd.Timestamp(args.start).to_pydatetime()
    args.end = pd.Timestamp(args.end).to_pydatetime()
    if args.start >= args.end:
        parser.error("--start は --end より前にしてください")
    if args.tp_lookback < 1:
        parser.error("--tp-lookback は1以上にしてください")
    if args.tp_multiplier <= 0 or args.rr <= 0:
        parser.error("--tp-multiplier と --rr は正数にしてください")
    if args.spread_pips < 0 or args.horizon_minutes < 1:
        parser.error("--spread-pips は0以上、--horizon-minutes は1以上です")
    if args.max_events is not None and args.max_events < 1:
        parser.error("--max-events は1以上にしてください")
    return args


def _normalize_time(
    df: pd.DataFrame,
    *,
    copy_frame: bool = True,
) -> pd.DataFrame:
    if copy_frame:
        df = df.copy()
    df["time_jp_dt"] = pd.to_datetime(
        df["time_jp"],
        format=TIME_FORMAT,
        errors="raise",
    )
    if not df["time_jp_dt"].is_monotonic_increasing:
        df.sort_values("time_jp_dt", inplace=True)
    if df["time_jp_dt"].duplicated().any():
        df.drop_duplicates("time_jp_dt", keep="last", inplace=True)
    df.reset_index(drop=True, inplace=True)
    return df


def prepare_m5(df: pd.DataFrame) -> pd.DataFrame:
    """Supply the candle fields used by PeaksClass without using future rows."""
    df = _normalize_time(df)
    for column in ("open", "close", "high", "low"):
        df[column] = pd.to_numeric(df[column], errors="coerce")

    df["inner_high"] = df.get(
        "inner_high",
        pd.concat([df["open"], df["close"]], axis=1).max(axis=1),
    )
    df["inner_low"] = df.get(
        "inner_low",
        pd.concat([df["open"], df["close"]], axis=1).min(axis=1),
    )
    df["body"] = df.get("body", df["close"] - df["open"])
    df["body_abs"] = df.get("body_abs", df["body"].abs())
    df["direction"] = df.get("direction", np.sign(df["body"]).replace(0, 1))
    df["moves"] = df.get("moves", df["high"] - df["low"])
    df["highlow"] = df.get("highlow", df["moves"])
    df["mid_outer"] = df.get("mid_outer", (df["high"] + df["low"]) / 2)
    df["middle_price"] = df.get(
        "middle_price",
        (df["inner_high"] + df["inner_low"]) / 2,
    )
    df["middle_price_wick"] = df.get(
        "middle_price_wick",
        (df["high"] + df["low"]) / 2,
    )
    df["up_rod"] = df.get("up_rod", df["high"] - df["inner_high"])
    df["low_rod"] = df.get("low_rod", df["inner_low"] - df["low"])
    df["bb_range"] = df.get("bb_range", np.nan)

    if "RSI" not in df or pd.to_numeric(df["RSI"], errors="coerce").isna().all():
        calculated = win_point.add_rsi(df)
        df["RSI"] = calculated["RSI_calc"]
    else:
        df["RSI"] = pd.to_numeric(df["RSI"], errors="coerce")
    return df


def prepare_s5(df: pd.DataFrame) -> pd.DataFrame:
    # S5 annual caches are large, so normalize this private load frame in place.
    df = _normalize_time(df, copy_frame=False)
    for column in ("open", "close", "high", "low"):
        if column not in df:
            if column == "open" and "close" in df:
                df[column] = df["close"]
            else:
                raise ValueError(f"S5に必要な列がありません: {column}")
        df[column] = pd.to_numeric(df[column], errors="coerce")
    df.drop(columns=["time_jp"], inplace=True)
    return df[["time_jp_dt", "open", "close", "high", "low"]]


def s5_cache_has_no_tick_completion(path: Path) -> bool:
    """Only new caches with auditable S5 completion are reusable."""
    columns = set(pd.read_csv(path, nrows=0).columns)
    required = {
        classOanda.S5_SYNTHETIC_COLUMN,
        classOanda.S5_ELAPSED_COLUMN,
        classOanda.S5_COMPLETION_VERSION_COLUMN,
    }
    return required.issubset(columns)


def _nearest_oanda_open_time(
    timestamp: pd.Timestamp,
    step: pd.Timedelta,
    direction: int,
    *,
    open_offset: int = 0,
) -> pd.Timestamp:
    """Find an OANDA FX timestamp, optionally offset by open-market bars."""
    timestamp = pd.Timestamp(timestamp)
    step = pd.Timedelta(step)
    if step <= pd.Timedelta(0):
        raise ValueError("step must be positive")
    if direction not in (-1, 1):
        raise ValueError("direction must be -1 or 1")
    if not isinstance(open_offset, int) or open_offset < 0:
        raise ValueError("open_offset must be a non-negative integer")
    timestamp = (
        timestamp.ceil(step)
        if direction == 1
        else timestamp.floor(step)
    )

    count = int(pd.Timedelta(days=4) / step) + open_offset + 1
    offsets = pd.timedelta_range(
        start=pd.Timedelta(0),
        periods=count,
        freq=step,
    )
    candidates = pd.DatetimeIndex(timestamp + direction * offsets)
    if candidates.tz is None:
        market_times = candidates.tz_localize("Asia/Tokyo")
    else:
        market_times = candidates.tz_convert("Asia/Tokyo")
    market_open = classOanda._oanda_market_open_mask(market_times)
    open_positions = np.flatnonzero(market_open)
    if open_positions.size <= open_offset:
        raise RuntimeError("OANDA market-open timestamp not found within 4 days")
    return pd.Timestamp(candidates[int(open_positions[open_offset])])


def data_coverage_errors(
    m5: pd.DataFrame,
    s5: pd.DataFrame,
    start: dt.datetime,
    end: dt.datetime,
    horizon_minutes: int,
    h1: pd.DataFrame | None = None,
) -> dict[str, list[str]]:
    """Detect truncated cache edges before event extraction begins.

    OANDA omits S5 rows when no price update occurred.  A short missing edge is
    therefore accepted up to the same causal limit used by the OANDA S5
    completion step.  No leading/trailing price is synthesized here; each
    candidate path is still required to be contiguous by LimitPathInspector.
    """
    errors: dict[str, list[str]] = {"M5": [], "S5": []}
    if h1 is not None:
        errors["H1"] = []
    start_time = pd.Timestamp(start)
    end_time = pd.Timestamp(end)
    if m5.empty:
        errors["M5"].append("empty")
    else:
        m5_times = m5["time_jp_dt"]
        history_rows = int((m5_times < start_time).sum())
        if history_rows < PEAK_HISTORY_BARS:
            errors["M5"].append(
                f"prehistory_rows={history_rows}<{PEAK_HISTORY_BARS}"
            )
        m5_in_period = m5_times.between(
            start_time,
            end_time,
            inclusive="left",
        )
        if not m5_in_period.any():
            errors["M5"].append("no_rows_in_requested_period")
        else:
            expected_m5_last = _nearest_oanda_open_time(
                end_time - pd.Timedelta(nanoseconds=1),
                pd.Timedelta(minutes=5),
                -1,
            )
            actual_m5_last = pd.Timestamp(m5_times.loc[m5_in_period].max())
            if actual_m5_last < expected_m5_last:
                errors["M5"].append(
                    "truncated_end:"
                    f"{actual_m5_last}<{expected_m5_last}"
                )

    if h1 is None:
        pass
    elif h1.empty:
        errors["H1"].append("empty")
    else:
        h1_times = h1["time_jp_dt"]
        history_rows = int((h1_times < start_time).sum())
        if history_rows < H1_HISTORY_BARS:
            errors["H1"].append(
                f"prehistory_rows={history_rows}<{H1_HISTORY_BARS}"
            )
        h1_in_period = h1_times.between(
            start_time,
            end_time,
            inclusive="left",
        )
        if not h1_in_period.any():
            errors["H1"].append("no_rows_in_requested_period")
        else:
            expected_h1_last = _nearest_oanda_open_time(
                end_time - pd.Timedelta(nanoseconds=1),
                pd.Timedelta(hours=1),
                -1,
            )
            actual_h1_last = pd.Timestamp(h1_times.loc[h1_in_period].max())
            if actual_h1_last < expected_h1_last:
                errors["H1"].append(
                    "truncated_end:"
                    f"{actual_h1_last}<{expected_h1_last}"
                )

    if s5.empty:
        errors["S5"].append("empty")
    else:
        required_end = end_time + pd.Timedelta(minutes=horizon_minutes)
        s5_times = s5["time_jp_dt"]
        s5_in_required_period = s5_times.between(
            start_time,
            required_end,
            inclusive="left",
        )
        if not s5_in_required_period.any():
            errors["S5"].append("no_rows_in_required_period")
        else:
            expected_s5_first = _nearest_oanda_open_time(
                start_time,
                pd.Timedelta(seconds=S5_SECONDS),
                1,
            )
            expected_s5_last = _nearest_oanda_open_time(
                required_end - pd.Timedelta(nanoseconds=1),
                pd.Timedelta(seconds=S5_SECONDS),
                -1,
            )
            relevant_s5_times = s5_times.loc[s5_in_required_period]
            actual_s5_first = pd.Timestamp(relevant_s5_times.min())
            actual_s5_last = pd.Timestamp(relevant_s5_times.max())
            s5_edge_tolerance = pd.Timedelta(
                classOanda.S5_NO_TICK_MAX_FILL_GAP
            )
            s5_step = pd.Timedelta(seconds=S5_SECONDS)
            tolerance_open_bars = int(s5_edge_tolerance / s5_step)
            latest_accepted_first = _nearest_oanda_open_time(
                expected_s5_first,
                s5_step,
                1,
                open_offset=tolerance_open_bars,
            )
            if actual_s5_first > latest_accepted_first:
                errors["S5"].append(
                    "truncated_start:"
                    f"{actual_s5_first}>{latest_accepted_first}"
                    f" (market_edge={expected_s5_first}, "
                    f"no_tick_tolerance={s5_edge_tolerance})"
                )
            earliest_accepted_last = _nearest_oanda_open_time(
                expected_s5_last,
                s5_step,
                -1,
                open_offset=tolerance_open_bars,
            )
            if actual_s5_last < earliest_accepted_last:
                errors["S5"].append(
                    "truncated_end:"
                    f"{actual_s5_last}<{earliest_accepted_last}"
                    f" (market_edge={expected_s5_last}, "
                    f"no_tick_tolerance={s5_edge_tolerance})"
                )
    return {frame: values for frame, values in errors.items() if values}


def load_pair_data(
    pair_name: str,
    start: dt.datetime,
    end: dt.datetime,
    existing_only: bool,
    horizon_minutes: int,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Load M5/H1 decision context and the S5 execution path."""
    win_point.PAIR = pair_name
    paths = win_point.cache_paths(start, end)
    requirements = {
        "M5": (
            start - dt.timedelta(hours=max(win_point.H1_HISTORY, 16)),
            end,
        ),
        "H1": (
            start - dt.timedelta(hours=H1_PREHISTORY_CALENDAR_HOURS),
            end,
        ),
        "S5": (start, end + dt.timedelta(minutes=horizon_minutes)),
    }
    data: dict[str, pd.DataFrame] = {}
    missing: list[str] = []
    incompatible: list[str] = []
    for frame in ("M5", "H1", "S5"):
        path = paths[frame]
        if not path.exists():
            missing.append(frame)
            continue
        if frame == "S5" and not s5_cache_has_no_tick_completion(path):
            incompatible.append(frame)
            continue
        usecols = (
            (lambda column: column in {"time_jp", "open", "close", "high", "low"})
            if frame == "S5"
            else None
        )
        data[frame] = pd.read_csv(path, usecols=usecols)

    if (missing or incompatible) and existing_only:
        details = []
        if missing:
            details.append(
                "missing=" + ", ".join(str(paths[name]) for name in missing)
            )
        if incompatible:
            details.append(
                "legacy_without_no_tick_completion="
                + ", ".join(str(paths[name]) for name in incompatible)
            )
        raise FileNotFoundError(
            "Usable cache unavailable: " + "; ".join(details)
        )
    oanda: classOanda.Oanda | None = None

    def fetch_frame(frame: str) -> pd.DataFrame:
        nonlocal oanda
        if oanda is None:
            oanda = classOanda.Oanda(tk.accountIDl, tk.access_tokenl, "live")
        fetch_from, fetch_to = requirements[frame]
        print(f"[FETCH] {pair_name} {frame}: {fetch_from} -> {fetch_to}")
        fetched = win_point.fetch_candles(
            oanda,
            frame,
            fetch_from,
            fetch_to,
        )
        paths[frame].parent.mkdir(parents=True, exist_ok=True)
        fetched.drop(columns="time_jp_dt").to_csv(
            paths[frame],
            index=False,
            encoding="utf-8",
        )
        return fetched.drop(columns="time_jp_dt")

    refresh_frames = list(dict.fromkeys([*missing, *incompatible]))
    if refresh_frames:
        for frame in refresh_frames:
            data[frame] = fetch_frame(frame)
    else:
        print(f"[CACHE] {pair_name}: M5/S5の既存キャッシュを使用")

    m5 = prepare_m5(data.pop("M5"))
    h1 = prepare_m5(data.pop("H1"))
    s5 = prepare_s5(data.pop("S5"))
    coverage_errors = data_coverage_errors(
        m5,
        s5,
        start,
        end,
        horizon_minutes,
        h1=h1,
    )
    if coverage_errors and existing_only:
        details = "; ".join(
            f"{frame}: {', '.join(values)}"
            for frame, values in coverage_errors.items()
        )
        raise ValueError(f"Cached data coverage is incomplete: {details}")
    if coverage_errors:
        print(f"[CACHE REFRESH] {pair_name}: {coverage_errors}")
        for frame in coverage_errors:
            refreshed = fetch_frame(frame)
            if frame == "M5":
                m5 = prepare_m5(refreshed)
            elif frame == "H1":
                h1 = prepare_m5(refreshed)
            else:
                s5 = prepare_s5(refreshed)
        remaining_errors = data_coverage_errors(
            m5,
            s5,
            start,
            end,
            horizon_minutes,
            h1=h1,
        )
        if remaining_errors:
            raise ValueError(
                "Fetched data coverage is incomplete: "
                + "; ".join(
                    f"{frame}: {', '.join(values)}"
                    for frame, values in remaining_errors.items()
                )
            )
    return m5, h1, s5


def target_parameters(
    m5: pd.DataFrame,
    index: int,
    pair: gene.CurrencyPair,
    lookback: int = TP_LOOKBACK,
    multiplier: float = TP_MULTIPLIER,
    rr: float = RR,
) -> dict[str, Any]:
    """Calculate TP/LC from exactly the preceding completed M5 candles."""
    decision_time = pd.Timestamp(m5.iloc[index]["time_jp_dt"])
    completed = m5.iloc[max(0, index - lookback) : index]
    base = {
        "tp_lookback": int(lookback),
        "tp_multiplier": float(multiplier),
        "rr": float(rr),
    }
    if len(completed) != lookback:
        return {
            **base,
            "target_valid": False,
            "target_skip_reason": "insufficient_completed_m5",
        }
    if (completed["time_jp_dt"] >= decision_time).any():
        return {
            **base,
            "target_valid": False,
            "target_skip_reason": "non_past_m5_in_target_window",
        }

    high = pd.to_numeric(completed["high"], errors="coerce")
    low = pd.to_numeric(completed["low"], errors="coerce")
    ranges = (high - low) / pair.pip_value
    if not np.isfinite(ranges.to_numpy(dtype=float)).all():
        return {
            **base,
            "target_valid": False,
            "target_skip_reason": "invalid_m5_range",
        }
    average_range = float(ranges.mean())
    tp_pips = float(average_range * multiplier)
    if not math.isfinite(tp_pips) or tp_pips <= 0:
        return {
            **base,
            "target_valid": False,
            "target_skip_reason": "non_positive_target",
        }
    return {
        **base,
        "target_valid": True,
        "target_skip_reason": None,
        "target_source_first_time": pd.Timestamp(
            completed.iloc[0]["time_jp_dt"]
        ),
        "target_source_last_time": pd.Timestamp(
            completed.iloc[-1]["time_jp_dt"]
        ),
        "recent_m5_avg_range_pips": average_range,
        "recent_m5_median_range_pips": float(ranges.median()),
        "recent_m5_min_range_pips": float(ranges.min()),
        "recent_m5_max_range_pips": float(ranges.max()),
        "tp_pips": tp_pips,
        "lc_pips": float(tp_pips / rr),
    }


def select_ahead_lines(
    peak_direction: int,
    current_price: float,
    upper_lines: list[dict[str, Any]],
    lower_lines: list[dict[str, Any]],
    pair: gene.CurrencyPair,
    profile: Any | None = None,
) -> list[dict[str, Any]]:
    """Keep every raw line strictly ahead in the newest peak direction."""
    if int(peak_direction) not in (-1, 1):
        raise ValueError("peak_direction must be -1 or 1")

    # この検証での count2 は、次の抵抗ポイントを探すための起点。
    # 上向き count2:
    #   下落 -> 安値から少し上昇 -> 上側の抵抗線候補へさらに上昇
    #   -> その抵抗線で SELL -> 下へ折り返して SELL の TP
    # 下向き count2 はこの逆で、下側の抵抗線候補に BUY を置く。
    # つまり注文方向は count2 の進行方向と逆になる。
    # ここでいう「次の count2」は予測したい次の折り返し地点の意味であり、
    # 候補ライン上で実際に二つ目の count2 が成立することは約定条件ではない。
    side = "upper" if peak_direction == 1 else "lower"
    trade_direction = -int(peak_direction)
    source = upper_lines if side == "upper" else lower_lines
    selected: list[dict[str, Any]] = []
    for line in source:
        try:
            raw_line_price = float(line["median_price"])
        except (KeyError, TypeError, ValueError):
            continue
        line_price = pair.round_price(raw_line_price)
        distance_pips = (
            (line_price - float(current_price))
            * int(peak_direction)
            / pair.pip_value
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
        selected.append(
            {
                "line": line,
                "line_side": side,
                "trade_direction": trade_direction,
                "trade_side": "BUY" if trade_direction == 1 else "SELL",
                "raw_line_price": raw_line_price,
                "line_price": line_price,
                "distance_pips": float(distance_pips),
                "current_policy_reversal_target": current_target,
            }
        )
    selected.sort(key=lambda item: (item["distance_pips"], item["line_price"]))
    for rank, item in enumerate(selected, start=1):
        item["candidate_rank"] = rank
        item["distance_rank"] = rank
    return selected


def _decision_snapshot(
    completed: pd.DataFrame,
    decision_time: pd.Timestamp,
    current_price: float,
) -> pd.DataFrame:
    history_desc = completed.iloc[::-1].reset_index(drop=True)
    dummy = history_desc.iloc[0].copy()
    dummy["time_jp"] = decision_time.strftime(TIME_FORMAT)
    dummy["time_jp_dt"] = decision_time
    for column in (
        "open",
        "close",
        "high",
        "low",
        "inner_high",
        "inner_low",
        "mid_outer",
        "middle_price",
        "middle_price_wick",
    ):
        if column in dummy:
            dummy[column] = current_price
    for column in (
        "body",
        "body_abs",
        "moves",
        "highlow",
        "up_rod",
        "low_rod",
    ):
        if column in dummy:
            dummy[column] = 0.0
    if "direction" in dummy:
        dummy["direction"] = 0
    return pd.concat(
        [pd.DataFrame([dummy]), history_desc],
        ignore_index=True,
    )


def rebuild_candidates_at(
    m5: pd.DataFrame,
    index: int,
    pair_name: str,
    h1: pd.DataFrame | None = None,
    h1_stair_cache: dict[pd.Timestamp, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Recreate peak and line state from rows strictly before ``index``."""
    pair = gene.currency_pair(pair_name)
    decision_time = pd.Timestamp(m5.iloc[index]["time_jp_dt"])
    completed = m5.iloc[max(0, index - PEAK_HISTORY_BARS) : index].copy()
    if len(completed) < LINE_HISTORY_BARS + 1:
        raise ValueError("insufficient_m5_for_line_rebuild")
    if (completed["time_jp_dt"] >= decision_time).any():
        raise ValueError("future_m5_in_line_snapshot")
    current_price = float(completed.iloc[-1]["close"])
    snapshot = _decision_snapshot(completed, decision_time, current_price)

    with contextlib.redirect_stdout(io.StringIO()):
        peaks = PeaksClass(snapshot, "M5", current_price, pair=pair)
    if not peaks.peaks_original:
        raise ValueError("no_peak")
    newest_peak = peaks.peaks_original[0]
    if int(newest_peak.get("count", 0)) != 2:
        raise ValueError(
            "count2_prefilter_mismatch:"
            + str(newest_peak.get("count"))
        )

    if h1 is None:
        h1_snapshot = snapshot
        h1_peaks = peaks
        h1_cache_key = None
        h1_stair_context = None
    else:
        completed_h1_end = int(
            h1["time_jp_dt"].searchsorted(
                decision_time - pd.Timedelta(hours=1),
                side="right",
            )
        )
        completed_h1 = h1.iloc[
            max(0, completed_h1_end - H1_HISTORY_BARS) : completed_h1_end
        ].copy()
        if len(completed_h1) < 60:
            raise ValueError("insufficient_h1_for_stair_rebuild")
        if (
            completed_h1["time_jp_dt"] + pd.Timedelta(hours=1)
            > decision_time
        ).any():
            raise ValueError("future_h1_in_stair_snapshot")
        h1_cache_key = pd.Timestamp(
            completed_h1.iloc[-1]["time_jp_dt"]
        )
        h1_stair_context = (
            h1_stair_cache.get(h1_cache_key)
            if h1_stair_cache is not None
            else None
        )
        if h1_stair_context is None:
            h1_snapshot = _decision_snapshot(
                completed_h1,
                decision_time,
                current_price,
            )
            with contextlib.redirect_stdout(io.StringIO()):
                h1_peaks = PeaksClass(
                    h1_snapshot,
                    "H1",
                    current_price,
                    pair=pair,
                )
        else:
            # M5 line rebuilding does not read H1 state.  These placeholders
            # keep the analysis namespace compatible while the causal H1
            # stair result is reused for the same latest completed H1 candle.
            h1_snapshot = snapshot
            h1_peaks = peaks

    analysis = SimpleNamespace(
        pair=pair_name,
        current_price=current_price,
        d5_df_r=snapshot,
        peaks_class=peaks,
        candle_meta_class=None,
        h1_df_r=h1_snapshot,
        peaks_class_hour=h1_peaks,
        candle_meta_class_hour=None,
        d30_df_r=snapshot,
        peaks_class_m30=peaks,
        candle_meta_class_m30=None,
    )
    with contextlib.redirect_stdout(io.StringIO()):
        line_class = LineStrengthCal(
            analysis,
            "m5",
            LINE_HISTORY_BARS,
        )
    profile = line_strategy_profile(pair_name)
    stair_context = detect_m5_stair_trend(
        peaks.peaks_original,
        pair,
        snapshot.iloc[1:],
        min_impulse_foot_count=getattr(
            profile,
            "predict_reversal_m5_stair_min_impulse_foot_count",
            3,
        ),
        min_latest_impulse_foot_count=getattr(
            profile,
            "predict_reversal_m5_stair_min_latest_impulse_foot_count",
            2,
        ),
        max_pullback_foot_count=getattr(
            profile,
            "predict_reversal_m5_stair_max_pullback_foot_count",
            3,
        ),
        min_impulse_pips=getattr(
            profile,
            "predict_reversal_m5_stair_min_impulse_pips",
            3.0,
        ),
        volatility_lookback=getattr(
            profile,
            "predict_reversal_m5_stair_volatility_lookback",
            12,
        ),
        volatility_multiplier=getattr(
            profile,
            "predict_reversal_m5_stair_volatility_multiplier",
            1.2,
        ),
        max_pullback_ratio=getattr(
            profile,
            "predict_reversal_m5_stair_max_pullback_ratio",
            0.65,
        ),
        min_break_pips=getattr(
            profile,
            "predict_reversal_m5_stair_min_break_pips",
            0.5,
        ),
        min_dominance_ratio=getattr(
            profile,
            "predict_reversal_m5_stair_min_dominance_ratio",
            1.5,
        ),
    )
    stair_context["profile_enabled"] = bool(
        getattr(profile, "predict_reversal_m5_stair_enabled", False)
    )
    if h1_stair_context is None:
        h1_stair_context = detect_h1_stair_trend(
            h1_peaks.peaks_original,
            pair,
            h1_snapshot.iloc[1:],
            min_impulse_foot_count=getattr(
                profile,
                "predict_reversal_h1_stair_min_impulse_foot_count",
                3,
            ),
            min_latest_impulse_foot_count=getattr(
                profile,
                "predict_reversal_h1_stair_min_latest_impulse_foot_count",
                2,
            ),
            max_pullback_foot_count=getattr(
                profile,
                "predict_reversal_h1_stair_max_pullback_foot_count",
                3,
            ),
            min_impulse_pips=getattr(
                profile,
                "predict_reversal_h1_stair_min_impulse_pips",
                10.0,
            ),
            volatility_lookback=getattr(
                profile,
                "predict_reversal_h1_stair_volatility_lookback",
                12,
            ),
            volatility_multiplier=getattr(
                profile,
                "predict_reversal_h1_stair_volatility_multiplier",
                1.2,
            ),
            max_pullback_ratio=getattr(
                profile,
                "predict_reversal_h1_stair_max_pullback_ratio",
                0.65,
            ),
            min_break_pips=getattr(
                profile,
                "predict_reversal_h1_stair_min_break_pips",
                3.0,
            ),
            min_dominance_ratio=getattr(
                profile,
                "predict_reversal_h1_stair_min_dominance_ratio",
                1.5,
            ),
        )
        h1_stair_context["profile_enabled"] = bool(
            getattr(profile, "predict_reversal_h1_stair_enabled", False)
        )
        if h1_stair_cache is not None and h1_cache_key is not None:
            h1_stair_cache[h1_cache_key] = h1_stair_context
    peak_direction = int(newest_peak["direction"])
    candidates = select_ahead_lines(
        peak_direction,
        current_price,
        line_class.upper_lines,
        line_class.lower_lines,
        pair,
        profile,
    )
    for candidate in candidates:
        candidate["m5_stair_context"] = stair_context
        candidate["h1_stair_context"] = h1_stair_context
    completed_desc = completed.sort_values(
        "time_jp_dt",
        ascending=False,
    ).reset_index(drop=True)
    rsi_info = {
        "rsi_1": (
            completed_desc.iloc[0].get("RSI")
            if len(completed_desc) >= 1
            else None
        ),
        "rsi_2": (
            completed_desc.iloc[1].get("RSI")
            if len(completed_desc) >= 2
            else None
        ),
        "rsi_3": (
            completed_desc.iloc[2].get("RSI")
            if len(completed_desc) >= 3
            else None
        ),
    }
    return {
        "decision_time": decision_time,
        "current_price": current_price,
        "newest_peak": newest_peak,
        "m5_peaks": peaks.peaks_original,
        "peak_direction": peak_direction,
        "completed_history": completed,
        "candidates": candidates,
        "profile": profile,
        "rsi_info": rsi_info,
        "stair_context": stair_context,
        "h1_stair_context": h1_stair_context,
    }


def _parse_time(value: Any) -> pd.Timestamp:
    if value is None or value == "":
        return pd.NaT
    return pd.to_datetime(value, format=TIME_FORMAT, errors="coerce")


def _episode_summary(
    mask: pd.Series,
    times: pd.Series,
) -> tuple[int, pd.Timestamp]:
    selected = np.flatnonzero(mask.to_numpy(dtype=bool))
    if not selected.size:
        return 0, pd.NaT
    episode_count = 0
    previous_index: int | None = None
    previous_time: pd.Timestamp | None = None
    for raw_index in selected:
        index = int(raw_index)
        timestamp = pd.Timestamp(times.iloc[index])
        new_episode = (
            previous_index is None
            or index != previous_index + 1
            or timestamp - previous_time > pd.Timedelta(minutes=5)
        )
        if new_episode:
            episode_count += 1
        previous_index = index
        previous_time = timestamp
    return episode_count, pd.Timestamp(times.iloc[selected[-1]])


def line_touch_features(
    completed_history: pd.DataFrame,
    line: dict[str, Any],
    decision_time: pd.Timestamp,
    pair: gene.CurrencyPair,
    tolerance_pips: float = RETOUCH_TOLERANCE_PIPS,
) -> dict[str, Any]:
    """Separate source-peak touches from later candle retouches."""
    source_last = _parse_time(
        line.get("newest_time") or line.get("line_latest_touch_time")
    )
    source_first = _parse_time(line.get("oldest_time"))
    source_count = int(line.get("count") or len(line.get("prices_info", [])))
    source_minutes = (
        float((decision_time - source_last).total_seconds() / 60)
        if not pd.isna(source_last)
        else np.nan
    )
    line_age_minutes = (
        float((decision_time - source_first).total_seconds() / 60)
        if not pd.isna(source_first)
        else np.nan
    )
    result = {
        "source_touch_exists": bool(source_count > 0),
        "source_touch_count": source_count,
        "source_first_touch_time": source_first,
        "source_last_touch_time": source_last,
        "minutes_since_source_touch": source_minutes,
        "line_age_minutes": line_age_minutes,
        "retouch_tolerance_pips": float(tolerance_pips),
        "prior_retouch_exists": False,
        "prior_retouch_count": 0,
        "prior_retouch_last_time": pd.NaT,
        "minutes_since_prior_retouch": np.nan,
        "prior_body_retouch_exists": False,
        "prior_body_retouch_count": 0,
        "prior_body_retouch_last_time": pd.NaT,
        "minutes_since_prior_body_retouch": np.nan,
    }
    result.update(
        predict_reversal_last_reach_context(
            completed_history,
            line,
            decision_time,
            pair,
            tolerance_pips,
        )
    )
    if pd.isna(source_last):
        return result

    history = completed_history[
        (completed_history["time_jp_dt"] > source_last)
        & (completed_history["time_jp_dt"] < decision_time)
    ].copy()
    if history.empty:
        return result

    line_price = float(line["median_price"])
    tolerance = pair.pips_to_price(tolerance_pips)
    zone_low = line_price - tolerance
    zone_high = line_price + tolerance
    wick_touch = (
        pd.to_numeric(history["high"], errors="coerce").ge(zone_low)
        & pd.to_numeric(history["low"], errors="coerce").le(zone_high)
    )
    body_touch = (
        pd.to_numeric(history["inner_high"], errors="coerce").ge(zone_low)
        & pd.to_numeric(history["inner_low"], errors="coerce").le(zone_high)
    )
    wick_count, wick_last = _episode_summary(
        wick_touch,
        history["time_jp_dt"],
    )
    body_count, body_last = _episode_summary(
        body_touch,
        history["time_jp_dt"],
    )
    result.update(
        {
            "prior_retouch_exists": bool(wick_count),
            "prior_retouch_count": wick_count,
            "prior_retouch_last_time": wick_last,
            "minutes_since_prior_retouch": (
                float((decision_time - wick_last).total_seconds() / 60)
                if not pd.isna(wick_last)
                else np.nan
            ),
            "prior_body_retouch_exists": bool(body_count),
            "prior_body_retouch_count": body_count,
            "prior_body_retouch_last_time": body_last,
            "minutes_since_prior_body_retouch": (
                float((decision_time - body_last).total_seconds() / 60)
                if not pd.isna(body_last)
                else np.nan
            ),
        }
    )
    return result


class LimitPathInspector:
    """Spread-aware S5 path inspection for a pending LIMIT order."""

    def __init__(self, s5: pd.DataFrame, pair: gene.CurrencyPair):
        self.pair = pair
        self.times = s5["time_jp_dt"].to_numpy(
            dtype="datetime64[ns]",
            copy=False,
        )
        self.opens = pd.to_numeric(s5["open"], errors="coerce").to_numpy(
            dtype=float,
            copy=False,
        )
        self.closes = pd.to_numeric(s5["close"], errors="coerce").to_numpy(
            dtype=float,
            copy=False,
        )
        self.highs = pd.to_numeric(s5["high"], errors="coerce").to_numpy(
            dtype=float,
            copy=False,
        )
        self.lows = pd.to_numeric(s5["low"], errors="coerce").to_numpy(
            dtype=float,
            copy=False,
        )

    @staticmethod
    def _base() -> dict[str, Any]:
        return {
            "has_s5_path": False,
            "path_skip_reason": None,
            "pending_path_complete": False,
            "position_path_complete_to_outcome": False,
            "has_full_horizon": False,
            "filled": False,
            "fill_time": pd.NaT,
            "fill_delay_seconds": np.nan,
            "fill_at_bar_open": False,
            "fill_bar_tp_ambiguous": False,
            "candidate_result": None,
            "trade_result": None,
            "tp_hit": False,
            "lc_hit": False,
            "both_hit_same_s5": False,
            "exit_time": pd.NaT,
            "trade_result_pips": np.nan,
            "result_r": np.nan,
            "max_favorable_pips_before_exit": np.nan,
            "max_adverse_pips_before_exit": np.nan,
            "pending_s5_rows": 0,
            "position_s5_rows": 0,
        }

    @staticmethod
    @functools.lru_cache(maxsize=4096)
    def _is_expected_market_closed_gap(
        previous_time: pd.Timestamp,
        next_time: pd.Timestamp,
    ) -> bool:
        """Accept a gap only when every missing S5 is a known market closure."""
        previous_jst = pd.Timestamp(previous_time)
        next_jst = pd.Timestamp(next_time)
        if previous_jst.tzinfo is None:
            previous_jst = previous_jst.tz_localize("Asia/Tokyo")
        else:
            previous_jst = previous_jst.tz_convert("Asia/Tokyo")
        if next_jst.tzinfo is None:
            next_jst = next_jst.tz_localize("Asia/Tokyo")
        else:
            next_jst = next_jst.tz_convert("Asia/Tokyo")
        gap = next_jst - previous_jst
        step = pd.Timedelta(seconds=S5_SECONDS)
        if gap <= step or gap > pd.Timedelta(days=4):
            return False
        missing_times = pd.date_range(
            start=previous_jst + step,
            end=next_jst - step,
            freq=step,
        )
        if not len(missing_times):
            return False
        return not bool(
            classOanda._oanda_market_open_mask(missing_times).any()
        )

    @staticmethod
    def _is_contiguous(
        times: np.ndarray,
        expected_start: pd.Timestamp,
        expected_end_exclusive: pd.Timestamp | None = None,
    ) -> bool:
        """Require an exact S5 sequence; unknown gaps are never assumed safe."""
        if not len(times):
            return False
        expected_start = pd.Timestamp(expected_start)
        if pd.Timestamp(times[0]) != expected_start:
            return False
        if len(times) > 1:
            gaps = np.diff(times)
            unexpected = np.flatnonzero(
                gaps != np.timedelta64(S5_SECONDS, "s")
            )
            for index in unexpected:
                previous = times[int(index)]
                following = times[int(index) + 1]
                if LimitPathInspector._is_expected_market_closed_gap(
                    pd.Timestamp(previous),
                    pd.Timestamp(following),
                ):
                    continue
                return False
        if expected_end_exclusive is not None:
            expected_end_exclusive = pd.Timestamp(expected_end_exclusive)
            actual_end = pd.Timestamp(times[-1]) + pd.Timedelta(
                seconds=S5_SECONDS
            )
            if actual_end != expected_end_exclusive:
                return False
        return True

    def inspect(
        self,
        decision_time: pd.Timestamp,
        expiry_time: pd.Timestamp,
        direction: int,
        line_price: float,
        tp_pips: float,
        lc_pips: float,
        horizon_minutes: int = HORIZON_MINUTES,
        spread_pips: float = SPREAD_PIPS,
    ) -> dict[str, Any]:
        base = self._base()
        decision_time = pd.Timestamp(decision_time)
        expiry_time = pd.Timestamp(expiry_time)
        if expiry_time <= decision_time:
            return {
                **base,
                "path_skip_reason": "invalid_pending_interval",
                "candidate_result": "invalid_pending_interval",
            }
        if int(direction) not in (-1, 1):
            raise ValueError("direction must be -1 or 1")

        start_i = int(
            np.searchsorted(
                self.times,
                np.datetime64(decision_time, "ns"),
                side="left",
            )
        )
        expiry_i = int(
            np.searchsorted(
                self.times,
                np.datetime64(expiry_time, "ns"),
                side="left",
            )
        )
        if start_i >= len(self.times) or start_i >= expiry_i:
            return {
                **base,
                "path_skip_reason": "no_s5_during_pending",
                "candidate_result": "incomplete_pending",
            }
        pending_times = self.times[start_i:expiry_i]

        half_spread = self.pair.pips_to_price(spread_pips / 2)
        pending_high = self.highs[start_i:expiry_i]
        pending_low = self.lows[start_i:expiry_i]
        if direction == 1:
            fill_touch = np.isfinite(pending_low) & (
                pending_low <= line_price - half_spread
            )
        else:
            fill_touch = np.isfinite(pending_high) & (
                pending_high >= line_price + half_spread
            )
        reached = np.flatnonzero(fill_touch)
        if not reached.size:
            pending_complete = self._is_contiguous(
                pending_times,
                decision_time,
                expiry_time,
            )
            if not pending_complete:
                return {
                    **base,
                    "path_skip_reason": "incomplete_pending",
                    "candidate_result": "incomplete_pending",
                    "pending_s5_rows": len(pending_times),
                    "pending_path_complete": False,
                }
            return {
                **base,
                "has_s5_path": True,
                "pending_path_complete": True,
                "candidate_result": "not_filled",
                "trade_result": "not_filled",
                "pending_s5_rows": len(pending_times),
            }

        fill_offset = int(reached[0])
        fill_i = start_i + fill_offset
        fill_time = pd.Timestamp(self.times[fill_i])
        pending_complete = self._is_contiguous(
            pending_times[: fill_offset + 1],
            decision_time,
        )
        if not pending_complete:
            return {
                **base,
                "path_skip_reason": "incomplete_pending_before_fill",
                "candidate_result": "incomplete_pending",
                "pending_s5_rows": fill_offset + 1,
                "pending_path_complete": False,
            }
        open_mid = float(self.opens[fill_i])
        fill_at_open = (
            open_mid + half_spread <= line_price
            if direction == 1
            else open_mid - half_spread >= line_price
        )
        horizon_end = fill_time + pd.Timedelta(minutes=horizon_minutes)
        end_i = int(
            np.searchsorted(
                self.times,
                np.datetime64(horizon_end, "ns"),
                side="left",
            )
        )
        path_times = self.times[fill_i:end_i]
        high = self.highs[fill_i:end_i]
        low = self.lows[fill_i:end_i]
        close = self.closes[fill_i:end_i]
        if not len(path_times):
            return {
                **base,
                "filled": True,
                "fill_time": fill_time,
                "fill_delay_seconds": float(
                    (fill_time - decision_time).total_seconds()
                ),
                "fill_at_bar_open": bool(fill_at_open),
                "path_skip_reason": "no_s5_after_fill",
                "candidate_result": "incomplete_horizon",
                "pending_s5_rows": fill_offset + 1,
            }

        actual_entry = float(line_price)
        tp_price = actual_entry + direction * self.pair.pips_to_price(tp_pips)
        lc_price = actual_entry - direction * self.pair.pips_to_price(lc_pips)
        if direction == 1:
            favorable_quote = high - half_spread
            adverse_quote = low - half_spread
            close_quote = close - half_spread
            favorable_pips = (
                favorable_quote - actual_entry
            ) / self.pair.pip_value
            adverse_pips = (
                adverse_quote - actual_entry
            ) / self.pair.pip_value
            tp_touch = favorable_quote >= tp_price
            lc_touch = adverse_quote <= lc_price
            fill_close_confirms_tp = (
                fill_at_open or close_quote[0] >= tp_price
            )
        else:
            favorable_quote = low + half_spread
            adverse_quote = high + half_spread
            close_quote = close + half_spread
            favorable_pips = (
                actual_entry - favorable_quote
            ) / self.pair.pip_value
            adverse_pips = (
                actual_entry - adverse_quote
            ) / self.pair.pip_value
            tp_touch = favorable_quote <= tp_price
            lc_touch = adverse_quote >= lc_price
            fill_close_confirms_tp = (
                fill_at_open or close_quote[0] <= tp_price
            )

        metric_favorable_pips = favorable_pips.copy()
        if not fill_at_open:
            close_progress_pips = float(
                direction
                * (float(close_quote[0]) - actual_entry)
                / self.pair.pip_value
            )
            metric_favorable_pips[0] = max(0.0, close_progress_pips)

        fill_bar_ambiguous = bool(
            tp_touch[0] and not lc_touch[0] and not fill_close_confirms_tp
        )
        hit_i: int | None = None
        if lc_touch[0] or (tp_touch[0] and fill_close_confirms_tp):
            hit_i = 0
        elif len(path_times) > 1:
            later_reached = np.flatnonzero(tp_touch[1:] | lc_touch[1:])
            if later_reached.size:
                hit_i = int(later_reached[0]) + 1

        coverage_rows = hit_i + 1 if hit_i is not None else len(path_times)
        path_complete_to_outcome = self._is_contiguous(
            path_times[:coverage_rows],
            fill_time,
            horizon_end if hit_i is None else None,
        )
        has_full_horizon = bool(
            hit_i is None and path_complete_to_outcome
        )
        common = {
            **base,
            "has_s5_path": True,
            "pending_path_complete": bool(pending_complete),
            "filled": True,
            "fill_time": fill_time,
            "fill_delay_seconds": float(
                (fill_time - decision_time).total_seconds()
            ),
            "fill_at_bar_open": bool(fill_at_open),
            "fill_bar_tp_ambiguous": fill_bar_ambiguous,
            "actual_entry_price": actual_entry,
            "tp_price": tp_price,
            "lc_price": lc_price,
            "position_path_complete_to_outcome": bool(
                path_complete_to_outcome
            ),
            "has_full_horizon": bool(has_full_horizon),
            "pending_s5_rows": fill_offset + 1,
            "position_s5_rows": len(path_times),
        }

        if not path_complete_to_outcome:
            return {
                **common,
                "path_skip_reason": "incomplete_horizon",
                "candidate_result": "incomplete_horizon",
                "trade_result": "incomplete_horizon",
                "max_favorable_pips_before_exit": float(
                    np.nanmax(metric_favorable_pips)
                ),
                "max_adverse_pips_before_exit": float(
                    np.nanmin(adverse_pips)
                ),
            }

        both_same_s5 = bool(
            hit_i is not None and tp_touch[hit_i] and lc_touch[hit_i]
        )
        if hit_i is None:
            exit_i = len(path_times) - 1
            result_name = "timeout"
            result_pips = float(
                direction
                * (float(close_quote[exit_i]) - actual_entry)
                / self.pair.pip_value
            )
            actual_exit = float(close_quote[exit_i])
            tp_hit = False
            lc_hit = False
        elif lc_touch[hit_i]:
            exit_i = hit_i
            result_name = (
                "both_same_s5_lc_assumed" if both_same_s5 else "lc"
            )
            result_pips = -float(lc_pips)
            actual_exit = float(lc_price)
            tp_hit = False
            lc_hit = True
        else:
            exit_i = hit_i
            result_name = "tp"
            result_pips = float(tp_pips)
            actual_exit = float(tp_price)
            tp_hit = True
            lc_hit = False

        exit_time = pd.Timestamp(path_times[exit_i])
        before_exit = slice(0, exit_i + 1)
        return {
            **common,
            "candidate_result": result_name,
            "trade_result": result_name,
            "tp_hit": tp_hit,
            "lc_hit": lc_hit,
            "both_hit_same_s5": both_same_s5,
            "exit_time": exit_time,
            "actual_exit_price": actual_exit,
            "trade_result_pips": result_pips,
            "result_r": float(result_pips / lc_pips),
            "max_favorable_pips_before_exit": float(
                np.nanmax(metric_favorable_pips[before_exit])
            ),
            "max_adverse_pips_before_exit": float(
                np.nanmin(adverse_pips[before_exit])
            ),
        }


def _line_columns(line: dict[str, Any]) -> dict[str, Any]:
    dirs = line.get("dirs_grouped") or []
    return {
        "line_total_strength": line.get("total_strength"),
        "line_count": line.get("count"),
        "line_average_strength": line.get("ave_strength"),
        "line_core_price": line.get("core_median_price"),
        "line_core_count": line.get("core_count"),
        "line_core_total_strength": line.get("core_total_strength"),
        "line_newest_source_time": line.get("newest_time"),
        "line_oldest_source_time": line.get("oldest_time"),
        "line_source_directions": "|".join(str(value) for value in dirs),
        "line_is_flipped": line.get("is_flipped_line"),
        "line_origin_role": line.get("line_origin_role"),
        "line_current_role": line.get("line_current_role"),
        "line_history_is_flipped": line.get("line_history_is_flipped"),
        "line_flip_count": line.get("line_flip_count"),
        "line_latest_flip_time": line.get("line_latest_flip_time"),
        "line_latest_touch_time": line.get("line_latest_touch_time"),
    }


def _peak_columns(peak: dict[str, Any], pair: gene.CurrencyPair) -> dict[str, Any]:
    return {
        "peak_count": peak.get("count"),
        "peak_direction": peak.get("direction"),
        "peak_latest_time": peak.get("latest_time_jp"),
        "peak_oldest_time": peak.get("oldest_time_jp"),
        "peak_price": peak.get("peak"),
        "peak_body_price": peak.get("latest_body_peak_price"),
        "peak_strength": peak.get("peak_strength"),
        "peak_gap_pips": (
            float(peak.get("gap", np.nan)) / pair.pip_value
            if peak.get("gap") is not None
            else np.nan
        ),
    }


STAIR_SEQUENCE_FIELDS = (
    "direction_sequence",
    "foot_count_sequence",
    "distance_pips_sequence",
    "impulse_foot_count_sequence",
    "pullback_foot_count_sequence",
    "impulse_distance_pips_sequence",
    "pullback_distance_pips_sequence",
    "pullback_ratio_sequence",
    "impulse_break_pips_sequence",
    "structure_progress_pips_sequence",
    "candidate_failed_conditions",
    "confirmed_failed_conditions",
)

STAIR_SCALAR_FIELDS = (
    "profile_enabled",
    "state",
    "direction",
    "observed_direction",
    "confirmed",
    "candidate_passed",
    "confirmed_passed",
    "analysis_leg_count",
    "detected_leg_count",
    "reason",
    "impulse_distance_pips",
    "pullback_distance_pips",
    "dominance_ratio",
    "required_impulse_pips",
    "median_range_pips",
    "median_m5_range_pips",
    "median_h1_range_pips",
    "first_impulse_foot_count",
    "first_impulse_pips",
    "first_pullback_foot_count",
    "first_pullback_pips",
    "first_pullback_ratio",
    "first_pullback_foot_ratio",
    "first_impulse_pips_per_foot",
    "first_pullback_pips_per_foot",
    "first_impulse_required_ratio",
    "second_impulse_foot_count",
    "second_impulse_pips",
    "second_pullback_foot_count",
    "second_pullback_pips",
    "second_pullback_ratio",
    "second_pullback_foot_ratio",
    "second_impulse_pips_per_foot",
    "second_pullback_pips_per_foot",
    "second_impulse_required_ratio",
    "third_impulse_foot_count",
    "third_impulse_pips",
    "third_impulse_pips_per_foot",
    "third_impulse_required_ratio",
    "net_progress_pips",
    "second_impulse_break_pips",
    "third_impulse_break_pips",
    "first_structure_progress_pips",
    "second_structure_progress_pips",
    "threshold_min_impulse_foot_count",
    "threshold_min_latest_impulse_foot_count",
    "threshold_max_pullback_foot_count",
    "threshold_min_impulse_pips",
    "threshold_volatility_lookback",
    "threshold_volatility_multiplier",
    "threshold_max_pullback_ratio",
    "threshold_min_break_pips",
    "threshold_min_dominance_ratio",
)


def stair_analysis_columns(
    context: dict[str, Any],
    peak_direction: int,
    prefix: str = "m5_stair",
) -> dict[str, Any]:
    """Flatten decision-time stair evidence for validation CSVs."""
    row = {
        prefix + "_" + field: context.get(field)
        for field in STAIR_SCALAR_FIELDS
    }
    for field in STAIR_SEQUENCE_FIELDS:
        values = context.get(field) or []
        row[prefix + "_" + field] = "|".join(
            str(value) for value in values
        )
    detected = context.get("state") in (
        "UP_CANDIDATE",
        "UP_CONFIRMED",
        "DOWN_CANDIDATE",
        "DOWN_CONFIRMED",
    )
    row[prefix + "_detected"] = detected
    row[prefix + "_would_block_predict_reversal"] = bool(
        detected
        and int(context.get("direction") or 0) == int(peak_direction)
    )
    for name, passed in (context.get("criteria") or {}).items():
        row[prefix + "_criterion_" + name] = passed
    return row


def _event_id(pair_name: str, decision_time: pd.Timestamp) -> str:
    return f"{pair_name}_{decision_time:%Y%m%d%H%M%S}"


def _distance_bin(values: pd.Series) -> pd.Series:
    return pd.cut(
        pd.to_numeric(values, errors="coerce"),
        [-np.inf, 3, 5, 8, 12, 20, 30, 50, np.inf],
        labels=["<3", "3-4", "5-7", "8-11", "12-19", "20-29", "30-49", "50+"],
        right=False,
    )


def make_ranking(
    candidates: pd.DataFrame,
    min_group_size: int,
) -> pd.DataFrame:
    if candidates.empty:
        return pd.DataFrame()
    work = candidates.copy()
    work["distance_bin"] = _distance_bin(work["distance_pips"])
    work["completed_trade"] = work["candidate_result"].isin(
        ["tp", "lc", "both_same_s5_lc_assumed", "timeout"]
    )
    work["is_win"] = work["candidate_result"].eq("tp")
    work["is_loss"] = work["candidate_result"].isin(
        ["lc", "both_same_s5_lc_assumed"]
    )
    work["is_timeout"] = work["candidate_result"].eq("timeout")
    dimensions = [
        ("all", []),
        ("candidate_rank", ["candidate_rank"]),
        ("predict_candidate_rank", ["predict_candidate_rank"]),
        ("trade_side", ["trade_side"]),
        ("distance", ["distance_bin"]),
        ("current_policy_target", ["current_policy_reversal_target"]),
        ("prior_retouch", ["prior_retouch_exists"]),
        ("rank_x_retouch", ["candidate_rank", "prior_retouch_exists"]),
        ("side_x_distance", ["trade_side", "distance_bin"]),
    ]
    summaries: list[dict[str, Any]] = []
    for group_name, columns in dimensions:
        grouped = [((), work)] if not columns else work.groupby(
            columns,
            dropna=False,
            observed=True,
        )
        for keys, group in grouped:
            if len(group) < min_group_size and group_name != "all":
                continue
            if not isinstance(keys, tuple):
                keys = (keys,)
            completed = group[group["completed_trade"]]
            row: dict[str, Any] = {
                "group_type": group_name,
                "candidate_rows": len(group),
                "event_count": group["event_id"].nunique(),
                "filled_count": int(group["filled"].fillna(False).sum()),
                "completed_trade_count": len(completed),
                "tp_count": int(group["is_win"].sum()),
                "lc_count": int(group["is_loss"].sum()),
                "timeout_count": int(group["is_timeout"].sum()),
                "fill_rate": float(group["filled"].fillna(False).mean()),
                "win_rate_completed": (
                    float(completed["is_win"].mean())
                    if len(completed)
                    else np.nan
                ),
                "mean_result_pips": (
                    float(
                        pd.to_numeric(
                            completed["trade_result_pips"],
                            errors="coerce",
                        ).mean()
                    )
                    if len(completed)
                    else np.nan
                ),
                "mean_result_r": (
                    float(
                        pd.to_numeric(
                            completed["result_r"],
                            errors="coerce",
                        ).mean()
                    )
                    if len(completed)
                    else np.nan
                ),
            }
            for column, key in zip(columns, keys):
                row[column] = key
            summaries.append(row)
    return pd.DataFrame(summaries)


def make_stair_analysis(
    candidates: pd.DataFrame,
    min_group_size: int,
) -> pd.DataFrame:
    """Summarize one selected PredictReversal candidate per count2 event."""
    if candidates.empty or "current_policy_predict_selected" not in candidates:
        return pd.DataFrame()
    work = candidates[
        candidates["current_policy_predict_selected"].fillna(False)
    ].copy()
    if work.empty:
        return pd.DataFrame()

    ratio_edges = [-np.inf, 0.25, 0.40, 0.55, 0.65, 0.80, 1.0, np.inf]
    ratio_labels = ["<0.25", "0.25-0.39", "0.40-0.54", "0.55-0.64", "0.65-0.79", "0.80-0.99", "1.00+"]
    dominance_edges = [-np.inf, 1.0, 1.25, 1.5, 2.0, 3.0, np.inf]
    dominance_labels = ["<1.00", "1.00-1.24", "1.25-1.49", "1.50-1.99", "2.00-2.99", "3.00+"]
    progress_edges = [-np.inf, 0.0, 0.5, 1.0, 2.0, 3.0, 5.0, np.inf]
    progress_labels = ["<0", "0-0.49", "0.50-0.99", "1.00-1.99", "2.00-2.99", "3.00-4.99", "5.00+"]
    pace_edges = [-np.inf, 1.0, 2.0, 3.0, 4.0, 5.0, 8.0, np.inf]
    pace_labels = ["<1", "1-1.99", "2-2.99", "3-3.99", "4-4.99", "5-7.99", "8+"]

    for ordinal in ("first", "second"):
        column = f"m5_stair_{ordinal}_pullback_ratio"
        work[column + "_bin"] = pd.cut(
            pd.to_numeric(work.get(column), errors="coerce"),
            ratio_edges,
            labels=ratio_labels,
            right=False,
        )
        foot_ratio_column = f"m5_stair_{ordinal}_pullback_foot_ratio"
        work[foot_ratio_column + "_bin"] = pd.cut(
            pd.to_numeric(work.get(foot_ratio_column), errors="coerce"),
            ratio_edges,
            labels=ratio_labels,
            right=False,
        )
    work["m5_stair_dominance_ratio_bin"] = pd.cut(
        pd.to_numeric(work.get("m5_stair_dominance_ratio"), errors="coerce"),
        dominance_edges,
        labels=dominance_labels,
        right=False,
    )
    for column in (
        "m5_stair_second_impulse_break_pips",
        "m5_stair_third_impulse_break_pips",
        "m5_stair_first_structure_progress_pips",
        "m5_stair_second_structure_progress_pips",
    ):
        work[column + "_bin"] = pd.cut(
            pd.to_numeric(work.get(column), errors="coerce"),
            progress_edges,
            labels=progress_labels,
            right=False,
        )
    for column in (
        "m5_stair_first_impulse_pips_per_foot",
        "m5_stair_first_pullback_pips_per_foot",
        "m5_stair_second_impulse_pips_per_foot",
        "m5_stair_second_pullback_pips_per_foot",
        "m5_stair_third_impulse_pips_per_foot",
        "m5_stair_net_progress_pips",
    ):
        work[column + "_bin"] = pd.cut(
            pd.to_numeric(work.get(column), errors="coerce"),
            pace_edges,
            labels=pace_labels,
            right=False,
        )
    for column in (
        "m5_stair_first_impulse_required_ratio",
        "m5_stair_second_impulse_required_ratio",
        "m5_stair_third_impulse_required_ratio",
    ):
        work[column + "_bin"] = pd.cut(
            pd.to_numeric(work.get(column), errors="coerce"),
            dominance_edges,
            labels=dominance_labels,
            right=False,
        )

    work["completed_trade"] = work["candidate_result"].isin(
        ["tp", "lc", "both_same_s5_lc_assumed", "timeout"]
    )
    work["is_win"] = work["candidate_result"].eq("tp")
    work["is_loss"] = work["candidate_result"].isin(
        ["lc", "both_same_s5_lc_assumed"]
    )
    dimensions = [
        ("all_selected", []),
        ("detected", ["m5_stair_detected"]),
        ("would_block", ["m5_stair_would_block_predict_reversal"]),
        ("state", ["m5_stair_state"]),
        ("candidate_passed", ["m5_stair_candidate_passed"]),
        ("confirmed_passed", ["m5_stair_confirmed_passed"]),
        ("first_pullback_ratio", ["m5_stair_first_pullback_ratio_bin"]),
        ("second_pullback_ratio", ["m5_stair_second_pullback_ratio_bin"]),
        ("first_pullback_foot_ratio", ["m5_stair_first_pullback_foot_ratio_bin"]),
        ("second_pullback_foot_ratio", ["m5_stair_second_pullback_foot_ratio_bin"]),
        ("first_pullback_foot_count", ["m5_stair_first_pullback_foot_count"]),
        ("second_pullback_foot_count", ["m5_stair_second_pullback_foot_count"]),
        ("first_impulse_foot_count", ["m5_stair_first_impulse_foot_count"]),
        ("second_impulse_foot_count", ["m5_stair_second_impulse_foot_count"]),
        ("third_impulse_foot_count", ["m5_stair_third_impulse_foot_count"]),
        ("dominance", ["m5_stair_dominance_ratio_bin"]),
        ("first_impulse_pace", ["m5_stair_first_impulse_pips_per_foot_bin"]),
        ("first_pullback_pace", ["m5_stair_first_pullback_pips_per_foot_bin"]),
        ("second_impulse_pace", ["m5_stair_second_impulse_pips_per_foot_bin"]),
        ("second_pullback_pace", ["m5_stair_second_pullback_pips_per_foot_bin"]),
        ("third_impulse_pace", ["m5_stair_third_impulse_pips_per_foot_bin"]),
        ("first_impulse_required_ratio", ["m5_stair_first_impulse_required_ratio_bin"]),
        ("second_impulse_required_ratio", ["m5_stair_second_impulse_required_ratio_bin"]),
        ("third_impulse_required_ratio", ["m5_stair_third_impulse_required_ratio_bin"]),
        ("net_progress", ["m5_stair_net_progress_pips_bin"]),
        ("second_impulse_break", ["m5_stair_second_impulse_break_pips_bin"]),
        ("third_impulse_break", ["m5_stair_third_impulse_break_pips_bin"]),
        ("first_structure_progress", ["m5_stair_first_structure_progress_pips_bin"]),
        ("second_structure_progress", ["m5_stair_second_structure_progress_pips_bin"]),
        ("candidate_failures", ["m5_stair_candidate_failed_conditions"]),
        ("confirmed_failures", ["m5_stair_confirmed_failed_conditions"]),
    ]
    criterion_columns = sorted(
        column
        for column in work.columns
        if column.startswith("m5_stair_criterion_")
    )
    dimensions.extend(
        (column.removeprefix("m5_stair_"), [column])
        for column in criterion_columns
    )

    summaries: list[dict[str, Any]] = []
    for group_name, columns in dimensions:
        grouped = [((), work)] if not columns else work.groupby(
            columns,
            dropna=False,
            observed=True,
        )
        for keys, group in grouped:
            if len(group) < min_group_size and group_name != "all_selected":
                continue
            if not isinstance(keys, tuple):
                keys = (keys,)
            completed = group[group["completed_trade"]]
            result_pips = pd.to_numeric(
                completed.get("trade_result_pips"),
                errors="coerce",
            )
            result_r = pd.to_numeric(
                completed.get("result_r"),
                errors="coerce",
            )
            favorable = pd.to_numeric(
                completed.get("max_favorable_pips_before_exit"),
                errors="coerce",
            )
            adverse = pd.to_numeric(
                completed.get("max_adverse_pips_before_exit"),
                errors="coerce",
            )
            row: dict[str, Any] = {
                "group_type": group_name,
                "selected_event_count": group["event_id"].nunique(),
                "filled_count": int(group["filled"].fillna(False).sum()),
                "completed_trade_count": len(completed),
                "tp_count": int(group["is_win"].sum()),
                "loss_count": int(group["is_loss"].sum()),
                "fill_rate": float(group["filled"].fillna(False).mean()),
                "win_rate_completed": (
                    float(completed["is_win"].mean())
                    if len(completed)
                    else np.nan
                ),
                "mean_result_pips": float(result_pips.mean()),
                "median_result_pips": float(result_pips.median()),
                "mean_result_r": float(result_r.mean()),
                "mean_max_favorable_pips": float(favorable.mean()),
                "mean_max_adverse_pips": float(adverse.mean()),
            }
            for column, key in zip(columns, keys):
                row[column] = key
            summaries.append(row)
    return pd.DataFrame(summaries)


def make_h1_stair_analysis(
    candidates: pd.DataFrame,
    min_group_size: int,
) -> pd.DataFrame:
    """Reuse the detailed stair summary for the H1 macro context."""
    if candidates.empty:
        return pd.DataFrame()
    work = candidates.copy()
    m5_columns = [
        column for column in work.columns if column.startswith("m5_stair_")
    ]
    work.drop(columns=m5_columns, inplace=True)
    work.rename(
        columns={
            column: "m5_stair_" + column.removeprefix("h1_stair_")
            for column in work.columns
            if column.startswith("h1_stair_")
        },
        inplace=True,
    )
    summary = make_stair_analysis(work, min_group_size)
    summary.rename(
        columns={
            column: "h1_stair_" + column.removeprefix("m5_stair_")
            for column in summary.columns
            if column.startswith("m5_stair_")
        },
        inplace=True,
    )
    return summary


def make_stair_policy_analysis(candidates: pd.DataFrame) -> pd.DataFrame:
    """Compare short-term, macro and combined stair blocking outcomes."""
    if candidates.empty:
        return pd.DataFrame()
    work = candidates.copy()
    work["completed_trade"] = work["candidate_result"].isin(
        ["tp", "lc", "both_same_s5_lc_assumed", "timeout"]
    )
    work["is_win"] = work["candidate_result"].eq("tp")
    selected = work[
        work["current_policy_predict_selected"].fillna(False)
    ].copy()
    if selected.empty:
        return pd.DataFrame()
    selected["m5_block"] = selected[
        "m5_stair_would_block_predict_reversal"
    ].fillna(False)
    selected["h1_block"] = selected[
        "h1_stair_would_block_predict_reversal"
    ].fillna(False)
    selected["combined_block"] = selected["m5_block"] | selected["h1_block"]
    selected["allowed_by_both"] = ~selected["combined_block"]
    groups = [
        ("all_counterfactual_selected", selected),
        ("m5_would_block", selected[selected["m5_block"]]),
        ("h1_would_block", selected[selected["h1_block"]]),
        ("either_would_block", selected[selected["combined_block"]]),
        ("allowed_by_both_stairs", selected[selected["allowed_by_both"]]),
        (
            "current_policy_live_selected",
            work[work["current_policy_live_selected"].fillna(False)],
        ),
    ]
    rows = []
    for label, group in groups:
        completed = group[group["completed_trade"]]
        result_pips = pd.to_numeric(
            completed.get("trade_result_pips"),
            errors="coerce",
        )
        rows.append(
            {
                "policy_group": label,
                "event_count": group["event_id"].nunique(),
                "filled_count": int(group["filled"].fillna(False).sum()),
                "completed_trade_count": len(completed),
                "tp_count": int(group["is_win"].sum()),
                "fill_rate": (
                    float(group["filled"].fillna(False).mean())
                    if len(group)
                    else np.nan
                ),
                "win_rate_completed": (
                    float(completed["is_win"].mean())
                    if len(completed)
                    else np.nan
                ),
                "mean_result_pips": (
                    float(result_pips.mean()) if len(completed) else np.nan
                ),
            }
        )
    return pd.DataFrame(rows)


def output_paths(
    pair_name: str,
    args: argparse.Namespace,
) -> dict[str, Path]:
    period = f"{args.start:%Y%m%d}_{args.end:%Y%m%d}"
    config = (
        f"m5line{LINE_HISTORY_BARS}"
        f"_range{args.tp_lookback}x{args.tp_multiplier:g}"
        f"_rr{args.rr:g}"
        f"_sp{args.spread_pips:g}"
        f"_{args.horizon_minutes}m"
    )
    stem = f"{pair_name}_{period}_{config}"
    folder = Path(args.output_dir)
    return {
        "candidates": folder / f"resistance_sweep_candidates_{stem}.csv",
        "wins": folder / f"resistance_sweep_wins_{stem}.csv",
        "events": folder / f"resistance_sweep_events_{stem}.csv",
        "ranking": folder / f"resistance_sweep_ranking_{stem}.csv",
        "stair_analysis": folder / f"resistance_sweep_stair_analysis_{stem}.csv",
        "h1_stair_analysis": folder / f"resistance_sweep_h1_stair_analysis_{stem}.csv",
        "stair_policy_analysis": folder / f"resistance_sweep_stair_policy_{stem}.csv",
        "progress": folder / f"resistance_sweep_progress_{stem}.json",
    }


def _notify(message: str) -> None:
    win_point.send_inspection_notice(message)


def _write_progress(
    path: Path,
    *,
    pair_name: str,
    args: argparse.Namespace,
    status: str,
    phase: str,
    wall_started: dt.datetime,
    process_started: float,
    total_positions: int | None = None,
    current_position: int = 0,
    evaluated_events: int = 0,
    candidate_rows: int = 0,
    decision_time: pd.Timestamp | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    elapsed_seconds = max(time.monotonic() - process_started, 0.0)
    progress_percent = (
        100.0 * current_position / total_positions
        if total_positions
        else None
    )
    remaining_seconds = (
        elapsed_seconds * (total_positions - current_position) / current_position
        if total_positions and current_position > 0
        else None
    )
    payload = {
        "pair": pair_name,
        "pid": os.getpid(),
        "status": status,
        "phase": phase,
        "started_at": wall_started.astimezone().isoformat(timespec="seconds"),
        "updated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "requested_start": args.start.isoformat(" "),
        "requested_end": args.end.isoformat(" "),
        "current_position": int(current_position),
        "total_positions": (
            int(total_positions) if total_positions is not None else None
        ),
        "progress_percent": (
            round(progress_percent, 3)
            if progress_percent is not None
            else None
        ),
        "evaluated_events": int(evaluated_events),
        "candidate_rows": int(candidate_rows),
        "current_decision_time": (
            pd.Timestamp(decision_time).isoformat(" ")
            if decision_time is not None
            else None
        ),
        "elapsed_minutes": round(elapsed_seconds / 60.0, 2),
        "estimated_remaining_minutes": (
            round(remaining_seconds / 60.0, 2)
            if remaining_seconds is not None
            else None
        ),
        "error": error,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary_path.replace(path)
    return payload


def _archive_progress(path: Path) -> Path:
    if not path.exists():
        return path
    archive = path.parent / "archive"
    archive.mkdir(parents=True, exist_ok=True)
    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    destination = archive / f"{path.stem}_{timestamp}{path.suffix}"
    sequence = 1
    while destination.exists():
        destination = archive / (
            f"{path.stem}_{timestamp}_{sequence}{path.suffix}"
        )
        sequence += 1
    path.replace(destination)
    path.with_suffix(path.suffix + ".tmp").unlink(missing_ok=True)
    return destination


def _mark_progress_failed(path: Path, error: Exception) -> Path:
    if not path.exists():
        return path
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = {}
    payload.update(
        {
            "status": "failed",
            "phase": "failed",
            "updated_at": dt.datetime.now().astimezone().isoformat(
                timespec="seconds"
            ),
            "error": f"{type(error).__name__}: {error}",
        }
    )
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary_path.replace(path)
    return _archive_progress(path)


def _event_summary(
    base: dict[str, Any],
    event_candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    row = dict(base)
    row["candidate_count"] = len(event_candidates)
    if not event_candidates:
        row.update(
            {
                "filled_candidate_count": 0,
                "completed_trade_count": 0,
                "winning_candidate_count": 0,
                "has_winning_candidate": False,
                "closest_winning_rank": np.nan,
                "closest_winning_distance_pips": np.nan,
            }
        )
        return row
    frame = pd.DataFrame(event_candidates)
    completed = frame["candidate_result"].isin(
        ["tp", "lc", "both_same_s5_lc_assumed", "timeout"]
    )
    wins = frame[frame["candidate_result"].eq("tp")]
    row.update(
        {
            "filled_candidate_count": int(frame["filled"].fillna(False).sum()),
            "completed_trade_count": int(completed.sum()),
            "winning_candidate_count": len(wins),
            "has_winning_candidate": bool(len(wins)),
            "closest_winning_rank": (
                int(wins["candidate_rank"].min()) if len(wins) else np.nan
            ),
            "closest_winning_distance_pips": (
                float(wins["distance_pips"].min()) if len(wins) else np.nan
            ),
        }
    )
    return row


def run_sweep(
    pair_name: str,
    args: argparse.Namespace,
) -> dict[str, Path]:
    pair = gene.currency_pair(pair_name)
    process_started = time.monotonic()
    wall_started = dt.datetime.now().astimezone()
    paths = output_paths(pair_name, args)
    Path(args.output_dir).mkdir(parents=True, exist_ok=True)
    _write_progress(
        paths["progress"],
        pair_name=pair_name,
        args=args,
        status="running",
        phase="loading_data",
        wall_started=wall_started,
        process_started=process_started,
    )
    m5, h1, s5 = load_pair_data(
        pair_name,
        args.start,
        args.end,
        args.existing_data,
        args.horizon_minutes,
    )
    indices = win_point.candidate_indices(m5, args.start, args.end).tolist()
    total_positions = len(indices)
    _write_progress(
        paths["progress"],
        pair_name=pair_name,
        args=args,
        status="running",
        phase="processing",
        wall_started=wall_started,
        process_started=process_started,
        total_positions=total_positions,
    )
    inspector = LimitPathInspector(s5, pair)
    candidate_rows: list[dict[str, Any]] = []
    event_rows: list[dict[str, Any]] = []
    h1_stair_cache: dict[pd.Timestamp, dict[str, Any]] = {}
    evaluated_events = 0
    last_decision_time: pd.Timestamp | None = None
    next_notice = pd.Timestamp(args.start) + pd.DateOffset(months=2)

    _notify(
        (
            f"{pair_name} count2 resistance inspection 開始\n"
            f"- 期間: {args.start:%Y-%m-%d %H:%M} ～ {args.end:%Y-%m-%d %H:%M}\n"
            f"- 条件: 直近{args.tp_lookback}本平均×{args.tp_multiplier:g}, "
            f"RR={args.rr:g}, spread={args.spread_pips:g}pips\n"
            f"- 評価: 全候補を独立した反実仮想LIMITとして検証"
        )
    )

    for position, index in enumerate(indices):
        decision_time = pd.Timestamp(m5.iloc[index]["time_jp_dt"])
        last_decision_time = decision_time
        current_position = position + 1
        if current_position == 1 or current_position % 50 == 0:
            _write_progress(
                paths["progress"],
                pair_name=pair_name,
                args=args,
                status="running",
                phase="processing",
                wall_started=wall_started,
                process_started=process_started,
                total_positions=total_positions,
                current_position=current_position,
                evaluated_events=evaluated_events,
                candidate_rows=len(candidate_rows),
                decision_time=decision_time,
            )
        event_base: dict[str, Any] = {
            "event_id": _event_id(pair_name, decision_time),
            "pair": pair_name,
            "decision_time": decision_time,
            "counterfactual_candidates": True,
        }
        if position + 1 >= len(indices):
            event_rows.append(
                {
                    **event_base,
                    "event_status": "no_next_count2",
                    "event_skip_reason": "next_count2_not_inside_requested_period",
                    "candidate_count": 0,
                }
            )
            break
        next_index = indices[position + 1]
        next_count2_time = pd.Timestamp(m5.iloc[next_index]["time_jp_dt"])
        event_base["next_count2_time"] = next_count2_time
        event_base["pending_minutes"] = float(
            (next_count2_time - decision_time).total_seconds() / 60
        )

        target = target_parameters(
            m5,
            index,
            pair,
            args.tp_lookback,
            args.tp_multiplier,
            args.rr,
        )
        if not target["target_valid"]:
            event_rows.append(
                {
                    **event_base,
                    **target,
                    "event_status": "skipped",
                    "event_skip_reason": target["target_skip_reason"],
                    "candidate_count": 0,
                }
            )
            continue

        try:
            rebuilt = rebuild_candidates_at(
                m5,
                index,
                pair_name,
                h1=h1,
                h1_stair_cache=h1_stair_cache,
            )
        except Exception as error:
            event_rows.append(
                {
                    **event_base,
                    **target,
                    "event_status": "skipped",
                    "event_skip_reason": (
                        f"line_rebuild_error:{type(error).__name__}:{error}"
                    ),
                    "candidate_count": 0,
                }
            )
            continue

        peak = rebuilt["newest_peak"]
        event_base.update(
            {
                **target,
                **_peak_columns(peak, pair),
                "decision_price": rebuilt["current_price"],
                "rsi_1": rebuilt["rsi_info"].get("rsi_1"),
                "rsi_2": rebuilt["rsi_info"].get("rsi_2"),
                "rsi_3": rebuilt["rsi_info"].get("rsi_3"),
                **stair_analysis_columns(
                    rebuilt["stair_context"],
                    int(peak.get("direction") or 0),
                ),
                **stair_analysis_columns(
                    rebuilt["h1_stair_context"],
                    int(peak.get("direction") or 0),
                    prefix="h1_stair",
                ),
            }
        )
        touches_by_candidate: dict[int, dict[str, Any]] = {}
        for candidate in rebuilt["candidates"]:
            touches = line_touch_features(
                rebuilt["completed_history"],
                candidate["line"],
                decision_time,
                pair,
                args.retouch_tolerance_pips,
            )
            candidate.update(touches)
            candidate["predict_distance_to_tp_ratio"] = (
                candidate["distance_pips"] / target["tp_pips"]
            )
            touches_by_candidate[id(candidate)] = touches

        counterfactual_candidates = [
            candidate
            for candidate in rebuilt["candidates"]
            if candidate.get("current_policy_reversal_target") is True
        ]
        rebuilt["profile"].rank_predict_reversal_candidates(
            counterfactual_candidates,
            rsi_info=rebuilt["rsi_info"],
            latest_peak_info={
                "direction": peak.get("direction"),
                "count": peak.get("count"),
            },
        )
        for candidate in rebuilt["candidates"]:
            candidate["counterfactual_predict_candidate_rank"] = (
                candidate.get("predict_candidate_rank")
            )
            candidate["counterfactual_predict_selected"] = (
                candidate.get("predict_candidate_rank") == 1
            )

        previous_peak = (
            rebuilt["m5_peaks"][1]
            if len(rebuilt["m5_peaks"]) > 1
            else {}
        )
        latest_peak_info = {
            "direction": peak.get("direction"),
            "count": peak.get("count"),
            "rsi": peak.get("rsi"),
            "previous_rsi": previous_peak.get("rsi"),
        }
        live_eligible_candidates = []
        for candidate in counterfactual_candidates:
            passes = rebuilt[
                "profile"
            ]._predict_reversal_candidate_passes_filters(
                candidate,
                latest_peak_info,
            )
            candidate["current_policy_live_eligible"] = bool(passes)
            if passes:
                live_eligible_candidates.append(candidate)
        rebuilt["profile"].rank_predict_reversal_candidates(
            live_eligible_candidates,
            rsi_info=rebuilt["rsi_info"],
            latest_peak_info=latest_peak_info,
        )
        for candidate in rebuilt["candidates"]:
            candidate.setdefault("current_policy_live_eligible", False)
            candidate["current_policy_live_selected"] = bool(
                candidate["current_policy_live_eligible"]
                and candidate.get("predict_candidate_rank") == 1
            )

        rows_for_event: list[dict[str, Any]] = []
        for candidate in rebuilt["candidates"]:
            line = candidate["line"]
            touches = touches_by_candidate[id(candidate)]
            path = inspector.inspect(
                decision_time=decision_time,
                expiry_time=next_count2_time,
                direction=candidate["trade_direction"],
                line_price=candidate["line_price"],
                tp_pips=target["tp_pips"],
                lc_pips=target["lc_pips"],
                horizon_minutes=args.horizon_minutes,
                spread_pips=args.spread_pips,
            )
            row = {
                **event_base,
                "candidate_rank": candidate["candidate_rank"],
                "distance_rank": candidate["distance_rank"],
                "predict_candidate_rank": candidate.get(
                    "predict_candidate_rank"
                ),
                "predict_candidate_count": candidate.get(
                    "predict_candidate_count"
                ),
                "predict_ranking_version": candidate.get(
                    "predict_ranking_version"
                ),
                "predict_rank_input_scope": candidate.get(
                    "predict_rank_input_scope"
                ),
                "predict_rank_score": candidate.get("predict_rank_score"),
                "predict_rank_pair": candidate.get("predict_rank_pair"),
                "predict_distance_to_tp_ratio": candidate.get(
                    "predict_distance_to_tp_ratio"
                ),
                "predict_rank_distance_to_tp_ratio": candidate.get(
                    "predict_rank_distance_to_tp_ratio"
                ),
                "predict_rank_average_strength": candidate.get(
                    "predict_rank_average_strength"
                ),
                "predict_rank_line_count": candidate.get(
                    "predict_rank_line_count"
                ),
                "predict_rank_core_average_strength": candidate.get(
                    "predict_rank_core_average_strength"
                ),
                "predict_rank_estimated_strength": candidate.get(
                    "predict_rank_estimated_strength"
                ),
                "predict_rank_rsi_1": candidate.get("predict_rank_rsi_1"),
                "predict_rank_rsi_2": candidate.get("predict_rank_rsi_2"),
                "predict_rank_directional_rsi": candidate.get(
                    "predict_rank_directional_rsi"
                ),
                "predict_rank_source_rsi": candidate.get(
                    "predict_rank_source_rsi"
                ),
                "predict_rank_source_elapsed_minutes": candidate.get(
                    "predict_rank_source_elapsed_minutes"
                ),
                "predict_rank_last_reach_elapsed_minutes": candidate.get(
                    "predict_rank_last_reach_elapsed_minutes"
                ),
                "predict_rank_last_reach_source": candidate.get(
                    "predict_rank_last_reach_source"
                ),
                "predict_rank_prior_retouch_count": candidate.get(
                    "predict_rank_prior_retouch_count"
                ),
                "predict_rank_components": candidate.get(
                    "predict_rank_components"
                ),
                "predict_rank_in_distance_cap": candidate.get(
                    "predict_rank_in_distance_cap"
                ),
                "predict_rank_distance_ratio_cap": candidate.get(
                    "predict_rank_distance_ratio_cap"
                ),
                "predict_rank_fallback": candidate.get(
                    "predict_rank_fallback"
                ),
                "predict_rank_flip_count": candidate.get(
                    "predict_rank_flip_count"
                ),
                "predict_rank_count_penalty": candidate.get(
                    "predict_rank_count_penalty"
                ),
                "predict_rank_flip_bonus": candidate.get(
                    "predict_rank_flip_bonus"
                ),
                "predict_distance_rank": candidate.get(
                    "predict_distance_rank"
                ),
                "current_policy_predict_selected": (
                    candidate.get("counterfactual_predict_selected")
                ),
                "counterfactual_predict_candidate_rank": candidate.get(
                    "counterfactual_predict_candidate_rank"
                ),
                "current_policy_live_eligible": candidate.get(
                    "current_policy_live_eligible"
                ),
                "predict_reversal_filter_policy_version": candidate.get(
                    "predict_reversal_filter_policy_version"
                ),
                "predict_reversal_top15_matches": "|".join(
                    candidate.get("predict_reversal_top15_matches") or []
                ),
                "predict_reversal_top15_match_count": candidate.get(
                    "predict_reversal_top15_match_count"
                ),
                "current_policy_live_selected": candidate.get(
                    "current_policy_live_selected"
                ),
                "line_side": candidate["line_side"],
                "trade_direction": candidate["trade_direction"],
                "trade_side": candidate["trade_side"],
                "line_price": candidate["line_price"],
                "raw_line_price": candidate["raw_line_price"],
                "distance_pips": candidate["distance_pips"],
                "distance_to_tp_ratio": (
                    candidate["distance_pips"] / target["tp_pips"]
                ),
                "current_policy_reversal_target": candidate[
                    "current_policy_reversal_target"
                ],
                "candidate_scope": "all_raw_m5_line_groups_ahead",
                "candidate_pruning_applied": False,
                "line_timeframe": "M5",
                "line_history_bars": LINE_HISTORY_BARS,
                "fixed_spread_pips": args.spread_pips,
                "pending_expiry_exclusive": True,
                "position_horizon_minutes": args.horizon_minutes,
                **_line_columns(line),
                **touches,
                **path,
            }
            candidate_rows.append(row)
            rows_for_event.append(row)

        event_status = "evaluated" if rows_for_event else "no_candidates"
        event_rows.append(
            _event_summary(
                {
                    **event_base,
                    "event_status": event_status,
                    "event_skip_reason": None,
                },
                rows_for_event,
            )
        )
        evaluated_events += 1

        while decision_time >= next_notice:
            elapsed_minutes = (time.monotonic() - process_started) / 60
            progress_percent = (
                100.0 * current_position / total_positions
                if total_positions
                else 0.0
            )
            remaining_minutes = (
                elapsed_minutes
                * (total_positions - current_position)
                / current_position
                if current_position > 0
                else None
            )
            _notify(
                (
                    f"{pair_name} count2 resistance inspection 進捗\n"
                    f"- 到達時刻: {next_notice:%Y-%m-%d %H:%M}\n"
                    f"- 処理位置: {current_position}/{total_positions} "
                    f"({progress_percent:.1f}%)\n"
                    f"- 評価イベント: {evaluated_events}\n"
                    f"- 候補行: {len(candidate_rows)}\n"
                    f"- 経過時間: {elapsed_minutes:.1f}分\n"
                    f"- 推定残り時間: "
                    + (
                        f"{remaining_minutes:.1f}分"
                        if remaining_minutes is not None
                        else "算出中"
                    )
                )
            )
            next_notice = next_notice + pd.DateOffset(months=2)

        if evaluated_events % 250 == 0:
            progress_percent = (
                100.0 * current_position / total_positions
                if total_positions
                else 0.0
            )
            print(
                f"[PROGRESS] {pair_name}: "
                f"position={current_position}/{total_positions} "
                f"({progress_percent:.1f}%), "
                f"events={evaluated_events}, candidates={len(candidate_rows)}"
            )
        if args.max_events is not None and evaluated_events >= args.max_events:
            break

    processed_positions = min(total_positions, len(event_rows))
    _write_progress(
        paths["progress"],
        pair_name=pair_name,
        args=args,
        status="running",
        phase="writing_results",
        wall_started=wall_started,
        process_started=process_started,
        total_positions=total_positions,
        current_position=processed_positions,
        evaluated_events=evaluated_events,
        candidate_rows=len(candidate_rows),
        decision_time=last_decision_time,
    )

    candidates = pd.DataFrame(candidate_rows)
    events = pd.DataFrame(event_rows)
    wins = (
        candidates[candidates["candidate_result"].eq("tp")].copy()
        if not candidates.empty
        else pd.DataFrame()
    )
    ranking = make_ranking(candidates, args.min_group_size)
    stair_analysis = make_stair_analysis(candidates, args.min_group_size)
    h1_stair_analysis = make_h1_stair_analysis(
        candidates,
        args.min_group_size,
    )
    stair_policy_analysis = make_stair_policy_analysis(candidates)
    paths = output_paths(pair_name, args)
    Path(args.output_dir).mkdir(parents=True, exist_ok=True)
    candidates.to_csv(paths["candidates"], index=False, encoding="utf-8-sig")
    wins.to_csv(paths["wins"], index=False, encoding="utf-8-sig")
    events.to_csv(paths["events"], index=False, encoding="utf-8-sig")
    ranking.to_csv(paths["ranking"], index=False, encoding="utf-8-sig")
    stair_analysis.to_csv(
        paths["stair_analysis"],
        index=False,
        encoding="utf-8-sig",
    )
    h1_stair_analysis.to_csv(
        paths["h1_stair_analysis"],
        index=False,
        encoding="utf-8-sig",
    )
    stair_policy_analysis.to_csv(
        paths["stair_policy_analysis"],
        index=False,
        encoding="utf-8-sig",
    )

    completed_mask = (
        candidates["candidate_result"].isin(
            ["tp", "lc", "both_same_s5_lc_assumed", "timeout"]
        )
        if not candidates.empty
        else pd.Series(dtype=bool)
    )
    completed_count = int(completed_mask.sum())
    win_count = int(
        candidates["candidate_result"].eq("tp").sum()
        if not candidates.empty
        else 0
    )
    winning_events = int(
        events.get("has_winning_candidate", pd.Series(dtype=bool))
        .fillna(False)
        .sum()
    )
    event_status = (
        events.get("event_status", pd.Series(dtype=object))
        .fillna("unknown")
        .value_counts()
    )
    event_skip_reason = events.get(
        "event_skip_reason",
        pd.Series(dtype=object),
    ).fillna("")
    line_error_count = int(
        event_skip_reason.str.startswith("line_rebuild_error:").sum()
    )
    target_skip_count = int(
        (
            events.get("event_status", pd.Series(dtype=object)).eq("skipped")
            & ~event_skip_reason.str.startswith("line_rebuild_error:")
        ).sum()
    )
    candidate_result_counts = (
        candidates.get("candidate_result", pd.Series(dtype=object))
        .fillna("unknown")
        .value_counts()
    )
    elapsed_minutes = (time.monotonic() - process_started) / 60
    summary_lines = [
        f"期間: {args.start:%Y-%m-%d} ～ {args.end:%Y-%m-%d}",
        f"検出count2: {len(indices)}",
        f"評価イベント: {evaluated_events}",
        f"候補なしイベント: {int(event_status.get('no_candidates', 0))}",
        (
            "除外イベント: "
            f"次count2なし={int(event_status.get('no_next_count2', 0))}, "
            f"ライン再構築エラー={line_error_count}, "
            f"TP算出不可等={target_skip_count}"
        ),
        f"候補行: {len(candidates)}",
        f"約定後の完了候補: {completed_count}",
        (
            "候補状態: "
            f"未約定={int(candidate_result_counts.get('not_filled', 0))}, "
            f"注文期間S5不完全={int(candidate_result_counts.get('incomplete_pending', 0))}, "
            f"約定後S5不完全={int(candidate_result_counts.get('incomplete_horizon', 0))}"
        ),
        (
            f"勝ち候補: {win_count}"
            + (
                f" ({win_count / completed_count:.1%})"
                if completed_count
                else ""
            )
        ),
        f"1本以上勝ち候補があったイベント: {winning_events}",
        f"経過時間: {elapsed_minutes:.1f}分",
        "注意: 候補行は同時注文ではなく、イベント内の独立した反実仮想",
    ]
    print(f"{pair_name} count2 resistance inspection 完了")
    for line in summary_lines:
        print(f"- {line}")
    _notify(
        (
            f"{pair_name} count2 resistance inspection 完了\n"
            + "\n".join(f"- {line}" for line in summary_lines)
        )
    )
    _write_progress(
        paths["progress"],
        pair_name=pair_name,
        args=args,
        status="complete",
        phase="complete",
        wall_started=wall_started,
        process_started=process_started,
        total_positions=total_positions,
        current_position=processed_positions,
        evaluated_events=evaluated_events,
        candidate_rows=len(candidate_rows),
        decision_time=last_decision_time,
    )
    paths["progress"] = _archive_progress(paths["progress"])
    return paths


def main(
    pair_name: str,
    argv: list[str] | None = None,
    *,
    default_start: dt.datetime | None = None,
    default_end: dt.datetime | None = None,
) -> dict[str, Path]:
    args = parse_args(
        pair_name,
        argv,
        default_start=default_start,
        default_end=default_end,
    )
    try:
        return run_sweep(pair_name, args)
    except Exception as error:
        progress_path = output_paths(pair_name, args)["progress"]
        try:
            _mark_progress_failed(progress_path, error)
        except Exception as progress_error:
            print(
                "[PROGRESS] failed to archive progress status: "
                f"{type(progress_error).__name__}: {progress_error}"
            )
        _notify(
            (
                f"{pair_name} count2 resistance inspection 異常終了\n"
                f"- エラー種別: {type(error).__name__}\n"
                f"- 内容: {error}"
            )
        )
        raise


if __name__ == "__main__":
    main("AUD_USD")
