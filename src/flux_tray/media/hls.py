"""Finite HLS playlist parsing and ffmpeg stream-copy downloads."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Callable
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from flux_tray.core.process import ProcessResult, ProcessSupervisor
from flux_tray.media.episodes import media_filename


_ATTRIBUTE = re.compile(r'([A-Z0-9-]+)=("[^"]*"|[^,]*)')


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
                duration += max(0.0, float(value))
            except ValueError:
                continue
        if not line.startswith("#EXT-X-STREAM-INF:"):
            continue
        attributes = dict(_ATTRIBUTE.findall(line.partition(":")[2]))
        uri = next((candidate for candidate in lines[index + 1:]
                    if not candidate.startswith("#")), None)
        if not uri:
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
        request = Request(url, headers={"User-Agent": "FluxTray/0.1", **headers})
        with urlopen(request, timeout=self.playlist_timeout) as response:
            payload = response.read(self.max_playlist_bytes + 1)
        if len(payload) > self.max_playlist_bytes:
            raise ValueError("HLS playlist exceeds the configured size limit")
        return payload.decode("utf-8-sig")

    @staticmethod
    def _header_argument(headers: dict[str, str]) -> str:
        return "".join(f"{key}: {value}\r\n" for key, value in headers.items())

    def download(self, episode: dict, output_dir: Path, *, source_name: str,
                 screen: tuple[int, int] | None = None, cancelled: Event | None = None,
                 progress_callback: Callable[[dict], None] | None = None) -> str:
        url = str(episode.get("url") or "")
        if not url.startswith(("http://", "https://")) or not url.split("?", 1)[0].lower().endswith(".m3u8"):
            raise ValueError("HLS download requires an HTTP(S) .m3u8 URL")
        headers = episode.get("headers") if isinstance(episode.get("headers"), dict) else {}
        playlist = parse_playlist(self._fetch_playlist(url, headers), url)
        if playlist.variants:
            url = pick_variant(playlist.variants, screen).url
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
                "-progress", "pipe:1", "-nostats"]
        if headers:
            argv.extend(["-headers", self._header_argument(headers)])
        argv.extend(["-i", url, "-map", "0", "-c", "copy", "-f", "matroska", str(partial)])

        progress_state: dict[str, str] = {}

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
            if not partial.is_file():
                raise RuntimeError("ffmpeg completed without creating the media file")
            os.replace(partial, destination)
            if progress_callback is not None:
                progress_callback({"percent": 100.0, "duration": playlist.duration})
            return str(destination)
        except BaseException:
            try:
                partial.unlink()
            except FileNotFoundError:
                pass
            raise
