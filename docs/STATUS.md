# Status

Dates and versions of real runs go in the evidence section at the end, never in
the tests' place.

## What was checked, and how

| What | How | Result |
|------|-----|--------|
| The 1233 tests the code had at baseline commit `eb73c7d` | real GTK under Xvfb, and GTK stubbed | pass, before any change |
| Everything now | the same two modes, on Python 3.14.6 with PyGObject 3.50.2, GTK 3.24 (1783 tests); `pyflakes` clean | pass |
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
- `find_source()` in `watch.py` prioritizes: movies → `sitefilme_com` first (direct m3u8), then `fsonline_one`; series → `fsonline_one` only. (Since 2026-11-25 `sitefilme_com` is parked, see Evidence: only `fsonline_one` is asked.) New tests in `test_watch.py::TestFindingATitle` cover this priority.
- Live-channel keys: Right and Left cycle from the channel playing (the first version indexed a list of configured channels, not the live ones) through an mpv input section held over the listener's own connection (mpv drops a section with the client that defined it), instead of `keybind` set to an empty command on removal. `_strip_emojis` no longer deletes CJK, Hangul or fullwidth text.
- News entries a feed edits come back once as `LIVE` items (`18a64e2`), now with a baseline on the first update time, at most one announcement an hour per entry, an unread item replaced in place, and the second sound only for items really added; undocumented before, README and F42 now say it.
- The hazard icons on the tray icon: one cached parser and drawer (there were two, the first dead), the thunderstorm and flood shapes drawn for the app (the ones in `18a64e2` were not MeteoAlarm's and not recognisable), a test that every path parses and stays inside its viewBox. With nothing unread the icon alternates between the temperature and a **white** hazard icon: the severity colour of `ac0c82d` is gone from the icon, and the severity shows in the rate only (README says so).
- Podcasts have their own accordion (F52): a source of `[media]` that is not a film, that a plugin understands and whose order is `newest` is listed under **Podcasts**, above Media, and only while one has an episode to watch; a new podcast episode only plays the sound. Discover and Track titles no longer keep an open popup open (they did, so the popup never closed after the last news item), the dismiss of the last news item now closes it as reading one does, and the accordions refresh whether or not the list collapses (the empty Media header is therefore bold, as it is with rows). A podcast that cannot be read shows under Podcasts only while another has something new.
- Discovery titles no longer expire: `media_cache.json` dropped what was not seen for 30 days, which also emptied Discover after a month with the app off or a chart unreadable. Now only a dismissal removes a title; the 5000-entry cap stays and drops the entries seen longest ago, which are the ones no chart lists (so none that Discover shows). A title that has left its chart is still kept but hidden, as before. Checked by the new test `test_media_cache.TestTheFile.test_an_entry_is_kept_however_long_ago_it_was_last_seen` (fails on the old code); an existing cache needs no migration (it only loses its age limit).
- New items in Media are silent: a new Discover title and a new episode of a series or a film no longer play the notification sound or open the popup (both called `on_new_items`; `_discovery_news` and `_on_media_new` are gone). A podcast's new episode still plays the sound alone (F52), a decision taken for the new-episode case: the request said "new items in media", which this reads as everything in the Media accordion. Checked by the changed tests in `test_ui_media` (`TestChecking`, `TestDiscoveryCheck`, `TestDiscoveryFromCharts`), each of which fails when `on_new_items` is put back at either call site (two deliberate breaks). Not checked: the tray icon, which `on_new_items` also refreshed; media never counted in the badge (README), so none is expected to change.
- The app no longer reads media plugins from `~/.config/flux-tray/media-plugins` (F51): `USER_MEDIA_PLUGIN_DIR` and `MEDIA_PLUGIN_DIRS` are gone and `app.py` gives `MediaSources` the repo's `addons/media-plugins` only. This is the change `docs/ARCHITECTURE.md` rule 4 said not to make without a migration; it was asked for, and there is nothing to migrate (no file of the person's is written or moved): a plugin that was only in that folder stops being loaded, and a copy of a built-in one there (the parked sitefilme one, say) no longer replaces or revives it. `MediaSources` itself still accepts several folders (its tests are unchanged in that part). Checked by running the real `FluxTray()` under Xvfb with a temporary `HOME` holding `~/.config/flux-tray/media-plugins/mine.py`: the commit before loaded `mine` among its drivers, this one does not (`archive`, `feed`, `fsonline_one`, `imdb-charts`, `yt-dlp` only); `test_mediasources.TestTheAppsPluginFolder` fails on the old `constants.py`. Not checked: whether the person's own copies in that folder differ from the repo's (they were not looked at); anything of theirs that only lived there needs to be moved into `addons/media-plugins`.
- A series played as a playlist is tracked all the way: only the first file of mpv's playlist was watched, so when mpv went on to the next episode by itself, that episode was never marked watched (its row stayed first in the list), the "playing" mark was cleared and an episode that finished downloading meanwhile was not appended to mpv's playlist. `_watch_local_playback` now asks `follow(path)` about the file that took the place of the one that ended and goes on with it when the UI claims it (`_follow_media_playback`: a downloaded, unwatched episode of the same source, and nothing clicked since); `clear_media_playing` takes the source and episode and clears only its own mark. The `on_playlist_advance` callback, which could only fire while the first file was still current, is removed. Checked with real mpv 0.37 under Xvfb and two 9-second files, through `play_media_file` and `mpv_append_playlist`: the old code reported the first file only, the new reports the first, is asked about the second and reports it too (about 16 s after mpv quits, the existing wait for an mpv that stopped answering); mpv's `path` went straight from one file to the next, with no gap, when sampled every 100 ms. Unit tests: `test_playback.TestWatchLocalPlayback` (4 new) and `test_ui_media.TestPlayingThroughAPlaylist`; each part of the fix, put back as it was, makes one of them fail. Not checked: your own series and your mpv config; whether `force-media-title` set by `mpv_append_playlist` renames the episode already playing (it sets the title on the current file; not changed here).
- A **Dismissed** tab, after Discover, to bring back a title dismissed by mistake (until now only editing `state.json` did): it lists the titles of the discovery cache whose key is in `media_discovery_seen` and that have no watch record, in the order of Discover, with the rows of Discover; a left click calls the same `_on_discovery_row_activated` as in Discover, so the title goes on the watch list and is in Track (the Track tab is now the fourth). The rule "dismissed and on no list" is what the data allows: a left click in Discover also writes the key to `media_discovery_seen`, so a title that was chosen, watched and removed (its film's source gone, its watch record with it) is listed there too; only a separate list of explicit dismissals would tell them apart, and it would not hold the dismissals made before. A title that left its chart is listed (`listed=False` entries are included here). The list is built once and kept until `_invalidate_discovery_cache`, like Discover's. Checked by `test_ui_media.TestTheDismissedTab` (6) and the accordion tests; each of three deliberate breaks (chosen titles listed, no watch-list call on a click, no invalidation) fails one; and the real app under Xvfb with openbox, a seeded cache, state and watch list: tabs Watch, Discover (1), Dismissed (2), Track (1); a real mouse click (`xdotool`) on the first Dismissed row left Dismissed (1) and made Track (2) with a searching record, screenshots looked at. Not checked: a long list (hundreds of rows), the rating and genre line of a row (no metadata in the run), the hover preview in that tab.
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
- `_search_fsonline_sitemap()` in `MediaMixin` was meant to run at the media check interval. It was never called by anything, would not have matched (a slug with its year against a title without) and did not save what it changed: removed on 2026-11-12. The plugin functions stay, unused by the app
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

2026-11-12: a right-click was slow, measured with a popup of realistic size under Xvfb (60 news items, 4000 seen entries, 8 media sources of 150 episodes, 600 cached titles = 1200 cache entries, 200 titles in the discovery list). A full rebuild of the popup took **5.6 s** (the first opening too). Two causes, both mine and the commit before it: `_load_metadata_cache` went over every cache entry at every call (the file was only parsed once), and `_get_discovery_items_cached` asked for the metadata of all 200 titles at every call, which the Discover tab makes once per row: about 40000 lookups of 1200 entries each. Now the pruned cache is the same dict until the file changes or an entry expires, and the discovery list is built once per change: the same rebuild takes **0.25 s**, the Discover tab's refresh 0.09 s. Also off the main loop now: Remove (cancelling a download waits up to 5 s; a film's file goes to the Trash).
- Fixed on the same day: download progress no longer reached the media rows (`_refresh_media_rows` only looked in the news list, and the rows are in the Watch tab); the Monitor button, the left click and Stop tracking now agree (the Monitor button did not dismiss the title or start a search, and Stop tracking sent the title straight back to Discover: its dismissal list was written and never read; the `monitoring` flag changed a label and nothing else, and is gone); Stop tracking of a followed series pauses its source (nothing more read or downloaded, files kept; its row says so); a feed's header went with its last item only after a rebuild; the sites that `find` asks are no longer named in `watch.py`: a plugin declares `FIND_PRIORITY` and `FIND_KINDS`; the plugin folder: the app reads `addons/media-plugins` and `~/.config/flux-tray/media-plugins` (a file there replaces a built-in one), `install.sh` copies nothing; CI now installs `requests` and `beautifulsoup4` and the plugin tests skip without them (three pushes went red on it); `suggestions.md` removed.
- Not changed, on purpose: the browser User-Agent for every request of `metadata.py` (its comment said it was for posters only), and TMDb stays off unless `tmdb=on`.

2026-11-24: Podcasts accordion and what keeps the popup open, under Xvfb (Python 3.14, PyGObject 3.50, GTK 3.24, no desktop):
- A real popup with news, a podcast and a series: Podcasts above Media, the podcast row only in Podcasts and the series only in Watch, both accordions open (screenshots looked at); 17 checks passed: left-click and right-click on a podcast row reach the media handlers, dismissing and reading the last news item close the popup with a podcast and a series waiting, a hand-opened popup with nothing unread shows both accordions, a new podcast episode plays the sound and leaves a closed popup closed, a new series episode opens it, a refresh nobody asked for does not close a popup that just opened, the Podcasts header and list go away when every episode is watched and come back when one arrives.
- Tests: pyflakes clean; 1817 tests pass in both modes (6 and 31 skipped). Each of four old rules was put back in turn (Discover and Track holding the popup, dismissing the last item keeping it open, a podcast episode opening the popup, no podcast recognised) and the new tests failed for each. The three golden popups were regenerated: the hidden Podcasts header and list are in them, and the feed of the `full` and `media_removed` scenarios is now under Podcasts.
- Not checked: the panel, focus and click-away behaviour of the real XFCE popup (XFCE-VALIDATION.md section 2 has the item), the hover details in the Podcasts list, and a long list of podcasts (the list grows to a third of the screen, then scrolls; only one row was drawn).

2026-11-24: memory grew from about 100 MB to 1 GB in 7-8 hours. Cause, found by running the app under Xvfb on Python 3.12 with 250 titles in the Discover list: every rebuild of the popup (a new item, a click on the icon with the popup closed) destroyed the window but not the rows of the Watch, Discover, Track and Podcasts lists, so each rebuild left its rows and its accordion alive, 8.2 MB per rebuild with 250 Discover titles (`refresh_list` alone did not grow). Fix: `MediaAccordion.dispose` and `PodcastAccordion.dispose` destroy their rows and `show_popup` calls them before it destroys the window.
- Measured: 20 rebuilds, 8156 KB each before, 42 KB each after; one accordion alive after, one more per rebuild before. The icon redraw (with a red alert pulsing, embedded in a tray), the timer ticks, 20 feed checks and 20 media checks do not grow.
- Tests: a new test that builds two popups with real rows and requires the first one's rows and accordions to be freed; it fails on the old code and passes now. pyflakes clean; the whole suite passes on Python 3.12 (1818 tests, 6 skipped) except the two `test_python_version` tests, which need 3.14, with the version guard taken out of a copy.
- Not checked: Python 3.14 and the stubbed mode (`tests/run_stubbed.py`), your real config (your plugins, OMDb, posters, feeds), and a run of hours on the desktop. Other growth I saw and did not fix: about 40 KB per popup rebuild and 2 KB per news item kept in `state.json`.

2026-11-25: Discover tab: the Monitor button is gone, and a left click always goes through the watch list.
- The Monitor button did what a left click on the row does, so it was removed (`_on_monitor_clicked` with it); a row of Discover has no button now. The left click and the right click are unchanged.
- A title that is already the page of a site (no IMDb id, or no plugin with `find`) used to become a source without a watch record, so a series of that kind was never in Track. It now gets a record with its source already set: a series is followed in Track until it is removed from Watch (or Stop tracking), a film is not tracked (it is in Watch once it is read).
- Not changed: a film leaves Track as soon as a site is found for it (`is_tracked`), not when its first read or download succeeds; between the two it is in neither tab, and a dynamic source whose first read fails is not shown anywhere. A series can only be removed from Watch from the right-click menu of a source added by a click ("Remove from list, mark seen, delete files"), which also trashes its files.
- Tests: four new or changed tests fail on the old code (a row with no button, a series from a site's page in Track, a film from a site's page on the list but not tracked, a followed series leaving Track when removed from Watch); one more pins the film-leaves-Track / series-stays behaviour of a search and passes on the old code too. Run on Python 3.14.6 under Xvfb. Not checked: the real popup on a desktop (clicking a row and watching it move between tabs), and any real site.

2026-11-25: A series can be started at a season and an episode (Track tab, *Start from…*).
- A `start` ({season, episode}) on the watch record and on the source entry, and `skipped` on the entry (the episodes the start marked as watched). `apply_start` (media.py) marks the numbered episodes before the start as watched at the first read and at every later one (`merge_episodes` calls it, so a late episode before the start is no news); moving or taking away the start gives back only `skipped`, so an episode that was really watched stays watched. Episodes without a season and an episode number are never skipped.
- `_set_series_start` keeps it on the record, puts it on the source when there is one and, in a thread, cancels the source's downloads (only when something was newly skipped) and plans again. `_search_watched` copies the record's current start to a source it has just found.
- The popover is a `Gtk.Popover` with two `Gtk.SpinButton` (as the timer's schedule uses) and uses the same `_launcher_open` guard as the media menu.
- Not changed: `merge_episodes` of a podcast (order `newest`) is unchanged when there is no start. A source listed by hand in `[media]` has no start (it would need a fourth field in the config line, a migration, or an entry in the Watch tab's menu): not built.
- Tests: 29 new or changed tests fail on the old code (checked with it restored). Run on Python 3.14.6 under Xvfb. Not checked: the popover on a real desktop (the new line in XFCE-VALIDATION section 2 lists what to try: arrows and typing in the spin buttons inside the popup, the popup staying open), and any real site's episode numbers.

2026-11-25: Watch tab: the row's tooltip no longer repeats the title's details.
- Hovering a Watch row showed two boxes: the preview beside the popup (poster, rating, plot) and the row's own tooltip, which began with the same details (`format_metadata_for_tooltip`). `media_row_view` no longer puts them in the tooltip; it keeps what the row cannot say (the episode, what a click does, the unwatched count, the last episode watched, and why a check or a download failed). The preview is unchanged; its text fallback for a title with no metadata is the same tooltip text.
- Not removed: `format_metadata_for_tooltip` in metadata.py (and `test_metadata.TestTheHoverText`) has no caller in the app now.
- Tests: the one that pinned the old tooltip now pins the new one and fails on the old code. Not checked: a real hover on a desktop.


2026-11-25: sitefilme.com is parked; fsonline.one is the only site asked for a title.
- `addons/media-plugins/sitefilme_com.py` is now `_sitefilme_com.py`: the loader has always skipped files that start with `_` or `.` (`test_mediasources.TestLoadingPlugins.test_files_that_are_not_plugins_are_ignored`), so nothing in the app changed to park it, and renaming it back brings it back. Its code is untouched except a note in its docstring. A copy of it in `~/.config/flux-tray/media-plugins/` would still be loaded: that folder is outside the repository and was not looked at.
- A title that a site was found to have, whose plugin is not loaded any more, is looked for again (`_release_lost_sources`, called by a full media check before the sources are listed; the pure test of what may be given up is `watch.holds_nothing`). The source is dropped with its queued downloads (an ongoing one is stopped first) and the record gets `source=None, checked=None`, so the same check asks the plugins that are loaded; a series keeps its start. A source with an episode on disk or really watched is left alone, to be watched (its row shows the "no source handler" error, as for any source no plugin understands), and nothing is done while any plugin failed to load. The app names no site: the test is whether the registry still has a driver for the source line.
- Not done: a source typed by hand into `[media]` (a `sitefilme_com:` line or a sitefilme address) is not on the watch list, so nothing looks for it again: its row shows the error until the line is removed. `config.conf` is not rewritten by the app.
- Tests: 24 new, in `test_ui_media.TestATitleWhosePluginIsGone`, `test_watch.TestASourceThatHoldsNothing` and `test_mediasources.TestTheBundledPlugins`; the first and the last fail on the old code (checked by taking the call out of `_check_media`, making the give-up test always true, ignoring plugin load errors, and by putting the plugin's old file name back). Run on Python 3.14 under Xvfb: the whole suite, real and stubbed, and pyflakes. The sandbox has no mpv, so the 6 tests that need it were skipped in the real run. Not checked: a real desktop, a real `media.json` with a title that sitefilme had found, and fsonline.one's own `find` for the titles that sitefilme had (the sites are out of the sandbox's reach).

2026-11-25: fsonline.one downloads fall back to the other servers the site lists.
- Seen on the owner's machine (output of a step-by-step run of the plugin's `resolve` pieces): for Primetime and Resident Evil, the page, the token, the server list and the subtitles all answered, the site listed two servers (mfw09.org and kaembed.net), and the one the plugin picks, kaembed.net, answered `404` for its embed page, so the download failed every time. The other server was never tried.
- `resolve` now tries the servers that have a link in turn (kaembed/vidmoly first, then the rest in the site's order) and takes the first that gives a stream; the error when none does names each host and its answer. `_pick_vidmoly` is no longer called (left in place).
- Not known: whether mfw09.org's embed page is read by `_extract_vidmoly_m3u8` (its markup was not seen), whether it has these two titles, and whether either server asks for something a plain request cannot give (the owner reports a puzzle to solve on the film page in a browser). A `404` is not what a bot check usually answers, so that is not shown to be the cause. The next failure's message will say what mfw09.org answered.
- Tests: 6 new (`test_fsonline.TestFsonlineResolve`, with the plugin's network functions replaced); 4 of them fail on the old `resolve`. Whole suite, real and stubbed, 1875 tests, pyflakes clean. Running `test_fsonline` alone from `tests/` makes `TestNormTitleWatchModule` fail to import `flux_tray` (it passes in the whole suite): that was already so and is left as it was.
