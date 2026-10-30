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
    assert service.state["download"]["status"] == "completed"
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



def test_media_source_can_be_renamed(tmp_path):
    store = JsonStore(tmp_path / "media.json",
                      lambda: {"sources": [], "episodes": {}, "queue": [], "watched": []})
    service = MediaService(store, tmp_path / "plugins")
    source_id = service.add_source("rss", "https://example.test/media.xml", "Old name")
    service.rename_source(source_id, "My media")
    assert service.state["sources"][0]["name"] == "My media"



def test_media_source_can_change_type_url_and_name(tmp_path):
    store = JsonStore(tmp_path / "media.json",
                      lambda: {"sources": [], "episodes": {}, "queue": [], "watched": []})
    service = MediaService(store, tmp_path / "plugins")
    source_id = service.add_source("rss", "https://example.test/old.xml", "Old")
    service.update_source(source_id, "youtube", "https://youtube.com/@example", "New")
    source = service.state["sources"][0]
    assert source["kind"] == "youtube"
    assert source["url"] == "https://youtube.com/@example"
    assert source["name"] == "New"
    assert source["initialized"] is False



def test_download_failure_is_persisted_for_manual_retry(tmp_path):
    class FailingDownloader:
        def download(self, episode, output_dir, **kwargs):
            raise RuntimeError("network disconnected")

    store = JsonStore(tmp_path / "media.json",
                      lambda: {"sources": [], "episodes": {}, "queue": [], "watched": []})
    service = MediaService(store, tmp_path / "plugins", ahead=1,
                           yt_dlp=FakeYtDlp(), downloader=FailingDownloader())
    source_id = service.add_source("youtube", "https://youtube.com/playlist?list=x")
    service.check_source(source_id)
    service.check_source(source_id, force=True)

    try:
        service.download_next()
    except RuntimeError as exc:
        assert "network disconnected" in str(exc)
    else:
        raise AssertionError("download failure was not propagated")

    assert service.state["download"]["status"] == "failed"
    assert service.state["download"]["error"] == "network disconnected"
    assert service.next_queued() is not None



def test_media_service_forwards_and_stores_download_progress(tmp_path):
    class ProgressDownloader:
        def download(self, episode, output_dir, **kwargs):
            kwargs["progress_callback"]({"percent": 37.5, "downloaded_bytes": 375,
                                         "total_bytes": 1000, "eta": 8})
            return str(tmp_path / "episode.mkv")

    store = JsonStore(tmp_path / "media.json",
                      lambda: {"sources": [], "episodes": {}, "queue": [], "watched": []})
    service = MediaService(store, tmp_path / "plugins", ahead=1,
                           yt_dlp=FakeYtDlp(), downloader=ProgressDownloader())
    source_id = service.add_source("youtube", "https://youtube.com/playlist?list=x")
    service.check_source(source_id)
    service.check_source(source_id, force=True)
    updates = []
    service.download_next(progress_callback=updates.append)

    assert updates[0]["percent"] == 37.5
    assert service.state["download"]["percent"] == 100.0
    assert service.state["download"]["status"] == "completed"



def test_interrupted_download_is_recovered_on_service_restart(tmp_path):
    store = JsonStore(tmp_path / "media.json",
        lambda: {"sources": [], "episodes": {}, "queue": [], "watched": [],
                 "download": {"status": "downloading", "title": "Episode"}})
    service = MediaService(store, tmp_path / "plugins")
    assert service.state["download"]["status"] == "failed"
    assert "interrupted" in service.state["download"]["error"]


def test_default_media_order_preserves_driver_listing(tmp_path):
    store = JsonStore(tmp_path / "media.json",
                      lambda: {"sources": [], "episodes": {}, "queue": [], "watched": []})
    service = MediaService(store, tmp_path / "plugins", ahead=3)
    source_id = service.add_source("rss", "https://example.test/feed.xml")
    service.state["episodes"] = {
        "later": {"id": "later", "source_id": source_id, "status": "new", "source_order": 0},
        "earlier": {"id": "earlier", "source_id": source_id, "status": "new", "source_order": 1},
    }
    service._fill_queue(source_id)
    assert service.state["queue"] == ["later", "earlier"]


def test_media_source_oldest_order_uses_episode_numbers(tmp_path):
    store = JsonStore(tmp_path / "media.json",
                      lambda: {"sources": [], "episodes": {}, "queue": [], "watched": []})
    service = MediaService(store, tmp_path / "plugins", ahead=3)
    source_id = service.add_source("rss", "https://example.test/feed.xml", order="oldest")
    service.state["episodes"] = {
        "ep3": {"id": "ep3", "source_id": source_id, "status": "new",
                "season": 1, "episode": 3, "source_order": 0},
        "ep1": {"id": "ep1", "source_id": source_id, "status": "new",
                "season": 1, "episode": 1, "source_order": 1},
        "ep2": {"id": "ep2", "source_id": source_id, "status": "new",
                "season": 1, "episode": 2, "source_order": 2},
    }
    service._fill_queue(source_id)
    assert service.state["queue"] == ["ep1", "ep2", "ep3"]


def test_media_source_newest_order_uses_dates_when_numbers_missing(tmp_path):
    store = JsonStore(tmp_path / "media.json",
                      lambda: {"sources": [], "episodes": {}, "queue": [], "watched": []})
    service = MediaService(store, tmp_path / "plugins", ahead=3)
    source_id = service.add_source("rss", "https://example.test/feed.xml", order="newest")
    service.state["episodes"] = {
        "old": {"id": "old", "source_id": source_id, "status": "new",
                "date": "2026-01-01", "source_order": 0},
        "new": {"id": "new", "source_id": source_id, "status": "new",
                "date": "2026-03-01", "source_order": 1},
        "middle": {"id": "middle", "source_id": source_id, "status": "new",
                   "date": "2026-02-01", "source_order": 2},
    }
    service._fill_queue(source_id)
    assert service.state["queue"] == ["new", "middle", "old"]


def test_media_source_order_can_be_updated_and_invalid_values_rejected(tmp_path):
    store = JsonStore(tmp_path / "media.json",
                      lambda: {"sources": [], "episodes": {}, "queue": [], "watched": []})
    service = MediaService(store, tmp_path / "plugins")
    source_id = service.add_source("rss", "https://example.test/feed.xml")
    service.update_source(source_id, "rss", "https://example.test/feed.xml", "Feed",
                          order="newest")
    assert service.state["sources"][0]["order"] == "newest"
    try:
        service.update_source(source_id, "rss", "https://example.test/feed.xml", "Feed",
                              order="random")
    except ValueError as exc:
        assert "oldest or newest" in str(exc)
    else:
        raise AssertionError("Invalid source order was accepted")


def test_media_episode_without_registered_source_can_be_marked_watched(tmp_path):
    store = JsonStore(tmp_path / "media.json",
                      lambda: {"sources": [], "episodes": {}, "queue": [], "watched": []})
    service = MediaService(store, tmp_path / "plugins")
    service.state["episodes"]["orphan"] = {
        "id": "orphan", "source_id": "removed-source", "status": "new",
    }
    service.mark_watched("orphan")
    assert service.state["episodes"]["orphan"]["status"] == "watched"
