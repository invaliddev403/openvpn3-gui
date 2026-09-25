#!/usr/bin/env bash
set -euo pipefail

readonly OPENVPN_KEY_URL="https://packages.openvpn.net/packages-repo.gpg"
readonly OPENVPN_APT_REPO="https://packages.openvpn.net/openvpn3/debian"

die() {
    printf 'Error: %s\n' "$*" >&2
    exit 1
}

run_as_root() {
    if (( EUID == 0 )); then
        "$@"
    elif command -v sudo >/dev/null 2>&1; then
        sudo "$@"
    else
        die "This installer requires root privileges. Run it as root or install sudo."
    fi
}

install_apt() {
    local codename=${VERSION_CODENAME:-}

    case "$codename" in
        bookworm|trixie|jammy|noble|questing|resolute) ;;
        *)
            die "OpenVPN's stable repository does not list ${PRETTY_NAME:-this release} as supported."
            ;;
    esac

    case "$(dpkg --print-architecture)" in
        amd64|arm64) ;;
        *) die "OpenVPN's Debian repository supports only amd64 and arm64." ;;
    esac

    run_as_root apt-get update
    run_as_root apt-get install -y apt-transport-https ca-certificates curl
    run_as_root install -d -m 0755 /etc/apt/keyrings

    local key_file
    key_file=$(mktemp)
    trap "rm -f '$key_file'" EXIT
    curl --fail --silent --show-error --location "$OPENVPN_KEY_URL" --output "$key_file"
    run_as_root install -m 0644 "$key_file" /etc/apt/keyrings/openvpn.asc
    rm -f "$key_file"
    trap - EXIT

    printf 'deb [signed-by=/etc/apt/keyrings/openvpn.asc] %s %s main\n' \
        "$OPENVPN_APT_REPO" "$codename" |
        run_as_root tee /etc/apt/sources.list.d/openvpn3.list >/dev/null

    run_as_root apt-get update
    run_as_root apt-get install -y openvpn3-client
}

install_rhel() {
    local major_version=${VERSION_ID%%.*}
    local repository_package

    case "$major_version" in
        8|9)
            repository_package="https://packages.openvpn.net/openvpn-openvpn3-epel-repo-1-1.noarch.rpm"
            ;;
        10)
            repository_package="https://packages.openvpn.net/openvpn-openvpn3-rhel+epel-repo-1-1.noarch.rpm"
            ;;
        *) die "OpenVPN's repository does not list RHEL $major_version as supported." ;;
    esac

    run_as_root dnf install -y "$repository_package"
    run_as_root dnf install -y openvpn3-client
}

install_fedora() {
    run_as_root dnf install -y dnf-plugins-core
    run_as_root dnf copr enable -y dsommers/openvpn3
    run_as_root dnf install -y openvpn3-client
}

[[ -r /etc/os-release ]] || die "Cannot identify this Linux distribution."
# shellcheck source=/etc/os-release
source /etc/os-release

if command -v openvpn3 >/dev/null 2>&1; then
    printf 'OpenVPN 3 is already installed: %s\n' "$(command -v openvpn3)"
    exit 0
fi

printf 'Installing OpenVPN 3 Linux on %s...\n' "${PRETTY_NAME:-$ID}"

case "${ID:-}" in
    debian|ubuntu) install_apt ;;
    rhel) install_rhel ;;
    fedora) install_fedora ;;
    *) die "Unsupported distribution: ${PRETTY_NAME:-${ID:-unknown}}" ;;
esac

command -v openvpn3 >/dev/null 2>&1 || die "Installation finished, but openvpn3 is not in PATH."
printf 'OpenVPN 3 installed successfully: %s\n' "$(command -v openvpn3)"
