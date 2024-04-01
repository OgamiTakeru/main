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
c = classPosition.order_information("test", oa)


def mode1():
    print("test1")
    print("  Mode1")
    global gl_latest_trigger_time, gl_peak_memo

    # 現在注文があるかを確認する
    if len(classPosition.position_check(classes)) >= 1:  # 現在、ポジションが１以上がある場合、解除。
        classPosition.reset_all_position(classes)
        print("  既存ポジションがあるため、解消してからオーダーを発行する")

    # 注文を実行する
    classes[0].order_plan_registration(test_order)

    print("MODE1 END")
    print("")


def mode2():
    print("test2")
    global gl_exe_mode
    classPosition.all_update_information(classes)  # 情報アップデート
    if classPosition.life_check(classes):
        # 表示用（１分に１回表示させたい）
        temp_date = datetime.datetime.now().replace(microsecond=0)  # 秒を算出
        if 0 <= int(temp_date.second) < 2:  # ＝１分に一回(毎分１秒と２秒)
            classes_info = classPosition.position_info(classes)
            print("■■■Mode2(各分表示 &　いずれかポジション有)", f.now())
            if classes_info == "":
                pass  # Wだけの場合は表示しない（改行がうっとうしい）
            else:
                print("    ", classes_info)


def exe_manage():
    """
    時間やモードによって、実行関数等を変更する
    :return:
    """
    # 時刻の分割（処理で利用）
    time_hour = gl_now.hour  # 現在時刻の「時」のみを取得
    time_min = gl_now.minute  # 現在時刻の「分」のみを取得
    time_sec = gl_now.second  # 現在時刻の「秒」のみを取得

    # グローバル変数の宣言（編集有分のみ）
    global gl_midnight_close_flag, gl_now_price_mid, gl_data5r_df, gl_first_exe, gl_first_time, gl_latest_exe_time

    if gl_latest_exe_time == 0:
        past_time = 66  # 初回のみテキトーな値でごまかす
    else:
        past_time = (datetime.datetime.now().replace(microsecond=0) - gl_latest_exe_time).seconds

    if time_min % 5 == 0 and 6 <= time_sec < 30 and past_time > 60:  # キャンドルの確認　秒指定だと飛ぶので、前回から●秒経過&秒数に余裕を追加
        print("■■■Candle調査", gl_now, past_time)  # 表示用（実行時）
        classPosition.all_update_information(classes)  # 情報アップデート
        d5_df = oa.InstrumentsCandles_multi_exe("USD_JPY", {"granularity": "M5", "count": 50}, 1)  # 時間昇順(直近が最後尾）
        if d5_df['error'] == -1:
            print("error Candle")
            return -1
        else:
            d5_df = d5_df['data']
        tc = (datetime.datetime.now().replace(microsecond=0) - classOanda.str_to_time(d5_df.iloc[-1]['time_jp'])).seconds
        if tc > 420:  # 何故か直近の時間がおかしい時がる
            print(" ★★直近データがおかしい", d5_df.iloc[-1]['time_jp'], f.now())

        gl_data5r_df = d5_df.sort_index(ascending=False)  # 対象となるデータフレーム（直近が上の方にある＝時間降順）をグローバルに
        d5_df.to_csv(tk.folder_path + 'main_data5.csv', index=False, encoding="utf-8")  # 直近保存用
        mode1()
        # print("GLlatest入れ替え", gl_latest_exe_time)
        gl_latest_exe_time = datetime.datetime.now().replace(microsecond=0)
        # print(gl_latest_exe_time)
    elif time_min % 1 == 0 and time_sec % 2 == 0:  # 高頻度での確認事項（キャンドル調査時のみ飛ぶ）
        mode2()

    # ■　初回だけ実行と同時に行う
    if gl_first_exe == 0:
        gl_first_exe = 1
        gl_first_time = gl_now
        print("■■■初回", gl_now)  # 表示用（実行時）
        # classPosition.all_update_information(classes)  # 情報アップデート
        d5_df = oa.InstrumentsCandles_multi_exe("USD_JPY", {"granularity": "M5", "count": 50}, 1)  # 時間昇順
        if d5_df['error'] == -1:
            print("error Candle First")
        else:
            d5_df = d5_df['data']
        # ↓時間指定
        # jp_time = datetime.datetime(2023, 9, 20, 12, 39, 0)
        # euro_time_datetime = jp_time - datetime.timedelta(hours=9)
        # euro_time_datetime_iso = str(euro_time_datetime.isoformat()) + ".000000000Z"  # ISOで文字型。.0z付き）
        # param = {"granularity": "M5", "count": 50, "to": euro_time_datetime_iso}
        # d5_df = oa.InstrumentsCandles_exe("USD_JPY", param)
        d5_df = oa.InstrumentsCandles_multi_exe("USD_JPY", {"granularity": "M5", "count": 50}, 1)
        d5_df = d5_df['data']
        print(d5_df.head(5))
        # ↑時間指定

        gl_data5r_df = d5_df.sort_index(ascending=False)  # 対象となるデータフレーム（直近が上の方にある＝時間降順）をグローバルに
        d5_df.to_csv(tk.folder_path + 'main_data5.csv', index=False, encoding="utf-8")  # 直近保存用
        mode1()




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


gl_first_exe = 0  # 初回のみ実行する内容があるため、初回フラグを準備しておく
gl_now = 0  # 現在時刻（ミリ秒無し） @exe_loopのみで変更あり
gl_num_for_new_class = 1  # クラスを生成する際、クラス名として利用する変数。（＝クラスの数）
gl_latest_exe_time = 0  # 実行タイミングに幅を持たせる（各５の倍数分の６秒~３０秒で１回実行）に利用する

classes = []
for i in range(1):
    # 複数のクラスを動的に生成する。クラス名は「C＋通し番号」とする。
    # クラス名を確定し、クラスを生成する。
    new_name = "c" + str(i)
    classes.append(classPosition.order_information(new_name, oa))  # 順思想のオーダーを入れるクラス
    # クラス数を記録し、通し番号をグローバル変数で記憶する（本文上で名前を付与するときに、利用する）
    gl_num_for_new_class += 1

test_order ={  # オーダー２を作成
    "name": "1",
    "order_permission": True,
    "target_price": now_price + 0.01,
    "lc_range": 0.03,
    "tp_range": 0.05,
    "units": 20,
    "direction": 1,
    "type": "MARKET",  # 1が順張り、-1が逆張り
    "trade_timeout": 1800,
    "remark": "test",
    "tr_range": 0.05,
    "lc_change": {"lc_change_exe": True, "lc_trigger_range": 0.04, "lc_ensure_range": 0.01}
}

print(classes)
print(classes[0].name)


# ■処理の開始
classPosition.reset_all_position(classes)  # 開始時は全てのオーダーを解消し、初期アップデートを行う
exe_loop(1, exe_manage)  # exe_loop関数を利用し、exe_manage関数を1秒ごとに実行