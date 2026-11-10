import io
import json
import os
import threading
import time
import unittest
import urllib.error
from unittest import mock

from facade import rt
from helpers import isolate_media_caches

TMDB_HIT = {'results': [{'id': 603, 'title': 'The Matrix', 'release_date': '1999-03-30', 'overview': 'Neo.',
                         'vote_average': 8.2, 'vote_count': 100, 'popularity': 50.0, 'original_language': 'en',
                         'poster_path': '/p.jpg', 'backdrop_path': '/b.jpg'}]}
TMDB_DETAILS = {'genres': [{'name': 'Action'}, {'name': 'Sci-Fi'}], 'runtime': 136, 'status': 'Released',
                'tagline': 'Free your mind.', 'homepage': '', 'imdb_id': 'tt0133093',
                'production_companies': [{'name': 'Warner Bros.'}], 'production_countries': [{'name': 'United States'}],
                'spoken_languages': [{'english_name': 'English'}],
                'credits': {'crew': [{'job': 'Director', 'name': 'Lana Wachowski'}, {'job': 'Gaffer', 'name': 'X'}],
                            'cast': [{'name': f'Actor {i}'} for i in range(12)]}}
OMDB_HIT = {'Response': 'True', 'imdbID': 'tt0133093', 'Title': 'The Matrix', 'Year': '1999', 'Type': 'movie',
            'imdbRating': '8.7', 'imdbVotes': '2,000,000', 'Metascore': '73', 'Director': 'The Wachowskis',
            'Actors': 'Keanu Reeves', 'Awards': 'Won 4 Oscars', 'Plot': 'A hacker.', 'Genre': 'Action',
            'Poster': 'N/A', 'totalSeasons': 'N/A', 'BoxOffice': '$172,076,928', 'Ratings': [{'Source': 'IMDb', 'Value': '8.7/10'}]}


class FakeNet:
    """Stands in for urlopen: `routes` is a list of (text that is in the address, reply),
    a reply being a dict (sent as JSON), bytes, or an exception to raise."""

    def __init__(self, *routes):
        self.routes = list(routes)
        self.requests = []

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        for part, reply in self.routes:
            if part in request.full_url:
                if isinstance(reply, Exception):
                    raise reply
                body = reply if isinstance(reply, bytes) else json.dumps(reply).encode()
                response = mock.MagicMock()
                response.__enter__.return_value = response
                response.read.side_effect = lambda n=-1: body[:n] if n and n > 0 else body
                return response
        raise urllib.error.URLError('no route for ' + request.full_url)

    def urls(self, part=''):
        return [r.full_url for r in self.requests if part in r.full_url]


def http_error(code, retry_after=None):
    headers = {'Retry-After': str(retry_after)} if retry_after is not None else {}
    return urllib.error.HTTPError('https://x', code, 'err', headers, io.BytesIO(b''))


class MetadataCase(unittest.TestCase):
    def setUp(self):
        self.folder = isolate_media_caches(self)
        self.logs = []
        for patcher in (mock.patch.object(rt, '_log', side_effect=self.logs.append),
                        mock.patch.object(rt, '_tmdb_rate_limit_until', 0.0)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def net(self, *routes):
        fake = FakeNet(*routes)
        patcher = mock.patch.object(rt.urllib.request, 'urlopen', fake)
        patcher.start()
        self.addCleanup(patcher.stop)
        return fake


class TestTheCacheFiles(MetadataCase):
    def test_what_is_stored_comes_back_and_the_file_is_replaced_whole(self):
        rt._update_metadata_cache(lambda c: c.__setitem__('movie:a:2020', {'title': 'A', 'cached_at': time.time()}))
        self.assertEqual(rt._load_metadata_cache()['movie:a:2020']['title'], 'A')
        self.assertEqual(sorted(p.name for p in self.folder.iterdir()), ['metadata_cache.json'])

    def test_expired_entries_go_and_a_negative_one_goes_sooner(self):
        now = time.time()
        day = 86400
        (self.folder / 'metadata_cache.json').write_text(json.dumps({
            'fresh': {'cached_at': now - 29 * day}, 'stale': {'cached_at': now - 31 * day},
            'neg-fresh': {'negative': True, 'cached_at': now - 6 * day}, 'neg-stale': {'negative': True, 'cached_at': now - 8 * day},
            'junk': 'text'}))
        self.assertEqual(sorted(rt._load_metadata_cache()), ['fresh', 'neg-fresh'])

    def test_a_broken_file_is_an_empty_cache_that_can_be_written_again(self):
        (self.folder / 'metadata_cache.json').write_text('{"half": ')
        self.assertEqual(rt._load_metadata_cache(), {})
        rt._update_metadata_cache(lambda c: c.__setitem__('k', {'cached_at': time.time()}))
        self.assertEqual(list(rt._load_metadata_cache()), ['k'])

    def test_an_unchanged_file_is_not_read_again_and_a_changed_one_is(self):
        rt._update_metadata_cache(lambda c: c.__setitem__('k', {'cached_at': time.time()}))
        with mock.patch.object(rt.json, 'load', wraps=rt.json.load) as read:
            rt._load_metadata_cache()
            rt._load_metadata_cache()
            self.assertEqual(read.call_count, 0)  # what this process wrote is already in hand
            path = self.folder / 'metadata_cache.json'
            path.write_text(json.dumps({'other': {'cached_at': time.time()}}))
            os.utime(path, ns=(1, 1))  # a change, whatever the clock's grain
            self.assertEqual(list(rt._load_metadata_cache()), ['other'])
            self.assertEqual(read.call_count, 1)

    def test_changes_from_several_threads_are_all_kept(self):
        def add(n):
            rt._update_metadata_cache(lambda c: c.__setitem__(f'k{n}', {'cached_at': time.time()}))
        threads = [threading.Thread(target=add, args=(n,)) for n in range(25)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(rt._load_metadata_cache()), 25)


class TestLookingATitleUp(MetadataCase):
    def tmdb_routes(self):
        return [('/search/movie', TMDB_HIT), ('/movie/603', TMDB_DETAILS)]

    def test_no_key_means_no_request_and_nothing_remembered(self):
        net = self.net()
        self.assertIsNone(rt.get_metadata('The Matrix', 1999))
        self.assertEqual(net.requests, [])
        self.assertEqual(rt._load_metadata_cache(), {})  # a key added later is tried at once

    def test_tmdb_search_and_details_make_the_record(self):
        net = self.net(*self.tmdb_routes(), ('image.tmdb.org', b'img'))
        meta = rt.get_metadata('The Matrix (1999)', None, 'movie', tmdb_key='TOKEN')
        self.assertEqual((meta['title'], meta['year'], meta['tmdb_id'], meta['imdb_id']), ('The Matrix', '1999', '603', 'tt0133093'))
        self.assertEqual((meta['genre'], meta['runtime'], meta['director']), ('Action, Sci-Fi', '136 min', 'Lana Wachowski'))
        self.assertEqual(len(meta['actors'].split(', ')), 10)
        self.assertEqual(len(net.urls('api.themoviedb.org')), 2)  # the credits and ids ride along with the details
        self.assertIn('append_to_response=credits%2Cexternal_ids', net.urls()[1])
        self.assertEqual(net.requests[0].get_header('Authorization'), 'Bearer TOKEN')
        self.assertEqual(net.requests[0].get_header('User-agent'), 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36')

    def test_the_answer_is_cached_by_title_and_by_both_ids_and_asked_for_once(self):
        net = self.net(*self.tmdb_routes())
        rt.get_metadata('The Matrix', 1999, 'movie', tmdb_key='T')
        cache = rt._load_metadata_cache()
        self.assertTrue({'movie:the matrix:1999', 'tmdb:603', 'imdb:tt0133093'} <= set(cache))
        before = len(net.requests)
        self.assertEqual(rt.get_metadata('The Matrix', 1999, 'movie', tmdb_key='T')['tmdb_id'], '603')
        self.assertEqual(len(net.requests), before)
        self.assertEqual(rt.get_cached_metadata('whatever', imdb_id='tt0133093')['tmdb_id'], '603')
        self.assertEqual(rt.get_cached_metadata('The Matrix (1999)')['tmdb_id'], '603')
        self.assertEqual(rt.get_cached_metadata('The Matrix', url='https://f.example/film/the-matrix-1999-online/')['tmdb_id'], '603')
        self.assertIsNone(rt.get_cached_metadata('The Matrix', media_type='series'))

    def test_a_failed_lookup_is_not_remembered_as_not_found(self):
        # the network down, a bad key, a server error: none says the title does not exist
        for failure in (urllib.error.URLError('down'), http_error(401), http_error(500), b'not json', TimeoutError('slow')):
            self.net(('/search/movie', failure))
            self.assertIsNone(rt.get_metadata('The Matrix', 1999, 'movie', tmdb_key='T'), failure)
            self.assertEqual(rt._load_metadata_cache(), {}, failure)

    def test_a_rate_limit_is_waited_out_before_another_request_goes(self):
        net = self.net(('/search/movie', http_error(429, retry_after=30)))
        self.assertIsNone(rt.get_metadata('A', 2001, 'movie', tmdb_key='T'))
        self.assertGreater(rt._tmdb_rate_limit_until, time.time() + 25)
        self.assertIsNone(rt.get_metadata('B', 2002, 'movie', tmdb_key='T'))
        self.assertEqual(len(net.requests), 1)
        self.assertEqual(rt._load_metadata_cache(), {})

    def test_a_title_tmdb_does_not_know_is_remembered_for_a_week(self):
        net = self.net(('/search/movie', {'results': []}))
        self.assertIsNone(rt.get_metadata('Nothing Here', 2030, 'movie', tmdb_key='T'))
        self.assertIsNone(rt.get_metadata('Nothing Here', 2030, 'movie', tmdb_key='T'))
        self.assertEqual(len(net.requests), 1)
        self.assertIn('neg:nothing here:2030:movie', rt._load_metadata_cache())

    def test_a_series_is_searched_as_tv(self):
        net = self.net(('/search/tv', {'results': [{'id': 9, 'name': 'Show', 'first_air_date': '2020-01-01'}]}),
                       ('/tv/9', {'genres': [], 'episode_run_time': [45], 'number_of_seasons': 3,
                                  'number_of_episodes': 30, 'external_ids': {'imdb_id': 'tt9'}}))
        meta = rt.get_metadata('Show', 2020, 'series', tmdb_key='T')
        self.assertTrue(net.urls()[0].startswith('https://api.themoviedb.org/3/search/tv?'))
        self.assertEqual((meta['runtime'], meta['total_seasons'], meta['total_episodes'], meta['imdb_id']), ('45 min', 3, 30, 'tt9'))

    def test_omdb_alone_answers_when_there_is_no_tmdb_key(self):
        net = self.net(('omdbapi.com', OMDB_HIT))
        meta = rt.get_metadata('The Matrix', 1999, 'movie', omdb_key='SECRET')
        self.assertEqual((meta['imdb_rating'], meta['metascore'], meta['imdb_id'], meta['poster'], meta['total_seasons']),
                         (8.7, 73, 'tt0133093', None, None))  # "N/A" is nothing
        self.assertTrue(net.urls()[0].startswith('https://www.omdbapi.com/?'))

    def test_omdb_adds_the_imdb_rating_to_a_tmdb_record_but_tmdb_keeps_the_cast_and_director(self):
        net = self.net(*self.tmdb_routes(), ('omdbapi.com', OMDB_HIT), ('image.tmdb.org', b'img'))
        meta = rt.get_metadata('The Matrix', 1999, 'movie', omdb_key='O', tmdb_key='T')
        self.assertEqual((meta['imdb_rating'], meta['metascore'], meta['awards'], meta['box_office']),
                         (8.7, 73, 'Won 4 Oscars', '$172,076,928'))
        self.assertEqual((meta['director'], meta['tmdb_id']), ('Lana Wachowski', '603'))
        self.assertIn('i=tt0133093', net.urls('omdbapi.com')[0])

    def test_omdb_failing_keeps_what_tmdb_found(self):
        self.net(*self.tmdb_routes(), ('omdbapi.com', urllib.error.URLError('down')))
        meta = rt.get_metadata('The Matrix', 1999, 'movie', omdb_key='O', tmdb_key='T')
        self.assertEqual(meta['tmdb_id'], '603')
        self.assertIsNone(meta.get('imdb_rating'))

    def test_omdb_says_not_found_or_a_bad_key_in_the_same_200(self):
        self.net(('omdbapi.com', {'Response': 'False', 'Error': 'Movie not found!'}))
        self.assertIsNone(rt.get_metadata('Nope', 2001, 'movie', omdb_key='O'))
        self.assertIn('neg:nope:2001:movie', rt._load_metadata_cache())  # that is an answer
        self.net(('omdbapi.com', {'Response': 'False', 'Error': 'Invalid API key!'}))
        self.assertIsNone(rt.get_metadata('Other', 2002, 'movie', omdb_key='O'))
        self.assertNotIn('neg:other:2002:movie', rt._load_metadata_cache())  # that is not

    def test_tmdb_down_falls_back_to_omdb_and_if_both_fail_nothing_is_remembered(self):
        self.net(('/search/movie', urllib.error.URLError('down')), ('omdbapi.com', OMDB_HIT))
        self.assertEqual(rt.get_metadata('The Matrix', 1999, 'movie', omdb_key='O', tmdb_key='T')['imdb_id'], 'tt0133093')
        rt._update_metadata_cache(lambda c: c.clear())
        self.net(('/search/movie', urllib.error.URLError('down')), ('omdbapi.com', urllib.error.URLError('down')))
        self.assertIsNone(rt.get_metadata('The Matrix', 1999, 'movie', omdb_key='O', tmdb_key='T'))
        self.assertEqual(rt._load_metadata_cache(), {})

    def test_the_keys_are_never_logged(self):
        self.net(('/search/movie', urllib.error.URLError('down')), ('omdbapi.com', http_error(401)))
        rt.get_metadata('A', 2001, 'movie', omdb_key='OMDB-SECRET', tmdb_key='TMDB-SECRET')
        self.assertTrue(self.logs)
        self.assertFalse([m for m in self.logs if 'SECRET' in m])

    def test_a_year_in_the_title_is_used(self):
        net = self.net(*self.tmdb_routes())
        rt.get_metadata('The Matrix (1999)', None, 'movie', tmdb_key='T')
        self.assertIn('year=1999', net.urls()[0])
        self.assertIn('query=The+Matrix&', net.urls()[0])


class TestRefreshing(MetadataCase):
    def test_without_a_key_nothing_is_asked(self):
        net = self.net()
        self.assertEqual(rt.refresh_metadata_cache(['A (2000)'], omdb_key='', tmdb_key=''), 0)
        self.assertEqual(net.requests, [])

    def test_only_titles_without_an_answer_are_looked_up_the_ones_with_a_year_first(self):
        rt._update_metadata_cache(lambda c: (c.__setitem__('movie:cached:2000', {'cached_at': time.time()}),
                                             c.__setitem__('neg:gone:2001:movie', {'negative': True, 'cached_at': time.time()})))
        asked = []

        def fake(title, year, mtype, omdb_key, tmdb_key, imdb_id=None):
            asked.append((title, year))
            return {'title': title}
        with mock.patch.object(rt, 'get_metadata', side_effect=fake):
            found = rt.refresh_metadata_cache(['No Year', 'Cached (2000)', 'Gone (2001)', 'New (2002)'], 'movie', tmdb_key='T')
        self.assertEqual(asked, [('New', '2002'), ('No Year', None)])
        self.assertEqual(found, 2)

    def test_a_cycle_is_at_most_so_many_lookups(self):
        with mock.patch.object(rt, 'get_metadata', return_value=None) as get:
            rt.refresh_metadata_cache([f'Title {i} (2000)' for i in range(75)], 'movie', tmdb_key='T')
        self.assertEqual(get.call_count, rt.MAX_API_CALLS_PER_CYCLE)

    def test_a_rate_limit_ends_the_cycle(self):
        calls = []

        def limited(title, *a):
            calls.append(title)
            rt._tmdb_rate_limit_until = time.time() + 60
        with mock.patch.object(rt, 'get_metadata', side_effect=limited):
            rt.refresh_metadata_cache(['A (2000)', 'B (2001)', 'C (2002)'], 'movie', tmdb_key='T')
        self.assertEqual(len(calls), 1)

    def test_the_series_and_movie_types_go_with_their_titles(self):
        types = []
        with mock.patch.object(rt, 'get_metadata', side_effect=lambda t, y, m, *a, **k: types.append(m)):
            rt.refresh_metadata_cache(['A (2000)', 'B (2001)'], ['movie', 'series'], tmdb_key='T')
        self.assertEqual(sorted(types), ['movie', 'series'])


class TestLookingATitleUpByItsImdbId(MetadataCase):
    CHART_OMDB = dict(OMDB_HIT, imdbID='tt15239678', Title='Dune: Part Two', Year='2024', Poster='https://m.media-amazon.com/p.jpg')

    def test_an_imdb_id_is_one_exact_request_to_omdb_and_nothing_else(self):
        net = self.net(('omdbapi.com', self.CHART_OMDB), ('media-amazon.com', b'img'))
        meta = rt.get_metadata('Dune: Part Two', None, 'movie', omdb_key='K', imdb_id='tt15239678')
        self.assertEqual((meta['imdb_id'], meta['year'], meta['imdb_rating']), ('tt15239678', '2024', 8.7))
        omdb = net.urls('omdbapi.com')
        self.assertEqual(len(omdb), 1)
        self.assertIn('i=tt15239678', omdb[0])
        self.assertNotIn('t=Dune', omdb[0])

    def test_it_is_cached_by_the_id_and_asked_for_once(self):
        net = self.net(('omdbapi.com', self.CHART_OMDB), ('media-amazon.com', b'img'))
        rt.get_metadata('Dune: Part Two', None, 'movie', omdb_key='K', imdb_id='tt15239678')
        rt.get_metadata('Dune: Part Two', None, 'movie', omdb_key='K', imdb_id='tt15239678')
        self.assertEqual(len(net.urls('omdbapi.com')), 1)
        self.assertEqual(rt.get_cached_metadata('whatever', imdb_id='tt15239678')['title'], 'Dune: Part Two')
        self.assertTrue(rt.get_cached_poster('x', imdb_id='tt15239678'))

    def test_a_title_without_a_year_is_not_filed_under_its_bare_name(self):
        # two films of the same name must not share an entry: only the id (and the year the answer gave) are keys
        self.net(('omdbapi.com', self.CHART_OMDB), ('media-amazon.com', b'img'))
        rt.get_metadata('Dune', None, 'movie', omdb_key='K', imdb_id='tt15239678')
        cache = rt._load_metadata_cache()
        self.assertIn('imdb:tt15239678', cache)
        self.assertIn('movie:dune:2024', cache)
        self.assertNotIn('movie:dune:unknown', cache)

    def test_an_id_omdb_does_not_know_is_remembered_by_the_id_and_not_asked_about_by_name(self):
        net = self.net(('omdbapi.com', {'Response': 'False', 'Error': 'Incorrect IMDb ID.'}))
        # "Incorrect IMDb ID" is OMDb saying it has nothing under that id
        self.assertIsNone(rt.get_metadata('Dune', None, 'movie', omdb_key='K', imdb_id='tt0000000'))
        self.assertIsNone(rt.get_metadata('Dune', None, 'movie', omdb_key='K', imdb_id='tt0000000'))
        self.assertEqual(len(net.requests), 1)
        self.assertIn('neg:imdb:tt0000000', rt._load_metadata_cache())

    def test_a_failure_with_an_id_is_not_remembered_and_does_not_fall_back_to_a_name_search(self):
        net = self.net(('omdbapi.com', urllib.error.URLError('down')))
        self.assertIsNone(rt.get_metadata('Dune', None, 'movie', omdb_key='K', imdb_id='tt15239678'))
        self.assertEqual(rt._load_metadata_cache(), {})
        self.assertEqual(len(net.requests), 1)  # the budget is not spent on a search by name

    def test_refresh_asks_by_id_first_and_passes_the_ids_along(self):
        calls = []
        with mock.patch.object(rt, 'get_metadata', side_effect=lambda t, y, m, ok, tk, imdb_id=None: calls.append((t, imdb_id))):
            rt.refresh_metadata_cache(['No Id (2020)', 'Has Id'], 'movie', omdb_key='K', tmdb_key='', imdb_ids=['', 'tt1'])
        self.assertEqual(calls, [('Has Id', 'tt1'), ('No Id', None)])

    def test_titles_already_cached_by_id_are_not_asked_again(self):
        rt._update_metadata_cache(lambda c: c.__setitem__('imdb:tt1', {'cached_at': time.time()}))
        with mock.patch.object(rt, 'get_metadata') as get:
            rt.refresh_metadata_cache(['Has Id'], 'movie', omdb_key='K', tmdb_key='', imdb_ids=['tt1'])
        get.assert_not_called()


class TestOmdbDailyLimit(MetadataCase):
    def setUp(self):
        super().setUp()
        self.limit = 3
        self.day = '2026-11-08'
        for patcher in (mock.patch.object(rt, 'omdb_daily_limit', side_effect=lambda: self.limit),
                        mock.patch.object(rt, '_omdb_day', side_effect=lambda: self.day)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def ask(self, net, n=1):
        for i in range(n):
            rt._omdb_get('K', t=f'x{i}')

    def test_every_request_is_counted_and_the_limit_stops_the_next_without_a_request(self):
        net = self.net(('omdbapi.com', OMDB_HIT))
        self.ask(net, 3)
        self.assertEqual(rt.omdb_requests_left(), 0)
        with self.assertRaises(rt.LookupFailed):
            self.ask(net)
        self.assertEqual(len(net.requests), 3)

    def test_a_failed_request_counts_too(self):
        net = self.net(('omdbapi.com', urllib.error.URLError('down')))
        with self.assertRaises(rt.LookupFailed):
            self.ask(net)
        self.assertEqual(rt.omdb_requests_left(), 2)

    def test_the_count_survives_a_restart_and_a_new_day_starts_from_nothing(self):
        net = self.net(('omdbapi.com', OMDB_HIT))
        self.ask(net, 2)
        rt._memo.clear()  # a new process: only the file is left
        self.assertEqual(rt.omdb_requests_left(), 1)
        self.day = '2026-11-09'
        self.assertEqual(rt.omdb_requests_left(), 3)
        self.ask(net, 3)
        self.assertEqual(len(net.requests), 5)

    def test_the_limit_comes_from_the_setting(self):
        self.limit = 0
        net = self.net(('omdbapi.com', OMDB_HIT))
        with self.assertRaises(rt.LookupFailed):
            self.ask(net)
        self.assertEqual(net.requests, [])
        self.limit = 5
        self.ask(net, 5)
        self.assertEqual(rt.omdb_requests_left(), 0)

    def test_omdb_saying_the_limit_is_reached_ends_the_day_whatever_the_count_was(self):
        net = self.net(('omdbapi.com', {'Response': 'False', 'Error': 'Request limit reached!'}))
        with self.assertRaises(rt.LookupFailed):
            self.ask(net)
        self.assertEqual(rt.omdb_requests_left(), 0)
        with self.assertRaises(rt.LookupFailed):
            self.ask(net)
        self.assertEqual(len(net.requests), 1)

    def test_a_title_looked_up_when_the_limit_is_reached_is_not_remembered_as_unknown(self):
        self.limit = 0
        self.net(('omdbapi.com', OMDB_HIT))
        self.assertIsNone(rt.get_metadata('A', 2001, 'movie', omdb_key='K'))
        self.assertEqual(rt._load_metadata_cache(), {})

    def test_a_refresh_with_only_omdb_stops_when_the_limit_is_reached(self):
        self.limit = 0
        with mock.patch.object(rt, 'get_metadata') as get:
            rt.refresh_metadata_cache(['A (2001)', 'B (2002)'], 'movie', omdb_key='K', tmdb_key='')
        get.assert_not_called()

    def test_the_quota_file_is_replaced_whole(self):
        net = self.net(('omdbapi.com', OMDB_HIT))
        self.ask(net, 2)
        self.assertEqual(json.loads((self.folder / 'omdb_quota.json').read_text()), {'day': '2026-11-08', 'used': 2})
        self.assertEqual(sorted(p.name for p in self.folder.iterdir() if p.is_file()), ['omdb_quota.json'])


class TestPosters(MetadataCase):
    def test_a_poster_is_fetched_once_and_kept_under_the_title_id(self):
        net = self.net(('image.tmdb.org', b'\x89PNG-bytes'))
        path = rt._cache_poster_image('https://image.tmdb.org/t/p/w300/p.jpg', 'movie:a:2000', tmdb_id='603')
        self.assertTrue(path.endswith('.jpg'))
        with open(path, 'rb') as f:
            self.assertEqual(f.read(), b'\x89PNG-bytes')
        self.assertEqual(rt._cache_poster_image('https://image.tmdb.org/t/p/w300/p.jpg', 'movie:b:2000', tmdb_id='603'), path)
        self.assertEqual(len(net.requests), 1)
        self.assertEqual(rt.get_cached_poster('anything', tmdb_id='603'), path)
        self.assertIsNone(rt.get_cached_poster('anything', tmdb_id='604'))
        self.assertEqual(sorted(p.name for p in rt.POSTER_CACHE_DIR.iterdir() if p.name != 'index.json' and p.name != path.rsplit('/', 1)[-1]), [])

    def test_only_http_and_https_addresses_are_fetched(self):
        net = self.net()
        for bad in (None, '', 'N/A', 'file:///etc/passwd', 'ftp://x/p.jpg'):
            self.assertIsNone(rt._cache_poster_image(bad, 'k'), bad)
        self.assertEqual(net.requests, [])

    def test_a_poster_that_is_too_large_or_fails_is_not_kept(self):
        self.net(('big', b'x' * (rt.MAX_POSTER_BYTES + 5)), ('down', urllib.error.URLError('down')))
        self.assertIsNone(rt._cache_poster_image('https://image.tmdb.org/big.jpg', 'k1'))
        self.assertIsNone(rt._cache_poster_image('https://image.tmdb.org/down.jpg', 'k2'))
        self.assertFalse(list(rt.POSTER_CACHE_DIR.glob('*.jpg')) if rt.POSTER_CACHE_DIR.exists() else [])

    def test_the_file_of_an_expired_poster_is_deleted(self):
        self.net(('image.tmdb.org', b'bytes'))
        path = rt._cache_poster_image('https://image.tmdb.org/a.jpg', 'k1')
        index = rt.POSTER_CACHE_DIR / 'index.json'
        data = json.loads(index.read_text())
        data['k1']['cached_at'] -= (rt.POSTER_CACHE_TTL_DAYS + 1) * 86400
        index.write_text(json.dumps(data))
        rt._cache_poster_image('https://image.tmdb.org/b.jpg', 'k2')  # any change to the index sweeps
        self.assertFalse(os.path.exists(path))

    def test_the_poster_is_found_by_title_when_there_is_no_id(self):
        self.net(('image.tmdb.org', b'bytes'))
        path = rt._cache_poster_image('https://image.tmdb.org/a.jpg', 'movie:alien:1979')
        self.assertEqual(rt.get_cached_poster('Alien (1979)'), path)

    def test_the_poster_of_a_found_title_is_fetched_with_the_title(self):
        net = self.net(('/search/movie', TMDB_HIT), ('/movie/603', TMDB_DETAILS), ('image.tmdb.org', b'bytes'))
        rt.get_metadata('The Matrix', 1999, 'movie', tmdb_key='T')
        self.assertEqual(net.urls('image.tmdb.org'), ['https://image.tmdb.org/t/p/w300/p.jpg'])
        self.assertTrue(rt.get_cached_poster('x', tmdb_id='603'))


class TestTheHoverText(MetadataCase):
    def test_the_text_is_escaped_markup(self):
        text = rt.format_metadata_for_tooltip({'title': 'Tom & <Jerry>', 'year': '2021', 'imdb_rating': 7.5,
                                               'overview': 'a < b & c'})
        self.assertIn('Tom &amp; &lt;Jerry&gt; (2021)', text)
        self.assertIn('IMDb: 7.5/10', text)
        self.assertIn('a &lt; b &amp; c', text)

    def test_nothing_known_is_no_text(self):
        self.assertIsNone(rt.format_metadata_for_tooltip(None))
        self.assertIsNone(rt.format_metadata_for_tooltip({}))

    def test_the_keys_come_from_the_media_section_of_the_config(self):
        with mock.patch.object(rt, '_media_setting', side_effect=lambda name: {'omdb_key': 'O', 'tmdb_key': 'T', 'tmdb': 'on'}.get(name)):
            self.assertEqual((rt.load_omdb_api_key(), rt.load_tmdb_api_key()), ('O', 'T'))
        with mock.patch.object(rt, '_media_setting', side_effect=lambda name: {'omdb_key': 'O', 'tmdb_key': 'T'}.get(name)):
            self.assertEqual((rt.load_omdb_api_key(), rt.load_tmdb_api_key()), ('O', None))  # tmdb is off unless it is on


if __name__ == '__main__':
    unittest.main()
