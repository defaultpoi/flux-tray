"""Small DNS and direct-IP connectivity diagnostic."""

from __future__ import annotations

import socket
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Callable, Sequence

from flux_tray.core.process import ProcessResult, ProcessSupervisor
from flux_tray.core.storage import JsonStore


@dataclass(frozen=True, slots=True)
class ConnectivityState:
    status: str
    dns_ok: bool
    network_ok: bool
    checked_at: str


class ConnectivityService:
    def __init__(self, store: JsonStore, *, host: str = "example.com",
                 network_target: tuple[str, int] = ("1.1.1.1", 443),
                 resolver: Callable = socket.getaddrinfo,
                 connector: Callable = socket.create_connection,
                 timeout: float = 3.0, process: ProcessSupervisor | None = None,
                 reset_command: Sequence[str] | None = None):
        self.store = store
        self.host = host
        self.network_target = network_target
        self.resolver = resolver
        self.connector = connector
        self.timeout = timeout
        self.process = process or ProcessSupervisor()
        self.reset_command = list(reset_command) if reset_command else None
        self.state = store.load()
        if not isinstance(self.state, dict):
            self.state = {}

    @property
    def reset_available(self) -> bool:
        return bool(self.reset_command)

    def reset(self) -> ProcessResult:
        if not self.reset_command:
            raise RuntimeError("Connectivity reset is not configured")
        result = self.process.run(self.reset_command, timeout=60)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "Connectivity reset command failed")
        return result

    def check(self) -> ConnectivityState:
        try:
            self.resolver(self.host, 443, type=socket.SOCK_STREAM)
            dns_ok = True
        except OSError:
            dns_ok = False
        try:
            connection = self.connector(self.network_target, timeout=self.timeout)
            connection.close()
            network_ok = True
        except OSError:
            network_ok = False
        if dns_ok and network_ok:
            status = "online"
        elif network_ok:
            status = "dns-error"
        else:
            status = "offline"
        result = ConnectivityState(status, dns_ok, network_ok,
                                   datetime.now(timezone.utc).isoformat())
        previous = self.state.get("status")
        self.state = asdict(result)
        if previous != status:
            self.store.save(self.state)
        return result
