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

def cal_predict_turn(peaks_class):
    """
    args[0]は必ずpeaks_classであること。
    args[1]は、本番の場合、過去の決済履歴のマイナスの大きさでTPが変わるかを検討したいため、オーダークラスを受け取る
    
    直近のピーク（latest_peakはこれから伸びるPeakなので、直前のpeakは[1]の物を示す
    """
    # ■基本情報の取得
    print("★★PREDICT　TURN")
    take_position = False
    s = "    "

    # ■Peaks等、大事な変数の設定
    target_num = 2  # 以下のループで「自分以外」を定義するため、変数に入れておく(同一方向の配列に対して）
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
    if peaks[0]['count'] == 3 and peaks[1]['count'] >= 3:  # [0]countは２では微妙（２はBreakのケースが多く見える）ので３．
        print("　カウント数は合格", peaks[0]['count'], "が3で、", peaks[1]['count'], "が３以上が対象")
    else:
        print("  山を形成するカウント不足", peaks[0]['count'], "が２で、", peaks[1]['count'], "が３以上が対象")
        return default_return_item
    # 変動が少ないところはスキップ
    if target_peak['gap'] <= 0.06:
        print("targetのGapが少なすぎる", target_peak['gap'], target_peak['latest_time_jp'])
        return default_return_item
    # ターゲットのピークが弱い
    if target_peak['peak_strength'] < 4:
        print("　ターゲットのピークの強さが弱い")
        return default_return_item
    # 抵抗線を突破してしまっている場合
    if target_peak['direction'] == 1:
        if peaks[0]['latest_price'] >= target_price:
            # 既に抵抗線を突破している場合
            print(" 既に抵抗線を上に突破しており、不可.現在価格:", peaks[0]['latest_price'], "線", target_price)
            return  default_return_item
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
        "lc": peaks_class.ave_move_for_lc,
        'priority': 4,
        "decision_time": peaks_class.df_r_original.iloc[0]['time_jp'],
        "decision_price": peaks_class.df_r_original.iloc[1]['close'],
        "order_timeout_min": 40,
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