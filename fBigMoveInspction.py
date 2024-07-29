import datetime  # 日付関係
import json
import numpy as np
import fBlockInspection as fTurn
import fGeneric as f
import fRangeInspection as ri


def big_move(df_r):

    print(" BIG MOVE INSPECTION")
    # 範囲を絞る
    time_range_foot = 70  # 直近N足分の検証期間
    df_r = df_r[:time_range_foot]  # 新しい範囲の検証
    df_r = df_r.reset_index(drop=True)
    print(" DataFrame")
    print(df_r.head(3))
    print(df_r.tail(3))
    max_price = df_r['high'].max()
    max_price_time = df_r[df_r['high'] == max_price]['time_jp'].values[0]
    max_price_index = df_r.index[df_r['high'] == max_price].tolist()[0]
    min_price = df_r['low'].min()
    min_price_time = df_r[df_r['low'] == min_price]['time_jp'].values[0]
    min_price_index = df_r.index[df_r['low'] == min_price].tolist()[0]
    latest_time = df_r.iloc[0]['time_jp']
    oldest_time = df_r.iloc[-1]['time_jp']
    print(" ", max_price, max_price_time, max_price_index)
    print("  ",min_price, min_price_time, min_price_index, latest_time, oldest_time)

    print(" ■DataFrametest")
    df_r_min = df_r.iloc[min_price_index-5:]
    print(df_r_min.head(3))
    print(df_r_min.tail(3))

    ri.find_lines_mm(df_r_min)

    # 最高値と最安値を求める

