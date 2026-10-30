"""Normalized media episode records and episode-number parsing."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass
from typing import Any


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
    cleaned = "".join("_" if char in {"/", "\\"} or ord(char) < 32 else char
                      for char in normalized).strip(" .")
    cleaned = re.sub(r"\s+", " ", cleaned)
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
    url = raw.get("url") or raw.get("webpage_url")
    identity = str(raw.get("id") or url or title).strip()
    if not identity:
        raise ValueError("Episode requires a stable id, URL or title")
    parsed = parse_season_episode(title)
    season = raw.get("season", raw.get("season_number"))
    episode = raw.get("episode", raw.get("episode_number"))
    if parsed and (season is None or episode is None):
        season, episode = parsed
    return MediaEpisode(
        id=f"{source_id}:{identity}", title=title, date=raw.get("date") or raw.get("upload_date"),
        url=str(url) if url else None, ext=raw.get("ext"),
        subs=raw.get("subs") if isinstance(raw.get("subs"), dict) else {},
        headers=raw.get("headers") if isinstance(raw.get("headers"), dict) else {},
        season=int(season) if season is not None else None,
        episode=int(episode) if episode is not None else None,
        metadata=raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {},
    )
