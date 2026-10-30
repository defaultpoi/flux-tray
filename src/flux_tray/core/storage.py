"""Atomic JSON storage; one store per service-owned document."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, Callable


class JsonStore:
    def __init__(self, path: Path, default_factory: Callable[[], Any]):
        self.path = Path(path)
        self._default_factory = default_factory
        self._lock = threading.RLock()

    def load(self) -> Any:
        with self._lock:
            try:
                with self.path.open(encoding="utf-8") as stream:
                    return json.load(stream)
            except FileNotFoundError:
                return self._default_factory()
            except (json.JSONDecodeError, UnicodeDecodeError):
                damaged = self.path.with_suffix(self.path.suffix + ".corrupt")
                try:
                    os.replace(self.path, damaged)
                except OSError:
                    pass
                return self._default_factory()

    def save(self, value: Any) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(
                prefix=f".{self.path.name}.", suffix=".tmp", dir=self.path.parent
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
                    stream.write("\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.path)
                try:
                    directory_fd = os.open(self.path.parent, os.O_RDONLY)
                    try:
                        os.fsync(directory_fd)
                    finally:
                        os.close(directory_fd)
                except OSError:
                    pass
            except BaseException:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass
                raise
