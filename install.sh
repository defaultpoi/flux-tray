#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
APP_DIR="$HOME/.local/lib/flux-tray"
BIN_DIR="${XDG_BIN_HOME:-$HOME/.local/bin}"
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}"
APPLICATIONS_DIR="$DATA_DIR/applications"
AUTOSTART_DIR="$CONFIG_DIR/autostart"
AUTOSTART_MODE=keep

usage() {
    printf 'Usage: %s [--autostart|--no-autostart]\n' "$0"
}

case "${1:-}" in
    "") ;;
    --autostart) AUTOSTART_MODE=enable ;;
    --no-autostart) AUTOSTART_MODE=disable ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
esac

if [ "$#" -gt 1 ]; then
    usage >&2
    exit 2
fi

if ! command -v python3 >/dev/null 2>&1; then
    printf 'Error: python3 is required.\n' >&2
    exit 1
fi

if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 14) else 1)'; then
    printf 'Error: Flux Tray requires Python 3.14 or newer.\n' >&2
    exit 1
fi

if ! python3 -c 'import gi, feedparser; gi.require_version("Gtk", "3.0"); from gi.repository import Gtk' >/dev/null 2>&1; then
    printf 'Error: GTK3, PyGObject and feedparser must be installed for system Python.\n' >&2
    printf 'See README.md for the required and optional Void packages.\n' >&2
    exit 1
fi

[ -d "$SCRIPT_DIR/src/flux_tray" ] || {
    printf 'Error: run this script from a Flux Tray source checkout.\n' >&2
    exit 1
}

mkdir -p "$APP_DIR" "$BIN_DIR" "$APPLICATIONS_DIR"
rm -rf "$APP_DIR/flux_tray"
cp -a "$SCRIPT_DIR/src/flux_tray" "$APP_DIR/"

python3 - "$APP_DIR" "$BIN_DIR/flux-tray" "$SCRIPT_DIR/flux-tray.desktop" "$APPLICATIONS_DIR/flux-tray.desktop" <<'PY'
from pathlib import Path
import shlex
import sys

app_dir, launcher, desktop_source, desktop_target = sys.argv[1:]
Path(launcher).write_text(
    "#!/bin/sh\n"
    f"APP_LIB_DIR={shlex.quote(app_dir)}\n"
    'export PYTHONPATH="$APP_LIB_DIR${PYTHONPATH:+:$PYTHONPATH}"\n'
    'exec python3 -m flux_tray "$@"\n',
    encoding="utf-8",
)
Path(launcher).chmod(0o755)

desktop = Path(desktop_source).read_text(encoding="utf-8")
exec_path = launcher.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%")
desktop = desktop.replace("Exec=flux-tray", f'Exec="{exec_path}"')
Path(desktop_target).write_text(desktop, encoding="utf-8")
PY

if [ "$AUTOSTART_MODE" = enable ]; then
    mkdir -p "$AUTOSTART_DIR"
    cp "$APPLICATIONS_DIR/flux-tray.desktop" "$AUTOSTART_DIR/flux-tray.desktop"
elif [ "$AUTOSTART_MODE" = disable ]; then
    rm -f "$AUTOSTART_DIR/flux-tray.desktop"
fi

printf 'Flux Tray installed.\n'
printf 'Launcher: %s/flux-tray\n' "$BIN_DIR"
printf 'Desktop entry: %s/flux-tray.desktop\n' "$APPLICATIONS_DIR"
if [ -f "$AUTOSTART_DIR/flux-tray.desktop" ]; then
    printf 'Autostart: enabled\n'
else
    printf 'Autostart: disabled (use --autostart to enable)\n'
fi
