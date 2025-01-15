import copy
import fBlockInspection as fTurn


def make_peaks_finalize(*args):
    """
    引数は、
    第一引数は、データフレームとする（dr_f)
    第二引数は任意で、ピークの最低必要個数を受け取る（max_peak_num)　これはループ時間の削減が目的。
    これらは配列として受け取る。(ちなみに辞書で受け取る場合は**argsで受け取る必要あり
    :param agrs:
    :return:
    """
    # ■導入処理
    dependence_min_peak_gap = 0.05
    # peaksを求める
    if len(args) == 2:
        print("      (pi)peaks数指定あり", args[1])
        all_peaks = make_peaks(args[0], args[1])
    else:
        # print(" peaks数指定なし")
        all_peaks = make_peaks(args[0])
    # ピークが1つしか存在しない場合、イレギュラーが発生するため、空を返却
    if len(all_peaks) == 1:
        return {"all_peaks": []}

    # ■各ピークに、時間的に次のピークの情報を追加していく（ただし入れ子(next(next())になってしまった、入れ替えていくことにする）
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

    # ■ピークの強度を求め、追記しておく（前後が長く、自身が極端に短い場合、一瞬の折り返しとみて強度が弱いこととする）
    for i in range(len(all_peaks_include_around)):
        item = all_peaks_include_around[i]
        curr_gap = item['gap'] if item['gap'] > 0 else 0.00000001  # ０で割った場合のエラーがないようにする。
        prev_gap = item['previous'].get('gap', 0)  # previousがある場合はその値と、ない場合は０を返す）
        next_gap = item['next'].get('gap', 0)  # nextがある場合はその値、ない場合は０を返す
        # print("  PeakInfoMaking（previous_now(1)_next)", round(prev_gap/curr_gap, 1), 1, round(next_gap/curr_gap, 1),
        # item['time'])
        if (prev_gap != 0 and next_gap != 0) and (prev_gap/curr_gap > 3 and next_gap/curr_gap > 3):
            # どちらかがおかしい場合は、ちょっと除外したい。ただし、ピークが5pips超えている場合は一つとみなす（★★5分足の場合）
            if curr_gap >= dependence_min_peak_gap:
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
                curr_gap_t = item['gap'] if item['gap'] > 0 else 0.00000001  # ０で割った場合のエラーがないようにする。
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


def make_peaks(*args):
    """
    リバースされたデータフレーム（直近が上）から、極値をN回分求める
    基本的にトップとボトムが交互のエータを返却する。
    直近(または指定の時間~）３時間前分を取得することにする
    :return:
    """
    # ■引数の整理
    # 基本検索と同様、最初の一つは除外する
    df_r = args[0]  # 引数からデータフレームを受け取る
    df_r = df_r[1:]  # 先頭は省く（数秒分の足のため）
    # ループの場合時間がかかるので、何個のPeakを取得するかを決定する(引数で指定されている場合は引数から受け取る）
    if len(args) == 2:
        max_peak_num = args[1]
    else:
        max_peak_num = 15  # N個のピークを取得する

    # ■処理の開始
    peaks = []  # 結果格納用
    for i in range(222):
        if len(df_r) == 0:
            break
        # peak = fTurn.turn_each_inspection(df_r)
        peak = fTurn.make_peak_with_skip(df_r)

        if peak['direction'] == 1:
            # 上向きの場合
            peak_latest = peak['data'].iloc[0]["inner_high"]
            peak_peak = peak['data'].iloc[0]["high"]
            peak_oldest = peak['data'].iloc[-1]["inner_low"]
        else:
            # 下向きの場合
            peak_latest = peak['data'].iloc[0]["inner_low"]
            peak_peak = peak['data'].iloc[0]["low"]
            peak_oldest = peak['data'].iloc[-1]["inner_high"]

        # 情報累積のためのデータを生成（上で算出した物を付与し、DataFrameを取り除く）
        add_info = {
            "time": peak['data'].iloc[0]['time_jp'],
            "peak": peak_latest,
            "time_old": peak['data'].iloc[-1]['time_jp'],
            "peak_old": peak_oldest,
            "gap": round(abs(peak_latest-peak_oldest), 3),
            "peak_peak": peak_peak
        }
        peak = {**add_info, **peak}
        # peak['time'] = peak['data'].iloc[0]['time_jp']
        # peak['peak'] = peak_latest
        # peak['time_old'] = peak['data'].iloc[-1]['time_jp']
        # peak['peak_old'] = peak_oldest
        # peak['gap'] = round(abs(peak_latest-peak_oldest), 3)
        # peak['peak_peak'] = peak_peak
        peak.pop('data', None)  # DataFrameを削除する# 存在しない場合はエラーを防ぐためにデフォルト値を指定
        peak.pop('data_remain', None)  # DataFrameを削除する
        # 表示時にぱっとわかるように、

        if len(peaks) != 0:
            if peaks[-1]['time'] == peak['time']:
                # 最後が何故か重複しまくる！時間がかぶったらおしまいにしておく
                break
            else:
                peaks.append(peak)  # 情報の蓄積
        else:
            peaks.append(peak)  # 情報の蓄積

        # ■ループ処理
        df_r = df_r[peak['count']-1:]  # 処理データフレームを次に進める
        # ピーク数検索数が上限に達したらループを終了する（ループ時に多いと時間がかかるため）
        if len(peaks) > max_peak_num:
            return peaks
    return peaks


def change_peaks_with_hard_skip(peaks_origin):
    """
    peaksを基にスキップを行う
    ↓このようなケース。②のカウントが３以下、①のピークより③のピークがが低い
      ② / ①
     /\/　
    /③
    この場合、簡易的なPeaksを生成する
    """
    # print("初期値")

    dependence_two_gap_at_most = 0.07

    peaks = peaks_origin.copy()
    # gene.print_arr(peaks)
    adjuster = 0
    for index in range(len(peaks)):  # 中で配列を買い替えるため、for i in peaksは使えない！！
        target_index = index + adjuster
        if len(peaks) - target_index < 3:  # one,two, thrを確保するため、三つは必要
            # print(" 終了")
            break

        one = peaks[target_index]
        two = peaks[target_index + 1]  # これが消える可能性があるピーク
        thr = peaks[target_index + 2]
        # print(target_index)
        # print("  ", one)
        # print("  ", two)
        # print("  ", thr)

        be_merge = False
        if two['count'] <= 3 or (two['count'] <= 5 and two['gap'] <= dependence_two_gap_at_most):  # カウントがアウトでも、ギャップが少なければ飛ばせるとみなす
            # print(" ２が３カウント以下⇒結合判定へ", two['count'])
            if (two['gap'] / one['gap'] <= 0.3 and two['gap'] / thr['gap'] <= 0.56) or (two['gap'] / one['gap'] <= 0.56 and two['gap'] / thr['gap'] <= 0.3):
                # print(" 結合可能", one['time'], "twoを削除し、oneとThreeをつなげる", target_index)
                be_merge = True
                # # 1に情報を集約
                # peaks[target_index]['peak_old'] = thr['peak_old']
                # peaks[target_index]['time_old'] = thr['time_old']
                # peaks[target_index]['count'] = one['count'] + two['count'] + thr['count']
                # peaks[target_index]['previous'] = thr['previous']
                # peaks[target_index]['gap'] = abs(one['peak'] - one['peak_old'])
                # # ２と３を削除する
                # del peaks[target_index+1:target_index + 3]
                # # アジャスターを調整
                # adjuster = adjuster
            else:
                pass
                # print(" 結合不可", round(two['gap'] / one['gap'], 3), round(two['gap'] / thr['gap'], 3))

            # 上下関係がつながっている場合も、スキップする
            # 中央が下り側
            if two['direction'] == -1:
                # print("  　中央下り", thr['peak_old'], two['peak'], "and", two['peak_old'], one['peak'])
                if thr['peak_old'] < two['peak'] and two['peak_old'] < one['peak']:
                    # print("       ⇒結合対象")
                    be_merge = True
            else:
                # print("  　中央登り", thr['peak_old'], two['peak'], "and", two['peak_old'], one['peak'])
                if thr['peak_old'] > two['peak'] and two['peak_old'] > one['peak']:
                    # print("       ⇒結合対象")
                    be_merge = True
        else:
            pass
            # print(" ２が３カウント以上⇒結合不可", two['count'], two['gap'])

        # スキップ処理
        if be_merge:
            # print(" 結合処理")
            # 1に情報を集約
            peaks[target_index + 2]['peak'] = one['peak']
            peaks[target_index + 2]['time'] = one['time']
            peaks[target_index + 2]['count'] = one['count'] + two['count'] + thr['count']
            peaks[target_index + 2]['next'] = one['next']
            peaks[target_index + 2]['gap'] = round(abs(thr['peak'] - thr['peak_old']), 3)
            # ２と３を削除する
            del peaks[target_index:target_index + 2]
            # アジャスターを調整(消去した場合、一つ前にしないとおかしくなる）
            adjuster = -1
        else:
            # 消去しない場合、特に問題なし
            adjuster = 0

    return peaks


def delete_peaks_information_for_print(peak):
    """
    information fix内で、latest等を表示する際、NextとPreviousのせいで、表示が長くなる。
    この二つを除去する
    """
    copy_data = copy.deepcopy(peak)
    copy_data.pop('next', None)
    copy_data.pop('previous', None)
    return copy_data
