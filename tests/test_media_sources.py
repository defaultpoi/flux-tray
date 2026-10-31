from types import SimpleNamespace

from flux_tray.media.sources import RssMediaAdapter


def test_rss_media_adapter_ignores_images_and_non_http_enclosures():
    body = b"""<?xml version="1.0"?>
    <rss version="2.0"><channel><title>Podcast</title>
      <item><guid>episode-1</guid><title>Episode 1</title>
        <enclosure url="https://media.example.test/episode.mp3"
                   length="100" type="audio/mpeg"/>
        <enclosure url="https://media.example.test/cover.jpg"
                   length="20" type="image/jpeg"/>
        <enclosure url="file:///tmp/local.mp3"
                   length="20" type="audio/mpeg"/>
        <enclosure url="https://media.example.test/vod.m3u8"
                   length="20" type="application/vnd.apple.mpegurl"/>
      </item>
    </channel></rss>"""

    adapter = RssMediaAdapter(fetcher=lambda _url: SimpleNamespace(body=body))
    episodes = adapter.list_episodes("https://example.test/feed.xml", "podcast")

    assert len(episodes) == 2
    assert episodes[0]["url"] == "https://media.example.test/episode.mp3"
    assert episodes[0]["ext"] == "mp3"
    assert episodes[0]["title"] == "Episode 1"
    assert episodes[1]["url"] == "https://media.example.test/vod.m3u8"
    assert episodes[1]["ext"] == "m3u8"
