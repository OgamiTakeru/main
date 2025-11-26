
import datetime
import fAnalysis_order_Main as am
import classInspection as ci
import fTurnInspection as ti



memo = "大量22_23LONG"

intest = ci.Inspection(
                        # pred.wrap_predict_turn_inspection_test,
                       ti.MainAnalysis,
                       True,
                       datetime.datetime(2025, 5, 22, 15, 55, 0),
                       'C:/Users/taker/OneDrive/Desktop/oanda_logs/大量22_23_m5_df.csv',
                       'C:/Users/taker/OneDrive/Desktop/oanda_logs/大量22_23_s5_df.csv',
                       600,
                       1,
                       memo + "2のみ",
                       False,  # グラフの描画あり
                       "")

# intest = ci.Inspection(pi.wrap_predict_turn_inspection_test,
#                        False,
#                        datetime.datetime(2025, 6, 25, 18, 55, 0),
#                        'C:/Users/taker/OneDrive/Desktop/oanda_logs/大量22_23_m5_df.csv',
#                        'C:/Users/taker/OneDrive/Desktop/oanda_logs/大量22_23_s5_df.csv',
#                        600,
#                        1,
#                        memo + "2のみ",
#                        False, # グラフの描画あり
#                        "")
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

