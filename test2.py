import pandas as pd

import datetime
import tokens as tk  # Token等、各自環境の設定ファイル（git対象外）
import classOanda as classOanda
import classPosition as classPosition
import fGeneric as gene

# グローバルでの宣言
oa = classOanda.Oanda(tk.accountIDl, tk.access_tokenl, "live")  # クラスの定義
# ↓時間指定
jp_time = datetime.datetime(2024, 10, 15, 14, 30, 0)
euro_time_datetime = jp_time - datetime.timedelta(hours=9)
euro_time_datetime_iso = str(euro_time_datetime.isoformat()) + ".000000000Z"  # ISOで文字型。.0z付き）
param = {"granularity": "M5", "count": 85, "to": euro_time_datetime_iso}
data_response = oa.InstrumentsCandles_exe("USD_JPY", param)
d5_df = data_response['data']
pd.set_option('display.max_columns', None)
print(d5_df)

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
    time1 = str_to_time(time_str_1)
    time2 = str_to_time(time_str_2)

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


def update_order_information_to_open_or_to_cancel(cur_class, cur_row, cur_row_index):
    """
    オーダーが約定するかを確認する関数
    引数は対象のクラス(CurrentClass)と、検証対象のデータ行(CurrentRow)と、そのデータ行のインデックス
    """
    # (1)オーダーの時間を求め、時間切れ判定も実施する
    order_keeping_time_sec = cal_str_time_gap(cur_row['time_jp'], cur_class.order_time)['gap']
    cur_class.order_keeping_time_sec = order_keeping_time_sec  # クラスの内容を更新（オーダー取得までの経過時間として使える。ポジション後は更新しないため）
    if order_keeping_time_sec >= cur_class.order_timeout_sec:
        print("タイムアウトです", cur_class.name)
        # クラス内容の更新
        cur_class.done = True

    # (2)取得判定を実施する　（同一行で取得⇒ロスカの可能性はここでは考えない）
    target_price = cur_class.target_price
    if cur_row['low'] < target_price < cur_row["high"]:
        print("取得しました", cur_class.name)
        # クラス内容の更新
        cur_row["result"] = cur_class.name + "取得"
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
    position_keeping_time_sec = cal_str_time_gap(cur_row['time_jp'], cur_class.order_time)['gap']  #

    # PLを計算する
    now_price = cur_row['close']  # 暫定としてクローズ価格を現在価格とする
    pl = (now_price - cur_class.target_price) * cur_class.direction  # 現価＞ターゲットだと現価-ターゲットは正の値。買いポジの場合は＋）

    # (2)クラス内の情報を更新する（最大プラスと最大マイナス）
    cur_class.position_keeping_time_sec = position_keeping_time_sec  # 所持継続時間の更新
    cur_class.unrealized_pl = pl  # 含み損益の更新
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


def execute_position_update(cur_class, cur_row, cur_row_index):
    """
    クラスに更新された情報を基に、ポジションに対する操作を行う
    ポジション解消や変更があった場合は、クラスの変数を直接変更してしまう。
    """
    global gl_total  # グローバル変数の変更宣言

    # 変数の簡略化
    target_price = cur_class.target_price
    lc_price = cur_class.lc_price
    tp_price = cur_class.tp_price

    # 単純LCとTPの処理
    if cur_row['low'] < lc_price < cur_row["high"]:
        print("ロスカットします", cur_class.name)
        cur_class.position_is_live = False
        cur_class.done = True
        print("マイナス値は", target_price - lc_price)
    if cur_row['low'] < tp_price < cur_row['high']:
        print("利確します", cur_class.name)
        cur_class.position_is_live = False
        cur_class.done = True
        print("プラス値", tp_price - target_price)
        gl_total += tp_price - target_price


class Order:
    class_total = 0

    def __init__(self, order_dic):
        self.position_is_live = False
        self.position_status = "PENDING" # pending, open ,closed, cancelled
        self.name = order_dic['name']
        self.target_price = order_dic['target_price']
        self.tp_price = order_dic['tp_price']
        self.lc_price = order_dic['lc_price']
        self.done = False
        self.units = 1  # これは数はあまり意味がなく、方向（1or-1かが大切）
        self.direction = self.units / abs(self.units)
        self.order_keeping_time_sec = 0  # 現在オーダーをキープしている時間
        self.order_timeout_sec = 150 * 60
        self.unrealized_pl = 0  # 含み損益
        self.realized_pl = 0
        self.position_keeping_time_sec = 0  # 現在ポジションをキープしている時間
        self.position_timeout_sec = 15 * 60
        self.order_time = order_dic['order_time']
        self.max_plus = 0  # ポジションを持っている中で、一番プラスになっている時を取得
        self.max_minus = 999  # ポジションを持っている中で、一番マイナスになっている時を取得


def data_preparation(start_time):
    """
    データの準備を行う
    5分足と5秒足（全期間取っちゃう？）
    """
    # 5分足

    # 5秒足のデータを取得する
    params = {
        "granularity": "S5",
        "count": 720,  # 約45分= 5秒足×550足分  , 60分　= 720
        "from": start_time,
    }
    df = oa.InstrumentsCandles_multi_exe("USD_JPY", params, 1)['data']


def main():
    """
    MAIN
    """
    # 確認用：classについて確認の表示をする
    for i, item in enumerate(classes):
        print(item.name, item.target_price, item.order_time)
    print("↑ここまでクラスの表示")

    # 処理開始
    for index, row in d5_df.iterrows():
        print(row['time_jp'], "最低価格", row['low'], "最高価格", row['high'], index)

        # 各クラスで検証する
        for i, item in enumerate(classes):
            # すでに実行済の場合は実行しない
            if item.done:
                continue
            # 処理を実施する
            if not item.position_is_live:
                # ポジションがない場合は、取得判定
                update_order_information_to_open_or_to_cancel(item, row, index)
            else:
                # 現状をアップデートする
                update_position_information(item, row, index)
                # ロスカ（利確）判定や、LCチェンジ等の処理を行う
                execute_position_update(item, row, index)

# 最初の一つをインスタンスを生成する
first_order = Order({"target_price": 149.6, "tp_price": 149.73, "lc_price": 148.5, "name": "1番目", "order_time": "2024/10/15 07:25:00", "order_timeout": 150*60})
second_order = Order({"target_price": 149.5, "tp_price": 149.6, "lc_price": 148.4, "name": "2番目", "order_time": "2024/10/15 08:00:00"})
classes = [first_order, second_order]
gl_total = 0  # トータル価格

# main()
test = d5_df.iloc[0]['time']  # 検証開始時間を入れる
print("テストの時間", test)
data_preparation(test)

print("トータル", gl_total)

