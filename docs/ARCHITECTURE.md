# Architecture

Target: Python 3, GTK3/PyGObject, GLib on Void glibc + XFCE + X11. Standard library first; feedparser for feeds. No migration layer or database.

Dependency direction: GTK presentation -> application composition root -> feature services -> shared runtime primitives -> OS/network adapters. UI renders immutable snapshots and dispatches commands only.

Feature ownership: FeedService owns feed/read/rules/polling; LiveService owns channel checks/schedules; MediaService owns sources/plugins/episodes/download queue/watched state; WeatherService owns forecast/alerts; UpdateService owns XBPS/Topgrade/orphans; ConnectivityService owns probes/diagnosis/recovery; TimerService owns countdown/schedules; LauncherService owns configured launch actions. Each owns its own state document. No cross-service mutation.

Shared primitives: typed INI Config with debounced reload; atomic JsonStore; monotonic named Scheduler with initial delay/backoff/no-overlap; bounded TaskManager with duplicate-key suppression/cancellation; ProcessSupervisor with argv, timeout, process group, output and reaping; small urllib HttpClient with timeout/response cap; bounded/redacting logger; explicit X11 desktop adapter.

Threading: GTK main thread only. Workers return plain data. One GLib.idle_add boundary dispatches UI callbacks. Never block GTK on Future.result(). Never hold state locks during I/O. Scheduler callbacks dispatch work, never perform blocking work.

Shutdown: stop scheduler -> cancel tasks -> terminate managed process groups -> persist services -> destroy GTK. mpv is a managed long-lived process with reuse/health checks.

Media driver protocol: built-ins and plugins return normalized source/episode records. Plugins do not own queue, downloads, watched state or UI. Validate outputs, isolate source errors. Plugins are trusted code. Launcher entries are config, not Python plugins.

Paths: ~/.config/flux-tray/config.conf; ~/.config/flux-tray/media-plugins/; ~/.local/share/flux-tray/{feeds,media,timers,updates}.json; ~/.local/state/flux-tray/flux-tray.log. Fresh defaults only; never inspect old paths.

UI: one tray icon and compact popup; separate section builders for feeds/read later, live, media, weather, updates/orphans, connectivity, timer/schedules and launcher. Update affected section; preserve scroll/expanded state. Validate GTK3 CSS as a whole on real XFCE. Inline rows preferred over popovers outside popup bounds.