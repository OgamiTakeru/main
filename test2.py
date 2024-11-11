import pandas as pd

import datetime
import tokens as tk  # Token等、各自環境の設定ファイル（git対象外）
import classOanda as classOanda
import classPosition as classPosition
import fGeneric as gene
import datetime
import fInspection_order_Main as im
import math
from decimal import Decimal, ROUND_DOWN
import glob
import os

# グローバルでの宣言
oa = classOanda.Oanda(tk.accountIDl, tk.access_tokenl, "live")  # クラスの定義
now_price_dic = oa.NowPrice_exe("USD_JPY")
now_price = now_price_dic['data']['mid']
print(now_price)
gl_start_time = datetime.datetime.now()
# クラスの定義
classes = []
for ic in range(3):
    # 複数のクラスを動的に生成する。クラス名は「C＋通し番号」とする。
    # クラス名を確定し、クラスを生成する。
    new_name = "c" + str(ic)
    classes.append(classPosition.order_information(new_name, oa, False))  # 順思想のオーダーを入れるクラス

exe_orders = [
    {'decision_price': 153.866, 'decision_time': '2024/11/11 19:05:00', 'direction': 1, 'expected_direction': 1, 'lc': 1, 'lc_change': [],
    'lc_price': "153.346", 'lc_range': 0.3300000000000125, 'name': 'カウンター Short: フラッグ形状(上側下落) Long フラッグ形状(上側下落)  LONG初成立 SHORT初成立3',
     'order_permission': True, 'position_margin': 0.038, 'price': 153.67600000000002,
     'priority': 3, 'stop_or_limit': 1, 'target': 153.67600000000002,
     'target_price': 153.67600000000002, 'tp': 0.53, 'tp_price': 154.206,
     'tp_range': 0.53, 'trade_timeout_min': 60, 'type': 'STOP', 'units': 1000}
]
classes[0].order_plan_registration(exe_orders[0])