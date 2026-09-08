# 最新更新日時: 2026-09-08 08:20 JST
"""Count-2 resistance-line exhaustive validation.

At every M5 decision point where the newest peak has count == 2, this module
rebuilds M5/M30/H1 resistance/support candidates from each timeframe's native
completed candles.  Every line ahead of the M5 peak direction is then tested
as an independent, counterfactual order.

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
from classCandleAnalysis import (
    CandleTimeframeBundle,
    H1_ANALYSIS_BARS as PRODUCTION_H1_PEAK_HISTORY_BARS,
    M30_ANALYSIS_BARS as PRODUCTION_M30_PEAK_HISTORY_BARS,
    M5_ANALYSIS_BARS as PRODUCTION_M5_PEAK_HISTORY_BARS,
    candleAnalysis as CandleAnalysis,
)
from classCandlePeaks import PeaksClass
from fCandleDataQuality import (
    is_expected_market_closed_gap as candle_gap_is_expected_closed,
    oanda_coverage_open_mask,
)
import fGeneric as gene
import fResistanceBreakoutCore as breakout_core
from fFootCountShape import (
    attach_line_wick_context,
    flatten_foot_count2_shape,
)
import send_notice as notice
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
M30_PREHISTORY_CALENDAR_HOURS = 24 * 21
LINE_TIMEFRAMES = ("M5", "M30", "H1")
TIMEFRAME_MINUTES = {"M5": 5, "M30": 30, "H1": 60}
TP_LOOKBACK = 6
TP_MULTIPLIER = 3.0
RR = 1.2
SPREAD_PIPS = 0.8
HORIZON_MINUTES = 60
RETOUCH_TOLERANCE_PIPS = 1.0
S5_SECONDS = 5
TIME_FORMAT = "%Y/%m/%d %H:%M:%S"
NORMALIZED_LC_RISK_YEN = 50.0
PRODUCTION_EQUIVALENCE_SAMPLE_COUNT = 30


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
            f"{pair_name}: M5 count2時点の進行方向先にある"
            "M5/M30/H1抵抗線候補を総当たり検証する"
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
    parser.add_argument(
        "--line-history-bars",
        type=int,
        default=LINE_HISTORY_BARS,
        help=(
            "各ライン足でラインを作る遡り本数。既定60本。"
            "同じ本数でもM5・M30・H1で実時間の範囲は異なる"
        ),
    )
    parser.add_argument(
        "--peak-history-bars",
        type=int,
        default=PEAK_HISTORY_BARS,
        help=(
            "各ライン足でピークを作る遡り本数。既定180本。"
            "line-history-bars より小さいと窓を伸ばしても古いピークが無い"
        ),
    )
    parser.add_argument(
        "--group-threshold-a",
        type=float,
        default=None,
        help="グループ化幅をA倍率で指定する。未指定なら足ごとの固定pips",
    )
    parser.add_argument(
        "--min-line-total-strength",
        type=float,
        default=0.0,
        help="ラインの合計強度の下限。既定0は現行どおり",
    )
    parser.add_argument(
        "--min-distance-a",
        type=float,
        default=0.0,
        help="現在価格からの距離の下限（A倍率）。近すぎる線を落とす",
    )
    parser.add_argument(
        "--exclude-flipped-recent",
        action="store_true",
        help=(
            "直近の構成ピークが転換状態の線を除外する。"
            "上側なのに直近が安値、下側なのに直近が高値、というもの"
        ),
    )
    parser.add_argument(
        "--min-line-direction-ratio",
        type=float,
        default=0.0,
        help=(
            "線の側に合う向きのピークが占める割合の下限（0〜1）。"
            "上側の抵抗線なら高値ピーク、下側の支持線なら安値ピークが本来の向き。"
            "0.7 なら7割以上。既定0は絞らない。"
            "2本・3本構成の線では7割は実質100%と同じになる点に注意"
        ),
    )
    parser.add_argument(
        "--separate-line-directions",
        action="store_true",
        help=(
            "上側のラインは高値のピーク、下側は安値のピークだけで組む。"
            "既定は本番と同じく向きを問わず束ねる"
        ),
    )
    parser.add_argument(
        "--min-line-peak-count",
        type=int,
        default=1,
        help="ラインとみなすのに必要なピーク数。既定1は現行どおり",
    )
    parser.add_argument(
        "--target-grid",
        action="store_true",
        help=(
            "TP/LCをA単位で総当たりし、セルごとの優位性を集計する。"
            "候補行は増えず、集計だけを別CSVへ出す"
        ),
    )
    parser.add_argument(
        "--enforce-peak-strength",
        action="store_true",
        help=(
            "ラインの構成ピークを min_line_peak_strength 以上に絞る。"
            "既定は本番と同じく絞らない"
        ),
    )
    parser.add_argument(
        "--entry-mode",
        choices=("limit", "stop"),
        default="limit",
        help=(
            "limit: ラインで折り返す側へ指値（従来の逆張り）。"
            "stop: ラインを抜ける側へ逆指値（ブレイク）"
        ),
    )
    parser.add_argument(
        "--stop-offset-pips",
        type=float,
        default=0.0,
        help="ブレイク時、ラインから何pips先に逆指値を置くか",
    )
    parser.add_argument(
        "--stop-slippage-pips",
        type=float,
        default=0.5,
        help=(
            "ブレイク時の想定スリッページ。逆指値は成行約定なので、"
            "不利側へこのぶん滑った価格を建値にする"
        ),
    )
    args = parser.parse_args(argv)
    if args.line_history_bars < 1 or args.peak_history_bars < 1:
        parser.error("--line-history-bars と --peak-history-bars は1以上です")
    if args.peak_history_bars < args.line_history_bars:
        parser.error(
            "--peak-history-bars は --line-history-bars 以上にしてください。"
            "小さいと窓を伸ばしても古いピークが存在しません"
        )
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


def prepare_analysis_candles(df: pd.DataFrame) -> pd.DataFrame:
    """Supply fields shared by PeaksClass for any analysis timeframe."""
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


def prepare_m5(df: pd.DataFrame) -> pd.DataFrame:
    """Backward-compatible name for callers/tests that prepare M5 candles."""
    return prepare_analysis_candles(df)


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
    market_open = oanda_coverage_open_mask(market_times)
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
    m30: pd.DataFrame | None = None,
) -> dict[str, list[str]]:
    """Detect truncated cache edges before event extraction begins.

    OANDA omits S5 rows when no price update occurred.  A short missing edge is
    therefore accepted up to the same causal limit used by the OANDA S5
    completion step.  No leading/trailing price is synthesized here; each
    candidate path is still required to be contiguous by LimitPathInspector.
    """
    errors: dict[str, list[str]] = {"M5": [], "S5": []}
    if m30 is not None:
        errors["M30"] = []
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

    if m30 is None:
        pass
    elif m30.empty:
        errors["M30"].append("empty")
    else:
        m30_times = m30["time_jp_dt"]
        history_rows = int((m30_times < start_time).sum())
        if history_rows < PEAK_HISTORY_BARS:
            errors["M30"].append(
                f"prehistory_rows={history_rows}<{PEAK_HISTORY_BARS}"
            )
        m30_in_period = m30_times.between(
            start_time,
            end_time,
            inclusive="left",
        )
        if not m30_in_period.any():
            errors["M30"].append("no_rows_in_requested_period")
        else:
            expected_m30_last = _nearest_oanda_open_time(
                end_time - pd.Timedelta(nanoseconds=1),
                pd.Timedelta(minutes=30),
                -1,
            )
            actual_m30_last = pd.Timestamp(m30_times.loc[m30_in_period].max())
            if actual_m30_last < expected_m30_last:
                errors["M30"].append(
                    "truncated_end:"
                    f"{actual_m30_last}<{expected_m30_last}"
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
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Load native M5/M30/H1 analysis candles and the S5 execution path."""
    win_point.PAIR = pair_name
    paths = dict(win_point.cache_paths(start, end))
    cache_name = f"{pair_name}_{start:%Y%m%d%H%M%S}_{end:%Y%m%d%H%M%S}"
    paths["M30"] = Path(tk.folder_path) / f"m30_{cache_name}.csv"
    requirements = {
        "M5": (
            start - dt.timedelta(hours=max(win_point.H1_HISTORY, 16)),
            end,
        ),
        "M30": (
            start - dt.timedelta(hours=M30_PREHISTORY_CALENDAR_HOURS),
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
    for frame in ("M5", "M30", "H1", "S5"):
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
        print(f"[CACHE] {pair_name}: M5/M30/H1/S5の既存キャッシュを使用")

    m5 = prepare_analysis_candles(data.pop("M5"))
    m30 = prepare_analysis_candles(data.pop("M30"))
    h1 = prepare_analysis_candles(data.pop("H1"))
    s5 = prepare_s5(data.pop("S5"))
    coverage_errors = data_coverage_errors(
        m5,
        s5,
        start,
        end,
        horizon_minutes,
        h1=h1,
        m30=m30,
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
                m5 = prepare_analysis_candles(refreshed)
            elif frame == "M30":
                m30 = prepare_analysis_candles(refreshed)
            elif frame == "H1":
                h1 = prepare_analysis_candles(refreshed)
            else:
                s5 = prepare_s5(refreshed)
        remaining_errors = data_coverage_errors(
            m5,
            s5,
            start,
            end,
            horizon_minutes,
            h1=h1,
            m30=m30,
        )
        if remaining_errors:
            raise ValueError(
                "Fetched data coverage is incomplete: "
                + "; ".join(
                    f"{frame}: {', '.join(values)}"
                    for frame, values in remaining_errors.items()
                )
            )
    return m5, m30, h1, s5


def target_parameters(
    m5: pd.DataFrame,
    index: int,
    pair: gene.CurrencyPair,
    lookback: int = TP_LOOKBACK,
    multiplier: float = TP_MULTIPLIER,
    rr: float = RR,
) -> dict[str, Any]:
    """Compatibility adapter to the shared newest-first breakout core."""
    decision_time = pd.Timestamp(m5.iloc[index]["time_jp_dt"])
    completed_df_r = m5.iloc[:index].iloc[::-1].reset_index(drop=True)
    return breakout_core.target_parameters(
        completed_df_r,
        decision_time,
        pair,
        lookback,
        multiplier,
        rr,
    )


# 優位性をTP/LC別に測るためのグリッド（A単位）。
# 現行の本番相当は tp=3.0A / lc=2.5A（rr1.2）で、これもセルに含まれる。
TARGET_GRID_TP_A = (1.0, 1.5, 2.0, 3.0, 4.0, 5.0)
TARGET_GRID_LC_A = (1.0, 1.5, 2.0, 2.5, 3.5)


def _line_count_bucket(line_count: Any) -> str:
    try:
        value = int(float(line_count))
    except (TypeError, ValueError):
        return "unknown"
    if value <= 1:
        return "1"
    if value == 2:
        return "2"
    if value <= 4:
        return "3-4"
    return "5+"


class TargetGridAccumulator:
    """TP/LCセルごとに、ランダム基準と実測の差を集計する。

    行を貯めるとメモリが持たないので、セル単位の合計だけを持つ。
    ランダム基準はドリフト無しのランダムウォークでの期待勝率
    ``LC距離 ÷ (TP距離 + LC距離)``。売りはbidで入りaskで決済するため、
    利確はスプレッドぶん遠く、損切りはスプレッドぶん近い。これを織り込まないと
    期待値が過大になり、優位性が実際より低く見える。
    """

    def __init__(self, spread_pips: float):
        self.spread_pips = float(spread_pips)
        self.cells: dict[tuple, dict[str, float]] = {}

    def add(
        self,
        tp_a: float,
        lc_a: float,
        line_count: Any,
        role: Any,
        tp_pips: float,
        lc_pips: float,
        path: dict[str, Any],
    ) -> None:
        if not path.get("filled"):
            return
        key = (
            float(tp_a),
            float(lc_a),
            _line_count_bucket(line_count),
            str(role),
        )
        cell = self.cells.get(key)
        if cell is None:
            cell = {
                "filled": 0.0,
                "resolved": 0.0,
                "tp_wins": 0.0,
                "expected_sum": 0.0,
                "pips_sum": 0.0,
                "win_pips_sum": 0.0,
                "yen_sum": 0.0,
                "timeout": 0.0,
            }
            self.cells[key] = cell
        cell["filled"] += 1.0
        result = path.get("trade_result")
        pips = path.get("trade_result_pips")
        if pips is not None and math.isfinite(float(pips)):
            cell["pips_sum"] += float(pips)
        result_r = path.get("result_r")
        if result_r is not None and math.isfinite(float(result_r)):
            cell["yen_sum"] += float(result_r) * NORMALIZED_LC_RISK_YEN
        if result == "timeout":
            cell["timeout"] += 1.0
        if result not in ("tp", "lc"):
            return
        tp_ask = float(tp_pips) + self.spread_pips
        lc_ask = float(lc_pips) - self.spread_pips
        if lc_ask <= 0 or tp_ask <= 0:
            return
        cell["resolved"] += 1.0
        cell["expected_sum"] += lc_ask / (tp_ask + lc_ask)
        if result == "tp":
            cell["tp_wins"] += 1.0
            if pips is not None and math.isfinite(float(pips)):
                cell["win_pips_sum"] += float(pips)

    def to_frame(self) -> pd.DataFrame:
        rows = []
        for (tp_a, lc_a, bucket, role), cell in sorted(self.cells.items()):
            resolved = cell["resolved"]
            actual = cell["tp_wins"] / resolved if resolved else np.nan
            expected = cell["expected_sum"] / resolved if resolved else np.nan
            rows.append(
                {
                    "tp_a": tp_a,
                    "lc_a": lc_a,
                    "configured_rr": tp_a / lc_a if lc_a else np.nan,
                    "line_count_bucket": bucket,
                    "line_peaks_count_bucket": bucket,
                    "line_current_role": role,
                    "filled_count": int(cell["filled"]),
                    "resolved_count": int(resolved),
                    "timeout_count": int(cell["timeout"]),
                    "actual_win_rate": actual,
                    "random_win_rate": expected,
                    "edge_points": (
                        (actual - expected) * 100.0
                        if resolved
                        else np.nan
                    ),
                    "sum_pips": cell["pips_sum"],
                    "mean_win_pips": (
                        cell["win_pips_sum"] / cell["tp_wins"]
                        if cell["tp_wins"]
                        else np.nan
                    ),
                    "net_result_yen": cell["yen_sum"],
                    "normalized_lc_risk_yen": NORMALIZED_LC_RISK_YEN,
                    "avg_pips": (
                        cell["pips_sum"] / cell["filled"]
                        if cell["filled"]
                        else np.nan
                    ),
                }
            )
        return pd.DataFrame(rows)


def select_ahead_lines(
    peak_direction: int,
    current_price: float,
    upper_lines: list[dict[str, Any]],
    lower_lines: list[dict[str, Any]],
    pair: gene.CurrencyPair,
    profile: Any | None = None,
    entry_mode: str = "limit",
    average_range_pips: float | None = None,
    min_distance_a: float = 0.0,
    exclude_flipped_recent: bool = False,
) -> list[dict[str, Any]]:
    """Compatibility adapter to the shared resistance-breakout core."""
    return breakout_core.select_ahead_lines(
        peak_direction,
        current_price,
        upper_lines,
        lower_lines,
        pair,
        profile,
        entry_mode,
        average_range_pips,
        min_distance_a,
        exclude_flipped_recent,
    )


def _build_event_decision_context(
    m5: pd.DataFrame,
    index: int,
    pair_name: str,
    h1: pd.DataFrame | None,
    peak_history_bars: int,
) -> Any:
    """Build the shared M5-trigger/H1 context once for one decision time."""
    decision_time = pd.Timestamp(m5.iloc[index]["time_jp_dt"])
    source_completed = m5.iloc[
        max(0, index - peak_history_bars) : index
    ].copy()
    if len(source_completed) < LINE_HISTORY_BARS:
        raise ValueError("insufficient_m5_for_decision_context")
    if (source_completed["time_jp_dt"] >= decision_time).any():
        raise ValueError("future_m5_in_decision_context")
    source_price = float(source_completed.iloc[-1]["close"])
    return CandleAnalysis.build_decision_context_from_frames(
        pair_name,
        decision_time,
        source_completed,
        h1,
        current_price=source_price,
        current_price_source="inspection_m5",
        mode="inspection",
        require_complete_flags=False,
        m5_history=peak_history_bars,
        h1_history=max(H1_HISTORY_BARS, peak_history_bars),
        # PeaksClassの足ごとの既定本数で切られないよう、
        # 検証で指定したピーク窓をM5/H1の両方へ適用する。
        peaks_class_factory=functools.partial(
            PeaksClass,
            analysis_num=peak_history_bars,
        ),
    )


def _decision_context_bundle(
    decision_context: Any,
    line_timeframe: str,
) -> CandleTimeframeBundle:
    """Expose the causal M5/H1 source as one explicit timeframe bundle."""
    if line_timeframe == "M5":
        original_df_r = decision_context.m5_original_df_r
        completed_df_r = decision_context.m5_completed_df_r
        peaks = decision_context.m5_peaks_class
    elif line_timeframe == "H1":
        original_df_r = decision_context.h1_original_df_r
        completed_df_r = decision_context.h1_completed_df_r
        peaks = decision_context.h1_peaks_class
    else:
        raise ValueError("decision context only provides M5 or H1")
    if original_df_r is None or completed_df_r is None or peaks is None:
        raise ValueError(line_timeframe + " decision context is unavailable")
    return CandleTimeframeBundle(
        timeframe=line_timeframe,
        duration=pd.Timedelta(minutes=TIMEFRAME_MINUTES[line_timeframe]),
        original_df_r=original_df_r,
        completed_df_r=completed_df_r,
        peaks_class=peaks,
        source_granularity=line_timeframe,
    )


def _native_m30_bundle(
    m30: pd.DataFrame | None,
    decision_time: pd.Timestamp,
    current_price: float,
    pair: gene.CurrencyPair,
    peak_history_bars: int,
) -> CandleTimeframeBundle:
    """Build M30 Peaks from native M30 candles completed by decision time."""
    if m30 is None:
        raise ValueError("native_m30_frame_is_required")
    original_df_r = CandleAnalysis.normalize_original_df_r(
        m30,
        decision_time,
        "m30_original_df_r",
    )
    completed_df_r = CandleAnalysis.select_completed_df_r(
        original_df_r,
        decision_time,
        pd.Timedelta(minutes=30),
        limit=peak_history_bars,
        require_complete_flag=False,
    )
    # native M30 と名付けただけのM5データを通さない。共通品質検査は
    # 30分間隔・判断境界・必要本数を確認し、営業時間内欠損が50%未満なら
    # 取得済みの完成足で続行する。
    completed_df_r = CandleAnalysis.validate_completed_history_for_context(
        completed_df_r,
        decision_time,
        pd.Timedelta(minutes=30),
        peak_history_bars,
        "M30",
        latest_boundary="M30",
        stale_is_integrity=True,
    )
    if (
        completed_df_r["time_jp_dt"] + pd.Timedelta(minutes=30)
        > decision_time
    ).any():
        raise ValueError("future_m30_in_line_snapshot")
    with contextlib.redirect_stdout(io.StringIO()):
        peaks = PeaksClass(
            original_df_r,
            "M30",
            current_price,
            pair,
            completed_df_r=completed_df_r,
            decision_time=decision_time,
            source_granularity="M30",
            analysis_num=peak_history_bars,
        )
    if not peaks.peaks_original:
        raise ValueError("no_M30_peak")
    return CandleTimeframeBundle(
        timeframe="M30",
        duration=pd.Timedelta(minutes=30),
        original_df_r=original_df_r,
        completed_df_r=completed_df_r,
        peaks_class=peaks,
        source_granularity="M30",
    )


def _timeframe_average_range_pips(
    completed_df_r: pd.DataFrame,
    pair: gene.CurrencyPair,
    lookback: int = TP_LOOKBACK,
) -> float | None:
    """Compatibility adapter for the shared newest-first A calculation."""
    return breakout_core.average_range_pips_from_completed_df_r(
        completed_df_r,
        pair,
        lookback,
    )


def _detect_m5_stair_once(
    decision_context: Any,
    *args: Any,
    **kwargs: Any,
) -> dict[str, Any]:
    """Reuse M5 stair evidence across the three line-timeframe rebuilds."""
    cached = getattr(
        decision_context,
        "_resistance_sweep_m5_stair_context",
        None,
    )
    if cached is None:
        cached = detect_m5_stair_trend(*args, **kwargs)
        setattr(
            decision_context,
            "_resistance_sweep_m5_stair_context",
            cached,
        )
    return cached


def rebuild_candidates_at(
    m5: pd.DataFrame,
    index: int,
    pair_name: str,
    h1: pd.DataFrame | None = None,
    m30: pd.DataFrame | None = None,
    h1_stair_cache: dict[pd.Timestamp, dict[str, Any]] | None = None,
    decision_context: Any | None = None,
    entry_mode: str = "limit",
    enforce_peak_strength_filter: bool = False,
    separate_line_directions: bool = False,
    min_line_peak_count: int = 1,
    group_threshold_a: float | None = None,
    min_line_total_strength: float = 0.0,
    min_line_direction_ratio: float = 0.0,
    min_distance_a: float = 0.0,
    exclude_flipped_recent: bool = False,
    line_history_bars: int = LINE_HISTORY_BARS,
    peak_history_bars: int = PEAK_HISTORY_BARS,
    line_timeframe: str = "M5",
) -> dict[str, Any]:
    """Recreate one timeframe's lines at an M5 count-2 decision."""
    pair = gene.currency_pair(pair_name)
    line_timeframe = str(line_timeframe).strip().upper()
    if line_timeframe not in LINE_TIMEFRAMES:
        raise ValueError("line_timeframe must be M5, M30 or H1")
    requested_decision_time = pd.Timestamp(m5.iloc[index]["time_jp_dt"])
    if decision_context is None:
        decision_context = _build_event_decision_context(
            m5,
            index,
            pair_name,
            h1,
            peak_history_bars,
        )
    context_pair = str(getattr(decision_context, "pair_name", "")).upper()
    if context_pair != str(pair_name).upper():
        raise ValueError("decision_context_pair_mismatch")
    decision_time = pd.Timestamp(decision_context.decision_time)
    if decision_time != requested_decision_time:
        raise ValueError("decision_context_time_mismatch")

    m5_completed_df_r = decision_context.m5_completed_df_r
    current_price = float(decision_context.current_price)
    m5_peaks = decision_context.m5_peaks_class
    if not m5_peaks.peaks_original:
        raise ValueError("no_M5_peak")
    newest_peak = m5_peaks.peaks_original[0]
    if int(newest_peak.get("count", 0)) != 2:
        raise ValueError(
            "count2_prefilter_mismatch:"
            + str(newest_peak.get("count"))
        )
    peak_direction = int(newest_peak["direction"])

    if line_timeframe == "M30":
        line_bundle = _native_m30_bundle(
            m30,
            decision_time,
            current_price,
            pair,
            peak_history_bars,
        )
    else:
        line_bundle = _decision_context_bundle(
            decision_context,
            line_timeframe,
        )
    if not line_bundle.is_native:
        raise ValueError(
            line_timeframe
            + "_line_source_is_not_native:"
            + str(line_bundle.source_granularity)
        )
    if len(line_bundle.completed_df_r) < line_history_bars:
        raise ValueError(
            "insufficient_"
            + line_timeframe
            + "_for_line_rebuild:"
            + str(len(line_bundle.completed_df_r))
            + "<"
            + str(line_history_bars)
        )
    line_peaks = line_bundle.peaks_class
    if not line_peaks.peaks_original:
        raise ValueError("no_" + line_timeframe + "_peak")
    completed = line_bundle.completed_df_r.iloc[::-1].reset_index(drop=True)

    h1_completed_df_r = decision_context.h1_completed_df_r
    h1_peaks = decision_context.h1_peaks_class
    if h1_completed_df_r is None:
        h1_cache_key = None
        h1_stair_context = None
    else:
        if len(h1_completed_df_r) < 60:
            raise ValueError("insufficient_h1_for_stair_rebuild")
        if (
            h1_completed_df_r["time_jp_dt"] + pd.Timedelta(hours=1)
            > decision_time
        ).any():
            raise ValueError("future_h1_in_stair_snapshot")
        h1_cache_key = pd.Timestamp(
            h1_completed_df_r.iloc[0]["time_jp_dt"]
        )
        h1_stair_context = (
            h1_stair_cache.get(h1_cache_key)
            if h1_stair_cache is not None
            else None
        )

    analysis = SimpleNamespace(
        pair=pair_name,
        analysis_mode="inspection",
        current_price=current_price,
        decision_time=decision_time,
    )
    with contextlib.redirect_stdout(io.StringIO()):
        # Aはラインを作る時間足そのものの直前完成足から算出する。
        # M30/H1にM5の中身を渡し、閾値だけ変える状態にはしない。
        average_range_pips = _timeframe_average_range_pips(
            line_bundle.completed_df_r,
            pair,
        )
        group_threshold_pips = (
            group_threshold_a * average_range_pips
            if group_threshold_a is not None and average_range_pips
            else None
        )
        line_class = LineStrengthCal(
            analysis,
            line_timeframe.lower(),
            line_history_bars,
            enforce_peak_strength_filter=enforce_peak_strength_filter,
            separate_line_directions=separate_line_directions,
            min_line_peak_count=min_line_peak_count,
            group_threshold_pips=group_threshold_pips,
            min_line_total_strength=min_line_total_strength,
            min_line_direction_ratio=min_line_direction_ratio,
            timeframe_bundle=line_bundle,
        )
    profile = getattr(
        decision_context,
        "_resistance_sweep_profile",
        None,
    )
    if profile is None:
        profile = line_strategy_profile(pair_name)
        setattr(decision_context, "_resistance_sweep_profile", profile)
    stair_context = _detect_m5_stair_once(
        decision_context,
        m5_peaks.peaks_original,
        pair,
        m5_completed_df_r,
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
            h1_completed_df_r,
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
    h1_pair_shape = decision_context.h1_shape_for_direction(peak_direction)
    candidates = select_ahead_lines(
        peak_direction,
        current_price,
        line_class.upper_lines,
        line_class.lower_lines,
        pair,
        profile if line_timeframe == "M5" else None,
        entry_mode=entry_mode,
        average_range_pips=average_range_pips,
        min_distance_a=min_distance_a,
        exclude_flipped_recent=exclude_flipped_recent,
    )
    for candidate in candidates:
        candidate["m5_stair_context"] = stair_context
        candidate["h1_stair_context"] = h1_stair_context
        candidate["line_timeframe"] = line_timeframe
    rsi_info = dict(decision_context.rsi_info)
    return {
        "decision_time": decision_time,
        "current_price": current_price,
        "newest_peak": newest_peak,
        "m5_peaks": m5_peaks.peaks_original,
        "line_peaks": line_peaks.peaks_original,
        "line_timeframe": line_timeframe,
        "line_source_granularity": str(
            line_bundle.source_granularity
        ).upper(),
        "line_history_bars": int(line_history_bars),
        "line_history_minutes": int(
            line_history_bars * TIMEFRAME_MINUTES[line_timeframe]
        ),
        "peak_history_bars": int(peak_history_bars),
        "line_average_range_pips": average_range_pips,
        "group_threshold_pips": float(line_class.threshold),
        "peak_direction": peak_direction,
        "completed_history": completed,
        "candidates": candidates,
        "profile": profile,
        "rsi_info": rsi_info,
        "stair_context": stair_context,
        "h1_stair_context": h1_stair_context,
        "h1_pair_shape_context": h1_pair_shape,
        "m5_foot_count2_shape_context": (
            decision_context.m5_foot_count2_shape
        ),
        "decision_context": decision_context,
    }


_PRODUCTION_EQUIVALENCE_FIELDS = (
    "decision_time",
    "pair",
    "source",
    "owner_tag",
    "resistance_breakout_version",
    "resistance_breakout_core_version",
    "resistance_breakout_policy_id",
    "line_timeframe",
    "line_source_granularity",
    "line_history_bars",
    "peak_history_bars",
    "configured_peak_history_bars",
    "candidate_rank",
    "distance_rank",
    "line_side",
    "direction",
    "line_price",
    "line_raw_median_price",
    "line_core_price",
    "line_peak_signature",
    "distance_pips",
    "line_peaks_count",
    "line_core_peak_count",
    "line_total_strength",
    "line_ave_strength",
    "line_core_total_strength",
    "line_direction_ratio",
    "line_is_flipped",
    "line_newest_peak_time",
    "line_oldest_peak_time",
    "line_average_range_pips",
    "group_threshold_pips",
    "trigger_foot_count",
    "trigger_peak_direction",
    "trigger_peak_time",
    "m5_average_range_pips",
    "entry_mode",
    "type",
    "target_price",
    "resistance_breakout_trigger_price",
    "tp_price",
    "lc_price",
    "tp_pips",
    "lc_pips",
    "stop_offset_pips",
    "assumed_stop_slippage_pips",
    "priority",
    "order_timeout_min",
    "trade_timeout_min",
    "order_permission",
)

_PRODUCTION_EQUIVALENCE_TIME_FIELDS = {
    "decision_time",
    "line_newest_peak_time",
    "line_oldest_peak_time",
    "trigger_peak_time",
}

_PRODUCTION_EQUIVALENCE_PRICE_FIELDS = {
    "line_price",
    "line_raw_median_price",
    "line_core_price",
    "target_price",
    "resistance_breakout_trigger_price",
    "tp_price",
    "lc_price",
}


def _causal_frame_for_equivalence(
    frame: pd.DataFrame,
    decision_time: pd.Timestamp,
    label: str,
    row_limit: int | None = None,
) -> pd.DataFrame:
    """Return source rows whose candle start is not after the decision."""
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        raise ValueError(label + " frame is empty")
    decision = CandleAnalysis.normalize_decision_time(decision_time)
    times = CandleAnalysis._frame_times(frame)
    causal_mask = times <= decision
    causal_positions = np.flatnonzero(causal_mask.to_numpy(dtype=bool))
    if not causal_positions.size:
        raise ValueError(label + " has no causal rows")
    if row_limit is not None:
        limit = max(int(row_limit), 1)
        causal_times = times.iloc[causal_positions]
        if len(causal_positions) > limit:
            if causal_times.is_monotonic_increasing:
                causal_positions = causal_positions[-limit:]
            elif causal_times.is_monotonic_decreasing:
                causal_positions = causal_positions[:limit]
            else:
                chronological_order = np.argsort(
                    causal_times.to_numpy(dtype="datetime64[ns]"),
                    kind="stable",
                )
                causal_positions = causal_positions[
                    chronological_order[-limit:]
                ]
    causal = frame.iloc[causal_positions].copy()
    causal["time_jp_dt"] = times.iloc[causal_positions].to_numpy()
    causal.sort_values("time_jp_dt", kind="stable", inplace=True)
    causal.reset_index(drop=True, inplace=True)
    return causal


def _build_equivalence_candle_analysis(
    pair_name: str,
    decision_time: pd.Timestamp,
    m5: pd.DataFrame,
    m30: pd.DataFrame,
    h1: pd.DataFrame,
) -> CandleAnalysis:
    """Build the production CandleAnalysis path without OANDA or Discord."""
    decision = CandleAnalysis.normalize_decision_time(decision_time)
    # 2年分をサンプルごとに複製しない。形成足を含み得る1本を足しても、
    # 本番Peaksが読む完成足数は完全に保持される。
    causal_m5 = _causal_frame_for_equivalence(
        m5,
        decision,
        "M5",
        PRODUCTION_M5_PEAK_HISTORY_BARS + 1,
    )
    causal_m30 = _causal_frame_for_equivalence(
        m30,
        decision,
        "M30",
        PRODUCTION_M30_PEAK_HISTORY_BARS + 1,
    )
    causal_h1 = _causal_frame_for_equivalence(
        h1,
        decision,
        "H1",
        PRODUCTION_H1_PEAK_HISTORY_BARS + 1,
    )
    latest_completed_m5 = CandleAnalysis.select_completed_df_r(
        causal_m5,
        decision,
        pd.Timedelta(minutes=5),
        limit=1,
        require_complete_flag=False,
    )
    current_price = float(latest_completed_m5.iloc[0]["close"])
    with contextlib.redirect_stdout(io.StringIO()):
        return CandleAnalysis(
            None,
            pair_name,
            target_time_jp=decision.to_pydatetime(),
            m5_original_df_r=causal_m5,
            h1_original_df_r=causal_h1,
            m30_original_df_r=causal_m30,
            s5_original_df_r=None,
            current_price=current_price,
            current_price_source="equivalence_latest_completed_m5",
            decision_time=decision,
        )


def _eligible_production_equivalence_indices(
    m5: pd.DataFrame,
    m30: pd.DataFrame,
    h1: pd.DataFrame,
    decision_indices: list[int] | tuple[int, ...] | np.ndarray | pd.Series,
) -> list[int]:
    if any(
        not isinstance(frame, pd.DataFrame) or frame.empty
        for frame in (m5, m30, h1)
    ):
        return []
    m5_times = np.sort(
        CandleAnalysis._frame_times(m5).to_numpy(dtype="datetime64[ns]")
    )
    m30_times = np.sort(
        CandleAnalysis._frame_times(m30).to_numpy(dtype="datetime64[ns]")
    )
    h1_times = np.sort(
        CandleAnalysis._frame_times(h1).to_numpy(dtype="datetime64[ns]")
    )

    def completed_count(times: np.ndarray, completed_start: pd.Timestamp) -> int:
        return int(np.searchsorted(
            times,
            np.datetime64(completed_start, "ns"),
            side="right",
        ))

    eligible = []
    for raw_index in decision_indices:
        index = int(raw_index)
        if index < 0 or index >= len(m5):
            raise IndexError("equivalence decision index is out of range")
        decision_time = CandleAnalysis.normalize_decision_time(
            m5.iloc[index]["time_jp_dt"]
        )
        if completed_count(
            m5_times,
            decision_time - pd.Timedelta(minutes=5),
        ) < PRODUCTION_M5_PEAK_HISTORY_BARS:
            continue
        if completed_count(
            m30_times,
            decision_time - pd.Timedelta(minutes=30),
        ) < PRODUCTION_M30_PEAK_HISTORY_BARS:
            continue
        if completed_count(
            h1_times,
            decision_time - pd.Timedelta(hours=1),
        ) < PRODUCTION_H1_PEAK_HISTORY_BARS:
            continue
        eligible.append(index)
    return eligible


def _is_missing_equivalence_value(value: Any) -> bool:
    if value is None:
        return True
    try:
        missing = pd.isna(value)
    except (TypeError, ValueError):
        return False
    return bool(missing) if isinstance(missing, (bool, np.bool_)) else False


def _assert_equivalence_value(
    *,
    field: str,
    expected: Any,
    actual: Any,
    pair: gene.CurrencyPair,
    decision_time: pd.Timestamp,
    timeframe: str = "context",
) -> None:
    expected_missing = _is_missing_equivalence_value(expected)
    actual_missing = _is_missing_equivalence_value(actual)
    if expected_missing or actual_missing:
        if expected_missing and actual_missing:
            return
        raise ValueError(
            "resistance breakout production equivalence mismatch: "
            f"decision={decision_time}, timeframe={timeframe}, field={field}, "
            f"sweep={expected!r}, production={actual!r}"
        )
    if field in _PRODUCTION_EQUIVALENCE_TIME_FIELDS:
        matches = pd.Timestamp(expected) == pd.Timestamp(actual)
    elif isinstance(expected, (bool, np.bool_)) or isinstance(
        actual,
        (bool, np.bool_),
    ):
        matches = bool(expected) is bool(actual)
    elif isinstance(expected, (int, float, np.integer, np.floating)) and isinstance(
        actual,
        (int, float, np.integer, np.floating),
    ):
        absolute_tolerance = (
            pair.pip_value / 10
            if field in _PRODUCTION_EQUIVALENCE_PRICE_FIELDS
            else 1e-9
        )
        matches = math.isclose(
            float(expected),
            float(actual),
            rel_tol=1e-9,
            abs_tol=absolute_tolerance,
        )
    else:
        matches = expected == actual
    if not matches:
        raise ValueError(
            "resistance breakout production equivalence mismatch: "
            f"decision={decision_time}, timeframe={timeframe}, field={field}, "
            f"sweep={expected!r}, production={actual!r}"
        )


def _assert_no_future_completed_rows(
    frame: pd.DataFrame,
    decision_time: pd.Timestamp,
    duration: pd.Timedelta,
    label: str,
) -> None:
    times = CandleAnalysis._frame_times(frame)
    if (times + duration > decision_time).any():
        raise ValueError(
            label + " contains a forming or future candle in equivalence check"
        )


def _sweep_candidate_as_production_plan(
    *,
    pair_name: str,
    decision_time: pd.Timestamp,
    rebuilt: dict[str, Any],
    candidate: dict[str, Any],
    target: dict[str, Any],
    trigger: dict[str, Any],
    policy: breakout_core.ResistanceBreakoutPolicy,
) -> dict[str, Any]:
    pair = gene.currency_pair(pair_name)
    line = candidate["line"]
    levels = breakout_core.build_stop_order_levels(
        candidate["line_price"],
        candidate["trade_direction"],
        target["tp_pips"],
        target["lc_pips"],
        pair,
        policy.stop_offset_pips,
    )
    native_direction = 1 if candidate["line_side"] == "upper" else -1
    return {
        "decision_time": decision_time,
        "pair": pair_name,
        "source": "resistance_breakout",
        "owner_tag": breakout_core.OWNER_TAG,
        "resistance_breakout_version": breakout_core.ADAPTER_VERSION,
        "resistance_breakout_core_version": breakout_core.CORE_VERSION,
        "resistance_breakout_policy_id": policy.policy_id,
        "line_timeframe": rebuilt["line_timeframe"],
        "line_source_granularity": rebuilt["line_source_granularity"],
        "line_history_bars": int(rebuilt["line_history_bars"]),
        "peak_history_bars": int(rebuilt["peak_history_bars"]),
        "configured_peak_history_bars": int(policy.peak_history_bars),
        "candidate_rank": int(candidate["candidate_rank"]),
        "distance_rank": int(candidate["distance_rank"]),
        "line_side": candidate["line_side"],
        "direction": int(candidate["trade_direction"]),
        "line_price": levels.line_price,
        "line_raw_median_price": candidate.get("raw_line_price"),
        "line_core_price": line.get("core_median_price"),
        "line_peak_signature": breakout_core.line_peak_signature(line),
        "distance_pips": float(candidate["distance_pips"]),
        "line_peaks_count": int(line.get("count") or 0),
        "line_core_peak_count": int(line.get("core_count") or 0),
        "line_total_strength": line.get("total_strength"),
        "line_ave_strength": line.get("ave_strength"),
        "line_core_total_strength": line.get("core_total_strength"),
        "line_direction_ratio": breakout_core.native_direction_ratio(
            line,
            native_direction,
        ),
        "line_is_flipped": line.get("is_flipped_line"),
        "line_newest_peak_time": line.get("newest_time"),
        "line_oldest_peak_time": line.get("oldest_time"),
        "line_average_range_pips": float(
            rebuilt["line_average_range_pips"]
        ),
        "group_threshold_pips": float(rebuilt["group_threshold_pips"]),
        "trigger_foot_count": trigger["trigger_foot_count"],
        "trigger_peak_direction": trigger["peak_direction"],
        "trigger_peak_time": trigger["peak_time"],
        "m5_average_range_pips": float(
            target["recent_m5_avg_range_pips"]
        ),
        "entry_mode": "stop",
        "type": "STOP",
        "target_price": levels.trigger_price,
        "resistance_breakout_trigger_price": levels.trigger_price,
        "tp_price": levels.tp_price,
        "lc_price": levels.lc_price,
        "tp_pips": levels.tp_pips,
        "lc_pips": levels.lc_pips,
        "stop_offset_pips": levels.stop_offset_pips,
        "assumed_stop_slippage_pips": float(
            policy.assumed_stop_slippage_pips
        ),
        "priority": int(policy.priority),
        "order_timeout_min": int(policy.order_timeout_min),
        "trade_timeout_min": int(policy.trade_timeout_min),
        "order_permission": breakout_core.ORDER_PERMISSION,
    }


def validate_production_context_equivalence(
    pair_name: str,
    m5: pd.DataFrame,
    m30: pd.DataFrame,
    h1: pd.DataFrame,
    decision_indices: list[int] | tuple[int, ...] | np.ndarray | pd.Series,
    sample_count: int = 30,
    *,
    policy: breakout_core.ResistanceBreakoutPolicy | None = None,
    require_candidates: bool = True,
) -> dict[str, Any]:
    """Fail fast unless sweep candidates equal production trial orders.

    The ordinary sweep deliberately stores broad candidates.  This check does
    not compare those broad defaults.  It rebuilds a separate M5/M30 baseline
    from the fixed live policy, then compares it with
    ``fResistanceBreakoutAnalysis.build_orders_for_decision``.  Current price
    is fixed to the latest completed M5 close on both paths; live quote drift is
    outside this offline context-equivalence check.
    """
    import fResistanceBreakoutAnalysis as live_breakout

    active_policy = (
        live_breakout.LIVE_TRIAL_POLICY_V1
        if policy is None
        else policy
    )
    eligible_indices = _eligible_production_equivalence_indices(
        m5,
        m30,
        h1,
        decision_indices,
    )
    if not eligible_indices:
        raise ValueError(
            "no decision has enough M5/M30/H1 history for production equivalence"
        )
    requested_samples = max(int(sample_count), 1)
    sample_positions = np.unique(np.linspace(
        0,
        len(eligible_indices) - 1,
        min(requested_samples, len(eligible_indices)),
        dtype=int,
    ))
    pair = gene.currency_pair(pair_name)
    checked_decisions = 0
    checked_candidates = 0
    checked_candidates_by_timeframe = {
        timeframe: 0 for timeframe in active_policy.timeframes
    }
    peak_history_by_timeframe: dict[str, int] = {}

    for sample_position in sample_positions:
        index = eligible_indices[int(sample_position)]
        decision_time = CandleAnalysis.normalize_decision_time(
            m5.iloc[index]["time_jp_dt"]
        )
        production_ca = _build_equivalence_candle_analysis(
            pair_name,
            decision_time,
            m5,
            m30,
            h1,
        )
        production_context = production_ca.require_basic_analysis()
        production_m5_bundle = production_ca.get_timeframe_bundle(
            "M5",
            require_native=True,
        )
        m5_peak_history = int(getattr(
            production_m5_bundle.peaks_class,
            "analysis_num",
            PRODUCTION_M5_PEAK_HISTORY_BARS,
        ))
        sweep_context = _build_event_decision_context(
            m5,
            index,
            pair_name,
            h1,
            m5_peak_history,
        )

        _assert_equivalence_value(
            field="decision_time",
            expected=sweep_context.decision_time,
            actual=production_context.decision_time,
            pair=pair,
            decision_time=decision_time,
        )
        _assert_equivalence_value(
            field="current_price",
            expected=sweep_context.current_price,
            actual=production_context.current_price,
            pair=pair,
            decision_time=decision_time,
        )
        _assert_no_future_completed_rows(
            sweep_context.m5_completed_df_r,
            decision_time,
            pd.Timedelta(minutes=5),
            "sweep M5",
        )
        _assert_no_future_completed_rows(
            production_context.m5_completed_df_r,
            decision_time,
            pd.Timedelta(minutes=5),
            "production M5",
        )

        sweep_trigger = breakout_core.evaluate_breakout_trigger(
            sweep_context.newest_m5_peak,
            active_policy.trigger_foot_count,
        )
        production_trigger = breakout_core.evaluate_breakout_trigger(
            production_context.newest_m5_peak,
            active_policy.trigger_foot_count,
        )
        for field in (
            "trigger_valid",
            "trigger_skip_reason",
            "trigger_foot_count",
            "peak_direction",
            "peak_time",
        ):
            compare_field = (
                "trigger_peak_time" if field == "peak_time" else field
            )
            _assert_equivalence_value(
                field=compare_field,
                expected=sweep_trigger.get(field),
                actual=production_trigger.get(field),
                pair=pair,
                decision_time=decision_time,
            )

        sweep_target = target_parameters(
            m5,
            index,
            pair,
            active_policy.target_lookback,
            active_policy.target_multiplier,
            active_policy.rr,
        )
        production_target = breakout_core.target_parameters(
            production_context.m5_completed_df_r,
            decision_time,
            pair,
            active_policy.target_lookback,
            active_policy.target_multiplier,
            active_policy.rr,
        )
        for field in (
            "target_valid",
            "target_skip_reason",
            "recent_m5_avg_range_pips",
            "tp_pips",
            "lc_pips",
        ):
            _assert_equivalence_value(
                field=field,
                expected=sweep_target.get(field),
                actual=production_target.get(field),
                pair=pair,
                decision_time=decision_time,
            )

        expected_plans: list[dict[str, Any]] = []
        target_is_executable = bool(
            sweep_trigger["trigger_valid"]
            and sweep_target["target_valid"]
            and breakout_core.live_target_is_wide_enough(
                sweep_target["tp_pips"],
                active_policy.spread_pips,
                active_policy.min_tp_spread_ratio,
            )
        )
        if target_is_executable:
            for timeframe in active_policy.timeframes:
                production_bundle = production_ca.get_timeframe_bundle(
                    timeframe,
                    require_native=True,
                )
                actual_peak_history = int(getattr(
                    production_bundle.peaks_class,
                    "analysis_num",
                    active_policy.peak_history_bars,
                ))
                peak_history_contract = {
                    "M5": PRODUCTION_M5_PEAK_HISTORY_BARS,
                    "M30": PRODUCTION_M30_PEAK_HISTORY_BARS,
                    "H1": PRODUCTION_H1_PEAK_HISTORY_BARS,
                }
                required_peak_history = peak_history_contract[timeframe]
                if actual_peak_history != required_peak_history:
                    raise ValueError(
                        "resistance breakout production equivalence mismatch: "
                        f"decision={decision_time}, timeframe={timeframe}, "
                        "field=peak_history_contract, "
                        f"expected={required_peak_history}, "
                        f"production={actual_peak_history}"
                    )
                peak_history_by_timeframe[timeframe] = actual_peak_history
                _assert_no_future_completed_rows(
                    production_bundle.completed_df_r,
                    decision_time,
                    production_bundle.duration,
                    "production " + timeframe,
                )
                rebuilt = rebuild_candidates_at(
                    m5,
                    index,
                    pair_name,
                    m30=m30,
                    h1=h1,
                    decision_context=sweep_context,
                    entry_mode="stop",
                    enforce_peak_strength_filter=(
                        active_policy.enforce_peak_strength_filter
                    ),
                    separate_line_directions=False,
                    min_line_peak_count=active_policy.min_line_peak_count,
                    group_threshold_a=active_policy.group_threshold_a,
                    min_line_total_strength=(
                        active_policy.min_line_total_strength
                    ),
                    min_line_direction_ratio=(
                        active_policy.min_line_direction_ratio
                    ),
                    min_distance_a=active_policy.min_distance_a,
                    exclude_flipped_recent=(
                        active_policy.exclude_flipped_recent
                    ),
                    line_history_bars=active_policy.line_history_bars,
                    peak_history_bars=actual_peak_history,
                    line_timeframe=timeframe,
                )
                for candidate in rebuilt["candidates"]:
                    expected_plans.append(
                        _sweep_candidate_as_production_plan(
                            pair_name=pair_name,
                            decision_time=decision_time,
                            rebuilt=rebuilt,
                            candidate=candidate,
                            target=sweep_target,
                            trigger=sweep_trigger,
                            policy=active_policy,
                        )
                    )
                    checked_candidates_by_timeframe[timeframe] += 1

        with contextlib.redirect_stdout(io.StringIO()):
            production_orders = live_breakout.build_orders_for_decision(
                production_ca,
                mode="inspection",
                policy=active_policy,
            )
        production_plans = [
            dict(order.exe_order_plan)
            for order in production_orders
        ]
        timeframe_order = {
            timeframe: position
            for position, timeframe in enumerate(active_policy.timeframes)
        }
        sort_key = lambda row: (
            timeframe_order.get(str(row.get("line_timeframe")).upper(), 999),
            int(row.get("candidate_rank") or 0),
        )
        expected_plans.sort(key=sort_key)
        production_plans.sort(key=sort_key)
        if len(expected_plans) != len(production_plans):
            raise ValueError(
                "resistance breakout production equivalence mismatch: "
                f"decision={decision_time}, field=candidate_count, "
                f"sweep={len(expected_plans)}, "
                f"production={len(production_plans)}"
            )
        for expected, actual in zip(expected_plans, production_plans):
            timeframe = str(expected["line_timeframe"]).upper()
            for field in _PRODUCTION_EQUIVALENCE_FIELDS:
                _assert_equivalence_value(
                    field=field,
                    expected=expected.get(field),
                    actual=actual.get(field),
                    pair=pair,
                    decision_time=decision_time,
                    timeframe=timeframe,
                )
        checked_decisions += 1
        checked_candidates += len(expected_plans)

    missing_candidate_timeframes = [
        timeframe
        for timeframe, count in checked_candidates_by_timeframe.items()
        if count < 1
    ]
    if require_candidates and missing_candidate_timeframes:
        raise ValueError(
            "production equivalence compared only empty candidate sets for: "
            + ", ".join(missing_candidate_timeframes)
        )
    return {
        "checked_decisions": checked_decisions,
        "checked_candidates": checked_candidates,
        "checked_candidates_by_timeframe": (
            checked_candidates_by_timeframe
        ),
        "candidate_evidence_by_timeframe": {
            timeframe: (
                "candidate_compared" if count > 0 else "empty_only"
            )
            for timeframe, count in checked_candidates_by_timeframe.items()
        },
        "fully_exercised": not missing_candidate_timeframes,
        "mismatches": 0,
        "core_version": breakout_core.CORE_VERSION,
        "policy_id": active_policy.policy_id,
        "timeframes": tuple(active_policy.timeframes),
        "peak_history_bars_by_timeframe": peak_history_by_timeframe,
        "current_price_source": "latest_completed_m5_close",
        "sweep_builder": "count2_resistance_sweep.rebuild_candidates_at",
        "production_builder": (
            "fResistanceBreakoutAnalysis.build_orders_for_decision"
        ),
    }


def _parse_time(value: Any) -> pd.Timestamp:
    if value is None or value == "":
        return pd.NaT
    return pd.to_datetime(value, format=TIME_FORMAT, errors="coerce")


def _episode_summary(
    mask: pd.Series,
    times: pd.Series,
    candle_minutes: int = 5,
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
            or timestamp - previous_time > pd.Timedelta(
                minutes=candle_minutes
            )
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
    candle_minutes: int = 5,
    include_predict_reversal_context: bool = True,
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
    if include_predict_reversal_context:
        # この特徴量はM5 PredictReversal profile専用。
        # M30/H1の抵抗線にM5前提の値を横流ししない。
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
        candle_minutes,
    )
    body_count, body_last = _episode_summary(
        body_touch,
        history["time_jp_dt"],
        candle_minutes,
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
        return candle_gap_is_expected_closed(
            pd.Timestamp(previous_time),
            pd.Timestamp(next_time),
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
        approach_side: int | None = None,
        entry_mode: str = "limit",
        stop_offset_pips: float = 0.0,
        stop_slippage_pips: float = 0.0,
    ) -> dict[str, Any]:
        """ラインを起点にした一件の注文を、S5の値動きで判定する。

        ``approach_side`` は「価格がどちらへ動けば注文が起動するか」を表す。
        上側のラインなら +1（上昇して届く）、下側なら -1。逆張り（limit）では
        注文方向と必ず逆向きになるため省略でき、その場合は従来どおり
        ``-direction`` を使う。ブレイク（stop）では注文方向と同じ向きになる
        ので、両者を分けて渡す必要がある。

        ``entry_mode`` が ``"stop"`` のときは、ラインから
        ``stop_offset_pips`` だけ先に置いた逆指値が起動し、成行で約定する。
        指値と違って有利な価格は保証されないので、``stop_slippage_pips`` を
        不利側へ足した価格を建値とする。抜けた直後は値動きが速く、ここを
        0 にすると実運用より良い結果が出る。

        中身は ``inspect_targets`` の一件版。判定の実体を一箇所に保つため、
        こちらは薄い呼び出しにしてある。
        """
        results = self.inspect_targets(
            decision_time=decision_time,
            expiry_time=expiry_time,
            direction=direction,
            line_price=line_price,
            targets=((float(tp_pips), float(lc_pips)),),
            horizon_minutes=horizon_minutes,
            spread_pips=spread_pips,
            approach_side=approach_side,
            entry_mode=entry_mode,
            stop_offset_pips=stop_offset_pips,
            stop_slippage_pips=stop_slippage_pips,
        )
        return results[0]

    def inspect_targets(
        self,
        decision_time: pd.Timestamp,
        expiry_time: pd.Timestamp,
        direction: int,
        line_price: float,
        targets,
        horizon_minutes: int = HORIZON_MINUTES,
        spread_pips: float = SPREAD_PIPS,
        approach_side: int | None = None,
        entry_mode: str = "limit",
        stop_offset_pips: float = 0.0,
        stop_slippage_pips: float = 0.0,
    ) -> list[dict[str, Any]]:
        """同じ約定に対して、複数の利確・損切り幅をまとめて判定する。

        ``targets`` は ``(tp_pips, lc_pips)`` の並び。約定の探索と保有期間の
        S5切り出しは幅に依存しないので、一度だけ行って全ての幅で使い回す。
        TP/LCを総当たりしたいとき、幅の数だけ検証を回し直さずに済む。

        戻り値は ``targets`` と同じ順・同じ長さ。約定しなかった等の理由で
        個別判定に至らない場合は、全要素へ同じ内容を返す。
        """
        targets = list(targets)
        if not targets:
            raise ValueError("targets must not be empty")

        base = self._base()
        decision_time = pd.Timestamp(decision_time)
        expiry_time = pd.Timestamp(expiry_time)

        def _same_for_all(payload):
            return [dict(payload) for _ in targets]

        if expiry_time <= decision_time:
            return _same_for_all({
                **base,
                "path_skip_reason": "invalid_pending_interval",
                "candidate_result": "invalid_pending_interval",
            })
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
            return _same_for_all({
                **base,
                "path_skip_reason": "no_s5_during_pending",
                "candidate_result": "incomplete_pending",
            })
        pending_times = self.times[start_i:expiry_i]

        mode = str(entry_mode).lower()
        if mode not in ("limit", "stop"):
            raise ValueError("entry_mode must be 'limit' or 'stop'")
        side = (
            int(approach_side)
            if approach_side is not None
            else (
                int(direction)
                if mode == "stop"
                else -int(direction)
            )
        )
        if side not in (-1, 1):
            raise ValueError("approach_side must be -1 or 1")

        half_spread = self.pair.pips_to_price(spread_pips / 2)
        if mode == "stop":
            trigger_price = breakout_core.stop_trigger_price(
                line_price,
                side,
                self.pair,
                stop_offset_pips,
            )
        else:
            trigger_price = float(line_price)
        pending_high = self.highs[start_i:expiry_i]
        pending_low = self.lows[start_i:expiry_i]
        if mode == "stop" and side == -1:
            # SELL STOPはbid(mid-half spread)がtrigger以下で起動する。
            fill_touch = np.isfinite(pending_low) & (
                pending_low <= trigger_price + half_spread
            )
        elif mode == "stop":
            # BUY STOPはask(mid+half spread)がtrigger以上で起動する。
            fill_touch = np.isfinite(pending_high) & (
                pending_high >= trigger_price - half_spread
            )
        elif side == -1:
            # BUY LIMITはaskがtrigger以下で約定する。
            fill_touch = np.isfinite(pending_low) & (
                pending_low <= trigger_price - half_spread
            )
        else:
            # SELL LIMITはbidがtrigger以上で約定する。
            fill_touch = np.isfinite(pending_high) & (
                pending_high >= trigger_price + half_spread
            )
        reached = np.flatnonzero(fill_touch)
        if not reached.size:
            pending_complete = self._is_contiguous(
                pending_times,
                decision_time,
                expiry_time,
            )
            if not pending_complete:
                return _same_for_all({
                    **base,
                    "path_skip_reason": "incomplete_pending",
                    "candidate_result": "incomplete_pending",
                    "pending_s5_rows": len(pending_times),
                    "pending_path_complete": False,
                })
            return _same_for_all({
                **base,
                "has_s5_path": True,
                "pending_path_complete": True,
                "candidate_result": "not_filled",
                "trade_result": "not_filled",
                "pending_s5_rows": len(pending_times),
            })

        fill_offset = int(reached[0])
        fill_i = start_i + fill_offset
        fill_time = pd.Timestamp(self.times[fill_i])
        pending_complete = self._is_contiguous(
            pending_times[: fill_offset + 1],
            decision_time,
        )
        if not pending_complete:
            return _same_for_all({
                **base,
                "path_skip_reason": "incomplete_pending_before_fill",
                "candidate_result": "incomplete_pending",
                "pending_s5_rows": fill_offset + 1,
                "pending_path_complete": False,
            })
        open_mid = float(self.opens[fill_i])
        if mode == "stop":
            fill_at_open = (
                open_mid - half_spread <= trigger_price
                if side == -1
                else open_mid + half_spread >= trigger_price
            )
        else:
            fill_at_open = (
                open_mid + half_spread <= trigger_price
                if side == -1
                else open_mid - half_spread >= trigger_price
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
            return _same_for_all({
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
            })

        if mode == "stop":
            # 逆指値は成行約定なので、不利側へ滑った価格を建値にする。
            actual_entry = breakout_core.stop_actual_entry_price(
                trigger_price,
                direction,
                self.pair,
                stop_slippage_pips,
            )
        else:
            actual_entry = float(trigger_price)

        # ここまでが利確・損切り幅に依存しない部分。以降を幅ごとに繰り返す。
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

        metric_favorable_pips = favorable_pips.copy()
        if not fill_at_open:
            close_progress_pips = float(
                direction
                * (float(close_quote[0]) - actual_entry)
                / self.pair.pip_value
            )
            metric_favorable_pips[0] = max(0.0, close_progress_pips)

        entry_common = {
            **base,
            "has_s5_path": True,
            "pending_path_complete": bool(pending_complete),
            "filled": True,
            "fill_time": fill_time,
            "fill_delay_seconds": float(
                (fill_time - decision_time).total_seconds()
            ),
            "fill_at_bar_open": bool(fill_at_open),
            "actual_entry_price": actual_entry,
            "pending_s5_rows": fill_offset + 1,
            "position_s5_rows": len(path_times),
        }

        results = []
        for raw_tp, raw_lc in targets:
            tp_pips = float(raw_tp)
            lc_pips = float(raw_lc)
            # OANDAへ先に送るTP/LCは絶対価格。STOPが滑って約定しても
            # trigger基準の価格は移動しない。損益だけactual_entryから測る。
            order_price_reference = (
                trigger_price if mode == "stop" else actual_entry
            )
            tp_price = order_price_reference + direction * self.pair.pips_to_price(
                tp_pips
            )
            lc_price = order_price_reference - direction * self.pair.pips_to_price(
                lc_pips
            )
            if direction == 1:
                tp_touch = favorable_quote >= tp_price
                lc_touch = adverse_quote <= lc_price
                fill_close_confirms_tp = (
                    fill_at_open or close_quote[0] >= tp_price
                )
            else:
                tp_touch = favorable_quote <= tp_price
                lc_touch = adverse_quote >= lc_price
                fill_close_confirms_tp = (
                    fill_at_open or close_quote[0] <= tp_price
                )

            fill_bar_ambiguous = bool(
                tp_touch[0]
                and not lc_touch[0]
                and not fill_close_confirms_tp
            )
            hit_i = None
            if lc_touch[0] or (tp_touch[0] and fill_close_confirms_tp):
                hit_i = 0
            elif len(path_times) > 1:
                later_reached = np.flatnonzero(tp_touch[1:] | lc_touch[1:])
                if later_reached.size:
                    hit_i = int(later_reached[0]) + 1

            coverage_rows = (
                hit_i + 1 if hit_i is not None else len(path_times)
            )
            path_complete_to_outcome = self._is_contiguous(
                path_times[:coverage_rows],
                fill_time,
                horizon_end if hit_i is None else None,
            )
            has_full_horizon = bool(
                hit_i is None and path_complete_to_outcome
            )
            common = {
                **entry_common,
                "fill_bar_tp_ambiguous": fill_bar_ambiguous,
                "tp_price": tp_price,
                "lc_price": lc_price,
                "position_path_complete_to_outcome": bool(
                    path_complete_to_outcome
                ),
                "has_full_horizon": bool(has_full_horizon),
            }

            if not path_complete_to_outcome:
                results.append({
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
                })
                continue

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
                result_pips = float(
                    direction
                    * (float(lc_price) - actual_entry)
                    / self.pair.pip_value
                )
                actual_exit = float(lc_price)
                tp_hit = False
                lc_hit = True
            else:
                exit_i = hit_i
                result_name = "tp"
                result_pips = float(
                    direction
                    * (float(tp_price) - actual_entry)
                    / self.pair.pip_value
                )
                actual_exit = float(tp_price)
                tp_hit = True
                lc_hit = False

            exit_time = pd.Timestamp(path_times[exit_i])
            before_exit = slice(0, exit_i + 1)
            results.append({
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
            })
        return results


def _line_direction_columns(line: dict[str, Any]) -> dict[str, Any]:
    """構成ピークの向きに関する内訳を返す。

    ``prices_info`` は新しい順。素の抵抗線・支持線と、役割が入れ替わった線
    （上側なのに直近が安値、下側なのに直近が高値）を後から切り分けたい。
    走行に時間がかかるため、ここで絞らず記録だけしておく。
    """
    info = line.get("prices_info") or []
    directions: list[int] = []
    for item in info:
        try:
            directions.append(int(float(item.get("direction") or 0)))
        except (TypeError, ValueError):
            directions.append(0)
    newest = directions[0] if directions else None
    positive = sum(1 for value in directions if value > 0)
    negative = sum(1 for value in directions if value < 0)
    same = positive if (newest or 0) > 0 else negative
    opposite = negative if (newest or 0) > 0 else positive
    return {
        # 直近の構成ピークの向き。上側の線で -1、下側の線で +1 なら、
        # 既に役割が入れ替わった線（flip）であって素の線ではない。
        "line_newest_peak_direction": newest,
        "line_positive_peak_count": positive,
        "line_negative_peak_count": negative,
        # 直近の向きを基準にした内訳。逆方向が多いほどレンジに近い。
        "line_same_direction_count": same if newest else None,
        "line_opposite_direction_count": opposite if newest else None,
    }


def _line_columns(line: dict[str, Any]) -> dict[str, Any]:
    dirs = line.get("dirs_grouped") or []
    return {
        "line_total_strength": line.get("total_strength"),
        # peaks count = この抵抗線・支持線を構成するピーク数。
        "line_peaks_count": line.get("count"),
        "line_count": line.get("count"),
        "line_average_strength": line.get("ave_strength"),
        "line_core_price": line.get("core_median_price"),
        "line_core_peak_count": line.get("core_count"),
        "line_core_count": line.get("core_count"),
        "line_core_total_strength": line.get("core_total_strength"),
        "line_newest_source_time": line.get("newest_time"),
        "line_oldest_source_time": line.get("oldest_time"),
        "line_source_directions": "|".join(str(value) for value in dirs),
        # 構成ピークの向きを、後から閾値を振れる形で残す。
        # 走行が長いので、絞り込みではなく記録にしておき、解析時に選ぶ。
        **_line_direction_columns(line),
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
        # foot count = この1ピークを構成するローソク足の本数。
        "trigger_foot_count": peak.get("count"),
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
    if "line_timeframe" not in work:
        work["line_timeframe"] = "M5"
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
        # M5/M30/H1の母数と成績を混ぜない。同じrank=1でも
        # それぞれの足内で付けた順位であり、直接比較できない。
        group_columns = ["line_timeframe", *columns]
        grouped = work.groupby(
            group_columns,
            dropna=False,
            observed=True,
        )
        for keys, group in grouped:
            if len(group) < min_group_size and group_name != "all":
                continue
            if not isinstance(keys, tuple):
                keys = (keys,)
            completed = group[group["completed_trade"]]
            wins = completed[completed["is_win"]]
            completed_result_yen = (
                pd.to_numeric(completed["result_yen"], errors="coerce")
                if "result_yen" in completed
                else pd.Series(index=completed.index, dtype=float)
            )
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
                "mean_win_pips": (
                    float(
                        pd.to_numeric(
                            wins["trade_result_pips"],
                            errors="coerce",
                        ).mean()
                    )
                    if len(wins)
                    else np.nan
                ),
                "net_result_yen": (
                    float(completed_result_yen.sum(min_count=1))
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
            for column, key in zip(group_columns, keys):
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
        f"m5-m30-h1line{args.line_history_bars}"
        f"_range{args.tp_lookback}x{args.tp_multiplier:g}"
        f"_rr{args.rr:g}"
        f"_sp{args.spread_pips:g}"
        f"_{args.horizon_minutes}m"
    )
    if args.enforce_peak_strength:
        config = f"{config}_strong"
    if args.group_threshold_a is not None:
        config = f"{config}_grp{args.group_threshold_a:g}A"
    if args.min_distance_a > 0:
        config = f"{config}_far{args.min_distance_a:g}A"
    if args.min_line_total_strength > 0:
        config = f"{config}_str{args.min_line_total_strength:g}"
    if args.min_line_direction_ratio > 0:
        config = f"{config}_dir{args.min_line_direction_ratio*100:g}"
    if args.exclude_flipped_recent:
        config = f"{config}_noflip"
    if args.separate_line_directions:
        config = f"{config}_dirsplit"
    if args.min_line_peak_count > 1:
        config = f"{config}_minpk{args.min_line_peak_count}"
    if args.entry_mode == "stop":
        # 逆張りの既存ファイルを上書きしないよう、ブレイク版は名前を分ける。
        config = (
            f"{config}_break"
            f"off{args.stop_offset_pips:g}"
            f"slip{args.stop_slippage_pips:g}"
        )
    stem = f"{pair_name}_{period}_{config}"
    folder = Path(args.output_dir)
    return {
        "candidates": folder / f"resistance_sweep_candidates_{stem}.csv",
        "target_grid": folder / f"resistance_sweep_target_grid_{stem}.csv",
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
    # 進捗表示は本質ではない。OneDriveのロックで長時間の走行を落とさない。
    gene.replace_with_retry(temporary_path, path, required=False)
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
    gene.replace_with_retry(path, destination)
    path.with_suffix(path.suffix + ".tmp").unlink(missing_ok=True)
    return destination


def _archive_existing_output(path: Path) -> list[Path]:
    """Preserve an older result and any residual temp beside it."""
    archived = []
    for candidate in (path, path.with_suffix(path.suffix + ".tmp")):
        if not candidate.exists():
            continue
        archive = candidate.parent / "archive"
        archive.mkdir(parents=True, exist_ok=True)
        timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        destination = archive / f"{candidate.stem}_{timestamp}{candidate.suffix}"
        sequence = 1
        while destination.exists():
            destination = archive / (
                f"{candidate.stem}_{timestamp}_{sequence}{candidate.suffix}"
            )
            sequence += 1
        gene.replace_with_retry(candidate, destination)
        archived.append(destination)
    return archived


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
    gene.replace_with_retry(temporary_path, path, required=False)
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
                "win_rate_completed": np.nan,
                "mean_win_pips": np.nan,
                "net_result_yen": 0.0,
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
    completed_rows = frame[completed]
    row.update(
        {
            "filled_candidate_count": int(frame["filled"].fillna(False).sum()),
            "completed_trade_count": int(completed.sum()),
            "winning_candidate_count": len(wins),
            "has_winning_candidate": bool(len(wins)),
            "win_rate_completed": (
                float(len(wins) / len(completed_rows))
                if len(completed_rows)
                else np.nan
            ),
            "mean_win_pips": (
                float(
                    pd.to_numeric(
                        wins["trade_result_pips"],
                        errors="coerce",
                    ).mean()
                )
                if len(wins)
                else np.nan
            ),
            "net_result_yen": (
                float(
                    pd.to_numeric(
                        completed_rows["result_yen"],
                        errors="coerce",
                    ).sum(min_count=1)
                )
                if len(completed_rows)
                else 0.0
            ),
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
    _archive_existing_output(paths["progress"])
    _write_progress(
        paths["progress"],
        pair_name=pair_name,
        args=args,
        status="running",
        phase="loading_data",
        wall_started=wall_started,
        process_started=process_started,
    )
    m5, m30, h1, s5 = load_pair_data(
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
        phase="production_equivalence",
        wall_started=wall_started,
        process_started=process_started,
        total_positions=total_positions,
    )
    inspector = LimitPathInspector(s5, pair)
    candidate_rows: list[dict[str, Any]] = []
    event_rows: list[dict[str, Any]] = []
    grid_accumulators = (
        {
            timeframe: TargetGridAccumulator(args.spread_pips)
            for timeframe in LINE_TIMEFRAMES
        }
        if args.target_grid
        else None
    )
    h1_stair_cache: dict[pd.Timestamp, dict[str, Any]] = {}
    evaluated_events = 0
    processed_positions = 0
    last_decision_time: pd.Timestamp | None = None
    next_notice = pd.Timestamp(args.start) + pd.DateOffset(months=2)

    _notify(
        (
            f"{pair_name} count2 resistance inspection 開始\n"
            f"- 期間: {args.start:%Y-%m-%d %H:%M} ～ {args.end:%Y-%m-%d %H:%M}\n"
            f"- 条件: 直近{args.tp_lookback}本平均×{args.tp_multiplier:g}, "
            f"RR={args.rr:g}, spread={args.spread_pips:g}pips\n"
            f"- トリガー: M5 count2\n"
            f"- ライン足: M5 / M30 / H1（それぞれnative完成足）\n"
            f"- 評価: 全候補を独立した反実仮想注文として検証"
        )
    )

    # 総当たりの広い保存条件とは別に、本番Trial固定条件で実CandleAnalysis、
    # 実Peaks、実LineStrengthCalを通す。ここが不一致なら集計へ進めない。
    production_equivalence = validate_production_context_equivalence(
        pair_name,
        m5,
        m30,
        h1,
        indices,
        sample_count=PRODUCTION_EQUIVALENCE_SAMPLE_COUNT,
        require_candidates=True,
    )
    equivalence_by_timeframe = production_equivalence[
        "checked_candidates_by_timeframe"
    ]
    _notify(
        (
            f"{pair_name} 抵抗線ブレイク 本番等価性確認完了\n"
            f"- 判断時刻: {production_equivalence['checked_decisions']}件\n"
            f"- 候補: {production_equivalence['checked_candidates']}件\n"
            + "\n".join(
                f"- {timeframe}: {count}件"
                for timeframe, count in equivalence_by_timeframe.items()
            )
            + "\n- 不一致: 0件"
        )
    )
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

    for position, index in enumerate(indices):
        decision_time = pd.Timestamp(m5.iloc[index]["time_jp_dt"])
        last_decision_time = decision_time
        current_position = position + 1
        processed_positions = current_position
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
            "decision_trigger_timeframe": "M5",
            "counterfactual_candidates": True,
        }
        if position + 1 >= len(indices):
            for line_timeframe in LINE_TIMEFRAMES:
                event_rows.append(
                    {
                        **event_base,
                        "line_timeframe": line_timeframe,
                        "event_status": "no_next_count2",
                        "event_skip_reason": (
                            "next_count2_not_inside_requested_period"
                        ),
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
            for line_timeframe in LINE_TIMEFRAMES:
                event_rows.append(
                    {
                        **event_base,
                        **target,
                        "line_timeframe": line_timeframe,
                        "event_status": "skipped",
                        "event_skip_reason": target["target_skip_reason"],
                        "candidate_count": 0,
                    }
                )
            continue

        try:
            decision_context = _build_event_decision_context(
                m5,
                index,
                pair_name,
                h1=h1,
                peak_history_bars=args.peak_history_bars,
            )
        except Exception as error:
            for line_timeframe in LINE_TIMEFRAMES:
                event_rows.append(
                    {
                        **event_base,
                        **target,
                        "line_timeframe": line_timeframe,
                        "event_status": "skipped",
                        "event_skip_reason": (
                            "decision_context_error:"
                            f"{type(error).__name__}:{error}"
                        ),
                        "candidate_count": 0,
                    }
                )
            continue

        rebuilt_by_timeframe: dict[str, dict[str, Any]] = {}
        for line_timeframe in LINE_TIMEFRAMES:
            try:
                rebuilt_frame = rebuild_candidates_at(
                    m5,
                    index,
                    pair_name,
                    m30=m30,
                    h1=h1,
                    h1_stair_cache=h1_stair_cache,
                    decision_context=decision_context,
                    entry_mode=args.entry_mode,
                    enforce_peak_strength_filter=args.enforce_peak_strength,
                    separate_line_directions=args.separate_line_directions,
                    min_line_peak_count=args.min_line_peak_count,
                    group_threshold_a=args.group_threshold_a,
                    min_line_total_strength=args.min_line_total_strength,
                    min_line_direction_ratio=args.min_line_direction_ratio,
                    min_distance_a=args.min_distance_a,
                    exclude_flipped_recent=args.exclude_flipped_recent,
                    line_history_bars=args.line_history_bars,
                    peak_history_bars=args.peak_history_bars,
                    line_timeframe=line_timeframe,
                )
            except Exception as error:
                event_rows.append(
                    {
                        **event_base,
                        **target,
                        "line_timeframe": line_timeframe,
                        "event_status": "skipped",
                        "event_skip_reason": (
                            f"line_rebuild_error:{type(error).__name__}:{error}"
                        ),
                        "candidate_count": 0,
                    }
                )
                continue
            rebuilt_by_timeframe[line_timeframe] = rebuilt_frame

        if not rebuilt_by_timeframe:
            continue
        # M5/M30/H1の中身は混ぜず、後段の注文パス検査だけ
        # 一本のループで共有する。候補rankは各足の内部で付与済み。
        rebuilt = dict(
            rebuilt_by_timeframe.get("M5")
            or next(iter(rebuilt_by_timeframe.values()))
        )
        rebuilt["candidates"] = []
        for line_timeframe, rebuilt_frame in rebuilt_by_timeframe.items():
            for candidate in rebuilt_frame["candidates"]:
                candidate["_completed_history"] = rebuilt_frame[
                    "completed_history"
                ]
                candidate["line_timeframe"] = line_timeframe
                candidate["line_source_granularity"] = rebuilt_frame[
                    "line_source_granularity"
                ]
                candidate["line_history_bars"] = rebuilt_frame[
                    "line_history_bars"
                ]
                candidate["line_history_minutes"] = rebuilt_frame[
                    "line_history_minutes"
                ]
                candidate["peak_history_bars"] = rebuilt_frame[
                    "peak_history_bars"
                ]
                candidate["line_average_range_pips"] = rebuilt_frame[
                    "line_average_range_pips"
                ]
                candidate["group_threshold_pips"] = rebuilt_frame[
                    "group_threshold_pips"
                ]
                rebuilt["candidates"].append(candidate)

        peak = rebuilt["newest_peak"]
        fc2_shape = rebuilt["decision_context"].shape_for_peak(
            peak,
            "M5",
            average_range_pips=target["recent_m5_avg_range_pips"],
        )
        if not fc2_shape.get("valid"):
            for line_timeframe in rebuilt_by_timeframe:
                event_rows.append(
                    {
                        **event_base,
                        **target,
                        **_peak_columns(peak, pair),
                        **flatten_foot_count2_shape(fc2_shape),
                        "line_timeframe": line_timeframe,
                        "event_status": "skipped",
                        "event_skip_reason": (
                            "foot_count2_shape_error:"
                            + str(fc2_shape.get("reason"))
                        ),
                        "candidate_count": 0,
                    }
                )
            continue
        h1_pair_shape = rebuilt["h1_pair_shape_context"]
        if not h1_pair_shape.get("valid"):
            for line_timeframe in rebuilt_by_timeframe:
                event_rows.append(
                    {
                        **event_base,
                        **target,
                        **_peak_columns(peak, pair),
                        **flatten_foot_count2_shape(fc2_shape),
                        **flatten_foot_count2_shape(
                            h1_pair_shape,
                            prefix="h1_pair_",
                        ),
                        "line_timeframe": line_timeframe,
                        "event_status": "skipped",
                        "event_skip_reason": (
                            "h1_two_candle_shape_error:"
                            + str(h1_pair_shape.get("reason"))
                        ),
                        "candidate_count": 0,
                    }
                )
            continue
        event_base.update(
            {
                **target,
                **_peak_columns(peak, pair),
                **flatten_foot_count2_shape(fc2_shape),
                **flatten_foot_count2_shape(h1_pair_shape, prefix="h1_pair_"),
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
            candidate["fc2_shape_context"] = attach_line_wick_context(
                fc2_shape,
                line_price=candidate["line_price"],
                line_side=candidate["line_side"],
                pair=pair,
            )
            touches = line_touch_features(
                candidate["_completed_history"],
                candidate["line"],
                decision_time,
                pair,
                args.retouch_tolerance_pips,
                TIMEFRAME_MINUTES[candidate["line_timeframe"]],
                candidate["line_timeframe"] == "M5",
            )
            candidate.update(touches)
            candidate["predict_distance_to_tp_ratio"] = (
                candidate["distance_pips"] / target["tp_pips"]
            )
            touches_by_candidate[id(candidate)] = touches

        m5_line_candidates = [
            candidate
            for candidate in rebuilt["candidates"]
            if candidate["line_timeframe"] == "M5"
        ]
        counterfactual_candidates = [
            candidate
            for candidate in m5_line_candidates
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
        for candidate in m5_line_candidates:
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
        for candidate in m5_line_candidates:
            candidate.setdefault("current_policy_live_eligible", False)
            candidate["current_policy_live_selected"] = bool(
                candidate["current_policy_live_eligible"]
                and candidate.get("predict_candidate_rank") == 1
            )
        for candidate in rebuilt["candidates"]:
            if candidate["line_timeframe"] == "M5":
                continue
            # PredictReversalはM5用profile。M30/H1へ横流しせず、
            # native足の素の抵抗線候補として検証する。
            candidate["counterfactual_predict_candidate_rank"] = None
            candidate["counterfactual_predict_selected"] = False
            candidate["current_policy_live_eligible"] = False
            candidate["current_policy_live_selected"] = False

        rows_for_event: dict[str, list[dict[str, Any]]] = {
            timeframe: [] for timeframe in rebuilt_by_timeframe
        }
        for candidate in rebuilt["candidates"]:
            line = candidate["line"]
            touches = touches_by_candidate[id(candidate)]
            line_timeframe = candidate["line_timeframe"]
            grid_accumulator = (
                grid_accumulators[line_timeframe]
                if grid_accumulators is not None
                else None
            )
            # 先頭が本番相当の一件。以降がグリッドのセルで、約定の探索と
            # 保有期間の切り出しを共有するため一度の呼び出しでまとめて判定する。
            targets = [(target["tp_pips"], target["lc_pips"])]
            if grid_accumulator is not None:
                average_range = float(target["recent_m5_avg_range_pips"])
                targets.extend(
                    (average_range * tp_a, average_range * lc_a)
                    for tp_a in TARGET_GRID_TP_A
                    for lc_a in TARGET_GRID_LC_A
                )
            # 変数名は path_results にする。paths は出力ファイルの辞書で、
            # ここで上書きすると後段の書き出しが壊れる。
            path_results = inspector.inspect_targets(
                decision_time=decision_time,
                expiry_time=next_count2_time,
                direction=candidate["trade_direction"],
                line_price=candidate["line_price"],
                targets=targets,
                horizon_minutes=args.horizon_minutes,
                spread_pips=args.spread_pips,
                approach_side=candidate["approach_side"],
                entry_mode=args.entry_mode,
                stop_offset_pips=args.stop_offset_pips,
                stop_slippage_pips=args.stop_slippage_pips,
            )
            path = path_results[0]
            result_r = path.get("result_r")
            path["result_yen"] = (
                float(result_r) * NORMALIZED_LC_RISK_YEN
                if result_r is not None and math.isfinite(float(result_r))
                else np.nan
            )
            if grid_accumulator is not None:
                cells = [
                    (tp_a, lc_a)
                    for tp_a in TARGET_GRID_TP_A
                    for lc_a in TARGET_GRID_LC_A
                ]
                for (tp_a, lc_a), (tp_pips, lc_pips), cell_path in zip(
                    cells, targets[1:], path_results[1:]
                ):
                    grid_accumulator.add(
                        tp_a,
                        lc_a,
                        candidate["line"].get("count"),
                        candidate["line_side"],
                        tp_pips,
                        lc_pips,
                        cell_path,
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
                "candidate_scope": (
                    "all_raw_"
                    + line_timeframe.lower()
                    + "_line_groups_ahead"
                ),
                "candidate_pruning_applied": False,
                "decision_trigger_timeframe": "M5",
                "line_timeframe": line_timeframe,
                "line_source_granularity": candidate[
                    "line_source_granularity"
                ],
                "line_history_bars": candidate["line_history_bars"],
                "line_history_minutes": candidate["line_history_minutes"],
                "peak_history_bars": candidate["peak_history_bars"],
                "line_average_range_pips": candidate[
                    "line_average_range_pips"
                ],
                "group_threshold_pips": candidate[
                    "group_threshold_pips"
                ],
                "normalized_lc_risk_yen": NORMALIZED_LC_RISK_YEN,
                "fixed_spread_pips": args.spread_pips,
                "pending_expiry_exclusive": True,
                "position_horizon_minutes": args.horizon_minutes,
                **flatten_foot_count2_shape(
                    candidate.get("fc2_shape_context")
                ),
                **_line_columns(line),
                **touches,
                **path,
            }
            candidate_rows.append(row)
            rows_for_event[line_timeframe].append(row)

        for line_timeframe, rebuilt_frame in rebuilt_by_timeframe.items():
            timeframe_rows = rows_for_event[line_timeframe]
            event_status = "evaluated" if timeframe_rows else "no_candidates"
            event_rows.append(
                _event_summary(
                    {
                        **event_base,
                        "line_timeframe": line_timeframe,
                        "line_source_granularity": rebuilt_frame[
                            "line_source_granularity"
                        ],
                        "line_history_bars": rebuilt_frame[
                            "line_history_bars"
                        ],
                        "line_history_minutes": rebuilt_frame[
                            "line_history_minutes"
                        ],
                        "peak_history_bars": rebuilt_frame[
                            "peak_history_bars"
                        ],
                        "group_threshold_pips": rebuilt_frame[
                            "group_threshold_pips"
                        ],
                        "event_status": event_status,
                        "event_skip_reason": None,
                    },
                    timeframe_rows,
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
    for key, path in paths.items():
        if key != "progress":
            _archive_existing_output(path)
    candidates.to_csv(paths["candidates"], index=False, encoding="utf-8-sig")
    if grid_accumulators is not None:
        target_grid_frames = []
        for line_timeframe, accumulator in grid_accumulators.items():
            timeframe_grid = accumulator.to_frame()
            timeframe_grid.insert(0, "line_timeframe", line_timeframe)
            timeframe_grid.insert(
                1,
                "line_source_granularity",
                line_timeframe,
            )
            target_grid_frames.append(timeframe_grid)
        pd.concat(target_grid_frames, ignore_index=True).to_csv(
            paths["target_grid"], index=False, encoding="utf-8-sig"
        )
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
    timeframe_summary_lines = []
    for line_timeframe in LINE_TIMEFRAMES:
        timeframe_candidates = (
            candidates[candidates["line_timeframe"].eq(line_timeframe)]
            if not candidates.empty
            else pd.DataFrame()
        )
        timeframe_completed = (
            timeframe_candidates[
                timeframe_candidates["candidate_result"].isin(
                    ["tp", "lc", "both_same_s5_lc_assumed", "timeout"]
                )
            ]
            if not timeframe_candidates.empty
            else pd.DataFrame()
        )
        timeframe_wins = (
            timeframe_completed[
                timeframe_completed["candidate_result"].eq("tp")
            ]
            if not timeframe_completed.empty
            else pd.DataFrame()
        )
        win_rate = (
            len(timeframe_wins) / len(timeframe_completed)
            if len(timeframe_completed)
            else np.nan
        )
        mean_win_pips = (
            float(
                pd.to_numeric(
                    timeframe_wins["trade_result_pips"],
                    errors="coerce",
                ).mean()
            )
            if len(timeframe_wins)
            else np.nan
        )
        net_yen = (
            float(
                pd.to_numeric(
                    timeframe_completed["result_yen"],
                    errors="coerce",
                ).sum(min_count=1)
            )
            if len(timeframe_completed)
            else 0.0
        )
        timeframe_summary_lines.append(
            f"{line_timeframe}: 完了={len(timeframe_completed)}, "
            + (
                f"勝率={win_rate:.1%}, "
                if math.isfinite(win_rate)
                else "勝率=-, "
            )
            + (
                f"平均勝ち={mean_win_pips:.2f}pips, "
                if math.isfinite(mean_win_pips)
                else "平均勝ち=-, "
            )
            + (
                f"損益={net_yen:.0f}円"
                f"（LC時{NORMALIZED_LC_RISK_YEN:g}円リスク換算）"
            )
        )
    summary_lines = [
        f"期間: {args.start:%Y-%m-%d} ～ {args.end:%Y-%m-%d}",
        (
            "本番等価性: "
            f"判断={production_equivalence['checked_decisions']}件, "
            f"候補={production_equivalence['checked_candidates']}件, "
            "不一致=0件"
        ),
        *(
            f"本番等価性 {timeframe}: 候補={count}件"
            for timeframe, count in equivalence_by_timeframe.items()
        ),
        f"検出count2: {len(indices)}",
        f"評価イベント: {evaluated_events}",
        (
            "候補なし時間足イベント: "
            f"{int(event_status.get('no_candidates', 0))}"
        ),
        (
            "除外時間足イベント: "
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
        f"1本以上勝ち候補があった時間足イベント: {winning_events}",
        *timeframe_summary_lines,
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
    with notice.inspection_notice_scope():
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
