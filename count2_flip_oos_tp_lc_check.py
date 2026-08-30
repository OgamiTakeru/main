# 最新更新日時: 2026-08-28 JST
"""凍結した TP/LC が、OOS でも最良だったのかを確かめる。

TP/LC は train 期間の総額（sum_yen）で選んでいる。train でたまたま大きく
伸びたトレードが総額を押し上げると、遠い TP が選ばれる。それが OOS でも
妥当だったかは、これまで確かめていなかった。

USD_JPY の OOS はその疑いが濃い。伸び（MFE/A 中央値 1.09）に対し TP は
1.7A で、19 件中 TP に届いたのは 2 件だけ。損切りは 10 件。「利確が遠すぎて
届かず、損切りには届く」形になっている。

ここでは凍結ポリシー（条件・tier・同時保有の制限）をそのままに、TP/LC だけを
振り直して OOS を測る。**選び直すためではなく、選び方が妥当だったかを見るため**
のもので、ここで良かった値を採用すると OOS で選定したことになり検証が壊れる。

    python count2_flip_oos_tp_lc_check.py --pair USD_JPY
"""

from __future__ import annotations

import argparse
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
    PolicyCondition,
    RankedPolicyCondition,
    TierExecutionConfig,
    TradeCombo,
    default_trade_combos,
)
from count2_flip_workflow import (
    candidate_source_path,
    inspect_trade_combo_grid_paths,
    load_candidates,
    load_path_inspector,
    range_filter_mask,
    replay_condition,
    s5_source_path,
    select_top_condition_policy_candidates,
    target_distance_filter_mask,
)


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


def run(pair, output_dir):
    artifact, paths = _artifact(pair, output_dir)
    top_policy = artifact["top_condition_policy"]
    execution = artifact["execution"]
    tier_configs = tuple(
        TierExecutionConfig.from_dict(item)
        for item in artifact["tier_execution_configs"]
    )
    ranked = tuple(
        RankedPolicyCondition.from_dict(item)
        for item in artifact["selected_top_conditions"]
    )
    frozen = {
        config.tier: TradeCombo.from_tp_rr(config.tp_a, config.rr)
        for config in tier_configs
    }

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
    combos = default_trade_combos(min_rr=1.0)
    grid = inspect_trade_combo_grid_paths(
        selected,
        inspector,
        FlipPathConfig(
            artifact["selected_path_config"]["order_wait_minutes"]
        ),
        combos,
        pair=pair,
        phase="oos_tp_lc_check",
        period_start=DEFAULT_OOS_START,
        progress_file=paths["progress"],
        started=time.monotonic(),
        notify=None,
    )

    # tier ごとの range filter は凍結値のまま使う（TP/LC だけを振る）。
    minimum_by_tier = {
        config.tier: config.min_range_filter_pips for config in tier_configs
    }
    rows = []
    condition = PolicyCondition("ALL", "all")
    for combo in combos:
        cell = grid[grid["grid_combo_id"].eq(combo.combo_id)]
        keep = []
        for tier, minimum in minimum_by_tier.items():
            part = cell[cell["signal_tier"].eq(tier)]
            if part.empty:
                continue
            keep.append(part[range_filter_mask(part, minimum)])
        if not keep:
            continue
        eligible = pd.concat(keep, ignore_index=True)
        _, performance = replay_condition(eligible, condition)
        rows.append(
            {
                "tp_a": combo.tp_a,
                "lc_a": round(combo.lc_a, 3),
                "RR": round(combo.configured_rr, 2),
                "件数": performance["completed_trade_count"],
                "勝率": round(performance["win_rate"] * 100, 1),
                "PF": round(performance["profit_factor_yen"], 2),
                "損益": round(performance["sum_yen"], 1),
            }
        )
    result = pd.DataFrame(rows)
    print(f"\n凍結されている TP/LC: ", {
        tier: f"tp{combo.tp_a:g}A/lc{combo.lc_a:.2f}A (RR{combo.configured_rr:.2f})"
        for tier, combo in frozen.items()
    })
    print("\n--- OOS を TP/LC で振り直した結果（損益順） ---")
    print(result.sort_values("損益", ascending=False).to_string(index=False))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="凍結 TP/LC が OOS でも妥当だったかを見る"
    )
    parser.add_argument("--pair", action="append", dest="pairs", default=None)
    parser.add_argument("--output-dir", type=Path, default=Path(tk.folder_path))
    args = parser.parse_args(argv)
    for pair in [p.upper() for p in (args.pairs or ["USD_JPY"])]:
        print("=" * 60)
        print(pair)
        run(pair, args.output_dir)


if __name__ == "__main__":
    main()
