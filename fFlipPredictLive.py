# 最新更新日時: 2026-08-26 06:27 JST
"""EUR/USD ``flip_predict_v19`` LineHolding live execution service.

This module is intentionally independent from ``main_exe``.  It never resets
the account, never cancels pending orders, and only mutates a trade whose pair,
trade id, and owner tag all match this service.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

import classOanda
from count2_flip_core import (
    FlipWatchEntryConfig,
    RankedPolicyCondition,
    TierExecutionConfig,
    _is_expected_market_closed_gap,
    add_feature_buckets,
    classify_flip_watch_entry,
    effective_trade_widths,
    validate_causal_candidate,
)
from count2_flip_workflow import (
    select_top_condition_policy_candidates,
    target_distance_filter_mask,
)
from count2_resistance_sweep import (
    _line_columns,
    _peak_columns,
    line_touch_features,
    prepare_m5,
    rebuild_candidates_at,
    stair_analysis_columns,
    target_parameters,
)
import fGeneric as gene
from fFootCountShape import (
    attach_line_wick_context,
    flatten_foot_count2_shape,
    foot_count2_shape_context,
)
import send_notice as notice
import tokens as tk


PAIR_NAME = "EUR_USD"
USD_JPY_NAME = "USD_JPY"
OWNER_TAG = "flip_predict_eur"
POLICY_VERSION = "flip_predict_v19"
SOURCE_ARTIFACT_SHA256 = (
    "CBBC7C97FA11C41E1FDDBE6F61574EF7ACB315DADECC41363CB197141CEB48A8"
)
STATE_SCHEMA_VERSION = 1
TIME_FORMAT = "%Y/%m/%d %H:%M:%S"
UTC = dt.timezone.utc
JST = ZoneInfo("Asia/Tokyo")

ORDER_WAIT_MINUTES = 60
POSITION_HORIZON_MINUTES = 60
FIXED_TOUCH_SPREAD_PIPS = 0.8
MIN_TARGET_DISTANCE_PIPS = 2.0
MIN_WIDTH_PIPS = 1.6
RISK_YEN = 50.0
MAX_UNITS = 5000
MAX_MARKET_SLIPPAGE_PIPS = 0.5
QUOTE_MAX_AGE_SECONDS = 15.0
READY_MAX_AGE_SECONDS = 10.0
BROKER_POLL_SECONDS = 10.0
S5_POLL_SECONDS = 4.0
LOOP_SLEEP_SECONDS = 1.0
RETOUCH_TOLERANCE_PIPS = 1.0
LIFECYCLE_ERROR_REASONS = frozenset(
    {
        "market_order_rejected",
        "unknown_s5_gap_before_touch",
        "unknown_s5_gap_during_observation",
    }
)

RUNTIME_DIR = Path(__file__).resolve().parent / "runtime_state"
STATE_PATH = RUNTIME_DIR / "flip_predict_eur_usd_v19.json"
LOCK_PATH = RUNTIME_DIR / "flip_predict_eur_usd_v19.lock"


SELECTED_TOP_CONDITIONS = (
    {
        "rank": 1,
        "tier": "HIGH",
        "condition": {
            "condition_id": "f_fc2_shape=REJECTION&f_oriented_rsi=against",
            "label": "f_fc2_shape=REJECTION&f_oriented_rsi=against",
            "clauses": [
                {"field": "f_fc2_shape", "value": "REJECTION"},
                {"field": "f_oriented_rsi", "value": "against"},
            ],
        },
    },
    {
        "rank": 2,
        "tier": "HIGH",
        "condition": {
            "condition_id": "f_session=new_york&f_fc2_shape=REJECTION",
            "label": "f_session=new_york&f_fc2_shape=REJECTION",
            "clauses": [
                {"field": "f_session", "value": "new_york"},
                {"field": "f_fc2_shape", "value": "REJECTION"},
            ],
        },
    },
    {
        "rank": 3,
        "tier": "HIGH",
        "condition": {
            "condition_id": "f_h1_shape=CONTINUATION&f_oriented_rsi=against",
            "label": "f_h1_shape=CONTINUATION&f_oriented_rsi=against",
            "clauses": [
                {"field": "f_h1_shape", "value": "CONTINUATION"},
                {"field": "f_oriented_rsi", "value": "against"},
            ],
        },
    },
    {
        "rank": 4,
        "tier": "HIGH",
        "condition": {
            "condition_id": "f_h1_shape=ENGULFING",
            "label": "f_h1_shape=ENGULFING",
            "clauses": [{"field": "f_h1_shape", "value": "ENGULFING"}],
        },
    },
    {
        "rank": 5,
        "tier": "HIGH",
        "condition": {
            "condition_id": "f_direction=up",
            "label": "f_direction=up",
            "clauses": [{"field": "f_direction", "value": "up"}],
        },
    },
    {
        "rank": 6,
        "tier": "MIDDLE",
        "condition": {
            "condition_id": "f_h1_stair_relation=opposed&f_h1_shape=ENGULFING",
            "label": "f_h1_stair_relation=opposed&f_h1_shape=ENGULFING",
            "clauses": [
                {"field": "f_h1_stair_relation", "value": "opposed"},
                {"field": "f_h1_shape", "value": "ENGULFING"},
            ],
        },
    },
    {
        "rank": 7,
        "tier": "MIDDLE",
        "condition": {
            "condition_id": "f_session=new_york",
            "label": "f_session=new_york",
            "clauses": [{"field": "f_session", "value": "new_york"}],
        },
    },
    {
        "rank": 8,
        "tier": "MIDDLE",
        "condition": {
            "condition_id": "f_prior_flip_count=1&f_prior_retouch=3plus",
            "label": "f_prior_flip_count=1&f_prior_retouch=3plus",
            "clauses": [
                {"field": "f_prior_flip_count", "value": "1"},
                {"field": "f_prior_retouch", "value": "3plus"},
            ],
        },
    },
    {
        "rank": 9,
        "tier": "MIDDLE",
        "condition": {
            "condition_id": (
                "f_fc2_relative_candle_sequence=AGAINST_WITH&"
                "f_fc2_second_wick_a=0p50to0p74"
            ),
            "label": (
                "f_fc2_relative_candle_sequence=AGAINST_WITH&"
                "f_fc2_second_wick_a=0p50to0p74"
            ),
            "clauses": [
                {
                    "field": "f_fc2_relative_candle_sequence",
                    "value": "AGAINST_WITH",
                },
                {"field": "f_fc2_second_wick_a", "value": "0p50to0p74"},
            ],
        },
    },
    {
        "rank": 10,
        "tier": "MIDDLE",
        "condition": {
            "condition_id": (
                "f_fc2_second_wick_a=0p50to0p74&"
                "f_fc2_second_pushback_a=0p50to0p74"
            ),
            "label": (
                "f_fc2_second_wick_a=0p50to0p74&"
                "f_fc2_second_pushback_a=0p50to0p74"
            ),
            "clauses": [
                {"field": "f_fc2_second_wick_a", "value": "0p50to0p74"},
                {
                    "field": "f_fc2_second_pushback_a",
                    "value": "0p50to0p74",
                },
            ],
        },
    },
    {
        "rank": 11,
        "tier": "LOW",
        "condition": {
            "condition_id": "f_distance_rank=4plus&f_core_peak=1",
            "label": "f_distance_rank=4plus&f_core_peak=1",
            "clauses": [
                {"field": "f_distance_rank", "value": "4plus"},
                {"field": "f_core_peak", "value": "1"},
            ],
        },
    },
    {
        "rank": 12,
        "tier": "LOW",
        "condition": {
            "condition_id": "f_direction=up&f_fc2_shape=REJECTION",
            "label": "f_direction=up&f_fc2_shape=REJECTION",
            "clauses": [
                {"field": "f_direction", "value": "up"},
                {"field": "f_fc2_shape", "value": "REJECTION"},
            ],
        },
    },
    {
        "rank": 13,
        "tier": "LOW",
        "condition": {
            "condition_id": "f_h1_stair_relation=aligned",
            "label": "f_h1_stair_relation=aligned",
            "clauses": [
                {"field": "f_h1_stair_relation", "value": "aligned"}
            ],
        },
    },
    {
        "rank": 14,
        "tier": "LOW",
        "condition": {
            "condition_id": (
                "f_m5_stair_relation=aligned&f_h1_stair_relation=aligned"
            ),
            "label": (
                "f_m5_stair_relation=aligned&f_h1_stair_relation=aligned"
            ),
            "clauses": [
                {"field": "f_m5_stair_relation", "value": "aligned"},
                {"field": "f_h1_stair_relation", "value": "aligned"},
            ],
        },
    },
    {
        "rank": 15,
        "tier": "LOW",
        "condition": {
            "condition_id": "f_line_age=1to4h&f_prior_retouch=3plus",
            "label": "f_line_age=1to4h&f_prior_retouch=3plus",
            "clauses": [
                {"field": "f_line_age", "value": "1to4h"},
                {"field": "f_prior_retouch", "value": "3plus"},
            ],
        },
    },
)

TIER_EXECUTION_SPECS = (
    {
        "tier": "HIGH",
        "first_rank": 1,
        "last_rank": 5,
        "tp_a": 2.0,
        "rr": 2.0 / 1.7,
        "min_range_filter_pips": 1.5,
    },
    {
        "tier": "MIDDLE",
        "first_rank": 6,
        "last_rank": 10,
        "tp_a": 2.0,
        "rr": 2.0 / 1.25,
        "min_range_filter_pips": 1.5,
    },
    {
        "tier": "LOW",
        "first_rank": 11,
        "last_rank": 15,
        "tp_a": 1.2,
        "rr": 1.2,
        "min_range_filter_pips": 1.5,
    },
)

WATCH_SPEC = {
    "observation_seconds": 60,
    "line_holding_max_breakout_a": 0.1,
    "line_holding_max_chase_a": 0.3,
    "near_line_max_breakout_a": 1.0,
    "breakout_continuation_a": 0.05,
    "max_entry_gap_a": 0.1,
}

POLICY_SNAPSHOT = {
    "version": POLICY_VERSION,
    "pair": PAIR_NAME,
    "source_artifact_sha256": SOURCE_ARTIFACT_SHA256,
    "top_conditions": SELECTED_TOP_CONDITIONS,
    "tier_execution": TIER_EXECUTION_SPECS,
    "watch": WATCH_SPEC,
    "line_holding_only": True,
    "order_wait_minutes": ORDER_WAIT_MINUTES,
    "replace_on_next_fc2": False,
    "position_horizon_minutes": POSITION_HORIZON_MINUTES,
    "fixed_touch_spread_pips": FIXED_TOUCH_SPREAD_PIPS,
    "minimum_target_distance_pips": MIN_TARGET_DISTANCE_PIPS,
    "minimum_width_pips": MIN_WIDTH_PIPS,
    "risk_yen": RISK_YEN,
    "profit_lock": False,
    "timed_half_lc": False,
    "line_wick_lc": False,
}
POLICY_FINGERPRINT = hashlib.sha256(
    json.dumps(
        POLICY_SNAPSHOT,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
).hexdigest()

RANKED_CONDITIONS = tuple(
    RankedPolicyCondition.from_dict(item) for item in SELECTED_TOP_CONDITIONS
)
TIER_CONFIGS = tuple(
    TierExecutionConfig.from_dict(item) for item in TIER_EXECUTION_SPECS
)
TIER_BY_NAME = {item.tier: item for item in TIER_CONFIGS}
WATCH_CONFIG = FlipWatchEntryConfig.from_dict(WATCH_SPEC)


class LiveDataError(RuntimeError):
    """A fail-closed market-data or broker-state error."""


class SpreadTooWideError(LiveDataError):
    """An expected execution constraint, not an analysis-data failure."""


def _utc_now() -> dt.datetime:
    return dt.datetime.now(tz=UTC)


def _parse_utc(value: Any) -> dt.datetime:
    if value is None or value is pd.NaT or value is pd.NA:
        raise LiveDataError("required UTC timestamp is missing")
    parsed = pd.Timestamp(value)
    if pd.isna(parsed):
        raise LiveDataError("required UTC timestamp is invalid")
    if parsed.tzinfo is None:
        parsed = parsed.tz_localize("UTC")
    else:
        parsed = parsed.tz_convert("UTC")
    return parsed.to_pydatetime()


def _utc_iso(value: dt.datetime) -> str:
    aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return aware.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _jst_naive_to_utc(value: pd.Timestamp) -> dt.datetime:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("Asia/Tokyo")
    else:
        timestamp = timestamp.tz_convert("Asia/Tokyo")
    return timestamp.tz_convert("UTC").to_pydatetime()


def _json_safe(value: Any) -> Any:
    if value is None or value is pd.NaT or value is pd.NA:
        return None
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (dt.datetime, pd.Timestamp)):
        timestamp = pd.Timestamp(value)
        if timestamp.tzinfo is not None:
            return timestamp.isoformat()
        return timestamp.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not math.isfinite(float(value)) else float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if value is pd.NA or (isinstance(value, float) and math.isnan(value)):
        return None
    return value


class SingleInstanceLock:
    """Cross-platform non-blocking OS lock; the lock file alone is not trusted."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle: Any | None = None
        self._windows = os.name == "nt"

    def __enter__(self) -> "SingleInstanceLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+b")
        self.handle.seek(0, os.SEEK_END)
        if self.handle.tell() == 0:
            self.handle.write(b"0")
            self.handle.flush()
        self.handle.seek(0)
        try:
            if self._windows:
                import msvcrt

                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError) as error:
            self.handle.close()
            self.handle = None
            raise RuntimeError("EUR/USD live service is already running") from error
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if self.handle is None:
            return
        try:
            self.handle.seek(0)
            if self._windows:
                import msvcrt

                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        finally:
            self.handle.close()
            self.handle = None


class StateStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def archive_orphan_temps(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Only this service's atomic-write temp is in scope.  Never move a
        # temp file that may belong to another strategy.
        orphaned = [self.path.with_suffix(self.path.suffix + ".tmp")]
        orphaned = [path for path in orphaned if path.exists()]
        if not orphaned:
            return
        archive = self.path.parent / "archive"
        archive.mkdir(parents=True, exist_ok=True)
        stamp = _utc_now().strftime("%Y%m%dT%H%M%S%fZ")
        for index, source in enumerate(orphaned):
            destination = archive / f"{source.stem}_{stamp}_{index}.tmp"
            shutil.move(str(source), str(destination))

    def default(self) -> dict[str, Any]:
        return {
            "schema_version": STATE_SCHEMA_VERSION,
            "policy_fingerprint": POLICY_FINGERPRINT,
            "pair": PAIR_NAME,
            "active": None,
            "recent_signal_ids": [],
            "last_decision_time_utc": None,
            "last_completion": None,
            "updated_at_utc": _utc_iso(_utc_now()),
        }

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return self.default()
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise RuntimeError(f"state file is unreadable: {self.path}") from error
        if not isinstance(value, dict):
            raise RuntimeError("state root must be a JSON object")
        if value.get("schema_version") != STATE_SCHEMA_VERSION:
            raise RuntimeError("state schema version mismatch")
        if value.get("policy_fingerprint") != POLICY_FINGERPRINT:
            raise RuntimeError("state policy fingerprint mismatch")
        if value.get("pair") != PAIR_NAME:
            raise RuntimeError("state pair mismatch")
        active = value.get("active")
        if active is not None and not isinstance(active, dict):
            raise RuntimeError("state active lifecycle is invalid")
        return value

    def save(self, value: dict[str, Any]) -> None:
        value["updated_at_utc"] = _utc_iso(_utc_now())
        payload = json.dumps(
            _json_safe(value),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self.path)


class LiveNotifier:
    def __init__(self) -> None:
        self.last_sent: dict[str, float] = {}

    def send(
        self,
        title: str,
        *items: str,
        throttle_key: str | None = None,
        throttle_seconds: float = 0.0,
    ) -> None:
        key = throttle_key or title
        now = time.monotonic()
        if throttle_seconds and now - self.last_sent.get(key, -math.inf) < throttle_seconds:
            return
        self.last_sent[key] = now
        lines = [f"EUR_USD flip_predict live | {title}"]
        lines.extend(f"- {item}" for item in items)
        message = "\n".join(lines)
        print(message)
        notice.line_send(message)


def _extension_tag(record: Mapping[str, Any]) -> str | None:
    extensions = record.get("clientExtensions")
    if not isinstance(extensions, Mapping):
        return None
    tag = extensions.get("tag")
    return str(tag) if tag is not None else None


def _extension_id(record: Mapping[str, Any]) -> str | None:
    extensions = record.get("clientExtensions")
    if not isinstance(extensions, Mapping):
        return None
    client_id = extensions.get("id")
    return str(client_id) if client_id is not None else None


@dataclass
class BrokerSnapshot:
    owned_trades: list[dict[str, Any]]
    foreign_trades: list[dict[str, Any]]
    owned_entry_orders: list[dict[str, Any]]
    foreign_entry_orders: list[dict[str, Any]]

    @property
    def entry_block_reason(self) -> str | None:
        if len(self.owned_trades) > 1:
            return "multiple owned EUR/USD trades"
        if self.owned_entry_orders:
            return "unexpected owned EUR/USD pending entry order exists"
        if self.owned_trades:
            return "owned EUR/USD trade already exists"
        return None


def _broker_snapshot(oa: classOanda.Oanda) -> BrokerSnapshot:
    trade_result = oa.OpenTrades_exe()
    if trade_result.get("error") != 0:
        raise LiveDataError("OpenTrades failed")
    order_result = oa.OrdersWaitPending_exe()
    if order_result.get("error") != 0:
        raise LiveDataError("OrdersWaitPending failed")
    trade_frame = trade_result.get("data")
    order_frame = order_result.get("data")
    trades = (
        trade_frame.to_dict("records")
        if isinstance(trade_frame, pd.DataFrame) and not trade_frame.empty
        else []
    )
    orders = (
        order_frame.to_dict("records")
        if isinstance(order_frame, pd.DataFrame) and not order_frame.empty
        else []
    )
    pair_trades = [item for item in trades if item.get("instrument") == PAIR_NAME]
    pair_orders = [item for item in orders if item.get("instrument") == PAIR_NAME]
    return BrokerSnapshot(
        owned_trades=[item for item in pair_trades if _extension_tag(item) == OWNER_TAG],
        foreign_trades=[item for item in pair_trades if _extension_tag(item) != OWNER_TAG],
        owned_entry_orders=[item for item in pair_orders if _extension_tag(item) == OWNER_TAG],
        foreign_entry_orders=[item for item in pair_orders if _extension_tag(item) != OWNER_TAG],
    )


def _fresh_quote(
    oa: classOanda.Oanda,
    instrument: str,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    result = oa.NowPrice_exe(instrument)
    if result.get("error") != 0:
        raise LiveDataError(f"{instrument} pricing failed")
    quote = result.get("data") or {}
    if quote.get("instrument") != instrument:
        raise LiveDataError(f"{instrument} pricing instrument mismatch")
    if quote.get("tradeable") is not True:
        raise LiveDataError(f"{instrument} is not tradeable")
    bid = float(quote.get("raw_bid"))
    ask = float(quote.get("raw_ask"))
    if not math.isfinite(bid) or not math.isfinite(ask) or ask < bid:
        raise LiveDataError(f"{instrument} quote is invalid")
    pair = gene.currency_pair(instrument)
    spread_pips = (ask - bid) / pair.pip_value
    if spread_pips > pair.spread_limit_pips + 1e-12:
        raise SpreadTooWideError(
            f"{instrument} spread {spread_pips:.2f}p exceeds {pair.spread_limit_pips:.2f}p"
        )
    quote_time = _parse_utc(quote.get("time"))
    current = now or _utc_now()
    age = (current - quote_time).total_seconds()
    if age < -2.0 or age > QUOTE_MAX_AGE_SECONDS:
        raise LiveDataError(f"{instrument} quote age is {age:.1f}s")
    quote["quote_time_utc"] = quote_time
    quote["spread_pips"] = spread_pips
    return quote


def _fetch_raw_candles(
    oa: classOanda.Oanda,
    granularity: str,
    count: int,
) -> pd.DataFrame:
    result = oa.InstrumentsCandles_multi_support_exe(
        PAIR_NAME,
        {"granularity": granularity, "count": int(count), "price": "M"},
    )
    if result.get("error") != 0:
        raise LiveDataError(f"{granularity} candle fetch failed")
    frame = result.get("data")
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        raise LiveDataError(f"{granularity} candle response is empty")
    required = {"time", "time_jp", "complete", "mid"}
    missing = required - set(frame.columns)
    if missing:
        raise LiveDataError(
            f"{granularity} candle response missing: {', '.join(sorted(missing))}"
        )
    work = frame.copy()
    work = work[work["complete"].eq(True)].copy()
    if work.empty:
        raise LiveDataError(f"{granularity} has no completed candles")
    work["time_utc"] = pd.to_datetime(work["time"], utc=True, errors="coerce")
    if work["time_utc"].isna().any():
        raise LiveDataError(f"{granularity} contains an invalid timestamp")
    work.sort_values("time_utc", kind="stable", inplace=True)
    duplicate = work[work["time_utc"].duplicated(keep=False)]
    if not duplicate.empty:
        raise LiveDataError(f"{granularity} contains duplicate completed candles")
    work.reset_index(drop=True, inplace=True)
    return work


def _prepare_completed_frame(
    raw: pd.DataFrame,
    decision_utc: dt.datetime,
    timeframe: pd.Timedelta,
) -> pd.DataFrame:
    cutoff = pd.Timestamp(decision_utc)
    work = raw[raw["time_utc"] + timeframe <= cutoff].copy()
    if work.empty:
        raise LiveDataError("no candles completed by the decision time")
    pair = gene.currency_pair(PAIR_NAME)
    processed = classOanda.add_basic_data(work, pair)
    processed = classOanda.add_rsi(processed)
    processed = classOanda.add_bb_data(processed, pair)
    return prepare_m5(processed)


def _assert_history_coverage(
    frame: pd.DataFrame,
    count: int,
    timeframe: pd.Timedelta,
    name: str,
) -> pd.DataFrame:
    if len(frame) < count:
        raise LiveDataError(f"insufficient {name} history: {len(frame)}/{count}")
    selected = frame.tail(count).copy()
    times = [pd.Timestamp(value) for value in selected["time_jp_dt"]]
    for previous, following in zip(times, times[1:]):
        difference = following - previous
        if difference == timeframe:
            continue
        # Candle timestamps are interval starts.  Test only the uncovered span;
        # the preceding candle itself may contain valid trading time.
        previous_covered_end = previous + timeframe - pd.Timedelta(seconds=5)
        if (
            difference <= timeframe
            or difference % timeframe != pd.Timedelta(0)
            or not _is_expected_market_closed_gap(previous_covered_end, following)
        ):
            raise LiveDataError(f"unknown gap in required {name} history")
    return selected.reset_index(drop=True)


def _marker_row(frame: pd.DataFrame, decision_jst: pd.Timestamp) -> pd.DataFrame:
    marker = frame.iloc[-1].copy()
    close = float(frame.iloc[-1]["close"])
    marker["time_jp"] = decision_jst.strftime(TIME_FORMAT)
    marker["time_jp_dt"] = decision_jst
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
        if column in marker:
            marker[column] = close
    for column in ("body", "body_abs", "moves", "highlow", "up_rod", "low_rod"):
        if column in marker:
            marker[column] = 0.0
    if "direction" in marker:
        marker["direction"] = 0
    return pd.concat([frame, pd.DataFrame([marker])], ignore_index=True)


def _candidate_rows(
    m5: pd.DataFrame,
    h1: pd.DataFrame,
    decision_jst: pd.Timestamp,
) -> list[dict[str, Any]]:
    pair = gene.currency_pair(PAIR_NAME)
    marker_frame = _marker_row(m5, decision_jst)
    index = len(marker_frame) - 1
    target = target_parameters(
        marker_frame,
        index,
        pair,
        lookback=6,
        multiplier=3.0,
        rr=1.2,
    )
    if not target.get("target_valid"):
        raise LiveDataError(f"target invalid: {target.get('target_skip_reason')}")
    rebuilt = rebuild_candidates_at(
        marker_frame,
        index,
        PAIR_NAME,
        h1=h1,
    )
    peak = rebuilt["newest_peak"]
    peak_direction = int(peak.get("direction") or 0)
    fc2_shape = foot_count2_shape_context(
        rebuilt["completed_history"],
        peak,
        decision_jst,
        pair,
        average_range_pips=target["recent_m5_avg_range_pips"],
        timeframe_minutes=5,
    )
    if not fc2_shape.get("valid"):
        raise LiveDataError(f"FC2 shape invalid: {fc2_shape.get('reason')}")
    h1_shape = rebuilt["h1_pair_shape_context"]
    if not h1_shape.get("valid"):
        raise LiveDataError(f"H1 shape invalid: {h1_shape.get('reason')}")
    event_id = f"{PAIR_NAME}_{decision_jst:%Y%m%d%H%M%S}"
    event_base = {
        "event_id": event_id,
        "pair": PAIR_NAME,
        "decision_time": decision_jst,
        "counterfactual_candidates": True,
        **target,
        **_peak_columns(peak, pair),
        **flatten_foot_count2_shape(fc2_shape),
        **flatten_foot_count2_shape(h1_shape, prefix="h1_pair_"),
        "decision_price": rebuilt["current_price"],
        "rsi_1": rebuilt["rsi_info"].get("rsi_1"),
        "rsi_2": rebuilt["rsi_info"].get("rsi_2"),
        "rsi_3": rebuilt["rsi_info"].get("rsi_3"),
        **stair_analysis_columns(
            rebuilt["stair_context"],
            peak_direction,
        ),
        **stair_analysis_columns(
            rebuilt["h1_stair_context"],
            peak_direction,
            prefix="h1_stair",
        ),
    }
    rows: list[dict[str, Any]] = []
    for candidate in rebuilt["candidates"]:
        line = candidate["line"]
        directions = line.get("dirs_grouped") or []
        if not directions:
            continue
        try:
            latest_line_peak_direction = int(np.sign(float(directions[0])))
        except (TypeError, ValueError):
            continue
        if latest_line_peak_direction != -peak_direction:
            continue
        line_fc2_shape = attach_line_wick_context(
            fc2_shape,
            line_price=candidate["line_price"],
            line_side=candidate["line_side"],
            pair=pair,
        )
        touches = line_touch_features(
            rebuilt["completed_history"],
            line,
            decision_jst,
            pair,
            RETOUCH_TOLERANCE_PIPS,
        )
        row = {
            **event_base,
            "candidate_rank": candidate["candidate_rank"],
            "distance_rank": candidate["distance_rank"],
            "line_side": candidate["line_side"],
            "trade_direction": candidate["trade_direction"],
            "trade_side": candidate["trade_side"],
            "line_price": candidate["line_price"],
            "raw_line_price": candidate["raw_line_price"],
            "distance_pips": candidate["distance_pips"],
            "current_policy_reversal_target": candidate.get(
                "current_policy_reversal_target"
            ),
            "line_latest_constituent_peak_direction": latest_line_peak_direction,
            **flatten_foot_count2_shape(line_fc2_shape),
            **_line_columns(line),
            **touches,
        }
        validate_causal_candidate(row)
        rows.append(row)
    return rows


def build_live_signal(
    oa: classOanda.Oanda,
    decision_utc: dt.datetime,
) -> dict[str, Any] | None:
    decision_jst = pd.Timestamp(decision_utc).tz_convert("Asia/Tokyo").tz_localize(None)
    raw_m5 = _fetch_raw_candles(oa, "M5", 350)
    raw_h1 = _fetch_raw_candles(oa, "H1", 300)
    m5 = _prepare_completed_frame(raw_m5, decision_utc, pd.Timedelta(minutes=5))
    h1 = _prepare_completed_frame(raw_h1, decision_utc, pd.Timedelta(hours=1))
    if pd.Timestamp(m5.iloc[-1]["time_jp_dt"]) + pd.Timedelta(minutes=5) != decision_jst:
        raise LiveDataError("latest completed M5 does not end at the decision boundary")
    m5 = _assert_history_coverage(m5, 180, pd.Timedelta(minutes=5), "M5")
    h1 = _assert_history_coverage(h1, 240, pd.Timedelta(hours=1), "H1")
    try:
        rows = _candidate_rows(m5, h1, decision_jst)
    except ValueError as error:
        normal_prefixes = ("no_peak", "count2_prefilter_mismatch")
        if str(error).startswith(normal_prefixes):
            return None
        raise
    if not rows:
        return None
    frame = pd.DataFrame(rows)
    frame = frame[target_distance_filter_mask(frame, MIN_TARGET_DISTANCE_PIPS)].copy()
    if frame.empty:
        return None
    featured = add_feature_buckets(frame)
    selected = select_top_condition_policy_candidates(
        featured,
        RANKED_CONDITIONS,
        TIER_CONFIGS,
    )
    if selected.empty:
        return None
    row = selected.iloc[0]
    tier_name = str(row["signal_tier"])
    tier = TIER_BY_NAME[tier_name]
    average_range_pips = float(row["recent_m5_avg_range_pips"])
    tp_pips, lc_pips = effective_trade_widths(
        average_range_pips,
        tier.trade_combo,
        gene.currency_pair(PAIR_NAME),
        MIN_WIDTH_PIPS,
    )
    peak_direction = int(row["peak_direction"])
    order_direction = int(row["trade_direction"])
    if order_direction != -peak_direction:
        raise LiveDataError("selected order direction is not opposite FC2 direction")
    line_price = float(row["line_price"])
    signal_seed = (
        f"{PAIR_NAME}|{decision_utc.isoformat()}|{line_price:.5f}|"
        f"{peak_direction}|{int(row['highest_matched_rank'])}"
    )
    signal_id = "fp_" + hashlib.sha256(signal_seed.encode("utf-8")).hexdigest()[:24]
    matched_ids = json.loads(str(row["matched_condition_ids"]))
    matched_ranks = json.loads(str(row["matched_condition_ranks"]))
    return {
        "phase": "PENDING_TOUCH",
        "signal_id": signal_id,
        "client_id": "fp_eur_" + signal_id.removeprefix("fp_"),
        "policy_version": POLICY_VERSION,
        "policy_fingerprint": POLICY_FINGERPRINT,
        "decision_time_utc": _utc_iso(decision_utc),
        "expiry_time_utc": _utc_iso(
            decision_utc + dt.timedelta(minutes=ORDER_WAIT_MINUTES)
        ),
        "line_price": line_price,
        "distance_pips": float(row["distance_pips"]),
        "distance_rank": int(row["distance_rank"]),
        "peak_direction": peak_direction,
        "order_direction": order_direction,
        "trade_side": "BUY" if order_direction == 1 else "SELL",
        "a_range_pips": average_range_pips,
        "a_price": gene.currency_pair(PAIR_NAME).pips_to_price(
            average_range_pips
        ),
        "signal_tier": tier_name,
        "highest_matched_rank": int(row["highest_matched_rank"]),
        "matched_condition_ids": matched_ids,
        "matched_condition_ranks": matched_ranks,
        "tier_tp_a": float(row["tier_tp_a"]),
        "tier_lc_a": float(row["tier_lc_a"]),
        "tier_rr": float(row["tier_rr"]),
        "tp_pips": float(tp_pips),
        "lc_pips": float(lc_pips),
        "risk_yen": RISK_YEN,
        "created_at_utc": _utc_iso(_utc_now()),
    }


def _normalize_s5(raw: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for _, candle in raw.iterrows():
        mid = candle.get("mid")
        if not isinstance(mid, Mapping):
            raise LiveDataError("S5 candle has no mid OHLC")
        values = {
            name: float(mid[key])
            for name, key in (("open", "o"), ("high", "h"), ("low", "l"), ("close", "c"))
        }
        if not all(math.isfinite(value) for value in values.values()):
            raise LiveDataError("S5 candle contains non-finite OHLC")
        rows.append({"time_utc": candle["time_utc"], **values})
    result = pd.DataFrame(rows).sort_values("time_utc", kind="stable")
    result.reset_index(drop=True, inplace=True)
    return result


def _exact_s5_window(
    frame: pd.DataFrame,
    start: dt.datetime,
    end: dt.datetime,
) -> pd.DataFrame:
    expected = pd.date_range(start=start, end=end, freq="5s", tz="UTC")
    indexed = frame.set_index("time_utc", verify_integrity=True)
    missing = expected.difference(indexed.index)
    if len(missing):
        raise LiveDataError(
            f"missing S5 candle at {pd.Timestamp(missing[0]).isoformat()}"
        )
    return indexed.loc[expected].reset_index()


def _owned_open_trade_details(
    oa: classOanda.Oanda,
    trade_id: str,
) -> dict[str, Any] | None:
    result = oa.TradeDetails_exe(trade_id)
    if result.get("error") != 0:
        raise LiveDataError(f"TradeDetails failed for {trade_id}")
    trade = (result.get("data") or {}).get("trade") or {}
    if str(trade.get("id")) != str(trade_id):
        raise LiveDataError("TradeDetails id mismatch")
    if trade.get("instrument") != PAIR_NAME:
        raise LiveDataError("TradeDetails pair mismatch")
    if _extension_tag(trade) != OWNER_TAG:
        raise LiveDataError("TradeDetails owner tag mismatch")
    if trade.get("state") != "OPEN":
        return None
    return trade


class FlipPredictEurLive:
    def __init__(
        self,
        oa: classOanda.Oanda,
        store: StateStore,
        notifier: LiveNotifier,
        state: dict[str, Any],
    ) -> None:
        self.oa = oa
        self.store = store
        self.notifier = notifier
        self.state = state
        self.snapshot: BrokerSnapshot | None = None
        self.last_broker_poll = -math.inf
        self.last_s5_poll = -math.inf

    def save(self) -> None:
        self.store.save(self.state)

    def finish_active(self, reason: str, *details: str) -> None:
        active = self.state.get("active") or {}
        signal_id = active.get("signal_id")
        recent = list(self.state.get("recent_signal_ids") or [])
        if signal_id and signal_id not in recent:
            recent.append(signal_id)
        self.state["recent_signal_ids"] = recent[-100:]
        self.state["last_completion"] = {
            "signal_id": signal_id,
            "reason": reason,
            "time_utc": _utc_iso(_utc_now()),
        }
        self.state["active"] = None
        self.save()
        if reason == "broker_trade_closed":
            self.notifier.send(
                "owned trade closed",
                *(details or (f"signal: {signal_id}",)),
            )
        elif reason in LIFECYCLE_ERROR_REASONS:
            self.notifier.send(
                "lifecycle error",
                f"reason: {reason}",
                *(details or (f"signal: {signal_id}",)),
            )

    def reconcile(self, snapshot: BrokerSnapshot) -> None:
        self.snapshot = snapshot
        active = self.state.get("active")
        owned = snapshot.owned_trades
        if len(owned) > 1:
            self.notifier.send(
                "entry blocked",
                "multiple owned EUR/USD trades were found",
                "no automatic close or cancellation was performed",
                throttle_key="multiple_owned",
                throttle_seconds=300,
            )
            return
        if owned:
            trade = owned[0]
            trade_id = str(trade.get("id"))
            trade_client_id = _extension_id(trade)
            if active is None or active.get("phase") != "POSITION_OPEN":
                signal_matches = bool(
                    active
                    and active.get("client_id")
                    and str(active.get("client_id")) == trade_client_id
                )
                if signal_matches:
                    recovered = dict(active)
                else:
                    abandoned_signal_id = active.get("signal_id") if active else None
                    recent = list(self.state.get("recent_signal_ids") or [])
                    if abandoned_signal_id and abandoned_signal_id not in recent:
                        recent.append(abandoned_signal_id)
                    self.state["recent_signal_ids"] = recent[-100:]
                    recovered = {
                        "signal_id": f"recovered_{trade_id}",
                        "client_id": trade_client_id,
                        "orphan_recovery": True,
                        "abandoned_signal_id": abandoned_signal_id,
                    }
                recovered.update(
                    {
                        "phase": "POSITION_OPEN",
                        "trade_id": trade_id,
                        "fill_price": float(trade.get("price")),
                        "open_time_utc": _utc_iso(_parse_utc(trade.get("openTime"))),
                        "protection_exact": (
                            bool(recovered.get("protection_exact", False))
                            if signal_matches
                            else None
                        ),
                        "recovered_from_broker": True,
                    }
                )
                self.state["active"] = recovered
                self.save()
                self.notifier.send(
                    "owned trade recovered",
                    f"trade id: {trade_id}",
                    f"signal ownership match: {signal_matches}",
                    "60-minute hard-close management is active",
                )
            elif str(active.get("trade_id")) != trade_id:
                raise LiveDataError("persisted trade id differs from owned broker trade")
            elif active.get("client_id") and str(active.get("client_id")) != trade_client_id:
                raise LiveDataError("persisted client id differs from owned broker trade")
            return
        if active and active.get("phase") == "POSITION_OPEN":
            trade_id = str(active.get("trade_id"))
            try:
                detail = _owned_open_trade_details(self.oa, trade_id)
            except LiveDataError as error:
                self.notifier.send(
                    "trade snapshot could not be confirmed",
                    f"trade id: {trade_id}",
                    f"detail: {error}",
                    "the lifecycle remains locked; no new order is allowed",
                    throttle_key="trade_snapshot_unconfirmed",
                    throttle_seconds=60,
                )
                return
            if detail is None:
                self.finish_active(
                    "broker_trade_closed",
                    f"trade id: {trade_id}",
                    "closure was confirmed by TradeDetails; no new order was issued",
                )
            else:
                self.notifier.send(
                    "OpenTrades snapshot omission",
                    f"trade id: {trade_id}",
                    "TradeDetails still reports OPEN; lifecycle remains locked",
                    throttle_key="open_trade_snapshot_omission",
                    throttle_seconds=60,
                )

    def ensure_exact_protection(self) -> None:
        active = self.state.get("active") or {}
        if active.get("phase") != "POSITION_OPEN":
            return
        if active.get("protection_exact") is True:
            return
        required = ("trade_id", "fill_price", "tp_pips", "lc_pips", "order_direction")
        if any(active.get(name) is None for name in required):
            return
        previous_attempt = active.get("protection_last_attempt_at_utc")
        if previous_attempt and (
            _utc_now() - _parse_utc(previous_attempt)
        ).total_seconds() < 15:
            return
        trade_id = str(active["trade_id"])
        if _owned_open_trade_details(self.oa, trade_id) is None:
            return
        pair = gene.currency_pair(PAIR_NAME)
        fill_price = float(active["fill_price"])
        direction = int(active["order_direction"])
        tp_price = pair.round_price(
            fill_price + direction * pair.pips_to_price(float(active["tp_pips"]))
        )
        lc_price = pair.round_price(
            fill_price - direction * pair.pips_to_price(float(active["lc_pips"]))
        )
        active["protection_last_attempt_at_utc"] = _utc_iso(_utc_now())
        self.save()
        result = self.oa.TradeCRCDO_exe(
            trade_id,
            {
                "takeProfit": {"price": tp_price, "timeInForce": "GTC"},
                "stopLoss": {"price": lc_price, "timeInForce": "GTC"},
            },
            instrument=PAIR_NAME,
        )
        if result.get("error") != 0:
            self.notifier.send(
                "protection adjustment failed",
                f"trade id: {trade_id}",
                "initial server-side TP/SL remains in place; retrying later",
                throttle_key="protection_failed",
                throttle_seconds=60,
            )
            return
        confirmed = _owned_open_trade_details(self.oa, trade_id)
        if confirmed is None:
            return
        take_profit = confirmed.get("takeProfitOrder")
        stop_loss = confirmed.get("stopLossOrder")
        confirmed_tp = (
            float(take_profit.get("price"))
            if isinstance(take_profit, Mapping) and take_profit.get("price") is not None
            else math.nan
        )
        confirmed_lc = (
            float(stop_loss.get("price"))
            if isinstance(stop_loss, Mapping) and stop_loss.get("price") is not None
            else math.nan
        )
        price_tolerance = 0.5 * (10.0 ** -pair.round_keta)
        if (
            not math.isfinite(confirmed_tp)
            or not math.isfinite(confirmed_lc)
            or abs(confirmed_tp - tp_price) > price_tolerance
            or abs(confirmed_lc - lc_price) > price_tolerance
        ):
            self.notifier.send(
                "protection verification failed",
                f"trade id: {trade_id}",
                "TradeDetails did not confirm both exact TP/SL prices",
                "initial or last confirmed server-side protection remains; retrying later",
                throttle_key="protection_verify_failed",
                throttle_seconds=60,
            )
            return
        active["exact_tp_price"] = tp_price
        active["exact_lc_price"] = lc_price
        active["protection_exact"] = True
        active["protection_updated_at_utc"] = _utc_iso(_utc_now())
        self.save()
        self.notifier.send(
            "protection confirmed",
            f"trade id: {trade_id}",
            f"TP: {tp_price:.5f}",
            f"LC: {lc_price:.5f}",
        )

    def manage_position(self, now: dt.datetime) -> None:
        active = self.state.get("active") or {}
        if active.get("phase") != "POSITION_OPEN":
            return
        open_raw = active.get("open_time_utc")
        if not open_raw:
            self.ensure_exact_protection()
            return
        open_time = _parse_utc(open_raw)
        if now < open_time + dt.timedelta(minutes=POSITION_HORIZON_MINUTES):
            self.ensure_exact_protection()
            return
        previous_attempt = active.get("hard_close_attempt_at_utc")
        if previous_attempt and (now - _parse_utc(previous_attempt)).total_seconds() < 15:
            return
        trade_id = str(active.get("trade_id"))
        trade = _owned_open_trade_details(self.oa, trade_id)
        if trade is None:
            return
        active["hard_close_attempt_at_utc"] = _utc_iso(now)
        self.save()
        result = self.oa.TradeClose_exe(trade_id, None)
        if result.get("error") != 0:
            self.notifier.send(
                "60-minute hard close failed",
                f"trade id: {trade_id}",
                "the exact owned trade will be retried; no other trade was touched",
                throttle_key="hard_close_failed",
                throttle_seconds=30,
            )
            return
        active["hard_close_requested"] = True
        active["hard_close_requested_at_utc"] = _utc_iso(now)
        self.save()
        self.notifier.send(
            "60-minute hard close requested",
            f"trade id: {trade_id}",
            f"OANDA open time: {open_time.isoformat()}",
        )

    def process_pending_touch(self, frame: pd.DataFrame, now: dt.datetime) -> None:
        active = self.state.get("active") or {}
        decision = _parse_utc(active["decision_time_utc"])
        expiry = _parse_utc(active["expiry_time_utc"])
        if frame.empty or frame["time_utc"].max().to_pydatetime() < decision:
            if now > expiry + dt.timedelta(seconds=30):
                self.finish_active("s5_coverage_unavailable_before_expiry")
            return
        latest = frame["time_utc"].max().to_pydatetime()
        scan_end = min(latest, expiry - dt.timedelta(seconds=5))
        if scan_end < decision:
            return
        try:
            window = _exact_s5_window(frame, decision, scan_end)
        except LiveDataError as error:
            self.finish_active("unknown_s5_gap_before_touch", str(error))
            return
        pair = gene.currency_pair(PAIR_NAME)
        half_spread = pair.pips_to_price(FIXED_TOUCH_SPREAD_PIPS / 2.0)
        if int(active["peak_direction"]) == 1:
            touched = window["high"].sub(half_spread).ge(float(active["line_price"]))
        else:
            touched = window["low"].add(half_spread).le(float(active["line_price"]))
        matches = np.flatnonzero(touched.to_numpy(dtype=bool))
        if matches.size:
            touch_time = pd.Timestamp(window.iloc[int(matches[0])]["time_utc"]).to_pydatetime()
            active["phase"] = "OBSERVING"
            active["touch_time_utc"] = _utc_iso(touch_time)
            active["observation_ready_time_utc"] = _utc_iso(
                touch_time + dt.timedelta(seconds=WATCH_CONFIG.observation_seconds + 5)
            )
            self.save()
            self.notifier.send(
                "line touched",
                f"signal: {active.get('signal_id')}",
                f"line: {float(active['line_price']):.5f}",
                "touch S5 is excluded; the next 12 completed S5 bars are observed",
            )
            return
        if latest >= expiry - dt.timedelta(seconds=5):
            self.finish_active("touch_wait_expired")
        elif now > expiry + dt.timedelta(seconds=30):
            self.finish_active("s5_coverage_unavailable_before_expiry")

    def process_observation(self, frame: pd.DataFrame, now: dt.datetime) -> None:
        active = self.state.get("active") or {}
        touch = _parse_utc(active["touch_time_utc"])
        ready = touch + dt.timedelta(seconds=WATCH_CONFIG.observation_seconds + 5)
        if now < ready:
            return
        observation_start = touch + dt.timedelta(seconds=5)
        observation_last_start = touch + dt.timedelta(
            seconds=WATCH_CONFIG.observation_seconds
        )
        try:
            observed = _exact_s5_window(frame, observation_start, observation_last_start)
        except LiveDataError as error:
            if now >= ready + dt.timedelta(seconds=5):
                self.finish_active("unknown_s5_gap_during_observation", str(error))
            return
        close = float(observed.iloc[-1]["close"])
        breakout_a = (
            (close - float(active["line_price"]))
            * int(active["peak_direction"])
            / float(active["a_price"])
        )
        classification = classify_flip_watch_entry(
            breakout_a,
            int(active["peak_direction"]),
            WATCH_CONFIG,
        )
        active.update(_json_safe(classification))
        active["watch_breakout_a"] = breakout_a
        active["watch_close_price"] = close
        active["watch_classified_at_utc"] = _utc_iso(ready)
        if (
            classification["watch_order_name"] != "FlipPredict_LineHolding"
            or classification["watch_chase_filtered"]
        ):
            branch = str(classification["watch_order_name"])
            reason = "line_holding_chase_filtered" if classification["watch_chase_filtered"] else "non_line_holding_branch"
            self.finish_active(reason, f"classification: {branch}", f"breakout: {breakout_a:.3f}A")
            return
        if int(classification["order_direction"]) != int(active["order_direction"]):
            raise LiveDataError("LineHolding classification direction mismatch")
        active["phase"] = "READY"
        active["release_time_utc"] = _utc_iso(ready)
        active["release_deadline_utc"] = _utc_iso(
            ready + dt.timedelta(seconds=READY_MAX_AGE_SECONDS)
        )
        self.save()

    def submit_ready(self, now: dt.datetime) -> None:
        active = self.state.get("active") or {}
        if active.get("phase") != "READY":
            return
        if now > _parse_utc(active["release_deadline_utc"]):
            spread_detail = active.get("release_spread_wait_detail")
            if spread_detail:
                self.finish_active("spread_too_wide_at_release", str(spread_detail))
            else:
                self.finish_active("line_holding_release_stale")
            return
        snapshot = _broker_snapshot(self.oa)
        self.reconcile(snapshot)
        active = self.state.get("active") or {}
        if active.get("phase") != "READY":
            return
        if snapshot.entry_block_reason:
            return
        try:
            usd_jpy_quote = _fresh_quote(self.oa, USD_JPY_NAME)
            quote = _fresh_quote(self.oa, PAIR_NAME)
        except SpreadTooWideError as error:
            detail = str(error)
            if active.get("release_spread_wait_detail") != detail:
                active["release_spread_wait_detail"] = detail
                self.save()
            return
        active.pop("release_spread_wait_detail", None)
        usd_jpy_rate = (
            float(usd_jpy_quote["raw_bid"])
            + float(usd_jpy_quote["raw_ask"])
        ) / 2.0
        direction = int(active["order_direction"])
        entry_price = float(quote["raw_ask"] if direction == 1 else quote["raw_bid"])
        actual_entry_a = (
            (entry_price - float(active["line_price"]))
            * int(active["peak_direction"])
            / float(active["a_price"])
        )
        if not (-WATCH_CONFIG.line_holding_max_chase_a <= actual_entry_a < WATCH_CONFIG.line_holding_max_breakout_a):
            self.finish_active(
                "line_holding_quote_recheck_failed",
                f"actual entry distance: {actual_entry_a:.3f}A",
                "required: -0.300A <= distance < 0.100A",
            )
            return
        pair = gene.currency_pair(PAIR_NAME)
        risk_lc_pips = float(active["lc_pips"]) + MAX_MARKET_SLIPPAGE_PIPS
        yen_per_unit_at_risk = risk_lc_pips * pair.pip_value * usd_jpy_rate
        units = int(math.floor(RISK_YEN / yen_per_unit_at_risk))
        units = min(units, MAX_UNITS)
        if units < 1:
            self.finish_active("calculated_units_below_one")
            return
        tp_price = pair.round_price(
            entry_price + direction * pair.pips_to_price(float(active["tp_pips"]))
        )
        lc_price = pair.round_price(
            entry_price - direction * pair.pips_to_price(float(active["lc_pips"]))
        )
        price_bound = pair.round_price(
            entry_price + direction * pair.pips_to_price(MAX_MARKET_SLIPPAGE_PIPS)
        )
        signed_units = units * direction
        client_id = str(active["client_id"])
        payload = {
            "order": {
                "type": "MARKET",
                "instrument": PAIR_NAME,
                "units": str(signed_units),
                "timeInForce": "FOK",
                "priceBound": price_bound,
                "positionFill": "OPEN_ONLY",
                "clientExtensions": {
                    "id": client_id,
                    "tag": OWNER_TAG,
                    "comment": "flip_predict_v19_LineHolding",
                },
                "tradeClientExtensions": {
                    "id": client_id,
                    "tag": OWNER_TAG,
                    "comment": "flip_predict_v19_LineHolding",
                },
                "takeProfitOnFill": {"price": tp_price, "timeInForce": "GTC"},
                "stopLossOnFill": {"price": lc_price, "timeInForce": "GTC"},
            }
        }
        submit_time = _utc_now()
        if submit_time > _parse_utc(active["release_deadline_utc"]):
            self.finish_active("line_holding_release_stale_before_post")
            return
        active.update(
            {
                "phase": "SUBMITTING",
                "submitting_at_utc": _utc_iso(submit_time),
                "quote_entry_price": entry_price,
                "actual_entry_a": actual_entry_a,
                "units": units,
                "signed_units": signed_units,
                "initial_tp_price": tp_price,
                "initial_lc_price": lc_price,
                "price_bound": price_bound,
                "usd_jpy_rate": usd_jpy_rate,
            }
        )
        self.save()
        if _utc_now() > _parse_utc(active["release_deadline_utc"]):
            self.finish_active("line_holding_release_stale_after_state_write")
            return
        result = self.oa.OrderCreate_dic_exe(payload)
        if result.get("error") != 0:
            self.notifier.send(
                "order result is ambiguous",
                f"signal: {active.get('signal_id')}",
                "the service will not submit the order again automatically",
            )
            return
        order_data = result.get("data") or {}
        if order_data.get("cancel") is True:
            self.finish_active(
                "market_order_rejected",
                f"signal: {active.get('signal_id')}",
                "OANDA returned a definite cancellation/rejection",
            )
            return
        trade_id = order_data.get("trade_id")
        fill_time = order_data.get("fill_time")
        try:
            fill_price = float(order_data.get("execution_price"))
        except (TypeError, ValueError):
            fill_price = math.nan
        if not trade_id or not fill_time or not math.isfinite(fill_price) or fill_price <= 0:
            self.notifier.send(
                "order fill is ambiguous",
                f"signal: {active.get('signal_id')}",
                "no automatic retry will occur; broker ownership reconciliation remains active",
            )
            return
        active.update(
            {
                "phase": "POSITION_OPEN",
                "trade_id": str(trade_id),
                "fill_price": fill_price,
                "open_time_utc": _utc_iso(_parse_utc(fill_time)),
                "protection_exact": False,
            }
        )
        self.save()
        self.notifier.send(
            "LineHolding market order filled",
            f"trade id: {trade_id}",
            f"side / units: {active['trade_side']} / {units}",
            f"fill: {fill_price:.5f}",
            f"tier / rank: {active['signal_tier']} / {active['highest_matched_rank']}",
        )
        self.ensure_exact_protection()

    def process_watch(self, now: dt.datetime) -> None:
        active = self.state.get("active") or {}
        phase = active.get("phase")
        if phase == "READY":
            self.submit_ready(now)
            return
        if phase not in {"PENDING_TOUCH", "OBSERVING"}:
            return
        monotonic_now = time.monotonic()
        if monotonic_now - self.last_s5_poll < S5_POLL_SECONDS:
            return
        self.last_s5_poll = monotonic_now
        raw = _fetch_raw_candles(self.oa, "S5", 900)
        frame = _normalize_s5(raw)
        if phase == "PENDING_TOUCH":
            self.process_pending_touch(frame, now)
        elif phase == "OBSERVING":
            self.process_observation(frame, now)
            if (self.state.get("active") or {}).get("phase") == "READY":
                self.submit_ready(now)

    def consider_new_signal(self, now: dt.datetime) -> None:
        if self.state.get("active") is not None:
            return
        if self.snapshot is None or self.snapshot.entry_block_reason:
            return
        local = now.astimezone(JST)
        if local.minute % 5 != 0 or not (6 <= local.second < 25):
            return
        decision_local = local.replace(second=0, microsecond=0)
        decision_utc = decision_local.astimezone(UTC)
        decision_key = _utc_iso(decision_utc)
        if self.state.get("last_decision_time_utc") == decision_key:
            return
        try:
            _fresh_quote(self.oa, PAIR_NAME)
        except SpreadTooWideError:
            return
        try:
            signal = build_live_signal(self.oa, decision_utc)
        except ValueError as error:
            if str(error).startswith(("no_peak", "count2_prefilter_mismatch")):
                self.state["last_decision_time_utc"] = decision_key
                self.save()
                return
            raise
        if signal is None:
            self.state["last_decision_time_utc"] = decision_key
            self.save()
            return
        if signal["signal_id"] in set(self.state.get("recent_signal_ids") or []):
            self.state["last_decision_time_utc"] = decision_key
            self.save()
            return
        self.state["last_decision_time_utc"] = decision_key
        self.state["active"] = signal
        self.save()
        self.notifier.send(
            "LineHolding candidate registered",
            f"decision: {decision_local:%Y-%m-%d %H:%M:%S %Z}",
            f"side / line: {signal['trade_side']} / {signal['line_price']:.5f}",
            f"tier / rank: {signal['signal_tier']} / {signal['highest_matched_rank']}",
            f"TP / LC: {signal['tp_pips']:.2f}p / {signal['lc_pips']:.2f}p",
            "next FC2 will not replace this candidate",
        )

    def tick(self) -> None:
        now = _utc_now()
        monotonic_now = time.monotonic()
        if monotonic_now - self.last_broker_poll >= BROKER_POLL_SECONDS:
            self.last_broker_poll = monotonic_now
            snapshot = _broker_snapshot(self.oa)
            self.reconcile(snapshot)
            self.manage_position(now)
        self.process_watch(now)
        self.consider_new_signal(now)

    def run(self) -> None:
        self.notifier.send(
            "service started",
            f"policy: {POLICY_VERSION} / LineHolding only",
            "risk: 50 yen; one EUR/USD lifecycle at a time",
            "manual/unowned EUR/USD resources are ignored and never modified; OPEN_ONLY is active",
            "wide live spreads silently pause new-signal analysis and order release",
        )
        while True:
            try:
                self.tick()
            except KeyboardInterrupt:
                raise
            except Exception as error:
                print("[EUR_USD live error]", type(error).__name__, str(error))
                self.notifier.send(
                    "fail-closed error",
                    f"{type(error).__name__}: {error}",
                    "no retry order, account-wide cancel, or account-wide close was issued",
                    throttle_key=f"loop_error:{type(error).__name__}:{error}",
                    throttle_seconds=60,
                )
            time.sleep(LOOP_SLEEP_SECONDS)


def _validate_live_tokens() -> None:
    if getattr(tk, "environmentl", None) != "live":
        raise RuntimeError("tokens.environmentl must be exactly 'live'")
    if not getattr(tk, "accountIDl2", ""):
        raise RuntimeError("tokens.accountIDl2 is empty")
    if not getattr(tk, "access_tokenl", ""):
        raise RuntimeError("tokens.access_tokenl is empty")


def run_live() -> None:
    """Start the explicitly authorized EUR/USD live loop."""
    gene.set_current_pair(PAIR_NAME)
    notifier = LiveNotifier()
    store = StateStore(STATE_PATH)
    with SingleInstanceLock(LOCK_PATH):
        store.archive_orphan_temps()
        state = store.load()
        _validate_live_tokens()
        oa = classOanda.Oanda(tk.accountIDl2, tk.access_tokenl, tk.environmentl)
        service = FlipPredictEurLive(oa, store, notifier, state)
        try:
            service.run()
        except KeyboardInterrupt:
            notifier.send(
                "service stopped",
                "operator interrupt received",
                "broker-side TP/SL and any open owned trade remain unchanged",
            )
