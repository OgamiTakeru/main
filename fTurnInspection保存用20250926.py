import fGeneric as gene
import pandas as pd
import classCandleAnalysis as ca
import classOrderCreate as OCreate


class turn_analisys:
    def __init__(self, candle_analysis):
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
        self.units_str = 0.1
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
        #     self.big_move_r_direction_order()
        self.cal_little_turn_at_trend()

    def add_order_and_flag_inspecion_class(self, order_class):
        """

        """
        self.take_position_flag = True
        self.exe_order_classes.append(order_class)
        # print("発行したオーダー2↓　(turn255)")
        # print(order_class.exe_order)

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

    def cal_little_turn_at_trend(self):
        """
        args[0]は必ずpeaks_classであること。
        args[1]は、本番の場合、過去の決済履歴のマイナスの大きさでTPが変わるかを検討したいため、オーダークラスを受け取る

        直近[0]がcount4の時、riverPeakにレジスタンスオーダーを入れる
        """
        # ■基本情報の取得
        print("★★TURN　本番用")

        # ■実行除外
        # 対象のPeakのサイズを確認（小さすぎる場合、除外）
        peaks = self.peaks_class.peaks_original_marked_hard_skip
        if peaks[1]['gap'] < 0.04:
            print("対象が小さい", peaks[1]['gap'])
            # return default_return_item

        # ■基本的な情報の取得
        # (1)
        r = peaks[0]
        t = peaks[1]
        f = peaks[2]
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

        # ■分岐
        print(" ●判定パラメーター一覧●  rCount:", r['count'])
        print("  平均キャンドル長", self.ca5.cal_move_ave(1))
        print("  RT情報 比率:", self.rt.lo_ratio)
        print("  TF情報 比率:", self.tf.lo_ratio)
        print("  T情報 SKIP有無:", self.rt.skip_exist_at_older, ",Skip数:", self.rt.skip_num_at_older, "t-Count:", t['count'])
        print("       T-strength:", self.rt.turn_strength_at_older)
        print("  超レンジ状態", self.peaks_class.hyper_range)
        print("  ビッグキャンドル有無", self.peaks_class.is_big_move_candle)

        # オーダーテスト用
        # ■■■BigMoveの場合は別途注意が必要
        if r['count'] == 2 and t['include_large']:
            print("BIG_MOVEテスト")
            print(t["latest_time_jp"], t['include_large'])
            self.big_move_r_direction_order()
            return 0


        # ■■Latestのピークが伸びる方向（基本形）
        comment = "None"
        if r['count'] == 2 and t['count'] >= 4:

            # ●判定セクション
            pattern = 0  # 1はトレンド（ｒ方向）、2はレンジ（ｔ方向）
            # ■■[B] リバーの戻りが、ターンに比べて小さい（当初からのルールと近しい場合）
            if self.rt.lo_ratio <= 0.3:
                # ■■■■
                if self.tf.lo_ratio <= 0.26:
                    comment = "2B_強いトレンド"
                    pattern = 1
                elif 0.26 <= self.tf.lo_ratio <= 0.45:
                    comment = "3B_ペナント型"
                    pattern = 2
                elif 0.7 <= self.tf.lo_ratio <= 1.3:
                    comment = "4B_レンジの強turnダブルトップ(r小)"
                    pattern = 2
                elif self.tf.lo_ratio > 1.45 and self.rt.lo_ratio >= 0.195 and self.rt.skip_num_at_older < 4:
                    comment = "◎◎5B_ジグザグトレンド(r短)"
                    pattern = 1
            # ■■[B] リバーの戻りが、ターンの半分前後
            elif 0.3 <= self.rt.lo_ratio <= 0.55:
                # ■■■■
                if self.tf.lo_ratio > 1.45 and self.rt.skip_num_at_older < 10:
                    comment = "◎◎5B_ジグザグトレンド(r中)"
                    pattern = 1
            # ■■[D] リバーの戻りがターンと同等のサイズ
            elif 0.8 <= self.rt.lo_ratio <= 1.1:
                # ■■■■
                if self.tf.lo_ratio <= 0.45:
                    comment = "3D_強いトレンド(r大)"
                    pattern = 1
                # ■■■■
                elif 0.7 <= self.tf.lo_ratio <= 1.3:
                    comment = "4D_レンジの強turnダブルトップ"
                    pattern = 2
                # ■■■■
                elif self.tf.lo_ratio > 1.5 and self.rt.skip_num_at_older < 4:
                    comment = "◎◎5B_ジグザグトレンド(r同等)"
                    pattern = 2
            # ■■[F] リバーが大きいとき
            elif self.rt.lo_ratio > 1.2:
                # ■■■■
                if self.tf.lo_ratio <= 0.45:
                    comment = "3F_強いジグザグトレンド"
                    pattern = 1
                # ■■■■
                elif 0.7 <= self.tf.lo_ratio <= 1.3:
                    comment = "4F_トレンド開始点"
                    pattern = 1
                # ■■■■
                elif self.tf.lo_ratio > 1.3:
                    comment = "5F_検討中"
                    pattern = 2

            # ●オーダーセクション
            if pattern == 0:
                print("オーダーなし", comment)
                return 0
            else:
                # ■オーダーがある場合
                # ■■突破方向
                if pattern == 1:
                    # ●本命オーダー
                    target_price = r['latest_body_peak_price'] + (self.sp * t['direction'])
                    order_class1 = OCreate.Order({
                        "name": comment,
                        "current_price": self.peaks_class.latest_price,
                        "target": target_price,
                        "direction": t['direction'],
                        "type": "MARKET",
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
                        "target": self.ca5.cal_move_ave(1.5),
                        "direction": r['direction'],
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

                # ■■レンジ方向
                elif pattern == 2:
                    # ●本命オーダー
                    target_price = r['latest_body_peak_price'] + (self.sp * t['direction'])
                    order_class1 = OCreate.Order({
                        "name": comment,
                        "current_price": self.peaks_class.latest_price,
                        "target": target_price,
                        "direction": r['direction'],
                        "type": "MARKET",
                        "tp": self.base_tp_range,  # self.ca5.cal_move_ave(1.5),
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
                        "target": self.ca5.cal_move_ave(1.1),  # 0.025,
                        "direction": t['direction'],
                        "type": "STOP",
                        "tp": self.base_tp_range,  # self.ca5.cal_move_ave(2.5),
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

        elif r['count'] == 3:
            if ((self.rt.skip_exist_at_older or 7 <= t['count'] < 100) and self.rt.skip_num_at_older < 3 and
                    0 < self.rt.turn_strength_at_older <= 8):
                if 0 < self.rt.lo_ratio <= 0.36:
                    # ■■オーダーを作成＆発行
                    comment = "●●●強いやつ(旧式"
                    order_class1 = OCreate.Order({
                        "name": comment,
                        "current_price": self.peaks_class.latest_price,
                        "target": 0,
                        "direction": t['direction'],
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

                    # ■■オーダーを作成＆発行
                    comment = "●●●強いやつ(旧式）逆"
                    order_class2 = OCreate.Order({
                        "name": comment,
                        "current_price": self.peaks_class.latest_price,
                        "target": self.ca5.cal_move_ave(1),
                        "direction": r['direction'],
                        "type": "STOP",
                        "tp": self.base_tp_range,  # self.ca5.cal_move_ave(5),
                        "lc": self.base_lc_range,
                        "lc_change": self.lc_change_test,
                        "units": self.units_str,
                        "priority": 4,
                        "decision_time": self.peaks_class.df_r_original.iloc[0]['time_jp'],
                        "candle_analysis_class": self.ca
                    })
                    self.add_order_and_flag_inspecion_class(order_class2)
                    # リンケージをたがいに登録する
                    order_class1.add_linkage(order_class2)
                    order_class2.add_linkage(order_class1)

                else:
                    print("戻りratio異なる", r['count'])
            else:
                pass
        else:
            print("rCountが不適切", r['count'])

    def cal_turn(self):
        """

        """


class TuneAnalysisInformation:
    def __init__(self, peaks_class, older_no, name):
        """
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
                print("　　◎リバーの方向が全部同じ（正方向）", self.second_last_close_price_later)
            elif target_peak['direction'] == -1 and latest_df['body'] < 0 and second_df['body'] < 0:
                self.is_same_direction_at_river_later = True  # リバー専用？　リバーの向きと、その直近2個のローソクの向きが同じかどうか
                self.second_last_close_price_later = second_df['close']
                print("　　　◎リバーの方向が全部同じ（負方向）", self.second_last_close_price_later)
            else:
                pass
                print("　　　NG リバー方向", target_peak['direction'], "ボディー向き", latest_df['body'], second_df['body'])

    def relation_2peaks_information(self, older_peak, later_peak):
        """
        渡された二つのピークの関係性を算出する
        unit_noが１の場合は、riverとturn。unit_noが２の場合は、turnとflop
        """
        # rt_ratio_sk = round(r_sk['gap'] / t_sk['gap'], 3)
        self.lo_ratio = round(later_peak['gap'] / older_peak['gap'], 3)
