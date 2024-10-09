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


def find_same_price_list_from_peaks(target_price, target_dir, peaks_all, predict_flag):
    """
    価格が指定され、それと同じpeakをpeaksから探し出し、リストとして返却する。方向（上端か下端か）は問わない（情報としては取得する）
    target_dirは、抵抗線となりうるポイント(1)か、サポート線となりうるポイント(-1)かを示す。
    引数
    target_price:target_dirとセット
    target_dir: 1(上端)or-1(下端)。target_priceで、なおかつdir(1=upperPeak, -1=lowerPeak)のものを探す。
    predictがTrueの場合は、latestの先に予測船があるかの調査。そのため、between_num調査時に、+1をすると都合が悪いため、アジャスタ＝０
    一方、predictがFalseの場合は、riverを基にした予測線。riverまで除外したピークのため、between_numにはアジャスタ＋１必要（上と逆）。
    そのため、このフラグでアジャスターを調整する。
    返却値
    same_priceのリスト
    """
    # 平均のピークGapを計算する
    sum = 0
    for item in peaks_all:
        sum += item['gap']
    ave = sum / len(peaks_all)

    # ②-1 探索用の変数の準備
    # between_numのカウントをする際の、アジャスタを調整。
    if predict_flag:
        # 予測値を用いた場合は、アジャスタを0にし(latest分)、検索のレンジも少し大きめにする
        start_adjuster = 0
        range_yen = 0.025  # 24/8/21 13:15のデータをもとに設定(0.04 = 指定の0.02×2(上と下分）) 　24/9/18　2.5まで広げてみる（フラッグ見つけやすく）
    else:
        start_adjuster = 1
        range_yen = gene.cal_at_least_most(0.01, round(ave * 0.153, 3), 0.041)  # 0.153倍が一番よかった(大きすぎないレベル）。。
    counter = 0  # 何回同等の値が出現したかを把握する
    depth_point_gap = 0  # 今のピークと一番離れている値、かつ、逆方向のポイント（同価格発見のタイミングでリセット）
    depth_point = 0
    depth_point_time = 0
    depth_break_count = depth_fit_count = 0
    near_point_gap = 100  # 同価格ではないが、一番近い値、かつ、同方向のポイント(同価格を発見のタイミングでリセットされる）
    near_point = 0
    near_point_time = 0
    near_break_count = near_fit_count = 0
    same_list = []
    between_peaks_num = start_adjuster  # 間に何個のピークがあったか。初期値は1としないとなんかおかしなことになる
    # print("　　　　判定閾値", range_yen)
    for i, item in enumerate(peaks_all):
        # 判定を行う
        # print(" 判定", target_price - range_yen, "<", item['peak'], "<=", target_price + range_yen)
        if target_price - range_yen <= item['peak'] <= target_price + range_yen:
            # 同価格があった場合
            if counter == 0:
                # print("target 変更 ", target_price, " ⇒", item['peak'], range_yen)
                # 今回のtargetPriceで最初の発見（最低値か最高値）の場合、それにtargetPriceを合わせに行く(それ基準で近い物を探すため）
                target_price = item['peak']

            # 今後ピークの強さで分岐する？
            if item['peak_strength'] == 0.5:
                print("    (ri)飛ばす可能性のあるPeak(通過確定価格ともいえる？？）", item['time'])

            counter += 1
            # 方向に関する判定
            if item['direction'] == target_dir:
                # print("　　　　同方向の近似ピーク（≒ダブルピークの素）", item['time'], near_point_gap)
                same_list.append({"time": item['time'],
                                  "peak": item['peak'],
                                  "same_dir": True,  # 同じ方向のピークかどうか
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
                                  "peak_strength": item['peak_strength']
                                  })
                # 通過したピーク情報を初期化する
                depth_point_gap = 0
                near_point_gap = 100
                near_break_count = near_fit_count = depth_break_count = depth_fit_count = 0
                between_peaks_num = start_adjuster  # 初期値は1のため注意
            else:
                pass
                # same_dir = False
                # print("　　　逆方向の近似ピーク(= 踊り場的な扱い)")

        else:
            # 通過するピーク（同価格ではない）の場合、記録を残す。
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
                # 同じピークの場合→Nearの方
                # ニアの方の深さの値を取得する
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
            # 最後のピークは同価格でないフラグを立てて、記録する（最後の同価格発見以降に、その価格よりオーバー等があるかを確認するため）
            if i == len(peaks_all) - 1 and len(same_list) != 0:
                # ほかにSamePriceが一つでもあった場合、最後の価格は残す
                # （SamePriceではないが、最後として残すことで、最上位のピークかどうかを判定できるようにする
                # ほかにSamePriceがない場合、この最後の値だけが入ってしまうため、ほかにSamePriceがない場合はスルーする
                same_list.append({"time": item['time'],
                                  "peak": item['peak'],
                                  "same_dir": False,
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
                                  "peak_strength": 0  # peakStrength＝０は、同価格ではない、最後の調査対象価格
                                  })
    # 同価格リスト
    # print("    (ri)ベース価格", target_price, target_price - range_yen, "<r<",
    #       target_price + range_yen,
    #       "許容ギャップ", range_yen, "方向", target_dir, " 平均ピークGap", ave)
    # print("    (ri)同価格リスト↓")
    # gene.print_arr(same_list)
    return same_list


def judge_line_strength_based_each_same_price_list(same_price_list, peaks, base_price, latest_direction):
    """
    ラインの強度を判定する。
    ・引数は同じ価格のリスト（同価格配列リストと、同価格情報）が、形状による強度判定には必要。
    ・同じ価格のリストの最後尾には、必ずstrength０の最後の値が付いてくる（同価格ではないが、調査期間の最後を示すもの）
    ・価格の高さ（一番上か下か）を検証するために、Peakが必要。（形状だけでなく、周辺の状況から高さを求める）
    ・target_price以降の引数は、返却値を整えるためのもの（引っ越し前の関数の名残。。）
    peakの扱い方
    ⇒このSamePriceListのBasePriceがPeaksの中で、どの高さにあるか（一番上の抵抗性なのか？等）を計算するために必要。
    """
    s6 = "      　"
    print(s6, "■JudgeLineStrength")
    # ■リターン値や、各初期値の設定
    minus_counter = 0  # 初期
    line_strength = 0.01
    line_position_strength = 0  # 1の場合は、一番上か一番下を示す（一番下でも-1としない）
    len_of_same_price_list = len(same_price_list) - 1  # 最後に調査最終時刻を示すデータがあるため、実データは-1
    # 調査期間すべてを通じて、最上位（または最下位）のLINEかを確認する。
    all_range_strong_line = sum(item['near_break_count'] for item in same_price_list)  # 0の場合(LINE越が）通算通じて強いLine
    remark = ""
    # 平均値はall_range_strong_lineが０の場合、除算エラーとなるため、ここで計算しておく（０除算とならないような仕組み）
    peak_strength_ave = 0 if len_of_same_price_list == 0 else sum([item['peak_strength'] for item in same_price_list[:-1]]) / len_of_same_price_list

    return_dic = {  # take_position_flagの返却は必須。Trueの場合注文情報が必要。
        "line_strength": line_strength,  # 検証では0は飛ばされてしまう。履歴のために飛ばしたくないため、0以外にしておく
        "line_position_strength": line_position_strength,  # 引数peakの中で、このsamepricelistの価格帯が一番上か。１がトップかボトム。それ以外０ 。
        "priority": 0,  # 基本はLineStrengthの写し。ただし別関数で、フラッグ形状の場合は２が上書きされる
        "line_on_num": 0,
        "same_time_latest": 0,
        "peak_strength_ave": peak_strength_ave,  # itemの最後尾は、peakStrength0の調査期間の最後尾を表すもののため、除外された計算結果
        "remark": ""  # 備考コメントが入る
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
        if min_peak['peak'] + 0.04 > base_price:
            # 最低値の範囲内であれば（0.04は余裕を持っている。同価格のスキップが0.05なので、それ以下に設定している）
            line_position_strength = 1
            print(s6, "最低Line(", base_price, ")", )
        else:
            line_position_strength = 0
            print(s6, "最低ではないLine(", base_price, ")", )
    else:
        # 直近が上方向の場合、上側から確認している（上のLineが最高値かどうかの判定）
        max_index, max_peak = max(enumerate(peaks[:]), key=lambda x: x[1]["peak"])
        if max_peak['peak'] - 0.04 < base_price:
            # 最高値の範囲（最低値より少し下よりも上）であれば
            line_position_strength = 1
            print(s6, "最高Line(", base_price, ")")
        else:
            line_position_strength = 0
            print(s6, "最高ではないLine(", base_price, ")")
    # ■同一価格が存在する場合(直近の同一価格、それ以前の同一価格（複数の可能性もあり）について調査を行う）
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

        if minus_counter > len_of_same_price_list * 0.5:
            # LINE越えが過半数の場合、LINEの信頼度つぃては高くない
            line_strength = 0.1
            remark = "複で越多め"
            # print(s6, "複数時　弱強度", minus_counter, len(same_list))
        elif minus_counter >= 1:
            line_strength = 0.3
            remark = "複でやや越多め"
            # print(s6, "複数時　１つ以上LINE越えあり", minus_counter)
        else:
            # LINE越えがない為、LINEの信頼度が比較的高い
            if len_of_same_price_list == 2:
                line_strength = 0.9
                remark = "複強め（2個のみ）"
            else:
                line_strength = 1  # 最も強い
                remark = "複強め"
            # print(s6, "複数時　強強度", minus_counter, len(same_list))

    # 返却値の整理
    return_dic["line_strength"] = line_strength
    return_dic["priority"] = line_strength
    return_dic["line_on_num"] = len_of_same_price_list
    return_dic['line_position_strength'] = line_position_strength
    return_dic["same_time_latest"] = 0 if len(same_price_list) == 0 else same_price_list[0]['time']
    return_dic['all_range_strong_line'] = all_range_strong_line  # 0が強い(Break回数が０）
    return_dic["remark"] = remark
    return return_dic


def update_line_strength(predict_line_info_list, double_peak_flag):
    """
    LINEが複数個ある場合、少し優先度を変更していく
    すでにLINEのストレングスまで算出された状態で実行される
    なおpredict_line_info_listは算出の特性上、
    [0]が最も現在価格から離れた位置にあり、添え字が大きくなればなるほど現在価格に近いLineとなる
    """
    print(" LINEが複数ある場合、お互いの関係性を考慮してストレングスを算出し、上書きして返却する")
    # ベースの情報を取得
    latest_direction = predict_line_info_list[0]['line_base_info']['latest_direction']
    print("     ベース情報 LatestDirection", latest_direction)

    # すべて方向が同じ場合は、現在価格に近いほうのストレングスを半減させる（超えて、もう一つのLineまで行く可能性が高い？）
    # lineと逆方向（逆張り思想と同じもの）の一覧を取得
    revers_lines = [item for item in predict_line_info_list if item["same_price_list"][0]['direction'] == latest_direction]
    print("     条件　Line個数:逆思想のLine個数", len(predict_line_info_list), len(revers_lines))
    if len(predict_line_info_list) == len(revers_lines):
        print("     すべて逆張り思想のLINE⇒手前側のストレングスを低減")
        # [0] が最も強い抵抗であるべき⇒[1]以降の抵抗を下げる
        for i, item in enumerate(predict_line_info_list):
            if i == 0:
                # 最も強くあるべき線（現在価格から遠い）
                line_strength_for_update = 1  # 1でストレングスを上書き
            else:
                # 中間地点たちのもの
                line_strength_for_update = 0.76  # 通過にならないぎりぎりの線で上書き
            item['strength_info']['line_strength'] = line_strength_for_update  # 上書き作業を実行
    else:
        print("     そうでもない（とりあえず何もしない）")

    # ダブルトップ形状直後の場合、最上値まで戻っていく前提のオーダーにしてみる
    if double_peak_flag:
        for i, item in enumerate(predict_line_info_list):
            if i == 0:
                # 最も強くあるべき線（現在価格から遠い）
                line_strength_for_update = 1  # 1でストレングスを上書き
            else:
                # 中間地点たちを通過にしなおす。
                print("   ダブルトップ直後で戻り強い可能性")
                line_strength_for_update = 0.5  # 通過にならないぎりぎりの線で上書き
            item['strength_info']['line_strength'] = line_strength_for_update  # 上書き作業を実行

    return predict_line_info_list


def judge_flag_figure(peaks, target_direction, line_strength):
    """
    フラッグ形状かどうかを判定する。
    peaks:元となるピークス。
    target_direction: この方向のピーク群が斜め上がり傾向になっているかを検証する（Upperが水平でLowerを検証したい場合、ここはー１が渡される）
    返り値は、成立しているかどうかのBoolean
    """
    s6 = "      "
    flag_figure_total = False  # これは返り値

    long_range_flag_info = judge_flag_figure_sub_function(peaks, target_direction, 5)
    long_range_flag = long_range_flag_info['flag_figure']
    short_range_flag_info = judge_flag_figure_sub_function(peaks, target_direction, 3)
    short_range_flag = short_range_flag_info['flag_figure']

    if line_strength == 1:
        # 最も強い抵抗線を持っている場合,ロングレンジでの判定のみ
        flag = long_range_flag
        remark = long_range_flag_info['remark']
    else:
        # ピークが2個程度の場合、ロング＋ショートレンジで必要
        if long_range_flag and short_range_flag:
            flag = True
        else:
            flag = False
        # 備考（ポジションの名前になる）を生成
        remark = gene.str_merge("Short:", short_range_flag_info['remark'], "Long", long_range_flag_info['remark'])
        # 【暫定処理】フラッグが少なくてさみしいので、、ロングでなってればOKにする（めんどくさいからフラグ上書き）
        flag = long_range_flag

    print(s6, "Flag形状確認", long_range_flag, short_range_flag, "結論", flag)

    return {
        "flag_figure": flag,
        "lc": short_range_flag_info['lc'],  # こっちのほうがlongよりLC幅が狭いので。いつかリスクを追う場合は、Longに？）
        "remark": remark
    }


def judge_flag_figure_sub_function(peaks, latest_direction, num):
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
    print(s7, "□　Flag確認関数")
    if latest_direction == 1:
        # ■■■直近の同価格ピークがUpper側だった場合の、反対のLowerのPeaksを求める　（一つ（すべて向きは同じはず）の方向を確認、）
        opposite_peaks = [item for item in peaks if item["direction"] == -1]  # 利用するのは、Lower側
        opposite_peaks = opposite_peaks[:num]  # 直近5個くらいでないと、昔すぎるのを参照してしまう（線より下の個数が増え、判定が厳しくなる）
        print(s7, "Opposite latest==1")
        gene.print_arr(opposite_peaks, 7)

        # 直近の一番下の値と何番目のピークだったかを求める
        min_index, min_info = min(enumerate(opposite_peaks), key=lambda x: x[1]["peak"])
        # print("    (ri)最小値とそのインデックス", min_info['peak'], min_index)
        # そのMinを原点として、直近Peakまでの直線の傾きを算出する(座標で言うx軸は秒単位）
        # yの増加量(価格の差分)　/ xの増加量(時間の差分)
        x_change_sec = (gene.cal_at_least(0.001,
                                          gene.cal_str_time_gap(min_info['time'], opposite_peaks[0]['time'])[
                                              'gap_abs'].seconds))  # ０にならない最低値を設定する
        tilt = (opposite_peaks[0]['peak'] - min_info['peak']) / x_change_sec
        if tilt >= 0:
            # print(s7, "(ri)tiltがプラス値。想定されるLowerのせり上がり")
            pass
        else:
            # print(s7, "(ri)tiltがマイナス値。広がっていく価格で、こちらは想定外")
            pass
        # 集計用の変数を定義する
        total_peaks_num = min_index + 1  # 母数になるPeaksの個数(最小値の場所そのものだが、直近の場合添え字が０なので、＋１で底上げ）
        clear_peaks_num = failed_peaks_num = 0  # 上側にある（＝合格）と下側にある（＝不合格）の個数
        on_line = 0  # 線上にあるものもカウントし、よりフラッグ形状であることを示したい
        # 各要素がその直線（0.05pipsの切片分だけ余裕をとる）より上にあるかを確認する
        for i, item in enumerate(opposite_peaks):
            # iがmin_indexを超える場合は終了する
            if i >= min_index:
                # print(s7, "(ri)breakします", i, min_index)
                break
            # thisの座標(a,b)を取得する
            a = gene.cal_str_time_gap(min_info['time'], item['time'])['gap_abs'].seconds  # 時間差分
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
            # ■線上といえるか
            c2 = 0.06
            jd_y_max = tilt * a + c2
            if jd_y_max > b > jd_y:
                # print(s7, "(ri)線上にあります")
                on_line += 1
            else:
                # print(s7, "(ri)線上にはありません")
                pass
        # 集計結果
        # print(s7, "(ri)全部で", total_peaks_num, '個のピークがあり、合格（上の方にあった）のは', clear_peaks_num,
        #       "不合格は", failed_peaks_num)
        # print(s7, "(ri)割合", clear_peaks_num / total_peaks_num * 100)
        # print(s7, "(ri)線上にあった数は", on_line, "割合的には", on_line / total_peaks_num * 100)
        if clear_peaks_num / total_peaks_num * 100 >= 60:  # 傾きに沿ったピークであるが、最小値が例外的な低い値の可能性も）
            if on_line / total_peaks_num * 100 >= 35:  # さらに傾きの線上に多い場合⇒間違えなくフラッグといえる
                print(s7, "(ri)Lowerの継続した上昇とみられる⇒検出したupperは突破される方向になる")
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
    else:
        # ■■■直近の同価格ピークがLower側だった場合の、反対のUpperPeaksを求める　（一つ（すべて向きは同じはず）の方向を確認、）
        opposite_peaks = [item for item in peaks if item["direction"] == 1]  # 利用するのは、Upper側
        opposite_peaks = opposite_peaks[:num]  # 直近5個くらいでないと、昔すぎるのを参照してしまう（線より下の個数が増え、判定が厳しくなる）
        print(s7, "Opposite latest==-1")
        gene.print_arr(opposite_peaks, 7)

        # 直近の一番下の値と何番目のピークだったかを求める
        max_index, max_info = max(enumerate(opposite_peaks), key=lambda x: x[1]["peak"])
        # print("    (ri)最大値とそのインデックス", max_info['peak'], max_index)
        # そのMinを原点として、直近Peakまでの直線の傾きを算出する(座標で言うx軸は秒単位）
        # yの増加量(価格の差分)　/ xの増加量(時間の差分)
        x_change_sec = gene.cal_at_least(1, gene.cal_str_time_gap(max_info['time'], opposite_peaks[0]['time'])[
            'gap_abs'].seconds)
        tilt = (opposite_peaks[0]['peak'] - max_info['peak']) / x_change_sec  # こちらはマイナスが期待される（下りのため）
        if tilt >= 0:
            # print(s7, "(ri)tiltがプラス値。広がっていく価格でこちらは想定外")
            pass
        else:
            # print(s7, "(ri)tiltがマイナス値。Upperが上から降りてくる、フラッグ形状")
            pass
        # 集計用の変数を定義する
        total_peaks_num = max_index + 1  # 母数になるPeaksの個数(最小値の場所そのもの）０の可能性があるため、個数を表現するために＋１
        clear_peaks_num = failed_peaks_num = 0  # 上側にある（＝合格）と下側にある（＝不合格）の個数
        on_line = 0  # 線上にあるものもカウントし、よりフラッグ形状であることを示したい
        # 各要素がその直線（0.05pipsの切片分だけ余裕をとる）より上にあるかを確認する
        for i, item in enumerate(opposite_peaks):
            # iがmin_indexを超える場合は終了する
            if i >= max_index:
                # print(s7, "(ri)検証終了？breakします", i, max_index)
                break
            # thisの座標(a,b)を取得する
            a = gene.cal_str_time_gap(max_info['time'], item['time'])['gap_abs'].seconds  # 時間差分
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
            c2 = -0.04
            jd_y_max = tilt * a + c2
            if jd_y_max < b < jd_y:
                # print(s7, "(ri)線上にあります")
                on_line += 1
            else:
                # print(s7, "(ri)線上にはありません")
                pass
        # 集計結果
        # print(s7, "(ri)全部で", total_peaks_num, 'このピークがあり、合格（上にあった）のは', clear_peaks_num,
        #       "不合格は", failed_peaks_num)
        # print(s7, "(ri)割合", clear_peaks_num / total_peaks_num * 100)
        if clear_peaks_num / total_peaks_num * 100 >= 60:
            if on_line / total_peaks_num * 100 >= 40:
                print(s7, "(ri)upperの継続した下落とみられる⇒　このLINEは下に突破される方向になる")
                flag_figure = True
                remark = "フラッグ形状(Upper下落)"
                # tk.line_send(s7, "(ri)フラッグ型（lower水平upper下落）の検出", num)
            else:
                print(s7, "(ri)upperの継続した下落だが、突発的な高さがあった可能性あり 3個以上のピークで強力なLINE　　ストレングス変更なし")
                # tk.line_send(s7, "(ri)フラッグ型なり損ね、lowerはサポート", num)
                pass
        else:
            print(s7, "(ri)upperに傾向性のある下降なし。レンジとみなせる。　ストレングス変更なし", num)
            pass

    # gene.print_arr(opposite_peaks)
    # LC値の参考地のため、opposite_peaksについて調査する
    total_peak = sum(item["peak"] for item in opposite_peaks)
    count = len(opposite_peaks)
    ave_peak_price = round(total_peak / count, 3)
    lc_margin = 0.01 * latest_direction * -1
    ave_peak_price = ave_peak_price + lc_margin
    print(s7, "OppositePeakAve", ave_peak_price)
    return {
        "flag_figure": flag_figure,  # フラッグ形状かどうかの判定（Boo）
        "lc": ave_peak_price,  # LC価格の提案を行う
        "remark": remark
    }


def judge_strength_from_predict_line_based_all_same_price_list(dic_args):
    """
    引数はDFやピークスなど
    """
    # ■返却値等を設定しておく
    # ■■途中までのLINEリストの構造
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
                "lc": 0,  # 途中でStrengthInfoに追加される。価格の場合と、レンジの場合が混在する
            }
        }
    # 表示時のインデント
    s4 = "    "
    s6 = "      "
    # リストの原型（これを上書きし、下のリストに追加していく）
    predict_line_info_list = []  # 実際に返却されるリスト
    # ■■　オーダーまでを加味すると、以下の返却値
    orders_and_evidence = {
        "take_position_flag": False,
        "exe_orders": [],
        "target_strength_info": {},  # オーダーにつながった、最強Line単品の情報
        "evidence": predict_line_info_list  # 全同一価格
    }

    # ■関数の開始準備（表示と情報の清流化）
    print(s4, "■find_predict_line_based_latest関数")
    fixed_information = cf.information_fix(dic_args)  # DFとPeaksが必ず返却される
    # 情報の取得
    target_df = fixed_information['df_r']
    peaks = fixed_information['peaks']
    target_dir = peaks[0]['direction']  # Lineの方向 予測ではLatest。値が1の場合UpperLine（＝上値抵抗）
    grid = 0.01  # 調査の細かさ
    # 条件を達成していない場合は実行せず
    if len(peaks) < 4:
        # ■ループの際、数が少ないとエラーの原因になる。３個切る場合ば終了（最低３個必要）
        return orders_and_evidence
        # return orders_and_info
    # 各変数の設定（動的な値）
    min_max_search_range = 11
    max_index, max_peak_info_in_latest4 = max(enumerate(peaks[:min_max_search_range]), key=lambda x: x[1]["peak"])
    min_index, min_peak_info_in_latest4 = min(enumerate(peaks[:min_max_search_range]), key=lambda x: x[1]["peak"])
    # print("    (rip)最大最小値検索範囲")
    # gene.print_arr(peaks[:min_max_search_range])
    # print("    (rip)その中の最大価格、最小価格", max_peak_info_in_latest4['peak'], min_peak_info_in_latest4['peak'])
    # 調査価格情報の設定と情報格納
    max_to_min_search = True  # Latestが上昇方向の場合、Maxから降りるように調査する＝加工の場合はMinから上るように調査(初期志向）(Falseで逆になる)
    if target_dir == 1:
        # latestが登り方向の場合
        search_max_price = max_peak_info_in_latest4['peak'] + grid  # 探索する最高値
        search_min_price = peaks[0]['peak']  # 探索する最低値。(現在価格）
        if max_to_min_search:
            # 簡単に切り替えられるように（変更点が複数あるため、一括で変更できるようにした）
            target_price = search_max_price  # - grid  # MAX側から調査（登りの場合、上から調査）
        else:
            target_price = search_min_price  # + grid  # 登りの場合でもMinからスタート
    else:
        # latestが下り方向の場合
        search_max_price = peaks[0]['peak']  # 探索する最低値
        search_min_price = min_peak_info_in_latest4['peak'] - grid  # 探索する最低値。
        if max_to_min_search:
            target_price = search_min_price  # + grid  # 下（Min）からスタート
        else:
            target_price = search_max_price  # - grid  # 下りの場合でもMAXからスタート
    # 返り値への登録(LIneBaseInfo)
    predict_line_info_list_base['line_base_info']['line_base_time'] = peaks[0]['time']
    predict_line_info_list_base['line_base_info']['line_base_price'] = target_price  # 暫定値
    predict_line_info_list_base['line_base_info']['line_base_direction'] = target_dir
    predict_line_info_list_base['line_base_info']['latest_direction'] = peaks[0]['direction']
    predict_line_info_list_base['line_base_info']['latest_time_in_df'] = peaks[0]['time']
    predict_line_info_list_base['line_base_info']['decision_price'] = target_df.iloc[0]['close']
    print(s6, "■価格と方向", target_dir, "調査範囲:", search_min_price, "<=", target_price, "<=", search_max_price)
    print(s6, "LineBaseInfo(参考表示)↓")
    print(s6, predict_line_info_list_base['line_base_info'])

    # ■同一価格の調査を開始
    while search_min_price <= target_price <= search_max_price:
        # print("    (rip)◆◆", target_price)
        same_price_list = find_same_price_list_from_peaks(target_price, target_dir, peaks, True)  # ★★
        same_price_list = [d for d in same_price_list if d["time"] != peaks[0]['time']]  # Latestは削除する(predict特有）
        # print("    (rip)同価格リスト (Latestピークを削除後)↓　最終時刻は", peaks[0]['time'])
        # gene.print_arr(same_price_list)

        if len(same_price_list) == 1:
            # 現時刻を消したうえで、内容が一つだけになっている場合、それは最後の時刻のもの（sameprice検索の使用でついてきてしまう）
            same_price_list = []
            # print(" 　　　(rip)最終時刻のもののみのため、スキップ")

        if len(same_price_list) >= 1:
            # 同価格リストが1つ以上発見された場合、範囲飛ばしと、返却値ベースへの登録を行う
            predict_line_info_list_base['line_base_info']['line_base_price'] = round(target_price, 3)  # 上書き
            predict_line_info_list_base['same_price_list'] = same_price_list
            predict_line_info_list.append(copy.deepcopy(predict_line_info_list_base))  # 一部の情報を返り値情報に追加
            # print("     (rip) --SkipperOn---")
            # print(same_price_list)
            skipper = 0.03
        else:
            skipper = 0

        # ④次のループへの準備★【重要部位】
        grid_adj = grid + skipper  # skipperをあらかじめgridに付加しておく（最後にスキッパーの除外も必要）
        if target_dir == 1:
            # latest(想定するLINEが上方向）が登り方向の場合
            if max_to_min_search:  # 上から下に価格を探す場合
                target_price = target_price - grid_adj
            else:
                target_price = target_price + grid_adj
        else:
            if max_to_min_search:
                target_price = target_price + grid_adj
            else:
                target_price = target_price - grid_adj

    print(s6, "■【最終】samePrimeLists結果", len(predict_line_info_list))
    gene.print_arr(predict_line_info_list, 6)

    # ■各Lineのストレングスを求める　（Lineが存在しない場合、終了）
    if len(predict_line_info_list) == 0:
        # same_priceがない場合、次のループへ
        print("     ★同価格なし⇒終了")
        return orders_and_evidence
        # return orders_and_info
    # ■■各同価格帯の強度を求める(この時点でSamePriceListが存在す＝Strengthは０以外が必ず付与される）
    for i, each_predict_line_info in enumerate(predict_line_info_list): # each_predict_line_infoはpredict_line_info_list_base同等
        print(s6, "■■各同一価格リストの強度確認", len(predict_line_info_list))
        print(s6, "各ベース価格")
        print(s6, each_predict_line_info['line_base_info']["line_base_price"],
              each_predict_line_info['line_base_info'])
        print(s6, "各同価格リスト↓")
        gene.print_arr(each_predict_line_info['same_price_list'], 7)
        # print("   シンプルな強度（形状をあまり見ない判定）")
        # ■■ライン強度検証の関数の呼び出し（ここで初めてストレングスを取得する）
        each_strength_info = judge_line_strength_based_each_same_price_list(
            each_predict_line_info['same_price_list'],
            peaks,
            each_predict_line_info['line_base_info']["line_base_price"],
            each_predict_line_info['line_base_info']["latest_direction"]
        )
        print("         強度結果", each_strength_info)
        # ■■■　【注文に必要な情報】ExpectedDirectionとLCを求め、StrengthInfoに初めて追加する（処理が遠い順のため、一つ遠いものがロスカット価格となる）
        far_lc_range = 0.07  # 一番遠い物のLC幅
        range_margin = 0.05
        # ■expectedDirectionを追加する（この後のフラッグで上書きされる可能性ある）
        each_strength_info['expected_direction'] = peaks[0]['direction'] * -1  # 逆
        # ■LCの追加
        if i == 0:
            # 初回のみ（一番遠い値）は、LCを適当に設定する（本当はこれが一番大事？！）
            each_strength_info['lc'] = far_lc_range
        else:
            if each_strength_info['expected_direction'] == 1:
                each_strength_info['lc'] = round(predict_line_info_list[i - 1]['line_base_info']["line_base_price"] + range_margin, 3)
            else:
                each_strength_info['lc'] = round(predict_line_info_list[i - 1]['line_base_info']["line_base_price"] - range_margin, 3)

        # ■■■フラッグかどうかを判定（Line強度とは別の関数にする）
        # if each_strength_info['all_range_strong_line'] == 0 and each_strength_info['line_on_num'] >= 3:  # 旧条件　かなり厳しい
        # if each_strength_info['line_on_num'] >= 3 and each_strength_info['line_strength'] == 1:  # 旧条件２　少し厳しい
        if each_strength_info['line_on_num'] >= 2 and each_strength_info['line_strength'] == 0.9:  # allRangeは不要か
            flag = judge_flag_figure(peaks, peaks[0]['direction'], each_strength_info['line_strength'])
            print(s6, "[Flagテスト]", each_predict_line_info['line_base_info']["line_base_price"])
            # フラッグの結果次第で、LineStrengthに横やりを入れる形で、値を買い替える
            if flag['flag_figure']:
                print(s6, "Flag成立")
                # 【注文に必要な情報】フラッグ形状の場合は上書きする
                each_strength_info['line_strength'] = -1  # フラッグ成立時は、通常とは逆
                each_strength_info['lc'] = flag['lc']
                each_strength_info['expected_direction'] = peaks[0]['direction']
                each_strength_info['remark'] = flag['remark']
                each_strength_info['priority'] = 2  # 備考を入れておく
                predict_line_info_list_base['strength_info'] = each_strength_info  # 上書きする

        # ■　結果を返却用配列に追加する(各要素に対して書き換えを行う。eachはpredict_line_info_list_baseと同様）
        each_predict_line_info['strength_info'] = each_strength_info  # Strengthに追加（上書き）

    # ■オーダーを作成する
    # ■■最も強いストレングスについての単発オーダー生成
    print(s4, "■最大LineStrengthのオーダー作成")
    exe_orders = []
    #  predict_line_listは添え字０から現在価格から遠いほうに並んでいる。その為、同値のストレングスがある場合、遠いほう（添え字が０に近い）が選ばれる
    max_index, max_strength = max(enumerate(predict_line_info_list[:]), key=lambda x: x[1]["strength_info"]["line_strength"])
    min_index, min_strength = min(enumerate(predict_line_info_list[:]), key=lambda x: x[1]["strength_info"]["line_strength"])  # 念のために取得
    flag_strength = [d for d in predict_line_info_list if d["strength_info"]["line_strength"] == -1]  # フラッグ形状の場合はこれが存在

    if len(flag_strength) != 0:
        target_strength_info = flag_strength[0]  # flag_strength は配列のため、要素としたいため、[0]とする
        print(s4, "フラッグがSameList内に存在")
    else:
        target_strength_info = max_strength

    # if min_strength["strength_info"]["line_strength"] == -1:
    #     # フラッグ形状がある場合、最小（フラッグの場合は-1となっており、これは最小値（突破）を意味する）を持つ情報でオーダー
    #     target_strength_info = min_strength#
    #     print(s4, "フラッグがSameList内に存在")
    # else:
    #     # それ以外は、最大のストレングス（抵抗線としての強さ）を採用
    #     target_strength_info = max_strength
    print(s4, "オーダー対象", target_strength_info)
    main_order_base = cf.order_base(cf.now_price())
    main_order_base['target'] = target_strength_info['line_base_info']['line_base_price']
    main_order_base['tp'] = 0.3  # 0.09  # LCは広め
    main_order_base['lc'] = target_strength_info["strength_info"]["lc"]  # * line_strength  # 0.09  # LCは広め
    main_order_base['type'] = 'LIMIT'
    main_order_base['expected_direction'] = target_strength_info['strength_info']['expected_direction']
    main_order_base['priority'] = target_strength_info['strength_info']['priority']
    main_order_base['units'] = main_order_base['units'] * 1
    main_order_base['name'] = target_strength_info['strength_info']['remark'] + str(main_order_base['priority'])
    # main_order_base['lc_change'] = []
    # gene.print_json(cf.order_finalize(main_order_base))
    print("ResLinInspec", main_order_base)
    exe_orders.append(cf.order_finalize(main_order_base))

    # 返却する
    orders_and_evidence["take_position_flag"] = True  # ここまで来ている＝注文あり
    orders_and_evidence["exe_orders"] = exe_orders
    # orders_and_evidence["target_strength_info"] = target_strength_info
    orders_and_evidence["evidence"] = predict_line_info_list
    return orders_and_evidence


def judge_strength_river_peak_line(dic_args):
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
            "each_strength_info": {  # strength関数で取得（その後の上書きあり）
                "line_strength": 0,
                "line_position_strength": 0,
                "line_on_num": 0,
                "same_time_latest": 0,
                "all_range_strong_line": 0,
                "remark": "",
                "lc": 0,  # 途中でStrengthInfoに追加される。価格の場合と、レンジの場合が混在する
            }
        }
    # 表示時のインデント
    ts = "    "
    s6 = "      "
    # リストの原型（これを上書きし、下のリストに追加していく）
    predict_line_info_list = []  # 実際に返却されるリスト
    # ■■　オーダーまでを加味すると、以下の返却値
    orders_and_evidence = {
        "take_position_flag": False,
        "exe_orders": [],
        "evidence": predict_line_info_list
    }

    # ■関数の開始準備（表示と情報の清流化）
    print(ts, "■river側のLineStrength（latest延長を基本とした場合、river側に戻ってくるかどうか？）")
    fixed_information = cf.information_fix(dic_args)  # DFとPeaksが必ず返却される
    target_df = fixed_information['df_r']
    peaks = fixed_information['peaks']

    # ■実際の調査の開始
    double_top_same_price_list = find_same_price_list_from_peaks(peaks[1]['peak'], peaks[1]['direction'], peaks, False)
    if len(double_top_same_price_list) != 0:
        # 同価格が存在する場合
        oppo_strength_info = judge_line_strength_based_each_same_price_list(
            double_top_same_price_list,
            peaks,
            peaks[1]['peak'],
            peaks[1]['direction']
        )  # ■■LINE強度の検証関数の呼び出し
        # print(s4, oppo_strength_info)
        if oppo_strength_info['line_strength'] >= 0.9:
            now_double_peak_gap = peaks[0]['gap']
            print(s6, "反対側に強い抵抗.価格:",peaks[1]['peak'], "強さ", oppo_strength_info['line_strength'],
                         "Gap", now_double_peak_gap)
    else:
        tk.line_send(s6, "反対が存在しないケース　不思議なケース(下でoppoが使えない)")


def judge_strength_double_top_break(dic_args):
    """
    ダブルトップを突破する強度。

    （基本的にLineの強度は、折り返す強さであらわされるため、突破する場合は強度はー１と表現される。）

    """
    # 表示時のインデント
    ts = "    "
    s6 = "      "
    # リストの原型（これを上書きし、下のリストに追加していく）
    predict_line_info_list = []  # 実際に返却されるリスト
    # ■■　オーダーまでを加味すると、以下の返却値
    orders_and_evidence = {
        "take_position_flag": False,
        "exe_orders": [],
        "evidence": predict_line_info_list
    }

    # ■関数の開始準備（表示と情報の清流化）
    print(ts, "■ダブルトップ突破形状の確認")
    fixed_information = cf.information_fix(dic_args)  # DFとPeaksが必ず返却される
    target_df = fixed_information['df_r']
    peaks = fixed_information['peaks']

    # ■■DoublePeak系の判断　（これは上記のLineStrengthとは独立の考え方に近い）
    double_peak_break_orders_and_evidence = dp.DoublePeak_predict({"df_r": target_df, "peaks": peaks})


    return double_peak_break_orders_and_evidence


# def find_predict_line_based_latest_for3(dic_args):
#     """
#     引数はDFやピークスなど
#     """
#     # ■返却値を設定しておく
#     predict_line_info_list_base = {
#             "line_base_info": {
#                 "line_base_time": 0,  # 予測では将来的に到達する場所のため、設定不可（とりあえず現在時刻？）
#                 "line_base_price": 0,  # 予測ではループで探すことになる（後で上書きする）、通常ではRiver価格
#                 "line_base_direction": 0,  # 予測ではLatest、通常はRiver。値が1の場合UpperLine（＝上値抵抗）
#                 "latest_direction": 0,  # 渡されたPeaksの直近の方向（＝直近の方向）
#                 "latest_time_in_df": 0,  # Latest。直近の時間（渡されたDFで判断）
#                 "decision_price": 0,
#             },
#             "same_price_list": [],
#             "strength_info": {  # strength関数で取得（その後の上書きあり）
#                 "line_strength": 0,
#                 "line_position_strength": 0,
#                 "line_on_num": 0,
#                 "same_time_latest": 0,
#                 "all_range_strong_line": 0,
#                 "remark": "",
#                 "order_before_finalized": {}  # 突破型のみ入っていく（これがそのままオーダーされる）
#             }
#         }
#     # 返却するリストの原型（これを上書きし、下のリストに追加していく）
#     predict_line_info_list = []  # 実際に返却されるリスト
#     predict_lint_info_list_error_return = [predict_line_info_list_base]  # エラーの時に返却される値
#
#     # ■関数の開始準備（表示と情報の清流化）
#     print("    find_predict_line_based_latest関数")
#     fixed_information = cf.information_fix(dic_args)  # DFとPeaksが必ず返却される
#     # 情報の取得
#     target_df = fixed_information['df_r']
#     peaks = fixed_information['peaks']
#     target_dir = peaks[0]['direction']  # Lineの方向 予測ではLatest、通常はRiver。値が1の場合UpperLine（＝上値抵抗）
#     grid = 0.01  # 調査の細かさ
#     # 条件を達成していない場合は実行せず
#     if len(peaks) < 4:
#         # ■ループの際、数が少ないとエラーの原因になる。３個切る場合ば終了（最低３個必要）
#         return predict_lint_info_list_error_return
#     # 各変数の設定（動的な値）
#     min_max_search_range = 11
#     max_index, max_peak_info_in_latest4 = max(enumerate(peaks[:min_max_search_range]), key=lambda x: x[1]["peak"])
#     min_index, min_peak_info_in_latest4 = min(enumerate(peaks[:min_max_search_range]), key=lambda x: x[1]["peak"])
#     # print("    (rip)最大最小値検索範囲")
#     # gene.print_arr(peaks[:min_max_search_range])
#     # print("    (rip)その中の最大価格、最小価格", max_peak_info_in_latest4['peak'], min_peak_info_in_latest4['peak'])
#     # 調査価格情報の設定と情報格納
#     max_to_min_search = True  # Latestが上昇方向の場合、Maxから降りるように調査する＝加工の場合はMinから上るように調査(初期志向）(Falseで逆になる)
#     if target_dir == 1:
#         # latestが登り方向の場合
#         search_max_price = max_peak_info_in_latest4['peak'] + grid  # 探索する最高値
#         search_min_price = peaks[0]['peak']  # 探索する最低値。(現在価格）
#         if max_to_min_search:
#             # 簡単に切り替えられるように（変更点が複数あるため、一括で変更できるようにした）
#             target_price = search_max_price  # - grid  # MAX側から調査（登りの場合、上から調査）
#         else:
#             target_price = search_min_price  # + grid  # 登りの場合でもMinからスタート
#     else:
#         # latestが下り方向の場合
#         search_max_price = peaks[0]['peak']  # 探索する最低値
#         search_min_price = min_peak_info_in_latest4['peak'] - grid  # 探索する最低値。
#         if max_to_min_search:
#             target_price = search_min_price  # + grid  # 下（Min）からスタート
#         else:
#             target_price = search_max_price  # - grid  # 下りの場合でもMAXからスタート
#     # 返り値への登録(LIneBaseInfo)
#     predict_line_info_list_base['line_base_info']['line_base_time'] = peaks[0]['time']
#     predict_line_info_list_base['line_base_info']['line_base_price'] = target_price
#     predict_line_info_list_base['line_base_info']['line_base_direction'] = target_dir
#     predict_line_info_list_base['line_base_info']['latest_direction'] = peaks[0]['direction']
#     predict_line_info_list_base['line_base_info']['latest_time_in_df'] = peaks[0]['time']
#     predict_line_info_list_base['line_base_info']['decision_price'] = target_df.iloc[0]['close']
#     print("    ■価格と方向", target_dir, "調査範囲:", search_min_price, "<=", target_price, "<=", search_max_price)
#     print("    　LineBaseInfo(参考表示)↓")
#     print("     ", predict_line_info_list_base['line_base_info'])
#
#     # ■同一価格の調査を開始
#     while search_min_price <= target_price <= search_max_price:
#         # print("    (rip)◆◆", target_price)
#         same_price_list = find_same_price_list_from_peaks(target_price, target_dir, peaks, True)
#         same_price_list = [d for d in same_price_list if d["time"] != peaks[0]['time']]  # Latestは削除する(predict特有）
#         # print("    (rip)同価格リスト (Latestピークを削除後)↓　最終時刻は", peaks[0]['time'])
#         # gene.print_arr(same_price_list)
#
#         if len(same_price_list) == 1:
#             # 現時刻を消したうえで、内容が一つだけになっている場合、それは最後の時刻のもの（sameprice検索の使用でついてきてしまう）
#             same_price_list = []
#             # print(" 　　　(rip)最終時刻のもののみのため、スキップ")
#
#         if len(same_price_list) >= 1:
#             # 同価格リストが1つ以上発見された場合、範囲飛ばしと、返却値ベースへの登録を行う
#             predict_line_info_list_base['line_base_info']['line_base_price'] = round(target_price, 3)
#             predict_line_info_list_base['same_price_list'] = same_price_list
#             predict_line_info_list.append(copy.deepcopy(predict_line_info_list_base))  # 一部の情報を返り値情報に追加
#             # print("     (rip) --SkipperOn---")
#             # print(same_price_list)
#             skipper = 0.05
#         else:
#             skipper = 0
#
#         # ④次のループへの準備★【重要部位】
#         grid_adj = grid + skipper  # skipperをあらかじめgridに付加しておく（最後にスキッパーの除外も必要）
#         if target_dir == 1:
#             # latest(想定するLINEが上方向）が登り方向の場合
#             if max_to_min_search:  # 上から下に価格を探す場合
#                 target_price = target_price - grid_adj
#             else:
#                 target_price = target_price + grid_adj
#         else:
#             if max_to_min_search:
#                 target_price = target_price + grid_adj
#             else:
#                 target_price = target_price - grid_adj
#
#     print("    ■【最終】samePrimeLists結果")
#     for item in predict_line_info_list:
#         print("     ", item)
#     # gene.print_arr(predict_line_info_list)
#
#     # ■各Lineのストレングスを求める　（Lineが存在しない場合、終了）
#     if len(predict_line_info_list) == 0:
#         # same_priceがない場合、次のループへ
#         print("     ★同価格なし⇒終了")
#         return predict_lint_info_list_error_return
#     # ■■各同価格帯の強度を求める
#     for each_predict_line_info in predict_line_info_list:  # each_predict_line_infoはpredict_line_info_list_base同等
#         print("    ■■ 各同一価格リストの強度確認")
#         print("      各ベース価格")
#         print("      ", each_predict_line_info['line_base_info']["line_base_price"],
#               each_predict_line_info['line_base_info'])
#         print("      各同価格リスト↓")
#         gene.print_arr(each_predict_line_info['same_price_list'], 7)
#         # print("   シンプルな強度（形状をあまり見ない判定）")
#         strength_info = judge_line_strength_based_same_price_list(
#             each_predict_line_info['same_price_list'],
#             peaks,
#             each_predict_line_info['line_base_info']["line_base_price"],
#             each_predict_line_info['line_base_info']["latest_direction"]
#         )  # ■■LINE強度の検証関数の呼び出し
#         print("      ", strength_info)
#         # フラッグかどうかを判定（Line強度とは別の関数にする）
#         # if strength_info['all_range_strong_line'] == 0 and strength_info['line_on_num'] >= 3:  # 旧条件
#         if strength_info['line_on_num'] >= 3 and strength_info['line_strength'] == 1:  # allRangeは不要か
#             flag = judge_flag_figure(peaks, peaks[0]['direction'], strength_info['line_strength'])
#             print("     ★★Flagテスト", each_predict_line_info['line_base_info']["line_base_price"])
#             # フラッグの結果次第で、LineStrengthに横やりを入れる形で、値を買い替える
#             if flag:
#                 strength_info['line_strength'] = -1  # フラッグ成立時は、通常とは逆
#                 strength_info['remark'] = "フラッグ形状"  # 備考を入れておく
#                 # 以下暫定（オーダー複数個になる対策として、フラッグありの場合は、フラッグ部分のみに置き換えてしまう）
#                 predict_line_info_list_base['line_base_info'] = each_predict_line_info['line_base_info']  # 上書き
#                 predict_line_info_list_base['same_price_list'] = each_predict_line_info['same_price_list']
#                 predict_line_info_list_base['strength_info'] = strength_info
#                 predict_line_info_list = [predict_line_info_list_base]  # ■フラッグ検出の場合は、思い切ってオーダーのもとを完全上書き！！（一つのみにする）
#                 break  # ループも抜け、この一つだけを返すようにする
#                 # ↑暫定対策ここまで
#         # ■■　結果を返却用配列に追加する(各要素に対して書き換えを行う。eachはpredict_line_info_list_baseと同様）
#         each_predict_line_info['strength_info'] = strength_info  # Strengthに追加（上書き）
#         print("      (rip)", strength_info)
#
#     # 各SamePriceではなく、トータルで見れる（SamePriceに依存しない）場合
#     print("    ■予測と反対側（今回でいうリバー）が強い抵抗線かを検討する")
#     double_top_same_price_list = find_same_price_list_from_peaks(peaks[1]['peak'], peaks[1]['direction'], peaks, False)
#     if len(double_top_same_price_list) != 0:
#         # 同価格が存在する場合
#         oppo_strength_info = judge_line_strength_based_same_price_list(
#             double_top_same_price_list,
#             peaks,
#             peaks[1]['peak'],
#             peaks[1]['direction']
#         )  # ■■LINE強度の検証関数の呼び出し
#         print("     ⇒⇒反対(river)のLine強度", oppo_strength_info)
#         if oppo_strength_info['line_strength'] >= 0.9:
#             now_double_peak_gap = peaks[0]['gap']
#             tk.line_send("  反対側に強い抵抗.価格:",peaks[1]['peak'], "強さ", oppo_strength_info['line_strength'],
#                          "Gap", now_double_peak_gap)
#     else:
#         tk.line_send("   反対が存在しないケース　不思議なケース(下でoppoが使えない)")
#
#     # ↑部を変えるの面倒だから、、、
#     predict_line_info_list[0]['strength_info']['line_strength'] = -11  # オーダー起点の数字をこの時点で０に、。
#
#     # ■■DoublePeak系の判断　（これは上記のLineStrengthとは独立の考え方に近い）
#     print("    ■突破形状の確認")
#     # ①形状が北斗七星型？
#     double_peak = dp.DoublePeak_predict({"df_r": target_df, "peaks": peaks})
#     if double_peak['take_position_flag']:
#         # 突破形状が確認された場合
#         # 最低値等でない場合は、ウォーニングを出す
#         if oppo_strength_info['line_position_strength'] == 0:
#             print("   ★★★★LINEが最上位、最下位ではない状態の突破形状")
#         # 突破形状が発見されたときは、一つのみのオーダーとする。
#         predict_line_info_list[0]['strength_info']['line_strength'] = double_peak['double_top_strength']
#         predict_line_info_list[0]['strength_info']['remark'] = double_peak['double_top_strength_memo'] + "latest3"
#         predict_line_info_list[0]['strength_info']['order_before_finalized'] = double_peak['order_before_finalized']
#     # if double_peak['take_position_flag']:
#     #     print("   形状的には突破形状（ダブルトップ未遂）")
#     #     # ②ピーク価格が、直近25足分（ピーク数ではなく）で,最も高い値（低い価格）の場合
#     #     flop_peak = peaks[2]['peak']
#     #     flop_from_now = peaks[0]['count'] + peaks[1]['count'] - 1  # flop以降で探す（0でもあまり影響はないかも）
#     #     narrow_range_df = target_df[flop_from_now:25]
#     #     if peaks[0]['direction'] == 1:
#     #         # レイテストが上向きの場合、Flopのピークが上記の範囲で最高値かどうかを判定する
#     #         filtered_df = narrow_range_df[narrow_range_df['inner_high'] > flop_peak + 0.02]  # 超えているものを探す
#     #     else:
#     #         # レイテストが下向きの場合、Flopのピークが上記の範囲で最下位かどうかを確認する
#     #         filtered_df = narrow_range_df[narrow_range_df['inner_low'] < flop_peak - 0.01]  # 超えているものを探す
#     #     print("　　ダブルトップ検証範囲", narrow_range_df.iloc[0]['time_jp'], narrow_range_df.iloc[-1]["time_jp"], flop_peak)
#     #     if len(filtered_df) > 0:
#     #         # 超えているものがある場合は、ちょっと微妙
#     #         print("  　微妙なDoubleTop未遂", filtered_df.iloc[0]['time_jp'])
#     #     else:
#     #         print("    真の突破型のダブルトップ未遂")
#     #         tk.line_send(" 　ダブル突破未遂発見")
#     #         predict_line_info_list[0]['strength_info']['line_strength'] = -1
#     #         predict_line_info_list[0]['strength_info']['remark'] = "ダブルトップ突破未遂"
#
#     # テスト的な
#
#     print("    ■移動距離の確認")
#     ms.cal_move_size({"df_r": target_df, "peaks": peaks})
#
#     return predict_line_info_list

# def find_latest_line_based_river(*args):
#     """
#     :param *dic_args: 複数の引数を取る可能性があるが、２パターン.
#     ①二つの引数がある場合 dic_args[0] = df_r、dic_args[1] = peaks
#     　→ループ等で呼び出される場合がメイン。df_rは基本参考値で、peaksで実施するのが理想（計算量削減の為）
#     ②一つだけの引数がある場合 dic_args[0] = df_r
#      →単発で実行する場合のみ
#
#     この関数の特徴は、
#     find_same_price_list_from_peaksに渡すPeaksが、peaks[2:]と２以降になっていること。
#     （fina_same_price_list_from_peaksは与えられたPeaksに対し調査してしまうため、riverを含まない範囲で渡す必要がある）
#
#      <調査の対象について＞
#      図で書くと、直近のターンポイント(river_peak)が、Lineとなっているかを確認する関数。
#       \　　↓ここが対象となる（=river)
#        \  /\←　この部分が２の場合に検出する（ここはLatestではない。２の場合＝１つ出来立ての足は省くので、このPeakは無いと同義）
#         \/  \ ←これがLatestとして扱われるもの
#     :return:
#     """
#     # 何が正解なのかわからないけど、最初に返却値を設定しておく
#     return_dic = {
#         "line_base_info": {},
#         "same_price_list": {},
#         "strength_info": {
#             "line_strength": 0,
#             "line_on_num": 0,
#             "same_time_latest": 0
#         }
#     }
#
#     # 準備部分（表示や、ピークスの算出を行う）
#     if len(args) == 2:
#         # 引数が二個の場合は、Peaksが来ている為、ピークスを求める必要なし
#         target_df = args[0]
#         peaks = args[1]
#     else:
#         # 引数が１つの場合（df_rのみ）、ピークスを求める必要あり
#         target_df = args[0][0:40]
#         peaks_info = p.peaks_collect_main(target_df, 12)
#         peaks = peaks_info["all_peaks"]
#     # 状況に応じた、ピークポイントの指定  # 添え字は0=latest, 1=river, 2=turn, 3=flop3
#     if len(peaks) < 4:
#         # ■ループの際、数が少ないとエラーの原因になる。３個切る場合ば終了（最低３個必要）
#         return return_dic
#
#     # (1) LINE探索する
#     # ①riverの同じ価格のポイントを探す（riverのポイントのみ）
#     # 1,旧順張りのためのLINEを見つける方法(riverを基準にする場合）
#     target_price = peaks[1]['peak']  # [1]はriverを示す
#     target_dir = peaks[1]['direction']
#     line_base_info = {
#         "line_base_time": peaks[1]['time'],  # River。
#         "line_base_price": target_price,
#         "line_base_direction": target_dir,  # 1の場合UpperLine（＝上値抵抗）
#         "latest_direction": peaks[0]['direction'],  # 渡されたPeaksの直近の方向（＝直近の方向）
#         "latest_time_in_df": peaks[0]['time'],  # Latest。直近の時間（渡されたDFで判断）
#         "decision_price": target_df.iloc[0]['close'],  #
#     }  # 以上、Line計算の元になるデータ（探索と想定探索で異なる）
#     print(" 価格と方向", target_price, target_dir)
#     gene.print_arr(peaks)
#     # メモ　従来の使い方をすると、[1]まで入れると、重複して数えてしまうため、turn[2]以前を採用(riverとlatest[0]は不要）
#     same_price_list = find_same_price_list_from_peaks(target_price, target_dir, peaks[2:], False)
#     print("SEARCH LINE INFO ↓SameLineList")
#     print(same_price_list)
#     print("LineBaseInfo")
#     print(line_base_info)
#     print("")
#
#     # ②Lineのストレングスを求める
#     if len(same_price_list) == 0:
#         # same_priceがない場合、即時、返却する
#         return {  # take_position_flagの返却は必須。
#             "line_base_info": line_base_info,
#             "same_price_list": same_price_list,
#             "strength_info": {
#                 "line_strength": 0,
#                 "line_on_num": 0,
#                 "same_time_latest": 0
#             }
#         }
#     # samePriceがある場合はストレングスを求めていく
#     strength_info = judge_line_strength_based_same_price_list(same_price_list)
#     print("強度確認")
#     print(strength_info)
#     return {
#         "line_base_info": line_base_info,
#         "same_price_list": same_price_list,
#         "strength_info": strength_info
#     }


