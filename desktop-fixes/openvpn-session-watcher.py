#!/usr/bin/python3
"""Wait for the desktop before creating OpenVPN's system D-Bus proxies."""
import runpy
import sys
import time

import dbus


def main():
    try:
        bus = dbus.SessionBus()
        while not bus.name_has_owner("org.freedesktop.Notifications"):
            time.sleep(2)
        runpy.run_path("/usr/bin/openvpn3-desktop-session-watcher", run_name="__main__")
    except (RuntimeError, dbus.exceptions.DBusException) as error:
        # Exit normally through Python so Apport does not create a crash dialog.
        # systemd retries with fresh D-Bus connections.
        print(f"OpenVPN notification helper will retry: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
