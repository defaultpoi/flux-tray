from flux_tray.core.storage import JsonStore
from flux_tray.weather.service import WeatherService


def test_weather_normalizes_current_and_five_day_forecast(tmp_path):
    payload = {
        "current": {"temperature_2m": 18.5, "apparent_temperature": 17.0,
                    "relative_humidity_2m": 60, "precipitation": 0.0,
                    "weather_code": 2, "wind_speed_10m": 12.0},
        "daily": {"time": ["2026-10-30"], "temperature_2m_max": [20.0],
                  "temperature_2m_min": [10.0], "precipitation_probability_max": [20],
                  "weather_code": [3]},
    }
    service = WeatherService(JsonStore(tmp_path / "weather.json", dict), 45.0, 26.0,
                             fetcher=lambda _url: payload)
    state = service.refresh()
    assert state["temperature"] == 18.5
    assert state["condition"] == "Partly cloudy"
    assert state["forecast"][0]["high"] == 20.0


def test_weather_refresh_uses_cached_result_until_interval(tmp_path):
    calls = []
    payload = {"current": {}, "daily": {}}
    service = WeatherService(JsonStore(tmp_path / "weather.json", dict), 45.0, 26.0,
                             fetcher=lambda url: calls.append(url) or payload)
    first = service.refresh()
    second = service.refresh()
    assert len(calls) == 1
    assert second == first


def test_weather_refresh_includes_alerts_without_failing_forecast(tmp_path):
    class Alerts:
        def active_alerts(self):
            return [{"id": "warning", "level": 3, "severity": "severe"}]
    service = WeatherService(
        JsonStore(tmp_path / "weather.json", dict), 45.0, 26.0,
        fetcher=lambda _url: {"current": {}, "daily": {}},
        alerts_client=Alerts(),
    )
    state = service.refresh()
    assert state["alerts"][0]["id"] == "warning"
    assert state["alert_level"] == 3
    assert state["alerts_error"] is None


def test_weather_alert_failure_does_not_discard_forecast(tmp_path):
    class Alerts:
        def active_alerts(self):
            raise RuntimeError("feed unavailable")
    service = WeatherService(
        JsonStore(tmp_path / "weather.json", dict), 45.0, 26.0,
        fetcher=lambda _url: {"current": {"temperature_2m": 10}, "daily": {}},
        alerts_client=Alerts(),
    )
    state = service.refresh()
    assert state["temperature"] == 10
    assert state["alerts"] == []
    assert state["alerts_error"] == "feed unavailable"
