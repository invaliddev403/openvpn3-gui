#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

INSTALL_DIR="$HOME/.local/lib/openvpn3-gui"
BIN_DIR="$HOME/.local/bin"
DESKTOP_DIR="$HOME/.local/share/applications"

echo "Installing OpenVPN3 GUI..."

mkdir -p "$INSTALL_DIR" "$BIN_DIR" "$DESKTOP_DIR"

# Copy application files
cp "$SCRIPT_DIR/vpn_gui.py" "$INSTALL_DIR/"
cp "$SCRIPT_DIR/us-vpn0-tcp.ovpn" "$INSTALL_DIR/"
chmod +x "$INSTALL_DIR/vpn_gui.py"

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
echo "  App:     $INSTALL_DIR/"
echo "  Launcher: $BIN_DIR/openvpn3-gui"
echo "  Desktop:  $DESKTOP_DIR/openvpn3-gui.desktop"
echo ""
echo "Make sure $BIN_DIR is in your PATH, then run: openvpn3-gui"
