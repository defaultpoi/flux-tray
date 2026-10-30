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

## Development

See [CONFIGURATION.md](docs/CONFIGURATION.md) for the current settings and [CONTRIBUTING.md](CONTRIBUTING.md) for local setup and test commands. The application is designed to be developed and tested on the target Void machine; CI should cover pure Python tests and static checks without pretending to validate XFCE tray behavior.

## Scope

The full feature inventory is mandatory. A milestone may be incomplete while implementation is in progress, but a feature must not be silently dropped, replaced with a stub, or marked complete until its behavior and tests exist.