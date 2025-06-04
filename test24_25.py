import tokens as tk  # Token等、各自環境の設定ファイル（git対象外）
import classOanda as classOanda
import datetime
import fAnalysis_order_Main as im
import classInspection as ci
import fPredictTurnInspection as pi

memo = "少量24_25 "
func = im.analysis_predict_mountain_test
# func = im.analysis_old_flag

loop = [
    datetime.datetime(2024, 10, 3, 9, 25, 0),  # いいマイナスデータ
    datetime.datetime(2024, 10, 10, 9, 25, 0),  # いいマイナスデータ
    datetime.datetime(2023, 9, 23, 23, 40, 6),  # Break系のいいマイナスデータ
    datetime.datetime(2023, 3, 6, 23, 40, 6),  # いいマイナスデータ
    datetime.datetime(2022, 2, 6, 23, 40, 6),  # いいマイナスデータ
]
# single_exe = True
single_exe = False

if single_exe:
    intest = ci.Inspection(pi.for_test_wrap_only2,
                           False,
                           # datetime.datetime(2024, 10, 3, 9, 25, 0),  # いいマイナスデータ
                           #  datetime.datetime(2024, 10, 10, 9, 25, 0),  # いいマイナスデータ
                           #  datetime.datetime(2023, 9, 10, 23, 40, 6),  # 謎の飛びデータ
                           #  datetime.datetime(2023, 9, 23, 23, 40, 6),  # Break系のいいマイナスデータ
                            datetime.datetime(2023, 3, 6, 23, 40, 6),  # いいマイナスデータ
                           #  datetime.datetime(2022, 2, 6, 23, 40, 6),  # いいマイナスデータ
                           # datetime.datetime(2022, 2, 21, 23, 40, 6),  # いいマイナスデータ
                           'C:/Users/taker/OneDrive/Desktop/oanda_logs/202503_m5_df.csv',
                           'C:/Users/taker/OneDrive/Desktop/oanda_logs/202503_s5_df.csv',
                           600,
                           1,
                           " テスト" + memo,
                           True,  # グラフの描画あり
                           )
else:
    tk.line_send("検証期間 ここから連続↓")
    i = 1
    for item in loop:
        intest = ci.Inspection(pi.for_test_wrap_only2,
                               False,
                               item,  # いいマイナスデータ
                               'C:/Users/taker/OneDrive/Desktop/oanda_logs/202503_m5_df.csv',
                               'C:/Users/taker/OneDrive/Desktop/oanda_logs/202503_s5_df.csv',
                               600,
                               1,
                               " テスト" + memo,
                               True,  # グラフの描画あり
                               )
        print(i, "つ目が終了")
    tk.line_send("検証期間 ここまで連続↑")




