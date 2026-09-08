# 最新更新日時: 2026-09-03 06:54 JST
"""AUD/USD のM5・M30・H1抵抗線を「抜ける側」へ逆指値で入り、OOS 1年で測る。

各ライン足は対応するnative完成足からPeaksを作る。M30をM5で代用しない。

既存の逆張り版（resistance_sweep_candidates_*）と、期間もライン生成も同じ。
注文方向と起動条件だけを入れ替える。逆張りは決着 n=20,458 で実測勝率が
ランダム基準を 5.5〜7.5 ポイント下回ったため、その裏返しを確かめる。

逆指値は成行約定で有利な価格が保証されず、ライン突破直後は値動きが速い。
``--stop-slippage-pips`` を 0 にすると実運用より良い数字が出るので、
不利側へ 0.5pips 滑った価格を建値にしている。

3通貨を並列で走らせるため、通貨ごとに起動ファイルを分けてある。
``win_point.PAIR`` へのモジュール変数の書き換えがあるので、
スレッドではなく必ずプロセスを分けること。

    python test_kick_aud_usd_resistance_break.py
"""

from count2_resistance_sweep import main


PAIR = "AUD_USD"
ARGV = [
    "--start", "2025-07-30 00:00:00",
    "--end", "2026-07-30 00:00:00",
    "--entry-mode", "stop",
    "--stop-offset-pips", "1.0",
    "--stop-slippage-pips", "0.5",
    # ラインの構成ピークを min_line_peak_strength(=2) 以上に絞る。
    # これは素材のピークを変えるので、後から絞り直せない。走行時に決める。
    "--enforce-peak-strength",
    # グループ化幅をA単位に。固定1.0pipsだと、同じ水準の高値が
    # ボラティリティ次第で別々の線に割れてしまう。
    # これもグループ化そのものを変えるので、後から絞り直せない。
    "--group-threshold-a", "0.5",
    # TP/LCをA単位で総当たりし、セルごとの優位性を集計する。
    "--target-grid",
    #
    # ここから下は「絞らない」方針。走行が長いので、候補を減らさず記録し、
    # 距離・強度・peaks数・向きの閾値は解析時に振る。以下は全て候補CSVの
    # 列から後で再現できる：
    #   --min-distance-a          -> distance_pips
    #   --min-line-total-strength -> line_total_strength
    #   --min-line-peak-count     -> line_count
    #   --exclude-flipped-recent  -> line_newest_peak_direction
    #   --separate-line-directions-> line_same/opposite_direction_count
    # native M30キャッシュが無い場合は、実行時にOANDAから取得して保存する。
]


if __name__ == "__main__":
    main(PAIR, list(ARGV))
