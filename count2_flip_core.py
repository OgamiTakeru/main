"""First-touch rejection helpers for ``flip_predict``.

The causal foot-count-2 snapshot registers a line in its direction of travel.
The line's newest constituent peak must point the other way, and the order is
also placed opposite the foot-count-2 direction.  The first spread-aware S5
touch fills the LIMIT order; there is no breakout confirmation or retest step.

Only fields known at ``decision_time`` may be used by feature conditions.
Fill and trade fields are labels and are never policy inputs.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd

import fGeneric as gene
from count2_resistance_sweep import LimitPathInspector, S5_SECONDS
from fFootCountShape import add_foot_count2_search_buckets


FLIP_VERSION = "flip_predict_v5"
DEFAULT_ORDER_WAIT_MINUTES = 120
DEFAULT_POSITION_HORIZON_MINUTES = 60
DEFAULT_SPREAD_PIPS = 0.8
DEFAULT_MIN_WIDTH_PIPS = 1.6
DEFAULT_RISK_YEN = 50.0
TOP_CONDITION_LIMIT = 15
TIER_HIGH = "HIGH"
TIER_MIDDLE = "MIDDLE"
TIER_LOW = "LOW"
TIER_NAMES = (TIER_HIGH, TIER_MIDDLE, TIER_LOW)
CONDITION_RANKING_TP_A = 1.7
CONDITION_RANKING_RR = 1.5
DEFAULT_TIER_TP_A = {
    TIER_HIGH: 1.7,
    TIER_MIDDLE: 1.7,
    TIER_LOW: 1.7,
}
DEFAULT_TIER_RR = {
    TIER_HIGH: 1.5,
    TIER_MIDDLE: 1.5,
    TIER_LOW: 1.5,
}


def _is_expected_annual_holiday_closure_gap(
    previous_time: pd.Timestamp,
    next_time: pd.Timestamp,
) -> bool:
    """Recognize only Christmas/New-Year closures joined to weekends."""
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
    gap = next_ny - previous_ny
    if gap < pd.Timedelta(hours=12) or gap > pd.Timedelta(hours=96):
        return False
    rollover_start = dt.time(16, 30)
    rollover_end = dt.time(17, 30)
    if not (
        rollover_start <= previous_ny.time() <= rollover_end
        and rollover_start <= next_ny.time() <= rollover_end
    ):
        return False

    def is_holiday(day: dt.date) -> bool:
        if (day.month, day.day) in {(1, 1), (12, 25)}:
            return True
        if day.weekday() == 4:
            following = day + dt.timedelta(days=1)
            return (following.month, following.day) in {(1, 1), (12, 25)}
        if day.weekday() == 0:
            previous = day - dt.timedelta(days=1)
            return (previous.month, previous.day) in {(1, 1), (12, 25)}
        return False

    day = previous_ny.date() + dt.timedelta(days=1)
    final_day = next_ny.date()
    holiday_seen = False
    while day <= final_day:
        holiday = is_holiday(day)
        holiday_seen = holiday_seen or holiday
        if day.weekday() < 5 and not holiday:
            return False
        day += dt.timedelta(days=1)
    return holiday_seen


def _is_expected_market_closed_gap(
    previous_time: pd.Timestamp,
    next_time: pd.Timestamp,
) -> bool:
    return bool(
        LimitPathInspector._is_expected_market_closed_gap(
            pd.Timestamp(previous_time), pd.Timestamp(next_time)
        )
        or _is_expected_annual_holiday_closure_gap(previous_time, next_time)
    )


@dataclass(frozen=True)
class FlipPathConfig:
    order_wait_minutes: int = DEFAULT_ORDER_WAIT_MINUTES

    def __post_init__(self) -> None:
        if self.order_wait_minutes < 1:
            raise ValueError("order_wait_minutes must be positive")

    @property
    def config_id(self) -> str:
        return f"order_wait{self.order_wait_minutes}m"


@dataclass(frozen=True)
class TradeCombo:
    tp_a: float
    lc_a: float

    def __post_init__(self) -> None:
        if (
            not math.isfinite(self.tp_a)
            or not math.isfinite(self.lc_a)
            or self.tp_a <= 0
            or self.lc_a <= 0
        ):
            raise ValueError("TP/LC A multipliers must be finite and positive")

    @property
    def configured_rr(self) -> float:
        return self.tp_a / self.lc_a

    @property
    def combo_id(self) -> str:
        tp = f"{self.tp_a:g}".replace(".", "p")
        lc = f"{self.lc_a:g}".replace(".", "p")
        return f"tp{tp}A_lc{lc}A"

    @classmethod
    def from_tp_rr(cls, tp_a: float, rr: float) -> "TradeCombo":
        rr = float(rr)
        if not math.isfinite(rr) or rr <= 0:
            raise ValueError("RR must be finite and positive")
        return cls(tp_a=float(tp_a), lc_a=float(tp_a) / rr)


@dataclass(frozen=True)
class PolicyCondition:
    condition_id: str
    label: str
    clauses: tuple[tuple[str, str], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "condition_id": self.condition_id,
            "label": self.label,
            "clauses": [
                {"field": field, "value": value}
                for field, value in self.clauses
            ],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PolicyCondition":
        clauses = tuple(
            (str(item["field"]), str(item["value"]))
            for item in value.get("clauses", [])
        )
        return cls(
            condition_id=str(value["condition_id"]),
            label=str(value.get("label", value["condition_id"])),
            clauses=clauses,
        )


@dataclass(frozen=True)
class TierExecutionConfig:
    tier: str
    first_rank: int
    last_rank: int
    tp_a: float
    rr: float

    def __post_init__(self) -> None:
        if self.tier not in TIER_NAMES:
            raise ValueError(f"unknown signal tier: {self.tier}")
        if self.first_rank < 1 or self.last_rank < self.first_rank:
            raise ValueError("invalid tier rank range")
        if not math.isfinite(self.tp_a) or self.tp_a <= 0:
            raise ValueError("tier TP must be finite and positive")
        if not math.isfinite(self.rr) or self.rr <= 0:
            raise ValueError("tier RR must be finite and positive")

    @property
    def trade_combo(self) -> TradeCombo:
        return TradeCombo.from_tp_rr(self.tp_a, self.rr)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tier": self.tier,
            "first_rank": self.first_rank,
            "last_rank": self.last_rank,
            "tp_a": self.tp_a,
            "rr": self.rr,
            "lc_a": self.trade_combo.lc_a,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TierExecutionConfig":
        return cls(
            tier=str(value["tier"]),
            first_rank=int(value["first_rank"]),
            last_rank=int(value["last_rank"]),
            tp_a=float(value["tp_a"]),
            rr=float(value["rr"]),
        )


@dataclass(frozen=True)
class RankedPolicyCondition:
    rank: int
    tier: str
    condition: PolicyCondition

    def __post_init__(self) -> None:
        if self.rank < 1:
            raise ValueError("condition rank must be positive")
        if self.tier not in TIER_NAMES:
            raise ValueError(f"unknown signal tier: {self.tier}")
        if self.condition.condition_id == "ALL":
            raise ValueError("ALL cannot be a ranked order trigger")

    def to_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "tier": self.tier,
            "condition": self.condition.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RankedPolicyCondition":
        return cls(
            rank=int(value["rank"]),
            tier=str(value["tier"]),
            condition=PolicyCondition.from_dict(value["condition"]),
        )


def default_path_configs() -> tuple[FlipPathConfig, ...]:
    return tuple(FlipPathConfig(wait) for wait in (60, 120))


def default_tier_execution_configs() -> tuple[TierExecutionConfig, ...]:
    """Return editable tier settings; initially every tier uses RR 1.5."""
    return (
        TierExecutionConfig(
            TIER_HIGH,
            1,
            5,
            DEFAULT_TIER_TP_A[TIER_HIGH],
            DEFAULT_TIER_RR[TIER_HIGH],
        ),
        TierExecutionConfig(
            TIER_MIDDLE,
            6,
            10,
            DEFAULT_TIER_TP_A[TIER_MIDDLE],
            DEFAULT_TIER_RR[TIER_MIDDLE],
        ),
        TierExecutionConfig(
            TIER_LOW,
            11,
            15,
            DEFAULT_TIER_TP_A[TIER_LOW],
            DEFAULT_TIER_RR[TIER_LOW],
        ),
    )


def tier_for_rank(
    rank: int,
    configs: Iterable[TierExecutionConfig],
) -> str:
    matches = [
        config.tier
        for config in configs
        if config.first_rank <= int(rank) <= config.last_rank
    ]
    if len(matches) != 1:
        raise ValueError(f"rank {rank} must belong to exactly one signal tier")
    return matches[0]


def default_trade_combos(min_rr: float = 1.0) -> tuple[TradeCombo, ...]:
    # Condition ranking needs one common outcome contract.  Tier-specific
    # RR is applied only after the top-15 triggers have been frozen.
    combo = TradeCombo.from_tp_rr(CONDITION_RANKING_TP_A, CONDITION_RANKING_RR)
    return (combo,) if combo.configured_rr + 1e-12 >= min_rr else ()


def expected_role(direction: int) -> str:
    if int(direction) == 1:
        return "resistance"
    if int(direction) == -1:
        return "support"
    raise ValueError("direction must be -1 or 1")


def effective_width_pips(
    average_range_pips: float,
    multiplier: float,
    pair: gene.CurrencyPair,
    minimum_pips: float = DEFAULT_MIN_WIDTH_PIPS,
) -> float:
    requested = max(float(average_range_pips) * float(multiplier), minimum_pips)
    return abs(pair.pips_to_price(requested)) / pair.pip_value


def effective_trade_widths(
    average_range_pips: float,
    combo: TradeCombo,
    pair: gene.CurrencyPair,
    minimum_pips: float = DEFAULT_MIN_WIDTH_PIPS,
) -> tuple[float, float]:
    """Scale the safety floor jointly, then quantize to executable price ticks."""
    average = float(average_range_pips)
    minimum = float(minimum_pips)
    if not math.isfinite(average) or average <= 0:
        raise ValueError("average range must be finite and positive")
    if not math.isfinite(minimum) or minimum < 0:
        raise ValueError("minimum width must be finite and non-negative")
    raw_tp = average * combo.tp_a
    raw_lc = average * combo.lc_a
    common_scale = max(
        1.0,
        minimum / raw_tp,
        minimum / raw_lc,
    )
    tick_pips = (10.0 ** -int(pair.round_keta)) / float(pair.pip_value)
    if not math.isfinite(tick_pips) or tick_pips <= 0:
        raise ValueError("pair price increment must be finite and positive")

    def ceil_to_tick(width_pips: float) -> float:
        ticks = math.ceil(width_pips / tick_pips - 1e-12)
        return ticks * tick_pips

    return (
        ceil_to_tick(raw_tp * common_scale),
        ceil_to_tick(raw_lc * common_scale),
    )


def result_yen(
    pair: gene.CurrencyPair,
    result_pips: float,
    lc_pips: float,
    risk_yen: float,
) -> float:
    result_r = float(result_pips) / float(lc_pips)
    if pair.name != "USD_JPY":
        # A causal USD/JPY conversion series is not part of the source ledger.
        # Keep the established repository convention for cross-pair comparison.
        return result_r * float(risk_yen)
    units = gene.calculate_units(
        pair,
        pair.pips_to_price(float(lc_pips)),
        risk_yen=float(risk_yen),
        rounding_tag="l",
    )
    return float(result_pips) * pair.pip_value * units


def _as_bool(value: Any) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def validate_causal_candidate(row: Mapping[str, Any]) -> None:
    decision = pd.Timestamp(row["decision_time"])
    for field in (
        "target_source_last_time",
        "fc2_source_last_time",
        "h1_pair_source_last_time",
        "line_newest_source_time",
        "line_latest_touch_time",
    ):
        raw = row.get(field)
        if raw is None or raw == "" or pd.isna(raw):
            continue
        timestamp = pd.to_datetime(raw, errors="coerce")
        if pd.isna(timestamp):
            continue
        if field == "h1_pair_source_last_time":
            # H1 source timestamps are candle starts and need a full hour.
            timestamp += pd.Timedelta(hours=1)
        elif field in {
            "target_source_last_time",
            "fc2_source_last_time",
            "line_newest_source_time",
            "line_latest_touch_time",
        }:
            # M5 source timestamps are candle starts and need five minutes.
            timestamp += pd.Timedelta(minutes=5)
        if timestamp > decision:
            raise ValueError(
                f"future candidate feature: {field}={timestamp} > {decision}"
            )


class FlipPathInspector:
    """Inspect a direct S5 line touch and the opposite-direction outcome."""

    def __init__(
        self,
        inspector: LimitPathInspector,
        pair: gene.CurrencyPair,
        *,
        period_end_exclusive: pd.Timestamp,
        spread_pips: float = DEFAULT_SPREAD_PIPS,
        position_horizon_minutes: int = DEFAULT_POSITION_HORIZON_MINUTES,
        min_width_pips: float = DEFAULT_MIN_WIDTH_PIPS,
        risk_yen: float = DEFAULT_RISK_YEN,
    ) -> None:
        if spread_pips < 0 or position_horizon_minutes < 1 or min_width_pips <= 0:
            raise ValueError("invalid flip path execution parameters")
        self.inspector = inspector
        self.pair = pair
        self.period_end = pd.Timestamp(period_end_exclusive)
        self.spread_pips = float(spread_pips)
        self.position_horizon_minutes = int(position_horizon_minutes)
        self.min_width_pips = float(min_width_pips)
        self.risk_yen = float(risk_yen)
        self.times = np.asarray(inspector.times)
        self.opens = np.asarray(inspector.opens)
        self.closes = np.asarray(inspector.closes)
        self.highs = np.asarray(inspector.highs)
        self.lows = np.asarray(inspector.lows)
        self._invalid_gap_indices = self._build_invalid_gap_indices()

    def _build_invalid_gap_indices(self) -> np.ndarray:
        """Index only unknown gaps; known market closures stay valid."""
        if len(self.times) < 2:
            return np.asarray([], dtype=np.int64)
        gaps = np.diff(self.times)
        unexpected = np.flatnonzero(gaps != np.timedelta64(S5_SECONDS, "s"))
        invalid = []
        for index in unexpected:
            if not _is_expected_market_closed_gap(
                pd.Timestamp(self.times[int(index)]),
                pd.Timestamp(self.times[int(index) + 1]),
            ):
                invalid.append(int(index))
        return np.asarray(invalid, dtype=np.int64)

    @staticmethod
    def _base() -> dict[str, Any]:
        return {
            "path_status": None,
            "approach_direction": np.nan,
            "order_direction": np.nan,
            "order_filled": False,
            "order_deadline": pd.NaT,
            "replaced_before_fill": False,
            "fill_time": pd.NaT,
            "fill_delay_from_decision_seconds": np.nan,
            "fill_at_bar_open": False,
            "position_path_complete": False,
            "position_horizon_end": pd.NaT,
            "outcomes": {},
        }

    @staticmethod
    def _known_window_complete(
        times: np.ndarray,
        expected_start: pd.Timestamp,
        expected_end_exclusive: pd.Timestamp,
    ) -> bool:
        if not len(times):
            return False
        expected_start = pd.Timestamp(expected_start)
        expected_end_exclusive = pd.Timestamp(expected_end_exclusive)
        if pd.Timestamp(times[0]) != expected_start:
            return False
        if len(times) > 1:
            gaps = np.flatnonzero(
                np.diff(times) != np.timedelta64(S5_SECONDS, "s")
            )
            for index in gaps:
                if not _is_expected_market_closed_gap(
                    pd.Timestamp(times[int(index)]),
                    pd.Timestamp(times[int(index) + 1]),
                ):
                    return False
        actual_end = pd.Timestamp(times[-1]) + pd.Timedelta(seconds=S5_SECONDS)
        if actual_end == expected_end_exclusive:
            return True
        if actual_end < expected_end_exclusive:
            return _is_expected_market_closed_gap(
                pd.Timestamp(times[-1]), expected_end_exclusive
            )
        return False

    def _indexed_window_complete(
        self,
        start_i: int,
        end_i: int,
        expected_start: pd.Timestamp,
        expected_end_exclusive: pd.Timestamp,
    ) -> bool:
        if start_i < 0 or end_i <= start_i or end_i > len(self.times):
            return False
        expected_start = pd.Timestamp(expected_start)
        expected_end_exclusive = pd.Timestamp(expected_end_exclusive)
        if pd.Timestamp(self.times[start_i]) != expected_start:
            return False
        # Internal edges of [start_i:end_i] are start_i through end_i - 2.
        invalid_position = int(
            np.searchsorted(self._invalid_gap_indices, start_i, side="left")
        )
        if (
            invalid_position < len(self._invalid_gap_indices)
            and int(self._invalid_gap_indices[invalid_position]) < end_i - 1
        ):
            return False
        actual_end = pd.Timestamp(self.times[end_i - 1]) + pd.Timedelta(
            seconds=S5_SECONDS
        )
        if actual_end == expected_end_exclusive:
            return True
        if actual_end < expected_end_exclusive:
            return _is_expected_market_closed_gap(
                pd.Timestamp(self.times[end_i - 1]), expected_end_exclusive
            )
        return False

    def _strict_position_window_complete(
        self,
        start_i: int,
        end_i: int,
        expected_start: pd.Timestamp,
        expected_end_exclusive: pd.Timestamp,
    ) -> bool:
        """Do not invent a timeout fill inside, or across, a market closure."""
        if start_i < 0 or end_i <= start_i or end_i > len(self.times):
            return False
        if pd.Timestamp(self.times[start_i]) != pd.Timestamp(expected_start):
            return False
        if len(self.times[start_i:end_i]) > 1 and bool(
            np.any(
                np.diff(self.times[start_i:end_i])
                != np.timedelta64(S5_SECONDS, "s")
            )
        ):
            return False
        actual_end = pd.Timestamp(self.times[end_i - 1]) + pd.Timedelta(
            seconds=S5_SECONDS
        )
        return actual_end == pd.Timestamp(expected_end_exclusive)

    def inspect(
        self,
        *,
        decision_time: pd.Timestamp,
        line_price: float,
        order_direction: int,
        average_range_pips: float,
        path_config: FlipPathConfig,
        trade_combos: Iterable[TradeCombo],
        next_count2_time: pd.Timestamp | None = None,
    ) -> dict[str, Any]:
        base = self._base()
        decision_time = pd.Timestamp(decision_time)
        order_direction = int(order_direction)
        if order_direction not in (-1, 1):
            raise ValueError("order_direction must be -1 or 1")
        approach_direction = -order_direction
        average_range_pips = float(average_range_pips)
        line_price = float(line_price)
        if not math.isfinite(average_range_pips) or average_range_pips <= 0:
            return {**base, "path_status": "invalid_average_range"}
        if not math.isfinite(line_price):
            return {**base, "path_status": "invalid_line_price"}
        if decision_time >= self.period_end:
            return {**base, "path_status": "outside_period"}

        configured_deadline = min(
            decision_time + pd.Timedelta(minutes=path_config.order_wait_minutes),
            self.period_end,
        )
        order_deadline = configured_deadline
        replacement_cutoff = False
        next_count2 = pd.to_datetime(next_count2_time, errors="coerce")
        if (
            not pd.isna(next_count2)
            and decision_time < next_count2 < order_deadline
        ):
            order_deadline = pd.Timestamp(next_count2)
            replacement_cutoff = True
        common = {
            **base,
            "approach_direction": approach_direction,
            "order_direction": order_direction,
            "order_deadline": order_deadline,
        }
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
                np.datetime64(order_deadline, "ns"),
                side="left",
            )
        )
        completed_without_rows = False
        if start_i >= expiry_i or start_i >= len(self.times):
            completed_without_rows = _is_expected_market_closed_gap(
                decision_time - pd.Timedelta(seconds=S5_SECONDS),
                order_deadline,
            )
            if completed_without_rows:
                status = "replaced_before_fill" if replacement_cutoff else "no_fill"
            else:
                status = "incomplete_order_window"
            return {
                **common,
                "path_status": status,
                "replaced_before_fill": bool(
                    replacement_cutoff and completed_without_rows
                ),
            }

        half_spread = self.pair.pips_to_price(self.spread_pips / 2.0)
        if order_direction == 1:
            touches = self.lows[start_i:expiry_i] + half_spread <= line_price
        else:
            touches = self.highs[start_i:expiry_i] - half_spread >= line_price
        reached = np.flatnonzero(touches)
        if not reached.size:
            complete = self._indexed_window_complete(
                start_i,
                expiry_i,
                decision_time,
                order_deadline,
            )
            if complete:
                status = "replaced_before_fill" if replacement_cutoff else "no_fill"
            else:
                status = "incomplete_order_window"
            return {
                **common,
                "path_status": status,
                "replaced_before_fill": bool(replacement_cutoff and complete),
            }

        fill_i = start_i + int(reached[0])
        fill_time = pd.Timestamp(self.times[fill_i])
        if not self._indexed_window_complete(
            start_i,
            fill_i + 1,
            decision_time,
            fill_time + pd.Timedelta(seconds=S5_SECONDS),
        ):
            closed = _is_expected_market_closed_gap(
                decision_time - pd.Timedelta(seconds=S5_SECONDS), fill_time
            )
            return {
                **common,
                "path_status": (
                    "incomplete_order_before_fill"
                    if not closed
                    else "incomplete_order_window"
                ),
            }
        fill_at_open = (
            float(self.opens[fill_i]) + half_spread <= line_price
            if order_direction == 1
            else float(self.opens[fill_i]) - half_spread >= line_price
        )
        filled = {
            **common,
            "order_filled": True,
            "fill_time": fill_time,
            "fill_delay_from_decision_seconds": float(
                (fill_time - decision_time).total_seconds()
            ),
            "fill_at_bar_open": bool(fill_at_open),
        }
        horizon_end = fill_time + pd.Timedelta(
            minutes=self.position_horizon_minutes
        )
        end_i = int(
            np.searchsorted(
                self.times, np.datetime64(horizon_end, "ns"), side="left"
            )
        )
        path_times = self.times[fill_i:end_i]
        if not len(path_times):
            return {
                **filled,
                "path_status": "incomplete_position_window",
                "position_horizon_end": horizon_end,
            }

        high = self.highs[fill_i:end_i]
        low = self.lows[fill_i:end_i]
        close = self.closes[fill_i:end_i]
        if order_direction == 1:
            favorable = (high - half_spread - line_price) / self.pair.pip_value
            adverse = (low - half_spread - line_price) / self.pair.pip_value
            timeout_pips = float(
                (close[-1] - half_spread - line_price) / self.pair.pip_value
            )
            fill_close_progress = float(
                (close[0] - half_spread - line_price) / self.pair.pip_value
            )
        else:
            favorable = (line_price - (low + half_spread)) / self.pair.pip_value
            adverse = (line_price - (high + half_spread)) / self.pair.pip_value
            timeout_pips = float(
                (line_price - (close[-1] + half_spread)) / self.pair.pip_value
            )
            fill_close_progress = float(
                (line_price - (close[0] + half_spread)) / self.pair.pip_value
            )
        favorable_cumulative = np.maximum.accumulate(favorable)
        adverse_cumulative = np.minimum.accumulate(adverse)
        metric_favorable = favorable.copy()
        if not fill_at_open:
            metric_favorable[0] = max(0.0, fill_close_progress)
        outcomes: dict[str, dict[str, Any]] = {}
        for combo in trade_combos:
            tp_pips, lc_pips = effective_trade_widths(
                average_range_pips,
                combo,
                self.pair,
                self.min_width_pips,
            )
            tp_reached = np.flatnonzero(favorable_cumulative >= tp_pips)
            lc_reached = np.flatnonzero(adverse_cumulative <= -lc_pips)
            tp_index = int(tp_reached[0]) if tp_reached.size else None
            lc_index = int(lc_reached[0]) if lc_reached.size else None
            # A TP seen inside the fill S5 cannot precede the touch unless the
            # order was marketable at that bar's open or its close confirms TP.
            if tp_index == 0 and not fill_at_open and fill_close_progress < tp_pips:
                later = np.flatnonzero(favorable[1:] >= tp_pips)
                tp_index = int(later[0]) + 1 if later.size else None
            if lc_index is not None and (tp_index is None or lc_index <= tp_index):
                exit_index = lc_index
                result_name = (
                    "both_same_s5_lc_assumed"
                    if tp_index is not None and tp_index == lc_index
                    else "lc"
                )
                result_pips = -lc_pips
            elif tp_index is not None:
                exit_index = tp_index
                result_name = "tp"
                result_pips = tp_pips
            else:
                exit_index = len(path_times) - 1
                result_name = "timeout"
                result_pips = timeout_pips
            outcome_end_i = fill_i + exit_index + 1
            outcome_end = (
                horizon_end
                if result_name == "timeout"
                else pd.Timestamp(path_times[exit_index])
                + pd.Timedelta(seconds=S5_SECONDS)
            )
            if not self._strict_position_window_complete(
                fill_i,
                outcome_end_i,
                fill_time,
                outcome_end,
            ):
                continue
            result_r = float(result_pips / lc_pips)
            outcomes[combo.combo_id] = {
                "combo_id": combo.combo_id,
                "tp_a": combo.tp_a,
                "lc_a": combo.lc_a,
                "configured_rr": combo.configured_rr,
                "effective_rr": tp_pips / lc_pips,
                "tp_pips": tp_pips,
                "lc_pips": lc_pips,
                "trade_result": result_name,
                "trade_result_pips": float(result_pips),
                "result_r": result_r,
                "result_yen": result_yen(
                    self.pair, result_pips, lc_pips, self.risk_yen
                ),
                "exit_time": pd.Timestamp(path_times[exit_index]),
                "actual_entry_price": line_price,
                "actual_exit_price": float(
                    line_price
                    + order_direction * self.pair.pips_to_price(result_pips)
                ),
                "max_favorable_pips": float(
                    np.nanmax(metric_favorable[: exit_index + 1])
                ),
                "max_adverse_pips": float(np.nanmin(adverse[: exit_index + 1])),
            }
        completed = bool(outcomes)
        return {
            **filled,
            "path_status": "trade" if completed else "incomplete_position_window",
            "position_path_complete": completed,
            "position_horizon_end": horizon_end,
            "outcomes": outcomes,
        }


def add_feature_buckets(frame: pd.DataFrame) -> pd.DataFrame:
    """Create the finite, causal feature catalog used by exhaustive search."""
    result = frame.copy()

    def numeric(name: str) -> pd.Series:
        return pd.to_numeric(result.get(name), errors="coerce")

    def cut(name: str, bins: list[float], labels: list[str]) -> pd.Series:
        return pd.cut(
            numeric(name), bins=bins, labels=labels, include_lowest=True
        ).astype("string").fillna("missing")

    distance_rank = numeric("distance_rank")
    result["f_distance_rank"] = np.select(
        [distance_rank.eq(1), distance_rank.eq(2), distance_rank.eq(3)],
        ["1", "2", "3"],
        default="4plus",
    )
    average = numeric("recent_m5_avg_range_pips").replace(0, np.nan)
    result["distance_a"] = numeric("distance_pips") / average
    result["f_distance_a"] = cut(
        "distance_a",
        [-np.inf, 0.5, 1.0, 2.0, 4.0, np.inf],
        ["lt0p5", "0p5to1", "1to2", "2to4", "ge4"],
    )
    result["f_peaks_count"] = cut(
        "line_count", [-np.inf, 1, 2, 3, np.inf], ["1", "2", "3", "4plus"]
    )
    result["f_core_peak"] = cut(
        "line_core_count",
        [-np.inf, 1, 2, np.inf],
        ["1", "2", "3plus"],
    )
    result["f_line_average_strength"] = cut(
        "line_average_strength",
        [-np.inf, 1.0, 2.0, 3.0, np.inf],
        ["le1", "1to2", "2to3", "gt3"],
    )
    result["f_line_total_strength"] = cut(
        "line_total_strength",
        [-np.inf, 3, 6, 10, np.inf],
        ["le3", "4to6", "7to10", "gt10"],
    )
    # This is the original structural flip judgement from
    # LineStrengthCal.line_each_analysis().  Do not substitute the separate
    # completed-close role-history fields here: those describe another
    # characteristic and can differ after an even number of role changes.
    structural_flip = (
        result["line_is_flipped"]
        if "line_is_flipped" in result
        else pd.Series(False, index=result.index)
    )
    result["flip_flag"] = structural_flip.map(_as_bool)
    result["f_flip_flag"] = result["flip_flag"].map(
        {True: "yes", False: "no"}
    )
    flip_count = numeric("line_flip_count").fillna(0)
    result["f_prior_flip_count"] = np.select(
        [flip_count.eq(0), flip_count.eq(1)],
        ["0", "1"],
        default="2plus",
    )
    result["f_history_flipped"] = result.get(
        "line_history_is_flipped", False
    ).map(_as_bool).map({True: "yes", False: "no"})
    result["f_line_age"] = cut(
        "line_age_minutes",
        [-np.inf, 60, 240, 1440, np.inf],
        ["lt1h", "1to4h", "4to24h", "ge24h"],
    )
    result["f_prior_retouch"] = cut(
        "prior_retouch_count",
        [-np.inf, 0, 1, 2, np.inf],
        ["0", "1", "2", "3plus"],
    )
    result["f_peak_strength"] = cut(
        "peak_strength",
        [-np.inf, 1, 2, 3, 5, np.inf],
        ["le1", "2", "3", "4to5", "gt5"],
    )
    direction = numeric("peak_direction").fillna(0)
    rsi = numeric("rsi_1")
    oriented_rsi = direction * (rsi - 50.0)
    result["oriented_rsi"] = oriented_rsi
    result["f_oriented_rsi"] = pd.cut(
        oriented_rsi,
        bins=[-np.inf, -15, -5, 5, 15, np.inf],
        labels=["strong_against", "against", "neutral", "with", "strong_with"],
        include_lowest=True,
    ).astype("string").fillna("missing")
    result = add_foot_count2_search_buckets(result)
    result["f_h1_shape"] = result.get("h1_pair_shape", "missing").astype(
        "string"
    ).fillna("missing")
    result["f_direction"] = direction.map({1.0: "up", -1.0: "down"}).fillna(
        "missing"
    )
    hour = pd.to_datetime(result["decision_time"]).dt.hour
    result["f_session"] = np.select(
        [hour.between(6, 13), hour.between(14, 21)],
        ["asia", "london"],
        default="new_york",
    )
    for source, destination in (
        ("m5_stair_observed_direction", "f_m5_stair_relation"),
        ("h1_stair_observed_direction", "f_h1_stair_relation"),
    ):
        observed = numeric(source).fillna(0)
        relation = observed * direction
        result[destination] = relation.map(
            {1.0: "aligned", -1.0: "opposed", 0.0: "none"}
        ).fillna("none")
    return result


FEATURE_FIELDS = (
    "f_distance_rank",
    "f_distance_a",
    "f_peaks_count",
    "f_core_peak",
    "f_line_average_strength",
    "f_line_total_strength",
    "f_flip_flag",
    "f_prior_flip_count",
    "f_history_flipped",
    "f_line_age",
    "f_prior_retouch",
    "f_peak_strength",
    "f_oriented_rsi",
    "f_fc2_shape",
    "f_fc2_relative_candle_sequence",
    "f_fc2_second_wick_a",
    "f_fc2_second_body_ratio",
    "f_fc2_second_pushback_a",
    "f_h1_shape",
    "f_direction",
    "f_session",
    "f_m5_stair_relation",
    "f_h1_stair_relation",
)

# The line/event sweep is exhaustive.  Feature interactions are restricted to
# economically interpretable pairs so that selection remains auditable and
# does not become an unbounded multiple-testing exercise.
FEATURE_INTERACTION_PAIRS = (
    ("f_distance_rank", "f_distance_a"),
    ("f_distance_rank", "f_peaks_count"),
    ("f_distance_rank", "f_core_peak"),
    ("f_distance_a", "f_peaks_count"),
    ("f_distance_a", "f_core_peak"),
    ("f_peaks_count", "f_core_peak"),
    ("f_peaks_count", "f_line_average_strength"),
    ("f_peaks_count", "f_flip_flag"),
    ("f_peaks_count", "f_history_flipped"),
    ("f_core_peak", "f_flip_flag"),
    ("f_core_peak", "f_history_flipped"),
    ("f_prior_flip_count", "f_prior_retouch"),
    ("f_line_age", "f_prior_retouch"),
    ("f_fc2_shape", "f_distance_a"),
    ("f_fc2_shape", "f_peaks_count"),
    ("f_fc2_shape", "f_core_peak"),
    ("f_fc2_shape", "f_oriented_rsi"),
    ("f_fc2_shape", "f_h1_shape"),
    ("f_fc2_relative_candle_sequence", "f_fc2_second_wick_a"),
    ("f_fc2_relative_candle_sequence", "f_fc2_second_body_ratio"),
    ("f_fc2_second_wick_a", "f_fc2_second_pushback_a"),
    ("f_h1_shape", "f_oriented_rsi"),
    ("f_direction", "f_fc2_shape"),
    ("f_session", "f_fc2_shape"),
    ("f_m5_stair_relation", "f_h1_stair_relation"),
    ("f_m5_stair_relation", "f_fc2_shape"),
    ("f_h1_stair_relation", "f_h1_shape"),
)


def enumerate_conditions(
    frame: pd.DataFrame,
    *,
    minimum_candidates: int = 100,
) -> list[PolicyCondition]:
    """Exhaust every observed value and every cross-field value pair."""
    conditions = [PolicyCondition("ALL", "All eligible flip_predict lines")]
    for field in FEATURE_FIELDS:
        counts = frame[field].astype(str).value_counts(dropna=False)
        for value, count in counts.items():
            if int(count) < minimum_candidates:
                continue
            condition_id = f"{field}={value}"
            conditions.append(
                PolicyCondition(condition_id, condition_id, ((field, str(value)),))
            )
    for left, right in FEATURE_INTERACTION_PAIRS:
        counts = (
            frame.groupby([left, right], dropna=False)
            .size()
            .sort_values(ascending=False)
        )
        for (left_value, right_value), count in counts.items():
            if int(count) < minimum_candidates:
                continue
            condition_id = f"{left}={left_value}&{right}={right_value}"
            conditions.append(
                PolicyCondition(
                    condition_id,
                    condition_id,
                    (
                        (left, str(left_value)),
                        (right, str(right_value)),
                    ),
                )
            )
    return conditions


def condition_mask(
    frame: pd.DataFrame,
    condition: PolicyCondition,
) -> np.ndarray:
    mask = np.ones(len(frame), dtype=bool)
    for field, expected in condition.clauses:
        if field not in frame:
            return np.zeros(len(frame), dtype=bool)
        mask &= frame[field].astype(str).to_numpy() == expected
    return mask


def serialize_path_config(config: FlipPathConfig) -> dict[str, Any]:
    return asdict(config)


def serialize_trade_combo(combo: TradeCombo) -> dict[str, Any]:
    return {**asdict(combo), "configured_rr": combo.configured_rr}
