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
| RSS/Atom | Fetch/parse, unread state, read-later, mute/routing rules, breaking-word matching, notifications and basic popup actions | Full feed settings UI, per-feed mute UI, category/author presentation, sound/pulse behavior, robust first-run and offline testing, full XFCE popup behavior |
| Live channels | Twitch logged-out GQL lookups batched in groups of 20; Streamlink JSON checks for YouTube; live/offline/error separation; last-known state preservation; Twitch viewer/category/start-time metadata; weekly schedule storage/editing; shared mpv playback and channel removal | YouTube viewer/start-time metadata is best-effort; real-provider verification, rate-limit resilience and full end-to-end playback testing |
| Media | yt-dlp/RSS-enclosure sources, plugin loading, episode normalization, ahead queue, resumable yt-dlp downloads, subtitles, shared mpv playback and watched threshold logic | Resolution/monitor selection, HLS partial playback, playlist-aware progress, source management polish, monitor-resolution selection, HLS partial playback, playlist-aware progress, download progress UI and end-to-end playback testing |
| Weather | Open-Meteo current conditions and five-day forecast using configured coordinates | Region lookup, MeteoAlarm alerts, severity mapping/pulse, setup UI and provider testing |
| Connectivity | DNS/direct-IP diagnostic, offline feed pause and recovery-triggered checks | User-configured reset action and broader outage/recovery tests |
| XBPS | Dry-run update scan, orphan listing, explicitly confirmed system update, orphan removal and cache cleanup | Topgrade integration, individual-package fallback, detailed version-change summaries and real Void package-manager validation |
| Timers | Persistent countdown, suspend/restart missed-deadline handling, one-shot alert | Recurring schedules, snooze/warn/fire-once workflow and alert UI polish |
| Launcher | JSON argv commands, managed background spawn | Launcher configuration UI and optional explicitly trusted shell commands |
| Tray | GTK3 status icon, popup, notifications and basic actions | Breaking/severe-weather pulse behavior, focus-out rules, theme/icon fallback validation and real XFCE interaction tests |

## Verification status

- Unit tests have been added for several pure services and command contracts, including Twitch batching and schedule validation; tests have not been executed in this session.
- The code has **not** been run on the target Void Linux desktop in this development session.
- No successful CI result or real XFCE/X11 integration result has been verified here.
- Do not treat this branch as a release until the missing behavior is implemented, the test suite passes, and the application has been exercised on the target machine over an extended run.
