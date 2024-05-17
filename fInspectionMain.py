import pandas as pd
import threading  # 定時実行用
import time
import datetime
import fTurnInspection as t  # とりあえずの関数集
import tokens as tk  # Token等、各自環境の設定ファイル（git対象外）
import classOanda as classOanda
import making as mk
import fGeneric as f
import fDoublePeaks as dp
import classPosition as classPosition
import fRangeInspection as ri
import fPeakLineInspection as p

# 調査として、DoubleやRange等の複数Inspectionを利用する場合、このファイルから呼び出す(一番下）

# 処理時間削減の為、data

# その他オーダーに必要な処理はここで記載する
def Inspection_main(df_r):
    """
    主にExeから呼ばれ、ダブル関係の結果(このファイル内のbeforeとbreak)をまとめ、注文形式にして返却する関数
    引数
    "data": df_r ローソク情報(逆順[直近が上の方にある＝時間降順])のみ。
    "use_in_range_inspection" :exeからexeの持っているLowLineやUpperLineを受け取る
        "lower_line"と"upper_line"が含まれる

    :return:
    このリターンの値は、そのまま発注に使われる。（take_position_flagがTrueの場合、exe_orders(配列)のオーダーが入る
        "take_position_flag": True or False
        "exe_orders": オーダーの配列。オーダーについては
        "lower_line": exeのLowerLineを書き換えるため
        "upper_line": exeのupperLineを書き換えるため

    """
    # パラメータから情報を取得する
    flag_and_orders = {
        "take_position_flag": False,
    }
    # （０）データを取得する
    peaks_info = p.peaks_collect_main(df_r[:90], 10)  # Peaksの算出（ループ時間短縮の為、必要最低限のピーク数（＝４）を指定する）
    peaks = peaks_info['all_peaks']
    latest = peaks[0]
    river = peaks[1]  # 最新のピーク（リバーと呼ぶ。このCount＝２の場合、折り返し直後）
    turn = peaks[2]  # 注目するポイント（ターンと呼ぶ）
    flop3 = peaks[3]  # レンジ判定用（プリフロップと呼ぶ）
    order_information = {"take_position_flag": False}  # ■何もなかった場合に返すもの（最低限の返却値）
    print("  <対象>:運用モード")
    print("  Latest", latest)
    print("  RIVER", river)
    print("  TURN ", turn)
    print("  FLOP3", flop3)

    if latest['count'] != 2:
        return {"take_position_flag": 0}

    # （１）RangeInspectionを実施（ここでTakePositionFlagを付与する）
    line_result = ri.find_lines(df_r)  # Lineが発見された場合には、['line_strength']が１以上になる
    latest = line_result['latest_line']
    if latest['line_strength'] != 0:
        # 直近でLINEを発見した場合、オーダーを生成する
        tk.line_send(" LINE発見", line_result)
        orders = ri.range_trid_make_order(line_result)
        flag_and_orders = {
            "take_position_flag": True,
            "exe_orders": orders,
        }
    else:
        # LINEが発見されない場合は、LINEに関するオーダーは発行しない
        # exe側の更新も行わない
        pass

    # （２）シンプルなダブルトップを見つける
    doublePeak_ans = dp.DoublePeak_4peaks(df_r, peaks)
    if doublePeak_ans['take_position_flag']:
        print(" シンプルDT発見")
        flag_and_orders = doublePeak_ans

    # 【FINAL】
    return flag_and_orders

    # ターンの直後かどうか
    # if peaks[0]['count'] != 2:
    #     print(" ターンから離れた状態。必要に応じて状態判別")
    #     return order_information
    #
    # # （１）beforeDoublePeakについて
    # # ダブルトップ直前で、ダブルトップを形成するところを狙いに行く。TF＜0.4、RT＜0.7
    # beforeDoublePeak_ans = dp.beforeDoublePeak(df_r, peaks)
    # #
    # # # (2)ダブルトップポイントをリバーが大きく通過している場合。TF＜0.4、RT＞1.3
    # DoublePeakBreak_ans = dp.DoublePeakBreak(df_r, peaks)
    #
    # # (3)ダブルトップ（これはピークが１０個必要。過去のデータを比べて最ピークかどうかを確認したいため）
    # doublePeak_ans = dp.DoublePeak_4peaks(df_r, peaks)
    #
    # # 【オーダーを統合する】  現状同時に成立しない仕様。
    # if doublePeak_ans['take_position_flag']:
    #     order_information = doublePeak_ans
    # elif DoublePeakBreak_ans['take_position_flag']:
    #     order_information = DoublePeakBreak_ans  # オーダー発行情報のみを返却する
    #
    # return order_information
