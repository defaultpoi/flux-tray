"""Typed access to the human-editable INI file."""

from __future__ import annotations

import configparser
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class Paths:
    config_dir: Path
    data_dir: Path
    state_dir: Path
    plugin_dir: Path

    @classmethod
    def user_default(cls) -> "Paths":
        home = Path.home()
        # Allow override via environment variable for read-only home directories
        config_dir = Path(os.environ.get("FLUX_TRAY_CONFIG_DIR", ""))
        if config_dir.is_absolute():
            config = config_dir
        else:
            config = home / ".config" / "flux-tray"
        
        data_dir = Path(os.environ.get("FLUX_TRAY_DATA_DIR", ""))
        if not data_dir.is_absolute():
            data_dir = home / ".local" / "share" / "flux-tray"
        
        state_dir = Path(os.environ.get("FLUX_TRAY_STATE_DIR", ""))
        if not state_dir.is_absolute():
            state_dir = home / ".local" / "state" / "flux-tray"
        
        return cls(
            config_dir=config,
            data_dir=data_dir,
            state_dir=state_dir,
            plugin_dir=config / "media-plugins",
        )


# Feed line format: URL|display name|interval minutes|mute rules|read-later rules
# Mute rules and read-later rules are semicolon-separated category/author patterns
# Example: https://example.com/feed.xml|Example Feed|60|category:news;author:john|category:tech
FEED_LINE_PATTERN = re.compile(
    r"^(?P<url>[^|]+)"
    r"(?:\|(?P<name>[^|]*))?"
    r"(?:\|(?P<interval>\d+))?"
    r"(?:\|(?P<mute>[^|]*))?"
    r"(?:\|(?P<read_later>[^|]*))?$"
)


class Config:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.parser = configparser.ConfigParser(
            interpolation=None, inline_comment_prefixes=("#",)
        )

    def load(self) -> None:
        self.parser.read(self.path, encoding="utf-8")

    def get(self, section: str, key: str, fallback: str | None = None) -> str | None:
        return self.parser.get(section, key, fallback=fallback)

    def get_int(self, section: str, key: str, fallback: int, minimum: int | None = None) -> int:
        try:
            value = self.parser.getint(section, key, fallback=fallback)
        except ValueError:
            value = fallback
        return max(value, minimum) if minimum is not None else value

    def get_bool(self, section: str, key: str, fallback: bool = False) -> bool:
        try:
            return self.parser.getboolean(section, key, fallback=fallback)
        except ValueError:
            return fallback

    def get_feeds(self) -> list[dict[str, Any]]:
        """Parse feed lines from [feeds] section using void-tray pipe-delimited format."""
        feeds = []
        raw = self.parser.get("feeds", "sources", fallback="")
        for line in raw.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            match = FEED_LINE_PATTERN.match(line)
            if not match:
                continue
            url = match.group("url").strip()
            name = match.group("name")
            interval_str = match.group("interval")
            mute_str = match.group("mute") or ""
            read_later_str = match.group("read_later") or ""
            feeds.append({
                "url": url,
                "name": name.strip() if name else url,
                "interval": int(interval_str) if interval_str and interval_str.isdigit() else 60,
                "mute_rules": [r.strip() for r in mute_str.split(";") if r.strip()],
                "read_later_rules": [r.strip() for r in read_later_str.split(";") if r.strip()],
            })
        return feeds

    def set_feeds(self, feeds: list[dict[str, Any]]) -> None:
        """Write feed lines to [feeds] section in void-tray pipe-delimited format."""
        if not self.parser.has_section("feeds"):
            self.parser.add_section("feeds")
        lines = []
        for feed in feeds:
            parts = [
                feed["url"],
                feed.get("name", feed["url"]),
                str(feed.get("interval", 60)),
                ";".join(feed.get("mute_rules", [])),
                ";".join(feed.get("read_later_rules", [])),
            ]
            lines.append("|".join(parts))
        self.parser.set("feeds", "sources", "\n".join(lines))
        self._write()

    def get_mute_rules(self) -> list[str]:
        """Get global mute rules from [mute] section."""
        raw = self.parser.get("mute", "rules", fallback="")
        return [line.strip() for line in raw.splitlines() if line.strip() and not line.startswith("#")]

    def set_mute_rules(self, rules: list[str]) -> None:
        if not self.parser.has_section("mute"):
            self.parser.add_section("mute")
        self.parser.set("mute", "rules", "\n".join(rules))
        self._write()

    def get_highlight_rules(self) -> list[str]:
        """Get global highlight rules from [highlight] section."""
        raw = self.parser.get("highlight", "rules", fallback="")
        return [line.strip() for line in raw.splitlines() if line.strip() and not line.startswith("#")]

    def set_highlight_rules(self, rules: list[str]) -> None:
        if not self.parser.has_section("highlight"):
            self.parser.add_section("highlight")
        self.parser.set("highlight", "rules", "\n".join(rules))
        self._write()

    def set_many(self, section: str, values: dict[str, str]) -> None:
        if not self.parser.has_section(section):
            self.parser.add_section(section)
        for key, value in values.items():
            self.parser.set(section, key, str(value))
        self._write()

    def remove_option(self, section: str, key: str) -> bool:
        removed = self.parser.remove_option(section, key)
        if removed:
            self._write()
        return removed

    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=f".{self.path.name}.",
                                         suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                self.parser.write(stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        except BaseException:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise

    def ensure_exists(self) -> None:
        if self.path.exists():
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(DEFAULT_CONFIG, encoding="utf-8")


DEFAULT_CONFIG = """# Flux Tray configuration

[feeds]
# Format: URL|display name|interval minutes|mute rules|read-later rules
# Mute/read-later rules: semicolon-separated category:NAME or author:NAME
# Example: https://example.com/feed.xml|Example Feed|60|category:news;author:john|category:tech
sources =

[popup]
auto_open = true
width = 440
height = 620

[live]
interval = 15
quality = best

[media]
interval = 60
ahead = 2
path = ~/Videos
screen_height =
yt_dlp_sort =

[weather]
interval = 30
alerts = false
country = romania
region =
location =
lat =
lon =

[updates]
interval = 12
installer = topgrade
topgrade_steps =
orphans = true

[timer]
max = 120
step = 60

[connectivity]
interval = 10
reset_command =

[launcher]

[mute]
# Global mute rules (category:NAME or author:NAME), one per line
rules =

[highlight]
# Global highlight rules (words to match in title/categories), one per line
rules =
"""
