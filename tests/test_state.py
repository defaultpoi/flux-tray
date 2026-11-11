import json
import os
import tempfile
import unittest
from unittest import mock

from facade import rt
from helpers import TmpConfigCase


def temp_files(directory):
    return sorted(name for name in os.listdir(directory) if name.endswith('.tmp'))


class TestState(TmpConfigCase):
    def test_missing_file_gives_defaults(self):
        s = rt.load_state()
        self.assertEqual(s['seen'], {})
        self.assertEqual(s['unread'], [])
        self.assertEqual(s['available_updates'], [])
        self.assertEqual(s['live_channels'], [])
        self.assertEqual(s['last_checked'], {})

    def test_orphans_default_to_an_empty_list(self):
        self.assertEqual(rt.load_state()['orphans'], [])

    def test_orphans_must_be_a_list_of_names(self):
        self.state_text(json.dumps({'orphans': 'libfoo'}))
        self.assertEqual(rt.load_state()['orphans'], [])
        self.state_text(json.dumps({'orphans': ['libfoo', 5, None, 'libbar']}))
        self.assertEqual(rt.load_state()['orphans'], ['libfoo', 'libbar'])

    def test_read_later_defaults_to_an_empty_list(self):
        self.assertEqual(rt.load_state()['read_later'], [])

    def test_read_later_must_be_a_list_of_complete_items(self):
        self.state_text(json.dumps({'read_later': 'oops'}))
        self.assertEqual(rt.load_state()['read_later'], [])
        good = {'id': '1', 'title': 'T', 'link': 'https://x.example/1', 'feed_url': 'u', 'saved': 5.0, 'tags': ['a']}
        self.state_text(json.dumps({'read_later': [good, {'id': '2'}, 'text', None, {'id': 3, 'title': 'T', 'link': 'l'}]}))
        self.assertEqual(rt.load_state()['read_later'], [good])

    def test_corrupt_json_gives_defaults(self):
        self.state_text('{not json')
        self.assertEqual(rt.load_state()['unread'], [])

    def test_non_dict_json_gives_defaults(self):
        self.state_text('[1, 2]')
        self.assertEqual(rt.load_state()['seen'], {})

    def corrupt_copy(self):
        with open(rt.STATE_FILE + '.corrupt') as f:
            return f.read()

    def test_a_corrupt_file_is_set_aside_and_not_overwritten_by_the_next_save(self):
        self.state_text('{"seen": {"a": 1}, "unread": [')  # cut off in the middle
        state = rt.load_state()
        self.assertEqual(state['unread'], [])
        self.assertEqual(self.corrupt_copy(), '{"seen": {"a": 1}, "unread": [')
        self.assertFalse(os.path.exists(rt.STATE_FILE))
        rt.save_state(state)  # what the app does a moment later
        self.assertEqual(self.corrupt_copy(), '{"seen": {"a": 1}, "unread": [')
        with open(rt.STATE_FILE) as f:
            self.assertEqual(json.load(f)['unread'], [])

    def test_json_that_is_not_an_object_is_set_aside(self):
        self.state_text('[1, 2]')
        self.assertEqual(rt.load_state()['seen'], {})
        self.assertEqual(self.corrupt_copy(), '[1, 2]')
        self.assertFalse(os.path.exists(rt.STATE_FILE))

    def test_a_file_that_is_not_text_is_set_aside_instead_of_crashing_the_start(self):
        with open(rt.STATE_FILE, 'wb') as f:
            f.write(b'\xff\xfe\x00{')
        self.assertEqual(rt.load_state()['unread'], [])
        with open(rt.STATE_FILE + '.corrupt', 'rb') as f:
            self.assertEqual(f.read(), b'\xff\xfe\x00{')

    def test_a_good_or_missing_file_is_not_set_aside(self):
        rt.load_state()
        self.state_text(json.dumps({'unread': [{'id': 'a'}]}))
        self.assertEqual(rt.load_state()['unread'], [{'id': 'a'}])
        self.state_text(json.dumps({'seen': [], 'unread': 'x'}))  # wrong-shaped keys are reset one by one
        rt.load_state()
        self.assertTrue(os.path.exists(rt.STATE_FILE))
        self.assertFalse(os.path.exists(rt.STATE_FILE + '.corrupt'))

    def test_a_later_corrupt_file_replaces_the_earlier_copy(self):
        self.state_text('{first')
        rt.load_state()
        self.state_text('{second')
        rt.load_state()
        self.assertEqual(self.corrupt_copy(), '{second')

    def test_a_failed_move_still_starts_with_defaults(self):
        self.state_text('{not json')
        with mock.patch.object(rt.os, 'replace', side_effect=OSError('read-only')):
            self.assertEqual(rt.load_state()['unread'], [])

    def test_a_file_that_cannot_be_read_is_not_called_corrupt(self):
        os.mkdir(rt.STATE_FILE)  # exists, but opening it fails with an OSError
        self.assertEqual(rt.load_state()['unread'], [])
        self.assertTrue(os.path.isdir(rt.STATE_FILE))
        self.assertFalse(os.path.exists(rt.STATE_FILE + '.corrupt'))

    def test_wrong_shaped_keys_reset(self):
        self.state_text(json.dumps({
            'seen': [], 'unread': 'x', 'available_updates': {},
            'live_channels': 5, 'last_checked': [],
        }))
        s = rt.load_state()
        self.assertEqual(s['seen'], {})
        self.assertEqual(s['unread'], [])
        self.assertEqual(s['available_updates'], [])
        self.assertEqual(s['live_channels'], [])
        self.assertEqual(s['last_checked'], {})

    def test_valid_keys_preserved(self):
        self.state_text(json.dumps({'unread': [{'id': 'a'}], 'seen': {'a': 1}}))
        s = rt.load_state()
        self.assertEqual(s['unread'], [{'id': 'a'}])
        self.assertEqual(s['seen'], {'a': {'seen_at': 1, 'updated': None}})

    def test_a_saved_countdown_end_is_kept_only_when_it_is_a_finite_number(self):
        self.state_text(json.dumps({'timer_end': 1760000000.5}))
        self.assertEqual(rt.load_state()['timer_end'], 1760000000.5)
        for bad in ('soon', None, True, [5], {'a': 1}):
            self.state_text(json.dumps({'timer_end': bad}))
            self.assertNotIn('timer_end', rt.load_state())
        self.state_text('{"timer_end": NaN}')  # Python's json accepts these
        self.assertNotIn('timer_end', rt.load_state())
        self.state_text('{"timer_end": Infinity}')
        self.assertNotIn('timer_end', rt.load_state())

    def test_save_roundtrip_leaves_no_tmp_file(self):
        rt.save_state({'a': 1})
        with open(rt.STATE_FILE) as f:
            self.assertEqual(json.load(f), {'a': 1})
        self.assertEqual(temp_files(self.dir), [])

    def test_each_save_uses_a_temp_file_of_its_own(self):
        renamed = []
        real_replace = os.replace

        def replace(src, dst):
            renamed.append(src)
            real_replace(src, dst)
        with mock.patch.object(rt.os, 'replace', replace):
            rt.save_state({'n': 1})
            rt.save_state({'n': 2})
        self.assertEqual(len(set(renamed)), 2)
        self.assertNotIn(rt.STATE_FILE + '.tmp', renamed)
        self.assertEqual({os.path.dirname(p) for p in renamed}, {self.dir})  # same directory, so the rename is atomic

    def test_two_saves_at_the_same_moment_do_not_share_a_temp_file(self):
        first_written = rt.threading.Event()
        release = rt.threading.Event()
        real_dump = rt.json.dump
        dumps = []

        def dump(data, f, **kwargs):
            real_dump(data, f, **kwargs)
            dumps.append(data)
            if len(dumps) == 1:  # the first save stops here: written, not yet renamed into place
                first_written.set()
                release.wait(5)
        errors = []

        def first_save():
            try:
                rt.save_state({'who': 'first'})
            except BaseException as e:
                errors.append(e)
        with mock.patch.object(rt.json, 'dump', dump):
            thread = rt.threading.Thread(target=first_save)
            thread.start()
            self.assertTrue(first_written.wait(5))
            rt.save_state({'who': 'second'})
            release.set()
            thread.join(5)
        self.assertEqual(errors, [])
        with open(rt.STATE_FILE) as f:
            self.assertEqual(json.load(f), {'who': 'first'})  # the save that finished last wins, whole
        self.assertEqual(temp_files(self.dir), [])

    def test_a_failed_save_keeps_the_old_file_and_leaves_no_temp_file(self):
        rt.save_state({'a': 1})
        with self.assertRaises(TypeError):
            rt.save_state({'a': object()})  # not serialisable: fails half-way through the write
        with open(rt.STATE_FILE) as f:
            self.assertEqual(json.load(f), {'a': 1})
        self.assertEqual(temp_files(self.dir), [])



class TestWriteAtomic(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(__import__('shutil').rmtree, self.dir, ignore_errors=True)
        self.path = os.path.join(self.dir, 'f.dat')

    def test_text_is_written_whole_and_no_temp_file_stays(self):
        rt.write_atomic(self.path, lambda f: f.write('héllo'))
        with open(self.path, encoding='utf-8') as f:
            self.assertEqual(f.read(), 'héllo')
        self.assertEqual(os.listdir(self.dir), ['f.dat'])

    def test_bytes_are_written_when_asked(self):
        rt.write_atomic(self.path, lambda f: f.write(b'\x89PNG\x00'), binary=True)
        with open(self.path, 'rb') as f:
            self.assertEqual(f.read(), b'\x89PNG\x00')
        self.assertEqual(os.listdir(self.dir), ['f.dat'])

    def test_a_failed_write_leaves_the_old_file_and_no_temp_file(self):
        rt.write_atomic(self.path, lambda f: f.write('old'))

        def broken(f):
            f.write('half')
            raise OSError('disk full')
        with self.assertRaises(OSError):
            rt.write_atomic(self.path, broken)
        with open(self.path) as f:
            self.assertEqual(f.read(), 'old')
        self.assertEqual(os.listdir(self.dir), ['f.dat'])


class TestDiscoveryDismissalsInTheState(TmpConfigCase):
    def test_a_missing_or_broken_list_is_an_empty_one(self):
        self.assertEqual(rt.load_state()['media_discovery_seen'], [])
        for bad in ('x', 5, {'a': 1}, None):
            with open(rt.STATE_FILE, 'w') as f:
                json.dump({'media_discovery_seen': bad}, f)
            self.assertEqual(rt.load_state()['media_discovery_seen'], [], bad)

    def test_only_the_keys_that_are_text_are_kept(self):
        with open(rt.STATE_FILE, 'w') as f:
            json.dump({'media_discovery_seen': ['tmdb:1', 5, None, ['x'], 'imdb:tt1']}, f)
        self.assertEqual(rt.load_state()['media_discovery_seen'], ['tmdb:1', 'imdb:tt1'])

    def test_the_list_survives_a_save_and_a_load(self):
        state = rt.load_state()
        state['media_discovery_seen'] = ['tmdb:1']
        rt.save_state(state)
        self.assertEqual(rt.load_state()['media_discovery_seen'], ['tmdb:1'])

    def test_the_seen_records_of_the_old_format_become_the_new(self):
        with open(rt.STATE_FILE, 'w') as f:
            json.dump({'seen': {'a': 123.0, 'b': {'seen_at': 5, 'updated': 9}, 'c': 'junk'}}, f)
        self.assertEqual(rt.load_state()['seen'], {'a': {'seen_at': 123.0, 'updated': None}, 'b': {'seen_at': 5, 'updated': 9}})


class TestTheWatchList(TmpConfigCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(rt, 'MEDIA_FILE', os.path.join(self.dir, 'media.json'))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_media_file_without_one_has_an_empty_list(self):
        self.assertEqual(rt.load_media()['watch'], {})

    def test_the_list_survives_a_save_and_a_load(self):
        media = rt.load_media()
        media['watch']['imdb:tt1'] = rt.new_watch_entry({'title': 'X', 'type': 'series', 'imdb_id': 'tt1'}, 1000, year='2020')
        rt.save_media(media)
        self.assertEqual(rt.load_media()['watch'], {'imdb:tt1': dict(media['watch']['imdb:tt1'])})

    def test_a_broken_list_is_dropped_but_the_sources_are_kept(self):
        with open(rt.MEDIA_FILE, 'w') as f:
            json.dump({'sources': {'s': {'title': 'T'}}, 'watch': {'a': 'junk', 'b': {'title': 'B'}}}, f)
        media = rt.load_media()
        self.assertEqual(sorted(media['watch']), ['b'])
        self.assertEqual(media['sources']['s']['title'], 'T')

    def test_the_movie_flag_of_a_source_is_kept_only_when_it_is_true(self):
        with open(rt.MEDIA_FILE, 'w') as f:
            json.dump({'sources': {'a': {'movie': True}, 'b': {'movie': 'yes'}, 'c': {}}}, f)
        media = rt.load_media()
        self.assertEqual([media['sources'][k]['movie'] for k in 'abc'], [True, False, False])
        self.assertIs(rt.new_media_entry()['movie'], False)


class TestMediaState(TmpConfigCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(rt, 'MEDIA_FILE', os.path.join(self.dir, 'media.json'))
        patcher.start()
        self.addCleanup(patcher.stop)

    def write(self, data):
        with open(rt.MEDIA_FILE, 'w') as f:
            f.write(data if isinstance(data, str) else json.dumps(data))

    def test_a_missing_file_starts_empty(self):
        self.assertEqual(rt.load_media(), {'sources': {}, 'watch': {}})

    def test_garbage_starts_empty(self):
        for text in ('', '{not json', '[1, 2]', 'null', '{"sources": []}'):
            self.write(text)
            self.assertEqual(rt.load_media(), {'sources': {}, 'watch': {}}, text)

    def test_garbage_is_set_aside_not_overwritten_by_the_next_save(self):
        for text in ('{"sources": {"https://x.example/f": {"title": "T", "episodes": [', '[1, 2]', '{"sources": []}'):
            self.write(text)
            media = rt.load_media()
            rt.save_media(media)  # the next save, which used to destroy it
            with open(rt.MEDIA_FILE + '.corrupt') as f:
                self.assertEqual(f.read(), text)
            self.assertEqual(rt.load_media(), {'sources': {}, 'watch': {}})

    def test_a_file_that_is_not_text_is_set_aside_too(self):
        with open(rt.MEDIA_FILE, 'wb') as f:
            f.write(b'\xff\xfe\x00{')
        self.assertEqual(rt.load_media(), {'sources': {}, 'watch': {}})
        self.assertTrue(os.path.exists(rt.MEDIA_FILE + '.corrupt'))

    def test_a_missing_empty_or_good_file_is_not_set_aside(self):
        rt.load_media()
        self.write({})  # a JSON object with nothing in it holds nothing to lose
        rt.load_media()
        self.write({'sources': {'https://x.example/f': {'title': 'T'}}})
        self.assertEqual(rt.load_media()['sources']['https://x.example/f']['title'], 'T')
        self.assertFalse(os.path.exists(rt.MEDIA_FILE + '.corrupt'))
        self.assertTrue(os.path.exists(rt.MEDIA_FILE))

    def test_a_file_that_cannot_be_read_is_left_alone(self):
        os.mkdir(rt.MEDIA_FILE)
        self.assertEqual(rt.load_media(), {'sources': {}, 'watch': {}})
        self.assertTrue(os.path.isdir(rt.MEDIA_FILE))
        self.assertFalse(os.path.exists(rt.MEDIA_FILE + '.corrupt'))

    def test_what_is_saved_is_loaded(self):
        entry = rt.new_media_entry()
        entry.update(title='Show', baselined=True, watched=['a'], known=['a', 'b'], new=['b'],
                     episodes=[{'id': 'a', 'title': 'A'}, {'id': 'b', 'title': 'B'}],
                     files={'a': {'video': '/v/a.mp4', 'subs': ['/v/a.en.srt']}},
                     last_watched={'id': 'a', 'title': 'A', 'at': 1.5})
        rt.save_media({'sources': {'https://x.example/feed': entry}})
        self.assertEqual(rt.load_media(), {'sources': {'https://x.example/feed': entry}, 'watch': {}})
        self.assertFalse(os.path.exists(rt.MEDIA_FILE + '.tmp'))

    def test_a_new_entry_has_every_field_the_code_reads(self):
        self.assertEqual(rt.new_media_entry(), {'title': '', 'episodes': [], 'known': [], 'new': [], 'watched': [],
                                                'files': {}, 'last_watched': None, 'resume': {}, 'remove_at': None,
                                                'baselined': False, 'movie': False})

    def test_fields_of_the_wrong_type_are_repaired(self):
        self.write({'sources': {'https://x.example/f': {
            'title': 5, 'episodes': 'many', 'known': {'a': 1}, 'new': None, 'watched': 'a', 'files': [], 'last_watched': 'a',
            'baselined': 'yes'}}})
        self.assertEqual(rt.load_media()['sources']['https://x.example/f'], rt.new_media_entry())

    def test_wrong_items_inside_lists_are_dropped(self):
        self.write({'sources': {'https://x.example/f': {
            'episodes': [{'id': 'a'}, {'title': 'no id'}, 'text', {'id': 5}], 'watched': ['a', 5, None, 'b'],
            'files': {'a': {'video': '/v/a.mp4'}, 'b': {'subs': []}, 'c': 'x', 'd': {'video': 5}},
            'last_watched': {'title': 'no id'}}}})
        entry = rt.load_media()['sources']['https://x.example/f']
        self.assertEqual(entry['episodes'], [{'id': 'a'}])
        self.assertEqual(entry['watched'], ['a', 'b'])
        self.assertEqual(entry['files'], {'a': {'video': '/v/a.mp4'}})
        self.assertIsNone(entry['last_watched'])

    def test_a_source_that_is_not_an_object_is_dropped(self):
        self.write({'sources': {'https://x.example/f': 'x', 'https://y.example/f': {}}})
        self.assertEqual(list(rt.load_media()['sources']), ['https://y.example/f'])

    def test_the_state_file_is_untouched(self):
        rt.save_media({'sources': {}})
        self.assertFalse(os.path.exists(rt.STATE_FILE))

    def test_each_save_uses_a_temp_file_of_its_own(self):
        renamed = []
        real_replace = os.replace

        def replace(src, dst):
            renamed.append(src)
            real_replace(src, dst)
        with mock.patch.object(rt.os, 'replace', replace):
            rt.save_media({'sources': {}})
            rt.save_media({'sources': {}})
        self.assertEqual(len(set(renamed)), 2)
        self.assertNotIn(rt.MEDIA_FILE + '.tmp', renamed)

    def test_a_failed_save_keeps_the_old_file_and_leaves_no_temp_file(self):
        rt.save_media({'sources': {'https://x.example/f': {'title': 'T'}}})
        with self.assertRaises(TypeError):
            rt.save_media({'sources': {'https://x.example/f': object()}})
        self.assertEqual(rt.load_media()['sources']['https://x.example/f']['title'], 'T')
        self.assertEqual(temp_files(self.dir), [])


if __name__ == '__main__':
    unittest.main()


class TestMergeFeedCheck(unittest.TestCase):
    NOW = 10_000_000.0

    def item(self, eid):
        return {'id': eid, 'title': eid, 'link': '', 'feed_url': 'u'}

    def merge(self, state, **given):
        arguments = dict(newly_seen_ids=set(), last_checked={}, feed_links={}, new_items=[], later_items=[])
        arguments.update(given)
        return rt.merge_feed_check(state, self.NOW, **arguments)

    def test_new_items_go_in_front_of_the_unread_ones(self):
        state = {'unread': [self.item('old')]}
        new, later = self.merge(state, new_items=[self.item('a'), self.item('b')])
        self.assertEqual([e['id'] for e in state['unread']], ['a', 'b', 'old'])
        self.assertEqual(([e['id'] for e in new], later), (['a', 'b'], []))

    def test_an_item_already_unread_is_not_added_twice_and_is_not_reported(self):
        state = {'unread': [self.item('a')]}
        new, _later = self.merge(state, new_items=[self.item('a')])
        self.assertEqual(([e['id'] for e in state['unread']], new), (['a'], []))

    def test_an_update_of_an_item_already_unread_replaces_it_at_the_front_and_is_reported(self):
        state = {'unread': [self.item('x'), self.item('a'), self.item('y')]}
        new, _later = self.merge(state, new_items=[dict(self.item('a'), title='A (edited)', live=True)])
        self.assertEqual([e['id'] for e in state['unread']], ['a', 'x', 'y'])
        self.assertEqual((state['unread'][0]['title'], state['unread'][0]['live']), ('A (edited)', True))
        self.assertEqual([e['id'] for e in new], ['a'])

    def test_an_item_that_is_not_an_update_still_is_not_added_twice_next_to_one_that_is(self):
        state = {'unread': [self.item('a'), self.item('b')]}
        new, _later = self.merge(state, new_items=[self.item('a'), dict(self.item('b'), live=True), self.item('c')])
        self.assertEqual([e['id'] for e in state['unread']], ['b', 'c', 'a'])
        self.assertEqual([e['id'] for e in new], ['b', 'c'])

    def test_the_unread_list_keeps_the_newest_items_up_to_the_cap(self):
        state = {'unread': [self.item(f'old{i}') for i in range(rt.MAX_UNREAD_ITEMS)]}
        self.merge(state, new_items=[self.item('new1'), self.item('new2')])
        ids = [e['id'] for e in state['unread']]
        self.assertEqual((len(ids), ids[:2], ids[-1]), (rt.MAX_UNREAD_ITEMS, ['new1', 'new2'], f'old{rt.MAX_UNREAD_ITEMS - 3}'))

    def test_read_later_items_are_stamped_and_not_duplicated(self):
        state = {'read_later': [self.item('known')]}
        _new, later = self.merge(state, later_items=[self.item('known'), self.item('fresh')])
        self.assertEqual([e['id'] for e in later], ['fresh'])
        self.assertEqual([e['id'] for e in state['read_later']], ['fresh', 'known'])
        self.assertEqual(state['read_later'][0]['saved'], self.NOW)

    def test_ids_are_remembered_and_old_ones_forgotten(self):
        state = {'seen': {'stale': {'seen_at': self.NOW - rt.SEEN_RETENTION_SECONDS - 1, 'updated': None}, 'kept': {'seen_at': self.NOW - 5, 'updated': None}}}
        self.merge(state, newly_seen_ids={'a', 'kept'})
        self.assertEqual(state['seen']['kept']['seen_at'], self.NOW - 5)  # 'kept' keeps its first-seen time
        self.assertEqual(state['seen']['a']['seen_at'], self.NOW)
        self.assertNotIn('stale', state['seen'])

    def test_an_entry_seen_long_ago_but_updated_recently_is_not_pruned(self):
        # An entry seen 31 days ago but updated 1 hour ago must be kept,
        # otherwise it would resurface as new on the next feed check
        state = {'seen': {'old_but_updated': {
            'seen_at': self.NOW - rt.SEEN_RETENTION_SECONDS - 86400,  # 31 days ago
            'updated': self.NOW - 3600  # 1 hour ago
        }}}
        self.merge(state)
        self.assertIn('old_but_updated', state['seen'])
        # The seen_at should remain the original first-seen time
        self.assertEqual(state['seen']['old_but_updated']['seen_at'], self.NOW - rt.SEEN_RETENTION_SECONDS - 86400)

    def test_last_checked_times_are_merged_not_replaced(self):
        state = {'last_checked': {'x': 1, 'y': 2}}
        self.merge(state, last_checked={'y': 5, 'z': 6})
        self.assertEqual(state['last_checked'], {'x': 1, 'y': 5, 'z': 6})

    def test_feed_links_are_merged_and_a_damaged_value_is_replaced(self):
        state = {'feed_links': {'a': 'https://a.example', 'b': 'https://old.example'}}
        self.merge(state, feed_links={'b': 'https://b.example'})
        self.assertEqual(state['feed_links'], {'a': 'https://a.example', 'b': 'https://b.example'})
        damaged = {'feed_links': 'oops'}
        self.merge(damaged, feed_links={'b': 'https://b.example'})
        self.assertEqual(damaged['feed_links'], {'b': 'https://b.example'})

    def test_nothing_to_add_leaves_an_empty_state_with_just_the_bookkeeping(self):
        state = {}
        self.assertEqual(self.merge(state), ([], []))
        self.assertEqual(state, {'seen': {}, 'last_checked': {}})


class TestMediaEntryResumeAndRemoval(unittest.TestCase):
    def clean(self, **fields):
        return rt._clean_media_entry({'title': 'T', 'episodes': [], **fields})

    def test_a_new_entry_has_no_resume_points_and_no_removal_due(self):
        entry = rt.new_media_entry()
        self.assertEqual((entry['resume'], entry['remove_at']), ({}, None))

    def test_resume_points_are_kept_as_seconds_by_episode(self):
        self.assertEqual(self.clean(resume={'e1': 754, 'e2': 12.5})['resume'], {'e1': 754.0, 'e2': 12.5})

    def test_a_resume_point_that_is_not_a_positive_finite_number_is_dropped(self):
        resume = {'a': 0, 'b': -3, 'c': 'soon', 'd': None, 'e': True, 'f': float('inf'), 'g': float('nan'), 5: 10, 'ok': 60}
        self.assertEqual(self.clean(resume=resume)['resume'], {'ok': 60.0})

    def test_a_resume_value_of_the_wrong_shape_is_an_empty_one(self):
        for bad in (None, [], 'x', 7):
            self.assertEqual(self.clean(resume=bad)['resume'], {})

    def test_remove_at_is_a_time_or_none(self):
        self.assertEqual(self.clean(remove_at=1_793_000_000)['remove_at'], 1_793_000_000.0)
        for bad in (None, 'tomorrow', True, float('inf'), float('nan'), [1]):
            self.assertIsNone(self.clean(remove_at=bad)['remove_at'])

    def test_both_survive_a_save_and_a_load(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'media.json')
            with mock.patch.object(rt, 'MEDIA_FILE', path):
                rt.save_media({'sources': {'https://x.example/f': self.clean(resume={'e1': 90}, remove_at=5.0)}})
                entry = rt.load_media()['sources']['https://x.example/f']
        self.assertEqual((entry['resume'], entry['remove_at']), ({'e1': 90.0}, 5.0))
