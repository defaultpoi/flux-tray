import threading
import time

from flux_tray.core.tasks import TaskManager


def test_duplicate_key_is_suppressed_until_task_finishes():
    gate = threading.Event()
    tasks = TaskManager(workers=1)
    try:
        first = tasks.submit("refresh", gate.wait)
        assert first is not None
        assert tasks.submit("refresh", lambda: None) is None
        gate.set()
        assert first.result(timeout=2) is True
        time.sleep(0.02)
        second = tasks.submit("refresh", lambda: 42)
        assert second.result(timeout=2) == 42
    finally:
        gate.set()
        tasks.shutdown()


def test_shutdown_rejects_new_work():
    tasks = TaskManager()
    tasks.shutdown()
    try:
        tasks.submit("x", lambda: None)
    except RuntimeError:
        pass
    else:
        raise AssertionError("submit after shutdown must fail")
