import fTurnInspection as t  # とりあえずの関数集
import tokens as tk  # Token等、各自環境の設定ファイル（git対象外）
import classOanda as oanda_class
import fPeakLineInspection as p  # とりあえずの関数集
import fGeneric as f
import statistics

oa = oanda_class.Oanda(tk.accountIDl, tk.access_tokenl, "live")  # クラスの定義


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

    # 表示用
    # print("      ", same_size, size_compare_comment, " ", after_change,
    #       "範囲", before_change, "[", round(after_change * min_range, 2), round(after_change * max_range, 2), "]", round(after_change / before_change, 3))

    return {
        # 順番通りの大小比較結果
        "size_compare_ratio": change_ratio,
        "size_compare_ratio_r": change_ratio_r,
        "gap": amount_of_change,
        "gap_abs": amount_of_change_abs,
        # サイズが同等かの判定
        "same_size": same_size,  # 同等の場合のみTrue
    }


def beforeDoublePeak(*args):
    """
    引数は配列で受け取る。今は最大二つを想定。
    引数１つ目：ローソク情報(逆順[直近が上の方にある＝時間降順])データフレームを受け取り、範囲の中で、ダブルトップ直前ついて捉える
    引数２つ目はループ検証時のパラメータ群(ループ検証の時のみ入ってくる）
    例→params_arr = [
            {"river_turn_ratio_min": 1, "river_turn_ratio": 1.3, "turn_flop_ratio": 0.6, "count": 2, "gap_min": 0, "gap": 0.02, "margin": 0.05, "sl": 1, "d": 1},
            {"river_turn_ratio_min": 1, "river_turn_ratio": 1.3, "turn_flop_ratio": 0.6, "count": 2, "gap_min": 0, "gap": 0.02, "margin": 0.05, "sl": 1, "d": 1},
        ]
    ①理想形 (ダブルトップ到達前）
　　　　　　　　　　　　　　　　　
       　　　　  　   /\← 10（基準：ターン）　←このピークがTP(ターンが10pipsや8本足くらいある場合は避ける（ちょい戻りを超えてる））
       フロップ　25→ /  \/  ← 7(リバー) ＋　割合だけでなく、数pipくらいトップピークまで余裕があれば。
          　　　　　/　　　　　　　　　←ピークの反対くらいがLC？

    ②
    :param df_r:
    :return:
    """
    # print(args)
    print("■直前ダブルピーク判定")
    df_r = args[0]
    df_r_part = df_r[:90]  # 検証に必要な分だけ抜き取る
    peaks_info = p.peaks_collect_main(df_r_part, 3)  # Peaksの算出（ループ時間短縮の為、必要最低限のピーク数（＝４）を指定する）
    peaks = peaks_info['all_peaks']

    # 必要なピークを出す
    peak_river = peaks[0]  # 最新のピーク（リバーと呼ぶ。このCount＝２の場合、折り返し直後）
    peak_turn = peaks[1]  # 注目するポイント（ターンと呼ぶ）
    peak_flop3 = peaks[2]  # レンジ判定用（プリフロップと呼ぶ）
    peaks_times = "River:" + f.delYear(peak_river['time']) + "-" + f.delYear(peak_river['time_old']) + "_" + \
                  "Turn:" + f.delYear(peak_turn['time']) + "-" + f.delYear(peak_turn['time_old']) + "_" + \
                  "FLOP3" + f.delYear(peak_flop3['time']) + "-" + f.delYear(peak_flop3['time_old'])
    print("  <対象>")
    print("  RIVER", peak_river)
    print("  TURN ", peak_turn)
    print("  FLOP3", peak_flop3)

    # (1) ターンを基準に
    col = "gap"  # 偏差値を使う場合はstdev　gapを使うことも可能
    # ⓪リバーのターンに対する割合を取得（〇%に小さくなっている事を想定）
    size_ans = size_compare(peak_river[col], peak_turn[col], 0.1, 0.3)
    river_turn_gap = round(size_ans['gap'], 3)
    river_turn_ratio = size_ans['size_compare_ratio']
    # ①ターンのフロップ３に対する割合を取得（〇%に小さくなっていることを想定）
    size_ans = size_compare(peak_turn[col], peak_flop3[col], 0.1, 0.3)
    turn_flop3_ratio = size_ans['size_compare_ratio']

    # ★★判定部
    # 条件値の設定（引数の有る場合は引数から設定）
    if len(args) == 2:  # 引数が存在する場合
        params = args[1]  # 引数の条件辞書を取得
        f_gap = 0.1
        rt_max = params['river_turn_ratio']
        tf_max = params['turn_flop_ratio']
        r_count = params['count']
        rt_gap_min = params['gap']
        p_margin = params['margin']
        t_count = params['tc']
        t_gap = params['tg']
        tp = (peak_turn['gap'] - peak_river['gap']) * params['tp']
        lc = (peak_turn['gap'] - peak_river['gap']) * params['lc']
        stop_or_limit = params['sl']
    else:
        # 基本的なパラメータ（呼び出し元から引数の指定でない場合、こちらを採用する）
        f_gap = 0.1  # フロップがは出来るだけ大きいほうが良い（強い方向を感じるため）
        rt_max = 0.7  # 0.6
        tf_max = 0.7  # 0.6
        r_count = 2  # 2
        rt_gap_min = 0.03  # 0.03
        p_margin = 0.008  # 0.01
        tp = (peak_turn['gap'] - peak_river['gap'])
        lc = (peak_turn['gap'] - peak_river['gap'])
        t_count = 7  # ターンは長すぎる(count)と、戻しが強すぎるため、この値以下にしておきたい。
        t_gap = 0.12  # ターンは長すぎる(gap)と、戻しが強すぎるため、この値以下にしておきたい。
        stop_or_limit = 1  # マージンの方向(+値は期待方向に対して取得猶予を取る場合(順張り),－値は期待と逆の場合は逆張り）
    # 判定
    take_position_flag = False  # ポジションフラグを初期値でFalseにする
    if peak_river['count'] == 2:  # リバーカウントは２丁度の場合のみ実施（最短）
        if turn_flop3_ratio < tf_max and peak_flop3['gap'] >= 0.06:  # フロップとターンの関係、フロップのサイズで分岐
            if river_turn_ratio < rt_max and abs(river_turn_gap) >= rt_gap_min and peak_river['count'] == r_count:  # ターンとリバーの関係、リバーの情報で分岐
                if peak_turn['gap'] <= t_gap and peak_turn['count'] <= t_count and peak_flop3['gap'] > f_gap:  # 各サイズで判定
                    take_position_flag = True
                    print("   ■■Beforeダブルトップ完成")
                else:
                    print("   不成立(サイズ)")
            else:
                print("   不成立(ターンリバー関係)")
                if len(args) != 2:
                    # 条件指定有の場合は送付しない（おおむね、テストなのでLINE送信しない。したらヤバイ）
                    tk.line_send(" リバー注目", peaks_times)
        else:
            print("   不成立(フロップターン関係)")
    else:
        print("   不成立(リバーCount)")
    print("   情報:", turn_flop3_ratio, "%", river_turn_ratio, "%", abs(river_turn_gap), peak_turn['gap'], peak_flop3['gap'])

    # target_priceを求める（そのが各変数を算出）
    position_margin = p_margin
    decision_price = df_r_part.iloc[0]['open']  # 計算用（リターンでも同じものを返却する）
    expected_direction = peak_river['direction']
    target_price = decision_price + (position_margin * expected_direction * stop_or_limit)
    # print("   ", peak_turn['gap']-peak_river['gap'])
    return {
        # ポジション検証に必要な要素
        "take_position_flag": take_position_flag,  # ポジション取得指示あり
        "decision_time": df_r_part.iloc[0]['time_jp'],  # 直近の時刻（ポジションの取得有無は無関係）
        "decision_price": df_r_part.iloc[0]['open'],  # ポジションフラグ成立時の価格（先頭[0]列のOpen価格）
        "position_margin": position_margin,  # position_margin (+値は猶予大）
        "stop_or_limit": stop_or_limit,
        "target_price": target_price,
        "lc_range": lc,  # 0.04,  # ロスカットレンジ（ポジションの取得有無は無関係）
        "tp_range": tp,  # 0.06,  # 利確レンジ（ポジションの取得有無は無関係）
        "expected_direction": expected_direction,
        # 以下参考項目
        "river_turn_ratio": river_turn_ratio,
        "turn_flop3_ratio": turn_flop3_ratio,
        "peak_river": peak_river['count'],
        "river_turn_gap": river_turn_gap,
        "tp_base": peak_turn['gap'] - peak_river['gap'],
        # パラメータ集
        "p_margin_min": p_margin,
        "p_turn_flop3_ratio_max": tf_max,
        "p_river_turn_ratio_max": rt_max,
        "p_river_turn_gap_max": abs(river_turn_gap),
        "p_turn_gap_max": t_gap,
        "p_flop_gap_max": f_gap,
        "p_tp": tp,
        "p_lc": lc,
    }


def beforeDoublePeakBreak(*args):
    """
    引数は配列で受け取る。今は最大二つを想定。
    引数１つ目：ローソク情報(逆順[直近が上の方にある＝時間降順])データフレームを受け取り、範囲の中で、ダブルトップ直前ついて捉える
    引数２つ目はループ検証時のパラメータ群(ループ検証の時のみ入ってくる）
    ②パターン２

　　　　　　　　　  ターン↓　　/　←このでっぱり部が、5pips以内（リーバーがターンの1.1倍以内？）
       　　　　  　   /\  /
       フロップ　30→ /  \/  ← 6(リバー) ＋　割合だけでなく、5pipくらいトップピークまで余裕があれば。
          　　　　　/　　　　　　　　　←ピークの反対くらいがLC？

    :param df_r:
    :return:
    """
    # print(args)
    print("■ダブルピークBreak判定")
    df_r = args[0]
    df_r_part = df_r[:90]  # 検証に必要な分だけ抜き取る
    peaks_info = p.peaks_collect_main(df_r_part, 3)  # Peaksの算出（ループ時間短縮の為、必要最低限のピーク数（＝４）を指定する）
    peaks = peaks_info['all_peaks']
    # f.print_arr(peaks)
    # print("PEAKS↑")

    # 必要なピークを出す
    peak_river = peaks[0]  # 最新のピーク（リバーと呼ぶ。このCount＝２の場合、折り返し直後）
    peak_turn = peaks[1]  # 注目するポイント（ターンと呼ぶ）
    peak_flop3 = peaks[2]  # レンジ判定用（プリフロップと呼ぶ）
    peaks_times = "Old:" + f.delYear(peak_flop3['time_old']) + "-" + f.delYear(peak_flop3['time']) + "_" + \
                  "Mid:" + f.delYear(peak_turn['time_old']) + "-" + f.delYear(peak_turn['time']) + "_" + \
                  "Latest" + f.delYear(peak_river['time_old']) + "-" + f.delYear(peak_river['time'])
    print("対象")
    print("直近", peak_river)
    print("ターン", peak_turn)
    print("古い3", peak_flop3)

    # (1) ターンを基準に
    col = "gap"  # 偏差値を使う場合はstdev　gapを使うことも可能
    # ⓪リバーのターンに対する割合を取得（〇%に小さくなっている事を想定）
    size_ans = size_compare(peak_river[col], peak_turn[col], 0.1, 0.3)
    river_turn_gap = round(size_ans['gap'], 3)
    river_turn_ratio = size_ans['size_compare_ratio']
    # ①ターンのフロップ３に対する割合を取得（〇%に小さくなっていることを想定）
    size_ans = size_compare(peak_turn[col], peak_flop3[col], 0.1, 0.3)
    turn_flop3_ratio = size_ans['size_compare_ratio']

    # ★★判定部
    # 条件値の設定（引数の有る場合は引数から設定）
    if len(args) == 2:  # 引数が存在する場合
        params = args[1]  # 引数の条件辞書を取得
        tf_max = params['turn_flop_ratio']
        rt_min = params['river_turn_ratio_min']
        rt_max = params['river_turn_ratio']
        rt_gap_min = params['gap_min']
        rt_gap_max = params['gap']
        r_count = params['count']
        p_margin = params['margin']
        lc = abs(peak_turn['gap']-peak_river['gap'])
        tp = abs(peak_turn['gap']-peak_river['gap'])
        stop_or_limit = params['sl']
        d = params['d']
    else:
        tf_max = 0.6  # あんまり戻りすぎていると、順方向に行く体力がなくなる？？だから少なめにしたい
        rt_min = 1.1
        rt_max = 1.5
        rt_gap_min = 0.00
        rt_gap_max = 0.03  # リバーがターンより長い量が、どの程度まで許容か(大きいほうがいい可能性も？）
        r_count = 2
        p_margin = 0.05
        lc = peak_river['gap']
        tp = peak_river['gap']
        stop_or_limit = 1
        d = 1
    # 判定
    take_position_flag = False
    if peak_river['count'] == 2:  # リバーのカウントは最短の２のみ
        if turn_flop3_ratio < tf_max and peak_flop3['gap'] >= 0.06:  # フロップ３とターンの関係、フロップ３のサイズ（GAP)について
            if rt_min < river_turn_ratio < rt_max and rt_gap_min < abs(river_turn_gap) < rt_gap_max:  # ターンとリバーの関係(率とgap）
                take_position_flag = True
                print("   ■■BREAK_Beforeダブルトップ完成")
            else:
                print("   不成立BREAK(リバーターン)")
        else:
            print("   不成立BREAK(ターンフロップ)")
    else:
        print("   不成立BREAK(リバーカウント)")
    print("   情報", turn_flop3_ratio, "%", river_turn_ratio, "%", turn_flop3_ratio, abs(river_turn_gap), peak_river['count'])

    # target_priceを求める（そのが各変数を算出）
    position_margin = p_margin
    stop_or_limit = stop_or_limit  # # マージンの方向(+値は期待方向に対して取得猶予を取る場合(順張り),－値は期待と逆の場合は逆張り）
    decision_price = df_r_part.iloc[0]['open']  # 計算用（リターンでも同じものを返却する）
    expected_direction = peak_river['direction'] * d
    target_price = decision_price + (position_margin * expected_direction * stop_or_limit)
    # print("   ", peak_turn['gap']-peak_river['gap'])
    return {
        # ポジション検証に必要な要素
        "take_position_flag": take_position_flag,  # ポジション取得指示あり
        "decision_time": df_r_part.iloc[0]['time_jp'],  # 直近の時刻（ポジションの取得有無は無関係）
        "decision_price": df_r_part.iloc[0]['open'],  # ポジションフラグ成立時の価格（先頭[0]列のOpen価格）
        "position_margin": position_margin,  # position_margin (+値は猶予大）
        "stop_or_limit": stop_or_limit,
        "target_price": target_price,
        "lc_range": lc, # 0.04,  # ロスカットレンジ（ポジションの取得有無は無関係）
        "tp_range": tp, #0.06,  # 利確レンジ（ポジションの取得有無は無関係）
        "expected_direction": expected_direction,
        # 以下参考項目
        "river_turn_ratio": river_turn_ratio,
        "turn_flop3_ratio": turn_flop3_ratio,
        "peak_river": peak_river['count'],
        "river_turn_gap": river_turn_gap,
        "tp_base": peak_turn['gap']-peak_river['gap']
    }


def wrapUp(df_r):
    """
    主にExeから呼ばれ、ダブル関係の結果をまとめ、注文形式にして返却する関数
    引数は現状ローソク情報(逆順[直近が上の方にある＝時間降順])のみ。
    :return:doublePeakの結果をまとめて、そのまま注文できるJsonの配列にして返却する
    """

    # （１）beforeDoublePeakについて
    # オーダーを二つに分解する。
    # 調査の結果、マージンが大きいほど勝率が上がることが判明。
    # その為、
    # 1 マージンを狭くして(５分足時は0.008)ポジション取得率を上げ、最低限の利確を目指すオーダー
    # 2 マージンを少し広くとり(5分足時は0.03)、勝率を上げつつ、大きな利益を狙いに行くオーダー
    # 検証を行う
    info = beforeDoublePeak(df_r)
    # オーダーの配列を定義する
    orders = []
    # 一旦結果を変数に入れておく
    decision_price = info['decision_price']
    position_margin = info['position_margin']
    expected_direction = info['expected_direction']
    tp_range = info['tp_range']
    lc_range = info['lc_range']
    stop_or_limit = info['stop_or_limit']
    if stop_or_limit == 1:
        type = "STOP"
    else:
        type = "LIMIT"
    # 1を作成（マージン小、利確小）
    orders.append(
        {
            "name": "MarginS-TPS",
            "order_permission": True,
            "target_price": decision_price + (0.008 * expected_direction * stop_or_limit),
            "tp_range": tp_range * 0.8,
            "lc_range": lc_range,
            "units": 10,
            "direction": expected_direction,
            "type": type,  # 1が順張り、-1が逆張り
            "trade_timeout": 1800,
            "remark": "test",
            "tr_range": 0,
        }
    )
    # 2を作成
    orders.append(
        {
            "name": "Margin_B-TP_B",
            "order_permission": True,
            "target_price": decision_price + (0.03 * expected_direction * stop_or_limit),
            "tp_range": tp_range * 3,
            "lc_range": lc_range,
            "units": 20,
            "direction": expected_direction,
            "type": type,  # 1が順張り、-1が逆張り
            "trade_timeout": 1800,
            "remark": "test",
            "tr_range": 0.05,
        }
    )
    # DoublePeakに関するデータ
    order_double_peak_before = {
        "take_position_flag": info['take_position_flag'],
        "orders": orders
    }

    # (2)beforeDoublePeakBreakについて
    # オーダーを二つに分解する。
    # 調査の結果、マージンが大きいほど勝率が上がることが判明。
    # その為、
    # 1 既に超えているので、超える側と、戻す側に両方にオーダーを入れておく
    info = beforeDoublePeakBreak(df_r)
    # オーダーの配列を定義する
    orders = []
    # 一旦結果を変数に入れておく
    decision_price = info['decision_price']
    position_margin = info['position_margin']
    expected_direction = info['expected_direction']
    tp_range = info['tp_range']
    lc_range = info['lc_range']
    stop_or_limit = info['stop_or_limit']
    if stop_or_limit == 1:
        type = "STOP"
    else:
        type = "LIMIT"
    # 1を作成（マージン小、利確小）
    orders.append(
        {
            "name": "Break_forward",
            "order_permission": True,
            "target_price": decision_price + (0.015 * expected_direction * stop_or_limit),
            "tp_range": tp_range * 0.8,
            "lc_range": lc_range,
            "units": 15,
            "direction": expected_direction,
            "type": type,  # 1が順張り、-1が逆張り
            "trade_timeout": 1800,
            "remark": "test",
            "tr_range": 0,
        }
    )
    # 2を作成(レンジの方向。リバーとは逆の方向）
    orders.append(
        {
            "name": "Break_reverse",
            "order_permission": True,
            "target_price": decision_price + (0.03 * (expected_direction * -1) * stop_or_limit),  # ダブルピークポイントにする？
            "tp_range": tp_range * 3,
            "lc_range": lc_range,
            "units": 25,
            "direction": expected_direction,
            "type": type,  # 1が順張り、-1が逆張り
            "trade_timeout": 1800,
            "remark": "test",
            "tr_range": 0.05,
        }
    )
    # DoublePeakに関するデータ
    order_double_peak_break = {
        "take_position_flag": info['take_position_flag'],
        "orders": orders
    }

    # 【オーダーを統合する】  現状同時に成立しないため、Trueの方のオーダーを採択する
    if order_double_peak_before['take_position_flag']:
        order_information = order_double_peak_before
        comment = "BEFORE"
    elif order_double_peak_break['take_position_flag']:
        order_information = order_double_peak_break
        comment = "BREAK"
    else:
        # 何もない場合はPositionFlagをFalseにして返す
        order_information = {"take_position_flag": False}

    # 参考（成立時は情報をLINE送信）
    if order_information['take_position_flag']:
        tk.line_send(comment, decision_price, expected_direction)

    return order_information

