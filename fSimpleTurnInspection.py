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


def main_simple_turn(dic_args):
    """
    引数はDFやピークスなど
    オーダーを生成する
    """

    # 表示時のインデント
    s4 = "    "
    s6 = "      "

    print(" シンプルターン調査")
    # ■関数事前準備■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■
    # ■■返却値 とその周辺の値
    exe_orders = []
    orders_and_evidence = {
        "take_position_flag": False,
        "exe_orders": exe_orders,
        "information": []
    }
    # ■■情報の整理と取得（関数の頭には必須）
    peaksclass = cpk.PeaksClass(dic_args['df_r'])
    df_r = dic_args['df_r']
    peaks = peaksclass.skipped_peaks

    # ■調査を実施する■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■
    # ■■実行しない条件の場合、実行を終了する
    if peaks[0]['count'] != 2:
        print(s6, "count2以外の実行無し", peaks[0]['count'])  # フラッグは基本的に、Latestの数がいつでも実行する
        return orders_and_evidence

    if peaks[1]['gap'] <= 0.03:
        print(s4, "前が少なすぎるのでキャンセル", peaks[1]["time"], peaks[1]['gap'])
        # tk.line_send("前が少なすぎるので今回はオーダーなし", peaks[1]["time"], peaks[1]['gap'])
        return orders_and_evidence

    # ■■解析の実行
    # ■注文情報の整理
    if peaks[0]['direction'] == 1:
        # 直近が上向きの場合
        target_price = df_r.iloc[1]['inner_high']  # 直近を除いたピークにほぼ等しい。マージンは０といえる
        lc_price_temp = df_r.iloc[1]['low']
    else:
        # 直近が下向きの場合
        target_price = df_r.iloc[1]['inner_low']
        lc_price_temp = df_r.iloc[1]['high']
    # 共通項目
    lc_range = abs(target_price - lc_price_temp)
    direction = peaks[0]['direction']
    # LCは小さめにしたい
    if lc_range >= 0.035:
        print(s6, "LCRangeが大きいため、LCを縮小")
        lc_range = 0.035
    if lc_range <= 0.01:
        print(s6, "LCRangeが小さいため、LCを縮小")
        lc_range = 0.02

    # ■サイズを検証し、オーダーを入れる(ここで検証を実施）
    move_size_ans = ms.cal_move_size({"df_r": df_r})
    # 大きな変動がある直後のオーダー（ビッグムーブとは逆の動き）
    if move_size_ans['big_move']:
        print("★Big_move_直後のカウンターオーダー(少し折り返した時点でオーダーが入る）")
        orders_and_evidence["take_position_flag"] = True  # ここまで来ている＝注文あり
        base_order_dic = {
            "target": 0.015,
            "type": "STOP",
            "expected_direction": peaks[0]['direction'],
            "tp": 0.9,
            "lc": peaks[1]['peak'],
            'priority': 4,
            "decision_time": df_r.iloc[0]['time_jp'],
            "order_timeout_min": 15,
            "name": "ビッグムーブ直後(HighPriority)",
        }
        base_order_class = OCreate.OrderCreateClass(base_order_dic)
        exe_orders.append(base_order_class.finalized_order)
    else:
        print("Big_Moveの後ではない")

    # ■抵抗線の調査を実施する
    # registance_line_ans = registance_analysis({"df_r": df_r})
    if move_size_ans['is_latest_peak_resistance_line'] != 0:
        print("  直前ピークが抵抗線（突破と戻りを同時に出す")
        print(peaks[1]['peak_old'])

        # ■突破方向
        orders_and_evidence["take_position_flag"] = True  # ここまで来ている＝注文あり
        base_order_dic = {
            "target": peaks[1]['peak'] + (0.02 * peaks[0]['direction'] * -1),
            "type": "STOP",
            "expected_direction": peaks[0]['direction'] * -1,
            "tp": 0.9,
            "lc": 0.06,
            'priority': 3,
            "decision_time": df_r.iloc[0]['time_jp'],
            "order_timeout_min": 20,
            "name": "直前ピークが抵抗線（突破方向）"
        }
        base_order_class = OCreate.OrderCreateClass(base_order_dic)
        counter_order_base = {
            "units": 10000,
            "target": peaks[1]['peak'] + (0.02 * peaks[0]['direction'] * -1),
            "type": "STOP",
            "expected_direction": peaks[0]['direction'] * -1,
            "tp": 0.9,
            "lc": 0.025,
            'priority': 3,
            "decision_time": df_r.iloc[0]['time_jp'],
            "order_timeout_min": 20,
            "name": "カウンタオーオーダー　直前ピークが抵抗線（突破方向）"
        }
        counter_order = OCreate.OrderCreateClass(counter_order_base)
        base_order_class.add_counter_order(counter_order.finalized_order)
        exe_orders.append(base_order_class.finalized_order)

        # ■戻り方向
        latest_candle_size = df_r.iloc[1]['highlow']
        orders_and_evidence["take_position_flag"] = True  # ここまで来ている＝注文あり
        base_order_dic = {
            "target": latest_candle_size,
            "type": "STOP",
            "expected_direction": peaks[0]['direction'] * -1,
            "tp": 0.9,
            "lc": 0.06,
            'priority': 3,
            "decision_time": df_r.iloc[0]['time_jp'],
            "order_timeout_min": 20,
            "name": "直前ピークが抵抗線（戻し方向）"
        }
        base_order_class = OCreate.OrderCreateClass(base_order_dic)
        counter_order_base = {
            "units": 10000,
            "target": peaks[1]['peak'] + (0.02 * peaks[0]['direction'] * -1),
            "type": "STOP",
            "expected_direction": peaks[0]['direction'] * -1,
            "tp": 0.9,
            "lc": 0.025,
            'priority': 3,
            "decision_time": df_r.iloc[0]['time_jp'],
            "order_timeout_min": 20,
            "name": "カウンタオーオーダー　直前ピークが抵抗線（戻し方向）"
        }
        counter_order = OCreate.OrderCreateClass(counter_order_base)
        base_order_class.add_counter_order(counter_order.finalized_order)
        exe_orders.append(base_order_class.finalized_order)
    else:
        print(" 直近抵抗線ではない")

    if move_size_ans['peak_is_peak']:
        if peaks[1]['gap'] >= 0.09:
            print("★直近での最ピーク値")
            orders_and_evidence["take_position_flag"] = True  # ここまで来ている＝注文あり
            # 突破方向
            base_order_dic = {
                "target": peaks[1]['peak'] + (0.02 * peaks[0]['direction'] * -1),
                "type": "STOP",
                "expected_direction": peaks[0]['direction'] * -1,
                "tp": 0.9,
                "lc": 0.06,
                'priority': 2,
                "decision_time": df_r.iloc[0]['time_jp'],
                "decision_price": target_price,
                "order_timeout_min": 20,
                "name": "直前ピークがピーク値（突破方向）"
            }
            base_order_class = OCreate.OrderCreateClass(base_order_dic)
            exe_orders.append(base_order_class.finalized_order)
            # カウンター方向
            range_order_dic = {
                "target": round((peaks[1]['peak'] + peaks[1]['peak_old']) / 2, 3),
                "type": "STOP",
                "expected_direction": peaks[0]['direction'],
                "tp": 0.9,
                "lc": peaks[1]['peak'],
                'priority': 2,
                "decision_time": df_r.iloc[0]['time_jp'],
                "decision_price": target_price,
                "order_timeout_min": 20,
                "name": "直前ピークがピーク値（もどり方向）"
            }
            range_order_class = OCreate.OrderCreateClass(range_order_dic)
            exe_orders.append(range_order_class.finalized_order)
        else:
            print(s4, " 最ピーク値だが、riverのギャップが小さいのでやらない。")
    else:
        print(" 直近は最ピークではない")


    # 返却する
    print(s4, "オーダー対象のため、オーダーリストを登録する(フラグは各場所で上げる)")
    orders_and_evidence["exe_orders"] = exe_orders

    if orders_and_evidence["take_position_flag"]:
        print("シンプルターンのオーダー表示")
        gene.print_arr(orders_and_evidence["exe_orders"])
        return orders_and_evidence
    else:
        print("  シンプルターンオーダーなし")
        print(orders_and_evidence)
        return orders_and_evidence


def main_simple_turn2(dic_args):
    """
    引数はDFやピークスなど
    オーダーを生成する
    """

    # 表示時のインデント
    s4 = "    "
    s6 = "      "

    print(" シンプルターン調査")
    # ■関数事前準備■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■
    # ■■返却値 とその周辺の値
    orders_and_evidence = {
        "take_position_flag": False,
        "exe_orders": [],
        "information": []
    }
    # ■■情報の整理と取得（関数の頭には必須）
    peaksclass = cpk.PeaksClass(dic_args['df_r'])
    df_r = dic_args['df_r']
    peaks = peaksclass.skipped_peaks



    # 返
    if orders_and_evidence["take_position_flag"]:
        print("シンプルターンのオーダー表示")
        gene.print_arr(orders_and_evidence["exe_orders"])
        return orders_and_evidence
    else:
        print("  シンプルターンオーダーなし")
        print(orders_and_evidence)
        return orders_and_evidence
