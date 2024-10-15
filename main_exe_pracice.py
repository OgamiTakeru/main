import threading  # 定時実行用
import time
import datetime
import sys
import pandas as pd

# 自作ファイルインポート
import tokens as tk  # Token等、各自環境の設定ファイル（git対象外）
import classOanda as classOanda
import classPosition as classPosition  # とりあえずの関数集
import fBlockInspection as t  # とりあえずの関数集
import fGeneric as f
import fPeakInspection as p
import fDoublePeaks as dp
import fInspection_order_Main as im
import making as ins
import fResistanceLineInspection as ri


def order_line_send(class_order_arr, add_info):
    """
    検証し、条件達成でオーダー発行。クラスへのオーダー作成に関するアクセスはこの関数からのみ行う。
    :param class_order_arr: 対象のクラスと、そこへの注文情報
    :param add_info: その他の情報（今は負け傾向の強さ）
    :return:
    """
    global gl_trade_num

    gl_trade_num = gl_trade_num + 1
    o_memo = ""

    for i in range(len(class_order_arr)):
        # 変数に入れ替えする

        class_order_pair = class_order_arr[i]
        info = class_order_pair
        target_class = class_order_pair['target_class']
        # ■通常オーダー(通常部）発行
        price = round(info['base_price'] + info['margin'], 3)  # marginの方向は調整済

        # オーダーを発行する（即時判断含める）
        if target_class.order_permission:
            # 送信用
            o = target_class.plan
            memo_each = "【" + target_class.name + "】:\n" + str(price) \
                        + "(" + str(round(info['base_price'], 3)) + "+" + str(info['margin']) + "),\n tp:" \
                        + str(o['tp_price']) + "-lc:" + str(o['lc_price']) \
                        + "\n(" + str(o['tp_range']) + "-" + str(o['lc_range']) + ")," \
                        + str(o['units']) + str(round(o['cascade_unit'] * 0.1, 3))
            o_memo = o_memo + memo_each + '\n'
        else:
            o_memo = "OrderPermissionFalse"

    # 送信は一回だけにしておく。
    # tk.line_send("■折返Position！", gl_live, gl_trade_num, "回目(", datetime.datetime.now().replace(microsecond=0), ")",
    #              "トリガー:", info['trigger'], "指定価格", price, "情報:", info['memo'], ",オーダー:", '\n', o_memo,
    #              '\n', "初回時間", gl_first_time, "その他情報⇒", "WL:", add_info['wl_info'])
    # テスト用
    # peak_information = p.peaks_collect(gl_data5r_df)
    # tops = p.horizon_line_detect(peak_information['tops'])
    # bottoms = p.horizon_line_detect(peak_information['bottoms'])
    # tk.line_send("【TOPS】", tops['ave'], "\n", "【BOTTOMS】", bottoms['ave'], "\n", "【TOPS_info】", tops['info'], "【bottomS_info】", bottoms['info'])
    peak_inspection = p.inspection_test(gl_data5r_df)
    tk.line_send(peak_inspection)


def mode1():
    """
    低頻度モード（ローソクを解析し、注文を行う関数）
    ・調査対象のデータフレームはexe_manageで取得し、グローバル変数として所有済（gl_data5r_df）。API発行回数削減の為。
    ・調査を他関数に依頼し、取得フラグと取得価格等を受け取り、それに従って注文を実行する関数
    発注に必要（引数で受け取るべき）な情報は以下の通り（oandaClass.order_plan_registrationに渡す最低限の情報)
    {
        "name": "MarginS-TPS",  # 〇　LINE送信に利用する
        "order_permission": True,  # 〇
        "target_price": order_base['decision_price'],  # ×
        "tp_range": order_base['tp_range'] * 0.8,  # 〇
        "lc_range": order_base['lc_range'],  # 〇
        "units": 10,  # 〇
        "direction": order_base['expected_direction'],  # 〇　（ask_bidとなる）
        "type": "STOP" if order_base['stop_or_limit'] == 1 else "LIMIT",　 # 〇
        "trade_timeout_min": 1800,  # 〇
        "remark": "test",  # 任意
        "tr_range": 0,  # 〇
        "lc_change": {"lc_change_exe": True, "lc_trigger_range": 0.3, "lc_ensure_range": 0.1}　任意
    },
    :return: なし
    """
    print("  Mode1")
    global gl_trade_num
    global gl_latest_trigger_time, gl_peak_memo
    global gl_upper_line, gl_lower_line  # RangeInspectionのみ

    # ■検証を実行し、結果を取得する
    # なお{"take_position_flag":Boo, "exe_orders":[], "exe_order":{}, "max_priority":(int) }が返却値の予定
    inspection_result_dic = im.inspection_warp_up_and_make_order_practice(gl_data5r_df)
    print(inspection_result_dic)

    # ■ オーダーフラグがない場合は、ここでこの関数は教師終了
    if not inspection_result_dic['take_position_flag']:
        # 発注がない場合は、終了 (ポケ除け的な部分）
        return 0
    # return 0  # テストモード（動かすがオーダーは入れない）の場合、このリターンをコメントインすし終了させるとオーダーしない。。

    # ■既存のオーダーやポジションとの兼ね合いの検証
    classes_info = classPosition.position_check(classes)  # 現在の情報を取得
    # ■■■既存オーダーが存在する場合、プライオリティ、現在のプラスマイナス、入れようとしている向きが同方向かを比較する
    if classes_info['order_exist']:
        # オーダーが存在する場合、互い(新規と既存)のプライオリティ次第で注文を発行する。基本的には既存を取り消すが、例外的に既存が優先される。
        # 取り急ぎ、フラッグ形状の２のみが優先対象（置き換わらない）
        if classes_info['max_priority'] > inspection_result_dic['max_priority']:
            # 同じだったら入れ替えたいので、「すでに入力されているものが大きかったら(>)」となる。
            # tk.line_send("新規オーダー見送り", classes_info['max_order_time_sec'], ",", classes_info['max_priority'], inspection_result_dic['max_priority'], inspection_result_dic['exe_orders'][0]['name'])
            return 0
    # ■■■既存のポジションが存在する場合　現在注文があるかを確認する(なんでポジション何だっけ？）
    if classes_info['position_exist']:
        # 既存のポジションがある場合、互い(新規と既存)プライオリティ次第で注文を発行する
        if classes_info['open_positions'][0]['pl'] < 0:
            # 現在のポジションがマイナスの場合
            if classes_info['open_positions'][0]['direction'] == inspection_result_dic['exe_orders'][0]['expected_direction']:
                # 新オーダー候補と方向が同じな場合
                # 新オーダーのプライオリティが既存の物より高い場合、新規で置き換える
                if inspection_result_dic['max_priority'] > classes_info['max_priority']:
                    # 新規が重要オーダー。このまま処理を継続し、既存のオーダーとポジションを消去し、新規オーダーを挿入
                    pass
                    # tk.line_send("★[practice]ポジションありだがフラッグ発生のため置換", "Pri", inspection_result_dic['max_priority'])
                else:
                    # 新規の重要性は今より低い。ただし、ポジション後２５分以内の物は、プライオリティが同一の場合でも置き変わらない
                    if classes_info['max_position_time_sec'] < 1500:
                        # tk.line_send("★[practice]ポジションありの為様子見 秒:", classes_info['max_position_time_sec'], "現pri", classes_info['max_priority'], "Pri", inspection_result_dic['max_priority'], inspection_result_dic['exe_orders'][0]['name'])
                        # classPosition.position_check(classes) で各ポジションの状態を確認可能
                        return 0
                    else:
                        # tk.line_send("[practice]重要度低いが、時間的に経過しているため、ポジション解消し新規オーダー投入", "現pri", classes_info['max_priority'], "新Pri", inspection_result_dic['max_priority'], inspection_result_dic['exe_orders'][0]['name'])
                        pass
            else:
                # tk.line_send("★[practice]既存のポジションと方向が同じ（マイナスだが）のため様子見", inspection_result_dic['exe_orders'][0]['name'])
                return 0
        else:
            # tk.line_send("[practice]★ポジションありで、プラスのため様子見", inspection_result_dic['exe_orders'][0]['name'])
            return 0

    # ■既存のオーダーがある場合（強制的に削除）
    classPosition.reset_all_position(classes)  # 開始時は全てのオーダーを解消し、初期アップデートを行う

    # ■注文を実行する
    gl_trade_num += 1
    line_send = ""  # LINE送信用の注文結果の情報
    print("  オーダー数", len(inspection_result_dic['exe_orders']))
    for n in range(len(inspection_result_dic['exe_orders'])):  # ここ（正規実行）では「配列」でOrder情報を受け取る（testでは辞書単品で受け取る）　
        print("  要求されたオーダー(each)")
        print(inspection_result_dic['exe_orders'][n])
        res_dic = classes[n].order_plan_registration(inspection_result_dic['exe_orders'][n])  #
        print("  オーダー結果")
        print(res_dic)
        # line_sendは利確や損切の指定が無い場合はエラーになりそう（ただそんな状態は基本存在しない）
        # TPrangeとLCrangeの表示は「inspection_result_dic」を参照している。
        line_send = line_send + "◆" + res_dic['order_name'] + \
                    "指定価格:【" + str(res_dic['order_result']['price']) + "】"+\
                    ", 数量:" + str(res_dic['order_result']['json']['orderCreateTransaction']['units']) + \
                    ", TP:" + str(res_dic['order_result']['json']['orderCreateTransaction']['takeProfitOnFill']['price']) + \
                    "(" + str(round(abs(float(res_dic['order_result']['json']['orderCreateTransaction']['takeProfitOnFill']['price']) - float(res_dic['order_result']['price'])), 2)) + ")" + \
                    ", LC:" + str(res_dic['order_result']['json']['orderCreateTransaction']['stopLossOnFill']['price']) + \
                    "(" + str(round(abs(float(res_dic['order_result']['json']['orderCreateTransaction']['stopLossOnFill']['price']) - float(res_dic['order_result']['price'])), 2)) + ")" + \
                    ", OrderID:" + str(res_dic['order_id']) + \
                    ", 取得価格:" + str(res_dic['order_result']['execution_price']) + ") "

        # 注文結果を送信す
    # tk.line_send("★オーダー発行", gl_trade_num, "回目: ",  " 　　　",  line_send,
    #              ", 現在価格:", str(gl_now_price_mid), "スプレッド", str(gl_now_spread))
    print("MODE1 END")
    print("")


def mode2():
    global gl_exe_mode
    # print("MODE2")
    classPosition.all_update_information(classes)  # 情報アップデート
    if classPosition.life_check(classes):
        # オーダー以上がある場合。表示用（１分に１回表示させたい）
        temp_date = datetime.datetime.now().replace(microsecond=0)  # 秒を算出
        if 2 <= int(temp_date.second) < 4:  # ＝１分に一回練習用は(毎分2秒と4秒)
            have_position = classPosition.position_check(classes)
            print("■■■Mode2(いずれかポジション有)", f.now(), "これは１分に１回表示")
            # if have_position['position_exist']:
                # ポジションがある場合
                # classPosition.close_opposite_order(classes)


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
    global gl_now_spread

    # ■土日は実行しない（ループにはいるが、API実行はしない）
    if gl_now.weekday() >= 5:
        # print("■土日の為API実行無し")
        return 0

    # ■深夜帯は実行しない　（ポジションやオーダーも全て解除）
    # if 6 <= time_hour <= 7:
    #     if gl_midnight_close_flag == 0:  # 繰り返し実行しないよう、フラグで管理する
    #         classPosition.reset_all_position(classes)
    #         tk.line_send("■深夜のポジション・オーダー解消を実施")
    #         gl_midnight_close_flag = 1  # 実施済みフラグを立てる

    # ■実行を行う
    else:
        gl_midnight_close_flag = 0  # 実行可能時には深夜フラグを解除しておく（毎回やってしまうけどいいや）

        # ■時間内でスプレッドが広がっている場合は強制終了し実行しない　（現価を取得しスプレッドを算出する＋グローバル価格情報を取得する）
        price_dic = oa.NowPrice_exe("USD_JPY")
        if price_dic['error'] == -1:  # APIエラーの場合はスキップ
            print("API異常発生の可能性", gl_now)
            return -1  # 終了
        else:
            price_dic = price_dic['data']

        gl_now_price_mid = price_dic['mid']  # 念のために保存しておく（APIの回数減らすため）
        gl_now_spread = price_dic['spread']
        if price_dic['spread'] > gl_arrow_spread:
            # print("    ▲スプレッド異常", gl_now, price_dic['spread'])
            return -1  # 強制終了

        # ■直近の検討データの取得　　　メモ：data_format = '%Y/%m/%d %H:%M:%S'
        # 直近の実行したローソク取得からの経過時間を取得する（秒単位で２連続の取得を行わないようにするためマージン）
        if gl_latest_exe_time == 0:
            past_time = 66  # 初回のみテキトーな値でごまかす
        else:
            past_time = (datetime.datetime.now().replace(microsecond=0) - gl_latest_exe_time).seconds

        if time_min % 5 == 0 and 10 <= time_sec < 30 and past_time > 60:  # キャンドルの確認　秒指定だと飛ぶので、前回から●秒経過&秒数に余裕を追加
            print("■■■Candle調査", gl_live, gl_now, past_time)  # 表示用（実行時）
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
            print("■■■初回", gl_now, gl_exe_mode, gl_live)  # 表示用（実行時）
            # classPosition.all_update_information(classes)  # 情報アップデート
            d5_df = oa.InstrumentsCandles_multi_exe("USD_JPY", {"granularity": "M5", "count": 50}, 1)  # 時間昇順
            if d5_df['error'] == -1:
                print("error Candle First")
            else:
                d5_df = d5_df['data']
            # ↓時間指定
            jp_time = datetime.datetime(2024, 8, 14, 8, 20, 0)
            euro_time_datetime = jp_time - datetime.timedelta(hours=9)
            euro_time_datetime_iso = str(euro_time_datetime.isoformat()) + ".000000000Z"  # ISOで文字型。.0z付き）
            param = {"granularity": "M5", "count": 85, "to": euro_time_datetime_iso}
            d5_df = oa.InstrumentsCandles_exe("USD_JPY", param)
            # ↑時間指定
            # ↓現在時刻
            d5_df = oa.InstrumentsCandles_multi_exe("USD_JPY", {"granularity": "M5", "count": 50}, 1)
            # ↑現在時刻
            d5_df = d5_df['data']
            print(d5_df.head(5))

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


# ■グローバル変数の宣言等
# 変更なし群
gl_arrow_spread = 0.011  # 実行を許容するスプレッド　＠ここ以外で変更なし
gl_first_exe = 0  # 初回のみ実行する内容があるため、初回フラグを準備しておく
# 変更あり群
gl_now = 0  # 現在時刻（ミリ秒無し） @exe_loopのみで変更あり
gl_now_str = ""
gl_now_price_mid = 0  # 現在価格（念のための保持）　@ exe_manageでのみ変更有
gl_now_spread = 0
gl_midnight_close_flag = 0  # 深夜突入時に一回だけポジション等の解消を行うフラグ　＠time_manageのみで変更あり
gl_exe_mode = 0  # 実行頻度のモード設定　＠
gl_data5r_df = 0  # 毎回複数回ローソクを取得は時間無駄なので１回を使いまわす　＠exe_manageで取得
gl_trade_num = 0  # 取引回数をカウントする
gl_num_for_new_class = 1  # クラスを生成する際、クラス名として利用する変数。（＝クラスの数）
gl_result_dic = {}
# gl_trade_win = 0  # プラスの回数を記録する
gl_live = "Pra"
gl_first_time = ""  # 初回の時間を抑えておく（LINEで見やすくするためだけ）
gl_latest_exe_time = 0  # 実行タイミングに幅を持たせる（各５の倍数分の６秒~３０秒で１回実行）に利用する
gl_latest_trigger_time = datetime.datetime.now() + datetime.timedelta(minutes=-6)  # 新規オーダーを入れてよいかの確認用
gl_peak_memo = {"memo_latest_past": "", "memo_mini_gap_past": "", "memo_para": ""}

# 倍率関係
unit_mag = 10 # 基本本番環境で動かす。unitsを低めに設定している為、ここで倍率をかけれる。
mag_unit_w = 1  # 勝っているときのUnit倍率
mag_lc_w = 1  # 勝っているときのLC幅の調整
mag_tp_w = 1  # 勝っているときのLC幅の調整
mag_unit_l = 1  # 負けている時のUnit倍率
mag_lc_l = 0.8  # 負けているときのLC幅の調整
mag_tp_l = 1  # 負けているときのLC幅の調整

# Rangeinspectionの結果保存用
gl_lower_line = 0
gl_upper_line = 0

# ■オアンダクラスの設定
fx_mode = 1  # 1=practice, 0=Live
if fx_mode == 1:  # practice
    oa = classOanda.Oanda(tk.accountID, tk.access_token, tk.environment)  # インスタンス生成
    gl_live = "Pra"
    is_live = False
else:  # Live
    oa = classOanda.Oanda(tk.accountIDl, tk.access_tokenl, tk.environmentl)  # インスタンス生成
    gl_live = "Live"
    is_live = True

# ■ポジションクラスの生成
classes = []
for i in range(10):
    # 複数のクラスを動的に生成する。クラス名は「C＋通し番号」とする。
    # クラス名を確定し、クラスを生成する。
    new_name = "c" + str(i)
    classes.append(classPosition.order_information(new_name, oa, is_live))  # 順思想のオーダーを入れるクラス
    # クラス数を記録し、通し番号をグローバル変数で記憶する（本文上で名前を付与するときに、利用する）
    gl_num_for_new_class += 1  # 実際使っていない

print(classes)
print(classes[0].name)


# ■処理の開始
classPosition.reset_all_position(classes)  # 開始時は全てのオーダーを解消し、初期アップデートを行う
tk.line_send("■■新規スタート", gl_live)
# main()
exe_loop(1, exe_manage)  # exe_loop関数を利用し、exe_manage関数を1秒ごとに実行
