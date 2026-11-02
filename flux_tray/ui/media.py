"""Podcasts, series and movies: checking sources, keeping the next episodes
downloaded, playing them in mpv and remembering what was watched."""

import os
import threading
import time as time_module

from ..gi_env import GLib, Gdk, Gio, Gtk, Pango
from ..config import load_media_movies, load_media_settings, load_media_sources, remove_media_sources
from ..constants import CONFIG_FILE
from ..desktop import move_to_trash, primary_monitor_size
from ..fileutil import remove_empty_dirs
from ..hls import is_hls
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
from ..playback import counts_as_watched, play_media_file, resume_point
from ..screen import media_target_size, remember_screen_size
from ..state import new_media_entry, save_media


MEDIA_CONFIG_DEBOUNCE_MS = 800  # an editor or the browser extension may write the file in several steps
PLAY_PARTIAL_MIN_BYTES = 1_500_000  # enough of a download for mpv to start on (about a minute of video)
MEDIA_MARKER_COLORS = {'ready': '#2e8b57', 'busy': '#d08000', 'failed': '#c0392b', 'idle': '#808080'}


def duration_text(seconds):
    """A time ahead for a row, in the largest sensible unit: '2 days', '23 h', '45 min'."""
    minutes = max(1, int(seconds // 60))
    if minutes >= 48 * 60:
        return f'{minutes // (24 * 60)} days'
    if minutes >= 60:
        return f'{(minutes + 30) // 60} h'
    return f'{minutes} min'


def media_row_view(name, entry, order, downloaded, status, error=None, now=None):
    """What a source's row shows: (name, next episode text, stats text, tooltip,
    marker colour key). `downloaded` is whether the next episode is on disk and
    `status` its entry in the downloads' progress ('queued', 'downloading' with a
    percent, or 'failed' with an error), None when nothing is going on. `error` is
    why the source's last check failed, if it did. A watched movie that is due to be
    removed says when."""
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
    label = episode_label(episode)
    text = ' '.join(p for p in (label, clean_title(episode.get('title'), (name, entry.get('title')))) if p)
    state = (status or {}).get('state')
    if state == 'downloading':
        stats, color, hint = f"{status.get('percent', 0)}%", 'busy', ('Click to watch while it downloads' if status.get('part') else 'Downloading')
    elif state == 'queued':
        stats, color, hint = 'queued', 'busy', 'Waiting to download'
    elif state == 'failed':
        stats, color, hint = 'failed', 'failed', f"Download failed: {status.get('error') or 'unknown error'} (retried at the next check; click to retry now)"
    elif downloaded:
        stats, color, hint = 'ready', 'ready', 'Click to play'
    else:
        stats, color, hint = 'not downloaded', 'idle', 'Click to download'
    if news:
        stats = f'{stats} - {news} new' if stats else f'{news} new'
    tooltip = '\n'.join(p for p in (text, hint, f'{unwatched_count(entry)} unwatched', last_line, error_line) if p)
    return name, text, stats, tooltip, color


def describe_media_error(error):
    """A source's failure as one line for its row: a driver's own message as it is
    (a ValueError, or no driver), anything else with the kind of error."""
    message = str(error).strip()
    if isinstance(error, (NoDriver, ValueError)) and message:
        return message[:300]
    return f'{error.__class__.__name__}: {message}'[:300].rstrip(': ')


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
        """Reads every configured source (or those in `only`), remembers what is
        new, then queues the downloads. A source that cannot be read keeps what is
        known of it."""
        new_total = 0
        self.media_registry.refresh()  # picks up plugins that were added or edited
        for url, _name, configured in load_media_sources():
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
        """Queues the next `ahead` unwatched episodes of every source that are not on disk."""
        ahead = load_media_settings()['ahead']
        wanted = []
        if ahead > 0:
            with self._media_data_lock:
                for url, _name, order in load_media_sources():
                    entry = self.media['sources'].get(url)
                    if entry:
                        for episode in upcoming(entry['episodes'], entry['watched'], self._effective_order(url, order), ahead):
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
                saved = normalize_saved(driver.download(episode, base, progress, lambda: False))
            else:
                files = normalize_files(driver.resolve(episode) if driver.resolve else resolve_files(episode))
                paths = episode_paths(root, name, episode, files, taken, names=names)
                if is_hls(files['video']['url']) and paths['video'].lower().endswith(('.ts', '.mkv')):
                    watchable['part'] = paths['video'] + '.part'
                    self.media_status[key] = {'state': 'downloading', 'percent': max(shown[0], 0), **watchable}
                saved = download_episode(paths, files, progress=progress, screen=media_target_size())
        except Exception as error:  # the partial file stays, so the next try carries on
            self.media_status[key] = {'state': 'failed', 'error': describe_media_error(error)}
            GLib.idle_add(self._refresh_media_rows)
            return
        with self._media_data_lock:
            entry['files'][episode_id] = saved
            save_media(self.media)
        self.media_status.pop(key, None)
        GLib.idle_add(self._refresh_media_rows)

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
        """Plays a source's next unwatched episode, or starts downloading it first."""
        order = self._media_source_order(url)
        with self._media_data_lock:
            entry = self.media['sources'].get(url)
            nxt = upcoming(entry['episodes'], entry['watched'], order, 1) if entry else []
            if not nxt:
                retry = not (entry and entry['episodes']) and url in self.media_errors
                if retry:
                    self.start_media_check()  # an unreadable source: try it again now
                return
            episode = nxt[0]
            start = (entry.get('resume') or {}).get(episode['id'])  # where it stopped last time
            ready = self._media_file_ready(entry, episode['id'])
            path = entry['files'][episode['id']]['video'] if ready else None
            name = self._media_display_name(url, entry)
        length = None  # the playlist's length, when playing a download that is not finished
        if not ready:
            status = self.media_status.get((url, episode['id']), {})
            part = status.get('part')
            if status.get('state') == 'downloading' and part and self._file_size(part) >= PLAY_PARTIAL_MIN_BYTES:
                path, length = part, status.get('length')  # watch it while it downloads
            else:
                if status.get('state') not in ('queued', 'downloading'):
                    self._enqueue_media([(url, episode['id'])], front=True)
                return
        if self.popup:
            self.popup.hide()
        shown = clean_title(episode.get('title'), (name, entry.get('title')))
        title = f"{name} \u00b7 {' '.join(p for p in (episode_label(episode), shown) if p)}"
        episode_id = episode['id']
        # A partial file's own length is only an estimate, so how far it got is measured against the
        # playlist's; without that, playing it is not tracked at all.
        track = ready or bool(length)
        stopped = {}  # where it stopped and how much of it was played, filled in when playback ends
        play_media_file(path, title, total_seconds=length, start=start, on_stopped=stopped.update,
                        sleep_seconds=load_media_settings()['sleep'],
                        on_finished=(lambda percent, remaining:
                                     GLib.idle_add(self._on_media_played, url, episode_id, percent, remaining,
                                                   dict(stopped), start)) if track else None)

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
            if url in load_media_movies():
                self._schedule_movie_removal(url)
        elif info.get('position') is not None:  # nothing seen means nothing to change
            self._set_media_resume(url, episode_id, resume_point(info['position'], watched=False))
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
        if behind is None or url in load_media_movies():
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
        movies = load_media_movies()
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
        movies = load_media_movies()
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

    def _media_menu_remove(self, _button, popover, urls):
        popover.popdown()
        self.remove_consumed_media(urls)

    def _media_menu_unwatch(self, _button, popover, url, episode_id):
        popover.popdown()
        self.mark_media_unwatched(url, episode_id)

    def _media_menu_content(self, url, popover):
        """What the right-click menu of a media row holds: removal of this source when
        everything in it is watched (the button says why when it is not; for a movie it
        takes the file to the Trash too), taking the last watched episode back as not
        watched (for a movie waiting to be removed: "I didn't finish it"), and, when more
        than one source is finished, removal of all of those at once."""
        consumed = self._consumed_media_sources()
        movies = load_media_movies()
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

    def media_source_urls(self):
        """The configured sources that have been read at least once, or that could not
        be, in config order."""
        with self._media_data_lock:
            return [url for url, _n, _o in load_media_sources()
                    if self.media['sources'].get(url, {}).get('episodes') or url in self.media_errors]

    def build_media_row(self, url):
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
        self._update_media_row(row, {u: (n, o) for u, n, o in load_media_sources()})
        return row

    def _update_media_row(self, row, configured):
        url = row.media_source
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
            name, text, stats, tooltip, color = media_row_view(
                name or entry.get('title') or url, entry, order, ready, status, error)
        escape = GLib.markup_escape_text
        row.media_marker.set_markup(f'<span foreground="{MEDIA_MARKER_COLORS[color]}">\u25cf</span>')
        row.media_label.set_markup(f'<span foreground="#000000"><b>{escape(name)}</b> - {escape(text)}</span>')
        row.media_stats.set_markup(f'<span foreground="#000000">- {escape(stats)}</span>' if stats else '')
        row.set_tooltip_text(tooltip or None)

    def _refresh_media_rows(self):
        """Updates the rows in place: rebuilding the list would collapse a popup
        that has only media to show."""
        if self.popup:
            configured = {u: (n, o) for u, n, o in load_media_sources()}
            for row in self.listbox.get_children():
                if hasattr(row, 'media_source'):
                    self._update_media_row(row, configured)
        return False
