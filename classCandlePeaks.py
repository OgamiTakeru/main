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
    # 基本となるデータフレーム
    df_r_original = None  # 直近の時刻が[0]となるデータフレーム。API取得のデータとは逆順
    # ピーク情報
    peaks_original = []  # 計算されたピークで、一番ベーシックなもの（DataFrameがない）
    peaks_original_with_df = []  # 要素にdataとdataFrameを持つ。SKipは結合させたりでめんどいのでやらない。
    skipped_peaks = []  # 計算された、スキップありのピーク
    skipped_peaks_hard = []  # 計算された、強いスキップありのピーク
    peaks_original_marked_skip = []  # 使ってない？？
    peaks_original_marked_hard_skip = []  # 使ってない？？　peaksとしてはオリジナル同様だが、スキップピークに、フラグが付いている物
    latest_resistance_line = {}  # Nullか、情報が入っているかのどちらか（Null＝抵抗線ではない）
    latest_price = 0  # 現在価格（場合よっては最新価格）
    latest_peak_price = 0  # 直近のピーク
    # 動きの数値化された情報
    is_big_move_peak = False
    is_big_move_candle = False
    ave_move = 0  # ここ5足程度の動きの大きさ（髭を含む）
    ave_move_for_lc = 0  # ここ5足程度の動きの大きさ（髭を含む）を加味した、LCの提案価格

    # 時間情報
    time_hour = 0

    # samePriceList関係
    same_price_list = []
    same_price_list_till_break = []
    same_price_list_inner = []
    same_price_list_outer = []
    result_not_same_price_list = []
    opposite_peaks = []
    break_peaks = []
    break_peaks_inner = []
    break_peaks_outer = []

    def __init__(self, original_df_r):
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

        # ■初期値の設定（Peak解析の基準）
        self.max_peak_num = 30  # ピークを最大何個まで求めるか（昔はこれを15で使ってたが、今は時間で切る）。念のために残っている.
        # ピークの強さの指標(点数)の設定（以下、peak_strengthを短縮のためにpsと略する）
        self.ps_default = 5  # ピーク基準値
        self.ps_most_min = 2  # 弱いピークに付与する値
        self.ps_min = 4  # 若干弱いピークに付与する値
        self.ps_most_max = 8  # 強いピークとみなす（直近数時間で最も高い（または低い）ピークの場合)　

        # MakePeaks時、ピークの強さを付与する場合、以下の数値以下の場合はピークの強さが弱くなる。makePeaksで利用。
        self.peak_strength_border = 0.03  # この数字以下のピークは、問答無用で点数を下げる（self.ps_most_minにする）
        self.peak_strength_border_second = 0.07  # この数字より下（かつ上の数字より大きい）場合、countが少なければ強度弱となる。

        # SkipPeaksの際の基準(SkipPeaks関数）
        self.skip_gap_border = 0.3  # 0.045  # この値以下のGapをもつPeakは、問答無用でスキップ処理される
        self.skip_gap_border_second = 0.3 #  0.05  # この値以下のGapを持つPeakは、重なり（ラップ）状況でスキップされる

        # 急変動(fluctuation)を検知する基準の設定　cal_move_size関数
        self.recent_fluctuation_range = 0  # 指定ではなく、計算で算出される。直近N足分以内での最大変動幅（最高値ー最低値）round済み
        self.fluctuation_gap = 0.3  # 急変動とみなす1足の変動は30pips以上。（1足でPeakの変動ではない）
        self.fluctuation_count = 3  # 3カウント以下でfluctuation_gapが起きた場合、急変動とみなす

        # 抵抗線関係の値　cal_big_mountain関数
        self.arrowed_gap = 0.05  # 抵抗線を探す時、ずれていてもいい許容値

        # 超レンジ判定
        self.hyper_range = False

        # ■実処理
        if PeaksClass.df_r_original is None:
            print(" 初回")
            # PeaksClass.df_r_original = original_df_r
        # else:
        #     print("元々登録済みのデータ範囲　From", PeaksClass.df_r_original.iloc[-1]['time_jp'], "to", PeaksClass.df_r_original.iloc[0]['time_jp'])
        #     print(original_df_r.equals(PeaksClass.df_r_original))
        #     if PeaksClass.df_r_original.iloc[-1]['time_jp'] == original_df_r.iloc[-1]['time_jp'] and PeaksClass.df_r_original.iloc[0]['time_jp'] == original_df_r.iloc[0]['time_jp']:
        #         print("同じ", PeaksClass.df_r_original.iloc[-1]['time_jp'], original_df_r.iloc[-1]['time_jp'])
        #         print("    ", PeaksClass.df_r_original.iloc[0]['time_jp'], original_df_r.iloc[0]['time_jp'])

        # if original_df_r.equals(PeaksClass.df_r_original):  # ←ほんとうはこれがいいけど、何故か差分が出るときあり
        if not PeaksClass.df_r_original is None and PeaksClass.df_r_original.iloc[-1]['time_jp'] == original_df_r.iloc[-1]['time_jp'] and PeaksClass.df_r_original.iloc[0]['time_jp'] == original_df_r.iloc[0]['time_jp']:
            # print("         [既にPeaksに変換済みのデータフレーム]")
            # print(PeaksClass.peaks_original)
            pass
        else:

            # (1)ピークスの算出
            PeaksClass.df_r_original = original_df_r
            # print("直近価格", PeaksClass.latest_price, original_df.iloc[0]['time_jp'])
            print("異なる", PeaksClass.df_r_original.iloc[-1]['time_jp'], original_df_r.iloc[-1]['time_jp'])
            print("    ", PeaksClass.df_r_original.iloc[0]['time_jp'], original_df_r.iloc[0]['time_jp'])

            self.df_r = original_df_r[1:]  # df_rは先頭は省く（数秒分の足のため）
            self.df_r = self.df_r[:55]  # 直近4.5時間分(55足分)のデータフレームにする
            print("API取得したデータ範囲　From", original_df_r.iloc[-1]['time_jp'], "to", original_df_r.iloc[0]['time_jp'])
            print("調査範囲　From", self.df_r.iloc[-1]['time_jp'], "to", self.df_r.iloc[0]['time_jp'])
            PeaksClass.peaks_original = self.make_peaks(self.df_r)  # 一番感度のいいPeaks。引数は書くとするなら。self.df_r。
            PeaksClass.peaks_original_with_df = self.make_peaks_with_df(self.df_r)  # 一番感度のいいPeaksにDfがついたもの
            # たまに起きる謎のエラー対応
            if len(PeaksClass.peaks_original) <= 2:
                tk.line_send("データがうまくとれていない。", len(original_df_r), "行のみ")
                print("おかしなことが起きている originalデータが少なすぎる @peakclass　全", len(original_df_r), "行のみ")
                gene.print_arr(PeaksClass.peaks_original)
                print(PeaksClass.df_r_original)
                print("↑", len(PeaksClass.df_r_original))
                print(original_df_r)
                print("↑　originalDf")
                print("おかしなことの表示")
            PeaksClass.skipped_peaks = self.skip_peaks()  # スキップピークの算出
            PeaksClass.skipped_peaks_hard = self.skip_peaks_hard()
            self.recalculation_peak_strength_for_peaks()  # ピークストレングスの算出

            # (2) ある程度よく使う値は変数に入れておく
            PeaksClass.latest_price = original_df_r.iloc[0]['open']
            PeaksClass.latest_peak_price = PeaksClass.peaks_original[0]['peak']
            print("直近価格", PeaksClass.latest_price)
            print("直近ピーク", PeaksClass.latest_peak_price)

            # (3) 時間の取得
            time_obj = pd.to_datetime(original_df_r.iloc[0]['time_jp'], format='%Y/%m/%d %H:%M:%S')
            PeaksClass.time_hour = time_obj.hour

            # (4)追加の機能（直近の数個が承服しすぎているかどうかの確認）
            self.check_very_narrow_range(self.df_r)

            # (4) 表示
            s = "   "
            peaks_original = copy.deepcopy(PeaksClass.peaks_original)# 深いコピーを作成
            for d in peaks_original:# 指定キーを削除
                d.pop('next', None)
                d.pop('previous_time_peak', None)
                d.pop('support_info', None)
                d.pop('memo_time', None)

            # print(s, "<SKIP前>", )
            # gene.print_arr(peaks_original[:10])
            # print("   |")
            # gene.print_arr(peaks_original[-2:])

            # print("")
            # print(s, "<SKIP後　対象>")
            # skipped_peaks = copy.deepcopy(PeaksClass.skipped_peaks)# 深いコピーを作成
            # for d in skipped_peaks:# 指定キーを削除
            #     d.pop('next', None)
            #     d.pop('previous_time_peak', None)
            #     d.pop('support_info', None)
            #     d.pop('memo_time', None)
            # gene.print_arr(skipped_peaks[:10])

            # print("")
            # print(s, "<hard SKIP後　対象>")
            # skipped_peaks_hard = copy.deepcopy(PeaksClass.skipped_peaks_hard)# 深いコピーを作成
            # for d in skipped_peaks_hard:# 指定キーを削除
            #     d.pop('next', None)
            #     d.pop('previous_time_peak', None)
            #     d.pop('support_info', None)
            #     d.pop('memo_time', None)
            # gene.print_arr(skipped_peaks_hard[:10])

            # print("")
            # print(s, "<hard SKIPのフラグのみ")
            # gene.print_arr(PeaksClass.peaks_original_marked_hard_skip[:15])

            #  (重要)

            #  (1)大きなレンジをターンストレングスで判断する場合
            self.peak_strength_sort()

            # (3)samePriceの算出
            # self.make_same_price_list(1, False)  # スタンダードな引数で出しておく

    def make_peak(self, df_r):
        """
        渡された範囲で、何連続で同方向に進んでいるかを検証する
        :param df_r: 直近が上側（日付降順/リバース）のデータを利用
        :return: Dict形式のデータを返伽
        """
        # コピーウォーニングのための入れ替え
        data_df = df_r.copy()
        temp = self.df_r_original  # Warning回避のため（staticにしろって言われるから）
        # 返却値を設定
        ans_dic = {
            "latest_time_jp": 0,  # これがpeakの時刻
            "oldest_time_jp": 0,
            "direction": 1,
            "peak_strength": self.ps_default,  # この関数では付与されない（単品では判断できない）。make_peaks関数で前後のPeakを加味して付与される
            "count": 0,  # 最新時刻からスタートして同じ方向が何回続いているか
            "data_size": len(data_df),  # (注)元のデータサイズ
            "latest_body_peak_price": 0,  # これがpeakの価格
            "oldest_body_peak_price": 0,
            "latest_wick_peak_price": 0,
            "oldest_wick_peak_price": 0,
            "latest_price": 0,
            "oldest_price": 0,
            "gap": 0.00000001,
            "gap_high_low": 0.00000001,
            "gap_close": 0.00000001,
            "body_ave": 0.00000001,
            "move_abs": 0.00000001,
            "memo_time": 0,
            "data": data_df,  # 対象となるデータフレーム（元のデータフレームではない）
            "data_remain": data_df,  # 対象以外の残りのデータフレーム
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
            if tilt == 0:
                tilt = 0.00000001
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
        ans_df = data_df[0:counter + 1]  # 同方向が続いてる範囲のデータを取得する
        ans_other_df = data_df[counter:]  # 残りのデータ

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
        body_ave = round(data_df["body_abs"].mean(), 3)
        move_ave = round(data_df["moves"].mean(), 3)

        # ■GAPを計算する（０の時は割る時とかに困るので、最低0.001にしておく）
        # gap = round(abs(latest_body_price - oldest_body_price), 3)  # MAXのサイズ感
        gap_close = round(abs(latest_body_price - ans_df.iloc[-1]["close"]), 3)  # 直近の価格（クローズの価格&向き不問）
        if gap_close == 0:
            gap_close = 0.00000001
        else:
            gap_close = gap_close

        gap = round(abs(latest_body_price - oldest_body_price), 3)  # 直近の価格（クローズの価格&向き不問）
        if gap == 0:
            gap = 0.00000001
        else:
            gap = gap

        gap_high_low = round(abs(latest_wick_price - oldest_wick_price), 3)  # 直近の価格（クローズの価格&向き不問）
        if gap_high_low == 0:
            gap_high_low = 0.00000001
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
        ans_dic["memo_time"] = f.str_to_time_hms(ans_df.iloc[-1]["time_jp"]) + "_" + f.str_to_time_hms(
            ans_df.iloc[0]["time_jp"])  # 表示に利用する時刻表示用
        # 追加項目
        ans_dic['include_large'] = check_large_body_in_peak(ans_dic)['include_large']
        ans_dic['include_very_large'] = check_large_body_in_peak(ans_dic)['include_very_large']
        ans_dic['highest'] = check_large_body_in_peak(ans_dic)['highest']
        ans_dic['lowest'] = check_large_body_in_peak(ans_dic)['lowest']
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
        df_r = df_r.copy()

        # ■処理の開始
        peaks = []  # 結果格納用
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

            # ■■■■■■■■実処理の追加(前後関係の追加）
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
            elif item_latest_ratio <= overlap_ratio and item_oldest_ratio <= overlap_ratio:
                # print("ラップ率が両サイドに比べてそこそこ低め⇒多少スキップの可能性が上がる）
                # print("", item['time'], latest_item['time'], oldest_merged_item['time'])
                # print("", item['gap'], latest_item['gap'], oldest_merged_item['gap'])
                # print("Peak現象判定(直近との比率）", item_latest_ratio,)
                # print("Peak現象判定(直古との比率）", item_oldest_ratio,)
                item['peak_strength'] = self.ps_min  # これで元データ入れ替えられるんだ？！
                peaks[i + 1]['peak_strength'] = self.ps_min  # ひとつ前(時間的はOldest）のPeakも強制的にStrengthが1となる


        return peaks

    def make_peaks_with_df(self, df_r):
        """
        リバースされたデータフレーム（直近が上）から、ピークを一覧にして返却する これがメイン
        :return:
        """
        # ■引数の整理
        df_r = df_r.copy()

        # ■処理の開始
        peaks = []  # 結果格納用
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

            # ■■■■■■■■実処理の追加(前後関係の追加）
            # peakの簡素化
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
            elif item_latest_ratio <= overlap_ratio and item_oldest_ratio <= overlap_ratio:
                # print("ラップ率が両サイドに比べてそこそこ低め⇒多少スキップの可能性が上がる）
                # print("", item['time'], latest_item['time'], oldest_merged_item['time'])
                # print("", item['gap'], latest_item['gap'], oldest_merged_item['gap'])
                # print("Peak現象判定(直近との比率）", item_latest_ratio,)
                # print("Peak現象判定(直古との比率）", item_oldest_ratio,)
                item['peak_strength'] = self.ps_min  # これで元データ入れ替えられるんだ？！
                peaks[i + 1]['peak_strength'] = self.ps_min  # ひとつ前(時間的はOldest）のPeakも強制的にStrengthが1となる


        return peaks

    def check_very_narrow_range(self, df_r):
        """
        与えられたデータの直近数個が、「きわめてレンジ」といえるか。
        ほとんど動きがないような状態。
        直近数個の中で、最大の物(8pips以内）を探し、その中に70％以上入っている足の割合が多い
        """
        target = 4  # 直近4個分
        df = df_r[0:target].copy()  # 同方向が続いてる範囲のデータを取得する

        max_gap_row = df.loc[df['body_abs'].idxmax()]
        max_gap_value = df['body_abs'].max()
        upper = max_gap_row['inner_high']
        lower = max_gap_row['inner_low']
        if max_gap_value >= 0.07:  # 一つの足の幅が７pip以上の場合は動き大き目のため、除外
            is_mini_range = False
        else:
            # 各行の区間長
            df['range_len'] = (df['inner_low'] - df['inner_high']).abs()

            # 各行の重なり開始と終了
            overlap_start = df[['inner_low', 'inner_high']].min(axis=1).clip(lower, upper)
            overlap_end = df[['inner_low', 'inner_high']].max(axis=1).clip(lower, upper)

            # 重なり長さ（負にならないよう0でクリップ）
            df['overlap_len'] = (overlap_end - overlap_start).clip(lower=0)

            # はみ出し長さと割合
            df['exceed_len'] = df['range_len'] - df['overlap_len']
            df['exceed_ratio_with_self'] = df['exceed_len'] / df['range_len']
            df['exceed_ratio_with_max'] = df['exceed_len'] / max_gap_value

            # 割合（％なら×100）
            df['overlap_ratio_with_self'] = df['overlap_len'] / df['range_len']
            df['overlap_ratio_with_max'] = df['overlap_len'] / max_gap_value

            print("超レンジ可の判定用")
            print("最大Body", max_gap_row['time_jp'])
            # print(df[['time_jp', 'overlap_ratio_with_max','exceed_ratio_with_max']])
            is_mini_range = ((df['exceed_ratio_with_max'] <= 0.24) & (df['overlap_ratio_with_max'] >= 0.4)).all()

        print("〇超レンジ判定⇒", is_mini_range)
        self.hyper_range = is_mini_range

    def recalculation_peak_strength_for_peaks(self):
        """
        ここ数時間で最大（または最小）のピーク値には、高得点を付与する
        """
        # 対象
        peaks = PeaksClass.peaks_original
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
            max_price_neg1_dict['peak_strength'] = self.ps_most_max
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
        for peak in PeaksClass.peaks_original:
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

    def skip_peaks(self):
        """
        peaksを受け取り、必要に応じてスキップする
        """
        s4 = "    "
        # print(s4, "SKIP Peaks")
        s4 = "    "
        # print(s4, "SKIP Peaks")
        adjuster = 0
        peaks = copy.deepcopy(PeaksClass.peaks_original)  # PeaksClass.peaks_original.copy()では浅いコピーとなる
        # フラグつけ用
        PeaksClass.peaks_original_marked_skip = copy.deepcopy(PeaksClass.peaks_original)
        for item in PeaksClass.peaks_original_marked_skip:
            item["skipped"] = False
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
                    PeaksClass.peaks_original_marked_skip[i+skip_counter]['skipped'] = True
                    PeaksClass.peaks_original_marked_skip[i+skip_counter + 1]['skipped'] = True
                    skip_counter = skip_counter + 2  # 2個消すので、2個分インクリメントが必要

                    # 消す作業の本番
                    peaks[latest_num]['oldest_body_peak_price'] = oldest_merged_item['oldest_body_peak_price']
                    peaks[latest_num]['oldest_time_jp'] = oldest_merged_item['oldest_time_jp']
                    peaks[latest_num]['oldest_price'] = oldest_merged_item['oldest_price']
                    peaks[latest_num]['count'] = (latest_item['count'] + vanish_item['count'] +
                                                         oldest_merged_item['count']) - 2
                    peaks[latest_num]['previous'] = oldest_merged_item['previous']
                    peaks[latest_num]['gap'] = round(abs(latest_item['latest_body_peak_price'] -
                                                                oldest_merged_item['oldest_body_peak_price']), 3)
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
        # peaks = copy.deepcopy(PeaksClass.peaks_original)  # PeaksClass.peaks_original.copy()では浅いコピーとなる
        peaks = copy.deepcopy(PeaksClass.skipped_peaks)  # PeaksClass.peaks_original.copy()では浅いコピーとなる
        # PeaksClass.peaks_original_marked_hard_skip = copy.deepcopy(PeaksClass.peaks_original)
        PeaksClass.peaks_original_marked_hard_skip = copy.deepcopy(PeaksClass.peaks_original_marked_skip)
        for item in PeaksClass.peaks_original_marked_hard_skip:
            item["skipped"] = False
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
                    PeaksClass.peaks_original_marked_hard_skip[i+skip_counter]['skipped'] = True
                    PeaksClass.peaks_original_marked_hard_skip[i+skip_counter + 1]['skipped'] = True
                    skip_counter = skip_counter + 2  # 2個消すので、2個分インクリメントが必要

                    # 消す作業の本番
                    peaks[latest_num]['oldest_body_peak_price'] = oldest_item['oldest_body_peak_price']
                    peaks[latest_num]['oldest_time_jp'] = oldest_item['oldest_time_jp']
                    peaks[latest_num]['oldest_price'] = oldest_item['oldest_price']
                    peaks[latest_num]['count'] = (latest_item['count'] + vanish_item['count'] +
                                                         oldest_item['count']) - 2
                    peaks[latest_num]['previous'] = oldest_item['previous']
                    peaks[latest_num]['gap'] = round(abs(latest_item['latest_body_peak_price'] -
                                                                oldest_item['oldest_body_peak_price']), 3)
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

        target_peak = PeaksClass.peaks_original[1]
        peaks_same_direction = [d for d in PeaksClass.peaks_original if d["direction"] == target_peak['direction']]
        peaks_oppo_direction = [d for d in PeaksClass.peaks_original if d["direction"] == target_peak['direction'] * -1]
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
        # skip = True
        # ■■情報の設定
        if skip:
            # Skip Peakを利用する
            peaks = PeaksClass.skipped_peaks
        else:
            peaks = PeaksClass.peaks_original
        # ターゲット情報
        # target_num = 2
        target_peak = peaks[target_num]
        target_price = target_peak['latest_body_peak_price']
        # print("   実行時引数 SKIP：", skip, " TargetNum:", target_num)
        # print("   ターゲットになるピーク@cp:", target_peak)

        # ■■閾値の情報
        # Margin情報
        arrowed_range = self.recent_fluctuation_range * 0.04  # 最大変動幅の4パーセント程度
        # arrowed_range = self.recent_fluctuation_range * 0.07  # 最大変動幅の4パーセント程度
        # 山の情報
        mountain_foot_min = 60  # 山のすそ野の広さ（この値以上の山の裾野の広さを狙う）
        base_time = datetime.strptime(peaks[0]['time'], '%Y/%m/%d %H:%M:%S')

        # ■■SamePriceListのリセット(繰り返し呼ばれた場合、.appendで追加だけされてしまう）
        PeaksClass.same_price_list = []
        PeaksClass.same_price_list_till_break = []
        PeaksClass.same_price_list_till_break2 = []
        PeaksClass.same_price_list_inner = []
        PeaksClass.same_price_list_outer = []
        PeaksClass.result_not_same_price_list = []
        PeaksClass.opposite_peaks = []
        PeaksClass.break_peaks = []
        PeaksClass.break_peaks_inner = []
        PeaksClass.break_peaks_outer = []
        # ■■同一価格の探索
        break_num = 0  #
        same_price_num = 0
        break_border = 1  # この数以上のBreakが発生するまでの同一価格リストを求める
        break_border2 = 2  # この数以上のBreakが発生するまでの同一価格リストを求める
        for i, item in enumerate(peaks):
            # print("     検証対象：", item['time'], item['peak_strength'], base_time)

            # 同一方向のものの、検索対象
            if item['direction'] != target_peak['direction']:
                continue
            # 既定の裾野の内側にある場合inner=True
            time_gap_sec = abs(datetime.strptime(item['latest_time_jp'], '%Y/%m/%d %H:%M:%S') - base_time)
            if time_gap_sec <= timedelta(minutes=mountain_foot_min):
                is_inner = True
            else:
                is_inner = False

            # 最初の一つは確保する（自分自身はたとえ強度が低くても、確保する）
            if i == target_num:
                # print("          FIRST：", item['time'], item['peak_strength'])
                PeaksClass.same_price_list.append({"i": i, "item": item, "time_gap": time_gap_sec})
                PeaksClass.same_price_list_till_break.append({"i": i, "item": item, "time_gap": time_gap_sec})
                PeaksClass.same_price_list_till_break2.append({"i": i, "item": item, "time_gap": time_gap_sec})
                if is_inner:
                    PeaksClass.same_price_list_inner.append({"i": i, "item": item, "time_gap": time_gap_sec})
                else:
                    PeaksClass.same_price_list_outer.append({"i": i, "item": item, "time_gap": time_gap_sec})
                continue
            # 除外条件（ターゲットより前の場合)
            if i < target_num:
                continue

            # Breakかを先に判定する
            if target_peak['direction'] == 1:
                if item['peak'] > target_price + arrowed_range:
                    # print("          Break up：", item['time'], item['peak_strength'])
                    # ターゲットピークを越えている場合(UpperLineで、上側に突き抜け）、NG
                    PeaksClass.break_peaks.append({"i": i, "item": item, "time_gap": time_gap_sec})
                    if is_inner:
                        PeaksClass.break_peaks_inner.append({"i": i, "item": item, "time_gap": time_gap_sec})
                    else:
                        PeaksClass.break_peaks_outer.append({"i": i, "item": item, "time_gap": time_gap_sec})
                    # 共通
                    break_num = break_num + 1
            else:
                if item['peak'] < target_price - arrowed_range:
                    # print("          Break：", item['time'], item['peak_strength'])
                    # ターゲットピークを越えている場合（lowerLineで下に突き抜け）、NG
                    PeaksClass.break_peaks.append({"i": i, "item": item, "time_gap": time_gap_sec})
                    if is_inner:
                        PeaksClass.break_peaks_inner.append({"i": i, "item": item, "time_gap": time_gap_sec})
                    else:
                        PeaksClass.break_peaks_outer.append({"i": i, "item": item, "time_gap": time_gap_sec})
                    # 共通
                    break_num = break_num + 1

            # 同一価格リストを取得（Breakがn個発生するまでの同一価格、全体の同一価格、時間内の同一価格）
            body_gap_abs = abs(target_price - item['peak'])
            if abs(item['latest_wick_peak_price'] - item['peak']) >= arrowed_range:
                # 髭が長すぎる場合は無効（無効は、上限をオーバーする値に設定してしまう
                body_wick_gap_abs = arrowed_range + 1  # 確実にarrowed_rangeより大きな値
            else:
                body_wick_gap_abs = abs(target_price - item['latest_wick_peak_price'])
            # wick_body_gap_abs = abs(target_peak['latest_wick_peak_price'] - item['peak'])
            # if body_gap_abs <= arrowed_range or body_wick_gap_abs <= arrowed_range or wlen(result_same_price_list)ick_body_gap_abs <= arrowed_range:
            if body_gap_abs <= arrowed_range or body_wick_gap_abs <= arrowed_range:
                # 同一価格とみなせる場合
                # print("          同一価格：")
                PeaksClass.same_price_list.append({"i": i, "item": item, "time_gap": time_gap_sec})
                # 同一価格とみなせる場合で、さらに時間いないかどうかを検証する
                if is_inner:
                    # print("         　 　　　　inner：")
                    PeaksClass.same_price_list_inner.append({"i": i, "item": item, "time_gap": time_gap_sec})
                else:
                    # print("         　 　　　　outer：")
                    PeaksClass.same_price_list_outer.append({"i": i, "item": item, "time_gap": time_gap_sec})
                # BreakがN個以下までの同一価格
                if break_num <= break_border:
                    PeaksClass.same_price_list_till_break.append({"i": i, "item": item, "time_gap": time_gap_sec})
                if break_num <= break_border2:
                    PeaksClass.same_price_list_till_break2.append({"i": i, "item": item, "time_gap": time_gap_sec})
                # 共通
                same_price_num = same_price_num + 1
            else:
                # print("          Not：",body_gap_abs,arrowed_range,body_wick_gap_abs,arrowed_range)
                PeaksClass.result_not_same_price_list.append({"i": i, "item": item, "time_gap": time_gap_sec})
        # 表示用
        # print("同一価格一覧 @cp")
        # f.print_arr(PeaksClass.same_price_list)
        # print("70分以内の同一価格一覧 @cp")
        # f.print_arr(PeaksClass.same_price_list_inner)
        # print("Break一覧 @cp")
        # f.print_arr(PeaksClass.break_peaks)
        # print("70分以内のBreak一覧 @cp")
        # f.print_arr(PeaksClass.break_peaks_inner)
        # print("70分より前のBreak一覧 @cp")
        # f.print_arr(PeaksClass.break_peaks_outer)
        # print("Breakまでの同一価格 @cp")
        # f.print_arr(PeaksClass.same_price_list_till_break)
        # print("Break2までの同一価格 @cp")
        # f.print_arr(PeaksClass.same_price_list_till_break2)


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


def check_large_body_in_peak(block_ans):
    """
    対象となる範囲のデータフレームをループし（ブロックを探すのと並行してやるので、二回ループ作業してることになるが）
    突発を含むかを判定する
    ついでに、HighLowのプライスも取得する
    """
    # 大きい順に並べる
    s6 = "      "

    # 足や通過に依存する数字
    dependence_very_large_body_criteria = 0.2
    dependence_large_body_criteria = 0.1

    # 情報を取得する
    sorted_df_by_body_size = block_ans['data'].sort_values(by='body_abs', ascending=False)
    max_body_in_block = sorted_df_by_body_size["body_abs"].max()

    # ■極大の変動を含むブロックかの確認
    include_very_large = False
    for index, row in sorted_df_by_body_size.iterrows():
        if row['body'] >= dependence_very_large_body_criteria:
            include_very_large = True
            break
        else:
            include_very_large = False

    # ■突発的な変動を含むか判断する（大き目サイズがたくさんあるのか、数個だけあるのか＝突発）
    counter = 0
    for index, row in sorted_df_by_body_size.iterrows():
        # 自分自身が、絶対的に見て0.13以上と大きく、他の物より約2倍ある物を探す。（自分だけが大きければ、突然の伸び＝戻る可能性大）
        # 自分自身を、未達カウントするため注意が必要
        smaller_body = row['body_abs'] if row['body_abs'] != 0 else 0.00000001
        if max_body_in_block > dependence_large_body_criteria:
            if max_body_in_block / smaller_body > 1.8:  # > 0.561:
                # print(s6, "Baseが大きめといえる", smaller_body / max_body_in_block , "size", smaller_body, max_body_in_block, row['time_jp'])
                counter = counter + 1
            else:
                pass
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


def peaks_information(peaks):
    """
    Peakが渡されると、色々な情報を計算してくれる
    渡されたＰｅａｋｓでの最大値、最小値

    """


def print_peaks():
    """
    information fix内で、latest等を表示する際、NextとPreviousのせいで、表示が長くなる。
    この二つを除去する
    """
    copy_data = copy.deepcopy(PeaksClass.skipped_peaks)
    copy_data.pop('next', None)
    copy_data.pop('previous', None)
    return copy_data




# def make_same_price_list_from_target_price(target_price, target_dir, peaks_all, same_price_range, is_recall):
#     """
#     target_dir方向（1の場合は上側、-1の場合は下側）のピーク値について以下を調査する
#     target_priceで指定された価格と近い価格(same_price_rangeの幅以内)にあるピークを検出する。
#     検討の上、一つ目の該当するピークが発見された場合、それをtarget_priceに置き換えで再帰する（ただし一回のみ。is_recallでコントロール）
#
#     返却値
#     """
#
#     s4 = "    "
#     s6 = "      "
#     # print(s4, "同価格リスト関数", is_recall)
#     # ■通貨等に依存する数字
#     dependence_same_price_range = same_price_range  # 0.027ガベスト
#
#     # ■各初期値
#     counter = 0  # 何回同等の値が出現したかを把握する
#     depth_point_gap = 0  # 今のピークと一番離れている値、かつ、逆方向のポイント（同価格発見のタイミングでリセット）
#     depth_point = 0
#     depth_point_time = 0
#     depth_break_count = depth_fit_count = 0
#     near_point_gap = 100  # 同価格ではないが、一番近い値、かつ、同方向のポイント(同価格を発見のタイミングでリセットされる）
#     near_point = 0
#     near_point_time = 0
#     near_break_count = near_fit_count = 0
#     same_price_list = []
#     start_adjuster = 0
#     between_peaks_num = start_adjuster  # 間に何個のピークがあったか。予測の場合は０
#
#     # peakの並び替えを実施（テスト中）
#     peaks_all_for_loop = peaks_all  # テストの時にコメントアウトしやすいように。。
#     # if target_dir == 1:
#     #     # 求める方向が上側のピークLineであれば、降順
#     #     peaks_all_for_loop = sorted(peaks_all, key=lambda x: x["peak"], reverse=True)
#     # else:
#     #     # 求める方向が下側のピークLineであれば、昇順
#     #     peaks_all_for_loop = sorted(peaks_all, key=lambda x: x["peak"])
#
#     # 返却値
#     return_dic = {
#         "same_price_list": [],
#         "strength_info": {"line_strength": 0},
#     }
#
#     for i, item in enumerate(peaks_all_for_loop):
#         # 判定を行う
#         # print(s6, " 判定", item['time'], target_price - dependence_same_price_range, "<", item['peak'], "<=",
#         # target_price + dependence_same_price_range, item['direction'],
#         # target_price - dependence_same_price_range <= item['peak'] <= target_price + dependence_same_price_range)
#         this_peak_price_info = {
#             "time": item['time'],
#             "peak": item['peak'],
#             "same_dir": True,  # これは直後で上書きする
#             "direction": target_dir,
#             "count_foot_gap": i,
#             "depth_point_gap": round(depth_point_gap, 3),
#             'depth_point': depth_point,
#             "depth_point_time": depth_point_time,
#             "depth_break_count": depth_break_count,
#             "depth_fit_count": depth_fit_count,
#             "near_point_gap": round(near_point_gap, 3),
#             "near_point": near_point,
#             "near_point_time": near_point_time,
#             'near_break_count': near_break_count,
#             'near_fit_count': near_fit_count,
#             "between_peaks_num": between_peaks_num,
#             "i": i,  # 何個目か
#             "peak_strength": item['peak_strength']  # 最終日の場合のみ後で上書きされる
#         }
#
#         # 最後尾のPeakを参考用として付属させる場合(本当は使いたいが、いったん機能削除）
#         add_oldest_peak = False
#         if add_oldest_peak and i == len(peaks_all_for_loop) - 1 and len(same_price_list) != 0:
#             # 最後尾の場合、痕跡として追加する。ただし、何か情報がある場合のみ追加する（何もない場合は０で返したいため）
#             this_peak_price_info['same_dir'] = False  # 一部上書き
#             this_peak_price_info['peak_strength'] = 0  # 一部上書き
#             same_price_list.append(this_peak_price_info)
#             break  # 重複して登録しないようにループ終了（同一価格を見逃すが、最後の時点で遠い話なので無視する）
#
#         # 実際のループの中身↓
#         if target_price - dependence_same_price_range <= item['peak'] <= target_price + dependence_same_price_range:
#             # ■同価格のピークがあった場合
#             if counter == 0:
#                 if not is_recall:
#                     # (recall(2個目以上の対象)の場合は、基準であるtargetPrice変更しない）
#                     # 今回のtargetPriceで最初の発見（最低値か最高値）の場合、それにtargetPriceを合わせに行く(それ基準で近い物を探すため）
#                     # (再起呼び出しされている場合は、ここはやらずに結果を返却するのみ)
#                     # print(s6, "target 変更 ", target_price, " ⇒", item['peak'], dependence_same_price_range)
#                     recall_result = make_same_price_list_from_target_price(item['peak'], target_dir, peaks_all,
#                                                                            same_price_range, True)
#                     return recall_result
#             # 同一価格のピークの情報を取得する
#             counter += 1
#             # 方向に関する判定
#             if item['direction'] == target_dir:
#                 # print("　　　　同方向の近似ピーク（≒ダブルピークの素）", item['time'], near_point_gap)
#                 this_peak_price_info['same_dir'] = True  # 一部上書き
#                 same_price_list.append(this_peak_price_info)
#                 # same_price_list.append({"time": item['time'],
#                 #                   "peak": item['peak'],
#                 #                   "same_dir": True,  # 同じ方向のピークかどうか
#                 #                   "direction": target_dir,
#                 #                   "count_foot_gap": i,
#                 #                   "depth_point_gap": round(depth_point_gap, 3),
#                 #                   'depth_point': depth_point,
#                 #                   "depth_point_time": depth_point_time,
#                 #                   "depth_break_count": depth_break_count,
#                 #                   "depth_fit_count": depth_fit_count,
#                 #                   "near_point_gap": round(near_point_gap, 3),
#                 #                   "near_point": near_point,
#                 #                   "near_point_time": near_point_time,
#                 #                   'near_break_count': near_break_count,
#                 #                   'near_fit_count': near_fit_count,
#                 #                   "between_peaks_num": between_peaks_num,
#                 #                   "i": i,  # 何個目か
#                 #                   "peak_strength": item['peak_strength']
#                 #                   })
#                 # 通過したピーク情報を初期化する
#                 near_point_gap = 100
#                 near_break_count = near_fit_count = depth_break_count = depth_fit_count = depth_point_gap = 0
#                 between_peaks_num = start_adjuster  # 初期値は1のため注意
#
#         else:
#             # ■同価格のピークではなかったの場合、通過するが記録は残す。
#             between_peaks_num += 1
#             # 条件分岐
#             peak_gap = (target_price - item['peak']) * target_dir
#             # 計算
#             if item['direction'] != target_dir:
#                 # 方向が異なるピークの場合→Depthの方
#                 # 深さの値を取得する
#                 if peak_gap > depth_point_gap:
#                     # 最大深度を更新する場合
#                     depth_point_gap = peak_gap
#                     depth_point = item['peak']
#                     depth_point_time = item['time']
#                 # マイナスプラスをカウントする
#                 if peak_gap <= 0:
#                     depth_break_count += 1  # マイナスというより、LINEを突破している位置にあるカウント
#                 else:
#                     depth_fit_count += 1
#
#             if item['direction'] == target_dir:
#                 # 同じピークの場合→Nearの方　ニアの方の深さの値を取得する
#                 # print("     TIME", item['time'])
#                 if peak_gap < near_point_gap:
#                     # 最も近い価格を超える（かつ逆方向）場合
#                     near_point_gap = peak_gap
#                     near_point = item['peak']
#                     near_point_time = item['time']
#                 # マイナスプラスをカウントする
#                 # print("     nearPointGap", peak_gap, item['time'])
#                 if peak_gap <= 0:
#                     near_break_count += 1
#                 else:
#                     near_fit_count += 1
#
#     # リスト完成後の処理（並び替えや、強度の算出）
#     if len(same_price_list) == 0:
#         # 同一価格が存在しない場合、何もしない
#         pass
#     else:
#         # 同一価格が存在する場合、強度を算出しておく
#         same_price_list = sorted(same_price_list, key=lambda x: x["time"], reverse=True)  # 念のため時間順に並び替え
#         strength_info = cal_strength_of_same_price_list(same_price_list, peaks_all, target_price, target_dir)
#         return_dic['same_price_list'] = same_price_list  # 返却値にセット
#         return_dic['strength_info'] = strength_info  # 返却値にセット
#
#     return return_dic
