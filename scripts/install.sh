#!/usr/bin/env bash
# Install a prebuilt local wheel; never use a developer's shared Python environment.
set -euo pipefail

project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
mode="${1:---install}"
if [[ $# -gt 1 || ( "$mode" != --install && "$mode" != --activate ) ]]; then
    echo 'Usage: sudo bash scripts/install.sh [--install|--activate]' >&2
    exit 2
fi
if [[ $EUID -ne 0 ]]; then
    echo 'Run this script with sudo in your own terminal.' >&2
    exit 1
fi

if [[ "$mode" == --activate ]]; then
    # systemd reads the root-only env file; do not source it as shell code.
    systemd-run --quiet --wait --pipe --collect --uid=pi-monitor \
        -p EnvironmentFile=/etc/pi-monitor/pi-monitor.env \
        /opt/pi-monitor/.venv/bin/python -m pi_monitor --check-config
    systemctl enable --now pi-monitor.service
    systemctl --no-pager --full status pi-monitor.service
    exit 0
fi

if systemctl is-active --quiet pi-monitor.service; then
    echo 'pi-monitor is already running. Stop it before updating the installation.' >&2
    exit 1
fi
/usr/bin/python3 -I -c 'import sys, venv; assert sys.version_info >= (3, 11), "Python 3.11+ required"'
for group in systemd-journal video; do
    if ! getent group "$group" >/dev/null; then
        echo "Required group is missing: $group" >&2
        exit 1
    fi
done

# One artifact avoids accidentally selecting an obsolete release.
shopt -s nullglob
wheels=("$project_dir"/dist/raspberry_pi_ntfy_monitor-*.whl)
if [[ ${#wheels[@]} -ne 1 ]]; then
    echo 'Build exactly one current wheel in dist/ before installing (uv build --wheel).' >&2
    exit 1
fi
for target in /opt/pi-monitor /opt/pi-monitor/.venv /etc/pi-monitor \
              /etc/pi-monitor/pi-monitor.env /var/lib/pi-monitor \
              /etc/systemd/system/pi-monitor.service; do
    if [[ -L "$target" ]]; then
        echo "Refusing unexpected symlink: $target" >&2
        exit 1
    fi
done
if [[ -e /opt/pi-monitor ]]; then
    /usr/bin/python3 -I - <<'PY'
import os
from pathlib import Path
for path in [Path('/opt/pi-monitor'), *Path('/opt/pi-monitor').rglob('*')]:
    info = path.lstat()
    if info.st_uid != 0 or (not path.is_symlink() and info.st_mode & 0o022):
        raise SystemExit('Existing installation must be root-owned and not group/world writable')
PY
fi
if ! id pi-monitor >/dev/null 2>&1; then
    useradd --system --user-group --home-dir /var/lib/pi-monitor \
        --no-create-home --shell /usr/sbin/nologin pi-monitor
else
    if [[ "$(getent passwd pi-monitor | cut -d: -f7)" != /usr/sbin/nologin ]]; then
        echo 'Existing pi-monitor account is not the expected service account.' >&2
        exit 1
    fi
fi
usermod -aG systemd-journal,video pi-monitor
install -d -o root -g root -m 0755 /opt/pi-monitor /etc/pi-monitor
install -d -o pi-monitor -g pi-monitor -m 0700 /var/lib/pi-monitor
umask 022
/usr/bin/python3 -I -m venv /opt/pi-monitor/.venv
wheel_name="$(basename -- "${wheels[0]}")"
install -o root -g root -m 0644 "${wheels[0]}" "/opt/pi-monitor/$wheel_name"
/opt/pi-monitor/.venv/bin/python -I -m pip --isolated install \
    --no-index --no-deps --force-reinstall "/opt/pi-monitor/$wheel_name"
if [[ ! -e /etc/pi-monitor/pi-monitor.env ]]; then
    install -o root -g root -m 0600 "$project_dir/config/pi-monitor.env.example" \
        /etc/pi-monitor/pi-monitor.env
else
    echo 'Preserving existing ntfy configuration.'
    chown root:root /etc/pi-monitor/pi-monitor.env
    chmod 0600 /etc/pi-monitor/pi-monitor.env
fi
install -o root -g root -m 0644 "$project_dir/systemd/pi-monitor.service" \
    /etc/systemd/system/pi-monitor.service
systemd-analyze verify /etc/systemd/system/pi-monitor.service
systemctl daemon-reload

cat <<'TEXT'

Installation complete. Service has not been started or enabled.
1. Configure your topic (and optional token) with:
   sudoedit /etc/pi-monitor/pi-monitor.env
   The server defaults to https://ntfy.sh.
2. From the project directory, validate configuration and activate with:
   sudo bash scripts/install.sh --activate
3. Check operation with:
   journalctl -u pi-monitor -f
TEXT
