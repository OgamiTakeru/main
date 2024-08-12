import pandas as pd
import threading  # 定時実行用
import time
import datetime
import fBlockInspection as t  # とりあえずの関数集
import tokens as tk  # Token等、各自環境の設定ファイル（git対象外）
import classOanda as classOanda
import making as mk
import fGeneric as f
import fDoublePeaks as dp
import classPosition as classPosition
import fResistanceLineInspection as ri
import fPeakInspection as p

oa = classOanda.Oanda(tk.accountIDl, tk.access_tokenl, "live")  # クラスの定義


# now_price_dic = oa.NowPrice_exe("USD_JPY")['data']['mid']
# now_price = now_price_dic['data']['mid']

# 調査として、DoubleやRange等の複数Inspectionを利用する場合、このファイルから呼び出す(一番下）


# 処理時間削減の為、data
def order_information_add_maji(finalized_order):
    """
    強制的に
    カスケードロスカとトレールを入れる。このレンジインスペクションがメイン
    :param finalized_order:
    :return:
    """

    # カスケードロスカ
    finalized_order['lc_change'] = [
        {"lc_change_exe": True, "lc_trigger_range": 0.013, "lc_ensure_range": -0.05},
        {"lc_change_exe": True, "lc_trigger_range": 0.04, "lc_ensure_range": 0.023}
    ]

    # トレール注文を入れる
    finalized_order['tr_range'] = 0.05

    return finalized_order


def order_information_add_small(finalized_order):
    """
    強制的に
    カスケードロスカとトレールを入れる。このレンジインスペクションがメイン
    :param finalized_order:
    :return:
    """

    # カスケードロスカ
    finalized_order['lc_change'] = [
        {"lc_change_exe": True, "lc_trigger_range": 0.016, "lc_ensure_range": 0.013},
        {"lc_change_exe": True, "lc_trigger_range": 0.04, "lc_ensure_range": 0.023}
    ]

    # トレール注文を入れる
    finalized_order['tr_range'] = 0.05

    return finalized_order


# その他オーダーに必要な処理はここで記載する
def Inspection_test(df_r):
    """
    主にExeから呼ばれ、ダブル関係の結果(このファイル内のbeforeとbreak)をまとめ、注文形式にして返却する関数
    引数
    "data": df_r ローソク情報(逆順[直近が上の方にある＝時間降順])のみ。

    :return:
    　このリターンの値は、そのまま発注に使われる。
    　本番（main_exe)から呼ばれる場合と、検証(main_analysis)から呼ばれる場合では、返すべき値が異なることに注意。
    　本番環境は複数のオーダーが可能だが、検証は一つのオーダーのみしか受け付けられないため。
    　本番環境を行いながらでもテストができるように、辞書配列と辞書を同時に返却する
    　（辞書は基本的に辞書配列の[0]となる見込み）
    　返却値は以下の通り
      return{
            "take_position_flag": True or False　Trueの場合、オーダーが入る
            "exe_orders": オーダーの【配列】。複数オーダーが可能な本番環境用
            "exe_order": オーダーの辞書単品。単品オーダーのみ受付可能な検証環境用（基本、exe_orders[0]でOK？）
      }
    """
    # 現在価格を取得する
    # now_price = oa.NowPrice_exe("USD_JPY")['data']['mid']
    now_price = df_r.iloc[0]['open']  # LatestがのOpen価格が現実的には一番直近の額となる
    take_position_flag = False  # 初期値を設定する

    # 返却値を設定しておく
    # テストでは、Orderは配列で渡し、中身はBasicの中身をfinalizeしたものを利用する）
    exe_orders_arr = []  # 配列
    basic = {
            "target": 0.00,
            "type": "STOP",
            "units": 100,
            "expected_direction": 1,
            "tp": 0.10,
            "lc": 0.10,
            'priority': 0,
            "decision_price": now_price,
            "name": "",
            "lc_change": {"lc_change_exe": True, "lc_trigger_range": 0.04, "lc_ensure_range": 0.01}
    }
    flag_and_orders = {"take_position_flag": False, "exe_order": basic, "exe_orders": []}

    # （０）Peakデータを取得する(データフレムは二時間半前くらいが良い？？）
    print(" Range調査対象")
    df_r_range = df_r[:100]  #  35
    print(df_r_range.head(1))
    print(df_r_range.tail(1))
    peaks_info = p.peaks_collect_main(df_r[:60], 10)  # Peaksの算出（ループ時間短縮の為、必要最低限のピーク数（＝４）を指定する）
    peaks = peaks_info['all_peaks']
    print("PEAKS")
    f.print_arr(peaks)
    latest = peaks[0]
    river = peaks[1]  # 最新のピーク（リバーと呼ぶ。このCount＝２の場合、折り返し直後）
    turn = peaks[2]  # 注目するポイント（ターンと呼ぶ）
    flop3 = peaks[3]  # レンジ判定用（プリフロップと呼ぶ）

    if latest['count'] != 2:
        print(" latestがCOUNT2以外")
        return flag_and_orders

    # （１）RangeInspectionを実施（ここでTakePositionFlagを付与する）
    line_result = ri.find_lines_mm(df_r[:35])  # Lineが発見された場合には、['line_strength']が１以上になる
    print("結果", line_result['latest_flag'])
    # print(line_result)

    if line_result['latest_flag'] and line_result['latest_line']['line_strength'] > 1:# >= 1.5 < 1
        # 直近がLINEを形成し、さらにそれが強いラインの場合。
        main_order = basic.copy()
        main_order['target'] = 0.01  # LCは広め
        main_order['tp'] = 0.05  # LCは広め
        main_order['lc'] = 0.05  # LCは広め
        main_order['expected_direction'] = line_result['latest_line']['line_direction'] * 1  # -
        main_order['priority'] = line_result['latest_line']['line_strength']
        main_order['units'] = basic['units'] * 2
        main_order['name'] = str(line_result['latest_line']['line_strength']) + "Main_resistance"
        # 注文を配列に追加
        exe_orders_arr.append(f.order_finalize(main_order))
        print(" ★★ORDER PRINT")
        print(exe_orders_arr)
        print(exe_orders_arr[0])
        flag_and_orders = {
            "take_position_flag": True,
            "exe_orders": exe_orders_arr,  # 本番用の、辞書の配列
            "exe_order": exe_orders_arr[0],
        }
        return flag_and_orders
    else:
        # 【検証用分岐】CSV出力時に項目がずれないように、ポジションフラグがない場合でもオーダーベースは残す
        # 本番環境では不要となる
        flag_and_orders = {
            "take_position_flag": False,
            "exe_orders": exe_orders_arr,  # 本番用の、辞書の配列
            "exe_order": f.order_finalize(basic),
        }
        return flag_and_orders


def Inspection_test_predict_line(df_r):
    """
    主にExeから呼ばれ、ダブル関係の結果(このファイル内のbeforeとbreak)をまとめ、注文形式にして返却する関数
    引数
    "data": df_r ローソク情報(逆順[直近が上の方にある＝時間降順])のみ。

    :return:
    　このリターンの値は、そのまま発注に使われる。
    　本番（main_exe)から呼ばれる場合と、検証(main_analysis)から呼ばれる場合では、返すべき値が異なることに注意。
    　本番環境は複数のオーダーが可能だが、検証は一つのオーダーのみしか受け付けられないため。
    　本番環境を行いながらでもテストができるように、辞書配列と辞書を同時に返却する
    　（辞書は基本的に辞書配列の[0]となる見込み）
    　返却値は以下の通り
      return{
            "take_position_flag": True or False　Trueの場合、オーダーが入る
            "exe_orders": オーダーの【配列】。複数オーダーが可能な本番環境用
            "exe_order": オーダーの辞書単品。単品オーダーのみ受付可能な検証環境用（基本、exe_orders[0]でOK？）
      }
    """
    # 現在価格を取得する
    # now_price = oa.NowPrice_exe("USD_JPY")['data']['mid']
    now_price = df_r.iloc[0]['open']  # LatestがのOpen価格が現実的には一番直近の額となる
    take_position_flag = False  # 初期値を設定する

    # 返却値を設定しておく
    # テストでは、Orderは配列で渡し、中身はBasicの中身をfinalizeしたものを利用する）
    exe_orders_arr = []  # 配列
    basic = {
            "target": 0.00,
            "type": "STOP",
            "units": 100,
            "expected_direction": 1,
            "tp": 0.10,
            "lc": 0.10,
            'priority': 0,
            "decision_price": now_price,
            "decision_time": df_r.iloc[0]['time_jp'],
            "name": "",
        "lc_change": {"lc_change_exe": True, "lc_trigger_range": 0.05, "lc_ensure_range": 0.012}
    }
    flag_and_orders = {"take_position_flag": False, "exe_order": basic, "exe_orders": []}

    # （０）Peakデータを取得する(データフレムは二時間半前くらいが良い？？）
    print(" Range調査対象")
    df_r_range = df_r[:100]  #  35
    print(df_r_range.head(1))
    print(df_r_range.tail(1))
    peaks_info = p.peaks_collect_main(df_r[:60], 10)  # Peaksの算出（ループ時間短縮の為、必要最低限のピーク数（＝４）を指定する）
    peaks = peaks_info['all_peaks']
    print("PEAKS")
    f.print_arr(peaks)
    latest = peaks[0]
    river = peaks[1]  # 最新のピーク（リバーと呼ぶ。このCount＝２の場合、折り返し直後）
    turn = peaks[2]  # 注目するポイント（ターンと呼ぶ）
    flop3 = peaks[3]  # レンジ判定用（プリフロップと呼ぶ）

    if latest['count'] != 3:  # 予測なので、Latestが４個続いたときに実行してみる
        print(" latestがCOUNT4の場合のみ(今回対象外）")
        return flag_and_orders

    # （１）RangeInspectionを実施（ここでTakePositionFlagを付与する）
    line_result = ri.search_latest_line(df_r[:35])  # Lineが発見された場合には、['line_strength']が１以上になる
    print("結果", line_result['latest_flag'])
    # print(line_result)

    if line_result['latest_line']['line_strength'] > 1:  # >= 1.5 < 1
        # 直近がLINEを形成し、さらにそれが強いラインの場合。 これはLINE探索の方！！！！
        main_order = basic.copy()
        main_order['target'] = line_result['latest_line']['line_price']  # LCは広め
        main_order['tp'] = 0.09  # LCは広め
        main_order['lc'] = 0.09  # LCは広め
        main_order['expected_direction'] = line_result['latest_line']['line_direction'] * 1  # -
        main_order['priority'] = line_result['latest_line']['line_strength']
        main_order['units'] = basic['units'] * 2
        main_order['name'] = str(line_result['latest_line']['line_strength']) + "Main_resistance"
        # 注文を配列に追加
        exe_orders_arr.append(f.order_finalize(main_order))
        print(" ★★ORDER PRINT")
        print(exe_orders_arr)
        print(exe_orders_arr[0])
        flag_and_orders = {
            "take_position_flag": True,
            "exe_orders": exe_orders_arr,  # 本番用の、辞書の配列
            "exe_order": exe_orders_arr[0],
            "line_strength": line_result['latest_line']['line_strength']
        }
        return flag_and_orders
    else:
        # 【検証用分岐】CSV出力時に項目がずれないように、ポジションフラグがない場合でもオーダーベースは残す
        # 本番環境では不要となる
        flag_and_orders = {
            "take_position_flag": False,
            "exe_orders": exe_orders_arr,  # 本番用の、辞書の配列
            "exe_order": f.order_finalize(basic),
        }
        return flag_and_orders


def wrap_up_Inspection_orders(df_r):
    res = Inspection_test(df_r)
    res_predict_line = Inspection_test_predict_line(df_r)

    # 何もない場合の返却値をあらかじめ生成しておく
    for_res = {
        "take_position_flag": False,
        "exe_orders": res['exe_orders']
    }

    if res['take_position_flag'] and res_predict_line['take_position_flag']:
        print("　本来はexe_ordersをがっちゃんこしたい")

    # 今(上記二つの解析)は明確にタイミングが異なり、同時の成立がないため、独立して返却が可能
    if res['take_position_flag']:
        tk.line_send("通常Flag成立")
        for_res = res
    elif res_predict_line['take_position_flag']:
        tk.line_send("予測値あり", res_predict_line['exe_order']['target'], res_predict_line['exe_order']['expected_direction'],
                     "LINE_STRENGTH:", res_predict_line['line_strength'])
        for_res = res_predict_line

    return for_res




