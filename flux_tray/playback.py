"""One persistent mpv fed by streamlink for live streams."""

import atexit
import json
import os
import re
import shutil
import socket
import subprocess
import threading
import time as time_module
import webbrowser

from .constants import YOUTUBE_CHECK_TIMEOUT_SECONDS
from .state import STATE_FILE
from .desktop import x_idle_seconds
from .log import _log
from .config import (load_twitch_channels, load_youtube_channels, load_twitch_qualities,
                     load_youtube_qualities, load_twitch_names, load_youtube_names,
                     load_twitch_schedules, load_youtube_schedules,
                     load_twitch_default_quality, load_youtube_default_quality)
from .windows import channels_due
from datetime import datetime


def _strip_emojis(text):
    """Removes emoji characters from text, leaving other characters intact."""
    if not text:
        return text
    # Emoji Unicode ranges (inclusive start, inclusive end)
    emoji_ranges = [
        (0x1F600, 0x1F64F),   # emoticons
        (0x1F300, 0x1F5FF),   # symbols & pictographs
        (0x1F680, 0x1F6FF),   # transport & map symbols
        (0x1F1E0, 0x1F1FF),   # flags (iOS)
        (0x2702, 0x27B0),     # dingbats
        (0x24C2, 0xD7FF),     # enclosed characters (BMP part)
        (0xE000, 0x1F251),    # enclosed characters (supplementary part, skipping surrogates)
        (0x1F900, 0x1F9FF),   # supplemental symbols and pictographs
        (0x1FA70, 0x1FAFF),   # symbols and pictographs extended-A
        (0x1F780, 0x1F7FF),   # geometric shapes extended (includes 🟢🟡🟠🟣🟤)
        (0x2B00, 0x2BFF),     # miscellaneous symbols and arrows (includes ⬆⬇⬅➡)
        (0x1F000, 0x1F02F),   # mahjong tiles
        (0x1F030, 0x1F09F),   # domino tiles
        (0x1F0A0, 0x1F0FF),   # playing cards
    ]
    def is_emoji(ch):
        cp = ord(ch)
        return any(start <= cp <= end for start, end in emoji_ranges)
    return ''.join(ch for ch in text if not is_emoji(ch)).strip()


# --- Live-stream playback -------------------------------------------------
# One persistent mpv window is shared by every live channel. mpv is started
# idle + maximized with an IPC socket; each click starts `streamlink
# --player-external-http` (serves the stream on a local port, no player of its
# own) and tells the running mpv to `loadfile` that URL, so a new channel
# replaces whatever is playing in the *same* window instead of opening another.
MPV_IPC_SOCKET = os.path.join(
    os.environ.get('XDG_RUNTIME_DIR') or '/tmp', f'flux-tray-mpv-{os.getuid()}.sock')

# Live channel cycling: ordered list of all configured channels (twitch + youtube)
# and key bindings for next/previous in mpv
_live_channels_list = []  # [(site, channel, quality, display_name)]
_live_channels_lock = threading.RLock()
_current_live_index = -1  # index into _live_channels_list of currently playing channel


STREAMLINK_READY_TIMEOUT_SECONDS = 30


MPV_START_TIMEOUT_SECONDS = 10


_player_lock = threading.Lock()  # guards _streamlink_proc


_mpv_lock = threading.Lock()     # serialises "is mpv up? if not, start it"


_streamlink_proc = None


_mpv_proc = None


_playing = None  # (streamlink_proc, site, channel) of the stream mpv is showing

# For local media (series/movies): (source_url, episode_id) currently playing
_media_playing = None
_media_playing_lock = threading.Lock()


def set_media_playing(source_url, episode_id):
    """Call when starting playback of a media episode."""
    global _media_playing
    with _media_playing_lock:
        _media_playing = (source_url, episode_id)


def get_media_playing():
    """Returns (source_url, episode_id) of currently playing media, or None."""
    with _media_playing_lock:
        return _media_playing


def clear_media_playing():
    """Call when media playback ends or is replaced."""
    global _media_playing
    with _media_playing_lock:
        _media_playing = None


def is_media_playing(source_url):
    """True if mpv is currently playing an episode from this media source."""
    with _media_playing_lock:
        return _media_playing is not None and _media_playing[0] == source_url


def is_stream_playing(site, channel):
    """True while `channel` on `site` ('Twitch'/'YouTube') is what the shared
    mpv is playing (its streamlink is still running)."""
    with _player_lock:
        playing = _playing
    return bool(playing and playing[1:] == (site, channel) and playing[0].poll() is None)


def _get_live_channels_list():
    """Build the ordered list of all configured live channels (Twitch + YouTube).
    Returns [(site, channel, quality, display_name)]."""
    channels = []

    # Get Twitch channels
    twitch_channels = load_twitch_channels()
    twitch_qualities = load_twitch_qualities()
    twitch_names = load_twitch_names()
    twitch_schedules = load_twitch_schedules()
    twitch_default_quality = load_twitch_default_quality()

    # Only include channels that are "due" (not restricted by schedule)
    due_twitch = channels_due(twitch_channels, twitch_schedules, set(), datetime.now())
    for ch in due_twitch:
        quality = twitch_qualities.get(ch, twitch_default_quality)
        name = twitch_names.get(ch)
        channels.append(('Twitch', ch, quality, name))

    # Get YouTube channels
    youtube_channels = load_youtube_channels()
    youtube_qualities = load_youtube_qualities()
    youtube_names = load_youtube_names()
    youtube_schedules = load_youtube_schedules()
    youtube_default_quality = load_youtube_default_quality()

    due_youtube = channels_due(youtube_channels, youtube_schedules, set(), datetime.now())
    for ch in due_youtube:
        quality = youtube_qualities.get(ch, youtube_default_quality)
        name = youtube_names.get(ch)
        channels.append(('YouTube', ch, quality, name))

    return channels


def _get_currently_live_channels():
    """Get list of currently live channels from state file.
    Returns [(site, channel, quality, display_name)] for channels that are currently live."""
    import json
    channels = []

    try:
        with open(STATE_FILE, 'r') as f:
            state = json.load(f)
    except Exception:
        return channels

    # Get Twitch live channels
    for entry in state.get('live_channels', []):
        ch = entry.get('channel')
        if ch:
            # Get quality and name from config
            qualities = load_twitch_qualities()
            names = load_twitch_names()
            default_q = load_twitch_default_quality()
            quality = qualities.get(ch, default_q)
            name = names.get(ch)
            channels.append(('Twitch', ch, quality, name))

    # Get YouTube live channels
    for entry in state.get('live_youtube_channels', []):
        ch = entry.get('channel')
        if ch:
            qualities = load_youtube_qualities()
            names = load_youtube_names()
            default_q = load_youtube_default_quality()
            quality = qualities.get(ch, default_q)
            name = names.get(ch)
            channels.append(('YouTube', ch, quality, name))

    return channels


def _update_live_channels_list():
    """Refresh the global live channels list."""
    global _live_channels_list
    with _live_channels_lock:
        _live_channels_list = _get_live_channels_list()


def _find_live_channel_index(site, channel):
    """Find the index of a channel in the live channels list."""
    with _live_channels_lock:
        for i, (s, c, _q, _n) in enumerate(_live_channels_list):
            if s == site and c == channel:
                return i
    return -1


def _register_live_channel_keybindings():
    """Register mpv key bindings for cycling through live channels.
    Returns True if key bindings were successfully registered."""
    # Define the key bindings in mpv using keybind command
    keybinds = [
        ['keybind', 'Right', 'script-message flux-tray-next-channel'],
        ['keybind', 'Left', 'script-message flux-tray-prev-channel'],
    ]
    return _mpv_ipc(keybinds)


def _unregister_live_channel_keybindings():
    """Remove mpv key bindings for live channel cycling."""
    keybinds = [
        ['keybind', 'Right', ''],  # empty command removes binding
        ['keybind', 'Left', ''],
    ]
    _mpv_ipc(keybinds)


def _cycle_live_channel(direction):
    """Cycle to the next/previous live channel. direction: 1 for next, -1 for previous.
    Only cycles through channels that are currently live."""
    global _current_live_index, _playing

    # Get currently live channels from state
    live_channels = _get_currently_live_channels()

    if not live_channels:
        return False

    # Find current index in the live channels list
    if _current_live_index < 0:
        with _player_lock:
            playing = _playing
        if playing:
            for i, (s, c, _q, _n) in enumerate(live_channels):
                if s == playing[1] and c == playing[2]:
                    _current_live_index = i
                    break

    if _current_live_index < 0 or _current_live_index >= len(live_channels):
        _current_live_index = 0

    # Calculate new index
    new_index = (_current_live_index + direction) % len(live_channels)
    _current_live_index = new_index

    site, channel, quality, name = live_channels[new_index]

    # Play the new channel with correct function signatures
    if site == 'Twitch':
        open_twitch_stream(channel, quality=quality, title=None, name=name)
    else:
        open_youtube_stream(channel, quality=quality, title=None, name=name)

    return True


def live_marker_markup(color, playing):
    """The colored bullet in front of a live row; a play triangle (forced to
    its text form, not the emoji one) while that stream is playing."""
    symbol = '▶︎' if playing else '●'
    return f'<span foreground="{color}"><b>{symbol}</b></span>'


def stream_window_title(site, channel, title=None):
    """mpv window title: site, user and stream title separated by bullets."""
    return ' \u00b7 '.join(p for p in (site, channel, title) if p)


def _mpv_ipc(commands, timeout=2.0):
    """Sends mpv JSON-IPC commands (each a list, e.g. ['loadfile', url,
    'replace']) and waits for one reply per command. True only if mpv is
    reachable and every command answered 'success'."""
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect(MPV_IPC_SOCKET)
        for command in commands:
            sock.sendall((json.dumps({'command': command}) + '\n').encode())
        pending = len(commands)
        ok = True
        buf = b''
        while pending > 0:
            chunk = sock.recv(4096)
            if not chunk:
                return False
            buf += chunk
            *lines, buf = buf.split(b'\n')
            for line in lines:
                try:
                    reply = json.loads(line)
                except ValueError:
                    continue
                if 'error' in reply:  # events have no 'error' key
                    pending -= 1
                    if reply['error'] != 'success':
                        ok = False
        return ok
    except OSError:
        return False
    finally:
        sock.close()


def _ensure_mpv():
    """True if an mpv with our IPC socket is running, starting one (idle,
    maximized) if not. --idle=once: it sits empty until the first stream,
    and quits when that playback ends, so the next click starts a fresh one."""
    global _mpv_proc
    with _mpv_lock:
        if _mpv_ipc([['get_property', 'pid']]):
            return True
        try:
            os.unlink(MPV_IPC_SOCKET)  # stale socket from a dead mpv
        except OSError:
            pass
        try:
            _mpv_proc = subprocess.Popen(
                ['mpv', '--idle=once', '--force-window=yes',
                 '--window-maximized=yes', f'--input-ipc-server={MPV_IPC_SOCKET}'],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            return False
        deadline = time_module.monotonic() + MPV_START_TIMEOUT_SECONDS
        while time_module.monotonic() < deadline:
            if _mpv_proc.poll() is not None:
                return False
            if _mpv_ipc([['get_property', 'pid']], timeout=0.5):
                return True
            time_module.sleep(0.2)
        return False


_mpv_version_cache = []  # [(major, minor) or None] once asked


def _mpv_loadfile_has_index():
    """mpv 0.38 put an index between loadfile's flags and its options; with an older
    mpv the options come straight after the flags. True when the new form is wanted
    (also when the version cannot be told: that is the one that will be common)."""
    if not _mpv_version_cache:
        try:
            out = subprocess.run(['mpv', '--version'], capture_output=True, text=True, timeout=5).stdout
            found = re.search(r'\bmpv v?(\d+)\.(\d+)', out)
            _mpv_version_cache.append((int(found.group(1)), int(found.group(2))) if found else None)
        except Exception:
            _mpv_version_cache.append(None)
    version = _mpv_version_cache[0]
    return version is None or version >= (0, 38)


def _load_in_mpv(stream_url, title, start=None):
    """Plays stream_url in the shared mpv window (replacing what's there), from
    `start` seconds in if given. If mpv does not take the start (a form of the command
    it does not know), the file is played from the beginning rather than not at all."""
    plain = ['loadfile', stream_url, 'replace']
    load = plain
    if start:
        load = plain + ([-1] if _mpv_loadfile_has_index() else []) + [f'start={start:.1f}']
    for _attempt in range(2):  # 2nd try covers mpv quitting right after the probe
        if not _ensure_mpv():
            return False
        if _mpv_ipc([['set_property', 'force-media-title', title], load]):
            return True
        if load is not plain and _mpv_ipc([['set_property', 'force-media-title', title], plain]):
            _log(f'mpv did not take start={start:.1f}; playing from the beginning')
            return True
        time_module.sleep(0.5)
    return False


def mpv_append_playlist(path, title):
    """Appends a file to the shared mpv's playlist via IPC.
    Used for series: when a new episode is downloaded or when starting a series,
    append subsequent episodes so 'next' in mpv works."""
    return _mpv_ipc([['loadfile', path, 'append-play'], ['set_property', 'force-media-title', title]])


def _mpv_get_properties(names, timeout=2.0):
    """{name: value} for mpv properties over the IPC socket; a property mpv cannot
    give right now (nothing loaded yet) is None. None when mpv is not reachable."""
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect(MPV_IPC_SOCKET)
        for number, name in enumerate(names, 1):
            sock.sendall((json.dumps({'command': ['get_property', name], 'request_id': number}) + '\n').encode())
        values, buf = {}, b''
        while len(values) < len(names):
            chunk = sock.recv(4096)
            if not chunk:
                return None
            buf += chunk
            *lines, buf = buf.split(b'\n')
            for line in lines:
                try:
                    reply = json.loads(line)
                except ValueError:
                    continue
                if 'request_id' in reply and 'error' in reply:  # events have neither
                    values[names[reply['request_id'] - 1]] = reply.get('data') if reply['error'] == 'success' else None
        return values
    except (OSError, IndexError, TypeError):
        return None
    finally:
        sock.close()


WATCH_POLL_SECONDS = 2.0
WATCH_LOAD_TIMEOUT_SECONDS = 30.0
WATCHED_PERCENT = 90.0
WATCHED_REMAINING_SECONDS = 20.0


WATCH_MAX_MISSES = 5  # polls in a row mpv may leave unanswered (waking from sleep) before it counts as gone
WATCH_MIN_PLAYED_FRACTION = 0.5  # of a file that must have been played, not skipped to, to count as watched
WATCH_MAX_PLAY_SPEED = 3  # a step between two polls of up to this many times real time is playing, not a seek
RESUME_MIN_SECONDS = 20  # an unfinished file is resumed only if it got further than this
RESUME_REWIND_SECONDS = 5  # and from this far before where it stopped, which is known only to a poll
SLEEP_PROMPT = 'Still watching? Press any key to carry on'


def counts_as_watched(percent, remaining, played_fraction=None):
    """Whether a playback that got as far as `percent` of the file, with `remaining`
    seconds left at its furthest point, was watched: through to the credits, or the
    last few seconds of anything that was at least half played. Polling is coarse,
    so the very end of a short file is often never seen. With `played_fraction`, how
    much of the file was actually played rather than skipped over, at least half of
    it must have been: seeking to the end to find one's place is not watching."""
    if percent is None:
        return False
    if played_fraction is not None and played_fraction < WATCH_MIN_PLAYED_FRACTION:
        return False
    return percent >= WATCHED_PERCENT or (percent >= 50 and remaining is not None and remaining <= WATCHED_REMAINING_SECONDS)


def _watch_local_playback(path, on_finished, poll=WATCH_POLL_SECONDS, total_seconds=None,
                          on_stopped=None, sleep_seconds=0, idle_seconds=None, on_playlist_advance=None):
    """Follows `path` in the shared mpv until it is replaced or mpv quits, then calls
    on_finished(furthest_percent, least_seconds_remaining) (None where never seen),
    after on_stopped({'position', 'played', 'duration'}) in seconds: where it stopped,
    how much of the file was played (steps of normal playback, not seeks; None if
    mpv gave no times) and the length. With total_seconds, how far it got is measured
    against that, since the length mpv reports for a file that is still being
    downloaded is only an estimate.

    mpv not answering is not taken as it having quit until it has failed
    WATCH_MAX_MISSES polls in a row: a laptop waking from sleep does not answer
    straight away, and giving up then would lose the rest of the file.

    With sleep_seconds, playback is paused (with a question on screen) once that long
    has passed without a key or mouse input, and carries on at the next one, so a film
    that nobody is watching does not run to its end. idle_seconds() tells the time since
    the last input (None when unknown).

    With on_playlist_advance, a callback is called when mpv advances to the next
    playlist item (user presses 'next'). The callback receives the new playlist
    position (1-indexed)."""
    percent = remaining = None
    loaded = False
    started = time_module.monotonic()
    misses = 0
    position = played = None
    duration = total_seconds
    paused_by_us = False
    idle_seconds = idle_seconds or x_idle_seconds
    max_step = poll * WATCH_MAX_PLAY_SPEED + 1
    last_playlist_pos = None
    while True:
        # Get properties including playlist position (try both 0-indexed and 1-indexed)
        values = _mpv_get_properties(['path', 'percent-pos', 'time-remaining', 'time-pos', 'duration', 'pause', 'playlist-pos', 'playlist-pos-1'])
        if values is None:
            misses += 1
            if misses >= WATCH_MAX_MISSES:
                break  # mpv is gone: it quits when the file ends
            time_module.sleep(poll)
            continue
        misses = 0
        if values.get('path') == path:
            loaded = True
            here, left = values.get('percent-pos'), values.get('time-remaining')
            at = values.get('time-pos')
            if isinstance(at, (int, float)):
                if position is not None and 0 < at - position <= max_step:
                    played += at - position
                elif played is None:
                    played = 0.0
                position = at
            if not total_seconds and isinstance(values.get('duration'), (int, float)) and values['duration'] > 0:
                duration = values['duration']
            if total_seconds:
                here = min(100.0, at * 100.0 / total_seconds) if isinstance(at, (int, float)) else None
                left = max(0.0, total_seconds - at) if isinstance(at, (int, float)) else None
            if isinstance(here, (int, float)) and (percent is None or here > percent):
                percent = here
            if isinstance(left, (int, float)) and (remaining is None or left < remaining):
                remaining = left

            # Check for playlist advancement
            if on_playlist_advance:
                # Try both property names (mpv has both playlist-pos (0-indexed) and playlist-pos-1 (1-indexed))
                playlist_pos = values.get('playlist-pos-1')
                if playlist_pos is None:
                    playlist_pos = values.get('playlist-pos')
                    if playlist_pos is not None:
                        playlist_pos = int(playlist_pos) + 1  # convert to 1-indexed
                if playlist_pos is not None:
                    playlist_pos = int(playlist_pos)
                    _log(f'Playlist position: {playlist_pos}, last: {last_playlist_pos}')
                    if last_playlist_pos is None:
                        last_playlist_pos = playlist_pos
                    elif playlist_pos > last_playlist_pos:
                        # Playlist advanced - call the callback
                        _log(f'Playlist advanced from {last_playlist_pos} to {playlist_pos}')
                        on_playlist_advance(playlist_pos)
                        last_playlist_pos = playlist_pos

            if sleep_seconds:
                idle = idle_seconds()
                if idle is not None and idle >= sleep_seconds and not paused_by_us and not values.get('pause'):
                    paused_by_us = bool(_mpv_ipc([['set_property', 'pause', True], ['show-text', SLEEP_PROMPT, 10000]]))
                elif idle is not None and idle < sleep_seconds and paused_by_us:
                    _mpv_ipc([['set_property', 'pause', False]])
                    paused_by_us = False
        elif loaded or time_module.monotonic() - started > WATCH_LOAD_TIMEOUT_SECONDS:
            break  # another file took its place, or it never loaded
        time_module.sleep(poll)
    if on_stopped:
        on_stopped({'position': position, 'played': played, 'duration': duration})
    on_finished(percent, remaining)


def resume_point(position, watched):
    """Where to carry on from next time, in seconds, or None: nowhere for a file that
    was watched through or that got hardly anywhere, otherwise a few seconds before
    where it stopped."""
    if watched or not isinstance(position, (int, float)) or position < RESUME_MIN_SECONDS:
        return None
    return max(0.0, position - RESUME_REWIND_SECONDS)


def play_media_file(path, title, on_finished=None, total_seconds=None, start=None, on_stopped=None, sleep_seconds=0, on_playlist_advance=None):
    """Plays a local file in the shared mpv window (replacing a stream or another
    file in it, the way one stream replaces another); subtitles saved next to it with
    the same name load on their own. True when it was handed to a player. With
    `start`, from that many seconds in. With on_finished, a thread reports how far
    playback got (see _watch_local_playback, which also says what on_stopped and
    sleep_seconds do; total_seconds is the length of a file that is still being
    downloaded). With on_playlist_advance, a callback is called when mpv advances to
    the next playlist item (user presses 'next'). The callback receives the new
    playlist position (1-indexed). Without mpv the file goes to the desktop's default
    player, untracked."""
    if not shutil.which('mpv'):
        try:
            subprocess.Popen(['xdg-open', path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
        except OSError:
            return False
    if not _load_in_mpv(path, title, start=start):
        return False
    _retire_stream()  # a stream that was in the window has nothing left to serve
    if on_finished or on_playlist_advance:
        threading.Thread(target=_watch_local_playback, args=(path, on_finished),
                         kwargs={'total_seconds': total_seconds, 'on_stopped': on_stopped, 'sleep_seconds': sleep_seconds,
                                 'on_playlist_advance': on_playlist_advance},
                         daemon=True).start()
    return True


def _retire_stream():
    """Called once a file has replaced a stream in the shared mpv: the stream's streamlink
    is stopped (as when the next stream replaces it) and no row shows it as playing."""
    global _playing, _current_live_index
    with _player_lock:
        _playing = None
    _current_live_index = -1
    _unregister_live_channel_keybindings()
    _stop_mpv_event_listener()
    _stop_streamlink()


def _stop_streamlink():
    global _streamlink_proc
    with _player_lock:
        proc, _streamlink_proc = _streamlink_proc, None
    if proc is not None and proc.poll() is None:
        try:
            proc.terminate()
        except OSError:
            pass


# --- MPV event listener for live channel cycling ---
_mpv_event_thread = None
_mpv_event_stop = threading.Event()


def _mpv_event_listener():
    """Background thread that listens for mpv events via IPC socket,
    specifically client-message events (from script-message) for channel cycling."""
    sock = None
    while not _mpv_event_stop.is_set():
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(1.0)
            sock.connect(MPV_IPC_SOCKET)

            buf = b''
            while not _mpv_event_stop.is_set():
                try:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    buf += chunk
                    *lines, buf = buf.split(b'\n')
                    for line in lines:
                        if not line:
                            continue
                        try:
                            event = json.loads(line)
                        except ValueError:
                            continue
                        # Handle client-message events (from script-message)
                        if event.get('event') == 'client-message':
                            args = event.get('args', [])
                            if args and args[0] == 'flux-tray-next-channel':
                                _cycle_live_channel(1)
                            elif args and args[0] == 'flux-tray-prev-channel':
                                _cycle_live_channel(-1)
                except socket.timeout:
                    continue
                except OSError:
                    break
        except OSError:
            pass  # mpv not running, will retry
        finally:
            if sock:
                try:
                    sock.close()
                except OSError:
                    pass
            sock = None
        time_module.sleep(2)  # wait before retrying


def _ensure_mpv_event_listener():
    """Start the mpv event listener thread if not already running."""
    global _mpv_event_thread
    if _mpv_event_thread is None or not _mpv_event_thread.is_alive():
        _mpv_event_stop.clear()
        _mpv_event_thread = threading.Thread(target=_mpv_event_listener, daemon=True)
        _mpv_event_thread.start()


def _stop_mpv_event_listener():
    """Stop the mpv event listener thread."""
    _mpv_event_stop.set()


def _stop_streamlink_on_exit():
    """Stop streamlink on exit, but only if no live stream is currently playing.
    If a live stream is playing, leave mpv and streamlink running so the user
    can continue watching after the app exits."""
    with _player_lock:
        playing = _playing
    # If a live stream is playing (streamlink proc is alive), don't stop it
    if playing is not None and playing[0] is not None and playing[0].poll() is None:
        _log('Live stream playing on exit: leaving mpv and streamlink running')
        return
    _stop_mpv_event_listener()
    _stop_streamlink()


atexit.register(_stop_streamlink_on_exit)


def _is_current_streamlink(proc):
    with _player_lock:
        return _streamlink_proc is proc


def _free_local_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]
    finally:
        s.close()


def _apply_stream_title(proc, url, site, channel, name=None):
    """Refines the window title with the author's display name and stream title
    from `streamlink --json` (external-http mode has no {author}/{title}
    substitution of its own): '<site> \u00b7 <author> \u00b7 <title>'. A display
    name from the config is used instead of the author. Emojis from stream titles
    (e.g., \U0001f534) are stripped."""
    try:
        result = subprocess.run(['streamlink', '--json', url],
                                capture_output=True, text=True,
                                timeout=YOUTUBE_CHECK_TIMEOUT_SECONDS)
        meta = json.loads(result.stdout).get('metadata') or {}
    except Exception:
        return
    title = stream_window_title(site, name or meta.get('author') or channel, _strip_emojis(meta.get('title')))
    if meta and _is_current_streamlink(proc):
        _mpv_ipc([['set_property', 'force-media-title', title]])


def _stop_streamlink_when_mpv_exits(proc):
    """The external-http server would otherwise serve forever after the mpv
    window is closed; stop it once mpv has been gone for two checks."""
    misses = 0
    while proc.poll() is None:
        time_module.sleep(3)
        if _mpv_ipc([['get_property', 'pid']], timeout=1):
            misses = 0
            continue
        misses += 1
        if misses >= 2:
            try:
                proc.terminate()
            except OSError:
                pass
            return


def _play_in_shared_mpv(url, quality, site, channel, fallback_url, title=None, name=None):
    """Worker thread: serve the stream via streamlink, load it into the
    shared mpv. Falls back to the browser if anything fails (unless a newer
    click has superseded this one).

    The previous stream's streamlink is deliberately left running until mpv
    has been told to load the new one: killing it first would end the file
    mpv is playing, and with --idle=once mpv quits when playback ends -- the
    window would close and reopen instead of being reused."""
    port = _free_local_port()
    try:
        proc = subprocess.Popen(
            ['streamlink', '--player-external-http',
             '--player-external-http-interface', '127.0.0.1',
             '--player-external-http-port', str(port), url, quality],
            # streamlink logs to stdout in some versions and stderr in others;
            # read both through one pipe
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, errors='replace')
    except Exception as e:
        _log(f'could not start streamlink: {e}')
        webbrowser.open(fallback_url)
        return
    global _streamlink_proc
    with _player_lock:
        previous, _streamlink_proc = _streamlink_proc, proc
    # streamlink logs this line once its local server is listening; mpv can
    # connect from then on (it fetches the actual stream on first request).
    watchdog = threading.Timer(STREAMLINK_READY_TIMEOUT_SECONDS, proc.kill)
    watchdog.start()
    ready = False
    recent = []  # last few log lines, for the failure message
    try:
        for line in proc.stdout:
            recent = (recent + [line.strip()])[-4:]
            if 'access with one of' in line:
                ready = True
                break
    finally:
        watchdog.cancel()
    loaded = ready and _load_in_mpv(f'http://127.0.0.1:{port}/',
                                    stream_window_title(site, name or channel, title))
    if not loaded:
        superseded = not _is_current_streamlink(proc)
        if not superseded:
            with _player_lock:  # the previous stream (if still alive) stays current
                _streamlink_proc = previous if previous is not None and previous.poll() is None else None
            if not ready:
                _log('streamlink never reported its local server; last output: ' + ' | '.join(recent))
            else:
                _log('streamlink is serving, but mpv could not be started or controlled')
        try:
            proc.terminate()
        except OSError:
            pass
        if not superseded:
            webbrowser.open(fallback_url)
        return
    global _playing, _current_live_index
    with _player_lock:
        _playing = (proc, site, channel)
    if previous is not None and previous.poll() is None:
        try:
            previous.terminate()  # mpv has already switched over to the new stream
        except OSError:
            pass

    # Update live channels list and register key bindings for channel cycling
    _update_live_channels_list()
    with _live_channels_lock:
        _current_live_index = _find_live_channel_index(site, channel)
    if _register_live_channel_keybindings():
        _ensure_mpv_event_listener()

    threading.Thread(target=_apply_stream_title, args=(proc, url, site, channel, name), daemon=True).start()
    threading.Thread(target=_stop_streamlink_when_mpv_exits, args=(proc,), daemon=True).start()
    for _line in proc.stdout:  # drain so streamlink never blocks on a full pipe
        pass


def _open_live_stream(url, quality, site, channel, fallback_url, title=None, name=None):
    if shutil.which('streamlink') and shutil.which('mpv'):
        try:
            threading.Thread(
                target=_play_in_shared_mpv,
                args=(url, quality, site, channel, fallback_url, title, name),
                daemon=True).start()
            return
        except Exception:
            pass
    webbrowser.open(fallback_url)


def open_twitch_stream(channel, quality='best', site='Twitch', title=None, name=None):
    """Plays the stream in the shared, maximized mpv window (see above) if
    streamlink and mpv are installed; falls back to opening the channel in
    the browser otherwise, or if starting playback fails."""
    _open_live_stream(f'twitch.tv/{channel}', quality, site, channel,
                      f'https://twitch.tv/{channel}', title, name)


def open_youtube_stream(channel, quality='best', title=None, name=None):
    """Same as open_twitch_stream (shared mpv window); falls back to the
    channel's page in the browser."""
    _open_live_stream(f'https://www.youtube.com/{channel}/live', quality,
                      'YouTube', channel, f'https://www.youtube.com/{channel}', title, name)
