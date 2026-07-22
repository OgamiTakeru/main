import datetime
import math
from pathlib import Path

import numpy as np
import pandas as pd

import classCandleAnalysis as ca
import classOanda
import fAnalysis_order_Main as am
import fGeneric as gene
import fLineAnalysis as ti
import tokens as tk
import send_notice as notice


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
        target_interval_minutes=60,
        pair="USD_JPY",
    ):
        self.oa = classOanda.Oanda(tk.accountIDl, tk.access_tokenl, "live")
        self.pair = pair
        self.p = gene.currency_pair(self.pair)
        self.gl_exist_data = is_exist_data
        self.start_time = start_time
        self.end_time = end_time
        self.gl_jp_time = end_time
        self.gl_m5_count = m5_count
        self.gl_m5_loop = loop
        self.memo = memo
        self.anaN = anaN
        self.insN = insN
        self.target_interval_minutes = target_interval_minutes
        self.spread_pips = 0.8
        self.half_spread_pips = self.spread_pips / 2

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
        self.process_start_time = datetime.datetime.now()
        self.progress_notice_months = 2
        self.next_progress_notice_time = self.add_months(
            self.start_time,
            self.progress_notice_months,
        )

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
        notice.line_send(
            "検証データをOANDAから取得開始",
            self.pair,
            str(fetch_from),
            "->",
            str(fetch_to),
        )

        m5_rows = math.ceil(total_seconds / (5 * 60)) + 5
        m5_count, m5_loop = self.cal_oanda_count_and_loop(m5_rows)
        params = {"granularity": "M5", "count": m5_count, "to": end_time_iso}
        data_response = self.oa.InstrumentsCandles_multi_exe(self.pair, params, m5_loop)
        self.gl_d5_df = data_response["data"]
        self.gl_d5_df_r = self.gl_d5_df.sort_index(ascending=False)
        notice.line_send("検証データ取得", self.pair, "M5", len(self.gl_d5_df), "rows")

        h1_fetch_from = self.required_h1_data_from()
        h1_total_seconds = max((fetch_to - h1_fetch_from).total_seconds(), 0)
        h1_rows = math.ceil(h1_total_seconds / (60 * 60)) + 5
        h1_count, h1_loop = self.cal_oanda_count_and_loop(h1_rows)
        params = {"granularity": "H1", "count": h1_count, "to": end_time_iso}
        data_response = self.oa.InstrumentsCandles_multi_exe(self.pair, params, h1_loop)
        self.gl_h1_df = data_response["data"]
        self.gl_h1_df_r = self.gl_h1_df.sort_index(ascending=False)
        notice.line_send("検証データ取得", self.pair, "H1", len(self.gl_h1_df), "rows")

        m30_rows = math.ceil(total_seconds / (30 * 60)) + 5
        m30_count, m30_loop = self.cal_oanda_count_and_loop(m30_rows)
        params = {"granularity": "M30", "count": m30_count, "to": end_time_iso}
        data_response = self.oa.InstrumentsCandles_multi_exe(self.pair, params, m30_loop)
        self.gl_m30_df = data_response["data"]
        self.gl_m30_df_r = self.gl_m30_df.sort_index(ascending=False)
        notice.line_send("検証データ取得", self.pair, "M30", len(self.gl_m30_df), "rows")

        s5_rows = math.ceil(total_seconds / 5) + 5
        s5_count, s5_loop = self.cal_oanda_count_and_loop(s5_rows)
        params = {"granularity": "S5", "count": s5_count, "to": end_time_iso}
        data_response = self.oa.InstrumentsCandles_multi_exe(self.pair, params, s5_loop)
        self.gl_s5_df = data_response["data"]
        notice.line_send("検証データ取得", self.pair, "S5", len(self.gl_s5_df), "rows")
        notice.line_send("検証データOANDA取得完了", self.pair)

    def normalize_time_columns(self):
        for df in (self.gl_d5_df, self.gl_h1_df, self.gl_m30_df, self.gl_s5_df):
            if df is not None and not df.empty and "time_jp" in df.columns:
                df["time_jp_dt"] = pd.to_datetime(df["time_jp"], format="%Y/%m/%d %H:%M:%S")
                df.sort_values("time_jp_dt", inplace=True)
                df.reset_index(drop=True, inplace=True)

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
        return f"{self.pair}_{start_name}_{end_name}"

    @staticmethod
    def save_df(df, path):
        if df is None or df.empty:
            return
        df.drop(columns=["time_jp_dt"], errors="ignore").to_csv(path, index=False, encoding="utf-8")
        print("Saved loaded data:", path)

    def loaded_data_covers_required_range(self):
        fetch_from, fetch_to = self.required_data_range()
        s5_cache_tolerance = datetime.timedelta(days=1)
        return (
            self.df_covers_range(self.gl_h1_df, self.required_h1_data_from(), self.end_time)
            and self.df_covers_range(self.gl_d5_df, fetch_from, self.end_time)
            and self.df_covers_range(
                self.gl_s5_df,
                self.start_time,
                fetch_to,
                s5_cache_tolerance,
            )
        )

    def save_result_data(self):
        path = Path(tk.folder_path) / f"result_{self.cache_base_name()}.csv"
        self.result_df.to_csv(path, index=False, encoding="utf-8")
        print("Saved inspection result:", path)


    @staticmethod
    def df_covers_range(df, start_time, end_time, tolerance=None):
        if df is None or df.empty or "time_jp_dt" not in df.columns:
            return False
        if tolerance is None:
            tolerance = datetime.timedelta(seconds=5)
        return (
            df["time_jp_dt"].min() <= start_time + tolerance
            and df["time_jp_dt"].max() + tolerance >= end_time
        )

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
            self.send_progress_notice_if_needed(i + 1, len(target_times), target_time)

        self.result_df = pd.DataFrame(self.results)
        print("Inspection result rows:", len(self.result_df))
        self.save_result_data()
        self.print_tp_last_touch_winrate_summary()
        self.print_elapsed_time()

    def print_tp_last_touch_winrate_summary(self):
        required = {
            "tp_last_touch_elapsed_bin",
            "order_result",
            "actual_res",
        }
        if self.result_df.empty or not required.issubset(self.result_df.columns):
            return

        rows = self.result_df.copy()
        if "result_type" in rows.columns:
            rows = rows[rows["result_type"] == "order"]
        rows = rows[rows["order_result"] != "not_filled"]
        if rows.empty:
            return

        bins = [
            "0-30m",
            "31-60m",
            "61-180m",
            "181-360m",
            "361-720m",
            "721-1440m",
            "1441-2880m",
            "2881-4320m",
            "4321-7200m",
            "7201-10080m",
            "10081-15000m",
            "15001m+",
            "no_touch_in_history",
        ]
        rows["tp_last_touch_elapsed_bin"] = pd.Categorical(
            rows["tp_last_touch_elapsed_bin"].fillna("no_touch_in_history"),
            categories=bins,
            ordered=True,
        )
        rows["actual_res"] = pd.to_numeric(rows["actual_res"], errors="coerce")
        rows["tp_touch_win"] = rows["actual_res"] > 0
        summary = rows.groupby(
            "tp_last_touch_elapsed_bin",
            observed=True,
        ).agg(
            trades=("tp_touch_win", "size"),
            wins=("tp_touch_win", "sum"),
            win_rate=("tp_touch_win", "mean"),
            average_pips=("actual_res", "mean"),
        )
        summary["win_rate"] = (summary["win_rate"] * 100).round(1)
        summary["average_pips"] = summary["average_pips"].round(2)
        print("TP last-touch elapsed / win-rate summary")
        print(summary.to_string())

        parts = []
        for elapsed_bin, row in summary.iterrows():
            parts.append(
                str(elapsed_bin)
                + " n="
                + str(int(row["trades"]))
                + " win="
                + str(row["win_rate"])
                + "% avg="
                + str(row["average_pips"])
                + "p"
            )
        notice.line_send(
            self.pair + " inspection TP last-touch win rate: " + " / ".join(parts)
        )

    def print_elapsed_time(self):
        elapsed_seconds = (datetime.datetime.now() - self.process_start_time).total_seconds()
        elapsed_minutes = elapsed_seconds / 60
        print("Inspection elapsed seconds:", round(elapsed_seconds, 1))
        print("Inspection elapsed minutes:", round(elapsed_minutes, 2))
        notice.line_send(
            "検証 終了しました",
            self.pair,
            str(self.start_time),
            "->",
            str(self.end_time),
            str(len(self.result_df)) + "件",
            str(round(elapsed_minutes, 2)) + "分",
        )

    @staticmethod
    def add_months(base_time, months):
        month_index = base_time.month - 1 + months
        year = base_time.year + month_index // 12
        month = month_index % 12 + 1
        day = min(base_time.day, Inspection.last_day_of_month(year, month))
        return base_time.replace(year=year, month=month, day=day)

    @staticmethod
    def last_day_of_month(year, month):
        if month == 12:
            next_month = datetime.datetime(year + 1, 1, 1)
        else:
            next_month = datetime.datetime(year, month + 1, 1)
        return (next_month - datetime.timedelta(days=1)).day

    def send_progress_notice_if_needed(self, completed_count, total_count, target_time):
        while (
            self.next_progress_notice_time is not None
            and target_time >= self.next_progress_notice_time
        ):
            elapsed_minutes = (
                datetime.datetime.now() - self.process_start_time
            ).total_seconds() / 60
            message = (
                self.pair
                + " 検証進捗 "
                + str(self.progress_notice_months)
                + "ヶ月区切り完了 "
                + str(self.next_progress_notice_time)
                + " / "
                + str(completed_count)
                + "/"
                + str(total_count)
                + "件 "
                + str(round(elapsed_minutes, 2))
                + "分"
            )
            print(message)
            notice.line_send(message)
            self.next_progress_notice_time = self.add_months(
                self.next_progress_notice_time,
                self.progress_notice_months,
            )

    def build_target_times(self):
        target_times = []
        target_time = self.start_time
        end_time = min(self.end_time, datetime.datetime.now().replace(microsecond=0))
        while target_time <= end_time:
            target_times.append(target_time)
            target_time = target_time + datetime.timedelta(
                minutes=self.target_interval_minutes
            )
        return target_times

    def inspect_one_time(self, target_time):
        analysis_h1_df_r = self.slice_past_df_r(
            self.gl_h1_df,
            target_time,
            250,
        )
        analysis_m30_df_r = self.slice_past_df_r(
            self.gl_m30_df if not self.gl_m30_df.empty else self.gl_h1_df,
            target_time,
            (self.anaN * 2) + 1,
        )
        analysis_m5_df_r = self.slice_past_df_r(
            self.gl_d5_df,
            target_time,
            (self.anaN * 12) + 1,
        )
        self.validate_analysis_boundary(
            analysis_m5_df_r,
            target_time,
            datetime.timedelta(minutes=5),
            "M5",
        )
        self.validate_analysis_boundary(
            analysis_h1_df_r,
            target_time,
            datetime.timedelta(hours=1),
            "H1",
        )
        self.validate_analysis_boundary(
            analysis_m30_df_r,
            target_time,
            (
                datetime.timedelta(minutes=30)
                if not self.gl_m30_df.empty
                else datetime.timedelta(hours=1)
            ),
            "M30",
        )
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
            self.pair,
            target_time_jp=target_time,
            m5_df_r=analysis_m5_df_r,
            h1_df_r=analysis_h1_df_r,
            m30_df_r=analysis_m30_df_r,
            s5_df_r=None,
            current_price=self.current_price_at(target_time, analysis_m5_df_r),
        )
        analysis_result = am.wrap_all_analysis(candle_analysis_class, None, "inspection")
        order_plans = self.extract_order_plans(analysis_result)
        for order_plan in order_plans:
            self.results.append(self.inspect_order_after(target_time, order_plan, inspection_s5_df))

        if any(order_plan.get("source") == "line" for order_plan in order_plans):
            return

        lines = self.extract_lines(analysis_result)
        rsi_info = self.build_rsi_info(analysis_m5_df_r, analysis_h1_df_r)
        for line_side, line in lines:
            if not ti.MainAnalysis.is_h1_line_limit_order_target(line_side, line):
                continue
            order_plan = self.line_to_order_plan(target_time, line_side, line, rsi_info)
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
        direction = int(order_plan["direction"])
        order_type = order_plan["type"]
        target_price = float(order_plan["target_price"])
        tp_price = float(order_plan["tp_price"])
        lc_price = float(order_plan["lc_price"])

        fill_search_df = inspection_s5_df
        order_timeout_min = order_plan.get("order_timeout_min")
        if order_type.upper() != "MARKET" and order_timeout_min is not None:
            fill_deadline = pd.to_datetime(target_time) + datetime.timedelta(
                minutes=float(order_timeout_min)
            )
            fill_times = pd.to_datetime(
                fill_search_df["time_jp"],
                format="%Y/%m/%d %H:%M:%S",
            )
            fill_search_df = fill_search_df[fill_times <= fill_deadline]

        mid_fill_index = self.find_order_fill_index(fill_search_df, target_price, direction, order_type)
        fill_index = self.find_order_fill_index_actual(fill_search_df, target_price, direction, order_type)
        if fill_index is None:
            mid_context = self.inspect_mid_context(
                order_plan,
                inspection_s5_df,
                mid_fill_index,
                tp_price,
                lc_price,
                direction,
            )
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
                {},
                {
                    **self.spread_context(order_plan, None, None),
                    **mid_context,
                    "spread_block_reason": (
                        "mid_filled_actual_not_filled"
                        if mid_fill_index is not None
                        else "same_not_filled"
                    ),
                },
            )

        after_fill_df = inspection_s5_df.iloc[fill_index:].reset_index(drop=True)
        fill_time = after_fill_df.iloc[0]["time_jp"]
        entry_price_actual = self.actual_entry_price(order_type, target_price, direction)
        max_plus_pips, max_minus_pips = self.cal_order_max_plus_minus_actual(
            after_fill_df,
            entry_price_actual,
            direction,
        )
        first_reach_results = self.cal_first_reach_results_actual(
            after_fill_df,
            entry_price_actual,
            direction,
        )
        close_result, close_time, close_price, close_index = self.find_order_close_actual(
            after_fill_df,
            tp_price,
            lc_price,
            direction,
        )
        elapsed_s5 = self.cal_elapsed_s5_after_fill(after_fill_df, close_index)
        force_results = self.cal_force_close_results_multi(
            after_fill_df,
            order_plan,
            tp_price,
            lc_price,
            direction,
            entry_price_actual=entry_price_actual,
            actual=True,
        )
        mid_context = self.inspect_mid_context(
            order_plan,
            inspection_s5_df,
            mid_fill_index,
            tp_price,
            lc_price,
            direction,
        )
        close_price_actual = self.actual_close_price(close_result, close_price, direction)

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
            force_results,
            {
                **self.spread_context(order_plan, entry_price_actual, close_price_actual),
                **mid_context,
                "spread_block_reason": self.spread_block_reason(
                    close_result,
                    mid_context.get("mid_order_result"),
                ),
            },
        )

    def spread_context(self, order_plan, entry_price_actual, close_price_actual):
        direction = int(order_plan["direction"])
        target_price = float(order_plan["target_price"])
        tp_price = float(order_plan["tp_price"])
        lc_price = float(order_plan["lc_price"])
        return {
            "spread_pips": self.spread_pips,
            "half_spread_pips": self.half_spread_pips,
            "entry_price_actual": entry_price_actual,
            "tp_price_actual": self.actual_close_price("tp", tp_price, direction),
            "lc_price_actual": self.actual_close_price("lc", lc_price, direction),
            "close_price_actual": close_price_actual,
            "target_price_mid": target_price,
            "tp_price_mid": tp_price,
            "lc_price_mid": lc_price,
        }

    def inspect_mid_context(self, order_plan, inspection_s5_df, mid_fill_index, tp_price, lc_price, direction):
        if mid_fill_index is None:
            return {
                "mid_order_result": "not_filled",
                "mid_res": None,
                "mid_fill_time": None,
                "mid_close_time": None,
                "mid_close_price": None,
            }

        mid_after_fill_df = inspection_s5_df.iloc[mid_fill_index:].reset_index(drop=True)
        mid_close_result, mid_close_time, mid_close_price, _ = self.find_order_close(
            mid_after_fill_df,
            tp_price,
            lc_price,
            direction,
        )
        return {
            "mid_order_result": mid_close_result,
            "mid_res": self.cal_order_result_pips(order_plan, mid_close_price),
            "mid_fill_time": mid_after_fill_df.iloc[0]["time_jp"],
            "mid_close_time": mid_close_time,
            "mid_close_price": mid_close_price,
        }

    @staticmethod
    def spread_block_reason(actual_result, mid_result):
        if mid_result == "not_filled":
            return "same_not_filled" if actual_result == "not_filled" else "actual_filled_mid_not_filled"
        if actual_result == "not_filled":
            return "mid_filled_actual_not_filled"
        if actual_result == mid_result:
            return "same"
        return "mid_" + str(mid_result) + "_actual_" + str(actual_result)

    @staticmethod
    def find_order_fill_index(df, target_price, direction, order_type):
        order_type = order_type.upper()
        if df.empty:
            return None
        if order_type == "MARKET":
            return 0
        if order_type == "STOP":
            hit = (
                df["high"].to_numpy() >= target_price
                if direction == 1
                else df["low"].to_numpy() <= target_price
            )
        elif order_type == "LIMIT":
            hit = (
                df["low"].to_numpy() <= target_price
                if direction == 1
                else df["high"].to_numpy() >= target_price
            )
        else:
            return None
        indexes = np.flatnonzero(hit)
        return int(indexes[0]) if indexes.size else None

    def find_order_fill_index_actual(self, df, target_price, direction, order_type):
        order_type = order_type.upper()
        if df.empty:
            return None
        if order_type == "MARKET":
            return 0

        half = self.p.pips_to_price(self.half_spread_pips)
        if order_type == "STOP":
            hit = (
                df["high"].to_numpy() >= target_price - half
                if direction == 1
                else df["low"].to_numpy() <= target_price + half
            )
        elif order_type == "LIMIT":
            hit = (
                df["low"].to_numpy() <= target_price - half
                if direction == 1
                else df["high"].to_numpy() >= target_price + half
            )
        else:
            return None
        indexes = np.flatnonzero(hit)
        return int(indexes[0]) if indexes.size else None

    @staticmethod
    def find_order_close(df, tp_price, lc_price, direction):
        if df.empty:
            return "not_closed", None, None, None
        high = df["high"].to_numpy()
        low = df["low"].to_numpy()
        if direction == 1:
            tp_hit = high >= tp_price
            lc_hit = low <= lc_price
        else:
            tp_hit = low <= tp_price
            lc_hit = high >= lc_price

        indexes = np.flatnonzero(tp_hit | lc_hit)
        if indexes.size:
            i = int(indexes[0])
            close_time = df.iloc[i]["time_jp"]
            if tp_hit[i] and lc_hit[i]:
                return "both_tp_lc_same_candle", close_time, None, i
            if tp_hit[i]:
                return "tp", close_time, tp_price, i
            return "lc", close_time, lc_price, i
        return "not_closed", None, None, None

    def find_order_close_actual(self, df, tp_price, lc_price, direction):
        if df.empty:
            return "not_closed", None, None, None
        half = self.p.pips_to_price(self.half_spread_pips)
        high = df["high"].to_numpy()
        low = df["low"].to_numpy()
        if direction == 1:
            tp_hit = high >= tp_price + half
            lc_hit = low <= lc_price + half
        else:
            tp_hit = low <= tp_price - half
            lc_hit = high >= lc_price - half

        indexes = np.flatnonzero(tp_hit | lc_hit)
        if indexes.size:
            i = int(indexes[0])
            close_time = df.iloc[i]["time_jp"]
            if tp_hit[i] and lc_hit[i]:
                return "both_tp_lc_same_candle", close_time, None, i
            if tp_hit[i]:
                return "tp", close_time, tp_price, i
            return "lc", close_time, lc_price, i
        return "not_closed", None, None, None

    @staticmethod
    def cal_elapsed_s5_after_fill(after_fill_df, close_index):
        if after_fill_df.empty:
            return None
        if close_index is None:
            return max(len(after_fill_df) - 1, 0)
        return close_index

    def cal_order_max_plus_minus(self, df, target_price, direction):
        pair = self.p
        if df.empty:
            return 0, 0
        if direction == 1:
            max_plus = pair.price_to_pips(df["high"].max() - target_price)
            max_minus = pair.price_to_pips(df["low"].min() - target_price)
        else:
            max_plus = pair.price_to_pips(target_price - df["low"].min())
            max_minus = pair.price_to_pips(target_price - df["high"].max())
        return max_plus, max_minus

    def actual_entry_price(self, order_type, target_price, direction):
        if str(order_type).upper() == "MARKET":
            return target_price + self.p.pips_to_price(self.half_spread_pips * direction)
        return target_price

    def actual_close_price(self, close_result, close_price, direction):
        if close_price is None:
            return None
        if close_result in ("tp", "lc"):
            return close_price
        return float(close_price) - self.p.pips_to_price(self.half_spread_pips * direction)

    def cal_order_result_pips_actual(self, entry_price_actual, close_price_actual, direction):
        if entry_price_actual is None or close_price_actual is None:
            return None
        return self.p.price_to_pips((float(close_price_actual) - float(entry_price_actual)) * direction)

    def cal_order_max_plus_minus_actual(self, df, entry_price_actual, direction):
        if df.empty or entry_price_actual is None:
            return 0, 0
        half = self.p.pips_to_price(self.half_spread_pips)
        if direction == 1:
            bid_high = df["high"].max() - half
            bid_low = df["low"].min() - half
            max_plus = self.p.price_to_pips(bid_high - entry_price_actual)
            max_minus = self.p.price_to_pips(bid_low - entry_price_actual)
        else:
            ask_low = df["low"].min() + half
            ask_high = df["high"].max() + half
            max_plus = self.p.price_to_pips(entry_price_actual - ask_low)
            max_minus = self.p.price_to_pips(entry_price_actual - ask_high)
        return max_plus, max_minus

    def cal_force_close_results_multi(
        self,
        after_fill_df,
        order_plan,
        tp_price,
        lc_price,
        direction,
        entry_price_actual=None,
        actual=False,
    ):
        results = {}
        for minutes in (15, 30, 45, 60):
            results.update(self.cal_force_close_results(
                after_fill_df,
                order_plan,
                tp_price,
                lc_price,
                direction,
                limit_seconds=minutes * 60,
                prefix=f"force{minutes}",
                entry_price_actual=entry_price_actual,
                actual=actual,
            ))
        return results

    def cal_force_close_results(
        self,
        after_fill_df,
        order_plan,
        tp_price,
        lc_price,
        direction,
        limit_seconds,
        prefix,
        entry_price_actual=None,
        actual=False,
    ):
        if after_fill_df.empty:
            return self.empty_force_close_results(prefix)

        limit_s5 = int(limit_seconds / 5)
        end_index = min(limit_s5, len(after_fill_df) - 1)
        limited_df = after_fill_df.iloc[:end_index + 1].reset_index(drop=True)
        if actual:
            close_result, close_time, close_price, close_index = self.find_order_close_actual(
                limited_df,
                tp_price,
                lc_price,
                direction,
            )
            max_plus_pips, max_minus_pips = self.cal_order_max_plus_minus_actual(
                limited_df,
                entry_price_actual,
                direction,
            )
        else:
            close_result, close_time, close_price, close_index = self.find_order_close(
                limited_df,
                tp_price,
                lc_price,
                direction,
            )
            max_plus_pips, max_minus_pips = self.cal_order_max_plus_minus(
                limited_df,
                float(order_plan["target_price"]),
                direction,
            )

        if close_result in ("tp", "lc"):
            force_result = close_result
            force_close_time = close_time
            force_close_price = close_price
            force_elapsed_s5 = close_index
        elif close_result == "both_tp_lc_same_candle":
            force_result = close_result
            force_close_time = close_time
            force_close_price = None
            force_elapsed_s5 = close_index
        else:
            force_result = "time_close"
            force_close_time = limited_df.iloc[end_index]["time_jp"]
            force_close_price = float(limited_df.iloc[end_index]["close"])
            force_elapsed_s5 = end_index
        force_close_price_actual = (
            self.actual_close_price(force_result, force_close_price, direction)
            if actual
            else force_close_price
        )
        force_res_pips = (
            self.cal_order_result_pips_actual(entry_price_actual, force_close_price_actual, direction)
            if actual
            else self.cal_order_result_pips(order_plan, force_close_price)
        )

        return {
            prefix + "_result": force_result,
            prefix + "_close_time": force_close_time,
            prefix + "_close_price": force_close_price,
            prefix + "_close_price_actual": force_close_price_actual,
            prefix + "_res_pips": force_res_pips,
            prefix + "_elapsed_s5": force_elapsed_s5,
            prefix + "_elapsed_seconds": None if force_elapsed_s5 is None else force_elapsed_s5 * 5,
            prefix + "_max_plus_pips": max_plus_pips,
            prefix + "_max_minus_pips": max_minus_pips,
            prefix + "_is_time_close": force_result == "time_close",
            prefix + "_is_plus": (
                None
                if force_res_pips is None
                else force_res_pips > 0
            ),
        }

    @staticmethod
    def empty_force_close_results(prefix):
        return {
            prefix + "_result": None,
            prefix + "_close_time": None,
            prefix + "_close_price": None,
            prefix + "_close_price_actual": None,
            prefix + "_res_pips": None,
            prefix + "_elapsed_s5": None,
            prefix + "_elapsed_seconds": None,
            prefix + "_max_plus_pips": None,
            prefix + "_max_minus_pips": None,
            prefix + "_is_time_close": None,
            prefix + "_is_plus": None,
        }

    def order_result_row(
        self,
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
        force_results=None,
        extra_results=None,
    ):
        extra_results = extra_results or {}
        entry_price_actual = extra_results.get("entry_price_actual")
        close_price_actual = extra_results.get("close_price_actual")
        res = self.cal_order_result_pips_actual(
            entry_price_actual,
            close_price_actual,
            int(order_plan["direction"]),
        )
        if res is None:
            res = self.cal_order_result_pips(order_plan, close_price)
        first_reach_results = first_reach_results or {}
        if force_results is None:
            force_results = {}
            for minutes in (15, 30, 45, 60):
                force_results.update(self.empty_force_close_results(f"force{minutes}"))
        tp_range = order_plan.get("tp_range")
        lc_range = order_plan.get("lc_range")
        tp_pips = self.p.price_to_pips(tp_range) if tp_range is not None else None
        lc_pips = self.p.price_to_pips(lc_range) if lc_range is not None else None
        rr = tp_pips / lc_pips if tp_pips is not None and lc_pips not in (None, 0) else None
        return {
            "result_type": "order",
            "target_time": target_time,
            "name": order_plan.get("name"),
            "pair": order_plan.get("pair", self.pair),
            "res": res,
            "actual_res": res,
            "order_type": order_plan.get("type"),
            "direction": order_plan.get("direction"),
            "target_price": order_plan.get("target_price"),
            "decision_price": order_plan.get("decision_price"),
            "target_distance_pips": order_plan.get("target_distance_pips"),
            "order_timeout_min": order_plan.get("order_timeout_min"),
            "tp_price": order_plan.get("tp_price"),
            "lc_price": order_plan.get("lc_price"),
            "tp_pips": tp_pips,
            "lc_pips": lc_pips,
            "rr": rr,
            "units": order_plan.get("units"),
            "priority": order_plan.get("priority"),
            "order_result": result,
            "actual_order_result": result,
            "fill_time": fill_time,
            "close_time": close_time,
            "close_price": close_price,
            "elapsed_s5": elapsed_s5,
            "elapsed_seconds": elapsed_seconds,
            "max_plus_pips": max_plus_pips,
            "max_minus_pips": max_minus_pips,
            **first_reach_results,
            **force_results,
            **extra_results,
            "source": order_plan.get("source"),
            "line_order_mode": order_plan.get("line_order_mode"),
            "line_timeframe": order_plan.get("line_timeframe"),
            "line_entry_type": order_plan.get("line_entry_type"),
            "line_entry_offset_pips": order_plan.get("line_entry_offset_pips"),
            "line_target_price": order_plan.get("line_target_price"),
            "line_distance_pips": order_plan.get("line_distance_pips"),
            "latest_peak_dir": order_plan.get("latest_peak_dir"),
            "latest_peak_count": order_plan.get("latest_peak_count"),
            "latest_peak_gap": order_plan.get("latest_peak_gap"),
            "latest_peak_time": order_plan.get("latest_peak_time"),
            "latest_peak_strength": order_plan.get("latest_peak_strength"),
            "latest_peak_price": order_plan.get("latest_peak_price"),
            "latest_peak_rsi": order_plan.get("latest_peak_rsi"),
            "previous_peak_dir": order_plan.get("previous_peak_dir"),
            "previous_peak_count": order_plan.get("previous_peak_count"),
            "previous_peak_gap": order_plan.get("previous_peak_gap"),
            "previous_peak_time": order_plan.get("previous_peak_time"),
            "previous_peak_strength": order_plan.get("previous_peak_strength"),
            "previous_peak_price": order_plan.get("previous_peak_price"),
            "previous_peak_rsi": order_plan.get("previous_peak_rsi"),
            "m5_previous_peak_line_side": order_plan.get("m5_previous_peak_line_side"),
            "m5_previous_peak_line_price": order_plan.get("m5_previous_peak_line_price"),
            "m5_previous_peak_line_distance_pips": order_plan.get("m5_previous_peak_line_distance_pips"),
            "m5_previous_peak_line_total_strength": order_plan.get("m5_previous_peak_line_total_strength"),
            "m5_previous_peak_line_count": order_plan.get("m5_previous_peak_line_count"),
            "m5_previous_peak_line_core_total_strength": order_plan.get("m5_previous_peak_line_core_total_strength"),
            "m5_previous_peak_line_is_flipped": order_plan.get("m5_previous_peak_line_is_flipped"),
            "m5_previous_peak_line_contains_peak": order_plan.get("m5_previous_peak_line_contains_peak"),
            "m5_previous_peak_line_is_near": order_plan.get("m5_previous_peak_line_is_near"),
            "m5_previous_peak_line_is_near_strong": order_plan.get("m5_previous_peak_line_is_near_strong"),
            "h1_previous_peak_line_side": order_plan.get("h1_previous_peak_line_side"),
            "h1_previous_peak_line_price": order_plan.get("h1_previous_peak_line_price"),
            "h1_previous_peak_line_distance_pips": order_plan.get("h1_previous_peak_line_distance_pips"),
            "h1_previous_peak_line_total_strength": order_plan.get("h1_previous_peak_line_total_strength"),
            "h1_previous_peak_line_count": order_plan.get("h1_previous_peak_line_count"),
            "h1_previous_peak_line_core_total_strength": order_plan.get("h1_previous_peak_line_core_total_strength"),
            "h1_previous_peak_line_is_flipped": order_plan.get("h1_previous_peak_line_is_flipped"),
            "h1_previous_peak_line_contains_peak": order_plan.get("h1_previous_peak_line_contains_peak"),
            "h1_previous_peak_line_is_near": order_plan.get("h1_previous_peak_line_is_near"),
            "h1_previous_peak_line_is_near_strong": order_plan.get("h1_previous_peak_line_is_near_strong"),
            "line_side": order_plan.get("line_side"),
            "line_price": order_plan.get("line_price"),
            "line_total_strength": order_plan.get("line_total_strength"),
            "line_count": order_plan.get("line_count"),
            "line_ave_strength": order_plan.get("line_ave_strength"),
            "line_is_flipped": order_plan.get("line_is_flipped"),
            "line_oldest_time": order_plan.get("line_oldest_time"),
            "core_median_price": order_plan.get("core_median_price"),
            "core_count": order_plan.get("core_count"),
            "core_total_strength": order_plan.get("core_total_strength"),
            "line_strategy": order_plan.get("line_strategy"),
            "line_peak_rsi_avg": order_plan.get("line_peak_rsi_avg"),
            "line_peak_rsi_latest": order_plan.get("line_peak_rsi_latest"),
            "line_peak_rsi_count": order_plan.get("line_peak_rsi_count"),
            "line_behavior": order_plan.get("line_behavior"),
            "line_break_score": order_plan.get("line_break_score"),
            "line_resist_score": order_plan.get("line_resist_score"),
            "line_behavior_reasons": order_plan.get("line_behavior_reasons"),
            "line_break_reasons": order_plan.get("line_break_reasons"),
            "line_resist_reasons": order_plan.get("line_resist_reasons"),
            "line_break_threshold_pips": order_plan.get("line_break_threshold_pips"),
            "line_origin_peak_dir": order_plan.get("line_origin_peak_dir"),
            "line_origin_role": order_plan.get("line_origin_role"),
            "line_current_role": order_plan.get("line_current_role"),
            "line_history_is_flipped": order_plan.get("line_history_is_flipped"),
            "line_flip_count": order_plan.get("line_flip_count"),
            "line_latest_flip_time": order_plan.get("line_latest_flip_time"),
            "line_latest_flip_elapsed_minutes": order_plan.get("line_latest_flip_elapsed_minutes"),
            "line_latest_flip_bars": order_plan.get("line_latest_flip_bars"),
            "line_latest_touch_peak_dir": order_plan.get("line_latest_touch_peak_dir"),
            "line_latest_touch_time": order_plan.get("line_latest_touch_time"),
            "line_latest_touch_elapsed_minutes": order_plan.get("line_latest_touch_elapsed_minutes"),
            "line_latest_touch_bars": order_plan.get("line_latest_touch_bars"),
            "line_touch_count": order_plan.get("line_touch_count"),
            "line_single_role": order_plan.get("line_single_role"),
            "line_single_role_last_touch_time": order_plan.get("line_single_role_last_touch_time"),
            "line_single_role_last_touch_elapsed_minutes": order_plan.get("line_single_role_last_touch_elapsed_minutes"),
            "line_single_role_last_touch_bars": order_plan.get("line_single_role_last_touch_bars"),
            "h1_upper_price": order_plan.get("h1_upper_price"),
            "h1_upper_distance_pips": order_plan.get("h1_upper_distance_pips"),
            "h1_upper_total_strength": order_plan.get("h1_upper_total_strength"),
            "h1_upper_count": order_plan.get("h1_upper_count"),
            "h1_upper_core_total_strength": order_plan.get("h1_upper_core_total_strength"),
            "h1_upper_is_flipped": order_plan.get("h1_upper_is_flipped"),
            "h1_lower_price": order_plan.get("h1_lower_price"),
            "h1_lower_distance_pips": order_plan.get("h1_lower_distance_pips"),
            "h1_lower_total_strength": order_plan.get("h1_lower_total_strength"),
            "h1_lower_count": order_plan.get("h1_lower_count"),
            "h1_lower_core_total_strength": order_plan.get("h1_lower_core_total_strength"),
            "h1_lower_is_flipped": order_plan.get("h1_lower_is_flipped"),
            "h1_nearest_side": order_plan.get("h1_nearest_side"),
            "h1_nearest_price": order_plan.get("h1_nearest_price"),
            "h1_nearest_distance_pips": order_plan.get("h1_nearest_distance_pips"),
            "h1_nearest_total_strength": order_plan.get("h1_nearest_total_strength"),
            "h1_nearest_count": order_plan.get("h1_nearest_count"),
            "h1_nearest_core_total_strength": order_plan.get("h1_nearest_core_total_strength"),
            "h1_nearest_is_flipped": order_plan.get("h1_nearest_is_flipped"),
            "h1_ahead_side": order_plan.get("h1_ahead_side"),
            "h1_ahead_price": order_plan.get("h1_ahead_price"),
            "h1_ahead_distance_pips": order_plan.get("h1_ahead_distance_pips"),
            "h1_ahead_total_strength": order_plan.get("h1_ahead_total_strength"),
            "h1_ahead_count": order_plan.get("h1_ahead_count"),
            "h1_ahead_core_total_strength": order_plan.get("h1_ahead_core_total_strength"),
            "h1_ahead_is_flipped": order_plan.get("h1_ahead_is_flipped"),
            "h1_path_ahead_1_side": order_plan.get("h1_path_ahead_1_side"),
            "h1_path_ahead_1_price": order_plan.get("h1_path_ahead_1_price"),
            "h1_path_ahead_1_distance_pips": order_plan.get("h1_path_ahead_1_distance_pips"),
            "h1_path_ahead_1_total_strength": order_plan.get("h1_path_ahead_1_total_strength"),
            "h1_path_ahead_1_count": order_plan.get("h1_path_ahead_1_count"),
            "h1_path_ahead_1_core_total_strength": order_plan.get("h1_path_ahead_1_core_total_strength"),
            "h1_path_ahead_1_is_flipped": order_plan.get("h1_path_ahead_1_is_flipped"),
            "h1_path_ahead_2_side": order_plan.get("h1_path_ahead_2_side"),
            "h1_path_ahead_2_price": order_plan.get("h1_path_ahead_2_price"),
            "h1_path_ahead_2_distance_pips": order_plan.get("h1_path_ahead_2_distance_pips"),
            "h1_path_ahead_2_total_strength": order_plan.get("h1_path_ahead_2_total_strength"),
            "h1_path_ahead_2_count": order_plan.get("h1_path_ahead_2_count"),
            "h1_path_ahead_2_core_total_strength": order_plan.get("h1_path_ahead_2_core_total_strength"),
            "h1_path_ahead_2_is_flipped": order_plan.get("h1_path_ahead_2_is_flipped"),
            "h1_path_ahead_1_to_2_distance_pips": order_plan.get("h1_path_ahead_1_to_2_distance_pips"),
            "h1_behind_side": order_plan.get("h1_behind_side"),
            "h1_behind_price": order_plan.get("h1_behind_price"),
            "h1_behind_distance_pips": order_plan.get("h1_behind_distance_pips"),
            "h1_behind_total_strength": order_plan.get("h1_behind_total_strength"),
            "h1_behind_count": order_plan.get("h1_behind_count"),
            "h1_behind_core_total_strength": order_plan.get("h1_behind_core_total_strength"),
            "h1_behind_is_flipped": order_plan.get("h1_behind_is_flipped"),
            "h1_near_same_line": order_plan.get("h1_near_same_line"),
            "h1_blocks_trade_direction": order_plan.get("h1_blocks_trade_direction"),
            "session_name": order_plan.get("session_name"),
            "session_hour": order_plan.get("session_hour"),
            "session_time": order_plan.get("session_time"),
            "session_units_multiplier": order_plan.get("session_units_multiplier"),
            "session_rr": order_plan.get("session_rr"),
            "session_tp_pips": order_plan.get("session_tp_pips"),
            "session_tp_multiplier": order_plan.get("session_tp_multiplier"),
            "session_lc_multiplier": order_plan.get("session_lc_multiplier"),
            "session_skip_reason": order_plan.get("session_skip_reason"),
            "rsi_1": order_plan.get("rsi_1"),
            "rsi_2": order_plan.get("rsi_2"),
            "rsi_3": order_plan.get("rsi_3"),
            "rsi_time_1": order_plan.get("rsi_time_1"),
            "rsi_time_2": order_plan.get("rsi_time_2"),
            "rsi_time_3": order_plan.get("rsi_time_3"),
            "rsi_upper_border": order_plan.get("rsi_upper_border"),
            "rsi_lower_border": order_plan.get("rsi_lower_border"),
            "rsi_is_high": order_plan.get("rsi_is_high"),
            "rsi_is_low": order_plan.get("rsi_is_low"),
            "h1_rsi_1": order_plan.get("h1_rsi_1"),
            "h1_rsi_2": order_plan.get("h1_rsi_2"),
            "h1_rsi_3": order_plan.get("h1_rsi_3"),
            "h1_rsi_time_1": order_plan.get("h1_rsi_time_1"),
            "h1_rsi_time_2": order_plan.get("h1_rsi_time_2"),
            "h1_rsi_time_3": order_plan.get("h1_rsi_time_3"),
            "h1_rsi_is_high": order_plan.get("h1_rsi_is_high"),
            "h1_rsi_is_low": order_plan.get("h1_rsi_is_low"),
            "path_tp_adjusted": order_plan.get("path_tp_adjusted"),
            "path_tp_adjusted_label": order_plan.get("path_tp_adjusted_label"),
            "tp_last_touch_time": order_plan.get("tp_last_touch_time"),
            "tp_last_touch_elapsed_minutes": order_plan.get("tp_last_touch_elapsed_minutes"),
            "tp_last_touch_found": order_plan.get("tp_last_touch_found"),
            "tp_last_touch_elapsed_bin": order_plan.get("tp_last_touch_elapsed_bin"),
            "tp_touch_history_oldest_time": order_plan.get("tp_touch_history_oldest_time"),
            "tp_touch_history_coverage_minutes": order_plan.get("tp_touch_history_coverage_minutes"),
            "path_tp_pips": order_plan.get("path_tp_pips"),
            "path_lc_pips": order_plan.get("path_lc_pips"),
            "path_tp_original_pips": order_plan.get("path_tp_original_pips"),
            "path_lc_original_pips": order_plan.get("path_lc_original_pips"),
            "path_tp_rr": order_plan.get("path_tp_rr"),
            "for_api_json": order_plan.get("for_api_json"),
            "memo": order_plan.get("memo"),
        }

    def cal_order_result_pips(self, order_plan, close_price):
        if close_price is None:
            return None

        pair = self.p
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

    @staticmethod
    def build_rsi_info(df_r, h1_df_r=None):
        upper_border = 67.5
        lower_border = 30
        h1_info = Inspection.build_prefixed_rsi_info(
            h1_df_r,
            "h1",
            upper_border,
            lower_border,
        )
        if len(df_r) <= 3 or "RSI" not in df_r.columns:
            return {
                "rsi_1": None,
                "rsi_2": None,
                "rsi_3": None,
                "rsi_time_1": None,
                "rsi_time_2": None,
                "rsi_time_3": None,
                "rsi_upper_border": upper_border,
                "rsi_lower_border": lower_border,
                "rsi_is_high": None,
                "rsi_is_low": None,
                **h1_info,
            }

        f_low = df_r.iloc[1]
        s_low = df_r.iloc[2]
        t_low = df_r.iloc[3]
        rsi_1 = f_low.get("RSI")
        return {
            "rsi_1": rsi_1,
            "rsi_2": s_low.get("RSI"),
            "rsi_3": t_low.get("RSI"),
            "rsi_time_1": f_low.get("time_jp"),
            "rsi_time_2": s_low.get("time_jp"),
            "rsi_time_3": t_low.get("time_jp"),
            "rsi_upper_border": upper_border,
            "rsi_lower_border": lower_border,
            "rsi_is_high": rsi_1 >= upper_border,
            "rsi_is_low": rsi_1 <= lower_border,
            **h1_info,
        }

    @staticmethod
    def build_prefixed_rsi_info(df_r, prefix, upper_border, lower_border):
        info = {
            f"{prefix}_rsi_1": None,
            f"{prefix}_rsi_2": None,
            f"{prefix}_rsi_3": None,
            f"{prefix}_rsi_time_1": None,
            f"{prefix}_rsi_time_2": None,
            f"{prefix}_rsi_time_3": None,
            f"{prefix}_rsi_is_high": None,
            f"{prefix}_rsi_is_low": None,
        }
        if df_r is None or len(df_r) <= 3 or "RSI" not in df_r.columns:
            return info

        f_low = df_r.iloc[1]
        s_low = df_r.iloc[2]
        t_low = df_r.iloc[3]
        rsi_1 = f_low.get("RSI")
        info.update({
            f"{prefix}_rsi_1": rsi_1,
            f"{prefix}_rsi_2": s_low.get("RSI"),
            f"{prefix}_rsi_3": t_low.get("RSI"),
            f"{prefix}_rsi_time_1": f_low.get("time_jp"),
            f"{prefix}_rsi_time_2": s_low.get("time_jp"),
            f"{prefix}_rsi_time_3": t_low.get("time_jp"),
            f"{prefix}_rsi_is_high": rsi_1 >= upper_border,
            f"{prefix}_rsi_is_low": rsi_1 <= lower_border,
        })
        return info

    def line_to_order_plan(self, target_time, line_side, line, rsi_info=None):
        pair = self.p
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
            "line_timeframe": "h1",
            "line_side": line_side,
            "line_price": pair.round_price(line_price),
            "line_total_strength": line.get("total_strength"),
            "line_count": line.get("count"),
            "line_ave_strength": line.get("ave_strength"),
            "line_is_flipped": line.get("is_flipped_line"),
            "line_oldest_time": line.get("oldest_time"),
            "core_median_price": line.get("core_median_price"),
            "core_count": line.get("core_count"),
            "core_total_strength": line.get("core_total_strength"),
            "line_strategy": "lower_c3_core1or3",
            "line_peak_rsi_avg": line.get("line_peak_rsi_avg"),
            "line_peak_rsi_latest": line.get("line_peak_rsi_latest"),
            "line_peak_rsi_count": line.get("line_peak_rsi_count"),
            **(rsi_info or {}),
        }

    def cal_first_reach_results(self, df, target_price, direction):
        thresholds = (5, 10, 15, 20, 25, 30)
        results = {}
        for pips in thresholds:
            side, reach_time, elapsed_s5 = self.find_first_reach(df, target_price, direction, pips)
            results[f"first_{pips}pips_side"] = side
            results[f"first_{pips}pips_time"] = reach_time
            results[f"first_{pips}pips_elapsed_s5"] = elapsed_s5
        return results

    def cal_first_reach_results_actual(self, df, entry_price_actual, direction):
        thresholds = (5, 10, 15, 20, 25, 30)
        results = {}
        for pips in thresholds:
            side, reach_time, elapsed_s5 = self.find_first_reach_actual(
                df,
                entry_price_actual,
                direction,
                pips,
            )
            results[f"first_{pips}pips_side"] = side
            results[f"first_{pips}pips_time"] = reach_time
            results[f"first_{pips}pips_elapsed_s5"] = elapsed_s5
        return results

    def find_first_reach(self, df, target_price, direction, threshold_pips):
        pair = self.p
        threshold_price = pair.pips_to_price(threshold_pips)
        if df.empty:
            return "none", None, None
        high = df["high"].to_numpy()
        low = df["low"].to_numpy()
        if direction == 1:
            plus_hit = high >= target_price + threshold_price
            minus_hit = low <= target_price - threshold_price
        else:
            plus_hit = low <= target_price - threshold_price
            minus_hit = high >= target_price + threshold_price

        indexes = np.flatnonzero(plus_hit | minus_hit)
        if indexes.size:
            i = int(indexes[0])
            reach_time = df.iloc[i]["time_jp"]
            if plus_hit[i] and minus_hit[i]:
                return "both", reach_time, i
            if plus_hit[i]:
                return "plus", reach_time, i
            return "minus", reach_time, i
        return "none", None, None

    def find_first_reach_actual(self, df, entry_price_actual, direction, threshold_pips):
        pair = self.p
        threshold_price = pair.pips_to_price(threshold_pips)
        half = pair.pips_to_price(self.half_spread_pips)
        if df.empty or entry_price_actual is None:
            return "none", None, None
        high = df["high"].to_numpy()
        low = df["low"].to_numpy()
        if direction == 1:
            bid_high = high - half
            bid_low = low - half
            plus_hit = bid_high >= entry_price_actual + threshold_price
            minus_hit = bid_low <= entry_price_actual - threshold_price
        else:
            ask_low = low + half
            ask_high = high + half
            plus_hit = ask_low <= entry_price_actual - threshold_price
            minus_hit = ask_high >= entry_price_actual + threshold_price

        indexes = np.flatnonzero(plus_hit | minus_hit)
        if indexes.size:
            i = int(indexes[0])
            reach_time = df.iloc[i]["time_jp"]
            if plus_hit[i] and minus_hit[i]:
                return "both", reach_time, i
            if plus_hit[i]:
                return "plus", reach_time, i
            return "minus", reach_time, i
        return "none", None, None

    def required_data_range(self):
        data_from = self.start_time - datetime.timedelta(hours=self.anaN)
        inspection_seconds = max(self.insN - 1, 0) * 5
        data_to_by_inspection = self.end_time + datetime.timedelta(seconds=inspection_seconds)
        now = datetime.datetime.now().replace(microsecond=0)
        data_to = min(data_to_by_inspection, now)
        return data_from, data_to

    def required_h1_data_from(self):
        return self.start_time - datetime.timedelta(hours=max(self.anaN, 250))

    @staticmethod
    def slice_past_df_r(df, target_time, row_count=None):
        if df is None or df.empty:
            return pd.DataFrame()
        end_index = int(df["time_jp_dt"].searchsorted(target_time, side="right"))
        start_index = 0 if row_count is None else max(0, end_index - row_count)
        return df.iloc[start_index:end_index].iloc[::-1].reset_index(drop=True)

    def current_price_at(self, target_time, analysis_m5_df_r):
        if self.gl_s5_df is not None and not self.gl_s5_df.empty:
            completed_s5_open_time = target_time - datetime.timedelta(seconds=5)
            end_index = int(
                self.gl_s5_df["time_jp_dt"].searchsorted(
                    completed_s5_open_time,
                    side="right",
                )
            )
            if end_index > 0:
                return self.gl_s5_df.iloc[end_index - 1]["close"]
        return analysis_m5_df_r.iloc[0]["close"]

    @staticmethod
    def validate_analysis_boundary(df_r, target_time, candle_duration, label):
        if df_r is None or len(df_r) < 2:
            return
        forming_open_time = df_r.iloc[0]["time_jp_dt"]
        latest_analysis_open_time = df_r.iloc[1]["time_jp_dt"]
        if forming_open_time > target_time:
            raise ValueError(
                label + " forming candle starts after target_time: "
                + str(forming_open_time)
            )
        if latest_analysis_open_time + candle_duration > target_time:
            raise ValueError(
                label + " analysis contains incomplete candle: "
                + str(latest_analysis_open_time)
            )

    def slice_inspection_s5_df(self, target_time):
        start_time = target_time
        start_index = int(
            self.gl_s5_df["time_jp_dt"].searchsorted(start_time, side="left")
        )
        end_index = min(start_index + self.insN, len(self.gl_s5_df))
        return self.gl_s5_df.iloc[start_index:end_index].reset_index(drop=True)

    @staticmethod
    def cal_oanda_count_and_loop(need_rows):
        if need_rows > 5000:
            return 5000, math.ceil(need_rows / 5000)
        return need_rows, 1
