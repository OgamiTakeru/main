import threading  # 定時実行用
import time
import tokens as tk  # Token等、各自環境の設定ファイル（git対象外）
import classOanda as classOanda
import classPosition as classPosition
import fGeneric as gene
import datetime
import fCommonFunction as cm
import fAnalysis_order_Main as im
import math
from decimal import Decimal, ROUND_DOWN
import glob
import os
import gc
import threading  # 定時実行用
import time
import tokens as tk  # Token等、各自環境の設定ファイル（git対象外）
import classOanda as classOanda
import classPosition as classPosition
import fGeneric as gene
import datetime
import fCommonFunction as cm
import fAnalysis_order_Main as im
import math
from decimal import Decimal, ROUND_DOWN
import glob
import os
import gc
import oandapyV20.endpoints.transactions as trans

# ■■■本文開始
# モードの設定と使うOandaモードの設定(oaの定義）
fx_mode = 0  # 1=practice, 0=Live
if fx_mode == 1:  # practice
    oa = classOanda.Oanda(tk.accountID, tk.access_token, tk.environment)  # インスタンス生成
    is_live = False
else:  # Live
    oa = classOanda.Oanda(tk.accountIDl, tk.access_tokenl, tk.environmentl)  # インスタンス生成
    is_live = True

# 現在価格の取得
now_price_dic = oa.NowPrice_exe("USD_JPY")
now_price = now_price_dic['data']['mid']
print(now_price)
# 現在時間（通常と同じ形式）を取得
gl_start_time = datetime.datetime.now()
d5_df = oa.InstrumentsCandles_multi_exe("USD_JPY", {"granularity": "M5", "count": 50}, 1)
d5_df = d5_df['data']
now_time = d5_df.iloc[-1]['time_jp']
print(now_time)

# クラスの定義
order_ans = oa.OrderDetails_exe(72519)  # ■■API
print("ORDER:", order_ans)

trade_ans = oa.TradeDetails_exe(72520)
print("TRADE", trade_ans)

print("TRANSACTION")
print(oa.get_transaction_single(72520))