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

gl_units = 20000


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
    fixed_information = cf.information_fix(dic_args)  # DFとPeaksが必ず返却される
    df_r = fixed_information['df_r']
    peaks = fixed_information['peaks']

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

        main_order_base = cf.order_base(target_price, df_r.iloc[0]['time_jp'])
        main_order_base['target'] = 0.015  # ビッグムーブの後で、スプレッドが大きい可能性もあり
        main_order_base['lc'] = peaks[1]['peak'] #
        main_order_base['order_timeout_min'] = 15  # lc_price
        main_order_base['type'] = "STOP"  # "STOP"  # "MARKET"
        main_order_base['expected_direction'] = peaks[0]['direction']
        main_order_base['priority'] = 4  # flag_info['strength_info']['priority']
        main_order_base['units'] = gl_units
        main_order_base['name'] = "ビッグムーブ直後(HighPriority)"
        exe_orders.append(cf.order_finalize(main_order_base))
    else:
        print("Big_Moveの後ではない")

    if move_size_ans['is_latest_peak_resistance_line'] != 0:
        if move_size_ans['is_latest_peak_resistance_line'] == 2:
            print("★直前ピークが抵抗線(考え方はダブルピークと近い) N3以上で数回当たられている抵抗線")
            orders_and_evidence["take_position_flag"] = True  # ここまで来ている＝注文あり
            main_order_base = cf.order_base(target_price, df_r.iloc[0]['time_jp'])
            # main_order_base['target'] = target_price + (0.035 * flag_info['line_base_info']['line_base_direction'])  # 0.05
            main_order_base['target'] = peaks[1]['peak'] + (0.02 * peaks[0]['direction'] * -1)
            main_order_base['lc'] = 0.06  # lc_price
            main_order_base['order_timeout_min'] = 20  # lc_price
            main_order_base['type'] = "STOP"  # "STOP"  # "MARKET"
            main_order_base['expected_direction'] = peaks[0]['direction'] * -1
            main_order_base['priority'] = 3  # flag_info['strength_info']['priority']
            main_order_base['units'] = gl_units
            main_order_base['name'] = "直前ピークが抵抗線（突破方向）"
            # カウンター用のオーダー
            counter_order_base = cf.order_base(target_price, df_r.iloc[0]['time_jp'])
            counter_order_base['target'] = peaks[1]['peak'] + (0.02 * peaks[0]['direction'] * -1)
            counter_order_base['lc'] = 0.04  # lc_price
            counter_order_base['order_timeout_min'] = 20  # lc_price
            counter_order_base['type'] = "STOP"  # "STOP"  # "MARKET"
            counter_order_base['expected_direction'] = main_order_base['expected_direction'] * -1  # peaks[0]['direction'] * -1
            counter_order_base['priority'] = 3  # flag_info['strength_info']['priority']
            counter_order_base['units'] = gl_units / 2
            counter_order_base['name'] = "カウンタオーオーダー　直前ピークが抵抗線（突破方向）"
            main_order_base['counter_order'] = cf.order_finalize(counter_order_base)

            exe_orders.append(cf.order_finalize(main_order_base))
        else:  # move_size_ans['is_latest_peak_resistance_line'] == 1（抵抗線N＝２で、よくあるやつで大体戻る）
            print("★直前ピークが弱い抵抗線 N2以上でよくある、戻る抵抗線")
            latest_candle_size = df_r.iloc[1]['highlow']
            orders_and_evidence["take_position_flag"] = True  # ここまで来ている＝注文あり
            main_order_base = cf.order_base(target_price, df_r.iloc[0]['time_jp'])
            # main_order_base['target'] = target_price + (0.035 * flag_info['line_base_info']['line_base_direction'])  # 0.05
            # main_order_base['target'] = peaks[0]['peak'] + (0.02 * peaks[0]['direction'] * 1)
            main_order_base['target'] = latest_candle_size  # 直近動いた分はマージンとして取る（戻る方だけ。感覚的に、、、）
            main_order_base['lc'] = 0.06  # lc_price
            main_order_base['order_timeout_min'] = 20  # lc_price
            main_order_base['type'] = "STOP"  # "STOP"  # "MARKET"
            main_order_base['expected_direction'] = peaks[0]['direction'] * 1
            main_order_base['priority'] = 3  # flag_info['strength_info']['priority']
            main_order_base['units'] = gl_units
            main_order_base['name'] = "直前ピークが抵抗線（戻し方向）"
            # exe_orders.append(cf.order_finalize(main_order_base))
            # カウンター用のオーダー
            counter_order_base = cf.order_base(target_price, df_r.iloc[0]['time_jp'])
            counter_order_base['target'] = peaks[1]['peak'] + (0.02 * peaks[0]['direction'] * -1)
            counter_order_base['lc'] = 0.04  # lc_price
            counter_order_base['order_timeout_min'] = 20  # lc_price
            counter_order_base['type'] = "STOP"  # "STOP"  # "MARKET"
            counter_order_base['expected_direction'] = main_order_base['expected_direction'] * -1  # peaks[0]['direction'] * -1
            counter_order_base['priority'] = 3  # flag_info['strength_info']['priority']
            counter_order_base['units'] = gl_units / 2
            counter_order_base['name'] = "カウンタオーオーダー　直前ピークが抵抗線（戻し方向）"
            main_order_base['counter_order'] = cf.order_finalize(counter_order_base)

            exe_orders.append(cf.order_finalize(main_order_base))
    else:
        print(" 直近抵抗線ではない")

    if move_size_ans['peak_is_peak']:
        if peaks[1]['gap'] >= 0.09:
            print("★直近での最ピーク値")
            orders_and_evidence["take_position_flag"] = True  # ここまで来ている＝注文あり
            # 突破方向
            main_order_base = cf.order_base(target_price, df_r.iloc[0]['time_jp'])
            main_order_base['target'] = peaks[1]['peak'] + (0.02 * peaks[0]['direction'] * -1)
            main_order_base['lc'] = 0.06  # lc_price
            main_order_base['order_timeout_min'] = 15  # lc_price
            main_order_base['type'] = "STOP"  # "STOP"  # "MARKET"
            main_order_base['expected_direction'] = peaks[0]['direction'] * -1
            main_order_base['priority'] = 2  # flag_info['strength_info']['priority']
            main_order_base['units'] = gl_units
            main_order_base['name'] = "直前ピークがピーク値（突破方向）"
            exe_orders.append(cf.order_finalize(main_order_base))
            # カウンター方向
            main_order_base = cf.order_base(target_price, df_r.iloc[0]['time_jp'])
            main_order_base['target'] = round((peaks[1]['peak'] + peaks[1]['peak_old']) / 2, 3)
            main_order_base['lc'] = peaks[1]['peak']  # lc_price
            main_order_base['order_timeout_min'] = 15  # lc_price
            main_order_base['type'] = "STOP"  # "STOP"  # "MARKET"
            main_order_base['expected_direction'] = peaks[0]['direction']
            main_order_base['priority'] = 2  # flag_info['strength_info']['priority']
            main_order_base['units'] = gl_units
            main_order_base['name'] = "直前ピークがピーク値（もどり方向）"
            exe_orders.append(cf.order_finalize(main_order_base))
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

def main_counter_after_gig_move(dic_args):
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
    fixed_information = cf.information_fix(dic_args)  # DFとPeaksが必ず返却される
    df_r = fixed_information['df_r']
    peaks = fixed_information['peaks']