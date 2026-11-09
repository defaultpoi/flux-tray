"""Podcasts, series and movies: checking sources, keeping the next episodes
downloaded, playing them in mpv and remembering what was watched."""

import html
import os
import re
import threading
import time as time_module

from ..gi_env import GLib, Gdk, GdkPixbuf, Gio, Gtk, Pango
from ..config import load_media_movies, load_media_settings, load_media_sources, remove_media_sources
from ..constants import CONFIG_FILE
from ..desktop import move_to_trash, primary_monitor_size
from ..fileutil import remove_empty_dirs
from ..hls import DownloadCancelled, is_hls
from ..media import (
    clean_title,
    download_episode,
    episode_basepath,
    episode_label,
    episode_paths,
    merge_episodes,
    new_unwatched,
    resolve_files,
    unwatched_count,
    upcoming,
)
from ..mediasources import NoDriver, normalize_files, normalize_saved
from ..network import run_when_online
from ..playback import counts_as_watched, is_media_playing, mpv_append_playlist, play_media_file, resume_point
from ..screen import media_target_size, remember_screen_size
from ..state import new_media_entry, save_media, save_state
from ..metadata import format_metadata_for_tooltip, get_cached_metadata, refresh_metadata_cache
from ..media_cache import (
    load_media_cache, update_media_cache, get_new_items, mark_listing, mark_seen, is_seen,
    get_all_cached_items, sync_metadata_ids, title_with_year,
)
from ..watch import find_source, is_searching, new_watch_entry, search_due, source_line
from ..log import _log


_discovery_running = threading.Lock()  # held by the discovery check that is running
_watch_searching = threading.Lock()  # held while the watched titles are being looked for
_DISCOVERY_TYPE_NAMES = {'movie': 'movies', 'series': 'series'}  # a kind, by the name discovery_types= uses


def _chart_item(episode, kind, rank, plugin):
    """A discovery item from an episode of a discovery source (a chart): its id is an IMDb id when
    it looks like one, and `rank` is its place in the chart."""
    ident = str(episode.get('id') or '')
    imdb_id = ident if re.fullmatch(r'tt\d+', ident) else (episode.get('imdb_id') or None)
    year = str(episode.get('year') or '')
    url = episode.get('url') or ident
    return {'id': url, 'title': episode.get('title') or ident, 'type': kind, 'url': url, 'imdb_id': imdb_id,
            'year': year if re.fullmatch(r'(?:19|20)\d{2}', year) else '', 'date': '', 'rank': rank, '_plugin': plugin}


def _give_known_ids(item):
    """Gives a discovery item the TMDb and IMDb ids the metadata cache has for its
    title, so that it is keyed by them from the start."""
    meta = get_cached_metadata(title_with_year(item), item.get('type') or 'movie', item.get('url') or item.get('id'))
    if meta:
        item['tmdb_id'] = item.get('tmdb_id') or meta.get('tmdb_id')
        item['imdb_id'] = item.get('imdb_id') or meta.get('imdb_id')


MEDIA_CONFIG_DEBOUNCE_MS = 800  # an editor or the browser extension may write the file in several steps
PLAY_PARTIAL_MIN_BYTES = 1_500_000  # enough of a download for mpv to start on (about a minute of video)
MEDIA_MARKER_COLORS = {'ready': '#2e8b57', 'busy': '#d08000', 'failed': '#c0392b', 'idle': '#808080', 'playing': '#2980b9'}


def duration_text(seconds):
    """A time ahead for a row, in the largest sensible unit: '2 days', '23 h', '45 min'."""
    minutes = max(1, int(seconds // 60))
    if minutes >= 48 * 60:
        return f'{minutes // (24 * 60)} days'
    if minutes >= 60:
        return f'{(minutes + 30) // 60} h'
    return f'{minutes} min'


def media_row_view(name, entry, order, downloaded, status, error=None, now=None, url=None, is_playing=False):
    """What a source's row shows: (name, next episode text, stats text, tooltip,
    marker colour key). `downloaded` is whether the next episode is on disk and
    `status` its entry in the downloads' progress ('queued', 'downloading' with a
    percent, or 'failed' with an error), None when nothing is going on. `error` is
    why the source's last check failed, if it did. A watched movie that is due to be
    removed says when. `is_playing` indicates if this source is currently playing in mpv."""
    # Extract IMDb/TMDb IDs from the next episode (or entry for movies)
    imdb_id = None
    tmdb_id = None
    if entry.get('episodes'):
        nxt = upcoming(entry.get('episodes', []), entry.get('watched', []), order, 1)
        if nxt:
            imdb_id = nxt[0].get('imdb_id')
            tmdb_id = nxt[0].get('tmdb_id')
    last = entry.get('last_watched')
    last_line = f"Last watched: {last.get('title') or last['id']}" if last else ''
    error_line = f'Last check failed: {error}' if error else ''
    news = new_unwatched(entry)
    nxt = upcoming(entry.get('episodes', []), entry.get('watched', []), order, 1)
    if not entry.get('episodes') and error:
        return name, 'cannot be read', '', '\n'.join((error, 'Click to try again')), 'failed'
    if not nxt:
        text = 'all watched' if entry.get('episodes') else 'no episodes yet'
        stats, removal_line = (f'{news} new' if news else ''), ''
        if entry.get('remove_at') is not None and entry.get('episodes'):
            left = max(0.0, entry['remove_at'] - (time_module.time() if now is None else now))
            stats = f'removed in {duration_text(left)}'
            removal_line = f'Removed with its file in {duration_text(left)}. Right-click it and choose "I didn\'t finish it" to keep it.'
        return name, text, stats, '\n'.join(p for p in (removal_line, last_line, error_line) if p), 'idle'
    episode = nxt[0]
    # What the cached metadata (TMDb/OMDb) says about the series or movie (not the episode)
    title = entry.get('title') or name
    meta = get_cached_metadata(title, url=url, imdb_id=imdb_id, tmdb_id=tmdb_id)
    total_episodes = meta.get('total_episodes') if meta else None
    label = episode_label(episode, total_episodes)
    text = ' '.join(p for p in (label, clean_title(episode.get('title'), (name, entry.get('title')))) if p)
    state = (status or {}).get('state')
    if state == 'downloading':
        stats, color, hint = f"{status.get('percent', 0)}%", 'busy', ('Click to watch while it downloads' if status.get('part') else 'Downloading')
    elif state == 'queued':
        stats, color, hint = 'queued', 'busy', 'Waiting to download'
    elif state == 'failed':
        stats, color, hint = 'failed', 'failed', f"Download failed: {status.get('error') or 'unknown error'} (retried at the next check; click to retry now)"
    elif is_playing:
        stats, color, hint = 'playing', 'playing', 'Playing in mpv'
    elif downloaded:
        stats, color, hint = 'ready', 'ready', 'Click to play'
    else:
        stats, color, hint = 'not downloaded', 'idle', 'Click to download'
    if news:
        stats = f'{stats} - {news} new' if stats else f'{news} new'

    # The tooltip is markup: the plain parts are escaped, the metadata already is
    parts = [html.escape(p, quote=False) for p in (text, hint, f'{unwatched_count(entry)} unwatched', last_line, error_line) if p]
    markup = format_metadata_for_tooltip(meta)
    if markup:
        parts.insert(1 if text else 0, markup)  # after the episode text
    return name, text, stats, '\n'.join(parts), color


def describe_media_error(error):
    """A source's failure as one line for its row: a driver's own message as it is
    (a ValueError, or no driver), anything else with the kind of error."""
    message = str(error).strip()
    if isinstance(error, (NoDriver, ValueError)) and message:
        return message[:300]
    return f'{error.__class__.__name__}: {message}'[:300].rstrip(': ')


def create_metadata_tooltip(meta):
    """Create a custom tooltip widget with poster image and metadata.
    Layout: top-left image, top-right details, bottom plot (full width).
    Returns a Gtk.Box widget or None if no metadata."""
    if not meta:
        return None

    # Main vertical container: top section (horizontal), bottom plot (full width)
    main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    main_box.set_margin_start(8)
    main_box.set_margin_end(8)
    main_box.set_margin_top(6)
    main_box.set_margin_bottom(6)

    # Top horizontal section: image on left, details on right
    top_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
    top_box.set_valign(Gtk.Align.START)

    # Poster image (top-left, 200px max width)
    imdb_id = meta.get('imdb_id')
    tmdb_id = meta.get('tmdb_id')
    title = meta.get('title') or meta.get('Title')
    poster_path = None
    if title:
        from ..metadata import get_cached_poster
        poster_path = get_cached_poster(title, imdb_id=imdb_id, tmdb_id=tmdb_id)

    if poster_path:
        try:
            image = Gtk.Image()
            pixbuf = GdkPixbuf.Pixbuf.new_from_file(poster_path)
            # Scale to reasonable width (200px max)
            if pixbuf.get_width() > 200:
                pixbuf = pixbuf.scale_simple(200, int(200 * pixbuf.get_height() / pixbuf.get_width()), GdkPixbuf.InterpType.BILINEAR)
            image.set_from_pixbuf(pixbuf)
            image.set_halign(Gtk.Align.START)
            image.set_valign(Gtk.Align.START)
            top_box.pack_start(image, False, False, 0)
        except Exception:
            pass
    else:
        # Fallback: load from URL in background (for cases where poster not yet cached)
        poster_url = meta.get('poster') or meta.get('Poster')
        if poster_url and poster_url != 'N/A':
            try:
                image = Gtk.Image()
                image.set_halign(Gtk.Align.START)
                image.set_valign(Gtk.Align.START)
                # Load poster asynchronously in background
                def load_poster():
                    try:
                        import urllib.request
                        from ..metadata import TMDB_USER_AGENT
                        ua = TMDB_USER_AGENT if 'image.tmdb.org' in poster_url else 'flux-tray/1.0'
                        req = urllib.request.Request(poster_url, headers={'User-Agent': ua})
                        with urllib.request.urlopen(req, timeout=5) as resp:
                            data = resp.read()
                        loader = GdkPixbuf.PixbufLoader()
                        loader.write(data)
                        loader.close()
                        pixbuf = loader.get_pixbuf()
                        # Scale to reasonable width (200px max)
                        if pixbuf.get_width() > 200:
                            pixbuf = pixbuf.scale_simple(200, int(200 * pixbuf.get_height() / pixbuf.get_width()), GdkPixbuf.InterpType.BILINEAR)
                        GLib.idle_add(image.set_from_pixbuf, pixbuf)
                    except Exception:
                        GLib.idle_add(image.set_from_icon_name, 'image-missing', Gtk.IconSize.DIALOG)
                threading.Thread(target=load_poster, daemon=True).start()
                top_box.pack_start(image, False, False, 0)
            except Exception:
                pass

    # Details on the right (top-right)
    details_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    details_box.set_valign(Gtk.Align.START)
    details_box.set_hexpand(True)

    # Title + year
    title = meta.get('title') or meta.get('Title')
    year = meta.get('year') or meta.get('Year')
    if title:
        year_str = f" ({year})" if year else ''
        # Escape title for markup (e.g., "Law & Order" -> "Law & Order")
        escaped_title = GLib.markup_escape_text(title)
        title_label = Gtk.Label(label=f'{title}{year_str}')
        title_label.set_markup(f'<b><span size="large">{escaped_title}{year_str}</span></b>')
        title_label.set_xalign(0)
        title_label.set_line_wrap(True)
        title_label.set_max_width_chars(60)
        title_label.set_margin_bottom(8)  # empty row below title
        details_box.pack_start(title_label, False, False, 0)

    # Helper to add a field row
    def add_field(label_text, value_text):
        if value_text is None or value_text == '' or value_text == 'N/A':
            return
        field_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        field_box.set_margin_top(1)
        field_box.set_margin_bottom(1)
        label = Gtk.Label(label=label_text)
        label.set_xalign(0)
        label.get_style_context().add_class('menu-text')
        label.set_markup(f'<b>{GLib.markup_escape_text(label_text)}</b>')
        value = Gtk.Label(label=value_text)
        value.set_xalign(0)
        value.set_line_wrap(True)
        value.set_max_width_chars(50)
        field_box.pack_start(label, False, False, 0)
        field_box.pack_start(value, True, True, 0)
        details_box.pack_start(field_box, False, False, 0)

    # Ratings: combine rating + votes on same line
    imdb_rating = meta.get('imdb_rating') or meta.get('imdbRating')
    imdb_votes = meta.get('imdb_votes') or meta.get('imdbVotes')
    if imdb_rating is not None and imdb_rating != 'N/A':
        rating_str = f'{imdb_rating:.1f}/10'
        if imdb_votes and imdb_votes != 'N/A':
            rating_str += f' ({imdb_votes} votes)'
        add_field('IMDb', rating_str)

    tmdb_rating = meta.get('tmdb_rating') or meta.get('tmdbRating')
    tmdb_votes = meta.get('tmdb_votes') or meta.get('tmdbVotes')
    if tmdb_rating is not None and tmdb_rating != 'N/A':
        rating_str = f'{tmdb_rating:.1f}/10'
        if tmdb_votes and tmdb_votes != 'N/A':
            rating_str += f' ({tmdb_votes} votes)'
        add_field('TMDb', rating_str)

    metascore = meta.get('metascore') or meta.get('Metascore')
    if metascore is not None and metascore != 'N/A':
        add_field('Metascore', f'{metascore}/100')

    # Ratings from OMDB (Rotten Tomatoes, etc.) - exclude IMDb/TMDb/Metacritic since shown above
    ratings = meta.get('ratings') or meta.get('Ratings')
    if ratings:
        for r in ratings:
            if isinstance(r, dict) and r.get('Source') and r.get('Value'):
                source = r['Source']
                if source not in ('Internet Movie Database', 'Metacritic'):
                    add_field(source, r['Value'])

    # Fields to display (excluding: production countries, production companies, imdb id, tmdb id, homepage, status, spoken languages, source, plot)
    field_mappings = [
        ('Type', ['type', 'Type']),
        ('Rated', ['Rated']),
        ('Genre', ['genre', 'Genre']),
        ('Runtime', ['runtime', 'Runtime']),
        ('Released', ['released', 'Released']),
        ('Language', ['language', 'Language']),
        ('Country', ['country', 'Country']),
        ('Awards', ['awards', 'Awards']),
        ('Director', ['director', 'Director']),
        ('Writer', ['writer', 'Writer']),
        ('Actors', ['actors', 'Actors']),
        ('Tagline', ['tagline']),
        ('Total Seasons', ['total_seasons', 'totalSeasons']),
        ('Total Episodes', ['total_episodes', 'totalEpisodes']),
        ('DVD', ['DVD']),
        ('Box Office', ['BoxOffice']),
    ]

    # Find value from any of the possible keys
    for display_label, keys in field_mappings:
        value = None
        for key in keys:
            value = meta.get(key)
            if value is not None and value != '':
                break
        if value is not None:
            # Format lists/arrays
            if isinstance(value, list):
                if value and isinstance(value[0], dict):
                    value = ', '.join(str(v.get('name', v)) for v in value)
                else:
                    value = ', '.join(str(v) for v in value)
            # Format numbers
            elif isinstance(value, float):
                value = f'{value:.1f}'
            # Skip null/empty/N/A
            elif value == '' or value == 'null' or value == 'N/A':
                continue

            # Limit writers to first 1, actors to first 3
            if display_label == 'Writer':
                parts = [p.strip() for p in str(value).split(',')]
                value = parts[0] if parts else str(value)
            elif display_label == 'Actors':
                parts = [p.strip() for p in str(value).split(',')]
                value = ', '.join(parts[:3]) if parts else str(value)

            add_field(display_label, str(value))

    top_box.pack_start(details_box, True, True, 0)
    main_box.pack_start(top_box, False, False, 0)

    # Plot: full-width at bottom (below both image and details)
    plot_value = None
    for key in ['overview', 'Plot']:
        v = meta.get(key)
        if v is not None and v != '' and v != 'N/A':
            plot_value = v
            break

    if plot_value:
        plot_label = Gtk.Label(label=str(plot_value))
        plot_label.set_line_wrap(True)
        plot_label.set_max_width_chars(80)
        plot_label.set_xalign(0)
        plot_label.set_yalign(0)
        plot_label.set_margin_top(8)
        plot_label.set_margin_bottom(4)
        plot_label.get_style_context().add_class('menu-text')
        main_box.pack_start(plot_label, False, False, 0)

    main_box.show_all()
    return main_box


class MediaMixin:
    # ---- checking the sources ------------------------------------------------

    def initial_media_check(self):
        threading.Thread(target=self.remove_due_movies, daemon=True).start()  # some fell due while the app was closed
        run_when_online(self.start_media_check)
        return False

    def periodic_media_check(self):
        threading.Thread(target=self.remove_due_movies, daemon=True).start()
        self.start_media_check()
        # re-arm with the interval currently in config.conf, so edits apply after the next check
        GLib.timeout_add_seconds(load_media_settings()['interval'], self.periodic_media_check)
        return False

    def periodic_discovery_check(self):
        self.start_discovery_fetch()
        # re-arm with the interval currently in config.conf
        GLib.timeout_add_seconds(load_media_settings()['interval'], self.periodic_discovery_check)
        return False

    def initial_discovery_check(self):
        """Run discovery fetch on startup after a short delay."""
        run_when_online(self.start_discovery_fetch)
        return False

    # ---- Discovery feed (plugins with fetch_discovery) --------------------------

    def start_discovery_fetch(self):
        """Fetches the discovery feeds of the plugins that have one, in a thread. A fetch
        that is still running is not started again."""
        if _discovery_running.acquire(blocking=False):
            threading.Thread(target=self._fetch_discovery_guarded, daemon=True).start()

    def _fetch_discovery_guarded(self):
        try:
            self._fetch_discovery_bg()
        except Exception as e:
            _log(f'discovery fetch error: {e}')
        finally:
            _discovery_running.release()

    def _discovery_seen(self):
        with self.lock:
            return {key for key in self.state.get('media_discovery_seen', []) if isinstance(key, str)}

    def _dismiss_discovery(self, items):
        """Marks discovery items dismissed (in the state, under its lock)."""
        with self.lock:
            seen = {key for key in self.state.get('media_discovery_seen', []) if isinstance(key, str)}
            for item in items:
                mark_seen(seen, item)
            self.state['media_discovery_seen'] = sorted(seen)
            save_state(self.state)

    def _fetch_discovery_bg(self):
        """A discovery check, all of it but the window, in a thread: reads what `discovery=` names
        (charts, say) or else asks the plugins that have a fetch_discovery, files what was found
        in the discovery cache (an item gets the ids that the metadata cache already has for it),
        looks the titles up for their posters, ratings and ids, and re-keys the entries those ids
        reach. The popup is touched on the main loop only, so no disk is read or written there on
        account of a check."""
        self.media_registry.refresh()
        settings = load_media_settings()
        types = settings['discovery_types']
        if settings['discovery']:
            found, scopes = self._read_discovery_sources(settings['discovery'], types)
        else:
            found, scopes = self._read_discovery_plugins(types), set()
        seen = self._discovery_seen()

        def file_items(cache):
            fresh = get_new_items(cache, found, seen)
            mark_listing(cache, found, scopes)
            return fresh
        fresh = update_media_cache(file_items)
        if fresh:
            _log(f'discovery: {len(fresh)} new items')
            GLib.idle_add(self._discovery_news)
        else:
            _log('discovery: no new items')
        self._enrich_discovery()

    def _read_discovery_plugins(self, types):
        """What the plugins' fetch_discovery functions find (the default source of discovery)."""
        existing_media_urls = set()
        with self._media_data_lock:
            for url, entry in self.media['sources'].items():
                if url.startswith('discovery:'):
                    continue
                for ep in entry.get('episodes') or []:
                    existing_media_urls.add(ep.get('ref') or ep.get('url') or ep.get('id'))
        found = []
        for plugin in self.media_registry.discovery_plugins():
            try:
                items = plugin.module.fetch_discovery(types=types, existing_media_urls=existing_media_urls)
            except Exception as e:
                _log(f'discovery fetch error from {plugin.name}: {e}')
                continue
            for item in items:
                item['_plugin'] = plugin.name
                _give_known_ids(item)
            found.extend(items)
        return found

    def _read_discovery_sources(self, sources, types):
        """What the sources named by `discovery=` list (a chart's titles, in its order): (items,
        the (plugin, kind) pairs that gave any, which are the ones whose listing is brought up to
        date). A source that cannot be read is left as it was."""
        found, scopes = [], set()
        for source, kind in sources:
            if _DISCOVERY_TYPE_NAMES[kind] not in types:
                continue
            try:
                driver, target = self.media_registry.driver_for(source)
                _title, episodes = driver.list_episodes(target)
            except Exception as e:
                _log(f'discovery source {source}: {describe_media_error(e)}')
                continue
            for rank, episode in enumerate(episodes, start=1):
                item = _chart_item(episode, kind, rank, driver.name)
                _give_known_ids(item)
                found.append(item)
            if episodes:
                scopes.add((driver.name, kind))
        return found, scopes

    def _enrich_discovery(self):
        """Looks up what the services know of the listed items and of the titles being watched
        (a few per check; OMDb by IMDb id when the item has one), then gives the entries the ids
        that came with it and shows the posters."""
        wanted = [(title_with_year(e), e.get('type') or 'movie', e.get('imdb_id'))
                  for e in get_all_cached_items(load_media_cache())]
        with self._media_data_lock:
            wanted += [(f"{w['title']} ({w['year']})" if w['year'] else w['title'], w['type'], w['imdb_id'])
                       for w in self.media.get('watch', {}).values()]
        if wanted:
            refresh_metadata_cache([t for t, _k, _i in wanted], [k for _t, k, _i in wanted],
                                   imdb_ids=[i for _t, _k, i in wanted])
            self._sync_discovery_ids()
        GLib.idle_add(self._discovery_refresh)

    def _sync_discovery_ids(self):
        """Gives the cached discovery entries the ids the metadata cache now has for them;
        what was dismissed under the old key is dismissed under the new."""
        def lookup(entry):
            return get_cached_metadata(title_with_year(entry), entry.get('type') or 'movie')
        with self.lock:
            seen = {key for key in self.state.get('media_discovery_seen', []) if isinstance(key, str)}
            moved = update_media_cache(lambda cache: sync_metadata_ids(cache, seen, lookup)[2])
            if moved:
                self.state['media_discovery_seen'] = sorted(seen)
                save_state(self.state)
        if moved:
            GLib.idle_add(self._discovery_refresh)

    def _discovery_news(self):
        """New discovery items: the same sound and popup as new feed items."""
        self.on_new_items()
        self._discovery_refresh()
        return False

    def _discovery_refresh(self):
        if self.popup and self.popup.get_visible():
            self.refresh_list()
        return False

    def _on_discovery_dismiss(self, _btn, item):
        """Right-click: a title nobody wants is dismissed for good; one that is being watched is
        no longer watched (and so is never shown again either)."""
        if item.get('watching'):
            self._stop_watching(item['_cache_key'])
        self._dismiss_discovery([item])
        GLib.idle_add(self.refresh_list, True)  # on the main loop, once the state is saved

    def _on_discovery_row_activated(self, item):
        """Left-click: a chart title is put on the watch list (see watch.py); a title that is already
        the page of a site is added as a source at once. Either way it leaves the discovery list."""
        if item.get('watching'):
            return  # looked for already
        if item.get('imdb_id') and self.media_registry.finders():
            self._watch_title(item)
        else:
            self._add_discovered_source(item)
        self._dismiss_discovery([item])
        GLib.idle_add(self.refresh_list, True)

    def _add_discovered_source(self, item):
        plugin_name = item.get('_plugin', 'unknown')
        source_url = item.get('id') or (list(item['urls'].values())[0] if item.get('urls') else None)
        if not source_url:
            _log(f'discovery row activated but no URL: {item}')
            return
        source = source_line(plugin_name, source_url)
        with self._media_data_lock:
            entry = self.media['sources'].setdefault(source, new_media_entry())
            entry['title'] = item['title']
            entry['movie'] = item.get('type') == 'movie'
            save_media(self.media)
        self.start_media_check(only=[source])

    # ---- titles to be downloaded: found on a site, then downloaded as any source is ----

    def _watch_title(self, item):
        """Puts a discovery item on the watch list and looks for it at once, in a thread. Every media
        check looks again, for as long as no site has it."""
        meta = get_cached_metadata(title_with_year(item), item.get('type') or 'movie', imdb_id=item.get('imdb_id'))
        year = item.get('year') or ((meta or {}).get('year') or '')[:4]
        with self._media_data_lock:
            self.media.setdefault('watch', {}).setdefault(
                item['_cache_key'], new_watch_entry(item, time_module.time(), year if year.isdigit() else ''))
            save_media(self.media)
        threading.Thread(target=self._search_watched, daemon=True).start()

    def _stop_watching(self, key):
        with self._media_data_lock:
            self.media.setdefault('watch', {}).pop(key, None)
            save_media(self.media)

    def _forget_watch_of(self, sources):
        """Takes the watch records whose title was found at one of `sources` off the list (the
        source is being removed, so the record has served). Call with the media lock held."""
        watch = self.media.setdefault('watch', {})
        for key in [k for k, w in watch.items() if w.get('source') in sources]:
            del watch[key]

    def _search_watched(self):
        """Asks the plugins that can find a title whether they have each title being watched, those not
        asked for a media check ago. A title that is found becomes a source (a film, if it is one) and
        is read and downloaded by the rules of [media]. One search at a time."""
        if not _watch_searching.acquire(blocking=False):
            return
        try:
            now = time_module.time()
            wait = load_media_settings()['interval']
            finders = self.media_registry.finders()
            with self._media_data_lock:
                due = [(key, dict(w)) for key, w in self.media.get('watch', {}).items() if search_due(w, now, wait)]
            found_sources = []
            for key, entry in due:
                found = find_source(finders, entry) if finders else None
                with self._media_data_lock:
                    record = self.media.get('watch', {}).get(key)
                    if record is None:
                        continue  # no longer wanted
                    record['checked'] = now
                    if found:
                        source = source_line(*found)
                        record['source'] = source
                        source_entry = self.media['sources'].setdefault(source, new_media_entry())
                        source_entry['title'] = entry['title']
                        source_entry['movie'] = entry['type'] == 'movie'
                        found_sources.append(source)
                        _log(f"watch: {entry['title']} found at {source}")
                    save_media(self.media)
            if found_sources:
                self.start_media_check(only=found_sources)
            if due:
                GLib.idle_add(self._discovery_refresh)
        except Exception as e:
            _log(f'watch search error: {e}')
        finally:
            _watch_searching.release()

    def _is_movie(self, url):
        """A film: a source of [media] marked `movie`, or one that was added from the watch list
        or the discovery list as a film."""
        entry = self.media['sources'].get(url)
        return url in load_media_movies() or bool(entry and entry.get('movie'))

    def _movie_sources(self):
        """Every source that is a film (a set). Takes the media lock: call it without."""
        with self._media_data_lock:
            return load_media_movies() | {url for url, entry in self.media['sources'].items() if entry.get('movie')}

    def start_media_check(self, only=None):
        """Checks every source, or just those in `only` (sources that were added to
        the config). A full check is skipped while another is running; a check of
        particular sources is queued behind it, never lost."""
        with self._media_request_lock:
            if only is None and self._media_checking:
                return  # a check is already in flight: skip this tick
            if only is None:
                self._media_pending_all = True
            else:
                self._media_pending |= set(only)
            if self._media_checking:
                return  # the running check looks for requests when it finishes
            self._media_checking = True
        threading.Thread(target=self._check_media_guarded, daemon=True).start()

    def _check_media_guarded(self):
        """Runs the requested checks one after another until none are waiting."""
        while True:
            with self._media_request_lock:
                everything, wanted = self._media_pending_all, set(self._media_pending)
                self._media_pending_all, self._media_pending = False, set()
                if not everything and not wanted:
                    self._media_checking = False  # decided under the lock, so no request slips in unseen
                    return
            try:
                self._check_media(None if everything else wanted)
            except BaseException:
                with self._media_request_lock:
                    self._media_checking = False
                raise

    def _check_media(self, only=None):
        """Reads every configured source and every source added by a click (or those in `only`),
        remembers what is new, then queues the downloads. A source that cannot be read keeps what is
        known of it. A full check also looks for the titles on the watch list."""
        new_total = 0
        self.media_registry.refresh()  # picks up plugins that were added or edited
        sources = [(url, configured) for url, _name, configured in load_media_sources()]
        configured_urls = {url for url, _configured in sources}
        with self._media_data_lock:
            sources += [(url, None) for url in self.media['sources']
                        if url not in configured_urls and not url.startswith('discovery:')]
        if only is None:
            self._search_watched()  # a title found now is read below, with the rest
        for url, configured in sources:
            if only is not None and url not in only:
                continue
            try:
                driver, target = self.media_registry.driver_for(url)
                title, episodes = driver.list_episodes(target)
            except Exception as error:  # network, bad JSON or feed, a plugin's bug: try again at the next check
                self.media_errors[url] = describe_media_error(error)
                if not isinstance(error, (NoDriver, ValueError)):
                    self.note_request_failure()
                continue
            self.media_errors.pop(url, None)
            with self._media_data_lock:
                entry = self.media['sources'].setdefault(url, new_media_entry())
                new_total += len(merge_episodes(entry, title, episodes, configured or driver.order))
                save_media(self.media)

        GLib.idle_add(self._on_media_new if new_total else self._refresh_media_rows)
        self._plan_media_downloads()
        # Trigger background metadata cache refresh only when new episodes found
        if new_total > 0:
            titles = [entry.get('title') or url for url, _n, _o in load_media_sources() if self.media['sources'].get(url)]
            threading.Thread(
                target=refresh_metadata_cache,
                args=(titles, ['series'] * len(titles)),
                daemon=True
            ).start()

    def _measure_screen(self):
        """Remembers the monitor's size for the download threads, which choose how large
        a video to fetch by it, now and whenever the monitors change."""
        remember_screen_size(primary_monitor_size())
        screen = Gdk.Screen.get_default()
        if screen is not None:
            screen.connect('monitors-changed', lambda *_: remember_screen_size(primary_monitor_size()))

    def watch_media_config(self):
        """Looks out for changes to config.conf, so that a source added by an editor or
        by the browser extension is read at once instead of at the next check."""
        self._media_known_sources = {u for u, _n, _o in load_media_sources()}
        try:
            self._media_config_monitor = Gio.File.new_for_path(CONFIG_FILE).monitor_file(Gio.FileMonitorFlags.NONE, None)
        except GLib.Error:
            return  # no file monitoring here: new sources wait for the next check
        self._media_config_monitor.connect('changed', self._on_media_config_event)

    def _on_media_config_event(self, _monitor, _file, _other, _event):
        if self._media_config_timer is not None:
            GLib.source_remove(self._media_config_timer)  # one reaction to a burst of events
        self._media_config_timer = GLib.timeout_add(MEDIA_CONFIG_DEBOUNCE_MS, self._media_config_changed)

    def _media_config_changed(self):
        self._media_config_timer = None
        urls = [u for u, _n, _o in load_media_sources()]
        new = [u for u in urls if u not in self._media_known_sources]
        self._media_known_sources = set(urls)
        if new:
            self.start_media_check(only=new)
        else:  # a name, an order or `ahead` may have changed: show it and keep the right ones downloaded
            self._plan_media_downloads()
            self._refresh_media_rows()
        return False

    def _on_media_new(self):
        if self.popup and self.popup.get_visible():
            self._refresh_media_rows()
        else:
            self.on_new_items()  # like a channel going live: sound and the popup opens
        return False

    # ---- downloads -----------------------------------------------------------

    @staticmethod
    def _media_file_ready(entry, episode_id):
        files = entry['files'].get(episode_id)
        return bool(files) and os.path.exists(files['video'])

    def _plan_media_downloads(self):
        """Queues the next `ahead` unwatched episodes of every source that are not on disk.
        Includes both configured sources and dynamically added sources (from discovery clicks)."""
        ahead = load_media_settings()['ahead']
        wanted = []
        if ahead > 0:
            config_sources = {u for u, _n, _o in load_media_sources()}
            # Get plugin names for identifying discovery-triggered sources (format: plugin_name:source_url)
            plugin_names = set()
            if hasattr(self, 'media_registry'):
                # MediaSources registry has drivers() method returning Driver objects with .name attribute
                if hasattr(self.media_registry, 'drivers'):
                    plugin_names = set(d.name for d in self.media_registry.drivers())
                elif hasattr(self.media_registry, 'plugins'):
                    plugin_names = set(self.media_registry.plugins.keys())
                elif hasattr(self.media_registry, 'by_source'):
                    # Test FakeRegistry has by_source dict
                    plugin_names = set(d.name for d in self.media_registry.by_source.values())
            with self._media_data_lock:
                # Configured sources
                for url, _name, order in load_media_sources():
                    entry = self.media['sources'].get(url)
                    if entry:
                        for episode in upcoming(entry['episodes'], entry['watched'], self._effective_order(url, order), ahead):
                            if not self._media_file_ready(entry, episode['id']):
                                wanted.append((url, episode['id']))
                # Dynamically added sources (from discovery clicks) - not in config, format: plugin_name:source_url
                for url, entry in self.media['sources'].items():
                    if url in config_sources or url.startswith('discovery:'):
                        continue
                    # Only treat as dynamic source if URL starts with a known plugin name (e.g., "fsonline_one:...")
                    prefix = url.split(':', 1)[0]
                    if prefix not in plugin_names:
                        continue  # stale/orphaned source, not a discovery click
                    if entry.get('episodes'):
                        # Use driver's default order for dynamic sources
                        try:
                            order = self.media_registry.driver_for(url)[0].order
                        except Exception:
                            order = 'newest'
                        for episode in upcoming(entry['episodes'], entry['watched'], order, ahead):
                            if not self._media_file_ready(entry, episode['id']):
                                wanted.append((url, episode['id']))
        self._enqueue_media(wanted)

    def _enqueue_media(self, items, front=False):
        with self._media_queue_lock:
            fresh = [i for i in items if i not in self._media_queue and i != self._media_current]
            self._media_queue = fresh + self._media_queue if front else self._media_queue + fresh
            for key in fresh:
                self.media_status[key] = {'state': 'queued'}
            start = bool(self._media_queue) and not self._media_worker_running
            if start:
                self._media_worker_running = True
        if start:
            threading.Thread(target=self._media_worker, daemon=True).start()
        if fresh:
            GLib.idle_add(self._refresh_media_rows)

    def _media_worker(self):
        while True:
            with self._media_queue_lock:
                if not self._media_queue:
                    self._media_worker_running = False
                    self._media_current = None
                    return
                key = self._media_queue.pop(0)
                self._media_current = key
            self._download_media_episode(*key)

    @staticmethod
    def _file_size(path):
        try:
            return os.path.getsize(path)
        except OSError:
            return 0

    def _media_display_name(self, url, entry):
        configured = {u: n for u, n, _o in load_media_sources()}.get(url)
        return configured or entry.get('title') or url

    def _cleanup_partial_files(self, url, episode_id, name, taken, title):
        """Delete partial/unfinished download files for an episode."""
        import os
        root = load_media_settings()['path']
        entry = self.media['sources'].get(url)
        if not entry:
            return
        episode = next((e for e in entry['episodes'] if e['id'] == episode_id), None)
        if not episode:
            return
        paths = episode_paths(root, name or entry.get('title') or url, episode, files={}, taken=taken, names=(entry.get('title'),))
        # Check for .part files and the actual file if it exists but is incomplete
        for file_key in ('video', 'subs'):
            if file_key == 'subs':
                # For subs, paths is a dict of lists
                for path in paths.get('subs', []):
                    part_path = path + '.part'
                    for p in (part_path, path):
                        try:
                            if os.path.exists(p):
                                os.remove(p)
                        except OSError:
                            pass
            else:
                part_path = paths.get('video', '') + '.part'
                for p in (part_path, paths.get('video', '')):
                    try:
                        if os.path.exists(p):
                            os.remove(p)
                    except OSError:
                        pass

    def _download_media_episode(self, url, episode_id):
        key = (url, episode_id)
        with self._media_data_lock:
            entry = self.media['sources'].get(url)
            episode = next((e for e in entry['episodes'] if e['id'] == episode_id), None) if entry else None
            taken = {f['video'] for i, f in entry['files'].items() if i != episode_id} if entry else set()  # its own old path is free
            name = self._media_display_name(url, entry) if entry else ''
        if episode is None:
            self.media_status.pop(key, None)
            return
        self.media_status[key] = {'state': 'downloading', 'percent': 0}
        GLib.idle_add(self._refresh_media_rows)
        shown = [-1]
        watchable = {}  # filled in for an HLS download to .ts or .mkv: its partial file plays while it grows

        def cancelled():
            """Check if this download has been cancelled."""
            with self._media_queue_lock:
                return key in self._media_cancel

        def progress(done, total):
            percent = int(done * 100 / total) if total else 0
            if percent != shown[0]:
                shown[0] = percent
                self.media_status[key] = {'state': 'downloading', 'percent': percent, **watchable,
                                          **({'length': total} if watchable and total else {})}  # seconds, for HLS
                GLib.idle_add(self._refresh_media_rows)

        try:
            driver = self.media_registry.driver_of(episode)
            root, names = load_media_settings()['path'], (entry.get('title'),)
            if driver.download:  # the driver fetches the files itself (yt-dlp, a plugin)
                base = episode_basepath(root, name, episode, taken, names=names)
                saved = normalize_saved(driver.download(episode, base, progress, cancelled))
            else:
                files = normalize_files(driver.resolve(episode) if driver.resolve else resolve_files(episode))
                paths = episode_paths(root, name, episode, files, taken, names=names)
                if is_hls(files['video']['url']) and paths['video'].lower().endswith(('.ts', '.mkv')):
                    watchable['part'] = paths['video'] + '.part'
                    self.media_status[key] = {'state': 'downloading', 'percent': max(shown[0], 0), **watchable}
                saved = download_episode(paths, files, progress=progress, cancelled=cancelled, screen=media_target_size())
        except Exception as error:  # the partial file stays, so the next try carries on
            # Check if it was a cancellation
            if isinstance(error, DownloadCancelled) or (cancelled() and 'cancelled' in str(error).lower()):
                self.media_status.pop(key, None)
                # Clean up partial files
                self._cleanup_partial_files(url, episode_id, name, taken, entry.get('title') if entry else None)
                GLib.idle_add(self._refresh_media_rows)
                return
            self.media_status[key] = {'state': 'failed', 'error': describe_media_error(error)}
            GLib.idle_add(self._refresh_media_rows)
            return
        with self._media_data_lock:
            entry['files'][episode_id] = saved
            save_media(self.media)
            # If this source is currently playing in mpv, append the new episode
            is_playing = is_media_playing(url)
            episode = next((e for e in entry['episodes'] if e['id'] == episode_id), None)
            ep_path = saved['video']
            # Get total episodes from cached metadata
            total_episodes = None
            title = entry.get('title') or name
            imdb_id = episode.get('imdb_id') if episode else None
            tmdb_id = episode.get('tmdb_id') if episode else None
            meta = get_cached_metadata(title, url=url, imdb_id=imdb_id, tmdb_id=tmdb_id)
            if meta and meta.get('total_episodes'):
                total_episodes = meta['total_episodes']
            ep_title = f"{name} · {episode_label(episode, total_episodes)} {clean_title(episode.get('title'), (name, entry.get('title')))}".strip() if episode else name
        self.media_status.pop(key, None)
        GLib.idle_add(self._refresh_media_rows)
        if is_playing and episode:
            mpv_append_playlist(ep_path, ep_title)

    # ---- playing and remembering ---------------------------------------------

    def _effective_order(self, url, configured):
        """The configured order, else the default of the driver that handles the source."""
        if configured in ('oldest', 'newest'):
            return configured
        try:
            return self.media_registry.driver_for(url)[0].order
        except NoDriver:
            return 'newest'

    def _media_source_order(self, url):
        return self._effective_order(url, next((o for u, _n, o in load_media_sources() if u == url), None))

    def on_media_row_clicked(self, url):
        """Plays a source's next unwatched episode, or starts downloading it first.
        For series, loads all downloaded unwatched episodes as a playlist."""
        order = self._media_source_order(url)
        with self._media_data_lock:
            entry = self.media['sources'].get(url)
            nxt = upcoming(entry['episodes'], entry['watched'], order, 1) if entry else []
            if not nxt:
                retry = not (entry and entry['episodes']) and url in self.media_errors
                if retry:
                    self.start_media_check()
                return
            episode = nxt[0]
            start = (entry.get('resume') or {}).get(episode['id'])
            ready = self._media_file_ready(entry, episode['id'])
            path = entry['files'][episode['id']]['video'] if ready else None
            name = self._media_display_name(url, entry)
            is_movie = self._is_movie(url)
            # Build playlist for series: all downloaded unwatched episodes in watch order
            playlist = []
            playlist_episode_ids = []  # track episode_ids in playlist order
            total_episodes = None
            if not is_movie and entry:
                # Get total episodes from cached metadata
                total_episodes = None
                title = entry.get('title') or name
                imdb_id = episode.get('imdb_id')
                tmdb_id = episode.get('tmdb_id')
                meta = get_cached_metadata(title, url=url, imdb_id=imdb_id, tmdb_id=tmdb_id)
                if meta and meta.get('total_episodes'):
                    total_episodes = meta['total_episodes']
                for ep in upcoming(entry['episodes'], entry['watched'], order, 100):  # large count = all
                    if self._media_file_ready(entry, ep['id']):
                        ep_path = entry['files'][ep['id']]['video']
                        ep_title = clean_title(ep.get('title'), (name, entry.get('title')))
                        playlist.append((ep_path, f"{name} \u00b7 {episode_label(ep, total_episodes)} {ep_title}".strip()))
                        playlist_episode_ids.append(ep['id'])
        length = None
        if not ready:
            status = self.media_status.get((url, episode['id']), {})
            part = status.get('part')
            if status.get('state') == 'downloading' and part and self._file_size(part) >= PLAY_PARTIAL_MIN_BYTES:
                path, length = part, status.get('length')
            else:
                if status.get('state') not in ('queued', 'downloading'):
                    self._enqueue_media([(url, episode['id'])], front=True)
                return
        if self.popup:
            self.popup.hide()
        shown = clean_title(episode.get('title'), (name, entry.get('title')))
        title = f"{name} \u00b7 {' '.join(p for p in (episode_label(episode, total_episodes), shown) if p)}"
        episode_id = episode['id']
        track = ready or bool(length)
        stopped = {}
        # Store playlist episode_ids for this source to track playlist position
        if playlist_episode_ids:
            self._media_playlist_episodes[url] = playlist_episode_ids
            # Set initial playing episode
            from ..playback import set_media_playing
            set_media_playing(url, episode_id)
        # Play first episode, then append playlist for series
        play_media_file(path, title, total_seconds=length, start=start, on_stopped=stopped.update,
                        sleep_seconds=load_media_settings()['sleep'],
                        on_finished=(lambda percent, remaining:
                                     GLib.idle_add(self._on_media_played, url, episode_id, percent, remaining,
                                                   dict(stopped), start)) if track else None,
                        on_playlist_advance=(lambda playlist_pos:
                                             GLib.idle_add(self._on_playlist_advanced, url, playlist_pos)) if playlist else None)
        # Append remaining episodes to mpv playlist for series
        if playlist:
            from ..playback import mpv_append_playlist
            # Skip first episode (already playing)
            for ep_path, ep_title in playlist[1:]:
                mpv_append_playlist(ep_path, ep_title)

    def _on_media_played(self, url, episode_id, percent, remaining, info=None, start=None):
        """Playback of an episode ended. `info` says where it stopped and how much of it was
        played (seeking over parts is not playing); `start` is where it carried on from, all
        of which counts as seen. Watched through: marked, and a movie is set to be removed.
        Otherwise the place is remembered for the next time."""
        info = info or {}
        played, duration = info.get('played'), info.get('duration')
        fraction = (played + (start or 0.0)) / duration if isinstance(played, (int, float)) and duration else None
        if counts_as_watched(percent, remaining, fraction):
            self.mark_media_watched(url, episode_id)
            if self._is_movie(url):
                self._schedule_movie_removal(url)
        elif info.get('position') is not None:  # nothing seen means nothing to change
            self._set_media_resume(url, episode_id, resume_point(info['position'], watched=False))
        # Clear playlist tracking and playing state when playback ends
        self._media_playlist_episodes.pop(url, None)
        from ..playback import clear_media_playing
        clear_media_playing()
        GLib.idle_add(self._refresh_media_rows)
        return False

    def _on_playlist_advanced(self, url, playlist_pos):
        """Called when mpv advances to the next playlist item (user pressed 'next').
        Triggers download planning to queue the next episode per the 'ahead' setting.
        Also updates the currently playing episode tracker."""
        # playlist_pos is 1-indexed. Position 1 is the first episode.
        # When it advances to position 2, we should plan downloads for the next episodes.
        self._plan_media_downloads()
        # Update the currently playing episode tracker
        playlist_eps = self._media_playlist_episodes.get(url)
        if playlist_eps and playlist_pos <= len(playlist_eps):
            new_episode_id = playlist_eps[playlist_pos - 1]  # 1-indexed to 0-indexed
            from ..playback import set_media_playing
            set_media_playing(url, new_episode_id)
            # Refresh the row to show playing state
            GLib.idle_add(self._refresh_media_rows)
        return False

    def _set_media_resume(self, url, episode_id, seconds):
        """Remembers where playback of an episode stopped; None forgets it."""
        with self._media_data_lock:
            entry = self.media['sources'].get(url)
            if not entry:
                return
            resume = entry.setdefault('resume', {})
            if seconds is None and episode_id not in resume or resume.get(episode_id) == seconds:
                return
            if seconds is None:
                del resume[episode_id]
            else:
                resume[episode_id] = seconds
            save_media(self.media)

    def mark_media_watched(self, url, episode_id):
        with self._media_data_lock:
            entry = self.media['sources'].get(url)
            if not entry:
                return
            if episode_id not in entry['watched']:
                entry['watched'].append(episode_id)
            episode = next((e for e in entry['episodes'] if e['id'] == episode_id), {})
            entry['last_watched'] = {'id': episode_id, 'title': episode.get('title') or episode_id, 'at': time_module.time()}
            entry['new'] = [i for i in entry['new'] if i != episode_id]
            entry.setdefault('resume', {}).pop(episode_id, None)  # watched through: nowhere to carry on from
            save_media(self.media)
        self._plan_media_downloads()  # keeps the next ones ready
        self._refresh_media_rows()
        threading.Thread(target=self._prune_watched_files, args=(url,), daemon=True).start()

    def mark_media_unwatched(self, url, episode_id):
        """Puts a watched episode back as not watched (it was counted by mistake, say the
        person fell asleep), and stops a movie's removal. True when it was watched."""
        with self._media_data_lock:
            entry = self.media['sources'].get(url)
            if not entry or episode_id not in entry['watched']:
                return False
            entry['watched'] = [i for i in entry['watched'] if i != episode_id]
            if (entry.get('last_watched') or {}).get('id') == episode_id:
                entry['last_watched'] = None
            entry['remove_at'] = None
            save_media(self.media)
        self._plan_media_downloads()  # its file may have gone to the Trash with `behind`
        self._refresh_media_rows()
        return True

    # ---- what happens to files once they are watched ---------------------------

    def _trash_episode_files(self, files):
        """Moves the video and subtitles of one episode to the Trash, and the folders that
        leaves empty. True when none of them is left where it was."""
        root = load_media_settings()['path']
        paths = [p for p in [files.get('video')] + list(files.get('subs') or []) if isinstance(p, str)]
        moved = [move_to_trash(path, root) for path in paths]
        for path in paths:
            remove_empty_dirs(os.path.dirname(path), root)
        return all(moved)

    def _prune_watched_files(self, url):
        """With `behind` set, only that many of the most recently watched episodes of a
        source keep their files: the files of older watched ones go to the Trash. They stay
        watched, so they are not downloaded again. Movies are removed another way."""
        behind = load_media_settings()['behind']
        if behind is None or self._is_movie(url):
            return
        with self._media_data_lock:
            entry = self.media['sources'].get(url)
            if not entry:
                return
            with_files = [i for i in entry['watched'] if i in entry['files']]  # in the order they were watched
            doomed = {i: dict(entry['files'][i]) for i in (with_files[:-behind] if behind else with_files)}
        gone = [i for i, files in doomed.items() if self._trash_episode_files(files)]
        if gone:
            with self._media_data_lock:
                entry = self.media['sources'].get(url)
                if entry:
                    for episode_id in gone:
                        entry['files'].pop(episode_id, None)
                    save_media(self.media)
            GLib.idle_add(self._refresh_media_rows)

    def _trash_source_files(self, url):
        """Moves every file of a source to the Trash and forgets them. True when all went;
        a file that could not go leaves the others forgotten and the source as it is."""
        with self._media_data_lock:
            entry = self.media['sources'].get(url)
            everything = {i: dict(f) for i, f in entry['files'].items()} if entry else {}
        gone = [i for i, files in everything.items() if self._trash_episode_files(files)]
        with self._media_data_lock:
            entry = self.media['sources'].get(url)
            if entry:
                for episode_id in gone:
                    entry['files'].pop(episode_id, None)
                save_media(self.media)
        return len(gone) == len(everything)

    def _schedule_movie_removal(self, url):
        """A movie was watched through: it is to be removed, with its file, after the grace
        period (right away with none), so that a film that was slept through can be put back."""
        grace = load_media_settings()['grace']
        with self._media_data_lock:
            entry = self.media['sources'].get(url)
            if not entry:
                return
            entry['remove_at'] = time_module.time() + grace
            save_media(self.media)
        if grace <= 0:
            self.remove_due_movies()
        else:
            self._refresh_media_rows()

    def remove_due_movies(self):
        """Removes the movies whose grace period is over: the file to the Trash, the line out
        of [media], what is known of it forgotten. A movie that is not watched through any
        more, or whose file cannot go to the Trash, is left (and tried again in an hour)."""
        now = time_module.time()
        movies = self._movie_sources()
        with self._media_data_lock:
            due = [url for url in movies if (entry := self.media['sources'].get(url)) and entry.get('remove_at') is not None
                   and entry['remove_at'] <= now and entry.get('episodes') and unwatched_count(entry) == 0]
        done = []
        for url in due:
            if self._trash_source_files(url):
                done.append(url)
            else:
                with self._media_data_lock:
                    self.media['sources'][url]['remove_at'] = now + 3600
                    save_media(self.media)
        gone = self._drop_media_sources(done)
        if gone:
            GLib.idle_add(self._media_rows_removed, gone)
        return gone

    # ---- taking watched sources off the list ----------------------------------

    def _consumed_media_sources(self):
        """[(source, display name)] of the configured sources that have been read and
        have nothing unwatched left, in config order."""
        configured = [(url, name) for url, name, _order in load_media_sources()]
        with self._media_data_lock:
            sources = self.media['sources']
            return [(url, name or sources[url].get('title') or url) for url, name in configured
                    if sources.get(url, {}).get('episodes') and unwatched_count(sources[url]) == 0]

    def remove_consumed_media(self, urls):
        """Takes sources whose episodes are all watched off the list: their lines go out of
        [media] in config.conf and what is known of them is forgotten. The files of
        episodes stay on disk; a movie's file goes to the Trash with it. A source that has
        something unwatched left, or that is not configured any more, is left alone (decided
        now, not when a menu was drawn). If the config cannot be written, or a movie's file
        cannot go to the Trash, the source and what is known of it stay: nothing is half
        done. Returns the sources taken off."""
        consumed = {url for url, _name in self._consumed_media_sources()}
        movies = self._movie_sources()
        wanted = [url for url in urls if url in consumed and (url not in movies or self._trash_source_files(url))]
        gone = self._drop_media_sources(wanted)
        if gone:
            self._media_rows_removed(gone)
        return gone

    def _drop_media_sources(self, urls):
        """Takes the lines of sources out of [media] and forgets the sources (not the files).
        Only those really gone from the config are forgotten. Returns them."""
        if not urls:
            return []
        remove_media_sources(urls)
        still_configured = {u for u, _n, _o in load_media_sources()}
        gone = [url for url in urls if url not in still_configured]
        if not gone:
            return []
        with self._media_data_lock:
            for url in gone:
                self.media['sources'].pop(url, None)
            self._forget_watch_of(set(gone))
            save_media(self.media)
        with self._media_queue_lock:
            self._media_queue = [key for key in self._media_queue if key[0] not in gone]
        for url in gone:
            self.media_errors.pop(url, None)
        for key in [k for k in self.media_status if k[0] in gone]:
            del self.media_status[key]
        self._media_known_sources -= set(gone)  # adding the source again later reads it as new
        return gone

    def _media_rows_removed(self, gone):
        """Brings the list in line with sources that were taken off it. With unread items or
        updates showing, the list is rebuilt as usual. Without them a rebuild would
        replace the media with 'No unread items' (media never fill a popup that is
        showing), so the rows go one by one, the heading with the last of them."""
        if not self.popup:
            return
        with self.lock:
            others = bool(self.state.get('unread') or self.state.get('available_updates'))
        if others:
            self.refresh_list(keep_open=True)
            return
        for row in self.listbox.get_children():
            if getattr(row, 'media_source', None) in gone:
                self.listbox.remove(row)
        remaining = self.listbox.get_children()
        if self._media_header_row is not None and not any(hasattr(row, 'media_source') for row in remaining):
            if self._media_header_row in remaining:
                self.listbox.remove(self._media_header_row)
            self._media_header_row = None
        if not self.listbox.get_children():
            self.refresh_list(keep_open=True)  # nothing left at all: say so

    def _cancel_source_downloads(self, url):
        """Cancel any ongoing download for the given source and clean up partial files.
        This signals the download worker to stop and waits for it to finish."""
        import time
        # Find all episodes being downloaded for this source
        with self._media_queue_lock:
            to_cancel = {key for key in self._media_queue if key[0] == url}
            current = self._media_current
            if current and current[0] == url:
                to_cancel.add(current)
            self._media_cancel.update(to_cancel)
        # Remove pending downloads from queue
        with self._media_queue_lock:
            self._media_queue = [key for key in self._media_queue if key[0] != url]
        # Wait for current download to finish (it checks _media_cancel periodically)
        if current and current[0] == url:
            # Wait up to 5 seconds for the download to notice cancellation
            for _ in range(50):
                time.sleep(0.1)
                with self._media_queue_lock:
                    if self._media_current != current:
                        break
        # Clean up cancel set
        with self._media_queue_lock:
            for key in to_cancel:
                self._media_cancel.discard(key)

    def _media_menu_remove(self, _button, popover, urls):
        popover.popdown()
        # Cancel ongoing downloads for these sources
        for url in urls:
            self._cancel_source_downloads(url)
        self.remove_consumed_media(urls)

    def _media_menu_remove_dynamic(self, _button, popover, url):
        """Remove a dynamically added source (from discovery click): remove from list,
        mark discovery item as seen, delete downloaded files, stop ongoing download,
        and remove partial files."""
        popover.popdown()
        # Find the discovery item that corresponds to this URL
        # The URL format is "plugin_name:source_url"
        plugin_name, _, source_url = url.partition(':')
        # Mark the discovery item that has this URL dismissed
        self._dismiss_discovery([
            item for item in get_all_cached_items(load_media_cache())
            if item.get('urls', {}).get(plugin_name) == source_url][:1])
        # Cancel ongoing download if any
        self._cancel_source_downloads(url)
        # Trash the source files (completed downloads)
        self._trash_source_files(url)
        # Remove from media sources
        with self._media_data_lock:
            self.media['sources'].pop(url, None)
            self._forget_watch_of({url})
            save_media(self.media)
        # Remove any pending downloads for this source
        with self._media_queue_lock:
            self._media_queue = [key for key in self._media_queue if key[0] != url]
        # Remove status entries
        for key in [k for k in self.media_status if k[0] == url]:
            del self.media_status[key]
        self._media_rows_removed([url])

    def _media_menu_unwatch(self, _button, popover, url, episode_id):
        popover.popdown()
        self.mark_media_unwatched(url, episode_id)

    def _media_menu_content(self, url, popover):
        """What the right-click menu of a media row holds: removal of this source when
        everything in it is watched (the button says why when it is not; for a movie it
        takes the file to the Trash too), taking the last watched episode back as not
        watched (for a movie waiting to be removed: "I didn't finish it"), and, when more
        than one source is finished, removal of all of those at once.
        For dynamically added sources (from discovery clicks), also offers to remove
        from list, mark as seen in discovery, and delete files."""
        consumed = self._consumed_media_sources()
        movies = self._movie_sources()
        config_sources = {u for u, _n, _o in load_media_sources()}
        is_dynamic = url not in config_sources and not url.startswith('discovery:')
        with self._media_data_lock:
            entry = self.media['sources'].get(url)
            read = bool(entry and entry.get('episodes'))
            left = unwatched_count(entry) if read else 0
            title = self._media_display_name(url, entry or {})
            last = (entry or {}).get('last_watched') or {}
            can_unwatch = last.get('id') in (entry or {}).get('watched', [])
            pending = (entry or {}).get('remove_at')
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        for margin in ('start', 'end', 'top', 'bottom'):
            getattr(box, f'set_margin_{margin}')(4)
        heading = Gtk.Label()
        heading.set_markup(f'<b>{GLib.markup_escape_text(title)}</b>')
        heading.set_xalign(0)
        heading.set_ellipsize(Pango.EllipsizeMode.END)
        heading.set_max_width_chars(40)
        heading.get_style_context().add_class('menu-text')  # dark text: the menu sits on a white scroller
        box.pack_start(heading, False, False, 0)

        is_movie = url in movies
        one = Gtk.Button(label='Remove movie and its file' if is_movie else 'Remove from list')
        if any(u == url for u, _n in consumed):
            one.set_tooltip_text('Takes this movie out of [media] and moves its file to the Trash.' if is_movie else
                                 'Takes this source out of [media] in config.conf. Downloaded files stay on disk.')
            one.connect('clicked', self._media_menu_remove, popover, [url])
        else:
            one.set_sensitive(False)
            one.set_tooltip_text(f'{left} unwatched episode{"" if left == 1 else "s"} left' if read
                                 else 'This source has not been read yet')
        box.pack_start(one, False, False, 0)

        # For dynamically added sources (from discovery clicks), add option to remove,
        # mark as seen in discovery, and delete files
        if is_dynamic:
            dyn_btn = Gtk.Button(label='Remove from list, mark seen, delete files')
            dyn_btn.set_tooltip_text('Removes this source from the list, marks the discovery item as seen (so it won\'t reappear), stops any ongoing download, and moves all downloaded files to the Trash.')
            dyn_btn.connect('clicked', self._media_menu_remove_dynamic, popover, url)
            box.pack_start(dyn_btn, False, False, 0)

        if can_unwatch:
            undo = Gtk.Button(label="I didn't finish it" if pending is not None else 'Mark as not watched')
            shown = last.get('title') or last['id']
            undo.set_tooltip_text(f'Puts "{shown}" back as not watched' + ('; the movie is not removed.' if pending is not None else '.'))
            undo.connect('clicked', self._media_menu_unwatch, popover, url, last['id'])
            box.pack_start(undo, False, False, 0)

        if len(consumed) > 1:
            names = [name for _u, name in consumed]
            listed = ', '.join(names[:8]) + (f' and {len(names) - 8} more' if len(names) > 8 else '')
            kept = "Downloaded files stay on disk" + ("; a movie's file goes to the Trash." if any(u in movies for u, _n in consumed) else '.')
            every = Gtk.Button(label=f'Remove all {len(consumed)} fully watched')
            every.set_tooltip_text(f'Takes these out of [media]: {listed}. {kept}')
            every.connect('clicked', self._media_menu_remove, popover, [u for u, _n in consumed])
            box.pack_start(every, False, False, 0)
        return box

    def _show_media_menu(self, row, event):
        """Popover on a media row (right-click), placed the way the feed menu is."""
        popover = Gtk.Popover.new(row)
        allocation = row.get_allocation()
        rect = Gdk.Rectangle()
        rect.x, rect.y, rect.width, rect.height = max(int(event.x) - allocation.x, 0), 0, 1, allocation.height
        popover.set_pointing_to(rect)
        position, max_height = self._feed_menu_room(row)
        popover.set_position(position)
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_propagate_natural_height(True)
        scroller.set_max_content_height(max_height)
        scroller.add(self._media_menu_content(row.media_source, popover))
        popover.add(scroller)
        popover.connect('closed', self.on_launcher_closed)
        self._launcher_open = True  # the guard the Launch list and the feed menu use: the popup stays under it
        scroller.show_all()
        popover.popup()

    # ---- the popup's rows ----------------------------------------------------

    def _is_discovery_url(self, url):
        """Check if a URL is a plugin discovery item."""
        return url.startswith('discovery:')

    def media_source_urls(self):
        """The configured sources that have been read at least once, or that could not
        be, in config order. Fully watched series (unwatched_count == 0) with no active
        downloads are hidden; they reappear when a new episode appears or download starts.
        Also includes dynamically added sources (from discovery clicks)."""
        with self._media_data_lock:
            sources = self.media['sources']
            urls = []
            config_sources = {u for u, _n, _o in load_media_sources()}

            # Config sources in config order
            for url, _name, _order in load_media_sources():
                # Sources with errors are always shown (so user can retry)
                if url in self.media_errors:
                    urls.append(url)
                    continue
                entry = sources.get(url)
                if not entry:
                    continue
                if not entry.get('episodes'):
                    continue
                # Show if there are unwatched episodes, or if there's an active download
                if unwatched_count(entry) > 0:
                    urls.append(url)
                else:
                    # Check if there's an active download for this source
                    has_active_download = any(
                        k[0] == url and v.get('state') in ('queued', 'downloading')
                        for k, v in self.media_status.items()
                    )
                    if has_active_download:
                        urls.append(url)
                    # else: fully watched with no active downloads - hide it

            # Dynamically added sources (from discovery clicks) - show at top if they have episodes
            # These are sources in media['sources'] but not in config
            dynamic_sources = []
            for url in sources:
                if url in config_sources:
                    continue
                if url.startswith('discovery:'):
                    continue  # discovery items handled separately
                entry = sources.get(url)
                if not entry or not entry.get('episodes'):
                    continue
                if unwatched_count(entry) > 0:
                    dynamic_sources.append(url)
                else:
                    has_active_download = any(
                        k[0] == url and v.get('state') in ('queued', 'downloading')
                        for k, v in self.media_status.items()
                    )
                    if has_active_download:
                        dynamic_sources.append(url)
            # Added ones go before the configured ones, the newest first, and those with something that
            # can be watched now before those still being downloaded
            dynamic_sources.reverse()
            dynamic_sources.sort(key=lambda url: not self._has_something_to_watch(sources[url]))
            urls = dynamic_sources + urls
            return urls

    def _has_something_to_watch(self, entry):
        """True when an episode that was not watched is downloaded."""
        return any(self._media_file_ready(entry, e['id']) for e in entry['episodes'] if e['id'] not in entry['watched'])

    def _watching_items(self):
        """The titles on the watch list that no site has been found to have yet, the newest first, in
        the shape of discovery items (so they are rows of the same kind, marked `watching`)."""
        with self._media_data_lock:
            watching = sorted(((key, dict(w)) for key, w in self.media.get('watch', {}).items() if is_searching(w)),
                              key=lambda kw: kw[1]['added'], reverse=True)
        return [{'id': key, '_cache_key': key, '_plugin': 'unknown', 'title': w['title'], 'year': w['year'],
                 'type': w['type'], 'imdb_id': w['imdb_id'], 'tmdb_id': None, 'urls': {}, 'genre': [],
                 'quality': None, 'rank': None, 'watching': True} for key, w in watching]

    def discovery_source_urls(self):
        """Return only discovery item URLs (unseen items from unified cache).
        These are the items shown in the discovery section of the media list: the titles being
        looked for first, then what is listed."""
        cache = load_media_cache()
        seen = set(self.state.get('media_discovery_seen', []))
        urls = [f'discovery:{item["_cache_key"]}' for item in self._watching_items()]
        for item in get_all_cached_items(cache):
            if not is_seen(seen, item):
                urls.append(f'discovery:{item["_cache_key"]}')
        return urls

    def get_discovery_items(self):
        """Get current discovery items from unified cache, filtered by dismissal state, after the
        titles being looked for."""
        cache = load_media_cache()
        seen = set(self.state.get('media_discovery_seen', []))
        items = self._watching_items()
        for item in get_all_cached_items(cache):
            if not is_seen(seen, item):
                # Add _plugin for backward compatibility (use first URL's plugin)
                urls = item.get('urls', {})
                item['_plugin'] = list(urls.keys())[0] if urls else 'unknown'
                items.append(item)
        return items

    def build_media_row(self, url):
        # Check if this is a discovery item
        if self._is_discovery_url(url):
            return self._build_discovery_media_row(url)

        row = Gtk.ListBoxRow()
        row.set_selectable(False)
        row.set_activatable(True)
        row.media_source = url

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        box.set_margin_start(3)
        box.set_margin_end(3)
        row.media_marker = Gtk.Label()
        box.pack_start(row.media_marker, False, False, 0)
        row.media_label = Gtk.Label()
        row.media_label.set_xalign(0)
        row.media_label.set_ellipsize(Pango.EllipsizeMode.END)  # a long title shrinks, the stats stay visible
        box.pack_start(row.media_label, False, False, 0)
        row.media_stats = Gtk.Label()
        box.pack_start(row.media_stats, False, False, 0)
        filler = Gtk.Box()
        filler.set_hexpand(True)
        box.pack_start(filler, True, True, 0)
        row.add(box)

        # Enable enter/leave events on the box (ListBoxRow is no-window, box receives events)
        box.set_events(box.get_events() | Gdk.EventMask.ENTER_NOTIFY_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK)
        box.connect('enter-notify-event', self._on_media_row_enter)  # once: a row is updated at every download tick
        box.connect('leave-notify-event', self._on_media_row_leave)

        self._update_media_row(row, {u: (n, o) for u, n, o in load_media_sources()})
        return row

    def _build_discovery_media_row(self, url):
        """Build a row for a plugin discovery item in the Media list."""
        # Parse the virtual URL: discovery:<cache_key>
        prefix, _, cache_key = url.partition(':')
        # Find the item by fetching current discovery items
        items = self.get_discovery_items()
        item = next((i for i in items if i.get('_cache_key') == cache_key), None)
        if not item:
            return None

        row = Gtk.ListBoxRow()
        row.set_selectable(False)
        row.set_activatable(True)
        row.media_source = url  # virtual URL for identification
        row.discovery_item = item  # for click/dismiss handlers

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        box.set_margin_start(6)
        box.set_margin_end(6)
        box.set_margin_top(3)
        box.set_margin_bottom(3)

        badge_text = '🎬' if item.get('type') == 'movie' else '📺'
        badge = Gtk.Label(label=badge_text)
        badge.set_margin_end(6)
        box.pack_start(badge, False, False, 0)

        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        text_box.set_hexpand(True)
        title_label = Gtk.Label()
        title_label.set_markup(f'<b>{GLib.markup_escape_text(item["title"])}</b>')
        title_label.set_xalign(0)
        title_label.set_ellipsize(Pango.EllipsizeMode.END)
        title_label.set_hexpand(True)
        text_box.pack_start(title_label, False, False, 0)

        # Show genre for both movies and series - use API genre from TMDb/OMDB cache
        # Pass first URL for year extraction if title doesn't have year
        first_url = next(iter(item.get('urls', {}).values()), None)
        meta = get_cached_metadata(
            title_with_year(item),
            media_type=item.get('type', 'movie'),
            url=first_url,
            imdb_id=item.get('imdb_id'),
            tmdb_id=item.get('tmdb_id')
        )
        api_genre = meta.get('genre') if meta else None
        # Fall back to site genre if API genre not available
        site_genre = ', '.join(item['genre']) if item.get('genre') else None
        rating = meta.get('imdb_rating') if meta else None
        genre = ' '.join(part for part in (f'⭐ {rating}' if rating else '', f'🎭 {api_genre or site_genre}' if (api_genre or site_genre) else '') if part)

        # Show genre and source on the same row
        genre_source_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        genre_source_box.set_hexpand(True)
        genre_source_box.set_halign(Gtk.Align.FILL)
        if genre:
            genre_label = Gtk.Label(label=genre)
            genre_label.set_xalign(0)
            genre_label.get_style_context().add_class('menu-text')
            genre_label.set_ellipsize(Pango.EllipsizeMode.END)
            genre_label.set_max_width_chars(60)
            genre_source_box.pack_start(genre_label, False, False, 0)

        # Show source badges (which sites have this movie/series) on the same row as genre, at the end
        urls = item.get('urls', {})
        if urls:
            # Create a filler to push sources to the right
            filler = Gtk.Box()
            filler.set_hexpand(True)
            genre_source_box.pack_start(filler, True, True, 0)

            source_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
            for source_name in urls.keys():
                # Convert plugin name to real site address (e.g., fsonline_one -> fsonline.one)
                display_name = source_name.replace('_', '.')
                src_label = Gtk.Label(label=display_name)
                src_label.set_margin_end(4)
                src_label.get_style_context().add_class('menu-text')
                src_label.set_markup(f'<span size="small"><b>{GLib.markup_escape_text(display_name)}</b></span>')
                source_box.pack_start(src_label, False, False, 0)
            genre_source_box.pack_start(source_box, False, False, 0)

        if genre or urls:
            text_box.pack_start(genre_source_box, True, True, 0)  # expand to fill width

        box.pack_start(text_box, True, True, 0)

        if item.get('watching'):
            looking = Gtk.Label()
            looking.set_markup('<span size="small"><i>looking for it…</i></span>')
            looking.set_margin_start(6)
            looking.set_margin_end(6)
            looking.get_style_context().add_class('menu-text')
            box.pack_start(looking, False, False, 0)

        # Show quality badge for movies (from fsonline plugin)
        if item.get('type') == 'movie' and item.get('quality'):
            quality = item['quality'].upper()
            quality_label = Gtk.Label(label=f'  {quality}  ')
            quality_label.set_margin_start(6)
            quality_label.set_margin_end(6)
            if quality == 'HD':
                quality_label.get_style_context().add_class('quality-hd')
            else:
                quality_label.get_style_context().add_class('quality-low')
            box.pack_start(quality_label, False, False, 0)

        # Add custom metadata tooltip with poster (TMDb/OMDB) - using Popover on left of popup
        # Store item on box for listbox motion tracking
        box.popover_data = {
            'type': 'discovery',
            'title': title_with_year(item),
            'media_type': item.get('type', 'movie'),
            'urls': item.get('urls', {}),
            'imdb_id': item.get('imdb_id'),
            'tmdb_id': item.get('tmdb_id'),
        }

        row.add(box)
        return row

    def _update_media_row(self, row, configured):
        url = row.media_source
        # Handle discovery items
        if self._is_discovery_url(url):
            # These are static - no need to update
            return

        with self._media_data_lock:
            entry = self.media['sources'].get(url)
            error = self.media_errors.get(url)
            if not entry and not error:
                return
            entry = entry or new_media_entry()  # a source that has never been read, only failed
            name, order = configured.get(url, (None, None))
            order = self._effective_order(url, order)
            nxt = upcoming(entry['episodes'], entry['watched'], order, 1)
            ready = bool(nxt) and self._media_file_ready(entry, nxt[0]['id'])
            status = self.media_status.get((url, nxt[0]['id'])) if nxt else None
            is_playing = is_media_playing(url)
            name, text, stats, tooltip, color = media_row_view(
                name or entry.get('title') or url, entry, order, ready, status, error, url=url, is_playing=is_playing)
        escape = GLib.markup_escape_text
        row.media_marker.set_markup(f'<span foreground="{MEDIA_MARKER_COLORS[color]}">\u25cf</span>')
        row.media_label.set_markup(f'<span foreground="#000000"><b>{escape(name)}</b> - {escape(text)}</span>')
        row.media_stats.set_markup(f'<span foreground="#000000">- {escape(stats)}</span>' if stats else '')
        # Fallback tooltip text for testing and accessibility
        tooltip_text = tooltip or None
        row.set_tooltip_markup(tooltip_text)

        # Set up custom metadata popover on left of popup (overrides fallback when triggered)
        # Store data on box for handler access
        box = row.get_child()
        if box:
            box.popover_data = {
                'entry': entry,
                'url': url,
                'name': name,
                'tooltip_text': tooltip_text,
            }

    def _show_metadata_popover(self, row, content_widget):
        """Show a metadata popover on the left side of the main popup (towards screen center).
        Uses a separate window positioned relative to the main popup."""
        _log(f'DEBUG: _show_metadata_popover called, popup visible: {self.popup.get_visible() if self.popup else "no popup"}')
        if not self.popup or not self.popup.get_visible():
            return
        # Don't recreate if already showing for this row
        if hasattr(self, '_metadata_popover_row') and self._metadata_popover_row == row:
            return
        # Remove any existing popover
        self._hide_metadata_popover()

        # Create a separate popup window for the metadata (not a Gtk.Popover, which is constrained to parent window)
        meta_window = Gtk.Window(type=Gtk.WindowType.POPUP)
        meta_window.set_decorated(False)
        meta_window.set_skip_taskbar_hint(True)
        meta_window.set_skip_pager_hint(True)
        meta_window.set_type_hint(Gdk.WindowTypeHint.TOOLTIP)
        meta_window.set_keep_above(True)
        meta_window.add(content_widget)
        content_widget.show_all()

        # Position to the LEFT of the main popup (towards screen center)
        # Get main popup position and size
        main_x, main_y = self.popup.get_position()
        main_w, _main_h = self.popup.get_size()

        # Get row position relative to the main popup
        # The row is inside listbox -> scrolled_window -> content_overlay -> outer -> popup
        # We need to translate coordinates from row to popup
        alloc = row.get_allocation()
        _log(f'DEBUG: row allocation: x={alloc.x}, y={alloc.y}, w={alloc.width}, h={alloc.height}')

        # Convert row allocation to coordinates relative to the main popup window
        # Get the row's position relative to the popup window
        row_x, row_y = row.translate_coordinates(self.popup, alloc.x, alloc.y)
        _log(f'DEBUG: row position in popup: x={row_x}, y={row_y}')

        # Metadata window width = main popup width (same width)
        meta_window_width = main_w
        meta_window_height = 400  # Fixed height for metadata

        # Calculate metadata window position: left of main popup, aligned top with main popup
        meta_x = main_x - meta_window_width - 12  # 12px gap from main popup
        meta_y = main_y  # Align top with main popup

        # Ensure on screen
        display = Gdk.Display.get_default()
        monitor = display.get_primary_monitor() or display.get_monitor(0)
        geo = monitor.get_geometry()
        if meta_x < geo.x:
            meta_x = geo.x
        if meta_y < geo.y:
            meta_y = geo.y
        if meta_y + meta_window_height > geo.y + geo.height:
            meta_y = geo.y + geo.height - meta_window_height

        meta_window.move(meta_x, meta_y)
        meta_window.resize(meta_window_width, meta_window_height)
        meta_window.show_all()

        _log(f'DEBUG: meta window shown at ({meta_x}, {meta_y}), main popup at ({main_x}, {main_y})')

        # Store reference
        self._metadata_popover = meta_window
        self._metadata_popover_row = row

    def _hide_metadata_popover(self):
        """Hide the metadata popover if visible."""
        if hasattr(self, '_metadata_popover') and self._metadata_popover:
            self._metadata_popover.destroy()
            self._metadata_popover = None
            self._metadata_popover_row = None

    def _on_media_row_enter(self, widget, event):
        """Handle enter event for media rows (called from listbox motion).
        Handles both discovery and regular media rows."""
        data = getattr(widget, 'popover_data', None)
        if not data:
            return False

        if data.get('type') == 'discovery':
            title = data['title']
            media_type = data.get('media_type', 'movie')
            urls = data.get('urls', {})
            imdb_id = data.get('imdb_id')
            tmdb_id = data.get('tmdb_id')
            _log(f'DEBUG: on_enter discovery for {title}')
            meta = get_cached_metadata(
                title,
                media_type=media_type,
                url=list(urls.values())[0] if urls else None,
                imdb_id=imdb_id,
                tmdb_id=tmdb_id,
            )
        else:
            # Regular media row
            entry = data['entry']
            url = data['url']
            name = data['name']
            tooltip_text = data['tooltip_text']
            title = entry.get('title') or name
            _log(f'DEBUG: on_enter regular for {title}')
            # Get IMDb/TMDb IDs from next episode
            imdb_id = None
            tmdb_id = None
            if entry.get('episodes'):
                nxt_ep = upcoming(entry['episodes'], entry.get('watched', []), self._effective_order(url, None), 1)
                if nxt_ep:
                    imdb_id = nxt_ep[0].get('imdb_id')
                    tmdb_id = nxt_ep[0].get('tmdb_id')
            meta = get_cached_metadata(title, url=url, imdb_id=imdb_id, tmdb_id=tmdb_id)
            tooltip_text = data.get('tooltip_text')

        _log(f'DEBUG: meta found: {meta is not None}')
        if meta:
            custom_widget = create_metadata_tooltip(meta)
            _log(f'DEBUG: tooltip_widget: {custom_widget is not None}')
            if custom_widget:
                self._show_metadata_popover(widget.get_parent(), custom_widget)
                return True

        # Fallback to text tooltip for regular rows
        if not data.get('type') == 'discovery' and tooltip_text:
            label = Gtk.Label()
            label.set_markup(tooltip_text)
            label.set_line_wrap(True)
            label.set_max_width_chars(50)
            label.set_margin_start(8)
            label.set_margin_end(8)
            label.set_margin_top(6)
            label.set_margin_bottom(6)
            label.set_selectable(True)
            self._show_metadata_popover(widget.get_parent(), label)
            return True
        return False

    def _on_media_row_leave(self, widget, event):
        # Mouse left the row - hide popover
        GLib.timeout_add(100, self._hide_metadata_popover)
        return False

    def _on_listbox_motion(self, listbox, event):
        """Track mouse motion over listbox to show metadata popover for hovered row."""
        # Get row at current Y position
        row = listbox.get_row_at_y(int(event.y))
        if row and hasattr(row, 'media_source'):
            box = row.get_child()
            if box and hasattr(box, 'popover_data') and box.popover_data:
                # Check if this is a different row than currently hovered
                if self._hovered_row != row:
                    self._hovered_row = row
                    # Trigger enter handler
                    self._on_media_row_enter(box, None)
        elif self._hovered_row:
            # Mouse left all media rows
            self._hovered_row = None
            GLib.timeout_add(100, self._hide_metadata_popover)
        return False

    def _on_listbox_leave(self, listbox, event):
        """Mouse left the listbox entirely."""
        self._hovered_row = None
        GLib.timeout_add(100, self._hide_metadata_popover)
        return False

    def _setup_listbox_hover_events(self):
        """Connect motion and leave events to listbox for metadata popover tracking."""
        if self.listbox:
            self.listbox.connect('motion-notify-event', self._on_listbox_motion)
            self.listbox.connect('leave-notify-event', self._on_listbox_leave)
            # Enable motion and leave events
            self.listbox.set_events(self.listbox.get_events() | Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK)
            self._hovered_row = None

    def _refresh_media_rows(self):
        """Updates the rows in place: rebuilding the list would collapse a popup
        that has only media to show."""
        if self.popup:
            configured = {u: (n, o) for u, n, o in load_media_sources()}
            for row in self.listbox.get_children():
                if hasattr(row, 'media_source'):
                    self._update_media_row(row, configured)
        return False
