"""Typed access to the human-editable INI file."""

from __future__ import annotations

import configparser
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Paths:
    config_dir: Path
    data_dir: Path
    state_dir: Path
    plugin_dir: Path

    @classmethod
    def user_default(cls) -> "Paths":
        home = Path.home()
        config = home / ".config" / "flux-tray"
        return cls(
            config_dir=config,
            data_dir=home / ".local" / "share" / "flux-tray",
            state_dir=home / ".local" / "state" / "flux-tray",
            plugin_dir=config / "media-plugins",
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

    def ensure_exists(self) -> None:
        if self.path.exists():
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(DEFAULT_CONFIG, encoding="utf-8")


DEFAULT_CONFIG = """# Flux Tray configuration

[feeds]
interval = 60

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

[launcher]
"""
