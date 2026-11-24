# Working on flux-tray with an assistant

The repo is the handoff. A new chat needs no brief: it reads
[CONTRIBUTING.md](../CONTRIBUTING.md) (the rules), [ARCHITECTURE.md](ARCHITECTURE.md)
(the design), [STATUS.md](STATUS.md) (what was checked, what was not, what is open)
and `git log`. Whatever a later session must know goes into one of those files in the
same commit as the change, never only into a message. Unfinished work goes to a branch
with a note in STATUS.md saying what is done, what is left and where it stopped;
a decision that has a reason gets the reason in one line.

One topic per chat works best. A long chat gets slow because of everything it has
accumulated (long tool output above all): start a new one when the topic changes.
For anything over about 200 lines, one chat makes the plan and commits it to `docs/`,
and a fresh chat implements it.

## A session

1. Clone. A fresh sandbox has no git identity: set `user.name` and `user.email` in
   the clone to what the existing commits use (`git log -1 --format='%an <%ae>'`).
   Before starting and before pushing, `git fetch` and `git log HEAD..origin/main`;
   if origin has commits you do not have, stop and say so. Never force-push.
2. Credentials. The owner pastes a short-lived token for the session. It is passed
   per command (`git -c http.extraheader="AUTHORIZATION: basic $(printf
   'x-access-token:%s' "$TOKEN" | base64 -w0)" push origin HEAD:main`; the API takes
   `Authorization: Bearer`) and never lands in a remote URL, a file, a commit, a log
   or a reply. The owner revokes it afterwards. An authentication error is reported
   as one.
3. Change, check (below), commit, push, wait for CI.
4. Report: what was run and what was seen, then what could not be checked.

## Checks

The same as CI (`.github/workflows/ci.yml`):

```
sudo apt-get install -y xvfb gir1.2-gtk-3.0 libgirepository1.0-dev libcairo2-dev pkg-config gcc ffmpeg
uv venv --python 3.14 .venv
uv pip install --python .venv/bin/python "pygobject<3.51" pycairo feedparser pyflakes yt-dlp requests beautifulsoup4

.venv/bin/python -m compileall -q flux_tray tests
.venv/bin/python -m pyflakes flux_tray tests flux-tray
sh -n install.sh && sh -n uninstall.sh
xvfb-run -a .venv/bin/python -m unittest discover -s tests
.venv/bin/python tests/run_stubbed.py
```

One module: `cd tests && xvfb-run -a python -m unittest test_network` (running
`unittest tests/test_x.py` from the root fails on the facade import).

Tests that need `mpv` skip when it is missing, so a run without it says "skipped",
not "passed". A fix comes with a test that fails on the old code: run the test
against the old code and watch it fail.

Code that starts a process, opens a socket, draws, or touches time or media is also
run for real, because mocked tests have missed real bugs in mpv, ffmpeg, yt-dlp and
the GTK popup. The earlier harness for that: build `FluxTray()` with a temporary
`HOME` (seeded `config.conf`, `state.json`, `media-plugins/`, an mpv config with
`ao=null`), drive it from a thread with `GLib.idle_add` helpers, run under
`xvfb-run -a -s '-screen 0 1368x768x24'` with `openbox`, screenshot with
`import -window root`, click with `xdotool` at coordinates from
`widget.translate_coordinates`. It needs `mpv openbox xdotool imagemagick`.

## CI, read from outside

The log of a job cannot be read from outside, so CI prints each failing test as an
annotation: `GET /repos/<owner>/<repo>/commits/<sha>/check-runs`, then
`/check-runs/<id>/annotations`. Poll `actions/runs?head_sha=<sha>` for the result.
A sandbox tool call is cut off after five minutes, so poll in short calls.

CI's runner can have a newer library than the sandbox. A failure that does not
reproduce locally may be that: `GLib.unix_signal_add` was missing there, which made
`mock.patch.object` raise before four tests ran (hide the attribute to reproduce it).

## What the sandbox cannot reach

Package mirrors, GitHub and a few similar hosts only. archive.org, YouTube, Plex,
the streaming sites behind the media plugins and the real desktop are out of reach:
anything about them is unverified until the owner pastes output from their machine.
Design diagnostics for that so they mask URLs and tokens.

## What the owner expects of a reply

- Short and direct: what changed, how to deploy it, an honest list of what was not
  verified. Behaviour choices that were made are stated, so they can be overruled.
- Metric units. Anything the owner must run is one pasteable terminal command that
  creates the file and makes it executable, not "save this file, then chmod".
- A question is answered before anything is done; when it points at a real defect,
  fix it with a test and say so. Questions and suggestions go at the end.
- The repo stays location-agnostic: no personal paths, names or site data in code,
  tests or docs (test data uses `example.com`). The deploy line (pull, restart) is
  therefore given in the reply and not kept here.

## Rules for the work

- One topic per commit. The message says what changed and why, and claims only what
  was run.
- Do what was asked. Do not rewrite working code for style (the first modular attempt
  was rewritten from scratch and lost half its features). Report other problems found
  instead of fixing them silently.
- If a feature exists in [FEATURES.md](FEATURES.md) or on origin, extend it; do not
  build a second one.
- New behaviour is documented: README, a row in FEATURES.md, and a line in STATUS.md
  for what was and was not checked.

## Gotchas found the hard way

- `Path.with_suffix` replaces everything after the last dot, so `Dr. House - S01E01`
  became `Dr.ts`. Build file names by string concatenation.
- A CSS stylesheet with one unknown property is dropped whole (look for "Failed to
  apply CSS styles" in the log). A `Gtk.Popover` cannot leave its window.
  `set_no_show_all` blocks `show_all` on that widget. `Gdk` is main-thread only:
  workers read sizes the main thread stored. A `Gio.FileMonitor` must be kept
  referenced.
- ffmpeg's `-progress` `out_time_ms` is in microseconds. A reader that does not
  drain ffmpeg's output stalls ffmpeg. ffprobe can fail on a stream ffmpeg downloads
  fine. yt-dlp's `--print` makes it quiet unless `--progress` is given.
- `feedparser` resolves a relative `guid` against the feed URL. JSON object keys
  become strings.
- Thread tests: never release a blocked worker until the other side is provably
  waiting (an early release made one test fail one run in eight). Use a generous
  `threading.Timer` or a sequential test, and make poll intervals patchable so tests
  stay fast.
- Mock-heavy UI tests are brittle, and most failures after feature work are stub
  fixtures (stubs borrow real methods: `class Stub: method = rt.FluxTray.method`).
  New logic gets pure tests; UI gets a few behaviour tests plus a real-GTK run.
