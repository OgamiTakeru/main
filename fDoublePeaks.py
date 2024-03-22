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
    理想形 (ダブルトップ到達前）
　　　　　　　　　　　　　　　　　
       　　23pips　   /\← 10pips（基準：ターン）
           フロップ→ /  \/  ← 7pipsまで(リバー)
          　　　　　/　　　　　　　　　←ピークの反対くらいがLC？
       ルール一覧
       ・ターンはフロップの４割まで以内の戻り。出来れば５pips以内？（ターンが大きいと、完全な折り返しになる為。）
       ・リバーはターンの８割まで以内の戻り。出来ればターン起点（ダブルトップ成立ポイント）まで3pips欲しい
       ・利確、理想はターン起点。ただリバーが大きい時は小さすぎるので、その時は3pipsとする。
       ・ロスカは、リバーの倍？あるいはターンの半分の長さまで（価格指定）とか。

    :param df_r:
    :return:　必須最低限　{"take_position_flag": boolean} の返却は必須。さらにTrueの場合注文情報が必要。
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
    peaks_times = "◇River:" + f.delYear(peak_river['time']) + "-" + f.delYear(peak_river['time_old']) + "(" + str(peak_river['direction']) + ")" \
                  "◇Turn:" + f.delYear(peak_turn['time']) + "-" + f.delYear(peak_turn['time_old']) + "(" + str(peak_turn['direction']) + ")" \
                  "◇FLOP三" + f.delYear(peak_flop3['time']) + "-" + f.delYear(peak_flop3['time_old']) + "(" + str(peak_flop3['direction']) + ")"
    print("  <対象>")
    print("  RIVER", peak_river)
    print("  TURN ", peak_turn)
    print("  FLOP3", peak_flop3)
    # 計算のバグの都合で、directionが交互になっていない場合有。おかしいので、除外
    if peak_turn['direction'] == peak_river['direction']:
        return {"take_position_flag": False}

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
        tf_max = params['tf_ratio']
        rt_max = params['rt_ratio']
        r_count = params['count']
        rt_gap_min = params['rt_gap']
        p_margin = params['margin']
        t_count = params['tc']
        t_gap = params['tg']
        tp = f.cal_at_least(0.04, (peak_turn['gap'] - peak_river['gap']) * params['tp'])
        lc = f.cal_at_least(0.04, (peak_turn['gap'] - peak_river['gap']) * params['lc'])
        stop_or_limit = params['sl']
    else:
        # 基本的なパラメータ（呼び出し元から引数の指定でない場合、こちらを採用する）
        f_gap = 0.05  # フロップがは出来るだけ大きいほうが良い（強い方向を感じるため）
        tf_max = 0.4  # 0.6
        rt_max = 0.7  # 0.6
        r_count = 2  # 2
        rt_gap_min = 0  # 0.03
        p_margin = 0.008  # 0.01
        tp = f.cal_at_least(0.04, (peak_turn['gap'] - peak_river['gap']) * 1)  # 5pipsとなると結構大きい。Minでも3pips欲しい
        lc = f.cal_at_least(0.04, (peak_turn['gap'] - peak_river['gap'] * 1))
        t_count = 7  # ターンは長すぎる(count)と、戻しが強すぎるため、この値以下にしておきたい。
        t_gap = 0.12  # ターンは長すぎる(gap)と、戻しが強すぎるため、この値以下にしておきたい。出来れば８くらい・・？
        stop_or_limit = 1  # マージンの方向(+値は期待方向に対して取得猶予を取る場合(順張り),－値は期待と逆の場合は逆張り）
    # 判定
    take_position_flag = False  # ポジションフラグを初期値でFalseにする
    if peak_river['count'] == r_count:  # リバーカウントは２丁度の場合のみ実施（最短）
        if turn_flop3_ratio < tf_max and peak_flop3['gap'] >= f_gap:  # フロップとターンの関係、フロップのサイズで分岐
            if river_turn_ratio < rt_max and abs(river_turn_gap) >= rt_gap_min:  # ターンとリバーの関係、リバーの情報で分岐
                if peak_turn['gap'] <= t_gap and peak_turn['count'] <= t_count:  # ターンサイズで判定(大きいターンなNG）
                    take_position_flag = True
                    print("   ■■Beforeダブルトップ完成")
                else:
                    print("   不成立(サイズ)")
            else:
                print("   不成立(ターンリバー関係)")
                if len(args) != 2:
                    # 条件指定有の場合は送付しない（おおむね、テストなのでLINE送信しない。したらヤバイ）
                    tk.line_send(" リバー注目", river_turn_ratio, peaks_times)
        else:
            print("   不成立(フロップターン関係)")
    else:
        print("   不成立(リバーCount)")
    print("   情報 tf:", turn_flop3_ratio, "%(<", tf_max, "),rt:", river_turn_ratio, "%(<", rt_max, "),",
                    "rt_gap:", abs(river_turn_gap), "(<", 0, "), t_gap", peak_turn['gap'], "(<", t_gap,"),", peak_flop3['gap'])

    # target_priceを求める（そのが各変数を算出）
    position_margin = p_margin
    decision_price = df_r_part.iloc[0]['open']  # 計算用（リターンでも同じものを返却する）
    expected_direction = peak_river['direction']
    target_price = decision_price + (position_margin * expected_direction * stop_or_limit)
    if take_position_flag:  # 表示用（ポジションある時のみ表示する）
        print("   決心価格", df_r_part.iloc[0]['open'], "決心時間", df_r_part.iloc[0]['time_jp'])
        print("   注文価格", target_price, "向とSL", expected_direction, stop_or_limit)
    return {  # take_position_flagの返却は必須。Trueの場合注文情報が必要。
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
    :return:　必須最低限　{"take_position_flag": boolean} の返却は必須。さらにTrueの場合注文情報が必要。
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
    peaks_times = "◇River:" + f.delYear(peak_river['time']) + "-" + f.delYear(peak_river['time_old']) + "(" + str(peak_river['direction']) + ")" \
                  "◇Turn:" + f.delYear(peak_turn['time']) + "-" + f.delYear(peak_turn['time_old']) + "(" + str(peak_turn['direction']) + ")" \
                  "◇FLOP三" + f.delYear(peak_flop3['time']) + "-" + f.delYear(peak_flop3['time_old']) + "(" + str(peak_flop3['direction']) + ")"
    print("  <対象>")
    print("  RIVER", peak_river)
    print("  TURN ", peak_turn)
    print("  FLOP3", peak_flop3)
    # 計算のバグの都合で、directionが交互になっていない場合有。おかしいので、除外
    if peak_turn['direction'] == peak_river['direction']:
        return {"take_position_flag": False}

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
        tf_max = params['tf_ratio_max']
        rt_min = params['rt_ratio_min']
        rt_max = params['rt_ratio_max']
        rt_gap_min = params['gap_min']
        rt_gap_max = params['gap']
        r_count = params['count']
        p_margin = params['margin']
        lc = f.cal_at_least(0.04, peak_river['gap']* 1)  # abs(peak_turn['gap']-peak_river['gap'])
        tp = f.cal_at_least(0.04, peak_river['gap']* 1)  # abs(peak_turn['gap']-peak_river['gap'])
        stop_or_limit = params['sl']
        d = params['d']
    else:
        tf_max = 0.4  # あんまり戻りすぎていると、順方向に行く体力がなくなる？？だから少なめにしたい
        rt_min = 0.95
        rt_max = 1.8  # 余りリバーが強いと、力が枯渇している可能性。
        rt_gap_min = 0.00
        rt_gap_max = 0.22  # リバーがターンより長い量が、どの程度まで許容か(大きいほうがいい可能性も？）
        r_count = 2
        p_margin = 0.02
        lc = f.cal_at_least(0.04, peak_river['gap']* 1)
        tp = f.cal_at_least(0.04, peak_river['gap']* 1)
        stop_or_limit = 1
        d = 1
    # 判定
    take_position_flag = False
    if peak_river['count'] == 2:  # リバーのカウントは最短の２のみ
        if turn_flop3_ratio < tf_max and peak_flop3['gap'] >= 0.05:  # フロップ３とターンの関係、フロップ３のサイズ（GAP)について
            if rt_min < river_turn_ratio < rt_max:  # ターンとリバーの関係(率とgap)
                if rt_gap_min < abs(river_turn_gap) < rt_gap_max:  # リバーのサイズ感(どれくらい出てるか）
                    take_position_flag = True
                    print("   ■■BREAK_Beforeダブルトップ完成")
                else:
                    print("   不成立BREAK（リバーサイズ）", abs(river_turn_gap))
            else:
                print("   不成立BREAK(リバーターン)")
        else:
            print("   不成立BREAK(ターンフロップ率, flopサイズ)")
    else:
        print("   不成立BREAK(リバーカウント)")
    print("   情報 tf:", turn_flop3_ratio, "%(<", tf_max, "),rt:(", rt_min, "<)", river_turn_ratio, "%(<", rt_max, "),",
                    "f_gap:", peak_flop3['gap'], "(>", 0.05, "), rt_gap凸:(",
                    rt_min, "<)", river_turn_gap, "(<", rt_max, ")")

    # target_priceを求める（そのが各変数を算出）
    position_margin = p_margin
    stop_or_limit = stop_or_limit  # # マージンの方向(+値は期待方向に対して取得猶予を取る場合(順張り),－値は期待と逆の場合は逆張り）
    decision_price = df_r_part.iloc[0]['open']  # 計算用（リターンでも同じものを返却する）
    expected_direction = peak_river['direction'] * d
    target_price = decision_price + (position_margin * expected_direction * stop_or_limit)
    if take_position_flag:  # 表示用（ポジションある時のみ表示する）
        print("   決心価格", df_r_part.iloc[0]['open'], "決心時間", df_r_part.iloc[0]['time_jp'])
        print("   注文価格", target_price, "向とSL", expected_direction, stop_or_limit)

    return {
        # ポジション検証に必要な要素
        "take_position_flag": take_position_flag,  # ポジション取得指示あり
        "decision_time": df_r_part.iloc[0]['time_jp'],  # 直近の時刻（ポジションの取得有無は無関係）
        "decision_price": df_r_part.iloc[0]['open'],  # ポジションフラグ成立時の価格（先頭[0]列のOpen価格）
        "position_margin": position_margin,  # position_margin (+値は猶予大）
        "stop_or_limit": stop_or_limit,
        "target_price": target_price,  # 直接使うこともあるが、マージンを数種類で実行する場合、渡し先で再計算する場合もあり。
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


def notDoublePeak(*args):
    """
    引数は配列で受け取る。今は最大二つを想定。
    引数１つ目：ローソク情報(逆順[直近が上の方にある＝時間降順])データフレームを受け取り、範囲の中で、ダブルトップ直前ついて捉える
    引数２つ目はループ検証時のパラメータ群(ループ検証の時のみ入ってくる）
    ダブルピークにならなそうな（水平ダブルピークではなく、フラッグ両旗形式になると推定されるもの）
　　　＊〇上辺が傾きの有るフラッグ形状の入口の場合　まぁ可能性の薄いと判断した下の二つも包括して、逆張りしておけばよいか・・・？
　　　　　　　　　  　　ターン　　　　
       　　　　  　   /\↓   　←　ここより手前で戻ると推定するケース（徐々に上下の振れ幅が縮まる旗形状と推定）
       フロップ　30→ /  \  /← 6(リバー)
          　　　　　/    \/　　　　　　　
                 /     ↑　このポイントが6割以上戻っている

     ＊×？上辺が上方向に徐々に行く場合→これはbeforeDoublePeakでの狙い。ただターンが長い場合上手くいかなそうなので、この形は却下したい。

　　　　　　　　　  　　ターン　 /\ ←　(未来のリバー）下のピークラインと平行に近くなるようなピークを形成すると推定　　　
       　　　　  　   /\↓   /　
       フロップ　30→ /  \  /← 6(リバー)
          　　　　　/    \/　　　　　　　
                 /     ↑　このポイントが6割以上戻っている

     ＊×　徐々に下に行く入り口の場合　→このケースはbeforeDoublePeakで拾える。（リバーターンの戻し率が低い場合は特に）
　　　　　　　　　  　　ターン　
       　　　　  　   /\↓   　
       フロップ　30→ /  \  /\　
          　　　　　/    \/　\　←(未来のリバー)このタイミングで、下向きのbeforeDoublepeakにひっかかる（リバー戻り40以内の場合）　　　　　
                 /  リバー↑　\

    具体的な条件
    ・ターンがフロップに対して６割以上戻っている場合、戻りが強かった。ダブルトップではなくレンジの突入と推定する。
    ・リバーがターンの３割しか戻っていない（更に上まで３ピップスあれば）場合、利確を取れる幅がある。→順張りオーダー
    ・ターン開始を超えたところに、逆張りをオーダーする。フロップとターンの差分だけ、ターン起点にプラスしたポイントが逆張りターゲット。

    :param df_r:
    :return:　必須最低限　{"take_position_flag": boolean} の返却は必須。さらにTrueの場合注文情報が必要。
    """
    # print(args)
    print("■NOTダブルピーク判定")
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
    peaks_times = "◇River:" + f.delYear(peak_river['time']) + "-" + f.delYear(peak_river['time_old']) + "(" + str(peak_river['direction']) + ")" \
                  "◇Turn:" + f.delYear(peak_turn['time']) + "-" + f.delYear(peak_turn['time_old']) + "(" + str(peak_turn['direction']) + ")" \
                  "◇FLOP3:" + f.delYear(peak_flop3['time']) + "-" + f.delYear(peak_flop3['time_old']) + "(" + str(peak_flop3['direction']) + ")"
    print("  <対象>")
    print("  RIVER", peak_river)
    print("  TURN ", peak_turn)
    print("  FLOP3", peak_flop3)
    # 計算のバグの都合で、directionが交互になっていない場合有。おかしいので、除外
    if peak_turn['direction'] == peak_river['direction']:
        return {"take_position_flag": False}

    # (1) ターンを基準に
    col = "gap"  # 偏差値を使う場合はstdev　gapを使うことも可能
    # ⓪リバーのターンに対する割合を取得（〇%に小さくなっている事を想定）
    size_ans = size_compare(peak_river[col], peak_turn[col], 0.1, 0.3)
    river_turn_gap = round(size_ans['gap'], 3)
    river_turn_ratio = size_ans['size_compare_ratio']
    # ①ターンのフロップ３に対する割合を取得（〇%に小さくなっていることを想定）
    size_ans = size_compare(peak_turn[col], peak_flop3[col], 0.1, 0.3)
    turn_flop3_gap = round(size_ans['gap'], 3)
    turn_flop3_ratio = size_ans['size_compare_ratio']

    # ★★判定部
    # 条件値の設定（引数の有る場合は引数から設定）
    if len(args) == 2:  # 引数が存在する場合
        # TODO 検証用はまだ未作成。
        params = args[1]  # 引数の条件辞書を取得
        tf_min = params['tf_ratio_max']
        rt_max = params['rt_ratio_max']
        p_margin = params['margin']
        lc = f.cal_at_least(0.04, peak_river['gap']* 1)  # abs(peak_turn['gap']-peak_river['gap'])
        tp = f.cal_at_least(0.04, peak_river['gap']* 1)  # abs(peak_turn['gap']-peak_river['gap'])
        stop_or_limit = params['sl']
        d = params['d']
    else:
        tf_min = 0.6  # 戻りが大きいほうが、レンジや比較的大きく伸びずにギザギザ伸びていくと推定。最低でも６割戻しがある場合が該当
        rt_max = 0.4  # 利確ポイントを考えると、戻りが少ないほうがよい
        p_margin = river_turn_gap * 0.666  # 逆張りのポイントは、ターン起点より少し手前(大体３分の２＝0.66くらい？）
        lc = river_turn_gap + turn_flop3_gap
        tp = peak_turn['gap']
        stop_or_limit = -1
        d = 1
    # 判定
    take_position_flag = False
    if peak_river['count'] == 2:  # リバーのカウントは最短の２のみ
        if 1 > turn_flop3_ratio > tf_min and peak_flop3['gap'] >= 0.06:  # フロップ３とターンの関係、フロップ３のサイズ（GAP)について
            if river_turn_ratio < rt_max :  # ターンとリバーの関係(率とgap)
                    take_position_flag = True
                    print("   ■■RANGE_逆張り　完成")
                    tk.line_send(" ★RANGE逆張り　完成（オーダー無し）")
            else:
                print("   不成立RANGE(リバーターン)")
        else:
            print("   不成立RANGE(ターンフロップ率, flopサイズ)")
    else:
        print("   不成立RANGE(リバーカウント)")
    print("   情報 tf:(1>", turn_flop3_ratio, "%(>", tf_min, "),rt:", river_turn_ratio, "%(<", rt_max, "),",
                    "f_gap:", peak_flop3['gap'], "(>", 0.06, "), rt_gap:", river_turn_gap)

    # target_priceを求める（そのが各変数を算出）
    position_margin = p_margin
    stop_or_limit = stop_or_limit  # # マージンの方向(+値は期待方向に対して取得猶予を取る場合(順張り),－値は期待と逆の場合は逆張り）
    decision_price = df_r_part.iloc[0]['open']  # 計算用（リターンでも同じものを返却する）
    expected_direction = peak_river['direction'] * -1
    target_price = decision_price + (position_margin * expected_direction * stop_or_limit)
    if take_position_flag:  # 表示用（ポジションある時のみ表示する）
        print("   決心価格", df_r_part.iloc[0]['open'], "決心時間", df_r_part.iloc[0]['time_jp'])
        print("   注文価格", target_price, "向とSL", expected_direction, stop_or_limit)

    return {
        # ポジション検証に必要な要素
        "take_position_flag": take_position_flag,  # ポジション取得指示あり
        "decision_time": df_r_part.iloc[0]['time_jp'],  # 直近の時刻（ポジションの取得有無は無関係）
        "decision_price": df_r_part.iloc[0]['open'],  # ポジションフラグ成立時の価格（先頭[0]列のOpen価格）
        "position_margin": position_margin,  # position_margin (+値は猶予大）
        "stop_or_limit": stop_or_limit,
        "target_price": target_price,  # 直接使うこともあるが、マージンを数種類で実行する場合、渡し先で再計算する場合もあり。
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
    主にExeから呼ばれ、ダブル関係の結果(このファイル内のbeforeとbreak)をまとめ、注文形式にして返却する関数
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
            "lc_change": {"lc_change_exe": True, "lc_trigger_range": 0.3, "lc_ensure_range": 0.1}
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
            "lc_change": {"lc_change_exe": True, "lc_trigger_range": 0.3, "lc_ensure_range": 0.1}
        }
    )
    # DoublePeakに関するデータ
    order_double_peak_before = {
        "take_position_flag": info['take_position_flag'],
        "orders": orders
    }

    # (2)beforeDoublePeakBreakについて
    # オーダーを二つに分解する。
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
            "tp_range": tp_range * 1,
            "lc_range": lc_range,
            "units": 15,
            "direction": expected_direction,
            "type": type,  # 1が順張り、-1が逆張り
            "trade_timeout": 1800,
            "remark": "test",
            "tr_range": 0.05,
            "lc_change": {"lc_change_exe": True, "lc_trigger_range": 0.3, "lc_ensure_range": 0.1}
        }
    )
    # 2を作成(レンジの方向。リバーとは逆の方向）
    orders.append(
        {
            "name": "Break_reverse",
            "order_permission": True,
            "target_price": decision_price + (0.03 * (expected_direction * -1) * stop_or_limit),  # ダブルピークポイントにする？
            "tp_range": tp_range * 1,
            "lc_range": lc_range,
            "units": 25,
            "direction": (expected_direction * -1),
            "type": type,  # 1が順張り、-1が逆張り
            "trade_timeout": 1800,
            "remark": "test",
            "tr_range": 0.05,
            "lc_change": {"lc_change_exe": True, "lc_trigger_range": 0.3, "lc_ensure_range": 0.1}
        }
    )
    # DoublePeakに関するデータ
    order_double_peak_break = {
        "take_position_flag": info['take_position_flag'],
        "orders": orders
    }

    # (3) 色々複合
    info = notDoublePeak(df_r)


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



def triplePeaks(*args):
    """
    引数は配列で受け取る。今は最大二つを想定。
    引数１つ目：ローソク情報(逆順[直近が上の方にある＝時間降順])データフレームを受け取り、範囲の中で、ダブルトップ直前ついて捉える
    引数２つ目はループ検証時のパラメータ群(ループ検証の時のみ入ってくる）
    例→params_arr = [
            {"river_turn_ratio_min": 1, "river_turn_ratio": 1.3, "turn_flop_ratio": 0.6, "count": 2, "gap_min": 0, "gap": 0.02, "margin": 0.05, "sl": 1, "d": 1},
            {"river_turn_ratio_min": 1, "river_turn_ratio": 1.3, "turn_flop_ratio": 0.6, "count": 2, "gap_min": 0, "gap": 0.02, "margin": 0.05, "sl": 1, "d": 1},
        ]
    理想形 (ダブルトップ到達前）
　　　　　　　　　　　　　　　　　
       　　23pips　   /\← 10pips（基準：ターン）
           フロップ→ /  \/  ← 7pipsまで(リバー)
          　　　　　/　　　　　　　　　←ピークの反対くらいがLC？
       ルール一覧
       ・ターンはフロップの４割まで以内の戻り。出来れば５pips以内？（ターンが大きいと、完全な折り返しになる為。）
       ・リバーはターンの８割まで以内の戻り。出来ればターン起点（ダブルトップ成立ポイント）まで3pips欲しい
       ・利確、理想はターン起点。ただリバーが大きい時は小さすぎるので、その時は3pipsとする。
       ・ロスカは、リバーの倍？あるいはターンの半分の長さまで（価格指定）とか。

    :param df_r:
    :return:　必須最低限　{"take_position_flag": boolean} の返却は必須。さらにTrueの場合注文情報が必要。
    """
    # print(args)
    print("■3つの力判定")
    df_r_part = args[0][:90]  # 検証に必要な分だけ抜き取る
    peaks_info = p.peaks_collect_main(df_r_part, 3)  # Peaksの算出（ループ時間短縮の為、必要最低限のピーク数（＝４）を指定する）
    peaks = peaks_info['all_peaks']

    # 必要なピークを出す
    river = peaks[0]  # 最新のピーク（リバーと呼ぶ。このCount＝２の場合、折り返し直後）
    turn = peaks[1]  # 注目するポイント（ターンと呼ぶ）
    flop3 = peaks[2]  # レンジ判定用（プリフロップと呼ぶ）
    peaks_times = "◇River:" + \
                  f.delYear(river['time']) + "-" + f.delYear(river['time_old']) + "(" + str(river['direction']) + ")" \
                  "◇Turn:" + \
                  f.delYear(turn['time']) + "-" + f.delYear(turn['time_old']) + "(" + str(turn['direction']) + ")" \
                  "◇FLOP三" + \
                  f.delYear(flop3['time']) + "-" + f.delYear(flop3['time_old']) + "(" + str(flop3['direction']) + ")"
    print("  <対象>")
    print("  RIVER", river)
    print("  TURN ", turn)
    print("  FLOP3", flop3)

    # (1) ターンを基準に
    col = "gap"  # 偏差値を使う場合はstdev　gapを使うことも可能
    # ⓪リバーのターンに対する割合を取得（〇%に小さくなっている事を想定）
    size_ans = size_compare(river[col], turn[col], 0.1, 0.3)
    river_turn_gap = round(size_ans['gap'], 3)
    river_turn_ratio = size_ans['size_compare_ratio']
    # ①ターンのフロップ３に対する割合を取得（〇%に小さくなっていることを想定）
    size_ans = size_compare(turn[col], flop3[col], 0.1, 0.3)
    turn_flop3_gap = round(size_ans['gap'], 3)
    turn_flop3_ratio = size_ans['size_compare_ratio']

    # (2)条件の設定
    # フロップターンの関係
    tf1 = 0.6
    tf2 = 0.7
    tf3 = 1.0
    tf4 = 1.5
    # ターンリバーの関係
    tr1_1 = 0.6
    tr1_2 = 0.9
    tr1_3 = 1.1
    tr1_4 = 1.4
    #
    tr3_1 = 0.3
    #
    tr4_1 = 0.7
    tr4_2 = 1.0
    # 一部計算が複雑なものをあらかじめ生成しておく。
    temp_ratio = 0.2
    if river['direction'] == 1:
        flag_target_price = turn['peak_old'] - (turn['gap'] * temp_ratio)
        margin_for_flag = flag_target_price - river['peak']
    else:
        flag_target_price = turn['peak_old'] - (turn['gap'] * temp_ratio)
        margin_for_flag = river['peak'] - flag_target_price

    # (3)判定処理  （マージン、ポジション方向、タイプ、TP、LCを取得する）
    # 初期値の設定
    take_position_flag = False
    position_margin = 0
    expected_direction = river['direction']
    stop_or_limit = 1
    lc_range = 0
    tp_range = 0  # 0.06,  # 利確レンジ（ポジションの取得有無は無関係）
    console_comment = "default"
    # 実判定
    if river['count'] == 2:
        if turn_flop3_ratio <= tf1:  # ◆微戻りパターン(<40)。順方向に伸びる、一番狙いの形状の為、順張りしたい。
            if river_turn_ratio <= tr1_1:  # ◇0-60 マージン有、順張りのリバー同方向にオーダー。一番いい形
                position_margin = 0.02  # 出来るだけマージンは取りたいが、大きいとポジション出来なくなる。
                expected_direction = river['direction']
                stop_or_limit = 1
                tp_range = 0.06
                lc_range = 0.06  # ターンの半分くらいが理想？
                tr_range = 0.05
                take_position_flag = True
                console_comment = "    成立　tf:0-40, rt:0-60　M有順張りリバー"
            elif river_turn_ratio <= tr1_2:  # ◇60-90 順張りのリバー同方向にオーダー。ただしMargin余裕があれば。
                if river_turn_gap >= 0.03:  # Margin余裕の確認。少ないと、厳しいと思われるため。
                    position_margin = 0.01
                    expected_direction = river['direction']
                    stop_or_limit = 1
                    tp_range = 0.05  #
                    lc_range = 0.05  #
                    tr_range = 0.05
                    take_position_flag = True
                    console_comment = "    成立　tf:0-40, rt:60-90　M微有順張りリバー"
                else:
                    console_comment = "    不成立　tf:0-40, rt:60-90, margin無し " + str(river_turn_gap)
            elif river_turn_ratio <= tr1_3:  # ◇90-110 待機
                console_comment = "    不成立 待機　tf:0-40, rt:90-110 " + str(river_turn_gap)
            elif river_turn_ratio <= tr1_4:  # ◇110-130 即順張りのリバー同方向にオーダー。ジグザグトレンドと推定
                position_margin = 0.004  # 極小
                expected_direction = river['direction']
                stop_or_limit = 1
                tp_range = 0.05  #
                lc_range = 0.05  #
                tr_range = 0.05
                take_position_flag = True
                console_comment = "    成立　tf:0-40, rt:60-90 即順張リバー"
            else:  # 130以上 待機　（伸びすぎていて、失速の可能性もあるため）
                console_comment = "    不成立　リバー大きすぎ　待機　tf:0-40, rt:130- "
        elif turn_flop3_ratio <= tf2:  # ◆待機パターン(<70)。戻が半端なため。
            console_comment = "    不成立　ターン中途半端　tf:40-70, rt:ー"
        elif turn_flop3_ratio <= tf3:  # ◆深戻りパターン(<100)。旗形状やジグザグトレンド(リバー同方向)と推定。
            if river_turn_ratio <= tr3_1:  # ◇0-30 即順張りのリバー同方向にオーダー。旗形状(大きく上がらないが)か、ジグザグトレンド。
                position_margin = 0.004  # 極小
                expected_direction = river['direction']
                stop_or_limit = 1
                tp_range = f.cal_at_least(0.03, river_turn_gap * 1)  # 大きくてもターン開始ポイントが目安(旗の場合はそこがMAX）。
                lc_range = f.cal_at_least(0.03, river_turn_gap * 1)  # TPにそろえる
                tr_range = 0.05
                take_position_flag = True
                console_comment = "    成立　tf:70-100, rt:0-30 即順張リバー"
            elif river_turn_ratio <= 100:  # ◇30-100 逆張りのリバー逆方向にオーダー（ターゲットはターン開始位置）ジグザグトレンドと推定
                position_margin = margin_for_flag   # 予め計算しておいたターン起点の少し手前までのマージン
                expected_direction = river['direction'] * -1  # リバーと逆
                stop_or_limit = -1
                tp_range = turn['gap'] * 0.7  # ターンの価格終わり(ちょっと手前)を目標(ターンの７掛け目安）
                lc_range = turn['gap'] * 0.7  # TPにそろえる
                tr_range = 0.05
                take_position_flag = True
                console_comment = "    成立　tf:70-100, rt:30-100 逆張リバー逆(ターン開始点)　TP注意"
            else:  # ◇100-
                console_comment = "    不成立　リバー大きすぎ　tf:70-100, rt:100-"
        elif turn_flop3_ratio <= tf4:  # ◆戻り大パターン(<150)。ジグザグトレンド(リバー逆方向)の入口と推定。
            if river_turn_ratio <= tr4_1:  # ◇0-70 逆張りのリバー逆方向にオーダー（ターン起点の少し手前）。ジグザグトレンド（リバー逆）と推定
                position_margin = margin_for_flag  # 予め計算しておいたターン起点の少し手前までのマージン
                expected_direction = river['direction'] * -1  # リバーと逆
                stop_or_limit = -1
                tp_range = 0.05
                lc_range = 0.05
                tr_range = 0.05
                take_position_flag = True
                console_comment = "    成立　tf:100-150, rt:0-70 逆張リバー逆(ターン開始点手前)　TP注意"
            elif river_turn_ratio <= tr4_2:  # ◇70-100 即逆張りのリバー逆方向にオーダー・ジグザグトレンド（リバー逆）と推定
                position_margin = 0.008
                expected_direction = river['direction'] * -1  # リバーと逆
                stop_or_limit = -1
                tp_range = 0.05
                lc_range = 0.05
                tr_range = 0.05
                take_position_flag = True
                console_comment = "    成立　tf:100-150, rt:70-100 即逆張リバー逆　TP注意"
            else:
                console_comment = "    不成立　リバー大きすぎ　tf:100-150, rt:100-"
        else:  # ◆待機パターン。戻りが強すぎるため。
            console_comment = "    不成立　リバー大きすぎ　tf:0-100, rt:100-"
    else:
        console_comment = "    PASS rivercount:" + str(river['count'])

    print(console_comment)
    print("   情報 tf:", turn_flop3_ratio, "%(", turn_flop3_gap, ")", "rt:", river_turn_ratio, "%(", river_turn_gap, ")",
                    "f_gap:", flop3['gap'], "t_gap:", turn['gap'], "r_gap:", river['gap'])

    # 集計
    target_price = df_r_part.iloc[0]['open'] + (position_margin * expected_direction * stop_or_limit)
    if take_position_flag:  # 表示用（ポジションある時のみ表示する）
        print("   決心価格", df_r_part.iloc[0]['open'], "決心時間", df_r_part.iloc[0]['time_jp'])
        print("   注文価格", target_price, "向とSL", expected_direction, stop_or_limit)
    order_base_information = {
        # ポジション検証に必要な要素
        "take_position_flag": take_position_flag,  # ポジション取得指示あり
        "decision_time": df_r_part.iloc[0]['time_jp'],  # 直近の時刻（ポジションの取得有無は無関係）
        "decision_price": df_r_part.iloc[0]['open'],  # ポジションフラグ成立時の価格（先頭[0]列のOpen価格）
        "position_margin": position_margin,  # position_margin (+値は猶予大）
        "stop_or_limit": stop_or_limit,
        "target_price": target_price,  # 直接使うこともあるが、マージンを数種類で実行する場合、渡し先で再計算する場合もあり。
        "lc_range": lc_range, # 0.04,  # ロスカットレンジ（ポジションの取得有無は無関係）
        "tp_range": tp_range, #0.06,  # 利確レンジ（ポジションの取得有無は無関係）
        "expected_direction": expected_direction,
        # 以下参考項目
        "console_comment": console_comment
    }

    # オーダーの生成 (将来別の関数へ）　
    orders = []
    # 一旦結果を変数に入れておく　（将来別の関数にするため、めんどくさい書き方になっている・）
    decision_price = order_base_information['decision_price']
    position_margin = order_base_information['position_margin']
    expected_direction = order_base_information['expected_direction']
    tp_range = order_base_information['tp_range']
    lc_range = order_base_information['lc_range']
    stop_or_limit = order_base_information['stop_or_limit']
    target_price = order_base_information['target_price']
    console_comment = order_base_information['console_comment']
    if stop_or_limit == 1:
        type = "STOP"
    else:
        type = "LIMIT"
    # 1を作成（マージン小、利確小）
    orders.append(
        {
            "name": console_comment,
            "order_permission": True,
            "target_price": target_price,
            "tp_range": tp_range,
            "lc_range": lc_range,
            "units": 10,
            "direction": expected_direction,
            "type": type,  # 1が順張り、-1が逆張り
            "trade_timeout": 1800,
            "remark": "test",
            "tr_range": 0.05,
            "lc_change": {"lc_change_exe": True, "lc_trigger_range": 0.3, "lc_ensure_range": 0.1},
            # 説明用
            "console_comment": console_comment
        }
    )

    return {
        "take_position_flag": take_position_flag,
        "orders": orders
    }


