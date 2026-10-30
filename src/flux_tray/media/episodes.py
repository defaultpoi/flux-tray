"""Normalized media episode records and episode-number parsing."""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime
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
    cleaned = "".join("_" if char in {"/", "\\"} or ord(char) < 32 else char
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


def _normalize_date(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    try:
        if re.fullmatch(r"\\d{8}", text):
            return datetime.strptime(text, "%Y%m%d").date().isoformat()
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError as exc:
        raise ValueError(f"Invalid episode date: {text!r}") from exc


def _normalize_number(value: Any, field: str) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not re.fullmatch(r"\\d+", str(value).strip()):
        raise ValueError(f"Episode {field} must be a non-negative whole number")
    return int(value)


def _normalize_headers(value: Any) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("Episode headers must be a dictionary")
    result = {}
    for key, item in value.items():
        if not isinstance(key, str) or not isinstance(item, str) or not key.strip():
            raise ValueError("Episode headers must contain string names and values")
        if any(char in key + item for char in "\\r\\n"):
            raise ValueError("Episode headers cannot contain line breaks")
        result[key.strip()] = item.strip()
    return result


def _normalize_subtitles(value: Any) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("Episode subtitles must be a language-to-URL dictionary")
    result = {}
    for language, url in value.items():
        if not isinstance(language, str) or not language.strip():
            raise ValueError("Subtitle language cannot be empty")
        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
            raise ValueError(f"Subtitle {language!r} requires an HTTP(S) URL")
        result[language.strip()] = url
    return result


def normalize_episode(raw: dict[str, Any], source_id: str) -> MediaEpisode:
    if not isinstance(raw, dict):
        raise TypeError("Episode record must be a dictionary")
    title = str(raw.get("title") or raw.get("name") or "Untitled").strip() or "Untitled"
    candidates = (raw.get("webpage_url"), raw.get("url"))
    url = next((value for value in candidates if isinstance(value, str)
                and value.startswith(("http://", "https://"))), None)
    if is_archive_org(url):
        raise ValueError("Archive.org sources are intentionally unsupported")
    identity = str(raw.get("id") or url or raw.get("url") or title).strip()
    if not identity:
        raise ValueError("Episode requires a stable id, URL or title")
    parsed = parse_season_episode(title)
    season = _normalize_number(raw.get("season", raw.get("season_number")), "season")
    number = _normalize_number(raw.get("episode", raw.get("episode_number")), "episode")
    if parsed:
        season = parsed[0] if season is None else season
        number = parsed[1] if number is None else number
    ext = raw.get("ext")
    if ext is not None:
        ext = str(ext).strip().lower().lstrip(".")
        if not re.fullmatch(r"[a-z0-9]{1,10}", ext):
            raise ValueError(f"Invalid media extension: {ext!r}")
    metadata = dict(raw.get("metadata")) if isinstance(raw.get("metadata"), dict) else {}
    for key in ("live_status", "is_live", "was_live", "duration"):
        if key in raw:
            metadata[key] = raw[key]
    prefix = f"{source_id}:" if source_id else ""
    normalized_id = identity if not prefix or identity.startswith(prefix) else prefix + identity
    return MediaEpisode(
        id=normalized_id, title=title, date=_normalize_date(raw.get("date") or raw.get("upload_date")),
        url=url, ext=ext, subs=_normalize_subtitles(raw.get("subs")),
        headers=_normalize_headers(raw.get("headers")), season=season, episode=number,
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
