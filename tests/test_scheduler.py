from flux_tray.core.scheduler import Scheduler


def test_job_is_due_after_initial_delay_and_does_not_overlap():
    now = [100.0]
    calls = []
    scheduler = Scheduler(clock=lambda: now[0])
    scheduler.add("feeds", 60, lambda: calls.append("tick"), initial_delay=0)
    due = scheduler.due()
    assert [job.name for job in due] == ["feeds"]
    assert scheduler.due() == []
    due[0].callback()
    scheduler.set_running("feeds", False)
    assert calls == ["tick"]
    assert scheduler.due() == []
    now[0] += 60
    assert [job.name for job in scheduler.due()] == ["feeds"]


def test_retry_overrides_regular_interval():
    now = [0.0]
    scheduler = Scheduler(clock=lambda: now[0])
    scheduler.add("feed", 3600, lambda: None)
    scheduler.retry("feed", 120)
    now[0] = 119
    assert scheduler.due() == []
    now[0] = 120
    assert len(scheduler.due()) == 1


import math
import pytest


@pytest.mark.parametrize("interval", [0, -1, math.nan, math.inf, -math.inf])
def test_add_rejects_non_positive_or_non_finite_intervals(interval):
    scheduler = Scheduler()
    with pytest.raises(ValueError, match="finite positive"):
        scheduler.add("feeds", interval, lambda: None)


@pytest.mark.parametrize("delay", [math.nan, math.inf, -math.inf])
def test_add_rejects_non_finite_initial_delay(delay):
    scheduler = Scheduler()
    with pytest.raises(ValueError, match="finite non-negative"):
        scheduler.add("feeds", 60, lambda: None, initial_delay=delay)


@pytest.mark.parametrize("delay", [math.nan, math.inf, -math.inf])
def test_retry_rejects_non_finite_delay(delay):
    scheduler = Scheduler()
    scheduler.add("feeds", 60, lambda: None)
    with pytest.raises(ValueError, match="finite non-negative"):
        scheduler.retry("feeds", delay)


def test_add_rejects_invalid_name_and_callback():
    scheduler = Scheduler()
    with pytest.raises(ValueError, match="job name"):
        scheduler.add(" ", 60, lambda: None)
    with pytest.raises(TypeError, match="callable"):
        scheduler.add("feeds", 60, None)
