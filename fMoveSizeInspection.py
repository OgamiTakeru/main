import fBlockInspection as t  # とりあえずの関数集
import tokens as tk  # Token等、各自環境の設定ファイル（git対象外）
import classOanda as oanda_class
import fPeakInspection as p  # とりあえずの関数集
import fGeneric as f
import statistics
import pandas as pd

oa = oanda_class.Oanda(tk.accountIDl, tk.access_tokenl, "live")  # クラスの定義


def cal_move_size(*args):
    """
    LCのサイズ等を決定するため、周辺の大きさを確認する
    """
    # 何が正解なのかわからないけど、最初に返却値を設定しておく
    predict_line_info_list = [
        {
            "line_base_info": {},
            "same_price_lists": [],
            # strength関数で取得（その後の上書きあり）
            "strength_info": {
                "line_strength": 0,
                "line_on_num": 0,
                "same_time_latest": 0,
                "all_range_strong_line": 0,
                "remark": ""
            }
        }
    ]

    # 準備部分（表示や、ピークスの算出を行う）
    if len(args) == 2:
        # 引数が二個の場合は、Peaksが来ている為、ピークスを求める必要なし
        target_df = args[0]
        peaks = args[1]
    else:
        # 引数が１つの場合（df_rのみ）、ピークスを求める必要あり
        target_df = args[0]
        peaks_info = p.peaks_collect_main(target_df, 15)
        peaks = peaks_info["all_peaks"]
    # 状況に応じた、ピークポイントの指定  # 添え字は0=latest, 1=river, 2=turn, 3=flop3

    # データフレームの状態で、サイズ感を色々求める
    filtered_df = target_df[:15]
    print(" 検出範囲", filtered_df.iloc[0]["time_jp"], "-", filtered_df.iloc[-1]['time_jp'])
    sorted_df = filtered_df.sort_values(by='body_abs', ascending=False)
    print("  最大足,", sorted_df.iloc[0]['time_jp'], sorted_df.iloc[0]['highlow'])
    print("  最小足,", sorted_df.iloc[-1]['time_jp'], sorted_df.iloc[-1]['highlow'])
    print("  平均", sorted_df['highlow'].mean())
