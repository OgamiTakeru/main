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
import fPeakLineInspection as p

# 調査として、DoubleやRange等の複数Inspectionを利用する場合、このファイルから呼び出す(一番下）

# その他オーダーに必要な処理はここで記載する

def Inspection_main(df_r):
    """
    主にExeから呼ばれ、ダブル関係の結果(このファイル内のbeforeとbreak)をまとめ、注文形式にして返却する関数
    引数は現状ローソク情報(逆順[直近が上の方にある＝時間降順])のみ。
    :return:doublePeakの結果をまとめて、そのまま注文できるJsonの配列にして返却する
    """
    # （０）データを取得する
    peaks_info = p.peaks_collect_main(df_r[:90], 10)  # Peaksの算出（ループ時間短縮の為、必要最低限のピーク数（＝４）を指定する）
    peaks = peaks_info['all_peaks']
    river = peaks[0]  # 最新のピーク（リバーと呼ぶ。このCount＝２の場合、折り返し直後）
    turn = peaks[1]  # 注目するポイント（ターンと呼ぶ）
    flop3 = peaks[2]  # レンジ判定用（プリフロップと呼ぶ）
    order_information = {"take_position_flag": False}  # ■何もなかった場合に返すもの（最低限の返却値）

    print("  <対象>:運用モード")
    print("  RIVER", river)
    print("  TURN ", turn)
    print("  FLOP3", flop3)
    peaks_times = "◇River:" + \
                  f.delYear(river['time']) + "-" + f.delYear(river['time_old']) + "(" + str(river['direction']) + ")" \
                                                                                                                  "◇Turn:" + \
                  f.delYear(turn['time']) + "-" + f.delYear(turn['time_old']) + "(" + str(turn['direction']) + ")" \
                                                                                                               "◇FLOP三" + \
                  f.delYear(flop3['time']) + "-" + f.delYear(flop3['time_old']) + "(" + str(flop3['direction']) + ")"

    # ターンの直後かどうか
    if peaks[0]['count'] != 2:
        print(" ターンから離れた状態。必要に応じて状態判別")
        return order_information

    # （１）beforeDoublePeakについて
    # ダブルトップ直前で、ダブルトップを形成するところを狙いに行く。TF＜0.4、RT＜0.7
    beforeDoublePeak_ans = dp.beforeDoublePeak(df_r, peaks)
    #
    # # (2)ダブルトップポイントをリバーが大きく通過している場合。TF＜0.4、RT＞1.3
    DoublePeakBreak_ans = dp.DoublePeakBreak(df_r, peaks)

    # (3)ダブルトップ（これはピークが１０個必要。過去のデータを比べて最ピークかどうかを確認したいため）
    doublePeak_ans = dp.DoublePeak_4peaks(df_r, peaks)

    # 【オーダーを統合する】  現状同時に成立しない仕様。
    if doublePeak_ans['take_position_flag']:
        order_information = doublePeak_ans
    elif DoublePeakBreak_ans['take_position_flag']:
        order_information = DoublePeakBreak_ans  # オーダー発行情報のみを返却する

    return order_information
