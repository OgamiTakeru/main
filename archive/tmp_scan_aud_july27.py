import contextlib
import datetime
import io
import json
from pathlib import Path

import pandas as pd

import classInspection as ci
import send_notice


OUTPUT = Path("tmp_aud_july27_scan_summary.json")
send_notice.line_send = lambda *args, **kwargs: None
start = datetime.datetime(2026, 7, 27, 0, 0)
end = datetime.datetime(2026, 7, 27, 23, 55)
cache = "AUD_USD_20260727000000_20260727235500"


class QuietInspection(ci.Inspection):
    def save_loaded_data(self): return
    def save_result_data(self): return
    def print_tp_last_touch_winrate_summary(self): return
    def print_elapsed_time(self): return


with contextlib.redirect_stdout(io.StringIO()):
    inspection = QuietInspection(
        is_exist_data=True,
        start_time=start,
        end_time=end,
        h1_data_path=rf"C:\Users\taker\OneDrive\Desktop\oanda_logs\h1_{cache}.csv",
        m5_data_path=rf"C:\Users\taker\OneDrive\Desktop\oanda_logs\m5_{cache}.csv",
        m30_data_path=rf"C:\Users\taker\OneDrive\Desktop\oanda_logs\m30_{cache}.csv",
        s5_data_path=rf"C:\Users\taker\OneDrive\Desktop\oanda_logs\s5_{cache}.csv",
        memo="AUD 7/27 full scan",
        anaN=60,
        insN=8640,
        target_interval_minutes=5,
        pair="AUD_USD",
    )

rows = inspection.result_df.copy()
if rows.empty:
    OUTPUT.write_text(json.dumps({"rows": 0}), encoding="utf-8")
    raise SystemExit

rows["dt"] = pd.to_datetime(rows["target_time"])
rows["hour"] = rows["dt"].dt.hour
rows["decided"] = rows["actual_order_result"].isin(["tp", "lc"])
rows["win"] = rows["actual_order_result"].eq("tp")
rows["pips"] = pd.to_numeric(rows["actual_res"], errors="coerce").fillna(0)


def grouped(columns):
    data = []
    for keys, group in rows.groupby(columns, dropna=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        decided = group[group["decided"]]
        data.append({
            **dict(zip(columns, keys)),
            "generated": len(group),
            "filled": int((group["actual_order_result"] != "not_filled").sum()),
            "decided": len(decided),
            "wins": int(decided["win"].sum()),
            "win_rate": float(decided["win"].mean()) if len(decided) else None,
            "pips": float(decided["pips"].sum()),
        })
    return data


detail_columns = [
    "target_time", "name", "line_order_mode", "line_entry_type", "direction",
    "actual_order_result", "actual_res", "line_total_strength",
    "line_break_score", "line_resist_score", "rsi_1", "latest_peak_rsi",
    "previous_peak_rsi", "h1_nearest_total_strength",
    "h1_path_ahead_1_distance_pips", "h1_path_ahead_1_total_strength",
    "regime_at_order", "memo",
]
details = rows[detail_columns].copy()
details["target_time"] = details["target_time"].astype(str)
payload = {
    "rows": len(rows),
    "overall": grouped(["line_order_mode", "line_entry_type"]),
    "hourly": grouped(["hour", "line_order_mode", "line_entry_type"]),
    "regime": grouped(["regime_at_order", "line_order_mode", "line_entry_type"]),
    "details": details.to_dict("records"),
}
OUTPUT.write_text(
    json.dumps(payload, ensure_ascii=False, indent=2, default=str),
    encoding="utf-8",
)
