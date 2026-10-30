import json

from flux_tray.live.twitch import TwitchProbe, channel_login


class Response:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()
    def __enter__(self):
        return self
    def __exit__(self, *_args):
        return False
    def read(self, _limit):
        return self.payload


def test_channel_login_accepts_channel_urls_and_rejects_non_channels():
    assert channel_login("https://www.twitch.tv/Example") == "Example"
    try:
        channel_login("https://www.twitch.tv/directory")
    except ValueError:
        pass
    else:
        raise AssertionError("reserved Twitch path accepted")


def test_twitch_probe_normalizes_live_and_offline_states():
    payload = [
        {"data": {"user": {"displayName": "Example", "stream": {
            "title": "Live now", "viewersCount": 123,
            "createdAt": "2026-10-30T10:00:00Z", "game": {"name": "Art"},
        }}}},
        {"data": {"user": {"displayName": "Offline", "stream": None}}},
    ]
    requests = []
    def opener(request, timeout):
        requests.append((request, timeout))
        return Response(payload)
    probe = TwitchProbe(opener=opener)
    results = probe.check_many([
        "https://twitch.tv/example", "https://twitch.tv/offline",
    ])
    live = results["https://twitch.tv/example"]
    assert live["status"] == "live"
    assert live["metadata"]["viewers"] == 123
    assert live["metadata"]["category"] == "Art"
    assert results["https://twitch.tv/offline"]["status"] == "offline"
    assert len(requests) == 1
    assert len(json.loads(requests[0][0].data)) == 2


def test_twitch_probe_batches_at_twenty():
    calls = []
    def opener(request, timeout):
        body = json.loads(request.data)
        calls.append(len(body))
        return Response([{"data": {"user": None}} for _ in body])
    probe = TwitchProbe(opener=opener)
    urls = [f"https://twitch.tv/channel{i}" for i in range(41)]
    results = probe.check_many(urls)
    assert len(results) == 41
    assert calls == [20, 20, 1]
