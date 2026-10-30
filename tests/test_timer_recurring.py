from datetime import datetime, timezone

import pytest

from flux_tray.core.storage import JsonStore
from flux_tray.timers.service import CountdownTimer


def make_timer(tmp_path):
    return CountdownTimer(JsonStore(tmp_path / "timer.json", dict))


def test_weekly_alarm_fires_once_per_date_and_persists(tmp_path):
    timer = make_timer(tmp_path)
    timer.add_schedule([0, 2], "07:30", "Morning reminder")
    monday = datetime(2026, 10, 26, 7, 30, tzinfo=timezone.utc)

    alert = timer.poll_schedules(monday)
    assert alert["label"] == "Morning reminder"
    assert timer.poll_schedules(monday) == alert
    assert timer.state["schedules"][0]["last_fired"] == "2026-10-26"

    restarted = make_timer(tmp_path)
    assert restarted.poll_schedules(monday) == alert


def test_alarm_does_not_fire_on_unselected_weekday(tmp_path):
    timer = make_timer(tmp_path)
    timer.add_schedule([0], "07:30", "Monday only")
    wednesday = datetime(2026, 10, 28, 7, 30, tzinfo=timezone.utc)
    assert timer.poll_schedules(wednesday) is None


def test_alarm_validation_and_removal(tmp_path):
    timer = make_timer(tmp_path)
    with pytest.raises(ValueError):
        timer.add_schedule([], "07:30", "Missing days")
    with pytest.raises(ValueError):
        timer.add_schedule([1], "25:00", "Invalid time")
    with pytest.raises(ValueError):
        timer.add_schedule([7], "07:30", "Invalid weekday")

    alarm = timer.add_schedule([1], "07:30", "Remove me")
    timer.remove_schedule(alarm["id"])
    assert timer.schedules == []


def test_alarm_can_be_snoozed_and_dismissed(tmp_path, monkeypatch):
    timer = make_timer(tmp_path)
    alarm = timer.add_schedule([0], "07:30", "Snooze me")
    now = datetime(2026, 10, 26, 7, 30, tzinfo=timezone.utc)
    monkeypatch.setattr("flux_tray.timers.service.time.time", lambda: 1000.0)

    first = timer.poll_schedules(now)
    assert first["schedule_id"] == alarm["id"]
    timer.snooze_schedule_alert(5)
    assert timer.poll_schedules(now) is None

    monkeypatch.setattr("flux_tray.timers.service.time.time", lambda: 1300.0)
    assert timer.poll_schedules(now)["label"] == "Snooze me"
    timer.dismiss_schedule_alert()
    assert timer.poll_schedules(now) is None



def test_alarm_catches_up_if_app_wakes_after_scheduled_time(tmp_path):
    timer = make_timer(tmp_path)
    timer.add_schedule([0], "07:30", "Missed morning alarm")
    monday_later = datetime(2026, 10, 26, 8, 15, tzinfo=timezone.utc)
    alert = timer.poll_schedules(monday_later)
    assert alert["label"] == "Missed morning alarm"
    assert alert["fired_at"].startswith("2026-10-26T08:15")



def test_countdown_start_and_cancel_preserve_weekly_alarms(tmp_path):
    timer = make_timer(tmp_path)
    alarm = timer.add_schedule([0, 4], "07:30", "Keep this alarm")
    timer.start(60)
    timer.cancel()

    restored = make_timer(tmp_path)
    assert [item["id"] for item in restored.schedules] == [alarm["id"]]
    assert restored.state["status"] == "idle"



def test_weekly_alarm_can_be_edited_without_changing_its_identity(tmp_path):
    timer = make_timer(tmp_path)
    alarm = timer.add_schedule([0], "07:30", "Old label")
    updated = timer.update_schedule(alarm["id"], [1, 3], "08:15", "New label")
    assert updated["id"] == alarm["id"]
    assert updated["weekdays"] == [1, 3]
    assert updated["time"] == "08:15"
    assert updated["label"] == "New label"
    assert updated["last_fired"] is None
