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


def test_timeout_terminates_process():
    with pytest.raises(ProcessError, match="timed out"):
        ProcessSupervisor().run(
            [sys.executable, "-c", "import time; time.sleep(5)"], timeout=0.1
        )


def test_cancellation_terminates_process():
    cancelled = threading.Event()
    threading.Thread(target=lambda: (time.sleep(0.1), cancelled.set()), daemon=True).start()
    with pytest.raises(ProcessError, match="cancelled"):
        ProcessSupervisor().run(
            [sys.executable, "-c", "import time; time.sleep(5)"],
            timeout=3, cancelled=cancelled,
        )
