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


def wrap_up_predict(peaks_class):
    """
    クラスをたくさん用いがケース
    args[0]は必ずdf_rであることで、必須。
    args[1]は、本番の場合、過去の決済履歴のマイナスの大きさでTPが変わるかを検討したいため、オーダークラスを受け取る
    """
    print("■■■■調査開始■■■■")

    #
    flag_and_orders = {
        "take_position_flag": False,
        "exe_orders": [],  # 本番用（本番運用では必須）
    }

    # predict 初期
    # predict_result = cal_predict_turn(peaks_class)  #
    # if predict_result['take_position_flag']:
    #     flag_and_orders["take_position_flag"] = True
    #     flag_and_orders["exe_orders"] = predict_result['exe_orders']
    #     # 代表プライオリティの追加
    #     max_priority = max(flag_and_orders["exe_orders"], key=lambda x: x['priority'])['priority']
    #     flag_and_orders['max_priority'] = max_priority
    #     flag_and_orders['for_inspection_dic'] = {}
    #
    #     return flag_and_orders

    # predict2
    predict_result2 = cal_predict_turn2(peaks_class)
    if predict_result2['take_position_flag']:
        flag_and_orders["take_position_flag"] = True
        flag_and_orders["exe_orders"] = predict_result2['exe_orders']
        # 代表プライオリティの追加
        max_priority = max(flag_and_orders["exe_orders"], key=lambda x: x['priority'])['priority']
        flag_and_orders['max_priority'] = max_priority
        flag_and_orders['for_inspection_dic'] = {}

        return flag_and_orders

    return flag_and_orders

def cal_predict_turn(peaks_class):
    """
    args[0]は必ずpeaks_classであること。
    args[1]は、本番の場合、過去の決済履歴のマイナスの大きさでTPが変わるかを検討したいため、オーダークラスを受け取る

    直近のピーク（latest_peakはこれから伸びるPeakなので、直前のpeakは[1]の物を示す
    """
    # ■基本情報の取得
    print("★★PREDICT　TURN")
    take_position = False
    # ■返却値の設定
    default_return_item = {
            "take_position_flag": take_position,
            "for_inspection_dic": {}
        }
    s = "    "

    # ■Peaks等、大事な変数の設定
    target_num = 2  # 以下のループで「自分以外」を定義するため、変数に入れておく(同一方向の配列に対して）
    # peaks = peaks_class.skipped_peaks
    peaks = peaks_class.skipped_peaks_hard
    if len(peaks)<target_num+1:
        return default_return_item
    peaks_class.make_same_price_list(target_num, True)  # クラス内でSamePriceListを実行
    target_peak = peaks[target_num]
    target_price = target_peak['latest_body_peak_price']
    print("ターゲットになるピーク:", target_peak['peak'], target_peak)

    # ■実行除外
    if len(peaks) < 4:
        # 検証時におかしなことになるため、除外
        return default_return_item
    if peaks[2]['gap'] >= peaks[1]['gap'] * 2.6 or peaks[2]['count'] >= peaks[1]['count'] * 2.6:
        print("オーダーなし[1]と[2]が急激な変動の続きになりそう")
        return default_return_item
    elif peaks[3]['gap'] >= peaks[2]['gap'] * 3 or peaks[3]['count'] >= peaks[2]['count'] * 1.5:
        print("オーダーなし[2]と[3]が急激な変動の続きになりそう")
        return default_return_item

    # 範囲が少ない
    if peaks[0]['count'] == 3 and peaks[1]['count'] >= 3:  # [0]countは２では微妙（２はBreakのケースが多く見える）ので３．
        print("　カウント数は合格", peaks[0]['count'], "が3で、", peaks[1]['count'], "が３以上が対象")
    else:
        print("  山を形成するカウント不足", peaks[0]['count'], "が２で、", peaks[1]['count'], "が３以上が対象")
        return default_return_item
    # 変動が少ないところはスキップ
    if target_peak['gap'] <= 0.04:
        print("targetのGapが少なすぎる", target_peak['gap'], target_peak['latest_time_jp'])
        return default_return_item
    # ターゲットのピークが弱い
    if target_peak['peak_strength'] < 4:
        print("　ターゲットのピークの強さが弱い")
        return default_return_item

    # 戻りが早いと判断される場合
    print("戻し具合の確認", peaks[0]['gap'], peaks[1]['gap'], peaks[0]['gap']/peaks[1]['gap']*100)
    print("戻し具合の確認2", peaks[1]['count'], peaks[0]['count'])
    # riverがlatestの2倍以上のカウントを持ちながら、latest(count=3)で80％も戻されている場合、勢い有と判断
    if peaks[1]['count'] >= peaks[0]['count'] * 2 and peaks[0]['gap']/peaks[1]['gap']*100 >= 80:
        print("戻しが早い")
        return default_return_item

    # 抵抗線を突破してしまっている場合
    if target_peak['direction'] == 1:
        if peaks[0]['latest_price'] >= target_price:
            # 既に抵抗線を突破している場合
            print(" 既に抵抗線を上に突破しており、不可.現在価格:", peaks[0]['latest_price'], "線", target_price)
            return default_return_item
    else:
        if peaks[0]['latest_price'] <= target_price:
            # 既に成功線を下に突破している場合
            print(" 既に抵抗線を下に突破しており、不可.現在価格:", peaks[0]['latest_price'], "線", target_price)
            return default_return_item

    # ■形状等の判定
    old_same_price_time_gap = peaks_class.same_price_list_till_break[-1]['time_gap']
    print("最古の同一価格時間差", old_same_price_time_gap)
    exe_orders = []
    if len(peaks_class.same_price_list_till_break) >= 1 and old_same_price_time_gap >=timedelta(minutes=25):
        take_position = True
        exe_orders.append(resistnce_order(peaks, peaks_class, "Predict抵抗", target_num))
    else:
        print("オーダーしません", len(peaks_class.same_price_list_till_break), old_same_price_time_gap)

    if take_position:
        print("オーダーします", "predict抵抗")
        print(exe_orders)

    return {
        "take_position_flag": take_position,
        "exe_orders": exe_orders,
        "for_inspection_dic": {}
    }


def cal_predict_turn2(peaks_class):
    """
    args[0]は必ずpeaks_classであること。
    args[1]は、本番の場合、過去の決済履歴のマイナスの大きさでTPが変わるかを検討したいため、オーダークラスを受け取る

    直近[0]がcount4の時、riverPeakにレジスタンスオーダーを入れる
    """
    # ■基本情報の取得
    print("★★PREDICT　TURN2222")
    take_position = False
    s = "    "

    # ■Peaks等、大事な変数の設定
    target_num = 1  # 以下のループで「自分以外」を定義するため、変数に入れておく(同一方向の配列に対して）
    # peaks = peaks_class.skipped_peaks
    peaks = peaks_class.skipped_peaks
    peaks_class.make_same_price_list(target_num, True)  # クラス内でSamePriceListを実行
    target_peak = peaks[target_num]
    target_price = target_peak['latest_body_peak_price']
    print("ターゲットになるピーク:", target_peak['peak'], target_peak)

    # ■返却値の設定
    default_return_item = {
        "take_position_flag": take_position,
        "for_inspection_dic": {}
    }

    # ■実行除外
    # 範囲が少ない
    if peaks[0]['count'] == 4:  # and peaks[1]['count'] >= 3:  # [0]countは２では微妙（２はBreakのケースが多く見える）ので３．
        print("　カウント数は合格", peaks[0]['count'], "が4以上が対象")
    else:
        print("  山を形成するカウント不足", peaks[0]['count'], "が4以上が対象")
        return default_return_item

    # ■形状等の判定
    old_same_price_time_gap = peaks_class.same_price_list_till_break[-1]['time_gap']
    print("最古の同一価格時間差", old_same_price_time_gap)
    exe_orders = []
    # [2]～[6]まで(同方向を2個づつ）を見て、サイズ感が不均等であれば、急上昇とみなす
    # directionごとの合計を辞書で保持
    totals = {
        1: {'count': 0, 'gap': 0},
        -1: {'count': 0, 'gap': 0},
    }
    # 集計処理
    for item in peaks[2:6]:
        dir = item['direction']
        totals[dir]['count'] += item['count']
        totals[dir]['gap'] += item['gap']
    print("比率1", totals[1], "-1", totals[-1])
    print("1-2比　1", peaks[1]['gap'], "2", peaks[2]['gap'] , peaks[1]['latest_time_jp'], peaks[2]['latest_time_jp'])
    if (totals[1]['gap'] >= totals[-1]['gap'] * 1.7 or totals[-1]['gap'] >= totals[1]['gap'] * 1.7 or
            totals[1]['count'] >= totals[-1]['count'] * 2 or totals[-1]['count'] >= totals[1]['count'] * 2):
        print("オーダーなし[2]の長さが長い⇒勢い有", peaks[2]['count'], peaks[2]['latest_time_jp'])
        return default_return_item
    elif peaks[2]['gap'] >= peaks[1]['gap'] * 3:
        print("オーダーなし[1]と[2]が急激な変動の続きになりそう")
        return default_return_item
    elif peaks[1]['gap'] >= peaks[0]['gap'] * 3 or peaks[1]['count'] >= peaks[0]['count'] * 3:
        print("オーダーなし[1]と[2]が急激な変動の続きになりそう")
        return default_return_item


    if peaks[1]['gap'] >= 0.04:
        take_position = True
        exe_orders.append(resistnce_order_for_1(peaks, peaks_class, "Predict抵抗2", target_num))
    else:
        print("オーダーしません", len(peaks_class.same_price_list_till_break), old_same_price_time_gap)

    if take_position:
        print("オーダーします", "predict抵抗")
        print(exe_orders)

    return {
        "take_position_flag": take_position,
        "exe_orders": exe_orders,
        "for_inspection_dic": {}
    }


def break_order(peaks, peaks_class, comment, same_price_list):

    same_price_len=len(same_price_list)
    if same_price_len<=3:
        same_price_len=3
    else:
        same_price_len=4

    # ★★履歴によるオーダー調整を実施する（TPを拡大する）★★★
    for_history_class = classPosition.order_information("test", "test", False)  # 履歴参照用
    tuned_data = for_history_class.tuning_by_history_break()  # TuneされたTPやLCChangeを取得する
    tp_range = tuned_data['tuned_tp_range']
    lc_change_type = tuned_data['tuned_lc_change_type']
    print("TP設定", tp_range, "lcChange設定", lc_change_type)

    # flag形状の場合（＝Breakの場合）
    base_order_dic = {
        "target": peaks[1]['latest_wick_peak_price'] + (0.006 * peaks[1]['direction']),
        "type": "STOP",
        "expected_direction": peaks[1]['direction'],
        # "tp": tp_range,  # 短期では0.15でもOK.ただ長期だと、マイナスの平均が0.114のためマイナスの数が多くなる
        # # "lc": 0.09,  # 0.06,
        # "tp": 0.075,
        # "lc": 0.075,
        "tp": 0.075,
        "lc": peaks_class.ave_move_for_lc,
        'priority': 3,
        "decision_time": peaks_class.df_r_original.iloc[0]['time_jp'],
        "decision_price": peaks_class.df_r_original.iloc[1]['close'],
        "order_timeout_min": 20,
        "lc_change_type": 0,
        "name": comment
    }
    base_order_class = OCreate.OrderCreateClass(base_order_dic)  # オーダーファイナライズ
    return base_order_class.finalized_order


def resistnce_order(peaks, peaks_class, comment, target_num):
    target_peak = peaks[target_num]

    # ★★履歴によるオーダー調整を実施する（TPを拡大する）★★★
    for_history_class = classPosition.order_information("test", "test", False)  # 履歴参照用
    tuned_data = for_history_class.tuning_by_history_break()  # TuneされたTPやLC.finalized_orderChangeを取得する
    tp_range = tuned_data['tuned_tp_range']
    lc_change_type = tuned_data['tuned_lc_change_type']
    print("TP設定", tp_range, "lcChange設定", lc_change_type)

    target_price = target_peak['peak'] + (peaks[0]['direction'] * 0.001)
    lc_price = OCreate.cal_lc_price_from_line_and_margin(peaks[1]['latest_wick_peak_price'], 0.03,
                                                         peaks[0]['direction'])
    gap = abs(lc_price - target_price)
    re_lc_range = gene.cal_at_most(0.09, gap)
    print("Orderのgap確認", gap, "target_price:", target_price, "deci_price:",
          peaks_class.df_r_original.iloc[1]['close'])
    base_order_dic = {
        "target": target_price,
        "type": "LIMIT",
        "expected_direction": peaks[0]['direction'] * -1,
        # "tp": tp_range,  # 短期では0.15でもOK.ただ長期だと、マイナスの平均が0.114のためマイナスの数が多くなる
        # "lc": lc_price,  # 0.06,
        "tp": peaks[1]['latest_body_peak_price'],  #0.03,
        "lc": peaks_class.cal_move_size_lc(1),
        # "lc": peaks_class.ave_move_for_lc,
        # "lc": 0.4,
        'priority': 4,
        "decision_time": peaks_class.df_r_original.iloc[0]['time_jp'],
        "decision_price": peaks_class.df_r_original.iloc[1]['close'],
        "order_timeout_min": 90,
        "lc_change_type": 1,
        "name": "PredictLineOrder"
    }
    base_order_class = OCreate.OrderCreateClass(base_order_dic)  # オーダー生成
    # gene.print_json(base_order_class.finalized_order_without_lc_change)  # 表示

    # オーダーの修正と、場合によって追加オーダー設定
    lc_max = 0.15
    lc_change_after = 0.075
    if base_order_class.finalized_order['lc_range'] >= lc_max:
        # LCレンジを計算してLCが大きすぎた場合、オーダー修正（LC短縮）
        print("LCが大きいため再オーダー設定")
        base_order_dic['lc'] = lc_change_after
        base_order_dic['name'] = base_order_dic['name'] + "_LC大で修正_"
        base_order_class = OCreate.OrderCreateClass(base_order_dic)  # オーダー生成（というか作り直し）
    else:
        base_order_class = OCreate.OrderCreateClass(base_order_dic)

    return base_order_class.finalized_order


def resistnce_order_for_1(peaks, peaks_class, comment, target_num):
    target_peak = peaks[target_num]

    # ★★履歴によるオーダー調整を実施する（TPを拡大する）★★★
    for_history_class = classPosition.order_information("test", "test", False)  # 履歴参照用
    tuned_data = for_history_class.tuning_by_history_break()  # TuneされたTPやLC.finalized_orderChangeを取得する
    tp_range = tuned_data['tuned_tp_range']
    lc_change_type = tuned_data['tuned_lc_change_type']
    print("TP設定", tp_range, "lcChange設定", lc_change_type)

    target_price = target_peak['peak'] + (peaks[0]['direction'] * 0.001)
    lc_price = OCreate.cal_lc_price_from_line_and_margin(peaks[1]['latest_wick_peak_price'], 0.03,
                                                         peaks[0]['direction'])
    gap = abs(lc_price - target_price)
    re_lc_range = gene.cal_at_most(0.09, gap)
    print("gap確認", gap, "target_price:", target_price, "deci_price:",
          peaks_class.df_r_original.iloc[1]['close'])
    print("Peak2のGap確認", peaks[0]['gap'], peaks[0]['latest_time_jp'])
    base_order_dic = {
        "target": target_price,
        "type": "LIMIT",
        "expected_direction": peaks[0]['direction'],
        # "tp": tp_range,  # 短期では0.15でもOK.ただ長期だと、マイナスの平均が0.114のためマイナスの数が多くなる
        # "lc": lc_price,  # 0.06,
        "tp": peaks_class.cal_move_size_lc(1.5),  #peaks[0]['gap'] * 0.8,  #0.03,
        "lc": peaks_class.cal_move_size_lc(0.6),
        # "lc": peaks_class.ave_move_for_lc,
        # "lc": 0.4,
        'priority': 4,
        "decision_time": peaks_class.df_r_original.iloc[0]['time_jp'],
        "decision_price": peaks_class.df_r_original.iloc[1]['close'],
        "order_timeout_min": 90,
        "lc_change_type": 1,
        "name": "■PredictLineOrder"
    }
    base_order_class = OCreate.OrderCreateClass(base_order_dic)  # オーダー生成
    # gene.print_json(base_order_class.finalized_order_without_lc_change)  # 表示

    # オーダーの修正と、場合によって追加オーダー設定
    lc_max = 0.15
    lc_change_after = 0.075
    if base_order_class.finalized_order['lc_range'] >= lc_max:
        # LCレンジを計算してLCが大きすぎた場合、オーダー修正（LC短縮）
        print("LCが大きいため再オーダー設定")
        base_order_dic['lc'] = lc_change_after
        base_order_dic['name'] = base_order_dic['name'] + "_LC大で修正_"
        base_order_class = OCreate.OrderCreateClass(base_order_dic)  # オーダー生成（というか作り直し）
    else:
        base_order_class = OCreate.OrderCreateClass(base_order_dic)

    return base_order_class.finalized_order