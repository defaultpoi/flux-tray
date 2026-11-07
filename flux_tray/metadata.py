"""Media metadata for the hover preview: TMDb (search, details, credits) with OMDb for
the IMDb rating, kept in metadata_cache.json beside config.conf, and the posters in
posters/. Standard library only.

A lookup that fails (no network, a bad key, a rate limit) is not remembered: only a
service's own "no such title" is, for NEGATIVE_CACHE_TTL_DAYS. The caches are replaced
whole (fileutil.write_atomic), one thread at a time, and re-read only when the file
changed, so the hover path costs a stat call.
"""

import hashlib
import html
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .config import _media_setting
from .constants import CONFIG_DIR
from .fileutil import write_atomic
from .log import _log


METADATA_CACHE_FILE = Path(CONFIG_DIR) / 'metadata_cache.json'
POSTER_CACHE_DIR = Path(CONFIG_DIR) / 'posters'
METADATA_CACHE_TTL_DAYS = 30
POSTER_CACHE_TTL_DAYS = 90
# Only a service's own "not found" is cached, for this many days
NEGATIVE_CACHE_TTL_DAYS = 7
# Most titles looked up per refresh cycle
MAX_API_CALLS_PER_CYCLE = 10
MAX_REPLY_BYTES = 2_000_000
MAX_POSTER_BYTES = 5_000_000

METADATA_USER_AGENT = 'flux-tray'
OMDB_BASE = 'https://www.omdbapi.com/'
TMDB_BASE = 'https://api.themoviedb.org/3'  # called with a v4 "API Read Access Token" as a Bearer token
TMDB_IMAGE_BASE = 'https://image.tmdb.org/t/p/w300'

# The fields OMDb adds to a TMDb result (TMDb's own director and cast stay)
OMDB_ENRICH_FIELDS = ('imdb_rating', 'imdb_votes', 'metascore', 'ratings', 'director', 'writer',
                      'actors', 'awards', 'dvd_released', 'box_office', 'production', 'website')
DETAIL_FIELDS = ('runtime', 'total_seasons', 'total_episodes', 'director', 'actors', 'status', 'tagline',
                 'homepage', 'production_companies', 'production_countries', 'spoken_languages')

_cache_lock = threading.RLock()
_memo = {}  # file path -> ((mtime_ns, size), parsed JSON), so an unchanged file is not read again
_tmdb_rate_limit_until = 0.0


class LookupFailed(Exception):
    """A service could not be asked, or its reply was unusable: no verdict on the
    title, so nothing is cached as "not found"."""


# --- The caches on disk ---------------------------------------------------------


def _read_store(path):
    """The JSON object in `path` ({} if it is missing or unreadable), parsed again
    only when the file changed. The result is shared: callers must not change it."""
    try:
        st = os.stat(path)
    except OSError:
        return {}
    stamp = (st.st_mtime_ns, st.st_size)
    with _cache_lock:
        hit = _memo.get(str(path))
        if hit and hit[0] == stamp:
            return hit[1]
        try:
            with open(path, encoding='utf-8') as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        _memo[str(path)] = (stamp, data)
        return data


def _write_store(path, data):
    with _cache_lock:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        write_atomic(path, lambda f: json.dump(data, f))
        st = os.stat(path)
        _memo[str(path)] = ((st.st_mtime_ns, st.st_size), data)


def _load_metadata_cache():
    """The metadata cache without its expired entries (a new dict; the entries are shared)."""
    now = time.time()
    fresh = {}
    for k, v in _read_store(METADATA_CACHE_FILE).items():
        if not isinstance(v, dict):
            continue
        days = NEGATIVE_CACHE_TTL_DAYS if v.get('negative') else METADATA_CACHE_TTL_DAYS
        if now - v.get('cached_at', 0) < days * 86400:
            fresh[k] = v
    return fresh


def _update_metadata_cache(change):
    """Applies `change(cache)` to the current cache and saves it, with no other
    thread's change in between (a read-change-write by two threads loses one)."""
    with _cache_lock:
        cache = _load_metadata_cache()
        change(cache)
        _write_store(METADATA_CACHE_FILE, cache)


def _make_negative_key(title, year, media_type):
    clean_title, _ = _parse_title_year(title)
    return f'neg:{clean_title.lower()}:{year or ""}:{media_type}'


def _is_negative_cached(title, year, media_type):
    return _make_negative_key(title, year, media_type) in _load_metadata_cache()


def _mark_negative_cache(title, year, media_type):
    neg_key = _make_negative_key(title, year, media_type)
    _update_metadata_cache(lambda c: c.__setitem__(neg_key, {'negative': True, 'cached_at': time.time()}))


def _poster_index():
    """The poster index without its expired entries (a new dict)."""
    now = time.time()
    return {k: v for k, v in _read_store(POSTER_CACHE_DIR / 'index.json').items()
            if isinstance(v, dict) and now - v.get('cached_at', 0) < POSTER_CACHE_TTL_DAYS * 86400}


def _update_poster_index(change):
    """Like _update_metadata_cache for the poster index; the files of entries that
    have expired are deleted."""
    with _cache_lock:
        old = _read_store(POSTER_CACHE_DIR / 'index.json')
        index = _poster_index()
        change(index)
        _write_store(POSTER_CACHE_DIR / 'index.json', index)
        for k, v in old.items():
            if k not in index and isinstance(v, dict) and v.get('path'):
                try:
                    os.unlink(v['path'])
                except OSError:
                    pass


def _get_poster_extension(url):
    ext = os.path.splitext(urllib.parse.urlparse(url or '').path)[1]
    return ext if ext in ('.jpg', '.jpeg', '.png', '.webp') else '.jpg'


def _cache_poster_image(poster_url, media_key, imdb_id=None, tmdb_id=None):
    """Downloads a poster into the poster cache (once per TMDb or IMDb id where there
    is one, else per `media_key`). Returns the file's path, or None."""
    if not poster_url or poster_url == 'N/A' or urllib.parse.urlparse(poster_url).scheme not in ('http', 'https'):
        return None
    cache_key = f'tmdb:{tmdb_id}' if tmdb_id else f'imdb:{imdb_id}' if imdb_id else media_key
    have = _poster_index().get(cache_key)
    if have and have.get('path') and os.path.exists(have['path']):
        return have['path']
    try:
        req = urllib.request.Request(poster_url, headers={'User-Agent': METADATA_USER_AGENT})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read(MAX_POSTER_BYTES + 1)
        if len(data) > MAX_POSTER_BYTES:
            return None
        POSTER_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path = POSTER_CACHE_DIR / (hashlib.sha1(cache_key.encode()).hexdigest() + _get_poster_extension(poster_url))
        write_atomic(path, lambda f: f.write(data), binary=True)
        entry = {'path': str(path), 'url': poster_url, 'cached_at': time.time()}
        _update_poster_index(lambda index: index.__setitem__(cache_key, entry))
        return str(path)
    except (OSError, ValueError) as e:
        _log(f'poster not cached: {e}')
        return None


def get_cached_poster(title, media_type='movie', imdb_id=None, tmdb_id=None):
    """The cached poster's file path for a title (by TMDb id, IMDb id, then title and
    year), or None. Only what is cached: it never goes to the network."""
    index = _poster_index()
    clean_title, year = _parse_title_year(title)
    for key in (f'tmdb:{tmdb_id}' if tmdb_id else None, f'imdb:{imdb_id}' if imdb_id else None,
                _make_key(clean_title, year, media_type)):
        path = index.get(key, {}).get('path') if key else None
        if path and os.path.exists(path):
            return path
    return None


# --- Titles ------------------------------------------------------------------------


def _make_key(title, year, media_type):
    """Cache key from title, year, and type (movie/series)."""
    return f'{media_type}:{title.lower()}:{year or "unknown"}'


def _parse_title_year(title):
    """Extract year from title like 'Movie Name (2023)' or 'Show Name 2023'.
    Also decodes HTML entities (e.g., &#8211; -> –)."""
    title = html.unescape(title.strip())
    # Match (YYYY) at end
    match = re.search(r'\(?(19\d{2}|20\d{2})\)?$', title)
    if match:
        return title[:match.start()].strip(), match.group(1)
    # Match YYYY at end (space separated)
    match = re.search(r'\s+(19\d{2}|20\d{2})$', title)
    if match:
        return title[:match.start()].strip(), match.group(1)
    return title, None


def _extract_year_from_url(url):
    """Extract year from URL slug like '/film/sentient-2026-online-subtitrat/'. """
    if not url:
        return None
    match = re.search(r'[-_](20\d{2}|19\d{2})[-_/.]', url)
    if match:
        return match.group(1)
    match = re.search(r'[-_](20\d{2}|19\d{2})$', url.rstrip('/'))
    return match.group(1) if match else None


# --- The services ------------------------------------------------------------------


def _get_json(url, headers):
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=10) as resp:
        return json.loads(resp.read(MAX_REPLY_BYTES).decode('utf-8'))


def _tmdb_get(path, api_key, **params):
    """TMDb's JSON for `path`, or None where it has nothing (404). Raises LookupFailed
    if it cannot be asked: no network, a bad key, a rate limit (waited out, as its
    Retry-After says, before another request goes)."""
    global _tmdb_rate_limit_until
    if time.time() < _tmdb_rate_limit_until:
        raise LookupFailed('TMDb is rate limiting')
    url = TMDB_BASE + path + ('?' + urllib.parse.urlencode(params) if params else '')
    try:
        return _get_json(url, {'User-Agent': METADATA_USER_AGENT, 'Authorization': f'Bearer {api_key}',
                               'Accept': 'application/json'})
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        if e.code == 429:
            try:
                wait = int(e.headers.get('Retry-After'))
            except (TypeError, ValueError):
                wait = 10
            _tmdb_rate_limit_until = time.time() + wait
        raise LookupFailed(f'TMDb: HTTP {e.code}') from e
    except (OSError, ValueError) as e:
        raise LookupFailed(f'TMDb: {e}') from e


def _omdb_get(api_key, **params):
    """OMDb's reply for these parameters, or None where it has no such title. Raises
    LookupFailed if it cannot be asked (an unusable or used-up key answers 200 with an
    Error text, which is not a "not found"). The key is in the address OMDb is
    asked, so no address is ever logged."""
    try:
        data = _get_json(OMDB_BASE + '?' + urllib.parse.urlencode({'apikey': api_key, **params}),
                         {'User-Agent': METADATA_USER_AGENT})
    except (OSError, ValueError) as e:
        raise LookupFailed(f'OMDb: {type(e).__name__}') from e
    if not isinstance(data, dict):
        raise LookupFailed('OMDb: unexpected reply')
    if data.get('Response') != 'True':
        error = str(data.get('Error', ''))
        if 'not found' in error.lower():
            return None
        raise LookupFailed(f'OMDb: {error or "no reply"}')
    return data


def _omdb_record(data, media_type):
    """OMDb's reply as a metadata dict ("N/A" and anything unusable become None)."""
    def text(key):
        v = data.get(key)
        return None if v in (None, '', 'N/A') else v

    def number(key, cast):
        try:
            return cast(text(key))
        except (TypeError, ValueError):
            return None

    return {
        'imdb_id': text('imdbID'), 'tmdb_id': None,
        'title': text('Title'), 'year': text('Year'), 'type': text('Type'),
        'imdb_rating': number('imdbRating', float), 'imdb_votes': text('imdbVotes'),
        'metascore': number('Metascore', int), 'ratings': data.get('Ratings') or [],
        'genre': text('Genre'), 'runtime': text('Runtime'), 'released': text('Released'),
        'overview': text('Plot'), 'language': text('Language'), 'country': text('Country'),
        'awards': text('Awards'), 'director': text('Director'), 'writer': text('Writer'),
        'actors': text('Actors'), 'poster': text('Poster'),
        'dvd_released': text('DVD'), 'box_office': text('BoxOffice'),
        'production': text('Production'), 'website': text('Website'),
        'total_seasons': number('totalSeasons', int),
        'source': 'omdb', 'media_type': media_type,
    }


def search_omdb(title, year=None, media_type='movie', api_key=None):
    """OMDb's best match for a title as a metadata dict, or None. Raises LookupFailed."""
    if not api_key:
        return None
    params = {'t': title, 'type': 'movie' if media_type == 'movie' else 'series', 'plot': 'full'}
    if year:
        params['y'] = year
    data = _omdb_get(api_key, **params)
    return _omdb_record(data, media_type) if data else None


def search_omdb_by_id(imdb_id, media_type='movie', api_key=None):
    """OMDb's record for an IMDb id (exact), or None. Raises LookupFailed."""
    if not api_key or not imdb_id:
        return None
    data = _omdb_get(api_key, i=imdb_id if imdb_id.startswith('tt') else 'tt' + imdb_id, plot='full')
    return _omdb_record(data, media_type) if data else None


def search_tmdb(title, year=None, media_type='movie', api_key=None):
    """TMDb's best match for a title as a metadata dict, or None. Raises LookupFailed."""
    if not api_key:
        return None
    params = {'query': title}
    if year:
        params['year'] = year
    data = _tmdb_get('/search/' + ('movie' if media_type == 'movie' else 'tv'), api_key, **params)
    results = (data or {}).get('results') or []
    if not results:
        return None
    r = results[0]
    return {
        'imdb_id': None,  # from the details
        'tmdb_id': str(r.get('id')),
        'title': r.get('title') or r.get('name'),
        'year': (r.get('release_date') or r.get('first_air_date') or '')[:4],
        'type': r.get('media_type', media_type),
        'imdb_rating': None, 'imdb_votes': None, 'metascore': None,
        'tmdb_rating': r.get('vote_average'), 'tmdb_votes': r.get('vote_count'),
        'popularity': r.get('popularity'), 'ratings': [],
        'genre': None, 'runtime': None,  # from the details
        'released': r.get('release_date') or r.get('first_air_date'),
        'overview': r.get('overview'), 'language': r.get('original_language'),
        'country': None, 'awards': None, 'director': None, 'writer': None, 'actors': None,
        'poster': f"{TMDB_IMAGE_BASE}{r['poster_path']}" if r.get('poster_path') else None,
        'total_seasons': r.get('number_of_seasons'), 'total_episodes': r.get('number_of_episodes'),
        'source': 'tmdb', 'media_type': media_type,
    }


def get_tmdb_details(tmdb_id, media_type='movie', api_key=None):
    """What a TMDb id adds to a search hit: genres, runtime, seasons, status, tagline,
    companies, countries, languages, the director and the first ten of the cast, and
    its IMDb id, in one request (credits and external ids ride along). None if TMDb
    has nothing under the id. Raises LookupFailed."""
    if not api_key or not tmdb_id:
        return None
    tmdb_type = 'movie' if media_type == 'movie' else 'tv'
    data = _tmdb_get(f'/{tmdb_type}/{tmdb_id}', api_key, append_to_response='credits,external_ids')
    if not isinstance(data, dict):
        return None
    if media_type == 'movie':
        runtime = data.get('runtime')
        imdb_id = data.get('imdb_id') or (data.get('external_ids') or {}).get('imdb_id')
    else:
        runtime = (data.get('episode_run_time') or [None])[0]
        imdb_id = (data.get('external_ids') or {}).get('imdb_id')
    credits_ = data.get('credits') or {}
    directors = [c['name'] for c in credits_.get('crew', []) if c.get('job') == 'Director' and c.get('name')]
    actors = [c['name'] for c in credits_.get('cast', [])[:10] if c.get('name')]
    return {
        'imdb_id': imdb_id or None,
        'genres': [g['name'] for g in data.get('genres', []) if g.get('name')],
        'runtime': f'{runtime} min' if runtime else None,
        'total_seasons': data.get('number_of_seasons'), 'total_episodes': data.get('number_of_episodes'),
        'status': data.get('status'), 'tagline': data.get('tagline'), 'homepage': data.get('homepage'),
        'production_companies': [c['name'] for c in data.get('production_companies', []) if c.get('name')],
        'production_countries': [c['name'] for c in data.get('production_countries', []) if c.get('name')],
        'spoken_languages': [x['english_name'] for x in data.get('spoken_languages', []) if x.get('english_name')],
        'director': ', '.join(directors) or None,
        'actors': ', '.join(actors) or None,
    }


# --- Looking a title up --------------------------------------------------------------


def _lookup(title, year, media_type, omdb_key, tmdb_key):
    """The metadata of a title from the services, or None if they have none. Raises
    LookupFailed when no service could be asked and none had an answer."""
    result = None
    failure = None
    if tmdb_key:
        try:
            result = search_tmdb(title, year, media_type, tmdb_key)
            if result:
                details = get_tmdb_details(result['tmdb_id'], media_type, tmdb_key)
                if details:
                    if details.get('genres'):
                        result['genre'] = ', '.join(details['genres'])
                    if details.get('imdb_id'):
                        result['imdb_id'] = details['imdb_id']
                    for field in DETAIL_FIELDS:
                        if details.get(field):
                            result[field] = details[field]
        except LookupFailed as e:
            failure = e
    if result is None and omdb_key:
        try:
            result = search_omdb(title, year, media_type, omdb_key)
        except LookupFailed as e:
            failure = failure or e
    elif result and omdb_key and result.get('imdb_id'):
        try:
            extra = search_omdb_by_id(result['imdb_id'], media_type, omdb_key)
        except LookupFailed as e:
            _log(f'OMDb enrichment skipped: {e}')
            extra = None
        for field in OMDB_ENRICH_FIELDS:
            if extra and extra.get(field) and not (field in ('director', 'actors') and result.get(field)):
                result[field] = extra[field]
    if result is None and failure:
        raise failure
    return result


def get_metadata(title, year=None, media_type='movie', omdb_key=None, tmdb_key=None):
    """Metadata for a title: from the cache, else from TMDb (search, details), with
    OMDb adding the IMDb rating and more (and answering alone when there is no TMDb
    key). The poster is fetched too. None if there is none, with a service's own
    "no such title" remembered for NEGATIVE_CACHE_TTL_DAYS; a lookup that could not
    be made is not remembered, nor is a missing key."""
    clean_title, parsed_year = _parse_title_year(title)
    year = year or parsed_year
    key = _make_key(clean_title, year, media_type)
    cached = _load_metadata_cache()
    if key in cached:
        return cached[key]
    if not (omdb_key or tmdb_key) or _make_negative_key(clean_title, year, media_type) in cached:
        return None
    try:
        result = _lookup(clean_title, year, media_type, omdb_key, tmdb_key)
    except LookupFailed as e:
        _log(f'metadata lookup of {clean_title!r} failed: {e}')
        return None
    if result is None:
        _mark_negative_cache(clean_title, year, media_type)
        return None
    result['cached_at'] = time.time()
    imdb_id, tmdb_id = result.get('imdb_id'), result.get('tmdb_id')
    if result.get('poster'):
        _cache_poster_image(result['poster'], key, imdb_id=imdb_id, tmdb_id=tmdb_id)

    def remember(cache):
        cache[key] = result
        if imdb_id:
            cache[f'imdb:{imdb_id}'] = result
        if tmdb_id:
            cache[f'tmdb:{tmdb_id}'] = result
    _update_metadata_cache(remember)
    return result


def refresh_metadata_cache(titles, media_types=None, omdb_key=None, tmdb_key=None):
    """Looks up the titles that have no cached answer (a thread's job: it asks the
    network). `titles` is a list of strings, `media_types` a list of the same length or
    one type ('movie' or 'series'). Titles with a year are tried first, and at most
    MAX_API_CALLS_PER_CYCLE are; a TMDb rate limit ends the cycle. Returns how many
    titles got metadata."""
    omdb_key = omdb_key if omdb_key is not None else load_omdb_api_key()
    tmdb_key = tmdb_key if tmdb_key is not None else load_tmdb_api_key()
    if not omdb_key and not tmdb_key:
        return 0
    if media_types is None:
        media_types = ['movie'] * len(titles)
    elif isinstance(media_types, str):
        media_types = [media_types] * len(titles)
    items = []
    for title, mtype in zip(titles, media_types):
        clean_title, year = _parse_title_year(title)
        items.append((year is not None, clean_title, year, mtype))
    items.sort(key=lambda item: not item[0])  # stable: titles with a year first
    found = tried = 0
    for _has_year, clean_title, year, mtype in items:
        if tried >= MAX_API_CALLS_PER_CYCLE or time.time() < _tmdb_rate_limit_until:
            break
        cache = _load_metadata_cache()
        if _make_key(clean_title, year, mtype) in cache or _make_negative_key(clean_title, year, mtype) in cache:
            continue
        tried += 1
        if get_metadata(clean_title, year, mtype, omdb_key, tmdb_key):
            found += 1
    return found


# --- What the hover shows ---------------------------------------------------------------


def format_metadata_for_tooltip(meta):
    """Format metadata dict into a tooltip string with markup.
    All user-provided text values are escaped for safe markup insertion."""
    if not meta:
        return None

    def esc(s):
        return html.escape(str(s))

    lines = []
    if meta.get('title'):
        year = f" ({esc(meta['year'])})" if meta.get('year') else ''
        lines.append(f'<b><span size="larger">{esc(meta["title"])}{year}</span></b>')
    # Ratings
    if meta.get('imdb_rating') is not None:
        lines.append(f'⭐ IMDb: {meta["imdb_rating"]:.1f}/10')
    if meta.get('tmdb_rating') is not None:
        lines.append(f'⭐ TMDb: {meta["tmdb_rating"]:.1f}/10')
    if meta.get('metascore') is not None:
        lines.append(f'🎯 Metascore: {meta["metascore"]}/100')
    if meta.get('popularity') is not None:
        lines.append(f'📈 Popularity: {meta["popularity"]:.0f}')
    # Details
    if meta.get('genre'):
        lines.append(f'🎭 {esc(meta["genre"])}')
    if meta.get('runtime'):
        lines.append(f'⏱ {esc(meta["runtime"])}')
    if meta.get('released'):
        lines.append(f'📅 Released: {esc(meta["released"])}')
    if meta.get('language'):
        lines.append(f'🌐 Language: {esc(meta["language"])}')
    if meta.get('country'):
        lines.append(f'🌍 Country: {esc(meta["country"])}')
    if meta.get('director'):
        lines.append(f'🎬 Director: {esc(meta["director"])}')
    if meta.get('actors'):
        actors = esc(meta['actors'][:100] + ('…' if len(meta['actors']) > 100 else ''))
        lines.append(f'👥 Cast: {actors}')
    if meta.get('total_seasons'):
        lines.append(f'📺 Seasons: {meta["total_seasons"]}')
    if meta.get('total_episodes'):
        lines.append(f'📺 Episodes: {meta["total_episodes"]}')
    if meta.get('status'):
        lines.append(f'📌 Status: {esc(meta["status"])}')
    if meta.get('tagline'):
        tagline = esc(meta['tagline'][:100] + ('…' if len(meta['tagline']) > 100 else ''))
        lines.append(f'💬 "{tagline}"')
    if meta.get('overview'):
        overview = esc(meta['overview'][:300] + ('…' if len(meta['overview']) > 300 else ''))
        lines.append(f'\n{overview}')

    return '\n'.join(lines) if lines else None


def get_cached_metadata(title, media_type='movie', url=None, imdb_id=None, tmdb_id=None):
    """The cached metadata dict for a title (by IMDb id, TMDb id, then title and year,
    the year from the url if the title has none), or None. Only what is cached: it
    never goes to the network."""
    cache = _load_metadata_cache()
    for key in (f'imdb:{imdb_id}' if imdb_id else None, f'tmdb:{tmdb_id}' if tmdb_id else None):
        if key in cache:
            return cache[key]
    clean_title, year = _parse_title_year(title)
    if year is None and url:
        year = _extract_year_from_url(url)
    return cache.get(_make_key(clean_title, year, media_type))


def load_omdb_api_key():
    """omdb_key from [media] of config.conf, or None."""
    return _media_setting('omdb_key')


def load_tmdb_api_key():
    """tmdb_key (an API Read Access Token) from [media] of config.conf, or None."""
    return _media_setting('tmdb_key')
