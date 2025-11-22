import datetime
import fTurnInspection as ti
import classOrderCreate as OCreate
import fGeneric as gene




class wrap_all_analysis():
    def __init__(self, candle_analysis_class):
        # 調査に必要な変数
        # self.df_r = df_r
        # self.oa = oa
        self.ca = candle_analysis_class  # CandleAnalysisインスタンスの生成

        # 結果を格納するための変数（大事）
        self.take_position_flag = False
        self.exe_order_classes = []

        # 実行
        self.wrap_all_inspections()

        # 最終的なオーダー
        print("最終的なオーダー")
        for i in range(len(self.exe_order_classes)):
            # 表示専用
            print(self.exe_order_classes[i].exe_order)

    def orders_add_this_class(self, order_classes):
        """

        """
        self.take_position_flag = True
        self.exe_order_classes.extend(order_classes)

    def orders_replace_this_class(self, order_classes):
        """
        オーダーを置き換えるよう（前の検証のオーダーは忘れる漢字）
        """
        self.take_position_flag = True
        self.exe_order_classes = order_classes

    def wrap_all_inspections(self):
        """
        クラスをたくさん用いがケース
        """

        # ターン起点のオーダー
        turn_analysis_instance = ti.turn_analisys(self.ca)
        # turn_analysis_instance = ti.BbAnalysis(self.ca)
        if turn_analysis_instance.take_position_flag:
            self.orders_add_this_class(turn_analysis_instance.exe_order_classes)

        # テスト用
        # range_analysis_instance = ti.predict_turn_analysis(self.ca)
        # if range_analysis_instance.take_position_flag:
        #     self.orders_add_this_class(range_analysis_instance.exe_order_classes)

        # # 時間起点のオーダー（深夜12時～2時前にかけて、下がる傾向がある気がする）
        # time_analysis_instance = time_analysis(self.ca)
        # if time_analysis_instance.take_position_flag:
        #     self.orders_replace_this_class(time_analysis_instance.exe_order_classes)  # オーダー置換


class time_analysis():
    def __init__(self, candle_analysis_class):
        # 調査に必要な変数
        self.ca = candle_analysis_class  # CandleAnalysisインスタンスの生成
        self.ca5 = self.ca.candle_class  # peaks以外の部分。cal_move_ave関数を使う用
        self.peaks_class = candle_analysis_class.peaks_class
        self.df_r = self.peaks_class.df_r_original

        # 注文用
        self.take_position_flag = False
        self.exe_order_classes = []

        # 変数
        self.sp = 0.004  # スプレッド考慮用
        self.base_lc_range = 1  # ここでのベースとなるLCRange
        self.base_tp_range = 1
        self.units_str = 1
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

        # 実行関数
        self.time_order()

    def add_order_and_flag_inspecion_class(self, order_class):
        """

        """
        self.take_position_flag = True
        self.exe_order_classes.append(order_class)

    def time_order(self):
        print("一番新しい時間", self.df_r.iloc[0]['time_jp'])
        s = self.df_r.iloc[0]['time_jp']
        dt = datetime.datetime.strptime(s, "%Y/%m/%d %H:%M:%S")
        hour = dt.hour
        minute = dt.minute
        if hour == 1 and minute <= 4:
            print("深夜の一時の初回です")
            order_class1 = OCreate.Order({
                "name": "深夜一時の売りオーダー",
                "current_price": self.peaks_class.latest_price,
                "target": 0,  # target_price,
                "direction": -1,
                "type": "MARKET",  # "MARKET",
                "tp": self.base_tp_range,  # self.ca5.cal_move_ave(5),
                "lc": self.base_lc_range,
                "lc_change": self.lc_change_test,
                "units": self.units_str,
                "priority": 100,
                "decision_time": self.peaks_class.df_r_original.iloc[0]['time_jp'],
                "candle_analysis_class": self.ca
            })
            self.add_order_and_flag_inspecion_class(order_class1)
