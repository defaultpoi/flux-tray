"""The popup's appearance and click hooks, pinned to files in tests/golden/.

tests/golden/render_popup.py builds the real popup from fixed data (a child
process: HOME decides where the app looks for its files when it is imported)
and prints the widget tree: text and markup, tooltips, margins, the style
classes the app added, the attributes that say what a click on a row does, and
the stylesheet. This test compares that with popup_<scenario>.json.

A difference is not always a mistake: after an intended change to how the popup
looks, look at the diff, then rewrite the files with
    FLUX_TRAY_UPDATE_GOLDEN=1 xvfb-run -a python3 -m unittest test_golden_popup
and commit them with the change. Needs real GTK and a display, so it is skipped
in the GTK-stubbed run and without DISPLAY.
"""
import difflib
import os
import pathlib
import subprocess
import sys
import unittest
from unittest import mock

HERE = pathlib.Path(__file__).resolve().parent
GOLDEN = HERE / 'golden'
STUBBED = isinstance(sys.modules.get('gi'), mock.Mock)


@unittest.skipIf(STUBBED, 'needs the real GTK bindings')
@unittest.skipUnless(os.environ.get('DISPLAY'), 'needs a display (run under xvfb-run)')
class TestPopupAppearance(unittest.TestCase):
    def render(self, scenario):
        env = {k: v for k, v in os.environ.items() if k not in ('GTK_THEME', 'FLUX_TRAY_DEBUG')}
        done = subprocess.run([sys.executable, '-W', 'ignore', str(GOLDEN / 'render_popup.py'), scenario],
                              capture_output=True, text=True, timeout=120, env=env)
        self.assertEqual(done.returncode, 0, done.stderr[-2000:])
        return done.stdout

    def check(self, scenario):
        actual = self.render(scenario)
        path = GOLDEN / f'popup_{scenario}.json'
        if os.environ.get('FLUX_TRAY_UPDATE_GOLDEN'):
            path.write_text(actual)
            self.skipTest(f'rewrote {path.name}')
        expected = path.read_text()
        if actual != expected:
            diff = list(difflib.unified_diff(expected.splitlines(), actual.splitlines(), 'golden', 'now', lineterm='', n=3))
            self.fail(f'the popup ({scenario}) no longer matches {path.name}; {len(diff)} diff lines:\n' + '\n'.join(diff[:60]))

    def test_every_section_at_once(self):
        self.check('full')

    def test_nothing_unread_but_a_saved_item(self):
        self.check('quiet')

    def test_the_menu_of_each_kind_of_media_row(self):
        self.check('media_menu')

    def test_removing_the_watched_sources_through_the_menu_end_to_end(self):
        self.check('media_removed')

    def test_the_run_is_repeatable(self):
        self.assertEqual(self.render('full'), self.render('full'))


if __name__ == '__main__':
    unittest.main()
