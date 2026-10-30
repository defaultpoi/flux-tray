"""Feed state and polling rules, independent of GTK."""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from uuid import uuid4

import feedparser

from flux_tray.core.storage import JsonStore
from flux_tray.feeds.fetch import FetchResult, fetch_feed


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _parse_date(entry: Any) -> datetime | None:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    try:
        from calendar import timegm
        return datetime.fromtimestamp(timegm(parsed), timezone.utc)
    except (OverflowError, TypeError, ValueError):
        return None


def _normal(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value.casefold())
    return "".join(ch for ch in folded if not unicodedata.combining(ch))


def _whole_word_match(text: str, words: list[str]) -> bool:
    normalized = _normal(text)
    return any(re.search(r"(?<!\\w)" + re.escape(_normal(word)) + r"(?!\\w)", normalized)
               for word in words if word.strip())


class FeedService:
    """Owns feed definitions, item state, unread/read-later and mute rules."""

    def __init__(self, store: JsonStore, fetcher: Callable[..., FetchResult] = fetch_feed,
                 *, breaking_words: list[str] | None = None, now: Callable[[], datetime] = _now):
        self.store = store
        self.fetcher = fetcher
        self.breaking_words = breaking_words or ["breaking"]
        self.now = now
        self.state = store.load()
        if not isinstance(self.state, dict):
            self.state = {"feeds": [], "items": {}, "read_later": []}
        self.state.setdefault("feeds", [])
        self.state.setdefault("items", {})
        self.state.setdefault("read_later", [])

    def _save(self) -> None:
        self.store.save(self.state)

    def add_feed(self, url: str, name: str | None = None, interval: int = 60) -> str:
        url = url.strip()
        if not url.startswith(("https://", "http://")):
            raise ValueError("Feed URL must use HTTP or HTTPS")
        if any(feed["url"] == url for feed in self.state["feeds"]):
            raise ValueError("Feed already exists")
        feed_id = uuid4().hex
        self.state["feeds"].append({"id": feed_id, "url": url, "name": name or url,
            "interval": max(60, int(interval)), "next_check": None, "etag": None,
            "modified": None, "muted": False, "last_error": None, "last_success": None})
        self._save()
        return feed_id

    def remove_feed(self, feed_id: str) -> None:
        self.state["feeds"] = [f for f in self.state["feeds"] if f["id"] != feed_id]
        self.state["items"] = {k: v for k, v in self.state["items"].items()
                                if v.get("feed_id") != feed_id}
        self._save()

    def set_muted(self, feed_id: str, muted: bool) -> None:
        feed = self._feed(feed_id)
        feed["muted"] = bool(muted)
        if muted:
            self.state["read_later"] = [i for i in self.state["read_later"]
                                         if self.state["items"].get(i, {}).get("feed_id") != feed_id]
        self._save()

    def _feed(self, feed_id: str) -> dict[str, Any]:
        for feed in self.state["feeds"]:
            if feed["id"] == feed_id:
                return feed
        raise KeyError(feed_id)

    def check_feed(self, feed_id: str, *, force: bool = False) -> int:
        feed = self._feed(feed_id)
        now = self.now()
        if not force and feed.get("next_check"):
            if datetime.fromisoformat(feed["next_check"]) > now:
                return 0
        try:
            result = self.fetcher(feed["url"], etag=feed.get("etag"),
                                  modified=feed.get("modified"))
            if not result.not_modified and result.body is not None:
                parsed = feedparser.parse(result.body)
                if parsed.bozo and not parsed.entries:
                    raise ValueError(f"Invalid feed: {parsed.bozo_exception}")
                fresh = self._ingest(feed, parsed.entries, now)
            else:
                fresh = 0
            feed["etag"], feed["modified"] = result.etag, result.modified
            feed["last_error"] = None
            feed["last_success"] = _iso(now)
            feed["next_check"] = _iso(now + timedelta(seconds=feed["interval"]))
            self._save()
            return fresh
        except Exception as exc:
            feed["last_error"] = str(exc)
            feed["next_check"] = _iso(now + timedelta(minutes=2))
            self._save()
            return 0

    def check_due(self) -> int:
        total = 0
        for feed in list(self.state["feeds"]):
            total += self.check_feed(feed["id"])
        return total

    def _ingest(self, feed: dict[str, Any], entries: list[Any], now: datetime) -> int:
        fresh = 0
        for entry in entries:
            link = str(entry.get("link") or "").strip()
            identity = str(entry.get("id") or link or entry.get("title") or "").strip()
            if not identity:
                continue
            item_id = f"{feed['id']}:{identity}"
            if item_id in self.state["items"]:
                continue
            published = _parse_date(entry)
            old = published is not None and published < now - timedelta(hours=24)
            item = {"id": item_id, "feed_id": feed["id"],
                "title": str(entry.get("title") or "(untitled)"), "link": link,
                "summary": str(entry.get("summary") or ""),
                "author": str(entry.get("author") or ""),
                "categories": [str(t.get("term", "")) for t in entry.get("tags", [])],
                "published": _iso(published) if published else None,
                "seen": bool(old), "read": bool(old),
                "breaking": False}
            text = " ".join([item["title"], *item["categories"]])
            item["breaking"] = _whole_word_match(text, self.breaking_words)
            self.state["items"][item_id] = item
            if not item["seen"]:
                fresh += 1
        unread = sorted((i for i in self.state["items"].values() if not i["read"]),
                        key=lambda i: i.get("published") or "")
        for item in unread[:-500]:
            item["read"] = True
            item["seen"] = True
        return fresh

    def mark_read(self, item_id: str) -> None:
        item = self.state["items"][item_id]
        item["read"] = item["seen"] = True
        self.state["read_later"] = [i for i in self.state["read_later"] if i != item_id]
        self._save()

    def mark_feed_read(self, feed_id: str) -> None:
        for item in self.state["items"].values():
            if item["feed_id"] == feed_id:
                item["read"] = item["seen"] = True
        self._save()

    def save_for_later(self, item_id: str) -> None:
        item = self.state["items"][item_id]
        feed = self._feed(item["feed_id"])
        if feed.get("muted"):
            return
        if item_id not in self.state["read_later"]:
            self.state["read_later"].append(item_id)
        item["read"] = item["seen"] = True
        self._save()

    def remove_read_later(self, item_id: str) -> None:
        self.state["read_later"] = [i for i in self.state["read_later"] if i != item_id]
        self._save()

    def unread_count(self) -> int:
        muted = {f["id"] for f in self.state["feeds"] if f.get("muted")}
        return sum(1 for item in self.state["items"].values()
                   if not item["read"] and item["feed_id"] not in muted)

    def unread_items(self) -> list[dict[str, Any]]:
        muted = {f["id"] for f in self.state["feeds"] if f.get("muted")}
        return sorted((i for i in self.state["items"].values()
                       if not i["read"] and i["feed_id"] not in muted),
                      key=lambda i: i.get("published") or "", reverse=True)
