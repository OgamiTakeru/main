# 最新更新日時: 2026-08-29 12:43 JST
"""Explicit launcher for AUD/USD live operation.

2026-08-27: flip 専用サービス（fFlipPredictLive.run_live）から main_exe へ移行。
flip が生んだオーダーも classPositionControl のスロットで管理されるようになり、
通貨ごとの保有数を一元的に数えられる。解析の有効モードと実行条件は
fAnalysis_order_Main.py の解析登録表で管理する。
"""

from __future__ import annotations

# True: OANDA通信・実発注を有効化 / False: 接続せず終了
LIVE = True

PAIR = "AUD_USD"


def main() -> None:
    if LIVE is not True:
        raise SystemExit(
            f"{PAIR}: OANDAへは接続していません。"
            "main_exe_aud.py先頭のLIVEをTrueにしてください。"
        )
    # Import after the LIVE guard so LIVE=False cannot create
    # an OANDA client or perform any broker/Discord communication.
    from main_exe import run

    # 通貨はここで名指しする（実行するファイルで対象口座が決まる）。
    run(PAIR, live=LIVE)


if __name__ == "__main__":
    main()
