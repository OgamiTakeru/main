import datetime
import subprocess
import sys

def last_day_of_month(year, month):
    if month == 12:
        next_month = datetime.datetime(year + 1, 1, 1)
    else:
        next_month = datetime.datetime(year, month + 1, 1)

    return next_month - datetime.timedelta(days=1)


# 2024年1月 ～ 2025年12月まで
start = datetime.datetime(2024, 11, 1)
end = datetime.datetime(2025, 11, 1)

current = start

while current <= end:

    # 月末日を取得
    last_day = last_day_of_month(current.year, current.month)

    # 日付文字列（run_month.py に渡す）
    dt_str = last_day.strftime("%Y-%m-%d %H:%M:%S")

    print(f"Running: {dt_str}")

    # 別プロセスで実行（メモリ完全にリセットされる）
    subprocess.run([
        sys.executable,    # 今の Python をそのまま使う
        "run_month_inspection.py",    # サブプロセス側のスクリプト
        dt_str             # 引数として日付を渡す
    ])

    # 次の月へ進める
    if current.month == 12:
        current = current.replace(year=current.year + 1, month=1)
    else:
        current = current.replace(month=current.month + 1)