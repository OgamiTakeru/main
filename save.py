import fBlockInspection as t  # とりあえずの関数集
import tokens as tk  # Token等、各自環境の設定ファイル（git対象外）
import classOanda as oanda_class
import fPeakLineInspection as p  # とりあえずの関数集
import fGeneric as f
import statistics

def add_stdev(peaks):
    """
    引数として与えられたPeaksに対して、偏差値を付与する
    :return:
    """
    # Gapのみを配列に置き換え（いい方法他にある？）
    targets = []
    for i in range(len(peaks)):
        targets.append(peaks[i]['gap'])
    # 平均と標準偏差を算出
    ave = statistics.mean(targets)
    stdev = statistics.stdev(targets)
    # 各偏差値を算出し、Peaksに追加しておく
    for i, item in enumerate(targets):
        peaks[i]["stdev"] = round((targets[i]-ave)/stdev*10+50, 2)

    return peaks


def size_compare(target, partner, min_range, max_range):
    """
    二つの数字のサイズ感を求める。
    (例）10, 9, 0.8, 1.2 が引数で来た場合、10の0.8倍＜9＜10の1.1倍　を満たしているかどうかを判定。
    :param partner: 比較元の数値（「現在に近いほう」が渡されるべき。どう変わったか、を意味するため）
    :param target: 比較対象の数値
    :param min_range: 最小の比率
    :param max_range: 最大の比率
    :return: {flag: 同等かどうか, comment:コメント}
    """
    if target * min_range <= partner <= target * max_range:
        # 同レベルのサイズ感の場合
        f_range_flag = True
        f_range_flag_detail = 0
        f_range_flag_comment = "同等"
    elif partner > target * max_range:
        # 直近を誤差内の最大値で考えても、before_change(過去)より小さい ⇒ 動きが少なくなった瞬間？
        f_range_flag = False
        f_range_flag_detail = 1
        f_range_flag_comment = "小さくなる変動直後"
    elif partner < target * min_range:
        # 直近を誤差内の最小値で考えても、before_change（過去）より大きい ⇒ 動きが激しくなった瞬間？
        f_range_flag = False
        f_range_flag_detail = -1
        f_range_flag_comment = "大きくなる変動直後"
    else:
        # 謎の場合
        f_range_flag = False
        f_range_flag_detail = 0
        f_range_flag_comment = "謎"

    return {
        "f_range_flag": f_range_flag,  # 同等の場合のみTrue
        "f_range_flag_detail": f_range_flag_detail,  # 判定結果として、大きくなった＝１、同等＝０、小さくなった＝ー１
        "f_range_flag_ratio": round(target / partner, 3),  # 具体的に何倍だったか
        "f_range_flag_comment": f_range_flag_comment,
        "min": round(target * min_range, 2),
        "max": round(target * max_range, 2),
        "before_change": partner,
        "after_change": target,
    }


def turn2Rule(df_r):
    """
    １、
    :return:
    """
    print("TURN2　ルール")
    df_r_part = df_r[:90]  # 検証に必要な分だけ抜き取る
    peaks_info = p.peaks_collect_main(df_r_part)  # Peaksの算出
    peaks = peaks_info['all_peaks']
    peaks = add_stdev(peaks)  # 偏差値を付与する
    f.print_arr(peaks)
    print("PEAKS↑")

    # 必要なピークを出す
    peak_river = peaks[0]  # 最新のピーク（リバーと呼ぶ。このCount＝２の場合、折り返し直後）
    peak_turn = peaks[1]  # 注目するポイント（ターンと呼ぶ）
    peak_flop3 = peaks[2]  # レンジ判定用（プリフロップと呼ぶ）
    peak_flop2 = peaks[3]  # レンジ判定用（プリフロップと呼ぶ）
    peaks_times = "Old:" + f.delYear(peak_flop3['time_old']) + "-" + f.delYear(peak_flop3['time']) + "_" + \
                  "Mid:" + f.delYear(peak_turn['time_old']) + "-" + f.delYear(peak_turn['time']) + "_" + \
                  "Latest" + f.delYear(peak_river['time_old']) + "-" + f.delYear(peak_river['time'])
    print("対象")
    print("直近", peak_river)
    print("ターン", peak_turn)
    print("古い3", peak_flop3)
    print("古い2", peak_flop2)

    # (1)リバーとターンで比較を実施する
    # ①偏差値の条件 (＠ターン）
    if peak_turn['stdev'] > 55:
        f_size = True
    else:
        f_size = False
    print("  偏差値:", f_size, " ", peak_flop3['stdev'])
    # ②カウントの条件（＠ターンとリバー）
    if peak_river['count'] == 2 and peak_turn['count'] >= 7:
        f_count = True
    else:
        f_count = False
    print("  カウント:", f_count, " 直近", peak_river['count'], "ターン", peak_turn['count'], "←直近2以下,ターン7以上でTrue")
    # ③戻り割合の条件（＠ターンとリバー）
    if peak_river['gap'] / peak_turn['gap'] < 0.5:  # 0.5の場合、半分以上戻っていたら戻りすぎ（False）。微戻り(半分以下)ならOK！
        f_return = True
    else:
        f_return = False
    print("  割合達成:", f_return, round(peak_river['gap'] / peak_turn['gap'], 1), " ", peak_river['gap'], peak_turn['gap'])
    # [最後]　各条件を考慮し、ポジションを持つかどうかを検討する
    if f_count and f_return and f_size:
        take_position = True
    else:
        take_position = False

    # (2) フロップ部の検証を行う⇒レンジ中なのかとかを確認できれば。。。
    col = "gap"  # 偏差値を使う場合はstdev　gapを使うことも可能
    # ①ターンとフロップ３について、サイズの関係性取得する(同程度のgapの場合、レンジ？）
    size_ans = size_compare(peak_turn[col], peak_flop3[col], 0.85, 1.15)
    turn_flop3_f = size_ans['f_range_flag']
    turn_flop3_detail = size_ans['f_range_flag_detail']
    print("  レンジ(フロップ３⇒ターン):", size_ans['f_range_flag'], size_ans['f_range_flag_comment'], " ", size_ans['after_change'],
          "範囲", size_ans['before_change'], "[", size_ans['min'], size_ans['max'], "]", size_ans['f_range_flag_ratio'])
    # ②フロップ３とフロップ２について、サイズの関係性を取得する
    size_ans = size_compare(peak_flop3[col], peak_flop2[col], 0.85, 1.15)
    flop3_flop2_f = size_ans['f_range_flag']
    flop3_flop2_detail = size_ans['f_range_flag_detail']
    print("  レンジ(フロップ２⇒フロップ3):", size_ans['f_range_flag'], size_ans['f_range_flag_comment'], " ", size_ans['after_change'],
          "範囲", size_ans['before_change'], "[", size_ans['min'], size_ans['max'], "]", size_ans['f_range_flag_ratio'])
    # ③ ターンとフロップ2について、サイズの関係性を取得する（フロップ３を挟む両サイドを意味する）
    #    フロップ２⇒フロップ３が小、フロップ３⇒ターンが大の場合、下げ方向強めの可能性。フロップ２とターンを比較する
    size_ans = size_compare(peak_turn[col], peak_flop2[col], 0.5, 2)
    turn_flop2_f = size_ans['f_range_flag']
    turn_flop2_detail = size_ans['f_range_flag_detail']
    print("  レンジ(フロップ２⇒ターン):", size_ans['f_range_flag'], size_ans['f_range_flag_comment'], " ", size_ans['after_change'],
          "範囲", size_ans['before_change'], "[", size_ans['min'], size_ans['max'], "]", size_ans['f_range_flag_ratio'])
    # <結果>
    #
    #  カクカクの条件
    #     フロップ3↓   /\←リバー
    #           /\  /←ターン
    #  　　   　/  \/
    #       　/←フロップ2
    #  ① フロップ２とターン　＞　フロップ３　(0.7倍くらいが目安？）　
    #  ② フロップ２とターンのサイズ比は不問
    #  ③ フロップ２とターンの偏差値は45程度は必要（小さすぎると微妙）　
    #  これらを満たしたとき、カクカクとみなす
    if turn_flop3_detail == 1 and flop3_flop2_detail == -1 and turn_flop2_detail == 0:
        if peak_flop2['direction'] == 1:
            print("  カクカク上がり発生中？")
        else:
            print("  カクカク下がり発生中？")
    elif turn_flop3_detail == -1 and flop3_flop2_detail == 1 and turn_flop2_detail == 0:
        if peak_flop2['direction'] == 1:
            print("  カクカク上がり発生中？")
        else:
            print("  カクカク下がり発生中？")
    else:
        print(" ", turn_flop3_detail, flop3_flop2_detail, turn_flop2_detail)

    if flop3_flop2_detail == 0 and turn_flop3_detail != 0:
        # ダブルトップ系（出来れば偏差値50くらいも条件に入れたいけれど）。turn_flop3==0でもいいかも？トリプルトップっぽくなる
        print("  ダブルトップ")
    else:
        print(" ", flop3_flop2_detail, turn_flop3_detail)

    return {
        "take_position": take_position,  # ポジション取得指示あり
        "s_time": df_r_part.iloc[0]['time_jp'],  # 直近の時刻（ポジションの取得有無は無関係）
        "trigger_price": peak_river['peak'],  # 直近の価格（ポジションの取得有無は無関係）
        "lc_range": peak_flop3['gap']/4,  # ロスカットレンジ（ポジションの取得有無は無関係）
        "tp_range": 0.05,  # 利確レンジ（ポジションの取得有無は無関係）
        "expect_direction": peak_flop3['direction'],  # ターン部分の方向
        # 以下参考項目
        "stdev": peak_flop3['stdev'],
        "o_count": peak_flop3['count'],
        "reterun_ratio": round(peak_river['gap'] / peak_flop3['gap'],1)
    }


def find_latest_line_choise_river_version(df_r):
    """
    直近のピーク価格について調査する。
    ただし直近のピークをどこに取るかは設定が変更できるようにする
    例えば、以下のようなケースの場合、
    0をriver(=latest)の場合と1をriverとする場合がある。
        /\ 1/\
      3/ 2\/ 0\
      /
    ただし、検証したいパターンによっては、知りたいピーク情報はターンとリバーの長さによって変ってくる
    基本的にはRiverピークを採択。
    turn = river
      t2=t        t2>t　　　　　t2<t
            ★           ★  　　   ★
        /\  /        /\  /     /\  /
       /  \/        /  \/        \/
                   /

    turn > river
      t2=t        t2>t　　　　　t2<t
        ★            ★
        /\           /\        /\
       /  \/        /  \/        \/
          ★       /             ★

    turn < river
      t2=t        t2>t　　　　　t2<t
                        ★
           /            /          /
        /\/          /\/     　 /\/
         ★         /            ★

    :param df_r:
    :return:
    """
    # 準備部分（表示や、ピークスの算出を行う）
    target_df = df_r[0:40]
    peaks_info = p.peaks_collect_main(df_r, 15)
    peaks_all = peaks_info["all_peaks"]
    # 状況に応じた、ピークポイントの指定  # 添え字は0=latest, 1=river, 2=turn, 3=flop3
    if len(peaks_all) < 4:
        # ■ループの際、数が少ないとエラーの原因になる。３個切る場合ば終了（最低３個必要）
        return {"line_strength": 0}

    turn2_gap = peaks_all[3]['gap']
    turn_gap = peaks_all[2]['gap']
    riv_gap = peaks_all[1]['gap']
    if 0 < abs(turn_gap - riv_gap) < 0.01:  # ほぼ同じ長さ、を意味したい
        comment = "　　　　LINEはTurn2で採択（Turn＝River）"
        target_p = 3
    elif turn_gap > riv_gap:
        if abs(turn2_gap - turn_gap) < max(turn_gap, turn2_gap) * 0.1:  # ほぼ同じ長さ、を意味したい
            # ほぼ同じ長さの場合は、同じ長さの端が揃う方を採択する（三角の頂点ではない）
            comment = "　　　　LINEはTurnを採択"
            target_p = 2
        elif turn2_gap > turn_gap:
            comment = "　　　　LINEはTurn2で採択"
            target_p = 3
        else:
            comment = "　　　　LINEはturnで採択"
            target_p = 2  # turnのピークを採択
    else:
        if abs(turn2_gap - turn_gap) < max(turn_gap, turn2_gap) * 0.1:  # ほぼ同じ長さ、を意味したい
            # ほぼ同じ長さの場合は、同じ長さの端が揃う方を採択する（三角の頂点ではない）
            comment = "　　　　LINEはTurnを採択"
            target_p = 2
        elif turn2_gap > turn_gap:
            comment = "　　　　LINEはTurn2で採択"
            target_p = 3
        else:
            comment = "　　　　LINEはturnで採択"
            target_p = 2  # turnのピークを採択
        # riv_gap > turn_gap
        # comment = "　　　　LINEはリバーを採択"
        # target_p = 1
    print("　　　　@レンジインスペクション", comment, turn_gap, riv_gap)
    line_strength = 0  # LINE強度の初期値を入れる

    # (0)最高値と最低値を取得
    # ・現在のピークがどの高さにいるか
    # ・どの価格帯が、濃いかを算出
    # を実施する
    now_price = target_df.iloc[0]['open']
    high = target_df["inner_high"].max()
    low = target_df["inner_low"].min()
    high_ave = target_df["inner_high"].mean()
    low_ave = target_df["inner_low"].mean()

    # (1) 直近のピークが再出現値か
    latest_peak = peaks_all[target_p]['peak']
    latest_dir = peaks_all[target_p]['direction']
    latest_time = peaks_all[target_p]['time']

    # 平均のピークGapを計算する
    sum = 0
    for item in peaks_all:
        sum += item['gap']
    ave = sum / len(peaks_all)
    # print("　　平均ピーク", ave)

    # 分析を開始する
    counter = 0  # 何回同等の値が出現したかを把握する
    range_yen = f.cal_at_least_most(0.01, round(ave * 0.1, 3), 0.035)  # * 0.38?  # 元々0.06の固定値。ただレンジのサイズ感によって変るべき
    same_dir = False
    depth_point_gap = 0  # 今のピークと一番離れている値、かつ、逆方向のポイント（同価格発見のタイミングでリセット）
    depth_point = 0
    depth_point_time = 0
    near_point_gap = 100   # 同価格ではないが、一番近い値、かつ、同方向のポイント(同価格を発見のタイミングでリセットされる）
    near_point = 0
    near_point_time = 0
    same_list = []
    # print("　　　　ダブルトップ判定閾値", range_yen)
    for i, item in enumerate(peaks_all):
        if i < 1 + target_p:
            # 自分自身の場合は探索せず。ただし自分自身は0ではなく１
            continue

        if i > 1 + target_p and latest_peak - range_yen <= item['peak'] <= latest_peak + range_yen:
            # 同価格を発見した場合。
            # if条件の、i>3 は、自分自身、不要な探索をスキップするため。
            # 4以下は、
            # \ 21 /
            # 3\/\/0　
            #  の形状を形成できないため、4以上の場合に探索スタート(i>3はそれを意味する)
            # 最初はcontinueだったが、スキップ部の情報を取得したいため、解除。
            # print("　　　　同等のピーク発見", item['time'], abs(item['peak']-latest_peak))
            counter += 1

            # 何分前に発生した物かを計算（９０分以内なら、色々考えないとなぁ）
            gap_time_min = f.seek_time_gap_seconds(latest_time, item['time']) / 60
            # 方向に関する判定
            if item['direction'] == latest_dir:
                same_dir = True
                # print("　　　　同方向の近似ピーク（≒ダブルピークの素）", item['time'], near_point_gap)
                same_list.append({"time": item['time'],
                                  "peak": item['peak'],
                                  "same_dir": same_dir,
                                  "gap_time_min": gap_time_min,
                                  "count_gap": i - target_p,
                                  "gap": round(abs(item['peak'] - latest_peak), 3),
                                  "depth_point_gap": round(depth_point_gap, 3),
                                  'depth_point': depth_point,
                                  "depth_point_time": depth_point_time,
                                  "near_point_gap": round(near_point_gap, 3),
                                  "near_point": near_point,
                                  "near_point_time": near_point_time,
                                  })
                # 通過したピーク情報を初期化する
                depth_point_gap = 0
                near_point_gap = 100
            else:
                pass
                # same_dir = False
                # print("　　　逆方向の近似ピーク(= 踊り場的な扱い)")

        else:
            # 通過するピーク（同価格ではない）の場合、記録を残す。
            # print(" CHECK", abs(item['peak']-latest_peak), depth_point_gap, near_point_gap)
            if latest_dir == 1:
                # 下ピークの場合
                #      ↓latest_peak
                # \    /
                #  \/\/

                caldera_gap = latest_peak - item['peak']  # プラス値の場合はカルデラ、－値の場合は三尊形状
                # print(" @", item['time'], caldera_gap)
                # 計算
                if caldera_gap > depth_point_gap and latest_dir != item['direction']:
                    # 最大高度を超える(かつ同方向）場合、入れ替えが発生
                    depth_point_gap = caldera_gap
                    depth_point = item['peak']
                    depth_point_time = item['time']
                if caldera_gap < near_point_gap and latest_dir == item['direction']:
                    # 最も近い価格を超える（かつ逆方向）場合、入れ替えが発生
                    near_point_gap = caldera_gap
                    near_point = item['peak']
                    near_point_time = item['time']
            else:
                # 上ピークの場合
                #   /\/\               \/\  /\/
                # \/    \/                \/  ↑latestPeak
                #      ↑latest_peak
                #  ↑全てプラス値          ↑　near値が－値、depth値がプラス値（これはマイナスにはならない気がする）
                caldera_gap = item['peak'] - latest_peak  # プラス値の場合は山、マイナスの場合は、逆コーンのような形状
                # print(" @", item['time'], near_point_gap,caldera_gap,latest_dir, item['direction'])
                # カルデラ形状
                if caldera_gap > depth_point_gap and latest_dir != item['direction']:
                    # 最大深度を超える(かつ同方向）場合、入れ替えが発生
                    depth_point_gap = caldera_gap
                    depth_point = item['peak']
                    depth_point_time = item['time']
                if caldera_gap < near_point_gap and latest_dir == item['direction']:
                    # 最も近い価格を超える（かつ逆方向）場合、入れ替えが発生
                    near_point_gap = caldera_gap
                    near_point = item['peak']
                    near_point_time = item['time']
    # f.print_arr(same_list)
    # print("　　　個数的には", counter, "回同等のぴーくが発生")
    # print("　　　対象ピークは", latest_peak, latest_dir)

    # 結果をもとに、谷があるかを判定する
    minus_counter = 0  # 複数発見時にしか利用しないが、LINEで履歴を送りたいので設定。
    if len(same_list) >= 2:
        # print("　　　　複数のSamePriceあり。強いLINEではあるが、当たってきてる回数が多いので、抜ける可能性大？")
        minus_counter = 0
        for i in range(len(same_list)):
            if same_list[i]['near_point_gap'] < 0:
                minus_counter += 1  # マイナスはLINEを超えた回数
        if minus_counter > len(same_list) * 0.5:
            # LINE越えが過半数の場合、LINEの信頼度つぃては高くない
            line_strength = 0.5
            # print("　　　　複数時　弱強度", minus_counter, len(same_list))
        elif minus_counter >= 1:
            line_strength = 1.5
            # print("　　　　複数時　１つ以上LINE越えあり", minus_counter)
        else:
            # LINE越えがない為、LINEの信頼度が比較的高い
            line_strength = 3
            # print("　　　　複数時　強強度", minus_counter, len(same_list))
    elif len(same_list) > 0:
        # print("　　　　SamePriceが１つあり→　調査する")
        # ニア（逆方向ピーク）までの凹みが、平均ピークのAveの半分以上ある場合は、深さが足りないと判断
        # 候補②　ニアまでの凹みが、直近のピークの３分の１までの折り返しに満たない状態だったら(長さが最大でも0.6倍）、カルデラとみなす
        # print(" バグだし", len(same_list))
        info = same_list[0]  # 同一価格が１つだけが成立（その情報を取得する）
        if info['near_point_gap'] < 0:
            # Nearが－値の場合値の場合 (これは強いLINEとは言いにくい？）
            #   \/\  /\/
            #      \/  ↑latestPeak
            #      ↑Near
            line_strength = 1  # ０は信用０　この場合は一度割って入るが、ある程度の信頼を置きたいため、１
            if info['count_gap'] == 4:
                pass
                # print("　　　　最小peaksでの成立(一度LINEを超えてから、戻ってきている状態)")
            else:
                pass
                # print("　　　　一度LINEを超えてから、戻ってきているじょつあい（最小Peaksではない）")
        else:
            # プラス値の場合は、一度もLINEを割ったことがないことになる（強いLINEといえる）
            #     ↓(間の底値がNearPoint） ここが６割程度の凹みがあれば、綺麗なカルデラ。
            #   /\/\
            # \/    \/
            #      　↑latest_peak
            line_strength = 2  # 久しく超えていないLINEの為、信頼度は高いLINEといえる
            if info['near_point_gap'] <= (info['depth_point_gap']*0.6):
                pass
                # print("  カルデラ成立", info['near_point_gap'], info['depth_point_gap'], info['depth_point_gap'] * 0.6)
            else:
                pass
                # print("  深いカルデラ成立", info['near_point_gap'], info['depth_point_gap'], info['depth_point_gap'] * 0.6)
    else:
        # sameLineが０の場合
        pass

    # 範囲情報
    # print(" 　 時間範囲", target_df.iloc[0]['time_jp'], ",", target_df.iloc[-1]['time_jp'])
    # print("　　価格範囲", high-low, high, low)  # 0.10以下は低い。なんなら0.15でも低いくらい。。
    # print("    価格範囲Ave", high_ave - low_ave, high_ave, low_ave)

    return {  # take_position_flagの返却は必須。Trueの場合注文情報が必要。
        "line_strength": line_strength,
        "line_price": latest_peak,
        "line_direction": latest_dir,  # 1は上端。
        "latest_direction": latest_dir,  # lineDirectionとは異なることもあり
        "line_base_time": latest_time,  # 調査の開始対象となったLINE価格の元になる時刻
        "latest_time": peaks_all[0]['time'],  # 実際の最新時刻
        "line_on_num": len(same_list),
        "minus_counter": minus_counter,
        "decision_price": now_price,
        "same_time_latest": 0 if len(same_list) == 0 else same_list[0]['time']  # 一番近い同一価格と判断した時刻
    }

