import pandas as pd

import datetime
import tokens as tk  # Token等、各自環境の設定ファイル（git対象外）
import classOanda as classOanda
import classPosition as classPosition
import fGeneric as gene
import datetime
import fInspection_order_Main as im
import math
from decimal import Decimal, ROUND_DOWN
import glob
import os

# グローバルでの宣言
oa = classOanda.Oanda(tk.accountIDl, tk.access_tokenl, "live")  # クラスの定義
now_price_dic = oa.NowPrice_exe("USD_JPY")
now_price = now_price_dic['data']['mid']
print(now_price)
gl_start_time = datetime.datetime.now()
# クラスの定義
classes = []
for ic in range(3):
    # 複数のクラスを動的に生成する。クラス名は「C＋通し番号」とする。
    # クラス名を確定し、クラスを生成する。
    new_name = "c" + str(ic)
    classes.append(classPosition.order_information(new_name, oa, False))  # 順思想のオーダーを入れるクラス


# test_df = oa.get_base_data_multi(1, 1000)
# test_df.to_csv(tk.folder_path + 'tranzaction.csv', index=False, encoding="utf-8")
# print(test_df)


class Order:
    class_total = 0

    def __init__(self, order_dic):
        print("検証でオーダー受付", order_dic['units'])
        print(order_dic)
        self.take_position_flag = False
        self.position_is_live = False
        self.position_status = "PENDING"  # pending, open ,closed, cancelled
        self.name = order_dic['name']
        self.target_price = order_dic['target_price']
        self.tp_price = order_dic['tp_price']
        self.lc_price = order_dic['lc_price']
        self.done = False
        self.units = order_dic['units'] * order_dic['direction']  # 正の値しか来ないようだ！？ なので、directionをかけておく
        self.direction = order_dic['direction']  # self.units / abs(self.units)
        self.order_keeping_time_sec = 0  # 現在オーダーをキープしている時間
        self.order_timeout_sec = 45 * 60
        self.position_timeout_sec = 50 * 60

        self.unrealized_pl = 0  # 含み損益
        self.unrealized_pl_high = 0  # 最大含み損益(検証特有。最もその足でプラスに考えた状態の損益）
        self.unrealized_pl_low = 0  # 最小含み損益（検証特融。最もその足でマイナスに考えた状態の損益）
        self.unrealized_pl_per_units = 0
        self.realized_pl = 0
        self.realized_pl_per_units = 0

        self.position_time = 0
        self.position_keeping_time_sec = 0  # 現在ポジションをキープしている時間
        self.order_time = order_dic['order_time']
        self.max_plus = 0  # ポジションを持っている中で、一番プラスになっている時を取得
        self.max_minus = 999  # ポジションを持っている中で、一番マイナスになっている時を取得
        self.settlement_price = 0
        self.lc_change = order_dic['lc_change']
        self.priority = order_dic['priority']

        self.comment = ""  # クラスごとに残すコメント（決済がLCChangeの場合LCとなるので、ClChangeとしたい、とか）

    def lc_change_done(self, i):
        self.lc_change[i]['done'] = True




def str_to_time(str_time):
    """
    時刻（文字列 yyyy/mm/dd hh:mm:mm）をDateTimeに変換する。
    何故かDFないの日付を扱う時、isoformat関数系が使えない。。なぜだろう。
    :param str_time:
    :return:
    """
    time_dt = datetime.datetime(int(str_time[0:4]),
                                int(str_time[5:7]),
                                int(str_time[8:10]),
                                int(str_time[11:13]),
                                int(str_time[14:16]),
                                int(str_time[17:19]))
    return time_dt


def cal_str_time_gap(time_str_1, time_str_2):
    """
    データフレームのtime_jp同士の時間の差を求める。
    引数で渡された日時のどちらか大きいか（Later）か判断し、差分を正の値で産出する。
    """
    time1 = time_str_1 if isinstance(time_str_1, datetime.datetime) else str_to_time(time_str_1)
    time2 = time_str_2 if isinstance(time_str_2, datetime.datetime) else str_to_time(time_str_2)

    if time1 > time2:
        later_time = time1
        older_time = time2
        r = 1
    else:
        later_time = time2
        older_time = time1
        r = -1
    gap_abs = later_time - older_time  # 正の値が保証された差分
    # gap = time1 - time2  # 渡されたものをそのまま引き算（これエラーになりそうだから消しておく）

    return {
        "gap_abs": gap_abs.seconds,
        "gap": gap_abs.seconds * r
    }


def find_analysis_dataframe(df, time_jp):
    """
    解析用に指定の時刻「より前」の5分足のデータフレームを取得する
    """
    idx = df[df['time_jp'] == time_jp].index
    if len(idx) == 0:
        return pd.DataFrame()  # 値が存在しない場合は空のデータフレームを返す
    # 最初のインデックスを取得し、その後の行をフィルタ
    return df[df.index <= idx[0]]


def update_order_information_and_take_position(cur_class, cur_row, cur_row_index):
    """
    オーダーが約定するかを確認する関数
    引数は対象のクラス(CurrentClass)と、検証対象のデータ行(CurrentRow)と、そのデータ行のインデックス
    """
    # スプレッドを考慮した、アジャスターを用意(買いの場合は、買い価格で開始する（0.004 = スプレッド÷2)。売りの場合はその逆）
    adjuster = 0.004 if cur_class.direction == 1 else -0.004

    # (1)オーダーの時間を求め、時間切れ判定も実施する
    order_keeping_time_sec = cal_str_time_gap(cur_row['time_jp'], cur_class.order_time)['gap']
    cur_class.order_keeping_time_sec = order_keeping_time_sec  # クラスの内容を更新（オーダー取得までの経過時間として使える。ポジション後は更新しないため）
    if order_keeping_time_sec >= cur_class.order_timeout_sec:
        print("   ■タイムアウトです", cur_class.name, cur_row['time_jp'])
        # クラス内容の更新
        cur_class.done = True

    # (2)取得判定を実施する　（同一行で取得⇒ロスカの可能性はここでは考えない）
    target_price = cur_class.target_price
    if cur_row['low'] + adjuster <= target_price < cur_row["high"] + adjuster:
        print("　　■取得しました", cur_class.name, cur_row['time_jp'], cur_row['low'], cur_row['high'], target_price)
        # クラス内容の更新
        cur_class.position_time = cur_row['time_jp']
        cur_class.position_is_live = True


def update_position_information(cur_class, cur_row, cur_row_index):
    """
    ポジションの情報を更新し（ポジションある状態での実行が前提）、必要に応じてクラスに反映する。
    """
    # (1)情報の整理
    # ポジションの最高プラスかマイナスを更新する(ロスカットかどうかはとりあえず加味しない）
    upper_gap = cur_row['high'] - cur_class.target_price  # 買いポジの場合はプラス域
    lower_gap = cur_class.target_price - cur_row['low']  # 買いポジの場合はマイナス域

    # 経過秒を計算する
    position_keeping_time_sec = cal_str_time_gap(cur_row['time_jp'], cur_class.position_time)['gap']

    # PLを計算する(幅があるため、基本はClose価格で計算した損益を使用するが、最大（最もプラスにとらえた）PLや最低PLも取得しておく
    # スプレッドを考慮した、アジャスターを用意(買いの場合は、売り価格で終了する（-0.004 = スプレッド÷2)。売りの場合はその逆）
    adjuster = -0.004 if cur_class.direction == 1 else 0.004
    now_price = cur_row['close']  # 暫定としてクローズ価格を現在価格とする ★NowPriceで考えるため、LCやTP priceとは誤差が出る。
    # 現価＞ターゲットだと現価-ターゲットは正の値。買いポジの場合は＋）
    pl_use_close = round((cur_row['close'] + adjuster - cur_class.target_price) * cur_class.direction,
                         3)  # 現価＞ターゲットだと現価-ターゲットは正の値。買いポジの場合は＋）
    pl_use_high = round((cur_row['high'] + adjuster - cur_class.target_price) * cur_class.direction,
                        3)  # 現価＞ターゲットだと現価-ターゲットは正の値。買いポジの場合は＋）
    pl_use_low = round((cur_row['low'] + adjuster - cur_class.target_price) * cur_class.direction,
                       3)  # 現価＞ターゲットだと現価-ターゲットは正の値。買いポジの場合は＋）

    # print("  -Update条件", cur_row['low'], cur_row['high'])
    # print("  -Update条件", pl_use_low, pl_use_high, cur_class.direction)

    if cur_class.direction == 1:
        # 買い方向の場合
        cur_class.unrealized_pl_high = pl_use_high
        cur_class.unrealized_pl_low = pl_use_low
    else:
        # 売り方向の場合
        cur_class.unrealized_pl_high = pl_use_low
        cur_class.unrealized_pl_low = pl_use_high

    # (2)クラス内の情報を更新する（最大プラスと最大マイナス）
    cur_class.position_keeping_time_sec = position_keeping_time_sec  # 所持継続時間の更新
    cur_class.unrealized_pl = pl_use_close * abs(cur_class.units)  # 含み損益の更新（Unitsをかけたもの）　マイナス値を持つ
    cur_class.unrealized_pl_per_units = pl_use_close  # 含み損益（Unitsに依存しない数） マイナス値を持つ
    # print(pl * abs(cur_class.units), pl, cur_row['time_jp'])
    if cur_class.direction == 1:
        # 買い方向の場合
        if cur_class.max_plus < upper_gap:
            cur_class.max_plus = upper_gap  # 更新
        if cur_class.max_minus > lower_gap:
            cur_class.max_minus = lower_gap  # 更新
    else:
        # 売り方向の場合
        if cur_class.max_plus < lower_gap:
            cur_class.max_plus = lower_gap  # 更新
        if cur_class.max_minus > upper_gap:
            cur_class.max_minus = upper_gap  # 更新

    # (3)LCチェンジを実行
    for i, lc_item in enumerate(cur_class.lc_change):
        # print("    LC_Change:", lc_item['lc_trigger_range'], cur_class.unrealized_pl_low, cur_class.unrealized_pl_high)
        if 'done' in lc_item or cur_class.position_keeping_time_sec <= lc_item['time_after']:
            # print("   　　⇒OUT", cur_class.position_keeping_time_sec, lc_item['time_after'])
            # if 'done' in lc_item:
            # print("        ⇒OUT", lc_item['done'])
            continue

        if cur_class.unrealized_pl_low < lc_item['lc_trigger_range'] < cur_class.unrealized_pl_high:
            new_lc_range = lc_item['lc_ensure_range']  # マイナス値もありうるため注意
            if cur_class.direction == 1:
                # 買い方向の場合
                new_lc_price = cur_class.target_price + new_lc_range
            else:
                # 売り方向の場合
                new_lc_price = cur_class.target_price - new_lc_range
            print("　　   ★LC底上げ", cur_class.lc_price, "⇒", new_lc_price, cur_row['time_jp'])
            cur_class.comment = "LC_c"
            cur_class.lc_change_done(i)  # Doneの追加
            cur_class.lc_price = new_lc_price  # 値の更新


def execute_position_finish(cur_class, cur_row, cur_row_index):
    """
    クラスに更新された情報を基に、ポジションに対する操作を行う
    ポジション解消や変更があった場合は、クラスの変数を直接変更してしまう。
    """
    global gl_total, gl_total_per_units, gl_results_list  # グローバル変数の変更宣言

    # 変数の簡略化
    target_price = cur_class.target_price
    lc_price = cur_class.lc_price
    tp_price = cur_class.tp_price

    # ■最終的にはここでクローズする。LCとTPの処理
    pl = 0  # 念のための初期値だが、このままの場合は異常発生時
    comment = ""
    # スプレッドを考慮した、アジャスターを用意(買いの場合は、売り価格で終了する（-0.004 = スプレッド÷2)。売りの場合はその逆）
    adjuster = -0.004 if cur_class.direction == 1 else 0.004

    # 価格による判定
    if cur_row['low'] + adjuster < lc_price < cur_row["high"] + adjuster:
        print("　　 ■ロスカットします", cur_class.name, cur_row['time_jp'], cur_row['low'], lc_price, cur_row["high"])
        pl = (lc_price - cur_class.target_price) * cur_class.direction
        cur_class.settlement_price = lc_price  # ポジション解消価格
        cur_class.position_is_live = False
        cur_class.done = True
        if cur_class.comment == "LC_c":
            # LCChangeがあった場合は、LCチェンジによるLC.ただしプラス域とは限らない。
            pass
        else:
            cur_class.comment = "LC"
    if cur_row['low'] + adjuster < tp_price < cur_row['high'] + adjuster and cur_class.position_is_live:  # （ロスカット優先）
        print("　　 ■利確します", cur_class.name, cur_row['time_jp'], cur_row['low'], tp_price, cur_row["high"])
        pl = (tp_price - cur_class.target_price) * cur_class.direction
        cur_class.settlement_price = tp_price  # ポジション解消価格
        cur_class.position_is_live = False
        cur_class.done = True
        cur_class.comment = "TP"

    # 時間による判定
    # print("   時間的トレード解消判定", cur_class.position_keeping_time_sec, "> 規定Sec", cur_class.position_timeout_sec, cur_class.unrealized_pl)
    if cur_class.position_keeping_time_sec > cur_class.position_timeout_sec:  # and cur_class.unrealized_pl < 0:
        # 本番ではマイナス継続が1分続いた場合だが、ここではマイナスでありかつ時間が経過なので、ある程度ずれる。ただマイナスはほぼ変わりない。
        print("    Trade解消(マイナス×時間)", cur_class.position_keeping_time_sec, "> 規定Sec",
              cur_class.position_timeout_sec)
        # 本番では、膠着状態における解消も実施しているが、ここではいったん除外
        pl = (cur_row['close'] - cur_class.target_price) * cur_class.direction
        cur_class.settlement_price = cur_row['close']  # ポジション解消価格（ここは暫定的にOpen価格
        cur_class.position_is_live = False
        cur_class.done = True
        cur_class.comment = "Tout"

    # 情報書き込み＆決済
    if not cur_class.position_is_live:
        print("　　   取得価格", cur_class.target_price, "決済価格", cur_class.settlement_price)
        # ポジション解消時にTarget PriceとTP/LC priceでの損益がPLに格納されているので、これを格納する
        cur_class.realized_pl = pl * abs(cur_class.units)  # 含み損益の更新（Unitsをかけたもの）　マイナス値を持つ
        cur_class.realized_pl_per_units = pl  # 含み損益（Unitsに依存しない数） マイナス値を持つ
        # print(pl * abs(cur_class.units), pl, cur_row['time_jp'])
        gl_total += cur_class.realized_pl
        gl_total_per_units += cur_class.realized_pl_per_units
        result_dic = {
            "time": cur_class.order_time,
            "res": cur_class.comment,
            "take": cur_class.target_price,
            "end": cur_class.settlement_price,
            "end_time": cur_row['time_jp'],
            "name": cur_class.name,
            "pl": round(cur_class.realized_pl, 3),
            "pl_per_units": round(cur_class.realized_pl_per_units, 3),
            "max_plus": cur_class.max_plus,
            "max_minus": cur_class.max_minus,
            "priority": cur_class.priority,
            "position_keeping_time": cur_class.position_keeping_time_sec,
            "take_position_price": cur_class.target_price,
            "settlement_price": cur_class.settlement_price,
            "tp_price": cur_class.tp_price,
            "lc_price": cur_class.lc_price
        }
        gl_results_list.append(result_dic)


def main_analysis_and_create_order():
    """
    5分足のデータを解析し、オーダーを発行する。
    発行後は別関数で、5秒のデータで検証する
    """
    global gl_classes, gl_test

    # ５秒足を１行ずつループし、５分単位で解析を実行する
    for index, row_s5 in trimmed_s5_df.iterrows():
        if index / 1000 == 0:
            print("■■■", row_s5['time_jp'], "■■■", index, "行目/", len(trimmed_s5_df), "中")


        # 【解析処理】分が5の倍数であれば、解析を実施する
        dt = str_to_time(row_s5['time_jp'])  # 時間に変換
        if dt.minute % 5 == 0 and dt.second == 0:  # 各5分0秒で解析を実行する
            analysis_df = find_analysis_dataframe(d5_df_r, row_s5['time_jp'])  # 解析用の5分足データを取得する
            print("★検証", row_s5['time_jp'], "行数", len(analysis_df))
            # print(analysis_df.head(5))
            # print(analysis_df.tail(5))
            if len(analysis_df) < gl_need_to_analysis:
                # 解析できない行数しかない場合、実施しない（5秒足の飛びや、取得範囲の関係で発生）
                print("   解析実施しません", len(analysis_df), "行しかないため（必要行数目安[固定値ではない]",
                      gl_need_to_analysis)
                continue  # returnではなく、次のループへ
            else:
                # ★★★ 解析を呼び出す
                analysis_result = im.inspection_warp_up_and_make_order(analysis_df)
                if not analysis_result['take_position_flag']:
                    # オーダー判定なしの場合、次のループへ（5秒後）
                    continue

                # ■（オプショナルな機能）ここでオーダーの重なりによる、オーダー発行有無の確認を実施する
                if len(gl_classes) != 0:
                    # 既存のオーダーが存在する場合
                    new_exe_order = analysis_result['exe_orders'][0]
                    new_exe_order_d = new_exe_order['direction']
                    print("★★★★★追加オーダーテスト")
                    for i, item_temp in enumerate(gl_classes):  # exist_position = classes[0] は何がダメ？？
                        if i == 0:  # とりあえずオーダーリストの最初（オーダーが一つだけを想定）
                            print(item_temp.name, item_temp.order_time)
                            exist_life = item_temp.position_is_live
                            exist_direction = item_temp.direction
                            exist_priority = item_temp.priority
                            exist_pl = item_temp.unrealized_pl
                            exist_keep_position_sec = item_temp.position_keeping_time_sec
                    print(exist_direction)
                    if exist_life:
                        # ポジションがある場合のみ
                        if exist_direction != new_exe_order_d:
                            # 方向が異なるときは、入れる可能性あり
                            print(" 方向が異なる")
                            pass
                            if new_exe_order['priority'] > exist_priority:
                                # 新規が重要オーダーの場合、このまま登録する
                                print("　　高プライオリティ　入れる")
                                pass
                            else:
                                if exist_pl < 0:
                                    # マイナスの場合
                                    if exist_keep_position_sec < 6 * 5 * 60:
                                        # 経過時間が立っていない場合、横いれしない
                                        print("  時間経過なし　いれない")
                                        continue
                                    else:
                                        # 経過時間がたっている場合、上書きする
                                        print("  時間経過　入れる")
                                        pass
                                else:
                                    # プラスの時 は様子見
                                    print("  プラス域のため様子見")
                                    continue
                        else:
                            # 方向が同じときは、上書きしない
                            print(" 同方向のためいれない")
                            continue

                # ★★★ クラスをリセット＆オーダーをクラスに登録する
                gl_classes = []  # リセット
                order_time = row_s5['time_jp']
                for i_order in range(len(analysis_result['exe_orders'])):
                    # print(analysis_result['exe_orders'][i_order])
                    analysis_result['exe_orders'][i_order]['order_time'] = order_time  # order_time追加（本番marketだとない）
                    gl_classes.append(Order(analysis_result['exe_orders'][i_order]))
                    gl_order_list.append({"time": order_time, "name": analysis_result['exe_orders'][i_order]['name']})

        # 【実質的な検証処理】各クラスを巡回し取得、解消　を5秒単位で実行する
        for i, each_c in enumerate(gl_classes):
            # すでに実行済の場合は実行しない
            if each_c.done:
                continue

            # 処理を実施する(ポジション取得～解消まで）
            if not each_c.position_is_live:
                # ポジションがない場合は、取得判定
                # print("    取得待ち", row_s5['low'], row_s5['high'], each_c.target_price)
                update_order_information_and_take_position(each_c, row_s5, index)
            else:
                # 現状をアップデートする
                update_position_information(each_c, row_s5, index)
                # ロスカ（利確）判定や、LCチェンジ等の処理を行う
                execute_position_finish(each_c, row_s5, index)


# オーダーのデモ
demo = {
    "target_price": 149.735,
    "tp_price": 150.284,
    "lc_price": 149.704,
    "name": "1番目",
    "order_time": "2024/10/21 16:45:00",
    "order_timeout": 150 * 60, "units": 100,
    "lc_change_waiting_second": 4 * 5 * 60,
    "priority": 0,
    "lc_change": [
        {"lc_change_exe": True, "lc_trigger_range": 0.038, "lc_ensure_range": -0.05},
        {"lc_change_exe": True, "lc_trigger_range": 0.048, "lc_ensure_range": 0.04},
        {"lc_change_exe": True, "lc_trigger_range": 0.07, "lc_ensure_range": 0.05},
        {"lc_change_exe": True, "lc_trigger_range": 0.10, "lc_ensure_range": 0.07},
        {"lc_change_exe": True, "lc_trigger_range": 0.15, "lc_ensure_range": 0.10},
        {"lc_change_exe": True, "lc_trigger_range": 0.20, "lc_ensure_range": 0.16},
        {"lc_change_exe": True, "lc_trigger_range": 0.25, "lc_ensure_range": 0.21}
    ]
}

# 最初の一つをインスタンスを生成する  150.284 149.834
gl_classes = []

# グローバルでの宣言
oa = classOanda.Oanda(tk.accountIDl, tk.access_tokenl, "live")  # クラスの定義
gl_start_time = datetime.datetime.now()  # 検証時間の計測用
gl_total = 0  # トータル価格
gl_total_per_units = 0  # トータル価格（ユニットによらない）
gl_need_to_analysis = 60  # 調査に必要な行数
gl_results_list = []
gl_order_list = []

# 現在時刻を取得しておく（データの保存用等）
gl_now = datetime.datetime.now().replace(microsecond=0)  # 現在の時刻を取得
gl_start_time_str = str(gl_now.month).zfill(2) + str(gl_now.day).zfill(2) + "_" + \
             str(gl_now.hour).zfill(2) + str(gl_now.minute).zfill(2) + str(gl_now.second).zfill(2)

# 解析のための「5分足」のデータを取得
exist_data = True
if exist_data:
    rescsv_path = 'C:/Users/taker/OneDrive/Desktop/oanda_logs/20231026071000_test_m5_df.csv'
    d5_df_r = pd.read_csv(rescsv_path, sep=",", encoding="utf-8")
else:
    m5_count = 5000  # 何足分取得するか？ 解析に必要なのは60足（約5時間程度）が目安。固定値ではなく、15ピーク程度が取れる分）
    m5_loop = 2  # 何ループするか
    jp_time = datetime.datetime(2024, 10, 29, 21, 0, 0)  # to
    search_file_name = gene.time_to_str(jp_time)
    euro_time_datetime = jp_time - datetime.timedelta(hours=9)
    euro_time_datetime_iso = str(euro_time_datetime.isoformat()) + ".000000000Z"  # ISOで文字型。.0z付き）
    params = {"granularity": "M5", "count": m5_count, "to": euro_time_datetime_iso}  # コツ　1回のみ実行したい場合は88
    data_response = oa.InstrumentsCandles_multi_exe("USD_JPY", params, m5_loop)
    d5_df = data_response['data']
    d5_df_r = d5_df.sort_index(ascending=False)  # 時系列を逆にしたものが解析用！
    pd.set_option('display.max_columns', None)
    print("解析用5分足データ")
    start_time = d5_df.iloc[0]['time_jp']
    end_time = d5_df.iloc[-1]['time_jp']
    d5_df.to_csv(tk.folder_path + gene.str_to_filename(start_time) + '_test_m5_df.csv', index=False, encoding="utf-8")
    print(d5_df_r.head(5))
    print(d5_df_r.tail(5))
    print("5分足での取得時刻は", start_time, "-", end_time, len(d5_df), "行")
    print("実際の解析時間は", d5_df.iloc[gl_need_to_analysis]['time_jp'], "-", end_time)


# 検証のための「5秒足」のデータを取得（解析用と同範囲のデータをとってしまう(最初の方が少し不要とはなる)。解析が5分足の場合×60行分取得すればよい）
end_time_euro = d5_df.iloc[-1]['time']  # Toに入れるデータ（これは解析用と一致させたいため、基本固定）
all_need_row = m5_count * 60 * m5_loop
if m5_count * 60 > 5000:
    # 5000を超えてしまう場合はループ処理が必要(繰り返しデータで使うため、少し多めに取ってしまう。5000単位をN個の粒度）
    loop_for_5s = math.ceil(all_need_row / 5000)
    s5_count = 5000
    trimming = (5000 * loop_for_5s - all_need_row) + (gl_need_to_analysis * 60)
    print("   5S検証：必要な行", all_need_row, "5000行のループ数", loop_for_5s, "多く取得できる行数",
          5000 * loop_for_5s - all_need_row)
else:
    # 5000以下の場合は、一回で取得できる
    s5_count = m5_count * 60  # シンプルに5分足の60倍
    loop_for_5s = 1  # ループ回数は1回
    trimming = gl_need_to_analysis * 60  # 実際に検証で使う範囲は、解析に必要な分を最初から除いた分。
params = {"granularity": "S5", "count": s5_count, "to": end_time_euro}  # 5秒足で必要な分を取得する
data_response = oa.InstrumentsCandles_multi_exe("USD_JPY", params, loop_for_5s)
s5_df = data_response['data']  # 期間の全5秒足を取得する  (これは解析に利用しないため、時系列を逆にしなくて大丈夫）
print("")
print("検証用データ")
start_s5_time = s5_df.iloc[0]['time_jp']
end_s5_time = s5_df.iloc[-1]['time_jp']
s5_df.to_csv(tk.folder_path + gene.str_to_filename(start_s5_time) + '_test_s5_df.csv', index=False, encoding="utf-8")
# print(s5_df.head(1))
# print(s5_df.tail(1))
print("検証時間の総取得期間は", start_s5_time, "-", end_s5_time, len(s5_df), "行")
trimmed_s5_df = s5_df[trimming:]
trimmed_s5_df = trimmed_s5_df.reset_index(drop=True)  # インデクスの再振り
start_trimmed_s5_time = trimmed_s5_df.iloc[0]['time_jp']
end_trimmed_s5_time = trimmed_s5_df.iloc[-1]['time_jp']
print("トリム後（実際に使う）5秒足のDFの期間は", start_trimmed_s5_time, end_trimmed_s5_time, len(trimmed_s5_df), "行")

print("")
print("")
print("検証開始")
main_analysis_and_create_order()

# 結果表示部
print("●●検証終了●●")
fin_time = datetime.datetime.now()
print("●オーダーリスト（約定しなかったものが最下部の結果に表示されないため、オーダーを表示）")
gene.print_arr(gl_order_list)
print("●結果リスト")
gene.print_arr(gl_results_list)
print("●検証を始めた時間と終わった時間", gl_start_time, fin_time)
print("●実際の解析時間(5分足 再表示)", d5_df.iloc[gl_need_to_analysis]['time_jp'], "-", end_time,
      len(d5_df.iloc[gl_need_to_analysis]), "行(", len(d5_df), "中)")
print("●実際の検証時間(トリム後5秒足 再表示)", start_trimmed_s5_time, end_trimmed_s5_time, len(trimmed_s5_df), "行(",
      len(s5_df), "中)")
print("●オーダーの個数", len(gl_order_list), "、約定した個数", len(gl_results_list))
print("●プラスの個数", len([item for item in gl_results_list if item["pl"] >= 0]), ", マイナスの個数",
      len([item for item in gl_results_list if item["pl"] < 0]))
print("●最終的な合計", round(gl_total, 3), round(gl_total_per_units, 3))

# 結果処理部
result_df = pd.DataFrame(gl_results_list)  # 結果の辞書配列をデータフレームに変換
try:
    result_df.to_csv(tk.folder_path + gl_start_time_str + '_main_analysis_ans.csv', index=False, encoding="utf-8")
    result_df.to_csv(tk.folder_path + 'main_analysis_ans_latest.csv', index=False, encoding="utf-8")
except:
    print("書き込みエラーあり")  # 今までExcelを開きっぱなしにしていてエラーが発生。日時を入れることで解消しているが、念のための分岐
    result_df.to_csv(tk.folder_path + gl_start_time_str + 'main_analysis_ans.csv', index=False, encoding="utf-8")
    pass

# 終了（LINEを送る）
# dataFrameから情報を取得する方法
plus_df = result_df[result_df["pl"] >= 0]  # PLがプラスのもの（TPではない。LCでもトレール的な場合プラスになっているため）
minus_df = result_df[result_df["pl"] < 0]
memo = ("現実通りのLCChange+LC縮小")
tk.line_send("test fin 【結果】", round(gl_total, 3), ",\n"
             , "【検証期間】", d5_df.iloc[gl_need_to_analysis]['time_jp'], "-", end_time, ",\n"
             , "【+域/-域の個数】", len(plus_df), ":", len(minus_df), ",\n"
             , "【+域/-域の平均値】", round(plus_df['pl_per_units'].mean(), 3), ":", round(minus_df['pl_per_units'].mean(), 3), ",\n"
             , "【条件】", memo, ",\n参考:処理開始時刻", gl_now
             )
