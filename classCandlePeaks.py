import datetime
from datetime import datetime
from datetime import timedelta
import pandas as pd
from collections import defaultdict
import tokens as tk
import fGeneric as gene
import fGeneric as f
import copy


class PeaksClass:

    def __init__(self, original_df_r, granularity):
        """
        処理解説
        make_peakでdf_rの直近一つのブロック（Peakと呼ぶ。同方向へローソクが進む範囲のこと。）を取得する。
          この関数での項目が全ての根底となる
        make_peaksでmake_peakを繰り返すことで、直近15個のブロック（＝peaksと呼ぶ）を取得する
        　またこのタイミングで、前後関係の追加と、PeaksのStrengthが付与される。
          peak_strengthはここで算出された後、recalculationで一部が上書きされる。
        算出されたPeakは粒度が細かすぎるため、skip_peaksを使い、粒度を荒くする。
        なおこの処理が実行されるのは、渡されたデータフレームが、登録されれているデータフレームと異なる場合のみ
        """
        print("PeaksClassInit", granularity)
        # ■■初期値の設定（Peak解析の基準）
        self.s = "     "
        # ■足の幅によって変わらない値
        self.max_peak_num = 60  # 30  # ピークを最大何個まで求めるか（昔はこれを15で使ってたが、今は時間で切る）。念のために残っている.
        self.analysis_num = 240  # この足の分のデータフレームを処理する（足ごとに設定）
        self.round_keta = 3  # 小数点何桁まで取得するか
        self.data_hold_peaks = 3  # 容量の関係で、直近のNピーク分のみ、データフレームも持つ。
        # ピークの強さの指標(点数)の設定（以下、peak_strengthを短縮のためにpsと略する）
        self.ps_default = 5  # ピーク基準値
        self.ps_most_most_min = 1  # 弱いピークに付与する値
        self.ps_most_min = 2  # 弱いピークに付与する値
        self.ps_min = 4  # 若干弱いピークに付与する値
        self.ps_most_max = 8  # 強いピークとみなす（直近数時間で最も高い（または低い）ピークの場合)　
        self.minimum = 0.0000001

        # ■足の幅で変わる値群
        if granularity == "M5":
            # MakePeaks時、ピークの強さを付与する場合、以下の数値以下の場合はピークの強さが弱くなる。makePeaksで利用。
            self.analysis_num = 180  # この足の分のデータフレームを処理する（足ごとに設定）
            self.peak_strength_border_min = 0.01
            self.peak_strength_border = 0.03  # この数字以下のピークは、問答無用で点数を下げる（self.ps_most_minにする）
            self.peak_strength_border_second = 0.07  # この数字より下（かつ上の数字より大きい）場合、countが少なければ強度弱となる。
            # SkipPeaksの際の基準(SkipPeaks関数）
            self.skip_gap_border = 0.045  # 0.045  # この値以下のGapをもつPeakは、スキップ処理の対象（これ以上の場合は、スキップ対象外）
            self.skip_gap_border_second = 0.05 #  0.05  # この値以下のGapを持つPeakは、重なり（ラップ）状況でスキップされる
            # 急変動(fluctuation)を検知する基準の設定　cal_move_size関数
            self.recent_fluctuation_range = 0.03  # 最大変動幅の4パーセント程度  # 指定ではなく、計算で算出される。直近N足分以内での最大変動幅（最高値ー最低値）round済み
            self.fluctuation_gap = 0.3  # 急変動とみなす1足の変動は30pips以上。（1足でPeakの変動ではない）
            self.fluctuation_count = 3  # 3カウント以下でfluctuation_gapが起きた場合、急変動とみなす
            # 抵抗線関係の値　cal_big_mountain関数
            self.arrowed_gap = 0.017  # 0.0245  # 抵抗線を探す時、ずれていてもいい許容値
            self.arrowed_break_gap = 0.02  # 抵抗線を探す時、これ以上越えていると、Breakしてると判断する範囲
            # 狭いレンジの期間の判定用の閾値
            self.check_very_narrow_range_range = 0.07  # 一つの足のサイズが、この閾値以下の場合、小さいレンジの可能性
            # 大きな動きのクライテリア
            self.dependence_very_large_body_criteria = 0.2
            self.dependence_large_body_criteria = 0.1
        elif granularity == "H1":
            # MakePeaks時、ピークの強さを付与する場合、以下の数値以下の場合はピークの強さが弱くなる。makePeaksで利用。
            self.analysis_num = 240  # この足の分のデータフレームを処理する（足ごとに設定）
            self.peak_strength_border_min = 0.05
            self.peak_strength_border = 0.15  # この数字以下のピークは、問答無用で点数を下げる（self.ps_most_minにする）
            self.peak_strength_border_second = 0.20  # この数字より下（かつ上の数字より大きい）場合、countが少なければ強度弱となる。
            # SkipPeaksの際の基準(SkipPeaks関数）
            self.skip_gap_border = 0.25  # 0.045  # この値以下のGapをもつPeakは、スキップ処理の対象（これ以上の場合は、スキップ対象外）
            self.skip_gap_border_second = 0.25 #  0.05  # この値以下のGapを持つPeakは、重なり（ラップ）状況でスキップされる
            # 急変動(fluctuation)を検知する基準の設定　cal_move_size関数
            self.recent_fluctuation_range = 0.03  # 最大変動幅の4パーセント程度  # 指定ではなく、計算で算出される。直近N足分以内での最大変動幅（最高値ー最低値）round済み
            self.fluctuation_gap = 0.3  # 急変動とみなす1足の変動は30pips以上。（1足でPeakの変動ではない）
            self.fluctuation_count = 3  # 3カウント以下でfluctuation_gapが起きた場合、急変動とみなす
            # 抵抗線関係の値　cal_big_mountain関数
            self.arrowed_gap = 0.03  # 抵抗線を探す時、ずれていてもいい許容値
            self.arrowed_break_gap = 0.04  # 抵抗線を探す時、これ以上越えていると、Breakしてると判断する範囲
            # 狭いレンジの期間の判定用の閾値
            self.check_very_narrow_range_range = 0.07  # 一つの足のサイズが、この閾値以下の場合、小さいレンジの可能性
            self.dependence_very_large_body_criteria = 0.2
            self.dependence_large_body_criteria = 0.1

        # ■■保存用の変数群（元々クラス変数だったものを、インスタンス変数に変更）
        # 基本となるデータフレーム
        self.df_r_original = None  # 直近の時刻が[0]となるデータフレーム。API取得のデータとは逆順
        # ピーク情報
        self.peaks_original = []  # 計算されたピークで、一番ベーシックなもの（DataFrameがない）
        self.peaks_original_with_df = []  # 要素にdataとdataFrameを持つ。SKipは結合させたりでめんどいのでやらない。
        self.skipped_peaks = []  # 計算された、スキップありのピーク
        self.skipped_peaks_hard = []  # 計算された、強いスキップありのピーク
        # self.peaks_original_marked_skip = []  # 使ってない？？
        # self.peaks_original_marked_hard_skip = []  # 使ってない？？　peaksとしてはオリジナル同様だが、スキップピークに、フラグが付いている物
        self.latest_resistance_line = {}  # Nullか、情報が入っているかのどちらか（Null＝抵抗線ではない）
        self.latest_price = 0  # 現在価格（場合よっては最新価格）
        self.latest_peak_price = 0  # 直近の折り返しのピーク(=turnのこと）
        self.gap_price_and_latest_turn_peak_abs = abs(self.latest_peak_price - self.latest_price)
        # 動きの数値化された情報
        self.is_big_move_peak = False
        self.is_big_move_candle = False
        self.ave_move = 0  # ここ5足程度の動きの大きさ（髭を含む）
        self.ave_move_for_lc = 0  # ここ5足程度の動きの大きさ（髭を含む）を加味した、LCの提案価格
        # 時間情報
        self.time_hour = 0
        # samePriceList関係
        self.same_price_list = []
        self.same_price_list_till_break = []
        self.same_price_list_till_break2 = []
        self.same_price_list_inner = []
        self.same_price_list_outer = []
        self.result_not_same_price_list = []
        self.opposite_peaks = []
        self.break_peaks = []
        self.break_peaks_inner = []
        self.break_peaks_outer = []
        self.peaks_with_same_price_list = []
        # 超レンジ判定
        self.hyper_range = False

        # ■実処理
        # (1)ピークスの算出
        self.df_r_original = original_df_r
        # print("直近価格", self.latest_price, original_df.iloc[0]['time_jp'])

        self.df_r = original_df_r[1:]  # df_rは先頭は省く（数秒分の足のため）
        self.df_r_copy = copy.deepcopy(self.df_r)
        self.df_r = self.df_r[:self.analysis_num]  # 直近4.5時間分(55足分)のデータフレームにする
        # print("API取得したデータ範囲　From", original_df_r.iloc[-1]['time_jp'], "to", original_df_r.iloc[0]['time_jp'])
        # print("調査範囲　From", self.df_r.iloc[-1]['time_jp'], "to", self.df_r.iloc[0]['time_jp'])
        temp_res = self.make_peaks(self.df_r)  # 一番感度のいいPeaks。引数は書くとするなら。self.df_r。
        self.peaks_original = temp_res['peaks']  # self.make_peaks(self.df_r)  # 一番感度のいいPeaks。引数は書くとするなら。self.df_r。
        # self.peaks_original_with_df = temp_res['peaks_with_df']  # self.make_peaks_with_df(self.df_r)  # 一番感度のいいPeaksにDfがついたもの

        # print("容量のテスト用", len(self.peaks_original_with_df))
        # for i, item in enumerate(self.peaks_original_with_df):
        #     print(item['latest_time_jp'], "-", item['oldest_time_jp'])
        #     print("    データサイズ", len(item['data']))
            # print(item['latest_time_jp'], len(item['data']))
            # print(item['data'].head(2))
            # print("↑Head")
            # print(item['data'].tail(2))
            # print("↑Tail")

        # たまに起きる謎のエラー対応
        if len(self.peaks_original) <= 2:
            tk.line_send("データがうまくとれていない。", len(original_df_r), "行のみ")
        self.skipped_peaks = self.skip_peaks()  # スキップピークの算出
        self.skipped_peaks_hard = self.skip_peaks_hard()
        self.recalculation_peak_strength_for_peaks()  # ピークストレングスの算出

        # (2) ある程度よく使う値は変数に入れておく
        self.latest_price = original_df_r.iloc[0]['open']
        self.latest_peak_price = self.peaks_original[0]['peak']
        self.gap_price_and_latest_turn_peak_abs = abs(self.latest_price - self.latest_peak_price)
        # print("直近価格", self.latest_price)
        # print("直近ピーク", self.latest_peak_price)

        # (3) 時間の取得
        time_obj = pd.to_datetime(original_df_r.iloc[0]['time_jp'], format='%Y/%m/%d %H:%M:%S')
        self.time_hour = time_obj.hour

        # (4)追加の機能（直近の数個が承服しすぎているかどうかの確認）
        # self.check_very_narrow_range(self.df_r)

        # (5)samePriceListを、各Peakに付与する
        for i, item in enumerate(self.peaks_original):
            # print("同価格リストの生成")
            # print(self.s, i, item['latest_time_jp'], item['latest_body_peak_price'])
            spl_res = self.make_same_price_list(i, False)
            spl = spl_res['same_price_list']
            # print(" ", len(spl))
            item_copy = copy.deepcopy(item)
            item_copy['same_price_list'] = spl
            item_copy['same_price_list_till_break'] = spl_res['till_break_list']
            item_copy['same_price_list_till_break0'] = spl_res['till_break_list2']
            item_copy['opposite_peaks'] = spl_res['opposite_peaks']
            self.peaks_with_same_price_list.append(item_copy)

        # 一番シンプルなpeaks_originalを作成する（長くなる要素を消して、表示がしやすいようにする）
        # peaks_original = copy.deepcopy(self.peaks_original)# 深いコピーを作成
        # for d in peaks_original:# 指定キーを削除
        #     d.pop('next', None)
        #     d.pop('previous_time_peak', None)
        #     d.pop('support_info', None)
        #     d.pop('memo_time', None)

        # (4) 表示
        s = "   "

        # print(s, "<SKIP前>", )
        # gene.print_arr(peaks_original[:10])
        # print("   |")
        # gene.print_arr(peaks_original[-2:])

        # print("")
        # print(s, "<SKIP後　対象>")
        # skipped_peaks = copy.deepcopy(self.skipped_peaks)# 深いコピーを作成
        # for d in skipped_peaks:# 指定キーを削除
        #     d.pop('next', None)
        #     d.pop('previous_time_peak', None)
        #     d.pop('support_info', None)
        #     d.pop('memo_time', None)
        # gene.print_arr(skipped_peaks[:10])

        # print("")
        # print(s, "<hard SKIP後　対象>")
        # skipped_peaks_hard = copy.deepcopy(self.skipped_peaks_hard)# 深いコピーを作成
        # for d in skipped_peaks_hard:# 指定キーを削除
        #     d.pop('next', None)
        #     d.pop('previous_time_peak', None)
        #     d.pop('support_info', None)
        #     d.pop('memo_time', None)
        # gene.print_arr(skipped_peaks_hard[:10])

        # print("")
        # print(s, "<hard SKIPのフラグのみ")
        # gene.print_arr(self.peaks_original_marked_hard_skip[:15])

        #  (重要)

        #  (1)大きなレンジをターンストレングスで判断する場合
        # self.peak_strength_sort()

        # (3)samePriceの算出
        # self.make_same_price_list(1, False)  # スタンダードな引数で出しておく

    def make_peak(self, df_r):
        """
        渡された範囲で、何連続で同方向に進んでいるかを検証する
        :param df_r: 直近が上側（日付降順/リバース）のデータを利用
        :return: Dict形式のデータを返伽
        """
        # コピーウォーニングのための入れ替え
        data_df = df_r  # メモリ削減のため.copy()は削除
        temp = self.df_r_original  # Warning回避のため（staticにしろって言われるから）
        # 返却値を設定
        ans_dic = {
            "latest_time_jp": 0,  # これがpeakの時刻
            "oldest_time_jp": 0,
            "direction": 1,
            "latest_body_peak_price": 0,  # これがpeakの価格
            "oldest_body_peak_price": 0,
            "latest_wick_peak_price": 0,
            "oldest_wick_peak_price": 0,
            "peak_strength": self.ps_default,  # この関数では付与されない（単品では判断できない）。make_peaks関数で前後のPeakを加味して付与される
            "count": 0,  # 最新時刻からスタートして同じ方向が何回続いているか
            "data_size": len(data_df),  # (注)元のデータサイズ
            "latest_price": 0,
            "oldest_price": 0,
            "gap": self.minimum,
            "gap_high_low": self.minimum,
            "gap_close": self.minimum,
            "body_ave": self.minimum,
            "move_abs": self.minimum,
            "memo_time": 0,
            "data": data_df,  # 対象となるデータフレーム（元のデータフレームではない）
            "data_remain": data_df,  # 対象以外の残りのデータフレーム
            # "data_from": 0,  # dataが容量的に持てない場合、スライスで指定するためのStartの添え字を確保
            # "data_to": 0,
            # "data_remain_from": 0,
            # "data_remain_to": 0,
            "support_info": {},
            "include_large": False,
            "include_very_large": False,
            # 古いのと互換性を持つための項目たち
            "time": 0,  # ピーク時刻（重複するが、わかりやすい名前で持っておく）
            "peak": 0,  # ピーク価格（重複するが、わかりやすい名前で持っておく）
            "time_old": 0,
            "peak_old": 0,
            "skip_include_num":0  # SKIP関数を通した場合、ここにピークの中で何回スキップしたかが入る
        }
        if len(data_df) <= 1:  # データが１つ以上存在していれば実施
            return ans_dic

        # 実処理処理の開始
        base_direction = 0
        counter = 0
        for i in range(len(data_df) - 1):
            tilt = data_df.iloc[i]['middle_price'] - data_df.iloc[i + 1]['middle_price']
            # tilt = data_df.iloc[i]['middle_price_wick'] - data_df.iloc[i + 1]['middle_price_wick']
            if tilt == 0:
                tilt = self.minimum
            tilt_direction = round(tilt / abs(tilt), 0)  # 方向のみ（念のためラウンドしておく）
            # ■初回の場合の設定。１行目と２行目の変化率に関する情報を取得、セットする
            if counter == 0:
                base_direction = tilt_direction
            else:
                # print(" 初回ではありません")
                pass

            # ■カウントを進めていく
            if tilt_direction == base_direction:  # 今回の検証変化率が、初回と動きの方向が同じ場合
                counter += 1
            else:
                break  # 連続が途切れた場合、ループを抜ける
        # ■対象のDFを取得し、情報を格納していく
        self.df_r_copy = self.df_r_copy[counter:]
        ans_df = data_df[0:counter + 1]  # 同方向が続いてる範囲のデータを取得する
        ans_other_df = data_df[counter:]  # 残りのデータ
        # print("DATAの範囲の検討")
        # print("から", ans_df.index[0], "まで", ans_df.index[-1])
        # print(ans_df)
        # print("まで", ans_other_df.index[0], "まで", ans_other_df.index[-1])
        # print(ans_other_df)

        if base_direction == 1:
            # 上り方向の場合、直近の最大価格をlatest_image価格として取得(latest価格とは異なる可能性あり）
            latest_body_price = ans_df.iloc[0]["inner_high"]
            oldest_body_price = ans_df.iloc[-1]["inner_low"]
            latest_wick_price = ans_df.iloc[0]["high"]
            oldest_wick_price = ans_df.iloc[-1]["low"]
        else:
            # 下り方向の場合
            latest_body_price = ans_df.iloc[0]["inner_low"]
            oldest_body_price = ans_df.iloc[-1]["inner_high"]
            latest_wick_price = ans_df.iloc[0]["low"]
            oldest_wick_price = ans_df.iloc[-1]["high"]
        #
        # ■平均移動距離等を考える
        body_ave = round(data_df["body_abs"].mean(), self.round_keta)
        move_ave = round(data_df["moves"].mean(), self.round_keta)

        # ■GAPを計算する（０の時は割る時とかに困るので、最低0.001にしておく）
        # gap = round(abs(latest_body_price - oldest_body_price), 3)  # MAXのサイズ感
        gap_close = round(abs(latest_body_price - ans_df.iloc[-1]["close"]), self.round_keta)  # 直近の価格（クローズの価格&向き不問）
        if gap_close == 0:
            gap_close = self.minimum
        else:
            gap_close = gap_close

        gap = round(abs(latest_body_price - oldest_body_price), self.round_keta)  # 直近の価格（クローズの価格&向き不問）
        if gap == 0:
            gap = self.minimum
        else:
            gap = gap

        gap_high_low = round(abs(latest_wick_price - oldest_wick_price), self.round_keta)  # 直近の価格（クローズの価格&向き不問）
        if gap_high_low == 0:
            gap_high_low = self.minimum
        else:
            gap_high_low = gap_high_low

        # ■　返却用にans_dicを上書き
        ans_dic['direction'] = base_direction
        ans_dic["count"] = counter + 1  # 最新時刻からスタートして同じ方向が何回続いているか
        ans_dic["data_size"] = len(data_df)  # (注)元のデータサイズ
        ans_dic["latest_body_peak_price"] = latest_body_price
        ans_dic["oldest_body_peak_price"] = oldest_body_price
        ans_dic["oldest_time_jp"] = ans_df.iloc[-1]["time_jp"]
        ans_dic["latest_time_jp"] = ans_df.iloc[0]["time_jp"]  # これがピークの時刻
        ans_dic["latest_price"] = ans_df.iloc[0]["close"]
        ans_dic["oldest_price"] = ans_df.iloc[-1]["open"]
        ans_dic["latest_wick_peak_price"] = latest_wick_price
        ans_dic["oldest_wick_peak_price"] = oldest_wick_price
        ans_dic["gap"] = gap
        ans_dic["gap_high_low"] = gap_high_low
        ans_dic["gap_close"] = gap_close
        ans_dic["body_ave"] = body_ave
        ans_dic["move_abs"] = move_ave
        ans_dic["data"] = ans_df  # 対象となるデータフレーム（元のデータフレームではない）
        ans_dic["data_remain"] = ans_other_df  # 対象以外の残りのデータフレーム
        # ans_dic["data_from"] = 0  # dataが容量的に持てない場合、スライスで指定するためのStartの添え字を確保
        # ans_dic["data_to"] = 0
        # ans_dic["data_remain_from"] = 0
        # ans_dic["data_remain_to"] = 0
        ans_dic["memo_time"] = f.str_to_time_hms(ans_df.iloc[-1]["time_jp"]) + "_" + f.str_to_time_hms(
            ans_df.iloc[0]["time_jp"])  # 表示に利用する時刻表示用
        # 追加項目
        ans_dic['include_large'] = self.check_large_body_in_peak(ans_dic)['include_large']
        ans_dic['include_very_large'] = self.check_large_body_in_peak(ans_dic)['include_very_large']
        ans_dic['highest'] = self.check_large_body_in_peak(ans_dic)['highest']
        ans_dic['lowest'] = self.check_large_body_in_peak(ans_dic)['lowest']
        # 互換性確保のため、データとしては重複するが、名前を変えて所持しているもの達（いつか消したいけど)
        ans_dic["time"] = ans_dic["latest_time_jp"]  # ピーク時刻（Latest）
        ans_dic["peak"] = ans_dic["latest_body_peak_price"]  # ピークのボディ価格（Latest。方向ごと）
        ans_dic["time_old"] = ans_dic["oldest_time_jp"]  #
        ans_dic["peak_old"] = ans_dic["oldest_body_peak_price"]  # 重複するが、わかりやすい名前で持っておく
        # 返却する
        return ans_dic

    def make_peaks(self, df_r):
        """
        リバースされたデータフレーム（直近が上）から、ピークを一覧にして返却する これがメイン
        :return:
        """
        # ■引数の整理
        # df_r = df_r.copy()  # メモリ削減のためコピー削除

        # ■処理の開始
        peaks = []  # 結果格納用
        peaks_with_df = []  #結果格納用
        next_time_peak = {}  # 処理的に次（時間的には後）のピークとして保管
        for i in range(222):
            if len(df_r) == 0:
                break
            # ■ピークの取得
            this_peak = self.make_peak(df_r)

            # ■ループ終了処理　ループ終了、または、 重複対策（←原因不明なので、とりあえず入れておく）
            if len(peaks) != 0 and peaks[-1]['latest_time_jp'] == this_peak['latest_time_jp']:
                # 最後が何故か重複しまくる！時間がかぶったら何もせず終了
                break
            elif len(peaks) > self.max_peak_num:
                # 終了（ピーク数検索数が上限に到達した場合）
                break

            # ■（エラー対応 基本必須）timeが０のものが最後に追加されるケース有。
            if this_peak['time'] == 0:
                break

            # ■■■■■■■■peaks WithDFの場合、前後関係を持たずに、このまま追加していく(容量削減を実施）
            if i <= self.data_hold_peaks:  # 容量の関係で、最初の10ピーク分のみ、DFを入れる
                # print("最初の20行以内", this_peak['latest_time_jp'], "-", this_peak['oldest_time_jp'])
                cols_to_keep = [  # 残したいカラム名
                    "time_jp", "open", "close", "high", "low",
                    "mid_outer", "inner_high", "inner_low",
                    "body", "body_abs", "bb_range"
                ]
                # cols_to_keep = [  # カラム名のメモ用
                #     "time_jp", "open", "close", "high", "low",
                #     "mid_outer", "inner_high", "inner_low",
                #     "body", "body_abs", "bb_range"
                # ]
                this_peak_copy = copy.deepcopy(this_peak)  # コピーを取る（参照先のthis_peaks自体は後で変更するため）
                this_peak_copy['data'] = this_peak_copy['data'][[c for c in cols_to_keep if c in this_peak_copy['data'].columns]]
                peaks_with_df.append(copy.deepcopy(this_peak))  # deepcopyで入れていく
            else:
                # print("20行以降", this_peak['latest_time_jp'], "-", this_peak['oldest_time_jp'])
                this_peak_copy = copy.deepcopy(this_peak)
                this_peak_copy['data'] = pd.DataFrame()
                this_peak_copy['data_remain'] = pd.DataFrame()
                peaks_with_df.append(this_peak_copy)

            # ■■■■■■■■シンプルなPeaksの場合、DFを消して、前後関係を追加する
            # peakの簡素化
            this_peak.pop('data', None)  # DataFrameを削除する# 存在しない場合はエラーを防ぐためにデフォルト値を指定
            this_peak.pop('data_remain', None)  # DataFrameを削除する
            # peakのコピーを生成（PreviousやNextがない状態）
            this_peak_simple_copy = this_peak.copy()  # 処理的に次（時間的には後）のピークとして保管
            # 後ピークの追加（時間的に後）
            this_peak['next'] = next_time_peak
            next_time_peak = this_peak_simple_copy  # 処理的に次（時間的には後）のピークとして保管
            # 前関係の追加 (現在処理⇒Peak,ひとつ前の処理（時間的には次）はpeaks[-1])
            if i != 0:
                # 先頭以外の時(next_timeはある状態。previousは次の処理で取得される）。先頭の時は実施しない。
                peaks[-1]['previous_time_peak'] = this_peak_simple_copy  # next_timeのpreviousに今回のpeakを追加
                peaks[-1]['previous'] = this_peak_simple_copy
            # 結果を追加
            peaks.append(this_peak)  # 情報の蓄積

            # ■ループ処理
            df_r = df_r[this_peak['count'] - 1:]  # 処理データフレームを次に進める

        # ■■■■■■■■ピークの強さを付与する(最大１0）
        for i, item in enumerate(peaks):
            # ほとんどスキップと同じ感じだが、Gapが0.05以下の場合は問答無用で低ランク
            # Gapがクリアしても、両側に比べて小さい場合、低ランク
            if i == 0 or i == len(peaks) - 1:
                continue

            # わかりやすく命名 （vanish_itemは中央のアイテムを示す）
            latest_item = peaks[i - 1]
            oldest_merged_item = peaks[i + 1]

            # 判定1 (サイズによる判定）
            count_border = 2
            if (item['gap'] <= self.peak_strength_border or
                    (item['gap'] <= self.peak_strength_border_second and item['count'] <= count_border)):
                if item['gap'] <= self.peak_strength_border_min:
                    # ほぼ見えないレベルの折り返しは点数を最も低くする
                    item['peak_strength'] = self.ps_most_most_min  # これで元データ入れ替えられるんだ？！
                    peaks[i + 1]['peak_strength'] = self.ps_most_most_min  # ひとつ前(時間的はOldest）のPeakも強制的にStrengthが1となる
                    print("peaks test1", item['latest_time_jp'], item['gap'])
                    continue
                # このアイテムのGapが小さい場合、直前も低くなる事に注意
                item['peak_strength'] = self.ps_most_min  # これで元データ入れ替えられるんだ？！
                peaks[i + 1]['peak_strength'] = self.ps_most_min  # ひとつ前(時間的はOldest）のPeakも強制的にStrengthが1となる
                continue

            # 判定2　（両サイドとの比率による判定）
            item_latest_ratio = item['gap'] / latest_item['gap']
            item_oldest_ratio = item['gap'] / oldest_merged_item['gap']
            overlap_ratio = 0.4  # ラップ率のボーダー値　(0.7以上でラップ大。0.7以下でラップ小）
            overlap_ratio_2 = 0.65
            if item_latest_ratio <= overlap_ratio and item_oldest_ratio <= overlap_ratio:
                # このアイテムのGapが小さい場合、直前も低くなる事に注意
                # print("ラップ率が両サイドに比べてかなり低い⇒ほぼスキップされる）
                # print("", item['time'], latest_item['time'], oldest_merged_item['time'])
                # print("", item['gap'], latest_item['gap'], oldest_merged_item['gap'])
                # print("Peak現象判定(直近との比率）", item_latest_ratio,)
                # print("Peak現象判定(直古との比率）", item_oldest_ratio,)
                item['peak_strength'] = self.ps_most_min  # これで元データ入れ替えられるんだ？！
                peaks[i + 1]['peak_strength'] = self.ps_most_min  # ひとつ前(時間的はOldest）のPeakも強制的にStrengthが1となる
                print("peaks test", item['latest_time_jp'], item['gap'])
            elif item_latest_ratio <= overlap_ratio and item_oldest_ratio <= overlap_ratio:
                # print("ラップ率が両サイドに比べてそこそこ低め⇒多少スキップの可能性が上がる）
                # print("", item['time'], latest_item['time'], oldest_merged_item['time'])
                # print("", item['gap'], latest_item['gap'], oldest_merged_item['gap'])
                # print("Peak現象判定(直近との比率）", item_latest_ratio,)
                # print("Peak現象判定(直古との比率）", item_oldest_ratio,)
                item['peak_strength'] = self.ps_min  # これで元データ入れ替えられるんだ？！
                peaks[i + 1]['peak_strength'] = self.ps_min  # ひとつ前(時間的はOldest）のPeakも強制的にStrengthが1となる
        # return peaks
        return {
            "peaks": peaks,
            "peaks_with_df": peaks_with_df
        }

    # def make_peaks_with_df(self, df_r):
    #     """
    #     リバースされたデータフレーム（直近が上）から、ピークを一覧にして返却する
    #     この関数では、対応するデータフレームをつけた状態で返却する。
    #     ただし速度の関係で、前後関係を示す情報は所持しない
    #     :return:
    #     """
    #     # ■引数の整理
    #     # df_r = df_r.copy()  # メモリ削減のためコピー削除
    #
    #     # ■処理の開始
    #     peaks = []  # 結果格納用
    #     next_time_peak = {}  # 処理的に次（時間的には後）のピークとして保管
    #     for i in range(222):
    #         if len(df_r) == 0:
    #             break
    #         # ■ピークの取得
    #         this_peak = self.make_peak(df_r)
    #
    #         # ■ループ終了処理　ループ終了、または、 重複対策（←原因不明なので、とりあえず入れておく）
    #         if len(peaks) != 0 and peaks[-1]['latest_time_jp'] == this_peak['latest_time_jp']:
    #             # 最後が何故か重複しまくる！時間がかぶったら何もせず終了
    #             break
    #         elif len(peaks) > self.max_peak_num:
    #             # 終了（ピーク数検索数が上限に到達した場合）
    #             break
    #
    #         # ■（エラー対応 基本必須）timeが０のものが最後に追加されるケース有。
    #         if this_peak['time'] == 0:
    #             break
    #
    #         # # ■■■■■■■■実処理の追加(前後関係の追加）
    #         # # peakの簡素化
    #         # # peakのコピーを生成（PreviousやNextがない状態）
    #         # this_peak_simple_copy = this_peak.copy()  # 処理的に次（時間的には後）のピークとして保管
    #         # # 後ピークの追加（時間的に後）
    #         # this_peak['next'] = next_time_peak
    #         # next_time_peak = this_peak_simple_copy  # 処理的に次（時間的には後）のピークとして保管
    #         # # 前関係の追加 (現在処理⇒Peak,ひとつ前の処理（時間的には次）はpeaks[-1])
    #         # if i != 0:
    #         #     # 先頭以外の時(next_timeはある状態。previousは次の処理で取得される）。先頭の時は実施しない。
    #         #     peaks[-1]['previous_time_peak'] = this_peak_simple_copy  # next_timeのpreviousに今回のpeakを追加
    #         #     peaks[-1]['previous'] = this_peak_simple_copy
    #         # 結果を追加
    #         peaks.append(this_peak)  # 情報の蓄積
    #
    #         # ■ループ処理
    #         df_r = df_r[this_peak['count'] - 1:]  # 処理データフレームを次に進める
    #
    #     # ■■■■■■■■ピークの強さを付与する(最大１0）
    #     for i, item in enumerate(peaks):
    #         # ほとんどスキップと同じ感じだが、Gapが0.05以下の場合は問答無用で低ランク
    #         # Gapがクリアしても、両側に比べて小さい場合、低ランク
    #         if i == 0 or i == len(peaks) - 1:
    #             continue
    #
    #         # わかりやすく命名 （vanish_itemは中央のアイテムを示す）
    #         latest_item = peaks[i - 1]
    #         oldest_merged_item = peaks[i + 1]
    #
    #         # 判定1 (サイズによる判定）
    #         count_border = 2
    #         if (item['gap'] <= self.peak_strength_border or
    #                 (item['gap'] <= self.peak_strength_border_second and item['count'] <= count_border)):
    #             # このアイテムのGapが小さい場合、直前も低くなる事に注意
    #             item['peak_strength'] = self.ps_most_min  # これで元データ入れ替えられるんだ？！
    #             peaks[i + 1]['peak_strength'] = self.ps_most_min  # ひとつ前(時間的はOldest）のPeakも強制的にStrengthが1となる
    #             continue
    #
    #         # 判定2　（両サイドとの比率による判定）
    #         item_latest_ratio = item['gap'] / latest_item['gap']
    #         item_oldest_ratio = item['gap'] / oldest_merged_item['gap']
    #         overlap_ratio = 0.4  # ラップ率のボーダー値　(0.7以上でラップ大。0.7以下でラップ小）
    #         overlap_ratio_2 = 0.65
    #         if item_latest_ratio <= overlap_ratio and item_oldest_ratio <= overlap_ratio:
    #             # このアイテムのGapが小さい場合、直前も低くなる事に注意
    #             # print("ラップ率が両サイドに比べてかなり低い⇒ほぼスキップされる）
    #             # print("", item['time'], latest_item['time'], oldest_merged_item['time'])
    #             # print("", item['gap'], latest_item['gap'], oldest_merged_item['gap'])
    #             # print("Peak現象判定(直近との比率）", item_latest_ratio,)
    #             # print("Peak現象判定(直古との比率）", item_oldest_ratio,)
    #             item['peak_strength'] = self.ps_most_min  # これで元データ入れ替えられるんだ？！
    #             peaks[i + 1]['peak_strength'] = self.ps_most_min  # ひとつ前(時間的はOldest）のPeakも強制的にStrengthが1となる
    #         elif item_latest_ratio <= overlap_ratio and item_oldest_ratio <= overlap_ratio:
    #             # print("ラップ率が両サイドに比べてそこそこ低め⇒多少スキップの可能性が上がる）
    #             # print("", item['time'], latest_item['time'], oldest_merged_item['time'])
    #             # print("", item['gap'], latest_item['gap'], oldest_merged_item['gap'])
    #             # print("Peak現象判定(直近との比率）", item_latest_ratio,)
    #             # print("Peak現象判定(直古との比率）", item_oldest_ratio,)
    #             item['peak_strength'] = self.ps_min  # これで元データ入れ替えられるんだ？！
    #             peaks[i + 1]['peak_strength'] = self.ps_min  # ひとつ前(時間的はOldest）のPeakも強制的にStrengthが1となる
    #
    #
    #     return peaks

    # def check_very_narrow_range(self, df_r):
    #     """
    #     与えられたデータの直近数個が、「きわめてレンジ」といえるか。
    #     ほとんど動きがないような状態。
    #     直近数個の中で、最大の物(8pips以内）を探し、その中に70％以上入っている足の割合が多い
    #     """
    #     target = 4  # 直近4個分
    #     df = df_r[0:target]  # メモリ削減のため.copy()削除  # 同方向が続いてる範囲のデータを取得する
    #
    #     max_gap_row = df.loc[df['body_abs'].idxmax()]
    #     max_gap_value = df['body_abs'].max()
    #     upper = max_gap_row['inner_high']
    #     lower = max_gap_row['inner_low']
    #     if max_gap_value >= self.check_very_narrow_range_range:  # 一つの足の幅が７pip以上の場合は動き大き目のため、除外
    #         is_mini_range = False
    #     else:
    #         # 各行の区間長
    #         df['range_len'] = (df['inner_low'] - df['inner_high']).abs()
    #
    #         # 各行の重なり開始と終了
    #         overlap_start = df[['inner_low', 'inner_high']].min(axis=1).clip(lower, upper)
    #         overlap_end = df[['inner_low', 'inner_high']].max(axis=1).clip(lower, upper)
    #
    #         # 重なり長さ（負にならないよう0でクリップ）
    #         df['overlap_len'] = (overlap_end - overlap_start).clip(lower=0)
    #
    #         # はみ出し長さと割合
    #         df['exceed_len'] = df['range_len'] - df['overlap_len']
    #         df['exceed_ratio_with_self'] = df['exceed_len'] / df['range_len']
    #         df['exceed_ratio_with_max'] = df['exceed_len'] / max_gap_value
    #
    #         # 割合（％なら×100）
    #         df['overlap_ratio_with_self'] = df['overlap_len'] / df['range_len']
    #         df['overlap_ratio_with_max'] = df['overlap_len'] / max_gap_value
    #
    #         # print("超レンジ可の判定用")
    #         # print("最大Body", max_gap_row['time_jp'])
    #         # print(df[['time_jp', 'overlap_ratio_with_max','exceed_ratio_with_max']])
    #         is_mini_range = ((df['exceed_ratio_with_max'] <= 0.24) & (df['overlap_ratio_with_max'] >= 0.4)).all()
    #
    #     # print("〇超レンジ判定⇒", is_mini_range)
    #     self.hyper_range = is_mini_range

    def recalculation_peak_strength_for_peaks(self):
        """
        ここ数時間で最大（または最小）のピーク値には、高得点を付与する
        """
        # 対象
        peaks = self.peaks_original
        # peak が最大の要素を取得
        max_peak_element = max(peaks, key=lambda x: x["peak"])
        max_peak_element["peak_strength"] = self.ps_most_max  # strength を 10 に変更
        # print("最大の要素", max_peak_element)

        # peak が最小の要素を取得
        min_peak_element = min(peaks, key=lambda x: x["peak"])
        min_peak_element["peak_strength"] = self.ps_most_max  # strength を 10 に変更
        # print("最小の要素", min_peak_element)

        # 追加要素　（最大の-1方向の抵抗値は、弱い（最大の1方向が強いわけだから））
        max_price_neg1_dict = max(
            (p for p in peaks if p['direction'] == -1),
            key=lambda p: p['peak'],
            default=None
        )
        if max_price_neg1_dict is not None:
            # 安全にアクセスできる
            max_price_neg1_dict['peak_strength'] = self.ps_most_min
        else:
            print("direction == -1 のデータが見つかりませんでした")
            gene.print_arr(peaks)
            # tk.line_send(" Maxに対する　peak_strength （classPeaks 395行目） のエラー発生（-1が見つからなかった）")
        # max_price_neg1_dict['peak_strength'] = self.ps_most_max  # minになってたけど・・・？

        # directionが1の中で最小のprice
        min_price_pos1_dict = min(
            (p for p in peaks if p['direction'] == 1),
            key=lambda p: p['peak'],
            default=None
        )
        if min_price_pos1_dict is not None:
            # 安全にアクセスできる
            min_price_pos1_dict['peak_strength'] = self.ps_most_min
        else:
            print("direction == 1 のデータが見つかりませんでした")
            gene.print_arr(peaks)
            # tk.line_send(" Minに対する　peak_strength （classPeaks 404行目） のエラー発生（1が見つからなかった）")

    def peak_strength_sort(self):
        """
        ピークの強さでソートして、長い目で見て強いピークを検討する。
        （ターンピークに注目することが多いが、全体から見てどのくらいなのか、を判定したい）
        """
        # direction別にまとめる
        peaks_by_dir = defaultdict(list)
        for peak in self.peaks_original:
            peaks_by_dir[peak["direction"]].append(peak)

        # directionごとに peak_strength 降順でソート
        sorted_peaks_by_dir = {
            d: sorted(lst, key=lambda x: x["peak_strength"], reverse=True)
            for d, lst in peaks_by_dir.items()
        }
        # print("!!classPeaks 608行目")
        # print("-1側")
        # gene.print_arr(sorted_peaks_by_dir[-1])
        # print("1側")
        # gene.print_arr(sorted_peaks_by_dir[1])
        return (
            {"-1":  sorted_peaks_by_dir[-1], "1": sorted_peaks_by_dir[1]}
        )

    def skip_peaks(self):
        """
        peaksを受け取り、必要に応じてスキップする
        """
        s4 = "    "
        # print(s4, "SKIP Peaks")
        s4 = "    "
        # print(s4, "SKIP Peaks")
        adjuster = 0
        peaks = copy.deepcopy(self.peaks_original)  # PeaksClass.peaks_original.copy()では浅いコピーとなる
        # # フラグつけ用
        # self.peaks_original_marked_skip = copy.deepcopy(self.peaks_original)
        # for item in self.peaks_original_marked_skip:
        #     item["skipped"] = False
        skip_counter = 0  # 何個スキップしたかをカウントする（フラグ付けのループの個数調整で利用。）
        i = 1
        while i < len(peaks) - 1:  # 中で配列を買い替えるため、for i in peaksは使えない！！
            vanish_num = i + adjuster  # 削除後に、それを起点にもう一度削除処理ができる
            if vanish_num == 0 or vanish_num >= len(peaks) - 1:
                # print("最初か最後のため、Vanish候補ではない", vanish_num, latest_item)
                i = i + 1
                continue

            # わかりやすく命名 （vanish_itemは中央のアイテムを示す）
            latest_num = vanish_num - 1
            latest_item = peaks[latest_num]
            oldest_merged_num = vanish_num + 1
            oldest_merged_item = peaks[oldest_merged_num]
            vanish_item = peaks[vanish_num]

            # ■スキップ判定 (vanishは真ん中のPeakを意味する）
            # (0)スキップフラグの設定
            is_skip = False
            # (1)基本判定 サイズが小さいときが対象
            count_border = 2
            if vanish_item['count'] <= count_border and vanish_item['gap'] <= self.skip_gap_border:
                pass
                # print(s4,s4, "小さい調査対象　vanish_item:", vanish_item['time'], vanish_item['count'], vanish_item['gap'])
                is_skip = True
            else:
                # そこそこサイズがあるので、スキップ
                # print(s4,s4, "サイズあるためスキップ　vanish_item:", vanish_item['time'], vanish_item['count'], vanish_item['gap'])
                i = i + 1
                continue

            # (2)ラップ判定
            # 変数の設定
            vanish_latest_ratio = vanish_item['gap'] / latest_item['gap']
            vanish_oldest_ratio = vanish_item['gap'] / oldest_merged_item['gap']
            # 判定１
            overlap_ratio = 0.6  # ラップ率のボーダー値　(0.7以上でラップ大。0.7以下でラップ小）
            overlap_min_ratio = 0.35
            # print(s4, s4, "latest", latest_item['time'], latest_item['gap'], "oldest", oldest_merged_item['time'], oldest_merged_item['gap'])
            # print(s4, s4, "  vanish:", vanish_item['time'], "vanish_latest_ratio:", vanish_latest_ratio, ",vanish_oldest_ratio:", vanish_oldest_ratio)
            if vanish_latest_ratio >= overlap_ratio and vanish_oldest_ratio >= overlap_ratio:
                # 両サイドが同じ程度のサイズ感の場合、レンジ感があるため、スキップはしない（ほとんどラップしている状態）
                i = i + 1
                continue
            else:
                if vanish_item['count'] <= count_border:
                    if vanish_latest_ratio <= overlap_min_ratio and vanish_oldest_ratio <= overlap_ratio:
                        # print("　latestに対して、Vanishが小さく、ラップが小さいほうがあるため、SKIP")
                        is_skip = True
                    elif vanish_oldest_ratio <= overlap_min_ratio and vanish_latest_ratio <= overlap_ratio:
                        # print("  oldestに対して、Vanishが小さく、ラップが小さい方があるため、SKIP")
                        is_skip = True

            # 判定２
            if vanish_item['gap'] <= self.skip_gap_border_second:
                if vanish_latest_ratio <= overlap_ratio and vanish_oldest_ratio <= overlap_ratio:
                    # print(s4, s4, "Gap小かつ微妙な折り返し", vanish_item['gap'], vanish_latest_ratio,vanish_oldest_ratio, latest_item['time'])
                    is_skip = True

            # ■スキップ処理
            if is_skip:
                if 'previous' in oldest_merged_item:
                    # 最後の一つはやらないため、IF文で最後の手前まで実施する
                    # marked_onlyの方にフラグを付けていく
                    # self.peaks_original_marked_skip[i+skip_counter]['skipped'] = True
                    # self.peaks_original_marked_skip[i+skip_counter + 1]['skipped'] = True
                    skip_counter = skip_counter + 2  # 2個消すので、2個分インクリメントが必要

                    # 消す作業の本番
                    peaks[latest_num]['oldest_body_peak_price'] = oldest_merged_item['oldest_body_peak_price']
                    peaks[latest_num]['oldest_time_jp'] = oldest_merged_item['oldest_time_jp']
                    peaks[latest_num]['oldest_price'] = oldest_merged_item['oldest_price']
                    peaks[latest_num]['count'] = (latest_item['count'] + vanish_item['count'] +
                                                         oldest_merged_item['count']) - 2
                    peaks[latest_num]['previous'] = oldest_merged_item['previous']
                    peaks[latest_num]['gap'] = round(abs(latest_item['latest_body_peak_price'] -
                                                                oldest_merged_item['oldest_body_peak_price']), self.round_keta)
                    peaks[latest_num]['peak_strength'] = self.ps_default  # 従来はlatest_item['strength']だが、結合＝０にした方がよい場合が、、
                    peaks[latest_num]['skip_include_num'] = peaks[latest_num]['skip_include_num'] + 1
                    # 互換性確保用（いつか消したい）
                    # 情報を吸い取った後、latestおよびmidは削除する
                    del peaks[latest_num + 1:latest_num + 3]

                else:
                    i = i + 1
                    # marked_onlyの方にフラグを付けていく

            else:
                # adjuster = -1
                # ans_peaks.append(vanish_item)
                i = i + 1

            if i > len(peaks):
                return peaks

        return peaks

    def skip_peaks_hard(self):
        """
        peaksを受け取り、必要に応じてスキップする
        """
        s4 = "    "
        # print(s4, "SKIP Peaks　はーど")
        adjuster = 0
        # peaks = copy.deepcopy(self.peaks_original)  # self.peaks_original.copy()では浅いコピーとなる
        peaks = copy.deepcopy(self.skipped_peaks)  # self.peaks_original.copy()では浅いコピーとなる
        # self.peaks_original_marked_hard_skip = copy.deepcopy(self.peaks_original)
        # self.peaks_original_marked_hard_skip = copy.deepcopy(self.peaks_original_marked_skip)
        # for item in self.peaks_original_marked_hard_skip:
        #     item["skipped"] = False

        skip_counter = 0  # 何個スキップしたかをカウントする（フラグ付けのループの個数調整で利用。）
        i = 1
        while i < len(peaks) -1:  # 中で配列を買い替えるため、for i in peaksは使えない！！
            vanish_num = i + adjuster  # 削除後に、それを起点にもう一度削除処理ができる
            if vanish_num == 0 or vanish_num >= len(peaks) - 1:
                # print("最初か最後のため、Vanish候補ではない", vanish_num, latest_item)
                i = i + 1
                continue

            # わかりやすく命名 （vanish_itemは中央のアイテムを示す）
            latest_num = vanish_num - 1
            latest_item = peaks[latest_num]
            oldest_num = vanish_num + 1
            oldest_item = peaks[oldest_num]
            vanish_item = peaks[vanish_num]

            # print(s4, s4, latest_item['time'])
            # print(s4, s4, s4, vanish_item['time'])
            # print(s4, s4, s4, oldest_item['time'])

            # ■スキップ判定 (vanishは真ん中のPeakを意味する）
            # (0)スキップフラグの設定
            is_skip = False
            # (1)基本判定 サイズが小さいときが対象
            count_border = 5
            if vanish_item['count'] <= count_border and vanish_item['gap'] <= self.skip_gap_border:
                pass
            else:
                # そこそこサイズがあるので、スキップ
                # print(s4,s4, "サイズあるためスキップ　vanish_item:", vanish_item['time'], vanish_item['count'], vanish_item['gap'])
                i = i + 1
                continue

            # (2)ラップ判定
            # 変数の設定
            vanish_latest_ratio = vanish_item['gap'] / latest_item['gap']
            vanish_oldest_ratio = vanish_item['gap'] / oldest_item['gap']
            # 判定１
            overlap_ratio = 0.6  # ラップ率のボーダー値　(0.7以上でラップ大。0.7以下でラップ小）
            overlap_min_ratio = 0.35
            # print(s4, s4, "latest", latest_item['time'], latest_item['gap'], "oldest", oldest_item['time'], oldest_item['gap'])
            # print(s4, s4, "  vanish:", vanish_item['time'], "vanish_latest_ratio:", vanish_latest_ratio, ",vanish_oldest_ratio:", vanish_oldest_ratio)
            if vanish_latest_ratio >= overlap_ratio and vanish_oldest_ratio >= overlap_ratio:
                # 両サイドが同じ程度のサイズ感の場合、レンジ感があるため、スキップはしない（ほとんどラップしている状態）
                i = i + 1
                continue
            else:
                if vanish_item['count'] <= count_border:
                    if vanish_latest_ratio <= overlap_min_ratio and vanish_oldest_ratio <= overlap_ratio:
                        # print("　latestに対して、Vanishが小さく、ラップが小さいほうがあるため、SKIP")
                        is_skip = True
                    elif vanish_oldest_ratio <= overlap_min_ratio and vanish_latest_ratio <= overlap_ratio:
                        # print("  oldestに対して、Vanishが小さく、ラップが小さい方があるため、SKIP")
                        is_skip = True

            # 判定２
            if vanish_item['gap'] <= self.skip_gap_border_second:
                if vanish_latest_ratio <= overlap_ratio and vanish_oldest_ratio <= overlap_ratio:
                    # print(s4, s4, "Gap小かつ微妙な折り返し", vanish_item['gap'], vanish_latest_ratio,vanish_oldest_ratio, latest_item['time'])
                    is_skip = True

            # ■スキップ処理
            if is_skip:
                # print("  削除対象", vanish_item['time'], i, i+skip_counter)
                if 'previous' in oldest_item:
                    # 最後の一つはやらないため、IF文で最後の手前まで実施する
                    # marked_onlyの方にフラグを付けていく
                    # self.peaks_original_marked_hard_skip[i+skip_counter]['skipped'] = True
                    # self.peaks_original_marked_hard_skip[i+skip_counter + 1]['skipped'] = True
                    skip_counter = skip_counter + 2  # 2個消すので、2個分インクリメントが必要

                    # 消す作業の本番
                    peaks[latest_num]['oldest_body_peak_price'] = oldest_item['oldest_body_peak_price']
                    peaks[latest_num]['oldest_time_jp'] = oldest_item['oldest_time_jp']
                    peaks[latest_num]['oldest_price'] = oldest_item['oldest_price']
                    peaks[latest_num]['count'] = (latest_item['count'] + vanish_item['count'] +
                                                         oldest_item['count']) - 2
                    peaks[latest_num]['previous'] = oldest_item['previous']
                    peaks[latest_num]['gap'] = round(abs(latest_item['latest_body_peak_price'] -
                                                                oldest_item['oldest_body_peak_price']), self.round_keta)
                    peaks[latest_num]['peak_strength'] = self.ps_default  # 従来はlatest_item['strength']だが、結合＝０にした方がよい場合が、、
                    peaks[latest_num]['skip_include_num'] = peaks[latest_num]['skip_include_num'] + 1
                    # 互換性確保用（いつか消したい）
                    # 情報を吸い取った後、latestおよびmidは削除する
                    del peaks[latest_num + 1:latest_num + 3]
                else:
                    i = i + 1
            else:
                # adjuster = -1
                # ans_peaks.append(vanish_item)
                i = i + 1

            if i > len(peaks):
                return peaks

        return peaks

    def cal_target_times_skip_num(self, peaks, target_time):
        """
        データフレームのJP形式の日付が渡され、そのピークがスキップを含むかを返却
        （スキップない場合は初期値の０、スキップありの場合は自然数を）
        """
        skipped_num = 0
        for item in peaks:
            # print("検索対象", item['latest_time_jp'])
            if item["latest_time_jp"] == target_time:
                skipped_num = item.get('skip_include_num', 0)
                # print(" 同一価格発見（Skipされていない）", item["time"], item['skip_include_num'])
                break
        return skipped_num

    def temp(self):

        target_peak = self.peaks_original[1]
        peaks_same_direction = [d for d in self.peaks_original if d["direction"] == target_peak['direction']]
        peaks_oppo_direction = [d for d in self.peaks_original if d["direction"] == target_peak['direction'] * -1]
        t_price = target_peak['peak']

        # 【定型】最も近いピークを探す(ターゲットのPeakと同じ方向の中で探す）。遠い場合はminではなくmaxで対応が可能
        closest_element = min(
            (d for d in peaks_same_direction if d["peak"] != target_peak["peak"]),  # 自分自身を除外
            key=lambda x: abs(x["peak"] - target_peak["peak"])  # peak の差を最小にする
        )
        print("Targetは", target_peak)
        print("一番近いのは", closest_element)

        # ■自身が最高点か

        # ■最も近いピークを探す(ループ）
        target_num = 0  # 以下のループで「自分以外」を定義するため、変数に入れておく(同一方向の配列に対して）
        t = peaks_same_direction[target_num]
        min_gap = 99999  # 差を一時的に入れておく変数
        ans_num = 0  # 対象のitem番号を入れておく
        print(peaks_same_direction)
        for i, item in enumerate(peaks_same_direction):
            # Continue
            if i == target_num:
                continue  # 自分自身は比較しない

            # 入れ替え処理
            this_gap_abs = abs(item['peak'] - t['peak'])
            if this_gap_abs < min_gap and item['peak_strength'] >= 4:
                min_gap = this_gap_abs  # 入れ替え処理
                ans_num = i  # 回答ほ保存
        print("一番近いやつループ", peaks_same_direction[ans_num])

    def make_same_price_list(self, target_num, skip):
        """
        samePriceListを作成する（指定のピーク価格を基準とする）
        ・一番近いピークまで何分か、一番近いピークまでの間にBreakがあるかどうか
        ・Breakが発生するまでの同一価格
        ・同一価格のリスト（全区間）
        ・同一価格のリスト（時間内）
        """
        s = self.s
        # skip = True
        # ■■情報の設定
        if skip:
            # Skip Peakを利用する
            peaks = self.skipped_peaks
        else:
            peaks = self.peaks_original
        # ターゲット情報
        # target_num = 2
        target_peak = peaks[target_num]
        target_price = target_peak['latest_body_peak_price']
        # 範囲はその時点の過去のみ
        peaks = peaks[target_num:]
        # print("   実行時引数 SKIP：", skip, " TargetNum:", target_num)
        # print(s, "   ターゲットになるピーク@cp:", target_peak)

        # ■■閾値の情報
        # Margin情報
        arrowed_range = self.arrowed_gap
        # arrowed_range = self.recent_fluctuation_range * 0.07  # 最大変動幅の4パーセント程度
        # 山の情報
        mountain_foot_min = 60  # 山のすそ野の広さ 足の個数（この値以上の山の裾野の広さを狙う）
        base_time = datetime.strptime(peaks[0]['time'], '%Y/%m/%d %H:%M:%S')

        # ■■SamePriceListのリセット(繰り返し呼ばれた場合、.appendで追加だけされてしまう）
        self.same_price_list = []
        self.same_price_list_till_break = []
        self.same_price_list_till_break2 = []
        self.same_price_list_inner = []
        self.same_price_list_outer = []
        self.result_not_same_price_list = []
        self.opposite_peaks = []
        self.break_peaks = []
        self.break_peaks_inner = []
        self.break_peaks_outer = []
        # ■■同一価格の探索
        break_num = 0  #
        same_price_num = 0
        strength_border = 1  # この点数以下のストレングスはカウントしない（１点はしない）
        break_border = 1  # この数以上のBreakが発生するまでの同一価格リストを求める
        break_border2 = 0  # この数以上のBreakが発生するまでの同一価格リストを求める
        for i, item in enumerate(peaks):
            # print(s, "      検証対象：", item['time'], item['peak_strength'], base_time)
            # 既定の裾野の内側にある場合inner=True
            time_gap_sec = abs(datetime.strptime(item['latest_time_jp'], '%Y/%m/%d %H:%M:%S') - base_time)
            if time_gap_sec <= timedelta(minutes=mountain_foot_min):
                is_inner = True
            else:
                is_inner = False

            # 同一方向のものの、検索対象
            if item['direction'] != target_peak['direction']:
                if i == 0:
                    pass
                else:
                    self.opposite_peaks.append({"i": i, "item": item, "time_gap": time_gap_sec})
                    # print("             反対側")
                continue

            # 最初の一つは確保する（自分自身はたとえ強度が低くても、確保する）
            # if i == target_num:
            if i == 0:  # 時系列的に過去のもののみがPeaksにある場合はこっち。
                # print("             FIRST：", item['time'], item['peak_strength'])
                self.same_price_list.append({"i": i, "item": item, "time_gap": time_gap_sec})
                self.same_price_list_till_break.append({"i": i, "item": item, "time_gap": time_gap_sec})
                self.same_price_list_till_break2.append({"i": i, "item": item, "time_gap": time_gap_sec})
                if is_inner:
                    self.same_price_list_inner.append({"i": i, "item": item, "time_gap": time_gap_sec})
                else:
                    self.same_price_list_outer.append({"i": i, "item": item, "time_gap": time_gap_sec})
                continue
            # i=0の場合、最低１つは入れるが、それを確保した後は、ピークが弱いものは除外
            if item['peak_strength'] <= strength_border:
                continue

            # 除外条件（ターゲットより前の場合)
            # if i < target_num:
            #     print("除外（iに比べて、時系列的に未来にあるため）")
            #     continue

            # Breakかを先に判定する
            if target_peak['direction'] == 1:
                if item['peak'] > target_price + self.arrowed_break_gap:
                    # print("          Break up：", item['time'], item['peak_strength'])
                    # ターゲットピークを越えている場合(UpperLineで、上側に突き抜け）、NG
                    self.break_peaks.append({"i": i, "item": item, "time_gap": time_gap_sec})
                    if is_inner:
                        self.break_peaks_inner.append({"i": i, "item": item, "time_gap": time_gap_sec})
                    else:
                        self.break_peaks_outer.append({"i": i, "item": item, "time_gap": time_gap_sec})
                    # 共通
                    break_num = break_num + 1
            else:
                if item['peak'] < target_price - self.arrowed_break_gap:
                    # print("          Break：", item['time'], item['peak_strength'])
                    # ターゲットピークを越えている場合（lowerLineで下に突き抜け）、NG
                    self.break_peaks.append({"i": i, "item": item, "time_gap": time_gap_sec})
                    if is_inner:
                        self.break_peaks_inner.append({"i": i, "item": item, "time_gap": time_gap_sec})
                    else:
                        self.break_peaks_outer.append({"i": i, "item": item, "time_gap": time_gap_sec})
                    # 共通
                    break_num = break_num + 1

            # 同一価格リストを取得（Breakがn個発生するまでの同一価格、全体の同一価格、時間内の同一価格）
            body_gap_abs = abs(target_price - item['peak'])
            if abs(item['latest_wick_peak_price'] - item['peak']) >= arrowed_range:
                # 髭が長すぎる場合は無効（無効は、上限をオーバーする値に設定してしまう
                body_wick_gap_abs = arrowed_range + 1  # 確実にarrowed_rangeより大きな値
            else:
                body_wick_gap_abs = abs(target_price - item['latest_wick_peak_price'])
            # if body_gap_abs <= arrowed_range or body_wick_gap_abs <= arrowed_range:  # 髭も混み
            if body_gap_abs <= arrowed_range:  # or body_wick_gap_abs <= arrowed_range:
                # 同一価格とみなせる場合
                # print("             同一価格：")
                self.same_price_list.append({"i": i, "item": item, "time_gap": time_gap_sec})
                # 同一価格とみなせる場合で、さらに時間いないかどうかを検証する
                if is_inner:
                    # print("               inner：")
                    self.same_price_list_inner.append({"i": i, "item": item, "time_gap": time_gap_sec})
                else:
                    # print("               outer：")
                    self.same_price_list_outer.append({"i": i, "item": item, "time_gap": time_gap_sec})
                # BreakがN個以下までの同一価格
                if break_num <= break_border:
                    self.same_price_list_till_break.append({"i": i, "item": item, "time_gap": time_gap_sec})
                if break_num <= break_border2:
                    self.same_price_list_till_break2.append({"i": i, "item": item, "time_gap": time_gap_sec})
                # 共通
                same_price_num = same_price_num + 1
            else:
                # print("             Not：", body_gap_abs, arrowed_range, body_wick_gap_abs, abs(1))
                self.result_not_same_price_list.append({"i": i, "item": item, "time_gap": time_gap_sec})
        # 表示用
        # print("同一価格一覧 @cp")
        # f.print_arr(self.same_price_list)
        # print("70分以内の同一価格一覧 @cp")
        # f.print_arr(self.same_price_list_inner)
        # print("Break一覧 @cp")
        # f.print_arr(self.break_peaks)
        # print("70分以内のBreak一覧 @cp")
        # f.print_arr(self.break_peaks_inner)
        # print("70分より前のBreak一覧 @cp")
        # f.print_arr(self.break_peaks_outer)
        # print("Breakまでの同一価格 @cp")
        # f.print_arr(self.same_price_list_till_break)
        # print("Break2までの同一価格 @cp")
        # f.print_arr(self.same_price_list_till_break2)
        return {
            "same_price_list": self.same_price_list,
            "till_break_list": self.same_price_list_till_break,
            "till_break_list2": self.same_price_list_till_break2,
            "break_list": self.break_peaks,
            "opposite_peaks": self.opposite_peaks
        }

    def check_large_body_in_peak(self, block_ans):
        """
        対象となる範囲のデータフレームをループし（ブロックを探すのと並行してやるので、二回ループ作業してることになるが）
        突発を含むかを判定する
        ついでに、HighLowのプライスも取得する
        """
        # 大きい順に並べる
        s6 = "      "

        # 足や通過に依存する数字
        # 情報を取得する
        sorted_df_by_body_size = block_ans['data'].sort_values(by='body_abs', ascending=False)
        max_body_in_block = sorted_df_by_body_size["body_abs"].max()

        # ■極大の変動を含むブロックかの確認
        include_very_large = False
        for index, row in sorted_df_by_body_size.iterrows():
            if row['body'] >= self.dependence_very_large_body_criteria:
                include_very_large = True
                break
            else:
                include_very_large = False

        # ■突発的な変動を含むか判断する（大き目サイズがたくさんあるのか、数個だけあるのか＝突発）
        counter = 0
        for index, row in sorted_df_by_body_size.iterrows():
            # 自分自身が、絶対的に見て0.13以上と大きく、他の物より約2倍ある物を探す。（自分だけが大きければ、突然の伸び＝戻る可能性大）
            # 自分自身を、未達カウントするため注意が必要
            smaller_body = row['body_abs'] if row['body_abs'] != 0 else self.minimum
            if max_body_in_block > self.dependence_large_body_criteria:
                counter = counter + 1
                # if max_body_in_block / smaller_body > 1.8:  # > 0.561:
                #     # print(s6, "Baseが大きめといえる", smaller_body / max_body_in_block , "size", smaller_body, max_body_in_block, row['time_jp'])
                #     counter = counter + 1
                # else:
                #     pass
                # print(s6, "自身より大き目（比率）", smaller_body / max_body_in_block, row['time_jp'])
            else:
                pass
                # print(s6, "baseBodyがそもそも小さい")
        if counter / (len(sorted_df_by_body_size)) >= 0.65:
            # 突発の伸びがあったと推定（急伸は戻る可能性大）　平均的に全部大きい場合は除く（大きくないものが75％以下の場合）
            # print(s6, "急伸の足を含む", counter / (len(sorted_df_by_body_size)), block_ans['data'].iloc[0]['time_jp'])
            include_large = True
        else:
            # print(s6, "急伸とみなさない")
            include_large = False

        return {
            "include_large": include_large,
            "include_very_large": include_very_large,
            "highest": sorted_df_by_body_size['high'].max(),
            "lowest": sorted_df_by_body_size['low'].min()
        }


def judge_peak_is_belong_peak_group(peaks, target_peak):
    """
    与えられたピークが、与えられたpeaksの中で最大（または最小）といえるかをＢｏｏｌｅａｎで返却する
    """
    depend_judge_range = 0.025
    ans = False

    max_index, max_peak = max(enumerate(peaks), key=lambda x: x[1]["peak"])
    min_index, min_peak = min(enumerate(peaks), key=lambda x: x[1]["peak"])

    if target_peak['direction'] == 1:
        if max_peak['peak'] - depend_judge_range <= target_peak['peak'] <= max_peak['peak'] + depend_judge_range:
            print("最大群")
            ans = True
        else:
            print("最大群ではない")
    else:
        if min_peak['peak'] - depend_judge_range <= target_peak['peak'] <= min_peak['peak'] + depend_judge_range:
            print("最小群")
            ans = True
        else:
            print("最小群ではない")

    return ans




