"""Debug logging, enabled by the FLUX_TRAY_DEBUG environment variable."""

import os
import sys


def _log(message):
    """Diagnostics to stderr, silent unless FLUX_TRAY_DEBUG is set (e.g.
    `FLUX_TRAY_DEBUG=1 flux-tray`)."""
    if os.environ.get('FLUX_TRAY_DEBUG'):
        print(f'flux-tray: {message}', file=sys.stderr, flush=True)
