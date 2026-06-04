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
import statistics
from collections import Counter

this_file_line_send = False
gl_previous_exe_df60_row = None
gl_previous_exe_df60_order_time = None
gl_previous_bb_h1_class = None
gl_latest_trend_trigger_time = None

gl_unis_std = 0.1  # OrderCreateのベーシックUnitは10000ドル。それにかける倍率

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

        self.ca5 = candle_analysis.candle_meta_class  # peaks以外の部分。cal_move_ave関数を使う用
        self.peaks_class = candle_analysis.peaks_class  # peaks_classだけを抽出
        self.df_r_m5 = candle_analysis.d5_df_r[1:]  # 5分足はひとつ前ので固定！！（Liveでも）

        self.ca60 = candle_analysis.candle_meta_class_hour
        self.peaks_class_hour = candle_analysis.peaks_class_hour
        self.df_r_h1 = candle_analysis.d60_df_r[from_i:]

        self.ca30 = candle_analysis.candle_meta_class_m30
        self.peaks_class_m30 = candle_analysis.peaks_class_m30
        self.df_r_m30 = candle_analysis.d30_df_r[from_i:]

        self.latest_time = candle_analysis.d5_df_r.iloc[0]['time_jp']  # 5分足で判断(0行目を利用）
        self.latest_price = candle_analysis.d5_df_r.iloc[from_i_price]['close']  # iloc[1]
        self.mode = mode  # 検証かどうか
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
        if self.position_control_class is None:
            # print("過去の勝ち負けは気にしない（単発のテストのため情報なし）")
            pass
        else:
            position_one = self.position_control_class.position_classes[0]  # positionの先頭を取得（どれでもいい）
            p = position_one.history_plus_minus
            # print("過去の勝ち負けの履歴", position_one.history_plus_minus)
            if len(p) >= 6:
                # print("勝ち負けの直近三個", p[-1], p[-2], p[-3], p[-4], p[-5], p[-6])
                pass
            else:
                pass
                # print("勝ち負けの直近三個", p[-1])
            # クラスが格納されるように変更したので、クラスのテスト
            for i, item in enumerate(self.position_control_class.result_class_arr):
                pass
                # print("クラスのテスト:", item.life, item.name, item.t_unrealize_pl, item.t_realize_pl, item.t_pl_u)

        # ■■■基本情報の表示
        # peaks = self.peaks_class.peaks_original
        # peaks_skip = self.peaks_class.skipped_peaks_hard
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
        # self.rt = TuneAnalysisInformation(self.peaks_class, 1, "rt")  # peak情報源生成
        # # FlopとTurn
        # self.tf = TuneAnalysisInformation(self.peaks_class, 2, "tf")  # peak情報源生成
        # # preFlopとflopの解析
        # self.fp = TuneAnalysisInformation(self.peaks_class, 2, "fp")  # peak情報源生成
        # 各価格に使うかもしれない物
        self.latest_turn_resistance_gap = abs(t['latest_body_peak_price'] - self.peaks_class.current_price)
        self.latest_flop_resistance_gap = abs(f['latest_body_peak_price'] - self.peaks_class.current_price)
        self.current_price = self.peaks_class.current_price

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
        self.units_str = 1 * gl_unis_std #0.1
        self.units_hedge = self.units_str
        # 汎用性高め
        self.lc_change_test = [
            {"exe": True, "time_after": 0, "trigger": 0.01, "ensure": -1},  # ←とにかく、LCCandleを発動させたい場合
        ]

        # ★★★調査実行
        self.main()

    def make_lc_change_dic(self, foot=None, dic_list=None, types="offence"):
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
            elif types == "hedge":
                print(s,s, "hedge")
                base_dic_list = [
                    # {"exe": True, "time_after": 600, "trigger": ca.cal_move_ave(1), "ensure": ca.cal_move_ave(1) * -1},
                    {"exe": True, "time_after": 0, "trigger": 0.018, "ensure": -0.006},
                ]
            elif types == "slow_start":
                # 最初の５分はほぼ振り状態となているもの
                base_dic_list = [
                    {"exe": True, "time_after": 605, "trigger": 0.05, "ensure": 0.11},
                    {"exe": True, "time_after": 605, "trigger": 0.05, "ensure": 0.015},
                    {"exe": True, "time_after": 605, "trigger": 0.07, "ensure": 0.03},
                    {"exe": True, "time_after": 605, "trigger": 0.12, "ensure": 0.09},
                    {"exe": True, "time_after": 605, "trigger": 0.16, "ensure": 0.012},
                    {"exe": True, "time_after": 605, "trigger": 0.20, "ensure": 0.19},
                ]
            elif types == "No":
                base_dic_list = [{"exe": False, "time_after": 605, "trigger": 1, "ensure": 1 * 0.8}]
            else:
                print(s, s, "offence")
                base_dic_list = [
                    # {"exe": True, "time_after": 600, "trigger": 0.05, "ensure": 0.11},
                    # {"exe": True, "time_after": 0, "trigger": -1, "ensure": -1 * ca.cal_move_ave(1)},  # ほぼLC
                    # {"exe": True, "time_after": 0, "trigger": ca.cal_move_ave(1), "ensure": ca.cal_move_ave(1) * -1},
                    # {"exe": True, "time_after": 0, "trigger": 0.02, "ensure": -0.03},
                    {"exe": True, "time_after": 0, "trigger": 0.04, "ensure": 0.010},
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

        if dic_list is not None:
            # もしdic_listが辞書の場合、配列に変換しておく
            if isinstance(dic_list, dict):
                dic_list = [dic_list]
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
        # self.bb_m5_class = BbAnalysis(candle_analysis, "M5", mode)  # 5分足は必ず実施
        # is_same = (gl_previous_exe_df60_row is not None) and df_h1_row.equals(gl_previous_exe_df60_row)
        # if is_same:
        #     pass
        #     print("1時間足のデータが同じだった ⇒ これは5分毎で値の変わらない検証で多く起こる")
        #     self.bb_h1_class = gl_previous_bb_h1_class  # クラスは新規生成されるため、グローバル変数で記録しておく
        # else:
        #     print("データが異なるので調査対象")
        #     if gl_previous_exe_df60_order_time != candle_analysis.d60_df_r.iloc[0]['time_jp']:
        #         print("まだオーダーをしていない時間のため調査対象", gl_previous_exe_df60_order_time, candle_analysis.d60_df_r.iloc[0]['time_jp'])
        #         gl_previous_bb_h1_class = BbAnalysis(candle_analysis, "H1", mode)  # クラスは新規生成されるため、グローバル変数で記録しておく
        #         self.bb_h1_class = gl_previous_bb_h1_class
        #         gl_previous_exe_df60_row = candle_analysis.d60_df_r.iloc[0]
        #         if gl_previous_bb_h1_class.take_position_flag:
        #             self.add_order_to_this_class(gl_previous_bb_h1_class.exe_order_classes)  # オーダーを登録
        #             gl_previous_exe_df60_order_time = gl_previous_bb_h1_class.latest_time_60  # １H起点のオーダーを入れた時刻を取得（重複オーダー防止用）
        #     else:
        #         self.bb_h1_class = gl_previous_bb_h1_class
        #         print("オーダー済みの時刻", gl_previous_exe_df60_order_time, candle_analysis.d60_df_r.iloc[0]['time_jp'])

        # (2)5分足での調査
        # self.bb_cross_analysis(0, mode)  # ０は引数。スタート地点

        # (3)抵抗線起点
        # self.predict_registance_turn_analysis()

        # (4)抵抗線（過去の逆抵抗）起点
        # self.predict_old_registration_turn_analysis()

        # (4)突然の大本命
        self.simple_turn_analysis()

    def simple_turn_analysis(self):
        print("■シンプルターンオーダー2", self.latest_price)

        # 変数化（共通
        s = self.s
        latest_price = self.latest_price  # self.ca = candle_analysis
        # 変数化（足ごと
        foot = 5
        if foot == 5:
            # ５分足の場合
            # 基本情報
            peaks_class = self.peaks_class
            peaks = self.peaks_class.peaks_original
            df = self.peaks_class.df_r_original  # これは
            range_gap_border = 0.06  # 30分足の場合0.8
            exist_order_gap_border = 0.04
            candle_foot = "M5"
            range_candle_border = 0.06
            range_candle_border_max = 0.1
            tp_min = 0.045
        else:
            # 30分足の場合
            # 基本情報
            peaks_class = self.peaks_class_m30
            peaks = self.peaks_class_m30.peaks_original  # self.peaks_class.peaks_original
            df = self.peaks_class_m30.df_r_original  # self.peaks_class.df_r_original  # これは
            range_gap_border = 0.085  # 30分足の場合0.8
            exist_order_gap_border = 0.04
            candle_foot = "M30"
            range_candle_border = 0.1
            range_candle_border_max = 0.15
            tp_min = 0.04

            # ３０分足の場合は、３０分に１回実行
            dt = datetime.strptime(self.latest_time, '%Y/%m/%d %H:%M:%S')
            minute = dt.minute
            if minute == 0 or minute == 30:  # or minute == 5 or minute == 35:  #minute % 30 == 0:
                pass
            else:
                print("30分足以外")
                return 0

        # 途中終了の場合
        if peaks[1]['gap'] < exist_order_gap_border:
            print(s, "対象が小さい", peaks[1]['gap'])
        if peaks[0]['count'] != 2:  # and self.mode == "inspection"
            print(s, "カウントが２以外", peaks[0]['count'])
            return 0

        # （０）ー１　レンジに入ったと思われる場合の除去
        print(s, "レンジ簡易判定", peaks[1]['latest_time_jp'], peaks[1]['count'], peaks[1]['gap'])
        print(s, "レンジ簡易判定", peaks[2]['latest_time_jp'], peaks[2]['count'], peaks[2]['gap'])
        print(s, "レンジ簡易判定", peaks[3]['latest_time_jp'], peaks[3]['count'], peaks[3]['gap'])
        if (peaks[1]['count'] <= 3 and peaks[1]['gap'] <= range_gap_border and peaks[2]['count'] <= 3 and
                peaks[2]['gap'] <= range_gap_border):
            pass

        # (0)-2 レンジに入った場合の除去
        print(s, "rangeチェック")
        l = peaks[0]
        r = peaks[1]
        print(l['count'])
        print(r)
        print(df.iloc[1]['time_jp'], df.iloc[1]['body_abs'])
        print(l['gap'], r['gap'], r['gap'] * 0.7, r['gap']*1.3)
        if r['count'] >= 4:
            if 0.7 * r['gap'] <= l['gap'] <= r['gap'] * 1.3 and df.iloc[1]['body_abs'] >= range_candle_border:
                print(s, "折り返しが強く、一本でかなり折り返している場合終了⇒変動ユニットのため終了せず")

        # (2)Range判定
        # latestの大きさで判断してみる　小さい場合は、ちょっと危ない？
        print(s, "Latestの確認")
        border_small_latest_peak = 0.06  # 6pips以下の折り返しは３０分足ではかなり小さい
        l = peaks[0]
        l_df1 = df.iloc[1]
        l_df2 = df.iloc[2]
        # Latestのサイズ
        if l['gap'] <= border_small_latest_peak:
            pass
            print(s, "latestPeaksのサイズは小さい")
        else:
            print(s, "latestPeaksのサイズは普通")
            pass

        # データフレーム関係
        is_latest_df_body_big = False
        if l_df1['body_abs'] >= range_candle_border_max:
            # 最後の一つがあまりにも大きいため、オーダーなし（伸びも大きいため、順張りでも伸びる可能性あり（逆の時におおきく負ける可能性大）
            is_latest_df_body_big = True
            print(s, "最後の一つが非常に大きい")

        # latestを形成する二つのローソクの向き
        is_l_bodies_same_direction = False
        if l_df1['body'] * l_df2['body'] <= 0:
            is_l_bodies_same_direction = False
            print(s, "互いの向きが異なる")
        else:
            is_l_bodies_same_direction = True
            print(s, "互いの向きが同じ")

        # latestを形成する二つのローソクのサイズ
        df1_df2_body_ratio = round(l_df2['body_abs'] / l_df1['body_abs'], 3)
        is_brake_and_go = False
        is_go_and_brake = False
        if df1_df2_body_ratio <= 0.3:
            # df1が大きくて、df2が小さい（折り返しポイントのローソクが直近の３割以下のサイズ）
            is_brake_and_go = True
            print(s, "ブレーキ後の大きな動きになっている", l_df1['body_abs'], l_df2['body_abs'], df1_df2_body_ratio)
        elif df1_df2_body_ratio >= 0.7:
            is_go_and_brake = True
            print(s, "大きな折り返しの後のブレーキ", l_df1['body_abs'], l_df2['body_abs'], df1_df2_body_ratio)

        # latestを形成する二つのローソクの重なり（Bodyサイズだけではなく、価格的に包括関係にあるか）
        max1 = l_df1['inner_high']
        min1 = l_df1['inner_low']
        max2 = l_df2['inner_high']
        min2 = l_df2['inner_low']
        width1 = max1 - min1
        width2 = max2 - min2
        overlap = max(0, min(max1, max2) - max(min1, min2))
        # overlap_ratio = overlap / width1 if width1 != 0 else 0  # A基準
        overlap_ratio2 = overlap / (max2 - min2)  # ひとつ前の足が、latestの足と何パーセントかぶっているか
        overlap_ratio = overlap / (max1 - min1)  # latestの何パーセントがそのひとつ前と被っているか
        size_ratio = width2 / width1 if width1 != 0 else 0

        size_condition = width2 >= width1 * 1.3
        overlap_condition = overlap >= width1 * 0.88  # ←ここがA基準
        print(l_df1['time_jp'] ,min1, max1, l_df2['time_jp'], min2, max2, overlap, max1 - min1)
        print("size", size_condition, size_ratio, "overlap1", overlap_ratio, "overlap2", overlap_ratio2)


        # 当初の、Latestの方向にそのまま行くやつ
        op = OrderPoints(peaks_class, df, latest_price, foot)  # オーダーポイントの計算
        # オーダー１の情報
        target_margin_limit = 0.009
        op.cal_target_price_oppo_limit(target_margin_limit)  # target価格を計算する(lc_rangeもここで計算される）
        is_exist_oppo = op.compare_with_exist_positions(self.position_control_class, op.l_dir_oppo)
        # オーダー２の情報
        target_margin_stop = 0.009
        op.cal_target_price_stop(target_margin_stop)  # targetマージンからtarget価格を計算する(lc_rangeもここで計算される）
        is_exist = op.compare_with_exist_positions(self.position_control_class, op.l_dir)

        # オーダー１用の数字の生成
        order_class = None
        if op.stop_order_cancel != 0 and not is_exist_oppo and op.stop_exe_op:
            order_class = OCreate.Order({
                "name": "シンプルターンShort",
                "current_price": latest_price,
                "target": op.target_price_limit_op,
                "direction": op.l_dir_oppo,  # op.l_dir,
                "type": "LIMIT",  # "STOP",  # "MARKET",
                "tp": op.tp_range_limit_wick_op,  # min(tp_min, op.lc_range_limit * 1.2),
                "lc": op.lc_range_limit_wick_op,  # 0.045,  #
                "lc_change": op.lc_change_limit_op,
                "units": op.cal_units(op.lc_range_limit_wick_op, tk.setting_json['s_units'], "s"),  # self.units_str * 1.01,  # 100,
                "priority": 5,
                "decision_time": df.iloc[0]['time_jp'],
                "candle_analysis_class": self.ca,
                "lc_change_candle_type": candle_foot,
                # "order_permission": False,
                "order_timeout_min": 15,
                "memo": "",
            })
            # self.add_order_to_this_class(order_class)

        # オーダー2用の数字の生成
        order_class1 = None
        if op.stop_order_cancel == 0 and not is_exist:
            order_class1 = OCreate.Order({
                "name": "シンプルターンLong",
                "current_price": latest_price,
                "target": op.target_price_stop,
                "direction": op.l_dir,
                "type": "STOP",  # "STOP",  # "MARKET",
                "tp": op.tp_range_stop,
                "lc": op.lc_range_stop,  # 0.15,  # 価格手指定しよう
                "lc_change": op.lc_change_stop,
                "units": op.cal_units(op.lc_range_stop, tk.setting_json['l_units'], "l"),  # 100,
                "priority": 5,
                "decision_time": df.iloc[0]['time_jp'],
                "candle_analysis_class": self.ca,
                "lc_change_candle_type": candle_foot,
                # "order_permission": False,
                "order_timeout_min": 15,
                "memo": op.stop_memo,
            })
            self.add_order_to_this_class(order_class1)
            if order_class1 is not None and order_class is not None:
                # order_classがある場合、リンケージオーダーとして登録する
                order_class1.add_linkage(order_class)
                order_class.add_linkage(order_class1)

class OrderPoints:
    def __init__(self, peaks_class, df_r, latest_price, foot):
        print(" ")
        print(" ★★オーダーポイントの整理")
        # ■■■基本情報の取得
        self.peaks_class = peaks_class
        self.peaks = peaks_class.peaks_original
        self.round_digit = 3
        self.spred = 0.008
        self.latest_price = latest_price
        self.peaks = self.peaks
        self.foot = foot

        # 抵抗線たち
        self.upper_lines = []
        self.lower_lines = []

        # 最新の動きに対して、順方向のオーダーの準備
        self.l_dir = self.peaks[0]['direction']  # peak[0]の方向（latestの方向)
        self.target_price_limit = 0  # リミット（逆張り）用の価格
        self.lc_price_limit = 0
        self.lc_price_limit_wick = 0
        self.lc_range_limit = 0
        self.lc_range_limit_wick = 0

        self.target_price_stop = 0  # ストップ（順張り）用の価格
        self.stop_order_cancel = 0
        self.tp_price_stop = 0
        self.tp_price_stop_wick = 0
        self.tp_range_stop = 0.6  # TPの初期値
        self.tp_range_stop_wick = 0
        self.lc_price_stop = 0
        self.lc_price_stop_wick = 0
        self.lc_range_stop = 0
        self.lc_range_stop_wick = 0
        self.lc_change_stop = []
        self.stop_memo = []

        # 最新の動きに対して、逆方向のオーダーの準備
        self.l_dir_oppo = self.l_dir * -1
        self.target_price_limit_op = 0  # リミット（逆張り）用の価格
        self.lc_price_limit_op = 0
        self.lc_price_limit_wick_op = 0
        self.lc_range_limit_op = 0
        self.lc_range_limit_wick_op = 0
        self.tp_price_limit_op = 0
        self.tp_price_limit_wick_op = 0
        self.tp_range_limit_op = 0
        self.tp_range_limit_wick_op = 0
        self.lc_change_limit_op = []

        self.target_price_stop_op = 0  # ストップ（順張り）用の価格
        self.lc_price_stop_op = 0
        self.lc_price_stop_wick_op = 0
        self.lc_range_stop_op = 0
        self.lc_range_stop_wick_op = 0
        self.tp_price_stop_op = 0
        self.tp_price_stop_wick_op = 0
        self.tp_range_stop_op = 0
        self.tp_range_stop_wick_op = 0
        self.lc_change_stop_op = []
        self.stop_exe_op = True

    def cal_target_price_oppo_limit(self, margin):
        rr = 1.3  # RR値。ロスカ幅に対する、利確幅の比率
        peaks = self.peaks
        spred = self.spred
        is_exe = True
        s = "    "
        base = self.peaks[0]['latest_body_peak_price']  # self.latest_price
        target_dir = self.l_dir_oppo
        print("@@@@@@@逆方向limitに関する計算 Dir:", target_dir, "@@@@@@")
        # ■■■ターゲット価格の算出
        if target_dir == -1:
            target_price = base - margin
        else:
            target_price = base + margin

        # upper
        upper_lines = self.predict_line_upper(target_price)
        # lower
        lower_lines = self.predict_line_lower(target_price)
        self.upper_lines = upper_lines
        self.lower_lines = lower_lines
        # TPとLCでも格納
        if target_dir == -1:
            # 直近価格＝注文価格の場合 いずれも直近価格から近い順に並んでいる。
            tp_lines = self.upper_lines
            lc_lines = self.lower_lines
        else:
            # 直近価格＝注文価格の場合
            tp_lines = self.lower_lines
            lc_lines = self.upper_lines
        print("TARGET PRICE:", target_price)
        print("  TP LINES", len(tp_lines))
        for i, g in enumerate(tp_lines):
            print(
                f"{s}"
                f"Group {i}: median_price = {g['median_price']:.3f}, "
                f"median = {g['median']:.3f}, "
                f"strength = {g['total_strength']}, "
                f"count = {g['count']}, "
                f"near = {g['near']}, "
                f"near_p = {g['near_price']}, "
                f"far = {g['far']}, "
                f"far_p = {g['far_price']}, "
                f"prices = {', '.join(map(str, g['prices']))}"
            )
        print("  LC LINES", len(lc_lines))
        for i, g in enumerate(lc_lines):
            print(
                f"{s}"
                f"Group {i}: median_price = {g['median_price']:.3f}, "
                f"median = {g['median']:.3f}, "
                f"total_strength = {g['total_strength']}, "
                f"count = {g['count']}, "
                f"near = {g['near']}, "
                f"near_p = {g['near_price']}, "
                f"far = {g['far']}, "
                f"far_price = {g['far_price']}, "
                f"prices = {', '.join(map(str, g['prices']))}"
            )

        # ■■■ラインの情報
        # 明示的に、結果を代入していく
        rr = 1.5
        self.target_price_limit_op = target_price  # リミット（逆張り）用の価格
        self.tp_price_limit_op = peaks[1]['latest_body_peak_price'] + (0 * target_dir)
        self.tp_price_limit_wick_op = peaks[1]['latest_wick_peak_price'] + (0 * target_dir)
        self.tp_range_limit_op = round(abs(target_price - self.tp_price_limit_op), 3)
        self.tp_range_limit_wick_op = round(abs(target_price - self.tp_price_limit_wick_op), 3)

        self.tp_range_limit_op = max(self.tp_range_limit_op, 0.05)
        self.tp_range_limit_wick_op = max(self.tp_range_limit_wick_op, 0.05)
        self.tp_price_limit_op = target_price + (self.tp_range_limit_op * target_dir)
        self.tp_price_limit_wick_op = target_price + (self.tp_price_limit_wick_op * target_dir)

        self.lc_range_limit_op = self.tp_range_limit_op / rr  # max(self.tp_range_limit_op / rr, 0.04)
        self.lc_range_limit_wick_op = self.tp_range_limit_wick_op / rr  # max(self.tp_range_limit_wick_op / rr, 0.04)
        self.lc_price_limit_op = target_price - (self.lc_range_limit_op * target_dir)
        self.lc_price_limit_wick_op = target_price - (self.lc_range_limit_wick_op * target_dir)
        self.lc_change_limit_op = [
                        {"exe": True, "time_after": 0, "trigger": 0.10, "ensure": 0.10 - 0.05},
                        {"exe": True, "time_after": 0, "trigger": 0.20, "ensure": 0.16},
                    ]

        if self.tp_range_limit_wick_op == 0 or self.lc_range_limit_wick_op == 0:
            tk.line_send("tpかLCが０！！")
            self.stop_exe_op = False

    def cal_target_price_oppo_stop(self, margin):
        rr = 1.3  # RR値。ロスカ幅に対する、利確幅の比率
        peaks = self.peaks
        spred = self.spred
        is_exe = True
        s = "    "
        base = self.peaks[0]['latest_body_peak_price']  # self.latest_price
        target_dir = self.l_dir_oppo
        print("@@@@@@@逆方向STOPに関する計算 Dir:", target_dir, "@@@@@@")
        # ■■■ターゲット価格の算出
        if target_dir == -1:
            target_price = base - margin
        else:
            target_price = base + margin

        # ■■■ラインの情報を取得
        line_info = self.predict_lines_wrap_up_rev(target_price, target_dir)  # self.lower等を算出
        tp_range_line = line_info['tp_range']
        tp_price_line = line_info['tp_price']
        lc_range = line_info['lc_range']
        lc_price = line_info['lc_price']
        lc_change_line = line_info['lc_change']
        is_exe_stop = line_info['is_exe']

        if line_info['tp_range'] == 0 or line_info['lc_range'] == 0:
            tk.line_send("tpかLCが０！！")
            return 1999

        # 明示的に、結果を代入していく
        self.target_price_stop_op = target_price  # ストップ（順張り）用の価格
        self.tp_price_stop_op = line_info['tp_price']
        self.tp_range_stop_op = line_info['tp_range']
        self.lc_price_stop_op = line_info['lc_price']
        self.lc_range_stop_op = line_info['lc_range']
        self.lc_change_stop_op = lc_change_line
        self.stop_exe_op = is_exe_stop
        # 参考用（基本的に未使用）
        self.tp_price_stop_wick_op = 0
        self.tp_range_stop_wick_op = 0
        self.lc_price_stop_wick_op = 0
        self.lc_range_stop_wick_op = 0

    def cal_target_price_limit(self, margin):
        base = self.latest_price
        base = self.peaks[0]['latest_body_peak_price']
        # ターゲットプライスを算出
        if self.l_dir == 1:
            self.target_price_limit = base - margin
        else:
            self.target_price_limit = base + margin

        # LCの価格を算出
        if self.l_dir == 1:
            self.lc_price_limit_wick = self.peaks[1]['lowest'] - self.spred  # 他にはlatest_body_peak_price
            self.lc_price_limit = self.peaks[1]['latest_body_peak_price'] - self.spred
        else:
            self.lc_price_limit_wick = self.peaks[1]['highest'] + self.spred
            self.lc_price_limit = self.peaks[1]['latest_body_peak_price'] + self.spred

        # op_r_priceをlcと仮定し、lc_rangeを計算する
        self.lc_range_limit = round(abs(self.lc_price_limit - self.target_price_limit), self.round_digit) + self.spred
        self.lc_range_limit_wick = round(abs(self.lc_price_limit_wick - self.target_price_limit), self.round_digit) + self.spred

        # lc_range用の最小LCレンジの調整（ピークで検討　少ない場合⇒ピークの極値で検討　少ない場合⇒0.05)
        border = 0.04
        if self.lc_range_limit < border:
            # wickまで伸ばしてみる
            self.lc_range_limit = self.lc_range_limit_wick
            if self.lc_range_limit < border:
                # wickも小さい場合、両方とも伸ばしてしまう。
                self.lc_range_limit = border
                self.lc_range_limit_wick = border
        # 大きすぎる場合も抑える
        self.lc_range_limit = max(border, min(self.lc_range_limit, 0.18))
        # self.lc_range_limit = min(self.lc_range_limit, 0.10)  # max(0.05, min(self.op_r_range_limit, 0.18))

    def cal_target_price_stop(self, margin):
        s = "    "
        peaks = self.peaks
        spred = self.spred
        base_price = self.latest_price  # peaks[0]['latest_body_peak_price']  # self.latest_price
        target_dir = self.l_dir
        self.stop_order_cancel = 999  # 途中返却の可能性もあるため、最初から入れておく
        order_cancel = 0
        margin2 = 0.005
        memo = ""
        rr_b = 1.62  # RR値。ロスカ幅に対する、利確幅の比率
        rr_s = 1.4
        tp_price = tp_range = lc_price = lc_range = 0  # 初期値
        latest = peaks[0]
        river = peaks[1]
        current_time = latest['latest_time_jp']
        lc_change = [
            {"exe": True, "time_after": 0, "trigger": 0.15, "ensure": 0.15 - 0.02},
            {"exe": True, "time_after": 0, "trigger": 0.20, "ensure": 0.16},
            {"exe": True, "time_after": 0, "trigger": 0.30, "ensure": 0.25},
        ]
        print("＠＠＠＠＠STOPについての計算 dir:", target_dir, "@@@@@")

        # ■■■ターゲットプライスを算出
        # margin = 0
        if target_dir == 1:
            target_price = base_price + margin
        else:
            target_price = base_price - margin

        # ■■■ラインの情報から、利確、ロスカの候補を算出する
        upper_lines = self.predict_line_upper(base_price)  # target_price
        # lower
        lower_lines = self.predict_line_lower(base_price)  # target_price
        self.upper_lines = upper_lines
        self.lower_lines = lower_lines

        # TPとLCでも格納
        if target_dir == 1:
            # 直近価格＝注文価格の場合 いずれも直近価格から近い順に並んでいる。
            tp_lines = self.upper_lines
            lc_lines = self.lower_lines
        else:
            # 直近価格＝注文価格の場合
            tp_lines = self.lower_lines
            lc_lines = self.upper_lines
        print("TARGET PRICE:", target_price, "BasePrice", base_price)
        print("  TP LINES", len(tp_lines))
        for i, g in enumerate(tp_lines):
            print(
                f"{s}"
                f"Group {i}: median_price = {g['median_price']:.3f}, "
                f"median = {g['median']:.3f}, "
                f"strength = {g['total_strength']}, "
                f"ave_strength = {g['ave_strength']}, "
                f"count = {g['count']}, "
                f"near_far_gap = {g['near_far_gap']}, "
                f"near = {g['near']}, "
                f"near_p = {g['near_price']}, "
                f"far = {g['far']}, "
                f"far_p = {g['far_price']}, "
                f"oldest_time = {g['oldest_time']}, "
                f"newest_time = {g['newest_time']}, "
                f"max_gap_minutes = {g['max_gap_minutes']}, "
                f"max_gap_start = {g['max_gap_start']}, "
                f"max_gap_end = {g['max_gap_end']}, "
                f"prices = {', '.join(map(str, g['prices']))}"
            )
        print("  LC LINES", len(lc_lines))
        for i, g in enumerate(lc_lines):
            print(
                f"{s}"
                f"Group {i}: median_price = {g['median_price']:.3f}, "
                f"median = {g['median']:.3f}, "
                f"total_strength = {g['total_strength']}, "
                f"ave_strength = {g['ave_strength']}, "
                f"count = {g['count']}, "
                f"near_far_gap = {g['near_far_gap']}, "
                f"near = {g['near']}, "
                f"near_p = {g['near_price']}, "
                f"far = {g['far']}, "
                f"far_price = {g['far_price']}, "
                f"oldest_time = {g['oldest_time']}, "
                f"newest_time = {g['newest_time']}, "
                f"max_gap_minutes = {g['max_gap_minutes']}, "
                f"max_gap_start = {g['max_gap_start']}, "
                f"max_gap_end = {g['max_gap_end']}, "
                f"prices = {', '.join(map(str, g['prices']))}"
            )

        # ■解析０　ローソクがかぶりすぐていないかの検証
        # latestを形成する二つのローソクの重なり（Bodyサイズだけではなく、価格的に包括関係にあるか）
        df = self.peaks_class.df_r_original  # これは
        l = peaks[0]
        l_df1 = df.iloc[1]
        l_df2 = df.iloc[2]
        max1 = l_df1['inner_high']
        min1 = l_df1['inner_low']
        max2 = l_df2['inner_high']
        min2 = l_df2['inner_low']
        max1 = l_df1['high']
        min1 = l_df1['low']
        max2 = l_df2['high']
        min2 = l_df2['low']
        width1 = max1 - min1
        width2 = max2 - min2
        overlap = max(0, min(max1, max2) - max(min1, min2))
        # overlap_ratio = overlap / width1 if width1 != 0 else 0  # A基準
        overlap_ratio2 = overlap / (max2 - min2)  # ひとつ前の足が、latestの足と何パーセントかぶっているか
        overlap_ratio = overlap / (max1 - min1)  # latestの何パーセントがそのひとつ前と被っているか
        size_ratio = width2 / width1 if width1 != 0 else 0

        size_condition = width2 >= width1 * 1.3
        overlap_condition = overlap >= width1 * 0.88  # ←ここがA基準
        print(l_df1['time_jp'] ,min1, max1, l_df2['time_jp'], min2, max2, overlap, max1 - min1)
        print("size", size_condition, size_ratio, "overlap1", overlap_ratio, "overlap2", overlap_ratio2)
        if overlap_ratio >= 0.7 and overlap_ratio2 >= 0.7:
            print("がっつりかぶっている")

        # ■解析１　利確とロスカの強さについて
        print("------------------------------------------------------------------")
        tp_len = len(tp_lines)
        lc_len = len(lc_lines)
        print(s, "len比較 tp", tp_len, "lc", lc_len)
        if tp_len >= lc_len * 2.5 or lc_len >= tp_len * 2.5:
            if tp_len > lc_len:
                print(s, "tpが重め　TP取りにくそう")
            else:
                print(s, "lcが重め　LCに行かなそう（TP行きやすいかも）")

        print("kokokokokoo")
        for i, item in enumerate(peaks[:6]):
            print(item["direction"],item["count"],item["latest_time_jp"], item["gap"])



        # ■解析２　TPの位置について
        print("-tp-----------------------------------------------------------------")
        # 一つ目のそこそこ強い物を取得する
        first_tp_line = {}
        strongest_line = {}
        if tp_len != 0:
            # 最も近く、そこそこの強さのラインを取得
            for i, line in enumerate(tp_lines):
                strength = line['total_strength']
                count = line['count']

                if strength > 5 and strength / count > 3:
                    first_tp_line = line
                    break
            # 一番大きいラインを取得
            strongest_line = max(tp_lines, key=lambda x:x['total_strength'])
        else:
            # tp linesが0本の場合
            print(s, "TP linesが0本です(強引にオーダーをコード）")
            lc_range = 0.03
            lc_price = target_price - (lc_range * target_dir)
            tp_range = lc_range * rr_b
            tp_price = target_price + (tp_range * target_dir)
            self.tp_price_stop = tp_price
            self.tp_range_stop = tp_range
            self.lc_price_stop = lc_price
            self.lc_range_stop = lc_range
            self.lc_change_stop = lc_change
            self.stop_order_cancel = order_cancel
            return 0
        if len(first_tp_line) == 0:
            print(s, "該当のTPなし")
            first_tp_line = tp_lines[0]
            strongest_line = tp_lines[0]
        print(" 初回のTPLine", first_tp_line)
        print("            streng", first_tp_line['total_strength'], "count", first_tp_line['count'], "gap", first_tp_line['median'])
        print(" もっとも強いTPline", strongest_line)
        print("            streng", strongest_line['total_strength'], "count", strongest_line['count'], "gap", strongest_line['median'])
        if strongest_line['ave_strength'] >= 6:
            # 8を含んでいそうな場合(平均が6以上の強さ）
            time_gap_min = gene.cal_str_time_gap(peaks[0]['latest_time_jp'], strongest_line['oldest_time'])['gap_abs_min']
            print(s, "強いラインは、突破しかかっている状況", peaks[0]['latest_time_jp'], strongest_line['oldest_time'])
            if time_gap_min <= 80:
                print(s, "時間差短め⇒突破する可能性あり・・？")
            else:
                print(s, "時間差だいぶ前⇒強い抵抗にもう一度上当たりにいく可能性")

        # 時間的に直近のもののみで判定してみる
        print("currenttime", current_time)
        filtered_groups = []
        # for i, item in enumerate(tp_lines):
        #     print("tttt", item['oldest_time'], gene.cal_str_time_gap(current_time, item['oldest_time'])['gap_abs_min'])
        #     if gene.cal_str_time_gap(current_time, item['oldest_time'])['gap_abs_min'] <= 60:
        #         print("   これそうだよ！")
        #         filtered_groups.append(item)
        filtered_groups = [
            g for g in tp_lines
            if gene.cal_str_time_gap(current_time, g['oldest_time'])['gap_abs_min'] <= 60
        ]
        print("  TP LINES（直近）", len(filtered_groups))
        for i, g in enumerate(filtered_groups):
            print(
                f"{s}"
                f"Group {i}: median_price = {g['median_price']:.3f}, "
                f"median = {g['median']:.3f}, "
                f"strength = {g['total_strength']}, "
                f"ave_strength = {g['ave_strength']}, "
                f"count = {g['count']}, "
                f"near_far_gap = {g['near_far_gap']}, "
                f"near = {g['near']}, "
                f"near_p = {g['near_price']}, "
                f"far = {g['far']}, "
                f"far_p = {g['far_price']}, "
                f"oldest_time = {g['oldest_time']}, "
                f"newest_time = {g['newest_time']}, "
                f"max_gap_minutes = {g['max_gap_minutes']}, "
                f"max_gap_start = {g['max_gap_start']}, "
                f"max_gap_end = {g['max_gap_end']}, "
                f"prices = {', '.join(map(str, g['prices']))}"
            )

        print("kokokokokoo")
        for i, item in enumerate(peaks[:6]):
            print(item["count"], item["gap"])


        # ■解析３　LCの強さについて(LCが強い場合それ以上行かなそうだから、おおきく出てもよい・・？）
        first_lc_line = {}
        if lc_len != 0:
            for i, line in enumerate(lc_lines):
                far = line['far']
                med_price = line['median_price']
                med = line['median']
                near_price = line['near_price']
                strength = line['total_strength']
                count = line['count']

                if strength > 5:
                    first_lc_line = line
                    break
        else:
            # lc linesが0本
            print(s, "lc_linesが０本です")
            self.stop_order_cancel = 90
            return 0
        if len(first_lc_line) == 0:
            print(s, "該当のLCなし")
            first_lc_line = lc_lines[0]

        print(" 初回のLCline", first_lc_line)
        print("            ", first_lc_line['total_strength'], first_lc_line['count'], first_lc_line['far'])

        # 一部の変数化
        latest_peak_range = round(abs(latest['latest_body_peak_price'] - latest['oldest_body_peak_price']), 3)
        latest_peak_price = base_price - (latest_peak_range * target_dir)
        latest_peak_wick_price = round(river["lowest"] if latest["direction"] == 1 else river["highest"], 3)
        latest_peak_wick_range = abs(target_price - latest_peak_wick_price) * 1.2
        latest_peak_wick_price = target_price - (latest_peak_wick_range * target_dir)

        # latest_peak_wick_range = round((latest["latest_body_peak_price"] - latest["lowest"]) + margin2 if latest["direction"] == 1 else (latest["highest"] - latest["latest_body_peak_price"]) + margin2, 3)
        # latest_peak_wick_range = latest_peak_wick_range * 1.2
        # latest_peak_wick_price = base_price - (latest_peak_wick_range * target_dir)

        # print(s, latest["latest_body_peak_price"], latest["lowest"], latest["highest"], latest['gap'])
        # print(s, "各LCの計算を先にしておく", latest_peak_price, latest_peak_range, latest_peak_wick_price, latest_peak_wick_range)

        # ベースはこれ
        lc_range = latest_peak_wick_range
        lc_price = latest_peak_wick_price
        tp_range = lc_range * rr_b
        tp_price = target_price + (tp_range * target_dir)

        if first_lc_line['total_strength'] >= 10 and first_lc_line['count'] >= 3:
            if first_lc_line['far'] >= 0.03:
                print(s, "@@@lc lineが強いため、このLC以上には負けなそう？？　LCをベースにTPを決める")
                lc_strength = first_lc_line['total_strength']
                if first_tp_line['far'] <= tp_range:
                    # 仮のtp range(temp_tp_range)が現実的かを確認する
                    print(s, " @@@かなりいい感じのTP？")
                    tp_range = tp_range
                    tp_price = target_price + (tp_range * target_dir)
                else:
                    print(s, "@@@temp TPに至る前に、強い抵抗線有 tempTP range", tp_range, "FarRange", first_tp_line['far'], "lc", lc_range)
                    if lc_strength <= first_tp_line['total_strength']:
                        print(s, "TPの抵抗線のほうが強い　⇒　TPに行きにくい")
                        order_cancel = 1
                    else:
                        print(s, "@@@TPの抵抗線のほうが弱い　⇒　TPに行きやすい　⇒　オーダーOK？　ベース通り")
            else:
                print(s, "@@@lc lineが強いが、近すぎる ⇒　すぐ抵抗されてTP側に行くのでは？　FarをLCとする")
                lc_range = max(first_lc_line['far'], latest_peak_wick_range)
                lc_price = target_price - (lc_range * target_dir)
                tp_range = lc_range * rr_b
                tp_price = target_price + (tp_range * target_dir)
        else:
            # lc_range = max(first_lc_line['far'], latest_peak_wick_range)
            # lc_price = first_lc_line['far_price']
            lc_strength = first_lc_line['total_strength']
            # temp_tp_range = lc_range * rr_b
            # tp_price = target_price + (temp_tp_range * target_dir)
            print(s, "@@@lc lineがそんなに強くない　⇒　もっと負けの方向に行くかもしれないため、警戒", lc_range)
            if first_tp_line['far'] <= tp_range:
                # 仮のtp range(temp_tp_range)が現実的かを確認する
                print(s, "@@@かなりいい感じのTP？ ベース通り")
                tp_range = tp_range
                tp_price = target_price + (tp_range * target_dir)
            else:
                print(s, "@@@temp TPに至る前に、強い抵抗線有 tempTP range", tp_range, "FarRange", first_tp_line['far'], lc_range)
                if lc_strength <= first_tp_line['total_strength']:
                    if 0.02 < tp_range <= 0.05:
                        print(" とりあえずTP短いので狙っておく ベース通り")
                    else:
                        print(s, "@@@TPの抵抗線のほうが強い　⇒　TPに行きにくい")
                        order_cancel = 3
                else:
                    print(s, "@@@それでも、TPの抵抗線のほうが弱い　⇒　TPに行きやすい　⇒　オーダーOK？")
                    temp_rr = round(tp_range / lc_range,2)
                    print(s, "理論RR", temp_rr, lc_range, tp_range)
                    if temp_rr < 1:
                        print(s, "tp幅が取れていない　RR短め設定＆LCchangeあり？")
                        rr = 1.2
                    elif temp_rr <= 1.3:
                        rr = 1.4
                        print(s, "若干RR取れている場合 RR１．４位に拡張")
                    elif temp_rr <= 1.8:
                        rr = 1.6
                        print(s, "TPがちょうど理想の状態")
                    else:
                        rr = 1.6
                    tp_range = round(lc_range * rr, 3)
                    tp_price = target_price + (tp_range * target_dir)

        print("最終結果(STOP)", order_cancel)
        if (tp_price == 0 or tp_range == 0 or lc_price == 0 or lc_range == 0) and order_cancel == 0:
            print(s, "０を含むオーダーになりそう！！おかしい　tp_price", tp_price, "tp_range", tp_range, lc_price, lc_range)
            order_cancel = 100
        if lc_range >= 0.12:
            print(s, "LC rangeが予想以上に大きい！！")
            tk.line_send("LCやTPが大きいため修正")
            lc_range = 0.12
            lc_price = target_price - (lc_range * target_dir)
            tp_range = lc_range * rr_b
            tp_price = target_price + (tp_range * target_dir)
            # order_cancel = 200

        print(s, "LC Changeテスト用")
        print(s, "rr1.6:", tp_range, "tt1.4", lc_range * rr_s, "lc_range", lc_range)
        if lc_range * rr_b - lc_range * rr_s >= 0.02:
            # lc_changeでensureまで0.02取れる場合は、攻めてみる
            lc_change = [
                {"exe": True, "time_after": 0, "trigger": lc_range * rr_b, "ensure": lc_range * rr_s},
                {"exe": True, "time_after": 0, "trigger": 0.20, "ensure": 0.16},
                {"exe": True, "time_after": 0, "trigger": 0.30, "ensure": 0.25},
            ]
            tp_range = 0.4
            tp_price = target_price + (tp_range * target_dir)
            memo = memo + "LcChange実装"
        memo = memo + "orderCancel:" + str(order_cancel)

        if tp_range == 0 or lc_range == 0:
            tk.line_send("tpかLCが０！！ long")
            return 1999

        # line_info = self.predict_lines_wrap_up(target_price, target_dir)  # self.lower等を算出
        # 明示的に、結果を代入していく
        self.target_price_stop = target_price  # ストップ（順張り）用の価格
        self.tp_price_stop = tp_price
        self.tp_range_stop = tp_range
        self.lc_price_stop = lc_price
        self.lc_range_stop = lc_range
        self.lc_change_stop = lc_change
        self.stop_order_cancel = order_cancel
        self.stop_memo = memo
        # 参考
        self.tp_price_stop_wick = 0
        self.tp_range_stop_wick = 0
        self.lc_price_stop_wick = 0
        self.lc_range_stop_wick = 0

    def predict_line_group(self, lines, order=1, threshold=0.017):
        """
        lines: 辞書のリスト
            必須キー:
                - latest_body_peak_price
                - peak_strength
                - time（datetime想定）
        order: 1=昇順, -1=降順
        """

        import statistics
        from datetime import datetime

        threshold = 0.03
        price_key = "latest_body_peak_price"

        # --- 価格でソート ---
        data_sorted = sorted(lines, key=lambda x: x[price_key])

        # --- グループ化 ---
        groups = []
        current_group = []

        for item in data_sorted:
            if not current_group:
                current_group.append(item)
                continue

            min_price = current_group[0][price_key]

            if (item[price_key] - min_price) <= threshold:
                current_group.append(item)
            else:
                groups.append(current_group)
                current_group = [item]

        if current_group:
            groups.append(current_group)

        # --- グループ情報作成 ---
        group_info = []

        for g in groups:
            # ---- 価格系 ----
            prices = sorted([x[price_key] for x in g])
            median_price = statistics.median(prices)
            total_strength = sum(x["peak_strength"] for x in g)

            # ---- 時間系 ----
            times_raw = [x["time"] for x in g]

            # datetime前提（文字列なら変換）
            if isinstance(times_raw[0], str):
                times = sorted([
                    datetime.strptime(t, "%Y/%m/%d %H:%M:%S")
                    for t in times_raw
                ])
            else:
                times = sorted(times_raw)

            oldest_time = times[0]
            newest_time = times[-1]

            # ---- 最大ギャップ ----
            max_gap = 0
            gap_start = None
            gap_end = None

            if len(times) >= 2:
                for t1, t2 in zip(times, times[1:]):
                    gap = (t2 - t1).total_seconds() / 60  # 分

                    if gap > max_gap:
                        max_gap = gap
                        gap_start = t1
                        gap_end = t2

            # ---- 期間全体（参考用）----
            total_span = (newest_time - oldest_time).total_seconds() / 60 if len(times) >= 2 else 0

            group_info.append({
                "median_price": median_price,
                "count": len(g),
                "total_strength": total_strength,
                "ave_strength": round(total_strength / len(g), 2),
                "prices": prices,

                # 時間情報
                "oldest_time": oldest_time,
                "newest_time": newest_time,

                # ←今回の主役
                "max_gap_minutes": max_gap,
                "max_gap_start": gap_start,
                "max_gap_end": gap_end,

                # おまけ（あとで使える）
                "total_span_minutes": total_span,
            })

        # --- 並び替え ---
        group_info = sorted(
            group_info,
            key=lambda x: x["median_price"],
            reverse=(order == -1)
        )

        return group_info


    def predict_line_lower(self, target_price):
        # 現在価格より下にある、抵抗線候補を列挙する
        print("     PREDICT LINE LOWER")
        # 変数置換
        margin = 0.000
        peaks = self.peaks[0:35]
        price = "latest_body_peak_price"
        # target_price = self.latest_price
        lines = []

        for i, item in enumerate(peaks):
            if i == 0:
                continue

            if item[price] < target_price + margin:
                temp = self.line_detect(i)
                if temp['same_price_list_comp_total'] >= 5:
                    # print("下の価格あったよ", item['latest_time_jp'], temp['same_price_list_comp_total'], item[price], item['direction'])
                    lines.append(item)
                else:
                    pass
                    # print("   ", item['latest_time_jp'], temp['same_price_list_comp_total'], item[price], item['direction'])

        # グルーピング
        line_group = self.predict_line_group(lines, -1, 0.023)
        # 情報の付与
        for d in line_group:  # 差分を追加しておく
            # if x - target_price
            d["median"] = round(target_price - d["median_price"], 3)
            d['near_price'] = min(d['prices'], key=lambda x: target_price - x)
            d['far_price'] = max(d['prices'], key=lambda x: target_price - x)
            # 差を計算

            d["near"] = round(target_price - d['near_price'], 3)
            d["far"] = round(target_price - d['far_price'], 3)
            d['near_far_gap'] = round(abs(max(d['prices'], key=lambda x: target_price - x) - min(d['prices'], key=lambda x: target_price - x)), 3)

        # 若干さかのぼって（価格を参照して）取得しているが、medianが離れている場合、除外する。
        final_lines = []
        s = "    "
        for d in line_group:
            # Lowerなので、ターゲットよりちょい上のものを入れるか入れないかの判定
            # medianが0.008以上さかのぼっている場合は、無視する。
            if d["median"] <= -0.008:
                continue
            # 基本は追加
            final_lines.append(d)

        return final_lines

    def predict_line_upper(self, target_price):
        # 現在価格より上にある、抵抗線候補を列挙する
        print("     PREDICT LINE UPPER")
        # 変数置換
        margin = 0.000
        peaks = self.peaks[0:35]
        # print(peaks[0]['latest_time_jp'], "-", peaks[-1]['latest_time_jp'])
        price = "latest_body_peak_price"
        # target_price = self.latest_price
        lines = []

        for i, item in enumerate(peaks):
            if i == 0:
                continue

            if item[price] >= target_price - margin:
                temp = self.line_detect(i)
                if temp['same_price_list_comp_total'] >= 5:
                    # print("上の価格あったよ", item['latest_time_jp'], temp['same_price_list_comp_total'], item[price], item['direction'])
                    lines.append(item)
                else:
                    pass
                    # print("   ", item['latest_time_jp'], temp['same_price_list_comp_total'], item[price], item['direction'])

        # グルーピング
        line_group = self.predict_line_group(lines, 1)

        # 情報の付与
        for d in line_group:  # 差分を追加しておく
            # Upperにおいて通常の向き
            d["median"] = round(target_price - d["median_price"], 3)
            d['near_price'] = min(d['prices'], key=lambda x: x - target_price)
            d['far_price'] = max(d['prices'], key=lambda x: x - target_price )
            # 差を計算
            d["near"] = round(d['near_price'] - target_price, 3)
            d["far"] = round(d['far_price'] - target_price, 3)
            d['near_far_gap'] = round(abs(max(d['prices'], key=lambda x: target_price - x) - min(d['prices'], key=lambda x: target_price - x)), 3)


        # 若干さかのぼって（価格を参照して）取得しているが、medianが離れている場合、除外する。
        final_lines = []
        s = "    "
        for d in line_group:
            # Ｕｐｐｅｒなので、ターゲットよりちょい下のものを入れるか入れないかの判定
            # medianが0.008以上さかのぼっている場合は、無視する。
            if d["median"] <= -0.008:
                print("MEDIANijyou ", d['median'])
                continue
            # 基本は追加
            print("追加", d,['median_price'], d['median'])
            final_lines.append(d)

        return final_lines

    def line_detect(self, target_no):
        peaks_class = self.peaks_class
        peaks_with_same_price_list = peaks_class.peaks_with_same_price_list
        target_no_time = peaks_class.peaks_original[target_no]['latest_time_jp']
        target_no_time = datetime.strptime(target_no_time, "%Y/%m/%d %H:%M:%S")

        if len(peaks_with_same_price_list) == 0:
            print("同一価格リストサイズ０")
            return 0
        # 変数代入＆表示
        # Breakを許容するタイプのSamePriceList
        same_price_list = peaks_with_same_price_list[target_no]["same_price_list_till_break"]  # ターンが抵抗線かを調べる。（リバーではない）
        same_price_list_total = sum(d['item']["peak_strength"] for d in same_price_list)
        same_price_list_till_over_5 = [d for d in peaks_with_same_price_list[target_no]["same_price_list_till_break"] if d["item"]["peak_strength"] >= 5]
        same_price_list_till_over_5_total = sum(d['item']["peak_strength"] for d in same_price_list_till_over_5)

        # breakを許容しないタイプのSamePriceList
        same_price_list0 = peaks_with_same_price_list[target_no]["same_price_list_till_break0"]  # ターンが抵抗線かを調べる。（リバーではない）
        same_price_list0_total = sum(d['item']["peak_strength"] for d in same_price_list0)
        same_price_list_till_break0_5 = [d for d in peaks_with_same_price_list[target_no]["same_price_list_till_break0"] if d["item"]["peak_strength"] >= 5]
        same_price_list_till_break0_5_total = sum(d['item']["peak_strength"] for d in same_price_list_till_over_5)

        # ブレークとか気にしないやつ
        same_price_list_comp = peaks_with_same_price_list[target_no]["same_price_list"]  # ターンが抵抗線かを調べる。（リバーではない）
        same_price_list_comp_total = sum(d['item']["peak_strength"] for d in same_price_list_comp)

        # 方向
        d = same_price_list[0]['item']['direction']
        target_price = same_price_list[0]['item']['latest_body_peak_price']

        if same_price_list_total <= 2:
            line_strength = 0
            # print(self.s, "抵抗なし(自身のみの検出）")
        elif same_price_list_total <= 4:
            line_strength = 1
            # print(self.s, "引っ掛かり程度の抵抗線")
        elif same_price_list_total < 10:  # 12は5が二つと2が一つを想定。
            if same_price_list_till_over_5_total >= 10:
                # print(self.s, "準 相当強めの抵抗線", same_price_list_total, same_price_list_till_over_5_total)
                line_strength = 7
            elif same_price_list_till_over_5_total >= 5 and len(same_price_list) >= 2:
                # print(self.s, "軽いダブルトップ抵抗線", same_price_list_total, same_price_list_till_over_5_total)
                line_strength = 5
            else:  # =5の場合は、自身のみ
                # print(self.s, "５自身のみか、複数の２", same_price_list_total, same_price_list_till_over_5_total)
                line_strength = 3
        else:
            # 12以上
            if same_price_list_till_over_5_total >= 10:
                # print(self.s, "相当強めの抵抗線", same_price_list_total, same_price_list_till_over_5_total)
                line_strength = 10
            else:
                # print(self.s, "強めの抵抗線", same_price_list_total, same_price_list_till_over_5_total)
                line_strength = 7

        # 狭い脚判定
        if len(same_price_list) == 2:
            latest_time = same_price_list[0]['item']['latest_time_jp']
            oldest_time = same_price_list[1]['item']['latest_time_jp']
            ans = gene.cal_str_time_gap(latest_time, oldest_time)
            # print(self.s, ans['gap_abs']/60, "分", latest_time, oldest_time)

        return {
            "same_price_list": same_price_list,
            "same_price_list_total": same_price_list_total,
            "same_price_list_till_over_5": same_price_list_till_over_5,
            "same_price_list_till_over_5_total": same_price_list_till_over_5_total,
            "same_price_list0": same_price_list0,
            "same_price_list0_total": same_price_list0_total,
            "same_price_list_till_break0_5": same_price_list_till_break0_5,
            "same_price_list_till_break0_5_total": same_price_list_till_break0_5_total,
            "same_price_list_comp": same_price_list_comp,
            "same_price_list_comp_total": same_price_list_comp_total,
            "line_strength": line_strength,
            "d": d,
            "target_price": target_price,
            "mes": "[" + str(d) + "抵抗線]" + str(target_price) + " "
        }

    def predict_lines_wrap_up(self, target_price, target_dir):
        # LINEからTPやLCの値を提案する。
        ss = "   "
        s = "    "

        # # 上下で格納(LINEの生成）
        # if len(self.upper_lines) + len(self.lower_lines) == 0:
        #     # upper
        #     upper_lines = self.predict_line_upper(target_price)
        #     # lower
        #     lower_lines = self.predict_line_lower(target_price)
        #     self.upper_lines = upper_lines
        #     self.lower_lines = lower_lines
        # else:
        #     # 既に生成済の場合は、生成しない。
        #     print(s, "すでにUpperLineとLowerLine検索実施済み")
        upper_lines = self.predict_line_upper(target_price)
        # lower
        lower_lines = self.predict_line_lower(target_price)
        self.upper_lines = upper_lines
        self.lower_lines = lower_lines

        # TPとLCでも格納
        if target_dir == 1:
            # 直近価格＝注文価格の場合 いずれも直近価格から近い順に並んでいる。
            tp_lines = self.upper_lines
            lc_lines = self.lower_lines
        else:
            # 直近価格＝注文価格の場合
            tp_lines = self.lower_lines
            lc_lines = self.upper_lines
        print("TARGET PRICE:", target_price)
        print("  TP LINES", len(tp_lines))
        for i, g in enumerate(tp_lines):
            print(
                f"{s}"
                f"Group {i}: median_price = {g['median_price']:.3f}, "
                f"median = {g['median']:.3f}, "
                f"strength = {g['total_strength']}, "
                f"count = {g['count']}, "
                f"near = {g['near']}, "
                f"near_p = {g['near_price']}, "
                f"far = {g['far']}, "
                f"far_p = {g['far_price']}, "
                f"prices = {', '.join(map(str, g['prices']))}"
            )
        print("  LC LINES", len(lc_lines))
        for i, g in enumerate(lc_lines):
            print(
                f"{s}"
                f"Group {i}: median_price = {g['median_price']:.3f}, "
                f"median = {g['median']:.3f}, "
                f"total_strength = {g['total_strength']}, "
                f"count = {g['count']}, "
                f"near = {g['near']}, "
                f"near_p = {g['near_price']}, "
                f"far = {g['far']}, "
                f"far_price = {g['far_price']}, "
                f"prices = {', '.join(map(str, g['prices']))}"
            )

        # ■■処理
        #TPについて
        print("新判定検証")
        # [0]で固定ではなく、最初に有効なもの、探すのがいいかも
        # count1 strength5 のみは除外。それ以外。
        print("TP幅検討")
        tp_price_min = tp_range_min = tp_price = tp_range = 0
        lc_change = []
        lc_change_temp = []
        rr = 1.6
        trigger_m = 0.01
        ensure_m = 0.01
        order_cancel = 0  # 0の場合はオーダー通常通りあり　それ以外はオーダー発行無しを示すフラグ＋種類
        if len(tp_lines) != 0:
            for i, line in enumerate(tp_lines):
                far = line['far']
                med_price = line['median_price']
                med = line['median']
                far_price = line['far_price']
                near = line['near']
                near_price = line['near_price']
                strength = line['total_strength']
                count = line['count']
                print("  TP検討", med_price)
                # 判定
                if count == 1:
                    if strength == 8:
                        # トレンドで新領域に入った場合
                        print(s, "新トレンドに入ったところ", med_price, "count:", count, "strength", strength)
                        if i == 0 or tp_price_min == 0:
                            tp_price_min = med_price
                            tp_range_min = med
                            lc_change.append(
                                {"exe": True, "time_after": 0, "trigger": med + trigger_m, "ensure": med - ensure_m,
                                 "trigger_price": med_price + trigger_m, "ensure_price": med_price - ensure_m})
                    elif strength <= 5:
                        print(s, "単発ライン⇒基本無視(LC change候補）", med_price, "count:", count, "strength", strength)
                        lc_change_temp.append(
                            {"exe": True, "time_after": 0, "trigger": med, "ensure": med,
                             "trigger_price": med_price, "ensure_price": med_price})
                elif 2 <= count <= 3:
                    if strength > 10:
                        print(s, "比較的抵抗するライン(LCチェンジ候補)")
                        if far <= 0.030:
                            pass
                            print(s, "farですら近い⇒TP　＆　初回の場合、この取引は危ない可能性大")
                            order_cancel = 1
                            break
                        else:
                            print(s, "farがある程度遠い。midLCChangeのEnsureを短めでよい？。発散してほしいが、逃げのLC change")
                            rr = 1.4
                            if i == 0 or tp_price_min == 0:
                                tp_price_min = med_price
                                tp_range_min = med
                            lc_change.append(
                                {"exe": True, "time_after": 0, "trigger": med + trigger_m, "ensure": med - ensure_m,
                                 "trigger_price": med_price + trigger_m, "ensure_price": med_price - ensure_m})
                    else:
                        print(s, "若干の抵抗だが、中粒の集合感。抵抗は弱。LC_changeはtrigger攻め気味。")
                        trigger_m = 0.01
                        ensure_m = 0.01
                        lc_change.append(
                            {"exe": True, "time_after": 0, "trigger": med + trigger_m, "ensure": med - ensure_m,
                             "trigger_price": med_price + trigger_m, "ensure_price": med_price - ensure_m})
                elif count >= 4:
                    # カウントが多いので、そろそろ発散の可能性（小粒でない限り
                    if strength < count * 3:
                        if strength >= 14:
                            print(s, "小粒だが、多い⇒微抵抗しそうだが突破の可能性もあるため、LC_Changeとして追加(4pips程度のおおきめの余裕が欲しい）")
                            if med <= 0.01:
                                print(s, "　極めて近距離に抵抗線。⇒無視が基本")
                                order_cancel = 2
                                break
                            else:
                                if i == 0 or tp_price_min == 0:
                                    tp_price_min = med_price
                                    tp_range_min = med
                                trigger_m = 0.002
                                ensure_m = 0.01
                                lc_change.append(
                                    {"exe": True, "time_after": 0, "trigger": med + trigger_m, "ensure": med - ensure_m,
                                     "trigger_price": med_price + trigger_m, "ensure_price": med_price - ensure_m})
                        else:
                            print(s, "カウントは多いが、小粒ぞろい。抵抗しないと推定")
                    elif strength <= 35:
                        print(s, "かなり強い抵抗がある⇒これはフラッグの可能性もあるが、抵抗されそう。TPはここで固定にした方がいいかも。")
                    else:
                        # 強そうな抵抗線。LCChangeを基本利確レベルで入れる
                        if med <= 0.03:
                            print(s, "近いところに、カウントの多いLINEあり⇒突破目前（フラッグの先頭？？！）")
                            rr = 1.6
                        else:
                            rr = 1.4  # 弱気
                            print(s, "LC change追加")
                            if i == 0 or tp_price_min == 0:
                                tp_price_min = med_price
                                tp_range_min = med
                            lc_change.append(
                                {"exe": True, "time_after": 0, "trigger": med + trigger_m, "ensure": med - ensure_m,
                                 "trigger_price": med_price + trigger_m, "ensure_price": med_price - ensure_m})
        else:
            # TP LINESが０この場合
            print("TP linesが0本")
            lc_change.append(
                {"exe": True, "time_after": 0, "trigger": 0.04, "ensure": 0.04,
                 "trigger_price": 0, "ensure_price": 0})

        # 調整
        # LC_Changeの調整
        print("LC の適正値の検討")
        if len(lc_change) == 0:
            # lc_changeが０件の場合は、規定値を入れる。やむなし。
            if len(lc_change_temp) == 0:
                print("　lc_changeが０、どっちも０なんですけど")
                lc_change = [
                    {"exe": True, "time_after": 0, "trigger": 0.15, "ensure": 0.15 - 0.02},
                    {"exe": True, "time_after": 0, "trigger": 0.20, "ensure": 0.16},
                    {"exe": True, "time_after": 0, "trigger": 0.30, "ensure": 0.25},
                ]
            else:
                print("　lc_changeが０のため、tempと差し替え")
                lc_change = lc_change_temp
        else:
            # lc_changeがある場合、調整。
            # lc_rangeの初回が遠い場合、tempに入っている物を付け足す
            if lc_change[0]['trigger'] >= 0.07:
                print(s, "初回のLcChangeがおおきい⇒temp_lc(仮のやつ）を探して0.08程度のものを探して追加する")
                lc_change_exist_temp = False
                for i, line in enumerate(lc_change_temp):
                    if 0.07 <= line['trigger'] <= 0.15:
                        # ちょうどいいのがある場合
                        lc_change_exist_temp = True
                        med = line['trigger']
                        med_price = line['trigger_price']
                        lc_change.append(
                            {"exe": True, "time_after": 0, "trigger": round(med - 0.008, 3), "ensure": round(med - 0.05, 3),
                             "trigger_price": round(med_price - 0.008, 3), "ensure_price": round(med_price - 0.05, 3)})
                        print(s, "追加分",
                              {"exe": True, "time_after": 0, "trigger": round(med - 0.008, 3),
                               "ensure": round(med - 0.05, 3),
                               "trigger_price": round(med_price - 0.008, 3),
                               "ensure_price": round(med_price - 0.05, 3)})
                if not lc_change_exist_temp:
                    # ちょうどいいのが無かった場合
                    lc_change.extend(
                        [
                            {"exe": True, "time_after": 0, "trigger": 0.10, "ensure": 0.10 - 0.05},
                            {"exe": True, "time_after": 0, "trigger": 0.20, "ensure": 0.16},
                        ]
                    )

            lc_change.sort(key=lambda x: x["trigger"])
        print(s, "最終のLC change")
        # roundを実施
        lc_change = [
            {
                **d,
                "trigger": round(d.get("trigger", 0), 3),
                "ensure": round(d.get("ensure", 0), 3)
            }
            for d in lc_change
        ]
        # 表示
        for i, item in enumerate(lc_change):
            print("  ", item)

        # RR情報
        st = "ensure"  # trigger
        peaks = self.peaks
        rr = 1.4
        tp_range_from_lc_change = lc_change[0][st]  # lc_change[0]['ensure]
        tp_price_form_lc_change = target_price + (target_dir * lc_change[0][st])
        lc_range_from_rr = round(tp_range_from_lc_change / rr, 2)
        lc_price_from_rr = round(target_price - (target_dir * lc_range_from_rr), 2)
        lc_price_river = peaks[1]['latest_body_peak_price'] - (0 * target_dir)  # 調整用もつけとく
        lc_range_river = round(abs(lc_price_river - target_price), 3)
        real_rr = round(abs(tp_range_from_lc_change / lc_range_river), 2)
        tp_range_from_lc = lc_range_river * rr
        tp_price_from_lc = round(target_price + (target_dir * tp_range_from_lc), 3)
        print(s, "基本的な利確等の情報 target_price", target_price)
        print(s, "利確幅(lc_changeの最低値)：", tp_range_from_lc_change, tp_price_form_lc_change)
        print(s, "RRを基に算出したlc_range", round(tp_range_from_lc_change / rr, 2), lc_price_from_rr)
        print(s, "本来lcにしたいrangeとpriceとRR", lc_range_river, lc_price_river, real_rr)
        print(s, "本来lcを採用した場合のrr基準のTP range＆price", tp_range_from_lc, tp_price_from_lc)
        print("")

        # メモ
        memo = ""
        # ■■■■パターン２　（LCからTPを決める方法を試す）
        # lc linesからの見解
        suggest_lc_price = 0  # latest_wick_peak_price  , latest_body_peak_price
        if len(lc_lines) != 0:
            if len(lc_lines) == 1:
                print("lc linesが1本")
                lc_line = lc_lines[0]
                print(lc_line)
                if lc_line['total_strength'] == 8:
                    print("ピークの中のピークのため、突破したらでかい動きに。(髭含めないLCで構える）")
                    suggest_lc_price = peaks[1]['latest_wick_peak_price']
        else:
            print(s, "lc linesが0本")


        if lc_range_river <= 0.013:
            print(s, "lc_が狭すぎるのでさすがに手を出さない", lc_range_river)
            order_cancel = 3
        elif lc_range_river <= 0.04:
            print(s, "lc狭いので、lc_priceをヒゲ＊1pipsに変更 and RRを下げる", lc_range_river, peaks[1]['latest_wick_peak_price'])
            rr = 1.2
            # 以下再計算
            lc_price_river = peaks[1]['latest_wick_peak_price'] - (0.01 * target_dir)  # 調整用もつけとく
            print("変更後", lc_price_river)
            lc_range_river = round(abs(lc_price_river - target_price), 3)
            real_rr = round(abs(tp_range_from_lc_change / lc_range_river), 2)
            tp_range_from_lc = lc_range_river * rr
            tp_price_from_lc = round(target_price + (target_dir * tp_range_from_lc), 3)
        else:
            rr = 1.6

        tp_range_from_lc = lc_range_river * rr
        result = [d for d in lc_change if d.get("ensure", 0) >= tp_range_from_lc]
        if len(result) == 0:
            print(s, "0の場合、そのまま利確幅にする ＆　プログラムの調整としてLC changeを入れておく")
            tp_range_final = tp_range_from_lc
            if len(result) == 0:
                result.extend(
                    [
                        {"exe": True, "time_after": 0, "trigger": 0.10, "ensure": 0.10 - 0.05},
                        {"exe": True, "time_after": 0, "trigger": 0.20, "ensure": 0.16},
                    ]
                )
        else:
            print(s, "ある場合はTP rangeを広げて、利確を上げれるようにする")
            tp_range_final = 0.25
        tp_price_final = target_price + (tp_range_final * target_dir)
        print(s, "さらに最終のLC change。　なおtpは", tp_price_final, tp_range_final)
        for i, item in enumerate(result):
            print("  ", item)

        print(" WrapUpここまで")

        if tp_range_from_lc_change <= 0.05:
            order_cancel = 10
            print("STOPオーダー実施せず")
        return {
            # "tp_range": tp_range_min,  # これはTP　Rangeだが、実際はもう少し上にする可能性がある
            "tp_range": tp_range_final,  # 0.2,
            "tp_price": tp_price_final,
            "lc_range": lc_range_river,
            "lc_price": lc_price_river,
            "lc_change": result,
            "order_cancel": order_cancel,
            "memo": memo,
        }

    def predict_lines_wrap_up_rev(self, target_price, target_dir):
        # LINEからTPやLCの値を提案する。
        ss = "   "
        s = "    "

        # upper
        upper_lines = self.predict_line_upper(target_price)
        # lower
        lower_lines = self.predict_line_lower(target_price)
        self.upper_lines = upper_lines
        self.lower_lines = lower_lines

        # TPとLCでも格納
        if target_dir == 1:
            # 直近価格＝注文価格の場合 いずれも直近価格から近い順に並んでいる。
            tp_lines = self.upper_lines
            lc_lines = self.lower_lines
        else:
            # 直近価格＝注文価格の場合
            tp_lines = self.lower_lines
            lc_lines = self.upper_lines
        print("TARGET PRICE:", target_price)
        print("  TP LINES", len(tp_lines))
        for i, g in enumerate(tp_lines):
            print(
                f"{s}"
                f"Group {i}: median = {g['median_price']:.3f}, "
                f"range = {g['median']:.3f}, "
                f"strength = {g['total_strength']}, "
                f"count = {g['count']}, "
                f"near = {g['near']}, "
                f"near_p = {g['near_price']}, "
                f"far = {g['far']}, "
                f"far_p = {g['far_price']}, "
                f"prices = {', '.join(map(str, g['prices']))}"
            )
        print("  LC LINES", len(lc_lines))
        for i, g in enumerate(lc_lines):
            print(
                f"{s}"
                f"Group {i}: median = {g['median_price']:.3f}, "
                f"range = {g['median']:.3f}, "
                f"total_strength = {g['total_strength']}, "
                f"count = {g['count']}, "
                f"near = {g['near']}, "
                f"near_p = {g['near_price']}, "
                f"far = {g['far']}, "
                f"far_price = {g['far_price']}, "
                f"prices = {', '.join(map(str, g['prices']))}"
            )

        # ■■処理
        #TPについて
        st = "ensure"  # trigger
        peaks = self.peaks
        rr = 1.4
        # tp_range_from_river = peaks[1]['latest_body_peak_price'] + (0 * target_dir)
        # tp_price_from_river = round(target_price + (target_dir * tp_range_from_river), 3)
        # lc_range_from_tp = round(tp_range_from_river / rr, 3)
        # lc_price_from_tp = round(target_price - (lc_range_from_tp * target_dir), 3)  # 調整用もつけとく
        # lc_change = [
        #                 {"exe": True, "time_after": 0, "trigger": 0.10, "ensure": 0.10 - 0.05},
        #                 {"exe": True, "time_after": 0, "trigger": 0.20, "ensure": 0.16},
        #             ]
        #
        # print(s, "基本的な利確等の情報 target_price", target_price)
        # print(s, "利確幅(lc_changeの最低値)：", tp_range_from_river, tp_price_from_river)
        # print(s, "RRを基に算出したlc_range", round(lc_range_from_tp / rr, 2), lc_price_from_tp)
        # print("")
        #
        # print(" WrapUpここまで")
        # return {
        #     "tp_range": tp_range_from_river,
        #     "tp_price": tp_price_from_river,
        #     "lc_range": lc_range_from_tp,
        #     "lc_price": lc_price_from_tp,
        #     "lc_change": lc_change,
        #     "is_exe": 0
        # }

    def cal_units(self, lc_range, risk_yen=500, type="s", yen_per_pip_per_lot=1000, ):
        """
        yen_per_pip_per_lot:
            例）ドル円で1ロット=1000通貨なら約10円/pips
                1万通貨なら約100円/pips
        """
        # 基本的なUNIT計算
        doller_yen = 10000
        lc_pips = max(lc_range / 0.01, 0.000000001)  # 下のdeveide0を防ぎたい
        print("　UNITSを計算する lc_range", lc_range, "pips", lc_pips, "許容損失", risk_yen)
        lot = risk_yen / (lc_pips * yen_per_pip_per_lot)
        units = int(lot * doller_yen)

        # 調整
        # 一桁目（10で割った余り）を取得
        last_digit = units % 10
        # 一桁目を除いた「十の位以上」のベース数値
        base = (units // 10) * 10
        if type == "l":
            # 0か5、近い方に合わせる
            if last_digit <= 2 or last_digit >= 8:
                # 0に近い場合（8, 9, 0, 1, 2）
                # ※ 8, 9の場合は次の桁の0に近いので、四捨五入に近い処理
                new_units = round(units / 5) * 5
            else:
                # 5に近い場合（3, 4, 5, 6, 7）
                new_units = base + 5

            # シンプルに書くなら： units = 5 * round(units / 5)
            units = int(5 * round(units / 5))

        elif type == "s":
            # 1か6、近い方に合わせる
            # unitsから1を引くと「0か5に合わせる問題」に置き換えられる
            adjusted = 5 * round((units - 1) / 5) + 1
            units = int(adjusted)

        return units

    def compare_with_exist_positions(self, position_control_class, plan_dir, plan_target_price=0):
        # 検証等、position_control_classがない場合は、強制的に、全オーダーを通す返り値を
        print("既存オーダーとの比較の関数")
        is_exist = False
        if position_control_class is None:
            # 検証等のポジションクラスを使わない場合は、スルー
            return is_exist
        else:
            # 既存ポジションについて
            max_minus = 0
            foot = 5
            if foot == 5:
                exist_order_gap_border = 0.04
            else:
                exist_order_gap_border = 0.04

            # 実処理
            # ■残存しているポジションの情報を取得
            peaks = self.peaks
            positions = position_control_class.position_classes
            exist_positions = []
            for i, position in enumerate(positions):
                # 生きているオーダーの取得価格が近い場合
                if position.life:
                    # 先に残存するポジションの一覧を生成しておく
                    info = {
                        "name": position.name,
                        "target_price": position.plan_json['target_price'],
                        "direction": position.plan_json['direction'],
                        "t_unrealize_pl": position.t_unrealize_pl
                    }
                    exist_positions.append(info)
            # 表示用
            for i, ex_position in enumerate(exist_positions):
                print(" ", ex_position['name'], ex_position['t_unrealize_pl'],
                      ex_position['direction'])

            # ■同方向の残存ポジションと、現在価格との比較
            matched_same_dir = [
                d for d in exist_positions
                if (
                        float(d.get("direction", 0)) * plan_dir > 0
                        # or float(d.get("pl", 0)) <= 0.01
                )
            ]
            exists_same_dir = len(matched_same_dir) >= 1  # booleanも持っておく

            # ■別方向の残存ポジション
            matched_rev_dir = [
                d for d in exist_positions
                if (
                        float(d.get("direction", 0)) * plan_dir < 0
                        and float(d.get("pl", 0)) > 0
                )
            ]
            exists_rev_dir_plus = len(matched_rev_dir) >= 1  # booleanも持っておく

            print("残存オーダーとの比較結果", exists_same_dir, ", 指定条件の残存数", len(matched_same_dir), "指定の方向", plan_dir)
            for i, item in enumerate(matched_same_dir):
                print("  ", item['name'], item['direction'], item['t_unrealize_pl'])

            if exists_same_dir or exists_rev_dir_plus:
                # 同方向の既存オーダーがある場合重複しないように、逆方向のプラスポジションがある場合は阻害しないように、オーダーなし。
                # 逆を言えば、逆方向のマイナスポジションの場合は、それを打ち消すような形でオーダー発行
                print("残存オーダーに同方向有！！", plan_dir, exists_same_dir, exists_rev_dir_plus)
                if exists_rev_dir_plus:
                    tk.line_send("逆方向のプラスポジションがあるため、それを阻害しないようにオーダーなし")
            else:
                pass
            return exists_same_dir or exists_rev_dir_plus

    def compare_with_history(self, position_control_class, plan_target_price, plan_dir):
        # ■履歴から、直近のマイナス傾向を算出する
        peaks = self.peaks
        # 過去１０回（３０分足だとほぼ１日分）と、トータルの合計を加味する
        positions = position_control_class.position_classes
        one_position = positions[0]   # 代表のポジション（クラス変数見るために一応）
        histories = one_position.result_dic_arr[-11:]
        total_PLu = one_position.total_PLu

        print("直近(最大１０回）の結果たち")
        for i, history in enumerate(histories):
            dir = float(history['units']) / abs(float(history['units']))
            print(" ", history['name'], history['pl_per_units'], dir, history['target_price'])
        print("既存のポジションたち")

        # 直近の負けの８０％が同方向の場合、そっちは弱いとなる。
        pos_count = 0
        neg_count = 0
        # 1. プラスとマイナスの個数をカウント
        pos_count = sum(1 for d in histories if float(d.get("units", 0)) > 0)
        neg_count = sum(1 for d in histories if float(d.get("units", 0)) < 0)
        # 2. 合計数を出す
        total = pos_count + neg_count
        # 3. ポジティブな割合（0.0 〜 1.0）を計算
        # totalが0の場合はエラーを避けるため 0.0 を代入
        pos_neg_ratio = pos_count / total if total > 0 else 0.0
        # 結果の確認
        print(f"ポジティブ割合: {pos_neg_ratio}")  # 例: 0.5

        # オーダーとの比較
        # plan_dir = 1
        # plan_target_price = self.latest_price
        threshold = 0.04
        names = []
        for item in histories:
            if (
                    plan_dir * float(item["units"]) > 0 and
                    abs(plan_target_price - float(item["target_price"])) <= threshold and
                    float(item["pl_per_units"]) < 0
            ):
                names.append(item["name"])
        exists = len(names) > 0
        if exists:
            print("履歴に同価格帯の同方向のマイナスポジションあり", names[0])
