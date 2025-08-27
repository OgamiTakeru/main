import fGeneric as gene
import pandas as pd
import classCandleAnalysis as ca
import classOrderCreate as OCreate


class turn_analisys:
    def __init__(self, candle_analysis, oa):
        self.oa = oa
        # test時と本番時で、分岐（本番ではpeaks_classが渡されるが、テストではdfが渡されるため、peaks_classに変換が必要）
        if isinstance(candle_analysis, pd.DataFrame):
            print("candle_analysisはDataFrameなのでtestと判断 ⇒ candle_analysisに変換し、格納")
            self.ca = ca.candleAnalysis(candle_analysis, oa)  # CandleAnalysisインスタンスの生成
            self.peaks_class = self.ca.peaks_class  # peaks_classだけを抽出
            test_mode = True
        else:
            print("PはDataFrameではないため、peaks_classと考える⇒返還不要")
            self.ca = candle_analysis
            self.peaks_class = self.ca.peaks_class  # peaks_classだけを抽出
            test_mode = False

        # 結果として使う大事な変数
        self.take_position_flag = False
        self.exe_orders = []
        # self.flag_and_orders = {
        #     "take_position_flag": False,
        #     "exe_orders": [],  # 本番用（本番運用では必須）
        # }

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
        # 係数の調整用
        self.lc_adj = 0.7
        self.arrow_skip = 1
        # Unit調整用
        self.units_mini = 0.1
        self.units_reg = 0.5
        self.units_str = 0.1

        # 調査実行（調査を実施し、self.flag_and_ordersの中身を埋める）
        if test_mode:
            self.cal_little_turn_at_trend_test()
        else:
            self.cal_little_turn_at_trend()

    def order_make_hedged(self, name, target_p, margin, direction, ls_type, tp, lc, lc_change, u, priority, watching):
        """
        与えられたtargetに対して、マージンを考慮し、指定の方向（STOPかLIMIT）を尊重してオーダーを生成。
        また、逆向きのオーダーも生成しておく。
        """
        # ■変数のミスをチェック
        if ls_type == "LIMIT" or ls_type == "STOP":
            pass
        else:
            print("type指定がミスってるよ:", ls_type)

        if tp >= 80:
            print("●●●　hedgedなのにTPがPrice指定されている（Range指定のみ）")
        if lc >= 80:
            print("●●●　hedgedなのにLCがPrice指定されている（Range指定のみ）")

        # ■本オーダーを生成
        # ■■エントリーポイントの算出
        if direction == 1:
            if ls_type == "LIMIT":
                # 買いの逆張り(今より低値で買い)。現在150円、ターゲット149円、1円マージンの場合、148円に下がった状態で買い。
                entry_price = target_p - margin
                if entry_price >= self.current_price:
                    print("ERROR発生の可能性　買いの逆張り(今より低値で買い)なのに、今より高い値段で買いになってる")
            else:
                # 買いの順張り(今より高値で買い)。現在150円、ターゲット151円、1円マージンの場合、152円に上がった時に買い。
                entry_price = target_p + margin
                if entry_price <= self.current_price:
                    print("ERROR発生の可能性　買いの順張り(今より高値で買い)なのに、今より低い値段で買いになってる")
        else:
            if ls_type == "LIMIT":
                # 売りの逆張り(今より高値で売り)。現在150円、ターゲット151円、1円マージンの場合、151円に上がった状態で売り。
                entry_price = target_p + margin
                if entry_price <= self.current_price:
                    print("ERROR発生の可能性　売りの逆張り(今より高値で売り)なのに、今より低い値段で売りになってる")
            else:
                # 売りの順張り(今より低値で売り)。現在150円、ターゲット149円、1円マージンの場合、148円に下がった時に売り。
                entry_price = target_p - margin
                if entry_price >= self.current_price:
                    print("ERROR発生の可能性　売りの順張り(今より低値で買い)なのに、今より高い値段で売りになってる")

        # watching
        if watching == 0:
            watching_setting = 0
        else:
            watching_setting = entry_price

        # flag形状の場合（＝Breakの場合）
        base_order_dic = {
            # targetはプラスで取得しにくい方向に。
            "oa_mode": 2,
            "target": entry_price,
            "type": ls_type,  # "STOP",
            "expected_direction": direction,
            "tp": tp,
            "lc": lc,
            'priority': 3,
            "decision_time": self.peaks_class.df_r_original.iloc[0]['time_jp'],
            "decision_price": self.peaks_class.df_r_original.iloc[1]['close'],
            "order_timeout_min": 20,
            "lc_change_type": lc_change,
            "units": self.units_str,
            "name": name,
            "watching_price": watching_setting,
            "alert": {"range": 0, "time": 0},
            "ref": {"move_ave": self.ca.cal_move_ave(1),
                    "peak1_target_gap": 0
                    }
        }
        base_order_class = OCreate.OrderCreateClass(base_order_dic)  # オーダーファイナライズ
        main_order = base_order_class.finalized_order

        # 逆向きのオーダーを生成する
        """
        逆の定義
        ①張りの基準は変更しない場合
        現在150円、ターゲット151円　マージン1円の買い順張り　⇒　現在150円、ターゲット149円、マージン1円の売り順張り
        　⇒この場合、ターゲットの変更が必要。ターゲット基本渡される（ターゲットと現在価格からの差分でみれはするが）
        ②張りを変更してしまう場合
        現在150円、ターゲット151円、マージン1円の買い順張り　⇒　現在150円、ターゲット151円、マージン1円の売り逆張り
        現在150円、ターゲット151円、マージン1円の売り逆張り　⇒　現在150円、ターゲット151円、マージン1円の買い順張り

        いったん②を採用（変更規模が少ないので）
        """
        if ls_type == "LIMIT":
            op_ls_type = "STOP"
        else:
            op_ls_type = "LIMIT"

        base_order_dic = {
            # targetはプラスで取得しにくい方向に。
            "oa_mode": 2,
            "target": entry_price,
            "type": "MARKET",  # op_ls_type,
            "expected_direction": direction * -1,
            "tp": tp * 1.5,
            "lc": lc * 1.5,
            'priority': 3,
            "decision_time": self.peaks_class.df_r_original.iloc[0]['time_jp'],
            "decision_price": self.peaks_class.df_r_original.iloc[1]['close'],
            "order_timeout_min": 20,
            "lc_change_type": lc_change,
            "units": self.units_str,
            "name": "逆" + name,
            "watching_price": watching_setting,
            "alert": {"range": 0, "time": 0},
            "ref": {"move_ave": self.ca.cal_move_ave(1),
                    "peak1_target_gap": 0
                    }
        }
        op_base_order_class = OCreate.OrderCreateClass(base_order_dic)  # オーダーファイナライズ
        op_main_order = op_base_order_class.finalized_order

        orders = [main_order, op_main_order]
        return orders

    def order_make(self, name, target_p, margin, direction, ls_type, tp, lc, lc_change, u, priority, watching):
        """
        与えられたtargetに対して、マージンを考慮し、指定の方向（STOPかLIMIT）を尊重してオーダーを生成。
        また、逆向きのオーダーも生成しておく。
        """
        # ■変数のミスをチェック
        if ls_type == "LIMIT" or ls_type == "STOP":
            pass
        else:
            print("type指定がミスってるよ:", ls_type)

        # ■本オーダーを生成
        # ■■エントリーポイントの算出
        if direction == 1:
            if ls_type == "LIMIT":
                # 買いの逆張り(今より低値で買い)。現在150円、ターゲット149円、1円マージンの場合、148円に下がった状態で買い。
                entry_price = target_p - margin
                if entry_price >= self.current_price:
                    print("ERROR発生の可能性　買いの逆張り(今より低値で買い)なのに、今より高い値段で買いになってる")
            else:
                # 買いの順張り(今より高値で買い)。現在150円、ターゲット151円、1円マージンの場合、152円に上がった時に買い。
                entry_price = target_p + margin
                if entry_price <= self.current_price:
                    print("ERROR発生の可能性　買いの順張り(今より高値で買い)なのに、今より低い値段で買いになってる")
        else:
            if ls_type == "LIMIT":
                # 売りの逆張り(今より高値で売り)。現在150円、ターゲット151円、1円マージンの場合、151円に上がった状態で売り。
                entry_price = target_p + margin
                if entry_price <= self.current_price:
                    print("ERROR発生の可能性　売りの逆張り(今より高値で売り)なのに、今より低い値段で売りになってる")
            else:
                # 売りの順張り(今より低値で売り)。現在150円、ターゲット149円、1円マージンの場合、148円に下がった時に売り。
                entry_price = target_p - margin
                if entry_price >= self.current_price:
                    print("ERROR発生の可能性　売りの順張り(今より低値で買い)なのに、今より高い値段で売りになってる")

        # watching
        if watching == 0:
            watching_setting = 0
        else:
            watching_setting = entry_price

        # flag形状の場合（＝Breakの場合）
        base_order_dic = {
            # targetはプラスで取得しにくい方向に。
            "target": entry_price,
            "type": ls_type,  # "STOP",
            "expected_direction": direction,
            "tp": tp,
            "lc": lc,
            'priority': 3,
            "decision_time": self.peaks_class.df_r_original.iloc[0]['time_jp'],
            "decision_price": self.peaks_class.df_r_original.iloc[1]['close'],
            "order_timeout_min": 20,
            "lc_change_type": lc_change,
            "units": self.units_str,
            "name": name,
            "watching_price": watching_setting,
            "alert": {"range": 0, "time": 0},
            "ref": {"move_ave": self.ca.cal_move_ave(1),
                    "peak1_target_gap": 0
                    }
        }
        base_order_class = OCreate.OrderCreateClass(base_order_dic)  # オーダーファイナライズ
        main_order = base_order_class.finalized_order
        orders = [main_order]
        return orders

    def orders_add_this_class_and_flag_on(self, orders):
        """

        """
        # self.flag_and_orders['take_position_flag'] = True
        # self.flag_and_orders['exe_orders'] = orders
        self.take_position_flag = True
        self.exe_orders.extend(orders)
        print("発行したオーダー↓")
        gene.print_arr(orders)

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

        # (4)よく使う条件分岐を、簡略化しておく
        # ■一部共通の分岐条件を生成しておく
        if self.rt.skip_num_at_older < 3 and 0 < self.rt.turn_strength_at_older <= 8:
            is_extendable_line = True
        else:
            is_extendable_line = False

        # ■分岐
        print(" ●判定パラメーター一覧●")
        print("  RT情報 比率:", self.rt.lo_ratio)
        print("  TF情報 比率:", self.tf.lo_ratio)
        print("  T情報 SKIP有無:", self.rt.skip_exist_at_older, ",Skip数:", self.rt.skip_num_at_older, "t-Count:", t['count'])
        print("       T-strength:", self.rt.turn_strength_at_older)
        print("  超レンジ状態", self.peaks_class.hyper_range)
        print("  ビッグキャンドル有無", self.peaks_class.is_big_move_candle)

        # オーダーテスト用
        # ■■Latestのピークが伸びる方向（基本形）
        exe_orders = []
        if r['count'] == 2 and t['count'] >= 4:
            # ■■Latestのピークが伸びる方向（基本形）
            comment = "ターン発生時(理想)"
            target_price = r['latest_body_peak_price'] + (self.sp * t['direction'])
            margin = 0.01  # 基本的に即時級。スプレッド分程度
            tp_range = self.ca.cal_move_ave(1.5)
            lc_price = t['latest_wick_peak_price']
            lc_range = abs(lc_price - self.current_price)
            # ■■オーダーを作成
            orders = self.order_make_hedged(
                comment,  # nameとなるcomment
                target_price,  # targetPrice
                margin,  # margin
                r['direction'],  # direction
                "STOP",  # STOP=順張り　LIMIT＝逆張り
                tp_range,  # TP hedgedはレンジ指定
                lc_range,  # LC hedgedはレンジ指定
                0,  # lcChange
                self.units_str,  # uni
                3,  # priority
                0,  # watching(0=off,1=On(watch基準はtarget(margin混み))
            )
            # ■オーダーを登録
            self.orders_add_this_class_and_flag_on(orders)

        elif r['count'] == 3:
            pass
            # if (rt.skip_exist_at_older or 7 <= t['count'] < 100) and rt.skip_num_at_older < 3 and 0 < rt.turn_strength_at_older <= 8:
            #     if 0 < rt.lo_ratio <= 0.36:
            #         if 0.8 <= fp.lo_ratio <= 1.1 and tf.lo_ratio <= 0.75:
            #             # フラッグ形状なりたて⇒突破しない方向
            #             comment = "●●●強いやつ(旧式） フラッグ版　watch対象"
            #             # ■ターゲット価格＆マージンの設定
            #             target_price = peaks_class.latest_price
            #             margin = peaks_class.cal_move_ave(0.15)  # 最強バージョン(回数は少ない＆現実は微妙）
            #             m_dir = 1
            #             # ■TPの設定
            #             tp = latest_flop_resistance_gap
            #             # ■LCの設定
            #             # パターン１（シンプルに、平均足で指定するケース)
            #             lc = peaks_class.cal_move_ave(0.8)
            #             # パターン２（ターンの移動幅の3分の2程度の距離を許容する）
            #             lc_range = round(t['gap'] / 3 * 2, 3)
            #             # ■LCChangeの設定
            #             lc_change = 3
            #
            #             # ■■オーダーを作成＆発行
            #             order = order_make_dir0_s(
            #                     peaks_class, comment, target_price, margin, m_dir,
            #                     tp,
            #                     tp,
            #                     lc_change,
            #                     units_str,
            #                     4,
            #                     lc * 0.7, 1)
            #             exe_orders.append(order)
            #         else:
            #             comment = "●●●強いやつ(旧式）　watch対象"
            #             # ■ターゲット価格＆マージンの設定
            #             target_price = peaks_class.latest_price
            #             margin = peaks_class.cal_move_ave(0.15)  # 最強バージョン(回数は少ない＆現実は微妙）
            #             m_dir = -1
            #             # ■TPの設定
            #             tp = peaks_class.cal_move_ave(5)
            #             # ■LCの設定
            #             # パターン１（シンプルに、平均足で指定するケース)
            #             lc = peaks_class.cal_move_ave(0.8)
            #             # パターン２（ターンの移動幅の3分の2程度の距離を許容する）
            #             lc_range = round(t['gap'] / 3 * 2, 3)
            #             # ■LCChangeの設定
            #             lc_change = 3
            #
            #             # ■■オーダーを作成＆発行
            #             # order = order_make_dir1_s(
            #             #         peaks_class, comment, target_price, margin, m_dir,
            #             #         tp,
            #             #         lc,
            #             #         lc_change,
            #             #         units_str,
            #             #         4,
            #             #         lc * 0.7, 1)
            #             # exe_orders.append(order)
            #             order = order_make(
            #                 peaks_class,  # peakClass
            #                 comment,  # nameとなるcomment
            #                 current_price,  # currentPrice
            #                 target_price,  # targetPrice
            #                 margin,  # margin
            #                 t['direction'],  # direction
            #                 "LIMIT",
            #                 tp,
            #                 tp,
            #                 lc_change,  # lcChange
            #                 units_str,  # unit
            #                 4,  # priority
            #                 1,  # watching(0=off,1=On(watch基準はtarget(margin混み))
            #             )
            #             exe_orders.extend(order)
            #     else:
            #         print("戻りratio異なる", r['count'])
            #         return default_return_item
            # else:
            #     return default_return_item
        else:
            print("rCountが不適切", r['count'])

    def cal_little_turn_at_trend_test(self):
        """
        args[0]は必ずpeaks_classであること。
        args[1]は、本番の場合、過去の決済履歴のマイナスの大きさでTPが変わるかを検討したいため、オーダークラスを受け取る

        直近[0]がcount4の時、riverPeakにレジスタンスオーダーを入れる
        """
        # ■基本情報の取得
        print("★★TURN　TEST")

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

        # (4)よく使う条件分岐を、簡略化しておく
        # ■一部共通の分岐条件を生成しておく
        if self.rt.skip_num_at_older < 3 and 0 < self.rt.turn_strength_at_older <= 8:
            is_extendable_line = True
        else:
            is_extendable_line = False

        # ■分岐
        print(" ●判定パラメーター一覧●")
        print("  RT情報 比率:", self.rt.lo_ratio)
        print("  TF情報 比率:", self.tf.lo_ratio)
        print("  T情報 SKIP有無:", self.rt.skip_exist_at_older, ",Skip数:", self.rt.skip_num_at_older, "t-Count:",
              t['count'])
        print("       T-strength:", self.rt.turn_strength_at_older)
        print("  超レンジ状態", self.peaks_class.hyper_range)
        print("  ビッグキャンドル有無", self.peaks_class.is_big_move_candle)

        # テスト専用のコード
        name_t = (("@" + str(self.rt.lo_ratio) + "@" +
                   str(self.rt.turn_strength_at_older)) + "@" + str(self.tf.lo_ratio) + "@" +
                  str(self.rt.skip_num_at_older) + "@" +
                  str(t['count']) + "@" + str(t['gap']))

        # オーダーテスト用
        # ■■Latestのピークが伸びる方向（基本形）
        exe_orders = []
        if r['count'] == 2 and t['count'] >= 4:
            # ■■Latestのピークが伸びる方向（基本形）
            comment = "ターン発生時(理想)" + name_t
            target_price = r['latest_body_peak_price'] + (self.sp * t['direction'])
            margin = 0.01  # 基本的に即時級。スプレッド分程度
            tp_range = self.ca.cal_move_ave(1.5)
            lc_price = t['latest_wick_peak_price']
            lc_range = abs(lc_price - self.current_price)
            # ■■オーダーを作成
            orders = self.order_make_hedged(
                comment,  # nameとなるcomment
                target_price,  # targetPrice
                margin,  # margin
                r['direction'],  # direction
                "STOP",  # STOP=順張り　LIMIT＝逆張り
                tp_range,  # TP hedgedはレンジ指定
                lc_range,  # LC hedgedはレンジ指定
                0,  # lcChange
                self.units_str,  # uni
                3,  # priority
                0,  # watching(0=off,1=On(watch基準はtarget(margin混み))
            )
            # ■オーダーを登録
            self.orders_add_this_class_and_flag_on(orders)

        elif r['count'] == 3:
            pass
            # if (rt.skip_exist_at_older or 7 <= t['count'] < 100) and rt.skip_num_at_older < 3 and 0 < rt.turn_strength_at_older <= 8:
            #     if 0 < rt.lo_ratio <= 0.36:
            #         if 0.8 <= fp.lo_ratio <= 1.1 and tf.lo_ratio <= 0.75:
            #             # フラッグ形状なりたて⇒突破しない方向
            #             comment = "●●●強いやつ(旧式） フラッグ版　watch対象"
            #             # ■ターゲット価格＆マージンの設定
            #             target_price = peaks_class.latest_price
            #             margin = peaks_class.cal_move_ave(0.15)  # 最強バージョン(回数は少ない＆現実は微妙）
            #             m_dir = 1
            #             # ■TPの設定
            #             tp = latest_flop_resistance_gap
            #             # ■LCの設定
            #             # パターン１（シンプルに、平均足で指定するケース)
            #             lc = peaks_class.cal_move_ave(0.8)
            #             # パターン２（ターンの移動幅の3分の2程度の距離を許容する）
            #             lc_range = round(t['gap'] / 3 * 2, 3)
            #             # ■LCChangeの設定
            #             lc_change = 3
            #
            #             # ■■オーダーを作成＆発行
            #             order = order_make_dir0_s(
            #                     peaks_class, comment, target_price, margin, m_dir,
            #                     tp,
            #                     tp,
            #                     lc_change,
            #                     units_str,
            #                     4,
            #                     lc * 0.7, 1)
            #             exe_orders.append(order)
            #         else:
            #             comment = "●●●強いやつ(旧式）　watch対象"
            #             # ■ターゲット価格＆マージンの設定
            #             target_price = peaks_class.latest_price
            #             margin = peaks_class.cal_move_ave(0.15)  # 最強バージョン(回数は少ない＆現実は微妙）
            #             m_dir = -1
            #             # ■TPの設定
            #             tp = peaks_class.cal_move_ave(5)
            #             # ■LCの設定
            #             # パターン１（シンプルに、平均足で指定するケース)
            #             lc = peaks_class.cal_move_ave(0.8)
            #             # パターン２（ターンの移動幅の3分の2程度の距離を許容する）
            #             lc_range = round(t['gap'] / 3 * 2, 3)
            #             # ■LCChangeの設定
            #             lc_change = 3
            #
            #             # ■■オーダーを作成＆発行
            #             # order = order_make_dir1_s(
            #             #         peaks_class, comment, target_price, margin, m_dir,
            #             #         tp,
            #             #         lc,
            #             #         lc_change,
            #             #         units_str,
            #             #         4,
            #             #         lc * 0.7, 1)
            #             # exe_orders.append(order)
            #             order = order_make(
            #                 peaks_class,  # peakClass
            #                 comment,  # nameとなるcomment
            #                 current_price,  # currentPrice
            #                 target_price,  # targetPrice
            #                 margin,  # margin
            #                 t['direction'],  # direction
            #                 "LIMIT",
            #                 tp,
            #                 tp,
            #                 lc_change,  # lcChange
            #                 units_str,  # unit
            #                 4,  # priority
            #                 1,  # watching(0=off,1=On(watch基準はtarget(margin混み))
            #             )
            #             exe_orders.extend(order)
            #     else:
            #         print("戻りratio異なる", r['count'])
            #         return default_return_item
            # else:
            #     return default_return_item
        else:
            print("rCountが不適切", r['count'])


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
                print("　　　NG リバー方向", target_peak['direction'], "ボディー向き", latest_df['body'], second_df['body'])

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


# def wrap_little_turn_inspection(peaks_class):
#     """
#     クラスをたくさん用いがケース
#     args[0]は必ずdf_rであることで、必須。
#     args[1]は、本番の場合、過去の決済履歴のマイナスの大きさでTPが変わるかを検討したいため、オーダークラスを受け取る
#     """
#     # peaksの算出
#     # peaks_class = cpk.PeaksClass(df_r)
#     #
#     flag_and_orders = {
#         "take_position_flag": False,
#         "exe_orders": [],  # 本番用（本番運用では必須）
#     }
#
#     # predict2
#     predict_result2 = cal_little_turn_at_trend(peaks_class)
#     if predict_result2['take_position_flag']:
#         flag_and_orders["take_position_flag"] = True
#         flag_and_orders["exe_orders"] = predict_result2['exe_orders']
#         # 代表プライオリティの追加
#         max_priority = max(flag_and_orders["exe_orders"], key=lambda x: x['priority'])['priority']
#         flag_and_orders['max_priority'] = max_priority
#         flag_and_orders['for_inspection_dic'] = {}
#
#         return flag_and_orders
#
#     return flag_and_orders
#
#
# def cal_little_turn_at_trend(peaks_class):
#     """
#     args[0]は必ずpeaks_classであること。
#     args[1]は、本番の場合、過去の決済履歴のマイナスの大きさでTPが変わるかを検討したいため、オーダークラスを受け取る
#
#     直近[0]がcount4の時、riverPeakにレジスタンスオーダーを入れる
#     """
#     # ■基本情報の取得
#     print("★★TURN　本番用")
#     take_position = False
#     # ■返却値の設定
#     default_return_item = {
#         "take_position_flag": take_position,
#         "for_inspection_dic": {}
#     }
#     s = "    "
#
#     # ■実行除外
#     # 対象のPeakのサイズを確認（小さすぎる場合、除外）
#     peaks = peaks_class.peaks_original_marked_hard_skip
#     if peaks[1]['gap'] < 0.04:
#         print("対象が小さい", peaks[1]['gap'])
#         # return default_return_item
#
#     # ■基本的な情報の取得
#     comment = ""
#     # (1)
#     r = peaks[0]
#     t = peaks[1]
#     f = peaks[2]
#     # (2)-1 RiverとTurnの解析（初動）
#     rt = TuneAnalysisInformation(peaks_class, 1, peaks[1], peaks[0], "rt")  # peak情報源生成
#     # (2)-2 FlopとTurnの解析（初動）
#     tf = TuneAnalysisInformation(peaks_class, 2, peaks[2], peaks[1], "tf")  # peak情報源生成
#     # (2)-3 preFlopとflopの解析（初動）
#     fp = TuneAnalysisInformation(peaks_class, 2, peaks[3], peaks[2], "fp")  # peak情報源生成
#
#     # (3) ●●よく使う値を、関数化しておく
#     # ターンが抵抗線と仮定した場合、直近価格からターンまでの価格差
#     latest_turn_resistance_gap = abs(t['latest_body_peak_price'] - peaks_class.latest_price)
#     latest_flop_resistance_gap = abs(f['latest_body_peak_price'] - peaks_class.latest_price)
#     current_price = peaks_class.latest_price
#     # いつか使うかも？LCのTPに対する倍率の一括調整用
#     lc_adj = 0.7
#     arrow_skip = 1
#     # Unit調整用
#     units_mini = 0.1
#     units_reg = 0.5
#     units_str = 0.1
#
#     # (4)●●よく使う条件分岐を、簡略化しておく
#     # ■一部共通の分岐条件を生成しておく
#     if rt.skip_num_at_older < 3 and 0 < rt.turn_strength_at_older <= 8:
#         is_extendable_line = True
#     else:
#         is_extendable_line = False
#
#     # ■分岐
#     print(" ●判定パラメーター一覧●")
#     print("  RT情報 比率:", rt.lo_ratio)
#     print("  TF情報 比率:", tf.lo_ratio)
#     print("  T情報 SKIP有無:", rt.skip_exist_at_older, ",Skip数:", rt.skip_num_at_older, "t-Count:", t['count'])
#     print("       T-strength:", rt.turn_strength_at_older)
#     print("  超レンジ状態", peaks_class.hyper_range)
#     print("  ビッグキャンドル有無", peaks_class.is_big_move_candle)
#
#     # オーダーテスト用
#     # ■■Latestのピークが伸びる方向（基本形）
#     sp = 0.004
#     target_price = peaks_class.latest_price
#     margin = sp  # 基本的に即時級。スプレッド分程度
#     tp_range = peaks_class.cal_move_ave(1)
#     lc_price = t['latest_wick_peak_price'] + (sp * t['direction'])
#
#     print("オーダーテスト用")
#     print(target_price + (r["direction"] + sp))
#     print("LC_price", lc_price)
#     print("TP_price", target_price + (r["direction"] * sp) + (r['direction']) + tp_range)
#
#     # ●●分岐詳細
#     exe_orders = []
#     if r['count'] == 2 and t['count'] >= 4:
#         # ■■Latestのピークが伸びる方向（基本形）
#         comment = "ターン発生時(理想)"
#         sp = 0.004
#         target_price = r['latest_body_peak_price']
#         margin = sp  # 基本的に即時級。スプレッド分程度
#         tp_range = peaks_class.cal_move_ave(1.5)
#         lc_price = t['latest_wick_peak_price'] + (sp * t['direction'])
#         lc_range = abs(lc_price - current_price)
#         # ■■オーダーを作成＆発行
#         order = order_make_hedged(
#             peaks_class,  # peakClass
#             comment,  # nameとなるcomment
#             current_price,  # currentPrice
#             target_price,  # targetPrice
#             margin,  # margin
#             r['direction'],  # direction
#             "STOP",  # STOP=順張り　LIMIT＝逆張り
#             tp_range,  # TP hedgedはレンジ指定
#             lc_range,  # LC hedgedはレンジ指定
#             0,  # lcChange
#             units_str,  # unit
#             3,  # priority
#             0,  # watching(0=off,1=On(watch基準はtarget(margin混み))
#         )
#         exe_orders.extend(order)
#     elif r['count'] == 3:
#         return default_return_item
#         # if (rt.skip_exist_at_older or 7 <= t['count'] < 100) and rt.skip_num_at_older < 3 and 0 < rt.turn_strength_at_older <= 8:
#         #     if 0 < rt.lo_ratio <= 0.36:
#         #         if 0.8 <= fp.lo_ratio <= 1.1 and tf.lo_ratio <= 0.75:
#         #             # フラッグ形状なりたて⇒突破しない方向
#         #             comment = "●●●強いやつ(旧式） フラッグ版　watch対象"
#         #             # ■ターゲット価格＆マージンの設定
#         #             target_price = peaks_class.latest_price
#         #             margin = peaks_class.cal_move_ave(0.15)  # 最強バージョン(回数は少ない＆現実は微妙）
#         #             m_dir = 1
#         #             # ■TPの設定
#         #             tp = latest_flop_resistance_gap
#         #             # ■LCの設定
#         #             # パターン１（シンプルに、平均足で指定するケース)
#         #             lc = peaks_class.cal_move_ave(0.8)
#         #             # パターン２（ターンの移動幅の3分の2程度の距離を許容する）
#         #             lc_range = round(t['gap'] / 3 * 2, 3)
#         #             # ■LCChangeの設定
#         #             lc_change = 3
#         #
#         #             # ■■オーダーを作成＆発行
#         #             order = order_make_dir0_s(
#         #                     peaks_class, comment, target_price, margin, m_dir,
#         #                     tp,
#         #                     tp,
#         #                     lc_change,
#         #                     units_str,
#         #                     4,
#         #                     lc * 0.7, 1)
#         #             exe_orders.append(order)
#         #         else:
#         #             comment = "●●●強いやつ(旧式）　watch対象"
#         #             # ■ターゲット価格＆マージンの設定
#         #             target_price = peaks_class.latest_price
#         #             margin = peaks_class.cal_move_ave(0.15)  # 最強バージョン(回数は少ない＆現実は微妙）
#         #             m_dir = -1
#         #             # ■TPの設定
#         #             tp = peaks_class.cal_move_ave(5)
#         #             # ■LCの設定
#         #             # パターン１（シンプルに、平均足で指定するケース)
#         #             lc = peaks_class.cal_move_ave(0.8)
#         #             # パターン２（ターンの移動幅の3分の2程度の距離を許容する）
#         #             lc_range = round(t['gap'] / 3 * 2, 3)
#         #             # ■LCChangeの設定
#         #             lc_change = 3
#         #
#         #             # ■■オーダーを作成＆発行
#         #             # order = order_make_dir1_s(
#         #             #         peaks_class, comment, target_price, margin, m_dir,
#         #             #         tp,
#         #             #         lc,
#         #             #         lc_change,
#         #             #         units_str,
#         #             #         4,
#         #             #         lc * 0.7, 1)
#         #             # exe_orders.append(order)
#         #             order = order_make(
#         #                 peaks_class,  # peakClass
#         #                 comment,  # nameとなるcomment
#         #                 current_price,  # currentPrice
#         #                 target_price,  # targetPrice
#         #                 margin,  # margin
#         #                 t['direction'],  # direction
#         #                 "LIMIT",
#         #                 tp,
#         #                 tp,
#         #                 lc_change,  # lcChange
#         #                 units_str,  # unit
#         #                 4,  # priority
#         #                 1,  # watching(0=off,1=On(watch基準はtarget(margin混み))
#         #             )
#         #             exe_orders.extend(order)
#         #     else:
#         #         print("戻りratio異なる", r['count'])
#         #         return default_return_item
#         # else:
#         #     return default_return_item
#     else:
#         print("rCountが不適切", r['count'])
#         return default_return_item
#
#     # 本番用ここまで★★
#     print("ターン解析　オーダー発行", )
#     print(comment)
#     gene.print_arr(exe_orders)
#     return {
#         "take_position_flag": True,
#         "exe_orders": exe_orders,
#         "for_inspection_dic": {}
#     }
#
# # ↓　解析テスト用（引数がdf_r)のもので、Long用解析のInspectionClassを使う際はこちらが必要
# def wrap_little_turn_inspection_test(df_r):
#     """
#     クラスをたくさん用いがケース
#     args[0]は必ずdf_rであることで、必須。
#     args[1]は、本番の場合、過去の決済履歴のマイナスの大きさでTPが変わるかを検討したいため、オーダークラスを受け取る
#     """
#     # peaksの算出
#     peaks_class = cpk.PeaksClass(df_r)
#     #
#     flag_and_orders = {
#         "take_position_flag": False,
#         "exe_orders": [],  # 本番用（本番運用では必須）
#     }
#
#     # predict2
#     predict_result2 = cal_little_turn_at_trend_test(peaks_class)
#     if predict_result2['take_position_flag']:
#         flag_and_orders["take_position_flag"] = True
#         flag_and_orders["exe_orders"] = predict_result2['exe_orders']
#         # 代表プライオリティの追加
#         max_priority = max(flag_and_orders["exe_orders"], key=lambda x: x['priority'])['priority']
#         flag_and_orders['max_priority'] = max_priority
#         flag_and_orders['for_inspection_dic'] = {}
#
#         return flag_and_orders
#
#     return flag_and_orders
#
#
# def cal_little_turn_at_trend_test(peaks_class):
#     """
#     args[0]は必ずpeaks_classであること。
#     args[1]は、本番の場合、過去の決済履歴のマイナスの大きさでTPが変わるかを検討したいため、オーダークラスを受け取る
#
#     直近[0]がcount4の時、riverPeakにレジスタンスオーダーを入れる
#     """
#     # ■基本情報の取得
#     # ■基本情報の取得
#     print("★★TURN　テスト用")
#     take_position = False
#     # ■返却値の設定
#     default_return_item = {
#         "take_position_flag": take_position,
#         "for_inspection_dic": {}
#     }
#     s = "    "
#
#     # ■実行除外
#     # 対象のPeakのサイズを確認（小さすぎる場合、除外）
#     peaks = peaks_class.peaks_original_marked_hard_skip
#     if peaks[1]['gap'] < 0.04:
#         print("対象が小さい", peaks[1]['gap'])
#         # return default_return_item
#
#     # ■基本的な情報の取得
#     comment = ""
#     # (1)
#     r = peaks[0]
#     t = peaks[1]
#     f = peaks[2]
#     # (2)-1 RiverとTurnの解析（初動）
#     rt = TuneAnalysisInformation(peaks_class, 1, peaks[1], peaks[0], "rt")  # peak情報源生成
#     # (2)-2 FlopとTurnフルの解析（初動）
#     tf = TuneAnalysisInformation(peaks_class, 2, peaks[2], peaks[1], "tf")  # peak情報源生成
#     # (2)-3 preFlopとflopの解析（初動）
#     fp = TuneAnalysisInformation(peaks_class, 2, peaks[3], peaks[2], "fp")  # peak情報源生成
#
#     # (3) ●●よく使う値を、関数化しておく
#     # ターンが抵抗線と仮定した場合、直近価格からターンまでの価格差
#     latest_turn_resistance_gap = abs(t['latest_body_peak_price'] - peaks_class.latest_price)
#     latest_flop_resistance_gap = abs(f['latest_body_peak_price'] - peaks_class.latest_price)
#     current_price = peaks_class.latest_price
#     # Unit調整用
#     units_mini = 0.1
#     units_reg = 1
#     units_str = 3.5
#     # LC調整用
#     lc_adj = 1.2
#     arrow_skip = 1
#
#
#     # ■表示用
#     print(" ●判定パラメーター一覧●")
#     print("  RT情報 比率:", rt.lo_ratio)
#     print("  TF情報 比率:", tf.lo_ratio)
#     print("  T情報 SKIP有無:", rt.skip_exist_at_older, ",Skip数:", rt.skip_num_at_older, "t-Count:", t['count'])
#     print("       T-strength:", rt.turn_strength_at_older)
#     print("  超レンジ状態", peaks_class.hyper_range)
#     print("  ビッグキャンドル有無", peaks_class.is_big_move_candle)
#
#     #  ■本分岐
#     # テスト専用のコード
#     name_t = (("@" + str(rt.lo_ratio) + "@" +
#               str(rt.turn_strength_at_older)) + "@" + str(tf.lo_ratio) + "@" + str(rt.skip_num_at_older) + "@" +
#               str(t['count']) + "@" + str(t['gap']))
#
#     # ●●よく使う条件分岐を、簡略化しておく
#     if rt.skip_num_at_older < 3 and 0 < rt.turn_strength_at_older <= 8:
#         is_extendable_line = True
#     else:
#         is_extendable_line = False
#
#     # ●●即終了の条件
#     if peaks_class.hyper_range:
#         # tk.line_send(" 超レンジのため、r_count2でもNG")
#         return default_return_item
#
#     # ●●分岐詳細
#     exe_orders = []
#     if r['count'] == 2 and t['count'] >= 4:
#         # ■■Latestのピークが伸びる方向（基本形）
#         comment = "ターン発生時(理想)" + name_t
#         sp = 0.004
#         target_price = r['latest_body_peak_price']
#         margin = sp  # 基本的に即時級。スプレッド分程度
#         tp_range = peaks_class.cal_move_ave(1.5)
#         lc_price = t['latest_wick_peak_price'] + (sp * t['direction'])
#         # ■■オーダーを作成＆発行
#         order = order_make(
#             peaks_class,  # peakClass
#             comment,  # nameとなるcomment
#             current_price,  # currentPrice
#             target_price,  # targetPrice
#             margin,  # margin
#             r['direction'],  # direction
#             "STOP",  # STOP=順張り　LIMIT＝逆張り
#             tp_range,
#             lc_price,
#             0,  # lcChange
#             units_str,  # unit
#             3,  # priority
#             0,  # watching(0=off,1=On(watch基準はtarget(margin混み))
#         )
#         exe_orders.extend(order)
#         # # テスト用
#         comment = "ターン発生時(TP=LC)" + name_t
#         sp = 0.004
#         target_price = current_price
#         margin = sp  # 基本的に即時級。スプレッド分程度
#         tp_range = peaks_class.cal_move_ave(1)
#         lc_range = peaks_class.cal_move_ave(1)
#         # ■■オーダーを作成＆発行
#         order = order_make(
#             peaks_class,  # peakClass
#             comment,  # nameとなるcomment
#             current_price,  # currentPrice
#             r['latest_body_peak_price'],  # targetPrice
#             margin,  # margin
#             r['direction'],  # direction
#             "STOP",  # STOP=順張り　LIMIT＝逆張り
#             tp_range,
#             lc_range,
#             0,  # lcChange
#             units_str,  # unit
#             3,  # priority
#             0,  # watching(0=off,1=On(watch基準はtarget(margin混み))
#         )
#         exe_orders.extend(order)
#     elif r['count'] == 3:
#         return default_return_item
#         # if (rt.skip_exist_at_older or 7 <= t['count'] < 100) and rt.skip_num_at_older < 3 and 0 < rt.turn_strength_at_older <= 8:
#         #     if 0 < rt.lo_ratio <= 0.36:
#         #         if 0.8 <= fp.lo_ratio <= 1.1 and tf.lo_ratio <= 0.75:
#         #             # フラッグ形状なりたて⇒突破しない方向
#         #             comment = "●●●強いやつ(旧式） フラッグ版　watch対象"
#         #             # ■ターゲット価格＆マージンの設定
#         #             target_price = peaks_class.latest_price
#         #             margin = peaks_class.cal_move_ave(0.15)  # 最強バージョン(回数は少ない＆現実は微妙）
#         #             m_dir = 1
#         #             # ■TPの設定
#         #             tp = latest_flop_resistance_gap
#         #             # ■LCの設定
#         #             # パターン１（シンプルに、平均足で指定するケース)
#         #             lc = peaks_class.cal_move_ave(0.8)
#         #             # パターン２（ターンの移動幅の3分の2程度の距離を許容する）
#         #             lc_range = round(t['gap'] / 3 * 2, 3)
#         #             # ■LCChangeの設定
#         #             lc_change = 3
#         #
#         #             # ■■オーダーを作成＆発行
#         #             order = order_make_dir0_s(
#         #                     peaks_class, comment, target_price, margin, m_dir,
#         #                     tp,
#         #                     tp,
#         #                     lc_change,
#         #                     units_str,
#         #                     4,
#         #                     lc * 0.7, 1)
#         #             exe_orders.append(order)
#         #         else:
#         #             comment = "●●●強いやつ(旧式）　watch対象"
#         #             # ■ターゲット価格＆マージンの設定
#         #             target_price = peaks_class.latest_price
#         #             margin = peaks_class.cal_move_ave(0.15)  # 最強バージョン(回数は少ない＆現実は微妙）
#         #             m_dir = -1
#         #             # ■TPの設定
#         #             tp = peaks_class.cal_move_ave(5)
#         #             # ■LCの設定
#         #             # パターン１（シンプルに、平均足で指定するケース)
#         #             lc = peaks_class.cal_move_ave(0.8)
#         #             # パターン２（ターンの移動幅の3分の2程度の距離を許容する）
#         #             lc_range = round(t['gap'] / 3 * 2, 3)
#         #             # ■LCChangeの設定
#         #             lc_change = 3
#         #
#         #             # ■■オーダーを作成＆発行
#         #             # order = order_make_dir1_s(
#         #             #         peaks_class, comment, target_price, margin, m_dir,
#         #             #         tp,
#         #             #         lc,
#         #             #         lc_change,
#         #             #         units_str,
#         #             #         4,
#         #             #         lc * 0.7, 1)
#         #             # exe_orders.append(order)
#         #             order = order_make(
#         #                 peaks_class,  # peakClass
#         #                 comment,  # nameとなるcomment
#         #                 current_price,  # currentPrice
#         #                 target_price,  # targetPrice
#         #                 margin,  # margin
#         #                 t['direction'],  # direction
#         #                 "LIMIT",
#         #                 tp,
#         #                 tp,
#         #                 lc_change,  # lcChange
#         #                 units_str,  # unit
#         #                 4,  # priority
#         #                 1,  # watching(0=off,1=On(watch基準はtarget(margin混み))
#         #             )
#         #             exe_orders.extend(order)
#         #     else:
#         #         print("戻りratio異なる", r['count'])
#         #         return default_return_item
#         # else:
#         #     return default_return_item
#     else:
#         print("rCountが不適切", r['count'])
#         return default_return_item
#
#     # 本番用ここまで★
#     print("ターン解析　オーダー発行")
#     print(comment)
#     gene.print_arr(exe_orders)
#     return {
#         "take_position_flag": True,
#         "exe_orders": exe_orders,
#         "for_inspection_dic": {}
#     }


# def order_make_dir0_s(peaks_class, comment, target_num, margin, margin_dir, tp, lc, lc_change, uni_base_time,
#                       priority, alert, watching):
#     """
#     基本的に[0]の方向にオーダーを出すSTOPを想定
#     target_num: オーダーの起点となるPeak.
#     margin: どれくらいのマージンを取るか
#     margin_dir: 1の場合取得しにくい方向に、－1の場合取得しやすいほうに
#     tp:TPの価格かレンジ
#     lc:lcの価格かレンジ
#     """
#     # 履歴によるオーダー調整を実施する（TPを拡大する）
#
#     # 必要項目を取得
#     peaks = peaks_class.skipped_peaks
#     order_dir = peaks[0]['direction']
#
#     for_history_class = classPosition.order_information("test", "test", False)  # 履歴参照用
#     tuned_data = for_history_class.tuning_by_history_break()
#     if tuned_data['is_previous_lose']:
#         # units = 2 * uni_base_time  # 負けてるときは倍プッシュ
#         # comment = comment + "倍プッシュ"
#         units = 1 * uni_base_time
#         # comment = comment + " [" + str(tuned_data['is_previous_lose']) + "]"
#         comment = comment + " [通常]"
#     else:
#         units = 1 * uni_base_time
#         # comment = comment + " [" + str(tuned_data['is_previous_lose']) + "]"
#         comment = comment + " [通常]"
#
#     # targetの設定
#     if target_num <= 5:
#         # target_numが、添え字とみなす場合
#         target = round(peaks[target_num]['latest_wick_peak_price'] + (margin * order_dir) * margin_dir, 3)
#     else:
#         # target_numが、添え字ではなく、直接価格を指定している場合
#         target = round(target_num + (margin * order_dir) * margin_dir * 1, 3)
#
#     # STOPオーダー専用のため、おかしな場合は、エラーを出す
#     now_price = peaks_class.latest_price
#     if order_dir == 1:
#         if target >= now_price:
#             type = "STOP"
#             print("  [1]と同じ1方向のSTOPオーダー　", order_dir, target, ">=", now_price)
#         else:
#             type = "LIMIT"
#             print("  [1]と同じ1方向のLIMITオーダー　", order_dir, target, "<", now_price)
#     else:
#         if target <= now_price:
#             type = "STOP"
#             print("  [1]と同じ-1方向のSTOPオーダー　", order_dir, target, "<=", now_price)
#         else:
#             type = "LIMIT"
#             print("  [1]と同じ-1方向のLIMITオーダー　", order_dir, target, ">", now_price)
#
#     # watching
#     if watching == 0:
#         watching_setting = 0
#     else:
#         watching_setting = target
#
#     # flag形状の場合（＝Breakの場合）
#     base_order_dic = {
#         # targetはプラスで取得しにくい方向に。
#         "target": target,
#         "type": "STOP",
#         "expected_direction": order_dir,
#         # "tp": tp_range,  # 短期では0.15でもOK.ただ長期だと、マイナスの平均が0.114のためマイナスの数が多くなる
#         # # "lc": 0.09,  # 0.06,
#         # "tp": 0.075,
#         # "lc": 0.075,
#         "tp": tp,
#         "lc": lc,
#         'priority': 3,
#         "decision_time": peaks_class.df_r_original.iloc[0]['time_jp'],
#         "decision_price": peaks_class.df_r_original.iloc[1]['close'],
#         "order_timeout_min": 20,
#         "lc_change_type": lc_change,
#         "alert": {"range": 0, "time": 0},
#         "units": units,
#         "name": comment,
#         "watching_price": watching_setting,
#         "ref": {"move_ave": peaks_class.cal_move_ave(1),
#                 "peak1_target_gap": abs(peaks[1]['latest_body_peak_price'] - target)
#                 }
#     }
#     base_order_class = OCreate.OrderCreateClass(base_order_dic)  # オーダーファイナライズ
#     # オーダーの修正と、場合によって追加オーダー設定
#     # lc_max = 0.15
#     # lc_change_after = 0.075
#     # if base_order_class.finalized_order['lc_range'] >= lc_max:
#     #     # LCレンジを計算してLCが大きすぎた場合、オーダー修正（LC短縮）
#     #     print("LCが大きいため再オーダー設定")
#     #     base_order_dic['lc'] = lc_change_after
#     #     base_order_dic['name'] = base_order_dic['name'] + "_LC大で修正_"
#     #     base_order_class = OCreate.OrderCreateClass(base_order_dic)  # オーダー生成（というか作り直し）
#     # else:
#     #     base_order_class = OCreate.OrderCreateClass(base_order_dic)
#     return base_order_class.finalized_order
#
# def order_make_dir1_s(peaks_class, comment, target_num, margin, margin_dir, tp, lc, lc_change, uni_base_time,
#                       priority, alert, watching):
#     """
#     基本的に[1]の方向にオーダーを出すSTOPオーダー
#     target_num: オーダーの起点となるPeak.
#     margin: どれくらいのマージンを取るか
#     margin_dir: 1の場合取得しにくい方向に、－1の場合取得しやすいほうに
#     tp:TPの価格かレンジ
#     lc:lcの価格かレンジ
#     """
#     # 履歴によるオーダー調整を実施する（TPを拡大する）
#
#     # 必要項目を取得
#     peaks = peaks_class.skipped_peaks
#     order_dir = peaks[1]['direction']
#
#     for_history_class = classPosition.order_information("test", "test", False)  # 履歴参照用
#     tuned_data = for_history_class.tuning_by_history_break()
#     if tuned_data['is_previous_lose']:
#         # units = 2 * uni_base_time  # 負けてるときは倍プッシュ
#         # comment = comment + "倍プッシュ"
#         units = 1 * uni_base_time
#         # comment = comment + " [" + str(tuned_data['is_previous_lose']) + "]"
#         comment = comment + " [通常]"
#     else:
#         units = 1 * uni_base_time
#         # comment = comment + " [" + str(tuned_data['is_previous_lose']) + "]"
#         comment = comment + " [通常]"
#
#     # targetの設定
#     if 0 <= target_num <= 5:
#         # target_numが、添え字とみなす場合
#         target = round(peaks[target_num]['latest_wick_peak_price'] + (margin * order_dir) * margin_dir, 3)
#     else:
#         # target_numが、添え字ではなく、直接価格を指定している場合
#         target = round(target_num + (margin * order_dir) * margin_dir * 1, 3)
#
#     # STOPオーダー専用のため、おかしな場合は、エラーを出す
#     now_price = peaks_class.latest_price
#     if order_dir == 1:
#         if target >= now_price:
#             type = "STOP"
#             print("  [1]と同じ1方向のSTOPオーダー　", order_dir, target, ">=", now_price)
#         else:
#             type = "LIMIT"
#             print("  [1]と同じ1方向のLIMITオーダー　", order_dir, target, "<", now_price)
#     else:
#         if target <= now_price:
#             type = "STOP"
#             print("  [1]と同じ-1方向のSTOPオーダー　", order_dir, target, "<=", now_price)
#         else:
#             type = "LIMIT"
#             print("  [1]と同じ-1方向のLIMITオーダー　", order_dir, target, ">", now_price)
#
#     # watching
#     if watching == 0:
#         watching_setting = 0
#     else:
#         watching_setting = target
#
#     # flag形状の場合（＝Breakの場合）
#     base_order_dic = {
#         # targetはプラスで取得しにくい方向に。
#         "target": target,
#         "type": type,  # "STOP",
#         "expected_direction": order_dir,
#         # "tp": tp_range,  # 短期では0.15でもOK.ただ長期だと、マイナスの平均が0.114のためマイナスの数が多くなる
#         # # "lc": 0.09,  # 0.06,
#         # "tp": 0.075,
#         # "lc": 0.075,
#         "tp": tp,
#         "lc": lc,
#         'priority': 3,
#         "decision_time": peaks_class.df_r_original.iloc[0]['time_jp'],
#         "decision_price": peaks_class.df_r_original.iloc[1]['close'],
#         "order_timeout_min": 20,
#         "lc_change_type": lc_change,
#         "units": units,
#         "name": comment,
#         "watching_price": watching_setting,
#         "alert": {"range": 0, "time": 0},
#         "ref": {"move_ave": peaks_class.cal_move_ave(1),
#                 "peak1_target_gap": abs(peaks[1]['latest_body_peak_price'] - target)
#                 }
#     }
#     base_order_class = OCreate.OrderCreateClass(base_order_dic)  # オーダーファイナライズ
#     # オーダーの修正と、場合によって追加オーダー設定
#     # lc_max = 0.15
#     # lc_change_after = 0.075
#     # if base_order_class.finalized_order['lc_range'] >= lc_max:
#     #     # LCレンジを計算してLCが大きすぎた場合、オーダー修正（LC短縮）
#     #     print("LCが大きいため再オーダー設定")
#     #     base_order_dic['lc'] = lc_change_after
#     #     base_order_dic['name'] = base_order_dic['name'] + "_LC大で修正_"
#     #     base_order_class = OCreate.OrderCreateClass(base_order_dic)  # オーダー生成（というか作り直し）
#     # else:
#     #     base_order_class = OCreate.OrderCreateClass(base_order_dic)
#     return base_order_class.finalized_order
#
#
# def order_make_hedged(peaks_class, name, cur_price, target_p, margin, direction, ls_type, tp, lc, lc_change, units_mag,
#                priority, watching):
#     """
#     与えられたtargetに対して、マージンを考慮し、指定の方向（STOPかLIMIT）を尊重してオーダーを生成。
#     また、逆向きのオーダーも生成しておく。
#     """
#     # ■変数のミスをチェック
#     if ls_type == "LIMIT" or ls_type == "STOP":
#         pass
#     else:
#         print("type指定がミスってるよ:", ls_type)
#
#     if tp >= 80:
#         print("●●●　hedgedなのにTPがPrice指定されている（Range指定のみ）")
#     if lc >= 80:
#         print("●●●　hedgedなのにLCがPrice指定されている（Range指定のみ）")
#
#     # ■本オーダーを生成
#     # ■■エントリーポイントの算出
#     if direction == 1:
#         if ls_type == "LIMIT":
#             # 買いの逆張り(今より低値で買い)。現在150円、ターゲット149円、1円マージンの場合、148円に下がった状態で買い。
#             entry_price = target_p - margin
#             if entry_price >= cur_price:
#                 print("ERROR発生の可能性　買いの逆張り(今より低値で買い)なのに、今より高い値段で買いになってる")
#         else:
#             # 買いの順張り(今より高値で買い)。現在150円、ターゲット151円、1円マージンの場合、152円に上がった時に買い。
#             entry_price = target_p + margin
#             if entry_price <= cur_price:
#                 print("ERROR発生の可能性　買いの順張り(今より高値で買い)なのに、今より低い値段で買いになってる")
#     else:
#         if ls_type == "LIMIT":
#             # 売りの逆張り(今より高値で売り)。現在150円、ターゲット151円、1円マージンの場合、151円に上がった状態で売り。
#             entry_price = target_p + margin
#             if entry_price <= cur_price:
#                 print("ERROR発生の可能性　売りの逆張り(今より高値で売り)なのに、今より低い値段で売りになってる")
#         else:
#             # 売りの順張り(今より低値で売り)。現在150円、ターゲット149円、1円マージンの場合、148円に下がった時に売り。
#             entry_price = target_p - margin
#             if entry_price >= cur_price:
#                 print("ERROR発生の可能性　売りの順張り(今より低値で買い)なのに、今より高い値段で売りになってる")
#
#     # watching
#     if watching == 0:
#         watching_setting = 0
#     else:
#         watching_setting = entry_price
#
#     # flag形状の場合（＝Breakの場合）
#     base_order_dic = {
#         # targetはプラスで取得しにくい方向に。
#         "oa_mode": 2,
#         "target": entry_price,
#         "type": ls_type,  # "STOP",
#         "expected_direction": direction,
#         "tp": tp,
#         "lc": lc,
#         'priority': 3,
#         "decision_time": peaks_class.df_r_original.iloc[0]['time_jp'],
#         "decision_price": peaks_class.df_r_original.iloc[1]['close'],
#         "order_timeout_min": 20,
#         "lc_change_type": lc_change,
#         "units": units_mag,
#         "name": name,
#         "watching_price": watching_setting,
#         "alert": {"range": 0, "time": 0},
#         "ref": {"move_ave": peaks_class.cal_move_ave(1),
#                 "peak1_target_gap": 0
#                 }
#     }
#     base_order_class = OCreate.OrderCreateClass(base_order_dic)  # オーダーファイナライズ
#     main_order = base_order_class.finalized_order
#
#     # 逆向きのオーダーを生成する
#     """
#     逆の定義
#     ①張りの基準は変更しない場合
#     現在150円、ターゲット151円　マージン1円の買い順張り　⇒　現在150円、ターゲット149円、マージン1円の売り順張り
#     　⇒この場合、ターゲットの変更が必要。ターゲット基本渡される（ターゲットと現在価格からの差分でみれはするが）
#     ②張りを変更してしまう場合
#     現在150円、ターゲット151円、マージン1円の買い順張り　⇒　現在150円、ターゲット151円、マージン1円の売り逆張り
#     現在150円、ターゲット151円、マージン1円の売り逆張り　⇒　現在150円、ターゲット151円、マージン1円の買い順張り
#
#     いったん②を採用（変更規模が少ないので）
#     """
#     if ls_type == "LIMIT":
#         op_ls_type = "STOP"
#     else:
#         op_ls_type = "LIMIT"
#
#     base_order_dic = {
#         # targetはプラスで取得しにくい方向に。
#         "oa_mode": 2,
#         "target": entry_price,
#         "type": "MARKET",  #op_ls_type,
#         "expected_direction": direction * -1,
#         "tp": tp * 1.5,
#         "lc": lc * 1.5,
#         'priority': 3,
#         "decision_time": peaks_class.df_r_original.iloc[0]['time_jp'],
#         "decision_price": peaks_class.df_r_original.iloc[1]['close'],
#         "order_timeout_min": 20,
#         "lc_change_type": lc_change,
#         "units": units_mag,
#         "name": "逆" + name,
#         "watching_price": watching_setting,
#         "alert": {"range": 0, "time": 0},
#         "ref": {"move_ave": peaks_class.cal_move_ave(1),
#                 "peak1_target_gap": 0
#                 }
#     }
#     op_base_order_class = OCreate.OrderCreateClass(base_order_dic)  # オーダーファイナライズ
#     op_main_order = op_base_order_class.finalized_order
#
#     orders = [main_order, op_main_order]
#     return orders
#
#
# def order_make(peaks_class, name, cur_price, target_p, margin, direction, ls_type, tp, lc, lc_change, units_mag, priority, watching):
#     """
#     与えられたtargetに対して、マージンを考慮し、指定の方向（STOPかLIMIT）を尊重してオーダーを生成。
#     また、逆向きのオーダーも生成しておく。
#     """
#     # ■変数のミスをチェック
#     if ls_type == "LIMIT" or ls_type == "STOP":
#         pass
#     else:
#         print("type指定がミスってるよ:", ls_type)
#
#     # ■本オーダーを生成
#     # ■■エントリーポイントの算出
#     if direction == 1:
#         if ls_type == "LIMIT":
#             # 買いの逆張り(今より低値で買い)。現在150円、ターゲット149円、1円マージンの場合、148円に下がった状態で買い。
#             entry_price = target_p - margin
#             if entry_price >= cur_price:
#                 print("ERROR発生の可能性　買いの逆張り(今より低値で買い)なのに、今より高い値段で買いになってる")
#         else:
#             # 買いの順張り(今より高値で買い)。現在150円、ターゲット151円、1円マージンの場合、152円に上がった時に買い。
#             entry_price = target_p + margin
#             if entry_price <= cur_price:
#                 print("ERROR発生の可能性　買いの順張り(今より高値で買い)なのに、今より低い値段で買いになってる")
#     else:
#         if ls_type == "LIMIT":
#             # 売りの逆張り(今より高値で売り)。現在150円、ターゲット151円、1円マージンの場合、151円に上がった状態で売り。
#             entry_price = target_p + margin
#             if entry_price <= cur_price:
#                 print("ERROR発生の可能性　売りの逆張り(今より高値で売り)なのに、今より低い値段で売りになってる")
#         else:
#             # 売りの順張り(今より低値で売り)。現在150円、ターゲット149円、1円マージンの場合、148円に下がった時に売り。
#             entry_price = target_p - margin
#             if entry_price >= cur_price:
#                 print("ERROR発生の可能性　売りの順張り(今より低値で買い)なのに、今より高い値段で売りになってる")
#
#     # watching
#     if watching == 0:
#         watching_setting = 0
#     else:
#         watching_setting = entry_price
#
#     # flag形状の場合（＝Breakの場合）
#     base_order_dic = {
#         # targetはプラスで取得しにくい方向に。
#         "target": entry_price,
#         "type": ls_type,  # "STOP",
#         "expected_direction": direction,
#         "tp": tp,
#         "lc": lc,
#         'priority': 3,
#         "decision_time": peaks_class.df_r_original.iloc[0]['time_jp'],
#         "decision_price": peaks_class.df_r_original.iloc[1]['close'],
#         "order_timeout_min": 20,
#         "lc_change_type": lc_change,
#         "units": units_mag,
#         "name": name,
#         "watching_price": watching_setting,
#         "alert": {"range": 0, "time": 0},
#         "ref": {"move_ave": peaks_class.cal_move_ave(1),
#                 "peak1_target_gap": 0
#                 }
#     }
#     base_order_class = OCreate.OrderCreateClass(base_order_dic)  # オーダーファイナライズ
#     main_order = base_order_class.finalized_order
#
#     # 逆向きのオーダーを生成する
#     """
#     逆の定義
#     ①張りの基準は変更しない場合
#     現在150円、ターゲット151円　マージン1円の買い順張り　⇒　現在150円、ターゲット149円、マージン1円の売り順張り
#     　⇒この場合、ターゲットの変更が必要。ターゲット基本渡される（ターゲットと現在価格からの差分でみれはするが）
#     ②張りを変更してしまう場合
#     現在150円、ターゲット151円、マージン1円の買い順張り　⇒　現在150円、ターゲット151円、マージン1円の売り逆張り
#     現在150円、ターゲット151円、マージン1円の売り逆張り　⇒　現在150円、ターゲット151円、マージン1円の買い順張り
#
#     いったん②を採用（変更規模が少ないので）
#     """
#     if ls_type == "LIMIT":
#         op_ls_type = "STOP"
#     else:
#         op_ls_type = "LIMIT"
#
#     base_order_dic = {
#         # targetはプラスで取得しにくい方向に。
#         "target": entry_price,
#         "type": op_ls_type,
#         "expected_direction": direction * -1,
#         "tp": tp,
#         "lc": lc,
#         'priority': 3,
#         "decision_time": peaks_class.df_r_original.iloc[0]['time_jp'],
#         "decision_price": peaks_class.df_r_original.iloc[1]['close'],
#         "order_timeout_min": 20,
#         "lc_change_type": lc_change,
#         "units": units_mag,
#         "name": "逆" + name,
#         "watching_price": watching_setting,
#         "alert": {"range": 0, "time": 0},
#         "ref": {"move_ave": peaks_class.cal_move_ave(1),
#                 "peak1_target_gap": 0
#                 }
#     }
#     op_base_order_class = OCreate.OrderCreateClass(base_order_dic)  # オーダーファイナライズ
#     op_main_order = op_base_order_class.finalized_order
#
#     orders = [main_order, op_main_order]
#     return orders
#

# def cal_little_turn_at_trend(peaks_class):
#     """
#     args[0]は必ずpeaks_classであること。
#     args[1]は、本番の場合、過去の決済履歴のマイナスの大きさでTPが変わるかを検討したいため、オーダークラスを受け取る
#
#     直近[0]がcount4の時、riverPeakにレジスタンスオーダーを入れる
#     """
#     # ■基本情報の取得
#     print("★★TURN　本番用")
#     take_position = False
#     # ■返却値の設定
#     default_return_item = {
#         "take_position_flag": take_position,
#         "for_inspection_dic": {}
#     }
#     s = "    "
#
#     # ■実行除外
#     # 対象のPeakのサイズを確認（小さすぎる場合、除外）
#     peaks = peaks_class.peaks_original_marked_hard_skip
#     if peaks[1]['gap'] < 0.04:
#         print("対象が小さい", peaks[1]['gap'])
#         # return default_return_item
#
#     # ■基本的な情報の取得
#     comment = ""
#     # (1)
#     r = peaks[0]
#     t = peaks[1]
#     f = peaks[2]
#     # (2)-1 RiverとTurnの解析（初動）
#     rt = TuneAnalysisInformation(peaks_class, 1, peaks[1], peaks[0], "rt")  # peak情報源生成
#     # (2)-2 FlopとTurnの解析（初動）
#     tf = TuneAnalysisInformation(peaks_class, 2, peaks[2], peaks[1], "tf")  # peak情報源生成
#     # (2)-3 preFlopとflopの解析（初動）
#     fp = TuneAnalysisInformation(peaks_class, 2, peaks[3], peaks[2], "fp")  # peak情報源生成
#
#     # (3) ●●よく使う値を、関数化しておく
#     # ターンが抵抗線と仮定した場合、直近価格からターンまでの価格差
#     latest_turn_resistance_gap = abs(t['latest_body_peak_price'] - peaks_class.latest_price)
#     latest_flop_resistance_gap = abs(f['latest_body_peak_price'] - peaks_class.latest_price)
#     current_price = peaks_class.latest_price
#     # いつか使うかも？LCのTPに対する倍率の一括調整用
#     lc_adj = 0.7
#     arrow_skip = 1
#     # Unit調整用
#     units_mini = 0.1
#     units_reg = 0.5
#     units_str = 0.5
#
#     # (4)●●よく使う条件分岐を、簡略化しておく
#     # ■一部共通の分岐条件を生成しておく
#     if rt.skip_num_at_older < 3 and 0 < rt.turn_strength_at_older <= 8:
#         is_extendable_line = True
#     else:
#         is_extendable_line = False
#
#     # ■分岐
#     print(" ●判定パラメーター一覧●")
#     print("  RT情報 比率:", rt.lo_ratio)
#     print("  TF情報 比率:", tf.lo_ratio)
#     print("  T情報 SKIP有無:", rt.skip_exist_at_older, ",Skip数:", rt.skip_num_at_older, "t-Count:", t['count'])
#     print("       T-strength:", rt.turn_strength_at_older)
#     print("  超レンジ状態", peaks_class.hyper_range)
#     print("  ビッグキャンドル有無", peaks_class.is_big_move_candle)
#
#     # オーダーテスト用
#     # ■■Latestのピークが伸びる方向（基本形）
#     sp = 0.004
#     target_price = peaks_class.latest_price
#     margin = sp  # 基本的に即時級。スプレッド分程度
#     tp_range = peaks_class.cal_move_ave(1)
#     lc_price = t['latest_wick_peak_price'] + (sp * t['direction'])
#
#     print("オーダーテスト用")
#     print(target_price + (r["direction"] + sp))
#     print("LC_price", lc_price)
#     print("TP_price", target_price + (r["direction"] * sp) + (r['direction']) + tp_range)
#
#     exe_orders = []
#     if r['count'] == 2:
#         # 超レンジのためスキップ
#         if peaks_class.hyper_range:
#             tk.line_send(" 超レンジのため、r_count2でもNG")
#             return default_return_item
#
#         # ■■[B] リバーの戻りが、ターンに比べて小さい（当初からのルールと近しい場合）
#         if rt.lo_ratio <= 0.3:
#             # ■■■■
#             if tf.lo_ratio <= 0.26:
#                 comment = "2B_強いトレンド"
#                 # ●TARGET
#                 target_price = peaks_class.latest_price
#                 # ●MARGIN
#                 margin = 0.01
#                 # ●TP価格の算出
#                 tp_range = t['gap']  # ターンのギャップ程度はいけるのでは？ (lcとの比率は、簡単に出せる）
#                 # ●LC_Change
#                 trg = latest_flop_resistance_gap * 1.1
#                 ens = latest_flop_resistance_gap * 0.9
#                 lc_change = [
#                     {"exe": True, "time_after": 200, "trigger": trg, "ensure": ens, "time_till": 10000},
#                 ]
#                 order = order_make_dir0_s(  # memo dir1関数で逆張りしたい場合、marginDirは-1に振る。
#                     peaks_class, comment,  # クラスやコメント
#                     target_price,  # target_price
#                     margin, 1,  # margin とその方向
#                     tp_range,  # TP
#                     tp_range * lc_adj,  # LC
#                     lc_change,  # LCChange
#                     units_mini,  # units
#                     2,  # priority
#                     peaks_class.cal_move_ave(0.7),  # alert
#                     0  # watching(0はwatch無し）
#                 )
#                 order['order_timeout_min'] = 5  # 5分でオーダー消去（すぐに越えてない場合はもうNGとみなす。最大10分か？）
#                 exe_orders.append(order)
#             # ■■■■
#             elif 0.26 <= tf.lo_ratio <= 0.45:
#                 comment = "3B_ペナント型"
#                 # ●TARGET
#                 target_price = peaks_class.latest_price
#                 # ●MARGIN
#                 margin = 0.007
#                 # ●TP価格の算出
#                 tp_range = t['gap']  # ターンのギャップ程度はいけるのでは？ (lcとの比率は、簡単に出せる）
#                 order = order_make_dir0_s(  # memo dir1関数で逆張りしたい場合、marginDirは-1に振る。
#                     peaks_class, comment, target_price, margin, -1,
#                     latest_flop_resistance_gap,
#                     latest_flop_resistance_gap * lc_adj,
#                     0,
#                     units_mini,
#                     2,
#                     peaks_class.cal_move_ave(0.7),
#                     0)
#                 order['order_timeout_min'] = 5  # 5分でオーダー消去（すぐに越えてない場合はもうNGとみなす。最大10分か？）
#                 exe_orders.append(order)
#             # ■■■■
#             elif 0.7 <= tf.lo_ratio <= 1.3:
#                 comment = "4B_レンジの強turnダブルトップ(r小)"
#                 return default_return_item
#                 # TARGET
#                 target_price = peaks_class.latest_price
#                 # MARGIN
#                 margin = 0.007
#                 # TP
#                 tp_price = f['latest_body_peak_price']  # Flopまで
#                 # LC
#                 lc_range = peaks_class.cal_move_ave(1.1)
#                 # LC_CHANGE
#                 trigger_gap = latest_flop_resistance_gap * 0.7
#                 ensure = latest_flop_resistance_gap * 0.2
#                 lc_change = [
#                     {"exe": True, "time_after": 200, "trigger": trigger_gap, "ensure": ensure, "time_till": 10000},
#                 ]
#                 order = order_make_dir0_s(
#                     peaks_class, comment, target_price, margin, 1,
#                     tp_price,
#                     lc_range,
#                     1,
#                     units_mini,
#                     2,
#                     peaks_class.cal_move_ave(0.7),
#                     0
#                 )
#                 order['order_timeout_min'] = 5  # 5分でオーダー消去（すぐに越えてない場合はもうNGとみなす。最大10分か？）
#                 exe_orders.append(order)
#             # ■■■■
#             elif tf.lo_ratio > 1.45 and rt.lo_ratio >= 0.195 and rt.skip_num_at_older <= arrow_skip:
#                 comment = "◎◎5B_ジグザグトレンド(r短)"
#                 # TARGET
#                 target_price = peaks_class.latest_price
#                 # MARGIN
#                 margin = 0.02  # 旧調子のいいとき0.02
#                 # ■TP価格の算出
#                 tp_range = t['gap']  # ターンのギャップ程度はいけるのでは？ (lcとの比率は、簡単に出せる）
#                 order = order_make_dir1_s(  # memo dir1関数で逆張りしたい場合、marginDirは-1に振る。
#                     peaks_class, comment, target_price, margin, 1,  # 旧調子のいいとき marginDir1(おかしい？）
#                     tp_range,
#                     tp_range * lc_adj,
#                     1,
#                     units_reg,
#                     2,
#                     peaks_class.cal_move_ave(0.7),
#                     1)
#                 order['order_timeout_min'] = 15  # 5分でオーダー消去（すぐに越えてない場合はもうNGとみなす。最大10分か？）
#                 # order['watching_price'] = 0
#                 exe_orders.append(order)
#             else:
#                 return default_return_item
#
#         # ■■[B] リバーの戻りが、ターンの半分前後
#         elif 0.3 <= rt.lo_ratio <= 0.55:
#             # ■■■■
#             if tf.lo_ratio > 1.45 and rt.skip_num_at_older <= arrow_skip:
#                 comment = "◎◎5B_ジグザグトレンド(r中)"
#                 # TARGET
#                 target_price = peaks_class.latest_price
#                 # MARGIN
#                 margin = peaks_class.cal_move_ave(1)  # 旧調子のいいとき0.02
#                 # ■TP価格の算出
#                 tp_range = t['gap']  # ターンのギャップ程度はいけるのでは？ (lcとの比率は、簡単に出せる）
#                 order = order_make_dir1_s(  # memo dir1関数で逆張りしたい場合、marginDirは-1に振る。
#                     peaks_class, comment, target_price, margin, 1,  # 旧調子のいいとき marginDir1(おかしい？）
#                     tp_range,
#                     tp_range * lc_adj,
#                     1,
#                     units_reg,
#                     2,
#                     peaks_class.cal_move_ave(0.7),
#                     1)
#                 order['order_timeout_min'] = 15  # 5分でオーダー消去（すぐに越えてない場合はもうNGとみなす。最大10分か？）
#                 # order['watching_price'] = 0
#                 exe_orders.append(order)
#             else:
#                 return default_return_item
#
#         # ■■[D] リバーの戻りがターンと同等のサイズ
#         elif 0.8 <= rt.lo_ratio <= 1.1:
#             # ■■■■
#             if tf.lo_ratio <= 0.45:
#                 comment = "3D_強いトレンド(r大)"
#                 # ●TARGET
#                 target_price = peaks_class.latest_price
#                 # ●MARGIN
#                 margin = 0.01
#                 # ●TP価格の算出
#                 tp_range = t['gap']  # ターンのギャップ程度はいけるのでは？ (lcとの比率は、簡単に出せる）
#                 # ●LC_Change
#                 lc_change = 3
#                 order = order_make_dir0_s(  # memo dir1関数で逆張りしたい場合、marginDirは-1に振る。
#                     peaks_class, comment, target_price, margin, 1,
#                     tp_range,
#                     tp_range * lc_adj,
#                     lc_change,
#                     units_mini,
#                     2,
#                     peaks_class.cal_move_ave(0.7),
#                     0)
#                 order['order_timeout_min'] = 5  # 5分でオーダー消去（すぐに越えてない場合はもうNGとみなす。最大10分か？）
#                 exe_orders.append(order)
#             # ■■■■
#             elif 0.7 <= tf.lo_ratio <= 1.3:
#                 comment = "4D_レンジの強turnダブルトップ"
#                 # TARGET
#                 target_price = peaks_class.latest_price
#                 # MARGIN
#                 margin = 0.01
#                 order = order_make_dir1_s(  # memo dir1関数で逆張りしたい場合、marginDirは-1に振る。
#                     peaks_class, comment, target_price, margin, -1,
#                     peaks_class.cal_move_ave(1.2),
#                     peaks_class.cal_move_ave(1.2) * lc_adj,
#                     1,
#                     units_mini,
#                     2,
#                     peaks_class.cal_move_ave(0.7),1)
#                 order['order_timeout_min'] = 5  # 5分でオーダー消去（すぐに越えてない場合はもうNGとみなす。最大10分か？）
#                 # order['watching_price'] = 0
#                 exe_orders.append(order)
#             # ■■■■
#             elif tf.lo_ratio > 1.5 and rt.skip_num_at_older <= arrow_skip:
#                 comment = "◎◎5B_ジグザグトレンド(r同等)⇒逆で試し中"
#                 # TARGET
#                 target_price = peaks_class.latest_price
#                 # MARGIN
#                 margin = 0.01  # 旧調子のいいとき0.02
#                 # ■TP価格の算出
#                 tp_range = t['gap']  # ターンのギャップ程度はいけるのでは？ (lcとの比率は、簡単に出せる）
#                 order = order_make_dir0_s(  # memo dir1関数で逆張りしたい場合、marginDirは-1に振る。
#                     peaks_class, comment, target_price, margin, 1,  # 旧調子のいいとき marginDir1(おかしい？）
#                     latest_flop_resistance_gap,
#                     latest_flop_resistance_gap * lc_adj,
#                     1,
#                     units_mini,
#                     2,
#                     peaks_class.cal_move_ave(0.7),
#                     1)
#                 order['order_timeout_min'] = 15  # 5分でオーダー消去（すぐに越えてない場合はもうNGとみなす。最大10分か？）
#                 # order['watching_price'] = 0
#                 exe_orders.append(order)
#             else:
#                 return default_return_item
#
#         # ■■[F] リバーが大きいとき
#         elif rt.lo_ratio > 1.2:
#             # ■■■■
#             if tf.lo_ratio <= 0.45:
#                 return default_return_item
#                 comment = "3F_強いジグザグトレンド"
#                 # ●TARGET
#                 target_price = peaks_class.latest_price
#                 # ●MARGIN
#                 margin = 0.01
#                 # ●TP価格の算出
#                 tp_range = peaks_class.cal_move_ave(1.5)
#                 # ●LC_Change
#                 # trg = latest_flop_resistance_gap * 1.1
#                 # ens = latest_flop_resistance_gap * 0.9
#                 # lc_change = [
#                 #     {"exe": True, "time_after": 200, "trigger": trg, "ensure": ens, "time_till": 10000},
#                 # ]
#                 order = order_make_dir0_s(  # memo dir1関数で逆張りしたい場合、marginDirは-1に振る。
#                     peaks_class, comment, target_price, margin, 1,
#                     tp_range,
#                     tp_range * lc_adj,
#                     3,
#                     units_mini,
#                     2,
#                     peaks_class.cal_move_ave(0.7),
#                     0)
#                 order['order_timeout_min'] = 5  # 5分でオーダー消去（すぐに越えてない場合はもうNGとみなす。最大10分か？）
#                 exe_orders.append(order)
#             # ■■■■
#             elif 0.7 <= tf.lo_ratio <= 1.3:
#                 return default_return_item
#                 comment = "4F_トレンド開始点"
#                 # ●TARGET
#                 target_price = peaks_class.latest_price
#                 # ●MARGIN
#                 margin = 0.01
#                 # ●TP価格の算出
#                 tp_range = peaks_class.cal_move_ave(1.5)
#                 # ●LC_Change
#                 # trg = latest_flop_resistance_gap * 1.1
#                 # ens = latest_flop_resistance_gap * 0.9
#                 # lc_change = [
#                 #     {"exe": True, "time_after": 200, "trigger": trg, "ensure": ens, "time_till": 10000},
#                 # ]
#                 order = order_make_dir0_s(  # memo dir1関数で逆張りしたい場合、marginDirは-1に振る。
#                     peaks_class, comment, target_price, margin, 1,
#                     tp_range,
#                     tp_range * lc_adj,
#                     3,
#                     units_mini,
#                     2,
#                     peaks_class.cal_move_ave(0.7),
#                     0)
#                 order['order_timeout_min'] = 5  # 5分でオーダー消去（すぐに越えてない場合はもうNGとみなす。最大10分か？）
#                 exe_orders.append(order)
#             # ■■■■
#             elif tf.lo_ratio > 1.3:
#                 comment = "5F_検討中"
#                 # ●TARGET
#                 target_price = peaks_class.latest_price
#                 # ●MARGIN
#                 margin = 0.01
#                 # ●TP価格の算出
#                 tp_range = peaks_class.cal_move_ave(1.5)
#                 # ●LC_Change
#                 # trg = latest_flop_resistance_gap * 1.1
#                 # ens = latest_flop_resistance_gap * 0.9
#                 # lc_change = [
#                 #     {"exe": True, "time_after": 200, "trigger": trg, "ensure": ens, "time_till": 10000},
#                 # ]
#                 order = order_make_dir0_s(  # memo dir1関数で逆張りしたい場合、marginDirは-1に振る。
#                     peaks_class, comment, target_price, margin, 1,
#                     tp_range,
#                     tp_range * lc_adj,
#                     3,
#                     units_mini,
#                     2,
#                     peaks_class.cal_move_ave(0.7),
#                     0)
#                 order['order_timeout_min'] = 5  # 5分でオーダー消去（すぐに越えてない場合はもうNGとみなす。最大10分か？）
#                 exe_orders.append(order)
#             else:
#                 return default_return_item
#         else:
#             print("戻りratio異なる", r['count'])
#             return default_return_item
#     elif r['count'] == 3:
#         if (rt.skip_exist_at_older or 7 <= t['count'] < 100) and rt.skip_num_at_older < 3 and 0 < rt.turn_strength_at_older <= 8:
#             if 0 < rt.lo_ratio <= 0.36:
#                 if 0.8 <= fp.lo_ratio <= 1.1 and tf.lo_ratio <= 0.75:
#                     # フラッグ形状なりたて⇒突破しない方向
#                     comment = "●●●強いやつ(旧式） フラッグ版　watch対象"
#                     # ■ターゲット価格＆マージンの設定
#                     target_price = peaks_class.latest_price
#                     margin = peaks_class.cal_move_ave(0.15)  # 最強バージョン(回数は少ない＆現実は微妙）
#                     m_dir = 1
#                     # ■TPの設定
#                     tp = latest_flop_resistance_gap
#                     # ■LCの設定
#                     # パターン１（シンプルに、平均足で指定するケース)
#                     lc = peaks_class.cal_move_ave(0.8)
#                     # パターン２（ターンの移動幅の3分の2程度の距離を許容する）
#                     lc_range = round(t['gap'] / 3 * 2, 3)
#                     # ■LCChangeの設定
#                     lc_change = 3
#
#                     # ■■オーダーを作成＆発行
#                     order = order_make_dir1_s(
#                             peaks_class, comment, target_price, margin, m_dir,
#                             tp,
#                             tp,
#                             lc_change,
#                             units_str,
#                             4,
#                             lc * 0.7, 1)
#                     exe_orders.append(order)
#                 else:
#                     comment = "●●●強いやつ(旧式）　watch対象"
#                     # ■ターゲット価格＆マージンの設定
#                     target_price = peaks_class.latest_price
#                     margin = peaks_class.cal_move_ave(0.15)  # 最強バージョン(回数は少ない＆現実は微妙）
#                     m_dir = -1
#                     # ■TPの設定
#                     tp = peaks_class.cal_move_ave(5)
#                     # ■LCの設定
#                     # パターン１（シンプルに、平均足で指定するケース)
#                     lc = peaks_class.cal_move_ave(0.8)
#                     # パターン２（ターンの移動幅の3分の2程度の距離を許容する）
#                     lc_range = round(t['gap'] / 3 * 2, 3)
#                     # ■LCChangeの設定
#                     lc_change = 3
#
#                     # ■■オーダーを作成＆発行
#                     order = order_make_dir1_s(
#                             peaks_class, comment, target_price, margin, m_dir,
#                             tp,
#                             lc,
#                             lc_change,
#                             units_str,
#                             4,
#                             lc * 0.7, 1)
#                     exe_orders.append(order)
#             else:
#                 print("戻りratio異なる", r['count'])
#                 return default_return_item
#         else:
#             return default_return_item
#     else:
#         print("rCountが不適切", r['count'])
#         return default_return_item
#
#     # 本番用ここまで★★
#     print("ターン解析　オーダー発行", )
#     print(comment)
#     gene.print_arr(exe_orders)
#     return {
#         "take_position_flag": True,
#         "exe_orders": exe_orders,
#         "for_inspection_dic": {}
#     }