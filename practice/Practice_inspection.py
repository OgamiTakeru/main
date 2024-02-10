from plotly.subplots import make_subplots
import plotly.graph_objects as go
import pandas as pd
import os
from scipy.signal import argrelmin, argrelmax
from numpy import linalg as LA
import numpy as np
import datetime
import math
import matplotlib.pyplot as plt

import programs.tokens as tk  # Token等、各自環境の設定ファイル（git対象外）
import programs.classOanda as oanda_class
import programs.fTurnInspection as f  # とりあえずの関数集


def input_base_data(ans_dic):
    latest_turn = ans_dic['figure_turn_result']['latest_turn_dic']
    figure_latest = ans_dic['figure_turn_result']['latest_turn_dic']['latest_ans']
    figure_oldest = ans_dic['figure_turn_result']['latest_turn_dic']['oldest_ans']
    line_base = ans_dic['figure_turn_result']['order_dic']['target_price']  # 基準となる価格（=直近のクローズ価格）
    expect_direction = ans_dic['figure_turn_result']['order_dic']['direction']
    macd = ans_dic['macd_result']
    # ★★★★検証
    each_res_dic = {
        "order_entry_time": figure_latest['data'].iloc[0]["time_jp"],
        "turn_ans": ans_dic['figure_turn_result']['result_dic']['turn_ans'],  # ★変更時注意
        "oldest_range": figure_oldest['gap'],
        "oldest_count": figure_oldest['count'],
        "oldest_oldest": figure_oldest['oldest_price'],
        "oldest_latest": figure_oldest['latest_price'],
        "oldest_oldest_image_price": figure_oldest['oldest_image_price'],
        "oldest_latest_image_price": figure_oldest['latest_image_price'],
        "oldest_body": figure_oldest['support_info']["body_ave"],
        "oldest_move": figure_oldest['support_info']["move_abs"],
        "latest_range": figure_latest['gap'],
        "latest_count": figure_latest['count'],
        "latest_oldest": figure_latest['oldest_price'],
        "latest_latest": figure_latest['latest_price'],
        "latest_oldest_image_price": figure_latest['oldest_image_price'],
        "latest_latest_image_price": figure_latest['latest_image_price'],
        "latest_body": figure_latest['support_info']["body_ave"],
        "latest_move": figure_latest['support_info']["move_abs"],
        "direction_latest": figure_latest['direction'],
        "return_ratio": latest_turn['return_ratio'],  # ★変更時注意
        "pattern_num": figure_latest['support_info']["pattern_num"],
        "pattern_num_abs": abs(figure_latest['support_info']["pattern_num"]),
        "pattern": figure_latest['support_info']["pattern_comment"],
        "range_judge": figure_latest['support_info']["range_expected"],
        "macd": macd['macd'],
        "macd_mae": macd['cross_mae'],
        "macd_cross": macd['cross'],
        "macd_cross_latest": macd['latest_cross'],
        "macd_cross_time": macd['latest_cross_time'],
        "macd_range": macd['range'],
        "macd_range_counter": macd['range_counter']
    }
    # 一部の情報を上書きして修正する
    if figure_latest['support_info']["range_expected"] == 1:  # 順思想に行く場合
        if figure_oldest['gap'] > 0.15:  # 15pips以上の変動後の場合
            each_res_dic['range_judge'] = 0
            each_res_dic['range_judje_re'] = "Change0"
        else:
            each_res_dic['range_judge'] = 1
            each_res_dic['range_judje_re'] = ""
    else:  # Trend予想＝latestの方向に行く
        each_res_dic['range_judge'] = 0
        each_res_dic['range_judje_re'] = ""

    print(figure_latest['data'].iloc[0]["time_jp"])
    print(figure_latest['data'])

    return each_res_dic


def get_inspection_data(time_base):
    """
    timebaseから始まる５Sのデータを取得し、データを返却する。キャッシュの利用も行う
    :param time_base:
    :return:
    """
    # print(" entry(検証開始)",  dr.iloc[0]['time_jp'], d.iloc[-1]['time_jp'])
    # mid_df.at[index_graph, "entry42"] = dr.iloc[0]['open']  # グラフ用データ追加
    folder_path_cache = tk.inspection_data_cache_folder_path  # キャッシュ保存用
    detail_range_sec = 3600  # ★　N行×5S の検証を行う。 この数字は、検証をしたい分数×60
    latest_row_time_dt = f.str_to_time(time_base[:26])  # 時刻を変換する
    detail_from_time_dt = latest_row_time_dt + datetime.timedelta(minutes=0)  # 開始時刻は分単位で調整可
    detail_from_time_iso = str(detail_from_time_dt.isoformat()) + ".000000000Z"  # API形式の時刻へ（ISOで文字型。.0z付き）
    # print(" ききき")
    # print(latest_row_time_dt, detail_from_time_dt, detail_from_time_iso)
    detail_from_time_str = str(detail_from_time_dt)  # キャッシュを考慮
    detail_from_time_str = detail_from_time_str.replace('-', '')  # キャッシュファイル名の為、記号を削除
    detail_from_time_str = detail_from_time_str.replace(' ', '')  # キャッシュファイル名の為、記号を削除
    detail_from_time_str = detail_from_time_str.replace(':', '')  # キャッシュファイル名の為、記号を削除
    file_name = folder_path_cache + detail_from_time_str + '.csv'
    print(detail_from_time_str)

    # ★★検証データの取得(キャッシュ　または　APIで取りに行く）　os.path.isfile(file_path)
    if os.path.isfile(file_name):
        # キャッシュファイルがある場合、そっちを優先する
        print(" キャッシュあり！！！！！！！")
        detail_df = pd.read_csv(file_name, sep=",", encoding="utf-8")
    else:
        # キャッシュがない場合はAPIで取得する
        print("  キャッシュ無しの為取得")
        detail_df = oa.InstrumentsCandles_exe("USD_JPY",
                                              {"granularity": 'S5', "count": int(detail_range_sec / 5),
                                               "from": detail_from_time_iso})  # ★★検証範囲の取得★★
        detail_df.drop(columns=['time'], inplace=True)
        detail_df.to_csv(file_name, index=False, encoding="utf-8")  # キャッシュ保存

    return detail_df


def judge_entry(ans_dic):
    """
    リアルなトレード（マージンを含めたエントリー価格で取得⇒解消まで実施
    :param detail_df:
    :param ans_dic:
    :param na:
    :return:
    """
    order_temp = {}  # ちょっと調整用（分岐する用）
    # ■実際の動きをそのままコピペ
    ans = ans_dic['judgment']
    turn_ans_temp = ans_dic['figure_turn_result']['result_dic']['turn_ans']  # 直近のターンがあるかどうか（連続性の考慮無し）
    turn_ans = ans_dic['figure_turn_result']['result_dic']['total_ans']  # 連続性を考慮したうえでのターン判定
    turn_target_price = ans_dic['figure_turn_result']['order_dic']['target_price']
    turn_expect_direction = ans_dic['figure_turn_result']['order_dic']['direction']
    macd_ans = ans_dic['macd_result']['cross']
    latest3_ans = ans_dic['latest3_figure_result']['result']
    latest3_target_price = ans_dic['latest3_figure_result']['order_dic']['target_price']
    latest3_expect_direction = ans_dic['latest3_figure_result']['order_dic']['direction']
    one_candle_move_mean = ans_dic['figure_turn_result']['latest_turn_dic']['oldest_ans']['move_abs']
    one_candle_body_mean = ans_dic['figure_turn_result']['latest_turn_dic']['oldest_ans']['body_ave']
    oldest_gap = ans_dic['figure_turn_result']['latest_turn_dic']['oldest_ans']['gap']

    if turn_ans_temp == 1:  # ターンが確認された場合（最優先）
        print("  ターンを確認")
        if turn_ans == 1:  # そのさらに直前のターンが発生がある場合
            print("   その直前にもターンを確認⇒オーダー無し")
        else:
            print("   ★オーダー発行")
            oa.OrderCancel_All_exe()  # 露払い
            oa.TradeAllClose_exe()  # 露払い
            order_temp = {
                "line_base": turn_target_price,
                "expect_dir": turn_expect_direction,
                "lc": 0.045,  # 少し狭い目のLC
                "tp": 0.09,
                "margin": 0.02,
                "memo": "ターン起点",
                "kinds": 1
            }
    elif latest3_ans == 1:  # ターン未遂が確認された場合（早い場合）
        print("  ターン未遂を確認　★オーダー発行")
        order_temp = {
            "line_base": latest3_target_price,
            "expect_dir": latest3_expect_direction,
            "lc": 0.02,  # 非常に狭いLC
            "tp": 0.09,
            "margin": 0.04,
            "memo": "ターン未遂起点",
            "kinds": 2,
        }

    # ■オーダーセッティングセクション(マージンの考慮）
    if "memo" in order_temp:  # 成立して、情報が付与された場合
        direction = order_temp['expect_dir']
        base_line = order_temp['line_base']
        margin = order_temp['margin']
        if direction == 1:  # 買いの場合
            base_line = base_line + margin
        else:  # 売りの場合
            base_line = base_line - margin
        ans = {
            "judgment": 1,
            "base_line_with_margin": base_line,
            "direction": direction,
            "kinds": order_temp['kinds'],
            "memo": order_temp['memo'],
            "order_info": order_temp, # 以降order_info['line_base']=オリジナルのLineBase、order_info['']
        }
    else:
        # 成立してない場合
        ans = {
            "judgment": 0,
        }

    return ans


# def order_future_inspection2(detail_df, ans_dic, na):
#     """
#     与えられた５秒足のデータから、データを取得する
#     :param detail_df:test
#     :param ans_dic 情報
#     :return:
#     """
#     # 変数の変換
#     latest_ans = ans_dic['figure_turn_result']['latest_turn_dic']['latest_ans']
#     oldest_ans = ans_dic['figure_turn_result']['latest_turn_dic']['oldest_ans']
#     # figure_union = ans_dic['figure_result']
#     macd_ans = ans_dic['macd_result']
#
#     res_dic = {}  # 初期化
#     print(detail_df.head(2))  # 検証データ取得！
#     print(detail_df.tail(2))  # 検証データ取得！
#     print(" [検証時刻:", detail_df.iloc[0]['time_jp'], "終了", detail_df.iloc[-1]["time_jp"])
#     res_dic['inspect_fin_time' + na] = detail_df.iloc[-1]["time_jp"]
#     entry_price = detail_df.iloc[0]["open"]
#     res_dic['entry_price' + na] = entry_price
#
#     # 検証を開始(検証データの値を収集）
#     high_ins = detail_df['high'].max()  # 最高値関係を求める
#     max_df = detail_df[detail_df['high'] == high_ins]  # max_dfは一時的な利用
#     res_dic['high_price' + na] = high_ins
#     res_dic['high_time' + na] = max_df.iloc[0]['time_jp']
#
#     low_ins = detail_df['low'].min()  # 最低価格関係を求める
#     min_df = detail_df[detail_df['low'] == low_ins]  # min_dfは一時的な利用
#     res_dic['low_price' + na] = low_ins
#     res_dic['low_time' + na] = min_df.iloc[0]['time_jp']
#
#     res_dic['latest_latest_image_price' + na] = latest_ans['latest_image_price']
#
#     if latest_ans['direction'] == 1:  # 直近が上り（谷形状の場合）
#         # 上方向に折り返し（最高値を求め、そことの距離を求める）
#         res_dic['minus' + na] = high_ins - latest_ans['latest_image_price']
#         res_dic['plus' + na] = latest_ans['latest_image_price'] - low_ins
#     else:  # 直近が下がり（山形状の場合）
#         # 下方向に折り返し（最低値を求める）
#         res_dic['minus' + na] = latest_ans['latest_image_price'] - low_ins
#         res_dic['plus' + na] = high_ins - latest_ans['latest_image_price']
#
#     # どっち（HighかLow）のピークが早かったかを算出する
#     high_time_datetime = f.str_to_time(max_df.iloc[0]['time_jp'])  # 時間形式に直す
#     low_time_datetime = f.str_to_time(min_df.iloc[0]['time_jp'])  # 時間形式に直す
#     if high_time_datetime < low_time_datetime:
#         #  maxの方が最初に到達
#         res_dic['first_arrive' + na] = "high_price"
#     else:
#         #  minの方が最初に到達
#         res_dic['first_arrive' + na] = "low_price"
#
#     # ★理想として、順思想と逆思想　どっちだったら勝てるかのを推測する
#     lc = 0.05
#     tp = 0.09
#
#     # LCの価格とTPの価格を求める
#     # position_direction = latest_ans['direction'] * -1
#     position_direction = macd_ans['cross']
#     entry_price = detail_df.iloc[0]["open"]
#     if position_direction == 1:  # 買いポジションの場合
#         tp_price = entry_price + tp
#         lc_price = entry_price - lc
#     else:  # 売りポジの場合
#         tp_price = entry_price - tp
#         lc_price = entry_price + lc
#
#     # LCに達成するタイミングを算出する
#     tp_flag = 0
#     lc_flag = 0
#     tp_timing = lc_timing = '2026/05/22 10:15:00'  # とりあえず先の日付
#     for index, item in detail_df.iterrows():  #
#         if item['low'] < tp_price < item['high']:
#             # tp_priceを含む場合
#             if tp_flag == 0:
#                 tp_timing = item['time_jp']
#                 tp_flag = 1
#
#         if item['low'] < lc_price < item['high']:
#             # lc_price を含み場合
#             if lc_flag == 0:
#                 lc_timing = item['time_jp']
#                 lc_flag = 1
#
#         if tp_flag == 1 and lc_flag == 1:
#             # 両方見つかっている場合、その時点で終了する
#             break
#
#     if tp_flag == 0 and lc_flag==0:
#         # とっちも満たさない場合
#         ans_timing = 0
#         ans = 0
#         tp_timing = lc_timing = 0
#         ans_pips = 0
#     elif tp_flag == 1 and lc_flag==1:
#         # 両方満たす場合
#         if f.str_to_time(tp_timing) < f.str_to_time(lc_timing):
#             # TPの方が早い
#             ans = 1  # TP
#             ans_timing = tp_timing
#             ans_pips = tp
#         else:
#             # LCの方が早い
#             ans = -1  # LC
#             ans_timing = lc_timing
#             ans_pips = lc
#     else:
#         if tp_flag == 1:  # TPの達成の場合
#             ans = 1  # TP
#             ans_timing = tp_timing
#             lc_timing = 0  # LCには入っていない
#             ans_pips = tp
#         else:
#             ans = -1  # LC
#             ans_timing = lc_timing
#             tp_timing = 0  # TPには入っていない
#             ans_pips = lc
#     res_dic['position_direction'] = position_direction
#     res_dic['tp_time'] = tp_timing
#     res_dic['tp_price'] = tp_price
#     res_dic['lc_time'] = lc_timing
#     res_dic['lc_price'] = lc_price
#     res_dic['ans'] = ans
#     res_dic['ans_pips'] = ans_pips
#     res_dic['ans_timing'] = ans_timing
#
#     # oldestRangeをそろえると、どうなるか
#     ratio_base = 0.01
#     temp_minus_ratio = round((res_dic['minus' + na] * ratio_base) / oldest_ans['gap'], 3)
#     temp_plus_ratio = round((res_dic['plus' + na] * ratio_base) / oldest_ans['gap'], 3)
#     res_dic['minus_ratio' + na] = temp_minus_ratio
#     res_dic['plus_ratio' + na] = temp_plus_ratio
#
#     return res_dic


def order_future_inspection(detail_df, ans_dic):
    # 検証結果格納用のDicや、検証に必要な変数を準備する
    res_dic = {}  # 初期化
    position = 0
    result = 0

    # 検証用のDFを表示する
    print(detail_df.head(2))  # 検証データ取得！
    print(detail_df.tail(2))  # 検証データ取得！
    print(" [検証時刻:", detail_df.iloc[0]['time_jp'], "終了", detail_df.iloc[-1]["time_jp"])

    # 検証に必要なデータを短い変数に入れておく
    original_base_line = ans_dic['order_info']['line_base']
    p = ans_dic['base_line_with_margin']
    d = ans_dic['direction']
    k = ans_dic['kinds']
    lc_range = ans_dic['order_info']['lc']
    tp_range = ans_dic['order_info']['tp']
    if d == 1:  # 買い方向の場合
        tp = p + tp_range
        lc = p - lc_range
    else:
        tp = p - tp_range
        lc = p + lc_range
    res_dic['entry_price_default'] = p
    res_dic['tp_default'] = tp
    res_dic['lc_default'] = lc
    res_dic['direction_default'] = d
    res_dic['kind_default'] = k

    # 【検証開始】ポジションを持っていない場合、規定価格でポジションを取得する
    for index, item in detail_df.iterrows():
        # Positionを持っていない場合、取得する
        if position == 0:
            if item['low'] < p < item['high']:  # ★ポジションを取得する
                position = 1  # ポジションフラグを立てる
                res_dic['entry_time_default'] = item['time_jp']  # 取得時間を取得
                # 即時決済もありうるため、ここでもLCとTPを確かめる
                if item['low'] < lc < item['high']:  # ★LC価格に引っかかる場合
                    res_dic['close_time_default'] = item['time_jp']  # 取得時間を取得
                    result = -1
                    break
                elif item['low'] < tp < item['high']:  # ★TP価格に引っかかる場合
                    res_dic['close_time_default'] = item['time_jp']  # 取得時間を取得
                    result = 1
                    break
            else:
                res_dic['entry_time_default'] = 0  # 何もない時は０を残すため、０を入れておく
        # Positionを持っていない場合、
        else:
            if item['low'] < lc < item['high']:  # ★LC価格に引っかかる場合
                res_dic['close_time_default'] = item['time_jp']  # 取得時間を取得
                result = -1
                break
            elif item['low'] < tp < item['high']:  # ★TP価格に引っかかる場合
                res_dic['close_time_default'] = item['time_jp']  # 取得時間を取得
                result = 1
                break
    res_dic['result_default'] = result
    return res_dic


def order_future_inspection_loop(detail_df, ans_dic):
    # 検証結果格納用のDicや、検証に必要な変数を準備する
    res_dic = {}  # 初期化
    position = 0
    p_result_arr = []
    l_result_arr = []
    info_arr = []
    result_max = 0
    max_search = 0.10

    # エントリーデータ
    res_dic['decision_time'] =  detail_df.iloc[0]['time_jp']
    line_base_origin = ans_dic['order_info']['line_base']  # オリジナルの価格
    d = ans_dic['direction']
    m_original = ans_dic['order_info']['margin']
    lc_range_original = ans_dic['order_info']['lc']
    tp_range_original = ans_dic['order_info']['tp']
    # エントリーデータの保存

    # 各条件をを変動していく
    each_condition_result_dic_arr = []
    for m in range(5):  # marginを増やしていく
        # 検証に必要なデータを短い変数に入れておく
        margin_yen = m/100 + 0.01  # 1pipsずつ増やしていく
        # c_name = c_name + "M" + str(m)

        for lc_loop in range(10):
            lc_yen = lc_loop/100 + 0.02  # 1pips増やしていく
            # c_name = c_name + "TP" + str(tp_loop)

            for tp_loop in range(10):
                tp_yen = tp_loop / 100 + 0.02  # 1pips増やしていく
                # 条件の算出
                if d == 1:  # 買い方向の場合
                    p = round(line_base_origin + margin_yen, 3)  # ポジションを取りにくい方向に移す
                    tp_price = p + tp_yen
                    lc_price = p - lc_yen
                else:
                    p = round(line_base_origin - margin_yen, 3)  # ポジションを取りにくい方向に移す
                    tp_price = p - tp_yen
                    lc_price = p + lc_yen

                # 【検証開始】ポジション取得から解消まで
                result = 0  # 結果の初期化
                counter = 0
                entry_time = 0
                close_time = 0
                for index, item in detail_df.iterrows():
                    # Positionを持っていない場合、取得する
                    if position == 0:
                        if item['low'] < p < item['high']:  # ★ポジションを取得する
                            # print("★★ポジション取得", item['time_jp'])
                            position = 1  # ポジションフラグを立てる（ポジション取得）
                            entry_time = item['time_jp']  # 取得時間を取得
                            # 即時決済もありうるため、ここでもLCとTPを確かめる
                            if item['low'] < lc_price < item['high']:  # ★LC価格に引っかかる場合
                                # print("★ポジション解除　即", item['time_jp'])
                                close_time = item['time_jp']  # 取得時間を取得
                                result = -1
                            elif item['low'] < tp_price < item['high']:  # ★TP価格に引っかかる場合
                                # print("  ★ポジション解除　即", item['time_jp'])
                                close_time = item['time_jp']  # 取得時間を取得
                                result = 1
                        else:
                            # print("★★ポジションとらず", item['low'], p, item['high'])
                            pass
                    # Positionを持っている場合クローズの処理
                    else:
                        if item['low'] < lc_price < item['high']:  # ★LC価格に引っかかる場合
                            # print("★ポジション解除", item['time_jp'])
                            close_time = item['time_jp']  # 取得時間を取得
                            result = -1
                        elif item['low'] < tp_price < item['high']:  # ★TP価格に引っかかる場合
                            # print("★ポジション解除", item['time_jp'])
                            close_time = item['time_jp']  # 取得時間を取得
                            result = 1
                        else:
                            # print(" ★★ポジ解消なし")
                            pass

                    # Result完了時はループ抜け（＝終了）、それ以外はループ継続（＋カウンター増加）
                    if result != 0:
                        position = 0  # ポジションフラグ解消
                        break
                    else:
                        counter = counter + 1
                # 結果を格納する（各パラメータの組み合わせ事⇒ループの一番深いところ（データ検証ループは除く）でListに追加していく。
                each_condition_result_dic = {
                    "result": result,
                    "tp_yen": round(tp_yen, 3),
                    "lc_yen": round(lc_yen, 3),
                    "margin": round(margin_yen, 3),
                    "entry_count": entry_time,
                    "close_count": close_time,
                    "tp_price": round(tp_price, 3),
                    "lc_price": round(lc_price, 3),
                    "p": line_base_origin,
                    # "p_margin": round(p, 3)
                }
                each_condition_result_dic_arr.append(each_condition_result_dic)

    # for i in range(len(each_condition_result_dic_arr)):
    #     print(each_condition_result_dic_arr[i])

    # 最終的な欲しい情報を記入する
    # TP版
    tp_list = list(filter(lambda item: item['result'] == 1, each_condition_result_dic_arr))
    if len(tp_list) >= 1:
        tp_sort = sorted(tp_list, key=lambda x: x['tp_yen'], reverse=True)  # TP値で降順
        tp_max = tp_sort[0]  # TPが一番大きい時の値を取得する
        res_dic['maxTP_res'] = tp_max['result']
        res_dic['maxTP_tp'] = tp_max['tp_yen']
        res_dic['maxTP_lc'] = tp_max['lc_yen']
        res_dic['maxTP_mar'] = tp_max['margin']
        res_dic['maxTP_entry_count'] = tp_max['entry_count']
        res_dic['maxTP_close_count'] = tp_max['close_count']
    else:
        res_dic['maxTP_tp'] = 0
        res_dic['maxTP_lc'] = 0
        res_dic['maxTP_mar'] = 0
        res_dic['maxTP_entry_count'] = 0
        res_dic['maxTP_close_count'] = 0
    #
    lc_list = list(filter(lambda item: item['result'] == -1, each_condition_result_dic_arr))
    if len(lc_list) >= 1:
        lc_sort = sorted(lc_list, key=lambda x: x['lc_yen'], reverse=True)  # TP値で降順
        lc_max = lc_sort[0]  # TPが一番大きい時の値を取得する
        res_dic['maxLC_res'] = lc_max['result']
        res_dic['maxLC_tp'] = lc_max['tp_yen']
        res_dic['maxLC_lc'] = lc_max['lc_yen']
        res_dic['maxLC_mar'] = lc_max['margin']
        res_dic['maxLC_entry_count'] = lc_max['entry_count']
        res_dic['maxLC_close_count'] = lc_max['close_count']
    else:
        res_dic['maxLC_tp'] = 0
        res_dic['maxLC_lc'] = 0
        res_dic['maxLC_mar'] = 0
        res_dic['maxLC_entry_count'] = 0
        res_dic['maxLC_close_count'] = 0

    # 重くなるかもしれないが、全データ（Result＝０以外）を入れておく
    # res_dic['data_TP'] = tp_list
    # res_dic['data_LC'] = lc_list

    return res_dic


def main_inspection():
    # データの取得 and peak情報付加　＋　グラフ作成
    mid_df = oa.InstrumentsCandles_multi_exe("USD_JPY", {"granularity": gl['candle_unit'], "count": gl['candle_num']}, gl['num'])
    # データの取得２
    # jp_time = datetime.datetime(2023, 6, 5, 11, 5, 00)
    # euro_time_datetime = jp_time - datetime.timedelta(hours=9)
    # euro_time_datetime_iso = str(euro_time_datetime.isoformat()) + ".000000000Z"  # ISOで文字型。.0z付き）
    # param = {"granularity": "M5", "count": 50, "to": euro_time_datetime_iso}
    # mid_df = oa.InstrumentsCandles_exe("USD_JPY", param)
    # mid_df.to_csv('C:/Users/taker/Desktop/Peak_TEST_DATA.csv', index=False, encoding="utf-8")



    # 調査を行う
    # ①調査に利用する変数を定義
    count_for_view = 0
    res_dic_arr = []
    inspection_range = 40  # 一回にN行分を取得して検討する (mid_dfは古いデータが上に存在。）
    for i in range(len(mid_df)):
        d = mid_df[len(mid_df)-inspection_range-i: len(mid_df)-i]  # 旧側(index0）を固定。新側をインクリメントしていきたい。最大３０行
        # 対象の範囲を調査する (実際ではdが取得された範囲）
        if len(d) >= inspection_range:
            print("★★★★★★★★★★★★★★★★★★★★", len(mid_df), i)
            count_for_view = count_for_view + 1
            index_graph = d.index.values[-1]  # インデックスを確認(列の仕分けに利用する）
            dr = d.sort_index(ascending=False)  # ★dが毎回の取得と同義⇒それを逆(最新が上)にする（逆を意味するrをつける）

            # ■直近のデータから、分析を実施。エントリの可否とエントリー価格と方向を取得する。
            inspection_condition = {
                "now_price": dr.iloc[0]['open'],  # 現在価格を渡す
                "data_r": dr,  # 時刻降順（直近が上）のデータを渡す
                "figure": {"ignore": 1, "latest_n": 2, "oldest_n": 30},
                "macd": {"short": 20, "long": 30},
                "save": False,  # データをCSVで保存するか（検証ではFalse推奨。Trueの場合は以下は必須）
                "time_str": "",  # 記録用の現在時刻
            }
            ans_dic = f.inspection_candle(inspection_condition)  # 状況を検査する（買いフラグの確認）
            entry_jd = judge_entry(ans_dic)

            if entry_jd['judgment'] != 0:
                # タイミング発生★★★
                print("★★★★")
                # ■基本的なデータを取得する（Dicに格納する）
                each_res_dic = input_base_data(ans_dic)  # 基本的な情報を入れる

                # ■①　検証データの取得や、グラフ化や出力を先に行う
                detail_df = get_inspection_data(dr.iloc[0]['time'])

                # 20分程度で検証結果を取得(default)
                short_detail_df = detail_df[0:]  # 20分の場合、20分×60秒÷5 = 240
                indpection_dic_ans = order_future_inspection(short_detail_df, entry_jd)
                each_res_dic.update(indpection_dic_ans)  # 結果の辞書同士を結合(個別同士）

                # ループ分を付与する
                short_dic_ans = order_future_inspection_loop(short_detail_df, entry_jd)
                each_res_dic.update(short_dic_ans)  # 結果の辞書同士を結合(個別同士）

                # 最後に全体のに結合
                res_dic_arr.append(each_res_dic)  # 全体に結合

    # 解析用結果の表示
    print(res_dic_arr)
    res_dic_df = pd.DataFrame(res_dic_arr)
    try:
        res_dic_df.to_csv(tk.folder_path + 'inspection.csv', index=False, encoding="utf-8")
    except:
        res_dic_df.to_csv(tk.folder_path + 'inspection_sub.csv', index=False, encoding="utf-8")

gl = {
    # 5分足対象
    "high_v": "high",  # "inner_high"
    "low_v": "low",  # "inner_low"５
    "p_order": 2,  # ピーク検出の幅  1分足だと４くらい？？
    "tiltgap_horizon": 0.0041,  # peak線とvalley線の差が、左記数字以下なら平行と判断。この数値以下なら平行。
    "tiltgap_pending": 0.011,  # peak線とvalley線の差が、左記数値以下なら平行以上-急なクロス以前と判断。それ以上は強いクロスとみなす
    "tilt_horizon": 0.0029,  # 単品の傾きが左記以下の場合、水平と判断。　　0.005だと少し傾き気味。。
    "tilt_pending": 0.03,  # 単品の傾きが左記以下の場合、様子見の傾きと判断。これ以上で急な傾きと判断。
    "candle_num": 5000,
    "num": 2, # cndle
    "candle_unit": "M5",
}

oa = oanda_class.Oanda(tk.accountID, tk.access_token, "practice")
start_time = datetime.datetime.now().replace(microsecond=0)  # 現在の時刻を取得
main_inspection()  # ほんちゃん
end_time = datetime.datetime.now().replace(microsecond=0)  # 現在の時刻を取得
print((end_time-start_time).seconds, start_time, end_time)

# # graph()

