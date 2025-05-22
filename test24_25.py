import tokens as tk  # Token等、各自環境の設定ファイル（git対象外）
import classOanda as classOanda
import datetime
import fAnalysis_order_Main as im
import classInspection as ci

memo = "少量24_25 "
# func = im.analysis_predict_mountain_test
func = im.analysis_old_flag

intest = ci.Inspection(func,
                       True,
                       datetime.datetime(2025, 5, 22, 15, 55, 0),
                       'C:/Users/taker/OneDrive/Desktop/oanda_logs/202503_m5_df.csv',
                       'C:/Users/taker/OneDrive/Desktop/oanda_logs/202503_s5_df.csv',
                       600,
                       1,
                       " TEST直近分でテスト" + memo
                       )

