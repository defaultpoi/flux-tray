# Status: what is verified, and what is known not to be

Read this before a task. It changes only when one of these facts changes. What a change was checked with goes in its commit
message (`git log`); older per-change evidence is in [HISTORY.md](HISTORY.md); what is open to do is in [BACKLOG.md](BACKLOG.md).

## Verified, and how

| What | How |
|---|---|
| Logic and widgets | The suite in two modes, real GTK under Xvfb and GTK stubbed: `tools/check.sh`. On 2026-11-27: 1893 tests in each mode (1 skipped with real GTK, 32 stubbed), Python 3.14.6, PyGObject 3.50.2, GTK 3.24, mpv 0.37.0. The same 1893 tests in each mode also pass on Python 3.12.3, the oldest the app accepts (system PyGObject 3.48.2, GTK 3.24.41, mpv 0.37.0; run 2026-11-27, 1 skipped with real GTK, 32 stubbed). CI runs both modes on every push, on Python 3.12 and 3.14 |
| The popup's look | `test_golden_popup` compares the widget tree of the real popup with the scenarios in `tests/golden/` |
| That a feature keeps its tests | `test_parity` against the rows of `docs/FEATURES.md` |
| That a fix is tested | its test fails on the old code (`tools/mutate.py` breaks the code on purpose); each commit says what was broken |
| Real tools | the tests that use yt-dlp, ffmpeg and mpv run the real binaries; the live-channel keys were run on mpv 0.37.0 and 0.41.0, `loadfile` with a start on 0.41.0, resume and a series played as a playlist on 0.37 (HISTORY) |
| Install scripts, Python 3.12 or newer | tests with a temporary `HOME`; an older Python is refused at import |

## Known not to be verified

- **The real desktop.** No item of [XFCE-VALIDATION.md](XFCE-VALIDATION.md) is ticked (0 of 47 on 2026-11-27): the panel's tray host, focus and click-away of the popup, real clicks, the Start from… popover, the hover previews, a real suspend, the XFCE Trash on another disk.
- **Real sites and services.** The sandbox cannot reach fsonline.one, IMDb, Plex, OMDb, TMDb or MeteoAlarm. HISTORY records runs against some of them (2026-11-10, and output the owner pasted on 2026-11-25); treat site behaviour as unverified unless the owner pasted output for it.
- **The app on a real desktop under Python 3.12.** Only the suite has run there (see above), not the app itself.
- **mpv other than 0.37 and 0.41**; a stream surviving the app's exit with streamlink; the licence of MeteoAlarm's wind and rain icons.
- **Hours of use.** Memory over a day on the real desktop. The leak behind 100 MB growing to 1 GB was found and fixed under Xvfb (20 popup rebuilds, 8156 KB each before, 42 KB after); other growth was seen and not fixed (BACKLOG).

## Code health, measured on 2026-11-27

Counted with `ast` and `wc`; the baseline's vulture, radon and coverage numbers are in HISTORY.

- `flux_tray/`: 12.5k lines of Python; `tests/`: 17.8k.
- `ui/media.py`: 2,862 lines, 23% of the app; `MediaMixin` has 94 methods, `MediaAccordion` 37. Nearly every media task lands there.
- Longest function: `create_metadata_tooltip` in `ui/media.py`, 224 lines. `app.py` sets about 87 attributes in `__init__`.
