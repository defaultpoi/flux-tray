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

    def screen_height(self) -> int | None:
        try:
            result = self.runner(["xrandr", "--current"], timeout=5)
        except Exception:
            return None
        if result.returncode != 0:
            return None
        heights = []
        for line in result.stdout.splitlines():
            connected = _CONNECTED.match(line)
            if not connected:
                continue
            mode = _MODE.search(connected.group(2))
            if mode:
                heights.append((bool(connected.group(1)), int(mode.group(2))))
        primary = [height for is_primary, height in heights if is_primary]
        return primary[0] if primary else max((height for _, height in heights), default=None)
