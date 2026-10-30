"""Resumable yt-dlp media downloads with external subtitle files."""

from __future__ import annotations

from pathlib import Path
from threading import Event
from typing import Callable

from flux_tray.core.process import ProcessResult, ProcessSupervisor
from flux_tray.media.episodes import is_archive_org, media_filename


class MediaDownloader:
    def __init__(self, runner: Callable[..., ProcessResult] | None = None,
                 process: ProcessSupervisor | None = None, timeout: float = 14400):
        self.process = process or ProcessSupervisor()
        self.runner = runner or self.process.run
        self.timeout = timeout

    def download(self, episode: dict, output_dir: Path, *,
                 subtitle_languages: tuple[str, ...] = ("en",),
                 format_sort: str | None = None,
                 cancelled: Event | None = None,
                 progress_callback: Callable[[dict], None] | None = None,
                 source_name: str | None = None) -> str:
        url = episode.get("url")
        if not url or not str(url).startswith(("http://", "https://")):
            raise ValueError("Episode has no playable HTTP(S) URL")
        if is_archive_org(str(url)):
            raise ValueError("Archive.org media downloads are intentionally unsupported")
        metadata = episode.get("metadata") or {}
        live_status = metadata.get("live_status", episode.get("live_status"))
        if metadata.get("is_live") or episode.get("is_live") or live_status == "is_live":
            raise ValueError("Live HLS streams cannot be queued as media downloads")
        output_dir = Path(output_dir).expanduser()
        output_dir.mkdir(parents=True, exist_ok=True)
        title = media_filename(source_name or "Media", episode)
        argv = [
            "yt-dlp", "--continue", "--no-overwrites", "--no-playlist",
            "--no-warnings", "--write-subs", "--write-auto-subs",
            "--sub-format", "best", "--print", "after_move:filepath",
            "-P", str(output_dir), "-o", f"{title}.%(ext)s",
        ]
        if progress_callback is None:
            argv.append("--no-progress")
        else:
            argv.extend([
                "--newline", "--progress-delta", "1", "--progress-template",
                "download:FLUX_PROGRESS|%(progress.downloaded_bytes)s|%(progress.total_bytes)s|%(progress.total_bytes_estimate)s|%(progress.eta)s",
            ])
        if subtitle_languages:
            argv.extend(["--sub-langs", ",".join(subtitle_languages)])
        if format_sort:
            argv.extend(["-S", format_sort])
        argv.append(str(url))

        def on_output(_channel: str, line: str) -> None:
            if progress_callback is None or not line.startswith("FLUX_PROGRESS|"):
                return
            parts = line.strip().split("|")
            if len(parts) < 5:
                return

            def number(value):
                try:
                    return float(value)
                except (TypeError, ValueError):
                    return None

            downloaded = number(parts[1].strip())
            total = number(parts[2].strip()) or number(parts[3].strip())
            eta = number(parts[4].strip())
            percent = (min(100.0, downloaded * 100.0 / total)
                       if downloaded is not None and total else None)
            progress_callback({"downloaded_bytes": downloaded, "total_bytes": total,
                               "eta": eta, "percent": percent})

        kwargs = {"timeout": self.timeout, "cancelled": cancelled}
        if progress_callback is not None:
            kwargs["output_callback"] = on_output
        result = self.runner(argv, **kwargs)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "Media download failed")
        paths = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if not paths:
            raise RuntimeError("yt-dlp did not report the downloaded file path")

        reported_path = Path(paths[-1]).expanduser()
        if not reported_path.is_absolute():
            reported_path = output_dir / reported_path
        try:
            completed_path = reported_path.resolve(strict=True)
            completed_path.relative_to(output_dir.resolve())
        except (OSError, ValueError) as exc:
            raise RuntimeError(
                "yt-dlp reported a download outside the configured media directory "
                "or a file that does not exist"
            ) from exc
        if not completed_path.is_file() or completed_path.stat().st_size == 0:
            raise RuntimeError("yt-dlp reported an invalid or empty media file")
        return str(completed_path)
