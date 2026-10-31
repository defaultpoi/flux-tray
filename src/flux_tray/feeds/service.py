"""Feed state and polling rules, independent of GTK."""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from uuid import uuid4

import feedparser

from flux_tray.core.storage import JsonStore
from flux_tray.feeds.fetch import FetchResult, fetch_feed, validate_feed_url


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


def _get_author(entry: Any) -> str:
    """Extract author from feedparser entry, checking multiple possible fields.
    Prefers parsed name from author_detail over raw author string."""
    # Try author_detail first (feedparser standard for parsed author info)
    author_detail = entry.get("author_detail")
    if isinstance(author_detail, dict):
        name = author_detail.get("name")
        if name:
            return str(name)
    # Try authors list (some feeds have multiple authors)
    authors = entry.get("authors")
    if authors:
        first = authors[0]
        if isinstance(first, dict):
            return str(first.get("name", ""))
        return str(first)
    # Fall back to raw author string (may be email format)
    author = entry.get("author")
    if author:
        return str(author)
    return ""


def _parse_rules(rules: list[str]) -> tuple[list[str], list[str]]:
    """Parse semicolon-separated rules into category and author patterns."""
    categories = []
    authors = []
    for rule in rules:
        rule = rule.strip()
        if not rule:
            continue
        if rule.startswith("category:"):
            categories.append(_normal(rule[9:]))  # "category:" is 9 chars
        elif rule.startswith("author:"):
            authors.append(_normal(rule[7:]))  # "author:" is 7 chars
    return categories, authors


def _matches_per_feed_rules(item: dict[str, Any], mute_categories: list[str],
                             mute_authors: list[str], read_later_categories: list[str],
                             read_later_authors: list[str]) -> tuple[bool, bool]:
    """Check if item matches per-feed mute or read-later rules.
    Returns (is_muted, is_read_later).
    Mute rule beats read-later rule (per void-tray behavior)."""
    author = _normal(item.get("author", ""))
    categories = [_normal(value) for value in item.get("categories", [])]

    # Check mute rules first (mute beats read-later)
    for cat in mute_categories:
        if cat and any(cat in c for c in categories):
            return True, False
    for auth in mute_authors:
        if auth and auth in author:
            return True, False

    # Check read-later rules
    for cat in read_later_categories:
        if cat and any(cat in c for c in categories):
            return False, True
    for auth in read_later_authors:
        if auth and auth in author:
            return False, True

    return False, False


def _apply_feed_rules_to_items(feed: dict[str, Any], items: dict[str, Any],
                                routing_rules: list[dict[str, str]],
                                breaking_words: list[str]) -> tuple[int, list[str]]:
    """Apply feed rules to items and return (fresh_count, read_later_ids_to_add)."""
    fresh = 0
    read_later_to_add = []
    mute_cats = feed.get("mute_categories", [])
    mute_auths = feed.get("mute_authors", [])
    rl_cats = feed.get("read_later_categories", [])
    rl_auths = feed.get("read_later_authors", [])

    for item_id, item in items.items():
        if item.get("feed_id") != feed["id"]:
            continue

        # Check per-feed mute/read-later rules first
        is_muted, is_read_later = _matches_per_feed_rules(
            item, mute_cats, mute_auths, rl_cats, rl_auths)

        # Then check global routing rules
        routed = False
        if not feed.get("muted"):
            author = _normal(item.get("author", ""))
            categories = [_normal(value) for value in item.get("categories", [])]
            for rule in routing_rules:
                value = _normal(rule.get("value", ""))
                if rule.get("kind") == "author" and value and value in author:
                    routed = True
                    break
                if rule.get("kind") == "category" and value and any(value in category for category in categories):
                    routed = True
                    break

        if is_muted:
            item["read"] = item["seen"] = True
            # Mute beats read-later - don't add to read_later
        elif is_read_later or routed:
            item["read"] = item["seen"] = True
            if item_id not in read_later_to_add:
                read_later_to_add.append(item_id)
        elif not item["seen"]:
            fresh += 1

    return fresh, read_later_to_add


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

    def add_feed(self, url: str, name: str | None = None, interval: int | None = None,
                 mute_rules: list[str] | None = None,
                 read_later_rules: list[str] | None = None) -> str:
        url = validate_feed_url(url.strip())
        if any(feed["url"] == url for feed in self.state["feeds"]):
            raise ValueError("Feed already exists")
        feed_id = uuid4().hex
        mute_cats, mute_auths = _parse_rules(mute_rules or [])
        rl_cats, rl_auths = _parse_rules(read_later_rules or [])
        self.state["feeds"].append({"id": feed_id, "url": url, "site_url": None, "name": name or url,
            "interval": max(60, int(interval if interval is not None else self.default_interval)),
            "next_check": None, "etag": None, "modified": None, "muted": False,
            "last_error": None, "last_success": None,
            "mute_categories": mute_cats, "mute_authors": mute_auths,
            "read_later_categories": rl_cats, "read_later_authors": rl_auths})
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

    def set_feed_rules(self, feed_id: str, mute_rules: list[str] | None = None,
                       read_later_rules: list[str] | None = None) -> None:
        feed = self._feed(feed_id)
        if mute_rules is not None:
            mute_cats, mute_auths = _parse_rules(mute_rules)
            feed["mute_categories"] = mute_cats
            feed["mute_authors"] = mute_auths
        if read_later_rules is not None:
            rl_cats, rl_auths = _parse_rules(read_later_rules)
            feed["read_later_categories"] = rl_cats
            feed["read_later_authors"] = rl_auths
        # Re-apply rules to existing items for this feed
        fresh, read_later_to_add = _apply_feed_rules_to_items(
            feed, self.state["items"], self.state["routing_rules"], self.breaking_words)
        for item_id in read_later_to_add:
            if item_id not in self.state["read_later"]:
                self.state["read_later"].append(item_id)
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
        # Re-apply rules to all items
        for feed in self.state["feeds"]:
            fresh, read_later_to_add = _apply_feed_rules_to_items(
                feed, self.state["items"], self.state["routing_rules"], self.breaking_words)
            for item_id in read_later_to_add:
                if item_id not in self.state["read_later"]:
                    self.state["read_later"].append(item_id)
        self._save()

    def set_breaking_words(self, words: list[str]) -> None:
        cleaned = list(dict.fromkeys(word.strip() for word in words if word.strip()))
        self.breaking_words = cleaned
        for item in self.state["items"].values():
            text = " ".join([item.get("title", ""), *item.get("categories", [])])
            was_breaking = item.get("breaking", False)
            item["breaking"] = _whole_word_match(text, cleaned)
            if item["breaking"] and not was_breaking:
                item["breaking_notified"] = False
        self._save()

    def breaking_items(self) -> list[dict[str, Any]]:
        return [item for item in self.unread_items() if item.get("breaking")]

    def take_unnotified_breaking_items(self) -> list[dict[str, Any]]:
        pending = [item for item in self.unread_items()
                   if item.get("breaking") and not item.get("breaking_notified", False)]
        if pending:
            for item in pending:
                item["breaking_notified"] = True
            self._save()
        return pending

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
                site_url = str(parsed.feed.get("link") or "").strip()
                if site_url.startswith(("https://", "http://")):
                    feed["site_url"] = site_url
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
        mute_cats = feed.get("mute_categories", [])
        mute_auths = feed.get("mute_authors", [])
        rl_cats = feed.get("read_later_categories", [])
        rl_auths = feed.get("read_later_authors", [])

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
                "author": _get_author(entry),
                "categories": [str(t.get("term", "")) for t in entry.get("tags", [])],
                "published": _iso(published) if published else None,
                "seen": bool(old), "read": bool(old),
                "breaking": False, "breaking_notified": False}
            text = " ".join([item["title"], *item["categories"]])
            item["breaking"] = _whole_word_match(text, self.breaking_words)
            self.state["items"][item_id] = item

            # Check per-feed mute/read-later rules first
            is_muted, is_read_later = _matches_per_feed_rules(
                item, mute_cats, mute_auths, rl_cats, rl_auths)

            # Then check global routing rules
            routed = self._matches_routing_rule(item) and not feed.get("muted")

            if is_muted:
                item["read"] = item["seen"] = True
                # Mute beats read-later - don't add to read_later
            elif is_read_later or routed:
                item["read"] = item["seen"] = True
                if item_id not in self.state["read_later"]:
                    self.state["read_later"].append(item_id)
            elif not item["seen"]:
                fresh += 1

        unread = sorted((i for i in self.state["items"].values() if not i["read"]),
                        key=lambda i: i.get("published") or "")
        for item in unread[:-500]:
            item["read"] = True
            item["seen"] = True
        return fresh

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
