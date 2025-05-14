import datetime
from datetime import timedelta

import classOanda
import tokens as tk
import fGeneric as gene
import gc
import fCommonFunction as cf
import sys

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
    latest_df_get_time = datetime.datetime.now().replace(microsecond=0) - timedelta(minutes=1)
    add_margin = 0.02  # CandleLcChangeで、余裕を見る分。初期は０だったが、マイナスを多くしても維持したい・・・！

    # 連続して取らないように、最後に取得したタイミングを抑える（ただし、オーダー即取得の場合にデータが取れないと困るので、１分前を入れておく）
    # ↓直前の情報を取得しておく
    before_latest_plu = 0
    before_latest_name = ""
    # ↓直前の情報の延長で、当面の情報を維持しておく
    history_plus_minus = [0]  # 空だと、過去のプラスマイナスを参照するときおかしなことになるので０を入れておく
    history_names = ["0"]  # 上の理由と同様に数字を入れておく

    def __init__(self, name, oa, is_live):
        self.name = name  #
        self.oa = oa  # クラス変数でもいいが、LiveとPracticeの混在ある？　引数でもらう
        self.is_live = is_live  # 本番環境か練習か（Boolean）
        # self.reset()
        # 以下リセット対象群
        self.priority = 0  # このポジションのプライオリティ（登録されるプランのプライオリティが、既登録以上の物だったら入れ替え予定）
        self.life = False  # 有効かどうか（オーダー発行からポジションクローズまでがTrue）
        self.order_permission = True
        self.plan = {}  # plan(name,units,direction,tp_range,lc_range,type,price,order_permission,margin,order_timeout_min)
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
        self.order_timeout_min = 45  # 分単位で指定
        self.trade_timeout_min = 50  # 分単位で指定
        self.over_write_block = False
        # 勝ち負け情報更新用(一つの関数を使いまわすため、辞書化する）
        self.win_lose_border_range = 0  # この値を超えている時間をWin、以下の場合Loseとする
        self.win_hold_time_sec = 0
        self.lose_hold_time_sec = 0
        self.win_max_plu = 0
        self.lose_max_plu = 0

        # ロスカット変更情報
        self.lc_change_dic = {}
        self.lc_change_from_candle_lc_price = 0
        self.lc_change_num = 0  # LCChangeまたはLCChangeCandleのいずれかの執行で加算される。０は未実行。１以上は執行済み。
        self.lc_change_less_minus_done = False
        # 特殊　カウンターオーダー
        self.counter_order_peace = {}  # 全ての情報は受け取れないので、CounterOrderで追記する
        self.counter_order_done = False

    def reset(self):
        # 情報の完全リセット（テンプレートに戻す）
        print("    OrderClassリセット")
        self.name = ""
        self.priority = 0  # このポジションのプライオリティ
        # self.is_live = True  # 本番環境か練習か（Boolean）　⇒する必要なし
        self.life = False
        self.plan = {}  # plan(name,units,direction,tp_range,lc_range,type,price,order_permission,margin,order_timeout_min)
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
        self.trade_timeout_min = 50
        self.over_write_block = False
        # 勝ち負け情報更新用
        self.win_lose_border_range = 0  # この値を超えている時間をWin、以下の場合Loseとする
        self.win_hold_time_sec = 0
        self.lose_hold_time_sec = 0
        self.win_max_plu = 0
        self.lose_max_plu = 0

        # ロスカット変更情報
        self.lc_change_dic = {}  # 空を持っておくだけ
        self.lc_change_from_candle_lc_price = 0
        self.lc_change_num = 0  # LCChangeまたはLCChangeCandleのいずれかの執行でTrueに変更される
        self.counter_order_peace = {}
        self.counter_order_done = False
        self.lc_change_less_minus_done = False

    def print_info(self):
        print("   <表示>", self.name, datetime.datetime.now().replace(microsecond=0))
        print("　 【life】", self.life)
        print("   【name】", self.name)
        print("   【order_permission】", self.order_permission)
        print("   【plan】", self.plan)
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

            # args = ("☆☆練習環境:",) + args
            # tk.line_send(*args)
            # if args[1] == "■■■解消:":
            #     # 中身を編集するため、一度リストに変換
            #     args_list = list(args)
            #     args_list[1] = "□□□解消:"  # ぱっとわかりやすいように変更
            #     tk.line_send(*tuple(args_list))
            # else:
            #     print("★★★", args)

    def order_plan_registration(self, plan):
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
        self.plan = plan  # 受け取ったプラン情報(そのままOrderできる状態が基本）

        # (1)クラスの名前＋情報の整流化（オアンダクラスに合う形に）
        print("消したいやつ(classPosition225行目"
              , "ClassPosition算出LC", round(plan['target_price'] - (abs(plan['lc_range']) * plan['direction']), 3)
              , "元LC", plan['lc_price']
              , "classPosition算出TP", round(plan['target_price'] + (abs(plan['tp_range']) * plan['direction']), 3)
              , "元TP", plan['tp_price']
              , "新DateNow", datetime.datetime.now()
              # , "元DateNow", self.plan['time']
              , "新price", plan['target_price']
              , "元price", plan['price']
              )
        # self.plan['price'] = plan['target_price']  # ターゲットプライス（注文価格）は、oandaClassではprice
        if 'priority' in plan:
            self.priority = plan['priority']  # プラオリティを登録する
        if 'trade_timeout_min' in plan:  # していない場合は初期値50分
            self.trade_timeout_min = plan['trade_timeout_min']
        if 'order_timeout_min' in plan:  # していない場合は初期値50分
            self.order_timeout_min = plan['order_timeout_min']
        self.name = plan['name']  #  + "(" + str(self.priority) + ")"  # 名前を入れる(クラス内の変更）
        # (2)各フラグを指定しておく
        self.order_permission = plan['order_permission']  # 即時のオーダー判断に利用する
        # (3-1) 付加情報１　各便利情報を格納しておく(直接Orderで使わない）
        # print("消したいやつ(classPosition225行目"
        #       , "ClassPosition算出LC", round(plan['target_price'] - (abs(plan['lc_range']) * plan['direction']), 3)
        #       , "元LC", plan['lc_price']
        #       , "classPosition算出TP", round(plan['target_price'] + (abs(plan['tp_range']) * plan['direction']), 3)
        #       , "元TP", plan['tp_price']
        #       , "新DateNow", datetime.datetime.now()
        #       , "元DateNow", self.plan['time']
        #       )
        # self.plan['lc_price'] = round(plan['target_price'] - (abs(plan['lc_range']) * plan['direction']), 3)
        # self.plan['tp_price'] = round(plan['target_price'] + (abs(plan['tp_range']) * plan['direction']), 3)
        # self.plan['time'] = datetime.datetime.now()

        # (4)LC_Change情報を格納する
        if "lc_change" in plan:
            self.lc_change_dic = plan['lc_change']  # 辞書を丸ごと

        # (6)ポジションがある場合、強制上書き（他のポジションの）を許可するかどうか
        if "over_write_block" in plan:
            self.over_write_block = plan['over_write_block']

        # (7)ポジションがある基準を超えている時間を継続する(デフォルトではコンストラクタで０が入る）
        if "win_lose_border_range" in plan:
            self.win_lose_border_range = plan['win_lose_border_range']

        # (8)カウンタオーダーを設定する
        if "counter_order" in plan:
            self.counter_order_peace = plan['counter_order']

        # (9)オーダーのLCを調整する（テスト中。過去の結果によって調子を変える）
        # lc_tuning_message = self.lc_tuning_by_history()
        # if lc_tuning_message:
        #     tk.line_send("過去のオーダーの勝敗履歴@classPosition, ", lc_tuning_message)
        # else:
        #     print("からです", lc_tuning_message)

        # (Final)オーダーを発行する
        if self.order_permission:
            order_res = self.make_order()
            if "order_result" in order_res:
                pass
            else:
                order_res['order_result'] = "この処理はオーダー失敗の可能性大"
        else:
            order_res = {"order_id": 0, 'order_result': 0}  # 返り値を揃えるため、強引だが辞書型を入れておく

        return {"order_name": self.name, "order_id": order_res['order_id'], "order_result": order_res['order_result']}

    def make_order(self):
        """
        planを元にオーダーを発行する。この時初めてLifeがTrueになる
        :return:
        """
        # 異常な数のオーダーを防御する
        # (1)　ポジション数の確認
        position_num_dic = self.oa.TradeAllCount_exe()
        position_num = position_num_dic['data']  # 現在のオーダー数を取得
        if position_num >= 10:
            # エラー等で大量のオーダーが入るのを防ぐ(６個以上のオーダーは防ぐ）
            self.send_line(" 【注】大量ポジションがある可能性", position_num_dic)
            return {"order_name": "error", "order_id": 0}
        # (2)オーダー数の確認
        order_num = self.oa.OrderCount_All_exe()
        if order_num >= 10:
            # エラー等で大量のオーダーが入るのを防ぐ
            self.send_line(" 【注】大量オーダーがある可能性", order_num)
            return {"order_name": "error", "order_id": 0}

        # (3)オーダー発行処理★
        order_ans_dic = self.oa.OrderCreate_dic_exe(self.plan)  # Plan情報からオーダー発行しローカル変数に結果を格納する
        order_ans = order_ans_dic['data']  # エラーはあんまりないから、いいわ。
        if order_ans['cancel']:  # キャンセルされている場合は、リセットする
            self.send_line(" 　Order不成立（今後ループの可能性）", self.name, order_ans['order_id'])
            return {"order_name": "error", "order_id": 0}

        # 必要な情報を登録する
        self.o_id = order_ans['order_id']
        self.o_time = order_ans['order_time']
        self.o_time_past_sec = 0  # 初回は変更なし
        self.life_set(True)  # ★重要　LIFEのONはここでのみ実施
        print("    オーダー発行完了＠make_order", self.name, )

        return {"order_name": "", "order_id": order_ans['order_id'], "order_result": order_ans}

    def close_order(self):
        # オーダークローズする関数 (情報のリセットは行わなず、Lifeの変更のみ）
        if not self.life:
            print("  order既にないが、CloseOrder指示あり", self.name)
            return 0  # Lifeが既にない場合は、実行無し

        self.life_set(False)  # まずはクローズ状態にする　（エラー時の反復を防ぐため。ただし毎回保存される？？）
        order_res_dic = self.oa.OrderDetails_exe(self.o_id)  # トレード情報の取得
        if order_res_dic['error'] == 1:
            print("    CloseOrderError@close_order")
            return 0
        order_info = order_res_dic["data"]['order']
        if order_info['state'] == "PENDING":  # orderがキャンセルできる状態の場合
            res = self.oa.OrderCancel_exe(self.o_id)
            if res['error'] == -1:
                print("   OrderCancelError@close_order")
                return 0
            # Close処理を実施
            self.o_state = "CANCELLED"
            # self.life_set(False)  # 本当はここに欲しい
            print("    orderCancel@close_order", self.o_id)
        else:  # FIEELDとかCANCELLEDの場合は、lifeにfalseを入れておく
            print("   order無し(決済済orキャンセル済)@close_order")

    def after_close_trade_function(self):
        """
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
        else:
            # 価格情報の更新
            order_information.total_yen = round(order_information.total_yen + float(trade_latest['unrealizedPL']), 2)
            order_information.total_PLu = round(order_information.total_PLu + trade_latest['PLu'], 3)
        # 計算する（回数）
        if float(trade_latest['realizedPL'])<0:
            order_information.minus_yen_position_num = order_information.minus_yen_position_num + 1
        else:
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
        print(float(trade_latest['initialUnits']), trade_latest['currentUnits'], self.o_json)
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
            res6 = "【合計】累積最大円:" + str(order_information.total_yen_max) + ",最小円:" + str(order_information.total_yen_min)
            res7 = "【合計】累計最大PL:" + str(order_information.total_PLu_max) + ",最小PL:" + str(order_information.total_PLu_min)
            res8 = "【回数】＋:" + str(order_information.plus_yen_position_num) + ",―:" + str(order_information.minus_yen_position_num)
            self.send_line("■■■解消:", self.name, '\n', gene.now(), '\n',
                           res4, res5, res1, id_info, res2, res3, res6, res7, res8, position_check_no_args()['name_list'])
        else:
            # 強制クローズ（Open最後の情報を利用する。stateはOpenの為、averageClose等がない。）
            # res1 = "強制Close【Unit】" + str(trade_latest['currentUnits'])
            res1 = "【Unit】" + str(units_for_view * direction)
            id_info = "【orderID】" + str(self.o_id) + "【tradeID】" + str(self.t_id)
            res2 = "【決:" + "現価" + ", " + "取:" + str(trade_latest['price']) + "】"
            res3 = "【ポジション期間の最大/小の振れ幅】 ＋域:" + str(self.win_max_plu) + "/ー域:" + str(self.lose_max_plu)
            res3 = res3 + " 保持時間(秒)" + str(trade_latest['time_past'])
            res4 = "【今回結果】" + str(trade_latest['PLu']) + "," + str(trade_latest['unrealizedPL']) + "円\n"
            res5 = "【合計】計" + str(order_information.total_PLu) + ",計" + str(order_information.total_yen) + "円"
            res6 = "【合計】累積最大円" + str(order_information.total_yen_max) + ",最小円" + str(
                order_information.total_yen_min)
            res7 = "【合計】累計最大PL" + str(order_information.total_PLu_max) + ",最小PL" + str(
                order_information.total_PLu_min)
            res8 = "【回数】＋:" + str(order_information.plus_yen_position_num) + ",―:" + str(order_information.minus_yen_position_num)

            self.send_line("■■■解消:", self.name, '\n', gene.now(), '\n',
                           res4, res5, res1, id_info, res2, res3, res6, res7, res8, position_check_no_args()['name_list'])

            # 結果のCSV保存
            tk.write_result({
                "time": gene.now(),
                "orderId": str(self.o_id),
                "tradeId": str(self.t_id),
                "plus_max": str(self.win_max_plu),
                "minus_max": str(self.lose_max_plu),
                "hold_time": str(trade_latest['time_past']),
                "result": str(trade_latest['PLu']),
                "result_yen": str(order_information.total_yen),
                "name": self.name
            })
        # カウンターオーダーの実行(いったんポジションを全てクローズした後）
        self.counter_order_exe()

    def counter_order_exe(self):
        # カウンターのオーダーを入れる。AfterCloseFunctionから呼ばれる
        # このクラスを再利用するため、LifeをTrueに戻すことを忘れずに
        if len(self.counter_order_peace) != 0 and not self.counter_order_done and 1 <= self.lc_change_num <= 2:
        # if len(self.counter_order_peace) != 0 and not self.counter_order_done and 0 <= self.lc_change_num:
            # カウンタオーダーがあり、カウンターオーダーが未執行で、なおかつ、LCChangeが執行されている場合（プラス確定の場合）
            # lcChangeが執行されていない場合は、だいぶ負けているため、自動的なカウンターは入れてはいけない、
            self.life_set(True)
            self.counter_order_done = True
            print("カウンター用オーダー")
            # 現在価格を取得する（ただし、今後のBidAskによって微妙に変えたい）

            if self.counter_order_peace['expected_direction'] == 1:
                # 買いの場合
                now_price = self.oa.NowPrice_exe("USD_JPY")['data']['ask']
            else:
                # 売りの場合
                now_price = self.oa.NowPrice_exe("USD_JPY")['data']['bid']

            # 書き換え確認用
            # print(" 書き換え前")
            # gene.print_json(self.counter_order_peace)
            # print(" 書き換え後")
            self.counter_order_peace['target'] = now_price + (0.01 * self.counter_order_peace['expected_direction'])
            self.counter_order_peace = cf.order_finalize(self.counter_order_peace)
            # gene.print_json(self.counter_order_peace)

            # オーダー発行
            self.order_plan_registration(self.counter_order_peace)
            # order_base(target_price, df_r.iloc[0]['time_jp'])
            print("カウンターオーダー実施。決済価格", self.t_json['averageClosePrice']
                           , "現時刻(dfFOrmat)", gene.now_df_format(), self.life, self.counter_order_done)
            self.send_line("カウンターオーダー実施。決済価格", self.t_json['averageClosePrice']
                           ,"現時刻(dfFOrmat)", gene.now_df_format(), " 現在価格", self.oa.NowPrice_exe("USD_JPY")
                           ,self.life, self.counter_order_done, "lcDoneNum:", self.lc_change_num)
            sys.exit(0)

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

            close_res = self.oa.TradeClose_exe(self.t_id, None)  # ★クローズを実行
            if close_res['error'] == -1:  # APIエラーの場合終了。ただし、
                self.send_line("  ★ポジション解消ミスNone＠close_position", self.name, self.t_id, self.t_pl_u)
                return 0
            # self.send_line("  ポジション解消指示", self.name, self.t_id, self.t_pl_u)
            self.after_close_trade_function()

        # 部分解除の場合（LINE送信無し）
        else:
            if float(units) > abs(float(self.t_current_units)):
                # 部分解消が失敗しそうなオーダーになっている場合
                self.send_line("    指定されたCloseUnits大（Error)⇒全解除, units", ">", abs(float(self.t_current_units)))
                self.life_set(False)  # ★大事　全解除の場合、APIがエラーでもLIFEフラグは取り下げる
                self.t_state = "CLOSED"
                close_res = self.oa.TradeClose_exe(self.t_id, None)  # ★オーダーを実行
                return 0
            else:
                # 部分解消が正常に実行できる注文数の場合
                close_res = self.oa.TradeClose_exe(self.t_id, {"units": units})  # ★オーダーを実行
                self.send_line('部分解消')
            if close_res['error'] == -1:  # APIエラーの場合終了。ただし、
                self.send_line("  ★ポジション解消ミス部分＠close_position", self.name, self.t_id, self.t_pl_u)
                return 0
            res_json = close_res['data_json']  # jsonデータを取得
            tradeID = res_json['orderFillTransaction']['tradeReduced']['tradeID']
            units = res_json['orderFillTransaction']['tradeReduced']['units']
            realizedPL = res_json['orderFillTransaction']['tradeReduced']['realizedPL']
            price = res_json['orderFillTransaction']['tradeReduced']['price']
            self.send_line("  ポジション部分解消", self.name, self.t_id, self.t_pl_u, "UNITS", units, "PL", realizedPL, "price", price)

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

    def detect_change(self):
        """
        update_informationでへんかを検知した場合これが　呼ばれる。
        :return:
        """
        order_latest = self.o_json
        trade_latest = self.t_json
        # print("detect_change関数")
        # print(order_latest)
        # print(trade_latest)
        if (self.o_state == "PENDING" or self.o_state == "") and order_latest['state'] == 'FILLED':  # オーダー達成（Pending⇒Filled）
            if trade_latest['state'] == 'OPEN':  # ポジション所持状態
                self.send_line("    (取得)", self.name, trade_latest['price'])
                #  取得時には、ローソクデータも取得しておく
                now = datetime.datetime.now().replace(microsecond=0)
                time_difference = now - self.latest_df_get_time  # 最後にDFを取った時からの経過時間
                seconds_difference = abs(time_difference.total_seconds())
                if seconds_difference >= 30:
                    # 初回の場合はやる
                    self.is_first_time_lc_change_candle = False  # 二回目以降はFalseにFalseを入れることになるが、、

                    d5_df = self.oa.InstrumentsCandles_multi_exe("USD_JPY", {"granularity": "M5", "count": 5},
                                                                 1)  # 時間昇順(直近が最後尾）
                    if d5_df['error'] == -1:
                        print("error Candle")
                        return -1
                    else:
                        self.latest_df = d5_df['data']
                        if self.is_first_time_lc_change_candle:
                            # 初回の場合は、取得したことにしない（５分ごとの時間が一番欲しいから）
                            self.is_first_time_lc_change_candle = False
                        else:
                            self.latest_df_get_time = datetime.datetime.now().replace(microsecond=0)
                        # print("LCChange用にDFを取得しました(取得時）", self.latest_df_get_time)
                        # print(self.latest_df)
                        # print("1行のみ抽出（取得時）")
                        # print(self.latest_df.iloc)
                        # print(" 置換対象のLC価格を持つ足データ（取得時）", self.latest_df.iloc[-2]['time_jp'])
                # else:
                #     print("前回取得時（取得時）", self.latest_df_get_time, "経過秒", seconds_difference)
                #     pass

            if "position_state" in trade_latest:
                if trade_latest['position_state'] == 'CLOSED':  # ポジションクローズ（ポジション取得とほぼ同時にクローズ[異常]）
                    self.send_line("    (即時)クローズ")
            else:
                pass
                # print("    NOT GOOD Ref")

        elif self.t_state == "OPEN" and trade_latest['state'] == "CLOSED":  # 通常の成り行きのクローズ時
            print("    成り行きのクローズ発生")
            self.after_close_trade_function()
            return 0

    def order_update_and_close(self):
        order_latest = self.o_json
        # 情報の更新
        self.o_state = order_latest['state']  # ここで初めて更新
        self.o_time_past_sec = order_latest['time_past']
        # オーダーのクローズを検討する
        if order_latest['state'] == "PENDING":
            # print("    時間的な解消を検討", self.o_time_past, self.o_state, "基準", self.order_timeout_min * 60)
            if self.o_time_past_sec > self.order_timeout_min * 60 and (self.o_state == "" or self.o_state == "PENDING"):
                self.close_order()
                self.send_line("   オーダー解消(時間)@", self.name, self.o_time_past_sec, ",", self.order_timeout_min
                               , position_check_no_args()['name_list'])
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
        self.t_time = trade_latest['openTime']  # 初回だけでよい？
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
        if trade_latest['state'] == "OPEN":
            # 規定時間を過ぎ、マイナス継続時間も１分程度ある場合は、もう強制ロスカットにする
            if self.t_time_past_sec > self.trade_timeout_min * 60 and self.lose_hold_time_sec > 60:
                self.send_line("   Trade解消(マイナス×時間)@", self.name, "PastTime", self.t_time_past_sec, ",LoseHold", self.lose_hold_time_sec
                               , position_check_no_args()['name_list'])
                self.close_trade(None)
        if trade_latest['state'] == "OPEN":
            # 規定時間を過ぎ、大きくプラスもなくふらふらしている場合
            if self.t_time_past_sec > self.trade_timeout_min * 60:  # 時間が経過している
                if self.win_max_plu <= dependence_win_max_plu_max and self.t_pl_u <= dependence_t_pl_u_max:
                    self.send_line("   Trade解消(微プラス膠着)@", self.name, "PastTime", self.t_time_past_sec, ",LoseHold",
                                 self.win_max_plu, self.t_pl_u)
                    self.close_trade(None)

    def update_information(self):  # orderとpositionを両方更新する
        """
        この関数では最新の状態を取得する（インスタンス変数を更新する）
        ただし、orderやTradeのステータスはこの関数では変更しない。
        （Update実行前との差分をみて変化を検知するプログラムより変更したくなく、その変化検知後に、order_update,trade_updateで更新）
        order "PENDING" "CANCELLED" "FILLED"
        position "OPEN" "CLOSED"
        :return:
        """
        if not self.life:
            return 0  # LifeがFalse（＝オーダーが発行されていない状態）では実行しない

        # (0)オーダーの仲間がいるかを確認
        self.exist_alive_class = life_check_no_args()  # 一つでも生きているクラスがあればTrueが入る

        # (1) OrderDetail,TradeDetailの取得（orderId,tradeIdの確保）
        order_ans = self.oa.OrderDetails_exe(self.o_id)  # ■■API
        if 'error' in order_ans:
            if order_ans['error'] == 1:
                print("OrderErrorのためリターン０（@classPosition463）")
                return 0
        order_latest = order_ans['data']['order']  # jsonを取得
        self.o_json = order_latest  # Json自体も格納
        # print("現在の状態　オーダー", self.name, self.o_id)
        # print("現在の状態　オー", self.name, self.o_json)

        if order_latest['state'] == "FILLED":
            #　オーダーが約定済みの場合
            if "tradeOpenedID" in order_latest:
                # ポジションが存在している場合
                # 他のオーダーを完全にクローズさせた場合
                if "tradeClosedIDs" in order_latest and not(self.already_offset_notice):
                    self.already_offset_notice = True  # オーダーが既存のオーダーを完全相殺し、さらにポジションもある場合の通知を2回目以降やらないため
                    # ただし、tradeCloseIDsもある場合は、このオーダーが他のオーダーを相殺した場合に発生する項目
                    # ★トレード有かつ相殺有の場合は、このオーダーがトレードよりも多いユニット注文があったことを意味する。
                    #  その為、オーダーのユニットの一部が相殺され、残るユニットがトレードとして存在する（その為Lifeを消さない）
                    tk.line_send("■■■オーダー解消（このオーダーは他のトレードを相殺＆残存ユニットのトレードへ↓）", self.name, "(",
                                 self.o_json['id'], ")")
                #
                self.t_id = order_latest['tradeOpenedID']
                trade_ans = self.oa.TradeDetails_exe(self.t_id)  # ■■API
                if trade_ans['error'] == 1:
                    print("    トレード情報取得Error＠update_information", self.t_id)
                    return 0
                trade_latest = trade_ans['data']['trade']  # Jsonデータの取得
                self.t_json = trade_latest  # Json自体も格納
                # print("ポジション詳細", self.t_json)
            elif "tradeReducedID" in order_latest:
                # このオーダーが、他のオーダーのポジションの一部を相殺した場合（このオーダーのポジションは相殺で消滅）
                # （tradeReduceがある場合、一部相殺状態）
                # Reduceしたトレードを見に行くと、最終的な結果が重複するため、トランザクション結果の価格を求める。
                # ただし格納形式を整えたいため、トレード情報を取得し、Pipsの部分だけを置き換える
                transaction_id = order_latest['fillingTransactionID']
                transaction_info = self.oa.get_transaction_single(transaction_id)
                reduced_trade_id = order_latest['tradeReducedID']
                trade_latest = self.oa.TradeDetails_exe(reduced_trade_id)['data']['trade']  # ■■API
                # print("トランザクション")
                # print(transaction_info)
                # print("トレード")
                # print(trade_latest)
                # 以下相殺発生分のみの情報に置き換え
                tk.line_send("■■■オーダー解消（相殺で消滅）", self.name, "(",   self.o_json['id'], ")" ,
                             "相殺したトレード", str(reduced_trade_id) + ",相殺したUNIT", transaction_info['transactions'][0]['requestedUnits'])
                trade_latest['state'] = "CLOSE"
                trade_latest['id'] = reduced_trade_id
                trade_latest['unrealizedPL'] = transaction_info['transactions'][0]['pl']  #
                trade_latest['currentUnits'] = float(transaction_info['transactions'][0]['requestedUnits'])  # 暫定的に相殺した分に置き換え
                trade_latest['state'] = "CLOSE"
                trade_latest['PLu'] = round(float(trade_latest['unrealizedPL']) / abs(float(transaction_info['transactions'][0]['requestedUnits'])), 3)
                self.t_json = trade_latest  # Json自体も格納
                # ★この場合に限り、このオーダーは存在しなくなるため、Close処理を実施する
                self.life_set(False)
                # self.after_close_trade_function()
            elif "tradeClosedIDs" in order_latest:
                # tradeCloseIDsがある場合は、このオーダーが他のオーダーを相殺した場合に発生する項目
                # ★この場合は、このオーダーでの通知（クローズ処理）は実施不要で、Lifeをクローズにする
                self.life_set(False)
                tk.line_send("■■■オーダー解消（このオーダーは他のトレードと完全相殺し終了）", self.name, "(",
                             self.o_json['id'], ")")
                return 0
            else:
                # ポジション取得待ち
                print("    トレード not detect", self.t_id)
                self.t_id = 0
                # tradeが０の場合、オーダーの更新のみ行う。
                self.order_update_and_close()
                return 0
        else:
            # オーダーがペンディングの場合(tradeはない状態)
            # print("    オーダーペンディング中", self.t_id)
            self.t_id = 0
            # tradeが０の場合、オーダーの更新のみ行う。
            self.order_update_and_close()
            return 0

        # (2) 【以下トレードありが前提】変化点を確認する order_update,trade_update yori mae niarukoto
        self.detect_change()

        # (3)情報をUpdate and Closeする
        self.order_update_and_close()
        self.trade_update_and_close()
        if self.o_state == "FILLED" and self.t_state == "CLOSED" and self.life:
            self.life_set(True)
            self.send_line("Filled Closed Trueの謎状態あり⇒強制的にLifeにFalseを入れて終了　classPosition 537行目")
        # 変化による情報（勝ち負けの各最大値、継続時間等の取得）
        self.updateWinLoseTime(trade_latest['PLu'])  # PLU(realizePL / Unit)の推移を記録する
        # ひっかけるようjなマイナス値を検出し、早期のロスカットを行う
        # self.lc_change_less_minus()
        # LCの変更を検討する(プラス域にいった場合のTP底上げ≒トレールに近い）
        self.lc_change()
        if self.lc_change_num != 0:
            # LC_Changeが執行されている場合は、Candleも有効にする
            self.lc_change_from_candle()

    def lc_change_less_minus(self):  # ポジションのLC底上げを実施 (基本的にはUpdateで平行してする形が多いかと）
        """
        ロスカットを狭い物から広いものに変更する（取得直後の直マイナスを減らしたい）
        特に、ブレイクと予想した物が、ひっかけですぐに戻るのを防止する
        """
        # print("   LC＿Change実行関数", self.name, self.t_pl_u, self.t_time_past_sec, len(self.lc_change_dic), self.t_state, self.lc_change_from_candle_lc_price)
        # print("    新ロスカットテスト", self.plan['type'], self.t_time_past_sec, self.t_pl_u, self.win_max_plu)
        # print("    新ロスカットテスト", self.lc_change_less_minus_done, self.t_state)
        if self.lc_change_less_minus_done or self.t_state != "OPEN":  # 足数×〇分足×秒
            # 実行しない条件は、既に実行済み　または、NotOpen
            return 0

        # 取得後短期間で、マイナス域にいて、なおかつプラスがほとんどない（ひっかけレベル）
        # print("    新ロスカットテスト", self.plan['type'], self.t_time_past_sec, self.t_pl_u, self.win_max_plu)
        if self.plan['type'] == "STOP":  # ひっかけに警戒するのは、順張り。すなわちSTOP。
            # if self.t_time_past_sec <= 220 and self.t_pl_u <= 0.02 and self.win_max_plu <= 0.007:
            if 60 < self.t_time_past_sec <= 220 and self.t_pl_u <= 0.02 and self.win_max_plu <= 0.016:
                # ロスカットを縮小する動きをとる
                lc_ensure_range = 0.036
                new_lc_price = round(float(self.t_execution_price) + (lc_ensure_range * self.plan['ask_bid']), 3)
                data = {"stopLoss": {"price": str(new_lc_price), "timeInForce": "GTC"}, }
                res = self.oa.TradeCRCDO_exe(self.t_id, data)  # LCライン変更の実行
                if res['error'] == -1:
                    self.send_line("    LC変更ミス＠lc_change")
                    return 0  # APIエラー時は終了
                # ★注意　self.plan["lc_price"]は更新しない！（元の価格をもとに、決めているため）⇒いや、変えてもいい・・？
                self.send_line("　(LC底上げ★即反対に行ったやつ)", self.name, self.t_pl_u, self.plan['lc_price'], "⇒", new_lc_price,
                             "lc底上げ", lc_ensure_range, "Posiprice", self.t_execution_price,
                             "予定価格", self.plan['price'], "[追加分]元々のRangeは", self.plan['lc_range'],
                               "現在マイナスは", self.t_pl_u, "最大Plusは", self.win_max_plu, "所持時間", self.t_time_past_sec)
                self.lc_change_less_minus_done = True  # フラグの成立（変更済）

            # # ボーダーラインを超えた場合
            # if self.t_pl_u >= lc_trigger_range:
            #     # print("　★変更確定")
            #     print(" 変更対象", i, lc_ensure_range, lc_trigger_range, self.t_pl_u)
            #     self.lc_change_num = self.lc_change_num + 1  # このクラス自体にLCChangeを実行した後をつけておく（カウント）
            #     # これで配列の中の辞書って変更できるっけ？？
            #     item['done'] = True
            #     new_lc_price = round(float(self.t_execution_price) + (lc_ensure_range * self.plan['ask_bid']), 3)
            #     data = {"stopLoss": {"price": str(new_lc_price), "timeInForce": "GTC"}, }
            #     res = self.oa.TradeCRCDO_exe(self.t_id, data)  # LCライン変更の実行
            #     if res['error'] == -1:
            #         self.send_line("    LC変更ミス＠lc_change")
            #         return 0  # APIエラー時は終了
            #     item['lc_change_exe'] = False  # 実行後はFalseする（１回のみ）
            #     # ★注意　self.plan["lc_price"]は更新しない！（元の価格をもとに、決めているため）⇒いや、変えてもいい・・？
            #     self.send_line("　(LC底上げ)", self.name, self.t_pl_u, self.plan['lc_price'], "⇒", new_lc_price,
            #                  "Border:", lc_trigger_range, "保証", lc_ensure_range, "Posiprice", self.t_execution_price,
            #                  "予定価格", self.plan['price'])
            #     break

    def lc_change(self):  # ポジションのLC底上げを実施 (基本的にはUpdateで平行してする形が多いかと）
        """
        ロスカット底上げを実施する。セルフとレールに近い
        lc_change_dicは配列で、lc_change_dicはPlanと同時にクラスに渡される。
        lc_change_dic =[{"lc_change_exe": True, "lc_trigger_range": 0.03, "lc_ensure_range": 0.1}]
        なお、LCの変更が執行されると、"done":Trueが付与される
        実行後
        [{"lc_change_exe": True, "lc_trigger_range": 0.03, "lc_ensure_range": 0.1” ,"done": False}]
        上記の辞書が、配列で渡される場合、配列全てで確認していく。
        :return:         print(" ロスカ変更関数", self.lc_change_dic, self.t_pl_u,self.t_state)
        """
        # print("   LC＿Change実行関数", self.name, self.t_pl_u, self.t_time_past_sec, len(self.lc_change_dic), self.t_state, self.lc_change_from_candle_lc_price)
        if len(self.lc_change_dic) == 0 or self.t_state != "OPEN":  # 足数×〇分足×秒
            # 指定がない場合、ポジションがない場合、ポジションの経過時間が短い場合は実行しない
            return 0

        if self.lc_change_from_candle_lc_price != 0:
            # print("既にキャンドルｌｃ変更有のため、通常ｌｃ無し", self.lc_change_from_candle_lc_price)
            pass

        for i, item in enumerate(self.lc_change_dic):
            # コードの１行を短くするため、置きかておく
            lc_exe = item['lc_change_exe']
            lc_ensure_range = item['lc_ensure_range']
            lc_trigger_range = item['lc_trigger_range']
            lc_change_waiting_time_sec = item['time_after']
            if "time_till" in item:
                # 指定の時間まで実行
                lc_change_till_sec = item['time_till']
            else:
                lc_change_till_sec = 100000  #

            # このループで実行しない場合（フラグオフの場合、DoneがTrueの場合^
            if not lc_exe or 'done' in item or self.t_time_past_sec < lc_change_waiting_time_sec:  # or self.t_time_past_sec > lc_change_till_sec:
                # エクゼフラグがFalse、または、done(この項目は実行した時にのみ作成される)が存在している場合、「実行しない」
                continue

            # ボーダーラインを超えた場合
            if self.t_pl_u >= lc_trigger_range:
                # print("　★変更確定")
                print(" 変更対象", i, lc_ensure_range, lc_trigger_range, self.t_pl_u)
                self.lc_change_num = self.lc_change_num + 1  # このクラス自体にLCChangeを実行した後をつけておく（カウント）
                # これで配列の中の辞書って変更できるっけ？？
                item['done'] = True
                new_lc_price = round(float(self.t_execution_price) + (lc_ensure_range * self.plan['ask_bid']), 3)
                data = {"stopLoss": {"price": str(new_lc_price), "timeInForce": "GTC"}, }
                res = self.oa.TradeCRCDO_exe(self.t_id, data)  # LCライン変更の実行
                if res['error'] == -1:
                    self.send_line("    LC変更ミス＠lc_change")
                    return 0  # APIエラー時は終了
                item['lc_change_exe'] = False  # 実行後はFalseする（１回のみ）
                # ★注意　self.plan["lc_price"]は更新しない！（元の価格をもとに、決めているため）⇒いや、変えてもいい・・？
                self.send_line("　(LC底上げ)", self.name, self.t_pl_u, self.plan['lc_price'], "⇒", new_lc_price,
                             "Border:", lc_trigger_range, "保証", lc_ensure_range, "Posiprice", self.t_execution_price,
                             "予定価格", self.plan['price'])
                break

    def lc_change_from_candle(self):  # ポジションのLC底上げを実施 (基本的にはUpdateで平行してする形が多いかと）
        """
        ロスカット底上げを実施する。セルフとレールに近い
        ひとつ前のローソクの最高値や最低値までをLC底上げする関数。
        最新のローソクを取得する必要がある。この関数自体は２秒に１回呼び出されるが、
        ローソクを取得するのは、５分に１回のみで問題ないため、メインと同じコードを書くことになるが、それで対応する。
        """
        # print("  ★LC＿ChangeFromCandle実行関数")
        if self.t_state != "OPEN" or self.t_pl_u < 0 or self.t_time_past_sec < 100:  # 足数×〇分足×秒
            # ポジションがない場合、プラス域ではない場合、所持時間が短い場合は実行しない
            # print("       lc_change_candleの実行無", self.t_state, self.t_pl_u, self.t_time_past_sec)
            return 0
        else:
            # print("       lc_change_candleの実行あり", self.t_state, self.t_pl_u, self.t_time_past_sec)
            pass

        # ★★★

        # LCChangeの実行部分
        # 定期的にデータフレームを取得する部分（引数で渡してもいいが、この関数で完結したかった）
        gl_now = datetime.datetime.now().replace(microsecond=0)  # 現在の時刻を取得
        time_hour = gl_now.hour  # 現在時刻の「時」のみを取得
        time_min = gl_now.minute  # 現在時刻の「分」のみを取得
        time_sec = gl_now.second  # 現在時刻の「秒」のみを取得
        if time_min % 5 == 0 and 6 <= time_sec < 30:
            # ５分毎か初回で実行
            now = datetime.datetime.now().replace(microsecond=0)
            time_difference = now - self.latest_df_get_time  # 最後にDFを取った時からの経過時間
            seconds_difference = abs(time_difference.total_seconds())
            if seconds_difference >= 30:
                d5_df = self.oa.InstrumentsCandles_multi_exe("USD_JPY", {"granularity": "M5", "count": 5}, 1)  # 時間昇順(直近が最後尾）
                if d5_df['error'] == -1:
                    print("error Candle")
                    return -1
                else:
                    self.latest_df = d5_df['data']
                    self.latest_df_get_time = datetime.datetime.now().replace(microsecond=0)
        #             print("LCChange用にDFを取得しました", self.latest_df_get_time)
        #             print(self.latest_df)
        #             print("1行のみ抽出")
        #             print(self.latest_df.iloc)
        #             print(" 置換対象のLC価格を持つ足データ", self.latest_df.iloc[-2]['time_jp'])
        #
        #     else:
        #         print("データ取得無し　前回から時間がたっていない", self.latest_df_get_time, "経過秒", seconds_difference)
        #         pass
        # else:
        #     print("データ取得無し　 時刻条件合わず",time_min,"分", time_sec,"秒")

        if self.plan['direction']>0:
            # 買い方向の場合、ひとつ前のローソクのLowの値をLC価格に
            lc_price_temp = float(self.latest_df.iloc[-2]['low']) - order_information.add_margin
        else:
            # 売り方向の場合、ひとつ前のローソクのHighの値をLC価格に
            lc_price_temp = float(self.latest_df.iloc[-2]['high']) + order_information.add_margin

        # print("対象となるLC基準", self.latest_df.iloc[-2]['time_jp'], lc_price_temp)

        if self.lc_change_from_candle_lc_price == lc_price_temp:
            # print(" 既にこの価格のLCとなっているため、変更処理は実施せず")
            return 0

        # ポジション取得から５分経過、かつ、temp_lc_priceがマイナス域でなく、利益が1pips以上確約できる場合、LCをlc_price_tempに移動する
        take_position_price = float(self.t_json['price'])
        lc_ensure_range = abs(take_position_price - lc_price_temp)
        if lc_ensure_range <= 0.01:
            # print(" 確保できる利益幅が0.01以下のため、変更なし")
            return 0
        if self.plan['direction'] > 0 and lc_price_temp < take_position_price:
            # 買い方向で、ターゲットよりLCtempが小さい価格の場合（lctempがマイナス域の場合)
            # print("   LCChangeCnadle", self.plan['direction'], lc_price_temp , "<",take_position_price )
            # print("lc_priceにしたい価格", lc_price_temp ,"　が取得価格", take_position_price, "より小さいためプラス確保のLCにならずNG")
            return 0
        elif self.plan['direction'] < 0 and lc_price_temp > take_position_price:
            # 売り方向で、ターゲットよりLCtempが大きい価格の場合（lctempがマイナス域の場合)
            # print("   LCChangeCnadle", self.plan['direction'], lc_price_temp , ">",take_position_price )
            # print("lc_priceにしたい価格", lc_price_temp, "　が取得価格", take_position_price, "より大きいためプラス確保のLCにならずNG")
            return 0

        # レンジ換算の時、大きすぎないかを確認
        if lc_ensure_range >= 0.08:
            print("range換算で大きすぎる・・・？", lc_ensure_range)

        # LCチェンジ執行
        self.lc_change_candle_done = True  # このクラス自体にLCChangeを実行した後をつけておく（各LCChange条件ではなく）
        new_lc_price = round(lc_price_temp, 3)
        data = {"stopLoss": {"price": str(new_lc_price), "timeInForce": "GTC"}, }
        res = self.oa.TradeCRCDO_exe(self.t_id, data)  # LCライン変更の実行
        if res['error'] == -1:
            self.send_line("    LC変更ミス＠lc_change")
            return 0  # APIエラー時は終了
        self.lc_change_from_candle_lc_price = lc_price_temp  # ロスカット価格の保存
        lc_range = round(abs(float(lc_price_temp) - float(self.t_execution_price)), 5)
        self.lc_change_num = self.lc_change_num + 1  # このクラス自体にLCChangeを実行した後をつけておく（カウント）
        self.send_line("　(LCCandle底上げ)", self.name, "現在のPL" ,self.t_pl_u, "新LC価格⇒", new_lc_price,
                       "保証", lc_range, "約定価格", self.t_execution_price,
                       "予定価格", self.plan['price'])

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
            print("  直近の勝敗pips", latest_plu, "詳細(直近1つ)", order_information.history_plus_minus[-1])
        else:
            # 過去の履歴が二つ以上の場合、直近の二つの合計で判断する
            latest_plu = order_information.history_plus_minus[-1] + order_information.history_plus_minus[-2]  # 変数化(短縮用)
            print("  直近の勝敗pips", latest_plu, "詳細(直近)", order_information.history_plus_minus[-1],
                  order_information.history_plus_minus[-2])
        # 最大でも現実的な10pips程度のTPに収める
        if abs(latest_plu) >= 0.01:
            latest_plu = 0.01

        # 値を調整する
        if latest_plu == 0:
            print("  初回(本番)かAnalysisでのTP調整執行⇒特に何もしない（TPの設定等は行う）")
            # 通常環境の場合
            tp_range = 0.5
            lc_change_type = 3
        else:
            if latest_plu <= tp_up_border_minus:
                print("  ★マイナスが大きいため、取り返し調整（TPを短縮し、確実なプラスを狙いに行く）", latest_plu * 0.8)
                # tp_range = tp_up_border_minus  # とりあえずそこそこをTPにする場合
                tp_range = abs(latest_plu * 0.8)  # 負け分をそのままTPにする場合
                lc_change_type = 4  # LCchangeの設定なし
                tk.line_send("取り返し調整発生")
            else:
                # 直近がプラスの場合プラスの場合、普通。
                print("  ★前回プラスのため、通常TP設定")
                tp_range = 0.5
                lc_change_type = 3  # LCchangeの設定なし

        return {"tuned_tp_range": tp_range, "tuned_lc_change_type": lc_change_type}


    def tuning_by_history_resi(self):
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
            print("  直近の勝敗pips", latest_plu, "詳細(直近1つ)", order_information.history_plus_minus[-1])
        else:
            # 過去の履歴が二つ以上の場合、直近の二つの合計で判断する
            latest_plu = order_information.history_plus_minus[-1] + order_information.history_plus_minus[-2]  # 変数化(短縮用)
            print("  直近の勝敗pips", latest_plu, "詳細(直近)", order_information.history_plus_minus[-1],
                  order_information.history_plus_minus[-2])
        # 最大でも現実的な10pips程度のTPに収める
        if abs(latest_plu) >= 0.01:
            latest_plu = 0.01

        # 値を調整する
        if latest_plu == 0:
            print("  初回(本番)かAnalysisでのTP調整執行⇒特に何もしない（TPの設定等は行う）")
            # 通常環境の場合
            tp_range = 0.5
            lc_change_type = 1
        else:
            if latest_plu <= tp_up_border_minus:
                print("  ★マイナスが大きいため、取り返し調整（TPを短縮し、確実なプラスを狙いに行く）", latest_plu * 0.8)
                # tp_range = tp_up_border_minus  # とりあえずそこそこをTPにする場合
                tp_range = abs(latest_plu * 0.8)  # 負け分をそのままTPにする場合
                lc_change_type = 3  # LCchangeの設定なし
                tk.line_send("取り返し調整発生")
            else:
                # 直近がプラスの場合プラスの場合、普通。
                print("  ★前回プラスのため、通常TP設定")
                tp_range = 0.5
                lc_change_type = 1  # LCchangeの設定なし

        return {"tuned_tp_range": tp_range, "tuned_lc_change_type": lc_change_type}



def error_end(info):
    print("  ★■★APIエラー発生")
    # print(" ")
    # sys.exit()  # 強制終了


def all_update_information(*args):
    """
    全ての情報を更新する
    :return:
    """
    classes = args[0]
    for item in classes:
        if item.life:
            # print("個別", item.life)
            item.update_information()


def reset_all_position(classes):
    """
    全てのオーダー、ポジションをリセットして、更新する
    :return:
    """
    print("  RESET ALL POSITIONS")
    oa = classes[0].oa  # とりあえずクラスの一つから。オアンダのクラスを取っておく
    oa.OrderCancel_All_exe()  # 露払い(classesに依存せず、オアンダクラスで全部を消す）
    oa.TradeAllClose_exe()  # 露払い(classesに依存せず、オアンダクラスで全部を消す）
    all_update_information(classes)  # 関数呼び出し（アップデート）


def life_check(classes):
    """
    オーダーが生きているかを確認する。一つでも生きていればＴｒｕｅを返す
    :return:
    """

    life = []
    unlife = []
    for item in classes:
        if item.life:
            life.append(item)
        else:
            unlife.append(item)
    # 結果を集約する
    if len(life) == 0:
        ans = False  # 一つもLifeがOnでない。
    else:
        ans = True  # 一つでもLifeがある場合はＴｒｕｅ
        # print(" 残っているLIFE", life)

    return ans


def life_check_no_args():
    """
    オーダーが生きているかを確認する。一つでも生きていればＴｒｕｅを返す
    :return:
    """
    classes = get_instances_of_class()
    life = []
    unlife = []
    for item in classes:
        if item.life:
            life.append(item)
        else:
            unlife.append(item)
    # 結果を集約する
    if len(life) == 0:
        ans = False  # 一つもLifeがOnでない。
    else:
        ans = True  # 一つでもLifeがある場合はＴｒｕｅ
        # print(" 残っているLIFE", life)

    return ans


def close_opposite_order(classes):
    # 現在のポジションの方向を確認（基本的に同方向のポジションしかない前提）
    position_direction = 0
    position_count = 0
    lives = 0  # オーダーとポジションの合計（＝ライフの合計）
    for item in classes:
        # print("  item_info", item.name, item.life)
        if item.t_state == "OPEN":
            position_count += 1
            position_direction = item.plan['direction']
        if item.life:
            lives += 1
    # 逆方向のオーダーを解除する
    for item in classes:
        if lives > 1:  # ライフオンが１以上（自分以外のオーダー等がある）
            # print(" ★CloseTarget", item.name, item.plan)
            if len(item.plan) != 0:  # 空のItemも存在している
                if item.plan['expected_direction'] != position_direction:
                    item.close_order()
                    # print("  CloseOppsite実行")
    # print("   CloseOppsit", position_direction, position_count, lives)


def position_info(classes):
    """
    lIFEがある物を探してくる
    :param classes:
    :return:
    """
    ans = ""
    count = 0
    for item in classes:
        if "W" in item.name:  # Wと未遂は除外
            pass
        else:
            if item.life:
                # 文章生成
                temp = "@:" + item.name + "," + item.t_state + ",pl:" + str(round(float(item.t_unrealize_pl), 2)) + "円,"
                temp = temp + str(item.t_pl_u) + " PLu," + "ID:" + str(item.t_id) + " "
                temp = temp + str(item.t_time_past_sec) + "秒経過"
                if count == 0:  # 初回のみ
                    pass
                else:
                    temp = "\n" + temp  # 二個目以降を次の行とするために、改行を入れる
                ans = ans + temp
    return ans


# 特定のクラスのインスタンス一覧を取得する関数(現在メモリ上にあるクラスのインスタンスのリストを返す）
def get_instances_of_class():
    """
    引数は無し。
    """
    return [obj for obj in gc.get_objects() if isinstance(obj, order_information)]


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
    classes = get_instances_of_class()

    # 実処理
    open_positions = []
    not_open_positions = []
    max_priority_order = 0
    max_priority_position = 0
    max_position_time_sec = 0
    max_order_time_sec = 0
    open_class_names = closed_class_names = pending_class_names = ""
    total_pl = 0
    for item in classes:
        if item.life:  #lifeがTrueの場合、ポジションかオーダーが存在
            # 各情報
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
                    "direction": item.plan['direction']
                })
                # ポジションの所有時間（ポジションがある中で最大）も取得しておく
                if item.t_time_past_sec > max_position_time_sec:
                    max_position_time_sec = item.t_time_past_sec  # 何分間持たれているポジションか
                # トータルの含み損益を表示する
                total_pl = total_pl + float(item.t_unrealize_pl)
                # オーダー時間リストを作る（表示用）
                open_class_names = open_class_names + "," + gene.delYearDay(item.o_time)
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
                    "direction": item.plan['direction']
                })
                # ポジションの所有時間（ポジションがある中で最大）も取得しておく
                if item.o_time_past_sec > max_order_time_sec:
                    max_order_time_sec = item.o_time_past_sec  # 何分間オーダー待ちか
                # オーダー時間リストを作成する（表示用）
                pending_class_names = pending_class_names + "," + gene.delYearDay(item.o_time)
            else:
                # どうやらt_stateが入っていない状態（オーダーエラーや謎の状態）
                print(" 謎の状態(t_state)", item.t_state, "o_state", item.o_state, item.name)
                tk.line_send("謎の状態発生(t_state)", item.t_state, "o_state", item.o_state, item.name)
                item.life_set(False)  # 強制的にクローズ

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
        "name_list": name_list
    }

