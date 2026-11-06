# flux-tray Project Conventions

This skill documents the coding conventions and patterns used in the flux-tray codebase. It is for Claude's reference only (user-invocable: false).

---

## 1. Dual-Mode GTK Testing (Real + Stubbed)

Tests must pass in two environments:
- **Real GTK**: `python3 -m unittest discover -s tests` (requires PyGObject)
- **Stubbed GTK**: `python3 tests/run_stubbed.py` (mocks GTK entirely)

### Stubbed Test Runner (`tests/run_stubbed.py`)
```python
for name in ('gi', 'gi.repository', 'cairo'):
    sys.modules[name] = mock.MagicMock()
# Then discover and run tests
```

### Test Patterns
- Use `mock.patch.object(rt, 'Gtk', mock.MagicMock())` to mock GTK in individual tests
- Patch `rt.GLib.idle_add`, `rt.GLib.timeout_add_seconds` etc. for main loop callbacks
- Shared fixtures in `tests/helpers.py` (e.g., `TmpConfigCase` for temp config/state files)
- The `facade` module (`tests/facade.py`) provides a unified test namespace `rt` that patches across all modules

### Example: Stubbed Test
```python
class TestPopupRebuildRules(unittest.TestCase):
    def test_auto_show_on_a_visible_popup_only_refreshes_the_list(self):
        stub = self.Stub(visible=True)
        with mock.patch.object(rt, 'is_fullscreen_active', return_value=False):
            stub.show_popup(auto=True)
        stub.refresh_list.assert_called_once()
        stub.old_popup.destroy.assert_not_called()
```

---

## 2. Atomic Writes via `fileutil.atomic_write`

All file writes use `flux_tray.fileutil.write_atomic()` to prevent readers from seeing partial data and to avoid temp file conflicts between processes/threads.

### `flux_tray/fileutil.py`
```python
def write_atomic(path, write):
    """Calls write(f) with a temp file beside path and renames it into place."""
    tmp = f'{path}.{uuid.uuid4().hex}.tmp'
    try:
        with open(tmp, 'x', encoding='utf-8') as f:
            write(f)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
```

### Usage in `state.py`
```python
def _write_json(path, data):
    write_atomic(path, lambda f: json.dump(data, f))

def save_state(state):
    _write_json(STATE_FILE, state)

def save_media(media):
    _write_json(MEDIA_FILE, media)
```

### Usage in `config.py` (config.conf edits)
```python
write_atomic(CONFIG_FILE, lambda f: f.writelines(lines))
```

---

## 3. Facade Patching for Testability (`tests/facade.py`)

The `facade.py` creates a unified test namespace `rt` that:
- Loads all `flux_tray` modules
- Detects name clashes across modules (same name bound to different objects)
- Provides a single `__dict__` view for `mock.patch.object(rt, 'name', ...)` to work across all modules

### Key Features
- **Namespace unification**: `rt.name` reads from the defining module; setting `rt.name` rebinds in ALL modules holding that name
- **Clash detection**: Fails fast if two modules bind the same name to different objects
- **Structural names**: Submodule attributes (e.g., `flux_tray.live`) are allowed

### Usage in Tests
```python
from facade import rt

# Patch works across all modules
with mock.patch.object(rt, 'Gtk', mock.MagicMock()):
    # ...

# Or patch a function
with mock.patch.object(rt, 'load_feeds', return_value=[]):
    # ...
```

---

## 4. 9 Mixin Modules Pattern

The `FluxTray` class in `app.py` composes behavior from 9 mixin classes in `flux_tray/ui/`:

```python
class FluxTray(ConnectivityMixin, FeedsMixin, IconMixin, LiveMixin, MediaMixin, PopupMixin, TimerMixin, UpdatesMixin, WeatherMixin):
```

### The 9 Mixins (in `flux_tray/ui/`)
| Mixin | File | Responsibility |
|-------|------|----------------|
| `ConnectivityMixin` | `connectivity.py` | Network probes, offline banner |
| `FeedsMixin` | `feeds.py` | Feed fetching, parsing, unread items |
| `IconMixin` | `icon.py` | Tray icon, badge count |
| `LiveMixin` | `live.py` | Twitch/YouTube live status |
| `MediaMixin` | `media.py` | Podcast/series/movie management |
| `PopupMixin` | `popup.py` | Popup window, list, menus |
| `TimerMixin` | `timer.py` | Countdown/schedule timer |
| `UpdatesMixin` | `updates.py` | Package update checking |
| `WeatherMixin` | `weather.py` | Weather bar, MeteoAlarm alerts |

### Mixin Pattern Rules
- Each mixin defines methods and attributes used by the main class
- Mixins access `self.lock` (threading.RLock) for thread safety
- Mixins use `GLib.idle_add` / `GLib.timeout_add_seconds` for UI updates from threads
- State shared via `self.state` (from `state.json`) and `self.media` (from `media.json`)

---

## 5. State File Handling (`state.json`, `media.json`)

### `state.py` — `state.json`
- **Atomic loads/saves** via `load_state()` / `save_state()`
- **Validation on load**: Each key validated to expected type; corrupt values reset to defaults
- **Corrupt file handling**: Unreadable/malformed files moved to `.corrupt` before replacement
- **Pruning**: `seen` items older than 30 days dropped; `unread` capped at 500 items

```python
def load_state():
    state = {"seen": {}, "unread": []}
    # ... load, validate each key, set defaults for corrupt ones
    return state
```

### `state.py` — `media.json`
- Separate file because episode lists are long
- Structure: `{'sources': {url: entry}}`
- Each entry cleaned via `_clean_media_entry()` to ensure all fields have correct types
- Same atomic write + corrupt handling as `state.json`

---

## 6. Media Plugin API (`mediasources.py`)

Plugins are Python modules in `~/.config/flux-tray/media-plugins/` that implement:

```python
# Required
def list_episodes(source) -> (title, [episode, ...]): ...

# Optional
def matches(source) -> bool: ...          # which [media] lines it handles
def resolve(episode) -> {'video': {...}, 'subs': [...]}: ...
def download(episode, base, progress, cancelled) -> {'video': path, 'subs': [paths]}: ...

# Optional attributes
NAME = 'my-plugin'        # lowercase, letters/digits/-/_, default: filename
ORDER = 'oldest' | 'newest'  # episode order, default: 'newest'
```

### Driver Interface (`mediasources.py`)
```python
class Driver:
    def __init__(self, name, module):
        self.name = name
        self.module = module
        self.order = getattr(module, 'ORDER', 'newest')
        self.resolve = getattr(module, 'resolve', None)
        self.download = getattr(module, 'download', None)

    def matches(self, source):
        check = getattr(self.module, 'matches', None)
        return bool(check(source)) if check else False

    def list_episodes(self, source):
        return normalize_episodes(self.name, self.module.list_episodes(source))
```

### Built-in Drivers
- `archive` (archive.org collections/items) — ORDER='oldest'
- `yt-dlp` (YouTube channels/playlists) — ORDER='newest'
- `feed` (RSS/Atom podcasts) — ORDER='newest'

### Plugin Loading
- Plugins loaded from `MEDIA_PLUGIN_DIR` (`~/.config/flux-tray/media-plugins/`)
- Hot-reloaded on file change (`MediaSources.refresh()`)
- Plugins tried first (can override built-ins), then built-ins

---

## 7. Config File Format (`config.conf`)

INI-style with sections, pipe-separated values, and key=value settings.

### Sections
| Section | Purpose |
|---------|---------|
| `[feeds]` | RSS/Atom feeds: `url\|name\|interval\|mute_rules\|read_later_rules` |
| `[mute]` | Title phrases that auto-mark as read (one per line or `\|`-separated) |
| `[twitch]` | Twitch channels: `channel\|name\|quality\|schedule` |
| `[youtube]` | YouTube channels: same format as `[twitch]` |
| `[updates]` | Package update settings: `interval`, `installer`, `steps`, `orphans` |
| `[media]` | Media sources + settings: `path`, `interval`, `ahead`, `behind`, `grace`, `sleep`, `ytdlp`, `screen` |
| `[highlight]` | Words that pulse in popup (default: `breaking`) |
| `[network]` | `reset=command` for "Reset network" button |
| `[actions]` | Timer actions: `Label\|command` (default: Suspend, Power off) |
| `[schedule]` | Recurring actions: `on\|off \| HH:MM \| days \| action` |
| `[launcher]` | Launch commands: `Label\|command` |
| `[weather]` | `lat\|lon`, `interval`, `alerts`, `country`, `region` |
| `[timer]` | `max=minutes`, `step=seconds` |

### Example
```ini
[feeds]
https://example.com/feed.xml|My Blog|5|category=sports
https://news.com/rss||10||category=long reads

[twitch]
channel1|Display Name|720p60|mon-fri 18:00-23:00

[media]
path=~/videos
interval=60
ahead=2
https://archive.org/details/series|My Series|oldest
```

### Parsing (`config.py`)
- `_read_config_sections()` returns `{section: [lines]}`
- Settings parsed via `key=value` lines; source lines via `url\|name\|order`
- Thread-safe edits via `_edit_config_section()` with `threading.RLock` + atomic write

---

## 8. No Type Hints, Python 3.14

- **No type annotations** anywhere in the codebase
- **Python 3.14+ required** (enforced in `test_python_version.py`)
- Uses modern Python features available in 3.14:
  - `exception.add_note()` for error context
  - `math.isfinite()` for numeric validation
  - `datetime.fromisoformat()` for ISO timestamps
  - `tomllib` for `pyproject.toml` parsing

### Version Check (`flux_tray/__init__.py`)
```python
import sys
if sys.version_info < (3, 14):
    sys.exit('flux-tray needs Python 3.14 or newer')
```

---

## 9. GTK Main Loop Patterns

### Periodic Tasks via `GLib.timeout_add_seconds()`
```python
# In FluxTray.__init__ (app.py)
GLib.timeout_add_seconds(1, self.initial_check)
GLib.timeout_add_seconds(SCHEDULER_TICK_SECONDS, self.periodic_check)
GLib.timeout_add(800, self.maybe_auto_show_startup)
GLib.timeout_add_seconds(2, self.initial_weather_check)
GLib.timeout_add_seconds(load_weather_refresh_interval(), self.periodic_weather_check)
GLib.timeout_add(ALERT_PULSE_INTERVAL_MS, self._alert_pulse_tick)
```

### UI Updates from Threads via `GLib.idle_add()`
```python
# In network.py - probe runs in thread, result to main loop
GLib.idle_add(self._on_probe_result, result)

# In feeds.py - feed check in thread, UI update on main loop
GLib.idle_add(self._on_feeds_fetched, new_items, later_items)

# In media.py - download progress on main loop
GLib.idle_add(self._on_media_progress, source_url, episode_id, done, total)
```

### Pulse Animations
```python
# Breaking news pulse (popup.py)
GLib.timeout_add(BREAKING_PULSE_MS, self._breaking_pulse_tick)

# Weather alert pulse (app.py)
GLib.timeout_add(ALERT_PULSE_INTERVAL_MS, self._alert_pulse_tick)
```

### One-Shot Callbacks via `GLib.timeout_add_seconds()` / `GLib.idle_add()`
```python
# Schedule a confirmation probe
GLib.timeout_add_seconds(CONFIRM_PROBE_SECONDS, self._confirm_probe)

# Run after widget setup
GLib.idle_add(popover.destroy)
```

---

## 10. Thread Safety: Network in Threads, UI via GLib.idle_add

### Pattern
- **Network I/O** runs in `threading.Thread` (daemon=True)
- **UI updates** marshaled to main loop via `GLib.idle_add()`
- **Shared state** protected by `threading.Lock` / `threading.RLock`

### Locks in `FluxTray` (`app.py`)
```python
self.lock = threading.Lock()                    # general state
self._check_lock = threading.Lock()             # feed check cycles
self._xbps_lock = threading.Lock()              # xbps db access
self._twitch_lock = threading.Lock()            # Twitch check cycles
self._youtube_lock = threading.Lock()           # YouTube check cycles
self._media_request_lock = threading.Lock()     # media check coordination
self._media_data_lock = threading.Lock()        # self.media
self._media_queue_lock = threading.Lock()       # download queue
```

### Example: Feed Check Thread (`feeds.py`)
```python
def start_check_thread(self, force=False):
    if not self._check_lock.acquire(blocking=False):
        return  # another check in progress
    threading.Thread(target=self._check_feeds, kwargs={'force': force}, daemon=True).start()

def _check_feeds(self, force):
    try:
        # ... network I/O ...
        new_items, later_items = merge_feed_check(...)
    finally:
        self._check_lock.release()
    # UI update on main loop
    GLib.idle_add(self._on_feeds_fetched, new_items, later_items)

def _on_feeds_fetched(self, new_items, later_items):
    # Runs on GTK main loop - safe to touch UI
    self.refresh_list()
    if new_items:
        self.show_popup(auto=True)
```

### Example: Connectivity Probe (`connectivity.py`)
```python
def probe_connectivity(self):
    if self._probing:
        return False
    self._probing = True
    threading.Thread(target=self._probe_and_callback, daemon=True).start()
    return True

def _probe_and_callback(self):
    result = diagnose_connectivity()  # network I/O
    GLib.idle_add(self._on_probe_result, result)  # UI on main loop

def _on_probe_result(self, result):
    self._probing = False
    # Update offline banner, trigger refreshes, etc.
```

### Coordination: `run_when_online()` (`network.py`)
```python
_online_waiting = []      # callbacks waiting for network
_online_poller_running = False

def run_when_online(fn):
    with _online_lock:
        _online_waiting.append(fn)
        if _online_poller_running:
            return
        _online_poller_running = True
    threading.Thread(target=_wait_for_network, daemon=True).start()
```

---

## Summary: Key Files for Reference

| Pattern | File(s) |
|---------|---------|
| Atomic writes | `flux_tray/fileutil.py`, `flux_tray/state.py`, `flux_tray/config.py` |
| Facade/tests | `tests/facade.py`, `tests/run_stubbed.py`, `tests/helpers.py` |
| Mixins | `flux_tray/app.py`, `flux_tray/ui/*.py` |
| State files | `flux_tray/state.py` |
| Media plugins | `flux_tray/mediasources.py`, `flux_tray/media.py` |
| Config format | `flux_tray/config.py`, `flux_tray/constants.py` |
| Python 3.14 | `flux_tray/__init__.py`, `tests/test_python_version.py` |
| GTK main loop | `flux_tray/app.py`, `flux_tray/ui/popup.py`, `flux_tray/ui/timer.py` |
| Thread safety | `flux_tray/network.py`, `flux_tray/feeds.py`, `flux_tray/app.py` |

---

*This skill is for Claude's reference only (user-invocable: false).*