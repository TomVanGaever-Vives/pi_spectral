#!/usr/bin/env bash
# Start the Pi WiFi Access Point ("Spectral").
# ESP32 and phone both connect to this network.
# Pi will be 192.168.4.1, clients get DHCP addresses 192.168.4.x
#
# NOTE: This disconnects from any existing WiFi (e.g. home network / SSH).

set -e

echo "Starting Spectral AP..."
sudo nmcli con up "Spectral-AP"
echo ""
echo "✓ AP active:  SSID = Spectral"
echo "              Pass = spectral2026"
echo "              Pi   = 192.168.4.1"
echo ""
echo "  Phone → connect to 'Spectral' WiFi, open http://192.168.4.1:8080"
echo "  ESP32 → connect as STA to 'Spectral' (spectral2026)"
echo ""
echo "To stop the AP and return to home WiFi:"
echo "  ./ap-stop.sh"
