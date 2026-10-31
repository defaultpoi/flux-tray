#!/bin/sh
set -eu

APP_DIR="$HOME/.local/lib/flux-tray"
BIN_DIR="${XDG_BIN_HOME:-$HOME/.local/bin}"
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}"

rm -rf "$APP_DIR"
rm -f "$BIN_DIR/flux-tray"
rm -f "$DATA_DIR/applications/flux-tray.desktop"
rm -f "$CONFIG_DIR/autostart/flux-tray.desktop"

printf 'Flux Tray application files removed.\n'
printf 'User configuration and data were left untouched.\n'
