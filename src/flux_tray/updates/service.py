"""XBPS update scanning and explicit package-maintenance actions."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from threading import Lock
from typing import Callable, Sequence

from flux_tray.core.process import ProcessResult, ProcessSupervisor
from flux_tray.core.storage import JsonStore


@dataclass(frozen=True, slots=True)
class PackageChange:
    pkgver: str
    action: str
    architecture: str
    repository: str
    installed_size: str
    download_size: str


class UpdateService:
    """Never installs or removes anything during a scan."""

    def __init__(self, store: JsonStore, process: ProcessSupervisor | None = None,
                 *, runner: Callable[..., ProcessResult] | None = None,
                 sudo: str = "sudo", timeout: float = 1800):
        self.store = store
        self.process = process or ProcessSupervisor()
        self.runner = runner or self.process.run
        self.sudo = sudo
        self.timeout = timeout
        self._lock = Lock()
        self.state = store.load()
        if not isinstance(self.state, dict):
            self.state = {}

    @staticmethod
    def _env() -> dict[str, str]:
        return {"LC_ALL": "C.UTF-8"}

    def _privileged(self, argv: Sequence[str]) -> list[str]:
        if os.geteuid() == 0:
            return list(argv)
        return [self.sudo, "-n", *argv]

    def _run(self, argv: Sequence[str], *, timeout: float) -> ProcessResult:
        with self._lock:
            return self.runner(list(argv), timeout=timeout, env=self._env())

    def scan_updates(self) -> list[PackageChange]:
        result = self._run(["xbps-install", "-Mn", "-u"], timeout=180)

        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "XBPS update scan failed")
        changes = []
        for line in result.stdout.splitlines():
            fields = line.split()
            if len(fields) == 6:
                changes.append(PackageChange(*fields))
        self.state = {"checked_at": datetime.now(timezone.utc).isoformat(),
                      "changes": [asdict(change) for change in changes],
                      "scan_output": result.stdout, "scan_error": None}
        self.store.save(self.state)
        return changes

    def list_orphans(self) -> list[str]:
        result = self._run(["xbps-query", "-O"], timeout=60)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "Could not list XBPS orphans")
        return sorted({line.strip().split()[0] for line in result.stdout.splitlines()
                       if line.strip()})

    def apply_updates(self) -> ProcessResult:
        """Run the real system update; callers must only expose this after explicit user action."""
        return self._run(self._privileged(["xbps-install", "-y", "-u"]),
                         timeout=self.timeout)

    def remove_orphans(self) -> ProcessResult:
        """Remove current automatic orphans after an explicit confirmation in the UI."""
        return self._run(self._privileged(["xbps-remove", "-y", "-o"]),
                         timeout=self.timeout)

    def clean_cache(self) -> ProcessResult:
        """Remove outdated cached packages after an explicit confirmation in the UI."""
        return self._run(self._privileged(["xbps-remove", "-y", "-O"]),
                           timeout=self.timeout)

    def remove_orphans_and_clean_cache(self) -> tuple[ProcessResult, ProcessResult]:
        removed = self.remove_orphans()
        if removed.returncode != 0:
            return removed, removed
        return removed, self.clean_cache()
