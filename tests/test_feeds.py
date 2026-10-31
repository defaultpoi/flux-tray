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
    body = "<rss><channel><item><guid>x</guid><title>BREÁKING: Alert</title></item></channel></rss>".encode("utf-8")
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
    <author>jane@example.com (Jane Doe)</author><category>Science</category></item></channel></rss>"""
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


def test_breaking_item_notification_is_consumed_once(tmp_path):
    body = "<rss><channel><item><guid>x</guid><title>Breaking: Alert</title></item></channel></rss>".encode("utf-8")
    service = make_service(tmp_path, body)
    feed_id = service.add_feed("https://example.test/rss")
    service.check_feed(feed_id)

    pending = service.take_unnotified_breaking_items()
    assert len(pending) == 1
    assert pending[0]["breaking_notified"] is True
    assert service.take_unnotified_breaking_items() == []


def test_feed_website_url_is_saved_from_feed_metadata(tmp_path):
    body = b'''<rss version="2.0"><channel><title>Example</title>
    <link>https://example.test/</link>
    <item><guid>one</guid><title>One</title></item>
    </channel></rss>'''
    service = make_service(tmp_path, body)
    feed_id = service.add_feed("https://example.test/feed.xml")
    service.check_feed(feed_id)
    feed = next(feed for feed in service.state["feeds"] if feed["id"] == feed_id)
    assert feed["site_url"] == "https://example.test/"


def test_add_feed_rejects_malformed_http_urls(tmp_path):
    service = make_service(tmp_path, b"<rss><channel/></rss>")
    for url in ("http:///missing-host", "https://example.test:99999/feed",
                "file:///etc/passwd", "https://example.test/feed with spaces"):
        try:
            service.add_feed(url)
        except ValueError as exc:
            assert "valid HTTP" in str(exc)
        else:
            raise AssertionError(f"Malformed feed URL was accepted: {url}")


def test_per_feed_mute_rules(tmp_path):
    """Test that per-feed mute rules mark matching items as read (not unread)."""
    body = b'''<?xml version="1.0"?><rss version="2.0"><channel>
    <item><guid>1</guid><title>Tech news</title><category>Technology</category></item>
    <item><guid>2</guid><title>Sports news</title><category>Sports</category></item>
    </channel></rss>'''
    service = make_service(tmp_path, body)
    # Add feed with mute rule for "Technology" category
    fid = service.add_feed("https://example.test/rss", mute_rules=["category:Technology"])
    service.check_feed(fid)
    # Only Sports item should be unread
    assert service.unread_count() == 1
    unread = service.unread_items()[0]
    assert unread["title"] == "Sports news"
    # Tech item should be marked read
    tech_item = next(item for item in service.state["items"].values() if item["title"] == "Tech news")
    assert tech_item["read"] is True
    assert tech_item["id"] not in service.state["read_later"]


def test_per_feed_mute_rules_author(tmp_path):
    """Test that per-feed mute rules work for author patterns."""
    body = b'''<?xml version="1.0"?><rss version="2.0"><channel>
    <item><guid>1</guid><title>By John</title><author>john@example.com (John Doe)</author></item>
    <item><guid>2</guid><title>By Jane</title><author>jane@example.com (Jane Smith)</author></item>
    </channel></rss>'''
    service = make_service(tmp_path, body)
    fid = service.add_feed("https://example.test/rss", mute_rules=["author:John"])
    service.check_feed(fid)
    assert service.unread_count() == 1
    unread = service.unread_items()[0]
    assert unread["title"] == "By Jane"


def test_per_feed_read_later_rules(tmp_path):
    """Test that per-feed read-later rules route items to read_later."""
    body = b'''<?xml version="1.0"?><rss version="2.0"><channel>
    <item><guid>1</guid><title>Tech news</title><category>Technology</category></item>
    <item><guid>2</guid><title>Sports news</title><category>Sports</category></item>
    </channel></rss>'''
    service = make_service(tmp_path, body)
    # Add feed with read-later rule for "Technology" category
    fid = service.add_feed("https://example.test/rss", read_later_rules=["category:Technology"])
    service.check_feed(fid)
    # Sports should be unread, Tech should be in read_later
    assert service.unread_count() == 1
    unread = service.unread_items()[0]
    assert unread["title"] == "Sports news"
    tech_item = next(item for item in service.state["items"].values() if item["title"] == "Tech news")
    assert tech_item["read"] is True
    assert tech_item["id"] in service.state["read_later"]


def test_mute_beats_read_later(tmp_path):
    """Test that mute rule beats read-later rule (per void-tray behavior)."""
    body = b'''<?xml version="1.0"?><rss version="2.0"><channel>
    <item><guid>1</guid><title>Important tech</title><category>Technology</category></item>
    </channel></rss>'''
    service = make_service(tmp_path, body)
    # Both mute and read-later for Technology - mute should win
    fid = service.add_feed("https://example.test/rss",
                           mute_rules=["category:Technology"],
                           read_later_rules=["category:Technology"])
    service.check_feed(fid)
    assert service.unread_count() == 0
    assert service.state["read_later"] == []
    tech_item = next(iter(service.state["items"].values()))
    assert tech_item["read"] is True


def test_global_and_per_feed_rules_combined(tmp_path):
    """Test that global routing rules and per-feed rules work together."""
    body = b'''<?xml version="1.0"?><rss version="2.0"><channel>
    <item><guid>1</guid><title>Global mute</title><category>Politics</category></item>
    <item><guid>2</guid><title>Feed mute</title><category>Technology</category></item>
    <item><guid>3</guid><title>Normal</title><category>Sports</category></item>
    </channel></rss>'''
    store = JsonStore(tmp_path / "f.json", lambda: {"feeds": [], "items": {}, "read_later": []})
    service = FeedService(store, fetcher=lambda *a, **k: FetchResult(body),
                          default_interval=60)
    # Global mute for Politics
    service.set_routing_rules([{"kind": "category", "value": "politics"}])
    fid = service.add_feed("https://example.test/rss", mute_rules=["category:Technology"])
    service.check_feed(fid)
    # Politics -> global mute -> read_later
    # Technology -> per-feed mute -> read (not in read_later)
    # Sports -> unread
    assert service.unread_count() == 1
    unread = service.unread_items()[0]
    assert unread["title"] == "Normal"
    tech_item = next(item for item in service.state["items"].values() if item["title"] == "Feed mute")
    assert tech_item["read"] is True
    assert tech_item["id"] not in service.state["read_later"]
    politics_item = next(item for item in service.state["items"].values() if item["title"] == "Global mute")
    assert politics_item["read"] is True
    assert politics_item["id"] in service.state["read_later"]


def test_set_feed_rules_updates_existing_feed(tmp_path):
    """Test that set_feed_rules updates mute/read-later rules for existing feed."""
    body = b'''<?xml version="1.0"?><rss version="2.0"><channel>
    <item><guid>1</guid><title>Tech news</title><category>Technology</category></item>
    </channel></rss>'''
    service = make_service(tmp_path, body)
    fid = service.add_feed("https://example.test/rss")
    service.check_feed(fid)
    # Initially unread
    assert service.unread_count() == 1
    # Add mute rule
    service.set_feed_rules(fid, mute_rules=["category:Technology"])
    # Rules should be applied to existing items
    assert service.unread_count() == 0
    tech_item = next(iter(service.state["items"].values()))
    assert tech_item["read"] is True
    assert tech_item["id"] not in service.state["read_later"]


def test_config_get_feeds_parses_pipe_delimited_format(tmp_path):
    """Test that Config.get_feeds parses the pipe-delimited format correctly."""
    from flux_tray.core.config import Config
    config_path = tmp_path / "config.conf"
    config_path.write_text("""[feeds]
sources = https://example.test/feed.xml|Example Feed|60|category:news;author:john|category:tech
""", encoding="utf-8")
    config = Config(config_path)
    config.load()
    feeds = config.get_feeds()
    assert len(feeds) == 1
    feed = feeds[0]
    assert feed["url"] == "https://example.test/feed.xml"
    assert feed["name"] == "Example Feed"
    assert feed["interval"] == 60
    assert feed["mute_rules"] == ["category:news", "author:john"]
    assert feed["read_later_rules"] == ["category:tech"]


def test_config_set_feeds_writes_pipe_delimited_format(tmp_path):
    """Test that Config.set_feeds writes the pipe-delimited format correctly."""
    from flux_tray.core.config import Config
    config_path = tmp_path / "config.conf"
    config_path.write_text("[feeds]\nsources = \n", encoding="utf-8")
    config = Config(config_path)
    config.load()
    feeds = [{
        "url": "https://example.test/feed.xml",
        "name": "Example Feed",
        "interval": 60,
        "mute_rules": ["category:news", "author:john"],
        "read_later_rules": ["category:tech"],
    }]
    config.set_feeds(feeds)
    # Reload and verify
    config2 = Config(config_path)
    config2.load()
    loaded = config2.get_feeds()
    assert len(loaded) == 1
    assert loaded[0]["url"] == "https://example.test/feed.xml"
    assert loaded[0]["name"] == "Example Feed"
    assert loaded[0]["interval"] == 60
    assert loaded[0]["mute_rules"] == ["category:news", "author:john"]
    assert loaded[0]["read_later_rules"] == ["category:tech"]


def test_config_get_mute_rules_and_highlight_rules(tmp_path):
    """Test that Config.get_mute_rules and get_highlight_rules work."""
    from flux_tray.core.config import Config
    config_path = tmp_path / "config.conf"
    config_path.write_text("""[mute]
rules = category:politics
    author:spammer
[highlight]
rules = urgent
    breaking
""", encoding="utf-8")
    config = Config(config_path)
    config.load()
    mute_rules = config.get_mute_rules()
    highlight_rules = config.get_highlight_rules()
    assert mute_rules == ["category:politics", "author:spammer"]
    assert highlight_rules == ["urgent", "breaking"]


def test_config_set_mute_rules_and_highlight_rules(tmp_path):
    """Test that Config.set_mute_rules and set_highlight_rules work."""
    from flux_tray.core.config import Config
    config_path = tmp_path / "config.conf"
    config_path.write_text("[mute]\nrules =\n[highlight]\nrules =\n", encoding="utf-8")
    config = Config(config_path)
    config.load()
    config.set_mute_rules(["category:politics", "author:spammer"])
    config.set_highlight_rules(["urgent", "breaking"])
    # Reload and verify
    config2 = Config(config_path)
    config2.load()
    assert config2.get_mute_rules() == ["category:politics", "author:spammer"]
    assert config2.get_highlight_rules() == ["urgent", "breaking"]
