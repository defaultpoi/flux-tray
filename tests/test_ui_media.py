import os
import shutil
import tempfile
import threading
import unittest
from unittest import mock

from facade import rt


URL = 'https://archive.org/details/show'
POD = 'https://example.com/pod.xml'


def ep(episode_id, number=None, date='', title=None):
    return {'id': episode_id, 'title': title or f'Show S01E0{number or 1} {episode_id}', 'date': date or f'2020-01-0{number or 1}',
            'season': 1 if number else None, 'episode': number}


def entry_with(*episodes, watched=(), new=(), files=None, title='Show', last=None):
    entry = rt.new_media_entry()
    entry.update(title=title, baselined=True, episodes=list(episodes), known=[e['id'] for e in episodes],
                 watched=list(watched), new=list(new), files=dict(files or {}), last_watched=last)
    return entry


class FakeDriver:
    """What the registry hands the mixin: a name, a default order, listing, and the
    optional resolve and download."""

    def __init__(self, name, order, download=None, resolve=None):
        self.name, self.order, self.download, self.resolve = name, order, download, resolve
        self.list_episodes = mock.Mock(return_value=(name, []))


class FakeRegistry:
    def __init__(self):
        self.by_source = {URL: FakeDriver('archive', 'oldest'), POD: FakeDriver('feed', 'newest')}
        self.by_episode_name = {}
        self.refreshed = 0

    def refresh(self):
        self.refreshed += 1

    def listing(self, source, result):
        driver = self.by_source[source]
        if isinstance(result, Exception):
            driver.list_episodes = mock.Mock(side_effect=result)
        else:
            driver.list_episodes = mock.Mock(return_value=result)

    def driver_for(self, source):
        if source not in self.by_source:
            raise rt.NoDriver(f'no source handler for {source}')
        return self.by_source[source], source

    def driver_of(self, episode):
        name = episode.get('driver') or ('archive' if str(episode.get('kind', '')).startswith('archive') else 'feed')
        for driver in self.by_source.values():
            if driver.name == name:
                return driver
        raise rt.NoDriver(f'the {name} source plugin is not loaded')

    def discovery_plugins(self):
        return []


class Stub:
    _effective_order = rt.FluxTray._effective_order
    _check_media_guarded = rt.FluxTray._check_media_guarded
    start_media_check = rt.FluxTray.start_media_check
    watch_media_config = rt.FluxTray.watch_media_config
    _on_media_config_event = rt.FluxTray._on_media_config_event
    _media_config_changed = rt.FluxTray._media_config_changed
    _file_size = staticmethod(rt.FluxTray._file_size)
    _check_media = rt.FluxTray._check_media
    _on_media_new = rt.FluxTray._on_media_new
    _media_file_ready = staticmethod(rt.FluxTray._media_file_ready)
    _plan_media_downloads = rt.FluxTray._plan_media_downloads
    _enqueue_media = rt.FluxTray._enqueue_media
    _media_worker = rt.FluxTray._media_worker
    _media_display_name = rt.FluxTray._media_display_name
    _download_media_episode = rt.FluxTray._download_media_episode
    _media_source_order = rt.FluxTray._media_source_order
    on_media_row_clicked = rt.FluxTray.on_media_row_clicked
    _on_media_played = rt.FluxTray._on_media_played
    mark_media_watched = rt.FluxTray.mark_media_watched
    media_source_urls = rt.FluxTray.media_source_urls
    build_media_row = rt.FluxTray.build_media_row
    _update_media_row = rt.FluxTray._update_media_row
    _refresh_media_rows = rt.FluxTray._refresh_media_rows
    _consumed_media_sources = rt.FluxTray._consumed_media_sources
    remove_consumed_media = rt.FluxTray.remove_consumed_media
    _media_menu_remove = rt.FluxTray._media_menu_remove
    _cancel_source_downloads = rt.FluxTray._cancel_source_downloads
    _drop_media_sources = rt.FluxTray._drop_media_sources
    _set_media_resume = rt.FluxTray._set_media_resume
    mark_media_unwatched = rt.FluxTray.mark_media_unwatched
    _schedule_movie_removal = rt.FluxTray._schedule_movie_removal
    _trash_source_files = rt.FluxTray._trash_source_files
    _trash_episode_files = rt.FluxTray._trash_episode_files
    remove_due_movies = rt.FluxTray.remove_due_movies
    _prune_watched_files = rt.FluxTray._prune_watched_files
    _is_discovery_url = rt.FluxTray._is_discovery_url
    get_discovery_items = rt.FluxTray.get_discovery_items
    start_discovery_fetch = rt.FluxTray.start_discovery_fetch
    _on_media_row_enter = rt.FluxTray._on_media_row_enter
    _on_media_row_leave = rt.FluxTray._on_media_row_leave

    def __init__(self):
        self.media = {'sources': {}}
        self.media_status = {}
        self.media_errors = {}
        self.media_registry = FakeRegistry()
        self._media_request_lock = threading.Lock()
        self._media_checking = False
        self._media_pending_all = False
        self._media_pending = set()
        self._media_known_sources = set()
        self._media_config_monitor = None
        self._media_config_timer = None
        self._media_data_lock = threading.Lock()
        self._media_queue_lock = threading.Lock()
        self._media_queue = []
        self._media_current = None
        self._media_worker_running = False
        self._media_cancel = set()
        self._media_playlist_episodes = {}
        self.popup = mock.MagicMock()
        self.popup.get_visible.return_value = False
        self.listbox = mock.MagicMock()
        self.note_request_failure = mock.Mock()
        self.on_new_items = mock.Mock()
        self.refresh_list = mock.Mock()
        self.lock = threading.Lock()
        self.state = {}
        self._media_header_row = None


class MediaCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.sources = [(URL, None, None)]
        self.settings = {'path': self.dir, 'interval': 3600, 'ahead': 2, 'behind': None, 'grace': 24 * 3600,
                         'sleep': 0, 'screen': None}
        self.movies = set()  # the sources marked `movie` in the config
        self.idle = []
        for name, value in (('load_media_sources', mock.Mock(side_effect=lambda: list(self.sources))),
                            ('load_media_movies', mock.Mock(side_effect=lambda: set(self.movies))),
                            ('load_media_settings', mock.Mock(side_effect=lambda: dict(self.settings))),
                            ('save_media', mock.Mock()),
                            ('load_media_cache', mock.Mock(return_value={})),
                            ('get_all_cached_items', mock.Mock(return_value=[]))):
            patcher = mock.patch.object(rt, name, value)
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(rt.GLib, 'idle_add', side_effect=lambda f, *a: self.idle.append((f, a)))
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch.object(rt.GLib, 'markup_escape_text',
                                    side_effect=lambda t: t.replace('&', '&amp;').replace('<', '&lt;'))
        patcher.start()
        self.addCleanup(patcher.stop)

    def queued(self, stub, name):
        return [a for f, a in self.idle if f == getattr(stub, name)]

    def touch(self, name):
        path = os.path.join(self.dir, name)
        with open(path, 'w') as f:
            f.write('x')
        return path


class TestMediaRowView(unittest.TestCase):
    def view(self, entry, order='oldest', downloaded=False, status=None, name='Show'):
        return rt.media_row_view(name, entry, order, downloaded, status, is_playing=False)

    def test_a_ready_episode(self):
        entry = entry_with(ep('a', 1), ep('b', 2))
        self.assertEqual(self.view(entry, downloaded=True)[:3], ('Show', 'S01E01 a', 'ready'))
        self.assertEqual(self.view(entry, downloaded=True)[4], 'ready')

    def test_the_next_episode_is_the_first_unwatched_in_order(self):
        entry = entry_with(ep('a', 1), ep('b', 2), watched=['a'])
        self.assertEqual(self.view(entry)[1], 'S01E02 b')
        newest = entry_with(ep('a', 1), ep('b', 2), watched=['b'])
        self.assertEqual(self.view(newest, order='newest')[1], 'S01E01 a')

    def test_the_title_is_cleaned_of_the_series_name_and_number(self):
        entry = entry_with(ep('x', 1, title='Show S01E01 Pilot'))
        self.assertEqual(self.view(entry)[1], 'S01E01 Pilot')
        self.assertEqual(self.view(entry, name='My Name')[1], 'S01E01 Pilot')  # the feed's own title is cut too

    def test_an_episode_without_a_number_shows_its_date(self):
        entry = entry_with(ep('p', None, date='2025-09-03', title='Pod episode 3'))
        self.assertEqual(self.view(entry)[1], '2025-09-03 Pod episode 3')

    def test_one_that_is_not_on_disk(self):
        _, _, stats, tooltip, color = self.view(entry_with(ep('a', 1)))
        self.assertEqual((stats, color), ('not downloaded', 'idle'))
        self.assertIn('Click to download', tooltip)

    def test_progress(self):
        _, _, stats, tooltip, color = self.view(entry_with(ep('a', 1)), status={'state': 'downloading', 'percent': 43})
        self.assertEqual((stats, color), ('43%', 'busy'))
        self.assertIn('Downloading', tooltip)

    def test_queued(self):
        _, _, stats, _t, color = self.view(entry_with(ep('a', 1)), status={'state': 'queued'})
        self.assertEqual((stats, color), ('queued', 'busy'))

    def test_a_failure_shows_why_in_the_tooltip(self):
        _, _, stats, tooltip, color = self.view(entry_with(ep('a', 1)), status={'state': 'failed', 'error': 'HTTP Error 503'})
        self.assertEqual((stats, color), ('failed', 'failed'))
        self.assertIn('HTTP Error 503', tooltip)

    def test_a_failure_without_a_message_is_still_explained(self):
        self.assertIn('unknown error', self.view(entry_with(ep('a', 1)), status={'state': 'failed'})[3])

    def test_new_episodes_are_counted_after_the_status(self):
        entry = entry_with(ep('a', 1), ep('b', 2), ep('c', 3), new=['b', 'c'])
        self.assertEqual(self.view(entry, downloaded=True)[2], 'ready - 2 new')
        self.assertEqual(self.view(entry, status={'state': 'downloading', 'percent': 5})[2], '5% - 2 new')

    def test_watched_new_episodes_are_not_counted(self):
        entry = entry_with(ep('a', 1), ep('b', 2), new=['b'], watched=['b'])
        self.assertEqual(self.view(entry, downloaded=True)[2], 'ready')

    def test_everything_watched(self):
        entry = entry_with(ep('a', 1), watched=['a'], last={'id': 'a', 'title': 'Pilot'})
        name, text, stats, tooltip, color = self.view(entry)
        self.assertEqual((text, stats, color), ('all watched', '', 'idle'))
        self.assertEqual(tooltip, 'Last watched: Pilot')

    def test_new_episodes_are_still_counted_when_nothing_is_left_to_watch(self):
        entry = entry_with(ep('a', 1), watched=['a'], new=['a'])
        self.assertEqual(self.view(entry)[2], '')  # watched ones are not new

    def test_a_source_with_no_episodes(self):
        self.assertEqual(self.view(entry_with())[1:3], ('no episodes yet', ''))

    def test_a_source_that_cannot_be_read_shows_why_and_offers_a_retry(self):
        name, text, stats, tooltip, color = rt.media_row_view('Show', entry_with(), 'oldest', False, None, 'yt-dlp is not installed', is_playing=False)
        self.assertEqual((text, stats, color), ('cannot be read', '', 'failed'))
        self.assertEqual(tooltip.split('\n'), ['yt-dlp is not installed', 'Click to try again'])

    def test_a_source_with_episodes_that_failed_its_last_check_keeps_its_row_and_notes_it(self):
        entry = entry_with(ep('a', 1))
        _, text, stats, tooltip, color = rt.media_row_view('Show', entry, 'oldest', True, None, 'OSError: offline', is_playing=False)
        self.assertEqual((text, stats, color), ('S01E01 a', 'ready', 'ready'))
        self.assertIn('Last check failed: OSError: offline', tooltip)

    def test_the_error_is_in_the_tooltip_when_everything_is_watched_too(self):
        entry = entry_with(ep('a', 1), watched=['a'])
        self.assertEqual(rt.media_row_view('Show', entry, 'oldest', False, None, 'x', is_playing=False)[3], 'Last check failed: x')

    def test_the_tooltip_has_the_episode_the_hint_the_count_and_the_last_watched(self):
        entry = entry_with(ep('a', 1), ep('b', 2), ep('c', 3), watched=['a'], last={'id': 'a', 'title': 'A title'})
        tooltip = self.view(entry, downloaded=True)[3]
        self.assertEqual(tooltip.split('\n'), ['S01E02 b', 'Click to play', '2 unwatched', 'Last watched: A title'])

    def test_a_last_watched_without_a_title_shows_its_id(self):
        entry = entry_with(ep('a', 1), watched=['a'], last={'id': 'a', 'title': ''})
        self.assertEqual(self.view(entry)[3], 'Last watched: a')


class TestChecking(MediaCase):
    def check(self, stub, **listings):
        """Runs a check with the listings given as {source url: result} on the fake drivers."""
        for source, result in listings.items():
            stub.media_registry.listing(source, result)
        stub._check_media()

    def test_the_first_check_sets_the_baseline_and_announces_nothing(self):
        stub = Stub()
        stub._plan_media_downloads = mock.Mock()
        stub.media_registry.listing(URL, ('Show', [ep('a', 1), ep('b', 2)]))
        stub._check_media()
        entry = stub.media['sources'][URL]
        self.assertTrue(entry['baselined'])
        self.assertEqual(entry['watched'], [])  # the archive driver's default is a series: from the start
        self.assertEqual(self.queued(stub, '_on_media_new'), [])
        self.assertEqual(len(self.queued(stub, '_refresh_media_rows')), 1)
        stub._plan_media_downloads.assert_called_once_with()
        self.save_media.assert_called_with(stub.media)
        self.assertEqual(stub.media_registry.refreshed, 1)  # plugins are looked at before every check

    def test_a_feed_is_a_podcast_and_starts_at_its_latest(self):
        self.sources = [(POD, 'Pod', None)]
        stub = Stub()
        stub._plan_media_downloads = mock.Mock()
        stub.media_registry.listing(POD, ('Pod', [ep('a', 1), ep('b', 2), ep('c', 3)]))
        stub._check_media()
        self.assertEqual(sorted(stub.media['sources'][POD]['watched']), ['a', 'b'])

    def test_the_configured_order_wins_over_the_drivers(self):
        self.sources = [(POD, 'Pod', 'oldest')]
        stub = Stub()
        stub._plan_media_downloads = mock.Mock()
        stub.media_registry.listing(POD, ('Pod', [ep('a', 1), ep('b', 2)]))
        stub._check_media()
        self.assertEqual(stub.media['sources'][POD]['watched'], [])

    def test_a_new_episode_is_announced(self):
        stub = Stub()
        stub._plan_media_downloads = mock.Mock()
        stub.media['sources'][URL] = entry_with(ep('a', 1))
        stub.media_registry.listing(URL, ('Show', [ep('a', 1), ep('b', 2)]))
        stub._check_media()
        self.assertEqual(len(self.queued(stub, '_on_media_new')), 1)
        self.assertEqual(stub.media['sources'][URL]['new'], ['b'])

    def test_a_source_that_cannot_be_read_keeps_what_is_known_and_the_others_go_on(self):
        self.sources = [(URL, None, None), (POD, None, None)]
        stub = Stub()
        stub._plan_media_downloads = mock.Mock()
        old = entry_with(ep('a', 1))
        stub.media['sources'][URL] = old
        stub.media_registry.listing(URL, OSError('offline'))
        stub.media_registry.listing(POD, ('Pod', [ep('p', 1)]))
        stub._check_media()
        stub.note_request_failure.assert_called_once_with()  # a network error may mean the connection is down
        self.assertIs(stub.media['sources'][URL], old)
        self.assertEqual(old['episodes'], [ep('a', 1)])
        self.assertIn(POD, stub.media['sources'])
        self.assertEqual(stub.media_errors, {URL: 'OSError: offline'})
        stub._plan_media_downloads.assert_called_once_with()

    def test_a_drivers_own_complaint_is_shown_as_it_is_and_is_not_a_network_failure(self):
        stub = Stub()
        stub._plan_media_downloads = mock.Mock()
        stub.media_registry.listing(URL, ValueError('yt-dlp is not installed (sudo xbps-install yt-dlp)'))
        stub._check_media()
        self.assertEqual(stub.media_errors, {URL: 'yt-dlp is not installed (sudo xbps-install yt-dlp)'})
        stub.note_request_failure.assert_not_called()

    def test_a_bug_in_a_plugin_is_shown_with_its_kind(self):
        stub = Stub()
        stub._plan_media_downloads = mock.Mock()
        stub.media_registry.listing(URL, KeyError('episodes'))
        stub._check_media()
        self.assertEqual(stub.media_errors[URL], "KeyError: 'episodes'")

    def test_a_source_nobody_handles_says_so(self):
        self.sources = [('ftp://example.com/x', None, None)]
        stub = Stub()
        stub._plan_media_downloads = mock.Mock()
        stub._check_media()
        self.assertEqual(stub.media_errors, {'ftp://example.com/x': 'no source handler for ftp://example.com/x'})
        stub.note_request_failure.assert_not_called()

    def test_a_source_that_reads_again_loses_its_error(self):
        stub = Stub()
        stub._plan_media_downloads = mock.Mock()
        stub.media_errors[URL] = 'old problem'
        stub.media_registry.listing(URL, ('Show', [ep('a', 1)]))
        stub._check_media()
        self.assertNotIn(URL, stub.media_errors)

    def test_removed_sources_are_not_read(self):
        self.sources = []
        stub = Stub()
        stub._plan_media_downloads = mock.Mock()
        stub._check_media()
        for driver in stub.media_registry.by_source.values():
            driver.list_episodes.assert_not_called()

    def test_a_full_check_is_skipped_while_another_is_running(self):
        stub = Stub()
        stub._media_checking = True
        with mock.patch.object(rt.threading, 'Thread') as thread:
            stub.start_media_check()
        thread.assert_not_called()
        self.assertFalse(stub._media_pending_all)  # skipped, not queued: the periodic tick does not pile up

    def test_a_check_runs_in_a_thread(self):
        stub = Stub()
        with mock.patch.object(rt.threading, 'Thread') as thread:
            stub.start_media_check()
        self.assertEqual(thread.call_args.kwargs['target'], stub._check_media_guarded)
        thread.return_value.start.assert_called_once_with()
        self.assertTrue(stub._media_checking)
        self.assertTrue(stub._media_pending_all)

    def test_a_check_of_given_sources_is_queued_behind_the_one_running(self):
        stub = Stub()
        stub._media_checking = True
        with mock.patch.object(rt.threading, 'Thread') as thread:
            stub.start_media_check(only=['https://new.example/a'])
            stub.start_media_check(only=['https://new.example/b'])
        thread.assert_not_called()
        self.assertEqual(stub._media_pending, {'https://new.example/a', 'https://new.example/b'})

    def test_a_check_of_given_sources_starts_when_none_is_running(self):
        stub = Stub()
        with mock.patch.object(rt.threading, 'Thread') as thread:
            stub.start_media_check(only=['https://new.example/a'])
        thread.return_value.start.assert_called_once_with()
        self.assertEqual(stub._media_pending, {'https://new.example/a'})
        self.assertFalse(stub._media_pending_all)

    def test_the_thread_runs_what_was_asked_for_and_then_stops(self):
        stub = Stub()
        stub._media_checking = True
        stub._media_pending_all = True
        stub._check_media = mock.Mock()
        stub._check_media_guarded()
        stub._check_media.assert_called_once_with(None)
        self.assertFalse(stub._media_checking)
        self.assertEqual((stub._media_pending, stub._media_pending_all), (set(), False))

    def test_a_request_that_arrives_during_a_check_is_run_right_after_it(self):
        stub = Stub()
        stub._media_checking = True
        stub._media_pending_all = True
        calls = []

        def check(only):
            calls.append(only)
            if len(calls) == 1:
                stub.start_media_check(only=['https://new.example/a'])  # added while the first check runs
        stub._check_media = check
        stub._check_media_guarded()
        self.assertEqual(calls, [None, {'https://new.example/a'}])
        self.assertFalse(stub._media_checking)

    def test_a_full_request_wins_over_queued_sources(self):
        stub = Stub()
        stub._media_checking = True
        stub._media_pending_all = True
        stub._media_pending = {'https://new.example/a'}
        stub._check_media = mock.Mock()
        stub._check_media_guarded()
        stub._check_media.assert_called_once_with(None)  # everything includes it

    def test_a_check_that_blows_up_lets_the_next_one_start(self):
        stub = Stub()
        stub._media_checking = True
        stub._media_pending_all = True
        stub._check_media = mock.Mock(side_effect=RuntimeError('boom'))
        with self.assertRaises(RuntimeError):
            stub._check_media_guarded()
        self.assertFalse(stub._media_checking)
        with mock.patch.object(rt.threading, 'Thread') as thread:
            stub.start_media_check()
        thread.return_value.start.assert_called_once_with()

    def test_only_the_asked_for_sources_are_read(self):
        self.sources = [(URL, None, None), (POD, None, None)]
        stub = Stub()
        stub._plan_media_downloads = mock.Mock()
        stub.media_registry.listing(URL, ('Show', [ep('a', 1)]))
        stub.media_registry.listing(POD, ('Pod', [ep('p', 1)]))
        stub._check_media(only={POD})
        stub.media_registry.by_source[URL].list_episodes.assert_not_called()
        self.assertEqual(list(stub.media['sources']), [POD])
        stub._plan_media_downloads.assert_called_once_with()

    def test_new_episodes_open_a_closed_popup_like_a_channel_going_live(self):
        stub = Stub()
        stub._refresh_media_rows = mock.Mock()
        self.assertFalse(stub._on_media_new())
        stub.on_new_items.assert_called_once_with()
        stub._refresh_media_rows.assert_not_called()

    def test_with_the_popup_open_the_rows_just_update(self):
        stub = Stub()
        stub.popup.get_visible.return_value = True
        stub._refresh_media_rows = mock.Mock()
        stub._on_media_new()
        stub._refresh_media_rows.assert_called_once_with()
        stub.on_new_items.assert_not_called()


class TestDescribeError(unittest.TestCase):
    def test_a_message_from_a_driver_is_kept(self):
        self.assertEqual(rt.describe_media_error(ValueError('could not read x')), 'could not read x')
        self.assertEqual(rt.describe_media_error(rt.NoDriver('no source handler for y')), 'no source handler for y')

    def test_other_errors_name_their_kind(self):
        self.assertEqual(rt.describe_media_error(OSError('boom')), 'OSError: boom')
        self.assertEqual(rt.describe_media_error(TimeoutError()), 'TimeoutError')

    def test_an_empty_value_error_still_says_something(self):
        self.assertEqual(rt.describe_media_error(ValueError()), 'ValueError')

    def test_long_messages_are_cut(self):
        self.assertEqual(len(rt.describe_media_error(ValueError('x' * 1000))), 300)


class TestConfigWatcher(MediaCase):
    def test_it_remembers_the_sources_and_watches_the_config_file(self):
        self.sources = [(URL, None, None), (POD, None, None)]
        stub = Stub()
        with mock.patch.object(rt, 'Gio') as gio:
            stub.watch_media_config()
        self.assertEqual(stub._media_known_sources, {URL, POD})
        gio.File.new_for_path.assert_called_once_with(rt.CONFIG_FILE)
        monitor = gio.File.new_for_path.return_value.monitor_file.return_value
        monitor.connect.assert_called_once_with('changed', stub._on_media_config_event)
        self.assertIs(stub._media_config_monitor, monitor)  # kept, or it would stop

    def test_without_file_monitoring_nothing_breaks(self):
        stub = Stub()
        with mock.patch.object(rt, 'Gio') as gio, mock.patch.object(rt.GLib, 'Error', Exception):
            gio.File.new_for_path.return_value.monitor_file.side_effect = Exception('no inotify')
            stub.watch_media_config()
        self.assertIsNone(stub._media_config_monitor)
        self.assertEqual(stub._media_known_sources, {URL})

    def test_a_burst_of_events_is_one_reaction(self):
        stub = Stub()
        with mock.patch.object(rt.GLib, 'timeout_add', side_effect=[11, 12, 13]) as add, \
                mock.patch.object(rt.GLib, 'source_remove') as remove:
            for _ in range(3):
                stub._on_media_config_event(None, None, None, None)
        self.assertEqual(add.call_count, 3)
        add.assert_called_with(rt.MEDIA_CONFIG_DEBOUNCE_MS, stub._media_config_changed)
        self.assertEqual([c.args[0] for c in remove.call_args_list], [11, 12])  # each cancelled the one before
        self.assertEqual(stub._media_config_timer, 13)

    def test_a_new_source_is_checked_at_once_and_only_it(self):
        self.sources = [(URL, None, None), (POD, 'Pod', None)]
        stub = Stub()
        stub._media_known_sources = {URL}
        stub.start_media_check = mock.Mock()
        stub._plan_media_downloads = mock.Mock()
        self.assertFalse(stub._media_config_changed())
        stub.start_media_check.assert_called_once_with(only=[POD])
        self.assertEqual(stub._media_known_sources, {URL, POD})
        stub._plan_media_downloads.assert_not_called()

    def test_several_new_sources_are_checked_together(self):
        self.sources = [(URL, None, None), (POD, None, None), ('yt-dlp:https://v.example/x', None, None)]
        stub = Stub()
        stub._media_known_sources = {URL}
        stub.start_media_check = mock.Mock()
        stub._media_config_changed()
        stub.start_media_check.assert_called_once_with(only=[POD, 'yt-dlp:https://v.example/x'])

    def test_a_change_that_adds_no_source_updates_what_is_shown_and_downloaded(self):
        self.sources = [(URL, 'A new name', 'newest')]
        stub = Stub()
        stub._media_known_sources = {URL}
        stub.start_media_check = mock.Mock()
        stub._plan_media_downloads = mock.Mock()
        stub._refresh_media_rows = mock.Mock()
        stub._media_config_changed()
        stub.start_media_check.assert_not_called()
        stub._plan_media_downloads.assert_called_once_with()
        stub._refresh_media_rows.assert_called_once_with()

    def test_removing_a_source_checks_nothing_and_adding_it_back_does(self):
        stub = Stub()
        stub._media_known_sources = {URL, POD}
        stub.start_media_check = mock.Mock()
        stub._plan_media_downloads = mock.Mock()
        stub._refresh_media_rows = mock.Mock()
        stub._media_config_changed()  # only URL is left
        stub.start_media_check.assert_not_called()
        self.assertEqual(stub._media_known_sources, {URL})
        self.sources = [(URL, None, None), (POD, None, None)]
        stub._media_config_changed()
        stub.start_media_check.assert_called_once_with(only=[POD])

    def test_a_config_that_could_not_be_read_for_a_moment_is_not_a_new_source_later(self):
        stub = Stub()
        stub._media_known_sources = {URL}
        stub.start_media_check = mock.Mock()
        stub._plan_media_downloads = mock.Mock()
        stub._refresh_media_rows = mock.Mock()
        self.sources = []  # half-written file
        stub._media_config_changed()
        self.sources = [(URL, None, None)]
        stub._media_config_changed()
        stub.start_media_check.assert_called_once_with(only=[URL])  # checked again, which is harmless


class TestWatchingWhileItDownloads(MediaCase):
    def stub(self, status, size=3_000_000, *episodes):
        stub = Stub()
        stub.media['sources'][URL] = entry_with(*(episodes or (ep('a', 1),)))
        stub.media_status[(URL, 'a')] = status
        stub._enqueue_media = mock.Mock()
        stub._file_size = lambda path: size
        return stub

    DOWNLOADING = {'state': 'downloading', 'percent': 30, 'part': '/v/Show/Show - S01E01 - a.ts.part', 'length': 2501}

    def test_a_row_that_is_downloading_plays_the_partial_file_measured_against_the_playlist(self):
        stub = self.stub(dict(self.DOWNLOADING))
        with mock.patch.object(rt, 'play_media_file') as play:
            stub.on_media_row_clicked(URL)
        self.assertEqual(play.call_args.args[0], '/v/Show/Show - S01E01 - a.ts.part')
        self.assertEqual(play.call_args.kwargs['total_seconds'], 2501)
        stub.popup.hide.assert_called_once_with()
        stub._enqueue_media.assert_not_called()  # the download carries on
        play.call_args.kwargs['on_finished'](95.0, 5.0)
        self.assertEqual(self.queued(stub, '_on_media_played'), [(URL, 'a', 95.0, 5.0, {}, None)])

    def test_with_too_little_downloaded_the_click_does_nothing(self):
        stub = self.stub(dict(self.DOWNLOADING), size=400_000)
        with mock.patch.object(rt, 'play_media_file') as play:
            stub.on_media_row_clicked(URL)
        play.assert_not_called()
        stub._enqueue_media.assert_not_called()

    def test_without_a_length_it_plays_but_does_not_track(self):
        stub = self.stub({'state': 'downloading', 'percent': 0, 'part': '/v/x.ts.part'})
        with mock.patch.object(rt, 'play_media_file') as play:
            stub.on_media_row_clicked(URL)
        play.assert_called_once()
        self.assertIsNone(play.call_args.kwargs['on_finished'])  # mpv's own length for a growing file would mislead
        self.assertIsNone(play.call_args.kwargs['total_seconds'])

    def test_a_download_that_cannot_be_watched_still_just_waits(self):
        stub = self.stub({'state': 'downloading', 'percent': 30})  # a plain file, or an mp4
        with mock.patch.object(rt, 'play_media_file') as play:
            stub.on_media_row_clicked(URL)
        play.assert_not_called()
        stub._enqueue_media.assert_not_called()

    def test_a_queued_one_is_not_playable(self):
        stub = self.stub({'state': 'queued'})
        with mock.patch.object(rt, 'play_media_file') as play:
            stub.on_media_row_clicked(URL)
        play.assert_not_called()

    def test_a_finished_download_plays_the_finished_file_as_before(self):
        path = self.touch('a.ts')
        stub = Stub()
        stub.media['sources'][URL] = entry_with(ep('a', 1), files={'a': {'video': path, 'subs': []}})
        with mock.patch.object(rt, 'play_media_file') as play:
            stub.on_media_row_clicked(URL)
        self.assertEqual(play.call_args.args[0], path)
        self.assertIsNone(play.call_args.kwargs['total_seconds'])
        self.assertIsNotNone(play.call_args.kwargs['on_finished'])

    def test_the_row_says_it_can_be_watched(self):
        entry = entry_with(ep('a', 1))
        view = rt.media_row_view('Show', entry, 'oldest', False, dict(self.DOWNLOADING), is_playing=False)
        self.assertEqual(view[2], '30%')
        self.assertIn('Click to watch while it downloads', view[3])
        plain = rt.media_row_view('Show', entry, 'oldest', False, {'state': 'downloading', 'percent': 30}, is_playing=False)
        self.assertNotIn('Click to watch', plain[3])  # ("unwatched" is in there, so the whole word is not the test)
        self.assertIn('Downloading', plain[3])

    def test_the_download_publishes_its_partial_file_and_the_length_for_hls_only(self):
        stub = Stub()
        stub.media['sources'][URL] = entry_with(dict(ep('a', 1), driver='archive'))
        seen = []

        def fake_download(paths, files, progress=None, cancelled=None, screen=None):
            seen.append(dict(stub.media_status[(URL, 'a')]))
            progress(10, 100)
            seen.append(dict(stub.media_status[(URL, 'a')]))
            return {'video': paths['video'], 'subs': []}
        for url, ext, expect_part in (('https://cdn.example/x/master.m3u8?t=1', '.ts', True), ('https://cdn.example/x/index.m3u8', '.mkv', True),
                                      ('https://cdn.example/x/index.m3u8', '.mp4', False), ('https://cdn.example/x/video.mp4', '.mp4', False)):
            seen.clear()
            files = {'video': {'url': url, 'ext': ext}, 'subs': []}
            stub.media_registry.by_source[URL].resolve = lambda e, f=files: f
            with mock.patch.object(rt, 'download_episode', side_effect=fake_download):
                stub._download_media_episode(URL, 'a')
            has_part = 'part' in seen[0]
            self.assertEqual(has_part, expect_part, (url, ext))
            if expect_part:
                self.assertTrue(seen[0]['part'].endswith(ext + '.part'))
                self.assertEqual(seen[1]['length'], 100)
            else:
                self.assertNotIn('length', seen[1])


class TestMeasuringTheScreen(MediaCase):
    def test_the_monitor_is_measured_at_the_start_and_again_when_monitors_change(self):
        stub = Stub()
        stub._measure_screen = rt.FluxTray._measure_screen.__get__(stub)
        with mock.patch.object(rt, 'primary_monitor_size', side_effect=[(1366, 768), (1920, 1080)]), mock.patch.object(rt, 'remember_screen_size') as remember, \
                mock.patch.object(rt.Gdk.Screen, 'get_default') as get_screen:
            stub._measure_screen()
            remember.assert_called_once_with((1366, 768))
            handler = get_screen.return_value.connect.call_args
            self.assertEqual(handler.args[0], 'monitors-changed')
            handler.args[1](get_screen.return_value)  # a monitor was plugged in
        self.assertEqual([c.args[0] for c in remember.call_args_list], [(1366, 768), (1920, 1080)])

    def test_without_a_screen_object_nothing_is_connected_and_nothing_breaks(self):
        stub = Stub()
        stub._measure_screen = rt.FluxTray._measure_screen.__get__(stub)
        with mock.patch.object(rt, 'primary_monitor_size', return_value=None), mock.patch.object(rt, 'remember_screen_size') as remember, \
                mock.patch.object(rt.Gdk.Screen, 'get_default', return_value=None):
            stub._measure_screen()
        remember.assert_called_once_with(None)


class TestPeriodicCheck(MediaCase):
    def test_it_checks_and_rearms_with_the_interval_now_in_the_config(self):
        stub = Stub()
        stub.start_media_check = mock.Mock()
        self.settings['interval'] = 1800
        with mock.patch.object(rt.GLib, 'timeout_add_seconds') as timer:
            self.assertFalse(stub_periodic(stub))
        stub.start_media_check.assert_called_once_with()
        timer.assert_called_once_with(1800, stub.periodic_media_check)

    def test_the_first_check_waits_for_the_network_without_blocking(self):
        stub = Stub()
        stub.start_media_check = mock.Mock()
        with mock.patch.object(rt, 'run_when_online') as run, mock.patch.object(rt, 'is_online') as probe:
            self.assertFalse(rt.FluxTray.initial_media_check(stub))
        run.assert_called_once_with(stub.start_media_check)
        probe.assert_not_called()


def stub_periodic(stub):
    stub.periodic_media_check = rt.FluxTray.periodic_media_check.__get__(stub)
    return stub.periodic_media_check()


class TestEffectiveOrder(MediaCase):
    def test_the_configured_order_wins(self):
        stub = Stub()
        self.assertEqual(stub._effective_order(URL, 'newest'), 'newest')
        self.assertEqual(stub._effective_order(POD, 'oldest'), 'oldest')

    def test_otherwise_the_drivers_default_applies(self):
        stub = Stub()
        self.assertEqual(stub._effective_order(URL, None), 'oldest')
        self.assertEqual(stub._effective_order(POD, None), 'newest')
        self.assertEqual(stub._effective_order(URL, 'sideways'), 'oldest')

    def test_a_source_nobody_handles_is_read_as_a_podcast(self):
        self.assertEqual(Stub()._effective_order('ftp://x', None), 'newest')

    def test_the_source_order_looks_up_the_configured_one(self):
        self.sources = [(URL, None, 'newest'), (POD, None, None)]
        stub = Stub()
        self.assertEqual(stub._media_source_order(URL), 'newest')
        self.assertEqual(stub._media_source_order(POD), 'newest')


class TestPlanning(MediaCase):
    def stub(self, entry, url=URL):
        stub = Stub()
        stub.media['sources'][url] = entry
        stub._enqueue_media = mock.Mock()
        return stub

    def test_the_next_unwatched_episodes_up_to_ahead_are_wanted(self):
        stub = self.stub(entry_with(ep('a', 1), ep('b', 2), ep('c', 3), ep('d', 4), watched=['a']))
        stub._plan_media_downloads()
        stub._enqueue_media.assert_called_once_with([(URL, 'b'), (URL, 'c')])

    def test_episodes_already_on_disk_are_not_wanted_again(self):
        path = self.touch('a.mp4')
        stub = self.stub(entry_with(ep('a', 1), ep('b', 2), ep('c', 3), files={'a': {'video': path, 'subs': []}}))
        stub._plan_media_downloads()
        stub._enqueue_media.assert_called_once_with([(URL, 'b')])  # ahead counts the one on disk

    def test_a_file_that_was_deleted_is_wanted_again(self):
        stub = self.stub(entry_with(ep('a', 1), files={'a': {'video': os.path.join(self.dir, 'gone.mp4'), 'subs': []}}))
        stub._plan_media_downloads()
        stub._enqueue_media.assert_called_once_with([(URL, 'a')])

    def test_ahead_zero_downloads_nothing(self):
        self.settings['ahead'] = 0
        stub = self.stub(entry_with(ep('a', 1)))
        stub._plan_media_downloads()
        stub._enqueue_media.assert_called_once_with([])

    def test_a_podcast_wants_its_newest_unwatched_first(self):
        self.sources = [(POD, 'Pod', None)]
        stub = self.stub(entry_with(ep('a', 1), ep('b', 2), ep('c', 3), watched=['c']), url=POD)
        stub._plan_media_downloads()
        stub._enqueue_media.assert_called_once_with([(POD, 'b'), (POD, 'a')])

    def test_sources_not_read_yet_or_no_longer_configured_are_ignored(self):
        self.sources = [(URL, None, None), (POD, None, None)]
        stub = self.stub(entry_with(ep('x', 1)), url='https://gone.example/feed')
        stub._plan_media_downloads()
        stub._enqueue_media.assert_called_once_with([])


class TestQueue(MediaCase):
    def test_items_are_queued_with_a_status_and_a_worker_starts(self):
        stub = Stub()
        with mock.patch.object(rt.threading, 'Thread') as thread:
            stub._enqueue_media([(URL, 'a'), (URL, 'b')])
        self.assertEqual(stub._media_queue, [(URL, 'a'), (URL, 'b')])
        self.assertEqual(stub.media_status[(URL, 'a')], {'state': 'queued'})
        self.assertTrue(stub._media_worker_running)
        self.assertEqual(thread.call_args.kwargs['target'], stub._media_worker)
        thread.return_value.start.assert_called_once_with()
        self.assertEqual(len(self.queued(stub, '_refresh_media_rows')), 1)

    def test_a_running_worker_is_not_started_twice(self):
        stub = Stub()
        stub._media_worker_running = True
        with mock.patch.object(rt.threading, 'Thread') as thread:
            stub._enqueue_media([(URL, 'a')])
        thread.assert_not_called()

    def test_what_is_queued_or_downloading_is_not_queued_again(self):
        stub = Stub()
        stub._media_queue = [(URL, 'a')]
        stub._media_current = (URL, 'b')
        stub._media_worker_running = True
        stub._enqueue_media([(URL, 'a'), (URL, 'b'), (URL, 'c')])
        self.assertEqual(stub._media_queue, [(URL, 'a'), (URL, 'c')])
        self.assertNotIn((URL, 'b'), stub.media_status)  # the current download keeps its own status

    def test_a_click_goes_to_the_front(self):
        stub = Stub()
        stub._media_queue = [(URL, 'a')]
        stub._media_worker_running = True
        stub._enqueue_media([(URL, 'z')], front=True)
        self.assertEqual(stub._media_queue, [(URL, 'z'), (URL, 'a')])

    def test_nothing_new_means_no_refresh_and_no_worker(self):
        stub = Stub()
        with mock.patch.object(rt.threading, 'Thread') as thread:
            stub._enqueue_media([])
        thread.assert_not_called()
        self.assertEqual(self.idle, [])

    def test_the_worker_goes_through_the_queue_and_then_stops(self):
        stub = Stub()
        stub._media_queue = [(URL, 'a'), (URL, 'b')]
        stub._media_worker_running = True
        done = []

        def download(url, episode_id):
            done.append((episode_id, stub._media_current))
            if episode_id == 'a':
                stub._media_queue.append((URL, 'late'))  # queued while working
        stub._download_media_episode = download
        stub._media_worker()
        self.assertEqual(done, [('a', (URL, 'a')), ('b', (URL, 'b')), ('late', (URL, 'late'))])
        self.assertFalse(stub._media_worker_running)
        self.assertIsNone(stub._media_current)


class TestDownloading(MediaCase):
    def stub(self, *episodes, title='Show'):
        stub = Stub()
        stub.media['sources'][URL] = entry_with(*episodes, title=title)
        return stub

    def files(self):
        return {'video': {'url': 'http://h/a.mp4', 'ext': '.mp4'}, 'subs': []}

    def test_a_finished_download_is_recorded_and_its_status_cleared(self):
        stub = self.stub(ep('a', 1))
        saved = {'video': os.path.join(self.dir, 'Show', 'a.mp4'), 'subs': []}
        seen = []

        def download(paths, files, progress=None, cancelled=None, screen=None):
            seen.append(dict(stub.media_status[(URL, 'a')]))
            progress(50, 100)
            seen.append(dict(stub.media_status[(URL, 'a')]))
            progress(100, 100)
            seen.append(dict(stub.media_status[(URL, 'a')]))
            return saved
        with mock.patch.object(rt, 'resolve_files', return_value=self.files()), \
                mock.patch.object(rt, 'download_episode', side_effect=download):
            stub._download_media_episode(URL, 'a')
        self.assertEqual([s['percent'] for s in seen], [0, 50, 100])
        self.assertEqual(stub.media['sources'][URL]['files']['a'], saved)
        self.assertNotIn((URL, 'a'), stub.media_status)
        self.save_media.assert_called_with(stub.media)
        self.assertGreaterEqual(len(self.queued(stub, '_refresh_media_rows')), 3)

    def test_progress_is_only_reported_when_the_percent_moves(self):
        stub = self.stub(ep('a', 1))

        def download(paths, files, progress=None, cancelled=None, screen=None):
            for done in range(0, 1001, 1):  # a thousand blocks of a hundred percent
                progress(done, 1000)
            return {'video': 'v', 'subs': []}
        with mock.patch.object(rt, 'resolve_files', return_value=self.files()), \
                mock.patch.object(rt, 'download_episode', side_effect=download):
            stub._download_media_episode(URL, 'a')
        self.assertLessEqual(len(self.queued(stub, '_refresh_media_rows')), 103)

    def test_an_unknown_total_does_not_divide_by_zero(self):
        stub = self.stub(ep('a', 1))

        def download(paths, files, progress=None, cancelled=None, screen=None):
            progress(5000, None)
            return {'video': 'v', 'subs': []}
        with mock.patch.object(rt, 'resolve_files', return_value=self.files()), \
                mock.patch.object(rt, 'download_episode', side_effect=download):
            stub._download_media_episode(URL, 'a')
        self.assertIn('a', stub.media['sources'][URL]['files'])

    def test_the_download_is_told_the_size_of_the_screen(self):
        stub = self.stub(ep('a', 1))
        for size in ((1366, 768), None):
            with mock.patch.object(rt, 'resolve_files', return_value=self.files()), mock.patch.object(rt, 'media_target_size', return_value=size), \
                    mock.patch.object(rt, 'download_episode', return_value={'video': 'v', 'subs': []}) as fetch:
                stub._download_media_episode(URL, 'a')
            self.assertEqual(fetch.call_args.kwargs['screen'], size)

    def test_files_go_where_the_settings_say_named_after_the_display_name(self):
        self.sources = [(URL, 'My Show', None)]
        stub = self.stub(ep('a', 1, title='Real Name S01E01 Pilot'), title='Real Name')
        with mock.patch.object(rt, 'resolve_files', return_value=self.files()), \
                mock.patch.object(rt, 'episode_paths', return_value={'video': 'v', 'subs': []}) as paths, \
                mock.patch.object(rt, 'download_episode', return_value={'video': 'v', 'subs': []}):
            stub._download_media_episode(URL, 'a')
        args, kwargs = paths.call_args
        self.assertEqual(args[:2], (self.dir, 'My Show'))
        self.assertEqual(kwargs['names'], ('Real Name',))

    def test_names_that_other_files_already_use_are_passed_on(self):
        stub = self.stub(ep('a', 1), ep('b', 2))
        stub.media['sources'][URL]['files']['a'] = {'video': '/v/a.mp4', 'subs': []}
        with mock.patch.object(rt, 'resolve_files', return_value=self.files()), \
                mock.patch.object(rt, 'episode_paths', return_value={'video': 'v', 'subs': []}) as paths, \
                mock.patch.object(rt, 'download_episode', return_value={'video': 'v', 'subs': []}):
            stub._download_media_episode(URL, 'b')
        self.assertEqual(paths.call_args.args[4], {'/v/a.mp4'})

    def test_a_deleted_episode_comes_back_under_its_own_name(self):
        stub = self.stub(ep('a', 1))
        stub.media['sources'][URL]['files']['a'] = {'video': '/v/Show/a.mp4', 'subs': []}  # recorded, but gone from the disk
        with mock.patch.object(rt, 'resolve_files', return_value=self.files()), \
                mock.patch.object(rt, 'episode_paths', return_value={'video': 'v', 'subs': []}) as paths, \
                mock.patch.object(rt, 'download_episode', return_value={'video': 'v', 'subs': []}):
            stub._download_media_episode(URL, 'a')
        self.assertEqual(paths.call_args.args[4], set())

    def driver_stub(self, download=None, resolve=None, **kwargs):
        stub = self.stub(dict(ep('a', 1, title='Show S01E01 Pilot'), driver='archive'), **kwargs)  # listed by the URL's driver
        driver = stub.media_registry.by_source[URL]
        driver.download, driver.resolve = download, resolve
        return stub, driver

    def test_a_driver_that_downloads_itself_gets_the_base_path_and_the_progress_callback(self):
        saved = self.touch('video.mkv')
        sub = self.touch('video.en.vtt')
        calls = []

        def download(episode, base, progress, cancelled):
            calls.append((episode['id'], base, cancelled()))
            progress(50, 100)
            return {'video': saved, 'subs': [sub, os.path.join(self.dir, 'missing.srt')]}
        stub, _driver = self.driver_stub(download=download)
        with mock.patch.object(rt, 'download_episode') as standard, mock.patch.object(rt, 'resolve_files') as resolve:
            stub._download_media_episode(URL, 'a')
        self.assertEqual(calls, [('a', os.path.join(self.dir, 'Show', 'Show - S01E01 - Pilot'), False)])
        standard.assert_not_called()
        resolve.assert_not_called()
        self.assertEqual(stub.media['sources'][URL]['files']['a'], {'video': saved, 'subs': [sub]})  # only files that exist
        self.assertNotIn((URL, 'a'), stub.media_status)

    def test_the_base_path_avoids_names_other_episodes_use(self):
        saved = self.touch('video.mkv')
        seen = []
        stub, _driver = self.driver_stub(download=lambda e, base, p, c: seen.append(base) or {'video': saved, 'subs': []})
        stub.media['sources'][URL]['files']['other'] = {'video': os.path.join(self.dir, 'Show', 'Show - S01E01 - Pilot.mkv'), 'subs': []}
        stub._download_media_episode(URL, 'a')
        self.assertEqual(seen, [os.path.join(self.dir, 'Show', 'Show - S01E01 - Pilot (2)')])

    def test_a_driver_that_claims_a_download_it_did_not_make_fails_the_episode(self):
        stub, _driver = self.driver_stub(download=lambda e, base, p, c: {'video': os.path.join(self.dir, 'nothing.mkv'), 'subs': []})
        stub._download_media_episode(URL, 'a')
        self.assertEqual(stub.media_status[(URL, 'a')]['state'], 'failed')
        self.assertIn('did not leave the video file', stub.media_status[(URL, 'a')]['error'])
        self.assertEqual(stub.media['sources'][URL]['files'], {})

    def test_a_driver_that_returns_nonsense_fails_the_episode(self):
        for result in (None, 'path', {}, {'video': 5}):
            stub, _driver = self.driver_stub(download=lambda e, base, p, c, r=result: r)
            stub._download_media_episode(URL, 'a')
            self.assertEqual(stub.media_status[(URL, 'a')]['state'], 'failed', result)

    def test_an_error_in_a_drivers_download_is_shown_with_its_kind(self):
        def download(episode, base, progress, cancelled):
            raise ValueError('yt-dlp: Video unavailable')
        stub, _driver = self.driver_stub(download=download)
        stub._download_media_episode(URL, 'a')
        self.assertEqual(stub.media_status[(URL, 'a')], {'state': 'failed', 'error': 'yt-dlp: Video unavailable'})

    def test_a_drivers_own_resolve_replaces_the_standard_lookup(self):
        files = {'video': {'url': 'http://h/a.mp4', 'ext': '.mp4'}, 'subs': []}
        resolved = mock.Mock(return_value=files)
        stub, _driver = self.driver_stub(resolve=resolved)
        with mock.patch.object(rt, 'resolve_files') as standard, \
                mock.patch.object(rt, 'download_episode', return_value={'video': 'v', 'subs': []}) as fetch:
            stub._download_media_episode(URL, 'a')
        resolved.assert_called_once()
        standard.assert_not_called()
        self.assertEqual(fetch.call_args.args[1], {'video': {'url': 'http://h/a.mp4', 'ext': '.mp4'}, 'subs': []})  # checked on the way

    def test_an_episode_whose_driver_is_gone_fails_with_the_reason(self):
        stub = self.stub(dict(ep('a', 1), driver='gone-plugin'))
        stub._download_media_episode(URL, 'a')
        self.assertEqual(stub.media_status[(URL, 'a')]['state'], 'failed')
        self.assertIn('gone-plugin source plugin is not loaded', stub.media_status[(URL, 'a')]['error'])

    def test_a_failure_is_shown_and_nothing_is_recorded(self):
        stub = self.stub(ep('a', 1))
        with mock.patch.object(rt, 'resolve_files', return_value=self.files()), \
                mock.patch.object(rt, 'download_episode', side_effect=OSError('connection reset')):
            stub._download_media_episode(URL, 'a')
        self.assertEqual(stub.media_status[(URL, 'a')], {'state': 'failed', 'error': 'OSError: connection reset'})
        self.assertEqual(stub.media['sources'][URL]['files'], {})
        self.save_media.assert_not_called()

    def test_a_failure_without_a_message_names_the_error(self):
        stub = self.stub(ep('a', 1))
        with mock.patch.object(rt, 'resolve_files', return_value=self.files()), \
                mock.patch.object(rt, 'download_episode', side_effect=TimeoutError()):
            stub._download_media_episode(URL, 'a')
        self.assertEqual(stub.media_status[(URL, 'a')]['error'], 'TimeoutError')

    def test_an_episode_that_cannot_be_resolved_fails_too(self):
        stub = self.stub(ep('a', 1))
        with mock.patch.object(rt, 'resolve_files', side_effect=ValueError('no media file in this item')):
            stub._download_media_episode(URL, 'a')
        self.assertEqual(stub.media_status[(URL, 'a')]['error'], 'no media file in this item')

    def test_an_episode_that_left_the_list_is_forgotten(self):
        stub = self.stub(ep('a', 1))
        stub.media_status[(URL, 'gone')] = {'state': 'queued'}
        with mock.patch.object(rt, 'resolve_files') as resolve:
            stub._download_media_episode(URL, 'gone')
            stub._download_media_episode('https://nowhere.example/', 'x')
        resolve.assert_not_called()
        self.assertNotIn((URL, 'gone'), stub.media_status)

    def test_the_display_name_is_the_configured_one_else_the_title_else_the_url(self):
        stub = Stub()
        self.sources = [(URL, 'Mine', None)]
        self.assertEqual(stub._media_display_name(URL, {'title': 'Theirs'}), 'Mine')
        self.sources = [(URL, None, None)]
        self.assertEqual(stub._media_display_name(URL, {'title': 'Theirs'}), 'Theirs')
        self.assertEqual(stub._media_display_name(URL, {'title': ''}), URL)


class TestPlaying(MediaCase):
    def stub(self, *episodes, **kwargs):
        stub = Stub()
        stub.media['sources'][URL] = entry_with(*episodes, **kwargs)
        stub._enqueue_media = mock.Mock()
        return stub

    def test_a_ready_episode_plays_with_the_popup_out_of_the_way(self):
        path = self.touch('a.mp4')
        stub = self.stub(ep('a', 1, title='Show S01E01 Pilot'), files={'a': {'video': path, 'subs': []}})
        with mock.patch.object(rt, 'play_media_file') as play:
            stub.on_media_row_clicked(URL)
        stub.popup.hide.assert_called_once_with()
        self.assertEqual(play.call_args.args, (path, 'Show \u00b7 S01E01 Pilot'))
        stub._enqueue_media.assert_not_called()

    def test_the_window_title_uses_the_configured_name(self):
        self.sources = [(URL, 'My Show', None)]
        path = self.touch('a.mp4')
        stub = self.stub(ep('a', 1, title='Show S01E01 Pilot'), files={'a': {'video': path, 'subs': []}})
        with mock.patch.object(rt, 'play_media_file') as play:
            stub.on_media_row_clicked(URL)
        self.assertEqual(play.call_args.args[1], 'My Show \u00b7 S01E01 Pilot')

    def test_it_is_the_next_unwatched_episode_that_plays(self):
        a, b = self.touch('a.mp4'), self.touch('b.mp4')
        stub = self.stub(ep('a', 1), ep('b', 2), watched=['a'],
                         files={'a': {'video': a, 'subs': []}, 'b': {'video': b, 'subs': []}})
        with mock.patch.object(rt, 'play_media_file') as play:
            stub.on_media_row_clicked(URL)
        self.assertEqual(play.call_args.args[0], b)

    def test_the_end_of_playback_comes_back_through_the_main_loop(self):
        path = self.touch('a.mp4')
        stub = self.stub(ep('a', 1), files={'a': {'video': path, 'subs': []}})
        with mock.patch.object(rt, 'play_media_file') as play:
            stub.on_media_row_clicked(URL)
        play.call_args.kwargs['on_finished'](95.0, 3.0)  # called from the watcher thread
        self.assertEqual(self.queued(stub, '_on_media_played'), [(URL, 'a', 95.0, 3.0, {}, None)])

    def test_an_episode_that_is_not_downloaded_is_queued_at_the_front_not_played(self):
        stub = self.stub(ep('a', 1))
        with mock.patch.object(rt, 'play_media_file') as play:
            stub.on_media_row_clicked(URL)
        play.assert_not_called()
        stub._enqueue_media.assert_called_once_with([(URL, 'a')], front=True)
        stub.popup.hide.assert_not_called()

    def test_a_download_that_is_already_going_is_left_alone(self):
        for state in ('queued', 'downloading'):
            stub = self.stub(ep('a', 1))
            stub.media_status[(URL, 'a')] = {'state': state}
            stub.on_media_row_clicked(URL)
            stub._enqueue_media.assert_not_called()

    def test_a_failed_download_is_retried_by_a_click(self):
        stub = self.stub(ep('a', 1))
        stub.media_status[(URL, 'a')] = {'state': 'failed', 'error': 'x'}
        stub.on_media_row_clicked(URL)
        stub._enqueue_media.assert_called_once_with([(URL, 'a')], front=True)

    def test_a_file_that_was_deleted_is_downloaded_again(self):
        stub = self.stub(ep('a', 1), files={'a': {'video': os.path.join(self.dir, 'gone.mp4'), 'subs': []}})
        with mock.patch.object(rt, 'play_media_file') as play:
            stub.on_media_row_clicked(URL)
        play.assert_not_called()
        stub._enqueue_media.assert_called_once_with([(URL, 'a')], front=True)

    def test_nothing_left_to_watch_or_an_unknown_source_does_nothing(self):
        stub = self.stub(ep('a', 1), watched=['a'])
        with mock.patch.object(rt, 'play_media_file') as play:
            stub.on_media_row_clicked(URL)
            stub.on_media_row_clicked('https://nowhere.example/')
        play.assert_not_called()
        stub._enqueue_media.assert_not_called()

    def test_a_podcast_plays_its_newest_unwatched(self):
        self.sources = [(POD, 'Pod', None)]
        a, c = self.touch('a.mp3'), self.touch('c.mp3')
        stub = Stub()
        stub.media['sources'][POD] = entry_with(ep('a', 1), ep('c', 3),
                                                files={'a': {'video': a, 'subs': []}, 'c': {'video': c, 'subs': []}})
        with mock.patch.object(rt, 'play_media_file') as play:
            stub.on_media_row_clicked(POD)
        self.assertEqual(play.call_args.args[0], c)

    def test_watched_enough_marks_the_episode(self):
        stub = Stub()
        stub.mark_media_watched = mock.Mock()
        self.assertFalse(stub._on_media_played(URL, 'a', 96.0, 2.0))
        stub.mark_media_watched.assert_called_once_with(URL, 'a')

    def test_stopping_part_way_does_not(self):
        stub = Stub()
        stub.mark_media_watched = mock.Mock()
        stub._on_media_played(URL, 'a', 30.0, 700.0)
        stub._on_media_played(URL, 'a', None, None)
        stub.mark_media_watched.assert_not_called()


class TestRemovingWatchedSources(MediaCase):
    """Taking sources whose episodes are all watched off the list (right-click on the row)."""
    FILM = 'https://archive.org/details/film'

    def setUp(self):
        super().setUp()
        self.sources = [(URL, None, None), (POD, 'The Podcast', None), (self.FILM, 'The Film', 'oldest')]
        self.config_lines = [url for url, _n, _o in self.sources]

        def remove(urls):  # what remove_media_sources does to config.conf, without touching one
            self.removed_calls.append(list(urls))
            if self.config_writable:
                self.sources = [s for s in self.sources if s[0] not in urls]
        self.removed_calls, self.config_writable = [], True
        patcher = mock.patch.object(rt, 'remove_media_sources', side_effect=remove)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.stub = Stub()
        self.stub._media_rows_removed = mock.Mock()
        self.stub.media['sources'] = {
            URL: entry_with(ep('a', 1), ep('b', 2), watched=['a', 'b'], title='Show'),   # all watched
            POD: entry_with(ep('p1', 1), ep('p2', 2), watched=['p1'], title='Pod'),      # one left
            self.FILM: entry_with(ep('f', 1), watched=['f'], title='Film'),              # all watched
        }

    def test_only_sources_with_everything_watched_are_offered_in_config_order(self):
        self.assertEqual(self.stub._consumed_media_sources(), [(URL, 'Show'), (self.FILM, 'The Film')])

    def test_a_source_never_read_or_without_episodes_is_not_consumed(self):
        self.stub.media['sources'][POD] = entry_with()  # read, but nothing in it
        del self.stub.media['sources'][self.FILM]       # configured, never read
        self.assertEqual(self.stub._consumed_media_sources(), [(URL, 'Show')])

    def test_a_source_that_is_no_longer_configured_is_not_offered(self):
        self.sources = [s for s in self.sources if s[0] != URL]
        self.assertEqual(self.stub._consumed_media_sources(), [(self.FILM, 'The Film')])

    def test_removing_takes_the_line_out_and_forgets_the_source(self):
        gone = self.stub.remove_consumed_media([URL])
        self.assertEqual(gone, [URL])
        self.assertEqual(self.removed_calls, [[URL]])
        self.assertNotIn(URL, self.stub.media['sources'])
        self.assertEqual(set(self.stub.media['sources']), {POD, self.FILM})
        self.save_media.assert_called_with(self.stub.media)
        self.stub._media_rows_removed.assert_called_once_with([URL])

    def test_removing_clears_what_was_in_memory_about_it_and_nothing_else(self):
        self.stub.media_errors = {URL: 'down', POD: 'down too'}
        self.stub.media_status = {(URL, 'a'): {'state': 'queued'}, (POD, 'p2'): {'state': 'queued'}}
        self.stub._media_queue = [(URL, 'a'), (POD, 'p2')]
        self.stub._media_known_sources = {URL, POD, self.FILM}
        self.stub.remove_consumed_media([URL])
        self.assertEqual(self.stub.media_errors, {POD: 'down too'})
        self.assertEqual(self.stub.media_status, {(POD, 'p2'): {'state': 'queued'}})
        self.assertEqual(self.stub._media_queue, [(POD, 'p2')])
        self.assertEqual(self.stub._media_known_sources, {POD, self.FILM})

    def test_several_at_once_in_one_edit_of_the_config(self):
        gone = self.stub.remove_consumed_media([URL, self.FILM])
        self.assertEqual(gone, [URL, self.FILM])
        self.assertEqual(self.removed_calls, [[URL, self.FILM]])
        self.assertEqual(set(self.stub.media['sources']), {POD})

    def test_a_source_with_something_unwatched_is_left_alone_even_if_asked(self):
        gone = self.stub.remove_consumed_media([POD, URL])
        self.assertEqual(gone, [URL])
        self.assertEqual(self.removed_calls, [[URL]])
        self.assertIn(POD, self.stub.media['sources'])

    def test_asking_for_nothing_consumed_changes_nothing(self):
        self.assertEqual(self.stub.remove_consumed_media([POD, 'https://nowhere.example/']), [])
        self.assertEqual(self.removed_calls, [])
        self.save_media.assert_not_called()
        self.stub._media_rows_removed.assert_not_called()

    def test_a_config_that_cannot_be_written_leaves_everything_as_it_was(self):
        self.config_writable = False
        self.assertEqual(self.stub.remove_consumed_media([URL]), [])
        self.assertIn(URL, self.stub.media['sources'])
        self.assertEqual(self.stub.media['sources'][URL]['watched'], ['a', 'b'])
        self.save_media.assert_not_called()
        self.stub.refresh_list.assert_not_called()

    def list_with(self, *urls, header=True, extra=0):
        """A list box of fake rows: a Media heading, a row per url, then `extra` other rows."""
        rows = []
        self.heading = rt.types.SimpleNamespace(name='heading')
        if header:
            rows.append(self.heading)
            self.stub._media_header_row = self.heading
        rows += [rt.types.SimpleNamespace(media_source=url) for url in urls]
        rows += [rt.types.SimpleNamespace(name=f'other{i}') for i in range(extra)]
        box = mock.Mock()
        box.get_children.side_effect = lambda: list(rows)
        box.remove.side_effect = rows.remove
        self.stub.listbox = box
        return rows

    def test_with_unread_items_showing_the_list_is_rebuilt(self):
        self.stub.state = {'unread': [{'id': 'x'}]}
        rows = self.list_with(URL, POD)
        rt.FluxTray._media_rows_removed(self.stub, [URL])
        self.stub.refresh_list.assert_called_once_with(keep_open=True)
        self.assertEqual(len(rows), 3)  # rebuilding is refresh_list's job

    def test_with_only_media_showing_the_rows_go_in_place_and_the_others_stay(self):
        rows = self.list_with(URL, POD, self.FILM)
        rt.FluxTray._media_rows_removed(self.stub, [URL, self.FILM])
        self.assertEqual([getattr(r, 'media_source', 'heading') for r in rows], ['heading', POD])
        self.stub.refresh_list.assert_not_called()

    def test_the_heading_goes_with_the_last_media_row_but_other_rows_stay(self):
        rows = self.list_with(URL, extra=2)
        rt.FluxTray._media_rows_removed(self.stub, [URL])
        self.assertEqual([r.name for r in rows], ['other0', 'other1'])
        self.assertIsNone(self.stub._media_header_row)
        self.stub.refresh_list.assert_not_called()

    def test_when_nothing_at_all_is_left_the_list_is_rebuilt_to_say_so(self):
        self.list_with(URL)
        rt.FluxTray._media_rows_removed(self.stub, [URL])
        self.stub.refresh_list.assert_called_once_with(keep_open=True)

    def test_without_a_popup_there_is_no_list_to_fix(self):
        self.stub.popup = None
        self.list_with(URL)
        rt.FluxTray._media_rows_removed(self.stub, [URL])
        self.stub.listbox.remove.assert_not_called()
        self.stub.refresh_list.assert_not_called()

    def test_the_menu_button_closes_the_menu_before_it_removes(self):
        order = []
        popover = mock.Mock()
        popover.popdown.side_effect = lambda: order.append('popdown')
        self.stub.remove_consumed_media = mock.Mock(side_effect=lambda urls: order.append(('remove', urls)))
        self.stub._media_menu_remove(None, popover, [URL])
        self.assertEqual(order, ['popdown', ('remove', [URL])])


class TestWatched(MediaCase):
    def stub(self, *episodes, **kwargs):
        stub = Stub()
        stub.media['sources'][URL] = entry_with(*episodes, **kwargs)
        stub._plan_media_downloads = mock.Mock()
        stub._refresh_media_rows = mock.Mock()
        return stub

    def test_marking_remembers_the_episode_and_when(self):
        stub = self.stub(ep('a', 1, title='Show S01E01 Pilot'), ep('b', 2), new=['a', 'b'])
        with mock.patch.object(rt.time_module, 'time', return_value=1234.5):
            stub.mark_media_watched(URL, 'a')
        entry = stub.media['sources'][URL]
        self.assertEqual(entry['watched'], ['a'])
        self.assertEqual(entry['last_watched'], {'id': 'a', 'title': 'Show S01E01 Pilot', 'at': 1234.5})
        self.assertEqual(entry['new'], ['b'])
        self.save_media.assert_called_with(stub.media)

    def test_it_keeps_the_next_ones_ready_and_updates_the_rows(self):
        stub = self.stub(ep('a', 1))
        stub.mark_media_watched(URL, 'a')
        stub._plan_media_downloads.assert_called_once_with()
        stub._refresh_media_rows.assert_called_once_with()

    def test_watching_twice_lists_it_once(self):
        stub = self.stub(ep('a', 1))
        stub.mark_media_watched(URL, 'a')
        stub.mark_media_watched(URL, 'a')
        self.assertEqual(stub.media['sources'][URL]['watched'], ['a'])

    def test_an_episode_that_left_the_list_is_still_remembered(self):
        stub = self.stub(ep('a', 1))
        stub.mark_media_watched(URL, 'vanished')
        self.assertEqual(stub.media['sources'][URL]['last_watched']['title'], 'vanished')

    def test_an_unknown_source_is_ignored(self):
        stub = self.stub(ep('a', 1))
        stub.mark_media_watched('https://nowhere.example/', 'a')
        stub._plan_media_downloads.assert_not_called()

    def test_marking_moves_the_next_episode_on(self):
        stub = self.stub(ep('a', 1), ep('b', 2))
        stub._plan_media_downloads = rt.FluxTray._plan_media_downloads.__get__(stub)
        stub._enqueue_media = mock.Mock()
        stub.mark_media_watched(URL, 'a')
        stub._enqueue_media.assert_called_once_with([(URL, 'b')])


class TestRows(MediaCase):
    def row(self, url=URL):
        row = mock.Mock(media_source=url)
        return row

    def stub(self, *episodes, **kwargs):
        stub = Stub()
        stub.media['sources'][URL] = entry_with(*episodes, **kwargs)
        return stub

    def test_the_sources_listed_are_the_configured_ones_that_were_read(self):
        self.sources = [(URL, None, None), (POD, None, None), ('https://c.example/x', None, None)]
        stub = Stub()
        stub.media['sources'][POD] = entry_with(ep('a', 1))
        stub.media['sources'][URL] = entry_with(ep('a', 1))
        stub.media['sources']['https://c.example/x'] = entry_with()  # read, but nothing in it yet
        stub.media['sources']['https://removed.example/'] = entry_with(ep('a', 1))
        # Dynamic sources (from discovery clicks) prepended, then config sources in config order
        self.assertEqual(stub.media_source_urls(), ['https://removed.example/', URL, POD])

    def test_a_source_that_could_not_be_read_is_listed_too(self):
        self.sources = [(URL, None, None), (POD, None, None)]
        stub = Stub()
        stub.media_errors[POD] = 'no source handler for x'
        self.assertEqual(stub.media_source_urls(), [POD])

    def test_a_row_for_a_source_that_never_read_shows_its_error(self):
        stub = Stub()
        stub.media_errors[URL] = 'yt-dlp is not installed'
        row = self.row()
        stub._update_media_row(row, {URL: ('My Show', None)})
        self.assertEqual(row.media_label.set_markup.call_args.args[0],
                         '<span foreground="#000000"><b>My Show</b> - cannot be read</span>')
        self.assertIn('#c0392b', row.media_marker.set_markup.call_args.args[0])
        self.assertIn('yt-dlp is not installed', row.set_tooltip_markup.call_args.args[0])
        self.assertNotIn(URL, stub.media['sources'])  # showing it creates no state

    def test_a_row_for_a_source_with_neither_state_nor_error_is_left_alone(self):
        stub = Stub()
        row = self.row()
        stub._update_media_row(row, {})
        row.media_label.set_markup.assert_not_called()

    def test_clicking_an_unreadable_source_checks_it_again(self):
        stub = Stub()
        stub.media_errors[URL] = 'OSError: offline'
        stub.start_media_check = mock.Mock()
        stub.on_media_row_clicked(URL)
        stub.start_media_check.assert_called_once_with()

    def test_clicking_a_source_that_just_has_nothing_to_watch_does_not_recheck(self):
        stub = Stub()
        stub.media['sources'][URL] = entry_with(ep('a', 1), watched=['a'])
        stub.media_errors[URL] = 'OSError: offline'  # but it has episodes, so no retry from the click
        stub.start_media_check = mock.Mock()
        stub.on_media_row_clicked(URL)
        stub.start_media_check.assert_not_called()

    def test_a_row_shows_the_name_the_episode_and_the_stats(self):
        path = self.touch('a.mp4')
        stub = self.stub(ep('a', 1, title='Show S01E01 Pilot'), ep('b', 2), new=['b'], files={'a': {'video': path, 'subs': []}})
        row = self.row()
        stub._update_media_row(row, {})
        row.media_label.set_markup.assert_called_with('<span foreground="#000000"><b>Show</b> - S01E01 Pilot</span>')
        row.media_stats.set_markup.assert_called_with('<span foreground="#000000">- ready - 1 new</span>')
        row.media_marker.set_markup.assert_called_with('<span foreground="#2e8b57">\u25cf</span>')
        self.assertIn('Click to play', row.set_tooltip_markup.call_args.args[0])

    def test_the_configured_name_and_order_are_used(self):
        stub = Stub()
        stub.media['sources'][POD] = entry_with(ep('a', 1, title='Old'), ep('b', 2, title='New'), title='Feed Title')
        row = self.row(POD)
        stub._update_media_row(row, {POD: ('My Pod', 'newest')})
        self.assertIn('<b>My Pod</b> - S01E02 New', row.media_label.set_markup.call_args.args[0])

    def test_the_feed_title_is_used_without_a_configured_name(self):
        stub = self.stub(ep('a', 1), title='Feed Title')
        row = self.row()
        stub._update_media_row(row, {})
        self.assertIn('<b>Feed Title</b>', row.media_label.set_markup.call_args.args[0])

    def test_status_colours(self):
        stub = self.stub(ep('a', 1))
        row = self.row()
        for status, color in (({'state': 'downloading', 'percent': 3}, '#d08000'), ({'state': 'queued'}, '#d08000'),
                              ({'state': 'failed', 'error': 'x'}, '#c0392b'), (None, '#808080')):
            stub.media_status.clear()
            if status:
                stub.media_status[(URL, 'a')] = status
            stub._update_media_row(row, {})
            self.assertIn(color, row.media_marker.set_markup.call_args.args[0])

    def test_markup_in_names_and_titles_is_escaped(self):
        stub = self.stub(ep('a', 1, title='Tom & <Jerry>'), title='A <b>')
        row = self.row()
        stub._update_media_row(row, {})
        markup = row.media_label.set_markup.call_args.args[0]
        self.assertIn('A &lt;b>', markup)
        self.assertIn('Tom &amp; &lt;Jerry>', markup)
        self.assertNotIn('<Jerry>', markup)

    def test_no_stats_means_an_empty_stats_label(self):
        stub = self.stub(ep('a', 1), watched=['a'])
        row = self.row()
        stub._update_media_row(row, {})
        row.media_stats.set_markup.assert_called_with('')

    def test_a_source_that_vanished_leaves_its_row_alone(self):
        stub = Stub()
        row = self.row()
        stub._update_media_row(row, {})
        row.media_label.set_markup.assert_not_called()

    def test_refreshing_updates_only_the_media_rows_in_place(self):
        stub = Stub()
        media_a, media_b, other = self.row(), self.row(POD), mock.Mock(spec=['set_tooltip_text'])
        stub.listbox.get_children.return_value = [media_a, other, media_b]
        stub._update_media_row = mock.Mock()
        self.sources = [(URL, 'Mine', 'oldest')]
        self.assertFalse(stub._refresh_media_rows())
        self.assertEqual([c.args[0] for c in stub._update_media_row.call_args_list], [media_a, media_b])
        self.assertEqual(stub._update_media_row.call_args.args[1], {URL: ('Mine', 'oldest')})
        stub.listbox.remove.assert_not_called()  # never rebuilt: that would collapse a media-only popup

    def test_without_a_popup_there_is_nothing_to_refresh(self):
        stub = Stub()
        stub.popup = None
        stub._update_media_row = mock.Mock()
        stub._refresh_media_rows()
        stub._update_media_row.assert_not_called()

    def test_a_row_is_clickable_and_remembers_its_source(self):
        stub = self.stub(ep('a', 1))
        stub._update_media_row = mock.Mock()
        with mock.patch.object(rt, 'Gtk', mock.MagicMock()) as gtk:
            row = stub.build_media_row(URL)
        self.assertEqual(row.media_source, URL)
        row.set_activatable.assert_called_with(True)
        row.set_selectable.assert_called_with(False)
        stub._update_media_row.assert_called_once_with(row, {URL: (None, None)})
        self.assertIs(row, gtk.ListBoxRow.return_value)


if __name__ == '__main__':
    unittest.main()


NOW = 1_793_000_000.0


class TestDurationText(unittest.TestCase):
    def test_the_largest_sensible_unit(self):
        for seconds, text in ((20, '1 min'), (45 * 60, '45 min'), (59 * 60, '59 min'), (60 * 60, '1 h'), (90 * 60, '2 h'),
                              (23 * 3600, '23 h'), (47 * 3600, '47 h'), (48 * 3600, '2 days'), (5 * 86400 + 3600, '5 days')):
            self.assertEqual(rt.duration_text(seconds), text, seconds)


class TestRowOfAMovieThatIsGoing(unittest.TestCase):
    def view(self, **fields):
        entry = entry_with(ep('f', 1), watched=['f'], title='Film')
        entry.update(fields)
        return rt.media_row_view('The Film', entry, None, False, None, now=NOW, is_playing=False)

    def test_a_watched_movie_that_is_to_be_removed_says_when_and_how_to_keep_it(self):
        _name, text, stats, tooltip, color = self.view(remove_at=NOW + 23 * 3600)
        self.assertEqual((text, stats, color), ('all watched', 'removed in 23 h', 'idle'))
        self.assertIn('Removed with its file in 23 h', tooltip)
        self.assertIn("I didn't finish it", tooltip)

    def test_a_removal_that_is_due_says_a_minute(self):
        self.assertEqual(self.view(remove_at=NOW - 500)[2], 'removed in 1 min')

    def test_without_a_removal_due_the_row_is_as_it_was(self):
        _name, text, stats, tooltip, _color = self.view()
        self.assertEqual((text, stats, tooltip), ('all watched', '', ''))

    def test_a_removal_is_not_mentioned_while_something_is_unwatched(self):
        entry = entry_with(ep('a', 1), ep('b', 2), watched=['a'])
        entry['remove_at'] = NOW + 3600
        _name, _text, stats, tooltip, _color = rt.media_row_view('Show', entry, 'oldest', True, None, now=NOW, is_playing=False)
        self.assertNotIn('removed in', stats + tooltip)


class TestPlayingFromWhereItStopped(TestWatchingWhileItDownloads):
    """Clicking a row plays on from where an unfinished episode stopped, and hands over the
    sleep timer; the end of playback is judged by what was played, not skipped."""

    def clicked(self, resume=None, sleep=0):
        stub = self.stub(None, 3_000_000)
        stub.media['sources'][URL]['files']['a'] = {'video': self.touch('a.mkv'), 'subs': []}
        stub.media['sources'][URL]['resume'] = {'a': resume} if resume else {}
        self.settings['sleep'] = sleep
        with mock.patch.object(rt, 'play_media_file') as play:
            stub.on_media_row_clicked(URL)
        return stub, play

    def test_an_episode_that_stopped_part_way_starts_there(self):
        _stub, play = self.clicked(resume=754.0)
        self.assertEqual(play.call_args.kwargs['start'], 754.0)

    def test_one_that_never_stopped_part_way_starts_where_it_always_did(self):
        _stub, play = self.clicked()
        self.assertIsNone(play.call_args.kwargs['start'])

    def test_the_sleep_timer_setting_goes_to_the_player(self):
        self.assertEqual(self.clicked(sleep=1800)[1].call_args.kwargs['sleep_seconds'], 1800)
        self.assertEqual(self.clicked(sleep=0)[1].call_args.kwargs['sleep_seconds'], 0)

    def test_where_it_stopped_reaches_the_end_of_playback_with_where_it_started(self):
        stub, play = self.clicked(resume=600.0)
        play.call_args.kwargs['on_stopped']({'position': 700.0, 'played': 95.0, 'duration': 1320.0})
        play.call_args.kwargs['on_finished'](53.0, 620.0)
        self.assertEqual(self.queued(stub, '_on_media_played'),
                         [(URL, 'a', 53.0, 620.0, {'position': 700.0, 'played': 95.0, 'duration': 1320.0}, 600.0)])


class TestWhatPlaybackLeavesBehind(MediaCase):
    def stub(self, url=URL, **fields):
        stub = Stub()
        stub.media['sources'][url] = entry_with(ep('a', 1), ep('b', 2), **fields)
        stub._plan_media_downloads = mock.Mock()
        stub._refresh_media_rows = mock.Mock()
        stub._schedule_movie_removal = mock.Mock()
        return stub

    def test_watched_through_is_marked_and_forgets_where_it_stopped(self):
        stub = self.stub()
        stub.media['sources'][URL]['resume'] = {'a': 600.0, 'b': 30.0}
        stub._on_media_played(URL, 'a', 99.0, 4.0, {'position': 1316.0, 'played': 1300.0, 'duration': 1320.0}, None)
        entry = stub.media['sources'][URL]
        self.assertEqual((entry['watched'], entry['resume']), (['a'], {'b': 30.0}))
        stub._schedule_movie_removal.assert_not_called()

    def test_stopping_part_way_remembers_the_place_a_few_seconds_back(self):
        stub = self.stub()
        stub._on_media_played(URL, 'a', 41.0, 780.0, {'position': 540.0, 'played': 540.0, 'duration': 1320.0}, None)
        entry = stub.media['sources'][URL]
        self.assertEqual((entry['watched'], entry['resume']), ([], {'a': 540.0 - rt.RESUME_REWIND_SECONDS}))
        self.save_media.assert_called_with(stub.media)

    def test_seeking_to_the_end_is_not_watching(self):
        stub = self.stub()
        stub._on_media_played(URL, 'a', 99.0, 20.0, {'position': 1500.0, 'played': 120.0, 'duration': 7200.0}, None)
        entry = stub.media['sources'][URL]
        self.assertEqual(entry['watched'], [])
        self.assertEqual(entry['resume'], {'a': 1495.0})

    def test_the_part_before_a_resume_counts_as_seen_when_the_rest_is_watched(self):
        stub = self.stub()
        stub._on_media_played(URL, 'a', 99.0, 10.0, {'position': 7190.0, 'played': 1100.0, 'duration': 7200.0}, 6000.0)
        self.assertEqual(stub.media['sources'][URL]['watched'], ['a'])

    def test_stopping_before_it_got_anywhere_forgets_an_old_place(self):
        stub = self.stub()
        stub.media['sources'][URL]['resume'] = {'a': 600.0}
        stub._on_media_played(URL, 'a', 1.0, 1300.0, {'position': 8.0, 'played': 8.0, 'duration': 1320.0}, None)
        self.assertEqual(stub.media['sources'][URL]['resume'], {})

    def test_playback_that_never_loaded_leaves_the_old_place_alone(self):
        stub = self.stub()
        stub.media['sources'][URL]['resume'] = {'a': 600.0}
        stub._on_media_played(URL, 'a', None, None, {'position': None, 'played': None, 'duration': None}, 600.0)
        self.assertEqual(stub.media['sources'][URL]['resume'], {'a': 600.0})
        self.save_media.assert_not_called()

    def test_an_unchanged_place_is_not_saved_again(self):
        stub = self.stub()
        stub.media['sources'][URL]['resume'] = {'a': 535.0}
        stub._on_media_played(URL, 'a', 41.0, 780.0, {'position': 540.0, 'played': 10.0, 'duration': 1320.0}, 535.0)
        self.save_media.assert_not_called()

    def test_without_the_details_the_furthest_point_alone_decides_as_before(self):
        stub = self.stub()
        stub._on_media_played(URL, 'a', 95.0, 30.0)
        self.assertEqual(stub.media['sources'][URL]['watched'], ['a'])

    def test_a_movie_watched_through_is_set_to_be_removed(self):
        self.movies = {URL}
        stub = self.stub()
        stub._on_media_played(URL, 'a', 99.0, 4.0, {'position': 1316.0, 'played': 1300.0, 'duration': 1320.0}, None)
        stub._schedule_movie_removal.assert_called_once_with(URL)

    def test_a_movie_that_was_not_watched_through_is_not(self):
        self.movies = {URL}
        stub = self.stub()
        stub._on_media_played(URL, 'a', 40.0, 800.0, {'position': 530.0, 'played': 530.0, 'duration': 1320.0}, None)
        stub._schedule_movie_removal.assert_not_called()


class TestPuttingAnEpisodeBack(MediaCase):
    def stub(self, **fields):
        stub = Stub()
        stub.media['sources'][URL] = entry_with(ep('a', 1), ep('b', 2), watched=['a', 'b'],
                                                last={'id': 'b', 'title': 'Show S01E02 b', 'at': 5.0}, **fields)
        stub._plan_media_downloads = mock.Mock()
        stub._refresh_media_rows = mock.Mock()
        return stub

    def test_the_episode_is_unwatched_and_next_in_line_again(self):
        stub = self.stub()
        self.assertTrue(stub.mark_media_unwatched(URL, 'b'))
        entry = stub.media['sources'][URL]
        self.assertEqual((entry['watched'], entry['last_watched']), (['a'], None))
        self.assertEqual(rt.upcoming(entry['episodes'], entry['watched'], 'oldest', 1)[0]['id'], 'b')
        self.save_media.assert_called_with(stub.media)
        stub._plan_media_downloads.assert_called_once_with()
        stub._refresh_media_rows.assert_called_once_with()

    def test_an_earlier_episode_leaves_the_last_watched_alone(self):
        stub = self.stub()
        stub.mark_media_unwatched(URL, 'a')
        self.assertEqual(stub.media['sources'][URL]['last_watched']['id'], 'b')

    def test_a_movie_waiting_to_be_removed_is_kept(self):
        stub = self.stub()
        stub.media['sources'][URL]['remove_at'] = NOW + 3600
        stub.mark_media_unwatched(URL, 'b')
        self.assertIsNone(stub.media['sources'][URL]['remove_at'])

    def test_an_episode_that_was_not_watched_changes_nothing(self):
        stub = self.stub()
        stub.media['sources'][URL]['watched'] = ['a']
        self.assertFalse(stub.mark_media_unwatched(URL, 'b'))
        self.assertFalse(stub.mark_media_unwatched('https://nowhere.example/', 'b'))
        self.save_media.assert_not_called()

    def test_the_menu_button_closes_the_menu_before_it_acts(self):
        order = []
        stub = self.stub()
        stub.mark_media_unwatched = mock.Mock(side_effect=lambda *a: order.append(('unwatch', a)))
        popover = mock.Mock()
        popover.popdown.side_effect = lambda: order.append('popdown')
        rt.FluxTray._media_menu_unwatch(stub, None, popover, URL, 'b')
        self.assertEqual(order, ['popdown', ('unwatch', (URL, 'b'))])


class TestKeepingOnlySomeWatchedFiles(MediaCase):
    """`behind`: only that many of the most recently watched episodes keep their files."""

    def setUp(self):
        super().setUp()
        self.trashed = []

        def trash(path, root):
            self.trashed.append((os.path.basename(path), root))
            os.remove(path)
            return path not in self.refuse
        self.refuse = set()
        patcher = mock.patch.object(rt, 'move_to_trash', side_effect=trash)
        patcher.start()
        self.addCleanup(patcher.stop)

    def stub(self, watched, episodes=('a', 'b', 'c', 'd', 'e'), url=URL):
        os.makedirs(os.path.join(self.dir, 'Show'), exist_ok=True)
        files = {i: {'video': self.touch(f'Show/{i}.mkv'), 'subs': [self.touch(f'Show/{i}.en.srt')]} for i in episodes}
        stub = Stub()
        stub.media['sources'][url] = entry_with(*(ep(i, n + 1) for n, i in enumerate(episodes)), watched=watched, files=files)
        stub._refresh_media_rows = mock.Mock()
        return stub

    def left(self):
        return sorted(os.listdir(os.path.join(self.dir, 'Show'))) if os.path.isdir(os.path.join(self.dir, 'Show')) else []

    def test_without_the_setting_nothing_is_ever_deleted(self):
        stub = self.stub(['a', 'b', 'c', 'd'])
        stub._prune_watched_files(URL)
        self.assertEqual(self.trashed, [])
        self.assertEqual(len(stub.media['sources'][URL]['files']), 5)

    def test_the_oldest_watched_go_to_the_trash_with_their_subtitles(self):
        self.settings['behind'] = 2
        stub = self.stub(['a', 'b', 'c', 'd'])
        stub._prune_watched_files(URL)
        self.assertEqual(sorted(name for name, _ in self.trashed), ['a.en.srt', 'a.mkv', 'b.en.srt', 'b.mkv'])
        self.assertEqual({root for _, root in self.trashed}, {self.dir})  # nothing outside the media folder is ever asked for
        self.assertEqual(set(stub.media['sources'][URL]['files']), {'c', 'd', 'e'})
        self.assertEqual(self.left(), ['c.en.srt', 'c.mkv', 'd.en.srt', 'd.mkv', 'e.en.srt', 'e.mkv'])
        self.save_media.assert_called_with(stub.media)

    def test_the_watched_order_decides_not_the_episode_order(self):
        self.settings['behind'] = 1
        stub = self.stub(['d', 'a', 'c'])  # watched in this order
        stub._prune_watched_files(URL)
        self.assertEqual(set(stub.media['sources'][URL]['files']), {'b', 'e', 'c'})

    def test_episodes_not_watched_yet_keep_their_files_whatever_the_setting(self):
        self.settings['behind'] = 0
        stub = self.stub(['a', 'b'])
        stub._prune_watched_files(URL)
        self.assertEqual(set(stub.media['sources'][URL]['files']), {'c', 'd', 'e'})

    def test_zero_keeps_no_watched_file(self):
        self.settings['behind'] = 0
        stub = self.stub(['a', 'b', 'c', 'd', 'e'])
        stub._prune_watched_files(URL)
        self.assertEqual(stub.media['sources'][URL]['files'], {})
        self.assertEqual(self.left(), [])

    def test_fewer_watched_than_the_setting_deletes_nothing(self):
        self.settings['behind'] = 3
        stub = self.stub(['a', 'b'])
        stub._prune_watched_files(URL)
        self.assertEqual(self.trashed, [])

    def test_they_stay_watched_so_they_are_not_downloaded_again(self):
        self.settings['behind'] = 1
        stub = self.stub(['a', 'b', 'c'])
        stub._prune_watched_files(URL)
        entry = stub.media['sources'][URL]
        self.assertEqual(entry['watched'], ['a', 'b', 'c'])
        self.assertEqual([e['id'] for e in rt.upcoming(entry['episodes'], entry['watched'], 'oldest', 5)], ['d', 'e'])

    def test_a_file_that_cannot_go_to_the_trash_is_kept_in_the_state_too(self):
        self.settings['behind'] = 1
        stub = self.stub(['a', 'b', 'c'])
        self.refuse = {os.path.join(self.dir, 'Show', 'a.mkv')}
        stub._prune_watched_files(URL)
        self.assertEqual(set(stub.media['sources'][URL]['files']), {'a', 'c', 'd', 'e'})

    def test_a_movie_is_not_pruned_it_has_its_own_removal(self):
        self.settings['behind'] = 0
        self.movies = {URL}
        stub = self.stub(['a', 'b'])
        stub._prune_watched_files(URL)
        self.assertEqual(self.trashed, [])

    def test_a_source_that_is_gone_is_nothing_to_prune(self):
        self.settings['behind'] = 0
        Stub()._prune_watched_files('https://nowhere.example/')
        self.assertEqual(self.trashed, [])

    def test_watching_an_episode_starts_the_pruning_in_the_background(self):
        stub = self.stub(['a'])
        stub._plan_media_downloads = mock.Mock()
        with mock.patch.object(rt.threading, 'Thread') as thread:
            stub.mark_media_watched(URL, 'b')
        self.assertEqual(thread.call_args.kwargs['target'], stub._prune_watched_files)
        self.assertEqual(thread.call_args.kwargs['args'], (URL,))
        thread.return_value.start.assert_called_once_with()


class TestARemovedMovie(MediaCase):
    FILM = 'https://archive.org/details/film'

    def setUp(self):
        super().setUp()
        self.sources = [(self.FILM, 'The Film', None), (URL, None, None)]
        self.movies = {self.FILM}
        self.trashed, self.refuse = [], set()

        def trash(path, root):
            self.trashed.append(os.path.basename(path))
            if path in self.refuse:
                return False
            os.remove(path)
            return True
        patcher = mock.patch.object(rt, 'move_to_trash', side_effect=trash)
        patcher.start()
        self.addCleanup(patcher.stop)

        def remove(urls):
            self.sources = [s for s in self.sources if s[0] not in urls]
        patcher = mock.patch.object(rt, 'remove_media_sources', side_effect=remove)
        patcher.start()
        self.addCleanup(patcher.stop)
        os.makedirs(os.path.join(self.dir, 'The Film'))
        self.video, self.subs = self.touch('The Film/film.mkv'), self.touch('The Film/film.en.srt')
        self.stub = Stub()
        self.stub.media['sources'] = {
            self.FILM: entry_with(ep('f', 1), watched=['f'], title='Film', files={'f': {'video': self.video, 'subs': [self.subs]}}),
            URL: entry_with(ep('a', 1), watched=['a'], title='Show'),
        }
        self.stub._media_rows_removed = mock.Mock()
        self.stub._refresh_media_rows = mock.Mock()

    def due(self, seconds_ago=10):
        self.stub.media['sources'][self.FILM]['remove_at'] = time_now() - seconds_ago

    def test_watching_it_through_sets_a_time_after_the_grace_period(self):
        self.settings['grace'] = 6 * 3600
        with mock.patch.object(rt.time_module, 'time', return_value=NOW):
            self.stub._schedule_movie_removal(self.FILM)
        self.assertEqual(self.stub.media['sources'][self.FILM]['remove_at'], NOW + 6 * 3600)
        self.assertEqual(self.trashed, [])
        self.save_media.assert_called_with(self.stub.media)
        self.stub._refresh_media_rows.assert_called_once_with()

    def test_without_a_grace_period_it_goes_at_once(self):
        self.settings['grace'] = 0
        self.stub._schedule_movie_removal(self.FILM)
        self.assertEqual(sorted(self.trashed), ['film.en.srt', 'film.mkv'])
        self.assertNotIn(self.FILM, self.stub.media['sources'])

    def test_when_the_time_has_come_the_file_the_line_and_the_memory_of_it_all_go(self):
        self.due()
        gone = self.stub.remove_due_movies()
        self.assertEqual(gone, [self.FILM])
        self.assertEqual(sorted(self.trashed), ['film.en.srt', 'film.mkv'])
        self.assertEqual([s[0] for s in self.sources], [URL])
        self.assertEqual(set(self.stub.media['sources']), {URL})
        self.assertEqual(self.queued(self.stub, '_media_rows_removed'), [([self.FILM],)])
        self.assertFalse(os.path.exists(os.path.join(self.dir, 'The Film')))  # and the folder it leaves empty

    def test_before_the_time_nothing_happens(self):
        self.stub.media['sources'][self.FILM]['remove_at'] = time_now() + 3600
        self.assertEqual(self.stub.remove_due_movies(), [])
        self.assertEqual(self.trashed, [])
        self.assertIn(self.FILM, self.stub.media['sources'])

    def test_a_movie_not_watched_through_is_never_removed(self):
        self.due()
        self.stub.media['sources'][self.FILM]['watched'] = []
        self.assertEqual(self.stub.remove_due_movies(), [])
        self.assertEqual(self.trashed, [])

    def test_a_source_that_is_not_marked_a_movie_is_never_removed_this_way(self):
        self.stub.media['sources'][URL]['remove_at'] = time_now() - 10
        self.assertEqual(self.stub.remove_due_movies(), [])
        self.assertIn(URL, self.stub.media['sources'])

    def test_a_movie_whose_marker_was_taken_out_of_the_config_is_left(self):
        self.due()
        self.movies = set()
        self.assertEqual(self.stub.remove_due_movies(), [])
        self.assertEqual(self.trashed, [])

    def test_a_file_that_cannot_go_to_the_trash_keeps_the_movie_and_waits_an_hour(self):
        self.due()
        self.refuse = {self.video}
        with mock.patch.object(rt.time_module, 'time', return_value=NOW):
            self.stub.media['sources'][self.FILM]['remove_at'] = NOW - 5
            self.assertEqual(self.stub.remove_due_movies(), [])
        entry = self.stub.media['sources'][self.FILM]
        self.assertEqual(entry['remove_at'], NOW + 3600)
        self.assertIn(self.FILM, [s[0] for s in self.sources])
        self.assertEqual(entry['files'].keys(), {'f'})  # still listed: the video is still there

    def test_removing_by_hand_from_the_menu_takes_the_file_too(self):
        gone = self.stub.remove_consumed_media([self.FILM])
        self.assertEqual(gone, [self.FILM])
        self.assertEqual(sorted(self.trashed), ['film.en.srt', 'film.mkv'])
        self.stub._media_rows_removed.assert_called_once_with([self.FILM])

    def test_removing_by_hand_a_movie_whose_file_cannot_go_leaves_it_as_it_is(self):
        self.refuse = {self.video}
        self.assertEqual(self.stub.remove_consumed_media([self.FILM]), [])
        self.assertIn(self.FILM, [s[0] for s in self.sources])
        self.assertIn(self.FILM, self.stub.media['sources'])

    def test_removing_a_series_by_hand_leaves_its_files_alone(self):
        self.stub.media['sources'][URL]['files'] = {'a': {'video': self.touch('a.mkv'), 'subs': []}}
        self.assertEqual(self.stub.remove_consumed_media([URL]), [URL])
        self.assertEqual(self.trashed, [])
        self.assertTrue(os.path.exists(os.path.join(self.dir, 'a.mkv')))

    def test_the_media_checks_start_by_removing_what_is_due(self):
        for method in ('initial_media_check', 'periodic_media_check'):
            stub = Stub()
            stub.remove_due_movies = mock.Mock()
            stub.start_media_check = stub.periodic_media_check = mock.Mock()
            with mock.patch.object(rt.threading, 'Thread') as thread, mock.patch.object(rt, 'run_when_online'), \
                    mock.patch.object(rt.GLib, 'timeout_add_seconds'):
                getattr(rt.FluxTray, method)(stub)
            self.assertEqual(thread.call_args.kwargs['target'], stub.remove_due_movies, method)
            thread.return_value.start.assert_called_once_with()


def time_now():
    return rt.time_module.time()
