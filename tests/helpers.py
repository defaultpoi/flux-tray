"""Fixtures shared by several test files."""
import os
import shutil
import tempfile
import unittest
from unittest import mock

from facade import rt


class TmpConfigCase(unittest.TestCase):
    """Redirects CONFIG_FILE / STATE_FILE to a temp dir for each test."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        patcher = mock.patch.multiple(
            rt,
            CONFIG_FILE=os.path.join(self.dir, 'config.conf'),
            STATE_FILE=os.path.join(self.dir, 'state.json'),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def conf(self, text):
        with open(rt.CONFIG_FILE, 'w') as f:
            f.write(text)

    def state_text(self, text):
        with open(rt.STATE_FILE, 'w') as f:
            f.write(text)


def isolate_media_caches(case):
    """Points the metadata cache, the poster cache and the discovery cache of a test at
    a temp dir (and clears what playing leaves in a module global), so that a test never
    reads or writes the person's own."""
    import pathlib
    folder = pathlib.Path(tempfile.mkdtemp())
    case.addCleanup(shutil.rmtree, folder, ignore_errors=True)
    patcher = mock.patch.multiple(
        rt,
        METADATA_CACHE_FILE=folder / 'metadata_cache.json',
        POSTER_CACHE_DIR=folder / 'posters',
        OMDB_QUOTA_FILE=folder / 'omdb_quota.json',
        CACHE_FILE=folder / 'media_cache.json',
    )
    patcher.start()
    case.addCleanup(patcher.stop)
    rt.clear_media_playing()
    case.addCleanup(rt.clear_media_playing)
    return folder


def ts(weekday, hour, minute=0, second=0):
    """Timestamp of a local time on the given weekday (0=Mon) of the reference week."""
    return rt.datetime(2026, 10, 5 + weekday, hour, minute, second).timestamp()


def dt(weekday, hour, minute=0):
    """A datetime on the given weekday (0=Mon) of a fixed reference week."""
    return rt.datetime(2026, 10, 5 + weekday, hour, minute)  # 2026-10-05 is a Monday
