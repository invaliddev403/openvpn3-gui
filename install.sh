#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

run_as_root() {
    if (( EUID == 0 )); then
        "$@"
    elif command -v sudo >/dev/null 2>&1; then
        sudo "$@"
    else
        echo "Error: Native Qt dependencies require root privileges. Install sudo or run this installer as root." >&2
        exit 1
    fi
}

install_qt_dependencies() {
    if command -v apt-get >/dev/null 2>&1; then
        echo "Installing native Qt/XCB dependencies..."
        run_as_root apt-get update
        run_as_root apt-get install -y \
            libgl1 \
            libxcb-cursor0 \
            libxcb-icccm4 \
            libxcb-image0 \
            libxcb-keysyms1 \
            libxcb-render-util0 \
            libxcb-xinerama0 \
            libxkbcommon-x11-0
    elif command -v dnf >/dev/null 2>&1; then
        echo "Installing native Qt/XCB dependencies..."
        run_as_root dnf install -y \
            libxkbcommon-x11 \
            mesa-libGL \
            xcb-util-cursor \
            xcb-util-image \
            xcb-util-keysyms \
            xcb-util-renderutil \
            xcb-util-wm
    else
        echo "Warning: Could not install native Qt/XCB dependencies automatically."
    fi
}

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

install_qt_dependencies

# Clean up older installation if it exists
if [ -d "$OLD_INSTALL_DIR" ] || [ -f "$OLD_BIN_PATH" ]; then
    echo "Cleaning up legacy installation..."
    rm -rf "$OLD_INSTALL_DIR"
    rm -f "$OLD_BIN_PATH"
fi

# Extract version from vpn_gui.py
VERSION=$(grep -oP 'APP_VERSION\s*=\s*"\K[^"]+' "$SCRIPT_DIR/vpn_gui.py")
echo "Installing OpenVPN3 GUI + CLI v$VERSION via pipx..."

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

# Fix autostart file if it exists but is missing --minimized or the GNOME delay
AUTOSTART_FILE="$HOME/.config/autostart/openvpn3-gui.desktop"
EXEC_LINE="Exec=$HOME/.local/bin/openvpn3-gui --minimized"
DELAY_LINE="X-GNOME-Autostart-Delay=3"
if [ -f "$AUTOSTART_FILE" ] && (
    ! grep -qF "$EXEC_LINE" "$AUTOSTART_FILE" ||
    ! grep -qF "$DELAY_LINE" "$AUTOSTART_FILE"
); then
    echo "Updating autostart entry..."
    cat > "$AUTOSTART_FILE" <<EOF
[Desktop Entry]
Name=OpenVPN3 GUI
Exec=$HOME/.local/bin/openvpn3-gui --minimized
Type=Application
X-GNOME-Autostart-enabled=true
X-GNOME-Autostart-Delay=3
EOF
fi

echo ""
echo "Done. v$VERSION installed."
echo "  GUI:      ~/.local/bin/openvpn3-gui"
echo "  CLI:      ~/.local/bin/openvpn3-cli"
echo "  Profiles: $PROFILES_DIR/"
echo ""
echo "Launch the GUI:    openvpn3-gui"
echo "Use the CLI:       openvpn3-cli --help"
