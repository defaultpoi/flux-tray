"""One reusable mpv instance controlled through its Unix IPC socket."""

from __future__ import annotations

import json
import socket
import subprocess
import time
from pathlib import Path
from threading import RLock


class MpvController:
    def __init__(self, socket_path: Path, executable: str = "mpv"):
        self.socket_path = Path(socket_path)
        self.executable = executable
        self.process: subprocess.Popen | None = None
        self._owned = False
        self._lock = RLock()

    def _send(self, command: list) -> None:
        payload = (json.dumps({"command": command}, ensure_ascii=False) + "\n").encode("utf-8")
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(2.0)
        try:
            client.connect(str(self.socket_path))
            client.sendall(payload)
        finally:
            client.close()

    def _start(self) -> None:
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        if self.socket_path.exists():
            try:
                self._send(["get_property", "idle-active"])
                self._owned = False
                return
            except OSError:
                try:
                    self.socket_path.unlink()
                except FileNotFoundError:
                    pass
        self.process = subprocess.Popen(
            [self.executable, "--idle=yes", "--force-window=yes",
             f"--input-ipc-server={self.socket_path}", "--no-terminal",
             "--title=Flux Tray"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        self._owned = True
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError("mpv exited while starting")
            if self.socket_path.exists():
                try:
                    self._send(["get_property", "idle-active"])
                    return
                except OSError:
                    pass
            time.sleep(0.05)
        raise TimeoutError("mpv IPC socket did not become ready")

    def load(self, url: str, title: str) -> None:
        local_file = Path(url).expanduser()
        if not url.startswith(("http://", "https://")) and not local_file.is_file():
            raise ValueError("mpv source must be an HTTP(S) URL or existing local file")
        with self._lock:
            if self.process is not None and self.process.poll() is not None:
                self.process = None
                self._owned = False
            if not self.socket_path.exists() or (self.process is not None and self.process.poll() is not None):
                self._start()
            else:
                try:
                    self._send(["get_property", "idle-active"])
                except OSError:
                    self._start()
            self._send(["loadfile", str(local_file) if local_file.is_file() else url, "replace"])
            self._send(["set_property", "force-media-title", title])

    def get_property(self, name: str):
        payload = json.dumps({"command": ["get_property", name], "request_id": 1}) + "\n"
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.settimeout(2.0)
        try:
            client.connect(str(self.socket_path))
            client.sendall(payload.encode("utf-8"))
            response = b""
            while b"\n" not in response:
                chunk = client.recv(65536)
                if not chunk:
                    break
                response += chunk
            if not response:
                return None
            result = json.loads(response.splitlines()[0])
            return result.get("data") if result.get("error") == "success" else None
        finally:
            client.close()

    def close(self) -> None:
        with self._lock:
            if self._owned and self.process is not None and self.process.poll() is None:
                try:
                    self._send(["quit"])
                    self.process.wait(timeout=3)
                except (OSError, subprocess.TimeoutExpired):
                    self.process.terminate()
                    try:
                        self.process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        self.process.kill()
                        self.process.wait()
            was_owned = self._owned
            self.process = None
            self._owned = False
            if was_owned:
                try:
                    self.socket_path.unlink()
                except FileNotFoundError:
                    pass
