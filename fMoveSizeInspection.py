import fBlockInspection as t  # とりあえずの関数集
import tokens as tk  # Token等、各自環境の設定ファイル（git対象外）
import classOanda as oanda_class
import fPeakInspection as p  # とりあえずの関数集
import fGeneric as f
import statistics
import pandas as pd
import fGeneric as gene
import fCommonFunction as cf

oa = oanda_class.Oanda(tk.accountIDl, tk.access_tokenl, "live")  # クラスの定義


def cal_move_size(dic_args):
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
    print("   ■変動幅検証関数")
    fixed_information = cf.information_fix(dic_args)  # DFとPeaksが必ず返却される
    # 情報の取得
    df_r = fixed_information['df_r']
    peaks = fixed_information['peaks']
    # 状況に応じた、ピークポイントの指定  # 添え字は0=latest, 1=river, 2=turn, 3=flop3

    # データフレームの状態で、サイズ感を色々求める
    filtered_df = df_r[:15]
    print("     検出範囲", filtered_df.iloc[0]["time_jp"], "-", filtered_df.iloc[-1]['time_jp'])
    sorted_df = filtered_df.sort_values(by='body_abs', ascending=False)
    max_high = sorted_df["high"].max()
    min_low = sorted_df['low'].min()
    max_min_gap = round(max_high - min_low, 3)
    print("     最大足,", sorted_df.iloc[0]['time_jp'], sorted_df.iloc[0]['highlow'])
    print("     最小足,", sorted_df.iloc[-1]['time_jp'], sorted_df.iloc[-1]['highlow'])
    print("     平均", sorted_df['highlow'].mean())
    print("     最大値、最小値", max_high, min_low, "差分", max_min_gap)

    # ピーク5個分の平均値を求める
    filtered_peaks = peaks[:5]
    print("     検出範囲ピーク",)
    gene.print_arr(filtered_peaks)
    peaks_ave = sum(item["gap"] for item in filtered_peaks) / len(filtered_peaks)
    max_index, max_peak = max(enumerate(filtered_peaks[:]), key=lambda x: x[1]["peak"])
    min_index, min_peak = min(enumerate(filtered_peaks[:]), key=lambda x: x[1]["peak"])
    print("     ", peaks_ave)
    print("     変動幅検証関数　ここまで")

