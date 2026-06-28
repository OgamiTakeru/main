import datetime

import classInspection as ci


memo = "大量22_23 flipped H1 line inspection"

inspection = ci.Inspection(
    is_exist_data=False,
    # start_time=datetime.datetime(2025, 6, 15, 0, 0, 0),
    # end_time=datetime.datetime(2026, 6, 16, 10, 0, 0),
    # start_time=datetime.datetime(2025, 12, 24, 0, 0, 0),
    # end_time=datetime.datetime(2026, 6, 24, 0, 0, 0),
    start_time=datetime.datetime(2026, 6, 24, 17, 40, 0),
    end_time=datetime.datetime.now().replace(microsecond=0),
    # start_time=datetime.datetime(2024, 6, 15, 0, 0, 0),
    # end_time=datetime.datetime(2025, 6, 16, 10, 0, 0),
    h1_data_path="C:/Users/taker/OneDrive/Desktop/oanda_logs/大量22_23_h1_df.csv",
    m5_data_path="C:/Users/taker/OneDrive/Desktop/oanda_logs/大量22_23_m5_df.csv",
    m30_data_path=None,
    s5_data_path="C:/Users/taker/OneDrive/Desktop/oanda_logs/大量22_23_s5_df.csv",
    memo=memo,
    anaN=60,  # 1時間足何足分かで指定する
    insN=8640,  # 5秒足何足分かで指定する 12時間で8640
    target_interval_minutes=5,
)

print(inspection.result_df)
