import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from facade import rt


class TestListAllUpdates(unittest.TestCase):
    def _proc(self, out='', err='', rc=0):
        p = mock.MagicMock()
        p.communicate.return_value = (out, err)
        p.returncode = rc
        return p

    def test_success(self):
        line = 'cryptsetup-2.8.8_1 update x86_64 https://r 1 2\n'
        with mock.patch.object(rt.subprocess, 'Popen', return_value=self._proc(out=line)):
            self.assertEqual(rt.list_all_updates(), ['cryptsetup'])

    def test_no_updates_is_empty_list_not_none(self):
        with mock.patch.object(rt.subprocess, 'Popen', return_value=self._proc()):
            self.assertEqual(rt.list_all_updates(), [])

    def test_nonzero_exit_is_failure(self):
        with mock.patch.object(rt.subprocess, 'Popen', return_value=self._proc(rc=1)):
            self.assertIsNone(rt.list_all_updates())

    def test_spawn_error_is_failure(self):
        with mock.patch.object(rt.subprocess, 'Popen', side_effect=OSError):
            self.assertIsNone(rt.list_all_updates())

    def test_timeout_kills_group_and_fails(self):
        p = self._proc()
        p.communicate.side_effect = rt.subprocess.TimeoutExpired('xbps-install', 60)
        with mock.patch.object(rt.subprocess, 'Popen', return_value=p), \
                mock.patch.object(rt, '_kill_process_group') as kill:
            self.assertIsNone(rt.list_all_updates())
            kill.assert_called_once_with(p)


class TestEditFileExternally(unittest.TestCase):
    def test_default_application_via_gio_is_used_first(self):
        with mock.patch.object(rt.Gio.AppInfo, 'launch_default_for_uri', return_value=True) as launch, \
                mock.patch.object(rt.subprocess, 'Popen') as popen:
            rt.edit_file_externally('/tmp/x.conf')
        launch.assert_called_once()
        popen.assert_not_called()

    def test_falls_back_to_xdg_open_when_gio_has_no_handler(self):
        class FakeGlibError(Exception):
            message = 'no handler'
        with mock.patch.object(rt.GLib, 'Error', FakeGlibError), \
                mock.patch.object(rt.Gio.AppInfo, 'launch_default_for_uri', side_effect=FakeGlibError()), \
                mock.patch.object(rt.shutil, 'which', side_effect=lambda n: '/usr/bin/xdg-open' if n == 'xdg-open' else None), \
                mock.patch.object(rt.subprocess, 'Popen') as popen:
            rt.edit_file_externally('/tmp/x.conf')
        popen.assert_called_once_with(['xdg-open', '/tmp/x.conf'])

    def test_terminal_editor_is_the_last_resort(self):
        with mock.patch.object(rt.Gio.AppInfo, 'launch_default_for_uri', return_value=False), \
                mock.patch.object(rt.shutil, 'which', side_effect=lambda n: '/usr/bin/xfce4-terminal' if n == 'xfce4-terminal' else None), \
                mock.patch.dict(rt.os.environ, {'EDITOR': 'nvim'}), \
                mock.patch.object(rt.subprocess, 'Popen') as popen:
            rt.edit_file_externally('/tmp/x.conf')
        popen.assert_called_once_with(['xfce4-terminal', '-e', 'nvim "/tmp/x.conf"'])


class TestNotificationSound(unittest.TestCase):
    def setUp(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        self.sound = os.path.join(d, 'notification.wav')
        patcher = mock.patch.object(rt, 'NOTIFICATION_SOUND_FILE', self.sound)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_plays_the_config_dir_file_with_the_first_available_player(self):
        open(self.sound, 'wb').close()
        with mock.patch.object(rt.shutil, 'which', side_effect=lambda p: '/usr/bin/aplay' if p == 'aplay' else None), \
                mock.patch.object(rt.subprocess, 'Popen') as popen:
            rt.play_notification_sound()
        self.assertEqual(popen.call_args[0][0], ['aplay', '-q', self.sound])

    def test_silent_when_the_file_is_missing_no_system_fallback(self):
        with mock.patch.object(rt.shutil, 'which', return_value='/usr/bin/paplay'), \
                mock.patch.object(rt.subprocess, 'Popen') as popen:
            rt.play_notification_sound()
        popen.assert_not_called()

    def test_no_player_installed_is_a_quiet_noop(self):
        open(self.sound, 'wb').close()
        with mock.patch.object(rt.shutil, 'which', return_value=None), \
                mock.patch.object(rt.subprocess, 'Popen') as popen:
            rt.play_notification_sound()
        popen.assert_not_called()


class TestCheckYoutubeLiveChannels(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(rt, 'fetch_youtube_live_details',
                                    return_value={'viewers': None, 'started': None})
        self.details = patcher.start()
        self.addCleanup(patcher.stop)

    def test_live_channels_get_viewers_and_start_time_from_the_page(self):
        self.details.return_value = {'viewers': 283, 'started': 1000.0}
        with mock.patch.object(rt.subprocess, 'run', side_effect=self._fake_run()):
            live = rt.check_youtube_live_channels(['live_channel', 'offline_channel'])
        self.assertEqual(live['live_channel'], {'title': 'Live now!', 'category': 'Gaming',
                                                'viewers': 283, 'started': 1000.0})
        self.details.assert_called_once_with('live_channel')   # only for channels that are live

    def _fake_run(self, live_substring='live_channel', offline_substring='offline_channel'):
        def run(cmd, capture_output, text, timeout):
            url = cmd[-1]
            result = mock.MagicMock()
            if live_substring in url:
                result.stdout = json.dumps({'metadata': {'id': 'x', 'author': 'A',
                                                           'category': 'Gaming', 'title': 'Live now!'},
                                            'streams': {'best': {}}})
            elif offline_substring in url:
                result.stdout = json.dumps({'error': 'No playable streams found'})
            else:
                raise OSError('boom')
            return result
        return run

    def test_empty_channels_no_subprocess(self):
        with mock.patch.object(rt.subprocess, 'run') as run:
            self.assertEqual(rt.check_youtube_live_channels([]), {})
            run.assert_not_called()

    def test_live_and_offline_distinguished(self):
        with mock.patch.object(rt.subprocess, 'run', side_effect=self._fake_run()):
            live = rt.check_youtube_live_channels(['live_channel', 'offline_channel'])
        self.assertEqual(live, {'live_channel': {'title': 'Live now!', 'category': 'Gaming',
                                                 'viewers': None, 'started': None}})

    def test_total_failure_returns_none(self):
        with mock.patch.object(rt.subprocess, 'run', side_effect=OSError('no streamlink')):
            self.assertIsNone(rt.check_youtube_live_channels(['a', 'b']))

    def test_partial_failure_keeps_successful_results(self):
        def run(cmd, capture_output, text, timeout):
            if 'bad' in cmd[-1]:
                raise OSError('network blip')
            result = mock.MagicMock()
            result.stdout = json.dumps({'error': 'No playable streams found'})
            return result
        with mock.patch.object(rt.subprocess, 'run', side_effect=run):
            result = rt.check_youtube_live_channels(['bad', 'good'])
        self.assertEqual(result, {})  # good determined not-live; bad simply absent, not a crash

    def test_live_when_streams_present_even_without_title(self):
        def run(cmd, capture_output, text, timeout):
            result = mock.MagicMock()
            result.stdout = json.dumps({'metadata': {'title': None}, 'streams': {'best': {}}})
            return result
        with mock.patch.object(rt.subprocess, 'run', side_effect=run), mock.patch.object(rt, '_log'):
            self.assertEqual(rt.check_youtube_live_channels(['@chan']),
                             {'@chan': {'title': '', 'category': '', 'viewers': None, 'started': None}})

    def test_log_lines_before_json_are_tolerated(self):
        def run(cmd, capture_output, text, timeout):
            result = mock.MagicMock()
            result.stdout = '[cli][info] hello\n' + json.dumps({'metadata': {'title': 'T'}, 'streams': {'best': {}}})
            return result
        with mock.patch.object(rt.subprocess, 'run', side_effect=run):
            self.assertEqual(rt.check_youtube_live_channels(['@chan']),
                             {'@chan': {'title': 'T', 'category': '', 'viewers': None, 'started': None}})

    def test_errors_are_logged(self):
        def run(cmd, capture_output, text, timeout):
            result = mock.MagicMock()
            result.stdout = json.dumps({'error': 'Unable to open URL: 403 Forbidden'})
            return result
        with mock.patch.object(rt.subprocess, 'run', side_effect=run), mock.patch.object(rt, '_log') as log:
            self.assertEqual(rt.check_youtube_live_channels(['@chan']), {})
        self.assertIn('403 Forbidden', log.call_args[0][0])

    def test_unparseable_json_treated_as_this_channel_failed(self):
        def run(cmd, capture_output, text, timeout):
            result = mock.MagicMock()
            result.stdout = 'not json'
            return result
        with mock.patch.object(rt.subprocess, 'run', side_effect=run):
            self.assertIsNone(rt.check_youtube_live_channels(['a']))


if __name__ == '__main__':
    unittest.main()


class TestMoveToTrash(unittest.TestCase):
    def setUp(self):
        self.dir = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.root = os.path.join(self.dir, 'media')
        os.makedirs(os.path.join(self.root, 'Show'))
        self.file = os.path.join(self.root, 'Show', 'e1.mkv')
        with open(self.file, 'w') as f:
            f.write('video')

    def trash(self, path, gio=None):
        gio = gio or mock.MagicMock()
        with mock.patch.object(rt, 'Gio', gio):
            return rt.move_to_trash(path, self.root), gio

    def test_a_file_inside_the_media_folder_goes_to_the_trash_not_to_oblivion(self):
        done, gio = self.trash(self.file)
        self.assertTrue(done)
        gio.File.new_for_path.assert_called_once_with(self.file)
        gio.File.new_for_path.return_value.trash.assert_called_once_with(None)

    def test_a_file_that_is_already_gone_counts_as_done_without_asking_the_desktop(self):
        done, gio = self.trash(os.path.join(self.root, 'Show', 'gone.mkv'))
        self.assertTrue(done)
        gio.File.new_for_path.assert_not_called()

    def test_nothing_outside_the_media_folder_is_touched(self):
        outside = os.path.join(self.dir, 'elsewhere.txt')
        sibling = os.path.join(self.dir, 'media2', 'x.mkv')  # same prefix, another folder
        os.makedirs(os.path.dirname(sibling))
        for path in (outside, sibling):
            with open(path, 'w') as f:
                f.write('x')
            done, gio = self.trash(path)
            self.assertFalse(done, path)
            gio.File.new_for_path.assert_not_called()

    def test_a_dotdot_that_leaves_the_folder_is_refused(self):
        escape = os.path.join(self.root, 'Show', '..', '..', 'elsewhere.txt')
        with open(os.path.join(self.dir, 'elsewhere.txt'), 'w') as f:
            f.write('x')
        done, gio = self.trash(escape)
        self.assertFalse(done)
        gio.File.new_for_path.assert_not_called()

    def test_a_link_is_refused_even_when_it_points_inside(self):
        link = os.path.join(self.root, 'Show', 'link.mkv')
        os.symlink(self.file, link)
        done, gio = self.trash(link)
        self.assertFalse(done)
        gio.File.new_for_path.assert_not_called()

    def test_a_directory_and_the_media_folder_itself_are_refused(self):
        for path in (os.path.join(self.root, 'Show'), self.root):
            done, gio = self.trash(path)
            self.assertFalse(done, path)
            gio.File.new_for_path.assert_not_called()

    def test_a_desktop_that_cannot_trash_leaves_the_file_and_says_so(self):
        gio = mock.MagicMock()
        gio.File.new_for_path.return_value.trash.side_effect = RuntimeError('no trash on this disk')
        with mock.patch.object(rt, '_log') as log:
            done, _ = self.trash(self.file, gio)
        self.assertFalse(done)
        self.assertTrue(os.path.exists(self.file))
        self.assertIn('no trash on this disk', log.call_args[0][0])

    @unittest.skipIf(isinstance(sys.modules.get('gi'), mock.Mock), 'needs the real GIO')
    def test_with_the_real_desktop_trash_the_file_ends_up_in_the_trash_folder(self):
        data = os.path.join(self.dir, 'data')
        code = ('import sys; sys.path.insert(0, %r); from flux_tray.desktop import move_to_trash; '
                'sys.exit(0 if move_to_trash(%r, %r) else 3)' % (os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                                                  self.file, self.root))
        env = {**os.environ, 'HOME': self.dir, 'XDG_DATA_HOME': data}
        done = subprocess.run([sys.executable, '-W', 'ignore', '-c', code], env=env, capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr[-600:])
        self.assertFalse(os.path.exists(self.file))
        self.assertEqual(os.listdir(os.path.join(data, 'Trash', 'files')), ['e1.mkv'])


class TestRemoveEmptyDirs(unittest.TestCase):
    def setUp(self):
        self.dir = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.root = os.path.join(self.dir, 'media')
        os.makedirs(os.path.join(self.root, 'Show', 'Season 1'))

    def test_empty_folders_go_up_to_but_not_including_the_media_folder(self):
        rt.remove_empty_dirs(os.path.join(self.root, 'Show', 'Season 1'), self.root)
        self.assertEqual(os.listdir(self.root), [])
        self.assertTrue(os.path.isdir(self.root))

    def test_a_folder_with_something_in_it_stops_the_climb(self):
        with open(os.path.join(self.root, 'Show', 'poster.jpg'), 'w') as f:
            f.write('x')
        rt.remove_empty_dirs(os.path.join(self.root, 'Show', 'Season 1'), self.root)
        self.assertEqual(os.listdir(os.path.join(self.root, 'Show')), ['poster.jpg'])

    def test_nothing_outside_the_media_folder_is_ever_removed(self):
        other = os.path.join(self.dir, 'other', 'empty')
        os.makedirs(other)
        rt.remove_empty_dirs(other, self.root)
        self.assertTrue(os.path.isdir(other))
        rt.remove_empty_dirs(self.root, self.root)
        self.assertTrue(os.path.isdir(self.root))
