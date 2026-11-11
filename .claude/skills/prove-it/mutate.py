#!/usr/bin/env python3
"""Breaks a file on purpose, runs tests, restores the file, and says whether the tests noticed.

  mutate.py FILE --old 'exact text' --new 'broken text' --test test_x.TestY [--test ...] [--all]

`old` must occur exactly once in FILE (or pass --all to break every occurrence). Exit 0 when the tests FAILED
(the break was caught), 1 when they passed (it was not), 2 when it could not be tried.
Environment: FLUX_PYTHON (default python3); xvfb-run is used when it exists.
"""
import argparse
import hashlib
import os
import shutil
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('file')
    parser.add_argument('--old', required=True)
    parser.add_argument('--new', required=True)
    parser.add_argument('--test', action='append', required=True, help='a test module, class or method, as unittest names it')
    parser.add_argument('--all', action='store_true')
    args = parser.parse_args()

    root = os.environ.get('CLAUDE_PROJECT_DIR') or subprocess.run(
        ['git', 'rev-parse', '--show-toplevel'], capture_output=True, text=True).stdout.strip() or os.getcwd()
    path = os.path.abspath(args.file)
    with open(path, encoding='utf-8') as f:
        original = f.read()
    count = original.count(args.old)
    if count == 0 or (count > 1 and not args.all):
        print(f'cannot try: the old text occurs {count} times in {args.file} (it must occur once, or use --all)')
        return 2
    before = hashlib.sha256(original.encode()).hexdigest()
    command = [os.environ.get('FLUX_PYTHON', 'python3'), '-W', 'ignore', '-m', 'unittest', *args.test]
    if shutil.which('xvfb-run'):
        command = ['xvfb-run', '-a', *command]
    try:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(original.replace(args.old, args.new) if args.all else original.replace(args.old, args.new, 1))
        result = subprocess.run(command, cwd=os.path.join(root, 'tests'), capture_output=True, text=True)
    finally:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(original)
    if hashlib.sha256(open(path, 'rb').read()).hexdigest() != before:
        print('WARNING: the file was not restored exactly: check git diff')
        return 2
    lines = [l for l in (result.stderr + result.stdout).strip().splitlines() if l.strip()]
    last = lines[-1] if lines else 'no output'
    if result.returncode != 0:
        print(f'CAUGHT: the tests failed with the break in place ({last})')
        return 0
    print(f'NOT CAUGHT: the tests still pass with the break in place ({last}). They do not cover this behaviour.')
    return 1


if __name__ == '__main__':
    sys.exit(main())
