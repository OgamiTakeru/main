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

oa = classOanda.Oanda(tk.accountIDl, tk.access_tokenl, "live")  # クラスの定義


# now_price_dic = oa.NowPrice_exe("USD_JPY")['data']['mid']
# now_price = now_price_dic['data']['mid']

# 調査として、DoubleやRange等の複数Inspectionを利用する場合、このファイルから呼び出す(一番下）


# 処理時間削減の為、data
# def order_information_add_maji(finalized_order):
#     """
#     強制的に
#     カスケードロスカとトレールを入れる。このレンジインスペクションがメイン
#     :param finalized_order:
#     :return:
#     """
#
#     # カスケードロスカ
#     finalized_order['lc_change'] = [
#         {"lc_change_exe": True, "lc_trigger_range": 0.013, "lc_ensure_range": -0.05},
#         {"lc_change_exe": True, "lc_trigger_range": 0.04, "lc_ensure_range": 0.023}
#     ]
#
#     # トレール注文を入れる
#     finalized_order['tr_range'] = 0.05
#
#     return finalized_order
#
#
# def order_information_add_small(finalized_order):
#     """
#     強制的に
#     カスケードロスカとトレールを入れる。このレンジインスペクションがメイン
#     :param finalized_order:
#     :return:
#     """
#
#     # カスケードロスカ
#     finalized_order['lc_change'] = [
#         {"lc_change_exe": True, "lc_trigger_range": 0.016, "lc_ensure_range": 0.013},
#         {"lc_change_exe": True, "lc_trigger_range": 0.04, "lc_ensure_range": 0.023}
#     ]
#
#     # トレール注文を入れる
#     finalized_order['tr_range'] = 0.05
#
#     return finalized_order


# その他オーダーに必要な処理はここで記載する
# def inspection_river_line_make_order(df_r):
#     # 返却用のDicを書いておく
#     flag_and_orders = {
#         "take_position_flag": False,
#         "exe_orders": [],  # 本番用の、辞書の配列
#         "exe_order": cf.order_finalize(cf.order_base(100)),  # 検証用（配列ではなく、一つの辞書）
#     }
#
#     # （０）Peakデータを取得する(データフレムは二時間半前くらいが良い？？）
#     print(" 【調査】リバーLine")
#     df_r_range = df_r[:]  # 数を調整したい場合はここで（基本的にはここでは調整せず、呼び出し元で調整しておく必要がある。）
#     print(df_r_range.head(1))
#     print(df_r_range.tail(1))
#     peaks_info = p.peaks_collect_main(df_r_range, 15)  # Peaksの算出（ループ時間短縮と調査の兼ね合いでpeaks数は15とする）
#     peaks = peaks_info['all_peaks']
#     print("PEAKS")
#     gene.print_arr(peaks)
#
#     if peaks[0]['count'] != 2:  # 予測なので、LatestがN個続いたときに実行してみる
#         print(" latestがCOUNTが2以外の場合は終了")
#         return flag_and_orders
#
#     # 1,旧順張りのためのLINEを見つける方法(riverを基準にする場合）
#     line_info = ri.find_latest_line_based_river(df_r_range, peaks)
#
#     # 1-3 オーダーを発行する
#     # オーダー情報の準備
#     # now_price = oa.NowPrice_exe("USD_JPY")['data']['mid']
#     now_price = df_r.iloc[0]['open']
#     order_base_info = cf.order_base(now_price)  # オーダーの初期辞書を取得する
#     exe_orders_arr = []
#
#     if line_info['strength_info']['line_strength'] > 2:  # >= 1.5 < 1
#         # 直近がLINEを形成し、さらにそれが強いラインの場合。
#         main_order = order_base_info.copy()
#         main_order['target'] = 0.01
#         main_order['tp'] = 0.05  # LCは広め
#         main_order['lc'] = 0.05  # LCは広め
#         main_order['type'] = 'LIMIT'
#         main_order['expected_direction'] = peaks[1]['direction'] * -1  # riverベース。*1=突破,*-1抵抗
#         main_order['priority'] = line_info['strength_info']['line_strength']
#         main_order['units'] = order_base_info['units'] * 1
#         main_order['name'] = str(line_info['strength_info']['line_strength']) + "Main_resistance"
#         main_order["lc_change"] = [
#             {"lc_change_exe": True, "lc_trigger_range": 0.04, "lc_ensure_range": 0.01}
#         ]
#         # 注文を配列に追加
#         exe_orders_arr.append(cf.order_finalize(main_order))
#
#         # ショートTPのオーダーを追加
#         short_tp_order = main_order.copy()
#         short_tp_order['tp'] = 0.03
#         short_tp_order['unit'] = short_tp_order['unit'] * 0.9
#         short_tp_order['name'] = short_tp_order['name'] + "_SHORT"
#         exe_orders_arr.append(cf.order_finalize(short_tp_order))
#         # print(" ★★ORDER PRINT")
#         # print(exe_orders_arr)
#         # print(exe_orders_arr[0])
#         flag_and_orders = {
#             "take_position_flag": True,
#             "exe_orders": exe_orders_arr,  # 本番用の、辞書の配列
#             "exe_order": exe_orders_arr[0],  # 検証用（配列ではなく、一つの辞書）
#         }
#         return flag_and_orders
#     elif peaks[1]['count'] == 5:  # riverが5の場合は、もっと伸びると信じる
#         # 折り返し直後だが、同一価格がない場合（突破するケースが多い？？）
#         main_order = order_base_info.copy()
#         main_order['target'] = 0.01
#         main_order['tp'] = 0.05  # LCは広め
#         main_order['lc'] = 0.05  # LCは広め
#         main_order['expected_direction'] = peaks[1]['direction'] * 1  # riverベース。*1=突破,*-1抵抗
#         main_order['priority'] = line_info['strength_info']['line_strength']
#         main_order['units'] = order_base_info['units'] * 0.1
#         main_order['name'] = str(line_info['strength_info']['line_strength']) + "NoLine_resistance"
#         main_order["lc_change"] = [
#             {"lc_change_exe": True, "lc_trigger_range": 0.04, "lc_ensure_range": 0.01}
#         ]
#         # 注文を配列に追加
#         exe_orders_arr.append(cf.order_finalize(main_order))
#         # ショートTPのオーダーを追加
#         short_tp_order = main_order.copy()
#         short_tp_order['tp'] = 0.03
#         short_tp_order['unit'] = short_tp_order['unit'] * 0.9
#         short_tp_order['name'] = short_tp_order['name'] + "_SHORT"
#         exe_orders_arr.append(cf.order_finalize(short_tp_order))
#         # print(" ★★ORDER PRINT")
#         # print(exe_orders_arr)
#         # print(exe_orders_arr[0])
#         flag_and_orders = {
#             "take_position_flag": True,
#             "exe_orders": exe_orders_arr,  # 本番用の、辞書の配列
#             "exe_order": exe_orders_arr[0],  # 検証用（配列ではなく、一つの辞書）
#         }
#         return flag_and_orders
#     else:
#         # 【検証用分岐】CSV出力時に項目がずれないように、ポジションフラグがない場合でもオーダーベースは残す
#         # 本番環境では不要となる
#         flag_and_orders = {
#             "take_position_flag": False,
#             "exe_orders": exe_orders_arr,  # 本番用の、辞書の配列
#             "exe_order": cf.order_finalize(order_base_info),  # 検証用（配列ではなく、一つの辞書）
#         }
#         return flag_and_orders
#
#
# def wrap_up_inspection_orders(df_r):
#     # 必要最低限の返却値の定義
#     for_res = {
#         "take_position_flag": False,  # 必須
#         "exe_orders": [],  # 仮で作っておく
#         "exe_order": {}
#     }
#
#     # 調査実施
#     line_order_info = inspection_river_line_make_order(df_r)
#     p_line_order_info = inspection_predict_line_make_order(df_r)
#
#     if line_order_info['take_position_flag'] and p_line_order_info['take_position_flag']:
#         print("　本来はexe_ordersをがっちゃんこしたい(現状は同タイミングはありえない）")
#
#     # 今(上記二つの解析)は明確にタイミングが異なり、同時の成立がないため、独立して返却が可能
#     if line_order_info['take_position_flag']:
#         # tk.line_send("通常Flag成立")
#         for_res = line_order_info
#     elif p_line_order_info['take_position_flag']:
#         print(p_line_order_info)
#         for_res = p_line_order_info
#
#     return for_res
#


# def inspection_predict_line_make_order(df_r):
#     """
#     主にExeから呼ばれ、ダブル関係の結果(このファイル内のbeforeとbreak)をまとめ、注文形式にして返却する関数
#     引数
#     "data": df_r ローソク情報(逆順[直近が上の方にある＝時間降順])のみ。
#
#     :return:
#     　このリターンの値は、そのまま発注に使われる。
#     　本番（main_exe)から呼ばれる場合と、検証(main_analysis)から呼ばれる場合では、返すべき値が異なることに注意。
#     　本番環境は複数のオーダーが可能だが、検証は一つのオーダーのみしか受け付けられないため。
#     　本番環境を行いながらでもテストができるように、辞書配列と辞書を同時に返却する
#     　（辞書は基本的に辞書配列の[0]となる見込み）
#     　返却値は以下の通り
#       return{
#             "take_position_flag": True or False　Trueの場合、オーダーが入る
#             "exe_orders": オーダーの【配列】。複数オーダーが可能な本番環境用
#             "exe_order": オーダーの辞書単品。単品オーダーのみ受付可能な検証環境用（基本、exe_orders[0]でOK？）
#       }
#     """
#     # 返却値を設定しておく
#     flag_and_orders = {
#         "take_position_flag": False,
#         "exe_orders": [],  # 本番用（本番運用では必須）
#         "exe_order": {}  # 検証用（CSV出力時。なお本番運用では不要だが、検証運用で任意。リストではなく辞書1つのみ）
#     }
#     # 関数が来た時の表示
#     print("    【調査スタート】予測Line")
#     print(df_r.head(1))
#     print(df_r.tail(1))
#
#     # 各数字やデータを取得する
#     now_price = cf.now_price()  # 現在価格の取得
#     order_base_info = cf.order_base(now_price)  # オーダー発行の元データを取得
#     fixed_information = cf.information_fix({"df_r": df_r})  # 引数情報から、調査対象のデータフレームとPeaksを確保する
#     peaks = fixed_information['peaks']
#
#     if peaks[0]['count'] == 2:  # 予測なので、LatestがN個続いたときに実行してみる
#         print(" latestがCOUNTが2の場合なので実行")
#         # （１）RangeInspectionを実施（ここでTakePositionFlagを付与する）
#         predict_line_info_list = ri.find_predict_line_strength_based_same_price_list(
#             {"df_r": df_r, "peaks": peaks})  # 調査！
#         print(" (Main)受け取った同価格リスト")
#         gene.print_arr(predict_line_info_list)
#     elif peaks[0]['count'] == 3:
#         print(" latestがCOUNTが3の場合なので実行（突破のみ）")
#         # （１）RangeInspectionを実施（ここでTakePositionFlagを付与する）
#         predict_line_info_list = ri.find_predict_line_based_latest_for3({"df_r": df_r, "peaks": peaks})  # 調査！
#         print(" (Main)受け取った同価格リスト")
#         gene.print_arr(predict_line_info_list)
#     else:
#         print(" latestが2と3以外")
#         return flag_and_orders
#
#     # （２）状況にあわせたオーダーを生成する
#     print("!テスト")
#     print(predict_line_info_list)
#     for i, each_line_info in enumerate(predict_line_info_list):
#         # 受け取った価格リストからオーダーを生成する
#         line_strength = float(each_line_info['strength_info']['line_strength'])
#         peak_strength_ave = float(each_line_info['strength_info']['peak_strength_ave'])
#         target_price = each_line_info['line_base_info']['line_base_price']
#         print("  (M)Line等の強度", line_strength, peak_strength_ave)
#         # オーダーの元を生成する
#         main_order = copy.deepcopy(order_base_info)
#
#         # if now_price - 0.04 <= target_price <= now_price + 0.04:
#         #     tk.line_send("    距離近いオーダーをキャンセル")
#         #     continue
#
#         # 暫定（オーダーの数を減らすため）
#         if i != 0:
#             continue
#
#         # 強度の組み合わせで、オーダーを生成する
#         if line_strength >= 0.5 and peak_strength_ave >= 0.75:
#             # ①強い抵抗線となりそうな場合（Latestから見ると、逆張り[limitオーダー]となる)
#             print("  (m)強い抵抗線　line,peak", line_strength, peak_strength_ave, target_price)
#             main_order['target'] = each_line_info['line_base_info']['line_base_price']
#             main_order['tp'] = 0.3 * line_strength  # 0.09  # LCは広め
#             main_order['lc'] = 0.15  # * line_strength  # 0.09  # LCは広め
#             main_order['type'] = 'LIMIT'
#             # main_order['tr_range'] = 0.10  # 要検討
#             main_order['expected_direction'] = peaks[0]['direction'] * -1  # latestに対し、1は突破。*-1は折り返し
#             main_order['priority'] = each_line_info['strength_info']['line_strength']
#             main_order['units'] = order_base_info['units'] * 1
#             main_order['name'] = each_line_info['strength_info']['remark'] + str(main_order['priority'])
#             # オーダーが来た場合は、フラグをあげ、オーダーを追加する
#             flag_and_orders['take_position_flag'] = True
#             flag_and_orders["exe_orders"].append(cf.order_finalize(main_order))
#             flag_and_orders["exe_order"] = main_order  # とりあえず代表一つ。。
#
#             # ショートTPのオーダーを追加
#             flag_and_orders["exe_orders"].append(cf.order_shorter(main_order))
#         elif -10 < line_strength < 0:
#             # -10を入れた理由は、オーダーを入れたくない時、－10入れておけばいいやと思ったので、、
#             if line_strength == -1:
#                 # フラッグ形状の場合
#                 # フラッグ形状やDoublePeak未遂が発覚している場合。Latest方向に強く伸びる予想 (通過と同義だが、プライオリティが異なる）
#                 print("  (m)フラッグ・突破形状検出（大きな動き前兆）", line_strength, peak_strength_ave, target_price)
#                 main_order['target'] = each_line_info['line_base_info']['line_base_price']
#                 main_order['tp'] = 0.30  # LCは広め
#                 main_order['lc'] = 0.15  #
#                 main_order['type'] = 'STOP'  # 順張り
#                 # main_order['tr_range'] = 0.10  # 要検討
#                 main_order['expected_direction'] = peaks[0]['direction'] * 1.2  # latestに対し、1は突破。*-1は折り返し
#                 main_order['priority'] = 2
#                 main_order['units'] = order_base_info['units'] * 1
#                 main_order['name'] = each_line_info['strength_info']['remark'] + str(main_order['priority'])
#                 # オーダーが来た場合は、フラグをあげ、オーダーを追加する
#                 flag_and_orders['take_position_flag'] = True
#                 flag_and_orders["exe_orders"].append(cf.order_finalize(main_order))
#                 flag_and_orders["exe_order"] = main_order  # とりあえず代表一つ。。
#
#                 # ショートTPのオーダーを追加
#                 flag_and_orders["exe_orders"].append(cf.order_shorter(main_order))
#             else:
#                 # 突破形状の場合
#                 flag_and_orders['take_position_flag'] = True
#                 flag_and_orders["exe_orders"].append(
#                     cf.order_finalize(each_line_info['strength_info']['order_before_finalized']))
#                 flag_and_orders["exe_order"] = cf.order_finalize(
#                     each_line_info['strength_info']['order_before_finalized'])  # とりあえず代表一つ。。
#
#                 # ショートTPのオーダーを追加
#                 # flag_and_orders["exe_orders"].append(cf.order_shorter(each_line_info['strength_info']['order_before_finalized']))
#
#         elif peak_strength_ave < 0.75:
#             # ②ピークが弱いものばかりである場合、通過点レベルの線とみなす（Latestから見ると、順張りとなる）
#             print("  (m)通過線　line,peak", line_strength, peak_strength_ave, target_price)
#             main_order['target'] = each_line_info['line_base_info']['line_base_price']
#             main_order['tp'] = 0.03  # LCは広め
#             main_order['lc'] = 0.04  # LCは広め
#             main_order['type'] = 'STOP'  # 順張り
#             # main_order['tr_range'] = 0.10  # 要検討
#             main_order['expected_direction'] = peaks[0]['direction'] * 1  # latestに対し、1は突破。*-1は折り返し
#             main_order['priority'] = 1
#             main_order['units'] = order_base_info['units'] * 0.1
#             main_order['name'] = "今はないはずのLINE探索(通過)" + str(main_order['priority'])
#             main_order['lc_change'] = [
#                 {"lc_change_exe": True, "lc_trigger_range": 0.02, "lc_ensure_range": 0.01},
#                 {"lc_change_exe": True, "lc_trigger_range": 0.04, "lc_ensure_range": 0.02},
#                 {"lc_change_exe": True, "lc_trigger_range": 0.10, "lc_ensure_range": 0.08}
#             ]
#             # オーダーが来た場合は、フラグをあげ、オーダーを追加する
#             flag_and_orders['take_position_flag'] = True
#             flag_and_orders["exe_orders"].append(cf.order_finalize(main_order))
#             flag_and_orders["exe_order"] = main_order  # とりあえず代表一つ。。
#
#             # ショートTPのオーダーを追加
#             flag_and_orders["exe_orders"].append(cf.order_shorter(main_order))
#         else:
#             # オーダー条件に合わない場合は、変更しない（main_orderのまま）。
#             # ただしこれは存在しない見込み（SamePriceが存在する＝オーダーを入れる）
#             pass
#
#     # (3) 設定されるLINEが遠すぎる場合、そこには到達するだろう、という見込みで通過前提の現在価格からそこへ向かうオーダーを追加する
#     # if len(predict_line_info_list)>0:
#     #     # predictLineが存在する場合のみ実行
#     #     # 条件の設定
#     #     if latest['direction'] == 1:
#     #         # 直近が上向きの場合（それよりも上側にオーダーLINEが設定されているオーダーリストの先頭が一番高い）
#     #         farthest_line = predict_line_info_list[0]['line_base_info']['line_base_price']
#     #         farthest_gap = abs(farthest_line - now_price)
#     #         nearest_line = predict_line_info_list[-1]['line_base_info']['line_base_price']
#     #         nearest_gap = nearest_line - now_price
#     #     else:
#     #         # 直近が下向きの場合　（それよりも下側にオーダーLINEが設定されている。オーダーリストの先頭が一番低い。Latestによって
#     #         farthest_line = predict_line_info_list[0]['line_base_info']['line_base_price']
#     #         farthest_gap = abs(farthest_line - now_price)
#     #         nearest_line = predict_line_info_list[-1]['line_base_info']['line_base_price']
#     #         nearest_gap = nearest_line - now_price
#     #     # 発行
#     #     print("    オーダーまでの幅", farthest_gap, nearest_line, farthest_line, now_price)
#     #     if farthest_gap >= 0.08:
#     #         # 近くてもGapが15Pips以上ある場合、Latestがそのまま延長して、そのLineまで頑張ると想定する。
#     #         main_order = copy.deepcopy(order_base_info)  # オーダーの生成
#     #         main_order['target'] = farthest_gap * 0.3  # 少しだけ余裕を見て設定
#     #         main_order['tp'] = 0.20  # LCは広め
#     #         main_order['lc'] = 0.1  # LCは広め
#     #         # main_order['type'] = 'STOP'  # 元々の通過。Latestに対して、順張り
#     #         main_order['type'] = 'LIMIT'  # Latestに対して、順張り
#     #         # main_order['tr_range'] = 0.10  # 要検討
#     #         # main_order['expected_direction'] = peaks[0]['direction'] * 1  # 元々の通過。latestに対し、1は突破。*-1は折り返し
#     #         main_order['expected_direction'] = peaks[0]['direction'] * -1  # latestに対し、1は突破。*-1は折り返し
#     #         main_order['priority'] = 1
#     #         main_order['units'] = order_base_info['units'] * 0.5
#     #         main_order['name'] = "Line遠(Latest延長)" + str(1)
#     #         main_order['lc_change'] = [
#     #             {"lc_change_exe": True, "lc_trigger_range": 0.01, "lc_ensure_range": -0.01},
#     #             {"lc_change_exe": True, "lc_trigger_range": 0.03, "lc_ensure_range": 0.01},
#     #             {"lc_change_exe": True, "lc_trigger_range": 0.05, "lc_ensure_range": 0.03},
#     #             {"lc_change_exe": True, "lc_trigger_range": 0.10, "lc_ensure_range": 0.08}
#     #         ]
#     #         # オーダーが来た場合は、フラグをあげ、オーダーを追加する
#     #         flag_and_orders['take_position_flag'] = True
#     #         flag_and_orders["exe_orders"].append(gene.order_finalize(main_order))
#     #         flag_and_orders["exe_order"] = main_order  # とりあえず代表一つ。。
#
#     # プライオリティの最大値を取得しておく
#     if len(flag_and_orders["exe_orders"]) >= 1:
#         max_priority = max(flag_and_orders["exe_orders"], key=lambda x: x['priority'])['priority']
#         flag_and_orders['max_priority'] = max_priority
#         print("max_priority", max_priority)
#         # print(flag_and_orders)
#
#     print("flag_and_ordes")
#     print(flag_and_orders)
#     print("ここまで")
#
#     return flag_and_orders


def analysis_warp_up_and_make_order(df_r):
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
    # 返却値を設定しておく　（上書きされない限り、takePositionFlag=Falseのまま進み、返却される）
    flag_and_orders = {
        "take_position_flag": False,
        "exe_orders": [],  # 本番用（本番運用では必須）
        "exe_order": {}, # 検証用（CSV出力時。なお本番運用では不要だが、検証運用で任意。リストではなく辞書1つのみ）
        'for_inspection_dic': {}
    }
    # 表示のインデント
    ts = " "
    s = "  "  # 2個分
    print(ts, "■■■■調査開始■■■■")
    # 関数が来た時の表示
    print(df_r.head(1))
    print(df_r.tail(1))
    # 各数字やデータを取得する
    fixed_information = cf.information_fix({"df_r": df_r})  # 引数情報から、調査対象のデータフレームとPeaksを確保する
    peaks = fixed_information['peaks']

    # ■■■■
    # ■各検証を実施し、その結果を保持する■
    print(s, "■フラッグ形状の調査")
    flag_orders_and_evidence = fi.main_flag({"df_r": df_r, "peaks": peaks})  # 調査(旧バージョン）
    # flag_orders_and_evidence = ri.main_line_strength_analysis_and_order({"df_r": df_r, "peaks": peaks})
    print(s, "■DoubleTOpBreakの調査")
    break_double_top_strength_orders_and_evidence = dp.for_inspection_main_double_peak({"df_r": df_r, "peaks": peaks})
    # print(s, "■クロス形状の判定")
    # cross_order = cm.main_cross({"df_r": df_r, "peaks": peaks})

    # ■各結果からオーダーを生成する（＋検証用のデータfor_inspection_dicも）
    if break_double_top_strength_orders_and_evidence['take_position_flag']:
        print(s, "【最終的判断:ダブルトップ突破系】⇒★★今回はLatest2では待機(take_positionをFalseに)")
        # DoubleTopの判定が最優先 (単品）
        flag_and_orders["take_position_flag"] = False
        flag_and_orders["exe_orders"] = \
            [cf.order_finalize(break_double_top_strength_orders_and_evidence['order_before_finalized'])]
        flag_and_orders['for_inspection_dic'] = break_double_top_strength_orders_and_evidence['for_inspection_dic']
    elif flag_orders_and_evidence['take_position_flag']:
        flag_and_orders["take_position_flag"] = True
        flag_and_orders["exe_orders"] = flag_orders_and_evidence['exe_orders']
        flag_and_orders['for_inspection_dic'] = flag_orders_and_evidence['information']
        flag_and_orders['for_inspection_dic']['latest_count'] = peaks[0]['count']
    # elif cross_order['take_position_flag']:
    #     print(s, "【最終的判断:クロス形状の確認")
    #     # DoubleTopの判定が最優先 (単品）
    #     flag_and_orders["take_position_flag"] = True
    #     flag_and_orders["exe_orders"] = cross_order['exe_orders']
    print(flag_and_orders['take_position_flag'])
    gene.print_arr(flag_and_orders['exe_orders'])

    # プライオリティの追加
    if len(flag_and_orders["exe_orders"]) >= 1:
        max_priority = max(flag_and_orders["exe_orders"], key=lambda x: x['priority'])['priority']
        flag_and_orders['max_priority'] = max_priority
        print(s, "max_priority", max_priority)
        # print(flag_and_orders)

    # テスト
    if flag_and_orders['take_position_flag']:
        size_flag = ms.cal_move_size({"df_r": df_r, "peaks": peaks})
        if size_flag['range_flag']:
            # Trueの場合は通常通り
            # tk.line_send("直近幅が小さいため、オーダーキャンセル", flag_and_orders["exe_orders"][0]['name'])
            print(s, "直近幅が小さいため、オーダーキャンセル", flag_and_orders["exe_orders"][0]['name'])
            flag_and_orders['take_position_flag'] = False
            flag_and_orders['for_inspection_dic']['narrow'] = True  # 検証用データに情報追加
        else:
            print(s, " 通常の動き")
            flag_and_orders['for_inspection_dic']['narrow'] = False  # 検証用データに情報追加
            pass
    return flag_and_orders


def analysis_warp_up_and_make_order_30(df_r):
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
    # 返却値を設定しておく　（上書きされない限り、takePositionFlag=Falseのまま進み、返却される）
    flag_and_orders = {
        "take_position_flag": False,
        "exe_orders": [],  # 本番用（本番運用では必須）
        "exe_order": {}, # 検証用（CSV出力時。なお本番運用では不要だが、検証運用で任意。リストではなく辞書1つのみ）
        'for_inspection_dic': {}
    }
    # 表示のインデント
    ts = " "
    s = "  "  # 2個分
    print(ts, "■■■■調査開始■■■■")
    # 関数が来た時の表示
    print(df_r.head(1))
    print(df_r.tail(1))
    # 各数字やデータを取得する
    fixed_information = cf.information_fix({"df_r": df_r})  # 引数情報から、調査対象のデータフレームとPeaksを確保する
    peaks = fixed_information['peaks']

    # ■■■■
    # ■各検証を実施し、その結果を保持する■
    print(s, "■フラッグ形状の調査(５分足以外)")
    flag_orders_and_evidence_another = fia.main_flag({"df_r": df_r, "peaks": peaks})  # 調査

    # ■各結果からオーダーを生成する（＋検証用のデータfor_inspection_dicも）
    if flag_orders_and_evidence_another['take_position_flag']:
        flag_and_orders["take_position_flag"] = True
        flag_and_orders["exe_orders"] = flag_orders_and_evidence_another['exe_orders']
        flag_and_orders['for_inspection_dic'] = flag_orders_and_evidence_another['information']
        flag_and_orders['for_inspection_dic']['latest_count'] = peaks[0]['count']
    print(flag_and_orders['take_position_flag'])
    gene.print_arr(flag_and_orders['exe_orders'])

    # プライオリティの追加
    if len(flag_and_orders["exe_orders"]) >= 1:
        max_priority = max(flag_and_orders["exe_orders"], key=lambda x: x['priority'])['priority']
        flag_and_orders['max_priority'] = max_priority
        print(s, "max_priority", max_priority)
        # print(flag_and_orders)

    # テスト
    if flag_and_orders['take_position_flag']:
        size_flag = ms.cal_move_size({"df_r": df_r, "peaks": peaks})
        if size_flag['range_flag']:
            # Trueの場合は通常通り
            # tk.line_send("直近幅が小さいため、オーダーキャンセル", flag_and_orders["exe_orders"][0]['name'])
            print(s, "直近幅が小さいため、オーダーキャンセル", flag_and_orders["exe_orders"][0]['name'])
            flag_and_orders['take_position_flag'] = False
            flag_and_orders['for_inspection_dic']['narrow'] = True  # 検証用データに情報追加
        else:
            print(s, " 通常の動き")
            flag_and_orders['for_inspection_dic']['narrow'] = False  # 検証用データに情報追加
            pass
    return flag_and_orders


def for_practice_analysis_warp_up_and_make_order(df_r):
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
    # 返却値を設定しておく　（上書きされない限り、takePositionFlag=Falseのまま進み、返却される）
    flag_and_orders = {
        "take_position_flag": False,
        "exe_orders": [],  # 本番用（本番運用では必須）
        "exe_order": {}  # 検証用（CSV出力時。なお本番運用では不要だが、検証運用で任意。リストではなく辞書1つのみ）
    }
    # 表示のインデント
    ts = " "
    s = "  "  # 2個分
    print(ts, "■■■■調査開始■■■■")
    # 関数が来た時の表示
    print(df_r.head(1))
    print(df_r.tail(1))
    # 各数字やデータを取得する
    fixed_information = cf.information_fix({"df_r": df_r})  # 引数情報から、調査対象のデータフレームとPeaksを確保する
    peaks = fixed_information['peaks']

    fixed_information_for3 = cf.information_fix({"df_r": df_r[1:]})  # 引数情報から、調査対象のデータフレームとPeaksを確保する
    peaks_for3 = fixed_information_for3['peaks']

    # 検証環境で、Peaksが少ないことが発生するため、その場合は処理を進めないようにする（検証環境専用）
    if len(fixed_information['peaks']) == 0 or len(fixed_information_for3['peaks']) == 0:  # 検証で起きるエラーに対応する
        return flag_and_orders
    else:
        peaks = fixed_information['peaks']

    if peaks[0]['direction'] == peaks_for3[0]['direction']:
        print("　通常")
    else:
        print(" すぐ折り返しが来ている状態（latest3でやるつもりがlatest2で意図しない状態になるやつ")

    print('調査テスト')
    print(peaks)
    print(peaks_for3)

    # ■検証とオーダー作成を実行
    if peaks[0]['count'] == 2:  # 予測なので、LatestがN個続いたときに実行してみる
        print(s, "■Latest2回の場合の実行")
        # latestが2個の時に実行されるもの
        # ■latest延長の予測Lineとその強度を求める（フラッグ形状も加味する）（直近のピークの延長）
        # print(s, "■Latest基準の同価格Strengthの調査")
        # orders_and_evidence = ri.main_line_strength_inspection_and_order_practice({"df_r": df_r, "peaks": peaks})  # 調査！
        # # gene.print_arr(orders_and_evidence['evidence'], 2)
        #
        # # ■river時点の価格を含むLineの強度を確認する　(peak[1]はリバー。まだオーダーまで作成せず、参考値）
        # print(s, "■river方向（逆）の強度の確認")
        # river_peak_line_strength = ri.main_river_strength_inspection_and_order({"df_r": df_r, "peaks": peaks})

        # ■上記二つに置き換えて、フック形状判定とする
        print(s, "■フックやパラレルの調査")
        orders_and_evidence = hi.main_hook_figure_inspection_and_order_practice({"df_r": df_r, "peaks": peaks})

        # ■ダブルトップ突破型に関する情報を取得する
        print(s, "■DoubleTOpBreakの調査")
        break_double_top_strength_orders_and_evidence = dp.main_double_peak({"df_r": df_r, "peaks": peaks})
        # print(s, break_double_top_strength_orders_and_evidence)

        if break_double_top_strength_orders_and_evidence['take_position_flag']:
            print(s, "【最終的判断:ダブルトップ突破系】⇒★★今回はLatest2では待機(take_positionをFalseに)")
            # DoubleTopの判定が最優先 (単品）
            flag_and_orders["take_position_flag"] = True
            flag_and_orders["exe_orders"] = \
                [cf.order_finalize(break_double_top_strength_orders_and_evidence['order_before_finalized'])]
        elif orders_and_evidence['take_position_flag']:
            print(s, "【最終的判断:通常ストレングス(flag含む)】")
            # シンプルなLineStrengthによるオーダー発行
            flag_and_orders["take_position_flag"] = True
            flag_and_orders["exe_orders"] = orders_and_evidence["exe_orders"]
            # ■■最も強いストレングスが遠い場合、最も強いストレングスに向かう方向へトラリピを設定
            trid_do = False
            if trid_do and orders_and_evidence["target_strength"]["strength_info"]["line_strength"] >= 0:  # フラッグではない場合（こっちはフラッグの可能性もあり)
                # Lineで折り返される判定が前提。（0より低い値 ＝突破方向となり、今回のトラリピの対象外）
                now_price = cf.now_price()
                now_price = peaks[0]['peak']
                main_target_price = orders_and_evidence["target_strength"]["line_base_info"]["line_base_price"]
                gap = abs(main_target_price - now_price)
                if gap >= 0.10:
                    print("トラリピ入ります")
                    print("strength", orders_and_evidence["target_strength"]["strength_info"]["line_strength"],
                          main_target_price)
                    # print(s4, "トラリピ入ります")
                    # 10pips以上退屈する場合、3pips起きにトラリピを入れていく(オーダーの向きは、Latestの延長のため、latestDirと同様）
                    margin = 0.02 if peaks[0]['direction'] == 1 else -0.02
                    plan = {
                        "decision_price": now_price,
                        "units": 100,
                        "start_price": now_price + margin,
                        "expected_direction": peaks[0]['direction'],
                        "lc_range": peaks[0]['gap'],
                        "grid": 0.03,
                        "num": 1,
                        # "end_price": main_target_price,
                        "type": "STOP"
                    }
                    trid_orders_finalized = cf.make_trid_order(plan)  # トラリピオーダーの生成（ファイナライズド）
                    # gene.print_arr(trid_orders_finalized)
                    flag_and_orders["exe_orders"].extend(trid_orders_finalized)  # ここは配列を足すので、appendではなくextend

    elif peaks[0]['count'] == 3:
        # latestが3この時に実行されるもの
        # ■ダブルトップ突破型に関する情報を取得する
        print(s, "■Latest3回の場合の実行")
        print(s, "■DoubleTOpBreakの調査(latest3)")
        df_r_first_delete = df_r[0:]
        break_double_top_strength_orders_and_evidence = dp.main_double_peak({"df_r": df_r_first_delete})
        print(s, break_double_top_strength_orders_and_evidence)
        if break_double_top_strength_orders_and_evidence['take_position_flag']:
            # DoubleTopの判定が最優先 (単品）
            # tk.line_send("latest3でDoubleTop突破確認")
            flag_and_orders["take_position_flag"] = True
            flag_and_orders["exe_orders"] = \
                [cf.order_finalize(break_double_top_strength_orders_and_evidence['order_before_finalized'])]

    print(" ■検証終了")
    # print(flag_and_orders['take_position_flag'])
    # gene.print_arr(flag_and_orders['exe_orders'])

    # プライオリティの追加
    print("おーだー")
    print(flag_and_orders["exe_orders"])
    if len(flag_and_orders["exe_orders"]) >= 1:
        max_priority = max(flag_and_orders["exe_orders"], key=lambda x: x['priority'])['priority']
        flag_and_orders['max_priority'] = max_priority
        print("max_priority", max_priority)
        # print(flag_and_orders)

    # テスト
    if flag_and_orders['take_position_flag']:
        size_flag = ms.cal_move_size({"df_r": df_r, "peaks": peaks})
        if size_flag['range_flag']:
            # Trueの場合は通常通り
            # tk.line_send("直近幅が小さいため、オーダーキャンセル", flag_and_orders["exe_orders"][0]['name'])
            print("直近幅が小さいため、オーダーキャンセル", flag_and_orders["exe_orders"][0]['name'])
            flag_and_orders['take_position_flag'] = False
        else:
            print(" 通常の動き")
            pass
    return flag_and_orders


def for_inspection_analysis_warp_up_and_make_order(df_r):
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
    # ■情報の準備
    # 表示のインデント
    ts = " "
    s = "  "  # 2個分
    print(ts, "■■■■調査開始■■■■")
    print(df_r.head(1))
    print(df_r.tail(1))
    # 返却値を設定しておく　（上書きされない限り、takePositionFlag=Falseのまま進み、返却される）
    flag_and_orders = {
        "take_position_flag": False,
        "exe_orders": [],  # 本番用（本番運用では必須）
        'for_inspection_dic': {}  # 調査や解析で利用する情報
    }
    # 各数字やデータを取得する
    fixed_information = cf.information_fix({"df_r": df_r})  # 引数情報から、調査対象のデータフレームとPeaksを確保する
    peaks = fixed_information['peaks']

    # ■■■■
    # ■各検証を実施し、その結果を保持する■
    print(s, "■DoubleTOpBreakの調査")
    break_double_top_strength_orders_and_evidence = dp.for_inspection_main_double_peak({"df_r": df_r, "peaks": peaks})
    print(s, "■フラッグ形状の調査")
    flag_orders_and_evidence = fi.for_inspection_main_flag({"df_r": df_r, "peaks": peaks})  # 調査
    # print(s, "■フラッグ形状の調査(５分足以外)")
    # flag_orders_and_evidence_another = fia.main_flag({"df_r": df_r, "peaks": peaks})  # 調査
    # print(s, "■クロス形状の判定")
    # cross_order = cm.main_cross({"df_r": df_r, "peaks": peaks})

    # ■各結果からオーダーを生成する（＋検証用のデータfor_inspection_dicも）
    if break_double_top_strength_orders_and_evidence['take_position_flag']:
        print(s, "【最終的判断:ダブルトップ突破系】⇒★★今回はLatest2では待機(take_positionをFalseに)")
        # DoubleTopの判定が最優先 (単品）
        flag_and_orders["take_position_flag"] = False
        flag_and_orders["exe_orders"] = \
            [cf.order_finalize(break_double_top_strength_orders_and_evidence['order_before_finalized'])]
        flag_and_orders['for_inspection_dic'] = break_double_top_strength_orders_and_evidence['for_inspection_dic']
    elif flag_orders_and_evidence['take_position_flag']:
        flag_and_orders["take_position_flag"] = True
        flag_and_orders["exe_orders"] = flag_orders_and_evidence['exe_orders']
        flag_and_orders['for_inspection_dic'] = flag_orders_and_evidence['information']
        flag_and_orders['for_inspection_dic']['latest_count'] = peaks[0]['count']
    # elif flag_orders_and_evidence_another['take_position_flag']:
    #     flag_and_orders["take_position_flag"] = True
    #     flag_and_orders["exe_orders"] = flag_orders_and_evidence_another['exe_orders']
    #     flag_and_orders['for_inspection_dic'] = flag_orders_and_evidence_another['information']
    #     flag_and_orders['for_inspection_dic']['latest_count'] = peaks[0]['count']
    # elif cross_order['take_position_flag']:
    #     print(s, "【最終的判断:クロス形状の確認")
    #     # DoubleTopの判定が最優先 (単品）
    #     flag_and_orders["take_position_flag"] = True
    #     flag_and_orders["exe_orders"] = cross_order['exe_orders']

    # ■■■■
    # ■オーダー群の最大プライオリティの追加ー集計
    if len(flag_and_orders["exe_orders"]) >= 1:
        max_priority = max(flag_and_orders["exe_orders"], key=lambda x: x['priority'])['priority']
        flag_and_orders['max_priority'] = max_priority
        print(s, "max_priority", max_priority)
        # print(flag_and_orders)

    # ■■■■
    # ■直近の動きが小さいときはオーダーを入れないようにする
    if flag_and_orders['take_position_flag']:
        size_flag = ms.cal_move_size({"df_r": df_r, "peaks": peaks})
        if size_flag['range_flag']:
            # Trueの場合は通常通り
            # tk.line_send("直近幅が小さいため、オーダーキャンセル", flag_and_orders["exe_orders"][0]['name'])
            print(s, "直近幅が小さいため、オーダーキャンセル", flag_and_orders["exe_orders"][0]['name'])
            flag_and_orders['take_position_flag'] = True  # False  # 現在休止中
            flag_and_orders['for_inspection_dic']['small_move'] = True  # 検証用データに情報追加
        else:
            print(s, " 通常の動き")
            flag_and_orders['for_inspection_dic']['small_move'] = False  # 検証用データに情報追加
    return flag_and_orders


def for_inspection_analysis_warp_up_and_make_order_30(df_r):
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
    # ■情報の準備
    # 表示のインデント
    ts = " "
    s = "  "  # 2個分
    print(ts, "■■■■調査開始■■■■")
    print(df_r.head(1))
    print(df_r.tail(1))
    # 返却値を設定しておく　（上書きされない限り、takePositionFlag=Falseのまま進み、返却される）
    flag_and_orders = {
        "take_position_flag": False,
        "exe_orders": [],  # 本番用（本番運用では必須）
        'for_inspection_dic': {}  # 調査や解析で利用する情報
    }
    # 各数字やデータを取得する
    fixed_information = cf.information_fix({"df_r": df_r})  # 引数情報から、調査対象のデータフレームとPeaksを確保する
    peaks = fixed_information['peaks']

    # ■■■■
    # ■各検証を実施し、その結果を保持する■
    # print(s, "■フラッグ形状の調査(５分足以外)")
    # flag_orders_and_evidence_another = fia.main_flag({"df_r": df_r, "peaks": peaks})  # 調査
    print(s, "■クロス形状の判定")
    cross_order = cm.main_cross({"df_r": df_r, "peaks": peaks})

    # ■各結果からオーダーを生成する（＋検証用のデータfor_inspection_dicも）
    # if break_double_top_strength_orders_and_evidence['take_position_flag']:
    #     print(s, "【最終的判断:ダブルトップ突破系】⇒★★今回はLatest2では待機(take_positionをFalseに)")
    #     # DoubleTopの判定が最優先 (単品）
    #     flag_and_orders["take_position_flag"] = False
    #     flag_and_orders["exe_orders"] = \
    #         [cf.order_finalize(break_double_top_strength_orders_and_evidence['order_before_finalized'])]
    #     flag_and_orders['for_inspection_dic'] = break_double_top_strength_orders_and_evidence['for_inspection_dic']
    # elif flag_orders_and_evidence['take_position_flag']:
    #     flag_and_orders["take_position_flag"] = True
    #     flag_and_orders["exe_orders"] = flag_orders_and_evidence['exe_orders']
    #     flag_and_orders['for_inspection_dic'] = flag_orders_and_evidence['information']
    #     flag_and_orders['for_inspection_dic']['latest_count'] = peaks[0]['count']
    # elif flag_orders_and_evidence_another['take_position_flag']:
    #     flag_and_orders["take_position_flag"] = True
    #     flag_and_orders["exe_orders"] = flag_orders_and_evidence_another['exe_orders']
    #     flag_and_orders['for_inspection_dic'] = flag_orders_and_evidence_another['information']
    #     flag_and_orders['for_inspection_dic']['latest_count'] = peaks[0]['count']
    if cross_order['take_position_flag']:
        print(s, "【最終的判断:クロス形状の確認")
        # DoubleTopの判定が最優先 (単品）
        flag_and_orders["take_position_flag"] = True
        flag_and_orders["exe_orders"] = cross_order['exe_orders']
    # if flag_orders_and_evidence_another['take_position_flag']:
    #     flag_and_orders["take_position_flag"] = True
    #     flag_and_orders["exe_orders"] = flag_orders_and_evidence_another['exe_orders']
    #     flag_and_orders['for_inspection_dic'] = flag_orders_and_evidence_another['information']
    #     flag_and_orders['for_inspection_dic']['latest_count'] = peaks[0]['count']

    # ■■■■
    # ■オーダー群の最大プライオリティの追加ー集計
    if len(flag_and_orders["exe_orders"]) >= 1:
        max_priority = max(flag_and_orders["exe_orders"], key=lambda x: x['priority'])['priority']
        flag_and_orders['max_priority'] = max_priority
        print(s, "max_priority", max_priority)
        # print(flag_and_orders)

    # ■■■■
    # ■直近の動きが小さいときはオーダーを入れないようにする
    if flag_and_orders['take_position_flag']:
        size_flag = ms.cal_move_size({"df_r": df_r, "peaks": peaks})
        if size_flag['range_flag']:
            # Trueの場合は通常通り
            # tk.line_send("直近幅が小さいため、オーダーキャンセル", flag_and_orders["exe_orders"][0]['name'])
            print(s, "直近幅が小さいため、オーダーキャンセル", flag_and_orders["exe_orders"][0]['name'])
            flag_and_orders['take_position_flag'] = True  # False  # 現在休止中
            flag_and_orders['for_inspection_dic']['small_move'] = True  # 検証用データに情報追加
        else:
            print(s, " 通常の動き")
            flag_and_orders['for_inspection_dic']['small_move'] = False  # 検証用データに情報追加
    return flag_and_orders
