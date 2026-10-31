import pytest

from flux_tray.feeds.fetch import fetch_feed, validate_feed_url


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http:///missing-host",
        "https://example.test:99999/feed",
        "http://[invalid-ipv6/feed",
        "https://example.test/feed with spaces",
    ],
)
def test_feed_url_validation_rejects_malformed_or_unsafe_urls(url):
    with pytest.raises(ValueError, match="valid HTTP"):
        validate_feed_url(url)


def test_feed_url_validation_accepts_case_insensitive_http_scheme():
    assert validate_feed_url("HTTPS://example.test/feed") == "HTTPS://example.test/feed"


@pytest.mark.parametrize("timeout", [0, -1, True, float("nan"), float("inf"), -float("inf")])
def test_feed_fetch_rejects_invalid_timeout_before_network(timeout, monkeypatch):
    def unexpected(*_args, **_kwargs):
        raise AssertionError("network should not be accessed")

    monkeypatch.setattr("flux_tray.feeds.fetch.urlopen", unexpected)
    with pytest.raises(ValueError, match="finite positive"):
        fetch_feed("https://example.test/feed", timeout=timeout)


@pytest.mark.parametrize("max_bytes", [0, -1, True, 1.5])
def test_feed_fetch_requires_positive_integer_limit(max_bytes, monkeypatch):
    def unexpected(*_args, **_kwargs):
        raise AssertionError("network should not be accessed")

    monkeypatch.setattr("flux_tray.feeds.fetch.urlopen", unexpected)
    with pytest.raises(ValueError, match="positive integer"):
        fetch_feed("https://example.test/feed", max_bytes=max_bytes)


def test_feed_fetch_rejects_invalid_url_before_network(monkeypatch):
    def unexpected(*_args, **_kwargs):
        raise AssertionError("network should not be accessed")

    monkeypatch.setattr("flux_tray.feeds.fetch.urlopen", unexpected)
    with pytest.raises(ValueError, match="valid HTTP"):
        fetch_feed("http:///missing-host")
