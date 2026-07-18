import datetime  # 日付関係
import json
from plotly.subplots import make_subplots  # draw_graph
import plotly.graph_objects as go  # draw_graph

basic_unit = 1000


class CurrencyPair:
    def __init__(
            self,
            name: str,
            pip_value: float,
            round_keta: int | None = None,
            price_min: float | None = None,
            price_max: float | None = None,
            spread_limit_pips: float = 1.1,
    ):
        self.name = name
        self.pip_value = pip_value
        self.round_keta = round_keta if round_keta is not None else self.default_round_keta(pip_value)
        self.price_min = price_min
        self.price_max = price_max
        self.spread_limit_pips = spread_limit_pips

    @staticmethod
    def default_round_keta(pip_value):
        return 3 if pip_value >= 0.01 else 5

    def round_price(self, price):
        return round(price, self.round_keta)

    def price_to_str(self, price):
        return str(self.round_price(price))

    def pips_to_price(self, pips: int | float) -> float:
        return self.round_price(pips * self.pip_value)

    def price_to_pips(self, price_diff: float) -> float:
        return round(price_diff / self.pip_value, 2)

    def is_price(self, value: int | float) -> bool:
        if self.price_min is None or self.price_max is None:
            return False
        return self.price_min <= float(value) <= self.price_max

    def exchange(self, unknown_num):
        if unknown_num >= self.pip_value * 100:
            result = round(unknown_num, 2)
        else:
            result = self.price_to_pips(unknown_num)
        return result


USD_JPY = CurrencyPair("USD_JPY", 0.01, 3, price_min=80, price_max=200, spread_limit_pips=1.1)
EUR_USD = CurrencyPair("EUR_USD", 0.0001, 5, price_min=0.5, price_max=2.0, spread_limit_pips=1.5)
AUD_USD = CurrencyPair("AUD_USD", 0.0001, 5, price_min=0.3, price_max=1.5, spread_limit_pips=1.8)

CURRENCY_PAIRS = {
    USD_JPY.name: USD_JPY,
    EUR_USD.name: EUR_USD,
    AUD_USD.name: AUD_USD,
}


def currency_pair(pair_name: str) -> CurrencyPair:
    if pair_name not in CURRENCY_PAIRS:
        raise ValueError(f"Unsupported currency pair: {pair_name}")
    return CURRENCY_PAIRS[pair_name]


def calculate_units(
        pair_info: CurrencyPair,
        lc_range: float,
        risk_yen: float = 500,
        rounding_tag: str = "s",
        usd_jpy_rate: float | None = None,
) -> int:
    """Calculate order units from the permitted loss and stop-loss distance."""
    lc_pips = max(pair_info.price_to_pips(lc_range), 0.000000001)
    if pair_info.name == "USD_JPY":
        yen_per_pip_per_unit = pair_info.pip_value
    elif pair_info.name in ("EUR_USD", "AUD_USD"):
        if usd_jpy_rate is None or float(usd_jpy_rate) <= 0:
            raise ValueError(pair_info.name + "のunits計算にはUSD_JPY価格が必要です")
        yen_per_pip_per_unit = pair_info.pip_value * float(usd_jpy_rate)
    else:
        raise ValueError("Unsupported currency pair: " + pair_info.name)

    units = int(risk_yen / (lc_pips * yen_per_pip_per_unit))

    if rounding_tag == "l":
        units = int(5 * round(units / 5))
    elif rounding_tag == "s":
        units = int(5 * round((units - 1) / 5) + 1)

    return units


currentPair = USD_JPY


def set_current_pair(pair_name: str) -> CurrencyPair:
    global currentPair
    currentPair = currency_pair(pair_name)
    return currentPair


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
        if len(str(item)) == 0:
            continue
        message = message + " " + str(item)
    return message


def str_to_time(str_time):
    """
    時刻（文字列 yyyy/mm/dd hh:mm:mm）をDateTimeに変換する。
    何故かDFないの日付を扱う時、isoformat関数系が使えない。。なぜだろう。
    :param str_time:
    :return:
    """
    if isinstance(str_time, datetime.datetime):
        # すでにdatetime → 何もしない
        time_dt = str_time
    else:
        time_dt = datetime.datetime(int(str_time[0:4]),
                                    int(str_time[5:7]),
                                    int(str_time[8:10]),
                                    int(str_time[11:13]),
                                    int(str_time[14:16]),
                                    int(str_time[17:19]))
    return time_dt


def str_to_filename(str_time):
    """
    時刻（文字列 yyyy/mm/dd hh:mm:mm）をファイル名に利用できる数字の羅列にする
    何故かDFないの日付を扱う時、isoformat関数系が使えない。。なぜだろう
    :param str_time:
    :return:
    """
    time_file_name = str_time[0:4] + str_time[5:7] + str_time[8:10] + str_time[11:13] + str_time[14:16] + str_time[17:19]
    return time_file_name


def time_to_str(dt_time):
    """
    DateTimeを文字列にする（ファイル名にしたりしたい時用）
    2024-08-10 19:40:00の形式を、20240810194000にする
    """
    ans = dt_time.strftime("%Y%m%d%H%M%S")
    # print("時刻を文字に変換テスト")
    return ans

def str_to_time_hms(str_time):
    """
    時刻（文字列：2023/5/24  21:55:00　形式）をDateTimeに変換する。
    基本的には表示用。時刻だけにする。
    :param str_time:
    :return:
    """
    time_str = str_time[11:13] + ":" + str_time[14:16] + ":" + str_time[17:19]

    return time_str

def str_to_time_short(str_time):
    """
    時刻（文字列：2023/5/24  21:55:00　形式）を　0524_21:55の形にする
    :param str_time:
    :return:
    """
    dt = datetime.datetime.strptime(str_time, "%Y/%m/%d  %H:%M:%S")

    # 必要な形式に変換
    result = dt.strftime("%m%d_%H:%M")

    return result


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
        r = 1
    else:
        later_time = time2
        older_time = time1
        r = -1
    gap_abs = later_time - older_time  # 正の値が保証された差分
    # gap = time1 - time2  # 渡されたものをそのまま引き算（これエラーになりそうだから消しておく）

    return {
        "gap_abs": gap_abs.total_seconds(),
        "gap": gap_abs.total_seconds() * r,
        "gap_abs_min": round(gap_abs.seconds / 60, 1)
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
    day = day[0].replace("0", "")  # 1/1  先頭の０だけ取る
    time = now_str[11:19]  # 09:10
    day_time = day + "_" + time
    return day_time  # 文字列型の日付（秒まであり）を返す


def now_df_format():
    """
    現在時刻を短縮系で返す
    :return:
    """
    now_str = f'{datetime.datetime.now():%Y/%m/%d %H:%M:%S}'
    return now_str


def delYear(original_time):
    """
    現在時刻を短縮系で返す（年を消す）
    :param original_time: 年月日をあらわした文字配列
    :return:
    """
    # 2023/01/01 09:10:12 ⇒ 1/1 09:10
    day = original_time[5:10]  # 01/01
    day = day.replace("0", "")  # 1/1
    time = original_time[11:16]  # 09:10
    day_time = day + " " + time
    return str(day_time)


def delYearDay(original_time):
    """
    現在時刻を短縮系で返す⇒19:14
    :param original_time: 年月日をあらわした文字配列
    :return:
    """
    # 2023/01/01 09:10:12　⇒　9:10　
    # print(" 渡された値", original_time)
    day = original_time[5:10]  # 01/01
    day = day.replace("0", "")  # 1/1
    time = original_time[11:16]  # 09:10
    return str(time)


def print_arr(*arr):
    """
    配列型を渡すと、それをわかりやすく表示する
    :param arr[0]  表示したい配列
    :param arr[1] 半角スペース何個分インデントするか。していない場合は4個がデフォ。半角数字で来る（任意）
    :return:
    """
    if len(arr) == 2:
        # インデントが指定されている
        indent = ""
        for i in range(arr[1]):
            indent = indent + " "
    else:
        indent = " "

    # 実表示 arr[0] が本体
    for i in range(len(arr[0])):
        # print("ー",  i,"ーーーーーーーーーーーーーーーーー")
        print(indent, i, arr[0][i])
    # print("↑ーーーーーーーーーーーーーーーーーーーーーーー")


def print_peaks(peaks, keys=None, indent_spaces=1):
    """
    peaks配列を渡して、指定したキーのみを改行表示する。
    :param peaks: peaksのリスト
    :param keys: 表示したいキーのリスト。Noneならすべて表示する。
    :param indent_spaces: 行頭のインデント文字数
    :return:
    """
    print("print   ")
    keys = [
        "latest_time_jp",
        "oldest_time_jp",
        "direction",
        "latest_body_peak_price",
        # "oldest_body_peak_price",
        # "latest_wick_peak_price",
        # "oldest_wick_peak_price",
        "peak_strength",
        "count",
    ]
    if keys is None:
        keys = []

    if not isinstance(peaks, (list, tuple)):
        peaks = [peaks]

    indent = " " * indent_spaces
    for i, peak in enumerate(peaks):
        if isinstance(peak, dict):
            if keys:
                items = [f"'{key}': {repr(peak.get(key))}" for key in keys]
                print(indent + str(i) + ", " + ", ".join(items))
            else:
                print(indent + str(i) + ", " + ", ".join([f"'{k}': {repr(v)}" for k, v in peak.items()]))
        else:
            print(indent + str(i), peak)


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


def time_to_euro_iso(jp_time):
    """
    JPtimeを受け取り、それをユーロタイムのISO形式に変換する
    OandaAPIでデータを抜き取れる形
    """
    euro_time = jp_time - datetime.timedelta(hours=9)
    euro_time_iso = str(euro_time.isoformat()) + ".000000000Z"

    return euro_time_iso


