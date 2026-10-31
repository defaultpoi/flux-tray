"""docs/FEATURES.md names the tests of every feature; this keeps it honest.

It reads the test files without importing them, so it also runs with GTK
stubbed. It fails when a feature row names no test, when a named test class
does not exist, when a test module is named by no row, or when a row points at a
section of docs/XFCE-VALIDATION.md that is not there.
"""
import ast
import pathlib
import re
import unittest

TESTS = pathlib.Path(__file__).resolve().parent
DOCS = TESTS.parent / 'docs'
NOT_FEATURES = {'test_parity', 'test_facade'}  # about the tests themselves


def test_classes():
    found = {}
    for path in sorted(TESTS.glob('test_*.py')):
        tree = ast.parse(path.read_text())
        found[path.stem] = {n.name for n in tree.body if isinstance(n, ast.ClassDef) and n.name.startswith('Test')}
    return found


def feature_rows():
    rows = []
    for line in (DOCS / 'FEATURES.md').read_text().splitlines():
        cells = [c.strip() for c in line.strip().strip('|').split('|')]
        if len(cells) == 4 and re.fullmatch(r'F\d+', cells[0]):
            rows.append(cells)
    return rows


class TestFeatureMatrix(unittest.TestCase):
    def test_there_are_features(self):
        self.assertGreaterEqual(len(feature_rows()), 30)

    def test_feature_ids_are_unique(self):
        ids = [r[0] for r in feature_rows()]
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_feature_names_tests_and_every_one_exists(self):
        known = test_classes()
        problems = []
        for feature, _what, tests, _desktop in feature_rows():
            refs = [t.strip() for t in tests.split(',') if t.strip()]
            if not refs:
                problems.append(f'{feature}: no tests named')
            for ref in refs:
                module, _, name = ref.partition('.')
                if name not in known.get(module, ()):
                    problems.append(f'{feature}: {ref} does not exist')
        self.assertEqual(problems, [])

    def test_every_test_module_belongs_to_a_feature(self):
        named = {t.strip().partition('.')[0] for r in feature_rows() for t in r[2].split(',')}
        orphans = sorted(set(test_classes()) - named - NOT_FEATURES)
        self.assertEqual(orphans, [], 'add these test modules to a row of docs/FEATURES.md')

    def test_desktop_checks_point_at_sections_that_exist(self):
        sections = set(re.findall(r'^## (\d+)\.', (DOCS / 'XFCE-VALIDATION.md').read_text(), re.MULTILINE))
        problems = []
        for feature, _what, _tests, desktop in feature_rows():
            for number in re.findall(r'\d+', desktop):
                if number not in sections:
                    problems.append(f'{feature}: section {number} of XFCE-VALIDATION.md')
        self.assertEqual(problems, [])


if __name__ == '__main__':
    unittest.main()
