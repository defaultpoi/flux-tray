"""Finite HLS playlist parsing and ffmpeg stream-copy downloads."""

from __future__ import annotations

import os
import re
import logging
import math
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Callable
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen

from flux_tray.core.process import ProcessResult, ProcessSupervisor
from flux_tray.media.episodes import media_filename, safe_filename
from flux_tray.media.helpers import _safe_headers


_ATTRIBUTE = re.compile(r'([A-Z0-9-]+)=("[^"]*"|[^,]*)')


def _validate_http_url(url: str, description: str) -> None:
    """Reject non-HTTP URLs and malformed authorities before opening a URL."""
    try:
        parsed = urlsplit(url)
        valid = parsed.scheme in {"http", "https"} and bool(parsed.hostname)
        if parsed.port is not None and not (1 <= parsed.port <= 65535):
            valid = False
    except ValueError:
        valid = False
    if not valid:
        raise ValueError(f"{description} must use a valid HTTP or HTTPS URL")


@dataclass(frozen=True, slots=True)
class HlsVariant:
    url: str
    width: int | None
    height: int | None
    bandwidth: int


@dataclass(frozen=True, slots=True)
class HlsPlaylist:
    variants: tuple[HlsVariant, ...]
    duration: float
    ended: bool


def parse_playlist(text: str, base_url: str) -> HlsPlaylist:
    """Parse the bounded subset of an HLS playlist needed for VOD downloads."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    variants = []
    duration = 0.0
    ended = "#EXT-X-ENDLIST" in lines
    for index, line in enumerate(lines):
        if line.startswith("#EXTINF:"):
            value = line[8:].split(",", 1)[0]
            try:
                seconds = float(value)
            except ValueError:
                seconds = 0.0
            total = duration + seconds
            if math.isfinite(seconds) and seconds > 0 and math.isfinite(total):
                duration = total
        if not line.startswith("#EXT-X-STREAM-INF:"):
            continue
        attributes = dict(_ATTRIBUTE.findall(line.partition(":")[2]))
        uri = lines[index + 1] if index + 1 < len(lines) else None
        if not uri or uri.startswith("#"):
            continue
        resolution = attributes.get("RESOLUTION", "")
        match = re.fullmatch(r"(\d+)x(\d+)", resolution)
        width, height = (int(match.group(1)), int(match.group(2))) if match else (None, None)
        try:
            bandwidth = int(attributes.get("AVERAGE-BANDWIDTH")
                             or attributes.get("BANDWIDTH") or 0)
        except ValueError:
            bandwidth = 0
        variants.append(HlsVariant(urljoin(base_url, uri), width, height, bandwidth))
    return HlsPlaylist(tuple(variants), duration, ended)


def pick_variant(variants: tuple[HlsVariant, ...], screen: tuple[int, int] | None,
                 headroom: float = 1.15) -> HlsVariant:
    if not variants:
        raise ValueError("HLS master playlist contains no variants")
    known = [variant for variant in variants if variant.width and variant.height]
    if screen and screen[0] > 0 and screen[1] > 0 and known:
        fitting = [variant for variant in known
                   if max(variant.width / screen[0], variant.height / screen[1]) <= headroom]
        if fitting:
            return max(fitting, key=lambda item: item.width * item.height)
        return min(known, key=lambda item: item.width * item.height)
    return max(variants, key=lambda item: item.bandwidth)


class HlsDownloader:
    def __init__(self, runner: Callable[..., ProcessResult] | None = None,
                 process: ProcessSupervisor | None = None, timeout: float = 14400,
                 playlist_timeout: float = 15, max_playlist_bytes: int = 1_000_000):
        self.process = process or ProcessSupervisor()
        self.runner = runner or self.process.run
        self.timeout = timeout
        self.playlist_timeout = playlist_timeout
        self.max_playlist_bytes = max_playlist_bytes

    def _fetch_playlist(self, url: str, headers: dict[str, str]) -> str:
        request = Request(url, headers={"User-Agent": "FluxTray/0.1", **_safe_headers(headers)})
        with urlopen(request, timeout=self.playlist_timeout) as response:
            payload = response.read(self.max_playlist_bytes + 1)
        if len(payload) > self.max_playlist_bytes:
            raise ValueError("HLS playlist exceeds the configured size limit")
        return payload.decode("utf-8-sig")

    @staticmethod
    def _header_argument(headers: dict[str, str]) -> str:
        return "".join(f"{key}: {value}\r\n" for key, value in headers.items())

    def _download_subtitles(self, episode: dict, output_dir: Path, basename: str,
                             headers: dict[str, str]) -> None:
        subtitles = episode.get("subs")
        if not isinstance(subtitles, dict):
            return
        for language, url in subtitles.items():
            if not isinstance(url, str):
                continue
            try:
                _validate_http_url(url, "Subtitle URL")
            except ValueError:
                continue
            extension = Path(urlsplit(url).path).suffix.lower()
            if extension not in {".vtt", ".srt", ".ass", ".ssa", ".ttml"}:
                continue
            destination = output_dir / f"{basename}.{safe_filename(str(language), 24)}{extension}"
            partial = Path(str(destination) + ".part")
            try:
                request = Request(
                    url, headers={"User-Agent": "FluxTray/0.1", **_safe_headers(headers)}
                )
                with urlopen(request, timeout=self.playlist_timeout) as response:
                    payload = response.read(2_000_001)
                if not payload or len(payload) > 2_000_000:
                    continue
                with partial.open("wb") as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(partial, destination)
            except Exception:
                try:
                    partial.unlink()
                except FileNotFoundError:
                    pass
                logging.getLogger("flux_tray.media.hls").debug(
                    "Could not download optional subtitle %s", language, exc_info=True
                )

    def download(self, episode: dict, output_dir: Path, *, source_name: str,
                 screen: tuple[int, int] | None = None, cancelled: Event | None = None,
                 progress_callback: Callable[[dict], None] | None = None) -> str:
        url = str(episode.get("url") or "")
        try:
            _validate_http_url(url, "HLS playlist URL")
        except ValueError as exc:
            raise ValueError("HLS download requires a valid HTTP(S) .m3u8 URL") from exc
        if not urlsplit(url).path.lower().endswith(".m3u8"):
            raise ValueError("HLS download requires an HTTP(S) .m3u8 URL")
        headers = _safe_headers(episode.get("headers"))
        playlist = parse_playlist(self._fetch_playlist(url, headers), url)
        if playlist.variants:
            url = pick_variant(playlist.variants, screen).url
            # Validate before opening: urlopen supports local file URLs, which
            # must never be reachable through an untrusted master playlist.
            _validate_http_url(url, "HLS variant URL")
            playlist = parse_playlist(self._fetch_playlist(url, headers), url)
        if not playlist.ended:
            raise ValueError("Live HLS playlists cannot be downloaded")
        if playlist.duration <= 0:
            raise ValueError("HLS playlist has no usable media duration")

        output_dir = Path(output_dir).expanduser()
        output_dir.mkdir(parents=True, exist_ok=True)
        destination = output_dir / (media_filename(source_name, episode) + ".mkv")
        partial = Path(str(destination) + ".part")
        argv = ["ffmpeg", "-nostdin", "-y", "-hide_banner", "-loglevel", "error",
                "-protocol_whitelist", "http,https,tcp,tls,crypto",
                "-progress", "pipe:1", "-nostats"]
        if headers:
            argv.extend(["-headers", self._header_argument(headers)])
        argv.extend(["-i", url, "-map", "0", "-c", "copy", "-f", "matroska", str(partial)])

        progress_state: dict[str, str] = {}
        if progress_callback is not None:
            progress_callback({"part_path": str(partial), "duration": playlist.duration,
                               "percent": 0.0})

        def on_output(_channel: str, line: str) -> None:
            key, separator, value = line.strip().partition("=")
            if not separator:
                return
            progress_state[key] = value
            if progress_callback is None:
                return
            try:
                elapsed = int(progress_state.get("out_time_ms", "0")) / 1_000_000
            except ValueError:
                return
            percent = min(100.0, elapsed * 100.0 / playlist.duration)
            progress_callback({"percent": percent, "elapsed": elapsed,
                               "duration": playlist.duration})

        try:
            result = self.runner(argv, timeout=self.timeout, cancelled=cancelled,
                                 output_callback=on_output if progress_callback else None)
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or "HLS download failed")
            if not partial.is_file() or partial.stat().st_size == 0:
                raise RuntimeError("ffmpeg completed without creating a non-empty media file")
            os.replace(partial, destination)
            self._download_subtitles(episode, output_dir, destination.stem, headers)
            if progress_callback is not None:
                progress_callback({"percent": 100.0, "duration": playlist.duration})
            return str(destination)
        except BaseException:
            try:
                partial.unlink()
            except FileNotFoundError:
                pass
            raise
