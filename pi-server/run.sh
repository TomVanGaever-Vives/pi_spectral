#!/usr/bin/env bash
# Run the Spectral audio visualizer (UART mode).

set -e
cd "$(dirname "$0")"

# If running on a desktop (X11/Wayland), let SDL auto-detect the display.
# If running from a console TTY (no desktop), use KMS for direct HDMI rendering.
if [ -z "$DISPLAY" ] && [ -z "$WAYLAND_DISPLAY" ]; then
    export SDL_VIDEODRIVER=kms
fi
export SDL_AUDIODRIVER=dummy   # audio comes from UART, not SDL

# Catches crashes before Python even starts (e.g. missing .so files).
exec 2> >(tee -a /tmp/spectral.log >&2)

# Use venv if available, otherwise system python
if [ -f venv/bin/python ]; then
    exec venv/bin/python main.py "$@"
else
    exec python3 main.py "$@"
fi