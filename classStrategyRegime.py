# 最新更新日時: 2026-08-29 15:38 JST

from pathlib import Path

import pandas as pd

import fGeneric as gene
import tokens as tk


class StrategyRegime:
    """Build a past-only market/performance snapshot for one currency pair."""

    TRADE_WINDOWS = (15, 30, 60)
    REGIME_NEUTRAL = "NEUTRAL"
    REGIME_RANGE = "RANGE"
    REGIME_UP_TREND = "UP_TREND"
    REGIME_DOWN_TREND = "DOWN_TREND"
    REGIME_UP_TREND_START = "UP_TREND_START"
    REGIME_DOWN_TREND_START = "DOWN_TREND_START"

    RANGE_EFFICIENCY_MAX = 0.20
    RANGE_EXPANSION_MAX = 1.10
    TREND_EFFICIENCY_MIN = 0.40
    TREND_EXPANSION_MIN = 0.90
    TREND_START_EFFICIENCY_MIN = 0.60
    TREND_START_EXPANSION_MIN = 1.20

    def __init__(self, pair, mode="live", history_path=None):
        self.pair = pair
        self.p = gene.currency_pair(pair)
        self.mode = mode
        self.history_path = Path(
            history_path or (tk.history_folder_path + "history.csv")
        )
        self._inspection_results = []
        self._history_cache = pd.DataFrame()
        self._history_mtime_ns = None
        self.latest_snapshot = self.empty_snapshot()

    def empty_snapshot(self):
        return {
            "pair": self.pair,
            "mode": self.mode,
            "decision_time": None,
            "trade_source": (
                "inspection" if self.mode == "inspection" else "live_history"
            ),
            "all": self._empty_direction_summary(),
            "buy": self._empty_direction_summary(),
            "sell": self._empty_direction_summary(),
            "market": self._empty_market_summary(),
            "monitor_only": False,
        }

    @classmethod
    def _empty_direction_summary(cls):
        return {
            "available_decisions": 0,
            **{
                f"last_{window}": {
                    "requested": window,
                    "decided": 0,
                    "wins": 0,
                    "win_rate": None,
                    "average_pips": None,
                    "total_pips": 0,
                }
                for window in cls.TRADE_WINDOWS
            },
        }

    def current_snapshot(self, decision_time, candle_analysis=None):
        decision_dt = self._to_timestamp(decision_time)
        trades = self._past_decided_trades(decision_dt)
        snapshot = {
            "pair": self.pair,
            "mode": self.mode,
            "decision_time": self._format_time(decision_dt),
            "trade_source": (
                "inspection" if self.mode == "inspection" else "live_history"
            ),
            "all": self._direction_summary(trades),
            "buy": self._direction_summary(trades[trades["direction"] == 1]),
            "sell": self._direction_summary(trades[trades["direction"] == -1]),
            "market": self._market_summary(candle_analysis, decision_dt),
            "monitor_only": False,
        }
        self.latest_snapshot = snapshot
        return snapshot

    @staticmethod
    def order_context(snapshot):
        if not snapshot:
            return {}
        context = {
            "regime_monitor_only": snapshot.get("monitor_only", True),
            "regime_decision_time": snapshot.get("decision_time"),
        }
        for side in ("all", "buy", "sell"):
            side_summary = snapshot.get(side, {})
            for window in StrategyRegime.TRADE_WINDOWS:
                summary = side_summary.get(f"last_{window}", {})
                prefix = f"regime_{side}_last_{window}"
                context[f"{prefix}_decided"] = summary.get("decided")
                context[f"{prefix}_win_rate"] = summary.get("win_rate")
                context[f"{prefix}_average_pips"] = summary.get("average_pips")
        market = snapshot.get("market", {})
        for key in (
            "regime",
            "trend_direction",
            "is_range",
            "is_trend",
            "is_trend_start",
            "regime_reason",
            "range_expansion_3_vs_12",
            "range_expansion_6_vs_12",
            "completed_h1_bars",
            "avg_h1_range_pips_24",
            "avg_h1_range_pips_72",
            "avg_h1_range_pips_available",
            "direction_efficiency_available",
            "bb_range_pips_latest",
        ):
            context[f"regime_{key}"] = market.get(key)
        for hours in (3, 6, 12):
            summary = market.get(f"window_{hours}", {})
            for key in (
                "net_pips",
                "travel_pips",
                "signed_efficiency",
                "direction_efficiency",
                "average_range_pips",
            ):
                context[f"regime_{hours}h_{key}"] = summary.get(key)
        return context

    def record_inspection_result(self, result_row):
        """Queue a simulated result; expose it only after its close time."""
        if self.mode != "inspection" or not result_row:
            return
        result = result_row.get("actual_order_result") or result_row.get("order_result")
        if result not in ("tp", "lc"):
            return
        close_time = self._to_timestamp(result_row.get("close_time"))
        if close_time is None:
            return
        try:
            direction = int(result_row.get("direction"))
            pips = float(result_row.get("actual_res"))
        except (TypeError, ValueError):
            return
        self._inspection_results.append(
            {
                "close_time": close_time,
                "direction": direction,
                "result_pips": pips,
                "win": result == "tp",
            }
        )

    def _past_decided_trades(self, decision_dt):
        if decision_dt is None:
            return self._empty_trades()
        if self.mode == "inspection":
            if not self._inspection_results:
                return self._empty_trades()
            rows = pd.DataFrame(self._inspection_results)
        else:
            rows = self._load_live_history()
        if rows.empty:
            return self._empty_trades()
        return (
            rows[rows["close_time"] <= decision_dt]
            .sort_values("close_time")
            .reset_index(drop=True)
        )

    def _load_live_history(self):
        try:
            stat = self.history_path.stat()
        except OSError:
            return self._empty_trades()
        if self._history_mtime_ns == stat.st_mtime_ns:
            return self._history_cache
        try:
            rows = pd.read_csv(self.history_path)
        except (OSError, ValueError, pd.errors.ParserError):
            return self._empty_trades()
        required = {
            "pair", "tradeID", "take_price", "end_time", "units", "pl_per_units"
        }
        if not required.issubset(rows.columns):
            return self._empty_trades()
        for column in ("tradeID", "take_price", "units", "pl_per_units"):
            rows[column] = pd.to_numeric(rows[column], errors="coerce")
        rows["close_time"] = pd.to_datetime(rows["end_time"], errors="coerce")
        rows = rows[
            rows["pair"].eq(self.pair)
            & rows["tradeID"].gt(0)
            & rows["take_price"].gt(0)
            & rows["units"].ne(0)
            & rows["close_time"].notna()
            & rows["pl_per_units"].notna()
        ].copy()
        rows = rows.sort_values("close_time").drop_duplicates("tradeID", keep="last")
        rows["direction"] = rows["units"].apply(lambda value: 1 if value > 0 else -1)
        rows["result_pips"] = rows["pl_per_units"]
        rows["win"] = rows["result_pips"] > 0
        self._history_cache = rows[
            ["close_time", "direction", "result_pips", "win"]
        ].reset_index(drop=True)
        self._history_mtime_ns = stat.st_mtime_ns
        return self._history_cache

    def _direction_summary(self, trades):
        output = self._empty_direction_summary()
        output["available_decisions"] = len(trades)
        for window in self.TRADE_WINDOWS:
            selected = trades.tail(window)
            decided = len(selected)
            wins = int(selected["win"].sum()) if decided else 0
            output[f"last_{window}"] = {
                "requested": window,
                "decided": decided,
                "wins": wins,
                "win_rate": wins / decided if decided else None,
                "average_pips": (
                    float(selected["result_pips"].mean()) if decided else None
                ),
                "total_pips": (
                    float(selected["result_pips"].sum()) if decided else 0
                ),
            }
        return output

    def _market_summary(self, candle_analysis, decision_dt):
        if candle_analysis is None or decision_dt is None:
            return self._empty_market_summary()
        h1_completed_df_r = getattr(
            candle_analysis,
            "h1_completed_df_r",
            None,
        )
        if h1_completed_df_r is None or h1_completed_df_r.empty:
            return self._empty_market_summary()
        frame = h1_completed_df_r.copy()
        time_column = "time_jp_dt" if "time_jp_dt" in frame.columns else "time_jp"
        if time_column not in frame.columns:
            return self._empty_market_summary()
        frame["regime_time"] = pd.to_datetime(frame[time_column], errors="coerce")
        frame = frame[
            frame["regime_time"] <= decision_dt - pd.Timedelta(hours=1)
        ].sort_values("regime_time")
        if frame.empty:
            return self._empty_market_summary()
        for column in ("open", "close", "high", "low", "bb_range"):
            if column in frame.columns:
                frame[column] = pd.to_numeric(frame[column], errors="coerce")
        factor = 1 / self.p.pips_to_price(1)
        absolute_close_move = frame["close"].diff().abs() * factor
        h1_range = (frame["high"] - frame["low"]) * factor
        body = (frame["close"] - frame["open"]).abs() * factor
        window_3 = self._window_summary(frame, 3, factor)
        window_6 = self._window_summary(frame, 6, factor)
        window_12 = self._window_summary(frame, 12, factor)
        regime = self._classify_market_regime(window_3, window_6, window_12)
        return {
            "completed_h1_bars": len(frame),
            "oldest_h1_time": self._format_time(frame.iloc[0]["regime_time"]),
            "latest_h1_time": self._format_time(frame.iloc[-1]["regime_time"]),
            "avg_h1_range_pips_24": self._mean_range(frame.tail(24), factor),
            "avg_h1_range_pips_72": self._mean_range(frame.tail(72), factor),
            "avg_h1_range_pips_available": self._safe_float(h1_range.mean()),
            "avg_h1_body_pips_available": self._safe_float(body.mean()),
            "direction_efficiency_available": self._direction_efficiency(
                frame, absolute_close_move, factor
            ),
            "bb_range_pips_latest": self._latest_bb_range(frame, factor),
            "window_3": window_3,
            "window_6": window_6,
            "window_12": window_12,
            **regime,
        }

    @classmethod
    def _empty_market_summary(cls):
        return {
            "regime": cls.REGIME_NEUTRAL,
            "trend_direction": 0,
            "is_range": False,
            "is_trend": False,
            "is_trend_start": False,
            "regime_reason": "insufficient completed H1 candles",
            "window_3": cls._empty_window_summary(3),
            "window_6": cls._empty_window_summary(6),
            "window_12": cls._empty_window_summary(12),
        }

    @staticmethod
    def _empty_window_summary(hours):
        return {
            "requested_bars": hours,
            "bars": 0,
            "net_pips": None,
            "travel_pips": None,
            "signed_efficiency": None,
            "direction_efficiency": None,
            "average_range_pips": None,
        }

    @classmethod
    def _window_summary(cls, frame, hours, factor):
        if len(frame) < hours:
            return cls._empty_window_summary(hours)
        selected = frame.tail(hours)
        path = pd.concat(
            [
                pd.Series([selected.iloc[0]["open"]]),
                selected["close"].reset_index(drop=True),
            ],
            ignore_index=True,
        )
        travel_pips = path.diff().abs().sum() * factor
        net_pips = (
            selected.iloc[-1]["close"] - selected.iloc[0]["open"]
        ) * factor
        signed_efficiency = net_pips / travel_pips if travel_pips else 0
        average_range_pips = (
            (selected["high"] - selected["low"]) * factor
        ).mean()
        return {
            "requested_bars": hours,
            "bars": len(selected),
            "net_pips": cls._safe_float(net_pips),
            "travel_pips": cls._safe_float(travel_pips),
            "signed_efficiency": cls._safe_float(signed_efficiency),
            "direction_efficiency": cls._safe_float(abs(signed_efficiency)),
            "average_range_pips": cls._safe_float(average_range_pips),
        }

    @classmethod
    def _classify_market_regime(cls, window_3, window_6, window_12):
        if window_12["bars"] < 12:
            return {
                "regime": cls.REGIME_NEUTRAL,
                "trend_direction": 0,
                "is_range": False,
                "is_trend": False,
                "is_trend_start": False,
                "regime_reason": "fewer than 12 completed H1 candles",
            }

        range_12 = window_12["average_range_pips"]
        expansion_3 = cls._safe_ratio(
            window_3["average_range_pips"],
            range_12,
        )
        expansion_6 = cls._safe_ratio(
            window_6["average_range_pips"],
            range_12,
        )
        efficiency_3 = window_3["direction_efficiency"]
        efficiency_6 = window_6["direction_efficiency"]
        direction_3 = cls._sign(window_3["signed_efficiency"])
        direction_6 = cls._sign(window_6["signed_efficiency"])

        if (
            efficiency_6 is not None
            and efficiency_6 >= cls.TREND_EFFICIENCY_MIN
            and expansion_6 is not None
            and expansion_6 >= cls.TREND_EXPANSION_MIN
            and direction_6 != 0
        ):
            regime = (
                cls.REGIME_UP_TREND
                if direction_6 == 1
                else cls.REGIME_DOWN_TREND
            )
            return {
                "regime": regime,
                "trend_direction": direction_6,
                "is_range": False,
                "is_trend": True,
                "is_trend_start": False,
                "regime_reason": (
                    f"6H efficiency={efficiency_6:.3f}, "
                    f"range expansion={expansion_6:.3f}"
                ),
                "range_expansion_3_vs_12": expansion_3,
                "range_expansion_6_vs_12": expansion_6,
            }

        if (
            efficiency_3 is not None
            and efficiency_3 >= cls.TREND_START_EFFICIENCY_MIN
            and expansion_3 is not None
            and expansion_3 >= cls.TREND_START_EXPANSION_MIN
            and direction_3 != 0
        ):
            regime = (
                cls.REGIME_UP_TREND_START
                if direction_3 == 1
                else cls.REGIME_DOWN_TREND_START
            )
            return {
                "regime": regime,
                "trend_direction": direction_3,
                "is_range": False,
                "is_trend": False,
                "is_trend_start": True,
                "regime_reason": (
                    f"3H efficiency={efficiency_3:.3f}, "
                    f"range expansion={expansion_3:.3f}"
                ),
                "range_expansion_3_vs_12": expansion_3,
                "range_expansion_6_vs_12": expansion_6,
            }

        if (
            efficiency_6 is not None
            and efficiency_6 <= cls.RANGE_EFFICIENCY_MAX
            and expansion_6 is not None
            and expansion_6 <= cls.RANGE_EXPANSION_MAX
        ):
            return {
                "regime": cls.REGIME_RANGE,
                "trend_direction": 0,
                "is_range": True,
                "is_trend": False,
                "is_trend_start": False,
                "regime_reason": (
                    f"6H efficiency={efficiency_6:.3f}, "
                    f"range expansion={expansion_6:.3f}"
                ),
                "range_expansion_3_vs_12": expansion_3,
                "range_expansion_6_vs_12": expansion_6,
            }

        return {
            "regime": cls.REGIME_NEUTRAL,
            "trend_direction": 0,
            "is_range": False,
            "is_trend": False,
            "is_trend_start": False,
            "regime_reason": (
                f"6H efficiency={efficiency_6:.3f}, "
                f"range expansion={expansion_6:.3f}"
            ),
            "range_expansion_3_vs_12": expansion_3,
            "range_expansion_6_vs_12": expansion_6,
        }

    @staticmethod
    def _safe_ratio(numerator, denominator):
        if numerator is None or denominator in (None, 0):
            return None
        return float(numerator) / float(denominator)

    @staticmethod
    def _sign(value):
        if value is None or value == 0:
            return 0
        return 1 if value > 0 else -1

    @staticmethod
    def _mean_range(frame, factor):
        if frame.empty:
            return None
        return StrategyRegime._safe_float(
            ((frame["high"] - frame["low"]) * factor).mean()
        )

    @staticmethod
    def _direction_efficiency(frame, absolute_close_move, factor):
        travel = absolute_close_move.sum()
        if not travel or len(frame) < 2:
            return None
        net = abs(frame.iloc[-1]["close"] - frame.iloc[0]["open"]) * factor
        return StrategyRegime._safe_float(net / travel)

    @staticmethod
    def _latest_bb_range(frame, factor):
        if "bb_range" not in frame.columns:
            return None
        values = frame["bb_range"].dropna()
        if values.empty:
            return None
        return StrategyRegime._safe_float(values.iloc[-1] * factor)

    @staticmethod
    def _empty_trades():
        return pd.DataFrame(
            columns=["close_time", "direction", "result_pips", "win"]
        )

    @staticmethod
    def _to_timestamp(value):
        if value is None:
            return None
        try:
            timestamp = pd.Timestamp(value)
        except (TypeError, ValueError):
            return None
        return None if pd.isna(timestamp) else timestamp

    @staticmethod
    def _format_time(value):
        if value is None or pd.isna(value):
            return None
        return pd.Timestamp(value).strftime("%Y/%m/%d %H:%M:%S")

    @staticmethod
    def _safe_float(value):
        if value is None or pd.isna(value):
            return None
        return float(value)
