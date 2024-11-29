import copy

import fPeakInspection as p  # とりあえずの関数集
import fGeneric as gene
import fDoublePeaks as dp
import tokens as tk

import fPeakInspection as peak_inspection
import fDoublePeaks as dp
import pandas as pd
import fMoveSizeInspection as ms
import fCommonFunction as cf
import fMoveSizeInspection as ms


def judge_flag_figure(peaks, target_direction, need_to_adjust):
    """
    旗の形状を探索するための、サポート関数
    peaks: ピークス
    num: ピークスの中で、直近num個分の中でフラッグ形状を判定する
    remark: コメント
    返り値は、成立しているかどうかのBoolean
    """

    # ■関数事前準備
    remark = "フラッグ不成立"
    s7 = "      "
    print(s7, " 新フラッグ調査関数")

    # ■■情報の整理と取得（関数の頭には必須）
    # #直接のテストで　argsが渡される場合
    # fixed_information = cf.information_fix(dic_args)  # DFとPeaksが必ず返却される
    # df_r = fixed_information['df_r']
    # peaks = fixed_information['peaks'][1:]
    # latest_direction = peaks[0]['direction']
    # 実運用でPeak渡される場合
    peaks = peak_inspection.hard_skip_after_peaks_cal(peaks)  # HARDスキップの場合
    latest_direction = peaks[0]['direction']

    # 返却値の基本
    return_base = {
        "is_tilt_line": False,
        "remark": ""
    }

    # ■TILTの判定を行う
    direction_integrity = True  # 方向性が一致しているかどうか（下側は上昇、上側が下降がここでは正とする）
    d = target_direction  # １の場合は上側、-1の場合は下側のピークスを対象として、調査をする
    tilt_result_list = []
    if need_to_adjust:
        # river側の場合に選択される。N個で検証
        adjuster = 1
    else:
        # turn側の場合に選択される。
        adjuster = 0

    # ■検証開始
    # for target_num in [3]:
    for target_num in range(3 - adjuster, 6 - adjuster):
        # num = i + 1  # iは０からスタートするため
        # ■■　情報を作成する
        target_peaks = [item for item in peaks if item["direction"] == d]  # 利用するのは、Lower側
        target_peaks = target_peaks[:target_num]
        if d == 1:
            # 上方向（が下がってきているかを確認）の場合、Max値
            min_index, min_or_max_info = max(enumerate(target_peaks), key=lambda x: x[1]["peak"])  # サイズ感把握のために取得
        else:
            # 下方向（が上ってきているかを確認）の場合、Min値
            min_index, min_or_max_info = min(enumerate(target_peaks), key=lambda x: x[1]["peak"])  # サイズ感把握のために取得
        oldest_info = target_peaks[-1]
        print(s7, "@調査するピークス", d, target_num)
        gene.print_arr(target_peaks, 7)
        print(s7, "先頭の情報", target_peaks[0]['peak'], target_peaks[0]['time'])
        print(s7, "最後尾の情報", oldest_info['peak'], oldest_info['time'])
        y_change = target_peaks[0]['peak'] - oldest_info['peak']
        if abs(y_change) <= 0.02:
            print(s7, "傾きが少なすぎる", abs(y_change))
            ans = {"is_tilt_line_each": False,
                   "count": target_num,
                   "tilt_pm": 0,
                   "direction": d,
                   "direction_integrity": 0,
                   "on_line_ratio": 0,
                   "near_line_ratio": 0,
                   "lc_price": 0,
                   "latest_info": {},
                   "oldest_info": {},
                   'y_change': y_change,
                   "remark": "remark"
                   }
            tilt_result_list.append(ans)
            continue
        else:
            print(s7, "いい傾き", abs(y_change))

        # ■■計算を算出する
        # OLDESTの価格を原点として、直近Peaksへの直線の傾きを算出する　yの増加量(価格の差分)　/ xの増加量(時間の差分)
        x_change_sec = (gene.cal_at_least(0.001,
                                          gene.cal_str_time_gap(oldest_info['time'], target_peaks[0]['time'])['gap_abs']))  # ０にならない最低値を設定する
        tilt = y_change / x_change_sec

        # 集計用の変数を定義する
        total_peaks_num = target_num
        on_line_num = near_line_num = 0  # 線上にあるものもカウントし、よりフラッグ形状であることを示したい
        is_tilt_line_each = False
        # 各要素がその直線（0.05pipsの切片分だけ余裕をとる）より上にあるかを確認する
        for i, item in enumerate(target_peaks):
            # ■座標(a,b)を取得する
            a = gene.cal_str_time_gap(oldest_info['time'], item['time'])['gap_abs']  # 時間差分
            b = item["peak"] - oldest_info['peak']  # ここでは
            # print(s7, "(ri)a:", a, ",b:", b)

            # ■線上といえるか[判定]
            margin = 0.02
            jd_y_max = tilt * a + margin
            jd_y_min = tilt * a + (margin * -1)
            if jd_y_max > b > jd_y_min:
                # print(s7, "(ri)線上にあります", item['time'])
                on_line_num += 1
            else:
                # print(s7, "(ri)線上にはありません", item['time'])
                pass

            # ■線の近くにあるか[判定]
            margin = abs(target_peaks[0]['peak'] - min_or_max_info['peak']) * 0.405  # * 0.405がちょうどよさそう
            margin = gene.cal_at_least(0.05, margin)  # 下側の下落、上側の上昇の場合、最小最大が逆になると０になる可能性がある
            # print(target_peaks[0]['time'], target_peaks[0]['peak'], min_or_max_info['time'], min_or_max_info['peak'])
            # print("MARGIN:", abs(target_peaks[0]['peak'] - min_or_max_info['peak']), margin)
            jd_y_max = tilt * a + margin
            jd_y_min = tilt * a + (margin * -1)
            if jd_y_max > b > jd_y_min:
                # print(s7, "(ri)　線近くにあります", item['time'])
                near_line_num += 1
            else:
                # print(s7, "(ri)　線近くにはありません", item['time'])
                pass
        # 集計結果
        # print(s7, "(ri)全部で", total_peaks_num, 'ピーク。線上：', on_line_num, "線近", near_line_num)
        # print(s7, "(ri)割合　線上:", on_line_num/total_peaks_num, "　線近:", near_line_num/total_peaks_num)
        on_line_ratio = round(on_line_num/total_peaks_num, 3)
        near_line_ratio = round(near_line_num/total_peaks_num, 3)
        # 最終判定
        tilt_pm = tilt / abs(tilt)  # tiltの方向を算出する（上側が下傾斜、下側の上傾斜の情報のみが必要）
        print(s7, "調査側は", d, "(d=1は上g側) 傾き方向は", tilt_pm)
        if d == tilt_pm:
            print(s7, "下側が下方向、上側が上方向に行っている（今回は収束と見たいため、不向き）")
            remark = "発散方向"
            direction_integrity = False  # 方向の整合性
        else:
            # 傾斜は合格、ピークスを包括できるかを確認
            if on_line_ratio >= 0.4 and near_line_ratio >= 0.6:
            # if on_line_ratio >= 0.55 and near_line_ratio >= 0.7:  # 0.35, 60
            # if on_line_ratio >= 0.35 and near_line_ratio >= 0.6:  # 緩いほう（従来の結果がよかった条件）
                is_tilt_line_each = True
                # remark = "継続した傾斜と判断"
                if tilt < 0:
                    remark = "上側下落"
                else:
                    remark = "下側上昇"
                print(s7, "継続した傾斜と判断", d)
            else:
                remark = "線上、線近くのどちらかが未達"
                print(s7, "線上、線近くのどちらかが未達", on_line_ratio, near_line_ratio)

        # ■LC値の参考値を算出（対象のピーク群の中間値）
        total_peak = sum(item["peak"] for item in target_peaks)
        ave_peak_price = round(total_peak / len(target_peaks), 3)
        # lc_margin = 0.01 * latest_direction * -1
        # ave_peak_price = ave_peak_price + lc_margin

        # ■累積(numごと）
        ans = {"is_tilt_line_each": is_tilt_line_each,
               "count": target_num,
               "tilt_pm": tilt_pm,
               "direction": d,
               "direction_integrity": direction_integrity,
               "on_line_ratio": on_line_ratio,
               "near_line_ratio": near_line_ratio,
               "lc_price": ave_peak_price,
               "latest_info": target_peaks[0],
               "oldest_info": oldest_info,
               'y_change': y_change,
               "remark": remark
            }
        tilt_result_list.append(ans)
        # ループここまで
    print("tilt_result_list")
    gene.print_arr(tilt_result_list)

    # ■情報を整理する（例えば3peak～5peaksの各直線で、複数の傾斜直線がある場合、傾斜直線成立としt、代表としてOldestな物を返却する)
    all_ans_num = len(tilt_result_list)
    true_num = sum(item["is_tilt_line_each"] for item in tilt_result_list)  #
    print(s7, all_ans_num, true_num, true_num/all_ans_num)
    # if true_num / all_ans_num >= 0.5:  # 0.5だと、従来取れていたものも取りこぼす(良くも悪くも)
    if true_num / all_ans_num >= 0.1:
        print(s7, "斜面成立(", all_ans_num, "の内", true_num, "個の成立")
        is_tilt_line = True
    else:
        # 成立が認められない場合でも、Onlineが10割のものがあれば、採用する
        temp = next((item for item in tilt_result_list if item["on_line_ratio"] == 1), None)
        if temp and temp['direction_integrity']:
            # ある場合は、それの方向性の整合が取れているかを確認する
            is_tilt_line = True
            print(s7, "満点があった")
        else:
            print(s7, "満点ない")
            return return_base

    # ■成立している中で、一番比較ピークが多いもの、少ないものを抽出しておく
    first_item = next((item for item in tilt_result_list if item["is_tilt_line_each"]), None)  # 最もLatestなTiltTrue
    oldest_item = next((item for item in reversed(tilt_result_list) if item["is_tilt_line_each"]), None)  # 最もOldestなTiltTrue
    oldest_item = max(
        (item for item in reversed(tilt_result_list) if item['is_tilt_line_each']),  # fが真の要素をフィルタ
        key=lambda x: x['y_change'],                  # kが最大のものを取得
        default=None                           # 空の場合はNoneを返す(空欄はこの前段階で除去されるのでありえない）
    )
    # print(first_item)
    # print(oldest_item)

    # ■推奨のロスカット価格を集合から計算しておく
    # 最大でもLCRange換算で10pips以内したい
    now_price = peaks[0]['peak']
    temp_lc_price = oldest_item['lc_price']  # lcPriceは収束の中間点
    lc_range = temp_lc_price - now_price  # これがマイナス値の場合Directionは１、プラス値となる場合Directionは-1
    if abs(lc_range) >= 0.1:
        # LCが大きすぎると判断される場合(10pips以上離れている）
        lc_range = 0.1  # LCRnageを指定
        if lc_range < 0:
            # LC_rangeがマイナス値　＝　Directionは１。その為、現在価格からマイナスするとLCPriceとなる
            lc_price = now_price - abs(lc_range)
        else:
            # LC_rangeがプラス値　＝　Directionは-1。その為、現在書くにプラスするとＬＣＰｒｉｃｅになる
            lc_price = now_price + abs(lc_range)
    else:
        # LCRangeが許容範囲内の場合、そのまま利用
        lc_price = temp_lc_price
    print(s7, "LC(価格orRange）", lc_price)

    ans_info = {
        "is_tilt_line": is_tilt_line,
        "tilt_list": tilt_result_list,
        "oldest_peak_info": oldest_item,
        "latest_peak_info": first_item,
        "lc_price": lc_price,  # 計算で大きすぎた場合、10pipsが入る
        "remark": oldest_item['remark'],  # 一番古いのを採用
    }
    return ans_info


def analysis_cross(dic_args):
    """
    引数はDFやピークスなど
    """

    # 表示時のインデント
    s4 = "    "
    s6 = "      "
    print(s4, "■クロス解析関数")

    # ■関数事前準備■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■
    # ■■返却値
    orders_and_evidence = {
        "cross_figure_flag": False,
        "information": {}  #
    }
    # ■■情報の整理と取得（関数の頭には必須）
    fixed_information = cf.information_fix(dic_args)  # DFとPeaksが必ず返却される
    target_df = fixed_information['df_r']
    peaks = fixed_information['peaks']  # 通常のピークス
    peaks_hard_skip = peak_inspection.hard_skip_after_peaks_cal(peaks)  # スキップしたピークス

    # ■調査を実施する■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■
    # ■形状判定の初期値
    judge_flag = False
    # ■(1)形状の判定　（上側は持続的な下落、かつ、下側は持続的な上昇になっているかの判定）
    # ■■　river側はN個、turn側はN-1個の調査とする（riverが3個の場合、turnは2個分の調査でよい）
    figure_results_list = []
    temp_latest_cross = False
    for i in range(2):
        base = i + 1  # 基本的に１（Riverを示す）　⇒ひとつ前でも成り立つかを確認するときはbaseを２にする
        print("クロス調査ループ回数", i, "riverPeak", peaks[base]['time'], "turnPeak", peaks[base]['time'])
        if peaks[base]['direction'] == 1:
            # riverがUpperの場合、最低、upperは3個、Lowerは2個の調査 ⇒lower側に調整Trueを入れる
            upper_tilt_line_info = judge_flag_figure(peaks[base:], peaks[base]['direction'], False)  # latestは無視
            print("↑●リバーピーク", peaks[base]['direction'], "結果", upper_tilt_line_info['is_tilt_line'])
            lower_tilt_line_info = judge_flag_figure(peaks[base:], peaks[base+1]['direction'], True)  # latestは無視
            print("↑●ターンピーク", peaks[base+1]["direction"], "結果", lower_tilt_line_info['is_tilt_line'])
        else:
            # riverがlowerの場合、最低、lowerは3個、upperは2個の調査 ⇒upper側に調整Trueを入れる
            upper_tilt_line_info = judge_flag_figure(peaks[base:], peaks[base]['direction'], True)  # latestは無視
            print("↑●リバーピークから", peaks[base]['direction'], "結果", upper_tilt_line_info['is_tilt_line'])
            lower_tilt_line_info = judge_flag_figure(peaks[base:], peaks[base+1]['direction'], False)  # latestは無視
            print("↑●ターンピークから", peaks[base+1]["direction"], "結果", lower_tilt_line_info['is_tilt_line'])
        if upper_tilt_line_info['is_tilt_line'] and lower_tilt_line_info['is_tilt_line']:
            print(s6, "▲形状的には成立っぽい")
            # figure_flag = True
            figure_results_list.append(True)
            if i == 1:
                # 初回(latestの時）のみ
                temp_latest_cross = True
        else:
            print(s6, "▲形状不成立", upper_tilt_line_info['is_tilt_line'], lower_tilt_line_info['is_tilt_line'])
            # return orders_and_evidence
            figure_results_list.append(False)
            pass
    # 過去分含めて、成立と言えるか
    if not(temp_latest_cross):
        # 初回すら見つからない場合は、この時点で返却
        return orders_and_evidence
    # 最低でも初回が見つかっている状態
    if figure_results_list[0] and figure_results_list[1]:
        # figure_results_list[0]は直近のもの。[1]は直近よりひとつ前のPeaksでやったもの。二つともOKの場合は重複になりすぎる
        figure_flag = False
        figure_remark = "不成立・繰り返し成立(1peak前)"
        print("  ", figure_remark)
    elif figure_results_list[0] and not(figure_results_list[1]):
        # 直近のみが成立（これが◎◎）
        figure_flag = True
        figure_remark = "初回成立"
        print("  ", figure_remark)
    else:
        figure_flag = False
        figure_remark = "不成立・直前不成立"
        print("  ", figure_remark)

    # ■(2)形状の判定（Oldestに対し、Latestの部分が、すぼまっている事）⇒収束度合いを確認したい
    squeeze_flag = False
    # print("型の確認", type(upper_tilt_line_info['oldest_peak_info']))
    upper_oldest_peak_info = upper_tilt_line_info['oldest_peak_info']['oldest_info']
    lower_oldest_peak_info = lower_tilt_line_info['oldest_peak_info']['oldest_info']
    print(s6, "Oldestピークのインデックス", upper_oldest_peak_info['time'], lower_oldest_peak_info['time'])
    oldest_gap = round(upper_oldest_peak_info['peak'] - lower_oldest_peak_info['peak'], 3)  # これが最大になっている必要がある。
    latest_gap = peaks[1]["gap"]
    print(s6, "oldest_info", oldest_gap, upper_oldest_peak_info['time'], lower_oldest_peak_info['time'])
    print(s6, "latest_info", latest_gap, peaks[1]['peak'], peaks[1]['peak_old'])
    # すぼみ判定１
    if latest_gap / oldest_gap <= 0.35:
        print(s6, "すぼみ形状確認（広さが半減） 参考比率", round(latest_gap / oldest_gap, 3), "が0.35以下")
        squeeze_flag = True
    else:
        print(s6, " すぼみではない", round(oldest_gap / latest_gap, 3), "が0.35以下ではない")
        pass
    # すぼみ判定２（最後の上下差が、10pips以内になっていること）
    river_gap = peaks[1]['gap']
    turn_gap = peaks[2]['gap']
    if river_gap <= 0.1 or turn_gap <= 0.1:
        squeeze_flag = True
        print(s6, "スクイーズ幅成立", river_gap, turn_gap, "基準は左の2つのいずれかが0.1以下")
    else:
        squeeze_flag = False
        print(s6, "スクイーズ幅不成立", river_gap, turn_gap, "基準は左の2ついずれかが0.1以下")
    # ■判定
    if figure_flag and squeeze_flag:
        cross_figure_flag = True
    else:
        cross_figure_flag = False

    return {
        "cross_figure_flag": cross_figure_flag,
        "oldest_gap": oldest_gap,
        "upper_oldest_peak_price": upper_oldest_peak_info['peak'],
        "lower_oldest_peak_price": lower_oldest_peak_info['peak'],
    }


def main_cross(dic_args):
    """
    引数はDFやピークスなど
    """

    # 表示時のインデント
    s4 = "    "
    s6 = "      "

    # ■関数事前準備■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■
    # ■■返却値 とその周辺の値
    exe_orders = []
    orders_and_evidence = {
        "take_position_flag": False,
        "exe_orders": exe_orders,
        "information": []
    }
    # ■■情報の整理と取得（関数の頭には必須）
    fixed_information = cf.information_fix(dic_args)  # DFとPeaksが必ず返却される
    df_r = fixed_information['df_r']
    peaks = fixed_information['peaks']

    # ■調査を実施する■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■
    # ■実行しない場合、強制的に終了させる
    #  実行タイミング⇒LatestCountが２の場合のみ（フラッグ形状とは異なる）
    if peaks[0]['count'] != 2:
        print(" 実行しないLatest条件")
        return orders_and_evidence
    #  ループの際、数が少ないとエラーの原因になる。３個切る場合ば終了（最低３個必要）
    if len(peaks) < 4:
        print(" 実行しないPEAK少ない")
        return orders_and_evidence
    # ■調査を実施する
    cross_figure_flag = analysis_cross({"df_r": df_r, "peaks": peaks})  # 調査関数呼び出し
    if not cross_figure_flag['cross_figure_flag']:  # 終了
        return orders_and_evidence
    print(s4, "LineStrengthのオーダー確定")

    # ■TargetやLC等を検討する
    # ■■価格を設定する
    if peaks[1]['direction'] == 1:
        # riverがUpperの場合 (latestは下がっているほう）
        upper_target_price = peaks[3]['peak']  # latestが上向きのため、riverをターゲットにするとすぐに入り過ぎそうだからflopにする
        upper_lc_price = peaks[4]['peak']
        lower_target_price = peaks[2]['peak']
        lower_lc_price = peaks[3]['peak']
    else:
        # riverがLowerの場合
        upper_target_price = peaks[2]['peak']
        upper_lc_price = peaks[3]['peak']
        lower_target_price = peaks[3]['peak']
        lower_lc_price = peaks[4]['peak']
    # ■■Rangeを計算して、調整する
    # UPPER
    upper_lc_gap = abs(upper_target_price - upper_lc_price)
    min_range = 0.06
    max_range = 0.07
    if min_range < upper_lc_gap < max_range:
        # 範囲内のLCRangeの場合、何もしない
        pass
    else:
        upper_lc_price = upper_target_price - max_range
    # LOWER
    lower_lc_gap = abs(lower_target_price - lower_lc_price)
    if min_range < lower_lc_gap < max_range:
        # 範囲内のLCRangeの場合、何もしない
        pass
    else:
        lower_lc_price = lower_target_price + max_range

    # ■オーダーを生成する
    units_test_special = 10000
    # ■■上側のオーダー(upper)
    main_order_base = cf.order_base_cross(df_r.iloc[0]['close'], df_r.iloc[0]['time_jp'])  # tpはLCChange任せのため、Baseのまま
    direction = 1  # 上向きを期待するオーダー
    main_order_base['target'] = upper_target_price
    # main_order_base['lc'] = gene.cal_at_least(0.05, cross_figure_flag['oldest_gap'] / 3.6)  # 0.06  # * line_strength  # 0.09  # LCは広め
    main_order_base['lc'] = upper_lc_price
    main_order_base['type'] = "STOP"
    main_order_base['expected_direction'] = direction
    main_order_base['priority'] = 3
    main_order_base['units'] = units_test_special  # main_order_base['units'] * 1
    main_order_base['name'] = 'クロス形状上向き(count:' + str(peaks[0]['count']) + ')'
    exe_orders.append(cf.order_finalize(main_order_base))
    # ■■下側のオーダー(lower)
    main_order_base = cf.order_base_cross(df_r.iloc[0]['close'], df_r.iloc[0]['time_jp'])  # tpはLCChange任せのため、Baseのまま
    direction = -1  # 下向きを期待するオーダー
    main_order_base['target'] = lower_target_price
    # main_order_base['lc'] = gene.cal_at_least(0.05, cross_figure_flag['oldest_gap'] / 3.6)  # 0.06  # * line_strength  # 0.09  # LCは広め
    main_order_base['lc'] = lower_lc_price
    main_order_base['type'] = "STOP"
    main_order_base['expected_direction'] = direction
    main_order_base['priority'] = 3
    main_order_base['units'] = units_test_special  # main_order_base['units'] * 1
    main_order_base['name'] = 'クロス形状下向き(count:' + str(peaks[0]['count']) + ')'
    exe_orders.append(cf.order_finalize(main_order_base))

    # 返却する
    print(s4, "オーダー対象")
    orders_and_evidence["take_position_flag"] = True  # ここまで来ている＝注文あり
    orders_and_evidence["exe_orders"] = exe_orders
    orders_and_evidence["evidence"] = []

    print("オーダー表示")
    gene.print_arr(orders_and_evidence["exe_orders"])
    return orders_and_evidence
