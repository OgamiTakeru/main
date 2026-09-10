"""Pure callback tests; no trading modules, price data, or network access."""

import unittest

from fInspectionEquivalence import (
    collect_equivalence_report,
    make_unavailable_equivalence_report,
)


def _sample(candidates=1, *, timeframe="M5"):
    return {
        "checked_decisions": 1,
        "checked_candidates": candidates,
        "checked_candidates_by_timeframe": {timeframe: candidates},
        "peak_history_bars_by_timeframe": {timeframe: 100},
        "mismatches": 0,
        "core_version": "example_core",
        "policy_id": "example_policy",
    }


class InspectionEquivalenceTest(unittest.TestCase):
    def test_success_uses_thirty_distributed_samples_and_retains_metadata(self):
        attempted = []

        def validate(index):
            attempted.append(index)
            return _sample()

        report = collect_equivalence_report(range(300), validate, timeframes=("M5",))
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["checked_decisions"], 30)
        self.assertEqual(report["attempted_decisions"], 30)
        self.assertEqual(report["checked_candidates"], 30)
        self.assertEqual(report["checked_candidates_by_timeframe"], {"M5": 30})
        self.assertEqual(report["peak_history_bars_by_timeframe"], {"M5": 100})
        self.assertEqual((attempted[0], attempted[-1]), (0, 299))
        self.assertEqual(len(set(attempted)), 30)
        self.assertEqual(report["policy_id"], "example_policy")
        self.assertEqual(report["issues"], [])

    def test_mismatch_is_retained_even_after_successful_replacement(self):
        attempted = []

        def validate(index):
            attempted.append(index)
            if len(attempted) == 2:
                raise ValueError("resistance breakout production equivalence mismatch: price")
            return _sample()

        report = collect_equivalence_report(
            range(300), validate, timeframes=("M5",),
            describe_index=lambda index: f"decision-{index}",
        )
        self.assertEqual(report["status"], "mismatch")
        self.assertEqual(report["checked_decisions"], 30)
        self.assertEqual(report["attempted_decisions"], 31)
        self.assertEqual(report["mismatches"], 1)
        self.assertEqual(report["errors"], 0)
        self.assertEqual(report["skipped_decisions"], 1)
        self.assertEqual(report["issues"][0]["kind"], "mismatch")
        self.assertEqual(report["issues"][0]["decision_time"], f"decision-{attempted[1]}")
        self.assertEqual(len(attempted), len(set(attempted)))

    def test_exception_does_not_prevent_later_comparisons(self):
        attempted = []

        def validate(index):
            attempted.append(index)
            if len(attempted) == 2:
                raise RuntimeError("missing history")
            return _sample()

        report = collect_equivalence_report(range(100), validate, timeframes=("M5",))
        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(report["checked_decisions"], 30)
        self.assertEqual(report["attempted_decisions"], 31)
        self.assertEqual(report["errors"], 1)
        self.assertEqual(report["issues"][0]["message"], "missing history")

    def test_all_exceptions_are_bounded_and_recorded(self):
        attempted = []

        def validate(index):
            attempted.append(index)
            raise ValueError("history unavailable")

        report = collect_equivalence_report(range(300), validate, timeframes=("M5",))
        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(report["attempted_decisions"], 90)
        self.assertEqual(report["checked_decisions"], 0)
        self.assertEqual(report["skipped_decisions"], 90)
        self.assertEqual(report["errors"], 90)
        self.assertEqual(len(report["issues"]), 90)
        self.assertEqual(len(set(attempted)), 90)

    def test_empty_candidates_are_compared_but_do_not_pass(self):
        report = collect_equivalence_report(
            range(300), lambda index: _sample(0), timeframes=("M5",),
        )
        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(report["checked_decisions"], 90)
        self.assertEqual(report["empty_candidate_decisions"], 90)
        self.assertEqual(report["skipped_decisions"], 0)
        self.assertEqual(report["missing_candidate_timeframes"], ["M5"])
        self.assertFalse(report["fully_exercised"])

    def test_missing_timeframe_evidence_is_supplemented(self):
        attempted = []

        def validate(index):
            attempted.append(index)
            return _sample(timeframe="H1" if len(attempted) > 30 else "M5")

        report = collect_equivalence_report(
            range(300), validate, timeframes=("M5", "H1"),
        )
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["checked_decisions"], 31)
        self.assertEqual(report["missing_candidate_timeframes"], [])
        self.assertEqual(report["checked_candidates_by_timeframe"], {"M5": 30, "H1": 1})

    def test_fewer_than_thirty_decisions_are_not_a_pass(self):
        report = collect_equivalence_report(range(5), lambda index: _sample())
        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(report["requested_samples"], 30)
        self.assertEqual(report["checked_decisions"], 5)
        self.assertEqual(report["attempted_decisions"], 5)

    def test_no_indices_does_not_pass_or_call_validator(self):
        def validate(index):
            self.fail("no index should be validated")

        report = collect_equivalence_report([], validate, timeframes=("M5",))
        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(report["attempted_decisions"], 0)
        self.assertFalse(report["fully_exercised"])

    def test_duplicate_indices_do_not_inflate_coverage(self):
        report = collect_equivalence_report([1] * 30, lambda index: _sample())
        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(report["eligible_decisions"], 1)
        self.assertEqual(report["checked_decisions"], 1)

    def test_description_error_is_recorded_without_hiding_original_error(self):
        def describe(index):
            raise RuntimeError("description unavailable")

        def validate(index):
            if index == 0:
                raise ValueError("invalid candle")
            return _sample()

        report = collect_equivalence_report(range(100), validate, describe_index=describe)
        self.assertEqual(report["checked_decisions"], 30)
        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(report["errors"], 2)
        self.assertEqual(
            [issue["kind"] for issue in report["issues"]],
            ["description_error", "error"],
        )
        self.assertEqual(report["issues"][1]["message"], "invalid candle")

    def test_zero_checked_decisions_are_not_counted_as_success(self):
        def validate(index):
            return {"checked_decisions": 0, "checked_candidates": 0}

        report = collect_equivalence_report(range(2), validate)
        self.assertEqual(report["checked_decisions"], 0)
        self.assertEqual(report["skipped_decisions"], 2)
        self.assertEqual(report["errors"], 2)
        self.assertEqual(report["status"], "incomplete")

    def test_preparation_failure_uses_the_same_incomplete_schema(self):
        report = make_unavailable_equivalence_report(
            RuntimeError("input unavailable"), timeframes=("M5", "H1"),
        )
        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(report["errors"], 1)
        self.assertEqual(report["checked_decisions"], 0)
        self.assertEqual(report["missing_candidate_timeframes"], ["M5", "H1"])
        self.assertEqual(report["issues"][0]["kind"], "preparation_error")

    def test_invalid_index_preparation_is_recorded(self):
        report = collect_equivalence_report(["not-an-index"], lambda index: _sample())
        self.assertEqual(report["status"], "incomplete")
        self.assertEqual(report["attempted_decisions"], 0)
        self.assertEqual(report["issues"][0]["kind"], "preparation_error")

    def test_keyboard_interrupt_propagates(self):
        def validate(index):
            raise KeyboardInterrupt()

        with self.assertRaises(KeyboardInterrupt):
            collect_equivalence_report(range(300), validate)

    def test_system_exit_propagates(self):
        def validate(index):
            raise SystemExit(2)

        with self.assertRaises(SystemExit):
            collect_equivalence_report(range(300), validate)


if __name__ == "__main__":
    unittest.main()
