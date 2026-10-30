"""Bounded RSS/Atom HTTP fetching."""

from __future__ import annotations

from dataclasses import dataclass
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


def fetch_feed(url: str, *, etag: str | None = None, modified: str | None = None,
               timeout: float = 15.0, max_bytes: int = 5_000_000) -> FetchResult:
    """Fetch one feed with conditional headers, a hard timeout and size limit."""
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
