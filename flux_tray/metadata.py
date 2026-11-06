"""Media metadata: OMDB/TMDb lookup for hover preview (poster, rating, excerpt).

Uses only stdlib (urllib, json). Cache in ~/.config/flux-tray/metadata_cache.json.
Poster images cached in ~/.config/flux-tray/posters/.
"""

import html
import json
import os
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


METADATA_CACHE_FILE = Path.home() / '.config' / 'flux-tray' / 'metadata_cache.json'
POSTER_CACHE_DIR = Path.home() / '.config' / 'flux-tray' / 'posters'
METADATA_CACHE_TTL_DAYS = 30
POSTER_CACHE_TTL_DAYS = 90
# Negative cache: failed lookups cached for this many days to avoid re-querying
NEGATIVE_CACHE_TTL_DAYS = 7
# Max API calls per refresh cycle (counts both successes and failures)
MAX_API_CALLS_PER_CYCLE = 10

# OMDB API
OMDB_BASE = 'http://www.omdbapi.com/'

# TMDb API v4 (Bearer token auth)
TMDB_BASE = 'https://api.themoviedb.org/3'
TMDB_IMAGE_BASE = 'https://image.tmdb.org/t/p/w300'
# User-Agent matching TheIntroDB (https://github.com/TheIntroDB)
TMDB_USER_AGENT = 'TheIntroDB/1.0 (+https://github.com/TheIntroDB)'
# Global rate limit tracking for TMDb
_tmdb_rate_limit_until = 0.0


def _tmdb_request(url, api_key, timeout=10):
    """Make a TMDb API request with rate limit handling (Retry-After header).
    Returns (data_dict, headers) or (None, None) on failure.
    Respects global rate limit across all TMDb calls."""
    global _tmdb_rate_limit_until
    import time
    now = time.time()
    if now < _tmdb_rate_limit_until:
        _log(f'TMDb rate limited, waiting until {_tmdb_rate_limit_until:.0f}')
        return None, None
    try:
        req = urllib.request.Request(
            url,
            headers={
                'User-Agent': TMDB_USER_AGENT,
                'Authorization': f'Bearer {api_key}',
                'Accept': 'application/json',
            }
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
            # Check for Retry-After header (rate limit)
            retry_after = resp.headers.get('Retry-After')
            if retry_after:
                try:
                    _tmdb_rate_limit_until = time.time() + int(retry_after)
                    _log(f'TMDb rate limit hit, retry after {retry_after}s (until {_tmdb_rate_limit_until:.0f})')
                except ValueError:
                    pass  # Invalid Retry-After value
            return data, resp.headers
    except urllib.error.HTTPError as e:
        if e.code == 429:  # Too Many Requests
            retry_after = e.headers.get('Retry-After')
            if retry_after:
                try:
                    _tmdb_rate_limit_until = time.time() + int(retry_after)
                    _log(f'TMDb 429 rate limit, retry after {retry_after}s (until {_tmdb_rate_limit_until:.0f})')
                except ValueError:
                    pass
        _log(f'TMDb HTTP error {e.code}: {e.reason}')
        return None, None
    except Exception as e:
        _log(f'TMDb request error: {e}')
        return None, None


def _load_metadata_cache():
    if METADATA_CACHE_FILE.exists():
        try:
            data = json.loads(METADATA_CACHE_FILE.read_text())
            # Clean old entries (both positive and negative)
            now = time.time()
            cleaned = {}
            for k, v in data.items():
                cached_at = v.get('cached_at', 0)
                # Negative cache entries have 'negative': True
                if v.get('negative'):
                    ttl = NEGATIVE_CACHE_TTL_DAYS * 86400
                else:
                    ttl = METADATA_CACHE_TTL_DAYS * 86400
                if now - cached_at < ttl:
                    cleaned[k] = v
            return cleaned
        except Exception:
            pass
    return {}


def _save_metadata_cache(cache):
    METADATA_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    METADATA_CACHE_FILE.write_text(json.dumps(cache))


def _make_negative_key(title, year, media_type):
    """Create a negative cache key for a failed lookup."""
    clean_title, _ = _parse_title_year(title)
    year = year or ''
    return f'neg:{clean_title.lower()}:{year}:{media_type}'


def _is_negative_cached(title, year, media_type):
    """Check if a lookup has failed recently (negative cache)."""
    cache = _load_metadata_cache()
    neg_key = _make_negative_key(title, year, media_type)
    return neg_key in cache


def _mark_negative_cache(title, year, media_type):
    """Record a failed lookup in the negative cache."""
    cache = _load_metadata_cache()
    neg_key = _make_negative_key(title, year, media_type)
    cache[neg_key] = {'negative': True, 'cached_at': time.time()}
    _save_metadata_cache(cache)


def _load_poster_cache():
    """Load poster cache index."""
    index_file = POSTER_CACHE_DIR / 'index.json'
    if index_file.exists():
        try:
            data = json.loads(index_file.read_text())
            now = time.time()
            cleaned = {}
            for k, v in data.items():
                if now - v.get('cached_at', 0) < POSTER_CACHE_TTL_DAYS * 86400:
                    cleaned[k] = v
            return cleaned
        except Exception:
            pass
    return {}


def _save_poster_cache(cache):
    POSTER_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    index_file = POSTER_CACHE_DIR / 'index.json'
    index_file.write_text(json.dumps(cache))


def _get_poster_extension(url):
    """Extract file extension from poster URL."""
    if not url:
        return '.jpg'
    parsed = urllib.parse.urlparse(url)
    path = parsed.path
    ext = os.path.splitext(path)[1]
    return ext if ext in ('.jpg', '.jpeg', '.png', '.webp') else '.jpg'


def _cache_poster_image(poster_url, media_key, imdb_id=None, tmdb_id=None):
    """Download and cache poster image locally. Returns local file path or None.
    Uses TMDB/IMDb ID as cache key when available to avoid duplicates from title variations."""
    if not poster_url or poster_url == 'N/A':
        return None
    try:
        # Ensure cache directory exists
        POSTER_CACHE_DIR.mkdir(parents=True, exist_ok=True)

        # Use ID-based key when available for better deduplication
        cache_key = media_key
        if tmdb_id:
            cache_key = f'tmdb:{tmdb_id}'
        elif imdb_id:
            cache_key = f'imdb:{imdb_id}'

        # Check if already cached
        poster_cache = _load_poster_cache()
        if cache_key in poster_cache:
            local_path = poster_cache[cache_key].get('path')
            if local_path and os.path.exists(local_path):
                return local_path

        # Download poster - use TMDb User-Agent for TMDb images
        ua = TMDB_USER_AGENT if 'image.tmdb.org' in poster_url else 'flux-tray/1.0'
        req = urllib.request.Request(poster_url, headers={'User-Agent': ua})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read()

        # Save to cache
        ext = _get_poster_extension(poster_url)
        filename = f'{cache_key.replace(":", "_").replace("/", "_")}{ext}'
        local_path = POSTER_CACHE_DIR / filename
        local_path.write_bytes(data)

        # Update index
        poster_cache[cache_key] = {
            'path': str(local_path),
            'url': poster_url,
            'cached_at': time.time(),
        }
        _save_poster_cache(poster_cache)
        return str(local_path)
    except Exception:
        return None


def get_cached_poster(title, media_type='movie', imdb_id=None, tmdb_id=None):
    """Get cached poster image path for a title.
    Uses ID-based lookup first when available to avoid title variation duplicates."""
    # Try ID-based keys first (most accurate)
    poster_cache = _load_poster_cache()
    if tmdb_id:
        key = f'tmdb:{tmdb_id}'
        if key in poster_cache:
            path = poster_cache[key].get('path')
            if path and os.path.exists(path):
                return path
    if imdb_id:
        key = f'imdb:{imdb_id}'
        if key in poster_cache:
            path = poster_cache[key].get('path')
            if path and os.path.exists(path):
                return path

    # Fall back to title/year lookup
    clean_title, year = _parse_title_year(title)
    key = _make_key(clean_title, year, media_type)
    if key in poster_cache:
        path = poster_cache[key].get('path')
        if path and os.path.exists(path):
            return path
    return None


def _make_key(title, year, media_type):
    """Cache key from title, year, and type (movie/series)."""
    return f'{media_type}:{title.lower()}:{year or "unknown"}'


def _parse_title_year(title):
    """Extract year from title like 'Movie Name (2023)' or 'Show Name 2023'.
    Also decodes HTML entities (e.g., &#8211; -> –)."""
    import html
    title = html.unescape(title.strip())
    # Match (YYYY) at end
    match = re.search(r'\(?(19\d{2}|20\d{2})\)?$', title)
    if match:
        year = match.group(1)
        clean = title[:match.start()].strip()
        return clean, year
    # Match YYYY at end (space separated)
    match = re.search(r'\s+(19\d{2}|20\d{2})$', title)
    if match:
        year = match.group(1)
        clean = title[:match.start()].strip()
        return clean, year
    return title, None


def _extract_year_from_url(url):
    """Extract year from URL slug like '/film/sentient-2026-online-subtitrat/'. """
    if not url:
        return None
    # Match YYYY in URL path (e.g., -2026- or -2026)
    match = re.search(r'[-_](20\d{2}|19\d{2})[-_/.]', url)
    if match:
        return match.group(1)
    # Match YYYY at end of path before extension
    match = re.search(r'[-_](20\d{2}|19\d{2})$', url.rstrip('/'))
    if match:
        return match.group(1)
    return None


def search_omdb(title, year=None, media_type='movie', api_key=None):
    """Search OMDB for movie/series. Returns dict with ALL available fields."""
    if not api_key:
        return None
    try:
        query = urllib.parse.quote(title)
        omdb_type = 'movie' if media_type == 'movie' else 'series'
        url = f'{OMDB_BASE}?apikey={api_key}&t={query}&type={omdb_type}&plot=full'
        if year:
            url += f'&y={year}'
        req = urllib.request.Request(url, headers={'User-Agent': 'flux-tray/1.0'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        if data.get('Response') != 'True':
            return None
        return {
            # IDs
            'imdb_id': data.get('imdbID'),
            'tmdb_id': None,  # Filled by enrichment
            # Basic info
            'title': data.get('Title'),
            'year': data.get('Year'),
            'type': data.get('Type'),  # movie/series/episode
            # Ratings
            'imdb_rating': float(data.get('imdbRating')) if data.get('imdbRating') != 'N/A' else None,
            'imdb_votes': data.get('imdbVotes') if data.get('imdbVotes') != 'N/A' else None,
            'metascore': int(data.get('Metascore')) if data.get('Metascore') != 'N/A' else None,
            'ratings': data.get('Ratings', []),  # List of {Source, Value}
            # Details
            'genre': data.get('Genre') if data.get('Genre') != 'N/A' else None,
            'runtime': data.get('Runtime') if data.get('Runtime') != 'N/A' else None,
            'released': data.get('Released') if data.get('Released') != 'N/A' else None,
            'overview': data.get('Plot') if data.get('Plot') != 'N/A' else None,
            'language': data.get('Language') if data.get('Language') != 'N/A' else None,
            'country': data.get('Country') if data.get('Country') != 'N/A' else None,
            'awards': data.get('Awards') if data.get('Awards') != 'N/A' else None,
            # People
            'director': data.get('Director') if data.get('Director') != 'N/A' else None,
            'writer': data.get('Writer') if data.get('Writer') != 'N/A' else None,
            'actors': data.get('Actors') if data.get('Actors') != 'N/A' else None,
            # Poster
            'poster': data.get('Poster') if data.get('Poster') != 'N/A' else None,
            # Series-specific
            'total_seasons': int(data.get('totalSeasons')) if data.get('totalSeasons') and data.get('totalSeasons') != 'N/A' else None,
            # Metadata
            'source': 'omdb',
            'media_type': media_type,
        }
    except Exception:
        return None


def search_tmdb(title, year=None, media_type='movie', api_key=None):
    """Search TMDb v4 for movie/series. Returns dict with ALL available fields.
    Uses Bearer token authentication (v4 API)."""
    if not api_key:
        return None
    try:
        query = urllib.parse.quote(title)
        tmdb_type = 'movie' if media_type == 'movie' else 'tv'
        url = f'{TMDB_BASE}/search/{tmdb_type}?query={query}'
        if year:
            url += f'&year={year}'
        data, _ = _tmdb_request(url, api_key)
        if data is None:
            return None
        results = data.get('results', [])
        if not results:
            return None
        r = results[0]
        return {
            # IDs
            'imdb_id': None,  # Filled by enrichment
            'tmdb_id': str(r.get('id')),
            # Basic info
            'title': r.get('title') or r.get('name'),
            'year': (r.get('release_date') or r.get('first_air_date') or '')[:4],
            'type': r.get('media_type', media_type),  # movie/tv
            # Ratings
            'imdb_rating': None,
            'imdb_votes': None,
            'metascore': None,
            'tmdb_rating': r.get('vote_average'),
            'tmdb_votes': r.get('vote_count'),
            'popularity': r.get('popularity'),
            'ratings': [],
            # Details
            'genre': None,  # Filled by get_tmdb_details
            'runtime': None,  # Filled by get_tmdb_details
            'released': r.get('release_date') or r.get('first_air_date'),
            'overview': r.get('overview'),
            'language': r.get('original_language'),
            'country': None,
            'awards': None,
            # People
            'director': None,
            'writer': None,
            'actors': None,
            # Poster
            'poster': f"{TMDB_IMAGE_BASE}{r['poster_path']}" if r.get('poster_path') else None,
            'backdrop': f"https://image.tmdb.org/t/p/w780{r['backdrop_path']}" if r.get('backdrop_path') else None,
            # Series-specific
            'total_seasons': r.get('number_of_seasons'),
            'total_episodes': r.get('number_of_episodes'),
            # Metadata
            'source': 'tmdb',
            'media_type': media_type,
        }
    except Exception:
        return None


def find_tmdb_by_imdb_id(imdb_id, media_type='movie', api_key=None):
    """Find TMDb entry by IMDb ID using /find endpoint.
    Returns TMDb ID if found, None otherwise."""
    if not api_key or not imdb_id:
        return None
    if not imdb_id.startswith('tt'):
        imdb_id = 'tt' + imdb_id  # Ensure tt prefix
    try:
        url = f'{TMDB_BASE}/find/{imdb_id}?external_source=imdb_id'
        data, _ = _tmdb_request(url, api_key)
        if data is None:
            return None
        # Results are in 'movie_results' or 'tv_results'
        results_key = 'movie_results' if media_type == 'movie' else 'tv_results'
        results = data.get(results_key, [])
        if results:
            return str(results[0].get('id'))
    except Exception:
        pass
    return None


def get_tmdb_details(tmdb_id, media_type='movie', api_key=None):
    """Get full TMDb details (including genres, runtime, credits) by TMDb ID."""
    if not api_key or not tmdb_id:
        return None
    try:
        tmdb_type = 'movie' if media_type == 'movie' else 'tv'
        url = f'{TMDB_BASE}/{tmdb_type}/{tmdb_id}'
        data, _ = _tmdb_request(url, api_key)
        if data is None:
            return None
        # Extract genres
        genres = [g['name'] for g in data.get('genres', [])]
        # Runtime (movies) or episode_run_time (series)
        runtime = None
        if media_type == 'movie':
            runtime = data.get('runtime')
        else:
            ep_runtime = data.get('episode_run_time', [])
            runtime = ep_runtime[0] if ep_runtime else None
        # Additional fields
        result = {
            'genres': genres,
            'runtime': f"{runtime} min" if runtime else None,
            'total_seasons': data.get('number_of_seasons'),
            'total_episodes': data.get('number_of_episodes'),
            'status': data.get('status'),
            'tagline': data.get('tagline'),
            'homepage': data.get('homepage'),
            'production_companies': [c['name'] for c in data.get('production_companies', [])],
            'production_countries': [c['name'] for c in data.get('production_countries', [])],
            'spoken_languages': [l['english_name'] for l in data.get('spoken_languages', [])],
        }
        # Get credits for director/actors
        credits_url = f'{TMDB_BASE}/{tmdb_type}/{tmdb_id}/credits'
        credits_data, _ = _tmdb_request(credits_url, api_key)
        if credits_data is None:
            return result
        credits = credits_data
        # Directors (crew with job == Director)
        directors = [c['name'] for c in credits.get('crew', []) if c.get('job') == 'Director']
        result['director'] = ', '.join(directors) if directors else None
        # Top actors
        actors = [c['name'] for c in credits.get('cast', [])[:10]]
        result['actors'] = ', '.join(actors) if actors else None
        return result
    except Exception:
        return None


def get_metadata(title, year=None, media_type='movie', omdb_key=None, tmdb_key=None):
    """Get metadata for a title, using cache first, then TMDb (primary), OMDB (enrichment).
    TMDb is tried first (generous limits, better international coverage).
    OMDB is used only for enrichment (IMDb ratings, Metascore, detailed credits) when we have a TMDb ID.
    Negative caching prevents re-querying failed lookups for NEGATIVE_CACHE_TTL_DAYS."""
    cache = _load_metadata_cache()
    key = _make_key(title, year, media_type)

    if key in cache:
        return cache[key]

    # Parse title/year for clean search
    clean_title, parsed_year = _parse_title_year(title)
    year = year or parsed_year

    # Check negative cache first
    if _is_negative_cached(clean_title, year, media_type):
        return None

    result = None
    tmdb_id = None

    # --- Phase 1: TMDb search (primary, generous limits) ---
    if tmdb_key:
        result = search_tmdb(clean_title, year, media_type, tmdb_key)
        if result:
            tmdb_id = result.get('tmdb_id')
            # Cache poster/backdrop
            if result.get('poster'):
                _cache_poster_image(result['poster'], key, tmdb_id=tmdb_id)
            if result.get('backdrop'):
                _cache_poster_image(result['backdrop'], key + '_backdrop', tmdb_id=tmdb_id)

    # --- Phase 2: OMDB enrichment (only if we got a TMDb result) ---
    # OMDB provides: IMDb ratings, Metascore, detailed credits, awards, DVD release dates
    if result and omdb_key:
        # Use TMDb ID to find IMDb ID via TMDb's /find endpoint, then query OMDB
        imdb_id = find_imdb_by_tmdb_id(tmdb_id, media_type, tmdb_key)
        if imdb_id:
            omdb_result = search_omdb_by_id(imdb_id, media_type, omdb_key)
            if omdb_result:
                # Merge OMDB enrichment fields
                for field in ('imdb_rating', 'imdb_votes', 'metascore', 'ratings',
                              'director', 'writer', 'actors', 'awards',
                              'dvd_released', 'box_office', 'production', 'website'):
                    if omdb_result.get(field):
                        result[field] = omdb_result[field]
                result['imdb_id'] = imdb_id

    # --- Phase 3: TMDb details enrichment (genres, runtime, seasons, etc.) ---
    if result and tmdb_id and tmdb_key:
        details = get_tmdb_details(tmdb_id, media_type, tmdb_key)
        if details:
            if details.get('genres'):
                result['genre'] = ', '.join(details['genres'])
            if details.get('runtime'):
                result['runtime'] = details['runtime']
            if details.get('total_seasons'):
                result['total_seasons'] = details['total_seasons']
            if details.get('total_episodes'):
                result['total_episodes'] = details['total_episodes']
            if details.get('director'):
                result['director'] = details['director']
            if details.get('actors'):
                result['actors'] = details['actors']
            if details.get('status'):
                result['status'] = details['status']
            if details.get('tagline'):
                result['tagline'] = details['tagline']
            if details.get('homepage'):
                result['homepage'] = details['homepage']
            if details.get('production_companies'):
                result['production_companies'] = details['production_companies']
            if details.get('production_countries'):
                result['production_countries'] = details['production_countries']
            if details.get('spoken_languages'):
                result['spoken_languages'] = details['spoken_languages']

    if result:
        result['cached_at'] = time.time()
        cache[key] = result
        # Also cache by IDs for fast lookup
        if result.get('imdb_id'):
            cache[f'imdb:{result["imdb_id"]}'] = result
        if result.get('tmdb_id'):
            cache[f'tmdb:{result["tmdb_id"]}'] = result
        _save_metadata_cache(cache)
        return result

    # No result from either API - record negative cache
    _mark_negative_cache(clean_title, year, media_type)
    return None


def search_omdb_by_id(imdb_id, media_type='movie', api_key=None):
    """Query OMDB by IMDb ID (exact match, no search ambiguity)."""
    if not api_key or not imdb_id:
        return None
    if not imdb_id.startswith('tt'):
        imdb_id = 'tt' + imdb_id
    try:
        url = f'{OMDB_BASE}?apikey={api_key}&i={imdb_id}&plot=full'
        req = urllib.request.Request(url, headers={'User-Agent': 'flux-tray/1.0'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
        if data.get('Response') != 'True':
            return None
        return {
            'imdb_id': data.get('imdbID'),
            'imdb_rating': float(data.get('imdbRating')) if data.get('imdbRating') != 'N/A' else None,
            'imdb_votes': data.get('imdbVotes') if data.get('imdbVotes') != 'N/A' else None,
            'metascore': int(data.get('Metascore')) if data.get('Metascore') != 'N/A' else None,
            'ratings': data.get('Ratings', []),
            'director': data.get('Director') if data.get('Director') != 'N/A' else None,
            'writer': data.get('Writer') if data.get('Writer') != 'N/A' else None,
            'actors': data.get('Actors') if data.get('Actors') != 'N/A' else None,
            'awards': data.get('Awards') if data.get('Awards') != 'N/A' else None,
            'dvd_released': data.get('DVD') if data.get('DVD') != 'N/A' else None,
            'box_office': data.get('BoxOffice') if data.get('BoxOffice') != 'N/A' else None,
            'production': data.get('Production') if data.get('Production') != 'N/A' else None,
            'website': data.get('Website') if data.get('Website') != 'N/A' else None,
        }
    except Exception:
        return None


def find_imdb_by_tmdb_id(tmdb_id, media_type='movie', api_key=None):
    """Find IMDb ID from TMDb ID using /find endpoint."""
    if not api_key or not tmdb_id:
        return None
    try:
        url = f'{TMDB_BASE}/find/{tmdb_id}?external_source=imdb_id'
        data, _ = _tmdb_request(url, api_key)
        if data is None:
            return None
        results = data.get('movie_results' if media_type == 'movie' else 'tv_results', [])
        if results:
            return results[0].get('imdb_id')
    except Exception:
        pass
    return None


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


def get_cached_metadata(title, media_type='movie', url=None):
    """Get raw cached metadata dict (including poster URL) for a title.
    Non-blocking - only returns cached data."""
    clean_title, year = _parse_title_year(title)
    if year is None and url:
        year = _extract_year_from_url(url)
    cache = _load_metadata_cache()
    key = _make_key(clean_title, year, media_type)
    if key in cache:
        return cache[key]
    return None


def load_omdb_api_key():
    """Load OMDB API key from config.conf [media] section: omdb_key=xxx"""
    from .config import _read_config_sections
    for line in _read_config_sections()['media']:
        key, sep, val = line.partition('=')
        if sep and key.strip().lower() == 'omdb_key':
            return val.split('#', 1)[0].strip()
    return None


def load_tmdb_api_key():
    """Load TMDb API key from config.conf [media] section: tmdb_key=xxx"""
    from .config import _read_config_sections
    for line in _read_config_sections()['media']:
        key, sep, val = line.partition('=')
        if sep and key.strip().lower() == 'tmdb_key':
            return val.split('#', 1)[0].strip()
    return None


def get_media_metadata(title, media_type='movie', omdb_key=None, tmdb_key=None, url=None, imdb_id=None, tmdb_id=None):
    """Main entry point: get metadata for a media title.
    Tries to extract year from title (or URL), then looks up in cache only (non-blocking).
    Returns formatted tooltip markup string or None."""
    # Try cache by IDs first (most accurate)
    cache = _load_metadata_cache()
    if imdb_id:
        imdb_key = f'imdb:{imdb_id}'
        if imdb_key in cache:
            return format_metadata_for_tooltip(cache[imdb_key])
    if tmdb_id:
        tmdb_key_cache = f'tmdb:{tmdb_id}'
        if tmdb_key_cache in cache:
            return format_metadata_for_tooltip(cache[tmdb_key_cache])

    clean_title, year = _parse_title_year(title)
    if year is None and url:
        year = _extract_year_from_url(url)
    if omdb_key is None:
        omdb_key = load_omdb_api_key()
    if tmdb_key is None:
        tmdb_key = load_tmdb_api_key()
    # Only use cached data for UI tooltips to avoid blocking
    key = _make_key(clean_title, year, media_type)
    if key in cache:
        return format_metadata_for_tooltip(cache[key])
    return None


def refresh_metadata_cache(titles, media_types=None, omdb_key=None, tmdb_key=None):
    """Background refresh of metadata cache for a list of titles.
    `titles` is a list of title strings. `media_types` can be a list of same length
    or a single type ('movie' or 'series'). Runs in a thread.
    Limits to MAX_API_CALLS_PER_CYCLE total API calls (counts both successes and failures).
    Prioritizes items with years parsed from title. Uses negative caching to skip
    recently failed lookups. Syncs found TMDb/IMDb IDs to the unified media cache."""
    if omdb_key is None:
        omdb_key = load_omdb_api_key()
    if tmdb_key is None:
        tmdb_key = load_tmdb_api_key()
    if not omdb_key and not tmdb_key:
        return
    if media_types is None:
        media_types = ['movie'] * len(titles)
    elif isinstance(media_types, str):
        media_types = [media_types] * len(titles)

    # Prepare items with priority info
    items = []
    for title, mtype in zip(titles, media_types):
        clean_title, year = _parse_title_year(title)
        key = _make_key(clean_title, year, mtype)
        # Priority: items with year parsed from title get higher priority (1), others (0)
        # Negative cache check will be done inside get_metadata
        priority = 1 if year else 0
        items.append((priority, title, clean_title, year, mtype, key))

    # Sort by priority (descending) so items with years are tried first
    items.sort(key=lambda x: x[0], reverse=True)

    api_calls = 0
    cache = _load_metadata_cache()

    for _priority, _orig_title, clean_title, year, mtype, key in items:
        if api_calls >= MAX_API_CALLS_PER_CYCLE:
            break
        # Skip if already in positive cache
        if key in cache:
            continue
        # Skip if in negative cache (checked inside get_metadata, but we can pre-check)
        if _is_negative_cached(clean_title, year, mtype):
            continue

        result = get_metadata(clean_title, year, mtype, omdb_key, tmdb_key)
        api_calls += 1  # Count every API attempt (success or failure)
        if result:
            cache = _load_metadata_cache()  # Reload cache after get_metadata saves

    # After fetching new metadata, sync IDs to unified media cache
    # Check if any new positive entries were added
    new_cache = _load_metadata_cache()
    if len(new_cache) > len(cache):
        try:
            from .media_cache import load_media_cache, save_media_cache, sync_metadata_ids
            from .state import load_state, save_state
            media_cache = load_media_cache()
            state = load_state()
            seen_set = set(state.get('media_discovery_seen', []))
            metadata_cache = _load_metadata_cache()
            last_sync = state.get('media_cache_last_sync', 0.0)
            media_cache, seen_set, new_last_sync = sync_metadata_ids(
                media_cache, seen_set, metadata_cache, last_sync
            )
            save_media_cache(media_cache)
            state['media_discovery_seen'] = list(seen_set)
            state['media_cache_last_sync'] = new_last_sync
            save_state(state)
        except Exception:
            pass  # Best effort sync


def get_metadata_by_ids(imdb_id=None, tmdb_id=None, media_type='movie', omdb_key=None, tmdb_key=None):
    """Get metadata using known IMDb/TMDb IDs (bypasses search).
    Returns full metadata dict or None."""
    cache = _load_metadata_cache()

    # Try cache by IMDb ID first
    if imdb_id:
        for key, val in cache.items():
            if val.get('imdb_id') == imdb_id:
                return val

    # Try cache by TMDb ID
    if tmdb_id:
        for key, val in cache.items():
            if val.get('tmdb_id') == str(tmdb_id):
                return val

    # Not in cache, fetch using IDs
    if omdb_key is None:
        omdb_key = load_omdb_api_key()
    if tmdb_key is None:
        tmdb_key = load_tmdb_api_key()
    if not omdb_key and not tmdb_key:
        return None

    result = None

    # Try OMDB by IMDb ID
    if omdb_key and imdb_id:
        try:
            if not imdb_id.startswith('tt'):
                imdb_id = 'tt' + imdb_id
            url = f'{OMDB_BASE}?apikey={omdb_key}&i={imdb_id}&plot=full'
            req = urllib.request.Request(url, headers={'User-Agent': 'flux-tray/1.0'})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
            if data.get('Response') == 'True':
                result = {
                    'imdb_id': data.get('imdbID'),
                    'tmdb_id': None,
                    'title': data.get('Title'),
                    'year': data.get('Year'),
                    'type': data.get('Type'),
                    'imdb_rating': float(data.get('imdbRating')) if data.get('imdbRating') != 'N/A' else None,
                    'imdb_votes': data.get('imdbVotes') if data.get('imdbVotes') != 'N/A' else None,
                    'metascore': int(data.get('Metascore')) if data.get('Metascore') != 'N/A' else None,
                    'ratings': data.get('Ratings', []),
                    'genre': data.get('Genre') if data.get('Genre') != 'N/A' else None,
                    'runtime': data.get('Runtime') if data.get('Runtime') != 'N/A' else None,
                    'released': data.get('Released') if data.get('Released') != 'N/A' else None,
                    'overview': data.get('Plot') if data.get('Plot') != 'N/A' else None,
                    'language': data.get('Language') if data.get('Language') != 'N/A' else None,
                    'country': data.get('Country') if data.get('Country') != 'N/A' else None,
                    'awards': data.get('Awards') if data.get('Awards') != 'N/A' else None,
                    'director': data.get('Director') if data.get('Director') != 'N/A' else None,
                    'writer': data.get('Writer') if data.get('Writer') != 'N/A' else None,
                    'actors': data.get('Actors') if data.get('Actors') != 'N/A' else None,
                    'poster': data.get('Poster') if data.get('Poster') != 'N/A' else None,
                    'total_seasons': int(data.get('totalSeasons')) if data.get('totalSeasons') and data.get('totalSeasons') != 'N/A' else None,
                    'source': 'omdb',
                    'media_type': media_type,
                }
        except Exception:
            pass

    # Enrich with TMDb if we have TMDb ID or can find it via IMDb ID
    if tmdb_key:
        tmdb_id_to_use = tmdb_id
        if not tmdb_id_to_use and result and result.get('imdb_id'):
            tmdb_id_to_use = find_tmdb_by_imdb_id(result['imdb_id'], media_type, tmdb_key)

        if tmdb_id_to_use:
            details = get_tmdb_details(tmdb_id_to_use, media_type, tmdb_key)
            if details:
                if result is None:
                    result = {'tmdb_id': str(tmdb_id_to_use), 'media_type': media_type}
                else:
                    result['tmdb_id'] = str(tmdb_id_to_use)

                if details.get('genres'):
                    result['genre'] = ', '.join(details['genres'])
                if details.get('runtime'):
                    result['runtime'] = details['runtime']
                if details.get('total_seasons'):
                    result['total_seasons'] = details['total_seasons']
                if details.get('total_episodes'):
                    result['total_episodes'] = details['total_episodes']
                if details.get('director'):
                    result['director'] = details['director']
                if details.get('actors'):
                    result['actors'] = details['actors']
                if details.get('status'):
                    result['status'] = details['status']
                if details.get('tagline'):
                    result['tagline'] = details['tagline']
                if details.get('homepage'):
                    result['homepage'] = details['homepage']
                if details.get('production_companies'):
                    result['production_companies'] = details['production_companies']
                if details.get('production_countries'):
                    result['production_countries'] = details['production_countries']
                if details.get('spoken_languages'):
                    result['spoken_languages'] = details['spoken_languages']

    if result:
        result['cached_at'] = time.time()
        # Cache poster if available
        imdb_id = result.get('imdb_id')
        tmdb_id = result.get('tmdb_id')
        if result.get('poster'):
            _cache_poster_image(result['poster'], key, imdb_id=imdb_id, tmdb_id=tmdb_id)
        if result.get('backdrop'):
            _cache_poster_image(result['backdrop'], key + '_backdrop', imdb_id=imdb_id, tmdb_id=tmdb_id)
        # Cache by title/year key for future lookups
        key = _make_key(result.get('title', ''), result.get('year', ''), media_type)
        cache[key] = result
        _save_metadata_cache(cache)
        # Also cache by IMDb ID
        if result.get('imdb_id'):
            imdb_key = f'imdb:{result["imdb_id"]}'
            cache[imdb_key] = result
        # Also cache by TMDb ID
        if result.get('tmdb_id'):
            tmdb_cache_key = f'tmdb:{result["tmdb_id"]}'
            cache[tmdb_cache_key] = result
        _save_metadata_cache(cache)

    return result


def get_cached_metadata(title, media_type='movie', url=None, imdb_id=None, tmdb_id=None):
    """Get raw cached metadata dict (including poster URL) for a title.
    Non-blocking - only returns cached data.
    Can also look up by IMDb ID or TMDb ID if provided."""
    cache = _load_metadata_cache()

    # Try direct ID lookups first (most accurate)
    if imdb_id:
        imdb_key = f'imdb:{imdb_id}'
        if imdb_key in cache:
            return cache[imdb_key]
    if tmdb_id:
        tmdb_key = f'tmdb:{tmdb_id}'
        if tmdb_key in cache:
            return cache[tmdb_key]

    # Fall back to title/year lookup
    clean_title, year = _parse_title_year(title)
    if year is None and url:
        year = _extract_year_from_url(url)
    key = _make_key(clean_title, year, media_type)
    if key in cache:
        return cache[key]
    return None