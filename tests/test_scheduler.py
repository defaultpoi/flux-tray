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
