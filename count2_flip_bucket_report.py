# 最新更新日時: 2026-08-26 JST
"""Report how each pair's candidates actually spread across feature buckets.

Bucket edges are only useful if they split a pair's real distribution.  An
edge set that dumps 76% of candidates into one bucket cannot discriminate
between events, which is what the original round-number strength edges did.

Run this before editing ``PAIR_BUCKET_OVERRIDES`` in count2_flip_core.py, so
a pair's edges are chosen from its own measured distribution rather than
copied from another pair.

    python count2_flip_bucket_report.py --pair AUD_USD
    python count2_flip_bucket_report.py --pair USD_JPY --pair AUD_USD
"""

from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

import pandas as pd

import tokens as tk
from count2_flip_analysis import DEFAULT_TRAIN_END, DEFAULT_TRAIN_START
from count2_flip_core import bucket_specs_for_pair
from count2_flip_workflow import candidate_source_path


# A bucket holding at least this share of a pair's candidates is flagged as
# dominant: the feature is close to constant and cannot separate events.
DOMINANT_BUCKET_SHARE = 0.60
# A bucket below this share rarely reaches the minimum-trade gate on its own.
THIN_BUCKET_SHARE = 0.02


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Report feature bucket occupancy per pair"
    )
    parser.add_argument(
        "--pair",
        action="append",
        dest="pairs",
        default=None,
        help="pair to report; repeat for several (default: the usual three)",
    )
    parser.add_argument("--start", default=DEFAULT_TRAIN_START.isoformat(" "))
    parser.add_argument("--end", default=DEFAULT_TRAIN_END.isoformat(" "))
    parser.add_argument("--output-dir", type=Path, default=Path(tk.folder_path))
    parser.add_argument(
        "--csv",
        type=Path,
        default=None,
        help="also write the full occupancy table to this CSV",
    )
    args = parser.parse_args(argv)
    args.pairs = [
        str(pair).upper()
        for pair in (args.pairs or ["AUD_USD", "EUR_USD", "USD_JPY"])
    ]
    for field in ("start", "end"):
        setattr(args, field, pd.Timestamp(getattr(args, field)).to_pydatetime())
    if args.start >= args.end:
        parser.error("--start must be earlier than --end")
    return args


def bucket_occupancy(
    pair: str,
    start: dt.datetime,
    end: dt.datetime,
    output_dir: Path,
) -> pd.DataFrame:
    """Return one row per (feature, bucket) with that bucket's share.

    Reads the raw candidate ledger rather than the filtered trade list, so
    the shares describe every event the search may condition on -- not only
    the subset that happened to fill.
    """
    source = candidate_source_path(pair, start, end, output_dir)
    if not source.exists():
        raise FileNotFoundError(f"no candidate ledger for {pair}: {source}")
    specs = bucket_specs_for_pair(pair)
    header = set(pd.read_csv(source, nrows=0).columns)
    wanted = {
        spec.source_column for spec in specs.values() if spec.source_column in header
    }
    # distance_a and minutes_since_line_flip are derived by the loader, not
    # stored in the ledger; rebuild both so their buckets can be reported.
    distance_inputs = {"distance_pips", "recent_m5_avg_range_pips"}
    flip_inputs = {"decision_time", "line_latest_flip_time"}
    usecols = sorted(wanted | ((distance_inputs | flip_inputs) & header))
    frame = pd.read_csv(source, usecols=usecols, low_memory=False)
    if distance_inputs <= header:
        average = pd.to_numeric(
            frame["recent_m5_avg_range_pips"], errors="coerce"
        ).replace(0, pd.NA)
        frame["distance_a"] = (
            pd.to_numeric(frame["distance_pips"], errors="coerce") / average
        )
    if flip_inputs <= header:
        decision = pd.to_datetime(
            frame["decision_time"], format="mixed", errors="coerce"
        )
        flipped = pd.to_datetime(
            frame["line_latest_flip_time"], format="mixed", errors="coerce"
        )
        frame["minutes_since_line_flip"] = (
            decision - flipped
        ).dt.total_seconds() / 60.0

    rows: list[dict[str, object]] = []
    for feature, spec in specs.items():
        if spec.source_column not in frame.columns:
            rows.append(
                {
                    "pair": pair,
                    "feature": feature,
                    "source_column": spec.source_column,
                    "bucket": "(column absent)",
                    "count": 0,
                    "share": float("nan"),
                }
            )
            continue
        values = pd.to_numeric(frame[spec.source_column], errors="coerce")
        buckets = (
            pd.cut(
                values,
                bins=list(spec.edges),
                labels=list(spec.labels),
                include_lowest=True,
            )
            .astype("string")
            .fillna("missing")
        )
        counts = buckets.value_counts()
        total = int(counts.sum())
        for bucket in [*spec.labels, "missing"]:
            count = int(counts.get(bucket, 0))
            if bucket == "missing" and count == 0:
                continue
            rows.append(
                {
                    "pair": pair,
                    "feature": feature,
                    "source_column": spec.source_column,
                    "bucket": bucket,
                    "count": count,
                    "share": count / total if total else float("nan"),
                }
            )
    return pd.DataFrame(rows)


def print_report(table: pd.DataFrame) -> None:
    for (pair, feature), group in table.groupby(
        ["pair", "feature"], sort=True
    ):
        shares = group.set_index("bucket")["share"]
        dominant = shares[shares >= DOMINANT_BUCKET_SHARE]
        empty = shares[shares == 0]
        thin = shares[(shares > 0) & (shares < THIN_BUCKET_SHARE)]
        flags = []
        if not dominant.empty:
            flags.append(
                "DOMINANT: "
                + ", ".join(
                    f"{name}={value:.0%}" for name, value in dominant.items()
                )
            )
        if not empty.empty:
            flags.append("EMPTY: " + ", ".join(empty.index))
        if not thin.empty:
            flags.append(
                "THIN: "
                + ", ".join(f"{name}={value:.1%}" for name, value in thin.items())
            )
        marker = "  <-- " + " | ".join(flags) if flags else ""
        print(f"{pair} {feature}{marker}")
        for bucket, value in shares.items():
            count = int(group.loc[group["bucket"] == bucket, "count"].iloc[0])
            bar = "#" * int(round(value * 40)) if value == value else ""
            print(f"    {bucket:<14s} {value:6.2%} ({count:>7d}) {bar}")
        print()


def main(argv: list[str] | None = None) -> pd.DataFrame:
    args = parse_args(argv)
    tables = []
    for pair in args.pairs:
        try:
            tables.append(
                bucket_occupancy(pair, args.start, args.end, args.output_dir)
            )
        except FileNotFoundError as error:
            print(f"skipped: {error}")
    if not tables:
        raise SystemExit("no candidate ledgers found for the requested pairs")
    table = pd.concat(tables, ignore_index=True)
    print_report(table)
    if args.csv is not None:
        table.to_csv(args.csv, index=False, encoding="utf-8")
        print(f"wrote {args.csv}")
    return table


if __name__ == "__main__":
    main()
