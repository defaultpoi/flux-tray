import sys
import threading
import time

import pytest

from flux_tray.core.process import ProcessError, ProcessSupervisor


def test_process_captures_output_and_environment():
    result = ProcessSupervisor().run(
        [sys.executable, "-c", "import os; print(os.environ['FLUX_TEST'])"],
        env={"FLUX_TEST": "works"},
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "works"


@pytest.mark.parametrize("timeout", [0, -1, True, float("nan"), float("inf"), -float("inf")])
def test_process_rejects_invalid_timeout_before_starting(timeout):
    with pytest.raises(ValueError, match="finite positive"):
        ProcessSupervisor().run([sys.executable, "-c", "pass"], timeout=timeout)


def test_timeout_terminates_process():
    with pytest.raises(ProcessError, match="timed out"):
        ProcessSupervisor().run(
            [sys.executable, "-c", "import time; time.sleep(5)"], timeout=0.1
        )


def test_successful_command_terminates_remaining_process_group_children(tmp_path):
    ready = tmp_path / "child-ready"
    marker = tmp_path / "child-survived"
    child_code = (
        "import pathlib, time; "
        "pathlib.Path(" + repr(str(ready)) + ").touch(); "
        "time.sleep(0.6); "
        "pathlib.Path(" + repr(str(marker)) + ").touch()"
    )
    parent_code = (
        "import pathlib, subprocess, sys, time\n"
        "child = " + repr(child_code) + "\n"
        "subprocess.Popen([sys.executable, '-c', child])\n"
        "ready = " + repr(str(ready)) + "\n"
        "deadline = time.monotonic() + 2\n"
        "while not pathlib.Path(ready).exists() and time.monotonic() < deadline:\n"
        "    time.sleep(0.01)\n"
    )
    started = time.monotonic()
    result = ProcessSupervisor().run([sys.executable, "-c", parent_code], timeout=3)
    assert result.returncode == 0
    assert time.monotonic() - started < 2
    time.sleep(0.7)
    assert not marker.exists()


def test_cancellation_terminates_process():
    cancelled = threading.Event()
    threading.Thread(target=lambda: (time.sleep(0.1), cancelled.set()), daemon=True).start()
    with pytest.raises(ProcessError, match="cancelled"):
        ProcessSupervisor().run(
            [sys.executable, "-c", "import time; time.sleep(5)"],
            timeout=3, cancelled=cancelled,
        )

def test_shutdown_terminates_unprotected_children():
    supervisor = ProcessSupervisor()
    completed = threading.Event()

    def work():
        try:
            supervisor.run([sys.executable, "-c", "import time; time.sleep(10)"], timeout=20)
        except ProcessError:
            completed.set()

    worker = threading.Thread(target=work)
    worker.start()
    deadline = time.monotonic() + 2
    while not supervisor._processes and time.monotonic() < deadline:
        time.sleep(0.01)
    supervisor.terminate_all()
    worker.join(timeout=3)
    assert completed.is_set()
    assert not worker.is_alive()


def test_shutdown_leaves_protected_transaction_running():
    supervisor = ProcessSupervisor()
    completed = threading.Event()

    def work():
        result = supervisor.run([sys.executable, "-c", "import time; time.sleep(0.2)"],
                                timeout=3, shutdown_protected=True)
        completed.set()
        assert result.returncode == 0

    worker = threading.Thread(target=work)
    worker.start()
    deadline = time.monotonic() + 2
    while not supervisor._processes and time.monotonic() < deadline:
        time.sleep(0.01)
    supervisor.terminate_all()
    worker.join(timeout=3)
    assert completed.is_set()
    assert not worker.is_alive()


def test_output_callback_receives_process_output():
    observed = []
    result = ProcessSupervisor().run(
        [sys.executable, "-c", "print('callback works')"],
        output_callback=lambda channel, line: observed.append((channel, line.strip())),
    )
    assert result.stdout.strip() == "callback works"
    assert ("stdout", "callback works") in observed
