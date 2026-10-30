from datetime import datetime, timezone

from flux_tray.core.storage import JsonStore
from flux_tray.media.service import MediaService


class FakeYtDlp:
    def __init__(self):
        self.items = [[{"id": "one", "title": "Show S01E01"},
                       {"id": "two", "title": "Show S01E02"}],
                      [{"id": "one", "title": "Show S01E01"},
                       {"id": "two", "title": "Show S01E02"},
                       {"id": "three", "title": "Show S01E03"}]]

    def list_episodes(self, url, source_id):
        from flux_tray.media.episodes import normalize_episode
        return [normalize_episode(item, source_id).to_dict() for item in self.items.pop(0)]


def test_first_check_is_baseline_then_new_episodes_are_queued(tmp_path):
    store = JsonStore(tmp_path / "media.json", lambda: {"sources": [], "episodes": {}, "queue": [], "watched": []})
    service = MediaService(store, tmp_path / "plugins", yt_dlp=FakeYtDlp(),
                           now=lambda: datetime(2026, 10, 30, tzinfo=timezone.utc))
    source_id = service.add_source("youtube", "https://youtube.com/playlist?list=x")
    assert service.check_source(source_id) == 0
    assert service.state["queue"] == []
    assert service.check_source(source_id, force=True) == 1
    assert len(service.state["queue"]) == 1
    assert service.next_queued()["title"] == "Show S01E03"


def test_ahead_zero_keeps_new_items_manual(tmp_path):
    store = JsonStore(tmp_path / "media.json", lambda: {"sources": [], "episodes": {}, "queue": [], "watched": []})
    service = MediaService(store, tmp_path / "plugins", ahead=0,
                           yt_dlp=FakeYtDlp(), now=lambda: datetime.now(timezone.utc))
    source_id = service.add_source("youtube", "https://youtube.com/playlist?list=x")
    service.check_source(source_id)
    service.check_source(source_id, force=True)
    assert service.state["queue"] == []

def test_ahead_queue_downloads_sequentially(tmp_path):
    class FakeDownloader:
        def __init__(self):
            self.calls = []
        def download(self, episode, output_dir, **kwargs):
            self.calls.append(episode["id"])
            return str(tmp_path / (episode["id"].split(":")[-1] + ".mkv"))

    downloader = FakeDownloader()
    store = JsonStore(tmp_path / "media.json", lambda: {"sources": [], "episodes": {}, "queue": [], "watched": []})
    service = MediaService(store, tmp_path / "plugins", ahead=2, yt_dlp=FakeYtDlp(),
                           downloader=downloader)
    source_id = service.add_source("youtube", "https://youtube.com/playlist?list=x")
    service.check_source(source_id)
    service.check_source(source_id, force=True)
    first = service.download_next()
    assert first["status"] == "downloaded"
    assert len(downloader.calls) == 1
    assert len(service.state["queue"]) == 0

def test_resolution_sort_uses_monitor_with_headroom_and_manual_override(tmp_path):
    store = JsonStore(tmp_path / "media.json", lambda: {"sources": [], "episodes": {}, "queue": [], "watched": []})
    automatic = MediaService(store, tmp_path / "plugins", screen_height=768)
    assert automatic._format_sort() == "res:652"
    manual = MediaService(store, tmp_path / "plugins", screen_height=768,
                          yt_dlp_sort="height:480")
    assert manual._format_sort() == "height:480"


def test_resolution_sort_detects_current_monitor_each_time(tmp_path):
    class Display:
        height = 768
        def screen_height(self):
            return self.height
    display = Display()
    store = JsonStore(tmp_path / "media.json", lambda: {"sources": [], "episodes": {}, "queue": [], "watched": []})
    service = MediaService(store, tmp_path / "plugins", display=display)
    assert service._format_sort() == "res:652"
    display.height = 1080
    assert service._format_sort() == "res:918"



def test_hls_episode_streams_directly_and_progress_marks_watched(tmp_path):
    class Player:
        def __init__(self, url):
            self.url = url
            self.loaded = None
        def load(self, url, title):
            self.loaded = (url, title)
        def get_property(self, name):
            return {"time-pos": 95.0, "duration": 100.0, "path": self.url}[name]

    url = "https://media.example.test/episode/index.m3u8"
    player = Player(url)
    store = JsonStore(tmp_path / "media.json",
                      lambda: {"sources": [], "episodes": {}, "queue": [], "watched": []})
    service = MediaService(store, tmp_path / "plugins", player=player)
    service.state["episodes"]["hls"] = {
        "id": "hls", "title": "HLS episode", "url": url, "ext": "m3u8",
        "status": "new", "source_id": "source",
    }

    service.play_episode("hls")
    assert player.loaded == (url, "HLS episode")
    assert service.update_playback_progress() is True
    assert service.state["episodes"]["hls"]["status"] == "watched"


def test_live_hls_stream_is_played_without_download(tmp_path):
    class Player:
        def __init__(self):
            self.loaded = None
        def load(self, url, title):
            self.loaded = (url, title)

    player = Player()
    store = JsonStore(tmp_path / "media.json",
                      lambda: {"sources": [], "episodes": {}, "queue": [], "watched": []})
    service = MediaService(store, tmp_path / "plugins", player=player)
    url = "https://live.example.test/channel/index.m3u8"
    service.state["episodes"]["live"] = {
        "id": "live", "title": "Live channel", "url": url, "is_live": True,
        "status": "new", "source_id": "source",
    }

    service.play_episode("live")
    assert player.loaded == (url, "Live channel")
