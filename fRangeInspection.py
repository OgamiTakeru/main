import fPeakLineInspection as p  # とりあえずの関数集
import fGeneric as f
import fDoublePeaks as dp


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


def test(df_r):
    """
    直近のピーク価格について調査する
    :param df_r:
    :return:
    """
    # 準備部分（表示や、ピークスの算出を行う）
    target_df = df_r[0:36]
    peaks_info = p.peaks_collect_main(df_r, 10)
    peaks_all = peaks_info["all_peaks"]
    print(" レンジインスペクション")
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

    # 平均のピークGapを計算する
    sum=0
    for item in peaks_all:
        sum += item['gap']
    ave = sum / len(peaks_all)
    print("　　平均ピーク", ave)
    # 分析を開始する
    counter = 0  # 何回同等の値が出現したかを把握する
    range_yen = ave * 0.2  # * 0.1  # 元々0.06の固定値。ただレンジのサイズ感によって変るべき
    same_dir = False
    same_peak = 0
    depth_point_gap = 0  # 今のピークと一番離れている値、かつ、逆方向のポイント（同価格発見のタイミングでリセット）
    depth_point = 0
    depth_point_time = 0
    near_point_gap = 100   # 同価格ではないが、一番近い値、かつ、同方向のポイント(同価格を発見のタイミングでリセットされる）
    near_point = 0
    near_point_time = 0
    same_list = []
    print("　　ダブルトップ判定閾値", range_yen)
    for i, item in enumerate(peaks_all):
        if i == 0:
            # 自分自身の場合は探索せず。
            continue

        if i > 3 and latest_peak - range_yen <= item['peak'] <= latest_peak + range_yen:
            # 同価格を発見した場合。
            # if条件の、i>3 は、自分自身、不要な探索をスキップするため。
            # 4以下は、
            # \ 23 /
            # 4\/\/1　
            #  の形状を形成できないため、4以上の場合に探索スタート(i>3はそれを意味する)
            # 最初はcontinueだったが、スキップ部の情報を取得したいため、解除。
            # print("　　　同等のピーク発見", item['time'], abs(item['peak']-latest_peak))
            counter += 1

            # 何分前に発生した物かを計算（９０分以内なら、色々考えないとなぁ）
            gap_time_min = f.seek_time_gap_seconds(latest_time, item['time']) / 60
            # 方向に関する判定
            if item['direction'] == latest_dir:
                same_dir = True
                # print("　　　同方向の近似ピーク（≒ダブルピークの素）")
            else:
                same_dir = False
                # print("　　　逆方向の近似ピーク(= 踊り場的な扱い)")

            # 記録する
            same_list.append({"time": item['time'],
                              "peak": item['peak'],
                              "same_dir": same_dir,
                              "gap_time": gap_time_min,
                              "count_gap": i,
                              "gap": round(abs(item['peak']-latest_peak), 3),
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
            # 通過するピーク（同価格ではない）の場合、記録を残す。
            # print(" CHECK", abs(item['peak']-latest_peak), depth_point_gap, near_point_gap)
            if latest_dir == 1:
                # 上ピークの場合
                #  /\/\
                # /    \
                caldera_gap = latest_peak - item['peak']  # プラス値の場合はカルデラ、－値の場合は三尊形状
                # 計算
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
            else:
                # 下ピークの場合
                # \    /
                #  \/\/
                caldera_gap = item['peak'] - latest_peak  # プラス値の場合はカルデラ、マイナス値の場合は三尊形状
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
    if len(same_list) >= 2 :
        print("  複数のSamePriceあり。強いトップではあるが、当たってきてる回数が多いので、抜ける可能性大？")
        take_position_flag = 0
    elif len(same_list) > 0:
        print("  単発のSamePriceあり→　調査する")
        take_position_flag = 1
        # ニア（逆方向ピーク）までの凹みが、平均ピークのAveの半分以上ある場合は、深さが足りないと判断
        # 候補②　ニアまでの凹みが、直近のピークの３分の１までの折り返しに満たない状態だったら(長さが最大でも0.6倍）、カルデラとみなす
        print(" バグだし", len(same_list))
        info = same_list[0]  # 同一価格が１つだけが成立（その情報を取得する）
        if info['near_point_gap'] < 0:
            # マイナス値の場合は、
            #     /\
            #  /\/  \/ この状態
            # /
            if info['count_gap'] == 4:
                print("   綺麗な三尊成立？")
            else:
                print("   三尊ポイもの（複数）形状")
        else:
            # マイナス値の場合は、
            #  /\/\/\この状態
            # /
            if info['near_point_gap'] <= (peaks_all[0]['gap']*0.33):
                print("  カルデラ成立", info['near_point_gap'], peaks_all[0]['gap'], peaks_all[0]['gap'] * 0.33)
            else:
                print("  深さ足りず", info['near_point_gap'], peaks_all[0]['gap'], peaks_all[0]['gap'] * 0.33)
    else:
        take_position_flag = 0


    # 範囲情報
    print(" 　 時間範囲", target_df.iloc[0]['time_jp'], ",", target_df.iloc[-1]['time_jp'])
    print("　　価格範囲", high-low, high, low)  # 0.10以下は低い。なんなら0.15でも低いくらい。。
    print("    価格範囲Ave", high_ave- low_ave, high_ave, low_ave)


    order_base = dp.order_finalize({"stop_or_limit": 1,
                                 "expected_direction": latest_dir * -1,
                                 "decision_time": 0,
                                 "decision_price": latest_peak,  # フラグ成立時の価格（先頭[0]列のOpen価格）
                                 "target": -0.02,  # 価格orマージンかを入れることが出来る
                                 "lc": 0.05,
                                 "tp": 0.05,  # tp,
                                 })

    return {  # take_position_flagの返却は必須。Trueの場合注文情報が必要。
        "take_position_flag": take_position_flag,
        "order_base": order_base,  # 検証で利用する。
        # "exe_orders": exe_orders,  # 発行するオーダー。このままオーダーを発行できる状態
        "records": {}  #records  # 記録軍。CSV保存時に出力して解析ができるように。
    }