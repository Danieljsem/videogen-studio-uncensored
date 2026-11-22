#!/usr/bin/env bash
# Videogen Studio (desktop app). First run ./install.sh
cd "$(dirname "$(readlink -f "$0")")"
E=studio/node_modules/electron/dist/electron
if [ ! -x venv/bin/python ]; then echo "Not installed yet - run ./install.sh"; exit 1; fi
if [ -x "$E" ]; then
  # Electron's setuid sandbox helper needs root ownership; without it, run like most AppImages do.
  # The window only ever loads the local UI (127.0.0.1), external links open in your browser.
  SB=studio/node_modules/electron/dist/chrome-sandbox
  if [ -u "$SB" ] && [ "$(stat -c %U "$SB")" = root ]; then exec "$E" studio "$@"; fi
  exec "$E" studio --no-sandbox "$@"
fi
# no desktop app -> browser
echo "Desktop app not installed - opening Videogen Studio in your browser (Ctrl+C to stop)."
venv/bin/python server.py & PID=$!
trap 'kill $PID 2>/dev/null' EXIT INT TERM
sleep 3; xdg-open "http://127.0.0.1:${WAN_PORT:-7870}" >/dev/null 2>&1 || echo "Open http://127.0.0.1:${WAN_PORT:-7870}"
wait $PID
