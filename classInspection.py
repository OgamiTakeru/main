import datetime
from datetime import timedelta
from scipy.stats import binomtest

import classOanda
import pandas as pd
import tokens as tk
import fGeneric as gene
import math
import plotly.graph_objects as go
import pandas as pd


class Order:
    class_total = 0

    def __init__(self, order_dic, for_inspection_dic):
        # print("検証でオーダー受付", order_dic['units'])
        print(order_dic)
        self.take_position_flag = False
        self.is_live = True  # オーダー発行時（インスタンス生成時）にTrueとなり、Orderキャンセルと、ポジション移行後のクローズでFalseとなる
        self.position_is_live = False
        self.position_status = "PENDING"  # pending, open ,closed, cancelled
        self.name = order_dic['name']
        self.target_price = order_dic['target_price']
        self.tp_price = order_dic['tp_price']
        self.lc_price = order_dic['lc_price']
        self.lc_price_original = order_dic['lc_price_original']
        self.units = order_dic['units'] * order_dic['direction']  # 正の値しか来ないようだ！？ なので、directionをかけておく
        self.direction = order_dic['direction']  # self.units / abs(self.units)
        self.order_keeping_time_sec = 0  # 現在オーダーをキープしている時間
        self.order_timeout_sec = order_dic['order_timeout_min'] * 60
        self.position_timeout_sec = 120 * 60  # 45 * 60

        self.unrealized_pl = 0  # 含み損益
        self.unrealized_pl_high = 0  # 最大含み損益(検証特有。最もその足でプラスに考えた状態の損益）
        self.unrealized_pl_low = 0  # 最小含み損益（検証特融。最もその足でマイナスに考えた状態の損益）
        self.unrealized_pl_per_units = 0
        self.realized_pl = 0
        self.realized_pl_per_units = 0

        self.position_time = 0
        self.position_keeping_time_sec = 0  # 現在ポジションをキープしている時間
        self.order_time = order_dic['order_time']
        self.max_plus = 0  # ポジションを持っている中で、一番プラスになっている時を取得
        self.max_plus_time_past = 0  # 何分経過時に最大のプラスを記録したか
        self.max_minus = 999  # ポジションを持っている中で、一番マイナスになっている時を取得
        self.max_minus_time_past = 0  # 何分経過時に、最大の負けを記録したか
        self.settlement_price = 0
        self.lc_change = order_dic['lc_change']
        self.priority = order_dic['priority']

        self.for_inspection_dic = for_inspection_dic

        self.comment = ""  # クラスごとに残すコメント（決済がLCChangeの場合LCとなるので、ClChangeとしたい、とか）

    def lc_change_done(self, i):
        self.lc_change[i]['done'] = True


class Inspection:
    def __init__(self, target_func, is_exist_data, target_to_time, m5_data_path, s5_data_path, m5_count, loop, memo, is_graph):
        """
        引数は色々取るが、二パターン
        必ず必要なのは、
        ・target_func⇒オーダーの発行フラグや、オーダーの内容を持っている物。
        ・memo ⇒　検証の後に、Memoを記入する用　何か記入が必要
        それ以外は条件によって異なる
        1,　既存のデータを使う場合
            5分足と、その範囲に適合する5秒足のファイルを利用する場合、
            is_exist_dataをTrueで渡し、m5_data_pathとs5_data_pathを指定する必要がある。
        ２，時間を指定する場合
            指定した時間を利用する場合、
            is_exist_dataをFalseにし、target_to_timeに対象の時刻を渡し、
            そこから何個分（時系列的に前まで）とるかを、m5_countとloopでしていする（5000×２回分のような）
            なおm5_countは5000が最大値
        """

        self.target_func = target_func
        self.gl_classes = []
        self.gl_exist_data = is_exist_data
        self.gl_jp_time = target_to_time  # TOの時刻
        self.gl_haba = "M5"
        self.gl_m5_count = m5_count
        self.gl_m5_loop = loop
        self.memo = memo
        self.result_df = None

        # gl_exist_date = Trueの場合の読み込みファイル
        # ■■■メイン（5分足や30分足）
        self.gl_main_csv_path = m5_data_path  # 大量データ(25)5分
        # ■■■検証用5秒足
        self.gl_s5_csv_path = s5_data_path  # 大量データ(25)5秒
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

        # 処理
        self.get_data()
        self.main()
        ans = self.cal_result_and_send_line()  # １は通常終了 0は異常終了
        if ans == 1:
            if is_graph:
                self.draw_graph()

    def get_data(self):
        """
        データを取得し、グローバル変数に格納する
        """
        # 解析のための「5分足」のデータを取得
        # gl_exist_data = True  # グローバルに変更
        if self.gl_exist_data:
            # 既存の5分足データを取得
            self.gl_d5_df = pd.read_csv(self.gl_main_csv_path, sep=",", encoding="utf-8")
            self.gl_5m_start_time = self.gl_d5_df.iloc[0]['time_jp']
            self.gl_5m_end_time = self.gl_d5_df.iloc[-1]['time_jp']
            self.gl_actual_5m_start_time = self.gl_d5_df.iloc[self.gl_need_to_analysis]['time_jp']
            self.gl_d5_df_r = self.gl_d5_df.sort_index(ascending=False)  # 時系列を逆にしたものが解析用！
            print(self.gl_d5_df_r.head(5))
            print(self.gl_d5_df_r.tail(5))
            print("5分足での取得時刻は", self.gl_5m_start_time, "-", self.gl_5m_end_time, len(self.gl_d5_df_r), "行")
            print("実際の解析時間は", self.gl_d5_df.iloc[self.gl_need_to_analysis]['time_jp'], "-", self.gl_5m_end_time)
            # 既存の5秒足データを取得
            self.gl_s5_df = pd.read_csv(self.gl_s5_csv_path, sep=",", encoding="utf-8")
            start_s5_time = self.gl_s5_df.iloc[0]['time_jp']
            end_s5_time = self.gl_s5_df.iloc[-1]['time_jp']
            print("検証用データ")
            print("検証時間の総取得期間は", start_s5_time, "-", end_s5_time, len(self.gl_s5_df), "行")

        else:
            # 5分足データを新規で取得
            euro_time_datetime = self.gl_jp_time - datetime.timedelta(hours=9)
            euro_time_datetime_iso = str(euro_time_datetime.isoformat()) + ".000000000Z"  # ISOで文字型。.0z付き）
            params = {"granularity": self.gl_haba, "count": self.gl_m5_count, "to": euro_time_datetime_iso}  # コツ　1回のみ実行したい場合は88
            data_response = self.oa.InstrumentsCandles_multi_exe("USD_JPY", params, self.gl_m5_loop)
            self.gl_d5_df = data_response['data']
            self.gl_d5_df_r = self.gl_d5_df.sort_index(ascending=False)  # 時系列を逆にしたものが解析用！
            self.gl_5m_start_time = self.gl_d5_df.iloc[0]['time_jp']
            self.gl_5m_end_time = self.gl_d5_df.iloc[-1]['time_jp']
            self.gl_actual_5m_start_time = self.gl_d5_df.iloc[self.gl_need_to_analysis]['time_jp']
            self.gl_d5_df.to_csv(tk.folder_path + gene.str_to_filename(self.gl_5m_start_time) + '_test_m5_df.csv', index=False,
                            encoding="utf-8")
            print("解析用5分足データ")
            print("5分足での取得時刻は", self.gl_5m_start_time, "-", self.gl_5m_end_time, len(self.gl_d5_df), "行")
            print("(実際の解析時間は", self.gl_actual_5m_start_time, "-", self.gl_5m_end_time)

            # 5秒足データを取得
            if self.gl_haba == "M5":
                over5000judge = 60
            elif self.gl_haba == "M30":
                over5000judge = 360
            else:
                over5000judge = 60

            end_time_euro = self.gl_d5_df_r.iloc[0]['time']  # Toに入れるデータ（これは解析用と一致させたいため、基本固定）
            all_need_row = self.gl_m5_count * 60 * self.gl_m5_loop
            if self.gl_m5_count * over5000judge > 5000:
                # 5000を超えてしまう場合はループ処理が必要(繰り返しデータで使うため、少し多めに取ってしまう。5000単位をN個の粒度）
                loop_for_5s = math.ceil(all_need_row / 5000)
                s5_count = 5000
                trimming = (5000 * loop_for_5s - all_need_row) + (self.gl_need_to_analysis * 60)
                print("   5S検証：必要な行", all_need_row, "5000行のループ数", loop_for_5s, "多く取得できる行数",
                      5000 * loop_for_5s - all_need_row)
            else:
                # 5000以下の場合は、一回で取得できる
                s5_count = self.gl_m5_count * over5000judge  # シンプルに5分足の60倍
                loop_for_5s = 1  # ループ回数は1回
                trimming = self.gl_need_to_analysis * over5000judge  # 実際に検証で使う範囲は、解析に必要な分を最初から除いた分。
            params = {"granularity": "S5", "count": s5_count, "to": end_time_euro}  # 5秒足で必要な分を取得する
            data_response = self.oa.InstrumentsCandles_multi_exe("USD_JPY", params, loop_for_5s)
            self.gl_s5_df = data_response['data']  # 期間の全5秒足を取得する  (これは解析に利用しないため、時系列を逆にしなくて大丈夫）
            start_s5_time = self.gl_s5_df.iloc[0]['time_jp']
            end_s5_time = self.gl_s5_df.iloc[-1]['time_jp']
            self.gl_s5_df.to_csv(tk.folder_path + gene.str_to_filename(start_s5_time) + '_test_s5_df.csv', index=False,
                            encoding="utf-8")
            print("")
            print("検証時間の総取得期間は", start_s5_time, "-", end_s5_time, len(self.gl_s5_df), "行")

        # 5秒足のデータが、5分足に対して多めに取れ（5000×Nの単位のため、最大4999の不要行がある。現実的にはなぜかもっと出る）、微笑に無駄なループが発生
        # するため、検証期間の先頭をそろえる　⇒　データフレームを、5秒足を左側（基準）、5分足を右側と考え、左外部結合を行う
        d5_df_for_merge = self.gl_d5_df.rename(columns=lambda x: f"{x}_y")  # 結合する側の名前にあらかじめ＿ｙをつけておく(予期せぬtime_xができるため）
        self.gl_inspection_base_df = pd.merge(self.gl_s5_df, d5_df_for_merge, left_on='time_jp', right_on='time_jp_y', how='left')
        # value2がNaNでない最初のインデックスを取得
        first_non_nan_index = self.gl_inspection_base_df['time_y'].first_valid_index()
        # インデックス以降のデータを取得
        self.gl_inspection_base_df = self.gl_inspection_base_df.loc[first_non_nan_index:]
        # テスト用
        # gl_inspection_base_df = gl_inspection_base_df[1286104:1779590]  # ここでは5秒足の足数になるため、広めでOK（解析機関
        # gl_inspection_base_df = gl_inspection_base_df.reset_index(drop=True)
        # print(gl_inspection_base_df.head(5))
        # print(gl_inspection_base_df.tail(5))
        # gl_actual_5m_start_time = gl_inspection_base_df.iloc[0]['time_jp']
        # gl_actual_end_time = gl_inspection_base_df.iloc[-1]['time_jp']
        # tk.line_send("test ", "【検証期間】", gl_actual_5m_start_time, "-", gl_actual_end_time)

        # インデックスを振りなおす（OK？）
        self.gl_inspection_base_df = self.gl_inspection_base_df.reset_index(drop=True)
        # 実際の調査開始時間と終了時間を取得する
        self.gl_actual_start_time = self.gl_inspection_base_df.iloc[0]['time_jp']
        self.gl_actual_end_time = self.gl_inspection_base_df.iloc[-1]['time_jp']
        print("マージされたデータフレームの行数", len(self.gl_inspection_base_df))
        print(self.gl_inspection_base_df.tail(5))

    def main(self):
        """
        5分足のデータを解析し、オーダーを発行する。
        発行後は別関数で、5秒のデータで検証する
        """

        # ５秒足を１行ずつループし、５分単位で解析を実行する
        for index, row_s5 in self.gl_inspection_base_df.iterrows():
            if index % 1000 == 0:
                print("■■■検証", row_s5['time_jp'], "■■■", index, "行目/", len(self.gl_inspection_base_df), "中")

            # 【解析処理】結合した5分足の部分にデータがあれば、解析トライをする   旧（分が5の倍数であれば、解析を実施する）
            dt = str_to_time(row_s5['time_jp'])  # 時間に変換
            # if dt.minute % 5 == 0 and dt.second == 0:  # 各5分0秒で解析を実行する
            if pd.notna(row_s5['time_y']):  # 毎5の倍数分で解析を実行する
                analysis_df = find_analysis_dataframe(self.gl_d5_df_r, row_s5['time_jp'])  # 解析用の5分足データを取得する
                if len(analysis_df) < self.gl_need_to_analysis:
                    # 解析できない行数しかない場合、実施しない（5秒足の飛びや、取得範囲の関係で発生）
                    print("   解析実施しません", len(analysis_df), "行しかないため（必要行数目安[固定値ではない]",
                          self.gl_need_to_analysis, "データ数", len(analysis_df), "行数:", index, "行目/",
                          len(self.gl_inspection_base_df), "中")
                    continue  # returnではなく、次のループへ
                else:
                    # ★★★ 解析を呼び出す★★★★★
                    print("★解析", row_s5['time_jp'], "行数", len(analysis_df), index, "行目/",
                          len(self.gl_inspection_base_df), "中")
                    # analysis_result = im.new_analysis_test(analysis_df)  # 検証専用コード
                    analysis_result = self.target_func(analysis_df)  # 検証専用コード
                    for order in analysis_result["exe_orders"]:  # original_lc_priceの追加
                        order["lc_price_original"] = order["lc_price"]
                    # analysis_result = im.analysis_warp_up_and_make_order(analysis_df)
                    if not analysis_result['take_position_flag']:
                        # オーダー判定なしの場合、次のループへ（5秒後）
                        continue
                    # ■上書き有無を判断
                    overwrite_order = False
                    if overwrite_order:
                        # 上書きする場合(実運用に近い）
                        # 既存のクラスをリセットして、改めて登録しなおす
                        # クラスをリセット＆オーダーをクラスに登録する
                        self.gl_classes = []  # リセット
                        order_time = row_s5['time_jp']
                        for i_order in range(len(analysis_result['exe_orders'])):
                            # print(analysis_result['exe_orders'][i_order])
                            analysis_result['exe_orders'][i_order][
                                'order_time'] = order_time  # order_time追加（本番marketだとない）
                            self.gl_classes.append(Order(analysis_result['exe_orders'][i_order],
                                                    analysis_result[
                                                        'for_inspection_dic']))  # インスタンス生成＋配列追加(is_life=True)
                            # 結果表示用の情報を作成
                            self.gl_order_list.append(
                                {"order_time": order_time, "name": analysis_result['exe_orders'][i_order]['name']})
                    else:
                        # ★上書きしない検証用
                        # 全てのオーダーに対して、検証を行う。LifeがFalseになったものに上書きしていく。ポジ解消タイミングによって、結果の時系列が逆になることも。
                        order_time = row_s5['time_jp']
                        for i_order in range(len(analysis_result['exe_orders'])):
                            # print(analysis_result['exe_orders'][i_order])
                            analysis_result['exe_orders'][i_order][
                                'order_time'] = order_time  # order_time追加（本番marketだとない）
                            gene.print_json(analysis_result)
                            self.gl_classes.append(Order(analysis_result['exe_orders'][i_order],
                                                    analysis_result[
                                                        'for_inspection_dic']))  # 【配列追加】インスタンス生成し、オーダーと検証用データを渡す。
                            # 結果表示用の情報を作成
                            self.gl_order_list.append(
                                {"order_time": order_time,
                                 "direction": analysis_result['exe_orders'][i_order]['direction'],
                                 "price": analysis_result['exe_orders'][i_order]['target_price'],
                                 "name": analysis_result['exe_orders'][i_order]['name']
                                 })

            # 【実質的な検証処理】各クラスを巡回し取得、解消　を5秒単位で実行する
            for i, each_c in enumerate(self.gl_classes):
                # すでに実行済の場合は実行しない
                if not each_c.is_live:
                    continue

                # 処理を実施する(ポジション取得～解消まで）
                if not each_c.position_is_live:
                    # ポジションがない場合は、取得判定
                    # print("    取得待ち", row_s5['low'], row_s5['high'], each_c.target_price,each_c.position_is_live)
                    update_order_information_and_take_position(each_c, row_s5, index)
                else:
                    # 現状をアップデートする
                    update_position_information(each_c, row_s5, index)
                    # ロスカ（利確）判定や、LCチェンジ等の処理を行う
                    self.execute_position_finish(each_c, row_s5, index)

    def cal_result_and_send_line(self):
        # ■結果処理
        # 検証内容をデータフレームに変換
        print(self.gl_results_list)
        if len(self.gl_results_list) == 0:
            print("結果無し（０件）")
            return 0
        result_df = pd.DataFrame(self.gl_results_list)  # 結果の辞書配列をデータフレームに変換
        # 解析に使いそうな情報をつけてしまう（オプショナルでなくてもいいかも）
        result_df['plus_minus'] = result_df['pl_per_units'].apply(lambda x: -1 if x < 0 else 1)  # プラスかマイナスかのカウント用
        result_df['order_time_datetime'] = pd.to_datetime(result_df['order_time'])  # 文字列の時刻をdatatimeに変換したもの
        result_df['Hour'] = result_df['order_time_datetime'].dt.hour
        result_df['name_only'] = result_df['name'].apply(
            lambda x: x[:-5] if isinstance(x, str) and len(x) > 5 else x)  # 時間削除
        # 平均値等
        result_df['group'] = (result_df['pl_per_units'] // 0.01) * 0.01
        absolute_mean = result_df['units'].abs().mean()
        # name列を@で分割
        name_parts = result_df['name_only'].str.split('@', expand=True)
        # 分割後の列数に応じて動的にカラム名をつける
        name_parts.columns = [f"param_{i}" for i in range(name_parts.shape[1])]
        # nameから@以降を削除（パラメータのため）
        result_df['name'] = name_parts['param_0']
        # 元のDataFrameに残りの name_parts を結合（name_0 は除く）
        name_parts_rest = name_parts.drop(columns=['param_0'])
        result_df = pd.concat([result_df, name_parts_rest], axis=1)
        self.result_df = result_df  # インスタンス変数にもコピーしておく

        # 保存
        try:
            result_df.to_csv(tk.folder_path + self.gl_start_time_str + self.memo + '_main_analysis_ans.csv', index=False,
                             encoding="utf-8")
            result_df.to_csv(tk.folder_path + 'main_analysis_ans_latest.csv', index=False, encoding="utf-8")
        except:
            print("書き込みエラーあり")  # 今までExcelを開きっぱなしにしていてエラーが発生。日時を入れることで解消しているが、念のための分岐
            result_df.to_csv(tk.folder_path + self.gl_start_time_str + 'main_analysis_ans.csv', index=False,
                             encoding="utf-8")

        # 結果表示（共通）
        print("●●検証終了●●", "   クラス数", len(self.gl_classes))
        fin_time = datetime.datetime.now()
        print("●スキップされたオーダー")
        gene.print_arr(self.gl_not_overwrite_orders)
        print("●オーダーリスト（約定しなかったものが最下部の結果に表示されないため、オーダーを表示）")
        gene.print_arr(self.gl_order_list)
        print("●結果リスト")
        gene.print_arr(self.gl_results_list)
        print("●データの範囲", self.gl_5m_start_time, self.gl_5m_end_time)
        print("●実際の解析範囲", self.gl_actual_5m_start_time, "-", self.gl_actual_end_time, "行(5分足換算:",
              round(len(self.gl_inspection_base_df) / 60, 0), ")")
        # 結果表示（分岐）
        if len(result_df) == 0:
            print("結果０です")
        else:
            # 簡易的な結果表示用
            plus_df = result_df[result_df["pl"] >= 0]  # PLがプラスのもの（TPではない。LCでもトレール的な場合プラスになっているため）
            minus_df = result_df[result_df["pl"] < 0]
            # 結果表示部
            print("●オーダーの個数", len(self.gl_order_list), "、約定した個数", len(self.gl_results_list))
            print("●プラスの個数", len(plus_df), ", マイナスの個数", len(minus_df))
            print("●最終的な合計", round(self.gl_total, 3), round(self.gl_total_per_units, 3))
            # LINEを送る
            inspection_day_gap_sec = gene.cal_str_time_gap(self.gl_actual_start_time, self.gl_actual_end_time)
            inspection_day_gap = inspection_day_gap_sec['gap_abs'] // (24 * 60 * 60)
            tk.line_send("test fin 【結果】", round(self.gl_total, 3), ",\n"
                         , "【検証期間】", self.gl_actual_start_time, "-", self.gl_actual_end_time, "(", inspection_day_gap, "日)", "\n"
                         , "【Unit平均】", round(absolute_mean, 0), ",\n"
                         , "【+域/-域の個数】", len(plus_df), ":", len(minus_df), " 計:", len(plus_df) + len(minus_df), ",\n"
                         , "【+域/-域の平均値】", round(plus_df['pl_per_units'].mean(), 3), ":",
                         round(minus_df['pl_per_units'].mean(), 3), ",\n"
                         , "【有意】", self.check_skill_difference(len(plus_df), len(minus_df)), ",\n"
                         , "【回数/日】", round((len(plus_df) + len(minus_df))/inspection_day_gap, 0), ",\n"
                         , "【条件】", self.memo, ",\n参考:処理開始時刻", self.gl_now)
        return 1

    def check_skill_difference(self, wins, losses):
        total = wins + losses
        result = binomtest(wins, n=total, p=0.5, alternative='two-sided')
        p = result.pvalue
        p_percent = round(p * 100, 0)

        comment = "発生率:" + str(p_percent)
        if p<0.05:
            comment = comment + "(有意差有)"
        else:
            comment = comment + "(有意差無)"

        return comment

    def execute_position_finish(self, cur_class, cur_row, cur_row_index):
        """
        クラスに更新された情報を基に、ポジションに対する操作を行う
        ポジション解消や変更があった場合は、クラスの変数を直接変更してしまう。
        """
        # 変数の簡略化
        target_price = cur_class.target_price
        lc_price = cur_class.lc_price
        tp_price = cur_class.tp_price

        # ■最終的にはここでクローズする。LCとTPの処理
        pl = 0  # 念のための初期値だが、このままの場合は異常発生時
        comment = ""
        # スプレッドを考慮した、アジャスターを用意(買いの場合は、売り価格で終了する（-0.004 = スプレッド÷2)。売りの場合はその逆）
        adjuster = -0.004 if cur_class.direction == 1 else 0.004

        # 価格による判定
        if cur_row['low'] + adjuster < lc_price < cur_row["high"] + adjuster:
            print("　　 ■ロスカットします", cur_class.name, cur_row['time_jp'], cur_row['low'], lc_price, cur_row["high"])
            pl = (lc_price - cur_class.target_price) * cur_class.direction
            cur_class.settlement_price = lc_price  # ポジション解消価格
            cur_class.position_is_live = False
            cur_class.is_live = False
            if cur_class.comment == "LC_c":
                # LCChangeがあった場合は、LCチェンジによるLC.ただしプラス域とは限らない。
                pass
            else:
                cur_class.comment = "LC"
        if cur_row['low'] + adjuster < tp_price < cur_row[
            'high'] + adjuster and cur_class.position_is_live:  # （ロスカット優先）
            print("　　 ■利確します", cur_class.name, cur_row['time_jp'], cur_row['low'], tp_price, cur_row["high"])
            pl = (tp_price - cur_class.target_price) * cur_class.direction
            cur_class.settlement_price = tp_price  # ポジション解消価格
            cur_class.position_is_live = False
            cur_class.is_live = False
            cur_class.comment = "TP"

        # 時間による判
        # print("   時間的トレード解消判定", cur_class.position_keeping_time_sec, "> 規定Sec", cur_class.position_timeout_sec, cur_class.unrealized_pl)
        if cur_class.position_keeping_time_sec > cur_class.position_timeout_sec:  # and cur_class.unrealized_pl < 0:
            # 本番ではマイナス継続が1分続いた場合だが、ここではマイナスでありかつ時間が経過なので、ある程度ずれる。ただマイナスはほぼ変わりない。
            print("    Trade解消(マイナス×時間)", cur_class.position_keeping_time_sec, "> 規定Sec",
                  cur_class.position_timeout_sec)
            # 本番では、膠着状態における解消も実施しているが、ここではいったん除外
            pl = (cur_row['close'] - cur_class.target_price) * cur_class.direction
            pl = (cur_row['open'] - cur_class.target_price) * cur_class.direction
            cur_class.settlement_price = cur_row['close']  # ポジション解消価格（ここは暫定的にOpen価格
            cur_class.position_is_live = False
            cur_class.is_live = False
            cur_class.comment = "p_Tout"

        # 情報書き込み＆決済 jp
        if not cur_class.position_is_live:
            print("　　   [結果表示]取得価格", cur_class.target_price, "決済価格", cur_class.settlement_price)
            # ポジション解消時にTarget PriceとTP/LC priceでの損益がPLに格納されているので、これを格納する
            cur_class.realized_pl = pl * abs(cur_class.units)  # 含み損益の更新（Unitsをかけたもの）　マイナス値を持つ
            cur_class.realized_pl_per_units = pl  # 含み損益（Unitsに依存しない数） マイナス値を持つ
            # print(pl * abs(cur_class.units), pl, cur_row['time_jp'])
            self.gl_total += cur_class.realized_pl
            self.gl_total_per_units += cur_class.realized_pl_per_units
            result_dic = {
                "order_time": cur_class.order_time,
                "res": cur_class.comment,
                "pl": round(cur_class.realized_pl, 3),
                "take_time": cur_class.position_time,
                "take_price": round(cur_class.target_price, 3),
                "end_time": cur_row['time_jp'],
                "end_price": round(cur_class.settlement_price, 3),
                "name": cur_class.name,
                "pl_per_units": round(cur_class.realized_pl_per_units, 3),
                "max_plus": round(cur_class.max_plus, 3),
                "max_plus_time_past": cur_class.max_plus_time_past,
                "max_minus": round(cur_class.max_minus, 3),
                "max_minus_time_past": cur_class.max_minus_time_past,
                "priority": cur_class.priority,
                "position_keeping_time": cur_class.position_keeping_time_sec,
                "settlement_price": round(cur_class.settlement_price, 3),
                "tp_price": round(cur_class.tp_price, 3),
                "lc_price": round(cur_class.lc_price, 3),
                "lc_price_original": round(cur_class.lc_price_original, 3),
                "direction": cur_class.direction,
                "units": cur_class.units,
            }
            # 検証用データを結合
            result_dic = {**result_dic, **cur_class.for_inspection_dic}
            self.gl_results_list.append(result_dic)

    def draw_graph(self):
        #  各データフレームの時刻をDateTimeに変換
        self.gl_d5_df['time_jp'] = pd.to_datetime(self.gl_d5_df['time_jp'])
        self.result_df['order_time'] = pd.to_datetime(self.result_df['order_time'])  # 決心時間（少しずれるので見にくい？）
        self.result_df['take_time'] = pd.to_datetime(self.result_df['take_time'])  # 決心時間（少しずれるので見にくい？）

        # ローソク足チャート作成
        fig = go.Figure(data=[
            go.Candlestick(
                x=self.gl_d5_df["time_jp"],
                open=self.gl_d5_df["open"],
                high=self.gl_d5_df["high"],
                low=self.gl_d5_df["low"],
                close=self.gl_d5_df["close"],
                name="Candles"
            )
        ])

        # マーカー追加（買いの場合は▲、売りの場合は▼、結果がプラスの場合青、マイナスの場合赤で表示される）
        for _, row in self.result_df.iterrows():
            # 【必須】三角マーカーを追加
            # 向き
            symbol = "triangle-up" if row["units"] > 0 else "triangle-down"
            # 色
            color = "blue" if row["pl"] > 0 else "red"

            fig.add_trace(go.Scatter(
                # x=[row["order_time"]],
                x=[row["order_time"]],
                y=[row["take_price"]],
                mode="markers",
                marker=dict(symbol=symbol, size=12, color=color),
                name="Trade",
                showlegend=False  # 凡例がうるさい場合はOFF
            ))
            # 黒い横棒（lc_price）：細い
            fig.add_trace(go.Scatter(
                x=[row["order_time"]],
                y=[row["lc_price_original"]],
                mode="markers",
                marker=dict(symbol='line-ew', size=7, color='black', line=dict(width=1)),
                name="LC Price",
                showlegend=False
            ))
            # 黒い横棒（tp_price）：太い
            fig.add_trace(go.Scatter(
                x=[row["order_time"]],
                y=[row["tp_price"]],
                mode="markers",
                marker=dict(symbol='line-ew', size=7, color='black', line=dict(width=3)),
                name="TP Price",
                showlegend=False
            ))

        # オプション（一時的な解析用）
        # PredictLineOrder の上書き三角マーカー（条件つき色）
        for _, row in self.result_df.iterrows():
            if "PredictLineOrder" in row["name"]:
                symbol = "triangle-up" if row["units"] > 0 else "triangle-down"
                color = "#87CEFA" if row["pl"] > 0 else "orange"  # 薄い青 or オレンジ
                fig.add_trace(go.Scatter(
                    x=[row["order_time"]],
                    y=[row["take_price"]],
                    mode="markers",
                    marker=dict(symbol=symbol, size=14, color=color),
                    name="PredictLineOrder",
                    showlegend=False
                ))
            # 星印をつける
            if "PredictLineOrder" in row.get("name", ""):
                fig.add_trace(go.Scatter(
                    x=[row["order_time"]],
                    y=[row["take_price"] + 0.2],
                    mode="markers",
                    marker=dict(
                        symbol="star",
                        size=12,
                        color="black",
                        line=dict(width=2, color="black")  # 中抜きスタイル
                    ),
                    name="PredictLineMark",
                    showlegend=False
                ))
            # TPとLCを記入
            # 黒い横棒（lc_price）：細い
            fig.add_trace(go.Scatter(
                x=[row["order_time"]],
                y=[row["lc_price_original"]],
                mode="markers",
                marker=dict(symbol='line-ew', size=7, color='black', line=dict(width=1)),
                name="LC Price",
                showlegend=False
            ))

            # 黒い横棒（tp_price）：太い
            fig.add_trace(go.Scatter(
                x=[row["order_time"]],
                y=[row["tp_price"]],
                mode="markers",
                marker=dict(symbol='line-ew', size=7, color='black', line=dict(width=3)),
                name="TP Price",
                showlegend=False
            ))



        # レイアウト調整
        fig.update_layout(
            title="ローソク足チャート + 取引ポイント",
            xaxis_title="時間",
            yaxis_title="価格",
            xaxis_rangeslider_visible=False
        )

        # 表示
        fig.show()

def str_to_time(str_time):
    """
    時刻（文字列 yyyy/mm/dd hh:mm:mm）をDateTimeに変換する。
    何故かDFないの日付を扱う時、isoformat関数系が使えない。。なぜだろう。
    :param str_time:
    :return:
    """
    time_dt = datetime.datetime(int(str_time[0:4]),
                                int(str_time[5:7]),
                                int(str_time[8:10]),
                                int(str_time[11:13]),
                                int(str_time[14:16]),
                                int(str_time[17:19]))
    return time_dt


def cal_str_time_gap(time_str_1, time_str_2):
    """
    データフレームのtime_jp同士の時間の差を求める。
    引数で渡された日時のどちらか大きいか（Later）か判断し、差分を正の値で産出する。
    """
    time1 = time_str_1 if isinstance(time_str_1, datetime.datetime) else str_to_time(time_str_1)
    time2 = time_str_2 if isinstance(time_str_2, datetime.datetime) else str_to_time(time_str_2)

    if time1 > time2:
        later_time = time1
        older_time = time2
        r = 1
    else:
        later_time = time2
        older_time = time1
        r = -1
    gap_abs = later_time - older_time  # 正の値が保証された差分
    # gap = time1 - time2  # 渡されたものをそのまま引き算（これエラーになりそうだから消しておく）

    return {
        "gap_abs": gap_abs.total_seconds(),
        "gap": gap_abs.total_seconds() * r
        # "gap_abs": gap_abs.seconds,
        # "gap": gap_abs.seconds * r
    }


def find_analysis_dataframe(df, time_jp):
    """
    解析用に指定の時刻「より前」の5分足のデータフレームを取得する
    """
    idx = df[df['time_jp'] == time_jp].index
    if len(idx) == 0:
        return pd.DataFrame()  # 値が存在しない場合は空のデータフレームを返す
    # 最初のインデックスを取得し、その後の行をフィルタ
    return df[df.index <= idx[0]]


def update_order_information_and_take_position(cur_class, cur_row, cur_row_index):
    """
    オーダーが約定するかを確認する関数
    引数は対象のクラス(CurrentClass)と、検証対象のデータ行(CurrentRow)と、そのデータ行のインデックス
    """
    # スプレッドを考慮した、アジャスターを用意(買いの場合は、買い価格で開始する（0.004 = スプレッド÷2)。売りの場合はその逆）
    adjuster = 0.004 if cur_class.direction == 1 else -0.004

    # (1)オーダーの時間を求め、時間切れ判定も実施する
    order_keeping_time_sec = cal_str_time_gap(cur_row['time_jp'], cur_class.order_time)['gap']
    cur_class.order_keeping_time_sec = order_keeping_time_sec  # クラスの内容を更新（オーダー取得までの経過時間として使える。ポジション後は更新しないため）
    if order_keeping_time_sec >= cur_class.order_timeout_sec:
        print("   ■タイムアウトです", cur_class.name, cur_row['time_jp'])
        # クラス内容の更新
        cur_class.is_live = False  # Lifeをクローズ
    else:
        # (2)タイムアウトでなければ、取得判定を実施する　（同一行で取得⇒ロスカの可能性はここでは考えない）
        target_price = cur_class.target_price
        if cur_row['low'] + adjuster <= target_price < cur_row["high"] + adjuster:
            print("　　■取得しました", cur_class.name, cur_row['time_jp'], cur_row['low'], cur_row['high'], target_price)
            # クラス内容の更新
            cur_class.position_time = cur_row['time_jp']
            cur_class.position_is_live = True
        else:
            # print(" 取得まち", cur_row['time_jp'], cur_class.name, target_price, cur_row['low'] + adjuster, cur_row["high"] + adjuster)
            pass


def update_position_information(cur_class, cur_row, cur_row_index):
    """
    ポジションの情報を更新し（ポジションある状態での実行が前提）、必要に応じてクラスに反映する。
    """
    # (1)情報の整理
    # ポジションの最高プラスかマイナスを更新する(ロスカットかどうかはとりあえず加味しない）
    upper_gap = cur_row['high'] - cur_class.target_price  # 買いポジの場合はプラス域
    lower_gap = cur_class.target_price - cur_row['low']  # 買いポジの場合はマイナス域

    # 経過秒を計算する
    position_keeping_time_sec = cal_str_time_gap(cur_row['time_jp'], cur_class.position_time)['gap']

    # PLを計算する(幅があるため、基本はClose価格で計算した損益を使用するが、最大（最もプラスにとらえた）PLや最低PLも取得しておく
    # スプレッドを考慮した、アジャスターを用意(買いの場合は、売り価格で終了する（-0.004 = スプレッド÷2)。売りの場合はその逆）
    adjuster = -0.004 if cur_class.direction == 1 else 0.004
    now_price = cur_row['close']  # 暫定としてクローズ価格を現在価格とする ★NowPriceで考えるため、LCやTP priceとは誤差が出る。
    # 現価＞ターゲットだと現価-ターゲットは正の値。買いポジの場合は＋）
    pl_use_close = round((cur_row['close'] + adjuster - cur_class.target_price) * cur_class.direction,
                         3)  # 現価＞ターゲットだと現価-ターゲットは正の値。買いポジの場合は＋）
    pl_use_high = round((cur_row['high'] + adjuster - cur_class.target_price) * cur_class.direction,
                        3)  # 現価＞ターゲットだと現価-ターゲットは正の値。買いポジの場合は＋）
    pl_use_low = round((cur_row['low'] + adjuster - cur_class.target_price) * cur_class.direction,
                       3)  # 現価＞ターゲットだと現価-ターゲットは正の値。買いポジの場合は＋）

    # print("  -Update条件", cur_row['low'], cur_row['high'])
    # print("  -Update条件", pl_use_low, pl_use_high, cur_class.direction)

    if cur_class.direction == 1:
        # 買い方向の場合
        cur_class.unrealized_pl_high = pl_use_high
        cur_class.unrealized_pl_low = pl_use_low
    else:
        # 売り方向の場合
        cur_class.unrealized_pl_high = pl_use_low
        cur_class.unrealized_pl_low = pl_use_high

    # (2)クラス内の情報を更新する（最大プラスと最大マイナス）
    cur_class.position_keeping_time_sec = position_keeping_time_sec  # 所持継続時間の更新
    cur_class.unrealized_pl = pl_use_close * abs(cur_class.units)  # 含み損益の更新（Unitsをかけたもの）　マイナス値を持つ
    cur_class.unrealized_pl_per_units = pl_use_close  # 含み損益（Unitsに依存しない数） マイナス値を持つ
    cur_class.pl = cur_class.unrealized_pl  # 途中でTest範囲が過ぎると、結果が入らなくなるため、この段階から入れておく
    cur_class.pl_per_units = cur_class.unrealized_pl_per_units  # 途中でTest範囲が過ぎると、結果が入らなくなるため、この段階から入れておく
    # print(pl * abs(cur_class.units), pl, cur_row['time_jp'])
    if cur_class.direction == 1:
        # 買い方向の場合
        if cur_class.max_plus < upper_gap:
            cur_class.max_plus = upper_gap  # 更新
            cur_class.max_plus_time_past = cur_class.position_keeping_time_sec
        if cur_class.max_minus > lower_gap:
            cur_class.max_minus = lower_gap  # 更新
            cur_class.max_minus_time_past = cur_class.position_keeping_time_sec
    else:
        # 売り方向の場合
        if cur_class.max_plus < lower_gap:
            cur_class.max_plus = lower_gap  # 更新
            cur_class.max_plus_time_past = cur_class.position_keeping_time_sec
        if cur_class.max_minus > upper_gap:
            cur_class.max_minus = upper_gap  # 更新
            cur_class.max_minus_time_past = cur_class.position_keeping_time_sec

    # (3)LCチェンジを実行(通常）
    for i, lc_item in enumerate(cur_class.lc_change):
        # print("    LC_Change:", lc_item['lc_trigger_range'], cur_class.unrealized_pl_low, cur_class.unrealized_pl_high)
        if 'done' in lc_item or cur_class.position_keeping_time_sec <= lc_item['time_after']:
            # print("   　　⇒OUT", cur_class.position_keeping_time_sec, lc_item['time_after'])
            # if 'done' in lc_item:
            # print("        ⇒OUT", lc_item['done'])
            continue

        if cur_class.unrealized_pl_low < lc_item['lc_trigger_range'] < cur_class.unrealized_pl_high:
            new_lc_range = lc_item['lc_ensure_range']  # マイナス値もありうるため注意
            if cur_class.direction == 1:
                # 買い方向の場合
                new_lc_price = cur_class.target_price + new_lc_range
            else:
                # 売り方向の場合
                new_lc_price = cur_class.target_price - new_lc_range
            print("　　   ★LC底上げ", cur_class.lc_price, "⇒", new_lc_price, cur_row['time_jp'])
            cur_class.comment = "LC_c"
            cur_class.lc_change_done(i)  # Doneの追加
            cur_class.lc_price = new_lc_price  # 値の更新
    # (3)LCチェンジを実行（直前ローソク利用）
    # if not cur_class.position_is_live or cur_class.pl_per_units < 0 or cur_class.position_keeping_time_sec < 100:  # 足数×〇分足×秒
    #     return 0
    # else:
    #     pass

