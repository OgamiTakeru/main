import pandas as pd
import threading  # 定時実行用
import time
import datetime
import fTurnInspection as t  # とりあえずの関数集
import tokens as tk  # Token等、各自環境の設定ファイル（git対象外）
import classOanda as classOanda
import making as mk
import fGeneric as f
import fDoublePeaks as dp
import classPosition as classPosition
import fPeakLineInspection as p
import fRangeInspection as ri

# グローバルでの宣言
oa = classOanda.Oanda(tk.accountIDl, tk.access_tokenl, "live")  # クラスの定義
now_price_dic = oa.NowPrice_exe("USD_JPY")
now_price = now_price_dic['data']['mid']
print(now_price)
gl_start_time = datetime.datetime.now()
# クラスの定義
classes = []
for i in range(3):
    # 複数のクラスを動的に生成する。クラス名は「C＋通し番号」とする。
    # クラス名を確定し、クラスを生成する。
    new_name = "c" + str(i)
    classes.append(classPosition.order_information(new_name, oa))  # 順思想のオーダーを入れるクラス



# data = {
#     "decision_price": 150,
#     "units": 2,
#     "expected_direction": 1,
#     "ask_bid": 1,
#     "start_price": 155.950,
#     "grid": 0.02,
#     "num": 3,
#     "end_price": 156.0,
#     "type": "STOP"
# }
#
# print("test")
# ans = dp.make_trid_order(data)
# f.print_arr(ans['exe_orders'])
# print(" オーダー実行")
# for n in range(len(ans['exe_orders'])):
#     print(" No." + str(n))
#     res_dic = classes[n].order_plan_registration(ans['exe_orders'][n])  #
#
