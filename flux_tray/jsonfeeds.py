"""A news feed that is JSON, not RSS or Atom: g1line.ro's `/api/news.php`.

`fetch_json_feed` returns what the feed check reads from a parsed feed (`bozo`,
`entries`, `feed`), with entries shaped like feedparser's, so muting, Read later,
the seen list and the popup need to know nothing about the format. Every other
feed address still goes to feedparser. An entry has no date on purpose: the API
gives a day, not a time, and the 24 h rule (an item that old is marked seen and
not shown) would drop items of yesterday that were never seen.
"""

import json
import urllib.parse
import urllib.request
from types import SimpleNamespace

from .links import is_web_url


G1LINE_HOSTS = ('g1line.ro', 'www.g1line.ro')
G1LINE_PATH = '/api/news.php'
G1LINE_SITE = 'https://g1line.ro/'
G1LINE_PER_PAGE = 30  # items asked for in one read (the API's own default is 12)
JSON_FEED_TIMEOUT_SECONDS = 15
JSON_FEED_MAX_BYTES = 2_000_000
JSON_FEED_USER_AGENT = 'Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0'


def is_json_feed(url):
    """True for the address of the g1line.ro news API, however its query is written."""
    if not isinstance(url, str):
        return False
    try:
        parts = urllib.parse.urlsplit(url.strip())
    except ValueError:
        return False
    return (parts.scheme in ('http', 'https') and (parts.hostname or '').lower() in G1LINE_HOSTS
            and parts.path == G1LINE_PATH)


def request_url(url):
    """`url` asking for G1LINE_PER_PAGE items, unless its own query already says how many."""
    parts = urllib.parse.urlsplit(url.strip())
    query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    if not any(name == 'per_page' for name, _value in query):
        query.append(('per_page', str(G1LINE_PER_PAGE)))
    return urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(query)))


def _text(value):
    return value.strip() if isinstance(value, str) else ''


def entries_from_payload(payload):
    """The feed entries of a decoded g1line response, newest first as the API sends them:
    id (g1line's own number: two items can share a source address), title as
    `source: title`, link (the source's article, when it is a web address),
    summary, and the region as the one category. Items without a title are left out.
    Raises ValueError when the response is not what the API sends."""
    items = payload.get('items') if isinstance(payload, dict) else None
    if not isinstance(items, list):
        raise ValueError('not a g1line news response')
    entries = []
    for item in items:
        if not isinstance(item, dict):
            continue
        title, source = _text(item.get('title')), _text(item.get('source'))
        if not title:
            continue
        entry = {'title': f'{source}: {title}' if source else title,
                 'link': item['source_url'].strip() if is_web_url(_text(item.get('source_url'))) else ''}
        number = item.get('id')
        if isinstance(number, (int, str)) and not isinstance(number, bool) and str(number).strip():
            entry['id'] = f'g1line:{str(number).strip()}'
        if _text(item.get('summary')):
            entry['summary'] = _text(item['summary'])
        if _text(item.get('region')):
            entry['tags'] = [{'term': _text(item['region'])}]
        entries.append(entry)
    return entries


def fetch_json_feed(url):
    """Reads the feed at `url` (see is_json_feed). Raises on a failed read or an answer that
    is not the API's, which the feed check counts as a failed fetch."""
    request = urllib.request.Request(request_url(url), headers={'User-Agent': JSON_FEED_USER_AGENT, 'Accept': 'application/json'})
    with urllib.request.urlopen(request, timeout=JSON_FEED_TIMEOUT_SECONDS) as response:
        body = response.read(JSON_FEED_MAX_BYTES)
    entries = entries_from_payload(json.loads(body.decode('utf-8', 'replace')))
    return SimpleNamespace(bozo=False, entries=entries, feed={'link': G1LINE_SITE})
