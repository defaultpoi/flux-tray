import pathlib
import subprocess
import sys
import tomllib
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent


class TestPythonVersion(unittest.TestCase):
    """Flux Tray runs on Python 3.14 and nothing older, and says so."""

    def import_as(self, version):
        code = ('import sys; sys.version_info = %r; sys.path.insert(0, %r); import flux_tray' % (version, str(ROOT)))
        return subprocess.run([sys.executable, '-c', code], capture_output=True, text=True)

    def test_an_older_python_stops_with_a_message_and_nothing_else_is_imported(self):
        for version in ((3, 13, 5, 'final', 0), (3, 12, 3, 'final', 0)):
            done = self.import_as(version)
            self.assertEqual(done.returncode, 1, version)
            self.assertIn('needs Python 3.14 or newer', done.stderr)
            self.assertNotIn('Traceback', done.stderr)

    def test_python_3_14_is_accepted(self):
        self.assertEqual(self.import_as((3, 14, 0, 'final', 0)).returncode, 0)

    def test_the_tests_themselves_run_on_it(self):
        self.assertGreaterEqual(sys.version_info[:2], (3, 14))

    def test_the_project_metadata_says_the_same(self):
        project = tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']
        self.assertEqual((project['name'], project['requires-python']), ('flux-tray', '>=3.14'))


if __name__ == '__main__':
    unittest.main()
