import datetime
from datetime import timedelta
import pandas as pd
from collections import defaultdict
import tokens as tk
import fGeneric as gene
import fGeneric as f
import copy
import classCandlePeaks as peaksClass
from pympler import asizeof


class candleAnalysis:

    # 重複のAPIたたきを極力減らしたい
    avoid_dup_5min_kara_time = 0  # 重複での処理作業防止用（最新で取得した5分足のデータのカラマデの時間を所持。クラス生成時、同じ場合は新規処理しない）
    avoid_dup_5min_made_time = 0
    latest_df_d5_df_r = None
    latest_peaks_class = None  # 最新の物を持っておく（判定用に冗長に持っていて、そとからはインスタンス変数を参照がメイン。）
    latest_candle_meta_class = None
    latest_h1_df_r = None
    latest_peaks_class_hour = None  # 最新の物を持っておく（判定用に冗長に持っていて、そとからはインスタンス変数を参照がメイン。）
    latest_candle_meta_class_hour = None
    latest_df_d30_df_r = None
    latest_peaks_class_m30 = None  # 最新の物を持っておく（判定用に冗長に持っていて、そとからはインスタンス変数を参照がメイン。）
    latest_candle_meta_class_m30 = None

    def __init__(
            self,
            base_oa=None,
            pair="USD_JPY",
            target_time_jp=0,
            m5_df_r=None,
            h1_df_r=None,
            m30_df_r=None,
            s5_df_r=None,
            current_price=None,
    ):
        """
        target_time_jpまでの時間を取得する
        """
        # pair 
        self.pair = pair  # 通貨ペア
        # オアンダクラス
        self.base_oa = base_oa
        self.need_df_num = 250

        self.current_price = 0  # 後に価格として入る(本番の場合[=時間指定なし]API、検証の場合はdfの先頭）
        self.current_price_by_df = 0  # デーらフレームから取得した（.iloc[1]['close']）価格

        # データ入れる用
        self.d5_df_r = None
        self.h1_df_r = None
        self.s5_df_r = None
        self.d30_df_r = None

        if m5_df_r is not None:
            self.d5_df_r = m5_df_r
            self.h1_df_r = h1_df_r
            self.d30_df_r = m30_df_r
            self.s5_df_r = s5_df_r
            if self.h1_df_r is None:
                raise ValueError("h1_df_r is required when m5_df_r is passed.")
            if self.d30_df_r is None:
                print("m30_df_r is not passed. h1_df_r is used as a temporary fallback for M30 analysis.")
                self.d30_df_r = self.h1_df_r
            if current_price is not None:
                self.current_price = current_price
            elif len(self.d5_df_r) >= 2:
                self.current_price = self.d5_df_r.iloc[1]['close']
            else:
                self.current_price = self.d5_df_r.iloc[0]['close']
            self.current_price_by_df = self.current_price

        # # ■■　重複でAPIを打つことを避けたい
        if m5_df_r is not None:
            pass
        elif candleAnalysis.latest_df_d5_df_r is None:
            print("データ取得（同じデータがないため、新規で取得）")
            t1 = 0
            pass
        else:
            t1 = datetime.datetime.strptime(candleAnalysis.latest_df_d5_df_r.iloc[0]['time_jp'], "%Y/%m/%d %H:%M:%S")
            t2 = datetime.datetime.now()
            same = (t1.year == t2.year and
                    t1.month == t2.month and
                    t1.day == t2.day and
                    t1.hour == t2.hour and
                    t1.minute == t2.minute)
            print("既存のデータのfrom", candleAnalysis.latest_df_d5_df_r.iloc[0]['time_jp'])
            print("既存のDataFrameと同じかどうか？", same, t1, t2)
            if same:
                print("同じデータのたpeaks_class_30mめ、データ新規取得＆Peaks生成は呼ばず(主にcandleLCChangeで発生)  既存:", t1, ",現時刻:", t2)
                # データを移植する（5分足）
                self.d5_df_r = candleAnalysis.latest_df_d5_df_r
                self.peaks_class = candleAnalysis.latest_peaks_class
                self.candle_meta_class = candleAnalysis.latest_candle_meta_class
                # データを移植する（60分足）
                self.h1_df_r = candleAnalysis.latest_h1_df_r
                self.peaks_class_hour = candleAnalysis.latest_peaks_class_hour
                self.candle_meta_class_hour = candleAnalysis.latest_candle_meta_class_hour
                # データを移植する（30分足）
                self.d30_df_r = candleAnalysis.latest_df_d30_df_r
                self.peaks_class_m30 = candleAnalysis.latest_peaks_class_m30
                self.candle_meta_class_m30 = candleAnalysis.latest_candle_meta_class_m30
                return

        # ■■データ取得
        if m5_df_r is None:
            self.get_date_df(target_time_jp)  # 現在価格と、self.d5_df_rとself.h1_df_rを取得
        if self.d5_df_r is None:
            print("データ取得＆Peaks生成 失敗？？")
        else:
            print("現在時刻（本番時のみ意味あり）", datetime.datetime.now())
            print("データ取得＆Peaks生成  データfrom", self.d5_df_r.iloc[0]['time_jp'], "to", self.d5_df_r.iloc[-1]['time_jp'])

        # ■■処理続行判定
        # 重複作業防止用に、クラス変数に5分足の最初と最後の情報を入れておく
        if self.d5_df_r is None:
            print("★★ データフレームが取得されていないエラーが発生")
            return

        # ■■処理
        # データを取得する(5分足系）
        granularity = "M5"
        self.peaks_class = peaksClass.PeaksClass(self.d5_df_r, granularity, self.current_price, gene.currency_pair(self.pair))  # ★peaks_classの生成
        self.candle_meta_class = CandleMeta(self.peaks_class, granularity)

        # データを取得する（60分足）
        granularity = "H1"
        self.peaks_class_hour = peaksClass.PeaksClass(self.h1_df_r, granularity, self.current_price, gene.currency_pair(self.pair))
        self.candle_meta_class_hour = CandleMeta(self.peaks_class_hour, granularity)

        # データを取得する（30分足）
        granularity = "M30"
        self.peaks_class_m30 = peaksClass.PeaksClass(self.d30_df_r, granularity, self.current_price, gene.currency_pair(self.pair))
        self.candle_meta_class_m30 = CandleMeta(self.peaks_class_m30, granularity)

        if m5_df_r is not None:
            return

        # ■■重複作業防止用に、クラス変数に5分足の最初と最後の情報、今回算出した情報を入れておく
        if self.d5_df_r is None:
            # Noneの場合はおかしいので処理しない（基本ない）
            pass
        else:
            # クラス変数に、最新の値だけを入れておく
            candleAnalysis.avoid_dup_5min_kara_time = self.d5_df_r.iloc[-1]['time_jp']
            candleAnalysis.avoid_dup_5min_made_time = self.d5_df_r.iloc[0]['time_jp']
            candleAnalysis.latest_df_d5_df_r = self.d5_df_r
            candleAnalysis.latest_peaks_class = self.peaks_class  # 最新の物を持っておく（判定用に冗長に持っていて、そとからはインスタンス変数を参照がメイン。）
            candleAnalysis.latest_candle_meta_class = self.candle_meta_class
            candleAnalysis.latest_h1_df_r = self.h1_df_r
            candleAnalysis.latest_peaks_class_hour = self.peaks_class_hour  # 最新の物を持っておく（判定用に冗長に持っていて、そとからはインスタンス変数を参照がメイン。）
            candleAnalysis.latest_candle_meta_class_hour = self.candle_meta_class_hour
            candleAnalysis.latest_df_d30_df_r = self.d30_df_r
            candleAnalysis.latest_peaks_class_m30 = self.peaks_class_m30  # 最新の物を持っておく（判定用に冗長に持っていて、そとからはインスタンス変数を参照がメイン。）
            candleAnalysis.latest_candle_meta_class_m30 = self.candle_meta_class_m30

    def update_s5_df(self, target_time_jp=0):
        # パラメータの準備
        param = {"granularity": "S5", "count": 5}

        if target_time_jp == 0:
            # 現在時刻でやる場合
            s5_df_res = self.base_oa.InstrumentsCandles_multi_exe(self.pair, param, 1)
        else:
            # 指定の時刻でやる場合
            euro_time_datetime = target_time_jp - datetime.timedelta(hours=9)
            param["to"] = f"{euro_time_datetime.isoformat()}.000000000Z"
            s5_df_res = self.base_oa.InstrumentsCandles_exe(self.pair, param)

        # エラーチェック
        if s5_df_res['error'] == -1:
            print("error Candle")
            return -1

        # データフレームを時間降順で保存
        self.s5_df_r = s5_df_res['data'].sort_index(ascending=False)

    def get_date_df(self, target_time_jp):
        # データを取得する
        if target_time_jp == 0:
            # ■■■nowでやる場合（リアルトレード環境がメイン）
            # 5分足のデータ
            d5_df_res = self.base_oa.InstrumentsCandles_multi_exe(self.pair,
                                                                  {"granularity": "M5", "count": self.need_df_num},
                                                                  1)  # 時間昇順(直近が最後尾）
            if d5_df_res['error'] == -1:
                print("error Candle")
                tk.line_send("5分ごと調査最初のデータフレーム取得に失敗（エラー）")
                return -1
            else:
                d5_df_latest_bottom = d5_df_res['data']
            self.d5_df_r = d5_df_latest_bottom.sort_index(ascending=False)  # 直近が上の方にある＝時間降順に変更

            # 60分足のデータ
            h1_df_res = self.base_oa.InstrumentsCandles_multi_exe(self.pair,
                                                                   {"granularity": "H1", "count": self.need_df_num},
                                                                   1)  # 時間昇順(直近が最後尾）
            if h1_df_res['error'] == -1:
                print("error Candle")
                tk.line_send("60分ごと調査最初のデータフレーム取得に失敗（エラー）")
                return -1
            else:
                h1_df_latest_bottom = h1_df_res['data']
            self.h1_df_r = h1_df_latest_bottom.sort_index(ascending=False)  # 直近が上の方にある＝時間降順に変更

            # 5秒足で
            s5_df_res = self.base_oa.InstrumentsCandles_multi_exe(self.pair,
                                                                  {"granularity": "S5", "count": 5},
                                                                  1)  # 時間昇順(直近が最後尾）
            if s5_df_res['error'] == -1:
                print("error Candle")
                tk.line_send("5分ごと調査最初のデータフレーム取得に失敗（エラー）")
                return -1
            else:
                s5_df_latest_bottom = s5_df_res['data']
            self.s5_df_r = s5_df_latest_bottom.sort_index(ascending=False)  # 直近が上の方にある＝時間降順に変更

            # 30分足のデータ
            d30_df_res = self.base_oa.InstrumentsCandles_multi_exe(self.pair,
                                                                   {"granularity": "M30", "count": self.need_df_num},
                                                                   1)  # 時間昇順(直近が最後尾）
            if d30_df_res['error'] == -1:
                print("error Candle")
                tk.line_send("30分ごと調査最初のデータフレーム取得に失敗（エラー）")
                return -1
            else:
                m30_df_latest_bottom = d30_df_res['data']
            self.d30_df_r = m30_df_latest_bottom.sort_index(ascending=False)  # 直近が上の方にある＝時間降順に変更

            # ★★現在価格の取得（API）
            price_dic = self.base_oa.NowPrice_exe(self.pair)
            if price_dic['error'] == -1:  # APIエラーの場合はスキップ
                print("API異常発生の可能性@candleAnalysis")
                return -1  # 終了
            self.current_price = price_dic['data']['mid']
            self.current_price_by_df = self.d5_df_r.iloc[1]['close']  # 共通

        else:
            # ■■■指定の時刻でやる場合
            jp_time = target_time_jp
            euro_time_datetime = jp_time - datetime.timedelta(hours=9)
            euro_time_datetime_iso = str(euro_time_datetime.isoformat()) + ".000000000Z"  # ISOで文字型。.0z付き）

            # ５分足データ
            param = {"granularity": "M5", "count": self.need_df_num, "to": euro_time_datetime_iso}
            d5_df_res = self.base_oa.InstrumentsCandles_exe(self.pair, param) # 時間昇順(直近が最後尾）
            if d5_df_res['error'] == -1:
                print("error Candle")
                tk.line_send("5分ごと調査最初のデータフレーム取得に失敗（エラー）")
                return -1
            else:
                d5_df_latest_bottom = d5_df_res['data']
            self.d5_df_r = d5_df_latest_bottom.sort_index(ascending=False)  # 直近が上の方にある＝時間降順に変更

            # 60分足のデータ
            param = {"granularity": "H1", "count": self.need_df_num, "to": euro_time_datetime_iso}
            h1_df_res = self.base_oa.InstrumentsCandles_exe(self.pair, param) # 時間昇順(直近が最後尾）
            if h1_df_res['error'] == -1:
                print("error Candle")
                tk.line_send("60分ごと調査最初のデータフレーム取得に失敗（エラー）")
                return -1
            else:
                h1_df_latest_bottom = h1_df_res['data']
            self.h1_df_r = h1_df_latest_bottom.sort_index(ascending=False)  # 直近が上の方にある＝時間降順に変更

            # 最短の５秒足も取得しておく
            param = {"granularity": "S5", "count": 5, "to": euro_time_datetime_iso}
            s5_df_res = self.base_oa.InstrumentsCandles_exe(self.pair, param)  # 時間昇順(直近が最後尾）
            if s5_df_res['error'] == -1:
                print("error Candle")
                tk.line_send("60分ごと調査最初のデータフレーム取得に失敗（エラー）")
                return -1
            else:
                s5_df_latest_bottom = s5_df_res['data']
            self.s5_df_r = s5_df_latest_bottom.sort_index(ascending=False)  # 直近が上の方にある＝時間降順に変更

            # 最短の30分足も取得しておく
            param = {"granularity": "M30", "count": self.need_df_num, "to": euro_time_datetime_iso}
            d30_df_res = self.base_oa.InstrumentsCandles_exe(self.pair, param)  # 時間昇順(直近が最後尾）
            if d30_df_res['error'] == -1:
                print("error Candle")
                tk.line_send("30分ごと調査最初のデータフレーム取得に失敗（エラー）")
                return -1
            else:
                m30_df_latest_bottom = d30_df_res['data']
            self.d30_df_r = m30_df_latest_bottom.sort_index(ascending=False)  # 直近が上の方にある＝時間降順に変更
            # print(self.d30_df_r.head(3))

            # ★★★currentPriceの取得（APIを使わず、データから）
            self.current_price = self.d5_df_r.iloc[1]['close']
            self.current_price_by_df = self.d5_df_r.iloc[1]['close']

class CandleMeta:
    def __init__(self, peaks_class, granularity):
        """
        target_time_jpまでの時間を取得する
        """
        # データ入れる用
        self.df_r = peaks_class.df_r_original
        self.peaks_class = peaks_class
        self.pair = peaks_class.pair
        self.u = peaks_class.pair.round_keta
        # 初期値
        self.ave_move = 0
        self.ave_move_for_lc = 0
        self.dependence_large_body_criteria = self.pair.pips_to_price(10)

        # データを取得する(5分足系）
        if granularity == "M5":
            self.recent_fluctuation_range = 0  # 指定ではなく、計算で算出される。直近N足分以内での最大変動幅（最高値ー最低値）round済み
            self.fluctuation_gap = self.pair.pips_to_price(30)  # 急変動とみなす1足の変動は30pips以上。（1足でPeakの変動ではない）
            self.fluctuation_count = 3  # 3カウント以下でfluctuation_gapが起きた場合、急変動とみなす
            self.is_big_move_candle = False
        elif granularity == "H1":
            self.recent_fluctuation_range = 0  # 指定ではなく、計算で算出される。直近N足分以内での最大変動幅（最高値ー最低値）round済み
            self.fluctuation_gap = self.pair.pips_to_price(30)  # 急変動とみなす1足の変動は30pips以上。（1足でPeakの変動ではない）
            self.fluctuation_count = 3  # 3カウント以下でfluctuation_gapが起きた場合、急変動とみなす
            self.is_big_move_candle = False
        elif granularity == "M30":
            self.recent_fluctuation_range = 0  # 指定ではなく、計算で算出される。直近N足分以内での最大変動幅（最高値ー最低値）round済み
            self.fluctuation_gap = self.pair.pips_to_price(30)  # 急変動とみなす1足の変動は30pips以上。（1足でPeakの変動ではない）
            self.fluctuation_count = 3  # 3カウント以下でfluctuation_gapが起きた場合、急変動とみなす
            self.is_big_move_candle = False

        #
        self.cal_move_size()

    def cal_move_size(self):
        # ■データフレームの状態で、サイズ感を色々求める
        filtered_df = self.df_r[:65]  # 直近4時間の場合、12×4 48
        sorted_df = filtered_df.sort_values(by='body_abs', ascending=False)
        max_high = sorted_df["inner_high"].max()
        min_low = sorted_df['inner_low'].min()
        self.recent_fluctuation_range = round(max_high - min_low, self.u)
        self.ave_move = filtered_df.head(5)["highlow"].mean()
        self.ave_move_for_lc = self.ave_move * 1.6
        # print("   ＜稼働範囲サマリ＞")
        # print("    検出範囲", filtered_df.iloc[0]["time_jp"], "-", filtered_df.iloc[-1]['time_jp'])
        # print("    最大値、最小値", max_high, min_low, "差分")
        # print("    平均キャンドル長", filtered_df.head(5)["highlow"].mean())
        # print("    提唱LC幅", self.ave_move_for_lc)
        # print("    狭いレンジか？", self.peaks_class.hyper_range)
        # print(t6, "最大足(最高-最低),", sorted_df.iloc[0]['time_jp'], sorted_df.iloc[0]['highlow'])
        # print(t6, "最小足(最高-最低),", sorted_df.iloc[-1]['time_jp'], sorted_df.iloc[-1]['highlow'])
        # print(t6, "平均(最高-最低)", sorted_df['highlow'].mean())
        # print(t6, "最大足(Body),", sorted_df.iloc[0]['time_jp'], sorted_df.iloc[0]['body_abs'])
        # print(t6, "最小足(Body),", sorted_df.iloc[-1]['time_jp'], sorted_df.iloc[-1]['body_abs'])
        # print(t6, "平均(Body)", sorted_df['body_abs'].mean())

        # ■ピーク5個の中で突発的できわめて大きな変動がある場合（雇用統計とか、、、）基本は戻る動きとみる？（それとも静観・・・？）
        if len(self.peaks_class.peaks_original) == 1:
            # 極まれに範囲外になる。
            target_peak = self.peaks_class.peaks_original[0]
            # print("特殊事態（Peaksが少なすぎる）")
            gene.print_arr(self.peaks_class.peaks_original)
        else:
            target_peak = self.peaks_class.peaks_original[1]  # ビッグムーブ検査の対象となるのはひとつ前のピーク
        if self.peaks_class.peaks_original[0]['count'] == 2:
            # 重複オーダーとなる可能性をここで防止するため、ビッグムーブの判定はLatestカウントが2の場合のみ
            if target_peak['gap'] >= self.fluctuation_gap and target_peak['count'] <= self.fluctuation_count:
                # 変動が大きく、カウントは3まで（だらだらと長く進んでいる変動は突発的なビッグムーブではない）
                self.peaks_class.is_big_move_peak = True
                # tk.line_send("ビッグムーブ観測　cal_move_size関数@classPeaks")
            else:
                self.peaks_class.is_big_move_peak = False

        # ■ピークの直近5個分の平均値等を求める
        filtered_peaks = self.peaks_class.peaks_original[:5]
        peaks_ave = sum(item["gap"] for item in filtered_peaks) / len(filtered_peaks)
        # 最大値と最小値
        max_index, max_peak = max(enumerate(filtered_peaks[:]), key=lambda x: x[1]["peak"])
        min_index, min_peak = min(enumerate(filtered_peaks[:]), key=lambda x: x[1]["peak"])
        # 最大変動と最小変動
        max_gap_index, max_gap = max(enumerate(filtered_peaks[:]), key=lambda x: x[1]["gap"])
        min_gap_index, min_gap = min(enumerate(filtered_peaks[:]), key=lambda x: x[1]["gap"])
        other_max_gap_items = [item for item in filtered_peaks[:] if item != max_gap]
        # print(t6, "検出範囲ピーク",)
        # gene.print_arr(filtered_peaks, 6)
        # print(t6, peaks_ave)
        # print(t6, "変動幅検証関数　ここまで")
        # print(t6, "最大ギャップ", max_gap)
        # print(t6, other_max_gap_items)

        # ■足の長さが急変動があるかを確認
        filtered_df = self.peaks_class.df_r_original[:5]  # 直近4時間の場合、12×4 48
        sorted_df = filtered_df.sort_values(by='body_abs', ascending=False)
        max_body = sorted_df["body_abs"].max()
        if max_body >= self.dependence_large_body_criteria:
            self.is_big_move_candle = True
        else:
            self.is_big_move_candle = False
        # print("    大きな変動があるか？", self.is_big_move_candle)

    def cal_move_ave(self, times):
        """
        直近の動き幅のtimes倍の数値を返却する(直接LC Rangeに利用することを想定）
        """
        # ■データフレームの状態で、サイズ感を色々求める
        filtered_df = self.peaks_class.df_r_original[:65]  # 直近4時間の場合、12×4 48
        self.ave_move = filtered_df.head(9)["highlow"].mean()
        self.ave_move_for_lc = self.ave_move * times
        return self.ave_move_for_lc

