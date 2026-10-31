"""Bounded background work with duplicate-key suppression."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from threading import Lock
from typing import Callable, TypeVar

T = TypeVar("T")


class TaskManager:
    def __init__(self, workers: int = 4):
        if isinstance(workers, bool) or not isinstance(workers, int) or workers <= 0:
            raise ValueError("workers must be a positive integer")
        self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="flux-tray")
        self._lock = Lock()
        self._active: dict[str, Future] = {}
        self._closed = False

    def submit(self, key: str, function: Callable[..., T], *args, **kwargs) -> Future[T] | None:
        if not isinstance(key, str) or not key.strip():
            raise ValueError("task key must be a non-empty string")
        if not callable(function):
            raise TypeError("task function must be callable")
        with self._lock:
            if self._closed:
                raise RuntimeError("task manager is shut down")
            active = self._active.get(key)
            if active is not None and not active.done():
                return None
            future = self._executor.submit(function, *args, **kwargs)
            self._active[key] = future
        future.add_done_callback(lambda done, task_key=key: self._finished(task_key, done))
        return future

    def _finished(self, key: str, future: Future) -> None:
        with self._lock:
            if self._active.get(key) is future:
                self._active.pop(key, None)

    def shutdown(self, wait: bool = True) -> None:
        with self._lock:
            self._closed = True
            active = tuple(self._active.values())
        for future in active:
            future.cancel()
        self._executor.shutdown(wait=wait, cancel_futures=True)
