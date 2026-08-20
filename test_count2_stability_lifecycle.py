"""Synthetic contract tests; no historical search or replay is started."""

from __future__ import annotations

import argparse
import json
import math
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import count2_stability_lifecycle as lifecycle
from count2_prior2y_oos_replay import stability_lc_contract_payload


def _period(
    period_id: str,
    *,
    yen: float = 100.0,
    pips: float = 10.0,
    result_r: float = 2.0,
    trades: int = 40,
    pf: float = 1.2,
) -> dict[str, object]:
    return {
        "period_id": period_id,
        "trades": trades,
        "sum_yen": yen,
        "sum_pips": pips,
        "sum_r": result_r,
        "profit_factor_r": pf,
        "profit_factor_r_infinite": False,
    }


def _full(
    *,
    result_r: float = 8.0,
    yen: float = 400.0,
    pips: float = 40.0,
    trades: int = 160,
) -> dict[str, object]:
    return {
        "trades": trades,
        "wins": 88,
        "losses": 72,
        "flat": 0,
        "win_rate": 0.55,
        "sum_yen": yen,
        "sum_pips": pips,
        "sum_r": result_r,
        "gross_profit_r": 48.0,
        "gross_loss_r": 40.0,
        "profit_factor_r": 1.2,
        "profit_factor_r_infinite": False,
        "average_win_r": 0.55,
        "average_loss_r": -0.5,
        "realized_rr": 1.1,
        "max_drawdown_r": 5.0,
        "max_drawdown_yen": 250.0,
    }


def _accepted_result(result_r: float, period_rs: tuple[float, ...]) -> dict[str, object]:
    periods = [_period(f"P{index + 1}", result_r=value) for index, value in enumerate(period_rs)]
    full = _full(result_r=result_r)
    acceptance = lifecycle.evaluate_acceptance(full, periods, max_dd_r=20.0)
    assert acceptance["accepted"]
    return {"full": full, "periods": periods, "acceptance": acceptance}


def test_acceptance_passes_balanced_four_period_candidate() -> None:
    periods = [_period(f"P{index}") for index in range(1, 5)]
    result = lifecycle.evaluate_acceptance(_full(), periods, max_dd_r=20.0)
    assert result["accepted"] is True
    assert result["positive_period_concentration"] == {
        "sum_yen": 0.25,
        "sum_pips": 0.25,
        "sum_r": 0.25,
    }


def test_exactly_fifty_percent_positive_period_concentration_is_rejected() -> None:
    periods = [
        _period("P1", yen=200, pips=20, result_r=4),
        _period("P2", yen=100, pips=10, result_r=2),
        _period("P3", yen=100, pips=10, result_r=2),
        _period("P4", yen=-20, pips=-2, result_r=-0.4),
    ]
    result = lifecycle.evaluate_acceptance(
        _full(yen=380, pips=38, result_r=7.6), periods, max_dd_r=20.0
    )
    assert math.isclose(
        result["positive_period_concentration"]["sum_r"], 0.5, abs_tol=1e-12
    )
    assert result["accepted"] is False
    assert "positive_profit_concentration_exceeds_50pct" in result["rejection_reasons"]


def test_b_requires_acceptance_higher_full_r_and_three_period_wins() -> None:
    a = _accepted_result(8.0, (2.0, 2.0, 2.0, 2.0))
    b = _accepted_result(10.0, (3.0, 3.0, 3.0, 1.0))
    winner = lifecycle.choose_train_winner({"A": a, "B": b})
    assert winner["candidate"] == "B"
    assert winner["b_period_r_wins_over_a"] == 3


def test_b_is_selected_when_it_alone_passes_declared_acceptance() -> None:
    a = _accepted_result(12.0, (3.0, 3.0, 3.0, 3.0))
    a["acceptance"] = {**a["acceptance"], "accepted": False}
    b = _accepted_result(8.0, (2.0, 2.0, 2.0, 2.0))
    winner = lifecycle.choose_train_winner({"A": a, "B": b})
    assert winner["candidate"] == "B"
    assert winner["reason"] == (
        "B_is_the_only_management_method_meeting_training_acceptance"
    )


def test_s5_slice_is_lower_inclusive_and_upper_exclusive() -> None:
    inspector = SimpleNamespace(
        times=np.asarray(
            [
                "2025-07-29T23:59:55",
                "2025-07-30T00:00:00",
                "2025-07-30T00:00:05",
                "2025-07-30T00:00:10",
            ],
            dtype="datetime64[ns]",
        ),
        opens=np.arange(4),
        closes=np.arange(4),
        highs=np.arange(4),
        lows=np.arange(4),
    )
    sliced = lifecycle._slice_inspector(
        inspector,
        pd.Timestamp("2025-07-30T00:00:00"),
        pd.Timestamp("2025-07-30T00:00:10"),
    )
    assert list(sliced.times) == [
        np.datetime64("2025-07-30T00:00:00", "ns"),
        np.datetime64("2025-07-30T00:00:05", "ns"),
    ]


def _selection_artifact(tmp_path: Path, *, following_start: str = "2025-07-30") -> Path:
    manifest = tmp_path / "grid.json"
    manifest.write_text("{}", encoding="utf-8")
    payload = {
        "version": "synthetic_selection_v1",
        "status": "complete",
        "pair": "USD_JPY",
        "selection": {
            "start_inclusive": "2023-07-30",
            "end_exclusive": "2025-07-30",
            "periods": [
                {"id": "P1", "start": "2023-07-30", "end": "2024-01-30"},
                {"id": "P2", "start": "2024-01-30", "end": "2024-07-30"},
                {"id": "P3", "start": "2024-07-30", "end": "2025-01-30"},
                {"id": "P4", "start": "2025-01-30", "end": "2025-07-30"},
            ],
        },
        "following": {
            "start_inclusive": following_start,
            "end_exclusive": "2026-07-30",
        },
        "source_grid_manifest": str(manifest),
        "selected_policies": [
            {
                "selection_rank": 1,
                "name": "stable_1",
                "condition": "M5_FC2::second_wick_A::0.25_0.49",
                "entry_candidate_rank": 2,
                "entry_offset_range_multiplier": -0.25,
                "tp_range_multiplier": 5.0,
                "lc_range_multiplier": 1.5,
            }
        ],
        "selection_rules": {"max_dd_r": 20.0},
    }
    path = tmp_path / "selection.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_selection_loader_accepts_aliases_and_preserves_four_boundaries(tmp_path: Path) -> None:
    contract = lifecycle.load_selection_contract(_selection_artifact(tmp_path))
    assert contract.pair == "USD_JPY"
    assert contract.selection_end == contract.following_start
    assert [period.period_id for period in contract.periods] == ["P1", "P2", "P3", "P4"]
    assert contract.policies[0].entry_rank == 2
    assert contract.policies[0].offset_multiplier == -0.25


def test_selection_loader_rejects_future_boundary_overlap(tmp_path: Path) -> None:
    path = _selection_artifact(tmp_path, following_start="2025-07-29")
    try:
        lifecycle.load_selection_contract(path)
    except ValueError as error:
        assert "Selection end must equal following start" in str(error)
    else:
        raise AssertionError("Future boundary overlap was not rejected")


def _lifecycle_artifact(tmp_path: Path) -> Path:
    fingerprint_file = tmp_path / "frozen.txt"
    fingerprint_file.write_text("frozen", encoding="utf-8")
    a = _accepted_result(8.0, (2.0, 2.0, 2.0, 2.0))
    b = _accepted_result(10.0, (3.0, 3.0, 3.0, 1.0))
    winner = lifecycle.choose_train_winner({"A": a, "B": b})
    selection = {
        "start_inclusive": "2023-07-30T00:00:00",
        "end_exclusive": "2025-07-30T00:00:00",
        "periods": [
            {"period_id": "P1", "start_inclusive": "2023-07-30", "end_exclusive": "2024-01-30"},
            {"period_id": "P2", "start_inclusive": "2024-01-30", "end_exclusive": "2024-07-30"},
            {"period_id": "P3", "start_inclusive": "2024-07-30", "end_exclusive": "2025-01-30"},
            {"period_id": "P4", "start_inclusive": "2025-01-30", "end_exclusive": "2025-07-30"},
        ],
    }
    following = {
        "start_inclusive": "2025-07-30T00:00:00",
        "end_exclusive": "2026-07-30T00:00:00",
    }
    settings = {
        "spread_pips": 0.8,
        "min_target_pips": 1.6,
        "risk_yen": 50.0,
        "trade_timeout_min": 60,
        "profit_lock_ratio": 0.5,
        "duplicate_threshold_pips": 3.0,
        "max_dd_r": 20.0,
    }
    policies: list[dict[str, object]] = []
    candidate_sets = {"A": [], "B": []}
    lc_contract = stability_lc_contract_payload()
    config = {
        "pair": "USD_JPY",
        "selection": selection,
        "following": following,
        "settings": settings,
        "grid_stable_policies": [],
        "candidate_gate_policies": candidate_sets,
        "selected_policies": policies,
        "lc_contract": lc_contract,
    }
    artifact: dict[str, object] = {
        "version": lifecycle.TRAIN_ARTIFACT_VERSION,
        "status": "complete",
        "pair": "USD_JPY",
        "selection": selection,
        "following": following,
        "settings": settings,
        "grid_stable_policies": [],
        "candidate_gate_policies": candidate_sets,
        "selected_policies": policies,
        "lc_contract": lc_contract,
        "train_results": {"A": a, "B": b},
        "frozen_train_winner": winner,
        "fingerprints": {
            "synthetic": lifecycle._file_fingerprint(fingerprint_file, include_sha256=True)
        },
        "config_sha256": lifecycle._sha256_payload(config),
        "future_safety": {
            "selection_and_following_half_open": True,
            "selection_uses_no_following_rows": True,
            "s5_used_only_after_decision": True,
            "following_never_reranks_conditions": True,
            "following_never_changes_frozen_train_winner": True,
        },
    }
    artifact["lifecycle_integrity_sha256"] = lifecycle._sha256_payload(
        lifecycle._integrity_payload(artifact)
    )
    path = tmp_path / "lifecycle.json"
    path.write_text(json.dumps(artifact), encoding="utf-8")
    return path


def test_lifecycle_artifact_tamper_is_rejected(tmp_path: Path) -> None:
    path = _lifecycle_artifact(tmp_path)
    lifecycle.validate_lifecycle_artifact(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["train_results"]["B"]["full"]["sum_r"] = 999
    path.write_text(json.dumps(payload), encoding="utf-8")
    try:
        lifecycle.validate_lifecycle_artifact(path)
    except ValueError as error:
        assert "integrity SHA256" in str(error)
    else:
        raise AssertionError("Tampered lifecycle artifact was not rejected")


def test_empty_policy_set_writes_zero_trade_outputs_without_loading_s5(tmp_path: Path) -> None:
    paths = {
        "A_trades": tmp_path / "A.csv",
        "B_trades": tmp_path / "B.csv",
    }
    progress_path = tmp_path / "progress.json"
    trades, summaries, context = lifecycle._run_pair_of_replays(
        args=argparse.Namespace(),
        policies=[],
        paths=paths,
        progress_path=progress_path,
        progress_phase="synthetic",
        pair="USD_JPY",
        started=0.0,
    )
    assert context == {"empty_policy_set": True, "s5_loaded": False}
    assert trades["A"].empty and trades["B"].empty
    assert summaries == {"A": {}, "B": {}}
    assert paths["A_trades"].is_file() and paths["B_trades"].is_file()
    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    assert progress["completed_replays"] == 2
    assert progress["total_replays"] == 2
    assert progress["current_replay_percent"] == 100


def test_condition_screen_keeps_only_full_lifecycle_gate_passes() -> None:
    periods = tuple(
        lifecycle.PeriodWindow(
            f"P{index + 1}",
            pd.Timestamp(start),
            pd.Timestamp(end),
        )
        for index, (start, end) in enumerate(
            (
                ("2023-07-30", "2024-01-30"),
                ("2024-01-30", "2024-07-30"),
                ("2024-07-30", "2025-01-30"),
                ("2025-01-30", "2025-07-30"),
            )
        )
    )
    passing = lifecycle.Policy(1, "stable", "PASS", "FC2::shape::REJECTION", 1, 0.0, 2.0, 1.0)
    failing = lifecycle.Policy(2, "stable", "FAIL", "FC2::shape::STALL", 1, 0.0, 2.0, 1.0)
    rows: list[dict[str, object]] = []
    for period in periods:
        for ordinal in range(40):
            result_r = 1.0 if ordinal < 22 else -1.0
            when = period.start + pd.Timedelta(days=1, minutes=ordinal)
            rows.append(
                {
                    "event_id": f"{period.period_id}-{ordinal}",
                    "decision_time": when,
                    "fill_time": when,
                    "exit_time": when,
                    "order_name": passing.order_name,
                    "condition_id": passing.condition_id,
                    "result_r": result_r,
                    "result_pips": result_r,
                    "result_yen": 50.0 * result_r,
                }
            )
    nested, _flat = lifecycle._condition_screen_results(
        candidate="A",
        policies=[passing, failing],
        trades=pd.DataFrame(rows),
        periods=periods,
        max_dd_r=20.0,
    )
    assert nested[0]["acceptance"]["accepted"] is True
    assert nested[1]["acceptance"]["accepted"] is False
    assert lifecycle._accepted_screen_policies([passing, failing], nested) == [passing]


def test_following_discovery_skips_manifest_with_changed_source(tmp_path: Path) -> None:
    start = pd.Timestamp("2025-07-30")
    end = pd.Timestamp("2026-07-30")
    sources: dict[str, Path] = {}
    stats: dict[str, dict[str, int]] = {}
    for name in ("source_candidates", "source_events", "s5_cache"):
        path = tmp_path / f"{name}.csv"
        path.write_text("header\n", encoding="utf-8")
        sources[name] = path
        stat = path.stat()
        stats[name] = {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
    manifest = {
        "status": "complete",
        "pair": "USD_JPY",
        "start": str(start),
        "end": str(end),
        "spread_pips": 0.8,
        "min_target_pips": 1.6,
        "risk_yen": 50.0,
        **{name: str(path) for name, path in sources.items()},
        "source_candidates_stat": stats["source_candidates"],
        "source_events_stat": stats["source_events"],
        "s5_cache_stat": stats["s5_cache"],
        "future_safety": {
            "s5_used_only_for_outcome": True,
            "s5_at_or_after_requested_end_excluded": True,
        },
    }
    manifest_path = tmp_path / (
        "count2_target_grid_manifest_USD_JPY_20250730_20260730_synthetic.json"
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    sources["source_candidates"].write_text("header\nchanged\n", encoding="utf-8")
    try:
        lifecycle._discover_grid_manifest(
            tmp_path,
            "USD_JPY",
            start,
            end,
            {"spread_pips": 0.8, "min_target_pips": 1.6, "risk_yen": 50.0},
        )
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("A stale following manifest was selected")


class Count2StabilityLifecycleTest(unittest.TestCase):
    """Unittest entry points keep the tests runnable without pytest."""

    def test_balanced_acceptance(self) -> None:
        test_acceptance_passes_balanced_four_period_candidate()

    def test_concentration_boundary(self) -> None:
        test_exactly_fifty_percent_positive_period_concentration_is_rejected()

    def test_b_promotion_rule(self) -> None:
        test_b_requires_acceptance_higher_full_r_and_three_period_wins()

    def test_b_only_accepted(self) -> None:
        test_b_is_selected_when_it_alone_passes_declared_acceptance()

    def test_half_open_s5_slice(self) -> None:
        test_s5_slice_is_lower_inclusive_and_upper_exclusive()

    def test_selection_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            test_selection_loader_accepts_aliases_and_preserves_four_boundaries(
                Path(folder)
            )

    def test_future_boundary_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            test_selection_loader_rejects_future_boundary_overlap(Path(folder))

    def test_artifact_tamper(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            test_lifecycle_artifact_tamper_is_rejected(Path(folder))

    def test_empty_policy_set(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            test_empty_policy_set_writes_zero_trade_outputs_without_loading_s5(
                Path(folder)
            )

    def test_condition_screen(self) -> None:
        test_condition_screen_keeps_only_full_lifecycle_gate_passes()

    def test_stale_following_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            test_following_discovery_skips_manifest_with_changed_source(Path(folder))


if __name__ == "__main__":
    unittest.main()
