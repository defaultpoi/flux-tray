"""Persistent countdown timer with suspend-aware missed-deadline detection."""

from __future__ import annotations

import time
import uuid
from datetime import datetime
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
        self.state.update({"status": "running", "duration": seconds,
                           "monotonic_deadline": mono + seconds,
                           "boottime_deadline": boot + seconds,
                           "boot_id": self.boot_id()})
        self._save()

    def cancel(self) -> None:
        self._recovered = False
        self.state["status"] = "idle"
        for key in ("duration", "monotonic_deadline", "boottime_deadline", "boot_id"):
            self.state.pop(key, None)
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

    @property
    def schedules(self) -> list[dict]:
        entries = self.state.get("schedules", [])
        return [item for item in entries if isinstance(item, dict)]

    def add_schedule(self, weekdays: list[int], clock: str, label: str) -> dict:
        """Add a local-time weekly alarm. Weekdays use Monday=0 through Sunday=6."""
        import re

        normalized_days = sorted({int(day) for day in weekdays})
        if not normalized_days or any(day < 0 or day > 6 for day in normalized_days):
            raise ValueError("Choose at least one weekday")
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", clock):
            raise ValueError("Time must use 24-hour HH:MM format")
        label = str(label).strip()[:80]
        if not label:
            raise ValueError("Alarm label cannot be empty")
        item = {"id": uuid.uuid4().hex, "weekdays": normalized_days,
                "time": clock, "label": label, "enabled": True,
                "last_fired": None}
        self.state.setdefault("schedules", []).append(item)
        self._save()
        return item

    def update_schedule(self, schedule_id: str, weekdays: list[int],
                        clock: str, label: str) -> dict:
        import re

        normalized_days = sorted({int(day) for day in weekdays})
        if not normalized_days or any(day < 0 or day > 6 for day in normalized_days):
            raise ValueError("Choose at least one weekday")
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", clock):
            raise ValueError("Time must use 24-hour HH:MM format")
        label = str(label).strip()[:80]
        if not label:
            raise ValueError("Alarm label cannot be empty")
        for item in self.schedules:
            if item.get("id") == schedule_id:
                changed = item.get("time") != clock or item.get("weekdays") != normalized_days
                item.update({"weekdays": normalized_days, "time": clock, "label": label})
                if changed:
                    item["last_fired"] = None
                self._save()
                return item
        raise KeyError(schedule_id)

    def remove_schedule(self, schedule_id: str) -> None:
        self.state["schedules"] = [
            item for item in self.schedules if item.get("id") != schedule_id
        ]
        alert = self.state.get("schedule_alert")
        if isinstance(alert, dict) and alert.get("schedule_id") == schedule_id:
            self.state.pop("schedule_alert", None)
        self._save()

    def poll_schedules(self, now: datetime | None = None) -> dict | None:
        """Return the active recurring alarm, firing each matching schedule once per date."""
        now = now or datetime.now().astimezone()
        minute = now.strftime("%H:%M")
        date_key = now.date().isoformat()
        active = self.state.get("schedule_alert")
        if isinstance(active, dict):
            snooze_until = float(active.get("snooze_until", 0) or 0)
            if snooze_until <= time.time():
                active.pop("snooze_until", None)
                self._save()
                return active
            return None
        for item in self.schedules:
            if (item.get("enabled", True) and now.weekday() in item.get("weekdays", [])
                    and item.get("time", "99:99") <= minute and item.get("last_fired") != date_key):
                item["last_fired"] = date_key
                alert = {"schedule_id": item["id"], "label": item["label"],
                         "fired_at": now.isoformat()}
                self.state["schedule_alert"] = alert
                self._save()
                return alert
        return None

    def snooze_schedule_alert(self, minutes: int = 5) -> None:
        alert = self.state.get("schedule_alert")
        if not isinstance(alert, dict):
            return
        self.state["schedule_alert"]["snooze_until"] = time.time() + max(1, int(minutes)) * 60
        self._save()

    def dismiss_schedule_alert(self) -> None:
        self.state.pop("schedule_alert", None)
        self._save()

    def acknowledge(self) -> None:
        if self.state.get("status") in {"ringing", "missed"}:
            self.cancel()
