"""Batched logged-out Twitch channel status lookup."""

from __future__ import annotations

import json
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from datetime import datetime, timezone
from typing import Callable


ENDPOINT = "https://gql.twitch.tv/gql"
# Twitch's public web client identifier, not a user credential.
CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"
QUERY = """query FluxTrayChannel($login: String!) {
  user(login: $login) {
    displayName
    stream { title viewersCount createdAt game { name } }
  }
}"""
_RESERVED = {"directory", "downloads", "jobs", "p", "products", "search", "settings",
             "signup", "login", "subscriptions", "turbo", "wallet"}


class TwitchLookupError(RuntimeError):
    pass


def channel_login(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {
        "twitch.tv", "www.twitch.tv", "m.twitch.tv"
    }:
        raise ValueError("Expected a Twitch channel URL")
    parts = [part for part in parsed.path.split("/") if part]
    if not parts or parts[0].casefold() in _RESERVED:
        raise ValueError("URL does not identify a Twitch channel")
    return parts[0]


class TwitchProbe:
    def __init__(self, *, opener: Callable = urlopen, timeout: float = 15.0):
        self.opener = opener
        self.timeout = timeout

    def check_many(self, urls: list[str]) -> dict[str, dict]:
        """Return status for URLs, issuing no more than 20 GQL operations per request."""
        logins = [(url, channel_login(url)) for url in urls]
        found: dict[str, dict] = {}
        for offset in range(0, len(logins), 20):
            batch = logins[offset:offset + 20]
            body = [{
                "operationName": "FluxTrayChannel",
                "variables": {"login": login},
                "query": QUERY,
            } for _, login in batch]
            request = Request(ENDPOINT, data=json.dumps(body).encode("utf-8"), headers={
                "Client-ID": CLIENT_ID,
                "Content-Type": "application/json",
                "User-Agent": "FluxTray/0.1",
            })
            try:
                with self.opener(request, timeout=self.timeout) as response:
                    raw = response.read(1_000_001)
                if len(raw) > 1_000_000:
                    raise TwitchLookupError("Twitch response exceeded 1 MB")
                payload = json.loads(raw)
            except Exception as exc:
                raise TwitchLookupError(f"Twitch lookup failed: {exc}") from exc
            if not isinstance(payload, list) or len(payload) != len(batch):
                raise TwitchLookupError("Twitch returned an unexpected batch response")
            checked = datetime.now(timezone.utc).isoformat()
            for (url, login), result in zip(batch, payload):
                if result.get("errors"):
                    raise TwitchLookupError(f"Twitch rejected lookup for {login}")
                user = (result.get("data") or {}).get("user")
                if user is None or user.get("stream") is None:
                    found[url] = {"status": "offline", "metadata": {}, "streams": []}
                    continue
                stream = user["stream"]
                metadata = {
                    "author": user.get("displayName") or login,
                    "title": stream.get("title") or "",
                    "category": (stream.get("game") or {}).get("name") or "",
                    "viewers": stream.get("viewersCount"),
                    "created_at": stream.get("createdAt"),
                    "checked_at": checked,
                }
                found[url] = {"status": "live", "metadata": metadata,
                              "streams": ["best"]}
        return found

    def check(self, url: str) -> dict:
        return self.check_many([url])[url]
