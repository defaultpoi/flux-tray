# Flux Tray — Code Improvement Suggestions

*Generated from senior Python code review*

---

## Analysis

Flux Tray is a well-structured GTK-based system tray application for XFCE on Void Linux that aggregates news feeds, Twitch/YouTube live streams, weather/alerts, media (podcasts/series/movies), and package updates. The codebase shows strong engineering practices: atomic file writes, threading for network operations, comprehensive config parsing, and thorough test coverage. However, there are several areas where modern Python practices could improve maintainability, type safety, and performance.

---

## Suggestions by Priority

### 1. Add Type Hints Throughout (High Priority)

The codebase uses no type hints despite being Python 3.14+. Adding them would catch bugs early and improve IDE support.

```python
# Example: flux_tray/config.py - add type hints
from __future__ import annotations
import os
import re
import shlex
import threading
from typing import Any

from .constants import CONFIG_DIR, CONFIG_FILE, DEFAULT_HIGHLIGHT_WORDS
from .fileutil import write_atomic
from .log import _log
from .textutil import _fold_text
from .windows import parse_schedule

CHECK_INTERVAL: int = 600
PENDING_CHECK_INTERVAL_SECONDS: int = 12 * 3600
# ...

def _read_config_sections() -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {
        'feeds': [], 'mute': [], 'twitch': [], 'weather': [], 'timer': [], 
        'youtube': [], 'updates': [], 'launcher': [], 'actions': [], 'schedule': [], 
        'network': [], 'highlight': [], 'media': []
    }
    # ...
    return sections

def load_feeds() -> list[tuple[str, str | None, int]]:
    feeds: list[tuple[str, str | None, int]] = []
    # ...
    return feeds

def load_highlight_words() -> tuple[str, ...]:
    # ...
    return tuple(words) or DEFAULT_HIGHLIGHT_WORDS
```

---

### 2. Replace `types.SimpleNamespace` with Proper Classes/Protocols (High Priority)

In `mediasources.py`, built-in drivers use `types.SimpleNamespace`. This should be a `Protocol` or dataclass for type safety and clarity.

```python
# flux_tray/mediasources.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol, Callable, Any

class MediaDriver(Protocol):
    NAME: str
    ORDER: str  # 'oldest' | 'newest'
    matches: Callable[[str], bool]
    list_episodes: Callable[[str], tuple[str, list[dict[str, Any]]]]
    resolve: Callable[[dict], dict] | None
    download: Callable[[dict, str, Callable, Callable], dict] | None

@dataclass
class BuiltinDriver:
    NAME: str
    ORDER: str
    matches: Callable[[str], bool]
    list_episodes: Callable[[str], tuple[str, list[dict[str, Any]]]]
    resolve: Callable[[dict], dict] | None = None
    download: Callable[[dict, str, Callable, Callable], dict] | None = None

def _builtin_drivers() -> list[BuiltinDriver]:
    return [
        BuiltinDriver(
            NAME='archive', ORDER='oldest',
            matches=lambda source: archive_identifier(source) is not None,
            list_episodes=_list_archive_source,
        ),
        BuiltinDriver(
            NAME='yt-dlp', ORDER='newest',
            matches=lambda source: is_youtube_url(source),
            list_episodes=_list_ytdlp_source,
            download=_download_ytdlp_episode,
        ),
        BuiltinDriver(
            NAME='feed', ORDER='newest',
            matches=lambda source: urllib.parse.urlparse(source).scheme in ('http', 'https'),
            list_episodes=lambda source: list_feed(source),
        ),
    ]
```

---

### 3. Use `pathlib.Path` Instead of `os.path` (Medium Priority)

Modern Python code should use `pathlib` for path manipulation. It's more readable and less error-prone.

```python
# flux_tray/constants.py
from pathlib import Path

CONFIG_DIR = Path.home() / '.config' / 'flux-tray'
CONFIG_FILE = CONFIG_DIR / 'config.conf'
MEDIA_PLUGIN_DIR = CONFIG_DIR / 'media-plugins'

# flux_tray/state.py
from pathlib import Path

STATE_FILE = CONFIG_DIR / 'state.json'
MEDIA_FILE = CONFIG_DIR / 'media.json'

def _set_aside(path: Path, why: str) -> None:
    try:
        path.replace(path.with_suffix(path.suffix + '.corrupt'))
    except OSError as e:
        _log(f'{path.name} is {why} and could not be set aside: {e}')
        return
    _log(f'{path.name} is {why}; moved to {path.name}.corrupt and started afresh')
```

---

### 4. Extract Configuration to Dataclasses/Pydantic Models (High Priority)

The config parsing returns raw dicts/tuples. Structured config objects would prevent bugs and improve IDE support.

```python
# flux_tray/config_models.py
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
from pathlib import Path

@dataclass
class FeedConfig:
    url: str
    custom_name: Optional[str] = None
    interval_seconds: int = 600
    mute_rules: list[tuple[str, str]] = field(default_factory=list)
    readlater_rules: list[tuple[str, str]] = field(default_factory=list)

@dataclass
class TwitchChannelConfig:
    channel: str
    display_name: Optional[str] = None
    quality: Optional[str] = None
    schedule_text: Optional[str] = None

@dataclass
class MediaSettings:
    path: Path = Path('~/videos').expanduser()
    interval_seconds: int = 3600
    ahead: int = 2
    behind: Optional[int] = None
    grace_seconds: int = 86400
    sleep_seconds: int = 0
    ytdlp_args: list[str] = field(default_factory=list)
    screen_size: Optional[tuple[int, int]] = None
    omdb_key: Optional[str] = None
    tmdb_key: Optional[str] = None
    discovery_types: tuple[str, ...] = ('movies', 'series')

@dataclass
class WeatherSettings:
    lat: Optional[float] = None
    lon: Optional[float] = None
    alerts_enabled: bool = False
    country: Optional[str] = None
    region: Optional[str] = None
    interval_seconds: int = 1800
```

---

### 5. Replace Global Module-Level State with Dependency Injection (Medium Priority)

Many modules use module-level globals (`_dns_lookup`, `_online_waiting`, `_config_edit_lock`). These should be encapsulated in classes.

```python
# flux_tray/network.py - before (module globals)
_dns_lock = threading.Lock()
_dns_lookup = None

# after - encapsulate in a class
class ConnectivityChecker:
    def __init__(self):
        self._dns_lock = threading.Lock()
        self._dns_lookup: tuple[threading.Thread, list[bool]] | None = None
    
    def dns_ok(self, timeout: float = DNS_TIMEOUT_SECONDS) -> bool:
        with self._dns_lock:
            # ...
```

```python
# flux_tray/config.py - before
_config_edit_lock = threading.RLock()

# after
class ConfigWriter:
    def __init__(self):
        self._lock = threading.RLock()
    
    def edit_section(self, name: str, transform: Callable[[list[str]], list[str]]) -> None:
        with self._lock:
            # ...
```

---

### 6. Use Structured Logging Instead of `_log` (Medium Priority)

The current `_log` function prints to stderr conditionally. Use `structlog` or stdlib `logging` for structured, filterable logs.

```python
# flux_tray/log.py
import logging
import os
import sys

_log = logging.getLogger('flux-tray')
_log.setLevel(logging.DEBUG if os.environ.get('FLUX_TRAY_DEBUG') else logging.WARNING)

_handler = logging.StreamHandler(sys.stderr)
_handler.setFormatter(logging.Formatter('flux-tray: %(message)s'))
_log.addHandler(_handler)

# Usage throughout codebase:
# _log.debug('connectivity probe failed', exc_info=True)
# _log.info('media plugin loaded', name=name)
# _log.warning('schedule invalid', channel=channel, error=str(e))
```

---

### 7. Consolidate Repeated Lock Patterns (Low Priority)

The `FluxTray.__init__` creates many locks. Group related state into classes with their own locks.

```python
# flux_tray/state.py - grouped state with locks
from dataclasses import dataclass, field
import threading

@dataclass
class MediaState:
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)
    sources: dict[str, dict] = field(default_factory=dict)
    queue: list = field(default_factory=list)
    current: Optional[tuple] = None
    worker_running: bool = False
    cancel: set = field(default_factory=set)
    checking: bool = False
    pending_all: bool = False
    pending: set = field(default_factory=set)
    known_sources: set = field(default_factory=set)

@dataclass
class TimerState:
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)
    remaining_seconds: int = 0
    running: bool = False
    deadline: Optional[float] = None
    end_wall: Optional[float] = None
    missed_boot: Optional[float] = None
    # ...
```

---

### 8. Fix Duplicate `_draw_svg_path` Function (Bug Fix)

In `flux_tray/ui/icon.py`, `_draw_svg_path` is defined twice (lines 58-89 and 118-162). The second definition shadows the first.

```python
# Remove the duplicate at line 118-162, keep the one at line 58-89
# But the second one handles 'C' (cubic bezier) and 'Z' commands!
# Merge them:
def _draw_svg_path(ctx, path_data, scale_x, scale_y, offset_x=0, offset_y=0):
    import re
    tokens = re.findall(r'([MLCZ])|(-?\d+\.?\d*)', path_data)
    tokens = [t for group in tokens for t in group if t]
    # ... handle M, L, C, Z commands
```

---

### 9. Use `functools.lru_cache` for Expensive Computations (Low Priority)

Functions like `glyph_rise_units`, `weather_code_glyph`, `parse_schedule` could be cached.

```python
# flux_tray/weather.py
from functools import lru_cache

@lru_cache(maxsize=32)
def weather_code_glyph(code: int | None) -> str | None:
    # ...

@lru_cache(maxsize=128)
def glyph_rise_units(glyph: str, widget_id: int = 0) -> int:
    # ...

# flux_tray/windows.py
@lru_cache(maxsize=64)
def parse_schedule(text: str) -> list[ScheduleWindow]:
    # ...
```

---

### 10. Add `slots=True` to Dataclasses (Low Priority, Python 3.14+)

```python
@dataclass(slots=True)
class FeedConfig:
    url: str
    custom_name: Optional[str] = None
    interval_seconds: int = 600
```

---

### 11. Replace `threading.Thread` with `concurrent.futures` or `asyncio` (Medium Priority)

The codebase creates many raw threads. `ThreadPoolExecutor` or async/await would be cleaner.

```python
# flux_tray/network.py - run_when_online using ThreadPoolExecutor
from concurrent.futures import ThreadPoolExecutor

_online_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='flux-online')

def run_when_online(fn: Callable[[], None]) -> None:
    _online_waiting.append(fn)
    if not _online_poller_running:
        _online_executor.submit(_wait_for_network)

# flux_tray/app.py - use executor for background tasks
_check_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix='flux-check')

def start_check_thread(self, force=False):
    self._check_executor.submit(self.check_feeds, force)
```

---

### 12. Use `enum.StrEnum` for String Constants (Low Priority)

```python
# flux_tray/constants.py
from enum import StrEnum

class AlertColor(StrEnum):
    YELLOW = 'yellow'
    ORANGE = 'orange'
    RED = 'red'

class TimerMode(StrEnum):
    COUNTDOWN = 'countdown'
    SCHEDULE = 'schedule'
```

---

### 13. Add `__slots__` to Classes with Many Instances (Low Priority)

Classes like `PopupMixin` rows, `IconMixin` rendering could benefit from slots.

---

### 14. Fix Mutable Default Arguments (Bug Fix)

In `flux_tray/updates.py:107`, `TopgradeOutput.__init__` uses `detail_lines=3` which is fine, but check for mutable defaults elsewhere.

---

### 15. Add `typing.TYPE_CHECKING` Imports for Circular Dependencies (Medium Priority)

The codebase has circular imports (e.g., `app.py` imports from `ui.*`, which import from `app` via `FluxTray`). Use `TYPE_CHECKING`:

```python
# flux_tray/ui/popup.py
from __future__ import annotations
import typing

if typing.TYPE_CHECKING:
    from ..app import FluxTray

class PopupMixin:
    def refresh_list(self: FluxTray, keep_open=False): ...
```

---

### 16. Use `dataclass` for Episode/Item Data Structures (Medium Priority)

Instead of dicts everywhere, use dataclasses for episodes, feed items, alerts.

```python
# flux_tray/media.py
from dataclasses import dataclass, field
from typing import Optional

@dataclass(slots=True)
class Episode:
    id: str
    title: str
    date: str = ''
    kind: str = ''
    ref: str = ''
    url: Optional[str] = None
    ext: Optional[str] = None
    subs: list[dict] = field(default_factory=list)
    driver: str = ''
    season: Optional[int] = None
    episode: Optional[int] = None

@dataclass(slots=True)
class MediaEntry:
    title: str = ''
    episodes: list[Episode] = field(default_factory=list)
    known: list[str] = field(default_factory=list)
    new: list[str] = field(default_factory=list)
    watched: list[str] = field(default_factory=list)
    files: dict[str, dict] = field(default_factory=dict)
    last_watched: Optional[dict] = None
    resume: dict[str, float] = field(default_factory=dict)
    remove_at: Optional[float] = None
    baselined: bool = False
```

---

### 17. Consolidate Similar Functions (Low Priority)

`load_twitch_channels`, `load_youtube_channels`, `load_twitch_qualities`, `load_youtube_qualities`, etc. follow the same pattern. Could use a generic helper.

---

### 18. Add `py.typed` Marker and `pyproject.toml` Config for Type Checking (Low Priority)

```toml
# pyproject.toml
[tool.pyright]
pythonVersion = "3.14"
typeCheckingMode = "strict"
reportMissingTypeStubs = false
```

---

### 19. Use `contextlib.contextmanager` for Lock Acquisition (Low Priority)

```python
from contextlib import contextmanager

@contextmanager
def locked(lock: threading.Lock):
    lock.acquire()
    try:
        yield
    finally:
        lock.release()

# Usage:
with locked(self.lock):
    # critical section
```

---

### 20. Extract Weather Alert Logic into Separate Module (Medium Priority)

`weather.py` is 400+ lines mixing API calls, parsing, and UI logic. Split into:
- `weather_api.py` - Open-Meteo calls
- `meteoalarm.py` - Alert fetching/parsing
- `weather_ui.py` - Glyph/formatting helpers

---

## Tests

The test suite is good but could benefit from:
- Property-based tests for config parsing (`hypothesis`)
- Integration tests for the full check cycle
- Snapshot tests for UI rendering

---

## Notes

**Trade-offs made:**
1. Type hints and dataclasses add verbose annotations but catch entire classes of bugs
2. Encapsulation increases boilerplate but improves testability and reduces global state bugs
3. `pathlib` is slightly slower than `os.path` but the difference is negligible for config files
4. Thread pools add a dependency on `concurrent.futures` (stdlib) but simplify thread lifecycle

**Follow-ups needed:**
- Run `mypy --strict` after adding type hints
- Consider `ruff` for linting (faster than flake8)
- Evaluate if `asyncio` + `aiohttp` could replace threading for network calls
- The `GI` imports via `gi_env.py` could use a typed wrapper

**Security concerns:**
- `subprocess.run` with user-controlled input (config commands) - ensure shell=False always
- `urllib.request` with user URLs - validate schemes (already done in `links.py`)
- Config file writes - atomic writes already used, good

The codebase is well-engineered for its domain. These suggestions modernize it without changing behavior.