import threading  # 定時実行用
import time
import datetime
import sys
import pandas as pd

# 自作ファイルインポート
import programs.tokens as tk  # Token等、各自環境の設定ファイル（git対象外）
import programs.classOanda as classOanda
import programs.classPosition as classPosition  # とりあえずの関数集
import programs.fTurnInspection as t  # とりあえずの関数集
import programs.fGeneric as f
import programs.fPeakLineInspection as p



# ■グローバル変数の宣言等
# 変更なし群
gl_peak_range = 2  # ピーク値算出用　＠ここ以外で変更なし
gl_arrow_spread = 0.008  # 実行を許容するスプレッド　＠ここ以外で変更なし
gl_first = 0
# 変更あり群
gl_now = 0  # 現在時刻（ミリ秒無し） @exe_loopのみで変更あり
gl_now_str = ""
gl_now_price_mid = 0  # 現在価格（念のための保持）　@ exe_manageでのみ変更有
gl_midnight_close_flag = 0  # 深夜突入時に一回だけポジション等の解消を行うフラグ　＠time_manageのみで変更あり
gl_exe_mode = 0  # 実行頻度のモード設定　＠
gl_data5r_df = 0  # 毎回複数回ローソクを取得は時間無駄なので１回を使いまわす　＠exe_manageで取得
gl_trade_num = 0  # 取引回数をカウントする
gl_result_dic = {}
# gl_trade_win = 0  # プラスの回数を記録する
gl_live = "Pra"
gl_first_time = ""  # 初回の時間を抑えておく（LINEで見やすくするためだけ）
gl_latest_exe_time = 0  # 実行タイミングに幅を持たせる（各５の倍数分の６秒~３０秒で１回実行）に利用する
gl_latest_trigger_time = datetime.datetime.now() + datetime.timedelta(minutes=-6)  # 新規オーダーを入れてよいかの確認用
gl_peak_memo = {"memo_latest_past":"", "memo_mini_gap_past": "", "memo_para": ""}

# 倍率関係
unit_mag = 10 # 基本本番環境で動かす。unitsを低めに設定している為、ここで倍率をかけれる。
mag_unit_w = 1  # 勝っているときのUnit倍率
mag_lc_w = 1  # 勝っているときのLC幅の調整
mag_tp_w = 1  # 勝っているときのLC幅の調整
mag_unit_l = 1  # 負けている時のUnit倍率
mag_lc_l = 0.8  # 負けているときのLC幅の調整
mag_tp_l = 1  # 負けているときのLC幅の調整

# ■オアンダクラスの設定
fx_mode = 0  # 1=practice, 0=Live
if fx_mode == 1:  # practice
    oa = classOanda.Oanda(tk.accountID, tk.access_token, tk.environment)  # インスタンス生成
    gl_live = "Pra"
else:  # Live
    oa = classOanda.Oanda(tk.accountIDl, tk.access_tokenl, tk.environmentl)  # インスタンス生成
    gl_live = "Live"

# ■ポジションクラスの生成
main_c = classPosition.order_information("1", oa)  # 順思想のオーダーを入れるクラス
second_c = classPosition.order_information("2", oa)  # 順思想のオーダーを入れるクラス
third_c = classPosition.order_information("3", oa)  # 順思想のオーダーを入れるクラス
fourth_c = classPosition.order_information("4", oa)  # 順思想のオーダーを入れるクラス
watch1_c = classPosition.order_information("5", oa)
watch2_c = classPosition.order_information("6", oa)
# ■ポジションクラスを一まとめにしておく
classes = [main_c, second_c, third_c, fourth_c, watch1_c, watch2_c]

# ■処理の開始
# classPosition.reset_all_position(classes)  # 開始時は全てのオーダーを解消し、初期アップデートを行う
# tk.line_send("■■新規スタート", gl_live)

# ↓ファイル読み込みテスト
df = pd.read_csv(tk.folder_path + 'main_data5.csv', sep=",", encoding="utf-8")
f.draw_graph(df)
df_r = df.sort_index(ascending=False)
# ↑ファイル読み込みテスト
test = p.peaks_collect_main(df_r)
f.print_arr(test['all_peaks'])
# main()

