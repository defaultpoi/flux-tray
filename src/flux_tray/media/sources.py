"""Built-in media source adapters for yt-dlp and RSS/Atom enclosures."""

from __future__ import annotations

import json
import re
from calendar import timegm
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import urlsplit

import feedparser

from flux_tray.core.process import ProcessResult, ProcessSupervisor
from flux_tray.feeds.fetch import fetch_feed
from flux_tray.media.episodes import is_archive_org, normalize_episode


class YtDlpAdapter:
    def __init__(self, runner: Callable[..., ProcessResult] | None = None,
                 process: ProcessSupervisor | None = None, timeout: float = 180):
        self.process = process or ProcessSupervisor()
        self.runner = runner or self.process.run
        self.timeout = timeout

    def list_episodes(self, url: str, source_id: str) -> list[dict[str, Any]]:
        if is_archive_org(url):
            raise ValueError("Archive.org is not a supported media source")
        result = self.runner([
            "yt-dlp", "--flat-playlist", "--dump-single-json", "--no-warnings",
            "--no-progress", url,
        ], timeout=self.timeout)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "yt-dlp source check failed")
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise ValueError("yt-dlp returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("yt-dlp returned an unexpected document")
        entries = payload.get("entries")
        if entries is None:
            entries = [payload]
        episodes = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            raw = dict(entry)
            if raw.get("url") and not str(raw["url"]).startswith(("http://", "https://")):
                if raw.get("id") and "youtube" in str(raw.get("extractor_key", "")).lower():
                    raw["url"] = f"https://www.youtube.com/watch?v={raw['id']}"
            episodes.append(normalize_episode(raw, source_id).to_dict())
        return episodes


class RssMediaAdapter:
    def __init__(self, fetcher: Callable[..., Any] = fetch_feed):
        self.fetcher = fetcher

    def list_episodes(self, url: str, source_id: str) -> list[dict[str, Any]]:
        if is_archive_org(url):
            raise ValueError("Archive.org is not a supported media source")
        result = self.fetcher(url)
        if result.body is None:
            return []
        parsed = feedparser.parse(result.body)
        if parsed.bozo and not parsed.entries:
            raise ValueError(f"Invalid media feed: {parsed.bozo_exception}")
        episodes = []
        for entry in parsed.entries:
            enclosures = entry.get("enclosures", [])
            for index, enclosure in enumerate(enclosures):
                if not isinstance(enclosure, dict):
                    continue
                media_url = enclosure.get("href") or enclosure.get("url")
                if not isinstance(media_url, str):
                    continue
                parsed_url = urlsplit(media_url)
                if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
                    continue
                mime_type = enclosure.get("type")
                if isinstance(mime_type, str) and mime_type.casefold().startswith("image/"):
                    continue
                published = entry.get("published_parsed") or entry.get("updated_parsed")
                date = datetime.fromtimestamp(timegm(published), timezone.utc).isoformat() if published else None
                filename = parsed_url.path.rsplit("/", 1)[-1]
                extension = filename.rsplit(".", 1)[-1] if "." in filename else None
                if not extension and isinstance(mime_type, str):
                    subtype = mime_type.rsplit("/", 1)[-1].casefold()
                    extension = "m3u8" if subtype in {
                        "vnd.apple.mpegurl", "x-mpegurl"
                    } else subtype.rsplit(".", 1)[-1]
                if extension and not re.fullmatch(r"[a-z0-9]{1,10}", extension.casefold()):
                    extension = None
                raw = {
                    "id": str(entry.get("id") or media_url) + f":{index}",
                    "title": entry.get("title") or "Untitled media",
                    "date": date,
                    "url": media_url,
                    "ext": extension or None,
                    "metadata": {"author": entry.get("author", ""),
                                 "summary": entry.get("summary", "")},
                }
                episodes.append(normalize_episode(raw, source_id).to_dict())
        return episodes
