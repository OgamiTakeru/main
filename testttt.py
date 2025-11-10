import tokens as tk  # Token等、各自環境の設定ファイル（git対象外）
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

intest = ci.Inspection(#pred.wrap_predict_turn_inspection_test,
                        ti.turn_analisys,  # インスタンス化前のクラスを渡す
                        # True,
                        True,
                       #  datetime.datetime(2023, 9, 10, 23, 40, 6),  # 謎の飛びデータ
                       #  datetime.datetime(2023, 9, 23, 23, 40, 6),  # Break系のいいマイナスデータ
                        datetime.datetime(2025, 11, 6, 12, 0, 6),  #ここが最後
                       #  'C:/Users/taker/OneDrive/Desktop/oanda_logs/25_short_test_h1_df.csv',
                       # 'C:/Users/taker/OneDrive/Desktop/oanda_logs/25_short_test_m5_df.csv',
                       # 'C:/Users/taker/OneDrive/Desktop/oanda_logs/25_short_test_s5_df.csv',
                       #  'C:/Users/taker/OneDrive/Desktop/oanda_logs/25_harf_test_h1_df.csv',
                       #  'C:/Users/taker/OneDrive/Desktop/oanda_logs/25_harf_test_m5_df.csv',
                       #  'C:/Users/taker/OneDrive/Desktop/oanda_logs/25_harf_test_s5_df.csv',
                        'C:/Users/taker/OneDrive/Desktop/oanda_logs/25_long_test_h1_df.csv',
                        'C:/Users/taker/OneDrive/Desktop/oanda_logs/25_long_test_m5_df.csv',
                        'C:/Users/taker/OneDrive/Desktop/oanda_logs/25_long_test_s5_df.csv',
                       5000,
                       3,
                       " テスト" + memo,
                       False,  # グラフの描画あり
                       ""
                       )