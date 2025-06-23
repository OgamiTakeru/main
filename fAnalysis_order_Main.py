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
import fCommonFunction as cf
import fMoveSizeInspection as ms
import fHookFigureInspection as hi
import fCrossMoveInspection as cm
import fFlagInspection as fi
import fFlagInspection_AnotherFoot as fia
import fSimpleTurnInspection as sti
import fSimpleTurnInspection_test as sti_t
import classPeaks as cpk
import fPredictTurnInspection as pi

oa = classOanda.Oanda(tk.accountIDl, tk.access_tokenl, "live")  # クラスの定義


def wrap_all_inspections(df_r):
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

    # peaksの算出
    peaks_class = cpk.PeaksClass(df_r)

    predict_result = pi.wrap_predict_turn_inspection(peaks_class)  #
    if predict_result['take_position_flag']:
        flag_and_orders["take_position_flag"] = True
        flag_and_orders["exe_orders"] = predict_result['exe_orders']
        # 代表プライオリティの追加
        max_priority = max(flag_and_orders["exe_orders"], key=lambda x: x['priority'])['priority']
        flag_and_orders['max_priority'] = max_priority
        flag_and_orders['for_inspection_dic'] = {}

    return flag_and_orders



# def new_analysis(df_r):
#     """
#     クラスをたくさん用いがケース
#     args[0]は必ずdf_rであることで、必須。
#     args[1]は、本番の場合、過去の決済履歴のマイナスの大きさでTPが変わるかを検討したいため、オーダークラスを受け取る
#     """
#     print("■■■■調査開始■■■■")
#
#     #
#     flag_and_orders = {
#         "take_position_flag": False,
#         "exe_orders": [],  # 本番用（本番運用では必須）
#     }
#
#     # peaksの算出
#     peaks_class = cpk.PeaksClass(df_r)
#     mountain_result = sti.cal_big_mountain(peaks_class)  #
#
#     if mountain_result['take_position_flag']:
#         flag_and_orders["take_position_flag"] = True
#         flag_and_orders["exe_orders"] = mountain_result['exe_orders']
#         # 代表プライオリティの追加
#         print(flag_and_orders["exe_orders"])
#         max_priority = max(flag_and_orders["exe_orders"], key=lambda x: x['priority'])['priority']
#         flag_and_orders['max_priority'] = max_priority
#         flag_and_orders['for_inspection_dic'] = {}
#
#     # break_short_inspection = sti.cal_short_time_break(peaks_class)
#     # if break_short_inspection['take_position_flag']:
#     #     flag_and_orders["take_position_flag"] = True
#     #     flag_and_orders["exe_orders"] = break_short_inspection['exe_orders']
#     #     # 代表プライオリティの追加
#     #     max_priority = max(flag_and_orders["exe_orders"], key=lambda x: x['priority'])['priority']
#     #     flag_and_orders['max_priority'] = max_priority
#     #     flag_and_orders['for_inspection_dic'] = {}
#
#     return flag_and_orders
#
#
# def new_analysis_test(df_r):
#     """
#     クラスをたくさん用いがケース
#     args[0]は必ずdf_rであることで、必須。
#     args[1]は、本番の場合、過去の決済履歴のマイナスの大きさでTPが変わるかを検討したいため、オーダークラスを受け取る
#     """
#     print("■■■■調査開始■■■■")
#
#     #
#     flag_and_orders = {
#         "take_position_flag": False,
#         "exe_orders": [],  # 本番用（本番運用では必須）
#     }
#
#     # peaksの算出
#     peaks_class = cpk.PeaksClass(df_r)
#     mountain_result = sti_t.cal_big_mountain(peaks_class)  #
#
#     if mountain_result['take_position_flag']:
#         flag_and_orders["take_position_flag"] = True
#         flag_and_orders["exe_orders"] = mountain_result['exe_orders']
#         # 代表プライオリティの追加
#         print(flag_and_orders["exe_orders"])
#         max_priority = max(flag_and_orders["exe_orders"], key=lambda x: x['priority'])['priority']
#         flag_and_orders['max_priority'] = max_priority
#         flag_and_orders['for_inspection_dic'] = {}
#
#     # break_short_inspection = sti.cal_short_time_break(peaks_class)
#     # if break_short_inspection['take_position_flag']:
#     #     flag_and_orders["take_position_flag"] = True
#     #     flag_and_orders["exe_orders"] = break_short_inspection['exe_orders']
#     #     # 代表プライオリティの追加
#     #     max_priority = max(flag_and_orders["exe_orders"], key=lambda x: x['priority'])['priority']
#     #     flag_and_orders['max_priority'] = max_priority
#     #     flag_and_orders['for_inspection_dic'] = {}
#
#     return flag_and_orders
#

# def predict_analysis_test(df_r):
#     """
#     クラスをたくさん用いがケース
#     args[0]は必ずdf_rであることで、必須。
#     args[1]は、本番の場合、過去の決済履歴のマイナスの大きさでTPが変わるかを検討したいため、オーダークラスを受け取る
#     """
#     print("■■■■調査開始■■■■")
#
#     #
#     flag_and_orders = {
#         "take_position_flag": False,
#         "exe_orders": [],  # 本番用（本番運用では必須）
#     }
#
#     # peaksの算出
#     peaks_class = cpk.PeaksClass(df_r)
#     mountain_result = pi.cal_predict_turn(peaks_class)  #
#
#     if mountain_result['take_position_flag']:
#         flag_and_orders["take_position_flag"] = True
#         flag_and_orders["exe_orders"] = mountain_result['exe_orders']
#         # 代表プライオリティの追加
#         print(flag_and_orders["exe_orders"])
#         max_priority = max(flag_and_orders["exe_orders"], key=lambda x: x['priority'])['priority']
#         flag_and_orders['max_priority'] = max_priority
#         flag_and_orders['for_inspection_dic'] = {}
#
#     # break_short_inspection = sti.cal_short_time_break(peaks_class)
#     # if break_short_inspection['take_position_flag']:
#     #     flag_and_orders["take_position_flag"] = True
#     #     flag_and_orders["exe_orders"] = break_short_inspection['exe_orders']
#     #     # 代表プライオリティの追加
#     #     max_priority = max(flag_and_orders["exe_orders"], key=lambda x: x['priority'])['priority']
#     #     flag_and_orders['max_priority'] = max_priority
#     #     flag_and_orders['for_inspection_dic'] = {}
#
#     return flag_and_orders
