import copy

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
import classOrderCreate as OCreate
import classPosition
import bisect


def line_tilt(target_peaks, peaks_class):
    """

    """

    s = "    "
    # ■■　間のPeaksの調査を行う
    print(s, "間のピークス傾きの検証 ↓対象のピークス")
    gene.print_arr(target_peaks)
    # ピークの平均値を算出
    if len(target_peaks) >= 3:
        # 3個より大きい場合は、端から二個同士の平均で、間で拡散傾向か収束傾向かを判断する
        # 時間的に直近のほう
        sum_later = (target_peaks[0]['peak'] + target_peaks[1]['peak']) / 2
        # 時間的に古い側のほう
        sum_older = (target_peaks[-1]['peak'] + target_peaks[-2]['peak']) / 2
    else:
        # 2つしかない場合は、直接比べるしかない
        sum_later = target_peaks[0]['peak']
        sum_older = target_peaks[-1]['peak']
    print(s, "直近", sum_later, "古いほう", sum_older)
    # 推移を検討する
    range_fluctuation_abs = abs(sum_later - sum_older)
    # 探索方向か谷か山かで異なる（山形状の場合はoppo_peaksのdirectionは1。谷形状の場合は-1）
    print(s, "反対の方向", target_peaks[0]['direction'])
    if target_peaks[0]['direction'] == -1:
        # 谷方向の場合
        if sum_later > sum_older:
            print(s, "ピーク減幅（やや突破気味の挙動の傾向）")
            comment = "_減幅_"
        else:
            print(s, "増幅傾向（戻る確率高い")
            comment = "_増幅_"
    else:
        # 山方向の場合
        if sum_later < sum_older:
            print(s, "減幅傾向（やや突破気味の挙動の傾向）")
            comment = "_減幅_"
        else:
            print(s, "増幅傾向（戻る確率高い")
            comment = "_増幅_"
    # 傾き方
    # print(s, "傾き方 間の最大gap", between_price_gap, "傾き", range_fluctuation_abs,
    #       range_fluctuation_abs / between_price_gap)
    # if range_fluctuation_abs / between_price_gap >= 0.25:
    #     # 全体の4分の１以上の傾きがある場合は、傾いている認定（平行ではない）
    #     print("☆傾いている")
    #     comment = comment + "傾き"
    # else:
    #     print("傾いているとは言いにくい")
    #     comment = comment + "Not傾き"


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

    # ■実行除外
    if peaks[0]['count'] != 2:
        print("  Latestカウントにより除外", peaks[0]['count'])
        return {
            "take_position_flag": take_position,
            "for_inspection_dic": {}
        }

    # ■■■実行
    target_peak = peaks[1]

    # ■同一価格の調査を行う（BodyPeakと髭ピークの組み合わせ。ただしどちらかはBodyPeakとする）
    target_num = 1  # 以下のループで「自分以外」を定義するため、変数に入れておく(同一方向の配列に対して）
    t = peaks[target_num]
    print("ターゲットになるピーク:", t)
    comment = ""  # 名前につくコメント

    # 変動が少ないところはスキップ
    if target_peak['gap'] <= 0.06:
        print("targetのGapが少なすぎる", target_peak['gap'])
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
    print("同一価格とみなす幅:", arrowed_range)
    for i, item in enumerate(peaks):

        # ■判定０　今回のピークをカウントしない場合
        # 反対方向のピークの場合
        if item['direction'] != target_peak['direction']:
            # ターゲットのピークと逆方向のピークの場合
            opposite_peaks.append({"i": i, "item": item})
            continue
        # 同方向でも、ターゲットをBreakしているもの
        if target_peak['direction'] == 1:
            if item['peak'] > target_peak['peak'] + same_price_range:
                # ターゲットピークを越えている場合(UpperLineで、上側に突き抜け）、NG
                break_peaks.append({"i": i, "item": item})
        else:
            if item['peak'] < target_peak['peak'] - same_price_range:
                # ターゲットピークを越えている場合（lowerLineで下に突き抜け）、NG
                break_peaks.append({"i": i, "item": item})

        # ■判定１　全ての近い価格を取得
        body_gap_abs = abs(t['peak'] - item['peak'])
        if abs(item['latest_wick_peak_price'] - item['peak']) >= same_price_range:
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

    print("同一価格一覧")
    gene.print_arr(result_same_price_list)
    print("Breakしているもの一覧")
    gene.print_arr(break_peaks)

    # 同一価格から、弱いピークを削除する
    peak_border = 4  # ここで指定したピークより大きなものを残す（4を指定した場合、５以上を残す）
    result_same_price_list = [
        entry
        for entry in result_same_price_list
        if entry["item"].get("peak_strength", 0) > peak_border  # 4より大きな物のみ抽出（＝4以下は削除する）
    ]
    print("同一価格一覧　弱ピーク削除後", len(result_same_price_list))
    gene.print_arr(result_same_price_list)
    if len(result_same_price_list) == 0:
        print("強度の弱いピークを除外すると、同一価格なし", target_peak['gap'])
        return {
            "take_position_flag": take_position,
            "for_inspection_dic": {}
        }

    # breakするまでの期間を求める(特殊　Breakしていても、Breakまで時間がある場合、かつ、同一価格もある場合
    # 　例外的に、break開始時に同一価格があったと考えて、処理をする）
    # 　★同一価格が二個未満、★かつ直近の同一価格が７０分以下の場合の場合は実施しない（そもそも基準を満たしていないため）
    sec_gap_oldest_same_price = gene.cal_str_time_gap(t['time'], result_same_price_list[-1]['item']['time'])
    if len(result_same_price_list) >= 2 and sec_gap_oldest_same_price['gap_abs'] / 60 >= 70:
        # 最低条件の達成(同一価格二個以上、かつ、それらが結構離れている）
        if len(break_peaks) != 0:
            print("直近のBreakPoint", break_peaks[0]['item']['time'])
            latest_break_gap_min = gene.cal_str_time_gap(t['time'], break_peaks[0]['item']['time'])['gap_abs'] /60
            if latest_break_gap_min <= 30:
                if len(break_peaks) >= 2:
                    #　２個以上Breakがある場合は、二つ目も確認して判断
                    print("直近のBreakが直前⇒　２5分以内であれば、ノーカウント", latest_break_gap_min)
                    second_break_gap_min = gene.cal_str_time_gap(t['time'], break_peaks[1]['item']['time'])['gap_abs'] / 60
                    if second_break_gap_min >= 70:
                        print(" 直近二個目が遠いため、調査実施")
                    else:
                        return {
                            "take_position_flag": take_position,
                            "for_inspection_dic": {}
                        }
                else:
                    print("一つだけの場合は、スルーでスタート。")
            else:
                print("直近のBreakは結構前⇒規定ないかどうか確認", latest_break_gap_min)
                if latest_break_gap_min >= 70:
                    print(" 結構前なので、この範囲で検証できる(面倒だから、result_same_priceを置き換えちゃう）", id)
                    # breakポイントを、同一価格として登録し、それ以前を消去してresult_same_priceを置きかえる
                    # 元のリスト
                    # 挿入位置を決定
                    indices = [d['i'] for d in result_same_price_list]
                    pos = bisect.bisect(indices, break_peaks[0]['i'])

                    # 新しいリストを作成
                    result_same_price_list = result_same_price_list[:pos] + [break_peaks[0]]
                    # print("新しい同一価格リスト")
                    # gene.print_arr(result_same_price_list)
        else:
            print("Break無し⇒結構強い？")
    else:
        print("同一価格情報の不一致", sec_gap_oldest_same_price, len(result_same_price_list))


    # ■同一価格を基にその中の解析を行う
    s = "   "
    if 4 >= len(result_same_price_list) >= 2:
        # ターゲットのピークに対して、同一とみなせる価格のピークが１つの場合(自身含め２個）、直近が何時間前だったかを確認する(最初と最後？）
        sec_gap_latest_same_price = gene.cal_str_time_gap(t['time'], result_same_price_list[0]['item']['time'])
        sec_gap_oldest_same_price = gene.cal_str_time_gap(t['time'], result_same_price_list[-1]['item']['time'])
        print(s, "最古の同一の時間", sec_gap_oldest_same_price['gap_abs'] / 60)
        if sec_gap_oldest_same_price['gap_abs'] / 60 >= 70:
            # ■■まずは戻るかの判定
            # 規定分以上の場合は、山検証の対象
            fr = result_same_price_list[0]['i']  # f はfromを示す（短く書く変数化）
            t = result_same_price_list[-1]['i']  # t はtoを示す（短く書く変数化）
            sandwiched_peaks = peaks[fr: t + 1]  # 間のピークス（両方の方向）
            sandwiched_peaks_oppo_peak = [d for d in sandwiched_peaks if d["direction"] == target_peak['direction'] * -1]

            # 期間内の最大値のピーク情報を求める。（逆サイドの方向が1の場合。-1の場合は最小値）は？
            if target_peak['direction'] * -1 == 1:
                far_item = max(sandwiched_peaks_oppo_peak, key=lambda x: x["peak"])
            else:
                far_item = min(sandwiched_peaks_oppo_peak, key=lambda x: x["peak"])
            t_gap = abs(far_item['peak'] - target_peak['peak'])
            print(s, "＜山(谷)探し＞")
            print(s, "山の高さと山の位置:", t_gap, far_item['time'], target_peak['time'])
            print(s, "直近の最大変動幅", peaks_class.recent_fluctuation_range, peaks_class.recent_fluctuation_range * 0.38)
            if t_gap >= peaks_class.recent_fluctuation_range * 0.38:  # 最大の7割以上ある山が形成されている場合
                print(s, "★★戻る判定！！", t_gap / peaks_class.recent_fluctuation_range)
                take_position = True
            # self.recent_fluctuation_range * 0.7

            # ■傾きの検証
            line_tilt(sandwiched_peaks_oppo_peak, peaks_class)

    elif len(result_same_price_list) >= 3:
        # 二つの場合、近いほうと遠いほうの比率を検討する
        sec_gap_latest_same_price = gene.cal_str_time_gap(t['time'], result_same_price_list[0]['item']['time'])
        sec_gap_oldest_same_price = gene.cal_str_time_gap(t['time'], result_same_price_list[-1]['item']['time'])
        # print("最古の同一の時間", sec_gap_oldest_same_price['gap_abs'] / 60)
        if sec_gap_oldest_same_price['gap_abs'] / 60 >= 90:
            # 90分以上の場合は、山検証の対象
            fr = result_same_price_list[0]['i']  # f はfromを示す（短く書く変数化）
            t = result_same_price_list[-1]['i']  # t はtoを示す（短く書く変数化）
            sandwiched_peaks = peaks[fr: t + 1]  # 間のピークス（両方の方向）
            sandwiched_peaks_oppo_peak = [d for d in sandwiched_peaks if
                                        d["direction"] == target_peak['direction'] * -1]
            # gene.print_arr(sandwiched_peaks)
            # print("逆サイドのみ")
            # gene.print_arr(sandwiched_peaks_oppo_peak)

            # 最大値（逆サイドの方向が1の場合。-1の場合は最小値）は？
            if target_peak['direction'] * -1 == 1:
                far_item = max(sandwiched_peaks_oppo_peak, key=lambda x: x["peak"])
            else:
                far_item = min(sandwiched_peaks_oppo_peak, key=lambda x: x["peak"])
            t_gap = abs(far_item['peak'] - target_peak['peak'])
            # print("対象は", far_item)
            # print(t_gap)
            # print(peaks_class.recent_fluctuation_range, peaks_class.recent_fluctuation_range * 0.7)
            if t_gap >= peaks_class.recent_fluctuation_range * 0.7:  # 最大の7割以上ある山が形成されている場合
                print("☆☆戻ると判定 3個", t_gap / peaks_class.recent_fluctuation_range)
                take_position = True
    else:
        # 3個以上の場合は結構突破している・・・？
        pass

    # スキップでも検証
    # print("  SKIPバージョン")
    skip_ans = cal_big_mountain_skip(peaks_class)
    # print("回答")
    # print(skip_ans['take_position_flag'])
    # print("  ↑")

    # Peakの強度の確認
    ps_group = cpk.judge_peak_is_belong_peak_group(peaks, target_peak)
    print("↑Peakが最大軍（最小群）かどうか")

    # ■■オーダーの設定
    # 初期値の設定
    exe_orders = []  # 返却用
    # オーダー調整用
    if take_position:
        tk.line_send("ポジションするよ")
    for_history_class = classPosition.order_information("test", "test", False)  # 履歴参照用
    latest_plu = for_history_class.history_plus_minus[-1]  # コード短縮化のための変数化
    print("  直近の勝敗pips", latest_plu)
    tp_up_border_minus = -0.045
    if latest_plu == 0:
        print(" 初回(本番)かAnalysisでのTP調整執行⇒特に何もしない（TPの設定等は行う）")
        # 通常環境の場合
        tp_range = 0.5
        lc_change_type = 1
    else:
        if latest_plu <= tp_up_border_minus:
            print("  マイナスが大きいため、取り返し調整（TPを短縮し、確実なプラスを狙いに行く）", latest_plu * 0.8)
            # tp_range = tp_up_border_minus  # とりあえずそこそこをTPにする場合
            tp_range = abs(latest_plu * 0.8)  # 負け分をそのままTPにする場合
            lc_change_type = 0  # LCchangeの設定なし
        else:
            # 直近がプラスの場合プラスの場合、普通。
            print("  マイナスが大きいため、取り返し調整（TPを短縮し、確実なプラスを狙いに行く）")
            tp_range = 0.5
            lc_change_type = 1  # LCchangeの設定なし


    # オーダーの作成
    if take_position:
        # オーダーありの場合
        peaks = peaks_class.peaks_original
        # 最大LCの調整
        target_price = peaks_class.latest_peak_price + (peaks[0]['direction'] * 0.024)
        lc_price = OCreate.cal_lc_price_from_line_and_margin(peaks[1]['latest_wick_peak_price'], 0.03, peaks[0]['direction'])
        gap = abs(lc_price-target_price)
        re_lc_range = gene.cal_at_most(0.09, gap)
        # print(peaks_class.df_r_original.iloc[1])
        print("gapはこれです", gap, "target_price:", target_price, "deci_price:", peaks_class.df_r_original.iloc[1]['close'])
        base_order_dic = {
            "target": target_price,
            "type": "STOP",
            "expected_direction": peaks[0]['direction'],
            "tp": tp_range,  # 短期では0.15でもOK.ただ長期だと、マイナスの平均が0.114のためマイナスの数が多くなる
            "lc": OCreate.cal_lc_price_from_line_and_margin(peaks[1]['latest_wick_peak_price'], 0.03, peaks[0]['direction']),  # 0.06,
            # "lc": 0.15,
            # "lc": 0.04,
            'priority': 3,
            "decision_time": peaks_class.df_r_original.iloc[0]['time_jp'],
            "decision_price": peaks_class.df_r_original.iloc[1]['close'],
            "order_timeout_min": 20,
            "lc_change_type": lc_change_type,
            "name": "山" + comment + str(len(result_same_price_list)) + "SKIP:" + str(skip_ans['take_position_flag'])
        }
        base_order_class = OCreate.OrderCreateClass(base_order_dic)  # オーダー生成
        # gene.print_json(base_order_class.finalized_order_without_lc_change)  # 表示

        # オーダーの修正と、場合によって追加オーダー設定
        lc_max = 0.15
        lc_change_after = 0.075
        if base_order_class.finalized_order['lc_range'] >= lc_max:
            print("LCが大きいため再オーダー設定")
            # オーダー修正（LC短縮）
            base_order_dic['lc'] = lc_change_after
            base_order_dic['name'] = base_order_dic['name'] + "LC大で修正_"
            base_order_class = OCreate.OrderCreateClass(base_order_dic)  # オーダー生成（というか作り直し）
            # gene.print_json(base_order_class.finalized_order_without_lc_change)  # 表示
            exe_orders.append(base_order_class.finalized_order)

            # 追加オーダー　：　少し下から用（Break方向）
            print("追加オーダー")
            peaks = peaks_class.peaks_original
            # Breakしない方向用
            base_order_dic = {
                "target": OCreate.cal_lc_price_from_line_and_margin(peaks[1]['latest_wick_peak_price'], 0.03,
                                                                    peaks[0]['direction']),
                "type": "LIMIT",
                "expected_direction": peaks[0]['direction'],
                "tp": 0.50,
                # "lc": OCreate.cal_lc_price_from_line_and_margin(peaks[1]['latest_wick_peak_price'], 0.03, peaks[0]['direction']),  # 0.06,
                "lc": 0.025,
                'priority': 3,
                "decision_time": peaks_class.df_r_original.iloc[0]['time_jp'],
                "decision_price": peaks_class.df_r_original.iloc[1]['close'],
                "order_timeout_min": 35,
                "lc_change_type": 2,
                "name": "追加オーダー"
            }
            # break方向の場合
            # base_order_dic = {
            #     "target": OCreate.cal_lc_price_from_line_and_margin(peaks[1]['latest_wick_peak_price'], 0.04,
            #                                                         peaks[0]['direction']),
            #     "type": "STOP",
            #     # "expected_direction": peaks[0]['direction'] * -1,  # Break
            #     "expected_direction": peaks[0]['direction'],  #
            #     "tp": 0.20,
            #     # "lc": OCreate.cal_lc_price_from_line_and_margin(peaks[1]['latest_wick_peak_price'], 0.03, peaks[0]['direction']),  # 0.06,
            #     "lc": 0.03,
            #     'priority': 3,
            #     "decision_time": peaks_class.df_r_original.iloc[0]['time_jp'],
            #     "decision_price": peaks_class.df_r_original.iloc[1]['close'],
            #     "order_timeout_min": 35,
            #     "lc_change_type": 2,
            #     "name": "追加オーダー"
            # }
            base_order_class = OCreate.OrderCreateClass(base_order_dic)
            # gene.print_json(base_order_class.finalized_order_without_lc_change)  # 表示
            exe_orders.append(base_order_class.finalized_order)
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
            if item['peak'] > target_peak['peak'] + same_price_range:
                # ターゲットピークを越えている場合(UpperLineで、上側に突き抜け）、NG
                break_peaks.append({"i": i, "item": item})
        else:
            if item['peak'] < target_peak['peak'] - same_price_range:
                # ターゲットピークを越えている場合（lowerLineで下に突き抜け）、NG
                break_peaks.append({"i": i, "item": item})

        # ■判定１　全ての近い価格を取得
        body_gap_abs = abs(t['peak'] - item['peak'])
        if abs(item['latest_wick_peak_price'] - item['peak']) >= same_price_range:
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
