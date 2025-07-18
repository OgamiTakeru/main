import copy
import matplotlib.pyplot as plt
import numpy as np
import fPeakInspection as p  # とりあえずの関数集
import fGeneric as gene
import fDoublePeaks as dp
import tokens as tk
import classPosition as classPosition  # とりあえずの関数集

import fPeakInspection as peak_inspection
import fDoublePeaks as dp
import pandas as pd
import fMoveSizeInspection as ms
import fCommonFunction as cf
import fMoveSizeInspection as ms
import fPeakInspection as pi
import classPeaks as cpk
from datetime import datetime, timedelta
from datetime import datetime
import classOrderCreate as OCreate
import classPosition
import fPredictTurn as pi
import bisect

class TuneAnalysisInformation:
    def __init__(self, peaks_class, older_no, older_peak, later_peak, name):
        self.name = name
        self.peaks_class = peaks_class
        self.turn_strength_at_older = 0
        self.skip_exist_at_older = False
        self.skip_num_at_older = 0
        self.lo_ratio = 0

        # 処理
        self.single_peak_additional_information(older_no)  # olderの解析
        self.relation_2peaks_information(older_peak, later_peak)  # 二つにまつわる解析

        # 表示
        print("----TurnAnalysisPrint", self.name)
        print("later:", later_peak['latest_time_jp'])
        print("older:", older_peak['latest_time_jp'])
        print("laterCount", later_peak['count'], "olderCount", older_peak['count'])
        print("olderスキップ有:", self.skip_exist_at_older, "olderSKIP数", self.skip_num_at_older)
        print("olderターン強度", self.turn_strength_at_older, "戻り率(通常)", self.lo_ratio)
        print("↑")

    def single_peak_additional_information(self, peak_no):
        """
        一つのピークの調査内容。peak_noで指定される
        基本的に１はターン、２はフロップを示す
        """
        # ■情報の元
        peaks = self.peaks_class.peaks_original_marked_hard_skip
        peaks_sk = self.peaks_class.skipped_peaks_hard  # 元々の
        target_peak = peaks[peak_no]  # 基本時間的に古いほうが入る。riverとturnの場合は１(turn)
        if len(peaks_sk) <= peak_no:
            # スキップの場合、１つになってしまっていることが、、
            target_peak_sk = target_peak  # とりあえずtargetPeakと同じものを入れて暫定
        else:
            # こっちが本来ほしいほう
            target_peak_sk = peaks_sk[peak_no]

        # ■各種調査
        # ⓪計算不要
        self.skip_num_at_older = target_peak_sk['skip_include_num']
        # ①　強度の判定
        self.peaks_class.make_same_price_list(1, False)  # クラス内でSamePriceListを実行
        self.turn_strength_at_older = sum(d["item"]["peak_strength"] for d in self.peaks_class.same_price_list)
        # gene.print_arr(self.peaks_class.same_price_list)

        # ②turnを生成するPeakに、スキップがあったかを確認する
        if self.peaks_class.cal_target_times_skip_num(self.peaks_class.skipped_peaks_hard, target_peak['latest_time_jp']) >= 1:
            self.skip_exist_at_older = True
        else:
            self.skip_exist_at_older = False

        # ③トレンド減速検知
        target_df = self.peaks_class.peaks_original_with_df[1]['data']  # "data"は特殊なPeaksが所持（スキップ非対応）
        brake_trend_exist = False
        # print("[1]のデータ")
        # print(target_df)
        if len(target_df) < 4:
            # print("target_dataが少なすぎる([1]がやけに短い⇒TrendBrakeあり？）")
            brake_trend_exist = True
        else:
            # BodyAveで検討
            older_body_ave = round((target_df.iloc[2]['body_abs'] + target_df.iloc[3]['body_abs']) / 2,
                                   2) + 0.0000000001  # 0防止
            later_body_ave = round((target_df.iloc[0]['body_abs'] + target_df.iloc[1]['body_abs']) / 2,
                                   2) + 0.0000000001  # 0防止
            # print("ratio", round(older_body_ave / later_body_ave, 2), "older", older_body_ave, "latest", later_body_ave)
            if older_body_ave / later_body_ave >= 3.5:  # 数が大きければ、よりブレーキがかかる
                # print("傾きの顕著な減少（ボディ）")
                brake_trend_exist = True

        # ④最後の足の方向について
        # r_df = self.peaks_class.peaks_original_with_df[0]['data']
        # latest_df = r_df.iloc[0]
        # latest_same = False
        # if (r['direction'] == 1 and latest_df['body'] > 0) or (r['direction'] == -1 and latest_df['body'] < 0):
        #     # print("リバーが正方向＋リバー最後が陽線 or リバーが負方向＋リバー最後が陰線", r['direction'], latest_df['body'])
        #     latest_same = True
        # else:
        #     pass
        #     # print("NG リバー方向", r['direction'], "ボディー向き", latest_df['body'])

    def relation_2peaks_information(self, older_peak, later_peak):
        """
        渡された二つのピークの関係性を算出する
        unit_noが１の場合は、riverとturn。unit_noが２の場合は、turnとflop
        """
        # rt_ratio_sk = round(r_sk['gap'] / t_sk['gap'], 3)
        self.lo_ratio = round(later_peak['gap'] / older_peak['gap'], 3)


def wrap_little_turn_inspection(peaks_class):
    """
    クラスをたくさん用いがケース
    args[0]は必ずdf_rであることで、必須。
    args[1]は、本番の場合、過去の決済履歴のマイナスの大きさでTPが変わるかを検討したいため、オーダークラスを受け取る
    """
    # peaksの算出
    # peaks_class = cpk.PeaksClass(df_r)
    #
    flag_and_orders = {
        "take_position_flag": False,
        "exe_orders": [],  # 本番用（本番運用では必須）
    }

    # predict2
    predict_result2 = cal_little_turn_at_trend(peaks_class)
    if predict_result2['take_position_flag']:
        flag_and_orders["take_position_flag"] = True
        flag_and_orders["exe_orders"] = predict_result2['exe_orders']
        # 代表プライオリティの追加
        max_priority = max(flag_and_orders["exe_orders"], key=lambda x: x['priority'])['priority']
        flag_and_orders['max_priority'] = max_priority
        flag_and_orders['for_inspection_dic'] = {}

        return flag_and_orders

    return flag_and_orders


def cal_little_turn_at_trend(peaks_class):
    """
    args[0]は必ずpeaks_classであること。
    args[1]は、本番の場合、過去の決済履歴のマイナスの大きさでTPが変わるかを検討したいため、オーダークラスを受け取る

    直近[0]がcount4の時、riverPeakにレジスタンスオーダーを入れる
    """
    # ■基本情報の取得
    print("★★TURN　本番用")
    take_position = False
    # ■返却値の設定
    default_return_item = {
        "take_position_flag": take_position,
        "for_inspection_dic": {}
    }
    s = "    "

    # ■実行除外
    # 対象のPeakのサイズを確認（小さすぎる場合、除外）
    peaks = peaks_class.peaks_original_marked_hard_skip
    if peaks[1]['gap'] < 0.04:
        print("対象が小さい", peaks[1]['gap'])
        # return default_return_item

    # ■基本的な情報の取得
    comment = ""
    # (1)
    r = peaks[0]
    t = peaks[1]
    f = peaks[2]
    # (2)-1 RiverとTurnの解析（初動）
    rt = TuneAnalysisInformation(peaks_class, 1, peaks[1], peaks[0], "rt")  # peak情報源生成
    # (2)-2FlopとTurnの解析（初動）
    t_df = peaks_class.peaks_original_with_df[1]['data'].head(3)  # Turn(1)のDFを取得する
    if len(t_df) < 3:
        print("ターンが短すぎるため、フロップまでの解析は不可？")
    else:
        t3_df = t_df.head(3)  # 3行以上の場合も、３行のみで判断
        t3_peak = peaks_class.make_peak(t3_df)  # 3行でpeakを生成
        print("ターンの最初3個を取得", t3_df.iloc[-1]['open'], "⇒", t3_df.iloc[0]['close'], "GAP", t3_peak['gap'])
        t3f = TuneAnalysisInformation(peaks_class, 2, peaks[2], t3_peak, "tf")  # peak情報源生成

    # ■分岐
    exe_orders = []
    if r['count'] == 2:
        # ●旧カウント３の強いやつの確認（flopまで考慮する）
        if rt.lo_ratio >= 0.8 or len(t_df) <3:
            print(" そもそもリバーがターンに対して戻りすぎている、または、ターンが短い場合 、微妙", rt.lo_ratio)
            pass
        else:
            if ((t3f.skip_exist_at_older or 7 <= f['count'] < 100) and t3f.skip_num_at_older< 3 and
                    0 < t3f.turn_strength_at_older <= 8):
                if 0 < t3f.lo_ratio <= 0.36:
                    comment = "●●●強いやつ"
                    # ■ターゲット価格＆マージンの設定
                    # target_price = peaks_class.latest_price
                    target_price = f['latest_body_peak_price']
                    margin = peaks_class.cal_move_ave(0)
                    m_dir = -1
                    # ■TPの設定
                    tp = peaks_class.cal_move_ave(5)
                    # ■LCの設定
                    # パターン１（シンプルに、平均足で指定するケース)
                    lc = peaks_class.cal_move_ave(2.2)
                    # パターン２（ターンの移動幅の3分の2程度の距離を許容する）
                    lc_range = round(t['gap'] / 3 * 2, 3)
                    # ■LCChangeの設定
                    lc_change = 3
                    # ■■オーダーを作成＆発行
                    exe_orders.append(
                        order_make_dir0_s(
                            peaks_class, comment, target_price, margin, m_dir,
                            tp,
                            lc,
                            lc_change,
                            3,
                            4,
                            lc * 0.7)
                    )
                    print("ターン解析　オーダー発行")
                    print(comment)
                    gene.print_arr(exe_orders)
                    return {
                        "take_position_flag": True,
                        "exe_orders": exe_orders,
                        "for_inspection_dic": {}
                    }
            else:
                # 強のやつを見ない
                pass

        # ●通常のCount２の挙動
        if ((rt.skip_exist_at_older or 6 <= t['count'] < 100) and rt.skip_num_at_older < 3
                and 0 < rt.turn_strength_at_older <= 8 and 0 < rt.lo_ratio <= 0.26):
            comment = "●●Count2のすぐBreak"
            line_price = t['latest_body_peak_price']  # 抵抗線になりうる価格（ターンのピーク価格）
            current_price = peaks_class.latest_price  # 現在の価格

            # ■ターゲットプライス判定
            # 本来、「抵抗線を越える＝突破の可能性大」とするため、抵抗線価格をターゲットPriceにしたい。
            # ただ、現在価格と近すぎると、瞬間的な越えの可能性も高くなるため、現在価格と抵抗線が近い場合は、調整する
            # （特にターンが登り方向で、最新の足が陽線の場合は特に近くなる。ただ陰陽の区別はいったんしない）
            min_margin_for_target = 0.01  # 最低でも3ピップスの余裕を見る
            # min_margin_for_target = round(t['gap']*0.2, 3)
            if abs(line_price-current_price) <= min_margin_for_target:
                target_price = line_price + (min_margin_for_target * t['direction'])
            else:
                target_price = line_price
            # target_price = line_price
            print("TurnPrice:", line_price, "targetPrice:", target_price, "footAve", peaks_class.cal_move_ave(1))
            # ■LC価格の算出
            # パターン１(turnピークから、3分の2の価格まで。LcChangeで、3分の1に底上げ？）
            temp_lc_range = round(t['gap']*0.2, 3)
            lc_price1 = t['latest_body_peak_price'] - (temp_lc_range * t['direction'])
            print("[LC1]tempLcRange:", temp_lc_range, "lcPrice", lc_price1, "lcRange", round(abs(target_price-lc_price1), 3))
            alert = round(t['gap']*0.1, 3)
            # ■TP価格の算出
            tp_range = t['gap']  # ターンのギャップ程度はいけるのでは？ (lcとの比率は、簡単に出せる）
            # ■LCChangeの算出（基本的に行わない)
            lc_change = 0  # LCChangeを行わない場合は数字の０を入れる
            first_ensure = t['gap'] * -0.1
            f_ave = peaks_class.cal_move_ave(1)  # 平均の足の幅（高さ）
            if f_ave <= temp_lc_range:
                # LCRangeが少しでも少なっている⇒OK
                first_ensure = f_ave
            else:
                # 従来のLCレンジより大きくなっている場合
                first_ensure = temp_lc_range * 0.8

            lc_change = [
                {"exe": True, "time_after": 200, "trigger": 0.01, "ensure": round(0.01-first_ensure,3), "time_till": 10000},
                # {"exe": True, "time_after": 0, "trigger": f_ave * 0.8, "ensure": f_ave * 0.05, "time_till": 1000},
                # {"exe": True, "time_after": 0, "trigger": f_ave * 1.3, "ensure": f_ave * 1, "time_till": 1000},
            ]
            # ■■オーダーを発行
            order = order_make_dir1_s(
                peaks_class, comment, target_price, 0, 1,
                tp_range,
                lc_price1,  # peaks_class.cal_move_ave(1),
                lc_change,
                2,
                3,
                alert)
            order['order_timeout_min'] = 10  # 5分でオーダー消去（すぐに越えてない場合はもうNGとみなす。最大10分か？）
            exe_orders.append(order)
        elif ((rt.skip_exist_at_older or 3 <= t['count'] < 100) and rt.skip_num_at_older < 3 and
              0 < rt.turn_strength_at_older <= 8 and 0.18 < rt.lo_ratio <= 2):
            comment = "△Count2のすぐRange側"
            target_price = peaks_class.latest_price
            margin = round(abs(t['gap']) / 5, 3)
            order = order_make_dir0_s(
                peaks_class, comment, target_price, margin, 1,
                peaks_class.cal_move_ave(1.2),
                peaks_class.cal_move_ave(1.2),
                1,
                1,
                3,
                peaks_class.cal_move_ave(0.7))
            order['order_timeout_min'] = 5  # 5分でオーダー消去（すぐに越えてない場合はもうNGとみなす。最大10分か？）
            exe_orders.append(order)
        elif ((rt.skip_exist_at_older or 5 <= t['count'] < 100) and rt.skip_num_at_older < 3 and
              11 < rt.turn_strength_at_older <= 100 and 0.10 < rt.lo_ratio <= 0.30):
            comment = "△Count2で抵抗値高い"
            target_price = t['latest_body_peak_price']
            margin = round(abs(t['gap']) / 4, 3)
            order = order_make_dir0_s(
                peaks_class, comment, target_price, 0, 1,
                peaks_class.cal_move_ave(1.5),
                peaks_class.cal_move_ave(1.0),
                1,
                1,
                3,
                peaks_class.cal_move_ave(0.7))
            order['order_timeout_min'] = 5  # 5分でオーダー消去（すぐに越えてない場合はもうNGとみなす。最大10分か？）
            exe_orders.append(order)
        else:
            print("NoOrder 1")
            return default_return_item

    elif r['count'] == 3:
        if (rt.skip_exist_at_older or 7 <= t['count'] < 100) and rt.skip_num_at_older < 3 and 0 < rt.turn_strength_at_older <= 8:
            if 0 < rt.lo_ratio <= 0.36:
                comment = "●●●強いやつ(旧式）"
                # if peaks_class.time_hour == 4 or peaks_class.time_hour == 5:
                #     tk.line_send("●●●強いやつだが、時間悪い")
                #     return default_return_item
                # ■ターゲット価格＆マージンの設定
                target_price = peaks_class.latest_price
                margin = peaks_class.cal_move_ave(0.4)
                m_dir = -1
                # ■TPの設定
                tp = peaks_class.cal_move_ave(5)
                # ■LCの設定
                # パターン１（シンプルに、平均足で指定するケース)
                lc = peaks_class.cal_move_ave(2.2)
                # パターン２（ターンの移動幅の3分の2程度の距離を許容する）
                lc_range = round(t['gap'] / 3 * 2, 3)
                # ■LCChangeの設定
                lc_change = 3
                # lc_change = [
                #     {"exe": True, "time_after": 0, "trigger": 0.01, "ensure": t['gap'] * 0.1, "time_till": 1000},
                #     {"exe": True, "time_after": 0, "trigger": f_ave * 0.8, "ensure": f_ave * 0.1, "time_till": 1000},
                # ]

                # ■■オーダーを作成＆発行
                exe_orders.append(
                    order_make_dir1_s(
                        peaks_class, comment, target_price, margin, m_dir,
                        tp,
                        lc,
                        lc_change,
                        3,
                        4,
                        lc * 0.7)
                )
            else:
                print("戻り値異なる", r['count'])
                return default_return_item
        else:
            print("条件アウト", r['count'])
            return default_return_item
    else:
        print("rCountが不適切", r['count'])
        return default_return_item

    # 本番用ここまで★★
    print("ターン解析　オーダー発行", )
    print(comment)
    gene.print_arr(exe_orders)
    return {
        "take_position_flag": True,
        "exe_orders": exe_orders,
        "for_inspection_dic": {}
    }

# ↓　解析テスト用（引数がdf_r)のもので、Long用解析のInspectionClassを使う際はこちらが必要
def wrap_little_turn_inspection_test(df_r):
    """
    クラスをたくさん用いがケース
    args[0]は必ずdf_rであることで、必須。
    args[1]は、本番の場合、過去の決済履歴のマイナスの大きさでTPが変わるかを検討したいため、オーダークラスを受け取る
    """
    # peaksの算出
    peaks_class = cpk.PeaksClass(df_r)
    #
    flag_and_orders = {
        "take_position_flag": False,
        "exe_orders": [],  # 本番用（本番運用では必須）
    }

    # predict2
    predict_result2 = cal_little_turn_at_trend_test(peaks_class)
    if predict_result2['take_position_flag']:
        flag_and_orders["take_position_flag"] = True
        flag_and_orders["exe_orders"] = predict_result2['exe_orders']
        # 代表プライオリティの追加
        max_priority = max(flag_and_orders["exe_orders"], key=lambda x: x['priority'])['priority']
        flag_and_orders['max_priority'] = max_priority
        flag_and_orders['for_inspection_dic'] = {}

        return flag_and_orders

    return flag_and_orders


def cal_little_turn_at_trend_test(peaks_class):
    """
    args[0]は必ずpeaks_classであること。
    args[1]は、本番の場合、過去の決済履歴のマイナスの大きさでTPが変わるかを検討したいため、オーダークラスを受け取る

    直近[0]がcount4の時、riverPeakにレジスタンスオーダーを入れる
    """
    # ■基本情報の取得
    # ■基本情報の取得
    print("★★TURN　テスト用")
    take_position = False
    # ■返却値の設定
    default_return_item = {
        "take_position_flag": take_position,
        "for_inspection_dic": {}
    }
    s = "    "

    # ■実行除外
    # 対象のPeakのサイズを確認（小さすぎる場合、除外）
    peaks = peaks_class.peaks_original_marked_hard_skip
    if peaks[1]['gap'] < 0.04:
        print("対象が小さい", peaks[1]['gap'])
        # return default_return_item

    # ■基本的な情報の取得
    comment = ""
    # (1)
    r = peaks[0]
    t = peaks[1]
    f = peaks[2]
    # (2)-1 RiverとTurnの解析（初動）
    rt = TuneAnalysisInformation(peaks_class, 1, peaks[1], peaks[0], "rt")  # peak情報源生成
    # (2)-2FlopとTurnの解析（初動）
    t_df = peaks_class.peaks_original_with_df[1]['data'].head(3)  # Turn(1)のDFを取得する
    if len(t_df) < 3:
        print("ターンが短すぎるため、フロップまでの解析は不可？")
        t3f = rt  # ここで代入したものは使われることないはず（ただしtypo対策として、念のためにrtと同値を入れておく）
    else:
        t3_df = t_df.head(3)  # 3行以上の場合も、３行のみで判断
        t3_peak = peaks_class.make_peak(t3_df)  # 3行でpeakを生成
        print("ターンの最初3個を取得", t3_df.iloc[-1]['open'], "⇒", t3_df.iloc[0]['close'], "GAP", t3_peak['gap'])
        t3f = TuneAnalysisInformation(peaks_class, 2, peaks[2], t3_peak, "tf")  # peak情報源生成

    # ■分岐
    exe_orders = []
    if r['count'] == 2:
        # ●旧カウント３の強いやつの確認（flopまで考慮する）
        if rt.lo_ratio >= 0.8 or len(t_df) <3:
            print(" そもそもリバーがターンに対して戻りすぎている、または、ターンが短い場合 、微妙", rt.lo_ratio)
            pass
        else:
            if ((t3f.skip_exist_at_older or 7 <= f['count'] < 100) and t3f.skip_num_at_older < 3 and
                    0 < t3f.turn_strength_at_older <= 8):
                if 0 < t3f.lo_ratio <= 0.36:
                    comment = "●●●強いやつ"
                    # ■ターゲット価格＆マージンの設定
                    target_price = peaks_class.latest_price
                    margin = peaks_class.cal_move_ave(0.4)
                    m_dir = -1
                    # ■TPの設定
                    tp = peaks_class.cal_move_ave(5)
                    # ■LCの設定
                    # パターン１（シンプルに、平均足で指定するケース)
                    lc = peaks_class.cal_move_ave(2.2)
                    # パターン２（ターンの移動幅の3分の2程度の距離を許容する）
                    lc_range = round(t['gap'] / 3 * 2, 3)
                    # ■LCChangeの設定
                    lc_change = 3
                    # ■■オーダーを作成＆発行
                    exe_orders.append(
                        order_make_dir1_s(
                            peaks_class, comment, target_price, margin, m_dir,
                            tp,
                            lc,
                            lc_change,
                            3,
                            4,
                            lc * 0.7)
                    )
                    print("ターン解析　オーダー発行")
                    print(comment)
                    gene.print_arr(exe_orders)
                    return {
                        "take_position_flag": True,
                        "exe_orders": exe_orders,
                        "for_inspection_dic": {}
                    }
            else:
                # 強のやつを見ない
                pass

        # ●通常のCount２の挙動
        if ((rt.skip_exist_at_older or 6 <= t['count'] < 100) and rt.skip_num_at_older < 3
                and 0 < rt.turn_strength_at_older <= 8 and 0 < rt.lo_ratio <= 0.26):
            comment = "●●Count2のすぐBreak"
            line_price = t['latest_body_peak_price']  # 抵抗線になりうる価格（ターンのピーク価格）
            current_price = peaks_class.latest_price  # 現在の価格

            # ■ターゲットプライス判定
            # 本来、「抵抗線を越える＝突破の可能性大」とするため、抵抗線価格をターゲットPriceにしたい。
            # ただ、現在価格と近すぎると、瞬間的な越えの可能性も高くなるため、現在価格と抵抗線が近い場合は、調整する
            # （特にターンが登り方向で、最新の足が陽線の場合は特に近くなる。ただ陰陽の区別はいったんしない）
            min_margin_for_target = 0.01  # 最低でも3ピップスの余裕を見る
            # min_margin_for_target = round(t['gap']*0.2, 3)
            if abs(line_price-current_price) <= min_margin_for_target:
                target_price = line_price + (min_margin_for_target * t['direction'])
            else:
                target_price = line_price
            # target_price = line_price
            print("TurnPrice:", line_price, "targetPrice:", target_price, "footAve", peaks_class.cal_move_ave(1))
            # ■LC価格の算出
            # パターン１(turnピークから、3分の2の価格まで。LcChangeで、3分の1に底上げ？）
            temp_lc_range = round(t['gap']*0.2, 3)
            lc_price1 = t['latest_body_peak_price'] - (temp_lc_range * t['direction'])
            print("[LC1]tempLcRange:", temp_lc_range, "lcPrice", lc_price1, "lcRange", round(abs(target_price-lc_price1), 3))
            alert = round(t['gap']*0.1, 3)
            # ■TP価格の算出
            tp_range = t['gap']  # ターンのギャップ程度はいけるのでは？ (lcとの比率は、簡単に出せる）
            # ■LCChangeの算出（基本的に行わない)
            lc_change = 0  # LCChangeを行わない場合は数字の０を入れる
            first_ensure = t['gap'] * -0.1
            f_ave = peaks_class.cal_move_ave(1)  # 平均の足の幅（高さ）
            if f_ave <= temp_lc_range:
                # LCRangeが少しでも少なっている⇒OK
                first_ensure = f_ave
            else:
                # 従来のLCレンジより大きくなっている場合
                first_ensure = temp_lc_range * 0.8

            lc_change = [
                {"exe": True, "time_after": 200, "trigger": 0.01, "ensure": round(0.01-first_ensure,3), "time_till": 10000},
                # {"exe": True, "time_after": 0, "trigger": f_ave * 0.8, "ensure": f_ave * 0.05, "time_till": 1000},
                # {"exe": True, "time_after": 0, "trigger": f_ave * 1.3, "ensure": f_ave * 1, "time_till": 1000},
            ]
            # ■■オーダーを発行
            order = order_make_dir1_s(
                peaks_class, comment, target_price, 0, 1,
                tp_range,
                lc_price1,  # peaks_class.cal_move_ave(1),
                lc_change,
                2,
                3,
                alert)
            order['order_timeout_min'] = 10  # 5分でオーダー消去（すぐに越えてない場合はもうNGとみなす。最大10分か？）
            exe_orders.append(order)
        elif ((rt.skip_exist_at_older or 3 <= t['count'] < 100) and rt.skip_num_at_older < 3 and
              0 < rt.turn_strength_at_older <= 8 and 0.18 < rt.lo_ratio <= 2):
            comment = "△Count2のすぐRange側"
            target_price = peaks_class.latest_price
            margin = round(abs(t['gap']) / 5, 3)
            order = order_make_dir0_s(
                peaks_class, comment, target_price, margin, 1,
                peaks_class.cal_move_ave(1.2),
                peaks_class.cal_move_ave(1.2),
                1,
                1,
                3,
                peaks_class.cal_move_ave(0.7))
            order['order_timeout_min'] = 5  # 5分でオーダー消去（すぐに越えてない場合はもうNGとみなす。最大10分か？）
            exe_orders.append(order)
        elif ((rt.skip_exist_at_older or 5 <= t['count'] < 100) and rt.skip_num_at_older < 3 and
              11 < rt.turn_strength_at_older <= 100 and 0.10 < rt.lo_ratio <= 0.30):
            comment = "△Count2で抵抗値高い"
            target_price = t['latest_body_peak_price']
            margin = round(abs(t['gap']) / 4, 3)
            order = order_make_dir0_s(
                peaks_class, comment, target_price, 0, 1,
                peaks_class.cal_move_ave(1.5),
                peaks_class.cal_move_ave(1.0),
                1,
                1,
                3,
                peaks_class.cal_move_ave(0.7))
            order['order_timeout_min'] = 5  # 5分でオーダー消去（すぐに越えてない場合はもうNGとみなす。最大10分か？）
            exe_orders.append(order)
        else:
            print("NoOrder 1")
            return default_return_item
    elif r['count'] == 3:
        if (rt.skip_exist_at_older or 7 <= t['count'] < 100) and rt.skip_num_at_older < 3 and 0 < rt.turn_strength_at_older <= 8:
            if 0 < rt.lo_ratio <= 0.36:
                comment = "●●●強いやつ(旧式）"
                # if peaks_class.time_hour == 4 or peaks_class.time_hour == 5:
                #     tk.line_send("●●●強いやつだが、時間悪い")
                #     return default_return_item
                # ■ターゲット価格＆マージンの設定
                target_price = peaks_class.latest_price
                margin = peaks_class.cal_move_ave(0.4)
                m_dir = -1
                # ■TPの設定
                tp = peaks_class.cal_move_ave(5)
                # ■LCの設定
                # パターン１（シンプルに、平均足で指定するケース)
                lc = peaks_class.cal_move_ave(2.2)
                # パターン２（ターンの移動幅の3分の2程度の距離を許容する）
                lc_range = round(t['gap'] / 3 * 2, 3)
                # ■LCChangeの設定
                lc_change = 3
                # lc_change = [
                #     {"exe": True, "time_after": 0, "trigger": 0.01, "ensure": t['gap'] * 0.1, "time_till": 1000},
                #     {"exe": True, "time_after": 0, "trigger": f_ave * 0.8, "ensure": f_ave * 0.1, "time_till": 1000},
                # ]

                # ■■オーダーを作成＆発行
                exe_orders.append(
                    order_make_dir1_s(
                        peaks_class, comment, target_price, margin, m_dir,
                        tp,
                        lc,
                        lc_change,
                        3,
                        4,
                        lc * 0.7)
                )
            else:
                print("戻り値異なる", r['count'])
                return default_return_item
        else:
            print("条件アウト", r['count'])
            return default_return_item
    else:
        print("rCountが不適切", r['count'])
        return default_return_item

    # 本番用ここまで★★
    print("ターン解析　オーダー発行")
    print(comment)
    gene.print_arr(exe_orders)
    return {
        "take_position_flag": True,
        "exe_orders": exe_orders,
        "for_inspection_dic": {}
    }


# ↓ループテスト用（paramsを使うような解析はこちら）
# def wrap_predict_turn_inspection_looptest(df_r, params):
#     """
#     クラスをたくさん用いがケース
#     args[0]は必ずdf_rであることで、必須。
#     args[1]は、本番の場合、過去の決済履歴のマイナスの大きさでTPが変わるかを検討したいため、オーダークラスを受け取る
#     """
#     # peaksの算出
#     peaks_class = cpk.PeaksClass(df_r)
#     #
#     flag_and_orders = {
#         "take_position_flag": False,
#         "exe_orders": [],  # 本番用（本番運用では必須）
#     }
#
#     # predict 初期
#     # predict_result = cal_predict_turn(peaks_class)  #
#     # if predict_result['take_position_flag']:
#     #     flag_and_orders["take_position_flag"] = True
#     #     flag_and_orders["exe_orders"] = predict_result['exe_orders']
#     #     # 代表プライオリティの追加
#     #     max_priority = max(flag_and_orders["exe_orders"], key=lambda x: x['priority'])['priority']
#     #     flag_and_orders['max_priority'] = max_priority
#     #     flag_and_orders['for_inspection_dic'] = {}
#     #
#     #     return flag_and_orders
#
#     # predict2
#     predict_result2 = cal_little_turn_at_trend_looptest(peaks_class, params)
#     if predict_result2['take_position_flag']:
#         flag_and_orders["take_position_flag"] = True
#         flag_and_orders["exe_orders"] = predict_result2['exe_orders']
#         # 代表プライオリティの追加
#         max_priority = max(flag_and_orders["exe_orders"], key=lambda x: x['priority'])['priority']
#         flag_and_orders['max_priority'] = max_priority
#         flag_and_orders['for_inspection_dic'] = {}
#
#         return flag_and_orders
#
#     return flag_and_orders
#
#
# def cal_little_turn_at_trend_looptest(peaks_class, params):
#     """
#     args[0]は必ずpeaks_classであること。
#     args[1]は、本番の場合、過去の決済履歴のマイナスの大きさでTPが変わるかを検討したいため、オーダークラスを受け取る
#
#     直近[0]がcount4の時、riverPeakにレジスタンスオーダーを入れる
#     """
#     # ■基本情報の取得
#     print("★★PREDICT　TURN2222")
#     take_position = False
#     # ■返却値の設定
#     default_return_item = {
#         "take_position_flag": take_position,
#         "for_inspection_dic": {}
#     }
#     s = "    "
#
#     # ■Peaks等、大事な変数の設定
#     # ターゲットになるピークを選択
#     target_num = 1  # 以下のループで「自分以外」を定義するため、変数に入れておく(同一方向の配列に対して）
#     peaks = peaks_class.peaks_original_marked_hard_skip
#     # peaks = peaks_class.skipped_peaks
#     target_peak = peaks[target_num]
#     # print("ターゲットになるピーク:", target_peak['peak'], target_peak)
#
#     # ■実行除外
#     # latestのカウントが既定の物かを確認
#     if peaks[0]['count'] == 3:  # and peaks[1]['count'] >= 3:  # [0]countは２では微妙（２はBreakのケースが多く見える）ので３．
#         print("　カウント数は合格", peaks[0]['count'], "が4以上が対象")
#     else:
#         print("  山を形成するカウント不足", peaks[0]['count'], "が4以上が対象")
#         return default_return_item
#     # 対象のPeakのサイズを確認（小さすぎる場合、除外）
#     if peaks[1]['gap'] < 0.04:
#         print("対象が小さい", peaks[1]['gap'])
#         return default_return_item
#
#     # ■判定に必要な数字の算出
#     # 1 強度の判定
#     peaks_class.make_same_price_list(target_num, False)  # クラス内でSamePriceListを実行
#     print("同一価格リスト（抵抗線強度検討用）")
#     gene.print_arr(peaks_class.same_price_list)
#     total_strength_of_1 = sum(d["item"]["peak_strength"] for d in peaks_class.same_price_list)
#     print("samePriceListの強度の合計値;", total_strength_of_1)
#     #    10以上だと強い⇒抵抗OrderのLCを小さくとる（越えた場合大きく越えそう）
#     #    なんなら、その場合はBreakOrderも出してみたい。
#
#     # 直近がスキップがあったかを確認したい
#     if peaks_class.cal_target_times_skip_num(peaks_class.skipped_peaks_hard, peaks[1]['latest_time_jp']) >= 1:
#         is_latest_skip_hard = True
#         print(" SKIPあり hard")
#     else:
#         if peaks[1]['count'] >= 8:
#             is_latest_skip_hard = True
#             print(" SKIPあり hard")
#         else:
#             is_latest_skip_hard = False
#             print(" SKIP無し hard")
#
#     if peaks_class.cal_target_times_skip_num(peaks_class.skipped_peaks, peaks[1]['latest_time_jp']) >= 1:
#         is_latest_skip = True
#         print(" SKIPあり hard")
#     else:
#         is_latest_skip = False
#         print(" SKIP無し hard")
#
#     # 直近が越えているかどうか
#     if peaks[0]['direction'] == 1:
#         # 直近が登りの場合
#         if peaks[0]['latest_body_peak_price'] <= peaks[2]['latest_body_peak_price']:
#             print(" [0]が[2]を下に越えている,[0]:", peaks[0]['latest_body_peak_price'], "[1]:",
#                   peaks[2]['latest_body_peak_price'])
#             is_over = True
#         else:
#             is_over = False
#     else:
#         if peaks[0]['latest_body_peak_price'] <= peaks[2]['latest_body_peak_price']:
#             print(" [0]が[2]を上に越えている,[0]:", peaks[0]['latest_body_peak_price'], "[1]:",
#                   peaks[2]['latest_body_peak_price'])
#             is_over = True
#         else:
#             is_over = False
#
#     # 越えていない場合の、[0]と[1]の比率
#     return_ratio_0_1 = peaks[0]['gap'] / peaks[1]['gap']
#     print(" 戻り率", return_ratio_0_1)
#
#     # 本番用★★
#     # if total_strength_of_1 <= 8 and not is_over:
#     #     print("strength<8、[2]越えてない、直近スキップ不問")  # > の向きが越える
#     #     comment = "strength<8、[2]越えてない、直近スキップなし"  # Peak[0]のほうが適切化も？？
#     #     target_price = peaks[0]['latest_body_peak_price']
#     #     exe_orders = [order_make_dir1_s(peaks_class, comment, target_price,
#     #                                     peaks_class.cal_move_ave(1), -1,
#     #                                     peaks_class.cal_move_ave(3),
#     #                                     peaks_class.cal_move_ave(1),
#     #                                     3)]
#     # elif total_strength_of_1 <= 8 and is_over and not is_latest_skip_hard:
#     #     print("strength<8、[2]越え、直近スキップ不問（事実上あり）")  # > の向きが越える
#     #     comment = "strength<8、[2]越え、直近スキップ不問（事実上あり）"  # Peak[0]のほうが適切化も？？
#     #     target_price = peaks[0]['latest_body_peak_price']
#     #     exe_orders = [order_make_dir0_s(peaks_class, comment, target_price,
#     #                                     peaks_class.cal_move_ave(1), 1,
#     #                                     peaks_class.cal_move_ave(3),
#     #                                     peaks_class.cal_move_ave(1),
#     #                                     3)]
#     #                                         # peaks_class.cal_move_ave(1), -1,
#     #                                         # peaks_class.cal_move_ave(3),
#     #                                         # peaks_class.cal_move_ave(1),
#     #                                         # 3)]
#     # elif total_strength_of_1 >= 10 and not is_over:
#     #     print("strength>=10、[2]越えなし、直近スキップ不問")
#     #     comment = "strength>=10、[2]越えなし、直近スキップ不問"  # Peak[0]のほうが適切化も？？
#     #     target_price = peaks[0]['latest_body_peak_price']
#     #     exe_orders = [order_make_dir1_s(peaks_class, comment, target_price,
#     #                                     peaks_class.cal_move_ave(1), 1,
#     #                                     peaks_class.cal_move_ave(3),
#     #                                     peaks_class.cal_move_ave(1),
#     #                                     3)]
#     # else:
#     #     return default_return_item
#     # 本番用ここまで★★
#
#     # ■判
#     position = True
#     if params['min_resi_stg'] <= total_strength_of_1 <= params['max_resi_stg']:
#         position = True
#     else:
#         return default_return_item
#
#     if return_ratio_0_1 <= params['rat']:
#         position = True
#     else:
#         return default_return_item
#
#     if params['over_filter'] == 1:
#         # overFilterOnの場合、overしている場合はNG
#         if is_over:
#             return default_return_item
#         else:
#             position = True
#     elif params['over_filter'] == -1:
#         # overFilterOnの場合、overしている
#         if is_over:
#             position = True
#         else:
#             return default_return_item
#     else:
#         # FilterがOffの場合、全部通過
#         position = True
#
#     # SKipフィルター
#     if params['skip_filter'] == 0:
#         position = True
#     elif params['skip_filter'] == 1:
#         # フィルターモードが１の場合、スキップが無いもののみが対象
#         if is_latest_skip_hard:
#             # skip_filterが有効の場合、スキップがある場合はNG
#             return default_return_item
#         else:
#             position = True
#     elif params['skip_filter'] == -1:
#         # フィルターモードがー１の場合、スキップが有る物のみ対象
#         # フィルターモードが１の場合、スキップが無いもののみが対象
#         if is_latest_skip_hard:
#             # skip_filterが有効の場合、スキップがある場合はNG
#             position = True
#         else:
#             return default_return_item
#     else:
#         return default_return_item
#
#     # skip_filterがTrueの場合、is_latest_skip_hardがTrueのものは除外（Falseのみ通過）
#     # Falseの場合は、今のところ全部通
#     if params['pat'] == 1:
#         target_price = peaks[0]['latest_body_peak_price']
#         exe_orders = [order_make_dir1_s(peaks_class, params['c'], target_price,
#                                         peaks_class.cal_move_ave(params['margin']), 1,
#                                         peaks_class.cal_move_ave(params['tp']),
#                                         peaks_class.cal_move_ave(params['lc']),
#                                         params['lc_change'],
#                                         1)]
#     elif params['pat'] == 2:
#         target_price = peaks[0]['latest_body_peak_price']
#         exe_orders = [order_make_dir1_s(peaks_class, params['c'], target_price,
#                                         peaks_class.cal_move_ave(params['margin']), -1,
#                                         peaks_class.cal_move_ave(params['tp']),
#                                         peaks_class.cal_move_ave(params['lc']),
#                                         params['lc_change'],
#                                         1)]
#     elif params['pat'] == 3:
#         target_price = peaks[0]['latest_body_peak_price']
#         exe_orders = [order_make_dir0_s(peaks_class, params['c'], target_price,
#                                         peaks_class.cal_move_ave(params['margin']), 1,
#                                         peaks_class.cal_move_ave(params['tp']),
#                                         peaks_class.cal_move_ave(params['lc']),
#                                         params['lc_change'],
#                                         1)]
#     # elif params['pat'] == 4:
#     else:
#         target_price = peaks[0]['latest_body_peak_price']
#         exe_orders = [order_make_dir0_s(peaks_class, params['c'], target_price,
#                                         peaks_class.cal_move_ave(params['margin']), -1,
#                                         peaks_class.cal_move_ave(params['tp']),
#                                         peaks_class.cal_move_ave(params['lc']),
#                                         params['lc_change'],
#                                         1)]
#
#     # if total_strength_of_1 > 8:  #最初は　>=10 と　>8
#     #     # 抵抗がかなり強い場合 (元々
#     #     return default_return_item
#
#     # if not is_over and not is_latest_skip_hard:
#     #     print("越えてない、かつ、直近スキップなし")  # > の向きが越える
#     #     comment = "越えている場合"  # Peak[0]のほうが適切化も？？
#     #     target_price = peaks[0]['latest_body_peak_price']
#     #     exe_orders = [order_make_dir0_s(peaks_class, comment, target_price,
#     #                                     # peaks_class.cal_move_ave(1), 1,
#     #                                     # peaks_class.cal_move_ave(3),
#     #                                     # peaks_class.cal_move_ave(1),
#     #                                     # 3)]
#     #                                     peaks_class.cal_move_ave(1), -1,
#     #                                     peaks_class.cal_move_ave(3),
#     #                                     peaks_class.cal_move_ave(1),
#     #                                     3)]
#     #     # return default_return_item
#     # else:
#     #     return default_return_item
#
#     # if is_over and not is_latest_skip_hard:
#     #     print("越えてる、かつ、直近スキップなし")  # > の向きが越える
#     #     comment = "越えている場合"  # Peak[0]のほうが適切化も？？
#     #     target_price = peaks[0]['latest_body_peak_price']
#     #     exe_orders = [order_make_dir0_s(peaks_class, comment, target_price,
#     #                                     peaks_class.cal_move_ave(1), 1,
#     #                                     peaks_class.cal_move_ave(3),
#     #                                     peaks_class.cal_move_ave(1),
#     #                                     3)]
#     #                                     # peaks_class.cal_move_ave(1), -1,
#     #                                     # peaks_class.cal_move_ave(3),
#     #                                     # peaks_class.cal_move_ave(1),
#     #                                     # 3)]  # 3=offence 1=difence
#     # # #     # return default_return_item
#     # else:
#     #     return default_return_item
#
#     # if is_over:# and is_latest_skip_hard:
#     #     print("越えてる、かつ、直近スキップなし")  # > の向きが越える
#     #     comment = "越えている場合"  # Peak[0]のほうが適切化も？？
#     #     target_price = peaks[0]['latest_body_peak_price']
#     #     exe_orders = [order_make_dir0_s(peaks_class, comment, target_price,
#     #                                     peaks_class.cal_move_ave(1), 1,
#     #                                     peaks_class.cal_move_ave(3),
#     #                                     peaks_class.cal_move_ave(1),
#     #                                     3)]
#     # #                                     peaks_class.cal_move_ave(1), -1,
#     # #                                     peaks_class.cal_move_ave(3),
#     # #                                     peaks_class.cal_move_ave(1),
#     # #                                     3)]
#     # # #     # return default_return_item
#     # else:
#     #     return default_return_item
#
#     # if not is_over:
#     #     print("越ない場合(スキップ不問）")  # > の向きが越える
#     #     comment = "越ない場合場合(スキップ不問)"  # Peak[0]のほうが適切化も？？
#     #     target_price = peaks[0]['latest_body_peak_price']
#     #     exe_orders = [order_make_dir1_s(peaks_class, comment, target_price,
#     #                                     # peaks_class.cal_move_ave(1), 1,
#     #                                     # peaks_class.cal_move_ave(3),
#     #                                     # peaks_class.cal_move_ave(1),
#     #                                     # 3)]
#     #                                     peaks_class.cal_move_ave(1), -1,
#     #                                     peaks_class.cal_move_ave(3),
#     #                                     peaks_class.cal_move_ave(1),
#     #                                     3)]
#     #     # return default_return_item
#     # else:
#     #     return default_return_item
#
#     # if is_over:
#     #     print("越ある場合(スキップ不問）")  # > の向きが越える
#     #     comment = "越ある場合場合(スキップ不問)"  # Peak[0]のほうが適切化も？？
#     #     target_price = peaks[0]['latest_body_peak_price']
#     #     exe_orders = [order_make_dir0_s(peaks_class, comment, target_price,
#     #                                     peaks_class.cal_move_ave(1), 1,
#     #                                     peaks_class.cal_move_ave(3),
#     #                                     peaks_class.cal_move_ave(1),
#     #                                     3)]
#     #                                     # peaks_class.cal_move_ave(1), -1,
#     #                                     # peaks_class.cal_move_ave(3),
#     #                                     # peaks_class.cal_move_ave(1),
#     #                                     # 3)]
#     #     # return default_return_item
#     # else:
#     #     return default_return_item
#
#     # if is_over and not is_latest_skip_hard:
#     #     print("越えてる、かつ、直近スキップなし")  # > の向きが越える
#     #     comment = "越えている場合"  # Peak[0]のほうが適切化も？？
#     #     target_price = peaks[0]['latest_body_peak_price']
#     #     exe_orders = [order_make_dir1_s(peaks_class, comment, target_price,
#     #                                     peaks_class.cal_move_ave(1), 1,
#     #                                     peaks_class.cal_move_ave(3),
#     #                                     peaks_class.cal_move_ave(1),
#     #                                     3)]
#     #                                     # peaks_class.cal_move_ave(1), -1,
#     #                                     # peaks_class.cal_move_ave(3),
#     #                                     # peaks_class.cal_move_ave(1),
#     #                                     # 3)]
#     # #     # return default_return_item
#     # else:
#     #     return default_return_item
#     return {
#         "take_position_flag": True,
#         "exe_orders": exe_orders,
#         "for_inspection_dic": {}
#     }


def order_make_dir0_s(peaks_class, comment, target_num, margin, margin_dir, tp, lc, lc_change, uni_base_time, priority, alert):
    """
    基本的に[0]の方向にオーダーを出すSTOPを想定
    target_num: オーダーの起点となるPeak.
    margin: どれくらいのマージンを取るか
    margin_dir: 1の場合取得しにくい方向に、－1の場合取得しやすいほうに
    tp:TPの価格かレンジ
    lc:lcの価格かレンジ
    """
    # 履歴によるオーダー調整を実施する（TPを拡大する）

    # 必要項目を取得
    peaks = peaks_class.skipped_peaks
    order_dir = peaks[0]['direction']

    for_history_class = classPosition.order_information("test", "test", False)  # 履歴参照用
    tuned_data = for_history_class.tuning_by_history_break()
    if tuned_data['is_previous_lose']:
        units = 2 * uni_base_time  # 負けてるときは倍プッシュ
        comment = comment + "倍プッシュ"
    else:
        units = 1 * uni_base_time
        # comment = comment + " [" + str(tuned_data['is_previous_lose']) + "]"
        comment = comment + " [通常]"

    # targetの設定
    if target_num <= 5:
        # target_numが、添え字とみなす場合
        target = round(peaks[target_num]['latest_wick_peak_price'] + (margin * order_dir) * margin_dir, 3)
    else:
        # target_numが、添え字ではなく、直接価格を指定している場合
        target = round(target_num + (margin * order_dir) * margin_dir * 1, 3)

    # STOPオーダー専用のため、おかしな場合は、エラーを出す
    now_price = peaks_class.latest_price
    if order_dir == 1:
        if target >= now_price:
            type = "STOP"
            print("  [1]と同じ1方向のSTOPオーダー　", order_dir, target, ">=", now_price)
        else:
            type = "LIMIT"
            print("  [1]と同じ1方向のLIMITオーダー　", order_dir, target, "<", now_price)
    else:
        if target <= now_price:
            type = "STOP"
            print("  [1]と同じ-1方向のSTOPオーダー　", order_dir, target, "<=", now_price)
        else:
            type = "LIMIT"
            print("  [1]と同じ-1方向のLIMITオーダー　", order_dir, target, ">", now_price)

    # flag形状の場合（＝Breakの場合）
    base_order_dic = {
        # targetはプラスで取得しにくい方向に。
        "target": target,
        "type": "STOP",
        "expected_direction": order_dir,
        # "tp": tp_range,  # 短期では0.15でもOK.ただ長期だと、マイナスの平均が0.114のためマイナスの数が多くなる
        # # "lc": 0.09,  # 0.06,
        # "tp": 0.075,
        # "lc": 0.075,
        "tp": tp,
        "lc": lc,
        'priority': 3,
        "decision_time": peaks_class.df_r_original.iloc[0]['time_jp'],
        "decision_price": peaks_class.df_r_original.iloc[1]['close'],
        "order_timeout_min": 20,
        "lc_change_type": lc_change,
        "alert": {"range": alert, "time": 0},
        "units": units,
        "name": comment,
        "order_permission":False,
        "ref": {"move_ave": peaks_class.cal_move_ave(1),
                "peak1_target_gap": abs(peaks[1]['latest_body_peak_price'] - target)
                }
    }
    base_order_class = OCreate.OrderCreateClass(base_order_dic)  # オーダーファイナライズ
    # オーダーの修正と、場合によって追加オーダー設定
    # lc_max = 0.15
    # lc_change_after = 0.075
    # if base_order_class.finalized_order['lc_range'] >= lc_max:
    #     # LCレンジを計算してLCが大きすぎた場合、オーダー修正（LC短縮）
    #     print("LCが大きいため再オーダー設定")
    #     base_order_dic['lc'] = lc_change_after
    #     base_order_dic['name'] = base_order_dic['name'] + "_LC大で修正_"
    #     base_order_class = OCreate.OrderCreateClass(base_order_dic)  # オーダー生成（というか作り直し）
    # else:
    #     base_order_class = OCreate.OrderCreateClass(base_order_dic)
    return base_order_class.finalized_order

def order_make_dir1_s(peaks_class, comment, target_num, margin, margin_dir, tp, lc, lc_change, uni_base_time, priority, alert):
    """
    基本的に[1]の方向にオーダーを出すSTOPオーダー
    target_num: オーダーの起点となるPeak.
    margin: どれくらいのマージンを取るか
    margin_dir: 1の場合取得しにくい方向に、－1の場合取得しやすいほうに
    tp:TPの価格かレンジ
    lc:lcの価格かレンジ
    """
    # 履歴によるオーダー調整を実施する（TPを拡大する）

    # 必要項目を取得
    peaks = peaks_class.skipped_peaks
    order_dir = peaks[1]['direction']

    for_history_class = classPosition.order_information("test", "test", False)  # 履歴参照用
    tuned_data = for_history_class.tuning_by_history_break()
    if tuned_data['is_previous_lose']:
        units = 2 * uni_base_time  # 負けてるときは倍プッシュ
        comment = comment + "倍プッシュ"
    else:
        units = 1 * uni_base_time
        # comment = comment + " [" + str(tuned_data['is_previous_lose']) + "]"
        comment = comment + " [通常]"

    # targetの設定
    if 0 <= target_num <= 5:
        # target_numが、添え字とみなす場合
        target = round(peaks[target_num]['latest_wick_peak_price'] + (margin * order_dir) * margin_dir, 3)
    else:
        # target_numが、添え字ではなく、直接価格を指定している場合
        target = round(target_num + (margin * order_dir) * margin_dir * 1, 3)

    # STOPオーダー専用のため、おかしな場合は、エラーを出す
    now_price = peaks_class.latest_price
    if order_dir == 1:
        if target >= now_price:
            type = "STOP"
            print("  [1]と同じ1方向のSTOPオーダー　", order_dir, target, ">=", now_price)
        else:
            type = "LIMIT"
            print("  [1]と同じ1方向のLIMITオーダー　", order_dir, target, "<", now_price)
    else:
        if target <= now_price:
            type = "STOP"
            print("  [1]と同じ-1方向のSTOPオーダー　", order_dir, target, "<=", now_price)
        else:
            type = "LIMIT"
            print("  [1]と同じ-1方向のLIMITオーダー　", order_dir, target, ">", now_price)

    # flag形状の場合（＝Breakの場合）
    base_order_dic = {
        # targetはプラスで取得しにくい方向に。
        "target": target,
        "type": type,  # "STOP",
        "expected_direction": order_dir,
        # "tp": tp_range,  # 短期では0.15でもOK.ただ長期だと、マイナスの平均が0.114のためマイナスの数が多くなる
        # # "lc": 0.09,  # 0.06,
        # "tp": 0.075,
        # "lc": 0.075,
        "tp": tp,
        "lc": lc,
        'priority': 3,
        "decision_time": peaks_class.df_r_original.iloc[0]['time_jp'],
        "decision_price": peaks_class.df_r_original.iloc[1]['close'],
        "order_timeout_min": 20,
        "lc_change_type": lc_change,
        "units": units,
        "name": comment,
        "order_permission": False,
        "alert": {"range": alert, "time": 0},
        "ref": {"move_ave": peaks_class.cal_move_ave(1),
                "peak1_target_gap": abs(peaks[1]['latest_body_peak_price'] - target)
                }
    }
    base_order_class = OCreate.OrderCreateClass(base_order_dic)  # オーダーファイナライズ
    # オーダーの修正と、場合によって追加オーダー設定
    # lc_max = 0.15
    # lc_change_after = 0.075
    # if base_order_class.finalized_order['lc_range'] >= lc_max:
    #     # LCレンジを計算してLCが大きすぎた場合、オーダー修正（LC短縮）
    #     print("LCが大きいため再オーダー設定")
    #     base_order_dic['lc'] = lc_change_after
    #     base_order_dic['name'] = base_order_dic['name'] + "_LC大で修正_"
    #     base_order_class = OCreate.OrderCreateClass(base_order_dic)  # オーダー生成（というか作り直し）
    # else:
    #     base_order_class = OCreate.OrderCreateClass(base_order_dic)
    return base_order_class.finalized_order


#
#
# def order_make_dir0_l(peaks_class, comment, target_num, margin, margin_dir, tp, lc):
#     """
#     基本的に[0]の方向にオーダーを出すLIMITを想定
#     target_num: オーダーの起点となるPeak.
#     margin: どれくらいのマージンを取るか
#     margin_dir: 1の場合取得しにくい方向に、－1の場合取得しやすいほうに
#     tp:TPの価格かレンジ
#     lc:lcの価格かレンジ
#     """
#     # 履歴によるオーダー調整を実施する（TPを拡大する）
#
#     # 必要項目を取得
#     peaks = peaks_class.skipped_peaks
#     order_dir = peaks[0]['direction']
#
#     # flag形状の場合（＝Breakの場合）
#     base_order_dic = {
#         # targetはプラスで取得しにくい方向に。
#         "target": peaks[target_num]['latest_wick_peak_price'] + (margin * order_dir) * (margin_dir * -1),
#         "type": "STOP",
#         "expected_direction": order_dir,
#         # "tp": tp_range,  # 短期では0.15でもOK.ただ長期だと、マイナスの平均が0.114のためマイナスの数が多くなる
#         # # "lc": 0.09,  # 0.06,
#         # "tp": 0.075,
#         # "lc": 0.075,
#         "tp": tp,
#         "lc": lc,
#         'priority': 3,
#         "decision_time": peaks_class.df_r_original.iloc[0]['time_jp'],
#         "decision_price": peaks_class.df_r_original.iloc[1]['close'],
#         "order_timeout_min": 20,
#         "lc_change_type": 1,
#         "name": comment
#     }
#     base_order_class = OCreate.OrderCreateClass(base_order_dic)  # オーダーファイナライズ
#     # オーダーの修正と、場合によって追加オーダー設定
#     # lc_max = 0.15
#     # lc_change_after = 0.075
#     # if base_order_class.finalized_order['lc_range'] >= lc_max:
#     #     # LCレンジを計算してLCが大きすぎた場合、オーダー修正（LC短縮）
#     #     print("LCが大きいため再オーダー設定")
#     #     base_order_dic['lc'] = lc_change_after
#     #     base_order_dic['name'] = base_order_dic['name'] + "_LC大で修正_"
#     #     base_order_class = OCreate.OrderCreateClass(base_order_dic)  # オーダー生成（というか作り直し）
#     # else:
#     #     base_order_class = OCreate.OrderCreateClass(base_order_dic)
#     return base_order_class.finalized_order
#
#
# def order_make_dir1_l(peaks_class, comment, target_num, margin, margin_dir, tp, lc):
#     """
#     基本的に[1]の方向にオーダーを出す場合（Breakに相当）。基本的にLIMITオーダーを想定（STOPもあり得る）
#     target_num: オーダーの起点となるPeak.
#     margin: どれくらいのマージンを取るか
#     margin_dir: 1の場合取得しにくい方向に、－1の場合取得しやすいほうに
#     tp:TPの価格かレンジ
#     lc:lcの価格かレンジ
#     """
#     # 履歴によるオーダー調整を実施する（TPを拡大する）
#
#     # 必要項目を取得
#     peaks = peaks_class.skipped_peaks
#     order_dir = peaks[1]['direction']
#     # targetの設定
#     if target_num <= 5:
#         # target_numが、添え字とみなす場合
#         print("髭価格", peaks[target_num]['latest_wick_peak_price'])
#         target = peaks[target_num]['latest_wick_peak_price'] + (margin * order_dir) * (margin_dir * -1)
#     else:
#         # target_numが、添え字ではなく、直接価格を指定している場合
#         target = target_num + (margin * order_dir) * (margin_dir * -1)
#
#     # flag形状の場合（＝Breakの場合）
#     base_order_dic = {
#         # targetはプラスで取得しにくい方向に。
#         "target": target,
#         "type": "LIMIT",
#         "expected_direction": order_dir,
#         # "tp": tp_range,  # 短期では0.15でもOK.ただ長期だと、マイナスの平均が0.114のためマイナスの数が多くなる
#         # # "lc": 0.09,  # 0.06,
#         # "tp": 0.075,
#         # "lc": 0.075,
#         "tp": tp,
#         "lc": lc,
#         'priority': 3,
#         "decision_time": peaks_class.df_r_original.iloc[0]['time_jp'],
#         "decision_price": peaks_class.df_r_original.iloc[1]['close'],
#         "order_timeout_min": 20,
#         "lc_change_type": 1,
#         "name": comment
#     }
#     base_order_class = OCreate.OrderCreateClass(base_order_dic)  # オーダーファイナライズ
#     # オーダーの修正と、場合によって追加オーダー設定
#     # lc_max = 0.15
#     # lc_change_after = 0.075
#     # if base_order_class.finalized_order['lc_range'] >= lc_max:
#     #     # LCレンジを計算してLCが大きすぎた場合、オーダー修正（LC短縮）
#     #     print("LCが大きいため再オーダー設定")
#     #     base_order_dic['lc'] = lc_change_after
#     #     base_order_dic['name'] = base_order_dic['name'] + "_LC大で修正_"
#     #     base_order_class = OCreate.OrderCreateClass(base_order_dic)  # オーダー生成（というか作り直し）
#     # else:
#     #     base_order_class = OCreate.OrderCreateClass(base_order_dic)
#     return base_order_class.finalized_order
#


# def break_order(peaks, peaks_class, comment, same_price_list):
#
#     same_price_len=len(same_price_list)
#     if same_price_len<=3:
#         same_price_len=3
#     else:
#         same_price_len=4
#
#     # ★★履歴によるオーダー調整を実施する（TPを拡大する）★★★
#     for_history_class = classPosition.order_information("test", "test", False)  # 履歴参照用
#     tuned_data = for_history_class.tuning_by_history_break()  # TuneされたTPやLCChangeを取得する
#     tp_range = tuned_data['tuned_tp_range']
#     lc_change_type = tuned_data['tuned_lc_change_type']
#     print("TP設定", tp_range, "lcChange設定", lc_change_type)
#
#     # flag形状の場合（＝Breakの場合）
#     base_order_dic = {
#         "target": peaks[1]['latest_wick_peak_price'] + (0.006 * peaks[1]['direction']),
#         "type": "STOP",
#         "expected_direction": peaks[1]['direction'],
#         # "tp": tp_range,  # 短期では0.15でもOK.ただ長期だと、マイナスの平均が0.114のためマイナスの数が多くなる
#         # # "lc": 0.09,  # 0.06,
#         # "tp": 0.075,
#         # "lc": 0.075,
#         "tp": 0.075,
#         "lc": peaks_class.ave_move_for_lc,
#         'priority': 3,
#         "decision_time": peaks_class.df_r_original.iloc[0]['time_jp'],
#         "decision_price": peaks_class.df_r_original.iloc[1]['close'],
#         "order_timeout_min": 20,
#         "lc_change_type": 0,
#         "name": comment
#     }
#     base_order_class = OCreate.OrderCreateClass(base_order_dic)  # オーダーファイナライズ
#
#     # オーダーの修正と、場合によって追加オーダー設定
#     # lc_max = 0.15
#     # lc_change_after = 0.075
#     # if base_order_class.finalized_order['lc_range'] >= lc_max:
#     #     # LCレンジを計算してLCが大きすぎた場合、オーダー修正（LC短縮）
#     #     print("LCが大きいため再オーダー設定")
#     #     base_order_dic['lc'] = lc_change_after
#     #     base_order_dic['name'] = base_order_dic['name'] + "_LC大で修正_"
#     #     base_order_class = OCreate.OrderCreateClass(base_order_dic)  # オーダー生成（というか作り直し）
#     # else:
#     #     base_order_class = OCreate.OrderCreateClass(base_order_dic)
#     return base_order_class.finalized_order
#
#
# def resistance_order(peaks, peaks_class, comment, target_num):
#     target_peak = peaks[target_num]
#
#     # ★★履歴によるオーダー調整を実施する（TPを拡大する）★★★
#     for_history_class = classPosition.order_information("test", "test", False)  # 履歴参照用
#     tuned_data = for_history_class.tuning_by_history_break()  # TuneされたTPやLC.finalized_orderChangeを取得する
#     tp_range = tuned_data['tuned_tp_range']
#     lc_change_type = tuned_data['tuned_lc_change_type']
#     print("TP設定", tp_range, "lcChange設定", lc_change_type)
#
#     target_price = target_peak['peak'] + (peaks[0]['direction'] * 0.001)
#     lc_price = OCreate.cal_lc_price_from_line_and_margin(peaks[1]['latest_wick_peak_price'], 0.03,
#                                                          peaks[0]['direction'])
#     gap = abs(lc_price - target_price)
#     re_lc_range = gene.cal_at_most(0.09, gap)
#     print("Orderのgap確認", gap, "target_price:", target_price, "deci_price:",
#           peaks_class.df_r_original.iloc[1]['close'])
#     base_order_dic = {
#         "target": target_price,
#         "type": "LIMIT",
#         "expected_direction": peaks[0]['direction'] * -1,
#         # "tp": tp_range,  # 短期では0.15でもOK.ただ長期だと、マイナスの平均が0.114のためマイナスの数が多くなる
#         # "lc": lc_price,  # 0.06,
#         "tp": peaks[1]['latest_body_peak_price'],  #0.03,
#         "lc": peaks_class.cal_move_ave(1),
#         # "lc": peaks_class.ave_move_for_lc,
#         # "lc": 0.4,
#         'priority': 4,
#         "decision_time": peaks_class.df_r_original.iloc[0]['time_jp'],
#         "decision_price": peaks_class.df_r_original.iloc[1]['close'],
#         "order_timeout_min": 90,
#         "lc_change_type": 1,
#         "name": "PredictLineOrder"
#     }
#     base_order_class = OCreate.OrderCreateClass(base_order_dic)  # オーダー生成
#     # gene.print_json(base_order_class.finalized_order_without_lc_change)  # 表示
#
#     # オーダーの修正と、場合によって追加オーダー設定
#     lc_max = 0.15
#     lc_change_after = 0.075
#     if base_order_class.finalized_order['lc_range'] >= lc_max:
#         # LCレンジを計算してLCが大きすぎた場合、オーダー修正（LC短縮）
#         print("LCが大きいため再オーダー設定")
#         base_order_dic['lc'] = lc_change_after
#         base_order_dic['name'] = base_order_dic['name'] + "_LC大で修正_"
#         base_order_class = OCreate.OrderCreateClass(base_order_dic)  # オーダー生成（というか作り直し）
#     else:
#         base_order_class = OCreate.OrderCreateClass(base_order_dic)
#
#     return base_order_class.finalized_order
#
#
# def resistance_order_weak(peaks, peaks_class, comment, target_num):
#     """
#     各進度が弱いため、LCを狭くしたもの
#     """
#     print("オーダー生成　レジデンスウィーク")
#     target_peak = peaks[target_num]
#
#     # ★★履歴によるオーダー調整を実施する（TPを拡大する）★★★
#     for_history_class = classPosition.order_information("test", "test", False)  # 履歴参照用
#     tuned_data = for_history_class.tuning_by_history_break()  # TuneされたTPやLC.finalized_orderChangeを取得する
#     tp_range = tuned_data['tuned_tp_range']
#     lc_change_type = tuned_data['tuned_lc_change_type']
#     print("TP設定", tp_range, "lcChange設定", lc_change_type)
#     print("target_num確認表示", target_num)
#
#     # peak[1]からのレジスタンス方向のため、peak[0]方向のポジション。その為、＋だと取得しにくく、ーだと取得しやすくなる
#     target_price = target_peak['peak'] + (peaks[0]['direction'] * peaks_class.cal_move_ave(1))  # 0.4もよかった
#     lc_price = OCreate.cal_lc_price_from_line_and_margin(peaks[1]['latest_wick_peak_price'], 0.03,
#                                                          peaks[0]['direction'])
#     gap = abs(lc_price - target_price)
#     re_lc_range = gene.cal_at_most(0.09, gap)
#     print("gap確認", gap, "target_price:", target_price, "deci_price:",
#           peaks_class.df_r_original.iloc[1]['close'])
#     print("Peak2のGap確認", peaks[0]['gap'], peaks[0]['latest_time_jp'])
#     base_order_dic = {
#         "target": target_price,
#         "type": "LIMIT",
#         "expected_direction": peaks[0]['direction'],
#         # "tp": tp_range,  # 短期では0.15でもOK.ただ長期だと、マイナスの平均が0.114のためマイナスの数が多くなる
#         # "lc": lc_price,  # 0.06,
#         # "tp": gene.cal_at_least(0.1, peaks_class.cal_move_size_lc(1.5)),
#         "tp": 0.5,
#         "lc": peaks_class.cal_move_ave(0.8),
#         # "lc": peaks_class.ave_move_for_lc,
#         # "lc": 0.4,
#         'priority': 4,
#         "decision_time": peaks_class.df_r_original.iloc[0]['time_jp'],
#         "decision_price": peaks_class.df_r_original.iloc[1]['close'],
#         "order_timeout_min": 90,
#         "lc_change_type": 1,
#         "name": "■PredictLineOrder"
#     }
#     base_order_class = OCreate.OrderCreateClass(base_order_dic)  # オーダー生成
#     # gene.print_json(base_order_class.finalized_order_without_lc_change)  # 表示
#
#     # オーダーの修正と、場合によって追加オーダー設定
#     # lc_max = 0.15
#     # lc_change_after = 0.075
#     # if base_order_class.finalized_order['lc_range'] >= lc_max:
#     #     # LCレンジを計算してLCが大きすぎた場合、オーダー修正（LC短縮）
#     #     print("LCが大きいため再オーダー設定")
#     #     base_order_dic['lc'] = lc_change_after
#     #     base_order_dic['name'] = base_order_dic['name'] + "_LC大で修正_"
#     #     base_order_class = OCreate.OrderCreateClass(base_order_dic)  # オーダー生成（というか作り直し）
#     # else:
#     #     base_order_class = OCreate.OrderCreateClass(base_order_dic)
#
#     return base_order_class.finalized_order
#
#
# def resistance_order_strong(peaks, peaks_class, comment, target_num):
#     """
#     確信度がそこそこ強いため、LCを少し強めに
#     """
#     print("オーダー生成　レジデンスストロング")
#     target_peak = peaks[target_num]
#
#     # ★★履歴によるオーダー調整を実施する（TPを拡大する）★★★
#     for_history_class = classPosition.order_information("test", "test", False)  # 履歴参照用
#     tuned_data = for_history_class.tuning_by_history_break()  # TuneされたTPやLC.finalized_orderChangeを取得する
#     tp_range = tuned_data['tuned_tp_range']
#     lc_change_type = tuned_data['tuned_lc_change_type']
#     print("TP設定", tp_range, "lcChange設定", lc_change_type)
#     print("target_num確認表示", target_num)
#
#     # peak[1]からのレジスタンス方向のため、peak[0]方向のポジション。その為、＋だと取得しにくく、ーだと取得しやすくなる
#     target_price = target_peak['peak'] + (peaks[0]['direction'] * peaks_class.cal_move_ave(0.01))  # 0.2
#     lc_price = OCreate.cal_lc_price_from_line_and_margin(peaks[1]['latest_wick_peak_price'], 0.03,
#                                                          peaks[0]['direction'])
#     gap = abs(lc_price - target_price)
#     re_lc_range = gene.cal_at_most(0.09, gap)
#     print("gap確認", gap, "target_price:", target_price, "deci_price:",
#           peaks_class.df_r_original.iloc[1]['close'])
#     print("Peak2のGap確認", peaks[0]['gap'], peaks[0]['latest_time_jp'])
#     base_order_dic = {
#         "target": target_price,
#         "type": "LIMIT",
#         "expected_direction": peaks[0]['direction'],
#         # "tp": tp_range,  # 短期では0.15でもOK.ただ長期だと、マイナスの平均が0.114のためマイナスの数が多くなる
#         # "lc": lc_price,  # 0.06,
#         # "tp": gene.cal_at_least(0.1, peaks_class.cal_move_size_lc(1.5)),
#         "tp": 0.5,
#         "lc": peaks_class.cal_move_ave(1.5),
#         # "lc": peaks_class.ave_move_for_lc,
#         # "lc": 0.4,
#         'priority': 4,
#         "decision_time": peaks_class.df_r_original.iloc[0]['time_jp'],
#         "decision_price": peaks_class.df_r_original.iloc[1]['close'],
#         "order_timeout_min": 90,
#         "lc_change_type": 1,
#         "name": "■PredictLineOrder"
#     }
#     base_order_class = OCreate.OrderCreateClass(base_order_dic)  # オーダー生成
#     # gene.print_json(base_order_class.finalized_order_without_lc_change)  # 表示
#
#     # オーダーの修正と、場合によって追加オーダー設定
#     # lc_max = 0.15
#     # lc_change_after = 0.075
#     # if base_order_class.finalized_order['lc_range'] >= lc_max:
#     #     # LCレンジを計算してLCが大きすぎた場合、オーダー修正（LC短縮）
#     #     print("LCが大きいため再オーダー設定")
#     #     base_order_dic['lc'] = lc_change_after
#     #     base_order_dic['name'] = base_order_dic['name'] + "_LC大で修正_"
#     #     base_order_class = OCreate.OrderCreateClass(base_order_dic)  # オーダー生成（というか作り直し）
#     # else:
#     #     base_order_class = OCreate.OrderCreateClass(base_order_dic)
#
#     return base_order_class.finalized_order
#
#
# def break_order_week(peaks, peaks_class, comment, same_price_list):
#     print("オーダー生成　ブレイクウィーク")
#     # ★★履歴によるオーダー調整を実施する（TPを拡大する）★★★
#     for_history_class = classPosition.order_information("test", "test", False)  # 履歴参照用
#     tuned_data = for_history_class.tuning_by_history_break()  # TuneされたTPやLCChangeを取得する
#     tp_range = tuned_data['tuned_tp_range']
#     lc_change_type = tuned_data['tuned_lc_change_type']
#     print("TP設定", tp_range, "lcChange設定", lc_change_type)
#
#     # flag形状の場合（＝Breakの場合）
#     base_order_dic = {
#         # 指定価格-整数は取得しやすくなる方向。指定価格＋整数は取得しにくくなる方向
#         "target": peaks[1]['latest_wick_peak_price'] + (peaks_class.cal_move_ave(0.5) * peaks[1]['direction']),
#         # "target": peaks[1]['latest_wick_peak_price'] + (peaks_class.cal_move_size_lc(1) * peaks[1]['direction']),
#         "type": "STOP",
#         "expected_direction": peaks[1]['direction'],
#         # "tp": tp_range,  # 短期では0.15でもOK.ただ長期だと、マイナスの平均が0.114のためマイナスの数が多くなる
#         # # "lc": 0.09,  # 0.06,
#         # "tp": 0.075,
#         # "lc": 0.075,
#         "tp": gene.cal_at_least(0.05, peaks_class.cal_move_ave(1.5)),
#         # "lc": gene.cal_at_least(0.05, peaks_class.cal_move_size_lc(1)),
#         # "tp": peaks_class.cal_move_size_lc(1.8),
#         "lc": peaks[2]['latest_wick_peak_price'],
#         'priority': 3,
#         "decision_time": peaks_class.df_r_original.iloc[0]['time_jp'],
#         "decision_price": peaks_class.df_r_original.iloc[1]['close'],
#         "order_timeout_min": 20,
#         "lc_change_type": 3,
#         "name": comment + "Break"
#     }
#     base_order_class = OCreate.OrderCreateClass(base_order_dic)  # オーダーファイナライズ
#
#     # オーダーの修正と、場合によって追加オーダー設定
#     lc_max = 0.25
#     lc_change_after = 0.25
#     if base_order_class.finalized_order['lc_range'] >= lc_max:
#         # LCレンジを計算してLCが大きすぎた場合、オーダー修正（LC短縮）
#         print("LCが大きいため再オーダー設定")
#         base_order_dic['lc'] = lc_change_after
#         base_order_dic['name'] = base_order_dic['name'] + "_LC大で修正_"
#         base_order_class = OCreate.OrderCreateClass(base_order_dic)  # オーダー生成（というか作り直し）
#     else:
#         base_order_class = OCreate.OrderCreateClass(base_order_dic)
#
#     return base_order_class.finalized_order
#

# 以下保存用

# def cal_predict_turn2(peaks_class):
#     """
#     args[0]は必ずpeaks_classであること。
#     args[1]は、本番の場合、過去の決済履歴のマイナスの大きさでTPが変わるかを検討したいため、オーダークラスを受け取る
#
#     直近[0]がcount4の時、riverPeakにレジスタンスオーダーを入れる
#     """
#     # ■基本情報の取得
#     print("★★PREDICT　TURN2222")
#     take_position = False
#     # ■返却値の設定
#     default_return_item = {
#         "take_position_flag": take_position,
#         "for_inspection_dic": {}
#     }
#     s = "    "
#
#     # ■Peaks等、大事な変数の設定
#     # ターゲットになるピークを選択
#     target_num = 1  # 以下のループで「自分以外」を定義するため、変数に入れておく(同一方向の配列に対して）
#     peaks = peaks_class.peaks_original_marked_hard_skip
#     # peaks = peaks_class.skipped_peaks
#     target_peak = peaks[target_num]
#     # print("ターゲットになるピーク:", target_peak['peak'], target_peak)
#
#     # ■実行除外
#     # latestのカウントが既定の物かを確認
#     if peaks[0]['count'] == 3:  # and peaks[1]['count'] >= 3:  # [0]countは２では微妙（２はBreakのケースが多く見える）ので３．
#         print("　カウント数は合格", peaks[0]['count'], "が4以上が対象")
#     else:
#         print("  山を形成するカウント不足", peaks[0]['count'], "が4以上が対象")
#         return default_return_item
#     # 対象のPeakのサイズを確認（小さすぎる場合、除外）
#     if peaks[1]['gap'] < 0.04:
#         print("対象が小さい", peaks[1]['gap'])
#         return default_return_item
#
#     # ■判定に必要な数字の算出
#     # 1 強度の判定
#     peaks_class.make_same_price_list(target_num, False)  # クラス内でSamePriceListを実行
#     print("同一価格リスト（抵抗線強度検討用）")
#     gene.print_arr(peaks_class.same_price_list)
#     total_strength_of_1 = sum(d["item"]["peak_strength"] for d in peaks_class.same_price_list)
#     print("samePriceListの強度の合計値;", total_strength_of_1)
#     #    10以上だと強い⇒抵抗OrderのLCを小さくとる（越えた場合大きく越えそう）
#     #    なんなら、その場合はBreakOrderも出してみたい。
#
#     # ■判
#     if total_strength_of_1 >= 10:
#         # 抵抗がかなり強い場合 (元々
#         return default_return_item
#
#     if total_strength_of_1 > 8:
#         # 抵抗が強すぎる場合 (target1の抵抗[同一価格リスト]が8以上ある)（これどうしよう・・？）
#         # ８は最小最大の既定の数字なので、７くらいがよい・・？
#         return default_return_item
#
#     # include_large': False, 'include_very_large'
#     # includeをSKIPP作成時に考慮できていない！！！！！！
#     # if peaks[0]['include_large'] or peaks[1]['include_large'] or peaks[2]['include_large']:
#     #     print("ラージあるため、スキップ", peaks[0]['include_large'], peaks[1]['include_large'], peaks[2]['include_large'])
#     #     return default_return_item
#
#     # 直近がスキップがあったかを確認したい
#     if peaks_class.cal_target_times_skip_num(peaks_class.skipped_peaks_hard, peaks[1]['latest_time_jp']) >= 1:
#         print("直近でSKIPがあった（急変動有？）")
#         comment = "直近でSKIPあり⇒[1]方向に突破予想"
#         # パターン１　少し[0]が同方向に進んだ位置に、逆張りオーダー([1])を仕掛ける
#         # これ割といいパターンがあるので、捨てにくい。
#         target_price = peaks[0]['latest_body_peak_price']
#         exe_orders = [order_make_dir1_s(peaks_class, comment, target_price,
#                                         # peaks_class.cal_move_ave(1), 1,
#                                         # peaks_class.cal_move_ave(3),
#                                         # peaks_class.cal_move_ave(1),
#                                         # 3)]
#                                         peaks_class.cal_move_ave(1), -1,
#                                         peaks_class.cal_move_ave(3),
#                                         peaks_class.cal_move_ave(1),
#                                         3)]
#                                         # peaks_class.cal_move_ave(1), 1,
#                                         # peaks_class.cal_move_ave(1.5),
#                                         # peaks_class.cal_move_ave(1.5),
#                                         # 0)]
#                                         # peaks_class.cal_move_ave(1), -1,
#                                         # peaks_class.cal_move_ave(1.5),
#                                         # peaks_class.cal_move_ave(1.5),
#                                         # 0)]
#
#         # return default_return_item
#         # return {
#         #     "take_position_flag": True,
#         #     "exe_orders": exe_orders,
#         #     "for_inspection_dic": {}
#         # }
#     # # else:
#     # #     return default_return_item
#
#
#     if peaks[0]['direction'] * (peaks[0]['latest_body_peak_price'] - peaks[2]['latest_body_peak_price']) >= 0:
#         print("越えている場合")  # > の向きが越える
#         comment = "越えている場合"  # Peak[0]のほうが適切化も？？
#         target_price = peaks[0]['latest_body_peak_price']
#         exe_orders = [order_make_dir0_s(peaks_class, comment, target_price,
#                                         peaks_class.cal_move_ave(1), 1,
#                                         peaks_class.cal_move_ave(3),
#                                         peaks_class.cal_move_ave(1),
#                                         3)]
#                                         # peaks_class.cal_move_ave(1), -1,
#                                         # peaks_class.cal_move_ave(3),
#                                         # peaks_class.cal_move_ave(1),
#                                         # 3)]
#                                         # peaks_class.cal_move_ave(1), 1,
#                                         # peaks_class.cal_move_ave(1.5),
#                                         # peaks_class.cal_move_ave(1.5),
#                                         # 0)]
#                                         # peaks_class.cal_move_ave(1), -1,
#                                         # peaks_class.cal_move_ave(1.5),
#                                         # peaks_class.cal_move_ave(1.5),
#                                         # 0)]
#         # return default_return_item
#         return {
#             "take_position_flag": True,
#             "exe_orders": exe_orders,
#             "for_inspection_dic": {}
#         }
#     else:
#         print("越えていない場合")
#         # if peaks[1]['gap'] >= peaks[0]['gap'] * 3:
#         #     # 長い変動直後の折り返しの場合
#         #     return default_return_item
#
#         # [1]に対して[0]がどの程度戻っているか。0.1の場合は1割り脅し
#         return_ratio_0_1 = peaks[0]['gap'] / peaks[1]['gap']  # 値が大きいほど戻りが強い
#
#         if True:
#         # if return_ratio_0_1 < 0.3:
#             # ★半分まで戻っていない場合、ジグザグ継続上昇（[0]から少し折り返した位置に、順張り）
#             # return default_return_item
#             comment = "抵抗5点の一つのみの抵抗オーダー"  # Peak[0]のほうが適切化も？？
#             print("抵抗線は一つだが、それが5点（直近の最低値）の場合、抵抗線とみなす")
#             target_price = peaks[0]['latest_body_peak_price']
#             exe_orders = [order_make_dir1_s(peaks_class, comment, target_price,
#                                             # peaks_class.cal_move_ave(1), 1,
#                                             # peaks_class.cal_move_ave(3),
#                                             # peaks_class.cal_move_ave(1),
#                                             # 3)]
#                                             peaks_class.cal_move_ave(1), -1,
#                                             peaks_class.cal_move_ave(3),
#                                             peaks_class.cal_move_ave(1),
#                                             3)]
#                                             # peaks_class.cal_move_ave(1), 1,
#                                             # peaks_class.cal_move_ave(1.5),
#                                             # peaks_class.cal_move_ave(1.5),
#                                             # 0)]
#                                             # peaks_class.cal_move_ave(1), -1,
#                                             # peaks_class.cal_move_ave(1.5),
#                                             # peaks_class.cal_move_ave(1.5),
#                                             # 0)]
#             # return default_return_item
#             return {
#                 "take_position_flag": True,
#                 "exe_orders": exe_orders,
#                 "for_inspection_dic": {}
#             }
#         # else:
#         #     return default_return_item
#
#     print("オーダーします")
#     print(exe_orders)
#
#     return {
#         "take_position_flag": True,
#         "exe_orders": exe_orders,
#         "for_inspection_dic": {}
#     }


# def cal_predict_turn2(peaks_class):
#     """
#     args[0]は必ずpeaks_classであること。
#     args[1]は、本番の場合、過去の決済履歴のマイナスの大きさでTPが変わるかを検討したいため、オーダークラスを受け取る
#
#     直近[0]がcount4の時、riverPeakにレジスタンスオーダーを入れる
#     """
#     # ■基本情報の取得
#     print("★★PREDICT　TURN2222")
#     take_position = False
#     # ■返却値の設定
#     default_return_item = {
#         "take_position_flag": take_position,
#         "for_inspection_dic": {}
#     }
#     s = "    "
#
#     # ■Peaks等、大事な変数の設定
#     # ターゲットになるピークを選択
#     target_num = 1  # 以下のループで「自分以外」を定義するため、変数に入れておく(同一方向の配列に対して）
#     peaks = peaks_class.peaks_original_marked_hard_skip
#     # peaks = peaks_class.skipped_peaks
#     target_peak = peaks[target_num]
#     print("ターゲットになるピーク:", target_peak['peak'], target_peak)
#
#     # ■実行除外
#     # latestのカウントが既定の物かを確認
#     if peaks[0]['count'] == 3:  # and peaks[1]['count'] >= 3:  # [0]countは２では微妙（２はBreakのケースが多く見える）ので３．
#         print("　カウント数は合格", peaks[0]['count'], "が4以上が対象")
#     else:
#         print("  山を形成するカウント不足", peaks[0]['count'], "が4以上が対象")
#         return default_return_item
#     # 対象のPeakのサイズを確認（小さすぎる場合、除外）
#     if peaks[1]['gap'] < 0.04:
#         print("対象が小さい", peaks[1]['gap'])
#         return default_return_item
#
#     # ■判定に必要な数字の算出
#     # 1 強度の判定
#     peaks_class.make_same_price_list(target_num, False)  # クラス内でSamePriceListを実行
#     print("同一価格リスト（抵抗線強度検討用）")
#     gene.print_arr(peaks_class.same_price_list)
#     total_strength_of_1 = sum(d["item"]["peak_strength"] for d in peaks_class.same_price_list)
#     print("samePriceListの強度の合計値;", total_strength_of_1)
#     #    10以上だと強い⇒抵抗OrderのLCを小さくとる（越えた場合大きく越えそう）
#     #    なんなら、その場合はBreakOrderも出してみたい。
#     # 2 判定に使うハードスキップ情報の取得
#     hard_peaks = peaks_class.skipped_peaks_hard
#
#     # ■判
#     # 急変動直後を思われる場合群
#     # if hard_peaks[2]['gap'] >= hard_peaks[1]['gap'] * 3:
#     #     return default_return_item
#     #     # 急変動から一瞬落ち着いた部分（[0]の[1]への戻り具合にもよる）⇒　基本的に[2]を突き抜けるBreakを想定。 ５－３
#     #     comment = "急変動後のBreak（2-1間)"
#     #     print(comment, hard_peaks[2]['gap'], ">", hard_peaks[2]['gap'], "*3")
#     #     # target2が一番良い(事実上Market)（感覚的には0だし、2まで戻ってないことを想定していた。。）
#     #     exe_orders = [order_make_dir0_s(peaks_class, comment, 0, 0.01, 1,
#     #                                     peaks_class.cal_move_size_lc(0.8), peaks_class.cal_move_size_lc(1))]
#     # elif hard_peaks[1]['gap'] >= hard_peaks[0]['gap'] * 3:
#     #     return default_return_item
#     #     # 急変動がまさに起こっていそうな場合（急変動から折り返した状態）⇒　[0]は今後すぐに折り返すことを想定。★精度悪い可能性大？
#     #     comment = "急変動中のBreak（2-1間)"
#     #     print(comment, hard_peaks[2]['gap'], ">", hard_peaks[2]['gap'], "*3")
#     #     exe_orders = [order_make_dir1_l(peaks_class, comment, 0, 0.01, 1,
#     #                                     0.1, peaks[2]['latest_wick_peak_price'])]
#     # 急変動後以外の場合
#     # else:
#     # if total_strength_of_1 >= 10:
#     #     # 0の抵抗が強い場合、越えたら突き抜ける(急変動がない前提のため、レジスタンスにするかも？）
#     #     comment = "強抵抗のBreakオーダー"  # これも精度悪いなぁ
#     #     print(comment, total_strength_of_1, "同一価格個数", len(peaks_class.same_price_list))
#     #     exe_orders = [order_make_dir1_s(peaks_class, comment, 1, 0, 1,
#     #                                     peaks_class.cal_move_size_lc(0.8), peaks_class.cal_move_size_lc(0.8))]
#     # else:
#     #     # 抵抗が少ない場合
#     #     if total_strength_of_1 <= 8:  # ８は最小最大の既定の数字なので、７くらいがよい・・？
#     #         # スキップされるレベルの抵抗線群の場合
#     #         if len(peaks_class.same_price_list) == 1 and total_strength_of_1 == 5:
#     #             comment = "抵抗5点の一つのみの抵抗オーダー"
#     #             print("抵抗線は一つだが、それが5点（直近の最低値）の場合、抵抗線とみなす")
#     #             # exe_orders = [resistance_order_weak(peaks, peaks_class, comment, target_num)]
#     #             exe_orders = [order_make_dir1_l(peaks_class, comment, 1, 0, 1,
#     #                                             peaks_class.cal_move_size_lc(0.8),
#     #                                             peaks_class.cal_move_size_lc(0.8))]
#     #         else:
#     #             print("RESI オーダー発行（弱抵抗）", total_strength_of_1)
#     #             comment = "弱抵抗の抵抗オーダー"
#     #             # exe_orders = [resistance_order_weak(peaks, peaks_class, "Predict抵抗2", target_num)]
#     #             # exe_orders = [break_order_week(peaks, peaks_class, "Predict抵抗2", target_num)]
#     #             exe_orders = [order_make_dir1_l(peaks_class, comment, 1, 0, 1,
#     #                                             peaks_class.cal_move_size_lc(0.8),
#     #                                             peaks_class.cal_move_size_lc(0.8))]
#     #     else:
#     #         # 抵抗線として、ある程度強そうな場合(Breakまではいたらない） ⇒昔は強レジスタンスだった
#     #         print("RESI オーダー発行（弱抵抗）⇒現在ノーオーダー", total_strength_of_1)
#     #         return default_return_item
#
#     if total_strength_of_1 < 10:
#         # 抵抗が少ない場合
#         if total_strength_of_1 <= 8:  # ８は最小最大の既定の数字なので、７くらいがよい・・？
#             if (peaks[0]['direction'] == 1 and peaks[0]['latest_body_peak_price'] <= peaks[2]['latest_body_peak_price'])\
#                     or (peaks[0]['direction'] == -1 and peaks[0]['latest_body_peak_price'] >= peaks[2]['latest_body_peak_price']):
#             # if peaks[0]['direction'] == 1 and peaks[0]['latest_body_peak_price'] <= peaks[2]['latest_body_peak_price']:
#             # if peaks[0]['latest_body_peak_price'] <= peaks[2]['latest_body_peak_price']:
#             # if peaks[0]['direction'] == -1 and peaks[0]['latest_body_peak_price'] >= peaks[2]['latest_body_peak_price']:
#             # if peaks[0]['latest_body_peak_price'] >= peaks[2]['latest_body_peak_price']:
#
#             #     return default_return_item
#             # # スキップされるレベルの抵抗線群の場合
#             # if len(peaks_class.same_price_list) == 1 and total_strength_of_1 == 5:
#                 comment = "抵抗5点の一つのみの抵抗オーダー"  # Peak[0]のほうが適切化も？？
#                 print("抵抗線は一つだが、それが5点（直近の最低値）の場合、抵抗線とみなす")
#                 # exe_orders = [resistance_order_weak(peaks, peaks_class, comment, target_num)]
#
#                 # パターン１　少し[0]が同方向に進んだ位置に、逆張りオーダーを仕掛ける
#                 i = 0
#                 if peaks[0]['direction'] == 1:
#                     # 直近の向きが登りの場合、df.iloc[1]の下側を取得する（
#                     target = peaks_class.df_r_original.iloc[i]['high']
#                     print(" ベース価格low", peaks_class.df_r_original.iloc[i])
#                 else:
#                     # 直近の向きが下理の場合、df.iloc[1]の上側を取得する
#                     target = peaks_class.df_r_original.iloc[i]['low']
#                     print(" ベース価格high", peaks_class.df_r_original.iloc[i])
#                 exe_orders = [order_make_dir1_l(peaks_class, comment, target,
#                                                 peaks_class.cal_move_ave(0.2), 1,
#                                                 peaks_class.cal_move_ave(1.5),
#                                                 peaks_class.cal_move_ave(1))]
#             else:
#                 return default_return_item
#                 print("RESI オーダー発行（弱抵抗）", total_strength_of_1)
#                 comment = "弱抵抗の抵抗オーダー"
#                 # exe_orders = [resistance_order_weak(peaks, peaks_class, "Predict抵抗2", target_num)]
#                 # exe_orders = [break_order_week(peaks, peaks_class, "Predict抵抗2", target_num)]
#                 exe_orders = [order_make_dir1_l(peaks_class, comment, 1, 0, 1,
#                                                 peaks_class.cal_move_ave(0.8),
#                                                 peaks_class.cal_move_ave(0.8))]
#         else:
#             # 抵抗線として、ある程度強そうな場合(Breakまではいたらない） ⇒昔は強レジスタンスだった
#             print("RESI オーダー発行（弱抵抗）⇒現在ノーオーダー", total_strength_of_1)
#             return default_return_item
#     else:
#         return default_return_item
#
#     print("オーダーします")
#     print(exe_orders)
#
#     return {
#         "take_position_flag": True,
#         "exe_orders": exe_orders,
#         "for_inspection_dic": {}
#     }
