#!/usr/bin/env python3
"""
flux-tray media plugin for sitefilme.com
Media source: supports movies only (/online/{id}/) with direct m3u8 + VTT from stf*.vip CDN.
Provides find() to locate titles via site search.
"""

import re
import urllib.parse
import urllib.request

import requests
from bs4 import BeautifulSoup

NAME = 'sitefilme_com'
ORDER = 'newest'

BASE_URL = 'https://sitefilme.com'
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'

_session = requests.Session()
_session.headers.update({'User-Agent': USER_AGENT, 'Referer': BASE_URL})


def find(title, year=None, imdb_id=None, kind='movie'):
    """Return the sitefilme.com URL for a movie title, or None if not found.

    Uses the site's search function (GET ?s=title) and matches results by
    normalized title and optionally year. This plugin only supports movies.
    """
    if kind != 'movie':
        return None

    wanted_norm = _norm_title(title)
    if not wanted_norm:
        return None

    try:
        # Search the site
        url = BASE_URL + '/'
        params = {'s': title}
        resp = _session.get(url, params=params, timeout=15)
        resp.raise_for_status()
    except Exception:
        return None

    soup = BeautifulSoup(resp.text, 'html.parser')
    # Find all movie links in search results
    links = soup.find_all('a', href=True)
    movie_links = [a for a in links if '/online/' in a.get('href', '')]

    best_url = None
    for a in movie_links:
        link_text = a.get_text(strip=True)
        link_url = a['href']

        # Extract title from link text (format: "IMDb8.4Title – Romanian (Year)YearGenre")
        # We want to match the English title part
        match = re.search(r'IMDb[\d.]+([^–]+)(?:–|$)', link_text)
        if match:
            found_title = match.group(1).strip()
        else:
            # Fallback: use the whole text before year
            found_title = re.sub(r'\s*\d{4}\s*$', '', link_text).strip()

        found_norm = _norm_title(found_title)
        if found_norm == wanted_norm:
            # If year is specified, try to verify
            if year:
                year_match = re.search(r'\((\d{4})\)', link_text)
                if year_match and year_match.group(1) == str(year):
                    return link_url
                # If no year in link or doesn't match, still consider it if it's the only match
                if not year_match:
                    best_url = link_url
            else:
                return link_url

    return best_url


def _norm_title(text):
    """Normalize title for comparison: lowercase, no punctuation, no diacritics."""
    import unicodedata
    text = unicodedata.normalize('NFKD', text or '')
    text = ''.join(c for c in text if not unicodedata.combining(c)).lower()
    # Keep only alphanumeric and spaces, replace with single space
    text = re.sub(r'[^a-z0-9\s]+', ' ', text)
    return ' '.join(text.split())


# --- Media source handling -----------------------------------------------------


def _extract_cdn_base(soup: BeautifulSoup, html: str = None) -> str:
    """Extract CDN base URL from page (e.g., https://stf02.vip)."""
    # Look for m3u8 or vtt URLs in page - search in raw HTML first
    text = html if html is not None else soup.get_text()
    # Pattern: https://stf02.vip/138199/138199.m3u8 (in JSON-LD contentUrl)
    m = re.search(r'(https?://stf\d+\.vip)/\d+/\d+\.m3u8', text)
    if m:
        return m.group(1)
    # Pattern: https://stf02.vip/138199/138199.vtt
    m = re.search(r'(https?://stf\d+\.vip)/\d+/\d+\.vtt', text)
    if m:
        return m.group(1)
    # Default fallback
    return 'https://stf04.vip'


def matches(source: str) -> bool:
    """Match sitefilme.com movie URLs."""
    return 'sitefilme.com' in source and '/online/' in source


def _get_soup_and_html(url: str):
    resp = _session.get(url, timeout=30)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, 'html.parser'), resp.text


def _extract_video_id(url: str) -> str:
    """Extract video ID from URL like https://sitefilme.com/online/138203/"""
    parsed = urllib.parse.urlparse(url)
    path_parts = parsed.path.strip('/').split('/')
    for i, part in enumerate(path_parts):
        if part == 'online' and i + 1 < len(path_parts):
            return path_parts[i + 1]
    # Fallback: last numeric part
    for part in reversed(path_parts):
        if part.isdigit():
            return part
    raise ValueError(f'Could not extract video ID from URL: {url}')


def _get_title(soup: BeautifulSoup) -> str:
    el = soup.select_one("meta[property='og:title'], h1, title")
    if el:
        if el.name == 'meta':
            title = el.get('content', '').strip()
        else:
            title = el.get_text(strip=True)
        # Clean up title
        title = re.sub(r'\s*[-–]\s*(Film Online|SiteFilme).*$', '', title, flags=re.IGNORECASE)
        # Format: "English Title - Romanian Title (Year)" -> "English Title"
        # Also handle duplicated: "Title - Title (Year)" -> "Title"
        title = _clean_sitefilme_title(title)
        return title.strip()
    return 'Unknown Movie'


def _clean_sitefilme_title(title: str) -> str:
    """Extract English title from 'English - Romanian (Year)' or deduplicate.
    Only splits when second part looks Romanian (diacritics/words)."""
    if ' - ' not in title:
        # No dash: could be English-only or Romanian-only, keep as-is
        title = re.sub(r'\s*\(\d{4}\)\s*$', '', title)
        return title.strip()

    parts = [p.strip() for p in title.split(' - ')]

    # Deduplication: "Title - Title (Year)" -> "Title"
    if len(parts) >= 2 and parts[0].lower() == parts[1].lower():
        title = parts[0]
    # Split only if second part looks Romanian (diacritics or common words)
    elif len(parts) >= 2 and _looks_romanian(parts[1]):
        title = parts[0]  # English title
    else:
        # English title with dash (e.g., "Mission: Impossible - Dead Reckoning")
        title = re.sub(r'\s*\(\d{4}\)\s*$', '', title)

    return title.strip()


def _looks_romanian(text: str) -> bool:
    """Check if text contains Romanian diacritics or common Romanian words."""
    # Romanian diacritics
    if re.search(r'[ăâîșțĂÂÎȘȚ]', text):
        return True
    # Common Romanian words in titles
    romanian_words = {'cu', 'și', 'si', 'de', 'la', 'în', 'in', 'din', 'pentru', 'un', 'o', 'pe', 'sub', 'fără', 'fara', 'preț', 'pret'}
    words = set(re.findall(r'\b\w+\b', text.lower()))
    return bool(words & romanian_words)


def list_episodes(source: str):
    """Return (title, episodes) for a movie URL: one episode, whose stream is only
    looked up when it is downloaded."""
    soup, _html = _get_soup_and_html(source)
    title = _get_title(soup)
    return title, [{'id': source, 'title': title, 'ref': source}]


def resolve(episode: dict):
    """The stream and subtitles of the movie, looked up when it is downloaded. The
    subtitle address is built from the video id and may not exist: the app skips
    a subtitle that cannot be downloaded."""
    page = episode.get('ref') or episode['url']  # episodes stored by the earlier version have the page in 'url'
    video_id = _extract_video_id(page)
    _soup, html = _get_soup_and_html(page)
    cdn_base = _extract_cdn_base(_soup, html)
    headers = {'User-Agent': USER_AGENT, 'Referer': page}
    return {
        'video': {'url': f'{cdn_base}/{video_id}/{video_id}.m3u8', 'ext': '.ts', 'headers': headers},
        'subs': [{'url': f'{cdn_base}/{video_id}/{video_id}.vtt', 'lang': 'ro', 'ext': '.vtt', 'headers': headers}],
    }