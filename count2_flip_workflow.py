# 最新更新日時: 2026-08-25 15:35 JST
"""Shared I/O, aggregation, and replay mechanics for ``flip_predict``."""

from __future__ import annotations

import datetime as dt
import json
import math
import os
import time
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Iterable, Mapping

import numpy as np
import pandas as pd

import fGeneric as gene
import tokens as tk
from count2_flip_core import (
    CONDITION_MINIMUM_POSITIVE_PERIODS,
    CONDITION_MULTIPLE_TESTING_ALPHA,
    EARLY_PATH_METRICS,
    EARLY_PATH_MINUTES,
    FEATURE_FIELDS,
    FLIP_VERSION,
    MINIMUM_CONDITION_TRADES,
    RANGE_FILTER_FRACTION_A,
    STRETCH_PROFIT_LOCK_TP_FRACTION,
    STRETCH_PROFIT_TARGET_B,
    STRETCH_PROFIT_TRIGGER_TP_FRACTION,
    FlipPathConfig,
    FlipPathInspector,
    FlipWatchEntryConfig,
    LineWickLcConfig,
    PolicyCondition,
    RankedPolicyCondition,
    RiskMultipleProfitLock,
    TierExecutionConfig,
    TimedHalfLcConfig,
    TradeCombo,
    add_feature_buckets,
    bonferroni_z_threshold,
    condition_mask,
    expected_role,
    line_wick_outcome_key,
    overlay_outcome_key,
    timed_outcome_key,
    tier_for_rank,
)
from count2_target_grid_search import (
    _bound_inspector_before,
    _load_typed_s5_inspector,
    _s5_coverage_errors,
)


Notice = Callable[[str], None]


SOURCE_COLUMNS = {
    "event_id",
    "pair",
    "decision_time",
    "next_count2_time",
    "counterfactual_candidates",
    "target_valid",
    "target_source_last_time",
    "recent_m5_avg_range_pips",
    "peak_count",
    "peak_direction",
    "trade_direction",
    "peak_strength",
    "fc2_valid",
    "fc2_source_last_time",
    "fc2_shape",
    "fc2_candle_sequence",
    "fc2_second_wick_A",
    "fc2_second_close_pushback_A",
    "fc2_second_body_to_first_ratio",
    "h1_pair_source_last_time",
    "h1_pair_shape",
    "decision_price",
    "rsi_1",
    "m5_stair_observed_direction",
    "h1_stair_observed_direction",
    "distance_rank",
    "line_price",
    "distance_pips",
    "line_total_strength",
    "line_count",
    "line_average_strength",
    "line_core_count",
    "line_core_total_strength",
    "line_newest_source_time",
    "line_source_directions",
    "line_is_flipped",
    "line_current_role",
    "line_history_is_flipped",
    "line_flip_count",
    "line_latest_touch_time",
    "line_latest_flip_time",
    "line_age_minutes",
    "prior_retouch_count",
    "minutes_since_prior_retouch",
}

# New candidate ledgers persist this directly.  Older ledgers remain usable:
# the shared FC2 helper derives the same value from candle_sequence and
# peak_direction without consulting any future candle.
OPTIONAL_SOURCE_COLUMNS = {
    "fc2_relative_candle_sequence",
}

NUMERIC_SOURCE_COLUMNS = {
    "recent_m5_avg_range_pips",
    "peak_count",
    "peak_direction",
    "trade_direction",
    "peak_strength",
    "fc2_second_wick_A",
    "fc2_second_close_pushback_A",
    "fc2_second_body_to_first_ratio",
    "decision_price",
    "rsi_1",
    "m5_stair_observed_direction",
    "h1_stair_observed_direction",
    "distance_rank",
    "line_price",
    "distance_pips",
    "line_total_strength",
    "line_count",
    "line_average_strength",
    "line_core_count",
    "line_core_total_strength",
    "line_flip_count",
    "line_age_minutes",
    "prior_retouch_count",
    "minutes_since_prior_retouch",
}


def _truthy(series: pd.Series) -> pd.Series:
    return series.astype("string").str.lower().isin(("true", "1", "yes", "y"))


def period_stem(pair: str, start: dt.datetime, end: dt.datetime) -> str:
    return f"{pair}_{start:%Y%m%d}_{end:%Y%m%d}"


def candidate_source_path(
    pair: str,
    start: dt.datetime,
    end: dt.datetime,
    output_dir: Path | None = None,
) -> Path:
    folder = Path(output_dir or tk.folder_path)
    stem = (
        f"{pair}_{start:%Y%m%d}_{end:%Y%m%d}"
        "_m5line60_range6x3_rr1.2_sp0.8_60m"
    )
    return folder / f"resistance_sweep_candidates_{stem}.csv"


def s5_source_path(
    pair: str,
    start: dt.datetime,
    end: dt.datetime,
    output_dir: Path | None = None,
) -> Path:
    folder = Path(output_dir or tk.folder_path)
    return folder / (
        f"s5_{pair}_{start:%Y%m%d%H%M%S}_{end:%Y%m%d%H%M%S}.csv"
    )


def file_stat(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "path": str(path.resolve()),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def archive_file(path: Path) -> Path | None:
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


def atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    def json_safe(value: Any) -> Any:
        if isinstance(value, Mapping):
            return {str(key): json_safe(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [json_safe(item) for item in value]
        if isinstance(value, np.generic):
            return json_safe(value.item())
        if value is pd.NA or value is pd.NaT:
            return None
        if isinstance(value, float) and not math.isfinite(value):
            return None
        return value

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            json_safe(payload),
            ensure_ascii=False,
            indent=2,
            default=str,
            allow_nan=False,
        ),
        encoding="utf-8",
    )
    _replace_with_retry(temporary, path)


def atomic_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_csv(temporary, index=False, encoding="utf-8-sig")
    _replace_with_retry(temporary, path)


def _replace_with_retry(
    source: Path,
    destination: Path,
    *,
    attempts: int = 20,
    delay_seconds: float = 0.15,
) -> None:
    """Tolerate short OneDrive/antivirus locks around an atomic replace."""
    last_error: OSError | None = None
    for _attempt in range(attempts):
        try:
            source.replace(destination)
            return
        except OSError as error:
            last_error = error
            time.sleep(delay_seconds)
    assert last_error is not None
    raise last_error


def progress_path(
    output_dir: Path,
    pair: str,
    train_start: dt.datetime,
    train_end: dt.datetime,
    oos_start: dt.datetime,
    oos_end: dt.datetime,
) -> Path:
    return output_dir / (
        f"{FLIP_VERSION}_progress_{pair}_{train_start:%Y%m%d}_{train_end:%Y%m%d}"
        f"_to_{oos_start:%Y%m%d}_{oos_end:%Y%m%d}.json"
    )


def write_progress(
    path: Path,
    *,
    pair: str,
    status: str,
    phase: str,
    current_row: int = 0,
    total_rows: int = 0,
    current_time: Any = None,
    started: float,
    error: str | None = None,
) -> dict[str, Any]:
    elapsed = time.monotonic() - started
    payload = {
        "version": FLIP_VERSION,
        "pair": pair,
        "pid": os.getpid(),
        "status": status,
        "phase": phase,
        "current_row": int(current_row),
        "total_rows": int(total_rows),
        "progress_percent": (
            round(100.0 * current_row / total_rows, 3) if total_rows else None
        ),
        "current_time": (
            pd.Timestamp(current_time).isoformat(" ")
            if current_time is not None and not pd.isna(current_time)
            else None
        ),
        "elapsed_minutes": round(elapsed / 60.0, 2),
        "updated_at": dt.datetime.now().astimezone().isoformat(
            timespec="seconds"
        ),
        "error": error,
    }
    try:
        atomic_json(path, payload)
    except OSError as error:
        # Progress is observational.  A transient sync-client lock must never
        # invalidate the causal analysis or its final result files.
        print(
            "[PROGRESS] update skipped after retries: "
            f"{type(error).__name__}: {error}"
        )
    return payload


def load_candidates(
    source: Path,
    *,
    pair: str,
    start: dt.datetime,
    end: dt.datetime,
    max_rows: int | None = None,
    chunksize: int = 20_000,
) -> pd.DataFrame:
    if not source.is_file():
        raise FileNotFoundError(f"flip_predict candidate source not found: {source}")
    header = set(pd.read_csv(source, nrows=0).columns)
    missing = SOURCE_COLUMNS.difference(header)
    if missing:
        raise ValueError(
            "flip_predict candidate source is missing columns: "
            + ", ".join(sorted(missing))
        )
    frames: list[pd.DataFrame] = []
    rows_read = 0
    available_columns = (SOURCE_COLUMNS | OPTIONAL_SOURCE_COLUMNS).intersection(
        header
    )
    reader = pd.read_csv(
        source,
        usecols=lambda column: column in available_columns,
        chunksize=chunksize,
        low_memory=False,
    )
    for chunk in reader:
        if max_rows is not None:
            remaining = max_rows - rows_read
            if remaining <= 0:
                break
            chunk = chunk.iloc[:remaining].copy()
        rows_read += len(chunk)
        decision = pd.to_datetime(chunk["decision_time"], errors="coerce")
        mask = (
            chunk["pair"].astype(str).str.upper().eq(pair)
            & decision.ge(pd.Timestamp(start))
            & decision.lt(pd.Timestamp(end))
            & _truthy(chunk["counterfactual_candidates"])
            & _truthy(chunk["target_valid"])
            & _truthy(chunk["fc2_valid"])
        )
        work = chunk.loc[mask].copy()
        if work.empty:
            continue
        work["decision_time"] = pd.to_datetime(
            work["decision_time"], errors="raise"
        )
        work["next_count2_time"] = pd.to_datetime(
            work["next_count2_time"], errors="coerce"
        )
        for column in NUMERIC_SOURCE_COLUMNS:
            work[column] = pd.to_numeric(work[column], errors="coerce")
        work = work[
            work["peak_count"].eq(2)
            & work["peak_direction"].isin((-1, 1))
            & work["trade_direction"].isin((-1, 1))
            & work["trade_direction"].eq(-work["peak_direction"])
            & work["line_price"].notna()
            & work["recent_m5_avg_range_pips"].gt(0)
        ]
        # dirs_grouped is stored newest-first; its first sign is the newest
        # constituent peak direction.  Historical support/resistance labels
        # are deliberately not order filters for this predicted role change.
        newest_group = pd.to_numeric(
            work["line_source_directions"]
            .astype("string")
            .str.split("|", regex=False)
            .str[0],
            errors="coerce",
        )
        work["line_latest_constituent_peak_direction"] = np.sign(newest_group)
        work = work[
            work["line_latest_constituent_peak_direction"].eq(
                -work["peak_direction"]
            )
        ].copy()
        if work.empty:
            continue
        decision = work["decision_time"]
        causal_specs = (
            ("target_source_last_time", pd.Timedelta(minutes=5)),
            ("fc2_source_last_time", pd.Timedelta(minutes=5)),
            ("h1_pair_source_last_time", pd.Timedelta(hours=1)),
            ("line_newest_source_time", pd.Timedelta(minutes=5)),
            ("line_latest_touch_time", pd.Timedelta(minutes=5)),
            ("line_latest_flip_time", pd.Timedelta(minutes=5)),
        )
        required_causal_columns = {
            "target_source_last_time",
            "fc2_source_last_time",
            "h1_pair_source_last_time",
            "line_newest_source_time",
        }
        for column, completion in causal_specs:
            source_time = pd.to_datetime(
                work[column], format="mixed", errors="coerce"
            )
            missing_required = (
                source_time.isna()
                if column in required_causal_columns
                else pd.Series(False, index=work.index)
            )
            if missing_required.any():
                bad = work.loc[
                    missing_required, ["event_id", "decision_time", column]
                ].iloc[0]
                reader.close()
                raise ValueError(
                    f"missing causal feature in {source.name}: {bad.to_dict()}"
                )
            future = source_time.notna() & (source_time + completion > decision)
            if future.any():
                bad = work.loc[future, ["event_id", "decision_time", column]].iloc[0]
                reader.close()
                raise ValueError(
                    f"future feature in {source.name}: {bad.to_dict()}"
                )
        # Recency of the line's most recent resistance/support role flip.
        # Missing (never flipped, line_flip_count == 0) is preserved as NaN
        # here and becomes the "missing" bucket in add_feature_buckets --
        # distinct from, and not to be confused with, a flip that merely
        # happened a long time ago.
        flip_time = pd.to_datetime(
            work["line_latest_flip_time"], format="mixed", errors="coerce"
        )
        work["minutes_since_line_flip"] = (
            (decision - flip_time).dt.total_seconds() / 60.0
        )
        frames.append(work)
        if max_rows is not None and rows_read >= max_rows:
            break
    reader.close()
    if not frames:
        raise ValueError(f"no eligible flip_predict candidates in {source}")
    result = pd.concat(frames, ignore_index=True)
    result.sort_values(
        ["decision_time", "event_id", "distance_rank", "line_price"],
        inplace=True,
        kind="stable",
    )
    result.reset_index(drop=True, inplace=True)
    # Derived strength metrics.  Absolute strength columns are dominated by
    # point masses (line_core_count is 1 for 76-82% of candidates), so these
    # ask different questions that the raw columns cannot express.
    core_strength = pd.to_numeric(
        result["line_core_total_strength"], errors="coerce"
    )
    total_strength = pd.to_numeric(
        result["line_total_strength"], errors="coerce"
    ).replace(0, np.nan)
    # What share of this line's strength comes from repeat-touch core peaks
    # rather than incidental ones?  1.0 means every constituent peak is core.
    result["line_core_strength_ratio"] = core_strength / total_strength
    # How strong is this line compared with the other lines competing at the
    # same event?  Cross-sectional within one decision, so it stays causal:
    # every line in the group is already known at that decision_time.
    event_median = result.groupby("event_id")["line_total_strength"].transform(
        "median"
    )
    result["line_relative_total_strength"] = total_strength / pd.to_numeric(
        event_median, errors="coerce"
    ).replace(0, np.nan)
    result["source_role"] = [
        expected_role(value)
        for value in result["line_latest_constituent_peak_direction"]
    ]
    result["predicted_role"] = [
        expected_role(value) for value in result["peak_direction"]
    ]
    return add_feature_buckets(result, pair=pair)


def load_path_inspector(
    s5_source: Path,
    *,
    pair_name: str,
    start: dt.datetime,
    end: dt.datetime,
    spread_pips: float,
    position_horizon_minutes: int,
    min_width_pips: float,
    risk_yen: float,
    profit_lock_enabled: bool,
    profit_lock_min_tp_pips: float,
    profit_lock_trigger_tp_fraction: float,
    profit_lock_result_pips: float,
    profit_lock_result_tp_fraction: float | None = None,
) -> tuple[FlipPathInspector, dict[str, Any]]:
    if not s5_source.is_file():
        raise FileNotFoundError(f"flip_predict S5 source not found: {s5_source}")
    pair = gene.currency_pair(pair_name)
    inspector, metadata = _load_typed_s5_inspector(s5_source, pair)
    inspector = _bound_inspector_before(inspector, pd.Timestamp(end))
    coverage_args = SimpleNamespace(start=start, end=end)
    errors = _s5_coverage_errors(inspector.times, coverage_args)
    if errors:
        raise ValueError("S5 coverage errors: " + " | ".join(errors))
    return (
        FlipPathInspector(
            inspector,
            pair,
            period_end_exclusive=pd.Timestamp(end),
            spread_pips=spread_pips,
            position_horizon_minutes=position_horizon_minutes,
            min_width_pips=min_width_pips,
            risk_yen=risk_yen,
            profit_lock_enabled=profit_lock_enabled,
            profit_lock_min_tp_pips=profit_lock_min_tp_pips,
            profit_lock_trigger_tp_fraction=(
                profit_lock_trigger_tp_fraction
            ),
            profit_lock_result_pips=profit_lock_result_pips,
            profit_lock_result_tp_fraction=(
                profit_lock_result_tp_fraction
            ),
        ),
        metadata,
    )


def stretch_profit_lock_tier_configs(
    base_configs: Iterable[TierExecutionConfig],
) -> tuple[TierExecutionConfig, ...]:
    """Double the frozen TP (1B -> 2B) while retaining the frozen hard LC."""
    configs = []
    for base in base_configs:
        configs.append(
            TierExecutionConfig(
                tier=base.tier,
                first_rank=base.first_rank,
                last_rank=base.last_rank,
                tp_a=base.tp_a * STRETCH_PROFIT_TARGET_B,
                rr=base.rr * STRETCH_PROFIT_TARGET_B,
                min_range_filter_pips=base.min_range_filter_pips,
            )
        )
    return tuple(configs)


def risk_multiple_profit_lock_inspectors(
    base: FlipPathInspector,
    tier_configs: Iterable[TierExecutionConfig],
    policy: RiskMultipleProfitLock,
) -> dict[str, FlipPathInspector]:
    """Clone ``base`` once per tier with that tier's raised-stop fractions.

    The path inspector expresses the lock as fractions of take-profit, but
    the policy is written in R.  Tiers pick their own RR, so the same R
    levels land on different fractions and each tier needs its own clone.
    Cloning per tier (not per trade) keeps the one-off gap indexing cheap.
    """
    inspectors: dict[str, FlipPathInspector] = {}
    for config in tier_configs:
        if policy.trigger_r >= config.rr:
            # The RR floor is advisory: when no TP/LC cell reaches it, a tier
            # can end up with an RR at or below the trigger, where the lock
            # could only arm after the take-profit had already closed the
            # trade.  Leave that tier unlocked rather than failing the run;
            # the caller records which tiers actually received the lock.
            continue
        trigger_fraction, result_fraction = policy.fractions_for_rr(config.rr)
        inspectors[config.tier] = FlipPathInspector(
            base.inspector,
            base.pair,
            period_end_exclusive=base.period_end,
            spread_pips=base.spread_pips,
            position_horizon_minutes=base.position_horizon_minutes,
            min_width_pips=base.min_width_pips,
            risk_yen=base.risk_yen,
            profit_lock_enabled=True,
            profit_lock_min_tp_pips=base.min_width_pips,
            profit_lock_trigger_tp_fraction=trigger_fraction,
            # Ignored while the event-relative result fraction is present.
            profit_lock_result_pips=1.0,
            profit_lock_result_tp_fraction=result_fraction,
        )
    return inspectors


def stretch_profit_lock_inspector(
    base: FlipPathInspector,
) -> FlipPathInspector:
    """Clone an inspector for 2B TP / 1.2B arm / +1B raised-stop paths."""
    return FlipPathInspector(
        base.inspector,
        base.pair,
        period_end_exclusive=base.period_end,
        spread_pips=base.spread_pips,
        position_horizon_minutes=base.position_horizon_minutes,
        min_width_pips=base.min_width_pips,
        risk_yen=base.risk_yen,
        profit_lock_enabled=True,
        profit_lock_min_tp_pips=base.min_width_pips,
        profit_lock_trigger_tp_fraction=(
            STRETCH_PROFIT_TRIGGER_TP_FRACTION
        ),
        # Ignored when the event-relative result fraction is present.
        profit_lock_result_pips=1.0,
        profit_lock_result_tp_fraction=(
            STRETCH_PROFIT_LOCK_TP_FRACTION
        ),
    )


class PerformanceAccumulator:
    def __init__(self) -> None:
        self.candidates = 0
        self.fills = 0
        self.trades = 0
        self.wins = 0
        self.losses = 0
        self.profit_locks = 0
        self.sum_win_pips = 0.0
        self.sum_loss_pips = 0.0
        self.sum_pips = 0.0
        self.sum_a = 0.0
        self.sum_yen = 0.0
        self.sum_yen_sq = 0.0
        self.gross_profit_yen = 0.0
        self.gross_loss_yen = 0.0
        self.month_yen: dict[str, float] = defaultdict(float)
        self.period_yen: dict[int, float] = defaultdict(float)

    def add_candidate(self, path: Mapping[str, Any]) -> None:
        self.candidates += 1
        self.fills += int(bool(path.get("order_filled")))

    def add_outcome(
        self,
        outcome: Mapping[str, Any],
        month: str,
        period_index: int | None = None,
        average_range_pips: float | None = None,
    ) -> None:
        pips = float(outcome["trade_result_pips"])
        yen = float(outcome["result_yen"])
        self.trades += 1
        self.profit_locks += int(outcome.get("trade_result") == "profit_lock")
        self.sum_pips += pips
        if average_range_pips is not None:
            average = float(average_range_pips)
            if math.isfinite(average) and average > 0:
                self.sum_a += pips / average
        self.sum_yen += yen
        self.sum_yen_sq += yen * yen
        self.month_yen[month] += yen
        if period_index is not None:
            self.period_yen[int(period_index)] += yen
        if pips > 0:
            self.wins += 1
            self.sum_win_pips += pips
        elif pips < 0:
            self.losses += 1
            self.sum_loss_pips += pips
        if yen > 0:
            self.gross_profit_yen += yen
        elif yen < 0:
            self.gross_loss_yen += -yen

    def row(self, *, period_count: int = 0) -> dict[str, Any]:
        positive_months = sum(value > 0 for value in self.month_yen.values())
        active_months = len(self.month_yen)
        period_values = [
            float(self.period_yen.get(index, 0.0))
            for index in range(period_count)
        ]
        positive_period_values = [value for value in period_values if value > 0]
        positive_period_profit = sum(positive_period_values)
        avg_yen_per_trade = self.sum_yen / self.trades if self.trades else 0.0
        if self.trades > 1:
            yen_variance = max(
                0.0,
                (self.sum_yen_sq - self.trades * avg_yen_per_trade ** 2)
                / (self.trades - 1),
            )
            yen_per_trade_sample_std = math.sqrt(yen_variance)
            yen_per_trade_standard_error = yen_per_trade_sample_std / math.sqrt(
                self.trades
            )
        else:
            yen_per_trade_sample_std = 0.0
            yen_per_trade_standard_error = 0.0
        yen_per_trade_z = (
            avg_yen_per_trade / yen_per_trade_standard_error
            if yen_per_trade_standard_error > 0
            else 0.0
        )
        return {
            "candidate_count": self.candidates,
            "order_fill_count": self.fills,
            "order_fill_rate": (
                self.fills / self.candidates if self.candidates else 0.0
            ),
            "completed_trade_count": self.trades,
            "win_count": self.wins,
            "profit_lock_count": self.profit_locks,
            "profit_lock_rate": (
                self.profit_locks / self.trades if self.trades else 0.0
            ),
            "win_rate": self.wins / self.trades if self.trades else 0.0,
            "average_win_pips": (
                self.sum_win_pips / self.wins if self.wins else 0.0
            ),
            "average_loss_pips": (
                self.sum_loss_pips / self.losses
                if self.losses
                else 0.0
            ),
            "sum_pips": self.sum_pips,
            "sum_a": self.sum_a,
            "gross_profit_yen": self.gross_profit_yen,
            "gross_loss_yen": self.gross_loss_yen,
            "sum_yen": self.sum_yen,
            "avg_yen_per_trade": avg_yen_per_trade,
            "yen_per_trade_sample_std": yen_per_trade_sample_std,
            "yen_per_trade_standard_error": yen_per_trade_standard_error,
            "yen_per_trade_z": yen_per_trade_z,
            "profit_factor_yen": (
                self.gross_profit_yen / self.gross_loss_yen
                if self.gross_loss_yen
                else (math.inf if self.gross_profit_yen else 0.0)
            ),
            "active_month_count": active_months,
            "positive_month_count": positive_months,
            "positive_month_rate": (
                positive_months / active_months if active_months else 0.0
            ),
            "worst_month_yen": min(self.month_yen.values(), default=0.0),
            "period_yen_json": json.dumps(period_values),
            "positive_period_count": len(positive_period_values),
            "max_positive_period_profit_share": (
                max(positive_period_values) / positive_period_profit
                if positive_period_profit
                else 0.0
            ),
        }


def four_period_index(
    timestamp: pd.Timestamp,
    period_start: dt.datetime,
    period_end: dt.datetime,
) -> int:
    start = pd.Timestamp(period_start)
    end = pd.Timestamp(period_end)
    current = pd.Timestamp(timestamp)
    if not start <= current < end:
        raise ValueError("trade timestamp is outside the analysis period")
    fraction = (current - start) / (end - start)
    return min(3, max(0, int(float(fraction) * 4.0)))


def four_period_metrics(
    trades: pd.DataFrame,
    period_start: dt.datetime,
    period_end: dt.datetime,
) -> dict[str, Any]:
    values = [0.0, 0.0, 0.0, 0.0]
    if not trades.empty:
        fills = pd.to_datetime(trades["fill_time"], errors="coerce")
        yen = pd.to_numeric(trades["result_yen"], errors="coerce")
        for timestamp, result_yen_value in zip(fills, yen):
            if pd.isna(timestamp) or pd.isna(result_yen_value):
                continue
            index = four_period_index(timestamp, period_start, period_end)
            values[index] += float(result_yen_value)
    positive = [value for value in values if value > 0]
    positive_total = sum(positive)
    return {
        "period_yen_json": json.dumps(values),
        "positive_period_count": len(positive),
        "max_positive_period_profit_share": (
            max(positive) / positive_total if positive_total else 0.0
        ),
    }


def range_filter_mask(
    frame: pd.DataFrame,
    minimum_fraction_pips: float,
) -> pd.Series:
    average = pd.to_numeric(
        frame["recent_m5_avg_range_pips"], errors="coerce"
    )
    return average.mul(RANGE_FILTER_FRACTION_A).add(1e-12).ge(
        float(minimum_fraction_pips)
    )


def target_distance_filter_mask(
    frame: pd.DataFrame,
    minimum_distance_pips: float,
) -> pd.Series:
    """Keep lines at least the fixed decision-time distance away."""
    minimum = float(minimum_distance_pips)
    if not np.isfinite(minimum) or minimum < 0:
        raise ValueError("minimum target distance must be finite and non-negative")
    distance = pd.to_numeric(frame["distance_pips"], errors="coerce")
    return distance.add(1e-9).ge(minimum)


def _notice_progress(
    notify: Notice | None,
    *,
    pair: str,
    phase: str,
    reached_time: pd.Timestamp,
    current_row: int,
    total_rows: int,
    started: float,
) -> None:
    if notify is None:
        return
    elapsed = (time.monotonic() - started) / 60.0
    notify(
        "\n".join(
            (
                f"{pair} flip_predict inspection progress",
                f"- phase: {phase}",
                f"- reached: {reached_time:%Y-%m-%d %H:%M:%S}",
                f"- row: {current_row}/{total_rows}",
                f"- elapsed: {elapsed:.2f} minutes",
            )
        )
    )


def scan_global_grid(
    frame: pd.DataFrame,
    inspector: FlipPathInspector,
    path_configs: Iterable[FlipPathConfig],
    trade_combos: Iterable[TradeCombo],
    range_filter_pips_values: Iterable[float],
    *,
    pair: str,
    phase: str,
    period_start: dt.datetime,
    period_end: dt.datetime,
    progress_file: Path,
    started: float,
    notify: Notice | None,
) -> pd.DataFrame:
    path_configs = tuple(path_configs)
    trade_combos = tuple(trade_combos)
    filter_values = tuple(
        sorted({float(value) for value in range_filter_pips_values})
    )
    if not filter_values or any(
        not math.isfinite(value) or value < 0 for value in filter_values
    ):
        raise ValueError("range filter grid must contain finite non-negative values")
    states = {
        (config.config_id, combo.combo_id, filter_value): {
            "accumulator": PerformanceAccumulator(),
            "locked_until": pd.NaT,
            "source_event_count": 0,
            "selected_lifecycle_count": 0,
            "replaced_before_fill_count": 0,
            "skipped_while_locked_count": 0,
            "pending_order_lock_count": 0,
        }
        for config in path_configs
        for combo in trade_combos
        for filter_value in filter_values
    }
    # Global execution settings must be selected on the same one-active-flip
    # lifecycle used by the final replay, not on impossible overlapping lines.
    event_frame = (
        frame.sort_values(
            ["decision_time", "event_id", "distance_rank", "distance_pips"],
            kind="stable",
        )
        .groupby("event_id", sort=False, as_index=False)
        .head(1)
        .reset_index(drop=True)
    )
    total = len(event_frame)
    next_notice = pd.Timestamp(period_start) + pd.DateOffset(months=2)
    for row_number, row in enumerate(event_frame.itertuples(index=False), start=1):
        decision_time = pd.Timestamp(row.decision_time)
        available_range_pips = (
            float(row.recent_m5_avg_range_pips) * RANGE_FILTER_FRACTION_A
        )
        for config in path_configs:
            active_filters_by_combo: dict[str, list[float]] = {}
            for combo in trade_combos:
                active_filters = []
                for filter_value in filter_values:
                    if available_range_pips + 1e-12 < filter_value:
                        continue
                    state = states[
                        (config.config_id, combo.combo_id, filter_value)
                    ]
                    state["source_event_count"] += 1
                    if (
                        pd.isna(state["locked_until"])
                        or decision_time >= state["locked_until"]
                    ):
                        active_filters.append(filter_value)
                    else:
                        state["skipped_while_locked_count"] += 1
                if active_filters:
                    active_filters_by_combo[combo.combo_id] = active_filters
            active_combos = [
                combo
                for combo in trade_combos
                if combo.combo_id in active_filters_by_combo
            ]
            if not active_combos:
                continue
            path = inspector.inspect(
                decision_time=decision_time,
                line_price=float(row.line_price),
                order_direction=int(row.trade_direction),
                average_range_pips=float(row.recent_m5_avg_range_pips),
                path_config=config,
                trade_combos=active_combos,
                next_count2_time=row.next_count2_time,
            )
            for combo in active_combos:
                for filter_value in active_filters_by_combo[combo.combo_id]:
                    state = states[
                        (config.config_id, combo.combo_id, filter_value)
                    ]
                    accumulator = state["accumulator"]
                    state["selected_lifecycle_count"] += 1
                    accumulator.add_candidate(path)
                    if path.get("replaced_before_fill"):
                        state["replaced_before_fill_count"] += 1
                    if not path.get("order_filled"):
                        pending_end = pd.to_datetime(
                            path.get("order_deadline"), errors="coerce"
                        )
                        if (
                            not pd.isna(pending_end)
                            and pending_end > decision_time
                        ):
                            state["locked_until"] = pending_end
                            state["pending_order_lock_count"] += 1
                        continue
                    if path.get("path_status") != "trade":
                        lock_deadline = pd.to_datetime(
                            path.get("position_horizon_end"), errors="coerce"
                        )
                        if not pd.isna(lock_deadline):
                            state["locked_until"] = lock_deadline
                        continue
                    outcome = path["outcomes"].get(combo.combo_id)
                    if outcome is not None:
                        fill_time = pd.Timestamp(path["fill_time"])
                        accumulator.add_outcome(
                            outcome,
                            fill_time.strftime("%Y-%m"),
                            four_period_index(
                                fill_time, period_start, period_end
                            ),
                            average_range_pips=float(
                                row.recent_m5_avg_range_pips
                            ),
                        )
                        exit_effective_time = pd.to_datetime(
                            outcome.get("exit_effective_time"), errors="coerce"
                        )
                        if pd.isna(exit_effective_time):
                            exit_time = pd.to_datetime(
                                outcome.get("exit_time"), errors="coerce"
                            )
                            if not pd.isna(exit_time):
                                exit_effective_time = exit_time + pd.Timedelta(
                                    seconds=5
                                )
                        if not pd.isna(exit_effective_time):
                            state["locked_until"] = exit_effective_time
                    else:
                        horizon_end = pd.to_datetime(
                            path.get("position_horizon_end"), errors="coerce"
                        )
                        if not pd.isna(horizon_end):
                            state["locked_until"] = horizon_end
        while decision_time >= next_notice:
            _notice_progress(
                notify,
                pair=pair,
                phase=phase,
                reached_time=next_notice,
                current_row=row_number,
                total_rows=total,
                started=started,
            )
            next_notice += pd.DateOffset(months=2)
        if row_number == 1 or row_number % 500 == 0:
            write_progress(
                progress_file,
                pair=pair,
                status="running",
                phase=phase,
                current_row=row_number,
                total_rows=total,
                current_time=decision_time,
                started=started,
            )
    rows = []
    for config in path_configs:
        for combo in trade_combos:
            for filter_value in filter_values:
                state = states[
                    (config.config_id, combo.combo_id, filter_value)
                ]
                rows.append(
                    {
                        "path_config_id": config.config_id,
                        "order_wait_minutes": config.order_wait_minutes,
                        "replace_unfilled_on_next_count2": (
                            config.replace_unfilled_on_next_count2
                        ),
                        "combo_id": combo.combo_id,
                        "tp_a": combo.tp_a,
                        "lc_a": combo.lc_a,
                        "configured_rr": combo.configured_rr,
                        "range_filter_fraction_a": RANGE_FILTER_FRACTION_A,
                        "min_range_filter_pips": filter_value,
                        "equivalent_minimum_a_pips": (
                            filter_value / RANGE_FILTER_FRACTION_A
                        ),
                        **state["accumulator"].row(period_count=4),
                        "source_event_count": state["source_event_count"],
                        "selected_lifecycle_count": state[
                            "selected_lifecycle_count"
                        ],
                        "replaced_before_fill_count": state[
                            "replaced_before_fill_count"
                        ],
                        "skipped_while_locked_count": state[
                            "skipped_while_locked_count"
                        ],
                        "pending_order_lock_count": state[
                            "pending_order_lock_count"
                        ],
                    }
                )
    return pd.DataFrame(rows)


def choose_global_policy(
    summary: pd.DataFrame,
    *,
    minimum_trades: int = 100,
    minimum_rr: float = 0.0,
) -> pd.Series:
    """Pick one TP/LC cell, preferring stability then total yen.

    ``minimum_rr`` drops cells whose configured reward/risk falls below the
    floor before any stage runs.  Ranking by ``sum_yen`` alone tends to
    settle near RR 1.0, which needs a high win rate to stay profitable; a
    floor buys a wider TP relative to LC at some cost in total yen.  If no
    cell clears the floor it is ignored rather than failing, so a pair whose
    grid cannot reach the requested RR still gets a policy.
    """
    if minimum_rr > 0 and "configured_rr" in summary.columns:
        above_floor = summary.loc[
            pd.to_numeric(summary["configured_rr"], errors="coerce")
            .add(1e-12)
            .ge(minimum_rr)
        ]
        if not above_floor.empty:
            summary = above_floor
    stages = (
        (
            "strict_stability",
            summary["completed_trade_count"].ge(minimum_trades)
            & summary["sum_yen"].gt(0)
            & summary["profit_factor_yen"].ge(1.1)
            & summary["positive_period_count"].ge(3)
            & summary["max_positive_period_profit_share"].le(0.60),
        ),
        (
            "relaxed_pf",
            summary["completed_trade_count"].ge(minimum_trades)
            & summary["sum_yen"].gt(0)
            & summary["profit_factor_yen"].ge(1.0)
            & summary["positive_period_count"].ge(3)
            & summary["max_positive_period_profit_share"].le(0.60),
        ),
        (
            "positive_minimum_trades",
            summary["completed_trade_count"].ge(minimum_trades)
            & summary["sum_yen"].gt(0),
        ),
        (
            "minimum_trades_only",
            summary["completed_trade_count"].ge(minimum_trades),
        ),
        ("unrestricted_fallback", pd.Series(True, index=summary.index)),
    )
    for stage, mask in stages:
        eligible = summary.loc[mask].copy()
        if eligible.empty:
            continue
        selected = eligible.sort_values(
            [
                "sum_yen",
                "positive_period_count",
                "profit_factor_yen",
                "max_positive_period_profit_share",
                "sum_pips",
                "min_range_filter_pips",
                "lc_a",
            ],
            ascending=[False, False, False, True, False, True, True],
            kind="stable",
        ).iloc[0].copy()
        selected["selection_stage"] = stage
        return selected
    raise ValueError("global grid is empty")


PATH_EXPORT_COLUMNS = (
    "path_status",
    "approach_direction",
    "signal_order_direction",
    "order_direction",
    "order_filled",
    "order_deadline",
    "replaced_before_fill",
    "watch_entry_enabled",
    "watch_order_name",
    "watch_entry_mode",
    "watch_initial_touch_deadline",
    "watch_line_touch_time",
    "watch_line_touch_known_time",
    "watch_observation_known_time",
    "watch_order_placed_time",
    "watch_order_release_time",
    "watch_observation_close",
    "watch_observation_high",
    "watch_observation_low",
    "watch_breakout_direction",
    "watch_breakout_distance_pips",
    "watch_breakout_distance_a",
    "watch_observed_extreme_price",
    "watch_entry_trigger_price",
    "watch_actual_entry_distance_from_line_a",
    "watch_entry_gap_from_trigger_a",
    "watch_chase_filtered",
    "watch_entry_gap_filtered",
    "watch_stop_fill_bar_adverse_censored",
    "fill_time",
    "fill_delay_from_decision_seconds",
    "fill_at_bar_open",
    "position_path_complete",
    "position_horizon_end",
)

OUTCOME_EXPORT_COLUMNS = (
    "combo_id",
    "tp_a",
    "lc_a",
    "configured_rr",
    "effective_rr",
    "tp_pips",
    "lc_pips",
    "original_tp_first_reached_time",
    "original_tp_known_from",
    "minutes_to_original_tp",
    "original_lc_first_reached_time",
    "original_lc_known_from",
    "minutes_to_original_lc",
    "counterfactual_horizon_original_tp_reached",
    "counterfactual_horizon_original_tp_first_reached_time",
    "counterfactual_horizon_minutes_to_original_tp",
    "counterfactual_horizon_original_lc_reached",
    "counterfactual_horizon_original_lc_first_reached_time",
    "counterfactual_horizon_minutes_to_original_lc",
    "half_tp_trigger_fraction",
    "half_tp_trigger_pips",
    "half_tp_reached",
    "half_tp_first_reached_time",
    "half_tp_known_from",
    "minutes_to_half_tp",
    "counterfactual_horizon_half_tp_reached",
    "counterfactual_horizon_half_tp_first_reached_time",
    "counterfactual_horizon_minutes_to_half_tp",
    "fill_bar_half_tp_ambiguous",
    "profit_lock_enabled",
    "profit_lock_min_tp_pips",
    "profit_lock_trigger_tp_fraction",
    "profit_lock_trigger_pips",
    "profit_lock_result_pips",
    "profit_lock_result_tp_fraction",
    "profit_lock_effective_result_pips",
    "profit_lock_trigger_reached",
    "counterfactual_horizon_profit_lock_trigger_reached",
    "profit_lock_activated",
    "profit_lock_active_from",
    "profit_lock_exit_at_bar_open",
    "profit_lock_slippage_pips",
    "original_lc_exit_at_bar_open",
    "original_lc_slippage_pips",
    "timed_half_lc_config_id",
    "timed_half_lc_enabled",
    "timed_half_lc_trigger_minutes",
    "timed_half_lc_fraction",
    "timed_half_lc_timer_anchor",
    "timed_half_lc_check_time",
    "timed_half_lc_checkpoint_evaluable",
    "timed_half_lc_position_open_at_checkpoint",
    "half_tp_reached_before_timed_checkpoint",
    "max_favorable_before_timed_checkpoint_pips",
    "max_adverse_before_timed_checkpoint_pips",
    "timed_half_lc_activated",
    "timed_half_lc_suppressed_by_fill_bar_ambiguity",
    "timed_half_lc_active_from",
    "timed_half_lc_requested_pips",
    "timed_half_lc_effective_pips",
    "timed_half_lc_price",
    "timed_half_lc_activation_open_pips",
    "timed_half_lc_activation_already_breached",
    "half_tp_reached_after_timed_activation",
    "counterfactual_half_tp_reached_after_timed_activation",
    "timed_half_lc_exit",
    "timed_half_lc_exit_mode",
    "timed_half_lc_exit_at_bar_open",
    "timed_half_lc_exit_time",
    "timed_half_lc_slippage_pips",
    "line_wick_lc_config_id",
    "line_wick_lc_enabled",
    "line_wick_lc_width_a",
    "line_wick_lc_requested_pips",
    "line_wick_lc_effective_pips",
    "line_wick_lc_price",
    "line_wick_lc_reached",
    "counterfactual_horizon_line_wick_lc_reached",
    "line_wick_lc_exit",
    "line_wick_lc_exit_mode",
    "line_wick_lc_exit_at_bar_open",
    "line_wick_lc_exit_time",
    "line_wick_lc_same_s5_tp_assumed_first",
    "line_wick_lc_slippage_pips",
    "trade_result",
    "trade_result_pips",
    "result_r",
    "result_yen",
    "exit_time",
    "exit_effective_time",
    "minutes_from_fill_to_exit",
    "minutes_from_timed_activation_to_exit",
    "actual_entry_price",
    "actual_exit_price",
    "max_favorable_pips",
    "max_adverse_pips",
    "exit_s5_opposite_extreme_censored",
    "exit_execution_mode",
    *(
        f"early_m{minute}_{metric}"
        for minute in EARLY_PATH_MINUTES
        for metric in EARLY_PATH_METRICS
    ),
)


def inspect_selected_paths(
    frame: pd.DataFrame,
    inspector: FlipPathInspector,
    path_config: FlipPathConfig,
    combo: TradeCombo,
    *,
    pair: str,
    phase: str,
    period_start: dt.datetime,
    progress_file: Path,
    started: float,
    notify: Notice | None,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    total = len(frame)
    next_notice = pd.Timestamp(period_start) + pd.DateOffset(months=2)
    for row_number, row in enumerate(frame.itertuples(index=False), start=1):
        decision_time = pd.Timestamp(row.decision_time)
        path = inspector.inspect(
            decision_time=decision_time,
            line_price=float(row.line_price),
            order_direction=int(row.trade_direction),
            average_range_pips=float(row.recent_m5_avg_range_pips),
            path_config=path_config,
            trade_combos=(combo,),
            next_count2_time=row.next_count2_time,
        )
        output = {column: path.get(column) for column in PATH_EXPORT_COLUMNS}
        output.update({column: np.nan for column in OUTCOME_EXPORT_COLUMNS})
        outcome = path["outcomes"].get(combo.combo_id, {})
        output.update(outcome)
        rows.append(output)
        while decision_time >= next_notice:
            _notice_progress(
                notify,
                pair=pair,
                phase=phase,
                reached_time=next_notice,
                current_row=row_number,
                total_rows=total,
                started=started,
            )
            next_notice += pd.DateOffset(months=2)
        if row_number == 1 or row_number % 500 == 0:
            write_progress(
                progress_file,
                pair=pair,
                status="running",
                phase=phase,
                current_row=row_number,
                total_rows=total,
                current_time=decision_time,
                started=started,
            )
    path_frame = pd.DataFrame(rows)
    result = pd.concat(
        [frame.reset_index(drop=True), path_frame.reset_index(drop=True)], axis=1
    )
    return result


def select_top_ranked_conditions(
    summary: pd.DataFrame,
    tier_configs: Iterable[TierExecutionConfig],
    *,
    limit: int = 15,
    minimum_trades: int = MINIMUM_CONDITION_TRADES,
    minimum_positive_periods: int = CONDITION_MINIMUM_POSITIVE_PERIODS,
) -> tuple[RankedPolicyCondition, ...]:
    """Freeze the top-N lifecycle rules by per-trade edge, excluding ALL.

    Two gates guard against biases from exhaustively searching hundreds of
    candidate conditions on one train period:

    - ``minimum_trades``: a condition needs at least this many completed
      train trades before its average is trusted — a condition with a
      handful of trades and a large total is not a signal, it is noise.
    - ``minimum_positive_periods``: requires ``positive_period_count`` (the
      train period split into four equal chronological quarters, see
      ``four_period_metrics``) already populated on ``summary`` by calling
      ``rank_replay_conditions(..., period_start=..., period_end=...)``.
      This mirrors the same within-train stability bar already used for
      TP/LC tier selection; condition mining previously had no analogous
      check at all. If the column is absent this gate is skipped.

    Ranking is by ``avg_yen_per_trade`` (per-trade expected value), not raw
    ``sum_yen`` — sorting by total otherwise lets a condition with many
    mediocre trades outrank a condition with fewer excellent trades purely
    on volume.

    ``yen_per_trade_z``/``bonferroni_z_threshold`` are available on
    ``summary`` as multiple-testing diagnostics but are intentionally not
    enforced as a hard gate here — see ``count2_flip_core.bonferroni_z_threshold``.
    """
    if limit < 1:
        raise ValueError("top condition limit must be positive")
    if minimum_trades < 1:
        raise ValueError("minimum_trades must be positive")
    if minimum_positive_periods < 0:
        raise ValueError("minimum_positive_periods must be non-negative")
    configs = tuple(tier_configs)
    ranked = summary[~summary["condition_id"].eq("ALL")].copy()
    ranked = ranked[
        pd.to_numeric(ranked["completed_trade_count"], errors="coerce")
        .fillna(0)
        .ge(minimum_trades)
    ]
    if "positive_period_count" in ranked.columns:
        ranked = ranked[
            pd.to_numeric(ranked["positive_period_count"], errors="coerce")
            .fillna(0)
            .ge(minimum_positive_periods)
        ]
    ranked.sort_values(
        [
            "avg_yen_per_trade",
            "positive_month_rate",
            "profit_factor_yen",
            "sum_pips",
            "condition_id",
        ],
        ascending=[False, False, False, False, True],
        inplace=True,
        kind="stable",
    )
    ranked.drop_duplicates("condition_id", keep="first", inplace=True)
    if len(ranked) < limit:
        raise ValueError(
            f"top-{limit} policy requires {limit} distinct non-ALL conditions "
            f"clearing minimum_trades={minimum_trades}/"
            f"minimum_positive_periods={minimum_positive_periods} "
            f"(only {len(ranked)} cleared)"
        )
    selected = []
    for rank, (_, row) in enumerate(ranked.head(limit).iterrows(), start=1):
        selected.append(
            RankedPolicyCondition(
                rank=rank,
                tier=tier_for_rank(rank, configs),
                condition=condition_from_summary(row),
            )
        )
    return tuple(selected)


def attach_bonferroni_diagnostics(
    frame: pd.DataFrame,
    num_candidates: int,
    *,
    alpha: float = CONDITION_MULTIPLE_TESTING_ALPHA,
) -> pd.DataFrame:
    """Report (without filtering on) each condition's multiple-testing bar.

    ``num_candidates`` should be the total number of distinct conditions that
    were exhaustively searched (e.g. ``len(enumerate_conditions(...))``), not
    just the number surviving other gates — the correction must reflect how
    many independent chances there were to find an apparent edge by luck.
    """
    result = frame.copy()
    threshold = bonferroni_z_threshold(num_candidates, alpha=alpha)
    result["bonferroni_num_candidates"] = num_candidates
    result["bonferroni_alpha"] = alpha
    result["bonferroni_z_threshold"] = threshold
    result["clears_bonferroni_bar"] = (
        pd.to_numeric(result.get("yen_per_trade_z"), errors="coerce")
        .abs()
        .ge(threshold)
    )
    return result


def select_top_condition_policy_candidates(
    frame: pd.DataFrame,
    ranked_conditions: Iterable[RankedPolicyCondition],
    tier_configs: Iterable[TierExecutionConfig],
    *,
    minimum_matched_conditions: int = 1,
) -> pd.DataFrame:
    """Apply the frozen top-condition OR and choose one line per FC2 event.

    ``minimum_matched_conditions`` requires that many of the ranked
    conditions to agree before an event is eligible.  The default of 1 is
    the plain OR: any single condition triggers.  Raising it treats
    agreement as confidence -- on AUD_USD's OOS year, events matching one
    condition averaged -14.1 yen while events matching four or more
    averaged +22.1, so a threshold of 3 kept roughly the same total profit
    as cutting to the top three ranks while placing more orders.
    """
    if minimum_matched_conditions < 1:
        raise ValueError("minimum_matched_conditions must be positive")
    conditions = tuple(sorted(ranked_conditions, key=lambda item: item.rank))
    configs = tuple(tier_configs)
    if not conditions:
        raise ValueError("ranked condition policy cannot be empty")
    ranks = [item.rank for item in conditions]
    if ranks != list(range(1, len(conditions) + 1)):
        raise ValueError("ranked conditions must have contiguous ranks from 1")
    if len({item.condition.condition_id for item in conditions}) != len(conditions):
        raise ValueError("ranked condition ids must be unique")
    for item in conditions:
        if tier_for_rank(item.rank, configs) != item.tier:
            raise ValueError("condition tier does not match frozen rank ranges")
    config_by_tier = {config.tier: config for config in configs}
    if len(config_by_tier) != len(configs):
        raise ValueError("tier execution config names must be unique")
    tier_priority = {config.tier: config.first_rank for config in configs}

    result = frame.reset_index(drop=True).copy()
    matched_ids: list[list[str]] = [[] for _ in range(len(result))]
    matched_ranks: list[list[int]] = [[] for _ in range(len(result))]
    for item in conditions:
        positions = np.flatnonzero(condition_mask(result, item.condition))
        for position in positions:
            matched_ids[int(position)].append(item.condition.condition_id)
            matched_ranks[int(position)].append(item.rank)

    result["matched_condition_ids"] = [
        json.dumps(values, ensure_ascii=False) for values in matched_ids
    ]
    result["matched_condition_ranks"] = [
        json.dumps(values) for values in matched_ranks
    ]
    result["matched_condition_count"] = [len(values) for values in matched_ranks]
    highest_rank = [values[0] if values else pd.NA for values in matched_ranks]
    result["highest_matched_rank"] = pd.array(highest_rank, dtype="Int64")
    result["signal_tier"] = [
        tier_for_rank(values[0], configs) if values else pd.NA
        for values in matched_ranks
    ]
    result["minimum_matched_conditions"] = minimum_matched_conditions
    result["top15_or_triggered"] = result["matched_condition_count"].ge(
        minimum_matched_conditions
    )
    result["tier_tp_a"] = result["signal_tier"].map(
        {tier: config.tp_a for tier, config in config_by_tier.items()}
    )
    result["tier_rr"] = result["signal_tier"].map(
        {tier: config.rr for tier, config in config_by_tier.items()}
    )
    result["tier_lc_a"] = result["signal_tier"].map(
        {tier: config.trade_combo.lc_a for tier, config in config_by_tier.items()}
    )
    result["range_filter_fraction_a"] = RANGE_FILTER_FRACTION_A
    result["available_range_filter_pips"] = pd.to_numeric(
        result["recent_m5_avg_range_pips"], errors="coerce"
    ).mul(RANGE_FILTER_FRACTION_A)
    result["tier_min_range_filter_pips"] = result["signal_tier"].map(
        {
            tier: config.min_range_filter_pips
            for tier, config in config_by_tier.items()
        }
    )
    result["range_filter_passed"] = result[
        "available_range_filter_pips"
    ].add(1e-12).ge(result["tier_min_range_filter_pips"])
    result["policy_line_selection"] = "highest_tier_then_nearest_line"
    eligible = result[
        result["top15_or_triggered"] & result["range_filter_passed"]
    ].copy()
    if eligible.empty:
        return eligible

    eligible["_tier_priority"] = eligible["signal_tier"].map(tier_priority)
    if eligible["_tier_priority"].isna().any():
        raise ValueError("triggered candidate has no tier execution config")
    eligible.sort_values(
        [
            "decision_time",
            "event_id",
            "_tier_priority",
            "distance_rank",
            "distance_pips",
            "line_price",
        ],
        inplace=True,
        kind="stable",
    )
    selected = (
        eligible.groupby("event_id", sort=False, as_index=False)
        .head(1)
        .copy()
    )
    selected.drop(columns="_tier_priority", inplace=True)
    return selected.reset_index(drop=True)


def inspect_tiered_paths(
    frame: pd.DataFrame,
    inspector: FlipPathInspector,
    path_config: FlipPathConfig,
    tier_configs: Iterable[TierExecutionConfig],
    *,
    pair: str,
    phase: str,
    period_start: dt.datetime,
    progress_file: Path,
    started: float,
    notify: Notice | None,
    timed_half_lc_config: TimedHalfLcConfig | None = None,
    line_wick_lc_config: LineWickLcConfig | None = None,
    watch_entry_config: FlipWatchEntryConfig | None = None,
    inspectors_by_tier: Mapping[str, FlipPathInspector] | None = None,
) -> pd.DataFrame:
    """Inspect one selected top-15 OR line per event with its tier TP/RR.

    ``inspectors_by_tier`` overrides ``inspector`` per tier, which the
    R-based raised stop needs because its fractions depend on each tier's
    RR.  Tiers absent from the mapping fall back to ``inspector``.
    """
    config_by_tier = {config.tier: config for config in tier_configs}
    timed_config = timed_half_lc_config or TimedHalfLcConfig(None)
    line_wick_config = line_wick_lc_config or LineWickLcConfig(None)
    rows: list[dict[str, Any]] = []
    total = len(frame)
    next_notice = pd.Timestamp(period_start) + pd.DateOffset(months=2)
    for row_number, row in enumerate(frame.itertuples(index=False), start=1):
        decision_time = pd.Timestamp(row.decision_time)
        tier = str(row.signal_tier)
        config = config_by_tier.get(tier)
        if config is None:
            raise ValueError(f"missing execution config for tier {tier}")
        combo = config.trade_combo
        tier_inspector = (
            inspectors_by_tier.get(tier, inspector)
            if inspectors_by_tier
            else inspector
        )
        path = tier_inspector.inspect(
            decision_time=decision_time,
            line_price=float(row.line_price),
            order_direction=int(row.trade_direction),
            average_range_pips=float(row.recent_m5_avg_range_pips),
            path_config=path_config,
            trade_combos=(combo,),
            next_count2_time=row.next_count2_time,
            timed_half_lc_configs=(timed_config,),
            line_wick_lc_configs=(line_wick_config,),
            watch_entry_config=watch_entry_config,
        )
        output = {column: path.get(column) for column in PATH_EXPORT_COLUMNS}
        output.update({column: np.nan for column in OUTCOME_EXPORT_COLUMNS})
        output.update(
            {
                "half_tp_trigger_fraction": timed_config.tp_fraction,
                "timed_half_lc_config_id": timed_config.config_id,
                "timed_half_lc_enabled": timed_config.enabled,
                "timed_half_lc_trigger_minutes": (
                    timed_config.trigger_minutes
                ),
                "timed_half_lc_fraction": timed_config.lc_fraction,
                "line_wick_lc_config_id": line_wick_config.config_id,
                "line_wick_lc_enabled": line_wick_config.enabled,
                "line_wick_lc_width_a": line_wick_config.width_a,
            }
        )
        output.update(
            path["outcomes"].get(
                overlay_outcome_key(combo, timed_config, line_wick_config), {}
            )
        )
        rows.append(output)
        while decision_time >= next_notice:
            _notice_progress(
                notify,
                pair=pair,
                phase=phase,
                reached_time=next_notice,
                current_row=row_number,
                total_rows=total,
                started=started,
            )
            next_notice += pd.DateOffset(months=2)
        if row_number == 1 or row_number % 500 == 0:
            write_progress(
                progress_file,
                pair=pair,
                status="running",
                phase=phase,
                current_row=row_number,
                total_rows=total,
                current_time=decision_time,
                started=started,
            )
    path_frame = pd.DataFrame(
        rows,
        columns=(*PATH_EXPORT_COLUMNS, *OUTCOME_EXPORT_COLUMNS),
    )
    return pd.concat(
        [frame.reset_index(drop=True), path_frame.reset_index(drop=True)], axis=1
    )


def inspect_timed_half_lc_grid_paths(
    frame: pd.DataFrame,
    inspector: FlipPathInspector,
    path_config: FlipPathConfig,
    tier_configs: Iterable[TierExecutionConfig],
    timed_configs: Iterable[TimedHalfLcConfig],
    *,
    pair: str,
    phase: str,
    period_start: dt.datetime,
    progress_file: Path,
    started: float,
    notify: Notice | None,
) -> pd.DataFrame:
    """Inspect every frozen timed-stop overlay once per selected event."""
    config_by_tier = {config.tier: config for config in tier_configs}
    policies = tuple(timed_configs)
    if not policies:
        raise ValueError("timed half-LC grid cannot be empty")
    source_positions: list[int] = []
    rows: list[dict[str, Any]] = []
    total = len(frame)
    next_notice = pd.Timestamp(period_start) + pd.DateOffset(months=2)
    for row_number, row in enumerate(frame.itertuples(index=False), start=1):
        decision_time = pd.Timestamp(row.decision_time)
        tier = str(row.signal_tier)
        tier_config = config_by_tier.get(tier)
        if tier_config is None:
            raise ValueError(f"missing execution config for tier {tier}")
        combo = tier_config.trade_combo
        path = inspector.inspect(
            decision_time=decision_time,
            line_price=float(row.line_price),
            order_direction=int(row.trade_direction),
            average_range_pips=float(row.recent_m5_avg_range_pips),
            path_config=path_config,
            trade_combos=(combo,),
            next_count2_time=row.next_count2_time,
            timed_half_lc_configs=policies,
        )
        for policy in policies:
            output = {column: path.get(column) for column in PATH_EXPORT_COLUMNS}
            output.update({column: np.nan for column in OUTCOME_EXPORT_COLUMNS})
            output.update(
                {
                    "half_tp_trigger_fraction": policy.tp_fraction,
                    "timed_half_lc_config_id": policy.config_id,
                    "timed_half_lc_enabled": policy.enabled,
                    "timed_half_lc_trigger_minutes": policy.trigger_minutes,
                    "timed_half_lc_fraction": policy.lc_fraction,
                }
            )
            outcome = path.get("outcomes", {}).get(
                timed_outcome_key(combo, policy)
            )
            if outcome is not None:
                output.update(outcome)
            elif path.get("order_filled"):
                # Another policy from the same shared S5 inspection may have
                # completed before a gap or period boundary.  Status and
                # locking must remain policy-specific.
                output["path_status"] = "incomplete_position_window"
                output["position_path_complete"] = False
            rows.append(output)
            source_positions.append(row_number - 1)
        while decision_time >= next_notice:
            _notice_progress(
                notify,
                pair=pair,
                phase=phase,
                reached_time=next_notice,
                current_row=row_number,
                total_rows=total,
                started=started,
            )
            next_notice += pd.DateOffset(months=2)
        if row_number == 1 or row_number % 500 == 0:
            write_progress(
                progress_file,
                pair=pair,
                status="running",
                phase=phase,
                current_row=row_number,
                total_rows=total,
                current_time=decision_time,
                started=started,
            )
    if not rows:
        empty_paths = pd.DataFrame(
            columns=(*PATH_EXPORT_COLUMNS, *OUTCOME_EXPORT_COLUMNS)
        )
        return pd.concat(
            [frame.iloc[0:0].copy(), empty_paths], axis=1
        )
    sources = frame.iloc[source_positions].reset_index(drop=True)
    outcomes = pd.DataFrame(
        rows, columns=(*PATH_EXPORT_COLUMNS, *OUTCOME_EXPORT_COLUMNS)
    ).reset_index(drop=True)
    result = pd.concat([sources, outcomes], axis=1)
    expected_rows = len(frame) * len(policies)
    if len(result) != expected_rows:
        raise RuntimeError("timed half-LC grid row-count invariant failed")
    policy_counts = result["timed_half_lc_config_id"].value_counts()
    if any(int(policy_counts.get(policy.config_id, 0)) != len(frame) for policy in policies):
        raise RuntimeError("timed half-LC event universe differs by policy")
    return result


def inspect_line_wick_lc_grid_paths(
    frame: pd.DataFrame,
    inspector: FlipPathInspector,
    path_config: FlipPathConfig,
    tier_configs: Iterable[TierExecutionConfig],
    line_wick_configs: Iterable[LineWickLcConfig],
    *,
    pair: str,
    phase: str,
    period_start: dt.datetime,
    progress_file: Path,
    started: float,
    notify: Notice | None,
    inspectors_by_tier: Mapping[str, FlipPathInspector] | None = None,
) -> pd.DataFrame:
    """Inspect every wick-cross stop width on one shared S5 path.

    ``inspectors_by_tier`` overrides ``inspector`` per tier so the R-based
    raised stop, whose fractions depend on each tier's RR, applies here too.
    """
    config_by_tier = {config.tier: config for config in tier_configs}
    policies = tuple(line_wick_configs)
    if not policies:
        raise ValueError("line-wick LC grid cannot be empty")
    source_positions: list[int] = []
    rows: list[dict[str, Any]] = []
    total = len(frame)
    next_notice = pd.Timestamp(period_start) + pd.DateOffset(months=2)
    for row_number, row in enumerate(frame.itertuples(index=False), start=1):
        decision_time = pd.Timestamp(row.decision_time)
        tier = str(row.signal_tier)
        tier_config = config_by_tier.get(tier)
        if tier_config is None:
            raise ValueError(f"missing execution config for tier {tier}")
        combo = tier_config.trade_combo
        tier_inspector = (
            inspectors_by_tier.get(tier, inspector)
            if inspectors_by_tier
            else inspector
        )
        path = tier_inspector.inspect(
            decision_time=decision_time,
            line_price=float(row.line_price),
            order_direction=int(row.trade_direction),
            average_range_pips=float(row.recent_m5_avg_range_pips),
            path_config=path_config,
            trade_combos=(combo,),
            next_count2_time=row.next_count2_time,
            line_wick_lc_configs=policies,
        )
        for policy in policies:
            output = {column: path.get(column) for column in PATH_EXPORT_COLUMNS}
            output.update({column: np.nan for column in OUTCOME_EXPORT_COLUMNS})
            output.update(
                {
                    "line_wick_lc_config_id": policy.config_id,
                    "line_wick_lc_enabled": policy.enabled,
                    "line_wick_lc_width_a": policy.width_a,
                }
            )
            outcome = path.get("outcomes", {}).get(
                line_wick_outcome_key(combo, policy)
            )
            if outcome is not None:
                output.update(outcome)
            elif path.get("order_filled"):
                output["path_status"] = "incomplete_position_window"
                output["position_path_complete"] = False
            rows.append(output)
            source_positions.append(row_number - 1)
        while decision_time >= next_notice:
            _notice_progress(
                notify,
                pair=pair,
                phase=phase,
                reached_time=next_notice,
                current_row=row_number,
                total_rows=total,
                started=started,
            )
            next_notice += pd.DateOffset(months=2)
        if row_number == 1 or row_number % 500 == 0:
            write_progress(
                progress_file,
                pair=pair,
                status="running",
                phase=phase,
                current_row=row_number,
                total_rows=total,
                current_time=decision_time,
                started=started,
            )
    if not rows:
        empty_paths = pd.DataFrame(
            columns=(*PATH_EXPORT_COLUMNS, *OUTCOME_EXPORT_COLUMNS)
        )
        return pd.concat([frame.iloc[0:0].copy(), empty_paths], axis=1)
    sources = frame.iloc[source_positions].reset_index(drop=True)
    outcomes = pd.DataFrame(
        rows, columns=(*PATH_EXPORT_COLUMNS, *OUTCOME_EXPORT_COLUMNS)
    ).reset_index(drop=True)
    result = pd.concat([sources, outcomes], axis=1)
    expected_rows = len(frame) * len(policies)
    if len(result) != expected_rows:
        raise RuntimeError("line-wick LC grid row-count invariant failed")
    policy_counts = result["line_wick_lc_config_id"].value_counts()
    if any(
        int(policy_counts.get(policy.config_id, 0)) != len(frame)
        for policy in policies
    ):
        raise RuntimeError("line-wick LC event universe differs by policy")
    return result


def inspect_trade_combo_grid_paths(
    frame: pd.DataFrame,
    inspector: FlipPathInspector,
    path_config: FlipPathConfig,
    trade_combos: Iterable[TradeCombo],
    *,
    pair: str,
    phase: str,
    period_start: dt.datetime,
    progress_file: Path,
    started: float,
    notify: Notice | None,
) -> pd.DataFrame:
    """Inspect every TP/LC candidate once per selected Top-15 event."""
    combos = tuple(trade_combos)
    source_positions: list[int] = []
    rows: list[dict[str, Any]] = []
    total = len(frame)
    next_notice = pd.Timestamp(period_start) + pd.DateOffset(months=2)
    for row_number, row in enumerate(frame.itertuples(index=False), start=1):
        decision_time = pd.Timestamp(row.decision_time)
        path = inspector.inspect(
            decision_time=decision_time,
            line_price=float(row.line_price),
            order_direction=int(row.trade_direction),
            average_range_pips=float(row.recent_m5_avg_range_pips),
            path_config=path_config,
            trade_combos=combos,
            next_count2_time=row.next_count2_time,
        )
        for combo in combos:
            output = {column: path.get(column) for column in PATH_EXPORT_COLUMNS}
            output.update({column: np.nan for column in OUTCOME_EXPORT_COLUMNS})
            output.update(path.get("outcomes", {}).get(combo.combo_id, {}))
            output["grid_combo_id"] = combo.combo_id
            output["grid_tp_a"] = combo.tp_a
            output["grid_lc_a"] = combo.lc_a
            output["grid_configured_rr"] = combo.configured_rr
            rows.append(output)
            source_positions.append(row_number - 1)
        while decision_time >= next_notice:
            _notice_progress(
                notify,
                pair=pair,
                phase=phase,
                reached_time=next_notice,
                current_row=row_number,
                total_rows=total,
                started=started,
            )
            next_notice += pd.DateOffset(months=2)
        if row_number == 1 or row_number % 500 == 0:
            write_progress(
                progress_file,
                pair=pair,
                status="running",
                phase=phase,
                current_row=row_number,
                total_rows=total,
                current_time=decision_time,
                started=started,
            )
    if not rows:
        return frame.iloc[0:0].copy()
    sources = frame.iloc[source_positions].reset_index(drop=True)
    outcomes = pd.DataFrame(rows).reset_index(drop=True)
    return pd.concat([sources, outcomes], axis=1)


def scan_tier_filter_lc_grid(
    grid_paths: pd.DataFrame,
    tier_configs: Iterable[TierExecutionConfig],
    trade_combos: Iterable[TradeCombo],
    range_filter_pips_values: Iterable[float],
    *,
    period_start: dt.datetime,
    period_end: dt.datetime,
) -> pd.DataFrame:
    """Evaluate A-width and TP/LC grids inside each confidence tier."""
    filters = tuple(sorted({float(value) for value in range_filter_pips_values}))
    combos = tuple(trade_combos)
    rows: list[dict[str, Any]] = []
    for tier_config in tier_configs:
        tier_paths = grid_paths[
            grid_paths["signal_tier"].eq(tier_config.tier)
        ]
        for combo in combos:
            combo_paths = tier_paths[
                tier_paths["grid_combo_id"].eq(combo.combo_id)
            ]
            for filter_value in filters:
                eligible = combo_paths.loc[
                    range_filter_mask(combo_paths, filter_value)
                ].copy()
                trades, performance = replay_condition(
                    eligible, PolicyCondition("ALL", "Tier range/LC grid")
                )
                rows.append(
                    {
                        "tier": tier_config.tier,
                        "first_rank": tier_config.first_rank,
                        "last_rank": tier_config.last_rank,
                        "range_filter_fraction_a": RANGE_FILTER_FRACTION_A,
                        "min_range_filter_pips": filter_value,
                        "equivalent_minimum_a_pips": (
                            filter_value / RANGE_FILTER_FRACTION_A
                        ),
                        "combo_id": combo.combo_id,
                        "tp_a": combo.tp_a,
                        "lc_a": combo.lc_a,
                        "configured_rr": combo.configured_rr,
                        **performance,
                        **four_period_metrics(
                            trades, period_start, period_end
                        ),
                    }
                )
    return pd.DataFrame(rows)


def scan_portfolio_tp_lc_grid(
    grid_paths: pd.DataFrame,
    tier_configs: Iterable[TierExecutionConfig],
    trade_combos: Iterable[TradeCombo],
) -> pd.DataFrame:
    """Replay each TP/LC pair after freezing the train-selected tier filters."""
    configs = tuple(tier_configs)
    minimum_by_tier = {
        config.tier: config.min_range_filter_pips for config in configs
    }
    rows: list[dict[str, Any]] = []
    if grid_paths.empty:
        return pd.DataFrame(
            [
                {
                    "combo_id": combo.combo_id,
                    "tp_a": combo.tp_a,
                    "lc_a": combo.lc_a,
                    "configured_rr": combo.configured_rr,
                    **PerformanceAccumulator().row(),
                }
                for combo in trade_combos
            ]
        )
    for combo in trade_combos:
        combo_paths = grid_paths[
            grid_paths["grid_combo_id"].eq(combo.combo_id)
        ].copy()
        minimum = combo_paths["signal_tier"].map(minimum_by_tier)
        if minimum.isna().any():
            raise ValueError("portfolio TP/LC grid contains an unknown tier")
        eligible = combo_paths.loc[
            pd.to_numeric(
                combo_paths["available_range_filter_pips"], errors="coerce"
            ).add(1e-12).ge(minimum)
        ].copy()
        _trades, performance = replay_condition(
            eligible, PolicyCondition("ALL", "Portfolio TP/LC grid")
        )
        rows.append(
            {
                "combo_id": combo.combo_id,
                "tp_a": combo.tp_a,
                "lc_a": combo.lc_a,
                "configured_rr": combo.configured_rr,
                **performance,
            }
        )
    return pd.DataFrame(rows)


def _attach_baseline_trade_comparison(
    all_trades: pd.DataFrame,
    baseline_trades: pd.DataFrame,
) -> pd.DataFrame:
    """Attach all baseline comparison columns in one de-fragmenting concat."""
    if baseline_trades.empty:
        return all_trades
    baseline_lookup = baseline_trades.set_index("event_id")
    event_ids = all_trades["event_id"]
    baseline_trade_result = event_ids.map(baseline_lookup["trade_result"])
    baseline_result_pips = event_ids.map(
        baseline_lookup["trade_result_pips"]
    )
    baseline_result_yen = event_ids.map(baseline_lookup["result_yen"])
    baseline_exit_time = event_ids.map(baseline_lookup["exit_time"])
    comparison_columns = pd.DataFrame(
        {
            "baseline_trade_result": baseline_trade_result,
            "baseline_trade_result_pips": baseline_result_pips,
            "baseline_result_yen": baseline_result_yen,
            "baseline_exit_time": baseline_exit_time,
            "delta_vs_baseline_result_pips": (
                pd.to_numeric(
                    all_trades["trade_result_pips"], errors="coerce"
                )
                - pd.to_numeric(baseline_result_pips, errors="coerce")
            ),
            "delta_vs_baseline_result_yen": (
                pd.to_numeric(all_trades["result_yen"], errors="coerce")
                - pd.to_numeric(baseline_result_yen, errors="coerce")
            ),
        },
        index=all_trades.index,
    )
    return pd.concat(
        [all_trades.copy(), comparison_columns],
        axis=1,
        copy=False,
    )


def scan_timed_half_lc_grid(
    grid_paths: pd.DataFrame,
    timed_configs: Iterable[TimedHalfLcConfig],
    *,
    period_start: dt.datetime,
    period_end: dt.datetime,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Replay each timer independently so its earlier exits unlock events."""
    policies = tuple(timed_configs)
    rows: list[dict[str, Any]] = []
    trade_frames: list[pd.DataFrame] = []
    for policy_order, policy in enumerate(policies):
        policy_paths = grid_paths[
            grid_paths["timed_half_lc_config_id"].eq(policy.config_id)
        ].copy()
        trades, performance = replay_condition(
            policy_paths,
            PolicyCondition("ALL", f"Timed half-LC {policy.config_id}"),
        )
        trades["timed_half_lc_policy_order"] = policy_order
        trade_frames.append(trades)
        activated = (
            trades.get("timed_half_lc_activated", pd.Series(False, index=trades.index))
            .fillna(False)
            .astype(bool)
        )
        timed_exits = (
            trades.get("timed_half_lc_exit", pd.Series(False, index=trades.index))
            .fillna(False)
            .astype(bool)
        )
        open_exits = (
            trades.get(
                "timed_half_lc_exit_at_bar_open",
                pd.Series(False, index=trades.index),
            )
            .fillna(False)
            .astype(bool)
        )
        late_half_tp = (
            trades.get(
                "half_tp_reached_after_timed_activation",
                pd.Series(False, index=trades.index),
            )
            .fillna(False)
            .astype(bool)
        )
        counterfactual_late_half_tp = (
            trades.get(
                "counterfactual_half_tp_reached_after_timed_activation",
                pd.Series(False, index=trades.index),
            )
            .fillna(False)
            .astype(bool)
        )
        ambiguity_suppressed = (
            trades.get(
                "timed_half_lc_suppressed_by_fill_bar_ambiguity",
                pd.Series(False, index=trades.index),
            )
            .fillna(False)
            .astype(bool)
        )
        rows.append(
            {
                "timed_half_lc_policy_order": policy_order,
                **policy.to_dict(),
                **performance,
                **four_period_metrics(trades, period_start, period_end),
                "timed_half_lc_activation_count": int(activated.sum()),
                "timed_half_lc_exit_count": int(timed_exits.sum()),
                "timed_half_lc_open_exit_count": int(open_exits.sum()),
                "late_half_tp_after_activation_count": int(late_half_tp.sum()),
                "counterfactual_horizon_late_half_tp_count": int(
                    counterfactual_late_half_tp.sum()
                ),
                "fill_bar_ambiguity_suppression_count": int(
                    ambiguity_suppressed.sum()
                ),
                "full_lc_count": int(
                    trades["trade_result"].isin(
                        ("lc", "both_same_s5_lc_assumed")
                    ).sum()
                ),
            }
        )
    summary = pd.DataFrame(rows)
    if summary.empty or not summary["config_id"].eq("baseline").any():
        raise ValueError("timed half-LC grid requires a baseline")
    baseline = summary.loc[summary["config_id"].eq("baseline")].iloc[0]
    for field in ("sum_yen", "sum_pips", "profit_factor_yen", "win_rate"):
        summary[f"delta_vs_baseline_{field}"] = (
            pd.to_numeric(summary[field], errors="coerce") - float(baseline[field])
        )
    all_trades = (
        pd.concat(trade_frames, ignore_index=True)
        if trade_frames
        else grid_paths.iloc[0:0].copy()
    )
    baseline_trades = all_trades[
        all_trades["timed_half_lc_config_id"].eq("baseline")
    ].copy()
    all_trades = _attach_baseline_trade_comparison(
        all_trades,
        baseline_trades,
    )
    return summary, all_trades


def scan_line_wick_lc_grid(
    grid_paths: pd.DataFrame,
    line_wick_configs: Iterable[LineWickLcConfig],
    *,
    period_start: dt.datetime,
    period_end: dt.datetime,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Replay each wick-cross width independently with lifecycle unlocking."""
    policies = tuple(line_wick_configs)
    rows: list[dict[str, Any]] = []
    trade_frames: list[pd.DataFrame] = []
    for policy_order, policy in enumerate(policies):
        policy_paths = grid_paths[
            grid_paths["line_wick_lc_config_id"].eq(policy.config_id)
        ].copy()
        trades, performance = replay_condition(
            policy_paths,
            PolicyCondition("ALL", f"Line-wick LC {policy.config_id}"),
        )
        trades["line_wick_lc_policy_order"] = policy_order
        trade_frames.append(trades)
        wick_exits = (
            trades.get(
                "line_wick_lc_exit", pd.Series(False, index=trades.index)
            )
            .fillna(False)
            .astype(bool)
        )
        gap_exits = (
            trades.get(
                "line_wick_lc_exit_at_bar_open",
                pd.Series(False, index=trades.index),
            )
            .fillna(False)
            .astype(bool)
        )
        same_s5 = (
            trades.get(
                "line_wick_lc_same_s5_tp_assumed_first",
                pd.Series(False, index=trades.index),
            )
            .fillna(False)
            .astype(bool)
        )
        rows.append(
            {
                "line_wick_lc_policy_order": policy_order,
                **policy.to_dict(),
                **performance,
                **four_period_metrics(trades, period_start, period_end),
                "line_wick_lc_exit_count": int(wick_exits.sum()),
                "line_wick_lc_gap_exit_count": int(gap_exits.sum()),
                "line_wick_lc_same_s5_tp_assumed_first_count": int(
                    same_s5.sum()
                ),
                "full_lc_count": int(
                    trades["trade_result"].isin(
                        ("lc", "both_same_s5_lc_assumed")
                    ).sum()
                ),
            }
        )
    summary = pd.DataFrame(rows)
    if summary.empty or not summary["config_id"].eq("baseline").any():
        raise ValueError("line-wick LC grid requires a baseline")
    baseline = summary.loc[summary["config_id"].eq("baseline")].iloc[0]
    for field in ("sum_yen", "sum_pips", "profit_factor_yen", "win_rate"):
        summary[f"delta_vs_baseline_{field}"] = (
            pd.to_numeric(summary[field], errors="coerce")
            - float(baseline[field])
        )
    all_trades = (
        pd.concat(trade_frames, ignore_index=True)
        if trade_frames
        else grid_paths.iloc[0:0].copy()
    )
    baseline_trades = all_trades[
        all_trades["line_wick_lc_config_id"].eq("baseline")
    ].copy()
    all_trades = _attach_baseline_trade_comparison(
        all_trades,
        baseline_trades,
    )
    return summary, all_trades


def choose_line_wick_lc_policy(
    summary: pd.DataFrame,
    *,
    minimum_trades: int = 30,
    minimum_exits: int = 30,
) -> pd.Series:
    """Freeze one stable wick width on train only; otherwise use baseline."""
    strict = summary.loc[
        ~summary["config_id"].eq("baseline")
        & summary["completed_trade_count"].ge(minimum_trades)
        & summary["line_wick_lc_exit_count"].ge(minimum_exits)
        & summary["sum_yen"].gt(0)
        & summary["profit_factor_yen"].ge(1.1)
        & summary["positive_period_count"].ge(3)
        & summary["max_positive_period_profit_share"].le(0.60)
        & summary["delta_vs_baseline_sum_yen"].gt(0)
    ].copy()
    if strict.empty:
        baseline = summary.loc[summary["config_id"].eq("baseline")]
        if len(baseline) != 1:
            raise ValueError("line-wick LC baseline selection is ambiguous")
        selected = baseline.iloc[0].copy()
        selected["selection_stage"] = "baseline_no_strict_candidate"
        return selected
    selected = strict.sort_values(
        [
            "sum_yen",
            "positive_period_count",
            "profit_factor_yen",
            "max_positive_period_profit_share",
            "delta_vs_baseline_sum_yen",
            "sum_pips",
            "line_wick_lc_policy_order",
        ],
        ascending=[False, False, False, True, False, False, True],
        kind="stable",
    ).iloc[0].copy()
    selected["selection_stage"] = "strict_stability"
    return selected


def choose_timed_half_lc_policy(
    summary: pd.DataFrame,
    *,
    minimum_trades: int = 100,
) -> pd.Series:
    """Select only a stable train policy; otherwise preserve baseline."""
    strict = summary.loc[
        summary["completed_trade_count"].ge(minimum_trades)
        & summary["sum_yen"].gt(0)
        & summary["profit_factor_yen"].ge(1.1)
        & summary["positive_period_count"].ge(3)
        & summary["max_positive_period_profit_share"].le(0.60)
    ].copy()
    if strict.empty:
        baseline = summary.loc[summary["config_id"].eq("baseline")]
        if len(baseline) != 1:
            raise ValueError("timed half-LC baseline selection is ambiguous")
        selected = baseline.iloc[0].copy()
        selected["selection_stage"] = "baseline_no_strict_candidate"
        return selected
    selected = strict.sort_values(
        [
            "sum_yen",
            "positive_period_count",
            "profit_factor_yen",
            "max_positive_period_profit_share",
            "sum_pips",
            "timed_half_lc_policy_order",
        ],
        ascending=[False, False, False, True, False, True],
        kind="stable",
    ).iloc[0].copy()
    selected["selection_stage"] = "strict_stability"
    return selected


def timed_half_lc_strict_mask(
    summary: pd.DataFrame,
    *,
    minimum_trades: int = 30,
    minimum_activations: int = 30,
) -> pd.Series:
    """Return the train-only eligibility mask for early-loss-cut policies."""
    return (
        ~summary["config_id"].eq("baseline")
        & summary["completed_trade_count"].ge(minimum_trades)
        & summary["timed_half_lc_activation_count"].ge(minimum_activations)
        & summary["sum_yen"].gt(0)
        & summary["profit_factor_yen"].ge(1.1)
        & summary["positive_period_count"].ge(3)
        & summary["max_positive_period_profit_share"].le(0.60)
        & summary["delta_vs_baseline_sum_yen"].gt(0)
    )


def select_timed_half_lc_policies(
    summary: pd.DataFrame,
    trades: pd.DataFrame,
    timed_configs: Iterable[TimedHalfLcConfig],
    *,
    minimum_trades: int = 30,
    minimum_activations: int = 30,
    limit: int = 5,
    maximum_trigger_jaccard: float = 0.85,
) -> tuple[tuple[TimedHalfLcConfig, ...], pd.DataFrame]:
    """Select distinct stable policies using train data only.

    Adjacent time/fraction settings can cut almost the same events.  After
    strict performance filtering, retain the higher-ranked setting and drop a
    later setting when its timed-exit event set has Jaccard overlap at or above
    ``maximum_trigger_jaccard``.
    """
    if minimum_trades < 1 or minimum_activations < 1 or limit < 1:
        raise ValueError("timed half-LC selection counts must be positive")
    if not 0 <= maximum_trigger_jaccard <= 1:
        raise ValueError("timed half-LC overlap threshold must be in [0, 1]")
    policies = tuple(timed_configs)
    policy_by_id = {policy.config_id: policy for policy in policies}
    if len(policy_by_id) != len(policies):
        raise ValueError("timed half-LC selection configs must be unique")
    baseline = summary.loc[summary["config_id"].eq("baseline")]
    if len(baseline) != 1 or "baseline" not in policy_by_id:
        raise ValueError("timed half-LC selection requires one baseline")

    strict = summary.loc[
        timed_half_lc_strict_mask(
            summary,
            minimum_trades=minimum_trades,
            minimum_activations=minimum_activations,
        )
    ].copy()
    if strict.empty:
        return (), strict
    strict.sort_values(
        [
            "sum_yen",
            "positive_period_count",
            "profit_factor_yen",
            "max_positive_period_profit_share",
            "delta_vs_baseline_sum_yen",
            "sum_pips",
            "timed_half_lc_policy_order",
        ],
        ascending=[False, False, False, True, False, False, True],
        inplace=True,
        kind="stable",
    )

    timed_exit = trades.get(
        "timed_half_lc_exit", pd.Series(False, index=trades.index)
    ).fillna(False).astype(bool)
    event_sets = {
        config_id: set(
            trades.loc[
                trades["timed_half_lc_config_id"].eq(config_id) & timed_exit,
                "event_id",
            ].astype(str)
        )
        for config_id in strict["config_id"].astype(str)
    }
    selected_rows: list[pd.Series] = []
    selected_sets: list[set[str]] = []
    for _, row in strict.iterrows():
        config_id = str(row["config_id"])
        if config_id not in policy_by_id:
            raise ValueError("strict timed half-LC row has no candidate config")
        events = event_sets[config_id]
        overlaps = []
        for prior in selected_sets:
            union = events | prior
            overlaps.append(len(events & prior) / len(union) if union else 1.0)
        maximum_overlap = max(overlaps, default=0.0)
        if maximum_overlap + 1e-12 >= maximum_trigger_jaccard:
            continue
        selected = row.copy()
        selected["selection_rank"] = len(selected_rows) + 1
        selected["selection_stage"] = "strict_stable_distinct_train"
        selected["maximum_trigger_jaccard_with_higher_rank"] = maximum_overlap
        selected_rows.append(selected)
        selected_sets.append(events)
        if len(selected_rows) >= limit:
            break

    selected_frame = (
        pd.DataFrame(selected_rows)
        if selected_rows
        else strict.iloc[0:0].copy()
    )
    selected_configs = tuple(
        policy_by_id[str(row["config_id"])]
        for _, row in selected_frame.iterrows()
    )
    return selected_configs, selected_frame


def choose_tier_execution_configs(
    summary: pd.DataFrame,
    base_configs: Iterable[TierExecutionConfig],
    *,
    minimum_trades: int = 30,
    minimum_rr: float = 0.0,
) -> tuple[tuple[TierExecutionConfig, ...], pd.DataFrame]:
    selected_configs = []
    selected_rows = []
    for base_config in base_configs:
        tier_summary = summary[summary["tier"].eq(base_config.tier)]
        if tier_summary.empty:
            raise ValueError(f"tier grid is empty for {base_config.tier}")
        selected = choose_global_policy(
            tier_summary,
            minimum_trades=minimum_trades,
            minimum_rr=minimum_rr,
        )
        selected_configs.append(
            TierExecutionConfig(
                tier=base_config.tier,
                first_rank=base_config.first_rank,
                last_rank=base_config.last_rank,
                tp_a=float(selected["tp_a"]),
                rr=float(selected["configured_rr"]),
                min_range_filter_pips=float(
                    selected["min_range_filter_pips"]
                ),
            )
        )
        selected_rows.append(selected.to_dict())
    return tuple(selected_configs), pd.DataFrame(selected_rows)


def performance_from_frame(frame: pd.DataFrame, mask: np.ndarray) -> dict[str, Any]:
    selected = frame.loc[mask]
    candidate_count = len(selected)
    fill_count = int(selected["order_filled"].fillna(False).astype(bool).sum())
    trades = selected[
        selected["path_status"].eq("trade")
        & pd.to_numeric(selected["trade_result_pips"], errors="coerce").notna()
    ].copy()
    trade_count = len(trades)
    profit_lock_count = int(
        trades["trade_result"].eq("profit_lock").sum()
    )
    if trade_count:
        pips = pd.to_numeric(trades["trade_result_pips"], errors="coerce")
        average = pd.to_numeric(
            trades["recent_m5_avg_range_pips"], errors="coerce"
        )
        result_a = pips.div(average.where(average > 0))
        yen = pd.to_numeric(trades["result_yen"], errors="coerce")
        wins = pips > 0
        losses = pips < 0
        gross_profit = float(yen[yen > 0].sum())
        gross_loss = float(-yen[yen < 0].sum())
        month_yen = yen.groupby(
            pd.to_datetime(trades["fill_time"]).dt.strftime("%Y-%m")
        ).sum()
    else:
        pips = pd.Series(dtype=float)
        result_a = pd.Series(dtype=float)
        yen = pd.Series(dtype=float)
        wins = pd.Series(dtype=bool)
        losses = pd.Series(dtype=bool)
        gross_profit = 0.0
        gross_loss = 0.0
        month_yen = pd.Series(dtype=float)
    active_months = len(month_yen)
    positive_months = int((month_yen > 0).sum())
    win_count = int(wins.sum())
    loss_count = int(losses.sum())
    return {
        "candidate_count": candidate_count,
        "order_fill_count": fill_count,
        "order_fill_rate": fill_count / candidate_count if candidate_count else 0.0,
        "completed_trade_count": trade_count,
        "win_count": win_count,
        "profit_lock_count": profit_lock_count,
        "profit_lock_rate": (
            profit_lock_count / trade_count if trade_count else 0.0
        ),
        "win_rate": win_count / trade_count if trade_count else 0.0,
        "average_win_pips": float(pips[wins].mean()) if win_count else 0.0,
        "average_loss_pips": float(pips[losses].mean()) if loss_count else 0.0,
        "sum_pips": float(pips.sum()),
        "sum_a": float(result_a.sum()),
        "gross_profit_yen": gross_profit,
        "gross_loss_yen": gross_loss,
        "sum_yen": float(yen.sum()),
        "profit_factor_yen": (
            gross_profit / gross_loss
            if gross_loss
            else (math.inf if gross_profit else 0.0)
        ),
        "active_month_count": active_months,
        "positive_month_count": positive_months,
        "positive_month_rate": (
            positive_months / active_months if active_months else 0.0
        ),
        "worst_month_yen": float(month_yen.min()) if active_months else 0.0,
    }


def line_holding_early_path_dataset(
    paths: pd.DataFrame,
    *,
    phase: str,
) -> pd.DataFrame:
    """Normalize causal minute-1..5 LineHolding snapshots and final labels.

    Snapshot columns are features known at ``checkpoint_time``.  Columns with
    the ``final_`` prefix are labels known only after ``exit_effective_time``
    and must never be used by an entry or earlier checkpoint decision.
    """
    identity_columns = (
        "event_id",
        "pair",
        "decision_time",
        "signal_tier",
        "highest_matched_rank",
        "matched_condition_ids",
        "matched_condition_ranks",
        "matched_condition_count",
        "fc2_shape",
        "fc2_candle_sequence",
        "fc2_relative_candle_sequence",
        "fc2_second_wick_A",
        "fc2_second_close_pushback_A",
        "fc2_second_body_to_first_ratio",
        "line_price",
        "line_total_strength",
        "line_count",
        "line_core_count",
        "line_is_flipped",
        "line_history_is_flipped",
        "line_flip_count",
        "signal_order_direction",
        "order_direction",
        "recent_m5_avg_range_pips",
        "watch_breakout_distance_pips",
        "watch_breakout_distance_a",
        "fill_time",
        "actual_entry_price",
        "tp_a",
        "lc_a",
        "tp_pips",
        "lc_pips",
    )
    snapshot_metrics = tuple(
        metric for metric in EARLY_PATH_METRICS if metric != "checkpoint_time"
    )
    final_columns = (
        "trade_result",
        "trade_result_pips",
        "result_r",
        "result_yen",
        "exit_time",
        "exit_effective_time",
        "minutes_from_fill_to_exit",
        "minutes_to_original_tp",
        "minutes_to_original_lc",
        "max_favorable_pips",
        "max_adverse_pips",
        "exit_s5_opposite_extreme_censored",
        "exit_execution_mode",
        "actual_exit_price",
    )
    output_columns = (
        "phase",
        *identity_columns,
        "elapsed_minute",
        "checkpoint_time",
        "snapshot_known_time",
        *snapshot_metrics,
        *(f"final_{column}" for column in final_columns),
        "final_max_favorable_a",
        "final_max_adverse_a",
        "final_is_hard_lc",
        "final_is_any_stop_exit",
        "final_is_tp",
        "final_is_profit",
        "snapshot_fields_are_causal",
        "final_fields_are_labels_only",
    )
    required_columns = {
        "watch_order_name",
        "path_status",
        "event_id",
        "pair",
        "decision_time",
        "recent_m5_avg_range_pips",
        "fill_time",
        "actual_entry_price",
        "tp_a",
        "lc_a",
        "tp_pips",
        "lc_pips",
        *final_columns,
        *(
            f"early_m{minute}_{metric}"
            for minute in EARLY_PATH_MINUTES
            for metric in EARLY_PATH_METRICS
        ),
    }
    missing_columns = sorted(required_columns.difference(paths.columns))
    if missing_columns:
        raise ValueError(
            "LineHolding early-path source columns are incomplete: "
            + ", ".join(missing_columns)
        )
    if paths.empty:
        return pd.DataFrame(columns=output_columns)

    names = paths.get(
        "watch_order_name", pd.Series(index=paths.index, dtype="string")
    ).astype("string")
    statuses = paths.get(
        "path_status", pd.Series(index=paths.index, dtype="string")
    ).astype("string")
    selected = paths.loc[
        names.eq("FlipPredict_LineHolding") & statuses.eq("trade")
    ]
    rows: list[dict[str, Any]] = []
    hard_lc_names = {"lc", "both_same_s5_lc_assumed"}
    any_stop_names = hard_lc_names | {"timed_half_lc", "line_wick_lc"}
    for source in selected.to_dict(orient="records"):
        average_range = pd.to_numeric(
            source.get("recent_m5_avg_range_pips"), errors="coerce"
        )
        result_name = str(source.get("trade_result") or "")
        result_pips = pd.to_numeric(
            source.get("trade_result_pips"), errors="coerce"
        )
        base = {column: source.get(column) for column in identity_columns}
        final = {
            f"final_{column}": source.get(column) for column in final_columns
        }
        for minute in EARLY_PATH_MINUTES:
            prefix = f"early_m{minute}_"
            checkpoint = source.get(prefix + "checkpoint_time", pd.NaT)
            row = {
                "phase": phase,
                **base,
                "elapsed_minute": minute,
                "checkpoint_time": checkpoint,
                "snapshot_known_time": checkpoint,
                **{
                    metric: source.get(prefix + metric)
                    for metric in snapshot_metrics
                },
                **final,
                "final_max_favorable_a": (
                    pd.to_numeric(source.get("max_favorable_pips"), errors="coerce")
                    / average_range
                    if pd.notna(average_range) and average_range > 0
                    else np.nan
                ),
                "final_max_adverse_a": (
                    pd.to_numeric(source.get("max_adverse_pips"), errors="coerce")
                    / average_range
                    if pd.notna(average_range) and average_range > 0
                    else np.nan
                ),
                "final_is_hard_lc": result_name in hard_lc_names,
                "final_is_any_stop_exit": result_name in any_stop_names,
                "final_is_tp": result_name == "tp",
                "final_is_profit": bool(pd.notna(result_pips) and result_pips > 0),
                "snapshot_fields_are_causal": True,
                "final_fields_are_labels_only": True,
            }
            rows.append(row)
    return pd.DataFrame(rows, columns=output_columns)


def summarize_watch_entry_branches(
    paths: pd.DataFrame,
    trades: pd.DataFrame,
) -> pd.DataFrame:
    """Summarize the three watch-entry branches after portfolio lifecycle replay."""
    names = (
        "FlipPredict_LineHolding",
        "FlipPredict_NearLineConsolidation",
        "FlipPredict_Breakout",
    )
    rows: list[dict[str, Any]] = []
    path_names = paths.get(
        "watch_order_name", pd.Series(index=paths.index, dtype="string")
    ).astype("string")
    trade_names = trades.get(
        "watch_order_name", pd.Series(index=trades.index, dtype="string")
    ).astype("string")
    for name in names:
        classified = paths.loc[path_names.eq(name)]
        classified_status = classified.get(
            "path_status", pd.Series(index=classified.index, dtype="string")
        ).astype("string")
        selected = trades.loc[trade_names.eq(name)].copy()
        pips = pd.to_numeric(
            selected.get("trade_result_pips"), errors="coerce"
        ).dropna()
        yen = pd.to_numeric(selected.get("result_yen"), errors="coerce").dropna()
        wins = pips[pips > 0]
        losses = pips[pips < 0]
        gross_profit = float(yen[yen > 0].sum())
        gross_loss = float(-yen[yen < 0].sum())
        rows.append(
            {
                "watch_order_name": name,
                "classified_candidate_count": int(len(classified)),
                "path_fill_count_before_lifecycle": int(
                    classified["order_filled"].fillna(False).astype(bool).sum()
                ),
                "chase_filtered_count": int(
                    classified_status.eq(
                        "watch_line_holding_chase_filtered"
                    ).sum()
                ),
                "entry_quote_or_gap_filtered_count": int(
                    classified_status.isin(
                        {
                            "watch_line_holding_entry_quote_filtered",
                            "watch_entry_gap_filtered",
                        }
                    ).sum()
                ),
                "pending_no_fill_count": int(
                    classified_status.isin(
                        {"watch_retest_no_fill", "watch_breakout_no_fill"}
                    ).sum()
                ),
                "stop_fill_bar_adverse_censored_count": int(
                    classified.get(
                        "watch_stop_fill_bar_adverse_censored",
                        pd.Series(False, index=classified.index),
                    )
                    .fillna(False)
                    .astype(bool)
                    .sum()
                ),
                "completed_trade_count": int(len(pips)),
                "win_count": int(len(wins)),
                "win_rate": float(len(wins) / len(pips)) if len(pips) else 0.0,
                "average_win_pips": float(wins.mean()) if len(wins) else 0.0,
                "average_loss_pips": float(losses.mean()) if len(losses) else 0.0,
                "sum_pips": float(pips.sum()),
                "gross_profit_yen": gross_profit,
                "gross_loss_yen": gross_loss,
                "sum_yen": float(yen.sum()),
                "profit_factor_yen": (
                    gross_profit / gross_loss
                    if gross_loss
                    else (math.inf if gross_profit else 0.0)
                ),
            }
        )
    return pd.DataFrame(rows)


def summarize_conditions(
    frame: pd.DataFrame,
    conditions: Iterable[PolicyCondition],
) -> pd.DataFrame:
    length = len(frame)
    feature_arrays = {
        field: frame[field].astype(str).to_numpy()
        for field in FEATURE_FIELDS
        if field in frame
    }
    fills = frame["order_filled"].fillna(False).to_numpy(dtype=bool)
    pips = pd.to_numeric(frame["trade_result_pips"], errors="coerce").to_numpy(
        dtype=float
    )
    yen = pd.to_numeric(frame["result_yen"], errors="coerce").to_numpy(
        dtype=float
    )
    average = pd.to_numeric(
        frame["recent_m5_avg_range_pips"], errors="coerce"
    ).to_numpy(dtype=float)
    trades = frame["path_status"].eq("trade").to_numpy() & np.isfinite(pips)
    profit_locks = frame["trade_result"].eq("profit_lock").to_numpy()
    month_values = (
        pd.to_datetime(frame["fill_time"])
        .dt.strftime("%Y-%m")
        .fillna("no_fill")
    )
    _month_labels, month_codes = np.unique(month_values.to_numpy(), return_inverse=True)

    def metrics(mask: np.ndarray) -> dict[str, Any]:
        candidate_count = int(mask.sum())
        fill_count = int(np.count_nonzero(mask & fills))
        trade_mask = mask & trades
        trade_count = int(trade_mask.sum())
        selected_pips = pips[trade_mask]
        selected_yen = yen[trade_mask]
        selected_average = average[trade_mask]
        selected_a = np.divide(
            selected_pips,
            selected_average,
            out=np.zeros_like(selected_pips),
            where=np.isfinite(selected_average) & (selected_average > 0),
        )
        wins = selected_pips > 0
        losses = selected_pips < 0
        win_count = int(wins.sum())
        profit_lock_count = int(np.count_nonzero(trade_mask & profit_locks))
        loss_count = int(losses.sum())
        gross_profit = float(selected_yen[selected_yen > 0].sum())
        gross_loss = float(-selected_yen[selected_yen < 0].sum())
        if trade_count:
            month_yen = np.bincount(
                month_codes[trade_mask],
                weights=selected_yen,
                minlength=len(_month_labels),
            )
            active = np.bincount(
                month_codes[trade_mask], minlength=len(_month_labels)
            ) > 0
            active_values = month_yen[active]
        else:
            active_values = np.asarray([], dtype=float)
        active_months = len(active_values)
        positive_months = int(np.count_nonzero(active_values > 0))
        return {
            "candidate_count": candidate_count,
            "order_fill_count": fill_count,
            "order_fill_rate": (
                fill_count / candidate_count if candidate_count else 0.0
            ),
            "completed_trade_count": trade_count,
            "win_count": win_count,
            "profit_lock_count": profit_lock_count,
            "profit_lock_rate": (
                profit_lock_count / trade_count if trade_count else 0.0
            ),
            "win_rate": win_count / trade_count if trade_count else 0.0,
            "average_win_pips": (
                float(selected_pips[wins].mean()) if win_count else 0.0
            ),
            "average_loss_pips": (
                float(selected_pips[losses].mean()) if loss_count else 0.0
            ),
            "sum_pips": float(selected_pips.sum()),
            "sum_a": float(selected_a.sum()),
            "gross_profit_yen": gross_profit,
            "gross_loss_yen": gross_loss,
            "sum_yen": float(selected_yen.sum()),
            "profit_factor_yen": (
                gross_profit / gross_loss
                if gross_loss
                else (math.inf if gross_profit else 0.0)
            ),
            "active_month_count": active_months,
            "positive_month_count": positive_months,
            "positive_month_rate": (
                positive_months / active_months if active_months else 0.0
            ),
            "worst_month_yen": (
                float(active_values.min()) if active_months else 0.0
            ),
        }

    rows = []
    for condition in conditions:
        mask = np.ones(length, dtype=bool)
        for field, expected in condition.clauses:
            values = feature_arrays.get(field)
            if values is None:
                mask[:] = False
                break
            mask &= values == expected
        rows.append(
            {
                "condition_id": condition.condition_id,
                "condition_label": condition.label,
                "clause_count": len(condition.clauses),
                "condition_json": json.dumps(
                    condition.to_dict(), ensure_ascii=False, sort_keys=True
                ),
                **metrics(mask),
            }
        )
    return pd.DataFrame(rows)


def replay_condition(
    frame: pd.DataFrame,
    condition: PolicyCondition,
    *,
    one_at_a_time: bool = True,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """条件に合うイベントを、実際のライフサイクル順に再生する。

    ``one_at_a_time`` が True（既定）なら、待機中または保有中の一件が
    片付くまで後続のシグナルを見送る。これは flip 専用サービスが自分の
    状態だけを見ていた頃の挙動で、これまでの検証成績はすべてこの前提で
    出ている。

    False にすると見送りをやめ、発生したシグナルをすべて取る。ポジションを
    スロットで管理するようになり同時保有が可能になったため、その場合の
    成績を測るための切り替え。実運用と検証を揃えるにはこちらを使う。
    """
    mask = condition_mask(frame, condition)
    eligible = frame.loc[mask].copy()
    eligible.sort_values(
        ["decision_time", "event_id", "distance_rank", "distance_pips"],
        inplace=True,
        kind="stable",
    )
    trade_rows: list[dict[str, Any]] = []
    locked_until = pd.NaT
    event_count = 0
    selected_lifecycle_count = 0
    replaced_before_fill = 0
    skipped_while_locked = 0
    pending_order_lock_count = 0
    accumulator = PerformanceAccumulator()
    for _event_id, group in eligible.groupby("event_id", sort=False):
        event_count += 1
        decision_time = pd.Timestamp(group.iloc[0]["decision_time"])
        if (
            one_at_a_time
            and not pd.isna(locked_until)
            and decision_time < locked_until
        ):
            skipped_while_locked += 1
            continue
        candidate = group.sort_values(
            ["distance_rank", "distance_pips", "line_price"], kind="stable"
        ).iloc[0]
        selected_lifecycle_count += 1
        accumulator.add_candidate(candidate)
        if candidate.get("replaced_before_fill"):
            replaced_before_fill += 1
        if not candidate.get("order_filled"):
            pending_end = pd.to_datetime(
                candidate.get("watch_order_release_time"), errors="coerce"
            )
            if pd.isna(pending_end):
                pending_end = pd.to_datetime(
                    candidate.get("order_deadline"), errors="coerce"
                )
            if not pd.isna(pending_end) and pending_end > decision_time:
                locked_until = pending_end
                pending_order_lock_count += 1
            continue
        if candidate.get("path_status") != "trade":
            position_horizon_end = pd.to_datetime(
                candidate.get("position_horizon_end"), errors="coerce"
            )
            if not pd.isna(position_horizon_end):
                locked_until = position_horizon_end
            continue
        exit_time = pd.to_datetime(candidate.get("exit_time"), errors="coerce")
        if pd.isna(exit_time):
            continue
        exit_effective_time = pd.to_datetime(
            candidate.get("exit_effective_time"), errors="coerce"
        )
        locked_until = (
            exit_effective_time
            if not pd.isna(exit_effective_time)
            else exit_time + pd.Timedelta(seconds=5)
        )
        accumulator.add_outcome(
            candidate,
            pd.Timestamp(candidate["fill_time"]).strftime("%Y-%m"),
            average_range_pips=float(candidate["recent_m5_avg_range_pips"]),
        )
        trade_rows.append(candidate.to_dict())
    trades = pd.DataFrame(trade_rows)
    performance = accumulator.row()
    if trades.empty:
        trades = eligible.iloc[0:0].copy()
    else:
        trades = trades.sort_values("fill_time", kind="stable").reset_index(drop=True)
    trades["cumulative_yen"] = pd.to_numeric(
        trades["result_yen"], errors="coerce"
    ).cumsum()
    trades["cumulative_pips"] = pd.to_numeric(
        trades["trade_result_pips"], errors="coerce"
    ).cumsum()
    performance.update(
        {
            "source_event_count": event_count,
            "selected_lifecycle_count": selected_lifecycle_count,
            "replaced_before_fill_count": replaced_before_fill,
            "skipped_while_locked_count": skipped_while_locked,
            "pending_order_lock_count": pending_order_lock_count,
        }
    )
    return trades, performance


def rank_replay_conditions(
    frame: pd.DataFrame,
    conditions: Iterable[PolicyCondition],
    *,
    keep_details: bool = True,
    period_start: dt.datetime | None = None,
    period_end: dt.datetime | None = None,
) -> tuple[pd.DataFrame, dict[str, tuple[pd.DataFrame, dict[str, Any]]]]:
    """Replay each candidate condition on its own eligible lifecycle.

    When ``period_start``/``period_end`` are given, each condition's
    four-period stability (``positive_period_count`` etc., see
    ``four_period_metrics``) is computed over that span exactly like the
    TP/LC tier grid already does — condition mining otherwise has no
    within-train stability check at all.
    """
    rows = []
    details: dict[str, tuple[pd.DataFrame, dict[str, Any]]] = {}
    compute_periods = period_start is not None and period_end is not None
    for condition in conditions:
        trades, performance = replay_condition(frame, condition)
        if keep_details:
            details[condition.condition_id] = (trades, performance)
        if compute_periods:
            performance = {
                **performance,
                **four_period_metrics(trades, period_start, period_end),
            }
        rows.append(
            {
                "condition_id": condition.condition_id,
                "condition_label": condition.label,
                "condition_json": json.dumps(
                    condition.to_dict(), ensure_ascii=False, sort_keys=True
                ),
                **performance,
            }
        )
    return pd.DataFrame(rows), details


def monthly_summary(trades: pd.DataFrame) -> pd.DataFrame:
    columns = (
        "month",
        "trade_count",
        "win_count",
        "profit_lock_count",
        "profit_lock_rate",
        "win_rate",
        "average_win_pips",
        "sum_pips",
        "sum_a",
        "gross_profit_yen",
        "gross_loss_yen",
        "sum_yen",
    )
    if trades.empty:
        return pd.DataFrame(columns=columns)
    work = trades.copy()
    work["month"] = pd.to_datetime(work["fill_time"]).dt.strftime("%Y-%m")
    rows = []
    for month, group in work.groupby("month", sort=True):
        wins = group[group["trade_result_pips"] > 0]
        profit_lock_count = int(group["trade_result"].eq("profit_lock").sum())
        profit = group.loc[group["result_yen"] > 0, "result_yen"].sum()
        loss = -group.loc[group["result_yen"] < 0, "result_yen"].sum()
        rows.append(
            {
                "month": month,
                "trade_count": len(group),
                "win_count": len(wins),
                "profit_lock_count": profit_lock_count,
                "profit_lock_rate": profit_lock_count / len(group),
                "win_rate": len(wins) / len(group),
                "average_win_pips": (
                    float(wins["trade_result_pips"].mean()) if len(wins) else 0.0
                ),
                "sum_pips": float(group["trade_result_pips"].sum()),
                "sum_a": float(
                    (
                        pd.to_numeric(
                            group["trade_result_pips"], errors="coerce"
                        )
                        / pd.to_numeric(
                            group["recent_m5_avg_range_pips"], errors="coerce"
                        ).where(
                            pd.to_numeric(
                                group["recent_m5_avg_range_pips"],
                                errors="coerce",
                            )
                            > 0
                        )
                    ).sum()
                ),
                "gross_profit_yen": float(profit),
                "gross_loss_yen": float(loss),
                "sum_yen": float(group["result_yen"].sum()),
            }
        )
    return pd.DataFrame(rows, columns=columns)


def condition_from_summary(row: Mapping[str, Any]) -> PolicyCondition:
    payload = row["condition_json"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    return PolicyCondition.from_dict(payload)
