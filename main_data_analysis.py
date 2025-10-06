import datetime
import tokens as tk  # Token等、各自環境の設定ファイル（git対象外）
import classOanda as oanda_class
import fAnalysis_order_Main as am
import classCandleAnalysis as ca
import pandas as pd
import fGeneric as f


# グローバルでの宣言
oa = oanda_class.Oanda(tk.accountIDl2, tk.access_tokenl, "live")  # クラスの定義
print(oa.NowPrice_exe("USD_JPY"))
gl_start_time = datetime.datetime.now()
gl_now = datetime.datetime.now().replace(microsecond=0)  # 現在の時刻を取得
gl_now_str = str(gl_now.month).zfill(2) + str(gl_now.day).zfill(2) + "_" + \
            str(gl_now.hour).zfill(2) + str(gl_now.minute).zfill(2) + "_" + str(gl_now.second).zfill(2)

# 過去履歴のまとめ検討
date_num_view = date_num_pivot = 300
# date_num_view = 30
# date_num_pivot = 30
# 生データ送信
path = tk.folder_path + 'history.csv'
temp = pd.read_csv(path)
df_part = temp.tail(date_num_view)
lines = []
a_sum = sum(int(x) for x in df_part['res'])
max_width = max(len(str(int(x))) for x in df_part['res'])
for _, row in df_part.iterrows():
    # res_val = int(row['res']) if isinstance(row['res'], (int, float)) else row['res']
    res_val = f"{int(row['res']):>{max_width}}"
    uni_val = int(row['units'] / abs(row['units']))
    hh_mm = ":".join(f.str_to_time_hms(row['end_time']).split(":")[:2])
    if uni_val == 1:
        uni_str = "L"  # 買い（ドルを）
    else:
        uni_str = "S"  # 売り
    line = f"{res_val}, {uni_str}, {hh_mm}, {row['name_only'][:13]}, "
    lines.append(line)
# 改行で結合
lines.append(f"{a_sum:>{max_width}}, 合計, -")
output_str = "\n".join(lines)
print(output_str)
tk.line_send("■■■:", "\n", output_str)

# pivot送信
# ピボット：A列でまとめ、resは合計、woは件数（count）
path = tk.folder_path + 'history.csv'
temp = pd.read_csv(path)
df_part = temp.tail(date_num_pivot)
summary = df_part.groupby("name_only").agg(
    res_sum=("res", lambda x: int(x.sum())),
    negative_count=("res", lambda x: (x < 0).sum()),
    positive_count=("res", lambda x: (x > 0).sum())
).reset_index()
lines = []
for _, row in summary.iterrows():
    name_val = f"{row['name_only'][:13]:<13}"
    line = f"{name_val}, {row['res_sum']}, {row['positive_count']}, {row['negative_count']}"
    lines.append(line)

pivot_str = "\n".join(lines)
# print(pivot_str)
tk.line_send("", "\n", pivot_str)

# res = oa.OpenTrades_exe()
# print(res['json'])
# trades = res['json']
#
# if len(trades) == 0:
#     print("現状のポジションなし")
# else:
#     for i, item in enumerate(trades):
#         pass

