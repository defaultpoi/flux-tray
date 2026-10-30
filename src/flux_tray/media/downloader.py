"""Resumable yt-dlp media downloads with external subtitle files."""

from __future__ import annotations

from pathlib import Path
from threading import Event
from typing import Callable

from flux_tray.core.process import ProcessResult, ProcessSupervisor
from flux_tray.media.episodes import safe_filename


class MediaDownloader:
    def __init__(self, runner: Callable[..., ProcessResult] | None = None,
                 process: ProcessSupervisor | None = None, timeout: float = 14400):
        self.process = process or ProcessSupervisor()
        self.runner = runner or self.process.run
        self.timeout = timeout

    def download(self, episode: dict, output_dir: Path, *,
                 subtitle_languages: tuple[str, ...] = ("en",),
                 cancelled: Event | None = None) -> str:
        url = episode.get("url")
        if not url or not str(url).startswith(("http://", "https://")):
            raise ValueError("Episode has no playable HTTP(S) URL")
        output_dir = Path(output_dir).expanduser()
        output_dir.mkdir(parents=True, exist_ok=True)
        title = safe_filename(str(episode.get("title") or "untitled"))
        argv = [
            "yt-dlp", "--continue", "--no-overwrites", "--no-playlist",
            "--no-progress", "--no-warnings", "--write-subs", "--write-auto-subs",
            "--sub-format", "best", "--print", "after_move:filepath",
            "-P", str(output_dir), "-o", f"{title}.%(ext)s",
        ]
        if subtitle_languages:
            argv.extend(["--sub-langs", ",".join(subtitle_languages)])
        argv.append(str(url))
        result = self.runner(argv, timeout=self.timeout, cancelled=cancelled)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "Media download failed")
        paths = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if not paths:
            raise RuntimeError("yt-dlp did not report the downloaded file path")
        return paths[-1]
