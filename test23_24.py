
import datetime
import fAnalysis_order_Main as am
import classInspection as ci
import fTurnInspection as ti




memo = "大量23_24LONG"

intest = ci.Inspection(
                        # pred.wrap_predict_turn_inspection_test,
                       ti.turn_analisys,
                       False,
                       datetime.datetime(2024, 10, 6, 15, 55, 0),
                       'C:/Users/taker/OneDrive/Desktop/oanda_logs/大量データ_test_m5_df.csv',
                       'C:/Users/taker/OneDrive/Desktop/oanda_logs/大量データ_test_s5_df.csv',
                       5000,
                       10,
                       memo,
                       False,
                       ""
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
