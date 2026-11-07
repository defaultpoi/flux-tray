"""The discovery cache: the films and series that plugins' fetch_discovery found, kept
in media_cache.json beside config.conf for MAX_CACHE_AGE after they were last seen.

An item is keyed by its TMDb id, else its IMDb id, else (while neither is known) by
its title without punctuation, accents or "(year)", its year and its type, so the
same film from two plugins is one entry with a URL for each. When metadata later
gives an id to an entry that has none, sync_metadata_ids re-keys it, merging with an
entry that already has that id. What the person dismissed is a set of these keys,
kept in state.json by the app.
"""

import json
import re
import threading
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .constants import CONFIG_DIR
from .fileutil import write_atomic

CACHE_FILE = Path(CONFIG_DIR) / 'media_cache.json'
MAX_CACHE_AGE = timedelta(days=30)
MAX_CACHE_ENTRIES = 5000

_lock = threading.RLock()
_YEAR_SUFFIX = re.compile(r'\s*\(((?:19|20)\d{2})\)\s*$')


def _normal_title(title):
    """A title as a key part: no "(year)" at the end, no accents, case or punctuation
    ("Spider-Man: No Way Home" and "Spider Man No Way Home" are one)."""
    title = _YEAR_SUFFIX.sub('', title or '')
    title = unicodedata.normalize('NFKD', title)
    title = ''.join(c for c in title if not unicodedata.combining(c)).casefold()
    return ' '.join(re.sub(r'[\W_]+', ' ', title).split())


def _item_year(item):
    """The release year an item names ('' if it names none): its `year` if that is a
    year, else the "(year)" its title ends in. Never the date it was found on, which is
    not when the film came out."""
    year = str(item.get('year') or '')
    if re.fullmatch(r'(?:19|20)\d{2}', year):
        return year
    match = _YEAR_SUFFIX.search(item.get('title') or '')
    return match.group(1) if match else ''


def title_with_year(item):
    """The item's title with its year, "Title (2024)", as the metadata lookup wants it
    (the title alone if no year is known)."""
    year = _item_year(item)
    title = _YEAR_SUFFIX.sub('', item.get('title') or '')
    return f'{title} ({year})' if year else title


def _fallback_key(mtype, title, year):
    return f'fallback:{mtype}:{_normal_title(title)}:{year}'


def _cache_key(item: dict) -> str:
    """The key of an item: its TMDb id, else its IMDb id, else the title/year/type key."""
    if item.get('tmdb_id'):
        return f'tmdb:{item["tmdb_id"]}'
    if item.get('imdb_id'):
        return f'imdb:{item["imdb_id"]}'
    return _fallback_key(item.get('type') or 'movie', item.get('title'), _item_year(item))


def load_media_cache() -> dict:
    """The cache without the entries not seen for MAX_CACHE_AGE ({} if there is none)."""
    with _lock:
        try:
            with open(CACHE_FILE, encoding='utf-8') as f:
                data = json.load(f)
        except (OSError, ValueError):
            return {}
    if not isinstance(data, dict):
        return {}
    oldest = datetime.now(timezone.utc) - MAX_CACHE_AGE
    cleaned = {}
    for key, entry in data.items():
        try:
            seen = datetime.fromisoformat(entry['last_seen'].replace('Z', '+00:00'))
            if seen > oldest and isinstance(entry.get('urls'), dict):
                cleaned[key] = entry
        except (KeyError, AttributeError, TypeError, ValueError):
            pass
    return cleaned


def save_media_cache(cache: dict):
    """Saves the cache (whole or not at all), the MAX_CACHE_ENTRIES last seen of it."""
    if len(cache) > MAX_CACHE_ENTRIES:
        newest = sorted(cache.items(), key=lambda kv: kv[1].get('last_seen', ''), reverse=True)
        cache = dict(newest[:MAX_CACHE_ENTRIES])
    with _lock:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        write_atomic(CACHE_FILE, lambda f: json.dump(cache, f, ensure_ascii=False, indent=2))


def update_media_cache(change):
    """Applies `change(cache)` to the current cache and saves it, with no other thread's
    change in between. Returns what `change` returns."""
    with _lock:
        cache = load_media_cache()
        result = change(cache)
        save_media_cache(cache)
        return result


def get_or_create_entry(cache: dict, item: dict) -> dict:
    """The cache entry of an item, made if there is none; it is marked seen now and
    gets this plugin's URL."""
    key = _cache_key(item)
    now = datetime.now(timezone.utc).isoformat()
    plugin = item.get('_plugin', 'unknown')
    url = item.get('url') or item.get('id')
    entry = cache.get(key)
    if entry is None:
        entry = cache[key] = {
            'key': key, 'title': item.get('title', ''), 'type': item.get('type', 'movie'),
            'year': _item_year(item), 'tmdb_id': item.get('tmdb_id'), 'imdb_id': item.get('imdb_id'),
            'urls': {}, 'image': item.get('image'), 'genre': item.get('genre', []),
            'date': item.get('date', ''), 'quality': item.get('quality'), 'first_seen': now,
        }
    entry['last_seen'] = now
    if url:
        entry['urls'][plugin] = url
    for field in ('image', 'genre', 'date'):
        if item.get(field) and not entry.get(field):
            entry[field] = item[field]
    if item.get('quality'):
        entry['quality'] = item['quality']  # a cam copy becomes an HD one: the newest word counts
    return entry


def get_new_items(cache: dict, items: list[dict], seen_set: set[str]) -> list[dict]:
    """The items whose key is not in `seen_set` (not dismissed); every item is put in
    the cache, a dismissed one too, so its newest URLs are kept."""
    new_items = []
    for item in items:
        if _cache_key(item) not in seen_set:
            new_items.append(item)
        get_or_create_entry(cache, item)
    return new_items


def mark_seen(seen_set: set[str], item: dict):
    """Marks an item dismissed."""
    seen_set.add(_cache_key(item))


def is_seen(seen_set: set[str], item: dict) -> bool:
    return _cache_key(item) in seen_set


def get_all_cached_items(cache: dict) -> list[dict]:
    """Every cached item in the shape the list shows, the newest first."""
    items = []
    for key, entry in cache.items():
        urls = entry.get('urls') or {}
        items.append({
            'id': next(iter(urls.values()), key),
            'title': entry.get('title', ''), 'type': entry.get('type', 'movie'),
            'year': entry.get('year', ''), 'date': entry.get('date', ''),
            'image': entry.get('image'), 'genre': entry.get('genre') or [], 'quality': entry.get('quality'),
            'tmdb_id': entry.get('tmdb_id'), 'imdb_id': entry.get('imdb_id'),
            'urls': urls, '_cache_key': key, 'first_seen': entry.get('first_seen', ''),
        })
    items.sort(key=lambda item: item['date'] or item['first_seen'], reverse=True)
    return items


def prune_seen_set(seen_set: set[str], cache: dict) -> set[str]:
    """The dismissed keys that are still in the cache (a dismissal is only kept as long
    as the item can come back)."""
    return seen_set & set(cache)


def sync_metadata_ids(cache: dict, seen_set: set[str], lookup) -> tuple[dict, set[str], int]:
    """Gives the entries that have no id the ids that metadata has for them.

    `lookup(entry)` returns the metadata dict for an entry or None. An entry keyed by
    title that has one with a TMDb or IMDb id is re-keyed by it, and merged (its URLs
    too) with the entry that already has that key; a dismissal of the old key becomes
    one of the new. Returns (cache, seen_set, how many entries were re-keyed); the
    arguments are changed in place."""
    moved = 0
    for old_key in [k for k in cache if k.startswith('fallback:')]:
        entry = cache[old_key]
        meta = lookup(entry)
        tmdb_id = (meta or {}).get('tmdb_id')
        imdb_id = (meta or {}).get('imdb_id')
        if not (tmdb_id or imdb_id):
            continue
        new_key = f'tmdb:{tmdb_id}' if tmdb_id else f'imdb:{imdb_id}'
        del cache[old_key]
        target = cache.get(new_key)
        if target is None:
            entry.update(key=new_key, tmdb_id=tmdb_id, imdb_id=imdb_id)
            cache[new_key] = entry
        else:
            for plugin, url in entry.get('urls', {}).items():
                target['urls'].setdefault(plugin, url)
            for field in ('image', 'genre', 'date', 'year', 'quality'):
                if entry.get(field) and not target.get(field):
                    target[field] = entry[field]
            target['first_seen'] = min(target.get('first_seen', ''), entry.get('first_seen', '')) or target.get('first_seen', '')
            target['last_seen'] = max(target.get('last_seen', ''), entry.get('last_seen', ''))
            target['tmdb_id'] = target.get('tmdb_id') or tmdb_id
            target['imdb_id'] = target.get('imdb_id') or imdb_id
        if old_key in seen_set:
            seen_set.discard(old_key)
            seen_set.add(new_key)
        moved += 1
    return cache, seen_set, moved
