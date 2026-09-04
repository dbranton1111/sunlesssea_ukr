#!/bin/bash
cd "$(dirname "$0")" || exit 1
xattr -dr com.apple.quarantine . >/dev/null 2>&1
PY="$HOME/Library/Application Support/UA-SunlessSea/venv/bin/python3"
[ -x "$PY" ] || PY="python3"
"$PY" install.py uninstall
echo
read -r -p "Натисни Enter…" _
