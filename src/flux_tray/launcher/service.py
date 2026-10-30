"""Safe user-defined argv launcher; shell commands are intentionally unsupported."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass

from flux_tray.core.config import Config
from flux_tray.core.process import ProcessSupervisor


@dataclass(frozen=True, slots=True)
class LaunchCommand:
    name: str
    argv: tuple[str, ...]


class LauncherService:
    def __init__(self, config: Config, process: ProcessSupervisor):
        self.config = config
        self.process = process

    def commands(self) -> list[LaunchCommand]:
        if not self.config.parser.has_section("launcher"):
            return []
        commands = []
        for name, value in self.config.parser.items("launcher"):
            try:
                argv = json.loads(value)
            except json.JSONDecodeError:
                continue
            if isinstance(argv, list) and argv and all(isinstance(part, str) and part for part in argv):
                commands.append(LaunchCommand(name, tuple(argv)))
        return commands

    def launch(self, name: str) -> subprocess.Popen:
        for command in self.commands():
            if command.name == name:
                return self.process.spawn(command.argv, shutdown_protected=True)
        raise KeyError(name)
