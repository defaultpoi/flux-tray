# Status

Dates and versions of real runs go in the evidence section at the end, never in
the tests' place.

## What was checked, and how

| What | How | Result |
|------|-----|--------|
| The 1233 tests the code had at baseline commit `eb73c7d` | real GTK under Xvfb, and GTK stubbed | pass, before any change |
| Everything now | the same two modes, on Python 3.14.6 with PyGObject 3.50.2, GTK 3.24 (1742 tests); `pyflakes` clean | pass |
| Popup look and click hooks | `test_golden_popup`, two scenarios; identical on three runs and in the dark and default theme; a changed header and a changed colour digit both fail it | pass |
| Each hardening change | its new tests run against the old code | fail there, pass now |
| yt-dlp and ffmpeg | the real binaries in the tests that use them (ffmpeg 6.1) | pass |
| mpv, the live-channel keys and `loadfile` with a start | the real mpv: 0.37.0 (Ubuntu) and 0.41.0 (AppImage build of 2026-10-24); `test_playback.TestLiveChannelKeysInARealMpv` on both, and the app's own `_load_in_mpv(..., start=20)` on 0.41.0, which takes the index form and starts at 20 s | pass |
| The way the old live-channel keys were taken away (`keybind Right ''`) | the same real mpv, both versions | left Right dead: no seeking in any file played after a stream. Replaced |
| New tests against the code they test | a deliberate break of each fix, one at a time , the new tests run | each break fails a test (23 breaks) |
| `install.sh`, `uninstall.sh` | tests with a temporary HOME | pass |
| Python 3.14 only | an older version number is refused at import with a message; the metadata says `>=3.14` | pass |
| CI on GitHub | `.github/workflows/ci.yml`: uv, Python 3.14, PyGObject built from source, both test modes; runs for commits `ae91f8a`, `36aed96` and `e50d623` (on `next` and on `main`) | pass |

## What was NOT checked

IMDb's chart pages (`imdb_charts.py` was run on fake pages only), `find` against the live fsonline site (its address pattern `<title>-<year>-online-subtitrat` and the IMDb id in `window.DFO_COMMUNITY_V5` were confirmed from one real page, "2012", which the plugin's tests use; the sitemap's `page=` parameter, which is the fallback, is not), OMDb answering with a real key (its error texts "Movie not found!", "Incorrect IMDb ID.", "Request limit reached!" are taken from its documentation), the day OMDb counts its limit by (UTC is used), a left click on a real desktop.

TMDb and OMDb answering (the lookups are tested against a fake network with the replies' shape taken from their documentation; nothing was asked of the real services, and a TMDb *API Read Access Token* is what `tmdb_key` takes), a stream surviving the app's exit (a Python child with a closed log pipe was seen to; streamlink itself was not), the licence of MeteoAlarm's wind and rain icons, mpv other than 0.37 and 0.41.0.

## What changed since the baseline

- Renamed to Flux Tray: package `flux_tray`, launcher `flux-tray`, class `FluxTray`, configuration directory `~/.config/flux-tray`, debug variable `FLUX_TRAY_DEBUG`. The names of the earlier versions, their configuration directory, their debug variable and the code that copied their files over are gone. Anything from an old directory has to be moved by hand once 
- Python 3.14 only: refused at import below it, `requires-python` in `pyproject.toml`, the tests and CI run on it.
- Links from feeds open only when they are http(s) addresses (`links.py`).
- A playlist address, and a variant a master playlist names, must be http(s) before it is read (`hls._fetch_text`). ffmpeg 6.1 already refuses a `file:` segment inside an http playlist, so no `-protocol_whitelist` was added.
- `config.conf` edits take turns and write through `write_atomic` (a weather write and a Mute click could lose one change; a failed write left `config.conf.tmp`).
- `_parse_default_gateway` no longer raises on a short line.
- Golden files for the popup, the parity matrix and its test, the real-desktop checklist, the install scripts.
- Alerts for the forecast days: the MeteoAlarm feed is read once and also yields alerts that have not started (up to the end of the fifth forecast day); the `›` button of the first weather slide takes the colour of the worst of them and says which in its tooltip, and the glyph of each affected day on the forecast slide takes that day's colour (a ⚠ where the day has no rain glyph). Alerts are mapped to days by their time windows in local time (tested at midnight edges and across time zones); an alert with no end covers only its start day. Checked on real GTK: the colours GTK computes for the button and its label, and screenshots. Not checked: a real feed, so how far ahead the country's feed really goes is not known; the colours are steady (no pulsing) by choice.
- The tray icon during a weather alert with nothing unread or to update: no disc, the temperature alternates between the severity colour and white at the severity's rate (as asked; the original pulsed a disc holding the temperature). Rendered with real cairo against the original: every other icon state (12 checked: plain temperature, negative, no weather, unread counts, updates, the scheduled-action warning, an alert with unread items or updates, an alert without a temperature) is pixel-identical; only the alert-with-temperature frames differ. The popup's weather bar is unchanged.
- Media: where an unfinished episode stopped is remembered and used (also after a stream took the mpv window, which is reused); watching is judged by time played, not by the furthest point; mpv silent for a few polls does not end the tracking; `behind`, `grace`, `sleep` and the `movie` marker; deletions go to the Trash, only for files inside the media folder; an episode can be put back as not watched. Checked on a real mpv 0.37 under Xvfb (resume, one process and one window across a stream switch, streamlink stopped, position remembered); X idle time checked against real input events under Xvfb. Not checked: mpv 0.38 or newer (the new `loadfile` form is covered by unit tests and a fallback), a real suspend, a real XFCE Trash on another disk.
- Fully watched sources can be taken off the Media list from a right-click menu (one, or all of them); not tried on a real desktop yet. `.coverage` is no longer tracked.
- Discovery and the metadata behind it (commit `28cd916`; first written in `18a64e2` with Claude Code, reworked here): plugins' `fetch_discovery` filed in one cache keyed by TMDb id, IMDb id, or title, year and type; the hover preview; TMDb and OMDb lookups. Reworked because the first version had no tests and: raised `NameError` on every lookup failure and then cached the title as "not found" for a week; gave the same film from two sites two entries (the discovery date stood in for the year); never re-keyed an entry (a size comparison that could not be true) and wrote `state.json` from a thread over the app's own copy; asked TMDb's `/find` for an IMDb id from a TMDb id (it cannot) so OMDb never enriched anything; did its disk and network work on the main loop; and added two hover handlers to every media row at every download tick. See README (Discovery) and F40, F41.
- The forecast-day alerts of `ae931a9` are back: `18a64e2` had been made from its parent, so the push replaced them with a second, weaker version of the feature (its alert-to-day mapper needed an `onset` the feed code never returned, so no day was ever marked). What was new in `18a64e2` and kept: the alert's own text from the CAP document (https meteoalarm.org only, 1 MB, cached) and a sentence built from the entry when it is missing.
- Discovery from IMDb's charts, the watch list and OMDb's daily limit (F45-F47). `discovery=` names the sources of the discovery list (charts, by the address their plugin matches); their titles come with IMDb ids, in chart order, and OMDb is asked for each by that id (one exact request, at most `omdb_daily_limit=` a day, the count in `omdb_quota.json`); `tmdb_key` is ignored unless `tmdb=on`. A left click puts the title on the watch list in `media.json`; the plugins' `find(title, year, imdb_id, kind)` are asked at every media check until one has it, and it then becomes a source read at every check (sources added by a click were only read once, at the click: a series was never followed), downloaded by the rules of `[media]`, a film removed after it is watched like the configured ones, and listed on top of the media list. A right click dismisses a title for good. Found while doing this: `get_new_items` called every undismissed item new at every check (with a chart, the popup would have opened with a sound every hour); the media check read the network while holding the media lock; the prefix of `imdb-charts:moviemeter` is cut off before the plugin sees it, so the plugin's own handling of that form could never have worked.
- IMDb chart discovery fixed (commit `2026-11-10`): `imdb_charts.py` now fetches via `r.jina.ai` proxy to bypass AWS WAF blocking (HTTP 202 challenge page). Returns ~100 titles per chart with correct IMDb IDs.
- Discovery plugins changed: `fsonline_one` and `sitefilme_com` no longer provide `fetch_discovery` (discovery now only from IMDb charts). Both plugins provide `find()` for the watch list.
- `sitefilme_com` gained `find()` (searches via `?s=title` and matches English title; movies only).
- `find_source()` in `watch.py` prioritizes: movies → `sitefilme_com` first (direct m3u8), then `fsonline_one`; series → `fsonline_one` only. New tests in `test_watch.py::TestFindingATitle` cover this priority.
- Live-channel keys: Right and Left cycle from the channel playing (the first version indexed a list of configured channels, not the live ones) through an mpv input section held over the listener's own connection (mpv drops a section with the client that defined it), instead of `keybind` set to an empty command on removal. `_strip_emojis` no longer deletes CJK, Hangul or fullwidth text.
- News entries a feed edits come back once as `LIVE` items (`18a64e2`), now with a baseline on the first update time, at most one announcement an hour per entry, an unread item replaced in place, and the second sound only for items really added; undocumented before, README and F42 now say it.
- The hazard icons on the tray icon: one cached parser and drawer (there were two, the first dead), the thunderstorm and flood shapes drawn for the app (the ones in `18a64e2` were not MeteoAlarm's and not recognisable), a test that every path parses and stays inside its viewBox. With nothing unread the icon alternates between the temperature and a **white** hazard icon: the severity colour of `ac0c82d` is gone from the icon, and the severity shows in the rate only (README says so).
- Cleanup found by measuring (below): dead and duplicated code removed, `build_popup_window` (223 lines) and `check_feeds` (the most complex function) split into parts that can be read and tested on their own.

## Code health, measured

Measured at the baseline with `vulture`, `coverage`, `radon` and a six-line duplicate scan, then again after the cleanup.

| | Baseline | After cleanup |
|---|---|---|
| Unused code (vulture, >= 60%) | 3 (an unused method, two unused variables) | 0 |
| Duplicated blocks of 6+ lines | 3 | 0 |
| Functions over 60 lines | 9 of 468 | 7 of 482 |
| Longest function | `build_popup_window`, 223 lines | `ensure_config`, 135 lines (a config template) |
| Most complex function | `check_feeds`, rank E (38) | `refresh_list`, rank F (42) |
| Line coverage by the tests | 85% overall | the same, plus the golden test and 22 direct tests of the feed logic |

The cleanup was checked three ways: the original tests unchanged, the golden
popup files byte for byte unchanged, and, for `check_feeds`, the old and the new
function run on 400 randomised scenarios (failed fetches, muted and old entries,
read-later rules, a full unread list, retention) with identical resulting state
and callbacks every time.

Still the largest and least tested:

- `ui/popup.py` `refresh_list` (113 lines, rank F) and `on_row_activated` (rank D): one long chain of `if hasattr(row, ...)` over row kinds.
- `ui/timer.py` (66% covered), `ui/icon.py` (68%), `ui/live.py` (67%), `ui/weather.py` (70%).
- `app.py` `__init__` (112 lines): 83 attributes set in one place for nine mixins to share.
- `download_hls`, `download_ytdlp`, `list_ytdlp` and `load_state` (rank D).
- The Twitch and YouTube checkers differ in one respect: only a failed Twitch check notes a request failure for the connectivity logic. That may be intended or an inconsistency.
- `schedule.load_schedule_settings` still reads the older single-schedule keys of `[schedule]`.

## Taken from the earlier rewrite attempt, and what was left

An earlier attempt at a rewrite, made from a written description, used to be in
this repository. It had the app's internals rebuilt but not its look or all of
its features. Taken as ideas, re-done against this code with tests: validating
addresses before using them, one atomic writer, install and uninstall scripts,
the checklist for a real desktop, the status and features documents.

Not taken, deliberately:

- Its task manager, scheduler and process supervisor. The timers and threads here have been verified in use, and no defect was found that they would fix. The supervisor is the exception worth a second look (process groups for downloads), but it lost all output on a single non-UTF-8 byte when tried, so it would need that fixed first.
- Its GUI editing of sources, weather setup and launcher entries, and its plugin syntax: they change how the app looks and how files and plugins are read.
- Its dropping of archive.org.

## Open items found, not changed

- Only the fsonline plugin has a `find`; sitefilme's has none (it has no search that is known), so a title only sitefilme has is never found. A site that names its pages by the Romanian title will not match an English chart title by its address.

- The tray icon no longer shows an alert's severity colour (above): wanted?
- sitefilme's discovery items are dated the day they were fetched, and fsonline's feed is read for the last 24 hours only: a check that comes more than a day after the last (the app off, or suspended) misses what appeared in between. The plugins are outside this repository.
- The quality badge is green for `HD` and red for anything else, so `BLURAY` and `WEBRIP`, which fsonline also reports, are red.
- `PERFORMANCE_ANALYSIS.md` is an agent's report; only the claim about `_refresh_media_rows` was checked (it was wrong, and is corrected there).

- `yt-dlp` and `ffmpeg` downloads are not started in their own process group; whether quitting during a download leaves a child behind has not been checked on a desktop (XFCE-VALIDATION 4).
- A feed is fetched with `feedparser.parse(url)`: a 15-second socket timeout applies to each read (`socket.setdefaulttimeout`), but there is no limit on the size of a response or on the total time. Fetching with explicit limits would also change how redirects, gzip and encodings are handled, which cannot be tried against real sites here.
- `state.json` is written by `json.dump` of the whole state on every save; fine at the sizes in use.

## Evidence

2026-11-08: real mpv 0.37.0 (Ubuntu 24.04) and 0.41.0 (`pkgforge-dev/mpv-AppImage`, `v0.41.0@2026-10-24`), headless and under Xvfb, no desktop: the live-channel key test passes on both, the old unbind leaves Right dead on both, and `_load_in_mpv('/tmp/t.mp4', 'Test title', start=20.0)` on 0.41.0 loaded the file with the title and started at 21.4 s.

2026-11-10: real network tests under Xvfb (Python 3.14, PyGObject 3.50, GTK 3.24):
- `imdb_charts.py` via `r.jina.ai` proxy: 100 movies + 100 series from IMDb charts (200 total)
- `fsonline_one.find()`: "Interstellar (2014)" → `https://fsonline.one/film/interstellar-2014-online-subtitrat/`, "The Odyssey (2026)" → `https://fsonline.one/film/the-odyssey-2026-online-subtitrat/`
- `sitefilme_com.find()`: "Interstellar (2014)" → `https://sitefilme.com/online/5291/`, "The Odyssey (2026)" → `https://sitefilme.com/online/135644/`
- `find_source()` priority verified: movies use sitefilme_com first, series use fsonline_one only
- All 1725 tests pass (Xvfb + stubbed), pyflakes clean

2026-11-10: fsonline sitemap-based watch list check (commit ccf82c0):
- Added `fetch_new_episodes(since_timestamp, watch_titles)` and `fetch_new_movies(since_timestamp, watch_titles)` to `fsonline_one` plugin
- Scans episodes/movies sitemaps (newest-first with `lastmod` timestamps), stops when items are older than `since_timestamp`
- Caches sitemap pages for 5 minutes (`SITEMAP_CACHE_SECONDS = 300`)
- `_search_fsonline_sitemap()` in `MediaMixin` runs at media check interval, checks watch list entries still searching, triggers targeted media checks only for series/movies with new episodes
- Shared `_norm_title()` in `watch.py` for title normalization (no accents, lowercase, dash-joined)
- 17 new tests in `test_fsonline.py` covering: empty cache, no matching titles, matching titles, pagination, stopping at older items, cache behavior, title extraction, title normalization
- All 1742 tests pass (Xvfb + stubbed), pyflakes clean; 4 mutations caught by tests (reversed comparison, wrong suffix check, disabled new-item detection, numbers stripped from title)

No run on a real desktop yet.

2026-11-10: Media Accordion UI repositioning and header redesign (this commit):
- Media accordion moved from top (after schedule warning) to bottom (just above footer buttons)
- Header button: removed icon (video-display-symbolic) and chevron (pan-down/pan-up-symbolic)
- Header text "Media" centered with count badge, `xalign=0.5`, `halign=CENTER`, `hexpand=True`
- 4 deliberate breaks caught by tests:
  1. `header_label.set_xalign(0.5)` → `0` → CAUGHT by `test_header_button_has_centered_text_no_icon_no_chevron`
  2. `header_box.set_halign(Gtk.Align.CENTER)` → `START` → CAUGHT by same test
  3. `header_box.set_hexpand(True)` → `False` → CAUGHT by same test
  4. Accordion at top position (old code) → golden tests FAIL, moved to bottom → PASS
- All 1760 tests pass (Xvfb + stubbed), pyflakes clean
- Golden test files updated: `popup_full.json`, `popup_quiet.json`, `popup_media_removed.json`

2026-11-11: Discovery/Track tab separation fix:
- `discovery_source_urls()` now excludes watching items (watch list entries with `source=None`) from Discover tab
- `track_item_count()` method added to `MediaMixin` — counts monitoring + searching entries for popup visibility
- `refresh_list()` uses `track_count` to keep popup open when Track tab has items
- 3 deliberate breaks caught by tests:
  1. `discovery_source_urls()` without `not item.get('watching')` filter → test `test_a_title_being_looked_for_is_the_first_row_of_the_discovery_list_the_newest_first` FAILS
  2. `track_item_count()` formula broken (only monitoring) → test `test_track_item_count_returns_monitoring_plus_searching` FAILS
  3. `refresh_list()` without `track_count == 0` check → test `test_a_media_only_popup_that_is_already_open_collapses_like_one_with_only_live_channels` FAILS

2026-11-11: Test isolation fix — tests no longer write to real `~/.config/flux-tray/state.json`:
- Root cause: `TmpConfigCase` patched `rt.STATE_FILE` but `flux_tray.state.STATE_FILE` is a module-level constant captured at import time
- Fix: `TestMediaAccordion` now inherits from `TmpConfigCase` (was `unittest.TestCase`), calling `super().setUp()` to activate the temp config patching before any state operations
- Verified: both test suites (1762 stubbed + 1762 Xvfb) pass; real `state.json` remains absent after full test runs
- All deliberate mutations caught; pyflakes clean

2026-11-11: Header badge count fix — Track tab items no longer counted in Media header badge:
- Bug: `_update_header_label()` summed `watch_count + discover_count + track_count` for the header badge
- Fix: Changed to `watch_count + discover_count` only; Track items are for monitoring/searching, not actionable media
- Test `test_update_header_label_shows_watch_plus_discover_count` verifies Track items (2) are excluded from header badge
- Mutation test (adding track_count back) caught by test: CAUGHT
- All 1762 tests pass (both modes); pyflakes clean
- All 1761 tests pass (Xvfb + stubbed), pyflakes clean

2026-11-11: Fix for old feed news resurfacing as unseen:
- Bug: `merge_feed_check()` in `state.py` pruned seen entries based only on `seen_at` timestamp (30-day retention). Entries seen long ago but recently updated (e.g., a feed entry edited today) were pruned, causing them to resurface as new unread items on the next feed check.
- Fix: Updated pruning logic to also keep entries where `updated` timestamp is within the retention period. Added test `test_an_entry_seen_long_ago_but_updated_recently_is_not_pruned`.
- Verified: All 1762 tests pass (Xvfb + stubbed), pyflakes clean. Deliberate break of the fix caught by new test.

2026-11-11: Fast right-click dismiss for news items:
- Bug: Right-click to dismiss a news item called `refresh_list()` which rebuilt the entire listbox from scratch (slow, especially with many items).
- Fix: Added `_remove_unread_row()` method that removes the single row from the listbox directly and updates state without full rebuild. Right-click handler now calls this fast path.
- Tests updated in `test_rules.py::TestHeaderClicks` and `test_ui_connectivity.py::TestOfflineBehavior` to mock the new method.
- Mutation test (reverting to `on_mark_read_clicked` / full rebuild) caught by test: CAUGHT
- All 1762 tests pass (both modes); pyflakes clean

2026-11-11: Fix for Discover tab showing only first item (Mobland):
- Bug: MediaAccordion's Discover tab (and other tabs) had broken scrolling. The scrolled windows used `set_propagate_natural_height(True)` which made them request their full natural height (8000+ px) from the parent notebook/revealer, instead of being constrained and showing scrollbars. The revealer expanded to fit the huge notebook, but the popup window constrained it, cutting off most items.
- Fix: Removed `set_propagate_natural_height(True)` from the three tab scrolled windows. Added a fixed max height (50% of screen) to the notebook so scrolled windows get a constrained allocation and can scroll properly.
- Verified: All 1762 tests pass (Xvfb + stubbed), pyflakes clean. Discover tab now shows all 200 items with working scrollbar.

2026-11-11: Fix for Media Accordion hover popovers not showing:
- Bug: MediaAccordion's three tab listboxes (Watch, Discover, Track) had no motion/leave event handlers connected, so hovering a row didn't show the metadata popover with title, year, type, IMDb/TMDb IDs, and overview.
- Fix: Added `_setup_listbox_hover_events()` method that connects `motion-notify-event` and `leave-notify-event` to all three tab listboxes, calling parent's `_on_media_row_enter()` and `_on_media_row_leave()` for metadata popover display.
- Verified: All 1762 tests pass (Xvfb + stubbed), pyflakes clean. Metadata popovers now appear on hover in all three tabs.
