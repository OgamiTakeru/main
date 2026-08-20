"""Small contract tests for the lifecycle train/fixed-replay hand-off.

These tests intentionally use synthetic arrays, AST inspection, and temporary
files only.  They must never start a year-long search or replay.
"""

from __future__ import annotations

import ast
import datetime as dt
import importlib
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

import count2_lifecycle_policy_search as lifecycle_search


ROOT = Path(__file__).resolve().parent
TRAIN_START = dt.datetime(2023, 7, 30)
TRAIN_END = dt.datetime(2025, 7, 30)
FOLLOWING_START = dt.datetime(2025, 7, 30)
FOLLOWING_END = dt.datetime(2026, 7, 30)
PAIRS = ("USD_JPY", "EUR_USD", "AUD_USD")


def _datetime_assignment(tree: ast.Module, name: str) -> dt.datetime:
    for statement in tree.body:
        if not isinstance(statement, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == name for target in statement.targets):
            continue
        call = statement.value
        assert isinstance(call, ast.Call)
        assert isinstance(call.func, ast.Attribute)
        assert call.func.attr == "datetime"
        return dt.datetime(*(ast.literal_eval(argument) for argument in call.args))
    raise AssertionError(f"wrapper lacks {name}")


def _string_assignment(tree: ast.Module, name: str) -> str:
    for statement in tree.body:
        if not isinstance(statement, ast.Assign):
            continue
        if any(isinstance(target, ast.Name) and target.id == name for target in statement.targets):
            return ast.literal_eval(statement.value)
    raise AssertionError(f"wrapper lacks {name}")


@pytest.mark.parametrize("pair", PAIRS)
def test_search_parse_defaults_keep_selection_and_following_half_open(pair: str, tmp_path: Path) -> None:
    args = lifecycle_search.parse_args(
        ["--risk-yen", "1000", "--output-dir", str(tmp_path)],
        default_pair=pair,
        default_train_start=TRAIN_START,
        default_train_end=TRAIN_END,
        default_following_start=FOLLOWING_START,
        default_following_end=FOLLOWING_END,
    )

    assert args.pair == pair
    assert (args.selection_start, args.selection_end) == (TRAIN_START, TRAIN_END)
    assert (args.following_start, args.following_end) == (
        FOLLOWING_START,
        FOLLOWING_END,
    )
    assert args.selection_end == args.following_start
    assert (args.oos_start, args.oos_end) == (TRAIN_START, TRAIN_END)
    assert "20230730_20250730" in Path(args.source_candidates).name
    assert "20260730" not in Path(args.source_candidates).name
    artifact_name = lifecycle_search.artifact_path(args).name
    assert pair in artifact_name
    assert "20230730_20250730_to_20250730_20260730" in artifact_name


@pytest.mark.parametrize("mode", ("train", "replay"))
@pytest.mark.parametrize(
    ("suffix", "pair"),
    (("usd_jpy", "USD_JPY"), ("eur_usd", "EUR_USD"), ("aud_usd", "AUD_USD")),
)
def test_pair_wrappers_pin_pair_and_all_four_boundaries(
    mode: str,
    suffix: str,
    pair: str,
) -> None:
    path = ROOT / f"test_long_inspection_lifecycle_{mode}_{suffix}.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    assert _string_assignment(tree, "PAIR") == pair
    assert _datetime_assignment(tree, "TRAIN_START") == TRAIN_START
    assert _datetime_assignment(tree, "TRAIN_END") == TRAIN_END
    assert _datetime_assignment(tree, "FOLLOWING_START") == FOLLOWING_START
    assert _datetime_assignment(tree, "FOLLOWING_END") == FOLLOWING_END

    expected_module = (
        "count2_lifecycle_policy_search"
        if mode == "train"
        else "count2_lifecycle_fixed_replay"
    )
    imports = [node for node in tree.body if isinstance(node, ast.ImportFrom)]
    assert any(node.module == expected_module and any(item.name == "main" for item in node.names) for node in imports)
    main_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "main"
    ]
    assert len(main_calls) == 1
    assert {keyword.arg: ast.unparse(keyword.value) for keyword in main_calls[0].keywords} == {
        "default_pair": "PAIR",
        "default_train_start": "TRAIN_START",
        "default_train_end": "TRAIN_END",
        "default_following_start": "FOLLOWING_START",
        "default_following_end": "FOLLOWING_END",
    }


def test_search_s5_slice_includes_lower_and_excludes_upper() -> None:
    start = np.datetime64("2025-07-30T00:00:00", "ns")
    end = np.datetime64("2025-07-30T00:00:10", "ns")
    times = np.array(
        [
            np.datetime64("2025-07-29T23:59:55", "ns"),
            start,
            np.datetime64("2025-07-30T00:00:05", "ns"),
            end,
            np.datetime64("2025-07-30T00:00:15", "ns"),
        ]
    )
    inspector = SimpleNamespace(
        times=times,
        opens=np.arange(5, dtype=float) + 10,
        closes=np.arange(5, dtype=float) + 20,
        highs=np.arange(5, dtype=float) + 30,
        lows=np.arange(5, dtype=float) + 40,
    )

    sliced = lifecycle_search._slice_inspector_window(inspector, TRAIN_END, TRAIN_END + dt.timedelta(seconds=10))

    assert sliced is inspector
    assert sliced.times.tolist() == [start, np.datetime64("2025-07-30T00:00:05", "ns")]
    assert sliced.opens.tolist() == [11.0, 12.0]
    assert sliced.closes.tolist() == [21.0, 22.0]
    assert sliced.highs.tolist() == [31.0, 32.0]
    assert sliced.lows.tolist() == [41.0, 42.0]
    assert np.all(sliced.times >= start)
    assert np.all(sliced.times < end)


def _fixed_source() -> tuple[str, ast.Module]:
    path = ROOT / "count2_lifecycle_fixed_replay.py"
    source = path.read_text(encoding="utf-8")
    return source, ast.parse(source, filename=str(path))


def _called_names(tree: ast.AST) -> list[str]:
    names: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            names.append(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            names.append(node.func.attr)
    return names


def test_fixed_artifact_validator_guards_tampering_and_all_boundaries() -> None:
    """Keep the security-sensitive artifact checks visible in the fixed consumer."""
    source, tree = _fixed_source()
    string_literals = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    required_artifact_keys = {
        "version",
        "status",
        "complete",
        "pair",
        "selection",
        "following",
        "start_inclusive",
        "end_exclusive",
        "config",
        "config_sha256",
        "fingerprints",
        "selected_condition_rows",
        "selected_policies",
        "selected_management_policies",
    }
    assert required_artifact_keys <= string_literals
    assert "sha256" in _called_names(tree)
    assert "Lifecycle replay engine changed after condition selection" in source
    assert sum(isinstance(node, ast.Raise) for node in ast.walk(tree)) >= 4
    # Comparing against all CLI boundaries is part of rejecting a copied or
    # edited artifact, not merely checking that the four labels exist.
    for attribute in ("train_start", "train_end", "following_start", "following_end"):
        assert f"args.{attribute}" in source


def test_fixed_replay_has_no_following_period_reselection_path() -> None:
    source, tree = _fixed_source()
    calls = _called_names(tree)

    assert "load_policies" not in calls
    assert calls.count("replay_metric") == 1
    assert "selected_policies" in source
    assert "selected_management_policies" in source
    assert "following_is_fixed_replay" in source
    assert "selection_files_read_during_following" in source
    assert "diagnostic" in source.lower()

    # The training module may be imported lazily to calculate the artifact
    # filename, but importing it at module load would also expose selection
    # helpers to the following-period process.
    top_level_imports = [
        node
        for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    assert all(
        not (
            isinstance(node, ast.ImportFrom)
            and node.module == "count2_lifecycle_policy_search"
        )
        and not (
            isinstance(node, ast.Import)
            and any(alias.name == "count2_lifecycle_policy_search" for alias in node.names)
        )
        for node in top_level_imports
    )


def test_fixed_generation_archives_live_temp_part_and_progress(tmp_path: Path) -> None:
    """Exercise cleanup only; importing the fixed module must not start replay."""
    fixed = importlib.import_module("count2_lifecycle_fixed_replay")
    archive_generation = getattr(fixed, "_archive_generation")
    paths = {
        "trades": tmp_path / "trades.csv",
        "summary": tmp_path / "summary.json",
        "progress": tmp_path / "progress.json",
    }
    residuals = [
        paths["trades"],
        paths["trades"].with_suffix(".csv.tmp"),
        paths["summary"].with_suffix(".json.part"),
        paths["progress"],
        paths["progress"].with_suffix(".json.tmp"),
    ]
    for index, path in enumerate(residuals):
        path.write_text(f"residual-{index}", encoding="utf-8")

    archived = archive_generation(paths)

    assert not any(path.exists() for path in residuals)
    assert len(archived) == len(residuals)
    assert all(Path(path).parent == tmp_path / "archive" for path in archived)
    assert all(Path(path).is_file() for path in archived)
