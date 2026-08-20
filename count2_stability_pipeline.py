"""One-click, cache-only count2 stability selection and fixed replay.

The public launcher exposes three logical phases:

1. build or reuse the exact prior-two-year counterfactual grid;
2. select stable regions, then gate each condition and its resulting portfolio
   through the complete frozen lifecycle A/B methods;
3. replay the resulting frozen artifact on the following year.

The module never edits a live strategy and contains no OANDA download path.  A
missing causal source ledger or S5 cache therefore fails closed in the owned
stage instead of fetching data implicitly.  All date windows are half-open.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import time
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


VERSION = "count2_stability_pipeline_v1"
DEFAULT_SELECTION_START = dt.datetime(2023, 7, 30)
DEFAULT_SELECTION_END = dt.datetime(2025, 7, 30)
DEFAULT_FOLLOWING_START = dt.datetime(2025, 7, 30)
DEFAULT_FOLLOWING_END = dt.datetime(2026, 7, 30)
DEFAULT_MAX_DD_R = 20.0
DEFAULT_MIN_NEIGHBOUR_SUM_R = -5.0
DEFAULT_READ_CHUNK_SIZE = 1_000
PAIR_CHOICES = ("USD_JPY", "EUR_USD", "AUD_USD")
LOGICAL_PHASE_TOTAL = 3


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (dt.datetime, dt.date)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value.resolve())
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return str(value)


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(_json_safe(payload), ensure_ascii=False, indent=2, allow_nan=False),
        encoding="utf-8",
    )
    temporary.replace(path)


def _archive_file(path: Path) -> Path:
    if not path.exists():
        return path
    archive = path.parent / "archive"
    archive.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    destination = archive / f"{path.stem}_{stamp}{path.suffix}"
    suffix = 1
    while destination.exists():
        destination = archive / f"{path.stem}_{stamp}_{suffix}{path.suffix}"
        suffix += 1
    path.replace(destination)
    return destination


def _archive_generation(paths: Iterable[Path]) -> list[Path]:
    """Archive prior final/progress and every pipeline-owned temp residual."""
    archived: list[Path] = []
    seen: set[Path] = set()
    for raw_path in paths:
        path = Path(raw_path)
        for candidate in (
            path,
            path.with_suffix(path.suffix + ".tmp"),
            path.with_suffix(path.suffix + ".part"),
        ):
            resolved = candidate.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            if candidate.exists():
                archived.append(_archive_file(candidate))
    return archived


def _bullet_message(lines: Sequence[str]) -> str:
    return "\n".join(
        line if line.lstrip().startswith("-") else f"- {line}" for line in lines
    )


def _notice(lines: Sequence[str]) -> None:
    """Print and send a notice whose every line is a bullet."""
    message = _bullet_message(lines)
    print(message)
    # Lazy import keeps importing this orchestrator side-effect free.
    import test_win_point_usd_aud as win_point

    win_point.send_inspection_notice(message)


def pipeline_paths(args: argparse.Namespace) -> dict[str, Path]:
    folder = Path(args.output_dir)
    stem = (
        f"{args.pair}_{args.selection_start:%Y%m%d}_{args.selection_end:%Y%m%d}"
        f"_to_{args.following_start:%Y%m%d}_{args.following_end:%Y%m%d}"
    )
    return {
        "result": folder / f"count2_stability_pipeline_result_{stem}.json",
        "progress": folder / f"count2_stability_pipeline_progress_{stem}.json",
    }


def _write_progress(
    path: Path,
    *,
    args: argparse.Namespace,
    started: float,
    status: str,
    phase: str,
    completed: int,
    phase_detail: str,
    outputs: Mapping[str, Path] | None = None,
    error: str | None = None,
) -> None:
    _write_json_atomic(
        path,
        {
            "version": VERSION,
            "status": status,
            "pair": args.pair,
            "phase": phase,
            "phase_detail": phase_detail,
            "completed": completed,
            "total": LOGICAL_PHASE_TOTAL,
            "progress_percent": round(100.0 * completed / LOGICAL_PHASE_TOTAL, 3),
            "selection": {
                "start_inclusive": args.selection_start,
                "end_exclusive": args.selection_end,
            },
            "following": {
                "start_inclusive": args.following_start,
                "end_exclusive": args.following_end,
            },
            "outputs": dict(outputs or {}),
            "error": error,
            "elapsed_minutes": round((time.monotonic() - started) / 60.0, 2),
            "updated_at": dt.datetime.now().astimezone(),
        },
    )


def _grid_cli(args: argparse.Namespace) -> list[str]:
    values = [
        "--pair",
        args.pair,
        "--start",
        args.selection_start.isoformat(" "),
        "--end",
        args.selection_end.isoformat(" "),
        "--output-dir",
        str(Path(args.grid_dir)),
        "--read-chunk-size",
        str(args.read_chunk_size),
    ]
    for option, attribute in (
        ("--source-candidates", "source_candidates"),
        ("--source-events", "source_events"),
        ("--s5-cache", "selection_s5_cache"),
    ):
        value = getattr(args, attribute, None)
        if value is not None:
            values.extend((option, str(value)))
    return values


def _manifest_output_paths(manifest: Mapping[str, Any]) -> dict[str, Path]:
    raw_outputs = manifest.get("outputs")
    if not isinstance(raw_outputs, Mapping):
        return {}
    return {
        str(name): Path(str(path)).resolve()
        for name, path in raw_outputs.items()
        if isinstance(path, (str, Path)) and str(path)
    }


def _is_complete_exact_grid_manifest(
    manifest_path: Path,
    *,
    expected_config: Mapping[str, Any],
) -> bool:
    """Return true only for the precise complete, uncapped grid generation."""
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, UnicodeError, json.JSONDecodeError):
        return False
    if not isinstance(manifest, Mapping) or manifest.get("status") != "complete":
        return False
    if manifest.get("max_source_rows") is not None:
        return False
    for key, expected in expected_config.items():
        if _json_safe(manifest.get(key)) != _json_safe(expected):
            return False
    try:
        if int(manifest.get("source_rows_processed", -1)) != int(
            manifest.get("source_rows_total", -2)
        ):
            return False
    except (TypeError, ValueError):
        return False
    outputs = _manifest_output_paths(manifest)
    # Progress is an archived operational log, not an analytical grid output.
    # Its later retention must never force a multi-hour recomputation.
    required = {"paths", "aggregate", "monthly", "manifest"}
    if not required.issubset(outputs):
        return False
    if outputs["manifest"] != manifest_path.resolve():
        return False
    return all(outputs[name].is_file() for name in required)


def _ensure_selection_grid(args: argparse.Namespace) -> tuple[dict[str, Path], bool]:
    """Reuse an exact completed grid or execute the cache-only grid stage."""
    import count2_target_grid_search as grid

    grid_args = grid.parse_args(
        _grid_cli(args),
        default_start=args.selection_start,
        default_end=args.selection_end,
        default_pair=args.pair,
    )
    paths = grid.output_paths(grid_args)
    expected_config = grid._grid_config(grid_args)
    if not args.rebuild_grid and _is_complete_exact_grid_manifest(
        paths["manifest"], expected_config=expected_config
    ):
        manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
        return {
            name: path
            for name, path in _manifest_output_paths(manifest).items()
            if path.is_file()
        }, True
    original_notify = grid._notify

    def bullet_grid_notice(message: str) -> None:
        original_notify(_bullet_message(str(message).splitlines()))

    preexisting_archive = _archive_snapshot(Path(grid_args.output_dir))
    grid._notify = bullet_grid_notice
    try:
        generated = grid.run_grid_search(grid_args)
    finally:
        grid._notify = original_notify
    return _resolve_returned_paths(
        generated,
        "grid",
        preexisting_archive_paths=preexisting_archive,
    ), False


def _archive_snapshot(folder: Path) -> frozenset[Path]:
    archive = Path(folder) / "archive"
    if not archive.is_dir():
        return frozenset()
    return frozenset(path.resolve() for path in archive.iterdir() if path.is_file())


def _latest_archived_path(
    path: Path,
    *,
    excluded: frozenset[Path] = frozenset(),
) -> Path | None:
    archive = path.parent / "archive"
    if not archive.is_dir():
        return None
    candidates = [
        candidate
        for candidate in archive.glob(f"{path.stem}_*{path.suffix}")
        if candidate.is_file() and candidate.resolve() not in excluded
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda item: (item.stat().st_mtime_ns, item.name)).resolve()


def _resolve_returned_paths(
    paths: Mapping[str, Path],
    stage: str,
    *,
    preexisting_archive_paths: frozenset[Path] = frozenset(),
) -> dict[str, Path]:
    """Resolve returned files, including progress already moved to archive."""
    resolved: dict[str, Path] = {}
    for name, raw_path in paths.items():
        path = Path(raw_path).resolve()
        if not path.is_file() and "progress" in name.lower():
            archived = _latest_archived_path(
                path,
                excluded=preexisting_archive_paths,
            )
            if archived is not None:
                path = archived
            else:
                # A zero-policy lifecycle run legitimately performs no S5
                # iteration.  Older archived progress must not be attributed
                # to that run, and absence of this operational log must not
                # turn a valid zero-adoption result into a failure.
                continue
        if not path.is_file():
            raise FileNotFoundError(f"{stage} returned a missing output {name}: {path}")
        resolved[str(name)] = path
    return resolved


def _run_stability_selection(
    args: argparse.Namespace,
    grid_manifest: Path,
) -> dict[str, Path]:
    import count2_stability_selection as selection

    argv = [
        "--pair",
        args.pair,
        "--selection-start",
        args.selection_start.isoformat(" "),
        "--selection-end",
        args.selection_end.isoformat(" "),
        "--following-start",
        args.following_start.isoformat(" "),
        "--following-end",
        args.following_end.isoformat(" "),
        "--grid-manifest",
        str(grid_manifest),
        "--output-dir",
        str(Path(args.output_dir)),
        "--max-dd-r",
        str(args.max_dd_r),
        "--min-neighbour-sum-r",
        str(args.min_neighbour_sum_r),
        "--read-chunk-size",
        str(args.read_chunk_size),
    ]
    preexisting_archive = _archive_snapshot(Path(args.output_dir))
    returned = selection.main(
        argv,
        default_pair=args.pair,
        default_selection_start=args.selection_start,
        default_selection_end=args.selection_end,
        default_following_start=args.following_start,
        default_following_end=args.following_end,
    )
    return _resolve_returned_paths(
        returned,
        "stability selection",
        preexisting_archive_paths=preexisting_archive,
    )


def _run_lifecycle_train(
    args: argparse.Namespace,
    selection_artifact: Path,
) -> dict[str, Path]:
    import count2_stability_lifecycle as lifecycle

    argv = [
        "--pair",
        args.pair,
        "--selection-start",
        args.selection_start.isoformat(" "),
        "--selection-end",
        args.selection_end.isoformat(" "),
        "--following-start",
        args.following_start.isoformat(" "),
        "--following-end",
        args.following_end.isoformat(" "),
        "--selection-artifact",
        str(selection_artifact),
        "--output-dir",
        str(Path(args.output_dir)),
        "--read-chunk-size",
        str(args.read_chunk_size),
    ]
    preexisting_archive = _archive_snapshot(Path(args.output_dir))
    returned = lifecycle.train_main(
        argv,
        default_pair=args.pair,
        default_selection_start=args.selection_start,
        default_selection_end=args.selection_end,
        default_following_start=args.following_start,
        default_following_end=args.following_end,
    )
    return _resolve_returned_paths(
        returned,
        "lifecycle A/B train",
        preexisting_archive_paths=preexisting_archive,
    )


def _run_fixed_following(
    args: argparse.Namespace,
    lifecycle_artifact: Path,
) -> dict[str, Path]:
    import count2_stability_lifecycle as lifecycle

    argv = [
        "--pair",
        args.pair,
        "--selection-start",
        args.selection_start.isoformat(" "),
        "--selection-end",
        args.selection_end.isoformat(" "),
        "--following-start",
        args.following_start.isoformat(" "),
        "--following-end",
        args.following_end.isoformat(" "),
        "--lifecycle-artifact",
        str(lifecycle_artifact),
        "--output-dir",
        str(Path(args.output_dir)),
        "--grid-dir",
        str(Path(args.grid_dir)),
        "--read-chunk-size",
        str(args.read_chunk_size),
    ]
    if args.following_grid_manifest is not None:
        argv.extend(("--following-grid-manifest", str(args.following_grid_manifest)))
    preexisting_archive = _archive_snapshot(Path(args.output_dir))
    returned = lifecycle.following_main(
        argv,
        default_pair=args.pair,
        default_selection_start=args.selection_start,
        default_selection_end=args.selection_end,
        default_following_start=args.following_start,
        default_following_end=args.following_end,
    )
    return _resolve_returned_paths(
        returned,
        "fixed following replay",
        preexisting_archive_paths=preexisting_archive,
    )


def _require_output(paths: Mapping[str, Path], key: str, stage: str) -> Path:
    path = paths.get(key)
    if path is None or not Path(path).is_file():
        raise FileNotFoundError(f"{stage} did not produce required {key}: {path}")
    return Path(path).resolve()


def _prefixed(prefix: str, paths: Mapping[str, Path]) -> dict[str, Path]:
    return {f"{prefix}_{name}": Path(path).resolve() for name, path in paths.items()}


def run_pipeline(args: argparse.Namespace) -> dict[str, Path]:
    paths = pipeline_paths(args)
    Path(args.output_dir).mkdir(parents=True, exist_ok=True)
    _archive_generation(paths.values())
    started = time.monotonic()
    outputs: dict[str, Path] = {}
    current_phase = "grid"
    _notice(
        [
            f"@everyone {args.pair} count2 stability 一括検証 開始",
            f"選定期間: {args.selection_start:%Y-%m-%d} 以上～{args.selection_end:%Y-%m-%d} 未満",
            f"following期間: {args.following_start:%Y-%m-%d} 以上～{args.following_end:%Y-%m-%d} 未満",
            "処理: 1/3 grid → 2/3 安定領域＋実ライフサイクルLC A/B → 3/3 固定following",
            "Top15強制採用なし・OANDA自動取得なし・liveコード変更なし",
        ]
    )
    try:
        _write_progress(
            paths["progress"],
            args=args,
            started=started,
            status="running",
            phase="grid",
            completed=0,
            phase_detail="build_or_reuse_exact_selection_grid",
            outputs=outputs,
        )
        grid_paths, reused = _ensure_selection_grid(args)
        grid_manifest = _require_output(grid_paths, "manifest", "grid")
        outputs.update(_prefixed("grid", grid_paths))
        _write_progress(
            paths["progress"],
            args=args,
            started=started,
            status="running",
            phase="selection_and_lc_train",
            completed=1,
            phase_detail="stable_condition_selection",
            outputs=outputs,
        )
        _notice(
            [
                f"@everyone {args.pair} count2 stability 1/3 grid 完了",
                f"grid: {'既存の完全一致キャッシュを再利用' if reused else '新規計算'}",
                f"manifest: {grid_manifest}",
            ]
        )

        current_phase = "stable_condition_selection"
        selection_paths = _run_stability_selection(args, grid_manifest)
        selection_artifact = _require_output(
            selection_paths, "artifact", "stability selection"
        )
        outputs.update(_prefixed("selection", selection_paths))
        _write_progress(
            paths["progress"],
            args=args,
            started=started,
            status="running",
            phase="selection_and_lc_train",
            completed=1,
            phase_detail="fixed_policy_lifecycle_ab_train",
            outputs=outputs,
        )
        current_phase = "lifecycle_ab_train"
        lifecycle_paths = _run_lifecycle_train(args, selection_artifact)
        lifecycle_artifact = _require_output(
            lifecycle_paths, "artifact", "lifecycle A/B train"
        )
        outputs.update(_prefixed("lifecycle_train", lifecycle_paths))
        _write_progress(
            paths["progress"],
            args=args,
            started=started,
            status="running",
            phase="fixed_following",
            completed=2,
            phase_detail="frozen_conditions_and_lc_following_replay",
            outputs=outputs,
        )
        _notice(
            [
                f"@everyone {args.pair} count2 stability 2/3 安定条件選定＋LC A/B 完了",
                f"selection artifact: {selection_artifact}",
                f"lifecycle artifact: {lifecycle_artifact}",
            ]
        )

        current_phase = "fixed_following"
        following_paths = _run_fixed_following(args, lifecycle_artifact)
        following_result = _require_output(
            following_paths, "result", "fixed following replay"
        )
        outputs.update(_prefixed("following", following_paths))
        _write_progress(
            paths["progress"],
            args=args,
            started=started,
            status="complete",
            phase="complete",
            completed=3,
            phase_detail="all_logical_phases_complete",
            outputs=outputs,
        )
        archived_progress = _archive_file(paths["progress"])
        outputs["pipeline_progress_archive"] = archived_progress.resolve()
        outputs["pipeline_result"] = paths["result"].resolve()
        result_payload = {
            "version": VERSION,
            "status": "complete",
            "pair": args.pair,
            "selection": {
                "start_inclusive": args.selection_start,
                "end_exclusive": args.selection_end,
            },
            "following": {
                "start_inclusive": args.following_start,
                "end_exclusive": args.following_end,
            },
            "logical_phases": [
                "exact_prior_grid",
                "stable_selection_and_lifecycle_ab_train",
                "fixed_following_replay",
            ],
            "grid_reused": reused,
            "top15_forced": False,
            "max_dd_r_limit": args.max_dd_r,
            "worst_neighbour_sum_r_limit": args.min_neighbour_sum_r,
            "automatic_oanda_download": False,
            "live_code_modified": False,
            "outputs": outputs,
            "elapsed_minutes": round((time.monotonic() - started) / 60.0, 2),
            "completed_at": dt.datetime.now().astimezone(),
        }
        _write_json_atomic(paths["result"], result_payload)
        _notice(
            [
                f"@everyone {args.pair} count2 stability 3/3 固定following 完了",
                f"following result: {following_result}",
                f"全出力一覧: {paths['result'].resolve()}",
                "検証期間で選んだ条件・LC方式はfollowing結果で再選択していません",
            ]
        )
        return outputs
    except Exception as error:
        _write_progress(
            paths["progress"],
            args=args,
            started=started,
            status="failed",
            phase=current_phase,
            completed=min(
                LOGICAL_PHASE_TOTAL,
                2 if any(key.startswith("lifecycle_train_") for key in outputs) else 1 if outputs else 0,
            ),
            phase_detail="pipeline_failed_closed",
            outputs=outputs,
            error=f"{type(error).__name__}: {error}",
        )
        archived = _archive_generation((paths["progress"],))
        _notice(
            [
                f"@everyone {args.pair} count2 stability 一括検証 失敗",
                f"エラー種別: {type(error).__name__}",
                f"内容: {error}",
                f"progress/temp: archiveへ移動済み ({archived[0] if archived else '対象なし'})",
            ]
        )
        raise
    finally:
        # A killed atomic write can leave a .tmp/.part even when its final
        # progress file has already been archived.
        _archive_generation(
            (
                paths["progress"].with_suffix(paths["progress"].suffix + ".tmp"),
                paths["progress"].with_suffix(paths["progress"].suffix + ".part"),
                paths["result"].with_suffix(paths["result"].suffix + ".tmp"),
                paths["result"].with_suffix(paths["result"].suffix + ".part"),
            )
        )


def _parse_datetime(value: str, option: str, parser: argparse.ArgumentParser) -> dt.datetime:
    try:
        return dt.datetime.fromisoformat(value)
    except (TypeError, ValueError) as error:
        parser.error(f"{option} is invalid: {error}")


def parse_args(
    argv: list[str] | None = None,
    *,
    default_pair: str = "USD_JPY",
    default_selection_start: dt.datetime = DEFAULT_SELECTION_START,
    default_selection_end: dt.datetime = DEFAULT_SELECTION_END,
    default_following_start: dt.datetime = DEFAULT_FOLLOWING_START,
    default_following_end: dt.datetime = DEFAULT_FOLLOWING_END,
) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run count2 stable-region selection and fixed following replay"
    )
    parser.add_argument("--pair", default=default_pair, choices=PAIR_CHOICES)
    parser.add_argument(
        "--selection-start", default=default_selection_start.isoformat(" ")
    )
    parser.add_argument("--selection-end", default=default_selection_end.isoformat(" "))
    parser.add_argument(
        "--following-start", default=default_following_start.isoformat(" ")
    )
    parser.add_argument("--following-end", default=default_following_end.isoformat(" "))
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--grid-dir", type=Path, default=None)
    parser.add_argument("--source-candidates", type=Path)
    parser.add_argument("--source-events", type=Path)
    parser.add_argument("--selection-s5-cache", type=Path)
    parser.add_argument("--following-grid-manifest", type=Path)
    parser.add_argument("--max-dd-r", type=float, default=DEFAULT_MAX_DD_R)
    parser.add_argument(
        "--min-neighbour-sum-r",
        type=float,
        default=DEFAULT_MIN_NEIGHBOUR_SUM_R,
        help="Reject a plateau when its worst one-step neighbour is below this R sum.",
    )
    parser.add_argument("--read-chunk-size", type=int, default=DEFAULT_READ_CHUNK_SIZE)
    parser.add_argument(
        "--rebuild-grid",
        action="store_true",
        help="Archive and recompute even if the exact completed grid exists.",
    )
    args = parser.parse_args(argv)
    args.selection_start = _parse_datetime(
        args.selection_start, "--selection-start", parser
    )
    args.selection_end = _parse_datetime(args.selection_end, "--selection-end", parser)
    args.following_start = _parse_datetime(
        args.following_start, "--following-start", parser
    )
    args.following_end = _parse_datetime(args.following_end, "--following-end", parser)
    if args.selection_start >= args.selection_end:
        parser.error("--selection-start must be earlier than --selection-end")
    if args.selection_end != args.following_start:
        parser.error("--selection-end must equal --following-start")
    if args.following_start >= args.following_end:
        parser.error("--following-start must be earlier than --following-end")
    if not math.isfinite(args.max_dd_r) or args.max_dd_r <= 0:
        parser.error("--max-dd-r must be finite and positive")
    if (
        not math.isfinite(args.min_neighbour_sum_r)
        or args.min_neighbour_sum_r >= 0
    ):
        parser.error("--min-neighbour-sum-r must be finite and negative")
    if args.read_chunk_size <= 0:
        parser.error("--read-chunk-size must be positive")
    if args.output_dir is None:
        import tokens as tk

        args.output_dir = Path(tk.folder_path)
    args.output_dir = Path(args.output_dir).resolve()
    args.grid_dir = Path(args.grid_dir or args.output_dir).resolve()
    return args


def main(
    argv: list[str] | None = None,
    *,
    default_pair: str = "USD_JPY",
    default_selection_start: dt.datetime = DEFAULT_SELECTION_START,
    default_selection_end: dt.datetime = DEFAULT_SELECTION_END,
    default_following_start: dt.datetime = DEFAULT_FOLLOWING_START,
    default_following_end: dt.datetime = DEFAULT_FOLLOWING_END,
) -> dict[str, Path]:
    args = parse_args(
        argv,
        default_pair=default_pair,
        default_selection_start=default_selection_start,
        default_selection_end=default_selection_end,
        default_following_start=default_following_start,
        default_following_end=default_following_end,
    )
    return run_pipeline(args)


if __name__ == "__main__":
    main()
