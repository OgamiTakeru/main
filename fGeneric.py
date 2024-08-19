import datetime  # 日付関係
import json
from plotly.subplots import make_subplots  # draw_graph
import plotly.graph_objects as go  # draw_graph


def draw_graph(mid_df):
    """
    ローソクチャーを表示する関数。
    引数にはDataFrameをとり、最低限Open,hitg,low,Close,Time_jp,が必要。その他は任意。
    """
    order_num = 2  # 極値調査の粒度  gl['p_order']  ⇒基本は３。元プログラムと同じ必要がある（従来Globalで統一＝引数で渡したいけど。。）
    fig = make_subplots(specs=[[{"secondary_y": True}]])  # 二軸の宣言
    # ローソクチャートを表示する
    graph_trace = go.Candlestick(x=mid_df["time_jp"], open=mid_df["open"], high=mid_df["high"],
                                 low=mid_df["low"], close=mid_df["close"], name="OHLC")
    fig.add_trace(graph_trace)

    # PeakValley情報をグラフ化する
    col_name = 'peak_' + str(order_num)
    if col_name in mid_df:
        add_graph = go.Scatter(x=mid_df["time_jp"], y=mid_df['peak_' + str(order_num)], mode="markers",
                               marker={"size": 10, "color": "red", "symbol": "circle"}, name="peak")
        fig.add_trace(add_graph)
    col_name = 'valley_' + str(order_num)
    if col_name in mid_df:
        add_graph = go.Scatter(x=mid_df["time_jp"], y=mid_df['valley_' + str(order_num)], mode="markers",
                               marker={"size": 10, "color": "blue", "symbol": "circle"}, name="valley")
        fig.add_trace(add_graph)
    # 移動平均線を表示する
    col_name = "ema_l"
    if col_name in mid_df:
        add_graph = go.Scatter(x=mid_df["time_jp"], y=mid_df[col_name], name=col_name)
        fig.add_trace(add_graph)
    col_name = "ema_s"
    if col_name in mid_df:
        add_graph = go.Scatter(x=mid_df["time_jp"], y=mid_df[col_name], name=col_name)
        fig.add_trace(add_graph)
    col_name = "cross_price"
    if col_name in mid_df:
        add_graph = go.Scatter(x=mid_df["time_jp"], y=mid_df[col_name],  mode="markers",
                               marker={"size": 5, "color": "black", "symbol": "cross"}, name=col_name)
        fig.add_trace(add_graph)
    # ボリンジャーバンドを追加する
    col_name = "bb_upper"
    if col_name in mid_df:
        add_graph = go.Scatter(x=mid_df["time_jp"], y=mid_df[col_name], name=col_name)
        fig.add_trace(add_graph)
    col_name = "bb_lower"
    if col_name in mid_df:
        add_graph = go.Scatter(x=mid_df["time_jp"], y=mid_df[col_name], name=col_name)
        fig.add_trace(add_graph)
    col_name = "bb_middle"
    if col_name in mid_df:
        add_graph = go.Scatter(x=mid_df["time_jp"], y=mid_df[col_name], name=col_name)
        fig.add_trace(add_graph)

    fig.show()
    # 参考＜マーカーの種類＞
    # symbols = ('circle', 'circle-open', 'circle-dot', 'circle-open-dot','square', 'diamond', 'cross', 'triangle-up')


def str_merge(*msg):
    """
    渡された文字列を結合して返却する
    :return:
    """
    # 関数は可変複数のコンマ区切りの引数を受け付ける
    message = ""
    # 複数の引数を一つにする（数字が含まれる場合があるため、STRで文字化しておく）
    for item in msg:
        message = message + " " + str(item)
    return message


def str_to_time(str_time):
    """
    時刻（文字列 yyyy/mm/dd hh:mm:mm）をDateTimeに変換する。
    何故かDFないの日付を扱う時、isoformat関数系が使えない。。なぜだろう。
    :param str_time:
    :return:
    """
    time_dt = datetime.datetime(int(str_time[0:4]),
                                int(str_time[5:7]),
                                int(str_time[8:10]),
                                int(str_time[11:13]),
                                int(str_time[14:16]),
                                int(str_time[17:19]))
    return time_dt


def str_to_time_hms(str_time):
    """
    時刻（文字列：2023/5/24  21:55:00　形式）をDateTimeに変換する。
    基本的には表示用。時刻だけにする。
    :param str_time:
    :return:
    """
    time_str = str_time[11:13] + ":" + str_time[14:16] + ":" + str_time[17:19]

    return time_str


def cal_str_time_gap(time_str_1, time_str_2):
    """
    データフレームのtime_jp同士の時間の差を求める。
    引数で渡された日時のどちらか大きいか（Later）か判断し、差分を正の値で産出する。
    """
    time1 = str_to_time(time_str_1)
    time2 = str_to_time(time_str_2)

    if time1 > time2:
        later_time = time1
        older_time = time2
    else:
        later_time = time2
        older_time = time1

    gap_abs = later_time - older_time  # 正の値が保証された差分
    # gap = time1 - time2  # 渡されたものをそのまま引き算（これエラーになりそうだから消しておく）

    return {
        "gap_abs": gap_abs
    }



def seek_time_gap_seconds(time1, time2):
    """
    time1 と　time2の時間差を求める（time1とtime2の大小はこの関数で確認する）
    必ず正の値の秒で返却する　（時に直す場合は/3600、分に直す場合は/60)
    :param time1: 文字列型の日付（time_jpと同形式）
    :param time2:
    :return:
    """
    time1_time = str_to_time(time1)
    time2_time = str_to_time(time2)
    if time1_time > time2_time:
        time_gap = time1_time - time2_time
    else:
        time_gap = time2_time - time1_time

    return time_gap.seconds


def now():
    """
    現在時刻を短縮系で返す
    :return:
    """
    now_str = f'{datetime.datetime.now():%Y/%m/%d %H:%M:%S}'
    day = now_str[5:10]  # 0101
    day = day.replace("0", "")  # 1/1
    time = now_str[11:19]  # 09:10
    day_time = day + "_" + time
    return day_time  # 文字列型の日付（秒まであり）を返す


def delYear(original_time):
    """
    現在時刻を短縮系で返す（年を消す）
    :param original_time: 年月日をあらわした文字配列
    :return:
    """
    # 2023/01/01 09:10:12
    day = original_time[5:10]  # 01/01
    day = day.replace("0", "")  # 1/1
    time = original_time[11:16]  # 09:10
    day_time = day + " " + time
    return str(day_time)


def delYearDay(original_time):
    """
    現在時刻を短縮系で返す（年月を消す）
    :param original_time: 年月日をあらわした文字配列
    :return:
    """
    # 2023/01/01 09:10:12
    day = original_time[5:10]  # 01/01
    day = day.replace("0", "")  # 1/1
    time = original_time[11:16]  # 09:10
    return str(time)


def print_arr(arr):
    """
    配列型を渡すと、それをわかりやすく表示する
    :param arr:
    :return:
    """
    for i in range(len(arr)):
        # print("ー",  i,"ーーーーーーーーーーーーーーーーー")
        print("    ", i, arr[i])
    # print("↑ーーーーーーーーーーーーーーーーーーーーーーー")


def print_json(dic):
    """
    Jsonを渡すと、わかりやすく表示する
    :param dic:
    :return:
    """
    print(json.dumps(dic, indent=2, ensure_ascii=False))


def cal_at_least(min_value, now_value):
    # 基本的にはnow_valueを返したいが、min_valueよりnow_valueが小さい場合はmin_vauleを返す
    # min_value = 2pips  now_value=3の場合は、３、min_value = 2pips  now_value=1 の場合　２を。
    if now_value >= min_value:
        ans = now_value
    else:
        ans = min_value
    # print(" CAL　MIN", ans)
    return ans


def cal_at_most(max_value, now_value):
    # 基本的にはnow_valueを返却したいが、max_valueよりnow_vaueが大きい場合はmax_valueを返却
    # max_value = 2pips  now_value=3の場合は2, max_value = 2pips  now_value=1 の場合　1を。
    if now_value >= max_value:
        ans = max_value
    else:
        ans = now_value
    # print(" CAL　MAX", ans)
    return ans


def cal_at_least_most(min_value, now_value, most_value):
    temp = cal_at_least(min_value, now_value)
    ans = cal_at_most(most_value, temp)
    return ans


def print_json(dic):
    print(json.dumps(dic, indent=2, ensure_ascii=False))


def order_base(now_prie):
    """
    引数現在の価格（dicisionPriceの決定のため）、呼ばれたらオーダーのもとになる辞書を返却するのみ
    従来常にBase＝｛price:00・・・｝等書いていたが、行数節約のため、、
    """
    return {
            "target": 0.00,
            "type": "STOP",
            "units": 100,
            "expected_direction": 1,
            "tp": 0.10,
            "lc": 0.10,
            'priority': 0,
            "decision_price": now_prie,
            "name": "",
            "lc_change": []
    }


def order_finalize(order_base):
    """
    オーダーを完成させる。TPRangeとTpPrice、Marginとターゲットプライスのどちらかが入ってれば完成させたい。
    martinとTarget価格をいずれかの受け取り。両方受け取ると齟齬が発生する可能性があるため、片方のみとする
    :param order_base:必須
    order_base = {
        "expected_direction": river['direction'] * -1,  # 必須
        "decision_time": river['time'],  # 任意（アウトプットのエクセルの時に使う　それ以外は使わない）
        "decision_price": river['peak'],  # 必須（特に、targetの指定がRangeで与えられた場合に利用する）
        "target": 価格 or Range で正の値  # 80以上の値は価格とみなし、それ以外ならMarginとする
        "tp": 価格 or Rangeで正の値,  # 80以上の値は価格とみなし、それ以外ならMarginとする
        "lc": 価格　or Rangeで正の値  # 80以上の値は価格とみなし、それ以外ならMarginとする
        #オプション
        ""
    }
    いずれかが必須
    # 注文方法は、Typeでもstop_or_limitでも可能
        "stop_or_limit": stop_or_limit,  # 必須 (1の場合順張り＝Stop,-1の場合逆張り＝Limit
        type = "STOP" "LIMIT" 等直接オーダーに使う文字列
    :return:　order_base = {
        "stop_or_limit": stop_or_limit,  # 任意（本番ではtype項目に置換して別途必要になる。計算に便利なように数字で。）
        "expected_direction": # 検証で必須（本番ではdirectionという名前で別途必須になる）
        "decision_time": # 任意
        "decision_price": # 検証で任意
        "position_margin": # 検証で任意
        "target_price": # 検証で必須　運用で任意(複数Marginで再計算する可能性あり)
        "lc_range": # 検証と本番で必須
        "tp_range": # 検証と本番で必須
        "tp_price": # 任意
        "lc_price": # 任意
        "type":"STOP" or "LIMIT",# 最終的にオーダーに必須（OandaClass）
        "direction", # 最終的にオーダーに必須（OandaClass）
        "price":,  # 最終的にオーダーに必須（OandaClass）
        "trade_timeout_min,　必須（ClassPosition）
        "order_permission"  必須（ClassPosition）
    }
    """
    # ⓪必須項目がない場合、エラーとする
    if not ('expected_direction' in order_base) or not ('decision_price' in order_base):
        print("　　　　エラー（項目不足)", 'expected_direction' in order_base,
              'decision_price' in order_base, 'decision_time' in order_base)
        return -1  # エラー

    # 0 注文方式を指定する
    if not ('stop_or_limit' in order_base) and not ("type" in order_base):
        print(" ★★オーダー方式が入力されていません")
    else:
        if 'type' in order_base:
            if order_base['type'] == "STOP":
                order_base['stop_or_limit'] = 1
            elif order_base['type'] == "LIMIT":
                order_base['stop_or_limit'] = -1
            elif order_base['type'] == "MARKET":
                pass
        elif 'stop_or_limit' in order_base:
            order_base['type'] = "STOP" if order_base['stop_or_limit'] == 1 else "LIMIT"

    # ①TargetPriceを確実に取得する
    if not ('target' in order_base):
        # どっちも入ってない場合、Error
        print("    ★★★target(Rangeか価格か）が入力されていません")
    elif order_base['target'] >= 80:
        # targetが８０以上の数字の場合、ターゲット価格が指定されたとみなす
        order_base['position_margin'] = abs(order_base['decision_price'] - order_base['target'])
        order_base['target_price'] = order_base['target']
        # print("    ★★target 価格指定", order_base['target'], abs(order_base['decision_price']), order_base['target_price'])
    elif order_base['target'] < 80:
        # targetが80未満の数字の場合、PositionまでのMarginが指定されたとみなす（負の数は受け入れない）
        if order_base['target'] < 0:
            print("   targetに負のRangeが指定されています。ABSで使用します（正の値を計算で調整）")
            order_base['target'] = abs(order_base['target'])
        order_base['position_margin'] = order_base['target']
        order_base['target_price'] = order_base['decision_price'] + \
                                     (order_base['target'] * order_base['expected_direction'] * order_base[
                                         'stop_or_limit'])
        # print("    t★arget Margin指定", order_base['target'], abs(order_base['decision_price']), order_base['target_price'])
    else:
        print("     Target_price PositionMarginどっちも入っている")

    # ② TP_priceとTP_Rangeを求める
    if not ('tp' in order_base):
        print("    ★★★TP情報が入っていません（利確設定なし？？？）")
        order_base['tp_range'] = 0  # 念のため０を入れておく（価格の指定は絶対に不要）
    elif order_base['tp'] >= 80:
        # print("    TP 価格指定")
        # 80以上の数字は、Price値だと認識。Priceの設定と、Rangeの算出と設定を実施。
        #    ただし、偶然Target_Priceと同じになる(秒でTPが入ってしまう)可能性あるため、target_price-価格が0.02未満の場合は調整する。
        if abs(order_base['target_price'] - order_base['tp']) < 0.02:
            # 調整を行う（Rangeを最低の0.02に設定し、そこから改めてLC＿Priceを算出する）
            print("  ★★TP価格とTarget価格が同値となったため、調整あり(0.02)")
            order_base['tp_range'] = 0.02
            order_base['tp_price'] = order_base['target_price'] + (
                        order_base['tp_range'] * order_base['expected_direction'])
        else:
            # 調整なしでOK
            order_base['tp_price'] = order_base['tp']
            order_base['tp_range'] = abs(order_base['target_price'] - order_base['tp'])
    elif order_base['tp'] < 80:
        # print("    TP　Range指定")
        # 80未満の数字は、Range値だと認識。Rangeの設定と、Priceの算出と設定を実施
        order_base['tp_price'] = order_base['target_price'] + (order_base['tp'] * order_base['expected_direction'])
        order_base['tp_range'] = order_base['tp']

    # ③ LC_priceとLC_rangeを求める
    if not ('lc' in order_base):
        # どっちも入ってない場合、エラー
        print("    ★★★LC情報が入っていません（利確設定なし？？）")
    elif order_base['lc'] >= 80:
        # print("    LC 価格指定")
        # 80以上の数字は、Price値だと認識。Priceの設定と、Rangeの算出と設定を実施。
        #     ただし、偶然Target_Priceと同じになる(秒でLCが入ってしまう)可能性あるため、target_price-価格が0.02未満の場合は調整する。
        if abs(order_base['target_price'] - order_base['lc']) < 0.02:
            # 調整を行う（Rangeを最低の0.02に設定し、そこから改めてLC＿Priceを算出する）
            print("  ★★LC価格とTarget価格が同値となったため、調整あり(0.02)")
            order_base['lc_range'] = 0.02
            order_base['lc_price'] = order_base['target_price'] - (
                        order_base['lc_range'] * order_base['expected_direction'])
        else:
            # 調整なしでOK
            order_base['lc_price'] = order_base['lc']
            order_base['lc_range'] = abs(order_base['target_price'] - order_base['lc'])
    elif order_base['lc'] < 80:
        # print("    LC RANGE指定")
        # 80未満の数字は、Range値だと認識。Rangeの設定と、Priceの算出と設定を実施
        order_base['lc_price'] = order_base['target_price'] - (order_base['lc'] * order_base['expected_direction'])
        order_base['lc_range'] = order_base['lc']

    # 最終的にオーダーで必要な情報を付与する(項目名を整えるためにコピーするだけ）。LimitかStopかを算出
    order_base['direction'] = order_base['expected_direction']
    order_base['price'] = order_base['target_price']
    order_base['trade_timeout_min'] = order_base['trade_timeout_min'] if 'trade_timeout_min' in order_base else 60
    order_base['order_permission'] = order_base['order_permission'] if 'order_permission' in order_base else True

    return order_base


def dict_compare(dic1, dic2):
    """
    引数の辞書型の中身の項目が同じかどうかを確認する。
    （入れ子になっている場合はそこまで確認しない）
    目的は、関数の返り値を、関数で共通化したい。
    その為、各関数の先頭で返却値の辞書を空で定義し、return直前に過不足ないかを確認する。その際にこの関数を利用する
    :param dic1:
    :param dic2:
    :return:
    """
    # print(dic1,dic2)
    if list(sorted(dic1)) == list(sorted(dic2)):
        # print(" 完全一致")
        return True
    else:
        # print(" 不完全一致")
        return False


def make_trid_order(plan):
    """
    トラップ&リピートイフダンの注文を入れる
    :param plan{
        decision_price: 参考値だが、入れておく
        units: １つのグリッドあたりの注文数。
        (不要）ask_bid: 1の場合買い(Ask)、-1の場合売り(Bid) 引数時は['direction']になってしまっている。
        start_price: 130.150のような小数点三桁で指定。（メモ：APIで渡す際は小数点３桁のStr型である必要がある。本関数内で自動変換）
                     トラリピの最初の価格を指定する
        expected_direction: 1 or -1
        grid: 格子幅の設定。またこれは基本的に各LCRangeとほぼ同等となる。
        start_price_lc: 検討中。
        num: end_priceがない場合は必須。何個分のグリッドを設置。
        end_price:　numがない場合は必須。numと両方ある場合は、こちらが優先。StartPriceからEndPriceまで設置する
        type:　"STOP" 基本はストップになるはずだけれど。

    :return: 上記の情報をまとめてArrで。オーダーミス発生(オーダー入らず)した場合は、辞書内cancelがTrueとなる。
    ■　結果は配列で返される。
    """
    # startPriceを取得する
    if 'start_price' in plan:
        start_price = plan['start_price']
        for_price = start_price  # for分で利用する価格
    else:
        print(" startPriceが入っていません")

    # NUMを求める（そっちの方が計算しやすいから。。endpriceの場合、ループ終了条件が、買いか売りかによって分岐が必要になる）
    if 'num' in plan:
        # numが指定されている場合は、純粋にそれを指定する
        num = plan['num']
    else:
        # numが指定されていない場合、EndpriceとstartPriceとの差分をgridで割った数がNumとなる
        if 'end_price' in plan and plan['end_price'] > 1:
            # エンドプライスが入っており、異常値（rangeを表すような極小値）が入っていないか
            num = int(abs(start_price - plan['end_price']) / plan['grid'])
        else:
            print("Endpriceが入ってない、またはEndpriceが異常値です")

    order_result_arr = []
    for i in range(num):
        # ループでGrid分を加味した価格でオーダーを打っていく。ただし、初回のみはLC価格が例外
        if i == 100:
            # 初回のみLCは広めにする？
            pass
        else:
            # 指定価格の設定
            each_order = order_finalize({  # オーダー２を作成
                "name": "TRID" + str(plan['expected_direction']) + str(i),
                "order_permission": True,
                "decision_price": plan['decision_price'],  # ★
                "target": for_price,  # 価格で指定する
                "decision_time": 0,  #
                "tp": plan['grid'] * 0.8,
                "lc": plan['grid'] * 0.8,
                "units": plan['units'],
                "expected_direction": plan['expected_direction'],
                "stop_or_limit": 1,  # ★順張り
                "trade_timeout_min": 1800,
                "remark": "test",
            })
            # オーダーの蓄積
            order_result_arr.append(each_order)

            # 次のループへ
            for_price = for_price + (plan['expected_direction'] * plan['grid'])

    return order_result_arr




