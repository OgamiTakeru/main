import fPeakLineInspection as p  # とりあえずの関数集
import fGeneric as f
import fDoublePeaks as dp
import pandas as pd


def find_latest_line_print(df_r):
    """
    ☆表示が沢山あるやつ（ループになると表示が邪魔なので、表示しないのを下に作った）
    直近のピーク価格について調査する。
    ただし直近のピークをどこに取るかは設定が変更できるようにする
    例えば、以下のようなケースの場合、
    0をriver(=latest)の場合と1をriverとする場合がある。
        /\ 1/\
      3/ 2\/ 0\
      /
    ただし、検証したいパターンによっては、知りたいピーク情報はターンとリバーの長さによって変ってくる
         ★
         /\
        /  \/
      \/2  1 0
      この場合は★部（Turn[2]のピーク）
       \
    　  \/\
        　 \/
        　 ☆
      この場合は☆部(River[1]ピーク）
    :param df_r:
    :return:
    """
    # 準備部分（表示や、ピークスの算出を行う）
    target_df = df_r[0:40]
    peaks_info = p.peaks_collect_main(df_r, 15)
    peaks_all = peaks_info["all_peaks"]
    print(" レンジインスペクション")
    # 状況に応じた、ピークポイントの指定  # 添え字は0=latest, 1=river, 2=turn, 3=flop3
    turn2_gap = peaks_all[3]['gap']
    turn_gap = peaks_all[2]['gap']
    riv_gap = peaks_all[1]['gap']
    if 0 < abs(turn_gap - riv_gap) < 0.01:  # ほぼ同じ長さ、を意味したい
        print(" LINEはTurn2で採択（Turn＝River）", turn_gap, riv_gap)
        target_p = 3
    elif turn_gap > riv_gap:
        if abs(turn2_gap - turn_gap) < max(turn_gap,turn2_gap) * 0.1:  # ほぼ同じ長さ、を意味したい
            # ほぼ同じ長さの場合は、同じ長さの端が揃う方を採択する（三角の頂点ではない）
            print(" LINEはTurnを採択", turn2_gap, turn_gap)
            target_p = 2
        elif turn2_gap > turn_gap:
            print(" LINEはTurn2で採択", turn2_gap, turn_gap)
            target_p = 3
        else:
            print(" LINEはturnで採択")
            target_p = 2  # turnのピークを採択
    else:
        # riv_gap > turn_gap
        print("LINEはリバーを採択")
        target_p = 1

    line_strength = 0  # LINE強度の初期値を入れる
    # print(target_df.head(1))
    # print(target_df.tail(1))
    # f.print_arr(peaks_all)

    # (0)最高値と最低値を取得
    # ・現在のピークがどの高さにいるか
    # ・どの価格帯が、濃いかを算出
    # を実施する
    now_price = target_df.iloc[0]['open']
    high = target_df["inner_high"].max()
    low = target_df["inner_low"].min()
    high_ave = target_df["inner_high"].mean()
    low_ave = target_df["inner_low"].mean()

    # (1) 直近のピークが再出現値か
    latest_peak = peaks_all[target_p]['peak']
    latest_dir = peaks_all[target_p]['direction']
    latest_time = peaks_all[target_p]['time']

    # 平均のピークGapを計算する
    sum = 0
    for item in peaks_all:
        sum += item['gap']
    ave = sum / len(peaks_all)
    # print("　　平均ピーク", ave)

    # 分析を開始する
    counter = 0  # 何回同等の値が出現したかを把握する
    range_yen = f.cal_at_least_most(0.01, round(ave * 0.1, 3), 0.035)  # * 0.38?  # 元々0.06の固定値。ただレンジのサイズ感によって変るべき
    same_dir = False
    depth_point_gap = 0  # 今のピークと一番離れている値、かつ、逆方向のポイント（同価格発見のタイミングでリセット）
    depth_point = 0
    depth_point_time = 0
    near_point_gap = 100   # 同価格ではないが、一番近い値、かつ、同方向のポイント(同価格を発見のタイミングでリセットされる）
    near_point = 0
    near_point_time = 0
    same_list = []
    print("　　ダブルトップ判定閾値", range_yen)
    for i, item in enumerate(peaks_all):
        if i < 1 + target_p:
            # 自分自身の場合は探索せず。ただし自分自身は0ではなく１
            continue

        if i > 1 + target_p and latest_peak - range_yen <= item['peak'] <= latest_peak + range_yen:
            # 同価格を発見した場合。
            # if条件の、i>3 は、自分自身、不要な探索をスキップするため。
            # 4以下は、
            # \ 21 /
            # 3\/\/0　
            #  の形状を形成できないため、4以上の場合に探索スタート(i>3はそれを意味する)
            # 最初はcontinueだったが、スキップ部の情報を取得したいため、解除。
            print("　　　同等のピーク発見", item['time'], abs(item['peak']-latest_peak))
            counter += 1

            # 何分前に発生した物かを計算（９０分以内なら、色々考えないとなぁ）
            gap_time_min = f.seek_time_gap_seconds(latest_time, item['time']) / 60
            # 方向に関する判定
            if item['direction'] == latest_dir:
                same_dir = True
                print("　　　同方向の近似ピーク（≒ダブルピークの素）", item['time'], near_point_gap)
                same_list.append({"time": item['time'],
                                  "peak": item['peak'],
                                  "same_dir": same_dir,
                                  "gap_time_min": gap_time_min,
                                  "count_gap": i - target_p,
                                  "gap": round(abs(item['peak'] - latest_peak), 3),
                                  "depth_point_gap": round(depth_point_gap, 3),
                                  'depth_point': depth_point,
                                  "depth_point_time": depth_point_time,
                                  "near_point_gap": round(near_point_gap, 3),
                                  "near_point": near_point,
                                  "near_point_time": near_point_time
                                  })
                # 通過したピーク情報を初期化する
                depth_point_gap = 0
                near_point_gap = 100
            else:
                pass
                # same_dir = False
                # print("　　　逆方向の近似ピーク(= 踊り場的な扱い)")

        else:
            # 通過するピーク（同価格ではない）の場合、記録を残す。
            # print(" CHECK", abs(item['peak']-latest_peak), depth_point_gap, near_point_gap)
            if latest_dir == 1:
                # 下ピークの場合
                #      ↓latest_peak
                # \    /
                #  \/\/

                caldera_gap = latest_peak - item['peak']  # プラス値の場合はカルデラ、－値の場合は三尊形状
                # print(" @", item['time'], caldera_gap)
                # 計算
                if caldera_gap > depth_point_gap and latest_dir != item['direction']:
                    # 最大高度を超える(かつ同方向）場合、入れ替えが発生
                    depth_point_gap = caldera_gap
                    depth_point = item['peak']
                    depth_point_time = item['time']
                if caldera_gap < near_point_gap and latest_dir == item['direction']:
                    # 最も近い価格を超える（かつ逆方向）場合、入れ替えが発生
                    near_point_gap = caldera_gap
                    near_point = item['peak']
                    near_point_time = item['time']
            else:
                # 上ピークの場合
                #   /\/\               \/\  /\/
                # \/    \/                \/  ↑latestPeak
                #      ↑latest_peak
                #  ↑全てプラス値          ↑　near値が－値、depth値がプラス値（これはマイナスにはならない気がする）
                caldera_gap = item['peak'] - latest_peak  # プラス値の場合は山、マイナスの場合は、逆コーンのような形状
                # print(" @", item['time'], near_point_gap,caldera_gap,latest_dir, item['direction'])
                # カルデラ形状
                if caldera_gap > depth_point_gap and latest_dir != item['direction']:
                    # 最大深度を超える(かつ同方向）場合、入れ替えが発生
                    depth_point_gap = caldera_gap
                    depth_point = item['peak']
                    depth_point_time = item['time']
                if caldera_gap < near_point_gap and latest_dir == item['direction']:
                    # 最も近い価格を超える（かつ逆方向）場合、入れ替えが発生
                    near_point_gap = caldera_gap
                    near_point = item['peak']
                    near_point_time = item['time']
    f.print_arr(same_list)
    print("　　個数的には", counter, "回同等のぴーくが発生")
    print("　　対象ピークは", latest_peak, latest_dir)

    # 結果をもとに、谷があるかを判定する
    minus_counter = 0  # 複数発見時にしか利用しないが、LINEで履歴を送りたいので設定。
    if len(same_list) >= 2:
        print("  複数のSamePriceあり。強いLINEではあるが、当たってきてる回数が多いので、抜ける可能性大？")
        minus_counter = 0
        for i in range(len(same_list)):
            if same_list[i]['near_point_gap'] < 0:
                minus_counter += 1  # マイナスはLINEを超えた回数
        if minus_counter > len(same_list) * 0.5:
            # LINE越えが過半数の場合、LINEの信頼度つぃては高くない
            line_strength = 0.5
            print("  複数時　弱強度", minus_counter, len(same_list))
        elif minus_counter >= 1:
            line_strength = 1.5
            print("  複数時　１つ以上LINE越えあり", minus_counter)
        else:
            # LINE越えがない為、LINEの信頼度が比較的高い
            line_strength = 3
            print("  複数時　強強度", minus_counter, len(same_list))
    elif len(same_list) > 0:
        print("  SamePriceが１つあり→　調査する")
        # ニア（逆方向ピーク）までの凹みが、平均ピークのAveの半分以上ある場合は、深さが足りないと判断
        # 候補②　ニアまでの凹みが、直近のピークの３分の１までの折り返しに満たない状態だったら(長さが最大でも0.6倍）、カルデラとみなす
        # print(" バグだし", len(same_list))
        info = same_list[0]  # 同一価格が１つだけが成立（その情報を取得する）
        if info['near_point_gap'] < 0:
            # Nearが－値の場合値の場合 (これは強いLINEとは言いにくい？）
            #   \/\  /\/
            #      \/  ↑latestPeak
            #      ↑Near
            line_strength = 1  # ０は信用０　この場合は一度割って入るが、ある程度の信頼を置きたいため、１
            if info['count_gap'] == 4:
                print("   最小peaksでの成立(一度LINEを超えてから、戻ってきている状態)")
            else:
                print("   一度LINEを超えてから、戻ってきているじょつあい（最小Peaksではない）")
        else:
            # プラス値の場合は、一度もLINEを割ったことがないことになる（強いLINEといえる）
            #     ↓(間の底値がNearPoint） ここが６割程度の凹みがあれば、綺麗なカルデラ。
            #   /\/\
            # \/    \/
            #      　↑latest_peak
            line_strength = 2  # 久しく超えていないLINEの為、信頼度は高いLINEといえる
            if info['near_point_gap'] <= (info['depth_point_gap']*0.6):
                print("  カルデラ成立", info['near_point_gap'], info['depth_point_gap'], info['depth_point_gap'] * 0.6)
            else:
                print("  深いカルデラ成立", info['near_point_gap'], info['depth_point_gap'], info['depth_point_gap'] * 0.6)
    else:
        # sameLineが０の場合
        pass

    # 範囲情報
    print(" 　 時間範囲", target_df.iloc[0]['time_jp'], ",", target_df.iloc[-1]['time_jp'])
    print("　　価格範囲", high-low, high, low)  # 0.10以下は低い。なんなら0.15でも低いくらい。。
    print("    価格範囲Ave", high_ave - low_ave, high_ave, low_ave)

    return {  # take_position_flagの返却は必須。Trueの場合注文情報が必要。
        "decision_price": now_price,
        "line_strength": line_strength,
        "line_price": latest_peak,
        "line_direction": latest_dir,  # 1は上端。
        "latest_direction": latest_dir,  # lineDirectionとは異なることもあり
        "line_base_time": latest_time,  # 調査の開始対象となったLINE価格の元になる時刻
        "latest_time": peaks_all[0]['time'],  # 実際の最新時刻
        "line_on_num": len(same_list),
        "minus_counter": minus_counter,
    }


def latest_move_horizon(df_r):
    """
    直近の４個くらいが、ギザギザしながら、水平に近い動きをしているか
    直近から４個分のPeaksで、
    ・
    :param df_r:
    :return:
    """
    target_df = df_r[0:36]
    peaks_info = p.peaks_collect_main(df_r, 10)
    peaks_all = peaks_info["all_peaks"]
    print(" レンジインスペクション(latest_Move)")
    print(target_df.head(1))
    print(target_df.tail(1))
    f.print_arr(peaks_all)

    # (0)最高値と最低値を取得
    # ・現在のピークがどの高さにいるか
    # ・どの価格帯が、濃いかを算出
    # を実施する
    high = target_df["inner_high"].max()
    low = target_df["inner_low"].min()
    high_ave = target_df["inner_high"].mean()
    low_ave = target_df["inner_low"].mean()


    # (1) 直近のピークが再出現値か
    latest_peak = peaks_all[0]['peak']
    latest_dir = peaks_all[0]['direction']
    latest_time = peaks_all[0]['time']
    print("　　latestPeakInfo", latest_peak, latest_dir)


def latest_move_type(df_r):
    """
    直近の動きの激しさを検証する
    直近から４個分のPeaksで、
    ・Gapがすべて4pips以内の場合、平坦な動きとする。
    ・Countが全て３以内の場合、平坦な動きとする
    :param df_r:
    :return:
    """
    target_df = df_r[0:36]
    peaks_info = p.peaks_collect_main(df_r, 10)
    peaks_all = peaks_info["all_peaks"]
    print(" レンジインスペクション(latest_Move)")
    print(target_df.head(1))
    print(target_df.tail(1))
    f.print_arr(peaks_all)

    # Gapの検証
    # GAP が少ない場合、トラリピ含めて狙いにくい。
    max_peak_updown = 0
    for i in range(3):  # 3ピーク分検証
        # print(peaks_all[i]['gap'])
        if peaks_all[i]['gap'] > max_peak_updown:
            max_peak_updown = peaks_all[i]['gap']

    if max_peak_updown <= 0.04:
        print("  直近は縦には平坦な値動き", max_peak_updown)
    else:
        print("  オーダー入れることが出来る動き", max_peak_updown)

    # Countの検証(あまり関係ないかも？？）
    # max_peak_count = 0
    # for i in range(3):  # 3ピーク分検証
    #     # print(peaks_all[i]['gap'])
    #     if peaks_all[i]['count'] > max_peak_count:
    #         max_peak_count = peaks_all[i]['count']
    # if max_peak_count <= 3:
    #     print("  直近はカウントには平坦な値動き", max_peak_count)
    # else:
    #     print("  オーダー入れることが出来る動き", max_peak_count)


def find_latest_line(df_r):
    """
    直近のピーク価格について調査する。
    ただし直近のピークをどこに取るかは設定が変更できるようにする
    例えば、以下のようなケースの場合、
    0をriver(=latest)の場合と1をriverとする場合がある。
        /\ 1/\
      3/ 2\/ 0\
      /
    ただし、検証したいパターンによっては、知りたいピーク情報はターンとリバーの長さによって変ってくる
         ★
         /\
        /  \/
      \/2  1 0
      この場合は★部（Turn[2]のピーク）
       \
    　  \/\
        　 \/
        　 ☆
      この場合は☆部(River[1]ピーク）
    :param df_r:
    :return:
    """
    # 準備部分（表示や、ピークスの算出を行う）
    target_df = df_r[0:40]
    peaks_info = p.peaks_collect_main(df_r, 15)
    peaks_all = peaks_info["all_peaks"]
    # 状況に応じた、ピークポイントの指定  # 添え字は0=latest, 1=river, 2=turn, 3=flop3
    if len(peaks_all) < 4:
        # ■ループの際、数が少ないとエラーの原因になる。３個切る場合ば終了（最低３個必要）
        return {"line_strength": 0}

    turn2_gap = peaks_all[3]['gap']
    turn_gap = peaks_all[2]['gap']
    riv_gap = peaks_all[1]['gap']
    if 0 < abs(turn_gap - riv_gap) < 0.01:  # ほぼ同じ長さ、を意味したい
        comment = "　　　　LINEはTurn2で採択（Turn＝River）"
        target_p = 3
    elif turn_gap > riv_gap:
        if abs(turn2_gap - turn_gap) < max(turn_gap,turn2_gap) * 0.1:  # ほぼ同じ長さ、を意味したい
            # ほぼ同じ長さの場合は、同じ長さの端が揃う方を採択する（三角の頂点ではない）
            comment = "　　　　LINEはTurnを採択"
            target_p = 2
        elif turn2_gap > turn_gap:
            comment = "　　　　LINEはTurn2で採択"
            target_p = 3
        else:
            comment = "　　　　LINEはturnで採択"
            target_p = 2  # turnのピークを採択
    else:
        # riv_gap > turn_gap
        comment = "　　　　LINEはリバーを採択"
        target_p = 1
    # print("　　　　@レンジインスペクション", comment, turn_gap, riv_gap)
    line_strength = 0  # LINE強度の初期値を入れる

    # (0)最高値と最低値を取得
    # ・現在のピークがどの高さにいるか
    # ・どの価格帯が、濃いかを算出
    # を実施する
    now_price = target_df.iloc[0]['open']
    high = target_df["inner_high"].max()
    low = target_df["inner_low"].min()
    high_ave = target_df["inner_high"].mean()
    low_ave = target_df["inner_low"].mean()

    # (1) 直近のピークが再出現値か
    latest_peak = peaks_all[target_p]['peak']
    latest_dir = peaks_all[target_p]['direction']
    latest_time = peaks_all[target_p]['time']

    # 平均のピークGapを計算する
    sum = 0
    for item in peaks_all:
        sum += item['gap']
    ave = sum / len(peaks_all)
    # print("　　平均ピーク", ave)

    # 分析を開始する
    counter = 0  # 何回同等の値が出現したかを把握する
    range_yen = f.cal_at_least_most(0.01, round(ave * 0.1, 3), 0.035)  # * 0.38?  # 元々0.06の固定値。ただレンジのサイズ感によって変るべき
    same_dir = False
    depth_point_gap = 0  # 今のピークと一番離れている値、かつ、逆方向のポイント（同価格発見のタイミングでリセット）
    depth_point = 0
    depth_point_time = 0
    near_point_gap = 100   # 同価格ではないが、一番近い値、かつ、同方向のポイント(同価格を発見のタイミングでリセットされる）
    near_point = 0
    near_point_time = 0
    same_list = []
    # print("　　　　ダブルトップ判定閾値", range_yen)
    for i, item in enumerate(peaks_all):
        if i < 1 + target_p:
            # 自分自身の場合は探索せず。ただし自分自身は0ではなく１
            continue

        if i > 1 + target_p and latest_peak - range_yen <= item['peak'] <= latest_peak + range_yen:
            # 同価格を発見した場合。
            # if条件の、i>3 は、自分自身、不要な探索をスキップするため。
            # 4以下は、
            # \ 21 /
            # 3\/\/0　
            #  の形状を形成できないため、4以上の場合に探索スタート(i>3はそれを意味する)
            # 最初はcontinueだったが、スキップ部の情報を取得したいため、解除。
            # print("　　　　同等のピーク発見", item['time'], abs(item['peak']-latest_peak))
            counter += 1

            # 何分前に発生した物かを計算（９０分以内なら、色々考えないとなぁ）
            gap_time_min = f.seek_time_gap_seconds(latest_time, item['time']) / 60
            # 方向に関する判定
            if item['direction'] == latest_dir:
                same_dir = True
                # print("　　　　同方向の近似ピーク（≒ダブルピークの素）", item['time'], near_point_gap)
                same_list.append({"time": item['time'],
                                  "peak": item['peak'],
                                  "same_dir": same_dir,
                                  "gap_time_min": gap_time_min,
                                  "count_gap": i - target_p,
                                  "gap": round(abs(item['peak'] - latest_peak), 3),
                                  "depth_point_gap": round(depth_point_gap, 3),
                                  'depth_point': depth_point,
                                  "depth_point_time": depth_point_time,
                                  "near_point_gap": round(near_point_gap, 3),
                                  "near_point": near_point,
                                  "near_point_time": near_point_time,
                                  })
                # 通過したピーク情報を初期化する
                depth_point_gap = 0
                near_point_gap = 100
            else:
                pass
                # same_dir = False
                # print("　　　逆方向の近似ピーク(= 踊り場的な扱い)")

        else:
            # 通過するピーク（同価格ではない）の場合、記録を残す。
            # print(" CHECK", abs(item['peak']-latest_peak), depth_point_gap, near_point_gap)
            if latest_dir == 1:
                # 下ピークの場合
                #      ↓latest_peak
                # \    /
                #  \/\/

                caldera_gap = latest_peak - item['peak']  # プラス値の場合はカルデラ、－値の場合は三尊形状
                # print(" @", item['time'], caldera_gap)
                # 計算
                if caldera_gap > depth_point_gap and latest_dir != item['direction']:
                    # 最大高度を超える(かつ同方向）場合、入れ替えが発生
                    depth_point_gap = caldera_gap
                    depth_point = item['peak']
                    depth_point_time = item['time']
                if caldera_gap < near_point_gap and latest_dir == item['direction']:
                    # 最も近い価格を超える（かつ逆方向）場合、入れ替えが発生
                    near_point_gap = caldera_gap
                    near_point = item['peak']
                    near_point_time = item['time']
            else:
                # 上ピークの場合
                #   /\/\               \/\  /\/
                # \/    \/                \/  ↑latestPeak
                #      ↑latest_peak
                #  ↑全てプラス値          ↑　near値が－値、depth値がプラス値（これはマイナスにはならない気がする）
                caldera_gap = item['peak'] - latest_peak  # プラス値の場合は山、マイナスの場合は、逆コーンのような形状
                # print(" @", item['time'], near_point_gap,caldera_gap,latest_dir, item['direction'])
                # カルデラ形状
                if caldera_gap > depth_point_gap and latest_dir != item['direction']:
                    # 最大深度を超える(かつ同方向）場合、入れ替えが発生
                    depth_point_gap = caldera_gap
                    depth_point = item['peak']
                    depth_point_time = item['time']
                if caldera_gap < near_point_gap and latest_dir == item['direction']:
                    # 最も近い価格を超える（かつ逆方向）場合、入れ替えが発生
                    near_point_gap = caldera_gap
                    near_point = item['peak']
                    near_point_time = item['time']
    # f.print_arr(same_list)
    # print("　　　個数的には", counter, "回同等のぴーくが発生")
    # print("　　　対象ピークは", latest_peak, latest_dir)

    # 結果をもとに、谷があるかを判定する
    minus_counter = 0  # 複数発見時にしか利用しないが、LINEで履歴を送りたいので設定。
    if len(same_list) >= 2:
        # print("　　　　複数のSamePriceあり。強いLINEではあるが、当たってきてる回数が多いので、抜ける可能性大？")
        minus_counter = 0
        for i in range(len(same_list)):
            if same_list[i]['near_point_gap'] < 0:
                minus_counter += 1  # マイナスはLINEを超えた回数
        if minus_counter > len(same_list) * 0.5:
            # LINE越えが過半数の場合、LINEの信頼度つぃては高くない
            line_strength = 0.5
            # print("　　　　複数時　弱強度", minus_counter, len(same_list))
        elif minus_counter >= 1:
            line_strength = 1.5
            # print("　　　　複数時　１つ以上LINE越えあり", minus_counter)
        else:
            # LINE越えがない為、LINEの信頼度が比較的高い
            line_strength = 3
            # print("　　　　複数時　強強度", minus_counter, len(same_list))
    elif len(same_list) > 0:
        # print("　　　　SamePriceが１つあり→　調査する")
        # ニア（逆方向ピーク）までの凹みが、平均ピークのAveの半分以上ある場合は、深さが足りないと判断
        # 候補②　ニアまでの凹みが、直近のピークの３分の１までの折り返しに満たない状態だったら(長さが最大でも0.6倍）、カルデラとみなす
        # print(" バグだし", len(same_list))
        info = same_list[0]  # 同一価格が１つだけが成立（その情報を取得する）
        if info['near_point_gap'] < 0:
            # Nearが－値の場合値の場合 (これは強いLINEとは言いにくい？）
            #   \/\  /\/
            #      \/  ↑latestPeak
            #      ↑Near
            line_strength = 1  # ０は信用０　この場合は一度割って入るが、ある程度の信頼を置きたいため、１
            if info['count_gap'] == 4:
                pass
                # print("　　　　最小peaksでの成立(一度LINEを超えてから、戻ってきている状態)")
            else:
                pass
                # print("　　　　一度LINEを超えてから、戻ってきているじょつあい（最小Peaksではない）")
        else:
            # プラス値の場合は、一度もLINEを割ったことがないことになる（強いLINEといえる）
            #     ↓(間の底値がNearPoint） ここが６割程度の凹みがあれば、綺麗なカルデラ。
            #   /\/\
            # \/    \/
            #      　↑latest_peak
            line_strength = 2  # 久しく超えていないLINEの為、信頼度は高いLINEといえる
            if info['near_point_gap'] <= (info['depth_point_gap']*0.6):
                pass
                # print("  カルデラ成立", info['near_point_gap'], info['depth_point_gap'], info['depth_point_gap'] * 0.6)
            else:
                pass
                # print("  深いカルデラ成立", info['near_point_gap'], info['depth_point_gap'], info['depth_point_gap'] * 0.6)
    else:
        # sameLineが０の場合
        pass

    # 範囲情報
    # print(" 　 時間範囲", target_df.iloc[0]['time_jp'], ",", target_df.iloc[-1]['time_jp'])
    # print("　　価格範囲", high-low, high, low)  # 0.10以下は低い。なんなら0.15でも低いくらい。。
    # print("    価格範囲Ave", high_ave - low_ave, high_ave, low_ave)

    return {  # take_position_flagの返却は必須。Trueの場合注文情報が必要。
        "line_strength": line_strength,
        "line_price": latest_peak,
        "line_direction": latest_dir,  # 1は上端。
        "latest_direction": latest_dir,  # lineDirectionとは異なることもあり
        "line_base_time": latest_time,  # 調査の開始対象となったLINE価格の元になる時刻
        "latest_time": peaks_all[0]['time'],  # 実際の最新時刻
        "line_on_num": len(same_list),
        "minus_counter": minus_counter,
        "decision_price": now_price,
        "same_time_latest": 0 if len(same_list) == 0 else same_list[0]['time']  # 一番近い同一価格と判断した時刻
    }


def find_lines(df_r):
    """
    find_latest_lineを繰り返し呼び出し、
    直近のUpperLineとLowerLineが発見されるまで繰り返す
    :param df_r:
    :return:
    """
    found_upper = False
    found_lower = False
    upper_information = {"line_strength": 0}
    lower_information = {"line_strength": 0}
    for i in range(30):
        if found_upper and found_lower:
            # print("　　　　両方発見→FIN")
            break
        else:
            range_result = find_latest_line(df_r[i:])
            if i == 0:
                # 初回のみ、真のLatestを取得する(LineStrength問わず）
                latest_line = range_result
                # 発見がある場合フラグは立てておく
                if range_result['line_strength'] != 0:
                    if range_result['line_direction'] == 1:
                        found_upper = True
                        upper_information = range_result
                    elif range_result['line_direction'] == -1:
                        found_lower = True
                        lower_information = range_result
                else:
                    pass
                    # 今後、直近が無ければ、他も探さなくていい気がする。。（時間短縮のため）
                    # break


            # 初回以外は探索モード
            if range_result['line_strength'] != 0:
                # LINEが発見された場合
                if range_result['line_direction'] == 1 and not found_upper:
                    found_upper = True
                    upper_information = range_result
                elif range_result['line_direction'] == -1 and not found_lower:
                    found_lower = True
                    lower_information = range_result
    # 返却する
    return {
        "latest_line": latest_line,
        "found_upper": found_upper,
        "upper_info": upper_information,
        "found_lower": found_lower,
        "lower_info": lower_information
    }


def range_trid_make_order(line_result):
    """
    直近にLINEが発生した状態で呼び出される（必ずオーダーを入れる状態）
    低いラインと高いラインを受け取り、
    ・範囲外に対する、順張り
    ・範囲内に対する、順張り
    のトラリピを入れていく。
    ただしエラー防止の為、トラリピの数は最大１０個にする
    :param line_result: 詳細はfind_lines関数の戻り値参照。
        latest_line:直近のLINE情報
        upper_infoとfoundUpper
        lower_infoとfoundLower
    :return:orderの配列 [{オーダー１},{オーダー２}]
    """
    # 範囲外へのオーダーを入れる
    # lowerが
    if line_result['found_lower']:
        # lowerが発見されている場合（直近かどうかはわからないが）
        lower_line = line_result['lower_info']
        lower_orders_arr = f.make_trid_order({
            "decision_price": lower_line['decision_price'],
            "units": 2,
            "expected_direction": -1,
            "start_price": lower_line['line_price'] - 0.01,
            "grid": 0.02,
            "num": 2,
            # "end_price": 156.0,
            "type": "STOP"
        })
    else:
        # 型だけ準備
        lower_orders_arr = []  # 空の配列

    # upper
    if line_result['found_upper'] != 0:
        # upperが発見されている場合（直近かどうかわからないが）
        upper_line = line_result['upper_info']
        upper_orders_arr = f.make_trid_order({
            "decision_price": upper_line['decision_price'],
            "units": 3,
            "expected_direction": 1,
            "start_price": upper_line['line_price'] + 0.01,
            "grid": 0.02,
            "num": 2,
            # "end_price": 156.0,
            "type": "STOP"
        })
    else:
        upper_orders_arr = []

    # 間に対してのオーダー発行
    # if upper_line !=0 and lower_line != 0:
    #     # 両端が決まっている場合のみ実施する
    #     pass

    # オーダーを結合する（
    orders_arr = lower_orders_arr + upper_orders_arr
    # 一時、結合が空だとできなかった　配列の結合は、空には結合不可の為、場合分けした）
    # if len(lower_orders_arr) == 0 and len(upper_orders_arr) == 0:
    #     # 実際この選択肢になることは無い（注文前提の為）
    #     print(" かなり変なこと発生")
    #     return {"take_position_flag": False}
    # elif len(lower_orders_arr) == 0:
    #     orders_arr = upper_orders_arr
    # elif len(upper_orders_arr) == 0:
    #     orders_arr = upper_orders_arr
    # else:
    #     print("lo")
    #     print(type(lower_orders_arr))
    #     print(" Lower")
    #     f.print_arr(lower_orders_arr)
    #     print(" upper")
    #     print(type(upper_orders_arr))
    #     f.print_arr(upper_orders_arr)
    #     print("↑")
    #     orders_arr = [] + upper_orders_arr

    return orders_arr
