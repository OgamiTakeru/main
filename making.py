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


def size_compare(target, partner, min_range, max_range):
    """
    二つの数字のサイズ感を求める。
    (例）10, 9, 0.8, 1.2 が引数で来た場合、10の0.8倍＜9＜10の1.1倍　を満たしているかどうかを判定。
    :param partner: 比較元の数値（「現在に近いほう」が渡されるべき。どう変わったか、を結果として返却するため）
    :param target: 比較対象の数値
    :param min_range: 最小の比率
    :param max_range: 最大の比率
    :return: {flag: 同等かどうか, comment:コメント}
    """
    if target * min_range <= partner <= target * max_range:
        # 同レベルのサイズ感の場合
        same_size = True
        size_compare = 0
        size_compare_comment = "同等"
    elif partner > target * max_range:
        # 直近を誤差内の最大値で考えても、partner(過去)より小さい ⇒ 動きが少なくなった瞬間？
        same_size = False
        size_compare = -1
        size_compare_comment = "小さくなる変動直後"
    elif partner < target * min_range:
        # 直近を誤差内の最小値で考えても、partner（過去）より大きい ⇒ 動きが激しくなった瞬間？
        same_size = False
        size_compare = 1
        size_compare_comment = "大きくなる変動直後"
    else:
        # 謎の場合
        same_size = False
        size_compare = 0
        size_compare_comment = "謎"
    # 表示用
    print("      ", same_size, size_compare_comment, " ", target,
          "範囲", partner, "[", round(target * min_range, 2), round(target * max_range, 2), "]", round(target / partner, 3))
        
    # 【判定を上書き】大きいほうを基準に考える（２と４が与えられた場合、２に係数をかける基準だと範囲が狭い。４に係数をかける ⇒　targetに大きい数を入れる）
    if partner > target:
        change = 1  # 入れ替えたか(入れ替えると大小関係が逆になる）
        target1 = partner
        partner1 = target
    else:
        change = 0
        target1 = target
        partner1 = partner

    if target1 * min_range <= partner1 <= target1 * max_range:
        # 同レベルのサイズ感の場合
        same_size = True
        size_compare = 0
        size_compare_comment = "同等"
    elif partner1 > target1 * max_range:
        # 直近を誤差内の最大値で考えても、partner(過去)より小さい ⇒ 動きが少なくなった瞬間？
        if change == 1:
            same_size = False
            size_compare = 1
            size_compare_comment = "大きくなる変動直後"
        else:
            same_size = False
            size_compare = -1
            size_compare_comment = "小さくなる変動直後"
    elif partner1 < target1 * min_range:
        # 直近を誤差内の最小値で考えても、partner（過去）より大きい ⇒ 動きが激しくなった瞬間？
        if change == 1:
            same_size = False
            size_compare = -1
            size_compare_comment = "小さくなる変動直後"
        else:
            same_size = False
            size_compare = 1
            size_compare_comment = "大きくなる変動直後"
    else:
        # 謎の場合
        same_size = False
        size_compare = 0
        size_compare_comment = "謎"
    # 表示用
    print("      ", same_size, size_compare_comment, " ", target1,
          "範囲", partner1, "[", round(target1 * min_range, 2), round(target1 * max_range, 2), "]", round(target1 / partner, 3))

    return {
        "same_size": same_size,  # 同等の場合のみTrue
        "size_compare": size_compare,  # 判定結果として、大きくなった＝１、同等＝０、小さくなった＝ー１
        "size_compare_ratio": round(target / partner, 3),  # 具体的に何倍だったか
        "size_compare_comment": size_compare_comment,
        "min": round(target * min_range, 2),
        "max": round(target * max_range, 2),
        "partner": partner,
        "target": target,
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
        take_position = False
    else:
        take_position = False

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

    # ダブルトップの条件
    #  フロップ3↓
    #        /\  /\ ←リバー
    #       /  \/ ←ターン
    #      /
    #     ↑フロップ2
    #  ①フロップ３とターンが同値レベル
    #  ②フロップ３とターン2よりも小さい（0.8くらい）
    #  ③フロップ３は偏差値４０（４ピップス程度）は欲しい。
    if turn_flop3_type == 0 and flop3_flop2_ratio < 0.8:
        # ダブルトップ系（出来れば偏差値50くらいも条件に入れたいけれど）。turn_flop3==0でもいいかも？トリプルトップっぽくなる
        take_position = True
        if peak_flop3['direction'] == -1:
            print("  ダブルトップ", turn_flop3_type, flop3_flop2_ratio)
        else:
            print("  ダブルボトム", turn_flop3_type, flop3_flop2_ratio)

    else:
        print(" ダブル系ならず", turn_flop3_type, flop3_flop2_ratio)

    return {
        # ポジション検証に必要な要素
        "take_position": take_position,  # ポジション取得指示あり
        "s_time": df_r_part.iloc[0]['time_jp'],  # 直近の時刻（ポジションの取得有無は無関係）
        "trigger_price": df_r_part.iloc[0]['open'],  # 直近の価格（ポジションの取得有無は無関係） 直近の足のOpenが事実上の最新価格
        "lc_range": peak_flop3['gap']/4,  # ロスカットレンジ（ポジションの取得有無は無関係）
        "tp_range": 0.05,  # 利確レンジ（ポジションの取得有無は無関係）
        "expect_direction": peak_turn['direction'],  # ターン部分の方向
        # 以下参考項目
        "turn_gap": peak_turn['gap'],
        "turn_count": peak_turn['count'],
        "river_count": peak_river['count']
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


