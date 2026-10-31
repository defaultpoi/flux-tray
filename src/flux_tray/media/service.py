"""Persistent media source catalog and bounded ahead-download queue state."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Callable
from uuid import uuid4

from flux_tray.core.storage import JsonStore
from flux_tray.media.plugins import MediaPluginRegistry
from flux_tray.media.downloader import MediaDownloader
from flux_tray.media.hls import HlsDownloader
from flux_tray.media.episodes import is_archive_org, safe_filename
from flux_tray.media.sources import RssMediaAdapter, YtDlpAdapter


class MediaService:
    def __init__(self, store: JsonStore, plugin_dir: Path, *, ahead: int = 2,
                 interval: int = 3600, yt_dlp: YtDlpAdapter | None = None,
                 rss: RssMediaAdapter | None = None,
                 downloader: MediaDownloader | None = None,
                 hls_downloader: HlsDownloader | None = None,
                 output_dir: Path | None = None, player=None, display=None,
                 screen_height: int | None = None, yt_dlp_sort: str | None = None,
                 now: Callable[[], datetime] | None = None):
        self.store = store
        self.plugins = MediaPluginRegistry(plugin_dir)
        self.ahead = max(0, int(ahead))
        self.interval = max(600, int(interval))
        self.yt_dlp = yt_dlp or YtDlpAdapter()
        self.rss = rss or RssMediaAdapter()
        self.downloader = downloader or MediaDownloader()
        self.hls_downloader = hls_downloader or HlsDownloader()
        self.output_dir = Path(output_dir or Path.home() / "Videos").expanduser()
        self.player = player
        self.display = display
        self.screen_height = int(screen_height) if screen_height else None
        self.yt_dlp_sort = yt_dlp_sort.strip() if yt_dlp_sort and yt_dlp_sort.strip() else None
        self.current_episode_id: str | None = None
        self._download_lock = Lock()
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.state = store.load()
        if not isinstance(self.state, dict):
            self.state = {}
        self.state.setdefault("sources", [])
        self.state.setdefault("episodes", {})
        self.state.setdefault("queue", [])
        self.state.setdefault("watched", [])
        download = self.state.get("download")
        if isinstance(download, dict) and download.get("status") == "downloading":
            download.update({"status": "failed",
                             "error": "Download interrupted before completion"})
            self.store.save(self.state)

    def _save(self):
        self.store.save(self.state)

    @staticmethod
    def _validate_order(order: str | None) -> str | None:
        if order is None or str(order).strip().lower() in {"", "default"}:
            return None
        value = str(order).strip().lower()
        if value not in {"oldest", "newest"}:
            raise ValueError("Media source order must be default, oldest or newest")
        return value

    @staticmethod
    def _ordered_episodes(episodes: list[dict[str, Any]],
                          order: str | None) -> list[dict[str, Any]]:
        """Order episodes while preserving adapter order for equal sort keys."""
        ordered = sorted(episodes, key=lambda item: item.get("source_order", 0))
        if order not in {"oldest", "newest"}:
            return ordered

        def sort_key(item: dict[str, Any]):
            season, number = item.get("season"), item.get("episode")
            if isinstance(season, int) and isinstance(number, int):
                return (0, season, number)
            return (1, str(item.get("date") or ""))

        # Python's stable reverse sort keeps equal-key items in their input order.
        ordered.sort(key=sort_key, reverse=order == "newest")
        return ordered

    def add_source(self, kind: str, url: str, name: str | None = None,
                   order: str | None = None) -> str:
        if kind not in {"youtube", "rss", "url", "plugin"}:
            raise ValueError("Source kind must be youtube, rss, url or plugin")
        if not url.strip():
            raise ValueError("Source URL cannot be empty")
        if kind != "plugin" and not url.strip().startswith(("https://", "http://")):
            raise ValueError("Media source must use HTTP or HTTPS")
        if is_archive_org(url.strip()):
            raise ValueError("Archive.org media sources are intentionally unsupported")
        source_id = uuid4().hex
        self.state["sources"].append({"id": source_id, "kind": kind, "url": url.strip(),
            "name": name or url.strip(), "order": self._validate_order(order),
            "initialized": False, "next_check": None,
            "last_error": None, "last_success": None})
        self._save()
        return source_id

    def update_source(self, source_id: str, kind: str, url: str, name: str,
                      order: str | None = None) -> None:
        if kind not in {"youtube", "rss", "url", "plugin"}:
            raise ValueError("Source kind must be youtube, rss, url or plugin")
        url = str(url).strip()
        if not url:
            raise ValueError("Source URL cannot be empty")
        if kind != "plugin" and not url.startswith(("https://", "http://")):
            raise ValueError("Media source must use HTTP or HTTPS")
        if is_archive_org(url):
            raise ValueError("Archive.org media sources are intentionally unsupported")
        source = self._source(source_id)
        identity_changed = source.get("kind") != kind or source.get("url") != url
        new_order = self._validate_order(order)

        if identity_changed:
            download = self.state.get("download") or {}
            active_episode = self.state["episodes"].get(download.get("episode_id"))
            if (download.get("status") == "downloading" and active_episode
                    and active_episode.get("source_id") == source_id):
                raise RuntimeError("Cannot change a media source while one of its episodes is downloading")
            removed = {key for key, episode in self.state["episodes"].items()
                       if episode.get("source_id") == source_id}
            self.state["episodes"] = {
                key: episode for key, episode in self.state["episodes"].items()
                if key not in removed
            }
            self.state["queue"] = [key for key in self.state["queue"] if key not in removed]
            self.state["watched"] = [key for key in self.state["watched"] if key not in removed]
            source.pop("last_watched", None)
            source.update({
                "kind": kind, "url": url, "name": str(name).strip() or url,
                "order": new_order, "initialized": False, "next_check": None,
                "last_error": None, "last_success": None,
            })
        else:
            old_order = source.get("order")
            source.update({
                "kind": kind, "url": url, "name": str(name).strip() or url,
                "order": new_order,
            })
            if old_order != new_order:
                queued_ids = [
                    key for key in self.state["queue"]
                    if key in self.state["episodes"]
                    and self.state["episodes"][key].get("source_id") == source_id
                ]
                queued_set = set(queued_ids)
                queued = [self.state["episodes"][key] for key in queued_ids]
                ordered_ids = iter(
                    episode["id"] for episode in self._ordered_episodes(queued, new_order)
                )
                self.state["queue"] = [
                    next(ordered_ids) if key in queued_set else key
                    for key in self.state["queue"]
                ]
        self._save()

    def rename_source(self, source_id: str, name: str) -> None:
        name = str(name).strip()
        if not name:
            raise ValueError("Media source name cannot be empty")
        self._source(source_id)["name"] = name[:120]
        self._save()

    def remove_source(self, source_id: str) -> None:
        source = self._source(source_id)
        download = self.state.get("download") or {}
        active_episode = self.state["episodes"].get(download.get("episode_id"))
        if (download.get("status") == "downloading" and active_episode
                and active_episode.get("source_id") == source_id):
            raise RuntimeError("Cannot remove a media source while one of its episodes is downloading")
        self.state["sources"] = [s for s in self.state["sources"] if s["id"] != source_id]
        removed = {key for key, episode in self.state["episodes"].items()
                   if episode.get("source_id") == source_id}
        self.state["episodes"] = {key: value for key, value in self.state["episodes"].items()
                                  if key not in removed}
        self.state["queue"] = [key for key in self.state["queue"] if key not in removed]
        self.state["watched"] = [key for key in self.state["watched"] if key not in removed]
        self._save()

    def _source(self, source_id: str) -> dict[str, Any]:
        for source in self.state["sources"]:
            if source["id"] == source_id:
                return source
        raise KeyError(source_id)

    def _list_source(self, source: dict[str, Any]) -> list[dict[str, Any]]:
        self.plugins.reload()
        plugin_items = self.plugins.list_episodes(source["url"])
        if plugin_items is not None:
            return plugin_items
        if source["kind"] == "rss":
            return self.rss.list_episodes(source["url"], source["id"])
        return self.yt_dlp.list_episodes(source["url"], source["id"])

    def check_source(self, source_id: str, *, force: bool = False) -> int:
        source = self._source(source_id)
        now = self.now()
        if not force and source.get("next_check"):
            if datetime.fromisoformat(source["next_check"]) > now:
                return 0
        try:
            listed = self._list_source(source)
            first_check = not source.get("initialized")
            added = 0
            for source_index, episode in enumerate(listed):
                episode_id = episode["id"]
                existing = self.state["episodes"].get(episode_id)
                if existing is not None:
                    existing["source_order"] = source_index
                    continue
                episode["source_id"] = source_id
                episode["source_order"] = source_index
                episode["status"] = "baseline" if first_check else "new"
                episode["discovered_at"] = now.isoformat()
                self.state["episodes"][episode_id] = episode
                if not first_check:
                    added += 1
            source["initialized"] = True
            source["last_error"] = None
            source["last_success"] = now.isoformat()
            source["next_check"] = (now + timedelta(seconds=self.interval)).isoformat()
            if not first_check:
                self._fill_queue(source_id)
            self._save()
            return added
        except Exception as exc:
            source["last_error"] = str(exc)
            source["next_check"] = (now + timedelta(minutes=2)).isoformat()
            self._save()
            return 0

    def _fill_queue(self, source_id: str) -> None:
        if self.ahead <= 0:
            return
        queued = sum(1 for key in self.state["queue"]
                     if self.state["episodes"].get(key, {}).get("source_id") == source_id)
        capacity = self.ahead - queued
        if capacity <= 0:
            return
        candidates = [episode for episode in self.state["episodes"].values()
                      if episode.get("source_id") == source_id and episode.get("status") == "new"]
        source = next((item for item in self.state["sources"]
                       if item.get("id") == source_id), {})
        candidates = self._ordered_episodes(candidates, source.get("order"))
        for episode in candidates[:capacity]:
            episode["status"] = "queued"
            self.state["queue"].append(episode["id"])

    def check_due(self, *, force: bool = False) -> int:
        added = 0
        for source in list(self.state["sources"]):
            added += self.check_source(source["id"], force=force)
        return added

    def queue_episode(self, episode_id: str) -> None:
        episode = self.state["episodes"][episode_id]
        if episode.get("status") in {"downloaded", "watched"}:
            return
        if episode_id not in self.state["queue"]:
            self.state["queue"].append(episode_id)
        episode["status"] = "queued"
        self._save()

    def next_queued(self) -> dict[str, Any] | None:
        for episode_id in self.state["queue"]:
            episode = self.state["episodes"].get(episode_id)
            if episode and episode.get("status") == "queued":
                return episode
        return None

    def _download_episode(self, episode: dict[str, Any], cancelled=None, progress_callback=None) -> str:
        source = self._source(episode["source_id"])
        resolved = self.plugins.resolve_episode(source["url"], episode)
        if is_archive_org(resolved.get("url")):
            raise ValueError("Archive.org media downloads are intentionally unsupported")
        metadata = resolved.get("metadata") or {}
        if metadata.get("is_live") or resolved.get("is_live") or metadata.get("live_status") == "is_live":
            raise ValueError("Live HLS streams cannot be queued as media downloads")
        source_dir = self.output_dir / safe_filename(str(source.get("name") or "Media"))
        source_dir.mkdir(parents=True, exist_ok=True)
        plugin_path = self.plugins.download_episode(source["url"], resolved,
                                                     source_dir, progress_callback, cancelled)
        if plugin_path is not None:
            return plugin_path
        source_name = str(source.get("name") or "Media")
        url = str(resolved.get("url") or "")
        if url.split("?", 1)[0].lower().endswith(".m3u8"):
            screen = self.display.screen_size() if self.display is not None and hasattr(
                self.display, "screen_size") else None
            return self.hls_downloader.download(
                resolved, source_dir, source_name=source_name, screen=screen,
                cancelled=cancelled, progress_callback=progress_callback,
            )
        return self.downloader.download(resolved, source_dir,
                                        format_sort=self._format_sort(), cancelled=cancelled,
                                        progress_callback=progress_callback,
                                        source_name=source_name)
    def _format_sort(self) -> str | None:
        if self.yt_dlp_sort:
            return self.yt_dlp_sort
        height = self.screen_height
        if height is None and self.display is not None:
            height = self.display.screen_height()
        if height is None or height <= 0:
            return None
        # Leave 15% headroom; yt-dlp selects the best resolution at/below this cap,
        # or the smallest available resolution if every format is larger.
        return f"res:{max(144, int(height * 0.85))}"

    @staticmethod
    def _is_streaming_episode(episode: dict[str, Any]) -> bool:
        metadata = episode.get("metadata") or {}
        live = (metadata.get("is_live") or episode.get("is_live")
                or metadata.get("live_status") == "is_live"
                or episode.get("live_status") == "is_live")
        protocol = str(metadata.get("protocol") or episode.get("protocol") or "").lower()
        extension = str(episode.get("ext") or metadata.get("ext") or "").lower()
        url_path = str(episode.get("url") or "").split("?", 1)[0].lower()
        return bool(live or extension == "m3u8" or "m3u8" in protocol
                    or url_path.endswith(".m3u8"))

    def play_episode(self, episode_id: str) -> dict[str, Any]:
        if self.player is None:
            raise RuntimeError("Shared mpv player is not configured")
        episode = self.state["episodes"][episode_id]
        path = episode.get("path")
        download = self.state.get("download") or {}
        if download.get("episode_id") == episode_id and download.get("status") == "downloading":
            partial_path = download.get("part_path")
            if partial_path:
                partial = Path(partial_path)
                try:
                    available = (
                        partial.is_file()
                        and partial.stat().st_size > 0
                        and float(download.get("elapsed") or 0) >= 60
                    )
                except (OSError, TypeError, ValueError):
                    available = False
                if available:
                    episode["partial_path"] = str(partial)
                    episode["partial_duration"] = download.get("duration")
                    path = str(partial)
        if not path or not Path(path).is_file():
            if self._is_streaming_episode(episode):
                path = episode.get("url")
                if not path:
                    raise ValueError("Streaming episode has no playable URL")
            else:
                path = self._download_and_record(episode)
        self.player.load(path, episode.get("title", "Flux Tray"))
        self.current_episode_id = episode_id
        return episode

    def source_summary(self, source_id: str) -> dict[str, Any]:
        source = self._source(source_id)
        episodes = [episode for episode in self.state["episodes"].values()
                    if episode.get("source_id") == source_id]
        unwatched = [episode for episode in episodes if episode.get("status") != "watched"]
        unwatched = self._ordered_episodes(unwatched, source.get("order"))
        episode = unwatched[0] if unwatched else None
        download = self.state.get("download") or {}
        if source.get("last_error"):
            status = "cannot be read"
        elif episode and episode.get("download_error"):
            status = "failed"
        elif episode and download.get("episode_id") == episode.get("id") and download.get("status") == "downloading":
            percent = download.get("percent")
            status = f"{percent:.0f}%" if isinstance(percent, (int, float)) else "downloading"
        elif episode and episode.get("status") == "downloaded":
            status = "ready"
        elif episode and episode.get("status") == "queued":
            status = "queued"
        else:
            status = "not downloaded" if episode else "caught up"
        title = episode.get("title", "Untitled") if episode else "No unwatched episodes"
        last_watched = source.get("last_watched") or {}
        details = [f"Unwatched: {len(unwatched)}"]
        if last_watched.get("title"):
            details.append(f"Last watched: {last_watched['title']}")
        failure = source.get("last_error") or (episode or {}).get("download_error")
        if failure:
            details.append(f"Failure: {failure}")
        return {
            "episode": title, "status": status,
            "new_count": sum(1 for item in episodes if item.get("status") in {"new", "queued"}),
            "unwatched_count": len(unwatched), "tooltip": "\n".join(details),
        }

    def play_next_unwatched(self, source_id: str | None = None) -> dict[str, Any] | None:
        candidates = [episode for episode in self.state["episodes"].values()
                      if episode.get("status") != "watched" and episode.get("status") != "baseline"
                      and (source_id is None or episode.get("source_id") == source_id)]
        candidates.extend(episode for episode in self.state["episodes"].values()
                          if episode.get("status") == "baseline"
                          and (source_id is None or episode.get("source_id") == source_id))
        if not candidates:
            return None
        if source_id is not None:
            order = self._source(source_id).get("order")
            candidates = self._ordered_episodes(candidates, order)
        else:
            candidates.sort(key=lambda item: (item.get("season") or 0, item.get("episode") or 0,
                                              item.get("date") or item.get("discovered_at") or ""))
        return self.play_episode(candidates[0]["id"])

    def update_playback_progress(self) -> bool:
        if self.player is None or self.current_episode_id is None:
            return False
        episode = self.state["episodes"].get(self.current_episode_id)
        if episode is None:
            return False
        source = episode.get("partial_path") or episode.get("path") or episode.get("url")
        if not source:
            return False
        try:
            position = self.player.get_property("time-pos")
            player_duration = self.player.get_property("duration")
            current_path = self.player.get_property("path")
        except OSError:
            return False
        duration = episode.get("partial_duration") if episode.get("partial_path") else player_duration
        if current_path != source or not isinstance(position, (int, float)) or not isinstance(duration, (int, float)) or duration <= 0:
            return False
        fraction = position / duration
        if fraction >= 0.90 or (fraction >= 0.50 and duration - position <= 20):
            self.mark_watched(episode["id"])
            self.current_episode_id = None
            return True
        return False
    def _download_and_record(self, episode: dict[str, Any], *, cancelled=None,
                             progress_callback=None) -> str:
        with self._download_lock:
            existing_path = episode.get("path")
            if existing_path and Path(existing_path).is_file():
                if episode.get("status") != "downloaded":
                    self.mark_downloaded(episode["id"], existing_path)
                return existing_path
            return self._download_and_record_locked(
                episode, cancelled=cancelled, progress_callback=progress_callback
            )

    def _download_and_record_locked(self, episode: dict[str, Any], *, cancelled=None,
                                    progress_callback=None) -> str:
        download_state = {
            "episode_id": episode["id"], "title": episode.get("title", "Untitled"),
            "status": "downloading", "started_at": self.now().isoformat(),
            "error": None,
        }
        self.state["download"] = download_state
        self._save()

        def report_progress(*args):
            if len(args) == 1 and isinstance(args[0], dict):
                details = args[0]
            elif len(args) >= 2:
                details = {"downloaded_bytes": args[0], "total_bytes": args[1]}
            else:
                details = {"message": str(args[0]) if args else ""}
            download_state.update(details)
            if progress_callback is not None:
                progress_callback(dict(download_state))

        try:
            path = self._download_episode(
                episode, cancelled=cancelled, progress_callback=report_progress
            )
        except Exception as exc:
            episode["download_error"] = str(exc)
            episode["last_attempt"] = self.now().isoformat()
            download_state.update({
                "status": "failed", "error": str(exc),
                "completed_at": self.now().isoformat(),
            })
            self._save()
            raise

        self.mark_downloaded(episode["id"], path)
        episode["download_error"] = None
        download_state.update({
            "status": "completed", "path": path, "percent": 100.0,
            "completed_at": self.now().isoformat(),
        })
        self._save()
        return path

    def download_next(self, *, cancelled=None, progress_callback=None) -> dict[str, Any] | None:
        episode = self.next_queued()
        if episode is None:
            return None
        self._download_and_record(
            episode, cancelled=cancelled, progress_callback=progress_callback
        )
        return episode
    def mark_downloaded(self, episode_id: str, path: str) -> None:
        episode = self.state["episodes"][episode_id]
        episode["status"] = "downloaded"
        episode["path"] = path
        self.state["queue"] = [key for key in self.state["queue"] if key != episode_id]
        self._fill_queue(episode["source_id"])
        self._save()

    def mark_watched(self, episode_id: str) -> None:
        episode = self.state["episodes"][episode_id]
        episode["status"] = "watched"
        episode["watched_at"] = self.now().isoformat()
        source = next((item for item in self.state["sources"]
                       if item.get("id") == episode.get("source_id")), None)
        if source is not None:
            source["last_watched"] = {"id": episode_id, "title": episode.get("title"),
                                      "at": episode["watched_at"]}
        if episode_id not in self.state["watched"]:
            self.state["watched"].append(episode_id)
        self.state["queue"] = [key for key in self.state["queue"] if key != episode_id]
        self._fill_queue(episode["source_id"])
        self._save()
