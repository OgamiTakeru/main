import threading  # 定時実行用
import time
import datetime
import sys
import pandas as pd

# 自作ファイルインポート
import tokens as tk  # Token等、各自環境の設定ファイル（git対象外）
import classOanda as classOanda
import classPosition as classPosition  # とりあえずの関数集
import fTurnInspection as t  # とりあえずの関数集
import fGeneric as f
import fPeakLineInspection as p
import making as ins


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
    tk.line_send("■折返Position！", gl_live, gl_trade_num, "回目(", datetime.datetime.now().replace(microsecond=0), ")",
                 "トリガー:", info['trigger'], "指定価格", price, "情報:", info['memo'], ",オーダー:", '\n', o_memo,
                 '\n', "初回時間", gl_first_time, "その他情報⇒", "WL:", add_info['wl_info'])
    # テスト用
    # peak_information = p.peaks_collect(gl_data5r_df)
    # tops = p.horizon_line_detect(peak_information['tops'])
    # bottoms = p.horizon_line_detect(peak_information['bottoms'])
    # tk.line_send("【TOPS】", tops['ave'], "\n", "【BOTTOMS】", bottoms['ave'], "\n", "【TOPS_info】", tops['info'], "【bottomS_info】", bottoms['info'])
    peak_inspection = p.inspection_test(gl_data5r_df)
    tk.line_send(peak_inspection)

def order_delete_function():
    """
    反対側のオーダーを消しておく
    理由は両建てがダメなため、LCのかぶり等の問題が発生する
    :return:
    """

    if main_c.t_state == "OPEN":  # and main_c.life:
        # main（順思想がオーダー)が入っている場合、逆思想は消す
        if third_c.life or fourth_c.life:  # どちらかがOnの場合（基本は同時にOffになるはずだけど）
            third_c.close_order()
            fourth_c.close_order()
            watch2_c.close_order()
            tk.line_send("■逆思想オーダー削除（ポジションは解消しない）", third_c.life, fourth_c.life)
    elif third_c.t_state == "OPEN":# and third_c.life:
        # third(逆思想オーダー）が入っている場合、順思想は消す
        if main_c.life or second_c.life:
            main_c.close_order()
            second_c.close_order()
            watch1_c.close_order()
            tk.line_send("■順思想オーダー削除（ポジションは解消しない）", main_c.life, second_c.life)


def mode1():
    """
    低頻度モード（ローソクを解析し、注文を行う関数）
    ・調査対象のデータフレームはexe_manageで取得し、グローバル変数として所有済（gl_data5r_df）。時短の為。
    ・調査を他関数に依頼し、取得フラグと取得価格等を受け取り、それに従って注文を実行する関数
    :return: なし
    """
    print("  Mode1")
    global gl_latest_trigger_time, gl_peak_memo

    # 調査結果を取得する
    ins_res = ins.beforeDoublePeak(gl_data5r_df)  # 調査結果を受け取る

    # 発注を実行する
    if ins_res['take_position_flag']:
        # 調査の結果、取得結果有の場合
        tk.line_send(ins_res['decision_time'], ins_res['decision_price'], ins_res['expected_direction'])
        # 注文を実行する
        order = {
            "name": "test",
            "order_permission": True,
            "target_price": ins_res['target_price'],
            "tp_range": ins_res['tp_range'],
            "lc_range": ins_res['lc_range'],
            "units": 10,
            "direction": ins_res['expected_direction'],
            "type": "STOP",  # 1が順張り、-1が逆張り
            "trade_timeout": 1800,
            "remark": "test",
            "tr_range": 0,
        }
        main_c.order_plan_registration(order)
    print("MODE1 END")


def mode2():
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

    # ■深夜帯は実行しない　（ポジションやオーダーも全て解除）
    if 3 <= time_hour <= 6:
        if gl_midnight_close_flag == 0:  # 繰り返し実行しないよう、フラグで管理する
            classPosition.reset_all_position(classes)
            tk.line_send("■深夜のポジション・オーダー解消を実施")
            gl_midnight_close_flag = 1  # 実施済みフラグを立てる
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
        if price_dic['spread'] > gl_arrow_spread:
            print("    ▲スプレッド異常", gl_now, price_dic['spread'])
            return -1  # 強制終了

        # ■直近の検討データの取得　　　メモ：data_format = '%Y/%m/%d %H:%M:%S'
        # 直近の実行したローソク取得からの経過時間を取得する（秒単位で２連続の取得を行わないようにするためマージン）
        if gl_latest_exe_time == 0:
            past_time = 66  # 初回のみテキトーな値でごまかす
        else:
            past_time = (datetime.datetime.now().replace(microsecond=0) - gl_latest_exe_time).seconds

        if time_min % 5 == 0 and 6 <= time_sec < 30 and past_time > 60:  # キャンドルの確認　秒指定だと飛ぶので、前回から●秒経過&秒数に余裕を追加
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
            jp_time = datetime.datetime(2023, 9, 20, 12, 39, 0)
            euro_time_datetime = jp_time - datetime.timedelta(hours=9)
            euro_time_datetime_iso = str(euro_time_datetime.isoformat()) + ".000000000Z"  # ISOで文字型。.0z付き）
            param = {"granularity": "M5", "count": 50, "to": euro_time_datetime_iso}
            d5_df = oa.InstrumentsCandles_exe("USD_JPY", param)
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


# ■グローバル変数の宣言等
# 変更なし群
gl_arrow_spread = 0.011  # 実行を許容するスプレッド　＠ここ以外で変更なし
gl_first_exe = 0  # 初回のみ実行する内容があるため、初回フラグを準備しておく
# 変更あり群
gl_now = 0  # 現在時刻（ミリ秒無し） @exe_loopのみで変更あり
gl_now_str = ""
gl_now_price_mid = 0  # 現在価格（念のための保持）　@ exe_manageでのみ変更有
gl_midnight_close_flag = 0  # 深夜突入時に一回だけポジション等の解消を行うフラグ　＠time_manageのみで変更あり
gl_exe_mode = 0  # 実行頻度のモード設定　＠
gl_data5r_df = 0  # 毎回複数回ローソクを取得は時間無駄なので１回を使いまわす　＠exe_manageで取得
gl_trade_num = 0  # 取引回数をカウントする
gl_result_dic = {}
# gl_trade_win = 0  # プラスの回数を記録する
gl_live = "Pra"
gl_first_time = ""  # 初回の時間を抑えておく（LINEで見やすくするためだけ）
gl_latest_exe_time = 0  # 実行タイミングに幅を持たせる（各５の倍数分の６秒~３０秒で１回実行）に利用する
gl_latest_trigger_time = datetime.datetime.now() + datetime.timedelta(minutes=-6)  # 新規オーダーを入れてよいかの確認用
gl_peak_memo = {"memo_latest_past":"", "memo_mini_gap_past": "", "memo_para": ""}

# 倍率関係
unit_mag = 10 # 基本本番環境で動かす。unitsを低めに設定している為、ここで倍率をかけれる。
mag_unit_w = 1  # 勝っているときのUnit倍率
mag_lc_w = 1  # 勝っているときのLC幅の調整
mag_tp_w = 1  # 勝っているときのLC幅の調整
mag_unit_l = 1  # 負けている時のUnit倍率
mag_lc_l = 0.8  # 負けているときのLC幅の調整
mag_tp_l = 1  # 負けているときのLC幅の調整

# ■オアンダクラスの設定
fx_mode = 0  # 1=practice, 0=Live
if fx_mode == 1:  # practice
    oa = classOanda.Oanda(tk.accountID, tk.access_token, tk.environment)  # インスタンス生成
    gl_live = "Pra"
else:  # Live
    oa = classOanda.Oanda(tk.accountIDl, tk.access_tokenl, tk.environmentl)  # インスタンス生成
    gl_live = "Live"

# ■ポジションクラスの生成
main_c = classPosition.order_information("1", oa)  # 順思想のオーダーを入れるクラス
second_c = classPosition.order_information("2", oa)  # 順思想のオーダーを入れるクラス
third_c = classPosition.order_information("3", oa)  # 順思想のオーダーを入れるクラス
fourth_c = classPosition.order_information("4", oa)  # 順思想のオーダーを入れるクラス
watch1_c = classPosition.order_information("5", oa)
watch2_c = classPosition.order_information("6", oa)
# ■ポジションクラスを一まとめにしておく
classes = [main_c, second_c, third_c, fourth_c, watch1_c, watch2_c]

# ■処理の開始
classPosition.reset_all_position(classes)  # 開始時は全てのオーダーを解消し、初期アップデートを行う
tk.line_send("■■新規スタート", gl_live)
# main()
exe_loop(1, exe_manage)  # exe_loop関数を利用し、exe_manage関数を1秒ごとに実行
