import datetime
from datetime import timedelta

import classOanda
import tokens as tk
import fGeneric as gene
import classPosition as classPosition  # とりあえずの関数集
import classPositionForTest as testClassPosition


class position_control:
    """
    ポジションクラスをコントロースするためのもの
    """
    # 常に最新のデータを取得してクラス変数に入れておく（毎回の取得はしないように工夫する。（してもいい気もするけど））


    # 履歴ファイル
    def __init__(self, is_live):
        # 変数の宣言
        self.u = 3
        self.position_classes = []
        self.count_true = 0
        self.oa = classOanda.Oanda(tk.accountIDl, tk.access_tokenl, tk.environmentl)
        self.oa2 = classOanda.Oanda(tk.accountIDl2, tk.access_tokenl, tk.environmentl)

        self.peaks_class = ""  # クラスアップデートの時に利用する（ポジションクラスに引数として渡すため）

        # 最大所持個数の設定
        self.max_position_num = 15  # 最大でも10個のポジションしかもてないようにする
        self.middle_priority_num = 8  # ミドルプライオリティ(max_position_numのうち）
        self.high_priority_num = 1  # ハイプライオリティのもの（max_position_numのうち）

        self.high_i_to = self.max_position_num
        self.high_i_from = self.high_i_to - self.high_priority_num  # ハイプライオリティスロット(1つ限)の、添え字（最大5スロットの場合、添え字的には4番目スロット）
        self.mid_i_to = self.high_i_from  # python配列のTO指定は「未満」なので、ー１が不要。（以下の場合はマイナスが必要）
        self.mid_i_from = self.mid_i_to - self.middle_priority_num
        self.normal_i_to = self.mid_i_from
        self.normal_i_from = 0

        self.normal_priority_num = self.max_position_num - self.high_priority_num

        # 処理
        for i in range(self.max_position_num):
            # 複数のクラスを動的に生成する。クラス名は「C＋通し番号」とする。
            # クラス名を確定し、クラスを生成する。
            new_name = "c" + str(i)
            self.position_classes.append(classPosition.order_information(new_name, is_live))  # 順思想のオーダーを入れるクラス
        self.print_classes_and_count()

    def print_classes_and_count(self):
        self.count_true = sum(1 for d in self.position_classes if hasattr(d, "life") and d.life)
        i = 0
        print(" 現在のクラスの状況(True:", self.count_true, ")")
        for i, item in enumerate(self.position_classes):
            if self.high_i_from <= i < self.high_i_to:
                comment = "h"
            elif self.mid_i_from <= i < self.mid_i_to:
                comment = "m"
            else:
                comment = "n"
            print(" ", i, "OaMode:", item.oa_mode, "[", comment, "], Pno:", item.t_id, ",name:", item.name, ",life:", item.life)

        # テスト
        # allowed_position_slot = self.position_classes[self.mid_i_from:self.mid_i_to]
        # for i, item in enumerate(allowed_position_slot):
        #     print(" ", i, "OaMode:", item.oa_mode, "Pno:", item.t_id, ",name:", item.name, ",life:", item.life)

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
        if order_max_priority >=100:
            order_priority_class = "high"
            i_from = self.high_i_from
            i_to = self.high_i_to
        elif order_max_priority >= 10:
            order_priority_class = "mid"
            i_from = self.mid_i_from
            i_to = self.mid_i_to
        else:
            order_priority_class = "normal"
            i_from = self.normal_i_from
            i_to = self.normal_i_to
        allowed_position_slot = self.position_classes[i_from:i_to]  # もらったオーダーの優先度で、許可されたスロット(positionList)

        for i, order_class in enumerate(allowed_position_slot):
            print(" Allowed　", i, "OaMode:", order_class.oa_mode, ",name:", order_class.name, ",life:", order_class.life)
            i = i + 1

        # 現在のクラスで、生きている物のみ抽出
        alive_classes = [c for c in allowed_position_slot if hasattr(c, "life") and c.life]
        if len(alive_classes) == 0:
            print(" プログラム上既存のオーダーは存在しないため、オーダー発行へ")
            pass
        elif len(alive_classes) == len(allowed_position_slot):
            tk.line_send("許容スロットがいっぱい（オーダー発行せず)", len(alive_classes), len(allowed_position_slot))
            self.print_classes_and_count()
            return 0
        elif len(order_classes) + len(alive_classes) > len(allowed_position_slot):
            tk.line_send("オーダー入れるとオーバーフロー（オーダー発行せず)", len(order_classes), len(alive_classes), len(allowed_position_slot))
            self.print_classes_and_count()
            return 0
        else:
            # 生きているインスタンスの最高値と、指定のプライオリティより高いものを算出
            max_instance = max(alive_classes, key=lambda c: getattr(c, "priority", float("-inf")))
            over_n_classes = [c for c in alive_classes if hasattr(c, "priority") and c.priority > order_max_priority]
            same_n_classes = [c for c in alive_classes if hasattr(c, "priority") and c.priority == order_max_priority]

        # ■現在のクラスの状況の確認
        print("現在のクラスの状況を確認 (classPositionControl)")
        self.print_classes_and_count()
        # 通常のオーダーの場合
        # if self.count_true >= self.normal_priority_num:
        #     # 10個以上オーダーがある場合はオーダーしない。
        #     print("★★既に10個以上オーダーがあるため、オーダー発行しない")
        #     return 0
        # elif self.count_true + len(order_classes) > self.max_position_num:  # ２はテキトーな数字。
        #     # 新規のオーダー合わせて13個以上になる場合もオーダーしない（新規オーダーがエラーで複数個出てる可能性のため）
        #     print("★★既存の物＋新規の合わせて12個以上になるため、オーダー発行しない(新規オーダー数:", len(order_classes))
        #     return 0

        # クラスに余りがある場合、その中で添え字が一番若いオーダーに上書き、または、追加をする
        line_send = ""
        for order_i, order_class in enumerate(order_classes):
            for class_index, position_slot in enumerate(allowed_position_slot):
                if position_slot.life:
                    # Trueの所には上書きしない
                    continue
                if class_index == self.high_i_from:
                    # ハイクラス用の添え字の場所には、入れない
                    continue

                # Falseのとこで実行する
                res_dic = position_slot.order_plan_registration(order_class)
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
                                    "指定価格:【" + str(round(res_dic['order_result']['price'], self.u)) + "】" + \
                                    ",DIR:" + str(res_dic['order_result']['direction']) + \
                                    ", 数量:" + str(res_dic['order_result']['units']) + \
                                    ", TP:" + str(round(res_dic['order_result']['tp_price'], self.u)) + \
                                    "(" + str(round(res_dic['order_result']['tp_range'], self.u)) + ")" + \
                                    ", LC:" + str(round(res_dic['order_result']['lc_price'], self.u)) + \
                                    "(" + str(round(res_dic['order_result']['lc_range'], self.u)) + ")" + \
                                    ", AveMove:" + str(round(res_dic['ref']['move_ave'], self.u)) + \
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
                                    ", タイプ:" + order_class.ls_type + \
                                    ", TP:" + str(o_trans['takeProfitOnFill']['price']) + \
                                    "(" + str(round(abs(float(o_trans['takeProfitOnFill']['price']) - float(res_dic['order_result']['price'])), self.u)) + ")" + \
                                    ", LC:" + str(o_trans['stopLossOnFill']['price']) + \
                                    "(" + str(round(abs(float(o_trans['stopLossOnFill']['price']) - float(res_dic['order_result']['price'])), self.u)) + ")" + \
                                    ", AveMove:" + str(round(res_dic['ref']['move_ave'], self.u)) + \
                                    ", OrderID:" + str(res_dic['order_id']) + \
                                    ", 取得価格:" + str(res_dic['order_result']['execution_price']) + "[システム]classNo:" + str(class_index) + ",\n"
                                    # "\n"
                        break
        return line_send

    def all_update_information(self, candle_analysis_class=None):
        """
        全ての情報を更新する
        :return:
        """
        for item in self.position_classes:
            if item.life:
                item.update_information(candle_analysis_class)

        # # 関連オーダーの更新
        self.linkage_control()

    def life_check(self):
        """
        オーダーが生きているかを確認する。一つでも生きていればＴｒｕｅを返す
        :return:
        """
        life = []
        unlife = []
        comment = ""
        for item in self.position_classes:
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
        for item in self.position_classes:
            if item.life:  # lifeがTrueの場合、ポジションかオーダーが存在
                # 各情報
                if item.o_state == "Watching":
                    watching_list.append({"name": item.name,
                                          "target": item.plan_json['target_price'],
                                          "direction": item.plan_json['direction'],
                                          "order_time": gene.time_to_str(item.order_register_time),
                                          "state": item.step1_filled,
                                          "keeping": round(item.step1_keeping_second, 0),
                                          })
                    continue
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
                        "direction": item.plan_json['direction'],
                        "t_time_past_sec": item.t_time_past_sec
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
                for class_index, each_exist_class in enumerate(self.position_classes):
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
        # self.oa2.TradeAllClose_exe()

        # プログラム内のクラスの整理
        self.all_update_information()  # 関数呼び出し（アップデート）

    def linkage_control(self):
        """
        終わってしまったポジションから、残っているポジションを変えに行く、という方向。
        """
        margin = 0.01
        lc_range = 0.03

        # print("PositionControlのリンケージセクション", len(self.position_classes))
        for main_position in self.position_classes:

            # print("★★", main_position.name, "のリンケージ残存を確認")
            if main_position.linkage_done:
                # print(main_position.name, " リンケージ調整済み(相手側を調整した,またはされた）")
                continue
            elif main_position.life and main_position.t_state == "OPEN":
                # print(main_position.name, " まだ自分がポジション所持中のため、処理しない", main_position.life, main_position.t_state)
                continue
            elif main_position.life and main_position.o_state == "PENDING":
                # print(main_position.name, " まだ自分がオーダー状態(ポジション前）のため、処理しない")
                continue
            elif not main_position.life and main_position.t_state == "":
                continue
            elif main_position.o_json:  # この条件は、テストモードでおかしなことが起きるために追加した（本番悪影響なら消したい）
                # print(main_position.o_json)
                if main_position.o_json['state'] == "PENDING":
                    continue

            # elifだと通過してしまう（上のどれかに引っかかってしまっている）ため、独立して記述（o_jsonで引っ掛かってる？）
            if main_position.o_state == "Watching":
                continue

            # これ正しい？
            if not main_position.life and main_position.t_state == "CLOSED" and not main_position.linkage_done:
                # ★クローズした初回のみ実施！！！？　フラグはここで建てておく。
                print("★★初回リンケージチェック", main_position.name, main_position.t_realize_pl)
                main_position.linkage_done_func()


            #　自身がの勝敗によって、Linkageをするかどうか
            print("       確認用position control", main_position.t_realize_pl)
            if float(main_position.t_realize_pl) >= 0:
                pass
                print("自身はプラス", main_position.name, main_position.t_realize_pl, main_position.o_state)
            else:
                print("自身はマイナス", main_position.name, main_position.t_realize_pl, main_position.o_state)
                # continue

            # 走査する
            if hasattr(main_position, "order_class"):
                if hasattr(main_position.order_class, "linkage_order_classes"):
                    print("  ", main_position.name, "のリンケージ")
                    if len(main_position.order_class.linkage_order_classes) == 0:
                        print("    linkage登録数０")
                        continue
                else:
                    print("    linkageのインスタンス変数なし")
                    continue

                # 本処理(残されたリンケージオーダーへの対応）
                for i, linkage_class in enumerate(main_position.linkage_order_classes):
                    left_position = next((obj for obj in self.position_classes if obj.name == linkage_class.name), None)
                    if left_position is None:
                        print("     レフトポジションがNone")
                    print("    ", linkage_class.name, "のオーダーが対象", left_position.life, left_position.t_pl_u)
                    if left_position is None:
                        print("    ", linkage_class.name, "のリンケージオーダー[", linkage_class.name, "]が対象だが見つからない")
                        # tk.line_send("リンケージ先がない物があった.", linkage_class.name, "のリンケージ", linkage_class.name)
                        main_position.linkage_done_func()  # 自身のリンケージも終了
                        continue
                    # 自分自身はポジションあるが、相手がクローズしてしまっている場合
                    if left_position.linkage_done:
                        # 既に残された側が、
                        print("     ", left_position.name, " 既にリンケージ調整され済み", )
                        continue

                    # メインの種類によって、場合分け？？
                    # (1)メインが、ヘッジ用（負けるか確認のやつ）の場合
                    if "シンプルターン_r" in main_position.name:
                        print("     rによるリンケージ操作", main_position.name, main_position.linkage_done, main_position.t_state, main_position.t_realize_pl, left_position.t_state)
                        if float(main_position.t_realize_pl) >= 0:
                            # プラス域の場合は、問答無用で相手をキャンセルする。

                            # 相手がまだオーダーの場合、オーダーをクローズする (自分の利確の分をLCにして継続するのもありかも）
                            if left_position.t_state == "" and left_position.o_state == "PENDING":
                                # print(" まだlinage先のポジションが成立していないため、オーダー解除")
                                left_position.close_order()
                                main_position.linkage_done_func()  # 自身のリンケージも終了
                                continue

                            # 相手がポジションの場合、クローズする
                            if left_position.life and left_position.t_state == "OPEN":
                                # 相方のポジションがまだある場合（毎なるポジションが想定される）
                                left_position.close_trade(None)
                                main_position.linkage_done_func()
                                continue
                        else:
                            # 相手がまだオーダーの場合、オーダーをクローズする (自分の利確の分をLCにして継続するのもありかも）
                            if left_position.t_state == "" and left_position.o_state == "PENDING":
                                print(" まだlinage先のポジションが成立していないため、オーダー解除")
                                left_position.close_order()
                                main_position.linkage_done_func()  # 自身のリンケージも終了
                                continue
                            # 相手がポジションの場合、プラスが予想される。自身がマイナスなので、相方のマイナス突入は死守。
                            if left_position.life and left_position.t_state == "OPEN":
                                left_position_take_price = left_position.plan_json['target_price']
                                tk.line_send("classPosition477テスト", left_position_take_price)
                                print("     残りポジションのTargetPrice", left_position.name, left_position_take_price, left_position_dir)
                                left_position_dir = left_position.plan_json['direction']
                                new_lc_price = left_position_take_price
                                if left_position_dir == 1:
                                    new_lc_price = new_lc_price - 0.001  # -正の値で、ロスカを広げる
                                else:
                                    new_lc_price = new_lc_price + 0.001  # -正の値で、ロスカを広げる
                                left_position.linkage_lc_change(new_lc_price)
                                main_position.linkage_done_func()

                    elif "シンプルターン" in main_position.name:
                        print("     シンプルターンによるリンケージ操作", main_position.name, ",", main_position.t_state, ",",main_position.t_realize_pl, ",",left_position.t_state)
                        # 相手がポジションの場合、プラスが予想される。自身がマイナスなので、相方のマイナス突入は死守。
                        if left_position.life and left_position.t_state == "OPEN":
                            left_position_take_price = left_position.plan_json['target_price']
                            tk.line_send("classPosition488テスト", left_position_take_price)
                            print("     残りポジションのTargetPrice", left_position.name, left_position_take_price)
                            new_lc_price = left_position_take_price
                            left_position.linkage_lc_change(new_lc_price)
                            main_position.linkage_done_func()
                        if left_position.t_state == "" and left_position.o_state == "PENDING":
                            # print(" まだlinage先のポジションが成立していないため、オーダー解除")
                            left_position.close_order()
                            main_position.linkage_done_func()  # 自身のリンケージも終了
                            continue
                    elif "rシンプルターン" in main_position.name:
                        print("    rシンプルターン_rが先に終了。rシンプルターンも終わらせないと？？")
                        # 利確してるときは、確実に終了させる　または、　少しでもマイナスが少ないようにする
                        if left_position.life and left_position.t_state == "OPEN":
                            left_position_take_price = left_position.plan_json['target_price']
                            tk.line_send("classPosition521テスト", left_position_take_price)

                    # if main_position.o_state == "CANCELLED":
                    #     # オーダーが時間切れ等でキャンセルした場合。
                    #     main_position.linkage_done_func()
                    #     left_pl_u = float(left_position.t_pl_u)  # 現在のプラマイ
                    #     if left_pl_u >= 0:
                    #         # 残されたオーダーがプラス域の場合（ほとんどないが、０の場合はOrder時間切れキャンセルの可能性←やられた）
                    #         pass
                    #     else:
                    #         # 残されたオーダーがマイナス域の場合（こっちがメインのケース）
                    #         new_lc_range = abs(lc_range) + margin
                    #         dir = int(left_position.plan_json['direction'])
                    #         # tk.line_send("    LC変更kakumin", main_position.lose_max_plu, left_position.t_pl_u, bigger_minus)
                    #         print("       計算要素", dir, new_lc_range, float(left_position.t_pl_u))
                    #         new_lc_price = float(left_position.t_execution_price) - (dir * new_lc_range)
                    #         print("       new_lc_price", new_lc_price, float(left_position.t_execution_price))
                    #         left_position.linkage_lc_change(new_lc_price)
                    #         # tk.line_send("オーダー時間切れキャンセル発生＆Linkage先あり@", main_position.name, new_lc_price, left_position.name)
                    #
                    # # パート２　ここからは下はいったん無視(同条件で、上にContinueあり）、、かな
                    # if left_position.life and left_position.t_state == "OPEN":
                    #     main_position.linkage_done_func()  # リンケージが単数前提の場合、ここでリンケージ機能をクローズしてしまう
                    #     # print("      相手のPL情報", left_position.t_pl_u)
                    #     # print("      自分の現在の状況", main_position.t_pl_u, main_position.plan_json['lc_price'])
                    #     # print("         ", main_position.t_execution_price)
                    #     # new_lc_range = abs(float(left_position.t_pl_u)) + 0.02
                    #     # dir = int(left_position.plan_json['direction'])
                    #     # print("       計算要素", dir, new_lc_range, float(left_position.t_pl_u))
                    #     # new_lc_price = float(left_position.t_execution_price) - (dir * new_lc_range)
                    #     # print("       new_lc_price", new_lc_price, float(left_position.t_execution_price))
                    #     # left_position.linkage_lc_change(new_lc_price)
                    #     #
                    #     # # TPも変更する？プラス域であきらめ？(memo)
                    #     # new_tp_range = abs(float(left_position.t_pl_u)) * 0.5  # 半分
                    #     # current_price = float(left_position.t_execution_price) + float(left_position.t_pl_u)
                    #     # price = current_price  # 現在価格基準を利用する場合、これをコメントイン(現マイナスの半分、等の指定がしやすい
                    #     # # price = left_position.t_execution_price  # 約定価格を利用する場合これをコメントイン
                    #     # if left_position.plan_json['direction'] == 1:
                    #     #     # 約定価格を基にした、利確価格変更
                    #     #     new_tp_price = price + new_tp_range
                    #     # else:
                    #     #     new_tp_price = price - new_tp_range
                    #     # print("       TP:計算要素", new_tp_range, float(left_position.t_pl_u), new_tp_price)
                    #     # left_position.linkage_tp_change(new_tp_price)
                    #
                    #     # プラス域かマイナス域で判定を変更する
                    #     left_pl_u = float(left_position.t_pl_u)  # 現在のプラマイ
                    #     if left_pl_u >= 0:
                    #         # 残されたオーダーがプラス域の場合（ほとんどないが、０の場合はOrder時間切れキャンセルの可能性←やられた）
                    #         pass
                    #     else:
                    #         # 残されたオーダーがマイナス域の場合（こっちがメインのケース）
                    #         bigger_minus = min(float(main_position.lose_max_plu), float(left_position.t_pl_u))
                    #         new_lc_range = abs(bigger_minus) + margin
                    #         dir = int(left_position.plan_json['direction'])
                    #         # tk.line_send("    LC変更kakumin", main_position.lose_max_plu, left_position.t_pl_u, bigger_minus)
                    #         print("       計算要素", dir, new_lc_range, float(left_position.t_pl_u))
                    #         new_lc_price = float(left_position.t_execution_price) - (dir * new_lc_range)
                    #         print("       new_lc_price", new_lc_price, float(left_position.t_execution_price))
                    #         left_position.linkage_lc_change(new_lc_price)
                    #
                    #         # lc_Change_Candleにする
                    #         # print(main_position.t_json)
                    #         # gene.print_json(main_position.o_json)
                    #         # gene.print_json(main_position.t_json)
                    #         print("　　　　自身（先に解消したほう）の利益range", main_position.t_json['PLu'])
                    #         if main_position.t_json['PLu'] >= 0:
                    #             print("    自身がプラスの場合、そのプラスを最大限に生かしたLCChangeを行う")
                    #             left_position.linkage_forced_lc_change_setting(main_position.t_json['PLu'], left_pl_u)
                    #         else:
                    #             print("     自身がマイナス終了のため、どうしようか考える")
            else:
                pass
                print("オーダークラスがない！！！⇒未発行とかそこらへん")


class position_control_for_test(position_control):
    def __init__(self, is_live, filename):
        # 変数の宣言
        print("test用　positioncontorol")
        self.position_classes = []
        self.count_true = 0
        self.oa = classOanda.Oanda(tk.accountIDl, tk.access_tokenl, tk.environmentl)
        self.oa2 = classOanda.Oanda(tk.accountIDl2, tk.access_tokenl, tk.environmentl)
        self.filename = filename
        # self.temp_file_name = memo

        # 最大所持個数の設定
        self.max_position_num = 25  # 最大でも10個のポジションしかもてないようにする
        self.middle_priority_num = 8  # ミドルプライオリティ(max_position_numのうち）
        self.high_priority_num = 1  # ハイプライオリティのもの（max_position_numのうち）

        self.high_i_to = self.max_position_num
        self.high_i_from = self.high_i_to - self.high_priority_num  # ハイプライオリティスロット(1つ限)の、添え字（最大5スロットの場合、添え字的には4番目スロット）
        self.mid_i_to = self.high_i_from  # python配列のTO指定は「未満」なので、ー１が不要。（以下の場合はマイナスが必要）
        self.mid_i_from = self.mid_i_to - self.middle_priority_num
        self.normal_i_to = self.mid_i_from
        self.normal_i_from = 0

        self.normal_priority_num = self.max_position_num - self.high_priority_num

        # 処理
        for i in range(self.max_position_num):
            # 複数のクラスを動的に生成する。クラス名は「C＋通し番号」とする。
            # クラス名を確定し、クラスを生成する。
            new_name = "c" + str(i)
            self.position_classes.append(testClassPosition.order_information(new_name, is_live, filename))  # 順思想のオーダーを入れるクラス
        self.print_classes_and_count()

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
        if order_max_priority >=100:
            order_priority_class = "high"
            i_from = self.high_i_from
            i_to = self.high_i_to
        elif order_max_priority >= 10:
            order_priority_class = "mid"
            i_from = self.mid_i_from
            i_to = self.mid_i_to
        else:
            order_priority_class = "normal"
            i_from = self.normal_i_from
            i_to = self.normal_i_to
        allowed_position_slot = self.position_classes[i_from:i_to]  # もらったオーダーの優先度で、許可されたスロット(positionList)

        for i, order_class in enumerate(allowed_position_slot):
            print(" Allowed　", i, "OaMode:", order_class.oa_mode, ",name:", order_class.name, ",life:", order_class.life)
            i = i + 1

        # 現在のクラスで、生きている物のみ抽出
        alive_classes = [c for c in allowed_position_slot if hasattr(c, "life") and c.life]
        if len(alive_classes) == 0:
            print(" プログラム上既存のオーダーは存在しないため、オーダー発行へ")
            pass
        elif len(alive_classes) == len(allowed_position_slot):
            # tk.line_send("許容スロットがいっぱい（オーダー発行せず)", len(alive_classes), len(allowed_position_slot))
            self.print_classes_and_count()
            return 0
        elif len(order_classes) + len(alive_classes) > len(allowed_position_slot):
            # tk.line_send("オーダー入れるとオーバーフロー（オーダー発行せず)", len(order_classes), len(alive_classes), len(allowed_position_slot))
            self.print_classes_and_count()
            return 0
        else:
            # 生きているインスタンスの最高値と、指定のプライオリティより高いものを算出
            max_instance = max(alive_classes, key=lambda c: getattr(c, "priority", float("-inf")))
            over_n_classes = [c for c in alive_classes if hasattr(c, "priority") and c.priority > order_max_priority]
            same_n_classes = [c for c in alive_classes if hasattr(c, "priority") and c.priority == order_max_priority]


        # ■現在のクラスの状況の確認
        print("現在のクラスの状況を確認 (classPositionControl)")
        self.print_classes_and_count()

        # クラスに余りがある場合、その中で添え字が一番若いオーダーに上書き、または、追加をする
        line_send = ""
        for order_i, order_class in enumerate(order_classes):
            for class_index, position_slot in enumerate(allowed_position_slot):
                if position_slot.life:
                    # Trueの所には上書きしない
                    continue
                if class_index == self.high_i_from:
                    # ハイクラス用の添え字の場所には、入れない
                    continue

                # Falseのとこで実行する
                res_dic = position_slot.order_plan_registration(order_class)
                break
                # if res_dic['order_id'] == 0:
                #     print("オーダー失敗している（大量オーダー等）")
                #     line_send = line_send + "オーダー失敗(" + str(order_i) + ")" + "\n"
                # else:
                #     # ■オーダーが成功している場合
                #     if res_dic['order_id'] == -1:
                #         # ウォッチオーダー
                #         print("オーダー通知")
                #         # print(res_dic)
                #         # line_sendは利確や損切の指定が無い場合はエラーになりそう（ただそんな状態は基本存在しない）
                #         # TPrangeとLCrangeの表示は「inspection_result_dic」を参照している。
                #         # print(res_dic['order_name'])
                #         # print(res_dic)
                #         line_send = line_send + "◆【" + str(res_dic['order_name']) + "】を即時ポジションなしで発行" + \
                #                     "指定価格:【" + str(round(res_dic['order_result']['price'], 3)) + "】" + \
                #                     ",DIR:" + str(res_dic['order_result']['direction']) + \
                #                     ", 数量:" + str(res_dic['order_result']['units']) + \
                #                     ", TP:" + str(round(res_dic['order_result']['tp_price'], 3)) + \
                #                     "(" + str(round(res_dic['order_result']['tp_range'], 3)) + ")" + \
                #                     ", LC:" + str(round(res_dic['order_result']['lc_price'], 3)) + \
                #                     "(" + str(round(res_dic['order_result']['lc_range'], 3)) + ")" + \
                #                     ", AveMove:" + str(round(res_dic['ref']['move_ave'], 3)) + \
                #                     "[システム]classNo:" + str(class_index) + ",\n"
                #         break
                #     else:
                #         # オーダーの生成完了をLINE通知する
                #         print("オーダー通知", res_dic['order_name'])
                #         print(res_dic)
                #         o_trans = res_dic['order_result']['json']['orderCreateTransaction']  # 短縮のための変数化
                #         line_send = line_send + "【" + str(res_dic['order_name']) + "】,\n" +\
                #                     "指定価格:【" + str(res_dic['order_result']['price']) + "】"+\
                #                     ", 数量:" + str(o_trans['units']) + \
                #                     ", タイプ:" + order_class.ls_type + \
                #                     ", TP:" + str(o_trans['takeProfitOnFill']['price']) + \
                #                     "(" + str(round(abs(float(o_trans['takeProfitOnFill']['price']) - float(res_dic['order_result']['price'])), 3)) + ")" + \
                #                     ", LC:" + str(o_trans['stopLossOnFill']['price']) + \
                #                     "(" + str(round(abs(float(o_trans['stopLossOnFill']['price']) - float(res_dic['order_result']['price'])), 3)) + ")" + \
                #                     ", AveMove:" + str(round(res_dic['ref']['move_ave'], 3)) + \
                #                     ", OrderID:" + str(res_dic['order_id']) + \
                #                     ", 取得価格:" + str(res_dic['order_result']['execution_price']) + "[システム]classNo:" + str(class_index) + ",\n"
                #                     # "\n"
                #         break
        return line_send

    def all_update_information(self, df_row, candle_analysis_class):
        """
        全ての情報を更新する
        :return:
        """
        for item in self.position_classes:
            if item.life:
                item.update_information(df_row, candle_analysis_class)

        # # 関連オーダーの更新
        self.linkage_control()

    def reset_all_position(self, df_row):
        print("  RESET ALL POSITIONS")
        # mainのオアンダクラスのオーダーを削除（API）
        # self.oa.OrderCancel_All_exe()
        # self.oa.TradeAllClose_exe()
        # 両建て用のオアンダクラスのオーダーの削除（API）
        self.oa2.OrderCancel_All_exe()
        # self.oa2.TradeAllClose_exe()

        # プログラム内のクラスの整理
        self.all_update_information(df_row)  # 関数呼び出し（アップデート）