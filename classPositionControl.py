import datetime
from datetime import timedelta

import classOanda
import tokens as tk
import fGeneric as gene
import classPosition as classPosition  # とりあえずの関数集


class position_control:
    """
    ポジションクラスをコントロースするためのもの
    """
    max_position_num = 10  # 最大でも10個のポジションしかもてないようにする
    is_live = True

    # 履歴ファイル
    def __init__(self, is_live):
        # 変数の宣言
        self.classes = []
        self.count_true = 0
        self.oa = classOanda.Oanda(tk.accountIDl, tk.access_tokenl, tk.environmentl)
        self.oa2 = classOanda.Oanda(tk.accountIDl2, tk.access_tokenl, tk.environmentl)

        # 処理
        for i in range(10):
            # 複数のクラスを動的に生成する。クラス名は「C＋通し番号」とする。
            # クラス名を確定し、クラスを生成する。
            new_name = "c" + str(i)
            self.classes.append(classPosition.order_information(new_name, is_live))  # 順思想のオーダーを入れるクラス
        self.print_classes_and_count()

    def print_classes_and_count(self):
        self.count_true = sum(1 for d in self.classes if hasattr(d, "life") and d.life)
        i = 0
        print(" 現在のクラスの状況(True:", self.count_true, ")")
        for item in self.classes:
            print(" ", i, "OaMode:", item.oa_mode, ",name:", item.name, ",life:", item.life)
            i = i + 1

    def order_class_add(self, order_classes):
        """
        調査結果を受け取り、他のオーダーを比較し、オーダーを追加するかを判定する
        """
        # ■オーダーのプライオリティの関係
        # 渡されたオーダーの中で、最大のプライオリティのものと、そのプライオリティを算出
        # max_dict = max(order_dic_list, key=lambda d: d["priority"], default=None)
        # max_dict = max(order_dic_list, key=lambda d: d.get("priority", float("-inf")))
        # order_max_priority = max_dict['priority']
        max_instance = max(order_classes, key=lambda x: x.exe_order["priority"])
        order_max_priority = max_instance.exe_order['priority']

        # 現在のクラスで、生きている物のみ抽出
        alive_classes = [c for c in self.classes if hasattr(c, "life") and c.life]
        if len(alive_classes) == 0:
            print(" プログラム上既存のオーダーは存在しないため、オーダー発行へ")
            pass
        else:
            # 生きているインスタンスの最高値と、指定のプライオリティより高いものを算出
            max_instance = max(alive_classes, key=lambda c: getattr(c, "priority", float("-inf")))
            over_n_classes = [c for c in alive_classes if hasattr(c, "priority") and c.priority > order_max_priority]
            same_n_classes = [c for c in alive_classes if hasattr(c, "priority") and c.priority == order_max_priority]

            if len(same_n_classes) > 2:
                # 新規と同レベルのオーダーが既に存在する場合、新規はスキップする（既存の物は消去しない）
                tk.line_send("同レベルのオーダーがあるため、追加オーダーせず", len(same_n_classes),"個のオーダー,",
                             order_max_priority, "のプライオリティ")
                return 0

        # ■現在のクラスの状況の確認
        print("現在のクラスの状況を確認 (classPositionControl)")
        self.print_classes_and_count()
        if self.count_true >= 10:
            # 10個以上オーダーがある場合はオーダーしない。
            print("★★既に10個以上オーダーがあるため、オーダー発行しない")
            return 0
        elif self.count_true + len(order_classes) >= 13:
            # 新規のオーダー合わせて13個以上になる場合もオーダーしない（新規オーダーがエラーで複数個出てる可能性のため）
            print("★★既存の物＋新規の合わせて13個以上になるため、オーダー発行しない(新規オーダー数:", len(order_classes))
            return 0

        # クラスに余りがある場合、その中で添え字が一番若いオーダーに上書き、または、追加をする
        line_send = ""
        for order_i, a_order in enumerate(order_classes):
            for class_index, each_exist_class in enumerate(self.classes):
                if each_exist_class.life:
                    # Trueの所には上書きしない
                    continue

                # Falseのとこで実行する
                res_dic = each_exist_class.order_plan_registration(a_order.exe_order)
                if res_dic['order_id'] == 0:
                    print("オーダー失敗している（大量オーダー等）")
                    line_send = line_send + "オーダー失敗(" + str(order_i) + ")" + "\n"
                else:
                    # ■オーダーが成功している場合
                    if res_dic['order_id'] == -1:
                        # ウォッチオーダー
                        print("オーダー通知")
                        # print(res_dic)
                        # line_sendは利確や損切の指定が無い場合はエラーになりそう（ただそんな状態は基本存在しない）
                        # TPrangeとLCrangeの表示は「inspection_result_dic」を参照している。
                        # print(res_dic['order_name'])
                        # print(res_dic)
                        line_send = line_send + "◆【" + str(res_dic['order_name']) + "】を即時ポジションなしで発行" + \
                                    "指定価格:【" + str(round(res_dic['order_result']['price'], 3)) + "】" + \
                                    ",DIR:" + str(res_dic['order_result']['direction']) + \
                                    ", 数量:" + str(res_dic['order_result']['units']) + \
                                    ", TP:" + str(round(res_dic['order_result']['tp_price'], 3)) + \
                                    "(" + str(round(res_dic['order_result']['tp_range'], 3)) + ")" + \
                                    ", LC:" + str(round(res_dic['order_result']['lc_price'], 3)) + \
                                    "(" + str(round(res_dic['order_result']['lc_range'], 3)) + ")" + \
                                    "[システム]classNo:" + str(class_index) + ",\n"
                        break
                    else:
                        # オーダーの生成完了をLINE通知する
                        print("オーダー通知", res_dic['order_name'])
                        print(res_dic)
                        o_trans = res_dic['order_result']['json']['orderCreateTransaction']  # 短縮のための変数化
                        line_send = line_send + "【" + str(res_dic['order_name']) + "】,\n" +\
                                    "指定価格:【" + str(res_dic['order_result']['price']) + "】"+\
                                    ", 数量:" + str(o_trans['units']) + \
                                    ", タイプ:" + a_order.ls_type + \
                                    ", TP:" + str(o_trans['takeProfitOnFill']['price']) + \
                                    "(" + str(round(abs(float(o_trans['takeProfitOnFill']['price']) - float(res_dic['order_result']['price'])), 3)) + ")" + \
                                    ", LC:" + str(o_trans['stopLossOnFill']['price']) + \
                                    "(" + str(round(abs(float(o_trans['stopLossOnFill']['price']) - float(res_dic['order_result']['price'])), 3)) + ")" + \
                                    ", OrderID:" + str(res_dic['order_id']) + \
                                    ", 取得価格:" + str(res_dic['order_result']['execution_price']) + "[システム]classNo:" + str(class_index) + ",\n"
                                    # "\n"
                        break
        return line_send

    def all_update_information(self):
        """
        全ての情報を更新する
        :return:
        """
        for item in self.classes:
            if item.life:
                item.update_information()

    def life_check(self):
        """
        オーダーが生きているかを確認する。一つでも生きていればＴｒｕｅを返す
        :return:
        """
        life = []
        unlife = []
        comment = ""
        for item in self.classes:
            if item.life:
                life.append(item)
                if item.t_state == "OPEN":
                    # print(item.name, "comment", comment, "lcStatus", item.lc_change_status)
                    comment = comment + "," + item.lc_change_status
            else:
                unlife.append(item)
        # 結果を集約する
        if len(life) == 0:
            ans = False  # 一つもLifeがOnでない。
        else:
            ans = True  # 一つでもLifeがある場合はＴｒｕｅ
            # print(" 残っているLIFE", life)

        return {"life_exist": ans, "one_line_comment": comment}

    def position_check(self):
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
        for item in self.classes:
            if item.life:  # lifeがTrueの場合、ポジションかオーダーが存在
                # 各情報
                if item.o_state == "Watching":
                    watching_list.append({"name": item.name,
                                          "target": item.plan_json['price'],
                                          "direction": item.plan_json['expected_direction'],
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
                        "realizedPL": item.t_json['realizedPL'],
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
                        tk.line_send(" 謎の状態　t_state=", item.t_state, ",o_state=", item.o_state, ", 名前:",
                                     item.name,
                                     ",life=", item.life, ",try_num", item.try_update_num, "回目　⇒再トライ")
                        item.count_up_position_check()  # 対象ポジションのtry_update_numをカウントアップする
                    else:
                        item.life_set(False)  # 強制的にクローズ
                        tk.line_send(" 謎の状態　t_state=", item.t_state, ",o_state=", item.o_state, ", 名前:",
                                     item.name,
                                     ",life=", item.life, ",try_num", item.try_update_num, "回目のため終了（lifeFalse)")
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

    def catch_up_position_and_del_order(self):
        """
        最初に実行される
        """
        res = self.oa2.OpenTrades_exe()
        if len(res['data']) == 0:
            return 0
        trades = res['json']['trades']
        print("trades", len(trades))
        print(trades)
        if len(trades) == 0:
            print("現状のポジションなし")
        else:
            # 既存のポジションをひとつづつ見ていく
            for i, exist_position_json in enumerate(trades):
                # クラスのスロットの空きをひとつづつ確認
                print("o,", exist_position_json)
                for class_index, each_exist_class in enumerate(self.classes):
                    if each_exist_class.life:
                        # Trueの所には上書きしない
                        continue
                    # Falseのところには代入して、
                    print(class_index)
                    each_exist_class.catch_exist_position(
                        "既存" + str(i),
                        2,
                        5,
                        exist_position_json)
                    break
        self.print_classes_and_count()


    def reset_all_position(self):
        print("  RESET ALL POSITIONS")
        # mainのオアンダクラスのオーダーを削除（API）
        # self.oa.OrderCancel_All_exe()
        # self.oa.TradeAllClose_exe()
        # 両建て用のオアンダクラスのオーダーの削除（API）
        self.oa2.OrderCancel_All_exe()
        self.oa2.TradeAllClose_exe()

        # プログラム内のクラスの整理
        self.all_update_information()  # 関数呼び出し（アップデート）
