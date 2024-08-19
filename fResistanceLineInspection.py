import fPeakInspection as p  # とりあえずの関数集
import fGeneric as f
import fDoublePeaks as dp
import pandas as pd


def find_same_price_list_from_peaks(target_price, target_dir, peaks_all):
    """
    価格が指定され、それと同じpeakをpeaksから探し出し、リストとして返却する。方向（上端か下端か）は問わない（情報としては取得する）
    target_dirは、抵抗線となりうるポイント(1)か、サポート線となりうるポイント(-1)かを示す。
    例1、渡されたピークが以下、target_priceが★、target_dirは-1(=peaks[1]のriverのdirectionと同様となるケース)
      peaks
        \  /\/\　
         \/    \/
               ↑★target_price
    例2、渡されたピークが以下、target_priceが★、target_dirは1(=peaks[0]のlatestのdirectionと同様となるケース)
      peaks       ↓★target_price(予測値）
        \  /\/\　
         \/    \/

    引数
    target_price:target_dirとセット
    target_dir: 1(上端)or-1(下端)。target_priceで、なおかつdir(1=upperPeak, -1=lowerPeak)のものを探す。
    返却値
    same_priceのリスト
    """
    # 平均のピークGapを計算する
    sum = 0
    for item in peaks_all:
        sum += item['gap']
    ave = sum / len(peaks_all)

    # ②探索開始
    counter = 0  # 何回同等の値が出現したかを把握する
    range_yen = f.cal_at_least_most(0.01, round(ave * 0.153, 3), 0.041)  # 0.153倍が一番よかった(大きすぎないレベル）。。
    depth_point_gap = 0  # 今のピークと一番離れている値、かつ、逆方向のポイント（同価格発見のタイミングでリセット）
    depth_point = 0
    depth_point_time = 0
    depth_minus_count = depth_plus_count = 0
    near_point_gap = 100  # 同価格ではないが、一番近い値、かつ、同方向のポイント(同価格を発見のタイミングでリセットされる）
    near_point = 0
    near_point_time = 0
    near_minus_count = near_plus_count = 0
    same_list = []
    between_peaks_num = 0  # 間に何個のピークがあったか。最短ダブルトップのの場合は2(自分自身をカウントするため）
    # print("　　　　ダブルトップ判定閾値", range_yen)
    for i, item in enumerate(peaks_all):
        # 判定を行う
        if target_price - range_yen <= item['peak'] <= target_price + range_yen:
            # 同価格を発見した場合。
            # print("　　　　同等のピーク発見", item['time'], abs(item['peak']-latest_peak))
            counter += 1

            # 何分前に発生した物かを計算（９０分以内なら、色々考えないとなぁ）
            # 方向に関する判定
            if item['direction'] == target_dir:
                # print("    Between確認", between_peaks_num, item['time'])
                same_dir = True
                # print("　　　　同方向の近似ピーク（≒ダブルピークの素）", item['time'], near_point_gap)
                same_list.append({"time": item['time'],
                                  "peak": item['peak'],
                                  "same_dir": same_dir,
                                  "count_foot_gap": i,
                                  "depth_point_gap": round(depth_point_gap, 3),
                                  'depth_point': depth_point,
                                  "depth_point_time": depth_point_time,
                                  "depth_minus_count": depth_minus_count,
                                  "depth_plus_count": depth_plus_count,
                                  "near_point_gap": round(near_point_gap, 3),
                                  "near_point": near_point,
                                  "near_point_time": near_point_time,
                                  'near_minus_count': near_minus_count,
                                  'near_plus_count': near_plus_count,
                                  "between_peaks_num": between_peaks_num,
                                  "i": i  # 何個目か
                                  })
                # 通過したピーク情報を初期化する
                depth_point_gap = 0
                near_point_gap = 100
                between_peaks_num = 0
            else:
                pass
                # same_dir = False
                # print("　　　逆方向の近似ピーク(= 踊り場的な扱い)")

        else:
            # 通過するピーク（同価格ではない）の場合、記録を残す。
            # print(" 　　スルーカウント", item['time'], abs(item['peak']-latest_peak), depth_point_gap, near_point_gap, between_peaks_num + 1)
            between_peaks_num += 1
            # 条件分岐
            peak_gap = abs(target_price - item['peak'])  # 指定価格と通過したピークの差分を取得（深さor高さを検証するため）
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
                    depth_minus_count += 1
                else:
                    depth_plus_count += 1
            if item['direction'] == target_dir:
                # 同じピークの場合→Nearの方
                # ニアの方の深さの値を取得する
                if peak_gap < near_point_gap:
                    # 最も近い価格を超える（かつ逆方向）場合
                    near_point_gap = peak_gap
                    near_point = item['peak']
                    near_point_time = item['time']
                # マイナスプラスをカウントする
                # print(" nearPointGap", peak_gap, item['time'])
                if peak_gap <= 0:
                    near_minus_count += 1
                else:
                    near_plus_count += 1
    # 同価格リスト
    print("    ベース価格", target_price, target_price - range_yen, "<r<",
          target_price + range_yen,
          "許容ギャップ", range_yen, "方向", target_dir, " 平均ピークGap", ave)
    print("    同価格リスト↓")
    f.print_arr(same_list)
    return same_list


def judge_line_strength_based_same_price_list(same_price_list):
    """
    ラインの強度を判定する。
    ・引数は同じ価格のリスト（配列）のみが、従来の強度判定には必要。
    ・target_price以降の引数は、返却値を整えるためのもの（引っ越し前の関数の名残。。）
    """
    # ■LineStrengthを決定するため、同価格リストの結果をもとに、谷があるかを判定する
    line_strength = 0.01
    minus_counter = 0  # 初期値
    if len(same_price_list) > 0:
        # 同一価格が存在する場合(直近の同一価格、それ以前の同一価格（複数の可能性もあり）について調査を行う）
        # ①まずは直近のSamePriceに関しての調査
        # print("　　　　SamePriceが１つあり→　調査する")
        # 同一価格の発見が１つの場合、
        # ＊パターン１　同一価格の間のピーク数が４個(丁度）の場合は、そのラインは強いライン
        #    以下の２パターンがあるが、どちらも強いラインの形（三尊、カルデラ）
        # 　   \/\  /\/
        # 　      \/  ↑river peak
        # 　      ↑Near
        # 　     ↓
        # 　   /\/\
        # 　 \/    \/
        #      　　　↑river_peak
        #  ＊パターン２　同一価格間のピーク数が４個よりも多い場合
        # 　    /\/\/\
        # 　  \/      \/
        #             ↑　river_peak
        #    near が半分以上マイナス値（ラインを割っている）の場合、信頼度が下がる
        #
        #   *パターン３　シンプルなダブルトップ系
        #    /\/\
        #   /
        #    betweenが２の場合のみ

        info = same_price_list[0]  # 同一価格が１つだけが成立（その情報を取得する）
        # print("Between", info['between_num'])
        # パターン１の処理
        if info['between_peaks_num'] == 4:
            line_strength = 2  # 強いラインとみなす

        # # パターン３の処理（シンプルダブルトップ）
        # if info['between_peaks_num'] == 2:
        #     if info['gap_time_min'] <= 20:  # 20分いないのダブルトップは、信頼度低（単なるギザギザの可能性）
        #         # print("初回短すぎ・・？")
        #         line_strength = 1.5  # 割とLineを突破することが多い気がするが。。。
        #     else:
        #         # print("適正？")
        #         line_strength = 2  # ただ、depthの深さによって変るのでは？

        # パターン２の処理
        if info['between_peaks_num'] > 4:
            # nearマイナスの数が、nearの数の半分以上の場合
            all_near_num = info['between_peaks_num'] / 2 - 1  # nearの数はこう求める
            minus_ratio = info['near_minus_count'] / all_near_num
            # print("    参考：マイナス比率", minus_ratio, info['near_minus_count'], all_near_num)
            if minus_ratio >= 0.4:
                line_strength = 0.5
            elif minus_ratio > 0:
                line_strength = 1.5
            else:
                line_strength = 3

        # ②同一価格が２個以上ある場合は、他も同号して検討する
        # print("　　　　複数のSamePriceあり。強いLINEではあるが、当たってきてる回数が多いので、抜ける可能性大？")
        if len(same_price_list) >= 2:
            for i in range(len(same_price_list)):
                if same_price_list[i]['near_point_gap'] < 0:
                    minus_counter += 1  # マイナスはLINEを超えた回数
            if minus_counter > len(same_price_list) * 0.5:
                # LINE越えが過半数の場合、LINEの信頼度つぃては高くない
                line_strength = 0.5
                # print("　　　　複数時　弱強度", minus_counter, len(same_list))
            elif minus_counter >= 1:
                line_strength = 1
                # print("　　　　複数時　１つ以上LINE越えあり", minus_counter)
            else:
                # LINE越えがない為、LINEの信頼度が比較的高い
                line_strength = 3
                # print("　　　　複数時　強強度", minus_counter, len(same_list))
    else:
        pass

    # # ただし、ぐちゃぐちゃしている場合（riverもturnもflop3もカウントが合計値が7以下（どれも２程度）の場合）LineStrengthを下げる
    # if river_count + turn_count + flop3_count <= 7:
    #     # print(peaks_all[1])
    #     # print(peaks_all[2])
    #     # print(peaks_all[3])
    #     # print(river_count, turn_count, flop3_count)
    #     print("   ◇◇ごちゃごちゃしている状態の為、ストレングスを解消", line_strength, "を０に", peaks_all[1]['count'],
    #           peaks_all[2]['count'], peaks_all[3]['count'])
    #     # line_strength = 0

    return_dic = {  # take_position_flagの返却は必須。Trueの場合注文情報が必要。
        "line_strength": line_strength,
        "line_on_num": len(same_price_list),
        "same_time_latest": 0 if len(same_price_list) == 0 else same_price_list[0]['time']  # 一番近い同一価格と判断した時刻
    }
    return return_dic


def find_predict_line_based_latest(*args):
    """
    基本的にはfind_latest_lineと似ている動き。
    find_latest_lineは指定されたDFからlatest_lineを産出するが、
    この関数は、想定される範囲で、Lineが生成される可能性があるかを計算するもの
       \　 ↓river peak
       \  /\←latest　
        \/
     ↓
    　\　　
       \  /\　
        \/  \/ ←こうなると予想されるポイントを探す
    latestが伸びていって、折り返したことを想定し、
    latestがriverとなり、latest_count＝２になったときに折り返す
    """
    # 何が正解なのかわからないけど、最初に返却値を設定しておく
    return_dic = {
        "line_base_info": {},
        "same_price_list": {},
        "strength_info": {
            "line_strength": 0,
            "line_on_num": 0,
            "same_time_latest": 0
        },
        "target_price": 0  # この関数特有（発見した価格＝オーダー価格）
    }
    
    # 準備部分（表示や、ピークスの算出を行う）
    if len(args) == 2:
        # 引数が二個の場合は、Peaksが来ている為、ピークスを求める必要なし
        target_df = args[0]
        peaks = args[1]
    else:
        # 引数が１つの場合（df_rのみ）、ピークスを求める必要あり
        target_df = args[0][0:40]
        peaks_info = p.peaks_collect_main(target_df, 12)
        peaks = peaks_info["all_peaks"]
    # 状況に応じた、ピークポイントの指定  # 添え字は0=latest, 1=river, 2=turn, 3=flop3
    if len(peaks) < 4:
        # ■ループの際、数が少ないとエラーの原因になる。３個切る場合ば終了（最低３個必要）
        return return_dic

    # 各変数の設定
    target_dir = peaks[0]['direction']  # Lineの方向
    grid = 0.02  # 調査の細かさ
    search_range = 0.1

    max_to_min_search = True  # Latestが上昇方向の場合、Maxから降りるように調査する＝加工の場合はMinから上るように調査(初期志向）(Falseで逆になる)
    # 調査価格情報の設定と情報格納
    if target_dir == 1:
        # latestが登り方向の場合
        search_min_price = peaks[0]['peak']  # 探索する最低値。(現在価格）
        search_max_price = peaks[0]['peak'] + search_range  # 探索する最高値
        if max_to_min_search:
            # 簡単に切り替えられるように（変更点が複数あるため、一括で変更できるようにした）
            target_price = search_max_price  # - grid  # MAX側から調査（登りの場合、上から調査）
        else:
            target_price = search_min_price  # + grid  # 登りの場合でもMinからスタート
    else:
        # latestが下り方向の場合
        search_min_price = peaks[0]['peak'] - search_range  # 探索する最低値。
        search_max_price = peaks[0]['peak']  # 探索する最高値
        if max_to_min_search:
            target_price = search_min_price  # + grid  # 下（Min）からスタート
        else:
            target_price = search_max_price  # - grid  # 下りの場合でもMAXからスタート
    line_base_info = {
        "line_base_time": peaks[0]['time'],  # 将来的に到達する場所のため、設定不可（とりあえず現在時刻？）
        "line_base_price": target_price,
        "line_base_direction": target_dir,  # 1の場合UpperLine（＝上値抵抗）
        "latest_direction": peaks[0]['direction'],  # 渡されたPeaksの直近の方向（＝直近の方向）
        "latest_time_in_df": peaks[0]['time'],  # Latest。直近の時間（渡されたDFで判断）
        "decision_price": target_df.iloc[0]['close'],  #
    }  # 以上、Line計算の元になるデータ（探索と想定探索で異なる）
    print(" 価格と方向", target_dir, "調査範囲:", search_min_price, "<=", target_price, "<=", search_max_price)

    # 価格の調査を開始
    while search_min_price <= target_price <= search_max_price:
        print("　◇", target_price)
        same_price_list = find_same_price_list_from_peaks(target_price, target_dir, peaks)
        print("    SEARCH LINE INFO ↓SameLineList")
        print("    ", same_price_list)
        print("    LineBaseInfo")
        print("    ", line_base_info)

        # ②Lineのストレングスを求める
        if len(same_price_list) == 0:
            # same_priceがない場合、次のループへ
            print("    同価格なし")
            pass
        else:
            # ③samePriceがある場合、ストレングスを求める
            strength_info = judge_line_strength_based_same_price_list(same_price_list)
            print("    強度確認")
            print("    ", strength_info)
            if strength_info['line_strength'] > 1:
                # 発見された場合、返却しループを終了
                return {
                    "line_base_info": line_base_info,
                    "same_price_list": same_price_list,
                    "strength_info": strength_info,
                    "target_price": target_price
                }

        # ④次のループへの準備★【重要部位】
        if target_dir == 1:
            # latest(想定するLINEが上方向）が登り方向の場合
            if max_to_min_search:  # 上から下に価格を探す場合
                target_price = target_price - grid
                # target_price = - grid  # 登りの場合は、上から探していく
            else:
                target_price = target_price + grid
                # target_price = + grid  # 登りの場合でも、下から探していく。(初期思想とは逆）
        else:
            if max_to_min_search:
                target_price = target_price + grid
                # target_price = + grid  # 下りの場合は、下から探していく
            else:
                target_price = target_price - grid
                # target_price = - grid  # 下りの場合でも、上から探していく ( 初期思想とは逆）

    # ダメな場合の返却
    return return_dic


def find_latest_line_based_river(*args):
    """
    :param *dic_args: 複数の引数を取る可能性があるが、２パターン.
    ①二つの引数がある場合 dic_args[0] = df_r、dic_args[1] = peaks
    　→ループ等で呼び出される場合がメイン。df_rは基本参考値で、peaksで実施するのが理想（計算量削減の為）
    ②一つだけの引数がある場合 dic_args[0] = df_r
     →単発で実行する場合のみ

    この関数の特徴は、
    find_same_price_list_from_peaksに渡すPeaksが、peaks[2:]と２以降になっていること。
    （fina_same_price_list_from_peaksは与えられたPeaksに対し調査してしまうため、riverを含まない範囲で渡す必要がある）

     <調査の対象について＞
     図で書くと、直近のターンポイント(river_peak)が、Lineとなっているかを確認する関数。
      \　　↓ここが対象となる（=river)
       \  /\←　この部分が２の場合に検出する（ここはLatestではない。２の場合＝１つ出来立ての足は省くので、このPeakは無いと同義）
        \/  \ ←これがLatestとして扱われるもの
    :return:
    """
    # 何が正解なのかわからないけど、最初に返却値を設定しておく
    return_dic = {
        "line_base_info": {},
        "same_price_list": {},
        "strength_info": {
            "line_strength": 0,
            "line_on_num": 0,
            "same_time_latest": 0
        }
    }

    # 準備部分（表示や、ピークスの算出を行う）
    if len(args) == 2:
        # 引数が二個の場合は、Peaksが来ている為、ピークスを求める必要なし
        target_df = args[0]
        peaks = args[1]
    else:
        # 引数が１つの場合（df_rのみ）、ピークスを求める必要あり
        target_df = args[0][0:40]
        peaks_info = p.peaks_collect_main(target_df, 12)
        peaks = peaks_info["all_peaks"]
    # 状況に応じた、ピークポイントの指定  # 添え字は0=latest, 1=river, 2=turn, 3=flop3
    if len(peaks) < 4:
        # ■ループの際、数が少ないとエラーの原因になる。３個切る場合ば終了（最低３個必要）
        return return_dic

    # (1) LINE探索する
    # ①riverの同じ価格のポイントを探す（riverのポイントのみ）
    # 1,旧順張りのためのLINEを見つける方法(riverを基準にする場合）
    target_price = peaks[1]['peak']  # [1]はriverを示す
    target_dir = peaks[1]['direction']
    line_base_info = {
        "line_base_time": peaks[1]['time'],  # River。
        "line_base_price": target_price,
        "line_base_direction": target_dir,  # 1の場合UpperLine（＝上値抵抗）
        "latest_direction": peaks[0]['direction'],  # 渡されたPeaksの直近の方向（＝直近の方向）
        "latest_time_in_df": peaks[0]['time'],  # Latest。直近の時間（渡されたDFで判断）
        "decision_price": target_df.iloc[0]['close'],  #
    }  # 以上、Line計算の元になるデータ（探索と想定探索で異なる）
    print(" 価格と方向", target_price, target_dir)
    # メモ　従来の使い方をすると、[1]まで入れると、重複して数えてしまうため、turn[2]以前を採用(riverとlatest[0]は不要）
    same_price_list = find_same_price_list_from_peaks(target_price, target_dir, peaks[2:])
    print("SEARCH LINE INFO ↓SameLineList")
    print(same_price_list)
    print("LineBaseInfo")
    print(line_base_info)
    print("")

    # ②Lineのストレングスを求める
    if len(same_price_list) == 0:
        # same_priceがない場合、即時、返却する
        return {  # take_position_flagの返却は必須。
            "line_base_info": line_base_info,
            "same_price_list": same_price_list,
            "strength_info": {
                "line_strength": 0,
                "line_on_num": 0,
                "same_time_latest": 0
            }
        }
    # samePriceがある場合はストレングスを求めていく
    strength_info = judge_line_strength_based_same_price_list(same_price_list)
    print("強度確認")
    print(strength_info)
    return {
        "line_base_info": line_base_info,
        "same_price_list": same_price_list,
        "strength_info": strength_info
    }


# def find_latest_river_line(*args):
#     """
#     :param *dic_args: 複数の引数を取る可能性があるが、２パターン.
#     ①二つの引数がある場合 dic_args[0] = df_r、dic_args[1] = peaks
#     　→ループ等で呼び出される場合がメイン。df_rは基本参考値で、peaksで実施するのが理想（計算量削減の為）
#     ②一つだけの引数がある場合 dic_args[0] = de_r
#      →単発で実行する場合のみ
#
#      <調査の対象について＞
#      図で書くと、直近のターンポイント(river_peak)が、Lineとなっているかを確認する関数。
#       \　　↓ここが対象となる（=river)
#        \  /\←　この部分が２の場合に検出する（ここはLatestではない。２の場合＝１つ出来立ての足は省くので、このPeakは無いと同義）
#         \/  \ ←これがLatestとして扱われるもの
#     :return:
#     """
#     # 準備部分（表示や、ピークスの算出を行う）
#     if len(args) == 2:
#         # 引数が二個の場合は、Peaksが来ている為、ピークスを求める必要なし
#         target_df = args[0]
#         peaks_all = args[1]
#     else:
#         # 引数が１つの場合（df_rのみ）、ピークスを求める必要あり
#         target_df = args[0][0:40]
#         peaks_info = p.peaks_collect_main(target_df, 12)
#         peaks_all = peaks_info["all_peaks"]
#     # 状況に応じた、ピークポイントの指定  # 添え字は0=latest, 1=river, 2=turn, 3=flop3
#     if len(peaks_all) < 4:
#         # ■ループの際、数が少ないとエラーの原因になる。３個切る場合ば終了（最低３個必要）
#         return {"line_strength": 0}
#
#     # (1) LINE探索する
#     # ⓪探索準備
#     target_p = 0  # riverのピークを採択（０がRiverの添え字）。
#     latest_peak = peaks_all[target_p]['peak']
#     latest_dir = peaks_all[target_p]['direction']
#     latest_gap = peaks_all[target_p]['gap']
#     latest_time = peaks_all[target_p]['time']
#     river_peak = peaks_all[1]['peak']  # riverのピークを求める（これがライン検索の基準となる）
#     river_peak_time = peaks_all[1]['time']
#     river_dir = peaks_all[1]['direction']
#     river_gap = peaks_all[1]['gap']
#     river_count = peaks_all[1]['count']
#     turn_count = peaks_all[2]['count']
#     flop3_count = peaks_all[3]['count']
#     # 平均のピークGapを計算する
#     sum = 0
#     for item in peaks_all:
#         sum += item['gap']
#     ave = sum / len(peaks_all)
#     # print("　　平均ピーク", ave)
#
#     # ①LatestとRiverの関係を求める（latestが大きいケースが、外しているケースが多い）Riverの0.4倍以下程度あってほしい
#     lr_ratio = latest_gap / river_gap
#
#     # ②探索開始
#     target_price = river_peak  # ★ 将来的に、想定価格で探す可能性があるため。
#     river_dir = river_dir
#     counter = 0  # 何回同等の値が出現したかを把握する
#     range_yen = f.cal_at_least_most(0.01, round(ave * 0.153, 3), 0.041)  #0.153倍が一番よかった(大きすぎないレベル）。。
#     depth_point_gap = 0  # 今のピークと一番離れている値、かつ、逆方向のポイント（同価格発見のタイミングでリセット）
#     depth_point = 0
#     depth_point_time = 0
#     depth_minus_count = depth_plus_count = 0
#     near_point_gap = 100  # 同価格ではないが、一番近い値、かつ、同方向のポイント(同価格を発見のタイミングでリセットされる）
#     near_point = 0
#     near_point_time = 0
#     near_minus_count = near_plus_count = 0
#     same_list = []
#     between_num = 0  # 間に何個のピークがあったか。最短ダブルトップのの場合は2(自分自身をカウントするため）
#     # print("　　　　ダブルトップ判定閾値", range_yen)
#     for i, item in enumerate(peaks_all):
#         # print("   target:", river_peak, " pair", item['peak'], item['time'], i, river_peak - range_yen <= item['peak'] <= river_peak + range_yen
#         #       , item['direction'])
#         if i < 1 + target_p:
#             # 自分自身の場合は探索せず。ただし自分自身は0ではなく１
#             continue
#
#         # 判定を行う
#         if i > 2 and target_price - range_yen <= item['peak'] <= target_price + range_yen:
#             # 同価格を発見した場合。
#             # print("　　　　同等のピーク発見", item['time'], abs(item['peak']-latest_peak))
#             counter += 1
#
#             # 何分前に発生した物かを計算（９０分以内なら、色々考えないとなぁ）
#             gap_time_min = f.seek_time_gap_seconds(river_peak_time, item['time']) / 60
#             # 方向に関する判定
#             if item['direction'] == river_dir:
#                 # print("    Between確認", between_num, item['time'])
#                 same_dir = True
#                 # print("　　　　同方向の近似ピーク（≒ダブルピークの素）", item['time'], near_point_gap)
#                 same_list.append({"time": item['time'],
#                                   "peak": item['peak'],
#                                   "same_dir": same_dir,
#                                   "gap_time_min": gap_time_min,
#                                   "count_foot_gap": i - target_p,
#                                   "depth_point_gap": round(depth_point_gap, 3),
#                                   'depth_point': depth_point,
#                                   "depth_point_time": depth_point_time,
#                                   "depth_minus_count": depth_minus_count,
#                                   "depth_plus_count": depth_plus_count,
#                                   "near_point_gap": round(near_point_gap, 3),
#                                   "near_point": near_point,
#                                   "near_point_time": near_point_time,
#                                   'near_minus_count': near_minus_count,
#                                   'near_plus_count': near_plus_count,
#                                   "between_num": between_num,
#                                   "i": i  # 何個目か
#                                   })
#                 # 通過したピーク情報を初期化する
#                 depth_point_gap = 0
#                 near_point_gap = 100
#                 between_num = 0
#             else:
#                 pass
#                 # same_dir = False
#                 # print("　　　逆方向の近似ピーク(= 踊り場的な扱い)")
#
#         else:
#             # 通過するピーク（同価格ではない）の場合、記録を残す。
#             # print(" 　　スルーカウント", item['time'], abs(item['peak']-latest_peak), depth_point_gap, near_point_gap, between_num + 1)
#             between_num += 1
#             # 条件分岐
#             if latest_dir == 1:
#                 # latestが上向き＝riverが下ピークの場合
#                 #       ↓depth
#                 # \  /\/\　
#                 #  \/ ↑  \/ ←latest(direction)
#                 #　　near ↑target_price(ライン検索値)
#                 peak_gap = item['peak'] - target_price  # プラス値の場合は上の図の通り。－値の場合は三尊形状（ライン越え）
#             else:
#                 # latestが下向きの場合　＝　riverが上向き
#                 #         ↓riverpeak(Lineの対象）
#                 #   /\    /\ ←latest
#                 #  /  \/\/
#                 #     　 ↑ depth
#                 #  ↑全てプラス値          ↑　near値が－値、depth値がプラス値（これはマイナスにはならない気がする）
#                 # print(" are????", target_price, item['peak'], item['time'])
#                 peak_gap = target_price - item['peak']  # プラスの場合上の絵。
#             # 計算
#             if item['direction'] != river_dir:
#                 # 方向が異なるピークの場合→Depthの方
#                 # 深さの値を取得する
#                 if peak_gap > depth_point_gap:
#                     # 最大深度を更新する場合
#                     depth_point_gap = peak_gap
#                     depth_point = item['peak']
#                     depth_point_time = item['time']
#                 # マイナスプラスをカウントする
#                 if peak_gap <= 0:
#                     depth_minus_count += 1
#                 else:
#                     depth_plus_count += 1
#             if item['direction'] == river_dir:
#                 # 同じピークの場合→Nearの方
#                 # ニアの方の深さの値を取得する
#                 if peak_gap < near_point_gap:
#                     # 最も近い価格を超える（かつ逆方向）場合
#                     near_point_gap = peak_gap
#                     near_point = item['peak']
#                     near_point_time = item['time']
#                 # マイナスプラスをカウントする
#                 # print(" nearPointGap", peak_gap, item['time'])
#                 if peak_gap <= 0:
#                     near_minus_count += 1
#                 else:
#                     near_plus_count += 1
#     # 同価格リスト
#     print("")
#     print("同価格リスト", "base", target_price, river_peak_time, river_peak - range_yen, "<r<", river_peak + range_yen,
#           "許容ギャップ", range_yen, "方向", river_dir, " 平均ピークGap", ave)
#     f.print_arr(same_list)
#     print(" ↑ここまで")
#
#     # ■LineStrengthを決定するため、同価格リストの結果をもとに、谷があるかを判定する
#     line_strength = 0.01
#     minus_counter = 0  # 初期値
#     if len(same_list) > 0:
#         # 同一価格が存在する場合(直近の同一価格、それ以前の同一価格（複数の可能性もあり）について調査を行う）
#         # ①まずは直近のSamePriceに関しての調査
#         # print("　　　　SamePriceが１つあり→　調査する")
#         # 同一価格の発見が１つの場合、
#         # ＊パターン１　同一価格の間のピーク数が４個(丁度）の場合は、そのラインは強いライン
#         #    以下の２パターンがあるが、どちらも強いラインの形（三尊、カルデラ）
#         # 　   \/\  /\/
#         # 　      \/  ↑river peak
#         # 　      ↑Near
#         # 　     ↓
#         # 　   /\/\
#         # 　 \/    \/
#         #      　　　↑river_peak
#         #  ＊パターン２　同一価格間のピーク数が４個よりも多い場合
#         # 　    /\/\/\
#         # 　  \/      \/
#         #             ↑　river_peak
#         #    near が半分以上マイナス値（ラインを割っている）の場合、信頼度が下がる
#         #
#         #   *パターン３　シンプルなダブルトップ系
#         #    /\/\
#         #   /
#         #    betweenが２の場合のみ
#
#         info = same_list[0]  # 同一価格が１つだけが成立（その情報を取得する）
#         # print("Between", info['between_num'])
#         # パターン１の処理
#         if info['between_num'] == 4:
#             line_strength = 2  # 強いラインとみなす
#
#         # パターン３の処理（シンプルダブルトップ）
#         if info['between_num'] == 2:
#             if info['gap_time_min'] <= 20:  # 20分いないのダブルトップは、信頼度低（単なるギザギザの可能性）
#                 # print("初回短すぎ・・？")
#                 line_strength = 1.5  # 割とLineを突破することが多い気がするが。。。
#             else:
#                 # print("適正？")
#                 line_strength = 2  # ただ、depthの深さによって変るのでは？
#
#         # パターン２の処理
#         if info['between_num'] > 4:
#             # nearマイナスの数が、nearの数の半分以上の場合
#             all_near_num = info['between_num'] / 2 - 1  # nearの数はこう求める
#             minus_ratio = info['near_minus_count'] / all_near_num
#             # print("    参考：マイナス比率", minus_ratio, info['near_minus_count'], all_near_num)
#             if minus_ratio >= 0.4:
#                 line_strength = 0.5
#             elif minus_ratio > 0:
#                 line_strength = 1.5
#             else:
#                 line_strength = 3
#
#         # ②同一価格が２個以上ある場合は、他も同号して検討する
#         # print("　　　　複数のSamePriceあり。強いLINEではあるが、当たってきてる回数が多いので、抜ける可能性大？")
#         if len(same_list) >= 2:
#             for i in range(len(same_list)):
#                 if same_list[i]['near_point_gap'] < 0:
#                     minus_counter += 1  # マイナスはLINEを超えた回数
#             if minus_counter > len(same_list) * 0.5:
#                 # LINE越えが過半数の場合、LINEの信頼度つぃては高くない
#                 line_strength = 0.5
#                 # print("　　　　複数時　弱強度", minus_counter, len(same_list))
#             elif minus_counter >= 1:
#                 line_strength = 1
#                 # print("　　　　複数時　１つ以上LINE越えあり", minus_counter)
#             else:
#                 # LINE越えがない為、LINEの信頼度が比較的高い
#                 line_strength = 3
#                 # print("　　　　複数時　強強度", minus_counter, len(same_list))
#     else:
#         pass
#
#     # # ただし、ぐちゃぐちゃしている場合（riverもturnもflop3もカウントが合計値が7以下（どれも２程度）の場合）LineStrengthを下げる
#     # if river_count + turn_count + flop3_count <= 7:
#     #     # print(peaks_all[1])
#     #     # print(peaks_all[2])
#     #     # print(peaks_all[3])
#     #     # print(river_count, turn_count, flop3_count)
#     #     print("   ◇◇ごちゃごちゃしている状態の為、ストレングスを解消", line_strength, "を０に", peaks_all[1]['count'],
#     #           peaks_all[2]['count'], peaks_all[3]['count'])
#     #     # line_strength = 0
#
#     return_dic = {  # take_position_flagの返却は必須。Trueの場合注文情報が必要。
#         "line_strength": line_strength,
#         "line_price": target_price,
#         "line_direction": river_dir,  # 1の場合UpperLine（＝上値抵抗）
#         "latest_direction": latest_dir,  # lineDirectionとは異なる(基本は逆になる）
#         "line_base_time": river_peak_time,  # 調査の開始対象となったLINE価格の元になる時刻
#         "latest_foot_gap": 99 if len(same_list) == 0 else same_list[0]['count_foot_gap'],
#         "latest_time": peaks_all[0]['time'],  # 実際の最新時刻
#         "line_on_num": len(same_list),
#         "minus_counter": minus_counter,
#         "decision_price": target_df.iloc[0]['close'],
#         "between_num": between_num,
#         "same_time_latest": 0 if len(same_list) == 0 else same_list[0]['time']  # 一番近い同一価格と判断した時刻
#     }
#
#     # if return_dic['line_strength'] != 0:
#     #     print("△結果")
#     #     print(return_dic)
#     #     # f.print_json(return_dic)
#     # print(" --")
#     print(" 結果", line_strength, return_dic)
#     return return_dic
