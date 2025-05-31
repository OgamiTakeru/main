import tokens as tk  # Token等、各自環境の設定ファイル（git対象外）
import classOanda as classOanda
import datetime
import fAnalysis_order_Main as im
import classInspection as ci
import fPredictTurnInspection as pi



memo = "大量23_24LONG"
func = im.analysis_predict_mountain_test
# func = im.analysis_old_flag

intest = ci.Inspection(pi.for_test_wrap_only2,
                       True,
                       datetime.datetime(2025, 5, 22, 15, 55, 0),
                       'C:/Users/taker/OneDrive/Desktop/oanda_logs/大量データ_test_m5_df.csv',
                       'C:/Users/taker/OneDrive/Desktop/oanda_logs/大量データ_test_s5_df.csv',
                       600,
                       1,
                        memo + "2のみ",
                        False,  # グラフの描画あり
                       )

# intest = ci.Inspection(pi.for_test_wrap_only1,
#                        True,
#                        datetime.datetime(2025, 5, 22, 15, 55, 0),
#                        'C:/Users/taker/OneDrive/Desktop/oanda_logs/大量データ_test_m5_df.csv',
#                        'C:/Users/taker/OneDrive/Desktop/oanda_logs/大量データ_test_s5_df.csv',
#                        600,
#                        1,
#                         memo + "1のみ",
#                         False,  # グラフの描画あり
#                        )
#
#
# intest = ci.Inspection(pi.for_test_wrap_upALL,
#                        True,
#                        datetime.datetime(2025, 5, 22, 15, 55, 0),
#                        'C:/Users/taker/OneDrive/Desktop/oanda_logs/大量データ_test_m5_df.csv',
#                        'C:/Users/taker/OneDrive/Desktop/oanda_logs/大量データ_test_s5_df.csv',
#                        600,
#                        1,
#                         memo + "両方",
#                         False,  # グラフの描画あり
#                        )
#
