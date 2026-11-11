---
name: prove-it
description: Prove that a change to flux-tray really works before calling it done: run the checks, break the code on purpose to see each new test fail, run process/socket/drawing code for real, check the docs, and report what was not checked. Use when a fix or feature is finished, or when asked whether a change is really done.
---

# Prove it

A test that cannot fail proves nothing, and a change that was only mocked is not checked. Do these in order and report what you saw, not what you expect.

1. **List the behaviours** the change adds or fixes: one line each, as "when X, Y". These are what you prove.
2. **Run the checks:** `python3 .claude/hooks/check.py`. It must exit 0. Do not go on while it is red.
3. **Break each behaviour on purpose.** For every line of step 1, find the smallest code change that makes it false and run:
   `python3 .claude/skills/prove-it/mutate.py FILE --old 'exact text' --new 'broken text' --test test_module.TestClass`
   It restores the file itself and says `CAUGHT` or `NOT CAUGHT`. On `NOT CAUGHT` the test does not cover the behaviour: strengthen it, then repeat. A fix with no test that fails on the old code is not done.
4. **Run it for real** if it starts a process, talks over a socket, reads a real file format or draws: mpv (`mpv --version` first, and say which version), `xvfb-run`, cairo, a real directory. A mock only shows the code calls what you told it to call. Put what you ran, with versions, under Evidence in `docs/STATUS.md`.
5. **Docs:** README says what the user sees, `docs/FEATURES.md` has a row naming the new tests (`tests/test_parity.py` enforces it), `docs/STATUS.md` says what was and was not checked.
6. **Read your own diff** with `git diff origin/main...`: duplicated functions, unused names, a write that is not `write_atomic`, network or disk work on the GTK thread, state changed without its lock, a claim in a comment or message that the code does not make true.

## Report

| Behaviour | Test | Broken on purpose: result |
|---|---|---|

Then **Not checked:** everything you could not run, and why. If the list is empty, say what you ran to be sure.
