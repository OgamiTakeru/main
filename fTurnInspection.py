import fGeneric as gene
import pandas as pd
import classCandleAnalysis as ca
import classOrderCreate as OCreate
import tokens as tk


class turn_analisys:
    def __init__(self, candle_analysis):
        self.s = "    "
        self.oa = candle_analysis.base_oa
        # test時と本番時で、分岐（本番ではpeaks_classが渡されるが、テストではdfが渡されるため、peaks_classに変換が必要）
        self.ca = candle_analysis
        self.ca5 = self.ca.candle_class  # peaks以外の部分。cal_move_ave関数を使う用
        self.peaks_class = self.ca.peaks_class  # peaks_classだけを抽出
        self.ca60 = self.ca.candle_class_hour
        self.peaks_class_hour = self.ca.peaks_class_hour

        # 結果として使う大事な変数
        self.take_position_flag = False
        self.exe_order_classes = []

        # 簡易的な解析値
        peaks = self.peaks_class.peaks_original_marked_hard_skip
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
        self.units_str = 1  #0.1
        self.units_hedge = self.units_str * 0.9
        # 汎用性高め
        self.lc_change_test = [
            {"exe": True, "time_after": 0, "trigger": 0.01, "ensure": -1},  # ←とにかく、LCCandleを発動させたい場合
            {"exe": True, "time_after": 600, "trigger": self.ca5.cal_move_ave(2), "ensure": -0.001},
            {"exe": True, "time_after": 600, "trigger": self.ca5.cal_move_ave(4), "ensure": self.ca5.cal_move_ave(2)},
            {"exe": True, "time_after": 600, "trigger": self.ca5.cal_move_ave(5), "ensure": self.ca5.cal_move_ave(3)},
            {"exe": True, "time_after": 6000, "trigger": self.ca5.cal_move_ave(6), "ensure": self.ca5.cal_move_ave(4)},
            {"exe": True, "time_after": 600, "trigger": self.ca5.cal_move_ave(7), "ensure": self.ca5.cal_move_ave(5)},
            {"exe": True, "time_after": 600, "trigger": self.ca5.cal_move_ave(8), "ensure": self.ca5.cal_move_ave(6)},
            {"exe": True, "time_after": 600, "trigger": self.ca5.cal_move_ave(9), "ensure": self.ca5.cal_move_ave(7)},
            {"exe": True, "time_after": 600, "trigger": self.ca5.cal_move_ave(10), "ensure": self.ca5.cal_move_ave(8)},
            {"exe": True, "time_after": 600, "trigger": self.ca5.cal_move_ave(11), "ensure": self.ca5.cal_move_ave(9)},
        ]

        # ★★★調査実行
        self.turn_main()

    def add_order_and_flag_inspecion_class(self, order_class):
        """

        """
        self.take_position_flag = True
        self.exe_order_classes.append(order_class)
        # print("発行したオーダー2↓　(turn255)")
        # print(order_class.exe_order)

    def turn_main(self):
        """
        args[0]は必ずpeaks_classであること。
        args[1]は、本番の場合、過去の決済履歴のマイナスの大きさでTPが変わるかを検討したいため、オーダークラスを受け取る

        直近[0]がcount4の時、riverPeakにレジスタンスオーダーを入れる
        """
        # ■基本情報の取得
        # print("★★TURN　本番用")

        # ■実行除外
        # 対象のPeakのサイズを確認（小さすぎる場合、除外）
        peaks = self.peaks_class.peaks_original_marked_hard_skip
        peaks_skip = self.peaks_class.skipped_peaks_hard
        if peaks[1]['gap'] < 0.04:
            print("対象が小さい", peaks[1]['gap'])

        # ■基本的な情報の取得
        # (1)
        r = peaks[0]
        t = peaks[1]
        f = peaks[2]
        s = "   "
        print(s, "<SKIP前>", )
        gene.print_arr(peaks[:10])
        print("")
        print(s, "<SKIP後＞")
        gene.print_arr(peaks_skip[:10])

        # テスト専用のコード
        name_t = (("@" + str(self.rt.lo_ratio) + "@" +
                   str(self.rt.turn_strength_at_older)) + "@" + str(self.tf.lo_ratio) + "@" +
                  str(self.rt.skip_num_at_older) + "@" +
                  str(t['count']) + "@" + str(t['gap']))

        # (4)よく使う条件分岐を、簡略化しておく
        # ■一部共通の分岐条件を生成しておく
        if self.rt.skip_num_at_older < 3 and 0 < self.rt.turn_strength_at_older <= 8:
            is_extendable_line = True
        else:
            is_extendable_line = False

        # ■表示
        print(" ●判定パラメーター一覧●  rCount:", r['count'])
        print("  平均キャンドル長", self.ca5.cal_move_ave(1))
        print("  RT情報 比率:", self.rt.lo_ratio)
        print("  TF情報 比率:", self.tf.lo_ratio)
        print("  T情報 SKIP有無:", self.rt.skip_exist_at_older, ",Skip数:", self.rt.skip_num_at_older, "t-Count:", t['count'])
        print("       T-strength:", self.rt.turn_strength_at_older)
        print("  超レンジ状態", self.peaks_class.hyper_range)
        print("  ビッグキャンドル有無", self.peaks_class.is_big_move_candle)

        # ■■■　条件によるオーダー発行
        # ①BBの検証　直近１時間前、２時間前、３時間前のBBの幅の違いを求める
        self.bb_range_analysis(self.ca.d5_df_r)

        # ②フラッグ検証（最優先）
        self.flag_analysis(self.peaks_class.peaks_with_same_price_list)  # いつか分離できるように、引数に明示的に渡しておく
        if self.take_position_flag:
            # この時点でフラッグがTrueになっている場合、続きはやらない
            return 0

        # ③形状の検証
        # 　-1 BigMoveの場合 (そこそこ優先度高）
        if r['count'] == 2 and t['include_large']:
            print("BIG_MOVEテスト")
            print(t["latest_time_jp"], t['include_large'])
            self.big_move_r_direction_order()
            return 0
        # 　-2 ローソク形状による
        # 基本的にRiverがTurnより短いもの、かつ、riverカウントが2の物（折り返し直後）が対象。
        pat = 0
        comment = ""
        if self.rt.lo_ratio <= 0.4 and r['count'] == 2:
            if 0.8 <= self.tf.lo_ratio <= 1.2:
                comment = "ftで山形成⇒レンジへ"
                pat = 1
            elif self.tf.lo_ratio <= 0.4:
                comment = "ジグザグ⇒ブレイクへ"
                pat = 2
            else:
                comment = "中途半端⇒レンジ"
                pat = 1
        elif self.rt.lo_ratio <= 0.9 and r['count'] == 2:
            comment = "すぐTPしたい"
            pat = 3
        else:
            pass

        if pat == 0:
            return 0
        elif pat == 1:
            # レンジメイン
            # ■■オーダーを作成＆発行
            order_class1 = OCreate.Order({
                "name": comment,
                "current_price": self.peaks_class.latest_price,
                "target": 0,
                "direction": t['direction'],
                "type": "MARKET",
                "tp": self.base_tp_range,  # self.ca5.cal_move_ave(5),
                "lc": self.base_lc_range,
                "lc_change": self.lc_change_test,
                "units": self.units_str * 1.1,
                "priority": 4,
                "decision_time": self.peaks_class.df_r_original.iloc[0]['time_jp'],
                "candle_analysis_class": self.ca
            })
            self.add_order_and_flag_inspecion_class(order_class1)
            order_class2 = OCreate.Order({
                "name": comment + "HEDGE",
                "current_price": self.peaks_class.latest_price,
                "target": self.ca5.cal_move_ave(1.5),
                "direction": r['direction'],
                "type": "STOP",
                "tp": self.base_tp_range,  # self.ca5.cal_move_ave(5),
                "lc": self.base_lc_range,
                "lc_change": self.lc_change_test,
                "units": self.units_hedge * 1.1,
                "priority": 4,
                "decision_time": self.peaks_class.df_r_original.iloc[0]['time_jp'],
                "candle_analysis_class": self.ca
            })
            self.add_order_and_flag_inspecion_class(order_class2)
            # リンケージをたがいに登録する
            order_class1.add_linkage(order_class2)
            order_class2.add_linkage(order_class1)
        elif pat == 1.5:
            # レンジメイン(Hedgeなし！）
            order_class1 = OCreate.Order({
                "name": comment,
                "current_price": self.peaks_class.latest_price,
                "target": 0,
                "direction": t['direction'],
                "type": "MARKET",
                "tp": self.ca5.cal_move_ave(2),  # self.ca5.cal_move_ave(5),
                "lc": self.ca5.cal_move_ave(2),  # self.base_lc_range,
                "lc_change": self.lc_change_test,
                "units": self.units_str * 1.1,
                "priority": 4,
                "decision_time": self.peaks_class.df_r_original.iloc[0]['time_jp'],
                "candle_analysis_class": self.ca
            })
            self.add_order_and_flag_inspecion_class(order_class1)
        elif pat == 2:
            # ブレイクメイン
            order_class1 = OCreate.Order({
                "name": comment,
                "current_price": self.peaks_class.latest_price,
                "target": 0,
                "direction": r['direction'],
                "type": "MARKET",
                "tp": self.base_tp_range,  # self.ca5.cal_move_ave(5),
                "lc": self.base_lc_range,
                "lc_change": self.lc_change_test,
                "units": self.units_str,
                "priority": 4,
                "decision_time": self.peaks_class.df_r_original.iloc[0]['time_jp'],
                "candle_analysis_class": self.ca
            })
            self.add_order_and_flag_inspecion_class(order_class1)
            order_class2 = OCreate.Order({
                "name": comment + "HEDGE",
                "current_price": self.peaks_class.latest_price,
                "target": self.ca5.cal_move_ave(1.5),
                "direction": t['direction'],
                "type": "STOP",
                "tp": self.base_tp_range,  # self.ca5.cal_move_ave(5),
                "lc": self.base_lc_range,
                "lc_change": self.lc_change_test,
                "units": self.units_hedge,
                "priority": 4,
                "decision_time": self.peaks_class.df_r_original.iloc[0]['time_jp'],
                "candle_analysis_class": self.ca
            })
            self.add_order_and_flag_inspecion_class(order_class2)
            # リンケージをたがいに登録する
            order_class1.add_linkage(order_class2)
            order_class2.add_linkage(order_class1)
        elif pat == 3:
            # 動きが少なそうなので、すぐTP狙い
            order_class1 = OCreate.Order({
                "name": comment,
                "current_price": self.peaks_class.latest_price,
                "target": 0,
                "direction": r['direction'],
                "type": "MARKET",
                "tp": self.ca5.cal_move_ave(2),
                "lc": self.ca5.cal_move_ave(2),
                "lc_change": self.lc_change_test,
                "units": self.units_str * 0.9,
                "priority": 4,
                "decision_time": self.peaks_class.df_r_original.iloc[0]['time_jp'],
                "candle_analysis_class": self.ca
            })
            self.add_order_and_flag_inspecion_class(order_class1)
            order_class2 = OCreate.Order({
                "name": comment + "HEDGE",
                "current_price": self.peaks_class.latest_price,
                "target": self.ca5.cal_move_ave(1.5),
                "direction": t['direction'],
                "type": "STOP",
                "tp": self.ca5.cal_move_ave(2),  # self.base_tp_range,  # self.ca5.cal_move_ave(5),
                "lc": self.ca5.cal_move_ave(2),  # self.base_lc_range,
                "lc_change": self.lc_change_test,
                "units": self.units_hedge * 0.9,
                "priority": 4,
                "decision_time": self.peaks_class.df_r_original.iloc[0]['time_jp'],
                "candle_analysis_class": self.ca
            })
            self.add_order_and_flag_inspecion_class(order_class2)
            # リンケージをたがいに登録する
            order_class1.add_linkage(order_class2)
            order_class2.add_linkage(order_class1)

    def big_move_r_direction_order(self):
        """
        大きい変動が認められた場合、反発オーダーを順張りで、少し戻った位置で設ける。この場合、LCも入れたいなぁ
        """
        peaks = self.peaks_class.peaks_original_marked_hard_skip
        if peaks[1]['gap'] < 0.04:
            print("対象が小さい", peaks[1]['gap'])
            # return default_return_item

        # ■基本的な情報の取得
        # (1)
        r = peaks[0]
        t = peaks[1]
        f = peaks[2]
        comment = "大変動後の反発"

        target_price = r['latest_body_peak_price'] + (self.sp * t['direction'])
        order_class1 = OCreate.Order({
            "name": comment,
            "current_price": self.peaks_class.latest_price,
            "target": self.ca5.cal_move_ave(0.5),  # target_price,
            "direction": r['direction'],
            "type": "STOP",  # "MARKET",
            "tp": self.base_tp_range,  # self.ca5.cal_move_ave(5),
            "lc": self.base_lc_range,
            "lc_change": self.lc_change_test,
            "units": self.units_str,
            "priority": 3,
            "decision_time": self.peaks_class.df_r_original.iloc[0]['time_jp'],
            "candle_analysis_class": self.ca
        })
        self.add_order_and_flag_inspecion_class(order_class1)
        # ●ヘッジオーダー
        order_class2 = OCreate.Order({
            "name": comment + "HEDGE",
            "current_price": self.peaks_class.latest_price,
            "target": self.ca5.cal_move_ave(0.6),
            "direction": t['direction'],
            "type": "STOP",
            "tp": self.base_tp_range,  # self.ca5.cal_move_ave(5),
            "lc": self.base_lc_range,
            "lc_change": self.lc_change_test,
            "units": self.units_str,
            "priority": 3,
            "decision_time": self.peaks_class.df_r_original.iloc[0]['time_jp'],
            "candle_analysis_class": self.ca
        })
        self.add_order_and_flag_inspecion_class(order_class2)

        # リンケージをたがいに登録する
        order_class1.add_linkage(order_class2)
        order_class2.add_linkage(order_class1)

    def bb_range_analysis(self, df_r):
        """
        BBのすぼまりを見る
        """
        print("----BB analysis")
        check_point1 = 0  # 直近
        check_point2 = 12  # 12足前
        check_point3 = 24  # 24足前
        bb1_range = df_r.iloc[check_point1]['bb_range']
        bb2_range = df_r.iloc[check_point2]['bb_range']
        bb3_range = df_r.iloc[check_point3]['bb_range']
        print(self.s, df_r.iloc[check_point1]['time_jp'], df_r.iloc[check_point1]['bb_range'], df_r.iloc[check_point1]['bb_upper'])
        print(self.s, df_r.iloc[check_point2]['time_jp'], df_r.iloc[check_point2]['bb_range'], df_r.iloc[check_point2]['bb_upper'])
        print(self.s, df_r.iloc[check_point3]['time_jp'], df_r.iloc[check_point3]['bb_range'], df_r.iloc[check_point3]['bb_upper'])

        # サイズ感の処理
        if bb3_range >= bb2_range >= bb1_range:
            print(self.s, "完全収束傾向")
            is_converged = 1
        elif bb1_range >= bb2_range >= bb3_range:
            print(self.s, "完全発散傾向")
            is_converged = -1
        else:
            print(self.s, "収束とも発散とも言えない")
            is_converged = 0

        if is_converged == 1:
            ratio_1_3 = round(bb1_range / bb3_range, 3)
            if ratio_1_3 <= 0.6:
                print(self.s, "結構な収束傾向にあり", ratio_1_3)
            elif ratio_1_3 <= 0.81:
                print(self.s, "少々な収束傾向", ratio_1_3)

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
        print(self.s, "ターンの強度（同一価格数）", len(latest_peak['same_price_list']))
        for i, item in enumerate(latest_peak['same_price_list']):
            print("          ",  item['i'], item['item']['latest_time_jp'], item['item']['peak_strength'])
        print(self.s, "Breakまでの同一価格")
        for i, item in enumerate(latest_peak['same_price_list_till_break']):
            print("          ",  item['i'], item['item']['latest_time_jp'], item['item']['peak_strength'])
        print(self.s, "Breakまでの同一価格(上位ランクのみ）")
        for i, item in enumerate(same_price_list_till_break_5):
            print("          ", item['i'], item['item']['latest_time_jp'], item['item']['peak_strength'])
        print(self.s, "反対サイド")
        for i, item in enumerate(latest_peak['opposite_peaks']):
            print("          ",  item['i'], item['item']['latest_time_jp'], item['item']['peak_strength'], item['item']['direction'])

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
            "lc_change": self.lc_change_test,
            "units": self.units_str * 1.2,
            "priority": 11,
            "decision_time": self.peaks_class.df_r_original.iloc[0]['time_jp'],
            "candle_analysis_class": self.ca
        })
        self.add_order_and_flag_inspecion_class(order_class1)
        order_class2 = OCreate.Order({
            "name": "フラッグレンジ(Hedge)方向",
            "current_price": self.peaks_class.latest_price,
            "target": self.ca5.cal_move_ave(1.5),
            "direction": r['direction'],
            "type": "STOP",
            "tp": self.base_tp_range,  # self.ca5.cal_move_ave(5),
            "lc": self.ca5.cal_move_ave(2),  # self.base_lc_range,
            "lc_change": self.lc_change_test,
            "units": self.units_hedge * 1.2,
            "priority": 11,
            "decision_time": self.peaks_class.df_r_original.iloc[0]['time_jp'],
            "candle_analysis_class": self.ca
        })
        self.add_order_and_flag_inspecion_class(order_class2)
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

        on_line_ratio = round(on_line_num / total_peaks_num, 3)
        near_line_ratio = round(near_line_num / total_peaks_num, 3)
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
        ave_peak_price = round(total_peak / len(target_peaks), 3)
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
        peaks = self.peaks_class.peaks_original_marked_hard_skip
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
        self.single_peak_additional_information_older(older_no)  # olderの解析
        self.single_peak_additional_information_later(older_no - 1)  # laterの解析
        self.relation_2peaks_information(older_peak, later_peak)  # 二つにまつわる解析


        # 表示
        # print("   later:", later_peak['latest_time_jp'])
        # print("   older:", older_peak['latest_time_jp'])
        # print("   laterCount", later_peak['count'], "olderCount", older_peak['count'])
        # print("   olderスキップ有:", self.skip_exist_at_older, "olderSKIP数", self.skip_num_at_older)
        # print("   olderターン強度", self.turn_strength_at_older, "戻り率(通常)", self.lo_ratio)
        # print("  ↑")

    def single_peak_additional_information_older(self, peak_no):
        """
        一つのピークの調査内容。peak_noで指定される
        基本的に１はターン、２はフロップを示す
        """
        # ■情報の元
        peaks = self.peaks_class.peaks_original_marked_hard_skip
        peaks_sk = self.peaks_class.skipped_peaks_hard  # 元々の
        target_peak = peaks[peak_no]  # 基本時間的に古いほうが入る。riverとturnの場合は１(turn)
        if len(peaks_sk) <= peak_no:
            # スキップの場合、１つになってしまっていることが、、
            print(" @@@@@@スキップでピークが一つになって少し変な状況")
            target_peak_sk = target_peak  # とりあえずtargetPeakと同じものを入れて暫定
        else:
            # こっちが本来ほしいほう
            target_peak_sk = peaks_sk[peak_no]

        # ■各種調査
        # print("   SinglePeakAdditional関数 ターゲットNo:", peak_no, target_peak_sk)
        # ⓪計算不要
        self.skip_num_at_older = target_peak_sk['skip_include_num']
        # ①　強度の判定
        self.peaks_class.make_same_price_list(peak_no, False)  # クラス内でSamePriceListを実行
        self.turn_strength_at_older = sum(d["item"]["peak_strength"] for d in self.peaks_class.same_price_list)
        # gene.print_arr(self.peaks_class.same_price_list)

        # ②turnを生成するPeakに、スキップがあったかを確認する
        if self.peaks_class.cal_target_times_skip_num(self.peaks_class.skipped_peaks_hard, target_peak['latest_time_jp']) >= 1:
            self.skip_exist_at_older = True
        else:
            self.skip_exist_at_older = False

        # ③トレンド減速検知
        target_df = self.peaks_class.peaks_original_with_df[1]['data']  # "data"は特殊なPeaksが所持（スキップ非対応）
        brake_trend_exist = False
        # print("[1]のデータ")
        # print(target_df)
        if len(target_df) < 4:
            # print("target_dataが少なすぎる([1]がやけに短い⇒TrendBrakeあり？）")
            brake_trend_exist = True
        else:
            # BodyAveで検討
            older_body_ave = round((target_df.iloc[2]['body_abs'] + target_df.iloc[3]['body_abs']) / 2,
                                   2) + 0.0000000001  # 0防止
            later_body_ave = round((target_df.iloc[0]['body_abs'] + target_df.iloc[1]['body_abs']) / 2,
                                   2) + 0.0000000001  # 0防止
            # print("ratio", round(older_body_ave / later_body_ave, 2), "older", older_body_ave, "latest", later_body_ave)
            if older_body_ave / later_body_ave >= 3.5:  # 数が大きければ、よりブレーキがかかる
                # print("傾きの顕著な減少（ボディ）")
                brake_trend_exist = True

        # ④最後の足の方向について
        # r_df = self.peaks_class.peaks_original_with_df[0]['data']
        # latest_df = r_df.iloc[0]
        # latest_same = False
        # if (r['direction'] == 1 and latest_df['body'] > 0) or (r['direction'] == -1 and latest_df['body'] < 0):
        #     # print("リバーが正方向＋リバー最後が陽線 or リバーが負方向＋リバー最後が陰線", r['direction'], latest_df['body'])
        #     latest_same = True
        # else:
        #     pass
        #     # print("NG リバー方向", r['direction'], "ボディー向き", latest_df['body'])

        # ⑤（基本riverで利用）最後の二つのローソクの向きが同じ、かつ、方向と同じかどうか
        if peak_no == 0:
            r_df = self.peaks_class.peaks_original_with_df[0]['data']
            latest_df = r_df.iloc[0]
            second_df = r_df.iloc[1]
            if target_peak['direction'] == 1 and latest_df['body'] > 0 and second_df['body'] > 0:
                self.is_same_direction_at_river = True  # リバー専用？　リバーの向きと、その直近2個のローソクの向きが同じかどうか
                self.second_last_close_price = second_df['close']
                print("　　◎リバーの方向が全部同じ（正方向）", self.second_last_close_price)
            elif target_peak['direction'] == -1 and latest_df['body'] < 0 and second_df['body'] < 0:
                self.is_same_direction_at_river = True  # リバー専用？　リバーの向きと、その直近2個のローソクの向きが同じかどうか
                self.second_last_close_price = second_df['close']
                print("　　　◎リバーの方向が全部同じ（負方向）", self.second_last_close_price)
            else:
                pass
                # print("　　　 リバー方向", target_peak['direction'], "ボディー向き", latest_df['body'], second_df['body'])

    def single_peak_additional_information_later(self, peak_no):
        """
        時系列的に新しい（rtの場合、river側(0)）
        基本Riverの状況を確認したいだけに作っている状況。他の値は使ってない。

        """
        # ■情報の元
        peaks = self.peaks_class.peaks_original_marked_hard_skip
        peaks_sk = self.peaks_class.skipped_peaks_hard  # 元々の
        target_peak = peaks[peak_no]  # 基本時間的に古いほうが入る。riverとturnの場合は１(turn)
        if len(peaks_sk) <= peak_no:
            # スキップの場合、１つになってしまっていることが、、
            print(" @@@@@@スキップでピークが一つになって少し変な状況")
            target_peak_sk = target_peak  # とりあえずtargetPeakと同じものを入れて暫定
        else:
            # こっちが本来ほしいほう
            target_peak_sk = peaks_sk[peak_no]

        # ■各種調査
        # print("   SinglePeakAdditional関数 ターゲットNo:", peak_no, target_peak_sk)
        # ⓪計算不要
        self.skip_num_at_later = target_peak_sk['skip_include_num']
        # ①　強度の判定
        self.peaks_class.make_same_price_list(peak_no, False)  # クラス内でSamePriceListを実行
        self.turn_strength_at_later = sum(d["item"]["peak_strength"] for d in self.peaks_class.same_price_list)
        # gene.print_arr(self.peaks_class.same_price_list)

        # ②turnを生成するPeakに、スキップがあったかを確認する
        if self.peaks_class.cal_target_times_skip_num(self.peaks_class.skipped_peaks_hard, target_peak['latest_time_jp']) >= 1:
            self.skip_exist_at_later = True
        else:
            self.skip_exist_at_later = False

        # ③トレンド減速検知
        target_df = self.peaks_class.peaks_original_with_df[1]['data']  # "data"は特殊なPeaksが所持（スキップ非対応）
        brake_trend_exist = False
        # print("[1]のデータ")
        # print(target_df)
        if len(target_df) < 4:
            # print("target_dataが少なすぎる([1]がやけに短い⇒TrendBrakeあり？）")
            brake_trend_exist = True
        else:
            # BodyAveで検討
            older_body_ave = round((target_df.iloc[2]['body_abs'] + target_df.iloc[3]['body_abs']) / 2,
                                   2) + 0.0000000001  # 0防止
            later_body_ave = round((target_df.iloc[0]['body_abs'] + target_df.iloc[1]['body_abs']) / 2,
                                   2) + 0.0000000001  # 0防止
            # print("ratio", round(older_body_ave / later_body_ave, 2), "older", older_body_ave, "latest", later_body_ave)
            if older_body_ave / later_body_ave >= 3.5:  # 数が大きければ、よりブレーキがかかる
                # print("傾きの顕著な減少（ボディ）")
                brake_trend_exist = True

        # ④最後の足の方向について
        # r_df = self.peaks_class.peaks_original_with_df[0]['data']
        # latest_df = r_df.iloc[0]
        # latest_same = False
        # if (r['direction'] == 1 and latest_df['body'] > 0) or (r['direction'] == -1 and latest_df['body'] < 0):
        #     # print("リバーが正方向＋リバー最後が陽線 or リバーが負方向＋リバー最後が陰線", r['direction'], latest_df['body'])
        #     latest_same = True
        # else:
        #     pass
        #     # print("NG リバー方向", r['direction'], "ボディー向き", latest_df['body'])

        # ⑤（基本riverで利用）最後の二つのローソクの向きが同じ、かつ、方向と同じかどうか
        if peak_no == 0:
            r_df = self.peaks_class.peaks_original_with_df[0]['data']
            latest_df = r_df.iloc[0]
            second_df = r_df.iloc[1]
            if target_peak['direction'] == 1 and latest_df['body'] > 0 and second_df['body'] > 0:
                self.is_same_direction_at_river_later = True  # リバー専用？　リバーの向きと、その直近2個のローソクの向きが同じかどうか
                self.second_last_close_price_later = second_df['close']
                # print("　　◎リバーの方向が全部同じ（正方向）", self.second_last_close_price_later)
            elif target_peak['direction'] == -1 and latest_df['body'] < 0 and second_df['body'] < 0:
                self.is_same_direction_at_river_later = True  # リバー専用？　リバーの向きと、その直近2個のローソクの向きが同じかどうか
                self.second_last_close_price_later = second_df['close']
                # print("　　　◎リバーの方向が全部同じ（負方向）", self.second_last_close_price_later)
            else:
                pass
                # print("　　　NG リバー方向", target_peak['direction'], "ボディー向き", latest_df['body'], second_df['body'])

    def relation_2peaks_information(self, older_peak, later_peak):
        """
        渡された二つのピークの関係性を算出する
        unit_noが１の場合は、riverとturn。unit_noが２の場合は、turnとflop
        """
        # rt_ratio_sk = round(r_sk['gap'] / t_sk['gap'], 3)
        self.lo_ratio = round(later_peak['gap'] / older_peak['gap'], 3)


class range_analisys:
    def __init__(self, candle_analysis):
        self.s = "    "
        self.oa = candle_analysis.base_oa
        # test時と本番時で、分岐（本番ではpeaks_classが渡されるが、テストではdfが渡されるため、peaks_classに変換が必要）
        self.ca = candle_analysis
        self.ca5 = self.ca.candle_class  # peaks以外の部分。cal_move_ave関数を使う用
        self.peaks_class = self.ca.peaks_class  # peaks_classだけを抽出
        self.ca60 = self.ca.candle_class_hour
        self.peaks_class_hour = self.ca.peaks_class_hour

        # 結果として使う大事な変数
        self.take_position_flag = False
        self.exe_order_classes = []

        # BB調査の結果
        self.bb_upper = 0
        self.bb_lower = 0
        self.bb_range = 0
        self.bb_current_ratio = 0
        self.test_comment = ""
        self.latest_peak_price = 0

        # 簡易的な解析値
        peaks = self.peaks_class.peaks_original_marked_hard_skip
        self.current_price = self.peaks_class.latest_price
        r = peaks[0]
        t = peaks[1]
        f = peaks[2]
        self.latest_peak_price = t['latest_body_peak_price']

        # 上限下限の線
        self.upper_line = 0
        self.lower_line = 999

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
        self.units_str = 1  #0.1
        self.units_hedge = self.units_str * 0.9
        # 汎用性高め
        self.lc_change_test = [
            {"exe": True, "time_after": 0, "trigger": 0.01, "ensure": -1},  # ←とにかく、LCCandleを発動させたい場合
            {"exe": True, "time_after": 600, "trigger": self.ca5.cal_move_ave(2), "ensure": -0.001},
            {"exe": True, "time_after": 600, "trigger": self.ca5.cal_move_ave(4), "ensure": self.ca5.cal_move_ave(2)},
            {"exe": True, "time_after": 600, "trigger": self.ca5.cal_move_ave(5), "ensure": self.ca5.cal_move_ave(3)},
            {"exe": True, "time_after": 6000, "trigger": self.ca5.cal_move_ave(6), "ensure": self.ca5.cal_move_ave(4)},
            {"exe": True, "time_after": 600, "trigger": self.ca5.cal_move_ave(7), "ensure": self.ca5.cal_move_ave(5)},
            {"exe": True, "time_after": 600, "trigger": self.ca5.cal_move_ave(8), "ensure": self.ca5.cal_move_ave(6)},
            {"exe": True, "time_after": 600, "trigger": self.ca5.cal_move_ave(9), "ensure": self.ca5.cal_move_ave(7)},
            {"exe": True, "time_after": 600, "trigger": self.ca5.cal_move_ave(10), "ensure": self.ca5.cal_move_ave(8)},
            {"exe": True, "time_after": 600, "trigger": self.ca5.cal_move_ave(11), "ensure": self.ca5.cal_move_ave(9)},
        ]

        # ★★★調査実行
        self.range_main()

    def add_order_and_flag_inspection_class(self, order_class):
        """

        """
        self.take_position_flag = True
        self.exe_order_classes.append(order_class)
        # print("発行したオーダー2↓　(turn255)")
        # print(order_class.exe_order)

    def range_main(self):
        """

        """
        # ■基本情報の取得
        # print("★★TURN　本番用")

        # ■実行除外
        # 対象のPeakのサイズを確認（小さすぎる場合、除外）
        peaks = self.peaks_class.peaks_original_marked_hard_skip
        r = peaks[0]
        t = peaks[1]
        f = peaks[2]
        peaks_skip = self.peaks_class.skipped_peaks_hard
        if peaks[1]['gap'] < 0.04:
            print("対象が小さい", peaks[1]['gap'])

        if r['count'] != 2:
            return 0

        # ■表示
        print(" ●RangeAnalysis判定パラメーター一覧●  rCount:", r['count'])
        print("  平均キャンドル長", )

        # ■■■　条件によるオーダー発行
        # ①BBの検証　直近１時間前、２時間前、３時間前のBBの幅の違いを求める
        self.bb_range_analysis(self.ca.d5_df_r)  # self.test_commentに空欄、trend、rangeのいずれかを入れる

        # ②抵抗線の算出
        turn_info = self.support_line_detect(1)  # turn部分もの（上下かは問わず）
        flop_info = self.support_line_detect(2)  # flop部分もの（上下かは問わず）
        # ②フラッグ検証（最優先）
        # self.flag_analysis(self.peaks_class.peaks_with_same_price_list)  # いつか分離できるように、引数に明示的に渡しておく

        # ■■■判定

        if self.test_comment == "range":  # 比較的横這いか、下降上昇が長い状態(レンジ～レンジ解消に向かっている）
            mes = ""
            print(self.s, turn_info['line_strength'], flop_info['line_strength'])
            if turn_info['line_strength'] >= 5 and flop_info['line_strength'] >= 5:
                mes = "BB横這い　＆　完全横這い"
                print(self.s, "BB横這い　＆　完全横這い")
            elif turn_info['line_strength'] >=5 and flop_info['line_strength'] < 5:
                if t['direction'] == 1:
                    print(self.s, "BB横這い　＆　上限あり1")
                    mes = "BB横這い　＆　上限あり1"
                else:
                    print(self.s, "BB横這い　＆　下限あり2")
                    mes = "BB横這い　＆　下限あり2"
            elif turn_info['line_strength'] < 5 and flop_info['line_strength'] >= 5:
                if peaks[2]['direction'] == 1:
                    print(self.s, "BB横這い　＆　上限あり3")
                    mes = "BB横這い　＆　上限あり3"
                else:
                    print(self.s, "BB横這い　＆　下限あり4")
                    mes = "BB横這い　＆　下限あり4"
                # print(self.s, "BB横這い　＆　turnバラバラ（フラッグの可能性もあり）")




    def support_line_detect(self, target_no):
        # ②抵抗線を探す（上側）
        peaks_with_same_price_list = self.peaks_class.peaks_with_same_price_list
        # gene.print_arr(peaks_with_same_price_list)
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
        print("----抵抗線検知  [方向]", d)
        print(self.s, "ターンの強度（同一価格数）", len(same_price_list), "total", same_price_list_total)
        for i, item in enumerate(same_price_list):
            print("          ",  item['i'], item['item']['latest_time_jp'], item['item']['peak_strength'], item['item']['direction'])
        print(self.s, "Breakまでの同一価格(上位ランクのみ） total", same_price_list_till_break_5_total)
        for i, item in enumerate(same_price_list_till_break_5):
            print("          ", item['i'], item['item']['latest_time_jp'], item['item']['peak_strength'])

        # 判定
        line_strength = 0
        if same_price_list_total <= 2:
            line_strength = 0
            print(self.s, "抵抗なし(自身のみの検出）")
        elif same_price_list_total <= 4:
            line_strength = 1
            print(self.s, "引っ掛かり程度の抵抗線")
        elif same_price_list_total < 10:  # 12は5が二つと2が一つを想定。
            if same_price_list_till_break_5_total >= 10:
                print(self.s, "準 相当強めの抵抗線", same_price_list_total, same_price_list_till_break_5_total)
                line_strength = 7
            elif same_price_list_till_break_5_total >= 5 and len(same_price_list) >= 2:
                print(self.s, "軽いダブルトップ抵抗線", same_price_list_total, same_price_list_till_break_5_total)
                line_strength = 5
            else:  # =5の場合は、自身のみ
                print(self.s, "５自身のみか、複数の２", same_price_list_total, same_price_list_till_break_5_total)
                line_strength = 3
        else:
            # 12以上
            if same_price_list_till_break_5_total >= 10:
                print(self.s, "相当強めの抵抗線", same_price_list_total, same_price_list_till_break_5_total)
                line_strength = 10
            else:
                print(self.s, "強めの抵抗線", same_price_list_total, same_price_list_till_break_5_total)
                line_strength = 7

        # 狭い脚判定
        if len(same_price_list) == 2:
            latest_time = same_price_list[0]['item']['latest_time_jp']
            oldest_time = same_price_list[1]['item']['latest_time_jp']
            ans = gene.cal_str_time_gap(latest_time, oldest_time)
            print(self.s, ans['gap_abs']/60, "分", latest_time, oldest_time)

        # 登録
        if d == 1:
            self.upper_line = target_price
        else:
            self.lower_line = target_price
        print(self.s, self.upper_line ,"-", self.lower_line)


        return {
            "same_price_list": same_price_list,
            "same_price_list_total": same_price_list_total,
            "same_price_list_till_break_5": same_price_list_till_break_5,
            "same_price_list_till_break_5_total": same_price_list_till_break_5_total,
            "line_strength": line_strength
        }


    def bb_range_analysis(self, df_r):
        """
        BBのすぼまりを見る
        """
        print("----BB analysis")
        allowed_ratio = 0.8  # 2割程度のサイズの違いは同等とみなす
        check_point1 = 0  # 直近
        check_point2 = 12  # 12足前
        check_point3 = 24  # 24足前
        bb1_range = df_r.iloc[check_point1]['bb_range']
        bb2_range = df_r.iloc[check_point2]['bb_range']
        bb3_range = df_r.iloc[check_point3]['bb_range']
        print(self.s, df_r.iloc[check_point1]['time_jp'], df_r.iloc[check_point1]['bb_range'], df_r.iloc[check_point1]['bb_upper'])
        print(self.s, df_r.iloc[check_point2]['time_jp'], df_r.iloc[check_point2]['bb_range'], df_r.iloc[check_point2]['bb_upper'])
        print(self.s, df_r.iloc[check_point3]['time_jp'], df_r.iloc[check_point3]['bb_range'], df_r.iloc[check_point3]['bb_upper'])

        # BBの広さと、現在の価格の位置関係を抑える
        self.bb_range = df_r.iloc[check_point1]['bb_range']
        self.bb_upper = df_r.iloc[check_point1]['bb_upper']
        self.bb_lower = df_r.iloc[check_point1]['bb_lower']
        self.bb_current_ratio = 100 * (self.bb_upper - self.current_price) / (self.bb_upper - self.bb_lower)
        # 現在の位置関係
        C = self.current_price
        C = self.latest_peak_price
        dist_to_A = abs(C - self.bb_upper)
        dist_to_B = abs(C - self.bb_lower)
        # 基準を選択（等距離ならA）
        if dist_to_A <= dist_to_B:
            base = "UPPER"
            percent = 100 * (self.bb_upper - C) / (self.bb_upper - self.bb_lower)
        else:
            base = "LOWER"
            percent = 100 * (C - self.bb_lower) / (self.bb_upper - self.bb_lower)
        bb_latest_peak_ratio = 100 * (self.bb_upper - self.latest_peak_price) / (self.bb_upper - self.bb_lower)
        print("現在価格の存在位置（上限基準)", percent, base)
        print("kakaku", self.latest_peak_price, self.current_price)


        # 幅が同じでも、移動している場合があるため、三つのラップ率を算出する（直近のBBに対して、何割ラップしているか）
        pairs = [(df_r.iloc[check_point1]['bb_lower'], df_r.iloc[check_point1]['bb_upper']),
                 (df_r.iloc[check_point2]['bb_lower'], df_r.iloc[check_point2]['bb_upper']),
                 (df_r.iloc[check_point3]['bb_lower'], df_r.iloc[check_point3]['bb_upper'])]
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
                "range": round(abs(length), 3),
                "rap_ratio": round(overlap_rate * 100, 1),  # %
                "size_ratio": round(size_ratio, 2),  # 直近を基準にした、各々のサイズ比率（BBなので2倍くらいなら同じとみなすかも）
                "tag": tag,
                "kukan": f"{start}-{end}",
            })
        print(self.s, "base", base_len)
        for r in results:
            print(self.s, r)

        # 重なり判定
        r0 = results[0]['rap_ratio']  # ０とついているが、直近を含めない、一番最初という意味
        r1 = results[1]['rap_ratio']
        rap_res = 0
        rap_comment = ""
        t = str(r0) + "," + str(r1)
        # if r0 >= 90:
        #     if r1 >= 90:
        #         rap_res = "flat-flag-just_flat"
        #         rap_comment = "直近ラップ結構大（きれいな平坦、フラッグ(両傾斜フラッグ含）、平坦型収束[収束の瞬間])"
        #     elif r1 >= 70:
        #         rap_res = "soon_flat"
        #         rap_comment = "直近ラップ結構大（上昇や下降から少し立った時（または弱めの上昇から)"
        #     else:  # r1 < 70
        #         rap_res = "just_flat"
        #         rap_comment = "直近ラップ結構大（上昇や下降直後に近い（少し強めの上昇から)"
        # elif r0 >= 80:
        #     if r1 >= 80:
        #         rap_res = "flat-flag-just_flat"
        #         rap_comment = "直近ラップ結構大（きれいな平坦、フラッグ(両傾斜フラッグ含）、平坦型収束[収束の瞬間])"
        #     elif r1 <= 60:
        #         rap_res = "just_flat"
        #         rap_comment = "直近ラップ結構大（急速な上昇や下降直後)"
        #     else:  # r1 >= 60
        #         rap_res = "soon_flat"
        #         rap_comment = "直近ラップ結構大（上昇や下降から少し立った時)"
        # elif r0 >= 70:
        #     if r1 >= 70:
        #         rap_res = "flat-flag-just_flat"
        #         rap_comment = "ラップ大（やや平坦で多少の傾きの可能性あり、フラッグ(両傾斜フラッグ含）、平坦型収束)"
        #     elif r1 <= 45:
        #         rap_res = "diverge_converge"
        #         rap_comment = "直近ラップわりと大（少し緩やかな上昇）、収まり始め、発散はじめ（発散フラッグ）"
        #     else:  # 45～70
        #         rap_res = "UNKNOWN"
        #         rap_comment = "微妙な状態"
        # elif r0 <= 55:
        #     if r1 <= 57:
        #         rap_res = "converge"
        #         rap_comment = "結構半分以下（発散始め or 極端な乱高下)"
        #     elif abs(r0 - r1) <= 10:
        #         rap_res = "converge"
        #         rap_comment = "レンジから発散し始めたタイミング"
        #     else:  # r1が５７より大きい場合。
        #         rap_res = "UNKNOWN"
        #         rap_comment = "よくわからない形"
        # elif r0 <= 70:
        #     if r1 <= 55:
        #         rap_res = "trend_flag"
        #         rap_comment = "完全なトレンド中、フラッグ広がり"
        #     elif abs(r0 - r1) <= 10:
        #         rap_res = "trend_flag"
        #         rap_comment = "レンジから発散し始めたタイミング"
        # print(self.s, rap_comment, " ,", t)

        # 割合判定
        sr0 = results[0]['size_ratio']  # ０とついているが、直近を含めない、一番最初という意味
        sr1 = results[1]['size_ratio']
        ts = str(sr0) + "," + str(sr1)
        # サイズ感の処理
        size_res = 0
        size_comment = ""

        # if abs(sr0 - sr1) < 0.4:
        #     # ■残り二つが同じサイズ
        #     # ①完全平行系
        #     if 0.8 <= sr0 <= 1.3 and 0.8 <= sr0 <= 1.3:
        #         size_comment = "flat"
        #     # ②前側平行系(ラッパ型）
        #     elif sr0 < 0.8 and sr1 < 0.8:
        #         size_comment = "trumpet"
        #     # ③後側平衡系（収束系）
        #     elif sr0 > 1.3 and sr1 > 1.3:
        #         size_comment = "re-trumpet"
        #     else:
        #         size_comment = "UnKnown"
        # elif sr0 > sr1 + 0.4:
        #     # ■発散系（直前が最初より明らかに大きい）
        #     # ①直前が1より小さい（直近が一番大きくなるフラッグ）
        #     if sr0 < 0.8:
        #         size_comment = "bigbang"
        #     elif 0.8 <= sr0 <= 1.3:
        #         size_comment = "semi_flat_from_small"
        #     else:
        #         size_comment = "中膨れ系(1時間程度の強変動後)"
        # elif sr1 > sr0 + 0.4:
        #     # ■収束系
        #     # ①直前が1より小さい（直近が一番大きくなるフラッグ）
        #     if sr0 < 0.8:
        #         size_comment = "中すぼみ系"
        #     elif 0.8 <= sr0 <= 1.3:
        #         size_comment = "semi_flat_from_big"
        #     else:
        #         size_comment = "flag"
        res_com = ""
        order_recommend = ""
        if abs(sr0 - sr1) < 0.3:
            # ■残り二つが同じサイズ
            # ①完全平行系
            if 0.7 <= sr0 <= 1.3 and 0.7 <= sr0 <= 1.3:
                size_comment = "parallel"
                # ■■ラップ率で傾きを判断
                # if r0 >= 88 and r1 >= 88:
                b = 70
                if r0 >= b and r1 >= b:
                    res_com = "フラット"
                    order_recommend = "range"
                elif r0 >= b and r1 < b:
                    res_com = "直近トレンド（平行折り返し後）"
                    order_recommend = "range"
                elif r0 < b and r1 < b-10 and r0 > r1:
                    res_com = "平行移動のトレンド"
                    order_recommend = "trend"
                else:
                    res_com = "平行移動のトレンドっぽいが微妙に違う"

            # ②前側平行系(ラッパ型）
            elif sr0 < 0.7 and sr1 < 0.7:
                size_comment = "trumpet"
                # ■■ラップで傾きを判定
                if r0 >= 90 and r1 >= 90:
                    res_com = "ラッパ型トレンドからの発散系"
                    order_recommend = "trend"
                elif r0 < 85:
                    if r1 <= 60:
                        res_com = "ラッパ型トレンド"
                        order_recommend = "trend"
                    else:
                        res_com = "ラッパ型トレンド（前ラップ大）"
                        order_recommend = "trend"
                else:
                    res_com = "ラッパ型中途半端"
            # ③後側平衡系（収束系）
            elif sr0 > 1.3 and sr1 > 1.3:
                size_comment = "re-trumpet"
                order_recommend = "range"
                # ■■ラップで傾きを判定
                if r0 >= 85:
                    if r1 >= 95:
                        res_com = "逆トランペット"
                    elif r1 <= 70:
                        res_com = "逆トランペット＿変動後の収束"
                    else:
                        res_com = "逆トランぺット中途半端１"
                elif r0 < 85:
                    if r1 <= 70:
                        res_com = "逆トランペット＿変動後の収束２"
                    else:
                        res_com = "逆トランペット中途半端２"
            else:
                size_comment = "UnKnown"
                res_com = "UnKnown1"
        elif sr0 > sr1 + 0.4:
            # ■発散系（直前が最初より明らかに大きい）
            # ①直前が1より小さい（直近が一番大きくなるフラッグ）
            if sr0 < 0.8:
                size_comment = "bigbang"
                order_recommend = "trend"
                # ■■ラップで傾きを判定
                if r0 >= 90:
                    if r1 >= 90:
                        res_com = "ビッグバン型"
                    else:
                        res_com = "ビッグバン型　初期ちょいずれ"
                else:
                    if r1 >= 90:
                        res_com = "ビッグバン型　トレンドに入りそう"
                    else:
                        res_com = "ビッグバン型　トレンド"
            elif 0.8 <= sr0 <= 1.3:
                size_comment = "semi_flat_from_small"
                res_com = "semi_flat_from_small"
                order_recommend = "range"
            else:
                size_comment = "中膨れ系(1時間程度の強変動後)"
                res_com = "中膨れ系（一時間程度の強変動後）"
                order_recommend = "range"
        elif sr1 > sr0 + 0.4:
            # ■収束系
            # ①直前が1より小さい（直近が一番大きくなるフラッグ）
            if sr0 < 0.8:
                size_comment = "中すぼみ系"
                res_com = "中すぼみ系（一時間程度の強変動）⇒発散？？"
                order_recommend = "trend"
            elif 0.8 <= sr0 <= 1.3:
                size_comment = "semi_flat_from_big"
                res_com = "semi_flat_from_big"
                order_recommend = "range"
            else:
                size_comment = "flag"
                # ■■ラップで傾きを判定
                if r0 >= 95:
                    if r1 >= 95:
                        res_com = "フラッグ型　両サイド収束"
                        order_recommend = "trend"
                    else:
                        res_com = "フラッグ型　両サイド収束ちょいずれ"
                        order_recommend = "trend"
                else:
                    if r1 >= 90:
                        res_com = "フラッグ型　ブレイク気味"
                        order_recommend = "trend"
                        # order_recommend = "break"
                    else:
                        res_com = "フラッグ型　トレンド"
                        order_recommend = "trend"
        print(self.s, size_comment, str(ts))


        # 最終判定
        if rap_res == 0:  # 結構ラップしている場合(中央の価格は変わっていない⇒後はすぼんでるか広がってるか）
            pass

        for_line = res_com + "　:　" + "【" + order_recommend + "】" + str(ts) + ",　" + str(t)
        self.test_comment = order_recommend
        tk.line_send(for_line)


    def cal_tilt(self, target_peaks):
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

        on_line_ratio = round(on_line_num / total_peaks_num, 3)
        near_line_ratio = round(near_line_num / total_peaks_num, 3)
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
        ave_peak_price = round(total_peak / len(target_peaks), 3)
        lc_margin = dependence_lc_range * d * -1
        ave_peak_price = ave_peak_price + lc_margin

        print(self.s, remark, on_line_ratio, near_line_ratio)

        return is_tilt
