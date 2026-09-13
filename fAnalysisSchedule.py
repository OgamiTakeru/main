# 最新更新日時: 2026-09-09 15:57 JST
"""Completed-bar scheduling and persistent, at-most-once live analysis claims.

Claim a decision BEFORE analysis can submit an order. A claimed attempt is never
automatically retried, including when the process stops or a broker reply is
uncertain. The caller must use a separate ledger path per account/pair/mode.
Importing this module does not create files or contact external services.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import threading
import uuid


_TIMEFRAME_MINUTES = {"M5": 5, "M30": 30, "H1": 60}
_PATH_LOCKS: dict[str, threading.Lock] = {}
_PATH_LOCKS_GUARD = threading.Lock()


class AnalysisScheduleError(RuntimeError):
    """A live decision cannot safely be checked or recorded; do not submit."""


def _timeframe(value: str) -> str:
    if not isinstance(value, str) or value.upper() not in _TIMEFRAME_MINUTES:
        raise ValueError(f"unsupported analysis timeframe: {value!r}")
    return value.upper()


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("analysis timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


def _decision_time(value: datetime, timeframe: str) -> datetime:
    value = _utc(value)
    if value.second or value.microsecond or value.minute % _TIMEFRAME_MINUTES[timeframe]:
        raise ValueError(f"decision_time must be an exact {timeframe} boundary")
    return value


def live_decision_time(
    now_utc: datetime,
    timeframe: str = "M5",
    delay_seconds: float = 6,
    window_end_seconds: float = 30,
) -> datetime | None:
    """Return the completed-bar boundary only within its dispatch window.

    Aware timestamps in any timezone are normalized to UTC. Naive timestamps
    are rejected. The end is exclusive: the default window is [06, 30) seconds
    of a boundary minute. Missed windows are not caught up later.
    """
    timeframe = _timeframe(timeframe)
    now_utc = _utc(now_utc)
    if not 0 <= delay_seconds < window_end_seconds <= 60:
        raise ValueError("require 0 <= delay_seconds < window_end_seconds <= 60")
    if now_utc.minute % _TIMEFRAME_MINUTES[timeframe]:
        return None
    seconds = now_utc.second + now_utc.microsecond / 1_000_000
    if not delay_seconds <= seconds < window_end_seconds:
        return None
    return now_utc.replace(second=0, microsecond=0)


class AnalysisRunLedger:
    """Maximum claimed boundary per strategy/timeframe, shared across restarts.

    A lower or equal boundary is already consumed. Both reads and claims use
    the same thread/process lock; each operation reloads persistent state. An
    absent ledger starts empty, but unreadable/malformed state fails closed.
    ``path=None`` provides an isolated in-memory ledger, principally for tests.
    """

    def __init__(self, path: str | os.PathLike | None = None):
        self.path = Path(path).resolve() if path is not None else None
        self._memory: dict[str, str] = {}
        if self.path is None:
            self._thread_lock = threading.Lock()
        else:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise AnalysisScheduleError("cannot prepare analysis ledger directory") from exc
            identity = os.path.normcase(str(self.path))
            with _PATH_LOCKS_GUARD:
                self._thread_lock = _PATH_LOCKS.setdefault(identity, threading.Lock())

    @staticmethod
    def _key(strategy: str, timeframe: str) -> str:
        if not isinstance(strategy, str) or not strategy.strip():
            raise ValueError("strategy must be a nonempty string")
        return f"{strategy}|{timeframe}"

    @contextmanager
    def _locked(self):
        with self._thread_lock:
            if self.path is None:
                yield
                return
            try:
                lock_file = self.path.with_name(self.path.name + ".lock").open("a+b")
            except OSError as exc:
                raise AnalysisScheduleError("cannot open analysis ledger lock") from exc
            with lock_file:
                try:
                    if os.name == "nt":
                        import msvcrt

                        lock_file.seek(0, os.SEEK_END)
                        if lock_file.tell() == 0:
                            lock_file.write(b"\0")
                            lock_file.flush()
                        lock_file.seek(0)
                        msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
                    else:
                        import fcntl

                        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                except OSError as exc:
                    raise AnalysisScheduleError("cannot acquire analysis ledger lock") from exc
                try:
                    yield
                finally:
                    if os.name == "nt":
                        lock_file.seek(0)
                        msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _read(self) -> dict[str, str]:
        if self.path is None:
            return dict(self._memory)
        try:
            with self.path.open("r", encoding="utf-8") as stream:
                data = json.load(stream)
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as exc:
            raise AnalysisScheduleError("analysis ledger is unreadable; no new orders allowed") from exc
        try:
            if not isinstance(data, dict) or set(data) != {"version", "watermarks"}:
                raise ValueError("unexpected ledger schema")
            if type(data["version"]) is not int or data["version"] != 1:
                raise ValueError("unsupported ledger version")
            watermarks = data["watermarks"]
            if not isinstance(watermarks, dict):
                raise ValueError("watermarks must be an object")
            for key, value in watermarks.items():
                strategy, timeframe = key.rsplit("|", 1)
                if timeframe != _timeframe(timeframe):
                    raise ValueError("noncanonical timeframe")
                self._key(strategy, timeframe)
                if not isinstance(value, str):
                    raise ValueError("watermark must be a timestamp string")
                _decision_time(datetime.fromisoformat(value.replace("Z", "+00:00")), timeframe)
            return watermarks
        except (TypeError, ValueError, AttributeError) as exc:
            raise AnalysisScheduleError("analysis ledger is malformed; no new orders allowed") from exc

    def _write(self, watermarks: dict[str, str]) -> None:
        if self.path is None:
            self._memory = dict(watermarks)
            return
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.path.parent,
                prefix=self.path.stem + "_", suffix=".tmp", delete=False,
            ) as stream:
                temporary = Path(stream.name)
                json.dump({"version": 1, "watermarks": watermarks}, stream, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        except (OSError, TypeError, ValueError) as exc:
            # Preserve a failed temporary for diagnosis; never mask the cause.
            if temporary is not None:
                try:
                    if temporary.exists():
                        archive = self.path.parent / "archive"
                        archive.mkdir(exist_ok=True)
                        os.replace(temporary, archive / f"{temporary.name}.{uuid.uuid4().hex}.failed")
                except OSError as archive_error:
                    if hasattr(exc, "add_note"):
                        exc.add_note(f"Temporary could not be archived: {archive_error}")
            raise AnalysisScheduleError("analysis claim could not be persisted; do not submit") from exc

    def is_processed(self, strategy: str, timeframe: str, decision_time: datetime) -> bool:
        timeframe = _timeframe(timeframe)
        decision_time = _decision_time(decision_time, timeframe)
        key = self._key(strategy, timeframe)
        with self._locked():
            previous = self._read().get(key)
            return previous is not None and _utc(
                datetime.fromisoformat(previous.replace("Z", "+00:00"))
            ) >= decision_time

    def claim(self, strategy: str, timeframe: str, decision_time: datetime) -> bool:
        """Persist consumption before external effects; False means do not run."""
        timeframe = _timeframe(timeframe)
        decision_time = _decision_time(decision_time, timeframe)
        key = self._key(strategy, timeframe)
        with self._locked():
            watermarks = self._read()
            previous = watermarks.get(key)
            if previous is not None and _utc(
                datetime.fromisoformat(previous.replace("Z", "+00:00"))
            ) >= decision_time:
                return False
            watermarks[key] = decision_time.isoformat(timespec="seconds")
            self._write(watermarks)
            return True
