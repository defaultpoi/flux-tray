"""Desktop integration: sounds, fullscreen detection, editor and launcher."""

import ctypes
import ctypes.util
import os
import shutil
import subprocess
import threading

from .gi_env import GLib, Gdk, Gio, Wnck
from .constants import CONFIG_DIR
from .log import _log


NOTIFICATION_SOUND_FILE = os.path.join(CONFIG_DIR, 'notification.wav')  # no sound if absent


def move_to_trash(path, root):
    """Moves one file to the desktop's Trash, from where it can be put back; nothing is
    erased. Only a regular file that lies inside `root` is touched: a link, a
    directory, a path that leads outside `root` (a `..`, a link in the way) is refused.
    Returns True when the file is no longer where it was (also when it was not
    there to begin with) and False when it was left in place."""
    try:
        if not os.path.lexists(path):
            return True
        real, base = os.path.realpath(path), os.path.realpath(root)
        if os.path.islink(path) or not os.path.isfile(path) or real == base \
                or os.path.commonpath([real, base]) != base:
            _log(f'not moving to the Trash, not a plain file inside {root}: {path}')
            return False
        Gio.File.new_for_path(real).trash(None)
        return True
    except Exception as error:  # GLib.Error when there is no Trash on that disk, OSError, ValueError
        _log(f'could not move {path} to the Trash: {error!r}')
        return False


def run_launcher_command(command):
    """Runs `command` through the shell, fully detached from the tray app
    (own session, no stdio), from the home directory. True if it started."""
    try:
        proc = subprocess.Popen(
            ['sh', '-c', command], cwd=os.path.expanduser('~'), start_new_session=True,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as e:
        _log(f'could not run launcher command {command!r}: {e}')
        return False
    threading.Thread(target=proc.wait, daemon=True).start()  # reap it, no zombie
    return True


def play_notification_sound():
    """Best-effort: plays notification.wav from the config directory with
    whichever player is available. Silently does nothing if the file or every
    player is missing."""
    if not os.path.exists(NOTIFICATION_SOUND_FILE):
        return
    for player in (['paplay'], ['aplay', '-q'],
                   ['ffplay', '-nodisp', '-autoexit', '-loglevel', 'quiet']):
        if shutil.which(player[0]):
            try:
                subprocess.Popen(player + [NOTIFICATION_SOUND_FILE],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return
            except Exception:
                continue


def primary_monitor_size():
    """(width, height) in pixels of the primary monitor, at its scale factor (a 1366x768
    panel set to 2x is 2732x1536 pixels of picture); None when there is no display to ask.
    Main thread only."""
    display = Gdk.Display.get_default()
    if display is None:
        return None
    monitor = display.get_primary_monitor() or display.get_monitor(0)
    if monitor is None:
        return None
    geometry, scale = monitor.get_geometry(), monitor.get_scale_factor() or 1
    return (geometry.width * scale, geometry.height * scale)


def is_fullscreen_active():
    """Best-effort check for whether the currently focused window is fullscreen,
    so the popup doesn't interrupt a video/game/presentation. Returns False
    (never suppresses) if the Wnck library isn't available."""
    if Wnck is None:
        return False
    try:
        screen = Wnck.Screen.get_default()
        screen.force_update()
        active = screen.get_active_window()
        return bool(active and active.is_fullscreen())
    except Exception:
        return False


def edit_file_externally(path):
    """Opens `path` in the user's default application for its type -- the one
    set in the desktop's settings (e.g. XFCE's Default Applications). Tried in
    order: GIO (in-process, needs nothing beyond GTK itself), xdg-open, and
    finally $EDITOR in a terminal."""
    try:
        if Gio.AppInfo.launch_default_for_uri(Gio.File.new_for_path(path).get_uri(), None):
            return
    except GLib.Error as e:
        _log(f'GIO could not open {path}: {e.message}')
    if shutil.which('xdg-open'):
        try:
            subprocess.Popen(['xdg-open', path])
            return
        except OSError as e:
            _log(f'xdg-open failed: {e}')
    editor = os.environ.get('EDITOR', 'vi')
    if shutil.which('xfce4-terminal'):
        subprocess.Popen(['xfce4-terminal', '-e', f'{editor} "{path}"'])
    else:
        try:
            subprocess.Popen([editor, path])
        except Exception:
            print(f"Couldn't open an editor — edit manually: {path}")


class _XScreenSaverInfo(ctypes.Structure):
    _fields_ = [('window', ctypes.c_ulong), ('state', ctypes.c_int), ('kind', ctypes.c_int),
                ('til_or_since', ctypes.c_ulong), ('idle', ctypes.c_ulong), ('event_mask', ctypes.c_ulong)]


_xss = None  # (library, display, root window, info) once opened, False when it cannot be
_xss_lock = threading.Lock()


def _open_xss():
    """Connects to the X display and the screensaver extension, which keeps the time
    of the last key or mouse input. False, with the reason logged, when it cannot."""
    try:
        x11_name, xss_name = ctypes.util.find_library('X11'), ctypes.util.find_library('Xss')
        if not x11_name or not xss_name:
            _log('idle time unavailable: libX11 or libXss (libXScrnSaver) not found')
            return False
        x11, xss = ctypes.CDLL(x11_name), ctypes.CDLL(xss_name)
        x11.XOpenDisplay.restype = ctypes.c_void_p
        x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
        x11.XDefaultRootWindow.restype = ctypes.c_ulong
        x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        xss.XScreenSaverAllocInfo.restype = ctypes.POINTER(_XScreenSaverInfo)
        xss.XScreenSaverQueryInfo.restype = ctypes.c_int
        xss.XScreenSaverQueryInfo.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(_XScreenSaverInfo)]
        display = x11.XOpenDisplay(None)
        if not display:
            _log('idle time unavailable: no X display')
            return False
        return xss, display, x11.XDefaultRootWindow(display), xss.XScreenSaverAllocInfo()
    except Exception as error:
        _log(f'idle time unavailable: {error!r}')
        return False


def x_idle_seconds():
    """Seconds since the last key or mouse input on the X display, or None when that
    cannot be told (no X, no screensaver extension)."""
    global _xss
    with _xss_lock:
        if _xss is None:
            _xss = _open_xss()
        if not _xss:
            return None
        xss, display, root, info = _xss
        try:
            return info.contents.idle / 1000.0 if xss.XScreenSaverQueryInfo(display, root, info) else None
        except Exception as error:
            _log(f'could not read the idle time: {error!r}')
            return None
