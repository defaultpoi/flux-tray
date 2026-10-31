"""Bounded RSS/Atom HTTP fetching."""

from __future__ import annotations

from dataclasses import dataclass
import math
from urllib.parse import urlsplit
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@dataclass(frozen=True, slots=True)
class FetchResult:
    body: bytes | None
    etag: str | None = None
    modified: str | None = None
    not_modified: bool = False


class FeedFetchError(RuntimeError):
    pass


def validate_feed_url(url: str) -> str:
    if not isinstance(url, str) or not url or any(ord(char) < 32 or char.isspace() for char in url):
        raise ValueError("Feed URL must be a valid HTTP or HTTPS URL")
    try:
        parsed = urlsplit(url)
        valid = parsed.scheme.lower() in {"http", "https"} and bool(parsed.hostname)
        port = parsed.port
        if port is not None and not (1 <= port <= 65535):
            valid = False
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("Feed URL must be a valid HTTP or HTTPS URL")
    return url


def fetch_feed(url: str, *, etag: str | None = None, modified: str | None = None,
               timeout: float = 15.0, max_bytes: int = 5_000_000) -> FetchResult:
    """Fetch one feed with conditional headers, a hard timeout and size limit."""
    validate_feed_url(url)
    try:
        valid_timeout = not isinstance(timeout, bool) and math.isfinite(timeout) and timeout > 0
    except (OverflowError, TypeError) as exc:
        raise ValueError("Feed timeout must be a finite positive number") from exc
    if not valid_timeout:
        raise ValueError("Feed timeout must be a finite positive number")
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0:
        raise ValueError("Feed max_bytes must be a positive integer")
    headers = {"User-Agent": "FluxTray/0.1 (+RSS reader)", "Accept":
               "application/atom+xml, application/rss+xml, application/xml, text/xml, */*"}
    if etag:
        headers["If-None-Match"] = etag
    if modified:
        headers["If-Modified-Since"] = modified
    request = Request(url, headers=headers)
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read(max_bytes + 1)
            if len(body) > max_bytes:
                raise FeedFetchError(f"Feed exceeds {max_bytes} bytes")
            return FetchResult(body, response.headers.get("ETag"),
                               response.headers.get("Last-Modified"))
    except HTTPError as exc:
        if exc.code == 304:
            return FetchResult(None, etag, modified, True)
        raise FeedFetchError(f"HTTP {exc.code}: {exc.reason}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise FeedFetchError(str(exc)) from exc
