import copy
import datetime  # 日付関係
import json
import numpy as np
import fBlockInspection as fTurn
import fGeneric as gene


#　ピーク一覧作成&分割
def peaks_collect_main(*args):
    """
    引数は、
    第一引数は、データフレームとする（dr_f)
    第二引数は任意で、ピークの最低必要個数を受け取る（max_peak_num)　これはループ時間の削減が目的。
    これらは配列として受け取る。(ちなみに辞書で受け取る場合は**argsで受け取る必要あり
    :param agrs:
    :return:
    """
    # peaksを求める
    if len(args) == 2:
        print("      (pi)peaks数指定あり", args[1])
        all_peaks = peaks_collect_all(args[0], args[1])
    else:
        # print(" peaks数指定なし")
        all_peaks = peaks_collect_all(args[0])

    # ピークが1つしか存在しない場合、イレギュラーが発生する
    if len(all_peaks) == 1:
        return {"all_peaks": []}
        # print(" 検証等で起きるイレギュラー")
        # all_peaks_include_around_base = copy.deepcopy(all_peaks[i])
        # all_peaks_include_around_base['next'] = {}
        # all_peaks_include_around_base['previous'] = copy.deepcopy(all_peaks[i + 1])  # ['time']

    # all_peaksから大きなデータ（計算に使ったものを付与したもの）を除去しておく
    for i in range(len(all_peaks)):
        del all_peaks[i]['ans']

    # 各ピークに、時間的に次のピークの情報を追加していく（ただし入れ子(next(next())になってしまった、入れ替えていくことにする）
    all_peaks_include_around = []
    for i in range(len(all_peaks)):
        # print("現在", all_peaks[i])
        all_peaks_include_around_base = copy.deepcopy(all_peaks[i])
        if i == 0:
            # latestは次がない
            all_peaks_include_around_base['next'] = {}
            all_peaks_include_around_base['previous'] = copy.deepcopy(all_peaks[i+1])#['time']
        elif i == len(all_peaks) - 1:
            # 最後は前がない
            all_peaks_include_around_base['next'] = copy.deepcopy(all_peaks[i-1])#['time']
            all_peaks_include_around_base['previous'] = {}
        else:
            # print(" Next", all_peaks[i - 1])
            # print(" previous", all_peaks[i + 1]['time'])
            all_peaks_include_around_base['next'] = copy.deepcopy(all_peaks[i-1])#['time']
            all_peaks_include_around_base['previous'] = copy.deepcopy(all_peaks[i+1])#['time']
        # 累積して、all_peaksと同様のものを作成する（中身にnextとpreviousがついただけ）
        all_peaks_include_around.append(all_peaks_include_around_base)
        # print(" 追加分", all_peaks_include_around_base)

    # ピークの強度を求め、追記しておく（前後が長く、自身が極端に短い場合、一瞬の折り返しとみて強度が弱いこととする）
    for i in range(len(all_peaks_include_around)):
        item = all_peaks_include_around[i]
        curr_gap = item['gap']
        prev_gap = item['previous'].get('gap', 0)  # previousがある場合はその値と、ない場合は０を返す）
        next_gap = item['next'].get('gap', 0)  # nextがある場合はその値、ない場合は０を返す
        # print("  PeakInfoMaking（previous_now(1)_next)", round(prev_gap/curr_gap, 1), 1, round(next_gap/curr_gap, 1),
        # item['time'])
        if (prev_gap != 0 and next_gap != 0) and (prev_gap/curr_gap > 3 and next_gap/curr_gap > 3):
            # どちらかがおかしい場合は、ちょっと除外したい。ただし、ピークが5pips超えている場合は一つとみなす（★★5分足の場合）
            if curr_gap >= 0.05:
                # print("      (pi)強度の低いPeak発見したがスルー（比率的に弱いが、5pips以上あり)", item['time'])
                item['peak_strength'] = 1
            else:
                # print("      (pi)強度の低いPeak発見", item['time'])
                item['peak_strength'] = 0.5
        else:
            # 自身が問題なくても、Nextに除外すべきPeak（Strengthが1）を持つ場合、自身もStrengthを1にする。（previousではない）
            # if i != 0 and all_peaks_include_around[i-1]['peak_strength'] == 1: この書き方だと、以降全部 strength=1となる。。
            # そのため一つ前が、上記と同じ条件を満たす場合、とする
            if i != 0:
                temp_item = all_peaks_include_around[i-1]
                curr_gap_t = temp_item['gap']
                prev_gap_t = temp_item['previous'].get('gap', 0)  # previousがある場合はその値と、ない場合は０を返す）
                next_gap_t = temp_item['next'].get('gap', 0)  # nextがある場合はその値、ない場合は０を返す
                if (prev_gap_t != 0 and next_gap_t != 0) and (prev_gap_t/curr_gap_t > 3 and next_gap_t/curr_gap_t > 3):
                    # 時間的に次のPeakが、除外すべきpeakとなる場合は、自身も１
                    item['peak_strength'] = 0.5
                else:
                    item['peak_strength'] = 1
            else:
                item['peak_strength'] = 1

    return {
        "all_peaks": all_peaks_include_around
    }


# ピーク一覧を作成（求める範囲もここで指定する）
def peaks_collect_all(*args):
    """
    リバースされたデータフレーム（直近が上）から、極値をN回分求める
    基本的にトップとボトムが交互のエータを返却する。
    直近(または指定の時間~）３時間前分を取得することにする
    :return:
    """
    # 基本検索と同様、最初の一つは除外する
    df_r = args[0]  # 引数からデータフレームを受け取る
    df_r = df_r[1:]

    # ループの場合時間がかかるので、何個のPeakを取得するかを決定する(引数で指定されている場合は引数から受け取る）
    if len(args) == 2:
        max_peak_num = args[1]
    else:
        max_peak_num = 15  # N個のピークを取得する

    peaks = []  # 結果格納用
    for i in range(222):
        if len(df_r) == 0:
            break
        # answers = fTurn.turn_each_inspection(df_r)
        ans = fTurn.each_block_inspection_skip(df_r)
        # ans = answers # 返り値には色々な値があるので、指定の返却値を取る（簡易版ではない）
        df_r = df_r[ans['count']-1:]
        if ans['direction'] == 1:
            # 上向きの場合
            peak_latest = ans['data'].iloc[0]["inner_high"]
            peak_peak = ans['data'].iloc[0]["high"]
            peak_oldest = ans['data'].iloc[-1]["inner_low"]
        else:
            # 下向きの場合
            peak_latest = ans['data'].iloc[0]["inner_low"]
            peak_peak = ans['data'].iloc[0]["low"]
            peak_oldest = ans['data'].iloc[-1]["inner_high"]

        peak_info = {
            'time': ans['data'].iloc[0]['time_jp'],
            'peak': peak_latest,
            'peak_peak': peak_peak,
            'time_old': ans['data'].iloc[-1]['time_jp'],
            'peak_old': peak_oldest,
            'direction': ans['direction'],
            'body_ave': ans['body_ave'],
            'count': len(ans["data"]),
            'gap': round(abs(peak_latest-peak_oldest), 3),
            'latest_price': ans['latest_price'],
            "latest2_dir": ans['latest2_dir'],
            "skip_counter": ans['skip_counter'],
            "include_large": ans['include_large'],
            'ans': ans,
        }
        if len(peaks) != 0:
            if peaks[-1]['time'] == peak_info['time']:
                # 最後が何故か重複しまくる！時間がかぶったらおしまいにしておく
                break
            else:
                peaks.append(peak_info)  # 全部のピークのデータを取得する
        else:
            peaks.append(peak_info)  # 全部のピークのデータを取得する

        # ピーク数の上限を設定する（ループ時に多いと時間がかかるため）
        if len(peaks) > max_peak_num:
            return peaks
    return peaks


def peaks_collect_main_not_skip(*args):
    """
    引数は、
    第一引数は、データフレームとする（dr_f)
    第二引数は任意で、ピークの最低必要個数を受け取る（max_peak_num)　これはループ時間の削減が目的。
    これらは配列として受け取る。(ちなみに辞書で受け取る場合は**argsで受け取る必要あり
    :param agrs:
    :return:
    """
    # peaksを求める
    if len(args) == 2:
        print("      (pi)peaks数指定あり", args[1])
        all_peaks = peaks_collect_all_not_skip(args[0], args[1])
    else:
        # print(" peaks数指定なし")
        all_peaks = peaks_collect_all_not_skip(args[0])

    # all_peaksから大きなデータ（計算に使ったものを付与したもの）を除去しておく
    for i in range(len(all_peaks)):
        del all_peaks[i]['ans']

    # ■各ピークに、時間的に前後のピークの情報を追加していく（ただし入れ子(next(next())にならないようにする）
    all_peaks_include_around = []
    for i in range(len(all_peaks)):
        # print("現在", all_peaks[i])
        all_peaks_include_around_base = copy.deepcopy(all_peaks[i])
        if i == 0:
            # latestは次がない
            all_peaks_include_around_base['next'] = {}
            all_peaks_include_around_base['previous'] = copy.deepcopy(all_peaks[i+1])#['time']
        elif i == len(all_peaks) - 1:
            # 最後は前がない
            all_peaks_include_around_base['next'] = copy.deepcopy(all_peaks[i-1])#['time']
            all_peaks_include_around_base['previous'] = {}
        else:
            # print(" Next", all_peaks[i - 1])
            # print(" previous", all_peaks[i + 1]['time'])
            all_peaks_include_around_base['next'] = copy.deepcopy(all_peaks[i-1])#['time']
            all_peaks_include_around_base['previous'] = copy.deepcopy(all_peaks[i+1])#['time']
        # 累積して、all_peaksと同様のものを作成する（中身にnextとpreviousがついただけ）
        all_peaks_include_around.append(all_peaks_include_around_base)
        # print(" 追加分", all_peaks_include_around_base)

    # ■ピークの強度を求め、追記しておく（前後が長く、自身が極端に短い場合、一瞬の折り返しとみて強度が弱いこととする）
    for i in range(len(all_peaks_include_around)):
        item = all_peaks_include_around[i]
        curr_gap = item['gap']
        prev_gap = item['previous'].get('gap', 0)  # previousがある場合はその値と、ない場合は０を返す）
        next_gap = item['next'].get('gap', 0)  # nextがある場合はその値、ない場合は０を返す
        # print("  PeakInfoMaking（previous_now(1)_next)", round(prev_gap/curr_gap, 1), 1, round(next_gap/curr_gap, 1),
        # item['time'])
        if (prev_gap != 0 and next_gap != 0) and (prev_gap/curr_gap > 3 and next_gap/curr_gap > 3):
            # どちらかがおかしい場合は、ちょっと除外したい。ただし、ピークが5pips超えている場合は一つとみなす（★★5分足の場合）
            if curr_gap >= 0.05:
                # print("      (pi)強度の低いPeak発見したがスルー（比率的に弱いが、5pips以上あり)", item['time'])
                item['peak_strength'] = 1
            else:
                # print("      (pi)強度の低いPeak発見", item['time'])
                item['peak_strength'] = 0.5
        else:
            # 自身が問題なくても、Nextに除外すべきPeak（Strengthが1）を持つ場合、自身もStrengthを1にする。（previousではない）
            # if i != 0 and all_peaks_include_around[i-1]['peak_strength'] == 1: この書き方だと、以降全部 strength=1となる。。
            # そのため一つ前が、上記と同じ条件を満たす場合、とする
            if i != 0:
                temp_item = all_peaks_include_around[i-1]
                curr_gap_t = temp_item['gap']
                prev_gap_t = temp_item['previous'].get('gap', 0)  # previousがある場合はその値と、ない場合は０を返す）
                next_gap_t = temp_item['next'].get('gap', 0)  # nextがある場合はその値、ない場合は０を返す
                if (prev_gap_t != 0 and next_gap_t != 0) and (prev_gap_t/curr_gap_t > 3 and next_gap_t/curr_gap_t > 3):
                    # 時間的に次のPeakが、除外すべきpeakとなる場合は、自身も１
                    item['peak_strength'] = 0.5
                else:
                    item['peak_strength'] = 1
            else:
                item['peak_strength'] = 1

    latest = all_peaks_include_around[0]
    river = all_peaks_include_around[1]  # 最新のピーク（リバーと呼ぶ。このCount＝２の場合、折り返し直後）
    turn = all_peaks_include_around[2]  # 注目するポイント（ターンと呼ぶ）
    flop3 = all_peaks_include_around[3]  # レンジ判定用（プリフロップと呼ぶ）
    # print("  (pi)<対象>:運用モード")
    # print("  (pi)Latest", latest)
    # print("  (pi)RIVER", river)
    # print("  (pi)TURN ", turn)
    # print("  (pi)FLOP3", flop3)
    return {
        "all_peaks": all_peaks_include_around
    }


def peaks_collect_all_not_skip(*args):
    """
    リバースされたデータフレーム（直近が上）から、極値をN回分求める
    基本的にトップとボトムが交互のエータを返却する。
    直近(または指定の時間~）３時間前分を取得することにする
    :return:
    """
    # 基本検索と同様、最初の一つは除外する
    df_r = args[0]  # 引数からデータフレームを受け取る
    df_r = df_r[1:]

    # ループの場合時間がかかるので、何個のPeakを取得するかを決定する(引数で指定されている場合は引数から受け取る）
    if len(args) == 2:
        max_peak_num = args[1]
    else:
        max_peak_num = 15  # N個のピークを取得する

    peaks = []  # 結果格納用
    for i in range(222):
        if len(df_r) == 0:
            break
        ans = fTurn.each_block_inspection(df_r)
        # ans = fTurn.each_block_inspection_skip(df_r)
        # ans = answers # 返り値には色々な値があるので、指定の返却値を取る（簡易版ではない）
        df_r = df_r[ans['count']-1:]
        if ans['direction'] == 1:
            # 上向きの場合
            peak_latest = ans['data'].iloc[0]["inner_high"]
            peak_peak = ans['data'].iloc[0]["high"]
            peak_oldest = ans['data'].iloc[-1]["inner_low"]
        else:
            # 下向きの場合
            peak_latest = ans['data'].iloc[0]["inner_low"]
            peak_peak = ans['data'].iloc[0]["low"]
            peak_oldest = ans['data'].iloc[-1]["inner_high"]

        peak_info = {
            'time': ans['data'].iloc[0]['time_jp'],
            'peak': peak_latest,
            'peak_peak': peak_peak,
            'time_old': ans['data'].iloc[-1]['time_jp'],
            'peak_old': peak_oldest,
            'direction': ans['direction'],
            'body_ave': ans['body_ave'],
            'count': len(ans["data"]),
            'gap': round(abs(peak_latest-peak_oldest), 3),
            'latest_price': ans['latest_price'],
            # "latest2_dir": ans['latest2_dir'],
            "include_large": ans['include_large'],
            'ans': ans,
        }
        if len(peaks) != 0:
            if peaks[-1]['time'] == peak_info['time']:
                # 最後が何故か重複しまくる！時間がかぶったらおしまいにしておく
                break
            else:
                peaks.append(peak_info)  # 全部のピークのデータを取得する
        else:
            peaks.append(peak_info)  # 全部のピークのデータを取得する

        # ピーク数の上限を設定する（ループ時に多いと時間がかかるため）
        if len(peaks) > max_peak_num:
            break

    # 余計なデータを消しておく
    # for d in peaks:
    #     d.pop('ans', None)
    return peaks



# ピーク一覧で作成したものを、TopとBottomに分割する
# def peaks_collect_separate(peaks):
#     """
#     peaks_collect_allで生成された情報（ピーク一覧）を、
#     山と谷に分割する
#     :param peaks:
#     :return:
#     """
#     # 一番先頭[0]に格納されたピークは、現在＝自動的にピークになる物となるため、
#     # print(peaks)
#     # print(peaks[1:])
#     # 直近のピークまでのカウント（足数）を求める
#     # print("■■渡されたもの", len(peaks))
#     # f.print_arr(peaks)
#     # print("■■渡されたものここまで")
#     print(" セパレート関数")
#     print(peaks)
#
#     from_last_peak = peaks[0]
#     # 最新のは除外しておく（余計なことになる可能性もあるため）
#     # peaks = peaks[1:]
#     # 上、下のピークをグルーピングする
#     top_peaks = []
#     bottom_peaks = []
#     for i in range(len(peaks)):
#         if peaks[i]['direction'] == 1:
#             # TopPeakの場合
#             top_peaks.append(peaks[i])  # 新規に最後尾に追加する
#         else:
#             # bottomPeakの場合
#             bottom_peaks.append(peaks[i])
#
#     # 直近のピークがどっち向きなのか、
#     if from_last_peak['direction'] == 1:
#         latest_peak_group = bottom_peaks  # 最新を含む方向性が上向きの場合、直近のピークは谷方向となる
#         second_peak_group = top_peaks
#     else:
#         latest_peak_group = top_peaks
#         second_peak_group = bottom_peaks
#
#
#     # 軽量版のデータも作っておく
#     top_peaks_right = top_peaks.copy()
#     for i in range(len(top_peaks_right)):
#         del top_peaks_right[i]['ans']
#     bottom_peaks_light = bottom_peaks.copy()
#     for i in range(len(bottom_peaks_light)):
#         del bottom_peaks_light[i]['ans']
#     print(" セパレート関数最後")
#     print(peaks)
#
#     # 表示用
#     # print("TOPS")
#     # f.print_arr(top_peaks_right)
#     # print("BOTTOMS")
#     # f.print_arr(bottom_peaks_light)
#
#
#     return {
#         "all_peaks": peaks,
#         "tops": top_peaks,
#         "bottoms": bottom_peaks,
#         "from_last_peak":  from_last_peak,  # 最後のPeakから何分経っているか(自身[最新]を含み、lastPeakを含まない）
#         "latest_peak_group": latest_peak_group,  # 直近からみて直近のグループ
#         "second_peak_group": second_peak_group,
#         "tops_light": top_peaks_right,
#         "bottoms_light": bottom_peaks_light
#     }


#########↑ここまでは頻発


# def peaks_collect_main_del(df_r):
#     """
#     ピークを集めるが、一部条件に合わないピークを削除する
#     :param df_r:
#     :return:
#     """
#     all_peaks = peaks_collect_all(df_r)
#     del_target = []
#     for i in range(len(all_peaks)):
#         b = all_peaks[i]
#         if i == 0:
#             # 先頭の場合はスキップ
#             pass
#         elif i == len(all_peaks) - 1:
#             # 最終の場合もスキップ
#             pass
#         else:
#             l = all_peaks[i-1]
#             o = all_peaks[i+1]
#             # 除外検討
#             if b['gap'] < l['gap'] * 0.2 and b['gap'] < o['gap'] * 0.2:
#                 print("除外対象",b['gap'], b['time'], o['time'])
#                 del_target.append(b)
#                 del_target.append(o)
#             if b['gap'] < 0.01:
#                 print("除外対象小さい",b['gap'], b['time'],o['time'])
#                 del_target.append(b)
#                 del_target.append(o)
#     # print("削除対象")
#     # 削除を行う
#     new_ans = all_peaks.copy()
#     for i in range(len(del_target)):
#         del_t = del_target[i]
#         new_ans = [s for s in new_ans if s != del_t]
#     # 回答を生成する
#     sep = peaks_collect_separate(new_ans)
#     print("TOPS")
#     f.print_arr(sep['tops_light'])
#     print('BOTTOMS')
#     f.print_arr(sep['bottoms_light'])
#     return sep


def peaks_only_big_mountain(df_r):
    """
    検出したピークから、以下のピークを削除する（ピークのみの抽出）
    ・ピークを生成する両足の比率が0.5~1.5以上の場合
    :param df_r:
    :return:
    """
    peaks = peaks_collect_all(df_r)  # ピークを取得
    big_peaks_light = []  # 結果を格納する
    big_peaks = []  # 結果（ピーク値のみ）を格納する
    skip_flag = 0
    for i in range(len(peaks)):
        if i+1 >= len(peaks):
            break

        # ２個目以降は確認していく
        if skip_flag == 0:
            now = peaks[i]
            older = peaks[i+1]  # 次のピーク（時系列的にはOlder）
            #  通常はこちら
            # N個以上連続の同方向かつある程度の高低差がある場合、または、N個以下でも高低差がある場合
            if (now['count'] >= 3 and now['gap']> 0.04) or now['gap'] > 0.05:
                # 自身(now)が適切なサイズと判断される場合　（小さすぎない）
                print("   〇", now['time'], now['time_oldest'], now['direction'], now['count'], now['gap'])
                big_peaks_light.append({
                    "time": now['time'],
                    "peak": now['peak'],
                    "time_oldest": now['time_oldest'],
                    "peak_oldest": now['peak_oldest'],
                    "direction": now['direction'],
                    "count": now['count'],
                    "gap": now['gap']
                })
                big_peaks.append(now)
            else:
                # 条件を満たしていない物は、削除する（＝追加しない）
                print("   無視", now['time'], now['time_oldest'], now['direction'], now['count'], now['gap'])
                skip_flag = 0
        else:
            skip_flag = 0
    return {
        "big_peaks_light": big_peaks_light,
        "big_peaks": big_peaks,
    }


def peaks_range_detect(df_r):
    """
    ピークを集めるが、一部条件に合わないピークを削除する
    :param df_r:データ
    :param foot 何足分無視するか
    :param price_f 何円以下を無視するか
    :return:
    """
    # ①現在Close価格が、データ範囲の中で最後にいつ登場したか（髭の場合はノーカウント）
    latest_price = df_r.iloc[0]['close']
    print(latest_price, df_r.iloc[0]['time_jp'])
    df = df_r.sort_index(ascending=True)  # 逆順（古いのが上）に並び替える
    for i in range(len(df)):
        if df.iloc[i]['inner_low'] < latest_price < df.iloc[i]['inner_high']:
            # 対象の値を含み無物を発見
            oldest_time = df.iloc[i]['time_jp']
            break
    print(oldest_time)


# ごちゃごちゃしているかどうか
def one_peak_inspection(same_peaks_group):
    """
    片方のピーク軍をもらい、特徴を算出する
    :return:
    """
    # ①ギザギザ度合いを見る（時間的に見周しているかどうか）
    time_gap_arr = []
    min_time_gap_minute = 10000
    max_time_gap_minute = 0
    for i in range(len(same_peaks_group)):
        # 次ピークとの時間差を計算
        if i + 1 >= len(same_peaks_group):  # 範囲を指定
            pass
        else:
            time_gap = round((gene.str_to_time(same_peaks_group[i]['time']) - gene.str_to_time(same_peaks_group[i + 1]['time'])).seconds / 60, 3)
        # 情報を蓄積する
        if min_time_gap_minute > time_gap:  # 最小値の場合、確保
            min_time_gap_minute = time_gap
        if max_time_gap_minute < time_gap:  # 最大値の場合、確保
            max_time_gap_minute = time_gap
        time_gap_arr.append(time_gap)
        ave_time_gap_minute = round(np.mean(np.array(time_gap_arr)), 3)  # 平均値の取得
    if max_time_gap_minute < 40 and ave_time_gap_minute < 30:
        state = "ごちゃごちゃしている"
    else:
        state = "変動幅大き目"
    print("平均値:", ave_time_gap_minute, "最大値:", max_time_gap_minute, "最小値", min_time_gap_minute, "リスト", time_gap_arr)
    print(state)


def calChangeFromPeaks(same_peaks_group):
    """
    同方向（山か谷か）における、近二個分の変化状況を把握する
    :param same_peaks_group:
    :return:
    """
    memo = ""
    line_send = 0
    # (0)情報の収集
    target_peak = same_peaks_group[0]['peak']
    target_time = same_peaks_group[0]['time']
    print("target_peak:", target_peak, target_time)
    # (1)直近二つのピークの情報
    gene.delYear(target_time)
    gap_latest2 = round(target_peak - same_peaks_group[1]['peak'], 3)  # 直近二つのピークの上下差(変化後＝０＝最新　ー　直前）
    time_gap_latest2 = round((gene.str_to_time(target_time) - gene.str_to_time(same_peaks_group[1]['time'])).seconds / 60, 3)
    memo_latest = gene.delYear(target_time) + "-" + gene.delYear(same_peaks_group[1]['time']) + \
                  "[" + str(target_peak) + "-" + str(same_peaks_group[1]['peak']) + "]" + \
                  "方向" + str(same_peaks_group[0]['direction']) + " GAP" + str(gap_latest2)
    print(memo_latest)

    # （２）直近のピークと、一番上下方向が近い同方向のピークを検索（３個分）
    comp_target = same_peaks_group[:3]  # 出来れば近いほうがいいので直近３個分の同方向ピークにする
    min_gap = 100  # とりあえず大きな値
    max_gap_time_gap = gene.str_to_time(target_time) + datetime.timedelta(minutes=1)
    skip_peaks = []
    index = 1  # 1からスタート
    for i in range(len(comp_target)):
        if i == 0:
            # ０個目は同価格になるのでスルー
            ans_dic = comp_target[i]  # 初期値の設定
        else:
            comp_item = comp_target[i]
            if abs(target_peak - comp_item['peak']) < min_gap:
                ans_dic = comp_item  # Gap最小場所の更新
                min_gap = target_peak - comp_item['peak']  # peakGapの更新
                max_gap_time_gap = round((gene.str_to_time(target_time) - gene.str_to_time(comp_item['time'])).seconds / 60, 3)
                index = i
            else:
                skip_peaks.append(comp_item)
    # 情報表示print("一番ギャップの少ないピーク", index)
    gap_min = round(abs(ans_dic['peak'] - target_peak), 3)
    price_min = ans_dic['peak']
    time_min = ans_dic['time']
    gap_time = gene.str_to_time(target_time) - gene.str_to_time(time_min)
    memo_mini_gap = gene.delYear(target_time) + "-" + gene.delYear(time_min) + \
                    "[" + str(target_peak) + "-" + str(price_min) + "]" + \
                    "方向" + str(same_peaks_group[0]['direction']) + " GAP" + str(gap_min) + " TimeGap" + str(gap_time)

    return {
        "gapLatest": gap_latest2,
        "tiltLatest": time_gap_latest2,
        "gapMin": gap_min,
        "memoLatest": memo_latest,
        "memoMiniGap": memo_mini_gap,
        "data": same_peaks_group,
    }


def latestFlagFigure(peak_informations):
    # ■■二つのPeakLineの関係性の算出
    # ■各々の変化状況を取得する
    print("■直近ピーク軍解析")
    latest_info = calChangeFromPeaks(peak_informations['latest_peak_group'])
    print("■セカンドピーク群解析")
    second_info = calChangeFromPeaks(peak_informations['second_peak_group'])
    print("■統合解析")
    latest_peak_gap = latest_info['data'][0]['peak'] - second_info['data'][0]['peak']  # 直近ピーク間の差分（大きさ）

    # ■二つがどのような形状か（平行、広がり、縮まり）
    # print(latest_info)
    # print()
    # print(second_info)
    lg = latest_info['gapLatest']
    sg = second_info['gapLatest']
    # 平行かの確認
    send_para = 0
    print("差分", abs(lg - sg))
    if abs(lg - sg) < 0.005:  # ほぼ平行とみなす場合（GAPの差）
        print("平行(", latest_peak_gap, ")")
        para_memo = "平行 " + str(round(latest_peak_gap, 3)) + ")"
        send_para = 1
    else:
        para_memo = "Not平行"
    para_memo = latest_info['memoLatest'] + para_memo

    # フラッグ形状の確認
    level_change = 0.011  # これより小さい場合、傾きが少ないとみなす
    slope_change = 0.02  # これより大きい場合、傾きが大きいとみなす
    ans_memo = ""
    send_ans = 0
    if abs(lg) < level_change:  # 「直近分が」単品の水平基準を満たす
        if slope_change <= abs(sg):  # 「セカンド分が」傾きが大きいとみなされる場合（セカンド群が）
            if sg < 0:  # 「セカンド分」が下向きの場合
                ans_memo = "直近水平(逆フラ)" + str(round(latest_peak_gap, 3)) + ")"
                send_ans = 1
            else:  # 「セカンド分が」上向きの場合
                ans_memo = "直近水平(正フラ)" + str(round(latest_peak_gap, 3)) + ")"
                send_ans = 1
        elif level_change < abs(sg) < slope_change:  # 「セカンド分の」傾きが中途半端な場合
            print("直近水平")
        else:  # 「セカンド分」の傾きが水平の場合
            print("直近水平&平行")
    elif abs(sg) < level_change:  # 「セカンド分が」水平の場合
        if slope_change <= abs(lg):  # 「直近分が」傾きが大きいとみなされる場合（セカンド群が）
            if lg < 0:  # 「直近分が」が下向きの場合
                ans_memo = "セカ水平(逆フラ)" + str(round(latest_peak_gap, 3)) + ")"
                send_ans = 1
            else:  # 「直近分が」上向きの場合
                ans_memo = "セカ水平(正フラ)" + str(round(latest_peak_gap, 3)) + ")"
                send_ans = 1
        elif level_change < abs(lg) < slope_change:  # 「直近分が」傾きが中途半端な場合
            print("セカンド水平")
        else:  # 「セカンド分」の傾きが水平の場合
            print("セカンド水平&平行")
    ans_memo = latest_info['memoLatest'] + ans_memo

    return {
        "para_send": send_para,
        "para_memo": para_memo,
        "ans_memo": ans_memo,
        "ans_send": send_ans
    }


# ボトムライン、トップラインを抽出する
def horizon_line_detect(same_peaks_group):
    # print(same_peaks_group)
    if same_peaks_group[0]['direction'] == 1:
        reverse = True  # 降順
    else:
        reverse = False  # 昇順

    # 並び替え（価格順)
    one_peak_sorted = sorted(same_peaks_group, key=lambda x: x['peak'], reverse=reverse)
    # 情報を絞る(価格と時間だけに）
    peak_prices = []
    for i in range(len(one_peak_sorted)):
        peak_prices.append({
            "price": one_peak_sorted[i]['peak'],
            "time": one_peak_sorted[i]['time']
        })
    # 上から（配列的に０番から。Topの場合は降順、Bottomの場合は昇順）
    gap_limit = 0.011
    combi_arr_ave = []
    combi_arr_info = []
    adj = 0  # アジャスター（一回グルーピングされたものは、BasePriceとして採用しない）
    # peak_prices = sorted(peak_prices, key=lambda x: x['time'], reverse=True)  # 時間準に並び替える
    for i in range(len(peak_prices)):
        i_adj = i + adj  # iにアジャスター分を追加する
        if i_adj >= len(peak_prices):
            break
        base_price = peak_prices[i_adj]['price']
        combi = []
        combi_info = []
        combi.append(base_price)
        combi_info.append(peak_prices[i_adj])
        # print("■Base", base_price, peak_prices)
        for y in range(len(peak_prices)):
            # print("  Target", peak_prices[y])
            if same_peaks_group[0]['direction'] == 1:
                if base_price > peak_prices[y]['price']:
                    if peak_prices[y]['price'] >= base_price - gap_limit:
                        # Baseと近い場合（Gapの内側にいる場合）、さらに、自身より小さい数字に対して比較する
                        combi.append(peak_prices[y]['price'])
                        combi_info.append(peak_prices[y])
                        adj = y  # adjに登録する
                        # print("  追加", peak_prices[y]['price'],peak_prices[y])
                    else:
                        # print("  OUT", peak_prices[y]['price'], base_price)
                        break  # もはや比較の必要なし
            else:
                if base_price < peak_prices[y]['price']:
                    if peak_prices[y]['price'] <= base_price + gap_limit:
                        # Baseと近い場合（Gapの内側にいる場合）、さらに、自身より大きい数字に対して比較する
                        combi.append(peak_prices[y]['price'])
                        combi_info.append(peak_prices[y])
                        adj = y  # adjに登録する
                        # print("  追加", peak_prices[y]['price'],peak_prices[y])
                    else:
                        # print("  OUT", peak_prices[y]['price'], base_price)
                        break  # もはや比較の必要なし
        # print("★", combi)
        # print("　⇒", combi_info)
        if len(combi) == 1:
            pass  # 自分自身の場合、処理しない
        else:
            # ぞれぞれの結果を格納していく
            # ①combi  [148.409, 148.414]
            # ①combi_info [{'price': 148.409, 'time': '2023/09/23 05:35:00'}, {'price': 148.414, 'time': '2023/09/23 05:15:00'}]
            # ↓　まとめると
            #  combi_arr_ave ⇒[①148.412, ②148.388]
            # ①[{'ave': 148.412, 'all': [{'price': 148.409, 'time': '2023/09/23 05:35:00'}, {'price': 148.414, 'time': '2023/09/23 05:15:00'}]},
            # ② {'ave': 148.388, 'all': [{'price': 148.376, 'time': '2023/09/23 04:40:00'}, {'price': 148.392, 'time': '2023/09/23 04:20:00'}]
            # 　上の内容に、time等も追加されている。
            combi_arr_ave.append(round(np.mean(np.array(combi)), 3))
            # TopとBottomで収集する内容が異なる場合（最高平均価格か最低平均価格か）
            combi_arr_info.append({
                "ave": round(np.mean(np.array(combi)), 3),
                "all": combi_info,
            })
            # print("最終結果に追加", combi_arr)

    # 何も入っていない場合、０を入れておく。
    if len(combi_arr_ave) == 0:
        combi_arr_ave.append(0)
        combi_arr_info.append(0)

    # 情報を追加する
    if len(combi_arr_ave) >= 2:
        combi_arr_ave.sort(reverse=reverse)
        most_ave = combi_arr_ave[0]
        mini_ave = combi_arr_ave[-1]
    else:
        most_ave = combi_arr_ave[0]
        mini_ave = combi_arr_ave[0]

    return {
        "most_ave": most_ave,
        "mini_ave": mini_ave,
        "ave_arr": combi_arr_ave,
        "info_arr": combi_arr_info,
    }


def current_position_with_horizon_line(df_r):
    print(df_r.head(3))
    print(df_r.tail(3))
    peak_information = peaks_collect_main_del(df_r)
    print("TOP情報")
    gene.print_arr(peak_information['tops_right'])
    top_ave = horizon_line_detect(peak_information['tops'])
    print("tops-ave", top_ave['ave'])
    print(top_ave['info'])
    if top_ave['ave'][0] != 0:
        latest_peak_minute = round((datetime.datetime.now() - gene.str_to_time(top_ave['info'][0]['all'][0]['time'])).seconds / 60, 0)
        print(latest_peak_minute, "前")

    print("BOTTOM情報")
    gene.print_arr(peak_information['bottoms_right'])
    bottom_ave = horizon_line_detect(peak_information['bottoms'])
    print("bottoms_ave", bottom_ave['ave'])
    print(bottom_ave['info'])
    if bottom_ave['ave'][0] != 0:
        latest_peak_minute = round((datetime.datetime.now() - gene.str_to_time(bottom_ave['info'][0]['all'][0]['time'])).seconds / 60, 0)
        print(latest_peak_minute, "前")

    # 現在価格
    now_price = df_r.iloc[0]['close']
    # TopLineの最大値
    max_top_line = top_ave['ave'][0]
    # BottomLineの最大値
    min_bottom_line = bottom_ave['ave'][0]

    # 条件分岐
    if max_top_line != 0 and min_bottom_line != 0:
        # どっちともが存在する場合
        if min_bottom_line < now_price < max_top_line:
            # 現在価格がトップとボトムの間にいる場合（レンジの途中?)
            state = "真ん中"
        elif now_price > max_top_line:
            # 現在価格がトップを超えている場合
            state = "上限越え(下限もあり)"
        elif now_price < min_bottom_line:
            # 現在価格がボトムを切っている場合
            state = "下限越え(上限もあり)"
    elif max_top_line == 0 and min_bottom_line == 0:
        state = "上限下限無し"
    else:
        if max_top_line != 0:
            # 上限がある場合
            if now_price > max_top_line:
                state = "上限越え(下限無し)"
            else:
                state = "上限以内(下限無し)"
        else:
            # 下限上がる場合
            if now_price < min_bottom_line:
                state = "下限越え(上限なし）"
            else:
                state = "下限以内(上限なし)"

    print(state, "now-top-bottom", now_price, max_top_line, min_bottom_line)


def line_tilt_arr_detect(same_peaks_group):
    """
    片方の、直近N個のピークの組み合わせの傾きのリストを算出する
    :param same_peaks_group:
    :return:
    """
    latest_range = 2

    same_peaks_group = same_peaks_group[:latest_range]
    # 情報を絞る(価格と時間だけに）
    peak_prices = []
    for i in range(len(same_peaks_group)):
        peak_prices.append({
            "price": same_peaks_group[i]['peak'],
            "time": same_peaks_group[i]['time']
        })
    # 上から（配列的に０番から。時系列順（０が最新））
    # f.print_arr(peak_prices)
    tilt_arr = []
    tilt_info_arr = []
    for i in range(len(peak_prices)):
        for y in range(len(peak_prices)):
            # print("  Target", peak_prices[y])
            if i < y:  # 組み合わせなので範囲を絞る
                pips_zouka_y = (peak_prices[i]['price'] - peak_prices[y]['price']) * 100  # 縦軸の変化（時後ー時前）
                time_zouka_x = round((gene.str_to_time(peak_prices[i]['time']) - gene.str_to_time(peak_prices[y]['time'])).seconds / 60, 3)
                tilt = round(pips_zouka_y / time_zouka_x, 3)  # 傾き
                tilt_combi = {
                    "latest_price": peak_prices[i]['price'],
                    "latest_time": peak_prices[i]['time'],
                    "older_price": peak_prices[y]['price'],
                    "older_time": peak_prices[y]['time']
                }
                tilt_arr.append(tilt)  # 傾きのみの配列を生成
                tilt_info_arr.append(   # 傾き＋情報を配列にする
                    {
                        "tilt": tilt,
                        "tilt_combi": tilt_combi
                     }
                )
    gene.print_arr(tilt_arr)
    gene.print_arr(tilt_info_arr)
    return tilt_info_arr


def inspection_test(df_r):
    # 情報を取得
    peaks = peaks_collect_main_del(df_r)
    print("■TOP情報")
    one_peak_inspection(peaks['tops'])
    horizon_info = horizon_line_detect(peaks['tops'])
    print("Most", horizon_info['most_ave'])
    print("Mini", horizon_info['mini_ave'])
    print("tops-ave", horizon_info['ave_arr'])
    print(horizon_info['info_arr'])

    print("■BOTTOM情報")
    one_peak_inspection(peaks['bottoms'])
    horizon_info = horizon_line_detect(peaks['bottoms'])
    print("Most", horizon_info['most_ave'])
    print("Mini", horizon_info['mini_ave'])
    print("tops-ave", horizon_info['ave_arr'])
    print(horizon_info['info_arr'])

    print("■新機能確認中")
    print("★TOPS")
    tops = line_tilt_arr_detect(peaks['tops'])
    print(tops)
    print("★BOTTOMS")
    bottoms = line_tilt_arr_detect(peaks['bottoms'])
    # p.current_position_with_horizon_line(df_r)
    horizon_arr = []
    temp_arr = []
    temp = ""
    for t in range(len(tops)):
        for b in range(len(bottoms)):
            t_tilt = tops[t]['tilt']  # 上側の傾き
            b_tilt = bottoms[b]['tilt']  # 下側の傾き
            # 関係性を探索する
            if abs(t_tilt - b_tilt) < 0.015:
                if abs(t_tilt) < 0.024 or abs(b_tilt) < 0.024:
                    print("水平")
                    temp = temp + "水平"
                print("平行")
                print(" ", tops[t])
                print(" ", bottoms[b])
                temp = temp + " " + "平行" + '\n'
                temp = temp + json.dumps(tops[t]) + '\n'
                temp = temp + json.dumps(bottoms[t]) + '\n'
                temp = temp + '\n'
                temp_arr.append(temp)
    return temp_arr
