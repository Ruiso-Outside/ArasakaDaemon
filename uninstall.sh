#!/usr/bin/env bash
# ARASAKA DAEMON // desinstalador Linux (as configuracoes em ~/.config/arasaka-daemon sao mantidas)
APP_ID=arasaka-daemon
DATA="${XDG_DATA_HOME:-$HOME/.local/share}/$APP_ID"
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
rm -f "$HOME/.local/bin/$APP_ID" "$APPS/$APP_ID.desktop" \
      "${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps/$APP_ID.svg"
[ "$(readlink -f "$HOME/.local/bin/pylsp" 2>/dev/null)" = "$DATA/venv/bin/pylsp" ] && rm -f "$HOME/.local/bin/pylsp"
rm -rf "$DATA"
update-desktop-database -q "$APPS" 2>/dev/null
printf '\e[38;2;227;18;31m ■ ARASAKA DAEMON REMOVIDO\e[0m\n'
