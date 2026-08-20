"""Synthetic tests for stable selection; no historical CSV is opened."""

from __future__ import annotations

import argparse
import datetime as dt
import inspect
import json
import math
import tempfile
import unittest
from collections import defaultdict
from pathlib import Path

import fGeneric as gene
import count2_stability_selection as selection


def _period(
    name: str,
    *,
    yen: float = 100.0,
    pips: float = 10.0,
    result_r: float = 2.0,
    completed: int = 40,
    pf: float = 1.2,
) -> dict[str, object]:
    return {
        "period_id": name,
        "completed_count": completed,
        "sum_yen": yen,
        "sum_pips": pips,
        "sum_r": result_r,
        "profit_factor_r": pf,
        "profit_factor_r_infinite": False,
    }


def _full() -> dict[str, object]:
    return {
        "completed_count": 160,
        "sum_yen": 400.0,
        "sum_pips": 40.0,
        "sum_r": 8.0,
        "profit_factor_r": 1.2,
        "profit_factor_r_infinite": False,
        "max_drawdown_r": 5.0,
    }


def test_hard_gate_accepts_balanced_candidate() -> None:
    periods = [_period(f"P{index}") for index in range(1, 5)]
    result = selection.hard_gate(_full(), periods, max_dd_r=20.0)
    assert result["accepted"] is True
    assert result["period_completed_total"] == 160
    assert result["positive_period_concentration"] == {
        "sum_yen": 0.25,
        "sum_pips": 0.25,
        "sum_r": 0.25,
    }


def test_exactly_fifty_percent_profit_concentration_is_rejected() -> None:
    periods = [
        _period("P1", yen=200, pips=20, result_r=4),
        _period("P2", yen=100, pips=10, result_r=2),
        _period("P3", yen=100, pips=10, result_r=2),
        _period("P4", yen=-20, pips=-2, result_r=-0.4),
    ]
    full = {**_full(), "sum_yen": 380, "sum_pips": 38, "sum_r": 7.6}
    result = selection.hard_gate(full, periods, max_dd_r=20.0)
    assert math.isclose(
        result["positive_period_concentration"]["sum_r"], 0.5, abs_tol=1e-12
    )
    assert result["accepted"] is False
    assert "positive_period_concentration_at_least_50pct" in result["rejection_reasons"]


def test_cartesian_neighbourhood_matches_user_example_shape() -> None:
    # Edge offset has 2 values; interior TP/LC have 3 each: 2*3*3=18.
    neighbours = selection.cartesian_neighbours((0, 4, 3), (3, 8, 8))
    assert len(neighbours) == 18
    assert (0, 4, 3) in neighbours
    assert (1, 5, 4) in neighbours


def test_component_is_axial_and_medoid_is_central_not_best_profit() -> None:
    points = {(0, 0, 0), (0, 1, 0), (0, 2, 0), (0, 3, 0)}
    components = selection.connected_components(points, (1, 4, 1))
    assert components == [points]
    # The two middle points tie; the deterministic lower coordinate is used.
    assert selection.component_medoid(points) == (0, 1, 0)


def test_ordered_shape_adjacency_and_undefined_contract() -> None:
    single = selection.adjacent_condition_ids(
        "FC2::second_wick_A_bin::0.25-0.49"
    )
    assert single == (
        "FC2::second_wick_A_bin::0.10-0.24",
        "FC2::second_wick_A_bin::0.50-0.74",
    )
    interaction = selection.adjacent_condition_ids(
        "M5_FC2_X_H1_PAIR::second_wick_A_bin::M5=0.25-0.49|H1=0.50-0.74"
    )
    assert (
        "M5_FC2_X_H1_PAIR::second_wick_A_bin::M5=0.10-0.24|H1=0.50-0.74"
        in interaction
    )
    assert (
        "M5_FC2_X_H1_PAIR::second_wick_A_bin::M5=0.25-0.49|H1=0.75-0.99"
        in interaction
    )
    assert selection.adjacent_condition_ids(
        "FC2::prior_impulse_retrace_ratio_bin::UNDEFINED"
    ) == ()
    assert selection.adjacent_condition_ids("FC2::shape::REJECTION") is None


def test_jaccard_exactly_seventy_percent_is_rejection_boundary() -> None:
    left = {str(value) for value in range(7)}
    right = {str(value) for value in range(10)}
    assert math.isclose(selection.jaccard(left, right), 0.70, abs_tol=1e-12)
    assert selection.jaccard(left, right) >= 0.70 - 1e-12


def test_event_membership_function_has_no_outcome_input() -> None:
    signature = inspect.signature(selection.update_event_memberships)
    assert not any(
        word in name
        for name in signature.parameters
        for word in ("fill", "result", "outcome", "tp", "lc")
    )
    memberships: dict[tuple[str, int], set[str]] = defaultdict(set)
    conditions = json.dumps(["FC2::shape::REJECTION", "OTHER::trade_side::BUY"])
    selection.update_event_memberships(
        memberships,
        event_id="event-1",
        entry_rank=2,
        conditions_json=conditions,
        allowed_condition_ids={"FC2::shape::REJECTION"},
    )
    # Repeating the same decision (as another offset path would) is idempotent.
    selection.update_event_memberships(
        memberships,
        event_id="event-1",
        entry_rank=2,
        conditions_json=conditions,
        allowed_condition_ids={"FC2::shape::REJECTION"},
    )
    assert memberships[("FC2::shape::REJECTION", 2)] == {"event-1"}


def test_period_boundary_purges_future_common_window() -> None:
    periods = selection._periods(
        selection.pd.Timestamp("2023-07-30"),
        selection.pd.Timestamp("2025-07-30"),
    )
    decision = selection.pd.Timestamp("2024-01-29 23:55:00")
    assert selection._period_index(
        decision, selection.pd.Timestamp("2024-01-30 00:00:00"), periods
    ) == 0
    assert selection._period_index(
        decision, selection.pd.Timestamp("2024-01-30 00:00:01"), periods
    ) is None
    assert selection._period_index(
        selection.pd.Timestamp("2024-01-30 00:00:00"),
        selection.pd.Timestamp("2024-01-30 01:00:00"),
        periods,
    ) == 1


def test_same_s5_ambiguity_uses_lc() -> None:
    spec = selection.GridSpec("USD_JPY", (0.0,), (1.0,), (1.0,), 50.0)
    key = selection.CandidateKey("FC2::shape::REJECTION", 1, 0, 0, 0)
    row = {
        "filled": True,
        "tp_p1A_pips": 10.0,
        "tp_p1A_reached": True,
        "tp_p1A_first_index": 0,
        "tp_p1A_first_time": "2024-01-01 00:00:05",
        "lc_p1A_pips": 10.0,
        "lc_p1A_reached": True,
        "lc_p1A_first_index": 0,
        "lc_p1A_first_time": "2024-01-01 00:00:05",
        "horizon_complete": True,
    }
    outcome = selection._row_outcome(
        row, key, spec, gene.currency_pair("USD_JPY"), {}
    )
    assert outcome is not None
    assert outcome.result_pips == -10.0
    assert outcome.result_r == -1.0


def test_zero_selection_artifact_contains_no_policy(tmp_path: Path) -> None:
    args = argparse.Namespace(
        pair="USD_JPY",
        selection_start=dt.datetime(2023, 7, 30),
        selection_end=dt.datetime(2025, 7, 30),
        following_start=dt.datetime(2025, 7, 30),
        following_end=dt.datetime(2026, 7, 30),
        max_dd_r=20.0,
        min_neighbour_sum_r=-5.0,
    )
    periods = selection._periods(
        selection.pd.Timestamp(args.selection_start),
        selection.pd.Timestamp(args.selection_end),
    )
    manifest = tmp_path / "grid.json"
    manifest.write_text("{}", encoding="utf-8")
    payload = selection._artifact_payload(
        args=args,
        periods=periods,
        manifest_path=manifest,
        selected_rows=[],
        fingerprints={},
        outputs={"selected": tmp_path / "selected.csv"},
        counts={"selected": 0},
    )
    assert payload["status"] == "complete"
    assert payload["selected_count"] == 0
    assert payload["selected_policies"] == []
    assert payload["selection_rules"]["forced_selection_count"] is None


class Count2StabilitySelectionTest(unittest.TestCase):
    """Unittest entry points keep the synthetic suite dependency-free."""

    def test_hard_gate(self) -> None:
        test_hard_gate_accepts_balanced_candidate()

    def test_concentration_boundary(self) -> None:
        test_exactly_fifty_percent_profit_concentration_is_rejected()

    def test_cartesian_neighbourhood(self) -> None:
        test_cartesian_neighbourhood_matches_user_example_shape()

    def test_component_medoid(self) -> None:
        test_component_is_axial_and_medoid_is_central_not_best_profit()

    def test_shape_adjacency(self) -> None:
        test_ordered_shape_adjacency_and_undefined_contract()

    def test_jaccard_boundary(self) -> None:
        test_jaccard_exactly_seventy_percent_is_rejection_boundary()

    def test_causal_membership_signature(self) -> None:
        test_event_membership_function_has_no_outcome_input()

    def test_period_boundary(self) -> None:
        test_period_boundary_purges_future_common_window()

    def test_same_s5_conservative_resolution(self) -> None:
        test_same_s5_ambiguity_uses_lc()

    def test_zero_selection_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            test_zero_selection_artifact_contains_no_policy(Path(folder))


if __name__ == "__main__":
    unittest.main()
