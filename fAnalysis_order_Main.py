# 最新更新日時: 2026-08-30 15:42 JST

import datetime
from dataclasses import dataclass

import fLineAnalysis as ti
import fFlipWatch  # noqa: F401  登録済みflipの出自ハンドラを起動時に登録する
import classOrderCreate as OCreate
import fGeneric as gene
import send_notice as notice


@dataclass(frozen=True)
class AnalysisRegistration:
    """解析の有効モード、実行条件、呼び出し先を一か所で管理する。"""

    name: str
    enabled_modes: tuple
    runner_method: str
    due_method: str = ""
    live_order_mode: str = "execute"


# 解析を追加するときは、解析固有のrunnerを用意してここへ登録する。
# main_exeは解析名・有効フラグ・固有の実行時刻を知らない。
ANALYSIS_REGISTRY = (
    AnalysisRegistration(
        name="line",
        enabled_modes=("inspection",),
        runner_method="wrap_line_analysis",
    ),
    AnalysisRegistration(
        name="flip",
        enabled_modes=("live",),
        runner_method="wrap_flip_analysis",
        due_method="flip_analysis_is_due",
    ),
    AnalysisRegistration(
        name="double_top",
        # 本番データで解析・注文組み立てまでは行うが、実発注はしない。
        enabled_modes=("inspection", "live"),
        runner_method="wrap_double_top_analysis",
        due_method="double_top_analysis_is_due",
        live_order_mode="trial",
    ),
)

_ANALYSIS_REGISTRATION_BY_NAME = {
    registration.name: registration
    for registration in ANALYSIS_REGISTRY
}
_LIVE_LINE_REGIME_CACHE = {}




class wrap_all_analysis():
    def __init__(
        self,
        candle_analysis_class,
        position_control_class=None,
        mode="inspection",
        strategy_regime=None,
        *,
        analysis_time_utc=None,
        decision_time_utc=None,
    ):
        # 調査に必要な変数
        self.ca = candle_analysis_class  # CandleAnalysisインスタンスの生成
        self.mode = mode  # Liveとアナリシスでは微妙に扱いが異なる場所がある
        self.position_control_class = position_control_class
        self.strategy_regime = strategy_regime
        self.analysis_time_utc = analysis_time_utc
        self.decision_time_utc = decision_time_utc

        # 結果を格納するための変数（大事）
        self.take_position_flag = False
        self.exe_order_classes = []
        self.turn_analysis_instance = None
        self.regime_snapshot = None
        self.flip_order_classes = []
        self.double_top_order_classes = []
        self.trial_order_classes = []
        self.position_control_result = None

        # 実行
        self.run_registered_analyses()
        self.register_orders_with_position_control()

        # 最終的なオーダー
        print("最終的なオーダー")
        for exe_order_class in self.exe_order_classes:
            print("-", exe_order_class.exe_order_plan['name'])
            print("  ", exe_order_class.exe_order_plan)
        print("trial注文（組み立てのみ・発注しない）")
        for trial_order_class in self.trial_order_classes:
            print("-", trial_order_class.exe_order_plan['name'])
            print("  ", trial_order_class.exe_order_plan)

    def orders_add_this_class(self, order_classes):
        """

        """
        self.take_position_flag = True
        if isinstance(order_classes, (list, tuple)):
            self.exe_order_classes.extend(order_classes)
        else:
            self.exe_order_classes.append(order_classes)

    def orders_replace_this_class(self, order_classes):
        """
        オーダーを置き換えるよう（前の検証のオーダーは忘れる漢字）
        """
        self.take_position_flag = True
        if isinstance(order_classes, (list, tuple)):
            self.exe_order_classes.extend(order_classes)
        else:
            self.exe_order_classes.append(order_classes)
        # self.exe_order_classes.extend(order_class)

    def orders_add_from_analysis(self, analysis_name, order_classes):
        """解析ごとの本番注文モードに従い、実発注用とtrial用を分離する。"""
        if not order_classes:
            return
        registration = _ANALYSIS_REGISTRATION_BY_NAME[analysis_name]
        if (
                self.mode == "live"
                and registration.live_order_mode == "trial"
        ):
            self.orders_add_trial_this_class(
                analysis_name,
                order_classes,
            )
            return
        if registration.live_order_mode not in ("execute", "trial"):
            raise ValueError(
                analysis_name + " has an invalid live_order_mode"
            )
        self.orders_add_this_class(order_classes)

    def orders_add_trial_this_class(self, analysis_name, order_classes):
        """注文を発注不能にしてtrial専用リストへ隔離する。"""
        classes = (
            list(order_classes)
            if isinstance(order_classes, (list, tuple))
            else [order_classes]
        )
        for order_class in classes:
            order_class.order_permission = False
            order_class.order_json["order_permission"] = False
            order_class.exe_order_plan["order_permission"] = False
            order_class.exe_order_plan["execution_mode"] = "trial"
        self.trial_order_classes.extend(classes)
        self.notify_trial_orders(analysis_name, classes)

    def notify_trial_orders(self, analysis_name, order_classes):
        """trial成立内容を、実発注ではないことが分かる形でDiscordへ送る。"""
        lines = [
            "【" + analysis_name + " trial no order】",
            "- 解析と注文組み立てのみ（発注なし）",
        ]
        for index, order_class in enumerate(order_classes, start=1):
            plan = order_class.exe_order_plan
            lines.extend((
                "- 候補" + str(index) + " 通貨: " + str(plan.get("pair")),
                "- 売買: " + (
                    "買い" if int(plan.get("direction") or 0) == 1 else "売り"
                ),
                "- エントリー想定: " + str(plan.get("target_price")),
                "- 利確: " + str(plan.get("tp_price")),
                "- 損切り: " + str(plan.get("lc_price")),
                "- priority: " + str(plan.get("priority")),
            ))
        notice.line_send("\n".join(lines))

    def register_orders_with_position_control(self):
        """本番注文をまとめてPositionControlへ一度だけ渡す。"""
        if self.mode != "live":
            return
        if self.position_control_class is None:
            raise ValueError("live analysis requires position_control_class")
        if not self.exe_order_classes:
            self.position_control_result = 0
            return
        self.position_control_result = (
            self.position_control_class.order_class_add(
                self.exe_order_classes
            )
        )

    def run_registered_analyses(self):
        """現在のモードで有効な解析を、登録順に実行する。

        一つの解析で例外が出ても、他の解析とループは続ける。ここで受け止めて
        おくことで、解析を追加する側は例外処理を書かなくてよい（書き忘れて
        本番のループごと止める事故を防ぐ）。
        """
        for registration in ANALYSIS_REGISTRY:
            if self.mode not in registration.enabled_modes:
                continue
            try:
                if registration.due_method:
                    if not getattr(self, registration.due_method)():
                        continue
                getattr(self, registration.runner_method)()
            except Exception as error:
                self.notify_analysis_failure(registration.name, error)

    def notify_analysis_failure(self, name, error):
        """解析一つ分の失敗を知らせる。ここでは握りつぶすだけで止めない。"""
        print(f"[{name}] 解析で例外:", type(error).__name__, error)
        if self.mode != "live":
            # 検証中は大量に飛ぶ可能性があるので通知しない。
            return
        notice.line_send(
            "【" + str(name) + "解析の失敗】"
            + "\n- " + type(error).__name__ + ": " + str(error)
            + "\n- 他の解析とループは継続する"
        )

    def wrap_line_analysis(self):
        """共有 CandleAnalysis から従来のライン解析を実行する。"""
        strategy_regime = self.strategy_regime
        if strategy_regime is None and self.mode == "live":
            import classStrategyRegime

            pair = getattr(self.ca, "pair", "USD_JPY")
            cache_key = (pair, self.mode)
            strategy_regime = _LIVE_LINE_REGIME_CACHE.get(cache_key)
            if strategy_regime is None:
                strategy_regime = classStrategyRegime.StrategyRegime(
                    pair,
                    mode=self.mode,
                )
                _LIVE_LINE_REGIME_CACHE[cache_key] = strategy_regime
            self.strategy_regime = strategy_regime

        turn_analysis_instance = ti.MainAnalysis(
            self.ca,
            self.position_control_class,
            self.mode,
            strategy_regime=strategy_regime,
        )
        self.turn_analysis_instance = turn_analysis_instance
        self.regime_snapshot = turn_analysis_instance.regime_snapshot
        if turn_analysis_instance.take_position_flag:
            self.orders_add_from_analysis(
                "line",
                turn_analysis_instance.exe_order_classes,
            )

    def m5_analysis_is_due(self):
        """完成M5を使う解析の本番実行窓。検証では毎判断時刻を処理する。"""
        if self.mode != "live":
            return True
        if self.analysis_time_utc is None:
            return False
        return (
            self.analysis_time_utc.minute % 5 == 0
            and 6 <= self.analysis_time_utc.second < 30
        )

    def flip_analysis_is_due(self):
        """flip固有の登録名から、共通のM5実行窓へ委譲する。"""
        return self.m5_analysis_is_due()

    def double_top_analysis_is_due(self):
        """ダブルトップ固有の登録名から、共通のM5実行窓へ委譲する。"""
        return self.m5_analysis_is_due()

    def wrap_flip_analysis(self):
        """共有 CandleAnalysis から flip の待機オーダーを組み立てる。

        例外は run_registered_analyses が受け止めるので、ここでは捕まえない。
        """
        import fFlipOrder

        pair = getattr(self.ca, "pair", "")
        if not fFlipOrder.has_approved_policy(pair):
            print(f"[flip] {pair or '(pair missing)'}: 承認済みポリシーなし、見送り")
            return
        if fFlipOrder.has_active_flip(self.position_control_class):
            # 検証ロジックと同じく、flip は同時に一つだけ動かす。
            return
        if self.decision_time_utc is None:
            raise ValueError("flip analysis requires decision_time_utc")

        self.flip_order_classes = fFlipOrder.build_orders_for_decision(
            getattr(self.ca, "base_oa", None),
            pair,
            self.decision_time_utc,
            self.ca,
        )
        if self.flip_order_classes:
            self.orders_add_from_analysis("flip", self.flip_order_classes)

    def wrap_double_top_analysis(self):
        """共有 CandleAnalysis からダブルトップの検出と注文生成を行う。"""
        import f_ダブルトップ as double_top

        self.double_top_order_classes = double_top.build_orders_for_decision(
            self.ca,
            mode=self.mode,
        )
        if self.double_top_order_classes:
            self.orders_add_from_analysis(
                "double_top",
                self.double_top_order_classes,
            )

    def _removed_flip_except(self, error):
        if False:
            print("[flip] オーダー組み立てで例外:", type(error).__name__, error)
            notice.line_send(
                "【flipオーダー組み立て失敗】\n"
                f"- {type(error).__name__}: {error}\n"
                "- 他の解析とループは継続する"
            )


class time_analysis():
    def __init__(self, candle_analysis_class):
        # 調査に必要な変数
        self.ca = candle_analysis_class  # CandleAnalysisインスタンスの生成
        self.basic_analysis = self.ca.require_basic_analysis()
        self.ca5 = self.ca.candle_meta_class  # peaks以外の部分。cal_move_ave関数を使う用
        self.peaks_class = self.basic_analysis.m5_peaks_class
        self.original_df_r = self.peaks_class.original_df_r

        # 注文用
        self.take_position_flag = False
        self.exe_order_classes = []

        # 変数
        self.sp = 0.004  # スプレッド考慮用
        self.base_lc_range = 1  # ここでのベースとなるLCRange
        self.base_tp_range = 1
        self.units_str = 1
        self.lc_change_test = [
            {"exe": True, "time_after": 0, "trigger": 0.01, "ensure": -1},  # ←とにかく、LCCandleを発動させたい場合
            {"exe": True, "time_after": 600, "trigger": self.ca5.cal_move_ave(2), "ensure": -0.001},
            {"exe": True, "time_after": 600, "trigger": self.ca5.cal_move_ave(4), "ensure": self.ca5.cal_move_ave(2)},
            {"exe": True, "time_after": 600, "trigger": self.ca5.cal_move_ave(5), "ensure": self.ca5.cal_move_ave(3)},
            {"exe": True, "time_after": 6000, "trigger": self.ca5.cal_move_ave(6), "ensure": self.ca5.cal_move_ave(4)},
            {"exe": True, "time_after": 600, "trigger": self.ca5.cal_move_ave(7), "ensure": self.ca5.cal_move_ave(5)},
            {"exe": True, "time_after": 600, "trigger": self.ca5.cal_move_ave(8), "ensure": self.ca5.cal_move_ave(6)},
            {"exe": True, "time_after": 600, "trigger": self.ca5.cal_move_ave(9), "ensure": self.ca5.cal_move_ave(7)},
            {"exe": True, "time_after": 600, "trigger": self.ca5.cal_move_ave(10), "ensure": self.ca5.cal_move_ave(8)},
            {"exe": True, "time_after": 600, "trigger": self.ca5.cal_move_ave(11), "ensure": self.ca5.cal_move_ave(9)},
        ]

        # 実行関数
        self.time_order()

    def add_order_and_flag_inspecion_class(self, order_class):
        """

        """
        self.take_position_flag = True
        self.exe_order_classes.append(order_class)

    def time_order(self):
        print("一番新しい時間", self.original_df_r.iloc[0]['time_jp'])
        s = self.original_df_r.iloc[0]['time_jp']
        dt = datetime.datetime.strptime(s, "%Y/%m/%d %H:%M:%S")
        hour = dt.hour
        minute = dt.minute
        if hour == 1 and minute <= 4:
            print("深夜の一時の初回です")
            order_class1 = OCreate.Order({
                "name": "深夜一時の売りオーダー",
                "current_price": self.peaks_class.current_price,
                "target": 0,  # target_price,
                "direction": -1,
                "type": "MARKET",  # "MARKET",
                "tp": self.base_tp_range,  # self.ca5.cal_move_ave(5),
                "lc": self.base_lc_range,
                "lc_change": self.lc_change_test,
                "units": self.units_str,
                "priority": 100,
                "decision_time": self.ca.decision_time.strftime(
                    "%Y/%m/%d %H:%M:%S"
                ),
                "pair": getattr(self.ca, "pair", "USD_JPY"),
                "candle_analysis_class": self.ca
            })
            self.add_order_and_flag_inspecion_class(order_class1)
