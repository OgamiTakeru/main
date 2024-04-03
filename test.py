import pandas as pd
import threading  # 定時実行用
import time
import datetime
import fTurnInspection as t  # とりあえずの関数集
import tokens as tk  # Token等、各自環境の設定ファイル（git対象外）
import classOanda as classOanda
import making as mk
import fGeneric as f
import fDoublePeaks as db
import classPosition as classPosition

# グローバルでの宣言
oa = classOanda.Oanda(tk.accountIDl, tk.access_tokenl, "live")  # クラスの定義
now_price_dic = oa.NowPrice_exe("USD_JPY")
now_price = now_price_dic['data']['mid']
print(now_price)
gl_start_time = datetime.datetime.now()

t ={  # オーダー２を作成
    "name": "DoublePeak-r(break)",
    "order_permission": True,
    "decision_price": river['peak'],  # ★
    "target": 0.01,  # ★
    "decision_time": 0,  #
    "tp": 0.05,
    "lc": 0.02,
    "units": 10,
    "expected_direction": 1,
    "stop_or_limit": 1,  # ★
    "trade_timeout": 1800,
    "remark": "test",
    "tr_range": 0.05,
    "lc_change": {"lc_change_exe": True, "lc_trigger_range": 0.7, "lc_ensure_range": 0.1}
}

test = db.order_finalize(t)
f.print_json(test)