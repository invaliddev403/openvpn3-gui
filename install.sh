#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Define paths
OLD_INSTALL_DIR="$HOME/.local/lib/openvpn3-gui"
OLD_BIN_PATH="$HOME/.local/bin/openvpn3-gui"
DESKTOP_DIR="$HOME/.local/share/applications"
PROFILES_DIR="$HOME/.config/openvpn3-gui/profiles"

# Check for dependencies
if ! command -v pipx &> /dev/null; then
    echo "Error: pipx is not installed. Please install pipx first (e.g., sudo apt install pipx)."
    exit 1
fi

if ! command -v openvpn3 &> /dev/null; then
    echo "Warning: openvpn3 is not installed or not in PATH."
fi

# Clean up older installation if it exists
if [ -d "$OLD_INSTALL_DIR" ] || [ -f "$OLD_BIN_PATH" ]; then
    echo "Cleaning up legacy installation..."
    rm -rf "$OLD_INSTALL_DIR"
    rm -f "$OLD_BIN_PATH"
fi

# Extract version from vpn_gui.py
VERSION=$(grep -oP 'APP_VERSION\s*=\s*"\K[^"]+' "$SCRIPT_DIR/vpn_gui.py")
echo "Installing OpenVPN3 GUI v$VERSION via pipx..."

# Use pipx to install the current directory
pipx install --force "$SCRIPT_DIR"

# Ensure directories exist with proper permissions
mkdir -p "$DESKTOP_DIR"
mkdir -p "$PROFILES_DIR"
chmod 700 "$PROFILES_DIR"

# Copy bundled profiles if any
for ovpn in "$SCRIPT_DIR"/*.ovpn; do
    [ -f "$ovpn" ] || continue
    dest="$PROFILES_DIR/$(basename "$ovpn")"
    if [ -f "$dest" ]; then
        echo "  Skipping profile $(basename "$ovpn") (already exists)"
    else
        cp "$ovpn" "$dest"
        chmod 600 "$dest"
        echo "  Installed profile: $(basename "$ovpn")"
    fi
done

# Update desktop entry
if [ -f "$SCRIPT_DIR/openvpn3-gui.desktop" ]; then
    echo "Installing desktop entry..."
    sed "s|%h|$HOME|g" "$SCRIPT_DIR/openvpn3-gui.desktop" > "$DESKTOP_DIR/openvpn3-gui.desktop"
    update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true
fi

echo ""
echo "Done. v$VERSION installed."
echo "  App:      ~/.local/bin/openvpn3-gui"
echo "  Profiles: $PROFILES_DIR/"
echo ""
echo "Run with: openvpn3-gui"
