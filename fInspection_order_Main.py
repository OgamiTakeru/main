import copy

import pandas as pd
import threading  # 定時実行用
import time
import datetime
import fBlockInspection as t  # とりあえずの関数集
import tokens as tk  # Token等、各自環境の設定ファイル（git対象外）
import classOanda as classOanda
import making as mk
import fGeneric as gene
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
def inspection_river_line_make_order(df_r):
    # 返却用のDicを書いておく
    flag_and_orders = {
        "take_position_flag": False,
        "exe_orders": [],  # 本番用の、辞書の配列
        "exe_order": gene.order_finalize(gene.order_base(100)),  # 検証用（配列ではなく、一つの辞書）
    }

    # （０）Peakデータを取得する(データフレムは二時間半前くらいが良い？？）
    print(" 【調査】リバーLine")
    df_r_range = df_r[:]  # 数を調整したい場合はここで（基本的にはここでは調整せず、呼び出し元で調整しておく必要がある。）
    print(df_r_range.head(1))
    print(df_r_range.tail(1))
    peaks_info = p.peaks_collect_main(df_r_range, 15)  # Peaksの算出（ループ時間短縮と調査の兼ね合いでpeaks数は15とする）
    peaks = peaks_info['all_peaks']
    print("PEAKS")
    gene.print_arr(peaks)

    if peaks[0]['count'] != 2:  # 予測なので、LatestがN個続いたときに実行してみる
        print(" latestがCOUNTが2以外の場合は終了")
        return flag_and_orders

    # 1,旧順張りのためのLINEを見つける方法(riverを基準にする場合）
    line_info = ri.find_latest_line_based_river(df_r_range, peaks)

    # 1-3 オーダーを発行する
    # オーダー情報の準備
    # now_price = oa.NowPrice_exe("USD_JPY")['data']['mid']
    now_price = df_r.iloc[0]['open']
    order_base_info = gene.order_base(now_price)  # オーダーの初期辞書を取得する
    exe_orders_arr = []

    if line_info['strength_info']['line_strength'] > 2:  # >= 1.5 < 1
        # 直近がLINEを形成し、さらにそれが強いラインの場合。
        main_order = order_base_info.copy()
        main_order['target'] = 0.01
        main_order['tp'] = 0.05  # LCは広め
        main_order['lc'] = 0.05  # LCは広め
        main_order['type'] = 'LIMIT'
        main_order['expected_direction'] = peaks[1]['direction'] * -1  # riverベース。*1=突破,*-1抵抗
        main_order['priority'] = line_info['strength_info']['line_strength']
        main_order['units'] = order_base_info['units'] * 1
        main_order['name'] = str(line_info['strength_info']['line_strength']) + "Main_resistance"
        main_order["lc_change"] = [
            {"lc_change_exe": True, "lc_trigger_range": 0.04, "lc_ensure_range": 0.01}
        ]
        # 注文を配列に追加
        exe_orders_arr.append(gene.order_finalize(main_order))
        # print(" ★★ORDER PRINT")
        # print(exe_orders_arr)
        # print(exe_orders_arr[0])
        flag_and_orders = {
            "take_position_flag": True,
            "exe_orders": exe_orders_arr,  # 本番用の、辞書の配列
            "exe_order": exe_orders_arr[0],  # 検証用（配列ではなく、一つの辞書）
        }
        return flag_and_orders
    elif peaks[1]['count'] == 5:  # riverが5の場合は、もっと伸びると信じる
        # 折り返し直後だが、同一価格がない場合（突破するケースが多い？？）
        main_order = order_base_info.copy()
        main_order['target'] = 0.01
        main_order['tp'] = 0.05  # LCは広め
        main_order['lc'] = 0.05  # LCは広め
        main_order['expected_direction'] = peaks[1]['direction'] * 1  # riverベース。*1=突破,*-1抵抗
        main_order['priority'] = line_info['strength_info']['line_strength']
        main_order['units'] = order_base_info['units'] * 0.1
        main_order['name'] = str(line_info['strength_info']['line_strength']) + "NoLine_resistance"
        main_order["lc_change"] = [
            {"lc_change_exe": True, "lc_trigger_range": 0.04, "lc_ensure_range": 0.01}
        ]
        # 注文を配列に追加
        exe_orders_arr.append(gene.order_finalize(main_order))
        # print(" ★★ORDER PRINT")
        # print(exe_orders_arr)
        # print(exe_orders_arr[0])
        flag_and_orders = {
            "take_position_flag": True,
            "exe_orders": exe_orders_arr,  # 本番用の、辞書の配列
            "exe_order": exe_orders_arr[0],  # 検証用（配列ではなく、一つの辞書）
        }
        return flag_and_orders
    else:
        # 【検証用分岐】CSV出力時に項目がずれないように、ポジションフラグがない場合でもオーダーベースは残す
        # 本番環境では不要となる
        flag_and_orders = {
            "take_position_flag": False,
            "exe_orders": exe_orders_arr,  # 本番用の、辞書の配列
            "exe_order": gene.order_finalize(order_base_info),  # 検証用（配列ではなく、一つの辞書）
        }
        return flag_and_orders


def inspection_predict_line_make_order(df_r):
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
    # 返却値を設定しておく
    flag_and_orders = {
        "take_position_flag": False,
        "exe_orders": [],   # 本番用（本番運用では必須）
        "exe_order": {}  # 検証用（CSV出力時。なお本番運用では不要だが、検証運用で任意。リストではなく辞書1つのみ）
    }
    # 各リスト
    now_price = df_r.iloc[0]['open']  # 現在時は、めんどうなのでAPIを叩かずに、データから取っちゃう。
    order_base_info = gene.order_base(now_price)  # オーダーの初期辞書を取得する
    # 関数が来た時の表示
    print("   OrderCreateMain【調査】予測Line")
    print(df_r.head(1))
    print(df_r.tail(1))

    # （０）Peakデータを取得する(データフレムは二時間半前くらいが良い？？）
    peaks_info = p.peaks_collect_main(df_r[:], 15)  # Peaksの算出（ループ時間短縮の為、必要最低限のピーク数（＝４）を指定する）
    peaks = peaks_info['all_peaks']
    print("PEAKS(予測)")
    gene.print_arr(peaks)
    latest = peaks[0]

    if latest['count'] != 2:  # 予測なので、LatestがN個続いたときに実行してみる
        print(" latestがCOUNTが３以外の場合は終了")
        return flag_and_orders

    # （１）RangeInspectionを実施（ここでTakePositionFlagを付与する）
    predict_line_info_list = ri.find_predict_line_based_latest(df_r[:])  # Lineが発見された場合には、['line_strength']が１以上になる
    print(" (Main)受け取った同価格リスト")
    gene.print_arr(predict_line_info_list)

    # （２）状況にあわせたオーダーを生成する
    for each_line_info in predict_line_info_list:
        # 受け取った価格リストからオーダーを生成する
        line_strength = float(each_line_info['strength_info']['line_strength'])
        peak_strength_ave = float(each_line_info['strength_info']['peak_strength_ave'])
        target_price = each_line_info['line_base_info']['line_base_price']
        print("  (M)Line等の強度", line_strength, peak_strength_ave)
        # オーダーの元を生成する
        main_order = copy.deepcopy(order_base_info)

        # 強度の組み合わせで、オーダーを生成する
        if line_strength >= 0.5 and peak_strength_ave >= 0.75:
            # ①強い抵抗線となりそうな場合（Latestから見ると、逆張り[limitオーダー]となる)
            print("  (m)強い抵抗線　line,peak", line_strength, peak_strength_ave, target_price)
            main_order['target'] = each_line_info['line_base_info']['line_base_price']
            main_order['tp'] = 0.1 * line_strength  # 0.09  # LCは広め
            main_order['lc'] = 0.1 * line_strength  # 0.09  # LCは広め
            main_order['type'] = 'LIMIT'
            # main_order['tr_range'] = 0.10  # 要検討
            main_order['expected_direction'] = peaks[0]['direction'] * -1  # latestに対し、1は突破。*-1は折り返し
            main_order['priority'] = each_line_info['strength_info']['line_strength']
            main_order['units'] = order_base_info['units'] * line_strength
            main_order['name'] = "LINE探索(強抵抗)" + str(each_line_info['strength_info']['line_strength'])
            main_order['lc_change'] = [
                {"lc_change_exe": True, "lc_trigger_range": 0.03, "lc_ensure_range": -0.05},
                {"lc_change_exe": True, "lc_trigger_range": 0.05, "lc_ensure_range": 0.012},
                {"lc_change_exe": True, "lc_trigger_range": 0.10, "lc_ensure_range": 0.08}
            ]
            # オーダーが来た場合は、フラグをあげ、オーダーを追加する
            flag_and_orders['take_position_flag'] = True
            flag_and_orders["exe_orders"].append(gene.order_finalize(main_order))
            flag_and_orders["exe_order"] = main_order  # とりあえず代表一つ。。
        elif line_strength < 0:
            # フラッグ形状が発覚している場合。Latest方向に強く伸びる予想 (通過と同義だが、プライオリティが異なる）
            print("  (m)フラッグ検出（大きな動き前兆）", line_strength, peak_strength_ave, target_price)
            main_order['target'] = each_line_info['line_base_info']['line_base_price']
            main_order['tp'] = 0.09  # LCは広め
            main_order['lc'] = 0.05  #
            main_order['type'] = 'STOP'  # 順張り
            # main_order['tr_range'] = 0.10  # 要検討
            main_order['expected_direction'] = peaks[0]['direction'] * 1  # latestに対し、1は突破。*-1は折り返し
            main_order['priority'] = 2
            main_order['units'] = order_base_info['units'] * 1
            main_order['name'] = "フラッグ検出" + str(each_line_info['strength_info']['line_strength'])
            main_order['lc_change'] = [
                {"lc_change_exe": True, "lc_trigger_range": 0.03, "lc_ensure_range": -0.05},
                {"lc_change_exe": True, "lc_trigger_range": 0.05, "lc_ensure_range": 0.012},
                {"lc_change_exe": True, "lc_trigger_range": 0.10, "lc_ensure_range": 0.08}
            ]
            # オーダーが来た場合は、フラグをあげ、オーダーを追加する
            flag_and_orders['take_position_flag'] = True
            flag_and_orders["exe_orders"].append(gene.order_finalize(main_order))
            flag_and_orders["exe_order"] = main_order  # とりあえず代表一つ。。
        elif peak_strength_ave < 0.75:
            # ②ピークが弱いものばかりである場合、通過点レベルの線とみなす（Latestから見ると、順張りとなる）
            print("  (m)通過線　line,peak", line_strength, peak_strength_ave, target_price)
            main_order['target'] = each_line_info['line_base_info']['line_base_price']
            main_order['tp'] = 0.03  # LCは広め
            main_order['lc'] = 0.04  # LCは広め
            main_order['type'] = 'STOP'  # 順張り
            # main_order['tr_range'] = 0.10  # 要検討
            main_order['expected_direction'] = peaks[0]['direction'] * 1  # latestに対し、1は突破。*-1は折り返し
            main_order['priority'] = 1
            main_order['units'] = order_base_info['units'] * 1.1
            main_order['name'] = "LINE探索(通過)" + str(each_line_info['strength_info']['line_strength'])
            main_order['lc_change'] = [
                {"lc_change_exe": True, "lc_trigger_range": 0.03, "lc_ensure_range": -0.02},
                {"lc_change_exe": True, "lc_trigger_range": 0.05, "lc_ensure_range": 0.012},
                {"lc_change_exe": True, "lc_trigger_range": 0.10, "lc_ensure_range": 0.08}
            ]
            # オーダーが来た場合は、フラグをあげ、オーダーを追加する
            flag_and_orders['take_position_flag'] = True
            flag_and_orders["exe_orders"].append(gene.order_finalize(main_order))
            flag_and_orders["exe_order"] = main_order  # とりあえず代表一つ。。
        else:
            # オーダー条件に合わない場合は、変更しない（main_orderのまま）。
            # ただしこれは存在しない見込み（SamePriceが存在する＝オーダーを入れる）
            pass

    # (3) 設定されるLINEが遠すぎる場合、そこには到達するだろう、という見込みで現在価格からそこへ向かうオーダーを追加する
    if len(predict_line_info_list)>0:
        # predictLineが存在する場合のみ実行
        if latest['direction'] == 1:
            # 直近が上向きの場合（それよりも上側にオーダーLINEが設定されているオーダーリストの先頭が一番高い）
            farthest_line = predict_line_info_list[0]['line_base_info']['line_base_price']
            farthest_gap = farthest_line - now_price
            nearest_line = predict_line_info_list[-1]['line_base_info']['line_base_price']
            nearest_gap = nearest_line - now_price
        else:
            # 直近が下向きの場合　（それよりも下側にオーダーLINEが設定されている。オーダーリストの先頭が一番低い。Latestによって
            farthest_line = predict_line_info_list[0]['line_base_info']['line_base_price']
            farthest_gap = farthest_line - now_price
            nearest_line = predict_line_info_list[-1]['line_base_info']['line_base_price']
            nearest_gap = nearest_line - now_price
        if nearest_gap >= 0.15:
            # 近くてもGapが15Pips以上ある場合、Latestがそのまま延長して、そのLineまで頑張ると想定する。
            main_order = copy.deepcopy(order_base_info)  # オーダーの生成
            main_order['target'] = 0.015  # 少しだけ余裕を見て設定
            main_order['tp'] = 0.03  # LCは広め
            main_order['lc'] = 0.03  # LCは広め
            main_order['type'] = 'STOP'  # Latestに対して、順張り
            # main_order['tr_range'] = 0.10  # 要検討
            main_order['expected_direction'] = peaks[0]['direction'] * 1  # latestに対し、1は突破。*-1は折り返し
            main_order['priority'] = 1
            main_order['units'] = order_base_info['units'] * 1.2
            main_order['name'] = "Line遠(Latest延長)" + str(1)
            main_order['lc_change'] = [
                {"lc_change_exe": True, "lc_trigger_range": 0.03, "lc_ensure_range": -0.05},
                {"lc_change_exe": True, "lc_trigger_range": 0.05, "lc_ensure_range": 0.012},
                {"lc_change_exe": True, "lc_trigger_range": 0.10, "lc_ensure_range": 0.08}
            ]
            # オーダーが来た場合は、フラグをあげ、オーダーを追加する
            flag_and_orders['take_position_flag'] = True
            flag_and_orders["exe_orders"].append(gene.order_finalize(main_order))
            flag_and_orders["exe_order"] = main_order  # とりあえず代表一つ。。

    # プライオリティの最大値を取得しておく
    max_priority = max(flag_and_orders["exe_orders"], key=lambda x: x['priority'])['priority']
    flag_and_orders['max_priority'] = max_priority
    print(max_priority)
    print(flag_and_orders)

    return flag_and_orders


def wrap_up_inspection_orders(df_r):
    # 必要最低限の返却値の定義
    for_res = {
        "take_position_flag": False,  # 必須
        "exe_orders": [],  # 仮で作っておく
        "exe_order": {}
    }

    # 調査実施
    line_order_info = inspection_river_line_make_order(df_r)
    p_line_order_info = inspection_predict_line_make_order(df_r)

    if line_order_info['take_position_flag'] and p_line_order_info['take_position_flag']:
        print("　本来はexe_ordersをがっちゃんこしたい(現状は同タイミングはありえない）")

    # 今(上記二つの解析)は明確にタイミングが異なり、同時の成立がないため、独立して返却が可能
    if line_order_info['take_position_flag']:
        # tk.line_send("通常Flag成立")
        for_res = line_order_info
    elif p_line_order_info['take_position_flag']:
        print(p_line_order_info)
        for_res = p_line_order_info

    return for_res




