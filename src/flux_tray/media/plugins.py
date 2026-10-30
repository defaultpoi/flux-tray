"""Trusted Python media plugin loader; reload only at source-check boundaries."""

from __future__ import annotations

import importlib.util
import logging
from pathlib import Path
from types import ModuleType
from typing import Any

from flux_tray.media.episodes import normalize_episode


class MediaPluginRegistry:
    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self.log = logging.getLogger("flux_tray.media.plugins")
        self.plugins: list[ModuleType] = []

    def reload(self) -> None:
        loaded = []
        if self.directory.exists():
            for path in sorted(self.directory.glob("*.py")):
                try:
                    spec = importlib.util.spec_from_file_location(
                        f"flux_tray_user_plugin_{path.stem}", path
                    )
                    if spec is None or spec.loader is None:
                        raise ImportError("No module loader available")
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    if not callable(getattr(module, "list_episodes", None)):
                        raise TypeError("Plugin must define list_episodes(source)")
                    loaded.append(module)
                except Exception:
                    self.log.exception("Could not load media plugin %s", path)
        self.plugins = sorted(loaded, key=lambda plugin: int(getattr(plugin, "ORDER", 100)))

    def _select(self, source: str) -> ModuleType | None:
        if source.startswith("plugin:"):
            _, name, _, remainder = source.split(":", 3) if source.count(":") >= 3 else (None, None, None, None)
            for plugin in self.plugins:
                if str(getattr(plugin, "NAME", plugin.__name__)) == name:
                    return plugin
            raise KeyError(f"Media plugin not found: {name}")
        for plugin in self.plugins:
            matches = getattr(plugin, "matches", None)
            if callable(matches):
                try:
                    if matches(source):
                        return plugin
                except Exception:
                    self.log.exception("Plugin matcher failed: %s", getattr(plugin, "NAME", plugin.__name__))
        return None

    def list_episodes(self, source: str) -> list[dict[str, Any]] | None:
        plugin = self._select(source)
        if plugin is None:
            return None
        records = plugin.list_episodes(source)
        if not isinstance(records, (list, tuple)):
            raise TypeError("Plugin list_episodes must return a list")
        source_id = f"plugin:{getattr(plugin, 'NAME', plugin.__name__)}"
        episodes = []
        for raw in records:
            if not isinstance(raw, dict):
                raise TypeError("Plugin episodes must be dictionaries")
            episodes.append(normalize_episode(raw, source_id).to_dict())
        return episodes
