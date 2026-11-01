"""Flux Tray: news, live streams, weather, media and package updates in one tray
icon and popup, for XFCE on Void Linux. Python 3.14 only."""
import sys

if sys.version_info < (3, 14):
    raise SystemExit(f'Flux Tray needs Python 3.14 or newer; this is Python {sys.version.split()[0]}.')

import warnings

# Gtk.StatusIcon is deprecated upstream but is what the XEMBED tray needs here;
# silence the per-call warnings it would otherwise print on every icon update.
warnings.filterwarnings('ignore', message=r'Gtk\.StatusIcon')
warnings.filterwarnings('ignore', message=r'GLib\.unix_signal_add')  # older-GLib fallback path
