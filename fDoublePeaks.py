import fTurnInspection as t  # とりあえずの関数集
import tokens as tk  # Token等、各自環境の設定ファイル（git対象外）
import classOanda as oanda_class
import fPeakLineInspection as p  # とりあえずの関数集
import fGeneric as f
import statistics
import pandas as pd

oa = oanda_class.Oanda(tk.accountIDl, tk.access_tokenl, "live")  # クラスの定義


def order_finalize(order_base):
    """
    オーダーを完成させる。TPRangeとTpPrice、Marginとターゲットプライスのどちらかが入ってれば完成させたい。
    :param order_base:必須
    order_base = {
        "stop_or_limit": stop_or_limit,  # 必須
        "expected_direction": river['direction'] * -1,  # 必須
        "decision_time": river['time'],  # 必須（実際には使わないけど、、）
        "decision_price": river['peak'],  # 必須
        "target": 価格 or Range  # 80以上の値は価格とみなし、それ以外ならMarginとする
        "tp": 価格 or Range,  # 80以上の値は価格とみなし、それ以外ならMarginとする
        "lc": 価格　or Range  # 80以上の値は価格とみなし、それ以外ならMarginとする
    }
    いずれかが必須
    # ポジションマージンか、target_priceが必要。最終的に必要になるのは「ポジションマージン」　（targetは複数オーダー発行だと調整が入る）
    {　
        "position_margin": position_margin,  # 検証で任意　運用で必須(複数Marginで再計算する可能性あり)
        "target_price": target_price,  # 検証で必須　運用で任意(複数Marginで再計算する可能性あり)
    }
    :return:　order_base = {
        "stop_or_limit": stop_or_limit,  # 運用で必須
        "expected_direction": river['direction'] * -1,  # 必須(基本的には直近(リバー)の順方向）
        "decision_time": river['time'],  # 任意
        "decision_price": river['peak'],  # 検証で任意　運用で必須(複数Marginで再計算する可能性あり)
        "position_margin": position_margin,  # 検証で任意　運用で必須(複数Marginで再計算する可能性あり)
        "target_price": target_price,  # 検証で必須　運用で任意(複数Marginで再計算する可能性あり)
        "lc_range": lc,  # 検証で必須　運用で任意
        "tp_range": tp,  # 検証で必須　運用で任意
        "tp_price": target_price + (tp * river['direction']),  # 任意
        "lc_price": target_price - (lc * river['direction']),  # 任意
    }
    """
    # ⓪必須項目がない場合、エラーとする
    if not('stop_or_limit' in order_base) or not('expected_direction' in order_base) or \
            not('decision_price' in order_base) or not('decision_time' in order_base):
        print("　　　　エラー（項目不足)",'stop_or_limit' in order_base,'expected_direction' in order_base,
              'decision_price' in order_base, 'decision_time' in order_base)
        return -1  # エラー

    # ①TargetPriceを確実に取得する
    if not ('target' in order_base):
        # どっちも入ってない場合、Ｅｒｒｏｒ
        print("    ★★★target(Rangeか価格か）が入力されていません")
    elif order_base['target'] >= 80:
        # targetが８０以上の数字の場合、ターゲット価格が指定されたとみなす
        print("    target 価格指定")
        order_base['position_margin'] = abs(order_base['decision_price'] - order_base['target'])
        order_base['target_price'] = order_base['target']
    elif order_base['target'] < 80:
        # targetが80未満の数字の場合、PositionまでのMarginが指定されたとみなす
        print("    target Margin指定")
        order_base['position_margin'] = order_base['target']
        order_base['target_price'] = order_base['decision_price'] + \
                                     (order_base['target'] * order_base['expected_direction'] * order_base['stop_or_limit'])
    else:
        print("     Target_price PositionMarginどっちも入っている")

    # ② TP_priceとTP_Rangeを求める
    if not ('tp' in order_base):
        print("    ★★★TP情報が入っていません（利確設定なし？？？）")
        order_base['tp_range'] = 0  # 念のため０を入れておく（価格の指定は絶対に不要）
    elif order_base['tp'] >= 80:
        print("    TP 価格指定")
        # 80以上の数字は、Price値だと認識。Priceの設定と、Rangeの算出と設定を実施。
        #    ただし、偶然Target_Priceと同じになる(秒でTPが入ってしまう)可能性あるため、target_price-価格が0.02未満の場合は調整する。
        if abs(order_base['target_price'] - order_base['tp']) < 0.02:
            # 調整を行う（Rangeを最低の0.02に設定し、そこから改めてLC＿Priceを算出する）
            print("  ★★TP価格とTarget価格が同値となったため、調整あり(0.02)")
            order_base['tp_range'] = 0.02
            order_base['tp_price'] = order_base['target_price'] + (order_base['tp_range'] * order_base['expected_direction'])
        else:
            # 調整なしでOK
            order_base['tp_price'] = order_base['tp']
            order_base['tp_range'] = abs(order_base['target_price'] - order_base['tp'])
    elif order_base['tp'] < 80:
        print("    TP　Range指定")
        # 80未満の数字は、Range値だと認識。Rangeの設定と、Priceの算出と設定を実施
        order_base['tp_price'] = order_base['target_price'] + (order_base['tp'] * order_base['expected_direction'])
        order_base['tp_range'] = order_base['tp']

    # ③ LC_priceとLC_rangeを求める
    if not('lc' in order_base):
        # どっちも入ってない場合、エラー
        print("    ★★★LC情報が入っていません（利確設定なし？？）")
    elif order_base['lc'] >= 80:
        print("    LC 価格指定")
        # 80以上の数字は、Price値だと認識。Priceの設定と、Rangeの算出と設定を実施。
        #     ただし、偶然Target_Priceと同じになる(秒でLCが入ってしまう)可能性あるため、target_price-価格が0.02未満の場合は調整する。
        if abs(order_base['target_price'] - order_base['lc']) < 0.02:
            # 調整を行う（Rangeを最低の0.02に設定し、そこから改めてLC＿Priceを算出する）
            print("  ★★LC価格とTarget価格が同値となったため、調整あり(0.02)")
            order_base['lc_range'] = 0.02
            order_base['lc_price'] = order_base['target_price'] - (order_base['lc_range'] * order_base['expected_direction'])
        else:
            # 調整なしでOK
            order_base['lc_price'] = order_base['lc']
            order_base['lc_range'] = abs(order_base['target_price'] - order_base['lc'])
    elif order_base['lc'] < 80:
        print("    LC RANGE指定")
        # 80未満の数字は、Range値だと認識。Rangeの設定と、Priceの算出と設定を実施
        order_base['lc_price'] = order_base['target_price'] - (order_base['lc'] * order_base['expected_direction'])
        order_base['lc_range'] = order_base['lc']

    return order_base


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
    gap = 0 # Flop3の半分くらいは余裕度が欲しい
    # ピークポイントを検索する（ここではピークofピークの場合Falseを意味する、not_peakを設定。
    print("　　　　PeakOfPeak最古時間", peaks_past[-1]["time_old"])
    for i in range(len(peaks_past)):
        if flop3['direction'] == 1:
            # フロップ傾きが１の場合、flop['peak']より大きな値がないかを探索
            if flop3['peak'] >= peaks_past[i]['peak'] + gap:
                # flop3が大きい場合、peakofPeak継続
                peak_of_peak = True
                peak_gap = peaks_past[i]['peak'] - flop3['peak']
            else:
                # flop3が前のより小さい場合、peakOfPeak解除。ループ終了
                peak_of_peak = False
                peak_gap = 0
                break
        else:
            # フロップ傾きがー１の場合、flop['peaks']より小さな値がないかを探索
            if flop3['peak'] <= peaks_past[i]['peak'] - gap:
                # flop3が小さい場合、peakofPeak継続
                peak_of_peak = True
                peak_gap = peaks_past[i]['peak'] - flop3['peak']
            else:
                # flop3が前のより大きい場合、peakOfPeak解除。ループ終了
                peak_of_peak = False
                peak_gap = 0
                break

    # peak10個分だと少ないので、DfRでも検討する(自分自身も検索範囲に入っているんので、Gapを入れるとおかしくなる）
    # part_of_df_r = df_r[15:40]  # ４時間分（４８足分）  # 自身(ターンピーク)を入れないためには、リバー2足＋ターン分で大体15足あれば。。
    # print("　　　　PeakOfPeak最古時間", part_of_df_r.iloc[-1]['time_jp'])
    # if flop3['direction'] == 1:
    #     # フロップ傾きが１の場合、flop['peak']より大きな値がないかを探索
    #     past_peak = part_of_df_r["inner_high"].max()
    #     # print("  最大価格", part_of_df_r["inner_high"].max())
    #     if flop3['peak'] >= past_peak + gap:
    #         # print(" ", flop3['peak'], past_peak + gap)
    #         peak_of_peak = True
    #     else:
    #         # print(" g", flop3['peak'], past_peak + gap)
    #         peak_of_peak = False
    # else:
    #     # フロップ傾きがー１の場合、flop['peaks']より小さな値がないかを探索
    #     past_peak = part_of_df_r["inner_low"].min()
    #     # print("  最小価格", part_of_df_r["inner_low"].min())
    #     if flop3['peak'] <= past_peak - gap:
    #         # print("  ", flop3['peak'], past_peak - gap)
    #         peak_of_peak = True
    #     else:
    #         # print("  g", flop3['peak'], past_peak - gap)
    #         peak_of_peak = False

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
    # (1)ピークスを取得（引数か処理）。この関数ではPeaksの情報を元にし、Dfは使わない。
    # ①必要最低限の項目たちを取得する
    peaks = judge_list_or_data_frame(args[0])  # ピークスを確保。モードを問わない共通処理。args[0]はデータフレームまたはPeaksList。
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
    f_gap = 0.1 if len(args) == 2 else 0.05  # 0.6
    tf_max = args[1]['tf_ratio_max'] if len(args) == 2 else 0.4  # 0.6
    rt_max = args[1]['rt_ratio_max'] if len(args) == 2 else 1.0  #
    rt_gap_min = args[1]['rt_gap'] if len(args) == 2 else 0  # 0.03
    r_count = args[1]['count'] if len(args) == 2 else 2  # params['count']
    position_margin = args[1]['margin'] if len(args) == 2 else 0.008  #
    tp = f.cal_at_least(0.04, (turn['gap'] - river['gap']) * args[1]['tp'])  # 5pipsとなると結構大きい。Minでも3pips欲しい
    lc = f.cal_at_least(0.04, (turn['gap'] - river['gap']) * args[1]['lc'])
    t_count = args[1]['tc'] if len(args) == 2 else 7  # ターンは長すぎる(count)と、戻しが強すぎるため、この値以下にしておきたい。
    t_gap = 0.12  # ターンは長すぎる(gap)と、戻しが強すぎるため、この値以下にしておきたい。出来れば８くらい・・？
    stop_or_limit = args[1]['sl'] if len(args) == 2 else 1  # マージンの方向(+値は期待方向に対して取得猶予を取る場合(順張り),－値は期待と逆の場合は逆張り）
    d = args[1]['d'] if len(args) == 2 else -1  # 売買の方向。リバーの方向に対し、同方向の場合１．逆方向の場合ー１
    # ②オーダーのベースを組み立てる（オーダ発行の元にするため、返却が必要な値。target_price等の算出）
    order_base = order_finalize({"stop_or_limit": stop_or_limit,
                                 "expected_direction": river['direction'] * d,
                                 "decision_time": river['time'],
                                 "decision_price": peaks[0]['peak'],  # フラグ成立時の価格（先頭[0]列のOpen価格）
                                 "position_margin": position_margin,
                                 "lc_range": lc,
                                 "tp_range": tp,
                                 })

    # (3)★★判定部
    take_position_flag = False  # ポジションフラグを初期値でFalseにする
    # リバー数で最初の判定（ネストを深くしないため、外に出した）
    if river['count'] == r_count:
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
        return {  # フラグ無しの場合、オーダー以外を返却。
            "take_position_flag": take_position_flag,
            "order_base": order_base,  # 検証で利用する。
            "records": records  # 記録軍。CSV保存時に出力して解析ができるように。
        }

    # (4) ★★実オーダーを組み立てる（成立時のみ生成）
    print("   決心価格", order_base['decision_price'], "決心時間", order_base['decision_time'])
    print("   注文価格", order_base['target_price'], "向とSL", order_base['expected_direction'], stop_or_limit)
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
        "records": records  # 記録軍。CSV保存時に出力して解析ができるように。
    }


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
    print("■ダブルピークBreak判定")
    # (1)ピークスを取得（引数か処理）。この関数ではPeaksの情報を元にし、Dfは使わない。
    # ①必要最低限の項目たちを取得する
    mode_judge = judge_list_or_data_frame(*args)  # ピークスを確保。モードを問わない共通処理。args[0]はデータフレームまたはPeaksList。
    peaks = mode_judge['peaks']
    river = peaks[0]  # 最新のピーク（リバーと呼ぶ。このCount＝２の場合、折り返し直後）
    turn = peaks[1]  # 注目するポイント（ターンと呼ぶ）
    flop3 = peaks[2]  # レンジ判定用（プリフロップと呼ぶ）
    param_mode = mode_judge['param_mode']
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
    tf_max = args[1]['tf_ratio_max'] if param_mode else 0.8  # 0.6
    rt_min = args[1]['rt_ratio_min'] if param_mode else 1.1  #
    rt_max = args[1]['rt_ratio_max'] if param_mode else 2.0  #
    position_margin = args[1]['margin'] if param_mode else 0.02  #
    tp = 0.03
    lc = turn['peak']
    t_count = 2  # ターンは長すぎる(count)と、戻しが強すぎるため、この値以下にしておきたい。
    t_gap = 0.12  # ターンは長すぎる(gap)と、戻しが強すぎるため、この値以下にしておきたい。出来れば８くらい・・？
    stop_or_limit = args[1]['sl'] if param_mode else 1  # マージンの方向(+値は期待方向に対して取得猶予を取る場合(順張り),－値は期待と逆の場合は逆張り）
    d = args[1]['d'] if param_mode else 1  # 売買の方向。リバーの方向に対し、同方向の場合１．逆方向の場合ー１
    # ②オーダーのベースを組み立てる（オーダ発行の元にするため、返却が必要な値。target_price等の算出）
    order_base = order_finalize({"stop_or_limit": stop_or_limit,
                                 "expected_direction": river['direction'] * d,
                                 "decision_time": river['time'],
                                 "decision_price": river['peak'],  # フラグ成立時の価格（先頭[0]列のOpen価格）
                                 "target": position_margin,  # 価格かマージンかを入れることが出来る
                                 "lc": lc,
                                 "tp": tp,
                                 })
    print(order_base)

    # (3)★★判定部
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
            print("   不成立(ターン関係)", turn['gap'],turn['count'])
    else:
        print("   　不成立（フロップカウント）")

    print("   情報 tf:", turn_flop3_ratio, "%(<", tf_max, "),rt:(", rt_min, "<)" ,river_turn_ratio, "%(<", rt_max, "),",
                    "rt_gap:", abs(river_turn_gap), "(<", 0, "), t_gap", turn['gap'], "(<", t_gap,"),", flop3['gap'])

    # (3) ★★判定部2(過去数個のピークの中で、フロップのピークが頂点かどうか(フロップが傾きマイナスなら最低値、逆なら最高値か）
    peak_of_peak = peak_of_peak_judgement(peaks[3:10], flop3)

    # ダブルトップの成立判定
    if not peak_of_peak:
        # flop3が頂点ではなかった場合、信用できないダブルトップ。
        if take_position_flag:
            take_position_flag = False
            print("    ■TakePositionFlagを解除（最ピークでないため）")

    # (3) ★★オーダーのベースを生成する（検証で利用するのはこのオブジェクト）
    # ①オーダー無し時は除外
    if not take_position_flag:  # ポジションフラグがFalseの場合は、返却をして終了
        return {  # フラグ無しの場合、オーダー以外を返却。
            "take_position_flag": take_position_flag,
            "order_base": order_base,  # 検証で利用する。
            "records": records  # 記録軍。CSV保存時に出力して解析ができるように。
        }

    # (4) ★★実オーダーを組み立てる（成立時のみ生成）
    print("   決心価格", order_base['decision_price'], "決心時間", order_base['decision_time'])
    print("   注文価格", order_base['target_price'], "向とSL", order_base['expected_direction'], stop_or_limit)
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
    print("■ダブルピーク判定")
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
    tf_max = args[1]['tf_ratio_max'] if param_mode else 0.8  # 0.6
    rt_min = args[1]['rt_ratio_min'] if param_mode else 0.7  #
    rt_max = args[1]['rt_ratio_max'] if param_mode else 1.0  #
    position_margin = args[1]['margin'] if param_mode else 0.02  #
    tp = f.cal_at_least(0.04, (abs(turn['peak'] - river['peak_old']) * 1))  # 5pipsとなると結構大きい。Minでも3pips欲しい
    lc = f.cal_at_least(0.03, (abs(turn['peak'] - river['peak_old']) * 0.8))
    t_count = 2  # ターンは長すぎる(count)と、戻しが強すぎるため、この値以下にしておきたい。
    t_gap = 0.12  # ターンは長すぎる(gap)と、戻しが強すぎるため、この値以下にしておきたい。出来れば８くらい・・？
    stop_or_limit = args[1]['sl'] if param_mode else 1  # マージンの方向(+値は期待方向に対して取得猶予を取る場合(順張り),－値は期待と逆の場合は逆張り）
    d = args[1]['d'] if param_mode else -1  # 売買の方向。リバーの方向に対し、同方向の場合１．逆方向の場合ー１
    # ②オーダーのベースを組み立てる（オーダ発行の元にするため、返却が必要な値。target_price等の算出）
    order_base = order_finalize({"stop_or_limit": stop_or_limit,
                                 "expected_direction": river['direction'] * d,
                                 "decision_time": river['time'],
                                 "decision_price": river['peak'],  # フラグ成立時の価格（先頭[0]列のOpen価格）
                                 "target": position_margin,  # 価格かマージンかを入れることが出来る
                                 "lc": lc,
                                 "tp": tp,
                                 })

    # (3)★★判定部
    take_position_flag = False  # ポジションフラグを初期値でFalseにする
    # リバー数で最初の判定（ネストを深くしないため、外に出した）
    if 4 <= flop3['count']:
        if turn_flop3_ratio < tf_max and 0.012 < turn['gap'] and t_count <= turn['count']:  # ターンの情報
            if rt_min < river_turn_ratio < rt_max:  # リバーについて（リバー比）
                take_position_flag = True
                print("   ■■ダブルトップ完成")
            else:
                print("   不成立(リバー関係)")
        else:
            print("   不成立(ターン関係)", turn['gap'],turn['count'])
    else:
        print("   　不成立（フロップカウント）")

    print("   情報 tf:", turn_flop3_ratio, "%(<", tf_max, "),rt:(", rt_min, "<)" ,river_turn_ratio, "%(<", rt_max, "),",
                    "rt_gap:", abs(river_turn_gap), "(<", 0, "), t_gap", turn['gap'], "(<", t_gap,"),", flop3['gap'])

    # (3) ★★判定部2(過去数個のピークの中で、フロップのピークが頂点かどうか(フロップが傾きマイナスなら最低値、逆なら最高値か）
    peak_of_peak = peak_of_peak_judgement(peaks[3:10], flop3, df_r)


    # ダブルトップの成立判定
    if not peak_of_peak:
        # flop3が頂点ではなかった場合、信用できないダブルトップ。
        if take_position_flag:
            take_position_flag = False
            print("    ■TakePositionFlagを解除（最ピークでないため）")

    # (3) ★★オーダーのベースを生成する（検証で利用するのはこのオブジェクト）
    # ①オーダー無し時は除外
    if not take_position_flag:  # ポジションフラグがFalseの場合は、返却をして終了
        return {  # フラグ無しの場合、オーダー以外を返却。
            "take_position_flag": take_position_flag,
            "order_base": order_base,  # 検証で利用する。
            "records": records  # 記録軍。CSV保存時に出力して解析ができるように。
        }

    # (4) ★★実オーダーを組み立てる（成立時のみ生成）
    print("   決心価格", order_base['decision_price'], "決心時間", order_base['decision_time'])
    print("   注文価格", order_base['target_price'], "向とSL", order_base['expected_direction'], stop_or_limit)
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
    peaks_info = p.peaks_collect_main(df_r[:90], 10)  # Peaksの算出（ループ時間短縮の為、必要最低限のピーク数（＝４）を指定する）
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
    # # ダブルトップ直前で、ダブルトップを形成するところを狙いに行く。TF＜0.4、RT＜0.7
    # beforeDoublePeak_ans = beforeDoublePeak(df_r, peaks)
    #
    # # (2)ダブルトップポイントをリバーが大きく通過している場合。TF＜0.4、RT＞1.3
    # beforeDoublePeakBreak_ans = DoublePeakBreak(df_r, peaks)

    # (3)ダブルトップ（これはピークが１０個必要。過去のデータを比べて最ピークかどうかを確認したいため）
    doublePeak_ans = DoublePeak(df_r, peaks)

    # 【オーダーを統合する】  現状同時に成立しない仕様。
    if doublePeak_ans['take_position_flag']:
        order_information = doublePeak_ans
    # elif doublePeak_ans['take_position_flag']:
    #     order_information = beforeDoublePeakBreak_ans  # オーダー発行情報のみを返却する
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
            "target_price": order_base_information['decision_price'] + (0.03 * (order_base_information['expected_direction']) * order_base_information['stop_or_limit']),
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
            "target_price": order_base_information['decision_price'] + (0.03 * (order_base_information['expected_direction'] * -1) * order_base_information['stop_or_limit']),
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





