#!/usr/bin/env bash
# Remove the `cloop` command. User data (~/.config/circuitloop, project runs/) is kept
# unless --purge is given.
set -euo pipefail

PURGE=0
[ "${1:-}" = "--purge" ] && PURGE=1

if command -v uv >/dev/null 2>&1 || [ -x "$HOME/.local/bin/uv" ]; then
  UV="$(command -v uv || echo "$HOME/.local/bin/uv")"
  "$UV" tool uninstall circuitloop || true
else
  echo "uv not found; nothing to uninstall" >&2
fi

CFG="${XDG_CONFIG_HOME:-$HOME/.config}/circuitloop"
if [ "$PURGE" = 1 ]; then
  rm -rf "$CFG"
  echo "removed $CFG"
elif [ -d "$CFG" ]; then
  echo "kept user config/parts in $CFG (use --purge to remove)"
fi
echo "circuitloop uninstalled. ngspice and agent CLIs were left untouched."
