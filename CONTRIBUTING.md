# Working on void-tray

- The suite must pass in both modes, and the second only means something if the first ran under a display:
  `xvfb-run -a python3 -m unittest discover -s tests` and `python3 tests/run_stubbed.py`. Also `python3 -m pyflakes void_tray tests void-tray`.
- A change that fixes something comes with a test that fails on the old code. Run it against the old code to see it fail.
- Do not rewrite code that works to change its style. Change structure when it buys something named, and one feature at a time, with the golden and parity tests green after each step.
- A new feature is a row in [docs/FEATURES.md](docs/FEATURES.md) with its tests; `tests/test_parity.py` fails otherwise. Deleting tests means editing the row in the same commit.
- If the popup is meant to look different, run the golden test, read the diff, then `VOID_TRAY_UPDATE_GOLDEN=1 xvfb-run -a python3 -m unittest test_golden_popup` from `tests/`, and commit the new files with the change.
- Do not change `config.conf` syntax, the media plugin contract or the files under `~/.config/void-tray` without a migration and a test for it.
- Say what was not checked. Real-desktop results go in [docs/STATUS.md](docs/STATUS.md) under Evidence.
