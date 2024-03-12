import fTurnInspection as t  # とりあえずの関数集
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
