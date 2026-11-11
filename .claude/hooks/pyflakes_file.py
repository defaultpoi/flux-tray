#!/usr/bin/env python3
"""PostToolUse on Edit/Write: pyflakes on the file that was just changed; what it finds goes back to Claude (exit 2)."""
import json
import os
import subprocess
import sys

try:
    event = json.load(sys.stdin)
except ValueError:
    sys.exit(0)
path = (event.get('tool_input') or {}).get('file_path') or ''
if not path.endswith('.py') or not os.path.exists(path):
    sys.exit(0)
result = subprocess.run([os.environ.get('FLUX_PYTHON', 'python3'), '-m', 'pyflakes', path], capture_output=True, text=True)
if result.returncode != 0 and (result.stdout or result.stderr).strip():
    sys.stderr.write('pyflakes found this in the file you just changed:\n' + (result.stdout + result.stderr).strip() + '\n')
    sys.exit(2)
