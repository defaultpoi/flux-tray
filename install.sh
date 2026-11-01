#!/bin/sh
# Links this checkout into ~/.local/bin so `flux-tray` starts it, and
# optionally starts it with the desktop session. `git pull` is the update.
#   ./install.sh                   link only
#   ./install.sh --autostart       link and add ~/.config/autostart/flux-tray.desktop
#   ./install.sh --no-autostart    link and remove that entry
# Never touches ~/.config/flux-tray (config.conf, state.json, media.json).
set -eu

here=$(cd "$(dirname "$0")" && pwd -P)
bin_dir="${HOME}/.local/bin"
link="${bin_dir}/flux-tray"
entry="${XDG_CONFIG_HOME:-${HOME}/.config}/autostart/flux-tray.desktop"
autostart=keep

for argument in "$@"; do
    case "$argument" in
        --autostart) autostart=yes ;;
        --no-autostart) autostart=no ;;
        *) echo "usage: $0 [--autostart | --no-autostart]" >&2; exit 2 ;;
    esac
done

mkdir -p "$bin_dir"
if [ -e "$link" ] && [ ! -L "$link" ]; then
    echo "$link exists and is not a link; leaving it alone" >&2
    exit 1
fi
ln -sf "$here/flux-tray" "$link"
echo "linked $link -> $here/flux-tray"

case "$autostart" in
    yes)
        mkdir -p "$(dirname "$entry")"
        cat > "$entry" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Flux Tray
Comment=News, live streams, updates, weather and media in the tray
Exec=$link
Terminal=false
DESKTOP
        echo "wrote $entry"
        ;;
    no)
        rm -f "$entry"
        echo "removed $entry"
        ;;
esac

case ":${PATH}:" in
    *":${bin_dir}:"*) ;;
    *) echo "note: ${bin_dir} is not on PATH in this shell" >&2 ;;
esac
