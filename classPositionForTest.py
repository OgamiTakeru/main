import datetime
from datetime import timedelta

import classOanda
import tokens as tk
import fGeneric as gene
import gc
import numpy as np
import classCandleAnalysis as ca
import os
import pandas as pd

# from test_loop import get_instances_of_class


class order_information:
    total_yen = 0  # トータルの円
    total_yen_max = 0  # これは０以上を検出したいので、float(-inf)ではNG
    total_yen_min = float('inf')
    total_PLu = 0  # PL/Unitの累計値
    total_PLu_max = 0  # これは０以上を検出したいので、float(-inf)ではNG
    total_PLu_min = float('inf')
    position_num = 0  # 何個のポジションを持ったか
    minus_yen_position_num = 0
    plus_yen_position_num = 0
    exist_alive_class = False  # 生きているクラスがあるかどうか（ある場合に限り、ローソクデータの取得を行いたいため）
    latest_df = None  # 直近の解析用のデータを持っておく（LcChangeFromCnadleで利用）
    latest_df_r = None
    latest_df_get_time = datetime.datetime.now().replace(microsecond=0) - timedelta(minutes=1)
    add_margin = 0.015  # CandleLcChangeで、余裕を見る分。初期は０だったが、マイナスを多くしても維持したい・・・！

    # history
    result_dic_arr = []

    # 連続して取らないように、最後に取得したタイミングを抑える（ただし、オーダー即取得の場合にデータが取れないと困るので、１分前を入れておく）
    # ↓直前の情報を取得しておく
    before_latest_plu = 0
    before_latest_name = ""
    # ↓直前の情報の延長で、当面の情報を維持しておく
    history_plus_minus = [0]  # 空だと、過去のプラスマイナスを参照するときおかしなことになるので０を入れておく
    history_names = ["0"]  # 上の理由と同様に数字を入れておく

    # 結果一覧送信時、その行数指定
    result_row = 7  # 過去10回分の結果を送信

    def select_oa(self, oa_mode):
        # print("SelectMode", oa_mode)
        self.oa_mode = oa_mode
        if self.is_live:
            if self.oa_mode == 1:
                # 通常アカウント
                self.oa = classOanda.Oanda(tk.accountIDl, tk.access_tokenl, tk.environmentl)
            else:
                # 両建て用アカウント
                self.oa = classOanda.Oanda(tk.accountIDl2, tk.access_tokenl, tk.environmentl)
        else:
            # デモ口座
            self.oa = classOanda.Oanda(tk.accountID, tk.access_token, tk.environment)

    def __init__(self, name, is_live, filepath):
        self.oa = classOanda.Oanda(tk.accountIDl2, tk.access_tokenl, tk.environmentl)  # 仮の値
        self.oa_mode = 2  # アカウント選択（１が通常、２が両建てアカウント） 初期値は１
        self.is_live = is_live  # 本番環境か練習か（Boolean）
        self.select_oa(self.oa_mode)  # 重要！　id_noとis_liveを基に、oaクラスを選択する
        self.name = name  #
        self.name_ymdhms = ""
        self.current_price = 0
        self.lc_change_candle_num = 100
        self.order_class = None
        self.linkage_order_classes = []
        self.linkage_done = False

        self.s = "    "
        # self.reset()
        self.ORDER_TIMEOUT_MIN_DEFAULT = 40  # 分単位で指定
        self.TRADE_TIMEOUT_MIN_DEFAULT = 600  # 分単位で指定
        # 以下リセット対象群
        self.priority = 0  # このポジションのプライオリティ（登録されるプランのプライオリティが、既登録以上の物だったら入れ替え予定）
        self.life = False  # 有効かどうか（オーダー発行からポジションクローズまでがTrue）
        self.order_permission = True
        self.waiting_order = False
        self.order_register_time = 0
        self.plan_json = {}
        self.for_api_json = {}
        # オーダー情報(オーダー発行時に基本的に上書きされる）
        self.o_json = {}
        self.o_id = 0
        self.o_time = 0
        self.o_state = ""
        self.o_time_past_sec = 0  # オーダー発行からの経過秒
        # トレード情報
        self.t_json = {}  # 最新情報は常に持っておく
        self.t_id = 0
        self.t_state = ""
        self.t_type = ""  # 結合ポジションか？　plantとinitialとcurrentのユニットの推移でわかる？
        self.t_initial_units = 0  # Planで代用可？少し意味異なる？
        self.t_current_units = 0
        self.t_time = 0
        self.t_time_past_sec = 0
        self.t_execution_price = 0  # 約定価格
        self.t_unrealize_pl = 0
        self.t_realize_pl = 0
        self.t_pl_u = 0
        self.t_close_time = 0
        self.t_close_price = 0
        self.already_offset_notice = False  # オーダーが既存のオーダーを完全相殺し、さらにポジションもある場合の通知を2回目以降やらないため
        # 経過時間管理
        self.order_timeout_min = self.ORDER_TIMEOUT_MIN_DEFAULT  # 分単位で指定
        self.trade_timeout_min = self.TRADE_TIMEOUT_MIN_DEFAULT  # 分単位で指定
        # 勝ち負け情報更新用(一つの関数を使いまわすため、辞書化する）
        self.win_lose_border_range = 0  # この値を超えている時間をWin、以下の場合Loseとする
        self.win_hold_time_sec = 0
        self.lose_hold_time_sec = 0
        self.win_max_plu = 0
        self.lose_max_plu = 0

        # ロスカット変更情報
        self.lc_change_dic_arr = []
        self.lc_change_from_candle_lc_price = 0
        self.lc_change_num = 0  # LCChangeまたはLCChangeCandleのいずれかの執行で加算される。０は未実行。１以上は執行済み。
        self.lc_change_less_minus_done = False
        self.lc_change_candle_done = False
        self.lc_change_status = ""
        self.lc_change_exe = True  # 基本的には実施する
        self.lc_change_candle_exe = True  # 基本的には実施する
        self.lc_change_candle_exe_at_minus = False  # マイナス域で、キャンドルLC＿Changeを実行する
        self.lc_change_candle_foot = "M5"

        # アラートライン設定
        self.alert_watch_exe = False
        self.alert_watch_done = False
        self.alert_range = 0
        self.alert_price = 0
        self.alert_watching = False
        self.plus_from_alert_price = 0
        self.minus_from_alert_price = 0
        self.beyond_alert_time = 0
        self.beyond_alert_time_sec = 0
        self.alert_wait_time_sec = 180
        self.alert_line_send_done = False

        # ポジション様子見用
        self.step1_filled = False
        self.step1_filled_time = 0
        self.step1_keeping_second = 0
        self.step1_filled_over_price = 0
        self.watching_out_time_border = 60  # startから、この時間経過でwatch終了＆Order終了（order終了優先）
        self.step1_keeping_time_border = 30
        self.step1_price_gap_border = 0.05
        self.watching_position_done_send_line = False
        self.watching_for_position_done = False
        self.step2_filled = False
        self.step2_keeping_second = 0
        self.step2_filled_time = 0
        self.watching_start_time_limit = 0

        # lc_Changeがおかしいので確認用
        self.no_lc_change = True
        self.first_lc_change_time = 0

        # オーダーが、オーダー情報なし、トレード情報なしとなっても、この回数分だけチェックする(時間差がありうるため）
        self.try_update_limit = 2
        self.try_update_num = 0

        # エラー対応用
        self.update_information_error_o_id = 0
        self.update_information_error_o_id_num = 0

        # 調査結果も保有する
        self.ca = None  # CandleAnalysisの格納
        self.send_line_exe = False  # いるか不明（Trueの場合は一部の情報についてLINE送信頻度増）

        # 検証用
        self.round_num = 3  # 検証用
        self.inspection_df = None  # 検証用
        self.filepath = filepath  # 検証用
        self.lc_kind = "Normal"  # 検証用
        self.test_count = 0  #テキトーに使うよう
        self.adjuster = 0  # 検証用

    def reset(self):
        # 情報の完全リセット（テンプレートに戻す）
        # print("    ●●●●OrderClassリセット●●●●")
        self.name = ""
        self.name_ymdhms = ""
        self.oa_mode = 0  # アカウント選択（１が通常、２が両建てアカウント）
        self.priority = 0  # このポジションのプライオリティ
        # self.is_live = True  # 本番環境か練習か（Boolean）　⇒する必要なし
        self.life = False
        self.waiting_order = False
        self.plan_json = {}  # plan(name,units,direction,tp_range,lc_range,type,price,order_permission,margin,order_timeout_min)
        self.for_api_json = {}
        self.order_register_time = 0
        self.order_class = None
        self.linkage_order_classes = []
        self.linkage_done = False
        # オーダー情報(オーダー発行時に基本的に上書きされる）
        self.o_id = 0
        self.o_time = 0
        self.o_state = ""
        self.o_time_past_sec = 0  # オーダー発行からの経過秒
        # トレード情報
        self.t_id = 0
        self.t_state = ""
        self.t_type = ""  # 結合ポジションか？　plantとinitialとcurrentのユニットの推移でわかる？
        self.t_initial_units = 0  # Planで代用可？少し意味異なる？
        self.t_current_units = 0
        self.t_time = 0
        self.t_time_past_sec = 0
        self.t_execution_price = 0  # 約定価格
        self.t_unrealize_pl = 0
        self.t_realize_pl = 0
        self.t_pl_u = 0
        self.t_close_time = 0
        self.t_close_price = 0
        self.already_offset_notice = False  # オーダーが既存のオーダーを完全相殺し、さらにポジションもある場合の通知を2回目以降やらないため
        # 経過時間管理
        self.order_timeout_min = 45  # 分単位で指定
        self.trade_timeout_min = 45
        # 勝ち負け情報更新用
        self.win_lose_border_range = 0  # この値を超えている時間をWin、以下の場合Loseとする
        self.win_hold_time_sec = 0
        self.lose_hold_time_sec = 0
        self.win_max_plu = 0
        self.lose_max_plu = 0

        # ロスカット変更情報
        self.lc_change_dic_arr = []  # 空を持っておくだけ
        self.lc_change_from_candle_lc_price = 0
        self.lc_change_num = 0  # LCChangeまたはLCChangeCandleのいずれかの執行でTrueに変更される
        self.lc_change_less_minus_done = False

        self.lc_change_exe = True  # 基本的には実施する
        self.lc_change_candle_exe = True  # 基本的には実施する
        self.lc_change_candle_exe_at_minus = False  # マイナス域で、キャンドルLC＿Changeを実行する
        self.lc_change_candle_done = False
        self.lc_change_candle_foot = "M5"

        # アラートライン設定
        self.alert_watch_exe = False
        self.alert_watch_done = False
        self.alert_range = 0
        self.alert_price = 0
        self.alert_watching = False
        self.plus_from_alert_price = 0
        self.minus_from_alert_price = 0
        self.beyond_alert_time = 0
        self.beyond_alert_time_sec = 0
        self.alert_wait_time_sec = 180
        self.alert_line_send_done = False

        # ポジション様子見用
        self.step1_filled = False
        self.step1_filled_time = 0
        self.step1_keeping_second = 0
        self.step1_filled_over_price = 0
        self.watching_out_time_border = 60  # startから、この時間経過でwatch終了＆Order終了（order終了優先）
        self.step1_keeping_time_border = 30
        self.step1_price_gap_border = 0.05
        self.watching_position_done_send_line = False
        self.watching_for_position_done = False
        self.step2_filled = False
        self.step2_keeping_second = 0
        self.step2_filled_time = 0
        self.watching_start_time_limit = 0

        # lc_Changeがおかしいので確認用
        self.no_lc_change = True
        self.first_lc_change_time = 0

        # オーダーが、オーダー情報なし、トレード情報なしとなっても、この回数分だけチェックする(時間差がありうるため）
        self.try_update_limit = 2
        self.try_update_num = 0

        # エラー対応用
        self.update_information_error_o_id = 0
        self.update_information_error_o_id_num = 0

        # 調査結果も保有する
        self.ca = None  # CandleAnalysisの格納

    def print_info(self):
        print("   <表示>", self.name, datetime.datetime.now().replace(microsecond=0))
        print("　 【life】", self.life)
        print("   【name】", self.name)
        print("   【order_permission】", self.order_permission)
        print("   【plan】", self.plan_json)
        print("   【order1】", self.o_id, self.o_time, self.o_state, self.o_time_past_sec)
        print("   【trade1】", self.t_id, self.t_execution_price, self.t_type, self.t_initial_units, self.t_current_units)
        print("   【trade1】", self.t_time, self.t_time_past_sec)
        print("   【trade2】", self.t_state, self.t_realize_pl, self.t_close_time, self.t_close_price)

    def print_info_short(self):
        print("   <表示>", self.name, datetime.datetime.now().replace(microsecond=0))
        print("　 【life】", self.life)
        print("   【name】", self.name)
        print("   【order1】", self.o_id, self.o_time, self.o_state, self.o_time_past_sec)
        print("   【trade1】", self.t_id, self.t_initial_units, self.t_current_units, self.t_execution_price)
        print("   【trade1】", self.t_unrealize_pl, self.t_pl_u, self.t_time_past_sec)

    def life_set(self, boo):
        self.life = boo
        if boo:
            pass
        else:
            # Life終了時（＝能動オーダークローズ、能動ポジションクローズ、市場で発生した成り行きのポジションクローズで発動）
            print(" LIFE 終了", self.name)
            # self.output_res()  # 解析用にポジション情報を収集しておく

    def count_up_position_check(self):
        """
        オーダーが謎な状態になる（Class外関数のposition_check関数で）
        時間的に、登録⇒チェックのタイミングが、単発的におかしくなっていると推定。
        従来、謎な状態を検知した時点で、LifeをFalseにしていたが、何回かposition_checkで実行する
        この関数は、外部から、そのトライの回数をポジションごとにカウントアップする物
        """
        if self.life:
            self.try_update_num = self.try_update_num + 1

    def send_line(self, *args):
        """
        元々定義していなかった。
        各メソッドからsendすると、「本番環境の場合はLINE送ってPracticeの場合に送らない」が面倒くさいので、いったんここを噛ませる
        """
        if self.is_live:  # is_liveがTrueは本番（lifeと紛らわしいが、、）
            tk.line_send(*args)
        else:
            print(" 練習用送信関数")
            # 練習用であることの接頭語の追加
            args = ("☆☆練習環境:",) + args
            if args[1] == "■■■解消:":
                # 中身を編集するため、一度リストに変換
                args_list = list(args)
                args_list[1] = "□□□解消:"  # ぱっとわかりやすいように変更
                tk.line_send(*tuple(args_list))
            elif args[1] == "■■■オーダー解消":
                # 中身を編集するため、一度リストに変換
                args_list = list(args)
                args_list[1] = "□□□解消:"  # ぱっとわかりやすいように変更
                tk.line_send(*tuple(args_list))
            else:
                tk.line_send(*args)

    def order_plan_registration(self, order_class):
        """
        【最重要】
        【最初】オーダー計画情報をクラスに登録する（保存する）。名前やCDCRO情報があれば、その登録含めて行っていく。
        :受け取る引数 planは、units,ask_bid,price,tp_range,lc_range,type,tr_range,order_timeout_min,
                order_permission(Boolean)は必須

        :OandaClass上で必要な情報
            units: 購入するユニット数。大体1万とか。
            ask_bid: 1の場合買い(Ask)、-1の場合売り(Bid) この関数内は['direction']名で扱う。(classOanda内でdirection→ask_bidに置換）
            price: 130.150のような小数点三桁で指定。（メモ：APIで渡す際は小数点３桁のStr型である必要がある。本関数内で自動変換）
                    成り行き注文であっても、LCやTPを設定する上では必要
            tp_range: 利確の幅を、0.01（1pips)単位で指定。0.06　のように指定する。指定しない場合０を渡す。負の値は正の値に変換
                      方向を持って渡される場合もあるが、一旦絶対値を取ってから計算する（＝渡される際の方向は不問）
            lc_range: ロスカの幅を、0.01(1pips)単位で指定。 0.06　のように指定する（負号を付ける必要はない）。指定しない場合０。　
            　　　　　　方向を持って渡される場合もあるが、一旦絶対値を取ってから計算する（＝渡される際の方向は不問）
            type: 下記参照
            tr_range: トレール幅を指定。0.01単位で指定。OANDAの仕様上0.05以上必須。指定しない場合は０を渡す
            remark: 今は使っていないが、引数としては残してある。何かしら文字列をテキトーに渡す。
        """
        self.reset()  # 一旦リセットする

        self.order_class = order_class
        plan = order_class.exe_order

        # ■受け取った情報を、インスタンス変数に入れていく
        self.order_register_time = datetime.datetime.now()
        # Jsonをそのまま入れるもの
        self.plan_json = plan  # 受け取ったプラン情報(そのままOrderできる状態が基本）
        self.for_api_json = plan['for_api_json']
        self.select_oa(plan['oa_mode'])

        # 検証用のアジャスター
        self.adjuster = -0.004 if self.plan_json['direction'] == 1 else 0.004  # ★検証用


        # (1)クラスの名前＋情報の整流化（オアンダクラスに合う形に）
        if hasattr(self.order_class, "linkage_order_classes"):
            self.linkage_order_classes = self.order_class.linkage_order_classes
        if 'priority' in plan:
            self.priority = plan['priority']  # プラオリティを登録する
        if 'trade_timeout_min' in plan:  # していない場合は初期値50分
            self.trade_timeout_min = plan['trade_timeout_min']
        if 'order_timeout_min' in plan:  # していない場合は初期値50分
            self.order_timeout_min = plan['order_timeout_min']
        self.name = plan['name']  # 本番用
        self.name_ymdhms = plan['name_ymdhms']
        # (2)各フラグを指定しておく
        # オーダ―パーミッションは、plan内でwatchingPrice指定なし、または０指定でパーミッションはTrue(即時取得）。
        if "watching_price" in plan:
            # 指定有
            if plan['watching_price'] == 0:
                self.order_permission = True  # 即時
            else:
                self.order_permission = False  # 待機
        else:
            # 指定なし
            self.order_permission = True
        # print("    オーダーパーミッション確認用", self.order_permission)
        # self.order_permission = plan['order_permission']  # 即時のオーダー判断に利用する

        # (4)LC_Change情報を格納する
        if "lc_change" in plan:
            self.lc_change_dic_arr = plan['lc_change']  # 辞書を丸ごと
            # おかしいのでテスト用
            if 'time_done' in self.lc_change_dic_arr[0]:
                tk.line_send("最初からLCChangeのDone時間が入っているNG classPosition.py ３３０行目付近")
        else:
            tk.line_send("lcLineミス classPosition.py ３３０行目付近")

        # (7)ポジションがある基準を超えている時間を継続する(デフォルトではコンストラクタで０が入る）
        if "win_lose_border_range" in plan:
            self.win_lose_border_range = plan['win_lose_border_range']

        # (9)アラート関係
        # {"range": 0, "time": 0}
        if "alert" in plan and "range" in plan['alert']:
            # if isinstance(plan['alert']['range'], int)
            if plan['alert']['range'] == 0:
                # 数字の場合は０のみ。
                self.alert_watch_exe = False
            else:
                self.alert_watch_exe = True
                self.alert_watching = False
                self.alert_range = plan['alert']['range']
                self.alert_price = plan['alert']['alert_price']
                # self.alert_wait_time_sec = 180
                # if self.plan['direction'] == 1:  # １の場合はドル買い（ASK）
                #     self.alert_price = self.plan['price'] - self.alert_range
                # else:
                #     self.alert_price = self.plan['price'] + self.alert_range
                # print("classPositionAlert確認")
                # print(plan['alert']['range'], self.plan['direction'], self.alert_price, self.plan['price'], self.alert_range)
        else:
            self.alert_watch_exe = False

        # (Final)オーダーを発行する
        if self.order_permission:
            # 即時オーダー発行
            order_res = self.make_order()
            if "order_result" in order_res:
                pass
            else:
                order_res['order_result'] = "この処理はオーダー失敗の可能性大"
        else:
            # オーダーをいったん待機し、ウォッチを行う
            self.life_set(True)  # ★重要　LIFEのONはここで二個目。
            self.waiting_order = True
            self.o_state = "Watching"
            order_res = {"order_name": self.name + "【未発行】", "order_id": -1, "order_result": {
                "price": self.plan_json['target_price'],
                "direction": self.plan_json['direction'],
                "units": self.plan_json['units'],
                "lc_price": self.plan_json['lc_price'],
                "lc_range": self.plan_json['lc_range'],
                "tp_price": self.plan_json['tp_price'],
                "tp_range": self.plan_json['tp_range'],
                }}  # 返り値を揃えるため、強引だが辞書型を入れておく

        return {"order_name": self.name, "order_id": order_res['order_id'], "order_result": order_res['order_result']
                , "ref": {"move_ave": round(plan['move_ave'], 3)}}

    def make_order(self):
        """
        検証用は完全オリジナル
        planを元にオーダーを発行する。この時初めてLifeがTrueになる
        :return:
        """
        # オーダー発行処理★
        # order_ans_dic = self.oa.OrderCreate_dic_exe(self.for_api_json)
        # order_ans = order_ans_dic['data']  # エラーはあんまりないから、いいわ。
        # if order_ans['cancel']:  # キャンセルされている場合は、リセットする
        #     self.send_line(" 　Order不成立（今後ループの可能性）", self.name, order_ans['order_id'])
        #     return {"order_name": "error", "order_id": 0}

        # 必要な情報を登録する
        self.o_id = 1
        self.o_time = self.plan_json['decision_time']
        self.o_state = "PENDING"
        self.o_time_past_sec = 0  # 初回は変更なし
        self.life_set(True)  # ★重要　LIFEのONはここでのみ実施
        print("    オーダー発行完了test＠make_order", self.name, )

        candleAnalysisClass = self.order_class.candle_analysis

        memory_dic = {
            "name": self.name,
            "name_ymdhms": self.name_ymdhms,
            "target_price": self.plan_json['target_price'],
            "direction": self.plan_json['direction'],
            "units": self.plan_json['units'],
            "lc_price": self.plan_json['lc_price'],
            "lc_range": self.plan_json['lc_range'],
            "tp_price": self.plan_json['tp_price'],
            "tp_range": self.plan_json['tp_range'],
            "move_ave": candleAnalysisClass.candle_class.ave_move
        }

        self.update_dataframe(memory_dic)

        return {"order_name": "", "order_id": self.o_id, "order_result": ""}

    def close_order(self):
        """
        検証用は完全オリジナル
        """
        # オーダークローズする関数 (情報のリセットは行わなず、Lifeの変更のみ）
        if not self.life:
            print("  order既にないが、CloseOrder指示あり", self.name)
            return 0  # Lifeが既にない場合は、実行無し
        self.life_set(False)  # まずはクローズ状態にする　（エラー時の反復を防ぐため。ただし毎回保存される？？）
        if self.o_state == "Watching":
            return 0

        # order_res_dic = self.oa.OrderDetails_exe(self.o_id)  # トレード情報の取得
        # if order_res_dic['error'] == 1:
        #     print("    CloseOrderError@close_order")
        #     return 0
        # order_info = order_res_dic["data"]['order']
        if self.o_state == "PENDING":  # orderがキャンセルできる状態の場合
            # res = self.oa.OrderCancel_exe(self.o_id)
            # if res['error'] == -1:
            #     print("   OrderCancelError@close_order")
            #     return 0
            # # Close処理を実施
            self.o_state = "CANCELLED"
            # self.life_set(False)  # 本当はここに欲しい
            print("    orderCancel@close_order", self.o_id)
        else:  # FIEELDとかCANCELLEDの場合は、lifeにfalseを入れておく
            print("   order無し(決済済orキャンセル済)@close_order")

    def after_close_trade_function(self):
        """
        検証専用（UpdateDataframe関数の呼び出しが随時発生）
        ポジションのクローズを検知した場合、（１）トータル価格等を更新　（２）Lineの送信　を実施する。
        ★また、カウンターオーダーの確認を行い、実施する。
        呼ばれるパターンは２種類
        ①自然のロスカット⇒クローズ状態が格納されている。
        ②強制クローズ⇒クローズ後に呼ばれるが、t_jsonの情報が書き換わっていない為、一つ古いOpen時の情報を使うことになる(いつかClose情報を使う？）
        :param trade_latest:
        :return:
        """
        trade_latest = self.t_json
        # (0)　改めてLifeを殺す
        self.life_set(False)
        # （１）計算するー累計の円や、回数等
        if trade_latest['state'] == "CLOSED":
            # Totalの円を求める
            order_information.total_yen = round(order_information.total_yen + float(trade_latest['realizedPL']), 2)
            if order_information.total_yen > order_information.total_yen_max:
                order_information.total_yen_max = order_information.total_yen  # 過去の勝ちの最大値を取得しておく(気分的に）
            elif order_information.total_yen < order_information.total_yen_min:
                order_information.total_yen_min = order_information.total_yen
            # TotalのPLuを求める
            order_information.total_PLu = round(order_information.total_PLu + trade_latest['PLu'], 3)
            if order_information.total_PLu > order_information.total_PLu_max:
                order_information.total_PLu_max = order_information.total_PLu
            elif order_information.total_PLu < order_information.total_PLu_min:
                order_information.total_PLu_min = order_information.total_PLu
            # 回数の算出　決済が完了し、realizedPLが算出されている場合。
            if float(trade_latest['realizedPL']) < 0:
                order_information.minus_yen_position_num = order_information.minus_yen_position_num + 1
            else:
                order_information.plus_yen_position_num = order_information.plus_yen_position_num + 1
        else:
            # 価格情報の更新
            order_information.total_yen = round(order_information.total_yen + float(trade_latest['unrealizedPL']), 2)
            order_information.total_PLu = round(order_information.total_PLu + trade_latest['PLu'], 3)
            # 計算する（回数）
            if float(trade_latest['unrealizedPL']) <= 0:
                order_information.minus_yen_position_num = order_information.minus_yen_position_num + 1
            elif float(trade_latest['unrealizedPL']) > 0:
                order_information.plus_yen_position_num = order_information.plus_yen_position_num + 1

        # 直前の結果を保存しておく
        order_information.before_latest_plu = trade_latest['PLu']
        order_information.before_latest_name = self.name
        order_information.history_plus_minus.append(trade_latest['PLu'])
        order_information.history_names.append(self.name)

        # （２）LINE送信
        # ①UNIT数を調整する
        # if abs(float(trade_latest['currentUnits'])) != 0 and abs(float(trade_latest['initialUnits'])) != abs(float(trade_latest['currentUnits'])):
        #     units_for_view = str(abs(float(trade_latest['currentUnits']))) + "相殺有"
        # else:
        #     units_for_view = abs(float(trade_latest['currentUnits']))
        units_for_view = abs(float(trade_latest['initialUnits'])) - abs(float(trade_latest['currentUnits']))
        # print("　　　　classPosition 540行目", float(trade_latest['initialUnits']), trade_latest['currentUnits'], self.o_json)
        direction = float(trade_latest['initialUnits']) / abs(float(trade_latest['initialUnits']))
        # ②本文作成
        if trade_latest['state'] == "CLOSED":
            # res1 = "【Unit】" + str(trade_latest['currentUnits'])
            res1 = "【Unit】" + str(units_for_view * direction)
            id_info = "【orderID】" + str(self.o_id) + "【tradeID】" + str(self.t_id)
            res2 = "【決:" + str(trade_latest['averageClosePrice']) + ", " + "取:" + str(trade_latest['price']) + "】"
            res3 = "【ポジション期間の最大/小の振れ幅】 ＋域:" + str(self.win_max_plu) + "/ー域:" + str(self.lose_max_plu)
            res3 = res3 + " 保持時間(秒)" + str(trade_latest['time_past'])
            res4 = "【今回結果】" + str(trade_latest['PLu']) + "," + str(trade_latest['realizedPL']) + "円\n"
            res5 = "【合計】計" + str(order_information.total_PLu) + ",計" + str(order_information.total_yen) + "円"
            res6 = "【合計】累積最大円:" + str(order_information.total_yen_max) + ",最小円:" + str(
                order_information.total_yen_min)
            res7 = "【合計】累計最大PL:" + str(order_information.total_PLu_max) + ",最小PL:" + str(
                order_information.total_PLu_min)
            res8 = "【回数】＋:" + str(order_information.plus_yen_position_num) + ",―:" + str(
                order_information.minus_yen_position_num)
            # 履歴の書き込み
            # print("書き込みエラー確認用")
            # print(trade_latest)
            result_dic = {
                "order_time": self.o_time,
                "res": str(trade_latest['realizedPL']),
                "res_tp_lc": self.t_json['res_tplc'],
                "take_time": self.t_time,
                "take_price": str(trade_latest['price']),
                "end_time": trade_latest['closeTime'],
                "end_price": str(trade_latest['averageClosePrice']),
                "orderID": str(self.o_id),
                "tradeID": str(self.t_id),
                "name": self.name,
                "name_only": self.name[:-5],
                "units": str(self.plan_json['units'] * direction),
                "pl_per_units": str(trade_latest['PLu']),  # 以下追加
                "lc_price_plan": self.plan_json['lc_price'],
                "lc_price_original_plan": self.plan_json['lc_price_original'],
                "tp_price": self.plan_json['tp_price'],
                "plus_minus": 1 if float(trade_latest['realizedPL']) > 0 else -1,
                "max_plus": str(self.win_max_plu),
                "max_minus": str(self.lose_max_plu),
                "position_keep_time": str(trade_latest['time_past']),
                "name_ymdhms": self.name_ymdhms,
                "tp_price_original_plan": self.plan_json['tp_price_original'],
            }
            order_information.result_dic_arr.append(result_dic)
            #
            self.update_dataframe(result_dic)
        else:
            # 強制クローズ（Open最後の情報を利用する。stateはOpenの為、averageClose等がない。）
            # res1 = "強制Close【Unit】" + str(trade_latest['currentUnits'])
            res1 = "【Unit】" + str(trade_latest['currentUnits'])  # )str(units_for_view * direction)
            id_info = "【orderID】" + str(self.o_id) + "【tradeID】" + str(self.t_id)
            res2 = "【決:" + str(self.current_price) + ", " + "取:" + str(trade_latest['price']) + "】"
            res3 = "【ポジション期間の最大/小の振れ幅】 ＋域:" + str(self.win_max_plu) + "/ー域:" + str(self.lose_max_plu)
            res3 = res3 + " 保持時間(秒)" + str(trade_latest['time_past'])
            res4 = "【今回結果】" + str(trade_latest['PLu']) + "," + str(trade_latest['unrealizedPL']) + "円\n"
            res5 = "【合計】計" + str(order_information.total_PLu) + ",計" + str(order_information.total_yen) + "円"
            res6 = "【合計】累積最大円" + str(order_information.total_yen_max) + ",最小円" + str(
                order_information.total_yen_min)
            res7 = "【合計】累計最大PL" + str(order_information.total_PLu_max) + ",最小PL" + str(
                order_information.total_PLu_min)
            res8 = "【回数】＋:" + str(order_information.plus_yen_position_num) + ",―:" + str(
                order_information.minus_yen_position_num)

            result_dic = {
                "order_time": self.o_time,
                "res": str(trade_latest['unrealizedPL']),  # 上と違う部分
                "take_time": self.t_time,
                "take_price": str(trade_latest['price']),
                "end_time": trade_latest['closeTime'],
                "end_price": str(self.current_price),  #str(trade_latest['averageClosePrice']),
                "orderID": str(self.o_id),
                "tradeID": str(self.t_id),
                "name": self.name,
                "name_only": self.name[:-5],
                "units": str(self.plan_json['units'] * direction),
                "pl_per_units": str(trade_latest['PLu']),  # 以下追加
                "lc_price_plan": self.plan_json['lc_price'],
                "lc_price_original_plan": self.plan_json['lc_price_original'],
                "tp_price": self.plan_json['tp_price'],
                "plus_minus": 1 if float(trade_latest['unrealizedPL']) > 0 else -1,
                "max_plus": str(self.win_max_plu),
                "max_minus": str(self.lose_max_plu),
                "position_keep_time": str(trade_latest['time_past']),
                "name_ymdhms": self.name_ymdhms,
                "tp_price_original_plan": self.plan_json['tp_price_original'],
            }
            order_information.result_dic_arr.append(result_dic)
            self.update_dataframe(result_dic)

        # # 共通処理
        # path = tk.folder_path + 'test.csv'
        # try:
        #     # ファイル書き込み
        #     if not os.path.exists(path):
        #         # ファイルが存在しない場合、新規作成
        #         df = pd.DataFrame(self.inspection_df)
        #         df.to_csv(path, index=False)
        #         self.inspection_df.to_csv(path, index=False)
        #     else:
        #         # ファイルが存在する場合、追記処理
        #         # df = pd.DataFrame([self.inspection_df])
        #         # df.to_csv(path, mode='a', header=False, index=False)
        #         self.inspection_df.to_csv(path, mode='a', header=False, index=False)
        #
        # except (OSError, PermissionError, IOError) as e:
        #     print(f"ファイルにアクセスできませんでした: {e}")


        # ①共通処理（ファイルへの書き込み）
        # path = tk.folder_path + 'history.csv'
        # try:
        #     # ファイル書き込み
        #     if not os.path.exists(path):
        #         # ファイルが存在しない場合、新規作成
        #         df = pd.DataFrame(order_information.result_dic_arr)
        #         df.to_csv(path, index=False)
        #     else:
        #         # ファイルが存在する場合、追記処理
        #         df = pd.DataFrame([result_dic])
        #         df.to_csv(path, mode='a', header=False, index=False)
        #
        # except (OSError, PermissionError, IOError) as e:
        #     print(f"ファイルにアクセスできませんでした: {e}")
        #
        # # ②集計値の送信(一覧）
        # temp = pd.read_csv(path)
        # df_part = temp.tail(order_information.result_row)
        # lines = []
        # a_sum = sum(int(x) for x in df_part['res'])
        # max_width = max(len(str(int(x))) for x in df_part['res'])
        # for _, row in df_part.iterrows():
        #     # res_val = int(row['res']) if isinstance(row['res'], (int, float)) else row['res']
        #     res_val = f"{int(row['res']):>{max_width}}"
        #     uni_val = int(row['units'] / abs(row['units']))
        #     hh_mm = ":".join(gene.str_to_time_hms(row['end_time']).split(":")[:2])
        #     if uni_val == 1:
        #         uni_str = "L"  # 買い（ドルを）
        #     else:
        #         uni_str = "S"  # 売り
        #     line = f"{res_val}, {uni_str}, {hh_mm}, {row['name_only'][:13]}, "
        #     lines.append(line)
        # # 改行で結合
        # lines.append(f"{a_sum:>{max_width}}")
        # output_str = "\n".join(lines)
        # tk.line_send("■■■:", "\n", output_str)
        #
        # # ③ピボット結果の送信
        # temp = pd.read_csv(path)
        # df_part = temp.tail(order_information.result_row)
        # summary = df_part.groupby("name_only").agg(
        #     res_sum=("res", lambda x: int(x.sum())),
        #     negative_count=("res", lambda x: (x < 0).sum()),
        #     positive_count=("res", lambda x: (x > 0).sum())
        # ).reset_index()
        # lines = []
        # for _, row in summary.iterrows():
        #     name_val = f"{row['name_only'][:13]:<13}"
        #     line = f"{name_val}, {row['res_sum']}, {row['positive_count']}, {row['negative_count']}"
        #     lines.append(line)
        # pivot_str = "\n".join(lines)
        # print(pivot_str)
        # tk.line_send("■■■:", "\n", pivot_str)

    def update_dataframe(self, new_data_dic):
        """
        検証専用
        """
        path = self.filepath
        # ファイル処理
        if os.path.exists(path):
            # あれば中身のデータフレーム
            original_df = pd.read_csv(path)
        else:
            # 無ければ空のデータフレーム
            original_df = pd.DataFrame()

        # 最初はNoneならDataFrameを新規作成
        if original_df.empty:
            # 初回の空の場合
            original_df = pd.DataFrame([new_data_dic])
        else:
            name = new_data_dic.get("name_ymdhms")
            if name is None:
                raise ValueError("new_data に 'name_ymdhms' キーが必要です。")

            # name が既に存在するかチェック
            mask = original_df["name_ymdhms"] == name

            # 既存のnameがある場合 → 横方向に更新
            if mask.any():
                idx = original_df.index[mask][0]
                for key, value in new_data_dic.items():
                    if key in original_df.columns:
                        col_dtype = original_df[key].dtype

                        # 数値列に文字列などが来たらキャスト
                        if pd.api.types.is_numeric_dtype(col_dtype):
                            try:
                                value = float(value)
                            except ValueError:
                                value = np.nan
                    original_df.loc[idx, key] = value
            else:
                # 既存のnameがない場合 → 新しい行として追加
                original_df = pd.concat([original_df, pd.DataFrame([new_data_dic])], ignore_index=True)


        try:
            # ファイル書き込み
            if not os.path.exists(path):
                # ファイルが存在しない場合、新規作成
                # df = pd.DataFrame(self.inspection_df)
                # df.to_csv(path, index=False)
                original_df.to_csv(path, index=False, encoding="utf-8")
            else:
                # ファイルが存在する場合、追記処理
                # df = pd.DataFrame([self.inspection_df])
                # df.to_csv(path, mode='a', header=False, index=False)
                # self.inspection_df.to_csv(path, mode='a', header=False, index=False)  # 追加モード
                original_df.to_csv(path, index=False, encoding="utf-8")  # 追加モード

        except (OSError, PermissionError, IOError) as e:
            print(f"ファイルにアクセスできませんでした: {e}")

        return original_df

    def close_trade(self, units):
        # ポジションをクローズする関数 (情報のリセットは行わなず、Lifeの変更のみ）
        # クローズ後は、AfterCloseFunctionに移行し、情報の送信等を行う
        if not self.life:
            print("    position既にないが、Close関数呼び出しあり", self.name)
            return 0

        # 全ポジション解除の場合
        if units is None:
            self.life_set(False)  # LIFEフラグの変更は、APIがエラーでも実行する
            self.t_state = "CLOSED"

            # close_res = self.oa.TradeClose_exe(self.t_id, None)  # ★クローズを実行
            # if close_res['error'] == -1:  # APIエラーの場合終了。ただし、
            #     self.send_line("  ★ポジション解消ミスNone＠close_position", self.name, self.t_id, self.t_pl_u)
            #     return 0
            # self.send_line("  ポジション解消指示", self.name, self.t_id, self.t_pl_u)
            self.after_close_trade_function()

        # 部分解除の場合（LINE送信無し）
        # else:
        #     if float(units) > abs(float(self.t_current_units)):
        #         # 部分解消が失敗しそうなオーダーになっている場合
        #         self.send_line("    指定されたCloseUnits大（Error)⇒全解除, units", ">", abs(float(self.t_current_units)))
        #         self.life_set(False)  # ★大事　全解除の場合、APIがエラーでもLIFEフラグは取り下げる
        #         self.t_state = "CLOSED"
        #         close_res = self.oa.TradeClose_exe(self.t_id, None)  # ★オーダーを実行
        #         return 0
        #     else:
        #         # 部分解消が正常に実行できる注文数の場合
        #         close_res = self.oa.TradeClose_exe(self.t_id, {"units": units})  # ★オーダーを実行
        #         self.send_line('部分解消')
        #     if close_res['error'] == -1:  # APIエラーの場合終了。ただし、
        #         self.send_line("  ★ポジション解消ミス部分＠close_position", self.name, self.t_id, self.t_pl_u)
        #         return 0
        #     res_json = close_res['data_json']  # jsonデータを取得
        #     tradeID = res_json['orderFillTransaction']['tradeReduced']['tradeID']
        #     units = res_json['orderFillTransaction']['tradeReduced']['units']
        #     realizedPL = res_json['orderFillTransaction']['tradeReduced']['realizedPL']
        #     price = res_json['orderFillTransaction']['tradeReduced']['price']
        #     self.send_line("  ポジション部分解消", self.name, self.t_id, self.t_pl_u, "UNITS", units, "PL", realizedPL,
        #                    "price", price)
        """
        検証専用
        """

    def updateWinLoseTime(self, new_pl):
        """
        最新の勝ち負け情報（PLu)を渡される。
        :param new_pl:
        :return:
        """
        # (1)pip情報の推移を記録する(プラス域維持時間とマイナス維持時間を求める）
        if new_pl >= self.win_lose_border_range:  # 今回プラス域である場合
            self.lose_hold_time_sec = 0  # Lose継続時間は必ず０に初期化（すでに０の場合もあるけれど）
            if self.t_pl_u <= 0:  # 前回がマイナスだった場合
                self.win_hold_time_sec = 0  # ０を入れるだけ（Win計測スタート地点）
            else:
                # 前回もプラスの場合
                self.win_hold_time_sec += 2  # 前回もプラスの場合、継続時間をプラスする（実行スパンが２秒ごとの為＋２）
        elif new_pl < self.win_lose_border_range:  # 今回マイナス域である場合
            self.win_hold_time_sec = 0  # Win継続時間は必ず０に初期化
            if self.t_pl_u >= 0:  # 前回がマイナスだった場合
                self.lose_hold_time_sec = 0  # ０を入れるだけ（Lose計測スタート地点）
            else:
                self.lose_hold_time_sec += 2  # 前回もマイナスの場合、継続時間をプラスする（実行スパンが２秒ごとの為＋２）

        # (2)プラスマイナスの最大値情報を取得しておく
        if self.lose_max_plu > self.t_pl_u:  # 最小値更新時
            self.lose_max_plu = self.t_pl_u
        if self.win_max_plu < self.t_pl_u:  # 最大値更新時
            self.win_max_plu = self.t_pl_u

    def detect_change(self, target_5s_row):
        """
        検証専用
        """
        """
        update_informationでへんかを検知した場合これが　呼ばれる。
        :return:
        """
        order_latest = self.o_json
        trade_latest = self.t_json
        # print("    detect_change関数")
        # print("    ", order_latest)
        # print("    ", trade_latest)
        if (self.o_state == "PENDING" or self.o_state == "") and order_latest['state'] == 'FILLED':  # オーダー達成（Pending⇒Filled）
            if trade_latest['state'] == 'OPEN':  # ポジション所持状態
                # self.send_line("    (取得)", self.name, trade_latest['price'])
                print(" 取得", self.name, target_5s_row['time_jp'])
                #  取得時には、ローソクデータも取得しておく
                # now = datetime.datetime.now().replace(microsecond=0)
                # time_difference = now - self.latest_df_get_time  # 最後にDFを取った時からの経過時間
                # seconds_difference = abs(time_difference.total_seconds())
                # if seconds_difference >= 30:
                #     # 初回の場合はやる
                #     self.is_first_time_lc_change_candle = False  # 二回目以降はFalseにFalseを入れることになるが、、
                #
                #     d5_df = self.oa.InstrumentsCandles_multi_exe("USD_JPY", {"granularity": "M5", "count": self.lc_change_candle_num},
                #                                                  1)  # 時間昇順(直近が最後尾）
                #     if d5_df['error'] == -1:
                #         print("error Candle")
                #         return -1
                #     else:
                #         self.latest_df = d5_df['data']
                #         if self.is_first_time_lc_change_candle:
                #             # 初回の場合は、取得したことにしない（５分ごとの時間が一番欲しいから）
                #             self.is_first_time_lc_change_candle = False
                #         else:
                #             self.latest_df_get_time = datetime.datetime.now().replace(microsecond=0)
                        # print("LCChange用にDFを取得しました(取得時）", self.latest_df_get_time)
                        # print(self.latest_df)
                        # print("1行のみ抽出（取得時）")
                        # print(self.latest_df.iloc)
                        # print(" 置換対象のLC価格を持つ足データ（取得時）", self.latest_df.iloc[-2]['time_jp'])
                # else:
                #     print("前回取得時（取得時）", self.latest_df_get_time, "経過秒", seconds_difference)
                #     pass

            # if "position_state" in trade_latest:
            #     if trade_latest['position_state'] == 'CLOSED':  # ポジションクローズ（ポジション取得とほぼ同時にクローズ[異常]）
            #         self.send_line("    (即時)クローズ")
            # else:
            #     pass
            #     # print("    NOT GOOD Ref")

        elif self.t_state == "OPEN" and trade_latest['state'] == "CLOSED":  # 通常の成り行きのクローズ時
            print("    成り行きのクローズ発生")
            self.after_close_trade_function()
            return 0

    def order_update_and_close(self):
        """
        検証専用　（UpdateDataFrame）
        """
        order_latest = self.o_json
        # 情報の更新
        # print(" オーダー情報の上書き", self.o_state, " ⇒", order_latest['state'])
        self.o_state = order_latest['state']  # ここで初めて更新
        self.o_time_past_sec = order_latest['time_past']
        # オーダーのクローズを検討する
        if order_latest['state'] == "PENDING":
            # print("    時間的な解消を検討", self.o_time_past, self.o_state, "基準", self.order_timeout_min * 60)
            if self.o_time_past_sec > self.order_timeout_min * 60 and (self.o_state == "" or self.o_state == "PENDING"):
                self.close_order()
                temp_dic = {
                    "name": self.name,
                    "name_ymdhms": self.name_ymdhms,
                    "order_cancel": True,
                    "order_keep_time": self.o_time_past_sec
                }
                self.inspection_df = self.update_dataframe(temp_dic)
                # self.send_line("   オーダー解消(時間)@", self.name, self.o_time_past_sec, ",", self.order_timeout_min
                #                , position_check_no_args()['name_list'])
        if order_latest['state'] == "CANCELLED":
            self.close_order()

    def trade_update_and_close(self):
        dependence_win_max_plu_max = 0.05
        dependence_t_pl_u_max = 0.03
        trade_latest = self.t_json  # とりあえず入れ替え（update関数で取得した最新の情報）
        # print("こっちでも", trade_latest)
        # トレード情報の更新
        self.t_id = trade_latest['id']  # 既に１度入れているけど、念のため
        self.t_state = trade_latest['state']  # Openとかそういう物
        self.t_initial_units = trade_latest['initialUnits']  # 初回だけでよい？
        self.t_current_units = trade_latest['currentUnits']
        # self.t_time = trade_latest['openTime']  # 初回だけでよい？
        self.t_time_past_sec = trade_latest['time_past']
        self.t_execution_price = trade_latest['price']  # 初回だけでよい？
        if trade_latest['state'] == "OPEN":
            self.t_unrealize_pl = trade_latest['unrealizedPL']
        elif trade_latest['state'] == "CLOSED":
            self.t_realize_pl = trade_latest['realizedPL']
            self.close_trade(None)
        self.t_pl_u = trade_latest['PLu']

        # クローズの場合はクローズ処理を実施
        if trade_latest['state'] == "CLOSED":
            if self.life:
                # Lifeがある場合は、確実に消しに行く
                print(" ポジションがクローズなので消しに行く（classPosition 480行目)")
                self.close_trade(None)

        # tradeのクローズを検討する
        # if trade_latest['state'] == "OPEN":
        #     # 規定時間を過ぎ、マイナス継続時間も１分程度ある場合は、もう強制ロスカットにする
        #     if self.t_time_past_sec > self.trade_timeout_min * 60 and self.lose_hold_time_sec > 60:
        #         self.send_line("   Trade解消(マイナス×時間)@", self.name, "PastTime", self.t_time_past_sec, ",LoseHold",
        #                        self.lose_hold_time_sec
        #                        , position_check_no_args()['name_list'])
        #         self.close_trade(None)

        # if trade_latest['state'] == "OPEN":
        #     # 規定時間を過ぎ、大きくプラスもなくふらふらしている場合
        #     if self.t_time_past_sec > self.trade_timeout_min * 60:  # 時間が経過している
        #         if self.win_max_plu <= dependence_win_max_plu_max and self.t_pl_u <= dependence_t_pl_u_max:
        #             self.send_line("   Trade解消(微プラス膠着)@", self.name, "PastTime", self.t_time_past_sec,
        #                            ",LoseHold",
        #                            self.win_max_plu, self.t_pl_u)
        #             self.close_trade(None)

    def is_in_range(self, range_row, target_price):
        """
        検証専用
        """
        if range_row['low'] + self.adjuster < target_price < range_row['high'] + self.adjuster:
            return True
        else:
            return False

    def update_information(self, target_5s_row, candle_analysis_class):  # orderとpositionを両方更新する
        """
        検証専用
        """
        """
        直近の5秒足のデータを取得する
        order "PENDING" "CANCELLED" "FILLED"
        position "OPEN" "CLOSED"
        :return:
        """
        print("  UpdateInformation", self.name)
        if not self.life:
            return 0  # LifeがFalse（＝オーダーが発行されていない状態）では実行しない

        # [分岐]初期にオーダー確定しない場合は、life=Trueだがオーダー等がない。
        if self.waiting_order:
            self.watching_for_position()
            return 0

        # (0)現在価格の取得
        self.current_price = target_5s_row['open']

        o_gap_time = gene.cal_str_time_gap(self.o_time, target_5s_row['time_jp'])
        o_gap_time_abs = o_gap_time['gap_abs']

        # 今の価格から、直近の状態を取得する
        print("   オーダーの調査", self.name)
        if self.o_state == "PENDING":
            print("    オーダーがpending時の判定")
            if self.is_in_range(target_5s_row, self.plan_json['target_price']) or self.plan_json['type'] == "MARKET":
                print("     取得要件の達成", self.name, self.o_state)
                self.o_json = {
                    "state": "FILLED",
                    "id": 1,
                    "time_past": o_gap_time_abs
                }
                self.t_json = {
                    "state": "OPEN",
                    "id": 2,
                    "time_past": 0,  # 取得したてとみて０
                }
                # self.o_state = "FILLED"
                self.t_time = target_5s_row['time_jp']
            else:
                print("     取得要件達成せず")
                self.o_json = {
                    "state": "PENDING",
                    "id": 11,
                    "time_past": o_gap_time_abs
                }
        else:
            print("    取得済みのため、経過時間を更新", self.name)
            self.o_json = {
                "state": "FILLED",
                "id": 11,
                "time_past": o_gap_time_abs
            }

        # (1) OrderDetail,TradeDetailの取得（orderId,tradeIdの確保）
        if self.o_id == -1:
            # 実行時に、既存のオーダーを拾ってきた場合、特殊な操作。
            # trade_ans = self.oa.TradeDetails_exe(self.t_id)  # ■■API
            # if trade_ans['error'] == 1:
            #     print("    トレード情報取得Error＠update_information", self.t_id)
            #     return 0
            # trade_latest = trade_ans['data']['trade']  # Jsonデータの取得
            # self.t_json = trade_latest  # Json自体も格納
            pass
        else:
            self.update_information_error_o_id_num = 0
            print("   ポジションの調査", self.name, self.o_state, self.t_state, self.o_json['state'])
            if self.o_json['state'] == "FILLED":
                # 基本情報の計算
                t_gap_time = gene.cal_str_time_gap(self.t_time, target_5s_row['time_jp'])
                t_gap_time_abs = t_gap_time['gap_abs']
                d = self.plan_json['direction']  # TPやLCの計算で利用する、ポジションの向き、１が買い
                print("    ポジションありのため、TPLC判断",  target_5s_row['time_jp'], self.name, self.t_time)
                print("     LC判定", target_5s_row['low'], self.plan_json['lc_price'], target_5s_row['high'])
                print("     TP判定", target_5s_row['low'], self.plan_json['tp_price'], target_5s_row['high'])
                #  オーダーが約定済みの場合、LC,TPに該当しているかを探索
                if self.is_in_range(target_5s_row, self.plan_json['lc_price']):
                    print("    ロスカットします", target_5s_row['time_jp'], self.plan_json['lc_price'])
                    plu = round((self.plan_json['lc_price'] - self.plan_json['target_price']) * d, self.round_num)
                    pl = round(plu * abs(self.plan_json['units']), self.round_num)
                    self.t_json = {
                        "state": "CLOSED",
                        "id": 29,
                        "initialUnits": self.plan_json['for_api_json']['order']['units'],
                        "currentUnits": self.plan_json['for_api_json']['order']['units'],
                        "averageClosePrice": self.plan_json['lc_price'],
                        "openTime": self.t_time,
                        "closeTime": target_5s_row['time_jp'],
                        "price": self.plan_json['target_price'],
                        "time_past": t_gap_time_abs,
                        "realizedPL": pl,
                        "PLu": plu,
                        "res_tplc": self.lc_kind
                    }
                elif self.is_in_range(target_5s_row, self.plan_json['tp_price']):
                    print("    利確します", target_5s_row['time_jp'], self.plan_json['tp_price'])
                    plu = round((self.plan_json['tp_price'] - self.plan_json['target_price']) * d, self.round_num)
                    pl = round(plu * abs(self.plan_json['units']), self.round_num)
                    self.t_json = {
                        "state": "CLOSED",
                        "id": 28,
                        "initialUnits": self.plan_json['for_api_json']['order']['units'],
                        "currentUnits": self.plan_json['for_api_json']['order']['units'],
                        "averageClosePrice": self.plan_json['tp_price'],
                        "openTime": self.t_time,
                        "closeTime": target_5s_row['time_jp'],
                        "price": self.plan_json['target_price'],
                        "time_past": t_gap_time_abs,
                        "realizedPL": pl,
                        "PLu": plu,
                        "res_tplc": "TP"
                    }
                else:
                    # 何もない場合は、PastTimeのカウントを実施
                    plu = round((self.plan_json['target_price'] - target_5s_row['mid_outer']) * d * -1, self.round_num)
                    pl = round(plu * abs(self.plan_json['units']), self.round_num)
                    print("    ポジション継続", self.name, " 継続時間", t_gap_time_abs, ",PL:", pl, "PLu", plu, "     ", target_5s_row['time_jp'], self.t_time)
                    self.t_json = {
                        "state": "OPEN",
                        "id": 2,
                        "initialUnits": self.plan_json['for_api_json']['order']['units'],
                        "currentUnits": self.plan_json['for_api_json']['order']['units'],
                        "averageClosePrice": self.plan_json['tp_price'],  # 追加
                        "openTime": self.t_time,
                        "closeTime": target_5s_row['time_jp'],  # 追加
                        "price": self.plan_json['target_price'],
                        "time_past": t_gap_time_abs,
                        "unrealizedPL": pl,  # 途中では出せない
                        "realizedPL": pl,  # 追加
                        "PLu": plu,
                        "res_tplc": "継続(途中クローズの可能性)"
                    }

            else:
                # オーダーがペンディングの場合(tradeはない状態)
                print("   オーダーペンディング中（", self.t_id, target_5s_row['time_jp'], self.name, self.o_time)
                self.t_id = 0
                # tradeが０の場合、オーダーの更新のみ行う。
                self.order_update_and_close()
                return 0

            # if target_5s_row['time_jp'] == "2025/10/03 00:05:00":
            #     e.print("")

        # (2) 【以下トレードありが前提】変化点を確認する order_update,trade_update yori mae niarukoto
        self.detect_change(target_5s_row)

        # (3)情報をUpdate and Closeする
        self.order_update_and_close()
        self.trade_update_and_close()
        if self.o_state == "FILLED" and self.t_state == "CLOSED" and self.life:
            self.life_set(True)
            # self.send_line("Filled Closed Trueの謎状態あり⇒強制的にLifeにFalseを入れて終了　classPosition 537行目")
        # 変化による情報（勝ち負けの各最大値、継続時間等の取得）
        self.updateWinLoseTime(self.t_json['PLu'])  # PLU(realizePL / Unit)の推移を記録する
        # ひっかけるようjなマイナス値を検出し、早期のロスカットを行う
        # self.lc_change_less_minus()
        # LCの変更を検討する(プラス域にいった場合のTP底上げ≒トレールに近い）
        self.lc_change()
        if self.lc_change_num != 0:
            # LC_Changeが執行されている場合は、Candleも有効にする
            pass
            self.lc_change_from_candle(candle_analysis_class)

        # # アラート
        # if self.alert_watch_exe:
        #     self.watching_for_alert()

    def watching_for_position_make_order(self):
        """
        watching for position から呼ばれる、オーダー発行関数
        """
        # オーダー発行
        order_res = self.make_order()
        self.waiting_order = False  # 超大事
        self.watching_for_position_done = True
        self.o_state = "PENDING"  # あらかじめ入れておく（オーダーと同時に入る可能性が高く、その場合、(取得)メールが来ないため）
        line_send = "　"
        if "order_result" in order_res:
            o_trans = order_res['order_result']['json']['orderCreateTransaction']
            line_send = line_send + "◆ Watchingオーダー発行【" + str(self.name) + "】,\n" + \
                        "指定価格:【" + str(self.plan_json['target_price']) + "】" + \
                        ", 数量:" + str(o_trans['units']) + \
                        ", TP:" + str(o_trans['takeProfitOnFill']['price']) + \
                        "(" + str(round(abs(float(o_trans['takeProfitOnFill']['price']) - float(self.plan_json['target_price'])),
                                        3)) + ")" + \
                        ", LC:" + str(o_trans['stopLossOnFill']['price']) + \
                        "(" + str(
                round(abs(float(o_trans['stopLossOnFill']['price']) - float(self.plan_json['target_price'])),
                      3)) + ")" + \
                        ", OrderID:" + str(order_res['order_id']) + \
                        ", Alert:" + str(self.alert_range) + \
                        "(" + str(round(self.alert_price, 3)) + ")" + \
                        ", 取得価格:" + str(
                order_res['order_result']['execution_price']) + ",\n"
            # tk.line_send(line_send)
        else:
            order_res['order_result'] = "この処理はオーダー失敗の可能性大"

        return {"order_name": self.name, "order_id": order_res['order_id'],
                "name_ymdhms": self.name_ymdhms, "order_result": order_res['order_result']}

    def watching_for_position(self):
        """
        規定価格を●秒間越えていら、正式にオーダーが発行される仕組み.
        一瞬だけひっかけるような動きでのロスを防止したい。特に、「順張りを目指す場合」
        すでにPlanがorder_registorにて登録されている状態が必要
        ★逆張りは向いていないかも・・？（タッチがうれしいから）
        """
        # print("   新機構のテスト", self.o_state)
        if self.o_state != "Watching" or self.watching_for_position_done:  # 足数×〇分足×秒
            # 実行しない条件は、既に実行済み　または、NotOpen
            return 0

        # ■【共通処理】現在価格等の更新
        now_time = datetime.datetime.now()
        o_dir = self.plan_json['direction']
        if o_dir == 1:
            # 買いの場合　askプライス
            now_price = self.oa.NowPrice_exe("USD_JPY")['data']['ask']
        else:
            # 売りの場合　bidプライス
            now_price = self.oa.NowPrice_exe("USD_JPY")['data']['bid']
        # 必要情報の取得
        temp_price = self.plan_json['target_price']

        # ■■順張りの場合
        # 目的：「一瞬だけエントリーポイントを越えて、すぐ下がる」を防ぎたい。
        # 方法：　エントリーポイントを10秒間越えている、あるいは、越えてるPipsが大きい場合に、オーダーを発行する。
        # ポイント：
        #  オーダー発行時、順張り基準を既に越えている場合がある。⇒これはそのままでオーダー＆即ポジになる？
        #   越えているPipsが大きい場合、LCをエントリーポイントにするのもあり、、か？
        #   勢いがない場合、越えている状態で、逆張りに切り替えてオーダーを発行するのもあり・・？（逃げ越しすぎ？）
        if self.plan_json['type'] == "STOP":
            if (round(self.step1_keeping_second, 0) % 15 == 0 and round(self.step1_keeping_second, 0) != 0) or 1 <= round(self.step1_keeping_second, 0) <= 2:
                pass
                # print(" ウォッチング内容（STOP）", self.step1_filled, "発行時:", gene.time_to_str(self.step1_filled_time),
                #       round(self.step1_filled_over_price, 3), "円",
                #       round(self.step1_keeping_second, 0),
                #       "bordertime", self.step1_keeping_time_border,
                #       "ウォッチ開始時間(0は無効中）", self.step1_filled_time)

            # ■タイムアウトの計算
            # ⓪経過時間の算出
            delta = datetime.datetime.now() - self.order_register_time
            gap_seconds_from_order_regist = delta.total_seconds()  # オーダー登録時からの経過時間を算出
            if isinstance(self.step1_filled_time, int):
                # self.watching_start_timeがint(ようするに０）の場合は、ウォッチ状態ではない
                gap_seconds_from_start_watching = 0
            else:
                # intではない場合⇒ようするに時刻の場合
                delta = datetime.datetime.now() - self.step1_filled_time
                gap_seconds_from_start_watching = delta.total_seconds()  # ウォッチ開始からの経過時間を算出
            # ①終了処置
            if gap_seconds_from_order_regist > self.order_timeout_min * 60:
                # オーダーの時間がタイムアウトしている場合
                if gap_seconds_from_start_watching > self.watching_out_time_border or gap_seconds_from_start_watching == 0:
                    # ウォッチの時間も経過している場合
                    # print("オーダー/ウォッチタイムアウト(またはgap_seconds_from_start_watchingが０でウォッチ状態ではない)",
                    #       self.order_register_time, "から", self.order_timeout_min ,"分経過,", gap_seconds_from_start_watching)
                    self.close_order()
                    # tk.line_send("ウォンチングのみのオーダーを解消", self.name)
                    return 0
                else:
                    # ウォッチの時間は時間内、または０ではなないため、このまま継続
                    pass

            # ■基準を越えたかの判定（STOPオーダーとLIMITオーダーで異なる）
            if not self.step1_filled:
                # トリガーの判定
                # 順張りの場合、瞬間的な越えを防ぎたい。少しの間越え続けている場合は、早めに順張り入れたい(下は変更予定）
                if o_dir == 1 and now_price > temp_price:
                    self.step1_filled = True
                    self.step1_filled_time = now_time
                    self.step1_filled_over_price = now_price - temp_price
                    # print("買い方向の順張りで、越えている　⇒取得可能状態")
                if o_dir == -1 and now_price < temp_price:
                    self.step1_filled = True
                    self.step1_filled_time = now_time
                    self.step1_filled_over_price = temp_price - now_price
                    # print("売り方向の順張りで、下回っている　⇒取得可能状態")
            else:
                # 越えている状態で情報の更新を進める
                if o_dir == 1 and now_price < temp_price:
                    self.step1_filled = False
                    self.step1_filled_time = now_time
                    self.step1_filled_over_price = 0
                    # print("買い方向の順張りで、下回っている　⇒解除")
                if o_dir == -1 and now_price > temp_price:
                    self.step1_filled = False
                    self.step1_filled_time = now_time
                    self.step1_filled_over_price = 0
                    # print("売り方向の順張りで、上回っている　⇒解除")

            # ■改めてウォッチモードに入るかを確認
            if not self.step1_filled:
                return 0

            # ■ここからウォッチモードの処理
            # ■経過時間（越えてからの経過時間)
            delta = now_time - self.step1_filled_time
            self.step1_keeping_second = delta.total_seconds()

            # ■判定
            exe_order = False  # exeorderのほうが適した名前？
            # 越えている状態で情報の更新を進める
            # 順張りの場合、瞬間的な越えを防ぎたい。少しの間越え続けている場合は、早めに順張り入れたい(下は変更予定）
            # ■時間（価格越具合）判定
            if self.step1_keeping_second >= self.step1_keeping_time_border:
                # 時間が長時間取得可能状態で過ぎている場合
                exe_order = True
            else:
                # 時間的には過ぎていない場合
                if self.step1_filled_over_price >= self.step1_price_gap_border:
                    # 価格がそこそこオーバーしていたら、取得しに行く（でかい動き？）
                    exe_order = True
            # ■状態通知用
            if not self.watching_position_done_send_line:
                # tk.line_send("初回のポジションウォッチング状態(STOP):", self.name)
                self.watching_position_done_send_line = True
            # ■実行
            if exe_order:
                self.step1_filled = False  # これ、ここで初期化する必要あり？
                self.watching_for_position_make_order()

        # ■■逆張りの場合(越えれば越えるほどよくない）
        elif self.plan_json['type'] == "LIMIT":
            # ■表示用
            if (round(self.step1_keeping_second, 0) % 15 == 0 and round(self.step1_keeping_second, 0) != 0) or 1 <= round(
                    self.step1_keeping_second, 0) <= 2:
                print_flag = True
            else:
                print_flag = False

            if print_flag:
                pass
                # print("    ウォッチング内容（LIMIT）", self.step1_filled, "発行時:",
                #       gene.time_to_str(self.step1_filled_time),
                #       round(self.step1_filled_over_price, 3), "円",
                #       round(self.step1_keeping_second, 0),
                #       "bordertime", self.step1_keeping_time_border,
                #       "ウォッチ開始時間(0は無効中）", self.step1_filled_time)

            # ■タイムアウトの計算
            # ⓪経過時間の算出
            delta = datetime.datetime.now() - self.order_register_time
            gap_seconds_from_order_regist = delta.total_seconds()  # オーダー登録時からの経過時間を算出
            # ウォッチ状態かを確認する（ウォッチ状態の場合、ウォッチ開始からの時間を算出）
            if isinstance(self.step1_filled_time, int):
                # self.watching_start_timeがint(ようするに０）の場合は、ウォッチ状態ではない
                gap_seconds_from_start_watching = 0
            else:
                # intではない場合⇒ようするに時刻の場合
                delta = datetime.datetime.now() - self.step1_filled_time
                gap_seconds_from_start_watching = delta.total_seconds()  # ウォッチ開始からの経過時間を算出
            # ①終了処置
            if gap_seconds_from_order_regist > self.order_timeout_min * 60:
                # オーダーの時間がタイムアウトしている場合
                if gap_seconds_from_start_watching > self.watching_out_time_border or gap_seconds_from_start_watching == 0:
                    # ウォッチの時間も経過している場合
                    # print(
                    #     "オーダー/ウォッチタイムアウト(またはgap_seconds_from_start_watchingが０でウォッチ状態ではない)",
                    #     self.order_register_time, "から", self.order_timeout_min, "分経過,",
                    #     gap_seconds_from_start_watching)
                    self.close_order()
                    # tk.line_send("ウォンチングのみのオーダーを解消", self.name)
                    return 0
                else:
                    # ウォッチの時間は時間内、または０ではなないため、このまま継続
                    pass

            # 方向性：逆張りの場合、突破し続ける状況を防ぎたい。一瞬突破して、元戻り続ける場合は、早めに取りたい
            # ■STEP1を満たしたかの確認（最初に指定ラインを通過したかどうか）
            if self.step2_filled:
                # step1はstep2が成立していない場合のみ実施
                pass
            else:
                # STEP1の判定処理
                if self.step1_filled:
                    # step1が成立した状態（越えている時間を算出する）
                    delta = now_time - self.step1_filled_time
                    self.step1_keeping_second = delta.total_seconds()

                    # step2への以降があるかを検討（５秒間連続で逆方向伸び状態を維持したのち、LIMIT方向に戻った場合）
                    if self.step1_keeping_second >= 10:
                        # 10秒以上Step1を維持している状態（step2への移行トリガーを探る）
                        if (o_dir == 1 and now_price > temp_price) or (o_dir == -1 and now_price < temp_price):
                            self.step2_filled = True  # step2はここでしかTrueにならない
                            self.step2_filled_time = now_time
                            # print("  STEP2初回成立　（一度越えて、戻ってきている状態）", now_time, "step1継続時間", self.step1_keeping_second)
                        else:
                            # これが深い場合、長い場合等は　色々オーダー価格かえたりしたいねぇ。
                            pass
                            # print("  STEP1の条件は達成　STEP2のトリガー待機中 これが深い場合、今まで負けてたやつ", self.step1_keeping_second)
                    else:
                        # step1を10秒以上経過していないため、STEP2以降の確認せず、経過待ち。
                        print("  STEP1 時間経過待ち", now_time, self.step1_keeping_second)
                        if (o_dir == 1 and now_price > temp_price) or (o_dir == -1 and now_price < temp_price):
                            self.step1_filled = False
                            # print("  　　STEP1中。価格が下回ったため、微妙（もう一度ステップ１の成立からやり直し）")

                else:
                    # 初回（step1不成立状態で、成立状態に移行したかを判定する）
                    if o_dir == 1 and now_price < temp_price:
                        self.step1_filled = True
                        self.step1_filled_time = now_time
                        self.step1_filled_over_price = temp_price - now_price
                        # print("　STEP1初回成立　買い方向の逆張りで、初めて下回った　⇒逆方向伸び状態", now_time)
                        # tk.line_send("LIMIT step1達成（買い逆）", self.name)
                    if o_dir == -1 and now_price > temp_price:
                        self.step1_filled = True
                        self.step1_filled_time = now_time
                        self.step1_filled_over_price = now_price - temp_price
                        # print("　STEP1初回成立　売り方向の逆張りで、初めて上回っている　⇒逆方向伸び状態", now_time)
                        # tk.line_send("LIMIT　step1達成（売り逆）", self.name)

            # ■Step2(一度ボーダーをオーダーと逆方向に越えた後、オーダーしたい方向に戻ってきている)の状況を確認
            order_exe = False
            if self.step2_filled:
                # step2が成立している場合、Step2を越えている時間を計測。オーダーに移行する。
                # 状況確認（経過時間）
                delta = now_time - self.step2_filled_time
                self.step2_keeping_second = delta.total_seconds()
                # 状況確認（ボーダーを越価格。152円時点で、150でLimit買い入れた場合、149⇒151となり、150買いを発行するかどうか）
                if o_dir == 1:
                    gap_price = now_price - temp_price  # +値でオーダー可。マイナスでstep1状態に逆戻り
                else:
                    gap_price = temp_price - now_price  # +値でオーダー可。マイナスでstep1状態に逆戻り

                # 判定
                # print("  ステップ２状況", self.step2_keeping_second, now_price, gap_price, now_time)
                if self.step2_keeping_second >= 20:
                    # step2の状態を10秒以上経過している(step2の条件はクリア）
                    if gap_price >= 0:
                        # step2の状態を10秒以上経過、かつ、価格も満足している場合オーダーを発行する（逆に発行遅いくらい・・・？）
                        order_exe = True  # オーダーexeはここでしかTrueにならない。
                        # print(" STEP２　オーダー執行可能に", self.step1_filled, self.step1_keeping_second, self.step2_filled,
                        #       self.step2_keeping_second, gap_price, now_time)
                    else:
                        # step1からやり直してほしい(最後の最後で価格が下回ってしまたような状態)
                        # print("  STEP2　最後の最後で価格が下回った", self.step1_filled, self.step1_keeping_second, self.step2_filled,
                        #       self.step2_keeping_second, gap_price)
                        self.step1_filled = False
                        self.step2_filled = False
                        return 0
                else:
                    # step2の状態が10秒以下の場合（待ち）
                    if gap_price < 0:
                        # 価格を満たさなくなった場合、Step1からやり直し
                        # print("  Step2の時間を満たす前に解除（STEP１へ）", self.step2_keeping_second, now_price, gap_price, now_time)
                        self.step1_filled = False
                        self.step2_filled = False
                        return 0
            #
            #
            # else:
            #     # step2が成立していない場合、何もしない
            #     pass
            #
            #     #     # self.keeping_second_limitは、規定越えの後、逆方向（理想方向）に進み始めて何秒か、を意味する
            #     #     #　１０秒逆に突破した後、初めて理想方向に進んだ時間を取得
            #     #     if self.step2_filled:
            #     #         # このフラグがOnでないと、時刻が入っていない
            #     #         delta = now_time - self.watching_start_time_limit
            #     #         self.step2_keeping_second = delta.total_seconds()
            #     #     else:
            #     #         # 初回、self.beyond_watching_trigger_limitがオフの状態で、条件を満たす（＝初回）
            #     #         if (o_dir == 1 and now_price > temp_price) or (o_dir == -1 and now_price < temp_price):
            #     #             print("初回　逆方向１０秒後、理想方向に生き始めた")
            #     #             delta = now_time - self.watching_start_time_limit
            #     #             self.step2_keeping_second = delta.total_seconds()
            #     #             self.step2_filled = True
            #     #         else:
            #     #             self.step2_keeping_second = 0
            #     #
            #     #     # 実判定処理
            #     #     if o_dir == 1:
            #     #         if now_price > temp_price:
            #     #             if self.step2_keeping_second >= 10:
            #     #                 # 10秒以上、いい状態をキープしている場合
            #     #                 self.step2_filled = True
            #     #                 self.watching_start_time_limit = now_time
            #     #                 self.step1_filled_over_price = 0
            #     #             else:
            #     #                 # いい状態の１０秒経過待ち
            #     #                 if print_flag:
            #     #                     print("買い方向の逆張りで、下回った後に、上回った　⇒いい状態(１０秒待ち)",
            #     #                           self.step2_filled, self.step2_keeping_second)
            #     #         else:
            #     #             if print_flag:
            #     #                 print("買い方向の逆張りで、下回った後、その状態を維持（突破し続けているためNG）")
            #     #     if o_dir == -1:
            #     #         if now_price < temp_price:
            #     #             if self.step2_keeping_second >= 10:
            #     #                 # 10秒以上、いい状態をキープしている場合
            #     #                 self.step2_filled = True
            #     #                 self.watching_start_time_limit = now_time
            #     #                 self.step1_filled_over_price = 0
            #     #             else:
            #     #                 if print_flag:
            #     #                     print("売り方向の逆張りで、上回った後に、下回っている　⇒いい状態(10秒待ち)",
            #     #                           self.step2_filled, self.step2_keeping_second)
            #     #         else:
            #     #             if print_flag:
            #     #                 print("売り方向の逆張りで、上回った後に、その状態を維持（突破し続けているためNG）")
            #     # else:
            #     #     print("逆方向への伸びが一瞬すぎる（また越えるのでは？なので待機）", self.step1_keeping_second, self.step1_filled)

            # ■改めてウォッチモードに入るかを確認
            # Falseの場合は当然不可。さらに、Trueであっても５秒異常経過していない場合は、不可
            # LIMITオーダー発行
            if order_exe:
                pass
            else:
                return 0

            # ■LIMIT用オーダー発行処理
            print(" LIMITオーダー　ウォッチ状態完了", self.step1_keeping_second, )
            self.step1_filled = False  # これ、ここで初期化する必要あり？
            self.step2_filled = False  # これ、ここで初期化する必要あり？
            self.watching_for_position_make_order()

    def lc_change(self):  # ポジションのLC底上げを実施 (基本的にはUpdateで平行してする形が多いかと）
        """
        検証専用
        """
        """
        ロスカット底上げを実施する。セルフとレールに近い
        lc_change_dicは配列で、lc_change_dicはPlanと同時にクラスに渡される。
        lc_change_dic =[{"exe": True, "trigger": 0.03, "ensure": 0.1}]
        なお、LCの変更が執行されると、"done":Trueが付与される
        実行後
        [{"exe": True, "trigger": 0.03, "ensure": 0.1” ,"done": False}]
        上記の辞書が、配列で渡される場合、配列全てで確認していく。
        :return:         print(" ロスカ変更関数", self.lc_change_dic, self.t_pl_u,self.t_state)
        """
        # print("   LC＿Change実行関数", self.name, self.t_pl_u, self.t_time_past_sec, len(self.lc_change_dic_arr), self.t_state, self.lc_change_from_candle_lc_price)
        if len(self.lc_change_dic_arr) == 0 or self.t_state != "OPEN":  # 足数×〇分足×秒
            # 指定がない場合、ポジションがない場合、ポジションの経過時間が短い場合は実行しない
            return 0

        if self.lc_change_from_candle_lc_price != 0:
            # print("既にキャンドルｌｃ変更有のため、通常ｌｃ無し", self.lc_change_from_candle_lc_price)
            pass

        if self.lc_change_exe:
            pass
        else:
            return 0

        if self.lc_change_candle_done:  # 既にキャンドルLCChangeに行った場合は、執行しない
            return 0

        status_res = "   LCCHANGE_status" + self.name + ": "
        for i, item in enumerate(self.lc_change_dic_arr):
            # コードの１行を短くするため、置きかておく
            lc_exe = item['exe']
            lc_ensure_range = item['ensure']
            lc_trigger_range = item['trigger']
            lc_change_waiting_time_sec = item['time_after']
            if "time_till" in item:
                # 指定の時間まで実行
                lc_change_till_sec = item['time_till']
            else:
                lc_change_till_sec = 100000  #

            # このループで実行しない場合（フラグオフの場合、DoneがTrueの場合^
            # if not lc_exe or 'done' in item or self.t_time_past_sec < lc_change_waiting_time_sec:
            if not lc_exe:  # or self.t_time_past_sec > lc_change_till_sec:
                # エクゼフラグがFalse、または、done(この項目は実行した時にのみ作成される)が存在している場合、「実行しない」
                status_res = status_res + gene.str_merge("[", i, "] 指定なし",  "lc_exe:", lc_exe, lc_change_waiting_time_sec, ","
                                           , "現pl" + str(self.t_pl_u), ",指定Trigger", lc_trigger_range)
                continue
            elif 'done' in item:  # or self.t_time_past_sec > lc_change_till_sec:
                # エクゼフラグがFalse、または、done(この項目は実行した時にのみ作成される)が存在している場合、「実行しない」
                status_res = status_res + gene.str_merge("[", i, "] 済", item['time_done'], "lc_exe:", lc_exe, lc_change_waiting_time_sec, ","
                                           , "現pl" + str(self.t_pl_u), ",指定Trigger", lc_trigger_range)
                # lc_Changeがおかしいので確認用(初回のLCChange確認なのに、0番目（最初が０とは限らないけど、、）に済がある場合はおかしい
                diff_seconds = datetime.datetime.now() - item['time_done']
                seconds = diff_seconds.total_seconds()
                # 2時間 = 7200 秒以上離れているか判定
                # if seconds >= 2 * 60 * 60 and self.no_lc_change:
                #     tk.line_send("LC_CHANGEがうまく発動しない可能性あり[", i, "]過去実行時間,", item['time_done'], self.name,
                #                  self.first_lc_change_time, self.no_lc_change, "1519行目cPosi")
                #     gene.print_arr(self.lc_change_dic_arr)
                #     self.no_lc_change = False  # 念のため
                # else:
                #     pass
                #     # print("  　LCChange　確認用(おかしくない）　最初のLC時刻", self.first_lc_change_time, i)
                #
                # if i == 0 and self.no_lc_change:
                #     tk.line_send("LC_CHANGEがうまく発動しない可能性あり", i, "過去実行時間,", item['time_done'])
                #     gene.print_arr(self.lc_change_dic_arr)
                #     self.no_lc_change = False  # 念のため
                continue
            # elif lc_change_till_sec < self.t_time_past_sec < lc_change_waiting_time_sec:  # ←この条件の時、一番プラスがピークだったけれども。。。。
            elif self.t_time_past_sec < lc_change_waiting_time_sec or self.t_time_past_sec > lc_change_till_sec:
                # エクゼフラグがFalse、または、done(この項目は実行した時にのみ作成される)が存在している場合、「実行しない」
                status_res = status_res + gene.str_merge("[", i, "] 時間未達",  "lc_exe:", lc_exe,
                                                         "時間", lc_change_waiting_time_sec, "～", lc_change_till_sec,
                                                         "現pl" + str(self.t_pl_u), ",指定Trigger", lc_trigger_range,
                                                         "対象時間", self.t_time_past_sec)
                continue
            else:
                status_res = status_res + gene.str_merge("[", i, "] 未,lc_exe:", lc_exe, lc_change_waiting_time_sec, ","
                                           , "現pl" + str(self.t_pl_u), ",指定Trigger", lc_trigger_range)

            # ボーダーラインを超えた場合
            if self.t_pl_u >= lc_trigger_range:
                # print("　★変更確定")
                self.no_lc_change = False
                self.first_lc_change_time = datetime.datetime.now()
                print(" 　　変更対象", i, "番目のLC_Change", lc_ensure_range, lc_trigger_range, self.t_pl_u)
                self.lc_change_num = self.lc_change_num + 1  # このクラス自体にLCChangeを実行した後をつけておく（カウント）
                # これで配列の中の辞書って変更できるっけ？？
                item['done'] = True
                item['time_done'] = datetime.datetime.now()
                new_lc_price = round(float(self.t_execution_price) + (lc_ensure_range * self.plan_json['direction']), 3)
                self.lc_kind = "LC_Change" + str(i)
                # data = {"stopLoss": {"price": str(new_lc_price), "timeInForce": "GTC"}, }
                # res = self.oa.TradeCRCDO_exe(self.t_id, data)  # LCライン変更の実行
                # if res['error'] == -1:
                #     self.send_line("    LC変更ミス＠lc_change")
                #     return 0  # APIエラー時は終了
                # item['lc_change_exe'] = False  # 実行後はFalseする（１回のみ）
                # # ★注意　self.plan["lc_price"]は更新しない！（元の価格をもとに、決めているため）⇒いや、変えてもいい・・？
                # if self.send_line_exe:
                #     self.send_line("　(LC底上げ)", self.name, self.t_pl_u, round(self.plan_json['lc_price'], 3), "⇒", new_lc_price,
                #                    "Border:", round(lc_trigger_range, 3), "保証", round(lc_ensure_range, 3), "Posiprice",
                #                    self.t_execution_price,
                #                    "予定価格", round(self.plan_json['target_price'], 3))
                # LC Priceの入れ替え
                self.plan_json['lc_price'] = new_lc_price
                break
        self.lc_change_status = status_res

    def lc_change_from_candle(self, candle_analysis_class):  # ポジションのLC底上げを実施 (基本的にはUpdateで平行してする形が多いかと）
        """
        検証専用
        """
        """
        ロスカット底上げを実施する。セルフとレールに近い
        ひとつ前のローソクの最高値や最低値までをLC底上げする関数。
        最新のローソクを取得する必要がある。この関数自体は２秒に１回呼び出されるが、
        ローソクを取得するのは、５分に１回のみで問題ないため、メインと同じコードを書くことになるが、それで対応する。
        主な発動条件は、
        　・LCChangeを一回でも実行
        　または
        　・現価格を含むピークのカウントが３以上。（最初の300秒以上経過と重複してる）
        　　　かつ
        　・現価格を含むピークの方向と、ポジションが同じ方向
        の場合。
        ⇒LCChangeは、LCChangeを実行してなくてもLinkageなどで強制的にフラグを立てさせられる場合有
        """
        # print("  ★LC＿ChangeFromCandle実行関数", self.name, self.t_state, self.lc_change_candle_exe)
        if self.t_state != "OPEN" or self.t_time_past_sec < 30:  # 足数×〇分足×秒
            # ポジションがない場合、所持時間が短い場合は実行しない
            # print("       lc_change_candleの実行無", self.t_state, self.t_pl_u, self.t_time_past_sec)
            return 0
        else:
            # print("       lc_change_candleの実行あり", self.t_state, self.t_pl_u, self.t_time_past_sec)
            pass

        if self.lc_change_candle_exe:
            pass
        else:
            # lc_Change_Candle実行フラグない場合はやらない
            return 0

        print("★★★★", self.order_class.lc_change_candle_type)
        if self.order_class.lc_change_candle_type == "M5":
            print("       5分足でのCandleLcChange")
            peaks_class = candle_analysis_class.peaks_class  # peaks_classだけを抽出
            peaks = peaks_class.peaks_original
            df_r = candle_analysis_class.d5_df_r[:5]
        elif self.order_class.lc_change_candle_type == "H1":
            print("       1時間足でのCandleLcChange")
            peaks_class = candle_analysis_class.peaks_class_hour  # peaks_classだけを抽出
            peaks = peaks_class.peaks_original
            df_r = candle_analysis_class.d60_df_r[:5]
        else:
            return 0
            # print("       (その他）5分足でのCandleLcChange")
            # candle_ana = candle_analysis_class
            # peaks_class = candle_ana.peaks_class  # peaks_classだけを抽出
            # df_r = peaks_class.df_r_original[:5]


        # 逆張り注文の際、self.latest_df.iloc[-2]['low']基準だとおかしいくなる。
        # peakを算出し、peaks[0]がカウント２以上ある場合のみ、self.latest_df.iloc[-2]['low']を参照するケースに変更(25/5/17)
        # peaks = peaks_class.peaks_original
        # print("CANDLE:" ,self.name)
        # print("CANDLE LC:", self.latest_df.iloc[-2]['low'])
        # print("CANDLE LC::", peaks[0]['latest_time_jp'], peaks[0]['count'])

        # print("test表示")
        # print(self.latest_df.head(3))
        print("確認用", self.name)
        print(df_r.iloc[1]['time_jp'], df_r.iloc[1]['low'])
        print(df_r.iloc[1]['time_jp'], df_r.iloc[1]['high'])
        print(peaks[0])
        # 直近のピークが3カウント以上の場合、かつ、ポジションと同じ方向（利益が増える方向）時に実行（ひとつ前のキャンドルを参照するため）
        if peaks[0]['count'] >= 3 and peaks[0]['direction'] == self.plan_json['direction']:
            # self.latest_df.iloc[-2]['low']の-2が選択できる状態であれば、実行する
            if self.plan_json['direction'] > 0:
                # 買い方向の場合、ひとつ前のローソクのLowの値をLC価格に
                lc_price_temp = float(df_r.iloc[1]['low']) - order_information.add_margin  # 本番用は並び替え前のため[-2]
            else:
                # 売り方向の場合、ひとつ前のローソクのHighの値をLC価格に
                lc_price_temp = float(df_r.iloc[1]['high']) + order_information.add_margin  # 本番用は並び替え前のため[-2]
            print("LCcandleChangeにて、直近peakカウント:", peaks[0]['count'], "変更基準ローソク時間:", df_r.iloc[1]['time_jp'])
        else:
            # self.latest_df.iloc[-2]['low']は逆張りの時におかしくなる
            print("LCcandleChange中断　直近peakカウント:", peaks[0]['count'], "間違えたローソク時間:", df_r.iloc[1]['time_jp'])
            return -1

        if self.lc_change_from_candle_lc_price == lc_price_temp:
            print(" 既にこの価格のLCとなっているため、変更処理は実施せず")
            return 0

        # ポジション取得から５分経過、かつ、temp_lc_priceがマイナス域でなく、利益が1pips以上確約できる場合、LCをlc_price_tempに移動する
        take_position_price = float(self.t_json['price'])
        lc_ensure_range = abs(take_position_price - lc_price_temp)
        if lc_ensure_range <= 0.01:
            # print(" 確保できる利益幅が0.01以下のため、変更なし")
            return 0

        # マイナス域の場合は、処理しない
        if self.plan_json['direction'] > 0 and lc_price_temp < take_position_price:
            # 買い方向で、ターゲットよりLCtempが小さい価格の場合（lctempがマイナス域の場合)
            # print("   LCChangeCnadle", self.plan['direction'], lc_price_temp , "<",take_position_price )
            print("lc_priceにしたい価格", lc_price_temp ,"　が取得価格", take_position_price, "より小さいためプラス確保のLCにならずNG")
            return 0
        elif self.plan_json['direction'] < 0 and lc_price_temp > take_position_price:
            # 売り方向で、ターゲットよりLCtempが大きい価格の場合（lctempがマイナス域の場合)
            # print("   LCChangeCnadle", self.plan_json['direction'], lc_price_temp , ">",take_position_price )
            print("lc_priceにしたい価格", lc_price_temp, "　が取得価格", take_position_price, "より大きいためプラス確保のLCにならずNG")
            return 0

        # レンジ換算の時、大きすぎないかを確認
        if lc_ensure_range >= 0.08:
            print("range換算で大きすぎる・・・？", lc_ensure_range)

        # LCチェンジ執行
        self.lc_change_candle_done = True  # このクラス自体にLCChangeを実行した後をつけておく（各LCChange条件ではなく）
        new_lc_price = round(lc_price_temp, 3)
        # data = {"stopLoss": {"price": str(new_lc_price), "timeInForce": "GTC"}, }
        # res = self.oa.TradeCRCDO_exe(self.t_id, data)  # LCライン変更の実行
        # if res['error'] == -1:
        #     self.send_line("    LC変更ミス＠lc_change")
        #     return 0  # APIエラー時は終了
        self.lc_change_from_candle_lc_price = lc_price_temp  # ロスカット価格の保存
        lc_range = round(abs(float(lc_price_temp) - float(self.t_execution_price)), 5)
        self.lc_change_num = self.lc_change_num + 1  # このクラス自体にLCChangeを実行した後をつけておく（カウント）
        self.lc_kind = "LC_Change_candle"

        print(gene.str_merge("　(LCCandle底上げ)", self.name, "現在のPL", self.t_pl_u, "新LC価格⇒", new_lc_price,
                             "保証", lc_range, "約定価格", self.t_execution_price,
                             "予定価格", self.plan_json['target_price']))
        # if self.send_line_exe:
        #     self.send_line("　(LCCandle底上げ)", self.name, "現在のPL", self.t_pl_u, "新LC価格⇒", new_lc_price,
        #                    "保証", lc_range, "約定価格", self.t_execution_price,
        #                    "予定価格", self.plan_json['target_price'])
        # print(lc_price_temp, "＜", take_position_price )
        # print("■■■■LCCHANGE_candle", self.name, new_lc_price)
        # if self.name == "中途半端⇒レンジ_23:35":
        #     if self.test_count == 0:
        #         te.print("")
        #     else:
        #         self.test_count = self.test_count + 1

        # LC Priceの入れ替え
        self.plan_json['lc_price'] = new_lc_price

    def tuning_by_history_break(self):
        """
        検討中
        呼びもとで過去１回分の結果を参照し、それが大きなLCだった場合は、この関数を呼ぶ。
        この関数は、リスクをとってそのLCと同額をTPとする。
        """

        tp_up_border_minus = -0.045  # これ以上のマイナスの場合、取り返しに行く。
        # 過去の履歴を確認する
        if len(order_information.history_plus_minus) == 1:
            # 過去の履歴が一つだけの場合
            latest_plu = order_information.history_plus_minus[-1]
            # print("  直近の勝敗pips", latest_plu, "詳細(直近1つ)", order_information.history_plus_minus[-1])
        else:
            # 過去の履歴が二つ以上の場合、直近の二つの合計で判断する
            latest_plu = order_information.history_plus_minus[-1] + order_information.history_plus_minus[-2]  # 変数化(短縮用)
            # print("  直近の勝敗pips", latest_plu, "詳細(直近)", order_information.history_plus_minus[-1],
            #       order_information.history_plus_minus[-2])
        # 最大でも現実的な10pips程度のTPに収める
        # if abs(latest_plu) >= 0.01:
        #     latest_plu = 0.01

        # 値を調整する
        # print("tuning @ classPosition1283, ", latest_plu, "<=", tp_up_border_minus)
        if latest_plu == 0:
            print("  初回(本番)かAnalysisでのTP調整執行⇒特に何もしない（TPの設定等は行う）")
            # 通常環境の場合
            is_previous_lose = False
            tp_range = 0.5
            lc_change_type = 3
        else:
            if latest_plu <= tp_up_border_minus:
                is_previous_lose = True
                print("  ★マイナスが大きいため、取り返し調整（TPを短縮し、確実なプラスを狙いに行く）", latest_plu * 0.8)
                # tp_range = tp_up_border_minus  # とりあえずそこそこをTPにする場合
                tp_range = abs(latest_plu * 0.8)  # 負け分をそのままTPにする場合
                lc_change_type = 4  # LCchangeの設定なし
                # tk.line_send("取り返し調整発生")
            else:
                # 直近がプラスの場合プラスの場合、普通。
                print("  ★前回プラスのため、通常TP設定")
                is_previous_lose = False
                tp_range = 0.5
                lc_change_type = 3  # LCchangeの設定なし

        return {"is_previous_lose": is_previous_lose,
                "tuned_tp_range": tp_range,
                "tuned_lc_change_type": lc_change_type}

    def catch_exist_position(self, name, oa_mode, priority, json):
        """
        検証には不要
        """
        """
        既存のポジションを、登録する
        """
        print("既存のポジションあり⇒")
        print(json)
        if "takeProfitOrder" in json:
            tp_price = json['takeProfitOrder']['price']
        else:
            tp_price = 0

        if "stopLossOrder" in json:
            lc_price = json['stopLossOrder']['price']
        else:
            lc_price = 0

        price = json['price']

        self.plan_json['target_price'] = float(price)
        self.plan_json['tp_price'] = float(tp_price)
        self.plan_json['lc_price'] = float(lc_price)
        self.plan_json['lc_price_original'] = float(lc_price)
        self.plan_json['direction'] = int(json['currentUnits']) / abs(int(json['currentUnits']))
        self.plan_json['units'] = json['currentUnits']
        self.plan_json['type'] = "Already"

        self.life = True
        self.name = name + "_" + str(gene.delYearDay(datetime.datetime.now().strftime("%Y/%m/%d %H:%M:%S")))
        self.oa_mode = 2  # アカウント選択（１が通常、２が両建てアカウント）
        self.priority = 5  # このポジションのプライオリティ

        self.waiting_order = False
        self.order_register_time = 0
        # オーダー情報(オーダー発行時に基本的に上書きされる）
        self.o_id = -1  # ★大事な代入
        self.o_time = datetime.datetime.now().strftime("%Y/%m/%d %H:%M:%S")
        self.o_state = ""
        self.o_time_past_sec = 0
        self.o_json['state'] = "FILLED"
        self.o_json['time_past'] = 0
        # トレード情報
        self.t_id = json['id']  # ★大事な代入
        self.t_state = ""  # ★大事な代入
        self.t_type = ""  # 結合ポジションか？　plantとinitialとcurrentのユニットの推移でわかる？
        self.t_initial_units = 0  # Planで代用可？少し意味異なる？
        self.t_current_units = 0
        self.t_time = 0
        self.t_time_past_sec = 0
        self.t_execution_price = 0  # 約定価格
        self.t_unrealize_pl = 0
        self.t_realize_pl = 0
        self.t_pl_u = 0
        self.t_close_time = 0
        self.t_close_price = 0
        self.already_offset_notice = False  # オーダーが既存のオーダーを完全相殺し、さらにポジションもある場合の通知を2回目以降やらないため
        # 経過時間管理
        self.order_timeout_min = self.ORDER_TIMEOUT_MIN_DEFAULT  # 分単位で指定
        self.trade_timeout_min = self.TRADE_TIMEOUT_MIN_DEFAULT
        # 勝ち負け情報更新用
        self.win_lose_border_range = 0  # この値を超えている時間をWin、以下の場合Loseとする
        self.win_hold_time_sec = 0
        self.lose_hold_time_sec = 0
        self.win_max_plu = 0
        self.lose_max_plu = 0

        # ロスカット変更情報
        self.lc_change_dic_arr = []  # 空を持っておくだけ
        self.lc_change_from_candle_lc_price = 0
        self.lc_change_num = 0  # LCChangeまたはLCChangeCandleのいずれかの執行でTrueに変更される
        self.lc_change_less_minus_done = False

        min10 = 0  # 60 * 10
        self.lc_change_dic_arr = [
            # {"exe": True, "time_after": min10, "trigger": 0.01, "ensure": 0.001},
            # {"exe": True, "time_after": min10, "trigger": 0.025, "ensure": 0.01},
            # {"exe": True, "time_after": 600, "trigger": 0.04, "ensure": 0.004},  # -0.02が強い
            # {"exe": True, "time_after": 600, "trigger": first_trigger, "ensure": first_ensure},
            {"exe": True, "time_after": min10, "trigger": 0.05, "ensure": 0.012},
            {"exe": True, "time_after": min10, "trigger": 0.08, "ensure": 0.044},
            {"exe": True, "time_after": min10, "trigger": 0.20, "ensure": 0.15},
            {"exe": True, "time_after": 600, "trigger": 0.40, "ensure": 0.35},
            {"exe": True, "time_after": 2 * 5 * 60, "trigger": 0.60, "ensure": 0.55},
            {"exe": True, "time_after": 2 * 5 * 60, "trigger": 0.70, "ensure": 0.65},
            {"exe": True, "time_after": 2 * 5 * 60, "trigger": 0.80, "ensure": 0.75},
            {"exe": True, "time_after": 2 * 5 * 60, "trigger": 0.90, "ensure": 0.85},
            {"exe": True, "time_after": 2 * 5 * 60, "trigger": 1.00, "ensure": 0.95},
        ]

    def linkage_done_func(self):
        self.linkage_done = True

    def linkage_lc_change(self, new_lc_price):
        """
        検証専用
        """
        """
        リンケージからのみの利用（リンケージフラグの取り下げあり）
        """

        # data = {"stopLoss": {"price": str(new_lc_price), "timeInForce": "GTC"}, }
        # res = self.oa.TradeCRCDO_exe(self.t_id, data)  # LCライン変更の実行
        # if res['error'] == -1:
        #     self.send_line("    LC変更ミス＠lc_change")
        #     return 0  # APIエラー時は終了
        # self.linkage_done_func()
        # if self.send_line_exe:
        #     self.send_line("　(LinkageLC上げ)", self.name, self.t_pl_u, round(self.plan_json['lc_price'], 3),
        #                    "⇒", new_lc_price,
        #                    self.t_execution_price,
        #                    "予定価格", round(self.plan_json['target_price'], 3))
        # LC Priceの入れ替え
        self.lc_kind = "Linkage" + self.lc_kind
        self.plan_json['lc_price'] = new_lc_price

    def linkage_tp_change(self, new_tp_price):
        """
        検証専用
        """
        """
        リンケージからのみの利用（リンケージフラグの取り下げあり）
        """
        # data = {"takeProfit": {"price": str(new_tp_price), "timeInForce": "GTC"}, }
        # res = self.oa.TradeCRCDO_exe(self.t_id, data)  # LCライン変更の実行
        # if res['error'] == -1:
        #     self.send_line("    TP変更ミス＠lc_change")
        #     return 0  # APIエラー時は終了
        # self.linkage_done_func()
        # if self.send_line_exe:
        #     self.send_line("　(LinkageTP上げ)", self.name, self.t_pl_u, round(self.plan_json['TP_price'], 3),
        #                    "⇒", new_tp_price,
        #                    self.t_execution_price,
        #                    "予定価格", round(self.plan_json['target_price'], 3))
        # LC Priceの入れ替え
        self.plan_json['tp_price_after'] = new_tp_price

    def linkage_forced_lc_change_setting(self, main_plu, pl_u):
        """
        強制的にLCChange実行したフラグ（これによりlc_Change_Candleに移行可能に）を立て、
        さらに、CandleLcChangeを実行したフラグ（これによりlc_changeを実行しなくなる）
        """
        # LC_Change_Candleにいきなり入る場合はここをコメントイン
        # self.lc_change_num = 1  # 回数が０以外の場合、LCCHANGE　CANDLEを実行するため
        # self.lc_change_candle_done = True
        # self.send_line("　(Linkage 強制CandleLcChangeへ)", self.name)

        # LC_Changeを再執行するにはこちらから
        # 執行のフラグの準備
        self.lc_change_num = 0  #
        self.lc_change_exe = True
        self.lc_change_from_candle_lc_price = 0  # キャンドル変更済の場合０以外。０にすることで、LcChangeに戻す
        self.lc_change_candle_done = False  # キャンドル変更がTrueの場合通常lc_Changeは実行されないため、戻す
        # 執行内容の準備
        if main_plu < 0:
            print("　　想定と異なるLinkageLcChange（メイン側マイナス終了）")
            return 0
        else:
            pass
        # メインのプラスを生かす。（メインプラスの半分まで戻ったら、メインプラスプラマイゼロ。
        tr = main_plu * -1  # 想定されているのはマイナス域で、どれだけマイナスを減らすか。

        self.lc_change_dic_arr = [
            {"exe": True, "time_after": 0, "trigger": round(tr / 2, 3), "ensure": round(tr, 3)},  # 負けの半分まで行ったら、、
            {"exe": True, "time_after": 0, "trigger": round(tr / 3, 3), "ensure": round((tr / 3) * 2, 3)},
        ]

def position_check_no_args():
    """
    引数を取らないバージョンのポジションチェック（試作中）
    クラスのリストはガベージコレクションで拾ってくる  + \
                            position_check_no_args()['name_list']
    W、ターン未遂以外のオーダーが存在するかを確認する.
    :param :
    :return:
    """
    # 存在するOrderInformationのクラスのインスタンス達を検索する
    classes = [obj for obj in gc.get_objects() if isinstance(obj, order_information)]

    # 実処理
    open_positions = []
    not_open_positions = []
    max_priority_order = 0
    max_priority_position = 0
    max_position_time_sec = 0
    max_order_time_sec = 0
    watching_list = []
    open_class_names = closed_class_names = pending_class_names = ""
    total_pl = 0
    for item in classes:
        if item.life:  #lifeがTrueの場合、ポジションかオーダーが存在
            # 各情報
            if item.o_state == "Watching":
                watching_list.append({"name": item.name,
                                      "target": item.plan_json['target_price'],
                                      "direction": item.plan_json['direction'],
                                      "order_time": gene.time_to_str(item.order_register_time),
                                      "state": item.step1_filled,
                                      "keeping": round(item.step1_keeping_second, 0),
                                      })
            if item.t_state == "OPEN":
                # ポジションがある場合、ポジションの情報を取得する
                # プライオリティも最高値を取得
                if item.priority > max_priority_position:
                    max_priority_position = item.priority  # ポジションの有る最大のプライオリティを取得する
                open_positions.append({
                    "name": item.name,
                    "life": item.life,
                    "priority": item.priority,
                    "o_state": item.o_state,
                    "t_state": item.t_state,
                    "pl": item.t_pl_u,
                    "direction": item.plan_json['direction']
                })
                # ポジションの所有時間（ポジションがある中で最大）も取得しておく
                if item.t_time_past_sec > max_position_time_sec:
                    max_position_time_sec = item.t_time_past_sec  # 何分間持たれているポジションか
                # トータルの含み損益を表示する
                total_pl = total_pl + float(item.t_unrealize_pl)
                # オーダー時間リストを作る（表示用）
                open_class_names = open_class_names + "," + gene.delYearDay(item.o_time) + "(oa" + str(item.oa_mode) + ")"
                # print("  ポジション状態", item.t_id, ",PL:", total_pl)
            elif item.o_state == "PENDING":
                # オーダーのみ（取得俟ちの場合）取得まち用の配列に入れておく
                # プライオリティも最高値を取得
                if item.priority > max_priority_order:
                    max_priority_order = item.priority  # ポジションの有る最大のプライオリティを取得する

                not_open_positions.append({
                    "name": item.name,
                    "life": item.life,
                    "priority": item.priority,
                    "o_state": item.o_state,
                    "t_state": item.t_state,
                    "pl": item.t_pl_u,
                    "direction": item.plan_json['direction']
                })
                # ポジションの所有時間（ポジションがある中で最大）も取得しておく
                if item.o_time_past_sec > max_order_time_sec:
                    max_order_time_sec = item.o_time_past_sec  # 何分間オーダー待ちか
                # オーダー時間リストを作成する（表示用）
                pending_class_names = pending_class_names + "," + gene.delYearDay(item.o_time) + "(oa" + str(item.oa_mode) + ")"
            else:
                # どうやらt_stateが入っていない状態（オーダーエラーや謎の状態）
                if item.o_state == "Watching":
                    # tk.line_send("ウォッチング中のオーダーあり　（５分毎処理）")
                    continue
                print(" 謎の状態　t_state=", item.t_state, ",o_state=", item.o_state, ", 名前:", item.name, ",life=",
                      item.life, ",try_num", item.try_update_num)
                # tk.line_send(" 謎の状態(分岐前）　t_state=", item.t_state, ",o_state=", item.o_state, ", 名前:", item.name, ",life=", item.life, ",try_num", item.try_update_num)
                if item.try_update_num <= item.try_update_limit:
                    # まだ何回か確認するまで、LifeはFalseにしない
                    # tk.line_send(" 謎の状態　t_state=", item.t_state, ",o_state=", item.o_state, ", 名前:", item.name,
                    #              ",life=", item.life, ",try_num", item.try_update_num, "回目　⇒再トライ")
                    item.count_up_position_check()  # 対象ポジションのtry_update_numをカウントアップする
                else:
                    item.life_set(False)  # 強制的にクローズ
                    # tk.line_send(" 謎の状態　t_state=", item.t_state, ",o_state=", item.o_state, ", 名前:", item.name,
                    #              ",life=", item.life, ",try_num", item.try_update_num, "回目のため終了（lifeFalse)")
        # else:
        #     # Lifeが終わっているもの

    # print(" ★★★★★一時テスト（classPosition)")
    # print(open_positions)
    # print(not_open_positions)
    # print("ここまで")
    # 結果の集約
    if len(open_positions) != 0:
        position_exist = True  # ポジションが一つでもOpenになっている場合は、True
    else:
        position_exist = False

    if len(not_open_positions) != 0:
        order_exist = True
    else:
        order_exist = False

    # 表示用の名前リストの作成
    name_list = "\n[P待ち]" + pending_class_names + "\n[P中]" + open_class_names + "\n"

    return {
        "position_exist": position_exist,
        "order_exist": order_exist,
        "open_positions": open_positions,
        "max_priority_position": max_priority_position,
        "not_open_positions": not_open_positions,  # 取得待ちの状態
        "max_priority_order": max_priority_order,
        "max_position_time_sec": max_position_time_sec,
        "max_order_time_sec": max_order_time_sec,
        "total_pl": total_pl,
        "name_list": name_list,
        "watching_list": watching_list
    }