"""Monotonic scheduler; callbacks dispatch work, never block."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Callable


@dataclass(slots=True)
class Job:
    name: str
    interval: float
    callback: Callable[[], None]
    due_at: float
    running: bool = False
    enabled: bool = True


class Scheduler:
    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._jobs: dict[str, Job] = {}

    def add(
        self, name: str, interval: float, callback: Callable[[], None],
        *, initial_delay: float | None = None,
    ) -> None:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("job name must be a non-empty string")
        if not callable(callback):
            raise TypeError("job callback must be callable")
        try:
            valid_interval = (not isinstance(interval, bool)
                             and math.isfinite(interval) and interval > 0)
        except (TypeError, OverflowError) as exc:
            raise ValueError("interval must be a finite positive number") from exc
        if not valid_interval:
            raise ValueError("interval must be a finite positive number")
        if initial_delay is None:
            delay = interval
        else:
            try:
                valid_delay = (not isinstance(initial_delay, bool)
                              and math.isfinite(initial_delay))
            except TypeError as exc:
                raise ValueError("initial delay must be a finite non-negative number") from exc
            if not valid_delay:
                raise ValueError("initial delay must be a finite non-negative number")
            delay = max(0, initial_delay)
        self._jobs[name] = Job(name, interval, callback, self._clock() + delay)

    def remove(self, name: str) -> None:
        self._jobs.pop(name, None)

    def set_running(self, name: str, running: bool) -> None:
        job = self._jobs.get(name)
        if job is not None:
            job.running = running
            if not running:
                job.due_at = self._clock() + job.interval

    def retry(self, name: str, delay: float) -> None:
        try:
            valid_delay = not isinstance(delay, bool) and math.isfinite(delay)
        except (TypeError, OverflowError) as exc:
            raise ValueError("retry delay must be a finite non-negative number") from exc
        if not valid_delay:
            raise ValueError("retry delay must be a finite non-negative number")
        if name in self._jobs:
            self._jobs[name].due_at = self._clock() + max(0, delay)

    def due(self) -> list[Job]:
        now = self._clock()
        ready = []
        for job in self._jobs.values():
            if job.enabled and not job.running and job.due_at <= now:
                job.running = True
                ready.append(job)
        return ready
