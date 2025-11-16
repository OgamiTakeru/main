import tokens as tk  # Token等、各自環境の設定ファイル（git対象外）
import datetime
import fAnalysis_order_Main as am
import classInspection as ci
import fTurnInspection as ti
import os

import datetime
import sys
import fTurnInspection as ti

# main.py からの引数（日付文字列）
# year = int(sys.argv[1])
# month = int(sys.argv[2])
dt_str = sys.argv[1]

# datetime に変換
dt = datetime.datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")

file_name_head = "25_short"
file_name_head = "25_harf"
file_name_head = "25_long"
# file_name_head = "2025_10"
# # file_name_head = "2025_9"
# file_name_head = "2025_6_7"
# file_name_head = "2025_3_5"
# file_name_head = "2025_5"
# file_name_head = "2025_4"
intest = ci.Inspection(#pred.wrap_predict_turn_inspection_test,
                        ti.turn_analisys,  # インスタンス化前のクラスを渡す
                        False,
                        # True,
                        dt,  #ここが最後
                        tk.folder_path + file_name_head + "_test_h1_df.csv",
                        tk.folder_path + file_name_head + "_test_m5_df.csv",
                        tk.folder_path + file_name_head + "_test_s5_df.csv",
                       3400,  # 1か月単位でやる場合、ここは3400
                       2,  # 1か月単位でやる場合、ここは2
                       " テスト" + file_name_head,
                       False,  # グラフの描画あり
                       "",
                        False,  # キャッシュの保存
                        # True  # キャッシュの保存
                       )

