"""Connectivity diagnostics and network utilities."""

from flux_tray.connectivity.service import ConnectivityService
from flux_tray.connectivity.network import dns_ok, run_when_online, reset_module_state

__all__ = ["ConnectivityService", "dns_ok", "run_when_online", "reset_module_state"]
