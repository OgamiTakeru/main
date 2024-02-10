import programs.fTurnInspection as f  # とりあえずの関数集
import programs.tokens as tk  # Token等、各自環境の設定ファイル（git対象外）
import programs.classOanda as oanda_class
import programs.fPeakLineInspection as p  # とりあえずの関数集
import programs.fGeneric as f
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
        ans = True
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
        ans = False
        margin = 0

    return {
        "ans": ans,
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


def turn2Rule(df_r):
    """
    １、
    :return:
    """
    print("TURN2　ルール")
    df_r_part = df_r[:90]  # 検証に必要な分だけ抜き取る
    peaks_info = p.peaks_collect_main(df_r_part)  # Peaksの算出
    peaks = peaks_info['all_peaks']
    peaks = add_stdev(peaks)  # 偏差値を付与する
    f.print_arr(peaks)
    print("PEAKS↑")

    # 必要なピークを出す
    peak_l = peaks[0]  # 最新のピーク  これは２＝折り返し直後　の関数になる
    peak_m = peaks[1]  # いわゆる戻し部分
    peak_o = peaks[2]  # 基準(プリフロップ）
    peaks_times = "Old:" + f.delYear(peak_o['time_old']) + "-" + f.delYear(peak_o['time']) + "_" + \
                  "Mid:" + f.delYear(peak_m['time_old']) + "-" + f.delYear(peak_m['time']) + "_" + \
                  "Latest" + f.delYear(peak_l['time_old']) + "-" + f.delYear(peak_l['time'])
    print("対象")
    print(peak_o)
    print(peak_m)
    print(peak_l)

    # 条件ごとにフラグを立てていく
    # ①偏差値の条件
    if peak_o['stdev'] > 55:
        f_size = True
        print("  偏差値達成", peak_o['stdev'])
    else:
        f_size = False
        print("  偏差値未達", peak_o['stdev'])

    # ②カウントの条件
    if peak_l['count'] == 2 and peak_o['count'] >= 7:
        f_count = True
        print("  カウント達成")
    else:
        f_count = False
        print(" カウント未達")

    # ③戻り割合の条件
    if peak_m['gap'] / peak_o['gap'] < 0.5:
        f_return = True
        print("  割合達成", peak_l['gap'], peak_o['gap'], round(peak_l['gap'] / peak_o['gap'], 1))
    else:
        f_return = False
        print("  割合未達", peak_l['gap'], peak_o['gap'], round(peak_l['gap'] / peak_o['gap'], 1))


    if f_count and f_return and f_size:
        ans = True
    else:
        ans = False

    return {
        "ans": ans,
        "s_time": df_r_part.iloc[0]['time_jp'],
        "trigger_price": peak_l['peak'],
        "lc_range": peak_o['gap']/4,
        "tp_range": 0.05,
        "expect_direction": peak_o['direction'],
        # 以下参考項目
        "stdev": peak_o['stdev'],
        "o_count": peak_o['count'],
        "reterun_ratio": round(peak_l['gap'] / peak_o['gap'],1)
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


