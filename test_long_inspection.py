import datetime

import classInspection as ci


# 検証メモ / 結果CSVをためて確認したい観点:
# - 現在RSIによる方向ゲート
#   - 反転BUYは、基本的にRSIが低い状態から狙う。
#   - 反転SELLは、基本的にRSIが高い状態から狙う。
#   - 現在RSIが低いだけで、遠い上側抵抗線へのSELLを正当化しない。
# - 直近ピークRSI
#   - peaks[0].rsi を latest_peak_rsi、peaks[1].rsi を previous_peak_rsi として保存する。
#   - 理由: ラインへの指値注文では、約定時点のRSIは注文判断時には分からない。
#     そのため、直近ピークのRSIから、ライン到達前の相場がすでに過熱/売られすぎか、
#     まだ勢いが残っているかを見る。
#   - 将来のライン到達を前提にしたTOP10判定では、現在足RSIではなくピークRSIのbinを見る。
#   - 特に count=2 の形では、peaks[0] と peaks[1] が直近の動きを作っているので重視する。
# - ライン構成ピークRSI
#   - line_peak_rsi_avg、line_peak_rsi_latest、line_peak_rsi_count を保存する。
#   - 理由: ラインは複数ピークで構成されるため、平均/最新RSIはライン側の性質として見る。
#     一方、peaks[0]/peaks[1] のRSIは、現在に近い相場状態として見る。
# - ラインの質
#   - line_count、line_total_strength、core_count、core_total_strength、
#     line_is_flipped、直近タッチ/ロール反転の新しさを比較する。
# - 距離と経路
#   - target_distance_pips、H1のnearest/ahead/path距離を見る。
#   - M5のターゲットに届く前に、H1ラインが進行方向をブロックしていないか確認する。
# - 結果の見方
#   - 約定率と、約定後の勝率を分けて見る。
#   - max_plus_pips、max_minus_pips、res、経過時間、first reach side を比較する。
# - セッションとTP
#   - session_name、session_hour、session_rr、session_tp_pips、path TP調整を見る。
# - 通貨ペアごとの差
#   - USD_JPY、EUR_USD、AUD_USDでは最適な閾値が違う可能性がある。
#   - 1つの通貨ペアで良かったRSI/ライン条件を、そのまま他ペアに移植しない。

PAIR = "USD_JPY"
# Previous inspection ranges kept for quick switching.
START_TIME = datetime.datetime(2025, 12, 24, 0, 0, 0)
# START_TIME = datetime.datetime(2026, 6, 24, 0, 0, 0)
END_TIME = datetime.datetime(2026, 6, 24, 0, 0, 0)

# START_TIME = datetime.datetime(2026, 7, 16, 6, 0, 0)
# END_TIME = datetime.datetime(2026, 7, 16, 23, 30, 0)

START_TIME = datetime.datetime(2026, 7, 14, 0, 0, 0)
END_TIME = datetime.datetime(2026, 7, 18, 6, 0, 0)

memo = f"{PAIR} line inspection"
cache_name = f"{PAIR}_{START_TIME:%Y%m%d%H%M%S}_{END_TIME:%Y%m%d%H%M%S}"

inspection = ci.Inspection(
    is_exist_data=False,
    start_time=START_TIME,
    end_time=END_TIME,
    h1_data_path=f"C:/Users/taker/OneDrive/Desktop/oanda_logs/h1_{cache_name}.csv",
    m5_data_path=f"C:/Users/taker/OneDrive/Desktop/oanda_logs/m5_{cache_name}.csv",
    m30_data_path=None,
    s5_data_path=f"C:/Users/taker/OneDrive/Desktop/oanda_logs/s5_{cache_name}.csv",
    memo=memo,
    anaN=60,
    insN=8640,
    target_interval_minutes=5,
    pair=PAIR,
)

print(inspection.result_df)
