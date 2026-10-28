#!/usr/bin/env bash
set -euo pipefail

source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
if (( EUID == 0 )); then
    echo "Error: Run this installer as your normal desktop user, without sudo." >&2
    exit 1
fi

# This upstream helper is optional and is not shipped on every distribution.
if [[ ! -f /usr/bin/openvpn3-desktop-session-watcher ]]; then
    echo "OpenVPN desktop session watcher is not installed; skipping startup fix."
    exit 0
fi
/usr/bin/python3 -c 'import dbus'
systemctl --user show-environment >/dev/null

helper_dir="$HOME/.local/libexec"
override_dir="$HOME/.config/systemd/user/openvpn3-desktop-session-watcher.service.d"
override_file="$override_dir/desktop-startup.conf"
mkdir -p "$helper_dir" "$override_dir"
if [[ -e "$override_file" ]]; then
    cp -p -- "$override_file" "$override_file.backup.$(date +%s)"
fi
install -m 755 "$source_dir/openvpn-session-watcher.py" "$helper_dir/openvpn-session-watcher.py"
cat > "$override_file" <<'EOF'
[Unit]
After=graphical-session.target
PartOf=graphical-session.target
StartLimitIntervalSec=0

[Service]
ExecStart=
ExecStart=/usr/bin/python3 %h/.local/libexec/openvpn-session-watcher.py
Restart=on-failure
RestartSec=15
EOF
systemctl --user daemon-reload
systemctl --user restart openvpn3-desktop-session-watcher.service
echo "OpenVPN desktop session watcher startup fix installed."
