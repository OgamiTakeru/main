import fPeakInspection as p  # とりあえずの関数集
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
        if abs(turn2_gap - turn_gap) < max(turn_gap, turn2_gap) * 0.1:  # ほぼ同じ長さ、を意味したい
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
    near_point_gap = 100  # 同価格ではないが、一番近い値、かつ、同方向のポイント(同価格を発見のタイミングでリセットされる）
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
            print("　　　同等のピーク発見", item['time'], abs(item['peak'] - latest_peak))
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
                #  depth ↓latestPeak候補
                # \  ↓ /
                #  \/\/
                # 　　↑latestPeakの基本（target=1)
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
            if info['count_foot_gap'] == 4:
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
            if info['near_point_gap'] <= (info['depth_point_gap'] * 0.6):
                print("  カルデラ成立", info['near_point_gap'], info['depth_point_gap'], info['depth_point_gap'] * 0.6)
            else:
                print("  深いカルデラ成立", info['near_point_gap'], info['depth_point_gap'],
                      info['depth_point_gap'] * 0.6)
    else:
        # sameLineが０の場合
        pass

    # 範囲情報
    print(" 　 時間範囲", target_df.iloc[0]['time_jp'], ",", target_df.iloc[-1]['time_jp'])
    print("　　価格範囲", high - low, high, low)  # 0.10以下は低い。なんなら0.15でも低いくらい。。
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


def search_latest_line(*args):
    """
    基本的にはfind_latest_lineと似ている動き。
    find_latest_lineは指定されたDFからlatest_lineを産出するが、
    この関数は、想定される範囲で、Lineが生成される可能性があるかを計算するもの
       \　 ↓river peak
       \  /\←latest　
        \/
     ↓
    　\　　
       \  /\　
        \/  \/ ←こうなると予想されるポイントを探す
    latestが伸びていって、折り返したことを想定し、
    latestがriverとなり、latest_count＝２になったときに折り返す
    """
    # 準備部分（表示や、ピークスの算出を行う）
    if len(args) == 2:
        # 引数が二個の場合は、Peaksが来ている為、ピークスを求める必要なし
        target_df = args[0]
        peaks_all = args[1]
    else:
        # 引数が１つの場合（df_rのみ）、ピークスを求める必要あり
        target_df = args[0][0:40]
        peaks_info = p.peaks_collect_main(target_df, 12)
        peaks_all = peaks_info["all_peaks"]
    # 状況に応じた、ピークポイントの指定  # 添え字は0=latest, 1=river, 2=turn, 3=flop3
    if len(peaks_all) < 4:
        # ■ループの際、数が少ないとエラーの原因になる。３個切る場合ば終了（最低３個必要）
        return {"line_strength": 0}

    # 各変数の設定
    now_latest_dir = peaks_all[0]['direction']  # 現在のLatest_dir。近い将来river_dirとなるはずのもの。
    expected_latest_dir = now_latest_dir * -1  # 折り返し直後の部分（今までcount=2で判定した部分の方向)
    if now_latest_dir == 1:
        # latestが登り方向の場合
        search_min_price = peaks_all[0]['peak']  # 探索する最低値。
        search_max_price = peaks_all[0]['peak'] + 0.1  # 探索する最高値
        target_price = search_max_price  # MAX側から調査
    else:
        # latestが下り方向の場合
        search_min_price = peaks_all[0]['peak'] - 0.1  # 探索する最低値。
        search_max_price = peaks_all[0]['peak']  # 探索する最高値
        target_price = search_min_price  # 下（Min）からスタート
    grid = 0.01  # 探索する幅（細かすぎると、、計算遅くなる？）
    next_river_peak_time = peaks_all[0]['time']  # 将来riverになるもの

    while search_min_price <= target_price <= search_max_price:
        # 平均のピークGapを計算する
        sum = 0
        for item in peaks_all:
            sum += item['gap']
        ave = sum / len(peaks_all)

        # ②探索開始
        target_dir = now_latest_dir  # 現在のLatestの方向（後のriverになる方向）
        counter = 0  # 何回同等の値が出現したかを把握する
        range_yen = f.cal_at_least_most(0.01, round(ave * 0.153, 3), 0.041)  # 0.153倍が一番よかった(大きすぎないレベル）。。
        depth_point_gap = 0  # 今のピークと一番離れている値、かつ、逆方向のポイント（同価格発見のタイミングでリセット）
        depth_point = 0
        depth_point_time = 0
        depth_minus_count = depth_plus_count = 0
        near_point_gap = 100  # 同価格ではないが、一番近い値、かつ、同方向のポイント(同価格を発見のタイミングでリセットされる）
        near_point = 0
        near_point_time = 0
        near_minus_count = near_plus_count = 0
        same_list = []
        between_num = 0  # 間に何個のピークがあったか。最短ダブルトップのの場合は2(自分自身をカウントするため）
        # print("　　　　ダブルトップ判定閾値", range_yen)
        for i, item in enumerate(peaks_all):
            # 判定を行う
            if target_price - range_yen <= item['peak'] <= target_price + range_yen:
                # 同価格を発見した場合。
                # print("　　　　同等のピーク発見", item['time'], abs(item['peak']-latest_peak))
                counter += 1

                # 何分前に発生した物かを計算（９０分以内なら、色々考えないとなぁ）
                gap_time_min = f.seek_time_gap_seconds(next_river_peak_time, item['time']) / 60
                # 方向に関する判定
                if item['direction'] == target_dir:
                    # print("    Between確認", between_num, item['time'])
                    same_dir = True
                    # print("　　　　同方向の近似ピーク（≒ダブルピークの素）", item['time'], near_point_gap)
                    same_list.append({"time": item['time'],
                                      "peak": item['peak'],
                                      "same_dir": same_dir,
                                      "gap_time_min": gap_time_min,
                                      "count_foot_gap": i,
                                      "depth_point_gap": round(depth_point_gap, 3),
                                      'depth_point': depth_point,
                                      "depth_point_time": depth_point_time,
                                      "depth_minus_count": depth_minus_count,
                                      "depth_plus_count": depth_plus_count,
                                      "near_point_gap": round(near_point_gap, 3),
                                      "near_point": near_point,
                                      "near_point_time": near_point_time,
                                      'near_minus_count': near_minus_count,
                                      'near_plus_count': near_plus_count,
                                      "between_num": between_num,
                                      "i": i  # 何個目か
                                      })
                    # 通過したピーク情報を初期化する
                    depth_point_gap = 0
                    near_point_gap = 100
                    between_num = 0
                else:
                    pass
                    # same_dir = False
                    # print("　　　逆方向の近似ピーク(= 踊り場的な扱い)")

            else:
                # 通過するピーク（同価格ではない）の場合、記録を残す。
                # print(" 　　スルーカウント", item['time'], abs(item['peak']-latest_peak), depth_point_gap, near_point_gap, between_num + 1)
                between_num += 1
                # 条件分岐
                if expected_latest_dir == 1:
                    # 想定されるlatestが上向き＝riverが下ピークの場合
                    #       ↓depth
                    # \  /\/\　
                    #  \/ ↑  \/ ←latest(direction)
                    # 　　near ↑target_price(ライン検索値)
                    peak_gap = item['peak'] - target_price  # プラス値の場合は上の図の通り。－値の場合は三尊形状（ライン越え）
                else:
                    # latestが下向きの場合　＝　riverが上向き
                    #         ↓riverpeak(Lineの対象）
                    #   /\    /\ ←latest
                    #  /  \/\/
                    #     　 ↑ depth
                    #  ↑全てプラス値          ↑　near値が－値、depth値がプラス値（これはマイナスにはならない気がする）
                    # print(" are????", target_price, item['peak'], item['time'])
                    peak_gap = target_price - item['peak']  # プラスの場合上の絵。
                # 計算
                if item['direction'] != target_dir:
                    # 方向が異なるピークの場合→Depthの方
                    # 深さの値を取得する
                    if peak_gap > depth_point_gap:
                        # 最大深度を更新する場合
                        depth_point_gap = peak_gap
                        depth_point = item['peak']
                        depth_point_time = item['time']
                    # マイナスプラスをカウントする
                    if peak_gap <= 0:
                        depth_minus_count += 1
                    else:
                        depth_plus_count += 1
                if item['direction'] == target_dir:
                    # 同じピークの場合→Nearの方
                    # ニアの方の深さの値を取得する
                    if peak_gap < near_point_gap:
                        # 最も近い価格を超える（かつ逆方向）場合
                        near_point_gap = peak_gap
                        near_point = item['peak']
                        near_point_time = item['time']
                    # マイナスプラスをカウントする
                    # print(" nearPointGap", peak_gap, item['time'])
                    if peak_gap <= 0:
                        near_minus_count += 1
                    else:
                        near_plus_count += 1
        # 同価格リスト
        print("")
        print("同価格リスト", "base", target_price, next_river_peak_time, target_price - range_yen, "<r<",
              target_price + range_yen,
              "許容ギャップ", range_yen, "方向", target_dir, " 平均ピークGap", ave)
        f.print_arr(same_list)
        print(" ↑ここまで")

        # ■LineStrengthを決定するため、同価格リストの結果をもとに、谷があるかを判定する
        line_strength = 0.01
        minus_counter = 0  # 初期値
        if len(same_list) > 0:
            # 同一価格が存在する場合(直近の同一価格、それ以前の同一価格（複数の可能性もあり）について調査を行う）
            # ①まずは直近のSamePriceに関しての調査
            # print("　　　　SamePriceが１つあり→　調査する")
            # 同一価格の発見が１つの場合、
            # ＊パターン１　同一価格の間のピーク数が４個(丁度）の場合は、そのラインは強いライン
            #    以下の２パターンがあるが、どちらも強いラインの形（三尊、カルデラ）
            # 　   \/\  /\/
            # 　      \/  ↑river peak
            # 　      ↑Near
            # 　     ↓
            # 　   /\/\
            # 　 \/    \/
            #      　　　↑river_peak
            #  ＊パターン２　同一価格間のピーク数が４個よりも多い場合
            # 　    /\/\/\
            # 　  \/      \/
            #             ↑　river_peak
            #    near が半分以上マイナス値（ラインを割っている）の場合、信頼度が下がる
            #
            #   *パターン３　シンプルなダブルトップ系
            #    /\/\
            #   /
            #    betweenが２の場合のみ

            info = same_list[0]  # 同一価格が１つだけが成立（その情報を取得する）
            # print("Between", info['between_num'])
            # パターン１の処理
            if info['between_num'] == 4:
                line_strength = 2  # 強いラインとみなす

            # パターン３の処理（シンプルダブルトップ）
            if info['between_num'] == 2:
                if info['gap_time_min'] <= 20:  # 20分いないのダブルトップは、信頼度低（単なるギザギザの可能性）
                    # print("初回短すぎ・・？")
                    line_strength = 1.5  # 割とLineを突破することが多い気がするが。。。
                else:
                    # print("適正？")
                    line_strength = 2  # ただ、depthの深さによって変るのでは？

            # パターン２の処理
            if info['between_num'] > 4:
                # nearマイナスの数が、nearの数の半分以上の場合
                all_near_num = info['between_num'] / 2 - 1  # nearの数はこう求める
                minus_ratio = info['near_minus_count'] / all_near_num
                # print("    参考：マイナス比率", minus_ratio, info['near_minus_count'], all_near_num)
                if minus_ratio >= 0.4:
                    line_strength = 0.5
                elif minus_ratio > 0:
                    line_strength = 1.5
                else:
                    line_strength = 3

            # ②同一価格が２個以上ある場合は、他も同号して検討する
            # print("　　　　複数のSamePriceあり。強いLINEではあるが、当たってきてる回数が多いので、抜ける可能性大？")
            if len(same_list) >= 2:
                for i in range(len(same_list)):
                    if same_list[i]['near_point_gap'] < 0:
                        minus_counter += 1  # マイナスはLINEを超えた回数
                if minus_counter > len(same_list) * 0.5:
                    # LINE越えが過半数の場合、LINEの信頼度つぃては高くない
                    line_strength = 0.5
                    # print("　　　　複数時　弱強度", minus_counter, len(same_list))
                elif minus_counter >= 1:
                    line_strength = 1
                    # print("　　　　複数時　１つ以上LINE越えあり", minus_counter)
                else:
                    # LINE越えがない為、LINEの信頼度が比較的高い
                    line_strength = 3
                    # print("　　　　複数時　強強度", minus_counter, len(same_list))
        else:
            pass

        return_dic = {  # take_position_flagの返却は必須。Trueの場合注文情報が必要。
            "line_strength": line_strength,
            "line_price": target_price,
            "line_direction": target_dir,  # 1の場合UpperLine（＝上値抵抗）
            "latest_direction": target_dir * -1,  # lineDirectionとは異なる(基本は逆になる）
            "line_base_time": target_df.iloc[0]['time'],  # 推定のため、これは算出不可（テキトーな値にする）
            "latest_foot_gap": 99 if len(same_list) == 0 else same_list[0]['count_foot_gap'],
            "latest_time": peaks_all[0]['time'],  # 実際の最新時刻
            "line_on_num": len(same_list),
            "minus_counter": minus_counter,
            "decision_price": target_df.iloc[0]['close'],
            "between_num": between_num,
            "same_time_latest": 0 if len(same_list) == 0 else same_list[0]['time']  # 一番近い同一価格と判断した時刻
        }

        # 判断する
        if return_dic['line_strength'] > 1:
            # 1.5以上のストレングスのピークが形成できる折り返し価格が発見された場合
            print(" この価格で、Lineを形成するピークができる可能性", target_price)
            return {
                "latest_flag": True,
                "latest_line": return_dic
            }
        else:
            print("  ★ダメでした", target_price)
        # ★ループ処理
        if now_latest_dir == 1:
            # latestが登り方向の場合
            target_price = + target_price - grid
        else:
            target_price = + target_price + grid
    # ダメな場合の返却
    return {
        "latest_flag": False,
        "latest_line": {
            "line_strength": 0.01,
            "line_price": target_price,
            "line_direction": 1,  # 1の場合UpperLine（＝上値抵抗）
            "latest_direction": 0,  # lineDirectionとは異なる(基本は逆になる）
            "line_base_time": target_df.iloc[0]['time'],  # 推定のため、これは算出不可（テキトーな値にする）
            "latest_foot_gap": 0,
            "latest_time": peaks_all[0]['time'],  # 実際の最新時刻
            "line_on_num": 0,
            "minus_counter": 0,
            "decision_price": target_df.iloc[0]['close'],
            "between_num": 0,
            "same_time_latest": 0  # 一番近い同一価格と判断した時刻
        }
    }


def find_latest_line(*args):
    """
    :param *dic_args: 複数の引数を取る可能性があるが、２パターン.
    ①二つの引数がある場合 dic_args[0] = df_r、dic_args[1] = peaks
    　→ループ等で呼び出される場合がメイン。df_rは基本参考値で、peaksで実施するのが理想（計算量削減の為）
    ②一つだけの引数がある場合 dic_args[0] = de_r
     →単発で実行する場合のみ

     <調査の対象について＞
     図で書くと、直近のターンポイント(river_peak)が、Lineとなっているかを確認する関数。
      \　　↓ここが対象となる（=river)
       \  /\←　この部分が２の場合に検出する（ここはLatestではない。２の場合＝１つ出来立ての足は省くので、このPeakは無いと同義）
        \/  \ ←これがLatestとして扱われるもの
    :return:
    """
    # 準備部分（表示や、ピークスの算出を行う）
    if len(args) == 2:
        # 引数が二個の場合は、Peaksが来ている為、ピークスを求める必要なし
        target_df = args[0]
        peaks_all = args[1]
    else:
        # 引数が１つの場合（df_rのみ）、ピークスを求める必要あり
        target_df = args[0][0:40]
        peaks_info = p.peaks_collect_main(target_df, 12)
        peaks_all = peaks_info["all_peaks"]
    # 状況に応じた、ピークポイントの指定  # 添え字は0=latest, 1=river, 2=turn, 3=flop3
    if len(peaks_all) < 4:
        # ■ループの際、数が少ないとエラーの原因になる。３個切る場合ば終了（最低３個必要）
        return {"line_strength": 0}

    # (1) LINE探索する
    # ⓪探索準備
    target_p = 0  # riverのピークを採択（０がRiverの添え字）。
    latest_peak = peaks_all[target_p]['peak']
    latest_dir = peaks_all[target_p]['direction']
    latest_gap = peaks_all[target_p]['gap']
    latest_time = peaks_all[target_p]['time']
    river_peak = peaks_all[1]['peak']  # riverのピークを求める（これがライン検索の基準となる）
    river_peak_time = peaks_all[1]['time']
    river_dir = peaks_all[1]['direction']
    river_gap = peaks_all[1]['gap']
    river_count = peaks_all[1]['count']
    turn_count = peaks_all[2]['count']
    flop3_count = peaks_all[3]['count']
    # 平均のピークGapを計算する
    sum = 0
    for item in peaks_all:
        sum += item['gap']
    ave = sum / len(peaks_all)
    # print("　　平均ピーク", ave)

    # ①LatestとRiverの関係を求める（latestが大きいケースが、外しているケースが多い）Riverの0.4倍以下程度あってほしい
    lr_ratio = latest_gap / river_gap

    # ②探索開始
    target_price = river_peak  # ★ 将来的に、想定価格で探す可能性があるため。
    target_dir = river_dir
    counter = 0  # 何回同等の値が出現したかを把握する
    range_yen = f.cal_at_least_most(0.01, round(ave * 0.153, 3), 0.041)  #0.153倍が一番よかった(大きすぎないレベル）。。
    depth_point_gap = 0  # 今のピークと一番離れている値、かつ、逆方向のポイント（同価格発見のタイミングでリセット）
    depth_point = 0
    depth_point_time = 0
    depth_minus_count = depth_plus_count = 0
    near_point_gap = 100  # 同価格ではないが、一番近い値、かつ、同方向のポイント(同価格を発見のタイミングでリセットされる）
    near_point = 0
    near_point_time = 0
    near_minus_count = near_plus_count = 0
    same_list = []
    between_num = 0  # 間に何個のピークがあったか。最短ダブルトップのの場合は2(自分自身をカウントするため）
    # print("　　　　ダブルトップ判定閾値", range_yen)
    for i, item in enumerate(peaks_all):
        # print("   target:", river_peak, " pair", item['peak'], item['time'], i, river_peak - range_yen <= item['peak'] <= river_peak + range_yen
        #       , item['direction'])
        if i < 1 + target_p:
            # 自分自身の場合は探索せず。ただし自分自身は0ではなく１
            continue

        # 判定を行う
        if i > 2 and target_price - range_yen <= item['peak'] <= target_price + range_yen:
            # 同価格を発見した場合。
            # print("　　　　同等のピーク発見", item['time'], abs(item['peak']-latest_peak))
            counter += 1

            # 何分前に発生した物かを計算（９０分以内なら、色々考えないとなぁ）
            gap_time_min = f.seek_time_gap_seconds(river_peak_time, item['time']) / 60
            # 方向に関する判定
            if item['direction'] == target_dir:
                # print("    Between確認", between_num, item['time'])
                same_dir = True
                # print("　　　　同方向の近似ピーク（≒ダブルピークの素）", item['time'], near_point_gap)
                same_list.append({"time": item['time'],
                                  "peak": item['peak'],
                                  "same_dir": same_dir,
                                  "gap_time_min": gap_time_min,
                                  "count_foot_gap": i - target_p,
                                  "depth_point_gap": round(depth_point_gap, 3),
                                  'depth_point': depth_point,
                                  "depth_point_time": depth_point_time,
                                  "depth_minus_count": depth_minus_count,
                                  "depth_plus_count": depth_plus_count,
                                  "near_point_gap": round(near_point_gap, 3),
                                  "near_point": near_point,
                                  "near_point_time": near_point_time,
                                  'near_minus_count': near_minus_count,
                                  'near_plus_count': near_plus_count,
                                  "between_num": between_num,
                                  "i": i  # 何個目か
                                  })
                # 通過したピーク情報を初期化する
                depth_point_gap = 0
                near_point_gap = 100
                between_num = 0
            else:
                pass
                # same_dir = False
                # print("　　　逆方向の近似ピーク(= 踊り場的な扱い)")

        else:
            # 通過するピーク（同価格ではない）の場合、記録を残す。
            # print(" 　　スルーカウント", item['time'], abs(item['peak']-latest_peak), depth_point_gap, near_point_gap, between_num + 1)
            between_num += 1
            # 条件分岐
            if latest_dir == 1:
                # latestが上向き＝riverが下ピークの場合
                #       ↓depth
                # \  /\/\　
                #  \/ ↑  \/ ←latest(direction)
                #　　near ↑target_price(ライン検索値)
                peak_gap = item['peak'] - target_price  # プラス値の場合は上の図の通り。－値の場合は三尊形状（ライン越え）
            else:
                # latestが下向きの場合　＝　riverが上向き
                #         ↓riverpeak(Lineの対象）
                #   /\    /\ ←latest
                #  /  \/\/
                #     　 ↑ depth
                #  ↑全てプラス値          ↑　near値が－値、depth値がプラス値（これはマイナスにはならない気がする）
                # print(" are????", target_price, item['peak'], item['time'])
                peak_gap = target_price - item['peak']  # プラスの場合上の絵。
            # 計算
            if item['direction'] != target_dir:
                # 方向が異なるピークの場合→Depthの方
                # 深さの値を取得する
                if peak_gap > depth_point_gap:
                    # 最大深度を更新する場合
                    depth_point_gap = peak_gap
                    depth_point = item['peak']
                    depth_point_time = item['time']
                # マイナスプラスをカウントする
                if peak_gap <= 0:
                    depth_minus_count += 1
                else:
                    depth_plus_count += 1
            if item['direction'] == target_dir:
                # 同じピークの場合→Nearの方
                # ニアの方の深さの値を取得する
                if peak_gap < near_point_gap:
                    # 最も近い価格を超える（かつ逆方向）場合
                    near_point_gap = peak_gap
                    near_point = item['peak']
                    near_point_time = item['time']
                # マイナスプラスをカウントする
                # print(" nearPointGap", peak_gap, item['time'])
                if peak_gap <= 0:
                    near_minus_count += 1
                else:
                    near_plus_count += 1
    # 同価格リスト
    print("")
    print("同価格リスト", "base", target_price, river_peak_time, river_peak - range_yen, "<r<", river_peak + range_yen,
          "許容ギャップ", range_yen, "方向", target_dir, " 平均ピークGap", ave)
    f.print_arr(same_list)
    print(" ↑ここまで")

    # ■LineStrengthを決定するため、同価格リストの結果をもとに、谷があるかを判定する
    line_strength = 0.01
    minus_counter = 0  # 初期値
    if len(same_list) > 0:
        # 同一価格が存在する場合(直近の同一価格、それ以前の同一価格（複数の可能性もあり）について調査を行う）
        # ①まずは直近のSamePriceに関しての調査
        # print("　　　　SamePriceが１つあり→　調査する")
        # 同一価格の発見が１つの場合、
        # ＊パターン１　同一価格の間のピーク数が４個(丁度）の場合は、そのラインは強いライン
        #    以下の２パターンがあるが、どちらも強いラインの形（三尊、カルデラ）
        # 　   \/\  /\/
        # 　      \/  ↑river peak
        # 　      ↑Near
        # 　     ↓
        # 　   /\/\
        # 　 \/    \/
        #      　　　↑river_peak
        #  ＊パターン２　同一価格間のピーク数が４個よりも多い場合
        # 　    /\/\/\
        # 　  \/      \/
        #             ↑　river_peak
        #    near が半分以上マイナス値（ラインを割っている）の場合、信頼度が下がる
        #
        #   *パターン３　シンプルなダブルトップ系
        #    /\/\
        #   /
        #    betweenが２の場合のみ

        info = same_list[0]  # 同一価格が１つだけが成立（その情報を取得する）
        # print("Between", info['between_num'])
        # パターン１の処理
        if info['between_num'] == 4:
            line_strength = 2  # 強いラインとみなす

        # パターン３の処理（シンプルダブルトップ）
        if info['between_num'] == 2:
            if info['gap_time_min'] <= 20:  # 20分いないのダブルトップは、信頼度低（単なるギザギザの可能性）
                # print("初回短すぎ・・？")
                line_strength = 1.5  # 割とLineを突破することが多い気がするが。。。
            else:
                # print("適正？")
                line_strength = 2  # ただ、depthの深さによって変るのでは？

        # パターン２の処理
        if info['between_num'] > 4:
            # nearマイナスの数が、nearの数の半分以上の場合
            all_near_num = info['between_num'] / 2 - 1  # nearの数はこう求める
            minus_ratio = info['near_minus_count'] / all_near_num
            # print("    参考：マイナス比率", minus_ratio, info['near_minus_count'], all_near_num)
            if minus_ratio >= 0.4:
                line_strength = 0.5
            elif minus_ratio > 0:
                line_strength = 1.5
            else:
                line_strength = 3

        # ②同一価格が２個以上ある場合は、他も同号して検討する
        # print("　　　　複数のSamePriceあり。強いLINEではあるが、当たってきてる回数が多いので、抜ける可能性大？")
        if len(same_list) >= 2:
            for i in range(len(same_list)):
                if same_list[i]['near_point_gap'] < 0:
                    minus_counter += 1  # マイナスはLINEを超えた回数
            if minus_counter > len(same_list) * 0.5:
                # LINE越えが過半数の場合、LINEの信頼度つぃては高くない
                line_strength = 0.5
                # print("　　　　複数時　弱強度", minus_counter, len(same_list))
            elif minus_counter >= 1:
                line_strength = 1
                # print("　　　　複数時　１つ以上LINE越えあり", minus_counter)
            else:
                # LINE越えがない為、LINEの信頼度が比較的高い
                line_strength = 3
                # print("　　　　複数時　強強度", minus_counter, len(same_list))
    else:
        pass

    # ただし、ぐちゃぐちゃしている場合（riverもturnもflop3もカウントが合計値が7以下（どれも２程度）の場合）LineStrengthを下げる
    if river_count + turn_count + flop3_count <= 7:
        # print(peaks_all[1])
        # print(peaks_all[2])
        # print(peaks_all[3])
        # print(river_count, turn_count, flop3_count)
        print("   ◇◇ごちゃごちゃしている状態の為、ストレングスを解消", line_strength, "を０に", peaks_all[1]['count'],
              peaks_all[2]['count'], peaks_all[3]['count'])
        # line_strength = 0

    return_dic = {  # take_position_flagの返却は必須。Trueの場合注文情報が必要。
        "line_strength": line_strength,
        "line_price": target_price,
        "line_direction": target_dir,  # 1の場合UpperLine（＝上値抵抗）
        "latest_direction": latest_dir,  # lineDirectionとは異なる(基本は逆になる）
        "line_base_time": river_peak_time,  # 調査の開始対象となったLINE価格の元になる時刻
        "latest_foot_gap": 99 if len(same_list) == 0 else same_list[0]['count_foot_gap'],
        "latest_time": peaks_all[0]['time'],  # 実際の最新時刻
        "line_on_num": len(same_list),
        "minus_counter": minus_counter,
        "decision_price": target_df.iloc[0]['close'],
        "between_num": between_num,
        "same_time_latest": 0 if len(same_list) == 0 else same_list[0]['time']  # 一番近い同一価格と判断した時刻
    }

    # if return_dic['line_strength'] != 0:
    #     print("△結果")
    #     print(return_dic)
    #     # f.print_json(return_dic)
    # print(" --")
    print(" 結果", line_strength, return_dic)
    return return_dic


def find_lines_mm(df_r):
    """
    find_latest_lineを繰り返し呼び出す。
    基本FindLinesと同等だが、こちらは、river～flop3までの最大値最小値が優先される.

    直近のUpperLineとLowerLineが発見されるまで繰り返す
    :param df_r:
    :return:
    """
    # 初期値の設定
    target_df = df_r[:36]  # ３時間分

    # まずピークスを求める
    peaks_info = p.peaks_collect_main(df_r, 15)
    peaks_all = peaks_info["all_peaks"]
    print("全ピークス", peaks_all)

    # （０）LINE以外の値を算出する。Latestのサイズ感や、最高値等
    latest_gap = peaks_all[0]['gap']
    river_gap = peaks_all[1]['gap']
    # LatestとRiverの関係を求める（latestが大きいケースが、外しているケースが多い）Riverの0.4倍以下程度あってほしい
    lr_ratio = latest_gap / river_gap

    # river~flop3までの最大値、最小値を求める
    high_peak = 0
    low_peak = 9999
    for i, item in enumerate(peaks_all):
        if i == 3:
            # river1 turn2 flop3 3 まで
            break
        else:
            if item['peak'] > high_peak:
                high_peak = item['peak']
            elif item['peak'] < low_peak:
                low_peak = item['peak']

    # (1)探索する（latestのupperとLow、信頼度が最も高いランクのUpperとLowerを取得する）
    lines = []
    latest_flag = False
    latest_upper_flag = False
    latest_lower_flag = False
    latest_line = latest_upper_line = latest_lower_line = lower_line = upper_line = {}
    for i in range(len(peaks_all)):
        # ■探索(peaksをひとつづつ減らしていく。df_rは減らさない)
        range_result = find_latest_line(df_r, peaks_all[i:])  # 引数二つ渡しで関数を呼ぶ（無効ではPeaks_allのみ利用）
        # ■初回の特別処理
        # latest_line(現在時刻から見て直近のリバーのピーク価格）
        if i == 0:
            latest_line = range_result

        # ■ループを抜ける処理
        if range_result['line_strength'] == 0:
            # Lineを発見出来ない場合は特に何もしない
            continue

        # ■Lineの最大値や最小値を判定していく
        # 初回のアッパーラインとロアラインを取得する(latestは、latest_upperかlatest_lowerと同値）抵抗
        if not latest_upper_flag and range_result['line_direction'] == 1:
            # Upperの場合(アッパー最初フラグがない　かつ、アッパーの場合）
            latest_upper_flag = True
            latest_upper_line = range_result
            upper_line = range_result
        elif not latest_lower_flag and range_result['line_direction'] == -1:
            # Lowerの場合（ロア最初フラグがない　かつ　アッパーの場合）
            latest_lower_flag = True
            latest_lower_line = range_result
            lower_line = range_result
        # UpperとLowerを検証を更新していく
        if 'line_price' in upper_line and range_result['line_price'] > upper_line['line_price'] and range_result[
            'line_direction'] == 1:
            # 今回のラインプライスがアッパーラインを超えた場合
            upper_line = range_result
        elif 'line_price' in lower_line and range_result['line_price'] < lower_line['line_price'] and range_result[
            'line_direction'] == -1:
            # 今回のラインプライスがロアラインを超えた場合
            lower_line = range_result

    # フラグの更新
    if latest_line['line_strength'] != 0:  # >= 1.5:
        latest_flag = True

    # latestのラインと、最高最低のラインがほぼ同じ数字の場合、フラグを立てておく
    if 'line_price' in latest_upper_line:
        if latest_upper_line['line_price'] > upper_line['line_price'] - 0.02:
            # latest_upperlineがほぼ最高Lineの場合。（Upperの方が上にあり、少し下がったとこより上側にLatestがいる場合）
            latest_upper_is_upper = True
        else:
            latest_upper_is_upper = False
    else:
        latest_upper_is_upper = False

    if 'line_price' in latest_lower_line:
        if latest_lower_line['line_price'] < lower_line['line_price'] + 0.02:
            latest_lower_is_lower = True
        else:
            latest_lower_is_lower = False
    else:
        latest_lower_is_lower = False

    return_dic = {
        "latest_flag": latest_flag,
        "latest_line": latest_line,
        "found_upper": latest_upper_flag,
        "latest_upper_line": latest_upper_line,
        "upper_line": upper_line,
        "latest_upper_is_upper": latest_upper_is_upper,
        "found_lower": latest_lower_flag,
        "latest_lower_line": latest_lower_line,
        "lower_line": lower_line,
        "latest_lower_is_lower": latest_lower_is_lower,
        "latest_size_ratio": round(lr_ratio, 3),
        "latest_direction": peaks_all[0]['direction']
    }
    # 返却する
    return return_dic


def make_orders_resistance_line(df_r):
    """
    抵抗線を用いた解析のまとめ。
    基本的に,InspectionMain関数から呼ばれ、オーダー候補を返却する。
    ただし、ほかの解析と複合する場合は少し微妙の場合もあるため、
    抵抗線のみを用いた解析（このファイル内の単品解析）の場合はここで計算を行う方向
    """
