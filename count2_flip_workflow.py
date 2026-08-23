# 最終更新: 2026-08-23 08:22 JST
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
    FEATURE_FIELDS,
    FLIP_VERSION,
    FlipPathConfig,
    FlipPathInspector,
    PolicyCondition,
    RankedPolicyCondition,
    TierExecutionConfig,
    TradeCombo,
    add_feature_buckets,
    condition_mask,
    expected_role,
    tier_for_rank,
)
from count2_target_grid_search import (
    _bound_inspector_before,
    _load_typed_s5_inspector,
    _s5_coverage_errors,
)


Notice = Callable[[str], None]


MIN_TRADE_RANGE_FRACTION_A = 0.25
MIN_TRADE_RANGE_FRACTION_PIPS = 2.0


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
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
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
    for chunk in pd.read_csv(
        source,
        usecols=lambda column: column in available_columns,
        chunksize=chunksize,
        low_memory=False,
    ):
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
            & work["recent_m5_avg_range_pips"]
            .mul(MIN_TRADE_RANGE_FRACTION_A)
            .ge(MIN_TRADE_RANGE_FRACTION_PIPS)
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
        )
        for column, completion in causal_specs:
            source_time = pd.to_datetime(
                work[column], format="mixed", errors="coerce"
            )
            future = source_time.notna() & (source_time + completion > decision)
            if future.any():
                bad = work.loc[future, ["event_id", "decision_time", column]].iloc[0]
                raise ValueError(
                    f"future feature in {source.name}: {bad.to_dict()}"
                )
        frames.append(work)
        if max_rows is not None and rows_read >= max_rows:
            break
    if not frames:
        raise ValueError(f"no eligible flip_predict candidates in {source}")
    result = pd.concat(frames, ignore_index=True)
    result.sort_values(
        ["decision_time", "event_id", "distance_rank", "line_price"],
        inplace=True,
        kind="stable",
    )
    result.reset_index(drop=True, inplace=True)
    result["source_role"] = [
        expected_role(value)
        for value in result["line_latest_constituent_peak_direction"]
    ]
    result["predicted_role"] = [
        expected_role(value) for value in result["peak_direction"]
    ]
    return add_feature_buckets(result)


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
        ),
        metadata,
    )


class PerformanceAccumulator:
    def __init__(self) -> None:
        self.candidates = 0
        self.fills = 0
        self.trades = 0
        self.wins = 0
        self.sum_win_pips = 0.0
        self.sum_loss_pips = 0.0
        self.sum_pips = 0.0
        self.sum_yen = 0.0
        self.gross_profit_yen = 0.0
        self.gross_loss_yen = 0.0
        self.month_yen: dict[str, float] = defaultdict(float)

    def add_candidate(self, path: Mapping[str, Any]) -> None:
        self.candidates += 1
        self.fills += int(bool(path.get("order_filled")))

    def add_outcome(self, outcome: Mapping[str, Any], month: str) -> None:
        pips = float(outcome["trade_result_pips"])
        yen = float(outcome["result_yen"])
        self.trades += 1
        self.sum_pips += pips
        self.sum_yen += yen
        self.month_yen[month] += yen
        if pips > 0:
            self.wins += 1
            self.sum_win_pips += pips
        elif pips < 0:
            self.sum_loss_pips += pips
        if yen > 0:
            self.gross_profit_yen += yen
        elif yen < 0:
            self.gross_loss_yen += -yen

    def row(self) -> dict[str, Any]:
        positive_months = sum(value > 0 for value in self.month_yen.values())
        active_months = len(self.month_yen)
        return {
            "candidate_count": self.candidates,
            "order_fill_count": self.fills,
            "order_fill_rate": (
                self.fills / self.candidates if self.candidates else 0.0
            ),
            "completed_trade_count": self.trades,
            "win_count": self.wins,
            "win_rate": self.wins / self.trades if self.trades else 0.0,
            "average_win_pips": (
                self.sum_win_pips / self.wins if self.wins else 0.0
            ),
            "average_loss_pips": (
                self.sum_loss_pips / (self.trades - self.wins)
                if self.trades > self.wins
                else 0.0
            ),
            "sum_pips": self.sum_pips,
            "gross_profit_yen": self.gross_profit_yen,
            "gross_loss_yen": self.gross_loss_yen,
            "sum_yen": self.sum_yen,
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
        }


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
    *,
    pair: str,
    phase: str,
    period_start: dt.datetime,
    progress_file: Path,
    started: float,
    notify: Notice | None,
) -> pd.DataFrame:
    path_configs = tuple(path_configs)
    trade_combos = tuple(trade_combos)
    states = {
        (config.config_id, combo.combo_id): {
            "accumulator": PerformanceAccumulator(),
            "locked_until": pd.NaT,
            "selected_lifecycle_count": 0,
            "replaced_before_fill_count": 0,
            "skipped_while_locked_count": 0,
        }
        for config in path_configs
        for combo in trade_combos
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
        for config in path_configs:
            active_combos = [
                combo
                for combo in trade_combos
                if pd.isna(states[(config.config_id, combo.combo_id)]["locked_until"])
                or decision_time
                >= states[(config.config_id, combo.combo_id)]["locked_until"]
            ]
            for combo in trade_combos:
                state = states[(config.config_id, combo.combo_id)]
                if combo not in active_combos:
                    state["skipped_while_locked_count"] += 1
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
                state = states[(config.config_id, combo.combo_id)]
                accumulator = state["accumulator"]
                state["selected_lifecycle_count"] += 1
                accumulator.add_candidate(path)
                if path.get("replaced_before_fill"):
                    state["replaced_before_fill_count"] += 1
                if not path.get("order_filled"):
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
                    fill_month = pd.Timestamp(path["fill_time"]).strftime("%Y-%m")
                    accumulator.add_outcome(outcome, fill_month)
                    exit_time = pd.to_datetime(
                        outcome.get("exit_time"), errors="coerce"
                    )
                    if not pd.isna(exit_time):
                        state["locked_until"] = exit_time + pd.Timedelta(seconds=5)
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
            state = states[(config.config_id, combo.combo_id)]
            rows.append(
                {
                    "path_config_id": config.config_id,
                    "order_wait_minutes": config.order_wait_minutes,
                    "combo_id": combo.combo_id,
                    "tp_a": combo.tp_a,
                    "lc_a": combo.lc_a,
                    "configured_rr": combo.configured_rr,
                    **state["accumulator"].row(),
                    "source_event_count": total,
                    "selected_lifecycle_count": state[
                        "selected_lifecycle_count"
                    ],
                    "replaced_before_fill_count": state[
                        "replaced_before_fill_count"
                    ],
                    "skipped_while_locked_count": state[
                        "skipped_while_locked_count"
                    ],
                }
            )
    return pd.DataFrame(rows)


def choose_global_policy(
    summary: pd.DataFrame,
    *,
    minimum_trades: int = 100,
) -> pd.Series:
    eligible = summary[
        summary["completed_trade_count"].ge(minimum_trades)
        & summary["profit_factor_yen"].ge(1.0)
        & summary["positive_month_rate"].ge(0.5)
    ]
    if eligible.empty:
        eligible = summary[summary["completed_trade_count"].ge(minimum_trades)]
    if eligible.empty:
        eligible = summary
    return eligible.sort_values(
        ["sum_yen", "positive_month_rate", "profit_factor_yen", "sum_pips"],
        ascending=[False, False, False, False],
        kind="stable",
    ).iloc[0]


PATH_EXPORT_COLUMNS = (
    "path_status",
    "approach_direction",
    "order_direction",
    "order_filled",
    "order_deadline",
    "replaced_before_fill",
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
    "trade_result",
    "trade_result_pips",
    "result_r",
    "result_yen",
    "exit_time",
    "actual_entry_price",
    "actual_exit_price",
    "max_favorable_pips",
    "max_adverse_pips",
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
) -> tuple[RankedPolicyCondition, ...]:
    """Freeze the raw top-N lifecycle rules, excluding the ALL baseline."""
    if limit < 1:
        raise ValueError("top condition limit must be positive")
    configs = tuple(tier_configs)
    ranked = summary[~summary["condition_id"].eq("ALL")].copy()
    ranked.sort_values(
        [
            "sum_yen",
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
            f"top-{limit} policy requires {limit} distinct non-ALL conditions"
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


def select_top_condition_policy_candidates(
    frame: pd.DataFrame,
    ranked_conditions: Iterable[RankedPolicyCondition],
    tier_configs: Iterable[TierExecutionConfig],
) -> pd.DataFrame:
    """Apply the frozen top-condition OR and choose one line per FC2 event."""
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
    result["top15_or_triggered"] = result["matched_condition_count"].gt(0)
    result["tier_tp_a"] = result["signal_tier"].map(
        {tier: config.tp_a for tier, config in config_by_tier.items()}
    )
    result["tier_rr"] = result["signal_tier"].map(
        {tier: config.rr for tier, config in config_by_tier.items()}
    )
    result["tier_lc_a"] = result["signal_tier"].map(
        {tier: config.trade_combo.lc_a for tier, config in config_by_tier.items()}
    )
    result["policy_line_selection"] = "highest_tier_then_nearest_line"
    eligible = result[result["top15_or_triggered"]].copy()
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
) -> pd.DataFrame:
    """Inspect one selected top-15 OR line per event with its tier TP/RR."""
    config_by_tier = {config.tier: config for config in tier_configs}
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
        output.update(path["outcomes"].get(combo.combo_id, {}))
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


def performance_from_frame(frame: pd.DataFrame, mask: np.ndarray) -> dict[str, Any]:
    selected = frame.loc[mask]
    candidate_count = len(selected)
    fill_count = int(selected["order_filled"].fillna(False).astype(bool).sum())
    trades = selected[
        selected["path_status"].eq("trade")
        & pd.to_numeric(selected["trade_result_pips"], errors="coerce").notna()
    ].copy()
    trade_count = len(trades)
    if trade_count:
        pips = pd.to_numeric(trades["trade_result_pips"], errors="coerce")
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
        "win_rate": win_count / trade_count if trade_count else 0.0,
        "average_win_pips": float(pips[wins].mean()) if win_count else 0.0,
        "average_loss_pips": float(pips[losses].mean()) if loss_count else 0.0,
        "sum_pips": float(pips.sum()),
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
    trades = frame["path_status"].eq("trade").to_numpy() & np.isfinite(pips)
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
        wins = selected_pips > 0
        losses = selected_pips < 0
        win_count = int(wins.sum())
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
            "win_rate": win_count / trade_count if trade_count else 0.0,
            "average_win_pips": (
                float(selected_pips[wins].mean()) if win_count else 0.0
            ),
            "average_loss_pips": (
                float(selected_pips[losses].mean()) if loss_count else 0.0
            ),
            "sum_pips": float(selected_pips.sum()),
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
) -> tuple[pd.DataFrame, dict[str, Any]]:
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
    accumulator = PerformanceAccumulator()
    for _event_id, group in eligible.groupby("event_id", sort=False):
        event_count += 1
        decision_time = pd.Timestamp(group.iloc[0]["decision_time"])
        if not pd.isna(locked_until) and decision_time < locked_until:
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
        locked_until = exit_time + pd.Timedelta(seconds=5)
        accumulator.add_outcome(
            candidate,
            pd.Timestamp(candidate["fill_time"]).strftime("%Y-%m"),
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
        }
    )
    return trades, performance


def rank_replay_conditions(
    frame: pd.DataFrame,
    conditions: Iterable[PolicyCondition],
    *,
    keep_details: bool = True,
) -> tuple[pd.DataFrame, dict[str, tuple[pd.DataFrame, dict[str, Any]]]]:
    rows = []
    details: dict[str, tuple[pd.DataFrame, dict[str, Any]]] = {}
    for condition in conditions:
        trades, performance = replay_condition(frame, condition)
        if keep_details:
            details[condition.condition_id] = (trades, performance)
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
        "win_rate",
        "average_win_pips",
        "sum_pips",
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
        profit = group.loc[group["result_yen"] > 0, "result_yen"].sum()
        loss = -group.loc[group["result_yen"] < 0, "result_yen"].sum()
        rows.append(
            {
                "month": month,
                "trade_count": len(group),
                "win_count": len(wins),
                "win_rate": len(wins) / len(group),
                "average_win_pips": (
                    float(wins["trade_result_pips"].mean()) if len(wins) else 0.0
                ),
                "sum_pips": float(group["trade_result_pips"].sum()),
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
