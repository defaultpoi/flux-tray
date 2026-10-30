# Implementation status

This document is deliberately conservative. A service existing in the repository does not mean the corresponding product feature is complete or production-ready.

## Implemented foundations

- Python package layout, GTK3 application composition root and X11 tray shell.
- Human-editable INI configuration, atomic JSON storage and rotating logs.
- Bounded task manager, monotonic scheduler and subprocess supervisor with process-group cleanup.
- Shared mpv IPC controller, including reuse of an existing configured IPC socket.

## Partial feature implementations

| Feature | Present | Still missing or unverified |
|---|---|---|
| RSS/Atom | Fetch/parse, unread state, read-later, per-feed mute, rename/polling-interval/remove controls, breaking-word and category/author routing editor, category/author item labels, one-shot breaking-item desktop notification plus beep, tray-icon pulse while breaking items remain unread, right-click unread item to mark read, full title/author/category tooltip | Feed-header actions (open all, Website/XML, rule editing in context menu), robust first-run/offline testing and full XFCE popup validation |
| Live channels | Twitch logged-out GQL lookups batched in groups of 20; Streamlink JSON checks for YouTube; live/offline/error separation; last-known state preservation; Twitch viewer/category/start-time metadata; weekly schedule storage/editing; shared mpv playback and channel removal | YouTube viewer/start-time metadata is best-effort; real-provider verification, rate-limit resilience and full end-to-end playback testing |
| Media | yt-dlp/RSS-enclosure sources, plugin loading with validated list/resolve/download results and bounded helper API, episode normalization, add/rename/remove source controls, ahead queue, resumable yt-dlp downloads, persisted download status/failure with manual retry, live yt-dlp percentage in the tray menu, subtitles, shared mpv playback, direct HLS/live URL streaming in mpv, watched threshold logic and automatic X11 monitor-aware yt-dlp resolution sorting with manual screen/format-sort overrides | Partial playback while an HLS download is still running, HLS subtitle sidecar handling, and end-to-end playback testing |
| Weather | Open-Meteo current conditions and five-day forecast; optional MeteoAlarm country Atom feed with active-time and accent-insensitive region filtering, severity mapping and alert display; guided place/coordinate and alert setup dialog; severe alerts pulse in both the tray icon and open popup | Real-provider validation and real XFCE alert interaction testing |
| Connectivity | DNS/direct-IP diagnostic, offline feed pause, recovery-triggered checks and explicit confirmation for an optional user-configured argv reset command | Broader outage/recovery tests and real reset-command validation |
| XBPS | Dry-run update scan, orphan listing, explicitly confirmed system update, orphan removal/cache cleanup, optional Topgrade `system` plus configured steps, per-package XBPS fallback, package/version/action/download-size confirmation summary, and persisted maintenance outcomes with view/dismiss UI | Installed-versus-available version comparison and real Void package-manager validation |
| Timers | Persistent countdown with suspend/restart missed-deadline handling; weekly local-time alarms with weekday selection, add/edit/remove, once-per-date firing, persistent active alert, five-minute snooze and dismiss controls | Richer warning/alert controls and real suspend/restart desktop validation |
| Launcher | JSON argv commands, managed background spawn, add/edit/remove launcher-command dialog with JSON argv validation | Optional explicitly trusted shell commands (intentionally unsupported by default) |
| Tray | GTK3 status icon, popup, notifications, theme-independent icon fallback, tracked GLib timers, guarded duplicate activation and shutdown cleanup; popup closes when unread feed items reach zero (read-later/live/media excluded) or the blank gap before the footer is right-clicked | Actual theme/panel validation and real XFCE interaction tests |

## Verification status

- GitHub Actions compiles `src` and `tests`, then runs the pytest suite on Python 3.14 only. The latest runs for the Python 3.14-only CI target and `requires-python = ">=3.14"` both passed (30 October 2026).
- CI does not exercise GTK interactions, real network providers, mpv, XBPS/Topgrade or the target desktop.
- The code has **not** been run on the target Void Linux desktop in this development session; real XFCE/X11 integration remains unverified. A repeatable manual checklist is in [XFCE-VALIDATION.md](XFCE-VALIDATION.md).
- Do not treat this branch as a release until the missing behavior is implemented, the test suite passes, and the application has been exercised on the target machine over an extended run.
