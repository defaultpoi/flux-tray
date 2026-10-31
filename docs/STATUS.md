# Status

Last updated at the commit that added this file. Dates and versions of real
runs go in the evidence section below, never in the tests' place.

## What was checked, and how

| What | How | Result |
|------|-----|--------|
| The 1233 tests of void-tray `eb73c7d` | real GTK under Xvfb, and GTK stubbed | pass, before any change |
| Everything now (see `git log` for the count) | the same two modes | pass |
| Popup look and click hooks | `test_golden_popup`, two scenarios; identical on three runs and in the dark and default theme; a changed header and a changed colour digit both fail it | pass |
| Each hardening change | its new tests run against the old code | fail there, pass now |
| yt-dlp and ffmpeg | the real binaries in the tests that use them (ffmpeg 6.1) | pass |
| `install.sh`, `uninstall.sh` | tests with a temporary HOME | pass |

## What was NOT checked

Everything in [XFCE-VALIDATION.md](XFCE-VALIDATION.md): a real panel and tray
host, a real mpv window, Twitch, YouTube, Open-Meteo, Meteoalarm and archive.org
answering, `xbps`, `topgrade` and `sudo` installs, suspend and resume, a 24-hour
run. The golden files were made on Ubuntu 24.04 with GTK 3.24 under Xvfb; they
leave out pixel sizes and icon names, but a different GTK major version may
differ in the classes it adds.

## What changed relative to void-tray `eb73c7d`

- Links from feeds open only when they are http(s) addresses (`links.py`).
- A playlist address, and a variant a master playlist names, must be http(s) before it is read (`hls._fetch_text`). ffmpeg 6.1 already refuses a `file:` segment inside an http playlist, so no `-protocol_whitelist` was added.
- `config.conf` edits take turns and write through `write_atomic` (a weather write and a Mute click could lose one change; a failed write left `config.conf.tmp`).
- `_parse_default_gateway` no longer raises on a short line.
- Golden files for the popup, the parity matrix and its test, the real-desktop checklist, the install scripts.

## Taken from flux-tray, and what was left

Taken as ideas, re-done against void-tray's code with tests: validating
addresses before using them, one atomic writer, install and uninstall scripts,
the checklist for a real desktop, the status and features documents.

Not taken, deliberately:

- Its task manager, scheduler and process supervisor. void-tray's timers and threads have been verified in use, and no defect was found that they would fix; replacing them would touch every feature. If you want them, the way is one feature at a time behind the golden and parity tests, starting with the downloads (below).
- Its GUI editing of sources, weather setup and launcher entries, its `~/.config/flux-tray` paths and `plugin:NAME:SOURCE` plugin syntax: they change how the app looks and how your files and plugins are read.
- Its dropping of archive.org and of the rss-tray migration.

## Open items found while comparing, not changed

- `yt-dlp` and `ffmpeg` downloads are not started in their own process group; whether quitting during a download leaves a child behind has not been checked on a desktop (XFCE-VALIDATION 4).
- A feed is fetched with `feedparser.parse(url)`: a 15-second socket timeout applies to each read (`socket.setdefaulttimeout`), but there is no limit on the size of a response or on the total time. flux-tray fetches with its own limits and hands bytes to feedparser; that would also change how redirects, gzip and encodings are handled, which cannot be tried against real sites here.
- `state.json` is written by `json.dump` of the whole state on every save; fine at the sizes in use.

## Evidence

(Nothing yet: no run on a real desktop.)
