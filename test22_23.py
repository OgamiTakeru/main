import tokens as tk  # Token等、各自環境の設定ファイル（git対象外）
import classOanda as classOanda
import datetime
import fAnalysis_order_Main as im
import classInspection as ci
import fPredictTurnInspection as pi


memo = "大量22_23LONG"
func = im.wrap_all_inspections
# func = im.analysis_old_flag

intest = ci.Inspection(pi.wrap_predict_turn_inspection_test,
                       True,
                       datetime.datetime(2025, 5, 22, 15, 55, 0),
                       'C:/Users/taker/OneDrive/Desktop/oanda_logs/大量22_23_m5_df.csv',
                       'C:/Users/taker/OneDrive/Desktop/oanda_logs/大量22_23_s5_df.csv',
                       600,
                       1,
                       memo + "2のみ",
                       False,
                       "")  # グラフの描画あり

# intest = ci.Inspection(pi.for_test_wrap_only1,
#                        True,
#                        datetime.datetime(2025, 5, 22, 15, 55, 0),
#                        'C:/Users/taker/OneDrive/Desktop/oanda_logs/大量22_23_m5_df.csv',
#                        'C:/Users/taker/OneDrive/Desktop/oanda_logs/大量22_23_s5_df.csv',
#                        600,
#                        1,
#                        memo + "１のみ",
#                         False)  # グラフの描画あり
#
# intest = ci.Inspection(pi.for_test_wrap_upALL,
#                        True,
#                        datetime.datetime(2025, 5, 22, 15, 55, 0),
#                        'C:/Users/taker/OneDrive/Desktop/oanda_logs/大量22_23_m5_df.csv',
#                        'C:/Users/taker/OneDrive/Desktop/oanda_logs/大量22_23_s5_df.csv',
#                        600,
#                        1,
#                        memo + "両方の方法",
#                         False)  # グラフの描画あり

