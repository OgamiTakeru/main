### 情報取得のテスト

import threading  # 定時実行用
import time
import datetime
import sys
import os
# import requests
import pandas as pd
# 自作ファイルインポート
import tokens as tk  # Token等、各自環境の設定ファイル（git対象外）
import classOanda as oanda_class

# ★必須。Tokenの設定、クラスの実体化⇒これ以降、oa.関数名で呼び出し可能
print("Start")
oa = oanda_class.Oanda(tk.accountID, tk.access_token, "practice")
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
# oa.OrderCancel_All_exe()  # 露払い(classesに依存せず、オアンダクラスで全部を消す）
# oa.TradeAllClose_exe()  # 露払い(classesに依存せず、オアンダクラスで全部を消す）
print("↑ここまで定例")


# 注文テスト
info = {
    "units": 9,
    "direction": 1,
    "tp_range": 0,
    "lc_range": 0,
    "type": "STOP",
    "price": 146.000
}
info_market = {
    "units": 6,
    "direction": 1,
    "tp_range": 0.04,
    "lc_range": 0,
    "type": "MARKET",
    "price": 146.883
}

info_r = {
    "units": 19,
    "direction": -1,
    "tp_range": 0,
    "lc_range": 0,
    "type": "MARKET",
    "price": 145.500
}

info_r_big = {
    "units": 14,
    "direction": -1,
    "tp_range": 0,
    "lc_range": 0,
    "type": "MARKET",
    "price": 145.500
}

###APIレスポンステスト
# print(oa.OrderDetails_exe(38116))
print(oa.TradeDetails_exe(38528))
print()
test = oa.TradeClose_exe(38528,None)
print(test)
print()
f.print_json(test['data_json'])



#
#  (5)部分解消の場合
# oa.OrderCancel_All_exe()  # 露払い(classesに依存せず、オアンダクラスで全部を消す）
# oa.TradeAllClose_exe()
# print("■■■■■（5）")
# print("■■通常オーダー作成")
# print("■オーダー１")
# order = oa.OrderCreate_dic_exe(info)
# order_id = order['data']['order_id']
# position_id = order['data']['json']['orderFillTransaction']['id']
# # f.print_json(order['data']['json'])
# f.print_json(order['data']['json']['orderFillTransaction']['id'])
# print("■部分解消オーダー")
# ans = oa.TradeClose_exe(position_id,{"units": "6"})
# # f.print_json(ans["data_json"])
#
# print("部分解消後、オーダー１はどうなるか")
# order_detail = oa.OrderDetails_exe(order_id)
# f.print_json(order_detail)
# print("部分解消オーダー オーダーJson")
# f.print_json(ans['data_json'])
# print("部分解消オーダー　トレード")
# details = oa.TradeDetails_exe(position_id)
# f.print_json(details)
# print(ans['data_json']['orderFillTransaction']['tradeReduced'])
# print(ans['data_json']['orderFillTransaction']['tradeReduced']['tradeID'])
# print(ans['data_json']['orderFillTransaction']['tradeReduced']['units'])  # 減らした分
# print(ans['data_json']['orderFillTransaction']['tradeReduced']['realizedPL'])  # 減らした分の確定損益
# print(ans['data_json']['orderFillTransaction']['tradeReduced']['price'])  # 減らしたタイミングの価格

# 必ず
# oa.OrderCancel_All_exe()  # 露払い(classesに依存せず、オアンダクラスで全部を消す）
# oa.TradeAllClose_exe()













# oa.OrderCancel_All_exe()  # 露払い(classesに依存せず、オアンダクラスで全部を消す）
# oa.TradeAllClose_exe()  # 露払い(classesに依存せず、オアンダクラスで全部を消す）
# print(" オーダー実行↓")
# order = oa.OrderCreate_dic_exe(plan)
# order_id = 33599  #order['data']['order_id']
# print("オーダー結果↓")
# # print(order)
# states = oa.OrderDetailsState_exe(order_id)
# print("オーダーDetail結果↓")
# print(states)
# position_id = states['data']['position_id']
# ans = oa.TradeClose_exe(position_id,{"units":"6"})
# print("オーダー部分クローズ結果")
# print(ans)
# print("")
# print(ans['data_json']['orderCreateTransaction']['tradeClose'])
# #{'units': '6', 'tradeID': '33527'}

# print("■部分決済後オーダー確認")
# state = oa.OrderDetails_exe(order_id)
# print(state)
# #
# print("■")
# oa.TradeClose_exe(position_id,{"units": "2"})
# states = oa.OrderDetailsState_exe(order_id)
# print(states)




# states = oa.OrderDetailsState_exe(0)
# print(states)
# if states['error'] != 0:
#     print("エラー")
# else:
#     data = states['data']
#     print(data)
#     if data['order_state'] == "FILLED" and data['position_state'] == "CLOSED":
#         # 即時決済されている＝いわゆる両建て状態で一瞬でキャンセルされた可能性
#         print("両建て系の為、再度オーダーが必要")
#     else:
#         print("正常にオーダーが入っています")
#
#
#
# print("↑ここまでオーダー")

# エラーテスト用（API）
# data = {
#     "stopLoss": {"price": str(139.99), "timeInForce": "GTC"},
# }
# test = oa.TradeCRCDO_exe(7332, data)  # ポジションを変更する
# print(test)
# print("CDCRo")
#
# temp = oa.OrderDetailsState_exe(10597)  #　ALL取得　分割のケース⇒7324
# print(temp)
# print("↓")
#
# order_res = oa.OrderDetails_exe(9396)
# print(order_res)
# print("")
# order_res = oa.OrderDetails_exe(732)
# print(order_res)
#
# print("↑")
#
# position_js = oa.TradeDetails_exe(7332)  # PositionIDから詳細を取得
# print("")
#
# print(position_js)

# test = oa.OrderCancel_exe(111)
# print(test)

# ★データの取得（複数一括）
# mid_df = oa.InstrumentsCandles_multi_exe("USD_JPY", {"granularity": 'M5', "count": 100}, 1)
# mid_df.to_csv(tk.folder_path + 'TEST_DATA.csv', index=False, encoding="utf-8")
# f.draw_graph(mid_df)  # グラフ化
# print(mid_df)






# data = {
#     "stopLoss": {"price": 132.151, "timeInForce": "GTC"},
#     # "takeProfit": {"price": 132.006, "timeInForce": "GTC"},
#     # "trailingStopLoss": {"distance": 0.05, "timeInForce": "GTC"},
# }
# res = oa.TradeCRCDO_exe(104959, data)  # ポジションを変更する
# print(res)


# print(oa.OrderDetailsState_exe(108428))


# print("test")
# オーダー番号から、オーダーの行く末を取得する
# order_id = 88169  # pending
# # order_id = ans['order_id']
# order_detail = oa.OrderDetailsState_exe(order_id)  # 詳細の取得
# print(order_detail)
#
# test = oa.OrderCancel_exe(order_id)
#
# print(type(test))
# if type(test) is int:
#     print("の")
# else:
#     print("OK")

# temp = oa.OrderDetails_exe(88169)  # 88169  97483
# print(temp)

# temp = oa.OrderCancel_exe(88169)
# print(temp)





# print(time_jp)

# オーダーブックの取得
# ans = oa.OrderBook_exe(price_dic['mid'])
# print(ans)

# オーダー全部キャンセル（必要な時あり）
# oa.OrderCancel_All_exe()

# オーダー一覧取得(TP/LCなし）
# orders = oa.OrdersWaitPending_exe()

#         print("80")

#
# # オーダー一覧取得（TP/LC含む）
# orders_all = oa.OrdersPending_exe()
# print(orders_all)

# print(oa.OpenTrades_exe())






# オーダー状況確認用
# pending_new_df = oa.OrdersWaitPending_exe()  # ペンディングオーダーの取得(利確注文等は含まない）
# print(pending_new_df)
# pending_new_df.to_csv(tk.folder_path + 'TEST_DATA.csv', index=False, encoding="utf-8")


# # ★データの取得（単品・Param確認用）
# mid_each_df = oa.InstrumentsCandles_exe("USD_JPY",
#                                         {"granularity": 'S5', "count": 10, "from": "2023-01-03T02:10:00.000000000Z"})
# print(" EACH CANDLE")
# print(mid_each_df)



# # ★注文を発行
# oa.OrderCreate_exe(10000, 1, price_dic['mid'], 0.05, 0.09, "STOP", 0.05, " ")



# print(orders)
# bef_order = pd.read_csv(tk.folder_path + 'orders.csv', sep=",", encoding="utf-8")
# print(bef_order)
# ans_dic_arr = []
# counter = 0
# if len(orders) != 0:
#     for index, item in bef_order.iterrows():
#         if len(orders[orders['id'].str.contains(str(item['id']))]) == 0:
#             temp_dic = {
#                 "id": item['id'],
#                 "price": item['price'],
#                 "units": item['units']
#             }
#             ans_dic_arr.append(temp_dic)
#
# print(len(ans_dic_arr))
# for i in range(len(ans_dic_arr)):
#     if ans_dic_arr[i]['units'] == -80:
