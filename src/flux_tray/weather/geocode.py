"""One-time Nominatim geocoding for configured place names."""

from __future__ import annotations

import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class NominatimGeocoder:
    def __init__(self, *, timeout: float = 10.0, opener=urlopen):
        self.timeout = timeout
        self.opener = opener

    def lookup(self, location: str) -> tuple[float, float]:
        query = urlencode({"q": location, "format": "jsonv2", "limit": 1})
        request = Request(
            "https://nominatim.openstreetmap.org/search?" + query,
            headers={"User-Agent": "FluxTray/0.1 (personal desktop application)",
                     "Accept": "application/json"},
        )
        with self.opener(request, timeout=self.timeout) as response:
            raw = response.read(100_001)
        if len(raw) > 100_000:
            raise ValueError("Nominatim response exceeds 100 KB")
        results = json.loads(raw)
        if not isinstance(results, list) or not results:
            raise ValueError(f"Location not found: {location}")
        latitude, longitude = float(results[0]["lat"]), float(results[0]["lon"])
        if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            raise ValueError("Nominatim returned invalid coordinates")
        return latitude, longitude
