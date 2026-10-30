# Mandatory product specification

Every item is required. Flux Tray starts with fresh config/state; no legacy migration or compatibility. **Archive.org is intentionally not supported. Do not add an Archive.org source adapter, parser, downloader, or special-case behavior.**

## Tray and popup
GTK3 tray icon for XFCE/X11. Green = no unread feed items (show temperature if available), orange = unread feeds, red = XBPS updates. Severe weather can pulse matching value/badge. Live/media never affect badge. Compact popup; independently refresh sections and preserve scroll/expanded state. Open on new feed items, live transitions and media episodes. Close automatically when the last unread feed item is marked read; live streams, media and read-later entries do not keep it open. Right-clicking the blank gap after the unread/read-later lists and before the footer closes it. Optional sound. Theme icon fallback; U+FE0E for text glyphs when needed. Menus must fit popup bounds; Gtk.Popover cannot reliably escape parent.

## Additional interaction and media details inferred from the handoff brief

- Unread feed rows: left-click opens and marks read; right-click marks read without opening. Hover text exposes the full title, author and categories.
- Feed header context menu: mark all read, open all feed items as browser tabs, open the feed website or raw XML, and manage category/author mute and read-later rules.
- Media source ordering: each source can use the driver's default order or explicitly choose oldest-first/newest-first. Recognize season/episode notation such as S01E05 and 1x05; otherwise use publication date and stable source order. Flux stores the order on the source record and preserves the adapter's listing order by default.
- Media presentation and files: show a compact per-source summary with next unwatched episode, download state/progress and failure reason; use predictable source/season/episode/title filenames and keep subtitles beside the video for mpv auto-loading.
- HLS downloads: choose a screen-appropriate rendition, report progress from playlist duration, support cancellation and partial playback while downloading when the container permits it; reject live playlists as downloads. A failed subtitle must not fail the video. The built-in finite-playlist downloader uses ffmpeg stream copy, chooses a master-playlist variant against the detected monitor, refuses playlists without `#EXT-X-ENDLIST`, and downloads supported external subtitle sidecars best-effort.
- Media plugins: expose small helpers for bounded JSON fetches, resumable downloads and season/episode parsing; validate normalized dates, whole-number episode metadata, extensions, HTTP(S) subtitle URLs, safe headers, resolver output and completed download paths.

These details extend the current feature list; they do not reintroduce Archive.org support, DRM circumvention, Plex support or cross-platform targets.

## RSS/Atom
Multiple feeds, names, per-feed intervals, configured feed ordering. Default tick 60 s; pause offline; failed feed retry after 2 min. First-seen items older than 24 h silently marked seen. Cap unread at 500, oldest excess remains seen. Opening item marks read; feed header marks all read. Read-later is separate, not unread/badged/notified; open/remove removes it. Rules route categories/authors to read-later. Global/per-feed mute; mute beats read-later. Breaking/urgent whole-word, case/accent-insensitive matching in title/categories; configurable words, default breaking; pulse until read/dismissed. Hover shows categories/author; retain Website/XML links. All fetches bounded and off GTK.

## Live channels
Twitch channels/names/schedules; 15 min default; batched requests of 20 via logged-out GQL behavior; show category/viewers/elapsed and title tooltip; failed check must not erase last-known state. YouTube channels/names/schedules; Streamlink JSON per channel, no API key; best-effort viewers/start time; distinguish offline from failed. Shared Streamlink+mpv playback at configured quality (default best), reuse same mpv window, title Site · name · title; browser fallback if binaries/launch fail. No badge impact.

## Media
Sources: YouTube channel/playlist/video; RSS/Atom audio/video enclosures; arbitrary yt-dlp URL; trusted Python plugin. DRM/login-only services excluded unless yt-dlp can use user-supplied cookies. Hourly checks default, minimum 10 min; check newly added sources promptly; recheck on connectivity recovery; failed source retains catalog; first check is baseline only. Oldest/newest order; recognize S01E05 and 1x05, else date/stable order.
Ahead downloads default 2 (0=manual only), sequential, grouped by source, normalized filenames, resumable, retry next check/manual click. HLS partial playback after about one minute; playlist-aware progress; mpv continues through final rename; refuse live HLS. Choose best rendition fitting monitor with 15% headroom; if all larger choose smallest; detect monitor changes; allow screen override; yt-dlp -S res override wins. Save configurable subtitle languages (English by default for YouTube); mpv auto-loads; RSS/plugins may supply subtitles. Never auto-delete watched media.
Play next unwatched; download first if absent; share mpv with live. Watched at 90%, or last 20 seconds after at least 50%; no resume-position tracking. Persist catalog, watched/download state, queue/progress.
Plugins in ~/.config/flux-tray/media-plugins/, dynamically reloaded at source-check boundary. Plugin precedence over built-ins; named prefix syntax. Required list_episodes(source); optional NAME, ORDER, matches, resolve(episode), download(episode, base, progress, cancelled). Episode: stable id, title/date, url/ext, subs, headers, season/episode and opaque metadata. Helpers: bounded JSON fetch, resumable download, season/episode parser. Validate output and show per-source errors. Plugins are trusted arbitrary Python.

## Weather
Open-Meteo current temperature, high/low, wind, rain, five-day forecast; refresh 30 min default, minimum 5. Optional MeteoAlarm; Nominatim region/country resolution only if not configured; filter active time window and region. Moderate yellow, severe orange, extreme red; pulse matching value/badge. Unknown severity must not overstate urgency; disable cleanly if region unsupported.

## Void package maintenance
XBPS scan via xbps-install -Mn -u, default every 12 h. Install only on explicit action; skip scan during install. Topgrade optional: Void system step plus configured extras; force LC_ALL=C.UTF-8; summarize steps and actual package version changes; failures show output and remain until dismissed. Without Topgrade install individually with per-package status. Orphans via xbps-query -O without root; offer list, Remove, Remove+cache cleanup, Cancel. Never remove without explicit click. Orphans do not affect badge/sound/popup. Narrow non-interactive sudo rules only; never broad sudoers. vkpurge excluded pending separate request.

## Timers and schedules
Countdown default 0–2 h in 1 min steps; configurable max/step. Monotonic/boot-clock deadline; detect missed deadline after restart/resume; missed countdown does not ring late. Recurring actions: warn, fire once, snooze, cancel, restart recovery; idempotent. 1 s tick refreshes timer/corner readout. Alert pulse 600 ms; breaking/missed 700 ms; avoid pulse work while popup hidden.

## Launcher and connectivity
User-defined launcher commands in popup. argv safe by default; shell only when intentionally configured/documented as arbitrary trusted code. Show failures, never block GTK.
Connectivity/DNS probe every 10 s; diagnose DNS vs general outage; optional user-configured reset command, never auto-run unless configured. On recovery trigger feed/media/weather/live checks with duplicate suppression.

## Acceptance
No GTK mutation from workers. HTTP calls bounded. Subprocesses timed, cancellable and reaped. Clean shutdown. Atomic service-owned state. Pure tests for state transitions; focused UI tests. Real XFCE validation for tray, popup focus, CSS/theme, icons and suspend/wake.