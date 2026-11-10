"""IMDB Chart media plugin for flux-tray.

Scrapes https://www.imdb.com/chart/moviemeter/ and https://www.imdb.com/chart/tvmeter/
to extract title IDs for the Media section. Uses r.jina.ai proxy to bypass AWS WAF blocking.
"""

import json
import re
import urllib.error
import urllib.parse
import urllib.request

from flux_tray.media import USER_AGENT, HTTP_TIMEOUT_SECONDS

NAME = 'imdb-charts'
ORDER = 'newest'

_CHART_URLS = {
    'moviemeter': 'https://www.imdb.com/chart/moviemeter/',
    'tvmeter': 'https://www.imdb.com/chart/tvmeter/',
}

# Pattern to extract title IDs from markdown links: [Title](https://www.imdb.com/title/tt12345/)
_JINA_TITLE_RE = re.compile(
    r'\[([^\]]+)\]\(https://www\.imdb\.com/title/(tt\d+)/'
)

_TITLE_ID_RE = re.compile(r'/title/(tt\d+)')

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
    re.DOTALL
)

_CHART_TITLES = {
    'moviemeter': 'IMDB Most Popular Movies',
    'tvmeter': 'IMDB Most Popular TV Shows',
}


def matches(source):
    """Return True for IMDB chart URLs or imdb-charts: prefix."""
    if source.startswith('imdb-charts:'):
        chart_type = source.split(':', 1)[1]
        return chart_type in _CHART_URLS
    parsed = urllib.parse.urlparse(source)
    if parsed.netloc not in ('www.imdb.com', 'imdb.com'):
        return False
    path = parsed.path.rstrip('/')
    chart_type = path.split('/')[-1] if path else ''
    return chart_type in _CHART_URLS


def list_episodes(source):
    """Return (title, episodes) for an IMDB chart page.

    Episodes are dicts with:
      - id: IMDB title ID (e.g., 'tt0111161')
      - title: the title name
      - date: empty (charts don't have dates)
      - url: the IMDB title page URL
      - ref: the chart type ('moviemeter' or 'tvmeter')
    """
    # The app takes the plugin's name off a line like imdb-charts:moviemeter before it calls this, so the
    # chart arrives as 'moviemeter'; a full 'imdb-charts:moviemeter' is accepted too
    if source in _CHART_URLS:
        chart_type = source
        url = _CHART_URLS[source]
    elif source.startswith('imdb-charts:'):
        chart_type = source.split(':', 1)[1]
        url = _CHART_URLS.get(chart_type)
        if not url:
            raise ValueError(f'unknown IMDB chart type: {chart_type}')
    else:
        parsed = urllib.parse.urlparse(source)
        path = parsed.path.rstrip('/')
        chart_type = path.split('/')[-1] if path else ''
        url = source

    if chart_type not in _CHART_URLS:
        raise ValueError(f'not an IMDB chart URL: {source}')

    html = _fetch_page(url)
    episodes = _parse_chart_html(html, chart_type)

    title = _CHART_TITLES.get(chart_type, f'IMDB {chart_type}')
    return title, episodes


def _fetch_page(url):
    """Fetch a page via r.jina.ai proxy to bypass AWS WAF blocking.

    The proxy returns markdown content with title links that we can parse.
    Falls back to direct fetch if proxy fails.
    """
    # Use jina.ai as a content extraction proxy
    proxy_url = f'https://r.jina.ai/http://{url.removeprefix("https://")}'
    try:
        request = urllib.request.Request(proxy_url, headers={'User-Agent': USER_AGENT})
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            content = response.read().decode('utf-8', errors='replace')
            # Check if we got actual markdown content with titles
            if _JINA_TITLE_RE.search(content):
                return content
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
        pass

    # Fallback: direct fetch (may be blocked by WAF)
    request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
        return response.read().decode('utf-8', errors='replace')


def _parse_chart_html(html, chart_type):
    """Extract title IDs from IMDB chart content.

    Tries jina.ai markdown format first, then __NEXT_DATA__ JSON (modern IMDB),
    then falls back to regex extraction from HTML.
    """
    # Try jina.ai markdown format first (our primary method via proxy)
    episodes = _extract_from_jina_markdown(html)
    if episodes:
        return episodes

    # Try __NEXT_DATA__ JSON (modern IMDB direct fetch)
    match = _NEXT_DATA_RE.search(html)
    if match:
        try:
            data = json.loads(match.group(1))
            return _extract_from_next_data(data, chart_type)
        except (json.JSONDecodeError, KeyError, TypeError):
            pass  # Fall back to regex

    # Fallback: regex extraction from HTML
    return _extract_from_html(html)


def _extract_from_jina_markdown(markdown):
    """Extract episodes from jina.ai markdown output."""
    episodes = []
    seen = set()

    for match in _JINA_TITLE_RE.finditer(markdown):
        title_name = match.group(1).strip()
        title_id = match.group(2)

        if title_id in seen:
            continue
        seen.add(title_id)

        episodes.append({
            'id': title_id,
            'title': title_name,
            'date': '',
            'url': f'https://www.imdb.com/title/{title_id}/',
            'ref': 'chart',
        })

    return episodes


def _extract_from_next_data(data, chart_type):
    """Extract episodes from __NEXT_DATA__ JSON structure."""
    episodes = []

    # Navigate to the chart data: props.pageProps.chartData.chart.edges
    try:
        chart_data = (
            data.get('props', {})
            .get('pageProps', {})
            .get('chartData', {})
            .get('chart', {})
            .get('edges', [])
        )
    except (AttributeError, TypeError):
        chart_data = []

    for edge in chart_data:
        node = edge.get('node') if isinstance(edge, dict) else None
        if not isinstance(node, dict):
            continue

        title_id = node.get('id') or node.get('titleId')
        if not title_id or not isinstance(title_id, str):
            continue
        if not title_id.startswith('tt'):
            title_id = 'tt' + title_id

        title_text = node.get('titleText', {})
        if isinstance(title_text, dict):
            title_name = title_text.get('text', '')
        else:
            title_name = str(title_text) if title_text else ''

        if title_id and title_name:
            episodes.append({
                'id': title_id,
                'title': title_name,
                'date': '',
                'url': f'https://www.imdb.com/title/{title_id}/',
                'ref': chart_type,
            })

    return episodes


def _extract_from_html(html):
    """Fallback: extract title IDs from HTML using regex."""
    episodes = []
    seen = set()

    # Look for title links in the chart table
    for match in _TITLE_ID_RE.finditer(html):
        title_id = match.group(1)
        if title_id in seen:
            continue
        seen.add(title_id)

        # Try to find the title text near this link
        start = max(0, match.start() - 500)
        end = min(len(html), match.end() + 500)
        context = html[start:end]

        title_name = _extract_title_from_context(context, title_id)
        if not title_name:
            title_name = title_id

        episodes.append({
            'id': title_id,
            'title': title_name,
            'date': '',
            'url': f'https://www.imdb.com/title/{title_id}/',
            'ref': 'chart',
        })

    return episodes


def _extract_title_from_context(context, title_id):
    """Try to extract title name from HTML context around a title link."""
    # Look for alt="Title Name" or aria-label="Title Name"
    alt_match = re.search(r'alt=["\']([^"\']+)["\']', context)
    if alt_match:
        return alt_match.group(1)

    aria_match = re.search(r'aria-label=["\']([^"\']+)["\']', context)
    if aria_match:
        return aria_match.group(1)

    # Look for the title in a nearby <img> tag for the poster
    img_match = re.search(r'<img[^>]+alt=["\']([^"\']+)["\']', context)
    if img_match:
        return img_match.group(1)

    # Look for link text: <a href="/title/tt12345/">Title Name</a>
    link_match = re.search(rf'<a[^>]+href=["\']/title/{re.escape(title_id)}/["\'][^>]*>([^<]+)</a>', context)
    if link_match:
        return link_match.group(1).strip()

    return None