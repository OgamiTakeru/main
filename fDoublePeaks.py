import fBlockInspection as t  # とりあえずの関数集
import tokens as tk  # Token等、各自環境の設定ファイル（git対象外）
import classOanda as oanda_class
import fPeakInspection as p  # とりあえずの関数集
import fGeneric as gene
import fCommonFunction as cf
import fMoveSizeInspection as ms
import statistics
import pandas as pd
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


# def DoublePeak(dic_args):
#     """
#     ★ピークスは１０個必要
#     １）引数について。関数を呼び出し、整流化する。最終的に必要なものは、
#     df_r：必須となる要素（ローソク情報(逆順[直近が上の方にある＝時間降順])データフレーム）
#     peaks：この関数の実行には必ず必要。開始時に渡されない場合、整流化関数でdf_rを元に算出される。
#     params：無い場合もある。無い場合はNone、ある場合はDic形式。
#     の三つ。
#     ２）ロジックについて
#     ＜ロジック概要＞ダブルトップを頂点とし、そこから戻る方向にポジションする。
#                      ↓ 10pips（基準：ターン）
#        　　23pips　   /\  /
#            フロップ→ /  \/  ← 7pipsまで(リバー)
#           　　　　　/　　　　　　　　　←ピークの反対くらいがLC？
#     　　トラップライン
#     　　・ターンのピークオールド起点でリバーの逆方向（逆張り）
#     　　・ターンのピーク起点でリバーの逆方向（順張り）
#        ルール一覧
#        ・ターンが小さい、または、少ない場合、ダブルトップポイントを瞬間的に突破する回数が多い為NGとしたい。、
#        　その為、ターンは３足分以上かつ、2pips以上とする。
#        ・出来ればフロップは長い方がいい気がする。フロップカウントは７以上
#        　（さらにフロップの頂点が新規ポイントの場合は率上がるかも？）
#        ・フロップのピーク点か、直近の10ピークの中で最も頂点の場合は、折り返し濃厚。最も頂点でない場合は、Breakまで行く可能性高い。
#        　（別途関数を準備）
#     :return:　必須最低限　{"take_position_flag": boolean} の返却は必須。さらにTrueの場合注文情報が必要。
#     """
#     # print(dic_args)
#     print("  ■ダブルピーク判定")
#     # (1)ピークスを取得（引数か処理）。この関数ではPeaksの情報を元にし、Dfは使わない。
#     # ①必要最低限の項目たちを取得する
#     fixed_information = cf.information_fix(dic_args)  # DFとPeaksが必ず返却される
#     # 情報の取得
#     df_r = fixed_information['df_r']
#     peaks = fixed_information['peaks']
#     river = peaks[1]  # 最新のピーク（リバーと呼ぶ。このCount＝２の場合、折り返し直後）
#     turn = peaks[2]  # 注目するポイント（ターンと呼ぶ）
#     flop3 = peaks[3]  # レンジ判定用（プリフロップと呼ぶ）
#     params = fixed_information['params']  # パラメータ情報の取得
#     inspection_params = fixed_information['inspection_params']
#     print("  r", river)
#     print("  t", turn)
#     print("  f",flop3)
#
#     # (2)パラメータ指定。
#     # ①　パラメータを設定する(検証用。売買に関するパラメータ）
#     # inspection_params = {"margin": 0.01, "d": 1}
#     if inspection_params:
#         # 売買に関するパラメータがある場合(Noneでない場合）、各値を入れていく（１つ入れるなら全て設定する必要あり）
#         position_margin = inspection_params['margin']
#         d = inspection_params['d']  # 売買の方向。リバーの方向に対し、同方向の場合１（ライン突破）．逆方向の場合ー１(ラインで抵抗）
#         sl = inspection_params['sl']  # Stop or Limit
#         tp = gene.cal_at_least(0.06, (abs(turn['peak'] - river['peak_old']) * 1))  # 5pipsとなると結構大きい。Minでも3pips欲しい
#         lc = gene.cal_at_least(0.05, (abs(turn['peak'] - river['peak_old']) * 0.8))
#     else:
#         # 売買に関してのパラメータ無し（ダブルトップで折り返しの方向で、固定のマージンやTP/LCで取得する）
#         position_margin = 0.01
#         d = -1  # 売買の方向。リバーの方向に対し、同方向の場合１．逆方向の場合ー１
#         sl = 1
#         tp = gene.cal_at_least(0.06, (abs(turn['peak'] - river['peak_old']) * 1))  # 5pipsとなると結構大きい。Minでも3pips欲しい
#         lc = gene.cal_at_least(0.05, (abs(turn['peak'] - river['peak_old']) * 0.8))
#
#     # ②　パラメータを設定する（対象の形状目標を変更できるようなパラメータ）
#     # params = {"tf_ratio_max": 0.65, "rt_ratio_min": 0.4, "rt_ratio_max": 1, "t_count": 2, "f3_count": 5}
#     if params:
#         # paramsが入っている場合（Noneでない場合）
#         tf_min = params['tf_ratio_min']
#         tf_max = params['tf_ratio_max']  # ターンは、フロップの６割値度
#         rt_min = params['rt_ratio_min']  # リバーは、ターンの最低４割程度
#         rt_max = params['rt_ratio_max']  # リバーは、ターンの最高でも６割程度
#         f3_count = params['f3_count']
#         t_count_min = params['t_count_min']  #
#         t_count_max = params['t_count_max']  # ターンは長すぎる(count)と、戻しが強すぎるため、この値以下にしておきたい。
#         r_count = params['r_count']
#     else:
#         # パラメータがない場合、一番スタンダート（最初）の物で実施する
#         tf_min = 0.3
#         tf_max = 1.2  # ターンは、フロップの６割値度(0.65) ⇒　参考までのダブルトップを求めるため、緩和し1.2へ
#         rt_min = 0.2  # リバーは、ターンの最低４割程度
#         rt_max = 1.0  # リバーは、ターンの最高でも６割程度
#         f3_count = 3
#         t_count_min = 2  #
#         t_count_max = 6  # ターンは長すぎる(count)と、戻しが強すぎるため、この値以下にしておきたい。
#         r_count = 2
#
#     # (3)★★判定部
#     take_position_flag = False  # ポジションフラグを初期値でFalseにする
#     #          f3  t  r
#     #           ↓　 ↓　↓　
#     #             /\  /
#     #            /  \/
#     #           /
#     # 　　　　　 / 　　　　
#     # ①形状の判定
#     # ①-1 各ブロックのサイズについて
#     const_flag = False
#     if river['count'] >= r_count:
#         if flop3['count'] >= f3_count:
#             if turn['gap'] >= 0.011 and t_count_min <= turn['count'] <= t_count_max:
#                 const_flag = True
#                 c = gene.str_merge("サイズ感は成立", flop3['count'], turn['count'], river['count'], turn['gap'])
#             else:
#                 c = gene.str_merge("turnのサイズ、カウントが規定値以下", turn['count'], turn['gap'])
#         else:
#             c = gene.str_merge("flop3のカウントが規定値以下", flop3['count'])
#     else:
#         c= gene.str_merge("riverのカウントが規定値以下", river['count'])
#
#     # ①-2 各ブロック同士のサイズ感の比率について
#     turn_ratio_based_flop3 = round(turn['gap'] / flop3['gap'], 3)
#     river_ratio_based_turn = round(river['gap'] / turn['gap'], 3)
#     compare_flag = False
#     if tf_min < turn_ratio_based_flop3 < tf_max:
#         if rt_min < river_ratio_based_turn < rt_max:
#             compare_flag = True
#             cr = gene.str_merge("サイズ割合は成立", turn_ratio_based_flop3, river_ratio_based_turn)
#         else:
#             cr = gene.str_merge("riverが範囲外", river_ratio_based_turn)
#     else:
#         cr = gene.str_merge("turnがflop3に対して大きすぎる", turn_ratio_based_flop3)
#
#     # ①-3 両方成立する場合、TakePositionフラグがOnになる
#     print("  DoubleTop結果", c, cr)
#     if const_flag and compare_flag:
#         take_position_flag = True
#
#     # (4)オーダーの作成と返却
#     if take_position_flag:
#         # オーダーの可能性がある場合、オーダーを正確に作成する
#         exe_orders = [
#             gene.order_finalize({  # オーダー２を作成
#                 "name": "DoublePeak(ダブル抵抗）",
#                 "order_permission": True,
#                 "decision_price": river['latest_price'],  # ['peak']か['latest_price']だが、後者の方が適切か？
#                 "target": round(river['latest_price'] + (position_margin * river['direction'] * d * sl), 3),  # 価格でする
#                 "peak_price": river['peak'],
#                 "decision_time": 0,  #
#                 "tp": 0.10,
#                 "lc": 0.03,
#                 "units": 10,
#                 "expected_direction": d * river['direction'],
#                 "stop_or_limit": sl,
#                 "trade_timeout": 1800,
#                 "remark": "test",
#                 "tr_range": 0.05,
#                 "lc_change": {"lc_change_exe": True, "lc_trigger_range": 0.03, "lc_ensure_range": 0.01}
#             })
#         ]
#         return {  # take_position_flagの返却は必須。Trueの場合注文情報が必要。
#             "take_position_flag": take_position_flag,
#             "exe_orders": exe_orders,  # 発行するオーダー。このままオーダーを発行できる状態
#         }
#     else:
#         return {  # take_position_flagの返却は必須。Trueの場合注文情報が必要。
#             "take_position_flag": False,  # take_position_flagの値と同様だが、わかりやすいようにあえてFalseで書いている
#         }
#     # # ②判定部2(過去数個のピークの中で、フロップのピークが頂点かどうか(フロップが傾きマイナスなら最低値、逆なら最高値か）
#     # peak_of_peak = peak_of_peak_judgement(peaks[3:10], flop3, df_r)
#     #
#     # # ③ダブルトップの成立判定
#     # if not peak_of_peak:
#     #     # flop3が頂点ではなかった場合、信用できないダブルトップ。
#     #     if take_position_flag:
#     #         take_position_flag = False
#     #         print("    ■TakePositionFlagを解除（最ピークでないため）")
#     #
#     # # (4) ★★オーダーのベースを生成する（検証で利用するのはこのオブジェクト）
#     # # ①オーダー無し時は除外
#     # if not take_position_flag:  # ポジションフラグがFalseの場合は、返却をして終了
#     #     return {  # フラグ無しの場合、オーダー以外を返却。
#     #         "take_position_flag": take_position_flag,
#     #         "order_base": order_base,  # 検証で利用する。
#     #         "records": records  # 記録軍。CSV保存時に出力して解析ができるように。
#     #     }
#     #
#     # # ②★★実オーダーを組み立てる（成立時のみ生成）
#     # print("   決心価格", order_base['decision_price'], "決心時間", order_base['decision_time'])
#     # print("   注文価格", order_base['target_price'], "向とSL", order_base['expected_direction'], stop_or_limit)
#     # exe_orders = [
#     #     f.order_finalize({  # オーダー２を作成
#     #         "name": "DoublePeak(ダブル抵抗）",
#     #         "order_permission": True,
#     #         "decision_price": river['peak'],  # ★
#     #         "target": turn['peak'] + (0.01 * river['direction'] * -1),  # 価格でする
#     #         "decision_time": 0,  #
#     #         "tp": 0.10,
#     #         "lc": 0.03,
#     #         "units": 10,
#     #         "expected_direction": river['direction'] * -1,
#     #         "stop_or_limit": 1,  # ★順張り
#     #         "trade_timeout": 1800,
#     #         "remark": "test",
#     #         "tr_range": 0.05,
#     #         "lc_change": {"lc_change_exe": True, "lc_trigger_range": 0.03, "lc_ensure_range": 0.01}
#     #     }),
#     #     f.order_finalize({
#     #         "name": "DoublePeak(ダブル突破）",
#     #         "order_permission": True,
#     #         "decision_price": river['peak'],  # ★
#     #         "target": flop3['peak'] + (0.01 * river['direction']),  # 価格でする
#     #         "decision_time": 0,  #
#     #         "tp": 0.10,
#     #         "lc": 0.03,
#     #         "units": 10,
#     #         "expected_direction": river['direction'],
#     #         "stop_or_limit": 1,  # ★
#     #         "trade_timeout": 1800,
#     #         "remark": "test",
#     #         "tr_range": 0.05,
#     #         "lc_change": {"lc_change_exe": True, "lc_trigger_range": 0.01, "lc_ensure_range": -0.02}
#     #     })
#     # ]
#     #
#     # return {  # take_position_flagの返却は必須。Trueの場合注文情報が必要。
#     #     "take_position_flag": take_position_flag,
#     #     "order_base": order_base,  # 検証で利用する。
#     #     "exe_orders": exe_orders,  # 発行するオーダー。このままオーダーを発行できる状態
#     #     "records": records  # 記録軍。CSV保存時に出力して解析ができるように。
#     # }


def DoublePeak_predict(dic_args):
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
        l_count = params['l_count']
        flop3_size = 0.12
    else:
        # パラメータがない場合、一番スタンダート（最初）の物で実施する
        rt_min = 0.1
        rt_max = 0.65  # リバーは、ターンの６割値度(0.65) ⇒
        lr_min = 0.24  # レイテストは、リバーの最低４割程度
        lr_max = 1  # レイテストは、リバーの最高でも６割程度
        lr_max_extend = 5
        t_count = 5
        r_count_min = 2  #
        r_count_max = 7  # リバーは長すぎる(count)と、戻しが強すぎるため、この値以下にしておきたい。6
        l_count = 2
        flop3_size = 0.15

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
            if river['gap'] >= 0.011 and r_count_min <= river['count'] <= r_count_max:
                const_flag = True
                c = gene.str_merge("サイズ感は成立", turn['count'], river['count'], latest['count'], river['gap'])
            else:
                c = gene.str_merge("riverのサイズ、カウントが規定値以下", river['count'], river['gap'])
        else:
            c = gene.str_merge("turnのカウントが規定値以下", turn['count'])
    else:
        c = gene.str_merge("latestのカウントが規定値以下", latest['count'])

    # ①-2 【基本形状】各ブロック同士のサイズ感の比率について
    turn_ratio_based_flop3 = round(river['gap'] / turn['gap'], 3)
    river_ratio_based_turn = round(latest['gap'] / river['gap'], 3)
    compare_flag = False
    confidence = 0
    if turn['gap'] > flop3_size:
        if rt_min < turn_ratio_based_flop3 < rt_max:
            if lr_min < river_ratio_based_turn < lr_max:
                compare_flag = True
                confidence = 1  # 一番信用のできる形のため、信頼度最大
                cr = gene.str_merge("サイズ割合は成立", turn_ratio_based_flop3, river_ratio_based_turn)
            elif lr_min < river_ratio_based_turn <= lr_max_extend:
                compare_flag = True
                confidence = 0.5  # 信頼度が微妙なため、信頼度半減(勢いがいいときは超えるんだけど、、超えない時もある）
                cr = gene.str_merge("サイズ割合は成立(LatestOver）", river_ratio_based_turn, lr_max_extend)
            else:
                cr = gene.str_merge("Latestが範囲外", river_ratio_based_turn, "規定値は", lr_max_extend, "以下")
        else:
            cr = gene.str_merge("riverがturnに対して大きすぎる", turn_ratio_based_flop3)
    else:
        cr = gene.str_merge("全体的に小さい（turnが小さい)", turn['gap'])

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
    temp_inspection_peaks = peaks[flop3_subscript:]  # flop以降のピークスすべて
    # gene.print_arr(temp_inspection_peaks, 6)
    if latest['direction'] == -1:
        # 直近が下り方向の場合、折り返し基準のflop3は下がり。その前が下がりメインの場合、下がりきっていると思われる。
        # flop3以前の、最も高い値を算出（その時刻を算出）
        max_index = max(enumerate(temp_inspection_peaks), key=lambda x: x[1].get('peak', float('-inf')))[0]
        # print(max_index, temp_inspection_peaks[max_index])
        temp_inspection_peaks = temp_inspection_peaks[:max_index]  # 最大値までの範囲で
        lower_peaks = [item for item in temp_inspection_peaks if item["direction"] == -1]  # Lower側
        lower_gap_total = sum(d['gap'] for d in lower_peaks)
        upper_peak = [item for item in temp_inspection_peaks if item["direction"] == 1]
        upper_gap_total = sum(d['gap'] for d in upper_peak)
        upper_lower_gap = round(lower_gap_total - upper_gap_total, 3)
        # print(lower_gap_total - upper_gap_total)
        # print(sum(d['gap'] for d in temp_inspection_peaks))

        if lower_gap_total - upper_gap_total > turn_gap * 1.3:
            print(t6, "3回折り返し相当の下がりあり（これ以上下がらない状態）Upper:",upper_gap_total,"lower:",lower_gap_total, "t", turn_gap)
            double_top_strength = 1
            double_top_strength_memo = double_top_strength_memo + ", 下がり切り" + str(upper_lower_gap) + str(turn_gap)
        else:
            print(t6, "突破形状維持（3回折り返し以内の下がり、もっと下がる）Upper:",upper_gap_total,"lower:",lower_gap_total, "t", turn_gap)
            double_top_strength = -1
            double_top_strength_memo = double_top_strength_memo + ", 突破(より下)"+ str(upper_lower_gap) + str(turn_gap)
    else:
        # 直近が登り方向の場合、折り返し基準のflop3は下がり。その前が下がりメインの場合、下がりきっていると思われる。
        # flop3以前の、最も低い値を算出（その時刻を算出）
        min_index = min(enumerate(temp_inspection_peaks), key=lambda x: x[1].get('peak', float('-inf')))[0]
        print(min_index, temp_inspection_peaks[min_index])
        temp_inspection_peaks = temp_inspection_peaks[:min_index]  # 最大値までの範囲で
        lower_peaks = [item for item in temp_inspection_peaks if item["direction"] == -1]  # Lower側
        lower_gap_total = sum(d['gap'] for d in lower_peaks)
        upper_peak = [item for item in temp_inspection_peaks if item["direction"] == 1]
        upper_gap_total = sum(d['gap'] for d in upper_peak)
        upper_lower_gap = round(upper_gap_total - lower_gap_total, 3)
        if upper_gap_total - lower_gap_total> turn_gap * 1.5:
            print(t6, "3回折り返し相当の上がりあり（これ以上上がらない状態）Upper:",upper_gap_total,"lower:",lower_gap_total, "t", turn_gap)
            double_top_strength = 1
            double_top_strength_memo = double_top_strength_memo + ", 上がり切り" + str(upper_lower_gap) + str(turn_gap)
        else:
            print(t6, "突破形状維持（3回折り返し以内の上がり、もっと上がる）Upper:",upper_gap_total,"lower:",lower_gap_total, "t", turn_gap)
            double_top_strength = -1
            double_top_strength_memo = double_top_strength_memo + ", 突破(より上)" + str(upper_lower_gap) + str(turn_gap)
    # 追加の検討要素②　ターンで突発的な足がある場合、突破しにくいのでは、という判定
    # gene.print_json(turn)
    if turn['include_large']:
        # 大きな足をインクルードする場合、抵抗線の信頼度は強い
        print(t6, "急変動を含むため、抵抗側と判断")
        tk.line_send("急変動を含むため、突破形状だが突破なし")
        double_top_strength = 1
        double_top_strength_memo = double_top_strength_memo + ", 突破(より上)" + str(upper_lower_gap) + str(turn_gap)

    # ■オーダーの作成を実施する
    now_price = cf.now_price()  # 現在価格の取得
    order_base_info = cf.order_base(now_price)  # オーダーの初期辞書を取得する(nowPriceはriver['latest_price']で代用)
    # オーダーの可能性がある場合、オーダーを正確に作成する
    if double_top_strength < 0:
        # ストレングスが突破形状の場合
        if confidence == 1:
            # 【突破形状】従来想定の突破形状
            main_order = copy.deepcopy(order_base_info)
            main_order['target'] = turn['peak']
            main_order['tp'] = 0.3
            main_order['lc'] = 0.15  # * line_strength  # 0.09  # LCは広め
            # main_order['type'] = 'STOP'  # 順張り（勢いがいい場合通過している場合もあるかもだが）
            main_order['type'] = 'MARKET'  # 順張り（勢いがいい場合通過している場合もあるかもだが）
            # main_order['tr_range'] = 0.10  # 要検討
            main_order['expected_direction'] = latest['direction']  # 突破方向
            main_order['priority'] = 2  # ほかので割り込まれない
            main_order['units'] = order_base_info['units'] * 1
            main_order['name'] = "突破形状（通常）"
        else:
            # 【突破形状】従来想定より、リバーの動きが速い
            double_top_strength = -0.9  # ★この場合のみ、このタイミングでストレングスを編集(いずれにせよ突破コース）
            main_order = copy.deepcopy(order_base_info)
            # main_order['target'] = river["peak"] + (0.02 * -1 * latest['direction']) # river(最新の折り返し地点）位まで戻る前提
            main_order['target'] = now_price + (0.022 * 1 * latest['direction'])  # 現在価格で挑戦する！（その代わりLCをturn価格に)
            main_order['tp'] = 0.3
            # main_order['lc'] = 0.22  # * line_strength  # 0.09  # LCは広め
            main_order['lc'] = river['peak'] + (0.03 * -1 * latest['direction'])
            # main_order['type'] = 'STOP'  # 順張り
            main_order['type'] = 'MARKET'  # 順張り（勢いがいい場合通過している場合もあるかもだが）
            # main_order['tr_range'] = 0.10  # 要検討
            main_order['expected_direction'] = latest['direction']  # 突破方向
            main_order['priority'] = 2  #
            main_order['units'] = order_base_info['units'] * 1
            main_order['name'] = "突破形状（latest大）"
    else:
        # ストレングスが抵抗形状の場合
        if confidence == 1:
            # 従来想定の突破形状の未遂（抵抗）
            main_order = copy.deepcopy(order_base_info)
            main_order['target'] = turn['peak']
            main_order['tp'] = 0.3
            main_order['lc'] = 0.15  # * line_strength  # 0.09  # LCは広め
            # main_order['type'] = 'LIMIT'  # 順張り（勢いがいい場合通過している場合もあるかもだが）
            main_order['type'] = 'MARKET'  # 順張り（勢いがいい場合通過している場合もあるかもだが）
            # main_order['tr_range'] = 0.10  # 要検討
            main_order['expected_direction'] = latest['direction'] * -1  # 抵抗方向
            main_order['priority'] = 2  # ほかので割り込まれない
            main_order['units'] = order_base_info['units'] * 1
            main_order['name'] = "NOT突破（突破形状だが突発含み）"
        else:
            # 従来想定より、リバーの動きが速いの未遂（抵抗）
            double_top_strength = 1  # ★この場合のみ、このタイミングでストレングスを編集(いずれにせよ突破コース）
            main_order = copy.deepcopy(order_base_info)
            # main_order['target'] = river["peak"] + (0.02 * -1 * latest['direction']) # river(最新の折り返し地点）位まで戻る前提
            main_order['target'] = now_price + (0.022 * 1 * latest['direction'])  # 現在価格で挑戦する！（その代わりLCをturn価格に)
            main_order['tp'] = 0.3
            # main_order['lc'] = 0.22  # * line_strength  # 0.09  # LCは広め
            main_order['lc'] = river['peak'] + (0.03 * -1 * latest['direction'])
            # main_order['type'] = 'LIMIT'  # 順張り
            main_order['type'] = 'MARKET'  # 順張り（勢いがいい場合通過している場合もあるかもだが）
            # main_order['tr_range'] = 0.10  # 要検討
            main_order['expected_direction'] = latest['direction'] * -1  # 抵抗方向
            main_order['priority'] = 2  #
            main_order['units'] = order_base_info['units'] * 1
            main_order['name'] = "NOT突破（latest大の突破形状だが突破含み）"

    return {  # take_position_flagの返却は必須。Trueの場合注文情報が必要。
        "take_position_flag": take_position_flag,
        "order_before_finalized": main_order,
        "double_top_strength": double_top_strength,
        "double_top_strength_memo": double_top_strength_memo,
    }


# def peakPatternMain(df_r):
#     # peaksを算出しておく
#     peaks_info = p.peaks_collect_main(df_r[:90], 10)  # Peaksの算出（ループ時間短縮の為、必要最低限のピーク数（＝）を指定）
#     peaks = peaks_info['all_peaks']
#     print("  <対象>")
#     print("  RIVER", peaks[0])
#     print("  TURN ", peaks[1])
#     print("  FLOP3", peaks[2])
#
#     # 初期構想のDoubleTopを検討する
#     inspection_params = {"margin": 0.05, "d": -1, "sl": -1}  # d=expected_direction, sl=Stop(1)orLimit(-1)
#     params = {"tf_ratio_min": 0, "tf_ratio_max": 0.45, "rt_ratio_min": 0.4, "rt_ratio_max": 1,
#               "f3_count": 5, "t_count_min": 2, "t_count_max": 4, "r_count": 2}
#     double_top_ans = DoublePeak({"df_r": df_r, "inspection_params": inspection_params, "params": params, "peaks": peaks})
#     if double_top_ans['take_position_flag']:
#         print(double_top_ans['exe_orders'])
#
#     # ガタガタと進んでいくケース
#     inspection_params = {"margin": 0.05, "d": -1, "sl": -1}  # d=expected_direction, sl=Stop(1)orLimit(-1)
#     params = {"tf_ratio_min": 0.55, "tf_ratio_max": 1, "rt_ratio_min": 0.4, "rt_ratio_max": 1.2,
#               "f3_count": 5, "t_count_min": 3, "t_count_max": 5, "r_count": 3}
#     jagged_move_ans = DoublePeak({"df_r": df_r, "inspection_params": inspection_params, "params": params, "peaks": peaks})
#     if jagged_move_ans['take_position_flag']:
#         print(jagged_move_ans['exe_orders'])
#
#     if double_top_ans['take_position_flag'] or jagged_move_ans['take_position_flag']:
#         print("  ★どちらかが成立",double_top_ans['take_position_flag'], jagged_move_ans['take_position_flag'])
#         if double_top_ans['take_position_flag']:
#             order = double_top_ans['exe_orders']
#             print(" ダブルトップが成立", double_top_ans['take_position_flag'])
#             tk.line_send("ダブルトップが成立", order)
#         else:
#             order = jagged_move_ans['exe_orders']
#             print(" ジグザグムーブが成立", jagged_move_ans['exe_orders'])
#             tk.line_send("ジグザグムーブが成立", order)

# def triplePeaks_pattern(*dic_args):
#     """
#     引数は配列で受け取る。今は最大二つを想定。
#     引数１つ目：ローソク情報(逆順[直近が上の方にある＝時間降順])データフレームを受け取り、範囲の中で、ダブルトップ直前ついて捉える
#     引数２つ目はループ検証時のパラメータ群(ループ検証の時のみ入ってくる）
#     例→params_arr = [
#             {"river_turn_ratio_min": 1, "river_turn_ratio": 1.3, "turn_flop_ratio": 0.6, "count": 2, "gap_min": 0, "gap": 0.02, "margin": 0.05, "sl": 1, "d": 1},
#             {"river_turn_ratio_min": 1, "river_turn_ratio": 1.3, "turn_flop_ratio": 0.6, "count": 2, "gap_min": 0, "gap": 0.02, "margin": 0.05, "sl": 1, "d": 1},
#         ]
#     理想形 (ダブルトップ到達前）
#
#     :param df_r:
#     :return:　必須最低限　{"take_position_flag": boolean} の返却は必須。さらにTrueの場合注文情報が必要。
#     """
#     # print(dic_args)
#     print("■3つの力判定")
#     df_r_part = dic_args[0][:90]  # 検証に必要な分だけ抜き取る
#     peaks_info = p.peaks_collect_main(df_r_part, 3)  # Peaksの算出（ループ時間短縮の為、必要最低限のピーク数（＝４）を指定する）
#     peaks = peaks_info['all_peaks']
#
#     # 必要なピークを出す (どれをRiverにするかを判断する）
#     # 一番直近のピークをlatestとするが、
#     # ①latestをriverとして扱う場合 (未確定のriverを扱う）。ただしlatestのCount＝２でないと毎回実施になってしまう)
#     # ②形が確定したriverを扱う場合　でスイッチできるようにする
#     latest_is_river = False
#     if latest_is_river:
#         # ①形の決まっていないlatestをriverとして扱う場合
#         latest = peaks[0]
#         river = peaks[0]  # 最新のピーク（リバーと呼ぶ。このCount＝２の場合、折り返し直後）
#         turn = peaks[1]  # 注目するポイント（ターンと呼ぶ）
#         flop3 = peaks[2]  # レンジ判定用（プリフロップと呼ぶ）
#     else:
#         #　②形が確定したriverを扱う場合
#         latest = peaks[0]  #
#         river = peaks[1]  # 最新のピーク（リバーと呼ぶ。このCount＝２の場合、折り返し直後）
#         turn = peaks[2]  # 注目するポイント（ターンと呼ぶ）
#         flop3 = peaks[3]  # レンジ判定用（プリフロップと呼ぶ）
#     peaks_times = "◇River:" + \
#                   f.delYear(river['time']) + "-" + f.delYear(river['time_old']) + "(" + str(river['direction']) + ")" \
#                                                                                                                   "◇Turn:" + \
#                   f.delYear(turn['time']) + "-" + f.delYear(turn['time_old']) + "(" + str(turn['direction']) + ")" \
#                                                                                                                "◇FLOP三" + \
#                   f.delYear(flop3['time']) + "-" + f.delYear(flop3['time_old']) + "(" + str(flop3['direction']) + ")"
#     print("  <対象>")
#     print("  RIVER", river)
#     print("  TURN ", turn)
#     print("  FLOP3", flop3)
#
#     # (1) ターンを基準に
#     col = "gap"  # 偏差値を使う場合はstdev　gapを使うことも可能
#     # ⓪リバーのターンに対する割合を取得（〇%に小さくなっている事を想定）
#     size_ans = size_compare(river[col], turn[col], 0.1, 0.3)
#     river_turn_gap = round(size_ans['gap'], 3)
#     river_turn_ratio = size_ans['size_compare_ratio']
#     # ①ターンのフロップ３に対する割合を取得（〇%に小さくなっていることを想定）
#     size_ans = size_compare(turn[col], flop3[col], 0.1, 0.3)
#     turn_flop3_gap = round(size_ans['gap'], 3)
#     turn_flop3_ratio = size_ans['size_compare_ratio']
#
#     # (2)条件の設定
#     # フロップターンの関係
#     tf1 = 0.6
#     tf2 = 0.7
#     tf3 = 1.0
#     tf4 = 1.5
#     # ターンリバーの関係
#     tr1_1 = 0.6
#     tr1_2 = 0.9
#     tr1_3 = 1.1
#     tr1_4 = 1.4
#     #
#     tr3_1 = 0.3
#     tr3_2 = 1.0
#     #
#     tr4_1 = 0.9
#     tr4_2 = 1.5
#
#     # (3)判定処理  （マージン、ポジション方向、タイプ、TP、LCを取得する）
#     # ①リバーはターン直後のみを採用。
#     if latest['count'] != 2:
#         print("   River 2以外の為スキップ")
#         return {"take_position_flag": False}
#     # ②フロップターンと、リバーターンの関係で調査する(複雑注意)
#     if turn_flop3_ratio <= tf1:  # ◆微戻りパターン(<40)。順方向に伸びる、一番狙いの形状の為、順張りしたい。
#         # フロップ３とターンの関係
#         #     /\　←微戻り
#         #    /  　
#         #   /
#         if river_turn_ratio <= tr1_1:  # ◇0-60 マージン有、順張りのリバー同方向にオーダー。一番いい形
#             #     /\/ ↑　　　←この形(もう少しリバーの戻りが弱い状態）
#             #    /  　
#             #   /
#             p_type = "t微戻り→r微戻り"
#         elif river_turn_ratio <= tr1_2:  # ◇60-90 順張りのリバー同方向にオーダー。ただしMargin余裕があれば。
#             #     /\/ ↑　←この形（リバーのが殆ど上まで戻っている状態）
#             #    /  　
#             #   /
#             p_type = "t微戻り→rダブルトップ"
#         elif river_turn_ratio <= tr1_3:  # ◇90-110 待機
#             #        /　↑↓？　　 ←ダブルトップを超えた直後を想定
#             #     /\/
#             #    /  　
#             p_type = "t微戻り→r戻り微オーバー"
#         elif river_turn_ratio <= tr1_4:  # ◇110-130 即順張りのリバー同方向にオーダー。ジグザグトレンドと推定
#             #         / ↑　　　　←結構、ダブルトップを超えた直後を想定
#             #        /
#             #     /\/
#             #    /  　
#             p_type = "t微戻り→r戻り強オーバー"
#         else:  # 130以上 待機　（伸びすぎていて、失速の可能性もあるため）
#             #         / ←これが大きすぎる場合
#             #        /
#             #     /\/
#             #    /
#             p_type = "t微戻り→r戻り超強オーバー"
#     elif turn_flop3_ratio <= tf2:  # ◆待機パターン(<70)。戻が半端なため。
#         #     /\ ←この形（リバーのが殆ど上まで戻っている状態）
#         #    /  \　
#         #   /
#         p_type = "t中途半端戻り"
#     elif turn_flop3_ratio <= tf3:  # ◆深戻りパターン(<100)。旗形状やジグザグトレンド(リバー同方向)と推定。
#         #     /\ ←この形（リバーのが殆ど上まで戻っている状態）
#         #    /  \　
#         #   /    \
#         #  /
#         if river_turn_ratio <= tr3_1:  # ◇0-30 逆張りのリバー逆方向。旗形状(大きく上がらない)等のレンジ。ワンチャン、ジグトレ
#             #     /\　　　↓
#             #    /  \　
#             #   /    \/
#             #  /
#             p_type = "tやや深戻り→r微戻り"
#         elif river_turn_ratio <= tr3_2:  # ◇30-100 逆張りのリバー逆方向にオーダー（ターゲットはターン開始位置）ジグザグトレンドと推定
#             #     /\
#             #    /  \  /  ↑
#             #   /    \/
#             #  /
#             p_type = "tやや深戻り→rダブルトップ以下"
#         else:  # ◇100-
#             #            /
#             #     /\    /
#             #    /  \  /  ↑
#             #   /    \/
#             #  /
#             p_type = "tやや深戻り→r戻りオーバー"
#     elif turn_flop3_ratio <= tf4:  # ◆戻り大パターン(<150)。ジグザグトレンド(リバー逆方向)の入口と推定。
#         #     /\
#         #    /  \　
#         #   /    \
#         #         \ ←　ターンが長い
#         if river_turn_ratio <= tr4_1:  # ◇0-90 逆張りのリバー逆方向にオーダー（ターン起点手前）。ジグザグトレンド（リバー逆）と推定
#             #     /\
#             #    /  \    /　↓　　　　
#             #   /    \  /
#             #         \/
#             p_type = "t強戻り→r戻り"
#         elif river_turn_ratio <= tr4_2:  # ◇90-150 即順リバー同方向。リバー強く、ジグザグするにせよ、リバー方向に行くと推定。
#             #              /
#             #     /\      /
#             #    /  \    /　　　　　
#             #   /    \  /
#             #         \/
#             p_type = "t強戻り→r強戻り"
#         else:
#             p_type = "t強戻り→r強すぎる戻り"
#     else:  # ◆待機パターン。戻りが強すぎるため。
#         p_type = "t強戻りすぎる"
#     print(p_type)
#     print("   情報 tf:", turn_flop3_ratio, "(", turn_flop3_gap, ")", "rt:", river_turn_ratio, "(", river_turn_gap, ")",
#           "f_gap:", flop3['gap'], "t_gap:", turn['gap'], "r_gap:", river['gap'])
#
#
#     return {
#         "take_position_flag": False,
#         "exe_orders":0,
#     }
