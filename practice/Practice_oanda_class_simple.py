### 情報取得のテスト

import threading  # 定時実行用
import time
import datetime
import sys
import os
# import requests
import pandas as pd
# 自作ファイルインポート
from plotly.subplots import make_subplots
import plotly.graph_objects as go
import programs.fTurnInspection as t  # とりあえずの関数集
import programs.tokens as tk  # Token等、各自環境の設定ファイル（git対象外）
import programs.classOanda as oanda_class
import programs.fGeneric as f
from time import sleep
import pytz
from dateutil import tz

# ★必須。Tokenの設定、クラスの実体化⇒これ以降、oa.関数名で呼び出し可能
print("Start")
# oa = oanda_class.Oanda(tk.accountID, tk.access_token, "practice")
oa = oanda_class.Oanda(tk.accountIDl, tk.access_tokenl, tk.environmentl)
# oa = classOanda.Oanda(tk.accountIDl, tk.access_tokenl, "live")

# # ★現在価格の取得
price_dic = oa.NowPrice_exe("USD_JPY")['data']
print("【現在価格live】", price_dic['mid'], price_dic['ask'], price_dic['bid'], price_dic['spread'])
print(oa.NowPrice_exe("USD_JPY")['data']['mid'])

euro_time = datetime.datetime(2021, 4, 1, 20, 22, 33) - datetime.timedelta(hours=9)
euro_iso = str(euro_time.isoformat()) + ".000000000Z"
param = {"granularity": "M5", "count": 10, "to": euro_iso}
print(oa.InstrumentsCandles_exe("USD_JPY", param))

print(oanda_class.str_to_time_hms(str(datetime.datetime.now().replace(microsecond=0))))
oa.OrderCancel_All_exe()  # 露払い(classesに依存せず、オアンダクラスで全部を消す）
oa.TradeAllClose_exe()  # 露払い(classesに依存せず、オアンダクラスで全部を消す）
print("↑ここまで定例")


trade_ans = oa.TradeDetails_exe(36432)  # ■■API
print(trade_ans)
# 注文テスト
# info = {
#     "units": 10,
#     "direction": 1,
#     "tp_range": 0,
#     "lc_range": 0,
#     "type": "STOP",
#     "price": 147.850,
#     "tp_range": 0.01
# }
#
# info_r = {
#     "units": 5,
#     "direction": -1,
#     "tp_range": 0,
#     "lc_range": 0,
#     "type": "MARKET",
#     "price": 145.500
# }
#
# info_r_big = {
#     "units": 14,
#     "direction": -1,
#     "tp_range": 0,
#     "lc_range": 0,
#     "type": "MARKET",
#     "price": 145.500
# }
#
# order = oa.OrderCreate_dic_exe(info)
# print(order)
# f.print_json(order['data']['json'])