import fGeneric as gene
import tokens as tk
import send_notice as notice
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
        self.pair_info = gene.currency_pair(self.instrument)
        self.base_oa_mode = 2  # デフォルトの口座は2(両建て用）
        self.basic_unit = 10000
        self.basic_lc_range = 1  # 1円
        self.trade_timeout_min_base = 240
        self.order_timeout_min_base = 60
        self.lc_change_base = 3  # ベースは０（LCchangeなし）
        # 判定に利用する、初期値
        self.u = self.pair_info.round_keta  # round時の有効桁数
        self.dependence_tp_lc_margin_pips = 1
        self.dependence_tp_lc_margin = self.pair_info.pips_to_price(self.dependence_tp_lc_margin_pips)  # targetとTP/LCとの間が極端に狭いときはウォーニングを出す

        # ■■
        self.data = {}  # Oanda API用のにはこのJsonを送信することでオーダーを発行可能
        self.exe_order_plan = {}
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
        self.lc_change = []
        self.linkage_order_classes = []
        self.lc_change_candle_type = ""
        self.memo = ""

        # 色々な情報を受け取っていれば、それを取得する(ただし、エラー防止のため、インスタンス変数で明示的に損z内を示す）
        self.candle_analysis = None
        self.move_ave = 0
        if "candle_analysis_class" in order_json:
            # print("candle_analysis_classがあるよ", round(order_json['candle_analysis_class'].candle_class.cal_move_ave(1), 3))
            self.move_ave = order_json['candle_analysis_class'].candle_meta_class.cal_move_ave(1)
            self.candle_analysis = order_json['candle_analysis_class']
        else:
            notice.line_send("【注意】キャンドルアナリシスが添付されていない注文が発生")
            print("candle_analysis_classがない")
            print(order_json)

        # ■■処理
        self.check_order_json()  # 渡された引数に、必要項目の抜けがある場合、ここで表示
        self.order_finalize_new()  # 管理に必要な情報を、計算で補完する。
        # self.lc_change_control()  # lc_changeを付与する。
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
                    "price": self.pair_info.price_to_str(self.target_price),  # 小数点3桁の文字列（それ以外はエラーとなる）
                    "takeProfitOnFill": {
                        "timeInForce": "GTC",
                        "price": self.pair_info.price_to_str(self.tp_price)  # 小数点3桁の文字列（それ以外はエラーとなる）
                    },
                    "stopLossOnFill": {
                        "timeInForce": "GTC",
                        "price": self.pair_info.price_to_str(self.lc_price)  # 小数点3桁の文字列（それ以外はエラーとなる）
                    },
                    # "trailingStopLossOnFill": {
                    #     "timeInForce": "GTC",
                    #     "distance": "0"  # 5pips以上,かつ,小数点3桁の文字列
                    # }
                }
            }
        # ■ポジション管理用含めた情報
        self.exe_order_plan = {
            "decision_time": self.decision_time,
            "units": self.units,
            "pair": self.instrument,
            "direction": self.direction,
            "target_price": self.pair_info.round_price(self.target_price),
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
            "move_ave": self.move_ave,  # 参考情報だが追加（無いとLineSendでエラーになるが、オーダーには影響ない）
            "candle_lc_change_type": "5M",  # lc_changeで利用する足,
            "memo": self.memo
        }

        # クラスにある情報を明示しておく（混乱防止用で、冗長な書き方）
        if "candle_analysis_class" in self.order_json:
            self.candle_analysis = self.order_json['candle_analysis_class']
        else:

            self.candle_analysis = None  # 基本、初回の強制オーダー以外では、candle_analysisは入ってくる

        # 他に対外的に使うやつ
        # self.linkage_classes = self.linkage_classes  # 覚書

    def update_plan(self, order_json):
        self.order_json_original = order_json  # オーダー用json
        self.order_json = self.order_json_original

        # ■■
        # 色々なオーダーに必要になる初期値
        self.instrument = "USD_JPY"
        self.pair_info = gene.currency_pair(self.instrument)
        self.base_oa_mode = 2  # デフォルトの口座は2(両建て用）
        self.basic_unit = 10000
        self.basic_lc_range = 1  # 1円
        self.trade_timeout_min_base = 240
        self.order_timeout_min_base = 60
        self.lc_change_base = 3  # ベースは０（LCchangeなし）
        # 判定に利用する、初期値
        self.u = self.pair_info.round_keta  # round時の有効桁数
        self.dependence_tp_lc_margin_pips = 1
        self.dependence_tp_lc_margin = self.pair_info.pips_to_price(self.dependence_tp_lc_margin_pips)  # targetとTP/LCとの間が極端に狭いときはウォーニングを出す

        # ■■
        # OandaAPI用のにはこのJsonを送信することでオーダーを発行可能
        self.data = {}
        self.exe_order_plan = {}
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
        self.lc_change = []
        self.linkage_order_classes = []
        self.lc_change_candle_type = ""

        # 色々な情報を受け取っていれば、それを取得する(ただし、エラー防止のため、インスタンス変数で明示的に損z内を示す）
        self.candle_analysis = None
        self.move_ave = 0
        if "candle_analysis_class" in order_json:
            # print("candle_analysis_classがあるよ", round(order_json['candle_analysis_class'].candle_class.cal_move_ave(1), 3))
            self.move_ave = order_json['candle_analysis_class'].candle_meta_class.cal_move_ave(1)
            self.candle_analysis = order_json['candle_analysis_class']
        else:
            notice.line_send("【注意】キャンドルアナリシスが添付されていない注文が発生 in updatePlan")
            print("candle_analysis_classがない")
            print(order_json)

        # ■■処理
        self.check_order_json()  # 渡された引数に、必要項目の抜けがある場合、ここで表示
        self.order_finalize_new()  # 管理に必要な情報を、計算で補完する。
        self.lc_change_control()  # lc_changeを付与する。
        self.make_json_from_instance()  # オーダー可能な情報を生成する。

    def check_order_json(self):
        """
        オーダーの中身を確認し、オーダーに必要な情報が足りているかを確認する

        最低限必要な情報
        order_base_dic = {
            # 必須項目群
            "target": 0.00,  # 通貨ペアごとの価格レンジ内なら価格、それ以外はRange。Rangeの場合、decision_priceを基準にPrice(APIに必須）に換算される。
            "type": "STOP",  # 文字列。計算時は数字のほうが楽なため、stop_or_limit変数で数字に置き換えたものも算出（finalize関数)
            "units": OrderCreateClass.basic_unit,
            "expected_direction": 1,
            "tp": 0.9,  # 通貨ペアごとの価格レンジ内なら価格、それ以外ならRange(target価格+tpRange。正の値）とする
            "lc": 0.03,  # 通貨ペアごとの価格レンジ内なら価格、それ以外ならRange(target価格+lcRange。正の値）とする
            'priority': 0,
            "decision_price": 0,  # "Now"という文字列の場合、この関数で即時取得する。targetがRangeの場合必須。
            "decision_time": "",
            "name": "",
            "order_timeout_min": 0,
        }

        order_base_dic = {
            "target_price": 価格で指定（target_marginのいずれかが必要。両方入っている場合、target_price優先）,
            "target_margin": pipsで指定。
            "type": "STOP",  # 文字列。計算時は数字のほうが楽なため、stop_or_limit変数で数字に置き換えたものも算出（finalize関数)
            "units": OrderCreateClass.basic_unit,
            "expected_direction": 1,
            "tp_price": 価格で指定。tp_rangeのいずれかが必要。両方入っている場合、tp_priceを優先
            "tp_range": pipsで指定
            "lc_price": 価格で指定。lc_rangeのいずれかが必要。両方入っている場合、lc_priceを優先
            "lc_range": pipsで指定
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

        # 通貨の登録(何もなかったらドル円)
        self.instrument = order_json['pair'] if "pair" in order_json else self.instrument
        self.pair_info = gene.currency_pair(self.instrument)
        self.u = self.pair_info.round_keta
        self.dependence_tp_lc_margin = self.pair_info.pips_to_price(self.dependence_tp_lc_margin_pips)

        # priority
        self.priority = order_json['priority']

        # Unitsがない場合は初期値を入れる
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
            if self.pair_info.is_price(order_json['target']):
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
            if self.pair_info.is_price(order_json['tp']):
                self.tp_range = self.pair_info.round_price(abs(self.target_price - order_json['tp']))  # Rangeを算出
                self.tp_price = self.pair_info.round_price(order_json['tp'])  # Priceはそのまま代入
            # レンジで指定されている場合
            else:
                self.tp_range = self.pair_info.round_price(order_json['tp'])  # Rangeはそのまま代入
                self.tp_price = self.pair_info.round_price(self.target_price + (self.tp_range * self.direction))

            # TPRangeが狭すぎる場合はウォーニングを出す
            if self.tp_range < self.dependence_tp_lc_margin:
                print("  ★★TP価格とTarget価格が極端に近いため、注意", self.tp_range, self.tp_price, self.target_price)

        # LC情報を取得する（LCの値は、正の値で指定される。クライテリアより小さい値ならRange指定、それ以上は価格直接指定と読み替える）
        if 'lc' in order_json:
            # 価格で指定されている場合
            if self.pair_info.is_price(order_json['lc']):
                self.lc_range = self.pair_info.round_price(abs(self.target_price - order_json['lc'])) # Rangeを算出
                self.lc_price = self.pair_info.round_price(order_json['lc'])  # Priceはそのまま代入
            # レンジで指定されている場合
            else:
                self.lc_range = self.pair_info.round_price(order_json['lc'])  # Rangeはそのまま代入
                self.lc_price = self.pair_info.round_price(self.target_price - (self.lc_range * self.direction))

            # LCRangeが狭すぎる場合はウォーニングを出す
            if self.lc_range < self.dependence_tp_lc_margin:
                print("  ★★LC価格とTarget価格が極端に近いため、注意", self.lc_range, self.lc_price, self.target_price)

        if "risk_yen" in order_json:
            self.risk_yen = float(order_json["risk_yen"])
            self.usd_jpy_rate = order_json.get("usd_jpy_rate")
            self.recalculate_units_from_risk()
        elif "units" in order_json:
            if order_json['units'] < 100:
                self.units = round(self.basic_unit * order_json['units'])
                self.units_adj = order_json['units']
            else:
                self.units = order_json["units"]
                self.units_adj = 1
        else:
            self.units = self.basic_unit

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
            self.order_permission = order_json['order_permission']  # 指定ある場合は指定に従う。
        else:
            self.order_permission = True  # 指定がなければ即時オーダーが基本

        # lc_change_candleで利用する足の設定
        if 'lc_change' in order_json:
            if order_json['lc_change'] is None:
                # ほぼ無効の物を入れておく
                self.lc_change = [{"exe": False, "time_after": 605, "trigger": 1, "ensure": 1 * 0.8}]
            else:
                self.lc_change = order_json['lc_change']
        else:
            self.lc_change = [{"exe": False, "time_after": 605, "trigger": 1, "ensure": 1 * 0.8}]

        # lc_change_candleで利用する足の設定
        if 'lc_change_candle_type' in order_json:
            self.lc_change_candle_type = order_json['lc_change_candle_type']
        else:
            self.lc_change_candle_type = "M5"

        # メモ
        if 'memo' in order_json:
            self.memo = order_json['memo']
        else:
            self.memo = ""

        # ref(無いと、検証の時にエラーになる)
        if "ref" in order_json:
            pass
        else:
            pass
            # order_json['ref'] = {"move_ave": 0, "peak1_target_gap": 0}

    def recalculate_units_from_risk(self):
        """Calculate units from the finalized LC range and risk amount."""
        if not getattr(self, "risk_yen", None):
            return
        if not self.lc_range:
            raise ValueError("risk_yenでunitsを計算するにはlcが必要です")

        self.units = gene.calculate_units(
            self.pair_info,
            self.lc_range,
            self.risk_yen,
            "l",
            self.usd_jpy_rate,
        )
        self.units_adj = 1

        if self.exe_order_plan:
            self.exe_order_plan["units"] = self.units
            self.exe_order_plan["risk_yen"] = self.risk_yen
        if self.data.get("order"):
            self.data["order"]["units"] = str(self.units * self.direction)

    def pips(self, pips, pair="dy"):
        """
        pipsを受け取り、価格で返却する。pips_exchangeに関数名にしたかったけど、式の途中で使うため短めに。
        """

        return self.pair_info.pips_to_price(pips)



    def add_linkage(self, another_order_class):
        # print("OrderCreate334")
        # print(self.linkage_classes)
        self.linkage_order_classes.append(another_order_class)
