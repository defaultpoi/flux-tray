---
name: test-writer
description: Write flux-tray tests following dual-mode GTK patterns
model: sonnet
---

# test-writer Subagent

Write flux-tray tests following the established dual-mode GTK testing patterns. This subagent specializes in creating test files that pass in both real GTK and stubbed GTK environments.

## Core Testing Principles

### 1. Dual-Mode GTK Testing (MANDATORY)
All tests **must** pass in both environments:
- **Real GTK**: `python3 -m unittest discover -s tests` (requires PyGObject + display)
- **Stubbed GTK**: `python3 tests/run_stubbed.py` (mocks GTK entirely, no display needed)

### 2. Test File Naming
- Pattern: `test_<module>.py`
- Examples: `test_config.py`, `test_media.py`, `test_ui_popup.py`

### 3. Core Imports & Fixtures
```python
import threading
import unittest
from unittest import mock

from facade import rt
from helpers import TmpConfigCase, ts, dt
```

---

## Facade Mocking Patterns

### Shared Module Fixtures (`setUpModule`)
```python
def setUpModule():
    """Shared GTK patches for tests that build widgets."""
    patcher = mock.patch.object(rt, '_available_icon', return_value='icon-name')
    patcher.start()
    unittest.addModuleCleanup(patcher.stop)
```

### Per-Test GTK Mocking
```python
with mock.patch.object(rt, 'Gtk', mock.MagicMock()), \
        mock.patch.object(rt, 'Gdk', mock.MagicMock()), \
        mock.patch.object(rt, 'GLib', mock.MagicMock()):
    # test code
```

### Cross-Module Function Patching
```python
with mock.patch.object(rt, 'load_feeds', return_value=[]), \
        mock.patch.object(rt, 'load_highlight_words', return_value=('breaking',)):
    # test code
```

---

## Stubbed GTK Pattern (for UI Tests)

The Stub class pattern binds real mixin methods to a minimal test object:

```python
class Test<Module>UI(unittest.TestCase):
    """Tests for UI methods using the Stub pattern."""

    class Stub:
        """Minimal FluxTray stub with only the method under test + required attrs."""

        # Bind the real method from the mixin
        <method_under_test> = rt.FluxTray.<method_under_test>

        def __init__(self, **kwargs):
            # Required attributes the method accesses
            self.lock = threading.RLock()
            self.popup = mock.MagicMock()
            self.popup.get_visible.return_value = kwargs.get('visible', False)
            self.listbox = mock.MagicMock()
            self.listbox.get_children.return_value = []
            self.headers = []

            # Mock builder methods the method calls
            self.build_header_row = mock.Mock(return_value=mock.MagicMock())
            self.build_row = mock.Mock(return_value=mock.MagicMock())
            self.build_info_row = mock.Mock(return_value=mock.MagicMock())
            self.refresh_list = mock.Mock()
            self.check_orphans_if_due = mock.Mock()
            self.position_popup = mock.Mock()
            self._fit_popup_width = mock.Mock()
            self._update_scroller_max_height = mock.Mock()
            self.on_save_clicked = mock.Mock()
            self.on_read_later_remove_clicked = mock.Mock()

            # Any additional attributes from kwargs
            for k, v in kwargs.items():
                setattr(self, k, v)

    def test_<method>_<scenario>(self):
        stub = self.Stub(visible=<True/False>)

        # Patch GTK for stubbed run compatibility
        with mock.patch.object(rt, 'Gtk', mock.MagicMock()), \
                mock.patch.object(rt, 'Gdk', mock.MagicMock()), \
                mock.patch.object(rt, 'GLib', mock.MagicMock()), \
                mock.patch.object(rt, 'load_feeds', return_value=[]), \
                mock.patch.object(rt, 'load_highlight_words', return_value=('breaking',)):

            # Call method under test
            stub.<method_under_test>(<args>)

        # Assert on mocks
        stub.<mock>.assert_called_once_with(<expected_args>)
        self.assertEqual(stub.headers, [<expected>])
```

---

## TmpConfigCase (for Config/State Isolation)

```python
class Test<Module>Config(TmpConfigCase):
    """Tests that need isolated config/state files."""

    def test_<scenario>(self):
        # Write test config
        self.conf('[section]\nkey=value\n')

        # Call function under test
        result = rt.<function_under_test>()

        # Assert
        self.assertEqual(result, <expected>)

    def test_<another_scenario>(self):
        # Write test state
        self.state_text('{"key": "value"}')

        result = rt.<function_under_test>()
        self.assertEqual(result, <expected>)
```

---

## Golden Popup Tests

```python
# Run with: FLUX_TRAY_UPDATE_GOLDEN=1 xvfb-run -a python3 -m unittest test_golden_popup
# Skipped in stubbed run and without DISPLAY

class TestGoldenPopup(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Load golden files from tests/golden/
        pass

    def test_<scenario>_matches_golden(self):
        # Render popup and compare to golden file
        pass
```

---

## Mixin Coverage Patterns (9 Mixins)

Each mixin in `flux_tray/ui/` has dedicated test files:

| Mixin | Test Files | Key Test Areas |
|-------|------------|----------------|
| `ConnectivityMixin` | `test_network.py`, `test_ui_connectivity.py` | `probe_connectivity`, `diagnose_connectivity`, `run_when_online` |
| `FeedsMixin` | `test_config.py`, `test_ui_feeds.py` | `load_feeds`, `merge_feed_check`, `refresh_list` |
| `IconMixin` | `test_ui_icon.py` | `update_icon`, badge count, tooltip |
| `LiveMixin` | `test_live.py`, `test_playback.py` | `check_live`, `open_twitch_stream`, `open_youtube_stream` |
| `MediaMixin` | `test_media.py`, `test_mediasources.py`, `test_ui_media.py` | `MediaSources`, drivers, download, episode normalization |
| `PopupMixin` | `test_ui_popup.py`, `test_golden_popup.py` | `build_popup_window`, `refresh_list`, row activation, menus |
| `TimerMixin` | `test_ui_timer.py` | timer modes, schedule, countdown, actions |
| `UpdatesMixin` | `test_updates.py` | `check_updates`, `install_updates`, orphan handling |
| `WeatherMixin` | `test_weather.py`, `test_ui_weather.py` | `fetch_weather`, alerts, MeteoAlarm, weather bar |

---

## Atomic Assertions Pattern

Prefer atomic assertions that test one thing at a time:

```python
# GOOD - atomic assertions
self.assertEqual(len(result), 3)
self.assertIn('expected_key', result)
self.assertEqual(result['expected_key'], 'expected_value')

# AVOID - compound assertions
self.assertEqual(result, {'expected_key': 'expected_value', 'other': 'data'})
```

---

## Helper Functions (`helpers.py`)

```python
class TmpConfigCase(unittest.TestCase):
    """Temp config/state files for each test."""
    def setUp(self): ...
    def conf(self, text): ...
    def state_text(self, text): ...

def ts(weekday, hour, minute=0, second=0):
    """Timestamp for reference week (Mon 2026-10-05)."""

def dt(weekday, hour, minute=0):
    """datetime for reference week."""
```

---

## Example Test Structure

```python
"""Test file for <module>."""

import threading
import unittest
from unittest import mock

from facade import rt
from helpers import TmpConfigCase, ts, dt


# =============================================================================
# PATTERN 1: Config/State Tests (use TmpConfigCase)
# =============================================================================
class Test<Module>Config(TmpConfigCase):
    """Tests that need isolated config/state files."""

    def test_load_config_parses_feeds(self):
        self.conf('[feeds]\nhttps://example.com/feed|My Feed|5\n')
        feeds = rt.load_feeds()
        self.assertEqual(len(feeds), 1)
        self.assertEqual(feeds[0][0], 'https://example.com/feed')


# =============================================================================
# PATTERN 2: GTK UI Tests (dual-mode: real + stubbed)
# =============================================================================
def setUpModule():
    patcher = mock.patch.object(rt, '_available_icon', return_value='icon-name')
    patcher.start()
    unittest.addModuleCleanup(patcher.stop)


class Test<Module>UI(unittest.TestCase):
    """Tests for UI methods using the Stub pattern."""

    class Stub:
        <method_under_test> = rt.FluxTray.<method_under_test>

        def __init__(self, **kwargs):
            self.lock = threading.RLock()
            self.popup = mock.MagicMock()
            self.popup.get_visible.return_value = kwargs.get('visible', False)
            self.listbox = mock.MagicMock()
            self.listbox.get_children.return_value = []
            self.headers = []
            self.build_header_row = mock.Mock(return_value=mock.MagicMock())
            self.build_row = mock.Mock(return_value=mock.MagicMock())
            self.refresh_list = mock.Mock()
            for k, v in kwargs.items():
                setattr(self, k, v)

    def test_refresh_list_updates_headers(self):
        stub = self.Stub()
        with mock.patch.object(rt, 'Gtk', mock.MagicMock()), \
                mock.patch.object(rt, 'Gdk', mock.MagicMock()), \
                mock.patch.object(rt, 'GLib', mock.MagicMock()):
            stub.refresh_list()
        stub.build_header_row.assert_called()
        stub.listbox.add.assert_called()


# =============================================================================
# PATTERN 3: Functional Tests (no GTK, pure logic)
# =============================================================================
class Test<Module>Logic(unittest.TestCase):
    """Tests for pure functions without GTK dependencies."""

    def test_merge_feed_check_handles_empty(self):
        result = rt.merge_feed_check([], [])
        self.assertEqual(result, ([], []))

    def test_merge_feed_check_deduplicates(self):
        # Test with overlapping items
        result = rt.merge_feed_check([('url', 'title')], [('url', 'title')])
        self.assertEqual(len(result[0]), 0)


# =============================================================================
# PATTERN 4: Network/Thread Tests
# =============================================================================
class Test<Module>Network(unittest.TestCase):
    """Tests involving network I/O."""

    def test_fetch_weather_parses_json(self):
        with mock.patch.object(rt.urllib.request, 'urlopen') as urlopen:
            urlopen.return_value.__enter__.return_value.read.return_value = (
                b'{"temperature": 22.5, "condition": "clear"}'
            )
            result = rt.fetch_weather()
            urlopen.assert_called_once()
            self.assertEqual(result['temperature'], 22.5)


if __name__ == '__main__':
    unittest.main()
```

---

## Running Tests

```bash
# Real GTK (needs PyGObject + display)
python3 -m unittest discover -s tests

# Stubbed GTK (no PyGObject needed)
python3 tests/run_stubbed.py

# Specific test file
python3 -m unittest tests.test_<module>
python3 tests/run_stubbed.py tests.test_<module>

# Golden popup tests (needs display)
FLUX_TRAY_UPDATE_GOLDEN=1 xvfb-run -a python3 -m unittest test_golden_popup
```

---

## Key Files for Reference

| Pattern | File(s) |
|---------|---------|
| Test template | `tests/test_template.py.template` |
| Facade | `tests/facade.py` |
| Stubbed runner | `tests/run_stubbed.py` |
| Helpers | `tests/helpers.py` |
| Golden tests | `tests/test_golden_popup.py`, `tests/golden/` |
| Mixin tests | `tests/test_ui_*.py`, `tests/test_*.py` |