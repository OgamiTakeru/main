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
    big_move = False
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
    ts = "    "
    t6 = "      "
    # print(ts, "■変動幅検証関数")
    fixed_information = cf.information_fix(dic_args)  # DFとPeaksが必ず返却される
    # 情報の取得
    df_r = fixed_information['df_r']
    peaks = fixed_information['peaks']
    # 状況に応じた、ピークポイントの指定  # 添え字は0=latest, 1=river, 2=turn, 3=flop3

    # ■データフレームの状態で、サイズ感を色々求める
    filtered_df = df_r[:48]  # 直近3時間の場合、12×３ 36
    sorted_df = filtered_df.sort_values(by='body_abs', ascending=False)
    max_high = sorted_df["inner_high"].max()
    min_low = sorted_df['inner_low'].min()
    max_min_gap = round(max_high - min_low, 3)
    print(t6, "検出範囲", filtered_df.iloc[0]["time_jp"], "-", filtered_df.iloc[-1]['time_jp'])
    print(t6, "最大値、最小値", max_high, min_low, "差分", max_min_gap)
    print(t6, "最大足(最高-最低),", sorted_df.iloc[0]['time_jp'], sorted_df.iloc[0]['highlow'])
    print(t6, "最小足(最高-最低),", sorted_df.iloc[-1]['time_jp'], sorted_df.iloc[-1]['highlow'])
    print(t6, "平均(最高-最低)", sorted_df['highlow'].mean())
    print(t6, "最大足(Body),", sorted_df.iloc[0]['time_jp'], sorted_df.iloc[0]['body_abs'])
    print(t6, "最小足(Body),", sorted_df.iloc[-1]['time_jp'], sorted_df.iloc[-1]['body_abs'])
    print(t6, "平均(Body)", sorted_df['body_abs'].mean())

    # ■ピーク5個分の平均値を求める
    filtered_peaks = peaks[:5]
    peaks_ave = sum(item["gap"] for item in filtered_peaks) / len(filtered_peaks)
    max_index, max_peak = max(enumerate(filtered_peaks[:]), key=lambda x: x[1]["peak"])
    min_index, min_peak = min(enumerate(filtered_peaks[:]), key=lambda x: x[1]["peak"])
    # print(t6, "検出範囲ピーク",)
    # gene.print_arr(filtered_peaks, 6)
    # print(t6, peaks_ave)
    # print(t6, "変動幅検証関数　ここまで")

    # ■ピーク5個の中できわめて大きな変動がある場合（雇用統計とか、、、）
    if max_peak['gap'] >= 0.3:
        print(" きわめて大きな変動があった")
        big_move = True
    else:
        big_move = False

    # ■ピーク4個分が、全てカウント３の場合、ほぼ動いてない相場とみる（相対的なため、Pipsでは指定しない？）
    range_counter = 0
    range_flag = False
    # print(peaks[:4])
    for i, item in enumerate(peaks[:4]):
        # print("確認")
        # print(item)
        if item['count'] <= 3:
            range_counter = range_counter + 1
            # print("Out")
    # print("Count=", range_counter)
    if range_counter == 4:
        range_flag = True
        # print("直近ピーク4回が全て短い⇒動きが少ない")
    else:
        range_flag = False
        # print("直近ピークが通常")

    return {
        "range_flag": range_flag,
        "big_move": big_move,
        "inner_min_max_gap": max_min_gap
    }

    # ■サイズ間でLCの幅とかを決めたい
    # 大きさを定義する
    very_small_range = 0.07
    # small_range = 0.11
    # middle_range = 0.15
    # # 変数を定義
    # flag = True
    # high_price = 0
    # low_price = 999
    # gap = 0
    # for index, row in df_r[0:15].iterrows():
    #     # high lowデータの更新
    #     if high_price < row['inner_high']:
    #         high_price = row['inner_high']
    #     if low_price > row['inner_low']:
    #         low_price = row['inner_low']
    #
    #     # 基準を超えているかを確認
    #     gap = high_price - low_price
    #     if gap > middle_range:
    #         # middleより大きい場合は、変動が大きな場所
    #         # print("これ以前は変動大", row['time_jp'])
    #         flag = True
    #         break
    #         pass
    #     elif gap > small_range:
    #         # small 以上　middle以下は、Middle
    #         # print("これ以前は変動中", row['time_jp'])
    #         flag = False
    #     else:
    #         flag = False







