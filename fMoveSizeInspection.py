import fBlockInspection as t  # とりあえずの関数集
import tokens as tk  # Token等、各自環境の設定ファイル（git対象外）
import classOanda as oanda_class
import fPeakInspection as p  # とりあえずの関数集
import fGeneric as gene
import fCommonFunction as cf
import fPeakInspection as pi
import classPeaks as cpk

oa = oanda_class.Oanda(tk.accountIDl, tk.access_tokenl, "live")  # クラスの定義


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
        # print("       TARGET", target_price)
        # print("       抵抗線で、同一価格とみなす範囲", target_price - dependence_same_price_range, "<", target_price + dependence_same_price_range)
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


def cal_move_size(dic_args):
    """
    LCのサイズ等を決定するため、周辺の大きさを確認する
    """
    big_move = False
    # 何が正解なのかわからないけど、最初に返却値を設定しておく
    predict_line_info_list = [
        {
            "line_base_info": {},
            "same_price_lists": [],
            # strength関数で取得（その後の上書きあり）
            "strength_info": {
                "line_strength": 0,
                "line_on_num": 0,
                "same_time_latest": 0,
                "all_range_strong_line": 0,
                "remark": ""
            }
        }
    ]

    # 準備部分（表示や、ピークスの算出を行う）
    ts = "    "
    t6 = "      "
    # print(ts, "■変動幅検証関数")
    peaksclass = cpk.PeaksClass(dic_args['df_r'])
    df_r = dic_args['df_r']
    peaks = peaksclass.skipped_peaks
    # 状況に応じた、ピークポイントの指定  # 添え字は0=latest, 1=river, 2=turn, 3=flop3

    s = "   "
    # print(s, "<通常ピークス　MoveInspectionの抵抗線探索用>")
    # print(s, "Latest", pi.delete_peaks_information_for_print(peaks[0]))
    # print(s, "river ", pi.delete_peaks_information_for_print(peaks[1]))
    # print(s, "turn", pi.delete_peaks_information_for_print(peaks[2]))
    # print(s, "flop3", pi.delete_peaks_information_for_print(peaks[3]))
    # print(s, "flop2", pi.delete_peaks_information_for_print(peaks[4]))
    # ■データフレームの状態で、サイズ感を色々求める
    filtered_df = df_r[:48]  # 直近3時間の場合、12×３ 36
    sorted_df = filtered_df.sort_values(by='body_abs', ascending=False)
    max_high = sorted_df["inner_high"].max()
    min_low = sorted_df['inner_low'].min()
    max_min_gap = round(max_high - min_low, 3)
    # print(t6, "検出範囲", filtered_df.iloc[0]["time_jp"], "-", filtered_df.iloc[-1]['time_jp'])
    # print(t6, "最大値、最小値", max_high, min_low, "差分", max_min_gap)
    # print(t6, "最大足(最高-最低),", sorted_df.iloc[0]['time_jp'], sorted_df.iloc[0]['highlow'])
    # print(t6, "最小足(最高-最低),", sorted_df.iloc[-1]['time_jp'], sorted_df.iloc[-1]['highlow'])
    # print(t6, "平均(最高-最低)", sorted_df['highlow'].mean())
    # print(t6, "最大足(Body),", sorted_df.iloc[0]['time_jp'], sorted_df.iloc[0]['body_abs'])
    # print(t6, "最小足(Body),", sorted_df.iloc[-1]['time_jp'], sorted_df.iloc[-1]['body_abs'])
    # print(t6, "平均(Body)", sorted_df['body_abs'].mean())

    # ■ピーク5個分の平均値を求める
    filtered_peaks = peaks[:5]
    peaks_ave = sum(item["gap"] for item in filtered_peaks) / len(filtered_peaks)
    # 最大値と最小値
    max_index, max_peak = max(enumerate(filtered_peaks[:]), key=lambda x: x[1]["peak"])
    min_index, min_peak = min(enumerate(filtered_peaks[:]), key=lambda x: x[1]["peak"])
    # 最大変動と最小変動
    max_gap_index, max_gap = max(enumerate(filtered_peaks[:]), key=lambda x: x[1]["gap"])
    min_gap_index, min_gap = min(enumerate(filtered_peaks[:]), key=lambda x: x[1]["gap"])
    other_max_gap_items = [item for item in filtered_peaks[:] if item != max_gap]
    # print(t6, "検出範囲ピーク",)
    # gene.print_arr(filtered_peaks, 6)
    # print(t6, peaks_ave)
    # print(t6, "変動幅検証関数　ここまで")
    # print(t6, "最大ギャップ", max_gap)
    # print(t6, other_max_gap_items)

    # ■ピーク5個の中で突発的できわめて大きな変動がある場合（雇用統計とか、、、）基本は戻る動きとみる？（それとも静観・・・？）
    target_peak = peaks[1]  # ビッグムーブ検査の対象となるのはひとつ前のピーク
    print(t6, "直近カウントと、ターゲットギャップ、カウント", peaks[0]['count'], target_peak['gap'], target_peak['count'])
    if peaks[0]['count'] == 2:
        # 重複オーダーとなる可能性をここで防止するため、ビッグムーブの判定はLatestカウントが2の場合のみ
        if target_peak['gap'] >= 0.3 and target_peak['count'] <=3:
            # 変動が大きく、カウントは3まで（だらだらと長く進んでいる変動は突発的なビッグムーブではない）
            big_move = True
        else:
            big_move = False
    #旧（おかしい？）
    # other_max_gap_ave = sum(item["gap"] for item in other_max_gap_items) / len(other_max_gap_items)
    # print(t6, "最大ギャップ以外の平均ピークとGAP", other_max_gap_ave, max_gap['gap'], max_gap['count'])
    # print(t6, "最大ギャップの時刻", max_gap['time'], max_gap['time_old'])
    # if max_gap['count'] <= 3:  # ピーク全体のギャップではなく、本来は足一つ程度がメインのため
    #     if max_gap['gap'] >= 0.3 and max_gap['count']:
    #         # print(t6, " 問答無用できわめて大きな変動があった")
    #         big_move = True
    #     else:
    #         if max_gap['gap'] / other_max_gap_ave > 3:  # 3倍以上なら
    #             # print(t6, " 大きなピークが、他のピークの平均の３倍ある⇒ビッグムーブと判断（一つの足でありたいが）")
    #             big_move = True
    #         else:
    #             big_move = False


    # ■ピーク4個分が、全てカウント３の場合、ほぼ動いてない相場とみる（相対的なため、Pipsでは指定しない？）
    range_counter = 0
    range_flag = False
    # print(peaks[:4])
    for i, item in enumerate(peaks[:4]):
        # print("確認")
        # print(item)
        if item['count'] <= 3:
            range_counter = range_counter + 1
            # print("Out")
    # print("Count=", range_counter)
    if range_counter == 4:
        range_flag = True
        # print("直近ピーク4回が全て短い⇒動きが少ない")
    else:
        range_flag = False
        # print("直近ピークが通常")

    # ■直近のピークがここ数時間で最大（最小）かどうか
    dependence_allowed_range_max_price = 0.04
    latest_direction = peaks[1]['direction']
    base_price = peaks[1]['peak']
    if latest_direction == -1:
        # 直近が下方向の場合、下側から確認している（下のLineが最低値かどうかの判定）
        min_index, min_peak = min(enumerate(peaks[:]), key=lambda x: x[1]["peak"])
        if min_peak['peak'] - dependence_allowed_range_max_price > base_price:
            # 最低値の範囲内であれば（0.04は余裕を持っている。同価格のスキップが0.05なので、それ以下に設定している）
            peak_is_peak = True
            # print(t6, "@@最低Price(", base_price, ")", )
        else:
            peak_is_peak = False
            # print(t6, "@@最低ではないPrice(", base_price, ")", )
    else:
        # 直近が上方向の場合、上側から確認している（上のLineが最高値かどうかの判定）
        max_index, max_peak = max(enumerate(peaks[:]), key=lambda x: x[1]["peak"])
        if max_peak['peak'] + dependence_allowed_range_max_price < base_price:
            # 最高値の範囲（最低値より少し下よりも上）であれば
            peak_is_peak = True
            # print(t6, "@@最高price(", base_price, ")")
        else:
            peak_is_peak = False
            # print(t6, "@@最高ではないprice(", base_price, ")")

    # ■直近のピークが、抵抗線として機能しているか
    # skipped_peaks = p.change_peaks_with_hard_skip(peaks)
    skipped_peaks = peaksclass.skipped_peaks
    same_price_range = max_min_gap * 0.033  # 直近の動きの3割程度
    same_price_range = gene.cal_at_least(0.020, same_price_range)
    same_price_info = make_same_price_list_from_target_price(base_price, latest_direction, skipped_peaks, same_price_range, True)
    same_price_list = same_price_info['same_price_list']
    strength_info = same_price_info['strength_info']
    print("      抵抗線とみる閾値", same_price_range, "範囲", base_price, "～", )
    print("      シンプルターンの抵抗線の値", len(same_price_list), strength_info['line_strength'])
    gene.print_arr(same_price_list, 7)
    # 判定は、[0]そもそも抵抗線無し、[1]は抵抗線はあるがN＝２のため強抵抗とみなす、[2]N＝３のため何回も当たりそろそろ突破の可能性と踏む。
    if len(same_price_list) >= 2 and strength_info['line_strength'] >= 0.7:
        is_latest_peak_resistance_line = 1
    elif len(same_price_list) >= 3 and strength_info['line_strength'] >= 0.7:
        is_latest_peak_resistance_line = 2
    else:
        is_latest_peak_resistance_line = 0
    # print(" 同一価格の個数(検証最終地である同一価格でない値を含む）", len(same_price_list))
    # print(" 実質的な同一価格", len(same_price_list)-1)
    # print(same_price_list)

    # 最高値で、なおかつビッグムーブの場合、⇒戻る
    # 最高値で、なおかつピークが抵抗線に含まれる場合

    return {
        "range_flag": range_flag,
        "big_move": big_move,
        "inner_min_max_gap": max_min_gap,
        "is_latest_peak_resistance_line": is_latest_peak_resistance_line,
        "peak_is_peak": peak_is_peak
    }

    # ■サイズ間でLCの幅とかを決めたい
    # 大きさを定義する
    very_small_range = 0.07
    # small_range = 0.11
    # middle_range = 0.15
    # # 変数を定義
    # flag = True
    # high_price = 0
    # low_price = 999
    # gap = 0
    # for index, row in df_r[0:15].iterrows():
    #     # high lowデータの更新
    #     if high_price < row['inner_high']:
    #         high_price = row['inner_high']
    #     if low_price > row['inner_low']:
    #         low_price = row['inner_low']
    #
    #     # 基準を超えているかを確認
    #     gap = high_price - low_price
    #     if gap > middle_range:
    #         # middleより大きい場合は、変動が大きな場所
    #         # print("これ以前は変動大", row['time_jp'])
    #         flag = True
    #         break
    #         pass
    #     elif gap > small_range:
    #         # small 以上　middle以下は、Middle
    #         # print("これ以前は変動中", row['time_jp'])
    #         flag = False
    #     else:
    #         flag = False







