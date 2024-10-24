import pandas as pd

import datetime
import tokens as tk  # Token等、各自環境の設定ファイル（git対象外）
import classOanda as classOanda
import classPosition as classPosition
import fGeneric as gene
import datetime
import fInspection_order_Main as im
import math

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
        self.take_position_flag = False
        self.position_is_live = False
        self.position_status = "PENDING" # pending, open ,closed, cancelled
        self.name = order_dic['name']
        self.target_price = order_dic['target_price']
        self.tp_price = order_dic['tp_price']
        self.lc_price = order_dic['lc_price']
        self.done = False
        self.units = order_dic['units']  # これは数はあまり意味がなく、方向（1or-1かが大切）
        self.direction = self.units / abs(self.units)
        self.order_keeping_time_sec = 0  # 現在オーダーをキープしている時間
        self.order_timeout_sec = 150 * 60
        self.unrealized_pl = 0  # 含み損益
        self.unrealized_pl_per_units = 0
        self.realized_pl = 0
        self.realized_pl_per_units = 0
        self.position_keeping_time_sec = 0  # 現在ポジションをキープしている時間
        self.position_timeout_sec = 15 * 60
        self.order_time = order_dic['order_time']
        self.max_plus = 0  # ポジションを持っている中で、一番プラスになっている時を取得
        self.max_minus = 999  # ポジションを持っている中で、一番マイナスになっている時を取得
        self.lc_change_waiting_second = order_dic['lc_change_waiting_second']
        self.lc_change = order_dic['lc_change']
        self.priority = order_dic['priority']

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


def find_5sec_dataframe_row(df, time_jp):
    """
    5秒足のでーれフレームから、指定の時刻以降のデータを取得する
    """
    idx = df[df['time_jp'] == time_jp].index
    if len(idx) == 0:
        return pd.DataFrame()  # 値が存在しない場合は空のデータフレームを返す
    # 最初のインデックスを取得し、その後の行をフィルタ
    return df[df.index > idx[0]]


def update_order_information_to_open_or_to_cancel(cur_class, cur_row, cur_row_index):
    """
    オーダーが約定するかを確認する関数
    引数は対象のクラス(CurrentClass)と、検証対象のデータ行(CurrentRow)と、そのデータ行のインデックス
    """
    # (1)オーダーの時間を求め、時間切れ判定も実施する
    order_keeping_time_sec = cal_str_time_gap(cur_row['time_jp'], cur_class.order_time)['gap']
    cur_class.order_keeping_time_sec = order_keeping_time_sec  # クラスの内容を更新（オーダー取得までの経過時間として使える。ポジション後は更新しないため）
    if order_keeping_time_sec >= cur_class.order_timeout_sec:
        print("   ■タイムアウトです", cur_class.name, cur_row['time_jp'])
        # クラス内容の更新
        cur_class.done = True

    # (2)取得判定を実施する　（同一行で取得⇒ロスカの可能性はここでは考えない）
    target_price = cur_class.target_price
    if cur_row['low'] < target_price < cur_row["high"]:
        print("　　■取得しました", cur_class.name, cur_row['time_jp'], cur_row['low'], cur_row['high'], target_price)
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
    now_price = cur_row['close']  # 暫定としてクローズ価格を現在価格とする ★NowPriceで考えるため、LCやTP priceとは誤差が出る。
    pl = (now_price - cur_class.target_price) * cur_class.direction  # 現価＞ターゲットだと現価-ターゲットは正の値。買いポジの場合は＋）

    # (2)クラス内の情報を更新する（最大プラスと最大マイナス）
    cur_class.position_keeping_time_sec = position_keeping_time_sec  # 所持継続時間の更新
    cur_class.unrealized_pl = pl * abs(cur_class.units)  # 含み損益の更新（Unitsをかけたもの）　マイナス値を持つ
    cur_class.unrealized_pl_per_units = pl  # 含み損益（Unitsに依存しない数） マイナス値を持つ
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
    position_keeping_time_sec = cur_class.position_keeping_time_sec
    if position_keeping_time_sec >= cur_class.lc_change_waiting_second:
        for i, item in enumerate(cur_class.lc_change):
            if 'done' in item:
                continue
            if item['lc_trigger_range'] < pl:
                new_lc_range = item['lc_ensure_range']  # マイナス値もありうるため注意
                if cur_class.direction == 1:
                    # 買い方向の場合
                    new_lc_price = cur_class.target_price + new_lc_range
                else:
                    # 売り方向の場合
                    new_lc_price = cur_class.target_price - new_lc_range
                print("　　   ★LC底上げ", cur_class.lc_price, "⇒", new_lc_price, cur_row['time_jp'])
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
    # 判定
    if cur_row['low'] < lc_price < cur_row["high"]:
        print("　　 ■ロスカットします", cur_class.name, cur_row['time_jp'], cur_row['low'], lc_price, cur_row["high"])
        pl = (lc_price - cur_class.target_price) * cur_class.direction
        settlement_price = lc_price
        cur_class.position_is_live = False
        cur_class.done = True
        comment = "LC"
    if cur_row['low'] < tp_price < cur_row['high'] and cur_class.position_is_live:  # （ロスカット優先）
        print("　　 ■利確します", cur_class.name, cur_row['time_jp'], cur_row['low'], tp_price, cur_row["high"])
        pl = (tp_price - cur_class.target_price) * cur_class.direction
        settlement_price = tp_price
        cur_class.position_is_live = False
        cur_class.done = True
        comment = "TP"
    # 情報書き込み＆決済
    if not cur_class.position_is_live:
        print("　　   取得価格", cur_class.target_price, "決済価格", settlement_price)
        # ポジション解消時にTarget PriceとTP/LC priceでの損益がPLに格納されているので、これを格納する
        cur_class.realized_pl = pl * abs(cur_class.units)  # 含み損益の更新（Unitsをかけたもの）　マイナス値を持つ
        cur_class.realized_pl_per_units = pl  # 含み損益（Unitsに依存しない数） マイナス値を持つ
        # print(pl * abs(cur_class.units), pl, cur_row['time_jp'])
        gl_total += cur_class.realized_pl
        gl_total_per_units += cur_class.realized_pl_per_units
        result_dic = {
            "time": cur_class.order_time,
            "res": comment,
            "take": cur_class.target_price,
            "end": settlement_price,
            "end_time": cur_row['time_jp'],
            "name": cur_class.name,
            "pl": round(cur_class.realized_pl, 3),
            "pl_per_units": round(cur_class.realized_pl_per_units, 3)}
        gl_results_list.append(result_dic)


def main_when_have_order(inspection_data):
    """
    MAIN
    """
    # 5秒足データを絞っておく（重要） 全部やると時間かかる。1時間分であれば、5S足で７２０行分
    inspection_data = inspection_data[:720]

    # 処理開始
    print("回数(オーダー個数)", len(gl_classes))
    for index, row in inspection_data.iterrows():
        # print(row['time_jp'], "最低価格", row['low'], "最高価格", row['high'], index)

        # 各クラスで検証する
        for i, item in enumerate(gl_classes):
            # すでに実行済の場合は実行しない
            if item.done:
                continue

            # 処理を実施する(ポジション取得～解消まで）
            if not item.position_is_live:
                # ポジションがない場合は、取得判定
                update_order_information_to_open_or_to_cancel(item, row, index)
            else:
                # 現状をアップデートする
                update_position_information(item, row, index)
                # ロスカ（利確）判定や、LCチェンジ等の処理を行う
                execute_position_finish(item, row, index)


def main_analysis_and_create_order():
    """
    5分足のデータを解析し、オーダーを発行する。
    発行後は別関数で、5秒のデータで検証する
    """
    global gl_classes, gl_test
    for index, row in d5_df_r.iterrows():
        if index <= gl_need_to_analysis:
            # 解析には50行以上必要
            print("解析期間がないため解析不可", row['time_jp'], index)
            continue

        # 解析を実施
        print(" 解析を実施", index, row['time_jp'], d5_df_r.loc[index]['time_jp'])
        target_df_r = d5_df_r.loc[index:1]
        analysis_result = im.inspection_warp_up_and_make_order(target_df_r)

        # テスト用
        # print("解析", row['time_jp'], index)
        # if index == 190:
        #     result = {"take_position_flag": True, "exe_orders": [demo]}
        # else:
        #     result = {"take_position_flag": False, "exe_orders": [demo]}

        # オーダー指示がある場合は、オーダーとを登録し、検証に移行する
        if analysis_result['take_position_flag']:
            print("  ★★★★★★オーダー取得指示あり", row['time_jp'], len(analysis_result['exe_orders']))
            order_time = d5_df_r.loc[index]['time_jp']  # 10:05の場合、10:00からのピーク
            gl_test.append(row['time_jp'])
            # # ■既存のオーダーを比較し、オーダーを入れるか検討する
            # if len(gl_classes) != 0:
            #     # 既存のオーダーが存在する場合
            #     new_exe_order = analysis_result['exe_orders'][0]
            #     new_exe_order_d = new_exe_order['units'] / abs(new_exe_order['units'])
            #     print("★★★★★追加オーダーテスト")
            #     for i, item in enumerate(gl_classes):  # exist_position = classes[0] は何がダメ？？
            #         if i == 0:
            #             print(item.name, item.order_time)
            #             exist_life = item.position_is_live
            #             exist_direction = item.direction
            #             exist_priority = item.priority
            #             exist_pl = item.unrealized_pl
            #             exist_keep_position_sec = item.position_keeping_time_sec
            #     print(exist_direction)
            #     if exist_life:
            #         # ポジションがある場合のみ
            #         if exist_direction != new_exe_order_d:
            #             # 方向が異なるときは、入れる可能性あり
            #             print(" 方向が異なる")
            #             pass
            #             if new_exe_order['priority'] > exist_priority:
            #                 # 新規が重要オーダーの場合、このまま登録する
            #                 print("　　高プライオリティ　入れる")
            #                 pass
            #             else:
            #                 if exist_pl < 0:
            #                     # マイナスの場合
            #                     if exist_keep_position_sec < 6 * 5 * 60:
            #                         # 経過時間が立っていない場合、横いれしない
            #                         print("  時間経過なし　いれない")
            #                         continue
            #                     else:
            #                         # 経過時間がたっている場合、上書きする
            #                         print("  時間経過　入れる")
            #                         pass
            #                 else:
            #                     # プラスの時 は様子見
            #                     print("  プラス域のため様子見")
            #                     continue
            #         else:
            #             # 方向が同じときは、上書きしない
            #             print(" 同方向のためいれない")
            #             continue

            # ■クラスをリセット＆オーダーを作成する
            gl_classes = []  # リセット
            for i_order in range(len(analysis_result['exe_orders'])):
                print(analysis_result['exe_orders'][i_order])
                analysis_result['exe_orders'][i_order]['order_time'] = order_time  # order_time項目を追加（本番だとない場合があるため）
                gl_classes.append(Order(analysis_result['exe_orders'][i_order]))
                gl_order_list.append({"time": order_time, "name":analysis_result['exe_orders'][i_order]['name']})
            # 対象の5秒足データを生成
            # s5_time = d5_df_r.iloc[index+1]['time_jp']  # order_timeだと1足分足りない（00分オーダーでも、00:05～になってしまう）
            inspection_dataframe_5s = find_5sec_dataframe_row(s5_df, order_time)
            print(inspection_dataframe_5s.head(5))
            # 検証
            main_when_have_order(inspection_dataframe_5s)
        else:
            # オーダーなし
            pass


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
gl_test = []

# グローバルでの宣言
oa = classOanda.Oanda(tk.accountIDl, tk.access_tokenl, "live")  # クラスの定義
gl_total = 0  # トータル価格
gl_total_per_units = 0  # トータル価格（ユニットによらない）
gl_need_to_analysis = 85  # 調査に必要な行数
gl_results_list = []
gl_order_list = []

# 解析のための「5分足」のデータを取得
jp_time = datetime.datetime(2024, 10, 24, 22, 00, 1)
euro_time_datetime = jp_time - datetime.timedelta(hours=9)
euro_time_datetime_iso = str(euro_time_datetime.isoformat()) + ".000000000Z"  # ISOで文字型。.0z付き）
params = {"granularity": "M5", "count": 110, "to": euro_time_datetime_iso}
data_response = oa.InstrumentsCandles_multi_exe("USD_JPY", params, 1)
d5_df = data_response['data']
d5_df_r = d5_df.sort_index(ascending=False)  # 時系列を逆にしたものが解析用！
# d5_df_r = d5_df_r.reset_index(drop=True)
pd.set_option('display.max_columns', None)
print("解析用データ")
print(d5_df_r.head(5))
print(d5_df_r.tail(5))

# 5分足データの必要情報と、5秒足のデータを何行取得すればいいかを計算
start_time = d5_df.iloc[0]['time_jp']
start_time_euro = d5_df.iloc[0]['time']
end_time = d5_df.iloc[-1]['time_jp']
end_time_euro = d5_df.iloc[-1]['time']
between_now = cal_str_time_gap(datetime.datetime.now(), end_time)['gap']
between_sec = cal_str_time_gap(end_time, start_time)['gap']
need_feets_5_sec = between_sec / 5
between_sec = cal_str_time_gap(end_time, start_time)['gap']
loop_for_5s = math.ceil(between_sec/5/5000)
print("5分足での取得時刻は", start_time, "-", end_time)
print("実際の解析時間は", d5_df.iloc[gl_need_to_analysis]['time_jp'], "-", end_time)
# print("検証期間は", between_sec/60, "分(", between_sec, "秒)")
# print("必要な5秒足の足数は", between_sec/5)
# print("要求する行数は5000行 ×", math.ceil(between_sec/5/5000))
#
# # 5秒足のデータを取得する
params = {"granularity": "S5", "count": 5000, "to": end_time_euro}  # 5秒足で必要な分を取得する
data_response = oa.InstrumentsCandles_multi_exe("USD_JPY", params, loop_for_5s)
# data_response = oa.InstrumentsCandles_exe("USD_JPY", params)
s5_df = data_response['data']  # 期間の全5秒足を取得する  (これは解析に利用しないため、時系列を逆にしなくて大丈夫）
print("検証用データ")
print(s5_df.head(5))
print(s5_df.tail(5))

print("")
print("")
print("検証開始")
main_analysis_and_create_order()
print("オーダーがあった時間")
gene.print_arr(gl_test)

print("最終結果", round(gl_total, 3), round(gl_total_per_units, 3))
print("オーダーズ")
gene.print_arr(gl_order_list)
print("結果")
gene.print_arr(gl_results_list)

# test()