import fBlockInspection as t  # とりあえずの関数集
import tokens as tk  # Token等、各自環境の設定ファイル（git対象外）
import classOanda as oanda_class
import fPeakInspection as p  # とりあえずの関数集
import fGeneric as gene
import fCommonFunction as cf
import fMoveSizeInspection as ms
import statistics
import pandas as pd
import fResistanceLineInspection as ri
import copy

oa = oanda_class.Oanda(tk.accountIDl, tk.access_tokenl, "live")  # クラスの定義


def peak_of_peak_judgement(peaks_past, flop3, df_r):
    """
    過去数個のピークの中で、フロップのピークが頂点かどうか(フロップが傾きマイナスなら最低値、逆なら最高値か)を判定する。
    とりあえず、最高値（最低値）であればTrue、最高値ではなくレンジ等の一部の場合はFalseを返却。
    当初、ダブルトップはピークOfピークの場合有効で、それ以外（レンジ等）の場合は成立しにくいと考えた。
    引数は２つ
    peaks:　検証に使わなかった残りのPeaksが渡される（大体Peaks[3:10]）0-2は検証で使用）
    flop3: ピーク判定を行うピーク。向きが山なのか谷なのか１の場合(=フロップが右肩上がり)は山。またピーク価格もする。
    :return:　peak Of Peakの場合Trueを返却。
    """
    # 必要なギャップを設定（PeakOfPeakを認定する為に、どの程度大きければ別とみなすのか）
    gap = -0.02  # Flop3の半分くらいは余裕度が欲しい

    # peak10個分だと少ないので、DfRでも検討する(自分自身も検索範囲に入っているんので、Gapを入れるとおかしくなる）
    part_of_df_r = df_r[15:40]  # ４時間分（４８足分）  # 自身(ターンピーク)を入れないためには、リバー2足＋ターン分で大体15足あれば。。
    print("　　　　PeakOfPeak最古時間", part_of_df_r.iloc[-1]['time_jp'])
    if flop3['direction'] == 1:
        # フロップ傾きが１の場合、flop['peak']より大きな値がないかを探索
        past_peak = part_of_df_r["inner_high"].max()
        # print("  最大価格", part_of_df_r["inner_high"].max())
        if flop3['peak'] >= past_peak + gap:
            # print(" ", flop3['peak'], past_peak + gap)
            peak_of_peak = True
        else:
            # print(" g", flop3['peak'], past_peak + gap)
            peak_of_peak = False
            print(" 　他に最大値が存在", part_of_df_r.loc[part_of_df_r["inner_high"].idxmax()]['time_jp'])
    else:
        # フロップ傾きがー１の場合、flop['peaks']より小さな値がないかを探索
        past_peak = part_of_df_r["inner_low"].min()
        # print("  最小価格", part_of_df_r["inner_low"].min())
        if flop3['peak'] <= past_peak - gap:
            # print("  ", flop3['peak'], past_peak - gap)
            peak_of_peak = True
        else:
            # print("  g", flop3['peak'], past_peak - gap)
            peak_of_peak = False
            print(" 　他に最小値が存在", part_of_df_r.loc[part_of_df_r["inner_low"].idxmin()]['time_jp'])

    # 終了
    return peak_of_peak


def size_compare(after_change, before_change, min_range, max_range):
    """
    二つの数字のサイズ感を求める。
    (例）10, 9, 0.8, 1.2 が引数で来た場合、10の0.8倍＜9＜10の1.1倍　を満たしているかどうかを判定。
    :param before_change:　比較対象の数値 （
    :param after_change: 比較元の数値（「現在に近いほう」が渡されるべき。どう変わったか、を結果として返却するため）
    :param min_range: 最小の比率
    :param max_range: 最大の比率
    :return: {flag: 同等かどうか, comment:コメント}
    """

    # (1)順番をそのままでサイスの比較を実施する
    amount_of_change = after_change - before_change  # 変化量（変化後ー変化前）
    amount_of_change_abs = abs(amount_of_change)  # 変化量の絶対値
    change_ratio = round(after_change / before_change, 3)  # AfterがBeforeの何倍か。（変化量ではなく、サイズのパーセンテージ）
    change_ratio_r = round(before_change / after_change, 3)  # AfterがBeforeの何倍か。（変化量ではなく、サイズのパーセンテージ）

    # （２）大きい方を基準にして、変化率を求める
    if before_change > after_change:
        big = before_change
        small = after_change
    else:
        big = after_change
        small = before_change

    if big * min_range <= small <= big * max_range:
        # 同レベルのサイズ感の場合
        same_size = 0
    else:
        # 謎の場合
        same_size = -1

    return {
        # 順番通りの大小比較結果
        "size_compare_ratio": change_ratio,
        "size_compare_ratio_r": change_ratio_r,
        "gap": amount_of_change,
        "gap_abs": amount_of_change_abs,
        # サイズが同等かの判定
        "same_size": same_size,  # 同等の場合のみTrue
    }


def double_peak_judgement_predict(dic_args):
    """
    ★ピークスは１０個必要
    １）引数について。関数を呼び出し、整流化する。最終的に必要なものは、
    df_r：必須となる要素（ローソク情報(逆順[直近が上の方にある＝時間降順])データフレーム）
    peaks：この関数の実行には必ず必要。開始時に渡されない場合、整流化関数でdf_rを元に算出される。
    params：無い場合もある。無い場合はNone、ある場合はDic形式。
    の三つ。
    ２）ロジックについて
    ＜ロジック概要＞ダブルトップを頂点とし、そこから戻る方向にポジションする。
                     ↓ 10pips（基準：リバー）
       　　23pips　   /\  /
           ターン　→ /  \/  ← 7pipsまで(レイテスト)
          　　　　　/　　　　　　　　　←ピークの反対くらいがLC？
    :return:　必須最低限　{"take_position_flag": boolean} の返却は必須。さらにTrueの場合注文情報が必要。
    """
    # print(dic_args)
    ts = "    "
    t6 = "      "
    print(ts, "■ダブルピーク判定関数")
    # (1)ピークスを取得（引数か処理）。この関数ではPeaksの情報を元にし、Dfは使わない。
    # ①必要最低限の項目たちを取得する
    fixed_information = cf.information_fix(dic_args)  # DFとPeaksが必ず返却される
    # 情報の取得
    df_r = fixed_information['df_r']
    peaks = fixed_information['peaks']
    latest = peaks[0]  # 最新のピーク（リバーと呼ぶ。このCount＝２の場合、折り返し直後）
    river = peaks[1]  # 注目するポイント（ターンと呼ぶ）
    turn = peaks[2]  # レンジ判定用（プリフロップと呼ぶ）
    flop3 = peaks[3]
    flop3_subscript = 3  # flop3は添え字的には「３」を意味する
    # テスト用パラメータの取得
    params = fixed_information['params']  # パラメータ情報の取得
    inspection_params = fixed_information['inspection_params']
    print(t6, "l", latest)
    print(t6, "r", river)
    print(t6, "t", turn)

    # (2)パラメータ指定。
    # ①　パラメータを設定する(検証用。売買に関するパラメータ）
    # inspection_params = {"margin": 0.01, "d": 1}
    if inspection_params:
        # 売買に関するパラメータがある場合(Noneでない場合）、各値を入れていく（１つ入れるなら全て設定する必要あり）
        position_margin = inspection_params['margin']
        d = inspection_params['d']  # 売買の方向。リバーの方向に対し、同方向の場合１（ライン突破）．逆方向の場合ー１(ラインで抵抗）
        sl = inspection_params['sl']  # Stop or Limit
        tp = gene.cal_at_least(0.06, (abs(river['peak'] - latest['peak_old']) * 1))  # 5pipsとなると結構大きい。Minでも3pips欲しい
        lc = gene.cal_at_least(0.05, (abs(river['peak'] - latest['peak_old']) * 0.8))
    else:
        # 売買に関してのパラメータ無し（ダブルトップで折り返しの方向で、固定のマージンやTP/LCで取得する）
        position_margin = 0.01
        d = -1  # 売買の方向。リバーの方向に対し、同方向の場合１．逆方向の場合ー１
        sl = 1
        tp = gene.cal_at_least(0.06, (abs(river['peak'] - latest['peak_old']) * 1))  # 5pipsとなると結構大きい。Minでも3pips欲しい
        lc = gene.cal_at_least(0.05, (abs(river['peak'] - latest['peak_old']) * 0.8))

    # ②　パラメータを設定する（対象の形状目標を変更できるようなパラメータ）
    # params = {"tf_ratio_max": 0.65, "rt_ratio_min": 0.4, "rt_ratio_max": 1, "t_count": 2, "t_count": 5}
    if params:
        # paramsが入っている場合（Noneでない場合）
        rt_min = params['rt_ratio_min']
        rt_max = params['rt_ratio_max']  # リバーは、ターンの６割値度
        lr_min = params['lr_ratio_min']  # レイテストは、リバーの最低４割程度
        lr_max = params['lr_ratio_max']  # レイテストは、リバーの最高でも６割程度
        lr_max_extend = params['lr_ratio_max_extend']  # レイテストは、リバーの最高でも６割程度
        t_count = params['t_count']
        r_count_min = params['r_count_min']  #
        r_count_max = params['r_count_max']  # ターンは長すぎる(count)と、戻しが強すぎるため、この値以下にしておきたい。
        r_body_max = 0.1
        l_count = params['l_count']
        turn_size = 0.12
    else:
        # パラメータがない場合、一番スタンダート（最初）の物で実施する
        rt_min = 0.07  # 0.1 がもともと。取りやすくした
        rt_max = 0.65  # リバーは、ターンの６割値度(0.65) ⇒
        lr_min = 0.24  # レイテストは、ある程度リバーに対して戻っている状態
        lr_max = 1  # レイテストは、リバーの最高でも６割程度
        lr_max_extend = 5
        t_count = 5
        r_count_min = 2  #
        r_count_max = 7  # リバーは長すぎる(count)と、戻しが強すぎるため、この値以下にしておきたい。（突破できなそう）
        r_body_max = 0.1  # リバーが１０pips以上あるとこれも戻しが強すぎるため、突破できないかも。
        l_count = 2
        turn_size = 0.0789  # 調子いいときは0.15 頻度を増やすために色々な場面を見た結果、個の値で試験

    # ■■　形状の判定部
    take_position_flag = False  # ポジションフラグを初期値でFalseにする
    #           t  r  l
    #           ↓　 ↓　↓　
    #             /\
    #            /  \/
    #           /
    # 　　　　　 / 　　　　
    # ①形状の判定
    # ①-1 【基本形状】各ブロックのサイズについて
    const_flag = False
    if latest['count'] >= l_count:
        if turn['count'] >= t_count:
            if river['gap'] >= 0.011 and r_count_min <= river['count'] <= r_count_max and river['gap'] < r_body_max:
                const_flag = True
                c = gene.str_merge("サイズ感は成立", turn['count'], river['count'], latest['count'], river['gap'])
            else:
                c = gene.str_merge("riverのサイズ、カウントが規定値外れ", river['count'], river['gap'])
        else:
            c = gene.str_merge("turnのカウントが規定値以下", turn['count'])
    else:
        c = gene.str_merge("latestのカウントが規定値以下", latest['count'])
    # *記録用の辞書配列を作成しておく
    for_inspection_dic = {
        "l_count": latest['count'],
        "t_gap": turn['gap'],
        "t_count": turn['count'],
        "r_gap": river['gap'],
        "r_count": river['count'],
    }

    # ①-2 【基本形状】各ブロック同士のサイズ感の比率について
    river_ratio_based_turn = round(river['gap'] / turn['gap'], 3)
    latest_ratio_based_river = round(latest['gap'] / river['gap'], 3)
    compare_flag = False
    confidence = 0
    if turn['gap'] > turn_size:
        if rt_min < river_ratio_based_turn < rt_max:
            if lr_min < latest_ratio_based_river < lr_max:
                compare_flag = True
                confidence = 1  # 一番信用のできる形のため、信頼度最大
                cr = gene.str_merge("サイズ割合は成立", river_ratio_based_turn, latest_ratio_based_river)
            elif lr_min < latest_ratio_based_river <= lr_max_extend:
                compare_flag = True
                confidence = 0.5  # 信頼度が微妙なため、信頼度半減(勢いがいいときは超えるんだけど、、超えない時もある）
                cr = gene.str_merge("サイズ割合は成立(LatestOver）", latest_ratio_based_river, lr_max_extend)
            else:
                cr = gene.str_merge("Latestが範囲外", latest_ratio_based_river, "規定値は", lr_max_extend, "以下")
        else:
            cr = gene.str_merge("riverがturnに対して大きすぎる", river_ratio_based_turn)
    else:
        cr = gene.str_merge("全体的に小さい（turnが小さい)", turn['gap'])
    # *サイズ比率を検証のために辞書化しておく
    for_inspection_dic['river_ratio_based_turn'] = river_ratio_based_turn
    for_inspection_dic['latest_ratio_based_river'] = latest_ratio_based_river

    # ①-3 両方成立する場合、TakePositionフラグがOnになる
    print(t6, "DoubleTop結果", c, cr)
    if const_flag and compare_flag:
        take_position_flag = True
    # ↑この上までで、TakePositionFlagは立つ (以下はTakePositionFlagがTrueの場合の追加検討に移行する）

    # ■■　細かい条件の確認（形状が成立していない場合は、このまま終了）
    if not take_position_flag:
        return {  # take_position_flagの返却は必須。Trueの場合注文情報が必要。
            "take_position_flag": False,  # take_position_flagの値と同様だが、わかりやすいようにあえてFalseで書いている
        }

    # ダブルトップ形状は確定した中で、他に細かい情報で判断していく
    # 追加の検討要素① flop3以前での動きの解析(すでに下落３回以上のターンを伴う大きな下落がある場合NG,山形状となる場合もNG）
    double_top_strength = 0  # DoubleTopが抵抗線となる場合は1、突破される予想の場合-1
    double_top_strength_memo = ""
    turn_time = turn['time']
    turn_peak = turn['peak']
    df_r_before_turn = df_r[df_r['time_jp'] < turn_time]
    turn_gap = turn['gap']
    temp_inspection_peaks = peaks[flop3_subscript:]  # flop以前のピークスすべて
    memo2 = ""
    # gene.print_arr(temp_inspection_peaks, 6)
    if latest['direction'] == -1:
        # 直近が下り方向の場合、折り返し基準のflop3は下がり。その前が下がりメインの場合、下がりきっていると思われる。
        # flop3以前の、最も高い値を算出（その時刻を算出）
        max_index = max(enumerate(temp_inspection_peaks), key=lambda x: x[1].get('peak', float('-inf')))[0]
        print(max_index, temp_inspection_peaks[max_index])
        temp_inspection_peaks = temp_inspection_peaks[:max_index]  # 最大値までの範囲で
        lower_peaks = [item for item in temp_inspection_peaks if item["direction"] == -1]  # Lower側
        lower_gap_total = sum(d['gap'] for d in lower_peaks)
        upper_peak = [item for item in temp_inspection_peaks if item["direction"] == 1]
        upper_gap_total = sum(d['gap'] for d in upper_peak)
        upper_lower_gap = round(lower_gap_total - upper_gap_total, 3)
        # print(lower_gap_total - upper_gap_total)
        # print(sum(d['gap'] for d in temp_inspection_peaks))

        # RiverピークとMaxの間に何個下向きのピークが存在するかをカウント
        gene.print_arr(temp_inspection_peaks[:max_index])
        peak_count_peaks = [item for item in temp_inspection_peaks[:max_index] if item["direction"] == -1]  # Lower側
        peak_count = len(peak_count_peaks)
        lower_upper_gap = abs(lower_gap_total - upper_gap_total)
        print(ts, "おかしい", lower_upper_gap, lower_gap_total, upper_gap_total)
        if lower_upper_gap / turn_gap >= 2 and lower_upper_gap >= 0.20:
            if flop3['count'] >= 5:  # and flop3['gap'] > 0.02:  # FLop3が長い場合、独立しているため、ここからの下落も考えられる
                print(t6, "突破形状維持（前が長いがFLOP3長め、もっと下がる）Upper:", upper_gap_total, "lower:", lower_gap_total, "t", turn_gap, "gap", lower_upper_gap)
                double_top_strength = -1
                double_top_strength_memo = double_top_strength_memo + ", 突破(より下)" + str(upper_lower_gap) + str(turn_gap)
            else:
                print(t6, "3回折り返し相当の下がりあり（これ以上下がらない状態）Upper:", upper_gap_total, "lower:", lower_gap_total, "t", turn_gap, "gap", lower_upper_gap, flop3['count'])
                double_top_strength = 1
                double_top_strength_memo = double_top_strength_memo + ", 下がり切り" + str(upper_lower_gap) + str(turn_gap)
        else:
            print(t6, "突破形状維持（3回折り返し以内の下がり、もっと下がる）Upper:", upper_gap_total, "lower:", lower_gap_total, "t", turn_gap, "gap", lower_upper_gap)
            double_top_strength = -1
            double_top_strength_memo = double_top_strength_memo + ", 突破(より下)"+ str(upper_lower_gap) + str(turn_gap)

        # 検証用の値を格納
        for_inspection_dic['lower_upper_gap'] = lower_upper_gap
        for_inspection_dic['lower_upper_gap_per_t_gap'] = round(lower_upper_gap / turn_gap, 3)
        for_inspection_dic['lower_gap_total'] = lower_gap_total
        for_inspection_dic['upper_gap_total'] = upper_gap_total
        for_inspection_dic['double_top_strength'] = double_top_strength

    else:
        # 直近が登り方向の場合、折り返し基準のflop3は下がり。その前が下がりメインの場合、下がりきっていると思われる。
        # flop3以前の、最も低い値を算出（その時刻を算出）
        min_index = min(enumerate(temp_inspection_peaks), key=lambda x: x[1].get('peak', float('-inf')))[0]
        # print(min_index, temp_inspection_peaks[min_index])
        temp_inspection_peaks = temp_inspection_peaks[:min_index]  # 最大値までの範囲で
        lower_peaks = [item for item in temp_inspection_peaks if item["direction"] == -1]  # Lower側
        lower_gap_total = sum(d['gap'] for d in lower_peaks)
        upper_peak = [item for item in temp_inspection_peaks if item["direction"] == 1]
        upper_gap_total = sum(d['gap'] for d in upper_peak)
        upper_lower_gap = round(upper_gap_total - lower_gap_total, 3)

        # RiverピークとMinの間に何個上向きのピークが存在するかをカウント
        gene.print_arr(temp_inspection_peaks[:min_index])
        peak_count_peaks = [item for item in temp_inspection_peaks[:min_index] if item["direction"] == 1]  # Lower側
        peak_count = len(peak_count_peaks)
        memo2 = "," + str(peak_count) + "ピーク有"

        lower_upper_gap = abs(lower_gap_total - upper_gap_total)
        if lower_upper_gap / turn_gap >= 2  and lower_upper_gap >= 0.20:
            if flop3['count'] >= 5: # and flop3['gap'] > 0.02::  # FLop3が長い場合、独立しているため、ここからの上昇も考えられる
                print(t6, "突破形状維持（前が長いがFLOP3長め、もっと上がる）Upper:", upper_gap_total, "lower:",lower_gap_total, "t", turn_gap, lower_upper_gap)
                double_top_strength = -1
                double_top_strength_memo = double_top_strength_memo + ", 突破(より上)" + str(upper_lower_gap) + str(turn_gap)
            elif latest['gap'] >= 0.1:
                print(t6, "レイテストが大きいため、戻す可能性大）Upper:", upper_gap_total, "lower:",lower_gap_total, "t", turn_gap, lower_upper_gap, flop3['count'])
                double_top_strength = 1
                double_top_strength_memo = double_top_strength_memo + ", 上がり切り" + str(upper_lower_gap) + str(turn_gap)
            else:
                print(t6, "3回折り返し相当の上がりあり（これ以上上がらない状態）Upper:",upper_gap_total,"lower:",lower_gap_total, "t", turn_gap, lower_upper_gap, flop3['count'])
                double_top_strength = 1
                double_top_strength_memo = double_top_strength_memo + ", 上がり切り" + str(upper_lower_gap) + str(turn_gap)
        else:
            print(t6, "突破形状維持（3回折り返し以内の上がり、もっと上がる）Upper:",upper_gap_total,"lower:",lower_gap_total, "t", turn_gap, lower_upper_gap)
            double_top_strength = -1
            double_top_strength_memo = double_top_strength_memo + ", 突破(より上)" + str(upper_lower_gap) + str(turn_gap)

        # 検証用の値を格納
        for_inspection_dic['lower_upper_gap'] = lower_upper_gap
        for_inspection_dic['lower_upper_gap_per_t_gap'] = round(lower_upper_gap / turn_gap, 3)
        for_inspection_dic['lower_gap_total'] = lower_gap_total
        for_inspection_dic['upper_gap_total'] = upper_gap_total
        for_inspection_dic['double_top_strength'] = double_top_strength


    # 追加の検討要素②　ターンで突発的な足がある場合、突破しにくいのでは、という判定
    # gene.print_json(turn)
    if turn['include_large']:
        # 大きな足をインクルードする場合、抵抗線の信頼度は強い
        print(t6, "急変動を含むため、抵抗側と判断")
        # tk.line_send("急変動を含むため、突破形状だが突破なし")
        double_top_strength = 1
        double_top_strength_memo = double_top_strength_memo + ", 突破(より上)" + str(upper_lower_gap) + str(turn_gap)
    # 検証用の値を格納
    for_inspection_dic['include_large'] = turn['include_large']
    for_inspection_dic['double_top_strength'] = double_top_strength

    return {
        "take_position_flag": take_position_flag,
        "confidence": confidence,  # latestが、すでに超えている(Break)しているかどうか。
        "double_top_strength": double_top_strength,
        "double_top_strength_memo": double_top_strength_memo,
        "latest": latest,
        "river": river,
        "turn": turn,
        "peaks": peaks,
        "for_inspection_dic": for_inspection_dic,
    }


def main_double_peak(dic_args):
    """
    本番用と練習用でオーダーを分けるために、関数を分割した.
    ダブルピークの判定を実施する
    """
    """
    ダブルトップを突破する強度。

    （基本的にLineの強度は、折り返す強さであらわされるため、突破する場合は強度はー１と表現される。）

    """
    # 表示時のインデント
    ts = "    "
    s6 = "      "

    answer = {  # take_position_flagの返却は必須。Trueの場合注文情報が必要。
        "take_position_flag": False,
        "order_before_finalized": "",
        "double_top_strength": "",
        "double_top_strength_memo": ""
    }

    # ■関数の開始準備（表示と情報の清流化）
    print(ts, "■ダブルトップ突破形状の確認")
    fixed_information = cf.information_fix(dic_args)  # DFとPeaksが必ず返却される
    target_df = fixed_information['df_r']
    peaks = fixed_information['peaks']

    # ■■DoublePeak系の判断　（これは上記のLineStrengthとは独立の考え方に近い）
    double_peak_info = double_peak_judgement_predict(dic_args)  # 関数呼び出しで形状の判定を実施する

    if not double_peak_info['take_position_flag']:
        return answer
    # ■オーダー作成パート
    take_position_flag = double_peak_info['take_position_flag']
    confidence = double_peak_info['confidence']
    double_top_strength = double_peak_info['double_top_strength']
    double_top_strength_memo = double_peak_info['double_top_strength_memo']
    peaks = double_peak_info['peaks']
    latest = double_peak_info['latest']
    river = double_peak_info['river']
    turn = double_peak_info['turn']

    # ■オーダーの作成を実施する
    # 価格の設定（現在価格、LC、等）
    now_price = cf.now_price()  # 現在価格の取得
    now_price = peaks[0]['peak']
    order_base_info = cf.order_base(now_price, target_df.iloc[0]['time_jp'])  # オーダーの初期辞書を取得する(nowPriceはriver['latest_price']で代用)
    # オーダーの可能性がある場合、オーダーを正確に作成する
    if double_top_strength < 0:
        # ストレングスが突破形状の場合(マイナス値）
        # LC価格の目安を求めるためのベースを計算
        print(ts, " なんでおかしいの？", river['peak'])
        lc_price_temp = river['peak'] + (0.03 * -1 * latest['direction'])  # 従来の設定ロスカット価格(直接価格指定）
        lc_range_temp = abs(now_price - lc_price_temp)  # 従来の設定ロスカ幅(計算用）
        lc = gene.cal_at_least(0.07, lc_range_temp)

        if confidence == 1:
            # 【突破形状】従来想定の突破形状
            main_order = copy.deepcopy(order_base_info)
            main_order['target'] = turn['peak']
            main_order['tp'] = 0.40
            main_order['lc'] = 0.12  # * line_strength  # 0.09  # LCは広め
            main_order['type'] = 'STOP'  # 順張り（勢いがいい場合通過している場合もあるかもだが）
            # main_order['type'] = 'MARKET'  # 順張り（勢いがいい場合通過している場合もあるかもだが）
            main_order['expected_direction'] = latest['direction']  # 突破方向
            main_order['priority'] = 2  # ほかので割り込まれない
            main_order['units'] = order_base_info['units'] * 1
            main_order['name'] = "突破形状（通常）"
        else:
            # 【突破形状】従来想定より、リバーの動きが速い (LCを小さくとる）
            double_top_strength = -0.9  # ★この場合のみ、このタイミングでストレングスを編集(いずれにせよ突破コース）
            main_order = copy.deepcopy(order_base_info)
            # main_order['target'] = river["peak"] + (0.02 * -1 * latest['direction']) # river(最新の折り返し地点）位まで戻る前提
            main_order['target'] = latest['peak'] + (0.022 * 1 * latest['direction'])  # 現在価格で挑戦する！（その代わりLCをturn価格に)
            main_order['tp'] = 0.40
            main_order['lc'] = 0.12  #　0.04
            # main_order['lc'] = river['peak'] + (0.03 * -1 * latest['direction'])
            main_order['type'] = 'STOP'  # 順張り
            # main_order['type'] = 'MARKET'  # 順張り（勢いがいい場合通過している場合もあるかもだが）
            main_order['expected_direction'] = latest['direction']  # 突破方向
            main_order['priority'] = 2  #
            main_order['units'] = order_base_info['units'] * 1
            main_order['name'] = "突破形状（latest大 LC小）"
    else:
        # ストレングスが抵抗形状の場合
        if confidence == 1:
            # 従来想定の突破形状の未遂（抵抗）
            main_order = copy.deepcopy(order_base_info)
            main_order['target'] = turn['peak']
            main_order['tp'] = 0.40
            main_order['lc'] = 0.12  # * line_strength  # 0.09  # LCは広め
            main_order['type'] = 'LIMIT'  # 順張り（勢いがいい場合通過している場合もあるかもだが）
            # main_order['type'] = 'MARKET'  # 順張り（勢いがいい場合通過している場合もあるかもだが）
            # main_order['tr_range'] = 0.10  # 要検討
            main_order['expected_direction'] = latest['direction'] * -1  # 抵抗方向
            main_order['priority'] = 2  # ほかので割り込まれない
            main_order['units'] = order_base_info['units'] * 1
            main_order['name'] = "NOT突破（突破形状だが）"
        else:
            # 従来想定より、リバーの動きが速いの未遂（抵抗）
            double_top_strength = 1  # ★この場合のみ、このタイミングでストレングスを編集(いずれにせよ突破コース）
            main_order = copy.deepcopy(order_base_info)
            lc_price_temp = river['peak'] + (0.03 * -1 * latest['direction'])  # 従来の設定ロスカット価格(直接価格指定）
            lc_range_temp = abs(now_price - lc_price_temp)  # 従来の設定ロスカ幅(計算用）
            lc = gene.cal_at_least(0.07, lc_range_temp)

            # main_order['target'] = river["peak"] + (0.02 * -1 * latest['direction']) # river(最新の折り返し地点）位まで戻る前提
            main_order['target'] = latest['peak'] + (0.022 * 1 * latest['direction'])  # 現在価格で挑戦する！（その代わりLCをturn価格に)
            main_order['tp'] = 0.40
            main_order['lc'] = 0.12  # 0.04
            # main_order['lc'] = river['peak'] + (0.03 * -1 * latest['direction'])
            main_order['type'] = 'LIMIT'  # 順張り
            # main_order['type'] = 'MARKET'  # 順張り（勢いがいい場合通過している場合もあるかもだが）
            # main_order['tr_range'] = 0.10  # 要検討
            main_order['expected_direction'] = latest['direction'] * -1  # 抵抗方向
            main_order['priority'] = 2  #
            main_order['units'] = order_base_info['units'] * 1
            main_order['name'] = "NOT突破（latest大の突破形状だが　LC小）"

    return {  # take_position_flagの返却は必須。Trueの場合注文情報が必要。
        "take_position_flag": take_position_flag,
        "order_before_finalized": main_order,
        "double_top_strength": double_top_strength,
        "double_top_strength_memo": double_top_strength_memo,
    }


def for_inspection_double_peak_judgement_predict(dic_args):
    """
    ★検証用！　検証ののデータを返し、さらに多めに取る。
    """
    # print(dic_args)
    ts = "    "
    t6 = "      "
    print(ts, "■ダブルピーク判定関数")
    # (1)ピークスを取得（引数か処理）。この関数ではPeaksの情報を元にし、Dfは使わない。
    # ①必要最低限の項目たちを取得する
    fixed_information = cf.information_fix(dic_args)  # DFとPeaksが必ず返却される
    # 情報の取得
    df_r = fixed_information['df_r']
    peaks = fixed_information['peaks']
    latest = peaks[0]  # 最新のピーク（リバーと呼ぶ。このCount＝２の場合、折り返し直後）
    river = peaks[1]  # 注目するポイント（ターンと呼ぶ）
    turn = peaks[2]  # レンジ判定用（プリフロップと呼ぶ）
    flop3 = peaks[3]
    flop3_subscript = 3  # flop3は添え字的には「３」を意味する
    # テスト用パラメータの取得
    params = fixed_information['params']  # パラメータ情報の取得
    inspection_params = fixed_information['inspection_params']
    print(t6, "l", latest)
    print(t6, "r", river)
    print(t6, "t", turn)

    # (2)パラメータ指定。
    # ①　パラメータを設定する(検証用。売買に関するパラメータ）
    # inspection_params = {"margin": 0.01, "d": 1}
    if inspection_params:
        # 売買に関するパラメータがある場合(Noneでない場合）、各値を入れていく（１つ入れるなら全て設定する必要あり）
        position_margin = inspection_params['margin']
        d = inspection_params['d']  # 売買の方向。リバーの方向に対し、同方向の場合１（ライン突破）．逆方向の場合ー１(ラインで抵抗）
        sl = inspection_params['sl']  # Stop or Limit
        tp = gene.cal_at_least(0.06, (abs(river['peak'] - latest['peak_old']) * 1))  # 5pipsとなると結構大きい。Minでも3pips欲しい
        lc = gene.cal_at_least(0.05, (abs(river['peak'] - latest['peak_old']) * 0.8))
    else:
        # 売買に関してのパラメータ無し（ダブルトップで折り返しの方向で、固定のマージンやTP/LCで取得する）
        position_margin = 0.01
        d = -1  # 売買の方向。リバーの方向に対し、同方向の場合１．逆方向の場合ー１
        sl = 1
        tp = gene.cal_at_least(0.06, (abs(river['peak'] - latest['peak_old']) * 1))  # 5pipsとなると結構大きい。Minでも3pips欲しい
        lc = gene.cal_at_least(0.05, (abs(river['peak'] - latest['peak_old']) * 0.8))

    # ②　パラメータを設定する（対象の形状目標を変更できるようなパラメータ）
    # params = {"tf_ratio_max": 0.65, "rt_ratio_min": 0.4, "rt_ratio_max": 1, "t_count": 2, "t_count": 5}
    if params:
        # paramsが入っている場合（Noneでない場合）
        rt_min = params['rt_ratio_min']
        rt_max = params['rt_ratio_max']  # リバーは、ターンの６割値度
        lr_min = params['lr_ratio_min']  # レイテストは、リバーの最低４割程度
        lr_max = params['lr_ratio_max']  # レイテストは、リバーの最高でも６割程度
        lr_max_extend = params['lr_ratio_max_extend']  # レイテストは、リバーの最高でも６割程度
        t_count = params['t_count']
        r_count_min = params['r_count_min']  #
        r_count_max = params['r_count_max']  # ターンは長すぎる(count)と、戻しが強すぎるため、この値以下にしておきたい。
        r_body_max = 0.1
        l_count = params['l_count']
        turn_size = 0.12
    else:
        # パラメータがない場合、一番スタンダート（最初）の物で実施する
        rt_min = 0.01  # リバーがターンに対してどの程度短くてもいいか
        rt_max = 0.95  # リバーは、ターンの６割値度(0.65)
        lr_min = 0.8  # レイテストが、リバーに対してどの程度戻っているか
        lr_max = 1  # レイテストは、リバーの最高でも６割程度
        lr_max_extend = 5
        t_count = 5
        r_count_min = 2  #
        r_count_max = 15  # 7リバーは長すぎる(count)と、戻しが強すぎるため、この値以下にしておきたい。（突破できなそう）
        r_body_max = 0.2  # リバーが１０pips以上あるとこれも戻しが強すぎるため、突破できないかも。
        l_count = 2
        turn_size = 0.0789  # 調子いいときは0.15 頻度を増やすために色々な場面を見た結果、個の値で試験

    # ■■　形状の判定部
    take_position_flag = False  # ポジションフラグを初期値でFalseにする
    #           t  r  l
    #           ↓　 ↓　↓　
    #             /\
    #            /  \/
    #           /
    # 　　　　　 / 　　　　
    # ①形状の判定
    # ①-1 【基本形状】各ブロックのサイズについて
    const_flag = False
    if latest['count'] >= l_count:
        if turn['count'] >= t_count:
            if river['gap'] >= 0.011 and r_count_min <= river['count'] <= r_count_max and river['gap'] < r_body_max:
                const_flag = True
                c = gene.str_merge("サイズ感は成立", turn['count'], river['count'], latest['count'], river['gap'])
            else:
                c = gene.str_merge("riverのサイズ、カウントが規定値外れ", river['count'], river['gap'])
        else:
            c = gene.str_merge("turnのカウントが規定値以下", turn['count'])
    else:
        c = gene.str_merge("latestのカウントが規定値以下", latest['count'])
    # *記録用の辞書配列を作成しておく
    for_inspection_dic = {
        "l_count": latest['count'],
        "t_gap": turn['gap'],
        "t_count": turn['count'],
        "r_gap": river['gap'],
        "r_count": river['count'],
    }

    # ①-2 【基本形状】各ブロック同士のサイズ感の比率について
    river_ratio_based_turn = round(river['gap'] / turn['gap'], 3)
    latest_ratio_based_river = round(latest['gap'] / river['gap'], 3)
    compare_flag = False
    confidence = 0
    if turn['gap'] > turn_size:
        if rt_min < river_ratio_based_turn < rt_max:
            if lr_min < latest_ratio_based_river < lr_max:
                compare_flag = True
                confidence = 1  # 一番信用のできる形のため、信頼度最大
                cr = gene.str_merge("サイズ割合は成立", river_ratio_based_turn, latest_ratio_based_river)
            elif lr_min < latest_ratio_based_river <= lr_max_extend:
                compare_flag = True
                confidence = 0.5  # 信頼度が微妙なため、信頼度半減(勢いがいいときは超えるんだけど、、超えない時もある）
                cr = gene.str_merge("サイズ割合は成立(LatestOver）", latest_ratio_based_river, lr_max_extend)
            else:
                cr = gene.str_merge("Latestが範囲外", latest_ratio_based_river, "規定値は", lr_max_extend, "以下")
        else:
            cr = gene.str_merge("riverがturnに対して大きすぎる", river_ratio_based_turn)
    else:
        cr = gene.str_merge("全体的に小さい（turnが小さい)", turn['gap'])
    # *サイズ比率を検証のために辞書化しておく
    for_inspection_dic['river_ratio_based_turn'] = river_ratio_based_turn
    for_inspection_dic['latest_ratio_based_river'] = latest_ratio_based_river

    # ①-3 両方成立する場合、TakePositionフラグがOnになる
    print(t6, "DoubleTop結果", c, cr)
    if const_flag and compare_flag:
        take_position_flag = True
    # ↑この上までで、TakePositionFlagは立つ (以下はTakePositionFlagがTrueの場合の追加検討に移行する）

    # ■■　細かい条件の確認（形状が成立していない場合は、このまま終了）
    if not take_position_flag:
        return {  # take_position_flagの返却は必須。Trueの場合注文情報が必要。
            "take_position_flag": False,  # take_position_flagの値と同様だが、わかりやすいようにあえてFalseで書いている
        }

    # ダブルトップ形状は確定した中で、他に細かい情報で判断していく
    # 追加の検討要素① flop3以前での動きの解析(すでに下落３回以上のターンを伴う大きな下落がある場合NG,山形状となる場合もNG）
    double_top_strength = 0  # DoubleTopが抵抗線となる場合は1、突破される予想の場合-1
    double_top_strength_memo = ""
    turn_time = turn['time']
    turn_peak = turn['peak']
    df_r_before_turn = df_r[df_r['time_jp'] < turn_time]
    turn_gap = turn['gap']
    temp_inspection_peaks = peaks[flop3_subscript:]  # flop以前のピークスすべて
    memo2 = ""
    # gene.print_arr(temp_inspection_peaks, 6)
    if latest['direction'] == -1:
        # 直近が下り方向の場合、折り返し基準のflop3は下がり。その前が下がりメインの場合、下がりきっていると思われる。
        # flop3以前の、最も高い値を算出（その時刻を算出）
        max_index = max(enumerate(temp_inspection_peaks), key=lambda x: x[1].get('peak', float('-inf')))[0]
        print(max_index, temp_inspection_peaks[max_index])
        temp_inspection_peaks = temp_inspection_peaks[:max_index]  # 最大値までの範囲で
        lower_peaks = [item for item in temp_inspection_peaks if item["direction"] == -1]  # Lower側
        lower_gap_total = sum(d['gap'] for d in lower_peaks)
        upper_peak = [item for item in temp_inspection_peaks if item["direction"] == 1]
        upper_gap_total = sum(d['gap'] for d in upper_peak)
        upper_lower_gap = round(lower_gap_total - upper_gap_total, 3)
        # print(lower_gap_total - upper_gap_total)
        # print(sum(d['gap'] for d in temp_inspection_peaks))

        # RiverピークとMaxの間に何個下向きのピークが存在するかをカウント
        gene.print_arr(temp_inspection_peaks[:max_index])
        peak_count_peaks = [item for item in temp_inspection_peaks[:max_index] if item["direction"] == -1]  # Lower側
        peak_count = len(peak_count_peaks)
        lower_upper_gap = abs(lower_gap_total - upper_gap_total)
        print(ts, "おかしい", lower_upper_gap, lower_gap_total, upper_gap_total)
        if lower_upper_gap / turn_gap >= 2 and lower_upper_gap >= 0.20:
            if flop3['count'] >= 5:  # and flop3['gap'] > 0.02:  # FLop3が長い場合、独立しているため、ここからの下落も考えられる
                print(t6, "突破形状維持（前が長いがFLOP3長め、もっと下がる）Upper:", upper_gap_total, "lower:", lower_gap_total, "t", turn_gap, "gap", lower_upper_gap)
                double_top_strength = -1
                double_top_strength_memo = double_top_strength_memo + ", 突破(より下)" + str(upper_lower_gap) + str(turn_gap)
            else:
                print(t6, "3回折り返し相当の下がりあり（これ以上下がらない状態）Upper:", upper_gap_total, "lower:", lower_gap_total, "t", turn_gap, "gap", lower_upper_gap, flop3['count'])
                double_top_strength = 1
                double_top_strength_memo = double_top_strength_memo + ", 下がり切り" + str(upper_lower_gap) + str(turn_gap)
        else:
            print(t6, "突破形状維持（3回折り返し以内の下がり、もっと下がる）Upper:", upper_gap_total, "lower:", lower_gap_total, "t", turn_gap, "gap", lower_upper_gap)
            double_top_strength = -1
            double_top_strength_memo = double_top_strength_memo + ", 突破(より下)"+ str(upper_lower_gap) + str(turn_gap)

        # 検証用の値を格納
        for_inspection_dic['lower_upper_gap'] = lower_upper_gap
        for_inspection_dic['lower_upper_gap_per_t_gap'] = round(lower_upper_gap / turn_gap, 3)
        for_inspection_dic['lower_gap_total'] = lower_gap_total
        for_inspection_dic['upper_gap_total'] = upper_gap_total
        for_inspection_dic['double_top_strength'] = double_top_strength

    else:
        # 直近が登り方向の場合、折り返し基準のflop3は下がり。その前が下がりメインの場合、下がりきっていると思われる。
        # flop3以前の、最も低い値を算出（その時刻を算出）
        min_index = min(enumerate(temp_inspection_peaks), key=lambda x: x[1].get('peak', float('-inf')))[0]
        # print(min_index, temp_inspection_peaks[min_index])
        temp_inspection_peaks = temp_inspection_peaks[:min_index]  # 最大値までの範囲で
        lower_peaks = [item for item in temp_inspection_peaks if item["direction"] == -1]  # Lower側
        lower_gap_total = sum(d['gap'] for d in lower_peaks)
        upper_peak = [item for item in temp_inspection_peaks if item["direction"] == 1]
        upper_gap_total = sum(d['gap'] for d in upper_peak)
        upper_lower_gap = round(upper_gap_total - lower_gap_total, 3)

        # RiverピークとMinの間に何個上向きのピークが存在するかをカウント
        gene.print_arr(temp_inspection_peaks[:min_index])
        peak_count_peaks = [item for item in temp_inspection_peaks[:min_index] if item["direction"] == 1]  # Lower側
        peak_count = len(peak_count_peaks)
        memo2 = "," + str(peak_count) + "ピーク有"

        lower_upper_gap = abs(lower_gap_total - upper_gap_total)
        if lower_upper_gap / turn_gap >= 2 and lower_upper_gap >= 0.20:
            if flop3['count'] >= 5:  # and flop3['gap'] > 0.02::  # FLop3が長い場合、独立しているため、ここからの上昇も考えられる
                print(t6, "突破形状維持（前が長いがFLOP3長め、もっと上がる）Upper:", upper_gap_total, "lower:",lower_gap_total, "t", turn_gap, lower_upper_gap)
                double_top_strength = -1
                double_top_strength_memo = double_top_strength_memo + ", 突破(より上)" + str(upper_lower_gap) + str(turn_gap)
            elif latest['gap'] >= 0.1:
                print(t6, "レイテストが大きいため、戻す可能性大）Upper:", upper_gap_total, "lower:",lower_gap_total, "t", turn_gap, lower_upper_gap, flop3['count'])
                double_top_strength = 1
                double_top_strength_memo = double_top_strength_memo + ", 上がり切り" + str(upper_lower_gap) + str(turn_gap)
            else:
                print(t6, "3回折り返し相当の上がりあり（これ以上上がらない状態）Upper:",upper_gap_total,"lower:",lower_gap_total, "t", turn_gap, lower_upper_gap, flop3['count'])
                double_top_strength = 1
                double_top_strength_memo = double_top_strength_memo + ", 上がり切り" + str(upper_lower_gap) + str(turn_gap)
        else:
            print(t6, "突破形状維持（3回折り返し以内の上がり、もっと上がる）Upper:",upper_gap_total,"lower:",lower_gap_total, "t", turn_gap, lower_upper_gap)
            double_top_strength = -1
            double_top_strength_memo = double_top_strength_memo + ", 突破(より上)" + str(upper_lower_gap) + str(turn_gap)

        # 検証用の値を格納
        for_inspection_dic['lower_upper_gap'] = lower_upper_gap
        for_inspection_dic['lower_upper_gap_per_t_gap'] = round(lower_upper_gap / turn_gap, 3)
        for_inspection_dic['lower_gap_total'] = lower_gap_total
        for_inspection_dic['upper_gap_total'] = upper_gap_total
        for_inspection_dic['double_top_strength'] = double_top_strength

    # TURNのLINEの強さを再判定
    temp = ri.main_turn_strength_inspection_and_order({"df_r": df_r, "peaks": peaks})
    for_inspection_dic['turn_strength'] = temp['target_line_strength']
    for_inspection_dic['len_turn_same_price_list'] = len(temp['turn_same_price_list'])

    # 追加の検討要素②　ターンで突発的な足がある場合、突破しにくいのでは、という判定
    # gene.print_json(turn)
    if turn['include_large']:
        # 大きな足をインクルードする場合、抵抗線の信頼度は強い
        print(t6, "急変動を含むため、抵抗側と判断")
        # tk.line_send("急変動を含むため、突破形状だが突破なし")
        double_top_strength = 1
        double_top_strength_memo = double_top_strength_memo + ", 突破(より上)" + str(upper_lower_gap) + str(turn_gap)
    # 検証用の値を格納
    for_inspection_dic['include_large'] = turn['include_large']
    for_inspection_dic['double_top_strength'] = double_top_strength

    # 直近5時間の中で、どの程度の高さにいるか（最大最小を4等分し、うち側の二つに入っているかどうか）


    return {
        "take_position_flag": take_position_flag,
        "confidence": confidence,  # latestが、すでに超えている(Break)しているかどうか。
        "double_top_strength": double_top_strength,
        "double_top_strength_memo": double_top_strength_memo,
        "latest": latest,
        "river": river,
        "turn": turn,
        "peaks": peaks,
        "for_inspection_dic": for_inspection_dic,
    }


def for_inspection_main_double_peak(dic_args):
    """
    検証用のダブルピークを呼び出すもの
    """
    # 表示時のインデント
    ts = "    "
    s6 = "      "

    answer = {  # take_position_flagの返却は必須。Trueの場合注文情報が必要。
        "take_position_flag": False,
        "order_before_finalized": "",
        "double_top_strength": "",
        "double_top_strength_memo": ""
    }

    # ■関数の開始準備（表示と情報の清流化）
    print(ts, "■ダブルトップ突破形状の確認")
    fixed_information = cf.information_fix(dic_args)  # DFとPeaksが必ず返却される
    target_df = fixed_information['df_r']
    peaks = fixed_information['peaks']

    # ■■DoublePeak系の判断　（これは上記のLineStrengthとは独立の考え方に近い）
    double_peak_info = for_inspection_double_peak_judgement_predict(dic_args)  # 関数呼び出しで形状の判定を実施する

    if not double_peak_info['take_position_flag']:
        return answer
    # ■オーダー作成パート
    take_position_flag = double_peak_info['take_position_flag']
    confidence = double_peak_info['confidence']
    double_top_strength = double_peak_info['double_top_strength']
    double_top_strength_memo = double_peak_info['double_top_strength_memo']
    peaks = double_peak_info['peaks']
    latest = double_peak_info['latest']
    river = double_peak_info['river']
    turn = double_peak_info['turn']

    # ■オーダーの作成を実施する
    # 価格の設定（現在価格、LC、等）
    now_price = cf.now_price()  # 現在価格の取得
    now_price = peaks[0]['peak']
    order_base_info = cf.order_base(now_price, target_df.iloc[0]['time_jp'])  # オーダーの初期辞書を取得する(nowPriceはriver['latest_price']で代用)
    # オーダーの可能性がある場合、オーダーを正確に作成する
    # 【突破形状】従来想定の突破形状
    main_order = copy.deepcopy(order_base_info)
    main_order['target'] = turn['peak']
    main_order['tp'] = 0.20
    main_order['lc'] = 0.20  # * line_strength  # 0.09  # LCは広め
    # main_order['type'] = 'STOP'  # 順張り（勢いがいい場合通過している場合もあるかもだが）
    main_order['type'] = 'MARKET'  # 順張り（勢いがいい場合通過している場合もあるかもだが）
    main_order['expected_direction'] = latest['direction'] * -1  # 突破方向
    main_order['priority'] = 2  # ほかので割り込まれない
    main_order['units'] = order_base_info['units'] * 1
    main_order['name'] = "共通条件（突破）"

    # if double_top_strength < 0:
    #     # ストレングスが突破形状の場合(マイナス値）
    #     # LC価格の目安を求めるためのベースを計算
    #     print(ts, " なんでおかしいの？", river['peak'])
    #     lc_price_temp = river['peak'] + (0.03 * -1 * latest['direction'])  # 従来の設定ロスカット価格(直接価格指定）
    #     lc_range_temp = abs(now_price - lc_price_temp)  # 従来の設定ロスカ幅(計算用）
    #     lc = gene.cal_at_least(0.07, lc_range_temp)
    #
    #     if confidence == 1:
    #         # 【突破形状】従来想定の突破形状
    #         main_order = copy.deepcopy(order_base_info)
    #         main_order['target'] = turn['peak']
    #         main_order['tp'] = 0.40
    #         main_order['lc'] = 0.12  # * line_strength  # 0.09  # LCは広め
    #         main_order['type'] = 'STOP'  # 順張り（勢いがいい場合通過している場合もあるかもだが）
    #         # main_order['type'] = 'MARKET'  # 順張り（勢いがいい場合通過している場合もあるかもだが）
    #         main_order['expected_direction'] = latest['direction']  # 突破方向
    #         main_order['priority'] = 2  # ほかので割り込まれない
    #         main_order['units'] = order_base_info['units'] * 1
    #         main_order['name'] = "突破形状（通常）"
    #     else:
    #         # 【突破形状】従来想定より、リバーの動きが速い (LCを小さくとる）
    #         double_top_strength = -0.9  # ★この場合のみ、このタイミングでストレングスを編集(いずれにせよ突破コース）
    #         main_order = copy.deepcopy(order_base_info)
    #         # main_order['target'] = river["peak"] + (0.02 * -1 * latest['direction']) # river(最新の折り返し地点）位まで戻る前提
    #         main_order['target'] = latest['peak'] + (0.022 * 1 * latest['direction'])  # 現在価格で挑戦する！（その代わりLCをturn価格に)
    #         main_order['tp'] = 0.40
    #         main_order['lc'] = 0.12  #　0.04
    #         # main_order['lc'] = river['peak'] + (0.03 * -1 * latest['direction'])
    #         main_order['type'] = 'STOP'  # 順張り
    #         # main_order['type'] = 'MARKET'  # 順張り（勢いがいい場合通過している場合もあるかもだが）
    #         main_order['expected_direction'] = latest['direction']  # 突破方向
    #         main_order['priority'] = 2  #
    #         main_order['units'] = order_base_info['units'] * 1
    #         main_order['name'] = "突破形状（latest大 LC小）"
    # else:
    #     # ストレングスが抵抗形状の場合
    #     if confidence == 1:
    #         # 従来想定の突破形状の未遂（抵抗）
    #         main_order = copy.deepcopy(order_base_info)
    #         main_order['target'] = turn['peak']
    #         main_order['tp'] = 0.40
    #         main_order['lc'] = 0.12  # * line_strength  # 0.09  # LCは広め
    #         main_order['type'] = 'LIMIT'  # 順張り（勢いがいい場合通過している場合もあるかもだが）
    #         # main_order['type'] = 'MARKET'  # 順張り（勢いがいい場合通過している場合もあるかもだが）
    #         # main_order['tr_range'] = 0.10  # 要検討
    #         main_order['expected_direction'] = latest['direction'] * -1  # 抵抗方向
    #         main_order['priority'] = 2  # ほかので割り込まれない
    #         main_order['units'] = order_base_info['units'] * 1
    #         main_order['name'] = "NOT突破（突破形状だが）"
    #     else:
    #         # 従来想定より、リバーの動きが速いの未遂（抵抗）
    #         double_top_strength = 1  # ★この場合のみ、このタイミングでストレングスを編集(いずれにせよ突破コース）
    #         main_order = copy.deepcopy(order_base_info)
    #         lc_price_temp = river['peak'] + (0.03 * -1 * latest['direction'])  # 従来の設定ロスカット価格(直接価格指定）
    #         lc_range_temp = abs(now_price - lc_price_temp)  # 従来の設定ロスカ幅(計算用）
    #         lc = gene.cal_at_least(0.07, lc_range_temp)
    #
    #         # main_order['target'] = river["peak"] + (0.02 * -1 * latest['direction']) # river(最新の折り返し地点）位まで戻る前提
    #         main_order['target'] = latest['peak'] + (0.022 * 1 * latest['direction'])  # 現在価格で挑戦する！（その代わりLCをturn価格に)
    #         main_order['tp'] = 0.40
    #         main_order['lc'] = 0.12  # 0.04
    #         # main_order['lc'] = river['peak'] + (0.03 * -1 * latest['direction'])
    #         main_order['type'] = 'LIMIT'  # 順張り
    #         # main_order['type'] = 'MARKET'  # 順張り（勢いがいい場合通過している場合もあるかもだが）
    #         # main_order['tr_range'] = 0.10  # 要検討
    #         main_order['expected_direction'] = latest['direction'] * -1  # 抵抗方向
    #         main_order['priority'] = 2  #
    #         main_order['units'] = order_base_info['units'] * 1
    #         main_order['name'] = "NOT突破（latest大の突破形状だが　LC小）"

    return {  # take_position_flagの返却は必須。Trueの場合注文情報が必要。
        "take_position_flag": take_position_flag,
        "order_before_finalized": main_order,
        "for_inspection_dic": double_peak_info['for_inspection_dic'],
        "double_top_strength": double_top_strength,
        "double_top_strength_memo": double_top_strength_memo,
    }

