#!/usr/bin/env bash
# install.sh -- one-shot setup for the Spectral Analyser on Raspberry Pi OS.
#
# Usage (run once after cloning):
#   bash install.sh
#
# What it does:
#   1. Checks system requirements
#   2. Creates a Python venv and installs dependencies
#   3. Grants serial-port access (dialout group)
#   4. Installs a desktop launcher icon

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVER_DIR="$REPO_DIR/pi-server"
DESKTOP_FILE="$REPO_DIR/spectral-analyser.desktop"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
ok()   { echo -e "${GREEN}[OK]${NC}  $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
fail() { echo -e "${RED}[FAIL]${NC} $*"; exit 1; }
info() { echo -e "      $*"; }

echo ""
echo "========================================"
echo "  Spectral Analyser -- installer"
echo "========================================"
echo ""

# ── 1. OS check ───────────────────────────────────────────────────────────────
if [[ "$(uname -s)" != "Linux" ]]; then
    fail "This installer is for Raspberry Pi OS (Linux) only."
fi
ok "Running on Linux"

# ── 2. Python 3.10+ ───────────────────────────────────────────────────────────
PYTHON=$(command -v python3 || true)
if [[ -z "$PYTHON" ]]; then
    fail "python3 not found. Install it with: sudo apt install python3"
fi
PY_VER=$("$PYTHON" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PY_MAJOR=${PY_VER%%.*}
PY_MINOR=${PY_VER##*.}
if (( PY_MAJOR < 3 || (PY_MAJOR == 3 && PY_MINOR < 10) )); then
    fail "Python 3.10 or newer is required (found $PY_VER). sudo apt install python3"
fi
ok "Python $PY_VER found"

# ── 3. System packages ────────────────────────────────────────────────────────
MISSING_PKGS=()
for pkg in python3-venv python3-pip; do
    if ! dpkg -s "$pkg" &>/dev/null; then
        MISSING_PKGS+=("$pkg")
    fi
done
if (( ${#MISSING_PKGS[@]} > 0 )); then
    info "Installing missing system packages: ${MISSING_PKGS[*]}"
    sudo apt-get install -y "${MISSING_PKGS[@]}"
fi
ok "System packages ready"

# ── 4. Python venv + dependencies ─────────────────────────────────────────────
VENV_DIR="$SERVER_DIR/venv"
if [[ ! -d "$VENV_DIR" ]]; then
    info "Creating virtual environment..."
    "$PYTHON" -m venv "$VENV_DIR"
fi
ok "Virtual environment ready"

info "Installing Python dependencies..."
"$VENV_DIR/bin/pip" install --quiet --upgrade pip
"$VENV_DIR/bin/pip" install --quiet -r "$SERVER_DIR/requirements.txt"
ok "Python dependencies installed"

# ── 5. Script permissions ─────────────────────────────────────────────────────
chmod +x "$SERVER_DIR/run.sh"
ok "run.sh is executable"

# ── 6. Serial port access (dialout group) ─────────────────────────────────────
if ! groups "$USER" | grep -qw dialout; then
    info "Adding $USER to dialout group for serial port access..."
    sudo usermod -aG dialout "$USER"
    warn "Serial port access requires a logout/reboot to take effect."
    warn "Run 'sudo reboot' after this installer finishes."
    NEED_REBOOT=1
else
    ok "User $USER already in dialout group"
    NEED_REBOOT=0
fi

# ── 7. Desktop launcher ───────────────────────────────────────────────────────
# Patch Exec path to the actual location of run.sh on this machine
sed "s|Exec=.*|Exec=bash $SERVER_DIR/run.sh|" "$DESKTOP_FILE" > /tmp/spectral-analyser.desktop

DESKTOP_DIR="$HOME/Desktop"
if [[ -d "$DESKTOP_DIR" ]]; then
    cp /tmp/spectral-analyser.desktop "$DESKTOP_DIR/spectral-analyser.desktop"
    chmod +x "$DESKTOP_DIR/spectral-analyser.desktop"
    ok "Desktop icon installed at $DESKTOP_DIR/spectral-analyser.desktop"
else
    warn "No Desktop folder found -- skipping icon install."
    info "You can add it later with:"
    info "  cp /tmp/spectral-analyser.desktop ~/Desktop/ && chmod +x ~/Desktop/spectral-analyser.desktop"
fi

# ── 8. Quick smoke-test (import check) ────────────────────────────────────────
info "Checking Python imports..."
"$VENV_DIR/bin/python" - <<'PYCHECK'
import importlib, sys
missing = []
for mod in ("serial", "numpy", "pygame", "fastapi", "uvicorn", "websockets"):
    if importlib.util.find_spec(mod) is None:
        missing.append(mod)
if missing:
    print(f"MISSING: {', '.join(missing)}", file=sys.stderr)
    sys.exit(1)
PYCHECK
ok "All Python imports OK"

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "========================================"
echo "  Installation complete!"
echo "========================================"
echo ""
info "To start the analyser:"
info "  Double-click the 'Spectral Analyser' icon on the desktop"
info "  -- or --"
info "  bash $SERVER_DIR/run.sh"
echo ""
info "ESP32 must be connected via USB serial (/dev/ttyUSB0 by default)."
info "To use a different port:  bash run.sh --port /dev/ttyAMA0"
info "To use WiFi UDP instead:  bash run.sh --udp"
info "To run without hardware:  bash run.sh --demo"
echo ""
if (( NEED_REBOOT )); then
    echo -e "${YELLOW}ACTION REQUIRED: reboot the Pi before the serial port will work.${NC}"
    echo ""
fi