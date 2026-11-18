#!/usr/bin/env bash
# ============================================================
#   ARASAKA DAEMON // instalador Linux (Zorin / Ubuntu / Debian)
#
#   Uso:  ./install.sh [opcoes]        (NAO rode com sudo)
#     --sem-lsp    nao instala o servidor de Python (pylsp)
#     -y           nao pede confirmacao
#   Outros servidores de linguagem: aba LINGUAGENS dentro da IDE.
# ============================================================
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_ID=arasaka-daemon
DATA="${XDG_DATA_HOME:-$HOME/.local/share}/$APP_ID"
BIN="$HOME/.local/bin"
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICONS="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/scalable/apps"
DO_LSP=1 YES=0
for a in "$@"; do
  case "$a" in
    --sem-lsp) DO_LSP=0 ;;
    -y|--yes) YES=1 ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) echo "Opcao desconhecida: $a"; exit 1 ;;
  esac
done
R=$'\e[38;2;227;18;31m'; RH=$'\e[38;2;255;59;71m'; W=$'\e[38;2;236;236;240m'; G=$'\e[38;2;120;120;130m'
B=$'\e[1m'; N=$'\e[0m'
STEP=0
step() { STEP=$((STEP + 1)); printf '\n%s%s[%02d]%s %s%s%s\n' "$R" "$B" "$STEP" "$N" "$W$B" "$*" "$N"; }
ok()   { printf '     %s■%s %s\n' "$R" "$N" "$*"; }
info() { printf '     %s›%s %s\n' "$R" "$N" "$*"; }
warn() { printf '     %s!! %s%s\n' "$RH" "$*" "$N"; }
die()  { printf '\n%s!! %s%s\n' "$RH" "$*" "$N"; exit 1; }

printf '\n%s%s   A R A S A K A   D A E M O N%s\n   %sIDE para Linux e Windows%s\n' "$R" "$B" "$N" "$G" "$N"
[ "$EUID" -eq 0 ] && die "Rode como seu usuario normal (sem sudo): ./install.sh"
[ -f "$DIR/arasaka_daemon/app.py" ] || die "Arquivos do app nao encontrados em $DIR"
command -v python3 >/dev/null || die "python3 nao encontrado"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' || die "Precisa de Python 3.9+"
if [ "$YES" -eq 0 ]; then
  printf '\n   Vai instalar a IDE (Python + Qt)'
  [ "$DO_LSP" -eq 1 ] && printf ' e o servidor de linguagem do Python'
  printf '.\n   %sContinuar? [s/N] %s' "$W" "$N"
  read -r r
  case "$r" in s|S|y|Y|sim|SIM) ;; *) echo "Cancelado."; exit 0 ;; esac
fi

step "Pacotes do sistema"
PKGS=(python3-venv python3-pip libxcb-cursor0 libxkbcommon-x11-0 libxcb-icccm4 libxcb-keysyms1 libxcb-image0
      libxcb-render-util0 libxcb-xinerama0 libxcb-shape0 libegl1 xdg-utils git)
MISSING=()
for p in "${PKGS[@]}"; do dpkg -s "$p" >/dev/null 2>&1 || MISSING+=("$p"); done
if [ ${#MISSING[@]} -gt 0 ]; then
  sudo -v || die "sudo necessario"
  info "instalando: ${MISSING[*]}"
  sudo apt-get update -qq || warn "apt update falhou"
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "${MISSING[@]}" || warn "alguns pacotes falharam"
else
  ok "tudo ja instalado"
fi

step "Ambiente Python (PySide6 / Qt 6)"
mkdir -p "$DATA"
[ -x "$DATA/venv/bin/python" ] || python3 -m venv "$DATA/venv" || die "falha ao criar o venv"
"$DATA/venv/bin/python" -m pip install -q --upgrade pip >/dev/null 2>&1
info "baixando PySide6 (~120 MB na primeira vez)..."
"$DATA/venv/bin/python" -m pip install -q --upgrade "PySide6-Essentials>=6.5" || die "falha ao instalar PySide6"
ok "PySide6 $("$DATA/venv/bin/python" -c 'import PySide6; print(PySide6.__version__)')"

mkdir -p "$BIN" "$APPS" "$ICONS"
if [ "$DO_LSP" -eq 1 ]; then
  step "Servidor de linguagem do Python (pylsp)"
  if command -v pylsp >/dev/null; then
    ok "pylsp ja disponivel"
  elif "$DATA/venv/bin/python" -m pip install -q "python-lsp-server[pyflakes]"; then
    ln -sf "$DATA/venv/bin/pylsp" "$BIN/pylsp"
    ok "pylsp instalado em $BIN/pylsp"
  else
    warn "falhou: instale depois pela aba LINGUAGENS"
  fi
fi

step "Arquivos do app"
rm -rf "$DATA/app"
mkdir -p "$DATA/app"
cp -r "$DIR/arasaka_daemon" "$DATA/app/"
find "$DATA/app" -name '__pycache__' -prune -exec rm -rf {} +
cat > "$BIN/$APP_ID" <<EOF
#!/bin/sh
# ARASAKA DAEMON launcher
export PYTHONPATH="$DATA/app\${PYTHONPATH:+:\$PYTHONPATH}"
case ":\$PATH:" in *":$BIN:"*) ;; *) export PATH="$BIN:\$PATH" ;; esac
exec "$DATA/venv/bin/python" -m arasaka_daemon "\$@"
EOF
chmod +x "$BIN/$APP_ID"
cp "$DIR/arasaka_daemon/assets/arasaka-daemon.svg" "$ICONS/$APP_ID.svg"
cat > "$APPS/$APP_ID.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Arasaka Daemon
GenericName=IDE de Programacao
Comment=Editor de codigo com LSP, terminal e execucao para varias linguagens
Exec="$BIN/$APP_ID" %F
Icon=$APP_ID
Terminal=false
Categories=Development;IDE;TextEditor;
Keywords=code;editor;ide;python;javascript;typescript;java;c;cpp;rust;go;arasaka;
MimeType=text/plain;text/x-python;text/x-csrc;text/x-c++src;text/x-java;application/javascript;application/json;text/x-shellscript;text/markdown;inode/directory;
StartupWMClass=arasaka-daemon
Actions=new;

[Desktop Action new]
Name=Nova janela
Exec="$BIN/$APP_ID"
EOF
update-desktop-database -q "$APPS" 2>/dev/null
ok "atalho no menu: Arasaka Daemon"

printf '\n%s%s ■ INSTALACAO CONCLUIDA%s\n' "$R" "$B" "$N"
printf '   %sAbra "Arasaka Daemon" no menu (ou rode: arasaka-daemon PASTA).%s\n' "$W" "$N"
printf '   %sNa aba LINGUAGENS instale runtimes e servidores das outras linguagens.%s\n\n' "$G" "$N"
