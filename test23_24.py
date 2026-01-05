import datetime
import fAnalysis_order_Main as am
import classInspection as ci
import fTurnInspection as ti
import os


memo = "25 LONG"

loop = [
    datetime.datetime(2024, 10, 3, 9, 25, 0),  # いいマイナスデータ
    # datetime.datetime(2024, 10, 10, 9, 25, 0),  # いいマイナスデータ
    datetime.datetime(2023, 9, 23, 23, 40, 6),  # Break系のいいマイナスデータ
    # datetime.datetime(2023, 3, 6, 23, 40, 6),  # いいマイナスデータ
    datetime.datetime(2022, 2, 6, 23, 40, 6),  # いいマイナスデータ
]
mode = 1  # 任意期間　または、　25年半年
# mode = 2  # 25年ちょっと
# mode = 4  # ループ
print("test")
path = "C:/Users/taker/OneDrive/Desktop/oanda_logs/"

file_name_head = "25_short"
file_name_head = "25_harf"
file_name_head = "25_long"
# file_name_head = "2025_10"
# # file_name_head = "2025_9"
# file_name_head = "2025_6_7"
# file_name_head = "2025_3_5"
# file_name_head = "2025_5"
# file_name_head = "2025_4"
file_name_head = "2024_12_1"
file_name_head = "2024_9_4"
intest = ci.Inspection(#pred.wrap_predict_turn_inspection_test,
                        ti.MainAnalysis,  # インスタンス化前のクラスを渡す
                        False,
                        # True,
                       #  datetime.datetime(2023, 9, 10, 23, 40, 6),  # 謎の飛びデータ
                       #  datetime.datetime(2023, 9, 23, 23, 40, 6),  # Break系のいいマイナスデータ
                        datetime.datetime(2026, 1, 5, 17, 30, 55), #ここが最後
                        path + file_name_head + "_test_h1_df.csv",
                        path + file_name_head + "_test_m5_df.csv",
                        path + file_name_head + "_test_s5_df.csv",
                       1000,  # 1か月単位でやる場合、ここは3400  数日間の場合は750位でいい
                       1,  # 1か月単位でやる場合、ここは2
                       " テスト" + file_name_head,
                       True,  # グラフの描画あり
                       "",
                        True,  # キャッシュの保存
                        # True  # キャッシュの保存
                        False  # キャッシュの利用をするかどうか
                       )

