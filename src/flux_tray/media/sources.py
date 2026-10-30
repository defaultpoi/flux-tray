"""Built-in media source adapters for yt-dlp and RSS/Atom enclosures."""

from __future__ import annotations

import json
from calendar import timegm
from datetime import datetime, timezone
from typing import Any, Callable

import feedparser

from flux_tray.core.process import ProcessResult, ProcessSupervisor
from flux_tray.feeds.fetch import fetch_feed
from flux_tray.media.episodes import normalize_episode


class YtDlpAdapter:
    def __init__(self, runner: Callable[..., ProcessResult] | None = None,
                 process: ProcessSupervisor | None = None, timeout: float = 180):
        self.process = process or ProcessSupervisor()
        self.runner = runner or self.process.run
        self.timeout = timeout

    def list_episodes(self, url: str, source_id: str) -> list[dict[str, Any]]:
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
                media_url = enclosure.get("href") or enclosure.get("url")
                if not media_url:
                    continue
                published = entry.get("published_parsed") or entry.get("updated_parsed")
                date = datetime.fromtimestamp(timegm(published), timezone.utc).isoformat() if published else None
                raw = {
                    "id": str(entry.get("id") or media_url) + f":{index}",
                    "title": entry.get("title") or "Untitled media",
                    "date": date,
                    "url": media_url,
                    "ext": enclosure.get("type", "").split("/")[-1] or None,
                    "metadata": {"author": entry.get("author", ""),
                                 "summary": entry.get("summary", "")},
                }
                episodes.append(normalize_episode(raw, source_id).to_dict())
        return episodes
