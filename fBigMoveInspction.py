import datetime  # 日付関係
import json
import numpy as np
import fBlockInspection as fTurn
import fGeneric as f
import fRangeInspection as ri


def inspection_df(df_r) -> dict:
    """
    param df_r: dataframe
    受け取ったデータフレームについて、
    最大値（とその時間）、最小値等を産出して返却。
    """

    # 　直近の最高値等を産出する。
    max_price = df_r['high'].max()
    max_price_time = df_r[df_r['high'] == max_price]['time_jp'].values[0]
    max_price_index = df_r.index[df_r['high'] == max_price].tolist()[0]
    min_price = df_r['low'].min()
    min_price_time = df_r[df_r['low'] == min_price]['time_jp'].values[0]
    min_price_index = df_r.index[df_r['low'] == min_price].tolist()[0]
    latest_time = df_r.iloc[0]['time_jp']
    oldest_time = df_r.iloc[-1]['time_jp']
    max_min_gap = max_price - min_price
    now_min_gap = df_r.iloc[0]['close'] - min_price
    latest_ratio_from_min = round(now_min_gap / max_min_gap, 3)  #     この区画で最小値から何パーセントの高さに、最新価格（≒現在価格）が存在するか。

    # 表示用
    # print(" ", max_price, max_price_time, max_price_index)
    # print("  ", min_price, min_price_time, min_price_index, latest_time, oldest_time)

    return {
        "max_price": max_price,
        "max_price_time": max_price_time,
        "min_price": min_price,
        "min_price_time": min_price_time,
        "max_min_gap": max_price - min_price,
        "latest_time": latest_time,
        "oldest_time": oldest_time,
        "latest_ratio_from_min": latest_ratio_from_min
    }


def big_move(df_r):
    print(" BIG MOVE INSPECTION")
    # 範囲を絞る
    time_range_foot = 70  # 直近N足分の検証期間
    df_r = df_r[:time_range_foot]  # 新しい範囲の検証

    # 全期間で情報を収集する
    all_range = inspection_df(df_r)
    # 直近はMinかMaxかどっちかを記録しておく
    if f.str_to_time(all_range['max_price_time']) > f.str_to_time(all_range['min_price_time']):
        latest_peak_time = all_range['max_price_time']
        latest_peak_price = all_range['max_price']
        latest_remark = "MAX"
    else:
        latest_peak_time = all_range['min_price_time']
        latest_peak_price = all_range['min_price']
        latest_remark = "MIN"
    print(all_range)
    print(all_range['max_price'], all_range['min_price'])
    gap_info = f.cal_str_time_gap(all_range['max_price_time'], all_range['min_price_time'])
    print(gap_info['gap_abs'], "が時間差")
    print("直近の時刻", all_range['latest_time'])
    print("直近の最大or最小", latest_remark, latest_peak_time)
    gap_from_latest_time = f.cal_str_time_gap(all_range['latest_time'], latest_peak_time)
    print("直近の時刻から直近のピークまでの時間差", gap_from_latest_time['gap_abs'])

    print("test")
    #  各ブロックでの情報を確認する
    roop = 3
    width = int(time_range_foot / roop)
    kara = 0
    made = width
    ans = []
    for i in range(roop):
        print("ループ", i, "回目　", kara, made, )

        # 各セクションで情報の取得
        df_temp = df_r[kara:made]
        each_ans = inspection_df(df_temp)
        # 計算
        # 1 ラップ率
        each_ans['gap_ratio'] = round(each_ans['max_min_gap'] / all_range['max_min_gap'], 2)  # 要素を追加
        print(" 各々", each_ans)
        print(" ラシオ", each_ans['gap_ratio'], each_ans['max_min_gap'], all_range['max_min_gap'])
        # 統合
        ans.append(each_ans)


        # 次の範囲へ
        kara = made
        made = kara + width + 1

    # 最高値の場所を絞り込む
    for i, item in enumerate(ans):
        print("比較対象", item['oldest_time'], item['latest_time'])
        min_section = max_section = 0  # 念のための初期値設定
        if item['max_price'] == all_range['max_price']:
            max_section = i
            max_section_range = item['gap_ratio']
            if max_section == 0:
                max_section_remark = "直近MAX"
            elif max_section == 1:
                max_section_remark ="中央MAX"
            else:
                max_section_remark = "過去MAX"
            # print("最大値はセクション", i)
        if item['min_price'] == all_range['min_price']:
            min_section = i
            min_section_range = item['gap_ratio']
            if min_section == 0:
                min_section_remark = "直近MIN"
            elif min_section == 1:
                min_section_remark ="中央MIN"
            else:
                min_section_remark = "過去MIN"
            # print("最小値はセクション", i)

    # まとめ
    print("まとめ",  all_range['oldest_time'], all_range['latest_time'])
    print(max_section_remark, max_section_range, min_section_remark,min_section_range)
    print(" 占有率", ans[2]['gap_ratio'], ans[1]['gap_ratio'], ans[0]['gap_ratio'])

    # # 判定
    # if min_section == 2 and (max_section == 1 or max_section == 0):
    #     # 上がりが続いている場合 （直近がMax）
    #
    # elif max_section == 2 and (min_section == 1 or min_section == 0):
    #     # 下がり続けている場合　（直近がMin）





