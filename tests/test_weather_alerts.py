from datetime import datetime, timezone

from flux_tray.weather.alerts import MeteoAlarmClient


FEED = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:cap="urn:oasis:names:tc:emergency:cap:1.2">
  <entry>
    <id>severe-1</id><title>Heavy rain warning</title>
    <link href="https://alerts.example/severe-1" />
    <cap:severity>Severe</cap:severity><cap:areaDesc>Buzău County</cap:areaDesc>
    <cap:effective>2026-10-30T10:00:00Z</cap:effective>
    <cap:expires>2026-10-30T20:00:00Z</cap:expires>
    <cap:description>Heavy rainfall expected</cap:description>
  </entry>
  <entry>
    <id>expired</id><title>Expired warning</title>
    <cap:severity>Extreme</cap:severity><cap:areaDesc>Buzau</cap:areaDesc>
    <cap:effective>2026-10-30T08:00:00Z</cap:effective>
    <cap:expires>2026-10-30T09:00:00Z</cap:expires>
  </entry>
  <entry>
    <id>other</id><title>Other county</title>
    <cap:severity>Extreme</cap:severity><cap:areaDesc>Cluj</cap:areaDesc>
    <cap:effective>2026-10-30T10:00:00Z</cap:effective>
    <cap:expires>2026-10-30T20:00:00Z</cap:expires>
  </entry>
</feed>""".encode("utf-8")


def test_meteoalarm_filters_region_and_active_time_and_maps_severity():
    client = MeteoAlarmClient(
        country="romania", region="Buzau",
        fetcher=lambda url: FEED,
        now=lambda: datetime(2026, 10, 30, 12, tzinfo=timezone.utc),
    )
    alerts = client.active_alerts()
    assert len(alerts) == 1
    assert alerts[0]["id"] == "severe-1"
    assert alerts[0]["severity"] == "severe"
    assert alerts[0]["color"] == "orange"
    assert alerts[0]["url"] == "https://alerts.example/severe-1"


def test_meteoalarm_requires_region():
    try:
        MeteoAlarmClient(region="")
    except ValueError:
        pass
    else:
        raise AssertionError("empty region accepted")
