# 最新更新日時: 2026-08-25 23:20 JST
"""Explicit launcher for EUR/USD flip_predict live operation."""

from __future__ import annotations

# True: OANDA通信・実発注を有効化 / False: 接続せず終了
LIVE = True


def main() -> None:
    if LIVE is not True:
        raise SystemExit(
            "EUR_USD: OANDAへは接続していません。"
            "main_exe_euro.py先頭のLIVEをTrueにしてください。"
        )
    # Import after the LIVE guard so LIVE=False cannot create
    # an OANDA client or perform any broker/Discord communication.
    from fFlipPredictLive import run_live

    run_live()


if __name__ == "__main__":
    main()
