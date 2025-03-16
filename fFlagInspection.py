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


def make_same_price_list_from_target_price(target_price, target_dir, peaks_all, same_price_range, is_recall):
    """
    target_dir方向（1の場合は上側、-1の場合は下側）のピーク値について以下を調査する
    target_priceで指定された価格と近い価格(same_price_rangeの幅以内)にあるピークを検出する。
    検討の上、一つ目の該当するピークが発見された場合、それをtarget_priceに置き換えで再帰する（ただし一回のみ。is_recallでコントロール）

    返却値
    """

    s4 = "    "
    s6 = "      "
    # print(s4, "同価格リスト関数", is_recall)
    # ■通貨等に依存する数字
    dependence_same_price_range = same_price_range  # 0.027ガベスト

    # ■各初期値
    counter = 0  # 何回同等の値が出現したかを把握する
    depth_point_gap = 0  # 今のピークと一番離れている値、かつ、逆方向のポイント（同価格発見のタイミングでリセット）
    depth_point = 0
    depth_point_time = 0
    depth_break_count = depth_fit_count = 0
    near_point_gap = 100  # 同価格ではないが、一番近い値、かつ、同方向のポイント(同価格を発見のタイミングでリセットされる）
    near_point = 0
    near_point_time = 0
    near_break_count = near_fit_count = 0
    same_price_list = []
    start_adjuster = 0
    between_peaks_num = start_adjuster  # 間に何個のピークがあったか。予測の場合は０

    # peakの並び替えを実施（テスト中）
    peaks_all_for_loop = peaks_all  # テストの時にコメントアウトしやすいように。。
    # if target_dir == 1:
    #     # 求める方向が上側のピークLineであれば、降順
    #     peaks_all_for_loop = sorted(peaks_all, key=lambda x: x["peak"], reverse=True)
    # else:
    #     # 求める方向が下側のピークLineであれば、昇順
    #     peaks_all_for_loop = sorted(peaks_all, key=lambda x: x["peak"])

    # 返却値
    return_dic = {
        "same_price_list": [],
        "strength_info": {"line_strength": 0},
    }

    for i, item in enumerate(peaks_all_for_loop):
        # 判定を行う
        # print(s6, " 判定", item['time'], target_price - dependence_same_price_range, "<", item['peak'], "<=",
        # target_price + dependence_same_price_range, item['direction'],
        # target_price - dependence_same_price_range <= item['peak'] <= target_price + dependence_same_price_range)
        this_peak_price_info = {
            "time": item['time'],
            "peak": item['peak'],
            "same_dir": True,  # これは直後で上書きする
            "direction": target_dir,
            "count_foot_gap": i,
            "depth_point_gap": round(depth_point_gap, 3),
            'depth_point': depth_point,
            "depth_point_time": depth_point_time,
            "depth_break_count": depth_break_count,
            "depth_fit_count": depth_fit_count,
            "near_point_gap": round(near_point_gap, 3),
            "near_point": near_point,
            "near_point_time": near_point_time,
            'near_break_count': near_break_count,
            'near_fit_count': near_fit_count,
            "between_peaks_num": between_peaks_num,
            "i": i,  # 何個目か
            "peak_strength": item['peak_strength']  # 最終日の場合のみ後で上書きされる
        }

        # 最後尾のPeakを参考用として付属させる場合(本当は使いたいが、いったん機能削除）
        add_oldest_peak = False
        if add_oldest_peak and i == len(peaks_all_for_loop) - 1 and len(same_price_list) != 0:
            # 最後尾の場合、痕跡として追加する。ただし、何か情報がある場合のみ追加する（何もない場合は０で返したいため）
            this_peak_price_info['same_dir'] = False  # 一部上書き
            this_peak_price_info['peak_strength'] = 0  # 一部上書き
            same_price_list.append(this_peak_price_info)
            break  # 重複して登録しないようにループ終了（同一価格を見逃すが、最後の時点で遠い話なので無視する）

        # 実際のループの中身↓
        if target_price - dependence_same_price_range <= item['peak'] <= target_price + dependence_same_price_range:
            # ■同価格のピークがあった場合
            if counter == 0:
                if not is_recall:
                    # (recall(2個目以上の対象)の場合は、基準であるtargetPrice変更しない）
                    # 今回のtargetPriceで最初の発見（最低値か最高値）の場合、それにtargetPriceを合わせに行く(それ基準で近い物を探すため）
                    # (再起呼び出しされている場合は、ここはやらずに結果を返却するのみ)
                    # print(s6, "target 変更 ", target_price, " ⇒", item['peak'], dependence_same_price_range)
                    recall_result = make_same_price_list_from_target_price(item['peak'], target_dir, peaks_all,
                                                                           same_price_range, True)
                    return recall_result
            # 同一価格のピークの情報を取得する
            counter += 1
            # 方向に関する判定
            if item['direction'] == target_dir:
                # print("　　　　同方向の近似ピーク（≒ダブルピークの素）", item['time'], near_point_gap)
                this_peak_price_info['same_dir'] = True  # 一部上書き
                same_price_list.append(this_peak_price_info)
                # same_price_list.append({"time": item['time'],
                #                   "peak": item['peak'],
                #                   "same_dir": True,  # 同じ方向のピークかどうか
                #                   "direction": target_dir,
                #                   "count_foot_gap": i,
                #                   "depth_point_gap": round(depth_point_gap, 3),
                #                   'depth_point': depth_point,
                #                   "depth_point_time": depth_point_time,
                #                   "depth_break_count": depth_break_count,
                #                   "depth_fit_count": depth_fit_count,
                #                   "near_point_gap": round(near_point_gap, 3),
                #                   "near_point": near_point,
                #                   "near_point_time": near_point_time,
                #                   'near_break_count': near_break_count,
                #                   'near_fit_count': near_fit_count,
                #                   "between_peaks_num": between_peaks_num,
                #                   "i": i,  # 何個目か
                #                   "peak_strength": item['peak_strength']
                #                   })
                # 通過したピーク情報を初期化する
                near_point_gap = 100
                near_break_count = near_fit_count = depth_break_count = depth_fit_count = depth_point_gap = 0
                between_peaks_num = start_adjuster  # 初期値は1のため注意

        else:
            # ■同価格のピークではなかったの場合、通過するが記録は残す。
            between_peaks_num += 1
            # 条件分岐
            peak_gap = (target_price - item['peak']) * target_dir
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
                    depth_break_count += 1  # マイナスというより、LINEを突破している位置にあるカウント
                else:
                    depth_fit_count += 1

            if item['direction'] == target_dir:
                # 同じピークの場合→Nearの方　ニアの方の深さの値を取得する
                # print("     TIME", item['time'])
                if peak_gap < near_point_gap:
                    # 最も近い価格を超える（かつ逆方向）場合
                    near_point_gap = peak_gap
                    near_point = item['peak']
                    near_point_time = item['time']
                # マイナスプラスをカウントする
                # print("     nearPointGap", peak_gap, item['time'])
                if peak_gap <= 0:
                    near_break_count += 1
                else:
                    near_fit_count += 1

    # リスト完成後の処理（並び替えや、強度の算出）
    if len(same_price_list) == 0:
        # 同一価格が存在しない場合、何もしない
        pass
    else:
        # 同一価格が存在する場合、強度を算出しておく
        same_price_list = sorted(same_price_list, key=lambda x: x["time"], reverse=True)  # 念のため時間順に並び替え
        strength_info = cal_strength_of_same_price_list(same_price_list, peaks_all, target_price, target_dir)
        return_dic['same_price_list'] = same_price_list  # 返却値にセット
        return_dic['strength_info'] = strength_info  # 返却値にセット

    return return_dic


def cal_strength_of_same_price_list(same_price_list, peaks, base_price, latest_direction):
    """
    ラインの強度を判定する。
    ・引数は同じ価格のリスト（同価格配列リストと、同価格情報）が、形状による強度判定には必要。
    ・同じ価格のリストの最後尾には、必ずstrength０の最後の値が付いてくる（同価格ではないが、調査期間の最後を示すもの）
    ・価格の高さ（一番上か下か）を検証するために、Peakが必要。（形状だけでなく、周辺の状況から高さを求める）
    ・target_price以降の引数は、返却値を整えるためのもの（引っ越し前の関数の名残。。）
    peakの扱い方
    ⇒このSamePriceListのBasePriceがPeaksの中で、どの高さにあるか（一番上の抵抗性なのか？等）を計算するために必要。
    """

    dependence_allowed_range_max_price = 0.04
    s4 = "   "
    s5 = "      "
    print(s5, "［JudgeLineStrength関数]")
    # ■リターン値や、各初期値の設定
    # 各初期値
    minus_counter = 0  # 初期
    len_of_list = len(same_price_list)  # リストの量
    # リターン値の初期設定（一部Listが０の場合に影響するため、この時点の身変数を利用）
    return_dic = {  # take_position_flagの返却は必須。Trueの場合注文情報が必要。
        "line_strength": 0,  # 検証では0は飛ばされてしまう。履歴のために飛ばしたくないため、0以外にしておく
        "line_position_strength": 0,  # 引数peakの中で、このsamepricelistの価格帯が一番上か。１がトップかボトム。それ以外０ 。
        "priority": 0,  # 基本はLineStrengthの写し。ただし別関数で、フラッグ形状の場合は２が上書きされる
        "line_on_num": 0,
        "same_time_latest": 0,
        "peak_strength_ave": 0,
        "remark": "",  # 備考コメントが入る
    }

    # ■検証処理
    # ピークの強さの平均を求める（スキップ仕様にすると、あんまり関係ないかも・・・？）
    if len_of_list == 0:
        # ★★★リストが０この場合は、その時点で終了★★★
        return return_dic

    # この時点で入力できるリターン値の設定
    return_dic['peak_strength_ave'] = sum([item['peak_strength'] for item in same_price_list]) / len_of_list
    return_dic["line_on_num"] = len_of_list
    return_dic["same_time_latest"] = same_price_list[0]['time']
    # 調査期間すべてを通じて、最上位（または最下位）のLINEかを確認する。 0の場合(LINE越が）通算通じて強いLine
    return_dic['all_range_strong_line'] = sum(item['near_break_count'] for item in same_price_list)

    # ■BasePriceがPeaksの中の高さのどこにいるのかを確かめる（一番上の場合、LinePositionStrength＝１とする。）
    if latest_direction == -1:
        # 直近が下方向の場合、下側から確認している（下のLineが最低値かどうかの判定）
        min_index, min_peak = min(enumerate(peaks[:]), key=lambda x: x[1]["peak"])
        if min_peak['peak'] - dependence_allowed_range_max_price > base_price:  # もともと＋だったが、－に修正した
            # 最低値の範囲内であれば（0.04は余裕を持っている。同価格のスキップが0.05なので、それ以下に設定している）
            return_dic['line_position_strength'] = 1  # 調査期間では最高価格のLine
        else:
            return_dic['line_position_strength'] = 0  # 最高価格ではない
    else:
        # 直近が上方向の場合、上側から確認している（上のLineが最高値かどうかの判定）
        max_index, max_peak = max(enumerate(peaks[:]), key=lambda x: x[1]["peak"])
        if max_peak['peak'] + dependence_allowed_range_max_price < base_price:  # もともと－だったが、＋に修正し
            # 最高値の範囲（最低値より少し下よりも上）であれば
            return_dic['line_position_strength'] = 1  # 調査期間では最低価格のLine
        else:
            return_dic['line_position_strength'] = 0  # 最低価格ではない

    # ■同一価格が存在する場合(直近の同一価格、それ以前の同一価格（複数の可能性もあり）について調査を行う）
    if len_of_list == 1:
        # ■■同一価格が一つの場合：(シンプルダブルトップ　or カルデラ等）
        info = same_price_list[0]  # 同一価格が１つだけが成立（その情報を取得する）
        between_peaks_num = info['between_peaks_num']  # 可読性向上（直近から、当該ピークまでのピーク数）
        if between_peaks_num == 2:
            # シンプルなシングルダブルトップ（同一価格二つ　And その間のピークスが二つ）
            return_dic['line_strength'] = 0.75
            return_dic["remark"] = "単DoubleTop"
        elif between_peaks_num == 4:
            # シンプルなカルデラ形状
            return_dic['line_strength'] = 0.8
            return_dic["remark"] = "単カルデラ"
        elif between_peaks_num > 4:
            # nearマイナスの数が、nearの数の半分以上の場合
            all_near_num = between_peaks_num / 2 - 1  # nearの数はこう求める
            minus_ratio = info['near_break_count'] / all_near_num
            # print(s6, "参考：マイナス比率", minus_ratio, info['near_break_count'], all_near_num, between_peaks_num)
            if minus_ratio >= 0.4:
                return_dic['line_strength'] = 0.1
                return_dic["remark"] = "単マイナス比率大"
            elif minus_ratio > 0:
                return_dic['line_strength'] = 0.5
                return_dic["remark"] = "単マイナス半分"
            else:
                return_dic['line_strength'] = 0.9
                return_dic["remark"] = "単強め"
        else:
            # 過去最高店で、他にない（あるの・・？）
            return_dic['line_strength'] = 0.01
            return_dic["remark"] = "最高単一ポイント（要チェック）"
    # elif len_of_list == 2:
    #     # ■■同一価格が２個ある場合
    #     for i in range(len_of_list):
    #         if same_price_list[i]['near_point_gap'] < 0:
    #             minus_counter += 1  # マイナスはLINEを超えた回数
    #     if minus_counter > len_of_list * 0.5:
    #         # LINE越えが過半数の場合、LINEの信頼度つぃては高くない
    #         line_strength = 0.1
    #         # print(s6, "複数時　弱強度", minus_counter, len(same_list))
    #     elif minus_counter >= 1:
    #         line_strength = 0.3
    #         # print(s6, "複数時　１つ以上LINE越えあり", minus_counter)
    #     else:
    #         # LINE越えがない為、LINEの信頼度が比較的高い
    #         line_strength = 1
    #         # print(s6, "複数時　強強度", minus_counter, len(same_list))
    elif len_of_list >= 2:
        # ■■同一価格が2個以上ある場合 (もともとフラッグを探すのは3個以上だったが、2個でもある場合もあったため、2個以上に変更）
        # ■■■まず、シンプルなトップの形状のみで判断
        for i in range(len_of_list):  # この比較はlen_of_same_price_listのため、最後の調査終了用peakは入らない
            if same_price_list[i]['near_point_gap'] < 0:
                minus_counter += 1  # マイナスはLINEを超えた回数
        # ↓↓保存用
        if minus_counter > len_of_list * 0.5:
            # LINE越えが過半数の場合、LINEの信頼度つぃては高くない
            return_dic['line_strength'] = 0.1
            return_dic["remark"] = "複で越多め"
            # print(s6, "複数時　弱強度", minus_counter, len(same_list))
        elif minus_counter >= 1:
            return_dic['line_strength'] = 0.3
            return_dic["remark"] = "複でやや越多め"
            # print(s6, "複数時　１つ以上LINE越えあり", minus_counter)
        else:
            # LINE越えがない為、LINEの信頼度が比較的高い
            if len_of_list == 2:
                return_dic['line_strength'] = 0.9
                return_dic["remark"] = "複強め（2個のみ）"
            else:
                return_dic['line_strength'] = 1
                return_dic["remark"] = "複強め"
            # print(s6, "複数時　強強度", minus_counter, len(same_list))

    # ただし同価格LINEをなすピークが２個（最後尾を除いて）で、かつ、その二つがくっついている（４足分以内に存在）の場合、NGとする
    if len_of_list == 2:
        time_gap = gene.cal_str_time_gap(same_price_list[0]['time'], same_price_list[1]['time'])['gap_abs']
        time_gap_min = time_gap / 60
        if time_gap_min <= 15:
            return_dic['line_strength'] = 0.1
            return_dic["remark"] = return_dic["remark"] + "だったが、SamePrice幅狭すぎでNG"

    return return_dic


def yobi_cal_strength_of_same_price_list(same_price_list, peaks, base_price, latest_direction):
    """
    ラインの強度を判定する。
    ・引数は同じ価格のリスト（同価格配列リストと、同価格情報）が、形状による強度判定には必要。
    ・同じ価格のリストの最後尾には、必ずstrength０の最後の値が付いてくる（同価格ではないが、調査期間の最後を示すもの）
    ・価格の高さ（一番上か下か）を検証するために、Peakが必要。（形状だけでなく、周辺の状況から高さを求める）
    ・target_price以降の引数は、返却値を整えるためのもの（引っ越し前の関数の名残。。）
    peakの扱い方
    ⇒このSamePriceListのBasePriceがPeaksの中で、どの高さにあるか（一番上の抵抗性なのか？等）を計算するために必要。
    """

    dependence_allowed_range_max_price = 0.04
    s4 = "   "
    s6 = "      　"
    print(s4, "［JudgeLineStrength関数]")
    # ■リターン値や、各初期値の設定
    minus_counter = 0  # 初期
    line_strength = 0.01
    line_position_strength = 0  # 1の場合は、一番上か一番下を示す（一番下でも-1としない）
    len_of_same_price_list = len(same_price_list)  # 最後に調査最終時刻を示すデータがあるため、実データは-1
    # 調査期間すべてを通じて、最上位（または最下位）のLINEかを確認する。
    all_range_strong_line = sum(item['near_break_count'] for item in same_price_list)  # 0の場合(LINE越が）通算通じて強いLine
    remark = ""
    # 平均値はall_range_strong_lineが０の場合、除算エラーとなるため、ここで計算しておく（０除算とならないような仕組み）
    peak_strength_ave = 0 if len_of_same_price_list == 0 else sum(
        [item['peak_strength'] for item in same_price_list[:-1]]) / len_of_same_price_list

    return_dic = {  # take_position_flagの返却は必須。Trueの場合注文情報が必要。
        "line_strength": line_strength,  # 検証では0は飛ばされてしまう。履歴のために飛ばしたくないため、0以外にしておく
        "line_position_strength": line_position_strength,  # 引数peakの中で、このsamepricelistの価格帯が一番上か。１がトップかボトム。それ以外０ 。
        "priority": 0,  # 基本はLineStrengthの写し。ただし別関数で、フラッグ形状の場合は２が上書きされる
        "line_on_num": 0,
        "same_time_latest": 0,
        "peak_strength_ave": peak_strength_ave,  # itemの最後尾は、peakStrength0の調査期間の最後尾を表すもののため、除外された計算結果
        "remark": "",  # 備考コメントが入る
        "same_price_list": []
    }
    # print(s6, AVE平均値", peak_strength_ave)
    # print(s6, 通算でのトップか？", all_range_strong_line)

    # ■調査不要の場合は即時リターンする
    if len_of_same_price_list == 0:
        # 同価格がない場合、ストレングスをミニマムで返却する
        return return_dic

    # ■BasePriceがPeaksの中の高さのどこにいるのかを確かめる（一番上の場合、LinePositionStrength＝１とする。）
    if latest_direction == -1:
        # 直近が下方向の場合、下側から確認している（下のLineが最低値かどうかの判定）
        min_index, min_peak = min(enumerate(peaks[:]), key=lambda x: x[1]["peak"])
        if min_peak['peak'] + dependence_allowed_range_max_price > base_price:
            # 最低値の範囲内であれば（0.04は余裕を持っている。同価格のスキップが0.05なので、それ以下に設定している）
            line_position_strength = 1
            print(s4, " 最低Line(", base_price, ")", )
        else:
            line_position_strength = 0
            print(s4, " 最低ではないLine(", base_price, ")", )
    else:
        # 直近が上方向の場合、上側から確認している（上のLineが最高値かどうかの判定）
        max_index, max_peak = max(enumerate(peaks[:]), key=lambda x: x[1]["peak"])
        if max_peak['peak'] - dependence_allowed_range_max_price < base_price:
            # 最高値の範囲（最低値より少し下よりも上）であれば
            line_position_strength = 1
            print(s4, " 最高Line(", base_price, ")")
        else:
            line_position_strength = 0
            print(s4, " 最高ではないLine(", base_price, ")")

    # ■同一価格が存在する場合(直近の同一価格、それ以前の同一価格（複数の可能性もあり）について調査を行う）
    # print(len_of_same_price_list)
    if len_of_same_price_list == 1:
        # ■■同一価格が一つの場合：(シンプルダブルトップ　or カルデラ等）
        info = same_price_list[0]  # 同一価格が１つだけが成立（その情報を取得する）
        between_peaks_num = info['between_peaks_num']  # 可読性向上（直近から、当該ピークまでのピーク数）
        if between_peaks_num == 2:
            # シンプルなシングルダブルトップ（同一価格二つ　And その間のピークスが二つ）
            line_strength = 0.75  # 2
            remark = "単DoubleTop"
        elif between_peaks_num == 4:
            # シンプルなカルデラ形状
            line_strength = 0.8  # 3
            remark = "単カルデラ"
        elif between_peaks_num > 4:
            # nearマイナスの数が、nearの数の半分以上の場合
            all_near_num = between_peaks_num / 2 - 1  # nearの数はこう求める
            minus_ratio = info['near_break_count'] / all_near_num
            # print(s6, "参考：マイナス比率", minus_ratio, info['near_break_count'], all_near_num, between_peaks_num)
            if minus_ratio >= 0.4:
                line_strength = 0.1  #  0.5
                remark = "単マイナス比率大"
            elif minus_ratio > 0:
                line_strength = 0.5  #1.5
                remark = "単マイナス半分"
            else:
                line_strength = 0.9  # 3
                remark = "単強め"
        else:
            # 過去最高店で、他にない（あるの・・？）
            line_strength = 0.01
            remark = "最高単一ポイント（要チェック）"
    # elif len_of_same_price_list == 2:
    #     # ■■同一価格が２個ある場合
    #     for i in range(len_of_same_price_list):
    #         if same_price_list[i]['near_point_gap'] < 0:
    #             minus_counter += 1  # マイナスはLINEを超えた回数
    #     if minus_counter > len_of_same_price_list * 0.5:
    #         # LINE越えが過半数の場合、LINEの信頼度つぃては高くない
    #         line_strength = 0.1
    #         # print(s6, "複数時　弱強度", minus_counter, len(same_list))
    #     elif minus_counter >= 1:
    #         line_strength = 0.3
    #         # print(s6, "複数時　１つ以上LINE越えあり", minus_counter)
    #     else:
    #         # LINE越えがない為、LINEの信頼度が比較的高い
    #         line_strength = 1
    #         # print(s6, "複数時　強強度", minus_counter, len(same_list))
    elif len_of_same_price_list >= 2:
        # ■■同一価格が2個以上ある場合 (もともとフラッグを探すのは3個以上だったが、2個でもある場合もあったため、2個以上に変更）
        # ■■■まず、シンプルなトップの形状のみで判断
        for i in range(len_of_same_price_list):  # この比較はlen_of_same_price_listのため、最後の調査終了用peakは入らない
            if same_price_list[i]['near_point_gap'] < 0:
                minus_counter += 1  # マイナスはLINEを超えた回数
        # ↓↓保存用
        if minus_counter > len_of_same_price_list * 0.5:
            # LINE越えが過半数の場合、LINEの信頼度つぃては高くない
            line_strength = 0.1
            remark = "複で越多め"
            # print(s6, "複数時　弱強度", minus_counter, len(same_list))
        elif minus_counter >= 1:
            line_strength = 0.3
            remark = "複でやや越多め"
            # print(s6, "複数時　１つ以上LINE越えあり", minus_counter)
        # ↑↑保存用
        # 5個中1個(0.25)、4個中1個(
        # ↓↓ここから新
        # if minus_counter/len_of_same_price_list > 0.25:  # 0.25以上（例：5個中1個はセーフ、）の場合は越が多いと判断　
        #     # LINE越えが過半数の場合、LINEの信頼度つぃては高くない
        #     line_strength = 0.1
        #     remark = "複で越多め"
        #     print(s6, "複数時　弱強度", minus_counter)
        # ↑↑ここまで新
        else:
            # LINE越えがない為、LINEの信頼度が比較的高い
            if len_of_same_price_list == 2:
                line_strength = 0.9
                remark = "複強め（2個のみ）"
            else:
                line_strength = 1  # 最も強い
                remark = "複強め"
            # print(s6, "複数時　強強度", minus_counter, len(same_list))

    # ただし同価格LINEをなすピークが２個（最後尾を除いて）で、かつ、その二つがくっついている（４足分以内に存在）の場合、NGとする
    if len_of_same_price_list == 2:
        time_gap = gene.cal_str_time_gap(same_price_list[0]['time'], same_price_list[1]['time'])['gap_abs']
        time_gap_min = time_gap / 60
        if time_gap_min <= 15:
            line_strength = 0.1
            remark = remark + "だったが、SamePrice幅狭すぎでNG"

    # 当面の検証用
    if len_of_same_price_list >= 4:
        print("４個以上のLINE形成ポイント有！！！！", base_price)
        tk.line_send("４個以上のLINE形成ポイント有！！！！", base_price)

    # print("テスト用", remark)
    # 返却値の整理
    return_dic["line_strength"] = line_strength
    return_dic["priority"] = line_strength
    return_dic["line_on_num"] = len_of_same_price_list
    return_dic['line_position_strength'] = line_position_strength
    return_dic["same_time_latest"] = 0 if len(same_price_list) == 0 else same_price_list[0]['time']
    return_dic['all_range_strong_line'] = all_range_strong_line  # 0が強い(Break回数が０）
    return_dic["remark"] = remark
    return return_dic


def tilt_cal(peaks, target_direction):
    """
    旗の形状を探索するための、サポート関数
    peaks: ピークス
    num: ピークスの中で、直近num個分の中でフラッグ形状を判定する
    remark: コメント
    返り値は、成立しているかどうかのBoolean
    """
    print("    ", "【傾斜調査関数】")
    # ■関数事前準備
    remark = "フラッグ不成立"
    s7 = "      "

    # ■■情報の整理と取得（関数の頭には必須）
    # #直接のテストで　argsが渡される場合
    # fixed_information = cf.information_fix(dic_args)  # DFとPeaksが必ず返却される
    # df_r = fixed_information['df_r']
    # peaks = fixed_information['peaks'][1:]
    # latest_direction = peaks[0]['direction']
    # 実運用でPeak渡される場合
    peaks = peak_inspection.change_peaks_with_hard_skip(peaks)  # HARDスキップの場合
    latest_direction = peaks[0]['direction']

    # 返却値の基本
    return_base = {
        "tilt_line_level": False,
        "remark": "",
    }
    # 足や通貨によって変わるもの
    dependence_y_change_min = 0.015
    dependence_on_line_margin = 0.027
    dependence_near_line_margin_at_least = 0.054
    dependence_lc_range = 0.01
    dependence_max_lc_range = 0.1

    # ■TILTの判定を行う
    direction_integrity = True  # 方向性が一致しているかどうか（下側は上昇、上側が下降がここでは正とする）
    d = target_direction  # １の場合は上側、-1の場合は下側のピークスを対象として、調査をする
    each_line_info = []
    # for target_num in [5]:
    for target_num in range(4, 7):
        # num = i + 1  # iは０からスタートするため
        # ■■　傾きの有無を確認
        target_peaks = [item for item in peaks if item["direction"] == d]  # 利用するのは、Lower側
        target_peaks = target_peaks[:target_num]
        if d == 1:
            # 上方向（が下がってきているかを確認）の場合、Max値
            min_index, min_or_max_info = max(enumerate(target_peaks), key=lambda x: x[1]["peak"])  # サイズ感把握のために取得
        else:
            # 下方向（が上ってきているかを確認）の場合、Min値
            min_index, min_or_max_info = min(enumerate(target_peaks), key=lambda x: x[1]["peak"])  # サイズ感把握のために取得
        oldest_info = target_peaks[-1]
        # print(s7, "@調査するピークス", d, target_num)
        # for i, item_each in enumerate(target_peaks):
        #     print(s7, item_each['time'], "  ", item_each['peak'])
        print(s7, "先頭の情報", target_peaks[0]['peak'], target_peaks[0]['time'])
        # print(s7, "最後尾の情報", oldest_info['peak'], oldest_info['time'])
        y_change = target_peaks[0]['peak'] - oldest_info['peak']
        if abs(y_change) <= dependence_y_change_min:
            # print(s7, "傾きが少なすぎる")
            ans = {"tilt_line_level_each": 0,
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
                   "remark": "傾斜無し"
                   }
            each_line_info.append(ans)
            continue
        else:
            print(s7, "いい傾き")

        # ■■傾きがある場合、詳細を確認（OnやNear）
        # OLDESTの価格を原点として、直近Peaksへの直線の傾きを算出する　yの増加量(価格の差分)　/ xの増加量(時間の差分)
        x_change_sec = (gene.cal_at_least(0.0000001,
                                          gene.cal_str_time_gap(oldest_info['time'], target_peaks[0]['time'])[
                                              'gap_abs']))  # ０にならない最低値を設定する
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
            jd_y_max = tilt * a + dependence_on_line_margin
            jd_y_min = tilt * a + (dependence_on_line_margin * -1)
            if jd_y_max > b > jd_y_min:
                # print(s7, "　(ri)線上にあります", item['time'], jd_y_max, b, jd_y_min, jd_y_max > b > jd_y_min)
                on_line_num += 1
            else:
                # print(s7, "　(ri)線上にはありません", item['time'], jd_y_max, b, jd_y_min, jd_y_max > b > jd_y_min)
                pass

            # ■線の近くにあるか[判定]
            near_line_margin = abs(target_peaks[0]['peak'] - min_or_max_info['peak']) * 0.405  # * 0.405がちょうどよさそう
            near_line_margin = gene.cal_at_least(dependence_near_line_margin_at_least,
                                                 near_line_margin)  # 下側の下落、上側の上昇の場合、最小最大が逆になると０になる可能性がある
            # print(target_peaks[0]['time'], target_peaks[0]['peak'], min_or_max_info['time'], min_or_max_info['peak'])
            # print("MARGIN:", abs(target_peaks[0]['peak'] - min_or_max_info['peak']), near_line_margin)
            jd_y_max = tilt * a + near_line_margin
            jd_y_min = tilt * a + (near_line_margin * -1)
            if jd_y_max > b > jd_y_min:
                # print(s7, "　(ri)　線近くにあります", item['time'], jd_y_max, b, jd_y_min, jd_y_max > b > jd_y_min)
                near_line_num += 1
            else:
                # print(s7, "　(ri)　線近くにはありません", item['time'], jd_y_max, b, jd_y_min, jd_y_max > b > jd_y_min)
                pass
        # 集計結果
        # print(s7, "(ri)全部で", total_peaks_num, 'ピーク。線上：', on_line_num, "線近", near_line_num)
        # print(s7, "(ri)割合　線上:", on_line_num/total_peaks_num, "　線近:", near_line_num/total_peaks_num)
        on_line_ratio = round(on_line_num / total_peaks_num, 3)
        near_line_ratio = round(near_line_num / total_peaks_num, 3)
        # 最終判定
        tilt_pm = tilt / abs(tilt)  # tiltの方向を算出する（上側が下傾斜、下側の上傾斜の情報のみが必要）
        tilt_line_level_each = 0
        # print(s7, "調査側は", d, "傾き方向は", tilt_pm)
        if d == tilt_pm:
            # print(s7, "下側が下方向、上側が上方向に行っている（今回は収束と見たいため、不向き）")
            remark = "発散方向"
            direction_integrity = False  # 方向の整合性
        else:
            # 傾斜は合格、ピークスを包括できるかを確認
            # if on_line_ratio >= 0.55 and near_line_ratio >= 0.7:  # 0.35, 60
            # if on_line_ratio >= 0.35 and near_line_ratio >= 0.6:  # 緩いほう（従来の結果がよかった条件）
            if on_line_ratio > 0.5 and near_line_ratio >= 0.8:  # 結構完璧な形（両端の2個を含むため、4個の場合2個より大きくしないといけない）
                # print(s7, "強力な継続的な傾きとみなせる", on_line_ratio, near_line_ratio, "peak_num", total_peaks_num,
                #       "On", on_line_num, "Near", near_line_num)
                tilt_line_level_each = 1
                # remark = "継続した傾斜と判断"
                if tilt < 0:
                    remark = "上側下落(強)"
                else:
                    remark = "下側上昇(強)"
            elif on_line_ratio >= 0.35 and near_line_ratio >= 0.5:  # さらに緩いほう（2025/1/13 13/50を取得したいため）
                # print(s7, "継続的な傾きとみなせる", on_line_ratio, near_line_ratio, "peak_num", total_peaks_num, "On",
                #       on_line_num, "Near", near_line_num)
                tilt_line_level_each = 0.5
                # remark = "継続した傾斜と判断"
                if tilt < 0:
                    remark = "上側下落(弱)"
                else:
                    remark = "下側上昇(弱)"
                # print(s7, "継続した傾斜と判断", d)
            else:
                remark = "線上、線近くのどちらかが未達"
                # print(s7, "線上、線近くのどちらかが未達", on_line_ratio, near_line_ratio)

        # ■LC値の参考値を算出（対象のピーク群の中間値）
        total_peak = sum(item["peak"] for item in target_peaks)
        ave_peak_price = round(total_peak / len(target_peaks), 3)
        lc_margin = dependence_lc_range * latest_direction * -1
        ave_peak_price = ave_peak_price + lc_margin

        # ■累積(numごと）
        ans = {"tilt_line_level_each": tilt_line_level_each,
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
        each_line_info.append(ans)
        # ループここまで

    # ■情報を整理する（例えば3peak～5peaksの各直線で、複数の傾斜直線がある場合、傾斜直線成立としt、代表としてOldestな物を返却する)
    # gene.print_arr(each_line_info, 7)
    all_ans_num = len(each_line_info)
    # true_num = sum(item["tilt_line_level_each"] for item in each_line_info)  # tilt_line_level_eachがbooleanだったころ
    true_num = sum(1 for item in each_line_info if
                   item["tilt_line_level_each"] != 0)  # tilt_line_level_each = 0はTiltではない。それ以外がTrue同等
    max_tilt_line_level = max(item["tilt_line_level_each"] for item in each_line_info)
    print(s7, all_ans_num, true_num, true_num / all_ans_num)
    tilt_line_level = 0  # 初期化
    if true_num / all_ans_num >= 0.1:  # if true_num / all_ans_num >= 0.5:  # 0.5だと、従来取れていたものも取りこぼす(良くも悪くも)
        # print(s7, "@@斜面成立(", all_ans_num, "の内", true_num, "個の成立")
        tilt_line_level = max_tilt_line_level
    else:
        # 成立が認められない場合でも、Onlineが10割のものがあれば、採用する
        temp = next((item for item in each_line_info if item["on_line_ratio"] == 1), None)
        if temp and temp['direction_integrity']:
            # ある場合は、それの方向性の整合が取れているかを確認する
            tilt_line_level = max_tilt_line_level
            # print(s7, "@@斜面成立(", all_ans_num, "の内", true_num, "個の成立")
        else:
            # print(s7, "@@斜面不成立", all_ans_num, "の内", true_num, "個の成立", "onLine", temp)
            return return_base

    # ■成立している中で、一番比較ピークが多いもの、少ないものを抽出しておく
    first_item = next((item for item in each_line_info if item["tilt_line_level_each"]), None)  # 最もLatestなTiltTrue
    # oldest_item = next((item for item in reversed(each_line_info) if item["tilt_line_level_each"]), None)  # 最もOldestなTiltTrue
    oldest_item = max(
        (item for item in reversed(each_line_info) if item['tilt_line_level_each']),  # fが真の要素をフィルタ
        key=lambda x: x['y_change'],  # kが最大のものを取得
        default=None  # 空の場合はNoneを返す
    )
    # print(s7, "＠＠直近のアイテム", first_item)
    # print(s7, "＠＠最古のアイテム", oldest_item)

    # ■推奨のロスカット価格を集合から計算しておく
    # 最大でもLCRange換算で10pips以内したい
    now_price = peaks[0]['peak']
    temp_lc_price = oldest_item['lc_price']  # lcPriceは収束の中間点
    lc_range = temp_lc_price - now_price  # これがマイナス値の場合Directionは１、プラス値となる場合Directionは-1
    max_lc_range = dependence_max_lc_range
    if abs(lc_range) >= max_lc_range:
        # LCが大きすぎると判断される場合(10pips以上離れている）
        # lc_range = 0.1  # LCRnageを指定　←旧　これがコメントイン（←けどおかしい）
        if lc_range < 0:
            # LC_rangeがマイナス値　＝　Directionは１。その為、現在価格からマイナスするとLCPriceとなる
            lc_price = now_price - abs(max_lc_range)  # 旧 abs(lc_range)←でもおかしい
            # print("上限越えLC(RangeマイナスのためDirectionは１)⇒", lc_price)
        else:
            # LC_rangeがプラス値　＝　Directionは-1。その為、現在書くにプラスするとＬＣＰｒｉｃｅになる
            lc_price = now_price + abs(max_lc_range)  # 旧　abs(lc_range)←でもおかしい
            # print("上限越えLC(RangeプラスのためDirectionはー１)⇒", lc_price)
    else:
        # LCRangeが許容範囲内の場合、そのまま利用
        lc_price = temp_lc_price
    # print(s7, "LC(価格orRange）", lc_price)

    # ↓↓保存用（何かおかしいけど結果がよかったやつ)
    # now_price = peaks[0]['peak']
    # temp_lc_price = oldest_item['lc_price']  # lcPriceは収束の中間点
    # lc_range = temp_lc_price - now_price  # これがマイナス値の場合Directionは１、プラス値となる場合Directionは-1
    # max_lc_range = dependence_max_lc_range
    # if abs(lc_range) >= max_lc_range:
    #     # LCが大きすぎると判断される場合(10pips以上離れている）
    #     lc_range = dependence_max_lc_range  # LCRnageを指定　←旧　これがコメントイン（←けどおかしい）
    #     if lc_range < 0:
    #         # LC_rangeがマイナス値　＝　Directionは１。その為、現在価格からマイナスするとLCPriceとなる
    #         lc_price = now_price - abs(max_lc_range)  # 旧 abs(lc_range)←でもおかしい
    #     else:
    #         # LC_rangeがプラス値　＝　Directionは-1。その為、現在書くにプラスするとＬＣＰｒｉｃｅになる
    #         lc_price = now_price + abs(max_lc_range)  # 旧　abs(lc_range)←でもおかしい
    # else:
    #     # LCRangeが許容範囲内の場合、そのまま利用
    #     lc_price = temp_lc_price
    # print(s7, "LC(価格orRange）", lc_price)
    # ↑↑保存用ここまで

    # ■5個の時の成立があるかを確認する
    res5 = next((item for item in each_line_info if item.get("count") == 5), None)
    # print(s7, "latest=5のもの(過去成績が良かったもの)", res5)
    if res5['tilt_line_level_each']:
        strength = 1
    else:
        strength = 0.5

    # 個の直線に関する情報は、全てOldestを参照する(LCPriceも元はOld）
    merge_line_tilt_info = {
        "tilt_line_level": tilt_line_level,
        "tilt_list": each_line_info,
        "oldest_peak_info": oldest_item,
        "latest_peak_info": first_item,
        "lc_price": lc_price,  # 計算で大きすぎた場合、10pipsが入る
        "remark": oldest_item['remark'],  # 一番古いのを採用
        "strength": strength  # 過去一番精度がいいのはpeakが5個の時（5の時以外は、少し短めのLCとする）
    }
    return merge_line_tilt_info


def judge_flag_figure(peaks, target_direction, df_r):
    """
    フラッグ形状かどうかを判定する。
    df_r:調査用のデータフレーム
    peaks:元となるピークス。
    target_direction: この方向のピーク群が斜め上がり傾向になっているかを検証する（Upperが水平でLowerを検証したい場合、ここはー１が渡される）
    返り値は、成立しているかどうかのBoolean

    ロングとショートで今のところ実施している


    フラッグはLatest＝２の時の調査のみではない必要がある。その為以下のルールを設定
    ・ひとつ前の状態でフラッグが発生している場合（連続発生）、二回目は実施しない。（連続の場合は何回あっても初回のみが実現可能）
    ・Latest＝２の時になく、latest=3以降である場合は、何かおかしいためやめる（ただしいい影響がある可能性もあり）
    """
    s6 = "      "
    # print(s6, "抵抗線向きは", target_direction, "傾きを確認したいのは", target_direction * -1)
    flag_ans = False

    # ■Peaksの準備
    # ■■直近
    peaks = peak_inspection.change_peaks_with_hard_skip(peaks)

    # ■直近の傾斜の有無を確認する
    tilt_line_info = tilt_cal(peaks, target_direction * -1)
    # tilt_ansの中身： {"tilt_line_level","tilt_list","oldest_peak_info","latest_peak_info","lc_price","remark","strength"}

    # ■直近がOKの場合、一つ前の足基準で、調査を行う
    if tilt_line_info['tilt_line_level'] > 0:
        # ■■ひとつ前の足
        print(s6, "ひとつ前の足で成立を確認（斜面）")
        fixed_information_prev = cf.information_fix({"df_r": df_r[1:]})  # DFとPeaksが必ず返却される
        peaks_prev = fixed_information_prev['peaks']
        tilt_ans_prev = tilt_cal(peaks_prev, target_direction * -1)
        if tilt_ans_prev['tilt_line_level'] > 0 and (target_direction == peaks_prev[0]['direction']):
            # ひとつ前の状態でも成立し、かつ、向きも同じな場合
            print(s6, "二回目以降の成立")
            tilt_line_info['remark'] = tilt_line_info['remark'] + "(二回目以降)"
            is_first = False
        else:
            # ひとつ前の状態では成立がなかった場合
            print(s6, "初回の成立")
            is_first = True
    else:
        # 現状の傾きが不成立の場合はFalseを返却
        return {"tilt_line_level": 0}

    # print(tilt_line_info['oldest_peak_info'])

    return {
        "tilt_line_level": tilt_line_info['tilt_line_level'],
        "is_first": is_first,
        "lc_price": tilt_line_info['lc_price'],  # こっちのほうがlongよりLC幅が狭いので。いつかリスクを追う場合は、Longに？）
        "remark": tilt_line_info['remark'],
        "strength": tilt_line_info['strength'],
        "oldest_peak_info": tilt_line_info['oldest_peak_info'],
        "y_change": tilt_line_info['oldest_peak_info']['y_change']
    }


def get_max_time(entry):
    return max(item["time"] for item in entry["same_price_list"])


def analysis(dic_args):
    """
    引数はDFやピークスなど
    """

    # 表示時のインデント
    s4 = "    "
    s6 = "      "
    flag_flag = False
    print(s4, "■find_predict_line_based_latest関数")

    # ■足や通貨に依存するもの
    dependence_search_grid = 0.01
    dependence_search_skipper = 0.03
    dependence_line_close_border = 0.07
    dependence_line_close_border = 0.07

    # ■関数事前準備
    # ■■よく使う型

    # ■■返却値用
    #  リストの原型（これを上書きし、下のリストに追加していく）
    predict_line_info_list = []  # 実際に返却されるリスト
    #  返却値
    orders_and_evidence = {
        "take_position_flag": False,
        "line_base_info": {},
        "same_price_list": {},
        "strength_info": {},
        "flag_info": {}
    }

    # ■■情報の整理と取得（関数の頭には必須）
    peaksclass = cpk.PeaksClass(dic_args['df_r'])
    target_df = dic_args['df_r']
    peaks = peaksclass.skipped_peaks
    # fixed_information = cf.information_fix(dic_args)  # DFとPeaksが必ず返却される
    # target_df = fixed_information['df_r']
    # peaks = fixed_information['peaks']
    target_dir = peaks[0]['direction']  # Lineの方向 予測ではLatest。値が1の場合UpperLine（＝上値抵抗）
    grid = dependence_search_grid  # 調査の細かさ
    now_time = target_df.iloc[0]['time_jp']

    # ■動きの幅を検討する
    ms_ans = ms.cal_move_size(dic_args)
    same_price_range = float(ms_ans['inner_min_max_gap']) * 0.033  # 大体動き幅の３パーセントを許容範囲に
    same_price_range = gene.cal_at_least(0.015, same_price_range)

    # ■調査を開始
    # 条件を達成していない場合は実行せず
    if len(peaks) < 4:
        # ■ループの際、数が少ないとエラーの原因になる。３個切る場合ば終了（最低３個必要）
        return orders_and_evidence

    # ■各変数の設定（動的な値）
    # 調査価格範囲の設定
    min_max_search_range = 11
    max_index, max_peak_info_in_latest4 = max(enumerate(peaks[:min_max_search_range]), key=lambda x: x[1]["peak"])
    min_index, min_peak_info_in_latest4 = min(enumerate(peaks[:min_max_search_range]), key=lambda x: x[1]["peak"])
    if target_dir == 1:
        # latestが登り方向の場合
        search_max_price = max_peak_info_in_latest4['peak'] + grid  # 探索する最高値。基本こっちを利用
        search_min_price = peaks[0]['peak'] - grid  # 探索する最低値（念のための算出）
        target_price = search_max_price  # MAX側から調査（登りの場合、上から調査）。逆にする場合、search_min_price
    else:
        # latestが下り方向の場合
        search_max_price = peaks[0]['peak'] + grid  # 探索する最低値（念のための算出）
        search_min_price = min_peak_info_in_latest4['peak'] - grid  # 探索する最低値。基本こっちを利用。
        target_price = search_min_price  # + grid  # 下（Min）からスタート
    print(s4, "調査範囲:", search_min_price, "<=", target_price, "<=", search_max_price, "同価格許容価格",
          same_price_range)
    print(s4, "　  LineBaseInfo(参考表示)↓", target_price)

    # ■同一価格の調査を開始
    flags = []
    while search_min_price <= target_price <= search_max_price:
        # ベースの情報
        line_base_info = {
            'line_base_time': peaks[0]['time'],
            'line_base_price': round(target_price, 3),
            'line_base_direction': target_dir,
            'latest_direction': peaks[0]['direction'],
            'latest_time_in_df': peaks[0]['time'],
            'decision_price': target_df.iloc[0]['close']
        }
        # 同一価格情報を取得し、フラッグ成立有無の確認　（各価格（格子状に）で抵抗ラインの候補を探す）
        print(s4, " ＊＊＊", target_price)
        same_price_info = make_same_price_list_from_target_price(target_price, target_dir, peaks, same_price_range,
                                                                 False)  # ★★
        if len(same_price_info['same_price_list']) != 0:
            print(s6, same_price_info['same_price_list'])  # ターゲットを基準にした、同一価格リスト（＆その強度）
            same_price_info['same_price_list'] = [d for d in same_price_info['same_price_list'] if
                                                  d["time"] != peaks[0]['time']]  # Latestは削除する(predict特有）
            # 傾きの検証を行う（Flag形状）
            strength_info = same_price_info['strength_info']  # コード短縮のための置換
            if strength_info['line_on_num'] >= 2 and strength_info['line_strength'] >= 0.9:
                flag_info = judge_flag_figure(peaks, peaks[0]['direction'], target_df)
                if flag_info['tilt_line_level'] > 0:
                    print(s6, "★Flag成立のためオーダーのもとの生成")
                    flag_flag = True  # フラッグ成立
                    # 情報の上書き（Strengthに書くのが適切なのか・・・？）
                    same_price_info['strength_info']['line_strength'] = -1
                    same_price_info['strength_info']['priority'] = 3  # これは入れる場所検討
                    same_price_info['strength_info']['expected_direction'] = peaks[0]['direction']  # 念のため。。。（これはここに依存しないようにしたいが）
                    same_price_info['strength_info']['y_change'] = flag_info['y_change']
                    # 抵抗線線と近いかの確認
                    gap_line_latest_price = abs(target_price - peaks[0]['peak'])
                    if dependence_line_close_border > gap_line_latest_price:
                        is_close = True
                    else:
                        is_close = False
                    same_price_info['strength_info']['line_is_close_for_flag'] = is_close

                    each = {
                        "line_base_info": line_base_info,
                        "same_price_list": same_price_info['same_price_list'],
                        "strength_info": same_price_info['strength_info'],
                        "flag_info": flag_info
                    }
                    flags.append(each)
                else:
                    print(s6, " 抵抗線はあるが、傾き不成立")
        else:
            # same price list が発見できなかった場合（抵抗線なし）
            pass

        # ■■次のループへの処理
        skipper = dependence_search_skipper if len(same_price_info['same_price_list']) >= 1 else 0  # スキッパーの設定
        grid_adj = grid + skipper  # skipperをあらかじめgridに付加しておく
        target_price = target_price - (grid_adj * target_dir)  # 次のループへ（トップ⇒ボトムの検索。ボトム⇒トップの場合は*-1)

    # ■ループ後の処理（フラッグを一つに絞り、オーダーTrueにする）
    if flag_flag:
        # フラッグが成立している場合
        print("■■■")
        # 表示用　（↓返却の中身に等しい）
        # for i, item in enumerate(flags):
        #     print(s6, "今回")
        #     print(s6, item['line_base_info'])
        #     print(s6, item['same_price_list'])
        #     print(s6, item['strength_info'])
        #     print(s6, item['flag_info'])

        # 対象を一つに絞る処理
        if flag_flag:
            # 念のためLineStrengthが-1のもの（そもそもここにはFlag成立＝strength-1のものしか来ないはず）
            flags = [d for d in flags if d["strength_info"]["line_strength"] == -1]
            # 一番新しい時間を含むSamePriceListを採用する
            latest_flag_info = max(flags, key=lambda x: max(detail["time"] for detail in x["same_price_list"]))
            # 今回対象の直近のピークを抵抗線に持つフラッグ形状
            print(s4, "結論", latest_flag_info)
            print(s4, "line_base_info", latest_flag_info['line_base_info'])
            print(s4, "same_price_list", latest_flag_info['same_price_list'])
            print(s4, "strength_info", latest_flag_info['strength_info'])
            print(s4, "flag_info", latest_flag_info['flag_info'])
            orders_and_evidence["take_position_flag"] = flag_flag
            orders_and_evidence["line_base_info"] = latest_flag_info['line_base_info']
            orders_and_evidence['same_price_list'] = latest_flag_info['same_price_list']
            orders_and_evidence['strength_info'] = latest_flag_info['strength_info']
            orders_and_evidence['flag_info'] = latest_flag_info['flag_info']
            return orders_and_evidence
    else:
        # フラッグが成立していない場合
        return orders_and_evidence


def main_flag(dic_args):
    """
    引数はDFやピークスなど
    オーダーを生成する
    """

    # 表示時のインデント
    s4 = "    "
    s6 = "      "

    print("     新フラッグ調査関数")
    # ■関数事前準備■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■
    # ■■返却値 とその周辺の値
    exe_orders = []
    orders_and_evidence = {
        "take_position_flag": False,
        "exe_orders": exe_orders,
        "information": []
    }
    # ■■情報の整理と取得（関数の頭には必須）
    # fixed_information = cf.information_fix(dic_args)  # DFとPeaksが必ず返却される
    # df_r = fixed_information['df_r']
    # peaks = fixed_information['peaks']
    # peaks = peak_inspection.change_peaks_with_hard_skip(peaks)
    print("Flagてｓｔ")
    peaksclass = cpk.PeaksClass(dic_args['df_r'])
    df_r = dic_args['df_r']
    peaks = peaksclass.skipped_peaks
    s = "   "
    # print(s, "<SKIP後　対象>")
    # print(s, "Latest", pi.delete_peaks_information_for_print(peaks[0]))
    # print(s, "river ", pi.delete_peaks_information_for_print(peaks[1]))
    # print(s, "turn", pi.delete_peaks_information_for_print(peaks[2]))
    # print(s, "flop3", pi.delete_peaks_information_for_print(peaks[3]))
    # print(s, "flop2", pi.delete_peaks_information_for_print(peaks[4]))

    latest_candle_size = df_r.iloc[1]['highlow']
    # ■調査を実施する■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■
    # ■■実行しない条件の場合、実行を終了する
    if peaks[0]['count'] != 2:  #  not(2 <= peaks[0]['count'] < 4):
        print(s6, "countで実行しない", peaks[0]['count'])  # フラッグは基本的に、Latestの数がいつでも実行する
        return orders_and_evidence
    else:
        print("★flag実行する", peaks[0]['count'])

    # ■■解析の実行
    flag_analysis_result = analysis({"df_r": df_r, "peaks": peaks})
    print("★メイン側", flag_analysis_result['take_position_flag'], peaks[0]['count'])
    if not flag_analysis_result['take_position_flag']:
        return orders_and_evidence

    # ■フラッグ専用のLCChange
    lc_change = [
        # {"lc_change_exe": True, "time_after": 2 * 5 * 60, "lc_trigger_range": 0.05, "lc_ensure_range": 0.04},
        # 2022-2023は 0.05トリガーにすると、マイナスになる！！
        {"lc_change_exe": True, "time_after": 0, "lc_trigger_range": 0.06, "lc_ensure_range": 0.04},
    ]

    # ■フラッグ形状が発見された場合はオーダーを発行する
    flag_info = flag_analysis_result
    position_type = "STOP"  # フラッグありの場合突破方向のため、STOP
    # ■■突破方向のオーダー（初回と二回目以降で異なる）
    # if flag_info['flag_info']['is_first'] and flag_info['strength_info']['line_is_close_for_flag']:
    if flag_info['strength_info']['line_is_close_for_flag']:
        print("初回　かつ　BaseLineと近すぎる", flag_info['flag_info']['is_first'],
              flag_info['strength_info']['line_is_close_for_flag'])
        return orders_and_evidence
        # # 初回成立の場合は、Lineまで遠い場合は、突破はオーダーなし(これはテスト用。終わったらIf文含めて消したほうがいいかも）
        # if flag_info['strength_info']['line_is_close_for_flag']:
        #     # 初回でも近い場合は、抵抗線Break側のオーダーを出す
        #     # フラッグ用
        #     return orders_and_evidence
        # else:
        #     # 初回でなおかつ、距離が遠い場合はオーダーしない
        #     return orders_and_evidence
        #     pass
    else:
        # 初回ではない場合(オーダー）　⇒突破のみ
        if flag_info['flag_info']['tilt_line_level'] >= 1:  # フラッグ形状がきれい（＝１）場合、突破
            break_position = True
        else:
            break_position = False  # あまり整っていないフラッグ形状の場合、レンジ

        if break_position:
            dependence_normal_margin = 0.006  # 0.035がシミュレーション上はベスト
            dependence_lc_range_max = 0.06
            dependence_lc_range_at_least = 0.04  # 最初は0.04
            dependence_counter_margin = 0.016  # 0.035がシミュレーション上はベスト
            dependence_lc_range_max_c = 0.055  # 0.12が強い
            dependence_lc_range_at_least_c = 0.022  # 0.12が強い　カウンターはそもそもが適当なため、狭いめ

            # ■■フラッグ用（突破方向）
            # 最大でもLCRange換算で10pips以内したい
            target_price = flag_info['line_base_info']['line_base_price'] + (
                    dependence_normal_margin * flag_info['line_base_info']['line_base_direction'])  # lcPriceは収束の中間点
            temp_lc_price = flag_info['flag_info']['lc_price']
            lc_range = temp_lc_price - target_price  # これがマイナス値の場合Directionは１、プラス値となる場合Directionは-1
            print(s6, "LC検討", target_price, temp_lc_price, lc_range, temp_lc_price)
            if abs(lc_range) >= dependence_lc_range_max:
                # LCが大きすぎると判断される場合(10pips以上離れている）
                if lc_range < 0:
                    # LC_rangeがマイナス値　＝　Directionは１。その為、現在価格からマイナスするとLCPriceとなる
                    lc_price = target_price - abs(dependence_lc_range_max)
                    print(s6, "ggLC価格(Dir1)", target_price, "-", abs(dependence_lc_range_max))
                else:
                    # LC_rangeがプラス値　＝　Directionは-1。その為、現在書くにプラスするとＬＣＰｒｉｃｅになる
                    lc_price = target_price + abs(dependence_lc_range_max)
                    print(s6, "gLC価格(Dir-1)", target_price, "+", abs(dependence_lc_range_max))
            elif abs(lc_range) <= dependence_lc_range_at_least:
                # LCが小さすぎる
                if lc_range < 0:
                    # LC_rangeがマイナス値　＝　Directionは１。その為、現在価格からマイナスするとLCPriceとなる
                    lc_price = target_price - abs(dependence_lc_range_at_least)
                    print(s6, "gggLC価格(Dir1)", target_price, "-", abs(dependence_lc_range_at_least))
                else:
                    # LC_rangeがプラス値　＝　Directionは-1。その為、現在書くにプラスするとＬＣＰｒｉｃｅになる
                    lc_price = target_price + abs(dependence_lc_range_at_least)
                    print(s6, "gggggLC価格(Dir-1)", target_price, "+", abs(dependence_lc_range_at_least))
            else:
                # LCRangeが許容範囲内の場合、そのまま利用
                lc_price = temp_lc_price
                print(s6, "そのままのLCを利用する", lc_price)
            main_order_base = cf.order_base(df_r.iloc[0]['close'], df_r.iloc[0]['time_jp'])  # tpはLCChange任せのため、Baseのまま
            # main_order_base['target'] = target_price + (0.035 * flag_info['line_base_info']['line_base_direction'])  # 0.05
            # main_order_base['lc'] = flag_info['strength_info']['lc_price']  # 0.06 ←0.06は結構本命  # 0.09  # LCは広め　　  # 入れる側の文字は　LCのみ
            main_order_base['target'] = target_price
            main_order_base['lc'] = lc_price
            main_order_base['type'] = position_type
            main_order_base['expected_direction'] = flag_info['strength_info']['expected_direction']
            main_order_base['priority'] = 5  # flag_info['strength_info']['priority']
            main_order_base['lc_change'] = lc_change
            main_order_base['units'] = main_order_base['units'] * 1
            main_order_base['name'] = "フラッグ強" + flag_info['strength_info']['remark']
            main_order_base['y_change'] = flag_info['strength_info']['y_change']
            exe_orders.append(cf.order_finalize(main_order_base))

            # ■■リバースオーダーも入れる（二回目以降のみ）
            # 最大でもLCRange換算で10pips以内したい
            target_price = peaks[1]['peak'] - (
                    dependence_counter_margin * flag_info['line_base_info']['line_base_direction'])
            print(s6, "カウンターのTarget検討", peaks[1]['peak'], peaks[1]['time'], dependence_counter_margin)
            temp_lc_price = flag_info['line_base_info']['line_base_price']
            lc_range = temp_lc_price - target_price  # これがマイナス値の場合Directionは１、プラス値となる場合Directionは-1
            print(s6, "LC検討", target_price, temp_lc_price, lc_range, peaks[0]['peak'])
            if abs(lc_range) >= dependence_lc_range_max_c:
                # LCが大きすぎると判断される場合(10pips以上離れている）
                if lc_range < 0:
                    # LC_rangeがマイナス値　＝　売り注文。その為、ターゲット価格にプラスするとLCPriceとなる
                    lc_price_counter = target_price + abs(dependence_lc_range_max_c)  # 通常とは符号逆 もともとー
                    print(s6, "LC価格(Dir1)", target_price, "-", abs(dependence_lc_range_max_c))
                else:
                    # LC_rangeがプラス値　＝　買い注文。その為、ターゲット価格からマイナスするとＬＣＰｒｉｃｅになる
                    lc_price_counter = target_price - abs(dependence_lc_range_max_c)  # 通常とは符号逆　もともと＋
                    print(s6, "LC価格(Dir-1)", target_price, "+", abs(dependence_lc_range_max_c))
            elif abs(lc_range) <= dependence_lc_range_at_least_c:
                # LCが小さすぎる
                if lc_range < 0:
                    # LC_rangeがマイナス値　＝　売り注文。その為、ターゲット価格にプラスするとLCPriceとなる
                    lc_price_counter = target_price + abs(dependence_lc_range_at_least_c)
                    print(s6, "LC価格(Dir1)", target_price, "-", abs(dependence_lc_range_at_least_c))
                else:
                    # LC_rangeがプラス値　＝　買い注文。その為、ターゲット価格からマイナスするとＬＣＰｒｉｃｅになる
                    lc_price_counter = target_price - abs(dependence_lc_range_at_least_c)
                    print(s6, "LC価格(Dir-1)", target_price, "+", abs(dependence_lc_range_at_least_c))
            else:
                # LCRangeが許容範囲内の場合、そのまま利用
                lc_price_counter = temp_lc_price
                print(s6, "そのままのLCを利用する", lc_price_counter)
            # 現在価格との整合性が取れない（即時オーダーとなる場合）があるため、考慮する
            if flag_info['strength_info']['expected_direction'] * -1 == -1:
                # カウンターが売り方向の場合、現在価格よりも下にあるべき。
                if target_price >= peaks[0]['peak']:
                    print("★★★整合性のとれないオーダーになりそうだった（売り側）", lc_price_counter, ">",
                          peaks[0]['peak'])
                    target_price = peaks[0]['peak'] - 0.035
            else:
                # カウンターが買い方向の場合、現在価格よりも上にあるべき
                if target_price <= peaks[0]['peak']:
                    print("★★★整合性のとれないオーダーになりそうだった（買い側）", lc_price_counter, "<",
                          peaks[0]['peak'])
                    target_price = peaks[0]['peak'] + 0.035

            main_order_base = cf.order_base(df_r.iloc[0]['close'], df_r.iloc[0]['time_jp'])  # tpはLCChange任せのため、Baseのまま
            # main_order_base['target'] = peaks[1]['peak'] - (0.035 * flag_info['line_base_info']['line_base_direction'])  # river価格＋マージン0.027
            main_order_base['target'] = target_price  # river価格＋マージン0.027
            main_order_base['lc'] = lc_price_counter  # ←悪くなさそうだが、広すぎる？
            main_order_base['type'] = position_type
            main_order_base['expected_direction'] = flag_info['strength_info']['expected_direction'] * -1
            main_order_base['priority'] = 5  # ['strength_info']['priority']
            main_order_base['units'] = main_order_base['units'] * 1
            main_order_base['lc_change'] = lc_change
            main_order_base['name'] = "フラッグ強リバース" + flag_info['strength_info']['remark']
            main_order_base['y_change'] = flag_info['strength_info']['y_change']
            exe_orders.append(cf.order_finalize(main_order_base))
        else:
            # 初回ではない場合 ＆　ブレイクではないほう（レンジに戻る方）。基本はブレイク方向だったが、念のためこっちも追加
            # その為、こちらは割と控えめなスタート
            dependence_normal_margin = latest_candle_size  # 0.032  # 0.035がシミュレーション上はベスト 0.032は割とひっかけられてしまう。
            dependence_lc_range_max = 0.06
            dependence_lc_range_at_least = 0.04  # 最初は0.04
            dependence_counter_margin = 0.032  # 0.035がシミュレーション上はベスト
            dependence_lc_range_max_c = 0.036  # 0.12が強い
            dependence_lc_range_at_least_c = 0.022  # 0.12が強い　カウンターはそもそもが適当なため、狭いめ

            # ■■フラッグ用（突破方向）
            # 最大でもLCRange換算で10pips以内したい
            target_price = flag_info['line_base_info']['line_base_price'] + (
                    dependence_normal_margin * flag_info['line_base_info'][
                'line_base_direction'])  # - (0.035 * flag_info['line_base_info']['line_base_direction'])  # Nowpriceというより、取得価格
            # temp_lc_price = flag_info['strength_info']['flag_info']['oldest_peak_info']['oldest_info']['peak']  # lcPriceは収束の中間点
            temp_lc_price = flag_info['flag_info']['lc_price']
            lc_range = temp_lc_price - target_price  # これがマイナス値の場合Directionは１、プラス値となる場合Directionは-1
            print(s6, "LC検討", target_price, temp_lc_price, lc_range, temp_lc_price)
            if abs(lc_range) >= dependence_lc_range_max:
                # LCが大きすぎると判断される場合(10pips以上離れている）
                if lc_range < 0:
                    # LC_rangeがマイナス値　＝　Directionは１。その為、現在価格からマイナスするとLCPriceとなる
                    lc_price = target_price - abs(dependence_lc_range_max)
                    print(s6, "ggLC価格(Dir1)", target_price, "-", abs(dependence_lc_range_max))
                else:
                    # LC_rangeがプラス値　＝　Directionは-1。その為、現在書くにプラスするとＬＣＰｒｉｃｅになる
                    lc_price = target_price + abs(dependence_lc_range_max)
                    print(s6, "gLC価格(Dir-1)", target_price, "+", abs(dependence_lc_range_max))
            elif abs(lc_range) <= dependence_lc_range_at_least:
                # LCが小さすぎる
                if lc_range < 0:
                    # LC_rangeがマイナス値　＝　Directionは１。その為、現在価格からマイナスするとLCPriceとなる
                    lc_price = target_price - abs(dependence_lc_range_at_least)
                    print(s6, "gggLC価格(Dir1)", target_price, "-", abs(dependence_lc_range_at_least))
                else:
                    # LC_rangeがプラス値　＝　Directionは-1。その為、現在書くにプラスするとＬＣＰｒｉｃｅになる
                    lc_price = target_price + abs(dependence_lc_range_at_least)
                    print(s6, "gggggLC価格(Dir-1)", target_price, "+", abs(dependence_lc_range_at_least))
            else:
                # LCRangeが許容範囲内の場合、そのまま利用
                lc_price = temp_lc_price
                print(s6, "そのままのLCを利用する", lc_price)
            main_order_base = cf.order_base(df_r.iloc[0]['close'], df_r.iloc[0]['time_jp'])  # tpはLCChange任せのため、Baseのまま
            # main_order_base['target'] = target_price + (0.035 * flag_info['line_base_info']['line_base_direction'])  # 0.05
            # main_order_base['lc'] = flag_info['strength_info']['lc_price']  # 0.06 ←0.06は結構本命  # 0.09  # LCは広め　　  # 入れる側の文字は　LCのみ
            main_order_base['target'] = target_price
            main_order_base['lc'] = dependence_lc_range_max
            main_order_base['type'] = "LIMIT"  # 逆張り
            main_order_base['expected_direction'] = flag_info['strength_info']['expected_direction'] * -1  # 逆張り
            main_order_base['priority'] = 5  # flag_info['strength_info']['priority']
            main_order_base['lc_change'] = lc_change
            main_order_base['units'] = main_order_base['units'] * 1
            main_order_base['name'] = "フラッグ弱(リバース)" + flag_info['strength_info']['remark']
            main_order_base['y_change'] = flag_info['strength_info']['y_change']
            exe_orders.append(cf.order_finalize(main_order_base))

            # ■■カウンタオーダーも入れる（二回目以降のみ）
            # 最大でもLCRange換算で10pips以内したい
            target_price = peaks[1]['peak'] - (
                    dependence_counter_margin * flag_info['line_base_info']['line_base_direction'])
            print(s6, "カウンターのTarget検討", peaks[1]['peak'], peaks[1]['time'], dependence_counter_margin)
            temp_lc_price = flag_info['line_base_info']['line_base_price']
            lc_range = temp_lc_price - target_price  # これがマイナス値の場合Directionは１、プラス値となる場合Directionは-1
            print(s6, "LC検討", target_price, temp_lc_price, lc_range, peaks[0]['peak'])
            if abs(lc_range) >= dependence_lc_range_max_c:
                # LCが大きすぎると判断される場合(10pips以上離れている）
                if lc_range < 0:
                    # LC_rangeがマイナス値　＝　売り注文。その為、ターゲット価格にプラスするとLCPriceとなる
                    lc_price_counter = target_price + abs(dependence_lc_range_max_c)  # 通常とは符号逆 もともとー
                    print(s6, "LC価格(Dir1)", target_price, "-", abs(dependence_lc_range_max_c))
                else:
                    # LC_rangeがプラス値　＝　買い注文。その為、ターゲット価格からマイナスするとＬＣＰｒｉｃｅになる
                    lc_price_counter = target_price - abs(dependence_lc_range_max_c)  # 通常とは符号逆　もともと＋
                    print(s6, "LC価格(Dir-1)", target_price, "+", abs(dependence_lc_range_max_c))
            elif abs(lc_range) <= dependence_lc_range_at_least_c:
                # LCが小さすぎる
                if lc_range < 0:
                    # LC_rangeがマイナス値　＝　売り注文。その為、ターゲット価格にプラスするとLCPriceとなる
                    lc_price_counter = target_price + abs(dependence_lc_range_at_least_c)
                    print(s6, "LC価格(Dir1)", target_price, "-", abs(dependence_lc_range_at_least_c))
                else:
                    # LC_rangeがプラス値　＝　買い注文。その為、ターゲット価格からマイナスするとＬＣＰｒｉｃｅになる
                    lc_price_counter = target_price - abs(dependence_lc_range_at_least_c)
                    print(s6, "LC価格(Dir-1)", target_price, "+", abs(dependence_lc_range_at_least_c))
            else:
                # LCRangeが許容範囲内の場合、そのまま利用
                lc_price_counter = temp_lc_price
                print(s6, "そのままのLCを利用する", lc_price_counter)
            # 現在価格との整合性が取れない（即時オーダーとなる場合）があるため、考慮する
            if flag_info['strength_info']['expected_direction'] * -1 == -1:
                # カウンターが売り方向の場合、現在価格よりも下にあるべき。
                if target_price >= peaks[0]['peak']:
                    print("★★★整合性のとれないオーダーになりそうだった（売り側）", lc_price_counter, ">",
                          peaks[0]['peak'])
                    target_price = peaks[0]['peak'] - 0.035
            else:
                # カウンターが買い方向の場合、現在価格よりも上にあるべき
                if target_price <= peaks[0]['peak']:
                    print("★★★整合性のとれないオーダーになりそうだった（買い側）", lc_price_counter, "<",
                          peaks[0]['peak'])
                    target_price = peaks[0]['peak'] + 0.035

            main_order_base = cf.order_base(df_r.iloc[0]['close'], df_r.iloc[0]['time_jp'])  # tpはLCChange任せのため、Baseのまま
            # main_order_base['target'] = peaks[1]['peak'] - (0.035 * flag_info['line_base_info']['line_base_direction'])  # river価格＋マージン0.027
            main_order_base['target'] = target_price  # river価格＋マージン0.027
            main_order_base['lc'] = dependence_lc_range_max_c
            main_order_base['type'] = "LIMIT"
            main_order_base['expected_direction'] = flag_info['strength_info']['expected_direction']  # * -1
            main_order_base['priority'] = 5  # ['strength_info']['priority']
            main_order_base['units'] = main_order_base['units'] * 1
            main_order_base['lc_change'] = lc_change
            main_order_base['name'] = "フラッグ弱(ブレイク)" + flag_info['strength_info']['remark'] + '(count:' + str(
                peaks[0]['count']) + ')'
            main_order_base['y_change'] = flag_info['strength_info']['y_change']
            exe_orders.append(cf.order_finalize(main_order_base))

    # if both_order:
    #     # breakを少し余裕をもって取り、それまでレンジ前提のオーダーも出す
    #     # 往復ビンタ怖いけどね
    #     dependence_normal_margin = 0.025  #
    #     dependence_lc_range_max = 0.09
    #     dependence_lc_range_at_least = 0.04
    #     dependence_margin_margin = 0.004
    #
    #     dependence_counter_margin = 0.025
    #     dependence_lc_range_max_c = 0.09
    #     dependence_lc_range_at_least_c = 0.04
    #
    #
    #     # ■■フラッグ用（突破方向）
    #     # 最大でもLCRange換算で10pips以内したい
    #     print(s6, "targetPrice計算", flag_info['line_base_info']['line_base_price'], dependence_normal_margin)
    #     target_price = flag_info['line_base_info']['line_base_price'] + (
    #                 dependence_normal_margin * flag_info['line_base_info'][
    #             'line_base_direction'])  # - (0.035 * flag_info['line_base_info']['line_base_direction'])  # Nowpriceというより、取得価格
    #     # temp_lc_price = flag_info['strength_info']['flag_info']['oldest_peak_info']['oldest_info']['peak']  # lcPriceは収束の中間点
    #     temp_lc_price = flag_info['strength_info']['lc_price']
    #     lc_range = temp_lc_price - target_price  # これがマイナス値の場合Directionは１、プラス値となる場合Directionは-1
    #     print(s6, "LC検討", target_price, temp_lc_price, lc_range, temp_lc_price)
    #     if abs(lc_range) >= dependence_lc_range_max:
    #         # LCが大きすぎると判断される場合(10pips以上離れている）
    #         if lc_range < 0:
    #             # LC_rangeがマイナス値　＝　Directionは１。その為、現在価格からマイナスするとLCPriceとなる
    #             lc_price = target_price - abs(dependence_lc_range_max)
    #             print(s6, "ggLC価格(Dir1)", target_price, "-", abs(dependence_lc_range_max))
    #         else:
    #             # LC_rangeがプラス値　＝　Directionは-1。その為、現在書くにプラスするとＬＣＰｒｉｃｅになる
    #             lc_price = target_price + abs(dependence_lc_range_max)
    #             print(s6, "gLC価格(Dir-1)", target_price, "+", abs(dependence_lc_range_max))
    #     elif abs(lc_range) <= dependence_lc_range_at_least:
    #         # LCが小さすぎる
    #         if lc_range < 0:
    #             # LC_rangeがマイナス値　＝　Directionは１。その為、現在価格からマイナスするとLCPriceとなる
    #             lc_price = target_price - abs(dependence_lc_range_at_least)
    #             print(s6, "gggLC価格(Dir1)", target_price, "-", abs(dependence_lc_range_at_least))
    #         else:
    #             # LC_rangeがプラス値　＝　Directionは-1。その為、現在書くにプラスするとＬＣＰｒｉｃｅになる
    #             lc_price = target_price + abs(dependence_lc_range_at_least)
    #             print(s6, "gggggLC価格(Dir-1)", target_price, "+", abs(dependence_lc_range_at_least))
    #     else:
    #         # LCRangeが許容範囲内の場合、そのまま利用
    #         lc_price = temp_lc_price
    #         print(s6, "そのままのLCを利用する", lc_price)
    #     main_order_base = cf.order_base(df_r.iloc[0]['close'], df_r.iloc[0]['time_jp'])  # tpはLCChange任せのため、Baseのまま
    #     # main_order_base['target'] = target_price + (0.035 * flag_info['line_base_info']['line_base_direction'])  # 0.05
    #     # main_order_base['lc'] = flag_info['strength_info']['lc_price']  # 0.06 ←0.06は結構本命  # 0.09  # LCは広め　　  # 入れる側の文字は　LCのみ
    #     main_order_base['target'] = target_price
    #     main_order_base['lc'] = lc_price   # Breakオーダーとバッティングしないように
    #     main_order_base['type'] = position_type
    #     main_order_base['expected_direction'] = flag_info['strength_info']['expected_direction']
    #     main_order_base['priority'] = 5  # flag_info['strength_info']['priority']
    #     main_order_base['lc_change'] = lc_change
    #     main_order_base['units'] = main_order_base['units'] * 1
    #     main_order_base['name'] = flag_info['strength_info']['remark'] + '(count:' + str(peaks[0]['count']) + ')'
    #     main_order_base['y_change'] = flag_info['strength_info']['y_change']
    #     exe_orders.append(cf.order_finalize(main_order_base))
    #     # ■Breakに至るまで、レンジに戻るオーダーも入れておく
    #     main_order_base = cf.order_base(df_r.iloc[0]['close'], df_r.iloc[0]['time_jp'])  # tpはLCChange任せのため、Baseのまま
    #     main_order_base['target'] = flag_info['line_base_info']['line_base_price']
    #     main_order_base['lc'] = dependence_normal_margin - dependence_margin_margin
    #     main_order_base['type'] = "LIMIT"  # これは逆張りのためLimit
    #     main_order_base['expected_direction'] = flag_info['strength_info']['expected_direction'] * -1
    #     main_order_base['priority'] = 5  # flag_info['strength_info']['priority']
    #     main_order_base['lc_change'] = lc_change
    #     main_order_base['units'] = main_order_base['units'] * 0.1
    #     main_order_base['name'] = flag_info['strength_info']['remark'] + "レンジ側 " + '(count:' + str(peaks[0]['count']) + ')'
    #     main_order_base['y_change'] = flag_info['strength_info']['y_change']
    #     exe_orders.append(cf.order_finalize(main_order_base))
    #
    #     # ■■カウンタオーダーも入れる（二回目以降のみ）
    #     # 最大でもLCRange換算で10pips以内したい
    #     target_price = peaks[1]['peak'] - (
    #                 dependence_counter_margin * flag_info['line_base_info']['line_base_direction'])
    #     temp_lc_price = flag_info['line_base_info']['line_base_price']
    #     lc_range = temp_lc_price - target_price  # これがマイナス値の場合Directionは１、プラス値となる場合Directionは-1
    #     print(s6, "LC検討", target_price, temp_lc_price, lc_range, peaks[0]['peak'])
    #     if abs(lc_range) >= dependence_lc_range_max_c:
    #         # LCが大きすぎると判断される場合(10pips以上離れている）
    #         if lc_range < 0:
    #             # LC_rangeがマイナス値　＝　売り注文。その為、ターゲット価格にプラスするとLCPriceとなる
    #             lc_price_counter = target_price + abs(dependence_lc_range_max_c)  # 通常とは符号逆 もともとー
    #             print(s6, "LC価格(Dir1)", target_price, "-", abs(dependence_lc_range_max_c))
    #         else:
    #             # LC_rangeがプラス値　＝　買い注文。その為、ターゲット価格からマイナスするとＬＣＰｒｉｃｅになる
    #             lc_price_counter = target_price - abs(dependence_lc_range_max_c)  # 通常とは符号逆　もともと＋
    #             print(s6, "LC価格(Dir-1)", target_price, "+", abs(dependence_lc_range_max_c))
    #     elif abs(lc_range) <= dependence_lc_range_at_least_c:
    #         # LCが小さすぎる
    #         if lc_range < 0:
    #             # LC_rangeがマイナス値　＝　売り注文。その為、ターゲット価格にプラスするとLCPriceとなる
    #             lc_price_counter = target_price + abs(dependence_lc_range_at_least_c)
    #             print(s6, "LC価格(Dir1)", target_price, "-", abs(dependence_lc_range_at_least_c))
    #         else:
    #             # LC_rangeがプラス値　＝　買い注文。その為、ターゲット価格からマイナスするとＬＣＰｒｉｃｅになる
    #             lc_price_counter = target_price - abs(dependence_lc_range_at_least_c)
    #             print(s6, "LC価格(Dir-1)", target_price, "+", abs(dependence_lc_range_at_least_c))
    #     else:
    #         # LCRangeが許容範囲内の場合、そのまま利用
    #         lc_price_counter = temp_lc_price
    #         print(s6, "そのままのLCを利用する", lc_price_counter)
    #     # 現在価格との整合性が取れない（即時オーダーとなる場合）があるため、考慮する
    #     if flag_info['strength_info']['expected_direction'] * -1 == -1:
    #         # カウンターが売り方向の場合、現在価格よりも下にあるべき。
    #         if target_price >= peaks[0]['peak']:
    #             print("★★★整合性のとれないオーダーになりそうだった（売り側）", lc_price_counter, ">", peaks[0]['peak'])
    #             target_price = peaks[0]['peak'] - 0.035
    #     else:
    #         # カウンターが買い方向の場合、現在価格よりも上にあるべき
    #         if target_price <= peaks[0]['peak']:
    #             print("★★★整合性のとれないオーダーになりそうだった（買い側）", lc_price_counter, "<", peaks[0]['peak'])
    #             target_price = peaks[0]['peak'] + 0.035
    #
    #     main_order_base = cf.order_base(df_r.iloc[0]['close'], df_r.iloc[0]['time_jp'])  # tpはLCChange任せのため、Baseのまま
    #     # main_order_base['target'] = peaks[1]['peak'] - (0.035 * flag_info['line_base_info']['line_base_direction'])  # river価格＋マージン0.027
    #     main_order_base['target'] = target_price  # river価格＋マージン0.027
    #     main_order_base['lc'] = lc_price_counter  # ←悪くなさそうだが、広すぎる？
    #     main_order_base['type'] = position_type
    #     main_order_base['expected_direction'] = flag_info['strength_info']['expected_direction'] * -1
    #     main_order_base['priority'] = 5  # ['strength_info']['priority']
    #     main_order_base['units'] = main_order_base['units'] * 1
    #     main_order_base['lc_change'] = lc_change
    #     main_order_base['name'] = "カウンター" + flag_info['strength_info']['remark'] + '(count:' + str(
    #         peaks[0]['count']) + ')'
    #     main_order_base['y_change'] = flag_info['strength_info']['y_change']
    #     exe_orders.append(cf.order_finalize(main_order_base))
    #     # ■カウンターに至るまで、レンジに戻るオーダーも入れておく
    #     main_order_base = cf.order_base(df_r.iloc[0]['close'], df_r.iloc[0]['time_jp'])  # tpはLCChange任せのため、Baseのまま
    #     main_order_base['target'] = peaks[1]['peak']
    #     main_order_base['lc'] = dependence_counter_margin - dependence_margin_margin
    #     main_order_base['type'] = "LIMIT"  # これは逆張りのためLimit
    #     main_order_base['expected_direction'] = flag_info['strength_info']['expected_direction']
    #     main_order_base['priority'] = 5  # flag_info['strength_info']['priority']
    #     main_order_base['lc_change'] = lc_change
    #     main_order_base['units'] = main_order_base['units'] * 0.1
    #     main_order_base['name'] = "カウンター" + flag_info['strength_info']['remark'] + "レンジ側 " + '(count:' + str(peaks[0]['count']) + ')'
    #     main_order_base['y_change'] = flag_info['strength_info']['y_change']
    #     exe_orders.append(cf.order_finalize(main_order_base))

    # 返却する
    print(s4, "オーダー対象", flag_info)
    orders_and_evidence["take_position_flag"] = True  # ここまで来ている＝注文あり
    orders_and_evidence["exe_orders"] = exe_orders
    orders_and_evidence["information"] = flag_info['strength_info']

    print("オーダー表示")
    gene.print_arr(orders_and_evidence["exe_orders"])
    return orders_and_evidence


def main_flag_calm_state(dic_args):
    """
    相場が落ち着いている場合は、「戻る方向」（従来の突破方向とは逆）にする。
    ただし、TargetへのMarginは少し大き目
    """

    # 表示時のインデント
    s4 = "    "
    s6 = "      "

    print(" 新フラッグ調査関数")
    # ■関数事前準備■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■
    # ■■返却値 とその周辺の値
    exe_orders = []
    orders_and_evidence = {
        "take_position_flag": False,
        "exe_orders": exe_orders,
        "information": []
    }
    # ■■情報の整理と取得（関数の頭には必須）
    # fixed_information = cf.information_fix(dic_args)  # DFとPeaksが必ず返却される
    # df_r = fixed_information['df_r']
    # peaks = fixed_information['peaks']
    # peaks = peak_inspection.change_peaks_with_hard_skip(peaks)
    peaksclass = cpk.PeaksClass(dic_args['df_r'])
    df_r = dic_args['df_r']
    peaks = peaksclass.skipped_peaks
    s = "   "
    # print(s, "<SKIP後　対象>")
    # print(s, "Latest", pi.delete_peaks_information_for_print(peaks[0]))
    # print(s, "river ", pi.delete_peaks_information_for_print(peaks[1]))
    # print(s, "turn", pi.delete_peaks_information_for_print(peaks[2]))
    # print(s, "flop3", pi.delete_peaks_information_for_print(peaks[3]))
    # print(s, "flop2", pi.delete_peaks_information_for_print(peaks[4]))

    # ■調査を実施する■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■
    # ■■実行しない条件の場合、実行を終了する
    if peaks[0]['count'] > 4:
        print(s6, "countで実行しない場合を宣言する")  # フラッグは基本的に、Latestの数がいつでも実行する
    # for i, item in enumerate(peaks[:7]):
    #     if item['include_very_large']:
    #         print("veryLargeあり")
    #         return orders_and_evidence
    # ■■解析の実行
    flag_analysis_result = analysis({"df_r": df_r, "peaks": peaks})
    print("メイン側", flag_analysis_result['take_position_flag'])
    if not flag_analysis_result['take_position_flag']:
        return orders_and_evidence

    # ■フラッグ専用のLCChange
    lc_change = [
        # {"lc_change_exe": True, "time_after": 2 * 5 * 60, "lc_trigger_range": 0.05, "lc_ensure_range": 0.04},
        # 2022-2023は 0.05トリガーにすると、マイナスになる！！
        {"lc_change_exe": True, "time_after": 0, "lc_trigger_range": 0.06, "lc_ensure_range": 0.04},
    ]

    # ■フラッグ形状が発見された場合はオーダーを発行する
    flag_info = flag_analysis_result['information']
    # "flag_info": {"LineBase": {}, "samePriceList": [{peaks}], "strengthInfo": {"lc_price,remark,y_change等"}

    # ■■突破方向のオーダー（初回と二回目以降で異なる）
    flag_final = True  # 初回の一部でオーダーが入らない仕様になったため、改めてフラグを持っておく（オーダーないときはOrderAndEvidence返却でもいいかも？）
    # if flag_info['strength_info']['is_first_for_flag']:
    if flag_info['flag_info']['is_first'] and flag_info['strength_info']['line_is_close_for_flag']:
        print("初回　かつ　BaseLineと近すぎる", flag_info['flag_info']['is_first'],
              flag_info['strength_info']['line_is_close_for_flag'])
        return orders_and_evidence
        # # 初回成立の場合は、Lineまで遠い場合は、突破はオーダーなし(これはテスト用。終わったらIf文含めて消したほうがいいかも）
        # if flag_info['strength_info']['line_is_close_for_flag']:
        #     # 初回でも近い場合は、抵抗線Break側のオーダーを出す
        #     # フラッグ用
        #     return orders_and_evidence
        # else:
        #     # 初回でなおかつ、距離が遠い場合はオーダーしない
        #     return orders_and_evidence
        #     pass
    else:
        # 初回ではない場合
        dependence_normal_margin = 0.026  # 0.035がシミュレーション上はベスト
        dependence_lc_range_max = 0.09
        dependence_lc_range_at_least = 0.04  # 最初は0.04
        dependence_counter_margin = 0.026  # 0.035がシミュレーション上はベスト
        dependence_lc_range_max_c = 0.022  # 0.12が強い
        dependence_lc_range_at_least_c = 0.022  # 0.12が強い　カウンターはそもそもが適当なため、狭いめ

        # ■■フラッグ用（突破方向）
        # 最大でもLCRange換算で10pips以内したい
        target_price = flag_info['line_base_info']['line_base_price'] + (
                dependence_normal_margin * flag_info['line_base_info'][
            'line_base_direction'])  # - (0.035 * flag_info['line_base_info']['line_base_direction'])  # Nowpriceというより、取得価格
        # temp_lc_price = flag_info['strength_info']['flag_info']['oldest_peak_info']['oldest_info']['peak']  # lcPriceは収束の中間点
        temp_lc_price = flag_info['strength_info']['lc_price']
        lc_range = temp_lc_price - target_price  # これがマイナス値の場合Directionは１、プラス値となる場合Directionは-1
        print(s6, "LC検討", target_price, temp_lc_price, lc_range, temp_lc_price)
        if abs(lc_range) >= dependence_lc_range_max:
            # LCが大きすぎると判断される場合(10pips以上離れている）
            if lc_range < 0:
                # LC_rangeがマイナス値　＝　Directionは１。その為、現在価格からマイナスするとLCPriceとなる
                lc_price = target_price - abs(dependence_lc_range_max)
                print(s6, "ggLC価格(Dir1)", target_price, "-", abs(dependence_lc_range_max))
            else:
                # LC_rangeがプラス値　＝　Directionは-1。その為、現在書くにプラスするとＬＣＰｒｉｃｅになる
                lc_price = target_price + abs(dependence_lc_range_max)
                print(s6, "gLC価格(Dir-1)", target_price, "+", abs(dependence_lc_range_max))
        elif abs(lc_range) <= dependence_lc_range_at_least:
            # LCが小さすぎる
            if lc_range < 0:
                # LC_rangeがマイナス値　＝　Directionは１。その為、現在価格からマイナスするとLCPriceとなる
                lc_price = target_price - abs(dependence_lc_range_at_least)
                print(s6, "gggLC価格(Dir1)", target_price, "-", abs(dependence_lc_range_at_least))
            else:
                # LC_rangeがプラス値　＝　Directionは-1。その為、現在書くにプラスするとＬＣＰｒｉｃｅになる
                lc_price = target_price + abs(dependence_lc_range_at_least)
                print(s6, "gggggLC価格(Dir-1)", target_price, "+", abs(dependence_lc_range_at_least))
        else:
            # LCRangeが許容範囲内の場合、そのまま利用
            lc_price = temp_lc_price
            print(s6, "そのままのLCを利用する", lc_price)
        main_order_base = cf.order_base(df_r.iloc[0]['close'], df_r.iloc[0]['time_jp'])  # tpはLCChange任せのため、Baseのまま
        # main_order_base['target'] = target_price + (0.035 * flag_info['line_base_info']['line_base_direction'])  # 0.05
        # main_order_base['lc'] = flag_info['strength_info']['lc_price']  # 0.06 ←0.06は結構本命  # 0.09  # LCは広め　　  # 入れる側の文字は　LCのみ
        main_order_base['target'] = target_price
        main_order_base['lc'] = 0.09
        main_order_base['type'] = "LIMIT"  # 逆張り
        main_order_base['expected_direction'] = flag_info['strength_info']['expected_direction'] * -1  # 逆張り
        main_order_base['priority'] = 5  # flag_info['strength_info']['priority']
        main_order_base['lc_change'] = lc_change
        main_order_base['units'] = main_order_base['units'] * 1
        main_order_base['name'] = "レンジ" + flag_info['strength_info']['remark'] + '(count:' + str(
            peaks[0]['count']) + ')'
        main_order_base['y_change'] = flag_info['strength_info']['y_change']
        exe_orders.append(cf.order_finalize(main_order_base))

        # ■■カウンタオーダーも入れる（二回目以降のみ）
        # 最大でもLCRange換算で10pips以内したい
        target_price = peaks[1]['peak'] - (
                dependence_counter_margin * flag_info['line_base_info']['line_base_direction'])
        print(s6, "カウンターのTarget検討", peaks[1]['peak'], peaks[1]['time'], dependence_counter_margin)
        temp_lc_price = flag_info['line_base_info']['line_base_price']
        lc_range = temp_lc_price - target_price  # これがマイナス値の場合Directionは１、プラス値となる場合Directionは-1
        print(s6, "LC検討", target_price, temp_lc_price, lc_range, peaks[0]['peak'])
        if abs(lc_range) >= dependence_lc_range_max_c:
            # LCが大きすぎると判断される場合(10pips以上離れている）
            if lc_range < 0:
                # LC_rangeがマイナス値　＝　売り注文。その為、ターゲット価格にプラスするとLCPriceとなる
                lc_price_counter = target_price + abs(dependence_lc_range_max_c)  # 通常とは符号逆 もともとー
                print(s6, "LC価格(Dir1)", target_price, "-", abs(dependence_lc_range_max_c))
            else:
                # LC_rangeがプラス値　＝　買い注文。その為、ターゲット価格からマイナスするとＬＣＰｒｉｃｅになる
                lc_price_counter = target_price - abs(dependence_lc_range_max_c)  # 通常とは符号逆　もともと＋
                print(s6, "LC価格(Dir-1)", target_price, "+", abs(dependence_lc_range_max_c))
        elif abs(lc_range) <= dependence_lc_range_at_least_c:
            # LCが小さすぎる
            if lc_range < 0:
                # LC_rangeがマイナス値　＝　売り注文。その為、ターゲット価格にプラスするとLCPriceとなる
                lc_price_counter = target_price + abs(dependence_lc_range_at_least_c)
                print(s6, "LC価格(Dir1)", target_price, "-", abs(dependence_lc_range_at_least_c))
            else:
                # LC_rangeがプラス値　＝　買い注文。その為、ターゲット価格からマイナスするとＬＣＰｒｉｃｅになる
                lc_price_counter = target_price - abs(dependence_lc_range_at_least_c)
                print(s6, "LC価格(Dir-1)", target_price, "+", abs(dependence_lc_range_at_least_c))
        else:
            # LCRangeが許容範囲内の場合、そのまま利用
            lc_price_counter = temp_lc_price
            print(s6, "そのままのLCを利用する", lc_price_counter)
        # 現在価格との整合性が取れない（即時オーダーとなる場合）があるため、考慮する
        if flag_info['strength_info']['expected_direction'] * -1 == -1:
            # カウンターが売り方向の場合、現在価格よりも下にあるべき。
            if target_price >= peaks[0]['peak']:
                print("★★★整合性のとれないオーダーになりそうだった（売り側）", lc_price_counter, ">", peaks[0]['peak'])
                target_price = peaks[0]['peak'] - 0.035
        else:
            # カウンターが買い方向の場合、現在価格よりも上にあるべき
            if target_price <= peaks[0]['peak']:
                print("★★★整合性のとれないオーダーになりそうだった（買い側）", lc_price_counter, "<", peaks[0]['peak'])
                target_price = peaks[0]['peak'] + 0.035

        main_order_base = cf.order_base(df_r.iloc[0]['close'], df_r.iloc[0]['time_jp'])  # tpはLCChange任せのため、Baseのまま
        # main_order_base['target'] = peaks[1]['peak'] - (0.035 * flag_info['line_base_info']['line_base_direction'])  # river価格＋マージン0.027
        main_order_base['target'] = target_price  # river価格＋マージン0.027
        main_order_base['lc'] = 0.09  # 0.026
        main_order_base['type'] = "LIMIT"
        main_order_base['expected_direction'] = flag_info['strength_info']['expected_direction']  # * -1
        main_order_base['priority'] = 5  # ['strength_info']['priority']
        main_order_base['units'] = main_order_base['units'] * 1
        main_order_base['lc_change'] = lc_change
        main_order_base['name'] = "レンジ" + "カウンター" + flag_info['strength_info']['remark'] + '(count:' + str(
            peaks[0]['count']) + ')'
        main_order_base['y_change'] = flag_info['strength_info']['y_change']
        exe_orders.append(cf.order_finalize(main_order_base))

    print(s4, "オーダー対象", flag_info)
    orders_and_evidence["take_position_flag"] = True  # ここまで来ている＝注文あり
    orders_and_evidence["exe_orders"] = exe_orders
    orders_and_evidence["information"] = flag_info['strength_info']

    print("オーダー表示")
    gene.print_arr(orders_and_evidence["exe_orders"])
    return orders_and_evidence
