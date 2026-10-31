"""Network utilities: DNS lookup with single in-flight thread and online waiter."""

from __future__ import annotations

import logging
import socket
import threading
import time
from typing import Callable

from flux_tray.core.tasks import TaskManager

_log = logging.getLogger("flux_tray.network")

# Module-level state for DNS and online handling
_dns_lock = threading.Lock()
_dns_lookup: threading.Thread | None = None
_dns_result: bool | None = None
_dns_exception: BaseException | None = None

_online_waiting: list[Callable[[], None]] = []
_online_waiting_lock = threading.Lock()
_online_poller_running = False
_online_poller_thread: threading.Thread | None = None


def dns_ok() -> bool:
    """Return True if DNS is currently working. Starts a lookup if none in flight."""
    global _dns_lookup, _dns_result, _dns_exception
    
    with _dns_lock:
        if _dns_lookup is not None and _dns_lookup.is_alive():
            # Another thread is already doing the lookup
            return _dns_result is True
        
        # Start a new lookup
        _dns_result = None
        _dns_exception = None
        _dns_lookup = threading.Thread(target=_dns_probe, daemon=True)
        _dns_lookup.start()
        
        # Wait for the lookup to complete with a timeout
        _dns_lookup.join(timeout=5.0)
        
        if _dns_exception:
            _log.debug("DNS probe raised: %s", _dns_exception)
            return False
        return _dns_result is True


def _dns_probe() -> None:
    """Probe DNS by resolving a known host."""
    global _dns_result, _dns_exception
    try:
        socket.getaddrinfo("example.com", 443, type=socket.SOCK_STREAM)
        _dns_result = True
    except Exception as exc:
        _dns_result = False
        _dns_exception = exc


def run_when_online(callback: Callable[[], None]) -> None:
    """Queue a callback to run when network is online.
    
    If already online, runs immediately on a new thread.
    Otherwise, queues for the online poller to invoke when connectivity returns.
    """
    # Quick check - if DNS is ok and we can connect, run immediately
    if _is_online_now():
        threading.Thread(target=callback, daemon=True).start()
        return
    
    with _online_waiting_lock:
        _online_waiting.append(callback)
        _start_online_poller()


def _is_online_now() -> bool:
    """Quick check if we appear to be online."""
    try:
        socket.getaddrinfo("example.com", 443, type=socket.SOCK_STREAM)
        # Also check TCP connectivity
        sock = socket.create_connection(("1.1.1.1", 443), timeout=3.0)
        sock.close()
        return True
    except Exception:
        return False


def _start_online_poller() -> None:
    """Start the online poller thread if not already running."""
    global _online_poller_running, _online_poller_thread
    
    with _online_waiting_lock:
        if _online_poller_running:
            return
        _online_poller_running = True
        _online_poller_thread = threading.Thread(target=_online_poller, daemon=True)
        _online_poller_thread.start()


def _online_poller() -> None:
    """Poller that waits for network connectivity and fires waiting callbacks."""
    global _online_poller_running, _online_waiting
    
    try:
        while True:
            with _online_waiting_lock:
                if not _online_waiting:
                    _online_poller_running = False
                    return
            
            if _is_online_now():
                # Network is back - fire all waiting callbacks
                callbacks_to_run: list[Callable[[], None]]
                with _online_waiting_lock:
                    callbacks_to_run = _online_waiting[:]
                    _online_waiting.clear()
                
                for callback in callbacks_to_run:
                    try:
                        threading.Thread(target=callback, daemon=True).start()
                    except Exception:
                        _log.exception("Online callback raised")
                return
            
            # Wait before next check
            time.sleep(5.0)
    except Exception:
        _log.exception("Online poller died unexpectedly")
    finally:
        with _online_waiting_lock:
            _online_poller_running = False


def reset_module_state() -> None:
    """Reset module state for testing."""
    global _dns_lookup, _dns_result, _dns_exception
    global _online_waiting, _online_poller_running, _online_poller_thread
    
    with _dns_lock:
        _dns_lookup = None
        _dns_result = None
        _dns_exception = None
    
    with _online_waiting_lock:
        _online_waiting.clear()
        _online_poller_running = False
        _online_poller_thread = None
