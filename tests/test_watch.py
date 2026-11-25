import unittest
from types import SimpleNamespace
from unittest import mock

from facade import rt


def finder(name, result=None, error=None, **declared):
    """A plugin with a find(); `declared` are what it says about itself (FIND_PRIORITY, FIND_KINDS)."""
    return SimpleNamespace(name=name, module=SimpleNamespace(find=mock.Mock(side_effect=error, return_value=result), **declared))


class TestAWatchRecord(unittest.TestCase):
    def test_it_is_made_from_a_discovery_item(self):
        item = {'title': 'Dune: Part Two', 'type': 'movie', 'imdb_id': 'tt15239678', 'url': 'https://www.imdb.com/title/tt15239678/'}
        self.assertEqual(rt.new_watch_entry(item, 1000, year='2024'), {
            'title': 'Dune: Part Two', 'year': '2024', 'type': 'movie', 'imdb_id': 'tt15239678',
            'added': 1000.0, 'checked': None, 'source': None, 'start': None})

    def test_a_series_stays_one_and_anything_else_is_a_movie(self):
        self.assertEqual(rt.new_watch_entry({'title': 'S', 'type': 'series'}, 1)['type'], 'series')
        self.assertEqual(rt.new_watch_entry({'title': 'S', 'type': 'tv'}, 1)['type'], 'movie')
        self.assertEqual(rt.new_watch_entry({'title': 'S'}, 1)['type'], 'movie')

    def test_no_year_and_no_id_are_kept_as_such(self):
        entry = rt.new_watch_entry({'title': 'X'}, 1)
        self.assertEqual((entry['year'], entry['imdb_id']), ('', None))

    def test_it_is_searching_until_a_source_is_found(self):
        entry = rt.new_watch_entry({'title': 'X'}, 1)
        self.assertTrue(rt.is_searching(entry))
        entry['source'] = 'fsonline_one:https://f/x'
        self.assertFalse(rt.is_searching(entry))





class TestAStartPoint(unittest.TestCase):
    def test_a_start_is_a_season_and_an_episode_of_whole_numbers(self):
        self.assertEqual(rt.clean_start({'season': 2, 'episode': 3, 'x': 1}), {'season': 2, 'episode': 3})
        self.assertEqual(rt.clean_start({'season': 0, 'episode': 0}), {'season': 0, 'episode': 0})

    def test_anything_else_is_no_start(self):
        for bad in (None, 5, 'S02E03', [2, 3], {}, {'season': 2}, {'season': '2', 'episode': 3}, {'season': 2.5, 'episode': 3},
                    {'season': True, 'episode': 1}, {'season': -1, 'episode': 1}):
            self.assertIsNone(rt.clean_start(bad), bad)

    def test_it_is_written_as_the_episode_label_is(self):
        self.assertEqual(rt.start_text({'season': 3, 'episode': 5}), 'S03E05')
        self.assertEqual(rt.start_text({'season': 12, 'episode': 104}), 'S12E104')
        self.assertEqual(rt.start_text(None), '')

    def test_a_record_that_was_stored_without_one_has_none(self):
        self.assertIsNone(rt.clean_watch({'k': {'title': 'X'}})['k']['start'])
        self.assertIsNone(rt.clean_watch({'k': {'title': 'X', 'start': 'S01E01'}})['k']['start'])


class TestWhatIsStored(unittest.TestCase):
    GOOD = {'title': 'X', 'year': '2024', 'type': 'series', 'imdb_id': 'tt1', 'added': 5, 'checked': 6.5, 'source': 'p:u',
            'start': {'season': 2, 'episode': 3}}

    def test_a_good_record_comes_back_the_same(self):
        self.assertEqual(rt.clean_watch({'imdb:tt1': dict(self.GOOD)}),
                         {'imdb:tt1': {**self.GOOD, 'added': 5.0, 'checked': 6.5}})

    def test_every_field_is_present_and_of_the_right_type(self):
        clean = rt.clean_watch({'k': {'title': 'X', 'year': 2024, 'type': 'tv', 'imdb_id': 5, 'added': 'now',
                                      'checked': float('nan'), 'source': ''}})
        self.assertEqual(clean, {'k': {'title': 'X', 'year': '', 'type': 'movie', 'imdb_id': None,
                                       'added': 0.0, 'checked': None, 'source': None, 'start': None}})


    def test_what_is_not_a_record_is_dropped(self):
        self.assertEqual(rt.clean_watch({5: dict(self.GOOD), 'a': 'text', 'b': {'year': '2020'}, 'c': {'title': 7}}), {})
        for bad in (None, [], 'x', 5):
            self.assertEqual(rt.clean_watch(bad), {})


class TestWhatTheTrackTabLists(unittest.TestCase):
    def entry(self, kind, source):
        return {'title': 'T', 'type': kind, 'source': source}

    def test_a_title_still_being_looked_for_is_tracked_whatever_it_is(self):
        for kind in ('movie', 'series'):
            entry = self.entry(kind, None)
            self.assertTrue(rt.is_tracked(entry))
            self.assertFalse(rt.is_following(entry))

    def test_a_series_that_was_found_is_followed_and_tracked(self):
        entry = self.entry('series', 'fsonline_one:https://f/serial/x')
        self.assertTrue(rt.is_following(entry))
        self.assertTrue(rt.is_tracked(entry))

    def test_a_film_that_was_found_is_neither_it_is_in_the_media_list(self):
        entry = self.entry('movie', 'fsonline_one:https://f/film/x')
        self.assertFalse(rt.is_following(entry))
        self.assertFalse(rt.is_tracked(entry))

    def test_a_flag_an_older_version_stored_is_ignored_and_not_kept(self):
        clean = rt.clean_watch({'k': {'title': 'T', 'monitoring': True}})
        self.assertNotIn('monitoring', clean['k'])
        self.assertTrue(rt.is_searching(clean['k']))


class TestWhenToLook(unittest.TestCase):
    def test_a_title_never_looked_for_is_due_at_once(self):
        self.assertTrue(rt.search_due({'source': None, 'checked': None}, 1000, 3600))

    def test_one_looked_for_less_than_the_wait_ago_is_not(self):
        self.assertFalse(rt.search_due({'source': None, 'checked': 1000.0}, 1000 + 3599, 3600))
        self.assertTrue(rt.search_due({'source': None, 'checked': 1000.0}, 1000 + 3600, 3600))

    def test_one_that_has_its_source_is_never_looked_for_again(self):
        self.assertFalse(rt.search_due({'source': 'p:u', 'checked': None}, 10 ** 9, 3600))





class TestFindingATitle(unittest.TestCase):
    ENTRY = {'title': 'Dune: Part Two', 'year': '2024', 'type': 'movie', 'imdb_id': 'tt15239678'}

    def test_the_first_plugin_that_has_it_wins_and_is_given_what_is_known_of_the_title(self):
        a, b, c = finder('a', None), finder('b', 'https://b.example/dune'), finder('c', 'https://c.example/dune')
        self.assertEqual(rt.find_source([a, b, c], self.ENTRY), ('b', 'https://b.example/dune'))
        a.module.find.assert_called_once_with(title='Dune: Part Two', year='2024', imdb_id='tt15239678', kind='movie')
        c.module.find.assert_not_called()

    def test_an_unknown_year_is_none_not_an_empty_string(self):
        plugin = finder('a', None)
        rt.find_source([plugin], dict(self.ENTRY, year=''))
        self.assertIsNone(plugin.module.find.call_args.kwargs['year'])

    def test_nobody_having_it_is_none(self):
        self.assertIsNone(rt.find_source([finder('a'), finder('b')], self.ENTRY))
        self.assertIsNone(rt.find_source([], self.ENTRY))

    def test_a_plugin_that_fails_does_not_stop_the_next(self):
        self.assertEqual(rt.find_source([finder('a', error=OSError('down')), finder('b', 'https://b.example/d')], self.ENTRY),
                         ('b', 'https://b.example/d'))

    def test_only_an_http_address_counts_as_having_it(self):
        for answer in ('', 'dune', 'file:///etc/passwd', 'javascript:alert(1)', 5, True, ['https://x'], {'url': 'https://x'}):
            self.assertIsNone(rt.find_source([finder('a', answer)], self.ENTRY), answer)

    def test_the_source_line_is_the_plugin_name_and_the_address(self):
        self.assertEqual(rt.source_line('fsonline_one', 'https://f/film/dune-2024'), 'fsonline_one:https://f/film/dune-2024')

    SERIES = dict(ENTRY, type='series', title='Breaking Bad', year='2008', imdb_id='tt0903747')

    def test_the_plugins_are_asked_in_the_order_of_the_priority_they_declare_whatever_the_order_given(self):
        late = finder('aaa_late', 'https://late.example/x', FIND_PRIORITY=50)
        early = finder('zzz_early', 'https://early.example/x', FIND_PRIORITY=5)
        self.assertEqual(rt.find_source([late, early], self.ENTRY), ('zzz_early', 'https://early.example/x'))
        late.module.find.assert_not_called()

    def test_a_plugin_that_declares_nothing_comes_after_those_that_do_and_ties_go_by_name(self):
        plain_b, plain_a = finder('b', 'https://b.example/x'), finder('a', 'https://a.example/x')
        declared = finder('z', 'https://z.example/x', FIND_PRIORITY=10)
        self.assertEqual(rt.find_source([plain_b, plain_a, declared], self.ENTRY)[0], 'z')
        self.assertEqual(rt.find_source([plain_b, plain_a], self.ENTRY)[0], 'a')

    def test_when_the_first_has_none_the_next_is_tried(self):
        first = finder('one', None, FIND_PRIORITY=1)
        second = finder('two', 'https://two.example/x', FIND_PRIORITY=2)
        self.assertEqual(rt.find_source([second, first], self.ENTRY), ('two', 'https://two.example/x'))
        first.module.find.assert_called_once_with(title='Dune: Part Two', year='2024', imdb_id='tt15239678', kind='movie')

    def test_a_plugin_is_only_asked_for_the_kinds_it_declares(self):
        films_only = finder('films', 'https://films.example/x', FIND_PRIORITY=1, FIND_KINDS=('movie',))
        both = finder('both', 'https://both.example/x', FIND_PRIORITY=2)
        self.assertEqual(rt.find_source([films_only, both], self.SERIES), ('both', 'https://both.example/x'))
        films_only.module.find.assert_not_called()
        self.assertEqual(rt.find_source([films_only, both], self.ENTRY)[0], 'films')

    def test_when_no_plugin_that_handles_the_kind_has_it_nothing_else_is_tried(self):
        films_only = finder('films', 'https://films.example/x', FIND_KINDS=('movie',))
        self.assertIsNone(rt.find_source([films_only], self.SERIES))
        films_only.module.find.assert_not_called()

    def test_a_declaration_that_makes_no_sense_is_taken_as_none_made(self):
        odd = finder('odd', 'https://odd.example/x', FIND_PRIORITY='first', FIND_KINDS='movie')
        better = finder('better', 'https://better.example/x', FIND_PRIORITY=50)
        self.assertEqual(rt.find_source([odd, better], self.SERIES)[0], 'better')  # odd counts as 100, and is asked for any kind
        self.assertEqual(rt.find_source([odd], self.SERIES)[0], 'odd')

    def test_no_site_is_named_by_the_code_that_asks(self):
        import inspect
        source = inspect.getsource(rt.find_source) + inspect.getsource(rt.new_watch_entry)
        self.assertNotIn('sitefilme', source)
        self.assertNotIn('fsonline', source)

    def test_the_two_built_in_plugins_declare_what_they_are_asked_for(self):
        import ast
        import os
        folder = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'addons', 'media-plugins')
        declared = {}
        for name in ('sitefilme_com.py', 'fsonline_one.py'):
            tree = ast.parse(open(os.path.join(folder, name), encoding='utf-8').read())
            declared[name] = {t.id: ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                              for t in n.targets if isinstance(t, ast.Name) and t.id in ('FIND_PRIORITY', 'FIND_KINDS')}
        self.assertEqual(declared['sitefilme_com.py'], {'FIND_PRIORITY': 10, 'FIND_KINDS': ('movie',)})
        self.assertEqual(declared['fsonline_one.py'], {'FIND_PRIORITY': 20})


if __name__ == '__main__':
    unittest.main()
