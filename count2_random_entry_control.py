# 最新更新日時: 2026-09-03 06:54 JST
"""抵抗線と「同じ時刻・同じ向き」で、置く価格だけを無作為にした対照群を作る。

## なぜ要るか

「ランダムなら勝つ確率 = LC距離 ÷ (TP距離 + LC距離)」という理論式は、
**どちらかの壁に当たるまで待ち続ける**場合のもの。実際は60分で打ち切り、
時間切れを決着から除外しているため、そのまま基準にすると偏る。

除外は中立ではない。利確が近く損切りが遠い設定では、損切りへ向かう遅い動きが
時間切れで捨てられ、決着した中では利確が過剰に多くなる。実測の時間切れ率は
セルによって2.2%〜74%と大きく変わり、この偏りが「優位性」として現れていた。

## どう作るか（2026-09-02 改訂：同一時刻で対応づける）

最初の版は「無作為な時刻」から抽出していたが、それだと相場環境がずれる。
実測で**抵抗線側のAが対照群より約1割高かった**（AUD 2.73 対 2.45 pips）。
count=2 は価格が動いて転換した直後に起きるので、静かな時間帯では発生しにくい。
無作為抽出は静かな時間も等しく拾うため平均が下がる。

A がずれると、同じ「利確3.0A」でも実際のpips幅が違い、
固定コスト（スプレッド0.8pips）の相対的な重みが変わってしまう。

そこで**抵抗線側の候補一件ごとに、同じ判断時刻・同じ注文方向を使い、
置く価格だけを無作為に引き直す**。こうすると：

- A（ボラティリティ）… 同じ時刻なので完全に一致
- 時間帯・曜日・指標の有無 … 同じ時刻なので完全に一致
- 保留期限（次のcount2まで）… 同じ
- 注文の向き … 同じ

**違うのは「注文をどこに置くか」だけ**になる。これがまさに測りたいこと。

厳密には、無作為に引いた価格がたまたま本物のラインの近くに来ることがある。
ただしこれは差が出にくくなる方向にしか働かないので、優位性を過大評価しない。

    python count2_random_entry_control.py
"""

from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd

import fGeneric as gene
import tokens as tk
from count2_resistance_sweep import (
    LimitPathInspector,
    TARGET_GRID_LC_A,
    TARGET_GRID_TP_A,
    TargetGridAccumulator,
    load_pair_data,
)


PAIRS = ("AUD_USD", "EUR_USD", "USD_JPY")
START = dt.datetime(2025, 7, 30, 0, 0, 0)
END = dt.datetime(2026, 7, 30, 0, 0, 0)
HORIZON_MINUTES = 60
SPREAD_PIPS = 0.8
STOP_OFFSET_PIPS = 1.0
STOP_SLIPPAGE_PIPS = 0.5
SEED = 20260902

# 対応づける抵抗線側の結果。ライン生成を変えたらここも変えること。
SOURCE_TAG = (
    "m5line60_range6x3_rr1.2_sp0.8_60m"
    "_strong_grp0.5A_far0.5A_str10_noflip_dirsplit_minpk2_breakoff1slip0.5"
)
OUTPUT_SUFFIX = "v3_matched"

SOURCE_COLUMNS = [
    "decision_time",
    "next_count2_time",
    "recent_m5_avg_range_pips",
    "decision_price",
    "line_side",
    "trade_direction",
    "distance_pips",
    "line_is_flipped",
]


def load_source(pair_name: str, output_dir: Path) -> pd.DataFrame:
    """抵抗線側の候補を読み、対応づけの土台にする。"""
    path = output_dir / (
        f"resistance_sweep_candidates_{pair_name}_"
        f"{START:%Y%m%d}_{END:%Y%m%d}_{SOURCE_TAG}.csv"
    )
    frame = pd.read_csv(path, usecols=SOURCE_COLUMNS, low_memory=False)
    frame = frame[
        frame["line_is_flipped"].astype(str).str.lower().eq("false")
    ].copy()
    for column in (
        "recent_m5_avg_range_pips",
        "decision_price",
        "distance_pips",
        "trade_direction",
    ):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame[
        (frame["recent_m5_avg_range_pips"] > 0)
        & (frame["distance_pips"] > 0)
        & frame["decision_price"].notna()
        & frame["trade_direction"].isin((-1, 1))
    ]
    if frame.empty:
        raise ValueError(f"{pair_name}: 対応づけできる候補がありません")
    return frame.reset_index(drop=True)


def run(pair_name: str, output_dir: Path) -> Path:
    pair = gene.currency_pair(pair_name)
    source = load_source(pair_name, output_dir)
    # 抵抗線側とまったく同じ読み込み経路。ここが違うと比較がデータ差になる。
    _m5, _m30, _h1, s5 = load_pair_data(
        pair_name,
        START,
        END,
        True,  # existing_only: OANDAへは取りに行かない
        HORIZON_MINUTES,
    )
    inspector = LimitPathInspector(s5, pair)
    rng = np.random.default_rng(SEED)
    distances = source["distance_pips"].to_numpy(dtype=float)

    accumulator = TargetGridAccumulator(SPREAD_PIPS)
    cells = [
        (tp_a, lc_a)
        for tp_a in TARGET_GRID_TP_A
        for lc_a in TARGET_GRID_LC_A
    ]
    used = 0
    for row in source.itertuples(index=False):
        side = 1 if str(row.line_side) == "upper" else -1
        average_range = float(row.recent_m5_avg_range_pips)
        # 距離だけを引き直す。時刻・向き・Aはそのまま使う。
        distance = float(rng.choice(distances))
        price = float(row.decision_price) + side * pair.pips_to_price(distance)

        targets = [
            (average_range * tp_a, average_range * lc_a)
            for tp_a, lc_a in cells
        ]
        results = inspector.inspect_targets(
            decision_time=pd.Timestamp(row.decision_time),
            expiry_time=pd.Timestamp(row.next_count2_time),
            direction=int(row.trade_direction),
            line_price=price,
            targets=targets,
            horizon_minutes=HORIZON_MINUTES,
            spread_pips=SPREAD_PIPS,
            approach_side=side,
            entry_mode="stop",
            stop_offset_pips=STOP_OFFSET_PIPS,
            stop_slippage_pips=STOP_SLIPPAGE_PIPS,
        )
        if not results[0].get("filled"):
            continue
        used += 1
        for (tp_a, lc_a), (tp_pips, lc_pips), result in zip(
            cells, targets, results
        ):
            accumulator.add(
                tp_a,
                lc_a,
                "random",
                "random",
                tp_pips,
                lc_pips,
                result,
            )

    frame = accumulator.to_frame()
    destination = output_dir / (
        f"random_entry_control_{pair_name}_"
        f"{START:%Y%m%d}_{END:%Y%m%d}_{OUTPUT_SUFFIX}_grid.csv"
    )
    frame.to_csv(destination, index=False, encoding="utf-8-sig")
    matched_a = source["recent_m5_avg_range_pips"]
    print(
        f"{pair_name}: 対応づけ={len(source):,} 約定={used:,}  "
        f"A中央値={matched_a.median():.2f}pips（抵抗線側と同一）  "
        f"-> {destination.name}"
    )
    return destination


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="同じ時刻・同じ向きで、置く価格だけ無作為にした対照群を作る"
    )
    parser.add_argument("--pair", action="append", dest="pairs", default=None)
    parser.add_argument("--output-dir", type=Path, default=Path(tk.folder_path))
    args = parser.parse_args(argv)
    for pair_name in [p.upper() for p in (args.pairs or PAIRS)]:
        run(pair_name, args.output_dir)


if __name__ == "__main__":
    main()
