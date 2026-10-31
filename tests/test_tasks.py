import threading
import time

import pytest

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

def test_immediately_completed_tasks_release_duplicate_keys():
    tasks = TaskManager(workers=2)
    try:
        for index in range(100):
            future = tasks.submit(f"quick-{index}", lambda: True)
            assert future is not None
            assert future.result(timeout=2) is True
    finally:
        tasks.shutdown()
@pytest.mark.parametrize("workers", [0, -1, True, 1.5])
def test_task_manager_requires_positive_integer_worker_count(workers):
    with pytest.raises(ValueError, match="positive integer"):
        TaskManager(workers=workers)


@pytest.mark.parametrize("key", [None, "", "  "])
def test_task_manager_rejects_empty_task_keys(key):
    tasks = TaskManager()
    try:
        with pytest.raises(ValueError, match="non-empty string"):
            tasks.submit(key, lambda: None)
    finally:
        tasks.shutdown()


def test_task_manager_rejects_non_callable_task():
    tasks = TaskManager()
    try:
        with pytest.raises(TypeError, match="callable"):
            tasks.submit("invalid", None)
    finally:
        tasks.shutdown()
