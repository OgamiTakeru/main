import copy

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
import classOrderCreate as OCreate


def cal_big_mountain(peaks_class):
    """
    直近のピーク（latest_peakはこれから伸びるPeakなので、直前のpeakは[1]の物を示す
    """
    # ■基本情報の取得
    take_position = False
    s = "    "

    # ■実行除外
    if peaks_class.peaks_original[0]['count'] != 2:
        return {
            "take_position_flag": take_position,
            "for_inspection_dic": {}
        }

    # ■■■実行
    target_peak = peaks_class.peaks_original[1]

    # ■同一価格の調査を行う（BodyPeakと髭ピークの組み合わせ。ただしどちらかはBodyPeakとする）
    target_num = 1  # 以下のループで「自分以外」を定義するため、変数に入れておく(同一方向の配列に対して）
    t = peaks_class.peaks_original[target_num]
    print(t)
    arrowed_range = peaks_class.recent_fluctuation_range * 0.04  # 最大変動幅の4パーセント程度
    result_same_price_list = []
    result_same_price_num_list = []
    result_not_same_price_num_list = []
    opposite_peaks = []
    opposite_peaks_num = []
    print("  ArrowedGap", arrowed_range)
    for i, item in enumerate(peaks_class.peaks_original):
        # Continue
        # if i == target_num:
        #     print("飛ばす", PeaksClass.peaks_original[target_num])
        #     continue  # 自分自身は比較しない

        # 反対方向のピークの場合
        if item['direction'] != target_peak['direction']:
            # ターゲットのピークと逆方向のピークの場合
            opposite_peaks.append(item)
            opposite_peaks_num.append(i)

        # ■判定１　全ての近い価格を取得
        body_gap_abs = abs(t['peak'] - item['peak'])
        body_wick_gap_abs = abs(t['peak'] - item['latest_wick_peak_price'])
        wick_body_gap_abs = abs(t['latest_wick_peak_price'] - item['peak'])
        if body_gap_abs <= arrowed_range or body_wick_gap_abs <= arrowed_range or wick_body_gap_abs <= arrowed_range:
            # 同一価格とみなせる場合
            result_same_price_list.append(item)
            result_same_price_num_list.append(i)
        else:
            print("         違う価格", item['time'], body_gap_abs)
            result_not_same_price_num_list.append(i)

    print("同一価格Ansew")
    gene.print_arr(result_same_price_list)
    gene.print_arr(result_same_price_num_list)

    if len(result_same_price_list) == 2:
        # ターゲットのピークに対して、同一とみなせる価格のピークが１つの場合(自身含め２個）、直近が何時間前だったかを確認する(最初と最後？）
        sec_gap_latest_same_price = gene.cal_str_time_gap(t['time'], result_same_price_list[0]['time'])
        sec_gap_oldest_same_price = gene.cal_str_time_gap(t['time'], result_same_price_list[-1]['time'])
        print("最古の同一の時間", sec_gap_oldest_same_price['gap_abs'] / 60)
        if sec_gap_oldest_same_price['gap_abs'] / 60 >= 70:
            # 90分以上の場合は、山検証の対象
            fr = result_same_price_num_list[0]  # f はfromを示す（短く書く変数化）
            t = result_same_price_num_list[-1]  # t はtoを示す（短く書く変数化）
            filtered_peaks = peaks_class.peaks_original[fr: t + 1]  # 間のピークス（両方の方向）
            filtered_peaks_oppo_peak = [d for d in filtered_peaks if
                                        d["direction"] == target_peak['direction'] * -1]
            gene.print_arr(filtered_peaks)
            print("逆サイドのみ")
            gene.print_arr(filtered_peaks_oppo_peak)

            # 最大値（逆サイドの方向が1の場合。-1の場合は最小値）は？
            if target_peak['direction'] * -1 == 1:
                far_item = max(filtered_peaks_oppo_peak, key=lambda x: x["peak"])
            else:
                far_item = min(filtered_peaks_oppo_peak, key=lambda x: x["peak"])
            t_gap = abs(far_item['peak'] - target_peak['peak'])
            print("対象は", far_item)
            print(t_gap, far_item['time'], target_peak['time'])
            print(peaks_class.recent_fluctuation_range, peaks_class.recent_fluctuation_range * 0.38)
            if t_gap >= peaks_class.recent_fluctuation_range * 0.38:  # 最大の7割以上ある山が形成されている場合
                print("☆☆戻ると判定 2個", t_gap / peaks_class.recent_fluctuation_range)
                take_position = True
            # self.recent_fluctuation_range * 0.7
    elif len(result_same_price_list) == 3:
        # 二つの場合、近いほうと遠いほうの比率を検討する
        sec_gap_latest_same_price = gene.cal_str_time_gap(t['time'], result_same_price_list[0]['time'])
        sec_gap_oldest_same_price = gene.cal_str_time_gap(t['time'], result_same_price_list[-1]['time'])
        print("最古の同一の時間", sec_gap_oldest_same_price['gap_abs'] / 60)
        if sec_gap_oldest_same_price['gap_abs'] / 60 >= 90:
            # 90分以上の場合は、山検証の対象
            fr = result_same_price_num_list[0]  # f はfromを示す（短く書く変数化）
            t = result_same_price_num_list[-1]  # t はtoを示す（短く書く変数化）
            filtered_peaks = peaks_class.peaks_original[fr: t + 1]  # 間のピークス（両方の方向）
            filtered_peaks_oppo_peak = [d for d in filtered_peaks if
                                        d["direction"] == target_peak['direction'] * -1]
            gene.print_arr(filtered_peaks)
            print("逆サイドのみ")
            gene.print_arr(filtered_peaks_oppo_peak)

            # 最大値（逆サイドの方向が1の場合。-1の場合は最小値）は？
            if target_peak['direction'] * -1 == 1:
                far_item = max(filtered_peaks_oppo_peak, key=lambda x: x["peak"])
            else:
                far_item = min(filtered_peaks_oppo_peak, key=lambda x: x["peak"])
            t_gap = abs(far_item['peak'] - target_peak['peak'])
            print("対象は", far_item)
            print(t_gap)
            print(peaks_class.recent_fluctuation_range, peaks_class.recent_fluctuation_range * 0.7)
            if t_gap >= peaks_class.recent_fluctuation_range * 0.7:  # 最大の7割以上ある山が形成されている場合
                print("☆☆戻ると判定 3個", t_gap / peaks_class.recent_fluctuation_range)
                take_position = True
    else:
        # 3個以上の場合は結構突破している・・・？
        pass

    # 返却用
    exe_orders = []
    if take_position:
        # オーダーありの場合
        peaks = peaks_class.peaks_original
        base_order_dic = {
            "target": 0.04,
            "type": "STOP",
            "expected_direction": peaks[0]['direction'],
            "tp": 0.09,
            "lc": OCreate.cal_lc_price_from_line_and_margin(peaks[1]['latest_wick_peak_price'], 0.03, peaks[0]['direction']),  # 0.06,
            # "lc": 0.05,
            'priority': 3,
            "decision_time": peaks_class.df_r_original.iloc[0]['time_jp'],
            "decision_price": peaks_class.df_r_original.iloc[1]['close'],
            "order_timeout_min": 20,
            "name": "山"
        }
        base_order_class = OCreate.OrderCreateClass(base_order_dic)
        exe_orders.append(base_order_class.finalized_order)

    return {
        "take_position_flag": take_position,
        "exe_orders": exe_orders,
        "for_inspection_dic": {}
    }

# def main_simple_turn(dic_args):
#     """
#     引数はDFやピークスなど
#     オーダーを生成する
#     """
#
#     # 表示時のインデント
#     s4 = "    "
#     s6 = "      "
#
#     print(" シンプルターン調査")
#     # ■関数事前準備■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■
#     # ■■返却値 とその周辺の値
#     exe_orders = []
#     orders_and_evidence = {
#         "take_position_flag": False,
#         "exe_orders": exe_orders,
#         "information": []
#     }
#     # ■■情報の整理と取得（関数の頭には必須）
#     peaksclass = cpk.PeaksClass(dic_args['df_r'])
#     df_r = dic_args['df_r']
#     peaks = peaksclass.skipped_peaks
#
#     # ■調査を実施する■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■
#     # ■■実行しない条件の場合、実行を終了する
#     if peaks[0]['count'] != 2:
#         print(s6, "count2以外の実行無し", peaks[0]['count'])  # フラッグは基本的に、Latestの数がいつでも実行する
#         return orders_and_evidence
#
#     if peaks[1]['gap'] <= 0.03:
#         print(s4, "前が少なすぎるのでキャンセル", peaks[1]["time"], peaks[1]['gap'])
#         # tk.line_send("前が少なすぎるので今回はオーダーなし", peaks[1]["time"], peaks[1]['gap'])
#         return orders_and_evidence
#
#     # ■■解析の実行
#     # ■注文情報の整理
#     if peaks[0]['direction'] == 1:
#         # 直近が上向きの場合
#         target_price = df_r.iloc[1]['inner_high']  # 直近を除いたピークにほぼ等しい。マージンは０といえる
#         lc_price_temp = df_r.iloc[1]['low']
#     else:
#         # 直近が下向きの場合
#         target_price = df_r.iloc[1]['inner_low']
#         lc_price_temp = df_r.iloc[1]['high']
#     # 共通項目
#     lc_range = abs(target_price - lc_price_temp)
#     direction = peaks[0]['direction']
#     # LCは小さめにしたい
#     if lc_range >= 0.035:
#         print(s6, "LCRangeが大きいため、LCを縮小")
#         lc_range = 0.035
#     if lc_range <= 0.01:
#         print(s6, "LCRangeが小さいため、LCを縮小")
#         lc_range = 0.02
#
#     # ■サイズを検証し、オーダーを入れる(ここで検証を実施）
#     move_size_ans = ms.cal_move_size({"df_r": df_r})
#     # 大きな変動がある直後のオーダー（ビッグムーブとは逆の動き）
#     if move_size_ans['big_move']:
#         print("★Big_move_直後のカウンターオーダー(少し折り返した時点でオーダーが入る）")
#         orders_and_evidence["take_position_flag"] = True  # ここまで来ている＝注文あり
#         base_order_dic = {
#             "target": 0.015,
#             "type": "STOP",
#             "expected_direction": peaks[0]['direction'],
#             "tp": 0.9,
#             "lc": peaks[1]['peak'],
#             'priority': 4,
#             "decision_time": df_r.iloc[0]['time_jp'],
#             "order_timeout_min": 15,
#             "name": "ビッグムーブ直後(HighPriority)",
#         }
#         base_order_class = OCreate.OrderCreateClass(base_order_dic)
#         exe_orders.append(base_order_class.finalized_order)
#     else:
#         print("Big_Moveの後ではない")
#
#     # ■抵抗線の調査を実施する
#     # registance_line_ans = registance_analysis({"df_r": df_r})
#     if move_size_ans['is_latest_peak_resistance_line'] != 0:
#         print("  直前ピークが抵抗線（突破と戻りを同時に出す")
#         print(peaks[1]['peak_old'])
#
#         # ■突破方向
#         orders_and_evidence["take_position_flag"] = True  # ここまで来ている＝注文あり
#         base_order_dic = {
#             "target": peaks[1]['peak'] + (0.02 * peaks[0]['direction'] * -1),
#             "type": "STOP",
#             "expected_direction": peaks[0]['direction'] * -1,
#             "tp": 0.9,
#             "lc": 0.06,
#             'priority': 3,
#             "decision_time": df_r.iloc[0]['time_jp'],
#             "order_timeout_min": 20,
#             "name": "直前ピークが抵抗線（突破方向）"
#         }
#         base_order_class = OCreate.OrderCreateClass(base_order_dic)
#         counter_order_base = {
#             "units": 10000,
#             "target": peaks[1]['peak'] + (0.02 * peaks[0]['direction'] * -1),
#             "type": "STOP",
#             "expected_direction": peaks[0]['direction'] * -1,
#             "tp": 0.9,
#             "lc": 0.025,
#             'priority': 3,
#             "decision_time": df_r.iloc[0]['time_jp'],
#             "order_timeout_min": 20,
#             "name": "カウンタオーオーダー　直前ピークが抵抗線（突破方向）"
#         }
#         counter_order = OCreate.OrderCreateClass(counter_order_base)
#         base_order_class.add_counter_order(counter_order.finalized_order)
#         exe_orders.append(base_order_class.finalized_order)
#
#         # ■戻り方向
#         latest_candle_size = df_r.iloc[1]['highlow']
#         orders_and_evidence["take_position_flag"] = True  # ここまで来ている＝注文あり
#         base_order_dic = {
#             "target": latest_candle_size,
#             "type": "STOP",
#             "expected_direction": peaks[0]['direction'] * -1,
#             "tp": 0.9,
#             "lc": 0.06,
#             'priority': 3,
#             "decision_time": df_r.iloc[0]['time_jp'],
#             "order_timeout_min": 20,
#             "name": "直前ピークが抵抗線（戻し方向）"
#         }
#         base_order_class = OCreate.OrderCreateClass(base_order_dic)
#         counter_order_base = {
#             "units": 10000,
#             "target": peaks[1]['peak'] + (0.02 * peaks[0]['direction'] * -1),
#             "type": "STOP",
#             "expected_direction": peaks[0]['direction'] * -1,
#             "tp": 0.9,
#             "lc": 0.025,
#             'priority': 3,
#             "decision_time": df_r.iloc[0]['time_jp'],
#             "order_timeout_min": 20,
#             "name": "カウンタオーオーダー　直前ピークが抵抗線（戻し方向）"
#         }
#         counter_order = OCreate.OrderCreateClass(counter_order_base)
#         base_order_class.add_counter_order(counter_order.finalized_order)
#         exe_orders.append(base_order_class.finalized_order)
#     else:
#         print(" 直近抵抗線ではない")
#
#     if move_size_ans['peak_is_peak']:
#         if peaks[1]['gap'] >= 0.09:
#             print("★直近での最ピーク値")
#             orders_and_evidence["take_position_flag"] = True  # ここまで来ている＝注文あり
#             # 突破方向
#             base_order_dic = {
#                 "target": peaks[1]['peak'] + (0.02 * peaks[0]['direction'] * -1),
#                 "type": "STOP",
#                 "expected_direction": peaks[0]['direction'] * -1,
#                 "tp": 0.9,
#                 "lc": 0.06,
#                 'priority': 2,
#                 "decision_time": df_r.iloc[0]['time_jp'],
#                 "decision_price": target_price,
#                 "order_timeout_min": 20,
#                 "name": "直前ピークがピーク値（突破方向）"
#             }
#             base_order_class = OCreate.OrderCreateClass(base_order_dic)
#             exe_orders.append(base_order_class.finalized_order)
#             # カウンター方向
#             range_order_dic = {
#                 "target": round((peaks[1]['peak'] + peaks[1]['peak_old']) / 2, 3),
#                 "type": "STOP",
#                 "expected_direction": peaks[0]['direction'],
#                 "tp": 0.9,
#                 "lc": peaks[1]['peak'],
#                 'priority': 2,
#                 "decision_time": df_r.iloc[0]['time_jp'],
#                 "decision_price": target_price,
#                 "order_timeout_min": 20,
#                 "name": "直前ピークがピーク値（もどり方向）"
#             }
#             range_order_class = OCreate.OrderCreateClass(range_order_dic)
#             exe_orders.append(range_order_class.finalized_order)
#         else:
#             print(s4, " 最ピーク値だが、riverのギャップが小さいのでやらない。")
#     else:
#         print(" 直近は最ピークではない")
#
#
#     # 返却する
#     print(s4, "オーダー対象のため、オーダーリストを登録する(フラグは各場所で上げる)")
#     orders_and_evidence["exe_orders"] = exe_orders
#
#     if orders_and_evidence["take_position_flag"]:
#         print("シンプルターンのオーダー表示")
#         gene.print_arr(orders_and_evidence["exe_orders"])
#         return orders_and_evidence
#     else:
#         print("  シンプルターンオーダーなし")
#         print(orders_and_evidence)
#         return orders_and_evidence
#
#
# def main_simple_turn2(dic_args):
#     """
#     引数はDFやピークスなど
#     オーダーを生成する
#     """
#
#     # 表示時のインデント
#     s4 = "    "
#     s6 = "      "
#
#     print(" シンプルターン調査")
#     # ■関数事前準備■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■
#     # ■■返却値 とその周辺の値
#     orders_and_evidence = {
#         "take_position_flag": False,
#         "exe_orders": [],
#         "information": []
#     }
#     # ■■情報の整理と取得（関数の頭には必須）
#     peaksclass = cpk.PeaksClass(dic_args['df_r'])
#     df_r = dic_args['df_r']
#     peaks = peaksclass.skipped_peaks
#
#
#
#     # 返
#     if orders_and_evidence["take_position_flag"]:
#         print("シンプルターンのオーダー表示")
#         gene.print_arr(orders_and_evidence["exe_orders"])
#         return orders_and_evidence
#     else:
#         print("  シンプルターンオーダーなし")
#         print(orders_and_evidence)
#         return orders_and_evidence
