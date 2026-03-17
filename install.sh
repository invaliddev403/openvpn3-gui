#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

INSTALL_DIR="$HOME/.local/lib/openvpn3-gui"
BIN_DIR="$HOME/.local/bin"
DESKTOP_DIR="$HOME/.local/share/applications"
PROFILES_DIR="$HOME/.config/openvpn3-gui/profiles"

echo "Installing OpenVPN3 GUI..."

mkdir -p "$INSTALL_DIR" "$BIN_DIR" "$DESKTOP_DIR" "$PROFILES_DIR"

# Copy application
cp "$SCRIPT_DIR/vpn_gui.py" "$INSTALL_DIR/"
chmod +x "$INSTALL_DIR/vpn_gui.py"

# Copy any bundled .ovpn profiles into the profiles directory
for ovpn in "$SCRIPT_DIR"/*.ovpn; do
    [ -f "$ovpn" ] || continue
    dest="$PROFILES_DIR/$(basename "$ovpn")"
    if [ -f "$dest" ]; then
        echo "  Skipping $(basename "$ovpn") (already exists in profiles dir)"
    else
        cp "$ovpn" "$dest"
        echo "  Installed profile: $(basename "$ovpn")"
    fi
done

# Create launcher script
cat > "$BIN_DIR/openvpn3-gui" <<EOF
#!/usr/bin/env bash
exec python3 "$INSTALL_DIR/vpn_gui.py" "\$@"
EOF
chmod +x "$BIN_DIR/openvpn3-gui"

# Install desktop entry (substitute %h placeholder with actual home)
sed "s|%h|$HOME|g" "$SCRIPT_DIR/openvpn3-gui.desktop" > "$DESKTOP_DIR/openvpn3-gui.desktop"
update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true

echo "Done."
echo "  App:      $INSTALL_DIR/vpn_gui.py"
echo "  Profiles: $PROFILES_DIR/"
echo "  Launcher: $BIN_DIR/openvpn3-gui"
echo "  Desktop:  $DESKTOP_DIR/openvpn3-gui.desktop"
echo ""
echo "Make sure $BIN_DIR is in your PATH, then run: openvpn3-gui"
