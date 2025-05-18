import datetime
from datetime import timedelta

import classOanda
import pandas as pd
import tokens as tk
import fGeneric as gene
import gc
import fCommonFunction as cf
import sys
import classPeaks as cpk


class Inspection:
    def __init__(self, is_exist_data, ):
        self.gl_exist_data = is_exist_data
        self.gl_jp_time = datetime.datetime(2025, 5, 17, 10, 40, 0)  # TOの時刻
        self.gl_haba = "M5"
        self.gl_m5_count = 4000
        self.gl_m5_loop = 1
        self.memo = " 直近分でテスト"
        self.memo = "少量24_25 " + self.memo

        # gl_exist_date = Trueの場合の読み込みファイル
        # ■■■メイン（5分足や30分足）
        self.gl_main_csv_path = 'C:/Users/taker/OneDrive/Desktop/oanda_logs/202503_m5_df.csv'  # 大量データ(25)5分
        # ■■■検証用5秒足
        self.gl_s5_csv_path = 'C:/Users/taker/OneDrive/Desktop/oanda_logs/202503_s5_df.csv'  # 大量データ(25)5秒
        # 最初の一つをインスタンスを生成する  150.284 149.834
        gl_classes = []
        pd.set_option('display.max_columns', None)

        # グローバルでの宣言
        self.oa = classOanda.Oanda(tk.accountIDl, tk.access_tokenl, "live")  # クラスの定義
        # データ取得用
        self.gl_need_to_analysis = 60  # 調査に必要な行数
        self.gl_d5_df = pd.DataFrame()
        self.gl_d5_df_r = pd.DataFrame()
        self.gl_s5_df = pd.DataFrame()
        self.gl_inspection_base_df = pd.DataFrame()
        self.gl_actual_start_time = 0
        self.gl_actual_end_time = 0
        self.gl_5m_start_time = 0
        self.gl_5m_end_time = 0
        self.gl_actual_5m_start_time = 0
        # 結果格納用
        self.gl_total = 0  # トータル価格
        self.gl_total_per_units = 0  # トータル価格（ユニットによらない）
        self.gl_not_overwrite_orders = []
        self.gl_results_list = []
        self.gl_order_list = []
        # 時間計測用（データの保存用等）
        self.gl_start_time = datetime.datetime.now()  # 検証時間の計測用
        self.gl_now = datetime.datetime.now().replace(microsecond=0)  # 現在の時刻を取得
        self.gl_start_time_str = str(self.gl_now.month).zfill(2) + str(self.gl_now.day).zfill(2) + "_" + \
                            str(self.gl_now.hour).zfill(2) + str(self.gl_now.minute).zfill(2) + str(self.gl_now.second).zfill(2)

    def reset(self):
        # 情報の完全リセット（テンプレートに戻す）
        print("    OrderClassリセット")
        self.name = ""
        self.priority = 0  # このポジションのプライオリティ
        # self.is_live = True  # 本番環境か練習か（Boolean）　⇒する必要なし
        self.life = False
        self.plan = {}  # plan(name,units,direction,tp_range,lc_range,type,price,order_permission,margin,order_timeout_min)
        # オーダー情報(オーダー発行時に基本的に上書きされる）
        self.o_id = 0
        self.o_time = 0
        self.o_state = ""
        self.o_time_past_sec = 0  # オーダー発行からの経過秒
        # トレード情報
        self.t_id = 0
        self.t_state = ""
        self.t_type = ""  # 結合ポジションか？　plantとinitialとcurrentのユニットの推移でわかる？
        self.t_initial_units = 0  # Planで代用可？少し意味異なる？
        self.t_current_units = 0
        self.t_time = 0
        self.t_time_past_sec = 0
        self.t_execution_price = 0  # 約定価格
        self.t_unrealize_pl = 0
        self.t_realize_pl = 0
        self.t_pl_u = 0
        self.t_close_time = 0
        self.t_close_price = 0
        self.already_offset_notice = False  # オーダーが既存のオーダーを完全相殺し、さらにポジションもある場合の通知を2回目以降やらないため
        # 経過時間管理
        self.order_timeout_min = 45  # 分単位で指定
        self.trade_timeout_min = 50
        self.over_write_block = False
        # 勝ち負け情報更新用
        self.win_lose_border_range = 0  # この値を超えている時間をWin、以下の場合Loseとする
        self.win_hold_time_sec = 0
        self.lose_hold_time_sec = 0
        self.win_max_plu = 0
        self.lose_max_plu = 0

        # ロスカット変更情報
        self.lc_change_dic = {}  # 空を持っておくだけ
        self.lc_change_from_candle_lc_price = 0
        self.lc_change_num = 0  # LCChangeまたはLCChangeCandleのいずれかの執行でTrueに変更される
        self.counter_order_peace = {}
        self.counter_order_done = False
        self.lc_change_less_minus_done = False

        # オーダーが、オーダー情報なし、トレード情報なしとなっても、この回数分だけチェックする(時間差がありうるため）
        self.try_update_limit = 2
        self.try_update_num = 0

    def get_data(self):
        """
        データを取得し、グローバル変数に格納する
        """
        # 解析のための「5分足」のデータを取得
        # gl_exist_data = True  # グローバルに変更
        if self.gl_exist_data:
            # 既存の5分足データを取得
            gl_d5_df = pd.read_csv(gl_main_csv_path, sep=",", encoding="utf-8")
            gl_5m_start_time = gl_d5_df.iloc[0]['time_jp']
            gl_5m_end_time = gl_d5_df.iloc[-1]['time_jp']
            gl_actual_5m_start_time = gl_d5_df.iloc[gl_need_to_analysis]['time_jp']
            gl_d5_df_r = gl_d5_df.sort_index(ascending=False)  # 時系列を逆にしたものが解析用！
            print(gl_d5_df_r.head(5))
            print(gl_d5_df_r.tail(5))
            print("5分足での取得時刻は", gl_5m_start_time, "-", gl_5m_end_time, len(gl_d5_df_r), "行")
            print("実際の解析時間は", gl_d5_df.iloc[gl_need_to_analysis]['time_jp'], "-", gl_5m_end_time)
            # 既存の5秒足データを取得
            gl_s5_df = pd.read_csv(gl_s5_csv_path, sep=",", encoding="utf-8")
            start_s5_time = gl_s5_df.iloc[0]['time_jp']
            end_s5_time = gl_s5_df.iloc[-1]['time_jp']
            print("検証用データ")
            print("検証時間の総取得期間は", start_s5_time, "-", end_s5_time, len(gl_s5_df), "行")

        else:
            # 5分足データを新規で取得
            euro_time_datetime = gl_jp_time - datetime.timedelta(hours=9)
            euro_time_datetime_iso = str(euro_time_datetime.isoformat()) + ".000000000Z"  # ISOで文字型。.0z付き）
            params = {"granularity": gl_haba, "count": gl_m5_count, "to": euro_time_datetime_iso}  # コツ　1回のみ実行したい場合は88
            data_response = oa.InstrumentsCandles_multi_exe("USD_JPY", params, gl_m5_loop)
            gl_d5_df = data_response['data']
            gl_d5_df_r = gl_d5_df.sort_index(ascending=False)  # 時系列を逆にしたものが解析用！
            gl_5m_start_time = gl_d5_df.iloc[0]['time_jp']
            gl_5m_end_time = gl_d5_df.iloc[-1]['time_jp']
            gl_actual_5m_start_time = gl_d5_df.iloc[gl_need_to_analysis]['time_jp']
            gl_d5_df.to_csv(tk.folder_path + gene.str_to_filename(gl_5m_start_time) + '_test_m5_df.csv', index=False,
                            encoding="utf-8")
            print("解析用5分足データ")
            print("5分足での取得時刻は", gl_5m_start_time, "-", gl_5m_end_time, len(gl_d5_df), "行")
            print("(実際の解析時間は", gl_actual_5m_start_time, "-", gl_5m_end_time)

            # 5秒足データを取得
            if gl_haba == "M5":
                over5000judge = 60
            elif gl_haba == "M30":
                over5000judge = 360
            else:
                over5000judge = 60

            end_time_euro = gl_d5_df_r.iloc[0]['time']  # Toに入れるデータ（これは解析用と一致させたいため、基本固定）
            all_need_row = gl_m5_count * 60 * gl_m5_loop
            if gl_m5_count * over5000judge > 5000:
                # 5000を超えてしまう場合はループ処理が必要(繰り返しデータで使うため、少し多めに取ってしまう。5000単位をN個の粒度）
                loop_for_5s = math.ceil(all_need_row / 5000)
                s5_count = 5000
                trimming = (5000 * loop_for_5s - all_need_row) + (gl_need_to_analysis * 60)
                print("   5S検証：必要な行", all_need_row, "5000行のループ数", loop_for_5s, "多く取得できる行数",
                      5000 * loop_for_5s - all_need_row)
            else:
                # 5000以下の場合は、一回で取得できる
                s5_count = gl_m5_count * over5000judge  # シンプルに5分足の60倍
                loop_for_5s = 1  # ループ回数は1回
                trimming = gl_need_to_analysis * over5000judge  # 実際に検証で使う範囲は、解析に必要な分を最初から除いた分。
            params = {"granularity": "S5", "count": s5_count, "to": end_time_euro}  # 5秒足で必要な分を取得する
            data_response = oa.InstrumentsCandles_multi_exe("USD_JPY", params, loop_for_5s)
            gl_s5_df = data_response['data']  # 期間の全5秒足を取得する  (これは解析に利用しないため、時系列を逆にしなくて大丈夫）
            start_s5_time = gl_s5_df.iloc[0]['time_jp']
            end_s5_time = gl_s5_df.iloc[-1]['time_jp']
            gl_s5_df.to_csv(tk.folder_path + gene.str_to_filename(start_s5_time) + '_test_s5_df.csv', index=False,
                            encoding="utf-8")
            print("")
            print("検証時間の総取得期間は", start_s5_time, "-", end_s5_time, len(gl_s5_df), "行")

        # 5秒足のデータが、5分足に対して多めに取れ（5000×Nの単位のため、最大4999の不要行がある。現実的にはなぜかもっと出る）、微笑に無駄なループが発生
        # するため、検証期間の先頭をそろえる　⇒　データフレームを、5秒足を左側（基準）、5分足を右側と考え、左外部結合を行う
        d5_df_for_merge = gl_d5_df.rename(columns=lambda x: f"{x}_y")  # 結合する側の名前にあらかじめ＿ｙをつけておく(予期せぬtime_xができるため）
        gl_inspection_base_df = pd.merge(gl_s5_df, d5_df_for_merge, left_on='time_jp', right_on='time_jp_y', how='left')
        # value2がNaNでない最初のインデックスを取得
        first_non_nan_index = gl_inspection_base_df['time_y'].first_valid_index()
        # インデックス以降のデータを取得
        gl_inspection_base_df = gl_inspection_base_df.loc[first_non_nan_index:]
        # テスト用
        # gl_inspection_base_df = gl_inspection_base_df[1286104:1779590]  # ここでは5秒足の足数になるため、広めでOK（解析機関
        # gl_inspection_base_df = gl_inspection_base_df.reset_index(drop=True)
        # print(gl_inspection_base_df.head(5))
        # print(gl_inspection_base_df.tail(5))
        # gl_actual_5m_start_time = gl_inspection_base_df.iloc[0]['time_jp']
        # gl_actual_end_time = gl_inspection_base_df.iloc[-1]['time_jp']
        # tk.line_send("test ", "【検証期間】", gl_actual_5m_start_time, "-", gl_actual_end_time)

        # インデックスを振りなおす（OK？）
        gl_inspection_base_df = gl_inspection_base_df.reset_index(drop=True)
        # 実際の調査開始時間と終了時間を取得する
        gl_actual_start_time = gl_inspection_base_df.iloc[0]['time_jp']
        gl_actual_end_time = gl_inspection_base_df.iloc[-1]['time_jp']
        print("マージされたデータフレームの行数", len(gl_inspection_base_df))
        print(gl_inspection_base_df.tail(5))