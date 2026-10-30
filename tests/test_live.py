from flux_tray.core.process import ProcessResult
from flux_tray.core.storage import JsonStore
from flux_tray.live.service import LiveService, StreamlinkProbe


def test_streamlink_json_live_metadata():
    payload = '{"streams":{"720p":{},"best":{}},"metadata":{"author":"channel","title":"Live"}}'
    probe = StreamlinkProbe(runner=lambda argv, **kwargs: ProcessResult(tuple(argv), 0, payload, ""))
    result = probe.check("https://youtube.com/@channel/live")
    assert result["status"] == "live"
    assert result["metadata"]["title"] == "Live"


def test_streamlink_offline_is_not_an_error():
    payload = '{"streams":{},"metadata":{}}'
    probe = StreamlinkProbe(runner=lambda argv, **kwargs: ProcessResult(tuple(argv), 0, payload, ""))
    assert probe.check("https://twitch.tv/channel")["status"] == "offline"


def test_live_service_preserves_last_known_state_on_error(tmp_path):
    responses = [
        {"status": "live", "metadata": {"title": "Stream"}, "streams": ["best"]},
    ]

    class Probe:
        def check(self, _url):
            if responses:
                return responses.pop(0)
            raise RuntimeError("temporary network failure")

    store = JsonStore(tmp_path / "live.json", lambda: {"channels": []})
    service = LiveService(store, Probe())
    channel_id = service.add_channel("twitch", "Channel", "https://twitch.tv/channel")
    assert service.check_channel(channel_id, force=True) == "live"
    assert service.check_channel(channel_id, force=True) == "live"
    channel = service.state["channels"][0]
    assert channel["last_error"] == "temporary network failure"

def test_play_channel_resolves_url_and_reuses_injected_player(tmp_path):
    class Player:
        def __init__(self):
            self.loaded = None
        def load(self, url, title):
            self.loaded = (url, title)

    player = Player()
    runner = lambda argv, **kwargs: ProcessResult(tuple(argv), 0, "https://cdn.example/live.m3u8\n", "")
    probe = StreamlinkProbe(runner=runner)
    store = JsonStore(tmp_path / "live.json", lambda: {"channels": []})
    service = LiveService(store, probe, player=player)
    channel_id = service.add_channel("youtube", "Example", "https://youtube.com/@example/live")
    service.state["channels"][0]["metadata"] = {"title": "Stream title"}
    service.play_channel(channel_id)
    assert player.loaded == ("https://cdn.example/live.m3u8", "Youtube · Example · Stream title")


def test_twitch_batch_checks_preserve_state_on_batch_failure(tmp_path):
    class Twitch:
        def __init__(self):
            self.calls = []
        def check_many(self, urls):
            self.calls.append(urls)
            if len(self.calls) == 1:
                return {url: {"status": "live", "metadata": {"title": "On air"}, "streams": ["best"]}
                        for url in urls}
            raise RuntimeError("temporary GQL outage")
        def check(self, url):
            raise AssertionError("single lookup should not be used for batch-capable probe")

    twitch = Twitch()
    store = JsonStore(tmp_path / "live.json", lambda: {"channels": []})
    service = LiveService(store, probe=StreamlinkProbe(runner=lambda *a, **k: None),
                          twitch_probe=twitch)
    first = service.add_channel("twitch", "One", "https://twitch.tv/one")
    second = service.add_channel("twitch", "Two", "https://twitch.tv/two")
    assert service.check_due(force=True) == 2
    assert len(twitch.calls) == 1 and len(twitch.calls[0]) == 2
    service.check_due(force=True)
    assert service.channel_state(first)["status"] == "live"
    assert service.channel_state(second)["status"] == "live"
    assert service.channel_state(first)["last_error"] == "temporary GQL outage"


def test_live_channel_schedule_validation_and_persistence(tmp_path):
    store = JsonStore(tmp_path / "live.json", lambda: {"channels": []})
    service = LiveService(store)
    channel_id = service.add_channel("youtube", "Example", "https://youtube.com/@example/live")
    service.set_schedule(channel_id, [{"weekday": 4, "time": "19:30"}])
    assert service.channel_state(channel_id)["schedule"] == [{"weekday": 4, "time": "19:30"}]
    try:
        service.set_schedule(channel_id, [{"weekday": 8, "time": "19:30"}])
    except ValueError:
        pass
    else:
        raise AssertionError("invalid weekday accepted")
