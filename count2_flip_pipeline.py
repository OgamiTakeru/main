# 最新更新日時: 2026-08-25 15:35 JST
"""One launcher for separated flip_predict analysis and fixed replay."""

from __future__ import annotations

import argparse
import datetime as dt
import time
from pathlib import Path
from typing import Any

import pandas as pd

import send_notice as notice
import test_win_point_usd_aud as win_point
import tokens as tk
from count2_flip_core import FLIP_VERSION
from count2_flip_analysis import (
    DEFAULT_OOS_END,
    DEFAULT_OOS_START,
    DEFAULT_TRAIN_END,
    DEFAULT_TRAIN_START,
    analysis_output_paths,
    run_analysis,
)
from count2_flip_replay import run_fixed_replay
from count2_flip_workflow import archive_file, write_progress


def parse_args(
    argv: list[str] | None = None,
    *,
    default_pair: str = "USD_JPY",
    default_train_start: dt.datetime = DEFAULT_TRAIN_START,
    default_train_end: dt.datetime = DEFAULT_TRAIN_END,
    default_oos_start: dt.datetime = DEFAULT_OOS_START,
    default_oos_end: dt.datetime = DEFAULT_OOS_END,
) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analyze flip_predict and replay the frozen policy"
    )
    parser.add_argument("--pair", default=default_pair)
    parser.add_argument("--train-start", default=default_train_start.isoformat(" "))
    parser.add_argument("--train-end", default=default_train_end.isoformat(" "))
    parser.add_argument("--oos-start", default=default_oos_start.isoformat(" "))
    parser.add_argument("--oos-end", default=default_oos_end.isoformat(" "))
    parser.add_argument("--output-dir", type=Path, default=Path(tk.folder_path))
    parser.add_argument("--max-train-rows", type=int)
    parser.add_argument("--max-oos-rows", type=int)
    parser.add_argument("--no-notify", action="store_true")
    args = parser.parse_args(argv)
    args.pair = str(args.pair).upper()
    for field in ("train_start", "train_end", "oos_start", "oos_end"):
        setattr(args, field, pd.Timestamp(getattr(args, field)).to_pydatetime())
    if args.train_start >= args.train_end or args.oos_start >= args.oos_end:
        parser.error("period starts must be earlier than ends")
    if args.train_end != args.oos_start:
        parser.error("--train-end must equal --oos-start")
    if args.max_train_rows is not None and args.max_train_rows < 1:
        parser.error("--max-train-rows must be positive")
    if args.max_oos_rows is not None and args.max_oos_rows < 1:
        parser.error("--max-oos-rows must be positive")
    if args.max_train_rows is not None or args.max_oos_rows is not None:
        parser.error(
            "partial row caps are disabled for formal full-period flip_predict outputs"
        )
    return args


def _archive_residual_temps(output_dir: Path) -> list[Path]:
    archived = []
    for path in output_dir.glob(f"{FLIP_VERSION}*.tmp"):
        destination = archive_file(path)
        if destination is not None:
            archived.append(destination)
    return archived


def run_pipeline(args: argparse.Namespace) -> dict[str, Any]:
    started = time.monotonic()
    notify = not args.no_notify
    paths = analysis_output_paths(
        args.output_dir,
        args.pair,
        args.train_start,
        args.train_end,
        args.oos_start,
        args.oos_end,
    )
    try:
        analysis = run_analysis(
            args.pair,
            train_start=args.train_start,
            train_end=args.train_end,
            oos_start=args.oos_start,
            oos_end=args.oos_end,
            output_dir=args.output_dir,
            max_rows=args.max_train_rows,
            notify=notify,
        )
        replay = run_fixed_replay(
            args.pair,
            train_start=args.train_start,
            train_end=args.train_end,
            oos_start=args.oos_start,
            oos_end=args.oos_end,
            output_dir=args.output_dir,
            artifact_path=analysis["artifact_path"],
            max_rows=args.max_oos_rows,
            notify=notify,
            progress_file=paths["progress"],
            started=started,
        )
        _archive_residual_temps(args.output_dir)
        return {"analysis": analysis, "replay": replay}
    except Exception as error:
        try:
            write_progress(
                paths["progress"],
                pair=args.pair,
                status="failed",
                phase="failed",
                started=started,
                error=f"{type(error).__name__}: {error}",
            )
            archive_file(paths["progress"])
            _archive_residual_temps(args.output_dir)
        finally:
            if notify:
                win_point.send_inspection_notice(
                    "\n".join(
                        (
                            f"{args.pair} flip_predict inspection failed",
                            f"- error type: {type(error).__name__}",
                            f"- detail: {error}",
                        )
                    )
                )
        raise


def main(
    argv: list[str] | None = None,
    *,
    default_pair: str = "USD_JPY",
    default_train_start: dt.datetime = DEFAULT_TRAIN_START,
    default_train_end: dt.datetime = DEFAULT_TRAIN_END,
    default_oos_start: dt.datetime = DEFAULT_OOS_START,
    default_oos_end: dt.datetime = DEFAULT_OOS_END,
) -> dict[str, Any]:
    args = parse_args(
        argv,
        default_pair=default_pair,
        default_train_start=default_train_start,
        default_train_end=default_train_end,
        default_oos_start=default_oos_start,
        default_oos_end=default_oos_end,
    )
    with notice.inspection_notice_scope():
        return run_pipeline(args)


if __name__ == "__main__":
    main()
