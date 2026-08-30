# 最新更新日時: 2026-08-27 JST
"""同時保有を許した場合の成績を、OOS 期間で測る。

これまでの検証は「flip は常に 1 つだけ」で回っていた。待機中または保有中の
一件が片付くまで、後続のシグナルを見送る作り（count2_flip_workflow の
locked_until）で、+271円 / +121円 といった数字はすべてこの前提のもの。

ポジションをスロットで管理するようになり同時保有が可能になったため、
見送っていたぶんを取ったら損益がどうなるかを確かめる。

train 側は全パスが出力済みなのでファイルから測れるが、OOS 側は
ベースラインの全パスが残っていないため、ここで作り直してから比較する。
既存のパイプラインには手を入れない（読むだけ）。

    python count2_flip_parallel_check.py
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import time
from pathlib import Path

import pandas as pd

import tokens as tk
from count2_flip_analysis import (
    DEFAULT_OOS_END,
    DEFAULT_OOS_START,
    DEFAULT_TRAIN_END,
    DEFAULT_TRAIN_START,
    analysis_output_paths,
)
from count2_flip_core import (
    FlipPathConfig,
    LineWickLcConfig,
    PolicyCondition,
    RiskMultipleProfitLock,
    TierExecutionConfig,
)
from count2_flip_workflow import (
    candidate_source_path,
    inspect_line_wick_lc_grid_paths,
    load_candidates,
    load_path_inspector,
    replay_condition,
    risk_multiple_profit_lock_inspectors,
    s5_source_path,
    select_top_condition_policy_candidates,
    target_distance_filter_mask,
)
from count2_flip_core import RankedPolicyCondition


PAIRS = ("AUD_USD", "EUR_USD", "USD_JPY")


def _artifact(pair, output_dir):
    paths = analysis_output_paths(
        output_dir,
        pair,
        DEFAULT_TRAIN_START,
        DEFAULT_TRAIN_END,
        DEFAULT_OOS_START,
        DEFAULT_OOS_END,
    )
    return json.loads(paths["artifact"].read_text(encoding="utf-8")), paths


def oos_baseline_paths(pair, output_dir):
    """凍結ポリシーで OOS を走らせ、ベースラインの全パスを作り直す。"""
    artifact, paths = _artifact(pair, output_dir)
    top_policy = artifact["top_condition_policy"]
    tier_configs = tuple(
        TierExecutionConfig.from_dict(item)
        for item in artifact["tier_execution_configs"]
    )
    ranked = tuple(
        RankedPolicyCondition.from_dict(item)
        for item in artifact["selected_top_conditions"]
    )
    execution = artifact["execution"]

    candidates = load_candidates(
        candidate_source_path(
            pair, DEFAULT_OOS_START, DEFAULT_OOS_END, output_dir
        ),
        pair=pair,
        start=DEFAULT_OOS_START,
        end=DEFAULT_OOS_END,
    )
    candidates = candidates[
        target_distance_filter_mask(
            candidates, execution["min_target_distance_pips"]
        )
    ].copy()
    selected = select_top_condition_policy_candidates(
        candidates,
        ranked,
        tier_configs,
        minimum_matched_conditions=int(
            top_policy["minimum_matched_conditions"]
        ),
    )
    profit_lock = execution.get("profit_lock", {})
    inspector, _ = load_path_inspector(
        s5_source_path(pair, DEFAULT_OOS_START, DEFAULT_OOS_END, output_dir),
        pair_name=pair,
        start=DEFAULT_OOS_START,
        end=DEFAULT_OOS_END,
        spread_pips=float(execution["spread_pips"]),
        position_horizon_minutes=int(execution["position_horizon_minutes"]),
        min_width_pips=float(execution["min_width_pips"]),
        risk_yen=float(execution["risk_yen"]),
        profit_lock_enabled=bool(profit_lock["enabled"]),
        profit_lock_min_tp_pips=float(profit_lock["minimum_effective_tp_pips"]),
        profit_lock_trigger_tp_fraction=float(
            profit_lock["trigger_tp_fraction"]
        ),
        profit_lock_result_pips=float(profit_lock["locked_result_pips"]),
    )
    lock_spec = top_policy.get("risk_multiple_profit_lock")
    inspectors_by_tier = (
        risk_multiple_profit_lock_inspectors(
            inspector,
            tier_configs,
            RiskMultipleProfitLock(
                trigger_r=float(lock_spec["trigger_r"]),
                result_r=float(lock_spec["result_r"]),
            ),
        )
        if lock_spec
        else None
    )
    frame = inspect_line_wick_lc_grid_paths(
        selected,
        inspector,
        FlipPathConfig(
            artifact["selected_path_config"]["order_wait_minutes"]
        ),
        tier_configs,
        (LineWickLcConfig(None),),
        pair=pair,
        phase="parallel_check_oos",
        period_start=DEFAULT_OOS_START,
        progress_file=paths["progress"],
        started=time.monotonic(),
        notify=None,
        inspectors_by_tier=inspectors_by_tier,
    )
    return frame[frame["line_wick_lc_config_id"].eq("baseline")].copy()


def compare(frame, label):
    condition = PolicyCondition("ALL", "all")
    rows = []
    for name, one_at_a_time in (
        ("1つだけ", True),
        ("全部取る", False),
    ):
        _, performance = replay_condition(
            frame, condition, one_at_a_time=one_at_a_time
        )
        rows.append(
            {
                "期間": label,
                "方式": name,
                "件数": performance["completed_trade_count"],
                "勝率": round(performance["win_rate"] * 100, 1),
                "PF": round(performance["profit_factor_yen"], 2),
                "損益": round(performance["sum_yen"], 1),
                "見送り": performance["skipped_while_locked_count"],
            }
        )
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="同時保有を許した場合の成績を比べる"
    )
    parser.add_argument("--pair", action="append", dest="pairs", default=None)
    parser.add_argument("--output-dir", type=Path, default=Path(tk.folder_path))
    args = parser.parse_args(argv)
    pairs = [p.upper() for p in (args.pairs or PAIRS)]

    for pair in pairs:
        print("=" * 46)
        print(pair)
        rows = []
        _, paths = _artifact(pair, args.output_dir)
        train_file = paths["line_wick_lc_paths"]
        if train_file.exists():
            train = pd.read_csv(train_file, low_memory=False)
            train = train[train["line_wick_lc_config_id"].eq("baseline")]
            rows += compare(train, "train")
        else:
            print("  train のパスが無いので飛ばす:", train_file.name)
        rows += compare(oos_baseline_paths(pair, args.output_dir), "OOS")
        print(pd.DataFrame(rows).to_string(index=False))
        print()


if __name__ == "__main__":
    main()
