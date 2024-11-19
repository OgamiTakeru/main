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


def judge_cross_figure_wrap_up(peaks, df_r):
    # ■形状の判定　（上側は持続的な下落、かつ、下側は持続的な上昇）
    # Latestの方向が-1の場合、River(1)から上側４個、下側３個
    # Latestの方向が１の場合、River(-1)から下側４個、上側３個
    figure_flag = False
    upper_num = 3  # 最初は４だったが、HardSkipPeaks機能を追加したので、３程度にする
    lower_num = 3  # 最初は４だったが、HardSkipPeaks機能を追加したので、３程度にする

    print(" Latestは無視(形成途中の可能性があるため")
    print(" まずはリバーピークから", peaks[1]['direction'])
    upper_info = judge_flag_figure(peaks[1:], peaks[1]['direction'], upper_num)  # latestは無視
    upper_oldest_peak_info = upper_info['oldest_peak_info']
    upper_latest_peak_info = upper_info['latest_peak_info']
    print(upper_info)

    print(" 次にターンピーク", peaks[2]["direction"])
    lower_info = judge_flag_figure(peaks[1:], peaks[2]['direction'], lower_num)  # latestは無視
    lower_oldest_peak_info = lower_info['oldest_peak_info']
    lower_latest_peak_info = lower_info['latest_peak_info']
    print(lower_info)

    if upper_info['flag_figure'] and lower_info['flag_figure']:
        print(" 形状的には成立っぽい")
        figure_flag = True
    else:
        print(" 形状不成立", upper_info['flag_figure'], lower_info['flag_figure'])
        pass

    # ■形状（すぼまり具合）
    subomi_flag = False
    print("Oldestピークのインデックス", upper_oldest_peak_info['time'], lower_oldest_peak_info['time'])
    oldest_gap = round(upper_oldest_peak_info['peak'] - lower_oldest_peak_info['peak'], 3)  # これが最大になっている必要がある。
    latest_gap = peaks[1]["gap"]
    print("oldest_info", oldest_gap, upper_oldest_peak_info['time'], lower_oldest_peak_info['time'])
    print("latest_info", latest_gap, peaks[1]['peak'], peaks[1]['peak_old'])
    # すぼみ判定１
    if latest_gap/oldest_gap <= 0.4:
        print("すぼみ形状確認（広さが半減）")
        subomi_flag = True
    else:
        print(" すぼみではない", round(oldest_gap/latest_gap, 3))
        pass
    # すぼみ判定２（上の最大値から直近の上側まで、下の最小値から直近の下側まで、それぞれ5ピップ以上の下降が認められるかどうか）
    if abs(upper_oldest_peak_info["peak"] - upper_latest_peak_info["peak"]) >= 0.05:
        print(" 上側は角度的にもOKな下降", abs(upper_oldest_peak_info["peak"] - upper_latest_peak_info["peak"]))
    else:
        print(" 上側はやや水平気味", abs(upper_oldest_peak_info["peak"] - upper_latest_peak_info["peak"]))

    if abs(lower_oldest_peak_info["peak"] - lower_latest_peak_info["peak"]) >= 0.05:
        print(" 下側は角度的にもOKな下降", abs(lower_oldest_peak_info["peak"] - lower_latest_peak_info["peak"]))
    else:
        print(" 下側はやや水平気味", abs(lower_oldest_peak_info["peak"] - lower_latest_peak_info["peak"]))

    # ■判定
    if figure_flag and subomi_flag:
        ans_flag = True
    else:
        ans_flag = False

    return {
        "flag": ans_flag,
        "oldest_gap": oldest_gap
    }


def judge_flag_figure(peaks, target_direction, num):
    """
    旗の形状を探索するための、サポート関数
    peaks: ピークス
    num: ピークスの中で、直近num個分の中でフラッグ形状を判定する
    remark: コメント
    返り値は、成立しているかどうかのBoolean
    """
    flag_figure = False  # これは返り値
    remark = "フラッグ不成立"
    s7 = "      "
    return_result = {
        "flag_figure": False,  # フラッグ形状かどうかの判定（Boo）
        "lc": 0,  # LC価格の提案を行う
        "remark": remark
    }

    print(s7, "□　Flag確認関数")
    # サイズ関東、全体的な話

    # 形状の詳細
    if target_direction == 1:
        # ■■■直近の同価格ピークがLower側だった場合の、反対のUpperPeaksを求める　（一つ（すべて向きは同じはず）の方向を確認、）
        target_peaks = [item for item in peaks if item["direction"] == 1]  # 利用するのは、Upper側
        target_peaks = target_peaks[:num]  # 直近5個くらいでないと、昔すぎるのを参照してしまう（線より下の個数が増え、判定が厳しくなる）
        print(s7, "対象の上側のピークス")
        gene.print_arr(target_peaks, 7)

        # 直近の一番下の値と何番目のピークだったかを求める
        max_index, max_info = max(enumerate(target_peaks), key=lambda x: x[1]["peak"])
        oldest_peak_index = max_index  # ピーク値のインデックス
        print("    (ri)最大値とそのインデックス", max_info['peak'], max_index)
        # そのMinを原点として、直近Peakまでの直線の傾きを算出する(座標で言うx軸は秒単位）
        # yの増加量(価格の差分)　/ xの増加量(時間の差分)
        x_change_sec = gene.cal_at_least(1, gene.cal_str_time_gap(max_info['time'], target_peaks[0]['time'])['gap_abs'])
        tilt = (target_peaks[0]['peak'] - max_info['peak']) / x_change_sec  # こちらはマイナスが期待される（下りのため）
        if tilt >= 0:
            # print(s7, "(ri)tiltがプラス値。広がっていく価格でこちらは想定外")
            pass
        else:
            # print(s7, "(ri)tiltがマイナス値。Upperが上から降りてくる、フラッグ形状")
            pass
        # 集計用の変数を定義する
        if max_index > 1:
            total_peaks_num = max_index
        else:
            total_peaks_num = 1  # devision 0エラーを防止
        clear_peaks_num = failed_peaks_num = 0  # 上側にある（＝合格）と下側にある（＝不合格）の個数
        on_line = 0  # 線上にあるものもカウントし、よりフラッグ形状であることを示したい
        # 各要素がその直線（0.05pipsの切片分だけ余裕をとる）より上にあるかを確認する
        for i, item in enumerate(target_peaks):
            # iがmin_indexを超える場合は終了する
            if i >= max_index:
                # print(s7, "(ri)検証終了？breakします", i, max_index)
                break
            # thisの座標(a,b)を取得する
            a = gene.cal_str_time_gap(max_info['time'], item['time'])['gap_abs']  # 時間差分
            b = item["peak"] - max_info['peak']  # ここではマイナス値がデフォルト（変化後ー変化前）
            # print(s7, "(ri)a:", a, ",b:", b)
            # 判定する
            c = 0.02  # プラス値のほうが余裕が出る（ある程度した上に突き抜けていたとしてもセーフ）
            jd_y = tilt * a + c  # Cは切片。0.02程度だけ下回ってもいいようにする
            # ■最低限の位置関係を保っているか（線より上にいる場合は超えている、下にいる場合が正常）
            if b < jd_y:
                clear_peaks_num += 1
                # print(s7, "(ri)下にあるため合格", item)
            else:
                failed_peaks_num += 1
                # print(s7, "(ri)上にあるため除外（不合格）", item)
            # ■線上といえるか
            margin = abs(target_peaks[0]['peak'] - target_peaks[-1]['peak']) * 0.3  # 0.3がちょうどよさそう
            # print("計算結果", abs(target_peaks[0]['peak'] - target_peaks[-1]['peak']), margin)
            # margin = 0.07
            jd_y_max = tilt * a + margin
            jd_y_min = tilt * a + (margin * -1)
            if jd_y_max > b > jd_y_min:
                print(s7, "(ri)線上にあります", item['time'])
                on_line += 1
            else:
                print(s7, "(ri)線上にはありません", item['time'])
                pass
        # 集計結果
        print(s7, "(ri)全部で", total_peaks_num, 'このピークがあり、合格（上にあった）のは', clear_peaks_num,
              "不合格は", failed_peaks_num)
        print(s7, "(ri)割合", clear_peaks_num / total_peaks_num * 100)
        print(s7, "(ri)線上割合", on_line, on_line / total_peaks_num * 100)
        if clear_peaks_num / total_peaks_num * 100 >= 100:  # 全てLINEの下側（突破ありは弱くなる）
            if on_line / total_peaks_num * 100 >= 65:  # 最低でも３個中２個が線上（N数はMaxIndexの場所によって変わるが、最低でも６６パーセント）
                print(s7, "(ri)upperの継続した下落とみられる")
                flag_figure = True
                remark = "フラッグ形状(上側下落)"
                # tk.line_send(s7, "(ri)フラッグ型（lower水平upper下落）の検出", num)
            else:
                print(s7, "(ri)upperの継続した下落だが、突発的な高さがあった可能性あり 3個以上のピークで強力なLINE　　ストレングス変更なし")
                # tk.line_send(s7, "(ri)フラッグ型なり損ね、lowerはサポート", num)
                pass
        else:
            print(s7, "(ri)upperに傾向性のある下降なし。レンジとみなせる。　ストレングス変更なし", num)
            pass

    else:
        # ■■■直近の同価格ピークがUpper側だった場合の、反対のLowerのPeaksを求める　（一つ（すべて向きは同じはず）の方向を確認、）
        target_peaks = [item for item in peaks if item["direction"] == -1]  # 利用するのは、Lower側
        target_peaks = target_peaks[:num]  # 直近5個くらいでないと、昔すぎるのを参照してしまう（線より下の個数が増え、判定が厳しくなる）
        print(s7, "対象の下側のピーク")
        gene.print_arr(target_peaks, 7)

        # 直近の一番下の値と何番目のピークだったかを求める
        min_index, min_info = min(enumerate(target_peaks), key=lambda x: x[1]["peak"])
        oldest_peak_index = min_index  # ピーク値のインデックス
        print("    (ri)最小値とそのインデックス", min_info['peak'], min_index)
        # そのMinを原点として、直近Peakまでの直線の傾きを算出する(座標で言うx軸は秒単位）
        # yの増加量(価格の差分)　/ xの増加量(時間の差分)
        x_change_sec = (gene.cal_at_least(0.001,
                                          gene.cal_str_time_gap(min_info['time'], target_peaks[0]['time'])['gap_abs']))  # ０にならない最低値を設定する
        tilt = (target_peaks[0]['peak'] - min_info['peak']) / x_change_sec
        if tilt >= 0:
            # print(s7, "(ri)tiltがプラス値。想定されるLowerのせり上がり")
            pass
        else:
            # print(s7, "(ri)tiltがマイナス値。広がっていく価格で、こちらは想定外")
            pass
        # 集計用の変数を定義する
        if min_index > 1:
            total_peaks_num = min_index
        else:
            total_peaks_num = 1  # devision 0エラーを防止
        clear_peaks_num = failed_peaks_num = 0  # 上側にある（＝合格）と下側にある（＝不合格）の個数
        on_line = 0  # 線上にあるものもカウントし、よりフラッグ形状であることを示したい
        # 各要素がその直線（0.05pipsの切片分だけ余裕をとる）より上にあるかを確認する
        for i, item in enumerate(target_peaks):
            # iがmin_indexを超える場合は終了する
            if i >= min_index:
                # print(s7, "(ri)breakします", i, min_index)
                break
            # thisの座標(a,b)を取得する
            a = gene.cal_str_time_gap(min_info['time'], item['time'])['gap_abs']  # 時間差分
            b = item["peak"] - min_info['peak']  # ここでは
            # print(s7, "(ri)a:", a, ",b:", b)
            # 判定する
            # ■上にあるか
            c = -0.02  # ここはマイナス値にすることで余裕が出る
            jd_y = tilt * a + c  # Cは切片。0.02程度だけ下回ってもいいようにする
            if b > jd_y:
                clear_peaks_num += 1
                # print(s7, "(ri)上にあります（合格）", item)
            else:
                failed_peaks_num += 1
                # print(s7, "(ri)下にあるため除外", item)
            # ■線上といえるか(余裕度は変動する。直近Peakと最小PeakのGapの15％とする）
            margin = abs(target_peaks[0]['peak'] - target_peaks[-1]['peak']) * 0.3  # 0.3がちょうどよさそう
            # print("計算結果", abs(target_peaks[0]['peak'] - target_peaks[-1]['peak']), margin)
            # margin = 0.07
            jd_y_max = tilt * a + margin
            jd_y_min = tilt * a + (margin * -1)
            if jd_y_max > b > jd_y_min:
                print(s7, "(ri)線上にありますg", item['time'])
                on_line += 1
            else:
                print(s7, "(ri)線上にはありませんg", item['time'])
                pass
        # 集計結果
        print(s7, "(ri)全部で", total_peaks_num, '個のピークがあり、合格（上の方にあった）のは', clear_peaks_num,
              "不合格は", failed_peaks_num)
        print(s7, "(ri)割合", clear_peaks_num / total_peaks_num * 100)
        print(s7, "(ri)線上にあった数は", on_line, "割合的には", on_line / total_peaks_num * 100)
        if clear_peaks_num / total_peaks_num * 100 >= 100:  # 全て上側（突破がある場合は弱くなる）
            if on_line / total_peaks_num * 100 >= 65:  # さらに傾きの線上に多い場合⇒間違えなくフラッグといえる
                print(s7, "(ri)Lowerの継続した上昇とみられる")
                flag_figure = True
                remark = "フラッグ型（下側上昇）"
                # tk.line_send("    (ri)フラッグ型（upper水平lower上昇）の検出", num)
            else:
                print(s7, "(ri)Lowerの継続した上昇だが、突発的な深さがあった可能性あり　ストレングス変更なし")
                # tk.line_send("    (ri)フラッグ型なり損ね。シンプルにupper強めのレンジとみなす", num)
                pass
        else:
            pass
            print(s7, "(ri)Lowerに特に傾向性のある上昇なし。Upper強めのレンジとみなす　ストレングス変更なし", num)

    # gene.print_arr(target_peaks)
    # LC値の参考地のため、opposite_peaksについて調査する
    total_peak = sum(item["peak"] for item in target_peaks)
    count = len(target_peaks)
    ave_peak_price = round(total_peak / count, 3)
    lc_margin = 0.01 * target_direction * -1
    ave_peak_price = ave_peak_price + lc_margin
    print(s7, "OppositePeakAve", ave_peak_price)
    return {
        "flag_figure": flag_figure,  # フラッグ形状かどうかの判定（Boo）
        "lc": ave_peak_price,  # LC価格の提案を行う
        "oldest_peak_info": target_peaks[oldest_peak_index],
        "latest_peak_info": target_peaks[0],
        "remark": remark
    }


def cal_tpf_line_strength_all_predict_line(dic_args):
    """
    引数はDFやピークスなど
    """

    # 表示時のインデント
    s4 = "    "
    s6 = "      "
    print(s4, "■find_predict_line_based_latest関数")

    # ■関数事前準備
    # ■■よく使う型
    predict_line_info_list_base = {
            "line_base_info": {
                "line_base_time": 0,  # 予測では将来的に到達する場所のため、設定不可（とりあえず現在時刻？）
                "line_base_price": 0,  # 予測ではループで探すことになる（後で上書きする）、通常ではRiver価格
                "line_base_direction": 0,  # 予測ではLatest、通常はRiver。値が1の場合UpperLine（＝上値抵抗）
                "latest_direction": 0,  # 渡されたPeaksの直近の方向（＝直近の方向）
                "latest_time_in_df": 0,  # Latest。直近の時間（渡されたDFで判断）
                "decision_price": 0,
            },
            "same_price_list": [],
            "strength_info": {  # strength関数で取得（その後の上書きあり）
                "line_strength": 0,
                "priority": 0,  # 基本はLineStrengthの写し。ただしフラッグ形状の場合は２が上書きされる
                "line_position_strength": 0,
                "line_on_num": 0,
                "same_time_latest": 0,
                "all_range_strong_line": 0,
                "remark": "",
                "is_first_for_flag": False,  # フラッグ形状の場合にのみ含まれる
                "lc": 0,  # 途中でStrengthInfoに追加される。価格の場合と、レンジの場合が混在する
            }
        }
    # ■■返却値用
    #  リストの原型（これを上書きし、下のリストに追加していく）
    predict_line_info_list = []  # 実際に返却されるリスト
    #  返却値
    orders_and_evidence = {
        "take_position_flag": False,
        # "exe_orders": [],
        # "target_strength_info": {},  # オーダーにつながった、最強Line単品の情報
        "evidence": predict_line_info_list  # 全同一価格
    }
    # ■■情報の整理と取得（関数の頭には必須）
    fixed_information = cf.information_fix(dic_args)  # DFとPeaksが必ず返却される
    target_df = fixed_information['df_r']
    peaks = fixed_information['peaks']
    target_dir = peaks[0]['direction']  # Lineの方向 予測ではLatest。値が1の場合UpperLine（＝上値抵抗）
    grid = 0.01  # 調査の細かさ

    # ■調査を開始
    # 条件を達成していない場合は実行せず
    if len(peaks) < 4:
        # ■ループの際、数が少ないとエラーの原因になる。３個切る場合ば終了（最低３個必要）
        return orders_and_evidence

    # 専用のPeakを算出
    peaks = peak_inspection.hard_skip_after_peaks_cal(peaks)

    ans = judge_cross_figure_wrap_up(peaks, target_df)

    return {
        "cross_figure_flag": ans['flag'],
        "oldest_gap": ans['oldest_gap']
    }


def main_cross_move_analysis_and_order(dic_args):
    """
    引数はDFやピークスなど
    """

    # 表示時のインデント
    s4 = "    "
    s6 = "      "

    # ■関数事前準備
    # ■■返却値 とその周辺の値
    exe_orders = []
    orders_and_evidence = {
        "take_position_flag": False,
        "exe_orders": exe_orders,
        "evidence": []  # 将来的に、predict_line_info_list
    }
    # ■■情報の整理と取得（関数の頭には必須）
    fixed_information = cf.information_fix(dic_args)  # DFとPeaksが必ず返却される
    df_r = fixed_information['df_r']
    peaks = fixed_information['peaks']

    # ■実行タイミング⇒LatestCountが２の場合のみ（フラッグ形状とは異なる）
    if peaks[0]['count'] != 2:
        print(" 実行無し（LatestCount＝２以外）")
        return orders_and_evidence

    # ■調査を実施する
    cross_figure_flag = cal_tpf_line_strength_all_predict_line({"df_r": df_r, "peaks": peaks})  # 調査関数呼び出し
    if not cross_figure_flag['cross_figure_flag']:  # 終了
        return orders_and_evidence
    print(s4, "LineStrengthのオーダー確定")

    main_order_base = cf.order_base(peaks[0]['peak'], peaks[0]['time'])
    direction = 1  # 上向きを期待するオーダー
    main_order_base['target'] = peaks[0]['peak'] + peaks[0]['gap']  # + 0.05
    main_order_base['tp'] = 0.53  # 0.09  # LCは広め
    main_order_base['lc'] = cross_figure_flag['oldest_gap'] / 3.6  # 0.06  # * line_strength  # 0.09  # LCは広め
    main_order_base['type'] = "STOP"
    main_order_base['expected_direction'] = direction
    main_order_base['priority'] = 3
    main_order_base['units'] = main_order_base['units'] * 1
    main_order_base['name'] = 'クロス形状上向き' + str(main_order_base['priority']) + ')'
    exe_orders.append(cf.order_finalize(main_order_base))

    main_order_base = cf.order_base(peaks[0]['peak'], peaks[0]['time'])
    direction = -1  # 上向きを期待するオーダー
    main_order_base['target'] = peaks[0]['peak'] - peaks[0]['gap']
    main_order_base['tp'] = 0.53  # 0.09  # LCは広め
    main_order_base['lc'] = cross_figure_flag['oldest_gap'] / 3.6  # 0.06  # * line_strength  # 0.09  # LCは広め
    main_order_base['type'] = "STOP"
    main_order_base['expected_direction'] = direction
    main_order_base['priority'] = 3
    main_order_base['units'] = main_order_base['units'] * 1
    main_order_base['name'] = 'クロス形状下向き' + str(main_order_base['priority']) + ')'
    exe_orders.append(cf.order_finalize(main_order_base))

    # 返却する
    print(s4, "オーダー対象")
    orders_and_evidence["take_position_flag"] = True  # ここまで来ている＝注文あり
    orders_and_evidence["exe_orders"] = exe_orders
    orders_and_evidence["evidence"] = []

    print("オーダー表示")
    gene.print_arr(orders_and_evidence["exe_orders"])
    return orders_and_evidence
