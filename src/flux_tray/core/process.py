"""Safe subprocess boundary with timeout and process-group cleanup."""

from __future__ import annotations

import os
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Mapping, Sequence


@dataclass(frozen=True, slots=True)
class ProcessResult:
    argv: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str


class ProcessError(RuntimeError):
    pass


class ProcessSupervisor:
    def run(
        self, argv: Sequence[str], *, timeout: float = 30, cwd: Path | None = None,
        env: Mapping[str, str] | None = None, cancelled: Event | None = None,
    ) -> ProcessResult:
        if not argv or not all(isinstance(part, str) for part in argv):
            raise ValueError("argv must be a non-empty sequence of strings")
        process = subprocess.Popen(
            list(argv), cwd=cwd, env=dict(os.environ, **(env or {})),
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, start_new_session=True,
        )
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            self._terminate(process)
            raise ProcessError(f"command timed out after {timeout:g}s: {argv[0]}") from exc
        if cancelled is not None and cancelled.is_set():
            self._terminate(process)
            raise ProcessError(f"command cancelled: {argv[0]}")
        return ProcessResult(tuple(argv), process.returncode, stdout, stderr)

    @staticmethod
    def _terminate(process: subprocess.Popen[str]) -> None:
        if process.poll() is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
            process.wait(timeout=2)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
