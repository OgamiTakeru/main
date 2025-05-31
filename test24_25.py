import tokens as tk  # Token等、各自環境の設定ファイル（git対象外）
import classOanda as classOanda
import datetime
import fAnalysis_order_Main as im
import classInspection as ci
import fPredictTurnInspection as pi

memo = "少量24_25 "
func = im.analysis_predict_mountain_test
# func = im.analysis_old_flag

# intest = ci.Inspection(func,
#                        True,
#                        datetime.datetime(2025, 5, 22, 15, 55, 0),
#                        'C:/Users/taker/OneDrive/Desktop/oanda_logs/202503_m5_df.csv',
#                        'C:/Users/taker/OneDrive/Desktop/oanda_logs/202503_s5_df.csv',
#                        600,
#                        1,
#                        " ＊＊＊" + memo
#                        )

intest = ci.Inspection(pi.for_test_wrap_only2,
                       False,
                       # datetime.datetime(2024, 10, 3, 9, 25, 0),  # いいマイナスデータ
                       #  datetime.datetime(2024, 10, 10, 9, 25, 0),  # いいマイナスデータ
                       #  datetime.datetime(2023, 9, 10, 23, 40, 6),  # 謎の飛びデータ
                        datetime.datetime(2023, 9, 23, 23, 40, 6),  # Break系のいいマイナスデータ
                       'C:/Users/taker/OneDrive/Desktop/oanda_logs/202503_m5_df.csv',
                       'C:/Users/taker/OneDrive/Desktop/oanda_logs/202503_s5_df.csv',
                       600,
                       1,
                       " テスト" + memo,
                       True,  # グラフの描画あり
                       )

