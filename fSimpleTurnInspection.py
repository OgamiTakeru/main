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
from datetime import datetime
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
    allowed_gap = (max_peak - min_peak) * 0.2  # 変動幅の20パーセント（惺窩君は18.4くらい）
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
    ratio_near = len(within_5)/len(opposite_peaks)
    print("近い物の割合", len(within_5)/len(opposite_peaks))

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
    if (search_direction == -1 and slope >=0 ) or (search_direction == 1 and slope <= 0):
        if ratio_near >= 0.7 and len(opposite_peaks) >= 4:
            print("  ▲フラッグ認定 近い割合:", ratio_near, "反対個数", len(opposite_peaks))
            is_flag = True
        else:
            print("  ▲フラッグnot認定", ratio_near, "反対個数", len(opposite_peaks))
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
    print("ターゲットになるピーク:", target_peak)
    comment = ""  # 名前につくコメント

    # 変動が少ないところはスキップ
    if target_peak['gap'] <= 0.06:
        print("targetのGapが少なすぎる", target_peak['gap'])
        return default_return_item

    arrowed_range = peaks_class.recent_fluctuation_range * 0.05  # 最大変動幅の4パーセント程度
    same_price_range = 0.04
    same_price_list = []
    result_not_same_price_list = []
    opposite_peaks = []
    break_peaks = []
    print("同一価格とみなす幅:", arrowed_range)
    for i, item in enumerate(peaks):
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
        else:
            if item['peak'] < target_peak['peak'] - arrowed_range:
                # ターゲットピークを越えている場合（lowerLineで下に突き抜け）、NG
                break_peaks.append({"i": i, "item": item})

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
        else:
            result_not_same_price_list.append({"i": i, "item": item})

    print("同一価格一覧")
    gene.print_arr(same_price_list)
    if len(same_price_list) <= 1:  # 同一価格がない（自分自身のみを含む）場合は、ここで調査終了
        print('同一価格無しのため、処理終了', len(same_price_list))
        return default_return_item


    print("Breakしているもの一覧")
    gene.print_arr(break_peaks)

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
            comment = "前Break裾野Break無し"
            break_judge = True
        else:
            # 直近のブレイクポイントが比較的近く、山間にBreakが存在する場合
            if len(break_peaks) == 1:
                # Breakポイントが一つだけの場合　　⇒　どの程度超えているかによって、変わるかも・・？
                print("裾野内のBreakが一つだけなので、とりあえず実行する", len(break_peaks))
                break_judge = True
                comment = "前Break裾野Break1個"
            else:
                # breakポイントが2個以上の場合
                second_break_gap_min = gene.cal_str_time_gap(target_peak['time'], break_peaks[1]['item']['time'])['gap_abs_min']
                if second_break_gap_min <= mountain_foot_min:
                    # 直近から二個目に近いBreakも、山の裾野の内部にある場合
                    print("裾野内にBreakが多いため、除外", len(break_peaks))
                    return default_return_item
                else:
                    comment = "前Break裾野Break2個以上？"
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
        comment = comment + "基本パターン"
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

    else:
        # 山の裾野以内にも同一価格が存在(細かく抵抗線に当たっている)場合 ⇒　個数やフラッグ形状を判断する
        # 反対側の傾きでBreakか突破（旗形状）か判断する
        print("直近短期間に同一価格にアタックされている場合　⇒　旗形状の場合はBreak？ ⇒分前", gap_latest_same_price_min)
        comment = comment + "基本に似たパターン"
        if len(same_price_list) >= 3:
            # 頻度多い（3回以上当たっている）場合、旗形状を警戒する
            # flag_judge = judge_flag_figure(filtered_peaks, peaks_class.peaks_original[1]['direction'], 8)
            flag_judge = judge_flag_figure_new(peaks_class.peaks_original,
                                               same_price_list,
                                               peaks_class.peaks_original[1]['direction'] * -1)
            is_flag = flag_judge['is_flag']
            print("直近近いが、頻度高いため、抵抗線とみなす")
            take_position = True
            comment = comment + "フラッグ以外の短期複数アタック"
        else:
            print("直近近く、単発的なものなので、抵抗線とみなさない", len(same_price_list))

    # ■■オーダーの設定
    # 初期値の設定
    exe_orders = []  # 返却用
    # ★★履歴によるオーダー調整を実施する（TPを拡大する）★★★
    for_history_class = classPosition.order_information("test", "test", False)  # 履歴参照用
    tuned_data = for_history_class.tuning_by_history()  # TuneされたTPやLCChangeを取得する
    tp_range = tuned_data['tuned_tp_range']
    lc_change_type = tuned_data['tuned_lc_change_type']
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
                "name": "Breakオーダー" + comment + "(" + str(len(same_price_list)) + ")_"
            }
            base_order_class = OCreate.OrderCreateClass(base_order_dic)  # オーダーファイナライズ
            exe_orders.append(base_order_class.finalized_order)  # オーダー登録
        else:
            # (当初の基本）抵抗線をBreakしないと判断される場合
            if len(same_price_list) <= 3:
                print("★★★とりあえずオリジナル⇒抵抗線の構成ピークが3個以下の場合、勝率が低いためNG")
                return default_return_item
            peaks = peaks_class.peaks_original
            # 最大LCの調整
            target_price = peaks_class.latest_peak_price + (peaks[0]['direction'] * 0.024)
            lc_price = OCreate.cal_lc_price_from_line_and_margin(peaks[1]['latest_wick_peak_price'], 0.03, peaks[0]['direction'])
            gap = abs(lc_price-target_price)
            re_lc_range = gene.cal_at_most(0.09, gap)
            print("Orderのgap確認", gap, "target_price:", target_price, "deci_price:", peaks_class.df_r_original.iloc[1]['close'])
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
                "name": "山" + comment + "(" + str(len(same_price_list)) + ")_"
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
                base_order_dic['name'] = base_order_dic['name'] + "LC大で修正_"
                base_order_class = OCreate.OrderCreateClass(base_order_dic)  # オーダー生成（というか作り直し）
                # gene.print_json(base_order_class.finalized_order_without_lc_change)  # 表示
                exe_orders.append(base_order_class.finalized_order)

                # # 追加オーダー（基本オーダーのロスカットの場所から、基本オーダーと同じ方向にオーダーを作成する）
                # print("追加オーダー")
                # peaks = peaks_class.peaks_original
                # # Breakしない方向用
                # base_order_dic = {
                #     "target": lc_price,
                #     "type": "LIMIT",
                #     "expected_direction": peaks[0]['direction'],
                #     "tp": 0.50,
                #     "lc": 0.025,
                #     # "tp": 0.075,
                #     # "lc": 0.075,
                #     'priority': 3,
                #     "decision_time": peaks_class.df_r_original.iloc[0]['time_jp'],
                #     "decision_price": peaks_class.df_r_original.iloc[1]['close'],
                #     "order_timeout_min": 35,
                #     "lc_change_type": 2,
                #     "name": "追加オーダー"
                # }
                # # break方向の場合
                # # base_order_dic = {
                # #     "target": OCreate.cal_lc_price_from_line_and_margin(peaks[1]['latest_wick_peak_price'], 0.04,
                # #                                                         peaks[0]['direction']),
                # #     "type": "STOP",
                # #     # "expected_direction": peaks[0]['direction'] * -1,  # Break
                # #     "expected_direction": peaks[0]['direction'],  #
                # #     "tp": 0.20,
                # #     # "lc": OCreate.cal_lc_price_from_line_and_margin(peaks[1]['latest_wick_peak_price'], 0.03, peaks[0]['direction']),  # 0.06,
                # #     "lc": 0.03,
                # #     'priority': 3,
                # #     "decision_time": peaks_class.df_r_original.iloc[0]['time_jp'],
                # #     "decision_price": peaks_class.df_r_original.iloc[1]['close'],
                # #     "order_timeout_min": 35,
                # #     "lc_change_type": 2,
                # #     "name": "追加オーダー"
                # # }
                # base_order_class = OCreate.OrderCreateClass(base_order_dic)
                # exe_orders.append(base_order_class.finalized_order)
                # gene.print_json(base_order_class.finalized_order_without_lc_change)  # 表示
            else:
                print("LCRange基準内のため、そのまま設定（延長先のオーダーもなし")
                exe_orders.append(base_order_class.finalized_order)  # オーダー登録

    return {
        "take_position_flag": take_position,
        "exe_orders": exe_orders,
        "for_inspection_dic": {}
    }


def cal_big_mountain_skip(peaks_class):
    """
    直近のピーク（latest_peakはこれから伸びるPeakなので、直前のpeakは[1]の物を示す
    """
    # ■基本情報の取得
    print("ビッグマウンテンスキップ")
    take_position = False
    s = "    "

    peaks = peaks_class.skipped_peaks

    # ■実行除外
    if peaks[0]['count'] != 2:
        print("no2-", peaks[0]['count'])
        return {
            "take_position_flag": take_position,
            "for_inspection_dic": {}
        }

    # ■■■実行
    target_peak = peaks[1]

    # ■同一価格の調査を行う（BodyPeakと髭ピークの組み合わせ。ただしどちらかはBodyPeakとする）
    target_num = 1  # 以下のループで「自分以外」を定義するため、変数に入れておく(同一方向の配列に対して）
    t = peaks[target_num]
    comment = ""  # 名前につくコメント

    # 変動が少ないところはスキップ
    if target_peak['gap'] <= 0.06:
        # print("targetのGapが少なすぎる", target_peak['gap'])
        return {
            "take_position_flag": take_position,
            "for_inspection_dic": {}
        }

    arrowed_range = peaks_class.recent_fluctuation_range * 0.042  # 最大変動幅の4パーセント程度
    same_price_range = 0.04
    result_same_price_list = []
    result_not_same_price_list = []
    opposite_peaks = []
    break_peaks = []
    # print("  ArrowedGap", arrowed_range)
    for i, item in enumerate(peaks):
        # Continue
        # if i == target_num:
        #     print("飛ばす", peaks[target_num])
        #     continue  # 自分自身は比較しない

        # ■判定０　今回のピークをカウントしない場合
        # 反対方向のピークの場合
        if item['direction'] != target_peak['direction']:
            # ターゲットのピークと逆方向のピークの場合
            opposite_peaks.append({"i": i, "item": item})
            continue
        # 同方向でも、ターゲットをBreakしているもの
        if target_peak['direction'] == 1:
            if item['peak'] > target_peak['peak'] + arrowed_range:
                # ターゲットピークを越えている場合(UpperLineで、上側に突き抜け）、NG
                break_peaks.append({"i": i, "item": item})
        else:
            if item['peak'] < target_peak['peak'] - arrowed_range:
                # ターゲットピークを越えている場合（lowerLineで下に突き抜け）、NG
                break_peaks.append({"i": i, "item": item})

        # ■判定１　全ての近い価格を取得
        body_gap_abs = abs(t['peak'] - item['peak'])
        if abs(item['latest_wick_peak_price'] - item['peak']) >= arrowed_range:
            # 髭が長すぎる場合は無効（無効は、上限をオーバーする値に設定してしまう
            body_wick_gap_abs = arrowed_range + 1  # 確実にarrowed_rangeより大きな値
        else:
            body_wick_gap_abs = abs(t['peak'] - item['latest_wick_peak_price'])
        wick_body_gap_abs = abs(t['latest_wick_peak_price'] - item['peak'])
        # if body_gap_abs <= arrowed_range or body_wick_gap_abs <= arrowed_range or wlen(result_same_price_list)ick_body_gap_abs <= arrowed_range:
        if body_gap_abs <= arrowed_range or body_wick_gap_abs <= arrowed_range:
            # 同一価格とみなせる場合
            result_same_price_list.append({"i": i, "item": item})
        else:
            # print("         違う価格", item['time'], body_gap_abs)
            result_not_same_price_list.append({"i": i, "item": item})

    # print("同一価格一覧")
    # gene.print_arr(result_same_price_list)
    # print("Breakしているもの一覧")
    # gene.print_arr(break_peaks)

    # breakするまでの期間を求める(特殊　Breakしていても、Breakまで時間がある場合、かつ、同一価格もある場合
    # 　例外的に、break開始時に同一価格があったと考えて、処理をする）
    if len(break_peaks) != 0:
        # print("直近のBreakPoint", break_peaks[0]['item']['time'])
        latest_break_gap_min = gene.cal_str_time_gap(t['time'], break_peaks[0]['item']['time'])['gap_abs'] /60
        if latest_break_gap_min <= 20:
            if len(break_peaks) >= 2:
                #　２個以上Breakがある場合は、二つ目も確認して判断
                # print("直近のBreakが直前⇒　２5分以内であれば、ノーカウント", latest_break_gap_min)
                second_break_gap_min = gene.cal_str_time_gap(t['time'], break_peaks[1]['item']['time'])['gap_abs'] / 60
                if second_break_gap_min >= 70:
                    pass
                    # print(" 直近二個目が遠いため、調査実施")
                else:
                    return {
                        "take_position_flag": take_position,
                        "for_inspection_dic": {}
                    }
            else:
                pass
                # print("一つだけの場合は、スルーでスタート。")
        else:
            # print("直近のBreakは結構前⇒規定ないかどうか確認", latest_break_gap_min)
            if latest_break_gap_min >= 70:
                # print(" 結構前なので、この範囲で検証できる(面倒だから、result_same_priceを置き換えちゃう）", id)
                # breakポイントを、同一価格として登録し、それ以前を消去してresult_same_priceを置きかえる
                # 元のリスト
                # 挿入位置を決定
                indices = [d['i'] for d in result_same_price_list]
                pos = bisect.bisect(indices, break_peaks[0]['i'])

                # 新しいリストを作成
                result_same_price_list = result_same_price_list[:pos] + [break_peaks[0]]
                # print("新しい同一価格リスト")
                # gene.print_arr(result_same_price_list)


    # ■同一価格を基にその中の解析を行う
    if 4 > len(result_same_price_list) >= 2:
        # ターゲットのピークに対して、同一とみなせる価格のピークが１つの場合(自身含め２個）、直近が何時間前だったかを確認する(最初と最後？）
        sec_gap_latest_same_price = gene.cal_str_time_gap(t['time'], result_same_price_list[0]['item']['time'])
        sec_gap_oldest_same_price = gene.cal_str_time_gap(t['time'], result_same_price_list[-1]['item']['time'])
        # print("最古の同一の時間", sec_gap_oldest_same_price['gap_abs'] / 60)
        if sec_gap_oldest_same_price['gap_abs'] / 60 >= 70:
            # 90分以上の場合は、山検証の対象
            fr = result_same_price_list[0]['i']  # f はfromを示す（短く書く変数化）
            t = result_same_price_list[-1]['i']  # t はtoを示す（短く書く変数化）
            filtered_peaks = peaks[fr: t + 1]  # 間のピークス（両方の方向）
            filtered_peaks_oppo_peak = [d for d in filtered_peaks if d["direction"] == target_peak['direction'] * -1]

            # 期間内の最大値のピーク情報を求める。（逆サイドの方向が1の場合。-1の場合は最小値）は？
            if target_peak['direction'] * -1 == 1:
                far_item = max(filtered_peaks_oppo_peak, key=lambda x: x["peak"])
            else:
                far_item = min(filtered_peaks_oppo_peak, key=lambda x: x["peak"])
            t_gap = abs(far_item['peak'] - target_peak['peak'])
            # print("対象は", far_item)
            # print(t_gap, far_item['time'], target_peak['time'])
            # print(peaks_class.recent_fluctuation_range, peaks_class.recent_fluctuation_range * 0.38)
            if t_gap >= peaks_class.recent_fluctuation_range * 0.38:  # 最大の7割以上ある山が形成されている場合
                # print("☆☆戻ると判定 2個", t_gap / peaks_class.recent_fluctuation_range)
                take_position = True
            # self.recent_fluctuation_range * 0.7

            # # ■■　間のPeaksの調査を行う
            # # print("間のピークス", result_same_price_list[0]['i'], result_same_price_list[-1]['i'])
            # comment = ""
            # between_peaks = peaks[result_same_price_list[0]['i'] + 1:result_same_price_list[-1]['i']]
            # gene.print_arr(between_peaks)
            # oppo_peaks = [d for d in between_peaks if d["direction"] == target_peak['direction'] * -1]
            # # print("その中で反対向きのもの")
            # # gene.print_arr(oppo_peaks)
            # if target_peak['direction'] == 1:
            #     far_side_peak = min(oppo_peaks, key=lambda x: x["peak"])
            # else:
            #     far_side_peak = max(oppo_peaks, key=lambda x: x["peak"])
            # between_price_gap = abs(far_side_peak['peak'] - target_peak['peak'])
            #
            # # ピークの平均値を算出
            # if len(oppo_peaks) >= 3:
            #     # 3個より大きい場合は、端から二個同士の平均で、間で拡散傾向か収束傾向かを判断する
            #     # 時間的に直近のほう
            #     sum_later = (oppo_peaks[0]['peak'] + oppo_peaks[1]['peak']) / 2
            #     # 時間的に古い側のほう
            #     sum_older = (oppo_peaks[-1]['peak'] + oppo_peaks[-2]['peak']) / 2
            # else:
            #     # 2つしかない場合は、直接比べるしかない
            #     sum_later = oppo_peaks[0]['peak']
            #     sum_older = oppo_peaks[-1]['peak']
            # # print("直近", sum_later, "古いほう", sum_older)
            # # 推移を検討する
            # range_fluctuation_abs = abs(sum_later - sum_older)
            # # 探索方向か谷か山かで異なる（山形状の場合はoppo_peaksのdirectionは1。谷形状の場合は-1）
            # # print("反対の方向", oppo_peaks[0]['direction'])
            # if oppo_peaks[0]['direction'] == -1:
            #     # 谷方向の場合
            #     if sum_later > sum_older:
            #         # print("ピーク減幅（やや突破気味の挙動の傾向）")
            #         comment = "_減幅_"
            #     else:
            #         # print("増幅傾向（戻る確率高い")
            #         comment = "_増幅_"
            # else:
            #     # 山方向の場合
            #     if sum_later < sum_older:
            #         # print("減幅傾向（やや突破気味の挙動の傾向）")
            #         comment = "_減幅_"
            #     else:
            #         # print("増幅傾向（戻る確率高い")
            #         comment = "_増幅_"
            # # 傾き方
            # # print("傾き方 間の最大gap", between_price_gap, "傾き", range_fluctuation_abs, range_fluctuation_abs/between_price_gap)
            # if range_fluctuation_abs/between_price_gap >= 0.25:
            #     # 全体の4分の１以上の傾きがある場合は、傾いている認定（平行ではない）
            #     # print("☆傾いている")
            #     comment = comment + "傾き"
            # else:
            #     # print("傾いているとは言いにくい")
            #     comment = comment + "Not傾き"

    elif len(result_same_price_list) >= 3:
        # 二つの場合、近いほうと遠いほうの比率を検討する
        sec_gap_latest_same_price = gene.cal_str_time_gap(t['time'], result_same_price_list[0]['item']['time'])
        sec_gap_oldest_same_price = gene.cal_str_time_gap(t['time'], result_same_price_list[-1]['item']['time'])
        # print("最古の同一の時間", sec_gap_oldest_same_price['gap_abs'] / 60)
        if sec_gap_oldest_same_price['gap_abs'] / 60 >= 90:
            # 90分以上の場合は、山検証の対象
            fr = result_same_price_list[0]['i']  # f はfromを示す（短く書く変数化）
            t = result_same_price_list[-1]['i']  # t はtoを示す（短く書く変数化）
            filtered_peaks = peaks[fr: t + 1]  # 間のピークス（両方の方向）
            filtered_peaks_oppo_peak = [d for d in filtered_peaks if
                                        d["direction"] == target_peak['direction'] * -1]
            # gene.print_arr(filtered_peaks)
            # print("逆サイドのみ")
            # gene.print_arr(filtered_peaks_oppo_peak)

            # 最大値（逆サイドの方向が1の場合。-1の場合は最小値）は？
            if target_peak['direction'] * -1 == 1:
                far_item = max(filtered_peaks_oppo_peak, key=lambda x: x["peak"])
            else:
                far_item = min(filtered_peaks_oppo_peak, key=lambda x: x["peak"])
            t_gap = abs(far_item['peak'] - target_peak['peak'])
            # print("対象は", far_item)
            # print(t_gap)
            # print(peaks_class.recent_fluctuation_range, peaks_class.recent_fluctuation_range * 0.7)
            if t_gap >= peaks_class.recent_fluctuation_range * 0.7:  # 最大の7割以上ある山が形成されている場合
                # print("☆☆戻ると判定 3個", t_gap / peaks_class.recent_fluctuation_range)
                take_position = True
    else:
        # 3個以上の場合は結構突破している・・・？
        pass

    # 返却用
    exe_orders = []
    if take_position:
        # オーダーありの場合
        # 最大LCの調整
        target_price = peaks_class.latest_peak_price + (peaks[0]['direction'] * 0.04)
        lc_price = OCreate.cal_lc_price_from_line_and_margin(peaks[1]['latest_wick_peak_price'], 0.03, peaks[0]['direction'])
        gap = abs(lc_price-target_price)
        re_lc_range = gene.cal_at_most(0.09, gap)
        # print(peaks_class.df_r_original.iloc[1])
        # print("gapはこれです", gap, "target_price:", target_price, "deci_price:", peaks_class.df_r_original.iloc[1]['close'])
        base_order_dic = {
            "target": 0.03,
            "type": "STOP",
            "expected_direction": peaks[0]['direction'],
            "tp": 0.09,  # 短期では0.15でもOK.ただ長期だと、マイナスの平均が0.114のためマイナスの数が多くなる
            "lc": OCreate.cal_lc_price_from_line_and_margin(peaks[1]['latest_wick_peak_price'], 0.03, peaks[0]['direction']),  # 0.06,
            # "lc": 0.15,
            # "lc": re_lc_range,
            'priority': 3,
            "decision_time": peaks_class.df_r_original.iloc[0]['time_jp'],
            "decision_price": peaks_class.df_r_original.iloc[1]['close'],
            "order_timeout_min": 20,
            "name": "山" + comment + str(len(result_same_price_list))
        }
        base_order_class = OCreate.OrderCreateClass(base_order_dic)
        exe_orders.append(base_order_class.finalized_order)

        # テスト用（Break方向）
        # peaks = peaks_class.peaks_original
        # base_order_dic = {
        #     "target": peaks[1]['latest_wick_peak_price'] + (0.04 * peaks[1]['direction']),
        #     "type": "STOP",
        #     "expected_direction": peaks[1]['direction'],
        #     "tp": 0.05,
        #     # "lc": OCreate.cal_lc_price_from_line_and_margin(peaks[1]['latest_wick_peak_price'], 0.03, peaks[0]['direction']),  # 0.06,
        #     "lc": 0.05,
        #     'priority': 3,
        #     "decision_time": peaks_class.df_r_original.iloc[0]['time_jp'],
        #     "decision_price": peaks_class.df_r_original.iloc[1]['close'],
        #     "order_timeout_min": 20,
        #     "name": "山"
        # }
        # base_order_class = OCreate.OrderCreateClass(base_order_dic)
        # exe_orders.append(base_order_class.finalized_order)
    return {
        "take_position_flag": take_position,
        "exe_orders": exe_orders,
        "for_inspection_dic": {}
    }


def cal_short_time_break(peaks_class):
    """
    現在のOpen価格が、過去４０分以内の抵抗線となる価格に対し、Breakする方向で当たっているか？
    当たっている場合は、Break方向にポジションを取る
    """

    print(" ★　昔と同じ手法を再現")
    # ■基本情報の取得
    take_position = False
    s = "    "

    # peaks = peaks_class.peaks_original
    peaks = peaks_class.skipped_peaks

    latest = peaks[0]
    river = peaks[1]
    turn = peaks[2]

    print(latest)
    print(river)
    print(turn)

    # ■実行除外
    if latest['count'] != 2:
        print("no2-", latest['count'])
        return {
            "take_position_flag": take_position,
            "for_inspection_dic": {}
        }

    river_turn_ratio = river['gap'] / turn['gap']
    print(river_turn_ratio)
    if river_turn_ratio < 0.3:
        print("比率OK", river_turn_ratio)

    #
    # # ■■■実行
    # target_peak = peaks[1]
    #
    # # ■同一価格の調査を行う（BodyPeakと髭ピークの組み合わせ。ただしどちらかはBodyPeakとする）
    # target_num = 1  # 以下のループで「自分以外」を定義するため、変数に入れておく(同一方向の配列に対して）
    # t = peaks[target_num]
    # print(t)
    # comment = ""  # 名前につくコメント
    #
    # # 変動が少ないところはスキップ
    # if target_peak['gap'] <= 0.06:
    #     print("targetのGapが少なすぎる", target_peak['gap'])
    #     return {
    #         "take_position_flag": take_position,
    #         "for_inspection_dic": {}
    #     }
    #
    # arrowed_range = peaks_class.recent_fluctuation_range * 0.042  # 最大変動幅の4パーセント程度
    # same_price_range = 0.04
    # result_same_price_list = []
    # result_not_same_price_list = []
    # opposite_peaks = []
    # break_peaks = []
    # print("  ArrowedGap", arrowed_range)
    # for i, item in enumerate(peaks):
    #     # Continue
    #     # if i == target_num:
    #     #     print("飛ばす", PeaksClass.peaks_original[target_num])
    #     #     continue  # 自分自身は比較しない
    #
    #     # ■判定０　今回のピークをカウントしない場合
    #     # 反対方向のピークの場合
    #     if item['direction'] != target_peak['direction']:
    #         # ターゲットのピークと逆方向のピークの場合
    #         opposite_peaks.append({"i": i, "item": item})
    #         continue
    #     # 同方向でも、ターゲットをBreakしているもの
    #     if target_peak['direction'] == 1:
    #         if item['peak'] > target_peak['peak'] + same_price_range:
    #             # ターゲットピークを越えている場合(UpperLineで、上側に突き抜け）、NG
    #             break_peaks.append({"i": i, "item": item})
    #     else:
    #         if item['peak'] < target_peak['peak'] - same_price_range:
    #             # ターゲットピークを越えている場合（lowerLineで下に突き抜け）、NG
    #             break_peaks.append({"i": i, "item": item})
    #
    #     # ■判定１　全ての近い価格を取得
    #     body_gap_abs = abs(t['peak'] - item['peak'])
    #     if abs(item['latest_wick_peak_price'] - item['peak']) >= same_price_range:
    #         # 髭が長すぎる場合は無効（無効は、上限をオーバーする値に設定してしまう
    #         body_wick_gap_abs = arrowed_range + 1  # 確実にarrowed_rangeより大きな値
    #     else:
    #         body_wick_gap_abs = abs(t['peak'] - item['latest_wick_peak_price'])
    #     wick_body_gap_abs = abs(t['latest_wick_peak_price'] - item['peak'])
    #     # if body_gap_abs <= arrowed_range or body_wick_gap_abs <= arrowed_range or wlen(result_same_price_list)ick_body_gap_abs <= arrowed_range:
    #     if body_gap_abs <= arrowed_range or body_wick_gap_abs <= arrowed_range:
    #         # 同一価格とみなせる場合
    #         result_same_price_list.append({"i": i, "item": item})
    #     else:
    #         print("         違う価格", item['time'], body_gap_abs)
    #         result_not_same_price_list.append({"i": i, "item": item})
    #
    # print("同一価格一覧")
    # gene.print_arr(result_same_price_list)
    # print("Breakしているもの一覧")
    # gene.print_arr(break_peaks)
    #
    # # breakするまでの期間を求める(特殊　Breakしていても、Breakまで時間がある場合、かつ、同一価格もある場合
    # # 　例外的に、break開始時に同一価格があったと考えて、処理をする）
    # # ★同一価格が二個未満、★かつ直近の同一価格が７０分以下の場合の場合は実施しない（そもそも基準を満たしていないため）
    # sec_gap_oldest_same_price = gene.cal_str_time_gap(t['time'], result_same_price_list[-1]['item']['time'])
    # if len(result_same_price_list) >= 2 and sec_gap_oldest_same_price['gap_abs'] / 60 >= 70:
    #     # 最低条件の達成(同一価格二個以上、かつ、それらが結構離れている）
    #     if len(break_peaks) != 0:
    #         print("直近のBreakPoint", break_peaks[0]['item']['time'])
    #         latest_break_gap_min = gene.cal_str_time_gap(t['time'], break_peaks[0]['item']['time'])['gap_abs'] /60
    #         if latest_break_gap_min <= 30:
    #             if len(break_peaks) >= 2:
    #                 #　２個以上Breakがある場合は、二つ目も確認して判断
    #                 print("直近のBreakが直前⇒　２5分以内であれば、ノーカウント", latest_break_gap_min)
    #                 second_break_gap_min = gene.cal_str_time_gap(t['time'], break_peaks[1]['item']['time'])['gap_abs'] / 60
    #                 if second_break_gap_min >= 70:
    #                     print(" 直近二個目が遠いため、調査実施")
    #                 else:
    #                     return {
    #                         "take_position_flag": take_position,
    #                         "for_inspection_dic": {}
    #                     }
    #             else:
    #                 print("一つだけの場合は、スルーでスタート。")
    #         else:
    #             print("直近のBreakは結構前⇒規定ないかどうか確認", latest_break_gap_min)
    #             if latest_break_gap_min >= 70:
    #                 print(" 結構前なので、この範囲で検証できる(面倒だから、result_same_priceを置き換えちゃう）", id)
    #                 # breakポイントを、同一価格として登録し、それ以前を消去してresult_same_priceを置きかえる
    #                 # 元のリスト
    #                 # 挿入位置を決定
    #                 indices = [d['i'] for d in result_same_price_list]
    #                 pos = bisect.bisect(indices, break_peaks[0]['i'])
    #
    #                 # 新しいリストを作成
    #                 result_same_price_list = result_same_price_list[:pos] + [break_peaks[0]]
    #                 print("新しい同一価格リスト")
    #                 gene.print_arr(result_same_price_list)
    # else:
    #     print("同一価格情報の不一致", sec_gap_oldest_same_price, len(result_same_price_list))
    #
    #
    # # ■同一価格を基にその中の解析を行う
    # if 4 > len(result_same_price_list) >= 2:
    #     # ターゲットのピークに対して、同一とみなせる価格のピークが１つの場合(自身含め２個）、直近が何時間前だったかを確認する(最初と最後？）
    #     sec_gap_latest_same_price = gene.cal_str_time_gap(t['time'], result_same_price_list[0]['item']['time'])
    #     sec_gap_oldest_same_price = gene.cal_str_time_gap(t['time'], result_same_price_list[-1]['item']['time'])
    #     print("最古の同一の時間", sec_gap_oldest_same_price['gap_abs'] / 60)
    #     if sec_gap_oldest_same_price['gap_abs'] / 60 >= 70:
    #         # 90分以上の場合は、山検証の対象
    #         fr = result_same_price_list[0]['i']  # f はfromを示す（短く書く変数化）
    #         t = result_same_price_list[-1]['i']  # t はtoを示す（短く書く変数化）
    #         filtered_peaks = peaks[fr: t + 1]  # 間のピークス（両方の方向）
    #         filtered_peaks_oppo_peak = [d for d in filtered_peaks if d["direction"] == target_peak['direction'] * -1]
    #
    #         # 期間内の最大値のピーク情報を求める。（逆サイドの方向が1の場合。-1の場合は最小値）は？
    #         if target_peak['direction'] * -1 == 1:
    #             far_item = max(filtered_peaks_oppo_peak, key=lambda x: x["peak"])
    #         else:
    #             far_item = min(filtered_peaks_oppo_peak, key=lambda x: x["peak"])
    #         t_gap = abs(far_item['peak'] - target_peak['peak'])
    #         print("対象は", far_item)
    #         print(t_gap, far_item['time'], target_peak['time'])
    #         print(peaks_class.recent_fluctuation_range, peaks_class.recent_fluctuation_range * 0.38)
    #         if t_gap >= peaks_class.recent_fluctuation_range * 0.38:  # 最大の7割以上ある山が形成されている場合
    #             print("☆☆戻ると判定 2個", t_gap / peaks_class.recent_fluctuation_range)
    #             take_position = True
    #         # self.recent_fluctuation_range * 0.7
    #
    #         # ■■　間のPeaksの調査を行う
    #         print("間のピークス", result_same_price_list[0]['i'], result_same_price_list[-1]['i'])
    #         comment = ""
    #         between_peaks = peaks[result_same_price_list[0]['i'] + 1:result_same_price_list[-1]['i']]
    #         gene.print_arr(between_peaks)
    #         oppo_peaks = [d for d in between_peaks if d["direction"] == target_peak['direction'] * -1]
    #         print("その中で反対向きのもの")
    #         gene.print_arr(oppo_peaks)
    #         if target_peak['direction'] == 1:
    #             far_side_peak = min(oppo_peaks, key=lambda x: x["peak"])
    #         else:
    #             far_side_peak = max(oppo_peaks, key=lambda x: x["peak"])
    #         between_price_gap = abs(far_side_peak['peak'] - target_peak['peak'])
    #
    #         # ピークの平均値を算出
    #         if len(oppo_peaks) >= 3:
    #             # 3個より大きい場合は、端から二個同士の平均で、間で拡散傾向か収束傾向かを判断する
    #             # 時間的に直近のほう
    #             sum_later = (oppo_peaks[0]['peak'] + oppo_peaks[1]['peak']) / 2
    #             # 時間的に古い側のほう
    #             sum_older = (oppo_peaks[-1]['peak'] + oppo_peaks[-2]['peak']) / 2
    #         else:
    #             # 2つしかない場合は、直接比べるしかない
    #             sum_later = oppo_peaks[0]['peak']
    #             sum_older = oppo_peaks[-1]['peak']
    #         print("直近", sum_later, "古いほう", sum_older)
    #         # 推移を検討する
    #         range_fluctuation_abs = abs(sum_later - sum_older)
    #         # 探索方向か谷か山かで異なる（山形状の場合はoppo_peaksのdirectionは1。谷形状の場合は-1）
    #         print("反対の方向", oppo_peaks[0]['direction'])
    #         if oppo_peaks[0]['direction'] == -1:
    #             # 谷方向の場合
    #             if sum_later > sum_older:
    #                 print("ピーク減幅（やや突破気味の挙動の傾向）")
    #                 comment = "_減幅_"
    #             else:
    #                 print("増幅傾向（戻る確率高い")
    #                 comment = "_増幅_"
    #         else:
    #             # 山方向の場合
    #             if sum_later < sum_older:
    #                 print("減幅傾向（やや突破気味の挙動の傾向）")
    #                 comment = "_減幅_"
    #             else:
    #                 print("増幅傾向（戻る確率高い")
    #                 comment = "_増幅_"
    #         # 傾き方
    #         print("傾き方 間の最大gap", between_price_gap, "傾き", range_fluctuation_abs, range_fluctuation_abs/between_price_gap)
    #         if range_fluctuation_abs/between_price_gap >= 0.25:
    #             # 全体の4分の１以上の傾きがある場合は、傾いている認定（平行ではない）
    #             print("☆傾いている")
    #             comment = comment + "傾き"
    #         else:
    #             print("傾いているとは言いにくい")
    #             comment = comment + "Not傾き"
    #
    # elif len(result_same_price_list) >= 3:
    #     # 二つの場合、近いほうと遠いほうの比率を検討する
    #     sec_gap_latest_same_price = gene.cal_str_time_gap(t['time'], result_same_price_list[0]['item']['time'])
    #     sec_gap_oldest_same_price = gene.cal_str_time_gap(t['time'], result_same_price_list[-1]['item']['time'])
    #     print("最古の同一の時間", sec_gap_oldest_same_price['gap_abs'] / 60)
    #     if sec_gap_oldest_same_price['gap_abs'] / 60 >= 90:
    #         # 90分以上の場合は、山検証の対象
    #         fr = result_same_price_list[0]['i']  # f はfromを示す（短く書く変数化）
    #         t = result_same_price_list[-1]['i']  # t はtoを示す（短く書く変数化）
    #         filtered_peaks = peaks[fr: t + 1]  # 間のピークス（両方の方向）
    #         filtered_peaks_oppo_peak = [d for d in filtered_peaks if
    #                                     d["direction"] == target_peak['direction'] * -1]
    #         gene.print_arr(filtered_peaks)
    #         print("逆サイドのみ")
    #         gene.print_arr(filtered_peaks_oppo_peak)
    #
    #         # 最大値（逆サイドの方向が1の場合。-1の場合は最小値）は？
    #         if target_peak['direction'] * -1 == 1:
    #             far_item = max(filtered_peaks_oppo_peak, key=lambda x: x["peak"])
    #         else:
    #             far_item = min(filtered_peaks_oppo_peak, key=lambda x: x["peak"])
    #         t_gap = abs(far_item['peak'] - target_peak['peak'])
    #         print("対象は", far_item)
    #         print(t_gap)
    #         print(peaks_class.recent_fluctuation_range, peaks_class.recent_fluctuation_range * 0.7)
    #         if t_gap >= peaks_class.recent_fluctuation_range * 0.7:  # 最大の7割以上ある山が形成されている場合
    #             print("☆☆戻ると判定 3個", t_gap / peaks_class.recent_fluctuation_range)
    #             take_position = True
    # else:
    #     # 3個以上の場合は結構突破している・・・？
    #     pass
    #
    # # スキップでも検証
    # print("■■■SKIPバージョン")
    # skip_ans = cal_big_mountain_skip(peaks_class)
    # print("回答")
    # print(skip_ans['take_position_flag'])
    # print("■■■↑")
    #
    # # Peakの強度の確認
    # ps_group = cpk.judge_peak_is_belong_peak_group(peaks, target_peak)
    # print("↑Peakが最大軍（最小群）かどうか")
    #
    # # 返却用
    # exe_orders = []
    # if take_position:
    #     # オーダーありの場合
    #     peaks = peaks_class.peaks_original
    #     # 最大LCの調整
    #     target_price = peaks_class.df_r_original.iloc[1]['close'] + (peaks[0]['direction'] * 0.024)
    #     lc_price = OCreate.cal_lc_price_from_line_and_margin(peaks[1]['latest_wick_peak_price'], 0.03, peaks[0]['direction'])
    #     gap = abs(lc_price-target_price)
    #     re_lc_range = gene.cal_at_most(0.09, gap)
    #     # print(peaks_class.df_r_original.iloc[1])
    #     print("gapはこれです", gap, "target_price:", target_price, "deci_price:", peaks_class.df_r_original.iloc[1]['close'])
    #     base_order_dic = {
    #         "target": 0.025,
    #         "type": "STOP",
    #         "expected_direction": peaks[0]['direction'],
    #         "tp": 0.50,  # 短期では0.15でもOK.ただ長期だと、マイナスの平均が0.114のためマイナスの数が多くなる
    #         "lc": OCreate.cal_lc_price_from_line_and_margin(peaks[1]['latest_wick_peak_price'], 0.03, peaks[0]['direction']),  # 0.06,
    #         # "lc": 0.15,
    #         # "lc": 0.04,
    #         'priority': 3,
    #         "decision_time": peaks_class.df_r_original.iloc[0]['time_jp'],
    #         "decision_price": peaks_class.df_r_original.iloc[1]['close'],
    #         "order_timeout_min": 20,
    #         "lc_change_type": 1,
    #         "name": "山" + comment + str(len(result_same_price_list)) + "SKIP:" + str(skip_ans['take_position_flag'])
    #     }
    #     base_order_class = OCreate.OrderCreateClass(base_order_dic)  # オーダー生成
    #     # gene.print_json(base_order_class.finalized_order_without_lc_change)  # 表示
    #
    #     # オーダーの修正と、場合によって追加オーダー設定
    #     lc_max = 0.09
    #     lc_change_after = 0.075
    #     if base_order_class.finalized_order['lc_range'] >= lc_max:
    #         print("LCが大きいため再オーダー設定")
    #         # オーダー修正（LC短縮）
    #         base_order_dic['lc'] = lc_change_after
    #         base_order_class = OCreate.OrderCreateClass(base_order_dic)  # オーダー生成
    #         # gene.print_json(base_order_class.finalized_order_without_lc_change)  # 表示
    #         exe_orders.append(base_order_class.finalized_order)
    #
    #         # 追加オーダー　：　少し下から用（Break方向）
    #         print("追加オーダー")
    #         peaks = peaks_class.peaks_original
    #         # Breakしない方向用
    #         base_order_dic = {
    #             "target": OCreate.cal_lc_price_from_line_and_margin(peaks[1]['latest_wick_peak_price'], 0.03,
    #                                                                 peaks[0]['direction']),
    #             "type": "LIMIT",
    #             "expected_direction": peaks[0]['direction'],
    #             "tp": 0.50,
    #             # "lc": OCreate.cal_lc_price_from_line_and_margin(peaks[1]['latest_wick_peak_price'], 0.03, peaks[0]['direction']),  # 0.06,
    #             "lc": 0.025,
    #             'priority': 3,
    #             "decision_time": peaks_class.df_r_original.iloc[0]['time_jp'],
    #             "decision_price": peaks_class.df_r_original.iloc[1]['close'],
    #             "order_timeout_min": 35,
    #             "lc_change_type": 2,
    #             "name": "追加オーダー"
    #         }
    #         # break方向の場合
    #         # base_order_dic = {
    #         #     "target": OCreate.cal_lc_price_from_line_and_margin(peaks[1]['latest_wick_peak_price'], 0.04,
    #         #                                                         peaks[0]['direction']),
    #         #     "type": "STOP",
    #         #     # "expected_direction": peaks[0]['direction'] * -1,  # Break
    #         #     "expected_direction": peaks[0]['direction'],  #
    #         #     "tp": 0.20,
    #         #     # "lc": OCreate.cal_lc_price_from_line_and_margin(peaks[1]['latest_wick_peak_price'], 0.03, peaks[0]['direction']),  # 0.06,
    #         #     "lc": 0.03,
    #         #     'priority': 3,
    #         #     "decision_time": peaks_class.df_r_original.iloc[0]['time_jp'],
    #         #     "decision_price": peaks_class.df_r_original.iloc[1]['close'],
    #         #     "order_timeout_min": 35,
    #         #     "lc_change_type": 2,
    #         #     "name": "追加オーダー"
    #         # }
    #         base_order_class = OCreate.OrderCreateClass(base_order_dic)
    #         # gene.print_json(base_order_class.finalized_order_without_lc_change)  # 表示
    #         exe_orders.append(base_order_class.finalized_order)
    #     else:
    #         print("LCRange基準内のため、そのまま設定（延長先のオーダーもなし")
    #         exe_orders.append(base_order_class.finalized_order)  # オーダー登録
    #
    #
    #
    #
    # return {
    #     "take_position_flag": take_position,
    #     "exe_orders": exe_orders,
    #     "for_inspection_dic": {}
    # }

# def main_simple_turn(dic_args):
#     """
#     引数はDFやピークスなど
#     オーダーを生成する
#     """
#
#     # 表示時のインデント
#     s4 = "    "
#     s6 = "      "
#
#     print(" シンプルターン調査")
#     # ■関数事前準備■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■
#     # ■■返却値 とその周辺の値
#     exe_orders = []
#     orders_and_evidence = {
#         "take_position_flag": False,
#         "exe_orders": exe_orders,
#         "information": []
#     }
#     # ■■情報の整理と取得（関数の頭には必須）
#     peaksclass = cpk.PeaksClass(dic_args['df_r'])
#     df_r = dic_args['df_r']
#     peaks = peaksclass.skipped_peaks
#
#     # ■調査を実施する■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■
#     # ■■実行しない条件の場合、実行を終了する
#     if peaks[0]['count'] != 2:
#         print(s6, "count2以外の実行無し", peaks[0]['count'])  # フラッグは基本的に、Latestの数がいつでも実行する
#         return orders_and_evidence
#
#     if peaks[1]['gap'] <= 0.03:
#         print(s4, "前が少なすぎるのでキャンセル", peaks[1]["time"], peaks[1]['gap'])
#         # tk.line_send("前が少なすぎるので今回はオーダーなし", peaks[1]["time"], peaks[1]['gap'])
#         return orders_and_evidence
#
#     # ■■解析の実行
#     # ■注文情報の整理
#     if peaks[0]['direction'] == 1:
#         # 直近が上向きの場合
#         target_price = df_r.iloc[1]['inner_high']  # 直近を除いたピークにほぼ等しい。マージンは０といえる
#         lc_price_temp = df_r.iloc[1]['low']
#     else:
#         # 直近が下向きの場合
#         target_price = df_r.iloc[1]['inner_low']
#         lc_price_temp = df_r.iloc[1]['high']
#     # 共通項目
#     lc_range = abs(target_price - lc_price_temp)
#     direction = peaks[0]['direction']
#     # LCは小さめにしたい
#     if lc_range >= 0.035:
#         print(s6, "LCRangeが大きいため、LCを縮小")
#         lc_range = 0.035
#     if lc_range <= 0.01:
#         print(s6, "LCRangeが小さいため、LCを縮小")
#         lc_range = 0.02
#
#     # ■サイズを検証し、オーダーを入れる(ここで検証を実施）
#     move_size_ans = ms.cal_move_size({"df_r": df_r})
#     # 大きな変動がある直後のオーダー（ビッグムーブとは逆の動き）
#     if move_size_ans['big_move']:
#         print("★Big_move_直後のカウンターオーダー(少し折り返した時点でオーダーが入る）")
#         orders_and_evidence["take_position_flag"] = True  # ここまで来ている＝注文あり
#         base_order_dic = {
#             "target": 0.015,
#             "type": "STOP",
#             "expected_direction": peaks[0]['direction'],
#             "tp": 0.9,
#             "lc": peaks[1]['peak'],
#             'priority': 4,
#             "decision_time": df_r.iloc[0]['time_jp'],
#             "order_timeout_min": 15,
#             "name": "ビッグムーブ直後(HighPriority)",
#         }
#         base_order_class = OCreate.OrderCreateClass(base_order_dic)
#         exe_orders.append(base_order_class.finalized_order)
#     else:
#         print("Big_Moveの後ではない")
#
#     # ■抵抗線の調査を実施する
#     # registance_line_ans = registance_analysis({"df_r": df_r})
#     if move_size_ans['is_latest_peak_resistance_line'] != 0:
#         print("  直前ピークが抵抗線（突破と戻りを同時に出す")
#         print(peaks[1]['peak_old'])
#
#         # ■突破方向
#         orders_and_evidence["take_position_flag"] = True  # ここまで来ている＝注文あり
#         base_order_dic = {
#             "target": peaks[1]['peak'] + (0.02 * peaks[0]['direction'] * -1),
#             "type": "STOP",
#             "expected_direction": peaks[0]['direction'] * -1,
#             "tp": 0.9,
#             "lc": 0.06,
#             'priority': 3,
#             "decision_time": df_r.iloc[0]['time_jp'],
#             "order_timeout_min": 20,
#             "name": "直前ピークが抵抗線（突破方向）"
#         }
#         base_order_class = OCreate.OrderCreateClass(base_order_dic)
#         counter_order_base = {
#             "units": 10000,
#             "target": peaks[1]['peak'] + (0.02 * peaks[0]['direction'] * -1),
#             "type": "STOP",
#             "expected_direction": peaks[0]['direction'] * -1,
#             "tp": 0.9,
#             "lc": 0.025,
#             'priority': 3,
#             "decision_time": df_r.iloc[0]['time_jp'],
#             "order_timeout_min": 20,
#             "name": "カウンタオーオーダー　直前ピークが抵抗線（突破方向）"
#         }
#         counter_order = OCreate.OrderCreateClass(counter_order_base)
#         base_order_class.add_counter_order(counter_order.finalized_order)
#         exe_orders.append(base_order_class.finalized_order)
#
#         # ■戻り方向
#         latest_candle_size = df_r.iloc[1]['highlow']
#         orders_and_evidence["take_position_flag"] = True  # ここまで来ている＝注文あり
#         base_order_dic = {
#             "target": latest_candle_size,
#             "type": "STOP",
#             "expected_direction": peaks[0]['direction'] * -1,
#             "tp": 0.9,
#             "lc": 0.06,
#             'priority': 3,
#             "decision_time": df_r.iloc[0]['time_jp'],
#             "order_timeout_min": 20,
#             "name": "直前ピークが抵抗線（戻し方向）"
#         }
#         base_order_class = OCreate.OrderCreateClass(base_order_dic)
#         counter_order_base = {
#             "units": 10000,
#             "target": peaks[1]['peak'] + (0.02 * peaks[0]['direction'] * -1),
#             "type": "STOP",
#             "expected_direction": peaks[0]['direction'] * -1,
#             "tp": 0.9,
#             "lc": 0.025,
#             'priority': 3,
#             "decision_time": df_r.iloc[0]['time_jp'],
#             "order_timeout_min": 20,
#             "name": "カウンタオーオーダー　直前ピークが抵抗線（戻し方向）"
#         }
#         counter_order = OCreate.OrderCreateClass(counter_order_base)
#         base_order_class.add_counter_order(counter_order.finalized_order)
#         exe_orders.append(base_order_class.finalized_order)
#     else:
#         print(" 直近抵抗線ではない")
#
#     if move_size_ans['peak_is_peak']:
#         if peaks[1]['gap'] >= 0.09:
#             print("★直近での最ピーク値")
#             orders_and_evidence["take_position_flag"] = True  # ここまで来ている＝注文あり
#             # 突破方向
#             base_order_dic = {
#                 "target": peaks[1]['peak'] + (0.02 * peaks[0]['direction'] * -1),
#                 "type": "STOP",
#                 "expected_direction": peaks[0]['direction'] * -1,
#                 "tp": 0.9,
#                 "lc": 0.06,
#                 'priority': 2,
#                 "decision_time": df_r.iloc[0]['time_jp'],
#                 "decision_price": target_price,
#                 "order_timeout_min": 20,
#                 "name": "直前ピークがピーク値（突破方向）"
#             }
#             base_order_class = OCreate.OrderCreateClass(base_order_dic)
#             exe_orders.append(base_order_class.finalized_order)
#             # カウンター方向
#             range_order_dic = {
#                 "target": round((peaks[1]['peak'] + peaks[1]['peak_old']) / 2, 3),
#                 "type": "STOP",
#                 "expected_direction": peaks[0]['direction'],
#                 "tp": 0.9,
#                 "lc": peaks[1]['peak'],
#                 'priority': 2,
#                 "decision_time": df_r.iloc[0]['time_jp'],
#                 "decision_price": target_price,
#                 "order_timeout_min": 20,
#                 "name": "直前ピークがピーク値（もどり方向）"
#             }
#             range_order_class = OCreate.OrderCreateClass(range_order_dic)
#             exe_orders.append(range_order_class.finalized_order)
#         else:
#             print(s4, " 最ピーク値だが、riverのギャップが小さいのでやらない。")
#     else:
#         print(" 直近は最ピークではない")
#
#
#     # 返却する
#     print(s4, "オーダー対象のため、オーダーリストを登録する(フラグは各場所で上げる)")
#     orders_and_evidence["exe_orders"] = exe_orders
#
#     if orders_and_evidence["take_position_flag"]:
#         print("シンプルターンのオーダー表示")
#         gene.print_arr(orders_and_evidence["exe_orders"])
#         return orders_and_evidence
#     else:
#         print("  シンプルターンオーダーなし")
#         print(orders_and_evidence)
#         return orders_and_evidence
#
#
# def main_simple_turn2(dic_args):
#     """
#     引数はDFやピークスなど
#     オーダーを生成する
#     """
#
#     # 表示時のインデント
#     s4 = "    "
#     s6 = "      "
#
#     print(" シンプルターン調査")
#     # ■関数事前準備■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■
#     # ■■返却値 とその周辺の値
#     orders_and_evidence = {
#         "take_position_flag": False,
#         "exe_orders": [],
#         "information": []
#     }
#     # ■■情報の整理と取得（関数の頭には必須）
#     peaksclass = cpk.PeaksClass(dic_args['df_r'])
#     df_r = dic_args['df_r']
#     peaks = peaksclass.skipped_peaks
#
#
#
#     # 返
#     if orders_and_evidence["take_position_flag"]:
#         print("シンプルターンのオーダー表示")
#         gene.print_arr(orders_and_evidence["exe_orders"])
#         return orders_and_evidence
#     else:
#         print("  シンプルターンオーダーなし")
#         print(orders_and_evidence)
#         return orders_and_evidence
