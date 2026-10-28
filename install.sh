#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

run_as_root() {
    if (( EUID == 0 )); then
        "$@"
    elif command -v sudo >/dev/null 2>&1; then
        sudo "$@"
    else
        echo "Error: Installing system dependencies requires sudo." >&2
        exit 1
    fi
}

install_dependencies() {
    if command -v apt-get >/dev/null 2>&1; then
        echo "Installing native Qt/XCB dependencies..."
        run_as_root apt-get update
        run_as_root apt-get install -y \
            pipx \
            python3-venv \
            python3-pyqt5 \
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
            pipx \
            python3-pip \
            python3-qt5 \
            libxkbcommon-x11 \
            mesa-libGL \
            xcb-util-cursor \
            xcb-util-image \
            xcb-util-keysyms \
            xcb-util-renderutil \
            xcb-util-wm
    else
        echo "Error: Automatic installation requires apt-get or dnf." >&2
        exit 1
    fi
}

# Define paths
OLD_INSTALL_DIR="$HOME/.local/lib/openvpn3-gui"
OLD_BIN_PATH="$HOME/.local/bin/openvpn3-gui"
DESKTOP_DIR="$HOME/.local/share/applications"
PROFILES_DIR="$HOME/.config/openvpn3-gui/profiles"

# Install into the desktop user's account, using sudo only for system packages.
if (( EUID == 0 )); then
    echo "Error: Run ./install.sh as your normal desktop user, without sudo." >&2
    exit 1
fi

case "$(uname -m)" in
    aarch64|arm64|x86_64|amd64) ;;
    *) echo "Error: Supported architectures are ARM64 and x86_64." >&2; exit 1 ;;
esac

if ! command -v openvpn3 &> /dev/null; then
    bash "$SCRIPT_DIR/install-openvpn3.sh"
fi

install_dependencies

# The distro's Qt bindings are native on both ARM64 and x86_64. Use its
# matching interpreter, even when another Python is first on PATH.
SYSTEM_PYTHON=/usr/bin/python3
"$SYSTEM_PYTHON" -c 'import sys; assert sys.version_info >= (3, 10), "Python 3.10+ is required"; from PyQt5 import QtCore, QtGui, QtWidgets'

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
# --force alone reuses old environments, including their interpreter and Qt
# wheels. Recreate this app's environment when migrating an existing install.
PIPX_VENVS=$(pipx environment --value PIPX_LOCAL_VENVS)
if [ -d "$PIPX_VENVS/openvpn3-gui" ]; then
    pipx uninstall openvpn3-gui
fi
pipx install --force --python "$SYSTEM_PYTHON" --system-site-packages "$SCRIPT_DIR"
pipx runpip openvpn3-gui check
pipx ensurepath

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

# Install the notification startup workaround when the upstream helper exists.
bash "$SCRIPT_DIR/desktop-fixes/install.sh"

echo ""
echo "Done. v$VERSION installed."
echo "  GUI:      ~/.local/bin/openvpn3-gui"
echo "  CLI:      ~/.local/bin/openvpn3-cli"
echo "  Profiles: $PROFILES_DIR/"
echo ""
echo "Launch the GUI:    openvpn3-gui"
echo "Use the CLI:       openvpn3-cli --help"
