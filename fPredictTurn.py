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
    # predict_result2 = cal_little_turn_at_trend(peaks_class)
    # if predict_result2['take_position_flag']:
    #     flag_and_orders["take_position_flag"] = True
    #     flag_and_orders["exe_orders"] = predict_result2['exe_orders']
    #     # 代表プライオリティの追加
    #     max_priority = max(flag_and_orders["exe_orders"], key=lambda x: x['priority'])['priority']
    #     flag_and_orders['max_priority'] = max_priority
    #     flag_and_orders['for_inspection_dic'] = {}
    #
    #     return flag_and_orders

    return flag_and_orders


def cal_little_turn_at_trend(peaks_class):
    """
    args[0]は必ずpeaks_classであること。
    args[1]は、本番の場合、過去の決済履歴のマイナスの大きさでTPが変わるかを検討したいため、オーダークラスを受け取る

    直近[0]がcount4の時、riverPeakにレジスタンスオーダーを入れる
    """
    # ■基本情報の取得
    print("★★PREDICT　本番用")
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

    # ■実行除外
    # 対象のPeakのサイズを確認（小さすぎる場合、除外）
    if t['gap'] < 0.04:
        print("対象が小さい", t['gap'])
        # return default_return_item

    # ■判定に必要な数字の算出
    # (1)強度の判定
    peaks_class.make_same_price_list(turn_peak_no, False)  # クラス内でSamePriceListを実行
    turn_strength = sum(d["item"]["peak_strength"] for d in peaks_class.same_price_list)
    gene.print_arr(peaks_class.same_price_list)
    print("同一価格リストの強度の合計値;", turn_strength)  # 10以上だと強い⇒抵抗OrderのLCを小さくとる（越えた場合大きく越えそう）
    # (２) turnを生成するPeakに、スキップがあったかを確認する
    if peaks_class.cal_target_times_skip_num(peaks_class.skipped_peaks_hard, t['latest_time_jp']) >= 1:
        skip_exist = True
    else:
        skip_exist = False
    # (3) 越えていない場合の、[0](river)と[1](turn)の比率
    rt_ratio_sk = round(r_sk['gap'] / t_sk['gap'], 3)
    rt_ratio = round(r['gap'] / t['gap'], 3)
    # (4) トレンドの減速の検知
    target_df = peaks_class.peaks_original_with_df[1]['data']  # "data"は特殊なPeaksが所持（スキップ非対応）
    brake_trend_exist = False
    print("[1]のデータ")
    print(target_df)
    if len(target_df) < 4:
        print("target_dataが少なすぎる([1]がやけに短い⇒TrendBrakeあり？）")
        brake_trend_exist = True
    else:
        # BodyAveで検討
        older_body_ave = round((target_df.iloc[2]['body_abs'] + target_df.iloc[3]['body_abs']) / 2,
                               2) + 0.0000000001  # 0防止
        later_body_ave = round((target_df.iloc[0]['body_abs'] + target_df.iloc[1]['body_abs']) / 2,
                               2) + 0.0000000001  # 0防止
        print("ratio", round(older_body_ave / later_body_ave, 2), "older", older_body_ave, "latest", later_body_ave)
        if older_body_ave / later_body_ave >= 3.5:  # 数が大きければ、よりブレーキがかかる
            print("傾きの顕著な減少（ボディ）")
            brake_trend_exist = True
    # 結果表示まとめ
    print("R数", r['count'], "スキップ有:", skip_exist, "tCount", t['count'], "SKIP数", t_sk['skip_include_num'])
    print("ターン強度", turn_strength, "戻り率(通常)", rt_ratio)
    print("傾きのブレーキ有無:", brake_trend_exist, "TURN数", r['count'], "戻率(Skip有)", rt_ratio_sk)

    # 本番用★★
    exe_orders = []
    if r['count'] == 2:
        if ((skip_exist or 6 <= t['count'] < 100) and t_sk['skip_include_num'] < 3 and
                0 < turn_strength <= 8 and 0 < rt_ratio <= 0.16):
            comment = "●●Count2のすぐBreak"
            target_price = t['latest_body_peak_price']  # targetはTurnのピーク値
            margin_border = 0.02
            if abs(target_price - peaks_class.latest_price) <= margin_border:
                # ほとんど即時オーダーになってしまう場合、1.5pipのマージンを取る
                print("即時オーダーになりそう")
                margin = margin_border
            else:
                # それ以外は基本的に通常通り、ＴａｒｇｅｔＰｒｉｃｅを使う（マージンを０にする）
                margin = 0
            lc_price = r['latest_wick_peak_price']
            lc_range = gene.cal_at_least(0.03, round(abs(target_price - lc_price), 3))  # lc_rangeに変換し最低値を確保
            print("参考 lc_price", lc_price, "lc_range:", round(abs(target_price - lc_price), 3), "targetPrice",
                  target_price)
            print("LCrange", lc_range, "latest_price", peaks_class.latest_price)
            temp = round(abs(target_price - t['latest_wick_peak_price']), 3)
            change_temp = gene.cal_at_least(0.04, temp)
            order = order_make_dir1_s(
                peaks_class, comment, target_price, margin, 1,
                peaks_class.cal_move_ave(1.2),
                peaks_class.cal_move_ave(1),
                # {"lc_change_exe": True, "time_after": 0, "lc_trigger_range": change_temp + 0.01,
                #  "lc_ensure_range": change_temp - 0.01},
                1,
                1.5,
                3)
            order['order_timeout_min'] = 10  # 5分でオーダー消去（すぐに越えてない場合はもうNGとみなす。最大10分か？）
            exe_orders.append(order)
        elif ((skip_exist or 5 <= t['count'] < 100) and t_sk['skip_include_num'] < 3 and
              0 < turn_strength <= 8 and 0.18 < rt_ratio <= 0.50):
            comment = "△Count2のすぐRange側"
            target_price = peaks_class.latest_price
            margin = round(abs(t['gap']) / 4, 3)
            order = order_make_dir0_s(
                peaks_class, comment, target_price, margin, 1,
                peaks_class.cal_move_ave(1.2),
                peaks_class.cal_move_ave(1.2),
                1,
                1,
                3)
            order['order_timeout_min'] = 5  # 5分でオーダー消去（すぐに越えてない場合はもうNGとみなす。最大10分か？）
            exe_orders.append(order)
        elif ((skip_exist or 5 <= t['count'] < 100) and t_sk['skip_include_num'] < 3 and
              11 < turn_strength <= 100 and 0.10 < rt_ratio <= 0.30):
            comment = "△Count2で抵抗値高い"
            target_price = t['latest_body_peak_price']
            margin = round(abs(t['gap']) / 4, 3)
            order = order_make_dir0_s(
                peaks_class, comment, target_price, 0, 1,
                peaks_class.cal_move_ave(1.5),
                peaks_class.cal_move_ave(1.0),
                1,
                0.5,
                3)
            order['order_timeout_min'] = 5  # 5分でオーダー消去（すぐに越えてない場合はもうNGとみなす。最大10分か？）
            exe_orders.append(order)
        else:
            print("NoOrder 1")
            return default_return_item
    elif r['count'] == 3:
        if ((skip_exist or 7 <= t['count'] < 100) and t_sk['skip_include_num'] < 3 and
                0 < turn_strength <= 8 and 0 < rt_ratio <= 0.36):
            comment = "●●●強いやつ"
            # target_price = peaks[0]['latest_body_peak_price']
            target_price = peaks_class.latest_price
            temp = round(abs(target_price - t['latest_wick_peak_price']), 3)
            change_temp = gene.cal_at_least(0.04, temp)
            exe_orders.append(
                order_make_dir1_s(
                    peaks_class, comment, target_price, peaks_class.cal_move_ave(0.55), -1,
                    peaks_class.cal_move_ave(5),
                    peaks_class.cal_move_ave(2.2),
                    3,
                    2.5,
                    4)
            )
        else:
            print("NoOrder 2")

            return default_return_item
    else:
        print("NoOrder 3")
        # # test即時オーダー用↓
        # target_price = peaks_class.latest_price
        # comment = "test"
        # exe_orders.append(
        #     order_make_dir1_s(
        #         peaks_class, "test", target_price, peaks_class.cal_move_ave(0.6), -1,
        #         peaks_class.cal_move_ave(5),
        #         peaks_class.cal_move_ave(2.2),
        #         3,
        #         0.1,
        #         4)
        # )
        # # test即時オーダーここまで↑
        return default_return_item

    # 本番用ここまで★★
    print(comment)
    gene.print_arr(exe_orders)
    return {
        "take_position_flag": True,
        "exe_orders": exe_orders,
        "for_inspection_dic": {}
    }


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