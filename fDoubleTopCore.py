# 最新更新日時: 2026-08-30 17:44 JST
"""本番と高速検証で共有するDoubleTop v1の副作用なし判定コア。

このモジュールはOANDA通信、Discord通知、ファイル入出力、注文登録を行わない。
本番は明示的にv1関数を固定利用し、検証固有の総当たり条件はここへ置かない。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import math
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd


CORE_VERSION_V1 = "double_top_core_v1"


@dataclass(frozen=True)
class DoubleTopPolicyV1:
    """DoubleTop v1の形成条件と注文条件。

    ``base_top_tolerance_pips`` と ``top_tolerance_height_ratio`` が共に
    指定された場合は、従来どおり両者の大きい方をトップ許容幅にする。
    ``max_top_gap_*`` は探索用の追加上限で、本番の固定ポリシーでは使わない。
    """

    policy_id: str = "double_top_v1"
    min_top_foot_count: int = 2
    min_height_pips: float = 6.0
    max_height_pips: float = 60.0
    min_t1_t2_minutes: float = 15.0
    max_t1_t2_minutes: float = 360.0
    base_top_tolerance_pips: float | None = 3.0
    top_tolerance_height_ratio: float | None = 0.20
    max_top_gap_pips: float | None = None
    max_top_gap_ratio: float | None = None
    neckline_break_buffer_pips: float = 0.0
    target_height_multiplier: float = 1.0
    stop_buffer_pips: float = 1.0
    min_order_distance_pips: float = 1.0
    risk_yen: float = 50.0
    priority: int = 5
    trade_timeout_min: int = 240


@dataclass(frozen=True)
class DoubleTopCandidateV1:
    core_version: str
    t1_time: pd.Timestamp
    neckline_time: pd.Timestamp
    t2_time: pd.Timestamp
    break_time: pd.Timestamp
    t1_price: float
    neckline_price: float
    t2_price: float
    top_reference_price: float
    height_price: float
    break_close: float
    previous_close: float
    t1_foot_count: int
    neckline_foot_count: int
    t2_foot_count: int
    decline_foot_count: int
    top_gap_pips: float
    top_gap_ratio: float
    top_tolerance_pips: float
    height_pips: float
    t1_t2_minutes: float
    neckline_t2_minutes: float
    t2_break_minutes: float
    break_depth_pips: float
    projected_target_price: float


@dataclass(frozen=True)
class DoubleTopOrderLevelsV1:
    entry_price: float
    target_price: float
    stop_price: float
    tp_pips: float
    lc_pips: float


def local_timestamp_v1(value: Any) -> pd.Timestamp:
    stamp = pd.Timestamp(value)
    if pd.isna(stamp):
        raise ValueError("double top contains an invalid time")
    if stamp.tzinfo is not None:
        stamp = stamp.tz_convert("Asia/Tokyo").tz_localize(None)
    return stamp.floor("s")


def peak_time_v1(peak: Mapping[str, Any]) -> pd.Timestamp:
    return local_timestamp_v1(
        peak.get("latest_time_jp", peak.get("latest_time", peak.get("time")))
    )


def peak_price_v1(peak: Mapping[str, Any]) -> float:
    return float(peak.get("peak", peak.get("latest_body_peak_price")))


def foot_count_v1(peak: Mapping[str, Any]) -> int:
    return int(float(peak.get("count") or 0))


def direction_v1(peak: Mapping[str, Any]) -> int:
    return int(float(peak.get("direction") or 0))


def row_time_v1(row: Mapping[str, Any]) -> pd.Timestamp:
    value = row.get("time_jp_dt")
    if value is None or pd.isna(value):
        value = row.get("time_jp")
    return local_timestamp_v1(value)


def top_gap_limit_pips_v1(
        height_pips: float,
        policy: DoubleTopPolicyV1,
) -> float:
    limits: list[float] = []
    base = policy.base_top_tolerance_pips
    ratio = policy.top_tolerance_height_ratio
    if base is not None and ratio is not None:
        limits.append(max(float(base), float(height_pips) * float(ratio)))
    elif base is not None:
        limits.append(float(base))
    elif ratio is not None:
        limits.append(float(height_pips) * float(ratio))
    if policy.max_top_gap_pips is not None:
        limits.append(float(policy.max_top_gap_pips))
    if policy.max_top_gap_ratio is not None:
        limits.append(float(height_pips) * float(policy.max_top_gap_ratio))
    return min(limits) if limits else math.inf


def extract_candidate_features_v1(
        peaks: Sequence[Mapping[str, Any]],
        latest_completed_row: Mapping[str, Any],
        previous_completed_row: Mapping[str, Any],
        pair: Any,
) -> DoubleTopCandidateV1 | None:
    """完成足と最新4 Peaksから、条件未適用の共通特徴量を作る。"""
    if len(peaks) < 4:
        return None
    decline, t2, neckline, t1 = peaks[:4]
    if tuple(map(direction_v1, (decline, t2, neckline, t1))) != (-1, 1, -1, 1):
        return None

    t1_time = peak_time_v1(t1)
    neckline_time = peak_time_v1(neckline)
    t2_time = peak_time_v1(t2)
    break_time = row_time_v1(latest_completed_row)
    if not (t1_time < neckline_time < t2_time < break_time):
        return None

    t1_price = peak_price_v1(t1)
    neckline_price = peak_price_v1(neckline)
    t2_price = peak_price_v1(t2)
    break_close = float(latest_completed_row["close"])
    previous_close = float(previous_completed_row["close"])
    numeric_values = (
        t1_price,
        neckline_price,
        t2_price,
        break_close,
        previous_close,
    )
    if not all(math.isfinite(value) for value in numeric_values):
        raise ValueError("double top contains an invalid price")
    if neckline_price >= min(t1_price, t2_price):
        return None

    top_reference_price = (t1_price + t2_price) / 2.0
    height_price = top_reference_price - neckline_price
    height_pips = float(pair.price_to_pips(height_price))
    top_gap_pips = float(pair.price_to_pips(abs(t1_price - t2_price)))
    if height_pips <= 0 or not all(
            math.isfinite(value) for value in (height_pips, top_gap_pips)
    ):
        return None
    top_gap_ratio = top_gap_pips / height_pips
    t1_t2_minutes = (t2_time - t1_time).total_seconds() / 60.0
    neckline_t2_minutes = (t2_time - neckline_time).total_seconds() / 60.0
    t2_break_minutes = (break_time - t2_time).total_seconds() / 60.0
    break_depth_pips = float(
        pair.price_to_pips(neckline_price - break_close)
    )
    projected_target_price = pair.round_price(
        neckline_price - height_price
    )
    return DoubleTopCandidateV1(
        core_version=CORE_VERSION_V1,
        t1_time=t1_time,
        neckline_time=neckline_time,
        t2_time=t2_time,
        break_time=break_time,
        t1_price=t1_price,
        neckline_price=neckline_price,
        t2_price=t2_price,
        top_reference_price=top_reference_price,
        height_price=height_price,
        break_close=break_close,
        previous_close=previous_close,
        t1_foot_count=foot_count_v1(t1),
        neckline_foot_count=foot_count_v1(neckline),
        t2_foot_count=foot_count_v1(t2),
        decline_foot_count=foot_count_v1(decline),
        top_gap_pips=top_gap_pips,
        top_gap_ratio=top_gap_ratio,
        top_tolerance_pips=math.inf,
        height_pips=height_pips,
        t1_t2_minutes=t1_t2_minutes,
        neckline_t2_minutes=neckline_t2_minutes,
        t2_break_minutes=t2_break_minutes,
        break_depth_pips=break_depth_pips,
        projected_target_price=projected_target_price,
    )


def candidate_matches_policy_v1(
        candidate: DoubleTopCandidateV1,
        pair: Any,
        policy: DoubleTopPolicyV1,
) -> bool:
    if (
            candidate.t1_foot_count < policy.min_top_foot_count
            or candidate.t2_foot_count < policy.min_top_foot_count
    ):
        return False
    if not (
            policy.min_t1_t2_minutes
            <= candidate.t1_t2_minutes
            <= policy.max_t1_t2_minutes
    ):
        return False
    if not (
            policy.min_height_pips
            <= candidate.height_pips
            <= policy.max_height_pips
    ):
        return False
    top_limit = top_gap_limit_pips_v1(candidate.height_pips, policy)
    if candidate.top_gap_pips > top_limit:
        return False
    break_threshold = candidate.neckline_price - pair.pips_to_price(
        policy.neckline_break_buffer_pips
    )
    return bool(
        candidate.break_close < break_threshold <= candidate.previous_close
    )


def detect_candidate_v1(
        peaks: Sequence[Mapping[str, Any]],
        latest_completed_row: Mapping[str, Any],
        previous_completed_row: Mapping[str, Any],
        pair: Any,
        policy: DoubleTopPolicyV1,
) -> DoubleTopCandidateV1 | None:
    candidate = extract_candidate_features_v1(
        peaks,
        latest_completed_row,
        previous_completed_row,
        pair,
    )
    if candidate is None or not candidate_matches_policy_v1(candidate, pair, policy):
        return None
    return replace(
        candidate,
        top_tolerance_pips=round(
            top_gap_limit_pips_v1(candidate.height_pips, policy),
            2,
        ),
    )


def frame_policy_mask_v1(
        frame: pd.DataFrame,
        pair: Any,
        policy: DoubleTopPolicyV1,
) -> np.ndarray:
    """検証イベント表へ、scalar判定と同じv1条件を一括適用する。"""
    if frame.empty:
        return np.zeros(0, dtype=bool)
    height = pd.to_numeric(frame["height_pips"], errors="coerce").to_numpy(float)
    top_gap = pd.to_numeric(frame["top_gap_pips"], errors="coerce").to_numpy(float)
    limits = np.full(len(frame), np.inf, dtype=float)
    base = policy.base_top_tolerance_pips
    ratio = policy.top_tolerance_height_ratio
    if base is not None and ratio is not None:
        limits = np.minimum(
            limits,
            np.maximum(float(base), height * float(ratio)),
        )
    elif base is not None:
        limits = np.minimum(limits, float(base))
    elif ratio is not None:
        limits = np.minimum(limits, height * float(ratio))
    if policy.max_top_gap_pips is not None:
        limits = np.minimum(limits, float(policy.max_top_gap_pips))
    if policy.max_top_gap_ratio is not None:
        limits = np.minimum(
            limits,
            height * float(policy.max_top_gap_ratio),
        )
    break_threshold = (
        pd.to_numeric(frame["neckline_price"], errors="coerce")
        - pair.pips_to_price(policy.neckline_break_buffer_pips)
    )
    mask = (
        pd.to_numeric(frame["t1_foot_count"], errors="coerce").ge(
            policy.min_top_foot_count
        )
        & pd.to_numeric(frame["t2_foot_count"], errors="coerce").ge(
            policy.min_top_foot_count
        )
        & pd.to_numeric(frame["formation_minutes"], errors="coerce").between(
            policy.min_t1_t2_minutes,
            policy.max_t1_t2_minutes,
            inclusive="both",
        )
        & pd.to_numeric(frame["height_pips"], errors="coerce").between(
            policy.min_height_pips,
            policy.max_height_pips,
            inclusive="both",
        )
        & pd.Series(top_gap <= limits, index=frame.index)
        & pd.to_numeric(frame["break_close"], errors="coerce").lt(
            break_threshold
        )
        & pd.to_numeric(frame["previous_close"], errors="coerce").ge(
            break_threshold
        )
    )
    return np.asarray(mask.fillna(False), dtype=bool)


def target_price_v1(
        pair: Any,
        neckline_price: float,
        height_price: float,
        height_multiplier: float,
) -> float:
    return pair.round_price(
        float(neckline_price) - float(height_price) * float(height_multiplier)
    )


def stop_price_v1(
        pair: Any,
        t1_price: float,
        t2_price: float,
        stop_buffer_pips: float,
) -> float:
    return pair.round_price(
        max(float(t1_price), float(t2_price))
        + pair.pips_to_price(float(stop_buffer_pips))
    )


def build_short_order_levels_v1(
        candidate: DoubleTopCandidateV1,
        pair: Any,
        current_price: float,
        policy: DoubleTopPolicyV1,
) -> DoubleTopOrderLevelsV1 | None:
    entry_price = pair.round_price(float(current_price))
    target_price = target_price_v1(
        pair,
        candidate.neckline_price,
        candidate.height_price,
        policy.target_height_multiplier,
    )
    stop_price = stop_price_v1(
        pair,
        candidate.t1_price,
        candidate.t2_price,
        policy.stop_buffer_pips,
    )
    if not all(
            math.isfinite(value)
            for value in (entry_price, target_price, stop_price)
    ):
        raise ValueError("double top order contains an invalid price")
    tp_pips = float(pair.price_to_pips(entry_price - target_price))
    lc_pips = float(pair.price_to_pips(stop_price - entry_price))
    if (
            tp_pips < policy.min_order_distance_pips
            or lc_pips < policy.min_order_distance_pips
    ):
        return None
    return DoubleTopOrderLevelsV1(
        entry_price=entry_price,
        target_price=target_price,
        stop_price=stop_price,
        tp_pips=tp_pips,
        lc_pips=lc_pips,
    )
