"""Trusted Python media plugin loader; reload only at source-check boundaries."""

from __future__ import annotations

import importlib.util
import logging
import sys
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
                module_name = f"flux_tray_user_plugin_{path.stem}"
                try:
                    spec = importlib.util.spec_from_file_location(module_name, path)
                    if spec is None or spec.loader is None:
                        raise ImportError("No module loader available")
                    module = importlib.util.module_from_spec(spec)
                    sys.modules[module_name] = module
                    spec.loader.exec_module(module)
                    if not callable(getattr(module, "list_episodes", None)):
                        raise TypeError("Plugin must define list_episodes(source)")
                    loaded.append(module)
                except Exception:
                    sys.modules.pop(module_name, None)
                    self.log.exception("Could not load media plugin %s", path)
        def order(plugin):
            try:
                return int(getattr(plugin, "ORDER", 100))
            except (TypeError, ValueError):
                return 100
        self.plugins = sorted(loaded, key=order)

    def _select(self, source: str) -> tuple[ModuleType, str] | None:
        if source.startswith("plugin:"):
            parts = source.split(":", 2)
            if len(parts) != 3 or not parts[1] or not parts[2]:
                raise ValueError("Plugin source must use plugin:NAME:SOURCE syntax")
            for plugin in self.plugins:
                if str(getattr(plugin, "NAME", plugin.__name__)) == parts[1]:
                    return plugin, parts[2]
            raise KeyError(f"Media plugin not found: {parts[1]}")
        for plugin in self.plugins:
            matches = getattr(plugin, "matches", None)
            if callable(matches):
                try:
                    if matches(source):
                        return plugin, source
                except Exception:
                    self.log.exception("Plugin matcher failed: %s",
                                       getattr(plugin, "NAME", plugin.__name__))
        return None

    def resolve_episode(self, source: str, episode: dict[str, Any]) -> dict[str, Any]:
        selected = self._select(source)
        if selected is None:
            return episode
        plugin, _plugin_source = selected
        resolver = getattr(plugin, "resolve", None)
        if not callable(resolver):
            return episode
        resolved = resolver(dict(episode))
        if resolved is None:
            return episode
        if not isinstance(resolved, dict):
            raise TypeError("Plugin resolve must return a dictionary or None")
        return {**episode, **resolved}

    def download_episode(self, source: str, episode: dict[str, Any], base: Path,
                         progress=None, cancelled=None) -> str | None:
        selected = self._select(source)
        if selected is None:
            return None
        plugin, _plugin_source = selected
        downloader = getattr(plugin, "download", None)
        if not callable(downloader):
            return None
        result = downloader(dict(episode), base, progress, cancelled)
        if result is None:
            return None
        return str(result)
    def list_episodes(self, source: str) -> list[dict[str, Any]] | None:
        selected = self._select(source)
        if selected is None:
            return None
        plugin, plugin_source = selected
        records = plugin.list_episodes(plugin_source)
        if not isinstance(records, (list, tuple)):
            raise TypeError("Plugin list_episodes must return a list")
        source_id = f"plugin:{getattr(plugin, 'NAME', plugin.__name__)}"
        episodes = []
        for raw in records:
            if not isinstance(raw, dict):
                raise TypeError("Plugin episodes must be dictionaries")
            episodes.append(normalize_episode(raw, source_id).to_dict())
        return episodes
