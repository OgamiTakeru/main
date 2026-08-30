# 最新更新日時: 2026-08-29 17:37 JST
"""flip_predict のオーダー発行前の見張りを、ポジションスロット上で行う。

classPosition はポジションを監視する責務だけを持ち、flip 固有の判断は持たない。
このファイルが origin="flip" のハンドラとして登録され、スロットが待機状態
（waiting_order=True）の間だけ呼ばれる。

## 何を待つのか（検証と一致させてある）

train/OOS 検証（AUD_USD +271円 / EUR_USD +121円）が実際に使っていたのは
「ラインへの初回タッチで、シグナルの方向へライン価格の指値が約定する」だけの
経路である。検証結果の watch_entry_enabled は全件 False で、60 秒観測と
3 モード分岐（LineHolding / NearLine / Breakout）は**使われていない**。

そのため、ここでもタッチを検出したらそのまま発注する。観測と 3 モード分岐は
将来それを検証してから実装する。検証していない取引を実弾で行わないための
判断であり、機能を削ったのではなく「まだ検証していないので入れていない」。

## タッチ判定

スプレッドの半分を見込んだヒゲがライン価格へ届いた完成 S5 を最初の 1 本として
扱う。これは count2_flip_core.FlipPathInspector のタッチ判定と同じ考え方。

## S5 の扱い

共有の candle_analysis_class.s5_completed_df_r は最大5本（25秒）である。mode2 は
2 秒ごとに回り 1 回の取得が 25 秒を覆うので、ここで受け取ったバーを時刻で
重複排除しながら貯めれば取りこぼさない。
"""

from __future__ import annotations

import datetime

import pandas as pd

import classPosition
import fFlipPredictPolicy as flip_policy
import fGeneric as gene


ORIGIN = "flip"

S5_SECONDS = 5
# 貯めておく S5 の最大本数（タッチ判定に十分な余裕）。
MAX_BUFFER_BARS = 240


def _naive_jst(value):
    """時刻をJSTへ変換してからnaiveなTimestampへ揃える。"""
    stamp = pd.to_datetime(value, errors="coerce")
    if pd.isna(stamp):
        return pd.NaT
    stamp = pd.Timestamp(stamp)
    if stamp.tzinfo is not None:
        stamp = stamp.tz_convert("Asia/Tokyo").tz_localize(None)
    return stamp


def _completion_flag_is_true(value):
    """True/1だけを完成として扱い、欠損や文字列は完成扱いしない。"""
    try:
        return bool(value == True)
    except (TypeError, ValueError):
        return False


def _extract_bars(candle_analysis_class, not_before=None):
    """共有フレームから完成 S5 を古い順で取り出す。

    形成中のバーは使わない。高値・安値がまだ動くため、確定していない値で
    タッチと判定すると、実際には触れていない位置で発注しうる。

    ``not_before`` を渡すと、その時刻より前に始まったバーを捨てる。注文を
    出す前から既にラインへ触れていた足を「注文後の初回タッチ」と取り違えて
    即発注するのを防ぐ。検証（FlipPathInspector）も判断時刻以降の S5 しか
    見ないので、ここを揃えないと本番と検証で挙動が食い違う。

    完成フラグまたは見張り開始時刻を確認できない場合は、誤発注を避けるため
    1本も返さない。
    """
    if not_before is None:
        return []
    s5_completed_df_r = getattr(
        candle_analysis_class,
        "s5_completed_df_r",
        None,
    )
    if s5_completed_df_r is None or len(s5_completed_df_r) == 0:
        return []
    if "time_jp" not in s5_completed_df_r.columns:
        return []
    completion_column = next(
        (
            name
            for name in ("is_complete", "complete")
            if name in s5_completed_df_r.columns
        ),
        None,
    )
    if completion_column is None:
        return []
    bars = []
    for row in s5_completed_df_r.to_dict("records"):
        if not _completion_flag_is_true(row.get(completion_column)):
            continue
        stamp = _naive_jst(row.get("time_jp"))
        if pd.isna(stamp):
            continue
        if not_before is not None and stamp < not_before:
            continue
        try:
            bars.append(
                {
                    "time": stamp,
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                }
            )
        except (KeyError, TypeError, ValueError):
            continue
    bars.sort(key=lambda item: item["time"])
    return bars


def flip_state(position):
    """スロットに紐づく flip の見張り状態を取り出す（無ければ作る）。"""
    state = getattr(position, "flip_watch_state", None)
    if state is None:
        plan = position.plan_json or {}
        state = {
            "phase": "PENDING_TOUCH",
            "bars": [],
            "line_price": float(plan.get("flip_line_price", 0.0)),
            "peak_direction": int(plan.get("flip_peak_direction", 0)),
            "spread_pips": float(plan.get("flip_spread_pips", 0.8)),
            "touch_time": None,
            # この時刻より前に始まった S5 は見張りの対象外。注文を出す前の
            # タッチを初回タッチと誤認しないための下限。
            "watch_from": _watch_start(position, plan),
        }
        position.flip_watch_state = state
    return state


def _watch_start(position, plan):
    """判断時刻と注文登録時刻のうち、遅い方から見張りを始める。"""
    candidates = []
    registered = getattr(position, "order_register_time", None)
    if registered:
        stamp = _naive_jst(registered)
        if not pd.isna(stamp):
            candidates.append(stamp)
    decision = plan.get("decision_time")
    if decision:
        stamp = _naive_jst(decision)
        if not pd.isna(stamp):
            candidates.append(stamp)
    return max(candidates) if candidates else None


def clear_flip_state(position):
    """スロットを使い回すときに、前回の見張り状態を残さない。

    classPosition.reset() から呼ばれる。動的属性のまま放置すると、次に同じ
    スロットへ入った注文が前回の DONE や貯めたバーを引き継いでしまう。
    """
    if hasattr(position, "flip_watch_state"):
        del position.flip_watch_state


def _absorb_bars(state, bars):
    """受け取ったバーを、時刻の重複を除きながら貯める。"""
    known = {item["time"] for item in state["bars"]}
    added = False
    for bar in bars:
        if bar["time"] in known:
            continue
        state["bars"].append(bar)
        known.add(bar["time"])
        added = True
    if added:
        state["bars"].sort(key=lambda item: item["time"])
        if len(state["bars"]) > MAX_BUFFER_BARS:
            state["bars"] = state["bars"][-MAX_BUFFER_BARS:]
    return added


def _detect_touch(state, pair_info):
    """スプレッドを見込んだヒゲが初めてラインへ届いたバーを返す。"""
    line_price = state["line_price"]
    direction = state["peak_direction"]
    if not line_price or direction not in (-1, 1):
        return None
    half_spread = pair_info.pips_to_price(state["spread_pips"] / 2.0)
    for bar in state["bars"]:
        if direction == 1:
            if bar["high"] - half_spread >= line_price:
                return bar
        else:
            if bar["low"] + half_spread <= line_price:
                return bar
    return None


def watch(position, candle_analysis_class):
    """origin="flip" のスロットが待機中に呼ばれる本体。

    タッチを検出したらそのまま発注する（検証と同じ経路）。発注したら
    waiting_order を False にする。タッチが来ない間は待機のまま 0 を返し、
    期限切れは classPosition 側の待機タイムアウトが面倒を見る。
    """
    if candle_analysis_class is None:
        return 0
    state = flip_state(position)
    if state["phase"] == "DONE":
        return 0
    if not _absorb_bars(
        state, _extract_bars(candle_analysis_class, state.get("watch_from"))
    ):
        return 0

    pair_info = gene.currency_pair(position.pair)
    touch = _detect_touch(state, pair_info)
    if touch is None:
        return 0

    state["touch_time"] = touch["time"]
    state["phase"] = "DONE"
    return _submit(position, state)


def _submit(position, state):
    """ライン価格の指値として発注する（検証の約定と同じ形）。

    検証では約定価格が常にライン価格そのもので、方向もシグナルの
    trade_direction のままだった。したがってここで方向や価格を作り替えず、
    登録済みのプランをそのまま発注する。
    """
    order_res = position.make_order()
    position.waiting_order = False  # 超大事（既存の発注経路と同じ約束）
    position.watching_for_position_done = True
    position.o_state = "PENDING"
    return order_res


classPosition.register_origin_watch_handler(ORIGIN, watch, clear_flip_state)

# 再起動したとき、OANDA に残った建玉のタグから出自を戻せるようにする。
# メモリ上の origin はプロセスと一緒に消えるが、タグは建玉に残っている。
for _pair, _spec in flip_policy.APPROVED_PAIRS.items():
    classPosition.register_origin_owner_tag(_spec["owner_tag"], ORIGIN)
