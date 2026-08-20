"""Synthetic contracts for the one-click count2 stability kick workflow.

No test in this module opens a market-data cache or starts a replay.
"""

from __future__ import annotations

import ast
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import count2_stability_pipeline as pipeline


ROOT = Path(__file__).resolve().parent
SELECTION_START = dt.datetime(2023, 7, 30)
SELECTION_END = dt.datetime(2025, 7, 30)
FOLLOWING_START = dt.datetime(2025, 7, 30)
FOLLOWING_END = dt.datetime(2026, 7, 30)
WRAPPERS = {
    "USD_JPY": "USD_JPY_kick_count2_stability.py",
    "EUR_USD": "EUR_USD_kick_count2_stability.py",
    "AUD_USD": "AUD_USD_kick_count2_stability.py",
}


class MonkeyPatch:
    """Small attribute patcher for the repository's unittest-only environment."""

    def __init__(self) -> None:
        self._changes: list[tuple[object, str, object]] = []

    def setattr(self, owner: object, name: str, value: object) -> None:
        self._changes.append((owner, name, getattr(owner, name)))
        setattr(owner, name, value)

    def undo(self) -> None:
        while self._changes:
            owner, name, value = self._changes.pop()
            setattr(owner, name, value)


def _args(folder: Path, pair: str = "USD_JPY") -> SimpleNamespace:
    return SimpleNamespace(
        pair=pair,
        selection_start=SELECTION_START,
        selection_end=SELECTION_END,
        following_start=FOLLOWING_START,
        following_end=FOLLOWING_END,
        output_dir=folder,
        grid_dir=folder,
        source_candidates=None,
        source_events=None,
        selection_s5_cache=None,
        following_grid_manifest=None,
        max_dd_r=20.0,
        min_neighbour_sum_r=-5.0,
        read_chunk_size=1000,
        rebuild_grid=False,
    )


def _touch(path: Path, text: str = "synthetic") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _assignment(tree: ast.Module, name: str):
    for statement in tree.body:
        if not isinstance(statement, ast.Assign):
            continue
        if any(isinstance(target, ast.Name) and target.id == name for target in statement.targets):
            return statement.value
    raise AssertionError(f"missing assignment: {name}")


def test_pair_kicks_pin_pair_and_all_half_open_boundaries() -> None:
    for pair, filename in WRAPPERS.items():
        path = ROOT / filename
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

        assert ast.literal_eval(_assignment(tree, "PAIR")) == pair
        expected = {
            "SELECTION_START": SELECTION_START,
            "SELECTION_END": SELECTION_END,
            "FOLLOWING_START": FOLLOWING_START,
            "FOLLOWING_END": FOLLOWING_END,
        }
        for name, value in expected.items():
            call = _assignment(tree, name)
            assert isinstance(call, ast.Call)
            assert isinstance(call.func, ast.Attribute) and call.func.attr == "datetime"
            actual = dt.datetime(*(ast.literal_eval(argument) for argument in call.args))
            assert actual == value

        imports = [node for node in tree.body if isinstance(node, ast.ImportFrom)]
        assert any(
            node.module == "count2_stability_pipeline"
            and any(alias.name == "main" for alias in node.names)
            for node in imports
        )
        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "main"
        ]
        assert len(calls) == 1
        assert {keyword.arg for keyword in calls[0].keywords} == {
            "default_pair",
            "default_selection_start",
            "default_selection_end",
            "default_following_start",
            "default_following_end",
        }


def test_pipeline_source_has_no_oanda_or_live_mutation_path() -> None:
    source = (ROOT / "count2_stability_pipeline.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert "requests" not in imported
    assert "classOanda" not in imported
    assert "oandapyV20" not in source
    assert "live_profile" not in source
    assert source.count("run_grid_search") == 1
    assert "rebuild_grid" in source


def test_pipeline_uses_the_published_selector_and_lifecycle_keyword_contracts() -> None:
    source = (ROOT / "count2_stability_pipeline.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls: dict[str, ast.Call] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        owner = node.func.value
        if isinstance(owner, ast.Name):
            calls[f"{owner.id}.{node.func.attr}"] = node

    shared_defaults = {
        "default_pair",
        "default_selection_start",
        "default_selection_end",
        "default_following_start",
        "default_following_end",
    }
    assert {keyword.arg for keyword in calls["selection.main"].keywords} == shared_defaults
    assert {keyword.arg for keyword in calls["lifecycle.train_main"].keywords} == shared_defaults
    assert {keyword.arg for keyword in calls["lifecycle.following_main"].keywords} == shared_defaults


def test_exact_grid_manifest_requires_config_completion_and_all_outputs(tmp_path: Path) -> None:
    paths = {
        name: tmp_path / f"grid_{name}{'.json' if name in {'manifest', 'progress'} else '.csv'}"
        for name in ("paths", "aggregate", "monthly", "manifest", "progress")
    }
    for name, path in paths.items():
        if name != "manifest":
            _touch(path)
    expected = {
        "version": "synthetic-grid-v1",
        "pair": "USD_JPY",
        "start": "2023-07-30 00:00:00",
        "end": "2025-07-30 00:00:00",
        "max_source_rows": None,
    }
    manifest = {
        **expected,
        "status": "complete",
        "source_rows_total": 123,
        "source_rows_processed": 123,
        "outputs": {name: str(path.resolve()) for name, path in paths.items()},
    }
    paths["manifest"].write_text(json.dumps(manifest), encoding="utf-8")

    assert pipeline._is_complete_exact_grid_manifest(
        paths["manifest"], expected_config=expected
    )

    # Progress is an archived operational log and is not required to reuse
    # the expensive analytical grid outputs.
    paths["progress"].unlink()
    assert pipeline._is_complete_exact_grid_manifest(
        paths["manifest"], expected_config=expected
    )

    paths["monthly"].unlink()
    assert not pipeline._is_complete_exact_grid_manifest(
        paths["manifest"], expected_config=expected
    )
    _touch(paths["monthly"])
    changed = dict(expected)
    changed["pair"] = "EUR_USD"
    assert not pipeline._is_complete_exact_grid_manifest(
        paths["manifest"], expected_config=changed
    )


def test_one_click_pipeline_runs_three_logical_phases_in_order(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    args = _args(tmp_path)
    grid_manifest = _touch(tmp_path / "grid_manifest.json", "{}")
    selection_artifact = _touch(tmp_path / "selection_artifact.json", "{}")
    lifecycle_artifact = _touch(tmp_path / "lifecycle_artifact.json", "{}")
    following_result = _touch(tmp_path / "following_result.json", "{}")
    calls: list[tuple[str, Path | None]] = []

    def fake_grid(_args):
        calls.append(("grid", None))
        return {"manifest": grid_manifest}, True

    def fake_selection(_args, manifest):
        calls.append(("selection", manifest))
        return {"artifact": selection_artifact}

    def fake_train(_args, artifact):
        calls.append(("lifecycle_train", artifact))
        return {"artifact": lifecycle_artifact}

    def fake_following(_args, artifact):
        calls.append(("following", artifact))
        return {"result": following_result}

    monkeypatch.setattr(pipeline, "_notice", lambda _lines: None)
    monkeypatch.setattr(pipeline, "_ensure_selection_grid", fake_grid)
    monkeypatch.setattr(pipeline, "_run_stability_selection", fake_selection)
    monkeypatch.setattr(pipeline, "_run_lifecycle_train", fake_train)
    monkeypatch.setattr(pipeline, "_run_fixed_following", fake_following)

    outputs = pipeline.run_pipeline(args)

    assert calls == [
        ("grid", None),
        ("selection", grid_manifest.resolve()),
        ("lifecycle_train", selection_artifact.resolve()),
        ("following", lifecycle_artifact.resolve()),
    ]
    assert outputs["pipeline_result"].is_file()
    assert outputs["pipeline_progress_archive"].is_file()
    assert outputs["pipeline_progress_archive"].parent == tmp_path / "archive"
    payload = json.loads(outputs["pipeline_result"].read_text(encoding="utf-8"))
    assert payload["status"] == "complete"
    assert payload["grid_reused"] is True
    assert payload["top15_forced"] is False
    assert payload["automatic_oanda_download"] is False
    assert payload["outputs"]["selection_artifact"] == str(selection_artifact.resolve())
    assert payload["outputs"]["following_result"] == str(following_result.resolve())


def test_grid_cli_uses_cache_dir_and_archived_progress_is_resolved(tmp_path: Path) -> None:
    args = _args(tmp_path / "results")
    args.grid_dir = (tmp_path / "grid-cache").resolve()
    cli = pipeline._grid_cli(args)
    assert cli[cli.index("--output-dir") + 1] == str(args.grid_dir)

    live_progress = tmp_path / "results" / "stage_progress.json"
    archived_progress = _touch(
        live_progress.parent / "archive" / "stage_progress_20260818_120000.json"
    )
    resolved = pipeline._resolve_returned_paths(
        {"progress": live_progress}, "synthetic stage"
    )
    assert resolved == {"progress": archived_progress.resolve()}


def test_pipeline_failure_archives_progress_and_does_not_start_following(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    args = _args(tmp_path)
    grid_manifest = _touch(tmp_path / "grid_manifest.json", "{}")
    following_started = False

    monkeypatch.setattr(pipeline, "_notice", lambda _lines: None)
    monkeypatch.setattr(
        pipeline,
        "_ensure_selection_grid",
        lambda _args: ({"manifest": grid_manifest}, True),
    )

    def fail_selection(_args, _manifest):
        raise ValueError("synthetic selection failure")

    def following(_args, _artifact):
        nonlocal following_started
        following_started = True
        return {}

    monkeypatch.setattr(pipeline, "_run_stability_selection", fail_selection)
    monkeypatch.setattr(pipeline, "_run_fixed_following", following)

    try:
        pipeline.run_pipeline(args)
    except ValueError as error:
        assert "synthetic selection failure" in str(error)
    else:
        raise AssertionError("Synthetic selection failure did not propagate")

    assert following_started is False
    assert not pipeline.pipeline_paths(args)["progress"].exists()
    archived_progress = list((tmp_path / "archive").glob("*pipeline_progress*.json"))
    assert len(archived_progress) == 1
    payload = json.loads(archived_progress[0].read_text(encoding="utf-8"))
    assert payload["status"] == "failed"
    assert payload["total"] == 3


def test_notices_are_bulleted_line_by_line() -> None:
    assert pipeline._bullet_message(["first", "- second", "third"]).splitlines() == [
        "- first",
        "- second",
        "- third",
    ]


class Count2StabilityPipelineTest(unittest.TestCase):
    def test_wrappers(self) -> None:
        test_pair_kicks_pin_pair_and_all_half_open_boundaries()

    def test_no_live_path(self) -> None:
        test_pipeline_source_has_no_oanda_or_live_mutation_path()

    def test_api_contracts(self) -> None:
        test_pipeline_uses_the_published_selector_and_lifecycle_keyword_contracts()

    def test_grid_manifest_contract(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            test_exact_grid_manifest_requires_config_completion_and_all_outputs(
                Path(folder)
            )

    def test_stage_order(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            patcher = MonkeyPatch()
            try:
                test_one_click_pipeline_runs_three_logical_phases_in_order(
                    Path(folder), patcher
                )
            finally:
                patcher.undo()

    def test_cache_dir_and_archived_progress(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            test_grid_cli_uses_cache_dir_and_archived_progress_is_resolved(
                Path(folder)
            )

    def test_failure_is_closed(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            patcher = MonkeyPatch()
            try:
                test_pipeline_failure_archives_progress_and_does_not_start_following(
                    Path(folder), patcher
                )
            finally:
                patcher.undo()

    def test_bullet_notices(self) -> None:
        test_notices_are_bulleted_line_by_line()


if __name__ == "__main__":
    unittest.main()
