#!/usr/bin/env python3
"""
flux-tray media plugin for fsonline.one
Supports series (/serial/...) and movies (/film/...).
Uses vidmoly/kaembed.net only (no Selenium/filemoon).

The plugin only finds the stream (list_episodes, resolve); the app downloads it
(HLS with ffmpeg, subtitles, progress, resume of nothing it cannot resume).
"""

import json
import re
import time
import unicodedata
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup

NAME = 'fsonline_one'
ORDER = 'oldest'

BASE_URL = 'https://fsonline.one'
AJAX_ENDPOINT = '/ajax/ajax.php'
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
STREAM_USER_AGENT = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                     '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
SUBTITLE_LANGUAGES = ('ro', 'en')  # saved as <name>.ro.vtt, <name>.en.vtt; mpv loads both

_session = requests.Session()
_session.headers.update({'User-Agent': USER_AGENT, 'Referer': BASE_URL})

# --- Discovery feed (sitemap) ------------------------------------------------

NS = {'sm': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
MAX_SITEMAP_AGE = timedelta(hours=24)
MAX_NEW_ITEMS_PER_CHECK = 20

TYPE_MAP = {
    'movies': ('film', 'movie'),
    'series': ('serial', 'series'),
}

# Direct sitemap URLs for the first page of each type (used by find())
SITEMAP_URLS = {
    'movies': 'https://fsonline.one/sitemap/sitemap.php?type=movies&page=1',
    'series': 'https://fsonline.one/sitemap/sitemap.php?type=series&page=1',
    'episodes': 'https://fsonline.one/sitemap/sitemap.php?type=episodes&page=1',
}

# Cache for episodes/movies sitemap pages (separate from find cache)
_sitemap_cache = {}  # (type, page) -> (timestamp, [(url, lastmod), ...])
SITEMAP_CACHE_SECONDS = 300  # 5 minutes


def _fetch_sitemap_with_lastmod(url):
    """Fetch a sitemap page and return list of (url, lastmod_timestamp) tuples."""
    try:
        root = ET.fromstring(_fetch_sitemap(url))
    except (OSError, ValueError, ET.ParseError):
        return None
    items = []
    for url_elem in root.findall('sm:url', NS):
        loc = url_elem.find('sm:loc', NS)
        lastmod = url_elem.find('sm:lastmod', NS)
        if loc is not None and loc.text:
            url_text = loc.text.strip()
            lastmod_ts = None
            if lastmod is not None and lastmod.text:
                try:
                    lastmod_ts = datetime.fromisoformat(lastmod.text.strip().replace('Z', '+00:00')).timestamp()
                except Exception:
                    pass
            items.append((url_text, lastmod_ts))
    return items


def _sitemap_page_with_lastmod(kind, page):
    """Fetch a sitemap page with lastmod timestamps, cached for SITEMAP_CACHE_SECONDS."""
    cached = _sitemap_cache.get((kind, page))
    if cached and time.time() - cached[0] < SITEMAP_CACHE_SECONDS:
        return cached[1]
    url = f'{BASE_URL}/sitemap/sitemap.php?type={kind}&page={page}'
    items = _fetch_sitemap_with_lastmod(url)
    if items is not None:
        _sitemap_cache[(kind, page)] = (time.time(), items)
    return items


def _extract_series_url(episode_url):
    """Convert /episod/series-name-2024/s02-e06/ to /serial/series-name-2024-online-subtitrat/"""
    # /episod/harlan-coben-s-final-twist-2026-online-subtitrat/s02-e06/
    parts = episode_url.rstrip('/').split('/')
    if len(parts) >= 5 and parts[3] == 'episod':
        series_slug = parts[4]
        # Remove season/episode from slug if present
        series_slug = re.sub(r'/s\d+-e\d+.*$', '', series_slug)
        # Slug from episode URL already has -online-subtitrat, don't add it again
        if not series_slug.endswith('-online-subtitrat'):
            series_slug = f'{series_slug}-online-subtitrat'
        return f'{BASE_URL}/serial/{series_slug}/'
    return None


def _extract_movie_url(movie_url):
    """Ensure movie URL is in correct format."""
    # Movie URLs from sitemap are already in correct format
    return movie_url if '/film/' in movie_url else None


def fetch_new_episodes(since_timestamp, watch_titles):
    """Returns set of series URLs that have new episodes since `since_timestamp`
    and match titles in `watch_titles` (set of normalized titles).
    Only reads pages until items are older than since_timestamp."""
    new_series = set()
    page = 1
    while True:
        items = _sitemap_page_with_lastmod('episodes', page)
        if not items:
            break
        page_has_new = False
        for ep_url, lastmod in items:
            if lastmod and lastmod > since_timestamp:
                page_has_new = True
                series_url = _extract_series_url(ep_url)
                if series_url:
                    # Check if this series matches any watched title
                    series_slug = series_url.rstrip('/').split('/')[-1]
                    series_slug = re.sub(r'-online-subtitrat.*$', '', series_slug, flags=re.IGNORECASE)
                    series_norm = _norm_title(series_slug)
                    if series_norm in watch_titles:
                        new_series.add(series_url)
            else:
                # Sitemap is sorted newest first, so we can stop
                return new_series
        if not page_has_new:
            break
        page += 1
    return new_series


def fetch_new_movies(since_timestamp, watch_titles):
    """Returns set of movie URLs that are new since `since_timestamp`
    and match titles in `watch_titles`."""
    new_movies = set()
    page = 1
    while True:
        items = _sitemap_page_with_lastmod('movies', page)
        if not items:
            break
        page_has_new = False
        for movie_url, lastmod in items:
            if lastmod and lastmod > since_timestamp:
                page_has_new = True
                movie_url = _extract_movie_url(movie_url)
                if movie_url:
                    # Check if this movie matches any watched title
                    movie_slug = movie_url.rstrip('/').split('/')[-1]
                    movie_slug = re.sub(r'-online-subtitrat.*$', '', movie_slug, flags=re.IGNORECASE)
                    movie_norm = _norm_title(movie_slug)
                    if movie_norm in watch_titles:
                        new_movies.add(movie_url)
            else:
                return new_movies
        if not page_has_new:
            break
        page += 1
    return new_movies


def _norm_title(text):
    """A title as it is compared: no accents, lower case, words joined by one dash."""
    text = unicodedata.normalize('NFKD', text or '')
    text = ''.join(c for c in text if not unicodedata.combining(c)).lower()
    return '-'.join(re.findall(r'[a-z0-9]+', text))


def _slug_parts(url):
    """(normalised title, year or None) of a page's address, read as _slug_to_title reads it."""
    slug = url.rstrip('/').split('/')[-1]
    slug = re.sub(r'-online-subtitrat.*$', '', slug, flags=re.IGNORECASE)
    slug = re.sub(r'-subtitrat.*$', '', slug, flags=re.IGNORECASE)
    for q in ('cam', 'ts', 'tc', 'scr', 'dvdrip', 'webrip', 'bluray', 'hdrip', 'hdtv', 'hd'):
        slug = re.sub(rf'-{q}(-|$)', r'\1', slug, flags=re.IGNORECASE)
    year = re.search(r'[-_](20\d{2}|19\d{2})$', slug)
    return _norm_title(re.sub(r'[-_](20\d{2}|19\d{2})$', '', slug)), (year.group(1) if year else None)


def _sitemap_page(kind, page):
    """The addresses on a page of the sitemap of films or series (read at most once an hour), or
    None if the page cannot be read."""
    cached = _find_pages.get((kind, page))
    if cached and time.time() - cached[0] < FIND_CACHE_SECONDS:
        return cached[1]
    try:
        root = ET.fromstring(_fetch_sitemap(f'{BASE_URL}/sitemap/sitemap.php?type={kind}&page={page}'))
    except (OSError, ValueError, ET.ParseError):
        return None
    urls = [loc.text.strip() for loc in root.findall('sm:url/sm:loc', NS) if loc.text]
    _find_pages[(kind, page)] = (time.time(), urls)
    return urls


MAX_VERIFY = 6  # pages opened to check an IMDb id


def _page_ids(url):
    """The IMDb and TMDb ids a title page declares (window.DFO_COMMUNITY_V5), {} if it declares none,
    None if the page cannot be read."""
    try:
        return _extract_external_ids(_get_soup(url))
    except Exception:
        return None


def find(title, year=None, imdb_id=None, kind='movie'):
    """The address on this site of a title, or None; it never raises. Pages are named
    <title>-<year>-online-subtitrat, so that address is tried first (one request): a page that is
    there is the title's if it declares its IMDb id (a page that declares none, such as an error
    page that answers 200, is not it). Failing that, the sitemap pages, newest first, are searched
    for an address that names the title, to a year either way (the site's year and IMDb's can
    differ); with an IMDb id, every page of that name is checked against it, whatever its year,
    and one that says it is another title's is not the one."""
    wanted = _norm_title(title)
    if not wanted:
        return None
    kind_name, prefix = ('movies', 'film') if kind == 'movie' else ('series', 'serial')
    if year and re.fullmatch(r'(?:19|20)\d{2}', str(year)):
        guess = f'{BASE_URL}/{prefix}/{wanted}-{year}-online-subtitrat/'
        ids = _page_ids(guess)
        if ids and (ids.get('imdb_id') == imdb_id if imdb_id else True):
            return guess
    exact, near, other = [], [], []
    for page in range(1, MAX_FIND_PAGES + 1):
        urls = _sitemap_page(kind_name, page)
        if not urls:
            break
        for url in urls:
            if f'/{prefix}/' not in url:
                continue
            base, slug_year = _slug_parts(url)
            if slug_year and f'{base}-{slug_year}' == wanted:
                base, slug_year = wanted, None  # the last word of the title looks like a year
            if base != wanted:
                continue
            if not year or not slug_year or slug_year == str(year):
                exact.append(url)
            elif abs(int(slug_year) - int(year)) <= 1:
                near.append(url)
            else:
                other.append(url)
    if not imdb_id:
        return (exact + near or [None])[0]
    weak = []
    for url in (exact + near + other)[:MAX_VERIFY]:
        page_id = (_page_ids(url) or {}).get('imdb_id')
        if page_id == imdb_id:
            return url  # the page says it is this title
        if not page_id and url not in other:
            weak.append(url)  # it says nothing: right if there is nothing better
    return weak[0] if weak else None


def _extract_quality_from_slug(url: str) -> str | None:
    """Extract quality hint from URL slug (e.g., 'cam', 'ts', 'hd', 'dvdrip')."""
    slug = url.rstrip('/').split('/')[-1].lower()
    # Common quality markers in slug
    quality_markers = ['cam', 'ts', 'tc', 'scr', 'dvdrip', 'webrip', 'bluray', 'hdrip', 'hdtv', 'hd']
    for q in quality_markers:
        if f'-{q}-' in slug or slug.endswith(f'-{q}') or f'-{q}.' in slug:
            return q.upper()
    return None


# find(): where a title is on this site. The sitemap lists the pages newest first; a title that is
# being looked for is a recent one, so a few pages are enough, and each is read once an hour.
MAX_FIND_PAGES = 12
FIND_CACHE_SECONDS = 3600
_find_pages = {}  # (type, page) -> (when it was read, [urls])


def _fetch_sitemap(url):
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'application/xml,application/xhtml+xml,text/html;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Referer': 'https://fsonline.one/',
    })
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.read().decode('utf-8')


def _parse_lastmod(text):
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace('Z', '+00:00'))
    except Exception:
        return None


def _slug_to_title(url, item_type):
    """Convert URL slug to display title.
    Movie: '[movie-name] [movie-year]'
    Series: '[show-name] [year] [s01e04] - [episode-name]' (but for discovery we only have series URL, not episode)
    """
    slug = url.rstrip('/').split('/')[-1]
    slug = re.sub(r'-online-subtitrat.*$', '', slug, flags=re.IGNORECASE)
    slug = re.sub(r'-subtitrat.*$', '', slug, flags=re.IGNORECASE)
    # Strip quality markers from slug before extracting year (cam, ts, hd, etc.)
    quality_markers = ['cam', 'ts', 'tc', 'scr', 'dvdrip', 'webrip', 'bluray', 'hdrip', 'hdtv', 'hd']
    for q in quality_markers:
        slug = re.sub(rf'-{q}(-|$)', r'\1', slug, flags=re.IGNORECASE)
    year_match = re.search(r'[-_](20\d{2}|19\d{2})$', slug)
    year = f' ({year_match.group(1)})' if year_match else ''
    slug = re.sub(r'[-_](20\d{2}|19\d{2})$', '', slug)
    base = slug.replace('-', ' ').replace('_', ' ').title()
    return base + year


# --- Media source handling ---------------------------------------------------

def matches(source: str) -> bool:
    """Match fsonline.one series and movie URLs."""
    return 'fsonline.one' in source and ('/serial/' in source or '/film/' in source or '/episod/' in source)


def _get_soup(url: str) -> BeautifulSoup:
    resp = _session.get(url, timeout=30)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, 'html.parser')


def _extract_token(soup: BeautifulSoup) -> str:
    """Extract data-token from page."""
    for sel in ('#main-wrapper[data-token]', '.watch_block[data-token]'):
        el = soup.select_one(sel)
        if el and el.get('data-token'):
            return el['data-token']
    for el in soup.find_all(attrs={'data-token': True}):
        token = el.get('data-token')
        if token and len(token) > 50:
            return token
    raise ValueError('Could not extract data-token')


def _get_servers(token: str, content_type: str) -> list:
    """Get server embed URLs from AJAX endpoint."""
    field = 'players' if content_type == 'movie' else 'players_show'
    resp = _session.post(
        urllib.parse.urljoin(BASE_URL, AJAX_ENDPOINT),
        data={field: token},
        timeout=30,
    )
    resp.raise_for_status()
    servers = resp.json()
    if isinstance(servers, dict) and servers.get('error'):
        raise ValueError(f"Server error: {servers['error']}")
    return servers if isinstance(servers, list) else ([servers] if servers else [])


def _pick_vidmoly(servers: list) -> dict | None:
    """Prefer vidmoly/kaembed.net (no Selenium needed)."""
    for s in servers:
        link = s.get('link', '')
        if 'vidmoly' in link or 'kaembed' in link:
            return s
    return servers[0] if servers else None


def _extract_subtitle_url(server: dict) -> str | None:
    """Extract subtitle API URL from server link."""
    link = server.get('link', '')
    if not link:
        return None
    parsed = urllib.parse.urlparse(link)
    query = urllib.parse.parse_qs(parsed.query)
    for param in ('sub.info', 'subget', 'sub'):
        if param in query:
            return query[param][0]
    return None


def _fetch_subtitles(sub_api_url: str) -> list:
    """The subtitles on offer in SUBTITLE_LANGUAGES, each tagged with its own language."""
    resp = _session.get(sub_api_url, timeout=30)
    resp.raise_for_status()
    offered = resp.json()
    found = []
    for lang in SUBTITLE_LANGUAGES:
        for s in offered if isinstance(offered, list) else []:
            if s.get('file') and s.get('label', '').lower().startswith(lang):
                found.append({'url': s['file'], 'lang': lang, 'ext': '.vtt'})
                break
    return found


def _extract_vidmoly_m3u8(embed_url: str) -> str | None:
    """Extract m3u8 from vidmoly/kaembed.net embed page (regex, no Selenium)."""
    resp = _session.get(embed_url, timeout=30)
    resp.raise_for_status()
    html = resp.text

    m = re.search(r"player\.setup\(\s*\{[^}]*sources\s*:\s*\[\s*\{\s*file\s*:\s*['\"]([^'\"]+\.m3u8[^'\"]*)['\"]", html, re.DOTALL)
    if m:
        return m.group(1)

    for m in re.findall(r"file\s*:\s*['\"](https?://[^'\"]+\.m3u8[^'\"]*)['\"]", html):
        if 'master.m3u8' in m or 'playlist.m3u8' in m:
            return m

    m = re.search(r"(https?://[^'\"]*vmpx\.online[^'\"]*\.m3u8[^'\"]*)", html)
    if m:
        return m.group(1)

    return None


def _clean_title(soup: BeautifulSoup, fallback: str, suffixes: tuple) -> str:
    el = soup.select_one("h1.heading-name a, h1.heading-name, meta[property='og:title']")
    if el:
        title = el.get('content', '').strip() if el.name == 'meta' else el.get_text(strip=True)
    else:
        title = fallback
    title = re.sub(r'\s*[-|]\s*F?Sonline.*$', '', title, flags=re.IGNORECASE)
    for suffix in suffixes:
        title = re.sub(rf'\s*{suffix}.*$', '', title, flags=re.IGNORECASE)
    return title.strip()


def _extract_external_ids(soup: BeautifulSoup) -> dict:
    """Extract IMDb/TMDb IDs from window.DFO_COMMUNITY_V5 JavaScript variable."""
    ids = {}
    for script in soup.find_all('script'):
        if not script.string:
            continue
        text = script.string
        if 'DFO_COMMUNITY_V5' in text:
            # Extract the JSON object: window.DFO_COMMUNITY_V5={...}
            match = re.search(r'window\.DFO_COMMUNITY_V5\s*=\s*(\{.*?\});?\s*$', text, re.MULTILINE | re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group(1))
                    context = data.get('context', {})
                    if context.get('imdbid'):
                        ids['imdb_id'] = context['imdbid']
                    if context.get('tmdbid'):
                        ids['tmdb_id'] = str(context['tmdbid'])
                except Exception:
                    pass
            break
    return ids


def _extract_quality(soup: BeautifulSoup) -> str | None:
    """Extract quality from btn-quality button on the page.
    Returns 'HD', 'CAM', 'TS', 'CAM-TS-V2', etc. or None if not found."""
    btn = soup.select_one('button.btn-quality, .btn-quality')
    if btn:
        text = btn.get_text(strip=True).upper()
        return text
    return None


def _is_hd_quality(quality: str | None) -> bool:
    """Check if quality is HD (acceptable)."""
    if not quality:
        return True  # Default to accepting if unknown
    quality = quality.upper()
    # Only accept HD quality
    return quality == 'HD'


def _get_series_title(soup: BeautifulSoup) -> str:
    return _clean_title(soup, 'Unknown Series', ('Serial Online Subtitrat', 'Online Subtitrat'))


def _get_movie_title(soup: BeautifulSoup) -> str:
    return _clean_title(soup, 'Unknown Movie', ('Film Online Subtitrat', 'Online Subtitrat'))


def list_episodes(source: str):
    """Return (title, episodes) for a series or movie URL, oldest first.
    For movies, only returns HD quality versions; non-HD (CAM, TS, etc.) are skipped."""
    soup = _get_soup(source)

    # Extract external IDs from page (IMDb, TMDb)
    external_ids = _extract_external_ids(soup)

    if '/film/' in source:
        # Check quality for movies
        quality = _extract_quality(soup)
        if not _is_hd_quality(quality):
            # Return empty list to indicate this movie should be skipped
            title = _get_movie_title(soup)
            return title, []

        title = _get_movie_title(soup)
        episode = {'id': source, 'title': title, 'ref': source}
        episode.update(external_ids)
        return title, [episode]

    title = _get_series_title(soup)
    episodes = {}
    for link in soup.find_all('a', href=True):
        href = link['href']
        m = re.search(r'/s(\d+)-e(\d+)/?$', href)
        if '/episod/' in href and m:
            full_url = urllib.parse.urljoin(BASE_URL, href)
            season, episode = int(m.group(1)), int(m.group(2))
            name = re.sub(r'^\s*Episod\s+\d+\s*:?\s*', '', link.get_text(strip=True), flags=re.IGNORECASE)
            ep_data = {
                'id': full_url,
                'title': name or f'Episod {episode}',
                'season': season,
                'episode': episode,
                'ref': full_url,
            }
            ep_data.update(external_ids)  # Add series-level IDs to each episode
            episodes.setdefault(full_url, ep_data)
    return title, sorted(episodes.values(), key=lambda e: (e['season'], e['episode']))


def resolve(episode: dict):
    """The stream and subtitles of an episode, looked up when it is downloaded."""
    url = episode.get('ref') or episode['url']
    soup = _get_soup(url)

    token = _extract_token(soup)
    servers = _get_servers(token, 'movie' if '/film/' in url else 'episode')
    server = _pick_vidmoly(servers)
    if not server:
        raise ValueError('No vidmoly server found')

    embed_url = server.get('link')
    if not embed_url:
        raise ValueError('No embed URL in server')

    m3u8 = _extract_vidmoly_m3u8(embed_url)
    if not m3u8:
        raise ValueError('Could not extract m3u8 from vidmoly embed')

    sub_api = _extract_subtitle_url(server)
    return {
        'video': {'url': m3u8, 'ext': '.ts', 'headers': {'Referer': embed_url, 'User-Agent': STREAM_USER_AGENT}},
        'subs': _fetch_subtitles(sub_api) if sub_api else [],
    }