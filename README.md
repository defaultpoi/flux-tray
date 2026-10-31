# flux-tray

A lightweight, personal desktop tray companion for **Void Linux (glibc), XFCE and X11**. Flux Tray brings feeds, live streams, media queues, weather, Void package maintenance, connectivity status and timers into one compact GTK3 popup.

This is a clean implementation. It does not migrate, import or maintain compatibility with state or configuration from any earlier application.

## Project status

The repository is being built in feature-complete milestones. The target is the complete feature set in [the feature specification](docs/FEATURES.md), with architecture and implementation decisions in [the architecture](docs/ARCHITECTURE.md), [the roadmap](docs/ROADMAP.md) and the conservative [implementation status](docs/STATUS.md).

## Design goals

- Native, small GTK3 application for the user's Void/XFCE/X11 desktop.
- Low idle CPU and memory use; no daemon stack, database server or web frontend.
- One owner for each feature's state and clear boundaries between UI, application logic and operating-system integrations.
- All blocking I/O and subprocess work runs off the GTK main thread.
- Explicit timeouts, cancellation, bounded concurrency and clean shutdown.
- Human-editable INI configuration; small, atomic JSON state files.
- Extension points for media sources and user launcher actions without turning the app into a framework.
- Tests for pure logic first; integration tests around real command contracts; real-GTK checks for visual behavior.

## Target environment

Void Linux glibc, XFCE, X11. This is intentionally not a cross-distribution project. System package operations use XBPS directly. GTK3 is retained because the target desktop uses an X11 tray and the old application's tested interaction model is GTK3-based.

## Dependencies

Required: Python 3, PyGObject/GTK3, GLib, feedparser.

Optional integrations are detected at runtime: mpv, Streamlink, yt-dlp, ffmpeg, Topgrade, xbps utilities and a command-line notification/audio player. Missing optional tools disable only the relevant action and produce a useful status message.

## Install on Void Linux

Install the required system dependencies first: Python 3.14+, GTK3, PyGObject and feedparser. Optional integrations such as mpv, Streamlink, yt-dlp and ffmpeg can be installed separately; missing optional tools disable only their related features.

From a source checkout:

```sh
./install.sh
```

This installs the application under `~/.local/lib/flux-tray`, creates the `~/.local/bin/flux-tray` launcher and installs a desktop entry. It uses system Python so GTK/PyGObject remain available.

Enable XFCE session autostart during installation:

```sh
./install.sh --autostart
```

To disable an existing autostart entry while updating:

```sh
./install.sh --no-autostart
```

Remove the application files later with:

```sh
./uninstall.sh
```

The uninstaller leaves `~/.config/flux-tray` and `~/.local/share/flux-tray` untouched. Ensure `~/.local/bin` is on your shell's `PATH` if you want to launch `flux-tray` from a terminal; the desktop entry uses the installed absolute launcher path.

## Development

See [CONFIGURATION.md](docs/CONFIGURATION.md) for the current settings and [CONTRIBUTING.md](CONTRIBUTING.md) for local setup and test commands. Use the [XFCE/X11 validation checklist](docs/XFCE-VALIDATION.md) for the real-desktop checks that CI cannot cover. The application is designed to be developed and tested on the target Void machine; CI should cover pure Python tests and static checks without pretending to validate XFCE tray behavior.

## Scope

The full feature inventory is mandatory. A milestone may be incomplete while implementation is in progress, but a feature must not be silently dropped, replaced with a stub, or marked complete until its behavior and tests exist.

## Media plugins

Trusted Python plugins live in `~/.config/flux-tray/media-plugins/*.py`. They are reloaded when a source check begins and are tried before the built-in RSS/yt-dlp adapters. A source can select a plugin explicitly with `plugin:NAME:SOURCE`; otherwise its optional `matches(source)` function can claim a URL.

A plugin must provide:

```python
NAME = "example"
ORDER = 100

def list_episodes(source):
    return [
        {
            "id": "stable-id",
            "title": "Example S01E01 - Pilot",
            "date": "2026-10-30",
            "url": "https://media.example.test/video.mp4",
            "ext": "mp4",
            "season": 1,
            "episode": 1,
            "headers": {},
            "subs": {"en": "https://media.example.test/subtitle.vtt"},
            "metadata": {},
        }
    ]
```

Optional hooks are `matches(source)`, `resolve(episode)`, and `download(episode, base, progress, cancelled)`. A resolver returns a dictionary of replacement episode fields or `None`. A downloader returns the path to a completed file inside the caller-provided output area, or `None` to use the built-in downloader. Report progress through `progress(downloaded_bytes, total_bytes)`; check the cancellation event while doing long work.

Each plugin receives `flux_tray_helpers` with `fetch_json(url, timeout=10, max_bytes=1000000, headers=None)`, resumable `download_file(url, destination, timeout=30, headers=None, progress=None, cancelled=None)`, and `parse_season_episode(title)`. Returned records, resolver fields, headers, subtitle URLs and downloaded file paths are validated before the app uses them.

Plugins execute arbitrary Python with the user's permissions. Install only plugins whose source you trust. They must use bounded network operations and must not block the GTK thread.
