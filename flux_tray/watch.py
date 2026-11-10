"""The titles the person asked to have downloaded (a left click on a discovery row) and
how each is found: a discovery item is a title on a chart, not a page that can be
downloaded, so the sites' plugins are asked, one check after another, whether they
have it. A plugin says so with `find(title, year, imdb_id, kind)`, which returns the
address of the title on its site, or None. When one does, the title becomes a source like
any other and is downloaded by the rules of [media]. Pure: no GTK, no files.
"""

import math
import re
import unicodedata

from .log import _log

KINDS = ('movie', 'series')


def _norm_title(text):
    """A title as it is compared: no accents, lower case, words joined by one dash."""
    text = unicodedata.normalize('NFKD', text or '')
    text = ''.join(c for c in text if not unicodedata.combining(c)).lower()
    return '-'.join(re.findall(r'[a-z0-9]+', text))


def new_watch_entry(item, now, year=''):
    """The record of a discovery item that was asked for. `year` is the release year when it
    is known (the item's own, or the metadata's), else ''."""
    kind = item.get('type')
    return {
        'title': str(item.get('title') or ''),
        'year': str(year or ''),
        'type': kind if kind in KINDS else 'movie',
        'imdb_id': item.get('imdb_id') or None,
        'added': float(now),
        'checked': None,
        'source': None,
    }


def clean_watch(raw):
    """{key: record} from what was stored, every field present and of the right type; what is
    not a record of a title is dropped."""
    def number(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    clean = {}
    for key, entry in (raw.items() if isinstance(raw, dict) else ()):
        if not isinstance(key, str) or not isinstance(entry, dict) or not isinstance(entry.get('title'), str):
            continue
        clean[key] = {
            'title': entry['title'],
            'year': entry['year'] if isinstance(entry.get('year'), str) else '',
            'type': entry['type'] if entry.get('type') in KINDS else 'movie',
            'imdb_id': entry['imdb_id'] if isinstance(entry.get('imdb_id'), str) and entry['imdb_id'] else None,
            'added': float(entry['added']) if number(entry.get('added')) else 0.0,
            'checked': float(entry['checked']) if number(entry.get('checked')) else None,
            'source': entry['source'] if isinstance(entry.get('source'), str) and entry['source'] else None,
        }
    return clean


def is_searching(entry):
    """True while no site has been found to have the title."""
    return entry.get('source') is None


def search_due(entry, now, wait):
    """True when a title that is still being looked for was last looked for `wait` seconds ago
    or never."""
    return is_searching(entry) and (entry.get('checked') is None or now - entry['checked'] >= wait)


def source_line(plugin_name, url):
    """The [media] source line for a title found at `url` by the plugin: how the plugin is
    chosen for it later too (see MediaSources.driver_for)."""
    return f'{plugin_name}:{url}'


def find_source(finders, entry):
    """(plugin name, address) of the first plugin in `finders` that has the title, else None.

    Priority logic:
    - For movies: search sitefilme_com first (movies only, direct m3u8), then fsonline_one
    - For series: search fsonline_one only (sitefilme doesn't have series)

    A plugin that fails, or answers with anything but an http(s) address, has not got it:
    its bug must not stop the others being asked."""
    kind = entry.get('type', 'movie')

    # Build ordered list of finders based on content type
    if kind == 'movie':
        # Movies: sitefilme_com first, then fsonline_one
        ordered = [f for f in finders if f.name == 'sitefilme_com']
        ordered += [f for f in finders if f.name == 'fsonline_one']
        # Any other finders after
        ordered += [f for f in finders if f.name not in ('sitefilme_com', 'fsonline_one')]
    else:
        # Series: fsonline_one only (sitefilme doesn't have series)
        ordered = [f for f in finders if f.name == 'fsonline_one']

    for finder in ordered:
        try:
            url = finder.module.find(title=entry['title'], year=entry.get('year') or None,
                                     imdb_id=entry.get('imdb_id'), kind=kind)
        except Exception as error:
            _log(f'media plugin {finder.name}: find() failed: {error!r}')
            continue
        if isinstance(url, str) and url.startswith(('http://', 'https://')):
            return finder.name, url
    return None
