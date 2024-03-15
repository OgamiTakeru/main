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

df_ans = oa.InstrumentsCandles_multi_exe("USD_JPY", {"granularity": "M5", "count": 10}, 1)
df = df_ans['data'].head(2)
latest = df.iloc[-1]['time']
latest_jp = df.iloc[-1]['time_jp']
print(latest, latest_jp)

params = {
    "granularity": "S5",
    "count": 1000,  # 60は10分分。240が正規
    "from": latest,
}
i_df = oa.InstrumentsCandles_multi_exe("USD_JPY", params, 1)

print(df.head(2))
print(i_df['data'].head(5))