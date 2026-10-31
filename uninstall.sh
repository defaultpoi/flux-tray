#!/bin/sh
# Removes what install.sh made. Leaves ~/.config/void-tray alone.
set -eu

here=$(cd "$(dirname "$0")" && pwd -P)
link="${HOME}/.local/bin/void-tray"
entry="${XDG_CONFIG_HOME:-${HOME}/.config}/autostart/void-tray.desktop"

if [ -L "$link" ] && [ "$(readlink "$link")" = "$here/void-tray" ]; then
    rm -f "$link"
    echo "removed $link"
elif [ -e "$link" ] || [ -L "$link" ]; then
    echo "$link is not the link install.sh made from this checkout; left it" >&2
fi
if [ -f "$entry" ]; then
    rm -f "$entry"
    echo "removed $entry"
fi
