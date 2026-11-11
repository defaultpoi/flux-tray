# flux-tray

GTK3 tray app, Python 3.14. The rules are in @CONTRIBUTING.md and the design in @docs/ARCHITECTURE.md: read both before you change code.

## A change is done when
1. `python3 -m pyflakes flux_tray tests flux-tray` prints nothing.
2. `xvfb-run -a python3 -m unittest discover -s tests` and `python3 tests/run_stubbed.py` both pass. A hook runs them when you stop and before a commit: fix what it reports, never work around it (no `--no-verify`, no deleting or loosening a test).
3. Every fix or feature has a test that fails on the old code. Prove it with `/prove-it`: break the code on purpose and watch the test fail.
4. Code that starts a process, opens a socket or draws is run for real (mpv, xvfb, cairo), not only mocked.
5. New behaviour is documented: README, a row in `docs/FEATURES.md`, and a line in `docs/STATUS.md` for what was and was not checked.

## Git
- Before starting and before pushing: `git fetch`, then `git log HEAD..origin/main`. If origin has commits you do not have, stop and tell me. Never force-push.
- One topic per commit. The message says what changed and why, and claims only what you ran (no test counts you did not see).
- Never write a token or key into a file, a commit or `.claude/`. If a push needs credentials, ask me.

## Scope
- Do what was asked. Do not refactor working code for style. Report other problems you find instead of fixing them silently.
- If a feature already exists in `docs/FEATURES.md` or on origin, extend it; do not build a second one.
- For anything over about 200 lines, make a plan and ask before you write code.

## End every report with
What you ran and what you saw, then what you could not check.
