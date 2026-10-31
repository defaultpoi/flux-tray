"""Safe subprocess boundary with timeout, cancellation and process-group cleanup."""

from __future__ import annotations

import math
import os
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Callable, Mapping, Sequence


@dataclass(frozen=True, slots=True)
class ProcessResult:
    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


class ProcessError(RuntimeError):
    pass


class ProcessSupervisor:
    def __init__(self):
        self._lock = Lock()
        self._processes: dict[subprocess.Popen, bool] = {}
        self._closed = False

    def run(
        self, argv: Sequence[str], *, timeout: float = 30, cwd: Path | None = None,
        env: Mapping[str, str] | None = None, cancelled: Event | None = None,
        shutdown_protected: bool = False,
        output_callback: Callable[[str, str], None] | None = None,
    ) -> ProcessResult:
        if not argv or not all(isinstance(part, str) for part in argv):
            raise ValueError("argv must be a non-empty sequence of strings")
        try:
            valid_timeout = (not isinstance(timeout, bool)
                             and math.isfinite(timeout) and timeout > 0)
        except TypeError as exc:
            raise ValueError("timeout must be a finite positive number") from exc
        if not valid_timeout:
            raise ValueError("timeout must be a finite positive number")
        with self._lock:
            if self._closed:
                raise ProcessError("process supervisor is shutting down")
            process = subprocess.Popen(
                list(argv), cwd=cwd, env=dict(os.environ, **(env or {})),
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, bufsize=1, start_new_session=True,
            )
            self._processes[process] = shutdown_protected
        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []

        def drain(stream, chunks, channel):
            try:
                for line in iter(stream.readline, ""):
                    chunks.append(line)
                    if output_callback is not None:
                        try:
                            output_callback(channel, line)
                        except Exception:
                            # A progress observer must never interrupt pipe draining.
                            pass
            finally:
                stream.close()

        readers = [
            Thread(target=drain, args=(process.stdout, stdout_chunks, "stdout"), daemon=True),
            Thread(target=drain, args=(process.stderr, stderr_chunks, "stderr"), daemon=True),
        ]
        for reader in readers:
            reader.start()
        deadline = time.monotonic() + timeout
        try:
            while process.poll() is None:
                if cancelled is not None and cancelled.is_set():
                    self._terminate(process)
                    raise ProcessError(f"command cancelled: {argv[0]}")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._terminate(process)
                    raise ProcessError(f"command timed out after {timeout:g}s: {argv[0]}")
                time.sleep(min(0.05, remaining))
            process.wait()
            for reader in readers:
                reader.join(timeout=2)
            with self._lock:
                shutting_down = self._closed and not shutdown_protected
            if shutting_down:
                raise ProcessError(f"command terminated during shutdown: {argv[0]}")
            return ProcessResult(tuple(argv), process.returncode,
                                 "".join(stdout_chunks), "".join(stderr_chunks))
        finally:
            if process.poll() is None:
                self._terminate(process)
            for reader in readers:
                reader.join(timeout=1)
            with self._lock:
                self._processes.pop(process, None)

    def spawn(self, argv: Sequence[str], *, cwd: Path | None = None,
              env: Mapping[str, str] | None = None,
              shutdown_protected: bool = False) -> subprocess.Popen:
        if not argv or not all(isinstance(part, str) for part in argv):
            raise ValueError("argv must be a non-empty sequence of strings")
        with self._lock:
            if self._closed:
                raise ProcessError("process supervisor is shutting down")
            process = subprocess.Popen(
                list(argv), cwd=cwd, env=dict(os.environ, **(env or {})),
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            self._processes[process] = shutdown_protected
        Thread(target=self._reap, args=(process,), daemon=True).start()
        return process

    def _reap(self, process: subprocess.Popen) -> None:
        process.wait()
        with self._lock:
            self._processes.pop(process, None)

    def terminate_all(self) -> None:
        """Prevent new work and terminate every unprotected child process group."""
        with self._lock:
            self._closed = True
            processes = tuple(process for process, protected in self._processes.items() if not protected)
        for process in processes:
            self._terminate(process)

    @staticmethod
    def _terminate(process: subprocess.Popen) -> None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()
