import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent


class TestInstallScripts(unittest.TestCase):
    def setUp(self):
        self.home = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        self.link = self.home / '.local' / 'bin' / 'flux-tray'
        self.entry = self.home / '.config' / 'autostart' / 'flux-tray.desktop'
        self.config = self.home / '.config' / 'flux-tray'
        self.config.mkdir(parents=True)
        (self.config / 'config.conf').write_text('[feeds]\n')

    def run_script(self, script, *arguments):
        env = {k: v for k, v in os.environ.items() if k != 'XDG_CONFIG_HOME'}
        env['HOME'] = str(self.home)
        return subprocess.run(['sh', str(ROOT / script), *arguments], capture_output=True, text=True, env=env)

    def test_installing_links_the_checkout_and_adds_no_autostart_entry(self):
        done = self.run_script('install.sh')
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(os.readlink(self.link), str(ROOT / 'flux-tray'))
        self.assertFalse(self.entry.exists())

    def test_autostart_writes_an_entry_that_runs_the_link_and_can_be_removed(self):
        self.assertEqual(self.run_script('install.sh', '--autostart').returncode, 0)
        text = self.entry.read_text()
        self.assertIn(f'Exec={self.link}\n', text)
        self.assertIn('Terminal=false', text)
        self.assertEqual(self.run_script('install.sh', '--no-autostart').returncode, 0)
        self.assertFalse(self.entry.exists())
        self.assertTrue(self.link.is_symlink())

    def test_installing_again_changes_nothing(self):
        self.run_script('install.sh', '--autostart')
        before = self.entry.read_text()
        self.assertEqual(self.run_script('install.sh').returncode, 0)  # no flag keeps the entry as it was
        self.assertEqual(self.entry.read_text(), before)
        self.assertEqual(os.readlink(self.link), str(ROOT / 'flux-tray'))

    def test_a_real_file_in_the_way_is_not_overwritten(self):
        self.link.parent.mkdir(parents=True)
        self.link.write_text('mine')
        done = self.run_script('install.sh')
        self.assertEqual(done.returncode, 1)
        self.assertEqual(self.link.read_text(), 'mine')

    def test_an_unknown_option_is_refused(self):
        self.assertEqual(self.run_script('install.sh', '--bogus').returncode, 2)
        self.assertFalse(self.link.exists())

    def test_uninstalling_removes_the_link_and_the_entry_but_keeps_the_config(self):
        self.run_script('install.sh', '--autostart')
        self.assertEqual(self.run_script('uninstall.sh').returncode, 0)
        self.assertFalse(self.link.exists() or self.link.is_symlink())
        self.assertFalse(self.entry.exists())
        self.assertEqual((self.config / 'config.conf').read_text(), '[feeds]\n')

    def test_uninstalling_leaves_a_link_that_points_somewhere_else(self):
        self.link.parent.mkdir(parents=True)
        self.link.symlink_to('/somewhere/else')
        done = self.run_script('uninstall.sh')
        self.assertEqual(done.returncode, 0)
        self.assertEqual(os.readlink(self.link), '/somewhere/else')


if __name__ == '__main__':
    unittest.main()
