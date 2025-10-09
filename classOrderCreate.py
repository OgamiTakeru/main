import fGeneric as gene
import tokens as tk
import copy

class Order:
    """
    このクラスで、オーダー発行＋オーダー＆ポジション管理が確実にできる情報に整える。
    オーダー発行時は、このクラスでのFinalizeが必須。
    （コード短縮のため、ポジション側や、オーダー発行用のオアンダクラスでは、データのチェック機能は搭載しない）
    オーダーfinalizeを行うと、以下が生成される
    ・oanda_order_json: API発行用
    ・order_json:　プログラムでオーダーやポジションを管理するために必要な情報を含んだJson

    """
    def __init__(self, order_json):
        # オーダー発行用のJsonを生成する。
        self.order_json_original = order_json  # オーダー用json
        self.order_json = self.order_json_original

        # ■■
        # 色々なオーダーに必要になる初期値
        self.instrument = "USD_JPY"
        self.base_oa_mode = 2  # デフォルトの口座は2(両建て用）
        self.basic_unit = 1000
        self.basic_lc_range = 1  # 1円
        self.trade_timeout_min_base = 240
        self.order_timeout_min_base = 60
        self.lc_change_base = 3  # ベースは０（LCchangeなし）
        # 判定に利用する、初期値
        self.u = 3  # round時の有効桁数
        self.dependence_price_or_range_criteria = 80  # ドル円の場合、80以上は価格とみなし、それ以下はrangeとみなす
        self.dependence_tp_lc_margin = 0.01  # targetとTP/LCとの間が極端に狭いときはウォーニングを出す（すぐ決済になってしまうため）

        # ■■
        # OandaAPI用のにはこのJsonを送信することでオーダーを発行可能
        self.data = {}
        self.exe_order = {}
        # オーダーを管理するための情報群（デフォルト値付）
        self.oa_mode = 2
        self.target = 0  # 正の値で記載。margin または　target_priceが渡される（引数のコピー）
        self.target_price = 0  # targetから抽出されたtarget_price
        self.margin = 0  # targetから抽出されたmargin(現在価格とtarget_priceの差分）
        self.direction = 0
        self.ls_type = ""
        self.units = 0
        self.units_adj = 0.1
        self.decision_time = 0  # 決心時の時間
        self.current_price = 0  # 現在価格（＝決心価格。現在価格はAPIで取得しない⇒大規模トライでもこのクラスを使うため）
        self.priority = 0
        self.tp_price = 0
        self.tp_range = 0  # 正の値で記載
        self.lc_price = 0
        self.lc_range = 0  # 正の値で起債
        self.name = "name"
        self.name_ymdhms = "name_for_test"  # 大量処理のテストで1年を通じて同じ名前が発生しないように、年月日をくっつけたものも準備
        self.trade_timeout_min = 0
        self.order_timeout_min = 0
        self.order_permission = True
        self.lc_change = {}
        self.linkage_order_classes = []

        # 色々な情報を受け取っていれば、それを取得する(ただし、エラー防止のため、インスタンス変数で明示的に損z内を示す）
        self.candle_analysis = None
        self.move_ave = 0
        if "candle_analysis_class" in order_json:
            # print("candle_analysis_classがあるよ", round(order_json['candle_analysis_class'].candle_class.cal_move_ave(1), 3))
            self.move_ave = order_json['candle_analysis_class'].candle_class.cal_move_ave(1)
        else:
            tk.line_send("【注意】キャンドルアナリシスが添付されていない注文が発生")
            print("candle_analysis_classがない")
            print(order_json)

        # ■■処理
        self.check_order_json()  # 渡された引数に、必要項目の抜けがある場合、ここで表示
        self.order_finalize_new()  # 管理に必要な情報を、計算で補完する。
        self.lc_change_control()  # lc_changeを付与する。
        self.make_json_from_instance()  # オーダー可能な情報を生成する。

    def make_json_from_instance(self):
        """
        インスタンス変数を、オーダー用の辞書（Json）形式に変換する
        本来は実施していなかったが、明示的に辞書に変換する記述を追加し、何を渡しているかわかりやすくする
        """
        # ■API送信用（一番大事な奴）
        self.data = {  # オーダーのテンプレート！（一応書いておく）
                "order": {
                    "instrument": self.instrument,
                    "units": str(self.units * self.direction),
                    "type": self.ls_type,  # "STOP(逆指)" or "LIMIT" or "MARKET"
                    "positionFill": "DEFAULT",
                    "price": str(round(self.target_price, self.u)),  # 小数点3桁の文字列（それ以外はエラーとなる）
                    "takeProfitOnFill": {
                        "timeInForce": "GTC",
                        "price": str(round(self.tp_price, self.u))  # 小数点3桁の文字列（それ以外はエラーとなる）
                    },
                    "stopLossOnFill": {
                        "timeInForce": "GTC",
                        "price": str(round(self.lc_price, self.u))  # 小数点3桁の文字列（それ以外はエラーとなる）
                    },
                    # "trailingStopLossOnFill": {
                    #     "timeInForce": "GTC",
                    #     "distance": "0"  # 5pips以上,かつ,小数点3桁の文字列
                    # }
                }
            }
        # ■ポジション管理用含めた情報
        self.exe_order = {
            "decision_time": self.decision_time,
            "units": self.units,
            "direction": self.direction,
            "target_price": round(self.target_price, 3),
            "lc_price": self.lc_price,  # 途中で変更される可能性あり（常に最新のLC価格を保持する物）
            "lc_range": self.lc_range,
            "tp_price": self.tp_price,  # 途中で変更される可能性あり（常に最新のTP価格を保持する物）
            "tp_range": self.tp_range,
            "type": self.ls_type,
            "name": self.name,
            "name_ymdhms": self.name_ymdhms,
            "oa_mode": self.oa_mode,
            "order_timeout_min": self.order_timeout_min,
            "trade_timeout_min": self.trade_timeout_min,
            "order_permission": self.order_permission,
            "priority": self.priority,
            "watching_price": 0,
            "lc_price_original": self.lc_price,  # LCは変更される可能性がある（元々の価格を保存するため）
            "tp_price_original": self.tp_price,  # TPは変更される可能性がある（元々の価格を保存するため）
            "for_api_json": self.data,  # 発注API用(classPositionにはexe_orderしか渡さないため、その中に入れておく）
            "lc_change": self.lc_change,
            "move_ave": self.move_ave  # 参考情報だが追加（無いとLineSendでエラーになるが、オーダーには影響ない）
        }

        # クラスにある情報を明示しておく（混乱防止用で、冗長な書き方）
        if "candle_analysis_class" in self.order_json:
            self.candle_analysis = self.order_json['candle_analysis_class']
        else:

            self.candle_analysis = None  # 基本、初回の強制オーダー以外では、candle_analysisは入ってくる

        # 他に対外的に使うやつ
        # self.linkage_classes = self.linkage_classes  # 覚書

    def check_order_json(self):
        """
        オーダーの中身を確認し、オーダーに必要な情報が足りているかを確認する

        最低限必要な情報
        order_base_dic = {
            "target": 0.00,  # 価格(80以上の値) or Range で正の値。Rangeの場合、decision_priceを基準にPrice(APIに必須）に換算される。
            "type": "STOP",  # 文字列。計算時は数字のほうが楽なため、stop_or_limit変数で数字に置き換えたものも算出（finalize関数)
            "units": OrderCreateClass.basic_unit,
            "expected_direction": 1,
            "tp": 0.9,  # 80以上の値は価格とみなし、それ以外ならRange(target価格+tpRange。正の値）とする
            "lc": 0.03,  # 80以上の値は価格とみなし、それ以外ならRange(target価格+lcRange。正の値）とする
            'priority': 0,
            "decision_price": 0,  # "Now"という文字列の場合、この関数で即時取得する。targetがRangeの場合必須。
            "decision_time": "",
            "name": "",
            "order_timeout_min": 0,
        }

        生成される情報(order_baseをorder_finalize関数に入れると、以下が生成される）
        finalized_order = {
            "units": 1000, #【Order必須】
            "stop_or_limit": stop_or_limit,  # 計算に便利な数字形式で１か-1で表現（1=STOP）。☆
            "type": "STOP" or "LIMIT",  # 【Order必須】 ☆　　(☆はどちらか一つあれば、この関数で両方を算出）
            "expected_direction":  # プログラム用
            "decision_time":  # プログラム用
            "decision_price":  # プログラム用
            "position_margin":  # プログラム用
            "target_price":  # プログラム用
            "lc_range":  # プログラム用
            "tp_range":  # プログラム用
            "tp_price":  # プログラム用
            "lc_price":  # プログラム用
            "direction",  # classOandaでask_bidという変数名に置換して利用。この値でTargetPriceやLCPriceを算出する。
            "price":,  # 【Order必須】この関数でtarget_priceを基に計算される。
            "trade_timeout_min,　# プログラム用
            "order_permission",　# プログラム用
            "priority",  # プログラム用
            "lc_change": [
                 {"exe": True, "time_after": 60, "trigger": 0.05, "ensure": 0.04},
            ],  　# プログラム用
        }
        """
        order_json = self.order_json
        print("targetなし。その場合、targetPriceが必要です。") if "target" not in order_json else None
        print("typeがありません") if "type" not in order_json else None
        print("directionがありません") if "direction" not in order_json else None
        print("lcがありません") if "lc" not in order_json else None
        print("tpがありません") if "tp" not in order_json else None
        print("decision_timeがありません") if "decision_time" not in order_json else None
        print("current_priceがありません") if "current_price" not in order_json else None
        print("priorityがありません") if "priority" not in order_json else None

    def order_finalize_new(self):
        """
        各値をチェックし、読み替える。　必要に応じてデフォルト値を入れる
        """
        order_json = self.order_json

        # 環境を選択する（通常環境か、両建て環境か）
        if "oa_mode" in order_json:
            self.oa_mode = order_json['oa_mode']
        else:
            self.oa_mode = self.base_oa_mode

        # 名前の入力
        # print(order_json['name'])
        self.name = order_json['name'] + "_" + str(gene.delYearDay(order_json['decision_time']))
        self.name_ymdhms = order_json['name'] + "_" + order_json['decision_time']

        # priority
        self.priority = order_json['priority']

        # Unitsがない場合は初期値を入れる
        if "units" in order_json:
            if order_json['units'] < 100:
                # 100以下の数字は倍率とみなす
                # print("   UNITが倍数として処理されています")
                self.units = round(self.basic_unit * order_json['units'])
                self.units_adj = order_json['units']
            else:
                # 直接の指定と判断
                self.units = self.order_json["units"]
                self.units_adj = 1
        else:
            # print("Unit指定がないため、Unitsを基本のものを入れておく")
            self.units = self.basic_unit

        # 注文方式を指定する
        if "type" in order_json:
            self.ls_type = order_json['type']
        else:
            print(" オーダー方法記載内為、MARKET注文とする")

        # 購入方向（１買い、-1売り）
        self.direction = order_json['direction']

        # 決心時間を入れておく（決心価格はcurrentPrice)
        self.decision_time = order_json['decision_time']
        self.current_price = order_json['current_price']

        # ★ここからは下は、Directionとtypeは必須。処理の順番が大切
        # ①TargetPriceを確実に取得する
        if 'target' in order_json:
            # 価格で指定されている、と判断される時
            if order_json['target'] >= self.dependence_price_or_range_criteria:
                self.target_price = order_json['target']
            # 現在価格との差分で指定されている、と判断されるとき
            else:
                margin = order_json['target']  # わかりやすいように変数で置換
                # STOPオーダー（順張りの場合）⇒現価より高い値段で買い、現価より低い値段で売り
                if self.ls_type == "STOP":
                    if self.direction == 1:
                        # 買いの場合、現在より高い値段を設定。
                        self.target_price = self.current_price + margin
                    else:
                        # 売りの場合、現在より低い価格を設定
                        self.target_price = self.current_price - margin
                # LIMITオーダー（逆張りの場合）⇒現価より低い値段で買い、現価より高い値段で売り
                elif self.ls_type == "LIMIT":
                    if self.direction == 1:
                        # 買いの場合、現在より低い値段を設定。
                        self.target_price = self.current_price - margin
                    else:
                        # 売りの場合、現在より高い価格を設定
                        self.target_price = self.current_price + margin
                # MARKETオーダーの場合
                else:
                    self.target_price = self.current_price

        # TP情報を取得する（TPの値は、クライテリアより小さい値ならRange指定、それ以上は価格直接指定と読み替える）
        if 'tp' in order_json:
            # 価格で指定されている場合
            if order_json['tp'] >= self.dependence_price_or_range_criteria:
                self.tp_range = round(abs(order_json['target_price'] - order_json['tp']), self.u)  # Rangeを算出
                self.tp_price = round(order_json['tp'], self.u)  # Priceはそのまま代入
            # レンジで指定されている場合
            else:
                self.tp_range = round(order_json['tp'], self.u)  # Rangeはそのまま代入
                self.tp_price = round(self.target_price + (self.tp_range * self.direction), self.u)

            # TPRangeが狭すぎる場合はウォーニングを出す
            if self.tp_range < self.dependence_tp_lc_margin:
                print("  ★★TP価格とTarget価格が極端に近いため、注意", self.tp_range, self.tp_price, self.target_price)

        # LC情報を取得する（LCの値は、正の値で指定される。クライテリアより小さい値ならRange指定、それ以上は価格直接指定と読み替える）
        if 'lc' in order_json:
            # 価格で指定されている場合
            if order_json['lc'] >= self.dependence_price_or_range_criteria:
                self.lc_range = round(abs(order_json['target_price'] - order_json['lc']), self.u) # Rangeを算出
                self.lc_price = round(order_json['lc'], self.u)  # Priceはそのまま代入
            # レンジで指定されている場合
            else:
                self.lc_range = round(order_json['lc'], self.u)  # Rangeはそのまま代入
                self.lc_price = round(self.target_price - (self.lc_range * self.direction), self.u)

            # LCRangeが狭すぎる場合はウォーニングを出す
            if self.lc_range < self.dependence_tp_lc_margin:
                print("  ★★LC価格とTarget価格が極端に近いため、注意", self.lc_range, self.lc_price, self.target_price)

        # 時間の設定
        # オーダータイムアウトは、入っていなければデフォルトを代入
        if 'order_timeout_min' in order_json:
            self.order_timeout_min = order_json['order_timeout_min']
        else:
            self.order_timeout_min = self.order_timeout_min_base

        # トレード（ポジション）タイムアウトは、入っていなければデフォルトを代入
        if 'trade_timeout_min' in order_json:
            self.trade_timeout_min = order_json['trade_timeout_min']
        else:
            self.trade_timeout_min = self.trade_timeout_min_base

        # オーダーの特殊な設定達
        # オーダーパーミッション
        if 'order_permission' in order_json:
            self.order_permission = True  # 即時オーダー発行
        else:
            self.order_permission = False

        # アラート機能
        if "alert" in order_json and "range" in order_json['alert']:
            # if isinstance(plan['alert']['range'], int)
            temp_range = round(order_json['alert']['range'], 3)
            temp_price = round(order_json['target_price'] - (
                        order_json['alert']['range'] * order_json['direction']), 3)
            # 改めて入れなおしてしまう（別に上書きでもいいんだけど）
            order_json['alert'] = {"range": temp_range, "alert_price": temp_price, "time": 0}
        else:
            order_json['alert'] = {"range": 0, "time": 0, "alert_price": 0}

        # ref(無いと、検証の時にエラーになる)
        if "ref" in order_json:
            pass
        else:
            pass
            # order_json['ref'] = {"move_ave": 0, "peak1_target_gap": 0}

    def add_linkage(self, another_order_class):
        # print("OrderCreate334")
        # print(self.linkage_classes)
        self.linkage_order_classes.append(another_order_class)

    def lc_change_control(self):
        order_json = self.order_json
        # LC_Changeを付与する 検証環境の都合で、必須。(finalizedに直接追加）
        # lc_changeは数字か辞書が入る。辞書の場合、lc_changeの先頭にそれが入る
        # self.finalized_order['lc_change'] = [] # 初期化
        # print("lc_change order create 324")
        # print(self.order_json)
        if "lc_change" not in order_json:
            # typeしていない場合はノーマルを追加
            self.add_lc_change_defence()
        else:
            if isinstance(order_json['lc_change'], int):
                # print("処理A: int型です", order_json['lc_change_type'])
                # 指定されている場合は、指定のLC_Change処理へ
                if order_json['lc_change'] == 1:
                    self.add_lc_change_defence()
                elif order_json['lc_change'] == 0:
                    self.add_lc_change_no_change()
                elif order_json['lc_change'] == 3:
                    self.add_lc_change_offence()
            else:
                self.add_lc_change_start_with_dic(order_json['lc_change'])

    def add_lc_change_no_change(self):
        """
        lcChange = 0で選ばれるもの
        形式的に入れたもの（形式的に入れないとエラーになるので）
        ほぼ到達しない１円を入れておく
        """
        self.lc_change = [
            {"exe": True, "time_after": 0, "trigger": 1, "ensure": 1},
        ]

    def add_lc_change_offence(self):
        """
        lcChange = 3で選ばれるもの
        実際の運用をイメージ
        ・最初の30分はlc_1.3程度をトリガーにしてLC分を確実に回収できるように
        　（一度20pips位上がった後に、LCまで戻っており、悔しかった。上がるのは大体直前
        ・30分以降は、ローソク形状の効果が切れたとみなし、プラスにいる場合はとにかく利確に向けた動きをする
        """
        self.lc_change = [
            # {"exe": True, "time_after": 0, "trigger": 1, "ensure": 1},
            # {"exe": True, "time_after": 600, "trigger": 0.025, "ensure": 0.005},
            {"exe": True, "time_after": 600, "trigger": 0.04, "ensure": 0.004},  # -0.02が強い
            {"exe": True, "time_after": 600, "trigger": 0.06, "ensure": 0.01},
            # {"exe": True, "time_after": 600, "trigger": first_trigger, "ensure": first_ensure},
            {"exe": True, "time_after": 600, "trigger": 0.08, "ensure": 0.02},
            {"exe": True, "time_after": 0, "trigger": 0.20, "ensure": 0.15},
            {"exe": True, "time_after": 600, "trigger": 0.40, "ensure": 0.35},
            {"exe": True, "time_after": 2 * 5 * 60, "trigger": 0.60, "ensure": 0.55},
            {"exe": True, "time_after": 2 * 5 * 60, "trigger": 0.70, "ensure": 0.65},
            {"exe": True, "time_after": 2 * 5 * 60, "trigger": 0.80, "ensure": 0.75},
            {"exe": True, "time_after": 2 * 5 * 60, "trigger": 0.90, "ensure": 0.85},
            {"exe": True, "time_after": 2 * 5 * 60, "trigger": 1.00, "ensure": 0.95},
        ]

    def add_lc_change_start_with_dic(self, dic_arr):
        """
        lcChange = 3で選ばれるもの
        実際の運用をイメージ
        ・最初の30分はlc_1.3程度をトリガーにしてLC分を確実に回収できるように
        　（一度20pips位上がった後に、LCまで戻っており、悔しかった。上がるのは大体直前
        ・30分以降は、ローソク形状の効果が切れたとみなし、プラスにいる場合はとにかく利確に向けた動きをする
        """
        # print("   特殊LCChange")

        add = [
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
        # print("   渡されたLcChange", dic_arr)
        # print("　　最終的なLcChange", add)
        self.lc_change = dic_arr + add

    def add_lc_change_defence(self):
        """
        lcChange = 1で選ばれるもの
        負ける可能性は高くなる可能性高い。
        少しプラスになったらLCの幅を減らしていく手法
        """
        min10 = 60 * 10
        self.lc_change = [
            {"exe": True, "time_after": min10, "trigger": 0.025, "ensure": 0.01},
            # {"exe": True, "time_after": 600, "trigger": 0.043, "ensure": 0.018},
            # {"exe": True, "time_after": 600, "trigger": first_trigger, "ensure": first_ensure},
            {"exe": True, "time_after": min10, "trigger": 0.05, "ensure": 0.052},
            {"exe": True, "time_after": min10, "trigger": 0.08, "ensure": 0.05},
            {"exe": True, "time_after": min10, "trigger": 0.20, "ensure": 0.15},
            {"exe": True, "time_after": 600, "trigger": 0.40, "ensure": 0.35},
            {"exe": True, "time_after": 2 * 5 * 60, "trigger": 0.60, "ensure": 0.55},
            {"exe": True, "time_after": 2 * 5 * 60, "trigger": 0.70, "ensure": 0.65},
            {"exe": True, "time_after": 2 * 5 * 60, "trigger": 0.80, "ensure": 0.75},
            {"exe": True, "time_after": 2 * 5 * 60, "trigger": 0.90, "ensure": 0.85},
            {"exe": True, "time_after": 2 * 5 * 60, "trigger": 1.00, "ensure": 0.95},
        ]

