# 最新更新日時: 2026-08-25 23:20 JST
"""AUD/USD live launcher."""

# True: OANDA通信・実発注を有効化 / False: 接続せず終了
LIVE = False

from main_exe import run


if __name__ == "__main__":
    run("AUD_USD", live=LIVE)
