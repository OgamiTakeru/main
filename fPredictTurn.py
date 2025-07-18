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
import bisect


def wrap_predict_turn_inspection_test(df_r):
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
    predict_result2 = cal_predict_turn_at_trend(peaks_class)
    if predict_result2['take_position_flag']:
        flag_and_orders["take_position_flag"] = True
        flag_and_orders["exe_orders"] = predict_result2['exe_orders']
        # 代表プライオリティの追加
        max_priority = max(flag_and_orders["exe_orders"], key=lambda x: x['priority'])['priority']
        flag_and_orders['max_priority'] = max_priority
        flag_and_orders['for_inspection_dic'] = {}

        return flag_and_orders

    return flag_and_orders

def wrap_predict_turn_inspection(peaks_class):
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
    predict_result2 = cal_predict_turn_at_trend(peaks_class)
    if predict_result2['take_position_flag']:
        flag_and_orders["take_position_flag"] = True
        flag_and_orders["exe_orders"] = predict_result2['exe_orders']
        # 代表プライオリティの追加
        max_priority = max(flag_and_orders["exe_orders"], key=lambda x: x['priority'])['priority']
        flag_and_orders['max_priority'] = max_priority
        flag_and_orders['for_inspection_dic'] = {}

        return flag_and_orders

    return flag_and_orders


def cal_predict_turn_at_trend(peaks_class):
    """
    args[0]は必ずpeaks_classであること。
    args[1]は、本番の場合、過去の決済履歴のマイナスの大きさでTPが変わるかを検討したいため、オーダークラスを受け取る

    基本的に折り返したタイミング(riverカウントが2の時)で、次どこで折り返すかのオーダーを入れる。
    その為基本的に、riverピークの方向とは逆のオーダーを入れる。

    （遠すぎる場合は考え物だが）
    """
    # ■基本情報の取得
    print("★★予測　解析　本番用")
    take_position = False
    # ■返却値の設定
    default_return_item = {
        "take_position_flag": take_position,
        "for_inspection_dic": {}
    }
    s = "    "

    # ■Peaks等、大事な変数の設定、ターゲットになるピークを選択
    turn_peak_no = 1  # 以下のループで「自分以外」を定義するため、変数に入れておく(同一方向の配列に対して）
    river_peak_no = turn_peak_no - 1  #
    peaks = peaks_class.peaks_original_marked_hard_skip
    peaks_sk = peaks_class.skipped_peaks_hard  # 元々の
    r = peaks[river_peak_no]  # 折り返し部分をRiverの頭文字をとってRとする。latestの部分がRになるケースが基本だが、[1]をRとするケースもあり
    t = peaks[turn_peak_no]  # ターンの頂点となる部分のためTurnの頭文字でTとする。
    r_sk = peaks_sk[river_peak_no]  # 折り返し部分をRiverの頭文字をとってRとする。latestの部分がRになるケースが基本だが、[1]をRとするケースもあり
    t_sk = peaks_sk[turn_peak_no]  # ターンの頂点となる部分のためTurnの頭文字でTとする。

    # ■処理開始
    # (3) 越えていない場合の、[0](river)と[1](turn)の比率
    rt_ratio_sk = round(r_sk['gap'] / t_sk['gap'], 3)
    rt_ratio = round(r['gap'] / t['gap'], 3)
    # if 0<rt_ratio<0.7:
    #     pass
    # else:
    #     return  default_return_item

    search_range = 0.09
    first_margin = 0.01
    search_grid = 0.02
    search_range_upper = round(search_grid/2, 3)  #0.01  # searchPriceの上下この範囲内でのピークを探す
    search_range_lower = round(search_grid/2, 3)  #0.01
    search_price = peaks_class.latest_price
    suggested_peaks = []
    loop_manegement = 0
    i = 0
    print("直近価格（スタート）", search_price)
    if r['count'] == 2:
        # 基本的には折り返し直後（riverカウント2の場合のみ）
        while loop_manegement <= search_range:  # ★ループ処理
            if r['direction'] == 1:
                if i == 0:
                    search_price = search_price + first_margin + search_grid
                else:
                    search_price = search_price + search_grid
            else:
                if i == 0:
                    search_price = search_price - first_margin - search_grid
                else:
                    search_price = search_price - search_grid
            search_price_upper = search_price + search_range_upper
            search_price_lower = search_price - search_range_lower
            # print("検索価格", round(search_price, 3), "(", search_price_lower, "-", search_price_upper)

            # 検索
            each_range_peaks = []
            for i, item in enumerate(peaks):
                # print("    ", item['latest_time_jp'])
                if i == 0:  # latestは無効
                    continue
                if item['direction'] != r['direction']:
                    # 方向が逆方向
                    continue
                # print("　検索対象", item['latest_body_peak_price'], item['latest_time_jp'])
                if search_price_lower <= item['latest_body_peak_price'] <= search_price_upper:
                    # print("                対象発見", item['latest_body_peak_price'], item['latest_time_jp'])
                    each_range_peaks.append(item)
            # 各調査での結果を集計＆格納
            each_range_peaks = sorted(each_range_peaks, key=lambda x: x["latest_body_peak_price"], reverse=(r['direction'] * -1 == 1))
            suggested_peaks.append(
                {
                    "base_price": round(search_price, 3),
                    "peaks": each_range_peaks
                }
            )
            loop_manegement += search_grid  # ★ループ処理★
            i += 1  # ★ループ処理

    # ■検証する
    if len(suggested_peaks) == 0:
        return default_return_item
    # 最も強いところを
    max_base_price = 0
    max_base_price_len = 0
    max_peak_streng = 0
    far_price = 0
    far_peak_strength = 0
    for each in suggested_peaks:
        # 表示用
        if len(each['peaks']) != 0:
            print("　　Base：", each['base_price'])
            for peak in each['peaks']:
                print("     対象:", peak['latest_time_jp'], peak['latest_body_peak_price'], peak['peak_strength'])
                pass
        # 抵抗累計が最大値の取得
        strength =sum(item["peak_strength"] for item in each['peaks'])
        if strength > max_peak_streng:  # >=にすると遠いほうで上書きされるので、一番近くで、Strengthが強いところを求める
            max_peak_streng = strength
            max_base_price = each['base_price']
        # 最も遠いところの算出
        if len(each['peaks']) != 0:
            far_price = each['base_price']
            far_peak_strength = strength
    print("予期されるターン方向:", r['direction'] * -1)
    print("調査範囲", search_price)
    print("最大の抵抗ポイント")
    print(max_base_price, max_peak_streng)
    print("最も離れてるポイントと、その差金額差（ＬＣ候補 gridに依存する）")
    print(far_price, "差分", round(abs(far_price - max_base_price), 3), "強度", far_peak_strength)
    if max_base_price == 0:
        return default_return_item

    # ■注文
    exe_orders = []
    order = order_make_dir1_s(
        peaks_class, str(max_peak_streng) + "反転予測", max_base_price, 0, 1,
        round(t['gap'] * 0.7, 3),
        round(t['gap'] * 0.7, 3),
        # peaks_class.cal_move_ave(2),
        # peaks_class.cal_move_ave(1.5),
        3,
        1,
        3)
    order['order_timeout_min'] = 45  # 45分でオーダー消去（すぐに越えてない場合はもうNGとみなす。最大10分か？）
    exe_orders.append(order)

    return default_return_item
    # print("PredictOrder発行")
    # print(order)
    #
    # # 本番用ここまで★★
    # gene.print_arr(exe_orders)
    # return {
    #     "take_position_flag": True,
    #     "exe_orders": exe_orders,
    #     "for_inspection_dic": {}
    # }


def order_make_dir0_s(peaks_class, comment, target_num, margin, margin_dir, tp, lc, lc_change, uni_base_time, priority):
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
        "units": units,
        "name": comment,
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


def order_make_dir1_s(peaks_class, comment, target_num, margin, margin_dir, tp, lc, lc_change, uni_base_time, priority):
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