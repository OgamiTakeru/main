import datetime
import math
from pathlib import Path

import pandas as pd

import classCandleAnalysis as ca
import classOanda
import fAnalysis_order_Main as am
import fGeneric as gene
import fTurnInspection as ti
import tokens as tk


class Inspection:
    def __init__(
        self,
        is_exist_data,
        start_time,
        end_time,
        h1_data_path,
        m5_data_path,
        m30_data_path=None,
        s5_data_path=None,
        m5_count=5000,
        loop=1,
        memo="",
        anaN=60,
        insN=500,
    ):
        self.oa = classOanda.Oanda(tk.accountIDl, tk.access_tokenl, "live")
        self.gl_exist_data = is_exist_data
        self.start_time = start_time
        self.end_time = end_time
        self.gl_jp_time = end_time
        self.gl_m5_count = m5_count
        self.gl_m5_loop = loop
        self.memo = memo
        self.anaN = anaN
        self.insN = insN

        self.gl_h1_csv_path = h1_data_path
        self.gl_main_csv_path = m5_data_path
        self.gl_m30_csv_path = m30_data_path
        self.gl_s5_csv_path = s5_data_path

        self.gl_d5_df = pd.DataFrame()
        self.gl_d5_df_r = pd.DataFrame()
        self.gl_s5_df = pd.DataFrame()
        self.gl_h1_df = pd.DataFrame()
        self.gl_h1_df_r = pd.DataFrame()
        self.gl_m30_df = pd.DataFrame()
        self.gl_m30_df_r = pd.DataFrame()
        self.result_df = pd.DataFrame()
        self.results = []

        print("Inspection start")
        self.get_data()
        self.print_loaded_data_range()
        self.save_loaded_data()
        self.run()

    def get_data(self):
        if self.gl_exist_data:
            self.load_existing_data()
        else:
            if self.load_start_cache_if_exists():
                self.normalize_time_columns()
                if self.loaded_data_covers_required_range():
                    print("Loaded cached inspection data and use it")
                    return
                print("Cached inspection data is short. Fetch from Oanda.")
            self.fetch_data_from_oanda()

        self.normalize_time_columns()

    def load_existing_data(self):
        self.gl_d5_df = pd.read_csv(self.gl_main_csv_path, sep=",", encoding="utf-8")
        self.gl_d5_df_r = self.gl_d5_df.sort_index(ascending=False)

        self.gl_h1_df = pd.read_csv(self.gl_h1_csv_path, sep=",", encoding="utf-8")
        self.gl_h1_df_r = self.gl_h1_df.sort_index(ascending=False)

        if self.gl_m30_csv_path:
            self.gl_m30_df = pd.read_csv(self.gl_m30_csv_path, sep=",", encoding="utf-8")
            self.gl_m30_df_r = self.gl_m30_df.sort_index(ascending=False)

        if self.gl_s5_csv_path:
            self.gl_s5_df = pd.read_csv(self.gl_s5_csv_path, sep=",", encoding="utf-8")

        print("M5:", self.gl_d5_df.iloc[0]["time_jp"], "-", self.gl_d5_df.iloc[-1]["time_jp"], len(self.gl_d5_df))
        print("H1:", self.gl_h1_df.iloc[0]["time_jp"], "-", self.gl_h1_df.iloc[-1]["time_jp"], len(self.gl_h1_df))

    def load_start_cache_if_exists(self):
        paths = self.cache_file_paths()
        required_keys = ("h1", "m5", "s5")
        if not all(paths[key].exists() for key in required_keys):
            return False

        self.gl_h1_df = pd.read_csv(paths["h1"], sep=",", encoding="utf-8")
        self.gl_h1_df_r = self.gl_h1_df.sort_index(ascending=False)

        self.gl_d5_df = pd.read_csv(paths["m5"], sep=",", encoding="utf-8")
        self.gl_d5_df_r = self.gl_d5_df.sort_index(ascending=False)

        self.gl_s5_df = pd.read_csv(paths["s5"], sep=",", encoding="utf-8")

        if paths["m30"].exists():
            self.gl_m30_df = pd.read_csv(paths["m30"], sep=",", encoding="utf-8")
            self.gl_m30_df_r = self.gl_m30_df.sort_index(ascending=False)

        print("Loaded cached inspection data:", paths["h1"].parent)
        return True

    def fetch_data_from_oanda(self):
        fetch_from, fetch_to = self.required_data_range()
        end_time_iso = gene.time_to_euro_iso(fetch_to)
        total_seconds = max((fetch_to - fetch_from).total_seconds(), 0)

        m5_rows = math.ceil(total_seconds / (5 * 60)) + 5
        m5_count, m5_loop = self.cal_oanda_count_and_loop(m5_rows)
        params = {"granularity": "M5", "count": m5_count, "to": end_time_iso}
        data_response = self.oa.InstrumentsCandles_multi_exe("USD_JPY", params, m5_loop)
        self.gl_d5_df = data_response["data"]
        self.gl_d5_df_r = self.gl_d5_df.sort_index(ascending=False)

        h1_rows = math.ceil(total_seconds / (60 * 60)) + 5
        h1_count, h1_loop = self.cal_oanda_count_and_loop(h1_rows)
        params = {"granularity": "H1", "count": h1_count, "to": end_time_iso}
        data_response = self.oa.InstrumentsCandles_multi_exe("USD_JPY", params, h1_loop)
        self.gl_h1_df = data_response["data"]
        self.gl_h1_df_r = self.gl_h1_df.sort_index(ascending=False)

        m30_rows = math.ceil(total_seconds / (30 * 60)) + 5
        m30_count, m30_loop = self.cal_oanda_count_and_loop(m30_rows)
        params = {"granularity": "M30", "count": m30_count, "to": end_time_iso}
        data_response = self.oa.InstrumentsCandles_multi_exe("USD_JPY", params, m30_loop)
        self.gl_m30_df = data_response["data"]
        self.gl_m30_df_r = self.gl_m30_df.sort_index(ascending=False)

        s5_rows = math.ceil(total_seconds / 5) + 5
        s5_count, s5_loop = self.cal_oanda_count_and_loop(s5_rows)
        params = {"granularity": "S5", "count": s5_count, "to": end_time_iso}
        data_response = self.oa.InstrumentsCandles_multi_exe("USD_JPY", params, s5_loop)
        self.gl_s5_df = data_response["data"]

    def normalize_time_columns(self):
        for df in (self.gl_d5_df, self.gl_h1_df, self.gl_m30_df, self.gl_s5_df):
            if df is not None and not df.empty and "time_jp" in df.columns:
                df["time_jp_dt"] = pd.to_datetime(df["time_jp"], format="%Y/%m/%d %H:%M:%S")

    def print_loaded_data_range(self):
        self.print_df_range("M5 all", self.gl_d5_df)
        self.print_df_range("H1 all", self.gl_h1_df)
        self.print_df_range("M30 all", self.gl_m30_df)
        self.print_df_range("S5 all", self.gl_s5_df)

    def save_loaded_data(self):
        paths = self.cache_file_paths()
        self.save_df(self.gl_h1_df, paths["h1"])
        self.save_df(self.gl_d5_df, paths["m5"])
        self.save_df(self.gl_m30_df, paths["m30"])
        self.save_df(self.gl_s5_df, paths["s5"])

    def cache_file_paths(self):
        cache_name = self.cache_base_name()
        folder_path = Path(tk.folder_path)
        return {
            "h1": folder_path / f"h1_{cache_name}.csv",
            "m5": folder_path / f"m5_{cache_name}.csv",
            "m30": folder_path / f"m30_{cache_name}.csv",
            "s5": folder_path / f"s5_{cache_name}.csv",
        }

    def cache_base_name(self):
        start_name = self.start_time.strftime("%Y%m%d%H%M%S")
        end_name = self.end_time.strftime("%Y%m%d%H%M%S")
        return f"{start_name}_{end_name}"

    @staticmethod
    def save_df(df, path):
        if df is None or df.empty:
            return
        df.drop(columns=["time_jp_dt"], errors="ignore").to_csv(path, index=False, encoding="utf-8")
        print("Saved loaded data:", path)

    def loaded_data_covers_required_range(self):
        fetch_from, fetch_to = self.required_data_range()
        return (
            self.df_covers_range(self.gl_h1_df, fetch_from, self.end_time)
            and self.df_covers_range(self.gl_d5_df, fetch_from, self.end_time)
            and self.df_covers_range(self.gl_s5_df, self.start_time + datetime.timedelta(seconds=5), fetch_to)
        )

    def save_result_data(self):
        path = Path(tk.folder_path) / f"result_{self.cache_base_name()}.csv"
        self.result_df.to_csv(path, index=False, encoding="utf-8")
        print("Saved inspection result:", path)


    @staticmethod
    def df_covers_range(df, start_time, end_time):
        if df is None or df.empty or "time_jp_dt" not in df.columns:
            return False
        return df["time_jp_dt"].min() <= start_time and df["time_jp_dt"].max() >= end_time

    @staticmethod
    def print_df_range(label, df):
        if df is None or df.empty:
            print(label + ":", "no data")
            return
        print(label + ":", df.iloc[0]["time_jp"], "-", df.iloc[-1]["time_jp"], len(df), "rows")

    def run(self):
        target_times = self.build_target_times()
        print("Inspection target count:", len(target_times))

        for i, target_time in enumerate(target_times):
            print("ーーーーーーーーーーーーーーーーーーーーーーーーーーーーーーーーーーーーーー")
            print("")
            print("Inspection target:", i + 1, "/", len(target_times), target_time)
            try:
                self.inspect_one_time(target_time)
            except Exception as e:
                print("Inspection error:", target_time, e)

        self.result_df = pd.DataFrame(self.results)
        print("Inspection result rows:", len(self.result_df))
        self.save_result_data()

    def build_target_times(self):
        target_times = []
        target_time = self.start_time
        end_time = min(self.end_time, datetime.datetime.now().replace(microsecond=0))
        while target_time <= end_time:
            target_times.append(target_time)
            target_time = target_time + datetime.timedelta(hours=1)
        return target_times

    def inspect_one_time(self, target_time):
        analysis_h1_df_r = self.slice_past_df_r(self.gl_h1_df, target_time, self.anaN)
        analysis_m30_df_r = self.slice_past_df_r(
            self.gl_m30_df if not self.gl_m30_df.empty else self.gl_h1_df,
            target_time,
            self.anaN * 2,
        )
        analysis_m5_df_r = self.slice_past_df_r(self.gl_d5_df, target_time, self.anaN * 12)
        inspection_s5_df = self.slice_inspection_s5_df(target_time)
        print(
            "  M5 df:",
            analysis_m5_df_r.iloc[0]["time_jp"] if len(analysis_m5_df_r) else None,
            "-",
            analysis_m5_df_r.iloc[-1]["time_jp"] if len(analysis_m5_df_r) else None,
            len(analysis_m5_df_r),
            "rows",
        )
        print(
            "  H1 df:",
            analysis_h1_df_r.iloc[0]["time_jp"] if len(analysis_h1_df_r) else None,
            "-",
            analysis_h1_df_r.iloc[-1]["time_jp"] if len(analysis_h1_df_r) else None,
            len(analysis_h1_df_r),
            "rows",
        )
        print(
            "  M30 df:",
            analysis_m30_df_r.iloc[0]["time_jp"] if len(analysis_m30_df_r) else None,
            "-",
            analysis_m30_df_r.iloc[-1]["time_jp"] if len(analysis_m30_df_r) else None,
            len(analysis_m30_df_r),
            "rows",
        )
        print(
            "  S5 inspection:",
            inspection_s5_df.iloc[0]["time_jp"] if len(inspection_s5_df) else None,
            "-",
            inspection_s5_df.iloc[-1]["time_jp"] if len(inspection_s5_df) else None,
            len(inspection_s5_df),
            "rows",
        )

        if len(analysis_h1_df_r) < self.anaN or len(inspection_s5_df) == 0:
            print("Skip by shortage:", target_time, len(analysis_h1_df_r), len(inspection_s5_df))
            return

        candle_analysis_class = ca.candleAnalysis(
            self.oa,
            target_time,
            m5_df_r=analysis_m5_df_r,
            h1_df_r=analysis_h1_df_r,
            m30_df_r=analysis_m30_df_r,
            s5_df_r=inspection_s5_df.sort_index(ascending=False).reset_index(drop=True),
            current_price=analysis_m5_df_r.iloc[0]["close"],
        )
        analysis_result = am.wrap_all_analysis(candle_analysis_class, None, "inspection")
        order_plans = self.extract_order_plans(analysis_result)
        for order_plan in order_plans:
            self.results.append(self.inspect_order_after(target_time, order_plan, inspection_s5_df))

        if any(order_plan.get("source") == "line" for order_plan in order_plans):
            return

        lines = self.extract_lines(analysis_result)
        for line_side, line in lines:
            order_plan = self.line_to_order_plan(target_time, line_side, line)
            self.results.append(self.inspect_order_after(target_time, order_plan, inspection_s5_df))

    @staticmethod
    def extract_order_plans(analysis_result):
        order_plans = []
        for order_class in getattr(analysis_result, "exe_order_classes", []):
            order_plan = getattr(order_class, "exe_order_plan", None)
            if order_plan:
                order_plans.append(order_plan)
        return order_plans

    def inspect_order_after(self, target_time, order_plan, inspection_s5_df):
        pair = gene.USD_JPY
        direction = int(order_plan["direction"])
        order_type = order_plan["type"]
        target_price = float(order_plan["target_price"])
        tp_price = float(order_plan["tp_price"])
        lc_price = float(order_plan["lc_price"])

        fill_index = self.find_order_fill_index(inspection_s5_df, target_price, direction, order_type)
        if fill_index is None:
            return self.order_result_row(
                target_time,
                order_plan,
                "not_filled",
                None,
                None,
                None,
                None,
                None,
                0,
                0,
                {},
            )

        after_fill_df = inspection_s5_df.iloc[fill_index:].reset_index(drop=True)
        fill_time = after_fill_df.iloc[0]["time_jp"]
        max_plus_pips, max_minus_pips = self.cal_order_max_plus_minus(after_fill_df, target_price, direction)
        first_reach_results = self.cal_first_reach_results(after_fill_df, target_price, direction)
        close_result, close_time, close_price, close_index = self.find_order_close(after_fill_df, tp_price, lc_price, direction)
        elapsed_s5 = self.cal_elapsed_s5_after_fill(after_fill_df, close_index)

        return self.order_result_row(
            target_time,
            order_plan,
            close_result,
            fill_time,
            close_time,
            close_price,
            elapsed_s5,
            elapsed_s5 * 5,
            max_plus_pips,
            max_minus_pips,
            first_reach_results,
        )

    @staticmethod
    def find_order_fill_index(df, target_price, direction, order_type):
        order_type = order_type.upper()
        for i, row in df.iterrows():
            if order_type == "STOP":
                if direction == 1 and row["high"] >= target_price:
                    return i
                if direction == -1 and row["low"] <= target_price:
                    return i
            elif order_type == "LIMIT":
                if direction == 1 and row["low"] <= target_price:
                    return i
                if direction == -1 and row["high"] >= target_price:
                    return i
            elif order_type == "MARKET":
                return i
        return None

    @staticmethod
    def find_order_close(df, tp_price, lc_price, direction):
        for i, row in df.iterrows():
            if direction == 1:
                tp_hit = row["high"] >= tp_price
                lc_hit = row["low"] <= lc_price
            else:
                tp_hit = row["low"] <= tp_price
                lc_hit = row["high"] >= lc_price

            if tp_hit and lc_hit:
                return "both_tp_lc_same_candle", row["time_jp"], None, i
            if tp_hit:
                return "tp", row["time_jp"], tp_price, i
            if lc_hit:
                return "lc", row["time_jp"], lc_price, i
        return "not_closed", None, None, None

    @staticmethod
    def cal_elapsed_s5_after_fill(after_fill_df, close_index):
        if after_fill_df.empty:
            return None
        if close_index is None:
            return max(len(after_fill_df) - 1, 0)
        return close_index

    @staticmethod
    def cal_order_max_plus_minus(df, target_price, direction):
        pair = gene.USD_JPY
        if df.empty:
            return 0, 0
        if direction == 1:
            max_plus = pair.price_to_pips(df["high"].max() - target_price)
            max_minus = pair.price_to_pips(df["low"].min() - target_price)
        else:
            max_plus = pair.price_to_pips(target_price - df["low"].min())
            max_minus = pair.price_to_pips(target_price - df["high"].max())
        return max_plus, max_minus

    @staticmethod
    def order_result_row(
        target_time,
        order_plan,
        result,
        fill_time,
        close_time,
        close_price,
        elapsed_s5,
        elapsed_seconds,
        max_plus_pips,
        max_minus_pips,
        first_reach_results=None,
    ):
        res = Inspection.cal_order_result_pips(order_plan, close_price)
        first_reach_results = first_reach_results or {}
        return {
            "result_type": "order",
            "target_time": target_time,
            "name": order_plan.get("name"),
            "res": res,
            "order_type": order_plan.get("type"),
            "direction": order_plan.get("direction"),
            "target_price": order_plan.get("target_price"),
            "tp_price": order_plan.get("tp_price"),
            "lc_price": order_plan.get("lc_price"),
            "units": order_plan.get("units"),
            "priority": order_plan.get("priority"),
            "order_result": result,
            "fill_time": fill_time,
            "close_time": close_time,
            "close_price": close_price,
            "elapsed_s5": elapsed_s5,
            "elapsed_seconds": elapsed_seconds,
            "max_plus_pips": max_plus_pips,
            "max_minus_pips": max_minus_pips,
            **first_reach_results,
            "source": order_plan.get("source"),
            "line_side": order_plan.get("line_side"),
            "line_price": order_plan.get("line_price"),
            "line_total_strength": order_plan.get("line_total_strength"),
            "line_count": order_plan.get("line_count"),
            "line_ave_strength": order_plan.get("line_ave_strength"),
            "line_is_flipped": order_plan.get("line_is_flipped"),
            "line_oldest_time": order_plan.get("line_oldest_time"),
            "for_api_json": order_plan.get("for_api_json"),
            "memo": order_plan.get("memo"),
        }

    @staticmethod
    def cal_order_result_pips(order_plan, close_price):
        if close_price is None:
            return None

        pair = gene.USD_JPY
        direction = int(order_plan["direction"])
        target_price = float(order_plan["target_price"])
        return pair.price_to_pips((float(close_price) - target_price) * direction)

    def extract_lines(self, analysis_result):
        turn = getattr(analysis_result, "turn_analysis_instance", None)
        line_class = getattr(turn, "line_class_h1_l", None)
        if line_class is None:
            line_class = ti.LineStrengthCal(analysis_result.ca, "h1", 65)

        lines = []
        for line in line_class.upper_lines:
            lines.append(("upper", line))
        for line in line_class.lower_lines:
            lines.append(("lower", line))
        return lines

    def line_to_order_plan(self, target_time, line_side, line):
        pair = gene.USD_JPY
        line_price = line["median_price"]
        direction = -1 if line_side == "upper" else 1
        spread_pips = 0.8
        lc_pips = 15
        rr = 1.65
        tp_pips = round(rr * (lc_pips + spread_pips) + spread_pips, 1)
        tp_price = pair.round_price(line_price + pair.pips_to_price(tp_pips * direction))
        lc_price = pair.round_price(line_price - pair.pips_to_price(lc_pips * direction))
        name = "line_" + line_side + "_" + target_time.strftime("%Y%m%d%H%M%S")

        return {
            "name": name,
            "type": "LIMIT",
            "direction": direction,
            "target_price": pair.round_price(line_price),
            "tp_price": tp_price,
            "lc_price": lc_price,
            "tp_range": pair.pips_to_price(tp_pips),
            "lc_range": pair.pips_to_price(lc_pips),
            "units": 0,
            "priority": line.get("total_strength"),
            "for_api_json": None,
            "memo": "virtual line order",
            "source": "line",
            "line_side": line_side,
            "line_price": pair.round_price(line_price),
            "line_total_strength": line.get("total_strength"),
            "line_count": line.get("count"),
            "line_ave_strength": line.get("ave_strength"),
            "line_is_flipped": line.get("is_flipped_line"),
            "line_oldest_time": line.get("oldest_time"),
        }

    @staticmethod
    def cal_first_reach_results(df, target_price, direction):
        thresholds = (5, 10, 15, 20, 25, 30)
        results = {}
        for pips in thresholds:
            side, reach_time, elapsed_s5 = Inspection.find_first_reach(df, target_price, direction, pips)
            results[f"first_{pips}pips_side"] = side
            results[f"first_{pips}pips_time"] = reach_time
            results[f"first_{pips}pips_elapsed_s5"] = elapsed_s5
        return results

    @staticmethod
    def find_first_reach(df, target_price, direction, threshold_pips):
        pair = gene.USD_JPY
        threshold_price = pair.pips_to_price(threshold_pips)
        for i, row in df.iterrows():
            if direction == 1:
                plus_hit = row["high"] >= target_price + threshold_price
                minus_hit = row["low"] <= target_price - threshold_price
            else:
                plus_hit = row["low"] <= target_price - threshold_price
                minus_hit = row["high"] >= target_price + threshold_price

            if plus_hit and minus_hit:
                return "both", row["time_jp"], i
            if plus_hit:
                return "plus", row["time_jp"], i
            if minus_hit:
                return "minus", row["time_jp"], i
        return "none", None, None

    def required_data_range(self):
        data_from = self.start_time - datetime.timedelta(hours=self.anaN)
        data_to_by_inspection = self.end_time + datetime.timedelta(seconds=self.insN * 5)
        now = datetime.datetime.now().replace(microsecond=0)
        data_to = min(data_to_by_inspection, now)
        return data_from, data_to

    @staticmethod
    def slice_past_df_r(df, target_time, row_count=None):
        sliced_df = df[df["time_jp_dt"] <= target_time].sort_values("time_jp_dt", ascending=False)
        if row_count is not None:
            sliced_df = sliced_df.head(row_count)
        return sliced_df.reset_index(drop=True)

    def slice_inspection_s5_df(self, target_time):
        start_time = target_time + datetime.timedelta(seconds=5)
        inspection_df = self.gl_s5_df[self.gl_s5_df["time_jp_dt"] >= start_time].sort_values("time_jp_dt")
        return inspection_df.head(self.insN).reset_index(drop=True)

    @staticmethod
    def cal_oanda_count_and_loop(need_rows):
        if need_rows > 5000:
            return 5000, math.ceil(need_rows / 5000)
        return need_rows, 1
