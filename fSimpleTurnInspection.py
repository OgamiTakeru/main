import copy

import fPeakInspection as p  # とりあえずの関数集
import fGeneric as gene
import fDoublePeaks as dp
import tokens as tk

import fPeakInspection as peak_inspection
import fDoublePeaks as dp
import pandas as pd
import fMoveSizeInspection as ms
import fCommonFunction as cf
import fMoveSizeInspection as ms


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
        print("前が少なすぎるのでキャンセル", peaks[1]["time"], peaks[1]['gap'])
        tk.line_send("前が少なすぎるので今回はオーダーなし", peaks[1]["time"], peaks[1]['gap'])
        return orders_and_evidence

    # ■■解析の実行
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
        print("LCRangeが大きいため、LCを縮小")
        lc_range = 0.035
    if lc_range <= 0.01:
        print("LCRangeが小さいため、LCを縮小")
        lc_range = 0.02

    # targetPriceの調整（折り返したら、折り返した方面に行く前提）
    margin = 0.00
    type = "STOP"
    if peaks[0]['direction'] == 1:
        # 直近が上向きの場合、ターゲット価格より低い値は逆張り的、それより上は順張り的
        if type == "STOP":
            target_price = target_price + margin
        elif type == "LIMIT":
            target_price = target_price - margin
        else:
            # MARKETの場合
            pass
    else:
        # 直近が下向きの場合、ターゲット価格より高い値は逆張り的、低い値は順張り的
        if type == "STOP":
            target_price = target_price - margin
        elif type == "LIMIT":
            target_price = target_price + margin
        else:
            # MARKETの場合
            pass

    # 大きな変動を含む場合は、ポジションの向きを逆にする（ポジションしないかも・・？）
    # 条件で実行しない場合
    if float(df_r.iloc[1]['body_abs']) >= 0.8 or float(df_r.iloc[2]['body_abs']) >= 0.8:
        print(" 大きな変動を直前に確認")
        tk.line_send("シンプル　大きな変動確認後", df_r.iloc[1]['time_jp'], df_r.iloc[1]['body_abs'],
                     df_r.iloc[2]['time_jp'], df_r.iloc[2]['body_abs'])
        orders_and_evidence["take_position_flag"] = True
        direction = direction * -1  # 方向の上書き

    print("シンプル基準")
    print("直近のもの（使わないデータ）", df_r.iloc[0]['time_jp'])
    print("対象", df_r.iloc[1]['time_jp'], target_price, lc_range)

    main_order_base = cf.order_base(target_price, df_r.iloc[0]['time_jp'])
    # main_order_base['target'] = target_price + (0.035 * flag_info['line_base_info']['line_base_direction'])  # 0.05
    main_order_base['target'] = target_price  # target_price
    main_order_base['lc'] = lc_range  # lc_price
    main_order_base['order_timeout_min'] = 5  # lc_price
    main_order_base['type'] = "LIMIT" # "STOP"  # "MARKET"
    main_order_base['expected_direction'] = direction
    main_order_base['priority'] = 3  # flag_info['strength_info']['priority']
    main_order_base['units'] = 10000
    main_order_base['name'] = "シンプルターン"
    exe_orders.append(cf.order_finalize(main_order_base))

    # 返却する
    print(s4, "オーダー対象")
    orders_and_evidence["take_position_flag"] = True  # ここまで来ている＝注文あり
    orders_and_evidence["exe_orders"] = exe_orders

    print("シンプルターンのオーダー表示")
    gene.print_arr(orders_and_evidence["exe_orders"])
    return orders_and_evidence
