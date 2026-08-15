"""Rank a completed prior-two-year count2 grid without rerunning outcomes.

The grid aggregate contains every causal M5/H1 morphology condition, every
same-feature M5 x H1 interaction, and every entry-rank x offset x TP x LC
combination.  This module applies explicit
minimum guards, keeps the best parameter combination per condition, and emits
separate risk-normalized-yen and raw-pips Top lists.  A condition appearing in
both lists receives the ``BOTH_`` order-name prefix.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd

import test_win_point_usd_aud as win_point
import tokens as tk


DEFAULT_START = dt.datetime(2023, 7, 30)
DEFAULT_END = dt.datetime(2025, 7, 30)
DEFAULT_TOP = 15

REQUIRED_COLUMNS = {
    "grid_version",
    "segment",
    "condition_id",
    "condition_source",
    "condition_field",
    "condition_value",
    "condition_label",
    "combo_id",
    "entry_candidate_rank",
    "entry_offset_range_multiplier",
    "tp_range_multiplier",
    "lc_range_multiplier",
    "configured_rr",
    "completed_count",
    "positive_rate_completed",
    "outcome_coverage_rate",
    "profit_factor_r",
    "average_effective_rr",
    "sum_yen",
    "sum_pips",
    "active_month_count",
    "positive_month_count",
    "positive_month_rate",
    "worst_month_r",
}


def parse_args(
    argv: list[str] | None = None,
    *,
    default_pair: str = "USD_JPY",
    default_start: dt.datetime = DEFAULT_START,
    default_end: dt.datetime = DEFAULT_END,
) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rank the causal prior-two-year foot-count-2 grid"
    )
    parser.add_argument("--pair", default=default_pair)
    parser.add_argument("--start", default=default_start.isoformat(" "))
    parser.add_argument("--end", default=default_end.isoformat(" "))
    parser.add_argument("--source", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path(tk.folder_path))
    parser.add_argument("--top", type=int, default=DEFAULT_TOP)
    parser.add_argument("--min-completed", type=int, default=100)
    parser.add_argument("--min-win-rate", type=float, default=0.40)
    parser.add_argument("--min-rr", type=float, default=1.20)
    parser.add_argument("--min-profit-factor", type=float, default=1.10)
    parser.add_argument("--min-outcome-coverage", type=float, default=0.95)
    parser.add_argument(
        "--condition-scope",
        choices=("shape", "all"),
        default="shape",
        help=(
            "shape ranks M5/H1 morphology and their interactions only; "
            "all also admits legacy line/session/stair conditions"
        ),
    )
    args = parser.parse_args(argv)
    args.pair = str(args.pair).upper()
    args.start = pd.Timestamp(args.start).to_pydatetime()
    args.end = pd.Timestamp(args.end).to_pydatetime()
    if args.end <= args.start:
        raise ValueError("--end must be after --start")
    if args.top <= 0 or args.min_completed <= 0:
        raise ValueError("--top and --min-completed must be positive")
    for name in ("min_win_rate", "min_rr", "min_profit_factor", "min_outcome_coverage"):
        value = float(getattr(args, name))
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"--{name.replace('_', '-')} must be finite and non-negative")
    return args


def _archive(path: Path) -> Path:
    if not path.exists():
        return path
    folder = path.parent / "archive"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    destination = folder / f"{path.stem}_{stamp}{path.suffix}"
    number = 1
    while destination.exists():
        destination = folder / f"{path.stem}_{stamp}_{number}{path.suffix}"
        number += 1
    path.replace(destination)
    return destination


def _grid_manifest_path(source: Path) -> Path:
    prefix = "count2_target_grid_aggregate_"
    if not source.name.startswith(prefix) or source.suffix.lower() != ".csv":
        raise ValueError(f"Unexpected aggregate filename: {source.name}")
    suffix = source.name.removeprefix(prefix).removesuffix(".csv")
    return source.with_name(f"count2_target_grid_manifest_{suffix}.json")


def _load_complete_grid_manifest(
    source: Path,
    args: argparse.Namespace,
) -> tuple[Path, dict[str, Any]]:
    """Reject development/partial grids before they can enter a ranking."""
    manifest_path = _grid_manifest_path(source)
    if not manifest_path.is_file():
        raise FileNotFoundError(
            f"Matching completed grid manifest not found: {manifest_path}"
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_version = (
        f"{args.pair.lower()}_count2_entry_tp_lc_grid_v9_m5_h1_shape"
    )
    expected_start = args.start.isoformat(" ")
    expected_end = args.end.isoformat(" ")
    if (
        manifest.get("status") != "complete"
        or manifest.get("version") != expected_version
        or str(manifest.get("pair")) != args.pair
        or str(manifest.get("start")) != expected_start
        or str(manifest.get("end")) != expected_end
    ):
        raise ValueError(
            f"Grid manifest does not match the requested complete period: "
            f"{manifest_path}"
        )
    if manifest.get("max_source_rows") is not None:
        raise ValueError(
            f"Development max-source-rows grid cannot be ranked: {manifest_path}"
        )
    try:
        processed = int(manifest["source_rows_processed"])
        total = int(manifest["source_rows_total"])
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(
            f"Grid manifest lacks full-row counts: {manifest_path}"
        ) from error
    if total <= 0 or processed != total:
        raise ValueError(
            f"Incomplete grid cannot be ranked: processed={processed}, total={total}"
        )
    recorded_output = (manifest.get("outputs") or {}).get("aggregate")
    if recorded_output is None or Path(recorded_output).resolve() != source.resolve():
        raise ValueError(
            f"Grid manifest/output mismatch: {manifest_path}"
        )
    return manifest_path, manifest


def _discover_source(args: argparse.Namespace) -> Path:
    if args.source is not None:
        source = args.source
    else:
        pattern = (
            f"count2_target_grid_aggregate_{args.pair}_"
            f"{args.start:%Y%m%d}_{args.end:%Y%m%d}_g*.csv"
        )
        matches = sorted(
            args.output_dir.glob(pattern),
            key=lambda path: path.stat().st_mtime_ns,
            reverse=True,
        )
        if not matches:
            raise FileNotFoundError(
                "No matching completed aggregate CSV: " + pattern
            )
        rejected: list[str] = []
        source = None
        for candidate in matches:
            try:
                _load_complete_grid_manifest(candidate.resolve(), args)
            except (FileNotFoundError, ValueError, json.JSONDecodeError) as error:
                rejected.append(f"{candidate.name}: {error}")
                continue
            source = candidate
            break
        if source is None:
            raise ValueError(
                "No complete full-period aggregate/manifest pair was found: "
                + " | ".join(rejected[:5])
            )
    source = source.resolve()
    if not source.is_file() or source.name.endswith((".part", ".tmp")):
        raise FileNotFoundError(f"Completed aggregate CSV not found: {source}")
    return source


def _output_paths(args: argparse.Namespace) -> dict[str, Path]:
    stem = f"{args.pair}_{args.start:%Y%m%d}_{args.end:%Y%m%d}"
    scope_suffix = "" if args.condition_scope == "shape" else "_all"
    folder = args.output_dir
    return {
        "yen": folder / f"count2_prior2y_top_yen_{stem}{scope_suffix}.csv",
        "pips": folder / f"count2_prior2y_top_pips_{stem}{scope_suffix}.csv",
        "manifest": folder / f"count2_prior2y_ranking_{stem}{scope_suffix}.json",
    }


def _safe_name(value: Any) -> str:
    text = str(value).strip()
    return "".join(character if character.isalnum() else "_" for character in text).strip("_")


def _eligible_rows(frame: pd.DataFrame, args: argparse.Namespace) -> pd.DataFrame:
    work = frame[frame["segment"].astype(str).eq("full")].copy()
    if args.condition_scope == "shape":
        work = work[
            work["condition_source"].astype(str).isin(
                {"FC2", "H1_PAIR", "M5_FC2_X_H1_PAIR"}
            )
        ].copy()
    numeric = [
        "completed_count",
        "positive_rate_completed",
        "outcome_coverage_rate",
        "profit_factor_r",
        "average_effective_rr",
        "sum_yen",
        "sum_pips",
        "active_month_count",
        "positive_month_count",
        "positive_month_rate",
        "worst_month_r",
    ]
    for column in numeric:
        work[column] = pd.to_numeric(work[column], errors="coerce")
    work = work[
        (work["completed_count"] >= args.min_completed)
        & (work["positive_rate_completed"] >= args.min_win_rate)
        & (work["average_effective_rr"] >= args.min_rr)
        & (work["profit_factor_r"] >= args.min_profit_factor)
        & (work["outcome_coverage_rate"] >= args.min_outcome_coverage)
        & (work["sum_yen"] > 0)
        & (work["sum_pips"] > 0)
    ].copy()
    if work.empty:
        raise ValueError("No grid rows pass the requested ranking guards")
    return work


def _top_per_condition(
    eligible: pd.DataFrame,
    *,
    metric: str,
    top: int,
) -> pd.DataFrame:
    tie_breakers = (
        [metric, "positive_month_rate", "worst_month_r", "profit_factor_r", "completed_count"]
        + (["sum_pips"] if metric == "sum_yen" else ["sum_yen"])
    )
    ordered = eligible.sort_values(
        tie_breakers,
        ascending=[False] * len(tie_breakers),
        kind="stable",
    )
    best = ordered.drop_duplicates("condition_id", keep="first").head(top).copy()
    best.insert(0, "rank", range(1, len(best) + 1))
    best.insert(1, "ranking_metric", metric)
    return best


def build_rankings(frame: pd.DataFrame, args: argparse.Namespace) -> tuple[pd.DataFrame, pd.DataFrame]:
    missing = REQUIRED_COLUMNS.difference(frame.columns)
    if missing:
        raise ValueError(
            "Aggregate CSV is missing required columns: " + ", ".join(sorted(missing))
        )
    versions = set(frame["grid_version"].dropna().astype(str))
    expected_version = f"{args.pair.lower()}_count2_entry_tp_lc_grid_v9_m5_h1_shape"
    if versions != {expected_version}:
        raise ValueError(
            f"Aggregate version mismatch: expected {expected_version}, got {sorted(versions)}"
        )
    sources = set(frame["condition_source"].dropna().astype(str))
    required_sources = {"FC2", "H1_PAIR", "M5_FC2_X_H1_PAIR"}
    if not required_sources.issubset(sources):
        raise ValueError(
            "Aggregate does not contain the complete M5/H1 shape catalog: "
            + ", ".join(sorted(required_sources.difference(sources)))
        )
    eligible = _eligible_rows(frame, args)
    yen = _top_per_condition(eligible, metric="sum_yen", top=args.top)
    pips = _top_per_condition(eligible, metric="sum_pips", top=args.top)
    both = set(yen["condition_id"]).intersection(pips["condition_id"])
    for ranking in (yen, pips):
        ranking.insert(
            2,
            "order_name",
            ranking.apply(
                lambda row: (
                    ("BOTH_" if row["condition_id"] in both else "")
                    + _safe_name(row["condition_id"])
                    + "_R"
                    + str(int(row["entry_candidate_rank"]))
                ),
                axis=1,
            ),
        )
    return yen, pips


def _write_csv_atomic(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    if temporary.exists():
        _archive(temporary)
    frame.to_csv(temporary, index=False, encoding="utf-8-sig")
    temporary.replace(path)


def _ranking_notices(pair: str, label: str, ranking: pd.DataFrame) -> list[str]:
    header = f"{pair} prior-2y foot count 2 {label} Top{len(ranking)}"
    result_lines: list[str] = []
    for _, row in ranking.iterrows():
        result_lines.append(
            "- "
            + str(int(row["rank"]))
            + ". "
            + str(row["order_name"])
            + " | condition="
            + str(row["condition_id"])
            + " | entry="
            + str(int(row["entry_candidate_rank"]))
            + " offset="
            + f"{float(row['entry_offset_range_multiplier']):g}A"
            + " TP="
            + f"{float(row['tp_range_multiplier']):g}A"
            + " LC="
            + f"{float(row['lc_range_multiplier']):g}A"
            + " | 円="
            + f"{float(row['sum_yen']):.0f}"
            + " pips="
            + f"{float(row['sum_pips']):.2f}"
            + " 勝率="
            + f"{100 * float(row['positive_rate_completed']):.1f}%"
        )
    messages: list[str] = []
    current = header
    for line in result_lines:
        if len(current) + len(line) + 1 > 1800:
            messages.append(current)
            current = header + "（続き）\n" + line
        else:
            current += "\n" + line
    messages.append(current)
    return messages


def run(args: argparse.Namespace) -> dict[str, Path]:
    source = _discover_source(args)
    expected_stem = f"{args.pair}_{args.start:%Y%m%d}_{args.end:%Y%m%d}"
    if expected_stem not in source.name:
        raise ValueError(
            f"Aggregate filename does not match requested period: {source.name}"
        )
    grid_manifest_path, grid_manifest = _load_complete_grid_manifest(source, args)
    # The aggregate can exceed a gigabyte after M5 x H1 interactions.  Load
    # only fields needed by the guards/ranking rather than materializing all
    # diagnostic metric columns.
    frame = pd.read_csv(
        source,
        usecols=sorted(REQUIRED_COLUMNS),
        low_memory=False,
    )
    yen, pips = build_rankings(frame, args)
    paths = _output_paths(args)
    for path in paths.values():
        _archive(path)
    manifest = {
        "pair": args.pair,
        "start_inclusive": args.start,
        "end_exclusive": args.end,
        "source": str(source),
        "source_size": source.stat().st_size,
        "source_grid_manifest": str(grid_manifest_path),
        "source_grid_created_at": grid_manifest.get("created_at"),
        "guards": {
            "min_completed": args.min_completed,
            "min_win_rate": args.min_win_rate,
            "min_rr": args.min_rr,
            "min_profit_factor": args.min_profit_factor,
            "min_outcome_coverage": args.min_outcome_coverage,
            "positive_yen_and_pips_required": True,
            "condition_scope": args.condition_scope,
        },
        "selection": {
            "best_grid_combination_per_condition": True,
            "yen_top": len(yen),
            "pips_top": len(pips),
            "both_condition_count": len(set(yen["condition_id"]).intersection(pips["condition_id"])),
            "future_data_read": False,
        },
        "outputs": {key: str(value) for key, value in paths.items()},
    }
    try:
        _write_csv_atomic(yen, paths["yen"])
        _write_csv_atomic(pips, paths["pips"])
        temporary = paths["manifest"].with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        temporary.replace(paths["manifest"])
    except Exception as error:
        for path in paths.values():
            _archive(path)
            _archive(path.with_suffix(path.suffix + ".tmp"))
        win_point.send_inspection_notice(
            "\n".join([
                f"{args.pair} prior-2y foot count 2 ranking 異常終了",
                f"- エラー種別: {type(error).__name__}",
                f"- 内容: {error}",
                "- temp/途中出力: archiveへ移動済み",
            ])
        )
        raise
    lines = [
        f"{args.pair} prior-2y foot count 2 ranking 完了",
        f"- 期間: {args.start:%Y-%m-%d} から {args.end:%Y-%m-%d} 未満",
        f"- 円損益Top: {len(yen)}件",
        f"- pips損益Top: {len(pips)}件",
        f"- BOTH条件: {manifest['selection']['both_condition_count']}件",
        f"- 円損益CSV: {paths['yen']}",
        f"- pips損益CSV: {paths['pips']}",
    ]
    message = "\n".join(lines)
    print(message)
    win_point.send_inspection_notice(message)
    for ranking_message in _ranking_notices(args.pair, "円損益順", yen):
        win_point.send_inspection_notice(ranking_message)
    for ranking_message in _ranking_notices(args.pair, "pips損益順", pips):
        win_point.send_inspection_notice(ranking_message)
    return paths


def main(
    argv: list[str] | None = None,
    *,
    default_pair: str = "USD_JPY",
    default_start: dt.datetime = DEFAULT_START,
    default_end: dt.datetime = DEFAULT_END,
) -> dict[str, Path]:
    return run(
        parse_args(
            argv,
            default_pair=default_pair,
            default_start=default_start,
            default_end=default_end,
        )
    )


if __name__ == "__main__":
    main()
