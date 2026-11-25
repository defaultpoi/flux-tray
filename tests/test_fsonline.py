"""Tests for fsonline.one plugin sitemap-based new episode/movie detection."""

import importlib.util
import os
import sys
import time
import unittest
from unittest import mock

HAVE_PLUGIN_DEPENDENCIES = all(importlib.util.find_spec(name) for name in ('requests', 'bs4'))


@unittest.skipUnless(HAVE_PLUGIN_DEPENDENCIES, 'the site plugins need requests and beautifulsoup4 (CI installs them)')
class TestFsonlineSitemapFunctions(unittest.TestCase):
    """Test the fsonline_one plugin's fetch_new_episodes and fetch_new_movies functions."""

    def setUp(self):
        # Import the plugin module from addons/media-plugins
        plugin_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'addons', 'media-plugins')
        if plugin_path not in sys.path:
            sys.path.insert(0, plugin_path)
        import fsonline_one
        self.plugin = fsonline_one
        # Clear the sitemap cache before each test
        self.plugin._sitemap_cache.clear()

    def _patch_sitemap(self, return_value):
        """Context manager to patch _sitemap_page_with_lastmod in the plugin module."""
        return mock.patch('fsonline_one._sitemap_page_with_lastmod', return_value=return_value)

    def test_fetch_new_episodes_empty_cache(self):
        """When sitemap returns no items, returns empty set."""
        with self._patch_sitemap(None):
            result = self.plugin.fetch_new_episodes(time.time(), {'some-title'})
            self.assertEqual(result, set())

    def test_fetch_new_episodes_no_matching_titles(self):
        """When sitemap has items but none match watch_titles, returns empty set."""
        # Mock sitemap to return items with lastmod in the future (newer than since_timestamp)
        future_time = time.time() + 3600
        mock_items = [
            ('https://fsonline.one/episod/other-series-2024/s01-e01/', future_time),
            ('https://fsonline.one/episod/another-show-2023/s02-e05/', future_time),
        ]
        def mock_sitemap(kind, page):
            if page == 1:
                return mock_items
            return []

        with mock.patch('fsonline_one._sitemap_page_with_lastmod', side_effect=mock_sitemap):
            result = self.plugin.fetch_new_episodes(time.time(), {'watched-series-2024'})
            self.assertEqual(result, set())

    def test_fetch_new_episodes_matching_title(self):
        """When sitemap has matching title, returns series URL."""
        future_time = time.time() + 3600
        mock_items = [
            ('https://fsonline.one/episod/watched-series-2024-online-subtitrat/s01-e01/', future_time),
        ]
        def mock_sitemap(kind, page):
            if page == 1:
                return mock_items
            return []

        with mock.patch('fsonline_one._sitemap_page_with_lastmod', side_effect=mock_sitemap):
            result = self.plugin.fetch_new_episodes(time.time(), {'watched-series-2024'})
            self.assertEqual(len(result), 1)
            self.assertIn('https://fsonline.one/serial/watched-series-2024-online-subtitrat/', result)

    def test_fetch_new_episodes_stops_when_older_than_since(self):
        """Stops pagination when items on a page are older than since_timestamp.
        Since sitemap is sorted newest-first, if the first item is older, we stop."""
        since = time.time() - 7200  # 2 hours ago
        # Page 1: first item is older than since, so we should stop immediately
        page1_items = [
            ('https://fsonline.one/episod/series-a-2024/s01-e01/', time.time() - 10000),
        ]
        call_count = [0]

        def mock_sitemap(kind, page):
            call_count[0] += 1
            if page == 1:
                return page1_items
            return []

        with mock.patch('fsonline_one._sitemap_page_with_lastmod', side_effect=mock_sitemap):
            result = self.plugin.fetch_new_episodes(since, {'series-a-2024'})
            # Should only call page 1, then stop because first item is older than since
            self.assertEqual(call_count[0], 1)
            self.assertEqual(result, set())

    def test_fetch_new_episodes_paginates_when_all_newer(self):
        """Continues to next page when all items on page are newer than since."""
        since = time.time() - 7200
        page1_items = [
            ('https://fsonline.one/episod/series-a-2024/s01-e01/', time.time()),
            ('https://fsonline.one/episod/series-b-2024/s01-e01/', time.time() - 3600),
        ]
        page2_items = [
            ('https://fsonline.one/episod/series-c-2024/s01-e01/', time.time() - 1800),
        ]
        page3_items = []  # Empty page 3 stops the loop
        call_count = [0]

        def mock_sitemap(kind, page):
            call_count[0] += 1
            if page == 1:
                return page1_items
            elif page == 2:
                return page2_items
            elif page == 3:
                return page3_items
            return []

        with mock.patch('fsonline_one._sitemap_page_with_lastmod', side_effect=mock_sitemap):
            result = self.plugin.fetch_new_episodes(since, {'series-a-2024', 'series-b-2024', 'series-c-2024'})
            # Calls page 1, page 2, page 3 (empty, stops)
            self.assertEqual(call_count[0], 3)
            self.assertEqual(len(result), 3)

    def test_fetch_new_movies_matching_title(self):
        """fetch_new_movies returns movie URL for matching title."""
        future_time = time.time() + 3600
        mock_items = [
            ('https://fsonline.one/film/watched-movie-2024-online-subtitrat/', future_time),
        ]
        def mock_sitemap(kind, page):
            if page == 1:
                return mock_items
            return []

        with mock.patch('fsonline_one._sitemap_page_with_lastmod', side_effect=mock_sitemap):
            result = self.plugin.fetch_new_movies(time.time(), {'watched-movie-2024'})
            self.assertEqual(len(result), 1)
            self.assertIn('https://fsonline.one/film/watched-movie-2024-online-subtitrat/', result)

    def test_fetch_new_movies_stops_when_older(self):
        """fetch_new_movies stops when items are older than since_timestamp."""
        since = time.time() - 7200
        mock_items = [
            ('https://fsonline.one/film/new-movie-2024-online-subtitrat/', time.time()),
            ('https://fsonline.one/film/old-movie-2023-online-subtitrat/', time.time() - 10000),
        ]
        call_count = [0]

        def mock_sitemap(kind, page):
            call_count[0] += 1
            if page == 1:
                return mock_items
            return []

        with mock.patch('fsonline_one._sitemap_page_with_lastmod', side_effect=mock_sitemap):
            result = self.plugin.fetch_new_movies(since, {'new-movie-2024', 'old-movie-2023'})
            self.assertEqual(call_count[0], 1)
            self.assertIn('https://fsonline.one/film/new-movie-2024-online-subtitrat/', result)
            self.assertNotIn('https://fsonline.one/film/old-movie-2023-online-subtitrat/', result)

    def test_sitemap_cache_works(self):
        """Sitemap pages are cached for SITEMAP_CACHE_SECONDS (5 minutes)."""
        mock_items = [('https://fsonline.one/film/test-2024-online-subtitrat/', time.time() + 3600)]
        with mock.patch('fsonline_one._fetch_sitemap_with_lastmod', return_value=mock_items) as mock_fetch:
            # First call
            result1 = self.plugin._sitemap_page_with_lastmod('movies', 1)
            # Second call (should use cache)
            result2 = self.plugin._sitemap_page_with_lastmod('movies', 1)
            self.assertEqual(result1, mock_items)
            self.assertEqual(result2, mock_items)
            # Should only fetch once
            mock_fetch.assert_called_once()

    def test_sitemap_cache_expires(self):
        """Cache expires after SITEMAP_CACHE_SECONDS."""
        self.plugin._sitemap_cache[('movies', 1)] = (time.time() - 400, [('https://fsonline.one/film/old/', time.time())])
        mock_items = [('https://fsonline.one/film/new-2024-online-subtitrat/', time.time() + 3600)]
        with mock.patch('fsonline_one._fetch_sitemap_with_lastmod', return_value=mock_items) as mock_fetch:
            result = self.plugin._sitemap_page_with_lastmod('movies', 1)
            self.assertEqual(result, mock_items)
            mock_fetch.assert_called_once()

    def test_extract_series_url(self):
        """_extract_series_url converts episode URL to series URL."""
        ep_url = 'https://fsonline.one/episod/breaking-bad-2008-online-subtitrat/s05-e07/'
        result = self.plugin._extract_series_url(ep_url)
        self.assertEqual(result, 'https://fsonline.one/serial/breaking-bad-2008-online-subtitrat/')

    def test_extract_series_url_none_for_invalid(self):
        """_extract_series_url returns None for non-episode URLs."""
        self.assertIsNone(self.plugin._extract_series_url('https://fsonline.one/film/movie-2024/'))
        self.assertIsNone(self.plugin._extract_series_url('https://fsonline.one/serial/series-2024/'))

    def test_extract_movie_url(self):
        """_extract_movie_url validates movie URLs."""
        movie_url = 'https://fsonline.one/film/dune-2024-online-subtitrat/'
        self.assertEqual(self.plugin._extract_movie_url(movie_url), movie_url)
        self.assertIsNone(self.plugin._extract_movie_url('https://fsonline.one/serial/series-2024/'))

    def test_norm_title_in_plugin(self):
        """_norm_title in plugin normalizes titles correctly."""
        self.assertEqual(self.plugin._norm_title('Dune: Part Two (2024)'), 'dune-part-two-2024')
        self.assertEqual(self.plugin._norm_title('Breaking Bad'), 'breaking-bad')
        self.assertEqual(self.plugin._norm_title('Él Niño'), 'el-nino')


class TestNormTitleWatchModule(unittest.TestCase):
    """Test _norm_title from watch module (the canonical version)."""

    def test_norm_title_basic(self):
        from flux_tray.watch import _norm_title
        self.assertEqual(_norm_title('Dune: Part Two (2024)'), 'dune-part-two-2024')
        self.assertEqual(_norm_title('Breaking Bad'), 'breaking-bad')

    def test_norm_title_accents(self):
        from flux_tray.watch import _norm_title
        self.assertEqual(_norm_title('Él Niño'), 'el-nino')
        self.assertEqual(_norm_title('São Paulo'), 'sao-paulo')

    def test_norm_title_empty(self):
        from flux_tray.watch import _norm_title
        self.assertEqual(_norm_title(''), '')
        self.assertEqual(_norm_title(None), '')

    def test_norm_title_numbers_and_symbols(self):
        from flux_tray.watch import _norm_title
        self.assertEqual(_norm_title('Season 2 Episode 5'), 'season-2-episode-5')
        self.assertEqual(_norm_title('Show@#$%^&*()'), 'show')


@unittest.skipUnless(HAVE_PLUGIN_DEPENDENCIES, 'the site plugins need requests and beautifulsoup4 (CI installs them)')
class TestFsonlineResolve(unittest.TestCase):
    """resolve(): the site lists several servers for a title, and one may not have it."""

    PAGE = 'https://fsonline.example/film/dune-2024-online-subtitrat/'
    OTHER = {'link': 'https://other.example/e/abc?token=SECRET'}
    KAEMBED = {'link': 'https://kaembed.example/embed-xyz.html?sub.info=https://subs.example/k.json'}

    def setUp(self):
        plugin_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'addons', 'media-plugins')
        if plugin_path not in sys.path:
            sys.path.insert(0, plugin_path)
        import requests
        import fsonline_one
        self.plugin = fsonline_one
        self.requests = requests
        self.streams = {}  # embed address -> a stream, an exception to raise, or None for a page without one
        self.asked = []

        def extract(embed_url):
            self.asked.append(embed_url)
            result = self.streams[embed_url]
            if isinstance(result, Exception):
                raise result
            return result

        for name, value in (('_get_soup', mock.Mock()), ('_extract_token', mock.Mock(return_value='t' * 60)),
                            ('_extract_vidmoly_m3u8', mock.Mock(side_effect=extract)),
                            ('_fetch_subtitles', mock.Mock(return_value=[{'url': 'https://subs.example/k.vtt', 'lang': 'ro', 'ext': '.vtt'}]))):
            patcher = mock.patch.object(fsonline_one, name, value)
            setattr(self, name.strip('_'), patcher.start())
            self.addCleanup(patcher.stop)

    def serve(self, *servers):
        patcher = mock.patch.object(self.plugin, '_get_servers', return_value=list(servers))
        patcher.start()
        self.addCleanup(patcher.stop)

    def http_error(self, code):
        return self.requests.HTTPError(f'{code} Client Error: Not Found for url: https://x.example/y?token=SECRET',
                                       response=mock.Mock(status_code=code))

    def resolve(self):
        return self.plugin.resolve({'ref': self.PAGE})

    def test_the_server_the_plugin_knows_is_tried_first_whatever_the_order_on_the_site(self):
        self.serve(self.OTHER, self.KAEMBED)
        self.streams = {self.KAEMBED['link']: 'https://cdn.example/a.m3u8', self.OTHER['link']: 'https://cdn.example/b.m3u8'}
        got = self.resolve()
        self.assertEqual(got['video']['url'], 'https://cdn.example/a.m3u8')
        self.assertEqual(got['video']['headers']['Referer'], self.KAEMBED['link'])
        self.assertEqual(self.asked, [self.KAEMBED['link']])  # the other was not needed
        self.fetch_subtitles.assert_called_once_with('https://subs.example/k.json')

    def test_when_that_server_does_not_have_the_title_the_next_one_is_tried(self):
        self.serve(self.OTHER, self.KAEMBED)
        self.streams = {self.KAEMBED['link']: self.http_error(404), self.OTHER['link']: 'https://cdn.example/b.m3u8'}
        got = self.resolve()
        self.assertEqual(got['video']['url'], 'https://cdn.example/b.m3u8')
        self.assertEqual(got['video']['headers']['Referer'], self.OTHER['link'])  # the stream is asked for as the server that has it
        self.assertEqual(self.asked, [self.KAEMBED['link'], self.OTHER['link']])
        self.assertEqual(got['subs'], [])  # this server names no subtitles, so none are asked for
        self.fetch_subtitles.assert_not_called()

    def test_a_server_whose_page_has_no_stream_is_passed_over_too(self):
        self.serve(self.KAEMBED, self.OTHER)
        self.streams = {self.KAEMBED['link']: None, self.OTHER['link']: 'https://cdn.example/b.m3u8'}
        self.assertEqual(self.resolve()['video']['url'], 'https://cdn.example/b.m3u8')

    def test_when_none_has_it_the_message_says_what_each_said_and_shows_no_address_or_token(self):
        self.serve(self.OTHER, self.KAEMBED)
        self.streams = {self.KAEMBED['link']: self.http_error(404), self.OTHER['link']: None}
        with self.assertRaises(ValueError) as caught:
            self.resolve()
        message = str(caught.exception)
        self.assertIn('kaembed.example: HTTP 404', message)
        self.assertIn('other.example: no stream in its page', message)
        self.assertNotIn('SECRET', message)
        self.assertNotIn('https://', message)

    def test_an_error_that_is_not_an_answer_of_the_site_is_named_by_its_kind(self):
        self.serve(self.KAEMBED)
        self.streams = {self.KAEMBED['link']: self.requests.ConnectionError('boom')}
        with self.assertRaises(ValueError) as caught:
            self.resolve()
        self.assertIn('kaembed.example: ConnectionError', str(caught.exception))

    def test_a_server_without_a_link_is_skipped_and_no_servers_is_said_so(self):
        self.serve({'name': 'broken'}, self.KAEMBED)
        self.streams = {self.KAEMBED['link']: 'https://cdn.example/a.m3u8'}
        self.assertEqual(self.resolve()['video']['url'], 'https://cdn.example/a.m3u8')
        self.serve()
        with self.assertRaisesRegex(ValueError, 'No vidmoly server found'):
            self.resolve()


if __name__ == '__main__':
    unittest.main()