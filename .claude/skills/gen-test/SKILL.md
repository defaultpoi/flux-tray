# gen-test — Generate flux-tray Test Files

**Purpose**: Create test files following flux-tray's established patterns.  
**Invocation**: User-only (`disable-model-invocation: true`).

---

## Test Patterns Reference

### 1. Test File Naming
- Pattern: `test_<module>.py`
- Examples: `test_config.py`, `test_media.py`, `test_ui_popup.py`

### 2. Dual-Mode GTK Testing (Real + Stubbed)
Tests **must** pass in both environments:
- **Real GTK**: `python3 -m unittest discover -s tests`
- **Stubbed GTK**: `python3 tests/run_stubbed.py`

### 3. Core Imports & Fixtures
```python
import unittest
from unittest import mock

from facade import rt
from helpers import TmpConfigCase, ts, dt
```

### 4. Facade Mocking Patterns
```python
# Patch GTK in setUpModule for shared fixtures
def setUpModule():
    patcher = mock.patch.object(rt, '_available_icon', return_value='icon-name')
    patcher.start()
    unittest.addModuleCleanup(patcher.stop)

# Patch per-test for isolated GTK mocking
with mock.patch.object(rt, 'Gtk', mock.MagicMock()), \
        mock.patch.object(rt, 'Gdk', mock.MagicMock()):
    # test code

# Patch functions across all modules
with mock.patch.object(rt, 'load_feeds', return_value=[]):
    # test code
```

### 5. Stubbed GTK Pattern (for individual tests)
```python
class MyTest(unittest.TestCase):
    class Stub:
        method_under_test = rt.FluxTray.method_under_test

        def __init__(self):
            self.popup = mock.MagicMock()
            self.lock = threading.RLock()
            # ... other attributes the method needs

    def test_something(self):
        stub = self.Stub()
        with mock.patch.object(rt, 'Gtk', mock.MagicMock()):
            stub.method_under_test(...)
        # assertions on stub.mock
```

### 6. TmpConfigCase (for config/state isolation)
```python
class TestMyConfig(TmpConfigCase):
    def test_something(self):
        self.conf('[feeds]\nhttps://example.com/feed\n')
        feeds = rt.load_feeds()
        self.assertEqual(feeds, [('https://example.com/feed', None, rt.CHECK_INTERVAL)])
```

### 7. Golden Popup Tests (`tests/golden/`)
```python
# Run with: FLUX_TRAY_UPDATE_GOLDEN=1 xvfb-run -a python3 -m unittest test_golden_popup
# Skipped in stubbed run and without DISPLAY
```

### 8. Mixin Coverage Patterns (9 mixins)
Each mixin in `flux_tray/ui/` has dedicated test files:
| Mixin | Test Files |
|-------|------------|
| ConnectivityMixin | `test_network.py`, `test_ui_connectivity.py` |
| FeedsMixin | `test_config.py`, `test_ui_feeds.py` |
| IconMixin | `test_ui_icon.py` |
| LiveMixin | `test_live.py`, `test_playback.py` |
| MediaMixin | `test_media.py`, `test_mediasources.py`, `test_ui_media.py` |
| PopupMixin | `test_ui_popup.py`, `test_golden_popup.py` |
| TimerMixin | `test_ui_timer.py` |
| UpdatesMixin | `test_updates.py` |
| WeatherMixin | `test_weather.py`, `test_ui_weather.py` |

### 9. Helper Functions (`helpers.py`)
```python
class TmpConfigCase(unittest.TestCase):
    # Temp config/state files for each test
    def setUp(self): ...
    def conf(self, text): ...
    def state_text(self, text): ...

def ts(weekday, hour, minute=0, second=0):
    # Timestamp for reference week (Mon 2026-10-05)

def dt(weekday, hour, minute=0):
    # datetime for reference week
```

### 10. Running Tests
```bash
# Real GTK (needs PyGObject + display)
python3 -m unittest discover -s tests

# Stubbed GTK (no PyGObject needed)
python3 tests/run_stubbed.py

# Specific test file
python3 -m unittest tests.test_config
python3 tests/run_stubbed.py tests.test_config

# Golden popup tests (needs display)
FLUX_TRAY_UPDATE_GOLDEN=1 xvfb-run -a python3 -m unittest test_golden_popup
```

---

## Usage

This skill provides a template. The user fills in:
1. Module name being tested
2. Test class name(s)
3. Specific test methods

The template includes:
- Proper imports
- Dual-mode GTK compatibility
- Facade mocking patterns
- TmpConfigCase usage
- Stub class pattern
- Common assertions

---

## Template Test File

See `tests/test_template.py.template` for a ready-to-use template.

Copy it to `tests/test_<module>.py` and replace the placeholders:
- `<MODULE>` → module name (e.g., `config`, `media`, `ui_popup`)
- `<TestClassName>` → descriptive class names
- `<method_under_test>` → actual method name
- `<scenario>` → test scenario description