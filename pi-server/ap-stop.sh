#!/usr/bin/env bash
# Stop the Pi WiFi AP and reconnect to home WiFi.

set -e

echo "Stopping Spectral AP..."
sudo nmcli con down "Spectral-AP" 2>/dev/null || true

echo "Reconnecting to home WiFi..."
# Try to reconnect to a known network
sudo nmcli con up "telenet-28637" 2>/dev/null && echo "✓ Connected to telenet-28637" || \
  echo "Could not auto-reconnect. Use: sudo nmcli dev wifi connect <SSID> password <pass>"
