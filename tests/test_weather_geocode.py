import json

from flux_tray.weather.geocode import NominatimGeocoder


class Response:
    def __init__(self, data):
        self.data = json.dumps(data).encode()
    def __enter__(self):
        return self
    def __exit__(self, *_args):
        return False
    def read(self, _limit):
        return self.data


def test_nominatim_returns_valid_coordinates_and_uses_user_agent():
    requests = []
    def opener(request, timeout):
        requests.append((request, timeout))
        return Response([{"lat": "45.25", "lon": "26.67"}])
    geocoder = NominatimGeocoder(opener=opener)
    assert geocoder.lookup("Buzau, Romania") == (45.25, 26.67)
    assert "FluxTray" in requests[0][0].headers["User-agent"]


def test_nominatim_rejects_unknown_place():
    geocoder = NominatimGeocoder(opener=lambda *_args, **_kwargs: Response([]))
    try:
        geocoder.lookup("Not a real place")
    except ValueError as exc:
        assert "not found" in str(exc).lower()
    else:
        raise AssertionError("unknown place accepted")
