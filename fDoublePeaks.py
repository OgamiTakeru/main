import fBlockInspection as t  # とりあえずの関数集
import tokens as tk  # Token等、各自環境の設定ファイル（git対象外）
import classOanda as oanda_class
import fPeakLineInspection as p  # とりあえずの関数集
import fGeneric as f
import statistics
import pandas as pd

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


# def judge_list_or_data_frame(*args):
#     """
#     各解析関数から呼ばれる。各解析関数は、データフレームかリスト（ピークのリスト）が渡される。(１つだけの引数）
#     理由は、データフレームからピークを計算する処理を少なくしたいが、関数を分割したいため、どっちも受け取れた方が便利なため。
#     データフレームを渡された場合、ピークスを算出してピークスを返却する。
#     リスト（ピークのリスト）を渡された場合、そのままピークスを返却する。この際ピークの個数もチェックできるといいかもしれないが。
#     :param args: DateFrame（逆順）か、ピークスのリストが渡される
#     :return: {"result":}ピークスのリスト(peaks_collect_mainの返り値の['all_peaks'])を返却する
#     """
#     if type(args[0]) == pd.core.frame.DataFrame:
#         print("       -検証モード（データフレームからピークスを算出)")
#         peaks_info = p.peaks_collect_main(args[0][:90], 10)  # Peaksの算出（ループ時間短縮の為、必要最低限のピーク数（＝４）を指定する）
#         peaks = peaks_info['all_peaks']
#         print("  <対象>")
#         print("  RIVER", peaks[0])
#         print("  TURN ", peaks[1])
#         print("  FLOP3", peaks[2])
#         print("　　　価格整合性調査:", args[0].iloc[0]['open'], args[0].iloc[1]['close'], peaks[0]['peak'])
#     else:
#         # 運用モードでは、元々ピークスが渡されているので、そのまま返却する
#         peaks = args[0]
#
#     return peaks
#


def judge_list_or_data_frame(*args):
    """
    各解析関数から呼ばれる。各解析関数が検証から呼ばれているか、本番から呼ばれているかを判定する
    [0]=df_r データフレーム

    第二引数存在し、かつそれがpeaks辞書の配列ではない場合、パラメータモードとする
    :param args: 以下３種類
        データフレームのみ→検証
        データフレーム＋Paramsの辞書(辞書配列ではない）　→検証（ループ）
        データフレーム＋Peaksの配列　→本番　（時短の為、ピークの再計算を行いたくない）
    :return: {"peaks":peaks, "param_mode":boolean(paramがある時のみ)}
    """
    print(" モード検証")
    # print(len(args))
    # print(args)
    # print(args[1])
    if len(args) == 2:
        # ２つある場合は、より深い判定が必要
        if isinstance(args[1], list):  # "time" in args[1][0]:
            # 配列が渡されているとき、それはピークスである。そして実践モード
            param_mode = False
            inspection_mode = False
        else:
            # 配列の先頭の辞書にTimeを含まない場合、それはParamである。そして検証モード
            param_mode = True
            inspection_mode = True
    else:
        # １つの場合は、パラむモードではない。そして検証モード
        param_mode = False
        inspection_mode = True

    if inspection_mode:
        print("       -検証モード（データフレームからピークスを算出)")
        peaks_info = p.peaks_collect_main(args[0][:90], 10)  # Peaksの算出（ループ時間短縮の為、必要最低限のピーク数（＝４）を指定する）
        peaks = peaks_info['all_peaks']
        print("  <対象>")
        print("  RIVER", peaks[0])
        print("  TURN ", peaks[1])
        print("  FLOP3", peaks[2])
        print("　　　価格整合性調査:", args[0].iloc[0]['open'], args[0].iloc[1]['close'], peaks[0]['peak'])
    else:
        # 運用モードでは、元々ピークスが渡されているので、そのまま返却する
        print("      -運用モード")
        peaks = args[1]

    return {"param_mode": param_mode, "peaks": peaks, "df_r": args[0]}


def judge_list_or_data_frame_4peaks(*args):
    """
    各解析関数から呼ばれる。各解析関数が検証から呼ばれているか、本番から呼ばれているかを判定する
    args配列の０番目は必ずdf_r（データフレーム）
    第二引数存在し、かつそれがpeaks辞書の配列ではない場合、パラメータモードとする
    :param args: 以下３種類
        データフレームのみ→検証
        データフレーム＋Paramsの辞書(辞書配列ではない）　→検証（ループ）
        データフレーム＋Peaksの配列　→本番　（時短の為、ピークの再計算を行いたくない）
    :return: {"peaks":peaks, "param_mode":boolean(paramがある時のみ), "df_r": データフレーム}
    """
    print(" モード検証")
    # print(len(args))
    # print(args)
    # print(args[1])
    if len(args) == 2:
        # ２つある場合は、より深い判定が必要
        if isinstance(args[1], list):  # "time" in args[1][0]:
            # 配列が渡されているとき、それはピークスである。そして実践モード
            param_mode = False
            inspection_mode = False
        else:
            # 配列の先頭の辞書にTimeを含まない場合、それはParamである。そして検証モード
            param_mode = True
            inspection_mode = True
    else:
        # １つの場合は、パラむモードではない。そして検証モード
        param_mode = False
        inspection_mode = True

    if inspection_mode:
        print("       -検証モード（データフレームからピークスを算出)")
        peaks_info = p.peaks_collect_main(args[0][:90], 10)  # Peaksの算出（ループ時間短縮の為、必要最低限のピーク数（＝４）を指定する）
        peaks = peaks_info['all_peaks']
        print("  <対象>")
        print("  LATEST", peaks[0])
        print("  RIVER", peaks[1])
        print("  TURN ", peaks[2])
        print("  FLOP3", peaks[3])
        print("　　　価格整合性調査:", args[0].iloc[0]['open'], args[0].iloc[1]['close'], peaks[0]['peak'])
    else:
        # 運用モードでは、元々ピークスが渡されているので、そのまま返却する
        print("      -運用モード")
        peaks = args[1]

    return {"param_mode": param_mode, "peaks": peaks, "df_r": args[0]}


def DoublePeakBreak_formed_in_past(df_r):
    """
    通常のDublePeakBreakを検証するさい、５分ごとに連続して成立する可能性あり。（運用だと繰り返しのオーダーが入る）
    df_rを１つ削った状態で同条件で成立を判断。
    １つ前の足まででも成立する場合、Trueを返却する。
    :param df_r:
    :return:
    """
    peaks_info = p.peaks_collect_main(df_r[:90], 10)  # Peaksの算出（ループ時間短縮の為、必要最低限のピーク数（＝４）を指定する）
    peaks = peaks_info['all_peaks']
    river = peaks[0]  # 最新のピーク（リバーと呼ぶ。このCount＝２の場合、折り返し直後）
    turn = peaks[1]  # 注目するポイント（ターンと呼ぶ）
    flop3 = peaks[2]  # レンジ判定用（プリフロップと呼ぶ）
    # (2)情報を変数に取得する
    # ⓪リバーのターンに対する割合を取得（〇%に小さくなっている事を想定）
    size_ans = size_compare(river["gap"], turn["gap"], 0.1, 0.3)
    river_turn_gap = round(size_ans['gap'], 3)
    river_turn_ratio = size_ans['size_compare_ratio']
    # ①ターンのフロップ３に対する割合を取得（〇%に小さくなっていることを想定）
    size_ans = size_compare(turn["gap"], flop3["gap"], 0.1, 0.3)
    turn_flop3_ratio = size_ans['size_compare_ratio']
    # (3)条件
    tf_max = 0.8  # 0.6
    rt_min = 1.1  #
    rt_max = 2.0  #
    position_margin = 0.02  #
    tp = 0.03
    lc = turn['peak']
    t_count = 2  # ターンは長すぎる(count)と、戻しが強すぎるため、この値以下にしておきたい。
    t_gap = 0.12  # ターンは長すぎる(gap)と、戻しが強すぎるため、この値以下にしておきたい。出来れば８くらい・・？
    stop_or_limit = 1  # マージンの方向(+値は期待方向に対して取得猶予を取る場合(順張り),－値は期待と逆の場合は逆張り）
    d = 1  # 売買の方向。リバーの方向に対し、同方向の場合１．逆方向の場合ー１
    # （４）判定
    take_position_flag = False  # ポジションフラグを初期値でFalseにする
    # リバー数で最初の判定（ネストを深くしないため、外に出した）
    if 4 <= flop3['count']:
        if turn_flop3_ratio < tf_max and 0.012 < turn['gap'] and t_count <= turn['count']:  # ターンの情報
            if rt_min < river_turn_ratio < rt_max:  # リバーについて（リバー比）
                take_position_flag = True
                print("   ■■ダブルピークBreak判定")
            else:
                print("   不成立(リバー関係)")
        else:
            print("   不成立(ターン関係)", turn['gap'], turn['count'])
    else:
        print("   　不成立（フロップカウント）")

    return take_position_flag  # 成立してる場合はTrue


def DoublePeakBreak(*args):
    """
    １）引数について。　引数は全３パターン。
    ①データフレームだけが来る。これはAnalysisから呼び出され、データフレームからピークスを算出後に、本関数メインの判定処理を実施。
    ②データフレームと条件配列(param)の２つが来る。これはAnalysisMultiから呼ばれている。基本は①と同様だが、条件ごとにループ検証を行う。
    ③ピークス(peaks_collect_mainの返り値内の,["all_peaks"])とデータフレームが。Total実行の関数から呼び出され、本関数メインの判定処理を実施。
    なお①②において、
    データフレーム：ローソク情報(逆順[直近が上の方にある＝時間降順])データフレーム
    条件(param) ：ループ検証時のパラメータ群(ループ検証の時のみ入ってくる）
    例→params_arr = [
        {"river_turn_ratio_min": 1, "river_turn_ratio": 1.3, "turn_flop_ratio": 0.6, "count": 2}
        {"river_turn_ratio_min": 1, "river_turn_ratio": 1.3, "turn_flop_ratio": 0.6, "count": 2}
    ]
    ③においてピークスは、peaks_collect_mainの返り値内の,["all_peaks"]が対象。
    ＜まとめ＞いかなる場合もargs[0]はデータフレームまたはPeaksとなり、[1]以降がオプションとなる。

    ＜ロジック＞ダブルトップの頂点を超えた場合、伸びる方向に進んでいくポジションをとる。

　　　　　　　　　  ターン↓　 /　←このでっぱり部が、5pips以内（リーバーがターンの1.1倍以内？）
       　　　　  　   /\  /
       フロップ　30→ /  \/  ← 6(リバー) ＋　割合だけでなく、5pipくらいトップピークまで余裕があれば。
          　　　　　/　　　←ターンのPeak値がLCPriceにする？
        ・リバーの個数に制限は設けない。その場合、１か所で数回発生する場合がある。
        　（

    :param df_r:
    :return:　必須最低限　{"take_position_flag": boolean} の返却は必須。さらにTrueの場合注文情報が必要。
    """
    # print(args)
    print("  ■ダブルピークBreak判定")
    # (1)ピークスを取得（引数か処理）。この関数ではPeaksの情報を元にし、Dfは使わない。
    # ①必要最低限の項目たちを取得する
    mode_judge = judge_list_or_data_frame(*args)  # ピークスを確保。モードを問わない共通処理。args[0]はデータフレームまたはPeaksList。
    peaks = mode_judge['peaks']
    river = peaks[0]  # 最新のピーク（リバーと呼ぶ。このCount＝２の場合、折り返し直後）
    turn = peaks[1]  # 注目するポイント（ターンと呼ぶ）
    flop3 = peaks[2]  # レンジ判定用（プリフロップと呼ぶ）
    param_mode = mode_judge['param_mode']
    df_r = mode_judge['df_r']
    formed_in_past = DoublePeakBreak_formed_in_past(df_r[1:])  # 【特殊】ひとつ前の足でも試す
    # (2)情報を変数に取得する
    # ⓪リバーのターンに対する割合を取得（〇%に小さくなっている事を想定）
    size_ans = size_compare(river["gap"], turn["gap"], 0.1, 0.3)
    river_turn_gap = round(size_ans['gap'], 3)
    river_turn_ratio = size_ans['size_compare_ratio']
    # ①ターンのフロップ３に対する割合を取得（〇%に小さくなっていることを想定）
    size_ans = size_compare(turn["gap"], flop3["gap"], 0.1, 0.3)
    turn_flop3_ratio = size_ans['size_compare_ratio']
    # ②記録用の情報を組み立てる（検証のアウトプット用）この情報は、成立有無関係なく生成可能。
    records = {
        "river_turn_ratio": river_turn_ratio,
        "turn_flop3_ratio": turn_flop3_ratio,
        "peak_river": river['count'],
        "river_turn_gap": river_turn_gap,
        "tp_base": turn['gap'] - river['gap'],
        "formed_in_past": formed_in_past
    }

    # (3)パラメータ指定。常実行時は数字の直接指定。paramsがある場合（ループ検証）の場合は、パラメーターを引数から取得する(args[1]=params)
    # ①　パラメータを設定する
    tf_max = args[1]['tf_ratio_max'] if param_mode else 0.6  # 0.6
    rt_min = args[1]['rt_ratio_min'] if param_mode else 1.0  #
    rt_max = args[1]['rt_ratio_max'] if param_mode else 2.0  #
    position_margin = args[1]['margin'] if param_mode else 0.005#
    tp = river['gap']
    lc = river['gap']
    t_count = 2  # ターンは長すぎる(count)と、戻しが強すぎるため、この値以下にしておきたい。
    t_gap = 0.13  # ターンは長すぎる(gap)と、戻しが強すぎるため、この値以下にしておきたい。出来れば８くらい・・？
    stop_or_limit = args[1]['sl'] if param_mode else 1  # マージンの方向(+値は期待方向に対して取得猶予を取る場合(順張り),－値は期待と逆の場合は逆張り）
    d = args[1]['d'] if param_mode else 1  # 売買の方向。リバーの方向に対し、同方向の場合１．逆方向の場合ー１
    # ②オーダーのベースを組み立てる（オーダ発行の元にするため、返却が必要な値。target_price等の算出）
    order_base = f.order_finalize(
        {"stop_or_limit": stop_or_limit,
         "expected_direction": river['direction'] * d,
         "decision_time": river['time'],
         "decision_price": river['peak'],  # フラグ成立時の価格（先頭[0]列のOpen価格）
         "target": flop3['peak'],  # 価格かマージンかを入れることが出来る
         "lc": lc,
         "tp": tp,}
    )

    # (3)★★判定部
    take_position_flag = False  # ポジションフラグを初期値でFalseにする
    # リバー数で最初の判定（ネストを深くしないため、外に出した）
    if 3 <= flop3['count']:  # 7にしたい
        if turn_flop3_ratio < tf_max and 0.011 < turn['gap'] and t_count <= turn['count']:  # ターンの情報
            if rt_min < river_turn_ratio < rt_max:  # リバーについて（リバー比）
                take_position_flag = True
                print("   ■■ダブルピークBreak判定")
            else:
                print("   不成立(リバー関係)")
        else:
            print("   不成立(ターン関係)", turn['gap'], turn['count'])
    else:
        print("   　不成立（フロップカウント）", flop3['count'])

    print("   情報 tf:", turn_flop3_ratio, "%(<", tf_max, "),rt:(", rt_min, "<)", river_turn_ratio, "%(<", rt_max, "),",
          "rt_gap:", abs(river_turn_gap), "(<", 0, "), t_gap", turn['gap'], "(<", t_gap, "),", flop3['gap'])

    # (3) ★★判定部2(過去数個のピークの中で、フロップのピークが頂点かどうか(フロップが傾きマイナスなら最低値、逆なら最高値か）
    # Breakの場合だと、逆に最ピークじゃない方が抜けやすい？
    peak_of_peak = peak_of_peak_judgement(peaks[3:10], flop3, df_r)
    # ダブルトップの成立判定
    if not peak_of_peak:
        # flop3が頂点だった場合、戻る予想なのでBreakには向いていない。
        if take_position_flag:
            take_position_flag = False
            print("    ■TakePositionFlagを解除（最ピークでないため）")

    # (4)★★判定部３　ひとつ前の足でも同様の場合、ポジションしない
    if formed_in_past:
        print("    ■前回(1足分前)も同形状")
        take_position_flag = False
    else:
        print("     過去判定同一なし")

    # (5) ■■オーダーのベースを生成する（検証で利用するのはこのオブジェクト）
    # ①オーダー無し時は除外
    if not take_position_flag:  # ポジションフラグがFalseの場合は、返却をして終了
        return {  # フラグ無しの場合、オーダー以外を返却。
            "take_position_flag": take_position_flag,
            "order_base": order_base,  # 検証で利用する。
            "records": records  # 記録軍。CSV保存時に出力して解析ができるように。
        }

    # (6) ■実オーダーを組み立てる（成立時のみ生成）
    print("   決心価格", order_base['decision_price'], "決心時間", order_base['decision_time'])
    print("   注文価格", order_base['target_price'], "向とSL", order_base['expected_direction'], stop_or_limit)
    exe_orders = [
        f.order_finalize({  # オーダー２を作成
            "name": "DoublePeakBreak(Riv順）",
            "order_permission": True,
            "decision_price": river['peak'],  # ★
            "target": river['peak'] + (position_margin * river['direction']),  # 価格でする
            "decision_time": 0,  #
            "tp": 0.10,
            "lc": 0.03,
            "units": 10,
            "expected_direction": river['direction'],
            "stop_or_limit": 1,  # ★順張り
            "trade_timeout": 1800,
            "remark": "test",
            "tr_range": 0.05,
            "lc_change": {"lc_change_exe": True, "lc_trigger_range": 0.03, "lc_ensure_range": 0.01}
        })
    ]

    return {  # take_position_flagの返却は必須。Trueの場合注文情報が必要。
        "take_position_flag": take_position_flag,
        "order_base": order_base,  # 検証で利用する。
        "exe_orders": exe_orders,  # 発行するオーダー。このままオーダーを発行できる状態
        "records": records  # 記録軍。CSV保存時に出力して解析ができるように。
    }


def DoublePeak(*args):
    """
    ★ピークスは１０個必要
    １）引数について。　引数は全３パターン。
    ①データフレームだけが来る。これはAnalysisから呼び出され、データフレームからピークスを算出後に、本関数メインの判定処理を実施。
    ②データフレームと条件配列(param)の２つが来る。これはAnalysisMultiから呼ばれている。基本は①と同様だが、条件ごとにループ検証を行う。
    ③ピークス(peaks_collect_mainの返り値内の,["all_peaks"])とデータフレームが。Total実行の関数から呼び出され、本関数メインの判定処理を実施。
    なお①②において、
    データフレーム：ローソク情報(逆順[直近が上の方にある＝時間降順])データフレーム
    条件(param) ：ループ検証時のパラメータ群(ループ検証の時のみ入ってくる）
    例→params_arr = [
        {"river_turn_ratio_min": 1, "river_turn_ratio": 1.3, "turn_flop_ratio": 0.6, "count": 2}
        {"river_turn_ratio_min": 1, "river_turn_ratio": 1.3, "turn_flop_ratio": 0.6, "count": 2}
    ]
    ③においてピークスは、peaks_collect_mainの返り値内の,["all_peaks"]が対象。
    ＜まとめ＞いかなる場合もargs[0]はデータフレームまたはPeaksとなり、[1]以降がオプションとなる。
    ２）ロジックについて
    ＜ロジック概要＞ダブルトップを頂点とし、そこから戻る方向にポジションする。
                     ↓ 10pips（基準：ターン）
       　　23pips　   /\  /
           フロップ→ /  \/  ← 7pipsまで(リバー)
          　　　　　/　　　　　　　　　←ピークの反対くらいがLC？
    　　トラップライン
    　　・ターンのピークオールド起点でリバーの逆方向（逆張り）
    　　・ターンのピーク起点でリバーの逆方向（順張り）
       ルール一覧
       ・ターンが小さい、または、少ない場合、ダブルトップポイントを瞬間的に突破する回数が多い為NGとしたい。、
       　その為、ターンは３足分以上かつ、2pips以上とする。
       ・出来ればフロップは長い方がいい気がする。フロップカウントは７以上
       　（さらにフロップの頂点が新規ポイントの場合は率上がるかも？）
       ・フロップのピーク点か、直近の10ピークの中で最も頂点の場合は、折り返し濃厚。最も頂点でない場合は、Breakまで行く可能性高い。
       　（別途関数を準備）
    :return:　必須最低限　{"take_position_flag": boolean} の返却は必須。さらにTrueの場合注文情報が必要。
    """
    # print(args)
    print("  ■ダブルピーク判定")
    # (1)ピークスを取得（引数か処理）。この関数ではPeaksの情報を元にし、Dfは使わない。
    # ①必要最低限の項目たちを取得する
    mode_judge = judge_list_or_data_frame(*args)  # ピークスを確保。モードを問わない共通処理。args[0]はデータフレームまたはPeaksList。
    peaks = mode_judge['peaks']
    river = peaks[0]  # 最新のピーク（リバーと呼ぶ。このCount＝２の場合、折り返し直後）
    turn = peaks[1]  # 注目するポイント（ターンと呼ぶ）
    flop3 = peaks[2]  # レンジ判定用（プリフロップと呼ぶ）
    param_mode = mode_judge['param_mode']
    df_r = mode_judge['df_r']
    # (2)情報を変数に取得する
    # ⓪リバーのターンに対する割合を取得（〇%に小さくなっている事を想定）
    size_ans = size_compare(river["gap"], turn["gap"], 0.1, 0.3)
    river_turn_gap = round(size_ans['gap'], 3)
    river_turn_ratio = size_ans['size_compare_ratio']
    # ①ターンのフロップ３に対する割合を取得（〇%に小さくなっていることを想定）
    size_ans = size_compare(turn["gap"], flop3["gap"], 0.1, 0.3)
    turn_flop3_ratio = size_ans['size_compare_ratio']
    # ②記録用の情報を組み立てる（検証のアウトプット用）この情報は、成立有無関係なく生成可能。
    records = {
        "river_turn_ratio": river_turn_ratio,
        "turn_flop3_ratio": turn_flop3_ratio,
        "peak_river": river['count'],
        "river_turn_gap": river_turn_gap,
        "tp_base": turn['gap'] - river['gap'],
    }

    # (3)パラメータ指定。常実行時は数字の直接指定。paramsがある場合（ループ検証）の場合は、パラメーターを引数から取得する(args[1]=params)
    # ①　パラメータを設定する
    if param_mode:  # turn['peak']はダブルトップBreakしない(river逆)
        if args[1]["p"] == "turn":
            target = turn['peak'] + (args[1]['margin'] * river['direction'] * -1)  # 抵抗側
        else:
            target = flop3['peak'] + (args[1]['margin'] * river['direction'])  # 突破側
    else:
        target = turn['peak'] + (0.005 * river['direction'] * -1)
    tf_max = args[1]['tf_ratio_max'] if param_mode else 0.65  # ターンは、フロップの６割値度
    rt_min = args[1]['rt_ratio_min'] if param_mode else 0.4  #  リバーは、ターンの最低４割程度
    rt_max = args[1]['rt_ratio_max'] if param_mode else 1.0  #　リバーは、ターンの最高でも６割程度
    position_margin = args[1]['margin'] if param_mode else 0.02  #
    tp = f.cal_at_least(0.06, (abs(turn['peak'] - river['peak_old']) * 1))  # 5pipsとなると結構大きい。Minでも3pips欲しい
    lc = f.cal_at_least(0.05, (abs(turn['peak'] - river['peak_old']) * 0.8))
    t_count = 2  # ターンは長すぎる(count)と、戻しが強すぎるため、この値以下にしておきたい。
    t_gap = 0.12  # ターンは長すぎる(gap)と、戻しが強すぎるため、この値以下にしておきたい。出来れば８くらい・・？
    stop_or_limit = args[1]['sl'] if param_mode else 1  # マージンの方向(+値は期待方向に対して取得猶予を取る場合(順張り),－値は期待と逆の場合は逆張り）
    d = args[1]['d'] if param_mode else -1  # 売買の方向。リバーの方向に対し、同方向の場合１．逆方向の場合ー１
    # ②オーダーのベースを組み立てる（オーダ発行の元にするため、返却が必要な値。target_price等の算出）
    order_base = f.order_finalize({"stop_or_limit": stop_or_limit,
                                 "expected_direction": river['direction'] * d,
                                 "decision_time": river['time'],
                                 "decision_price": river['peak'],  # フラグ成立時の価格（先頭[0]列のOpen価格）
                                 "target": target,  # turn['peak'] + (0.01 * river['direction']),  # 価格かマージンかを入れることが出来る
                                 "lc": lc,
                                 "tp": tp,  # tp,
                                 })

    # (3)★★判定部
    take_position_flag = False  # ポジションフラグを初期値でFalseにする
    # ①形状の判定
    # 1 必ず省く条件の場合(全体的なサイズ感が小さいことによる除外）
    if 4 <= flop3['count']:
        if turn_flop3_ratio < tf_max and 0.011 <= turn['gap'] and t_count <= turn['count']:  # ターンの情報
            if rt_min < river_turn_ratio < rt_max:  # リバーについて（リバー比）
                take_position_flag = True
                print("   ■■ダブルトップ完成")
            else:
                print("   不成立(リバー関係)")
        else:
            print("   不成立(ターン関係)", turn['gap'], turn['count'])
    else:
        print("   　不成立（フロップカウント）")

    print("   情報 tf:", turn_flop3_ratio, "%(<", tf_max, "),rt:(", rt_min, "<)", river_turn_ratio, "%(<", rt_max, "),",
          "rt_gap:", abs(river_turn_gap), "(<", 0, "), t_gap", turn['gap'], "(<", t_gap, "),", flop3['gap'])

    # ②判定部2(過去数個のピークの中で、フロップのピークが頂点かどうか(フロップが傾きマイナスなら最低値、逆なら最高値か）
    peak_of_peak = peak_of_peak_judgement(peaks[3:10], flop3, df_r)

    # ③ダブルトップの成立判定
    if not peak_of_peak:
        # flop3が頂点ではなかった場合、信用できないダブルトップ。
        if take_position_flag:
            take_position_flag = False
            print("    ■TakePositionFlagを解除（最ピークでないため）")

    # (4) ★★オーダーのベースを生成する（検証で利用するのはこのオブジェクト）
    # ①オーダー無し時は除外
    if not take_position_flag:  # ポジションフラグがFalseの場合は、返却をして終了
        return {  # フラグ無しの場合、オーダー以外を返却。
            "take_position_flag": take_position_flag,
            "order_base": order_base,  # 検証で利用する。
            "records": records  # 記録軍。CSV保存時に出力して解析ができるように。
        }

    # ②★★実オーダーを組み立てる（成立時のみ生成）
    print("   決心価格", order_base['decision_price'], "決心時間", order_base['decision_time'])
    print("   注文価格", order_base['target_price'], "向とSL", order_base['expected_direction'], stop_or_limit)
    exe_orders = [
        f.order_finalize({  # オーダー２を作成
            "name": "DoublePeak(ダブル抵抗）",
            "order_permission": True,
            "decision_price": river['peak'],  # ★
            "target": turn['peak'] + (0.01 * river['direction'] * -1),  # 価格でする
            "decision_time": 0,  #
            "tp": 0.10,
            "lc": 0.03,
            "units": 10,
            "expected_direction": river['direction'] * -1,
            "stop_or_limit": 1,  # ★順張り
            "trade_timeout": 1800,
            "remark": "test",
            "tr_range": 0.05,
            "lc_change": {"lc_change_exe": True, "lc_trigger_range": 0.03, "lc_ensure_range": 0.01}
        }),
        f.order_finalize({
            "name": "DoublePeak(ダブル突破）",
            "order_permission": True,
            "decision_price": river['peak'],  # ★
            "target": flop3['peak'] + (0.01 * river['direction']),  # 価格でする
            "decision_time": 0,  #
            "tp": 0.10,
            "lc": 0.03,
            "units": 10,
            "expected_direction": river['direction'],
            "stop_or_limit": 1,  # ★
            "trade_timeout": 1800,
            "remark": "test",
            "tr_range": 0.05,
            "lc_change": {"lc_change_exe": True, "lc_trigger_range": 0.01, "lc_ensure_range": -0.02}
        })
    ]

    return {  # take_position_flagの返却は必須。Trueの場合注文情報が必要。
        "take_position_flag": take_position_flag,
        "order_base": order_base,  # 検証で利用する。
        "exe_orders": exe_orders,  # 発行するオーダー。このままオーダーを発行できる状態
        "records": records  # 記録軍。CSV保存時に出力して解析ができるように。
    }


def DoublePeak_4peaks(*args):
    """
    ★ピークスは１０個必要
    １）引数について。　引数は全３パターン。
    ①データフレームだけが来る。これはAnalysisから呼び出され、データフレームからピークスを算出後に、本関数メインの判定処理を実施。
    ②データフレームと条件配列(param)の２つが来る。これはAnalysisMultiから呼ばれている。基本は①と同様だが、条件ごとにループ検証を行う。
    ③ピークス(peaks_collect_mainの返り値内の,["all_peaks"])とデータフレームが。Total実行の関数から呼び出され、本関数メインの判定処理を実施。
    なお①②において、
    データフレーム：ローソク情報(逆順[直近が上の方にある＝時間降順])データフレーム
    条件(param) ：ループ検証時のパラメータ群(ループ検証の時のみ入ってくる）
    例→params_arr = [
        {"river_turn_ratio_min": 1, "river_turn_ratio": 1.3, "turn_flop_ratio": 0.6, "count": 2}
        {"river_turn_ratio_min": 1, "river_turn_ratio": 1.3, "turn_flop_ratio": 0.6, "count": 2}
    ]
    ③においてピークスは、peaks_collect_mainの返り値内の,["all_peaks"]が対象。
    ＜まとめ＞いかなる場合もargs[0]はデータフレームまたはPeaksとなり、[1]以降がオプションとなる。
    ２）ロジックについて
    ＜ロジック概要＞ダブルトップを頂点とし、そこから戻る方向にポジションする。
                      ↓ ターン
       　　     　   /\  /\ ←レイテスト
        　フロップ3→ /  \/ ←リバー
         　 　　　　/　　　　　　　　　←ピークの反対くらいがLC？
    　　レイテストのCountが２に限定する（リバーが確定するタイミング）

    :return:　必須最低限　{"take_position_flag": boolean} の返却は必須。さらにTrueの場合注文情報が必要。
    """
    # print(args)
    print("  ■ダブルトップ(4ピーク)")
    # (1)ピークスを取得（引数か処理）。この関数ではPeaksの情報を元にし、Dfは使わない。
    # ①必要最低限の項目たちを取得する
    mode_judge = judge_list_or_data_frame_4peaks(*args)  # ピークスを確保。モードを問わない共通処理。args[0]はデータフレームまたはPeaksList。
    param_mode = mode_judge['param_mode']
    df_r = mode_judge['df_r']
    peaks = mode_judge['peaks']
    latest = peaks[0]  # 最新のピーク（リバーと呼ぶ。このCount＝２の場合、折り返し直後）
    river = peaks[1]  # ピーク（リバーと呼ぶ）
    turn = peaks[2]  # 注目するポイント（ターンと呼ぶ）
    flop3 = peaks[3]  # レンジ判定用（プリフロップと呼ぶ）

    # (2)情報を変数に取得する
    # ⓪リバーのターンに対する割合を取得（〇%に小さくなっている事を想定）
    size_ans = size_compare(river["gap"], turn["gap"], 0.1, 0.3)
    river_turn_gap = round(size_ans['gap'], 3)
    river_turn_ratio = size_ans['size_compare_ratio']
    # ①ターンのフロップ３に対する割合を取得（〇%に小さくなっていることを想定）
    size_ans = size_compare(turn["gap"], flop3["gap"], 0.1, 0.3)
    turn_flop3_ratio = size_ans['size_compare_ratio']
    # ②記録用の情報を組み立てる（検証のアウトプット用）この情報は、成立有無関係なく生成可能。
    records = {
        "river_turn_ratio": river_turn_ratio,
        "turn_flop3_ratio": turn_flop3_ratio,
        "peak_river": river['count'],
        "river_turn_gap": river_turn_gap,
        "tp_base": turn['gap'] - river['gap'],
    }

    # (3)パラメータ指定。常実行時は数字の直接指定。paramsがある場合（ループ検証）の場合は、パラメーターを引数から取得する(args[1]=params)
    # ①　パラメータを設定する
    if param_mode: # turn['peak']はダブルトップBreakしない(river逆)
        if args[1]["p"] == "turn":
            target = turn['peak'] + (args[1]['margin'] * river['direction'] * -1)  # 抵抗側
        else:
            target = flop3['peak'] + (args[1]['margin'] * river['direction'])  # 突破側
    else:
        target = turn['peak'] + (0.01 * river['direction'] * -1)
    tf_max = args[1]['tf_ratio_max'] if param_mode else 0.8  # 0.6
    rt_min = args[1]['rt_ratio_min'] if param_mode else 0.7  #
    rt_max = args[1]['rt_ratio_max'] if param_mode else 1.0  #
    position_margin = args[1]['margin'] if param_mode else 0.02
    tp = f.cal_at_least(0.06, (abs(turn['peak'] - river['peak_old']) * 1))  # 5pipsとなると結構大きい。Minでも3pips欲しい
    lc = f.cal_at_least(0.05, (abs(turn['peak'] - river['peak_old']) * 0.8))
    t_count = 2  # ターンは長すぎる(count)と、戻しが強すぎるため、この値以下にしておきたい。
    t_gap = 0.12  # ターンは長すぎる(gap)と、戻しが強すぎるため、この値以下にしておきたい。出来れば８くらい・・？
    stop_or_limit = args[1]['sl'] if param_mode else 1  # マージンの方向(+値は期待方向に対して取得猶予を取る場合(順張り),－値は期待と逆の場合は逆張り）
    d = args[1]['d'] if param_mode else -1  # 売買の方向。リバーの方向に対し、同方向の場合１．逆方向の場合ー１
    # ②オーダーのベースを組み立てる（オーダ発行の元にするため、返却が必要な値。target_price等の算出）
    order_base = f.order_finalize({"stop_or_limit": stop_or_limit,
                                 "expected_direction": river['direction'] * d,
                                 "decision_time": river['time'],
                                 "decision_price": river['peak'],  # フラグ成立時の価格（先頭[0]列のOpen価格）
                                 "target": target,  # turn['peak'] + (0.00 * river['direction']),  # 価格かマージンかを入れることが出来る
                                 "lc": lc,
                                 "tp": tp,  # tp,
                                 })

    # (3)★★判定部
    take_position_flag = False  # ポジションフラグを初期値でFalseにする
    # ①形状の判定
    if latest['count'] == 2:
        # この時点でターンは発生（latest=2)
        if 4 <= flop3['count']:
            if turn_flop3_ratio < tf_max and 0.012 < turn['gap'] and t_count <= turn['count']:  # ターンの情報
                if rt_min < river_turn_ratio < rt_max:  # リバーについて（リバー比）
                    take_position_flag = True
                    print("   ■■ダブルトップ完成")
                    print("    Peak-latest", river['peak'], "-", flop3['peak'])
                else:
                    print("   不成立(リバー関係) &　ターン発生")
            else:
                print("   不成立(ターン関係)　 &　ターン発生", turn['gap'], turn['count'])
        else:
            print("   　不成立（フロップカウント）　 &　ターン発生")
    else:
        print("    不成立（リバーカウント")

    print("   情報 tf:", turn_flop3_ratio, "%(<", tf_max, "),rt:(", rt_min, "<)", river_turn_ratio, "%(<", rt_max, "),",
          "rt_gap:", abs(river_turn_gap), "(<", 0, "), t_gap", turn['gap'], "(<", t_gap, "),", flop3['gap'])

    # ②判定部2(過去数個のピークの中で、フロップのピークが頂点かどうか(フロップが傾きマイナスなら最低値、逆なら最高値か）
    peak_of_peak = peak_of_peak_judgement(peaks[3:10], flop3, df_r)

    # ③ダブルトップの成立判定
    if not peak_of_peak:
        # flop3が頂点ではなかった場合、信用できないダブルトップ。
        if take_position_flag:
            take_position_flag = False
            print("    ■TakePositionFlagを解除（最ピークでないため）")

    # (4) ★★オーダーのベースを生成する（検証で利用するのはこのオブジェクト）
    # ①オーダー無し時は除外
    if not take_position_flag:  # ポジションフラグがFalseの場合は、返却をして終了
        return {  # フラグ無しの場合、オーダー以外を返却。
            "take_position_flag": take_position_flag,
            "order_base": order_base,  # 検証で利用する。
            "records": records  # 記録軍。CSV保存時に出力して解析ができるように。
        }

    # ②★★実オーダーを組み立てる（成立時のみ生成）
    print("   決心価格", order_base['decision_price'], "決心時間", order_base['decision_time'])
    print("   注文価格", order_base['target_price'], "向とSL", order_base['expected_direction'], stop_or_limit)
    exe_orders = [
        f.order_finalize({  # オーダー２を作成
            "name": "DoublePeak４(ダブルピーク抵抗）",
            "order_permission": True,
            "decision_price": river['peak'],  # ★
            "target": turn['peak'] + (0.01 * river['direction'] * -1),  # 価格でする
            "decision_time": 0,  #
            "tp": 0.10,
            "lc": 0.03,
            "units": 10,
            "expected_direction": river['direction'] * -1,
            "stop_or_limit": 1,  # ★順張り
            "trade_timeout": 1800,
            "remark": "test",
            "tr_range": 0.05,
            "lc_change": {"lc_change_exe": True, "lc_trigger_range": 0.02, "lc_ensure_range": 0.01}
        }),
        f.order_finalize({
            "name": "DoublePeak４(ダブルピーク突破）",
            "order_permission": True,
            "decision_price": river['peak'],  # ★
            "target": flop3['peak'] + (0.01 * river['direction']),  # 価格でする
            "decision_time": 0,  #
            "tp": 0.10,
            "lc": 0.03,
            "units": 10,
            "expected_direction": river['direction'],
            "stop_or_limit": 1,  # ★
            "trade_timeout": 1800,
            "remark": "test",
            "tr_range": 0.05,
            "lc_change": {"lc_change_exe": True, "lc_trigger_range": 0.02, "lc_ensure_range": 0.01}
        })
    ]

    return {  # take_position_flagの返却は必須。Trueの場合注文情報が必要。
        "take_position_flag": take_position_flag,
        "order_base": order_base,  # 検証で利用する。
        "exe_orders": exe_orders,  # 発行するオーダー。このままオーダーを発行できる状態
        "records": records  # 記録軍。CSV保存時に出力して解析ができるように。
    }


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
            position_margin = margin_for_flag  # 予め計算しておいたターン起点の少し手前までのマージン
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
        "lc_range": lc_range,  # 0.04,  # ロスカットレンジ（ポジションの取得有無は無関係）
        "tp_range": tp_range,  # 0.06,  # 利確レンジ（ポジションの取得有無は無関係）
        "expected_direction": expected_direction,
        # 以下参考項目
        "console_comment": console_comment
    }

    # オーダーの生成 (将来別の関数へ）　
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
    exe_orders = [
        {
            "name": console_comment,
            "order_permission": True,
            "target_price": order_base_information['decision_price'] + (
                        0.03 * (order_base_information['expected_direction']) * order_base_information[
                    'stop_or_limit']),
            "tp_range": tp_range,
            "lc_range": lc_range,
            "units": 10,
            "direction": expected_direction,
            "type": type,  # 1が順張り、-1が逆張り
            "trade_timeout": 1800,
            "remark": "test",
            "tr_range": 0.05,
            "lc_change": {"lc_change_exe": True, "lc_trigger_range": 0.3, "lc_ensure_range": 0.1},
        },
        {
            "name": console_comment,
            "order_permission": True,
            "target_price": order_base_information['decision_price'] + (
                        0.03 * (order_base_information['expected_direction'] * -1) * order_base_information[
                    'stop_or_limit']),
            "tp_range": tp_range,
            "lc_range": lc_range,
            "units": 10,
            "direction": expected_direction * -1,
            "type": type,  # 1が順張り、-1が逆張り
            "trade_timeout": 1800,
            "remark": "test",
            "tr_range": 0.05,
            "lc_change": {"lc_change_exe": True, "lc_trigger_range": 0.3, "lc_ensure_range": 0.1},
        },
    ]

    return {
        "take_position_flag": take_position_flag,
        "exe_orders": exe_orders,
    }


def triplePeaks_pattern(*args):
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

    # 必要なピークを出す (どれをRiverにするかを判断する）
    # 一番直近のピークをlatestとするが、
    # ①latestをriverとして扱う場合 (未確定のriverを扱う）。ただしlatestのCount＝２でないと毎回実施になってしまう)
    # ②形が確定したriverを扱う場合　でスイッチできるようにする
    latest_is_river = False
    if latest_is_river:
        # ①形の決まっていないlatestをriverとして扱う場合
        latest = peaks[0]
        river = peaks[0]  # 最新のピーク（リバーと呼ぶ。このCount＝２の場合、折り返し直後）
        turn = peaks[1]  # 注目するポイント（ターンと呼ぶ）
        flop3 = peaks[2]  # レンジ判定用（プリフロップと呼ぶ）
    else:
        #　②形が確定したriverを扱う場合
        latest = peaks[0]  #
        river = peaks[1]  # 最新のピーク（リバーと呼ぶ。このCount＝２の場合、折り返し直後）
        turn = peaks[2]  # 注目するポイント（ターンと呼ぶ）
        flop3 = peaks[3]  # レンジ判定用（プリフロップと呼ぶ）
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

    # (3)判定処理  （マージン、ポジション方向、タイプ、TP、LCを取得する）
    # ①リバーはターン直後のみを採用。
    if latest['count'] != 2:
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
            p_type = "t微戻り→r微戻り"
        elif river_turn_ratio <= tr1_2:  # ◇60-90 順張りのリバー同方向にオーダー。ただしMargin余裕があれば。
            #     /\/ ↑　←この形（リバーのが殆ど上まで戻っている状態）
            #    /  　
            #   /
            p_type = "t微戻り→rダブルトップ"
        elif river_turn_ratio <= tr1_3:  # ◇90-110 待機
            #        /　↑↓？　　 ←ダブルトップを超えた直後を想定
            #     /\/
            #    /  　
            p_type = "t微戻り→r戻り微オーバー"
        elif river_turn_ratio <= tr1_4:  # ◇110-130 即順張りのリバー同方向にオーダー。ジグザグトレンドと推定
            #         / ↑　　　　←結構、ダブルトップを超えた直後を想定
            #        /
            #     /\/
            #    /  　
            p_type = "t微戻り→r戻り強オーバー"
        else:  # 130以上 待機　（伸びすぎていて、失速の可能性もあるため）
            #         / ←これが大きすぎる場合
            #        /
            #     /\/
            #    /
            p_type = "t微戻り→r戻り超強オーバー"
    elif turn_flop3_ratio <= tf2:  # ◆待機パターン(<70)。戻が半端なため。
        #     /\ ←この形（リバーのが殆ど上まで戻っている状態）
        #    /  \　
        #   /
        p_type = "t中途半端戻り"
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
            p_type = "tやや深戻り→r微戻り"
        elif river_turn_ratio <= tr3_2:  # ◇30-100 逆張りのリバー逆方向にオーダー（ターゲットはターン開始位置）ジグザグトレンドと推定
            #     /\
            #    /  \  /  ↑
            #   /    \/
            #  /
            p_type = "tやや深戻り→rダブルトップ以下"
        else:  # ◇100-
            #            /
            #     /\    /
            #    /  \  /  ↑
            #   /    \/
            #  /
            p_type = "tやや深戻り→r戻りオーバー"
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
            p_type = "t強戻り→r戻り"
        elif river_turn_ratio <= tr4_2:  # ◇90-150 即順リバー同方向。リバー強く、ジグザグするにせよ、リバー方向に行くと推定。
            #              /
            #     /\      /
            #    /  \    /　　　　　
            #   /    \  /
            #         \/
            p_type = "t強戻り→r強戻り"
        else:
            p_type = "t強戻り→r強すぎる戻り"
    else:  # ◆待機パターン。戻りが強すぎるため。
        p_type = "t強戻りすぎる"
    print(p_type)
    print("   情報 tf:", turn_flop3_ratio, "(", turn_flop3_gap, ")", "rt:", river_turn_ratio, "(", river_turn_gap, ")",
          "f_gap:", flop3['gap'], "t_gap:", turn['gap'], "r_gap:", river['gap'])


    return {
        "take_position_flag": False,
        "exe_orders":0,
    }
