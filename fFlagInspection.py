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


def make_same_price_list_from_target_price(target_price, target_dir, peaks_all, predict_flag):
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
        range_yen = 0.027  # 24/8/21 13:15のデータをもとに設定(0.04 = 指定の0.02×2(上と下分）) 　24/9/18　2.5まで広げてみる（フラッグ見つけやすく）
        # range_yen = 0.013  # 24/8/21 13:15のデータをもとに設定(0.04 = 指定の0.02×2(上と下分）) 　24/9/18　2.5まで広げてみる（フラッグ見つけやすく）
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
        # print(" 判定", item['time'], target_price - range_yen, "<", item['peak'], "<=", target_price + range_yen)
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
    print(" 新フラッグ調査関数")
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
    ans_list = []
    # for target_num in [5]:
    for target_num in range(4, 7):
        print("■◇s", target_num)
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
        for i, item_each in enumerate(target_peaks):
            print(s7, item_each['time'], "  ", item_each['peak'])
        # gene.print_arr(target_peaks, 7)
        print(s7, "先頭の情報", target_peaks[0]['peak'], target_peaks[0]['time'])
        print(s7, "最後尾の情報", oldest_info['peak'], oldest_info['time'])
        y_change = target_peaks[0]['peak'] - oldest_info['peak']
        if abs(y_change) <= 0.015:
            print(s7, "傾きが少なすぎる")
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
                   "remark": 0
                   }
            ans_list.append(ans)
            continue
        else:
            print(s7, "いい傾き")

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
        print(s7, "調査側は", d, "傾き方向は", tilt_pm)
        if d == tilt_pm:
            print(s7, "下側が下方向、上側が上方向に行っている（今回は収束と見たいため、不向き）")
            remark = "発散方向"
            direction_integrity = False  # 方向の整合性
        else:
            # 傾斜は合格、ピークスを包括できるかを確認
            # if on_line_ratio >= 0.55 and near_line_ratio >= 0.7:  # 0.35, 60
            if on_line_ratio >= 0.35 and near_line_ratio >= 0.6:  # 緩いほう（従来の結果がよかった条件）
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
        lc_margin = 0.01 * latest_direction * -1
        ave_peak_price = ave_peak_price + lc_margin

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
        ans_list.append(ans)
        # ループここまで

    # ■情報を整理する（例えば3peak～5peaksの各直線で、複数の傾斜直線がある場合、傾斜直線成立としt、代表としてOldestな物を返却する)
    gene.print_arr(ans_list, 7)
    all_ans_num = len(ans_list)
    true_num = sum(item["is_tilt_line_each"] for item in ans_list)  #
    print(s7, all_ans_num, true_num, true_num/all_ans_num)
    # if true_num / all_ans_num >= 0.5:  # 0.5だと、従来取れていたものも取りこぼす(良くも悪くも)
    if true_num / all_ans_num >= 0.1:
        print(s7, "斜面成立(", all_ans_num, "の内", true_num, "個の成立")
        is_tilt_line = True
    else:
        # 成立が認められない場合でも、Onlineが10割のものがあれば、採用する
        temp = next((item for item in ans_list if item["on_line_ratio"] == 1), None)
        if temp and temp['direction_integrity']:
            # ある場合は、それの方向性の整合が取れているかを確認する
            is_tilt_line = True
            print(s7, " あった")
        else:
            print(s7, " やっぱりない")
            return return_base

    # ■成立している中で、一番比較ピークが多いもの、少ないものを抽出しておく
    first_item = next((item for item in ans_list if item["is_tilt_line_each"]), None)  # 最もLatestなTiltTrue
    # oldest_item = next((item for item in reversed(ans_list) if item["is_tilt_line_each"]), None)  # 最もOldestなTiltTrue
    oldest_item = max(
        (item for item in reversed(ans_list) if item['is_tilt_line_each']),  # fが真の要素をフィルタ
        key=lambda x: x['y_change'],                  # kが最大のものを取得
        default=None                           # 空の場合はNoneを返す
    )
    print(s7, "直近のアイテム", first_item)
    print(s7, "最古のアイテム", oldest_item)

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

    # ■5個の時の成立があるかを確認する
    res5 =next((item for item in ans_list if item.get("count") == 5), None)
    print(s7, "latest=5のもの(過去成績が良かったもの)", res5)
    if res5['is_tilt_line_each']:
        strength = 1
    else:
        strength = 0.5

    # 個の直線に関する情報は、全てOldestを参照する(LCPriceも元はOld）
    ans_info = {
        "is_tilt_line": is_tilt_line,
        "tilt_list": ans_list,
        "oldest_peak_info": oldest_item,
        "latest_peak_info": first_item,
        "lc_price": lc_price,  # 計算で大きすぎた場合、10pipsが入る
        "remark": oldest_item['remark'],  # 一番古いのを採用
        "strength": strength  # 過去一番精度がいいのはpeakが5個の時（5の時以外は、少し短めのLCとする）
    }
    return ans_info
        

def judge_flag_figure_wrap_up_hard_skip(peaks, target_direction, line_strength, df_r):
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
    print(s6, "抵抗線向きは", target_direction, "傾きを確認したいのは", target_direction * -1)
    flag_ans = False

    # ■Peaksの準備
    # ■■直近
    peaks = peak_inspection.hard_skip_after_peaks_cal(peaks)
    # ■■ひとつ前の足
    fixed_information_prev = cf.information_fix({"df_r": df_r[1:]})  # DFとPeaksが必ず返却される
    peaks_prev = fixed_information_prev['peaks']

    # ■直近の傾斜の有無を確認する
    tilt_line_info = tilt_cal(peaks, target_direction * -1)
    # tilt_ansの中身： {"tilt_flag","tilt_list","oldest_peak_info","latest_peak_info","lc_price","remark","strength"}

    # ■直近がOKの場合、一つ前の足基準で、調査を行う
    if tilt_line_info['is_tilt_line']:
        # 現状で傾きが成立してれば、とりあえずFlagはTrueとなる
        tilt_flag = True
        tilt_ans_prev = tilt_cal(peaks_prev, target_direction * -1)
        if tilt_ans_prev['is_tilt_line'] and (target_direction == peaks_prev[0]['direction']):
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
        return {"tilt_flag": False}

    # print(tilt_line_info['oldest_peak_info'])

    return {
        "tilt_flag": tilt_flag,
        "is_first": is_first,
        "lc_price": tilt_line_info['lc_price'],  # こっちのほうがlongよりLC幅が狭いので。いつかリスクを追う場合は、Longに？）
        "remark": tilt_line_info['remark'],
        "strength": tilt_line_info['strength'],
        "oldest_peak_info": tilt_line_info['oldest_peak_info'],
        "y_change": tilt_line_info['oldest_peak_info']['y_change']
    }


def analysis_flag(dic_args):
    """
    引数はDFやピークスなど
    """

    # 表示時のインデント
    s4 = "    "
    s6 = "      "
    flag_flag = False
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

    # ■各変数の設定（動的な値）
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
        search_min_price = peaks[0]['peak'] - grid   # 探索する最低値。(現在価格）　「24/11/19」-gridを増やした
        if max_to_min_search:
            # 簡単に切り替えられるように（変更点が複数あるため、一括で変更できるようにした）
            target_price = search_max_price  # - grid  # MAX側から調査（登りの場合、上から調査）
        else:
            target_price = search_min_price  # + grid  # 登りの場合でもMinからスタート
    else:
        # latestが下り方向の場合
        search_max_price = peaks[0]['peak'] + grid  # 探索する最低値 [24/11/19]+girdを増やした
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
        same_price_list = make_same_price_list_from_target_price(target_price, target_dir, peaks, True)  # ★★
        same_price_list = [d for d in same_price_list if d["time"] != peaks[0]['time']]  # Latestは削除する(predict特有）
        # print("    (rip)同価格リスト (Latestピークを削除後)↓　最終時刻は", peaks[0]['time'])
        # gene.print_arr(same_price_list)

        if len(same_price_list) == 1:
            # 現時刻を消したうえで、内容が一つだけになっている場合、それは最後の時刻のもの（sameprice検索の使用でついてきてしまう）
            same_price_list = []
            # print(" 　　　(rip)最終時刻のもののみのため、スキップ")

        if len(same_price_list) >= 1:
            # 同価格リストが発見された場合、範囲飛ばしと、返却値ベースへの登録を行う
            predict_line_info_list_base['line_base_info']['line_base_price'] = round(target_price, 3)  # 仮情報に上書き
            predict_line_info_list_base['same_price_list'] = same_price_list  #
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
        for i, item_each in enumerate(each_predict_line_info['same_price_list']):
            print(s6, item_each['time'], item_each['peak'])
        # gene.print_arr(each_predict_line_info['same_price_list'], 7)

        # ■■ライン強度検証の関数の呼び出し（ここで初めてストレングスを取得する）
        each_strength_info_result = cal_strength_of_same_price_list(
            each_predict_line_info['same_price_list'],
            peaks,
            each_predict_line_info['line_base_info']["line_base_price"],
            each_predict_line_info['line_base_info']["latest_direction"]
        )
        print("         強度結果", each_strength_info_result)

        # ■■■フラッグかどうかを判定（Line強度とは別の関数にする） ★★事実上これがメイン
        # if each_strength_info['all_range_strong_line'] == 0 and each_strength_info['line_on_num'] >= 3:  # 旧条件　かなり厳しい
        # if each_strength_info['line_on_num'] >= 3 and each_strength_info['line_strength'] == 1:  # 旧条件２　少し厳しい
        if each_strength_info_result['line_on_num'] >= 2 and each_strength_info_result['line_strength'] >= 0.9:  # allRangeは不要か
            # flag = judge_flag_figure_wrap_up(peaks, peaks[0]['direction'], each_strength_info_result['line_strength'], target_df)
            flag_info = judge_flag_figure_wrap_up_hard_skip(peaks, peaks[0]['direction'], each_strength_info_result['line_strength'], target_df)  # ★スキップバージョン
            print(s6, "[Flagテスト結果]", each_predict_line_info['line_base_info']["line_base_price"])
            # フラッグの結果次第で、LineStrengthに横やりを入れる形で、値を買い替える
            if flag_info['tilt_flag']:
                print(s6, "Flag成立")
                # 【注文に必要な情報】フラッグ形状の場合、まず元の情報に上書きする
                flag_flag = True  # フラッグ成立
                each_strength_info_result['line_strength'] = -1  # フラッグ成立時は、通常とは逆
                each_strength_info_result['lc_price'] = flag_info['lc_price']
                each_strength_info_result['expected_direction'] = peaks[0]['direction']
                each_strength_info_result['latest_direction'] = peaks[0]['direction']
                each_strength_info_result['remark'] = str(flag_info['remark'])
                each_strength_info_result['priority'] = 3  # 備考を入れておく
                each_strength_info_result['is_first_for_flag'] = flag_info['is_first']  # 備考を入れておく
                each_strength_info_result['strength'] = flag_info['strength']  # 備考を入れておく
                each_strength_info_result['y_change'] = flag_info['y_change']
                each_strength_info_result['flag_info'] = flag_info
                each_strength_info_result['line_is_close_for_flag']\
                    = True if 0.07 > abs(each_predict_line_info['line_base_info']["line_base_price"] - peaks[0]['peak']) else False  # breakラインまで近いかどうか

        else:
            print(s6, "flagtestなし", each_strength_info_result['line_on_num'], each_strength_info_result['line_strength'])

        # ■　結果を返却用配列に追加する(各要素に対して書き換えを行う。eachはpredict_line_info_list_baseと同様）
        each_predict_line_info['strength_info'] = each_strength_info_result  # predict_line_info_listの一つを更新

    # ■（NEW）同価格リストの中から、フラッグの情報(ストレングスが-1)だけを取得する
    # 返却内容の整理（evidenceの中身がフラッグだけか、それ以外も含むか、が初期のとは異なる）
    # {"フラッグ",True or False
    #  "information": [{"LineBase":{}, "samePriceList":[{peaks}], "strengthInfo":{"lc,remark,y_change等"}]
    #              [{"LineBase":{}, "samePriceList":[{peaks}], "strengthInfo":{"lc,remark,y_change, flag_info等"}]
    #  }
    #  flag_infoの中身： {"tilt_flag","is_first","lc_price","remark","strength","oldest_peak_info","y_change"}
    #
    if flag_flag:
        flag_info_list = [d for d in predict_line_info_list if d["strength_info"]["line_strength"] == -1]
        # print(s6, "フラッグ")
        # print(flag_info_list)
        flag_info = flag_info_list[0]  # その中から先頭の一つに絞る
        orders_and_evidence["take_position_flag"] = flag_flag
        orders_and_evidence["information"] = flag_info

        return orders_and_evidence
    else:
        orders_and_evidence["take_position_flag"] = flag_flag  # False代入と同義
        return orders_and_evidence


def main_flag(dic_args):
    """
    引数はDFやピークスなど
    オーダーを生成する
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
    fixed_information = cf.information_fix(dic_args)  # DFとPeaksが必ず返却される
    df_r = fixed_information['df_r']
    peaks = fixed_information['peaks']

    # ■調査を実施する■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■■
    # ■■実行しない条件の場合、実行を終了する
    if peaks[0]['count'] == 1:
        print(s6, "countで実行しない場合を宣言する")  # フラッグは基本的に、Latestの数がいつでも実行する
    # ■■解析の実行
    flag_analysis_result = analysis_flag({"df_r": df_r, "peaks": peaks})
    if not flag_analysis_result['take_position_flag']:
        return orders_and_evidence

    # ■フラッグ形状が発見された場合はオーダーを発行する
    flag_info = flag_analysis_result['information']
    # "flag_info": {"LineBase": {}, "samePriceList": [{peaks}], "strengthInfo": {"lc_price,remark,y_change等"}
    position_type = "STOP"  # フラッグありの場合突破方向のため、STOP
    print(s4, "フラッグが発生した時の情報", flag_info)
    # ■■突破方向のオーダー（初回と二回目以降で異なる）
    flag_final = True  # 初回の一部でオーダーが入らない仕様になったため、改めてフラグを持っておく（オーダーないときはOrderAndEvidence返却でもいいかも？）
    if flag_info['strength_info']['is_first_for_flag']:
        # 初回成立の場合は、Lineまで遠い場合は、突破はオーダーなし(これはテスト用。終わったらIf文含めて消したほうがいいかも）
        if flag_info['strength_info']['line_is_close_for_flag']:
            # 初回でも近い場合は、抵抗線Break側のオーダーを出す
            # フラッグ用
            # main_order_base = cf.order_base(flag_info['line_base_info']['decision_price'], flag_info['line_base_info']['line_base_time'])
            # main_order_base['target'] = flag_info['line_base_info']['line_base_price'] - (0.01 * flag_info['line_base_info']['line_base_direction'])  # 0.05
            # main_order_base['tp'] = 0.53  # 0.09  # LCは広め
            # # main_order_base['lc'] = gene.cal_at_least(0.06, peaks[1]['peak']) # * line_strength  # 0.09  # LCは広め
            # main_order_base['lc'] = 0.03
            # main_order_base['type'] = position_type
            # main_order_base['expected_direction'] = flag_info['strength_info']['expected_direction']
            # main_order_base['priority'] = flag_info['strength_info']['priority']
            # main_order_base['units'] = main_order_base['units'] * -1
            # main_order_base['name'] = '初回特別' + flag_info['strength_info']['remark'] + '(' + str(main_order_base['priority']) + ')'
            # main_order_base['lc_change'] = [{"lc_change_exe": True, "time_after": 2 * 5 * 60, "lc_trigger_range": 0.01, "lc_ensure_range": -0.007}] + main_order_base['lc_change']
            # main_order_base['lc_change'] = [{"lc_change_exe": True, "time_after": 2 * 5 * 60, "lc_trigger_range": 0.05, "lc_ensure_range": 0.04}] + main_order_base['lc_change']
            # main_order_base['y_change'] = flag_info['strength_info']['y_change']
            # exe_orders.append(cf.order_finalize(main_order_base))
            return orders_and_evidence
        else:
            # 初回でなおかつ、距離が遠い場合はオーダーしない
            return orders_and_evidence
            pass
    else:
        # 初回ではない場合
        # フラッグ用（突破方向）
        main_order_base = cf.order_base(flag_info['line_base_info']['decision_price'], flag_info['line_base_info']['line_base_time'])    # tpはLCChange任せのため、Baseのまま
        main_order_base['target'] = flag_info['line_base_info']['line_base_price'] + (0.035 * flag_info['line_base_info']['line_base_direction'])  # 0.05
        main_order_base['lc'] = flag_info['strength_info']['lc_price']  # 0.06 ←0.06は結構本命  # 0.09  # LCは広め　　  # 入れる側の文字は　LCのみ
        main_order_base['type'] = position_type
        main_order_base['expected_direction'] = flag_info['strength_info']['expected_direction']
        main_order_base['priority'] = 5  # flag_info['strength_info']['priority']
        main_order_base['units'] = main_order_base['units'] * 1
        main_order_base['name'] = flag_info['strength_info']['remark'] + '(count:' + str(peaks[0]['count']) + ')'
        main_order_base['y_change'] = flag_info['strength_info']['y_change']
        exe_orders.append(cf.order_finalize(main_order_base))

        # ■■カウンタオーダーも入れる（二回目以降のみ）
        # 最大でもLCRange換算で10pips以内したい
        now_price = peaks[1]['peak'] - (0.035 * flag_info['line_base_info']['line_base_direction'])  # Nowpriceというより、取得価格
        temp_lc_price = flag_info['strength_info']['flag_info']['oldest_peak_info']['oldest_info']['peak']  # lcPriceは収束の中間点
        lc_range = temp_lc_price - now_price  # これがマイナス値の場合Directionは１、プラス値となる場合Directionは-1
        print(s6, "LC検討", now_price, temp_lc_price, lc_range)
        lc_range_border = 0.12
        if abs(lc_range) >= lc_range_border:
            # LCが大きすぎると判断される場合(10pips以上離れている）
            lc_range = lc_range_border  # LCRnageを指定
            if lc_range < 0:
                # LC_rangeがマイナス値　＝　Directionは１。その為、現在価格からマイナスするとLCPriceとなる
                lc_price = now_price - abs(lc_range_border)
                print(s6, "LC価格(Dir1)", now_price, "-", abs(lc_range_border))
            else:
                # LC_rangeがプラス値　＝　Directionは-1。その為、現在書くにプラスするとＬＣＰｒｉｃｅになる
                lc_price = now_price + abs(lc_range_border)
                print(s6, "LC価格(Dir-1)", now_price, "+", abs(lc_range_border))
        elif abs(lc_range) <= 0.06:
            # LCが小さすぎる
            lc_range = 0.07  # LCRnageを指定
            if lc_range < 0:
                # LC_rangeがマイナス値　＝　Directionは１。その為、現在価格からマイナスするとLCPriceとなる
                lc_price = now_price - abs(lc_range_border)
                print(s6, "LC価格(Dir1)", now_price, "-", abs(lc_range_border))
            else:
                # LC_rangeがプラス値　＝　Directionは-1。その為、現在書くにプラスするとＬＣＰｒｉｃｅになる
                lc_price = now_price + abs(lc_range_border)
                print(s6, "LC価格(Dir-1)", now_price, "+", abs(lc_range_border))
        else:
            # LCRangeが許容範囲内の場合、そのまま利用
            lc_price = temp_lc_price
            print(s6, "そのままのLCを利用する", lc_price)

        main_order_base = cf.order_base(flag_info['line_base_info']['decision_price'], flag_info['line_base_info']['line_base_time'])  # tpはLCChange任せのため、Baseのまま
        main_order_base['target'] = peaks[1]['peak'] - (0.035 * flag_info['line_base_info']['line_base_direction'])  # river価格＋マージン0.027
        # main_order_base['lc'] = gene.cal_at_most(0.09, flag_info['line_base_info']['line_base_price'] - 0.02 * (flag_info['strength_info']['expected_direction'] * -1))  # -0.02を追加してみた
        # main_order_base['lc'] = gene.cal_at_most(0.08, target_strength_info['line_base_info']['line_base_price']) # ←ダメだった！！！！
        # main_order_base['lc'] = flag_info['line_base_info']['line_base_price'] - 0.05 * (flag_info['strength_info']['expected_direction'] * -1)  # ←よかったけど、さらに上を！
        # gene.print_json(flag_info['strength_info']['flag_info']['oldest_peak_info']['oldest_info']['peak'])
        # main_order_base['lc'] = flag_info['strength_info']['flag_info']['oldest_peak_info']['oldest_info']['peak']  # ←悪くなさそうだが、広すぎる？
        main_order_base['lc'] = lc_price  # ←悪くなさそうだが、広すぎる？
        main_order_base['type'] = position_type
        main_order_base['expected_direction'] = flag_info['strength_info']['expected_direction'] * -1
        main_order_base['priority'] = 5  # ['strength_info']['priority']
        main_order_base['units'] = main_order_base['units'] * 1
        main_order_base['name'] = "カウンター" + flag_info['strength_info']['remark'] + '(count:' + str(peaks[0]['count']) + ')'
        main_order_base['y_change'] = flag_info['strength_info']['y_change']
        exe_orders.append(cf.order_finalize(main_order_base))


    # 返却する
    print(s4, "オーダー対象", flag_info)
    orders_and_evidence["take_position_flag"] = True  # ここまで来ている＝注文あり
    orders_and_evidence["exe_orders"] = exe_orders
    orders_and_evidence["information"] = flag_info['strength_info']

    print("オーダー表示")
    gene.print_arr(orders_and_evidence["exe_orders"])
    return orders_and_evidence


def for_practice_main_line_strength_analysis_and_order(dic_args):
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

    # ■調査を実施する
    ans_of_predict_line_info_list = analysis_flag({"df_r": df_r, "peaks": peaks})  # 調査関数呼び出し
    if not ans_of_predict_line_info_list['take_position_flag']:
        return orders_and_evidence
    print(s4, "LineStrengthのオーダー確定")
    predict_line_info_list = ans_of_predict_line_info_list['evidence']

    #  predict_line_listは添え字０から現在価格から遠いほうに並んでいる。その為、同値のストレングスがある場合、遠いほう（添え字が０に近い）が選ばれる
    max_index, max_strength = max(enumerate(predict_line_info_list[:]), key=lambda x: x[1]["strength_info"]["line_strength"])
    min_index, min_strength = min(enumerate(predict_line_info_list[:]), key=lambda x: x[1]["strength_info"]["line_strength"])  # 念のために取得
    flag_strength = [d for d in predict_line_info_list if d["strength_info"]["line_strength"] == -1]  # -1はフラッグ形状を示す
    # オーダーの元情報を取得する。フラッグの場合と通常の場合で、方向(expected_direction)が異なるため、Limit等も変わる。
    if len(flag_strength) != 0:
        # フラッグ形状が発見された場合
        target_strength_info = flag_strength[0]  # flag_strength は配列のため、要素としたいため、[0]とする
        position_type = "STOP"  # フラッグありの場合突破方向のため、STOP
        print(s4, "フラッグがSameList内に存在")
        # ■■突破方向のオーダー
        if target_strength_info['strength_info']['is_first_for_flag']:
            # 初回成立の場合は、Lineまで遠い場合は、突破はオーダーなし(これはテスト用。終わったらIf文含めて消したほうがいいかも）
            if target_strength_info['strength_info']['line_is_close_for_flag']:
                # 初回でも近い場合は、抵抗線Break側のオーダーを出す
                # フラッグ用（突破方向 記録用のため、コメントアウトされた状態が正）
                main_order_base = cf.order_base(target_strength_info['line_base_info']['decision_price'], target_strength_info['line_base_info']['line_base_time'])
                main_order_base['target'] = target_strength_info['line_base_info']['line_base_price'] + (0.035 * target_strength_info['line_base_info']['line_base_direction'])  # 0.05
                main_order_base['tp'] = 0.53  # 0.09  # LCは広め
                main_order_base['lc'] = 0.06  # * line_strength  # 0.09  # LCは広め
                main_order_base['type'] = position_type
                main_order_base['expected_direction'] = target_strength_info['strength_info']['expected_direction']
                main_order_base['priority'] = target_strength_info['strength_info']['priority']
                main_order_base['units'] = main_order_base['units'] * 1
                main_order_base['name'] = target_strength_info['strength_info']['remark'] + '[初回特別](' + str(main_order_base['priority']) + ')'
                exe_orders.append(cf.order_finalize(main_order_base))
            else:
                # 初回でなおかつ、距離が遠い場合はオーダーしない
                pass
        else:
            # フラッグ用（突破方向）
            main_order_base = cf.order_base(target_strength_info['line_base_info']['decision_price'], target_strength_info['line_base_info']['line_base_time'])
            main_order_base['target'] = target_strength_info['line_base_info']['line_base_price'] + (0.035 * target_strength_info['line_base_info']['line_base_direction'])  # 0.05
            main_order_base['tp'] = 0.53  # 0.09  # LCは広め
            main_order_base['lc'] = 0.06  # * line_strength  # 0.09  # LCは広め
            main_order_base['type'] = position_type
            main_order_base['expected_direction'] = target_strength_info['strength_info']['expected_direction']
            main_order_base['priority'] = target_strength_info['strength_info']['priority']
            main_order_base['units'] = main_order_base['units'] * 1
            main_order_base['name'] = target_strength_info['strength_info']['remark'] + '(' + str(main_order_base['priority']) + ')'
            exe_orders.append(cf.order_finalize(main_order_base))

        # ■■フラッグの場合は、カウンタオーダーも入れる（突破じゃないほうも入れておく
        main_order_base = cf.order_base(target_strength_info['line_base_info']['decision_price'], target_strength_info['line_base_info']['line_base_time'])
        main_order_base['target'] = peaks[1]['peak'] - (0.05 * target_strength_info['line_base_info']['line_base_direction'])  # river価格＋マージン
        main_order_base['tp'] = 0.53  # 0.09  # LCは広め
        main_order_base['lc'] = target_strength_info['line_base_info']['line_base_price']
        # main_order_base['lc'] = gene.cal_at_most(0.08, target_strength_info['line_base_info']['line_base_price']) # ←ダメだった！！！！
        main_order_base['type'] = position_type
        main_order_base['expected_direction'] = target_strength_info['strength_info']['expected_direction'] * -1
        main_order_base['priority'] = target_strength_info['strength_info']['priority']
        main_order_base['units'] = main_order_base['units'] * 1
        main_order_base['name'] = "カウンター" + target_strength_info['strength_info']['remark']+ '(' + str(main_order_base['priority']) + ')'
        exe_orders.append(cf.order_finalize(main_order_base))
    else:
        # それ以外
        target_strength_info = max_strength
        position_type = "LIMIT"
        return orders_and_evidence  # とりあえずフラッグのみを採用する

    # 返却する
    print(s4, "オーダー対象", target_strength_info)
    orders_and_evidence["take_position_flag"] = True  # ここまで来ている＝注文あり
    orders_and_evidence["exe_orders"] = exe_orders
    orders_and_evidence["evidence"] = predict_line_info_list

    print("オーダー表示")
    gene.print_arr(orders_and_evidence["exe_orders"])
    return orders_and_evidence


