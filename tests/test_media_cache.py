import json
import threading
import unittest
from datetime import datetime, timedelta, timezone

from facade import rt
from helpers import isolate_media_caches


def item(title, **extra):
    return {'title': title, 'type': 'movie', 'date': '2026-11-06', **extra}


class TestCacheKeys(unittest.TestCase):
    def test_an_id_wins_tmdb_before_imdb(self):
        self.assertEqual(rt._cache_key(item('X', tmdb_id='603', imdb_id='tt0133093')), 'tmdb:603')
        self.assertEqual(rt._cache_key(item('X', imdb_id='tt0133093')), 'imdb:tt0133093')

    def test_the_same_film_from_two_plugins_is_one_key(self):
        # as the two plugins write it: fsonline puts the year in the title and dates the item by
        # the sitemap; sitefilme has a year field, a title without it and today's date
        fsonline = item('Dune Part Two (2024)', date='2026-11-06')
        sitefilme = item('Dune Part Two', year='2024', date='2026-11-07')
        self.assertEqual(rt._cache_key(fsonline), rt._cache_key(sitefilme))

    def test_punctuation_accents_and_case_do_not_matter(self):
        self.assertEqual(rt._cache_key(item('Spider-Man: No Way Home (2021)')),
                         rt._cache_key(item('SPIDER MAN NO WAY HOME', year='2021')))
        self.assertEqual(rt._cache_key(item('Amélie', year='2001')), rt._cache_key(item('Amelie (2001)')))

    def test_the_date_it_was_found_on_is_not_the_year(self):
        found = item('Alien', date='2026-11-06')
        self.assertEqual(rt._cache_key(found), 'fallback:movie:alien:')
        self.assertNotEqual(rt._cache_key(found), rt._cache_key(item('Alien (1979)', date='2026-11-06')))

    def test_a_year_and_a_type_tell_films_apart(self):
        self.assertNotEqual(rt._cache_key(item('Dune (1984)')), rt._cache_key(item('Dune (2021)')))
        self.assertNotEqual(rt._cache_key(item('Fargo', type='movie')), rt._cache_key(item('Fargo', type='series')))

    def test_a_year_field_that_is_not_a_year_is_ignored(self):
        self.assertEqual(rt._cache_key(item('Alien (1979)', year='N/A')), rt._cache_key(item('Alien (1979)')))

    def test_a_title_with_its_year(self):
        self.assertEqual(rt.title_with_year(item('Dune Part Two', year='2024')), 'Dune Part Two (2024)')
        self.assertEqual(rt.title_with_year(item('Dune Part Two (2024)')), 'Dune Part Two (2024)')
        self.assertEqual(rt.title_with_year(item('Dune Part Two')), 'Dune Part Two')


class TestTheFile(unittest.TestCase):
    def setUp(self):
        self.folder = isolate_media_caches(self)

    def entry(self, **extra):
        return {'key': 'k', 'title': 'T', 'type': 'movie', 'urls': {'p': 'u'},
                'last_seen': datetime.now(timezone.utc).isoformat(), **extra}

    def test_what_is_saved_is_loaded(self):
        rt.save_media_cache({'a': self.entry()})
        self.assertEqual(list(rt.load_media_cache()), ['a'])

    def test_no_file_or_a_broken_one_is_an_empty_cache(self):
        self.assertEqual(rt.load_media_cache(), {})
        (self.folder / 'media_cache.json').write_text('{"half": ')
        self.assertEqual(rt.load_media_cache(), {})
        (self.folder / 'media_cache.json').write_text('[1, 2]')
        self.assertEqual(rt.load_media_cache(), {})

    def test_entries_not_seen_for_thirty_days_and_unusable_ones_are_dropped(self):
        old = (datetime.now(timezone.utc) - timedelta(days=31)).isoformat()
        (self.folder / 'media_cache.json').write_text(json.dumps({
            'fresh': self.entry(), 'old': self.entry(last_seen=old), 'nodate': {'urls': {}},
            'garbage': 'text', 'baddate': self.entry(last_seen='yesterday'), 'nourls': {'last_seen': self.entry()['last_seen']}}))
        self.assertEqual(list(rt.load_media_cache()), ['fresh'])

    def test_the_file_is_replaced_whole_with_no_temp_file_left(self):
        rt.save_media_cache({'a': self.entry()})
        rt.save_media_cache({'b': self.entry()})
        self.assertEqual(sorted(p.name for p in self.folder.iterdir()), ['media_cache.json'])
        self.assertEqual(list(json.loads((self.folder / 'media_cache.json').read_text())), ['b'])

    def test_only_the_last_seen_are_kept_beyond_the_limit(self):
        rt.MAX_CACHE_ENTRIES, keep = 3, rt.MAX_CACHE_ENTRIES
        self.addCleanup(setattr, rt, 'MAX_CACHE_ENTRIES', keep)
        now = datetime.now(timezone.utc)
        rt.save_media_cache({str(i): self.entry(last_seen=(now - timedelta(hours=i)).isoformat()) for i in range(6)})
        self.assertEqual(sorted(rt.load_media_cache()), ['0', '1', '2'])

    def test_changes_from_several_threads_are_all_kept(self):
        def add(n):
            rt.update_media_cache(lambda cache: cache.__setitem__(str(n), self.entry()))
        threads = [threading.Thread(target=add, args=(n,)) for n in range(25)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(rt.load_media_cache()), 25)


class TestEntries(unittest.TestCase):
    def test_an_item_makes_an_entry_with_its_plugins_url(self):
        cache = {}
        entry = rt.get_or_create_entry(cache, item('Dune (2024)', _plugin='fsonline', url='https://f/dune', genre=['SF']))
        self.assertEqual(list(cache), [entry['key']])
        self.assertEqual((entry['urls'], entry['year'], entry['genre']), ({'fsonline': 'https://f/dune'}, '2024', ['SF']))

    def test_the_same_film_from_another_plugin_adds_its_url_to_the_entry(self):
        cache = {}
        rt.get_or_create_entry(cache, item('Dune (2024)', _plugin='fsonline', url='https://f/dune'))
        rt.get_or_create_entry(cache, item('Dune', year='2024', _plugin='sitefilme', url='https://s/1', image='poster.jpg'))
        self.assertEqual(len(cache), 1)
        entry = next(iter(cache.values()))
        self.assertEqual(entry['urls'], {'fsonline': 'https://f/dune', 'sitefilme': 'https://s/1'})
        self.assertEqual(entry['image'], 'poster.jpg')  # what the first lacked

    def test_the_quality_is_kept_and_the_newest_word_counts(self):
        cache = {}
        rt.get_or_create_entry(cache, item('A (2020)', quality='cam', _plugin='p', url='u'))
        rt.get_or_create_entry(cache, item('A (2020)', _plugin='p', url='u'))  # a sighting that says nothing keeps it
        self.assertEqual(rt.get_all_cached_items(cache)[0]['quality'], 'cam')
        rt.get_or_create_entry(cache, item('A (2020)', quality='hd', _plugin='p', url='u'))
        self.assertEqual(rt.get_all_cached_items(cache)[0]['quality'], 'hd')

    def test_what_an_entry_has_is_not_overwritten(self):
        cache = {}
        rt.get_or_create_entry(cache, item('A (2020)', image='one.jpg', _plugin='p', url='u'))
        rt.get_or_create_entry(cache, item('A (2020)', image='two.jpg', _plugin='q', url='v'))
        self.assertEqual(next(iter(cache.values()))['image'], 'one.jpg')

    def test_new_items_leave_out_what_was_dismissed_but_still_file_it(self):
        cache, seen = {}, set()
        a, b = item('A (2020)', url='ua', _plugin='p'), item('B (2021)', url='ub', _plugin='p')
        rt.mark_seen(seen, a)
        self.assertEqual(rt.get_new_items(cache, [a, b], seen), [b])
        self.assertEqual(len(cache), 2)
        self.assertTrue(rt.is_seen(seen, a))
        self.assertFalse(rt.is_seen(seen, b))

    def test_the_list_is_newest_first_and_survives_a_thin_entry(self):
        cache = {'x': {'key': 'x', 'title': 'Old', 'urls': {'p': 'u1'}, 'date': '2026-01-01', 'first_seen': ''},
                 'y': {'key': 'y', 'title': 'New', 'urls': {}, 'date': '2026-11-01', 'first_seen': ''}}
        items = rt.get_all_cached_items(cache)
        self.assertEqual([i['title'] for i in items], ['New', 'Old'])
        self.assertEqual(items[0]['id'], 'y')  # no url: the key stands in
        self.assertEqual(items[1]['id'], 'u1')
        self.assertEqual(items[1]['_cache_key'], 'x')


class TestGivingEntriesTheirIds(unittest.TestCase):
    def cache_of_one(self, **extra):
        cache = {}
        entry = rt.get_or_create_entry(cache, item('Dune Part Two (2024)', _plugin='fsonline', url='https://f/d', **extra))
        return cache, entry['key']

    def test_an_entry_with_ids_known_is_re_keyed(self):
        cache, old = self.cache_of_one()
        cache, seen, moved = rt.sync_metadata_ids(cache, set(), lambda e: {'tmdb_id': '693134', 'imdb_id': 'tt15239678'})
        self.assertEqual((list(cache), moved), (['tmdb:693134'], 1))
        self.assertEqual((cache['tmdb:693134']['key'], cache['tmdb:693134']['imdb_id']), ('tmdb:693134', 'tt15239678'))
        self.assertNotIn(old, cache)

    def test_the_imdb_id_serves_when_there_is_no_tmdb_id(self):
        cache, _ = self.cache_of_one()
        rt.sync_metadata_ids(cache, set(), lambda e: {'imdb_id': 'tt15239678'})
        self.assertEqual(list(cache), ['imdb:tt15239678'])

    def test_a_dismissal_follows_the_entry(self):
        cache, old = self.cache_of_one()
        seen = {old, 'other'}
        rt.sync_metadata_ids(cache, seen, lambda e: {'tmdb_id': '1'})
        self.assertEqual(seen, {'tmdb:1', 'other'})

    def test_two_entries_that_come_to_share_an_id_become_one_with_both_urls(self):
        cache = {}
        rt.get_or_create_entry(cache, item('Dune Part Two (2024)', _plugin='fsonline', url='https://f/d'))
        rt.get_or_create_entry(cache, item('Dune: Part Two', year='2023', _plugin='sitefilme', url='https://s/1'))  # another year: its own entry
        self.assertEqual(len(cache), 2)
        _, _, moved = rt.sync_metadata_ids(cache, set(), lambda e: {'tmdb_id': '693134'})
        self.assertEqual((list(cache), moved), (['tmdb:693134'], 2))
        self.assertEqual(cache['tmdb:693134']['urls'], {'fsonline': 'https://f/d', 'sitefilme': 'https://s/1'})

    def test_entries_without_an_answer_or_with_ids_are_left_alone(self):
        cache, old = self.cache_of_one()
        rt.get_or_create_entry(cache, item('Has Id', tmdb_id='5', _plugin='p', url='u'))
        asked = []
        _, _, moved = rt.sync_metadata_ids(cache, set(), lambda e: asked.append(e['title']))
        self.assertEqual((moved, sorted(cache)), (0, sorted([old, 'tmdb:5'])))
        self.assertEqual(asked, ['Dune Part Two (2024)'])  # only the one without an id was asked about

    def test_metadata_without_ids_changes_nothing(self):
        cache, old = self.cache_of_one()
        self.assertEqual(rt.sync_metadata_ids(cache, set(), lambda e: {'title': 'Dune'})[2], 0)
        self.assertEqual(list(cache), [old])


if __name__ == '__main__':
    unittest.main()
