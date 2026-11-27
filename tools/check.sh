#!/bin/sh
# CI's checks (.github/workflows/ci.yml) plus tools/, in one command, with the output cut down to what a session needs:
# one line per step, the failing tests by name, and the "Ran N tests ... OK (skipped=K)" line. The full logs stay in
# /tmp/flux-check-*.log.
#
#   tools/check.sh          everything
#   tools/check.sh setup    only make .venv (Python 3.14 and the packages CI installs), then stop
#
# Not done here: installing the system libraries (xvfb, GTK 3 with its typelibs, cairo and girepository headers,
# ffmpeg; mpv, openbox, xdotool and imagemagick for the real-run checks): see docs/WORKFLOW.md.
# A step that cannot run is reported as NOT RUN and counts as a failure: a skipped check is not a passed one.
cd "$(dirname "$0")/.." || exit 2
PY=.venv/bin/python

if [ ! -x "$PY" ]; then
  command -v uv >/dev/null 2>&1 || { echo "uv is missing: pipx install uv (or pip install uv), then run this again" >&2; exit 2; }
  uv venv --python 3.14 .venv >/tmp/flux-check-venv.log 2>&1 &&
    uv pip install --python "$PY" "pygobject<3.51" pycairo feedparser pyflakes yt-dlp requests beautifulsoup4 >>/tmp/flux-check-venv.log 2>&1 ||
    { echo "could not make .venv (see /tmp/flux-check-venv.log)" >&2; tail -n 5 /tmp/flux-check-venv.log >&2; exit 2; }
  echo "== .venv made"
fi
[ "$1" = setup ] && exit 0

fail=0
step() {  # step LABEL COMMAND...: the output goes to a log; failures are named, a pass shows the closing line
  label=$1; shift
  log=/tmp/flux-check-$(printf %s "$label" | tr -c 'A-Za-z0-9' '-').log
  if "$@" >"$log" 2>&1; then
    printf '== ok      %-22s %s\n' "$label" "$(tail -n 3 "$log" | grep -E '^(Ran |OK|FAILED)' | tr '\n' ' ')"
  else
    fail=1
    printf '== FAILED  %-22s (log: %s)\n' "$label" "$log"
    grep -E '^(FAIL|ERROR): ' "$log" | head -n 20
    [ -n "$(grep -E '^(FAIL|ERROR): ' "$log")" ] || tail -n 15 "$log"
  fi
}

step compileall "$PY" -m compileall -q flux_tray tests tools
step pyflakes "$PY" -m pyflakes flux_tray tests tools flux-tray
step "shell syntax" sh -c 'sh -n install.sh && sh -n uninstall.sh && sh -n tools/check.sh'
if command -v xvfb-run >/dev/null 2>&1; then
  step "suite, real GTK" xvfb-run -a "$PY" -W ignore -m unittest discover -s tests
else
  echo "== NOT RUN suite, real GTK: no xvfb-run"; fail=1
fi
step "suite, GTK stubbed" "$PY" -W ignore tests/run_stubbed.py
command -v mpv >/dev/null 2>&1 || echo "note: no mpv here, so the tests that need it are skipped (they say 'skipped', not 'passed')"
[ "$fail" = 0 ] && echo "== all green" || echo "== RED"
exit "$fail"
