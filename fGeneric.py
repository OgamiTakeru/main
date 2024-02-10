import datetime  # 日付関係
import json
from plotly.subplots import make_subplots  # draw_graph
import plotly.graph_objects as go  # draw_graph


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
        print(i, arr[i])
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



