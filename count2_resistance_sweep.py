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
import io
import math
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd

import classOanda
from classCandlePeaks import PeaksClass
import fGeneric as gene
from fLineAnalysis import LineStrengthCal, line_strategy_profile
import test_win_point_usd_aud as win_point
import tokens as tk


DEFAULT_START = dt.datetime(2025, 7, 30)
DEFAULT_END = dt.datetime(2026, 7, 30)
LINE_HISTORY_BARS = 60
PEAK_HISTORY_BARS = 180
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


def _likely_weekend_closed(timestamp: pd.Timestamp) -> bool:
    """Conservative JST weekend window used only for cache edge checks."""
    timestamp = pd.Timestamp(timestamp)
    return (
        timestamp.weekday() in (5, 6)
        or (timestamp.weekday() == 0 and timestamp.hour < 6)
    )


def _nearest_likely_open_time(
    timestamp: pd.Timestamp,
    step: pd.Timedelta,
    direction: int,
) -> pd.Timestamp:
    timestamp = pd.Timestamp(timestamp)
    for _ in range(int(pd.Timedelta(days=4) / step) + 1):
        if not _likely_weekend_closed(timestamp):
            return timestamp
        timestamp = timestamp + direction * step
    return timestamp


def data_coverage_errors(
    m5: pd.DataFrame,
    s5: pd.DataFrame,
    start: dt.datetime,
    end: dt.datetime,
    horizon_minutes: int,
) -> dict[str, list[str]]:
    """Detect truncated cache edges before event extraction begins."""
    errors: dict[str, list[str]] = {"M5": [], "S5": []}
    start_time = pd.Timestamp(start)
    end_time = pd.Timestamp(end)
    if m5.empty:
        errors["M5"].append("empty")
    else:
        history_rows = int((m5["time_jp_dt"] < start_time).sum())
        if history_rows < PEAK_HISTORY_BARS:
            errors["M5"].append(
                f"prehistory_rows={history_rows}<{PEAK_HISTORY_BARS}"
            )
        if not m5["time_jp_dt"].between(
            start_time,
            end_time,
            inclusive="left",
        ).any():
            errors["M5"].append("no_rows_in_requested_period")
        expected_m5_last = _nearest_likely_open_time(
            end_time - pd.Timedelta(minutes=5),
            pd.Timedelta(minutes=5),
            -1,
        )
        actual_m5_last = pd.Timestamp(m5["time_jp_dt"].max())
        if actual_m5_last < expected_m5_last:
            errors["M5"].append(
                "truncated_end:"
                f"{actual_m5_last}<{expected_m5_last}"
            )

    if s5.empty:
        errors["S5"].append("empty")
    else:
        expected_s5_first = _nearest_likely_open_time(
            start_time,
            pd.Timedelta(seconds=S5_SECONDS),
            1,
        )
        actual_s5_first = pd.Timestamp(s5["time_jp_dt"].min())
        if actual_s5_first > expected_s5_first:
            errors["S5"].append(
                "truncated_start:"
                f"{actual_s5_first}>{expected_s5_first}"
            )
        required_end = end_time + pd.Timedelta(minutes=horizon_minutes)
        expected_s5_last = _nearest_likely_open_time(
            required_end - pd.Timedelta(seconds=S5_SECONDS),
            pd.Timedelta(seconds=S5_SECONDS),
            -1,
        )
        actual_s5_last = pd.Timestamp(s5["time_jp_dt"].max())
        if actual_s5_last < expected_s5_last:
            errors["S5"].append(
                "truncated_end:"
                f"{actual_s5_last}<{expected_s5_last}"
            )
    return {frame: values for frame, values in errors.items() if values}


def load_pair_data(
    pair_name: str,
    start: dt.datetime,
    end: dt.datetime,
    existing_only: bool,
    horizon_minutes: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load only M5 and S5; H1 is not involved in this validation."""
    win_point.PAIR = pair_name
    paths = win_point.cache_paths(start, end)
    requirements = {
        "M5": (
            start - dt.timedelta(hours=max(win_point.H1_HISTORY, 16)),
            end,
        ),
        "S5": (start, end + dt.timedelta(minutes=horizon_minutes)),
    }
    data: dict[str, pd.DataFrame] = {}
    missing: list[str] = []
    incompatible: list[str] = []
    for frame in ("M5", "S5"):
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
    s5 = prepare_s5(data.pop("S5"))
    coverage_errors = data_coverage_errors(
        m5,
        s5,
        start,
        end,
        horizon_minutes,
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
            else:
                s5 = prepare_s5(refreshed)
        remaining_errors = data_coverage_errors(
            m5,
            s5,
            start,
            end,
            horizon_minutes,
        )
        if remaining_errors:
            raise ValueError(
                "Fetched data coverage is incomplete: "
                + "; ".join(
                    f"{frame}: {', '.join(values)}"
                    for frame, values in remaining_errors.items()
                )
            )
    return m5, s5


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

    analysis = SimpleNamespace(
        pair=pair_name,
        current_price=current_price,
        d5_df_r=snapshot,
        peaks_class=peaks,
        candle_meta_class=None,
        h1_df_r=snapshot,
        peaks_class_hour=peaks,
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
    peak_direction = int(newest_peak["direction"])
    candidates = select_ahead_lines(
        peak_direction,
        current_price,
        line_class.upper_lines,
        line_class.lower_lines,
        pair,
        profile,
    )
    return {
        "decision_time": decision_time,
        "current_price": current_price,
        "newest_peak": newest_peak,
        "peak_direction": peak_direction,
        "completed_history": completed,
        "candidates": candidates,
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
    def _is_expected_weekend_gap(
        previous_time: pd.Timestamp,
        next_time: pd.Timestamp,
    ) -> bool:
        previous_time = pd.Timestamp(previous_time)
        next_time = pd.Timestamp(next_time)
        gap = next_time - previous_time
        return (
            previous_time.weekday() == 5
            and next_time.weekday() == 0
            and previous_time.hour in (5, 6, 7)
            and next_time.hour in (5, 6, 7, 8)
            and pd.Timedelta(hours=46) <= gap <= pd.Timedelta(hours=50)
        )

    @staticmethod
    def _is_expected_daily_break_gap(
        previous_time: pd.Timestamp,
        next_time: pd.Timestamp,
    ) -> bool:
        """Accept OANDA's known 16:59-17:05 New York daily pause."""
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
        previous_ny = previous_jst.tz_convert("America/New_York")
        next_ny = next_jst.tz_convert("America/New_York")
        if (
            previous_ny.normalize() != next_ny.normalize()
            or previous_ny.weekday() >= 4
        ):
            return False
        break_start = previous_ny.normalize() + pd.Timedelta(
            hours=16,
            minutes=59,
        )
        break_end = previous_ny.normalize() + pd.Timedelta(
            hours=17,
            minutes=5,
        )
        return (
            previous_ny <= break_start
            and next_ny >= break_end
            and next_ny - previous_ny <= pd.Timedelta(minutes=15)
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
                if LimitPathInspector._is_expected_weekend_gap(
                    pd.Timestamp(previous),
                    pd.Timestamp(following),
                ):
                    continue
                if LimitPathInspector._is_expected_daily_break_gap(
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
    }


def _notify(message: str) -> None:
    win_point.send_inspection_notice(message)


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
    m5, s5 = load_pair_data(
        pair_name,
        args.start,
        args.end,
        args.existing_data,
        args.horizon_minutes,
    )
    indices = win_point.candidate_indices(m5, args.start, args.end).tolist()
    inspector = LimitPathInspector(s5, pair)
    candidate_rows: list[dict[str, Any]] = []
    event_rows: list[dict[str, Any]] = []
    evaluated_events = 0
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
            rebuilt = rebuild_candidates_at(m5, index, pair_name)
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
            }
        )
        rows_for_event: list[dict[str, Any]] = []
        for candidate in rebuilt["candidates"]:
            line = candidate["line"]
            touches = line_touch_features(
                rebuilt["completed_history"],
                line,
                decision_time,
                pair,
                args.retouch_tolerance_pips,
            )
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
            _notify(
                (
                    f"{pair_name} count2 resistance inspection 進捗\n"
                    f"- 到達時刻: {next_notice:%Y-%m-%d %H:%M}\n"
                    f"- 評価イベント: {evaluated_events}\n"
                    f"- 候補行: {len(candidate_rows)}\n"
                    f"- 経過時間: {elapsed_minutes:.1f}分"
                )
            )
            next_notice = next_notice + pd.DateOffset(months=2)

        if evaluated_events % 250 == 0:
            print(
                f"[PROGRESS] {pair_name}: "
                f"events={evaluated_events}, candidates={len(candidate_rows)}"
            )
        if args.max_events is not None and evaluated_events >= args.max_events:
            break

    candidates = pd.DataFrame(candidate_rows)
    events = pd.DataFrame(event_rows)
    wins = (
        candidates[candidates["candidate_result"].eq("tp")].copy()
        if not candidates.empty
        else pd.DataFrame()
    )
    ranking = make_ranking(candidates, args.min_group_size)
    paths = output_paths(pair_name, args)
    Path(args.output_dir).mkdir(parents=True, exist_ok=True)
    candidates.to_csv(paths["candidates"], index=False, encoding="utf-8-sig")
    wins.to_csv(paths["wins"], index=False, encoding="utf-8-sig")
    events.to_csv(paths["events"], index=False, encoding="utf-8-sig")
    ranking.to_csv(paths["ranking"], index=False, encoding="utf-8-sig")

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
