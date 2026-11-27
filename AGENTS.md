# Start here (for an assistant)

Flux Tray: one owner's GTK3 tray app, Python 3.14 only, XFCE on Void Linux. A new chat needs no brief from them: read this
page, [CONTRIBUTING.md](CONTRIBUTING.md) (the rules), [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) (the design),
[docs/STATUS.md](docs/STATUS.md) and [docs/BACKLOG.md](docs/BACKLOG.md), then only what the task needs (the map below).
The history is `git log`; per-change evidence older than 2026-11-27 is in [docs/HISTORY.md](docs/HISTORY.md).

## Open a session

1. **Token.** It is in the Project instructions (the owner may also paste one): a fine-grained token for this repo only, Contents read and write.
   Cloning needs none (the repo is public); only a push and the GitHub API do. If there is none, or a push fails on it, ask the owner for a new one; do not work around it.
   It goes into a command as a header, never into a URL, a file, a commit, a log or a reply (the API takes `Authorization: Bearer`):
   `git clone https://github.com/defaultpoi/flux-tray.git`, and later `H="AUTHORIZATION: basic $(printf 'x-access-token:%s' "$TOKEN" | base64 -w0)"; git -c http.extraheader="$H" push origin HEAD:main`
2. **The clone.** `git config user.name defaultpoi; git config user.email defaultpoi@users.noreply.github.com; git config core.hooksPath .githooks`
   (the hook refuses a push that would drop commits from origin).
3. **Baseline.** `tools/check.sh` (the first run makes `.venv`; the system libraries are in [docs/WORKFLOW.md](docs/WORKFLOW.md)). Know it is green before you change anything.
4. **Before every push.** `git fetch`, then `git log HEAD..origin/main` must be empty; if not, stop and tell the owner. Never force-push.
   After the push, wait for CI and read it (WORKFLOW.md, "CI, read from outside"); do not report green before it is.

## Taking a task

A task is a line from the owner: a bug or a feature. Answer a question before doing anything; if it points at a real defect, fix it with a test and say so.

- **More than one reasonable reading of what the owner will see** (a name, a place, what a click does, what must not change):
  reply first with the reading you will build and the forks, each with a default, in five lines at most, and stop. One word settles it.
  A bug with one clear reading needs no such step. Anything over about 200 lines: write the plan into `docs/` and ask; a fresh chat implements it.
- **Several tasks in the same area** go in one session, one commit each. Unfinished work goes to a branch, with a line in BACKLOG.md saying what is done and where it stopped.
- **Scope.** Do what was asked. Do not rewrite working code for style (the first modular attempt was rewritten from scratch and lost half its features).
  A problem you find on the way goes into BACKLOG.md as `[found]`, not into the diff. If a feature is already in [docs/FEATURES.md](docs/FEATURES.md), extend it.
- **A change is done** when CONTRIBUTING.md's rules hold and: `tools/check.sh` is green; every fix or feature has a test that fails on the old code, proved with
  `python3 tools/mutate.py FILE --old 'exact text' --new 'broken text' --test test_x.TestY` (it prints CAUGHT or NOT CAUGHT and restores the file);
  anything that starts a process, opens a socket, draws or touches media was also run for real (WORKFLOW.md); README says what the owner sees, FEATURES.md has the row,
  BACKLOG.md has what you closed and what you found.
- **Where the evidence goes.** What you ran and saw goes in the commit message body, not in a document. `docs/STATUS.md` changes only when what is verified or what is known to be unverified changes.
  One topic per commit; the message says what changed and why and claims only what you ran (no test count you did not see).

## Where to look

| The task is in | Read |
|---|---|
| Media: the Watch, Discover, Track and Seen tabs, Podcasts, the watch list, Start from… | `flux_tray/ui/media.py` (`MediaAccordion` is the tabs, `PodcastAccordion` the podcasts, `MediaMixin` the checks, downloads and clicks), `watch.py` (watch list, `find`), `media.py` (episodes, `apply_start`), `media_cache.py` (the Discover cache), `mediasources.py` (the plugin loader). Tests: `test_ui_media`, `test_watch`, `test_media*`, `test_mediasources` |
| A site plugin (what a title or episode resolves to) | `addons/media-plugins/`: `fsonline_one.py`, `imdb_charts.py`; `_sitefilme_com.py` is parked (a leading `_` stops it loading). The contract is in README, "Media plugins". The sites are out of the sandbox's reach |
| Popup, rows, what keeps it open or closes it | `ui/popup.py` (`refresh_list`, `show_popup`), `tests/test_ui_popup.py`, `tests/golden/` (CONTRIBUTING.md says how to regenerate) |
| News feeds, mute and read-later rules | `ui/feeds.py`, `rules.py`, `state.py` (`state.json`) |
| Weather, alerts, the tray icon | `weather.py`, `ui/weather.py`, `ui/icon.py` |
| Live channels, mpv | `live.py`, `ui/live.py`, `playback.py`, `hls.py` |
| Timer and schedule; package updates | `schedule.py`, `ui/timer.py`; `updates.py`, `ui/updates.py` |
| `config.conf` and what it accepts | `config.py` and README, "Configuration" (its syntax and the files in `~/.config/flux-tray` change only with a migration and a test) |
| How the tests are built | `tests/facade.py` (one namespace `rt` over the package), `tests/helpers.py` (`TmpConfigCase` points config and state at a temp dir), `tests/run_stubbed.py` |
| GTK threads, mpv, ffmpeg, yt-dlp, feedparser, a memory leak | [docs/GOTCHAS.md](docs/GOTCHAS.md): read it before touching them |
| Why something is the way it is | `git log -S<word>`, then `grep -n <word> docs/HISTORY.md` |
| What a user sees, option by option | README (grep its headings; the layout of the code is at "Project layout") |
| A real-desktop check | [docs/XFCE-VALIDATION.md](docs/XFCE-VALIDATION.md): tick an item with the date only after the owner reports it |

## What the owner gets back

Short and direct, in this order:

1. What changed, and what you chose where the request left it open, so they can overrule it.
2. How to deploy: the owner pulls and restarts; give the line in the reply (the repo stays free of personal paths, names and site data; test data uses `example.com`).
   Anything they must run is one pasteable terminal command that creates the file and makes it executable. Metric units.
3. **Try this**: two to four clicks that show the change on the real desktop. They answer ✓ or ✗; a ✓ goes into the next commit message, and into XFCE-VALIDATION.md if it is one of its items.
4. What you ran and saw (versions, counts as printed), then what you could not check.
5. Questions and suggestions last, and at most one question.
