#!/usr/bin/env bash
# Run the Spectral audio visualizer.
# Automatically starts the WiFi AP, launches the app, and restores WiFi on exit.

set -e
cd "$(dirname "$0")"

# ── Start WiFi AP ─────────────────────────────────────────────────────────────
echo "Starting Spectral WiFi AP..."
sudo nmcli con up "Spectral-AP" 2>/dev/null || true
sleep 1
echo "✓ AP active (SSID: Spectral, 192.168.4.1)"

# Restore home WiFi when the app exits (Ctrl-C, close, crash, etc.)
cleanup() {
    echo ""
    echo "Stopping AP, reconnecting to home WiFi..."
    sudo nmcli con down "Spectral-AP" 2>/dev/null || true
    sudo nmcli con up "telenet-28637" 2>/dev/null || true
    echo "✓ Home WiFi restored"
}
trap cleanup EXIT

# ── Display driver ────────────────────────────────────────────────────────────
# If running on a desktop (X11/Wayland), let SDL auto-detect the display.
# If running from a console TTY (no desktop), use KMS for direct HDMI rendering.
if [ -z "$DISPLAY" ] && [ -z "$WAYLAND_DISPLAY" ]; then
    export SDL_VIDEODRIVER=kms
fi
export SDL_AUDIODRIVER=dummy   # audio comes from UDP, not SDL

# Log everything to /tmp/spectral.log (also logged in Python, but this catches
# crashes before Python even starts, e.g. missing .so files).
exec 2> >(tee -a /tmp/spectral.log >&2)

# ── Launch app ────────────────────────────────────────────────────────────────
# Use venv if available, otherwise system python
if [ -f venv/bin/python ]; then
    exec venv/bin/python main.py "$@"
else
    exec python3 main.py "$@"
fi
