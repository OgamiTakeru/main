import datetime
from datetime import datetime
from datetime import timedelta
import pandas as pd
from collections import defaultdict
import tokens as tk
import fGeneric as gene
import fGeneric as f
import copy
import classCandlePeaks as peaksClass



class candleAnalysis:
    def __init__(self, original_df, oa):
        self.df_r = original_df
        self.peaks_class = peaksClass.PeaksClass(original_df)  # ★★peaks_classインスタンスの生成

        # 変数系
        # cal_move_size関数
        self.recent_fluctuation_range = 0  # 指定ではなく、計算で算出される。直近N足分以内での最大変動幅（最高値ー最低値）round済み
        self.fluctuation_gap = 0.3  # 急変動とみなす1足の変動は30pips以上。（1足でPeakの変動ではない）
        self.fluctuation_count = 3  # 3カウント以下でfluctuation_gapが起きた場合、急変動とみなす
        self.is_big_move_candle = False
        # cal_move_ave関数
        self.ave_move = 0
        self.ave_move_for_lc = 0

    def cal_move_size(self):
        # ■データフレームの状態で、サイズ感を色々求める
        filtered_df = self.df_r.df_r_original[:65]  # 直近4時間の場合、12×4 48
        sorted_df = filtered_df.sort_values(by='body_abs', ascending=False)
        max_high = sorted_df["inner_high"].max()
        min_low = sorted_df['inner_low'].min()
        self.recent_fluctuation_range = round(max_high - min_low, 3)
        self.ave_move = filtered_df.head(5)["highlow"].mean()
        self.ave_move_for_lc = self.ave_move * 1.6
        print("   ＜稼働範囲サマリ＞")
        print("    検出範囲", filtered_df.iloc[0]["time_jp"], "-", filtered_df.iloc[-1]['time_jp'])
        print("    最大値、最小値", max_high, min_low, "差分")
        print("    平均キャンドル長", filtered_df.head(5)["highlow"].mean())
        print("    提唱LC幅", self.ave_move_for_lc)
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
            print("特殊事態（Peaksが少なすぎる）")
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
        if max_body >= 0.1:
            self.is_big_move_candle = True
        else:
            self.is_big_move_candle = False

    def cal_move_ave(self, times):
        """
        直近の動き幅のtimes倍の数値を返却する(直接LC Rangeに利用することを想定）
        """
        # ■データフレームの状態で、サイズ感を色々求める
        filtered_df = self.peaks_class.df_r_original[:65]  # 直近4時間の場合、12×4 48
        self.ave_move = filtered_df.head(9)["highlow"].mean()
        self.ave_move_for_lc = self.ave_move * times
        return self.ave_move_for_lc
