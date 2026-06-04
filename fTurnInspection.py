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
from statistics import median
from collections import defaultdict
import math
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
            self.mode = "live"
            from_i_price = 0  #
        else:
            from_i = 1
            self.mode = "inspection"
            from_i_price = 1
        self.position_control_class = position_control_class
        self.line_send_exe = this_file_line_send
        self.line_send_mes = ""
        self.s = "    "
        self.round_digit = 3
        self.oa = candle_analysis.base_oa

        self.candle_analysis_all = candle_analysis

        self.ca5 = candle_analysis.candle_meta_class  # peaks以外の部分。cal_move_ave関数を使う用
        self.peaks_class = candle_analysis.peaks_class  # peaks_classだけを抽出
        self.df_r_m5 = candle_analysis.d5_df_r[1:]  # 5分足はひとつ前ので固定！！（Liveでも）

        self.ca60 = candle_analysis.candle_meta_class_hour
        self.peaks_class_hour = candle_analysis.peaks_class_hour
        self.df_r_h1 = candle_analysis.d60_df_r[from_i:]

        self.ca30 = candle_analysis.candle_meta_class_m30
        self.peaks_class_m30 = candle_analysis.peaks_class_m30
        self.df_r_m30 = candle_analysis.d30_df_r[from_i:]

        self.current_time = candle_analysis.d5_df_r.iloc[0]['time_jp']  # 5分足で判断(0行目を利用）
        self.current_price = candle_analysis.current_price  # candleAnalysisからとる（本番の場合はAPIで最新、解析の場合はclose価格)
        self.mode = mode  # 検証かどうか
        self.pair = "USD_JPY"
        print("current_priceの確認(main_analysis)", self.current_price, "移動平均", self.ca5.cal_move_ave(1))
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
        gene.print_peaks(peaks[:4])
        print("↓")
        gene.print_peaks(peaks[-2:])
        print("")

        print(self.s, "<SKIP後＞", len(peaks_skip), asizeof.asizeof(peaks_skip))
        gene.print_peaks(peaks_skip[:3])
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
        self.latest_turn_resistance_gap = abs(t['latest_body_peak_price'] - self.current_price)
        self.latest_flop_resistance_gap = abs(f['latest_body_peak_price'] - self.current_price)

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
        self.units_str = 1 * gl_unis_std  #0.1
        self.units_hedge = self.units_str
        # 汎用性高め
        self.lc_change_test = [
            {"exe": True, "time_after": 0, "trigger": 0.01, "ensure": -1},  # ←とにかく、LCCandleを発動させたい場合
        ]

        # ★★★調査実行
        self.main()

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
        candle_analysis = self.candle_analysis_all
        peaks = self.peaks_class.peaks_original
        peaks_skip = self.peaks_class.skipped_peaks_hard
        mode = self.mode
        # 変数化（BB）
        df_h1_row = candle_analysis.d60_df_r.iloc[0]
        bb_h1_class = self.bb_h1_class
        bb_m5_class = self.bb_m5_class

        # ■途中終了判定
        # if peaks[1]['gap'] < 0.04:
        #     print("対象が小さい", peaks[1]['gap'])

        # (4)大本命
        self.simple_turn_analysis()
        # (5)ターン時以外
        self.predict_analysis()

    def get_strongest_line(self, lines):
        """最強のLINEを取得"""
        if not lines:
            return None
        return max(lines, key=lambda x: x['total_strength'])


    def compare_lines(self, line_3h, line_6h, line_type='tp', threshold=0.5):
        """複数時間軸のLINEを比較（TP または LC）
        
        Args:
            line_3h: 3時間足の抵抗線計算結果
            line_6h: 6時間足の抵抗線計算結果
            line_type: 'tp' または 'lc'
            threshold: medianの差の閾値
        
        Returns:
            判定結果を辞書で返す
        """
        
        # line_typeに応じて対象を選択
        if line_type.lower() == 'tp':
            lines_3h = line_3h.tp_lines
            lines_6h = line_6h.tp_lines
        elif line_type.lower() == 'lc':
            lines_3h = line_3h.lc_lines
            lines_6h = line_6h.lc_lines
        else:
            raise ValueError("line_type は 'tp' または 'lc' で指定してください")
        
        strongest_3h = self.get_strongest_line(lines_3h)
        strongest_6h = self.get_strongest_line(lines_6h)
        
        if strongest_3h is None or strongest_6h is None:
            return {
                'status': '不足',
                'reason': 'データが不足',
                'line_type': line_type,
            }
        
        median_3h = strongest_3h['median']
        median_6h = strongest_6h['median']
        median_diff = abs(median_3h - median_6h)
        
        status = '変化なし' if median_diff <= threshold else '変化有'
        
        return {
            'status': status,
            'line_type': line_type,
            'median_diff': round(median_diff, 3),
            'threshold': threshold,
            'median_3h': median_3h,
            'median_6h': median_6h,
            'strength_3h': strongest_3h['total_strength'],
            'strength_6h': strongest_6h['total_strength'],
            'price_3h': strongest_3h['median_price'],
            'price_6h': strongest_6h['median_price'],
        }


    def predict_analysis(self):
        # ターン時以外でも実行される
        print("■予測オーダー")
        s = self.s
        current_price = self.current_price  # self.ca = candle_analysis
        foot = 5
        if foot == 5:
            # ５分足の場合
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
            dt = datetime.strptime(self.current_time, '%Y/%m/%d %H:%M:%S')
            minute = dt.minute
            if minute == 0 or minute == 30:  # or minute == 5 or minute == 35:  #minute % 30 == 0:
                pass
            else:
                print("30分足以外")
                return 0
        # base_price = self.current_price
        base_price = peaks[0]['latest_body_peak_price']  # self.latest_price

        # ■RSI
        f_low = df.iloc[1]
        p_low = df.iloc[2]  # ひとつ前の足
        print("    RSI", f_low['time_jp'], f_low['RSI'])
        if f_low['RSI'] >= 70 and p_low['RSI'] >= 70:
            print("    2個連続でRSI越えている")

        # ■ラインの検証
        line_class3 = LineStrengthCal(self.candle_analysis_all, "m5", 3)
        line_class6 = LineStrengthCal(self.candle_analysis_all, "m5", 6)
        result = self.compare_lines(line_class3, line_class6, threshold=0.5)
        print(f"判定: {result['status']}")
    

    def simple_turn_analysis(self):
        print("■シンプルターンオーダー2", self.current_price)

        # 変数化（共通
        s = self.s
        current_price = self.current_price  # self.ca = candle_analysis
        # 変数化（足ごと
        foot = 5
        if foot == 5:
            # ５分足の場合
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
            dt = datetime.strptime(self.current_time, '%Y/%m/%d %H:%M:%S')
            minute = dt.minute
            if minute == 0 or minute == 30:  # or minute == 5 or minute == 35:  #minute % 30 == 0:
                pass
            else:
                print("30分足以外")
                return 0

        # 途中終了の場合
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
        print(df.iloc[1]['time_jp'], df.iloc[1]['body_abs'])
        print(l['gap'], r['gap'], r['gap'] * 0.7, r['gap'] * 1.3)
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
        print(l_df1['time_jp'], min1, max1, l_df2['time_jp'], min2, max2, overlap, max1 - min1)
        print("size", size_condition, size_ratio, "overlap1", overlap_ratio, "overlap2", overlap_ratio2)

        # 当初の、Latestの方向にそのまま行くやつ
        op = OrderPoints(self.candle_analysis_all, peaks_class, foot)  # オーダーポイントの計算
        # オーダー２の情報
        target_margin_stop = -0.001
        op.cal_target_price_stop(target_margin_stop)  # targetマージンからtarget価格を計算する(lc_rangeもここで計算される）
        is_exist = op.compare_with_exist_positions(self.position_control_class, op.dir_stop, op.order_stop_priority)
        # 逆方向のオーダー用
        # op.cal_target_price_oppo_stop(0.005)

        # オーダー2用の数字の生成
        order_class1 = None
        if op.stop_order_cancel == 0:  # 0以外の場合は、キャンセルということ
            if not is_exist:  # 阻害するポジションが無い場合は、通常通りオーダー
                order_class1 = OCreate.Order({
                    "name": "シンプルターン順 Big",
                    "current_price": current_price,
                    "target": op.target_price_stop,
                    "direction": op.dir_stop,
                    "type": op.order_stop,  # "LIMIT",  # "STOP",  # "MARKET",
                    "tp": op.tp_range_stop,
                    "lc": op.lc_range_stop,  # 0.15,  # 価格手指定しよう
                    "lc_change": op.lc_change_stop,
                    "units": int(op.cal_units(op.lc_range_stop, tk.setting_json['l_units'], "l") * 0.5),  # 100,
                    "priority": 5,
                    "decision_time": df.iloc[0]['time_jp'],
                    "candle_analysis_class": self.candle_analysis_all,
                    "lc_change_candle_type": candle_foot,
                    # "order_permission": False,
                    "order_timeout_min": 15,
                    "memo": op.stop_memo,
                })
                self.add_order_to_this_class(order_class1)

                # order_class2 = OCreate.Order({
                #     "name": "シンプルターン順 Small",
                #     "current_price": current_price,
                #     "target": op.target_price_stop,
                #     "direction": op.l_dir,
                #     "type": "STOP",  # "STOP",  # "MARKET",
                #     "tp": op.tp_range_stop_s,
                #     "lc": op.lc_range_stop,  # 0.15,  # 価格手指定しよう
                #     "lc_change": op.lc_change_stop,
                #     "units": int(op.cal_units(op.lc_range_stop, tk.setting_json['l_units'], "l") * 0.6),  # 100,
                #     "priority": 5,
                #     "decision_time": df.iloc[0]['time_jp'],
                #     "candle_analysis_class": self.candle_analysis_all,
                #     "lc_change_candle_type": candle_foot,
                #     # "order_permission": False,
                #     "order_timeout_min": 15,
                #     "memo": op.stop_memo,
                # })
                # self.add_order_to_this_class(order_class2)
            else:
                tk.line_send("オーダーを阻止するオーダーありのため、発行せず", is_exist)
        elif op.stop_order_cancel == 11:
            # 戻りすぎの場合は、明確に逆方向にオーダーを出す
            order_class1 = OCreate.Order({
                "name": "シンプルターン順 [戻り]",
                "current_price": current_price,
                "target": op.target_price_stop,
                "direction": op.dir_stop,
                "type": op.order_stop,  # "STOP",  # "MARKET",
                "tp": op.tp_range_stop,
                "lc": op.lc_range_stop,  # 0.15,  # 価格手指定しよう
                "lc_change": [],
                "units": int(op.cal_units(op.lc_range_stop, tk.setting_json['l_units'], "l") * 0.5),  # 100,
                "priority": 5,
                "decision_time": df.iloc[0]['time_jp'],
                "candle_analysis_class": self.candle_analysis_all,
                "lc_change_candle_type": candle_foot,
                # "order_permission": False,
                "order_timeout_min": 15,
                "memo": op.stop_memo,
            })
            self.add_order_to_this_class(order_class1)
        else:
            print("オーダーキャンセルのコードあり", op.stop_order_cancel)
            tk.line_send("オーダーキャンセルのコードあり", op.stop_order_cancel)


class CurrencyPair:
    """通貨ペアのメタデータ"""

    def __init__(self, name: str, pip_value: float):
        self.name = name
        self.pip_value = pip_value

    def pips_to_price(self, pips: float) -> float:
        """pipsを価格差に変換"""
        return pips * self.pip_value

    def price_to_pips(self, price_diff: float) -> float:
        """価格差をpipsに変換"""
        return price_diff / self.pip_value

    def exchange(self, unknown_num):
        """値を渡されたら、勝手に判断してpipsに変換する"""
        if unknown_num >= self.pip_value * 100:
            # 例えばドル円で２と来た場合は、pipsと判断。
            result = unknown_num
        else:
            result = unknown_num / self.pip_value
        return result


class LineStrengthCal:
    def __init__(self, candle_analysis_class, foot, time_before=3):
        print("  ")
        print("  抵抗線計算クラス 時間", time_before, "足", foot)
        # ■■■基本情報の取得
        mode = "live"
        if mode == "live":
            from_i = 0
            self.mode = "live"
        else:
            from_i = 1
            self.mode = "inspection"
        self.p = CurrencyPair("USDJPY", 0.01)

        self.s = "     "
        self.pair = "USD_JPY"
        self.candle_analysis_class = candle_analysis_class  # ローソク情報の全て
        self.time_before = time_before

        # 各足でのローソク情報
        self.candle_meta_m5 = candle_analysis_class.candle_meta_class  # peaks以外の部分。cal_move_ave関数を使う用
        self.peaks_class_m5 = candle_analysis_class.peaks_class  # peaks_classだけを抽出
        self.peaks_m5 = self.peaks_class_m5.peaks_original
        self.df_r_m5 = candle_analysis_class.d5_df_r[1:]  # 5分足はひとつ前ので固定！！（Liveでも）

        self.candle_meta_h1 = candle_analysis_class.candle_meta_class_hour
        self.peaks_class_h1 = candle_analysis_class.peaks_class_hour
        self.peaks_h1 = candle_analysis_class.peaks_class_hour.peaks_original
        self.df_r_h1 = candle_analysis_class.d60_df_r[from_i:]

        self.candle_meta_m30 = candle_analysis_class.candle_meta_class_m30
        self.peaks_class_m30 = candle_analysis_class.peaks_class_m30
        self.peaks_m30 = candle_analysis_class.peaks_class_m30.peaks_original
        self.df_r_m30 = candle_analysis_class.d30_df_r[from_i:]

        self.current_time = candle_analysis_class.d5_df_r.iloc[0]['time_jp']  # 5分足で判断(0行目を利用）
        self.current_price = candle_analysis_class.current_price  # candleAnalysisからとる（本番の場合はAPIで最新、解析の場合はclose価格)
        self.target_dir = self.peaks_m5[0]['direction']

        # 結果保持用
        self.upper_lines = []
        self.lower_lines = []

        # 関数の実行
        self.lines_wrap_up()  # linesの算出


    def lines_wrap_up(self):
        """
        Lineを探索する
        """
        base_price = self.current_price
        time_before_h = self.time_before
        threshold = 3
        upper_lines = self.search_upper_lines(base_price, time_before_h, threshold)  # target_price
        lower_lines = self.search_lower_lines(base_price, time_before_h, threshold)  # target_price
        
        if self.target_dir == 1:
            # 直近価格＝注文価格の場合 いずれも直近価格から近い順に並んでいる。
            self.tp_lines = upper_lines
            self.lc_lines = lower_lines
        else:
            # 直近価格＝注文価格の場合
            self.tp_lines = lower_lines
            self.lc_lines = upper_lines
        self.lower_lines = lower_lines
        self.upper_lines = upper_lines

        print("    TARGET PRICE:", base_price, "BasePrice", base_price)
        print("    TP LINES", len(self.tp_lines))
        for i, g in enumerate(self.tp_lines):
            print(
                self.s,
                f"Group {i}: median_price = {g['median_price']:.3f}, "
                f"median = {g['median']:.3f}, "
                f"strength = {g['total_strength']}, "
                f"count = {g['count']}, "
                f"ave_strength = {g['ave_strength']}, "
                f"oldest_time = {g['oldest_time']}, "
                f"prices = {', '.join(map(str, g['prices']))}"
            )
        print("    LC LINES", len(self.lc_lines))
        for i, g in enumerate(self.lc_lines):
            print(
                self.s,
                f"Group {i}: median_price = {g['median_price']:.3f}, "
                f"median = {g['median']:.3f}, "
                f"strength = {g['total_strength']}, "
                f"count = {g['count']}, "
                f"ave_strength = {g['ave_strength']}, "
                f"oldest_time = {g['oldest_time']}, "
                f"prices = {', '.join(map(str, g['prices']))}"
            )

    def search_upper_lines(self, base_price, time_before_h=3, threshold=2):
        # print("    UpperLines検索")
        peaks = self.peaks_class_m5.peaks_original  # 使う足の選択
        # 時間でPeaksを絞り込み（直近N時間のピークで解析）
        border_time = datetime.strptime(self.current_time, '%Y/%m/%d %H:%M:%S') - timedelta(hours=time_before_h)
        peaks = [
            d for d in peaks
            if datetime.strptime(d['latest_time_jp'], '%Y/%m/%d %H:%M:%S') > border_time
        ]
        # グループ化
        minus_groups = self.make_same_price_group(
            peaks=peaks,
            upper_lower=1,  # base_priceより下側
            target_price=base_price,
            width=threshold,
            sort_direction=1  # 昇順
        )
        # 弱すぎるグループは排除する
        filtered = [d for d in minus_groups if d["ave_strength"] >= 1.5 and d['count'] >= 2]
        return filtered

    def search_lower_lines(self, base_price, time_before_h=3, threshold=2):
        # print("    LowerLines検索")
        peaks = self.peaks_class_m5.peaks_original  # 使う足の選択
        # 時間でPeaksを絞り込み（直近N時間のピークで解析）
        border_time = datetime.strptime(self.current_time, '%Y/%m/%d %H:%M:%S') - timedelta(hours=time_before_h)
        peaks = [
            d for d in peaks
            if datetime.strptime(d['latest_time_jp'], '%Y/%m/%d %H:%M:%S') > border_time
        ]
        # グループ化
        minus_groups = self.make_same_price_group(
            peaks=peaks,
            upper_lower=-1,  # base_priceより下側
            target_price=base_price,
            width=threshold,
            sort_direction=-1  # 降順
        )
        # 弱すぎるグループは排除する
        filtered = [d for d in minus_groups if d["ave_strength"] >= 1.5 and d['count'] >= 2]
        return filtered

    def make_same_price_group(self, peaks,
                              upper_lower,
                              target_price,
                              width=3,  # pips単位
                              direction_filter=None,
                              sort_direction=-1,
                              ):
        # target_priceをpipsに変換（基準点として）
        target_price_pips = self.p.price_to_pips(target_price)
        # print(f"DEBUG: target_price={target_price}, target_price_pips={target_price_pips}")
        # print(f"DEBUG: width={width} pips")

        if upper_lower == -1:
            # 下側の場合
            filtered_peaks = [
                p for p in peaks
                if float(p['latest_body_peak_price']) < target_price
            ]
        else:
            # 上側の場合
            filtered_peaks = [
                p for p in peaks
                if float(p['latest_body_peak_price']) >= target_price
            ]

        if direction_filter is not None:
            filtered_peaks = [
                p for p in filtered_peaks
                if p['direction'] == direction_filter
            ]

        groups = defaultdict(list)
        
        for p in filtered_peaks:
            price = float(p['latest_body_peak_price'])
            price_pips = self.p.price_to_pips(price)
            
            # ← ここをデバッグ
            group_key = round(
                math.floor(price_pips / width) * width,
                5
            )
            
            # print(f"DEBUG: price={price}, price_pips={price_pips}, group_key={group_key}")
            
            groups[group_key].append(p)
        
        # print(f"DEBUG: groups={dict(groups)}")  # グループの内容確認
        # print(f"DEBUG: filtered_peaks count={len(filtered_peaks)}")

        results = []

        for group_key, items in groups.items():
            prices = [
                float(x['latest_body_peak_price'])
                for x in items
            ]
            prices_pips = [self.p.price_to_pips(p) for p in prices]

            latest_times = [
                datetime.strptime(
                    x['latest_time_jp'],
                    '%Y/%m/%d %H:%M:%S'
                )
                for x in items
            ]

            median_price_pips = median(prices_pips)
            median_diff_pips = abs(target_price_pips - median_price_pips)

            results.append({
                'median_price': median(prices),
                'median_p': round(abs(target_price - median(prices)), 3),
                'median': median_diff_pips,
                "total_strength": sum(float(x['peak_strength']) for x in items),
                'count': len(items),
                "ave_strength": round(sum(float(x['peak_strength']) for x in items) / len(items) if items else 0, 1),
                'prices': prices,
                'range_min': group_key,
                'range_max': group_key + width,
                'newest_time': max(latest_times).strftime('%Y/%m/%d %H:%M:%S'),
                'oldest_time': min(latest_times).strftime('%Y/%m/%d %H:%M:%S'),
            })

        results = sorted(
            results,
            key=lambda x: x['median_price'],  # 価格で並び替え
            reverse=(sort_direction == -1)
        )
        return results


class OrderPoints:
    def __init__(self, candle_analysis_all, peaks_class, foot):
        print(" ")
        print(" ★★オーダーポイントの整理")
        # ■■■基本情報の取得
        self.candle_analysis_all = candle_analysis_all
        self.peaks_class = peaks_class
        self.peaks = peaks_class.peaks_original
        self.round_digit = 3
        self.spred = 0.008
        self.current_price = candle_analysis_all.current_price  # 本番だとAPI経由の正確な値になる
        self.current_time = self.candle_analysis_all.d5_df_r.iloc[0]['time_jp']
        self.peaks = self.peaks
        self.foot = foot

        # 既存のオーダーとの比較
        self.exists_same_dir = False
        self.exists_rev_dir_plus = False
        self.matched_rev_dir_minus = False

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
        self.order_stop = "STOP"
        self.order_stop_priority = 5
        self.dir_stop = self.l_dir
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
        self.stop_memo = ""
        self.tp_range_stop_s = 0.6  # TP2の初期値(RR0.75のもの）
        self.tp_price_stop_s = 0

    def cal_target_price_stop(self, margin):
        s = "    "
        peaks = self.peaks
        spred = self.spred
        # base_price = self.current_price
        base_price = peaks[0]['latest_body_peak_price']  # self.latest_price
        target_dir = self.l_dir
        self.stop_order_cancel = 999  # 途中返却の可能性もあるため、最初から入れておく
        df = self.peaks_class.df_r_original  # これは
        order_cancel = 0
        margin2 = 0.005
        memo = ""
        rr_b = 1.65  # RR値。ロスカ幅に対する、利確幅の比率
        rr_s = 1.4
        tp_price = tp_range = lc_price = lc_range = 0  # 初期値
        latest = peaks[0]
        river = peaks[1]
        current_time = latest['latest_time_jp']
        lc_change = []
        # ■■■ターゲットプライスを算出
        if target_dir == 1:
            target_price = base_price + margin
        else:
            target_price = base_price - margin

        print("＠＠＠＠＠STOPについての計算 dir:", target_dir, "@@@@@")

        # ■■■ラインの情報から、利確、ロスカの候補を算出する
        time_before_h = 4
        threshold = 0.05
        # テスト表示用
        border_time = datetime.strptime(self.current_time, '%Y/%m/%d %H:%M:%S') - timedelta(hours=time_before_h)
        peaks_latest = [
            d for d in peaks
            if datetime.strptime(d['latest_time_jp'], '%Y/%m/%d %H:%M:%S') > border_time
        ]

        # 本番用
        peaks_latest = [
            d for d in peaks
            if datetime.strptime(d['latest_time_jp'], '%Y/%m/%d %H:%M:%S') > border_time
        ]
        upper_lines = self.predict_line_upper(base_price, time_before_h, threshold)  # target_price
        # lower
        lower_lines = self.predict_line_lower(base_price, time_before_h, threshold)  # target_price
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
                f"total_strength = {g['total_strength']}, "
                f"count = {g['count']}, "
                f"ave_strength = {g['ave_strength']}, "
                # f"near_far_gap = {g['near_far_gap']}, "
                # f"near = {g['near']}, "
                # f"near_p = {g['near_price']}, "
                # f"far = {g['far']}, "
                # f"far_price = {g['far_price']}, "
                f"oldest_time = {g['oldest_time']}, "
                f"newest_time = {g['newest_time']}, "
                # f"max_gap_minutes = {g['max_gap_minutes']}, "
                # f"max_gap_start = {g['max_gap_start']}, "
                # f"max_gap_end = {g['max_gap_end']}, "
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
                f"ave_strength = {g['ave_strength']}, "
                # f"near_far_gap = {g['near_far_gap']}, "
                # f"near = {g['near']}, "
                # f"near_p = {g['near_price']}, "
                # f"far = {g['far']}, "
                # f"far_price = {g['far_price']}, "
                f"oldest_time = {g['oldest_time']}, "
                f"newest_time = {g['newest_time']}, "
                # f"max_gap_minutes = {g['max_gap_minutes']}, "
                # f"max_gap_start = {g['max_gap_start']}, "
                # f"max_gap_end = {g['max_gap_end']}, "
                f"prices = {', '.join(map(str, g['prices']))}"
            )

        # ■解析１　利確とロスカの強さについて
        print("-lc-----------------------------------------------------------------")
        if len(lc_lines) != 0:
            # riverPeakが強い抵抗線に含まれているか、または過去最高のpeakかを判定する
            river_peak_price = peaks[1]['latest_body_peak_price']
            item_with_river = next((item for item in lc_lines if river_peak_price in item['prices']), None)
            if item_with_river:
                print(s, "riverを含む抵抗線", item_with_river['median_price'], "price", river_peak_price)
                if item_with_river['total_strength'] >= 5 and item_with_river['count'] >= 2:
                    print(s, "riverがそこそこの抵抗線に含まれる　⇒　ここらでLC方向は歯止めがかかる rr1.2?")
                    lc_range = peaks[0]['gap']
                    print(s, "latest_range(riverまでのrange)", lc_range)
                else:
                    print(s, "riverがそこそこの抵抗線に含まれるが、弱い⇒LC方向に持っていく可能性")
            else:
                print(s, "riverはLineに含まれない　⇒　LC方向にもっと行く可能性あり")
            #
            most_far_lc_line = lc_lines[-1]
            print("最も遠いLCLine")
            print(most_far_lc_line)
        else:
            print("LC 0本")

        # 過去最高のピーク化を確認
        river_peak_strength = peaks[1]['peak_strength']
        if river_peak_strength == 8:
            print(s, "river peaksは最高到達点", river_peak_strength)
        elif river_peak_strength == 5:
            print(s, "river peaksは通常ポイント", river_peak_strength)
        else:
            print(s, "river_peaksは小さいポイント", river_peak_strength)

        # ■解析２　TPの位置について
        print("-tp-----------------------------------------------------------------")
        # 一つ目のそこそこ強い物を取得する
        if len(tp_lines) != 0:
            max_line = max(tp_lines, key=lambda x: x['total_strength'])
            if max_line['median'] <= 0.03:
                self.stop_order_cancel = "median 0.03以下"
                # return 0
        else:
            # TPが0本
            pass

        # ■解析３　TPLINEとLCLINEが両方ある場合のみ実施
        if len(tp_lines) != 0 and len(lc_lines) != 0:
            most_far_lc_line = lc_lines[-1]
            most_far_tp_line = tp_lines[-1]
            if most_far_lc_line['median'] + most_far_tp_line['median'] <= 0.1:
                tk.line_send("かなり狭いレンジ。", most_far_tp_line['median_price'], most_far_lc_line['median_price'])
        else:
            print("両方無い場合は実施しない")

        # ■直近2時間でのPeaksの数
        if len(peaks_latest) >= 5:
            print(s, "レンジ判定。細かそうなので、大きなLCにしておく。")
            self.stop_order_cancel = 11
            self.dir_stop = self.l_dir
            self.target_price_stop = peaks[0]['latest_body_peak_price'] - (self.l_dir * 0.004)  # LIMIT"!!
            self.tp_range_stop = 0.1
            self.tp_price_stop = self.target_price_stop + (self.dir_stop * self.tp_range_stop)
            self.lc_range_stop = self.tp_range_stop / 1.3  # rr_s = 1.4
            self.lc_price_stop = self.target_price_stop - (self.dir_stop * self.tp_range_stop)
            self.order_stop = "LIMIT"  # STOP関数なのにLIMIT,,
            self.lc_change_stop = []
            self.stop_order_cancel = order_cancel  # 0以外でキャンセル
            self.order_stop_priority = 5
            self.stop_memo = memo + "レンジ判定のため、幅大！！"
            return 0

        # ■■■価格変動の速さを計測（６秒で動きすぎているかの判定　いまは参考程度）
        # 順方向なので、直近のpeak方向が１の場合、＋方向に離れてる場合は、動きが強い
        now_peak_gap = round(self.current_price - latest['latest_body_peak_price'], 3)

        latest_df = df.iloc[1]  # [0]は形成され始めた瞬間の足なので注意
        if now_peak_gap >= 0.007:
            if latest['direction'] == latest_df['direction']:
                if (now_peak_gap >= 0 and self.l_dir == 1) or (self.l_dir == -1 and now_peak_gap <= 0):
                    print(s, "順方方向に、大きく動いている。")
                    tk.line_send("LatestPriceとPeak価格差大 現価:", self.current_price, ",P価格:",
                                 peaks[0]['latest_body_peak_price'], ",GAP:", now_peak_gap)
                    self.stop_memo = "価格差大！！"
                    target_price = self.current_price  # 現在価格にマージンをつけずに執行
                    # self.stop_order_cancel = 15
                    # return 0
                else:
                    print(s, "差は大きいが、逆方向なので気にしない。")
                    tk.line_send("LatestPriceとPeak価格差大(逆） 現価:", self.current_price, ",P価格:",
                                 peaks[0]['latest_body_peak_price'], ",GAP:", now_peak_gap)
            else:
                print("方向が逆のため、Gapは大きい", now_peak_gap, latest['direction'], latest_df['direction'])

        # ■■■形状判定
        # １　latestとriverの比率
        latest_gap = peaks[0]['gap']
        river_gap = peaks[1]['gap']
        turn_gap = peaks[2]['gap']
        ratio_l_r = round(latest_gap / river_gap, 2)
        ratio_r_t = round(river_gap / turn_gap, 2)

        # if river_gap <= 0.035:
        if river_gap <= 0.00:
            print(s, "riverが小さすぎる!", river_gap, peaks[1]['latest_body_peak_price'],
                  peaks[2]['latest_body_peak_price'])
            print(s, "伸びる可能性の検討", ratio_r_t, ratio_l_r)
            print(s, "turnは", turn_gap, round(turn_gap / river_gap, 1), ratio_r_t, ratio_l_r)
            self.stop_order_cancel = 18
            if ratio_r_t <= 0.38 and ratio_l_r >= 1.0 and river_gap >= 0.015:
                # ただし、伸びた後の微妙な折り返し＆riverを越えているの場合、そのまま行く可能性あり
                print(" 伸びる可能性あるやつ")
                # self.stop_order_cancel = 20
                # return 0
            elif round(turn_gap / river_gap, 1) >= 1.8:
                print(s, "turnがそこそことれているので、とりあえず取ってみる")
            else:
                return 0
        elif peaks[1]['count'] == 2 and peaks[2]['count'] == 2 and peaks[1]['gap'] <= 0.28 and peaks[2]['gap'] <= 0.03:
            print(s, "とりあえずレンジ判定する")
            self.stop_order_cancel = 5
            return 0
        else:
            # サイズをクリアする場合、比率も見ておく（elseにしないと、伸びる可能性なのに、戻り強すぎ、が起きてしまう）
            print("latestのriverに対する比率", ratio_l_r, "turnのriverに対する比率", ratio_r_t, "rivergap", river_gap)
            if 1.8 >= ratio_l_r >= 0.9:
                a = round(df.iloc[1]['body_abs'], 3)
                b = round(df.iloc[2]['body_abs'], 3)
                print(s, "dfの長さ", a, b, df.iloc[1]['time_jp'], latest_gap, a > latest_gap * 0.8,
                      b > latest_gap * 0.8)
                if a > latest_gap * 0.8 or b > latest_gap * 0.8:
                    print(" 戻りが強すぎるため、基本やらない方がいい")
                    self.stop_order_cancel = 11
                    self.dir_stop = self.l_dir * -1
                    self.target_price_stop = peaks[0]['latest_body_peak_price'] - (self.l_dir * 0.004)  # LIMIT"!!
                    self.tp_range_stop = peaks[1]['gap'] * 0.5
                    self.tp_price_stop = self.target_price_stop + (self.dir_stop * self.tp_range_stop)
                    self.lc_range_stop = self.tp_range_stop / 1.4  # rr_s = 1.4
                    self.lc_price_stop = self.target_price_stop - (self.dir_stop * self.tp_range_stop)
                    self.order_stop = "LIMIT"  # STOP関数なのにLIMIT,,
                    self.lc_change_stop = []
                    self.stop_order_cancel = order_cancel  # 0以外でキャンセル
                    self.stop_memo = memo + "戻り強い"
                    self.order_stop_priority = 5
                    return 0
                else:
                    print(s, "均等に伸びてるので通常通り")

            else:
                # riverとlatestが問題ない場合でも、
                if ratio_l_r >= 0.63:
                    # latestが割と戻しつつ、さらにturnとriverが近い値の場合、レンジっぽい
                    if 0.8 <= ratio_r_t <= 1.2:
                        print("　戻りはそこそこだが、turnとriverが同じくらいの大きさのため、レンジ判定でやらない")
                        self.stop_order_cancel = 12
                        return 0
        # ■解析０　ローソクがかぶりすぐていないかの検証
        # latestを形成する二つのローソクの重なり（Bodyサイズだけではなく、価格的に包括関係にあるか）
        # l = peaks[0]
        # l_df1 = df.iloc[1]
        # l_df2 = df.iloc[2]
        # max1 = l_df1['inner_high']
        # min1 = l_df1['inner_low']
        # max2 = l_df2['inner_high']
        # min2 = l_df2['inner_low']
        # max1 = l_df1['high']
        # min1 = l_df1['low']
        # max2 = l_df2['high']
        # min2 = l_df2['low']
        # width1 = max1 - min1
        # width2 = max2 - min2
        # overlap = max(0, min(max1, max2) - max(min1, min2))
        # # overlap_ratio = overlap / width1 if width1 != 0 else 0  # A基準
        # overlap_ratio2 = overlap / (max2 - min2)  # ひとつ前の足が、latestの足と何パーセントかぶっているか
        # overlap_ratio = overlap / (max1 - min1)  # latestの何パーセントがそのひとつ前と被っているか
        # size_ratio = width2 / width1 if width1 != 0 else 0
        #
        # size_condition = width2 >= width1 * 1.3
        # overlap_condition = overlap >= width1 * 0.88  # ←ここがA基準
        # print(l_df1['time_jp'] ,min1, max1, l_df2['time_jp'], min2, max2, overlap, max1 - min1)
        # print("size", size_condition, size_ratio, "overlap1", overlap_ratio, "overlap2", overlap_ratio2)
        # if overlap_ratio >= 0.7 and overlap_ratio2 >= 0.7:
        #     print("がっつりかぶっている")

        # ■■■ダウ系
        # 0 ダウ転換
        strs = "latest_body_peak_price"
        p1 = peaks[1][strs]
        u1 = peaks[2][strs]
        p2 = peaks[3][strs]
        u2 = peaks[4][strs]
        older_gap = round(abs(u2 - p2), 3)
        later_gap = round(abs(u1 - p1), 3)
        small_big_ratio = round(peaks[2]['gap'] / max(peaks[1]['gap'], peaks[3]['gap']), 3)
        print(s, "ダウポイントP:", peaks[1]['latest_time_jp'], peaks[3]['latest_time_jp'], p1, p2)
        print(s, "ダウポイントU:", peaks[2]['latest_time_jp'], peaks[4]['latest_time_jp'], u1, u2)
        print(s, "GAPs", older_gap, later_gap, round(older_gap / later_gap, 1))
        print(s, "gaps bigs", peaks[1]['gap'], peaks[3]['gap'], "small", peaks[2]['gap'])
        print(s, "big_small_ratio", small_big_ratio)
        if 0.8 < older_gap / later_gap < 1.2 and small_big_ratio <= 0.73:
            predict_gap = peaks[2]["gap"]  # elseの場合は使わないが共通処理
            latest_gap = peaks[0]['gap']
            yuuyo_gap = round(predict_gap - latest_gap, 3)  # マイナスの場合は、latestで順方向にかなり戻している場合
            predict_tp = peaks[1]['gap']  # riverがダウ伸びしろしては適切
            predict_tp_price = peaks[0]['latest_body_peak_price'] + (self.l_dir * -1 * predict_tp)
            print(s, "サイズ比率的にはOK ,Pre", predict_gap, "lat", latest_gap)
            if u2 > u1 > p2 > p1:
                print(s, "価格位置関係もOK（下がるダウ） 順への伸びしろは", yuuyo_gap, "。その後下がる可能性", predict_tp,
                      predict_tp_price)
                self.target_price_stop = peaks[0]['latest_body_peak_price'] + (self.l_dir * 0.004)  # LIMIT"!!
                self.dir_stop = self.l_dir * -1
                self.tp_range_stop = predict_tp * 0.95
                self.tp_price_stop = self.target_price_stop + (self.dir_stop * self.tp_range_stop)
                self.lc_range_stop = self.tp_range_stop / 1.4  # rr_s = 1.4
                self.lc_price_stop = self.target_price_stop - (self.dir_stop * self.tp_range_stop)
                self.order_stop = "LIMIT"  # STOP関数なのにLIMIT,,
                self.lc_change_stop = []
                self.stop_order_cancel = order_cancel  # 0以外でキャンセル
                self.stop_memo = memo + "@@@@@@ダウ下がり@@@@@"
                self.order_stop_priority = 6
                return 0
            elif u2 < u1 < p2 < p1:
                print(s, "価格位置関係もOK（上がるダウ）順への伸びしろは", yuuyo_gap, "。その後上がる可能性", predict_tp,
                      predict_tp_price)
                self.target_price_stop = peaks[0]['latest_body_peak_price'] - (self.l_dir * 0.004)  # LIMIT"!!
                self.dir_stop = self.l_dir * -1
                self.tp_range_stop = predict_tp * 0.95
                self.tp_price_stop = self.target_price_stop + (self.dir_stop * self.tp_range_stop)
                self.lc_range_stop = self.tp_range_stop / 1.4  # rr_s = 1.4
                self.lc_price_stop = self.target_price_stop - (self.dir_stop * self.tp_range_stop)
                self.order_stop = "LIMIT"  # STOP関数なのにLIMIT,,
                self.lc_change_stop = []
                self.stop_order_cancel = order_cancel  # 0以外でキャンセル
                self.stop_memo = memo + "@@@@@ダウ上がり@@@@@"
                self.order_stop_priority = 6
                return 0
            else:
                print(s, "価格位置関係NG")

        # 一部の変数化
        if latest["direction"] == 1:
            # 最後のピークが登りの場合
            river_peak = river["lowest"]
            latest_peak = latest['lowest']
            latest_peak_wick_price_temp = min(river_peak, latest_peak)
        else:
            # 最後のピークが下りの場合
            river_peak = river["highest"]
            latest_peak = latest['highest']
            latest_peak_wick_price_temp = max(river_peak, latest_peak)
        latest_peak_wick_range_temp = abs(target_price - latest_peak_wick_price_temp)
        # 調整１（小さすぎる場合は、最低値を入れる
        if latest_peak_wick_range_temp <= 0.03:
            # 小さすぎるLCの場合は、0.03は取るようにする
            latest_peak_wick_range_temp = 0.03
            latest_peak_wick_price_temp = target_price - (target_dir * latest_peak_wick_range_temp)
        # 調整２（大きすぎる場合、倍率をかけない）
        latest_peak_wick_range = latest_peak_wick_range_temp * (1.2 if latest_peak_wick_range_temp <= 0.05 else 1.0)
        latest_peak_wick_price = target_price - (latest_peak_wick_range * target_dir)
        print("LC候補", latest_peak_wick_price_temp, "レンジ", abs(target_price - latest_peak_wick_price_temp),
              latest_peak_wick_range)
        # ベースはこれ
        lc_range = latest_peak_wick_range
        lc_price = latest_peak_wick_price
        tp_range = lc_range * rr_b
        tp_price = target_price + (tp_range * target_dir)
        tp_range_s = lc_range * 0.75
        tp_price_s = target_price + (tp_range_s * target_dir)

        print("最終結果(STOP)", order_cancel)
        if (tp_price == 0 or tp_range == 0 or lc_price == 0 or lc_range == 0) and order_cancel == 0:
            print(s, "０を含むオーダーになりそう！！おかしい　tp_price", tp_price, "tp_range", tp_range, lc_price, lc_range)
            order_cancel = 100

        # tpが広すぎる場合があるので、調整
        tr = round(tp_range * 0.625, 3)
        if tr >= 0.08:
            tr = 0.055
        if tp_range >= 0.1:
            print(s, "tpが大きいので、LCChangeで０調整を行う")
            lc_change = [
                {"exe": True, "time_after": 0, "trigger": tr, "ensure": tp_range * 0.1},
            ]
        elif tp_range >= 0.05:
            print(s, "通常のLCChange")
            lc_change = [
                {"exe": True, "time_after": 0, "trigger": tr, "ensure": tp_range * 0.1},
            ]

        # 明示的に、結果を代入していく
        self.target_price_stop = target_price  # ストップ（順張り）用の価格
        self.tp_price_stop = tp_price
        self.tp_range_stop = tp_range
        self.lc_price_stop = lc_price
        self.lc_range_stop = lc_range
        self.lc_change_stop = lc_change
        self.stop_order_cancel = order_cancel  # 0以外でキャンセル
        self.stop_memo = "test"
        self.order_stop = "LIMIT"  # STOP関数なのにいったん、、LIMIT,,,
        # Small用
        self.tp_range_stop_s = tp_range_s
        self.tp_price_stop_s = tp_price_s
        # 参考
        self.tp_price_stop_wick = 0
        self.tp_range_stop_wick = 0
        self.lc_price_stop_wick = 0
        self.lc_range_stop_wick = 0


    def make_same_price_group(self, peaks,
                              upper_lower,
                              target_price,
                              width=0.03,
                              direction_filter=None,
                              sort_direction=-1,  # 1=昇順, -1=降順
                              ):
        # priceで絞り込み
        if upper_lower == -1:
            # 下側の場合
            filtered_peaks = [
                p for p in peaks
                if float(p['latest_body_peak_price']) < target_price
            ]
        else:
            # 上側の場合
            filtered_peaks = [
                p for p in peaks
                if float(p['latest_body_peak_price']) >= target_price
            ]
        # print("   ...", upper_lower)
        # print(filtered_peaks)
        # directionで絞り込み
        if direction_filter is not None:
            filtered_peaks = [
                p for p in filtered_peaks
                if p['direction'] == direction_filter
            ]
        groups = defaultdict(list)

        # グルーピング
        for p in filtered_peaks:
            price = float(p['latest_body_peak_price'])
            # 浮動小数誤差対策
            group_key = round(
                math.floor(price / width) * width,
                5
            )
            groups[group_key].append(p)
        results = []

        for group_key, items in groups.items():
            prices = [
                float(x['latest_body_peak_price'])
                for x in items
            ]
            latest_times = [
                datetime.strptime(
                    x['latest_time_jp'],
                    '%Y/%m/%d %H:%M:%S'
                )
                for x in items
            ]
            median_price = median(prices)
            results.append({
                # 'items': items,
                'median_price': median_price,
                'median': round(abs(target_price - median_price), 3),
                "total_strength": sum(float(x['peak_strength']) for x in items),
                'count': len(items),
                "ave_strength": round(sum(float(x['peak_strength']) for x in items) / len(items) if items else 0, 1),
                'prices': prices,
                'range_min': round(group_key, 5),
                'range_max': round(group_key + width, 5),
                'newest_time': max(latest_times).strftime('%Y/%m/%d %H:%M:%S'),
                'oldest_time': min(latest_times).strftime('%Y/%m/%d %H:%M:%S'),
            })
        # median_price降順
        results = sorted(
            results,
            key=lambda x: x['median_price'],
            reverse=(sort_direction == -1)
        )
        return results

    def predict_line_lower(self, target_price, time_before_h=3, threshold=0.023):
        # 現在価格より下にある、抵抗線候補を列挙する
        print("     PREDICT LINE LOWER  target", target_price)
        # 変数置換
        same_price_list_sum_border = 4  # 同価格リストの合計値の下限（これ以上ないと、Lineとして認めない）
        margin = 0.000
        peaks = self.peaks[0:35]
        # 時間でフィルタ
        border_time = datetime.strptime(self.current_time, '%Y/%m/%d %H:%M:%S') - timedelta(hours=time_before_h)
        peaks = [
            d for d in peaks
            if datetime.strptime(d['latest_time_jp'], '%Y/%m/%d %H:%M:%S') > border_time
        ]
        # for i, item in enumerate(peaks):
        #     print(item)
        minus_groups = self.make_same_price_group(
            peaks=peaks,
            upper_lower=-1,  # target_priceより下側
            target_price=target_price,
            width=0.02,
            sort_direction=-1  # 降順
        )
        for i, item in enumerate(minus_groups):
            print(item)

        # aveが1.5以上のもの。
        filtered = [d for d in minus_groups if d["ave_strength"] >= 1.5 and d['count'] >= 2]

        return filtered

    def predict_line_upper(self, target_price, time_before_h=3, threshold=0.023):
        # 現在価格より上にある、抵抗線候補を列挙する
        print("     PREDICT LINE UPPER")
        # 変数置換
        margin = 0.000
        peaks = self.peaks[0:35]
        # 時間でフィルタ
        border_time = datetime.strptime(self.current_time, '%Y/%m/%d %H:%M:%S') - timedelta(hours=time_before_h)
        peaks = [
            d for d in peaks
            if datetime.strptime(d['latest_time_jp'], '%Y/%m/%d %H:%M:%S') > border_time
        ]
        # for i, item in enumerate(peaks):
        #     print(item)
        minus_groups = self.make_same_price_group(
            peaks=peaks,
            upper_lower=1,  # target_priceより下側
            target_price=target_price,
            width=0.02,
            sort_direction=1  # 降順
        )
        for i, item in enumerate(minus_groups):
            print(item)

        filtered = [d for d in minus_groups if d["ave_strength"] >= 1.5 and d['count'] >= 2]
        return filtered

    def cal_units(self, lc_range, risk_yen=500, tag="s", yen_per_pip_per_lot=1000, ):
        """
        risk_yenは最大の負け額
        tagは注文がアプリからわかりやすいように、強引にUNITの一桁目を調整する。sの場合は1か６、lの場合は0か５になる
        yen_per_pip_per_lot:
            例）ドル円で1ロット=1000通貨なら約10円/pips
                1万通貨なら約100円/pips
        """
        # 基本的なUNIT計算
        doller_yen = 10000
        lc_pips = max(lc_range / 0.01, 0.000000001)  # 下のdeveide0を防ぎたい
        # print("　UNITSを計算する lc_range", lc_range, "pips", lc_pips, "許容損失", risk_yen)
        lot = risk_yen / (lc_pips * yen_per_pip_per_lot)
        units = int(lot * doller_yen)

        # 調整
        # 一桁目（10で割った余り）を取得
        last_digit = units % 10
        # 一桁目を除いた「十の位以上」のベース数値
        base = (units // 10) * 10
        if tag == "l":
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

        elif tag == "s":
            # 1か6、近い方に合わせる
            # unitsから1を引くと「0か5に合わせる問題」に置き換えられる
            adjusted = 5 * round((units - 1) / 5) + 1
            units = int(adjusted)

        return units

    def compare_with_exist_positions(self, position_control_class, plan_dir, plan_priority, plan_target_price=0):
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
                        "t_unrealize_pl": position.t_unrealize_pl,
                        "priority": position.plan_json['priority']
                    }
                    exist_positions.append(info)
            # 表示用
            # for i, ex_position in enumerate(exist_positions):
            #     print(" ", ex_position['name'], ex_position['t_unrealize_pl'],
            #           ex_position['direction'])

            # ■同方向の残存ポジションと、現在価格との比較
            matched_same_dir = [
                d for d in exist_positions
                if (
                        float(d.get("direction", 0)) * plan_dir > 0
                        and float(d.get("priority", 0)) >= plan_priority
                )
            ]
            exists_same_dir = len(matched_same_dir) >= 1  # booleanも持っておく

            # ■別方向かつ、プラス域の残存:ポジション
            matched_rev_dir = [
                d for d in exist_positions
                if (
                        float(d.get("direction", 0)) * plan_dir < 0
                        and float(d.get("pl", 0)) > 0
                        and float(d.get("priority", 0)) >= plan_priority
                )
            ]
            exists_rev_dir_plus = len(matched_rev_dir) >= 1  # booleanも持っておく

            # ■別方向かつ、プラス域の残存:ポジション
            matched_rev_dir_minus = [
                d for d in exist_positions
                if (
                        float(d.get("direction", 0)) * plan_dir < 0
                        and float(d.get("pl", 0)) > 0
                        and float(d.get("priority", 0)) >= plan_priority
                )
            ]
            exists_rev_dir_plus_minus = len(matched_rev_dir_minus) >= 1  # booleanも持っておく
            if exists_rev_dir_plus_minus:
                tk.line_send("別方向にマイナスポジションあり")

            print("残存オーダーとの比較結果", exists_same_dir, ", 指定条件の残存数", len(matched_same_dir),
                  "指定の方向", plan_dir)
            for i, item in enumerate(matched_same_dir):
                print("  ", item['name'], item['direction'], item['t_unrealize_pl'])

            if exists_same_dir or exists_rev_dir_plus:
                # 同方向の既存オーダーがある場合重複しないように、逆方向のプラスポジションがある場合は阻害しないように、オーダーなし。
                # 逆を言えば、逆方向のマイナスポジションの場合は、それを打ち消すような形でオーダー発行
                print("残存オーダーに同方向有！！", plan_dir, exists_same_dir, exists_rev_dir_plus)
                if exists_rev_dir_plus:
                    pass
                    # tk.line_send("逆方向のプラスポジションがあるため、それを阻害しないようにオーダーなし")
                elif exists_same_dir:
                    pass
                    # tk.line_send("同方向のオーダーがあるため、オーダーを控える？")
            else:
                pass

            # 値を格納する（Or条件のものだけリターンしておいた方が使いやすそう。単品はインスタンス変数参照）
            self.exists_same_dir = exists_same_dir
            self.exists_rev_dir_plus = exists_rev_dir_plus
            self.matched_rev_dir_minus = matched_rev_dir_minus
            return exists_same_dir or exists_rev_dir_plus

    def compare_with_history(self, position_control_class, plan_target_price, plan_dir):
        # ■履歴から、直近のマイナス傾向を算出する
        peaks = self.peaks
        # 過去１０回（３０分足だとほぼ１日分）と、トータルの合計を加味する
        positions = position_control_class.position_classes
        one_position = positions[0]  # 代表のポジション（クラス変数見るために一応）
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
