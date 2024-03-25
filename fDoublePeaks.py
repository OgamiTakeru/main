import fTurnInspection as t  # とりあえずの関数集
import tokens as tk  # Token等、各自環境の設定ファイル（git対象外）
import classOanda as oanda_class
import fPeakLineInspection as p  # とりあえずの関数集
import fGeneric as f
import statistics
import pandas as pd

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

    return {
        # 順番通りの大小比較結果
        "size_compare_ratio": change_ratio,
        "size_compare_ratio_r": change_ratio_r,
        "gap": amount_of_change,
        "gap_abs": amount_of_change_abs,
        # サイズが同等かの判定
        "same_size": same_size,  # 同等の場合のみTrue
    }


def judge_list_or_data_frame(*args):
    """
    各解析関数から呼ばれる。各解析関数は、データフレームかリスト（ピークのリスト）が渡される。(１つだけの引数）
    理由は、データフレームからピークを計算する処理を少なくしたいが、関数を分割したいため、どっちも受け取れた方が便利なため。
    データフレームを渡された場合、ピークスを算出してピークスを返却する。
    リスト（ピークのリスト）を渡された場合、そのままピークスを返却する。この際ピークの個数もチェックできるといいかもしれないが。
    :param args: DateFrame（逆順）か、ピークスのリストが渡される
    :return: {"result":}ピークスのリスト(peaks_collect_mainの返り値の['all_peaks'])を返却する
    """
    if type(args[0]) == pd.core.frame.DataFrame:
        print("       -検証モード（データフレームからピークスを算出)")
        peaks_info = p.peaks_collect_main(args[:90], 3)  # Peaksの算出（ループ時間短縮の為、必要最低限のピーク数（＝４）を指定する）
        peaks = peaks_info['all_peaks']
        print("  <対象>")
        print("  RIVER", peaks[0])
        print("  TURN ", peaks[1])
        print("  FLOP3", peaks[2])
        print("　　　価格整合性調査:", args[0].iloc[0]['open'], args[0].iloc[1]['close'], peaks[0]['peak'])
    else:
        # 運用モードでは、元々ピークスが渡されているので、そのまま返却する
        peaks = args[0]

    return peaks


def beforeDoublePeak(*args):
    """
    １）引数のパターンは３パターン。
    ①データフレームだけが来る。これはAnalysisから呼び出され、データフレームからピークスを算出後に、本関数メインの判定処理を実施。
    ②データフレームと条件(param)の２つが来る。これはAnalysisMultiから呼ばれている。基本は①と同様だが、条件ごとにループ検証を行う。
    ③ピークス(peaks_collect_mainの返り値内の,["all_peaks"])だけが来る。Total実行の関数から呼び出され、本関数メインの判定処理を実施。
    なお①②において、
    データフレーム：ローソク情報(逆順[直近が上の方にある＝時間降順])データフレーム
    条件(param) ：ループ検証時のパラメータ群(ループ検証の時のみ入ってくる）
    例→params_arr = [
        {"river_turn_ratio_min": 1, "river_turn_ratio": 1.3, "turn_flop_ratio": 0.6, "count": 2}
        {"river_turn_ratio_min": 1, "river_turn_ratio": 1.3, "turn_flop_ratio": 0.6, "count": 2}
    ]
    ③においてピークスは、peaks_collect_mainの返り値内の,["all_peaks"]が対象。
    ＜まとめ＞いかなる場合もargs[0]はデータフレームまたはPeaksとなり、[1]以降がオプションとなる。

　　　　　　　　　
       　　23pips　   /\← 10pips（基準：ターン）
           フロップ→ /  \/  ← 7pipsまで(リバー)
          　　　　　/　　　　　　　　　←ピークの反対くらいがLC？
       ルール一覧
       ・ターンはフロップの４割まで以内の戻り。出来れば５pips以内？（ターンが大きいと、完全な折り返しになる為。）
       ・リバーはターンの８割まで以内の戻り。出来ればターン起点（ダブルトップ成立ポイント）まで3pips欲しい
       ・利確、理想はターン起点。ただリバーが大きい時は小さすぎるので、その時は3pipsとする。
       ・ロスカは、リバーの倍？あるいはターンの半分の長さまで（価格指定）とか。
    :return:　必須最低限　{"take_position_flag": boolean} の返却は必須。さらにTrueの場合注文情報が必要。
    """
    # print(args)
    print("■直前ダブルピーク判定")
    # (1)ピークスを取得（引数か処理）、パラメータの設定（引数か直接の設定）
    # ①必要最低限の項目たちを取得する
    peaks = judge_list_or_data_frame(args[0])  # ピークスを確保。モードを問わない共通処理。args[0]はデータフレームまたはPeaksList。
    river = peaks[0]  # 最新のピーク（リバーと呼ぶ。このCount＝２の場合、折り返し直後）
    turn = peaks[1]  # 注目するポイント（ターンと呼ぶ）
    flop3 = peaks[2]  # レンジ判定用（プリフロップと呼ぶ）
    # ②paramsがある場合（ループ検証）の場合は、パラメーターを引数から取得する(args[1]。それ以外は、直接の設定
    if len(args) == 2:  # 引数が存在する場合
        params = args[1]  # 引数の条件辞書を取得
        f_gap = 0.1
        tf_max = params['tf_ratio']
        rt_max = params['rt_ratio']
        r_count = params['count']
        rt_gap_min = params['rt_gap']
        position_margin = params['margin']
        t_count = params['tc']
        t_gap = params['tg']
        tp = f.cal_at_least(0.04, (turn['gap'] - river['gap']) * params['tp'])
        lc = f.cal_at_least(0.04, (turn['gap'] - river['gap']) * params['lc'])
        stop_or_limit = params['sl']
    else:
        # 基本的なパラメータ（呼び出し元から引数の指定でない場合、こちらを採用する）
        f_gap = 0.05  # フロップがは出来るだけ大きいほうが良い（強い方向を感じるため）
        tf_max = 0.4  # 0.6
        rt_max = 0.7  # 0.6
        r_count = 2  # 2
        rt_gap_min = 0  # 0.03
        position_margin = 0.008  # 0.01
        tp = f.cal_at_least(0.04, (turn['gap'] - river['gap']) * 1)  # 5pipsとなると結構大きい。Minでも3pips欲しい
        lc = f.cal_at_least(0.04, (turn['gap'] - river['gap'] * 1))
        t_count = 7  # ターンは長すぎる(count)と、戻しが強すぎるため、この値以下にしておきたい。
        t_gap = 0.12  # ターンは長すぎる(gap)と、戻しが強すぎるため、この値以下にしておきたい。出来れば８くらい・・？
        stop_or_limit = 1  # マージンの方向(+値は期待方向に対して取得猶予を取る場合(順張り),－値は期待と逆の場合は逆張り）
    # (1)-②　情報を変数に取得する
    col = "gap"  # 偏差値を使う場合はstdev　gapを使うことも可能
    # ⓪リバーのターンに対する割合を取得（〇%に小さくなっている事を想定）
    size_ans = size_compare(river[col], turn[col], 0.1, 0.3)
    river_turn_gap = round(size_ans['gap'], 3)
    river_turn_ratio = size_ans['size_compare_ratio']
    # ①ターンのフロップ３に対する割合を取得（〇%に小さくなっていることを想定）
    size_ans = size_compare(turn[col], flop3[col], 0.1, 0.3)
    turn_flop3_ratio = size_ans['size_compare_ratio']

    # (3)★★判定部
    take_position_flag = False  # ポジションフラグを初期値でFalseにする
    # リバー数で最初の判定（ネストを深くしないため、外に出した）
    if river['count'] != r_count:
        print("   不成立　リバー数", river['count'])
        return {"take_position_flag": False}
    # その他条件で判定
    if turn_flop3_ratio < tf_max and flop3['gap'] >= f_gap:  # フロップとターンの関係、フロップのサイズで分岐
        if river_turn_ratio < rt_max and abs(river_turn_gap) >= rt_gap_min:  # ターンとリバーの関係、リバーの情報で分岐
            if turn['gap'] <= t_gap and turn['count'] <= t_count:  # ターンサイズで判定(大きいターンなNG）
                take_position_flag = True
                print("   ■■Beforeダブルトップ完成")
            else:
                print("   不成立(サイズ)")
        else:
            print("   不成立(ターンリバー関係)")
            if type(args[0]) == pd.core.frame.DataFrame:
                # 条件指定有の場合は送付しない（おおむね、テストなのでLINE送信しない。したらヤバイ）
                tk.line_send(" リバー注目", river_turn_ratio, river['time'])
    else:
        print("   不成立(フロップターン関係)")

    print("   情報 tf:", turn_flop3_ratio, "%(<", tf_max, "),rt:", river_turn_ratio, "%(<", rt_max, "),",
                    "rt_gap:", abs(river_turn_gap), "(<", 0, "), t_gap", turn['gap'], "(<", t_gap,"),", flop3['gap'])

    # (3) ★★オーダーのベースを生成する（検証で利用するのはこのオブジェクト）
    # ①オーダー無し時は除外
    if not take_position_flag:  # ポジションフラグがFalseの場合は、返却をして終了
        return {"take_position_flag": False}
    # ②オーダー発生時は、情報を整える
    expected_direction = river['direction']  # 以後のコード短縮化の為、変数化
    target_price = river['peak'] + (position_margin * expected_direction * stop_or_limit)  # 以後のコード短縮化の為、変数化
    print("   ★決心価格", river['peak'], "決心時間", river['time'])
    print("   　注文価格", target_price, "向とSL", expected_direction, stop_or_limit)
    # ③オーダーのベースを組み立てる（オーダ発行の元。また、検証ではこの値で検証を行う）
    order_base = {
        "stop_or_limit": stop_or_limit,  # 運用で必須
        "expected_direction": expected_direction,  # 必須
        "decision_time": river['time'],  # 任意
        "decision_price": river['peak'],  # 検証で任意　運用で必須(複数Marginで再計算する可能性あり)
        "position_margin": position_margin,  # 検証で任意　運用で必須(複数Marginで再計算する可能性あり)
        "target_price": target_price,  # 検証で必須　運用で任意(複数Marginで再計算する可能性あり)
        "lc_range": lc,  # 検証で必須　運用で任意
        "tp_range": tp,  # 検証で必須　運用で任意
        "tp_price": target_price + (tp * expected_direction),  # 任意
        "lc_price": target_price - (lc * expected_direction),  # 任意
    }
    # ④利用したパラメータ情報を組み立てる（検証のアウトプット用）
    params = {
        "p_margin_min": position_margin,
        "p_turn_flop3_ratio_max": tf_max,
        "p_river_turn_ratio_max": rt_max,
        "p_river_turn_gap_max": abs(river_turn_gap),
        "p_turn_gap_max": t_gap,
        "p_flop_gap_max": f_gap,
        "p_tp": tp,
        "p_lc": lc,
    }
    # ⑤記録用の情報を組み立てる（検証のアウトプット用）
    records = {
        "river_turn_ratio": river_turn_ratio,
        "turn_flop3_ratio": turn_flop3_ratio,
        "peak_river": river['count'],
        "river_turn_gap": river_turn_gap,
        "tp_base": turn['gap'] - river['gap'],
    }

    # (4) ★★実オーダーを組み立てる
    exe_orders = [
        {  # オーダー１を作成
            "name": "MarginS-TPS",
            "order_permission": True,
            "target_price": order_base['decision_price'] + (0.008 * order_base['expected_direction'] * order_base['stop_or_limit']),
            "tp_range": order_base['tp_range'] * 0.8,
            "lc_range": order_base['lc_range'],
            "units": 10,
            "direction": order_base['expected_direction'],
            "type": "STOP" if order_base['stop_or_limit'] == 1 else "LIMIT",
            "trade_timeout": 1800,
            "remark": "test",
            "tr_range": 0,
            "lc_change": {"lc_change_exe": True, "lc_trigger_range": 0.3, "lc_ensure_range": 0.1}
        },
        {  # オーダー２を作成
            "name": "Margin_B-TP_B",
            "order_permission": True,
            "target_price": order_base['decision_price'] + (0.03 * order_base['expected_direction'] * order_base['stop_or_limit']),
            "tp_range": order_base['tp_range'] * 3,
            "lc_range": order_base['lc_range'],
            "units": 20,
            "direction": order_base['expected_direction'],
            "type": "STOP" if order_base['stop_or_limit'] == 1 else "LIMIT",   # 1が順張り、-1が逆張り
            "trade_timeout": 1800,
            "remark": "test",
            "tr_range": 0.05,
            "lc_change": {"lc_change_exe": True, "lc_trigger_range": 0.3, "lc_ensure_range": 0.1}
        }
    ]

    return {  # take_position_flagの返却は必須。Trueの場合注文情報が必要。
        "take_position_flag": take_position_flag,
        "order_base": order_base,  # 検証で利用する。
        "exe_orders": exe_orders,  # 発行するオーダー。このままオーダーを発行できる状態
        "params": params,  # パラメータ群。CSV保存時に出力して解析ができるように
        "records": records  # 記録軍。CSV保存時に出力して解析ができるように。
    }


def beforeDoublePeakBreak(*args):
    """
    引数は配列で受け取る。今は最大二つを想定。
    引数１つ目：ローソク情報(逆順[直近が上の方にある＝時間降順])データフレームを受け取り、範囲の中で、ダブルトップ直前ついて捉える
    引数２つ目はループ検証時のパラメータ群(ループ検証の時のみ入ってくる）
    ②パターン２

　　　　　　　　　  ターン↓　 /　←このでっぱり部が、5pips以内（リーバーがターンの1.1倍以内？）
       　　　　  　   /\  /
       フロップ　30→ /  \/  ← 6(リバー) ＋　割合だけでなく、5pipくらいトップピークまで余裕があれば。
          　　　　　/　　　　　　　　　←ピークの反対くらいがLC？

    :param df_r:
    :return:　必須最低限　{"take_position_flag": boolean} の返却は必須。さらにTrueの場合注文情報が必要。
    """
    # print(args)
    print("■ダブルピークBreak判定")
    # (1)ピークスを取得（引数か処理）、パラメータの設定（引数か直接の設定）
    # ①必要最低限の項目たちを取得する
    peaks = judge_list_or_data_frame(args[0])  # ピークスを確保。モードを問わない共通処理。args[0]はデータフレームまたはPeaksList。
    river = peaks[0]  # 最新のピーク（リバーと呼ぶ。このCount＝２の場合、折り返し直後）
    turn = peaks[1]  # 注目するポイント（ターンと呼ぶ）
    flop3 = peaks[2]  # レンジ判定用（プリフロップと呼ぶ）
    # ②paramsがある場合（ループ検証）の場合は、パラメーターを引数から取得する(args[1]。それ以外は、直接の設定
    if len(args) == 2:  # 引数が存在する場合
        params = args[1]  # 引数の条件辞書を取得
        tf_max = params['tf_ratio_max']
        rt_min = params['rt_ratio_min']
        rt_max = params['rt_ratio_max']
        rt_gap_min = params['gap_min']
        rt_gap_max = params['gap']
        r_count = params['count']
        position_margin = params['margin']
        lc = f.cal_at_least(0.04, river['gap']* 1)  # abs(peak_turn['gap']-peak_river['gap'])
        tp = f.cal_at_least(0.04, river['gap']* 1)  # abs(peak_turn['gap']-peak_river['gap'])
        stop_or_limit = params['sl']
        d = params['d']
    else:
        tf_max = 0.4  # あんまり戻りすぎていると、順方向に行く体力がなくなる？？だから少なめにしたい
        rt_min = 0.95
        rt_max = 1.8  # 余りリバーが強いと、力が枯渇している可能性。
        rt_gap_min = 0.00
        rt_gap_max = 0.22  # リバーがターンより長い量が、どの程度まで許容か(大きいほうがいい可能性も？）
        r_count = 2
        position_margin = 0.02
        lc = f.cal_at_least(0.04, river['gap']* 1)
        tp = f.cal_at_least(0.04, river['gap']* 1)
        stop_or_limit = 1
        d = 1

    # (1)-②　情報を変数に取得する
    col = "gap"  # 偏差値を使う場合はstdev　gapを使うことも可能
    # ⓪リバーのターンに対する割合を取得（〇%に小さくなっている事を想定）
    size_ans = size_compare(river[col], turn[col], 0.1, 0.3)
    river_turn_gap = round(size_ans['gap'], 3)
    river_turn_ratio = size_ans['size_compare_ratio']
    # ①ターンのフロップ３に対する割合を取得（〇%に小さくなっていることを想定）
    size_ans = size_compare(turn[col], flop3[col], 0.1, 0.3)
    turn_flop3_ratio = size_ans['size_compare_ratio']

    # (2)★★判定部
    take_position_flag = False
    # リバー数で最初の判定（ネストを深くしないため、外に出した）
    if river['count'] != r_count:
        print("   不成立　リバー数", river['count'])
        return {"take_position_flag": False}
    # その他条件で判定
    if turn_flop3_ratio < tf_max and flop3['gap'] >= 0.05:  # フロップ３とターンの関係、フロップ３のサイズ（GAP)について
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

    print("   情報 tf:", turn_flop3_ratio, "%(<", tf_max, "),rt:(", rt_min, "<)", river_turn_ratio, "%(<", rt_max, "),",
                    "f_gap:", flop3['gap'], "(>", 0.05, "), rt_gap凸:(",
                    rt_min, "<)", river_turn_gap, "(<", rt_max, ")")

    # (3) ★★オーダーのベースを生成する（検証で利用するのはこのオブジェクト）
    # ①オーダー無し時は除外
    if not take_position_flag:  # ポジションフラグがFalseの場合は、返却をして終了
        return {"take_position_flag": False}
    # ②オーダー発生時は、情報を整える
    expected_direction = river['direction']  # 以後のコード短縮化の為、変数化
    target_price = river['peak'] + (position_margin * expected_direction * stop_or_limit)  # 以後のコード短縮化の為、変数化
    print("   決心価格", river['peak'], "決心時間", river['time'])
    print("   注文価格", target_price, "向とSL", expected_direction, stop_or_limit)
    # ③オーダーのベースを組み立てる
    order_base = {
        "stop_or_limit": stop_or_limit,  # 運用で必須
        "expected_direction": expected_direction,  # 必須
        "decision_time": river['time'],  # 任意
        "decision_price": river['peak'],  # 検証で任意　運用で必須(複数Marginで再計算する可能性あり)
        "position_margin": position_margin,  # 検証で任意　運用で必須(複数Marginで再計算する可能性あり)
        "target_price": target_price,  # 検証で必須　運用で任意(複数Marginで再計算する可能性あり)
        "lc_range": lc,  # 検証で必須　運用で任意
        "tp_range": tp,  # 検証で必須　運用で任意
        "tp_price": target_price + (tp * expected_direction),  # 任意
        "lc_price": target_price - (lc * expected_direction),  # 任意
    }
    # ④利用したパラメータ情報を組み立てる
    params = {
        "p_margin_min": position_margin,
        "p_turn_flop3_ratio_max": tf_max,
        "p_river_turn_ratio_max": rt_max,
        "p_river_turn_gap_max": abs(river_turn_gap),
        "p_tp": tp,
        "p_lc": lc,
    }
    # ⑤記録用の情報を組み立てる
    records = {
        "river_turn_ratio": river_turn_ratio,
        "turn_flop3_ratio": turn_flop3_ratio,
        "peak_river": river['count'],
        "river_turn_gap": river_turn_gap,
        "tp_base": turn['gap'] - river['gap'],
    }

    # (4)★★オーダーを組み立てる
    exe_orders = [
        {
            "name": "Break_forward",
            "order_permission": True,
            "target_price": order_base['decision_price'] + (0.015 * order_base['expected_direction'] * order_base['stop_or_limit']),
            "tp_range": order_base['tp_range'] * 1,
            "lc_range": order_base['lc_range'],
            "units": 15,
            "direction": order_base['expected_direction'],
            "type": "STOP" if order_base['stop_or_limit'] == 1 else "LIMIT",   # 1が順張り、-1が逆張り,  # 1が順張り、-1が逆張り
            "trade_timeout": 1800,
            "remark": "target:",
            "tr_range": 0.05,
            "lc_change": {"lc_change_exe": True, "lc_trigger_range": 0.3, "lc_ensure_range": 0.1}
        },
    # 2を作成(レンジの方向。リバーとは逆の方向）
        {
            "name": "Break_reverse",
            "order_permission": True,
            "target_price": order_base['decision_price'] + (0.03 * (order_base['expected_direction'] * -1) * order_base['stop_or_limit']),
            "tp_range": order_base['tp_range'] * 1,
            "lc_range": order_base['lc_range'],
            "units": 25,
            "direction": (order_base['expected_direction'] * -1),
            "type": "STOP" if order_base['stop_or_limit'] == 1 else "LIMIT",   # 1が順張り、-1が逆張り,  # 1が順張り、-1が逆張り
            "trade_timeout": 1800,
            "remark": "test",
            "tr_range": 0.05,
            "lc_change": {"lc_change_exe": True, "lc_trigger_range": 0.3, "lc_ensure_range": 0.1}
        }
    ]

    return {  # take_position_flagの返却は必須。Trueの場合注文情報が必要。
        "take_position_flag": take_position_flag,
        "order_base": order_base,  # 検証で利用する。
        "exe_orders": exe_orders,  # 発行するオーダー。このままオーダーを発行できる状態
        "params": params,  # パラメータ群。CSV保存時に出力して解析ができるように
        "records": records  # 記録軍。CSV保存時に出力して解析ができるように。
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
    # （０）データを取得する
    peaks_info = p.peaks_collect_main(df_r[:90], 3)  # Peaksの算出（ループ時間短縮の為、必要最低限のピーク数（＝４）を指定する）
    peaks = peaks_info['all_peaks']
    river = peaks[0]  # 最新のピーク（リバーと呼ぶ。このCount＝２の場合、折り返し直後）
    turn = peaks[1]  # 注目するポイント（ターンと呼ぶ）
    flop3 = peaks[2]  # レンジ判定用（プリフロップと呼ぶ）

    print("  <対象>:運用モード")
    print("  RIVER", river)
    print("  TURN ", turn)
    print("  FLOP3", flop3)
    peaks_times = "◇River:" + \
                  f.delYear(river['time']) + "-" + f.delYear(river['time_old']) + "(" + str(river['direction']) + ")" \
                  "◇Turn:" + \
                  f.delYear(turn['time']) + "-" + f.delYear(turn['time_old']) + "(" + str(turn['direction']) + ")" \
                  "◇FLOP三" + \
                  f.delYear(flop3['time']) + "-" + f.delYear(flop3['time_old']) + "(" + str(flop3['direction']) + ")"

    # （１）beforeDoublePeakについて
    # tf < 0.4
    beforeDoublePeak_ans = beforeDoublePeak(peaks)

    # (2)beforeDoublePeakBreakについて
    beforeDoublePeakBreak_ans = beforeDoublePeakBreak(peaks)

    # 【オーダーを統合する】  現状同時に成立しない仕様。
    if beforeDoublePeak_ans['take_position_flag']:
        order_information = beforeDoublePeak_ans['exe_orders']  # オーダー発行情報のみをへんきゃく
    elif beforeDoublePeakBreak_ans['take_position_flag']:
        order_information = beforeDoublePeakBreak_ans  # オーダー発行情報のみを返却する
    else:
        # 何もない場合はPositionFlagをFalseにして返す
        order_information = {"take_position_flag": False}

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
    tr3_2 = 1.0
    #
    tr4_1 = 0.9
    tr4_2 = 1.5
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
    # ①リバーはターン直後のみを採用。
    if river['count'] != 2:
        print("   River 2以外の為スキップ")
        return {"take_position_flag": False}
    # ②フロップターンと、リバーターンの関係で調査する(複雑注意)
    if turn_flop3_ratio <= tf1:  # ◆微戻りパターン(<40)。順方向に伸びる、一番狙いの形状の為、順張りしたい。
        # フロップ３とターンの関係
        #     /\　←微戻り
        #    /  　
        #   /
        if river_turn_ratio <= tr1_1:  # ◇0-60 マージン有、順張りのリバー同方向にオーダー。一番いい形
            #     /\/ ↑　　　←この形(もう少しリバーの戻りが弱い状態）
            #    /  　
            #   /
            position_margin = 0.02  # 出来るだけマージンは取りたいが、大きいとポジション出来なくなる。
            expected_direction = river['direction']
            stop_or_limit = 1
            tp_range = 0.06
            lc_range = 0.06  # ターンの半分くらいが理想？
            tr_range = 0.05
            take_position_flag = True
            console_comment = "1成立　tf:0-40, rt:0-60　M有順張りリバー　いつもの（理想）"
        elif river_turn_ratio <= tr1_2:  # ◇60-90 順張りのリバー同方向にオーダー。ただしMargin余裕があれば。
            #     /\/ ↑　←この形（リバーのが殆ど上まで戻っている状態）
            #    /  　
            #   /
            if river_turn_gap >= 0.03:  # Margin余裕の確認。少ないと、厳しいと思われるため。
                position_margin = 0.01
                expected_direction = river['direction']
                stop_or_limit = 1
                tp_range = 0.05  #
                lc_range = 0.05  #
                tr_range = 0.05
                take_position_flag = True
                console_comment = "2成立　tf:0-40, rt:60-90　M微有順張りリバー　いつもの（MARGIN小）"
            else:
                console_comment = "△1不成立　tf:0-40, rt:60-90, margin無し " + str(river_turn_gap)
        elif river_turn_ratio <= tr1_3:  # ◇90-110 待機
            #        /　↑↓？　　 ←ダブルトップを超えた直後を想定
            #     /\/
            #    /  　
            console_comment = "△2 不成立 待機　tf:0-40, rt:90-110 " + str(river_turn_gap)
        elif river_turn_ratio <= tr1_4:  # ◇110-130 即順張りのリバー同方向にオーダー。ジグザグトレンドと推定
            #         / ↑　　　　←結構、ダブルトップを超えた直後を想定
            #        /
            #     /\/
            #    /  　
            position_margin = 0.004  # 極小
            expected_direction = river['direction']
            stop_or_limit = 1
            tp_range = 0.05  #
            lc_range = 0.05  #
            tr_range = 0.05
            take_position_flag = True
            console_comment = "3成立　tf:0-40, rt:60-90 即順張リバー　ジグザグリバー方向"
        else:  # 130以上 待機　（伸びすぎていて、失速の可能性もあるため）
            #         / ←これが大きすぎる場合
            #        /
            #     /\/
            #    /
            console_comment = "△3 不成立　リバー大きすぎ　待機　tf:0-40, rt:130- "
    elif turn_flop3_ratio <= tf2:  # ◆待機パターン(<70)。戻が半端なため。
        #     /\ ←この形（リバーのが殆ど上まで戻っている状態）
        #    /  \　
        #   /
        console_comment = "△4 不成立　ターン中途半端　tf:40-70, rt:ー"
    elif turn_flop3_ratio <= tf3:  # ◆深戻りパターン(<100)。旗形状やジグザグトレンド(リバー同方向)と推定。
        #     /\ ←この形（リバーのが殆ど上まで戻っている状態）
        #    /  \　
        #   /    \
        #  /
        if river_turn_ratio <= tr3_1:  # ◇0-30 逆張りのリバー逆方向。旗形状(大きく上がらない)等のレンジ。ワンチャン、ジグトレ
            #     /\　　　↓
            #    /  \　
            #   /    \/
            #  /
            position_margin = 0.04  #
            expected_direction = river['direction'] * -1
            stop_or_limit = -1
            tp_range = f.cal_at_least(0.03, river_turn_gap * 1)  # 大きくてもターン開始ポイントが目安(旗の場合はそこがMAX）。
            lc_range = f.cal_at_least(0.03, river_turn_gap * 1)  # TPにそろえる
            tr_range = 0.05
            take_position_flag = True
            console_comment = "3成立　tf:70-100, rt:0-30 逆張りリバー逆。レンジ予想"
        elif river_turn_ratio <= tr3_2:  # ◇30-100 逆張りのリバー逆方向にオーダー（ターゲットはターン開始位置）ジグザグトレンドと推定
            #     /\    /
            #    /  \  /  ↑
            #   /    \/
            #  /
            position_margin = margin_for_flag   # 予め計算しておいたターン起点の少し手前までのマージン
            expected_direction = river['direction'] * -1  # リバーと逆
            stop_or_limit = -1
            tp_range = turn['gap'] * 0.7  # ターンの価格終わり(ちょっと手前)を目標(ターンの７掛け目安）
            lc_range = turn['gap'] * 0.7  # TPにそろえる
            tr_range = 0.05
            take_position_flag = True
            console_comment = "4成立　tf:70-100, rt:30-100 逆張リバー逆(ターン開始点)　ジグザグリバー逆　TP注意"
        else:  # ◇100-
            #            /
            #     /\    /
            #    /  \  /  ↑
            #   /    \/
            #  /
            console_comment = "△5 不成立　リバー大きすぎ　tf:70-100, rt:100-"
    elif turn_flop3_ratio <= tf4:  # ◆戻り大パターン(<150)。ジグザグトレンド(リバー逆方向)の入口と推定。
        #     /\
        #    /  \　
        #   /    \
        #         \ ←　ターンが長い
        if river_turn_ratio <= tr4_1:  # ◇0-90 逆張りのリバー逆方向にオーダー（ターン起点手前）。ジグザグトレンド（リバー逆）と推定
            #     /\
            #    /  \    /　↓　　　　
            #   /    \  /
            #         \/
            position_margin = margin_for_flag  # 予め計算しておいたターン起点の少し手前までのマージン
            expected_direction = river['direction'] * -1  # リバーと逆
            stop_or_limit = -1
            tp_range = 0.05
            lc_range = 0.05
            tr_range = 0.05
            take_position_flag = True
            console_comment = "5成立　tf:100-150, rt:0-90 逆張リバー逆(ターン開始点手前)　ジグザグリバー逆方向へ"
        elif river_turn_ratio <= tr4_2:  # ◇90-150 即順リバー同方向。リバー強く、ジグザグするにせよ、リバー方向に行くと推定。
            #              /
            #     /\      /
            #    /  \    /　　　　　
            #   /    \  /
            #         \/
            position_margin = 0.008
            expected_direction = river['direction'] * 1  # リバーと逆
            stop_or_limit = 1
            tp_range = 0.05
            lc_range = 0.05
            tr_range = 0.05
            take_position_flag = True
            console_comment = "6成立　tf:100-150, rt:90-150 即順リバー同方向 (ジグザグリバー方向) 少し下がってから？"
        else:
            console_comment = "    △6 不成立　リバー大きすぎ　tf:100-150, rt:100-"
    else:  # ◆待機パターン。戻りが強すぎるため。
        console_comment = "    △7 不成立　リバー大きすぎ　tf:0-100, rt:100-"

    print("    ", console_comment)
    print("   情報 tf:", turn_flop3_ratio, "(", turn_flop3_gap, ")", "rt:", river_turn_ratio, "(", river_turn_gap, ")",
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
            "console_comment": "★" + console_comment
        }
    )

    return {
        "take_position_flag": take_position_flag,
        "exe_orders": orders,
    }





