# OpenVPN3 GUI

A PyQt5 desktop client and system tray icon for the [`openvpn3`](https://github.com/OpenVPN/openvpn3-linux) CLI. Supports multiple profiles, session management, and runs persistently in the system tray.

## Features

- System tray icon with colour-coded connection status
- Import and manage multiple `.ovpn` profiles
- Connect, disconnect, pause, and resume sessions
- View live session statistics
- Minimises to tray on close; right-click to quit
- Cleans up orphaned sessions and stale app instances on startup

## Requirements

- Python 3.10+
- PyQt5 (`pip install PyQt5` or `sudo apt install python3-pyqt5`)
- [`openvpn3`](https://openvpn.net/cloud-docs/owner/connectors/connector-user-guides/openvpn-3-client-for-linux.html) installed at `/usr/bin/openvpn3`

## Installation

```bash
git clone <repo-url>
cd openvpn3-gui
./install.sh
```

The installer:
- Copies the app to `~/.local/lib/openvpn3-gui/`
- Creates a launcher at `~/.local/bin/openvpn3-gui`
- Installs a `.desktop` entry for app launchers
- Copies any bundled `.ovpn` files into the profiles directory (skips existing)

Make sure `~/.local/bin` is in your `PATH`, then run:

```bash
openvpn3-gui
```

### Upgrading

Re-run `./install.sh` — it will detect the installed version and upgrade automatically. User profiles are never overwritten.

## Profile management

Profiles are stored in `~/.config/openvpn3-gui/profiles/`. You can:

- **Import** a profile via the GUI (`Import…` button or tray → `Import Profile…`)
- **Switch** profiles using the dropdown or the tray `Profiles` submenu
- **Remove** a profile with the `Remove` button (deletes the file)

## Project structure

```
openvpn3-gui/
├── vpn_gui.py            # Main application
├── openvpn3-gui.desktop  # Desktop entry (template)
├── install.sh            # Installer / upgrade script
└── .gitignore            # Excludes *.ovpn files
```

## Version

Current version is defined in `vpn_gui.py`:

```python
APP_VERSION = "1.1.0"
```

Bump this before running `install.sh` to publish an upgrade.
