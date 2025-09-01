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
            "direction": direction,
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
            "direction": direction * -1,
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
        if ls_type == "LIMIT" or ls_type == "STOP" or "MARKET":
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
            "direction": direction,
            "tp": tp,
            "lc": lc,
            'priority': 3,
            "decision_time": self.peaks_class.df_r_original.iloc[0]['time_jp'],
            "decision_price": self.peaks_class.df_r_original.iloc[1]['close'],
            "order_timeout_min": 20,
            "trade_timeout_min": 240,
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
        print("発行したオーダー↓　(turn255)")
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
        print(" ●判定パラメーター一覧●  rCOunt:", r['count'])
        print("  RT情報 比率:", self.rt.lo_ratio)
        print("  TF情報 比率:", self.tf.lo_ratio)
        print("  T情報 SKIP有無:", self.rt.skip_exist_at_older, ",Skip数:", self.rt.skip_num_at_older, "t-Count:", t['count'])
        print("       T-strength:", self.rt.turn_strength_at_older)
        print("  超レンジ状態", self.peaks_class.hyper_range)
        print("  ビッグキャンドル有無", self.peaks_class.is_big_move_candle)

        # オーダーテスト用
        # ■■Latestのピークが伸びる方向（基本形）
        exe_orders = []
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
                    margin = 0.01  # 基本的に即時級。スプレッド分程度
                    tp_range = self.ca.cal_move_ave(1.5)
                    lc_price = t['latest_wick_peak_price']
                    lc_range = abs(lc_price - self.current_price)
                    orders_r = self.order_make(
                        comment,  # nameとなるcomment
                        target_price,  # targetPrice
                        margin,  # margin
                        r['direction'],  # direction
                        "MARKET",  # STOP=順張り　LIMIT＝逆張り
                        self.ca.cal_move_ave(5),  # TP hedgedはレンジ指定
                        1,  # LC hedgedはレンジ指定
                        1,  # lcChange  1 =defence
                        self.units_str,  # uni
                        3,  # priority
                        0,  # watching(0=off,1=On(watch基準はtarget(margin混み))
                    )
                    self.orders_add_this_class_and_flag_on(orders_r)

                    # ●ヘッジオーダー
                    target_price = r['latest_body_peak_price'] + (self.sp * t['direction'])
                    margin = self.ca.cal_move_ave(1.5)  # 基本的に即時級。スプレッド分程度
                    tp_range = self.ca.cal_move_ave(1.5)
                    lc_price = t['latest_wick_peak_price']
                    lc_range = abs(lc_price - self.current_price)
                    orders_r = self.order_make(
                        comment + "HEDGE",  # nameとなるcomment
                        target_price,  # targetPrice
                        margin,  # margin
                        t['direction'],  # direction
                        "STOP",  # STOP=順張り　LIMIT＝逆張り
                        1,  # TP hedgedはレンジ指定
                        1,  # LC hedgedはレンジ指定
                        1,  # lcChange  1 =defence
                        self.units_str,  # uni
                        3,  # priority
                        0,  # watching(0=off,1=On(watch基準はtarget(margin混み))
                    )
                    self.orders_add_this_class_and_flag_on(orders_r)

                # ■■レンジ方向
                elif pattern == 2:
                    # ●本命オーダー
                    target_price = r['latest_body_peak_price'] + (self.sp * t['direction'])
                    margin = 0.01  # 基本的に即時級。スプレッド分程度
                    tp_range = self.ca.cal_move_ave(1.5)
                    lc_price = t['latest_wick_peak_price']
                    lc_range = abs(lc_price - self.current_price)
                    orders_r = self.order_make(
                        comment,  # nameとなるcomment
                        target_price,  # targetPrice
                        margin,  # margin
                        t['direction'],  # direction
                        "MARKET",  # STOP=順張り　LIMIT＝逆張り
                        self.ca.cal_move_ave(1.5),  # TP hedgedはレンジ指定
                        1,  # LC hedgedはレンジ指定
                        1,  # lcChange  1 =defence
                        self.units_str,  # uni
                        3,  # priority
                        0,  # watching(0=off,1=On(watch基準はtarget(margin混み))
                    )
                    self.orders_add_this_class_and_flag_on(orders_r)

                    # ●ヘッジオーダー
                    target_price = r['latest_body_peak_price'] + (self.sp * t['direction'])
                    margin = 0.025  # 基本的に即時級。スプレッド分程度
                    tp_range = self.ca.cal_move_ave(1.5)
                    lc_price = t['latest_wick_peak_price']
                    lc_range = abs(lc_price - self.current_price)
                    orders_r = self.order_make(
                        comment + "HEDGE",  # nameとなるcomment
                        target_price,  # targetPrice
                        margin,  # margin
                        r['direction'],  # direction
                        "STOP",  # STOP=順張り　LIMIT＝逆張り
                        1,  # TP hedgedはレンジ指定
                        1,  # LC hedgedはレンジ指定
                        1,  # lcChange  1 =defence
                        self.units_str,  # uni
                        3,  # priority
                        0,  # watching(0=off,1=On(watch基準はtarget(margin混み))
                    )
                    self.orders_add_this_class_and_flag_on(orders_r)

        elif r['count'] == 3:
            if ((self.rt.skip_exist_at_older or 7 <= t['count'] < 100) and self.rt.skip_num_at_older < 3 and
                    0 < self.rt.turn_strength_at_older <= 8):
                if 0 < self.rt.lo_ratio <= 0.36:
                    # ■■オーダーを作成＆発行
                    comment = "●●●強いやつ(旧式"
                    orders = self.order_make(
                        comment,  # nameとなるcomment
                        self.peaks_class.latest_price,  # targetPrice
                        self.ca.cal_move_ave(1),  # margin
                        t['direction'],  # direction
                        "LIMIT",  # STOP=順張り　LIMIT＝逆張り
                        self.ca.cal_move_ave(5),  # TP hedgedはレンジ指定
                        2,  # LC hedgedはレンジ指定
                        1,  # lcChange  1 =defence
                        self.units_str,  # uni
                        4,  # priority
                        0,  # watching(0=off,1=On(watch基準はtarget(margin混み))
                    )
                    # ■オーダーを登録
                    self.orders_add_this_class_and_flag_on(orders)
                    # # test
                    gene.print_json(orders[0])
                    OCreate.Order({
                        "name": comment,
                        "current_price": self.peaks_class.latest_price,
                        "target": 0,
                        "direction": t['direction'],
                        "ls_type": "LIMIT",
                        "tp": self.ca.cal_move_ave(5),
                        "lc": 2,
                        "lc_change": 1,
                        "units": self.units_str,
                        "priority": 4,
                        "decision_time": self.peaks_class.df_r_original.iloc[0]['time_jp'],
                    })
                    print("オーダー新クラステストここまで")

                    # ■■オーダーを作成＆発行
                    comment = "●●●強いやつ(旧式）逆"
                    orders = self.order_make(
                        comment,  # nameとなるcomment
                        self.peaks_class.latest_price,  # targetPrice
                        self.ca.cal_move_ave(0.1),  # margin
                        r['direction'],  # direction
                        "STOP",  # STOP=順張り　LIMIT＝逆張り
                        self.ca.cal_move_ave(1),  # TP hedgedはレンジ指定
                        2,  # LC hedgedはレンジ指定
                        1,  # lcChange  1 =defence
                        self.units_str,  # uni
                        4,  # priority
                        0,  # watching(0=off,1=On(watch基準はtarget(margin混み))
                    )
                    # ■オーダーを登録
                    self.orders_add_this_class_and_flag_on(orders)

                else:
                    print("戻りratio異なる", r['count'])
            else:
                pass
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
        print(" ●判定パラメーター一覧●")
        print("  RT情報 比率:", self.rt.lo_ratio)
        print("  TF情報 比率:", self.tf.lo_ratio)
        print("  T情報 SKIP有無:", self.rt.skip_exist_at_older, ",Skip数:", self.rt.skip_num_at_older, "t-Count:",
              t['count'])
        print("       T-strength:", self.rt.turn_strength_at_older)
        print("  超レンジ状態", self.peaks_class.hyper_range)
        print("  ビッグキャンドル有無", self.peaks_class.is_big_move_candle)



        # オーダーテスト用
        # ■■Latestのピークが伸びる方向（基本形）
        exe_orders = []
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
                    margin = 0.01  # 基本的に即時級。スプレッド分程度
                    tp_range = self.ca.cal_move_ave(1.5)
                    lc_price = t['latest_wick_peak_price']
                    lc_range = abs(lc_price - self.current_price)
                    orders_r = self.order_make_hedged(
                        comment,  # nameとなるcomment
                        target_price,  # targetPrice
                        margin,  # margin
                        r['direction'],  # direction
                        "MARKET",  # STOP=順張り　LIMIT＝逆張り
                        self.ca.cal_move_ave(5),  # TP hedgedはレンジ指定
                        1,  # LC hedgedはレンジ指定
                        1,  # lcChange  1 =defence
                        self.units_str,  # uni
                        3,  # priority
                        0,  # watching(0=off,1=On(watch基準はtarget(margin混み))
                    )
                    self.orders_add_this_class_and_flag_on(orders_r)

                    # ●ヘッジオーダー
                    target_price = r['latest_body_peak_price'] + (self.sp * t['direction'])
                    margin = self.ca.cal_move_ave(1.5)  # 基本的に即時級。スプレッド分程度
                    tp_range = self.ca.cal_move_ave(1.5)
                    lc_price = t['latest_wick_peak_price']
                    lc_range = abs(lc_price - self.current_price)
                    orders_r = self.order_make_hedged(
                        comment + "HEDGE",  # nameとなるcomment
                        target_price,  # targetPrice
                        margin,  # margin
                        t['direction'],  # direction
                        "STOP",  # STOP=順張り　LIMIT＝逆張り
                        1,  # TP hedgedはレンジ指定
                        1,  # LC hedgedはレンジ指定
                        1,  # lcChange  1 =defence
                        self.units_str,  # uni
                        3,  # priority
                        0,  # watching(0=off,1=On(watch基準はtarget(margin混み))
                    )
                    self.orders_add_this_class_and_flag_on(orders_r)

                # ■■レンジ方向
                elif pattern == 2:
                    # ●本命オーダー
                    target_price = r['latest_body_peak_price'] + (self.sp * t['direction'])
                    margin = 0.01  # 基本的に即時級。スプレッド分程度
                    tp_range = self.ca.cal_move_ave(1.5)
                    lc_price = t['latest_wick_peak_price']
                    lc_range = abs(lc_price - self.current_price)
                    orders_r = self.order_make_hedged(
                        comment,  # nameとなるcomment
                        target_price,  # targetPrice
                        margin,  # margin
                        t['direction'],  # direction
                        "MARKET",  # STOP=順張り　LIMIT＝逆張り
                        self.ca.cal_move_ave(1.5),  # TP hedgedはレンジ指定
                        1,  # LC hedgedはレンジ指定
                        1,  # lcChange  1 =defence
                        self.units_str,  # uni
                        3,  # priority
                        0,  # watching(0=off,1=On(watch基準はtarget(margin混み))
                    )
                    self.orders_add_this_class_and_flag_on(orders_r)

                    # ●ヘッジオーダー
                    target_price = r['latest_body_peak_price'] + (self.sp * t['direction'])
                    margin = 0.025  # 基本的に即時級。スプレッド分程度
                    tp_range = self.ca.cal_move_ave(1.5)
                    lc_price = t['latest_wick_peak_price']
                    lc_range = abs(lc_price - self.current_price)
                    orders_r = self.order_make_hedged(
                        comment + "HEDGE",  # nameとなるcomment
                        target_price,  # targetPrice
                        margin,  # margin
                        r['direction'],  # direction
                        "STOP",  # STOP=順張り　LIMIT＝逆張り
                        1,  # TP hedgedはレンジ指定
                        1,  # LC hedgedはレンジ指定
                        1,  # lcChange  1 =defence
                        self.units_str,  # uni
                        3,  # priority
                        0,  # watching(0=off,1=On(watch基準はtarget(margin混み))
                    )
                    self.orders_add_this_class_and_flag_on(orders_r)

        elif r['count'] == 3:
            if ((self.rt.skip_exist_at_older or 7 <= t['count'] < 100) and self.rt.skip_num_at_older < 3 and
                    0 < self.rt.turn_strength_at_older <= 8):
                if 0 < self.rt.lo_ratio <= 0.36:
                    # ■■オーダーを作成＆発行
                    comment = "●●●強いやつ(旧式"
                    orders = self.order_make(
                        comment,  # nameとなるcomment
                        self.peaks_class.latest_price,  # targetPrice
                        self.ca.cal_move_ave(1),  # margin
                        t['direction'],  # direction
                        "LIMIT",  # STOP=順張り　LIMIT＝逆張り
                        self.ca.cal_move_ave(5),  # TP hedgedはレンジ指定
                        2,  # LC hedgedはレンジ指定
                        1,  # lcChange  1 =defence
                        self.units_str,  # uni
                        4,  # priority
                        0,  # watching(0=off,1=On(watch基準はtarget(margin混み))
                    )
                    # ■オーダーを登録
                    self.orders_add_this_class_and_flag_on(orders)

                    # ■■オーダーを作成＆発行
                    comment = "●●●強いやつ(旧式）逆"
                    orders = self.order_make(
                        comment,  # nameとなるcomment
                        self.peaks_class.latest_price,  # targetPrice
                        self.ca.cal_move_ave(0.1),  # margin
                        r['direction'],  # direction
                        "STOP",  # STOP=順張り　LIMIT＝逆張り
                        self.ca.cal_move_ave(1),  # TP hedgedはレンジ指定
                        2,  # LC hedgedはレンジ指定
                        1,  # lcChange  1 =defence
                        self.units_str,  # uni
                        4,  # priority
                        0,  # watching(0=off,1=On(watch基準はtarget(margin混み))
                    )
                    # ■オーダーを登録
                    self.orders_add_this_class_and_flag_on(orders)

                else:
                    print("戻りratio異なる", r['count'])
            else:
                pass
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
