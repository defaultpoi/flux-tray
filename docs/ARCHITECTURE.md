# Architecture

void-tray is one process on the GTK main loop. Timers run on it; anything that
waits (the network, a subprocess, a download) runs on a short-lived thread and
hands its result back with `GLib.idle_add`. Shared state is guarded by a small
number of named locks, each next to the data it guards (see `RssTray.__init__`).

## Layers

- **Mostly pure logic** (top-level modules): `config`, `state`, `rules`, `windows`, `schedule`, `network`, `updates`, `live`, `weather`, `media`, `mediasources`, `ytdlp`, `hls`, `links`, `fileutil`, `proc`, `playback`, `desktop`. They take values and return values and the tests call them directly; `app.py` and everything under `ui/` is where GTK lives.
- **Widgets** (`ui/`): `popup` builds the window and the list; `feeds`, `live`, `media`, `updates`, `weather`, `timer`, `icon` and `connectivity` are mixins that `app.RssTray` is assembled from. Each owns the widgets and the state of its part of the popup.
- **Entry**: `void-tray` (launcher), `void_tray/app.py` (`RssTray`, signals, `main`).

## Rules the structure keeps

1. A file is replaced whole or not at all: `fileutil.write_atomic` writes through a temp file of its own and renames it (`state.json`, `media.json`, `config.conf`). `config.conf` has one writer (`config._edit_config_section`); edits take turns under one lock.
2. Anything from outside is checked before use: links from feeds go through `links.open_link`, playlist addresses through `hls._fetch_text`.
3. Package scans and installs (xbps, topgrade, sudo) run in their own process group with a timeout and are ended as a group (`proc._kill_process_group`). Downloads (`yt-dlp`, `ffmpeg`) are not yet: see STATUS.md.
4. The file formats, `config.conf` syntax, the media plugin contract and `~/.config/void-tray` do not change, because whatever appends lines to `config.conf` (a browser extension, say), the user's media plugins and their files depend on them.

## Where this came from

The code is void-tray as of commit `eb73c7d`, 1233 tests green, kept as it was:
that is how the popup looks and behaves the same. What was added on top is the
part of flux-tray that fixed something real in it (links, playlists, the config
writer, the install scripts, the real-desktop checklist, the parity matrix) and
what neither had: golden files for the popup. What was not taken from flux-tray,
and why, is in [STATUS.md](STATUS.md).

## Tests

`tests/facade.py` gives the suite one namespace over the package (see the
README). `test_golden_popup` pins the popup's look, `test_parity` keeps
[FEATURES.md](FEATURES.md) honest. Both modes (real GTK under a display, GTK stubbed)
must pass.
