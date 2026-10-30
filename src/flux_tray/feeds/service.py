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
    return any(re.search(r"(?<!\w)" + re.escape(_normal(word)) + r"(?!\w)", normalized)
               for word in words if word.strip())


class FeedService:
    """Owns feed definitions, item state, unread/read-later and mute rules."""

    def __init__(self, store: JsonStore, fetcher: Callable[..., FetchResult] = fetch_feed,
                 *, breaking_words: list[str] | None = None, default_interval: int = 60,
                 now: Callable[[], datetime] = _now):
        self.store = store
        self.fetcher = fetcher
        self.breaking_words = breaking_words or ["breaking"]
        self.default_interval = max(60, int(default_interval))
        self.now = now
        self.state = store.load()
        if not isinstance(self.state, dict):
            self.state = {"feeds": [], "items": {}, "read_later": []}
        self.state.setdefault("feeds", [])
        self.state.setdefault("items", {})
        self.state.setdefault("read_later", [])
        self.state.setdefault("routing_rules", [])

    def _save(self) -> None:
        self.store.save(self.state)

    def add_feed(self, url: str, name: str | None = None, interval: int | None = None) -> str:
        url = url.strip()
        if not url.startswith(("https://", "http://")):
            raise ValueError("Feed URL must use HTTP or HTTPS")
        if any(feed["url"] == url for feed in self.state["feeds"]):
            raise ValueError("Feed already exists")
        feed_id = uuid4().hex
        self.state["feeds"].append({"id": feed_id, "url": url, "name": name or url,
            "interval": max(60, int(interval if interval is not None else self.default_interval)), "next_check": None, "etag": None,
            "modified": None, "muted": False, "last_error": None, "last_success": None})
        self._save()
        return feed_id

    def rename_feed(self, feed_id: str, name: str) -> None:
        name = name.strip()
        if not name:
            raise ValueError("Feed name cannot be empty")
        self._feed(feed_id)["name"] = name
        self._save()

    def set_interval(self, feed_id: str, interval: int) -> None:
        self._feed(feed_id)["interval"] = max(60, int(interval))
        self._save()

    def reorder_feeds(self, ordered_ids: list[str]) -> None:
        current = {feed["id"]: feed for feed in self.state["feeds"]}
        if len(ordered_ids) != len(current) or set(ordered_ids) != set(current):
            raise ValueError("Order must contain every feed exactly once")
        self.state["feeds"] = [current[feed_id] for feed_id in ordered_ids]
        self._save()

    def set_routing_rules(self, rules: list[dict[str, str]]) -> None:
        validated = []
        for rule in rules:
            kind = rule.get("kind", "").strip().lower()
            value = rule.get("value", "").strip()
            if kind not in {"category", "author"} or not value:
                raise ValueError("Routing rules require kind=category|author and a value")
            validated.append({"kind": kind, "value": value})
        self.state["routing_rules"] = validated
        for item_id, item in self.state["items"].items():
            feed = next((f for f in self.state["feeds"] if f["id"] == item["feed_id"]), None)
            if feed is None or feed.get("muted"):
                continue
            if self._matches_routing_rule(item):
                item["read"] = item["seen"] = True
                if item_id not in self.state["read_later"]:
                    self.state["read_later"].append(item_id)
        self._save()

    def _matches_routing_rule(self, item: dict[str, Any]) -> bool:
        author = _normal(item.get("author", ""))
        categories = [_normal(value) for value in item.get("categories", [])]
        for rule in self.state.get("routing_rules", []):
            value = _normal(rule.get("value", ""))
            if rule.get("kind") == "author" and value and value in author:
                return True
            if rule.get("kind") == "category" and value and any(value in category for category in categories):
                return True
        return False
    def set_breaking_words(self, words: list[str]) -> None:
        cleaned = list(dict.fromkeys(word.strip() for word in words if word.strip()))
        self.breaking_words = cleaned
        for item in self.state["items"].values():
            text = " ".join([item.get("title", ""), *item.get("categories", [])])
            item["breaking"] = _whole_word_match(text, cleaned)
        self._save()

    def breaking_items(self) -> list[dict[str, Any]]:
        return [item for item in self.unread_items() if item.get("breaking")]

    def read_later_items(self) -> list[dict[str, Any]]:
        return [self.state["items"][item_id] for item_id in self.state["read_later"]
                if item_id in self.state["items"]]

    def clear_read_later(self, item_id: str) -> None:
        self.remove_read_later(item_id)

    def remove_feed(self, feed_id: str) -> None:
        self.state["feeds"] = [f for f in self.state["feeds"] if f["id"] != feed_id]
        removed_ids = {k for k, v in self.state["items"].items() if v.get("feed_id") == feed_id}
        self.state["items"] = {k: v for k, v in self.state["items"].items() if k not in removed_ids}
        self.state["read_later"] = [item_id for item_id in self.state["read_later"]
                                    if item_id not in removed_ids]
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
            return 0 if feed.get("muted") else fresh
        except Exception as exc:
            feed["last_error"] = str(exc)
            feed["next_check"] = _iso(now + timedelta(minutes=2))
            self._save()
            return 0

    def check_due(self, *, force: bool = False) -> int:
        total = 0
        for feed in list(self.state["feeds"]):
            total += self.check_feed(feed["id"], force=force)
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
            routed = self._matches_routing_rule(item) and not feed.get("muted")
            if not item["seen"] and not routed:
                fresh += 1
            if routed:
                item["read"] = item["seen"] = True
                self.state["read_later"].append(item_id)
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
