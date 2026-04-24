#!/usr/bin/env python3
"""
openvpn3-cli — command-line interface for OpenVPN3 profile and session management.
Profiles are stored in ~/.config/openvpn3-gui/profiles/ (shared with the GUI).
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import threading
import time

OPENVPN3     = shutil.which("openvpn3") or "/usr/bin/openvpn3"
PROFILES_DIR = os.path.expanduser("~/.config/openvpn3-gui/profiles")

# ── ANSI colours ──────────────────────────────────────────────────────────────
_USE_COLOR = sys.stdout.isatty()

def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _USE_COLOR else text

def green(t):  return _c("32", t)
def yellow(t): return _c("33", t)
def red(t):    return _c("31", t)
def bold(t):   return _c("1",  t)
def dim(t):    return _c("2",  t)
def cyan(t):   return _c("36", t)

# ── Core openvpn3 helpers ─────────────────────────────────────────────────────

def _run(cmd: list[str], timeout: int = 15) -> tuple[int, str]:
    """Run a command; return (returncode, combined output)."""
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        return result.returncode, (result.stdout + result.stderr).strip()
    except FileNotFoundError:
        sys.exit(red(f"Error: openvpn3 not found at {OPENVPN3}"))
    except subprocess.TimeoutExpired:
        return 1, "Command timed out."


def _parse_sessions(text: str) -> list[dict]:
    """Parse `openvpn3 sessions-list` output into a list of session dicts."""
    if "No sessions available" in text:
        return []

    sessions = []
    for block in re.split(r"-{20,}", text):
        block = block.strip()
        if not block:
            continue
        path_match = re.search(r"(/net/openvpn/v3/sessions/\S+)", block)
        if not path_match:
            continue

        path   = path_match.group(1)
        lower  = block.lower()

        if "connected" in lower:
            state = "Connected"
        elif any(s in lower for s in ("awaiting external authentication", "web based authentication",
                                      "await_auth", "await_web_auth")):
            state = "Awaiting Auth"
        elif "paused" in lower:
            state = "Paused"
        elif "connecting" in lower or "get config" in lower:
            state = "Connecting"
        else:
            state = "Unknown"

        # Extract config/profile name if present
        name_match = re.search(r"Config name[:\s]+(\S.*)", block, re.IGNORECASE)
        name = name_match.group(1).strip() if name_match else "(unknown)"

        sessions.append({"path": path, "state": state, "name": name})

    return sessions


def _get_sessions() -> list[dict]:
    _, out = _run([OPENVPN3, "sessions-list"])
    return _parse_sessions(out)


def _session_path_for(profile_name: str | None) -> str | None:
    """Return the session path for a named profile, or the first active session."""
    sessions = _get_sessions()
    if not sessions:
        return None
    if profile_name:
        for s in sessions:
            if profile_name.lower() in s["name"].lower():
                return s["path"]
    return sessions[0]["path"]


def _list_profiles() -> list[str]:
    """Sorted list of profile names (no extension)."""
    try:
        os.makedirs(PROFILES_DIR, exist_ok=True)
        return sorted(
            os.path.splitext(f)[0]
            for f in os.listdir(PROFILES_DIR)
            if f.endswith(".ovpn")
        )
    except OSError:
        return []


def _profile_path(name: str) -> str:
    return os.path.join(PROFILES_DIR, f"{name}.ovpn")


def _status_color(state: str) -> str:
    colors = {
        "Connected":    green,
        "Connecting":   yellow,
        "Awaiting Auth": yellow,
        "Paused":       yellow,
        "Disconnected": dim,
        "Unknown":      dim,
    }
    fn = colors.get(state, dim)
    return fn(state)


# ── Sub-command implementations ───────────────────────────────────────────────

def cmd_status(args):
    """Show current VPN session status."""
    sessions = _get_sessions()
    if not sessions:
        print(f"Status: {_status_color('Disconnected')}")
        return

    for s in sessions:
        label = _status_color(s["state"])
        print(f"Status:  {label}")
        print(f"Profile: {cyan(s['name'])}")
        print(f"Path:    {dim(s['path'])}")
        if len(sessions) > 1:
            print()


def cmd_list(args):
    """List available VPN profiles."""
    profiles = _list_profiles()
    sessions = _get_sessions()
    active_names = {s["name"].lower() for s in sessions}

    if not profiles:
        print(dim("No profiles found."))
        print(dim(f"Import one with:  openvpn3-cli import <file.ovpn>"))
        return

    print(bold(f"{'#':<4} {'Profile':<40} {'Status'}"))
    print(dim("─" * 60))
    for i, name in enumerate(profiles, 1):
        if any(name.lower() in a for a in active_names):
            status = green("● connected")
        else:
            status = dim("○ idle")
        print(f"{str(i)+'.':<4} {name:<40} {status}")


def _get_auth_url(session_path: str) -> str | None:
    """Try to retrieve the web-auth URL for a session via the openvpn3 CLI."""
    _, out = _run([OPENVPN3, "session-auth", "--list"], timeout=5)
    urls = re.findall(r'https?://[^\s\r\n]+', out)
    if urls:
        return urls[0]
    if session_path:
        _, out = _run(
            [OPENVPN3, "session-manage", "--path", session_path, "--show-auth-url"],
            timeout=5,
        )
        urls = re.findall(r'https?://[^\s\r\n]+', out)
        if urls:
            return urls[0]
    return None


def _show_auth_url(url: str):
    """Print the auth URL so the user can open it in a local browser."""
    width = min(len(url) + 6, 80)
    bar = dim("─" * width)
    print()
    print(f"  {yellow('! Authentication required')}")
    print(f"  {bar}")
    print(f"  {bold(cyan(url))}")
    print(f"  {bar}")
    print(f"  Copy the URL above and open it in your browser to log in.")
    print(dim("  Waiting for authentication to complete…"))
    print()


def cmd_connect(args):
    """Connect to a VPN profile, handling Authentik/web-auth automatically."""
    profiles = _list_profiles()
    if not profiles:
        print(red("No profiles found. Import one first:"))
        print(f"  openvpn3-cli import <file.ovpn>")
        sys.exit(1)

    name = _resolve_profile(args.profile, profiles)
    if name is None:
        sys.exit(1)

    config_path = _profile_path(name)
    print(f"Connecting to {cyan(name)} …")

    auth_shown  = threading.Event()   # set once we've displayed the auth URL
    session_ref = [""]                # mutable holder for the session path

    try:
        proc = subprocess.Popen(
            [OPENVPN3, "session-start", "--config", config_path],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
        )
    except FileNotFoundError:
        sys.exit(red(f"Error: openvpn3 not found at {OPENVPN3}"))

    def _stream():
        """Read session-start stdout; surface auth URLs as they appear."""
        for line in proc.stdout:
            line = line.rstrip()
            if not line:
                continue
            print(dim(f"  {line}"))
            urls = re.findall(r'https?://[^\s\r\n]+', line)
            if urls and not auth_shown.is_set():
                auth_shown.set()
                _show_auth_url(urls[0])

    reader = threading.Thread(target=_stream, daemon=True)
    reader.start()

    # Poll sessions-list while session-start is running.
    # This catches the auth URL via session-auth if it didn't appear in stdout.
    deadline = time.time() + 300  # 5-minute overall timeout
    try:
        while time.time() < deadline:
            sessions = _get_sessions()
            for s in sessions:
                session_ref[0] = s["path"]

                if s["state"] == "Awaiting Auth" and not auth_shown.is_set():
                    url = _get_auth_url(s["path"])
                    if url:
                        auth_shown.set()
                        _show_auth_url(url)

                elif s["state"] == "Connected":
                    proc.terminate()
                    reader.join(timeout=1)
                    print(green("Connected."))
                    return

            # If session-start exits before auth completes, keep polling —
            # the daemon handles the auth callback independently.
            if proc.poll() is not None and not auth_shown.is_set():
                break
            time.sleep(2)

    except KeyboardInterrupt:
        proc.terminate()
        print()
        sys.exit(0)

    reader.join(timeout=2)
    rc = proc.wait() if proc.poll() is None else proc.returncode

    # One final status check after session-start exits
    sessions = _get_sessions()
    if any(s["state"] == "Connected" for s in sessions):
        print(green("Connected."))
    elif rc == 0:
        print(yellow("Session started — run 'openvpn3-cli status' to check."))
    else:
        print(red("Connection failed."))
        sys.exit(1)


def cmd_disconnect(args):
    """Disconnect the active VPN session."""
    path = _session_path_for(getattr(args, "profile", None))
    if path is None:
        print(dim("No active session to disconnect."))
        return

    print("Disconnecting …")
    rc, out = _run([OPENVPN3, "session-manage", "--disconnect", "--path", path])
    _print_output(out)
    if rc == 0:
        print(green("Disconnected."))
    else:
        print(red("Disconnect failed."))
        sys.exit(1)


def cmd_pause(args):
    """Pause the active VPN session."""
    path = _session_path_for(getattr(args, "profile", None))
    if path is None:
        print(dim("No active session to pause."))
        return

    rc, out = _run([OPENVPN3, "session-manage", "--pause", "--path", path])
    _print_output(out)
    if rc == 0:
        print(yellow("Session paused."))
    else:
        print(red("Pause failed."))
        sys.exit(1)


def cmd_resume(args):
    """Resume a paused VPN session."""
    path = _session_path_for(getattr(args, "profile", None))
    if path is None:
        print(dim("No paused session found."))
        return

    rc, out = _run([OPENVPN3, "session-manage", "--resume", "--path", path])
    _print_output(out)
    if rc == 0:
        print(green("Session resumed."))
    else:
        print(red("Resume failed."))
        sys.exit(1)


def cmd_stats(args):
    """Show statistics for the active VPN session."""
    path = _session_path_for(getattr(args, "profile", None))
    if path is None:
        print(dim("No active session."))
        return

    rc, out = _run([OPENVPN3, "session-stats", "--path", path])
    if out:
        print(out)
    if rc != 0:
        sys.exit(1)


def cmd_import(args):
    """Import a .ovpn profile file."""
    src = os.path.abspath(args.file)
    if not os.path.isfile(src):
        print(red(f"File not found: {src}"))
        sys.exit(1)
    if not src.endswith(".ovpn"):
        print(red("File must have a .ovpn extension."))
        sys.exit(1)

    os.makedirs(PROFILES_DIR, exist_ok=True)

    if args.name:
        dest_name = args.name if args.name.endswith(".ovpn") else args.name + ".ovpn"
    else:
        dest_name = os.path.basename(src)

    dest = os.path.join(PROFILES_DIR, dest_name)
    profile_name = os.path.splitext(dest_name)[0]

    if os.path.exists(dest) and not args.force:
        print(yellow(f"Profile '{profile_name}' already exists. Use --force to overwrite."))
        sys.exit(1)

    shutil.copy2(src, dest)
    # Restrict permissions — profile may contain credentials
    os.chmod(dest, 0o600)
    print(green(f"Imported profile: {profile_name}"))


def cmd_remove(args):
    """Remove a VPN profile."""
    profiles = _list_profiles()
    name = _resolve_profile(args.profile, profiles)
    if name is None:
        sys.exit(1)

    path = _profile_path(name)
    if not os.path.exists(path):
        print(red(f"Profile not found: {name}"))
        sys.exit(1)

    if not args.yes:
        try:
            confirm = input(f"Remove profile '{name}'? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            sys.exit(0)
        if confirm not in ("y", "yes"):
            print("Cancelled.")
            return

    os.remove(path)
    print(green(f"Removed profile: {name}"))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _resolve_profile(spec: str, profiles: list[str]) -> str | None:
    """
    Resolve a profile from a name substring or 1-based index.
    Returns the exact profile name, or None on failure.
    """
    if not profiles:
        print(red("No profiles available."))
        return None

    # Try numeric index first
    if spec.isdigit():
        idx = int(spec) - 1
        if 0 <= idx < len(profiles):
            return profiles[idx]
        print(red(f"No profile at index {spec}. Run 'openvpn3-cli list' to see profiles."))
        return None

    # Exact match
    if spec in profiles:
        return spec

    # Case-insensitive substring match
    matches = [p for p in profiles if spec.lower() in p.lower()]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        print(red(f"Ambiguous profile '{spec}'. Matches:"))
        for m in matches:
            print(f"  {m}")
        return None

    print(red(f"Profile not found: '{spec}'"))
    print(dim("Run 'openvpn3-cli list' to see available profiles."))
    return None


def _print_output(text: str):
    """Print non-empty openvpn3 output, dimmed."""
    if text:
        for line in text.splitlines():
            print(dim(f"  {line}"))


# ── Argument parser ───────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="openvpn3-cli",
        description=bold("OpenVPN3 CLI") + " — manage VPN profiles and sessions",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="\n".join([
            dim("Examples:"),
            f"  openvpn3-cli list",
            f"  openvpn3-cli connect work-vpn",
            f"  openvpn3-cli connect 1            # connect by list number",
            f"  openvpn3-cli status",
            f"  openvpn3-cli disconnect",
            f"  openvpn3-cli import ~/Downloads/corp.ovpn",
            f"  openvpn3-cli import ~/corp.ovpn --name 'Corp VPN'",
            f"  openvpn3-cli remove work-vpn",
            f"  openvpn3-cli stats",
        ]),
    )

    sub = parser.add_subparsers(dest="command", metavar="<command>")
    sub.required = True

    # status
    p_status = sub.add_parser("status", help="show current VPN status")
    p_status.set_defaults(func=cmd_status)

    # list
    p_list = sub.add_parser("list", aliases=["ls"], help="list available profiles")
    p_list.set_defaults(func=cmd_list)

    # connect
    p_connect = sub.add_parser("connect", help="connect to a profile")
    p_connect.add_argument(
        "profile",
        help="profile name, substring, or list number (from 'openvpn3-cli list')",
    )
    p_connect.set_defaults(func=cmd_connect)

    # disconnect
    p_disc = sub.add_parser("disconnect", aliases=["down"], help="disconnect active session")
    p_disc.add_argument("profile", nargs="?", default=None,
                        help="profile name to target (optional if only one session)")
    p_disc.set_defaults(func=cmd_disconnect)

    # pause
    p_pause = sub.add_parser("pause", help="pause active session")
    p_pause.add_argument("profile", nargs="?", default=None)
    p_pause.set_defaults(func=cmd_pause)

    # resume
    p_resume = sub.add_parser("resume", help="resume paused session")
    p_resume.add_argument("profile", nargs="?", default=None)
    p_resume.set_defaults(func=cmd_resume)

    # stats
    p_stats = sub.add_parser("stats", help="show session statistics")
    p_stats.add_argument("profile", nargs="?", default=None)
    p_stats.set_defaults(func=cmd_stats)

    # import
    p_import = sub.add_parser("import", help="import a .ovpn profile")
    p_import.add_argument("file", help="path to .ovpn file")
    p_import.add_argument("--name", "-n", default=None,
                          help="override profile name (default: filename stem)")
    p_import.add_argument("--force", "-f", action="store_true",
                          help="overwrite existing profile")
    p_import.set_defaults(func=cmd_import)

    # remove
    p_remove = sub.add_parser("remove", aliases=["rm", "delete"],
                               help="remove a profile")
    p_remove.add_argument("profile", help="profile name or list number")
    p_remove.add_argument("--yes", "-y", action="store_true",
                          help="skip confirmation prompt")
    p_remove.set_defaults(func=cmd_remove)

    return parser


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
    except KeyboardInterrupt:
        print()
        sys.exit(0)


if __name__ == "__main__":
    main()
