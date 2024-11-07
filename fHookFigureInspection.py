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
import fResistanceLineInspection as ri

oa = oanda_class.Oanda(tk.accountIDl, tk.access_tokenl, "live")  # クラスの定義


def parallel_move(dic_args):
    """
    だんだんと上がっていく（下がっていく）ムーブを取得したい
    """
    # print(dic_args)
    ts = "    "
    t6 = "      "
    print(ts, "■パラレルムーブ判定関数")
    result_info = {
        "take_position_flag": False,
        "expected_direction": 1,
    }
    # (1)ピークスを取得（引数か処理）。この関数ではPeaksの情報を元にし、Dfは使わない。
    # ①必要最低限の項目たちを取得する
    fixed_information = cf.information_fix(dic_args)  # DFとPeaksが必ず返却される
    # 情報の取得
    df_r = fixed_information['df_r']
    peaks = fixed_information['peaks']

    # ■ピーク中央値の移動線を検討する
    # ■■MiddlePriceを追加する
    for i, item in enumerate(peaks):
        item['middle_price'] = round((item['peak'] + item['peak_old']) / 2, 3)
    # ■■MiddlePriceの遷移を確認する
    peak_count = 0
    for i, item in enumerate(peaks):
        if i == 0:
            # latestの中央値は無視
            peak_count = 1
            continue
        # 解析
        later_middle_price = peaks[i]['middle_price']
        older_middle_price = peaks[i+1]['middle_price']
        gap = later_middle_price - older_middle_price
        # print(older_middle_price, "⇒", later_middle_price)
        # print(gap)

        # 長い移動があったときは、怪しい。
        if item['count'] >= 5:
            print(t6, "カウント大のため、ノーカン", item['time'])
            break

        # 本ループ
        if i == 1:
            # 初回の上下方向を登録
            first_gap = gap
            peak_count += 1
            print(t6, "初回([0]をのぞくと2個目）", peak_count, peaks[i+1]['time'], "-", peaks[i+1]['time_old'], ",", peaks[i]['time'], "-", peaks[i]['time_old'],gap)
        else:
            if first_gap == 0:
                first_gap = gap
            print(item)

            if gap < 0 and first_gap < 0:
                # マイナスで、なおかつ最初と同じ方向だった場合、
                peak_count += 1
                print(t6, "-", peak_count, peaks[i+1]['time'], "-", peaks[i+1]['time_old'], ",", peaks[i]['time'], "-", peaks[i]['time_old'])
            elif gap > 0 and first_gap > 0:
                peak_count += 1
                print(t6, "+", peak_count, peaks[i+1]['time'], "-", peaks[i+1]['time_old'], ",", peaks[i]['time'], "-", peaks[i]['time_old'])
            else:
                print(t6, "異なる", peak_count, peaks[i+1]['time'], "-", peaks[i+1]['time_old'], ",", peaks[i]['time'], "-", peaks[i]['time_old'])
                break
    # ■■カウントやサイズを検証する
    peak_count_sucusess = 0
    for i, item in enumerate(peaks):
        # ■■■サイズを検討（一つでも15ピップスを超えていたら、無効とする
        if 0.05 >= item['gap'] >= 0.15:
            peak_count_sucusess = 0  # 無効にするために、とりあえず判定に使う数字を０にしてしまう。
            print(t6, "サイズオーバー(or未満)が発生", item['time'])
            break
        # ■■■カウントを検証
        if i == peak_count + 1:
            # 調査範囲は、ミドル推移が続いている分のみ（カウント＋１の数字が適正）
            break
        if 3 <= item['count']:  # <= 6:
            print(t6, "合格", item['time'], i)
            peak_count_sucusess += 1
        else:
            print(t6, "範囲不合格", item['time'], i)
            pass
    # ■■判定
    answer = False
    if 5 >= peak_count >= 3 and 4 >= peak_count_sucusess >= 3:  # 継続して発生するため、初回(4,3)と二回目(5,4)のみ検出にする。
        print(t6, "傾向性のある上昇", peak_count, peak_count_sucusess)
        answer = True
        pass
    else:
        print(t6, "傾向性なし", peak_count, peak_count_sucusess)
        return result_info

    # expected_directionを求める
    if first_gap == 0:
        expected_direction = 1  # ０の場合、０で割れないエラーが発生する
    else:
        expected_direction = first_gap/abs(first_gap)

    return {
        "take_position_flag": answer,
        "expected_direction": expected_direction
    }


def hook_figure_inspection(dic_args):
    """
    フック形状を求める（ダブルピークの前段階の別の話）
    LINEのストレングスも利用する
    基本的にレイテストとリバーでのみの比較となる
    レイテストの方向に、成り行きで順張りをとるかの判断基準がメイン
    """
    # print(dic_args)
    ts = "    "
    t6 = "      "
    print(ts, "■フック判定関数")
    result_info = {
        "take_position_flag": False,
        "expected_direction": 1,
    }
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

    # ■Riverの強度を判定
    river_peak_line_strength = ri.cal_river_strength({"df_r": df_r, "peaks": peaks})
    river_strength = river_peak_line_strength  # いつか辞書が返却されて置き換えたことを想定し、変数を入れ替えておく

    # ■レイテストとリバーの関係を確認
    # ■■レイテストとリバーの比率を確認 (リバーを１として、どのくらいか）
    ratio = latest['gap'] / river['gap']
    if ratio >= 1:
        # 1を超えている場合は、終了
        return result_info
    else:
        print(t6, "割合はクリア", ratio)
        pass

    # ■■リバーのサイズ感を確認（あまりに小さい場合はやめておく）
    if river['gap'] < 0.06:
        # リバーが小さい場合は、終了
        return result_info
    else:
        print(t6, "リバーサイズはクリア", river['gap'])

    if river_strength >= 0.8:
        # リバーのストレングスが強い場合は、まず合格（それ以外不合格）
        result_info['take_position_flag'] = True
    else:
        print(t6, "リバースストレングス弱め")

    return result_info


def main_hook_figure_inspection_and_order(dic_args):
    """
    本番用と練習用でオーダーを分けるために、関数を分割した.
    ダブルピークの判定を実施する
    """
    ts = "    "
    t6 = "      "
    # ①必要最低限の項目たちを取得する
    fixed_information = cf.information_fix(dic_args)  # DFとPeaksが必ず返却される
    # 情報の取得
    df_r = fixed_information['df_r']
    peaks = fixed_information['peaks']

    # ■各調査を実施
    # ■■平行移動の確認
    parallel_move_info = parallel_move({"df_r": df_r, "peaks": peaks})

    # ■■フック形状の確認
    hook_info = hook_figure_inspection(dic_args)

    # 結果の表示
    print(t6, "パラレル", parallel_move_info['take_position_flag'], "フック", hook_info['take_position_flag'])

    # ■オーダーの作成(パラレル優先。）
    take_position_flag = False
    # now_price = cf.now_price()  # 現在価格の取得　★これのせいで謎の遅延（print順がテレコになる）が発生することがある。謎！
    now_price = peaks[0]["peak"]
    order_base_info = cf.order_base(now_price,  df_r.iloc[0]['time_jp'])  # オーダーの初期辞書を取得する(nowPriceはriver['latest_price']で代用)

    if parallel_move_info['take_position_flag']:
        # 基本は順張り。
        if peaks[0]["direction"] == parallel_move_info['expected_direction']:
            type_str = "STOP"
        else:
            type_str = "LIMIT"
        main_order = copy.deepcopy(order_base_info)
        main_order['target'] = 0.015
        main_order['tp'] = 0.10
        main_order['lc'] = 0.10  # * line_strength  # 0.09  # LCは広め
        main_order['type'] = type_str  #
        # main_order['type'] = 'MARKET'  #
        main_order['expected_direction'] = parallel_move_info['expected_direction']  # 突破方向
        main_order['priority'] = 1.9  # かなり高め。ダブルトップブレイク以外には割り込まれない
        main_order['units'] = order_base_info['units'] * 1
        main_order['name'] = "パラレルムーブ"
        take_position_flag = False
    elif hook_info['take_position_flag']:
        main_order = copy.deepcopy(order_base_info)
        main_order['target'] = 0.015
        main_order['tp'] = 0.02
        main_order['lc'] = 0.01  # * line_strength  # 0.09  # LCは広め
        main_order['type'] = 'STOP'  # 順張り（勢いがいい場合通過している場合もあるかもだが）
        # main_order['type'] = 'MARKET'  # 順張り（勢いがいい場合通過している場合もあるかもだが）
        main_order['expected_direction'] = peaks[0]["direction"]  # 突破方向
        main_order['priority'] = 1.9  # かなり高め。ダブルトップブレイク以外には割り込まれない
        main_order['units'] = order_base_info['units'] * 1
        main_order['name'] = "フック形状（リヴァー強め）"
        take_position_flag = False
    else:
        main_order = copy.deepcopy(order_base_info)
        main_order['target'] = now_price  # 0.015
        main_order['tp'] = 0.03
        main_order['lc'] = 0.03  # * line_strength  # 0.09  # LCは広め
        # main_order['type'] = 'STOP'  # 順張り（勢いがいい場合通過している場合もあるかもだが）
        main_order['type'] = 'MARKET'  # 順張り（勢いがいい場合通過している場合もあるかもだが）
        main_order['expected_direction'] = peaks[0]["direction"]  # 突破方向
        main_order['priority'] = 1.9  # かなり高め。ダブルトップブレイク以外には割り込まれない
        main_order['units'] = order_base_info['units']
        main_order['name'] = "通常フック形状"
        take_position_flag = False

    finalized_order = cf.order_finalize(main_order)
    return {
        "take_position_flag": take_position_flag,
        "exe_orders": [finalized_order],
        "for_inspection_dic": {}
    }


def main_hook_figure_inspection_and_order_practice(dic_args):
    """
    本番用と練習用でオーダーを分けるために、関数を分割した.
    ダブルピークの判定を実施する
    """
    ts = "    "
    t6 = "      "
    # ①必要最低限の項目たちを取得する
    fixed_information = cf.information_fix(dic_args)  # DFとPeaksが必ず返却される
    # 情報の取得
    df_r = fixed_information['df_r']
    peaks = fixed_information['peaks']

    # ■各調査を実施
    # ■■平行移動の確認
    parallel_move_info = parallel_move({"df_r": df_r, "peaks": peaks})

    # ■■フック形状の確認
    hook_info = hook_figure_inspection(dic_args)

    # 結果の表示
    print(t6, "パラレル", parallel_move_info['take_position_flag'], "フック", hook_info['take_position_flag'])

    # ■オーダーの作成(パラレル優先。）
    take_position_flag = False
    now_price = cf.now_price()  # 現在価格の取得
    now_price = peaks[0]['peak']
    order_base_info = cf.order_base(now_price, df_r.iloc[0]['time_jp'])  # オーダーの初期辞書を取得する(nowPriceはriver['latest_price']で代用)

    if parallel_move_info['take_position_flag']:
        # 基本は順張り。
        if peaks[0]["direction"] == parallel_move_info['expected_direction']:
            type_str = "STOP"
        else:
            type_str = "LIMIT"
        main_order = copy.deepcopy(order_base_info)
        main_order['target'] = 0.015
        main_order['tp'] = 0.5
        main_order['lc'] = 0.08  # * line_strength  # 0.09  # LCは広め
        main_order['type'] = type_str  #
        # main_order['type'] = 'MARKET'  #
        main_order['expected_direction'] = parallel_move_info['expected_direction']  # 突破方向
        main_order['priority'] = 1.9  # かなり高め。ダブルトップブレイク以外には割り込まれない
        main_order['units'] = order_base_info['units'] * 1
        main_order['name'] = "パラレルムーブ"
        take_position_flag = False
    elif hook_info['take_position_flag']:
        main_order = copy.deepcopy(order_base_info)
        main_order['target'] = 0.015
        main_order['tp'] = 0.5
        main_order['lc'] = 0.08  # * line_strength  # 0.09  # LCは広め
        main_order['type'] = 'STOP'  # 順張り（勢いがいい場合通過している場合もあるかもだが）
        # main_order['type'] = 'MARKET'  # 順張り（勢いがいい場合通過している場合もあるかもだが）
        main_order['expected_direction'] = peaks[0]["direction"]  # 突破方向
        main_order['priority'] = 1.9  # かなり高め。ダブルトップブレイク以外には割り込まれない
        main_order['units'] = order_base_info['units'] * 1
        main_order['name'] = "フック形状（リヴァー強め）"
        take_position_flag = True
    else:
        main_order = copy.deepcopy(order_base_info)
        main_order['target'] = now_price  # 0.015
        main_order['tp'] = 0.03
        main_order['lc'] = 0.03  # * line_strength  # 0.09  # LCは広め
        # main_order['type'] = 'STOP'  # 順張り（勢いがいい場合通過している場合もあるかもだが）
        main_order['type'] = 'MARKET'  # 順張り（勢いがいい場合通過している場合もあるかもだが）
        main_order['expected_direction'] = peaks[0]["direction"]  # 突破方向
        main_order['priority'] = 1.9  # かなり高め。ダブルトップブレイク以外には割り込まれない
        main_order['units'] = order_base_info['units']
        main_order['name'] = "通常フック形状"
        take_position_flag = False

    finalized_order = cf.order_finalize(main_order)

    return {
        "take_position_flag": take_position_flag,
        "exe_orders": [finalized_order]
    }


