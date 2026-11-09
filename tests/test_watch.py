import unittest
from types import SimpleNamespace
from unittest import mock

from facade import rt


def finder(name, result=None, error=None):
    return SimpleNamespace(name=name, module=SimpleNamespace(find=mock.Mock(side_effect=error, return_value=result)))


class TestAWatchRecord(unittest.TestCase):
    def test_it_is_made_from_a_discovery_item(self):
        item = {'title': 'Dune: Part Two', 'type': 'movie', 'imdb_id': 'tt15239678', 'url': 'https://www.imdb.com/title/tt15239678/'}
        self.assertEqual(rt.new_watch_entry(item, 1000, year='2024'), {
            'title': 'Dune: Part Two', 'year': '2024', 'type': 'movie', 'imdb_id': 'tt15239678',
            'added': 1000.0, 'checked': None, 'source': None})

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


class TestWhatIsStored(unittest.TestCase):
    GOOD = {'title': 'X', 'year': '2024', 'type': 'series', 'imdb_id': 'tt1', 'added': 5, 'checked': 6.5, 'source': 'p:u'}

    def test_a_good_record_comes_back_the_same(self):
        self.assertEqual(rt.clean_watch({'imdb:tt1': dict(self.GOOD)}),
                         {'imdb:tt1': {**self.GOOD, 'added': 5.0, 'checked': 6.5}})

    def test_every_field_is_present_and_of_the_right_type(self):
        clean = rt.clean_watch({'k': {'title': 'X', 'year': 2024, 'type': 'tv', 'imdb_id': 5, 'added': 'now',
                                      'checked': float('nan'), 'source': ''}})
        self.assertEqual(clean, {'k': {'title': 'X', 'year': '', 'type': 'movie', 'imdb_id': None,
                                       'added': 0.0, 'checked': None, 'source': None}})

    def test_what_is_not_a_record_is_dropped(self):
        self.assertEqual(rt.clean_watch({5: dict(self.GOOD), 'a': 'text', 'b': {'year': '2020'}, 'c': {'title': 7}}), {})
        for bad in (None, [], 'x', 5):
            self.assertEqual(rt.clean_watch(bad), {})


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


if __name__ == '__main__':
    unittest.main()
