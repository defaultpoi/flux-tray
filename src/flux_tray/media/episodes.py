"""Normalized media episode records and episode-number parsing."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urlsplit


def is_archive_org(url: str | None) -> bool:
    if not url:
        return False
    host = (urlsplit(url).hostname or "").casefold().rstrip(".")
    return host == "archive.org" or host.endswith(".archive.org")

_PATTERNS = (
    re.compile(r"(?i)(?:^|\b)S(\d{1,3})\s*E(\d{1,4})(?:\b|$)"),
    re.compile(r"(?i)(?:^|\b)(\d{1,3})x(\d{1,4})(?:\b|$)"),
)


def parse_season_episode(title: str) -> tuple[int, int] | None:
    for pattern in _PATTERNS:
        match = pattern.search(title)
        if match:
            return int(match.group(1)), int(match.group(2))
    return None


def safe_filename(value: str, limit: int = 160) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    cleaned = "".join("_" if char in {"/", "\"} or ord(char) < 32 else char
                      for char in normalized).strip(" .")
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = cleaned.lstrip(". ")
    return (cleaned or "untitled")[:limit]


@dataclass(frozen=True, slots=True)
class MediaEpisode:
    id: str
    title: str
    date: str | None = None
    url: str | None = None
    ext: str | None = None
    subs: dict[str, str] | None = None
    headers: dict[str, str] | None = None
    season: int | None = None
    episode: int | None = None
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_episode(raw: dict[str, Any], source_id: str) -> MediaEpisode:
    title = str(raw.get("title") or raw.get("name") or "Untitled")
    candidates = (raw.get("webpage_url"), raw.get("url"))
    url = next((value for value in candidates if isinstance(value, str) and value.startswith(("http://", "https://"))), None)
    if is_archive_org(url):
        raise ValueError("Archive.org sources are intentionally unsupported")
    identity = str(raw.get("id") or url or raw.get("url") or title).strip()
    if not identity:
        raise ValueError("Episode requires a stable id, URL or title")
    parsed = parse_season_episode(title)
    season = raw.get("season", raw.get("season_number"))
    episode = raw.get("episode", raw.get("episode_number"))
    if parsed and (season is None or episode is None):
        season, episode = parsed
    metadata = dict(raw.get("metadata")) if isinstance(raw.get("metadata"), dict) else {}
    for key in ("live_status", "is_live", "was_live", "duration"):
        if key in raw:
            metadata[key] = raw[key]
    return MediaEpisode(
        id=f"{source_id}:{identity}", title=title, date=raw.get("date") or raw.get("upload_date"),
        url=str(url) if isinstance(url, str) and url.startswith(("http://", "https://")) else None,
        ext=raw.get("ext"),
        subs=raw.get("subs") if isinstance(raw.get("subs"), dict) else {},
        headers=raw.get("headers") if isinstance(raw.get("headers"), dict) else {},
        season=int(season) if season is not None else None,
        episode=int(episode) if episode is not None else None,
        metadata=metadata,
    )


def media_filename(source_name: str, episode: dict[str, Any]) -> str:
    """Build a stable source/episode/title basename for video and subtitles."""
    source = safe_filename(str(source_name or "Media"))
    title = str(episode.get("title") or "untitled").strip()
    title = re.sub(rf"^\s*{re.escape(str(source_name or ''))}\s*[-–—:|]*\s*",
                   "", title, flags=re.IGNORECASE) if source_name else title
    parsed = parse_season_episode(title)
    season = episode.get("season")
    number = episode.get("episode")
    if season is None or number is None:
        if parsed:
            season, number = parsed
    if season is not None and number is not None:
        try:
            season, number = int(season), int(number)
        except (TypeError, ValueError):
            season = number = None
    if season is not None and number is not None:
        title = re.sub(r"(?i)^\s*(?:S\d{1,3}\s*E\d{1,4}|\d{1,3}x\d{1,4})\s*[-–—:|]*\s*",
                       "", title)
        prefix = f"{source} - S{season:02d}E{number:02d}"
        return safe_filename(f"{prefix} - {title}" if title else prefix)
    return safe_filename(f"{source} - {title}")
