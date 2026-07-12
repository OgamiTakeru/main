import datetime

import classInspection as ci


PAIR = "USD_JPY"
# Previous inspection ranges kept for quick switching.
# START_TIME = datetime.datetime(2025, 6, 15, 0, 0, 0)
# END_TIME = datetime.datetime(2026, 6, 16, 10, 0, 0)
START_TIME = datetime.datetime(2025, 12, 24, 0, 0, 0)
# START_TIME = datetime.datetime(2026, 6, 22, 0, 0, 0)
END_TIME = datetime.datetime(2026, 6, 24, 0, 0, 0)
# START_TIME = datetime.datetime(2026, 6, 30, 0, 0, 0)
# END_TIME = datetime.datetime.now().replace(microsecond=0)
# START_TIME = datetime.datetime(2024, 6, 15, 0, 0, 0)
# END_TIME = datetime.datetime(2025, 6, 16, 10, 0, 0)

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
