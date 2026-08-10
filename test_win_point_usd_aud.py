"""AUD_USD の「勝てる折り返し地点」を先に探す検証。

注文ロジックは使わず、M5 の最新ピーク (peaks[0]) の count が 2 の地点で
そのピーク方向へ成行エントリーする追随モード、またはピーク0の起点を逆方向へ
S5終値でブレイクしてから入る失敗ブレイクモードを検証する。エントリー後
60 分の S5 を使い、スプレッド込みで指定利確幅に到達できたかを目的変数にする。
利確幅は固定値のほか、直近 N 本の確定 M5 の平均高安幅に連動させられる。

出力:
  win_points_*.csv       全候補と成否、RSI、抵抗/支持の特徴量
  win_only_*.csv         指定した利確幅への到達地点だけ
  group_ranking_*.csv    特徴量グループ別ランキング

例:
  python test_win_point_usd_aud.py --start 2026-01-01 --end 2026-06-30
  python test_win_point_usd_aud.py --start 2026-01-01 --end 2026-06-30 \
      --tp-mode recent-m5-range --tp-lookback 6 --tp-multiplier 1.0
  python test_win_point_usd_aud.py --start "2026-07-01 00:00" \
      --end "2026-07-15 00:00" --existing-data
"""

from __future__ import annotations

import argparse
import datetime as dt
import math
from pathlib import Path

import numpy as np
import pandas as pd

import classOanda
import fGeneric as gene
import send_notice as notice
import tokens as tk


PAIR = "AUD_USD"
DEFAULT_START = dt.datetime(2024, 6, 24)
DEFAULT_END = dt.datetime(2025, 6, 24)
M5_HISTORY = 181
H1_HISTORY = 240

# 検証条件（3通貨共通）
TP_MODE = "recent-m5-range"
TP_LOOKBACK = 6
TP_MULTIPLIER = 3.0
TP_MIN_PIPS = 0.1
TP_MAX_PIPS = 999.0
RR = 1.3
HORIZON_MINUTES = 60
SPREAD_PIPS = 0.8

# エントリー方式。既存3ファイルは peak0-follow のままにし、
# 失敗ブレイク専用ラッパーから peak0-failure-break を指定する。
ENTRY_MODE = "peak0-follow"
FAILURE_BREAK_MAX_WAIT_SECONDS = 60
FAILURE_BREAK_BUFFER_PIPS = 0.0
FAILURE_BREAK_REFERENCE = "body"
FAILURE_BREAK_CONFIRMATION = "s5-close"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            f"{PAIR}のpeaks[0].count==2地点を起点に、"
            "固定または可変TPへの到達傾向を調べる。"
        )
    )
    parser.add_argument("--start", default=DEFAULT_START.isoformat(" "))
    parser.add_argument("--end", default=DEFAULT_END.isoformat(" "))
    parser.add_argument("--tp-pips", type=float, default=8.0)
    parser.add_argument(
        "--tp-mode",
        choices=["fixed", "recent-m5-range"],
        default=TP_MODE,
        help="fixed: --tp-pips、recent-m5-range: 直近M5平均高安幅×倍率",
    )
    parser.add_argument("--tp-lookback", type=int, default=TP_LOOKBACK)
    parser.add_argument("--tp-multiplier", type=float, default=TP_MULTIPLIER)
    parser.add_argument(
        "--tp-min-pips",
        type=float,
        default=TP_MIN_PIPS,
        help="可変TPの下限",
    )
    parser.add_argument(
        "--tp-max-pips",
        type=float,
        default=TP_MAX_PIPS,
        help="可変TPの上限",
    )
    parser.add_argument(
        "--horizon-minutes",
        type=int,
        default=HORIZON_MINUTES,
    )
    parser.add_argument("--spread-pips", type=float, default=SPREAD_PIPS)
    parser.add_argument(
        "--rr",
        type=float,
        default=RR,
        help="reward/risk。LC幅 = TP幅 / RR",
    )
    parser.add_argument(
        "--existing-data",
        action="store_true",
        help="キャッシュだけを使用し、不足時はエラーにする",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(tk.folder_path),
    )
    parser.add_argument(
        "--min-group-size",
        type=int,
        default=30,
        help="ランキングに残すグループの最小件数",
    )
    return parser.parse_args()


def cache_paths(start: dt.datetime, end: dt.datetime) -> dict[str, Path]:
    name = f"{PAIR}_{start:%Y%m%d%H%M%S}_{end:%Y%m%d%H%M%S}"
    folder = Path(tk.folder_path)
    return {
        "M5": folder / f"m5_{name}.csv",
        "H1": folder / f"h1_{name}.csv",
        "S5": folder / f"s5_{name}.csv",
    }


def normalize(df: pd.DataFrame) -> pd.DataFrame:
    df["time_jp_dt"] = pd.to_datetime(
        df["time_jp"],
        format="%Y/%m/%d %H:%M:%S",
    )
    if not df["time_jp_dt"].is_monotonic_increasing:
        df.sort_values("time_jp_dt", inplace=True)
        df.reset_index(drop=True, inplace=True)
    return df


def fetch_candles(
    oa: classOanda.Oanda,
    granularity: str,
    start: dt.datetime,
    end: dt.datetime,
) -> pd.DataFrame:
    seconds = {"S5": 5, "M5": 300, "H1": 3600}[granularity]
    rows = math.ceil((end - start).total_seconds() / seconds) + 5
    count = min(rows, 5000)
    loops = max(1, math.ceil(rows / count))
    params = {
        "granularity": granularity,
        "count": count,
        "to": gene.time_to_euro_iso(end),
    }
    response = oa.InstrumentsCandles_multi_exe(
        PAIR,
        params,
        loops,
        start_time=start,
        end_time=end,
    )
    if response.get("error") == -1:
        raise RuntimeError(f"OANDA data fetch failed: {granularity}")
    df = normalize(response["data"])
    return df[df["time_jp_dt"].between(start, end)].reset_index(drop=True)


def load_data(
    start: dt.datetime,
    end: dt.datetime,
    existing_only: bool,
) -> dict[str, pd.DataFrame]:
    paths = cache_paths(start, end)
    history_from = start - dt.timedelta(hours=max(H1_HISTORY, 16))
    future_to = end + dt.timedelta(minutes=60)
    required = {
        "M5": (history_from, end),
        "H1": (history_from, end),
        "S5": (start, future_to),
    }
    data: dict[str, pd.DataFrame] = {}
    missing = []
    for frame, path in paths.items():
        if path.exists():
            usecols = (
                ["time_jp", "close", "high", "low"]
                if frame == "S5"
                else None
            )
            data[frame] = normalize(pd.read_csv(path, usecols=usecols))
        else:
            missing.append(frame)
    if not missing:
        print(
            f"[CACHE] {PAIR}: M5/H1/S5の既存キャッシュを使用します。"
            "OANDA APIは使用しません。"
        )
    if missing and existing_only:
        raise FileNotFoundError(
            "Missing cache(s): " + ", ".join(str(paths[x]) for x in missing)
        )
    if missing:
        oa = classOanda.Oanda(tk.accountIDl, tk.access_tokenl, "live")
        for frame in missing:
            fetch_from, fetch_to = required[frame]
            print(f"Fetch {PAIR} {frame}: {fetch_from} -> {fetch_to}")
            fetched = fetch_candles(oa, frame, fetch_from, fetch_to)
            paths[frame].parent.mkdir(parents=True, exist_ok=True)
            fetched.drop(columns="time_jp_dt").to_csv(
                paths[frame], index=False, encoding="utf-8"
            )
            if frame == "S5":
                fetched = fetched[
                    ["time_jp", "close", "high", "low", "time_jp_dt"]
                ]
            data[frame] = fetched
    return data


def send_inspection_notice(message: str) -> None:
    """通知失敗で長時間の検証本体を停止させない。"""
    try:
        notice.send_inspection_notice(message)
    except Exception as error:
        print("[Discord notification error]", error)


def send_progress_notices(
    pair_name: str,
    target_time: pd.Timestamp,
    next_notice_time: pd.Timestamp,
    completed: int,
    total: int,
    process_started: dt.datetime,
) -> pd.Timestamp:
    while target_time >= next_notice_time:
        elapsed_minutes = (dt.datetime.now() - process_started).total_seconds() / 60
        message = (
            f"{pair_name} win-point inspection 2か月分進捗 "
            f"到達={next_notice_time:%Y-%m-%d %H:%M:%S} "
            f"候補={completed}/{total} "
            f"経過={elapsed_minutes:.2f}分"
        )
        print(message)
        send_inspection_notice(message)
        next_notice_time = next_notice_time + pd.DateOffset(months=2)
    return next_notice_time


def add_rsi(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    df = df.copy()
    close = pd.to_numeric(df["close"], errors="coerce")
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    df["RSI_calc"] = (100 - (100 / (1 + rs))).fillna(50)
    return df


def candidate_indices(m5: pd.DataFrame, start: dt.datetime, end: dt.datetime) -> np.ndarray:
    """既存PeaksClassと同じ定義で peaks[0].count==2 を直接抽出する。

    PeaksClass の count は「同方向の価格点数」で、方向変化数ではない。
    したがってcount=2は、直近の確定M5間で方向が変わった最初の地点。
    """
    middle = pd.to_numeric(m5["middle_price"], errors="coerce").to_numpy()
    direction = np.sign(np.diff(middle))
    direction[direction == 0] = 1
    exact_two = np.zeros(len(m5), dtype=bool)
    # 判断 index=i では i-1 までが確定。diff[i-2] が最新方向で、
    # diff[i-3] から反転していれば、最新ピークの価格点数は2。
    exact_two[3:] = direction[1:-1] != direction[:-2]
    time_gap = m5["time_jp_dt"].diff()
    consecutive = np.zeros(len(m5), dtype=bool)
    consecutive[3:] = (
        time_gap.iloc[2:-1].eq(pd.Timedelta(minutes=5)).to_numpy()
        & time_gap.iloc[1:-2].eq(pd.Timedelta(minutes=5)).to_numpy()
    )
    times = m5["time_jp_dt"]
    in_period = times.between(start, end, inclusive="left").to_numpy()
    return np.flatnonzero(exact_two & consecutive & in_period)


def peak_context_at_candidate(
    m5: pd.DataFrame,
    index: int,
    pair,
) -> tuple[dict, dict] | None:
    """重いPeaksClass再生成なしで、最新・直前ピークの基本値を作る。"""
    if index < 3:
        return None
    middle = pd.to_numeric(
        m5.iloc[max(0, index - M5_HISTORY) : index]["middle_price"],
        errors="coerce",
    ).to_numpy()
    if len(middle) < 3 or np.isnan(middle[-3:]).any():
        return None
    latest_direction = 1 if middle[-1] - middle[-2] >= 0 else -1
    previous_direction = 1 if middle[-2] - middle[-3] >= 0 else -1
    if latest_direction == previous_direction:
        return None

    previous_run_changes = 1
    cursor = len(middle) - 3
    while cursor > 0:
        older_direction = (
            1 if middle[cursor] - middle[cursor - 1] >= 0 else -1
        )
        if older_direction != previous_direction:
            break
        previous_run_changes += 1
        cursor -= 1

    latest_row = m5.iloc[index - 1]
    pivot_row = m5.iloc[index - 2]
    previous_oldest_row = m5.iloc[index - 2 - previous_run_changes]
    if latest_direction == 1:
        latest_gap = abs(
            float(latest_row["inner_high"]) - float(pivot_row["inner_low"])
        )
    else:
        latest_gap = abs(
            float(latest_row["inner_low"]) - float(pivot_row["inner_high"])
        )
    if previous_direction == 1:
        previous_gap = abs(
            float(pivot_row["inner_high"])
            - float(previous_oldest_row["inner_low"])
        )
    else:
        previous_gap = abs(
            float(pivot_row["inner_low"])
            - float(previous_oldest_row["inner_high"])
        )

    latest_peak = {
        "count": 2,
        "direction": latest_direction,
        "gap": pair.round_price(latest_gap),
        "rsi": latest_row.get("RSI"),
        # PeaksClass が gap 算出に使うローソク本体側の起点。
        # count=2 の失敗ブレイクでは、この価格を逆方向へ抜けたかを見る。
        "start_price": (
            float(pivot_row["inner_low"])
            if latest_direction == 1
            else float(pivot_row["inner_high"])
        ),
        "start_time": pivot_row["time_jp_dt"],
        "latest_price": (
            float(latest_row["inner_high"])
            if latest_direction == 1
            else float(latest_row["inner_low"])
        ),
    }
    previous_peak = {
        "count": previous_run_changes + 1,
        "direction": previous_direction,
        "gap": pair.round_price(previous_gap),
        "rsi": pivot_row.get("RSI"),
    }
    return latest_peak, previous_peak


def h1_turning_points(h1: pd.DataFrame) -> pd.DataFrame:
    """確定済みH1だけで利用可能になる方向転換点を作る。

    行 i の方向が行 i-1 から変わった時、転換価格は i-1 の価格とする。
    この転換を知れるのは行 i のH1足が確定した時刻なので、
    confirmed_time = 行 i の開始時刻 + 1時間とする。
    """
    price = pd.to_numeric(h1["middle_price"], errors="coerce")
    direction = np.sign(price.diff()).replace(0, np.nan).ffill()
    previous_direction = direction.shift(1)
    turn_confirmed = (
        direction.notna()
        & previous_direction.notna()
        & direction.ne(previous_direction)
    )
    strength = price.diff().abs().rolling(3, min_periods=1).sum()
    points = pd.DataFrame(
        {
            "time_jp_dt": h1["time_jp_dt"].shift(1)[turn_confirmed].to_numpy(),
            "confirmed_time": (
                h1.loc[turn_confirmed, "time_jp_dt"] + pd.Timedelta(hours=1)
            ).to_numpy(),
            "middle_price": price.shift(1)[turn_confirmed].to_numpy(),
            "direction": previous_direction[turn_confirmed].to_numpy(),
            "peak_strength": strength.shift(1)[turn_confirmed].to_numpy(),
        }
    )
    return points.reset_index(drop=True)


def resistance_features(
    points: pd.DataFrame,
    decision_time: pd.Timestamp,
    entry: float,
    direction: int,
    pair,
) -> dict:
    past = points[points["confirmed_time"] <= decision_time].tail(H1_HISTORY)
    if past.empty:
        return {}
    tolerance = pair.pips_to_price(3)
    work = past.copy()
    work["bucket"] = (work["middle_price"] / tolerance).round().astype(int)
    groups = (
        work.groupby("bucket")
        .agg(
            line_price=("middle_price", "median"),
            line_count=("middle_price", "size"),
            line_total_strength=("peak_strength", "sum"),
            line_latest_time=("time_jp_dt", "max"),
        )
        .reset_index(drop=True)
    )
    groups["signed_distance_pips"] = (
        (groups["line_price"] - entry) * direction / pair.pip_value
    )
    ahead = groups[groups["signed_distance_pips"] >= 0].sort_values(
        "signed_distance_pips"
    )
    behind = groups[groups["signed_distance_pips"] < 0].sort_values(
        "signed_distance_pips", ascending=False
    )

    def values(prefix: str, rows: pd.DataFrame) -> dict:
        if rows.empty:
            return {
                f"{prefix}_distance_pips": np.nan,
                f"{prefix}_count": 0,
                f"{prefix}_total_strength_pips": 0.0,
            }
        row = rows.iloc[0]
        return {
            f"{prefix}_price": row["line_price"],
            f"{prefix}_distance_pips": abs(row["signed_distance_pips"]),
            f"{prefix}_count": int(row["line_count"]),
            f"{prefix}_total_strength_pips": (
                row["line_total_strength"] / pair.pip_value
            ),
            f"{prefix}_latest_time": row["line_latest_time"],
        }

    return {**values("h1_ahead", ahead), **values("h1_behind", behind)}


class S5PathInspector:
    """S5時刻を二分探索し、候補ごとに必要な約1時間だけを評価する。"""

    def __init__(self, s5: pd.DataFrame, pair):
        self.pair = pair
        self.times = s5["time_jp_dt"].to_numpy(dtype="datetime64[ns]", copy=False)
        self.closes = pd.to_numeric(s5["close"], errors="coerce").to_numpy(
            dtype=float, copy=False
        )
        self.highs = pd.to_numeric(s5["high"], errors="coerce").to_numpy(
            dtype=float, copy=False
        )
        self.lows = pd.to_numeric(s5["low"], errors="coerce").to_numpy(
            dtype=float, copy=False
        )

    def find_failure_breakout(
        self,
        decision_time: pd.Timestamp,
        peak_direction: int,
        peak_start_price: float,
        decision_mid_price: float,
        max_wait_seconds: int,
        buffer_pips: float,
    ) -> dict:
        """ピーク0起点の逆抜けを、確定したS5終値だけで検出する。

        S5行の時刻は足の開始時刻なので、終値を知れる5秒後を確認・
        エントリー時刻とする。同じS5足をその後のTP/LC判定には使わない。
        """
        decision_time = pd.Timestamp(decision_time)
        decision_np = np.datetime64(decision_time, "ns")
        wait_end = decision_time + pd.Timedelta(seconds=max_wait_seconds)
        wait_end_np = np.datetime64(wait_end, "ns")
        start_i = int(np.searchsorted(self.times, decision_np, side="left"))
        end_i = int(np.searchsorted(self.times, wait_end_np, side="left"))
        trade_direction = -int(peak_direction)
        buffer_price = self.pair.pips_to_price(buffer_pips)
        breakout_level = float(
            peak_start_price + trade_direction * buffer_price
        )
        base = {
            "entry_mode": "peak0-failure-break",
            "peak_direction": int(peak_direction),
            "breakout_direction": trade_direction,
            "peak_start_price": float(peak_start_price),
            "peak_start_reference": FAILURE_BREAK_REFERENCE,
            "breakout_level": breakout_level,
            "breakout_max_wait_seconds": int(max_wait_seconds),
            "breakout_buffer_pips": float(buffer_pips),
            "breakout_confirmation": FAILURE_BREAK_CONFIRMATION,
        }
        already_broken = (
            decision_mid_price > breakout_level
            if trade_direction == 1
            else decision_mid_price < breakout_level
        )
        if already_broken:
            return {
                **base,
                "breakout_triggered": False,
                "breakout_skip_reason": "already_broken_at_decision",
            }
        if start_i >= len(self.times) or start_i >= end_i:
            return {
                **base,
                "breakout_triggered": False,
                "breakout_skip_reason": "no_s5_during_wait",
            }

        times = self.times[start_i:end_i]
        closes = self.closes[start_i:end_i]
        valid = np.isfinite(closes)
        if trade_direction == 1:
            crossed = valid & (closes > breakout_level)
        else:
            crossed = valid & (closes < breakout_level)
        reached = np.flatnonzero(crossed)
        if not reached.size:
            return {
                **base,
                "breakout_triggered": False,
                "breakout_skip_reason": "not_broken_within_wait",
            }

        trigger_i = int(reached[0])
        trigger_bar_time = pd.Timestamp(times[trigger_i])
        entry_time = trigger_bar_time + pd.Timedelta(seconds=5)
        mid_entry = float(closes[trigger_i])
        overshoot_pips = (
            (mid_entry - breakout_level)
            * trade_direction
            / self.pair.pip_value
        )
        return {
            **base,
            "breakout_triggered": True,
            "breakout_skip_reason": None,
            "breakout_trigger_bar_time": trigger_bar_time,
            "breakout_trigger_time": entry_time,
            "breakout_delay_seconds": float(
                (entry_time - decision_time).total_seconds()
            ),
            "breakout_trigger_mid_close": mid_entry,
            "breakout_overshoot_pips": float(overshoot_pips),
            "entry_time": entry_time,
            "entry_mid_price": mid_entry,
        }

    def inspect(
        self,
        decision_time: pd.Timestamp,
        direction: int,
        signal_reference_price: float,
        tp_pips: float,
        lc_pips: float,
        horizon_minutes: int,
        spread_pips: float,
    ) -> dict:
        decision_np = np.datetime64(decision_time, "ns")
        end_time = decision_time + pd.Timedelta(minutes=horizon_minutes)
        end_np = np.datetime64(end_time, "ns")
        start_i = int(np.searchsorted(self.times, decision_np, side="left"))
        end_i = int(np.searchsorted(self.times, end_np, side="left"))
        if start_i >= len(self.times) or start_i >= end_i:
            return {
                "has_s5_path": False,
                "path_skip_reason": "no_s5_after_decision",
                "tp_hit": False,
                "lc_hit": False,
            }

        first_time = pd.Timestamp(self.times[start_i])
        if first_time >= decision_time + pd.Timedelta(minutes=5):
            return {
                "has_s5_path": False,
                "path_skip_reason": "s5_start_gap",
                "tp_hit": False,
                "lc_hit": False,
            }

        times = self.times[start_i:end_i]
        high = self.highs[start_i:end_i]
        low = self.lows[start_i:end_i]
        close = self.closes[start_i:end_i]
        # 判断時点で既知の直前確定M5終値を成行時のmid近似値にする。
        # S5は無取引時に行自体が欠けるため、最初のS5 openは使わない。
        mid_entry = float(signal_reference_price)
        half_spread = self.pair.pips_to_price(spread_pips / 2)
        actual_entry = mid_entry + direction * half_spread

        if direction == 1:
            executable_favorable = high - half_spread
            executable_adverse = low - half_spread
            plus = (executable_favorable - actual_entry) / self.pair.pip_value
            minus = (executable_adverse - actual_entry) / self.pair.pip_value
        else:
            executable_favorable = low + half_spread
            executable_adverse = high + half_spread
            plus = (actual_entry - executable_favorable) / self.pair.pip_value
            minus = (actual_entry - executable_adverse) / self.pair.pip_value

        tp_touch = plus >= tp_pips
        lc_touch = minus <= -lc_pips
        reached = np.flatnonzero(tp_touch | lc_touch)
        hit_i = int(reached[0]) if reached.size else None
        last_before_end_is_near = (
            pd.Timestamp(times[-1]) >= end_time - pd.Timedelta(minutes=5)
        )
        first_after_end_is_near = (
            end_i < len(self.times)
            and pd.Timestamp(self.times[end_i])
            < end_time + pd.Timedelta(minutes=5)
        )
        has_full_horizon = last_before_end_is_near or first_after_end_is_near
        if hit_i is None and not has_full_horizon:
            return {
                "has_s5_path": False,
                "path_skip_reason": "incomplete_horizon",
                "tp_hit": False,
                "lc_hit": False,
                "s5_path_rows": len(times),
            }

        both_same_s5 = bool(
            hit_i is not None and tp_touch[hit_i] and lc_touch[hit_i]
        )
        if hit_i is None:
            trade_result = "timeout"
            tp_hit = False
            lc_hit = False
            exit_i = len(times) - 1
            if direction == 1:
                actual_exit = float(close[exit_i] - half_spread)
                result_pips = (
                    actual_exit - actual_entry
                ) / self.pair.pip_value
            else:
                actual_exit = float(close[exit_i] + half_spread)
                result_pips = (
                    actual_entry - actual_exit
                ) / self.pair.pip_value
        elif both_same_s5:
            # S5 OHLCだけでは同一足内の順序が不明なため保守的にLC扱い。
            trade_result = "both_same_s5_lc_assumed"
            tp_hit = False
            lc_hit = True
            exit_i = hit_i
            result_pips = -lc_pips
            actual_exit = actual_entry - direction * self.pair.pips_to_price(
                lc_pips
            )
        elif tp_touch[hit_i]:
            trade_result = "tp"
            tp_hit = True
            lc_hit = False
            exit_i = hit_i
            result_pips = tp_pips
            actual_exit = actual_entry + direction * self.pair.pips_to_price(
                tp_pips
            )
        else:
            trade_result = "lc"
            tp_hit = False
            lc_hit = True
            exit_i = hit_i
            result_pips = -lc_pips
            actual_exit = actual_entry - direction * self.pair.pips_to_price(
                lc_pips
            )

        reach_time = (
            pd.Timestamp(times[hit_i]) if hit_i is not None else pd.NaT
        )
        elapsed_seconds = (
            (reach_time - decision_time).total_seconds()
            if hit_i is not None
            else np.nan
        )
        before_exit = slice(0, exit_i + 1)
        return {
            "has_s5_path": True,
            "path_skip_reason": None,
            "signal_reference_price": signal_reference_price,
            "mid_entry_price": mid_entry,
            "actual_entry_price": actual_entry,
            "actual_exit_price": actual_exit,
            "trade_result": trade_result,
            "tp_hit": tp_hit,
            "lc_hit": lc_hit,
            "both_hit_same_s5": both_same_s5,
            "first_reach_time": reach_time,
            "first_reach_elapsed_seconds": elapsed_seconds,
            "tp_hit_time": reach_time if tp_hit else pd.NaT,
            "tp_elapsed_seconds": elapsed_seconds if tp_hit else np.nan,
            "lc_hit_time": reach_time if lc_hit else pd.NaT,
            "lc_elapsed_seconds": elapsed_seconds if lc_hit else np.nan,
            "trade_result_pips": float(result_pips),
            "result_r": float(result_pips / lc_pips),
            "max_favorable_pips": float(np.nanmax(plus)),
            "max_adverse_pips": float(np.nanmin(minus)),
            "max_favorable_pips_before_exit": float(
                np.nanmax(plus[before_exit])
            ),
            "max_adverse_pips_before_exit": float(
                np.nanmin(minus[before_exit])
            ),
            "has_full_horizon": has_full_horizon,
            "s5_path_rows": len(times),
        }


def target_pips_at(
    m5: pd.DataFrame,
    index: int,
    args: argparse.Namespace,
    pair,
) -> dict:
    """判断時点より前の確定足だけでTPを決める。"""
    lookback = max(1, int(args.tp_lookback))
    completed = m5.iloc[max(0, index - lookback) : index]
    ranges = (
        pd.to_numeric(completed["high"], errors="coerce")
        - pd.to_numeric(completed["low"], errors="coerce")
    ) / pair.pip_value
    average_range = float(ranges.mean()) if len(ranges) else np.nan
    median_range = float(ranges.median()) if len(ranges) else np.nan
    total_range = (
        (
            float(pd.to_numeric(completed["high"], errors="coerce").max())
            - float(pd.to_numeric(completed["low"], errors="coerce").min())
        )
        / pair.pip_value
        if len(completed)
        else np.nan
    )
    if args.tp_mode == "recent-m5-range":
        raw_target = average_range * args.tp_multiplier
        effective_target = float(
            np.clip(raw_target, args.tp_min_pips, args.tp_max_pips)
        )
    else:
        raw_target = float(args.tp_pips)
        effective_target = raw_target
    lc_pips = effective_target / args.rr
    return {
        "tp_mode": args.tp_mode,
        "tp_pips": effective_target,
        "lc_pips": lc_pips,
        "rr": args.rr,
        "tp_raw_pips": raw_target,
        "tp_was_clipped": not np.isclose(effective_target, raw_target),
        "tp_lookback": lookback,
        "tp_multiplier": args.tp_multiplier,
        "recent_m5_avg_range_pips": average_range,
        "recent_m5_median_range_pips": median_range,
        "recent_m5_total_range_pips": total_range,
    }


def add_bins(rows: pd.DataFrame) -> pd.DataFrame:
    rows = rows.copy()
    rows["direction_name"] = np.where(rows["direction"] == 1, "BUY", "SELL")
    rows["m5_rsi_bin"] = pd.cut(
        rows["m5_rsi"],
        [-np.inf, 30, 40, 50, 60, 70, np.inf],
        labels=["<30", "30-39", "40-49", "50-59", "60-69", "70+"],
        right=False,
    )
    rows["h1_rsi_bin"] = pd.cut(
        rows["h1_rsi"],
        [-np.inf, 35, 45, 55, 65, np.inf],
        labels=["<35", "35-44", "45-54", "55-64", "65+"],
        right=False,
    )
    rows["ahead_distance_bin"] = pd.cut(
        rows["h1_ahead_distance_pips"],
        [-np.inf, 8, 15, 30, np.inf],
        labels=["0-7", "8-14", "15-29", "30+"],
        right=False,
    ).astype(object).fillna("no_line")
    rows["ahead_strength_bin"] = pd.cut(
        rows["h1_ahead_total_strength_pips"],
        [-np.inf, 10, 25, 50, np.inf],
        labels=["weak", "medium", "strong", "very_strong"],
        right=False,
    ).astype(object).fillna("no_line")
    rows["peak_gap_bin"] = pd.cut(
        rows["peak_gap_pips"],
        [-np.inf, 3, 6, 10, np.inf],
        labels=["<3", "3-5", "6-9", "10+"],
        right=False,
    )
    rows["tp_pips_bin"] = pd.cut(
        rows["tp_pips"],
        [-np.inf, 5, 8, 11, 15, np.inf],
        labels=["<5", "5-7", "8-10", "11-14", "15+"],
        right=False,
    )
    if "peak_to_previous_gap_ratio" in rows:
        rows["peak_ratio_bin"] = pd.cut(
            rows["peak_to_previous_gap_ratio"],
            [-np.inf, 0.25, 0.5, 1, 2, np.inf],
            labels=["<0.25", "0.25-0.49", "0.50-0.99", "1.00-1.99", "2.00+"],
            right=False,
        )
    if "previous_peak_count" in rows:
        rows["previous_peak_count_bin"] = pd.cut(
            pd.to_numeric(rows["previous_peak_count"], errors="coerce"),
            [-np.inf, 3, 5, 8, np.inf],
            labels=["2", "3-4", "5-7", "8+"],
            right=False,
        )
    if "breakout_delay_seconds" in rows:
        rows["breakout_delay_bin"] = pd.cut(
            pd.to_numeric(rows["breakout_delay_seconds"], errors="coerce"),
            [-np.inf, 16, 31, 61, np.inf],
            labels=["5-15s", "20-30s", "35-60s", "60s+"],
            right=False,
        )
    return rows


def make_ranking(rows: pd.DataFrame, min_size: int) -> pd.DataFrame:
    rows = rows.copy()
    rows["is_timeout"] = rows["trade_result"].eq("timeout")
    dimensions = [
        ["direction_name", "m5_rsi_bin"],
        ["direction_name", "h1_rsi_bin"],
        ["direction_name", "ahead_distance_bin"],
        ["direction_name", "ahead_strength_bin"],
        ["tp_mode", "tp_pips_bin"],
        ["direction_name", "m5_rsi_bin", "ahead_distance_bin"],
        ["direction_name", "peak_gap_bin", "ahead_strength_bin", "tp_pips_bin"],
    ]
    if "breakout_delay_bin" in rows:
        dimensions.extend(
            [
                ["direction_name", "breakout_delay_bin"],
                ["direction_name", "peak_ratio_bin"],
                ["direction_name", "previous_peak_count_bin"],
                [
                    "direction_name",
                    "peak_ratio_bin",
                    "previous_peak_count_bin",
                ],
                [
                    "direction_name",
                    "m5_rsi_bin",
                    "ahead_strength_bin",
                    "breakout_delay_bin",
                ],
            ]
        )
    base_expectancy_r = float(rows["result_r"].mean())
    tables = []
    for columns in dimensions:
        grouped = (
            rows.groupby(columns, observed=True, dropna=False)
            .agg(
                samples=("tp_hit", "size"),
                wins=("tp_hit", "sum"),
                losses=("lc_hit", "sum"),
                timeouts=("is_timeout", "sum"),
                win_rate=("tp_hit", "mean"),
                expectancy_r=("result_r", "mean"),
                avg_result_pips=("trade_result_pips", "mean"),
                avg_mfe_pips=("max_favorable_pips", "mean"),
                avg_mae_pips=("max_adverse_pips", "mean"),
                median_tp_seconds=("tp_elapsed_seconds", "median"),
                median_first_reach_seconds=(
                    "first_reach_elapsed_seconds",
                    "median",
                ),
            )
            .reset_index()
        )
        grouped = grouped[grouped["samples"] >= min_size].copy()
        if grouped.empty:
            continue
        resolved = grouped["wins"] + grouped["losses"]
        grouped["resolved_win_rate"] = np.where(
            resolved > 0,
            grouped["wins"] / resolved,
            np.nan,
        )
        grouped["group_type"] = " + ".join(columns)
        grouped["group"] = grouped[columns].astype(str).agg(" / ".join, axis=1)
        # 小標本の偶然を抑えるため、全体100件分を事前分布とする縮約期待R。
        grouped["ranking_score"] = (
            grouped["expectancy_r"] * grouped["samples"]
            + base_expectancy_r * 100
        ) / (grouped["samples"] + 100)
        tables.append(grouped)
    if not tables:
        return pd.DataFrame()
    ranking = pd.concat(tables, ignore_index=True, sort=False)
    ranking = ranking.sort_values(
        ["ranking_score", "samples"], ascending=[False, False]
    ).reset_index(drop=True)
    ranking.insert(0, "rank", np.arange(1, len(ranking) + 1))
    return ranking[
        [
            "rank",
            "group_type",
            "group",
            "samples",
            "wins",
            "losses",
            "timeouts",
            "win_rate",
            "resolved_win_rate",
            "expectancy_r",
            "ranking_score",
            "avg_result_pips",
            "avg_mfe_pips",
            "avg_mae_pips",
            "median_tp_seconds",
            "median_first_reach_seconds",
        ]
    ]


def run(
    args: argparse.Namespace,
    pair_name: str = PAIR,
    entry_mode: str = ENTRY_MODE,
) -> None:
    global PAIR
    PAIR = pair_name
    start = pd.Timestamp(args.start).to_pydatetime()
    end = pd.Timestamp(args.end).to_pydatetime()
    if start >= end:
        raise ValueError("--start must be earlier than --end")
    if args.tp_lookback < 1:
        raise ValueError("--tp-lookback must be at least 1")
    if args.tp_multiplier <= 0:
        raise ValueError("--tp-multiplier must be positive")
    if args.tp_pips <= 0:
        raise ValueError("--tp-pips must be positive")
    if args.tp_min_pips <= 0 or args.tp_min_pips > args.tp_max_pips:
        raise ValueError("--tp-min-pips must be positive and <= --tp-max-pips")
    if args.rr <= 0:
        raise ValueError("--rr must be positive")
    if args.horizon_minutes <= 0:
        raise ValueError("--horizon-minutes must be positive")
    if args.spread_pips < 0:
        raise ValueError("--spread-pips must not be negative")
    if entry_mode not in {"peak0-follow", "peak0-failure-break"}:
        raise ValueError(f"Unsupported entry mode: {entry_mode}")
    process_started = dt.datetime.now()
    next_notice_time = pd.Timestamp(start) + pd.DateOffset(months=2)
    pair = gene.currency_pair(PAIR)
    data = load_data(start, end, args.existing_data)
    m5 = add_rsi(data["M5"])
    h1 = add_rsi(data["H1"])
    s5 = data["S5"]
    s5_inspector = S5PathInspector(s5, pair)
    h1_points = h1_turning_points(h1)
    indices = candidate_indices(m5, start, end)
    print(
        f"peaks[0].count==2 candidates: {len(indices)} "
        f"(entry_mode={entry_mode})"
    )

    rows = []
    eligible_candidates = 0
    breakout_triggered_count = 0
    breakout_skip_counts: dict[str, int] = {}
    for number, index in enumerate(indices, 1):
        decision = m5.iloc[index]["time_jp_dt"]
        next_notice_time = send_progress_notices(
            PAIR,
            decision,
            next_notice_time,
            number,
            len(indices),
            process_started,
        )
        peak_context = peak_context_at_candidate(m5, int(index), pair)
        if peak_context is None:
            continue
        peak, previous_peak = peak_context
        eligible_candidates += 1
        peak_direction = int(peak["direction"])
        target_info = target_pips_at(m5, int(index), args, pair)
        if entry_mode == "peak0-failure-break":
            entry_info = s5_inspector.find_failure_breakout(
                decision,
                peak_direction,
                float(peak["start_price"]),
                float(m5.iloc[index - 1]["close"]),
                FAILURE_BREAK_MAX_WAIT_SECONDS,
                FAILURE_BREAK_BUFFER_PIPS,
            )
            if not entry_info["breakout_triggered"]:
                reason = str(entry_info["breakout_skip_reason"])
                breakout_skip_counts[reason] = (
                    breakout_skip_counts.get(reason, 0) + 1
                )
                continue
            breakout_triggered_count += 1
            direction = int(entry_info["breakout_direction"])
            entry_time = pd.Timestamp(entry_info["entry_time"])
            signal_reference_price = float(entry_info["entry_mid_price"])
        else:
            direction = peak_direction
            entry_time = decision
            signal_reference_price = float(m5.iloc[index - 1]["close"])
            entry_info = {
                "entry_mode": entry_mode,
                "peak_direction": peak_direction,
                "breakout_triggered": np.nan,
                "entry_time": entry_time,
                "entry_mid_price": signal_reference_price,
            }
        path_result = s5_inspector.inspect(
            entry_time,
            direction,
            signal_reference_price,
            target_info["tp_pips"],
            target_info["lc_pips"],
            args.horizon_minutes,
            args.spread_pips,
        )
        if not path_result["has_s5_path"]:
            continue
        entry = float(path_result["mid_entry_price"])
        # 開始時刻が decision-1h 以下の、完全に確定したH1足だけを参照する。
        completed_h1_open = decision - pd.Timedelta(hours=1)
        h1_index = int(
            h1["time_jp_dt"].searchsorted(
                completed_h1_open,
                side="right",
            )
        ) - 1
        row = {
            "pair": PAIR,
            "decision_time": decision,
            "decision_to_entry_seconds": float(
                (entry_time - decision).total_seconds()
            ),
            "direction": direction,
            **entry_info,
            **target_info,
            "horizon_minutes": args.horizon_minutes,
            "spread_pips": args.spread_pips,
            "peaks0_count": int(peak["count"]),
            "peak_gap_pips": float(peak["gap"]) / pair.pip_value,
            "peak_rsi": peak.get("rsi", peak.get("peak_rsi")),
            "previous_peak_gap_pips": (
                float(previous_peak["gap"]) / pair.pip_value
            ),
            "previous_peak_count": previous_peak["count"],
            "previous_peak_direction": previous_peak["direction"],
            "previous_peak_rsi": previous_peak.get("rsi"),
            "peak_to_previous_gap_ratio": (
                float(peak["gap"]) / float(previous_peak["gap"])
                if float(previous_peak["gap"]) > 0
                else np.nan
            ),
            "m5_rsi": float(m5.iloc[index - 1]["RSI_calc"]),
            "h1_rsi": (
                float(h1.iloc[h1_index]["RSI_calc"]) if h1_index >= 0 else np.nan
            ),
            **resistance_features(h1_points, decision, entry, direction, pair),
            **path_result,
        }
        rows.append(row)
        if number % 500 == 0:
            print(f"Processed {number}/{len(indices)} candidates")

    result = pd.DataFrame(rows)
    if entry_mode == "peak0-failure-break":
        print(
            f"Failure-break triggered={breakout_triggered_count}/"
            f"{eligible_candidates} "
            f"({breakout_triggered_count / eligible_candidates:.2%})"
            if eligible_candidates
            else "Failure-break triggered=0/0"
        )
        print("Failure-break skips:", breakout_skip_counts)
    if result.empty:
        print("No verified candidates were found.")
        elapsed_minutes = (dt.datetime.now() - process_started).total_seconds() / 60
        send_inspection_notice(
            f"{PAIR} win-point inspection 終了 "
            f"{start:%Y-%m-%d %H:%M:%S}->{end:%Y-%m-%d %H:%M:%S} "
            f"検証件数=0 経過={elapsed_minutes:.2f}分"
        )
        return
    result = add_bins(result)
    ranking = make_ranking(result, args.min_group_size)
    if args.tp_mode == "fixed":
        tp_tag = f"fixed{args.tp_pips:g}"
    else:
        tp_tag = (
            f"range{args.tp_lookback}x{args.tp_multiplier:g}"
            f"_{args.tp_min_pips:g}-{args.tp_max_pips:g}"
        )
    entry_tag = (
        ""
        if entry_mode == "peak0-follow"
        else (
            f"_failbreak{FAILURE_BREAK_MAX_WAIT_SECONDS}s"
            f"_{FAILURE_BREAK_REFERENCE}"
            f"_{FAILURE_BREAK_CONFIRMATION.replace('-', '')}"
        )
    )
    name = (
        f"{PAIR}_{start:%Y%m%d%H%M%S}_{end:%Y%m%d%H%M%S}"
        f"{entry_tag}_{tp_tag}_rr{args.rr:g}_sp{args.spread_pips:g}"
        f"_{args.horizon_minutes}m"
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    all_path = args.output_dir / f"win_points_{name}.csv"
    win_path = args.output_dir / f"win_only_{name}.csv"
    rank_path = args.output_dir / f"group_ranking_{name}.csv"
    result.to_csv(all_path, index=False, encoding="utf-8-sig")
    result[result["tp_hit"]].to_csv(win_path, index=False, encoding="utf-8-sig")
    ranking.to_csv(rank_path, index=False, encoding="utf-8-sig")
    print(
        f"Verified={len(result)}, wins={int(result['tp_hit'].sum())}, "
        f"losses={int(result['lc_hit'].sum())}, "
        f"timeouts={int(result['trade_result'].eq('timeout').sum())}, "
        f"win_rate={result['tp_hit'].mean():.2%}, "
        f"expectancy={result['result_r'].mean():.3f}R"
    )
    print(ranking.head(20).to_string(index=False))
    print("Saved:", all_path)
    print("Saved:", win_path)
    print("Saved:", rank_path)
    elapsed_minutes = (dt.datetime.now() - process_started).total_seconds() / 60
    completion_message = (
        f"{PAIR} win-point inspection 終了 mode={entry_mode} "
        f"{start:%Y-%m-%d %H:%M:%S}->{end:%Y-%m-%d %H:%M:%S} "
        f"検証={len(result)}件 勝ち={int(result['tp_hit'].sum())}件 "
        f"LC={int(result['lc_hit'].sum())}件 "
        f"勝率={result['tp_hit'].mean():.2%} "
        f"期待値={result['result_r'].mean():.3f}R "
        f"経過={elapsed_minutes:.2f}分"
    )
    print(completion_message)
    send_inspection_notice(completion_message)


if __name__ == "__main__":
    run(parse_args())
