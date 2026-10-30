"""Persistent countdown timer with suspend-aware missed-deadline detection."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from flux_tray.core.storage import JsonStore


def _boot_id() -> str:
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
    except OSError:
        return "unknown"


def _boottime() -> float:
    clock = getattr(time, "CLOCK_BOOTTIME", None)
    return time.clock_gettime(clock) if clock is not None else time.monotonic()


class CountdownTimer:
    """One persistent countdown; expiration is delivered once, never late after suspend."""

    def __init__(self, store: JsonStore, *, monotonic: Callable[[], float] = time.monotonic,
                 boottime: Callable[[], float] = _boottime,
                 boot_id: Callable[[], str] = _boot_id, maximum: int = 7200,
                 step: int = 60):
        self.store = store
        self.monotonic = monotonic
        self.boottime = boottime
        self.boot_id = boot_id
        self.maximum = max(60, int(maximum))
        self.step = min(max(1, int(step)), self.maximum)
        self.state = store.load()
        if not isinstance(self.state, dict):
            self.state = {}
        self.state.setdefault("status", "idle")
        self._recovered = self.state.get("status") == "running"

    def _save(self) -> None:
        self.store.save(self.state)

    def start(self, seconds: int) -> None:
        seconds = int(seconds)
        if seconds < self.step or seconds > self.maximum or seconds % self.step:
            raise ValueError(f"Duration must be a multiple of {self.step} between "
                             f"{self.step} and {self.maximum} seconds")
        mono, boot = self.monotonic(), self.boottime()
        self._recovered = False
        self.state = {"status": "running", "duration": seconds,
                      "monotonic_deadline": mono + seconds,
                      "boottime_deadline": boot + seconds,
                      "boot_id": self.boot_id()}
        self._save()

    def cancel(self) -> None:
        self._recovered = False
        self.state = {"status": "idle"}
        self._save()

    def remaining(self) -> int:
        if self.state.get("status") != "running":
            return 0
        if self.state.get("boot_id") != self.boot_id():
            return 0
        return max(0, int(self.state.get("monotonic_deadline", 0) - self.monotonic() + 0.999))

    def poll(self) -> str:
        """Return 'ring', 'missed' or 'idle'; ring is emitted only once."""
        if self.state.get("status") != "running":
            return self.state.get("status", "idle")
        if self.state.get("boot_id") != self.boot_id():
            self.state["status"] = "missed"
            self._save()
            return "missed"
        mono_expired = self.monotonic() >= self.state.get("monotonic_deadline", 0)
        boot_expired = self.boottime() >= self.state.get("boottime_deadline", 0)
        if self._recovered:
            self._recovered = False
            if mono_expired or boot_expired:
                self.state["status"] = "missed"
                self._save()
                return "missed"
        if boot_expired and not mono_expired:
            self.state["status"] = "missed"
            self._save()
            return "missed"
        if mono_expired:
            self.state["status"] = "ringing"
            self._save()
            return "ring"
        return "running"

    def acknowledge(self) -> None:
        if self.state.get("status") in {"ringing", "missed"}:
            self.cancel()
