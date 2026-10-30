"""Small bounded HTTP helpers available to trusted media plugins."""

from __future__ import annotations

import json
import os
from pathlib import Path
from threading import Event
from typing import Callable
from urllib.request import Request, urlopen

from flux_tray.media.episodes import parse_season_episode


def fetch_json(url: str, *, timeout: float = 10, max_bytes: int = 1_000_000,
               headers: dict[str, str] | None = None):
    if not url.startswith(("https://", "http://")):
        raise ValueError("URL must use HTTP or HTTPS")
    request = Request(url, headers={"User-Agent": "FluxTray/0.1", **(headers or {})})
    with urlopen(request, timeout=timeout) as response:
        payload = response.read(max_bytes + 1)
    if len(payload) > max_bytes:
        raise ValueError(f"Response exceeds {max_bytes} bytes")
    result = json.loads(payload)
    return result


def download_file(url: str, destination: Path, *, timeout: float = 30,
                  headers: dict[str, str] | None = None,
                  progress: Callable[[int, int | None], None] | None = None,
                  cancelled: Event | None = None) -> str:
    if not url.startswith(("https://", "http://")):
        raise ValueError("URL must use HTTP or HTTPS")
    destination = Path(destination).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")
    offset = partial.stat().st_size if partial.exists() else 0
    request_headers = {"User-Agent": "FluxTray/0.1", **(headers or {})}
    if offset:
        request_headers["Range"] = f"bytes={offset}-"
    request = Request(url, headers=request_headers)
    with urlopen(request, timeout=timeout) as response:
        resumed = offset > 0 and getattr(response, "status", 200) == 206
        if not resumed:
            offset = 0
        remaining = response.headers.get("Content-Length")
        total = offset + int(remaining) if remaining and remaining.isdigit() else None
        mode = "ab" if resumed else "wb"
        downloaded = offset
        with partial.open(mode) as output:
            while True:
                if cancelled is not None and cancelled.is_set():
                    raise RuntimeError("Download cancelled")
                chunk = response.read(65536)
                if not chunk:
                    break
                output.write(chunk)
                downloaded += len(chunk)
                if progress is not None:
                    progress(downloaded, total)
            output.flush()
            os.fsync(output.fileno())
    os.replace(partial, destination)
    return str(destination)
