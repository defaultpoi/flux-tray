"""X11 display resolution detection for media format selection."""

from __future__ import annotations

import re
from typing import Callable

from flux_tray.core.process import ProcessResult, ProcessSupervisor


_CONNECTED = re.compile(r"^\S+ connected(?: (primary))?\s+(.*)$")
_MODE = re.compile(r"(?<!\d)(\d{3,5})x(\d{3,5})(?:[+-]\d+[+-]\d+)?")


class XrandrDisplay:
    def __init__(self, runner: Callable[..., ProcessResult] | None = None,
                 process: ProcessSupervisor | None = None):
        self.process = process or ProcessSupervisor()
        self.runner = runner or self.process.run

    def screen_size(self) -> tuple[int, int] | None:
        try:
            result = self.runner(["xrandr", "--current"], timeout=5)
        except Exception:
            return None
        if result.returncode != 0:
            return None
        modes = []
        for line in result.stdout.splitlines():
            connected = _CONNECTED.match(line)
            if not connected:
                continue
            mode = _MODE.search(connected.group(2))
            if mode:
                modes.append((bool(connected.group(1)),
                              int(mode.group(1)), int(mode.group(2))))
        primary = [(width, height) for is_primary, width, height in modes if is_primary]
        if primary:
            return primary[0]
        return max(((width, height) for _, width, height in modes),
                   key=lambda size: size[0] * size[1], default=None)

    def screen_height(self) -> int | None:
        size = self.screen_size()
        return size[1] if size else None
