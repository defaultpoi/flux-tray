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
    runner = lambda argv, **kwargs: ProcessResult(tuple(argv), 0, "https://cdn.example/live.m3u8\\n", "")
    probe = StreamlinkProbe(runner=runner)
    store = JsonStore(tmp_path / "live.json", lambda: {"channels": []})
    service = LiveService(store, probe, player=player)
    channel_id = service.add_channel("youtube", "Example", "https://youtube.com/@example/live")
    service.state["channels"][0]["metadata"] = {"title": "Stream title"}
    service.play_channel(channel_id)
    assert player.loaded == ("https://cdn.example/live.m3u8", "Youtube · Example · Stream title")
