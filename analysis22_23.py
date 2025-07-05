import tokens as tk  # Token等、各自環境の設定ファイル（git対象外）
import classOanda as classOanda
import datetime
import fAnalysis_order_Main as im
import classInspection as ci
import fTurnInspection as pi
import datetime
from datetime import datetime
from datetime import timedelta
import pandas as pd

import classOanda
import tokens as tk
import fGeneric as gene
import gc
import fCommonFunction as cf
import sys
import fGeneric as f
import copy


memo = "大量22_23LONG"
func = im.wrap_all_inspections
# func = im.analysis_old_flag

# intest = ci.Inspection(pi.wrap_predict_turn_inspection_test,
#                        True,
#                        datetime.datetime(2025, 5, 22, 15, 55, 0),
#                        'C:/Users/taker/OneDrive/Desktop/oanda_logs/大量22_23_m5_df.csv',
#                        'C:/Users/taker/OneDrive/Desktop/oanda_logs/大量22_23_s5_df.csv',
#                        600,
#                        1,
#                        memo + "2のみ",
#                        False, # グラフの描画あり
#                        "")

def get_data(main_path):
    """
    データを取得し、グローバル変数に格納する
    """
    # 解析のための「5分足」のデータを取得
    # gl_exist_data = True  # グローバルに変更
    # 既存の5分足データを取得
    gl_main_csv_path = main_path
    gl_s5_csv_path = 'C:/Users/taker/OneDrive/Desktop/oanda_logs/大量22_23_s5_df.csv'

    gl_d5_df = pd.read_csv(gl_main_csv_path, sep=",", encoding="utf-8")
    gl_5m_start_time = gl_d5_df.iloc[0]['time_jp']
    gl_5m_end_time = gl_d5_df.iloc[-1]['time_jp']
    gl_actual_5m_start_time = gl_d5_df.iloc[60]['time_jp']
    gl_d5_df_r = gl_d5_df.sort_index(ascending=False)  # 時系列を逆にしたものが解析用！
    print(gl_d5_df_r.head(5))
    print(gl_d5_df_r.tail(5))
    print("5分足での取得時刻は", gl_5m_start_time, "-", gl_5m_end_time, len(gl_d5_df_r), "行")
    print("実際の解析時間は", gl_d5_df.iloc[60]['time_jp'], "-", gl_5m_end_time)
    # 既存の5秒足データを取得
    gl_s5_df = pd.read_csv(gl_s5_csv_path, sep=",", encoding="utf-8")
    start_s5_time = gl_s5_df.iloc[0]['time_jp']
    end_s5_time = gl_s5_df.iloc[-1]['time_jp']
    print("検証用データ")
    print("検証時間の総取得期間は", start_s5_time, "-", end_s5_time, len(gl_s5_df), "行")

    # 5秒足のデータが、5分足に対して多めに取れ（5000×Nの単位のため、最大4999の不要行がある。現実的にはなぜかもっと出る）、微笑に無駄なループが発生
    # するため、検証期間の先頭をそろえる　⇒　データフレームを、5秒足を左側（基準）、5分足を右側と考え、左外部結合を行う
    d5_df_for_merge = gl_d5_df.rename(columns=lambda x: f"{x}_y")  # 結合する側の名前にあらかじめ＿ｙをつけておく(予期せぬtime_xができるため）
    gl_inspection_base_df = pd.merge(gl_s5_df, d5_df_for_merge, left_on='time_jp', right_on='time_jp_y',
                                     how='left')
    # value2がNaNでない最初のインデックスを取得
    first_non_nan_index = gl_inspection_base_df['time_y'].first_valid_index()
    # インデックス以降のデータを取得
    gl_inspection_base_df = gl_inspection_base_df.loc[first_non_nan_index:]
    # テスト用
    # gl_inspection_base_df = gl_inspection_base_df[1286104:1779590]  # ここでは5秒足の足数になるため、広めでOK（解析機関
    # gl_inspection_base_df = gl_inspection_base_df.reset_index(drop=True)
    # print(gl_inspection_base_df.head(5))
    # print(gl_inspection_base_df.tail(5))
    # gl_actual_5m_start_time = gl_inspection_base_df.iloc[0]['time_jp']
    # gl_actual_end_time = gl_inspection_base_df.iloc[-1]['time_jp']
    # tk.line_send("test ", "【検証期間】", gl_actual_5m_start_time, "-", gl_actual_end_time)

    # インデックスを振りなおす（OK？）
    gl_inspection_base_df = gl_inspection_base_df.reset_index(drop=True)
    # 実際の調査開始時間と終了時間を取得する
    gl_actual_start_time = gl_inspection_base_df.iloc[0]['time_jp']
    gl_actual_end_time = gl_inspection_base_df.iloc[-1]['time_jp']
    print("マージされたデータフレームの行数", len(gl_inspection_base_df))
    print(gl_inspection_base_df.tail(5))

    return gl_d5_df

def for_analysis(df):
    # time_jpが '2025/07/03 05:50:00' のような文字列なら、まずdatetimeに変換
    df['time_jp'] = pd.to_datetime(df['time_jp'])

    # 時刻（時単位）で丸める（例: 05:50 → 05:00）
    df['rounded_hour'] = df['time_jp'].dt.floor('h')

    # high と low の差分を計算
    df['diff'] = df['high'] - df['low']

    # 日付と時（hour）だけのカラムを作成
    df['date'] = df['rounded_hour'].dt.date
    df['hour'] = df['rounded_hour'].dt.hour

    # 日付と時刻ごとに平均を取る
    daily_hourly_diff = df.groupby(['date', 'hour'])['diff'].mean().reset_index()

    # 結果表示（例: 7月1日4時 0.5）
    print(daily_hourly_diff)

    # 時（hour）ごとに平均差分を計算
    hourly_avg_diff = daily_hourly_diff.groupby('hour')['diff'].mean().reset_index()

    # 結果表示（例: 4時 0.7）
    print("時間だけのやつ")
    print(hourly_avg_diff)
    return hourly_avg_diff


df = get_data('C:/Users/taker/OneDrive/Desktop/oanda_logs/大量22_23_m5_df.csv')
res1 = for_analysis(df)

df = get_data('C:/Users/taker/OneDrive/Desktop/oanda_logs/大量データ_test_m5_df.csv')
res2 = for_analysis(df)

print("22")
print(res1)
print("23")
print(res2)
