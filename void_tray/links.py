"""Opening links from feeds in the browser, restricted to web addresses.

A feed controls its item links. A `file:` link would open a local file, and a
custom scheme (`ssh:`, `smb:`, ...) would hand the address to whatever program
registered it, so only http and https links are passed on."""

import urllib.parse
import webbrowser

from .log import _log


def is_web_url(url):
    """True for an http or https address that names a host and has no spaces or
    control characters."""
    if not isinstance(url, str) or not url or any(c.isspace() or ord(c) < 32 for c in url):
        return False
    try:
        parsed = urllib.parse.urlparse(url)
        parsed.port  # raises ValueError for a port that is not a number in range
    except ValueError:
        return False
    return parsed.scheme in ('http', 'https') and bool(parsed.hostname)


def open_link(url, new_tab=False):
    """Opens `url` in the browser when it is a web address. Returns whether it was opened."""
    if not is_web_url(url):
        _log(f'not opening a link that is not an http(s) address: {str(url)[:80]!r}')
        return False
    (webbrowser.open_new_tab if new_tab else webbrowser.open)(url)
    return True
