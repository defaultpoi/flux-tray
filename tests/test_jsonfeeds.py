import http.server
import json
import threading
import unittest

from facade import rt


# What g1line.ro/api/news.php sends (shortened; the addresses are made up).
G1LINE_RESPONSE = {
    'items': [
        {'id': 1078, 'source': 'The Example Post', 'source_url': 'https://news.example.com/a1',
         'title': 'Prima știre, cu diacritice', 'summary': 'Rezumatul primei știri.',
         'image_url': 'https://img.example.com/1.jpg', 'region': 'Orientul Mijlociu',
         'pub_date': '2026-11-27', 'date_label': '27 noiembrie 2026', 'color': 'hsl(-128 55% 40%)'},
        {'id': 1075, 'source': 'A Philosopher (1513)', 'source_url': 'https://g1line.ro/index.php',
         'title': 'A quotation', 'summary': 'Why it matters.', 'region': 'Global'},
        {'id': 1074, 'source': 'Another Quotation', 'source_url': 'https://g1line.ro/index.php',
         'title': 'A second quotation', 'summary': '', 'region': ''},
    ],
    'page': 1, 'per_page': 12, 'total': 1044, 'has_more': True,
}


class TestIsJsonFeed(unittest.TestCase):
    def test_the_g1line_api_with_or_without_a_query(self):
        for url in ('https://g1line.ro/api/news.php', 'https://g1line.ro/api/news.php?per_page=5',
                    'http://www.g1line.ro/api/news.php', 'https://G1LINE.RO/api/news.php', ' https://g1line.ro/api/news.php '):
            self.assertTrue(rt.is_json_feed(url), url)

    def test_nothing_else(self):
        for url in ('https://g1line.ro/', 'https://g1line.ro/api/other.php', 'https://example.com/api/news.php',
                    'https://g1line.ro.example.com/api/news.php', 'ftp://g1line.ro/api/news.php',
                    'https://example.com/feed.xml', '', None, 5):
            self.assertFalse(rt.is_json_feed(url), url)


class TestRequestUrl(unittest.TestCase):
    def test_it_asks_for_thirty_items(self):
        self.assertEqual(rt.request_url('https://g1line.ro/api/news.php'), 'https://g1line.ro/api/news.php?per_page=30')

    def test_an_address_that_says_how_many_is_left_alone(self):
        self.assertEqual(rt.request_url('https://g1line.ro/api/news.php?per_page=5'),
                         'https://g1line.ro/api/news.php?per_page=5')

    def test_another_query_is_kept(self):
        self.assertEqual(rt.request_url('https://g1line.ro/api/news.php?region=Europa'),
                         'https://g1line.ro/api/news.php?region=Europa&per_page=30')


class TestEntriesFromPayload(unittest.TestCase):
    def entries(self, payload=None):
        return rt.entries_from_payload(G1LINE_RESPONSE if payload is None else payload)

    def test_the_title_is_the_source_then_the_title(self):
        self.assertEqual(self.entries()[0]['title'], 'The Example Post: Prima știre, cu diacritice')

    def test_a_click_goes_to_the_source_url(self):
        self.assertEqual(self.entries()[0]['link'], 'https://news.example.com/a1')

    def test_the_summary_is_kept_for_the_hover_and_an_empty_one_is_not(self):
        entries = self.entries()
        self.assertEqual(entries[0]['summary'], 'Rezumatul primei știri.')
        self.assertNotIn('summary', entries[2])

    def test_the_region_is_the_category(self):
        entries = self.entries()
        self.assertEqual(rt.entry_tag_terms(entries[0]), ['Orientul Mijlociu'])
        self.assertEqual(rt.entry_tag_terms(entries[2]), [])

    def test_items_that_share_a_source_address_are_different_items(self):
        entries = self.entries()
        self.assertEqual(entries[1]['link'], entries[2]['link'])
        self.assertNotEqual(rt.entry_id(entries[1], 'u'), rt.entry_id(entries[2], 'u'))

    def test_an_entry_has_no_date(self):
        # the API gives a day, not a time: a date would make yesterday's unseen items "older than 24 h"
        for entry in self.entries():
            self.assertIsNone(rt.entry_age_seconds(entry))
            self.assertIsNone(rt.entry_updated_timestamp(entry))

    def test_an_item_without_a_source_is_just_its_title(self):
        entry = self.entries({'items': [{'id': 1, 'title': 'Only a title', 'source_url': 'https://a.example/x'}]})[0]
        self.assertEqual(entry['title'], 'Only a title')

    def test_an_item_without_a_title_is_left_out(self):
        self.assertEqual(self.entries({'items': [{'id': 1, 'source': 'S', 'title': '  '}, {'id': 2}, 'junk', None]}), [])

    def test_a_source_url_that_is_not_a_web_address_gives_no_link(self):
        for bad in ('file:///etc/hostname', 'ssh://x', '', None, 5):
            entry = self.entries({'items': [{'id': 1, 'title': 'T', 'source_url': bad}]})[0]
            self.assertEqual(entry['link'], '', bad)

    def test_an_answer_that_is_not_the_api_raises(self):
        for payload in ({}, {'items': 'x'}, [], 'x', None):
            with self.assertRaises(ValueError):
                rt.entries_from_payload(payload)


class FakeApi(http.server.BaseHTTPRequestHandler):
    seen = []
    status, body = 200, b''

    def do_GET(self):
        FakeApi.seen.append((self.path, self.headers.get('User-Agent'), self.headers.get('Accept')))
        self.send_response(FakeApi.status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.end_headers()
        self.wfile.write(FakeApi.body)

    def log_message(self, *args):
        pass


class TestFetchJsonFeed(unittest.TestCase):
    """Against a real server on this machine: the request is really made."""

    def setUp(self):
        FakeApi.seen, FakeApi.status = [], 200
        FakeApi.body = json.dumps(G1LINE_RESPONSE).encode()
        self.server = http.server.HTTPServer(('127.0.0.1', 0), FakeApi)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.url = f'http://127.0.0.1:{self.server.server_address[1]}/api/news.php'

    def test_it_asks_for_thirty_items_and_reads_them(self):
        parsed = rt.fetch_json_feed(self.url)
        path, agent, accept = FakeApi.seen[0]
        self.assertEqual(path, '/api/news.php?per_page=30')
        self.assertIn('Mozilla', agent)
        self.assertEqual(accept, 'application/json')
        self.assertFalse(parsed.bozo)
        self.assertEqual(len(parsed.entries), 3)
        self.assertEqual(parsed.feed['link'], 'https://g1line.ro/')

    def test_an_error_status_raises(self):
        FakeApi.status = 500
        with self.assertRaises(Exception):
            rt.fetch_json_feed(self.url)

    def test_an_answer_that_is_not_json_raises(self):
        FakeApi.body = b'<html>blocked</html>'
        with self.assertRaises(ValueError):
            rt.fetch_json_feed(self.url)

    def test_a_json_answer_that_is_not_the_api_raises(self):
        FakeApi.body = b'{"error": "rate limited"}'
        with self.assertRaises(ValueError):
            rt.fetch_json_feed(self.url)


if __name__ == '__main__':
    unittest.main()
