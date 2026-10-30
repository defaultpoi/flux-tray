"""Streamlink JSON-based live status checks for supported channel URLs."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from uuid import uuid4

from flux_tray.core.process import ProcessResult, ProcessSupervisor
from flux_tray.core.storage import JsonStore
from flux_tray.live.twitch import TwitchProbe


class StreamlinkProbe:
    def __init__(self, runner: Callable[..., ProcessResult] | None = None,
                 process: ProcessSupervisor | None = None, timeout: float = 25):
        self.process = process or ProcessSupervisor()
        self.runner = runner or self.process.run
        self.timeout = timeout

    def check(self, url: str) -> dict[str, Any]:
        result = self.runner(["streamlink", "--json", url], timeout=self.timeout)
        payload = None
        if result.stdout.strip():
            try:
                payload = json.loads(result.stdout)
            except json.JSONDecodeError:
                payload = None
        if result.returncode == 0 and isinstance(payload, dict):
            streams = payload.get("streams") or {}
            metadata = payload.get("metadata") or {}
            if streams:
                return {"status": "live", "metadata": metadata, "streams": list(streams)}
            return {"status": "offline", "metadata": metadata, "streams": []}
        error = (result.stderr or result.stdout).strip()
        lowered = error.casefold()
        if any(marker in lowered for marker in ("no playable streams found", "no streams found",
                                                 "stream is offline", "channel is offline")):
            return {"status": "offline", "metadata": {}, "streams": []}
        raise RuntimeError(error or f"Streamlink exited with status {result.returncode}")


class LiveService:
    def __init__(self, store: JsonStore, probe: StreamlinkProbe | None = None,
                 *, twitch_probe=None, interval: int = 900,
                 now: Callable[[], datetime] | None = None, player=None, quality: str = "best"):
        self.store = store
        self.probe = probe or StreamlinkProbe()
        self.twitch_probe = twitch_probe or (TwitchProbe() if probe is None else probe)
        self.interval = max(60, int(interval))
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.player = player
        self.quality = quality
        self.state = store.load()
        if not isinstance(self.state, dict):
            self.state = {}
        self.state.setdefault("channels", [])

    def _save(self):
        self.store.save(self.state)

    def add_channel(self, platform: str, name: str, url: str) -> str:
        platform = platform.strip().lower()
        if platform not in {"twitch", "youtube"}:
            raise ValueError("Platform must be twitch or youtube")
        if not url.startswith(("https://", "http://")):
            raise ValueError("Channel URL must use HTTP or HTTPS")
        if any(channel["url"] == url for channel in self.state["channels"]):
            raise ValueError("Channel already exists")
        channel_id = uuid4().hex
        self.state["channels"].append({
            "id": channel_id, "platform": platform, "name": name.strip() or url,
            "url": url, "status": "unknown", "metadata": {}, "streams": [],
            "last_error": None, "next_check": None, "last_check": None,
        })
        self._save()
        return channel_id

    def remove_channel(self, channel_id: str) -> None:
        self.state["channels"] = [c for c in self.state["channels"] if c["id"] != channel_id]
        self._save()

    def check_channel(self, channel_id: str, *, force: bool = False) -> str:
        channel = next((c for c in self.state["channels"] if c["id"] == channel_id), None)
        if channel is None:
            raise KeyError(channel_id)
        now = self.now()
        if not force and channel.get("next_check"):
            if datetime.fromisoformat(channel["next_check"]) > now:
                return channel["status"]
        try:
            checker = self.twitch_probe if channel["platform"] == "twitch" else self.probe
            result = checker.check(channel["url"])
            channel["status"] = result["status"]
            channel["metadata"] = result.get("metadata", {})
            channel["streams"] = result.get("streams", [])
            channel["last_error"] = None
            channel["last_check"] = now.isoformat()
            channel["next_check"] = (now + timedelta(seconds=self.interval)).isoformat()
        except Exception as exc:
            # Preserve the last-known online/offline state; expose the error separately.
            channel["last_error"] = str(exc)
            channel["next_check"] = (now + timedelta(minutes=2)).isoformat()
        self._save()
        return channel["status"]

    def check_due(self, *, force: bool = False) -> int:
        transitions = 0
        now = self.now()
        due = []
        for channel in self.state["channels"]:
            next_check = channel.get("next_check")
            if force or not next_check or datetime.fromisoformat(next_check) <= now:
                due.append(channel)
        twitch = [channel for channel in due if channel["platform"] == "twitch"]
        youtube = [channel for channel in due if channel["platform"] == "youtube"]
        if twitch and hasattr(self.twitch_probe, "check_many"):
            try:
                results = self.twitch_probe.check_many([channel["url"] for channel in twitch])
            except Exception as exc:
                for channel in twitch:
                    channel["last_error"] = str(exc)
                    channel["next_check"] = (now + timedelta(minutes=2)).isoformat()
            else:
                for channel in twitch:
                    transitions += self._apply_check_result(channel, results[channel["url"]], now)
        else:
            for channel in twitch:
                transitions += self._check_due_channel(channel, now)
        for channel in youtube:
            transitions += self._check_due_channel(channel, now)
        if due:
            self._save()
        return transitions

    def _check_due_channel(self, channel: dict, now: datetime) -> int:
        previous = channel.get("status")
        try:
            checker = self.twitch_probe if channel["platform"] == "twitch" else self.probe
            result = checker.check(channel["url"])
        except Exception as exc:
            channel["last_error"] = str(exc)
            channel["next_check"] = (now + timedelta(minutes=2)).isoformat()
            return 0
        return self._apply_check_result(channel, result, now, previous)

    def _apply_check_result(self, channel: dict, result: dict, now: datetime,
                            previous: str | None = None) -> int:
        previous = channel.get("status") if previous is None else previous
        channel["status"] = result["status"]
        channel["metadata"] = result.get("metadata", {})
        channel["streams"] = result.get("streams", [])
        channel["last_error"] = None
        channel["last_check"] = now.isoformat()
        channel["next_check"] = (now + timedelta(seconds=self.interval)).isoformat()
        return int(channel["status"] == "live" and previous != "live")

    def play_channel(self, channel_id: str) -> None:
        if self.player is None:
            raise RuntimeError("mpv player is not configured")
        channel = next((c for c in self.state["channels"] if c["id"] == channel_id), None)
        if channel is None:
            raise KeyError(channel_id)
        result = self.probe.runner(["streamlink", "--stream-url", channel["url"], self.quality],
                                   timeout=45)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "Streamlink could not resolve the channel")
        urls = [line.strip() for line in result.stdout.splitlines()
                if line.strip().startswith(("http://", "https://"))]
        if not urls:
            raise RuntimeError("Streamlink did not return a playable URL")
        metadata = channel.get("metadata", {})
        title = metadata.get("title") or "Live"
        site = channel["platform"].title()
        self.player.load(urls[-1], f"{site} · {channel['name']} · {title}")
    def live_channels(self) -> list[dict[str, Any]]:
        return [channel for channel in self.state["channels"] if channel.get("status") == "live"]
