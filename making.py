import fTurnInspection as t  # とりあえずの関数集
import tokens as tk  # Token等、各自環境の設定ファイル（git対象外）
import classOanda as oanda_class
import fPeakLineInspection as p  # とりあえずの関数集
import fGeneric as f
import statistics

oa = oanda_class.Oanda(tk.accountIDl, tk.access_tokenl, "live")  # クラスの定義


def add_stdev(peaks):
    """
    引数として与えられたPeaksに対して、偏差値を付与する
    :return:
    """
    # Gapのみを配列に置き換え（いい方法他にある？）
    targets = []
    for i in range(len(peaks)):
        targets.append(peaks[i]['gap'])
    # 平均と標準偏差を算出
    ave = statistics.mean(targets)
    stdev = statistics.stdev(targets)
    # 各偏差値を算出し、Peaksに追加しておく
    for i, item in enumerate(targets):
        peaks[i]["stdev"] = round((targets[i]-ave)/stdev*10+50, 2)

    return peaks


def size_compare(after_change, before_change, min_range, max_range):
    """
    二つの数字のサイズ感を求める。
    (例）10, 9, 0.8, 1.2 が引数で来た場合、10の0.8倍＜9＜10の1.1倍　を満たしているかどうかを判定。
    :param before_change:　比較対象の数値 （
    :param after_change: 比較元の数値（「現在に近いほう」が渡されるべき。どう変わったか、を結果として返却するため）
    :param min_range: 最小の比率
    :param max_range: 最大の比率
    :return: {flag: 同等かどうか, comment:コメント}
    """

    # (1)順番をそのままでサイスの比較を実施する
    amount_of_change = after_change - before_change  # 変化量（変化後ー変化前）
    amount_of_change_abs = abs(amount_of_change)  # 変化量の絶対値
    change_ratio = round(after_change / before_change, 3)  # AfterがBeforeの何倍か。（変化量ではなく、サイズのパーセンテージ）
    change_ratio_r = round(before_change / after_change, 3)  # AfterがBeforeの何倍か。（変化量ではなく、サイズのパーセンテージ）

    # （２）大きい方を基準にして、変化率を求める
    if before_change > after_change:
        big = before_change
        small = after_change
    else:
        big = after_change
        small = before_change

    if big * min_range <= small <= big * max_range:
        # 同レベルのサイズ感の場合
        same_size = 0
    else:
        # 謎の場合
        same_size = -1

    # 表示用
    # print("      ", same_size, size_compare_comment, " ", after_change,
    #       "範囲", before_change, "[", round(after_change * min_range, 2), round(after_change * max_range, 2), "]", round(after_change / before_change, 3))

    return {
        # 順番通りの大小比較結果
        "size_compare_ratio": change_ratio,
        "size_compare_ratio_r": change_ratio_r,
        "gap": amount_of_change,
        "gap_abs": amount_of_change_abs,
        # サイズが同等かの判定
        "same_size": same_size,  # 同等の場合のみTrue
    }


def turn3Rule(df_r):
    """
    １、大きな変動のピーク①を確認
    　・偏差値にして６０程度
    　・直近２時間において最安、最高を更新するようなピーク
    ２，大きなピークの次（１回の折り返し後）、ピーク①の半分以下の戻しであるピーク②が発生
    　・基本的に大きな後は半分も戻らないことが多い気がするが。。
    ３，ピーク②の後、ピーク①の折り返し地点とほぼ同程度までの戻しのピーク③が直近。
    ４，この場合はピーク①の終了価格とピーク②の終了価格のレンジとなる可能性が高い。
    　　＝ピーク③が確定した瞬間に、レンジ方向にトレール注文発行。（ようするにダブルトップorダブルボトムの形）
    :param df_r:
    :return:
    """
    print("TURN3　ルール")
    df_r_part = df_r[:90]  # 検証に必要な分だけ抜き取る
    peaks_info = p.peaks_collect_main(df_r_part)  # Peaksの算出
    peaks = peaks_info['all_peaks']
    peaks = add_stdev(peaks)  # 偏差値を付与する
    f.print_arr(peaks)

    # ピークの設定
    peak_big = peaks[3]  # 一番長いピーク（起点）
    peak2 = peaks[2]
    peak3 = peaks[1]
    latest = peaks[0]
    print(latest)
    print(peak3)
    print(peak2)
    print(peak_big)

    # 折り返し出来たてを狙う（ピーク③の発見）
    jd_time = True if latest['count'] <= 2 else False
    print(" TIME", jd_time, latest['count'])

    # ピーク１の変動が大きいかどうか (かつ３本以上のあしで構成される: １つだけが長いのではなく、継続した移動を捉えたい）
    big_border = 58
    jd_big = True if peak_big['stdev'] > big_border else False
    print(" BIG", jd_big, peak_big['stdev'])

    # 大きなピーク(1)後のピーク(2)が、大きなピークの半分以下か。
    jd_ratio = True if peak2['gap'] < (peak_big['gap'] / 2) else False
    print(" RATIO", jd_ratio, peak2['gap'], (peak_big['gap'] / 2))

    # ピーク(3)の終了価格が、大きなピーク(1)の終了価格の前後の場合（ダブルトップ）  上と下で分けた方がよい？
    range = 0.05  # 許容される最初のピークとの差（小さければ小さいほど理想のダブルトップ形状となる）
    jd_double = True if peak_big['peak'] - range < peak3['peak'] < peak_big['peak'] + range else False
    print(" DOUBLE", jd_double, peak_big['peak'], peak3['peak'], peak3['peak']-peak_big['peak'])

    if jd_big and jd_time and jd_ratio and jd_double:
        start_price = latest['peak']
        latest_direction = latest['direction']
        expect_direction = latest['direction']  # * -1
        ans = True
        print("条件達成", expect_direction)
    else:
        start_price = 0
        latest_direction = 0
        expect_direction = 0
        ans = False

    # LC【価格】を確定する（ピーク２(大きいものからの戻りのピーク）の３分の１だけの移動距離　±　ピーク１の直近価格)
    lc_range_temp = peak2['gap'] / 3
    lc_price = peak_big['peak'] + (lc_range_temp * peak_big['direction'])
    print(" LCcal", peak2['gap'], lc_range_temp)

    # TP【価格】を確定する
    tp_price = 0.045

    return {
        "ans": ans,
        "s_time": df_r_part.iloc[0]['time_jp'],
        "trigger_price": start_price,
        "lc_range": round(abs(lc_price - start_price), 3),
        "tp_range": round(tp_price, 3),  # 今は幅がそのまま入っている
        "expect_direction": expect_direction,
        "peakBIG_start": peak_big['time_old'],
        "peakBIG_end": peak_big['time'],
        "peakBIG_Gap": peak_big['gap'],
        "BIG": peak_big['stdev'],
        "peakBigNext_END": peak2['time'],
        "peakReturn": peak3['time'],
        "BIG_JD": jd_big,
        "2FEET": latest['count'],
        "2FEET_JD": jd_time,
        "RETURN_big": peak_big['gap'],
        "RETUEN_big_next": peak2['gap'],
        "RETURN_JD": jd_ratio,
        "PEAK_GAP": peak3['peak']-peak_big['peak'],
        "PEAK_GAP_JD": jd_double,
        "lc_price": round(abs(lc_price), 3),
        "tp_price": round(tp_price, 3),  # 今は幅がそのまま入っている
    }


def turn1Rule(df_r):
    """
    １、
    :return:
    """
    print("TURN1　ルール")
    df_r_part = df_r[:90]  # 検証に必要な分だけ抜き取る
    peaks_info = p.peaks_collect_main(df_r_part)  # Peaksの算出
    peaks = peaks_info['all_peaks']
    peaks = add_stdev(peaks)  # 偏差値を付与する
    f.print_arr(peaks)
    print("PEAKS↑")

    # 必要なピークや価格を取得する
    now_price = df_r_part.iloc[0]['close']
    peak_l = peaks[0]  # 最新のピーク
    peak_o = peaks[1]
    peaks_times = "Old:" + f.delYear(peak_o['time_old']) + "-" + f.delYear(peak_o['time']) + "_" + \
                  "Latest:" + f.delYear(peak_l['time_old']) + "-" + f.delYear(peak_l['time'])
    print("対象")
    print(peak_o)
    print(peak_l)

    # 条件ごとにフラグを立てていく
    expect_direction = peak_o['direction']
    # ①カウントの条件
    if peak_l['count'] == 2 and peak_o['count'] >= 6:
        f_count = True
        print("  カウント達成")
    else:
        f_count = False
        print(" カウント未達")

    # ②戻り割合の条件
    if peak_l['gap'] / peak_o['gap'] < 0.34:
        f_return = True
        print("  割合達成", peak_l['gap'], peak_o['gap'], round(peak_l['gap'] / peak_o['gap'], 1))
    else:
        f_return = False
        print("  割合未達", peak_l['gap'], peak_o['gap'], round(peak_l['gap'] / peak_o['gap'], 1))

    # ③偏差値の条件
    if peak_o['stdev'] > 54:
        f_size = True
        print("  偏差値達成", peak_o['stdev'])
    else:
        f_size = False
        print("  偏差値未達", peak_o['stdev'])

    # ■情報の統合
    if f_count and f_return and f_size:
        take_position = True
        margin = 0.0
    #     # ■３０分足の確認
    #     jp_time = f.str_to_time(df_r_part.iloc[0]['time_jp'])
    #     euro_time_datetime = jp_time - datetime.timedelta(hours=9)
    #     euro_time_datetime_iso = str(euro_time_datetime.isoformat()) + ".000000000Z"  # ISOで文字型。.0z付き）
    #     param = {"granularity": "M30", "count": 10, "to": euro_time_datetime_iso}  # 最低５０行
    #     long_df_temp = oa.InstrumentsCandles_multi_exe("USD_JPY", param, 1)
    #     long_df = long_df_temp["data"]
    #     long_df_r = long_df.sort_index(ascending=False)
    #     long_peaks_info = p.peaks_collect_main(long_df_r)  # Peaksの算出
    #     long_peaks = long_peaks_info['all_peaks']
    #     long_peaks = add_stdev(long_peaks)  # 偏差値を付与する
    #     long_peaks = long_peaks[:2]
    #     print("★広いスパンのDF", jp_time)
    #     print(long_df_r.head(5))
    #     f.print_arr(long_peaks)
    #     # ピーク幅を求めるため、最大と最小の価格を求める
    #     peak_prices = []
    #     for i, item in enumerate(long_peaks):  # 複数個でもいいように、For文で取得しておく
    #         peak_prices.append(item['peak'])
    #         peak_prices.append(item['peak_old'])
    #     peak_prices.sort()  # 昇順(左が小）に並び替える
    #     long_min = peak_prices[0]
    #     long_max = peak_prices[-1]
    #     print(long_min, long_max)
    #
    #     # 現在の価格が、長いスパンで見るとどの程度の位置にいるのかを確認
    #     # ＜考え方＞
    #     # ３０分足２個分のピークの最大値最小値を取得
    #     # 最大値ー最小値間を４分割し(mm_gap)、両端は外側の力が強いと判断。
    #     # 内側の二つは、更に内に向く力が強いと判断
    #     # いずれはその時の方向も考慮しないといけないと思う
    #     mm_gap = (long_max - long_min) / 4
    #     upper_from = long_max - mm_gap  # これ以上が上昇？
    #     lower_from = long_min + mm_gap  # これ以下が下降？
    #     if long_min < now_price < long_max:
    #         print(" 長いスパンの変動の内側")
    #         if now_price > upper_from:
    #             print("　　上昇傾向？")
    #             long_predicted_direction = 1
    #         elif now_price < lower_from:
    #             print("    下降傾向？")
    #             long_predicted_direction = -1
    #         else:
    #             long_predicted_direction = expect_direction
    #     elif df_r_part.iloc[0]['close'] < long_min:
    #         print(" 長いスパンの変動より下落（ありえない？）")
    #         long_predicted_direction = expect_direction
    #     else:
    #         print(" 長いスパンの変動より上昇（ありえない？）")
    #         long_predicted_direction = expect_direction
    #         margin = peak_l['gap']
    else:
        take_position = False
        margin = 0

    return {
        "take_position": take_position,
        "s_time": df_r_part.iloc[0]['time_jp'],
        "trigger_price": df_r_part.iloc[0]['close'] + (expect_direction * margin),
        "lc_range": f.cal_at_least(0.050, peak_o['gap']/4),
        "tp_range": 0.06,# f.cal_at_least(0.065, peak_o['gap']/4),
        "expect_direction": expect_direction,
        # 以下参考項目
        # "long_predicted_direction": long_predicted_direction,
        "stdev": peak_o['stdev'],
        "o_count": peak_o['count'],
        "reterun_ratio": round(peak_l['gap'] / peak_o['gap'],1)
    }


def boxSearch(df_r):
    """
    データフレームを受け取り、範囲の中で、
    ・現在の価格の位置（縦方向に、下限上限からどの程度の高さにいるか）
    ・縦方向に見て、どこの価格帯に多く滞在しているか
        # (1) 範囲のを縦幅にN等分(大体５？）し、どこに滞在していることが多いかを確認する。また現在価格がどこに属するかも判定
    #
    #     /\/\   _ ←この部分が一番、滞在が濃い
    #    /       _
    #   /        _
    # 5%以下の場合は、動き始めた直後くらい
    # 10%以下の滞在率の場合、かなり動き始めて、最初のターン直後くらい
    # 20%以下の場合、動き始めて１山程度のレンジに入ったような状態
    # 結果は[〇%、×%]となり、左（添え字０）が低い価格帯。添え字はcontain_grid_now。
    # 例えばN=5で[5,10,15,20,50]でcontain_grid_now =1 の場合、やや低価格の位置にいる事になる・
    :param df_r:
    :return:
    """
    print("ボックスサーチ")
    df_r = df_r[:60]  # 検証に必要な分だけ抜き取る 90の場合7.5時間前。５時間（６０）くらいでいい？

    box_max = df_r["high"].max()
    box_min = df_r["low"].min()
    grid_num = 5
    grid_range = (box_max - box_min) / grid_num  # 範囲を５等分にする
    contain_grid_now = 0
    now_price = df_r.iloc[0]['close']
    #
    grid_ans = []
    grid_ans_ratio = []
    for g in range(grid_num):
        min_temp = box_min + grid_range * g
        max_temp = box_min + grid_range * (g + 1)
        counter = 0
        # 現在の価格がどのグリッドかを確認
        # ToDo GridRangeのサイズによっても変る？
        if min_temp < now_price <= max_temp:
            contain_grid_now = g
        # 各行のグリッド滞在数を確認
        for i in range(len(df_r)):  # 時間短縮の為、本当はPeakでやりたいが、、一旦DFを直接
            if min_temp < float(df_r.iloc[i]['mid_outer']) <= max_temp:
                counter += 1

        grid_ans.append(counter)
        grid_ans_ratio.append(round(counter/len(df_r) * 100, 0))
        print(min_temp, max_temp, round(counter/len(df_r) * 100, 0))

    print("もっとも古いデータ", df_r.iloc[-1]['time_jp'], df_r.iloc[0]['time_jp'])
    print(grid_ans_ratio)
    print("現在の価格がどのグリッドか",contain_grid_now, grid_ans_ratio[contain_grid_now],now_price, round(grid_range, 3))


def doublePeak(df_r):
    """
    # ★ダブルトップについて
    #  フロップ3↓
    #        /\  /\ ←リバー
    #       /  \/ ←ターン
    #      /
    #     ↑フロップ2
    #  ＜成立条件＞
    #  ①フロップ３とターンが同値レベル(カウント数は不要かもしれない。あったとしても、２個でも有効なダブルトップがあった 2/13 03:05:00）
    #    ただし、フロップ３とターンの差分（gap）は0.008以内としたい。指定の範囲以内でも1pipsずれていると、見た目は結構ずれている。。
    #    その代わり、割合を少し広めにとる。
    #  ②フロップ３とターン2よりも小さい（0.8くらい）
    #  ③フロップ３は偏差値４０（４ピップス程度）は欲しい。
    #  ＜ポジション検討＞
    #  ①Directionはターンの方向とする。（正の場合、ダブルトップ突破方向）
    #  ②リバーの長さがMarginとなる。（marginは正の値のみ。渡した先でDirectionを考慮する）
    #
    :return:
    """
    print("ダブルピーク判定")
    df_r_part = df_r[:90]  # 検証に必要な分だけ抜き取る(時間的な部分）
    peaks_info = p.peaks_collect_main(df_r_part, 4)  # Peaksの算出（ループ時間短縮の為、必要最低限のピーク数（＝４）を指定する）
    peaks = peaks_info['all_peaks']
    peaks = add_stdev(peaks)  # 偏差値を付与する
    f.print_arr(peaks)
    print("PEAKS↑")

    # 必要なピークを出す
    peak_river = peaks[0]  # 最新のピーク（リバーと呼ぶ。このCount＝２の場合、折り返し直後）
    peak_turn = peaks[1]  # 注目するポイント（ターンと呼ぶ）
    peak_flop3 = peaks[2]  # レンジ判定用（プリフロップと呼ぶ）
    peak_flop2 = peaks[3]  # レンジ判定用（プリフロップと呼ぶ）
    peaks_times = "Old:" + f.delYear(peak_flop3['time_old']) + "-" + f.delYear(peak_flop3['time']) + "_" + \
                  "Mid:" + f.delYear(peak_turn['time_old']) + "-" + f.delYear(peak_turn['time']) + "_" + \
                  "Latest" + f.delYear(peak_river['time_old']) + "-" + f.delYear(peak_river['time'])
    print("対象")
    print("直近", peak_river)
    print("ターン", peak_turn)
    print("古い3", peak_flop3)
    print("古い2", peak_flop2)

    # (1) フロップ部の検証を行う⇒レンジ中なのかとかを確認できれば。。。
    col = "gap"  # 偏差値を使う場合はstdev　gapを使うことも可能
    # ⓪リバーとターンについての比率を確認
    print("  レンジ(フロップ３⇒ターン)")
    size_ans = size_compare(peak_river[col], peak_turn[col], 0.7, 1.42)
    river_turn_f = size_ans['same_size']
    river_turn_type = size_ans['size_compare']
    river_turn_gap = size_ans['gap']
    river_turn_ratio = size_ans['size_compare_ratio']
    river_turn_ratio_r = size_ans['size_compare_ratio_r']
    # ①ターンとフロップ３について、サイズの関係性取得する(同程度のgapの場合、レンジ？）
    print("  レンジ(フロップ３⇒ターン)")
    size_ans = size_compare(peak_turn[col], peak_flop3[col], 0.7, 1.42)
    turn_flop3_f = size_ans['same_size']
    turn_flop3_type = size_ans['size_compare']
    turn_flop3_gap = size_ans['gap']
    turn_flop3_ratio = size_ans['size_compare_ratio']
    turn_flop3_ratio_r = size_ans['size_compare_ratio_r']
    # ②フロップ３とフロップ２について、サイズの関係性を取得する
    print("  レンジ(フロップ２⇒フロップ3)")
    size_ans = size_compare(peak_flop3[col], peak_flop2[col], 0.85, 1.15)
    flop3_flop2_f = size_ans['same_size']
    flop3_flop2_ratio = size_ans['size_compare_ratio']
    flop3_flop2_type = size_ans['size_compare']
    # ③ ターンとフロップ2について、サイズの関係性を取得する（フロップ３を挟む両サイドを意味する）
    #    フロップ２⇒フロップ３が小、フロップ３⇒ターンが大の場合、下げ方向強めの可能性。フロップ２とターンを比較する
    print("  レンジ(フロップ２⇒ターン)")
    size_ans = size_compare(peak_turn[col], peak_flop2[col], 0.5, 2)
    turn_flop2_f = size_ans['same_size']
    turn_flop2_type = size_ans['size_compare']



    # 初期値の設定
    take_position_flag = False
    # 判定部分
    # (1)ダブルトップの成立を確認
    if river_turn_ratio <= 0.7:
        # riverがターンの７割程度の戻り程度の場合（戻りすぎていない）
        if turn_flop3_type == 0 and turn_flop3_gap <= 0.008:
            # V字部分が、ほぼ同一の高さ(比率だけではなく、Gap値でも判断）
            if 0.1 >= peak_turn['gap'] >= 0.01:
                # ターン部分の高さが、市営の範囲内
                # ★ダブルピーク確定
                if peak_flop3['direction'] == -1:
                    print("  ダブルトップ")
                else:
                    print("  ダブルボトム")
                # リバーの長さ（
                if peak_river['count'] >= 3:
                    take_position_flag = False
                else:
                    take_position_flag = True
            else:
                print("  ダブルトップ不成立：ターンの高さ範囲外")
        else:
            print("   ダブルトップ不成立：ターンVならず")
    else:
        print("   ダブルトップ不成立：Riverの戻り率対象外")
    print("    turn_flop3:", turn_flop3_type, round(turn_flop3_gap, 4), "turn_gap:", peak_turn['gap'])

    # (2)ダブルトップの前の情報　（ダブルトップ成立時に判定。ダブルトップ成立でも、事前条件が悪ければみなさない）
    if take_position_flag:
        if flop3_flop2_ratio < 0.6 or flop3_flop2_ratio > 1.5:
            # flop3とflop2のサイズ（ダブルトップへの入り方）についての条件
            # ダブルピーク確定
            if peak_flop3['direction'] == -1:
                print("  ダブルトップ")
            else:
                print("  ダブルボトム")
            # リバーの長さ（
            if peak_river['count'] >= 3:
                take_position_flag = False
            else:
                take_position_flag = True
        else:
            print("  ダブルトップ導入部未遂")
        print("    flop3_flop2:", flop3_flop2_ratio)

    # 返却値の整理整頓　(ターゲットプライスの算出）
    position_margin = peak_river['gap']
    stop_or_limit = -1  # マージンの方向(+値は期待方向に対して取得猶予を取る場合(順張り),－値は期待と逆の場合は逆張り）
    decision_price = df_r_part.iloc[0]['open']  # 計算用（リターンでも同じものを返却する）
    expected_direction = peak_river['direction']
    target_price = decision_price + (position_margin * expected_direction * stop_or_limit)
    print(take_position_flag)
    # print(" POSITION情報　決心価格", decision_price, "マージン", position_margin, "targetprice", target_price, "Ex方向", expected_direction)

    return {
        # ポジション検証に必要な要素
        "take_position_flag": take_position_flag,  # ポジション取得指示あり
        "decision_time": df_r_part.iloc[0]['time_jp'],  # 直近の時刻（ポジションの取得有無は無関係）
        "decision_price": df_r_part.iloc[0]['open'],  # ポジションフラグ成立時の価格（先頭[0]列のOpen価格）
        "position_margin": peak_river['gap'],  #ポジションまでのマージン
        "stop_or_limit": stop_or_limit,
        "target_price": target_price,
        "lc_range": peak_turn['gap'], # 0.04,  # ロスカットレンジ（ポジションの取得有無は無関係）
        "tp_range": peak_turn['gap'], #0.06,  # 利確レンジ（ポジションの取得有無は無関係）
        "expect_direction": peak_turn['direction'],  # ターン部分の方向
        # 以下参考項目
        "turn_gap": peak_turn['gap'],
        "turn_count": peak_turn['count'],
        "river_gap": peak_river['gap'],
        "river_count": peak_river['count'],
        "flop3_gap": peak_flop3['gap'],
        "flop3_count": peak_flop3['count'],
        "flop2_gap": peak_flop2['gap'],
        "flop2_count": peak_flop2['count'],
        "turn_flop3_ratio": turn_flop3_ratio,
        "flop3_flop2_ratio": flop3_flop2_ratio
    }


def doublePeak_multi(df_r, params):
    """
    １、
    :return:
    """
    # print("ダブルピーク判定")
    df_r_part = df_r[:90]  # 検証に必要な分だけ抜き取る
    peaks_info = p.peaks_collect_main(df_r_part)  # Peaksの算出
    peaks = peaks_info['all_peaks']
    peaks = add_stdev(peaks)  # 偏差値を付与する
    # f.print_arr(peaks)
    # print("PEAKS↑")

    # 必要なピークを出す
    peak_river = peaks[0]  # 最新のピーク（リバーと呼ぶ。このCount＝２の場合、折り返し直後）
    peak_turn = peaks[1]  # 注目するポイント（ターンと呼ぶ）
    peak_flop3 = peaks[2]  # レンジ判定用（プリフロップと呼ぶ）
    peak_flop2 = peaks[3]  # レンジ判定用（プリフロップと呼ぶ）
    # peaks_times = "Old:" + f.delYear(peak_flop3['time_old']) + "-" + f.delYear(peak_flop3['time']) + "_" + \
    #               "Mid:" + f.delYear(peak_turn['time_old']) + "-" + f.delYear(peak_turn['time']) + "_" + \
    #               "Latest" + f.delYear(peak_river['time_old']) + "-" + f.delYear(peak_river['time'])
    # print("対象")
    # print("直近", peak_river)
    # print("ターン", peak_turn)
    # print("古い3", peak_flop3)
    # print("古い2", peak_flop2)

    # (1) フロップ部の検証を行う⇒レンジ中なのかとかを確認できれば。。。
    col = "gap"  # 偏差値を使う場合はstdev　gapを使うことも可能
    size_ans = size_compare(peak_turn[col], peak_river[col], 0.7, 1.42)
    turn_river_f = size_ans['same_size']
    # ①ターンとフロップ３について、サイズの関係性取得する(同程度のgapの場合、レンジ？）
    # print("  レンジ(フロップ３⇒ターン)")
    size_ans = size_compare(peak_turn[col], peak_flop3[col], 0.7, 1.42)
    turn_flop3_f = size_ans['same_size']
    turn_flop3_type = size_ans['size_compare']
    turn_flop3_gap = size_ans['gap']
    turn_flop3_ratio = size_ans['size_compare_ratio']
    turn_flop3_ratio_r = size_ans['size_compare_ratio_r']
    # ②フロップ３とフロップ２について、サイズの関係性を取得する
    # print("  レンジ(フロップ２⇒フロップ3)")
    size_ans = size_compare(peak_flop3[col], peak_flop2[col], 0.85, 1.15)
    flop3_flop2_f = size_ans['same_size']
    flop3_flop2_ratio = size_ans['size_compare_ratio']
    flop3_flop2_type = size_ans['size_compare']
    # ③ ターンとフロップ2について、サイズの関係性を取得する（フロップ３を挟む両サイドを意味する）
    #    フロップ２⇒フロップ３が小、フロップ３⇒ターンが大の場合、下げ方向強めの可能性。フロップ２とターンを比較する
    # print("  レンジ(フロップ２⇒ターン)")
    size_ans = size_compare(peak_turn[col], peak_flop2[col], 0.5, 2)
    turn_flop2_f = size_ans['same_size']
    turn_flop2_type = size_ans['size_compare']

    # ★ダブルトップについて
    #  フロップ3↓
    #        /\  /\ ←リバー
    #       /  \/ ←ターン
    #      /
    #     ↑フロップ2
    #  ＜成立条件＞
    #  ①フロップ３とターンが同値レベル(カウント数は不要かもしれない。あったとしても、２個でも有効なダブルトップがあった 2/13 03:05:00）
    #  ②フロップ３とターン2よりも小さい（0.8くらい）
    #  ③フロップ３は偏差値４０（４ピップス程度）は欲しい。
    #  ＜ポジション検討＞
    #  ①Directionはターンの方向とする。（正の場合、ダブルトップ突破方向）
    #  ②リバーの長さがMarginとなる。（marginは正の値のみ。渡した先でDirectionを考慮する）

    # position_marginを計算しておく
    expected_direction = peak_turn['direction'] * params['dir']
    if params["margin_type"] == "turn":
        position_margin = (peak_turn['gap'] + params['margin']) * params['t_type'] * expected_direction
    elif params['margin_type'] == "river":
        position_margin = (peak_river['gap'] + params['margin']) * params['t_type'] * expected_direction
    elif params['margin_type'] == "both":
        position_margin = (peak_turn['gap'] + peak_river['gap'] + params['position_margin']) * params['t_type'] * expected_direction
    else:
        position_margin = params['margin'] * params['t_type'] * expected_direction
    take_position_flag = False

    # 初期値の設定
    take_position_flag = False
    # 判定部分
    if turn_flop3_type == 0 and turn_flop3_gap <= 0.008:
        # V字部分が、ほぼ同一の高さ
        if 0.1 >= peak_turn['gap'] >= params['turn_gap']:
            # ターン部分の高さが、市営の範囲内
            if params['f32_min'] < flop3_flop2_ratio < params['f32_max']:
                # flop3とflop2のサイズ（ダブルトップへの入り方）についての条件
                # ダブルピーク確定
                if peak_flop3['direction'] == -1:
                    print("  ダブルトップ")
                else:
                    print("  ダブルボトム")
                # リバーの長さ（
                if turn_river_f >= 0.8:
                    take_position_flag = False
                else:
                    take_position_flag = True
            else:
                pass
                # print("  ダブルトップ導入部未遂")
        else:
            pass
            # print("  ターンの高さ範囲外")
    else:
        pass
        # print("   ターンVならず")
    # print("    turn_flop3:", turn_flop3_type, round(turn_flop3_gap, 4), "flop3_flop2_ratio:", flop3_flop2_ratio,
    #       "turn_gap:", peak_turn['gap'])
    # print("   triggerPrice:", df_r_part.iloc[0]['open'], position_margin ,df_r_part.iloc[0]['open'] + position_margin)

    # 返却値の整理整頓　(ターゲットプライスの算出）
    position_margin = peak_river['gap']
    stop_or_limit = 1  # マージンの方向(+値は期待方向に対して取得猶予を取る場合(順張り),－値は期待と逆の場合は逆張り）
    decision_price = df_r_part.iloc[0]['open']  # 計算用（リターンでも同じものを返却する）
    expected_direction = peak_river['direction']
    target_price = decision_price + (position_margin * expected_direction * stop_or_limit)
    # print(" POSITION情報　決心価格", decision_price, "マージン", position_margin, "targetprice", target_price, "Ex方向", expected_direction)

    return {
        # ポジション検証に必要な要素
        "take_position_flag": take_position_flag,  # ポジション取得指示あり
        "decision_time": df_r_part.iloc[0]['time_jp'],  # 直近の時刻（ポジションの取得有無は無関係）
        "decision_price": df_r_part.iloc[0]['open'],  # ポジションフラグ成立時の価格（先頭[0]列のOpen価格）
        "position_margin": position_margin,  #
        "stop_or_limit": stop_or_limit,
        "target_price": target_price,
        "lc_range": 0.038,  # ロスカットレンジ（ポジションの取得有無は無関係）
        "tp_range": 0.038,  # 利確レンジ（ポジションの取得有無は無関係）
        "expect_direction": expected_direction,  # ターン部分の方向
        # 以下参考項目
        "turn_gap": peak_turn['gap'],
        "turn_count": peak_turn['count'],
        "river_count": peak_river['count']
    }


def stairsPeak(df_r):
    """
    １、
    :return:
    """
    print("ダブルピーク判定")
    df_r_part = df_r[:90]  # 検証に必要な分だけ抜き取る
    peaks_info = p.peaks_collect_main(df_r_part)  # Peaksの算出
    peaks = peaks_info['all_peaks']
    peaks = add_stdev(peaks)  # 偏差値を付与する
    f.print_arr(peaks)
    print("PEAKS↑")

    # 必要なピークを出す
    peak_river = peaks[0]  # 最新のピーク（リバーと呼ぶ。このCount＝２の場合、折り返し直後）
    peak_turn = peaks[1]  # 注目するポイント（ターンと呼ぶ）
    peak_flop3 = peaks[2]  # レンジ判定用（プリフロップと呼ぶ）
    peak_flop2 = peaks[3]  # レンジ判定用（プリフロップと呼ぶ）
    peaks_times = "Old:" + f.delYear(peak_flop3['time_old']) + "-" + f.delYear(peak_flop3['time']) + "_" + \
                  "Mid:" + f.delYear(peak_turn['time_old']) + "-" + f.delYear(peak_turn['time']) + "_" + \
                  "Latest" + f.delYear(peak_river['time_old']) + "-" + f.delYear(peak_river['time'])
    print("対象")
    print("直近", peak_river)
    print("ターン", peak_turn)
    print("古い3", peak_flop3)
    print("古い2", peak_flop2)

    # (1) フロップ部の検証を行う⇒レンジ中なのかとかを確認できれば。。。
    col = "gap"  # 偏差値を使う場合はstdev　gapを使うことも可能
    # ①ターンとフロップ３について、サイズの関係性取得する(同程度のgapの場合、レンジ？）
    print("  レンジ(フロップ３⇒ターン)")
    size_ans = size_compare(peak_turn[col], peak_flop3[col], 0.83, 1.18)
    turn_flop3_f = size_ans['same_size']
    turn_flop3_ratio = size_ans['size_compare_ratio']
    turn_flop3_type = size_ans['size_compare']
    # ②フロップ３とフロップ２について、サイズの関係性を取得する
    print("  レンジ(フロップ２⇒フロップ3)")
    size_ans = size_compare(peak_flop3[col], peak_flop2[col], 0.85, 1.15)
    flop3_flop2_f = size_ans['same_size']
    flop3_flop2_ratio = size_ans['size_compare_ratio']
    flop3_flop2_type = size_ans['size_compare']
    # ③ ターンとフロップ2について、サイズの関係性を取得する（フロップ３を挟む両サイドを意味する）
    #    フロップ２⇒フロップ３が小、フロップ３⇒ターンが大の場合、下げ方向強めの可能性。フロップ２とターンを比較する
    print("  レンジ(フロップ２⇒ターン)")
    size_ans = size_compare(peak_turn[col], peak_flop2[col], 0.5, 2)
    turn_flop2_f = size_ans['same_size']
    turn_flop2_type = size_ans['size_compare']

    #  ★カクカクの条件
    #     フロップ3↓   /\←リバー    \                /\
    #           /\  /←ターン       \  /\             \ ↓ターン
    #  　　   　/  \/               \/  \ターン        \/\
    #       　/←フロップ2                 \/
    #  ① フロップ２とターン　＞　フロップ３　(0.7倍くらいが目安？）　
    #  ② フロップ２とターンのサイズ比は不問(結果的には関係するかも）
    #  ③ フロップ３のサイズもある程度必要（２個以上、編偏差値４０以上）　
    #  ④ フロップ２とターンの偏差値は45程度は必要（小さすぎると微妙）
    #  これらを満たしたとき、カクカクとみなす

    if turn_flop3_ratio > 1.2 and flop3_flop2_ratio < 0.8 and peak_turn['gap'] >= 0.05:
        # ターンがフロップ3のN倍以上（大きくなる）、フロップ３がフロップ２の0.N倍以内(小さくなる）
        #    \   ↓ フロップ3
        #     \  /\
        #      \/  \←ターン
        #           \/　←リバー
        take_position_flag = True
        expect_direction = peak_turn['direction']
        if peak_turn['direction'] == 1:
            # ターンが上向き（上昇）
            print("  カクカク上昇")
        else:
            # ターンが下向き（下降）
            print("  カクカク下降")
    elif turn_flop3_ratio < 0.8 and flop3_flop2_ratio > 1.2 and peak_flop3['gap'] >= 0.05:
        # ターンがフロップ3の0.N倍以内（小さくなる）、フロップ３がフロップ２のN倍以上(大きくなる）
        #
        #      /\←フロップ3
        #        \ ↓ターン
        #         \/\ ←リバー
        take_position_flag = True
        expect_direction = peak_turn['direction'] * -1
        if peak_turn['direction'] == 1:
            # ターンが下向き（下降）
            print("  カクカク下降")
        else:
            # ターンが上向き（上昇）
            print("  カクカク上昇")
    else:
        take_position_flag = False
        expect_direction = peak_turn['direction']
        print(" カクカク不成立", turn_flop3_ratio, ", ", flop3_flop2_ratio, ", ", peak_turn['gap'], ">=0.05")

    # リバーのタイミングを調整
    if peak_river['count'] != 2 and peak_river['count'] != 3:
        if take_position_flag:
            print(" リバー数でのポジション解除")
        take_position_flag = False



    return {
        # ポジション検証に必要な要素
        "take_position_flag": take_position_flag,  # ポジション取得指示あり
        "decision_time": df_r_part.iloc[0]['time_jp'],  # 直近の時刻（ポジションの取得有無は無関係）
        "decision_price": df_r_part.iloc[0]['open'],  # ポジションフラグ成立時の価格（先頭[0]列のOpen価格）
        "position_margin": 0.04,  #peak_turn['gap'],  #
        "lc_range": 0.05,  # ロスカットレンジ（ポジションの取得有無は無関係）
        "tp_range": 0.05,  # 利確レンジ（ポジションの取得有無は無関係）
        "expect_direction": expect_direction,  # ターン部分の方向
        # 以下参考項目
        "turn_gap": peak_turn['gap'],
        "turn_count": peak_turn['count'],
        "river_count": peak_river['count'],
        "flop3_flop2_ratio": flop3_flop2_ratio,
    }


def now_position(df_r):
    print("PositionInspection")
    # 今自分の価格がどんな状態にあるかを確認する
    df_r_part = df_r  # 検証に必要な分だけ抜き取る
    peaks_info = p.peaks_collect_main(df_r_part)  # Peaksの算出
    peaks = peaks_info['all_peaks']
    peaks = add_stdev(peaks)  # 偏差値を付与する
    print(df_r_part)
    f.print_arr(peaks)
    print("PEAKS↑")
    # # 必要なピークや価格を取得する
    # now_price = df_r_part.iloc[0]['close']
    # peak_l = peaks[0]  # 最新のピーク
    # peak_o = peaks[1]
    # peaks_times = "Old:" + f.delYear(peak_o['time_old']) + "-" + f.delYear(peak_o['time']) + "_" + \
    #               "Latest:" + f.delYear(peak_l['time_old']) + "-" + f.delYear(peak_l['time'])
    # print("対象")
    # print(peak_o)
    # print(peak_l)
    #
    # # 今存在のピークと、ひとつ前のピークの長さを求める
    # # 折り返し直後、ぐちゃぐちゃしてる時、等を判定する
    # # (1)　折り返しに関する調査（時間的な折り返し直後かどうか）
    # if peak_l['count'] <= 4 and peak_l['gap']/peak_o['gap'] < 0.5:
    #     print(" ターン直後")
    # else:
    #     print(" ターン以外")
    #
    # # (2)ターン以外の情報を収集する
    # if (peak_l['count'] <= 4 and peak_l['stdev'] < 50) and (peak_o['count'] <= 4 and peak_o['stdev'] < 50):
    #     print(" 短い者同士")
    #
    #


def turn2Rule(df_r):
    """
    １、
    :return:
    """
    print("ダブルピーク判定")
    df_r_part = df_r[:90]  # 検証に必要な分だけ抜き取る
    peaks_info = p.peaks_collect_main(df_r_part)  # Peaksの算出
    peaks = peaks_info['all_peaks']
    peaks = add_stdev(peaks)  # 偏差値を付与する
    f.print_arr(peaks)
    print("PEAKS↑")

    # 必要なピークを出す
    peak_river = peaks[0]  # 最新のピーク（リバーと呼ぶ。このCount＝２の場合、折り返し直後）
    peak_turn = peaks[1]  # 注目するポイント（ターンと呼ぶ）
    peak_flop3 = peaks[2]  # レンジ判定用（プリフロップと呼ぶ）
    peak_flop2 = peaks[3]  # レンジ判定用（プリフロップと呼ぶ）
    peaks_times = "Old:" + f.delYear(peak_flop3['time_old']) + "-" + f.delYear(peak_flop3['time']) + "_" + \
                  "Mid:" + f.delYear(peak_turn['time_old']) + "-" + f.delYear(peak_turn['time']) + "_" + \
                  "Latest" + f.delYear(peak_river['time_old']) + "-" + f.delYear(peak_river['time'])
    print("対象")
    print("直近", peak_river)
    print("ターン", peak_turn)
    print("古い3", peak_flop3)
    print("古い2", peak_flop2)

    # (1)リバーとターンで比較を実施する
    # ①偏差値の条件 (＠ターン）
    if peak_turn['stdev'] > 55:
        f_size = True
    else:
        f_size = False
    print("  偏差値:", f_size, " ", peak_flop3['stdev'])
    # ②カウントの条件（＠ターンとリバー）
    if peak_river['count'] == 2 and peak_turn['count'] >= 7:
        f_count = True
    else:
        f_count = False
    print("  カウント:", f_count, " 直近", peak_river['count'], "ターン", peak_turn['count'], "←直近2以下,ターン7以上でTrue")
    # ③戻り割合の条件（＠ターンとリバー）
    if peak_river['gap'] / peak_turn['gap'] < 0.5:  # 0.5の場合、半分以上戻っていたら戻りすぎ（False）。微戻り(半分以下)ならOK！
        f_return = True
    else:
        f_return = False
    print("  割合達成:", f_return, round(peak_river['gap'] / peak_turn['gap'], 1), " ", peak_river['gap'], peak_turn['gap'])
    # [最後]　各条件を考慮し、ポジションを持つかどうかを検討する
    if f_count and f_return and f_size:
        take_position_flag = False
    else:
        take_position_flag = False

    # (2) フロップ部の検証を行う⇒レンジ中なのかとかを確認できれば。。。
    col = "gap"  # 偏差値を使う場合はstdev　gapを使うことも可能
    # ①ターンとフロップ３について、サイズの関係性取得する(同程度のgapの場合、レンジ？）
    print("  レンジ(フロップ３⇒ターン)")
    size_ans = size_compare(peak_turn[col], peak_flop3[col], 0.83, 1.18)
    turn_flop3_f = size_ans['same_size']
    turn_flop3_type = size_ans['size_compare']
    # ②フロップ３とフロップ２について、サイズの関係性を取得する
    print("  レンジ(フロップ２⇒フロップ3)")
    size_ans = size_compare(peak_flop3[col], peak_flop2[col], 0.85, 1.15)
    flop3_flop2_f = size_ans['same_size']
    flop3_flop2_ratio = size_ans['size_compare_ratio']
    flop3_flop2_type = size_ans['size_compare']
    # ③ ターンとフロップ2について、サイズの関係性を取得する（フロップ３を挟む両サイドを意味する）
    #    フロップ２⇒フロップ３が小、フロップ３⇒ターンが大の場合、下げ方向強めの可能性。フロップ２とターンを比較する
    print("  レンジ(フロップ２⇒ターン)")
    size_ans = size_compare(peak_turn[col], peak_flop2[col], 0.5, 2)
    turn_flop2_f = size_ans['same_size']
    turn_flop2_type = size_ans['size_compare']
    # <結果>
    #
    #  カクカクの条件
    #     フロップ3↓   /\←リバー
    #           /\  /←ターン
    #  　　   　/  \/
    #       　/←フロップ2
    #  ① フロップ２とターン　＞　フロップ３　(0.7倍くらいが目安？）　
    #  ② フロップ２とターンのサイズ比は不問
    #  ③ フロップ２とターンの偏差値は45程度は必要（小さすぎると微妙）　
    #  ④ フロップ３のサイズもある程度必要（２個以上、編偏差値４０以上）
    #  これらを満たしたとき、カクカクとみなす
    if turn_flop3_type == 1 and flop3_flop2_type == -1 and turn_flop2_type == 0:
        if peak_flop2['direction'] == 1:
            print("  カクカク上がり発生中？")
        else:
            print("  カクカク下がり発生中？")
    elif turn_flop3_type == -1 and flop3_flop2_type == 1 and turn_flop2_type == 0:
        if peak_flop2['direction'] == 1:
            print("  カクカク上がり発生中？")
        else:
            print("  カクカク下がり発生中？")
    else:
        print(" ", turn_flop3_type, flop3_flop2_type, turn_flop2_type)

    # ★ダブルトップについて
    #  フロップ3↓
    #        /\  /\ ←リバー
    #       /  \/ ←ターン
    #      /
    #     ↑フロップ2
    #  ＜成立条件＞
    #  ①フロップ３とターンが同値レベル(カウント数は不要かもしれない。あったとしても、２個でも有効なダブルトップがあった 2/13 03:05:00）
    #  ②フロップ３とターン2よりも小さい（0.8くらい）
    #  ③フロップ３は偏差値４０（４ピップス程度）は欲しい。
    #  ＜ポジション検討＞
    #  ①Directionはターンの方向とする。（正の場合、ダブルトップ突破方向）
    #  ②リバーの長さがMarginとなる。（marginは正の値のみ。渡した先でDirectionを考慮する）
    #

    if turn_flop3_type == 0 and flop3_flop2_ratio < 0.8 and peak_turn['gap'] >= 0.03:
        # ダブルトップ系（出来れば偏差値50くらいも条件に入れたいけれど）。turn_flop3==0でもいいかも？トリプルトップっぽくなる
        # flop3_flop2_ratioはフロップ２が長いのが基本（フロップ3がフロップ２の5割り以内）　また、
        position_margin = peak_river['gap'] + peak_turn['gap']  # peak_turn['gap']  # peak_river['gap']*2# + 0.01
        if peak_flop3['direction'] == -1:
            print("  ダブルトップ", turn_flop3_type, flop3_flop2_ratio)
        else:
            print("  ダブルボトム", turn_flop3_type, flop3_flop2_ratio)
        # リバーが短くする場合
        if peak_river['count'] >= 5:
            take_position_flag = False
        else:
            take_position_flag = True

    else:
        take_position_flag = False
        position_margin = 0
        print(" ダブル系ならず", turn_flop3_type, flop3_flop2_ratio)

    return {
        # ポジション検証に必要な要素
        "take_position_flag": take_position_flag,  # ポジション取得指示あり
        "decision_time": df_r_part.iloc[0]['time_jp'],  # 直近の時刻（ポジションの取得有無は無関係）
        "decision_price": df_r_part.iloc[0]['open'],  # ポジションフラグ成立時の価格（先頭[0]列のOpen価格）
        "position_margin": position_margin,  #
        "lc_range": 0.04,  # ロスカットレンジ（ポジションの取得有無は無関係）
        "tp_range": 0.06,  # 利確レンジ（ポジションの取得有無は無関係）
        "expect_direction": peak_turn['direction'],  # ターン部分の方向
        # 以下参考項目
        "turn_gap": peak_turn['gap'],
        "turn_count": peak_turn['count'],
        "river_count": peak_river['count'],
        "flop3_flop2_ratio": flop3_flop2_ratio,
    }


def beforeDoublePeakBreak(*args):
    """
    引数は配列で受け取る。
    引数１つ目は配列。
    データフレームを受け取り、範囲の中で、
    ダブルトップ直前で、ダブルトップに向かう動きについて捉える
    引数２つ目はループ検証時のパラメータ群(ループ検証の時のみ入ってくる）
    ②パターン２

　　　　　　　　　  ターン↓　　/　←このでっぱり部が、5pips以内（リーバーがターンの1.1倍以内？）
       　　　　  　   /\  /
       フロップ　30→ /  \/  ← 6(リバー) ＋　割合だけでなく、5pipくらいトップピークまで余裕があれば。
          　　　　　/　　　　　　　　　←ピークの反対くらいがLC？

    :param df_r:
    :return:
    """
    print(args)
    print("直前　ダブルピークBreak判定")
    df_r = args[0]
    df_r_part = df_r[:90]  # 検証に必要な分だけ抜き取る
    peaks_info = p.peaks_collect_main(df_r_part, 3)  # Peaksの算出（ループ時間短縮の為、必要最低限のピーク数（＝４）を指定する）
    peaks = peaks_info['all_peaks']
    peaks = add_stdev(peaks)  # 偏差値を付与する
    f.print_arr(peaks)
    print("PEAKS↑")

    # 必要なピークを出す
    peak_river = peaks[0]  # 最新のピーク（リバーと呼ぶ。このCount＝２の場合、折り返し直後）
    peak_turn = peaks[1]  # 注目するポイント（ターンと呼ぶ）
    peak_flop3 = peaks[2]  # レンジ判定用（プリフロップと呼ぶ）
    peaks_times = "Old:" + f.delYear(peak_flop3['time_old']) + "-" + f.delYear(peak_flop3['time']) + "_" + \
                  "Mid:" + f.delYear(peak_turn['time_old']) + "-" + f.delYear(peak_turn['time']) + "_" + \
                  "Latest" + f.delYear(peak_river['time_old']) + "-" + f.delYear(peak_river['time'])
    print("対象")
    print("直近", peak_river)
    print("ターン", peak_turn)
    print("古い3", peak_flop3)

    # (1) ターンを基準に
    col = "gap"  # 偏差値を使う場合はstdev　gapを使うことも可能
    # ⓪リバーのターンに対する割合を取得（〇%に小さくなっている事を想定）
    size_ans = size_compare(peak_river[col], peak_turn[col], 0.1, 0.3)
    river_turn_gap = size_ans['gap']
    river_turn_ratio = size_ans['size_compare_ratio']
    # ①ターンのフロップ３に対する割合を取得（〇%に小さくなっていることを想定）
    size_ans = size_compare(peak_turn[col], peak_flop3[col], 0.1, 0.3)
    turn_flop3_ratio = size_ans['size_compare_ratio']
    print("   リバーのターン割合", river_turn_ratio, "ターンのフロップに対する割合", turn_flop3_ratio)

    # ★★判定部
    # 条件値の設定（引数の有る場合は引数から設定）
    if len(args) == 2:  # 引数が存在する場合
        params = args[1]
        rt_min = params['river_turn_ratio_min']
        rt_max = params['river_turn_ratio']
        tf_max = params['turn_flop_ratio']
        r_count = params['count']
        rt_gap_min = params['gap_min']
        rt_gap_max = params['gap']
        p_margin = params['margin']
        lc = abs(peak_turn['gap']-peak_river['gap'])
        tp = abs(peak_turn['gap']-peak_river['gap'])
        stop_or_limit = params['sl']
        d = params['d']
    else:
        rt_min = 1
        rt_max = 1.3
        tf_max = 0.6  # あんまり戻りすぎていると、順方向に行く体力がなくなる？？だから少なめにしたい
        r_count = 2
        rt_gap_min = 0.00
        rt_gap_max = 0.03  # リバーがターンより長い量が、どの程度まで許容か(大きいほうがいい可能性も？）
        p_margin = 0.05
        lc = peak_river['gap']
        tp = peak_river['gap']
        stop_or_limit = 1
        d = 1
    # 判定
    take_position_flag = False
    if peak_river['count'] == r_count:  # 戻り数　river['count']は要変更
        if rt_min < river_turn_ratio < rt_max and turn_flop3_ratio < tf_max:
            if 0 < river_turn_gap and  rt_gap_min < abs(river_turn_gap) < rt_gap_max:  # リバーの方が長く、ある程度達していたら
                take_position_flag = True
                print("   ■■BeforeダブルトップBreak完成", river_turn_ratio, turn_flop3_ratio, abs(river_turn_gap), peak_river['count'])
            else:
                print("   ポジションはする猶予無し（ダブルトップ候補までの距離）", river_turn_ratio, turn_flop3_ratio, river_turn_gap, peak_river['count'])
        else:
            print("   不成立Brearariok", river_turn_ratio, turn_flop3_ratio, abs(river_turn_gap), peak_river['count'])
    else:
        print("   不成立Break", river_turn_ratio, turn_flop3_ratio, abs(river_turn_gap), peak_river['count'])

    # target_priceを求める（そのが各変数を算出）
    position_margin = p_margin
    stop_or_limit = stop_or_limit  # # マージンの方向(+値は期待方向に対して取得猶予を取る場合(順張り),－値は期待と逆の場合は逆張り）
    decision_price = df_r_part.iloc[0]['open']  # 計算用（リターンでも同じものを返却する）
    expected_direction = peak_river['direction'] * d
    target_price = decision_price + (position_margin * expected_direction * stop_or_limit)
    print("   POSITION情報　決心価格", decision_price, "マージン", position_margin, "targetprice", target_price, "Ex方向", expected_direction, "Type", stop_or_limit)
    # print("   ", peak_turn['gap']-peak_river['gap'])
    return {
        # ポジション検証に必要な要素
        "take_position_flag": take_position_flag,  # ポジション取得指示あり
        "decision_time": df_r_part.iloc[0]['time_jp'],  # 直近の時刻（ポジションの取得有無は無関係）
        "decision_price": df_r_part.iloc[0]['open'],  # ポジションフラグ成立時の価格（先頭[0]列のOpen価格）
        "position_margin": position_margin,  # position_margin (+値は猶予大）
        "stop_or_limit": stop_or_limit,
        "target_price": target_price,
        "lc_range": lc, # 0.04,  # ロスカットレンジ（ポジションの取得有無は無関係）
        "tp_range": tp, #0.06,  # 利確レンジ（ポジションの取得有無は無関係）
        "expected_direction": expected_direction,
        # 以下参考項目
        "river_turn_ratio": river_turn_ratio,
        "turn_flop3_ratio": turn_flop3_ratio,
        "peak_river": peak_river['count'],
        "river_turn_gap": river_turn_gap,
        "tp_base": peak_turn['gap']-peak_river['gap']
    }


def beforeDoublePeak(*args):
    """
    引数は配列で受け取る。
    引数１つ目は配列。
    データフレームを受け取り、範囲の中で、
    ダブルトップ直前で、ダブルトップに向かう動きについて捉える
    引数２つ目はループ検証時のパラメータ群(ループ検証の時のみ入ってくる）
    ①理想形 (ダブルトップ到達前）
　　　　　　　　　　　　　　　　　
       　　　　  　   /\← 10（基準：ターン）　←このピークがTP(ターンが10pipsや8本足くらいある場合は避ける（ちょい戻りを超えてる））
       フロップ　30→ /  \/  ← 6(リバー) ＋　割合だけでなく、数pipくらいトップピークまで余裕があれば。
          　　　　　/　　　　　　　　　←ピークの反対くらいがLC？
    :param df_r:
    :return:
    """
    # print(args)
    print(" 直前ダブルピーク判定")
    df_r = args[0]
    df_r_part = df_r[:90]  # 検証に必要な分だけ抜き取る
    peaks_info = p.peaks_collect_main(df_r_part, 3)  # Peaksの算出（ループ時間短縮の為、必要最低限のピーク数（＝４）を指定する）
    peaks = peaks_info['all_peaks']
    peaks = add_stdev(peaks)  # 偏差値を付与する

    # 必要なピークを出す
    peak_river = peaks[0]  # 最新のピーク（リバーと呼ぶ。このCount＝２の場合、折り返し直後）
    peak_turn = peaks[1]  # 注目するポイント（ターンと呼ぶ）
    peak_flop3 = peaks[2]  # レンジ判定用（プリフロップと呼ぶ）
    peaks_times = "Old:" + f.delYear(peak_flop3['time_old']) + "-" + f.delYear(peak_flop3['time']) + "_" + \
                  "Mid:" + f.delYear(peak_turn['time_old']) + "-" + f.delYear(peak_turn['time']) + "_" + \
                  "Latest" + f.delYear(peak_river['time_old']) + "-" + f.delYear(peak_river['time'])
    print("  <対象>")
    print("  RIVER", peak_river)
    print("  TURN ", peak_turn)
    print("  FLOP3", peak_flop3)

    # (1) ターンを基準に
    col = "gap"  # 偏差値を使う場合はstdev　gapを使うことも可能
    # ⓪リバーのターンに対する割合を取得（〇%に小さくなっている事を想定）
    size_ans = size_compare(peak_river[col], peak_turn[col], 0.1, 0.3)
    river_turn_gap = size_ans['gap']
    river_turn_ratio = size_ans['size_compare_ratio']
    # ①ターンのフロップ３に対する割合を取得（〇%に小さくなっていることを想定）
    size_ans = size_compare(peak_turn[col], peak_flop3[col], 0.1, 0.3)
    turn_flop3_ratio = size_ans['size_compare_ratio']
    print("   リバーのターン割合", river_turn_ratio, "ターンのフロップに対する割合", turn_flop3_ratio)

    # ★★判定部
    # 条件値の設定（引数の有る場合は引数から設定）
    if len(args) == 2:  # 引数が存在する場合
        f_gap = 0.1
        params = args[1]
        rt_max = params['river_turn_ratio']
        tf_max = params['turn_flop_ratio']
        r_count = params['count']
        rt_gap_min = params['gap']
        p_margin = params['margin']
        lc = (peak_turn['gap']-peak_river['gap']) * 0.8
        tp = peak_turn['gap']-peak_river['gap']
    else:
        f_gap = 0.1  # new
        rt_max = 0.6  # 0.6
        tf_max = 0.6  # 0.6
        r_count = 2  # 2
        rt_gap_min = 0.01  # 0.03
        p_margin = 0.008  # 0.01
        lc = (peak_turn['gap']-peak_river['gap'])
        tp = (peak_turn['gap']-peak_river['gap'])
    # 判定
    take_position_flag = False
    if peak_river['count'] == r_count:  # リバーのカウント
        if river_turn_ratio < rt_max and turn_flop3_ratio < tf_max and peak_flop3['gap'] > f_gap:  # 戻り数　river['count']は要変更
            if abs(river_turn_gap) >= rt_gap_min:  # 5pips程度の戻りの有用があれば
                if peak_turn['gap'] <= 0.14 and peak_turn['count']<=8:  # 0.08,4
                    take_position_flag = True
                    print("   ■■Beforeダブルトップ完成", river_turn_ratio, turn_flop3_ratio, abs(river_turn_gap), peak_river['count'])
                else:
                    print("    不成立（ターン情報）　むしろ、逆に入れてもいいかも？？", peak_turn['gap'], peak_turn['count'])
            else:
                print("   ポジションはする猶予無し（ダブルトップ候補までの距離）", river_turn_ratio, turn_flop3_ratio, abs(river_turn_gap), peak_river['count'])
        else:
            print("   不成立 riverturn",river_turn_ratio," turnFlop3",turn_flop3_ratio,peak_flop3['gap'] )
    else:
        print("   不成立", river_turn_ratio, turn_flop3_ratio, abs(river_turn_gap), peak_river['count'])

    # target_priceを求める（そのが各変数を算出）
    position_margin = p_margin
    stop_or_limit = 1  # # マージンの方向(+値は期待方向に対して取得猶予を取る場合(順張り),－値は期待と逆の場合は逆張り）
    decision_price = df_r_part.iloc[0]['open']  # 計算用（リターンでも同じものを返却する）
    expected_direction = peak_river['direction']
    target_price = decision_price + (position_margin * expected_direction * stop_or_limit)
    print("   POSITION情報　決心価格", decision_price, "マージン", position_margin, "targetprice", target_price, "Ex方向", expected_direction)
    # print("   ", peak_turn['gap']-peak_river['gap'])
    return {
        # ポジション検証に必要な要素
        "take_position_flag": take_position_flag,  # ポジション取得指示あり
        "decision_time": df_r_part.iloc[0]['time_jp'],  # 直近の時刻（ポジションの取得有無は無関係）
        "decision_price": df_r_part.iloc[0]['open'],  # ポジションフラグ成立時の価格（先頭[0]列のOpen価格）
        "position_margin": position_margin,  # position_margin (+値は猶予大）
        "stop_or_limit": stop_or_limit,
        "target_price": target_price,
        "lc_range": lc, # 0.04,  # ロスカットレンジ（ポジションの取得有無は無関係）
        "tp_range": tp, #0.06,  # 利確レンジ（ポジションの取得有無は無関係）
        "expected_direction": expected_direction,
        # 以下参考項目
        "river_turn_ratio": river_turn_ratio,
        "turn_flop3_ratio": turn_flop3_ratio,
        "peak_river": peak_river['count'],
        "river_turn_gap": river_turn_gap,
        "tp_base": peak_turn['gap']-peak_river['gap']
    }



