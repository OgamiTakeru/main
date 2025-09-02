import classCandleAnalysis as ca
import fTurnInspection as ti
import fGeneric as gene

class wrap_all_analisys():
    def __init__(self, df_r, oa):
        # 調査に必要な変数
        self.df_r = df_r
        self.oa = oa
        self.ca = ca.candleAnalysis(df_r, oa)  # CandleAnalysisインスタンスの生成

        # 結果を格納するための変数（大事）
        self.take_position_flag = False
        self.exe_order_classes = []

        # 実行
        self.wrap_all_inspections()


    def orders_add_this_class_and_flag_on2(self, order_classes):
        """

        """
        # self.flag_and_orders['take_position_flag'] = True
        # self.flag_and_orders['exe_orders'] = orders
        self.take_position_flag = True
        self.exe_order_classes.extend(order_classes)

    def wrap_all_inspections(self):
        """
        クラスをたくさん用いがケース
        args[0]は必ずdf_rであることで、必須。
        args[1]は、本番の場合、過去の決済履歴のマイナスの大きさでTPが変わるかを検討したいため、オーダークラスを受け取る
        """

        # ターン起点のオーダー
        turn_analysis_instance = ti.turn_analisys(self.ca, self.oa)
        # turn_result = ti.wrap_little_turn_inspection(peaks_class)  #
        if turn_analysis_instance.take_position_flag:
            # self.orders_add_this_class_and_flag_on(turn_analysis_instance.exe_orders)
            self.orders_add_this_class_and_flag_on2(turn_analysis_instance.exe_order_classes)
        print("wrap")
        for i in range(len(self.exe_order_classes)):
            print(self.exe_order_classes[i].exe_order)
