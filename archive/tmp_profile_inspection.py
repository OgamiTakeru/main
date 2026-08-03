import cProfile
import contextlib
import datetime
import io
import pstats
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import classInspection as ci
import send_notice


class ProfileInspection(ci.Inspection):
    def save_loaded_data(self):
        return

    def save_result_data(self):
        return

    def print_tp_last_touch_winrate_summary(self):
        return

    def print_elapsed_time(self):
        return


def main():
    send_notice.line_send = lambda *args, **kwargs: None
    cache = "EUR_USD_20250624000000_20260624000000"
    profiler = cProfile.Profile()
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        profiler.enable()
        inspection = ProfileInspection(
            is_exist_data=True,
            start_time=datetime.datetime(2026, 6, 1, 0, 0),
            end_time=datetime.datetime(2026, 6, 1, 6, 0),
            h1_data_path=rf"C:\Users\taker\OneDrive\Desktop\oanda_logs\h1_{cache}.csv",
            m5_data_path=rf"C:\Users\taker\OneDrive\Desktop\oanda_logs\m5_{cache}.csv",
            m30_data_path=rf"C:\Users\taker\OneDrive\Desktop\oanda_logs\m30_{cache}.csv",
            s5_data_path=rf"C:\Users\taker\OneDrive\Desktop\oanda_logs\s5_{cache}.csv",
            memo="inspection profiler",
            anaN=60,
            insN=8640,
            target_interval_minutes=5,
            pair="EUR_USD",
        )
        profiler.disable()
    print("targets:", len(inspection.build_target_times()))
    print("results:", len(inspection.results))
    pstats.Stats(profiler).strip_dirs().sort_stats("cumulative").print_stats(35)


if __name__ == "__main__":
    main()
