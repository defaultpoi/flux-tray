"""Builds the real popup from fixed data and prints its widget tree as JSON.

Usage: render_popup.py full|quiet|media_menu|media_removed. `full` shows every
section; `quiet` has only a saved item, so the popup says there is nothing unread;
`media_menu` has a podcast with an episode left, a series and a film that are all
watched, and prints the right-click menu of each of their rows; `media_removed`
presses "Remove all 2 fully watched" in the series' menu and prints what is left
(the popup, config.conf, the sources in media.json).

Run by tests/test_golden_popup.py in a child process, under a display, with its
own HOME: the paths are fixed when flux_tray is imported. Nothing here touches
the network: timers are not scheduled and the checks that start threads are
replaced.

The tree records what a person sees and clicks: each widget's type, text
(markup as written), tooltip, visibility, margins, the style classes the app
added, and the plain attributes the app hangs on a row to know what a click
means. It leaves out what depends on the machine: pixel sizes (fonts), icon
names (theme) and GTK's own default classes.
"""
import json
import os
import pathlib
import sys
import tempfile
import time

NOW = 1_793_000_000  # a fixed 'now' (late October 2026) so elapsed times read the same every run
HOME = tempfile.mkdtemp(prefix='flux-tray-golden-')
os.environ['HOME'] = HOME
os.environ['XDG_DATA_HOME'] = HOME + '/.local/share'  # where the desktop Trash is: never the real one
os.environ.pop('FLUX_TRAY_DEBUG', None)
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

CONFIG = """\
[feeds]
https://news.example/rss|Example News|10
https://blog.example/atom|Example Blog|10

[highlight]
harbour

[twitch]
interval=15
quality=720p60,720p,best
examplechan|Example Channel

[youtube]
@examplebeta|Beta Show

[media]
path=~/videos
interval=60
ahead=0
https://media.example/feed.xml|Example Podcast|newest
https://media.example/series.xml|Example Series|oldest
"""

STATE = {
    'seen': {},
    'unread': [
        {'id': 'n1', 'title': 'Harbour reopens after the storm', 'link': 'https://news.example/1', 'feed_url': 'https://news.example/rss',
         'author': 'A. Writer', 'tags': ['World']},
        {'id': 'n2', 'title': 'A much longer headline that goes on and on to show how the popup shortens a title '
                              'when it does not fit the line any more', 'link': 'https://news.example/2',
         'feed_url': 'https://news.example/rss'},
        {'id': 'b1', 'title': 'New release of the example tool', 'link': 'https://blog.example/1', 'feed_url': 'https://blog.example/atom'},
    ],
    'read_later': [{'id': 's1', 'title': 'Saved for the weekend', 'link': 'https://news.example/saved'}],
    'available_updates': [{'pkgname': 'libexample', 'title': 'libexample 1.0_1 -> 1.1_1'},
                          {'pkgname': 'exampled', 'title': 'exampled 2.3_1 -> 2.4_1'}],
    'orphans': ['libold', 'libolder'],
    'live_channels': [{'channel': 'examplechan', 'title': 'Playing with friends', 'category': 'Just Chatting',
                       'viewers': 1234, 'started': NOW - 3 * 3600 - 21 * 60}],
    'live_youtube_channels': [{'channel': '@examplebeta', 'title': 'Evening stream', 'viewers': 56}],
}


def episode(number, title, date):
    return {'id': f'ep{number}', 'title': title, 'date': date, 'season': 1, 'episode': number}


MEDIA = {'sources': {
    'https://media.example/feed.xml': {
        'title': 'Example Podcast', 'baselined': True,
        'episodes': [episode(1, 'Example Podcast S01E01 First', '2026-10-01'), episode(2, 'Example Podcast S01E02 Second', '2026-10-08')],
        'known': ['ep1', 'ep2'], 'new': ['ep2'], 'watched': ['ep1'], 'files': {}, 'last_watched': None,
    },
    'https://media.example/series.xml': {
        'title': 'Example Series', 'baselined': True,
        'episodes': [episode(1, 'Example Series S01E01 Pilot', '2026-09-01'), episode(2, 'Example Series S01E02 Next', '2026-09-08')],
        'known': ['ep1', 'ep2'], 'new': [], 'watched': [], 'files': {}, 'last_watched': None,
    },
}}

SCENARIO = sys.argv[1] if len(sys.argv) > 1 else 'full'
if SCENARIO == 'quiet':
    STATE = {'seen': {}, 'unread': [], 'read_later': STATE['read_later']}
    MEDIA = {'sources': {}}
elif SCENARIO in ('media_menu', 'media_removed'):
    import copy
    CONFIG += 'https://media.example/film.xml|Example Film|movie\n'
    STATE = {'seen': {}, 'unread': [], 'read_later': STATE['read_later']}
    MEDIA = copy.deepcopy(MEDIA)
    MEDIA['sources']['https://media.example/series.xml']['watched'] = ['ep1', 'ep2']
    MEDIA['sources']['https://media.example/series.xml']['last_watched'] = {
        'id': 'ep2', 'title': 'Example Series S01E02 Next', 'at': NOW - 100}
    film_file = pathlib.Path(HOME, 'videos', 'Example Film', 'film.mkv')  # a real file, for the Trash
    film_file.parent.mkdir(parents=True)
    film_file.write_bytes(b'not really a film')
    MEDIA['sources']['https://media.example/film.xml'] = {
        'title': 'Example Film', 'baselined': True, 'episodes': [episode(1, 'Example Film', '2026-08-01')],
        'known': ['ep1'], 'new': [], 'watched': ['ep1'], 'files': {'ep1': {'video': str(film_file), 'subs': []}},
        'last_watched': {'id': 'ep1', 'title': 'Example Film', 'at': NOW - 3600}, 'remove_at': NOW + 5 * 3600}
elif SCENARIO != 'full':
    raise SystemExit(f'unknown scenario {SCENARIO!r}')

config_dir = pathlib.Path(HOME, '.config', 'flux-tray')
config_dir.mkdir(parents=True)
(config_dir / 'config.conf').write_text(CONFIG)
(config_dir / 'state.json').write_text(json.dumps(STATE))
(config_dir / 'media.json').write_text(json.dumps(MEDIA))

time.time = lambda: NOW

from flux_tray.gi_env import GLib, Gtk  # noqa: E402
import flux_tray.app as app_module  # noqa: E402

GLib.timeout_add = lambda *a, **k: 0
GLib.timeout_add_seconds = lambda *a, **k: 0
for name in ('probe_connectivity', 'check_orphans_if_due', 'watch_media_config', '_measure_screen'):
    setattr(app_module.FluxTray, name, lambda self, *a, **k: None)

SIMPLE = (str, int, float, bool)
_fresh_cache = {}


def default_classes(widget):
    kind = type(widget)
    if kind not in _fresh_cache:
        try:
            _fresh_cache[kind] = set(kind().get_style_context().list_classes())
        except Exception:
            _fresh_cache[kind] = set()
    return _fresh_cache[kind]


def describe(widget):
    node = {'type': type(widget).__name__, 'visible': widget.get_visible(), 'sensitive': widget.get_sensitive()}
    classes = sorted(set(widget.get_style_context().list_classes()) - default_classes(widget))
    if classes:
        node['classes'] = classes
    for key, value in (('tooltip', widget.get_tooltip_text()), ('tooltip_markup', widget.get_tooltip_markup())):
        if value and not (key == 'tooltip_markup' and value == node.get('tooltip')):
            node[key] = value
    margins = [widget.get_margin_start(), widget.get_margin_end(), widget.get_margin_top(), widget.get_margin_bottom()]
    if any(margins):
        node['margins'] = margins
    if widget.get_hexpand():
        node['hexpand'] = True
    if isinstance(widget, Gtk.Label):
        node['text'] = widget.get_label()
        node['markup'] = widget.get_use_markup()
        node['xalign'] = round(widget.get_xalign(), 2)
        node['ellipsize'] = widget.get_ellipsize().value_nick
        node['wrap'] = widget.get_line_wrap()
    elif isinstance(widget, (Gtk.Button, Gtk.ToggleButton)) and not isinstance(widget, Gtk.MenuButton):
        node['text'] = widget.get_label()
        if isinstance(widget, Gtk.ToggleButton):
            node['active'] = widget.get_active()
    elif isinstance(widget, Gtk.Entry):
        node['text'] = widget.get_text()
    elif isinstance(widget, Gtk.Range):
        node['range'] = [widget.get_adjustment().get_lower(), widget.get_adjustment().get_upper(), widget.get_value()]
    elif isinstance(widget, Gtk.ListBoxRow):
        node['selectable'], node['activatable'] = widget.get_selectable(), widget.get_activatable()
    attrs = {k: v for k, v in sorted(vars(widget).items()) if not k.startswith('_') and isinstance(v, SIMPLE)}
    if attrs:
        node['attrs'] = attrs
    if isinstance(widget, Gtk.Container):
        children = [describe(child) for child in widget.get_children()]
        if children:
            node['children'] = children
    return node


def pump():
    for _ in range(50):
        while Gtk.events_pending():
            Gtk.main_iteration()


def walk(widget):
    yield widget
    if isinstance(widget, Gtk.Container):
        for child in widget.get_children():
            yield from walk(child)


def media_scenario(tray):
    series = 'https://media.example/series.xml'
    if SCENARIO == 'media_menu':
        return {'menus': {url: describe(tray._media_menu_content(url, Gtk.Popover())) for url in MEDIA['sources']}}
    menu = tray._media_menu_content(series, Gtk.Popover())
    button = next(w for w in walk(menu) if isinstance(w, Gtk.Button) and (w.get_label() or '').startswith('Remove all'))
    button.clicked()
    pump()
    trash = pathlib.Path(HOME, '.local', 'share', 'Trash', 'files')
    return {'config': (config_dir / 'config.conf').read_text(),
            'media_json_sources': sorted(json.loads((config_dir / 'media.json').read_text())['sources']),
            'in_the_trash': sorted(p.name for p in trash.iterdir()) if trash.exists() else [],
            'left_in_the_media_folder': sorted(str(p.relative_to(HOME)) for p in pathlib.Path(HOME, 'videos').rglob('*')),
            'popup': describe(tray.popup)}


def main():
    from flux_tray.ui.popup import POPUP_CSS
    tray = app_module.FluxTray()
    tray.show_popup()
    pump()
    if SCENARIO in ('media_menu', 'media_removed'):
        json.dump(media_scenario(tray), sys.stdout, indent=1, sort_keys=True, ensure_ascii=False)
        sys.stdout.write('\n')
        return
    window = tray.popup
    result = {
        'window': {'decorated': window.get_decorated(), 'resizable': window.get_resizable(),
                   'skip_taskbar': window.get_skip_taskbar_hint(),
                   'type_hint': window.get_type_hint().value_nick},
        'css': POPUP_CSS.strip().splitlines(),
        'tree': describe(window),
    }
    json.dump(result, sys.stdout, indent=1, sort_keys=True, ensure_ascii=False)
    sys.stdout.write('\n')


main()
