#!/usr/bin/env bash
# circuitloop installer (Linux). Installs the `cloop` command with uv.
# It never runs sudo: missing system packages are reported with the command to run.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EDITABLE=0
for arg in "$@"; do
  case "$arg" in
    --editable|-e) EDITABLE=1 ;;
    -h|--help)
      echo "usage: ./install.sh [--editable]"
      echo "  --editable  install in editable mode (for development)"
      exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

info() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mwarning:\033[0m %s\n' "$*" >&2; }

if [ "$(uname -s)" != "Linux" ]; then
  warn "circuitloop supports Linux only (detected $(uname -s)); continuing anyway."
fi

# --- uv ---------------------------------------------------------------------
if ! command -v uv >/dev/null 2>&1; then
  if [ -x "$HOME/.local/bin/uv" ]; then
    export PATH="$HOME/.local/bin:$PATH"
  else
    info "uv not found — installing it into ~/.local/bin (https://docs.astral.sh/uv/)"
    if command -v curl >/dev/null 2>&1; then
      curl -LsSf https://astral.sh/uv/install.sh | sh
    elif command -v wget >/dev/null 2>&1; then
      wget -qO- https://astral.sh/uv/install.sh | sh
    else
      echo "error: need curl or wget to install uv (or install uv from your distribution," >&2
      echo "       e.g. 'sudo pacman -S --needed uv' on Arch Linux)" >&2
      exit 2
    fi
    export PATH="$HOME/.local/bin:$PATH"
  fi
fi
info "using $(uv --version)"

# --- cloop ------------------------------------------------------------------
info "installing circuitloop from $REPO_DIR"
if [ "$EDITABLE" = 1 ]; then
  uv tool install --force --python ">=3.11" --editable "$REPO_DIR"
else
  uv tool install --force --python ">=3.11" "$REPO_DIR"
fi

BIN_DIR="$(uv tool dir --bin)"
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) warn "$BIN_DIR is not on your PATH. Add it, e.g.: uv tool update-shell   (then open a new shell)"
     export PATH="$BIN_DIR:$PATH" ;;
esac

# --- system dependencies (reported, never installed with sudo) ---------------
# Distro family: os-release ID/ID_LIKE first (Arch derivatives report ID_LIKE=arch),
# then whichever package manager is on PATH.
distro_family() {
  local ids=""
  if [ -r /etc/os-release ]; then
    ids="$( . /etc/os-release; echo " ${ID:-} ${ID_LIKE:-} " | tr '[:upper:]' '[:lower:]')"
  fi
  case "$ids" in
    *" arch "*|*" archarm "*|*" manjaro "*|*" endeavouros "*|*" cachyos "*|*" garuda "*|*" artix "*) echo pacman; return ;;
    *" debian "*|*" ubuntu "*) echo apt; return ;;
    *" fedora "*|*" rhel "*|*" centos "*) echo dnf; return ;;
  esac
  if command -v pacman >/dev/null 2>&1; then echo pacman
  elif command -v apt-get >/dev/null 2>&1; then echo apt
  elif command -v dnf >/dev/null 2>&1; then echo dnf
  else echo unknown; fi
}
FAMILY="$(distro_family)"

pm_hint() {
  case "$FAMILY" in
    pacman) echo "sudo pacman -S --needed $*" ;;
    apt)    echo "sudo apt install $*" ;;
    dnf)    echo "sudo dnf install $*" ;;
    *)      echo "install '$*' with your distribution's package manager" ;;
  esac
}
[ "$FAMILY" = pacman ] && info "detected an Arch-based distribution (pacman)"

if ! command -v ngspice >/dev/null 2>&1; then
  warn "ngspice is required for simulation but was not found."
  echo "    run: $(pm_hint ngspice)"
fi
if ! command -v claude >/dev/null 2>&1 && ! command -v opencode >/dev/null 2>&1; then
  warn "no agent CLI found. Install at least one of:"
  if ! command -v npm >/dev/null 2>&1; then
    echo "    first install Node.js/npm: $(pm_hint nodejs npm)"
  fi
  echo "    Claude Code: npm install -g @anthropic-ai/claude-code"
  echo "    OpenCode:    npm install -g opencode-ai"
fi

# --- final check ------------------------------------------------------------
info "running cloop doctor"
if cloop doctor; then
  info "done. Try: cloop init my_board --example ldo_5v && cd my_board && cloop run"
else
  warn "some required dependencies are missing (see the table above)."
  exit 2
fi
