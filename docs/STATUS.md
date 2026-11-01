# Status

Dates and versions of real runs go in the evidence section at the end, never in
the tests' place.

## What was checked, and how

| What | How | Result |
|------|-----|--------|
| The 1233 tests the code had at baseline commit `eb73c7d` | real GTK under Xvfb, and GTK stubbed | pass, before any change |
| Everything now | the same two modes, on Python 3.14.4 with PyGObject 3.50.2, GTK 3.24 | pass |
| Popup look and click hooks | `test_golden_popup`, two scenarios; identical on three runs and in the dark and default theme; a changed header and a changed colour digit both fail it | pass |
| Each hardening change | its new tests run against the old code | fail there, pass now |
| yt-dlp and ffmpeg | the real binaries in the tests that use them (ffmpeg 6.1) | pass |
| `install.sh`, `uninstall.sh` | tests with a temporary HOME | pass |
| Python 3.14 only | an older version number is refused at import with a message; the metadata says `>=3.14` | pass |
| CI on GitHub | `.github/workflows/ci.yml`: uv, Python 3.14, PyGObject built from source, both test modes; runs for commits `ae91f8a`, `36aed96` and `e50d623` (on `next` and on `main`) | pass |

## What was NOT checked

Everything in [XFCE-VALIDATION.md](XFCE-VALIDATION.md): a real panel and tray
host, a real mpv window, Twitch, YouTube, Open-Meteo, Meteoalarm and archive.org
answering, `xbps`, `topgrade` and `sudo` installs, suspend and resume, a 24-hour
run. The golden files were made on Ubuntu 24.04 with GTK 3.24 under Xvfb; they
leave out pixel sizes and icon names, but a different GTK major version may
differ in the classes it adds.

## What changed since the baseline

- Renamed to Flux Tray: package `flux_tray`, launcher `flux-tray`, class `FluxTray`, configuration directory `~/.config/flux-tray`, debug variable `FLUX_TRAY_DEBUG`. The names of the earlier versions, their configuration directory, their debug variable and the code that copied their files over are gone. Anything from an old directory has to be moved by hand once 
- Python 3.14 only: refused at import below it, `requires-python` in `pyproject.toml`, the tests and CI run on it.
- Links from feeds open only when they are http(s) addresses (`links.py`).
- A playlist address, and a variant a master playlist names, must be http(s) before it is read (`hls._fetch_text`). ffmpeg 6.1 already refuses a `file:` segment inside an http playlist, so no `-protocol_whitelist` was added.
- `config.conf` edits take turns and write through `write_atomic` (a weather write and a Mute click could lose one change; a failed write left `config.conf.tmp`).
- `_parse_default_gateway` no longer raises on a short line.
- Golden files for the popup, the parity matrix and its test, the real-desktop checklist, the install scripts.
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

- `yt-dlp` and `ffmpeg` downloads are not started in their own process group; whether quitting during a download leaves a child behind has not been checked on a desktop (XFCE-VALIDATION 4).
- A feed is fetched with `feedparser.parse(url)`: a 15-second socket timeout applies to each read (`socket.setdefaulttimeout`), but there is no limit on the size of a response or on the total time. Fetching with explicit limits would also change how redirects, gzip and encodings are handled, which cannot be tried against real sites here.
- `state.json` is written by `json.dump` of the whole state on every save; fine at the sizes in use.

## Evidence

(Nothing yet: no run on a real desktop.)
