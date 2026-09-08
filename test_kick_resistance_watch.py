# 最新更新日時: 2026-09-07 JST
"""抵抗線ブレイクの注文を「見るだけ」。発注しない。

チャートと突き合わせて、想定した線・想定した価格に注文が出るかを
確かめるためのもの。**このツールは注文に一切触れない**（発注も取消も決済もしない）。

実発注は `fResistanceOrder` を作って `fAnalysis_order_Main` の解析登録に載せ、
`classPositionControl` に管理させる。OANDA へ直接発注する経路は作らないこと。

5分ごとに、3通貨について M5 と M30 の線を組み立て、
検証（2023-2025の2年）と同じ条件で出すはずの逆指値を表示する。

    python test_kick_resistance_watch.py

止めるときは Ctrl+C。
"""

from resistance_live_monitor import run

# ■ 設定（実行引数は使わない。ここを直して実行する）
TIMEFRAMES = ("M5", "M30")          # ("M30",) にすると M30 だけ
PAIRS = ("AUD_USD", "EUR_USD", "USD_JPY")
RISK_YEN = 500.0                    # 表示する建玉の計算に使う
MAX_UNITS = 3000                    # 建玉の上限
MIN_TP_SPREAD_RATIO = 3.0           # 利確がスプレッドの何倍以上なら出すか
HORIZON_MINUTES = 60                # 約定から何分で手仕舞いするか
INTERVAL_SECONDS = 300              # 確認の間隔。300秒＝M5の確定に合わせる
ONCE = False                        # True にすると1回だけ見て終了


if __name__ == "__main__":
    run(
        timeframes=TIMEFRAMES,
        pairs=PAIRS,
        risk_yen=RISK_YEN,
        max_units=MAX_UNITS,
        min_tp_spread_ratio=MIN_TP_SPREAD_RATIO,
        horizon_minutes=HORIZON_MINUTES,
        interval_seconds=INTERVAL_SECONDS,
        once=ONCE,
    )
