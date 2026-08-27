# 最新更新日時: 2026-08-25 14:59 JST
"""First-touch rejection helpers for ``flip_predict``.

The causal foot-count-2 snapshot registers a line in its direction of travel.
The direct baseline fills the opposite-direction LIMIT on the first touch.
The optional watch policy observes one completed minute after that touch and
then uses line-holding MARKET, near-line retest LIMIT, or continuation STOP.

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


FLIP_VERSION = "flip_predict_v19"
DEFAULT_ORDER_WAIT_MINUTES = 90
DEFAULT_REPLACE_UNFILLED_ON_NEXT_COUNT2 = False
DEFAULT_POSITION_HORIZON_MINUTES = 60
DEFAULT_SPREAD_PIPS = 0.8
DEFAULT_MIN_WIDTH_PIPS = 1.6
DEFAULT_RISK_YEN = 50.0
DEFAULT_MIN_TARGET_DISTANCE_PIPS = 2.0
DEFAULT_PROFIT_LOCK_ENABLED = False
DEFAULT_PROFIT_LOCK_MIN_TP_PIPS = 10.0
DEFAULT_PROFIT_LOCK_TRIGGER_TP_FRACTION = 0.5
DEFAULT_PROFIT_LOCK_RESULT_PIPS = 1.0
# Stretch-profit comparison: the frozen tier TP is 1B. Keep the frozen LC,
# target 2B, arm after 1.2B, and then protect +1B.
STRETCH_PROFIT_TARGET_B = 2.0
STRETCH_PROFIT_TRIGGER_B = 1.2
STRETCH_PROFIT_LOCK_B = 1.0
STRETCH_PROFIT_TRIGGER_TP_FRACTION = (
    STRETCH_PROFIT_TRIGGER_B / STRETCH_PROFIT_TARGET_B
)
STRETCH_PROFIT_LOCK_TP_FRACTION = (
    STRETCH_PROFIT_LOCK_B / STRETCH_PROFIT_TARGET_B
)
DEFAULT_TIMED_HALF_LC_MINUTES = (3, 6, 9, 12, 15, 18)
DEFAULT_TIMED_HALF_LC_FRACTIONS = (0.3, 0.4, 0.5, 0.6, 0.7)
DEFAULT_TIMED_HALF_LC_FRACTION = 0.5
DEFAULT_TIMED_HALF_LC_TP_FRACTION = 0.5
DEFAULT_LINE_WICK_LC_FRACTIONS = (0.05, 0.10, 0.15, 0.20)
WATCH_LINE_HOLDING_MAX_BREAKOUT_A = 0.10
WATCH_LINE_HOLDING_MAX_CHASE_A = 0.30
WATCH_NEAR_LINE_MAX_BREAKOUT_A = 1.00
WATCH_BREAKOUT_CONTINUATION_A = 0.05
WATCH_MAX_ENTRY_GAP_A = 0.10
WATCH_OBSERVATION_SECONDS = 60
EARLY_PATH_MINUTES = (1, 2, 3, 4, 5)
EARLY_PATH_METRICS = (
    "checkpoint_time",
    "checkpoint_evaluable",
    "position_open",
    "current_close_pips",
    "current_close_a",
    "current_line_distance_pips",
    "current_line_distance_a",
    "cumulative_mfe_pips",
    "cumulative_mfe_a",
    "cumulative_mae_pips",
    "cumulative_mae_a",
    "interval_net_pips",
    "interval_net_a",
    "interval_mfe_pips",
    "interval_mfe_a",
    "interval_mae_pips",
    "interval_mae_a",
    "interval_favorable_s5_fraction",
    "interval_line_side_close_fraction",
    "cumulative_line_cross_count",
)
TOP_CONDITION_LIMIT = 15
# Selection gates for condition mining (guards against the sum_yen-volume
# bias and the multiple-testing bias of exhaustively searching hundreds of
# candidate conditions).  See ``select_top_ranked_conditions`` in
# count2_flip_workflow.py.
MINIMUM_CONDITION_TRADES = 30
# How many of the ranked conditions must agree before an event is traded.
# 1 is the plain OR (any single condition triggers).  Agreement behaves like
# confidence: on AUD_USD's OOS year single-match events averaged -14.1 yen
# while four-or-more averaged +22.1, and requiring three turned both AUD_USD
# (-157 -> +271 yen) and EUR_USD (-256 -> +336) profitable.
#
# USD_JPY is set to three for consistency but is not expected to trade much:
# 75% of its matches are single-condition and only 15 OOS events reach three.
# Its problem is upstream -- its conditions barely overlap -- so treat a
# USD_JPY result here as inconclusive rather than as a working policy.
# See memo/flip_predict_todo.md.
DEFAULT_MINIMUM_MATCHED_CONDITIONS = 1
PAIR_MINIMUM_MATCHED_CONDITIONS: dict[str, int] = {
    "AUD_USD": 3,
    "EUR_USD": 3,
    "USD_JPY": 3,
}
# Reward/risk floor applied when picking each tier's TP/LC cell.  Ranking by
# sum_yen alone settles near RR 1.0, which leans on a high win rate; AUD_USD's
# train grid shows TP 2.0A / LC 1.4A (RR 1.43) still wins 62.7% with PF 1.93,
# so a floor buys durability at a modest cost in total yen.  0 disables it.
#
# 1.4 is the shared default for every pair.  A pair that needs a different
# floor overrides it in PAIR_MINIMUM_TIER_RR; setting a pair to 0.0 there
# disables the floor for that pair alone.  The floor is advisory: when no
# TP/LC cell reaches it, selection falls back to the whole grid rather than
# failing, so raising it can never leave a pair without a policy.
DEFAULT_MINIMUM_TIER_RR = 1.4
PAIR_MINIMUM_TIER_RR: dict[str, float] = {}


def minimum_tier_rr_for_pair(pair: str | None) -> float:
    """Return the reward/risk floor for ``pair`` (default: no floor)."""
    if not pair:
        return DEFAULT_MINIMUM_TIER_RR
    return PAIR_MINIMUM_TIER_RR.get(
        str(pair).upper(), DEFAULT_MINIMUM_TIER_RR
    )


@dataclass(frozen=True)
class RiskMultipleProfitLock:
    """Raise the stop to a fixed profit once the trade reaches a trigger.

    Both levels are multiples of R, the trade's own loss-cut distance, so a
    tier running RR 1.43 and one running RR 1.77 still lock the same real
    profit.  With ``trigger_r=1.2`` and ``result_r=1.05`` a trade that runs
    to +1.2R can no longer finish below +1.05R; it gives back 0.15R of the
    high-water mark in exchange for removing the full-loss outcome.

    The trade keeps its original take-profit, so the upside is unchanged --
    this only removes the tail where a winner round-trips back into a loss.
    """

    trigger_r: float
    result_r: float

    def __post_init__(self) -> None:
        values = (self.trigger_r, self.result_r)
        if any(not math.isfinite(value) or value <= 0 for value in values):
            raise ValueError("profit lock R multiples must be finite and positive")
        if self.result_r >= self.trigger_r:
            raise ValueError("locked profit must be below the trigger")

    def fractions_for_rr(self, rr: float) -> tuple[float, float]:
        """Convert the R multiples into fractions of a tier's take-profit.

        ``rr`` is that tier's take-profit expressed in R, so dividing by it
        rebases both levels onto the take-profit scale the path inspector
        works in.  Raises when the trigger is not below the take-profit,
        which would arm the lock only after the trade had already closed.
        """
        rr = float(rr)
        if not math.isfinite(rr) or rr <= 0:
            raise ValueError("tier RR must be finite and positive")
        if self.trigger_r >= rr:
            raise ValueError(
                f"profit lock trigger {self.trigger_r}R is not below the "
                f"take-profit at {rr}R, so it could never arm"
            )
        return self.trigger_r / rr, self.result_r / rr

    def to_dict(self) -> dict[str, Any]:
        return {"trigger_r": self.trigger_r, "result_r": self.result_r}


# Raised-stop policy in multiples of the trade's own risk, shared by every
# pair: protect +1.05R once +1.2R trades, against the 1.4R take-profit.
# Requires trigger_r below each tier's RR, which DEFAULT_MINIMUM_TIER_RR
# (1.4) keeps true.  A pair overrides it in PAIR_RISK_MULTIPLE_PROFIT_LOCK;
# mapping a pair to None there disables the raised stop for that pair alone.
DEFAULT_RISK_MULTIPLE_PROFIT_LOCK = RiskMultipleProfitLock(
    trigger_r=1.2, result_r=1.05
)
PAIR_RISK_MULTIPLE_PROFIT_LOCK: dict[str, RiskMultipleProfitLock | None] = {}


def risk_multiple_profit_lock_for_pair(
    pair: str | None,
) -> RiskMultipleProfitLock | None:
    """Return the raised-stop policy for ``pair``, or None to disable it."""
    if not pair:
        return DEFAULT_RISK_MULTIPLE_PROFIT_LOCK
    return PAIR_RISK_MULTIPLE_PROFIT_LOCK.get(
        str(pair).upper(), DEFAULT_RISK_MULTIPLE_PROFIT_LOCK
    )


def minimum_matched_conditions_for_pair(pair: str | None) -> int:
    """Return the agreement threshold for ``pair`` (default: plain OR)."""
    if not pair:
        return DEFAULT_MINIMUM_MATCHED_CONDITIONS
    return PAIR_MINIMUM_MATCHED_CONDITIONS.get(
        str(pair).upper(), DEFAULT_MINIMUM_MATCHED_CONDITIONS
    )
CONDITION_MINIMUM_POSITIVE_PERIODS = 3
CONDITION_MULTIPLE_TESTING_ALPHA = 0.05
TIER_HIGH = "HIGH"
TIER_MIDDLE = "MIDDLE"
TIER_LOW = "LOW"
TIER_NAMES = (TIER_HIGH, TIER_MIDDLE, TIER_LOW)
RANGE_FILTER_FRACTION_A = 0.25
# The formal timed-LC run holds the causal 0.25A gate at 1.5 pips.
DEFAULT_RANGE_FILTER_PIPS_GRID = (1.5,)
# Train-only TP/LC grid.  Combinations below configured RR 1.0 are excluded.
DEFAULT_TP_A_GRID = (1.0, 1.2, 1.4, 1.5, 1.7, 2.0)
DEFAULT_LC_A_GRID = (
    1.0,
    1.1333333333333333,
    1.25,
    1.4,
    1.5,
    1.6,
    1.7,
    2.0,
)
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
    replace_unfilled_on_next_count2: bool = (
        DEFAULT_REPLACE_UNFILLED_ON_NEXT_COUNT2
    )

    def __post_init__(self) -> None:
        if self.order_wait_minutes < 1:
            raise ValueError("order_wait_minutes must be positive")

    @property
    def config_id(self) -> str:
        replacement = (
            "replace_next_fc2"
            if self.replace_unfilled_on_next_count2
            else "keep_through_next_fc2"
        )
        return f"order_wait{self.order_wait_minutes}m_{replacement}"


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
class FlipWatchEntryConfig:
    """Causal one-minute line watch followed by one of three entry modes."""

    observation_seconds: int = WATCH_OBSERVATION_SECONDS
    line_holding_max_breakout_a: float = (
        WATCH_LINE_HOLDING_MAX_BREAKOUT_A
    )
    line_holding_max_chase_a: float = WATCH_LINE_HOLDING_MAX_CHASE_A
    near_line_max_breakout_a: float = WATCH_NEAR_LINE_MAX_BREAKOUT_A
    breakout_continuation_a: float = WATCH_BREAKOUT_CONTINUATION_A
    max_entry_gap_a: float = WATCH_MAX_ENTRY_GAP_A

    def __post_init__(self) -> None:
        if self.observation_seconds < S5_SECONDS:
            raise ValueError("watch observation must be at least one S5")
        if self.observation_seconds % S5_SECONDS:
            raise ValueError("watch observation must align to completed S5 bars")
        values = (
            self.line_holding_max_breakout_a,
            self.line_holding_max_chase_a,
            self.near_line_max_breakout_a,
            self.breakout_continuation_a,
            self.max_entry_gap_a,
        )
        if any(not math.isfinite(value) or value <= 0 for value in values):
            raise ValueError("watch A thresholds must be finite and positive")
        if (
            self.near_line_max_breakout_a
            <= self.line_holding_max_breakout_a
        ):
            raise ValueError("near-line upper bound must exceed holding bound")

    @property
    def observation_bars(self) -> int:
        return self.observation_seconds // S5_SECONDS

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "FlipWatchEntryConfig":
        return cls(**dict(value))


def classify_flip_watch_entry(
    breakout_distance_a: float,
    breakout_direction: int,
    config: FlipWatchEntryConfig,
) -> dict[str, Any]:
    """Classify a completed watch window without reading any future price."""
    breakout_distance_a = float(breakout_distance_a)
    breakout_direction = int(breakout_direction)
    if not math.isfinite(breakout_distance_a):
        raise ValueError("watch breakout distance must be finite")
    if breakout_direction not in (-1, 1):
        raise ValueError("watch breakout direction must be -1 or 1")
    if breakout_distance_a < config.line_holding_max_breakout_a:
        return {
            "watch_order_name": "FlipPredict_LineHolding",
            "watch_entry_mode": "MARKET",
            "order_direction": -breakout_direction,
            "watch_chase_filtered": bool(
                breakout_distance_a < -config.line_holding_max_chase_a
            ),
        }
    if breakout_distance_a <= config.near_line_max_breakout_a:
        return {
            "watch_order_name": "FlipPredict_NearLineConsolidation",
            "watch_entry_mode": "LIMIT_RETEST",
            "order_direction": breakout_direction,
            "watch_chase_filtered": False,
        }
    return {
        "watch_order_name": "FlipPredict_Breakout",
        "watch_entry_mode": "STOP_CONTINUATION",
        "order_direction": breakout_direction,
        "watch_chase_filtered": False,
    }


@dataclass(frozen=True)
class TimedHalfLcConfig:
    """Causal checkpoint exit when open P/L is at or below a fraction of LC."""

    trigger_minutes: int | None
    lc_fraction: float = DEFAULT_TIMED_HALF_LC_FRACTION
    tp_fraction: float = DEFAULT_TIMED_HALF_LC_TP_FRACTION

    def __post_init__(self) -> None:
        if self.trigger_minutes is not None and self.trigger_minutes < 1:
            raise ValueError("timed half-LC minutes must be positive")
        if not math.isfinite(self.lc_fraction) or not 0 < self.lc_fraction <= 1:
            raise ValueError("timed half-LC fraction must be in (0, 1]")
        if not math.isfinite(self.tp_fraction) or not 0 < self.tp_fraction < 1:
            raise ValueError("timed half-LC TP fraction must be in (0, 1)")

    @property
    def enabled(self) -> bool:
        return self.trigger_minutes is not None

    @property
    def config_id(self) -> str:
        if not self.enabled:
            return "baseline"
        fraction = f"{self.lc_fraction:g}".replace(".", "p")
        return f"timed_{self.trigger_minutes}m_lc{fraction}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "config_id": self.config_id,
            "enabled": self.enabled,
            "trigger_minutes": self.trigger_minutes,
            "lc_fraction": self.lc_fraction,
            "tp_fraction": self.tp_fraction,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TimedHalfLcConfig":
        minutes = value.get("trigger_minutes")
        config = cls(
            trigger_minutes=(
                None if minutes is None or pd.isna(minutes) else int(minutes)
            ),
            lc_fraction=float(value["lc_fraction"]),
            tp_fraction=float(value["tp_fraction"]),
        )
        expected_id = value.get("config_id")
        if expected_id is not None and str(expected_id) != config.config_id:
            raise ValueError("timed half-LC config id mismatch")
        enabled = value.get("enabled")
        if (
            enabled is not None
            and not pd.isna(enabled)
            and bool(enabled) != config.enabled
        ):
            raise ValueError("timed half-LC enabled flag mismatch")
        return config


@dataclass(frozen=True)
class LineWickLcConfig:
    """Protective stop when the spread-aware S5 wick crosses the line."""

    width_a: float | None

    def __post_init__(self) -> None:
        if self.width_a is not None and (
            not math.isfinite(self.width_a) or self.width_a <= 0
        ):
            raise ValueError("line-wick LC width A must be finite and positive")

    @property
    def enabled(self) -> bool:
        return self.width_a is not None

    @property
    def config_id(self) -> str:
        if not self.enabled:
            return "baseline"
        width = f"{self.width_a:g}".replace(".", "p")
        return f"line_wick_lc_{width}A"

    def to_dict(self) -> dict[str, Any]:
        return {
            "config_id": self.config_id,
            "enabled": self.enabled,
            "width_a": self.width_a,
            "trigger_source": "spread_aware_s5_wick",
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LineWickLcConfig":
        width = value.get("width_a")
        config = cls(
            None if width is None or pd.isna(width) else float(width)
        )
        expected_id = value.get("config_id")
        if expected_id is not None and str(expected_id) != config.config_id:
            raise ValueError("line-wick LC config id mismatch")
        enabled = value.get("enabled")
        if (
            enabled is not None
            and not pd.isna(enabled)
            and bool(enabled) != config.enabled
        ):
            raise ValueError("line-wick LC enabled flag mismatch")
        return config


def default_timed_half_lc_configs() -> tuple[TimedHalfLcConfig, ...]:
    return (
        TimedHalfLcConfig(None),
        *(
            TimedHalfLcConfig(minutes, lc_fraction=fraction)
            for minutes in DEFAULT_TIMED_HALF_LC_MINUTES
            for fraction in DEFAULT_TIMED_HALF_LC_FRACTIONS
        ),
    )


def default_line_wick_lc_configs() -> tuple[LineWickLcConfig, ...]:
    return (
        LineWickLcConfig(None),
        *(
            LineWickLcConfig(width_a)
            for width_a in DEFAULT_LINE_WICK_LC_FRACTIONS
        ),
    )


def overlay_outcome_key(
    combo: TradeCombo,
    timed_config: TimedHalfLcConfig,
    line_wick_config: LineWickLcConfig,
) -> str:
    enabled_ids = [
        config.config_id
        for config in (timed_config, line_wick_config)
        if config.enabled
    ]
    return "__".join((combo.combo_id, *enabled_ids))


def timed_outcome_key(combo: TradeCombo, config: TimedHalfLcConfig) -> str:
    return overlay_outcome_key(
        combo,
        config,
        LineWickLcConfig(None),
    )


def line_wick_outcome_key(
    combo: TradeCombo, config: LineWickLcConfig
) -> str:
    return overlay_outcome_key(
        combo,
        TimedHalfLcConfig(None),
        config,
    )


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
    min_range_filter_pips: float = 0.0

    def __post_init__(self) -> None:
        if self.tier not in TIER_NAMES:
            raise ValueError(f"unknown signal tier: {self.tier}")
        if self.first_rank < 1 or self.last_rank < self.first_rank:
            raise ValueError("invalid tier rank range")
        if not math.isfinite(self.tp_a) or self.tp_a <= 0:
            raise ValueError("tier TP must be finite and positive")
        if not math.isfinite(self.rr) or self.rr <= 0:
            raise ValueError("tier RR must be finite and positive")
        if (
            not math.isfinite(self.min_range_filter_pips)
            or self.min_range_filter_pips < 0
        ):
            raise ValueError("tier range filter must be finite and non-negative")

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
            "range_filter_fraction_a": RANGE_FILTER_FRACTION_A,
            "min_range_filter_pips": self.min_range_filter_pips,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TierExecutionConfig":
        return cls(
            tier=str(value["tier"]),
            first_rank=int(value["first_rank"]),
            last_rank=int(value["last_rank"]),
            tp_a=float(value["tp_a"]),
            rr=float(value["rr"]),
            min_range_filter_pips=float(
                value.get("min_range_filter_pips", 0.0)
            ),
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
    return tuple(
        FlipPathConfig(
            wait,
            replace_unfilled_on_next_count2=(
                DEFAULT_REPLACE_UNFILLED_ON_NEXT_COUNT2
            ),
        )
        for wait in (60, 90)
    )


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
    """Return the train-only TP/LC grid with the requested RR floor."""
    return tuple(
        TradeCombo(tp_a, lc_a)
        for tp_a in DEFAULT_TP_A_GRID
        for lc_a in DEFAULT_LC_A_GRID
        if tp_a / lc_a + 1e-12 >= min_rr
    )


@dataclass(frozen=True)
class BucketSpec:
    """Edges and labels that group one continuous column into buckets.

    ``edges`` are ``pandas.cut`` bin boundaries (right-closed, with the
    lowest interval inclusive), so a value equal to an edge falls into the
    bucket *below* it.  ``labels`` must therefore have exactly one fewer
    entry than ``edges``.
    """

    source_column: str
    edges: tuple[float, ...]
    labels: tuple[str, ...]

    def __post_init__(self) -> None:
        if len(self.labels) != len(self.edges) - 1:
            raise ValueError(
                f"{self.source_column}: {len(self.edges)} edges need "
                f"{len(self.edges) - 1} labels, got {len(self.labels)}"
            )
        if len(set(self.labels)) != len(self.labels):
            raise ValueError(f"{self.source_column}: bucket labels must be unique")
        if any(
            not (left < right)
            for left, right in zip(self.edges, self.edges[1:])
        ):
            raise ValueError(
                f"{self.source_column}: bucket edges must strictly increase"
            )


# Bucket edges are tuned per pair because the same nominal strength means
# different things across pairs -- e.g. line_average_strength sits exactly
# at 5.0 for ~45% of AUD_USD candidates but ~63% of USD_JPY candidates.
# Only continuous inputs whose distribution is pair-dependent live here;
# categorical features (shape, session, direction) need no edges.
DEFAULT_BUCKET_SPECS: dict[str, BucketSpec] = {
    "f_distance_a": BucketSpec(
        "distance_a",
        (-np.inf, 0.5, 1.0, 2.0, 4.0, np.inf),
        ("lt0p5", "0p5to1", "1to2", "2to4", "ge4"),
    ),
    "f_peaks_count": BucketSpec(
        "line_count",
        (-np.inf, 1, 2, 3, np.inf),
        ("1", "2", "3", "4plus"),
    ),
    "f_core_peak": BucketSpec(
        "line_core_count",
        (-np.inf, 1, 2, np.inf),
        ("1", "2", "3plus"),
    ),
    "f_line_average_strength": BucketSpec(
        "line_average_strength",
        (-np.inf, 2.49, 3.49, 4.99, 5.0, np.inf),
        ("lt2p5", "2p5to3p4", "3p5to4p9", "eq5", "gt5"),
    ),
    "f_line_total_strength": BucketSpec(
        "line_total_strength",
        (-np.inf, 5, 9, 14, np.inf),
        ("le5", "6to9", "10to14", "ge15"),
    ),
    "f_line_core_total_strength": BucketSpec(
        "line_core_total_strength",
        (-np.inf, 5, 10, np.inf),
        ("le5", "6to10", "ge11"),
    ),
    # Share of the line's strength contributed by repeat-touch core peaks.
    # "eq1" (every peak is core) is a genuine point mass at 54%/70%.
    "f_line_core_strength_ratio": BucketSpec(
        "line_core_strength_ratio",
        (-np.inf, 0.6, 0.999, np.inf),
        ("lt0p6", "0p6to0p99", "eq1"),
    ),
    # This line's strength against the median of the lines competing at the
    # same event -- the best-spread strength feature on both pairs, because
    # it rescales away the absolute point masses.
    "f_line_relative_strength": BucketSpec(
        "line_relative_total_strength",
        (-np.inf, 0.999, 1.0, 1.5, np.inf),
        ("lt1", "eq1", "1to1p5", "gt1p5"),
    ),
    # The line lookback window caps ages near ~300 minutes, so the earlier
    # 60/240/1440 edges left "ge24h" almost empty (~1.8%) and dumped 57-60%
    # of candidates into "1to4h".  These quartile-based edges hold for both
    # AUD_USD and USD_JPY (no bucket above 27%), so they stay shared:
    # identical edges keep condition ids meaning the same thing across pairs.
    "f_line_age": BucketSpec(
        "line_age_minutes",
        (-np.inf, 60, 120, 200, 255, np.inf),
        ("le1h", "1to2h", "2to3h", "3to4h", "gt4h"),
    ),
    # Roughly quartiles of the non-missing population.  "missing" (never
    # flipped) is itself ~45-49% of candidates and is a meaningful bucket,
    # not a gap to be filled.
    "f_minutes_since_flip": BucketSpec(
        "minutes_since_line_flip",
        (-np.inf, 40, 85, 150, np.inf),
        ("le40m", "41to85m", "86to150m", "gt150m"),
    ),
    "f_prior_retouch": BucketSpec(
        "prior_retouch_count",
        (-np.inf, 0, 1, 2, np.inf),
        ("0", "1", "2", "3plus"),
    ),
    # peak_strength is effectively two-valued in practice (2 or 5; ~0.01%
    # of candidates exceed 5).  The earlier le1/2/3/4to5/gt5 edges left
    # "le1" and "3" permanently empty, so those buckets could never be
    # enumerated as conditions and only inflated the candidate count.
    "f_peak_strength": BucketSpec(
        "peak_strength",
        (-np.inf, 2, 5, np.inf),
        ("le2", "3to5", "gt5"),
    ),
}

# Per-pair overrides.  A pair listed here replaces only the named features;
# everything else falls back to DEFAULT_BUCKET_SPECS.  Add a pair's entry
# after measuring its own candidate distribution with
# count2_flip_bucket_report.py -- do not copy another pair's edges without
# checking.  Prefer a shared default when it holds for every pair: identical
# edges keep a condition id meaning the same thing across pairs.
#
# Not every skew is fixable by re-bucketing.  line_core_count sits at 1 for
# 76% (AUD_USD) / 82% (USD_JPY) of candidates and line_average_strength sits
# at exactly 5.0 for 45% / 63%: those are genuine point masses in the source
# data, and no edge placement can split a single repeated value.
PAIR_BUCKET_OVERRIDES: dict[str, dict[str, BucketSpec]] = {
    "AUD_USD": {},
    "EUR_USD": {},
    "USD_JPY": {
        # USD_JPY concentrates harder at exactly 5.0 (63% vs AUD_USD's 45%),
        # leaving only 29% below it.  The shared five-bucket split strands
        # "lt2p5" at 2.4% here, so the two weakest buckets are merged.
        "f_line_average_strength": BucketSpec(
            "line_average_strength",
            (-np.inf, 3.49, 4.99, 5.0, np.inf),
            ("lt3p5", "3p5to4p9", "eq5", "gt5"),
        ),
    },
}


def bucket_specs_for_pair(pair: str | None) -> dict[str, BucketSpec]:
    """Return the effective bucket specs for ``pair``.

    Unknown or omitted pairs fall back to the shared defaults, so adding a
    new pair never requires editing this module first.
    """
    specs = dict(DEFAULT_BUCKET_SPECS)
    if pair:
        specs.update(PAIR_BUCKET_OVERRIDES.get(str(pair).upper(), {}))
    return specs


def _inverse_normal_cdf_upper_tail(tail_probability: float) -> float:
    """Return z such that P(Z > z) = tail_probability, for a standard normal Z.

    Uses the Abramowitz & Stegun 26.2.23 rational approximation (accurate to
    about 4.5e-4) so no external statistics dependency (e.g. scipy) is
    required.  Only valid for ``0 < tail_probability <= 0.5``.
    """
    if not math.isfinite(tail_probability) or not 0 < tail_probability <= 0.5:
        raise ValueError("tail probability must be in (0, 0.5]")
    t = math.sqrt(-2.0 * math.log(tail_probability))
    c0, c1, c2 = 2.515517, 0.802853, 0.010328
    d1, d2, d3 = 1.432788, 0.189269, 0.001308
    return t - (c0 + c1 * t + c2 * t * t) / (
        1.0 + d1 * t + d2 * t * t + d3 * t * t * t
    )


def bonferroni_z_threshold(
    num_candidates: int,
    alpha: float = CONDITION_MULTIPLE_TESTING_ALPHA,
) -> float:
    """Two-sided per-comparison z critical value under a Bonferroni correction.

    When ``num_candidates`` conditions are exhaustively tested for a
    train-period edge, the chance of at least one showing an apparent edge by
    pure luck grows with the number of candidates.  Bonferroni correction
    keeps the family-wise false-positive rate at ``alpha`` by requiring each
    individual candidate's two-sided test to clear ``alpha / num_candidates``
    instead of the uncorrected ``alpha``.
    """
    if num_candidates < 1:
        raise ValueError("num_candidates must be positive")
    if not math.isfinite(alpha) or not 0 < alpha < 1:
        raise ValueError("alpha must be in (0, 1)")
    tail_probability = alpha / (2.0 * num_candidates)
    return _inverse_normal_cdf_upper_tail(tail_probability)


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
    required_fields = {
        "target_source_last_time",
        "fc2_source_last_time",
        "h1_pair_source_last_time",
        "line_newest_source_time",
    }
    for field in (
        "target_source_last_time",
        "fc2_source_last_time",
        "h1_pair_source_last_time",
        "line_newest_source_time",
        "line_latest_touch_time",
    ):
        raw = row.get(field)
        if raw is None or raw == "" or pd.isna(raw):
            if field in required_fields:
                raise ValueError(f"missing causal candidate feature: {field}")
            continue
        timestamp = pd.to_datetime(raw, errors="coerce")
        if pd.isna(timestamp):
            if field in required_fields:
                raise ValueError(f"invalid causal candidate feature: {field}")
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
        profit_lock_enabled: bool = DEFAULT_PROFIT_LOCK_ENABLED,
        profit_lock_min_tp_pips: float = DEFAULT_PROFIT_LOCK_MIN_TP_PIPS,
        profit_lock_trigger_tp_fraction: float = (
            DEFAULT_PROFIT_LOCK_TRIGGER_TP_FRACTION
        ),
        profit_lock_result_pips: float = DEFAULT_PROFIT_LOCK_RESULT_PIPS,
        profit_lock_result_tp_fraction: float | None = None,
    ) -> None:
        if spread_pips < 0 or position_horizon_minutes < 1 or min_width_pips <= 0:
            raise ValueError("invalid flip path execution parameters")
        result_fraction = (
            None
            if profit_lock_result_tp_fraction is None
            else float(profit_lock_result_tp_fraction)
        )
        if (
            not math.isfinite(profit_lock_min_tp_pips)
            or profit_lock_min_tp_pips <= 0
            or not math.isfinite(profit_lock_trigger_tp_fraction)
            or not 0 < profit_lock_trigger_tp_fraction < 1
            or not math.isfinite(profit_lock_result_pips)
            or profit_lock_result_pips <= 0
            or (
                result_fraction is None
                and profit_lock_result_pips
                >= profit_lock_min_tp_pips * profit_lock_trigger_tp_fraction
            )
            or (
                result_fraction is not None
                and (
                    not math.isfinite(result_fraction)
                    or not 0 < result_fraction < profit_lock_trigger_tp_fraction
                )
            )
        ):
            raise ValueError("invalid profit-lock parameters")
        self.inspector = inspector
        self.pair = pair
        self.period_end = pd.Timestamp(period_end_exclusive)
        self.spread_pips = float(spread_pips)
        self.position_horizon_minutes = int(position_horizon_minutes)
        self.min_width_pips = float(min_width_pips)
        self.risk_yen = float(risk_yen)
        self.profit_lock_enabled = bool(profit_lock_enabled)
        self.profit_lock_min_tp_pips = float(profit_lock_min_tp_pips)
        self.profit_lock_trigger_tp_fraction = float(
            profit_lock_trigger_tp_fraction
        )
        self.profit_lock_result_pips = float(profit_lock_result_pips)
        self.profit_lock_result_tp_fraction = result_fraction
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
            "signal_order_direction": np.nan,
            "order_direction": np.nan,
            "order_filled": False,
            "order_deadline": pd.NaT,
            "replaced_before_fill": False,
            "watch_entry_enabled": False,
            "watch_order_name": None,
            "watch_entry_mode": None,
            "watch_initial_touch_deadline": pd.NaT,
            "watch_line_touch_time": pd.NaT,
            "watch_line_touch_known_time": pd.NaT,
            "watch_observation_known_time": pd.NaT,
            "watch_order_placed_time": pd.NaT,
            "watch_order_release_time": pd.NaT,
            "watch_observation_close": np.nan,
            "watch_observation_high": np.nan,
            "watch_observation_low": np.nan,
            "watch_breakout_direction": np.nan,
            "watch_breakout_distance_pips": np.nan,
            "watch_breakout_distance_a": np.nan,
            "watch_observed_extreme_price": np.nan,
            "watch_entry_trigger_price": np.nan,
            "watch_actual_entry_distance_from_line_a": np.nan,
            "watch_entry_gap_from_trigger_a": np.nan,
            "watch_chase_filtered": False,
            "watch_entry_gap_filtered": False,
            "watch_stop_fill_bar_adverse_censored": False,
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

    def _early_path_fields(
        self,
        *,
        path_times: np.ndarray,
        timer_anchor: pd.Timestamp,
        exit_effective_time: pd.Timestamp,
        entry_price: float,
        line_price: float,
        order_direction: int,
        average_range_pips: float,
        close_progress: np.ndarray,
        open_progress: np.ndarray,
        metric_favorable: np.ndarray,
        metric_adverse: np.ndarray,
        path_opens: np.ndarray,
        path_closes: np.ndarray,
    ) -> dict[str, Any]:
        """Return causal, completed-S5 snapshots for minutes 1 through 5.

        Snapshot values are populated only while the position is still open at
        the checkpoint.  The final outcome and final MFE/MAE remain separate
        labels, so prices after an earlier exit can never become position data.
        """
        output: dict[str, Any] = {}
        timer_anchor = pd.Timestamp(timer_anchor)
        exit_effective_time = pd.Timestamp(exit_effective_time)
        path_times = np.asarray(path_times)
        close_progress = np.asarray(close_progress, dtype=float)
        open_progress = np.asarray(open_progress, dtype=float)
        metric_favorable = np.asarray(metric_favorable, dtype=float)
        metric_adverse = np.asarray(metric_adverse, dtype=float)
        path_opens = np.asarray(path_opens, dtype=float)
        path_closes = np.asarray(path_closes, dtype=float)
        executable_line_offset_pips = float(
            order_direction * (entry_price - line_price) / self.pair.pip_value
        )

        for minute in EARLY_PATH_MINUTES:
            prefix = f"early_m{minute}_"
            checkpoint = timer_anchor + pd.Timedelta(minutes=minute)
            for metric in EARLY_PATH_METRICS:
                output[prefix + metric] = (
                    pd.NaT if metric == "checkpoint_time" else np.nan
                )
            output[prefix + "checkpoint_time"] = checkpoint
            if checkpoint >= self.period_end:
                output[prefix + "checkpoint_time"] = pd.NaT
                output[prefix + "checkpoint_evaluable"] = False
                output[prefix + "position_open"] = False
                continue

            end_i = int(
                np.searchsorted(
                    path_times,
                    np.datetime64(checkpoint, "ns"),
                    side="left",
                )
            )
            start_time = checkpoint - pd.Timedelta(minutes=1)
            start_i = int(
                np.searchsorted(
                    path_times,
                    np.datetime64(start_time, "ns"),
                    side="left",
                )
            )
            expected_bars = int(pd.Timedelta(minutes=1).total_seconds() / S5_SECONDS)
            interval_complete = bool(
                end_i > start_i
                and end_i <= len(path_times)
                and end_i - start_i == expected_bars
                and pd.Timestamp(path_times[start_i]) == start_time
                and pd.Timestamp(path_times[end_i - 1])
                + pd.Timedelta(seconds=S5_SECONDS)
                == checkpoint
                and not np.any(
                    np.diff(path_times[start_i:end_i])
                    != np.timedelta64(S5_SECONDS, "s")
                )
            )
            position_open = bool(exit_effective_time > checkpoint)
            output[prefix + "checkpoint_evaluable"] = bool(
                interval_complete and position_open
            )
            output[prefix + "position_open"] = position_open
            if not interval_complete or not position_open:
                continue

            completed = slice(0, end_i)
            interval = slice(start_i, end_i)
            current_close_pips = float(close_progress[end_i - 1])
            line_close = (
                close_progress[:end_i] + executable_line_offset_pips
            )
            initial_line_distance = float(
                open_progress[0] + executable_line_offset_pips
            )
            line_sign = np.sign(
                np.concatenate(([initial_line_distance], line_close))
            )
            nonzero_line_sign = line_sign[line_sign != 0]
            cross_count = int(
                np.count_nonzero(
                    nonzero_line_sign[1:] != nonzero_line_sign[:-1]
                )
            )
            favorable_bodies = (
                order_direction
                * (path_closes[interval] - path_opens[interval])
                > 0
            )
            output.update(
                {
                    prefix + "current_close_pips": current_close_pips,
                    prefix + "current_close_a": (
                        current_close_pips / average_range_pips
                    ),
                    prefix + "current_line_distance_pips": float(
                        line_close[-1]
                    ),
                    prefix + "current_line_distance_a": float(
                        line_close[-1] / average_range_pips
                    ),
                    prefix + "cumulative_mfe_pips": float(
                        np.nanmax(metric_favorable[completed])
                    ),
                    prefix + "cumulative_mfe_a": float(
                        np.nanmax(metric_favorable[completed])
                        / average_range_pips
                    ),
                    prefix + "cumulative_mae_pips": float(
                        np.nanmin(metric_adverse[completed])
                    ),
                    prefix + "cumulative_mae_a": float(
                        np.nanmin(metric_adverse[completed])
                        / average_range_pips
                    ),
                    prefix + "interval_net_pips": float(
                        current_close_pips - open_progress[start_i]
                    ),
                    prefix + "interval_net_a": float(
                        (current_close_pips - open_progress[start_i])
                        / average_range_pips
                    ),
                    prefix + "interval_mfe_pips": float(
                        np.nanmax(metric_favorable[interval])
                    ),
                    prefix + "interval_mfe_a": float(
                        np.nanmax(metric_favorable[interval])
                        / average_range_pips
                    ),
                    prefix + "interval_mae_pips": float(
                        np.nanmin(metric_adverse[interval])
                    ),
                    prefix + "interval_mae_a": float(
                        np.nanmin(metric_adverse[interval])
                        / average_range_pips
                    ),
                    prefix + "interval_favorable_s5_fraction": float(
                        np.mean(favorable_bodies)
                    ),
                    prefix + "interval_line_side_close_fraction": float(
                        np.mean(line_close[start_i:end_i] >= 0)
                    ),
                    prefix + "cumulative_line_cross_count": cross_count,
                }
            )
        return output

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
        timed_half_lc_configs: Iterable[TimedHalfLcConfig] | None = None,
        line_wick_lc_configs: Iterable[LineWickLcConfig] | None = None,
        watch_entry_config: FlipWatchEntryConfig | None = None,
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
            path_config.replace_unfilled_on_next_count2
            and not pd.isna(next_count2)
            and decision_time < next_count2 < order_deadline
        ):
            order_deadline = pd.Timestamp(next_count2)
            replacement_cutoff = True
        common = {
            **base,
            "approach_direction": approach_direction,
            "signal_order_direction": order_direction,
            "order_direction": order_direction,
            "order_deadline": order_deadline,
            "watch_entry_enabled": watch_entry_config is not None,
            "watch_initial_touch_deadline": (
                order_deadline if watch_entry_config is not None else pd.NaT
            ),
            "watch_breakout_direction": approach_direction,
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

        touch_i = start_i + int(reached[0])
        touch_time = pd.Timestamp(self.times[touch_i])
        if not self._indexed_window_complete(
            start_i,
            touch_i + 1,
            decision_time,
            touch_time + pd.Timedelta(seconds=S5_SECONDS),
        ):
            closed = _is_expected_market_closed_gap(
                decision_time - pd.Timedelta(seconds=S5_SECONDS), touch_time
            )
            return {
                **common,
                "path_status": (
                    "incomplete_order_before_fill"
                    if not closed
                    else "incomplete_order_window"
                ),
            }
        fill_i = touch_i
        fill_time = touch_time
        entry_price = line_price
        fill_at_open = bool(
            float(self.opens[fill_i]) + half_spread <= line_price
            if order_direction == 1
            else float(self.opens[fill_i]) - half_spread >= line_price
        )
        watch_fields: dict[str, Any] = {
            "watch_line_touch_time": touch_time,
            "watch_line_touch_known_time": (
                touch_time + pd.Timedelta(seconds=S5_SECONDS)
            ),
        }
        if watch_entry_config is not None:
            observation_end_i = touch_i + watch_entry_config.observation_bars + 1
            if observation_end_i >= len(self.times):
                return {
                    **common,
                    **watch_fields,
                    "path_status": "incomplete_watch_observation",
                }
            observation_start_i = touch_i + 1
            observation_known_time = pd.Timestamp(self.times[observation_end_i])
            if observation_known_time >= self.period_end:
                return {
                    **common,
                    **watch_fields,
                    "path_status": "incomplete_watch_observation",
                }
            if not self._strict_position_window_complete(
                observation_start_i,
                observation_end_i,
                touch_time + pd.Timedelta(seconds=S5_SECONDS),
                observation_known_time,
            ):
                return {
                    **common,
                    **watch_fields,
                    "path_status": "incomplete_watch_observation",
                }
            observation_close = float(self.closes[observation_end_i - 1])
            observation_high = float(
                np.max(self.highs[observation_start_i:observation_end_i])
            )
            observation_low = float(
                np.min(self.lows[observation_start_i:observation_end_i])
            )
            a_price = self.pair.pips_to_price(average_range_pips)
            breakout_direction = approach_direction
            breakout_distance_a = float(
                (observation_close - line_price) * breakout_direction / a_price
            )
            watch_fields.update(
                {
                    "watch_observation_known_time": observation_known_time,
                    "watch_observation_close": observation_close,
                    "watch_observation_high": observation_high,
                    "watch_observation_low": observation_low,
                    "watch_breakout_direction": breakout_direction,
                    "watch_breakout_distance_pips": (
                        breakout_distance_a * average_range_pips
                    ),
                    "watch_breakout_distance_a": breakout_distance_a,
                    "watch_order_placed_time": observation_known_time,
                }
            )
            search_start_i = observation_end_i
            classification = classify_flip_watch_entry(
                breakout_distance_a,
                breakout_direction,
                watch_entry_config,
            )
            watch_fields.update(classification)
            order_direction = int(classification["order_direction"])
            if classification["watch_entry_mode"] == "MARKET":
                order_deadline = observation_known_time
            else:
                order_deadline = min(
                    observation_known_time
                    + pd.Timedelta(minutes=path_config.order_wait_minutes),
                    self.period_end,
                )
            common["order_deadline"] = order_deadline
            watch_fields["watch_order_release_time"] = order_deadline
            expiry_i = int(
                np.searchsorted(
                    self.times,
                    np.datetime64(order_deadline, "ns"),
                    side="left",
                )
            )
            if classification["watch_order_name"] == "FlipPredict_LineHolding":
                if classification["watch_chase_filtered"]:
                    return {
                        **common,
                        **watch_fields,
                        "path_status": "watch_line_holding_chase_filtered",
                        "watch_chase_filtered": True,
                    }
                fill_i = search_start_i
                fill_time = pd.Timestamp(self.times[fill_i])
                entry_price = float(
                    self.opens[fill_i] + half_spread * order_direction
                )
                fill_at_open = True
                watch_fields["watch_entry_trigger_price"] = entry_price
                open_breakout_a = float(
                    (entry_price - line_price)
                    * breakout_direction
                    / a_price
                )
                if not (
                    -watch_entry_config.line_holding_max_chase_a
                    <= open_breakout_a
                    < watch_entry_config.line_holding_max_breakout_a
                ):
                    return {
                        **common,
                        **watch_fields,
                        "order_direction": order_direction,
                        "path_status": "watch_line_holding_entry_quote_filtered",
                        "watch_entry_gap_filtered": True,
                        "watch_order_release_time": fill_time,
                    }
            elif (
                classification["watch_order_name"]
                == "FlipPredict_NearLineConsolidation"
            ):
                watch_fields["watch_entry_trigger_price"] = line_price
                if order_direction == 1:
                    entry_touches = (
                        self.lows[search_start_i:expiry_i] + half_spread
                        <= line_price
                    )
                else:
                    entry_touches = (
                        self.highs[search_start_i:expiry_i] - half_spread
                        >= line_price
                    )
                entry_reached = np.flatnonzero(entry_touches)
                if not entry_reached.size:
                    complete = self._indexed_window_complete(
                        search_start_i,
                        expiry_i,
                        observation_known_time,
                        order_deadline,
                    )
                    return {
                        **common,
                        **watch_fields,
                        "order_direction": order_direction,
                        "path_status": (
                            "watch_retest_no_fill"
                            if complete
                            else "incomplete_order_window"
                        ),
                    }
                fill_i = search_start_i + int(entry_reached[0])
                fill_time = pd.Timestamp(self.times[fill_i])
                marketable_open = float(
                    self.opens[fill_i] + half_spread * order_direction
                )
                fill_at_open = bool(
                    marketable_open <= line_price
                    if order_direction == 1
                    else marketable_open >= line_price
                )
                entry_price = marketable_open if fill_at_open else line_price
            else:
                continuation_price = self.pair.pips_to_price(
                    average_range_pips
                    * watch_entry_config.breakout_continuation_a
                )
                if order_direction == 1:
                    observed_extreme = float(
                        np.max(
                            self.highs[observation_start_i:observation_end_i]
                            + half_spread
                        )
                    )
                    trigger_price = observed_extreme + continuation_price
                    entry_touches = (
                        self.highs[search_start_i:expiry_i] + half_spread
                        >= trigger_price
                    )
                else:
                    observed_extreme = float(
                        np.min(
                            self.lows[observation_start_i:observation_end_i]
                            - half_spread
                        )
                    )
                    trigger_price = observed_extreme - continuation_price
                    entry_touches = (
                        self.lows[search_start_i:expiry_i] - half_spread
                        <= trigger_price
                    )
                watch_fields["watch_entry_trigger_price"] = trigger_price
                watch_fields["watch_observed_extreme_price"] = observed_extreme
                entry_reached = np.flatnonzero(entry_touches)
                if not entry_reached.size:
                    complete = self._indexed_window_complete(
                        search_start_i,
                        expiry_i,
                        observation_known_time,
                        order_deadline,
                    )
                    return {
                        **common,
                        **watch_fields,
                        "order_direction": order_direction,
                        "path_status": (
                            "watch_breakout_no_fill"
                            if complete
                            else "incomplete_order_window"
                        ),
                    }
                fill_i = search_start_i + int(entry_reached[0])
                fill_time = pd.Timestamp(self.times[fill_i])
                marketable_open = float(
                    self.opens[fill_i] + half_spread * order_direction
                )
                fill_at_open = bool(
                    marketable_open >= trigger_price
                    if order_direction == 1
                    else marketable_open <= trigger_price
                )
                entry_price = marketable_open if fill_at_open else trigger_price
            watch_fields["watch_actual_entry_distance_from_line_a"] = float(
                abs(entry_price - line_price) / a_price
            )
            watch_fields["watch_entry_gap_from_trigger_a"] = float(
                abs(entry_price - float(watch_fields["watch_entry_trigger_price"]))
                / a_price
            )
            if not self._indexed_window_complete(
                touch_i,
                fill_i + 1,
                touch_time,
                fill_time + pd.Timedelta(seconds=S5_SECONDS),
            ):
                return {
                    **common,
                    **watch_fields,
                    "order_direction": order_direction,
                    "path_status": "incomplete_watch_before_fill",
                }
            if (
                fill_at_open
                and watch_fields.get("watch_entry_mode")
                in {"LIMIT_RETEST", "STOP_CONTINUATION"}
                and watch_fields["watch_entry_gap_from_trigger_a"]
                > watch_entry_config.max_entry_gap_a + 1e-12
            ):
                return {
                    **common,
                    **watch_fields,
                    "order_direction": order_direction,
                    "path_status": "watch_entry_gap_filtered",
                    "watch_entry_gap_filtered": True,
                    "watch_order_release_time": fill_time,
                }
            watch_fields["watch_order_release_time"] = fill_time
        filled = {
            **common,
            **watch_fields,
            "order_direction": order_direction,
            "order_filled": True,
            "fill_time": fill_time,
            "fill_delay_from_decision_seconds": float(
                (fill_time - decision_time).total_seconds()
            ),
            "fill_at_bar_open": bool(fill_at_open),
            "watch_stop_fill_bar_adverse_censored": bool(
                watch_fields.get("watch_entry_mode") == "STOP_CONTINUATION"
                and not fill_at_open
            ),
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
            favorable = (high - half_spread - entry_price) / self.pair.pip_value
            adverse = (low - half_spread - entry_price) / self.pair.pip_value
            close_progress = (
                close - half_spread - entry_price
            ) / self.pair.pip_value
            open_progress = (
                self.opens[fill_i:end_i] - half_spread - entry_price
            ) / self.pair.pip_value
            timeout_pips = float(close_progress[-1])
            fill_close_progress = float(
                (close[0] - half_spread - entry_price) / self.pair.pip_value
            )
        else:
            favorable = (entry_price - (low + half_spread)) / self.pair.pip_value
            adverse = (entry_price - (high + half_spread)) / self.pair.pip_value
            close_progress = (
                entry_price - (close + half_spread)
            ) / self.pair.pip_value
            open_progress = (
                entry_price - (self.opens[fill_i:end_i] + half_spread)
            ) / self.pair.pip_value
            timeout_pips = float(close_progress[-1])
            fill_close_progress = float(
                (entry_price - (close[0] + half_spread)) / self.pair.pip_value
            )
        metric_favorable = favorable.copy()
        metric_adverse = adverse.copy()
        if not fill_at_open:
            if watch_fields.get("watch_entry_mode") == "STOP_CONTINUATION":
                # A STOP must cross the favorable side after entry, but the
                # opposite wick may have occurred before the trigger.  Only
                # adverse movement confirmed by the fill-bar close is causal.
                metric_adverse[0] = min(0.0, fill_close_progress)
            else:
                # For a LIMIT touch, the favorable wick may precede the fill.
                metric_favorable[0] = max(0.0, fill_close_progress)
        favorable_cumulative = np.maximum.accumulate(metric_favorable)
        adverse_cumulative = np.minimum.accumulate(metric_adverse)
        metric_favorable_cumulative = np.maximum.accumulate(metric_favorable)
        timed_configs = tuple(
            timed_half_lc_configs or (TimedHalfLcConfig(None),)
        )
        if not timed_configs:
            raise ValueError("at least one timed half-LC config is required")
        config_ids = [config.config_id for config in timed_configs]
        if len(set(config_ids)) != len(config_ids):
            raise ValueError("timed half-LC config ids must be unique")
        line_wick_configs = tuple(
            line_wick_lc_configs or (LineWickLcConfig(None),)
        )
        if not line_wick_configs:
            raise ValueError("at least one line-wick LC config is required")
        line_wick_ids = [config.config_id for config in line_wick_configs]
        if len(set(line_wick_ids)) != len(line_wick_ids):
            raise ValueError("line-wick LC config ids must be unique")
        overlay_configs = tuple(
            (timed_config, line_wick_config)
            for timed_config in timed_configs
            for line_wick_config in line_wick_configs
        )
        if any(
            timed_config.enabled and line_wick_config.enabled
            for timed_config, line_wick_config in overlay_configs
        ):
            raise ValueError(
                "timed half-LC and line-wick LC grids must be inspected "
                "independently"
            )
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
            original_tp_first_time = (
                pd.Timestamp(path_times[tp_index])
                if tp_index is not None
                else pd.NaT
            )
            original_lc_first_time = (
                pd.Timestamp(path_times[lc_index])
                if lc_index is not None
                else pd.NaT
            )
            profit_lock_enabled = bool(
                self.profit_lock_enabled
                and tp_pips + 1e-12 >= self.profit_lock_min_tp_pips
            )
            profit_lock_trigger_pips = (
                tp_pips * self.profit_lock_trigger_tp_fraction
                if profit_lock_enabled
                else np.nan
            )
            profit_lock_trigger_index: int | None = None
            profit_lock_index: int | None = None
            profit_lock_exit_pips = (
                tp_pips * self.profit_lock_result_tp_fraction
                if self.profit_lock_result_tp_fraction is not None
                else self.profit_lock_result_pips
            )
            profit_lock_exit_mode = "not_active"
            if profit_lock_enabled:
                trigger_reached = np.flatnonzero(
                    metric_favorable_cumulative >= profit_lock_trigger_pips
                )
                if trigger_reached.size:
                    profit_lock_trigger_index = int(trigger_reached[0])
                    # The raised stop becomes causal only after the trigger S5
                    # has completed.  Never infer intrabar ordering from its
                    # high and low.
                    first_active_index = profit_lock_trigger_index + 1
                    if first_active_index < len(adverse):
                        lock_open = np.flatnonzero(
                            open_progress[first_active_index:]
                            <= profit_lock_exit_pips
                        )
                        lock_touch = np.flatnonzero(
                            adverse[first_active_index:]
                            <= profit_lock_exit_pips
                        )
                        open_index = (
                            first_active_index + int(lock_open[0])
                            if lock_open.size
                            else None
                        )
                        touch_index = (
                            first_active_index + int(lock_touch[0])
                            if lock_touch.size
                            else None
                        )
                        lock_indices = [
                            value
                            for value in (open_index, touch_index)
                            if value is not None
                        ]
                        if lock_indices:
                            profit_lock_index = min(lock_indices)
                            if (
                                open_index is not None
                                and open_index == profit_lock_index
                            ):
                                profit_lock_exit_pips = float(
                                    open_progress[profit_lock_index]
                                )
                                profit_lock_exit_mode = (
                                    "activation_or_gap_open"
                                )
                            else:
                                profit_lock_exit_mode = "intrabar_touch"
            for timed_config, line_wick_config in overlay_configs:
                half_tp_trigger_pips = tp_pips * timed_config.tp_fraction
                half_tp_reached = np.flatnonzero(
                    metric_favorable_cumulative >= half_tp_trigger_pips
                )
                half_tp_index = (
                    int(half_tp_reached[0]) if half_tp_reached.size else None
                )
                half_tp_first_time = (
                    pd.Timestamp(path_times[half_tp_index])
                    if half_tp_index is not None
                    else pd.NaT
                )
                half_tp_known_from = (
                    half_tp_first_time + pd.Timedelta(seconds=S5_SECONDS)
                    if half_tp_index is not None
                    else pd.NaT
                )
                fill_bar_half_tp_ambiguous = bool(
                    not fill_at_open
                    and favorable[0] + 1e-12 >= half_tp_trigger_pips
                    and metric_favorable[0] + 1e-12 < half_tp_trigger_pips
                )

                timer_anchor = (
                    fill_time
                    if fill_at_open
                    else fill_time + pd.Timedelta(seconds=S5_SECONDS)
                )
                timed_check_time = pd.NaT
                timed_active_index: int | None = None
                timed_checkpoint_evaluable = False
                position_open_at_checkpoint = False
                half_tp_before_checkpoint = False
                timed_lc_activated = False
                timed_lc_suppressed_by_fill_ambiguity = False
                timed_lc_active_from = pd.NaT
                timed_activation_open_pips = np.nan
                timed_activation_already_breached = False
                max_favorable_before_checkpoint = np.nan
                max_adverse_before_checkpoint = np.nan
                timed_stop_index: int | None = None
                timed_stop_result_pips = np.nan
                timed_stop_exit_mode = "not_active"

                tick_pips = (
                    10.0 ** -int(self.pair.round_keta)
                ) / float(self.pair.pip_value)
                timed_requested_lc_pips = lc_pips * timed_config.lc_fraction
                timed_effective_lc_pips = max(
                    tick_pips,
                    math.floor(
                        timed_requested_lc_pips / tick_pips + 1e-12
                    )
                    * tick_pips,
                )
                timed_lc_price = float(
                    entry_price
                    + order_direction
                    * self.pair.pips_to_price(-timed_effective_lc_pips)
                )

                if timed_config.enabled:
                    timed_check_time = timer_anchor + pd.Timedelta(
                        minutes=int(timed_config.trigger_minutes)
                    )
                    timed_active_index = int(
                        np.searchsorted(
                            path_times,
                            np.datetime64(timed_check_time, "ns"),
                            side="left",
                        )
                    )
                    timed_checkpoint_evaluable = (
                        timed_active_index < len(path_times)
                    )
                    if timed_checkpoint_evaluable:
                        completed_slice = slice(0, timed_active_index)
                        if timed_active_index > 0:
                            max_favorable_before_checkpoint = float(
                                np.nanmax(metric_favorable[completed_slice])
                            )
                            max_adverse_before_checkpoint = float(
                                np.nanmin(metric_adverse[completed_slice])
                            )
                        half_tp_before_checkpoint = bool(
                            (
                                half_tp_index is not None
                                and half_tp_index < timed_active_index
                            )
                            or (
                                fill_bar_half_tp_ambiguous
                                and timed_active_index > 0
                            )
                        )
                        prior_tp = tp_index is not None and tp_index < timed_active_index
                        prior_lc = lc_index is not None and lc_index < timed_active_index
                        prior_profit_lock = (
                            profit_lock_index is not None
                            and profit_lock_index < timed_active_index
                        )
                        position_open_at_checkpoint = not (
                            prior_tp or prior_lc or prior_profit_lock
                        )
                        if position_open_at_checkpoint:
                            timed_activation_open_pips = float(
                                open_progress[timed_active_index]
                            )
                            timed_activation_already_breached = bool(
                                timed_activation_open_pips
                                <= -timed_effective_lc_pips + 1e-12
                            )
                        timed_lc_suppressed_by_fill_ambiguity = bool(
                            position_open_at_checkpoint
                            and timed_activation_already_breached
                            and fill_bar_half_tp_ambiguous
                            and timed_active_index > 0
                        )
                        timed_lc_activated = bool(
                            position_open_at_checkpoint
                            and timed_activation_already_breached
                            and not timed_lc_suppressed_by_fill_ambiguity
                        )
                        if timed_lc_activated:
                            timed_lc_active_from = pd.Timestamp(
                                path_times[timed_active_index]
                            )
                            # The checkpoint S5 open is the only decision input.
                            # Once it is already at/below the reduced LC width,
                            # close at that spread-aware open without inspecting
                            # any later high/low.
                            timed_stop_index = timed_active_index
                            timed_stop_result_pips = timed_activation_open_pips
                            timed_stop_exit_mode = "activation_or_gap_open"

                line_wick_requested_pips = (
                    average_range_pips * float(line_wick_config.width_a)
                    if line_wick_config.enabled
                    else np.nan
                )
                line_wick_effective_pips = (
                    max(
                        tick_pips,
                        math.ceil(
                            line_wick_requested_pips / tick_pips - 1e-12
                        )
                        * tick_pips,
                    )
                    if line_wick_config.enabled
                    else np.nan
                )
                line_wick_price = (
                    float(
                        line_price
                        + order_direction
                        * self.pair.pips_to_price(-line_wick_effective_pips)
                    )
                    if line_wick_config.enabled
                    else np.nan
                )
                line_wick_stop_index: int | None = None
                line_wick_stop_result_pips = np.nan
                line_wick_stop_exit_mode = "not_active"
                if line_wick_config.enabled:
                    line_wick_reached = np.flatnonzero(
                        adverse_cumulative <= -line_wick_effective_pips
                    )
                    if line_wick_reached.size:
                        line_wick_stop_index = int(line_wick_reached[0])
                        line_wick_stop_result_pips = -line_wick_effective_pips
                        line_wick_stop_exit_mode = "intrabar_wick_touch"
                        if (
                            line_wick_stop_index > 0 or fill_at_open
                        ) and open_progress[line_wick_stop_index] <= (
                            -line_wick_effective_pips + 1e-12
                        ):
                            line_wick_stop_result_pips = float(
                                open_progress[line_wick_stop_index]
                            )
                            line_wick_stop_exit_mode = "gap_open"

                original_lc_index = lc_index
                if (
                    original_lc_index is not None
                    and profit_lock_trigger_index is not None
                    and original_lc_index > profit_lock_trigger_index
                ):
                    # Once the trigger S5 closes, +1 pip replaces the original LC.
                    original_lc_index = None
                if (
                    timed_lc_activated
                    and original_lc_index is not None
                    and timed_active_index is not None
                    and original_lc_index >= timed_active_index
                ):
                    original_lc_index = None
                original_lc_result_pips = -lc_pips
                original_lc_exit_mode = "intrabar_touch"
                if (
                    original_lc_index is not None
                    and (original_lc_index > 0 or fill_at_open)
                    and open_progress[original_lc_index]
                    <= -lc_pips + 1e-12
                ):
                    original_lc_result_pips = float(
                        open_progress[original_lc_index]
                    )
                    original_lc_exit_mode = "gap_open"

                stop_candidates = []
                if original_lc_index is not None:
                    stop_candidates.append(
                        (
                            original_lc_index,
                            "lc",
                            original_lc_result_pips,
                            original_lc_exit_mode,
                        )
                    )
                if timed_stop_index is not None:
                    stop_candidates.append(
                        (
                            timed_stop_index,
                            "timed_half_lc",
                            timed_stop_result_pips,
                            timed_stop_exit_mode,
                        )
                    )
                if line_wick_stop_index is not None:
                    stop_candidates.append(
                        (
                            line_wick_stop_index,
                            "line_wick_lc",
                            line_wick_stop_result_pips,
                            line_wick_stop_exit_mode,
                        )
                    )
                if profit_lock_index is not None:
                    stop_candidates.append(
                        (
                            profit_lock_index,
                            "profit_lock",
                            profit_lock_exit_pips,
                            profit_lock_exit_mode,
                        )
                    )
                stop = (
                    min(stop_candidates, key=lambda value: value[0])
                    if stop_candidates
                    else None
                )
                if stop is not None and (
                    tp_index is None or int(stop[0]) <= tp_index
                ):
                    exit_index = int(stop[0])
                    stop_name = str(stop[1])
                    result_pips = float(stop[2])
                    exit_mode = str(stop[3])
                    if stop_name == "profit_lock":
                        result_name = "profit_lock"
                    elif stop_name == "timed_half_lc":
                        result_name = "timed_half_lc"
                    elif stop_name == "line_wick_lc":
                        result_name = "line_wick_lc"
                    else:
                        result_name = (
                            "both_same_s5_lc_assumed"
                            if tp_index is not None and tp_index == exit_index
                            else "lc"
                        )
                elif tp_index is not None:
                    exit_index = tp_index
                    result_name = "tp"
                    result_pips = tp_pips
                    exit_mode = "intrabar_touch"
                else:
                    exit_index = len(path_times) - 1
                    result_name = "timeout"
                    result_pips = timeout_pips
                    exit_mode = "horizon_close"
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
                profit_lock_activated = bool(
                    profit_lock_trigger_index is not None
                    and exit_index > profit_lock_trigger_index
                )
                profit_lock_active_from = (
                    pd.Timestamp(path_times[profit_lock_trigger_index])
                    + pd.Timedelta(seconds=S5_SECONDS)
                    if profit_lock_activated
                    else pd.NaT
                )
                timed_lc_exit = result_name == "timed_half_lc"
                timed_lc_exit_at_open = bool(
                    timed_lc_exit
                    and timed_stop_exit_mode == "activation_or_gap_open"
                )
                line_wick_lc_exit = result_name == "line_wick_lc"
                line_wick_lc_exit_at_open = bool(
                    line_wick_lc_exit
                    and line_wick_stop_exit_mode == "gap_open"
                )
                line_wick_lc_reached_while_open = bool(
                    line_wick_stop_index is not None
                    and (
                        line_wick_stop_index < exit_index
                        or (
                            line_wick_stop_index == exit_index
                            and line_wick_lc_exit
                        )
                    )
                )
                exit_at_bar_open = exit_mode in (
                    "activation_or_gap_open",
                    "gap_open",
                )
                exit_time = pd.Timestamp(path_times[exit_index])
                half_tp_reached_while_open = bool(
                    half_tp_index is not None
                    and (
                        half_tp_index < exit_index
                        or (
                            half_tp_index == exit_index
                            and result_name in ("tp", "timeout")
                        )
                    )
                )
                half_tp_after_activation_while_open = bool(
                    timed_lc_activated
                    and half_tp_reached_while_open
                    and half_tp_index is not None
                    and timed_active_index is not None
                    and half_tp_index >= timed_active_index
                )
                counterfactual_half_tp_after_activation = bool(
                    timed_lc_activated
                    and half_tp_index is not None
                    and timed_active_index is not None
                    and half_tp_index >= timed_active_index
                )
                original_tp_reached_while_open = bool(
                    tp_index is not None
                    and (
                        tp_index < exit_index
                        or (tp_index == exit_index and result_name == "tp")
                    )
                )
                original_lc_reached_while_open = bool(
                    lc_index is not None
                    and (
                        lc_index < exit_index
                        or (
                            lc_index == exit_index
                            and result_name
                            in ("lc", "both_same_s5_lc_assumed")
                        )
                    )
                )
                profit_lock_trigger_reached_while_open = bool(
                    profit_lock_trigger_index is not None
                    and (
                        profit_lock_trigger_index < exit_index
                        or (
                            profit_lock_trigger_index == exit_index
                            and result_name in ("tp", "timeout")
                        )
                    )
                )
                exit_effective_time = (
                    exit_time
                    if exit_at_bar_open
                    else exit_time + pd.Timedelta(seconds=S5_SECONDS)
                )
                exit_s5_opposite_extreme_censored = result_name != "timeout"
                if exit_s5_opposite_extreme_censored:
                    # The opposite wick of an intrabar TP/LC S5 may occur
                    # after the position has already exited.  Keep completed
                    # prior S5s, the known exit-S5 open, and the exit point.
                    entry_mark_pips = -self.spread_pips
                    exit_open_pips = (
                        float(open_progress[exit_index])
                        if exit_index > 0 or fill_at_open
                        else entry_mark_pips
                    )
                    known_boundary_points = np.asarray(
                        (entry_mark_pips, exit_open_pips, float(result_pips)),
                        dtype=float,
                    )
                    final_favorable_points = np.concatenate(
                        (
                            metric_favorable[:exit_index],
                            known_boundary_points,
                        )
                    )
                    final_adverse_points = np.concatenate(
                        (
                            metric_adverse[:exit_index],
                            known_boundary_points,
                        )
                    )
                else:
                    final_favorable_points = metric_favorable[: exit_index + 1]
                    final_adverse_points = metric_adverse[: exit_index + 1]
                final_max_favorable_pips = float(
                    np.nanmax(final_favorable_points)
                )
                final_max_adverse_pips = float(
                    np.nanmin(final_adverse_points)
                )
                early_path_fields: dict[str, Any] = {}
                if (
                    watch_fields.get("watch_order_name")
                    == "FlipPredict_LineHolding"
                ):
                    early_path_fields = self._early_path_fields(
                        path_times=path_times,
                        timer_anchor=timer_anchor,
                        exit_effective_time=exit_effective_time,
                        entry_price=entry_price,
                        line_price=line_price,
                        order_direction=order_direction,
                        average_range_pips=average_range_pips,
                        close_progress=close_progress,
                        open_progress=open_progress,
                        metric_favorable=metric_favorable,
                        metric_adverse=metric_adverse,
                        path_opens=self.opens[fill_i:end_i],
                        path_closes=close,
                    )
                outcome_key = overlay_outcome_key(
                    combo, timed_config, line_wick_config
                )
                outcomes[outcome_key] = {
                    "combo_id": combo.combo_id,
                    "tp_a": combo.tp_a,
                    "lc_a": combo.lc_a,
                    "configured_rr": combo.configured_rr,
                    "effective_rr": tp_pips / lc_pips,
                    "tp_pips": tp_pips,
                    "lc_pips": lc_pips,
                    "original_tp_first_reached_time": (
                        original_tp_first_time
                        if original_tp_reached_while_open
                        else pd.NaT
                    ),
                    "original_tp_known_from": (
                        original_tp_first_time + pd.Timedelta(seconds=S5_SECONDS)
                        if original_tp_reached_while_open
                        else pd.NaT
                    ),
                    "minutes_to_original_tp": (
                        float(
                            (
                                original_tp_first_time
                                + pd.Timedelta(seconds=S5_SECONDS)
                                - timer_anchor
                            ).total_seconds()
                            / 60
                        )
                        if original_tp_reached_while_open
                        else np.nan
                    ),
                    "original_lc_first_reached_time": (
                        original_lc_first_time
                        if original_lc_reached_while_open
                        else pd.NaT
                    ),
                    "original_lc_known_from": (
                        original_lc_first_time + pd.Timedelta(seconds=S5_SECONDS)
                        if original_lc_reached_while_open
                        else pd.NaT
                    ),
                    "minutes_to_original_lc": (
                        float(
                            (
                                original_lc_first_time
                                + pd.Timedelta(seconds=S5_SECONDS)
                                - timer_anchor
                            ).total_seconds()
                            / 60
                        )
                        if original_lc_reached_while_open
                        else np.nan
                    ),
                    "counterfactual_horizon_original_tp_reached": (
                        tp_index is not None
                    ),
                    "counterfactual_horizon_original_tp_first_reached_time": (
                        original_tp_first_time
                    ),
                    "counterfactual_horizon_minutes_to_original_tp": (
                        float(
                            (
                                original_tp_first_time
                                + pd.Timedelta(seconds=S5_SECONDS)
                                - timer_anchor
                            ).total_seconds()
                            / 60
                        )
                        if tp_index is not None
                        else np.nan
                    ),
                    "counterfactual_horizon_original_lc_reached": (
                        lc_index is not None
                    ),
                    "counterfactual_horizon_original_lc_first_reached_time": (
                        original_lc_first_time
                    ),
                    "counterfactual_horizon_minutes_to_original_lc": (
                        float(
                            (
                                original_lc_first_time
                                + pd.Timedelta(seconds=S5_SECONDS)
                                - timer_anchor
                            ).total_seconds()
                            / 60
                        )
                        if lc_index is not None
                        else np.nan
                    ),
                    "half_tp_trigger_fraction": timed_config.tp_fraction,
                    "half_tp_trigger_pips": half_tp_trigger_pips,
                    "half_tp_reached": half_tp_reached_while_open,
                    "half_tp_first_reached_time": (
                        half_tp_first_time
                        if half_tp_reached_while_open
                        else pd.NaT
                    ),
                    "half_tp_known_from": (
                        half_tp_known_from
                        if half_tp_reached_while_open
                        else pd.NaT
                    ),
                    "minutes_to_half_tp": (
                        float((half_tp_known_from - timer_anchor).total_seconds() / 60)
                        if half_tp_reached_while_open
                        else np.nan
                    ),
                    "counterfactual_horizon_half_tp_reached": (
                        half_tp_index is not None
                    ),
                    "counterfactual_horizon_half_tp_first_reached_time": (
                        half_tp_first_time
                    ),
                    "counterfactual_horizon_minutes_to_half_tp": (
                        float(
                            (half_tp_known_from - timer_anchor).total_seconds()
                            / 60
                        )
                        if half_tp_index is not None
                        else np.nan
                    ),
                    "fill_bar_half_tp_ambiguous": fill_bar_half_tp_ambiguous,
                    "profit_lock_enabled": profit_lock_enabled,
                    "profit_lock_min_tp_pips": self.profit_lock_min_tp_pips,
                    "profit_lock_trigger_tp_fraction": (
                        self.profit_lock_trigger_tp_fraction
                    ),
                    "profit_lock_trigger_pips": profit_lock_trigger_pips,
                    "profit_lock_result_pips": self.profit_lock_result_pips,
                    "profit_lock_result_tp_fraction": (
                        self.profit_lock_result_tp_fraction
                    ),
                    "profit_lock_effective_result_pips": (
                        profit_lock_exit_pips if profit_lock_enabled else np.nan
                    ),
                    "profit_lock_trigger_reached": (
                        profit_lock_trigger_reached_while_open
                    ),
                    "counterfactual_horizon_profit_lock_trigger_reached": (
                        profit_lock_trigger_index is not None
                    ),
                    "profit_lock_activated": profit_lock_activated,
                    "profit_lock_active_from": profit_lock_active_from,
                    "profit_lock_exit_at_bar_open": bool(
                        result_name == "profit_lock" and exit_at_bar_open
                    ),
                    "profit_lock_slippage_pips": (
                        float(result_pips - profit_lock_exit_pips)
                        if result_name == "profit_lock" and exit_at_bar_open
                        else 0.0 if result_name == "profit_lock" else np.nan
                    ),
                    "original_lc_exit_at_bar_open": bool(
                        result_name in ("lc", "both_same_s5_lc_assumed")
                        and exit_at_bar_open
                    ),
                    "original_lc_slippage_pips": (
                        float(result_pips + lc_pips)
                        if result_name in ("lc", "both_same_s5_lc_assumed")
                        and exit_at_bar_open
                        else (
                            0.0
                            if result_name
                            in ("lc", "both_same_s5_lc_assumed")
                            else np.nan
                        )
                    ),
                    "timed_half_lc_config_id": timed_config.config_id,
                    "timed_half_lc_enabled": timed_config.enabled,
                    "timed_half_lc_trigger_minutes": timed_config.trigger_minutes,
                    "timed_half_lc_fraction": timed_config.lc_fraction,
                    "timed_half_lc_timer_anchor": timer_anchor,
                    "timed_half_lc_check_time": timed_check_time,
                    "timed_half_lc_checkpoint_evaluable": (
                        timed_checkpoint_evaluable
                    ),
                    "timed_half_lc_position_open_at_checkpoint": (
                        position_open_at_checkpoint
                    ),
                    "half_tp_reached_before_timed_checkpoint": (
                        half_tp_before_checkpoint
                    ),
                    "max_favorable_before_timed_checkpoint_pips": (
                        max_favorable_before_checkpoint
                    ),
                    "max_adverse_before_timed_checkpoint_pips": (
                        max_adverse_before_checkpoint
                    ),
                    "timed_half_lc_activated": timed_lc_activated,
                    "timed_half_lc_suppressed_by_fill_bar_ambiguity": (
                        timed_lc_suppressed_by_fill_ambiguity
                    ),
                    "timed_half_lc_active_from": timed_lc_active_from,
                    "timed_half_lc_requested_pips": timed_requested_lc_pips,
                    "timed_half_lc_effective_pips": timed_effective_lc_pips,
                    "timed_half_lc_price": timed_lc_price,
                    "timed_half_lc_activation_open_pips": (
                        timed_activation_open_pips
                    ),
                    "timed_half_lc_activation_already_breached": (
                        timed_activation_already_breached
                    ),
                    "half_tp_reached_after_timed_activation": (
                        half_tp_after_activation_while_open
                    ),
                    "counterfactual_half_tp_reached_after_timed_activation": (
                        counterfactual_half_tp_after_activation
                    ),
                    "timed_half_lc_exit": timed_lc_exit,
                    "timed_half_lc_exit_mode": timed_stop_exit_mode,
                    "timed_half_lc_exit_at_bar_open": timed_lc_exit_at_open,
                    "timed_half_lc_exit_time": (
                        exit_time if timed_lc_exit else pd.NaT
                    ),
                    "timed_half_lc_slippage_pips": (
                        float(result_pips + timed_effective_lc_pips)
                        if timed_lc_exit_at_open
                        else 0.0 if timed_lc_exit else np.nan
                    ),
                    "line_wick_lc_config_id": line_wick_config.config_id,
                    "line_wick_lc_enabled": line_wick_config.enabled,
                    "line_wick_lc_width_a": line_wick_config.width_a,
                    "line_wick_lc_requested_pips": (
                        line_wick_requested_pips
                    ),
                    "line_wick_lc_effective_pips": (
                        line_wick_effective_pips
                    ),
                    "line_wick_lc_price": line_wick_price,
                    "line_wick_lc_reached": line_wick_lc_reached_while_open,
                    "counterfactual_horizon_line_wick_lc_reached": (
                        line_wick_stop_index is not None
                    ),
                    "line_wick_lc_exit": line_wick_lc_exit,
                    "line_wick_lc_exit_mode": line_wick_stop_exit_mode,
                    "line_wick_lc_exit_at_bar_open": (
                        line_wick_lc_exit_at_open
                    ),
                    "line_wick_lc_exit_time": (
                        exit_time if line_wick_lc_exit else pd.NaT
                    ),
                    "line_wick_lc_same_s5_tp_assumed_first": bool(
                        line_wick_lc_exit
                        and tp_index is not None
                        and tp_index == exit_index
                    ),
                    "line_wick_lc_slippage_pips": (
                        float(result_pips + line_wick_effective_pips)
                        if line_wick_lc_exit_at_open
                        else 0.0 if line_wick_lc_exit else np.nan
                    ),
                    "trade_result": result_name,
                    "trade_result_pips": float(result_pips),
                    "result_r": result_r,
                    "result_yen": result_yen(
                        self.pair, result_pips, lc_pips, self.risk_yen
                    ),
                    "exit_time": exit_time,
                    "exit_effective_time": exit_effective_time,
                    "minutes_from_fill_to_exit": float(
                        (exit_effective_time - timer_anchor).total_seconds() / 60
                    ),
                    "minutes_from_timed_activation_to_exit": (
                        float(
                            (exit_effective_time - timed_lc_active_from).total_seconds()
                            / 60
                        )
                        if timed_lc_activated
                        else np.nan
                    ),
                    "actual_entry_price": entry_price,
                    "actual_exit_price": float(
                        entry_price
                        + order_direction * self.pair.pips_to_price(result_pips)
                    ),
                    "max_favorable_pips": final_max_favorable_pips,
                    "max_adverse_pips": final_max_adverse_pips,
                    "exit_s5_opposite_extreme_censored": (
                        exit_s5_opposite_extreme_censored
                    ),
                    "exit_execution_mode": exit_mode,
                    **early_path_fields,
                }
        completed = bool(outcomes)
        return {
            **filled,
            "path_status": "trade" if completed else "incomplete_position_window",
            "position_path_complete": completed,
            "position_horizon_end": horizon_end,
            "outcomes": outcomes,
        }


def add_feature_buckets(
    frame: pd.DataFrame,
    pair: str | None = None,
) -> pd.DataFrame:
    """Create the finite, causal feature catalog used by exhaustive search.

    ``pair`` selects that pair's bucket-edge overrides from
    ``PAIR_BUCKET_OVERRIDES``; ``None`` (or an unlisted pair) uses
    ``DEFAULT_BUCKET_SPECS`` unchanged.  Edges are configuration, not
    behaviour: changing them changes only how continuous inputs are grouped
    for the exhaustive condition search, never how a trade is executed.
    """
    result = frame.copy()
    specs = bucket_specs_for_pair(pair)

    def numeric(name: str) -> pd.Series:
        return pd.to_numeric(result.get(name), errors="coerce")

    def cut(name: str, bins: list[float], labels: list[str]) -> pd.Series:
        return pd.cut(
            numeric(name), bins=bins, labels=labels, include_lowest=True
        ).astype("string").fillna("missing")

    def spec_cut(feature: str) -> pd.Series:
        """Bucket a column using the (possibly pair-overridden) spec."""
        spec = specs[feature]
        return cut(spec.source_column, list(spec.edges), list(spec.labels))

    distance_rank = numeric("distance_rank")
    result["f_distance_rank"] = np.select(
        [distance_rank.eq(1), distance_rank.eq(2), distance_rank.eq(3)],
        ["1", "2", "3"],
        default="4plus",
    )
    average = numeric("recent_m5_avg_range_pips").replace(0, np.nan)
    result["distance_a"] = numeric("distance_pips") / average
    result["f_distance_a"] = spec_cut("f_distance_a")
    result["f_peaks_count"] = spec_cut("f_peaks_count")
    result["f_core_peak"] = spec_cut("f_core_peak")
    # Strength bucket edges come from the observed candidate distribution,
    # not from round numbers.  The earlier edges (le1/1to2/2to3/gt3 and
    # le3/4to6/7to10/gt10) collapsed most candidates into a single bucket --
    # "gt3" held ~76% of AUD_USD candidates and "le3" held literally none --
    # so line strength could not discriminate between events at all.
    result["f_line_average_strength"] = spec_cut("f_line_average_strength")
    result["f_line_total_strength"] = spec_cut("f_line_total_strength")
    # Combined strength of only the core (repeat-touch) peaks, as opposed to
    # every constituent peak.  Previously carried through the pipeline but
    # never exposed as a searchable feature.
    result["f_line_core_total_strength"] = spec_cut(
        "f_line_core_total_strength"
    )
    # Derived ratios computed by load_candidates.  Guarded like
    # f_minutes_since_flip so callers that predate them still work.
    for feature in ("f_line_core_strength_ratio", "f_line_relative_strength"):
        if specs[feature].source_column in result.columns:
            result[feature] = spec_cut(feature)
        else:
            result[feature] = "missing"
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
    result["f_line_age"] = spec_cut("f_line_age")
    # Recency of the line's most recent resistance/support role flip.
    # "missing" means line_flip_count == 0 (never flipped) -- a distinct,
    # meaningful bucket, not the same as a flip that happened long ago.
    # Guarded (rather than assumed-present like the other source columns)
    # because other callers of add_feature_buckets (e.g. the live EUR/USD
    # service) predate this feature and may not populate the column.
    if "minutes_since_line_flip" in result.columns:
        result["f_minutes_since_flip"] = spec_cut("f_minutes_since_flip")
    else:
        result["f_minutes_since_flip"] = "missing"
    result["f_prior_retouch"] = spec_cut("f_prior_retouch")
    result["f_peak_strength"] = spec_cut("f_peak_strength")
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
    "f_line_core_total_strength",
    "f_line_core_strength_ratio",
    "f_line_relative_strength",
    "f_flip_flag",
    "f_prior_flip_count",
    "f_history_flipped",
    "f_line_age",
    "f_minutes_since_flip",
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
    ("f_core_peak", "f_line_core_total_strength"),
    ("f_line_core_total_strength", "f_line_total_strength"),
    ("f_line_core_total_strength", "f_distance_a"),
    ("f_line_core_total_strength", "f_history_flipped"),
    ("f_line_core_strength_ratio", "f_core_peak"),
    ("f_line_core_strength_ratio", "f_distance_a"),
    ("f_line_core_strength_ratio", "f_history_flipped"),
    ("f_line_relative_strength", "f_distance_rank"),
    ("f_line_relative_strength", "f_distance_a"),
    ("f_line_relative_strength", "f_core_peak"),
    ("f_line_relative_strength", "f_line_core_strength_ratio"),
    ("f_line_relative_strength", "f_history_flipped"),
    ("f_line_relative_strength", "f_minutes_since_flip"),
    ("f_line_average_strength", "f_distance_a"),
    ("f_line_average_strength", "f_history_flipped"),
    ("f_line_total_strength", "f_distance_a"),
    ("f_minutes_since_flip", "f_line_core_total_strength"),
    ("f_prior_flip_count", "f_prior_retouch"),
    ("f_line_age", "f_prior_retouch"),
    ("f_minutes_since_flip", "f_core_peak"),
    ("f_minutes_since_flip", "f_distance_a"),
    ("f_minutes_since_flip", "f_oriented_rsi"),
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
