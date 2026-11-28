# Backlog

The owner's bugs and features, and what assistants found and did not change. One line each. A session takes the items of one area
together, deletes what it closed (the commit says what was done) and adds what it found. Marks: **[owner]** asked for by the owner;
**[found]** an assistant found it on the way and left it; **[proposed]** suggested to the owner, not asked for. Details of the older
ones are in [HISTORY.md](HISTORY.md) (grep a word of the line).

## Asked, open

- [owner] Start a series from a season and episode when it is configured by hand in `[media]`: it has no `start` (the Track row's "Start from…" covers series added by a click). A right-click entry in the Watch tab, or a fourth field in the config line with a migration.

## Found, not changed

Behaviour:
- [found] Collapsing the Media accordion after the last news item was read leaves the empty popup open (it closes on the next right-click on an empty part, Escape or tray click, or the next rebuild that finds nothing unread).
- [found] A film leaves Track as soon as a site is found for it, not when its first read or download works: until then it is in neither tab, and a source whose first read fails is shown nowhere.
- [found] A series added by a click leaves Watch only through its right-click menu, "Remove from list, mark seen, delete files", which also trashes its files.
- [found] A source typed by hand into `[media]` whose plugin is gone (a `sitefilme_com:` line, say) is not on the watch list, so nothing looks for it again: its row shows the "no source handler" error until the line is removed. The app does not rewrite `config.conf`.
- [found] A title only a parked site had, or one that fsonline.one names by its Romanian title, is never found (its address pattern is `<title>-<year>-online-subtitrat`).
- [found] fsonline's feed is read for the last 24 hours only: a check more than a day after the last (the app off or suspended) misses what appeared in between.
- [found] The quality badge is green for `HD` and red for anything else, so `BLURAY` and `WEBRIP`, which fsonline also reports, are red.
- [found] Downloads by `yt-dlp` and `ffmpeg` are not started in their own process group: whether quitting during one leaves a child behind is unchecked on a desktop (XFCE-VALIDATION, section 4).
- [found] A feed is fetched with `feedparser.parse(url)`: 15 seconds per read, but no limit on the size of a response or on the total time. Limits would change how redirects, gzip and encodings are handled, which cannot be tried against real sites from the sandbox.
- [found] About 40 KB of memory per popup rebuild and 2 KB per news item kept in `state.json` still accumulate.
- [found] The Twitch and YouTube checkers differ: only a failed Twitch check notes a request failure for the connectivity logic. Intended?
- [found] fsonline.one: whether mfw09.org's embed page is read by `_extract_vidmoly_m3u8` is not known; the next failure's message says what it answered (needs the owner's output).
- [found] `tests/test_links.py` only tries `file:///...`: with a scheme check that also accepted `file`, the suite still passes, though `file://host/path` has a host name (found 2026-11-27 with `tools/mutate.py`).
- [found] Running `test_fsonline` alone from `tests/` makes `TestNormTitleWatchModule` fail to import `flux_tray`; it passes in the whole suite.

Cleanup:
- [found] `_launcher_open` (set by the Launch list, the feed menu and the media menus) had one reader, the popup's focus-out handler, which is gone: nothing reads it now, only tests assert it is set.
- [found] No caller: `format_metadata_for_tooltip` in `metadata.py` (and `test_metadata.TestTheHoverText`), `_pick_vidmoly` in `fsonline_one.py`, and its `fetch_new_episodes` and `fetch_new_movies` (the sitemap check was never wired in).
- [found] Internal names still say "dismissed" (`get_dismissed_items`, `dismissed_listbox`, `TestTheDismissedTab`) for what the Seen tab lists.
- [found] `schedule.load_schedule_settings` still reads the older single-schedule keys of `[schedule]`.
- [found] Least tested and most tangled (as measured at the baseline): `refresh_list` (113 lines, rank F) and `on_row_activated` in `ui/popup.py`; `ui/timer.py`, `ui/icon.py`, `ui/live.py` and `ui/weather.py` at 66 to 70% coverage; `download_hls`, `download_ytdlp`, `list_ytdlp`, `load_state` (rank D).

For the owner to decide:
- [found] The tray icon no longer shows an alert's severity colour (the severity shows in the blink rate only): wanted?

## Proposed

- [proposed] G1line through `https://r.jina.ai/` when the direct read fails (the way the imdb-charts plugin asks the proxy for IMDb): add it only if the owner's log shows g1line.ro turning the app's request away.
- [proposed] `flux-tray --version` and `flux-tray --report`: print the commit, memory use, the number of live accordions, the counts in `media.json` and the last 50 log lines with URLs masked, so a bug report says what is running. Today the app prints no version.
- [proposed] A nightly soak in CI: the app under xvfb with fake feeds and fast timers for about 30 minutes, failing if memory keeps climbing. The 100 MB to 1 GB leak showed only with a full list and hours of use.
- [proposed] Split `ui/media.py`: plan in a chat of its own, then one extraction per commit with the golden and parity tests green after each.
