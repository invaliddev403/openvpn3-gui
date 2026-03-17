#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

INSTALL_DIR="$HOME/.local/lib/openvpn3-gui"
BIN_DIR="$HOME/.local/bin"
DESKTOP_DIR="$HOME/.local/share/applications"
PROFILES_DIR="$HOME/.config/openvpn3-gui/profiles"

# Extract version from the source file
NEW_VERSION=$(grep -oP 'APP_VERSION\s*=\s*"\K[^"]+' "$SCRIPT_DIR/vpn_gui.py")

# Detect existing install and its version
if [ -f "$INSTALL_DIR/vpn_gui.py" ]; then
    OLD_VERSION=$(grep -oP 'APP_VERSION\s*=\s*"\K[^"]+' "$INSTALL_DIR/vpn_gui.py" 2>/dev/null || echo "unknown")
    echo "Upgrading OpenVPN3 GUI: v$OLD_VERSION → v$NEW_VERSION"
else
    echo "Installing OpenVPN3 GUI v$NEW_VERSION"
fi

mkdir -p "$INSTALL_DIR" "$BIN_DIR" "$DESKTOP_DIR" "$PROFILES_DIR"

# Always overwrite the application (upgrade)
cp "$SCRIPT_DIR/vpn_gui.py" "$INSTALL_DIR/"
chmod +x "$INSTALL_DIR/vpn_gui.py"

# Copy any bundled .ovpn profiles — never overwrite existing user profiles
for ovpn in "$SCRIPT_DIR"/*.ovpn; do
    [ -f "$ovpn" ] || continue
    dest="$PROFILES_DIR/$(basename "$ovpn")"
    if [ -f "$dest" ]; then
        echo "  Skipping profile $(basename "$ovpn") (already exists)"
    else
        cp "$ovpn" "$dest"
        echo "  Installed profile: $(basename "$ovpn")"
    fi
done

# Always overwrite the launcher
cat > "$BIN_DIR/openvpn3-gui" <<EOF
#!/usr/bin/env bash
exec python3 "$INSTALL_DIR/vpn_gui.py" "\$@"
EOF
chmod +x "$BIN_DIR/openvpn3-gui"

# Always overwrite the desktop entry
sed "s|%h|$HOME|g" "$SCRIPT_DIR/openvpn3-gui.desktop" > "$DESKTOP_DIR/openvpn3-gui.desktop"
update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true

echo ""
echo "Done. v$NEW_VERSION installed."
echo "  App:      $INSTALL_DIR/vpn_gui.py"
echo "  Profiles: $PROFILES_DIR/"
echo "  Launcher: $BIN_DIR/openvpn3-gui"
echo "  Desktop:  $DESKTOP_DIR/openvpn3-gui.desktop"
echo ""
echo "Make sure $BIN_DIR is in your PATH, then run: openvpn3-gui"
