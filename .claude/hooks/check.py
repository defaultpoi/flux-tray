#!/usr/bin/env python3
"""The checks that decide whether a change is done: pyflakes, then the suite in its two modes.

  check.py            run them; exit 0 if green, 1 if not (the report is on stderr)
  check.py --stop     as a Stop hook: exit 2 (which keeps Claude working, with the report) if red; says nothing
                      when nothing changed since the last green run, so questions and chat cost nothing

Environment: FLUX_PYTHON (default python3) is the interpreter the project runs on; FLUX_NO_XVFB=1 skips the real-GTK
mode where there is no xvfb-run (the stubbed mode then runs alone, and the report says so).
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys

ROOT = os.environ.get('CLAUDE_PROJECT_DIR') or subprocess.run(
    ['git', 'rev-parse', '--show-toplevel'], capture_output=True, text=True).stdout.strip() or os.getcwd()
PY = os.environ.get('FLUX_PYTHON', 'python3')
STAMP = os.path.join(ROOT, '.git', 'claude-last-green')


def tree_hash():
    """A hash of the working tree's changes, so an unchanged tree is not checked twice."""
    def git(*args):
        return subprocess.run(['git', *args], cwd=ROOT, capture_output=True).stdout
    digest = hashlib.sha256(git('rev-parse', 'HEAD') + git('diff', 'HEAD'))
    for name in git('ls-files', '--others', '--exclude-standard').decode().splitlines():
        digest.update(name.encode())
        try:
            with open(os.path.join(ROOT, name), 'rb') as f:
                digest.update(f.read())
        except OSError:
            pass
    return digest.hexdigest()


def run(label, command):
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    if result.returncode == 0:
        return None
    lines = (result.stdout + result.stderr).strip().splitlines()
    failing = [l for l in lines if l.startswith(('FAIL:', 'ERROR:')) or 'Error' in l[:40]]
    tail = failing[:15] or lines[-25:]
    return f'{label} FAILED:\n' + '\n'.join(tail)


def run_checks():
    problems, notes = [], []
    problems.append(run('pyflakes', [PY, '-m', 'pyflakes', 'flux_tray', 'tests', 'flux-tray']))
    if shutil.which('xvfb-run') and not os.environ.get('FLUX_NO_XVFB'):
        problems.append(run('suite with real GTK', ['xvfb-run', '-a', PY, '-W', 'ignore', '-m', 'unittest', 'discover', '-s', 'tests']))
    else:
        notes.append('the real-GTK mode was NOT run (no xvfb-run): it must pass before this is pushed')
    problems.append(run('suite stubbed', [PY, '-W', 'ignore', 'tests/run_stubbed.py']))
    return [p for p in problems if p], notes


def main():
    stop = '--stop' in sys.argv
    if stop:
        try:
            event = json.load(sys.stdin)
        except ValueError:
            event = {}
        if event.get('stop_hook_active'):
            return 0  # already continuing because of this hook: do not loop
    here = tree_hash()
    try:
        with open(STAMP) as f:
            if f.read().strip() == here:
                return 0
    except OSError:
        pass
    if stop and not subprocess.run(['git', 'status', '--porcelain'], cwd=ROOT, capture_output=True, text=True).stdout.strip():
        return 0
    problems, notes = run_checks()
    if problems:
        sys.stderr.write('The checks are red. Fix this before you finish; do not skip or weaken a test.\n\n' + '\n\n'.join(problems) + '\n')
        return 2 if stop else 1
    with open(STAMP, 'w') as f:
        f.write(here)
    for note in notes:
        sys.stderr.write(note + '\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
