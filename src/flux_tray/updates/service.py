"""XBPS update scanning and explicit package-maintenance actions."""

from __future__ import annotations

import os
import re
import shutil
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
                 sudo: str = "sudo", timeout: float = 1800,
                 installer: str = "xbps", topgrade_steps: tuple[str, ...] = (),
                 topgrade_executable: str = "topgrade"):
        self.store = store
        self.process = process or ProcessSupervisor()
        self.runner = runner or self.process.run
        self.sudo = sudo
        self.timeout = timeout
        self.installer = installer.strip().casefold()
        self.topgrade_steps = tuple(dict.fromkeys(step.strip() for step in topgrade_steps if step.strip()))
        self.topgrade_executable = topgrade_executable
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

    def _run(self, argv: Sequence[str], *, timeout: float, shutdown_protected: bool = False) -> ProcessResult:
        with self._lock:
            return self.runner(list(argv), timeout=timeout, env=self._env(),
                               shutdown_protected=shutdown_protected)

    def _record_action(self, action: str, results: Sequence[ProcessResult],
                       version_changes: list[dict] | None = None) -> None:
        records = [{
            "argv": list(result.argv),
            "returncode": int(result.returncode),
            "stdout": str(result.stdout)[-4000:],
            "stderr": str(result.stderr)[-4000:],
        } for result in results]
        self.state["last_action"] = {
            "action": action,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "success": all(item["returncode"] == 0 for item in records),
            "results": records,
        }
        if action.startswith("System update"):
            self.state["last_action"]["version_changes"] = version_changes
        self.store.save(self.state)

    def dismiss_last_action(self) -> None:
        self.state.pop("last_action", None)
        self.store.save(self.state)

    def scan_updates(self) -> list[PackageChange]:
        result = self._run(["xbps-install", "-Mn", "-u"], timeout=180)

        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "XBPS update scan failed")
        changes = []
        for line in result.stdout.splitlines():
            fields = line.split()
            if len(fields) == 6:
                changes.append(PackageChange(*fields))
        last_action = self.state.get("last_action")
        self.state = {"checked_at": datetime.now(timezone.utc).isoformat(),
                      "changes": [asdict(change) for change in changes],
                      "scan_output": result.stdout, "scan_error": None}
        if last_action:
            self.state["last_action"] = last_action
        self.store.save(self.state)
        return changes

    def list_orphans(self) -> list[str]:
        result = self._run(["xbps-query", "-O"], timeout=60)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "Could not list XBPS orphans")
        return sorted({line.strip().split()[0] for line in result.stdout.splitlines()
                       if line.strip()})

    def _installed_versions(self) -> dict[str, str] | None:
        try:
            result = self._run(["xbps-query", "-l"], timeout=60)
        except Exception:
            return None
        if result.returncode != 0:
            return None
        versions = {}
        for line in result.stdout.splitlines():
            match = re.match(r"^\[\*\]\s+(.+)-([0-9][^\s]*)", line.strip())
            if match:
                versions[match.group(1)] = match.group(2)
        return versions

    @staticmethod
    def _version_changes(before: dict[str, str] | None,
                         after: dict[str, str] | None) -> list[dict] | None:
        if before is None or after is None:
            return None
        return [
            {"package": name, "old": before.get(name), "new": after.get(name)}
            for name in sorted(before.keys() | after.keys())
            if before.get(name) != after.get(name)
        ]

    def apply_updates(self) -> ProcessResult | tuple[ProcessResult, ...]:
        """Run the real system update; callers must only expose this after explicit user action."""
        before = self._installed_versions()
        if self.installer == "topgrade" and shutil.which(self.topgrade_executable):
            steps = tuple(dict.fromkeys(("system", *self.topgrade_steps)))
            argv = [self.topgrade_executable, "--only", *steps, "--yes", "--no-retry"]
            result = self._run(argv, timeout=self.timeout, shutdown_protected=True)
            results = (result,)
            action = "System update (Topgrade)"
            return_value = result
        else:
            changes = self.state.get("changes") or []
            completed = []
            for change in changes:
                pkgver = str(change.get("pkgver", ""))
                package = pkgver.rsplit("-", 1)[0] if "-" in pkgver else pkgver
                if not package:
                    continue
                result = self._run(self._privileged(["xbps-install", "-y", "-u", package]),
                                   timeout=self.timeout, shutdown_protected=True)
                completed.append(result)
                if result.returncode != 0:
                    break
            results = tuple(completed)
            action = "System update (XBPS)"
            return_value = results
        after = self._installed_versions()
        self._record_action(action, results, self._version_changes(before, after))
        return return_value

    def remove_orphans(self) -> ProcessResult:
        """Remove current automatic orphans after an explicit confirmation in the UI."""
        result = self._run(self._privileged(["xbps-remove", "-y", "-o"]),
                           timeout=self.timeout, shutdown_protected=True)
        self._record_action("Remove orphan packages", (result,))
        return result

    def clean_cache(self) -> ProcessResult:
        """Remove outdated cached packages after an explicit confirmation in the UI."""
        result = self._run(self._privileged(["xbps-remove", "-y", "-O"]),
                           timeout=self.timeout, shutdown_protected=True)
        self._record_action("Clean package cache", (result,))
        return result

    def remove_orphans_and_clean_cache(self) -> tuple[ProcessResult, ProcessResult]:
        removed = self.remove_orphans()
        if removed.returncode != 0:
            return removed, removed
        return removed, self.clean_cache()
