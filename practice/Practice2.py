import programs.fTurnInspection as f  # とりあえずの関数集
import pandas as pd
import datetime
import matplotlib.pyplot as plt
import numpy as np
import programs.tokens as tk  # Token等、各自環境の設定ファイル（git対象外）
import programs.classOanda as oanda_class
import programs.fTurnInspection as f  # とりあえずの関数集

oa = oanda_class.Oanda(tk.accountID, tk.access_token, "practice")  # クラスの定義

jp_time = datetime.datetime(2023, 6, 15, 4, 5, 00)  # ＋１足分多めがベスト
euro_time_datetime = jp_time - datetime.timedelta(hours=9)
euro_time_datetime_iso = str(euro_time_datetime.isoformat()) + ".000000000Z"  # ISOで文字型。.0z付き）
param = {"granularity": "M5", "count": 30, "to": euro_time_datetime_iso}
df = oa.InstrumentsCandles_exe("USD_JPY", param)
# df = oa.InstrumentsCandles_multi_exe("USD_JPY", {"granularity": "M15", "count": 30}, 1)  # 直近の場合
df_r = df.sort_index(ascending=False)
print(df_r.head(5))
### ↑これより上は消さない


# チャート分析結果を取得する
inspection_condition = {
    "now_price": 150,  # 現在価格を渡す
    "data_r": df_r,  # 対象となるデータ
    "figure": {"data_r": df_r, "ignore": 1, "latest_n": 2, "oldest_n": 30, "return_ratio": 50},
    "figure3": {"data_r": df_r, "ignore": 1, "latest_n": 3, "oldest_n": 30, "return_ratio": 50},
    "macd": {"short": 20, "long": 30},
    "save": True,  # データをCSVで保存するか（検証ではFalse推奨。Trueの場合は下の時刻は必須）
    "time_str": "test",  # 記録用の現在時刻
}
ans_dic = f.inspection_candle(inspection_condition)  # 状況を検査する（買いフラグの確認）
print(" ★★★回答（Figure）")
print(ans_dic['figure_turn_result'])

