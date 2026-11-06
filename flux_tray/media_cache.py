"""
Unified media cache keyed by TMDB ID (fallback: IMDb ID).
Stores items from all discovery plugins with their source URLs.
"""

import json
import re
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

CACHE_FILE = Path.home() / '.config' / 'flux-tray' / 'media_cache.json'
MAX_CACHE_AGE = timedelta(days=30)
MAX_CACHE_ENTRIES = 5000


def _cache_key(item: dict) -> str:
    """Generate cache key from TMDB ID, fallback to IMDb ID."""
    tmdb_id = item.get('tmdb_id')
    if tmdb_id:
        return f'tmdb:{tmdb_id}'
    imdb_id = item.get('imdb_id')
    if imdb_id:
        return f'imdb:{imdb_id}'
    # Fallback: use title (without year) + year + type
    title = item.get('title', '').lower().strip()
    # Remove year from title if present (e.g., "Movie (2026)" -> "Movie")
    title = re.sub(r'\s*\(\d{4}\)\s*$', '', title)
    year = item.get('year', '') or item.get('date', '')[:4]
    mtype = item.get('type', 'movie')
    return f'fallback:{mtype}:{title}:{year}'


def load_media_cache() -> dict:
    """Load the unified media cache."""
    if CACHE_FILE.exists():
        try:
            data = json.loads(CACHE_FILE.read_text())
            # Clean old entries
            now = time.time()
            cleaned = {}
            for key, entry in data.items():
                last_seen = entry.get('last_seen')
                if last_seen:
                    try:
                        seen_dt = datetime.fromisoformat(last_seen.replace('Z', '+00:00'))
                        if now - seen_dt.timestamp() < MAX_CACHE_AGE.total_seconds():
                            cleaned[key] = entry
                    except Exception:
                        pass
            return cleaned
        except Exception:
            pass
    return {}


def save_media_cache(cache: dict):
    """Save the unified media cache with size limit."""
    if len(cache) > MAX_CACHE_ENTRIES:
        items = sorted(cache.items(), key=lambda x: x[1].get('last_seen', ''), reverse=True)
        cache = dict(items[:MAX_CACHE_ENTRIES])
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2))


def get_or_create_entry(cache: dict, item: dict) -> dict:
    """Get existing cache entry or create new one for this item."""
    key = _cache_key(item)
    now = datetime.now(timezone.utc).isoformat()

    if key in cache:
        entry = cache[key]
        # Update last_seen
        entry['last_seen'] = now
        # Merge URLs from this plugin
        plugin = item.get('_plugin', 'unknown')
        url = item.get('url') or item.get('id')
        if url:
            urls = entry.setdefault('urls', {})
            urls[plugin] = url
        # Update other fields if missing
        for field in ('image', 'genre', 'date'):
            if field in item and item[field] and not entry.get(field):
                entry[field] = item[field]
        return entry

    # Create new entry
    entry = {
        'key': key,
        'title': item.get('title', ''),
        'type': item.get('type', 'movie'),
        'year': item.get('year', '') or (item.get('date', '')[:4] if item.get('date') else ''),
        'tmdb_id': item.get('tmdb_id'),
        'imdb_id': item.get('imdb_id'),
        'urls': {},
        'image': item.get('image'),
        'genre': item.get('genre', []),
        'date': item.get('date', ''),
        'first_seen': now,
        'last_seen': now,
    }
    plugin = item.get('_plugin', 'unknown')
    url = item.get('url') or item.get('id')
    if url:
        entry['urls'][plugin] = url

    cache[key] = entry
    return entry


def get_new_items(cache: dict, items: list[dict], seen_set: set[str]) -> list[dict]:
    """Filter items to only return those not in seen_set, and update cache."""
    new_items = []
    for item in items:
        key = _cache_key(item)
        if key in seen_set:
            # Already dismissed - still update cache with any new URLs
            get_or_create_entry(cache, item)
            continue
        new_items.append(item)
        get_or_create_entry(cache, item)
    return new_items


def mark_seen(seen_set: set[str], item: dict):
    """Mark an item as seen/dismissed."""
    key = _cache_key(item)
    seen_set.add(key)


def is_seen(seen_set: set[str], item: dict) -> bool:
    """Check if item has been dismissed."""
    key = _cache_key(item)
    return key in seen_set


def get_all_cached_items(cache: dict) -> list[dict]:
    """Get all cached items for display (sorted by date, newest first)."""
    items = []
    for entry in cache.values():
        # Convert cache entry back to item format for display
        item = {
            'id': list(entry['urls'].values())[0] if entry['urls'] else entry['key'],
            'title': entry['title'],
            'type': entry['type'],
            'year': entry['year'],
            'date': entry['date'],
            'image': entry['image'],
            'genre': entry['genre'],
            'tmdb_id': entry.get('tmdb_id'),
            'imdb_id': entry.get('imdb_id'),
            'urls': entry['urls'],  # All source URLs
            '_cache_key': entry['key'],
        }
        items.append(item)
    items.sort(key=lambda x: x.get('date', '') or x.get('first_seen', ''), reverse=True)
    return items


def prune_seen_set(seen_set: set[str], cache: dict) -> set[str]:
    """Remove seen entries that no longer exist in cache."""
    return seen_set & set(cache.keys())


def sync_metadata_ids(
    cache: dict,
    seen_set: set[str],
    metadata_cache: dict,
    last_sync_time: float = 0.0,
) -> tuple[dict, set[str], float]:
    """Incremental sync: only process metadata entries newer than last_sync_time.

    For fallback-keyed cache entries that now have TMDb/IMDb IDs in metadata cache,
    migrate them to proper ID-based keys. Returns (updated_cache, updated_seen_set, new_last_sync_time).

    Uses direct key lookup (O(1)) instead of building reverse index (O(M)).
    """
    new_cache = {}
    key_mapping = {}  # old_key -> new_key
    max_meta_time = last_sync_time

    for meta_key, meta_val in metadata_cache.items():
        if not isinstance(meta_val, dict):
            continue
        cached_at = meta_val.get('cached_at', 0)
        if cached_at <= last_sync_time:
            continue  # Already processed
        max_meta_time = max(max_meta_time, cached_at)

        tmdb_id = meta_val.get('tmdb_id')
        imdb_id = meta_val.get('imdb_id')
        if not (tmdb_id or imdb_id):
            continue

        mtype = meta_val.get('type', 'movie')
        title = meta_val.get('title', '').lower().strip()
        year = str(meta_val.get('year', ''))
        fallback_key = f'fallback:{mtype}:{title}:{year}'

        if fallback_key in cache:
            entry = cache[fallback_key]
            new_key = f'tmdb:{tmdb_id}' if tmdb_id else f'imdb:{imdb_id}'

            new_entry = entry.copy()
            new_entry['key'] = new_key
            new_entry['tmdb_id'] = tmdb_id
            new_entry['imdb_id'] = imdb_id
            new_cache[new_key] = new_entry
            key_mapping[fallback_key] = new_key

    # Rebuild full cache: keep non-migrated entries
    for key, entry in cache.items():
        if key not in key_mapping and key not in new_cache:
            new_cache[key] = entry

    # Update seen_set: migrate old keys to new keys
    new_seen = set()
    for key in seen_set:
        new_seen.add(key_mapping.get(key, key))

    return new_cache, new_seen, max_meta_time