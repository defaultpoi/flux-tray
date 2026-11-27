# Running things in a session

What to do and where to look is in [AGENTS.md](../AGENTS.md); this page is the reference for the machinery.

## Checks

`tools/check.sh` runs what CI runs, plus `tools/`: one line per step, failing tests by name, the full logs in
`/tmp/flux-check-*.log`. The first run makes `.venv` with Python 3.14 (`tools/check.sh setup` does only that). On 2026-11-27, in
the sandbox, the whole script took about 40 s. It needs the system libraries, which the sandbox installs as root (there is no sudo):

```
apt-get update && apt-get install -y xvfb gir1.2-gtk-3.0 libgirepository1.0-dev libcairo2-dev pkg-config gcc ffmpeg mpv openbox xdotool imagemagick
```

A tool call is cut off after five minutes, and a background job started inside one is killed when the call ends. Start a long job
detached and poll it in short calls: `(setsid nohup tools/check.sh setup >/tmp/setup.log 2>&1 &)`.

One module: `cd tests && xvfb-run -a ../.venv/bin/python -m unittest test_network` (running
`unittest tests/test_x.py` from the root fails on the facade import).

Tests that need `mpv` skip when it is missing, so a run without it says "skipped",
not "passed". A fix comes with a test that fails on the old code: run the test
against the old code and watch it fail.

Code that starts a process, opens a socket, draws, or touches time or media is also
run for real, because mocked tests have missed real bugs in mpv, ffmpeg, yt-dlp and
the GTK popup. The earlier harness for that: build `FluxTray()` with a temporary
`HOME` (seeded `config.conf`, `state.json`, an mpv config with
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
It does reach the Ubuntu mirrors (`apt-get`), PyPI and the GitHub downloads `uv` uses for Python 3.14, which is why `tools/check.sh` can run in full here.
