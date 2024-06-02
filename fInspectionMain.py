import pandas as pd
import threading  # 定時実行用
import time
import datetime
import fTurnInspection as t  # とりあえずの関数集
import tokens as tk  # Token等、各自環境の設定ファイル（git対象外）
import classOanda as classOanda
import making as mk
import fGeneric as f
import fDoublePeaks as dp
import classPosition as classPosition
import fRangeInspection as ri
import fPeakLineInspection as p
oa = classOanda.Oanda(tk.accountIDl, tk.access_tokenl, "live")  # クラスの定義
# now_price_dic = oa.NowPrice_exe("USD_JPY")['data']['mid']
# now_price = now_price_dic['data']['mid']

# 調査として、DoubleやRange等の複数Inspectionを利用する場合、このファイルから呼び出す(一番下）


# 処理時間削減の為、data
def order_information_add(finalized_order):
    """
    強制的に
    カスケードロスカとトレールを入れる。このレンジインスペクションがメイン
    :param finalized_order:
    :return:
    """

    # カスケードロスカ
    finalized_order['lc_change_dic'] = [
            {"lc_change_exe": True, "lc_trigger_range": 0.01, "lc_ensure_range": -0.01},
            {"lc_change_exe": True, "lc_trigger_range": 0.04, "lc_ensure_range": 0.023}
        ]

    # トレール注文を入れる
    finalized_order['tr_range'] = 0.05

    return finalized_order


# その他オーダーに必要な処理はここで記載する
def Inspection_main(df_r):
    """
    主にExeから呼ばれ、ダブル関係の結果(このファイル内のbeforeとbreak)をまとめ、注文形式にして返却する関数
    引数
    "data": df_r ローソク情報(逆順[直近が上の方にある＝時間降順])のみ。
    "use_in_range_inspection" :exeからexeの持っているLowLineやUpperLineを受け取る
        "lower_line"と"upper_line"が含まれる

    :return:
    このリターンの値は、そのまま発注に使われる。（take_position_flagがTrueの場合、exe_orders(配列)のオーダーが入る
        "take_position_flag": True or False
        "exe_orders": オーダーの配列。オーダーについては
        "lower_line": exeのLowerLineを書き換えるため
        "upper_line": exeのupperLineを書き換えるため

    """
    # 現在価格を取得する
    now_price = oa.NowPrice_exe("USD_JPY")['data']['mid']
    now_price = df_r.iloc[0]['open']
    # パラメータから情報を取得する
    flag_and_orders = {
        "take_position_flag": False,
    }
    # （０）Peakデータを取得する(データフレムは二時間半前くらいが良い？？）
    print(" Range調査対象")
    df_r_range = df_r[:35]
    print(df_r_range.head(1))
    print(df_r_range.tail(1))
    peaks_info = p.peaks_collect_main(df_r[:35], 10)  # Peaksの算出（ループ時間短縮の為、必要最低限のピーク数（＝４）を指定する）
    peaks = peaks_info['all_peaks']
    latest = peaks[0]
    river = peaks[1]  # 最新のピーク（リバーと呼ぶ。このCount＝２の場合、折り返し直後）
    turn = peaks[2]  # 注目するポイント（ターンと呼ぶ）
    flop3 = peaks[3]  # レンジ判定用（プリフロップと呼ぶ）
    order_information = {"take_position_flag": False}  # ■何もなかった場合に返すもの（最低限の返却値）
    print("  <対象>:運用モード")
    print("  Latest", latest)
    print("  RIVER", river)
    print("  TURN ", turn)
    print("  FLOP3", flop3)

    if latest['count'] != 2:
        print(" COUNT2以外")
        return {"take_position_flag": 0}

    # （１）RangeInspectionを実施（ここでTakePositionFlagを付与する）
    line_result = ri.find_lines(df_r[:35])  # Lineが発見された場合には、['line_strength']が１以上になる
    latest = line_result['latest_line']
    latest_line = line_result['latest_line']['line_price'] if line_result['latest_line']['line_strength'] != 0 else 0
    upper_line = line_result['upper_info']['line_price'] if line_result['found_upper'] else 0
    lower_line = line_result['lower_info']['line_price'] if line_result['found_lower'] else 0

    # オーダー情報格納（仮）
    upper_over_order = {}
    upper_in_order = {}
    lower_in_order = {}
    lower_over_order = {}
    order_merge = []  # 配列
    comment_now = ""

    if latest['line_strength'] != 0:
        print(line_result)
        # 上下ラインとも見つけられた場合
        if line_result['found_upper'] and line_result['found_lower']:
            # 各値を計算しておく
            latest_direction = line_result['latest_direction']
            now_upper_gap = upper_line - now_price  # プラス値が現在価格が範囲内。マイナス値の場合は現在価格がUpper超え
            now_lower_gap = now_price - lower_line  # プラス値が現在価格が範囲内。マイナス値の場合は現在価格がlower以下
            # UpperもLowerもある場合、二つの間のGapを求める
            line_gap = round(line_result['upper_info']['line_price'] - line_result['lower_info']['line_price'], 3)

            if lower_line < now_price < upper_line:
                # 現在価格がUpper以下Lower以上の範囲にいるかどうか
                if line_gap <= 0.80:
                    # lineの幅が狭い場合。挟むような形でオーダーを出す.
                    comment_now = "  幅が狭いため、向かい合いオーダー"
                    upper_over_order = {"target": upper_line + 0.01, "expected_direction": 1, "tp": 0.02, "lc": 0.04,
                                        "type": "STOP", "units": 15, "decision_price": now_price, "name": "1over"}  #
                    upper_in_order = {"target": upper_line, "expected_direction": -1, "tp": 0.03,
                                      "lc": 0.04, "type": "LIMIT", "units": 10, "decision_price": now_price,
                                      "name": "-1in"}  # tp = line_gap * 0.8
                    lower_in_order = {"target": lower_line, "expected_direction": 1, "tp": 0.03,
                                      "lc": 0.04, "type": "LIMIT", "units": 20, "decision_price": now_price,
                                      "name": "1in"}
                    lower_over_order = {"target": lower_line - 0.01, "expected_direction": -1, "tp": 0.02, "lc": 0.04,
                                        "type": "STOP", "units": 25, "decision_price": now_price, "name": "-1over"}
                else:
                    # lineの幅がそこそこある場合（突き抜ける場合は強い突き抜け)INは折り返し、overは突き抜け 注：if文の関係上、間にある前提
                    from_upper_ratio = now_upper_gap / line_gap  # upperからの割合
                    if from_upper_ratio <= 0.30:
                        comment_now = "  割と上の方。この価格より下に、Lowerまでトラリピ追加"
                        upper_over_order = {"target": upper_line + 0.01, "expected_direction": -1, "tp": 0.02,
                                            "lc": 0.04, "type": "LIMIT", "units": 11, "decision_price": now_price, "name":"1over"}
                        upper_in_order = {"target": now_price - 0.012, "expected_direction": -1, "tp": line_gap * 0.8,
                                          "lc": line_gap * 0.8, "type": "STOP", "units": 12, "decision_price": now_price, "name":"-1in"}
                    elif from_upper_ratio >= 0.070:
                        comment_now = "  割と下の方。この価格より上に、Upperまでトラリピ追加"
                        lower_in_order = {"target": now_price + 0.012, "expected_direction": -1, "tp": 0.03,
                                          "lc": 0.04, "type": "LIMIT", "units": 22, "decision_price": now_price, "name":"1in"}  # tp = line_gap * 0.8
                        lower_over_order = {"target": lower_line - 0.01, "expected_direction": 1, "tp": 0.02,
                                            "lc": 0.04, "type": "LIMIT", "units": 21, "decision_price": now_price, "name": "-1over"}
                    else:
                        comment_now = " 割とさまよっている状態"
                        upper_over_order = {"target": now_price + 0.01, "expected_direction": -1, "tp": upper_line,
                                            "lc": lower_line, "type": "LIMIT", "units": 31, "decision_price": now_price, "name":"1over"}
                        lower_over_order = {"target": now_price - 0.01, "expected_direction": 1, "tp": lower_line,
                                            "lc": upper_line, "type": "LIMIT", "units": 32, "decision_price": now_price, "name":"-2over"}
            else:
                # 現在価格がUpperとLowerの外側にある場合(直近の２足が凄く伸びている場合？？）
                if now_price < lower_line:
                    # \
                    #  \/\/\ ←ここら辺がUpperLower
                    #       \/　←　この折返しで呼ばれる（line突破後なので強い？）ただlineまでは戻る可能性
                    # inはlower側に戻るのを取るオーダー、overは初期のちょい折り返しを目指すオーダー
                    tp = f.cal_at_least(0.03, abs(lower_line - now_price))
                    lower_in_order = {"target": now_price + 0.012, "expected_direction": -1, "tp": tp * 1.2,
                                      "lc": tp * 1.1, "type": "LIMIT", "units": 61, "decision_price": now_price, "name":"1in"}
                    lower_over_order = {"target": now_price - 0.012, "expected_direction": 1, "tp": tp,
                                        "lc": lower_line, "type": "LIMIT", "units": 62, "decision_price": now_price, "name":"-1over"}
                    comment_now = "lower側に既に飛び出ている場合(latest_dirが１）"
                elif now_price > upper_line:
                    #       /\ ←　この折返しで呼ばれる（line突破後なので強い？）ただlineまでは戻る可能性
                    #  /\/\/ ←ここら辺がUpperLower
                    # /      　
                    # inはlower側に戻るのを取るオーダー、overは初期のちょい折り返しを目指すオーダー
                    tp = abs(upper_line - now_price)
                    upper_over_order = {"target": now_price + 0.012, "expected_direction": -1, "tp": tp,
                                        "lc": upper_line, "type": "LIMIT", "units": 71, "decision_price": now_price, "name":"1over"}
                    upper_in_order = {"target": now_price - 0.012, "expected_direction": 1, "tp": tp * 1.2,
                                      "lc": tp * 1.1, "type": "LIMIT", "units": 72, "decision_price": now_price, "name":"-1in"}
                    comment_now = "upper側に既に飛び出ている場合(latest_dirが-１）"


        else:
            # UpperかLowerのいずれかしか見つからなかった場合
            #        発見　
            # Upper〇　　Lower↑　　買い？
            #           Lower↓　　売り？
            # Lower〇   Upper↑　買い？
            #           Upper↓　　売り？　
            # 上の表を実装したいが、それが出来ない間は暫定的にline突き抜けと、現在価格からの発見できない方向へのLine方向へのオーダー
            if line_result['found_upper']:
                # upperが発見されている場合
                if now_price > upper_line:
                    # 現在価格がUpperLineより上の場合（より上へ）
                    comment_now = "Upperのみ（現在価格がUpperより上。より上へ）"
                    upper_over_order = {"target": now_price + 0.01, "expected_direction": -1, "tp": 0.02,
                                        "lc": 0.04, "type": "LIMIT", "units": 41, "decision_price": now_price, "name":"1over"}
                    # upper_in_order = {"target": now_price - 0.012, "expected_direction": -1, "tp": 0.03,
                    #                   "lc": 0.4, "type": "STOP", "units": 42, "decision_price": now_price, "name":"t"}
                else:
                    # 現在価格がUpperLineより下の場合（もう一度Upperに近づく）
                    comment_now = "Upperのみ（現在価格がUpperより下。再度Upperに近づく）"
                    upper_over_order = {"target": now_price + 0.01, "expected_direction": -1, "tp": 0.02,
                                        "lc": 0.04, "type": "LIMIT", "units": 41, "decision_price": now_price, "name":"1over"}
                    # upper_in_order = {"target": now_price - 0.012, "expected_direction": -1, "tp": 0.03,
                    #                   "lc": 0.4, "type": "STOP", "units": 42, "decision_price": now_price, "name":"t"}
            elif line_result['found_lower']:
                # lowerが発見されている場合
                if now_price < lower_line:
                    # 現在価格がLowerLineより下の場合
                    comment_now = "Lowerのみ(現在価格がLowerより下。より下へ。"
                    lower_in_order = {"target": now_price + 0.012, "expected_direction": -1, "tp": 0.03,
                                      "lc": 0.04, "type": "LIMIT", "units": 51, "decision_price": now_price, "name": "-1in"}
                    # lower_over_order = {"target": lower_line - 0.01, "expected_direction": -1, "tp": 0.02,
                    #                     "lc": 0.04, "type": "STOP", "units": 52, "decision_price": now_price,
                    #                     "name": "t"}
                else:
                    comment_now = "Lowerのみ(現在価格がLowerより上。再度Lowerに近づく方向へ"
                    lower_in_order = {"target": now_price + 0.01, "expected_direction": 1, "tp": 0.03,
                                      "lc": 0.04, "type": "LIMIT", "units": 51, "decision_price": now_price, "name":"-1in"}
                    # lower_over_order = {"target": lower_line - 0.01, "expected_direction": -1, "tp": 0.02,
                    #                     "lc": 0.04, "type": "STOP", "units": 52, "decision_price": now_price, "name":"t"}

        if len(upper_over_order):
            order_merge.append(f.order_finalize(upper_over_order))
        if len(upper_in_order):
            order_merge.append(f.order_finalize(upper_in_order))
        if len(lower_in_order):
            order_merge.append(f.order_finalize(lower_in_order))
        if len(lower_over_order):
            order_merge.append(f.order_finalize(lower_over_order))

        print("オーダー表示")

        flag_and_orders = {
            "take_position_flag": True,
            "exe_orders": order_merge,
            "memo": f.str_merge("upper", upper_line, "lower", lower_line, "latest", latest_line, comment_now, now_price)
        }
    else:
        # LINEが発見されない場合は、LINEに関するオーダーは発行しない
        # exe側の更新も行わない
        pass

    # （２）シンプルなダブルトップを見つける
    doublePeak_ans = dp.DoublePeak_4peaks(df_r, peaks)
    if doublePeak_ans['take_position_flag']:
        print(" シンプルDT発見")
        flag_and_orders = doublePeak_ans
        flag_and_orders['memo'] = "DoubleTop4"

    # 【FINAL】
    return flag_and_orders


def Inspection_main2(df_r):
    """
    主にExeから呼ばれ、ダブル関係の結果(このファイル内のbeforeとbreak)をまとめ、注文形式にして返却する関数
    引数
    "data": df_r ローソク情報(逆順[直近が上の方にある＝時間降順])のみ。
    "use_in_range_inspection" :exeからexeの持っているLowLineやUpperLineを受け取る
        "lower_line"と"upper_line"が含まれる

    :return:
    このリターンの値は、そのまま発注に使われる。（take_position_flagがTrueの場合、exe_orders(配列)のオーダーが入る
        "take_position_flag": True or False
        "exe_orders": オーダーの配列。オーダーについては
        "lower_line": exeのLowerLineを書き換えるため
        "upper_line": exeのupperLineを書き換えるため

    """
    # 現在価格を取得する
    now_price = oa.NowPrice_exe("USD_JPY")['data']['mid']
    now_price = df_r.iloc[0]['open']
    # パラメータから情報を取得する
    take_position_flag = False
    flag_and_orders = {
        "take_position_flag": take_position_flag,
    }
    # （０）Peakデータを取得する(データフレムは二時間半前くらいが良い？？）
    print(" Range調査対象")
    df_r_range = df_r[:35]
    print(df_r_range.head(1))
    print(df_r_range.tail(1))
    peaks_info = p.peaks_collect_main(df_r[:35], 10)  # Peaksの算出（ループ時間短縮の為、必要最低限のピーク数（＝４）を指定する）
    peaks = peaks_info['all_peaks']
    latest = peaks[0]
    river = peaks[1]  # 最新のピーク（リバーと呼ぶ。このCount＝２の場合、折り返し直後）
    turn = peaks[2]  # 注目するポイント（ターンと呼ぶ）
    flop3 = peaks[3]  # レンジ判定用（プリフロップと呼ぶ）
    print("  <対象>:運用モード")
    print("  Latest", latest)
    print("  RIVER", river)
    print("  TURN ", turn)
    print("  FLOP3", flop3)

    if latest['count'] != 2:
        print(" COUNT2以外")
        return {"take_position_flag": 0}

    # （１）RangeInspectionを実施（ここでTakePositionFlagを付与する）
    line_result = ri.find_lines_mm(df_r[:35])  # Lineが発見された場合には、['line_strength']が１以上になる
    print("結果")
    print(line_result)

    # upperlineを取得
    upper_line = 0
    if line_result['found_upper']:
        if line_result['upper_line']['line_strength'] >= 2:
            upper_line = line_result['upper_line']['line_price']
        else:
            line_result['found_upper'] = False
    # lowerLineを取得
    lower_line = 0
    if line_result['found_lower']:
        if line_result['lower_line']['line_strength'] >= 2:
            lower_line = line_result['lower_line']['line_price']
        else:
            line_result['found_lower']

    # オーダー情報格納（仮）
    upper_over_order = {}
    upper_in_order = {}
    lower_in_order = {}
    lower_over_order = {}
    order_merge = []  # 配列
    comment_now = ""

    if line_result['latest_flag']:
        # 直近のリバーが、抵抗ラインと判定された場合、即時、抵抗ラインから押し戻される方向にポジションを取る
        comment_now = " 直近の抵抗ラインを発見" + str(line_result['line_direction'])
        resistance_order ={"target": now_price, "expected_direction": line_result['line_direction'] * -1,
                           "tp": 0.10, "lc": 0.04,
                            "type": "MARKET", "units": 15, "decision_price": now_price, "name": "1over"}

    if line_result['found_upper'] and line_result['found_lower']:
        if lower_line < now_price < upper_line:
            # 現在価格がUpper以下Lower以上の範囲にいるかどうか
            comment_now = "  幅が狭いため、向かい合いオーダー"
            upper_over_order = {"target": upper_line + 0.01, "expected_direction": 1, "tp": 0.02, "lc": 0.04,
                                "type": "STOP", "units": 15, "decision_price": now_price, "name": "1over"}  #
            upper_in_order = {"target": upper_line, "expected_direction": -1, "tp": 0.03,
                              "lc": 0.04, "type": "LIMIT", "units": 10, "decision_price": now_price,
                              "name": "-1in"}  # tp = line_gap * 0.8
            lower_in_order = {"target": lower_line, "expected_direction": 1, "tp": 0.03,
                              "lc": 0.04, "type": "LIMIT", "units": 20, "decision_price": now_price,
                              "name": "1in"}
            lower_over_order = {"target": lower_line - 0.01, "expected_direction": -1, "tp": 0.02, "lc": 0.04,
                                "type": "STOP", "units": 25, "decision_price": now_price, "name": "-1over"}
        elif now_price < lower_line:
            comment_now = "  上下ラインありだが、現在価格がlower以下(さらに下がる方向）"
            lower_over_order = {"target": lower_line - 0.01, "expected_direction": -1, "tp": 0.02, "lc": 0.04,
                                "type": "STOP", "units": 25, "decision_price": now_price, "name": "-1over"}
        elif now_price > upper_line:
            comment_now = "  上下ラインありだが、現在価格がupper以上(さらに上がる方向）"
            upper_over_order = {"target": upper_line + 0.01, "expected_direction": 1, "tp": 0.02, "lc": 0.04,
                                "type": "STOP", "units": 15, "decision_price": now_price, "name": "1over"}
    elif not line_result['found_upper'] and line_result['found_lower']:
        # Lowerだけの発見の場合
        if now_price < lower_line:
            comment_now = "  下ラインのみ、現在価格がlower以下(さらに下がる方向）"
            lower_over_order = {"target": lower_line - 0.01, "expected_direction": -1, "tp": 0.02, "lc": 0.04,
                                "type": "STOP", "units": 25, "decision_price": now_price, "name": "-1over"}
        else:
            comment_now = "  下ラインのみ、現在価格がlower以上(LowerLine超えられず上昇に転じている）"
            lower_in_order = {"target": lower_line, "expected_direction": 1, "tp": 0.03,
                              "lc": 0.04, "type": "LIMIT", "units": 20, "decision_price": now_price,
                              "name": "1in"}
    elif line_result['found_upper'] and not line_result['found_lower']:
        # upperだけの発見の場合
        if now_price > upper_line:
            comment_now = "  上ラインのみ、現在価格がupper以上(さらに上がる方向）"
            upper_over_order = {"target": upper_line + 0.01, "expected_direction": 1, "tp": 0.02, "lc": 0.04,
                                "type": "STOP", "units": 15, "decision_price": now_price, "name": "1over"}
        else:
            comment_now = "  上ラインのみ、現在価格がupper以下(upperLine超えられえず、下落に転じている）"
            upper_in_order = {"target": upper_line, "expected_direction": -1, "tp": 0.03,
                              "lc": 0.04, "type": "LIMIT", "units": 10, "decision_price": now_price,
                              "name": "-1in"}

    # RangeOrder共通処理
    if len(upper_over_order):
        order_merge.append(order_information_add(f.order_finalize(upper_over_order)))
        take_position_flag = True
    if len(upper_in_order):
        order_merge.append(order_information_add(f.order_finalize(upper_in_order)))
        take_position_flag = True
    if len(lower_in_order):
        order_merge.append(order_information_add(f.order_finalize(lower_in_order)))
        take_position_flag = True
    if len(lower_over_order):
        order_merge.append(order_information_add(f.order_finalize(lower_over_order)))
        take_position_flag = True

    print("オーダー表示")

    flag_and_orders = {
        "take_position_flag": take_position_flag,
        "exe_orders": order_merge,
        "memo": f.str_merge("upper", upper_line, "lower", lower_line, "now",comment_now, now_price)
    }


    # （２）シンプルなダブルトップを見つける
    # doublePeak_ans = dp.DoublePeak_4peaks(df_r, peaks)
    # if doublePeak_ans['take_position_flag']:
    #     print(" シンプルDT発見")
    #     flag_and_orders = doublePeak_ans
    #     flag_and_orders['memo'] = "DoubleTop4"

    # 【FINAL】
    return flag_and_orders
