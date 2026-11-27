# Working on flux-tray

- `tools/check.sh` must be green: pyflakes, then the suite in both modes, `xvfb-run -a python3 -m unittest discover -s tests` and `python3 tests/run_stubbed.py`. The second only means something if the first ran under a display.
- A change that fixes something comes with a test that fails on the old code. Break the code on purpose with `tools/mutate.py` and watch the test fail.
- Code that starts a process, opens a socket, draws or touches media is also run for real (mpv, xvfb, cairo), not only mocked: mocked tests have missed real bugs there. How: [docs/WORKFLOW.md](docs/WORKFLOW.md).
- Do not rewrite code that works to change its style. Change structure when it buys something named, and one feature at a time, with the golden and parity tests green after each step.
- A new feature is a row in [docs/FEATURES.md](docs/FEATURES.md) with its tests; `tests/test_parity.py` fails otherwise. Deleting tests means editing the row in the same commit.
- If the popup is meant to look different, run the golden test, read the diff, then `FLUX_TRAY_UPDATE_GOLDEN=1 xvfb-run -a python3 -m unittest test_golden_popup` from `tests/`, and commit the new files with the change.
- Do not change `config.conf` syntax, the media plugin contract or the files under `~/.config/flux-tray` without a migration and a test for it.
- Say what was not checked, in the commit message. [docs/STATUS.md](docs/STATUS.md) changes only when what is verified, or what is known to be unverified, changes. A real-desktop result the owner reports ticks its item in [docs/XFCE-VALIDATION.md](docs/XFCE-VALIDATION.md), with the date.
- Working with an assistant (a session, where to look, what to hand back): [AGENTS.md](AGENTS.md).
