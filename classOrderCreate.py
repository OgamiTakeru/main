import fGeneric as gene
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
        self.basic_unit = 10000
        self.trade_timeout_min_base = 240
        self.order_timeout_min_base = 15
        self.lc_change_base = 3  # ベースは０（LCchangeなし）
        # 判定に利用する、初期値
        self.u = 3  # round時の有効桁数
        self.dependence_price_or_range_criteria = 80  # ドル円の場合、80以上は価格とみなし、それ以下はrangeとみなす
        self.dependence_tp_lc_margin = 0.01  # targetとTP/LCとの間が極端に狭いときはウォーニングを出す（すぐ決済になってしまうため）

        # ■■
        # OandaAPI用のにはこのJsonを送信することでオーダーを発行可能
        self.data = {}
        self.exe_orders = {}
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
        self.current_price = 0 # 現在価格（＝決心価格。現在価格はAPIで取得しない⇒大規模トライでもこのクラスを使うため）
        self.priority = 0
        self.tp_price = 0
        self.tp_range = 0  # 正の値で記載
        self.lc_price = 0
        self.lc_range = 0  # 正の値で起債
        self.name = "name"
        self.trade_timeout_min = 0
        self.order_timeout_min = 0
        self.order_permission = True
        self.lc_change = {}

        # ■■処理
        self.check_order_json()
        self.order_finalize_new()
        self.lc_change_control()  #
        self.make_json_from_instance()

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
        self.exe_orders = {
            "decision_time": self.decision_time,
            "units": self.units,
            "direction": self.direction,
            "target_price": round(self.target_price, 3),
            "lc_price": self.lc_price,
            "lc_range": self.lc_range,
            "tp_price": self.tp_price,
            "tp_range": self.tp_range,
            "type": self.ls_type,
            "name": self.name,
            "oa_mode": self.oa_mode,
            "order_timeout_min": self.order_timeout_min,
            "trade_timeout_min": self.trade_timeout_min,
            "order_permission": self.order_permission,
            "priority": self.priority,
            "watching_price": 0,
            "lc_price_original": self.lc_price,
            "api_data": self.data,  # 発注API用
            "lc_change": self.lc_change
        }
        print("最終系")
        gene.print_json(self.exe_orders)

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
        print(order_json['name'])
        self.name = order_json['name'] + "_" + str(gene.delYearDay(order_json['decision_time']))

        # priority
        self.priority = order_json['priority']

        # Unitsがない場合は初期値を入れる
        if "units" in order_json:
            if order_json['units'] <= 100:
                # 100以下の数字は倍率とみなす
                print("   UNITが倍数として処理されています")
                self.units = self.basic_unit * order_json['units']
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
            order_json['ref'] = {"move_ave": 0, "peak1_target_gap": 0}

    def lc_change_control(self):
        order_json = self.order_json
        # LC_Changeを付与する 検証環境の都合で、必須。(finalizedに直接追加）
        # lc_changeは数字か辞書が入る。辞書の場合、lc_changeの先頭にそれが入る
        # self.finalized_order['lc_change'] = [] # 初期化
        if "lc_change_type" not in order_json:
            # typeしていない場合はノーマルを追加
            self.add_lc_change_defence()
        else:
            if isinstance(order_json['lc_change_type'], int):
                # print("処理A: int型です", order_json['lc_change_type'])
                # 指定されている場合は、指定のLC_Change処理へ
                if order_json['lc_change_type'] == 1:
                    self.add_lc_change_defence()
                elif order_json['lc_change_type'] == 0:
                    self.add_lc_change_no_change()
                elif order_json['lc_change_type'] == 3:
                    self.add_lc_change_offence()
            else:
                self.add_lc_change_start_with_dic(order_json['lc_change_type'])

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
        print("特殊LCChange")

        add = [
            # {"exe": True, "time_after": 0, "trigger": 1, "ensure": 1},
            # {"exe": True, "time_after": 600, "trigger": 0.025, "ensure": 0.005},
            # {"exe": True, "time_after": 0, "trigger": 0.04, "ensure": 0.010},
            # {"exe": True, "time_after": 600, "trigger": first_trigger, "ensure": first_ensure},
            # {"exe": True, "time_after": 0, "trigger": 0.08, "ensure": 0.05},
            {"exe": True, "time_after": 0, "trigger": 0.15, "ensure": 0.1},
            {"exe": True, "time_after": 0, "trigger": 0.20, "ensure": 0.15},
            {"exe": True, "time_after": 600, "trigger": 0.40, "ensure": 0.35},
            {"exe": True, "time_after": 2 * 5 * 60, "trigger": 0.60, "ensure": 0.55},
            {"exe": True, "time_after": 2 * 5 * 60, "trigger": 0.70, "ensure": 0.65},
            {"exe": True, "time_after": 2 * 5 * 60, "trigger": 0.80, "ensure": 0.75},
            {"exe": True, "time_after": 2 * 5 * 60, "trigger": 0.90, "ensure": 0.85},
            {"exe": True, "time_after": 2 * 5 * 60, "trigger": 1.00, "ensure": 0.95},
        ]
        print("   渡されたLcChange", dic_arr)
        print("　　最終的なLcChange", add)
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


class OrderCreateClass:
    """
    処理解説
    インスタンスを生成すると、現在価格等を取得するため、OandaClassも生成する
    また、以下の情報を受け取り、ファイナライズを実施する。

    最低限必要な情報
    order_base_dic = {
        "target": 0.00,  # 価格(80以上の値) or Range で正の値。Rangeの場合、decision_priceを基準にPrice(APIに必須）に換算される。
        "type": "STOP",  # 文字列。計算時は数字のほうが楽なため、stop_or_limit変数で数字に置き換えたものも算出（finalize関数)
        "units": OrderCreateClass.basic_unit,
        "direction": 1,
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
        "direction":  # プログラム用
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

    最終的にAPIに流すJson
    data = {  # オーダーのテンプレート！（一応書いておく）
        "order": {
            "instrument": "USD_JPY",　　# ←これはclassOandaで直接入れちゃっている
            "units": "10",
            "type": "",  # "STOP(逆指)" or "LIMIT"
            "positionFill": "DEFAULT",
            "price": "150",  # USD/JPYの場合、小数点下三桁までの「文字列」。指値の時に必要。成り行き時は入力不要
            "stopLossOnFill": {
                "price": "151",
                "timeInForce": "GTC"
            },
            "takeProfitOnFill": {
                "price": "149",
                "timeInForce" : "GTC"
            },
            "trailingStopLossOnFill": {
                "distance": "0.05",  # 0.05以上の文字列
                "timeInForce": "GTC"
            }
        }
    }
    """
    basic_unit = 10000
    # basic_unit = 25000
    oa = None

    def __init__(self, order_json):
        # 引数を格納する
        self.order_base = order_json  # 受け取る際の簡易的な情報（オーダーキック用）

        # ■初期値の設定
        self.base_oa_mode = 2  # デフォルトの口座は2(両建て用）
        # 価格や通貨に依存する物たち
        self.dependence_price_or_range_criteria = 80  # ドル円の場合、80以上は価格とみなし、それ以下はrangeとみなす
        self.dependence_tp_lc_margin = 0.02  # 最低限の幅を保つためのもの。ドル円の場合0.02円(2pips) (LC価格とTarget価格が同値となった時の調整)

        # ■処理
        self.check_args()  # 引数のオーダーベースを確認する（エラーがある場合は返す）
        self.finalized_order = self.order_finalize()  # オーダーをファイナライズする(finalizedのオーダーは別の変数に入れる）
        self.lc_change_control()  #

        # 追加処理：解析用のデータを取得する（とりあえずないと途中でエラーになるので）
        self.finalized_order['for_inspection_dic'] = {}

        # 表示用
        self.finalized_order_without_lc_change = copy.deepcopy(self.finalized_order)
        self.finalized_order_without_lc_change.pop("lc_change", None)  # キーがなければ None を返す

    def check_args(self):
        """
        渡された引数を確認する
        """
        order_json = self.order_base

        # 情報に不足がないかの確認
        print("targetなし。その場合、targetPriceが必要です。") if "target" not in self.order_base else None
        print("typeがありません") if "type" not in self.order_base else None
        print("directionがありません") if "direction" not in self.order_base else None
        print("lcがありません") if "lc" not in self.order_base else None
        print("tpがありません") if "tp" not in self.order_base else None
        print("decision_timeがありません") if "decision_time" not in self.order_base else None
        print("decision_priceがありません。この場合targetがマージンを示す場合、基準がないため利用できません。") if "decision_price" not in self.order_base else None
        print("priorityがありません") if "priority" not in self.order_base else None
        # print("decision_priceがありません（なければここで入れます）") if "decision_price" not in order_json else None

        # Unitsがない場合は初期値を入れる
        if "units" in order_json:
            if order_json['units'] == 1:
                # unit指定が１の場合は、基本値を入れる
                self.order_base["units"] = self.basic_unit
            elif order_json['units'] <= 100:
                # 100以下の数字は倍率とみなす
                self.order_base["units"] = self.basic_unit * order_json['units']
            else:
                # 直接の指定と判断
                self.order_base["units"] = self.order_base["units"]
        else:
            # print("Unit指定がないため、Unitsを基本のものを入れておく")
            self.order_base["units"] = self.basic_unit

        # 環境を選択する（通常環境か、両建て環境か）
        if "oa_mode" in order_json:
            pass
        else:
            self.order_base['oa_mode'] = 2  # 何も書かれていない場合は通常環境に入れる

        # 情報を取得する（場合によって）
        if "decision_price" not in order_json or self.order_base["decision_price"] == "Now":
            # decision_priceはなければ(または明示的にNowが指定してくれている場合）ここで追加する
            # print("decision_priceを追加しました")
            self.order_base["decision_price"] = self.get_now_mid_price()

    def lc_change_control(self):
        order_json = self.order_base
        # LC_Changeを付与する 検証環境の都合で、必須。(finalizedに直接追加）
        # lc_changeは数字か辞書が入る。辞書の場合、lc_changeの先頭にそれが入る
        # self.finalized_order['lc_change'] = [] # 初期化
        if "lc_change_type" not in order_json:
            # typeしていない場合はノーマルを追加
            self.add_lc_change_defence()
        else:
            if isinstance(order_json['lc_change_type'], int):
                # print("処理A: int型です", order_json['lc_change_type'])
                # 指定されている場合は、指定のLC_Change処理へ
                if order_json['lc_change_type'] == 1:
                    self.add_lc_change_defence()
                elif order_json['lc_change_type'] == 0:
                    self.add_lc_change_no_change()
                elif order_json['lc_change_type'] == 3:
                    self.add_lc_change_offence()
                elif order_json['lc_change_type'] == 4:
                    self.add_lc_change_after_lc()
            else:
                self.add_lc_change_start_with_dic(order_json['lc_change_type'])

    def get_now_mid_price(self):
        """
        各関数の行数削減（特にエラー対応）のため、関数に出す
        ・とりあえずミドル価格を返す
        ・エラーの場合、このループをおしまいにする？それともっぽい値を返却する？
        """
        price_dic = self.oa.NowPrice_exe("USD_JPY")
        if price_dic['error'] == -1:  # APIエラーの場合はスキップ
            print("      API異常発生の可能性")
            return -1  # 終了
        else:
            price_dic = price_dic['data']
        return price_dic['mid']

    def add_lc_change_no_change(self):
        """
        lcChange = 0で選ばれるもの
        形式的に入れたもの（形式的に入れないとエラーになるので）
        ほぼ到達しない１円を入れておく
        """
        self.finalized_order['lc_change'] = [
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
        self.finalized_order['lc_change'] = [
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
        print("特殊LCChange")

        add = [
            # {"exe": True, "time_after": 0, "trigger": 1, "ensure": 1},
            # {"exe": True, "time_after": 600, "trigger": 0.025, "ensure": 0.005},
            # {"exe": True, "time_after": 0, "trigger": 0.04, "ensure": 0.010},
            # {"exe": True, "time_after": 600, "trigger": first_trigger, "ensure": first_ensure},
            # {"exe": True, "time_after": 0, "trigger": 0.08, "ensure": 0.05},
            {"exe": True, "time_after": 0, "trigger": 0.15, "ensure": 0.1},
            {"exe": True, "time_after": 0, "trigger": 0.20, "ensure": 0.15},
            {"exe": True, "time_after": 600, "trigger": 0.40, "ensure": 0.35},
            {"exe": True, "time_after": 2 * 5 * 60, "trigger": 0.60, "ensure": 0.55},
            {"exe": True, "time_after": 2 * 5 * 60, "trigger": 0.70, "ensure": 0.65},
            {"exe": True, "time_after": 2 * 5 * 60, "trigger": 0.80, "ensure": 0.75},
            {"exe": True, "time_after": 2 * 5 * 60, "trigger": 0.90, "ensure": 0.85},
            {"exe": True, "time_after": 2 * 5 * 60, "trigger": 1.00, "ensure": 0.95},
        ]
        print("   渡されたLcChange", dic_arr)
        print("　　最終的なLcChange", add)
        self.finalized_order['lc_change'] = dic_arr + add

    def add_lc_change_after_lc(self):
        """
        lcChange = 4で選ばれるもの
        実際の運用をイメージ
        ・LCの取引の後は、そのLCを取り返す動きをする
        """
        lc = self.finalized_order['lc_range']
        self.finalized_order['lc_change'] = [
            {"exe": True, "time_after": 0, "trigger": round(lc * 1.1, 3), "ensure": round(lc * 0.8, 3)},
            {"exe": True, "time_after": 1200, "trigger": 0.018, "ensure": -0.01},
            {"exe": True, "time_after": 1200, "trigger": 0.043, "ensure": 0.021},
            {"exe": True, "time_after": 1200, "trigger": 0.08, "ensure": 0.06},
            # # {"exe": True, "time_after": 0, "trigger": 0.08, "ensure": 0.06},
            # {"exe": True, "time_after": 0, "trigger": 0.10, "ensure": 0.084},
            # # {"exe": True, "time_after": 0, "trigger": 0.12, "ensure": 0.10},
            # # {"exe": True, "time_after": 0, "trigger": 0.14, "ensure": 0.12},
            {"exe": True, "time_after": 0, "trigger": 0.20, "ensure": 0.15},
            # {"exe": True, "time_after": 0, "trigger": 0.25, "ensure": 0.20},
            # {"exe": True, "time_after": 0, "trigger": 0.35, "ensure": 0.33},
            {"exe": True, "time_after": 2 * 5 * 60, "trigger": 0.40, "ensure": 0.38},
            # {"exe": True, "time_after": 2 * 5 * 60, "trigger": 0.50, "ensure": 0.43},
            # {"exe": True, "time_after": 2 * 5 * 60, "trigger": 0.60, "ensure": 0.57},
            {"exe": True, "time_after": 2 * 5 * 60, "trigger": 0.70, "ensure": 0.67},
            # {"exe": True, "time_after": 2 * 5 * 60, "trigger": 0.80, "ensure": 0.77},
            {"exe": True, "time_after": 2 * 5 * 60, "trigger": 0.90, "ensure": 0.87}
        ]

    def add_lc_change_defence(self):
        """
        lcChange = 1で選ばれるもの
        負ける可能性は高くなる可能性高い。
        少しプラスになったらLCの幅を減らしていく手法
        """
        min10 = 60 * 10
        self.finalized_order['lc_change'] = [
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

    def order_finalize(self):
        order_base_info = self.order_base

        # ⓪必須項目がない場合、エラーとする
        if not ('direction' in order_base_info) or not ('decision_price' in order_base_info):
            print("　　　　エラー（項目不足)", 'direction' in order_base_info,
                  'decision_price' in order_base_info, 'decision_time' in order_base_info)
            return -1  # エラー

        # 環境を選択する（通常環境か、両建て環境か）
        if "oa_mode" in order_base_info:
            pass
        else:
            self.order_base['oa_mode'] = self.base_oa_mode  # 何も書かれていない場合は通常環境に入れる

        # 0 注文方式を指定する
        if not ('stop_or_limit' in order_base_info) and not ("type" in order_base_info):
            print(" ★★オーダー方式が入力されていません")
        else:
            if 'type' in order_base_info:
                if order_base_info['type'] == "STOP":
                    order_base_info['stop_or_limit'] = 1
                elif order_base_info['type'] == "LIMIT":
                    order_base_info['stop_or_limit'] = -1
                elif order_base_info['type'] == "MARKET":
                    print(
                        "    Marketが指定されてます。targetは価格が必要です。Rangeを指定すると['stop_or_limit']がないエラーになる可能性がある")
                    pass
            elif 'stop_or_limit' in order_base_info:
                order_base_info['type'] = "STOP" if order_base_info['stop_or_limit'] == 1 else "LIMIT"

        # ①TargetPriceを確実に取得する
        if not ('target' in order_base_info):
            # どっちも入ってない場合、Error
            print("    ★★★target(Rangeか価格か）が入力されていません")
        elif order_base_info['target'] >= self.dependence_price_or_range_criteria:
            # targetが８０以上の数字の場合、ターゲット価格が指定されたとみなす
            order_base_info['position_margin'] = round(
                abs(order_base_info['decision_price'] - order_base_info['target']), 3)
            order_base_info['target_price'] = order_base_info['target']
            # print("    ★★target 価格指定", order_base['target'], abs(order_base['decision_price']), order_base['target_price'])
        elif order_base_info['target'] < self.dependence_price_or_range_criteria:
            # targetが80未満の数字の場合、PositionまでのMarginが指定されたとみなす（負の数は受け入れない）
            # decision_priceにこのマージンを足して（購入方向を自動調整）、算出する。
            if order_base_info['target'] < 0:
                print("   targetに負のRangeが指定されています。ABSで使用します（正の値を計算で調整）")
                order_base_info['target'] = abs(order_base_info['target'])
            order_base_info['position_margin'] = round(order_base_info['target'], 3)
            order_base_info['target_price'] = order_base_info['decision_price'] + \
                                              (order_base_info['target'] * order_base_info['direction'] *
                                               order_base_info[
                                                   'stop_or_limit'])
            # print("    t★arget Margin指定", order_base['target'], abs(order_base['decision_price']), order_base['target_price'])
        else:
            print("     Target_price PositionMarginどっちも入っている")

        # ② TP_priceとTP_Rangeを求める
        if not ('tp' in order_base_info):
            print("    ★★★TP情報が入っていません（利確設定なし？？？）")
            order_base_info['tp_range'] = 0  # 念のため０を入れておく（価格の指定は絶対に不要）
        elif order_base_info['tp'] >= self.dependence_price_or_range_criteria:
            # print("    TP 価格指定")
            # 80以上の数字は、Price値だと認識。Priceの設定と、Rangeの算出と設定を実施。
            #    ただし、偶然Target_Priceと同じになる(秒でTPが入ってしまう)可能性あるため、target_price-価格が0.02未満の場合は調整する。
            if abs(order_base_info['target_price'] - order_base_info['tp']) < self.dependence_tp_lc_margin:
                # 調整を行う（Rangeを最低の0.02に設定し、そこから改めてLC＿Priceを算出する）
                print("  ★★TP価格とTarget価格が同値となったため、調整あり(0.02)")
                order_base_info['tp_range'] = self.dependence_tp_lc_margin
                order_base_info['tp_price'] = round(order_base_info['target_price'] + (
                        order_base_info['tp_range'] * order_base_info['direction']), 3)
            else:
                # 調整なしでOK
                order_base_info['tp_price'] = round(order_base_info['tp'], 3)
                order_base_info['tp_range'] = round(abs(order_base_info['target_price'] - order_base_info['tp']), 3)
        elif order_base_info['tp'] < self.dependence_price_or_range_criteria:
            # print("    TP　Range指定")
            # 80未満の数字は、Range値だと認識。Rangeの設定と、Priceの算出と設定を実施
            order_base_info['tp_price'] = round(
                order_base_info['target_price'] + (order_base_info['tp'] * order_base_info['direction']), 3)
            order_base_info['tp_range'] = round(order_base_info['tp'], 3)

        # ③ LC_priceとLC_rangeを求める
        if not ('lc' in order_base_info):
            # どっちも入ってない場合、エラー
            print("    ★★★LC情報が入っていません（利確設定なし？？）")
        elif order_base_info['lc'] >= self.dependence_price_or_range_criteria:
            # print("    LC 価格指定")
            # 80以上の数字は、Price値だと認識。Priceの設定と、Rangeの算出と設定を実施。
            #     ただし、偶然Target_Priceと同じになる(秒でLCが入ってしまう)可能性あるため、target_price-価格が0.02未満の場合は調整する。
            if abs(order_base_info['target_price'] - order_base_info['lc']) < self.dependence_tp_lc_margin:
                # 調整を行う（Rangeを最低の0.02に設定し、そこから改めてLC＿Priceを算出する）
                print("  ★★LC価格とTarget価格が同値となったため、調整あり(0.02)")
                order_base_info['lc_range'] = self.dependence_tp_lc_margin
                order_base_info['lc_price'] = round(order_base_info['target_price'] - (
                        order_base_info['lc_range'] * order_base_info['direction']), 3)
            else:
                # 調整なしでOK
                order_base_info['lc_price'] = round(order_base_info['lc'], 3)
                order_base_info['lc_range'] = abs(order_base_info['target_price'] - order_base_info['lc'])
        elif order_base_info['lc'] < self.dependence_price_or_range_criteria:
            # print("    LC RANGE指定")
            # 80未満の数字は、Range値だと認識。Rangeの設定と、Priceの算出と設定を実施
            order_base_info['lc_price'] = round(
                order_base_info['target_price'] - (order_base_info['lc'] * order_base_info['direction']), 3)
            order_base_info['lc_range'] = round(order_base_info['lc'], 3)
        # ③-2  lc_priceは処理の中で、上書きされる可能性があるため、同一情報をoriginalとして保存しておく
        order_base_info['lc_price_original'] = order_base_info['lc_price']

        # ④alertの設定を行う（alertは数字か辞書が入る。数字かつ０の場合、辞書の場合、lc_changeの先頭にそれが入る
        if "alert" in order_base_info and "range" in order_base_info['alert']:
            # if isinstance(plan['alert']['range'], int)
            temp_range = round(order_base_info['alert']['range'], 3)
            temp_price = round(order_base_info['target_price'] - (
                        order_base_info['alert']['range'] * order_base_info['direction']), 3)
            # 改めて入れなおしてしまう（別に上書きでもいいんだけど）
            order_base_info['alert'] = {"range": temp_range, "alert_price": temp_price, "time": 0}
        else:
            order_base_info['alert'] = {"range": 0, "time": 0, "alert_price": 0}

        # 最終的にオーダーで必要な情報を付与する(項目名を整えるためにコピーするだけ）。LimitかStopかを算出
        order_base_info['direction'] = order_base_info['direction']
        order_base_info['price'] = order_base_info['target_price']
        order_base_info['order_timeout_min'] = order_base_info[
            'order_timeout_min'] if 'order_timeout_min' in order_base_info else 60

        order_base_info['trade_timeout_min'] = order_base_info[
            'trade_timeout_min'] if 'trade_timeout_min' in order_base_info else 150
        # オーダー即時取得許可は、していなければTrue
        order_base_info['order_permission'] = order_base_info[
            'order_permission'] if 'order_permission' in order_base_info else True
        # 表示形式の問題で、、念のため（機能としては不要）
        order_base_info['decision_price'] = float(order_base_info['decision_price'])

        # ordered_dict = OrderedDict((key, order_base_info[key]) for key in order)
        order_base_info = sorted_dict = {key: order_base_info[key] for key in sorted(order_base_info)}

        # 名前の最後尾に時刻（決心時刻）を付与して、名前で時刻がわかるようにする
        order_base_info['name'] = order_base_info['name'] + "_" + str(gene.delYearDay(order_base_info['decision_time']))

        order_base_info['for_api_json'] = {}

        # ■コマンドラインで見にくいので、表示の順番を変えたい、、、（書き方雑だけど）
        temp = order_base_info['name']  # いったん保存
        del order_base_info["name"]
        order_base_info['name'] = temp

        temp = order_base_info['trade_timeout_min']  # いったん保存
        del order_base_info["trade_timeout_min"]
        order_base_info['trade_timeout_min'] = temp

        temp = order_base_info['order_timeout_min']  # いったん保存
        del order_base_info["order_timeout_min"]
        order_base_info['order_timeout_min'] = temp

        temp = order_base_info['tp_range']  # いったん保存
        del order_base_info["tp_range"]
        order_base_info['tp_range'] = temp

        temp = order_base_info['tp']  # いったん保存
        del order_base_info["tp"]
        order_base_info['tp'] = temp

        temp = order_base_info['price']  # いったん保存
        del order_base_info["price"]
        order_base_info['price'] = temp

        temp = order_base_info['target']  # いったん保存
        del order_base_info["target"]
        order_base_info['target'] = temp

        temp = order_base_info['priority']  # いったん保存
        del order_base_info["priority"]
        order_base_info['priority'] = temp

        temp = order_base_info['position_margin']  # いったん保存
        del order_base_info["position_margin"]
        order_base_info['position_margin'] = temp
        #
        temp = order_base_info['order_permission']  # いったん保存
        del order_base_info["order_permission"]
        order_base_info['order_permission'] = temp

        temp = order_base_info['alert']  # いったん保存
        del order_base_info["alert"]
        order_base_info['alert'] = temp

        # LC_CHANGE
        temp = order_base_info['lc_range']  # いったん保存
        del order_base_info["lc_range"]
        order_base_info['lc_range'] = temp
        # LC
        temp = order_base_info['lc']  # いったん保存
        del order_base_info["lc"]
        order_base_info['lc'] = temp
        # 方向
        temp = order_base_info['direction']  # いったん保存
        del order_base_info["direction"]
        order_base_info['direction'] = temp
        # decisionPrice
        temp = order_base_info['decision_price']  # いったん保存
        del order_base_info["decision_price"]
        order_base_info['decision_price'] = temp
        # lc_Change_type
        temp = order_base_info['lc_change_type']  # いったん保存
        del order_base_info["lc_change_type"]
        order_base_info['lc_change_type'] = temp
        # lc_price_original
        temp = order_base_info['lc_price_original']  # いったん保存
        del order_base_info["lc_price_original"]
        order_base_info['lc_price_original'] = temp
        # ref
        temp = order_base_info['ref']  # いったん保存
        del order_base_info["ref"]
        order_base_info['ref'] = temp

        # LCChange(これが最後尾にしたい）
        if "lc_change" in order_base_info:
            temp = order_base_info['lc_change']  # いったん保存
            del order_base_info["lc_change"]
            order_base_info['lc_change'] = temp

        if "stop_or_limit" in order_base_info:
            temp = order_base_info['stop_or_limit']  # いったん保存
            del order_base_info["stop_or_limit"]
            order_base_info['stop_or_limit'] = temp

        return order_base_info

