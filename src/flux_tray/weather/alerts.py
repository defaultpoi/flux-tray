"""MeteoAlarm Atom/CAP warning feed parser."""

from __future__ import annotations

import unicodedata
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.request import urlopen
from typing import Callable


COUNTRY_FEED = "https://feeds.meteoalarm.org/feeds/meteoalarm-legacy-atom-{country}"
_SEVERITY = {"minor": 1, "moderate": 2, "severe": 3, "extreme": 4}


def _normal(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.casefold())
    return "".join(char for char in value if not unicodedata.combining(char))


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].casefold()


def _child_text(element: ET.Element, name: str) -> str:
    for child in element.iter():
        if _local(child.tag) == name.casefold() and child.text:
            return child.text.strip()
    return ""


def _time(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
    except ValueError:
        return None


class MeteoAlarmClient:
    def __init__(self, *, country: str = "romania", region: str,
                 fetcher: Callable[[str], bytes] | None = None,
                 now: Callable[[], datetime] | None = None):
        self.country = country.strip().casefold().replace(" ", "-")
        self.region = region.strip()
        self.fetcher = fetcher or self._fetch
        self.now = now or (lambda: datetime.now(timezone.utc))
        if not self.country or not self.region:
            raise ValueError("MeteoAlarm requires a country and region")

    @staticmethod
    def _fetch(url: str) -> bytes:
        with urlopen(url, timeout=12) as response:
            raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ValueError("MeteoAlarm response exceeds 2 MB")
        return raw

    def active_alerts(self) -> list[dict]:
        url = COUNTRY_FEED.format(country=self.country)
        root = ET.fromstring(self.fetcher(url))
        now = self.now()
        active = []
        for entry in root.iter():
            if _local(entry.tag) != "entry":
                continue
            area = _child_text(entry, "areaDesc") or _child_text(entry, "area")
            if self.region and _normal(self.region) not in _normal(area):
                continue
            severity = (_child_text(entry, "severity") or _child_text(entry, "awareness_level")).casefold()
            if severity not in _SEVERITY:
                continue
            effective = _time(_child_text(entry, "effective") or _child_text(entry, "onset"))
            expires = _time(_child_text(entry, "expires"))
            if effective and effective > now:
                continue
            if expires and expires <= now:
                continue
            title = _child_text(entry, "title")
            identifier = _child_text(entry, "id")
            link = next((child.attrib.get("href") for child in entry
                         if _local(child.tag) == "link" and child.attrib.get("href")), None)
            active.append({
                "id": identifier or title,
                "title": title or "Weather warning",
                "area": area,
                "severity": severity,
                "level": _SEVERITY[severity],
                "color": "yellow" if severity in {"minor", "moderate"} else
                         "orange" if severity == "severe" else "red",
                "description": _child_text(entry, "description") or _child_text(entry, "summary"),
                "effective": effective.isoformat() if effective else None,
                "expires": expires.isoformat() if expires else None,
                "url": link,
            })
        return sorted(active, key=lambda item: item["level"], reverse=True)
