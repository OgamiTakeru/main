import threading  # 定時実行用
import time
import datetime

# 自作ファイルインポート
import tokens as tk  # Token等、各自環境の設定ファイル（git対象外）
import classOanda as classOanda
import classPosition as classPosition  # とりあえずの関数集
import classOrderCreate as OCreate
import fGeneric as f
import fAnalysis_order_Main as am
import classCandleAnalysis as ca
import classPositionControl as classPositionControl
import copy

class main():
    def __init__(self):
        print("Mainインスタンスの生成")
        self.base_oa = classOanda.Oanda(tk.accountIDl2, tk.access_tokenl, tk.environmentl)
        self.exe_mode = tk.environmentl

        # ■変数の宣言
        # 変更なし群
        self.ARROW_SPREAD = 0.011  # 実行を許容するスプレッド　＠ここ以外で変更なし
        self.NEED_DF_NUM = 250  # 解析に必要な行数（元々５０行だったが、１００にしたほうが、取引回数が多くなりそう）
        # 時刻系
        self.now = 0
        self.now_str = 0
        self.time_hour = 0  # 現在時刻の「時」のみを取得
        self.time_min = 0  # 現在時刻の「分」のみを取得
        self.time_sec = 0  # 現在時刻の「秒」のみを取得
        self.latest_exe_time = datetime.datetime.now().replace(microsecond=0)  # 最終実行時刻を取得しておく
        self.past_time_from_latest_mode1_exe = 0
        start_time = datetime.datetime.now().replace(microsecond=0)  # 現在の時刻を取得
        self.start_time_str = str(start_time.month).zfill(2) + str(start_time.day).zfill(2) + "_" + \
             str(start_time.hour).zfill(2) + str(start_time.minute).zfill(2)
        # 価格系
        self.now_price_mid = 0
        self.now_spread = 0

        # データ系
        self.candleAnalysisClass = None

        # 回数カウント系
        self.trade_num = 1

        # フラグ系
        self.first_exe = True  # 初回の実行
        self.midnight_close_flag = 0  # 深夜突入時に一回だけポジション等の解消を行うフラグ　＠time_manageのみで変更あり

        # ■■■処理の開始
        # ■ポジションクラスの生成
        self.positions_control_class = classPositionControl.position_control(True)  # ポジションリストの用意
        # self.positions_control_class.reset_all_position()  # 開始時は全てのオーダーを解消し、初期アップデートを行う
        self.positions_control_class.reset_all_position()
        self.positions_control_class.catch_up_position_and_del_order()

    def exe_loop(self, interval, wait=True):
        """
        :param interval: 何秒ごとに実行するか
        :param fun: 実行する関数（この関数への引数は与えることが出来ない）
        :param wait: True固定
        :return: なし
        """
        base_time = time.time()
        while True:
            # 現在時刻の取得
            self.get_time_info()
            # t = threading.Thread(target=fun)
            t = threading.Thread(target=self.exe_manage)
            t.start()
            if wait:  # 時間経過待ち処理？
                t.join()
            # 待機処理
            next_time = ((base_time - time.time()) % 1) or 1
            time.sleep(next_time)

    def get_time_info(self):
        self.now = datetime.datetime.now().replace(microsecond=0)  # 現在の時刻を取得
        self.now_str = str(self.now.month).zfill(2) + str(self.now.day).zfill(2) + "_" + \
                     str(self.now.hour).zfill(2) + str(self.now.minute).zfill(2) + "_" + str(self.now.second).zfill(2)
        self.time_hour = self.now.hour  # 現在時刻の「時」のみを取得
        self.time_min = self.now.minute  # 現在時刻の「分」のみを取得
        self.time_sec = self.now.second  # 現在時刻の「秒」のみを取得

    def force_order(self):
        # ■■オーダーの生成
        price_dic = self.base_oa.NowPrice_exe("USD_JPY")
        if price_dic['error'] == -1:  # APIエラーの場合はスキップ
            print("API異常発生の可能性")
            return -1  # 終了
        else:
            price_dic = price_dic['data']
        # 値たち
        current_price = price_dic['mid']  # 念のために保存しておく（APIの回数減らすため）
        dir = -1
        lc_range = 0.015
        tp_price = 0.01
        # オーダー
        order_class = OCreate.Order({
            "name": "強制オーダーテスト",
            "current_price": current_price,
            "target": 0.02,
            "direction": 1,
            "type": "MARKET",
            "tp": 0.1,
            "lc": 0.1,
            "lc_change": 0,
            "units": 150,
            "priority": 1,
            "decision_time": '2025/07/11 23:30:00',
        })
        order_class2 = OCreate.Order({
            "name": "強制オーダーテスト逆",
            "current_price": current_price,
            "target": 0.03,
            "direction": -1,
            "type": "STOP",
            "tp": 0.1,
            "lc": 1,
            "lc_change": 0,
            "units": 250,
            "priority": 1,
            "decision_time": '2025/07/11 23:30:00',
        })
        order_class.add_linkage(order_class2)
        order_class2.add_linkage(order_class)

        # ■オーダーの発行
        print("test")
        exe_res = self.positions_control_class.order_class_add([order_class, order_class2])
        if exe_res == 0:
            tk.line_send(" オーダー発行失敗　main 131")
        else:
            tk.line_send("★★★オーダー発行", "ForceOrder回目: ", " 　　　", exe_res,
                         ", 現在価格:", self.now_price_mid, "スプレッド", str(self.now_spread),
                         "直前の結果:", classPosition.order_information.before_latest_plu, ",開始時間",
                         self.start_time_str)

    # def get_df_data(self):
    #     """
    #     データを取得する
    #     """
    #     # 5分足のデータ
    #     d5_df_res = self.base_oa.InstrumentsCandles_multi_exe("USD_JPY",
    #                                             {"granularity": "M5", "count": self.need_df_num},
    #                                             1)  # 時間昇順(直近が最後尾）
    #     if d5_df_res['error'] == -1:
    #         print("error Candle")
    #         tk.line_send("5分ごと調査最初のデータフレーム取得に失敗（エラー）")
    #         return -1
    #     else:
    #         d5_df_latest_bottom = d5_df_res['data']
    #     tc = (datetime.datetime.now().replace(microsecond=0) - classOanda.str_to_time(
    #         d5_df_latest_bottom.iloc[-1]['time_jp'])).seconds
    #     if tc > 420:  # 何故か直近の時間がおかしい時がる
    #         print(" ★★直近データがおかしい", d5_df_latest_bottom.iloc[-1]['time_jp'], f.now())
    #     if len(d5_df_latest_bottom) <= 10:
    #         print("　取得したデータフレームの行数がおかしい", len(d5_df_latest_bottom))
    #         print(d5_df_latest_bottom)
    #         print("ｄｆここまで")
    #     else:
    #         print("取得したデータは正常と思われる")
    #
    #     self.d5_df = d5_df_latest_bottom.sort_index(ascending=False)  # 直近が上の方にある＝時間降順に変更
    #     self.d5_df.to_csv(tk.folder_path + 'main_data5.csv', index=False, encoding="utf-8")  # 直近保存用
    #
    #     # 60分足のデータ
    #     d60_df_res = self.base_oa.InstrumentsCandles_multi_exe("USD_JPY",
    #                                             {"granularity": "H1", "count": self.need_df_num},
    #                                             1)  # 時間昇順(直近が最後尾）
    #     if d60_df_res['error'] == -1:
    #         print("error Candle")
    #         tk.line_send("5分ごと調査最初のデータフレーム取得に失敗（エラー）")
    #         return -1
    #     else:
    #         d60_df_latest_bottom = d60_df_res['data']
    #     tc = (datetime.datetime.now().replace(microsecond=0) - classOanda.str_to_time(
    #         d60_df_latest_bottom.iloc[-1]['time_jp'])).seconds
    #     if tc > 420:  # 何故か直近の時間がおかしい時がる
    #         print(" ★★直近データがおかしい", d60_df_latest_bottom.iloc[-1]['time_jp'], f.now())
    #     if len(d60_df_latest_bottom) <= 10:
    #         print("　取得したデータフレームの行数がおかしい", len(d60_df_latest_bottom))
    #         print(d60_df_latest_bottom)
    #         print("ｄｆここまで")
    #     else:
    #         print("取得したデータは正常と思われる")
    #
    #     self.d60_df = d60_df_latest_bottom.sort_index(ascending=False)  # 直近が上の方にある＝時間降順に変更
    #     self.d60_df.to_csv(tk.folder_path + 'main_data60.csv', index=False, encoding="utf-8")  # 直近保存用

    def mode1(self):
        """
        5分に一度行わる処理
        """
        print("■■■■■■5分ごと調査■■■■", self.now, self.past_time_from_latest_mode1_exe)  # 表示用（実行時）

        # ■処理
        if self.first_exe:
            # 初回は、manageで取得したデータで実行する
            pass
        else:
            self.positions_control_class.all_update_information()  # positionの更新
            self.candleAnalysisClass = ca.candleAnalysis(self.base_oa, 0)  # 現在時刻（０）でデータ取得
            # self.get_df_data()  # データの取得

        # ■調査実行
        analysis_result_instance = am.wrap_all_analysis(self.candleAnalysisClass)
        # ■ オーダー発行
        if not analysis_result_instance.take_position_flag:
            # 発注がない場合は、終了 (ポケ除け的な部分）
            pass
        else:
            # オーダーを登録＆発行する
            exe_res = self.positions_control_class.order_class_add(analysis_result_instance.exe_order_classes)
            if exe_res == 0:
                pass
                # tk.line_send(" オーダー発行せず　or 失敗　main 175")
            else:
                tk.line_send("★★★オーダー発行", self.trade_num, "回目: ", " 　　　", exe_res,
                             ", 現在価格:", self.now_price_mid, "スプレッド", str(self.now_spread),
                             "直前の結果:", classPosition.order_information.before_latest_plu, ",開始時間",
                             self.start_time_str)
                self.trade_num = self.trade_num + 1

        # ■最終実行時刻の更新
        self.latest_exe_time = datetime.datetime.now().replace(microsecond=0)  # 最終実行時刻を取得しておく

    def mode2(self):
        self.positions_control_class.all_update_information(self.candleAnalysisClass)  # positionの更新
        life_check_res = self.positions_control_class.life_check()

        if life_check_res['life_exist']:
            # オーダー以上がある場合。表示用（１分に１回表示させたい）
            self.positions_control_class.linkage_control()  # positionの更新
            c = ""
            temp_date = datetime.datetime.now().replace(microsecond=0)  # 秒を算出
            if 0 <= int(temp_date.second) < 2:  # ＝１分に一回(毎分１秒～２秒の間)
                current_positions = self.positions_control_class.position_check()
                print("■■■Mode2(いずれかポジション有)", f.now(), "これは１分に１回表示")
                if len(current_positions['open_positions']) > 0:
                    # ポジションがある場合、表示する情報を組み立てる。
                    info = []
                    for i, item in enumerate(current_positions['open_positions']):
                        name = item['name']
                        pr = item['priority']
                        rpl = item["t_time_past_sec"]
                        pl = item['pl']
                        if len(current_positions['watching_list']) > 0:
                            w = ", ".join(["|".join(map(str, d.values())) for d in current_positions['watching_list'][i]])
                        else:
                            w = ""
                        c = c + "   " + name + "(priority:" + str(pr) + ",t_pass_sec:" + str(rpl) + ",pl:" + str(pl) + ",w:" + w + ")"
                print("   ⇒", c)
                # print("     ", life_check_res['one_line_comment'])

    def exe_manage(self):
        """
        時間やモードによって、実行関数等を変更する
        :return:
        """
        # ■■実行しない場合を列挙
        # ■土日は実行しない（ループにはいるが、API実行はしない）
        if self.now.weekday() == 6:
            # print("■土日の為API実行無し")
            return 0
        elif self.now.weekday() == 5:
            if self.time_hour >= 4:
                if self.time_hour ==4 and self.time_min == 0 and self.time_sec <=2:
                    print("■土曜の朝4時で終了（ポジションは開放しない・・？）(4時０分2秒まで表示)")
                return 0
        elif self.now.weekday() == 0:
            if self.time_hour <= 7:
                if self.time_min == 0 and self.time_sec <=1:
                    print("■月曜になった深夜～朝までは実行無し", self.time_hour)
                return 0

        # ■深夜帯(6時～7時)は実行しない　（ポジションやオーダーも全て解除）
        # if 6 <= self.time_hour <= 7:
        #     if self.midnight_close_flag == 0:  # 繰り返し実行しないよう、フラグで管理する
        #         # self.positions_control_class.reset_all_position()
        #         tk.line_send("■深夜のオーダー解消を実施")
        #         self.base_oa.OrderCancel_All_exe()
        #         self.midnight_close_flag = 1  # 実施済みフラグを立てる
        #     return 0
        # else:
        #     self.midnight_close_flag = 0  # 実行可能開始時以降は深夜フラグを解除（毎回やってしまうけどいいや）

        # ■時間内でスプレッドが広がっている場合は強制終了し実行しない　（現価を取得しスプレッドを算出する＋グローバル価格情報を取得する）
        price_dic = self.base_oa.NowPrice_exe("USD_JPY")
        if price_dic['error'] == -1:  # APIエラーの場合はスキップ
            print("API異常発生の可能性")
            return -1  # 終了
        else:
            price_dic = price_dic['data']
            if price_dic['spread'] > self.ARROW_SPREAD:
                # print("    ▲スプレッド異常", self.now, price_dic['spread'])
                return -1  # 強制終了
            self.now_price_mid = price_dic['mid']  # 念のために保存しておく（APIの回数減らすため）
            self.now_spread = price_dic['spread']

        # ■直近の検討データの取得　　　メモ：data_format = '%Y/%m/%d %H:%M:%S'
        # 直近の実行したローソク取得からの経過時間を取得する（秒単位で２連続の取得を行わないようにするためマージン）
        if not self.first_exe:
            # 初回ではない場合（通常はこっち）
            self.past_time_from_latest_mode1_exe = (
                (datetime.datetime.now().replace(microsecond=0) - self.latest_exe_time).seconds)

            # ↓秒指定だと飛ぶので、前回から●秒経過&秒数に余裕を追加
            if self.time_min % 5 == 0 and 6 <= self.time_sec < 30 and self.past_time_from_latest_mode1_exe > 60:
                print("  ")
                print("  ")
                self.mode1()  # ★★Mode1の実行

            if self.time_min % 1 == 0 and self.time_sec % 2 == 0:  # 高頻度での確認事項（キャンドル調査時のみ飛ぶ）
                self.mode2()  #

        else:
            # ■　初回だけ実行と同時に行う特殊処理
            print("■■■初回", self.exe_mode)  # 表示用（実行時）
            tk.line_send("start")

            # 現時刻を使う
            self.candleAnalysisClass = ca.candleAnalysis(self.base_oa, 0)  # 現在時刻（０）でデータ取得
            # 指定時刻を使う
            # self.candleAnalysisClass = ca.candleAnalysis(self.base_oa, datetime.datetime(2025, 9, 1, 8, 5, 6))
            self.mode1()

            # 強制オーダーを入れる場合は、以下コメントイン
            # self.force_order()
            # self.positions_control_class.print_classes_and_count()

            # 初回実行の終了フラグ
            self.first_exe = False
            print("ーーー初回の処理終了ーーー")


main_exe = main()  # インスタンスの生成
main_exe.exe_loop(1)  # ループ処理の実行
