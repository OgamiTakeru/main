import datetime
from datetime import timedelta

import classOanda
import tokens as tk
import fGeneric as gene
import gc
import fCommonFunction as cf
import sys
import fGeneric as f
import copy
import fBlockInspection as fTurn


class OrderCreateClass:
    basic_unit = 10000
    # basic_unit = 25000
    oa = None

    def __init__(self, order_json):
        """
        処理解説
        インスタンスを生成すると、現在価格等を取得するため、OandaClassも生成する
        また、以下の情報を受け取り、ファイナライズを実施する。

        最低限必要な情報
        order_base_dic = {
            "target": 0.00,  # 価格(80以上の値) or Range で正の値。Rangeの場合、decision_priceを基準にPrice(APIに必須）に換算される。
            "type": "STOP",  # 文字列。計算時は数字のほうが楽なため、stop_or_limit変数で数字に置き換えたものも算出（finalize関数)
            "units": OrderCreateClass.basic_unit,
            "expected_direction": 1,
            "tp": 0.9,  # 80以上の値は価格とみなし、それ以外ならRange(target価格+tpRange。正の値）とする
            "lc": 0.03,  # 80以上の値は価格とみなし、それ以外ならRange(target価格+lcRange。正の値）とする
            'priority': 0,
            "decision_price": 0,  # "Now"という文字列の場合、この関数で即時取得する。targetがRangeの場合必須。
            "decision_time": "",
            "name": "",
            "order_timeout_min": 0,
        }

        生成される情報(order_baseをorder_finalize関数に入れると、以下が生成される）
        finalized_order = {
            "units": 1000, #【Order必須】
            "stop_or_limit": stop_or_limit,  # 計算に便利な数字形式で１か-1で表現（1=STOP）。☆
            "type": "STOP" or "LIMIT",  # 【Order必須】 ☆　　(☆はどちらか一つあれば、この関数で両方を算出）
            "expected_direction":  # プログラム用
            "decision_time":  # プログラム用
            "decision_price":  # プログラム用
            "position_margin":  # プログラム用
            "target_price":  # プログラム用
            "lc_range":  # プログラム用
            "tp_range":  # プログラム用
            "tp_price":  # プログラム用
            "lc_price":  # プログラム用
            "direction",  # classOandaでask_bidという変数名に置換して利用。この値でTargetPriceやLCPriceを算出する。
            "price":,  # 【Order必須】この関数でtarget_priceを基に計算される。
            "trade_timeout_min,　# プログラム用
            "order_permission",　# プログラム用
            "priority",  # プログラム用
            "lc_change": [
                 {"exe": True, "time_after": 60, "trigger": 0.05, "ensure": 0.04},
            ],  　# プログラム用
        }

        最終的にAPIに流すJson
        data = {  # オーダーのテンプレート！（一応書いておく）
            "order": {
                "instrument": "USD_JPY",　　# ←これはclassOandaで直接入れちゃっている
                "units": "10",
                "type": "",  # "STOP(逆指)" or "LIMIT"
                "positionFill": "DEFAULT",
                "price": "150",  # USD/JPYの場合、小数点下三桁までの「文字列」。指値の時に必要。成り行き時は入力不要
                "stopLossOnFill": {
                    "price": "151",
                    "timeInForce": "GTC"
                },
                "takeProfitOnFill": {
                    "price": "149",
                    "timeInForce" : "GTC"
                },
                "trailingStopLossOnFill": {
                    "distance": "0.05",  # 0.05以上の文字列
                    "timeInForce": "GTC"
                }
            }
        }
        """
        self.order_base = order_json  # 受け取る際の簡易的な情報（オーダーキック用）
        self.finalized_order = {}  # 最終的にAPIに渡される部分
        self.finalized_order_without_lc_change = {}

        if OrderCreateClass.oa is None:
            # print("OrderCreateClassで新規Oaクラスの生成を実施（初回のみのはず）")
            OrderCreateClass.oa = classOanda.Oanda(tk.accountIDl, tk.access_tokenl, "live")  # クラス変数の必要あり？
        else:
            pass
            # print(" 既にオーダークラスは一度生成済み（参照するため、逆にメモリ大丈夫か・・・？）")

        # 情報に不足がないかの確認
        print("targetなし。その場合、targetPriceが必要です。") if "target" not in order_json else None
        print("typeがありません") if "type" not in order_json else None
        print("expected_directionがありません") if "expected_direction" not in order_json else None
        print("lcがありません") if "lc" not in order_json else None
        print("tpがありません") if "tp" not in order_json else None
        print("decision_timeがありません") if "decision_time" not in order_json else None
        print("decision_priceがありません。この場合targetがマージンを示す場合、基準がないため利用できません。") if "decision_price" not in order_json else None
        print("priorityがありません") if "priority" not in order_json else None
        # print("decision_priceがありません（なければここで入れます）") if "decision_price" not in order_json else None

        # ref情報（なくてもかまわない、オーダーの基礎になりそうな参考情報）
        # 現状、LCChangeのもとになる数字を取得するのに利用
        self.move_ave = 0  # 最初のLCChangeの値(一番最初は、平均変動を利用したい）
        self.peak1_target_gap = 0
        # print("classOrderCreate 114", order_json['ref'])
        if "ref" in order_json:
            # 参考となる数字がインプットされている場合
            if "move_ave" in order_json['ref']:
                self.move_ave = order_json['ref']['move_ave']
            if "peak1_target_gap" in order_json['ref']:
                self.peak1_target_gap = order_json['ref']["peak1_target_gap"]

        # Unitsがない場合は初期値を入れる
        if "units" in order_json:
            if order_json['units'] == 1:
                # unit指定が１の場合は、基本値を入れる
                self.order_base["units"] = self.basic_unit
            elif order_json['units'] <= 100:
                # 100以下の数字は倍率とみなす
                self.order_base["units"] = self.basic_unit * order_json['units']
            else:
                # 直接の指定と判断
                self.order_base["units"] = self.order_base["units"]
        else:
            # print("Unit指定がないため、Unitsを基本のものを入れておく")
            self.order_base["units"] = self.basic_unit

        # 情報を取得する（場合によって）
        if "decision_price" not in order_json or self.order_base["decision_price"] == "Now":
            # decision_priceはなければ(または明示的にNowが指定してくれている場合）ここで追加する
            # print("decision_priceを追加しました")
            self.order_base["decision_price"] = self.get_now_mid_price()

        # オーダーをファイナライズする(finalizedのオーダーは別の変数に入れる）
        self.finalized_order = self.order_finalize()

        # 解析用のデータを取得する（とりあえずないと途中でエラーになるので）
        self.finalized_order['for_inspection_dic'] = {}

        # LC_Changeを付与する 検証環境の都合で、必須。(finalizedに直接追加）
        # lc_changeは数字か辞書が入る。辞書の場合、lc_changeの先頭にそれが入る
        # self.finalized_order['lc_change'] = [] # 初期化
        if "lc_change_type" not in order_json:
            # typeしていない場合はノーマルを追加
            self.add_lc_change_defence()
        else:
            if isinstance(order_json['lc_change_type'], int):
                # print("処理A: int型です", order_json['lc_change_type'])
                # 指定されている場合は、指定のLC_Change処理へ
                if order_json['lc_change_type'] == 1:
                    self.add_lc_change_defence()
                elif order_json['lc_change_type'] == 0:
                    self.add_lc_change_no_change()
                elif order_json['lc_change_type'] == 3:
                    self.add_lc_change_offence()
                elif order_json['lc_change_type'] == 4:
                    self.add_lc_change_after_lc()
            else:
                self.add_lc_change_start_with_dic(order_json['lc_change_type'])

        # 表示用
        self.finalized_order_without_lc_change = copy.deepcopy(self.finalized_order)
        self.finalized_order_without_lc_change.pop("lc_change", None)  # キーがなければ None を返す

    def get_now_mid_price(self):
        """
        各関数の行数削減（特にエラー対応）のため、関数に出す
        ・とりあえずミドル価格を返す
        ・エラーの場合、このループをおしまいにする？それともっぽい値を返却する？
        """
        price_dic = self.oa.NowPrice_exe("USD_JPY")
        if price_dic['error'] == -1:  # APIエラーの場合はスキップ
            print("      API異常発生の可能性")
            return -1  # 終了
        else:
            price_dic = price_dic['data']
        return price_dic['mid']

    def add_lc_change_no_change(self):
        """
        lcChange = 0で選ばれるもの
        形式的に入れたもの（形式的に入れないとエラーになるので）
        ほぼ到達しない１円を入れておく
        """
        self.finalized_order['lc_change'] = [
            {"exe": True, "time_after": 0, "trigger": 1, "ensure": 1},
        ]

    def add_lc_change_offence(self):
        """
        lcChange = 3で選ばれるもの
        実際の運用をイメージ
        ・最初の30分はlc_1.3程度をトリガーにしてLC分を確実に回収できるように
        　（一度20pips位上がった後に、LCまで戻っており、悔しかった。上がるのは大体直前
        ・30分以降は、ローソク形状の効果が切れたとみなし、プラスにいる場合はとにかく利確に向けた動きをする
        """
        # 動き代を基にする
        # first_trigger = 0.025
        # first_ensure = round(first_trigger - self.move_ave, 3)
        first_ensure = 0.01
        first_trigger = round(first_ensure + (self.move_ave * 1), 3)

        # 動きを基にする　パート２
        first_ensure = self.peak1_target_gap
        first_trigger = round(first_ensure + (self.move_ave * 0.5), 3)

        # 動きを基にする　パート２
        first_ensure = self.move_ave * 2.0
        first_trigger = self.move_ave * 2.2

        self.finalized_order['lc_change'] = [
            # {"exe": True, "time_after": 0, "trigger": 1, "ensure": 1},
            # {"exe": True, "time_after": 600, "trigger": 0.025, "ensure": 0.005},
            {"exe": True, "time_after": 600, "trigger": 0.04, "ensure": -0.02},
            {"exe": True, "time_after": 600, "trigger": 0.06, "ensure": 0.01},
            # {"exe": True, "time_after": 600, "trigger": first_trigger, "ensure": first_ensure},
            {"exe": True, "time_after": 600, "trigger": 0.08, "ensure": 0.02},
            {"exe": True, "time_after": 0, "trigger": 0.20, "ensure": 0.15},
            {"exe": True, "time_after": 600, "trigger": 0.40, "ensure": 0.35},
            {"exe": True, "time_after": 2 * 5 * 60, "trigger": 0.60, "ensure": 0.55},
            {"exe": True, "time_after": 2 * 5 * 60, "trigger": 0.70, "ensure": 0.65},
            {"exe": True, "time_after": 2 * 5 * 60, "trigger": 0.80, "ensure": 0.75},
            {"exe": True, "time_after": 2 * 5 * 60, "trigger": 0.90, "ensure": 0.85},
            {"exe": True, "time_after": 2 * 5 * 60, "trigger": 1.00, "ensure": 0.95},
        ]

    def add_lc_change_start_with_dic(self, dic_arr):
        """
        lcChange = 3で選ばれるもの
        実際の運用をイメージ
        ・最初の30分はlc_1.3程度をトリガーにしてLC分を確実に回収できるように
        　（一度20pips位上がった後に、LCまで戻っており、悔しかった。上がるのは大体直前
        ・30分以降は、ローソク形状の効果が切れたとみなし、プラスにいる場合はとにかく利確に向けた動きをする
        """
        # 動き代を基にする
        # first_trigger = 0.025
        # first_ensure = round(first_trigger - self.move_ave, 3)
        first_ensure = 0.01
        first_trigger = round(first_ensure + (self.move_ave * 1), 3)

        # 動きを基にする　パート２
        first_ensure = self.peak1_target_gap
        first_trigger = round(first_ensure + (self.move_ave * 0.5), 3)

        # 動きを基にする　パート２
        first_ensure = self.move_ave * 2.0
        first_trigger = self.move_ave * 2.2
        print("特殊LCChange")

        add = [
            # {"exe": True, "time_after": 0, "trigger": 1, "ensure": 1},
            # {"exe": True, "time_after": 600, "trigger": 0.025, "ensure": 0.005},
            # {"exe": True, "time_after": 0, "trigger": 0.04, "ensure": 0.010},
            # {"exe": True, "time_after": 600, "trigger": first_trigger, "ensure": first_ensure},
            # {"exe": True, "time_after": 0, "trigger": 0.08, "ensure": 0.05},
            {"exe": True, "time_after": 0, "trigger": 0.20, "ensure": 0.15},
            {"exe": True, "time_after": 600, "trigger": 0.40, "ensure": 0.35},
            {"exe": True, "time_after": 2 * 5 * 60, "trigger": 0.60, "ensure": 0.55},
            {"exe": True, "time_after": 2 * 5 * 60, "trigger": 0.70, "ensure": 0.65},
            {"exe": True, "time_after": 2 * 5 * 60, "trigger": 0.80, "ensure": 0.75},
            {"exe": True, "time_after": 2 * 5 * 60, "trigger": 0.90, "ensure": 0.85},
            {"exe": True, "time_after": 2 * 5 * 60, "trigger": 1.00, "ensure": 0.95},
        ]
        print("LCCHange", dic_arr)
        print("lCCHANE", add)
        self.finalized_order['lc_change'] = dic_arr + add

    def add_lc_change_after_lc(self):
        """
        lcChange = 4で選ばれるもの
        実際の運用をイメージ
        ・LCの取引の後は、そのLCを取り返す動きをする
        """
        lc = self.finalized_order['lc_range']
        self.finalized_order['lc_change'] = [
            {"exe": True, "time_after": 0, "trigger": round(lc * 1.1, 3), "ensure": round(lc * 0.8, 3)},
            {"exe": True, "time_after": 1200, "trigger": 0.018, "ensure": -0.01},
            {"exe": True, "time_after": 1200, "trigger": 0.043, "ensure": 0.021},
            {"exe": True, "time_after": 1200, "trigger": 0.08, "ensure": 0.06},
            # # {"exe": True, "time_after": 0, "trigger": 0.08, "ensure": 0.06},
            # {"exe": True, "time_after": 0, "trigger": 0.10, "ensure": 0.084},
            # # {"exe": True, "time_after": 0, "trigger": 0.12, "ensure": 0.10},
            # # {"exe": True, "time_after": 0, "trigger": 0.14, "ensure": 0.12},
            {"exe": True, "time_after": 0, "trigger": 0.20, "ensure": 0.15},
            # {"exe": True, "time_after": 0, "trigger": 0.25, "ensure": 0.20},
            # {"exe": True, "time_after": 0, "trigger": 0.35, "ensure": 0.33},
            {"exe": True, "time_after": 2 * 5 * 60, "trigger": 0.40, "ensure": 0.38},
            # {"exe": True, "time_after": 2 * 5 * 60, "trigger": 0.50, "ensure": 0.43},
            # {"exe": True, "time_after": 2 * 5 * 60, "trigger": 0.60, "ensure": 0.57},
            {"exe": True, "time_after": 2 * 5 * 60, "trigger": 0.70, "ensure": 0.67},
            # {"exe": True, "time_after": 2 * 5 * 60, "trigger": 0.80, "ensure": 0.77},
            {"exe": True, "time_after": 2 * 5 * 60, "trigger": 0.90, "ensure": 0.87}
        ]

    def add_lc_change_defence(self):
        """
        lcChange = 1で選ばれるもの
        負ける可能性は高くなる可能性高い。
        少しプラスになったらLCの幅を減らしていく手法
        """
        # 動き代を基にする
        # first_trigger = 0.025
        # first_ensure = round(first_trigger - self.move_ave, 3)
        first_ensure = 0.01
        first_trigger = round(first_ensure + (self.move_ave * 1), 3)

        # 動きを基にする　パート２
        first_ensure = self.peak1_target_gap
        first_trigger = round(first_ensure + (self.move_ave * 0.5), 3)

        self.finalized_order['lc_change'] = [
            {"exe": True, "time_after": 0, "trigger": 0.025, "ensure": -0.01},
            # {"exe": True, "time_after": 600, "trigger": 0.043, "ensure": 0.018},
            # {"exe": True, "time_after": 600, "trigger": first_trigger, "ensure": first_ensure},
            {"exe": True, "time_after": 0, "trigger": 0.05, "ensure": 0.025},
            {"exe": True, "time_after": 0, "trigger": 0.08, "ensure": 0.05},
            {"exe": True, "time_after": 0, "trigger": 0.20, "ensure": 0.15},
            {"exe": True, "time_after": 600, "trigger": 0.40, "ensure": 0.35},
            {"exe": True, "time_after": 2 * 5 * 60, "trigger": 0.60, "ensure": 0.55},
            {"exe": True, "time_after": 2 * 5 * 60, "trigger": 0.70, "ensure": 0.65},
            {"exe": True, "time_after": 2 * 5 * 60, "trigger": 0.80, "ensure": 0.75},
            {"exe": True, "time_after": 2 * 5 * 60, "trigger": 0.90, "ensure": 0.85},
            {"exe": True, "time_after": 2 * 5 * 60, "trigger": 1.00, "ensure": 0.95},
        ]

    def add_counter_order(self, finalized_counter_order):
        # カウンターオーダー自身がFinalizedされていない限りできない。
        self.finalized_order['counter_order'] = finalized_counter_order

    def order_finalize(self):
        # 価格や通貨に依存する物たち
        dependence_price_or_range_criteria = 80  # ドル円の場合、80以上は価格とみなし、それ以下はrangeとみなす
        dependence_tp_lc_margin = 0.02  # 最低限の幅を保つためのもの。ドル円の場合0.02円(2pips) (LC価格とTarget価格が同値となった時の調整)

        order_base_info = self.order_base

        # ⓪必須項目がない場合、エラーとする
        if not ('expected_direction' in order_base_info) or not ('decision_price' in order_base_info):
            print("　　　　エラー（項目不足)", 'expected_direction' in order_base_info,
                  'decision_price' in order_base_info, 'decision_time' in order_base_info)
            return -1  # エラー

        # 0 注文方式を指定する
        if not ('stop_or_limit' in order_base_info) and not ("type" in order_base_info):
            print(" ★★オーダー方式が入力されていません")
        else:
            if 'type' in order_base_info:
                if order_base_info['type'] == "STOP":
                    order_base_info['stop_or_limit'] = 1
                elif order_base_info['type'] == "LIMIT":
                    order_base_info['stop_or_limit'] = -1
                elif order_base_info['type'] == "MARKET":
                    print(
                        "    Marketが指定されてます。targetは価格が必要です。Rangeを指定すると['stop_or_limit']がないエラーになる")
                    pass
            elif 'stop_or_limit' in order_base_info:
                order_base_info['type'] = "STOP" if order_base_info['stop_or_limit'] == 1 else "LIMIT"

        # ①TargetPriceを確実に取得する
        if not ('target' in order_base_info):
            # どっちも入ってない場合、Error
            print("    ★★★target(Rangeか価格か）が入力されていません")
        elif order_base_info['target'] >= dependence_price_or_range_criteria:
            # targetが８０以上の数字の場合、ターゲット価格が指定されたとみなす
            order_base_info['position_margin'] = round(
                abs(order_base_info['decision_price'] - order_base_info['target']), 3)
            order_base_info['target_price'] = order_base_info['target']
            # print("    ★★target 価格指定", order_base['target'], abs(order_base['decision_price']), order_base['target_price'])
        elif order_base_info['target'] < dependence_price_or_range_criteria:
            # targetが80未満の数字の場合、PositionまでのMarginが指定されたとみなす（負の数は受け入れない）
            # decision_priceにこのマージンを足して（購入方向を自動調整）、算出する。
            if order_base_info['target'] < 0:
                print("   targetに負のRangeが指定されています。ABSで使用します（正の値を計算で調整）")
                order_base_info['target'] = abs(order_base_info['target'])
            order_base_info['position_margin'] = round(order_base_info['target'], 3)
            order_base_info['target_price'] = order_base_info['decision_price'] + \
                                              (order_base_info['target'] * order_base_info['expected_direction'] *
                                               order_base_info[
                                                   'stop_or_limit'])
            # print("    t★arget Margin指定", order_base['target'], abs(order_base['decision_price']), order_base['target_price'])
        else:
            print("     Target_price PositionMarginどっちも入っている")

        # ② TP_priceとTP_Rangeを求める
        if not ('tp' in order_base_info):
            print("    ★★★TP情報が入っていません（利確設定なし？？？）")
            order_base_info['tp_range'] = 0  # 念のため０を入れておく（価格の指定は絶対に不要）
        elif order_base_info['tp'] >= dependence_price_or_range_criteria:
            # print("    TP 価格指定")
            # 80以上の数字は、Price値だと認識。Priceの設定と、Rangeの算出と設定を実施。
            #    ただし、偶然Target_Priceと同じになる(秒でTPが入ってしまう)可能性あるため、target_price-価格が0.02未満の場合は調整する。
            if abs(order_base_info['target_price'] - order_base_info['tp']) < dependence_tp_lc_margin:
                # 調整を行う（Rangeを最低の0.02に設定し、そこから改めてLC＿Priceを算出する）
                print("  ★★TP価格とTarget価格が同値となったため、調整あり(0.02)")
                order_base_info['tp_range'] = dependence_tp_lc_margin
                order_base_info['tp_price'] = round(order_base_info['target_price'] + (
                        order_base_info['tp_range'] * order_base_info['expected_direction']), 3)
            else:
                # 調整なしでOK
                order_base_info['tp_price'] = round(order_base_info['tp'], 3)
                order_base_info['tp_range'] = round(abs(order_base_info['target_price'] - order_base_info['tp']), 3)
        elif order_base_info['tp'] < dependence_price_or_range_criteria:
            # print("    TP　Range指定")
            # 80未満の数字は、Range値だと認識。Rangeの設定と、Priceの算出と設定を実施
            order_base_info['tp_price'] = round(
                order_base_info['target_price'] + (order_base_info['tp'] * order_base_info['expected_direction']), 3)
            order_base_info['tp_range'] = round(order_base_info['tp'], 3)

        # ③ LC_priceとLC_rangeを求める
        if not ('lc' in order_base_info):
            # どっちも入ってない場合、エラー
            print("    ★★★LC情報が入っていません（利確設定なし？？）")
        elif order_base_info['lc'] >= dependence_price_or_range_criteria:
            # print("    LC 価格指定")
            # 80以上の数字は、Price値だと認識。Priceの設定と、Rangeの算出と設定を実施。
            #     ただし、偶然Target_Priceと同じになる(秒でLCが入ってしまう)可能性あるため、target_price-価格が0.02未満の場合は調整する。
            if abs(order_base_info['target_price'] - order_base_info['lc']) < dependence_tp_lc_margin:
                # 調整を行う（Rangeを最低の0.02に設定し、そこから改めてLC＿Priceを算出する）
                print("  ★★LC価格とTarget価格が同値となったため、調整あり(0.02)")
                order_base_info['lc_range'] = dependence_tp_lc_margin
                order_base_info['lc_price'] = round(order_base_info['target_price'] - (
                        order_base_info['lc_range'] * order_base_info['expected_direction']), 3)
            else:
                # 調整なしでOK
                order_base_info['lc_price'] = round(order_base_info['lc'], 3)
                order_base_info['lc_range'] = abs(order_base_info['target_price'] - order_base_info['lc'])
        elif order_base_info['lc'] < dependence_price_or_range_criteria:
            # print("    LC RANGE指定")
            # 80未満の数字は、Range値だと認識。Rangeの設定と、Priceの算出と設定を実施
            order_base_info['lc_price'] = round(
                order_base_info['target_price'] - (order_base_info['lc'] * order_base_info['expected_direction']), 3)
            order_base_info['lc_range'] = round(order_base_info['lc'], 3)

        # ④alertの設定を行う（alertは数字か辞書が入る。数字かつ０の場合、辞書の場合、lc_changeの先頭にそれが入る
        if "alert" in order_base_info and "range" in order_base_info['alert']:
            # if isinstance(plan['alert']['range'], int)
            temp_range = round(order_base_info['alert']['range'], 3)
            temp_price = round(order_base_info['target_price'] - (
                        order_base_info['alert']['range'] * order_base_info['expected_direction']), 3)
            # 改めて入れなおしてしまう（別に上書きでもいいんだけど）
            order_base_info['alert'] = {"range": temp_range, "alert_price": temp_price, "time": 0}
        else:
            order_base_info['alert'] = {"range": 0, "time": 0, "alert_price": 0}

        # 最終的にオーダーで必要な情報を付与する(項目名を整えるためにコピーするだけ）。LimitかStopかを算出
        order_base_info['direction'] = order_base_info['expected_direction']
        order_base_info['price'] = order_base_info['target_price']
        order_base_info['order_timeout_min'] = order_base_info[
            'order_timeout_min'] if 'order_timeout_min' in order_base_info else 60

        order_base_info['trade_timeout_min'] = order_base_info[
            'trade_timeout_min'] if 'trade_timeout_min' in order_base_info else 150
        order_base_info['order_permission'] = order_base_info[
            'order_permission'] if 'order_permission' in order_base_info else True
        # 表示形式の問題で、、念のため（機能としては不要）
        order_base_info['decision_price'] = float(order_base_info['decision_price'])

        # ordered_dict = OrderedDict((key, order_base_info[key]) for key in order)
        order_base_info = sorted_dict = {key: order_base_info[key] for key in sorted(order_base_info)}

        # 名前の最後尾に時刻（決心時刻）を付与して、名前で時刻がわかるようにする
        order_base_info['name'] = order_base_info['name'] + "_" + str(gene.delYearDay(order_base_info['decision_time']))

        # ■コマンドラインで見にくいので、表示の順番を変えたい、、、（書き方雑だけど）
        temp = order_base_info['name']  # いったん保存
        del order_base_info["name"]
        order_base_info['name'] = temp

        temp = order_base_info['trade_timeout_min']  # いったん保存
        del order_base_info["trade_timeout_min"]
        order_base_info['trade_timeout_min'] = temp

        temp = order_base_info['order_timeout_min']  # いったん保存
        del order_base_info["order_timeout_min"]
        order_base_info['order_timeout_min'] = temp

        temp = order_base_info['tp_range']  # いったん保存
        del order_base_info["tp_range"]
        order_base_info['tp_range'] = temp

        temp = order_base_info['tp']  # いったん保存
        del order_base_info["tp"]
        order_base_info['tp'] = temp

        temp = order_base_info['price']  # いったん保存
        del order_base_info["price"]
        order_base_info['price'] = temp

        temp = order_base_info['target']  # いったん保存
        del order_base_info["target"]
        order_base_info['target'] = temp

        temp = order_base_info['priority']  # いったん保存
        del order_base_info["priority"]
        order_base_info['priority'] = temp

        temp = order_base_info['position_margin']  # いったん保存
        del order_base_info["position_margin"]
        order_base_info['position_margin'] = temp
        #
        temp = order_base_info['order_permission']  # いったん保存
        del order_base_info["order_permission"]
        order_base_info['order_permission'] = temp

        temp = order_base_info['alert']  # いったん保存
        del order_base_info["alert"]
        order_base_info['alert'] = temp

        # LC_CHANGE
        temp = order_base_info['lc_range']  # いったん保存
        del order_base_info["lc_range"]
        order_base_info['lc_range'] = temp
        # LC
        temp = order_base_info['lc']  # いったん保存
        del order_base_info["lc"]
        order_base_info['lc'] = temp
        # 方向
        temp = order_base_info['expected_direction']  # いったん保存
        del order_base_info["expected_direction"]
        order_base_info['expected_direction'] = temp
        # decisionPrice
        temp = order_base_info['decision_price']  # いったん保存
        del order_base_info["decision_price"]
        order_base_info['decision_price'] = temp
        # lc_Change_type
        temp = order_base_info['lc_change_type']  # いったん保存
        del order_base_info["lc_change_type"]
        order_base_info['lc_change_type'] = temp
        # ref
        temp = order_base_info['ref']  # いったん保存
        del order_base_info["ref"]
        order_base_info['ref'] = temp

        # LCChange(これが最後尾にしたい）
        if "lc_change" in order_base_info:
            temp = order_base_info['lc_change']  # いったん保存
            del order_base_info["lc_change"]
            order_base_info['lc_change'] = temp

        if "stop_or_limit" in order_base_info:
            temp = order_base_info['stop_or_limit']  # いったん保存
            del order_base_info["stop_or_limit"]
            order_base_info['stop_or_limit'] = temp

        return order_base_info


def cal_lc_price_from_line_and_margin(line_price, margin, expected_direction):
    """
    価格、マージン、購入方向を受け取り、
    line_priceを基準に、マージン分だけ余裕をとった（マージンを正の値にした場合、含み損が大きくなる方向）LC価格を算出する
    付与が、148, 0.06 , -1　の場合、
    148 + 0.06 = 148.06がLC値になる
    """
    # print(line_price)
    # print(margin)
    if expected_direction == 1:
        ans = line_price - margin
    else:
        ans = line_price + margin
    return ans


def cal_tp_price_from_line_and_margin(line_price, margin, expected_direction):
    """
    価格、マージン、購入方向を受け取り、
    cal_lcの逆（TPバージョン）をする
    """
    if expected_direction == 1:
        ans = line_price + margin
    else:
        ans = line_price - margin
    return ans


