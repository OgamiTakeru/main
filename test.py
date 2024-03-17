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

double_bef = {"river_turn_ratio": 0.61, "turn_flop_ratio": 0.5, "count": 2, "gap": 0.03, "margin": 0.008, "tg": 0.12, "tc": 15, "tp": 1.5, "lc":1.5}
params_arr = [  # t_type は順張りか逆張りか
    double_bef['river_turn_ratio']=0.66,
    double_bef
]

print(params_arr)