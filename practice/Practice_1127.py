import programs.fTurnInspection as f  # とりあえずの関数集
import pandas as pd
import json
import datetime
import matplotlib.pyplot as plt
import numpy as np
import programs.tokens as tk  # Token等、各自環境の設定ファイル（git対象外）
import programs.classOanda as oanda_class
import programs.fTurnInspection as t  # とりあえずの関数集
import programs.fPeakLineInspection as p  # とりあえずの関数集
import programs.fTurnInspection as fTurn
import programs.fGeneric as f

oa = oanda_class.Oanda(tk.accountIDl, tk.access_tokenl, "live")  # クラスの定義

jp_time = datetime.datetime(2023, 11, 10, 10, 5, 6)
euro_time_datetime = jp_time - datetime.timedelta(hours=9)
euro_time_datetime_iso = str(euro_time_datetime.isoformat()) + ".000000000Z"  # ISOで文字型。.0z付き）
param = {"granularity": "M5", "count": 200, "to": euro_time_datetime_iso}  # 最低５０行
df = oa.InstrumentsCandles_exe("USD_JPY", param)  # 時間指定
df = oa.InstrumentsCandles_multi_exe("USD_JPY", {"granularity": "M5", "count": 200}, 1)  # 直近の場合
df = df["data"]
df.to_csv(tk.folder_path + 'TEST.csv', index=False, encoding="utf-8")  # 直近保存用
df_r = df.sort_index(ascending=False)
print(df_r.head(5))
print(df_r.tail(5))
print("↓↓")
### ↑これより上は消さない

def inspection(df_r):
    """
    (0) 　10時間(５分足120個分）で最高値/底値、外側の抵抗ラインを求める
    (1)

    :return:
    """
    df_r_part = df_r[:140]
    peaks = p.make_peaks_finalize(df_r_part)  # Peaksの算出
    # 最高値の算出
    top_peaks = peaks['tops']
    top_peaks_sorted = sorted(top_peaks, key=lambda x: x['peak'], reverse=True)  # LCで降順
    highest_price = top_peaks_sorted[0]['peak']
    # 最底値の算出
    bottom_peaks = peaks['bottoms']
    bottom_peaks_sorted = sorted(bottom_peaks, key=lambda x: x['peak'], reverse=False)  # LCで降順
    lowest_price = bottom_peaks_sorted[0]['peak']

    # 群衆ピークLine価格の算出（TOP-Bottomの１０分の１（およそ３Pips）を群衆基準とする）
    scope = (highest_price - lowest_price) / 10
    scope = 0.01
    # 最高値から群集ピークを求める（最も多い群衆を算出する）
    max_group = 0
    max_group_line = 0
    max_group_time = 0
    top_lines = []
    for i in range(len(top_peaks_sorted)):
        base_price = top_peaks_sorted[i]['peak']  # この価格からScope分に何個ピークがあるかを確認する
        counter = 0
        for y in range(len(top_peaks_sorted)-i):
            # print(" cal", base_price, top_peaks_sorted[i+y]['peak'])
            if base_price - top_peaks_sorted[i+y]['peak'] <= scope:
                counter += 1
            else:
                break
        # 今回のbase_priceに対しての全ての結果を格納する（２個以上の場合）
        if counter >= 2:
            top_lines.append({"base_price": base_price, "counter": counter})
        # 最大Counterの結果のみも格納する
        if counter > max_group:
            max_group = counter
            max_group_line = base_price
            max_group_time = top_peaks_sorted[i]['time']
    # 最底値から群集ピークを求める（最も多い群衆を算出する）
    min_group = 0
    min_group_line = 0
    min_group_time = 0
    bottom_lines = []
    for i in range(len(bottom_peaks_sorted)):
        base_price = bottom_peaks_sorted[i]['peak']  # この価格からScope分に何個ピークがあるかを確認する
        counter = 0
        for y in range(len(bottom_peaks_sorted)-i):
            if bottom_peaks_sorted[i+y]['peak'] - base_price <= scope:
                counter += 1
            else:
                break
        # 今回のbase_priceに対しての全ての結果を格納する（２個以上の場合）
        if counter >= 2:
            bottom_lines.append({"base_price": base_price, "counter": counter})
        # 最大グループ判定
        if counter > min_group:
            min_group = counter
            min_group_line = base_price
            min_group_time = bottom_peaks_sorted[i]['time']

    print("■", df_r_part.iloc[-1]['time_jp'], "-", df_r_part.iloc[0]['time_jp'], " ", round(scope, 3))
    print(" TOP:", top_peaks_sorted[0]['peak'], "bottom", bottom_peaks_sorted[0]['peak'])
    print(" TopLine", max_group_line, max_group, max_group_time)
    print("  ", top_lines)
    print(" BotLine", min_group_line, min_group, min_group_time)
    print("  ", bottom_lines)

    # (2)　直近２個の傾きを求める
    latest = 2
    if latest == 1:
        target_peaks = top_peaks
    else:
        target_peaks = bottom_peaks
    latest_peak = target_peaks[0]['peak']
    oldest_peak = target_peaks[1]['peak']
    y_gap = latest_peak - oldest_peak
    # x_gap = (latest_peak - oldest_peak) * 1000
    print(latest_peak, oldest_peak, y_gap,)
    print(target_peaks[0])
    print(target_peaks[1])
    time_gap_seconds = (f.str_to_time(target_peaks[0]['time']) - f.str_to_time(target_peaks[1]['time'])).seconds
    x_gap = round(time_gap_seconds / 60)
    print(time_gap_seconds, x_gap)
    print(y_gap, x_gap)
    tilt = (y_gap / x_gap) * 100  # 通常の一次関数のオーダーにしたい
    # tilt = y_gap / x_gap
    print(tilt)


def inspection_block(df_r):
    """

    :param df_r:
    :return:
    """

    df_r = df_r[:30]
    print(df_r.head(1))
    print(df_r.tail(1))
    # 調査幅を取得する（最高値最低値の２０分の１？）
    highest = df_r["high"].max()
    lowest = df_r["low"].min()
    range = (highest - lowest)/20
    print(highest,lowest, range)


def block_inspection_main(df_r):
    print("TurnInspection")
    df_r_part = df_r[:140]
    peaks_info = p.make_peaks_finalize(df_r_part)  # Peaksの算出
    peaks = peaks_info['all_peaks']
    turn_inspection_sub(peaks[0], peaks[1])
    while len(peaks)>3:
        temp = block_inspection_each(peaks)
        peaks = temp['next_peaks']



def block_inspection_each(peaks):
    # f.print_arr(peaks)
    # 戻り状況の確認

    # 直近のブロックの有無と長さを求める
    print("■■ブロック探し")
    # base_price = peaks['all_peaks'][0]['peak']  # とりあえず直近の価格を入れておく
    base_price = (peaks[1]['peak'] + peaks[1]['peak_oldest']) / 2
    rest = 0  # ピーク範囲にないカウント(ピーク数にするか、カウント数にするか？
    rest_max = 2  #
    in_range_count = 0
    end_index = 0
    # print(base_price, peaks[1])
    # print(peaks[1]['time'], peaks[1]['time_oldest'], peaks[1]['peak'], peaks[1]['peak_oldest'], base_price)
    for i, item in enumerate(peaks):
        # 注意　添え字０については対象外（２個目から検証のため。変更の先は気を付けて）
        if i == 0:
            continue

        # peakとpeak_oldestどちらが大きいかを確認する
        if item['peak'] > item['peak_oldest']:
            high = item['peak']
            low = item['peak_oldest']
        else:
            high = item['peak_oldest']
            low = item['peak']
        # print(" ", item, base_price)

        # ベースがピーク範囲にあるか
        if low < base_price < high:
            # 範囲内の場合
            # print(" 　〇")
            in_range_count += 1  # カウンター
            rest = 0  # リセット
            end_peak = item  # 直近から昔に向かってサーチしているので、Endは逆を言えばレンジが始まった時間ともいえる
            end_index = i
        else:
            # 範囲外の場合
            if rest <= rest_max:
                # 4連続以内の範囲外であれば、次のループへ
                rest += 1
            else:
                # 既定のRest連続数を超えたら、ループ終了。ただし初回の場合のみ、直近ピーク情報を返却する
                if in_range_count == 0:
                    end_peak = peaks[0]
                    end_index = i
                else:
                    pass  # end_peakは、それ以外は既に範囲内が存在しており、そこで代入されている。
                break
    # print("結果 Base", base_price,",ピーク貫き数", in_range_count, "REST(＝４である)", rest)
    # print("終了時の方向↓(これを含む）", end_index)
    # print(end_peak)
    # print("次のターゲット")
    next_peaks = peaks[end_index:]
    # print(next_peaks)
    informations = {
        "next_peaks": next_peaks,
        "base_price": base_price,
        "latest": peaks[1],
        "oldest": end_peak,
        "peaks_num": in_range_count,
        "latest_time": peaks[1]["time"],
        "latest_price": peaks[1]["peak"],
        "oldest_time": end_peak['time_oldest'],
        "oldest_price": end_peak["peak_oldest"]
    }
    print(" ", base_price, "," , informations['latest_time'], "(", informations['latest_price'], ")-", informations['oldest_time'], "(",
          informations['oldest_price'], ")", informations['peaks_num'])
    return informations


def turn_inspection_sub(latest, second):
    print("Latest")
    print(latest)
    print("second")
    print(second)
    latest_dir = latest['direction']
    latest_gap = latest['gap']
    latest_count = latest['count']
    second_dir = second['direction']
    second_gap = second['gap']
    second_count = second['count']
    print(latest_dir,latest_count,latest_gap)
    print(second_dir,second_count,second_gap)

    # 戻し状況の確認
    return_ratio = latest_gap / second_gap * 100
    print(return_ratio)
    if return_ratio <= 30:
        print("　ちょい戻し中")
    elif return_ratio <= 70:
        print(" 半分戻り中")
    elif return_ratio <= 100:
        print("等倍戻し中")
    elif return_ratio > 100:
        print(" 突き抜け中")



res = block_inspection_main(df_r[0:60])
# turn_inspection(df_r[0:20])

# print(fTurn.turn_each_inspection(df_r))



# ピーク集を出す
# peaks = p.peaks_only_big_mountain(df_r)
# latest_time = df_r.iloc[0]['time_jp']
# print("Peak,", latest_time)
# f.print_arr(peaks['big_peaks_right'])
# print("Separate")
# each_peaks = p.peaks_collect_separate(peaks['big_peaks'])
# print("Tilt確認")
# print("TOP")
# tilts = p.line_tilt_arr_detect(each_peaks['tops'])
# print(tilts)
# t = tilts[0]['tilt']
# t_time = tilts[0]['tilt_combi']['latest_time']
# t_time_past_sec = round((f.str_to_time(latest_time) - f.str_to_time(t_time)).seconds / 60, 3)
# print("  ", t, t_time, latest_time, t_time_past_sec)
#
#
# print("BOTTOM")
# tilts = p.line_tilt_arr_detect(each_peaks['bottoms'])
# print(tilts)
# t = tilts[0]['tilt']
# t_time = tilts[0]['tilt_combi']['latest_time']
# t_time_past_sec = round((f.str_to_time(latest_time) - f.str_to_time(t_time)).seconds / 60, 3)
# print("  ", t, t_time, latest_time, t_time_past_sec)
# #

# p.peaks_collect_main_del(df_r)


# p.peaks_range_detect(df_r)


# # 情報を取得
# p.inspection_test(df_r)
# #
# print(p.latest_tilt_line_detect(df_r))





# LINEを抽出する
# def line_detect(same_peaks_group):
#     print("ピーク個数", len(same_peaks_group))
#     # f.print_json(same_peaks_group)
#     ans = []
#     ans2 = []
#     for i in range(len(same_peaks_group)):
#         base_price = same_peaks_group[i]['peak']  # 比較元
#         base_time = same_peaks_group[i]['time']  # 比較元
#         base = {"price": base_price, "time": base_time}
#         sets = [base]  # １つのBaseに対する類似値
#         for y in range(len(same_peaks_group)):
#             comp_price = same_peaks_group[y]['peak']  # ループして見ていく
#             if comp_price - 0.015 < base['price'] < comp_price + 0.015:
#                 if i != y:
#                     sets.append({"price": comp_price, "time": same_peaks_group[y]['time']})
#         if len(sets) == 1:
#             pass  # 自身だけの場合は不要
#         else:
#             ans.append(sets)
#             set_a = sorted(sets, key=lambda x: x['time'], reverse=False)
#             # print("★追加対象", set_a)
#             if set_a in ans2:  # 既にまったく同じものが入ってる場合(組み合わせなので)、登録しない（重複削除ができないので、登録しない方向）
#                 # print("入ってる", set_a, "@", ans2)
#                 pass
#             else:
#                 ans2.append(set_a)
#     # print("")
#     pop_target = []
#     for i in range(len(ans2)):
#         base = ans2[i]  # 中身 Baseは自身が、他の誰かに包括されていないかを確かめる（自分が消される）
#         base_len = len(ans2[i])  # 個数
#         for y in range(len(ans2)):
#             if base_len < len(ans2[y]):  # 自分より個数が多いのを見つけた場合（自分を含む、それ以上の情報があるかもしれない）
#                 exist_num = 0
#                 for i_each in range(len(base)):
#                     # print(base[i_each], "と", ans2[y])
#                     if base[i_each] in ans2[y]:
#                         # print("★")
#                         exist_num += 1
#                 if exist_num == len(base):  # 自分が全て相手の一部と一致すれば、自身は消去される。
#                     # print("消すやつ", base)
#                     pop_target.append(i)
#
#     pop_target = sorted(pop_target, reverse=True)
#     for i in range(len(pop_target)):
#         ans2.pop(pop_target[i])
#
#     ave_arr = []
#     for i in range(len(ans2)):
#         total = 0
#         for y in range(len(ans2[i])):
#             total += ans2[i][y]["price"]
#         ave = total / len(ans2[i])
#         print("平均", ave, ans2[i])
#         ave_arr.append(
#             {"ave": ave,
#              "info": ans2[i]
#              }
#         )
#     return ave_arr

# # 近似線の算出関数メイン
# def inspection_tilt(target_list):
#     """
#     引数は、最新が先頭にある、極値のみを抜いたデータ
#     関数の途中で、過去から先頭に並んでいる状況（通常の関数では、直近から先頭に並んでいる）
#     :return:
#     """
#     # print("test", target_list)
#     target_list_r = target_list
#     # target_list_r = list(reversed(target_list))  # 過去を先頭に、並微カエル
#     y = []  # 価格
#     x = []  # 時刻系
#     x_span = 0  # 時系列は０スタート
#     for i in range(len(tops)):
#         p = target_list_r[i]
#         if "time_oldest" in p:
#             # print(p['time_latest'], p['peak_latest'], "-", p['time_oldest'], p['peak_oldest'], p['count'], p['tilt'],
#             #       p['gap'])
#             y.append(p['peak_latest'])  # Y軸方向
#             x.append(x_span)  # X軸方向（時間ではなく、足の数）
#             x_span = x_span + p['count']  # 足の数を増やしていく
#
#     # 近似線の算出
#     x = np.array(x)  # npListに変換
#     y = np.array(y)
#     a, b = reg1dim(x, y)
#     plt.scatter(x, y, color="k")
#     plt.plot([0, x.max()], [b, a * x.max() + b])  # (0, b)地点から(xの最大値,ax + b)地点までの線
#     # plt.show()
#     print("並び替え後(最新が最後）")
#     print(y)
#     print(x)
#     print(a, b)
#     max_price = max(y)
#     min_price = min(y)
#     res = {
#         "max_price": max_price,
#         "min_price": min_price,
#         "data": y
#     }
#     return res
#
#
# # 近似線の算出の計算
# def reg1dim(x, y):
#     n = len(x)
#     a = ((np.dot(x, y)- y.sum() * x.sum()/n)/
#         ((x ** 2).sum() - x.sum()**2 / n))
#     b = (y.sum() - a * x.sum())/n
#     return a, b







