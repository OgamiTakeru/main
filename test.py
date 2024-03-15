import pandas as pd
import datetime
import fTurnInspection as t  # とりあえずの関数集
import tokens as tk  # Token等、各自環境の設定ファイル（git対象外）
import classOanda as oanda_class
import making as mk
import fGeneric as f

# グローバルでの宣言
oa = oanda_class.Oanda(tk.accountIDl, tk.access_tokenl, "live")  # クラスの定義
now_price_dic = oa.NowPrice_exe("USD_JPY")
now_price = now_price_dic['data']['mid']
print(now_price)
gl_start_time = datetime.datetime.now()

now_price = 148.35
data = {
    "units": 1,
    "direction": 1,
    "price": now_price,
    "tp_price": now_price + 0.06,
    "lc_price": now_price - 0.06,
    "tp_range": 0.01,
    # "lc_range": 0.01,
    "type": "STOP",

}
oa.OrderCreate_dic_exe(data)


