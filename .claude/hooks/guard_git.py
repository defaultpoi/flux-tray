#!/usr/bin/env python3
"""PreToolUse on Bash: stops the git mistakes that cost work.

  git push --force / -f          refused (use --force-with-lease after fetching, and ask the person)
  git push                       refused when origin has commits that HEAD lacks (after a fetch)
  git commit --no-verify / -n    refused
  git commit                     refused when staged lines hold a token or key, or the checks are red

Exit 2 sends the reason to Claude and stops the command.
"""
import json
import os
import re
import shlex
import subprocess
import sys

ROOT = os.environ.get('CLAUDE_PROJECT_DIR') or os.getcwd()
SECRET = re.compile(r'github_pat_[A-Za-z0-9_]{20,}|gh[pousr]_[A-Za-z0-9]{30,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----|sk-[A-Za-z0-9]{32,}')


def git(*args):
    return subprocess.run(['git', *args], cwd=ROOT, capture_output=True, text=True)


def refuse(message):
    sys.stderr.write(message + '\n')
    sys.exit(2)


try:
    command = (json.load(sys.stdin).get('tool_input') or {}).get('command') or ''
except ValueError:
    sys.exit(0)

# every git command in the line (`a && git push`, `git -C x commit`)
for part in re.split(r'&&|\|\||;|\n', command):
    try:
        words = shlex.split(part)  # a quoted message is one word, so '-n' inside it is not an option
    except ValueError:
        words = part.split()
    if 'git' not in words:
        continue
    words = words[words.index('git') + 1:]
    while words and words[0].startswith('-'):  # git -C dir ...
        words = words[2:] if words[0] in ('-C', '-c') else words[1:]
    verb, rest = (words[0] if words else ''), words[1:]
    if verb == 'push':
        if any(w in ('-f', '--force') or w.startswith('--force=') or (w.startswith('+') and ':' not in w[:1]) for w in rest):
            refuse('Refused: no force pushes. A forced push replaces what is on origin, and the work on it is lost '
                   'unless someone has it. Fetch, look at `git log HEAD..origin/<branch>`, merge or rebase, then push normally, '
                   'or ask the person.')
        git('fetch', '--quiet')
        branch = git('rev-parse', '--abbrev-ref', 'HEAD').stdout.strip()
        behind = git('rev-list', '--count', f'HEAD..origin/{branch}')
        if behind.returncode == 0 and behind.stdout.strip() not in ('', '0'):
            log = git('log', '--oneline', f'HEAD..origin/{branch}').stdout
            refuse(f'Refused: origin/{branch} has {behind.stdout.strip()} commit(s) you do not have:\n{log}'
                   'Look at them, merge or rebase, run the checks, then push. Tell the person.')
    elif verb == 'commit':
        if any(w in ('--no-verify', '-n') or (w.startswith('-') and not w.startswith('--') and 'n' in w[1:]) for w in rest):
            refuse('Refused: do not commit with --no-verify. Make the checks pass.')
        added = [l[1:] for l in git('diff', '--cached', '-U0').stdout.splitlines() if l.startswith('+') and not l.startswith('+++')]
        if any(SECRET.search(l) for l in added):
            refuse('Refused: a staged line looks like a token or private key. Take it out (and tell the person if it was a real one: it must be revoked).')
        check = subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'check.py')],
                               capture_output=True, text=True)
        if check.returncode != 0:
            refuse('Refused: the checks are red, so this is not ready to commit.\n' + check.stderr)
sys.exit(0)
