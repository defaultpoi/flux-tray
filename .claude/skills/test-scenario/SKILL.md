---
name: test-scenario
description: Generate flux-tray GTK test scenarios for complex patterns (threading, GLib.idle_add, pulse animations, network probes, media downloads)
user-invocable: true
---

# test-scenario — flux-tray GTK Test Scenario Generator

Generates test boilerplate for complex flux-tray patterns: threading + GLib.idle_add, pulse animations, network probes, media downloads, feed checks, and mixin interactions.

## Usage

```bash
# Interactive (prompts for scenario type)
/test-scenario

# Direct with arguments
/test-scenario thread-idle-add --mixin FeedsMixin --method _check_feeds
/test-scenario pulse --mixin PopupMixin --interval BREAKING_PULSE_MS
/test-scenario network-probe --mixin ConnectivityMixin
/test-scenario media-download --mixin MediaMixin --driver yt-dlp
/test-scenario feed-check --mixin FeedsMixin
/test-scenario schedule-action --mixin TimerMixin
```

## Scenario Templates

### 1. Thread + GLib.idle_add Pattern (Most Common)

**When**: Network I/O in thread, UI update on main loop
**Used by**: FeedsMixin, ConnectivityMixin, LiveMixin, MediaMixin, UpdatesMixin

```python
class Test<Mixin><Scenario>(unittest.TestCase):
    """Test <Mixin>.<method> thread -> idle_add flow."""

    def setUp(self):
        self.stub = self.Stub()

    def test_<method>_threads_network_then_idle_adds_ui_update(self):
        """<method> runs network I/O in thread, then GLib.idle_add UI callback."""
        # Arrange: patch GLib.idle_add to capture callback
        captured = {}
        def capture_idle_add(fn, *args, **kwargs):
            captured['fn'] = fn
            captured['args'] = args
            captured['kwargs'] = kwargs
            return 1  # fake source ID

        with mock.patch.object(rt, 'GLib') as mock_glib:
            mock_glib.idle_add.side_effect = capture_idle_add
            mock_glib.timeout_add_seconds.return_value = 1

            # Act: call the method (starts thread)
            getattr(self.stub, '<method>')()

            # Assert: thread started, hasn't called idle_add yet
            self.assertFalse(captured)

            # Simulate thread completion by calling the internal callback
            # (tests the _on_*_result method directly)
            fake_result = <expected_result_structure>
            self.stub._on_<callback>(fake_result)

            # Assert: idle_add was called with UI update method
            mock_glib.idle_add.assert_called_once()
            called_fn = mock_glib.idle_add.call_args[0][0]
            self.assertEqual(called_fn.__name__, '_on_<callback>_ui')

    def test_<method>_idle_add_callback_updates_ui_correctly(self):
        """The idle_add callback updates UI state correctly."""
        # Arrange
        fake_result = <expected_result_structure>

        # Act: call the UI callback directly (runs on main loop in real app)
        self.stub._on_<callback>_ui(fake_result)

        # Assert: UI updated
        self.stub.refresh_list.assert_called_once()
        # or specific UI assertions
```

### 2. Pulse Animation Pattern

**When**: Periodic `GLib.timeout_add` for visual pulsing (breaking news, weather alerts)
**Used by**: PopupMixin (`_breaking_pulse_tick`), FluxTray (`_alert_pulse_tick`)

```python
class Test<Mixin>Pulse(unittest.TestCase):
    """Test pulse animation lifecycle."""

    def setUp(self):
        self.stub = self.Stub()

    def test_pulse_starts_timeout_and_toggles_visibility(self):
        """Pulse starts GLib.timeout_add and toggles label markup."""
        with mock.patch.object(rt, 'GLib') as mock_glib:
            mock_glib.timeout_add.return_value = 42  # source ID

            # Act: start pulse
            self.stub._start_<pulse_name>_pulse()

            # Assert: timeout_add called with correct interval
            mock_glib.timeout_add.assert_called_once_with(
                rt.<PULSE_INTERVAL_CONSTANT>,  # e.g., BREAKING_PULSE_MS
                self.stub._<pulse_name>_pulse_tick
            )

    def test_pulse_tick_toggles_markup_and_returns_true(self):
        """Each tick toggles markup and returns True to continue."""
        # Arrange: label with initial markup
        self.stub.<label>.get_markup.return_value = 'normal'
        self.stub.<label>.set_markup = mock.MagicMock()

        # Act: call tick
        result = self.stub._<pulse_name>_pulse_tick()

        # Assert
        self.assertTrue(result)  # continue pulse
        self.stub.<label>.set_markup.assert_called_once()
        # Verify toggled: 'normal' -> 'pulsed' or vice versa

    def test_pulse_stops_on_condition(self):
        """Pulse stops (returns False) when condition met."""
        # Arrange: condition that stops pulse
        self.stub.<stop_condition> = True

        # Act
        result = self.stub._<pulse_name>_pulse_tick()

        # Assert
        self.assertFalse(result)  # stop pulse
        # Verify source removed if tracked
```

### 3. Network Probe Pattern

**When**: Background connectivity probe with confirmation probe
**Used by**: ConnectivityMixin (`probe_connectivity`, `_confirm_probe`)

```python
class TestConnectivityProbe(unittest.TestCase):
    """Test connectivity probe thread and confirmation flow."""

    def setUp(self):
        self.stub = self.Stub()

    def test_probe_connectivity_starts_thread(self):
        """probe_connectivity starts daemon thread, returns True."""
        with mock.patch.object(rt, 'threading') as mock_threading:
            mock_thread = mock.MagicMock()
            mock_threading.Thread.return_value = mock_thread

            result = self.stub.probe_connectivity()

            # Assert
            self.assertTrue(result)
            mock_threading.Thread.assert_called_once()
            args, kwargs = mock_threading.Thread.call_args
            self.assertTrue(kwargs.get('daemon'))
            mock_thread.start.assert_called_once()

    def test_probe_connectivity_returns_false_if_already_probing(self):
        """Second probe returns False immediately."""
        self.stub._probing = True

        result = self.stub.probe_connectivity()

        self.assertFalse(result)

    def test_probe_thread_calls_idle_add_with_result(self):
        """Probe thread calls GLib.idle_add with diagnose_connectivity result."""
        captured = {}
        def capture_idle_add(fn, *args):
            captured['fn'] = fn
            captured['args'] = args
            return 1

        with mock.patch.object(rt, 'GLib') as mock_glib:
            mock_glib.idle_add.side_effect = capture_idle_add
            with mock.patch.object(rt, 'diagnose_connectivity', return_value={'online': True}):
                # Act: run thread target directly
                self.stub._probe_and_callback()

                # Assert
                mock_glib.idle_add.assert_called_once()
                self.assertEqual(captured['fn'].__name__, '_on_probe_result')
                self.assertEqual(captured['args'][0], {'online': True})

    def test_on_probe_result_updates_offline_banner(self):
        """_on_probe_result shows/hides offline banner based on result."""
        # Online
        self.stub._on_probe_result({'online': True})
        self.stub.offline_banner.hide.assert_called_once()

        # Offline
        self.stub.offline_banner.reset_mock()
        self.stub._on_probe_result({'online': False})
        self.stub.offline_banner.show.assert_called_once()
```

### 4. Media Download Pattern

**When**: Episode download with progress callbacks, driver resolve/download
**Used by**: MediaMixin (`download_episode`, `_on_media_progress`)

```python
class TestMediaDownload(unittest.TestCase):
    """Test media download flow with driver."""

    def setUp(self):
        self.stub = self.Stub()
        self.source_url = 'https://example.com/feed'
        self.episode_id = 'ep123'

    def test_download_episode_calls_driver_resolve_then_download(self):
        """download_episode calls driver.resolve then driver.download."""
        # Arrange: mock driver
        mock_driver = mock.MagicMock()
        mock_driver.resolve.return_value = {'video': {'url': 'vid.mp4'}, 'subs': []}
        mock_driver.download = mock.MagicMock()
        self.stub._get_driver = mock.MagicMock(return_value=mock_driver)

        # Act
        self.stub.download_episode(self.source_url, self.episode_id)

        # Assert
        mock_driver.resolve.assert_called_once_with(<episode_dict>)
        mock_driver.download.assert_called_once()

    def test_download_progress_idle_add_updates_ui(self):
        """Download progress calls GLib.idle_add with progress callback."""
        captured = {}
        def capture_idle_add(fn, *args):
            captured['fn'] = fn
            captured['args'] = args
            return 1

        with mock.patch.object(rt, 'GLib') as mock_glib:
            mock_glib.idle_add.side_effect = capture_idle_add

            # Act: simulate progress callback from driver
            self.stub._on_media_progress(self.source_url, self.episode_id, 50, 100)

            # Assert
            mock_glib.idle_add.assert_called_once()
            self.assertEqual(captured['fn'].__name__, '_on_media_progress_ui')
            self.assertEqual(captured['args'], (self.source_url, self.episode_id, 50, 100))

    def test_download_complete_refreshes_list(self):
        """Download completion refreshes popup list."""
        self.stub.download_episode(self.source_url, self.episode_id)
        self.stub._on_media_done(self.source_url, self.episode_id, {'video': 'path.mp4'})

        self.stub.refresh_list.assert_called_once()
```

### 5. Feed Check Pattern

**When**: Periodic feed check with merge logic, auto-show popup
**Used by**: FeedsMixin (`start_check_thread`, `_check_feeds`, `_on_feeds_fetched`)

```python
class TestFeedCheck(unittest.TestCase):
    """Test feed check thread, merge, and auto-show."""

    def setUp(self):
        self.stub = self.Stub()

    def test_start_check_thread_acquires_lock_and_starts_thread(self):
        """start_check_thread acquires _check_lock, starts daemon thread."""
        with mock.patch.object(rt, 'threading') as mock_threading:
            mock_thread = mock.MagicMock()
            mock_threading.Thread.return_value = mock_thread

            self.stub.start_check_thread(force=True)

            # Assert
            mock_threading.Thread.assert_called_once()
            mock_thread.start.assert_called_once()
            # Lock should be acquired (thread target releases it)

    def test_check_feeds_releases_lock_on_exception(self):
        """_check_feeds releases _check_lock even on exception."""
        with mock.patch.object(rt, 'merge_feed_check', side_effect=Exception('network')):
            # Should not raise, lock released in finally
            self.stub._check_feeds(force=False)

        # Lock should be released (next call would acquire)
        self.assertTrue(self.stub._check_lock.acquire(blocking=False))
        self.stub._check_lock.release()

    def test_on_feeds_fetched_refreshes_and_auto_shows(self):
        """_on_feeds_fetched calls refresh_list and auto-shows on new items."""
        # With new items
        self.stub._on_feeds_fetched(['new1', 'new2'], [])
        self.stub.refresh_list.assert_called_once()
        self.stub.show_popup.assert_called_once_with(auto=True)

        # Without new items
        self.stub.reset_mock()
        self.stub._on_feeds_fetched([], ['later1'])
        self.stub.refresh_list.assert_called_once()
        self.stub.show_popup.assert_not_called()
```

### 6. Schedule/Timer Action Pattern

**When**: Recurring schedule triggers action, timer countdown
**Used by**: TimerMixin, ScheduleMixin

```python
class TestScheduleAction(unittest.TestCase):
    """Test scheduled action execution."""

    def setUp(self):
        self.stub = self.Stub()

    def test_periodic_check_triggers_scheduled_actions(self):
        """periodic_check runs schedule.check_now and executes due actions."""
        with mock.patch.object(rt, 'schedule') as mock_schedule:
            mock_schedule.check_now.return_value = [('suspend', 'systemctl suspend')]

            self.stub.periodic_check()

            mock_schedule.check_now.assert_called_once()
            # Should execute the action
            self.stub._execute_action.assert_called_once_with('systemctl suspend')

    def test_timer_countdown_updates_badge_and_pulse(self):
        """Timer tick updates badge count and pulses icon."""
        self.stub.timer_seconds = 300

        self.stub._timer_tick()

        self.assertEqual(self.stub.timer_seconds, 299)
        self.stub.update_badge.assert_called_once()
        # Verify pulse if applicable
```

## Stub Class Template

```python
class Stub:
    """Test stub for <Mixin> with mocked GTK and dependencies."""

    def __init__(self):
        # Create mixin instance with minimal deps
        self.mixin = rt.<MixinClass>()
        # Mock all external dependencies
        self.mixin.Gtk = mock.MagicMock()
        self.mixin.GLib = mock.MagicMock()
        self.mixin.Gdk = mock.MagicMock()
        # Mock UI elements
        self.mixin.popup = mock.MagicMock()
        self.mixin.popup.window = mock.MagicMock()
        self.mixin.offline_banner = mock.MagicMock()
        self.mixin.<label> = mock.MagicMock()
        # Mock internal locks
        self.mixin._check_lock = threading.Lock()
        self.mixin._probing = False
        # Mock methods called by tested code
        self.mixin.refresh_list = mock.MagicMock()
        self.mixin.show_popup = mock.MagicMock()
        self.mixin.update_badge = mock.MagicMock()
        self.mixin._execute_action = mock.MagicMock()
        self.mixin._get_driver = mock.MagicMock()
        # State
        self.mixin.state = rt.load_state()
        self.mixin.media = rt.load_media()

    # Delegate to mixin for cleaner test code
    def __getattr__(self, name):
        return getattr(self.mixin, name)
```

## Helper: `tests/helpers.py` Utilities

```python
# Use existing helpers
from tests.helpers import TmpConfigCase  # temp config/state files

class TestWithTmpFiles(TmpConfigCase):
    """Test with isolated config and state files."""
    def test_something(self):
        self.write_config('[feeds]\nurl|name|5')
        self.write_state({'seen': {}, 'unread': []})
        # ...
```

## Running Generated Tests

```bash
# Real GTK
python -m unittest tests.test_<module>.Test<Class> -v

# Stubbed
python tests/run_stubbed.py tests.test_<module>.Test<Class> -v
```

## Arguments Reference

| Scenario | Required Args | Optional Args |
|----------|---------------|---------------|
| `thread-idle-add` | `--mixin`, `--method` | `--callback` |
| `pulse` | `--mixin`, `--interval` | `--label` |
| `network-probe` | `--mixin` | -- |
| `media-download` | `--mixin`, `--driver` | `--source`, `--episode` |
| `feed-check` | `--mixin` | -- |
| `schedule-action` | `--mixin` | `--action` |

---

*Generated test files go to `tests/test_ui_<mixin>.py` or new file per scenario.*