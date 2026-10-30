from flux_tray.core.storage import JsonStore
from flux_tray.timers.service import CountdownTimer


class Clock:
    def __init__(self):
        self.mono = 100.0
        self.boot = 100.0
        self.id = "boot-a"

    def monotonic(self):
        return self.mono

    def boottime(self):
        return self.boot

    def boot_id(self):
        return self.id


def make_timer(tmp_path, clock):
    store = JsonStore(tmp_path / "timer.json", dict)
    return CountdownTimer(store, monotonic=clock.monotonic, boottime=clock.boottime,
                          boot_id=clock.boot_id, maximum=7200, step=60)


def test_countdown_expires_once(tmp_path):
    clock = Clock()
    timer = make_timer(tmp_path, clock)
    timer.start(120)
    assert timer.remaining() == 120
    clock.mono += 120
    clock.boot += 120
    assert timer.poll() == "ring"
    assert timer.poll() == "ringing"
    timer.acknowledge()
    assert timer.poll() == "idle"


def test_suspend_expiration_is_missed_not_rung(tmp_path):
    clock = Clock()
    timer = make_timer(tmp_path, clock)
    timer.start(120)
    clock.boot += 180
    assert timer.poll() == "missed"
    assert timer.poll() == "missed"


def test_restart_with_elapsed_deadline_does_not_ring(tmp_path):
    clock = Clock()
    timer = make_timer(tmp_path, clock)
    timer.start(60)
    clock.id = "boot-b"
    restored = make_timer(tmp_path, clock)
    assert restored.poll() == "missed"


def test_duration_must_match_configured_step(tmp_path):
    timer = make_timer(tmp_path, Clock())
    try:
        timer.start(61)
    except ValueError:
        pass
    else:
        raise AssertionError("invalid duration accepted")
