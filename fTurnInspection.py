import copy

import fGeneric as gene
import sys
from pympler import asizeof
import pandas as pd
import classCandleAnalysis as ca
import classOrderCreate as OCreate
import tokens as tk
from datetime import datetime, timedelta
import requests

this_file_line_send = False
gl_previous_exe_df60_row = None
gl_previous_exe_df60_order_time = None
gl_previous_bb_h1_class = None
gl_latest_trend_trigger_time = None

gl_unis_std = 0.1

class BaseAnalysisClass:
    def __init__(self, candle_analysis):
        print(" ")
        print(" ★★ターンアナリシス")
        # ■■■基本情報の取得
        self.line_send_exe = this_file_line_send
        self.line_send_mes = ""
        self.s = "    "
        self.oa = candle_analysis.base_oa
        self.ca = candle_analysis
        self.ca5 = self.ca.candle_class  # peaks以外の部分。cal_move_ave関数を使う用
        self.peaks_class = self.ca.peaks_class  # peaks_classだけを抽出
        self.ca60 = self.ca.candle_class_hour
        self.peaks_class_hour = self.ca.peaks_class_hour

        # ■■■基本結果の変数の宣言
        self.take_position_flag = False
        self.exe_order_classes = []
        self.send_message_at_last = ""

    def line_send(self, *msg):
        # 関数は可変複数のコンマ区切りの引数を受け付ける
        message = ""
        # 複数の引数を一つにする（数字が含まれる場合があるため、STRで文字化しておく）
        for item in msg:
            message = message + " " + str(item)
        # 時刻の表示を作成する
        now_str = f'{datetime.now():%Y/%m/%d %H:%M:%S}'
        # メッセージの最後尾に付ける
        message = message + " (" + now_str[5:10] + "_" + now_str[11:19] + ")"
        if len(message) >= 2000:
            print("@@文字オーバー")
            print(message)
            message = "Discord受信許容文字数オーバー" + str(len(message))
        if not self.line_send_exe:
            print("     [Disc(送付無し)]", message)  # コマンドラインにも表示
            return 0
        # ■■■  通常のDiscord送信　■■■　　最悪これ以下だけあればいい
        data = {"content": "@everyone " + message,
                "allowed_mentions": {
                    "parse": ["everyone"]
                }
                }
        requests.post(tk.WEBHOOK_URL_main, json=data)
        print("     [Disc]", message)  # コマンドラインにも表示

    def add_order_to_this_class(self, order_class):
        """

        """
        self.take_position_flag = True
        self.exe_order_classes.append(order_class)
        # print("発行したオーダー2↓　(turn255)")
        # print(order_class.exe_order)


class BbAnalysis:
    """
    initは拡張前のものを利用する
    """
    def __init__(self, candle_analysis, foot, mode="inspection"):
        print(" ")
        print(" ★★BB形状アナリシス")
        # ■■■基本情報の取得
        self.s = "    "
        self.round_digit=3
        self.oa = candle_analysis.base_oa
        self.foot = foot
        self.ca = candle_analysis
        self.latest_time = candle_analysis.d5_df_r.iloc[0]['time_jp']  # 5分足で判断(0行目を利用）
        latest_time_datetime = datetime.strptime(self.latest_time, "%Y/%m/%d %H:%M:%S")
        self.latest_time_60 = candle_analysis.d60_df_r.iloc[0]['time_jp']  # オーダー重複防止に利用

        # ■■■オーダー関係の数字
        self.sp = 0.004  # スプレッド考慮用
        self.base_lc_range = 1  # ここでのベースとなるLCRange
        self.base_tp_range = 1
        # 係数の調整用
        self.lc_adj = 0.7
        self.arrow_skip = 1
        # Unit調整用
        self.units_mini = 0.1
        self.units_reg = 0.5
        self.units_str = 1 * gl_unis_std #0.1
        self.units_hedge = self.units_str

        # ■■■結果等の入力
        self.latest_price_position_in_bb = 1
        self.glass_res = None
        self.trumpet_res = None
        self.is_previous = False
        self.take_position_flag = False
        self.exe_order_classes = []

        # データフレームを取得　足ごとで異なる
        if mode == "live":
            if foot == "H1":
                from_i = from_i_price = 0
                print(self.s, "本番は、1時間足が5分ごとに更新されるため、データフレームの先頭行を使う")
            else:
                from_i = 1
                from_i_price = 0
                print(self.s, "本番でも、5分足は０最初に取得以降更新されないため、iloc[1]から使う")
        else:
            print(self.s, "BBを先頭行は無視して検証する")
            from_i = from_i_price = 1  # データフレームの先頭行は、本番の時は０で常に変動を使うが、検証の時は１にしないと未来になってしまう。

        if foot == "H1":
            # 1時間足の場合
            print(" 1時間足のBB検討")
            self.df_r = candle_analysis.d60_df_r[from_i:]  # 先頭行は生成されたばかりのもの（だが検証時は未来になってしまう）
            self.ave = candle_analysis.candle_class_hour
            self.df_r_include0 = candle_analysis.d60_df_r
            self.peaks_class = self.ca.peaks_class_hour
        elif foot == "M5":
            # 5分足の場合
            print(" 5分足のBB検討")
            self.df_r = candle_analysis.d5_df_r[from_i:]
            self.ave = candle_analysis.candle_class
            self.df_r_include0 = candle_analysis.d5_df_r
            self.peaks_class = self.ca.peaks_class
        else:
            # 該当しない場合、5分足を入れておく
            print(" 5分足のBB検討2")
            self.df_r = candle_analysis.d5_df_r[from_i:]
            self.ave = candle_analysis.candle_class
            self.df_r_include0 = candle_analysis.d5_df_r
            self.peaks_class = self.ca.peaks_class
        # ↓このタイミングで実施する必要がある（検証時はdf_r.iloc[0]が完成済なのでcloseは未来になる。Liveかでcloseが常に更新して使いたい。）
        self.latest_price = candle_analysis.d5_df_r[from_i_price:].iloc[0]['close']  # 必ず5分足のデータでやる(df_rだと1時間足の場合おかしくなる）
        print("latest_priceの確認 (Bb)", self.latest_price, self.latest_time)
        self.bb_shape_main()

    def add_order_to_this_class(self, order_class):
        """

        """
        self.take_position_flag = True
        if isinstance(order_class, (list, tuple)):
            self.exe_order_classes.extend(order_class)
        else:
            self.exe_order_classes.append(order_class)
        # self.exe_order_classes.extend(order_class)

    def make_lc_change_dic(self, dic=None):
        """
        time_afterは秒指定
        """
        s = self.s
        ave = self.ave
        foot = self.foot

        base_dic = [
                # {"exe": True, "time_after": 0, "trigger": 1, "ensure": 1},
                # {"exe": True, "time_after": 600, "trigger": 0.025, "ensure": 0.005},
                # {"exe": True, "time_after": 0, "trigger": 0.04, "ensure": 0.010},
                # {"exe": True, "time_after": 600, "trigger": first_trigger, "ensure": first_ensure},
                # {"exe": True, "time_after": 0, "trigger": 0.08, "ensure": 0.05},
                # {"exe": True, "time_after": 0, "trigger": 0.15, "ensure": 0.1},
                # {"exe": True, "time_after": 0, "trigger": 0.20, "ensure": 0.15},
                # {"exe": True, "time_after": 600, "trigger": 0.40, "ensure": 0.35},
                {"exe": True, "time_after": 2 * 5 * 60, "trigger": 0.60, "ensure": 0.55},
                {"exe": True, "time_after": 2 * 5 * 60, "trigger": 0.70, "ensure": 0.65},
                {"exe": True, "time_after": 2 * 5 * 60, "trigger": 0.80, "ensure": 0.75},
                {"exe": True, "time_after": 2 * 5 * 60, "trigger": 0.90, "ensure": 0.85},
                {"exe": True, "time_after": 2 * 5 * 60, "trigger": 1.00, "ensure": 0.95},
            ]

        if dic is None:
            print(s, s, "dicが空です@lc_change")
            if foot is None:
                # 何も指定がないとき
                print(s, s, "footが空です@lc_change")
                return base_dic
            else:

                if foot == "M5":
                    print(s, s, "foot指定有　5M@lc_change")
                    base_dic = [
                        # {"exe": True, "time_after": 0, "trigger": 0.01,
                        #  "ensure": -1},
                        # {"exe": True, "time_after": 0, "trigger": -1, "ensure": -1 * ave.cal_move_ave(1)},  # ほぼLC
                        {"exe": True, "time_after": 600, "trigger": ave.cal_move_ave(1.7), "ensure": ave.cal_move_ave(1.5)},
                        {"exe": True, "time_after": 600, "trigger": ave.cal_move_ave(2.3), "ensure": ave.cal_move_ave(2)},
                        {"exe": True, "time_after": 600, "trigger": ave.cal_move_ave(3.3), "ensure": ave.cal_move_ave(3)},
                        {"exe": True, "time_after": 600, "trigger": ave.cal_move_ave(4.3), "ensure": ave.cal_move_ave(4)},
                    ]
                elif foot == "H1":
                    print(s, s, "foot指定有 H1@lc_change")
                    base_dic = [
                        # {"exe": True, "time_after": 0, "trigger": -1, "ensure": -1 * ave.cal_move_ave(1)},  # ほぼLC
                        {"exe": True, "time_after": 600, "trigger": 0.07, "ensure": 0.12},
                        {"exe": True, "time_after": 600, "trigger": ave.cal_move_ave(1.8), "ensure": ave.cal_move_ave(1.2)},
                        {"exe": True, "time_after": 600, "trigger": ave.cal_move_ave(2.5), "ensure": ave.cal_move_ave(1.8)},
                        {"exe": True, "time_after": 600, "trigger": ave.cal_move_ave(3.3), "ensure": ave.cal_move_ave(2.6)},
                        {"exe": True, "time_after": 600, "trigger": ave.cal_move_ave(4.3), "ensure": ave.cal_move_ave(3.6)},
                        {"exe": True, "time_after": 600, "trigger": ave.cal_move_ave(5.3), "ensure": ave.cal_move_ave(4.6)},
                        {"exe": True, "time_after": 600, "trigger": ave.cal_move_ave(6.3), "ensure": ave.cal_move_ave(5.6)}
                    ]
                return base_dic

        else:
            return dic + base_dic

    def bb_shape_main(self):
        """
        いくつかの関数の結果をラップアップする
        """
        global gl_latest_trend_trigger_time
        # 変数化
        s = self.s
        df_r = self.df_r  # 0が消されているdf_r
        foot = self.foot

        # (1)現在の価格がBBのどこら辺にあるかを確認する(オーダーの方向を決める）
        self.latest_price_position_in_bb = self.latest_price_position_in_bb_func(df_r)

        # (2)砂時計型の発掘
        glass_res = self.bb_glass_analysis(df_r[:15], True)
        self.glass_res = glass_res

        # (3)トランペット型
        trumpet_res = self.bb_trumpet_analysis(df_r[:15], True)
        self.trumpet_res = trumpet_res
        print("ここまでの結果", self.foot, "Glass", glass_res['is_shape'], "(order:", glass_res['is_ordered'], ")",
              ",Trumpet", trumpet_res['is_shape'], "(order:", trumpet_res['is_ordered'], ")")

        # (4)13時間以内に砂時計かトランペットがあったかどうか
        trend_range_hour = 12
        is_previous = False
        previous_time = ""
        bef_i = 0
        for i in range(trend_range_hour + 1, 1, -1):  # 1からスタートする（０はすでにやっているため）
            # ①砂時計型の確認
            target_df = df_r[i:i + 15]  # 直近から15行（15時間分が範囲）
            loop_glass_res = self.bb_glass_analysis(target_df, False)
            loop_trumpet_res = self.bb_trumpet_analysis(target_df, False)
            if loop_glass_res['is_ordered'] or loop_trumpet_res['is_ordered']:
                is_previous = True
                previous_time = target_df.iloc[0]['time_jp']
                gl_latest_trend_trigger_time = previous_time  # 直近ではっせいしたトレンド時刻を入れておく（glass,trumpet出ない場合はここで入るイメージでOK？）
                bef_i = i
                break  # 13時間以内で見つけたら終了
            else:
                is_previous = False

        self.is_previous = is_previous
        # 表示用（発見されたトレンドの開始点が今より何分前か）
        if previous_time != "":
            gap_min = gene.cal_str_time_gap(previous_time, self.latest_time)['gap_abs_min']
        else:
            gap_min = 0
        print("13足以内のトレンド", is_previous, previous_time, ",", gap_min, "足数的には", bef_i)

        # (5)オーダーを入れる
        if foot == "H1":
            if trumpet_res['is_ordered']:
                self.add_order_to_this_class(trumpet_res['order_class'])
                print("トランペットオーダー登録", foot)
            if glass_res['is_ordered']:
                self.add_order_to_this_class(glass_res['order_class'])
                print("砂時計オーダー登録", foot)
        else:
            if trumpet_res['is_ordered']:
                print("トランペットオーダーあるが、5分足なので登録しない")
            if glass_res['is_ordered']:
                self.add_order_to_this_class(glass_res['order_class'])
                print("砂時計オーダーあるが、5分足なので登録しない")

    def latest_price_position_in_bb_func(self, df_r):
        # 変数化
        s = self.s
        df_r = self.df_r

        # (1)現在の価格がBBのどこら辺にあるかを確認する(オーダーの方向を決める）
        big = df_r.iloc[0]['bb_upper']
        small = df_r.iloc[0]['bb_lower']
        N = df_r.iloc[0]['close']
        diff_big = abs(big - N)
        diff_small = abs(N - small)
        # 判定
        if diff_big < diff_small:
            bb_latest_position_in_bb = 1  # 大きいほうに近い
        else:
            bb_latest_position_in_bb = -1  # 小さいほうに近い

        return bb_latest_position_in_bb

    def bb_glass_analysis(self, df_r, do_print):
        """
        固定された行ではなく、最初のN行の中で、形状を判定する
        （固定された行を使う関数は、S,N,M行の３点を固定し、形状を判定する）
        """
        global gl_latest_trend_trigger_time  # トレンドを確認した初回の時刻を入れておく
        # 変数化
        s = self.s
        # df_r_10 = copy.deepcopy(self.df_r[:15])
        peaks_skip = self.peaks_class.skipped_peaks
        ave = self.ave
        latest_time = self.latest_time
        latest_price = self.latest_price
        latest_price_position_in_bb = self.latest_price_position_in_bb
        foot = self.foot

        # 最後まで処理を実施しない場合
        if pd.isna(df_r.iloc[-1]['bb_range']):
            print("最終行のbb_rangeがNaNのため対象外。（大量データでの検証時に起こりうる）", df_r.iloc[-1]['time_jp'])
            return {
                "is_ordered": False,  # オーダーが起きたもの（
                "is_glass_shape": False,  # longであろうと、通常であろうと、とにかく砂時計型かどうか
                "is_glass_shape_long": False,  # longの場合
                "bb_shape": "glass",
                "is_first_glass_shape": False,
                "order_class": False,
                "is_shape": False  # まとめ用の変数 返却先で使いやすいように
            }
            # return {"bb_shape": ""}  # Noneのまま進むとエラーになるので、ここで終了（リターン）

        # 本処理
        min_idx = df_r["bb_range"].idxmin()  # 最小値の場所を取得
        min_val = df_r.loc[min_idx, "bb_range"]  # 最小値の値を取得
        if df_r.loc[min_idx]['time_jp'] == df_r.iloc[0]['time_jp']:
            # print(s, "先頭が一番小さい⇒これは対象外")
            head_is_minimum = True
        else:
            head_is_minimum = False

        # 判定
        # ② 最小値より前(時系列的には直近側）で1.5倍以上のRangeがある行
        before_rows = df_r.loc[:min_idx - 1]
        before_cond_rows = before_rows[before_rows["bb_range"] >= min_val * 1.23]  # データフレームのミスに気が付く前は1.25
        # ③ 最小値より後で1.4倍以上のRangeがある行
        after_rows = df_r.loc[min_idx + 1:]
        after_cond_rows = after_rows[after_rows["bb_range"] >= min_val * 1.4]

        # 条件を満たすか？
        before_cond = not before_cond_rows.empty
        after_cond = not after_cond_rows.empty
        # 両方を満たす場合True
        result = before_cond and after_cond
        # 最終のカウント
        latest_count = peaks_skip[0]['count']
        if result and not head_is_minimum:
            # 砂時計型にも2種類
            if latest_count <= 4:
                is_glass_shape = True
                is_glass_shape_long = False
            else:
                is_glass_shape = True
                is_glass_shape_long = True
            # 初回の砂時計型か？
            if len(before_cond_rows) == 1:
                is_first_glass_shape = True  # 形が砂時計、かつ、最新
            else:
                is_first_glass_shape = False  # 形は砂時計だが、最新の砂時計ではない
        else:
            is_glass_shape = False
            is_glass_shape_long = False
            is_first_glass_shape = False  # 形も違う

        order_class = None
        is_ordered = False
        if is_first_glass_shape:
            if is_glass_shape and not is_glass_shape_long:
                # 従来の型（turn　Countが4個以内のもの）
                order_class = OCreate.Order({
                    "name": "トレンド 砂時計通常",
                    "current_price": latest_price,
                    "target": 0,
                    "direction": latest_price_position_in_bb,
                    "type": "MARKET",
                    "tp": ave.cal_move_ave(6),  # self.ca60.cal_move_ave(1),
                    "lc": ave.cal_move_ave(1.4),  # + self.ca60.cal_move_ave(1),  # self.ca5.cal_move_ave(2.5),
                    "lc_change": self.make_lc_change_dic(),
                    "units": self.units_str * 1.1,
                    "priority": 11,
                    "decision_time": latest_time,
                    "candle_analysis_class": self.ca,
                    "lc_change_candle_type": foot,
                })
                is_ordered = True
                gl_latest_trend_trigger_time = latest_time
            elif is_glass_shape and is_glass_shape_long:
                # 従来の型ではないが、検証する（長いトレンドの後）
                order_class = OCreate.Order({
                    "name": "トレンド 砂時計Long",
                    "current_price": latest_price,
                    "target": 0,
                    "direction": latest_price_position_in_bb,
                    "type": "MARKET",
                    "tp": ave.cal_move_ave(6),  # self.ca60.cal_move_ave(1),
                    "lc": ave.cal_move_ave(1.4),  # + self.ca60.cal_move_ave(1),  # self.ca5.cal_move_ave(2.5),
                    "lc_change": self.make_lc_change_dic(),
                    "units": self.units_str * 1.1,
                    "priority": 11,
                    "decision_time": latest_time,
                    "candle_analysis_class": self.ca,
                    "lc_change_candle_type": foot,
                })
                is_ordered = True
                gl_latest_trend_trigger_time = latest_time
        if do_print:
            print("　 --BBアナリシス(Flex）")
            print(s, "直近の対象時間", df_r.iloc[0]['time_jp'])
            print(s, "最古の対象時間", df_r.iloc[-1]['time_jp'])
            # print(s, "元々のデータフレーム")
            # print(df_r)
            print(s, "結果:", result, before_cond, after_cond, )
            print(s, "最小Range:", min_val, "(index:", min_idx, ")", df_r.loc[min_idx]['time_jp'])
            print(s, "前の数（1の場合は初めて膨らんだところ）", len(before_cond_rows))
            print(s, "前(直近)の条件を満たす行:", len(before_cond_rows), "行")  # before_cond_rows['time_jp'])
            print(s, "後の条件を満たす行:", len(after_cond_rows), "行")  # after_cond_rows['time_jp'])
            print(s, "latestPeakのカウント", peaks_skip[0]['count'], peaks_skip[0]['latest_time_jp'])
            print(s, "先頭が最小か？", head_is_minimum)
            print(s, "発生時刻", gl_latest_trend_trigger_time)
            print(s, "オーダー判定条件", result, latest_count, "←4より小さいこと", len(before_cond_rows), head_is_minimum, is_first_glass_shape)
            print(s, "最終結果　order:", is_ordered, ",is_glass:", is_glass_shape,
                  ",is_glass_long", is_glass_shape_long, ",first", is_first_glass_shape)

        return {
            "is_ordered": is_ordered,  # オーダーが起きたもの（
            "is_glass_shape": is_glass_shape,  # longであろうと、通常であろうと、とにかく砂時計型かどうか
            "is_glass_shape_long": is_glass_shape_long,  # longの場合
            "bb_shape": "glass",
            "is_first_glass_shape": is_first_glass_shape,
            "order_class": order_class,
            "is_shape": is_glass_shape  # まとめ用の変数 返却先で使いやすいように
        }

    def bb_trumpet_analysis(self, df_r, do_print):
        """
        トランペット形状
        """
        global gl_latest_trend_trigger_time
        # 変数化
        s = self.s
        # df_r_10 = copy.deepcopy(self.df_r[:15])
        peaks_skip = self.peaks_class.skipped_peaks
        ave = self.ave
        latest_time = self.latest_time
        latest_price = self.latest_price
        latest_price_position_in_bb = self.latest_price_position_in_bb
        foot = self.foot

        # 結果格納用
        is_trumpet = False
        is_ordered = False
        is_first = False
        order_class = None

        bb_trumpet = self.bb_shape_with_fixed_row_analysis(0, df_r, do_print)  # 現在での成立を検討する
        bb_trumpet_older = self.bb_shape_with_fixed_row_analysis(1, df_r, do_print)  # 一つ昔の条件で実施(重複防止)

        if bb_trumpet['bb_shape'] == "trumpet":
            if bb_trumpet['bb_shape'] == bb_trumpet_older['bb_shape']:
                is_trumpet = True
                is_first = False
                # print(s, "直近でも成立しているが、その前でも成立する⇒今回はオーダーなし")
            else:
                print(s, "トランペットの初回成立")
                is_trumpet = True
                is_first = True

        if is_trumpet and is_first:
            order_class = OCreate.Order({
                "name": "トレンドtrumpet",
                "current_price": latest_price,
                "target": 0,
                "direction": latest_price_position_in_bb,
                "type": "MARKET",
                "tp": ave.cal_move_ave(6),  # self.ca60.cal_move_ave(1),
                "lc": ave.cal_move_ave(1.4),  # + self.ca60.cal_move_ave(1),  # self.ca5.cal_move_ave(2.5),
                "lc_change": self.make_lc_change_dic(),
                "units": self.units_str * 1.2,
                "priority": 11,
                "decision_time": latest_time,
                "candle_analysis_class": self.ca,
                "lc_change_candle_type": foot,
            })
            is_ordered = True
            gl_latest_trend_trigger_time = latest_time
            # print("オーダーの中身", order_class.exe_order)

        return {
            "order_class": order_class,
            "is_trumpet": is_trumpet,
            "is_first": is_first,
            "is_ordered": is_ordered,
            "is_shape": is_trumpet,
            "bb_shape": bb_trumpet['bb_shape']
        }

    def bb_shape_with_fixed_row_analysis(self, slicer, df_r, do_print):
        """
        BBの形状を見る。
        slicerは、固定する行数を底上げする（ひとつ前の足での成立を確認し、重複でのオーダーを避けたい）
        """
        # (0)共通で利用する変数
        # 変数化
        s = self.s
        # df_r_10 = copy.deepcopy(self.df_r[:15])
        peaks_skip = self.peaks_class.skipped_peaks
        ave = self.ave
        latest_time = self.latest_time
        latest_price = self.latest_price
        latest_price_position_in_bb = self.latest_price_position_in_bb
        foot = self.foot

        # 最後まで処理を実施しない場合
        if pd.isna(df_r.iloc[-1]['bb_range']):
            print("最終行のbb_rangeがNaNのため対象外。（大量データでの検証時に起こりうる）@")
            return {"bb_shape": ""}  # Noneのまま進むとエラーになるので、ここで終了（リターン）

        # （1）平行型の調査　データフレームの固定された行を利用する
        if foot == "H1":
            check_point1 = 0 + slicer  # 直近
            check_point2 = 7 + slicer  # 12足前
            check_point3 = 11 + slicer  # 24足前 ⇒ここはトランペット特化にするため18に
        else:
            # M5の場合(逆トランペットを探したい）
            check_point1 = 0 + slicer  # 直近
            check_point2 = 4 + slicer  # 12足前
            check_point3 = 11 + slicer  # 24足前 ⇒ここはトランペット特化にするため18に
        bb1 = df_r.iloc[check_point1]
        bb2 = df_r.iloc[check_point2]
        bb3 = df_r.iloc[check_point3]

        # BBの広さと、現在の価格の位置関係を抑える
        bb_range = bb1['bb_range']
        bb_upper = bb1['bb_upper']
        bb_lower = bb1['bb_lower']
        bb_current_ratio = 100 * (bb_upper - latest_price) / (bb_upper - bb_lower)
        # 現在の位置関係
        dist_to_A = abs(latest_price - bb_upper)
        dist_to_B = abs(latest_price - bb_lower)
        # 基準を選択（等距離ならA）
        if dist_to_A <= dist_to_B:
            base = "UPPER"
            percent = 100 * (bb_upper - latest_price) / (bb_upper - bb_lower)
        else:
            base = "LOWER"
            percent = 100 * (latest_price - bb_lower) / (bb_upper - bb_lower)
        bb_latest_peak_ratio = 100 * (bb_upper - latest_price) / (bb_upper - bb_lower)

        # 幅が同じでも、移動している場合があるため、三つのラップ率を算出する（直近のBBに対して、何割ラップしているか）
        pairs = [(bb1['bb_lower'], bb1['bb_upper']),
                 (bb2['bb_lower'], bb2['bb_upper']),
                 (bb3['bb_lower'], bb3['bb_upper'])]
        base_start, base_end = pairs[0]
        base_len = base_end - base_start
        results = []
        for i, (start, end) in enumerate(pairs[1:], start=2):
            # 重なり計算
            overlap_start = max(base_start, start)
            overlap_end = min(base_end, end)
            overlap = max(0, overlap_end - overlap_start)

            # 基準区間に対する重なり率（0〜1）
            overlap_rate = overlap / (base_end - base_start)

            # サイズ比（自身 / 基準
            length = end - start
            size_ratio = length / base_len

            # タグ判定
            lower_out = start < base_start
            upper_out = end > base_end
            if lower_out and upper_out:
                tag = "両方に外れている"
            elif lower_out:
                tag = "下に外れている"
            elif upper_out:
                tag = "上に外れている"
            else:
                tag = "内側"

            results.append({
                "index": i,
                "range": round(abs(length), self.round_digit),
                "rap_ratio": round(overlap_rate * 100, 1),  # %
                "size_ratio": round(size_ratio, 2),  # 直近を基準にした、各々のサイズ比率（BBなので2倍くらいなら同じとみなすかも）
                "tag": tag,
                "kukan": f"{start}-{end}"
            })

        # 重なり判定
        r0 = results[0]['rap_ratio']  # ０とついているが、直近を含めない、一番最初という意味
        r1 = results[1]['rap_ratio']
        rap_res = 0
        rap_comment = ""
        t = str(r0) + "," + str(r1)
        sr0 = results[0]['size_ratio']  # ０とついているが、直近を含めない、一番最初という意味
        sr1 = results[1]['size_ratio']
        ts = str(sr0) + "," + str(sr1)
        # サイズ感の処理
        size_res = 0
        bb_shape = ""

        bb_shape_jpn_detail = ""
        bb_trend = ""

        if abs(sr0 - sr1) < 0.3:
            # ■残り二つが同じサイズ
            # ①完全平行系
            if 0.76 <= sr0 <= 1.23 and 0.76 <= sr0 <= 1.23:
                bb_shape = "parallel"
                # ■■ラップ率で傾きを判断
                # if r0 >= 88 and r1 >= 88:
                b = 70
                if r0 >= b and r1 >= b:
                    bb_shape_jpn_detail = "フラット"
                    bb_trend = "range"
                elif r0 >= b and r1 < b:
                    bb_shape_jpn_detail = "直近トレンド（平行折り返し後）"
                    bb_trend = "range"
                elif r0 < b and r1 < b-10 and r0 > r1:
                    bb_shape_jpn_detail = "平行移動のトレンド"
                    bb_trend = "parallel_trend"
                    if bb3['bb_upper'] > bb2['bb_upper']:
                        print("右肩下がり")
                        bb_trend = bb_trend + "get_low"
                    else:
                        print("右肩上がり")
                        bb_trend = bb_trend + "get_high"
                else:
                    bb_shape_jpn_detail = "平行移動のトレンドっぽいが微妙に違う"

            # ②前側平行系(ラッパ型）
            # elif sr0 < 0.73 and sr1 < 0.73:
            elif sr0 < 0.76 and sr1 < 0.76:
                bb_shape = "trumpet"
                # ■■ラップで傾きを判定
                if r0 >= 90 and r1 >= 90:
                    bb_shape_jpn_detail = "ラッパ型トレンドからの発散系"
                    bb_trend = "trend"
                elif r0 < 85:
                    if r1 <= 60:
                        bb_shape_jpn_detail = "ラッパ型トレンド"
                        bb_trend = "trend"
                    else:
                        bb_shape_jpn_detail = "ラッパ型トレンド（前ラップ大）"
                        bb_trend = "trend"
                else:
                    bb_shape_jpn_detail = "ラッパ型中途半端"
            # # ③後側平衡系（収束系）
            # elif sr0 > 1.3 and sr1 > 1.3:
            #     bb_shape = "re-trumpet"
            #     bb_trend = "range"
            #     # ■■ラップで傾きを判定
            #     if r0 >= 85:
            #         if r1 >= 95:
            #             bb_shape_jpn_detail = "逆トランペット"
            #         elif r1 <= 70:
            #             bb_shape_jpn_detail = "逆トランペット＿変動後の収束"
            #         else:
            #             bb_shape_jpn_detail = "逆トランぺット中途半端１"
            #     elif r0 < 85:
            #         if r1 <= 70:
            #             bb_shape_jpn_detail = "逆トランペット＿変動後の収束２"
            #         else:
            #             bb_shape_jpn_detail = "逆トランペット中途半端２"
            else:
                bb_shape = "UnKnown"
        elif sr0 > sr1 + 0.35:
            # ■発散系（直前が最初より明らかに大きい）
            # ①直前が1より小さい（直近が一番大きくなるフラッグ）
            if sr0 < 0.8:
                bb_shape = "bigbang"
                bb_trend = "trend"
                # ■■ラップで傾きを判定
                if r0 >= 90:
                    if r1 >= 90:
                        bb_shape_jpn_detail = "ビッグバン型"
                    else:
                        bb_shape_jpn_detail = "ビッグバン型　初期ちょいずれ"
                else:
                    if r1 >= 90:
                        bb_shape_jpn_detail = "ビッグバン型　トレンドに入りそう"
                    else:
                        bb_shape_jpn_detail = "ビッグバン型　トレンド"
            elif 0.8 <= sr0 <= 1.3:
                bb_shape = "semi_flat_from_small"
                bb_shape_jpn_detail = "semi_flat_from_small"
                bb_trend = "range"
            else:
                bb_shape = "中膨れ系(1時間程度の強変動後)"
                bb_shape_jpn_detail = "中膨れ系（一時間程度の強変動後）"
                bb_trend = "range"
        elif sr1 > sr0 + 0.35:
            # ■収束系
            # ①直前が1より小さい（直近が一番大きくなるフラッグ）
            if sr0 < 0.8:
                bb_shape = "中すぼみ系"
                bb_shape_jpn_detail = "中すぼみ系（一時間程度の強変動）⇒発散？？"
                bb_trend = "trend"
            elif 0.8 <= sr0 <= 1.3:
                bb_shape = "re-trumpet"
                bb_shape_jpn_detail = "semi_flat_from_big"
                bb_trend = "range"
            else:
                bb_shape = "flag"
                # ■■ラップで傾きを判定
                if r0 >= 95:
                    if r1 >= 95:
                        bb_shape_jpn_detail = "フラッグ型　両サイド収束"
                        bb_trend = "trend"
                    else:
                        bb_shape_jpn_detail = "フラッグ型　両サイド収束ちょいずれ"
                        bb_trend = "trend"
                else:
                    if r1 >= 90:
                        bb_shape_jpn_detail = "フラッグ型　ブレイク気味"
                        bb_trend = "trend"
                        # bb_trend = "break"
                    else:
                        bb_shape_jpn_detail = "フラッグ型　トレンド"
                        bb_trend = "trend"

        if do_print:
            if slicer == 0:
                print("　--BBアナリシス(Fixed）")
                # 重複の表示は重くなるので、初回分だけ表示。
                print(s, "ベースとなる直近のBB幅", base_len, "open:", df_r.iloc[0]['open'], df_r.iloc[0]['close'])
                for r in results:
                    print(s, r)
                print(self.s, bb1['time_jp'], bb1['bb_range'], bb1['bb_upper'])
                print(self.s, bb2['time_jp'], bb2['bb_range'], bb2['bb_upper'])
                print(self.s, bb3['time_jp'], bb3['bb_range'], bb3['bb_upper'])
                print(self.s, "【BB形状元々】結果", bb_shape, str(ts), bb_shape_jpn_detail)

        return {
            "bb_shape": bb_shape,  # 実際はサイズのみで判断（ずれは使っていない）
            "bb_shape_jpn_detail": bb_shape_jpn_detail,
            "bb_trend": bb_trend,
            "shape_comment": bb_shape,
            "bb_time": bb1["time_jp"]
        }


class MainAnalysis:
    def __init__(self, candle_analysis, position_control_class=None, mode="inspection"):
        print(" ■メインアナリシス", mode)

        # ■■■基本情報の取得
        if mode == "live":
            from_i = 0
            from_i_price = 0  #
        else:
            from_i = 1
            from_i_price = 1
        self.position_control_class = position_control_class
        self.line_send_exe = this_file_line_send
        self.line_send_mes = ""
        self.s = "    "
        self.round_digit = 3
        self.oa = candle_analysis.base_oa
        self.ca = candle_analysis
        self.ca5 = candle_analysis.candle_class  # peaks以外の部分。cal_move_ave関数を使う用
        self.peaks_class = candle_analysis.peaks_class  # peaks_classだけを抽出
        self.df_r_m5 = candle_analysis.d5_df_r[1:]  # 5分足はひとつ前ので固定！！（Liveでも）
        self.ca60 = candle_analysis.candle_class_hour
        self.peaks_class_hour = candle_analysis.peaks_class_hour
        self.df_r_h1 = candle_analysis.d60_df_r[from_i:]
        self.latest_time = candle_analysis.d5_df_r.iloc[0]['time_jp']  # 5分足で判断(0行目を利用）
        self.latest_price = candle_analysis.d5_df_r.iloc[from_i_price]['close']  # iloc[1]
        self.mode = mode
        self.pair = "USD_JPY"
        print("latest_priceの確認(main_analysis)", self.latest_price, "移動平均", self.ca5.cal_move_ave(1))
        # 抵抗線関係
        self.exist_strong_line = False
        # BB関係
        self.latest_exe_bb_h1_row = None
        self.bb_h1_class = None
        self.bb_m5_class = None
        self.bb5_cross_pattern = 0  # 1が強め、2が強いのあったが折り返し

        # ■■■基本結果の変数の宣言
        self.take_position_flag = False
        self.exe_order_classes = []
        self.send_message_at_last = ""

        # ■■■　現在の勝ち負けの様子
        print("test", self.position_control_class)
        if self.position_control_class is None:
            print("過去の勝ち負けは気にしない（単発のテストのため情報なし）")
        else:
            position_one = self.position_control_class.position_classes[0]  # positionの先頭を取得（どれでもいい）
            p = position_one.history_plus_minus
            print("過去の勝ち負けの履歴", position_one.history_plus_minus)
            if len(p) >= 6:
                print("勝ち負けの直近三個", p[-1], p[-2], p[-3], p[-4], p[-5], p[-6])
            else:
                print("勝ち負けの直近三個", p[-1])

        # ■■■基本情報の表示
        peaks = self.peaks_class.peaks_original
        peaks_skip = self.peaks_class.skipped_peaks_hard
        print(self.s, "<SKIP前>", len(peaks), asizeof.asizeof(peaks))
        gene.print_arr(peaks[:3])
        print("↓")
        gene.print_arr(peaks[-2:])
        print("")

        print(self.s, "<SKIP後＞", len(peaks_skip), asizeof.asizeof(peaks_skip))
        gene.print_arr(peaks_skip[:3])
        print("")

        # print(self.s, "<SKIP前 1h足>", len(self.peaks_class_hour.peaks_original), asizeof.asizeof(self.peaks_class_hour.peaks_original))
        # gene.print_arr(self.peaks_class_hour.peaks_original[:3])
        # print("↓")
        # gene.print_arr(self.peaks_class_hour.peaks_original[-2:])
        # print("")
        #
        # print(self.s, "<SKIP後 1h足＞", len(self.peaks_class_hour.skipped_peaks), asizeof.asizeof(self.peaks_class_hour.skipped_peaks))
        # gene.print_arr(self.peaks_class_hour.skipped_peaks[:3])
        #
        # print(self.s, "<SKIP HARD後 1h足＞", len(self.peaks_class_hour.skipped_peaks_hard), asizeof.asizeof(self.peaks_class_hour.skipped_peaks_hard))
        # gene.print_arr(self.peaks_class_hour.skipped_peaks_hard[:3])

        # ■■■■　以下は解析値等
        # ■■■簡易的な解析値
        peaks = self.peaks_class.peaks_original
        r = peaks[0]
        t = peaks[1]
        f = peaks[2]
        # RiverとTurnの解析
        self.rt = TuneAnalysisInformation(self.peaks_class, 1, "rt")  # peak情報源生成
        # FlopとTurn
        self.tf = TuneAnalysisInformation(self.peaks_class, 2, "tf")  # peak情報源生成
        # preFlopとflopの解析
        self.fp = TuneAnalysisInformation(self.peaks_class, 2, "fp")  # peak情報源生成
        # 各価格に使うかもしれない物
        self.latest_turn_resistance_gap = abs(t['latest_body_peak_price'] - self.peaks_class.latest_price)
        self.latest_flop_resistance_gap = abs(f['latest_body_peak_price'] - self.peaks_class.latest_price)
        self.current_price = self.peaks_class.latest_price

        # 調整用の係数たち
        self.sp = 0.004  # スプレッド考慮用
        self.base_lc_range = 1  # ここでのベースとなるLCRange
        self.base_tp_range = 1
        # 係数の調整用
        self.lc_adj = 0.7
        self.arrow_skip = 1
        # Unit調整用
        self.units_mini = 0.1
        self.units_reg = 0.5
        self.units_str =1 * gl_unis_std #0.1
        self.units_hedge = self.units_str
        # 汎用性高め
        self.lc_change_test = [
            {"exe": True, "time_after": 0, "trigger": 0.01, "ensure": -1},  # ←とにかく、LCCandleを発動させたい場合
        ]

        # ★★★調査実行
        self.main()

    def make_lc_change_dic(self, foot=None, dic=None, types="offence"):
        """
        time_afterは秒指定
        """
        s = self.s
        base_dic_list = [
                {"exe": True, "time_after": 2 * 5 * 60, "trigger": 1.00, "ensure": 0.95},
            ]
        if foot is None:
            # 何も指定がないとき
            print(s, s, "footが空です Error@lc_change")
            return base_dic_list

        # 辞書構築処理
        if foot == "M5":
            print(s, s, "foot指定有　5M@lc_change", types)
            ca = self.ca5
            if types == "safety":
                print(s,s, "safety")
                base_dic_list = [
                    # {"exe": True, "time_after": 600, "trigger": ca.cal_move_ave(1), "ensure": ca.cal_move_ave(1) * -1},
                    {"exe": True, "time_after": 0, "trigger": 0.018, "ensure": 0.006},
                    {"exe": True, "time_after": 0, "trigger": 0.05, "ensure": 0.03},
                ]
            else:
                print(s, s, "offence")
                base_dic_list = [
                    # {"exe": True, "time_after": 600, "trigger": 0.05, "ensure": 0.11},
                    # {"exe": True, "time_after": 0, "trigger": -1, "ensure": -1 * ca.cal_move_ave(1)},  # ほぼLC
                    # {"exe": True, "time_after": 0, "trigger": ca.cal_move_ave(1), "ensure": ca.cal_move_ave(1) * -1},
                    # {"exe": True, "time_after": 0, "trigger": 0.02, "ensure": -0.03},
                    {"exe": True, "time_after": 0, "trigger": 0.05, "ensure": 0.015},
                    {"exe": True, "time_after": 0, "trigger": 0.07, "ensure": 0.03},
                    {"exe": True, "time_after": 0, "trigger": 0.12, "ensure": 0.09},
                    {"exe": True, "time_after": 0, "trigger": 0.16, "ensure": 0.012},
                    {"exe": True, "time_after": 0, "trigger": 0.20, "ensure": 0.19},
                    {"exe": True, "time_after": 0, "trigger": 0.30, "ensure": 0.28},
                    {"exe": True, "time_after": 0, "trigger": 0.40, "ensure": 0.38},
                    # {"exe": True, "time_after": 600, "trigger": ca.cal_move_ave(1.8), "ensure": ca.cal_move_ave(0.2)},
                    # {"exe": True, "time_after": 600, "trigger": ca.cal_move_ave(2.5), "ensure": ca.cal_move_ave(1.8)},
                    # {"exe": True, "time_after": 600, "trigger": ca.cal_move_ave(3.3), "ensure": ca.cal_move_ave(2.6)},
                    # {"exe": True, "time_after": 600, "trigger": ca.cal_move_ave(4.3), "ensure": ca.cal_move_ave(3.6)},
                    # {"exe": True, "time_after": 600, "trigger": ca.cal_move_ave(5.3), "ensure": ca.cal_move_ave(4.6)},
                    # {"exe": True, "time_after": 600, "trigger": ca.cal_move_ave(6.3), "ensure": ca.cal_move_ave(5.6)}
                ]
        elif foot == "H1":
            print(s, s, "foot指定有 H1@lc_change")
            ca = self.ca60
            base_dic_list = [
                # {"exe": True, "time_after": 0, "trigger": -1, "ensure": -1 * ca.cal_move_ave(1)},  # ほぼLC
                {"exe": True, "time_after": 600, "trigger": ca.cal_move_ave(1.7), "ensure": ca.cal_move_ave(1.5)},
                {"exe": True, "time_after": 600, "trigger": ca.cal_move_ave(2.3), "ensure": ca.cal_move_ave(2)},
                {"exe": True, "time_after": 600, "trigger": ca.cal_move_ave(3.3), "ensure": ca.cal_move_ave(3)},
                {"exe": True, "time_after": 600, "trigger": ca.cal_move_ave(4.3), "ensure": ca.cal_move_ave(4)},
            ]

        if dic is not None:
            dic_list = [dic]
            print(s, s, "dicがあるため、dicを先頭に追加して返却@lc_change")
            return dic_list + base_dic_list
        else:
            return base_dic_list

    def line_comment_add(self, *msg):
        message = ""
        # 複数の引数を一つにする（数字が含まれる場合があるため、STRで文字化しておく）
        for item in msg:
            message = message + " " + str(item)

        self.line_send_mes = "\n" + self.line_send_mes + message

    def line_send(self, *msg):
        # 関数は可変複数のコンマ区切りの引数を受け付ける
        message = ""
        # 複数の引数を一つにする（数字が含まれる場合があるため、STRで文字化しておく）
        for item in msg:
            message = message + " " + str(item)
        # 時刻の表示を作成する
        now_str = f'{datetime.now():%Y/%m/%d %H:%M:%S}'
        # メッセージの最後尾に付ける
        message = message + " (" + now_str[5:10] + "_" + now_str[11:19] + ")"
        if len(message) >= 2000:
            print("@@文字オーバー")
            print(message)
            message = "Discord受信許容文字数オーバー" + str(len(message))
        if not self.line_send_exe:
            print("     [Disc(送付無し)]", message)  # コマンドラインにも表示
            return 0
        # ■■■  通常のDiscord送信　■■■　　最悪これ以下だけあればいい
        data = {"content": "@everyone " + message,
                "allowed_mentions": {
                    "parse": ["everyone"]
                }
                }
        requests.post(tk.WEBHOOK_URL_main, json=data)
        print("     [Disc]", message)  # コマンドラインにも表示

    def add_order_to_this_class(self, order_class):
        """

        """
        self.take_position_flag = True
        if isinstance(order_class, (list, tuple)):
            self.exe_order_classes.extend(order_class)
        else:
            self.exe_order_classes.append(order_class)
        # self.exe_order_classes.extend(order_class)
        # print("発行したオーダー2↓　(turn255)")
        # print(order_class.exe_order)

    def main(self):
        """
        ターン直後での判断。
        """
        # 変数化
        global gl_previous_exe_df60_row
        global gl_previous_exe_df60_order_time
        global gl_previous_bb_h1_class

        s = self.s
        df_r = self.df_r_m5  # 場合によって0が消されているdf_r
        candle_analysis = self.ca
        peaks = self.peaks_class.peaks_original
        peaks_skip = self.peaks_class.skipped_peaks_hard
        mode = self.mode
        # 変数化（BB）
        df_h1_row = candle_analysis.d60_df_r.iloc[0]
        bb_h1_class = self.bb_h1_class
        bb_m5_class = self.bb_m5_class

        # ■途中終了判定
        if peaks[1]['gap'] < 0.04:
            print("対象が小さい", peaks[1]['gap'])

        # ■■■BBの形状の調査
        # (1)主に1時間足での調査
        self.bb_m5_class = BbAnalysis(candle_analysis, "M5", mode)  # 5分足は必ず実施
        is_same = (gl_previous_exe_df60_row is not None) and df_h1_row.equals(gl_previous_exe_df60_row)
        if is_same:
            pass
            print("1時間足のデータが同じだった ⇒ これは5分毎で値の変わらない検証で多く起こる")
            self.bb_h1_class = gl_previous_bb_h1_class  # クラスは新規生成されるため、グローバル変数で記録しておく
        else:
            print("データが異なるので調査対象")
            if gl_previous_exe_df60_order_time != candle_analysis.d60_df_r.iloc[0]['time_jp']:
                print("まだオーダーをしていない時間のため調査対象", gl_previous_exe_df60_order_time, candle_analysis.d60_df_r.iloc[0]['time_jp'])
                gl_previous_bb_h1_class = BbAnalysis(candle_analysis, "H1", mode)  # クラスは新規生成されるため、グローバル変数で記録しておく
                self.bb_h1_class = gl_previous_bb_h1_class
                gl_previous_exe_df60_row = candle_analysis.d60_df_r.iloc[0]
                if gl_previous_bb_h1_class.take_position_flag:
                    self.add_order_to_this_class(gl_previous_bb_h1_class.exe_order_classes)  # オーダーを登録
                    gl_previous_exe_df60_order_time = gl_previous_bb_h1_class.latest_time_60  # １H起点のオーダーを入れた時刻を取得（重複オーダー防止用）
            else:
                self.bb_h1_class = gl_previous_bb_h1_class
                print("オーダー済みの時刻", gl_previous_exe_df60_order_time, candle_analysis.d60_df_r.iloc[0]['time_jp'])

        # (2)5分足での調査
        self.bb_cross_analysis(0, mode)  # ０は引数。スタート地点

        # (3)ターン起点
        self.predict_registance_turn_analysis()

        # (4)突然の大本命
        self.simple_turn_analysis()

    def big_move_r_direction_order(self):
        """
        大きい変動が認められた場合、反発オーダーを順張りで、少し戻った位置で設ける。この場合、LCも入れたいなぁ
        """
        peaks = self.peaks_class.peaks_original
        if peaks[1]['gap'] < 0.04:
            print("対象が小さい", peaks[1]['gap'])
            # return default_return_item

        # ■基本的な情報の取得
        # (1)
        r = peaks[0]
        t = peaks[1]
        f = peaks[2]
        comment = "大変動後の反発"

        # target_price = r['latest_body_peak_price'] + (self.sp * t['direction'])
        # order_class1 = OCreate.Order({
        #     "name": comment,
        #     "current_price": self.peaks_class.です！,
        #     "target": self.ca5.cal_move_ave(0.5),  # target_price,
        #     "direction": r['direction'],
        #     "type": "STOP",  # "MARKET",
        #     "tp": self.base_tp_range,  # self.ca5.cal_move_ave(5),
        #     "lc": self.base_lc_range,
        #     "lc_change": self.make_lc_change_dic("M5"),
        #     "units": self.units_str,
        #     "priority": 3,
        #     "decision_time": self.peaks_class.df_r_original.iloc[0]['time_jp'],
        #     "candle_analysis_class": self.ca,
        #     "lc_change_candle_type": "M5",  # M5の場合は、order_classで自動補完されるが、念のため
        # })
        # self.add_order_to_this_class(order_class1)
        # ●ヘッジオーダー
        order_class2 = OCreate.Order({
            "name": comment + "HEDGE",
            "current_price": self.peaks_class.latest_price,
            "target": self.peaks_class.latest_price,  # self.ca5.cal_move_ave(0.4),
            "direction": t['direction'],
            "type": "MARKET",  # "STOP",
            "tp": self.ca5.cal_move_ave(5),  # self.ca5.cal_move_ave(5),
            "lc": self.ca5.cal_move_ave(4),
            "lc_change": self.make_lc_change_dic("M5"),
            "units": self.units_str,
            "priority": 3,
            "decision_time": self.peaks_class.df_r_original.iloc[0]['time_jp'],
            "candle_analysis_class": self.ca,
            "lc_change_candle_type": "M5",  # M5の場合は、order_classで自動補完されるが、念のため
        })
        self.add_order_to_this_class(order_class2)

        # リンケージをたがいに登録する
        # order_class1.add_linkage(order_class2)
        # order_class2.add_linkage(order_class1)

    def bb_cross_analysis(self, from_i, mode):
        """
        BBと交わっている（越えそう）なものが何個連続しているかを検討する
        """
        print("■BB Crossターン")

        # (1)変数化
        # 0 引数候補
        # 1 共通
        s = self.s
        target_df = self.df_r_m5[from_i:15]  # LiveとInspectionで分別済みのデータフレーム。さらにfrom_iで指定可能
        latest_time = self.latest_time
        latest_price = self.latest_price
        ave = self.ca5
        bb_m5 = self.bb_m5_class  # 5分足のBBの情報
        bb_latest_position_in_bb5 = self.bb_m5_class.latest_price_position_in_bb
        bb_h1_class = self.bb_h1_class
        peaks = self.peaks_class.peaks_original
        print(s, "5分足での調査（短期スパン） 1時間足13時間前の有無", bb_h1_class.is_previous, ",方向", self.bb_h1_class.latest_price_position_in_bb)
        print(s, "BBの張り付き方向(5分足）", bb_latest_position_in_bb5)

        # (0)実行しない場合
        if from_i == 0:  # 最初からの想定の場合（5分足のトレンドを見るとかではない場合）
            # 1時間足のトレンド開始が13時間以内、かつ、５分足トレンドと1時間足トレンドが異なる場合（1時間足を優先）
            if bb_h1_class.is_previous and (bb_h1_class.latest_price_position_in_bb != bb_latest_position_in_bb5):
                print(s, "1時間足のトレンドの向きとは異なるため、BBCross無し", bb_h1_class.latest_price_position_in_bb)
                return 0
            # (1-2)終了条件
            # print("BBcross確認", target_df.iloc[0]['time_jp'], target_df.iloc[0]['moves'])
            if mode == "live":
                if float(target_df.iloc[0]['moves']) <= 0.025:
                    print(s, "liveの0行目（直近）で、足が始まった直後ため、BBCross無し", round(float(target_df.iloc[0]['moves']), self.round_digit))
                    return 0
            # (1-3)終了条件 (move条件の後に書く）
            if peaks[0]['count'] == 2:
                print(s, "折り返し直後（直近カウントが２）のため、BBCross無し", peaks[0]['count'])
                return 0
        else:
            # ただこの関数のBBクロスを見たい場合のみ
            print(s, "BBクロスのみを知りたい", target_df.iloc[0]['time_jp'])
            pass

        # (1)BB跨ぎの確認
        # BBを越えていのおカウント
        count = 0
        is_latest_out = False
        i = 0
        for idx, row in target_df[:4].iterrows():
            #
            max_val = row['high']
            min_val = row['low']
            low = min(min_val, max_val)
            high = max(min_val, max_val)
            width = (high - low) or 1e-9  # 0の場合はFalseとされるため、０の場合は極小値を入れる
            res = 0
            if bb_latest_position_in_bb5 == -1:
                b = row['bb_lower']
                # 上側外れ（完全にBB内側） → 0
                if low > b:
                    res = 0.0

                # 一部がはみ出ている状態
                if low <= b <= high:
                    res = (b - low) / width

                # 下側外れ（完全にBBの外側　1以上）
                if high < b:
                    res = 1 + (b - high) / width

            # ---------------------------
            # パターン2（上側外れを割合で表す）
            # ---------------------------
            else:
                b = row['bb_upper']
                # 下側外れ（完全に）BBの内側 → 0
                if high < b:
                    res = 0.0

                # 一部がはみ出ている状態
                if low <= b <= high:
                    res = (high - b) / width

                # 下側外れ（完全にBBの外側）（1以上）
                if low > b:
                    res = 1 + (low - b) / width
            print(s, row['time_jp'], res, "idx", idx)
            print(s, s, "  ", b, high, low)

            # 結果のカウント
            if res >= 0.40:
                count = count + 1
            if res >= 0.4 and i == 0:
                is_latest_out = True  # 直近が越えている
                print(s, "直近もBB越えている")
            # カウンター作動
            i = i + 1
        print(s, "BB40パーセント越え数", count)

        if count == 3:
            order_class1 = OCreate.Order({
                "name": "シンプルBB M5新戻り",
                "current_price": latest_price,
                "target": 0.013,  #  ave.cal_move_ave(0.25),
                "direction": bb_latest_position_in_bb5*-1,
                "type": "LIMIT",  # "MARKET",
                "tp": 0.25,  # ave.cal_move_ave(3),  ,
                "lc": ave.cal_move_ave(1.2),  # width,  # 戻るにして、短めに
                "lc_change": self.make_lc_change_dic("M5"),
                "units": self.units_str * 1.2,
                "priority": 11,
                "decision_time": self.peaks_class.df_r_original.iloc[0]['time_jp'],
                "candle_analysis_class": self.ca,
                "lc_change_candle_type": "M5",
            })
            # オーダーの追加
            self.add_order_to_this_class(order_class1)
            self.bb5_cross_pattern = 2  # 戻りのほう

        # if count == 3 and is_latest_out:  # 3の場合のみ。
        #     order_class1 = OCreate.Order({
        #         "name": "シンプルBB M5",
        #         "current_price": latest_price,
        #         "target": 0.013,  #  ave.cal_move_ave(0.25),
        #         "direction": bb_latest_position_in_bb5,
        #         "type": "LIMIT",  # "MARKET",
        #         "tp": 0.25,  # ave.cal_move_ave(3),  ,
        #         "lc": ave.cal_move_ave(2),  # width,
        #         "lc_change": self.make_lc_change_dic("M5"),
        #         "units": self.units_str * 1.2,
        #         "priority": 11,
        #         "decision_time": self.peaks_class.df_r_original.iloc[0]['time_jp'],
        #         "candle_analysis_class": self.ca,
        #         "lc_change_candle_type": "M5",
        #     })
        #     # オーダーの追加
        #     self.add_order_to_this_class(order_class1)
        #     #
        #     self.bb5_cross_pattern = 1  # 順張りのほう
        # elif count == 3 and not is_latest_out:
        #     print(s, "これはもしかして折り返しが強いかも！！？")
        #     order_class1 = OCreate.Order({
        #         "name": "シンプルBB 戻し M5",
        #         "current_price": latest_price,
        #         "target": 0.015,  #  ave.cal_move_ave(0.25),
        #         "direction": bb_latest_position_in_bb5 * -1,
        #         "type": "STOP",  # "MARKET",
        #         "tp": 0.25,  # ave.cal_move_ave(3),  ,
        #         "lc": ave.cal_move_ave(2),  # width,
        #         "lc_change": self.make_lc_change_dic("M5"),
        #         "units": self.units_str * 1.2,
        #         "priority": 11,
        #         "decision_time": self.peaks_class.df_r_original.iloc[0]['time_jp'],
        #         "candle_analysis_class": self.ca,
        #         "lc_change_candle_type": "M5",
        #     })
        #     # オーダーの追加
        #     self.add_order_to_this_class(order_class1)
        #     self.bb5_cross_pattern = 2  # 戻りのほう

    def predict_registance_turn_analysis(self):
        """
        ターンを起点とするオーダー
        """
        print("■ターン予測のオーダー")
        # 変数化
        s = self.s
        peaks = self.peaks_class.peaks_original
        peaks_skip = self.peaks_class.skipped_peaks_hard
        latest_price = self.latest_price  # self.ca = candle_analysis
        ave = self.ca.candle_class
        latest_time = self.latest_time
        bb_h1_class = self.bb_h1_class  # この結果が必須！
        bb_m5_class = self.bb_m5_class  # この結果も必須”
        mode = self.mode
        lc_margin = ave.cal_move_ave(1)  # プラス値で、取得しやすい方向にTargetPriceを動かす。
        lc_adjasuter = lc_margin if peaks[0]['direction'] == 1 else lc_margin * -1  # 逆張り前提。

        # 途中終了の場合
        if peaks[1]['gap'] < 0.04:
            print("対象が小さい", peaks[1]['gap'])
        if peaks[0]['count'] != 2:
            print("リバーカウントが3以外", peaks[0]['count'])
            return 0

        # if bb_h1_class.is_previous and (bb_h1_class.latest_price_position_in_bb != peaks[0]['direction']):
        #     print(s, "1時間足のトレンドとlatestの向きが異なるため、抵抗線オーダー無し", bb_h1_class.latest_price_position_in_bb)
        #     return 0
        if bb_m5_class.trumpet_res['bb_shape'] == "re-trumpet" or bb_m5_class.trumpet_res['bb_shape'] == "parallel":
            print("5分足で逆トランペットを発見！")
            is_re_trumpet = True
        else:
            is_re_trumpet = False
        # if self.take_position_flag:
        #     print(s, "既にオーダーがあるため、抵抗線オーダーは行わない。")
        #     return 0
        if bb_m5_class.is_previous:
            print(s, "5分足でのトレンド直後のため、抵抗線オーダーは行わない")
            # return 0

        # ①25足分(約２時間)で、強いラインを検索する
        strong_border = 6
        foot_count_max = 30
        foot_count = 0
        target_i = 2  # 基本は2
        max_line_info = 0
        max_line_i = 0
        max_peak_total = 0
        latest_peak = peaks[0]
        far_price = 0 if latest_peak['direction'] == 1 else 999
        price_list = "same_price_list"
        price_target_total = "same_price_list_total"
        print(s, "対象のピークス", peaks[0]['latest_time_jp'], "-", peaks[-1]['latest_time_jp'])
        for i, item in enumerate(peaks):
            if i >= 2 and latest_peak['direction'] == item['direction']:
                if latest_peak['direction'] == 1:
                    # スキップ判定
                    if float(latest_peak['latest_body_peak_price']) > float(item['latest_body_peak_price']):
                        # print(s, "最新価格より低い価格のピークなので検討しない", item['latest_time_jp'])
                        continue
                    else:
                        # 検討対象の場合、LC候補の価格も同時に取得しておく
                        if item['latest_body_peak_price'] > far_price:
                            far_price = item['latest_body_peak_price']
                else:
                    # スキップ判定
                    if latest_peak['latest_body_peak_price'] < item['latest_body_peak_price']:
                        # print(s, "最新価格より高い価格のピークなので検討しない", latest_peak['latest_body_peak_price'], item['latest_body_peak_price'])
                        continue
                    else:
                        # 検討対象の場合、LC候補の価格も同時に取得しておく
                        if item['latest_body_peak_price'] < far_price:
                            far_price = item['latest_body_peak_price']
                # 同じ向きの、足の個数範囲内のピークだった場合
                # print(s, i, item['latest_time_jp'], foot_count)
                i_line_info = self.support_line_detect(i)
                if i_line_info[price_target_total] >= strong_border:
                    # 最低限の強度を越えている
                    if i_line_info[price_target_total] > max_peak_total:
                        # 最高のピーク値を更新
                        max_peak_total = i_line_info[price_target_total]
                        max_line_info = i_line_info
                        max_line_i = i

            # 足数をカウントする
            foot_count = foot_count + item['count']
            if foot_count > foot_count_max:
                break
        print(s, "LC候補価格", far_price, far_price + lc_adjasuter)
        # ②フロップのラインも求めておく
        flop_line_info = self.support_line_detect(2)  # turnの抵抗線度合い

        print(s, "同価格リスト（flop） 数", len(flop_line_info[price_list]), "点", flop_line_info[price_target_total], flop_line_info[price_list], "turn=", peaks[2])
        gene.print_arr(flop_line_info[price_list])

        # ■直近（Flop）が１０越えていた場合はflopを採用。10越えていない場合、過去25足で一番大きな抵抗線を採用する。
        if flop_line_info[price_target_total] >= strong_border:
            print(s, "フロップが強いので、キープ")
            target_line = flop_line_info
            target_i = 2
        else:
            if max_line_info != 0 and max_line_info[price_target_total] >= strong_border:
                print(s, "直近の期間で強いLINE有（Flopは弱い）", max_line_info, peaks[max_line_i]['latest_time_jp'])
                target_line = max_line_info
                target_i = max_line_i
                print(s, "同価格リスト（MAX）", max_line_info[price_target_total], "turn=",
                      peaks[target_i])
                gene.print_arr(max_line_info[price_list])
            else:
                print(s, "強いLine無し")
                return 0

        # 最終的にターンが選ばれても、おかしい状況の場合は終了
        if latest_peak['latest_body_peak_price'] > peaks[2]['latest_body_peak_price'] and latest_peak['direction'] == 1:
            # print(s, "現在価格よりターゲットのほうが小さいのでNG（ロジック上フロップが選ばえた場合に発生）")
            return 0
        elif latest_peak['latest_body_peak_price'] < peaks[2]['latest_body_peak_price'] and latest_peak['direction'] == -1:
            # print(s, "現在価格よりフロップのほうが大きいのでNG（ロジック上フロップが選ばえた場合に発生）")
            return 0

        # 最高、最低到達点の確認。また
        highest_price = 0
        lowest_price = 999
        for i, item in enumerate(target_line[price_list]):
            if item['item']['highest'] > highest_price:
                highest_price = item['item']['highest']
            if item['item']['lowest'] < lowest_price:
                lowest_price = item['item']['lowest']
        if peaks[0]['direction'] * -1 == 1:  # ポジション予定の方向が買いの場合、最低価格をLC価格候補にする
            lc_price_temp = lowest_price
        else:
            lc_price_temp = highest_price
        print(s, "該当区間の最高価格と最低価格", highest_price, lowest_price, "LC候補価格", lc_price_temp)

        # self.exist_strong_lineのコントロール
        self.exist_strong_line = True  # ここまで来ていればTrue
        print(s, "強い抵抗線有 peakNo", target_i, peaks[target_i])

        # オーダー発行準備＋最終判断
        target_price = round(peaks[target_i]['latest_body_peak_price'] + (-0.01 * peaks[target_i]['direction']), self.round_digit)
        if abs(self.current_price - target_price) <= 0.03:
            print(s, "オーダー価格と現在価格が近すぎるため、オーダーを回避 target:", target_price, " current:", self.current_price, "line", peaks[target_i]['latest_body_peak_price'])
            print(s, "flop4点基準の場合、これは逆に突破する前兆？？（今まで抵抗でマイナスが多かったので） ")
            print(s, "ただそれでもいい場合もあるので、高得点の場合は、LCを短くしてトライするのもあり")
            pattern = 1
            target_price = round(peaks[target_i]['latest_body_peak_price'] + (0.01 * peaks[target_i]['direction']), self.round_digit)
        else:
            pattern = 0
            # return 0

        # 直近（Flop）が１０越えていた場合はflopを採用。10越えていない場合、過去25足で一番大きな抵抗線を採用する。
        if target_line[price_target_total] >= strong_border and len(target_line[price_list]) >= 2:  # 理想は13以上？
            if pattern == 0:
                print(s, "予測ターンオーダーをしたい！ target:", target_price)
                order_class1 = OCreate.Order({
                    "name": "抵抗線ターン予測(逆張り）",
                    "current_price": latest_price,
                    "target": target_price,
                    "direction": peaks[0]['direction'] * -1,  # latestの反対（latestが抵抗線に当たって帰ってくるオーダーなので）
                    "type": "LIMIT",  # 逆張りなのでLIMIT
                    "tp": ave.cal_move_ave(1.4),  # ave.cal_move_ave(3),  ,
                    "lc": lc_price_temp,  # ave.cal_move_ave(1.2),  # width,
                    "lc_change": self.make_lc_change_dic("M5", None, "offence"),
                    "units": self.units_str * 1.3,
                    "priority": 11,
                    "decision_time": self.peaks_class.df_r_original.iloc[0]['time_jp'],
                    "candle_analysis_class": self.ca,
                    "lc_change_candle_type": "M5",
                    # "order_timeout_min": 40
                })
                # オーダーの追加
                self.add_order_to_this_class(order_class1)
            else:
                print(s, "予測ターン(r)オーダーをしたい！ target:", target_price)
                order_class1 = OCreate.Order({
                    "name": "抵抗線ターン予測(逆張り）_r",
                    "current_price": latest_price,
                    "target": target_price,
                    "direction": peaks[0]['direction'],  # latestの反対（latestが抵抗線に当たって帰ってくるオーダーなので）
                    "type": "STOP",  # 逆張りなのでLIMIT
                    "tp": ave.cal_move_ave(1.4),  # ave.cal_move_ave(3),  ,
                    "lc": ave.cal_move_ave(1.2),  # width,
                    "lc_change": self.make_lc_change_dic("M5", None, "offence"),
                    "units": self.units_str * 1.31,
                    "priority": 11,
                    "decision_time": self.peaks_class.df_r_original.iloc[0]['time_jp'],
                    "candle_analysis_class": self.ca,
                    "lc_change_candle_type": "M5",
                    # "order_timeout_min": 40
                })
                # オーダーの追加
                self.add_order_to_this_class(order_class1)

    def simple_turn_analysis(self):
        print("■シンプルターンオーダー", self.latest_price)
        # 変数化
        s = self.s
        peaks = self.peaks_class.peaks_original
        peaks_skip = self.peaks_class.skipped_peaks_hard
        latest_price = self.latest_price  # self.ca = candle_analysis
        ave = self.ca.candle_class_hour
        latest_time = self.latest_time
        bb_h1_class = self.bb_h1_class  # この結果が必須！
        bb_m5_class = self.bb_m5_class  # この結果も必須”
        mode = self.mode
        ave5 = self.ca5
        df = self.peaks_class.df_r_original
        big_move_criteria = 0.1  # 個以上動いたら、5分１足にしては大きい
        u = self.round_digit
        pattern = 0  # 通常では0
        allowed_gap_to_bb = 0.02  # 現在価格と近いBBまでの距離（近い場合＋レンジの場合は伸びないはず）
        latest_dir = peaks[0]['direction']

        # 途中終了の場合
        if peaks[1]['gap'] < 0.04:
            print(s, "対象が小さい", peaks[1]['gap'])
        if peaks[0]['count'] != 2:  # and self.mode == "inspection"
            return 0

        # 数字に調整が入る場合
        if df.iloc[1]['moves'] >= big_move_criteria or df.iloc[2]['moves'] >= big_move_criteria:
            print(s, "ビッグムーブのため、LCを少し広げておく")
        else:
            print(s, "ビッグムーブなし", df.iloc[1]['time_jp'],  df.iloc[1]['moves'],  df.iloc[2]['time_jp'],  df.iloc[1]['moves'])

        # peaks[0]の足の大きさの比較
        df1 = df.iloc[1]
        df2 = df.iloc[2]
        a1 = df1['inner_low']
        b1 = df1['inner_high']
        a2 = df2['inner_low']
        b2 = df2['inner_high']
        size1 = b1 - a1
        size2 = b2 - a2
        base_size = max(size1, size2)
        overlap = max(0, min(b1, b2) - max(a1, a2))
        overlap_rate = overlap / base_size if base_size > 0 else 0
        print(s, "df_test", df.iloc[1]['time_jp'], df.iloc[2]['time_jp'])
        print(s, "df_test", overlap_rate)
        if overlap_rate >= 0.8:
            print(s, "直近のラップが大きいため、読みにくい")
            return 0


        # 瞬間の価格変動は？
        if mode == "live":
            # 変動が大きいときは、ローソクの終わり値と、現在価格がずれる。ずれている時はちょっと警戒！
            latest_price_from_df = df.iloc[1]['close']  # iloc[1]
            price_dic = self.oa.NowPrice_exe(self.pair)  # US/JPY
            latest_price = price_dic['data']['mid']  # mid価格でいいや
        else:
            latest_price_from_df = df.iloc[1]['close']  # iloc[1]
            latest_price = latest_price_from_df  # 検証の場合、どうしようもないので一致
        gap_of_second = round(abs(latest_price_from_df - latest_price), u)
        print(s, "  価格差の検証 API価格:", latest_price, " DF価格:", latest_price_from_df, "差", gap_of_second)
        if gap_of_second >= 0.02:
            print(s, "瞬間的に移動が大きい⇒見送り？LimitかStopの変更？")
            if mode == "live":
                tk.line_send("瞬間的な価格変動が大きい？ API価格", latest_price, "DF価格", latest_price_from_df)

        # riverの最後の足が長い場合は、おかしいことになる？
        latest_foot = df.iloc[1]  # peaksを作ったきっかけの足
        if latest_dir == 1:
            target_bb_price = round(df.iloc[1]['bb_upper'], self.round_digit)  # [0]のほうが良い？
        else:
            target_bb_price = round(df.iloc[1]['bb_lower'], self.round_digit)
        gap_bb_to = round(abs(latest_price-target_bb_price), self.round_digit)  # 狭ければNG？
        print(s, "  直近の足", latest_foot['time_jp'])
        print(s, "  抵抗線の発見有無", self.exist_strong_line)
        print(s, "  現在価格とBBと距離", latest_price, target_bb_price, gap_bb_to)
        # latestとturnの比率
        # rt = TuneAnalysisInformation(self.peaks_class, 1, "rt")  # peak情報源生成
        rt_ratio = round(peaks[0]['gap'] / peaks[1]['gap'], 3)
        print(s, "  rt比率", rt_ratio)  # riverの方が大きい場合、1を超える

        if rt_ratio >= 1.2:
            print(s, "  riverがturnより大きい（riverとは逆に戻ってきそう。）", rt_ratio)
            if gap_bb_to <= 0.03:
                print("BBの近くに価格が迫っている", gap_bb_to)
        else:
            print(s, "river小さめ　BBまでの距離有　REV??", rt_ratio, gap_bb_to)

        # latestの戻り幅が大きい（turnが3カウント以上あり、3カウントを越える戻りの場合。1.2よりこっちのほうが現実的？）
        body_total = 0
        count = 0
        for i in range(2, 4):  # 最大2回（4-2)、ただしturnのカウント以下
            print(s, "  dfの時間：", df.iloc[i]['time_jp'], i, count, df.iloc[i]['body'])
            body_total = body_total + abs(df.iloc[i]['body'])
            count = count + 1
            if count == peaks[1]['count']:
                break
        print(s, "  ターン直近2個の合計", body_total, "(参考)ターンカウント", peaks[1]['gap'], "count", peaks[1]['count'])
        rt_ratio_new = round(peaks[0]['gap'] / body_total, 3)
        print(s, "  body_totalとの比率", rt_ratio_new, "latestのgap", peaks[0]['gap'])
        if peaks[0]['gap'] >= 0.05:
            if rt_ratio_new >= 1.1:
                print(s, "latestが大きく、rtの比率も大きく、戻りが強いと判断？ gap", peaks[0]['gap'], "rt", rt_ratio_new)
                pattern = 1

        # 小さな繰り返しの時
        p1_gap = peaks[1]['gap']
        p1_count = peaks[1]['count']
        p2_gap = peaks[2]['gap']
        p2_count = peaks[2]['count']
        gap_criteria = 0.06
        count_criteria = 3
        if p1_gap <= gap_criteria or p1_count <= count_criteria:
            # 二回連続でギャップが小さいとき
            if p2_gap <= gap_criteria or p2_count <= count_criteria:
                # カウントも少ないとき
                print(s, "強いレンジと思われるため、微妙, 直近", peaks[1]['latest_time_jp'], p1_gap, p1_count, "P2", peaks[2]['latest_time_jp'], p2_gap, p2_count)
                return 0

        # ★★★オーダー
        # (1)オーダー準備
        river = peaks[1]
        latest = peaks[0]

        # r方向準備
        r_dir = peaks[0]['direction'] * -1
        if r_dir == 1:
            r_target_price = river['highest']
        else:
            r_target_price = river['lowest']

        # 順張り方向準備
        s_dir = peaks[0]['direction']
        if s_dir == 1:
            s_target_price = latest['highest']
            s_lc_price = river['lowest']
        else:
            s_target_price = latest['lowest']
            s_lc_price = river['highest']
        s_lc_range = round(abs(s_lc_price - s_target_price), self.round_digit)  # 計算用
        s_for_lc_change = {"exe": True, "time_after": 0, "trigger": s_lc_range + 0.01, "ensure": s_lc_range * 0.5}
        print(s, "オーダー準備(r)", r_target_price)
        print(s, "オーダー準備(s)", s_target_price, s_lc_price, s_lc_range)
        if s_lc_range >= 0.09:  # lcが大きすぎる場合は、補正する(機能の準備のみ）
            arrowed_lc_range = 0.09
            if s_dir == 1:
                print(s, "LCrangeが広すぎるので修正", s_dir, s_target_price - arrowed_lc_range)
            else:
                print(s, "LCrangeが広すぎるので修正", s_dir, s_target_price + arrowed_lc_range)

        # ここからオーダー
        print(s, "  ５分足トレンドについて is_previous", bb_m5_class.is_previous, "向き",bb_m5_class.latest_price_position_in_bb)
        print(s, "  BBCrossの有無(0=無し,1=あり,2=戻り)", self.bb5_cross_pattern)
        print(s, "  分足のトレンドがあり、latestの向きが異なるため、逆張り", bb_m5_class.latest_price_position_in_bb)

        order_class = OCreate.Order({
            "name": "ちゃんと負けてるかテスト",
            "current_price": latest_price,
            "target": s_target_price,
            "direction": s_dir,
            "type": "STOP",  # "STOP",  # "MARKET",
            "tp": 0.25,  # ave5.cal_move_ave(2),  # 0.2,  # ave5.cal_move_ave(3),  ,
            "lc": s_lc_price,  # width,
            "lc_change": self.make_lc_change_dic("M5", s_for_lc_change, "offence"),
            "units": self.units_str,  # 100,
            "priority": 5,
            "decision_time": df.iloc[0]['time_jp'],
            "candle_analysis_class": self.ca,
            "lc_change_candle_type": "M5",
        })
        # self.add_order_to_this_class(order_class)

        order_class_r = OCreate.Order({
            "name": "ちゃんと負けてるかテスト_r",
            "current_price": latest_price,
            "target": r_target_price,
            "direction": r_dir,
            "type": "STOP",  # "MARKET",
            "tp": 0.025,  # ave5.cal_move_ave(3),  ,
            "lc": 0.03,  # ave5.cal_move_ave(1),  # width,
            "lc_change": self.make_lc_change_dic("M5", None, "safety"),
            "units": self.units_str,  # 100,
            "priority": 5,
            "decision_time": df.iloc[0]['time_jp'],
            "candle_analysis_class": self.ca,
            "lc_change_candle_type": "M5",
            "order_timeout_min": 15,
        })
        # self.add_order_to_this_class(order_class_r)

        order_class_r.add_linkage(order_class)
        order_class.add_linkage(order_class_r)
        self.add_order_to_this_class(order_class)
        self.add_order_to_this_class(order_class_r)
        # if pattern == 0:
        #     # pattern = 0 latestそのままの方向にベットする場合
        #     print(s, "５分足トレンドについて is_previous", bb_m5_class.is_previous, "向き", bb_m5_class.latest_price_position_in_bb)
        #     print(s, "BBCrossの有無(0=無し,1=あり,2=戻り)", self.bb5_cross_pattern)
        #     # これが意外とうまくいってるので、少し改良
        #     print(s, "5分足のトレンドがあり、latestの向きが異なるため、逆張り", bb_m5_class.latest_price_position_in_bb)
        #     # order_class1 = OCreate.Order({
        #     #     "name": "ちゃんと負けてるかテスト_s",
        #     #     "current_price": latest_price,
        #     #     "target": 0.01,
        #     #     "direction": peaks[0]['direction'],
        #     #     "type": "STOP",  # "STOP",  # "MARKET",
        #     #     "tp": 0.03,  # ave5.cal_move_ave(3),  ,
        #     #     "lc": ave5.cal_move_ave(1),  # width,
        #     #     "lc_change": self.make_lc_change_dic("M5", None, "safety"),
        #     #     "units": self.units_str * 0.5,  # 100,
        #     #     "priority": 5,
        #     #     "decision_time": df.iloc[0]['time_jp'],
        #     #     "candle_analysis_class": self.ca,
        #     #     "lc_change_candle_type": "M5",
        #     # })
        #     # self.add_order_to_this_class(order_class1)
        #     order_class = OCreate.Order({
        #         "name": "ちゃんと負けてるかテスト",
        #         "current_price": latest_price,
        #         "target": 0.01,
        #         "direction": peaks[0]['direction'],
        #         "type": "STOP",  # "STOP",  # "MARKET",
        #         "tp": 0.2,  # ave5.cal_move_ave(3),  ,
        #         "lc": ave5.cal_move_ave(1.5),  # width,
        #         "lc_change": self.make_lc_change_dic("M5", None, "offence"),
        #         "units": self.units_str,  # 100,
        #         "priority": 5,
        #         "decision_time": df.iloc[0]['time_jp'],
        #         "candle_analysis_class": self.ca,
        #         "lc_change_candle_type": "M5",
        #     })
        #     # self.add_order_to_this_class(order_class)
        #
        #     order_class_r = OCreate.Order({
        #         "name": "ちゃんと負けてるかテスト_r",
        #         "current_price": latest_price,
        #         "target": 0.015,
        #         "direction": peaks[0]['direction'] * -1,
        #         "type": "STOP",  # "MARKET",
        #         "tp": 0.025,  # ave5.cal_move_ave(3),  ,
        #         "lc": 0.03, # ave5.cal_move_ave(1),  # width,
        #         "lc_change": self.make_lc_change_dic("M5", None, "safety"),
        #         "units": self.units_str,  # 100,
        #         "priority": 5,
        #         "decision_time": df.iloc[0]['time_jp'],
        #         "candle_analysis_class": self.ca,
        #         "lc_change_candle_type": "M5",
        #     })
        #     # self.add_order_to_this_class(order_class_r)
        #
        #     order_class_r.add_linkage(order_class)
        #     order_class.add_linkage(order_class_r)
        #     self.add_order_to_this_class(order_class_r)
        #     self.add_order_to_this_class(order_class)
        # else:
        #     # pattern = 1　⇒latestとは逆に張る場合（従来の思想とは異なる）
        #     # order_class1 = OCreate.Order({
        #     #     "name": "ちゃんと負けてるかテストrev_s",
        #     #     "current_price": latest_price,
        #     #     "target": 0.01,
        #     #     "direction": peaks[0]['direction'] * -1,
        #     #     "type": "STOP",  # "STOP",  # "MARKET",
        #     #     "tp": 0.2,  # ave5.cal_move_ave(3),  ,
        #     #     "lc": ave5.cal_move_ave(1),  # width,
        #     #     "lc_change": self.make_lc_change_dic("M5", None, "safety"),
        #     #     "units": self.units_str * 0.5,  # 100,
        #     #     "priority": 5,
        #     #     "decision_time": df.iloc[0]['time_jp'],
        #     #     "candle_analysis_class": self.ca,
        #     #     "lc_change_candle_type": "M5",
        #     # })
        #     # self.add_order_to_this_class(order_class1)
        #     order_class_rev = OCreate.Order({
        #         "name": "ちゃんと負けてるかテストrev",
        #         "current_price": latest_price,
        #         "target": 0.01,
        #         "direction": peaks[0]['direction'] * -1,
        #         "type": "STOP",  # "STOP",  # "MARKET",
        #         "tp": 0.2,  # ave5.cal_move_ave(3),  ,
        #         "lc": ave5.cal_move_ave(1.5),  # width,
        #         "lc_change": self.make_lc_change_dic("M5", None, "offence"),
        #         "units": self.units_str,  # 100,
        #         "priority": 5,
        #         "decision_time": df.iloc[0]['time_jp'],
        #         "candle_analysis_class": self.ca,
        #         "lc_change_candle_type": "M5",
        #     })
        #     # self.add_order_to_this_class(order_class_rev)  # 後に書いた
        #
        #     order_class_rev_r = OCreate.Order({
        #         "name": "ちゃんと負けてるかテストrev_r",
        #         "current_price": latest_price,
        #         "target": 0.015,
        #         "direction": peaks[0]['direction'],
        #         "type": "STOP",  # "MARKET",
        #         "tp": 0.025,  # ave5.cal_move_ave(3),  ,
        #         "lc": 0.03,  # ave5.cal_move_ave(1),  # width,
        #         "lc_change": self.make_lc_change_dic("M5", None, "safety"),
        #         "units": self.units_str,  # 100,
        #         "priority": 5,
        #         "decision_time": df.iloc[0]['time_jp'],
        #         "candle_analysis_class": self.ca,
        #         "lc_change_candle_type": "M5",
        #     })
        #     # self.add_order_to_this_class(order_class_rev_r)  # 後に書いた
        #
        #     # リンケージをたがいに登録する
        #     order_class_rev.add_linkage(order_class_rev_r)
        #     order_class_rev_r.add_linkage(order_class_rev)
        #     self.add_order_to_this_class(order_class_rev)
        #     self.add_order_to_this_class(order_class_rev_r)

        return 0


    def support_line_analysis(self):
        print("　　■サポートラインアナリシス")
        s = self.s
        line_mes = ""
        peaks = self.peaks_class.peaks_original

        # ■■解析セクション　抵抗線の算出
        turn_info = self.support_line_detect(1)  # turn部分もの（上下かは問わず）
        flop_info = self.support_line_detect(2)  # flop部分もの（上下かは問わず）
        if turn_info['same_price_list_till_break_5_total'] >= 15:
            line_on = True
            line_mes = line_mes + turn_info['mes']
        if flop_info['same_price_list_till_break_5_total'] >= 15:
            line_on = True
            line_mes = line_mes + flop_info['mes']
        # 髭分を考慮する（参考）
        turn = peaks[1]
        if turn['direction'] == 1:
            peak_of_peak = turn['highest']  # 髭込みで、そのピークの中での最大値（ピークのところの髭ではなく、最小）
        else:
            peak_of_peak = turn['lowest']

        # テスト用の送信
        if not line_mes == "":
            print(s, "抵抗線")
            for i, item in enumerate(turn_info['same_price_list_till_break_5']):
                print(item)
            wick_length = abs(float(peak_of_peak) - float(peaks[1]['latest_body_peak_price']))
            print(s, "ただし髭混みの最低価格は", peaks[1]['latest_wick_peak_price'], "(", wick_length, ")")

            if wick_length >= 0.05:
                self.send_message_at_last = line_mes + "注意　長いひげあり（髭分は余裕をみたロスカとヘッジオーダーが必要）"
            # self.line_send(line_mes)

        print(" ターン抵抗線の向きと強さと価格", turn['latest_time_jp'], turn['direction'], turn['latest_body_peak_price'],
              turn_info['same_price_list_till_break_5_total'])
        gene.print_arr(turn_info['same_price_list'])

    def support_line_detect(self, target_no):
        # ②抵抗線を探す（上側）
        peaks_with_same_price_list = self.peaks_class.peaks_with_same_price_list
        target_no_time = self.peaks_class.peaks_original[target_no]['latest_time_jp']
        target_no_time = datetime.strptime(target_no_time, "%Y/%m/%d %H:%M:%S")

        if len(peaks_with_same_price_list) == 0:
            print("同一価格リストサイズ０")
            return 0
        # 変数代入＆表示
        same_price_list = peaks_with_same_price_list[target_no]['same_price_list_till_break']  # ターンが抵抗線かを調べる。（リバーではない）
        same_price_list_total = sum(d['item']["peak_strength"] for d in same_price_list)
        same_price_list_till_break_5 = [d for d in peaks_with_same_price_list[target_no]['same_price_list_till_break'] if d["item"]["peak_strength"] >= 5]
        same_price_list_till_break_5_total = sum(d['item']["peak_strength"] for d in same_price_list_till_break_5)
        # 方向
        d = same_price_list[0]['item']['direction']
        target_price = same_price_list[0]['item']['latest_body_peak_price']
        # 表示
        # print("----抵抗線検知  [方向]", d, "対象", target_no)
        # print(self.s, "ターンの強度（同一価格数）", len(same_price_list), "total", same_price_list_total)
        # for i, item in enumerate(same_price_list):
        #     print("          ",  item['i'], item['item']['latest_time_jp'], item['item']['peak_strength'], item['item']['direction'])
        # print(self.s, "Breakまでの同一価格(上位ランクのみ） total", same_price_list_till_break_5_total)
        # for i, item in enumerate(same_price_list_till_break_5):
        #     print("          ", item['i'], item['item']['latest_time_jp'], item['item']['peak_strength'])


        # 判定
        line_strength = 0
        if same_price_list_total <= 2:
            line_strength = 0
            # print(self.s, "抵抗なし(自身のみの検出）")
        elif same_price_list_total <= 4:
            line_strength = 1
            # print(self.s, "引っ掛かり程度の抵抗線")
        elif same_price_list_total < 10:  # 12は5が二つと2が一つを想定。
            if same_price_list_till_break_5_total >= 10:
                # print(self.s, "準 相当強めの抵抗線", same_price_list_total, same_price_list_till_break_5_total)
                line_strength = 7
            elif same_price_list_till_break_5_total >= 5 and len(same_price_list) >= 2:
                # print(self.s, "軽いダブルトップ抵抗線", same_price_list_total, same_price_list_till_break_5_total)
                line_strength = 5
            else:  # =5の場合は、自身のみ
                # print(self.s, "５自身のみか、複数の２", same_price_list_total, same_price_list_till_break_5_total)
                line_strength = 3
        else:
            # 12以上
            if same_price_list_till_break_5_total >= 10:
                # print(self.s, "相当強めの抵抗線", same_price_list_total, same_price_list_till_break_5_total)
                line_strength = 10
            else:
                # print(self.s, "強めの抵抗線", same_price_list_total, same_price_list_till_break_5_total)
                line_strength = 7

        # 狭い脚判定
        if len(same_price_list) == 2:
            latest_time = same_price_list[0]['item']['latest_time_jp']
            oldest_time = same_price_list[1]['item']['latest_time_jp']
            ans = gene.cal_str_time_gap(latest_time, oldest_time)
            # print(self.s, ans['gap_abs']/60, "分", latest_time, oldest_time)

        # 登録
        if d == 1:
            self.upper_line = target_price
        else:
            self.lower_line = target_price
        # print(self.s, self.upper_line, "-", self.lower_line)


        return {
            "same_price_list": same_price_list,
            "same_price_list_total": same_price_list_total,
            "same_price_list_till_break_5": same_price_list_till_break_5,
            "same_price_list_till_break_5_total": same_price_list_till_break_5_total,
            "line_strength": line_strength,
            "d": d,
            "target_price": target_price,
            "mes": "[" + str(d) + "抵抗線]" + str(target_price) + " "
        }

    def flag_analysis(self, peaks_with_same_price_list):
        """
        片方が抵抗線的な、フラッグの成立を判定する（上下とも傾いているフラッグではない）
        ①抵抗線の検証
        ②抵抗線とは逆側のピークの傾きを検証
        ③直近のピークが収束（ピーク幅が15pips以下）かを判定
        """
        if len(peaks_with_same_price_list) == 0:
            print("同一価格リストサイズ０")
            return 0
        # 変数代入＆表示
        r = peaks_with_same_price_list[0]
        t = peaks_with_same_price_list[1]
        latest_peak = peaks_with_same_price_list[1]  # ターンが抵抗線かを調べる。（リバーではない）
        same_price_list_till_break_5 = [d for d in latest_peak['same_price_list_till_break'] if d["item"]["peak_strength"] >= 5]
        print("----FlagAnalyis")
        # print(self.s, "ターンの強度（同一価格数）", len(latest_peak['same_price_list']))
        # for i, item in enumerate(latest_peak['same_price_list']):
        #     print("          ",  item['i'], item['item']['latest_time_jp'], item['item']['peak_strength'])
        # print(self.s, "Breakまでの同一価格")
        # for i, item in enumerate(latest_peak['same_price_list_till_break']):
        #     print("          ",  item['i'], item['item']['latest_time_jp'], item['item']['peak_strength'])
        # print(self.s, "Breakまでの同一価格(上位ランクのみ）")
        # for i, item in enumerate(same_price_list_till_break_5):
        #     print("          ", item['i'], item['item']['latest_time_jp'], item['item']['peak_strength'])
        # print(self.s, "反対サイド")
        # for i, item in enumerate(latest_peak['opposite_peaks']):
        #     print("          ",  item['i'], item['item']['latest_time_jp'], item['item']['peak_strength'], item['item']['direction'])

        # 0基本的な判定
        if r['count'] == 2 and t['peak_strength'] != 2:
            pass
        else:
            print(self.s, "フラッグCount2以外、または、ターン強度弱いのためやらず", r['count'], t['peak_strength'])
            return 0

        # ①抵抗線の検証
        if len(same_price_list_till_break_5) >= 2:
            is_line = True
        else:
            is_line = False

        # ②抵抗線とは逆側のピークの傾きを検証
        is_tilt = self.flag_analysis_cal_tilt(latest_peak['opposite_peaks'])

        # ③直近のピークが収束

        print(self.s, "FLAG判定 isLine", is_line, ",isTilt", is_tilt, "isPeak収束", )
        print(self.s, "現在価格", self.peaks_class.latest_price)

        # 最終判定
        if is_line and is_tilt:
            pass
        else:
            return 0
        # ■■オーダーの生成
        # フラッグ後は、大きく価格が動く可能性がある⇒両建はするが、マイナス側の深追いはやめたい
        order_class1 = OCreate.Order({
            "name": "フラッグ突破方向",
            "current_price": self.peaks_class.latest_price,
            "target": t['latest_body_peak_price'] + (self.ca5.cal_move_ave(0.5) * t['direction']),
            "direction": t['direction'],  # フラッグはターン基準（ターンが抵抗かどうか）なので、t方向が突破方向
            "type": "STOP",
            "tp": self.base_tp_range,  # self.ca5.cal_move_ave(5),
            "lc": self.ca5.cal_move_ave(2),  # self.base_lc_range,
            "lc_change": self.make_lc_change_dic("M5"),
            "units": self.units_str * 1.2,
            "priority": 11,
            "decision_time": self.peaks_class.df_r_original.iloc[0]['time_jp'],
            "candle_analysis_class": self.ca,
            "lc_change_candle_type": "M5",  # M5の場合は、order_classで自動補完されるが、念のため
        })
        self.add_order_to_this_class(order_class1)
        order_class2 = OCreate.Order({
            "name": "フラッグレンジ(Hedge)方向",
            "current_price": self.peaks_class.latest_price,
            "target": self.ca5.cal_move_ave(1.5),
            "direction": r['direction'],
            "type": "STOP",
            "tp": self.base_tp_range,  # self.ca5.cal_move_ave(5),
            "lc": self.ca5.cal_move_ave(2),  # self.base_lc_range,
            "lc_change": self.make_lc_change_dic("M5"),
            "units": self.units_hedge * 1.2,
            "priority": 11,
            "decision_time": self.peaks_class.df_r_original.iloc[0]['time_jp'],
            "candle_analysis_class": self.ca,
            "lc_change_candle_type": "M5",  # M5の場合は、order_classで自動補完されるが、念のため
        })
        self.add_order_to_this_class(order_class2)
        # リンケージをたがいに登録する
        order_class1.add_linkage(order_class2)
        order_class2.add_linkage(order_class1)

    def flag_analysis_cal_tilt(self, target_peaks):
        """
        directionが-1の場合、下側のピークの傾きがあるかどうかの計算
        """
        dependence_y_change_min = 0.015
        dependence_on_line_margin = 0.027
        dependence_near_line_margin_at_least = 0.054
        dependence_lc_range = 0.01
        dependence_max_lc_range = 0.1
        d = target_peaks[0]['item']['direction']  # 代表で先頭の方向を取得
        is_tilt = False  # 返却される値

        # ■■フィルタ作業
        # ■フィルタに使う数字
        till_id = self.peaks_class.peaks_with_same_price_list[1]['same_price_list_till_break'][-1]['i']  # Break前まで
        # ■フィルタ作業
        # ①peaksから指定の方向だけをフィルタし抜き出す場合（基本的に引数で、既にフィルタされた物を受け取る前提のため、使わないメモ用）
        # target_peaks = [item for item in peaks if item["direction"] == d]  # 利用するのは、Lower側
        # ②PeaksStrengthが５以上のもののみを抽出する
        target_peaks = [d for d in target_peaks if d["item"]["peak_strength"] >= 5]
        # ③同一価格（反対側の）のBreakまで
        target_peaks = [d for d in target_peaks if d["i"] <= till_id]
        # ④先頭の３個のピーク、または、Strengthが８の前までのものを取得する
        # index_8 = next((i for i, d in enumerate(target_peaks) if d["item"]["peak_strength"] == 8), None)  # 強さ８のindex取得
        # if index_8 is not None:
        #     target_peaks = target_peaks[:index_8 + 1]  # 8 の手前まで
        # else:
        #     target_peaks = target_peaks[:3]  # 8 がなければ先頭3個
        # ⑤最小または最大値まで、かつStrengthが５以上のものを取得
        # ⑥数が０（強さが5以上のものが０）の場合、傾きは無いとする
        if len(target_peaks) == 0:
            is_tilt = False
            print("  傾きを算出する対象のピークがない")
            return is_tilt

        if d == 1:
            # 上方向（が下がってきているかを確認）の場合、Max値
            min_index, min_or_max_info = max(enumerate(target_peaks), key=lambda x: x[1]['item']["latest_body_peak_price"])  # サイズ感把握のために取得
        else:
            # 下方向（が上ってきているかを確認）の場合、Min値
            min_index, min_or_max_info = min(enumerate(target_peaks), key=lambda x: x[1]['item']["latest_body_peak_price"])
        target_peaks = target_peaks[:min_index + 1]
        total_peaks_num = len(target_peaks)
        print(self.s, "TargetPeaksForTilt")
        gene.print_arr(target_peaks)

        # ■■処理
        latest_item = target_peaks[0]['item']
        oldest_item = target_peaks[-1]['item']
        y_change = latest_item['latest_body_peak_price'] - oldest_item['latest_body_peak_price']
        print(self.s, "Min Max Info")
        print(self.s, min_or_max_info)
        if abs(y_change) <= dependence_y_change_min:
            print(self.s, "傾きが少なすぎる⇒フラッグ判定なし", abs(y_change), dependence_y_change_min)
            return 0
        else:
            print(self.s, "傾きOK", abs(y_change), dependence_y_change_min)

        # ■■傾きがある場合、詳細を確認（OnやNear）
        # OLDESTの価格を原点として、直近Peaksへの直線の傾きを算出する　yの増加量(価格の差分)　/ xの増加量(時間の差分)
        x_change_sec = (gene.cal_at_least(0.0000001,
                    gene.cal_str_time_gap(oldest_item['latest_time_jp'], latest_item['latest_time_jp'])['gap_abs']))  # ０にならない最低値を設定する
        tilt = y_change / x_change_sec
        tilt = max(tilt, 1e-8)  # 0を防ぐ（この数で割るため）

        on_line_num = near_line_num = 0
        for i, item in enumerate(target_peaks):
            # ■座標(a,b)を取得する
            a = gene.cal_str_time_gap(oldest_item['latest_time_jp'], item['item']['latest_time_jp'])['gap_abs']  # 時間差分
            b = item['item']["latest_body_peak_price"] - oldest_item['latest_body_peak_price']  # ここでは
            # print(s7, "(ri)a:", a, ",b:", b)

            # ■線上といえるか[判定]
            jd_y_max = tilt * a + dependence_on_line_margin
            jd_y_min = tilt * a + (dependence_on_line_margin * -1)
            if jd_y_max > b > jd_y_min:
                # print("　(ri)線上にあります", item['item']['latest_time_jp'], jd_y_max, b, jd_y_min, jd_y_max > b > jd_y_min)
                on_line_num += 1
            else:
                # print("　(ri)線上にはありません", item['item']['latest_time_jp'], jd_y_max, b, jd_y_min, jd_y_max > b > jd_y_min)
                pass

            # ■線の近くにあるか[判定]
            near_line_margin = abs(latest_item['latest_body_peak_price'] - min_or_max_info['item']['latest_body_peak_price']) * 0.405  # * 0.405がちょうどよさそう
            near_line_margin = gene.cal_at_least(dependence_near_line_margin_at_least,
                                                 near_line_margin)  # 下側の下落、上側の上昇の場合、最小最大が逆になると０になる可能性がある
            # print(target_peaks[0]['time'], target_peaks[0]['peak'], min_or_max_info['time'], min_or_max_info['peak'])
            # print("MARGIN:", abs(target_peaks[0]['peak'] - min_or_max_info['peak']), near_line_margin)
            jd_y_max = tilt * a + near_line_margin
            jd_y_min = tilt * a + (near_line_margin * -1)
            if jd_y_max > b > jd_y_min:
                # print("　(ri)　線近くにあります", item['item']['latest_time_jp'], jd_y_max, b, jd_y_min, jd_y_max > b > jd_y_min)
                near_line_num += 1
            else:
                # print("　(ri)　線近くにはありません", item['item']['latest_time_jp'], jd_y_max, b, jd_y_min, jd_y_max > b > jd_y_min)
                pass

        on_line_ratio = round(on_line_num / total_peaks_num, 2)
        near_line_ratio = round(near_line_num / total_peaks_num, 2)
        # 最終判定
        tilt_pm = tilt / abs(tilt)  # tiltの方向を算出する（上側が下傾斜、下側の上傾斜の情報のみが必要）
        tilt_line_level_each = 0
        # print(s7, "調査側は", d, "傾き方向は", tilt_pm)
        if d == tilt_pm:
            # print(s7, "下側が下方向、上側が上方向に行っている（今回は収束と見たいため、不向き）")
            remark = "発散方向"
            direction_integrity = False  # 方向の整合性
        else:
            # 傾斜は合格、ピークスを包括できるかを確認
            # if on_line_ratio >= 0.55 and near_line_ratio >= 0.7:  # 0.35, 60
            # if on_line_ratio >= 0.35 and near_line_ratio >= 0.6:  # 緩いほう（従来の結果がよかった条件）
            if on_line_ratio > 0.5 and near_line_ratio >= 0.8:  # 結構完璧な形（両端の2個を含むため、4個の場合2個より大きくしないといけない）
                # print(s7, "強力な継続的な傾きとみなせる", on_line_ratio, near_line_ratio, "peak_num", total_peaks_num,
                #       "On", on_line_num, "Near", near_line_num)
                tilt_line_level_each = 1
                is_tilt = True
                # remark = "継続した傾斜と判断"
                if tilt < 0:
                    remark = "上側下落(強)"
                else:
                    remark = "下側上昇(強)"
            elif on_line_ratio >= 0.35 and near_line_ratio >= 0.5:  # さらに緩いほう（2025/1/13 13/50を取得したいため）
                # print(s7, "継続的な傾きとみなせる", on_line_ratio, near_line_ratio, "peak_num", total_peaks_num, "On",
                #       on_line_num, "Near", near_line_num)
                tilt_line_level_each = 0.5
                # remark = "継続した傾斜と判断"
                if tilt < 0:
                    remark = "上側下落(弱)"
                else:
                    remark = "下側上昇(弱)"
                # print(s7, "継続した傾斜と判断", d)
            else:
                remark = "線上、線近くのどちらかが未達"
                # print(s7, "線上、線近くのどちらかが未達", on_line_ratio, near_line_ratio)

        # ■LC値の参考値を算出（対象のピーク群の中間値）
        total_peak = sum(item['item']["latest_body_peak_price"] for item in target_peaks)
        ave_peak_price = round(total_peak / len(target_peaks), self.round_digit)
        lc_margin = dependence_lc_range * d * -1
        ave_peak_price = ave_peak_price + lc_margin

        print(self.s, remark, on_line_ratio, near_line_ratio)

        return is_tilt



class TuneAnalysisInformation:
    def __init__(self, peaks_class, older_no, name):
        """
        与えられたピークの中の、任意の二つのピークのサイズの比率を求める。
        任意とは、引数のOlderNoで指定される。与えられたピークスの中の、older_no番目と、older_no-1番目を比較する
        （例）　
        1 9:15
        2 8:50
        3 7:40
        older_noが３を与えられた場合、olderは３、時間的に新しいlatestは2(=3-1)となる。
        olderNOが1の場合、LaterNoは0
        """
        # print("  ----TurnAnalysisPrint　　【", name, "】")
        self.name = name
        self.peaks_class = peaks_class
        peaks = self.peaks_class.peaks_original
        later_no = older_no - 1
        older_peak = peaks[older_no]
        later_peak = peaks[later_no]

        # older
        self.lo_ratio = 0
        self.turn_strength_at_older = 0
        self.skip_exist_at_older = False
        self.skip_num_at_older = 0
        self.is_same_direction_at_river = False  # リバー専用？　リバーの向きと、その直近2個のローソクの向きが同じかどうか
        self.second_last_close_price = 0  # is_sameと同時に使われること多い。ひとつ前のローソクの開始価格（勢いある時は越えない）
        # later
        self.turn_strength_at_later = 0
        self.skip_exist_at_later = False
        self.skip_num_at_later = 0
        self.is_same_direction_at_river_later = False  # リバー専用？　リバーの向きと、その直近2個のローソクの向きが同じかどうか
        self.second_last_close_price_later = 0  # is_sameと同時に使われること多い。ひとつ前のローソクの開始価格（勢いある時は越えない）

        # 処理
        # self.single_peak_additional_information_older(older_no)  # olderの解析
        # self.single_peak_additional_information_later(older_no - 1)  # laterの解析
        # self.relation_2peaks_information(older_peak, later_peak)  # 二つにまつわる解析


        # 表示
        # print("   later:", later_peak['latest_time_jp'])
        # print("   older:", older_peak['latest_time_jp'])
        # print("   laterCount", later_peak['count'], "olderCount", older_peak['count'])
        # print("   olderスキップ有:", self.skip_exist_at_older, "olderSKIP数", self.skip_num_at_older)
        # print("   olderターン強度", self.turn_strength_at_older, "戻り率(通常)", self.lo_ratio)
        # print("  ↑")

    # def single_peak_additional_information_older(self, peak_no):
    #     """
    #     一つのピークの調査内容。peak_noで指定される
    #     基本的に１はターン、２はフロップを示す
    #     """
    #     # ■情報の元
    #     peaks = self.peaks_class.peaks_original
    #     peaks_sk = self.peaks_class.skipped_peaks_hard  # 元々の
    #     target_peak = peaks[peak_no]  # 基本時間的に古いほうが入る。riverとturnの場合は１(turn)
    #     if len(peaks_sk) <= peak_no:
    #         # スキップの場合、１つになってしまっていることが、、
    #         print(" @@@@@@スキップでピークが一つになって少し変な状況")
    #         target_peak_sk = target_peak  # とりあえずtargetPeakと同じものを入れて暫定
    #     else:
    #         # こっちが本来ほしいほう
    #         target_peak_sk = peaks_sk[peak_no]
    #
    #     # ■各種調査
    #     # print("   SinglePeakAdditional関数 ターゲットNo:", peak_no, target_peak_sk)
    #     # ⓪計算不要
    #     self.skip_num_at_older = target_peak_sk['skip_include_num']
    #     # ①　強度の判定
    #     self.peaks_class.make_same_price_list(peak_no, False)  # クラス内でSamePriceListを実行
    #     self.turn_strength_at_older = sum(d["item"]["peak_strength"] for d in self.peaks_class.same_price_list)
    #     # gene.print_arr(self.peaks_class.same_price_list)
    #
    #     # ②turnを生成するPeakに、スキップがあったかを確認する
    #     if self.peaks_class.cal_target_times_skip_num(self.peaks_class.skipped_peaks_hard, target_peak['latest_time_jp']) >= 1:
    #         self.skip_exist_at_older = True
    #     else:
    #         self.skip_exist_at_older = False
    #
    #     # ③トレンド減速検知
    #     target_df = self.peaks_class.peaks_original_with_df[1]['data']  # "data"は特殊なPeaksが所持（スキップ非対応）
    #     brake_trend_exist = False
    #     # print("[1]のデータ")
    #     # print(target_df)
    #     if len(target_df) < 4:
    #         # print("target_dataが少なすぎる([1]がやけに短い⇒TrendBrakeあり？）")
    #         brake_trend_exist = True
    #     else:
    #         # BodyAveで検討
    #         older_body_ave = round((target_df.iloc[2]['body_abs'] + target_df.iloc[3]['body_abs']) / 2,
    #                                self.round_digit) + 0.0000000001  # 0防止
    #         later_body_ave = round((target_df.iloc[0]['body_abs'] + target_df.iloc[1]['body_abs']) / 2,
    #                                self.round_digit) + 0.0000000001  # 0防止
    #         # print("ratio", round(older_body_ave / later_body_ave, self.round_digit), "older", older_body_ave, "latest", later_body_ave)
    #         if older_body_ave / later_body_ave >= 3.5:  # 数が大きければ、よりブレーキがかかる
    #             # print("傾きの顕著な減少（ボディ）")
    #             brake_trend_exist = True
    #
    #     # ④最後の足の方向について
    #     # r_df = self.peaks_class.peaks_original_with_df[0]['data']
    #     # latest_df = r_df.iloc[0]
    #     # latest_same = False
    #     # if (r['direction'] == 1 and latest_df['body'] > 0) or (r['direction'] == -1 and latest_df['body'] < 0):
    #     #     # print("リバーが正方向＋リバー最後が陽線 or リバーが負方向＋リバー最後が陰線", r['direction'], latest_df['body'])
    #     #     latest_same = True
    #     # else:
    #     #     pass
    #     #     # print("NG リバー方向", r['direction'], "ボディー向き", latest_df['body'])
    #
    #     # ⑤（基本riverで利用）最後の二つのローソクの向きが同じ、かつ、方向と同じかどうか
    #     if peak_no == 0:
    #         r_df = self.peaks_class.peaks_original_with_df[0]['data']
    #         latest_df = r_df.iloc[0]
    #         second_df = r_df.iloc[1]
    #         if target_peak['direction'] == 1 and latest_df['body'] > 0 and second_df['body'] > 0:
    #             self.is_same_direction_at_river = True  # リバー専用？　リバーの向きと、その直近2個のローソクの向きが同じかどうか
    #             self.second_last_close_price = second_df['close']
    #             print("　　◎リバーの方向が全部同じ（正方向）", self.second_last_close_price)
    #         elif target_peak['direction'] == -1 and latest_df['body'] < 0 and second_df['body'] < 0:
    #             self.is_same_direction_at_river = True  # リバー専用？　リバーの向きと、その直近2個のローソクの向きが同じかどうか
    #             self.second_last_close_price = second_df['close']
    #             print("　　　◎リバーの方向が全部同じ（負方向）", self.second_last_close_price)
    #         else:
    #             pass
    #             # print("　　　 リバー方向", target_peak['direction'], "ボディー向き", latest_df['body'], second_df['body'])

    # def single_peak_additional_information_later(self, peak_no):
    #     """
    #     時系列的に新しい（rtの場合、river側(0)）
    #     基本Riverの状況を確認したいだけに作っている状況。他の値は使ってない。
    #
    #     """
    #     # ■情報の元
    #     peaks = self.peaks_class.peaks_original
    #     peaks_sk = self.peaks_class.skipped_peaks_hard  # 元々の
    #     target_peak = peaks[peak_no]  # 基本時間的に古いほうが入る。riverとturnの場合は１(turn)
    #     if len(peaks_sk) <= peak_no:
    #         # スキップの場合、１つになってしまっていることが、、
    #         print(" @@@@@@スキップでピークが一つになって少し変な状況")
    #         target_peak_sk = target_peak  # とりあえずtargetPeakと同じものを入れて暫定
    #     else:
    #         # こっちが本来ほしいほう
    #         target_peak_sk = peaks_sk[peak_no]
    #
    #     # ■各種調査
    #     # print("   SinglePeakAdditional関数 ターゲットNo:", peak_no, target_peak_sk)
    #     # ⓪計算不要
    #     self.skip_num_at_later = target_peak_sk['skip_include_num']
    #     # ①　強度の判定
    #     self.peaks_class.make_same_price_list(peak_no, False)  # クラス内でSamePriceListを実行
    #     self.turn_strength_at_later = sum(d["item"]["peak_strength"] for d in self.peaks_class.same_price_list)
    #     # gene.print_arr(self.peaks_class.same_price_list)
    #
    #     # ②turnを生成するPeakに、スキップがあったかを確認する
    #     if self.peaks_class.cal_target_times_skip_num(self.peaks_class.skipped_peaks_hard, target_peak['latest_time_jp']) >= 1:
    #         self.skip_exist_at_later = True
    #     else:
    #         self.skip_exist_at_later = False
    #
    #     # ③トレンド減速検知
    #     target_df = self.peaks_class.peaks_original_with_df[1]['data']  # "data"は特殊なPeaksが所持（スキップ非対応）
    #     brake_trend_exist = False
    #     # print("[1]のデータ")
    #     # print(target_df)
    #     if len(target_df) < 4:
    #         # print("target_dataが少なすぎる([1]がやけに短い⇒TrendBrakeあり？）")
    #         brake_trend_exist = True
    #     else:
    #         # BodyAveで検討
    #         older_body_ave = round((target_df.iloc[2]['body_abs'] + target_df.iloc[3]['body_abs']) / 2,
    #                                self.round_digit) + 0.0000000001  # 0防止
    #         later_body_ave = round((target_df.iloc[0]['body_abs'] + target_df.iloc[1]['body_abs']) / 2,
    #                                self.round_digit) + 0.0000000001  # 0防止
    #         # print("ratio", round(older_body_ave / later_body_ave, self.round_digit), "older", older_body_ave, "latest", later_body_ave)
    #         if older_body_ave / later_body_ave >= 3.5:  # 数が大きければ、よりブレーキがかかる
    #             # print("傾きの顕著な減少（ボディ）")
    #             brake_trend_exist = True
    #
    #     # ④最後の足の方向について
    #     # r_df = self.peaks_class.peaks_original_with_df[0]['data']
    #     # latest_df = r_df.iloc[0]
    #     # latest_same = False
    #     # if (r['direction'] == 1 and latest_df['body'] > 0) or (r['direction'] == -1 and latest_df['body'] < 0):
    #     #     # print("リバーが正方向＋リバー最後が陽線 or リバーが負方向＋リバー最後が陰線", r['direction'], latest_df['body'])
    #     #     latest_same = True
    #     # else:
    #     #     pass
    #     #     # print("NG リバー方向", r['direction'], "ボディー向き", latest_df['body'])
    #
    #     # ⑤（基本riverで利用）最後の二つのローソクの向きが同じ、かつ、方向と同じかどうか
    #     if peak_no == 0:
    #         r_df = self.peaks_class.peaks_original_with_df[0]['data']
    #         latest_df = r_df.iloc[0]
    #         second_df = r_df.iloc[1]
    #         if target_peak['direction'] == 1 and latest_df['body'] > 0 and second_df['body'] > 0:
    #             self.is_same_direction_at_river_later = True  # リバー専用？　リバーの向きと、その直近2個のローソクの向きが同じかどうか
    #             self.second_last_close_price_later = second_df['close']
    #             # print("　　◎リバーの方向が全部同じ（正方向）", self.second_last_close_price_later)
    #         elif target_peak['direction'] == -1 and latest_df['body'] < 0 and second_df['body'] < 0:
    #             self.is_same_direction_at_river_later = True  # リバー専用？　リバーの向きと、その直近2個のローソクの向きが同じかどうか
    #             self.second_last_close_price_later = second_df['close']
    #             # print("　　　◎リバーの方向が全部同じ（負方向）", self.second_last_close_price_later)
    #         else:
    #             pass
    #             # print("　　　NG リバー方向", target_peak['direction'], "ボディー向き", latest_df['body'], second_df['body'])

    def relation_2peaks_information(self, older_peak, later_peak):
        """
        渡された二つのピークの関係性を算出する
        unit_noが１の場合は、riverとturn。unit_noが２の場合は、turnとflop
        """
        # rt_ratio_sk = round(r_sk['gap'] / t_sk['gap'], 2)
        self.lo_ratio = round(later_peak['gap'] / older_peak['gap'], 2)

