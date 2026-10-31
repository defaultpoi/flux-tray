import pytest

from flux_tray.ui.links import is_valid_web_url


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/article",
        "HTTP://example.com",
        "https://example.com:8443/path",
    ],
)
def test_valid_web_links_accept_http_schemes_case_insensitively(url):
    assert is_valid_web_url(url)


@pytest.mark.parametrize(
    "url",
    [
        None,
        "",
        "ftp://example.com/file",
        "https:///missing-host",
        "https://[malformed",
        "https://example.com:99999/",
        "https://example.com:0/",
        "https://example.com/path with spaces",
        "https://example.com/\nmalformed",
    ],
)
def test_invalid_web_links_are_rejected(url):
    assert not is_valid_web_url(url)
