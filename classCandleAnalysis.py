# 最新更新日時: 2026-08-29 21:21 JST

import contextlib
import datetime
import io
import math
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
from collections import defaultdict
import tokens as tk
import send_notice as notice
import fGeneric as gene
import fGeneric as f
import copy
import classCandlePeaks as peaksClass
import fCandleDataQuality as candle_quality
from fFootCountShape import (
    foot_count2_shape_context,
    latest_two_candle_shape_context,
)
from pympler import asizeof


JST = ZoneInfo("Asia/Tokyo")
M5_ANALYSIS_BARS = 180
H1_ANALYSIS_BARS = 240


@dataclass
class CandleDecisionContext:
    """One causal candle/peak snapshot shared by every strategy."""

    pair_name: str
    pair: Any
    mode: str
    decision_time: pd.Timestamp
    current_price: float
    current_price_source: str
    latest_completed_m5_close: float
    m5_original_df_r: pd.DataFrame
    h1_original_df_r: pd.DataFrame | None
    m5_completed_df_r: pd.DataFrame
    h1_completed_df_r: pd.DataFrame | None
    m5_peaks_class: Any
    h1_peaks_class: Any
    newest_m5_peak: dict[str, Any]
    m5_foot_count2_shape: dict[str, Any]
    h1_latest_two_shapes: dict[int, dict[str, Any]]
    rsi_info: dict[str, Any]
    data_quality_validated: bool
    m5_missing_bars: int
    h1_missing_bars: int
    m5_missing_ratio: float
    h1_missing_ratio: float
    m5_last_end: pd.Timestamp
    h1_last_end: pd.Timestamp | None

    @property
    def peak_direction(self) -> int:
        try:
            return int(self.newest_m5_peak.get("direction") or 0)
        except (TypeError, ValueError, AttributeError):
            return 0

    def h1_shape_for_direction(self, direction: int) -> dict[str, Any]:
        """Return the common latest-two-H1 shape in the requested orientation."""
        return self.h1_latest_two_shapes.get(int(direction), {"valid": False})

    def shape_for_peak(
            self,
            peak: dict[str, Any],
            timeframe: str = "M5",
            *,
            average_range_pips: float | None = None,
    ) -> dict[str, Any]:
        """Describe one foot-count-2 peak without fetching/rebuilding candles."""
        timeframe = str(timeframe).upper()
        if timeframe == "M5":
            completed_df_r = self.m5_completed_df_r
            minutes = 5
        elif timeframe == "H1":
            completed_df_r = self.h1_completed_df_r
            minutes = 60
        else:
            raise ValueError("timeframe must be M5 or H1")
        return foot_count2_shape_context(
            completed_df_r,
            peak,
            self.decision_time,
            self.pair,
            average_range_pips=average_range_pips,
            timeframe_minutes=minutes,
        )


class candleAnalysis:

    # 重複のAPIたたきを極力減らしたい
    avoid_dup_5min_kara_time = 0  # 重複での処理作業防止用（最新で取得した5分足のデータのカラマデの時間を所持。クラス生成時、同じ場合は新規処理しない）
    avoid_dup_5min_made_time = 0
    latest_m5_original_df_r = None
    latest_m5_completed_df_r = None
    latest_peaks_class = None  # 最新の物を持っておく（判定用に冗長に持っていて、そとからはインスタンス変数を参照がメイン。）
    latest_candle_meta_class = None
    latest_h1_original_df_r = None
    latest_h1_completed_df_r = None
    latest_s5_original_df_r = None
    latest_s5_completed_df_r = None
    latest_peaks_class_hour = None  # 最新の物を持っておく（判定用に冗長に持っていて、そとからはインスタンス変数を参照がメイン。）
    latest_candle_meta_class_hour = None
    latest_m30_original_df_r = None
    latest_m30_completed_df_r = None
    latest_peaks_class_m30 = None  # 最新の物を持っておく（判定用に冗長に持っていて、そとからはインスタンス変数を参照がメイン。）
    latest_candle_meta_class_m30 = None
    latest_current_price = None
    latest_current_price_by_df = None
    latest_current_price_source = None
    latest_decision_context = None
    latest_decision_context_error = None
    latest_decision_context_error_type = None
    latest_decision_context_not_ready = False
    latest_pair = None

    def __init__(
            self,
            base_oa=None,
            pair="USD_JPY",
            target_time_jp=0,
            m5_original_df_r=None,
            h1_original_df_r=None,
            m30_original_df_r=None,
            s5_original_df_r=None,
            current_price=None,
            h1_analysis_cache=None,
            m30_analysis_cache=None,
            decision_time=None,
            current_price_source=None,
    ):
        """
        target_time_jpまでの時間を取得する
        """
        # pair
        self.pair = pair  # 通貨ペア
        # オアンダクラス
        self.base_oa = base_oa
        self.need_df_num = 250
        # flip の既存ライブ判定と同じ本数でRSIを準備してから直近250本へ絞る。
        self.m5_need_df_num = 350
        self.h1_need_df_num = 300

        self.analysis_mode = (
            "inspection"
            if target_time_jp != 0 or m5_original_df_r is not None
            else "live"
        )
        self.decision_time = self.resolve_decision_time(
            decision_time,
            target_time_jp,
            m5_original_df_r,
        )

        self.current_price = 0  # 後に価格として入る(本番の場合[=時間指定なし]API、検証の場合はdfの先頭）
        self.current_price_by_df = 0  # 判断時刻までの最新完成M5終値
        self.current_price_source = current_price_source or "unresolved"
        self.decision_context = None
        self.basic_analysis = None
        self.decision_context_error = None
        self.decision_context_error_type = None
        self.decision_context_not_ready = False

        # 命名契約:
        # original_df_r = 判断時刻以前の取得範囲（形成中の0行目を含み得る）
        # completed_df_r = 終了時刻とcompleteフラグを満たす完成足だけ
        # _r = 実時刻の降順（0行目が最新）
        self.m5_original_df_r = None
        self.m5_completed_df_r = None
        self.h1_original_df_r = None
        self.h1_completed_df_r = None
        self.s5_original_df_r = None
        self.s5_completed_df_r = None
        self.m30_original_df_r = None
        self.m30_completed_df_r = None
        self.m30_uses_h1_fallback = False

        if m5_original_df_r is not None:
            self.m5_original_df_r = m5_original_df_r
            self.h1_original_df_r = h1_original_df_r
            self.m30_original_df_r = m30_original_df_r
            self.s5_original_df_r = s5_original_df_r
            if self.h1_original_df_r is None:
                raise ValueError(
                    "h1_original_df_r is required when "
                    "m5_original_df_r is passed."
                )
            if self.m30_original_df_r is None:
                print(
                    "m30_original_df_r is not passed. "
                    "h1_original_df_r is used as a temporary fallback "
                    "for M30 analysis."
                )
                self.m30_original_df_r = self.h1_original_df_r
                self.m30_uses_h1_fallback = True
            if current_price is not None:
                self.current_price = float(current_price)
                if current_price_source is None:
                    self.current_price_source = "inspection_candle"
            else:
                completed_close = self.latest_completed_close(
                    self.m5_original_df_r,
                    self.decision_time,
                    datetime.timedelta(minutes=5),
                )
                if completed_close is None:
                    raise ValueError("no completed M5 close for current price")
                self.current_price = completed_close
                self.current_price_source = "inspection_m5"
            completed_close = self.latest_completed_close(
                self.m5_original_df_r,
                self.decision_time,
                datetime.timedelta(minutes=5),
            )
            self.current_price_by_df = (
                completed_close
                if completed_close is not None
                else self.current_price
            )

        # # ■■　重複でAPIを打つことを避けたい
        if m5_original_df_r is not None:
            pass
        elif (
                self.analysis_mode != "live"
                or
                candleAnalysis.latest_m5_original_df_r is None
                or (
                    candleAnalysis.latest_pair is not None
                    and candleAnalysis.latest_pair != self.pair
                )
        ):
            print("データ取得（同じデータがないため、新規で取得）")
            t1 = 0
            pass
        else:
            t1 = datetime.datetime.strptime(
                candleAnalysis.latest_m5_original_df_r.iloc[0]['time_jp'],
                "%Y/%m/%d %H:%M:%S",
            )
            t2 = datetime.datetime.now()
            same = (t1.year == t2.year and
                    t1.month == t2.month and
                    t1.day == t2.day and
                    t1.hour == t2.hour and
                    t1.minute == t2.minute)
            cached_context = candleAnalysis.latest_decision_context
            same = bool(
                same
                and cached_context is not None
                and pd.Timestamp(cached_context.decision_time)
                == self.decision_time
                and pd.Timestamp(cached_context.m5_last_end)
                == self.decision_time
                and cached_context.h1_last_end is not None
                and pd.Timestamp(cached_context.h1_last_end)
                == self.decision_time.floor("h")
            )
            print(
                "既存のデータのfrom",
                candleAnalysis.latest_m5_original_df_r.iloc[0]['time_jp'],
            )
            print("既存のDataFrameと同じかどうか？", same, t1, t2)
            if same:
                print("同じデータのたpeaks_class_30mめ、データ新規取得＆Peaks生成は呼ばず(主にcandleLCChangeで発生)  既存:", t1, ",現時刻:", t2)
                # データを移植する（5分足）
                self.m5_original_df_r = candleAnalysis.latest_m5_original_df_r
                self.m5_completed_df_r = candleAnalysis.latest_m5_completed_df_r
                self.peaks_class = candleAnalysis.latest_peaks_class
                self.candle_meta_class = candleAnalysis.latest_candle_meta_class
                # データを移植する（60分足）
                self.h1_original_df_r = candleAnalysis.latest_h1_original_df_r
                self.h1_completed_df_r = candleAnalysis.latest_h1_completed_df_r
                self.s5_original_df_r = candleAnalysis.latest_s5_original_df_r
                self.s5_completed_df_r = candleAnalysis.latest_s5_completed_df_r
                self.peaks_class_hour = candleAnalysis.latest_peaks_class_hour
                self.candle_meta_class_hour = candleAnalysis.latest_candle_meta_class_hour
                # データを移植する（30分足）
                self.m30_original_df_r = candleAnalysis.latest_m30_original_df_r
                self.m30_completed_df_r = candleAnalysis.latest_m30_completed_df_r
                self.peaks_class_m30 = candleAnalysis.latest_peaks_class_m30
                self.candle_meta_class_m30 = candleAnalysis.latest_candle_meta_class_m30
                self.current_price = candleAnalysis.latest_current_price
                self.current_price_by_df = candleAnalysis.latest_current_price_by_df
                self.current_price_source = candleAnalysis.latest_current_price_source
                self.decision_context = candleAnalysis.latest_decision_context
                self.basic_analysis = self.decision_context
                self.decision_context_error = (
                    candleAnalysis.latest_decision_context_error
                )
                self.decision_context_error_type = (
                    candleAnalysis.latest_decision_context_error_type
                )
                self.decision_context_not_ready = (
                    candleAnalysis.latest_decision_context_not_ready
                )
                self.sync_peaks_from_basic_analysis()
                return

        # ■■データ取得
        if m5_original_df_r is None:
            self.get_date_df(target_time_jp)
        if self.m5_original_df_r is None:
            print("データ取得＆Peaks生成 失敗？？")
        else:
            print("現在時刻（本番時のみ意味あり）", datetime.datetime.now())
            print(
                "データ取得＆Peaks生成  データfrom",
                self.m5_original_df_r.iloc[0]['time_jp'],
                "to",
                self.m5_original_df_r.iloc[-1]['time_jp'],
            )

        # ■■処理続行判定
        # 重複作業防止用に、クラス変数に5分足の最初と最後の情報を入れておく
        if self.m5_original_df_r is None:
            print("★★ データフレームが取得されていないエラーが発生")
            return

        self.prepare_timeframe_dataframes()

        # ■■処理
        # データを取得する(5分足系）
        granularity = "M5"
        self.peaks_class = peaksClass.PeaksClass(
            self.m5_original_df_r,
            granularity,
            self.current_price,
            gene.currency_pair(self.pair),
            completed_df_r=self.m5_completed_df_r,
            decision_time=self.decision_time,
        )  # ★peaks_classの生成
        self.candle_meta_class = CandleMeta(self.peaks_class, granularity)

        # データを取得する（60分足）
        granularity = "H1"
        if h1_analysis_cache is None:
            self.peaks_class_hour = peaksClass.PeaksClass(
                self.h1_original_df_r,
                granularity,
                self.current_price,
                gene.currency_pair(self.pair),
                completed_df_r=self.h1_completed_df_r,
                decision_time=self.decision_time,
            )
            self.candle_meta_class_hour = CandleMeta(
                self.peaks_class_hour,
                granularity,
            )
        else:
            self.peaks_class_hour, self.candle_meta_class_hour = h1_analysis_cache
            self.refresh_cached_peak_price(
                self.peaks_class_hour,
                self.current_price,
            )

        # データを取得する（30分足）
        granularity = "M30"
        if m30_analysis_cache is None:
            self.peaks_class_m30 = peaksClass.PeaksClass(
                self.m30_original_df_r,
                granularity,
                self.current_price,
                gene.currency_pair(self.pair),
                completed_df_r=self.m30_completed_df_r,
                decision_time=self.decision_time,
                source_granularity=(
                    "H1" if self.m30_uses_h1_fallback else "M30"
                ),
            )
            self.candle_meta_class_m30 = CandleMeta(
                self.peaks_class_m30,
                granularity,
            )
        else:
            self.peaks_class_m30, self.candle_meta_class_m30 = m30_analysis_cache
            self.refresh_cached_peak_price(
                self.peaks_class_m30,
                self.current_price,
            )

        # 戦略共通の完成足・Peaks・ローソク形状はここで一度だけ作る。
        self.build_basic_analysis()

        if m5_original_df_r is not None:
            return

        # ■■重複作業防止用に、クラス変数に5分足の最初と最後の情報、今回算出した情報を入れておく
        if self.m5_original_df_r is None:
            # Noneの場合はおかしいので処理しない（基本ない）
            pass
        else:
            # クラス変数に、最新の値だけを入れておく
            candleAnalysis.avoid_dup_5min_kara_time = (
                self.m5_original_df_r.iloc[-1]['time_jp']
            )
            candleAnalysis.avoid_dup_5min_made_time = (
                self.m5_original_df_r.iloc[0]['time_jp']
            )
            candleAnalysis.latest_m5_original_df_r = self.m5_original_df_r
            candleAnalysis.latest_m5_completed_df_r = self.m5_completed_df_r
            candleAnalysis.latest_peaks_class = self.peaks_class  # 最新の物を持っておく（判定用に冗長に持っていて、そとからはインスタンス変数を参照がメイン。）
            candleAnalysis.latest_candle_meta_class = self.candle_meta_class
            candleAnalysis.latest_h1_original_df_r = self.h1_original_df_r
            candleAnalysis.latest_h1_completed_df_r = self.h1_completed_df_r
            candleAnalysis.latest_s5_original_df_r = self.s5_original_df_r
            candleAnalysis.latest_s5_completed_df_r = self.s5_completed_df_r
            candleAnalysis.latest_peaks_class_hour = self.peaks_class_hour  # 最新の物を持っておく（判定用に冗長に持っていて、そとからはインスタンス変数を参照がメイン。）
            candleAnalysis.latest_candle_meta_class_hour = self.candle_meta_class_hour
            candleAnalysis.latest_m30_original_df_r = self.m30_original_df_r
            candleAnalysis.latest_m30_completed_df_r = self.m30_completed_df_r
            candleAnalysis.latest_peaks_class_m30 = self.peaks_class_m30  # 最新の物を持っておく（判定用に冗長に持っていて、そとからはインスタンス変数を参照がメイン。）
            candleAnalysis.latest_candle_meta_class_m30 = self.candle_meta_class_m30
            candleAnalysis.latest_current_price = self.current_price
            candleAnalysis.latest_current_price_by_df = self.current_price_by_df
            candleAnalysis.latest_current_price_source = self.current_price_source
            candleAnalysis.latest_decision_context = self.decision_context
            candleAnalysis.latest_decision_context_error = self.decision_context_error
            candleAnalysis.latest_decision_context_error_type = (
                self.decision_context_error_type
            )
            candleAnalysis.latest_decision_context_not_ready = (
                self.decision_context_not_ready
            )
            candleAnalysis.latest_pair = self.pair

    @staticmethod
    def normalize_decision_time(value):
        stamp = pd.Timestamp(value)
        if pd.isna(stamp):
            raise ValueError("decision time is invalid")
        if stamp.tzinfo is not None:
            stamp = stamp.tz_convert(JST).tz_localize(None)
        return stamp.floor("s")

    @classmethod
    def resolve_decision_time(
            cls,
            decision_time,
            target_time_jp,
            m5_original_df_r,
    ):
        if decision_time is not None:
            return cls.normalize_decision_time(decision_time)
        if target_time_jp != 0:
            return cls.normalize_decision_time(target_time_jp)
        if (
                isinstance(m5_original_df_r, pd.DataFrame)
                and not m5_original_df_r.empty
        ):
            raise ValueError(
                "decision_time or target_time_jp is required when "
                "m5_original_df_r is passed"
            )
        return pd.Timestamp.now(tz=JST).floor("5min").tz_localize(None)

    @staticmethod
    def _frame_times(frame):
        time_column = (
            "time_jp_dt"
            if "time_jp_dt" in frame.columns
            else "time_jp"
        )
        if time_column not in frame.columns:
            raise ValueError("candle frame has no time column")
        times = pd.to_datetime(frame[time_column], errors="coerce")
        if times.isna().any():
            raise ValueError("candle frame contains an invalid time")
        if getattr(times.dt, "tz", None) is not None:
            times = times.dt.tz_convert(JST).dt.tz_localize(None)
        return times

    @classmethod
    def normalize_original_df_r(cls, frame, decision_time, label):
        """Normalize one source frame to newest-first and keep row 0."""
        if not isinstance(frame, pd.DataFrame) or frame.empty:
            raise ValueError(label + " is empty")
        decision = cls.normalize_decision_time(decision_time)
        original_df_r = frame.copy()
        original_df_r["_basic_time"] = cls._frame_times(original_df_r)
        original_df_r = original_df_r[
            original_df_r["_basic_time"] <= decision
        ].copy()
        if original_df_r.empty:
            raise ValueError(label + " has no candle at decision_time")
        original_df_r.sort_values(
            "_basic_time",
            ascending=False,
            kind="stable",
            inplace=True,
        )
        if original_df_r["_basic_time"].duplicated().any():
            raise ValueError(label + " contains duplicate times")
        original_df_r["time_jp_dt"] = original_df_r["_basic_time"]
        original_df_r["time_jp"] = original_df_r[
            "_basic_time"
        ].dt.strftime("%Y/%m/%d %H:%M:%S")
        original_df_r.drop(columns="_basic_time", inplace=True)
        original_df_r.reset_index(drop=True, inplace=True)
        return original_df_r

    @classmethod
    def select_completed_df_r(
            cls,
            frame,
            decision_time,
            candle_duration,
            *,
            limit=None,
            require_complete_flag=False,
    ):
        """Return completed candles newest-first; row 0 is latest complete."""
        if not isinstance(frame, pd.DataFrame) or frame.empty:
            raise ValueError("candle frame is empty")
        required = {"open", "close", "high", "low"}
        missing = required - set(frame.columns)
        if missing:
            raise ValueError("candle frame missing: " + ", ".join(sorted(missing)))

        decision = cls.normalize_decision_time(decision_time)
        work = frame.copy()
        work["_basic_time"] = cls._frame_times(work)
        completion_column = next(
            (name for name in ("is_complete", "complete") if name in work),
            None,
        )
        if completion_column is None and require_complete_flag:
            raise ValueError("live candle frame has no completion flag")
        if completion_column is not None:
            work = work[work[completion_column].eq(True)].copy()

        duration = pd.Timedelta(candle_duration)
        work = work[work["_basic_time"] + duration <= decision].copy()
        if work.empty:
            raise ValueError("no candle is completed by decision time")
        work.sort_values(
            "_basic_time",
            ascending=False,
            kind="stable",
            inplace=True,
        )
        if work["_basic_time"].duplicated().any():
            raise ValueError("candle frame contains duplicate times")
        if limit is not None:
            work = work.head(int(limit)).copy()

        for column in required:
            work[column] = pd.to_numeric(work[column], errors="coerce")
        numeric_values = work[list(required)].to_numpy(dtype=float)
        if not all(math.isfinite(float(value)) for value in numeric_values.ravel()):
            raise ValueError("candle frame contains invalid OHLC")

        work["time_jp_dt"] = work["_basic_time"]
        work["time_jp"] = work["_basic_time"].dt.strftime("%Y/%m/%d %H:%M:%S")
        work.drop(columns="_basic_time", inplace=True)
        work.reset_index(drop=True, inplace=True)
        return work

    @classmethod
    def latest_completed_close(
            cls,
            frame,
            decision_time,
            candle_duration,
    ):
        try:
            completed_df_r = cls.select_completed_df_r(
                frame,
                decision_time,
                candle_duration,
                limit=1,
                require_complete_flag=False,
            )
        except (TypeError, ValueError):
            return None
        value = float(completed_df_r.iloc[0]["close"])
        return value if math.isfinite(value) else None

    @classmethod
    def latest_observed_close(cls, frame):
        """Return the newest finite close, including a live forming candle."""
        if not isinstance(frame, pd.DataFrame) or frame.empty or "close" not in frame:
            return None
        try:
            work = frame.copy()
            work["_basic_time"] = cls._frame_times(work)
            work["close"] = pd.to_numeric(work["close"], errors="coerce")
            work.sort_values("_basic_time", inplace=True)
            value = float(work.iloc[-1]["close"])
        except (TypeError, ValueError, IndexError):
            return None
        return value if math.isfinite(value) else None

    @classmethod
    def frame_uses_hourly_candles(cls, frame):
        """Detect the existing H1-as-M30 fallback from its actual cadence."""
        if not isinstance(frame, pd.DataFrame) or len(frame) < 3:
            return False
        times = cls._frame_times(frame).drop_duplicates().sort_values()
        positive_diffs = times.diff().dropna()
        positive_diffs = positive_diffs[positive_diffs > pd.Timedelta(0)]
        if positive_diffs.empty:
            return False
        return positive_diffs.median() >= pd.Timedelta(minutes=50)

    def prepare_timeframe_dataframes(self):
        """Build explicit original/completed newest-first frames once."""
        require_complete_flag = self.analysis_mode == "live"

        self.m5_original_df_r = self.normalize_original_df_r(
            self.m5_original_df_r,
            self.decision_time,
            "m5_original_df_r",
        )
        self.m5_completed_df_r = self.select_completed_df_r(
            self.m5_original_df_r,
            self.decision_time,
            datetime.timedelta(minutes=5),
            require_complete_flag=require_complete_flag,
        )

        self.h1_original_df_r = self.normalize_original_df_r(
            self.h1_original_df_r,
            self.decision_time,
            "h1_original_df_r",
        )
        self.h1_completed_df_r = self.select_completed_df_r(
            self.h1_original_df_r,
            self.decision_time,
            datetime.timedelta(hours=1),
            require_complete_flag=require_complete_flag,
        )

        self.m30_original_df_r = self.normalize_original_df_r(
            self.m30_original_df_r,
            self.decision_time,
            "m30_original_df_r",
        )
        self.m30_uses_h1_fallback = bool(
            self.m30_uses_h1_fallback
            or self.frame_uses_hourly_candles(self.m30_original_df_r)
        )
        if self.m30_uses_h1_fallback:
            self.m30_completed_df_r = self.select_completed_df_r(
                self.m30_original_df_r,
                self.decision_time,
                datetime.timedelta(hours=1),
                require_complete_flag=require_complete_flag,
            )
        else:
            self.m30_completed_df_r = self.select_completed_df_r(
                self.m30_original_df_r,
                self.decision_time,
                datetime.timedelta(minutes=30),
                require_complete_flag=require_complete_flag,
            )

        if self.s5_original_df_r is not None:
            self.s5_original_df_r = self.normalize_original_df_r(
                self.s5_original_df_r,
                self.decision_time,
                "s5_original_df_r",
            )
            self.s5_completed_df_r = self.select_completed_df_r(
                self.s5_original_df_r,
                self.decision_time,
                datetime.timedelta(seconds=5),
                require_complete_flag=require_complete_flag,
            )

    @classmethod
    def peaks_match_completed(
            cls,
            peaks_class,
            completed_df_r,
            current_price,
            pair,
    ):
        """Check whether PeaksClass already used this exact completed history."""
        peak_frame = getattr(peaks_class, "analysis_df_r", None)
        if not isinstance(peak_frame, pd.DataFrame):
            return False
        try:
            same_price = math.isclose(
                float(peaks_class.current_price),
                float(current_price),
                rel_tol=0.0,
                abs_tol=1e-12,
            )
        except (AttributeError, TypeError, ValueError):
            return False
        if not same_price or getattr(getattr(peaks_class, "pair", None), "name", None) != pair.name:
            return False
        if len(peak_frame) != len(completed_df_r):
            return False
        try:
            peak_work = peak_frame.copy()
            completed_work = completed_df_r.copy()
            peak_work["_compare_time"] = cls._frame_times(peak_work)
            completed_work["_compare_time"] = cls._frame_times(completed_work)
            peak_work.sort_values("_compare_time", inplace=True)
            completed_work.sort_values("_compare_time", inplace=True)
            peak_work.reset_index(drop=True, inplace=True)
            completed_work.reset_index(drop=True, inplace=True)
        except (TypeError, ValueError):
            return False
        if not peak_work["_compare_time"].equals(completed_work["_compare_time"]):
            return False
        price_columns = ["open", "close", "high", "low"]
        peak_prices = peak_work[price_columns].apply(pd.to_numeric, errors="coerce")
        completed_prices = completed_work[price_columns].apply(
            pd.to_numeric,
            errors="coerce",
        )
        if peak_prices.isna().any().any() or completed_prices.isna().any().any():
            return False
        return bool((peak_prices - completed_prices).abs().le(1e-12).all().all())

    @classmethod
    def normalize_peak_metadata(cls, peaks_class, decision_time):
        """Add the explicit foot-count name and make recency decision-relative."""
        decision = cls.normalize_decision_time(decision_time)
        peaks_class.decision_time = decision
        peaks_class.time_hour = decision.hour
        for collection_name in (
            "peaks_original",
            "peaks_original_with_df",
            "skipped_peaks",
            "skipped_peaks_hard",
        ):
            for peak in getattr(peaks_class, collection_name, []):
                if isinstance(peak, dict) and "count" in peak:
                    peak.setdefault("foot_count", peak.get("count"))
        peaks_class.peaks_latest = [
            peak
            for peak in getattr(peaks_class, "peaks_original", [])
            if cls.normalize_decision_time(peak["latest_time_jp"])
            > decision - pd.Timedelta(hours=1)
        ]

    @classmethod
    def validate_completed_history_for_context(
            cls,
            completed_df_r,
            decision_time,
            candle_duration,
            required_bars,
            label,
            *,
            latest_boundary,
            allow_latest_known_closure=False,
            stale_is_integrity=False,
            require_market_open=False,
    ):
        """全解析共通の鮮度・必要本数・既知休場込み欠損検査。"""
        return candle_quality.validate_completed_history(
            completed_df_r,
            decision_time,
            candle_duration,
            required_bars,
            label,
            latest_boundary=latest_boundary,
            allow_latest_known_closure=allow_latest_known_closure,
            stale_is_integrity=stale_is_integrity,
            require_market_open=require_market_open,
        )

    @classmethod
    def build_decision_context_from_frames(
            cls,
            pair_name,
            decision_time,
            m5_frame,
            h1_frame,
            *,
            current_price,
            current_price_source,
            mode,
            require_complete_flags=False,
            m5_history=M5_ANALYSIS_BARS,
            h1_history=H1_ANALYSIS_BARS,
            peaks_class_factory=None,
            m5_peaks_class=None,
            h1_peaks_class=None,
    ):
        """Build the common causal analysis used by flip and future detectors."""
        decision = cls.normalize_decision_time(decision_time)
        pair = gene.currency_pair(pair_name)
        peaks_factory = peaks_class_factory or peaksClass.PeaksClass
        price = float(current_price)
        if not math.isfinite(price):
            raise ValueError("current price is invalid")

        m5_original_df_r = cls.normalize_original_df_r(
            m5_frame,
            decision,
            "m5_original_df_r",
        )
        m5_completed_df_r = cls.select_completed_df_r(
            m5_original_df_r,
            decision,
            datetime.timedelta(minutes=5),
            limit=m5_history,
            require_complete_flag=require_complete_flags,
        )
        m5_completed_df_r = cls.validate_completed_history_for_context(
            m5_completed_df_r,
            decision,
            datetime.timedelta(minutes=5),
            m5_history,
            "M5",
            latest_boundary="M5",
            stale_is_integrity=str(mode) == "inspection",
            require_market_open=True,
        )
        m5_quality = dict(
            m5_completed_df_r.attrs.get("candle_quality") or {}
        )
        if not cls.peaks_match_completed(
                m5_peaks_class,
                m5_completed_df_r,
                price,
                pair,
        ):
            with contextlib.redirect_stdout(io.StringIO()):
                m5_peaks_class = peaks_factory(
                    m5_original_df_r,
                    "M5",
                    price,
                    pair,
                    completed_df_r=m5_completed_df_r,
                    decision_time=decision,
                )
        m5_peaks_class.completed_df_r = m5_completed_df_r
        m5_peaks_class.analysis_df_r = m5_completed_df_r
        if not m5_peaks_class.peaks_original:
            raise ValueError("no M5 peak")
        cls.normalize_peak_metadata(m5_peaks_class, decision)

        h1_original_df_r = None
        h1_completed_df_r = None
        h1_last_end = None
        h1_quality = {}
        if h1_frame is None:
            h1_peaks_class = m5_peaks_class
            h1_shapes = {
                -1: {"valid": False, "reason": "missing_h1_frame"},
                1: {"valid": False, "reason": "missing_h1_frame"},
            }
        else:
            h1_original_df_r = cls.normalize_original_df_r(
                h1_frame,
                decision,
                "h1_original_df_r",
            )
            h1_completed_df_r = cls.select_completed_df_r(
                h1_original_df_r,
                decision,
                datetime.timedelta(hours=1),
                limit=h1_history,
                require_complete_flag=require_complete_flags,
            )
            h1_completed_df_r = cls.validate_completed_history_for_context(
                h1_completed_df_r,
                decision,
                datetime.timedelta(hours=1),
                h1_history,
                "H1",
                latest_boundary="H1",
                allow_latest_known_closure=True,
                stale_is_integrity=str(mode) == "inspection",
            )
            h1_quality = dict(
                h1_completed_df_r.attrs.get("candle_quality") or {}
            )
            if not cls.peaks_match_completed(
                    h1_peaks_class,
                    h1_completed_df_r,
                    price,
                    pair,
            ):
                with contextlib.redirect_stdout(io.StringIO()):
                    h1_peaks_class = peaks_factory(
                        h1_original_df_r,
                        "H1",
                        price,
                        pair,
                        completed_df_r=h1_completed_df_r,
                        decision_time=decision,
                    )
            h1_peaks_class.completed_df_r = h1_completed_df_r
            h1_peaks_class.analysis_df_r = h1_completed_df_r
            h1_shapes = {
                direction: latest_two_candle_shape_context(
                    h1_completed_df_r,
                    decision,
                    pair,
                    direction=direction,
                    timeframe_minutes=60,
                )
                for direction in (-1, 1)
            }
            cls.normalize_peak_metadata(h1_peaks_class, decision)
            h1_last_end = (
                pd.Timestamp(h1_completed_df_r.iloc[0]["time_jp_dt"])
                + pd.Timedelta(hours=1)
            )

        newest_peak = m5_peaks_class.peaks_original[0]
        m5_foot_shape = foot_count2_shape_context(
            m5_completed_df_r,
            newest_peak,
            decision,
            pair,
            timeframe_minutes=5,
        )
        rsi_info = {
            f"rsi_{number}": (
                m5_completed_df_r.iloc[number - 1].get("RSI")
                if len(m5_completed_df_r) >= number
                else None
            )
            for number in (1, 2, 3)
        }
        return CandleDecisionContext(
            pair_name=str(pair_name).upper(),
            pair=pair,
            mode=str(mode),
            decision_time=decision,
            current_price=price,
            current_price_source=str(current_price_source),
            latest_completed_m5_close=float(m5_completed_df_r.iloc[0]["close"]),
            m5_original_df_r=m5_original_df_r,
            h1_original_df_r=h1_original_df_r,
            m5_completed_df_r=m5_completed_df_r,
            h1_completed_df_r=h1_completed_df_r,
            m5_peaks_class=m5_peaks_class,
            h1_peaks_class=h1_peaks_class,
            newest_m5_peak=newest_peak,
            m5_foot_count2_shape=m5_foot_shape,
            h1_latest_two_shapes=h1_shapes,
            rsi_info=rsi_info,
            data_quality_validated=h1_completed_df_r is not None,
            m5_missing_bars=int(m5_quality.get("missing_bars") or 0),
            h1_missing_bars=int(h1_quality.get("missing_bars") or 0),
            m5_missing_ratio=float(m5_quality.get("missing_ratio") or 0.0),
            h1_missing_ratio=float(h1_quality.get("missing_ratio") or 0.0),
            m5_last_end=(
                pd.Timestamp(m5_completed_df_r.iloc[0]["time_jp_dt"])
                + pd.Timedelta(minutes=5)
            ),
            h1_last_end=h1_last_end,
        )

    def build_basic_analysis(self):
        """Build and retain the common strategy context exactly once per CA."""
        try:
            self.decision_context = self.build_decision_context_from_frames(
                self.pair,
                self.decision_time,
                self.m5_original_df_r,
                self.h1_original_df_r,
                current_price=self.current_price,
                current_price_source=self.current_price_source,
                mode=self.analysis_mode,
                require_complete_flags=self.analysis_mode == "live",
                m5_peaks_class=self.peaks_class,
                h1_peaks_class=self.peaks_class_hour,
            )
            self.basic_analysis = self.decision_context
            self.sync_peaks_from_basic_analysis()
            self.decision_context_error = None
            self.decision_context_error_type = None
            self.decision_context_not_ready = False
        except (KeyError, TypeError, ValueError) as error:
            # 因果contextを作れない場合は、旧Peaksへフォールバックさせない。
            self.decision_context = None
            self.basic_analysis = None
            self.decision_context_error = str(error)
            self.decision_context_error_type = type(error)
            self.decision_context_not_ready = bool(
                isinstance(error, candle_quality.CandleHistoryNotReady)
                or str(error).startswith(
                    (
                        "no candle is completed",
                    )
                )
            )
        return self.decision_context

    def sync_peaks_from_basic_analysis(self):
        """因果contextをM5/H1 Peaksの正本として互換参照も同期する。"""
        context = self.basic_analysis
        if context is None:
            return

        canonical_m5_peaks = context.m5_peaks_class
        m5_meta_needs_rebuild = (
            getattr(self, "peaks_class", None) is not canonical_m5_peaks
            or getattr(
                getattr(self, "candle_meta_class", None),
                "peaks_class",
                None,
            ) is not canonical_m5_peaks
            or getattr(
                getattr(self, "candle_meta_class", None),
                "completed_df_r",
                None,
            ) is not context.m5_completed_df_r
        )
        canonical_m5_meta = (
            CandleMeta(canonical_m5_peaks, "M5")
            if m5_meta_needs_rebuild
            else self.candle_meta_class
        )

        canonical_h1_peaks = context.h1_peaks_class
        h1_meta_needs_rebuild = (
            getattr(self, "peaks_class_hour", None) is not canonical_h1_peaks
            or getattr(
                getattr(self, "candle_meta_class_hour", None),
                "peaks_class",
                None,
            ) is not canonical_h1_peaks
            or getattr(
                getattr(self, "candle_meta_class_hour", None),
                "completed_df_r",
                None,
            ) is not context.h1_completed_df_r
        )
        canonical_h1_meta = (
            CandleMeta(canonical_h1_peaks, "H1")
            if h1_meta_needs_rebuild
            else self.candle_meta_class_hour
        )

        self.peaks_class = canonical_m5_peaks
        self.candle_meta_class = canonical_m5_meta
        self.peaks_class_hour = canonical_h1_peaks
        self.candle_meta_class_hour = canonical_h1_meta

    def require_basic_analysis(self):
        """新規解析が旧Peaksへフォールバックしないための共通入口。"""
        context = self.basic_analysis
        if context is None:
            detail = self.decision_context_error or "unknown context error"
            error_type = self.decision_context_error_type
            if (
                    isinstance(error_type, type)
                    and issubclass(error_type, candle_quality.CandleHistoryError)
            ):
                raise error_type(detail)
            if self.decision_context_not_ready:
                raise candle_quality.CandleHistoryNotReady(detail)
            raise ValueError("basic_analysis is unavailable: " + detail)

        # 互換属性を誰かが差し替えても、解析前に正本へ戻して分裂を残さない。
        self.sync_peaks_from_basic_analysis()
        context_time = self.normalize_decision_time(context.decision_time)
        if context_time != self.normalize_decision_time(self.decision_time):
            raise ValueError("basic_analysis decision_time mismatch")
        if str(context.pair_name).upper() != str(self.pair).upper():
            raise ValueError("basic_analysis pair mismatch")
        if not getattr(context, "data_quality_validated", False):
            raise ValueError("basic_analysis data quality is not validated")
        if context.h1_completed_df_r is None:
            raise ValueError("basic_analysis H1 history is unavailable")
        if (
                self.peaks_class is not context.m5_peaks_class
                or self.peaks_class_hour is not context.h1_peaks_class
        ):
            raise RuntimeError("basic_analysis Peaks identity mismatch")
        return context

    @staticmethod
    def refresh_cached_peak_price(peaks_class, current_price):
        """Refresh the only peak fields that depend on the current M5 price."""
        peaks_class.current_price = current_price
        peaks_class.gap_price_and_latest_turn_peak_abs = abs(
            peaks_class.latest_peak_price - current_price
        )
        for collection_name in (
            "peaks_original",
            "peaks_original_with_df",
            "skipped_peaks",
            "skipped_peaks_hard",
        ):
            for peak in getattr(peaks_class, collection_name, []):
                if isinstance(peak, dict):
                    peak["latest_price"] = current_price

    def update_s5_df(self, target_time_jp=0):
        # パラメータの準備
        param = {"granularity": "S5", "count": 5}

        if target_time_jp == 0:
            # 現在時刻でやる場合
            s5_df_res = self.base_oa.InstrumentsCandles_multi_exe(self.pair, param, 1)
        else:
            # 指定の時刻でやる場合
            euro_time_datetime = target_time_jp - datetime.timedelta(hours=9)
            param["to"] = f"{euro_time_datetime.isoformat()}.000000000Z"
            s5_df_res = self.base_oa.InstrumentsCandles_exe(self.pair, param)

        # エラーチェック
        if s5_df_res['error'] == -1:
            print("error Candle")
            return -1

        # データフレームを時間降順で保存
        observation_time = (
            pd.Timestamp.now(tz=JST).floor("s").tz_localize(None)
            if target_time_jp == 0
            else self.normalize_decision_time(target_time_jp)
        )
        self.s5_original_df_r = self.normalize_original_df_r(
            s5_df_res['data'],
            observation_time,
            "s5_original_df_r",
        )
        self.s5_completed_df_r = self.select_completed_df_r(
            self.s5_original_df_r,
            observation_time,
            datetime.timedelta(seconds=5),
            require_complete_flag=target_time_jp == 0,
        )

    def get_date_df(self, target_time_jp):
        # データを取得する
        if target_time_jp == 0:
            # ■■■nowでやる場合（リアルトレード環境がメイン）
            # 5分足のデータ
            d5_df_res = self.base_oa.InstrumentsCandles_multi_exe(self.pair,
                                                                  {"granularity": "M5", "count": self.m5_need_df_num},
                                                                  1)  # 時間昇順(直近が最後尾）
            if d5_df_res['error'] == -1:
                print("error Candle")
                notice.line_send("5分ごと調査最初のデータフレーム取得に失敗（エラー）")
                return -1
            else:
                d5_df_latest_bottom = d5_df_res['data']
            self.m5_original_df_r = self.normalize_original_df_r(
                d5_df_latest_bottom,
                self.decision_time,
                "m5_original_df_r",
            ).head(self.need_df_num).copy()

            # 60分足のデータ
            h1_df_res = self.base_oa.InstrumentsCandles_multi_exe(self.pair,
                                                                   {"granularity": "H1", "count": self.h1_need_df_num},
                                                                   1)  # 時間昇順(直近が最後尾）
            if h1_df_res['error'] == -1:
                print("error Candle")
                notice.line_send("60分ごと調査最初のデータフレーム取得に失敗（エラー）")
                return -1
            else:
                h1_df_latest_bottom = h1_df_res['data']
            self.h1_original_df_r = self.normalize_original_df_r(
                h1_df_latest_bottom,
                self.decision_time,
                "h1_original_df_r",
            ).head(self.need_df_num).copy()

            # 5秒足で
            s5_df_res = self.base_oa.InstrumentsCandles_multi_exe(self.pair,
                                                                  {"granularity": "S5", "count": 5},
                                                                  1)  # 時間昇順(直近が最後尾）
            if s5_df_res['error'] == -1:
                print("error Candle")
                notice.line_send("5分ごと調査最初のデータフレーム取得に失敗（エラー）")
                return -1
            else:
                s5_df_latest_bottom = s5_df_res['data']
            self.s5_original_df_r = self.normalize_original_df_r(
                s5_df_latest_bottom,
                self.decision_time,
                "s5_original_df_r",
            )

            # 30分足のデータ
            d30_df_res = self.base_oa.InstrumentsCandles_multi_exe(self.pair,
                                                                   {"granularity": "M30", "count": self.need_df_num},
                                                                   1)  # 時間昇順(直近が最後尾）
            if d30_df_res['error'] == -1:
                print("error Candle")
                notice.line_send("30分ごと調査最初のデータフレーム取得に失敗（エラー）")
                return -1
            else:
                m30_df_latest_bottom = d30_df_res['data']
            self.m30_original_df_r = self.normalize_original_df_r(
                m30_df_latest_bottom,
                self.decision_time,
                "m30_original_df_r",
            ).head(self.need_df_num).copy()

            # ★★現在価格の取得（API）
            self.current_price_by_df = self.latest_completed_close(
                self.m5_original_df_r,
                self.decision_time,
                datetime.timedelta(minutes=5),
            )
            try:
                price_dic = self.base_oa.NowPrice_exe(self.pair)
            except Exception:
                price_dic = {"error": -1}
            try:
                quote_price = float(price_dic["data"]["mid"])
            except (KeyError, TypeError, ValueError):
                quote_price = None
            if (
                    isinstance(price_dic, dict)
                    and price_dic.get("error") == 0
                    and quote_price is not None
                    and math.isfinite(quote_price)
            ):
                self.current_price = quote_price
                self.current_price_source = "live_quote"
            else:
                # 軽微なquote障害では通知せず、同じ取得周期の最新足へ退避する。
                fallback_price = self.latest_observed_close(self.s5_original_df_r)
                if fallback_price is not None:
                    self.current_price = fallback_price
                    self.current_price_source = "live_s5"
                else:
                    fallback_price = self.latest_observed_close(self.m5_original_df_r)
                    if fallback_price is None:
                        return -1
                    self.current_price = fallback_price
                    self.current_price_source = "live_m5"
            if self.current_price_by_df is None:
                self.current_price_by_df = self.current_price

        else:
            # ■■■指定の時刻でやる場合
            jp_time = target_time_jp
            euro_time_datetime = jp_time - datetime.timedelta(hours=9)
            euro_time_datetime_iso = str(euro_time_datetime.isoformat()) + ".000000000Z"  # ISOで文字型。.0z付き）

            # ５分足データ
            param = {"granularity": "M5", "count": self.m5_need_df_num, "to": euro_time_datetime_iso}
            d5_df_res = self.base_oa.InstrumentsCandles_exe(self.pair, param) # 時間昇順(直近が最後尾）
            if d5_df_res['error'] == -1:
                print("error Candle")
                notice.line_send("5分ごと調査最初のデータフレーム取得に失敗（エラー）")
                return -1
            else:
                d5_df_latest_bottom = d5_df_res['data']
            self.m5_original_df_r = self.normalize_original_df_r(
                d5_df_latest_bottom,
                self.decision_time,
                "m5_original_df_r",
            ).head(self.need_df_num).copy()

            # 60分足のデータ
            param = {"granularity": "H1", "count": self.h1_need_df_num, "to": euro_time_datetime_iso}
            h1_df_res = self.base_oa.InstrumentsCandles_exe(self.pair, param) # 時間昇順(直近が最後尾）
            if h1_df_res['error'] == -1:
                print("error Candle")
                notice.line_send("60分ごと調査最初のデータフレーム取得に失敗（エラー）")
                return -1
            else:
                h1_df_latest_bottom = h1_df_res['data']
            self.h1_original_df_r = self.normalize_original_df_r(
                h1_df_latest_bottom,
                self.decision_time,
                "h1_original_df_r",
            ).head(self.need_df_num).copy()

            # 最短の５秒足も取得しておく
            param = {"granularity": "S5", "count": 5, "to": euro_time_datetime_iso}
            s5_df_res = self.base_oa.InstrumentsCandles_exe(self.pair, param)  # 時間昇順(直近が最後尾）
            if s5_df_res['error'] == -1:
                print("error Candle")
                notice.line_send("60分ごと調査最初のデータフレーム取得に失敗（エラー）")
                return -1
            else:
                s5_df_latest_bottom = s5_df_res['data']
            self.s5_original_df_r = self.normalize_original_df_r(
                s5_df_latest_bottom,
                self.decision_time,
                "s5_original_df_r",
            )

            # 最短の30分足も取得しておく
            param = {"granularity": "M30", "count": self.need_df_num, "to": euro_time_datetime_iso}
            d30_df_res = self.base_oa.InstrumentsCandles_exe(self.pair, param)  # 時間昇順(直近が最後尾）
            if d30_df_res['error'] == -1:
                print("error Candle")
                notice.line_send("30分ごと調査最初のデータフレーム取得に失敗（エラー）")
                return -1
            else:
                m30_df_latest_bottom = d30_df_res['data']
            self.m30_original_df_r = self.normalize_original_df_r(
                m30_df_latest_bottom,
                self.decision_time,
                "m30_original_df_r",
            ).head(self.need_df_num).copy()
            # print(self.m30_original_df_r.head(3))

            # ★★★currentPriceの取得（検証では判断時刻までの完成足だけを使う）
            self.current_price_by_df = self.latest_completed_close(
                self.m5_original_df_r,
                self.decision_time,
                datetime.timedelta(minutes=5),
            )
            inspection_s5_price = self.latest_completed_close(
                self.s5_original_df_r,
                self.decision_time,
                datetime.timedelta(seconds=5),
            )
            if inspection_s5_price is not None:
                self.current_price = inspection_s5_price
                self.current_price_source = "inspection_s5"
            elif self.current_price_by_df is not None:
                self.current_price = self.current_price_by_df
                self.current_price_source = "inspection_m5"
            else:
                return -1

class CandleMeta:
    def __init__(self, peaks_class, granularity):
        """
        target_time_jpまでの時間を取得する
        """
        # データ入れる用
        self.completed_df_r = peaks_class.completed_df_r
        self.peaks_class = peaks_class
        self.pair = peaks_class.pair
        self.u = peaks_class.pair.round_keta
        # 初期値
        self.ave_move = 0
        self.ave_move_for_lc = 0
        self.dependence_large_body_criteria = self.pair.pips_to_price(10)

        # データを取得する(5分足系）
        if granularity == "M5":
            self.recent_fluctuation_range = 0  # 指定ではなく、計算で算出される。直近N足分以内での最大変動幅（最高値ー最低値）round済み
            self.fluctuation_gap = self.pair.pips_to_price(30)  # 急変動とみなす1足の変動は30pips以上。（1足でPeakの変動ではない）
            self.fluctuation_count = 3  # 3カウント以下でfluctuation_gapが起きた場合、急変動とみなす
            self.is_big_move_candle = False
        elif granularity == "H1":
            self.recent_fluctuation_range = 0  # 指定ではなく、計算で算出される。直近N足分以内での最大変動幅（最高値ー最低値）round済み
            self.fluctuation_gap = self.pair.pips_to_price(30)  # 急変動とみなす1足の変動は30pips以上。（1足でPeakの変動ではない）
            self.fluctuation_count = 3  # 3カウント以下でfluctuation_gapが起きた場合、急変動とみなす
            self.is_big_move_candle = False
        elif granularity == "M30":
            self.recent_fluctuation_range = 0  # 指定ではなく、計算で算出される。直近N足分以内での最大変動幅（最高値ー最低値）round済み
            self.fluctuation_gap = self.pair.pips_to_price(30)  # 急変動とみなす1足の変動は30pips以上。（1足でPeakの変動ではない）
            self.fluctuation_count = 3  # 3カウント以下でfluctuation_gapが起きた場合、急変動とみなす
            self.is_big_move_candle = False

        #
        self.cal_move_size()

    def cal_move_size(self):
        # ■データフレームの状態で、サイズ感を色々求める
        filtered_df_r = self.completed_df_r[:65]  # 直近4時間の場合、12×4 48
        sorted_df = filtered_df_r.sort_values(by='body_abs', ascending=False)
        max_high = sorted_df["inner_high"].max()
        min_low = sorted_df['inner_low'].min()
        self.recent_fluctuation_range = round(max_high - min_low, self.u)
        self.ave_move = filtered_df_r.head(5)["highlow"].mean()
        self.ave_move_for_lc = self.ave_move * 1.6
        # print("   ＜稼働範囲サマリ＞")
        # print("    検出範囲", filtered_df_r.iloc[0]["time_jp"], "-", filtered_df_r.iloc[-1]['time_jp'])
        # print("    最大値、最小値", max_high, min_low, "差分")
        # print("    平均キャンドル長", filtered_df_r.head(5)["highlow"].mean())
        # print("    提唱LC幅", self.ave_move_for_lc)
        # print("    狭いレンジか？", self.peaks_class.hyper_range)
        # print(t6, "最大足(最高-最低),", sorted_df.iloc[0]['time_jp'], sorted_df.iloc[0]['highlow'])
        # print(t6, "最小足(最高-最低),", sorted_df.iloc[-1]['time_jp'], sorted_df.iloc[-1]['highlow'])
        # print(t6, "平均(最高-最低)", sorted_df['highlow'].mean())
        # print(t6, "最大足(Body),", sorted_df.iloc[0]['time_jp'], sorted_df.iloc[0]['body_abs'])
        # print(t6, "最小足(Body),", sorted_df.iloc[-1]['time_jp'], sorted_df.iloc[-1]['body_abs'])
        # print(t6, "平均(Body)", sorted_df['body_abs'].mean())

        # ■ピーク5個の中で突発的できわめて大きな変動がある場合（雇用統計とか、、、）基本は戻る動きとみる？（それとも静観・・・？）
        if len(self.peaks_class.peaks_original) == 1:
            # 極まれに範囲外になる。
            target_peak = self.peaks_class.peaks_original[0]
            # print("特殊事態（Peaksが少なすぎる）")
            gene.print_arr(self.peaks_class.peaks_original)
        else:
            target_peak = self.peaks_class.peaks_original[1]  # ビッグムーブ検査の対象となるのはひとつ前のピーク
        if self.peaks_class.peaks_original[0]['count'] == 2:
            # 重複オーダーとなる可能性をここで防止するため、ビッグムーブの判定はLatestカウントが2の場合のみ
            if target_peak['gap'] >= self.fluctuation_gap and target_peak['count'] <= self.fluctuation_count:
                # 変動が大きく、カウントは3まで（だらだらと長く進んでいる変動は突発的なビッグムーブではない）
                self.peaks_class.is_big_move_peak = True
                # tk.line_send("ビッグムーブ観測　cal_move_size関数@classPeaks")
            else:
                self.peaks_class.is_big_move_peak = False

        # ■ピークの直近5個分の平均値等を求める
        filtered_peaks = self.peaks_class.peaks_original[:5]
        peaks_ave = sum(item["gap"] for item in filtered_peaks) / len(filtered_peaks)
        # 最大値と最小値
        max_index, max_peak = max(enumerate(filtered_peaks[:]), key=lambda x: x[1]["peak"])
        min_index, min_peak = min(enumerate(filtered_peaks[:]), key=lambda x: x[1]["peak"])
        # 最大変動と最小変動
        max_gap_index, max_gap = max(enumerate(filtered_peaks[:]), key=lambda x: x[1]["gap"])
        min_gap_index, min_gap = min(enumerate(filtered_peaks[:]), key=lambda x: x[1]["gap"])
        other_max_gap_items = [item for item in filtered_peaks[:] if item != max_gap]
        # print(t6, "検出範囲ピーク",)
        # gene.print_arr(filtered_peaks, 6)
        # print(t6, peaks_ave)
        # print(t6, "変動幅検証関数　ここまで")
        # print(t6, "最大ギャップ", max_gap)
        # print(t6, other_max_gap_items)

        # ■足の長さが急変動があるかを確認
        filtered_df_r = self.completed_df_r[:5]
        sorted_df = filtered_df_r.sort_values(by='body_abs', ascending=False)
        max_body = sorted_df["body_abs"].max()
        if max_body >= self.dependence_large_body_criteria:
            self.is_big_move_candle = True
        else:
            self.is_big_move_candle = False
        # print("    大きな変動があるか？", self.is_big_move_candle)

    def cal_move_ave(self, times):
        """
        直近の動き幅のtimes倍の数値を返却する(直接LC Rangeに利用することを想定）
        """
        # ■データフレームの状態で、サイズ感を色々求める
        filtered_df_r = self.completed_df_r[:65]
        self.ave_move = filtered_df_r.head(9)["highlow"].mean()
        self.ave_move_for_lc = self.ave_move * times
        return self.ave_move_for_lc

