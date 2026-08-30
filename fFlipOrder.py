# 最新更新日時: 2026-08-29 20:40 JST
"""flip_predict のシグナルを、既存のオーダー（OCreate.Order）に変換する。

flip は「オーダーを生む解析」に徹し、生まれたオーダーは既存のスロット
（classPositionControl）が他の戦略と同じように管理する。この橋渡しだけを
ここが担当する。

発注前の見張り（タッチ→観測→3モード判定）は fFlipWatch が、
発注後の損切り引き上げは classPosition の既存 lc_change が受け持つので、
ここでは「待機状態のオーダーを組み立てる」ことだけを行う。
"""

from __future__ import annotations

import datetime

import classOrderCreate as OCreate
import fFlipPredictPolicy as flip_policy
import fGeneric as gene
from count2_flip_core import effective_trade_widths


ORIGIN = "flip"

# ライン価格の指値。検証（OOS）でも約定価格は常にライン価格そのものだった。
INITIAL_ORDER_TYPE = "LIMIT"

MIN_WIDTH_PIPS = 1.6
RISK_YEN = 50.0
ORDER_WAIT_MINUTES = 60
POSITION_HORIZON_MINUTES = 60
FIXED_TOUCH_SPREAD_PIPS = 0.8
# クロス通貨の units 計算用。取得できなかったときだけ使う。
FALLBACK_USD_JPY_RATE = 160.0


def raised_stop_lc_change(policy, lc_pips):
    """損切り引き上げを、既存 lc_change の形に翻訳する。

    lc_change は「trigger まで含み益が伸びたら ensure の位置まで損切りを
    引き上げる」仕組みで、flip の「+trigger_r に達したら +result_r を確保」と
    同じことを言っている。R はそのトレード自身の損切り幅なので、pips へ直す
    のは lc_pips を掛けるだけでよい。

    policy が無い、または R 倍率が取れない場合は空を返し、引き上げなしにする。
    """
    if policy is None or policy.profit_lock is None:
        return []
    lock = policy.profit_lock
    lc_pips = float(lc_pips)
    if lc_pips <= 0:
        return []
    pair_info = gene.currency_pair(policy.pair)
    return [
        {
            "exe": True,
            "time_after": 0,
            "trigger": pair_info.pips_to_price(lc_pips * lock.trigger_r),
            "ensure": pair_info.pips_to_price(lc_pips * lock.result_r),
        }
    ]


def usd_jpy_rate_for(pair, oa):
    """クロス通貨の units 計算に要る USD/JPY レートを取る。

    USD_JPY 自身なら不要なので None。取得できない場合も注文を落とさず、
    既存の解析側と同じ保守的な既定値へ落とす（fLineAnalysis と同じ考え方）。
    """
    if str(pair).upper() == "USD_JPY":
        return None
    if oa is not None:
        try:
            response = oa.NowPrice_exe("USD_JPY")
            if response.get("error") == 0:
                return float(response["data"]["mid"])
        except Exception as error:  # 取得失敗で注文全体を落とさない
            print("[flip] USD_JPYレート取得に失敗、既定値を使う:", error)
    return FALLBACK_USD_JPY_RATE


def build_order(signal, pair, candle_analysis_class, policy=None, oa=None):
    """flip のシグナル一件を、待機状態のオーダーに変換する。

    signal は fFlipPredictLive.build_live_signal が返す辞書と同じ形。
    戻り値の Order は origin="flip" を持つので、スロットに登録されると
    fFlipWatch へ委譲され、観測が済むまで発注されない。
    """
    if policy is None:
        policy = flip_policy.live_policy(pair)
    pair_info = gene.currency_pair(pair)

    tp_pips = float(signal["tp_pips"])
    lc_pips = float(signal["lc_pips"])
    line_price = float(signal["line_price"])
    # 待機中の想定方向。観測後に反転する場合があるので、fFlipWatch が確定させる。
    provisional_direction = int(signal["order_direction"])

    order_json = {
        "name": f"Flip_{signal['signal_tier']}_{signal['highest_matched_rank']}",
        "pair": pair,
        "origin": ORIGIN,
        "owner_tag": policy.owner_tag,
        "current_price": line_price,
        # 待機の起点はライン価格。実際の建値は観測後の種別で決まる。
        "target": line_price,
        "direction": provisional_direction,
        "type": INITIAL_ORDER_TYPE,
        # 【最重要】False で登録しないと classPosition が即座に発注してしまい、
        # タッチ待ちが一度も動かない。待機させるための必須指定。
        "order_permission": False,
        "tp": pair_info.pips_to_price(tp_pips),
        "lc": pair_info.pips_to_price(lc_pips),
        "lc_change": raised_stop_lc_change(policy, lc_pips),
        "risk_yen": RISK_YEN,
        "usd_jpy_rate": usd_jpy_rate_for(pair, oa),
        "priority": _priority_for_tier(signal["signal_tier"]),
        "decision_time": signal["decision_time_utc"],
        "order_timeout_min": ORDER_WAIT_MINUTES,
        "trade_timeout_min": POSITION_HORIZON_MINUTES,
        "candle_analysis_class": candle_analysis_class,
        "memo": (
            f"flip {signal['signal_tier']} rank{signal['highest_matched_rank']} "
            f"tp{tp_pips:.1f}p lc{lc_pips:.1f}p"
        ),
        # fFlipWatch が見張りに使う情報（classPosition は中身を解釈しない）
        "flip_line_price": line_price,
        "flip_peak_direction": int(signal["peak_direction"]),
        "flip_average_range_pips": float(signal["a_range_pips"]),
        "flip_spread_pips": FIXED_TOUCH_SPREAD_PIPS,
        "flip_observation_seconds": policy.watch_config.observation_seconds,
        "flip_watch_config": policy.watch_config.to_dict(),
        "flip_signal_id": signal["signal_id"],
        "flip_policy_fingerprint": policy.fingerprint(),
    }
    return OCreate.Order(order_json)


def _priority_for_tier(tier):
    """tier を既存の priority 体系へ写す。

    既存は priority>=100 を high スロット、それ以外を通常スロットに割り当てる。
    flip は専用枠を持たず 15 枠を共用すると決めたので、high は使わず
    通常スロットの中で tier の順序だけを表す。
    """
    return {"HIGH": 30, "MIDDLE": 20, "LOW": 10}.get(str(tier), 10)


def has_approved_policy(pair):
    """Return whether flip has a reviewed live policy for this pair."""
    return str(pair).upper() in flip_policy.APPROVED_PAIRS


def has_active_flip(position_control):
    """flip 起点の待機注文または建玉が、すでに一つでもあるか。

    検証は「flip は常に 1 つだけ」で回っており、+271円 / +121円 という数字は
    その前提のもの。見送っていたぶんまで取ると成績は落ちる（OOS 実測:
    AUD_USD +271 -> +68、EUR_USD +121 -> +71）。同じ形にするため、
    すでに動いている flip があれば新しいシグナルを作らない。

    再起動後も効くよう、出自は OANDA のタグから復元される
    （classPosition.catch_exist_position）。
    """
    for slot in getattr(position_control, "position_classes", []):
        if not getattr(slot, "life", False):
            continue
        if getattr(slot, "origin", "") == ORIGIN:
            return True
    return False


def build_orders_for_decision(oa, pair, decision_utc, candle_analysis_class):
    """5分足の判断時刻ぶんの flip オーダーを作る（無ければ空リスト）。

    シグナルの組み立ては、渡された CandleAnalysis の完成足を使う。
    判定本体は研究パイプラインと同じ関数群（add_feature_buckets /
    select_top_condition_policy_candidates など）を通る経路なので、
    「検証したロジック＝実際に動くロジック」が保たれる。ここで別実装を
    起こしてはいけない。M5/H1 の再取得も行わない。

    足確定の公開待ちや休場は例外にせず空リストで次回へ回す。
    未知欠損など履歴整合性の異常は、通常のno-signalと区別するため
    上位の解析wrapへ再送出する。
    """
    # 遅延 import（起動時に必ずライブ側を読み込ませないため）
    import fFlipPredictLive as flip_live

    policy = flip_live.bind_policy(pair)
    try:
        signal = flip_live.build_signal_from_candle_analysis(
            candle_analysis_class,
            decision_utc,
        )
    except flip_live.LiveDataNotReady:
        # OANDAの足確定反映待ちは本番で起こり得る正常状態。エラー表示しない。
        return []
    except flip_live.LiveDataIntegrityError:
        # 未知欠損は通常のno-signalに丸めず、wrap側へ返す。
        raise
    except flip_live.LiveDataError as error:
        print("[flip] シグナル組み立てを見送り:", error)
        return []
    if not signal:
        return []
    return [
        build_order(signal, pair, candle_analysis_class, policy=policy, oa=oa)
    ]
