import fBlockInspection as t  # とりあえずの関数集
import tokens as tk  # Token等、各自環境の設定ファイル（git対象外）
import classOanda as oanda_class
import fPeakInspection as p  # とりあえずの関数集
import fGeneric as f
import statistics
import pandas as pd
import fGeneric as gene
import fCommonFunction as cf

oa = oanda_class.Oanda(tk.accountIDl, tk.access_tokenl, "live")  # クラスの定義


def make_same_price_list_from_target_price(target_price, target_dir, peaks_all, same_price_range, is_recall):
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

    s4 = "    "
    s6 = "      "
    print(s4, "同価格リスト関数", is_recall)
    # ■通貨等に依存する数字
    dependence_same_price_range = same_price_range
    # dependence_same_price_range = 0.015  # 0.027がベスト

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
    same_list = []
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

    # print("　　　　判定閾値", dependence_same_price_range)
    for i, item in enumerate(peaks_all_for_loop):
        # 判定を行う
        # print(s6, " 判定", item['time'], target_price - dependence_same_price_range, "<", item['peak'], "<=", target_price + dependence_same_price_range, item['direction'], target_price - dependence_same_price_range <= item['peak'] <= target_price + dependence_same_price_range)
        if target_price - dependence_same_price_range <= item['peak'] <= target_price + dependence_same_price_range:
            # ■同価格のピークがあった場合 (recall(2個目以上の対象)の場合は、変更しない）
            if counter == 0:
                if is_recall:
                    # 再起呼び出しされている場合は、ここはやらずに結果を返却するのみ
                    pass
                else:
                    # 今回のtargetPriceで最初の発見（最低値か最高値）の場合、それにtargetPriceを合わせに行く(それ基準で近い物を探すため）
                    # print(s6, "target 変更 ", target_price, " ⇒", item['peak'], dependence_same_price_range)
                    target_price = item['peak']
                    recall_result = make_same_price_list_from_target_price(target_price, target_dir, peaks_all, same_price_range, True)
                    return recall_result

            # ■同一価格のピークの情報を取得する
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
            # if i == len(peaks_all) - 1 and len(same_list) != 0:
            #     # ほかにSamePriceが一つでもあった場合、最後の価格は残す
            #     # （SamePriceではないが、最後として残すことで、最上位のピークかどうかを判定できるようにする
            #     # ほかにSamePriceがない場合、この最後の値だけが入ってしまうため、ほかにSamePriceがない場合はスルーする
            #     same_list.append({"time": item['time'],
            #                       "peak": item['peak'],
            #                       "same_dir": False,
            #                       "direction": target_dir,
            #                       "count_foot_gap": i,
            #                       "depth_point_gap": round(depth_point_gap, 3),
            #                       'depth_point': depth_point,
            #                       "depth_point_time": depth_point_time,
            #                       "depth_break_count": depth_break_count,
            #                       "depth_fit_count": depth_fit_count,
            #                       "near_point_gap": round(near_point_gap, 3),
            #                       "near_point": near_point,
            #                       "near_point_time": near_point_time,
            #                       'near_break_count': near_break_count,
            #                       'near_fit_count': near_fit_count,
            #                       "between_peaks_num": between_peaks_num,
            #                       "i": i,  # 何個目か
            #                       "peak_strength": 0  # peakStrength＝０は、同価格ではない、最後の調査対象価格
            #                       })
    # 最後のピークは同価格でないフラグを立てて、記録する（最後の同価格発見以降に、その価格よりオーバー等があるかを確認するため）
    if len(same_list) != 0:
        # ほかにSamePriceが一つでもあった場合、最後の価格は残す
        # （SamePriceではないが、最後として残すことで、最上位のピークかどうかを判定できるようにする
        # ほかにSamePriceがない場合、この最後の値だけが入ってしまうため、ほかにSamePriceがない場合はスルーする
        item = peaks_all[-1]
        same_list.append({"time": item['time'],
                          "peak": item['peak'],
                          "same_dir": False,
                          "direction": target_dir,
                          "count_foot_gap": len(peaks_all),
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
                          "i": len(peaks_all),  # 何個目か
                          "peak_strength": 0  # peakStrength＝０は、同価格ではない、最後の調査対象価格
                          })

    # 同価格リスト
    # print("    (ri)ベース価格", target_price, target_price - dependence_same_price_range, "<r<",
    #       target_price + dependence_same_price_range,
    #       "許容ギャップ", dependence_same_price_range, "方向", target_dir, " 平均ピークGap", ave)
    # print("    (ri)同価格リスト↓")
    # gene.print_arr(same_list)

    # 最初にpeaks_allをpeakによる降順昇順を行った場合、ここで時刻による降順に戻す
    same_list = sorted(same_list, key=lambda x: x["time"], reverse=True)
    return same_list


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
    fixed_information = cf.information_fix(dic_args)  # DFとPeaksが必ず返却される
    # 情報の取得
    df_r = fixed_information['df_r']
    peaks = fixed_information['peaks']
    # 状況に応じた、ピークポイントの指定  # 添え字は0=latest, 1=river, 2=turn, 3=flop3

    # ■データフレームの状態で、サイズ感を色々求める
    filtered_df = df_r[:48]  # 直近3時間の場合、12×３ 36
    sorted_df = filtered_df.sort_values(by='body_abs', ascending=False)
    max_high = sorted_df["inner_high"].max()
    min_low = sorted_df['inner_low'].min()
    max_min_gap = round(max_high - min_low, 3)
    print(t6, "検出範囲", filtered_df.iloc[0]["time_jp"], "-", filtered_df.iloc[-1]['time_jp'])
    print(t6, "最大値、最小値", max_high, min_low, "差分", max_min_gap)
    print(t6, "最大足(最高-最低),", sorted_df.iloc[0]['time_jp'], sorted_df.iloc[0]['highlow'])
    print(t6, "最小足(最高-最低),", sorted_df.iloc[-1]['time_jp'], sorted_df.iloc[-1]['highlow'])
    print(t6, "平均(最高-最低)", sorted_df['highlow'].mean())
    print(t6, "最大足(Body),", sorted_df.iloc[0]['time_jp'], sorted_df.iloc[0]['body_abs'])
    print(t6, "最小足(Body),", sorted_df.iloc[-1]['time_jp'], sorted_df.iloc[-1]['body_abs'])
    print(t6, "平均(Body)", sorted_df['body_abs'].mean())

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
    print(t6, "最大ギャップ", max_gap)
    print(t6, other_max_gap_items)

    # ■ピーク5個の中できわめて大きな変動がある場合（雇用統計とか、、、）基本は戻る動きとみる？（それとも静観・・・？）
    other_max_gap_ave = sum(item["gap"] for item in other_max_gap_items) / len(other_max_gap_items)
    print(t6, "最大ギャップ以外の平均ピーク", other_max_gap_ave)
    if max_gap['count'] <= 3:  # ピーク全体のギャップではなく、本来は足一つ程度がメインのため
        if max_gap['gap'] >= 0.3 and max_gap['count']:
            print(t6, " 問答無用できわめて大きな変動があった")
            big_move = True
        else:
            if max_gap['gap'] / other_max_gap_ave > 3:  # 3倍以上なら
                print(t6, " 大きなピークが、他のピークの平均の３倍ある⇒ビッグムーブと判断（一つの足でありたいが）")
                big_move = True
            else:
                big_move = False

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
            print(t6, "@@最低Price(", base_price, ")", )
        else:
            peak_is_peak = False
            print(t6, "@@最低ではないPrice(", base_price, ")", )
    else:
        # 直近が上方向の場合、上側から確認している（上のLineが最高値かどうかの判定）
        max_index, max_peak = max(enumerate(peaks[:]), key=lambda x: x[1]["peak"])
        if max_peak['peak'] + dependence_allowed_range_max_price < base_price:
            # 最高値の範囲（最低値より少し下よりも上）であれば
            peak_is_peak = True
            print(t6, "@@最高price(", base_price, ")")
        else:
            peak_is_peak = False
            print(t6, "@@最高ではないprice(", base_price, ")")

    # ■直近のピークが、抵抗線として機能しているか
    skipped_peaks = p.change_peaks_with_hard_skip(peaks)
    same_price_range = max_min_gap * 0.033  # 直近の動きの3割程度
    same_price_range = gene.cal_at_least(0.029, same_price_range)
    same_price_list = make_same_price_list_from_target_price(base_price, latest_direction, skipped_peaks, same_price_range, True)
    print("SimpleTurnの解析", same_price_range)
    print(same_price_list)
    if len(same_price_list)-1 >= 2:
        is_latest_peak_resistance_line = True
    else:
        is_latest_peak_resistance_line = False
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







