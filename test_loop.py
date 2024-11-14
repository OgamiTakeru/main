import threading  # 定時実行用
import time
import tokens as tk  # Token等、各自環境の設定ファイル（git対象外）
import classOanda as classOanda
import classPosition as classPosition
import fGeneric as gene
import datetime
import fCommonFunction as cm
import fInspection_order_Main as im
import math
from decimal import Decimal, ROUND_DOWN
import glob
import os
import gc


def get_instances_of_class(cls):
    """
    特定のクラスのインスタンス一覧を取得する関数
    """
    return [obj for obj in gc.get_objects() if isinstance(obj, cls)]


def exe_manage():
    """
    時間やモードによって、実行関数等を変更する
    :return:
    """
    print("■■■クラスアップデート", )  # 表示用（実行時）
    classPosition.all_update_information(classes)  # 情報アップデート


def exe_loop(interval, fun, wait=True):
    """
    :param interval: 何秒ごとに実行するか
    :param fun: 実行する関数（この関数への引数は与えることが出来ない）
    :param wait: True固定
    :return: なし
    """
    global gl_now, gl_now_str
    base_time = time.time()
    while True:
        # 現在時刻の取得
        gl_now = datetime.datetime.now().replace(microsecond=0)  # 現在の時刻を取得
        gl_now_str = str(gl_now.month).zfill(2) + str(gl_now.day).zfill(2) + "_" + \
                     str(gl_now.hour).zfill(2) + str(gl_now.minute).zfill(2) + "_" + str(gl_now.second).zfill(2)
        t = threading.Thread(target=fun)
        t.start()
        if wait:  # 時間経過待ち処理？
            t.join()
        # 待機処理
        next_time = ((base_time - time.time()) % 1) or 1
        time.sleep(next_time)


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
classes = []
for i in range(12):
    # 複数のクラスを動的に生成する。クラス名は「C＋通し番号」とする。
    # クラス名を確定し、クラスを生成する。
    new_name = "c" + str(i)
    classes.append(classPosition.order_information(new_name, oa, is_live))  # 順思想のオーダーを入れるクラス
for item in classes:
    print(item.name)
print(" ↑クラス一覧")

# 仮のオーダーの設定
exe_orders = []
# 仮１
order1 = cm.order_base(now_price, now_time)  # orderbaseの初期値は、Unitsは正の値、TypeはSTOP、TP/LCは0.1
order1['name'] = "test1"
order1['target'] = 0.05  # マージンで設定
order1['type'] = "MARKET"
order1['target'] = now_price
order1_finalized = cm.order_finalize(order1)
exe_orders.append(order1_finalized)
# 仮２
order2 = cm.order_base(now_price, now_time)  # orderbaseの初期値は、Unitsは正の値、TypeはSTOP、TP/LCは0.1
order2['name'] = "test2"
order2['target'] = 0.08  # マージンで設定
order2_finalized = cm.order_finalize(order2)
exe_orders.append(order2_finalized)

# オーダーの発行
for order_n in range(len(exe_orders)):  # オーダーを順に参照
    for class_index, each_class in enumerate(classes):  # クラスを参照
        if each_class.life:
            # lifeがTrueの場合、次のClassに探していく
            print(" クラス埋まりあり", each_class.name, each_class.o_time, each_class.o_state, each_class.t_state,class_index)
            continue
        # クラスが埋まっていない場合は、そこに入れていく
        print("空き発見", class_index)
        res_dic = classes[class_index].order_plan_registration(exe_orders[order_n])
        break

# [インスタンス表示テスト] MyClassのインスタンス一覧を取得
instances = get_instances_of_class(classPosition.order_information)
# 各インスタンスの情報を表示
for instance in instances:
    print(instance.name)

# ■処理の開始
# classPosition.reset_all_position(classes)  # 開始時は全てのオーダーを解消し、初期アップデートを行う
# main()
exe_loop(1, exe_manage)  # exe_loop関数を利用し、exe_manage関数を1秒ごとに実行

