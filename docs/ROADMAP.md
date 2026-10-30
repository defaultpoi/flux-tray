# Roadmap

A milestone is complete only with behavior, tests and docs. Stubs do not count.

- [ ] M0 Foundation: packaging/launcher, config, atomic stores, logging, bounded task manager, scheduler, process supervisor, GTK tray/popup shell; real XFCE validation.
- [ ] M1 Feeds: polling/retry/offline, old-item baseline, 500 cap, read/read-later, mute precedence, breaking pulse, tooltip/sound/popup behavior.
- [ ] M2 Connectivity/weather: 10 s DNS diagnosis, recovery hooks, Open-Meteo current/forecast, MeteoAlarm region/time/severity.
- [ ] M3 Live: Twitch batches, YouTube Streamlink, schedules, offline-vs-error, shared mpv playback/reuse/browser fallback.
- [ ] M4 Media sources: normalized models/order, Archive.org, YouTube, RSS/Atom enclosures, yt-dlp, dynamic plugins.
- [ ] M5 Media runtime: sequential ahead queue, resumable downloads/retry, HLS partial playback, monitor resolution, subtitles, watched state.
- [ ] M6 Void maintenance: XBPS scan/install, Topgrade orchestration/summary, orphan scan and explicit removal/cache cleanup.
- [ ] M7 Tools: monotonic countdown, missed deadline, recurring schedules, launcher.
- [ ] M8 Integration: popup/tray polish, CSS/theme/icon fallback, focus, suspend/resume, process cleanup, idle CPU/RAM profile, docs/install.
Record real-machine checks as unverified until run. No migrations or cross-platform work.