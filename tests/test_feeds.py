from datetime import datetime, timezone

from flux_tray.core.storage import JsonStore
from flux_tray.feeds.fetch import FetchResult
from flux_tray.feeds.service import FeedService


def make_service(tmp_path, body, now=None):
    store = JsonStore(tmp_path / "feeds.json", lambda: {"feeds": [], "items": {}, "read_later": []})
    fixed = now or datetime(2026, 10, 30, 12, tzinfo=timezone.utc)
    service = FeedService(store, fetcher=lambda *a, **k: FetchResult(body), now=lambda: fixed)
    return service


def test_first_check_is_baseline_and_new_items_are_unread(tmp_path):
    body = b'''<?xml version="1.0"?><rss version="2.0"><channel><title>Example</title>
    <item><guid>old</guid><title>Old item</title><pubDate>Mon, 01 Jan 2024 10:00:00 GMT</pubDate></item>
    <item><guid>new</guid><title>Breaking: New item</title><pubDate>Fri, 30 Oct 2026 11:00:00 GMT</pubDate></item>
    </channel></rss>'''
    service = make_service(tmp_path, body)
    feed_id = service.add_feed("https://example.test/rss")
    assert service.check_feed(feed_id) == 1
    assert service.unread_count() == 1
    unread = service.unread_items()[0]
    assert unread["title"] == "Breaking: New item"
    old_item = next(item for item in service.state["items"].values() if item["title"] == "Old item")
    assert old_item["read"] is True


def test_second_check_discovers_new_item_and_read_later_is_not_unread(tmp_path):
    bodies = [b'''<rss><channel><item><guid>one</guid><title>First</title><pubDate>Mon, 01 Jan 2024 10:00:00 GMT</pubDate></item></channel></rss>''',
              b'''<rss><channel><item><guid>one</guid><title>First</title></item>
              <item><guid>two</guid><title>Second</title></item></channel></rss>''']
    store = JsonStore(tmp_path / "f.json", lambda: {"feeds": [], "items": {}, "read_later": []})
    service = FeedService(store, fetcher=lambda *a, **k: FetchResult(bodies.pop(0)))
    fid = service.add_feed("https://example.test/rss")
    service.check_feed(fid)
    assert service.check_feed(fid, force=True) == 1
    item = service.unread_items()[0]
    service.save_for_later(item["id"])
    assert service.unread_count() == 0
    assert item["id"] in service.state["read_later"]


def test_muted_feed_cannot_be_saved_for_later(tmp_path):
    body = b"<rss><channel><item><guid>x</guid><title>X</title></item></channel></rss>"
    service = make_service(tmp_path, body)
    fid = service.add_feed("https://example.test/rss")
    service.check_feed(fid)
    service.set_muted(fid, True)
    item_id = next(iter(service.state["items"]))
    service.save_for_later(item_id)
    assert service.state["read_later"] == []


def test_breaking_match_is_case_and_accent_insensitive_whole_word(tmp_path):
    body = b"<rss><channel><item><guid>x</guid><title>BREÁKING: Alert</title></item></channel></rss>"
    service = make_service(tmp_path, body)
    fid = service.add_feed("https://example.test/rss")
    service.check_feed(fid)
    item = next(iter(service.state["items"].values()))
    assert item["breaking"] is True


def test_feed_settings_and_order_are_persisted(tmp_path):
    service = make_service(tmp_path, b"<rss><channel/></rss>")
    first = service.add_feed("https://one.test/rss", "One")
    second = service.add_feed("https://two.test/rss", "Two")
    service.rename_feed(first, "Primary")
    service.set_interval(first, 30)
    service.reorder_feeds([second, first])
    assert [f["id"] for f in service.state["feeds"]] == [second, first]
    assert service.state["feeds"][1]["name"] == "Primary"
    assert service.state["feeds"][1]["interval"] == 60


def test_invalid_feed_order_is_rejected(tmp_path):
    service = make_service(tmp_path, b"<rss><channel/></rss>")
    service.add_feed("https://one.test/rss")
    try:
        service.reorder_feeds([])
    except ValueError:
        pass
    else:
        raise AssertionError("invalid order accepted")


def test_breaking_words_can_be_updated_and_reclassified(tmp_path):
    body = b"<rss><channel><item><guid>x</guid><title>Urgent alert</title></item></channel></rss>"
    service = make_service(tmp_path, body)
    feed_id = service.add_feed("https://example.test/rss")
    service.check_feed(feed_id)
    item = next(iter(service.state["items"].values()))
    assert not item["breaking"]
    service.set_breaking_words(["urgent"])
    assert item["breaking"]
    assert service.breaking_items() == [item]

def test_category_and_author_rules_route_items_to_read_later(tmp_path):
    body = b"""<rss><channel><item><guid>x</guid><title>News</title>
    <author>Jane Doe</author><category>Science</category></item></channel></rss>"""
    service = make_service(tmp_path, body)
    service.set_routing_rules([{"kind": "category", "value": "sci"}])
    fid = service.add_feed("https://example.test/rss")
    service.check_feed(fid)
    item_id = next(iter(service.state["items"]))
    assert service.unread_count() == 0
    assert item_id in service.state["read_later"]

def test_muting_removes_existing_read_later_items(tmp_path):
    body = b"""<rss><channel><item><guid>x</guid><title>News</title></item></channel></rss>"""
    service = make_service(tmp_path, body)
    fid = service.add_feed("https://example.test/rss")
    service.check_feed(fid)
    item_id = next(iter(service.state["items"]))
    service.save_for_later(item_id)
    service.set_muted(fid, True)
    assert item_id not in service.state["read_later"]

def test_configured_default_feed_interval_is_used(tmp_path):
    store = JsonStore(tmp_path / "f.json", lambda: {"feeds": [], "items": {}, "read_later": []})
    service = FeedService(store, default_interval=180)
    feed_id = service.add_feed("https://example.test/rss")
    feed = next(feed for feed in service.state["feeds"] if feed["id"] == feed_id)
    assert feed["interval"] == 180