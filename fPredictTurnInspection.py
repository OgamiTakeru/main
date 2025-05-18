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


def judge_flag_figure_new(peaks, same_price_list, direction):
    """
    フラッグ形状を算出する
    ・同一価格が発見された、時系列的にひとつ前の逆ピーク（ストレングス5以上）のものまで
    ・逆ピークまでの落差が、最終(最古）の同一価格の次の逆ピークまでの落差の2倍(1.5?)まで
    """
    print(" フラッグ形状算出用 関数")
    # 色々な初期値
    search_direction = direction
    target_peaks = []
    peaks = peaks[1:]  # [0]は自分自身のため、排除したほうがよい気がする。

    # 対象となるPeaks(傾きを求める側)を算出
    oldest_time_str = same_price_list[-1]['item']['latest_time_jp']
    oldest_time = datetime.strptime(oldest_time_str, "%Y/%m/%d %H:%M:%S")
    for i, item in enumerate(peaks):
        if datetime.strptime(item['latest_time_jp'], "%Y/%m/%d %H:%M:%S") > oldest_time:
            # 最古の同一価格よりも、新しい時間のピークの場合（無条件で追加されるもの）
            target_peaks.append(item)
        else:
            # 最古の価格を越えている場合
            target_peaks.append(item)
            if item['peak_strength'] >= 5 and item['direction'] == search_direction:
                # search_directionのpeak_strengthが5以上のものを発見した場合、終了
                break

    # print("フラッグ検証をする範囲")
    # gene.print_arr(target_peaks)

    print("フラッグ検証をする範囲の中で、傾きを求めたい側のPeaks")
    opposite_peaks = [item for item in target_peaks if item["direction"] == search_direction]
    gene.print_arr(opposite_peaks)

    # 近似線を算出する
    # 時間をdatetimeに変換
    times = [datetime.strptime(d['latest_time_jp'], '%Y/%m/%d %H:%M:%S') for d in opposite_peaks]
    # 時間を数値（秒）に変換（回帰のため）
    time_seconds = [(t - times[0]).total_seconds() for t in times]
    # peak値
    peaks = [d['peak'] for d in opposite_peaks]
    # 近似直線（1次関数）を計算
    coefficients = np.polyfit(time_seconds, peaks, 1)  # 1次関数
    poly = np.poly1d(coefficients)
    trend = poly(time_seconds)
    # 変動幅を抑える
    temp_peaks = [d['peak'] for d in opposite_peaks]
    max_peak = max(temp_peaks)
    min_peak = min(temp_peaks)
    allowed_gap = (max_peak - min_peak) * 0.4  # ★★変動幅の20パーセント（惺窩君は18.4くらい）
    print("変動幅の検討　最大", max_peak, min_peak, allowed_gap)
    # [検出１]近似線を下回るもの（上回るもの）データを算出
    below_trend_data = [
        opposite_peaks[i]
        for i in range(len(opposite_peaks))
        if peaks[i] < trend[i]
    ]
    #     結果表示
    print("近似線より下にあるデータ:")
    for d in below_trend_data:
        print(d)
    # [検出２]近似線に対し、下、かつ遠いと判断されるデータを抽出
    border_range = allowed_gap
    below_trend_within_5 = [
        opposite_peaks[i]
        for i in range(len(opposite_peaks))
        if 0 < (trend[i] - peaks[i]) <= border_range  # 下にある　かつ　N以上離れている
        # if 0 > (trend[i] - peaks[i]) >= border_range  # 上にある　かつ　N以上離れている
        # if (trend[i] - peaks[i]) <= border_range  # N以内
    ]
    # 結果表示
    print("近似線より下にあり、差が指定以上のデータ:")
    for d in below_trend_within_5:
        print(d)

    # [検出3]近似線に対し、遠いと判断されるデータを抽出
    border_range = allowed_gap
    within_5 = [
        opposite_peaks[i]
        for i in range(len(opposite_peaks))
        if abs(trend[i] - peaks[i]) <= border_range
    ]
    # 結果表示
    print("近似線との誤差が5以内のデータ::")
    for d in within_5:
        print(d)
    ratio_near = len(within_5)/len(opposite_peaks)
    print("近い物の割合", len(within_5)/len(opposite_peaks))

    # [検証４]傾きを求める
    times = [datetime.strptime(d['latest_time_jp'], '%Y/%m/%d %H:%M:%S') for d in opposite_peaks]
    time_minutes = [(t - times[0]).total_seconds() / 60 for t in times]
    peaks = [d['peak'] for d in opposite_peaks]
    # 一次近似
    coefficients = np.polyfit(time_minutes, peaks, 1)  # 単位：分
    slope = coefficients[0]
    intercept = coefficients[1]
    print(f"傾き（1分あたり）: {slope:.4f}")
    print(f"切片: {intercept:.4f}")

    # 判定
    is_flag = False
    if (search_direction == -1 and slope >=0 ) or (search_direction == 1 and slope <= 0):
        if ratio_near >= 0.7 and len(opposite_peaks) >= 4:
            print("  ▲フラッグ認定 近い割合:", ratio_near, "反対個数", len(opposite_peaks))
            is_flag = True
        else:
            print("  ▲フラッグnot認定 (近似割合が0.7より下⇒", ratio_near, "反対個数が4個以上⇒", len(opposite_peaks))
    else:
        print(" 　　▲近似線の傾きが異なる 探索ピーク方向：", search_direction, slope)

    # 参考　差の一覧を表示
    # 差が5以内のデータで、プラスかマイナスの差を表示
    within_5_with_diff = [
        (opposite_peaks[i], trend[i] - peaks[i])  # 差を計算
        for i in range(len(opposite_peaks))
        if abs(trend[i] - peaks[i]) <= 5
    ]
    # 結果表示（差も表示）
    print("近似線との誤差が5以内のデータ（差も表示）:　目標の設定値", allowed_gap)
    for d, diff in within_5_with_diff:
        print(f"日時: {d['latest_time_jp']}, peak: {d['peak']}, 差: {diff:.2f}")

    # グラフ描画
    # plt.figure(figsize=(10, 5))
    # plt.plot(times, peaks, 'o-', label='peak values')
    # plt.plot(times, trend, 'r--', label='approx. line')
    # plt.xlabel('Time')
    # plt.ylabel('Peak')
    # plt.title('Peak Trend Over Time')
    # plt.legend()
    # plt.xticks(rotation=45)
    # plt.tight_layout()
    # plt.show()

    return {"is_flag": is_flag}


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