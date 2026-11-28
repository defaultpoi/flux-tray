"""The imdb-charts plugin reads the chart page's own list (rating and poster of each title) and asks the
r.jina.ai proxy, which gives titles only, when the page itself cannot be had."""
import json
import os
import sys
import unittest
import urllib.error
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'addons', 'media-plugins'))
import imdb_charts  # noqa: E402

MOVIEMETER = 'https://www.imdb.com/chart/moviemeter/'
POSTER = 'https://m.media-amazon.com/images/M/MV5BNjEzYTE2ODEtNzY5Zi00ZmVmLWEyYzEtYjdlZWU2NjcyYzMzXkEyXkFqcGc@._V1_.jpg'

# The first title of the page as the owner copied it from IMDb's moviemeter on 2026-11-27
FIRST = {'@type': 'ListItem', 'item': {
    '@type': 'Movie', 'url': 'https://www.imdb.com/title/tt32558705/', 'name': 'The Hunger Games: Sunrise on the Reaping',
    'description': 'Revisit the world of Panem 24 years before the events of The Hunger Games.', 'image': POSTER,
    'aggregateRating': {'@type': 'AggregateRating', 'bestRating': 10, 'worstRating': 1, 'ratingValue': 7.5, 'ratingCount': 37535},
    'contentRating': 'PG-13', 'genre': 'Action, Adventure, Fantasy', 'duration': 'PT2H38M'}}


def listed(title_id, name, **item):
    """A list element of the same shape (made up, for the cases the owner's page does not show)."""
    return {'@type': 'ListItem', 'item': {'@type': 'Movie', 'url': f'https://www.imdb.com/title/{title_id}/', 'name': name, **item}}


def page(*elements, before=''):
    data = {'@type': 'ItemList', 'itemListElement': list(elements)}
    return f'<html><head>{before}<script type="application/ld+json">{json.dumps(data)}</script></head><body></body></html>'


class Response:
    def __init__(self, text):
        self.text = text

    def read(self):
        return self.text.encode()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def site(direct, proxy):
    """urlopen as the site and the proxy answer it: a text, or an exception to raise; the requests it got are in `.asked`."""
    asked = []

    def urlopen(request, timeout=None):
        asked.append(request.full_url)
        answer = proxy if request.full_url.startswith('https://r.jina.ai/') else direct
        if isinstance(answer, Exception):
            raise answer
        return Response(answer)
    urlopen.asked = asked
    return urlopen


class TestTheChartPage(unittest.TestCase):
    def test_the_titles_come_in_the_order_of_the_list_with_their_rating_and_poster(self):
        episodes = imdb_charts._parse_chart_html(page(FIRST, listed('tt2', 'Second', image='https://x/p.jpg')), 'moviemeter')
        self.assertEqual([e['id'] for e in episodes], ['tt32558705', 'tt2'])
        self.assertEqual(episodes[0], {'id': 'tt32558705', 'title': 'The Hunger Games: Sunrise on the Reaping', 'date': '',
                                       'url': 'https://www.imdb.com/title/tt32558705/', 'ref': 'moviemeter',
                                       'rating': 7.5, 'image': POSTER})

    def test_a_title_with_no_rating_or_a_rating_that_is_not_one_has_none(self):
        bad = ({}, {'aggregateRating': {'ratingValue': 0}}, {'aggregateRating': {'ratingValue': 11}},
               {'aggregateRating': {'ratingValue': '7.5'}}, {'aggregateRating': {'ratingValue': True}}, {'aggregateRating': 'x'})
        episodes = imdb_charts._parse_chart_html(page(*[listed(f'tt{i}', f'T{i}', **extra) for i, extra in enumerate(bad, 1)]), 'moviemeter')
        self.assertEqual(len(episodes), len(bad))
        self.assertEqual([e.get('rating') for e in episodes], [None] * len(bad))

    def test_a_whole_rating_is_a_number_with_a_decimal_point(self):
        episode = imdb_charts._parse_chart_html(page(listed('tt1', 'T', aggregateRating={'ratingValue': 8})), 'moviemeter')[0]
        self.assertEqual(repr(episode['rating']), '8.0')

    def test_a_poster_that_is_not_an_https_address_is_not_taken(self):
        for image in ('http://x/p.jpg', 'javascript:alert(1)', '', None, 5):
            episode = imdb_charts._parse_chart_html(page(listed('tt1', 'T', image=image)), 'moviemeter')[0]
            self.assertNotIn('image', episode, image)

    def test_a_title_twice_or_with_no_title_page_or_no_name_is_left_out(self):
        elements = (listed('tt1', 'One'), listed('tt1', 'One again'), listed('tt2', ''), listed('tt3', 'Three'),
                    {'@type': 'ListItem', 'item': {'name': 'No page', 'url': 'https://www.imdb.com/name/nm1/'}}, 'junk')
        episodes = imdb_charts._parse_chart_html(page(*elements), 'moviemeter')
        self.assertEqual([e['title'] for e in episodes], ['One', 'Three'])

    def test_other_scripts_and_broken_ones_are_passed_over_to_find_the_list(self):
        before = ('<script type="application/ld+json">{not json</script>'
                  '<script type="application/ld+json">{"@type": "BreadcrumbList", "itemListElement": []}</script>')
        episodes = imdb_charts._parse_chart_html(page(FIRST, before=before), 'moviemeter')
        self.assertEqual([e['id'] for e in episodes], ['tt32558705'])

    def test_a_page_with_no_list_still_goes_to_the_other_readers(self):
        markdown = '1. [Some Film](https://www.imdb.com/title/tt77/) 7.1'
        self.assertEqual([(e['id'], e.get('rating')) for e in imdb_charts._parse_chart_html(markdown, 'moviemeter')], [('tt77', None)])


class TestFetchingThePage(unittest.TestCase):
    MARKDOWN = '[Proxy Film](https://www.imdb.com/title/tt9/) and [Other](https://www.imdb.com/title/tt8/)'

    def episodes(self, urlopen):
        with mock.patch.object(imdb_charts.urllib.request, 'urlopen', urlopen):
            return imdb_charts.list_episodes('moviemeter')

    def test_the_page_is_asked_for_first_and_the_proxy_is_not_asked_when_it_has_the_chart(self):
        urlopen = site(page(FIRST), self.MARKDOWN)
        title, episodes = self.episodes(urlopen)
        self.assertEqual(urlopen.asked, [MOVIEMETER])
        self.assertEqual((title, episodes[0]['rating'], episodes[0]['image']), ('IMDB Most Popular Movies', 7.5, POSTER))

    def test_a_page_with_no_chart_in_it_goes_to_the_proxy_which_gives_the_titles_only(self):
        urlopen = site('<html>Please prove you are human</html>', self.MARKDOWN)
        _, episodes = self.episodes(urlopen)
        self.assertEqual(len(urlopen.asked), 2)
        self.assertTrue(urlopen.asked[1].startswith('https://r.jina.ai/'))
        self.assertEqual([(e['id'], e.get('rating'), e.get('image')) for e in episodes], [('tt9', None, None), ('tt8', None, None)])

    def test_a_refusal_by_the_site_goes_to_the_proxy_too(self):
        refused = urllib.error.HTTPError(MOVIEMETER, 403, 'Forbidden', {}, None)
        _, episodes = self.episodes(site(refused, self.MARKDOWN))
        self.assertEqual([e['id'] for e in episodes], ['tt9', 'tt8'])

    def test_when_neither_answers_the_error_is_the_sites(self):
        down = urllib.error.URLError('site down')
        with self.assertRaises(urllib.error.URLError) as caught:
            self.episodes(site(down, urllib.error.URLError('proxy down')))
        self.assertIs(caught.exception, down)

    def test_a_page_with_no_chart_that_the_proxy_cannot_help_with_is_still_read_as_it_always_was(self):
        html = '<a href="/title/tt5/">Linked Film</a>'
        _, episodes = self.episodes(site(html, urllib.error.URLError('proxy down')))
        self.assertEqual([e['id'] for e in episodes], ['tt5'])


if __name__ == '__main__':
    unittest.main()
