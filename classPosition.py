import datetime
import tokens as tk
import fGeneric as f


class order_information:
    total_yen = 0  # トータルの円
    total_PLu = 0  # PL/Unitの累計値
    position_num = 0  # 何個のポジションを持ったか

    def __init__(self, name, oa):
        self.oa = oa  # クラス変数でもいいが、LiveとPracticeの混在ある？　引数でもらう
        # リセ対象群
        self.name = name  # FwかRvかの表示用。引数でもらう
        self.priority = 0  # このポジションのプライオリティ（登録されるプランのプライオリティが、既登録以上の物だったら入れ替え予定）
        self.life = False  # 有効かどうか（オーダー発行からポジションクローズまでがTrue）
        self.order_permission = True
        self.plan = {}  # plan(name,units,direction,tp_range,lc_range,type,price,order_permission,margin,order_timeout_min)
        # オーダー情報(オーダー発行時に基本的に上書きされる）
        self.o_json = {}
        self.o_id = 0
        self.o_time = 0
        self.o_state = ""
        self.o_time_past = 0  # オーダー発行からの経過秒
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
        # 経過時間管理
        self.order_timeout_min = 25  # 分単位で指定
        self.trade_timeout_min = 50  # 分単位で指定
        self.over_write_block = False
        # 勝ち負け情報更新用(一つの関数を使いまわすため、辞書化する）
        self.win_lose_border_range = 0  # この値を超えている時間をWin、以下の場合Loseとする
        self.win_hold_time_sec = 0
        self.lose_hold_time_sec = 0
        self.win_max_plu = 0
        self.lose_max_plu = 0

        # ロスカット変更情報
        self.lc_change_dic = {}  # 空を持っておくだけ

    def reset(self):
        # 情報の完全リセット（テンプレートに戻す）
        print("    OrderClassリセット")
        self.name = ""
        self.priority = 0  # このポジションのプライオリティ
        self.life = False
        self.plan = {}  # plan(name,units,direction,tp_range,lc_range,type,price,order_permission,margin,order_timeout_min)
        # オーダー情報(オーダー発行時に基本的に上書きされる）
        self.o_id = 0
        self.o_time = 0
        self.o_state = ""
        self.o_time_past = 0  # オーダー発行からの経過秒
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
        # 経過時間管理
        self.order_timeout_min = 25  # 分単位で指定
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

    def print_info(self):
        print("   <表示>", self.name, datetime.datetime.now().replace(microsecond=0))
        print("　 【life】", self.life)
        print("   【name】", self.name)
        print("   【order_permission】", self.order_permission)
        print("   【plan】", self.plan)
        print("   【order1】", self.o_id, self.o_time, self.o_state, self.o_time_past)
        print("   【trade1】", self.t_id, self.t_execution_price, self.t_type, self.t_initial_units, self.t_current_units)
        print("   【trade1】", self.t_time, self.t_time_past_sec)
        print("   【trade2】", self.t_state, self.t_realize_pl, self.t_close_time, self.t_close_price)

    def print_info_short(self):
        print("   <表示>", self.name, datetime.datetime.now().replace(microsecond=0))
        print("　 【life】", self.life)
        print("   【name】", self.name)
        print("   【order1】", self.o_id, self.o_time, self.o_state, self.o_time_past)
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
        self.plan['price'] = plan['target_price']  # ターゲットプライス（注文価格）は、oandaClassではprice
        if 'priority' in plan:
            self.priority = plan['priority']  # プラオリティを登録する
        if 'trade_timeout_min' in plan:  # していない場合は初期値50分
            self.trade_timeout_min = plan['trade_timeout_min']
        self.name = plan['name'] + str(self.priority)  # 名前を入れる(クラス内の変更）
        # (2)各フラグを指定しておく
        self.order_permission = plan['order_permission']  # 即時のオーダー判断に利用する
        # (3-1) 付加情報１　各便利情報を格納しておく(直接Orderで使わない）
        self.plan['lc_price'] = round(plan['target_price'] - (abs(plan['lc_range']) * plan['direction']), 3)
        self.plan['tp_price'] = round(plan['target_price'] + (abs(plan['tp_range']) * plan['direction']), 3)
        self.plan['time'] = datetime.datetime.now()

        # (4)LC_Change情報を格納する
        if "lc_change" in plan:
            self.lc_change_dic = plan['lc_change']  # 辞書を丸ごと


        # (6)ポジションがある場合、強制上書き（他のポジションの）を許可するかどうか
        if "over_write_block" in plan:
            self.over_write_block = plan['over_write_block']

        # (7)ポジションがある基準を超えている時間を継続する(デフォルトではコンストラクタで０が入る）
        if "win_lose_border_range" in plan:
            self.win_lose_border_range = plan['win_lose_border_range']

        # (Final)オーダーを発行する
        if self.order_permission:
            order_res = self.make_order()
        else:
            order_res = {"order_id": 0}  # 返り値を揃えるため、強引だが辞書型を入れておく

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
            tk.line_send(" 【注】大量ポジション入る可能性", position_num_dic)
            return {"order_name": "error", "order_id": 0}
        # (2)オーダー数の確認
        order_num = self.oa.OrderCount_All_exe()
        if order_num >= 10:
            # エラー等で大量のオーダーが入るのを防ぐ
            tk.line_send(" 【注】大量オーダー入る可能性", order_num)
            return {"order_name": "error", "order_id": 0}

        # (3)オーダー発行処理★
        order_ans_dic = self.oa.OrderCreate_dic_exe(self.plan)  # Plan情報からオーダー発行しローカル変数に結果を格納する
        order_ans = order_ans_dic['data']  # エラーはあんまりないから、いいわ。
        if order_ans['cancel']:  # キャンセルされている場合は、リセットする
            tk.line_send(" 　Order不成立（今後ループの可能性）", self.name, order_ans['order_id'])
            return {"order_name": "error", "order_id": 0}

        # 必要な情報を登録する
        self.o_id = order_ans['order_id']
        self.o_time = order_ans['order_time']
        self.o_time_past = 0  # 初回は変更なし
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
        呼ばれるパターンは２種類
        ①自然のロスカット⇒クローズ状態が格納されている。
        ②強制クローズ⇒クローズ後に呼ばれるが、t_jsonの情報が書き換わっていない為、一つ古いOpen時の情報を使うことになる(いつかClose情報を使う？）
        :param trade_latest:
        :return:
        """
        trade_latest = self.t_json
        # (0)　改めてLifeを殺す
        self.life_set(False)
        # （１）
        if trade_latest['state'] == "CLOSED":
            order_information.total_yen = round(order_information.total_yen + float(trade_latest['realizedPL']), 2)
            order_information.total_PLu = round(order_information.total_PLu + trade_latest['PLu'], 3)
        else:
            # 価格情報の更新
            order_information.total_yen = round(order_information.total_yen + float(trade_latest['unrealizedPL']), 2)
            order_information.total_PLu = round(order_information.total_PLu + trade_latest['PLu'], 3)

        # （２）LINE送信
        if trade_latest['state'] == "CLOSED":
            res1 = "【Unit】" + str(trade_latest['initialUnits'])
            id_info = "【orderID】" + str(self.o_id) + "【tradeID】" + str(self.t_id)
            res2 = "【決:" + str(trade_latest['averageClosePrice']) + ", " + "取:" + str(trade_latest['price']) + "】"
            res3 = "【ポジション期間の最大/小の振れ幅】 ＋域:" + str(self.win_max_plu) + "/ー域:" + str(self.lose_max_plu)
            res3 = res3 + " 保持時間(秒)" + str(trade_latest['time_past'])
            res4 = "【今回結果】" + str(trade_latest['PLu']) + "," + str(trade_latest['realizedPL']) + "円\n"
            res5 = "【合計】計" + str(order_information.total_PLu) + ",計" + str(order_information.total_yen) + "円"
            tk.line_send(" ▲解消:", self.name, '\n', f.now(), '\n',
                         res4, res5, res1, id_info, res2, res3)
        else:
            # 強制クローズ（Open最後の情報を利用する。stateはOpenの為、averageClose等がない。）
            res1 = "強制Close【Unit】" + str(trade_latest['initialUnits'])
            id_info = "【orderID】" + str(self.o_id) + "【tradeID】" + str(self.t_id)
            res2 = "【決:" + "現価" + ", " + "取:" + str(trade_latest['price']) + "】"
            res3 = "【ポジション期間の最大/小の振れ幅】 ＋域:" + str(self.win_max_plu) + "/ー域:" + str(self.lose_max_plu)
            res3 = res3 + " 保持時間(秒)" + str(trade_latest['time_past'])
            res4 = "【今回結果】" + str(trade_latest['PLu']) + "," + str(trade_latest['unrealizedPL']) + "円\n"
            res5 = "【合計】計" + str(order_information.total_PLu) + ",計" + str(order_information.total_yen) + "円"
            tk.line_send(" ▲解消:", self.name, '\n', f.now(), '\n',
                         res4, res5, res1, id_info, res2, res3)

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
                tk.line_send("  ★ポジション解消ミスNone＠close_position", self.name, self.t_id, self.t_pl_u)
                return 0
            tk.line_send("  ポジション解消指示", self.name, self.t_id, self.t_pl_u)
            self.after_close_trade_function()

        # 部分解除の場合（LINE送信無し）
        else:
            if float(units) > abs(float(self.t_current_units)):
                # 部分解消が失敗しそうなオーダーになっている場合
                tk.line_send("    指定されたCloseUnits大（Error)⇒全解除, units", ">", abs(float(self.t_current_units)))
                self.life_set(False)  # ★大事　全解除の場合、APIがエラーでもLIFEフラグは取り下げる
                self.t_state = "CLOSED"
                close_res = self.oa.TradeClose_exe(self.t_id, None)  # ★オーダーを実行
                return 0
            else:
                # 部分解消が正常に実行できる注文数の場合
                close_res = self.oa.TradeClose_exe(self.t_id, {"units": units})  # ★オーダーを実行

            if close_res['error'] == -1:  # APIエラーの場合終了。ただし、
                tk.line_send("  ★ポジション解消ミス部分＠close_position", self.name, self.t_id, self.t_pl_u)
                return 0
            res_json = close_res['data_json']  # jsonデータを取得
            tradeID = res_json['orderFillTransaction']['tradeReduced']['tradeID']
            units = res_json['orderFillTransaction']['tradeReduced']['units']
            realizedPL = res_json['orderFillTransaction']['tradeReduced']['realizedPL']
            price = res_json['orderFillTransaction']['tradeReduced']['price']
            tk.line_send("  ポジション部分解消", self.name, self.t_id, self.t_pl_u, "UNITS", units, "PL", realizedPL, "price", price)

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
        if (self.o_state == "PENDING" or self.o_state == "") and order_latest['state'] == 'FILLED':  # オーダー達成（Pending⇒Filled）
            if trade_latest['state'] == 'OPEN':  # ポジション所持状態
                tk.line_send("    (取得)", self.name)

            if "position_state" in trade_latest:
                if trade_latest['position_state'] == 'CLOSED':  # ポジションクローズ（ポジション取得とほぼ同時にクローズ[異常]）
                    tk.line_send("    (即時)クローズ")
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
        self.o_time_past = order_latest['time_past']
        # オーダーのクローズを検討する
        if order_latest['state'] == "PENDING":
            # print("    時間的な解消を検討", self.o_time_past, self.o_state, "基準", self.order_timeout_min * 60)
            if self.o_time_past > self.order_timeout_min * 60 and (self.o_state == "" or self.o_state == "PENDING"):
                tk.line_send("   オーダー解消(時間)@", self.name, self.o_time_past, ",", self.order_timeout_min)
                self.close_order()

    def trade_update_and_close(self):
        trade_latest = self.t_json  # とりあえず入れ替え（update関数で取得した最新の情報）
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
        elif trade_latest['state'] == "CLOSED":  # いる？
            self.t_realize_pl = trade_latest['realizedPL']
        self.t_pl_u = trade_latest['PLu']

        # tradeのクローズを検討する
        if trade_latest['state'] == "OPEN":
            # 規定時間を過ぎ、マイナス継続時間も１分程度ある場合は、もう強制ロスカットにする
            if self.t_time_past_sec > self.trade_timeout_min * 60 and self.lose_hold_time_sec > 60:
                tk.line_send("   Trade解消(マイナス×時間)@", self.name, "PastTime", self.t_time_past_sec, ",LoseHold", self.lose_hold_time_sec)
                self.close_trade(None)
            # 規定時間を過ぎ、大きくプラスもなくふらふらしている場合
            if self.t_time_past_sec > self.trade_timeout_min * 60:  # 時間が経過している
                if self.win_max_plu <= 0.05 and self.t_pl_u <= 0.03:
                    tk.line_send("   Trade解消(微プラス膠着)@", self.name, "PastTime", self.t_time_past_sec, ",LoseHold",
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

        # (1) OrderDetail,TradeDetailの取得（orderId,tradeIdの確保）
        order_ans = self.oa.OrderDetails_exe(self.o_id)  # ■■API
        order_latest = order_ans['data']['order']  # jsonを取得
        self.o_json = order_latest  # Json自体も格納
        if "tradeOpenedID" in order_latest:  # ポジションが存在している場合
            # print("    トレードdetect", self.t_id)
            self.t_id = order_latest['tradeOpenedID']
            trade_ans = self.oa.TradeDetails_exe(self.t_id)  # ■■API
            if trade_ans['error'] == 1:
                print("    トレード情報取得Error＠update_information", self.t_id)
                return 0
            trade_latest = trade_ans['data']['trade']  # Jsonデータの取得
            self.t_json = trade_latest  # Json自体も格納
        else:  # ポジションが存在していない（既存ポジションに相殺された）　または、ポジション取得待ち
            # print("    トレード not detect", self.t_id)
            self.t_id = 0
            # tradeが０の場合、オーダーの更新のみ行う。
            self.order_update_and_close()
            return 0

        # (2) 【以下トレードありが前提】変化点を確認する order_update,trade_update yori mae niarukoto
        self.detect_change()

        # (3)情報をUpdate and Closeする
        self.order_update_and_close()
        self.trade_update_and_close()

        # 変化による情報（勝ち負けの各最大値、継続時間等の取得）
        self.updateWinLoseTime(trade_latest['PLu'])  # PLU(realizePL / Unit)の推移を記録する
        # LCの変更を検討する
        self.lc_change()

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
        # print("  ★LC＿Change実行関数")
        if len(self.lc_change_dic) == 0 or self.t_state != "OPEN" or self.t_time_past_sec < 60:
            # 指定がない場合、ポジションがない場合、ポジションの経過時間が短い場合は実行しない
            return 0

        for i, item in enumerate(self.lc_change_dic):
            # コードの１行を短くするため、置きかておく
            lc_exe = item['lc_change_exe']
            lc_ensure_range = item['lc_ensure_range']
            lc_trigger_range = item['lc_trigger_range']

            # このループで実行しない場合（フラグオフの場合、DoneがTrueの場合
            if not lc_exe or 'done' in item:
                # エクゼフラグがFalse、または、done(この項目は実行した時にのみ作成される)が存在している場合、「実行しない」
                continue

            # ボーダーラインを超えた場合
            if self.t_pl_u >= lc_trigger_range:
                # print("　★変更確定")
                print(" 変更対象", i, lc_ensure_range, lc_trigger_range, self.t_pl_u)
                # これで配列の中の辞書って変更できるっけ？？
                item['done'] = True
                new_lc_price = round(float(self.t_execution_price) + (lc_ensure_range * self.plan['ask_bid']), 3)
                data = {"stopLoss": {"price": str(new_lc_price), "timeInForce": "GTC"}, }
                res = self.oa.TradeCRCDO_exe(self.t_id, data)  # LCライン変更の実行
                if res['error'] == -1:
                    tk.line_send("    LC変更ミス＠lc_change")
                    return 0  # APIエラー時は終了
                item['lc_change_exe'] = False  # 実行後はFalseする（１回のみ）
                tk.line_send("　(LC底上げ)", self.name, self.t_pl_u, self.plan['lc_price'], "⇒", new_lc_price,
                             "Border:", lc_trigger_range, "保証", lc_ensure_range, "Posiprice", self.t_execution_price,
                             "予定価格", self.plan['price'])
                break


def error_end(info):
    print("  ★■★APIエラー発生")
    # print(" ")
    # sys.exit()  # 強制終了


def all_update_information(classes):
    """
    全ての情報を更新する
    :return:
    """
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

    return ans


def position_check(classes):
    """
    W、ターン未遂以外のオーダーが存在するかを確認する.
    :param classes:
    :return:
    """
    open_positions = []
    not_open_positions = []
    max_priority = 0
    max_position_time_sec = 0
    summary_diretcion = 1
    for item in classes:
        if item.t_state == "OPEN":
            print(" ★★★", item.t_id)
            open_positions.append({"name":item.name, "priority": item.priority})
            # 方向だけ取得（ポジションを持った時に、反対側のオーダーを消しあ
            if item.priority > max_priority:
                max_priority = item.priority  # ポジションの有る最大のプライオリティを取得する
            if item.t_time_past_sec > max_position_time_sec:
                max_position_time_sec = item.t_time_past_sec  # 何分間持たれているポジションか
        else:
            not_open_positions.append(item.name)
    # 結果の集約
    if len(open_positions) != 0 :
        ans = True  # ポジションが一つでもOpenになっている場合は、True
    else:
        ans = False

    return {
        "ans": ans,
        "open_positions": open_positions,
        "max_priority": max_priority,
        "max_position_time_sec": max_position_time_sec
    }


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
