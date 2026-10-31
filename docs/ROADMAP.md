# Roadmap

A milestone is complete only with behavior, tests and docs. Stubs do not count.

- [ ] M0 Foundation: packaging/launcher, config, atomic stores, logging, bounded task manager, scheduler, process supervisor, GTK tray/popup shell; real XFCE validation.
- [x] M1 Feeds: polling/retry/offline, old-item baseline, 500 cap, read/read-later, mute precedence, breaking pulse, tooltip/sound/popup behavior.
- [x] M2 Connectivity/weather: 10 s DNS diagnosis, recovery hooks, Open-Meteo current/forecast, MeteoAlarm region/time/severity.
- [x] M3 Live: Twitch batches, YouTube Streamlink, schedules, offline-vs-error, shared mpv playback/reuse/browser fallback.
- [ ] M4 Media sources: normalized models/order, YouTube, RSS/Atom enclosures, yt-dlp, dynamic plugins. Per-source default/oldest/newest ordering is implemented in the service and source editor.
- [ ] M5 Media runtime: sequential ahead queue, resumable downloads/retry and percentage progress, Direct HLS/live URL playback, monitor resolution, subtitles, watched state. Remaining: full target-desktop playback validation.
- [x] M6 Void maintenance: XBPS scan/install, Topgrade orchestration/summary, orphan scan and explicit removal/cache cleanup.
- [x] M7 Tools: monotonic countdown and missed-deadline handling; weekly recurring alarms with add/edit/remove, snooze/dismiss; launcher command management UI.
- [ ] M8 Integration: tray timer/callback cleanup, duplicate-activation guard, theme-independent icon fallback, feed-header context actions, popup read-later list and scroll preservation, blank-area right-click dismissal, and manual XFCE validation checklist are implemented; remaining: real XFCE verification of unread-zero/right-click dismissal, item right-click and feed-header context menu, actual theme/panel checks, suspend/resume validation, idle CPU/RAM profile and target-machine testing; user-local install/uninstall and optional XFCE autostart scripts are implemented.
Record real-machine checks as unverified until run. No migrations or cross-platform work.