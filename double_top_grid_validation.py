# 最新更新日時: 2026-08-30 17:44 JST
"""DoubleTopの因果的な総当たり探索と翌年固定リプレイ。

形成判断には判断時刻までに完成したM5だけを使う。S5は判断後の結果付けに
だけ使い、探索期間とリプレイ期間は ``[start, end)`` で完全に分離する。
実行時引数は使わず、起動ファイルから固定期間と通貨ペアを渡す。
"""

from __future__ import annotations

import datetime as dt
import gc
import json
import math
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

import fGeneric as gene
import fDoubleTopCore as double_top_core
import f_ダブルトップ as live_double_top
import send_notice as notice
import tokens as tk
from classCandleAnalysis import (
    H1_ANALYSIS_BARS,
    M5_ANALYSIS_BARS,
    candleAnalysis,
)
from count2_target_grid_search import _load_typed_s5_inspector
from fCandleDataQuality import (
    analysis_missing_bar_stats,
    is_expected_market_closed_gap,
)


VERSION = "double_top_grid_v2"
TIME_FORMAT = "%Y/%m/%d %H:%M:%S"
M5_HISTORY_BARS = M5_ANALYSIS_BARS
H1_HISTORY_BARS = H1_ANALYSIS_BARS
RISK_YEN = float(live_double_top.LIVE_TRIAL_POLICY_V1.risk_yen)
SPREAD_PIPS = 0.8
MAX_MISSING_RATIO = 0.50
NORMAL_PRIORITY_SLOT_COUNT = 6
SIMILAR_ACTIVE_PIPS = 3.0
TOP_COUNT = 15
MIN_COMPLETED = 30
MIN_COVERAGE = 0.80
MIN_PROFIT_FACTOR = 1.05
MIN_ACTIVE_MONTHS = 12
MIN_POSITIVE_MONTH_RATE = 0.50
MIN_INTERACTION_EVENTS = 20

TP_HEIGHT_MULTIPLIERS = (0.50, 0.75, 1.00, 1.25, 1.50)
STOP_BUFFER_PIPS = (0.0, 1.0, 2.0, 3.0, 5.0)
TRADE_TIMEOUT_MINUTES = (60, 120, 240, 480)

# 高速走査の候補母集団だけを決める固定条件。本番ポリシーとは完全に分離する。
GRID_DISCOVERY_POLICY_V1 = double_top_core.DoubleTopPolicyV1(
    policy_id="grid_discovery_v1",
    min_top_foot_count=0,
    min_height_pips=3.0,
    max_height_pips=120.0,
    min_t1_t2_minutes=10.0,
    max_t1_t2_minutes=1440.0,
    base_top_tolerance_pips=None,
    top_tolerance_height_ratio=None,
    max_top_gap_pips=30.0,
    max_top_gap_ratio=0.75,
    neckline_break_buffer_pips=0.0,
)

CORE_INTERACTION_FAMILIES = (
    "both_top_foot_min",
    "decline_foot_min",
    "height_min",
    "top_gap_max",
    "top_gap_ratio_max",
    "formation_max",
    "t2_break_max",
    "break_depth_min",
    "height_a_min",
    "top_relation",
)


@dataclass(frozen=True)
class ExecutionCombo:
    combo_id: str
    tp_height_multiplier: float
    stop_buffer_pips: float
    trade_timeout_minutes: int


@dataclass(frozen=True)
class ConditionSpec:
    condition_id: str
    family: str
    label: str
    field: str = ""
    operator: str = ""
    value: Any = None
    components: tuple[str, ...] = ()


@dataclass
class PreparedMarketPath:
    decision_time: pd.Timestamp
    entry_time: pd.Timestamp | None
    entry_price: float | None
    times: np.ndarray
    opens_ask: np.ndarray
    highs_ask: np.ndarray
    lows_ask: np.ndarray
    missing_prefix: np.ndarray
    initial_missing: int
    period_end: pd.Timestamp
    reason: str | None = None

    def boundary_index(self, timeout_minutes: int) -> int | None:
        deadline = self.decision_time + pd.Timedelta(minutes=timeout_minutes)
        if deadline >= self.period_end or not len(self.times):
            return None
        index = int(
            np.searchsorted(
                self.times,
                np.datetime64(deadline, "ns"),
                side="left",
            )
        )
        if index >= len(self.times):
            return None
        return index

    def missing_ratio_through(self, index: int) -> float:
        observed = int(index) + 1
        missing = self.initial_missing + int(self.missing_prefix[index])
        denominator = observed + missing
        return float(missing / denominator) if denominator else 1.0


class TwoMonthProgress:
    def __init__(
        self,
        pair: str,
        phase: str,
        start: dt.datetime,
        end: dt.datetime,
        total_rows: int,
    ):
        self.pair = pair
        self.phase = phase
        self.start = pd.Timestamp(start)
        self.end = pd.Timestamp(end)
        self.total_rows = int(total_rows)
        self.next_boundary = self.start + pd.DateOffset(months=2)
        self.started = time.monotonic()

    def update(self, current_time: Any, current_row: int) -> None:
        current = pd.Timestamp(current_time)
        while current >= self.next_boundary and self.next_boundary <= self.end:
            elapsed = (time.monotonic() - self.started) / 60.0
            _notify(
                "【DoubleTop検証進捗】",
                f"- 通貨ペア: {self.pair}",
                f"- 工程: {self.phase}",
                f"- 期間到達: {self.next_boundary:%Y/%m/%d %H:%M:%S}",
                f"- 処理行: {current_row}/{self.total_rows}",
                f"- 経過: {elapsed:.1f}分",
            )
            self.next_boundary += pd.DateOffset(months=2)


def _notify(*lines: str) -> None:
    notice.send_inspection_notice("\n".join(str(line) for line in lines))


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, np.generic):
        return _json_safe(value.item())
    if value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _archive_existing(path: Path) -> Path | None:
    if not path.exists():
        return None
    archive = path.parent / "archive"
    archive.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    destination = archive / f"{path.stem}_{stamp}{path.suffix}"
    sequence = 1
    while destination.exists():
        destination = archive / (
            f"{path.stem}_{stamp}_{sequence}{path.suffix}"
        )
        sequence += 1
    path.replace(destination)
    return destination


def _atomic_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _archive_existing(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_csv(temporary, index=False, encoding="utf-8-sig")
    temporary.replace(path)


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _archive_existing(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            _json_safe(payload),
            ensure_ascii=False,
            indent=2,
            default=str,
            allow_nan=False,
        ),
        encoding="utf-8",
    )
    temporary.replace(path)


def _archive_residual_temp_and_logs(output_dir: Path) -> list[str]:
    archived: list[str] = []
    patterns = ("double_top_grid_v*.tmp", "double_top_grid_v*.log")
    for pattern in patterns:
        for path in output_dir.glob(pattern):
            destination = _archive_existing(path)
            if destination is not None:
                archived.append(str(destination))
    return archived


def _period_stem(
    pair: str,
    train_start: dt.datetime,
    train_end: dt.datetime,
    oos_start: dt.datetime,
    oos_end: dt.datetime,
) -> str:
    return (
        f"{pair}_{train_start:%Y%m%d}_{train_end:%Y%m%d}"
        f"_to_{oos_start:%Y%m%d}_{oos_end:%Y%m%d}"
    )


def _output_paths(
    output_dir: Path,
    pair: str,
    train_start: dt.datetime,
    train_end: dt.datetime,
    oos_start: dt.datetime,
    oos_end: dt.datetime,
) -> dict[str, Path]:
    prefix = f"{VERSION}_{_period_stem(pair, train_start, train_end, oos_start, oos_end)}"
    return {
        "train_events": output_dir / f"{prefix}_train_events.csv",
        "train_outcomes": output_dir / f"{prefix}_train_outcomes.csv",
        "grid": output_dir / f"{prefix}_grid.csv",
        "top15": output_dir / f"{prefix}_top15.csv",
        "oos_events": output_dir / f"{prefix}_oos_events.csv",
        "oos_outcomes": output_dir / f"{prefix}_oos_outcomes.csv",
        "oos_top15": output_dir / f"{prefix}_oos_top15_replay.csv",
        "oos_trades": output_dir / f"{prefix}_oos_combined_trades.csv",
        "oos_baseline": output_dir / f"{prefix}_oos_current_policy_trades.csv",
        "summary": output_dir / f"{prefix}_summary.json",
        "progress": output_dir / f"{prefix}_progress.json",
    }


def _source_path(
    output_dir: Path,
    granularity: str,
    pair: str,
    start: dt.datetime,
    end: dt.datetime,
) -> Path:
    path = output_dir / (
        f"{granularity.lower()}_{pair}_{start:%Y%m%d%H%M%S}_"
        f"{end:%Y%m%d%H%M%S}.csv"
    )
    if not path.is_file():
        raise FileNotFoundError(f"検証元データがありません: {path}")
    return path


def _read_candles(path: Path, label: str) -> pd.DataFrame:
    wanted = {
        "time_jp",
        "open",
        "close",
        "high",
        "low",
        "middle_price",
        "inner_high",
        "inner_low",
        "body",
        "body_abs",
        "moves",
        "direction",
        "RSI",
    }
    frame = pd.read_csv(
        path,
        usecols=lambda column: column in wanted,
        low_memory=False,
    )
    required = {"time_jp", "open", "close", "high", "low"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"{label} missing columns: {sorted(missing)}")
    frame["time_jp_dt"] = pd.to_datetime(
        frame["time_jp"],
        format=TIME_FORMAT,
        errors="raise",
    )
    numeric_columns = [column for column in wanted if column != "time_jp" and column in frame]
    frame[numeric_columns] = frame[numeric_columns].apply(
        pd.to_numeric,
        errors="coerce",
    )
    for column in ("open", "close", "high", "low"):
        if not np.isfinite(frame[column].to_numpy(dtype=float)).all():
            raise ValueError(f"{label} contains invalid {column}")
    frame.sort_values("time_jp_dt", kind="stable", inplace=True)
    duplicate_count = int(frame["time_jp_dt"].duplicated(keep="last").sum())
    if duplicate_count:
        frame.drop_duplicates("time_jp_dt", keep="last", inplace=True)
    frame.reset_index(drop=True, inplace=True)
    if "middle_price" not in frame or frame["middle_price"].isna().any():
        frame["middle_price"] = (frame["open"] + frame["close"]) / 2.0
    if "inner_high" not in frame or frame["inner_high"].isna().any():
        frame["inner_high"] = frame[["open", "close"]].max(axis=1)
    if "inner_low" not in frame or frame["inner_low"].isna().any():
        frame["inner_low"] = frame[["open", "close"]].min(axis=1)
    if "body" not in frame or frame["body"].isna().any():
        frame["body"] = frame["close"] - frame["open"]
    if "body_abs" not in frame or frame["body_abs"].isna().any():
        frame["body_abs"] = frame["body"].abs()
    if "moves" not in frame or frame["moves"].isna().any():
        frame["moves"] = frame["high"] - frame["low"]
    if "direction" not in frame or frame["direction"].isna().any():
        frame["direction"] = np.sign(frame["body"])
    frame.attrs["duplicate_count"] = duplicate_count
    return frame


def _tilt_direction(newer_middle: float, older_middle: float) -> int:
    # PeaksClassは差が0のときminimumを入れるため、同値は+1になる。
    return 1 if float(newer_middle) - float(older_middle) >= 0 else -1


def _peak_segment(
    latest_index: int,
    history_floor: int,
    middle: np.ndarray,
    inner_high: np.ndarray,
    inner_low: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    times: np.ndarray,
) -> dict[str, Any] | None:
    if latest_index - 1 < history_floor:
        return None
    direction = _tilt_direction(
        middle[latest_index],
        middle[latest_index - 1],
    )
    oldest_index = latest_index - 1
    while oldest_index - 1 >= history_floor:
        current_direction = _tilt_direction(
            middle[oldest_index],
            middle[oldest_index - 1],
        )
        if current_direction != direction:
            break
        oldest_index -= 1
    if direction == 1:
        peak_price = float(inner_high[latest_index])
        oldest_body_price = float(inner_low[oldest_index])
        wick_price = float(high[latest_index])
        oldest_wick_price = float(low[oldest_index])
    else:
        peak_price = float(inner_low[latest_index])
        oldest_body_price = float(inner_high[oldest_index])
        wick_price = float(low[latest_index])
        oldest_wick_price = float(high[oldest_index])
    return {
        "direction": direction,
        "count": latest_index - oldest_index + 1,
        "latest_index": latest_index,
        "oldest_index": oldest_index,
        "latest_time": pd.Timestamp(times[latest_index]),
        "oldest_time": pd.Timestamp(times[oldest_index]),
        "peak": peak_price,
        "oldest_body_price": oldest_body_price,
        "gap": abs(peak_price - oldest_body_price),
        "wick_gap": abs(wick_price - oldest_wick_price),
    }


def _latest_four_peaks(
    latest_index: int,
    middle: np.ndarray,
    inner_high: np.ndarray,
    inner_low: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    times: np.ndarray,
) -> list[dict[str, Any]]:
    history_floor = max(0, latest_index - M5_HISTORY_BARS + 1)
    peaks: list[dict[str, Any]] = []
    segment_latest = latest_index
    for _ in range(4):
        peak = _peak_segment(
            segment_latest,
            history_floor,
            middle,
            inner_high,
            inner_low,
            high,
            low,
            times,
        )
        if peak is None:
            return []
        peaks.append(peak)
        segment_latest = int(peak["oldest_index"])
    return peaks


def _session_name(hour: int) -> str:
    if 6 <= hour < 15:
        return "ASIA"
    if 15 <= hour < 21:
        return "LONDON"
    return "NEW_YORK"


def _rsi_bin(value: Any) -> str | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    if number < 35:
        return "<35"
    if number < 45:
        return "35-44"
    if number < 55:
        return "45-54"
    if number < 65:
        return "55-64"
    return "65+"


def _range_bin(value: float) -> str:
    if value < 3:
        return "<3"
    if value < 5:
        return "3-4"
    if value < 8:
        return "5-7"
    if value < 12:
        return "8-11"
    return "12+"


def _h1_context(
    decision_time: pd.Timestamp,
    h1: pd.DataFrame,
    h1_times: np.ndarray,
) -> dict[str, Any]:
    completed_start_max = decision_time - pd.Timedelta(hours=1)
    latest_index = int(
        np.searchsorted(
            h1_times,
            np.datetime64(completed_start_max, "ns"),
            side="right",
        )
    ) - 1
    if latest_index < 0:
        return {
            "h1_latest_direction": np.nan,
            "h1_previous_direction": np.nan,
            "h1_two_sequence": None,
            "h1_trend3_direction": np.nan,
            "h1_rsi": np.nan,
            "h1_rsi_bin": None,
        }
    latest = h1.iloc[latest_index]
    previous = h1.iloc[latest_index - 1] if latest_index >= 1 else None
    latest_direction = int(np.sign(float(latest["close"]) - float(latest["open"])))
    previous_direction = (
        int(np.sign(float(previous["close"]) - float(previous["open"])))
        if previous is not None
        else 0
    )
    trend3_direction = 0
    if latest_index >= 3:
        trend3_direction = int(
            np.sign(
                float(latest["close"])
                - float(h1.iloc[latest_index - 3]["close"])
            )
        )
    rsi = latest.get("RSI", np.nan)
    return {
        "h1_latest_direction": latest_direction,
        "h1_previous_direction": previous_direction,
        "h1_two_sequence": f"{previous_direction}|{latest_direction}",
        "h1_trend3_direction": trend3_direction,
        "h1_rsi": rsi,
        "h1_rsi_bin": _rsi_bin(rsi),
    }


def generate_events(
    pair_name: str,
    period_start: dt.datetime,
    period_end: dt.datetime,
    m5: pd.DataFrame,
    h1: pd.DataFrame,
    phase: str,
) -> tuple[pd.DataFrame, dict[str, int]]:
    pair = gene.currency_pair(pair_name)
    times = m5["time_jp_dt"].to_numpy(dtype="datetime64[ns]", copy=False)
    h1_times = h1["time_jp_dt"].to_numpy(dtype="datetime64[ns]", copy=False)
    middle = m5["middle_price"].to_numpy(dtype=float, copy=False)
    inner_high = m5["inner_high"].to_numpy(dtype=float, copy=False)
    inner_low = m5["inner_low"].to_numpy(dtype=float, copy=False)
    high = m5["high"].to_numpy(dtype=float, copy=False)
    low = m5["low"].to_numpy(dtype=float, copy=False)
    opens = m5["open"].to_numpy(dtype=float, copy=False)
    closes = m5["close"].to_numpy(dtype=float, copy=False)
    body_abs = m5["body_abs"].to_numpy(dtype=float, copy=False)
    moves = m5["moves"].to_numpy(dtype=float, copy=False)
    rsi_values = (
        m5["RSI"].to_numpy(dtype=float, copy=False)
        if "RSI" in m5
        else np.full(len(m5), np.nan)
    )
    start_decision = np.datetime64(pd.Timestamp(period_start), "ns")
    end_decision = np.datetime64(pd.Timestamp(period_end), "ns")
    decision_times = times + np.timedelta64(5, "m")
    candidate_indices = np.flatnonzero(
        (decision_times >= start_decision)
        & (decision_times < end_decision)
    )
    reporter = TwoMonthProgress(
        pair_name,
        phase,
        period_start,
        period_end,
        len(candidate_indices),
    )
    diagnostics = {
        "rows_scanned": 0,
        "sequence_matches": 0,
        "cross_matches": 0,
        "broad_filter_skips": 0,
        "quality_half_missing_skips": 0,
    }
    events: list[dict[str, Any]] = []
    for processed, raw_index in enumerate(candidate_indices, start=1):
        index = int(raw_index)
        decision_time = pd.Timestamp(decision_times[index])
        reporter.update(decision_time, processed)
        diagnostics["rows_scanned"] += 1
        if index < M5_HISTORY_BARS - 1 or index < 1:
            continue
        peaks = _latest_four_peaks(
            index,
            middle,
            inner_high,
            inner_low,
            high,
            low,
            times,
        )
        if len(peaks) != 4:
            continue
        decline, t2, neckline, t1 = peaks
        if tuple(peak["direction"] for peak in peaks) != (-1, 1, -1, 1):
            continue
        diagnostics["sequence_matches"] += 1
        break_close = float(closes[index])
        previous_close = float(closes[index - 1])
        neckline_price = double_top_core.peak_price_v1(neckline)
        if not (break_close < neckline_price <= previous_close):
            continue
        diagnostics["cross_matches"] += 1
        candidate = double_top_core.detect_candidate_v1(
            peaks,
            m5.iloc[index],
            m5.iloc[index - 1],
            pair,
            GRID_DISCOVERY_POLICY_V1,
        )
        if candidate is None:
            diagnostics["broad_filter_skips"] += 1
            continue

        t1_price = candidate.t1_price
        t2_price = candidate.t2_price
        neckline_price = candidate.neckline_price
        height_pips = candidate.height_pips
        top_gap_pips = candidate.top_gap_pips
        top_gap_ratio = candidate.top_gap_ratio
        formation_minutes = candidate.t1_t2_minutes
        t2_break_minutes = candidate.t2_break_minutes

        history_floor = index - M5_HISTORY_BARS + 1
        history_times = [pd.Timestamp(value) for value in times[history_floor:index + 1]]
        quality = analysis_missing_bar_stats(
            history_times,
            pd.Timedelta(minutes=5),
            expected_end=decision_time,
        )
        if float(quality["missing_ratio"]) >= MAX_MISSING_RATIO:
            diagnostics["quality_half_missing_skips"] += 1
            continue

        recent_floor = max(history_floor, index - 11)
        recent_average_range_pips = float(
            pair.price_to_pips(float(np.mean(moves[recent_floor:index + 1])))
        )
        if recent_average_range_pips <= 0:
            diagnostics["broad_filter_skips"] += 1
            continue
        break_depth_pips = candidate.break_depth_pips
        break_body_pips = float(pair.price_to_pips(body_abs[index]))
        height_a = height_pips / recent_average_range_pips
        break_body_a = break_body_pips / recent_average_range_pips
        top_relation_tolerance = pair.pips_to_price(1.0)
        if t2_price < t1_price - top_relation_tolerance:
            top_relation = "T2_LOWER"
        elif t2_price > t1_price + top_relation_tolerance:
            top_relation = "T2_HIGHER"
        else:
            top_relation = "T2_EQUAL"
        break_time = candidate.break_time
        event_id = (
            f"{pair_name}:{candidate.t1_time:%Y%m%d%H%M}:"
            f"{candidate.neckline_time:%Y%m%d%H%M}:"
            f"{candidate.t2_time:%Y%m%d%H%M}:"
            f"{break_time:%Y%m%d%H%M}"
        )
        row = {
            "event_id": event_id,
            "pair": pair_name,
            "source_row_index": index,
            "decision_time": decision_time,
            "break_time": break_time,
            "core_version": candidate.core_version,
            "discovery_policy_id": GRID_DISCOVERY_POLICY_V1.policy_id,
            "t1_time": candidate.t1_time,
            "neckline_time": candidate.neckline_time,
            "t2_time": candidate.t2_time,
            "t1_price": t1_price,
            "neckline_price": neckline_price,
            "t2_price": t2_price,
            "break_open": float(opens[index]),
            "break_close": break_close,
            "previous_close": previous_close,
            "t1_foot_count": candidate.t1_foot_count,
            "t2_foot_count": candidate.t2_foot_count,
            "both_top_foot_min": min(
                candidate.t1_foot_count,
                candidate.t2_foot_count,
            ),
            "decline_foot_count": candidate.decline_foot_count,
            "neckline_foot_count": candidate.neckline_foot_count,
            "height_price": candidate.height_price,
            "height_pips": height_pips,
            "top_gap_pips": top_gap_pips,
            "top_gap_ratio": top_gap_ratio,
            "formation_minutes": formation_minutes,
            "t2_break_minutes": t2_break_minutes,
            "neckline_t2_minutes": candidate.neckline_t2_minutes,
            "break_depth_pips": break_depth_pips,
            "break_body_pips": break_body_pips,
            "break_body_a": break_body_a,
            "recent_m5_average_range_pips": recent_average_range_pips,
            "height_a": height_a,
            "t1_leg_pips": float(pair.price_to_pips(float(t1["gap"]))),
            "t2_leg_pips": float(pair.price_to_pips(float(t2["gap"]))),
            "decline_leg_pips": float(pair.price_to_pips(float(decline["gap"]))),
            "top_relation": top_relation,
            "session": _session_name(decision_time.hour),
            "weekday": decision_time.day_name().upper(),
            "decision_hour": decision_time.hour,
            "m5_rsi": float(rsi_values[index]) if math.isfinite(rsi_values[index]) else np.nan,
            "m5_rsi_bin": _rsi_bin(rsi_values[index]),
            "m5_range_bin": _range_bin(recent_average_range_pips),
            "m5_missing_bars": int(quality["missing_bars"]),
            "m5_missing_ratio": float(quality["missing_ratio"]),
            "m5_closure_gap_count": int(quality["closure_gap_count"]),
        }
        row.update(_h1_context(decision_time, h1, h1_times))
        events.append(row)

    frame = pd.DataFrame(events)
    if frame.empty:
        return frame, diagnostics
    frame.sort_values(["decision_time", "event_id"], kind="stable", inplace=True)
    frame.reset_index(drop=True, inplace=True)
    if frame["event_id"].duplicated().any():
        raise ValueError("DoubleTop event_idが重複しています")
    return frame, diagnostics


def validate_production_context_equivalence(
    pair_name: str,
    m5: pd.DataFrame,
    h1: pd.DataFrame,
    events: pd.DataFrame,
    sample_count: int = 30,
) -> dict[str, Any]:
    """候補だけ正式CandleAnalysis contextへ通し、本番v1と照合する。"""
    if events.empty:
        return {
            "checked": 0,
            "mismatches": 0,
            "core_version": double_top_core.CORE_VERSION_V1,
        }
    pair = gene.currency_pair(pair_name)
    h1_times = h1["time_jp_dt"].to_numpy(dtype="datetime64[ns]", copy=False)
    eligible_positions = []
    for position, decision_value in enumerate(events["decision_time"]):
        latest_h1_start = np.datetime64(
            pd.Timestamp(decision_value) - pd.Timedelta(hours=1),
            "ns",
        )
        completed_h1_count = int(
            np.searchsorted(h1_times, latest_h1_start, side="right")
        )
        if completed_h1_count >= H1_HISTORY_BARS:
            eligible_positions.append(position)
    if not eligible_positions:
        raise ValueError("本番context照合に必要なH1履歴がありません")
    sample_positions = np.unique(
        np.linspace(
            0,
            len(eligible_positions) - 1,
            min(sample_count, len(eligible_positions)),
            dtype=int,
        )
    )
    checked = 0
    numeric_fields = {
        "t1_price": "t1_price",
        "neckline_price": "neckline_price",
        "t2_price": "t2_price",
        "break_close": "break_close",
        "previous_close": "previous_close",
        "height_price": "height_price",
        "height_pips": "height_pips",
        "top_gap_pips": "top_gap_pips",
        "top_gap_ratio": "top_gap_ratio",
        "t1_t2_minutes": "formation_minutes",
        "t2_break_minutes": "t2_break_minutes",
        "break_depth_pips": "break_depth_pips",
    }
    count_fields = (
        "t1_foot_count",
        "neckline_foot_count",
        "t2_foot_count",
        "decline_foot_count",
    )
    time_fields = ("t1_time", "neckline_time", "t2_time", "break_time")
    for sample_position in sample_positions:
        event_position = eligible_positions[int(sample_position)]
        event = events.iloc[event_position]
        decision_time = pd.Timestamp(event["decision_time"])
        m5_index = int(event["source_row_index"])
        m5_context_frame = m5.iloc[
            m5_index - M5_HISTORY_BARS + 1:m5_index + 1
        ]
        latest_h1_start = np.datetime64(
            decision_time - pd.Timedelta(hours=1),
            "ns",
        )
        h1_end = int(np.searchsorted(h1_times, latest_h1_start, side="right"))
        h1_context_frame = h1.iloc[
            h1_end - H1_HISTORY_BARS:h1_end
        ]
        context = candleAnalysis.build_decision_context_from_frames(
            pair_name,
            decision_time,
            m5_context_frame,
            h1_context_frame,
            current_price=float(event["break_close"]),
            current_price_source="latest_completed_m5_close",
            mode="inspection",
            require_complete_flags=False,
            m5_history=M5_HISTORY_BARS,
            h1_history=H1_HISTORY_BARS,
        )
        if (
            context.m5_completed_df_r["time_jp_dt"] + pd.Timedelta(minutes=5)
            > decision_time
        ).any():
            raise ValueError("未来のM5が本番context照合へ混入しました")
        if (
            context.h1_completed_df_r["time_jp_dt"] + pd.Timedelta(hours=1)
            > decision_time
        ).any():
            raise ValueError("未来のH1が本番context照合へ混入しました")
        actual = live_double_top.detect_candidate(
            context,
            GRID_DISCOVERY_POLICY_V1,
        )
        if actual is None:
            raise ValueError("高速候補を本番DoubleTop v1が再現できません")
        for field in time_fields:
            if pd.Timestamp(getattr(actual, field)) != pd.Timestamp(event[field]):
                raise ValueError("高速候補と本番contextの時刻が不一致: " + field)
        for field in count_fields:
            if int(getattr(actual, field)) != int(event[field]):
                raise ValueError("高速候補と本番contextのfoot countが不一致: " + field)
        for candidate_field, event_field in numeric_fields.items():
            if not math.isclose(
                float(getattr(actual, candidate_field)),
                float(event[event_field]),
                rel_tol=1e-9,
                abs_tol=pair.pip_value / 10,
            ):
                raise ValueError(
                    "高速候補と本番contextの数値が不一致: "
                    + candidate_field
                )
        checked += 1
    return {
        "checked": checked,
        "mismatches": 0,
        "core_version": double_top_core.CORE_VERSION_V1,
        "context_builder": "CandleAnalysis.build_decision_context_from_frames",
        "production_detector": "f_ダブルトップ.detect_candidate",
    }


def _execution_combo_id(
        tp_height_multiplier: float,
        stop_buffer_pips: float,
        trade_timeout_minutes: int,
) -> str:
    return (
        f"TP{float(tp_height_multiplier):g}H_"
        f"LCtop{float(stop_buffer_pips):g}p_"
        f"T{int(trade_timeout_minutes)}m"
    )


def live_trial_execution_combo() -> ExecutionCombo:
    policy = live_double_top.LIVE_TRIAL_POLICY_V1
    return ExecutionCombo(
        combo_id=_execution_combo_id(
            policy.target_height_multiplier,
            policy.stop_buffer_pips,
            policy.trade_timeout_min,
        ),
        tp_height_multiplier=float(policy.target_height_multiplier),
        stop_buffer_pips=float(policy.stop_buffer_pips),
        trade_timeout_minutes=int(policy.trade_timeout_min),
    )


def execution_combos() -> list[ExecutionCombo]:
    combos: list[ExecutionCombo] = []
    for tp_multiplier in TP_HEIGHT_MULTIPLIERS:
        for stop_buffer in STOP_BUFFER_PIPS:
            for timeout in TRADE_TIMEOUT_MINUTES:
                combos.append(
                    ExecutionCombo(
                        combo_id=_execution_combo_id(
                            tp_multiplier,
                            stop_buffer,
                            timeout,
                        ),
                        tp_height_multiplier=float(tp_multiplier),
                        stop_buffer_pips=float(stop_buffer),
                        trade_timeout_minutes=int(timeout),
                    )
                )
    return combos


def _single_condition_specs() -> list[ConditionSpec]:
    specs = [
        ConditionSpec("ALL", "all", "全候補", operator="all"),
        ConditionSpec(
            "CURRENT_TRIAL_V1",
            "current_policy",
            "現在のtrial_v1形成条件",
            operator="current_policy",
        ),
    ]

    def thresholds(
        family: str,
        field: str,
        operator: str,
        values: Iterable[float],
        label: str,
    ) -> None:
        symbol = ">=" if operator == "ge" else "<="
        for value in values:
            specs.append(
                ConditionSpec(
                    f"DT::{family}::{operator}{float(value):g}",
                    family,
                    f"{label}{symbol}{float(value):g}",
                    field,
                    operator,
                    float(value),
                )
            )

    thresholds("t1_foot_min", "t1_foot_count", "ge", (1, 2, 3, 4, 5), "T1 foot ")
    thresholds("t2_foot_min", "t2_foot_count", "ge", (1, 2, 3, 4, 5), "T2 foot ")
    thresholds("both_top_foot_min", "both_top_foot_min", "ge", (1, 2, 3, 4, 5), "両トップfoot ")
    thresholds("decline_foot_min", "decline_foot_count", "ge", (2, 3, 4, 5, 6), "割れ脚foot ")
    thresholds("height_min", "height_pips", "ge", (4, 6, 8, 10, 15, 20), "H(pips) ")
    thresholds("height_max", "height_pips", "le", (20, 30, 45, 60, 90), "H(pips) ")
    thresholds("top_gap_max", "top_gap_pips", "le", (1, 2, 3, 4, 5, 8), "トップ差(pips) ")
    thresholds("top_gap_ratio_max", "top_gap_ratio", "le", (0.10, 0.15, 0.20, 0.25, 0.30, 0.40), "トップ差/H ")
    thresholds("formation_min", "formation_minutes", "ge", (15, 30, 60, 120), "T1-T2分 ")
    thresholds("formation_max", "formation_minutes", "le", (120, 240, 360, 720), "T1-T2分 ")
    thresholds("t2_break_max", "t2_break_minutes", "le", (10, 20, 30, 60, 120), "T2-割れ分 ")
    thresholds("break_depth_min", "break_depth_pips", "ge", (0, 0.5, 1, 2, 3), "ネック割れ深さ(pips) ")
    thresholds("break_body_a_min", "break_body_a", "ge", (0.5, 1, 1.5, 2), "割れ足body/A ")
    thresholds("height_a_min", "height_a", "ge", (1, 1.5, 2, 3, 4), "H/A ")
    thresholds("quality_max", "m5_missing_ratio", "le", (0, 0.01, 0.05, 0.10, 0.25), "M5欠損率 ")

    categories = {
        "top_relation": ("T2_LOWER", "T2_EQUAL", "T2_HIGHER"),
        "session": ("ASIA", "LONDON", "NEW_YORK"),
        "weekday": ("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY"),
        "m5_rsi_bin": ("<35", "35-44", "45-54", "55-64", "65+"),
        "m5_range_bin": ("<3", "3-4", "5-7", "8-11", "12+"),
        "h1_latest_direction": (-1, 0, 1),
        "h1_two_sequence": ("-1|-1", "-1|1", "1|-1", "1|1"),
        "h1_trend3_direction": (-1, 0, 1),
        "h1_rsi_bin": ("<35", "35-44", "45-54", "55-64", "65+"),
    }
    for field, values in categories.items():
        family = field
        for value in values:
            specs.append(
                ConditionSpec(
                    f"DT::{family}::eq{value}",
                    family,
                    f"{field}={value}",
                    field,
                    "eq",
                    value,
                )
            )
    return specs


def _condition_mask(frame: pd.DataFrame, spec: ConditionSpec) -> np.ndarray:
    if spec.operator == "all":
        return np.ones(len(frame), dtype=bool)
    if spec.operator == "current_policy":
        pair_name = str(frame.iloc[0]["pair"])
        return double_top_core.frame_policy_mask_v1(
            frame,
            gene.currency_pair(pair_name),
            live_double_top.LIVE_TRIAL_POLICY_V1,
        )
    if spec.components:
        raise ValueError("interaction mask requires component masks")
    series = frame[spec.field]
    if spec.operator == "ge":
        return np.asarray(pd.to_numeric(series, errors="coerce").ge(float(spec.value)), dtype=bool)
    if spec.operator == "le":
        return np.asarray(pd.to_numeric(series, errors="coerce").le(float(spec.value)), dtype=bool)
    if spec.operator == "eq":
        return np.asarray(series.eq(spec.value), dtype=bool)
    raise ValueError(f"unknown condition operator: {spec.operator}")


def build_condition_catalog(
    events: pd.DataFrame,
) -> tuple[list[ConditionSpec], dict[str, np.ndarray]]:
    specs: list[ConditionSpec] = []
    masks: dict[str, np.ndarray] = {}
    by_family: dict[str, list[ConditionSpec]] = {}
    for spec in _single_condition_specs():
        mask = _condition_mask(events, spec)
        if not mask.any():
            continue
        specs.append(spec)
        masks[spec.condition_id] = mask
        by_family.setdefault(spec.family, []).append(spec)

    for left_position, left_family in enumerate(CORE_INTERACTION_FAMILIES):
        for right_family in CORE_INTERACTION_FAMILIES[left_position + 1:]:
            for left in by_family.get(left_family, []):
                for right in by_family.get(right_family, []):
                    mask = masks[left.condition_id] & masks[right.condition_id]
                    if int(mask.sum()) < MIN_INTERACTION_EVENTS:
                        continue
                    spec = ConditionSpec(
                        condition_id=f"{left.condition_id}&&{right.condition_id}",
                        family=f"{left_family}_X_{right_family}",
                        label=f"{left.label} ＆ {right.label}",
                        operator="interaction",
                        components=(left.condition_id, right.condition_id),
                    )
                    specs.append(spec)
                    masks[spec.condition_id] = mask
    return specs, masks


def _unknown_missing_count(previous: pd.Timestamp, following: pd.Timestamp) -> int:
    difference = following - previous
    if difference <= pd.Timedelta(seconds=5):
        return 0
    if is_expected_market_closed_gap(previous, following):
        return 0
    steps = int(difference // pd.Timedelta(seconds=5))
    return max(steps - 1, 0)


class MarketPathInspector:
    """S5の小規模欠損を許容する、成行売り専用の結果判定。"""

    def __init__(self, pair_name: str, source: Path, period_end: dt.datetime):
        self.pair = gene.currency_pair(pair_name)
        self.base, self.metadata = _load_typed_s5_inspector(source, self.pair)
        self.period_end = pd.Timestamp(period_end)
        self.end_index = int(
            np.searchsorted(
                self.base.times,
                np.datetime64(self.period_end, "ns"),
                side="left",
            )
        )
        self.half_spread = self.pair.pips_to_price(SPREAD_PIPS / 2.0)

    def prepare(
        self,
        decision_time: Any,
        max_timeout_minutes: int,
    ) -> PreparedMarketPath:
        decision = pd.Timestamp(decision_time)
        start_index = int(
            np.searchsorted(
                self.base.times,
                np.datetime64(decision, "ns"),
                side="left",
            )
        )
        if start_index >= self.end_index:
            return PreparedMarketPath(
                decision,
                None,
                None,
                np.asarray([], dtype="datetime64[ns]"),
                np.asarray([], dtype=float),
                np.asarray([], dtype=float),
                np.asarray([], dtype=float),
                np.asarray([], dtype=np.int64),
                0,
                self.period_end,
                "no_s5_at_decision",
            )
        max_deadline = decision + pd.Timedelta(minutes=max_timeout_minutes)
        boundary_index = int(
            np.searchsorted(
                self.base.times,
                np.datetime64(max_deadline, "ns"),
                side="left",
            )
        )
        # タイムアウト時点の最初のS5始値まであればよい。週末をまたぐ場合も
        # searchsortedが次の市場再開足を直接指すため、余分な数日分は読まない。
        desired_end_index = min(boundary_index + 1, self.end_index)
        times = self.base.times[start_index:desired_end_index]
        if not len(times):
            return PreparedMarketPath(
                decision,
                None,
                None,
                times,
                np.asarray([], dtype=float),
                np.asarray([], dtype=float),
                np.asarray([], dtype=float),
                np.asarray([], dtype=np.int64),
                0,
                self.period_end,
                "empty_s5_path",
            )
        first_time = pd.Timestamp(times[0])
        initial_missing = _unknown_missing_count(
            decision - pd.Timedelta(seconds=5),
            first_time,
        )
        differences = np.diff(times).astype("timedelta64[s]").astype(np.int64)
        missing_each = np.zeros(len(times), dtype=np.int64)
        for offset in np.flatnonzero(differences > 5):
            previous = pd.Timestamp(times[int(offset)])
            following = pd.Timestamp(times[int(offset) + 1])
            missing_each[int(offset) + 1] = _unknown_missing_count(previous, following)
        missing_prefix = np.cumsum(missing_each)
        opens_mid = self.base.opens[start_index:desired_end_index]
        entry_price = float(opens_mid[0] - self.half_spread)
        return PreparedMarketPath(
            decision,
            first_time,
            entry_price,
            times,
            self.base.opens[start_index:desired_end_index] + self.half_spread,
            self.base.highs[start_index:desired_end_index] + self.half_spread,
            self.base.lows[start_index:desired_end_index] + self.half_spread,
            missing_prefix,
            initial_missing,
            self.period_end,
        )

    def inspect_combos(
        self,
        event: pd.Series,
        combos: list[ExecutionCombo],
    ) -> list[dict[str, Any]]:
        max_timeout = max(combo.trade_timeout_minutes for combo in combos)
        prepared = self.prepare(event["decision_time"], max_timeout)
        base_row = {
            "event_id": event["event_id"],
            "pair": event["pair"],
            "decision_time": event["decision_time"],
            "entry_time": prepared.entry_time,
            "entry_price": prepared.entry_price,
        }
        if prepared.reason is not None or prepared.entry_price is None:
            return [
                {
                    **base_row,
                    **asdict(combo),
                    "status": prepared.reason or "no_path",
                    "result": "incomplete",
                    "exit_time": pd.NaT,
                    "target_price": np.nan,
                    "stop_price": np.nan,
                    "tp_pips": np.nan,
                    "lc_pips": np.nan,
                    "effective_rr": np.nan,
                    "result_pips": np.nan,
                    "result_yen": np.nan,
                    "path_missing_ratio": 1.0,
                    "both_same_s5": False,
                }
                for combo in combos
            ]

        entry = float(prepared.entry_price)
        height_price = float(event["height_price"])
        targets = {
            multiplier: double_top_core.target_price_v1(
                self.pair,
                float(event["neckline_price"]),
                height_price,
                multiplier,
            )
            for multiplier in {combo.tp_height_multiplier for combo in combos}
        }
        stops = {
            buffer_pips: double_top_core.stop_price_v1(
                self.pair,
                float(event["t1_price"]),
                float(event["t2_price"]),
                buffer_pips,
            )
            for buffer_pips in {combo.stop_buffer_pips for combo in combos}
        }

        target_first: dict[float, int | None] = {}
        for multiplier, target in targets.items():
            reached = np.flatnonzero(prepared.lows_ask <= target)
            target_first[multiplier] = int(reached[0]) if reached.size else None
        stop_first: dict[float, int | None] = {}
        for buffer, stop in stops.items():
            reached = np.flatnonzero(prepared.highs_ask >= stop)
            stop_first[buffer] = int(reached[0]) if reached.size else None

        results: list[dict[str, Any]] = []
        for combo in combos:
            target = targets[combo.tp_height_multiplier]
            stop = stops[combo.stop_buffer_pips]
            tp_pips = float(self.pair.price_to_pips(entry - target))
            lc_pips = float(self.pair.price_to_pips(stop - entry))
            common = {
                **base_row,
                **asdict(combo),
                "target_price": target,
                "stop_price": stop,
                "tp_pips": tp_pips,
                "lc_pips": lc_pips,
                "effective_rr": tp_pips / lc_pips if lc_pips > 0 else np.nan,
            }
            if tp_pips < 1.0 or lc_pips < 1.0:
                results.append(
                    {
                        **common,
                        "status": "invalid_order_width",
                        "result": "invalid",
                        "exit_time": pd.NaT,
                        "result_pips": np.nan,
                        "result_yen": np.nan,
                        "path_missing_ratio": np.nan,
                        "both_same_s5": False,
                    }
                )
                continue
            boundary = prepared.boundary_index(combo.trade_timeout_minutes)
            if boundary is None:
                results.append(
                    {
                        **common,
                        "status": "incomplete_period_boundary",
                        "result": "incomplete",
                        "exit_time": pd.NaT,
                        "result_pips": np.nan,
                        "result_yen": np.nan,
                        "path_missing_ratio": np.nan,
                        "both_same_s5": False,
                    }
                )
                continue
            tp_index = target_first[combo.tp_height_multiplier]
            stop_index = stop_first[combo.stop_buffer_pips]
            hit_candidates = [
                index
                for index in (tp_index, stop_index)
                if index is not None and index < boundary
            ]
            first_hit = min(hit_candidates) if hit_candidates else None
            outcome_index = first_hit if first_hit is not None else boundary
            missing_ratio = prepared.missing_ratio_through(outcome_index)
            if missing_ratio >= MAX_MISSING_RATIO:
                results.append(
                    {
                        **common,
                        "status": "half_or_more_s5_missing",
                        "result": "incomplete",
                        "exit_time": pd.NaT,
                        "result_pips": np.nan,
                        "result_yen": np.nan,
                        "path_missing_ratio": missing_ratio,
                        "both_same_s5": False,
                    }
                )
                continue

            both_same = bool(
                first_hit is not None
                and tp_index == first_hit
                and stop_index == first_hit
            )
            if first_hit is not None and (stop_index == first_hit):
                open_exit = float(prepared.opens_ask[first_hit])
                actual_exit = max(stop, open_exit) if open_exit >= stop else stop
                result_name = "both_same_s5_lc_assumed" if both_same else "lc"
                result_pips = float(self.pair.price_to_pips(entry - actual_exit))
                exit_time = pd.Timestamp(prepared.times[first_hit])
            elif first_hit is not None:
                result_name = "tp"
                result_pips = tp_pips
                exit_time = pd.Timestamp(prepared.times[first_hit])
            else:
                boundary_open = float(prepared.opens_ask[boundary])
                if boundary_open >= stop:
                    result_name = "lc_gap_at_timeout"
                    result_pips = float(self.pair.price_to_pips(entry - boundary_open))
                elif boundary_open <= target:
                    result_name = "tp_gap_at_timeout"
                    result_pips = tp_pips
                else:
                    result_name = "timeout"
                    result_pips = float(self.pair.price_to_pips(entry - boundary_open))
                exit_time = pd.Timestamp(prepared.times[boundary])
            result_yen = float(result_pips / lc_pips * RISK_YEN)
            results.append(
                {
                    **common,
                    "status": "complete",
                    "result": result_name,
                    "exit_time": exit_time,
                    "result_pips": result_pips,
                    "result_yen": result_yen,
                    "path_missing_ratio": missing_ratio,
                    "both_same_s5": both_same,
                }
            )
        return results


def evaluate_outcomes(
    pair_name: str,
    events: pd.DataFrame,
    combos: list[ExecutionCombo],
    s5_source: Path,
    period_start: dt.datetime,
    period_end: dt.datetime,
    phase: str,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    inspector = MarketPathInspector(pair_name, s5_source, period_end)
    reporter = TwoMonthProgress(
        pair_name,
        phase,
        period_start,
        period_end,
        len(events),
    )
    rows: list[dict[str, Any]] = []
    for position, (_, event) in enumerate(events.iterrows(), start=1):
        reporter.update(event["decision_time"], position)
        rows.extend(inspector.inspect_combos(event, combos))
    outcome_frame = pd.DataFrame(rows)
    metadata = dict(inspector.metadata)
    del inspector
    gc.collect()
    return outcome_frame, metadata


def _outcome_matrices(
    events: pd.DataFrame,
    combos: list[ExecutionCombo],
    outcomes: pd.DataFrame,
) -> dict[str, np.ndarray]:
    event_index = {event_id: index for index, event_id in enumerate(events["event_id"])}
    combo_index = {combo.combo_id: index for index, combo in enumerate(combos)}
    shape = (len(events), len(combos))
    matrices = {
        "result_pips": np.full(shape, np.nan),
        "result_yen": np.full(shape, np.nan),
        "effective_rr": np.full(shape, np.nan),
    }
    for row in outcomes.itertuples(index=False):
        event_position = event_index[str(row.event_id)]
        combo_position = combo_index[str(row.combo_id)]
        for field in matrices:
            value = getattr(row, field)
            matrices[field][event_position, combo_position] = (
                float(value) if pd.notna(value) else np.nan
            )
    return matrices


def _profit_factor(values: np.ndarray) -> float:
    positive = float(values[values > 0].sum())
    negative = float(values[values < 0].sum())
    if negative == 0:
        return math.inf if positive > 0 else 0.0
    return positive / abs(negative)


def aggregate_grid(
    events: pd.DataFrame,
    specs: list[ConditionSpec],
    masks: dict[str, np.ndarray],
    combos: list[ExecutionCombo],
    matrices: dict[str, np.ndarray],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    pips_matrix = matrices["result_pips"]
    yen_matrix = matrices["result_yen"]
    rr_matrix = matrices["effective_rr"]
    for spec in specs:
        mask = masks[spec.condition_id]
        event_count = int(mask.sum())
        condition_pips = pips_matrix[mask]
        condition_yen = yen_matrix[mask]
        condition_rr = rr_matrix[mask]
        for combo_position, combo in enumerate(combos):
            pips = condition_pips[:, combo_position]
            yen = condition_yen[:, combo_position]
            rr = condition_rr[:, combo_position]
            complete = np.isfinite(pips) & np.isfinite(yen)
            completed_count = int(complete.sum())
            complete_pips = pips[complete]
            complete_yen = yen[complete]
            wins = complete_pips > 0
            losses = complete_pips < 0
            rows.append(
                {
                    **asdict(spec),
                    **asdict(combo),
                    "event_count": event_count,
                    "completed_count": completed_count,
                    "outcome_coverage_rate": (
                        completed_count / event_count if event_count else 0.0
                    ),
                    "win_count": int(wins.sum()),
                    "loss_count": int(losses.sum()),
                    "win_rate": float(wins.mean()) if completed_count else np.nan,
                    "average_win_pips": (
                        float(complete_pips[wins].mean()) if wins.any() else np.nan
                    ),
                    "average_loss_pips": (
                        float(complete_pips[losses].mean()) if losses.any() else np.nan
                    ),
                    "average_result_pips": (
                        float(complete_pips.mean()) if completed_count else np.nan
                    ),
                    "sum_pips": float(complete_pips.sum()),
                    "sum_yen": float(complete_yen.sum()),
                    "average_result_yen": (
                        float(complete_yen.mean()) if completed_count else np.nan
                    ),
                    "profit_factor_yen": _profit_factor(complete_yen),
                    "average_effective_rr": (
                        float(np.nanmean(rr[complete])) if completed_count else np.nan
                    ),
                }
            )
    return pd.DataFrame(rows)


def _monthly_metrics(
    events: pd.DataFrame,
    mask: np.ndarray,
    result_yen: np.ndarray,
) -> dict[str, Any]:
    complete = mask & np.isfinite(result_yen)
    if not complete.any():
        return {
            "active_month_count": 0,
            "positive_month_count": 0,
            "positive_month_rate": 0.0,
            "worst_month_yen": np.nan,
        }
    months = pd.to_datetime(events.loc[complete, "decision_time"]).dt.to_period("M")
    values = pd.Series(result_yen[complete], index=months.astype(str).to_numpy())
    monthly = values.groupby(level=0).sum()
    active = len(monthly)
    positive = int(monthly.gt(0).sum())
    return {
        "active_month_count": active,
        "positive_month_count": positive,
        "positive_month_rate": positive / active if active else 0.0,
        "worst_month_yen": float(monthly.min()) if active else np.nan,
    }


def select_top15(
    events: pd.DataFrame,
    grid: pd.DataFrame,
    masks: dict[str, np.ndarray],
    combos: list[ExecutionCombo],
    matrices: dict[str, np.ndarray],
) -> pd.DataFrame:
    combo_index = {combo.combo_id: index for index, combo in enumerate(combos)}
    eligible = grid[
        grid["completed_count"].ge(MIN_COMPLETED)
        & grid["outcome_coverage_rate"].ge(MIN_COVERAGE)
        & grid["profit_factor_yen"].ge(MIN_PROFIT_FACTOR)
        & grid["sum_yen"].gt(0)
        & grid["sum_pips"].gt(0)
    ].copy()
    if eligible.empty:
        return eligible
    eligible.sort_values(
        ["sum_yen", "profit_factor_yen", "completed_count"],
        ascending=[False, False, False],
        kind="stable",
        inplace=True,
    )
    stability_rows: list[dict[str, Any]] = []
    for row in eligible.head(3000).itertuples(index=False):
        index = combo_index[str(row.combo_id)]
        stability_rows.append(
            {
                "condition_id": row.condition_id,
                "combo_id": row.combo_id,
                **_monthly_metrics(
                    events,
                    masks[str(row.condition_id)],
                    matrices["result_yen"][:, index],
                ),
            }
        )
    stability = pd.DataFrame(stability_rows)
    eligible = eligible.merge(stability, on=["condition_id", "combo_id"], how="inner")
    strict = eligible[
        eligible["active_month_count"].ge(MIN_ACTIVE_MONTHS)
        & eligible["positive_month_rate"].ge(MIN_POSITIVE_MONTH_RATE)
    ].copy()
    strict["selection_tier"] = "strict"
    if len(strict) < TOP_COUNT:
        existing = set(zip(strict["condition_id"], strict["combo_id"]))
        fallback = eligible[
            [
                (condition_id, combo_id) not in existing
                for condition_id, combo_id in zip(
                    eligible["condition_id"],
                    eligible["combo_id"],
                )
            ]
        ].copy()
        fallback["selection_tier"] = "fallback_without_month_guard"
        strict = pd.concat([strict, fallback], ignore_index=True)
    strict.sort_values(
        ["sum_yen", "profit_factor_yen", "completed_count"],
        ascending=[False, False, False],
        kind="stable",
        inplace=True,
    )
    top = strict.head(TOP_COUNT).copy()
    top.insert(0, "rank", np.arange(1, len(top) + 1))
    return top


def _spec_lookup(specs: list[ConditionSpec]) -> dict[str, ConditionSpec]:
    return {spec.condition_id: spec for spec in specs}


def _event_matches_spec(
    event_frame: pd.DataFrame,
    spec: ConditionSpec,
    lookup: dict[str, ConditionSpec],
) -> np.ndarray:
    if spec.components:
        mask = np.ones(len(event_frame), dtype=bool)
        for component in spec.components:
            mask &= _condition_mask(event_frame, lookup[component])
        return mask
    return _condition_mask(event_frame, spec)


def _metric_summary(values_pips: np.ndarray, values_yen: np.ndarray) -> dict[str, Any]:
    complete = np.isfinite(values_pips) & np.isfinite(values_yen)
    pips = values_pips[complete]
    yen = values_yen[complete]
    wins = pips > 0
    losses = pips < 0
    return {
        "completed_count": int(complete.sum()),
        "win_count": int(wins.sum()),
        "loss_count": int(losses.sum()),
        "win_rate": float(wins.mean()) if len(pips) else np.nan,
        "average_win_pips": float(pips[wins].mean()) if wins.any() else np.nan,
        "average_loss_pips": float(pips[losses].mean()) if losses.any() else np.nan,
        "sum_pips": float(pips.sum()),
        "sum_yen": float(yen.sum()),
        "profit_factor_yen": _profit_factor(yen),
    }


def build_oos_top15_table(
    oos_events: pd.DataFrame,
    top15: pd.DataFrame,
    specs: list[ConditionSpec],
    combos: list[ExecutionCombo],
    matrices: dict[str, np.ndarray],
) -> tuple[pd.DataFrame, dict[int, np.ndarray]]:
    lookup = _spec_lookup(specs)
    combo_index = {combo.combo_id: index for index, combo in enumerate(combos)}
    rows: list[dict[str, Any]] = []
    rank_masks: dict[int, np.ndarray] = {}
    for row in top15.itertuples(index=False):
        spec = lookup[str(row.condition_id)]
        mask = _event_matches_spec(oos_events, spec, lookup)
        rank_masks[int(row.rank)] = mask
        index = combo_index[str(row.combo_id)]
        metrics = _metric_summary(
            np.where(mask, matrices["result_pips"][:, index], np.nan),
            np.where(mask, matrices["result_yen"][:, index], np.nan),
        )
        rows.append(
            {
                "rank": int(row.rank),
                "condition_id": row.condition_id,
                "condition_label": row.label,
                "combo_id": row.combo_id,
                "selection_tier": row.selection_tier,
                "train_completed_count": int(row.completed_count),
                "train_win_rate": float(row.win_rate),
                "train_average_win_pips": float(row.average_win_pips),
                "train_sum_pips": float(row.sum_pips),
                "train_sum_yen": float(row.sum_yen),
                "train_profit_factor_yen": float(row.profit_factor_yen),
                "oos_candidate_count": int(mask.sum()),
                **{f"oos_{key}": value for key, value in metrics.items()},
            }
        )
    return pd.DataFrame(rows), rank_masks


def combined_replay(
    pair_name: str,
    events: pd.DataFrame,
    top15: pd.DataFrame,
    rank_masks: dict[int, np.ndarray],
    outcomes: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    pair = gene.currency_pair(pair_name)
    outcome_lookup = {
        (str(row.event_id), str(row.combo_id)): row
        for row in outcomes.itertuples(index=False)
    }
    active: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    blocked_slots = 0
    blocked_similar = 0
    no_policy = 0
    for event_position, event in events.iterrows():
        decision = pd.Timestamp(event["decision_time"])
        active = [item for item in active if pd.Timestamp(item["exit_time"]) > decision]
        selected = None
        for policy in top15.itertuples(index=False):
            if bool(rank_masks[int(policy.rank)][event_position]):
                selected = policy
                break
        if selected is None:
            no_policy += 1
            continue
        outcome = outcome_lookup[(str(event["event_id"]), str(selected.combo_id))]
        entry_price = float(outcome.entry_price) if pd.notna(outcome.entry_price) else np.nan
        status = str(outcome.status)
        blocked_reason = None
        if len(active) >= NORMAL_PRIORITY_SLOT_COUNT:
            blocked_reason = "normal_slot_full"
            blocked_slots += 1
        elif math.isfinite(entry_price) and any(
            abs(pair.price_to_pips(entry_price - float(item["entry_price"])))
            <= SIMILAR_ACTIVE_PIPS
            for item in active
        ):
            blocked_reason = "similar_active_sell"
            blocked_similar += 1
        accepted = blocked_reason is None
        if accepted:
            exit_time = (
                pd.Timestamp(outcome.exit_time)
                if pd.notna(outcome.exit_time)
                else decision + pd.Timedelta(minutes=int(selected.trade_timeout_minutes))
            )
            active.append({"entry_price": entry_price, "exit_time": exit_time})
        rows.append(
            {
                "event_id": event["event_id"],
                "decision_time": decision,
                "selected_rank": int(selected.rank),
                "condition_id": selected.condition_id,
                "condition_label": selected.label,
                "combo_id": selected.combo_id,
                "accepted": accepted,
                "blocked_reason": blocked_reason,
                "path_status": status,
                "entry_time": outcome.entry_time,
                "entry_price": outcome.entry_price,
                "exit_time": outcome.exit_time,
                "result": outcome.result,
                "result_pips": outcome.result_pips if accepted else np.nan,
                "result_yen": outcome.result_yen if accepted else np.nan,
                "tp_pips": outcome.tp_pips,
                "lc_pips": outcome.lc_pips,
                "path_missing_ratio": outcome.path_missing_ratio,
            }
        )
    frame = pd.DataFrame(rows)
    if frame.empty:
        metrics = _metric_summary(np.asarray([]), np.asarray([]))
    else:
        metrics = _metric_summary(
            pd.to_numeric(frame["result_pips"], errors="coerce").to_numpy(dtype=float),
            pd.to_numeric(frame["result_yen"], errors="coerce").to_numpy(dtype=float),
        )
    metrics.update(
        {
            "selected_event_count": len(frame),
            "accepted_count": int(frame["accepted"].sum()) if len(frame) else 0,
            "blocked_slot_count": blocked_slots,
            "blocked_similar_count": blocked_similar,
            "no_matching_top15_count": no_policy,
        }
    )
    return frame, metrics


def current_policy_replay(
    pair_name: str,
    events: pd.DataFrame,
    specs: list[ConditionSpec],
    outcomes: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    baseline_spec = _spec_lookup(specs)["CURRENT_TRIAL_V1"]
    mask = _condition_mask(events, baseline_spec)
    baseline_combo = live_trial_execution_combo()
    policy_frame = pd.DataFrame(
        [
            {
                "rank": 1,
                "condition_id": baseline_spec.condition_id,
                "label": baseline_spec.label,
                "combo_id": baseline_combo.combo_id,
                "trade_timeout_minutes": baseline_combo.trade_timeout_minutes,
            }
        ]
    )
    return combined_replay(
        pair_name,
        events,
        policy_frame,
        {1: mask},
        outcomes,
    )


def _write_progress(
    path: Path,
    pair: str,
    status: str,
    phase: str,
    started: float,
    **extra: Any,
) -> None:
    payload = {
        "version": VERSION,
        "pair": pair,
        "status": status,
        "phase": phase,
        "updated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "elapsed_minutes": round((time.monotonic() - started) / 60.0, 2),
        **extra,
    }
    _atomic_json(path, payload)


def run_pair(
    pair_name: str,
    train_start: dt.datetime,
    train_end: dt.datetime,
    oos_start: dt.datetime,
    oos_end: dt.datetime,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    pair_name = str(pair_name).upper()
    output_dir = Path(output_dir or tk.folder_path)
    paths = _output_paths(
        output_dir,
        pair_name,
        train_start,
        train_end,
        oos_start,
        oos_end,
    )
    started = time.monotonic()
    _write_progress(paths["progress"], pair_name, "running", "load", started)
    _notify(
        "【DoubleTop総当たり検証開始】",
        f"- 通貨ペア: {pair_name}",
        f"- 条件探索: {train_start:%Y/%m/%d}〜{train_end:%Y/%m/%d}",
        f"- 固定リプレイ: {oos_start:%Y/%m/%d}〜{oos_end:%Y/%m/%d}",
        f"- 売買条件数: {len(execution_combos())}",
        "- 未来足: 使用しない",
    )
    try:
        train_m5_source = _source_path(output_dir, "M5", pair_name, train_start, train_end)
        train_h1_source = _source_path(output_dir, "H1", pair_name, train_start, train_end)
        train_s5_source = _source_path(output_dir, "S5", pair_name, train_start, train_end)
        oos_m5_source = _source_path(output_dir, "M5", pair_name, oos_start, oos_end)
        oos_h1_source = _source_path(output_dir, "H1", pair_name, oos_start, oos_end)
        oos_s5_source = _source_path(output_dir, "S5", pair_name, oos_start, oos_end)

        train_m5 = _read_candles(train_m5_source, "train M5")
        train_h1 = _read_candles(train_h1_source, "train H1")
        _write_progress(paths["progress"], pair_name, "running", "train_event_scan", started)
        train_events, train_diagnostics = generate_events(
            pair_name,
            train_start,
            train_end,
            train_m5,
            train_h1,
            "条件探索・M5形成抽出",
        )
        if train_events.empty:
            raise ValueError(f"{pair_name}の探索期間にDoubleTop候補がありません")
        train_context_check = validate_production_context_equivalence(
            pair_name,
            train_m5,
            train_h1,
            train_events,
        )
        _atomic_csv(paths["train_events"], train_events)

        combos = execution_combos()
        specs, masks = build_condition_catalog(train_events)
        _write_progress(paths["progress"], pair_name, "running", "train_s5_grid", started)
        train_outcomes, train_s5_metadata = evaluate_outcomes(
            pair_name,
            train_events,
            combos,
            train_s5_source,
            train_start,
            train_end,
            "条件探索・S5結果付け",
        )
        _atomic_csv(paths["train_outcomes"], train_outcomes)
        train_matrices = _outcome_matrices(train_events, combos, train_outcomes)
        grid = aggregate_grid(train_events, specs, masks, combos, train_matrices)
        _atomic_csv(paths["grid"], grid)
        top15 = select_top15(train_events, grid, masks, combos, train_matrices)
        if top15.empty:
            raise ValueError(f"{pair_name}は最低条件を満たす上位条件がありません")
        _atomic_csv(paths["top15"], top15)

        del train_outcomes, train_matrices, grid, train_h1
        gc.collect()

        oos_m5 = _read_candles(oos_m5_source, "oos M5")
        oos_h1 = _read_candles(oos_h1_source, "oos H1")
        _write_progress(paths["progress"], pair_name, "running", "oos_event_scan", started)
        oos_events, oos_diagnostics = generate_events(
            pair_name,
            oos_start,
            oos_end,
            oos_m5,
            oos_h1,
            "固定リプレイ・M5形成抽出",
        )
        if oos_events.empty:
            raise ValueError(f"{pair_name}のリプレイ期間にDoubleTop候補がありません")
        oos_context_check = validate_production_context_equivalence(
            pair_name,
            oos_m5,
            oos_h1,
            oos_events,
        )
        _atomic_csv(paths["oos_events"], oos_events)

        live_combo = live_trial_execution_combo()
        needed_combo_ids = list(dict.fromkeys(
            list(top15["combo_id"].astype(str))
            + [live_combo.combo_id]
        ))
        combo_lookup = {combo.combo_id: combo for combo in combos}
        oos_combos = [combo_lookup[combo_id] for combo_id in needed_combo_ids]
        _write_progress(paths["progress"], pair_name, "running", "oos_s5_replay", started)
        oos_outcomes, oos_s5_metadata = evaluate_outcomes(
            pair_name,
            oos_events,
            oos_combos,
            oos_s5_source,
            oos_start,
            oos_end,
            "固定リプレイ・S5結果付け",
        )
        _atomic_csv(paths["oos_outcomes"], oos_outcomes)
        oos_matrices = _outcome_matrices(oos_events, oos_combos, oos_outcomes)
        oos_top15, rank_masks = build_oos_top15_table(
            oos_events,
            top15,
            specs,
            oos_combos,
            oos_matrices,
        )
        _atomic_csv(paths["oos_top15"], oos_top15)
        combined_trades, combined_summary = combined_replay(
            pair_name,
            oos_events,
            top15,
            rank_masks,
            oos_outcomes,
        )
        _atomic_csv(paths["oos_trades"], combined_trades)
        baseline_trades, baseline_summary = current_policy_replay(
            pair_name,
            oos_events,
            specs,
            oos_outcomes,
        )
        _atomic_csv(paths["oos_baseline"], baseline_trades)

        summary = {
            "version": VERSION,
            "pair": pair_name,
            "shared_logic": {
                "core_version": double_top_core.CORE_VERSION_V1,
                "discovery_policy_id": GRID_DISCOVERY_POLICY_V1.policy_id,
                "live_policy_id": live_double_top.LIVE_TRIAL_POLICY_V1.policy_id,
                "production_imports_validation": False,
                "fast_peak_scan": "candidate discovery only",
                "formal_context_audit": (
                    "CandleAnalysis.build_decision_context_from_frames"
                ),
            },
            "periods": {
                "train_start": train_start,
                "train_end_exclusive": train_end,
                "oos_start": oos_start,
                "oos_end_exclusive": oos_end,
            },
            "causality": {
                "decision_features": "completed M5/H1 only",
                "entry_price": "first S5 bid open at or after decision",
                "outcome_data": "S5 at or after decision only",
                "train_oos_overlap": False,
                "period_end_outcomes": "excluded when unresolved before end",
                "production_context_equivalence_train": train_context_check,
                "production_context_equivalence_oos": oos_context_check,
            },
            "missing_policy": {
                "unknown_missing_ratio_reject_at": MAX_MISSING_RATIO,
                "known_weekend_and_annual_holiday_closures": "allowed",
                "minor_recent_gaps": "allowed and counted",
            },
            "grid": {
                "single_and_interaction_condition_count": len(specs),
                "execution_combo_count": len(combos),
                "grid_row_count": len(specs) * len(combos),
                "top_count": len(top15),
                "risk_yen": RISK_YEN,
                "spread_pips": SPREAD_PIPS,
            },
            "train": {
                "event_count": len(train_events),
                "diagnostics": train_diagnostics,
                "s5": train_s5_metadata,
                "top15": top15.to_dict(orient="records"),
            },
            "oos": {
                "event_count": len(oos_events),
                "diagnostics": oos_diagnostics,
                "s5": oos_s5_metadata,
                "top15_independent": oos_top15.to_dict(orient="records"),
                "combined_top15": combined_summary,
                "current_trial_v1": baseline_summary,
            },
            "yen_note": (
                "損益円は各取引をLC時50円リスクに正規化した実現R×50円。"
                "将来のUSD/JPY換算レートは使わない。"
            ),
            "outputs": {name: str(path.resolve()) for name, path in paths.items()},
            "elapsed_minutes": round((time.monotonic() - started) / 60.0, 2),
        }
        _atomic_json(paths["summary"], summary)
        archived_residuals = _archive_residual_temp_and_logs(output_dir)
        _write_progress(
            paths["progress"],
            pair_name,
            "complete",
            "complete",
            started,
            train_events=len(train_events),
            oos_events=len(oos_events),
            top_count=len(top15),
            archived_residuals=archived_residuals,
        )
        _notify(
            "【DoubleTop総当たり検証完了】",
            f"- 通貨ペア: {pair_name}",
            f"- 探索候補: {len(train_events)}件",
            f"- 条件数: {len(specs)}件",
            f"- 条件×売買: {len(specs) * len(combos)}通り",
            f"- OOS採用取引: {combined_summary['completed_count']}件",
            f"- OOS勝率: {combined_summary['win_rate']:.1%}",
            f"- OOS平均勝ち: {combined_summary['average_win_pips']:.2f}pips",
            f"- OOS損益: {combined_summary['sum_yen']:.0f}円",
            f"- OOS合計: {combined_summary['sum_pips']:.2f}pips",
            f"- 現行trial_v1損益: {baseline_summary['sum_yen']:.0f}円",
        )
        return summary
    except Exception as error:
        _write_progress(
            paths["progress"],
            pair_name,
            "failed",
            "failed",
            started,
            error=f"{type(error).__name__}: {error}",
        )
        _archive_residual_temp_and_logs(output_dir)
        _notify(
            "【DoubleTop総当たり検証失敗】",
            f"- 通貨ペア: {pair_name}",
            f"- エラー: {type(error).__name__}: {error}",
        )
        raise


def run_all_pairs(
    pairs: Iterable[str],
    train_start: dt.datetime,
    train_end: dt.datetime,
    oos_start: dt.datetime,
    oos_end: dt.datetime,
) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for pair in pairs:
        summaries.append(
            run_pair(
                pair,
                train_start,
                train_end,
                oos_start,
                oos_end,
            )
        )
    _notify(
        "【DoubleTop全通貨検証完了】",
        *[
            (
                f"- {summary['pair']}: "
                f"{summary['oos']['combined_top15']['completed_count']}件 / "
                f"勝率{summary['oos']['combined_top15']['win_rate']:.1%} / "
                f"平均勝ち{summary['oos']['combined_top15']['average_win_pips']:.2f}pips / "
                f"損益{summary['oos']['combined_top15']['sum_yen']:.0f}円"
            )
            for summary in summaries
        ],
    )
    return summaries
