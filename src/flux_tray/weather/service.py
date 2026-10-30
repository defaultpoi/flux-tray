"""Open-Meteo forecast client and normalized weather state."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from urllib.parse import urlencode
from urllib.request import urlopen

from flux_tray.core.storage import JsonStore


_WMO = {
    0: "Clear", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Depositing rime fog", 51: "Light drizzle", 53: "Drizzle",
    55: "Dense drizzle", 56: "Freezing drizzle", 57: "Dense freezing drizzle",
    61: "Light rain", 63: "Rain", 65: "Heavy rain", 66: "Freezing rain",
    67: "Heavy freezing rain", 71: "Light snow", 73: "Snow", 75: "Heavy snow",
    77: "Snow grains", 80: "Rain showers", 81: "Heavy showers", 82: "Violent showers",
    85: "Snow showers", 86: "Heavy snow showers", 95: "Thunderstorm",
    96: "Thunderstorm with hail", 99: "Thunderstorm with heavy hail",
}


def _fetch_json(url: str, timeout: float = 10.0) -> dict[str, Any]:
    with urlopen(url, timeout=timeout) as response:
        raw = response.read(1_000_001)
    if len(raw) > 1_000_000:
        raise ValueError("Weather response exceeds 1 MB")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("Invalid weather response")
    return data


class WeatherService:
    def __init__(self, store: JsonStore, latitude: float, longitude: float,
                 *, fetcher: Callable[[str], dict[str, Any]] = _fetch_json,
                 interval: int = 1800, alerts_client=None):
        if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            raise ValueError("Invalid latitude or longitude")
        self.store = store
        self.latitude = latitude
        self.longitude = longitude
        self.fetcher = fetcher
        self.alerts_client = alerts_client
        self.interval = max(300, int(interval))
        self.state = store.load()
        if not isinstance(self.state, dict):
            self.state = {}

    def refresh(self, *, force: bool = False) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        last = self.state.get("fetched_at")
        if not force and last:
            try:
                if now - datetime.fromisoformat(last) < timedelta(seconds=self.interval):
                    return self.state
            except ValueError:
                pass
        params = urlencode({
            "latitude": self.latitude, "longitude": self.longitude,
            "current": "temperature_2m,apparent_temperature,relative_humidity_2m,precipitation,weather_code,wind_speed_10m",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code",
            "forecast_days": 5, "timezone": "auto",
        })
        data = self.fetcher("https://api.open-meteo.com/v1/forecast?" + params)
        current = data.get("current") or {}
        daily = data.get("daily") or {}
        days = []
        count = min(5, len(daily.get("time", [])))
        for index in range(count):
            code = daily.get("weather_code", [None] * count)[index]
            days.append({
                "date": daily["time"][index],
                "high": self._at(daily, "temperature_2m_max", index),
                "low": self._at(daily, "temperature_2m_min", index),
                "rain_probability": self._at(daily, "precipitation_probability_max", index),
                "condition": _WMO.get(code, "Unknown"),
            })
        code = current.get("weather_code")
        alerts, alerts_error = [], None
        if self.alerts_client is not None:
            try:
                alerts = self.alerts_client.active_alerts()
            except Exception as exc:
                alerts_error = str(exc)
        self.state = {
            "fetched_at": now.isoformat(),
            "temperature": current.get("temperature_2m"),
            "feels_like": current.get("apparent_temperature"),
            "humidity": current.get("relative_humidity_2m"),
            "precipitation": current.get("precipitation"),
            "wind_speed": current.get("wind_speed_10m"),
            "condition": _WMO.get(code, "Unknown"),
            "forecast": days,
            "alerts": alerts,
            "alert_level": max((item.get("level", 0) for item in alerts), default=0),
            "alerts_error": alerts_error,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "error": None,
        }
        self.store.save(self.state)
        return self.state

    @staticmethod
    def _at(values: dict[str, Any], key: str, index: int):
        sequence = values.get(key) or []
        return sequence[index] if index < len(sequence) else None
