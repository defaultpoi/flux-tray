"""Small bounded HTTP helpers available to trusted media plugins."""

from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path
from threading import Event
from typing import Callable
from urllib.request import Request, urlopen

from flux_tray.media.episodes import parse_season_episode, validate_http_url


def _safe_headers(headers: dict[str, str] | None) -> dict[str, str]:
    if headers is None:
        return {}
    if not isinstance(headers, dict):
        raise ValueError("HTTP headers must be a dictionary")
    result = {}
    for name, value in headers.items():
        if not isinstance(name, str) or not name.strip() or not isinstance(value, str):
            raise ValueError("HTTP headers must contain non-empty string names and values")
        if any(char in name + value for char in (chr(10), chr(13))):
            raise ValueError("HTTP headers cannot contain line breaks")
        result[name.strip()] = value.strip()
    return result


def _validate_timeout(timeout: float) -> None:
    try:
        valid = not isinstance(timeout, bool) and math.isfinite(timeout) and timeout > 0
    except TypeError as exc:
        raise ValueError("timeout must be a finite positive number") from exc
    if not valid:
        raise ValueError("timeout must be a finite positive number")


def fetch_json(url: str, *, timeout: float = 10, max_bytes: int = 1_000_000,
               headers: dict[str, str] | None = None):
    validate_http_url(url, "Plugin request URL")
    _validate_timeout(timeout)
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or max_bytes <= 0:
        raise ValueError("max_bytes must be a positive integer")
    request = Request(url, headers={"User-Agent": "FluxTray/0.1", **_safe_headers(headers)})
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
    validate_http_url(url, "Plugin download URL")
    _validate_timeout(timeout)
    destination = Path(destination).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")
    offset = partial.stat().st_size if partial.exists() else 0
    request_headers = {"User-Agent": "FluxTray/0.1", **_safe_headers(headers)}
    if offset:
        request_headers["Range"] = f"bytes={offset}-"
    request = Request(url, headers=request_headers)
    with urlopen(request, timeout=timeout) as response:
        status = getattr(response, "status", 200)
        remaining = response.headers.get("Content-Length")
        response_length = int(remaining) if remaining and remaining.isdigit() else None
        expected_response_length = response_length
        if status == 206:
            content_range = response.headers.get("Content-Range", "")
            match = re.fullmatch(r"bytes ([0-9]+)-([0-9]+)/([0-9]+|[*])", content_range)
            if match is None or int(match.group(1)) != offset:
                raise ValueError("Server returned an invalid range for the resumed download")
            range_end = int(match.group(2))
            if range_end < offset:
                raise ValueError("Server returned an invalid range for the resumed download")
            expected_response_length = range_end - offset + 1
            if response_length is not None and response_length != expected_response_length:
                raise ValueError("Server range length does not match Content-Length")
            range_total = match.group(3)
            total = int(range_total) if range_total.isdigit() else (
                offset + expected_response_length if response_length is not None else None
            )
            if total is not None and range_end >= total:
                raise ValueError("Server returned an invalid total for the resumed download")
            mode = "ab" if offset else "wb"
        else:
            offset = 0
            total = response_length
            mode = "wb"
        downloaded = offset
        received = 0
        with partial.open(mode) as output:
            while True:
                if cancelled is not None and cancelled.is_set():
                    raise RuntimeError("Download cancelled")
                if expected_response_length is None:
                    chunk = response.read(65536)
                else:
                    remaining_bytes = expected_response_length - received
                    if remaining_bytes <= 0:
                        if response.read(1):
                            raise RuntimeError("Download response exceeded the expected byte count")
                        break
                    chunk = response.read(min(65536, remaining_bytes))
                if not chunk:
                    break
                output.write(chunk)
                received += len(chunk)
                downloaded += len(chunk)
                if progress is not None:
                    progress(downloaded, total)
            output.flush()
            os.fsync(output.fileno())
        if expected_response_length is not None and received != expected_response_length:
            raise RuntimeError("Download response ended before the expected byte count")
        if total is not None and downloaded != total:
            raise RuntimeError("Download ended before the expected total size")
        if downloaded == 0:
            raise RuntimeError("Download completed without receiving any data")
    os.replace(partial, destination)
    return str(destination)
