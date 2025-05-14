import copy
import matplotlib.pyplot as plt
import numpy as np
import fPeakInspection as p  # とりあえずの関数集
import fGeneric as gene
import fDoublePeaks as dp
import tokens as tk
import classPosition as classPosition  # とりあえずの関数集

import fPeakInspection as peak_inspection
import fDoublePeaks as dp
import pandas as pd
import fMoveSizeInspection as ms
import fCommonFunction as cf
import fMoveSizeInspection as ms
import fPeakInspection as pi
import classPeaks as cpk
from datetime import datetime, timedelta
import classOrderCreate as OCreate
import classPosition
import bisect


def judge_flag_figure_new(peaks, same_price_list, direction):
    """
    フラッグ形状を算出する
    ・同一価格が発見された、時系列的にひとつ前の逆ピーク（ストレングス5以上）のものまで
    ・逆ピークまでの落差が、最終(最古）の同一価格の次の逆ピークまでの落差の2倍(1.5?)まで
    """
    print(" フラッグ形状算出用 関数")
    # 色々な初期値
    search_direction = direction
    target_peaks = []
    peaks = peaks[1:]  # [0]は自分自身のため、排除したほうがよい気がする。

    # 対象となるPeaks(傾きを求める側)を算出
    oldest_time_str = same_price_list[-1]['item']['latest_time_jp']
    oldest_time = datetime.strptime(oldest_time_str, "%Y/%m/%d %H:%M:%S")
    for i, item in enumerate(peaks):
        if datetime.strptime(item['latest_time_jp'], "%Y/%m/%d %H:%M:%S") > oldest_time:
            # 最古の同一価格よりも、新しい時間のピークの場合（無条件で追加されるもの）
            target_peaks.append(item)
        else:
            # 最古の価格を越えている場合
            target_peaks.append(item)
            if item['peak_strength'] >= 5 and item['direction'] == search_direction:
                # search_directionのpeak_strengthが5以上のものを発見した場合、終了
                break

    # print("フラッグ検証をする範囲")
    # gene.print_arr(target_peaks)

    print("フラッグ検証をする範囲の中で、傾きを求めたい側のPeaks")
    opposite_peaks = [item for item in target_peaks if item["direction"] == search_direction]
    gene.print_arr(opposite_peaks)

    # 近似線を算出する
    # 時間をdatetimeに変換
    times = [datetime.strptime(d['latest_time_jp'], '%Y/%m/%d %H:%M:%S') for d in opposite_peaks]
    # 時間を数値（秒）に変換（回帰のため）
    time_seconds = [(t - times[0]).total_seconds() for t in times]
    # peak値
    peaks = [d['peak'] for d in opposite_peaks]
    # 近似直線（1次関数）を計算
    coefficients = np.polyfit(time_seconds, peaks, 1)  # 1次関数
    poly = np.poly1d(coefficients)
    trend = poly(time_seconds)
    # 変動幅を抑える
    temp_peaks = [d['peak'] for d in opposite_peaks]
    max_peak = max(temp_peaks)
    min_peak = min(temp_peaks)
    allowed_gap = (max_peak - min_peak) * 0.4  # ★★元々0.2の時に勝率大# 変動幅の20パーセント（惺窩君は18.4くらい）
    print("変動幅の検討　最大", max_peak, min_peak, allowed_gap)
    # [検出１]近似線を下回るもの（上回るもの）データを算出
    below_trend_data = [
        opposite_peaks[i]
        for i in range(len(opposite_peaks))
        if peaks[i] < trend[i]
    ]
    #     結果表示
    print("近似線より下にあるデータ:")
    for d in below_trend_data:
        print(d)
    # [検出２]近似線に対し、下、かつ遠いと判断されるデータを抽出
    border_range = allowed_gap
    below_trend_within_5 = [
        opposite_peaks[i]
        for i in range(len(opposite_peaks))
        if 0 < (trend[i] - peaks[i]) <= border_range  # 下にある　かつ　N以上離れている
        # if 0 > (trend[i] - peaks[i]) >= border_range  # 上にある　かつ　N以上離れている
        # if (trend[i] - peaks[i]) <= border_range  # N以内
    ]
    # 結果表示
    print("近似線より下にあり、差が指定以上のデータ:")
    for d in below_trend_within_5:
        print(d)

    # [検出3]近似線に対し、遠いと判断されるデータを抽出
    border_range = allowed_gap
    within_5 = [
        opposite_peaks[i]
        for i in range(len(opposite_peaks))
        if abs(trend[i] - peaks[i]) <= border_range
    ]
    # 結果表示
    print("近似線との誤差が5以内のデータ::")
    for d in within_5:
        print(d)
    ratio_near = len(within_5) / len(opposite_peaks)
    print("近い物の割合", len(within_5) / len(opposite_peaks))

    # [検証４]傾きを求める
    times = [datetime.strptime(d['latest_time_jp'], '%Y/%m/%d %H:%M:%S') for d in opposite_peaks]
    time_minutes = [(t - times[0]).total_seconds() / 60 for t in times]
    peaks = [d['peak'] for d in opposite_peaks]
    # 一次近似
    coefficients = np.polyfit(time_minutes, peaks, 1)  # 単位：分
    slope = coefficients[0]
    intercept = coefficients[1]
    print(f"傾き（1分あたり）: {slope:.4f}")
    print(f"切片: {intercept:.4f}")

    # 判定
    is_flag = False
    if (search_direction == -1 and slope >= 0) or (search_direction == 1 and slope <= 0):
        if ratio_near >= 0.7 and len(opposite_peaks) >= 4:
            print("  ▲フラッグ認定 近い割合:", ratio_near, "反対個数", len(opposite_peaks))
            is_flag = True
        else:
            print("  ▲フラッグnot認定 (近似割合が0.7より下⇒", ratio_near, "反対個数が4個以上⇒", len(opposite_peaks))
    else:
        print(" 　　▲近似線の傾きが異なる 探索ピーク方向：", search_direction, slope)

    # 参考　差の一覧を表示
    # 差が5以内のデータで、プラスかマイナスの差を表示
    within_5_with_diff = [
        (opposite_peaks[i], trend[i] - peaks[i])  # 差を計算
        for i in range(len(opposite_peaks))
        if abs(trend[i] - peaks[i]) <= 5
    ]
    # 結果表示（差も表示）
    print("近似線との誤差が5以内のデータ（差も表示）:　目標の設定値", allowed_gap)
    for d, diff in within_5_with_diff:
        print(f"日時: {d['latest_time_jp']}, peak: {d['peak']}, 差: {diff:.2f}")

    # グラフ描画
    # plt.figure(figsize=(10, 5))
    # plt.plot(times, peaks, 'o-', label='peak values')
    # plt.plot(times, trend, 'r--', label='approx. line')
    # plt.xlabel('Time')
    # plt.ylabel('Peak')
    # plt.title('Peak Trend Over Time')
    # plt.legend()
    # plt.xticks(rotation=45)
    # plt.tight_layout()
    # plt.show()

    return {"is_flag": is_flag}


def cal_big_mountain(peaks_class):
    """
    args[0]は必ずpeaks_classであること。
    args[1]は、本番の場合、過去の決済履歴のマイナスの大きさでTPが変わるかを検討したいため、オーダークラスを受け取る

    直近のピーク（latest_peakはこれから伸びるPeakなので、直前のpeakは[1]の物を示す
    """
    # ■基本情報の取得
    take_position = False
    s = "    "

    peaks = peaks_class.peaks_original
    # peaks = peaks_class.skipped_peaks

    default_return_item = {
        "take_position_flag": take_position,
        "for_inspection_dic": {}
    }

    # ■実行除外
    if peaks[0]['count'] != 2:
        print("  Latestカウントにより除外", peaks[0]['count'])
        return default_return_item

    # ■■■実行
    # ■同一価格の調査を行う（BodyPeakと髭ピークの組み合わせ。ただしどちらかはBodyPeakとする）
    target_num = 1  # 以下のループで「自分以外」を定義するため、変数に入れておく(同一方向の配列に対して）
    target_peak = peaks[target_num]
    base_time = datetime.strptime(target_peak['time'], '%Y/%m/%d %H:%M:%S')
    print("ターゲットになるピーク:", target_peak)
    comment = ""  # 名前につくコメント

    # 変動が少ないところはスキップ
    if target_peak['gap'] <= 0.06:
        print("targetのGapが少なすぎる", target_peak['gap'])
        return default_return_item

    arrowed_range = peaks_class.recent_fluctuation_range * 0.05  # 最大変動幅の4パーセント程度
    same_price_range = 0.04
    same_price_list = []
    same_price_list_inner = []
    same_price_list_outer = []
    result_not_same_price_list = []
    opposite_peaks = []
    break_peaks = []
    break_peaks_inner = []
    break_peaks_outer=[]
    range_min=70
    print("同一価格とみなす幅:", arrowed_range)
    for i, item in enumerate(peaks):
        if abs(datetime.strptime(item['latest_time_jp'], '%Y/%m/%d %H:%M:%S') - base_time) <= timedelta(minutes=range_min):
            is_inner = True
        else:
            is_inner = False

        # print("     検証対象：", item['time'], item['peak_strength'])
        # ■判定０　今回のピークをカウントしない場合
        # 反対方向のピークの場合
        if item['direction'] != target_peak['direction']:
            # ターゲットのピークと逆方向のピークの場合
            opposite_peaks.append({"i": i, "item": item})
            continue
        # 弱いピークはカウントしない
        if item['peak_strength'] <= 4:
            continue  # ピークとみなさないため、何もせずスルー

        # ■判定１　同一価格か、Breakかの判定
        # 同方向でも、ターゲットをBreakしているもの
        if target_peak['direction'] == 1:
            if item['peak'] > target_peak['peak'] + arrowed_range:
                # ターゲットピークを越えている場合(UpperLineで、上側に突き抜け）、NG
                break_peaks.append({"i": i, "item": item})
                if is_inner:
                    break_peaks_inner.append({"i": i, "item": item})
                else:
                    break_peaks_outer.append({"i": i, "item": item})
        else:
            if item['peak'] < target_peak['peak'] - arrowed_range:
                # ターゲットピークを越えている場合（lowerLineで下に突き抜け）、NG
                break_peaks.append({"i": i, "item": item})
                if is_inner:
                    break_peaks_inner.append({"i": i, "item": item})
                else:
                    break_peaks_outer.append({"i": i, "item": item})

        # ■判定１　全ての近い価格を取得
        body_gap_abs = abs(target_peak['peak'] - item['peak'])
        if abs(item['latest_wick_peak_price'] - item['peak']) >= arrowed_range:
            # 髭が長すぎる場合は無効（無効は、上限をオーバーする値に設定してしまう
            body_wick_gap_abs = arrowed_range + 1  # 確実にarrowed_rangeより大きな値
        else:
            body_wick_gap_abs = abs(target_peak['peak'] - item['latest_wick_peak_price'])
        wick_body_gap_abs = abs(target_peak['latest_wick_peak_price'] - item['peak'])
        # if body_gap_abs <= arrowed_range or body_wick_gap_abs <= arrowed_range or wlen(result_same_price_list)ick_body_gap_abs <= arrowed_range:
        if body_gap_abs <= arrowed_range or body_wick_gap_abs <= arrowed_range:
            # 同一価格とみなせる場合
            same_price_list.append({"i": i, "item": item})
            if is_inner:
                same_price_list_inner.append({"i": i, "item": item})
            else:
                same_price_list_outer.append({"i": i, "item": item})
        else:
            result_not_same_price_list.append({"i": i, "item": item})

    print("同一価格一覧")
    gene.print_arr(same_price_list)
    print("70分以内の同一価格一覧")
    gene.print_arr(same_price_list_inner)
    if len(same_price_list) <= 1:  # 同一価格がない（自分自身のみを含む）場合は、ここで調査終了
        print('同一価格無しのため、処理終了', len(same_price_list))
        return default_return_item
    print("Break一覧")
    gene.print_arr(break_peaks)
    print("70分以内のBreak一覧")
    gene.print_arr(break_peaks_inner)
    print("70分より前のBreak一覧")
    gene.print_arr(break_peaks_outer)

    # ■■　抵抗線の強度分析
    # ■各種設定値
    mountain_foot_min = 60  # 山のすそ野の広さ（この値以上の山の裾野の広さを狙う）
    # 同一価格の範囲内の、サイズを求める。 規定分以上の場合は、山検証の対象
    sandwiched_peaks = peaks[same_price_list[0]['i']: same_price_list[-1]['i'] + 1]  # 間のピークス（両方の方向）
    sandwiched_peaks_oppo_peak = [d for d in sandwiched_peaks if d["direction"] == target_peak['direction'] * -1]
    # 期間内の最大値のピーク情報を求める。（逆サイドの方向が1の場合。-1の場合は最小値）は？
    if target_peak['direction'] * -1 == 1:
        far_item = max(sandwiched_peaks_oppo_peak, key=lambda x: x["peak"])
    else:
        far_item = min(sandwiched_peaks_oppo_peak, key=lambda x: x["peak"])
    t_gap = abs(far_item['peak'] - target_peak['peak'])
    print(s, "＜山(谷)探し＞")
    print(s, "  山の高さと山の位置:", t_gap, far_item['time'], target_peak['time'])
    print(s, "  直近の最大変動幅", peaks_class.recent_fluctuation_range, peaks_class.recent_fluctuation_range * 0.38)

    # ■Breakの有無（全体的にない場合「強」、部分的にある場合「直近同一ピークまではない」または「直近同一ピークまでもある」
    break_judge = False
    if len(break_peaks) != 0:
        # Breakが発生している場合（ほとんどのケースだと思われる）
        latest_break_gap_min = gene.cal_str_time_gap(target_peak['time'], break_peaks[0]['item']['time'])['gap_abs_min']
        if latest_break_gap_min >= mountain_foot_min:
            # 直近のブレイクポイントが山の裾野より以前にある場合（従来の想定のパターンで、山間にBreak無しで、山のすそ野は大体70分程度）
            print("Break有だが、山の裾野の範囲にBreakはなし")
            comment = "裾野Break無し、前Break" + str(len(break_peaks)) + "個"
            break_judge = True
        else:
            # 直近のブレイクポイントが比較的近く、山間にBreakが存在する場合
            if len(break_peaks) == 1:
                # Breakポイントが一つだけの場合　　⇒　どの程度超えているかによって、変わるかも・・？
                print("裾野内のBreakが一つだけなので、とりあえず実行する", len(break_peaks))
                break_judge = True
                comment = "裾野Break1個、前Break" + str(len(break_peaks)) + "個"
            else:
                # breakポイントが2個以上の場合
                second_break_gap_min = gene.cal_str_time_gap(target_peak['time'], break_peaks[1]['item']['time'])[
                    'gap_abs_min']
                if second_break_gap_min <= mountain_foot_min:
                    # 直近から二個目に近いBreakも、山の裾野の内部にある場合
                    print("裾野内にBreakが多いため、除外", len(break_peaks))
                    return default_return_item
                else:
                    comment = "裾野Break2個以上、それ含めたBreak数" + str(len(break_peaks)) + "個"
                    print("ようわからん")
    else:
        # Breakが発生していない場合（かなりレアケースだが、相当強い抵抗線の可能性がある）
        print("Breakポイントがない強めの抵抗線")
        comment = "Break完全無し"
        break_judge = True
    # Breakまとめ
    if break_judge:
        pass
    else:
        print("Breakの条件が合わないため検証終了")
        return default_return_item

    # ■同一価格が作る抵抗線の強度の検証
    latest_peak = same_price_list[1]  # [0]はTarget自身。[1]が自身を除く、Latestとなる
    oldest_peak = same_price_list[-1]
    is_flag = False
    gap_latest_same_price_min = gene.cal_str_time_gap(target_peak['time'], latest_peak['item']['time'])['gap_abs_min']
    gap_oldest_same_price_min = gene.cal_str_time_gap(target_peak['time'], oldest_peak['item']['time'])['gap_abs_min']
    print("target確認", target_peak['time'], "直近", latest_peak['item']['time'], "差", gap_latest_same_price_min)
    print("直近の折り返しピーク", peaks_class.peaks_original[1]['direction'])
    if gap_latest_same_price_min >= mountain_foot_min:
        # 【基本パターン】直近の同一価格が、山の裾野(約70分)を満たす場合
        print("基本的なパターン　直近の同一価格が、山の裾野を満たす")
        if t_gap >= peaks_class.recent_fluctuation_range * 0.3:  # 下げれば下げるほど、山が低くてもOKになる(基準0.38)
            # 最大の7割以上ある山が形成されている場合
            print("強い抵抗線と推定", t_gap / peaks_class.recent_fluctuation_range)
            take_position = True
            # flag_judge = judge_flag_figure(filtered_peaks, peaks_class.peaks_original[1]['direction'], 8)
            flag_judge = judge_flag_figure_new(peaks_class.peaks_original,
                                               same_price_list,
                                               peaks_class.peaks_original[1]['direction'] * -1)
            is_flag = flag_judge['is_flag']
        else:
            print("山が低すぎるため、強い抵抗線と判定せず")
        comment = comment + "_基本パターン" + "_高さ率@" + str(
            round(t_gap / peaks_class.recent_fluctuation_range, 1))

    else:
        # 山の裾野以内にも同一価格が存在(細かく抵抗線に当たっている)場合 ⇒　個数やフラッグ形状を判断する
        # 反対側の傾きでBreakか突破（旗形状）か判断する
        print("直近短期間に同一価格にアタックされている場合　⇒　旗形状の場合はBreak？ ⇒分前", gap_latest_same_price_min)
        comment = comment + "_基本に似たパターン"
        if len(same_price_list) >= 3:
            # 頻度多い（3回以上当たっている）場合、旗形状を警戒する
            # flag_judge = judge_flag_figure(filtered_peaks, peaks_class.peaks_original[1]['direction'], 8)
            flag_judge = judge_flag_figure_new(peaks_class.peaks_original,
                                               same_price_list,
                                               peaks_class.peaks_original[1]['direction'] * -1)
            is_flag = flag_judge['is_flag']
            print("直近近いが、頻度高いため、抵抗線とみなす")
            take_position = True
            comment = comment + "_フラッグ以外の短期複数アタック"
        else:
            print("直近近く、単発的なものなので、抵抗線とみなさない", len(same_price_list))

    # 検証の結果、以下の条件では実行しない方がよさそう ←結果的によかったが、取引回数を増やすための検証のため、いったん除外
    if len(same_price_list) <= 3:
        print("★★★とりあえずオリジナル,Breakともに抵抗線の構成ピークが3個以下の場合、勝率が低いためNG")
        return default_return_item

    # ■■オーダーの設定
    # 初期値の設定
    exe_orders = []  # 返却用
    # ★★履歴によるオーダー調整を実施する（TPを拡大する）★★★
    # for_history_class = classPosition.order_information("test", "test", False)  # 履歴参照用
    # tuned_data = for_history_class.tuning_by_history()  # TuneされたTPやLCChangeを取得する
    # tp_range = tuned_data['tuned_tp_range']
    # lc_change_type = tuned_data['tuned_lc_change_type']
    # print("TP設定", tp_range, "lcChange設定", lc_change_type)
    # tp_up_border_minus = -0.045  # これ以上のマイナスの場合、取り返しに行く。
    # # 過去の履歴を確認する
    # if len(for_history_class.history_plus_minus) == 1:
    #     # 過去の履歴が一つだけの場合
    #     latest_plu = for_history_class.history_plus_minus[-1]
    #     print("  直近の勝敗pips", latest_plu, "詳細(直近1つ)", for_history_class.history_plus_minus[-1])
    # else:
    #     # 過去の履歴が二つ以上の場合、直近の二つの合計で判断する
    #     latest_plu = for_history_class.history_plus_minus[-1] + for_history_class.history_plus_minus[-2]  # 変数化(短縮用)
    #     print("  直近の勝敗pips", latest_plu, "詳細(直近)", for_history_class.history_plus_minus[-1], for_history_class.history_plus_minus[-2])
    # # 最大でも現実的な10pips程度のTPに収める
    # if abs(latest_plu) >= 0.01:
    #     latest_plu = 0.01
    # # 値を調整する
    # if latest_plu == 0:
    #     print("  初回(本番)かAnalysisでのTP調整執行⇒特に何もしない（TPの設定等は行う）")
    #     # 通常環境の場合
    #     tp_range = 0.5
    #     lc_change_type = 1
    # else:
    #     if latest_plu <= tp_up_border_minus:
    #         print("  ★マイナスが大きいため、取り返し調整（TPを短縮し、確実なプラスを狙いに行く）", latest_plu * 0.8)
    #         # tp_range = tp_up_border_minus  # とりあえずそこそこをTPにする場合
    #         tp_range = abs(latest_plu * 0.8)  # 負け分をそのままTPにする場合
    #         lc_change_type = 0  # LCchangeの設定なし
    #     else:
    #         # 直近がプラスの場合プラスの場合、普通。
    #         print("  ★マイナスが大きいため、取り返し調整（TPを短縮し、確実なプラスを狙いに行く）")
    #         tp_range = 0.5
    #         lc_change_type = 1  # LCchangeの設定なし

    # オーダーの作成
    if take_position:
        # オーダーありの場合
        if is_flag:
            # flag形状の場合（＝Breakの場合）
            exe_orders.append(break_order(peaks, peaks_class, comment, same_price_list))
            # base_order_dic = {
            #     "target": peaks[1]['latest_wick_peak_price'] + (0.006 * peaks[1]['direction']),
            #     "type": "STOP",
            #     "expected_direction": peaks[1]['direction'],
            #     "tp": tp_range,  # 短期では0.15でもOK.ただ長期だと、マイナスの平均が0.114のためマイナスの数が多くなる
            #     "lc": 0.09,  # 0.06,
            #     'priority': 3,
            #     "decision_time": peaks_class.df_r_original.iloc[0]['time_jp'],
            #     "decision_price": peaks_class.df_r_original.iloc[1]['close'],
            #     "order_timeout_min": 20,
            #     "lc_change_type": lc_change_type,
            #     "name": "Breakオーダー_" + comment + "_(" + str(len(same_price_list)) + ")"
            # }
            # base_order_class = OCreate.OrderCreateClass(base_order_dic)  # オーダーファイナライズ
            # exe_orders.append(base_order_class.finalized_order)  # オーダー登録
        else:
            # (当初の基本）抵抗線をBreakしないと判断される場合

            peaks = peaks_class.peaks_original
            exe_orders.append(resistnce_order(peaks, peaks_class, comment, same_price_list))
            # # 最大LCの調整
            # target_price = peaks_class.latest_peak_price + (peaks[0]['direction'] * 0.024)
            # lc_price = OCreate.cal_lc_price_from_line_and_margin(peaks[1]['latest_wick_peak_price'], 0.03,
            #                                                      peaks[0]['direction'])
            # gap = abs(lc_price - target_price)
            # re_lc_range = gene.cal_at_most(0.09, gap)
            # print("Orderのgap確認", gap, "target_price:", target_price, "deci_price:",
            #       peaks_class.df_r_original.iloc[1]['close'])
            # base_order_dic = {
            #     "target": target_price,
            #     "type": "STOP",
            #     "expected_direction": peaks[0]['direction'],
            #     "tp": tp_range,  # 短期では0.15でもOK.ただ長期だと、マイナスの平均が0.114のためマイナスの数が多くなる
            #     "lc": lc_price,  # 0.06,
            #     'priority': 3,
            #     "decision_time": peaks_class.df_r_original.iloc[0]['time_jp'],
            #     "decision_price": peaks_class.df_r_original.iloc[1]['close'],
            #     "order_timeout_min": 20,
            #     "lc_change_type": lc_change_type,
            #     "name": "山_" + comment + "_(" + str(len(same_price_list)) + ")"
            # }
            # base_order_class = OCreate.OrderCreateClass(base_order_dic)  # オーダー生成
            # # gene.print_json(base_order_class.finalized_order_without_lc_change)  # 表示
            #
            # # オーダーの修正と、場合によって追加オーダー設定
            # lc_max = 0.15
            # lc_change_after = 0.075
            # if base_order_class.finalized_order['lc_range'] >= lc_max:
            #     # LCレンジを計算してLCが大きすぎた場合、オーダー修正（LC短縮）
            #     print("LCが大きいため再オーダー設定")
            #     base_order_dic['lc'] = lc_change_after
            #     base_order_dic['name'] = base_order_dic['name'] + "LC大で修正_"
            #     base_order_class = OCreate.OrderCreateClass(base_order_dic)  # オーダー生成（というか作り直し）
            #     # gene.print_json(base_order_class.finalized_order_without_lc_change)  # 表示
            #     exe_orders.append(base_order_class.finalized_order)
            #
            # else:
            #     print("LCRange基準内のため、そのまま設定（延長先のオーダーもなし")
            #     exe_orders.append(base_order_class.finalized_order)  # オーダー登録

    print("結果(LIVE)", take_position)

    return {
        "take_position_flag": take_position,
        "exe_orders": exe_orders,
        "for_inspection_dic": {}
    }


def break_order(peaks, peaks_class, comment, same_price_list):

    same_price_len=len(same_price_list)
    if same_price_len<=3:
        same_price_len=3
    else:
        same_price_len=4

    # ★★履歴によるオーダー調整を実施する（TPを拡大する）★★★
    for_history_class = classPosition.order_information("test", "test", False)  # 履歴参照用
    tuned_data = for_history_class.tuning_by_history_break()  # TuneされたTPやLCChangeを取得する
    tp_range = tuned_data['tuned_tp_range']
    lc_change_type = tuned_data['tuned_lc_change_type']
    print("TP設定", tp_range, "lcChange設定", lc_change_type)

    # flag形状の場合（＝Breakの場合）
    base_order_dic = {
        "target": peaks[1]['latest_wick_peak_price'] + (0.006 * peaks[1]['direction']),
        "type": "STOP",
        "expected_direction": peaks[1]['direction'],
        "tp": tp_range,  # 短期では0.15でもOK.ただ長期だと、マイナスの平均が0.114のためマイナスの数が多くなる
        "lc": 0.09,  # 0.06,
        # "tp": 0.075,
        # "lc": 0.075,
        'priority': 3,
        "decision_time": peaks_class.df_r_original.iloc[0]['time_jp'],
        "decision_price": peaks_class.df_r_original.iloc[1]['close'],
        "order_timeout_min": 20,
        "lc_change_type": lc_change_type,
        "name": comment + "@" + str(same_price_len)
    }
    base_order_class = OCreate.OrderCreateClass(base_order_dic)  # オーダーファイナライズ
    return base_order_class.finalized_order


def resistnce_order(peaks, peaks_class, comment, same_price_list):

    same_price_len=len(same_price_list)
    if same_price_len<=3:
        same_price_len=3
    else:
        same_price_len=4

    # ★★履歴によるオーダー調整を実施する（TPを拡大する）★★★
    for_history_class = classPosition.order_information("test", "test", False)  # 履歴参照用
    tuned_data = for_history_class.tuning_by_history_break()  # TuneされたTPやLC.finalized_orderChangeを取得する
    tp_range = tuned_data['tuned_tp_range']
    lc_change_type = tuned_data['tuned_lc_change_type']  #0 i no
    print("TP設定", tp_range, "lcChange設定", lc_change_type)


    target_price = peaks_class.latest_peak_price + (peaks[0]['direction'] * 0.024)
    lc_price = OCreate.cal_lc_price_from_line_and_margin(peaks[1]['latest_wick_peak_price'], 0.03,
                                                         peaks[0]['direction'])
    gap = abs(lc_price - target_price)
    re_lc_range = gene.cal_at_most(0.09, gap)
    print("Orderのgap確認", gap, "target_price:", target_price, "deci_price:",
          peaks_class.df_r_original.iloc[1]['close'])
    base_order_dic = {
        "target": target_price,
        "type": "STOP",
        "expected_direction": peaks[0]['direction'],
        "tp": tp_range,  # 短期では0.15でもOK.ただ長期だと、マイナスの平均が0.114のためマイナスの数が多くなる
        "lc": lc_price,  # 0.06,
        # "tp": 0.075,
        # "lc": 0.075,
        'priority': 3,
        "decision_time": peaks_class.df_r_original.iloc[0]['time_jp'],
        "decision_price": peaks_class.df_r_original.iloc[1]['close'],
        "order_timeout_min": 20,
        "lc_change_type": lc_change_type,
        "name": comment + "@" + str(same_price_len)
    }
    base_order_class = OCreate.OrderCreateClass(base_order_dic)  # オーダー生成
    # gene.print_json(base_order_class.finalized_order_without_lc_change)  # 表示

    # オーダーの修正と、場合によって追加オーダー設定
    lc_max = 0.15
    lc_change_after = 0.075
    if base_order_class.finalized_order['lc_range'] >= lc_max:
        # LCレンジを計算してLCが大きすぎた場合、オーダー修正（LC短縮）
        print("LCが大きいため再オーダー設定")
        base_order_dic['lc'] = lc_change_after
        base_order_dic['name'] = base_order_dic['name'] + "_LC大で修正_"
        base_order_class = OCreate.OrderCreateClass(base_order_dic)  # オーダー生成（というか作り直し）
    else:
        base_order_class = OCreate.OrderCreateClass(base_order_dic)

    return base_order_class.finalized_order