# Raspberry Pi ntfy monitor

A Python 3.11+ daemon for a Raspberry Pi 4 running Ubuntu Linux. Combines
structured journald events with periodic checks and sends HTTPS notifications
through [ntfy](https://docs.ntfy.sh/). Runs as an unprivileged systemd service.
No third-party Python runtime dependencies. Optional security-update checks use
the distribution's `python3-apt` via `/usr/bin/python3`.

Features:

- Boot/reboot evidence and detection of unexpected monitor restarts.
- Internet outage duration after stable recovery, using independent TCP probes.
- Successful SSH authentication and aggregated suspicious SSH activity.
- fail2ban bans; kernel OOM, filesystem, storage and selected hardware errors.
- Temperature, available disk space, MemAvailable, sustained load per CPU core.
- Raspberry Pi undervoltage/throttling flags, read-only mounts, critical services.
- Daily security-update notifications and configurable public IPv4 changes.
- Atomic persistent state, hysteresis, bounded queues/counters, rate limiting,
  deduplication, retries, journal resume cursors and graceful shutdown.

Example notifications (illustrative):

```text
SSH login                         SSH suspicious activity
User: tester                      73 events in 300s
From: 192.0.2.20                   12 unique source IPs
Authentication: publickey         Top sources:
                                  192.0.2.10: 18

CPU temperature normal            Internet connection restored
Current: 72.8 °C                   Down for: 522s
Worst: 84.7 °C                     Started: 2026-10-10T14:31:10+02:00
Duration: 756s                     Restored: 2026-10-10T14:39:52+02:00
```

The daemon owns alert state. One journal follower feeds independent parsers and
an SSH aggregator. Each polling monitor has at most one background read; completed
readings are applied by the daemon. A separate bounded worker sends ntfy messages.
See [architecture and delivery guarantees](docs/architecture.md).

## Install on Ubuntu / Raspberry Pi

Use an OS with **Python 3.11 or newer**, for example Ubuntu 24.04. Ubuntu 22.04's
default Python 3.10 does not meet this requirement. Run the following on the Pi.
Replace `YOUR_GITHUB_ACCOUNT` after publishing the repository, or use your existing
local checkout and skip the clone commands.

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-apt
python3 --version
git clone https://github.com/YOUR_GITHUB_ACCOUNT/raspberry-pi-ntfy-monitor.git
cd raspberry-pi-ntfy-monitor
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pytest
ruff check .
```

Install a root-owned copy and a dedicated service account. The account needs
`systemd-journal` to read system logs and `video` for firmware access where the
hardware uses `/dev/vcio` or `/dev/vchiq`. These groups should already exist on the
Pi; check with `getent group systemd-journal video`. If firmware access is not
available, throttling checks degrade gracefully; do not broaden device permissions.
The steps below are for a **first installation**.

```bash
sudo useradd --system --user-group --home-dir /var/lib/pi-monitor \
  --no-create-home --shell /usr/sbin/nologin pi-monitor
sudo usermod -aG systemd-journal,video pi-monitor
sudo install -d -o root -g root -m 0755 /opt/pi-monitor
sudo cp -r src pyproject.toml README.md LICENSE /opt/pi-monitor/
sudo chown -R root:root /opt/pi-monitor
sudo python3 -m venv /opt/pi-monitor/.venv
sudo /opt/pi-monitor/.venv/bin/pip install /opt/pi-monitor
sudo install -d -o root -g root -m 0755 /etc/pi-monitor
sudo install -o root -g root -m 0600 config/pi-monitor.env.example \
  /etc/pi-monitor/pi-monitor.env
sudo install -d -o pi-monitor -g pi-monitor -m 0700 /var/lib/pi-monitor
sudoedit /etc/pi-monitor/pi-monitor.env
```

Set at least `PI_NTFY_TOPIC` to your own protected or unguessable topic. Set
`PI_NTFY_URL` and `PI_NTFY_TOKEN` as needed for your server. Keep the token empty
when authentication is not used. Subscribe to that topic in the ntfy app.
An unguessable topic on a public server is not equivalent to authenticated access;
SSH notifications contain usernames and remote addresses. Prefer a protected topic
for sensitive operational data.

Validate the **actual environment file** before enabling the service. The following
uses transient systemd units so the root-only environment file is read by systemd
and the Python process runs as `pi-monitor`. The test command sends a real message
only when you run it yourself.

```bash
sudo systemd-run --wait --pipe --collect --uid=pi-monitor \
  -p EnvironmentFile=/etc/pi-monitor/pi-monitor.env \
  /opt/pi-monitor/.venv/bin/python -m pi_monitor --check-config
sudo systemd-run --wait --pipe --collect --uid=pi-monitor \
  -p EnvironmentFile=/etc/pi-monitor/pi-monitor.env \
  /opt/pi-monitor/.venv/bin/python -m pi_monitor --test-notification
sudo install -o root -g root -m 0644 systemd/pi-monitor.service \
  /etc/systemd/system/pi-monitor.service
sudo systemctl daemon-reload
sudo systemctl enable --now pi-monitor
systemctl status pi-monitor
journalctl -u pi-monitor -f
```

For an upgrade: stop the service, update the root-owned source copy, reinstall
`/opt/pi-monitor` with its venv's pip, rerun configuration validation, and restart.
Keep the state directory; do not replace a live environment in place.

## Installation using the local installer

Alternatively, build a wheel as your normal development user, then run the local
installer. It uses the OS Python (3.11+) for `/opt/pi-monitor/.venv`; your shared
uv development environment is not used or changed by the installer.

```bash
uv build --wheel
sudo bash scripts/install.sh
sudoedit /etc/pi-monitor/pi-monitor.env
sudo bash scripts/install.sh --activate
```

The installer requires existing `systemd-journal` and `video` groups, Python venv
support and exactly one project wheel in `dist/`. It installs that wheel offline,
creates the dedicated account and directories, preserves existing configuration,
and installs/verifies the systemd unit. A running service must first be stopped
before reinstalling. The separate `--activate` step validates the root-only
environment file before enabling and starting the service. Fill in your own topic
first; the placeholder is deliberately rejected. Run sudo in your own terminal;
never send a sudo password or ntfy token through chat.

## Configuration and CLI

All settings use `PI_*` environment variables. The application does **not** source
`.env` files itself. systemd reads `/etc/pi-monitor/pi-monitor.env`; for local use,
export variables in your shell. A complete commented-by-reference template is in
[config/pi-monitor.env.example](config/pi-monitor.env.example), and every setting
is explained in [docs/configuration.md](docs/configuration.md).

```bash
export PI_NTFY_TOPIC='REPLACE_WITH_YOUR_PRIVATE_TOPIC'
# Replace the placeholder before validation; the literal example is rejected.
python -m pi_monitor --check-config
python -m pi_monitor --show-effective-config
python -m pi_monitor --diagnostics
python -m pi_monitor --test-notification
python -m pi_monitor --status
python -m pi_monitor --foreground
```

For local foreground use, also set `PI_STATE_DIR` to an absolute writable path,
for example `"$PWD/.local-state"`. Keep runtime state out of Git. Status reads the
last saved heartbeat and alert state; it is not a live systemd health query.
No flag defaults to foreground operation. Effective configuration hides topic and
token; status omits usernames and public IP. Only one process may own a state directory.

## Permissions and operational limits

- A readable persistent journal is needed for previous-boot inference. Without it,
  the previous cause is `unknown`. Available tail evidence is heuristic, never proof
  of power loss. Previous uptime is a lower bound from the latest saved sample.
- SSH must log to journald; both `sshd` and `sshd-session` formats are supported.
  fail2ban must send ban messages to journald/syslog. Its usual standalone logfile
  is **not followed**. Check the active logging setup; see troubleshooting.
- `vcgencmd` is optional and OS/firmware dependent. Missing or inaccessible hardware
  does not stop other monitors. Historical bits are separate from current faults.
- Security counts use existing APT metadata. Ensure the OS's normal APT refresh
  timer is healthy. Ubuntu/Debian security origins are recognized; Ubuntu Pro/ESM,
  phased updates and third-party security repositories are not comprehensively
  classified. The tool does not guarantee patch compliance.
- Connectivity means TCP reachability to at least one configured IP:port, not
  proof that every internet service or DNS works. First public-IP reading establishes
  a baseline; external endpoint failures never become address-change alerts.
- Bounded queues intentionally trade delivery completeness for low memory use.
  Notifications are best effort, not an audit archive. See architecture for limits.

No SSH, firewall, fail2ban or OS security settings are changed by installation.
The shipped service is unprivileged and cannot write the root-owned installation.
It intentionally does not use `ProtectSystem`/`PrivateDevices`, which would mask
read-only mount transitions or block Raspberry Pi firmware devices. Other hardening
options are documented in architecture.

## Troubleshooting and removal

Start with [docs/troubleshooting.md](docs/troubleshooting.md).

```bash
sudo systemctl disable --now pi-monitor
sudo rm /etc/systemd/system/pi-monitor.service
sudo systemctl daemon-reload
sudo rm -r /opt/pi-monitor
```

To also remove configuration, state and the dedicated account (irreversible):

```bash
sudo rm -r /etc/pi-monitor /var/lib/pi-monitor
sudo userdel pi-monitor
# userdel may already remove the matching group; check first.
getent group pi-monitor && sudo groupdel pi-monitor
```

## Development and publication

Open the repository in VS Code and select `.venv/bin/python`. Python, Pylance and
Ruff recommendations are included. Tests use synthetic data, fakes and subprocess
fixtures and need no network, Pi hardware, SSH server or fail2ban.

```bash
python -m pip install -e '.[dev]'
pytest
ruff check .
ruff format --check .
python -m build
```

CI is configured for Python 3.11, 3.12 and 3.13 on Ubuntu. A local pass does not
establish that the GitHub-hosted workflow has run. Contributions should include
behaviour tests, updated documentation, and no private logs or credentials. Read
[AGENTS.md](AGENTS.md) for coding conventions and [CHANGELOG.md](CHANGELOG.md) for history.

Before publication, inspect staged changes, tracked files **and all history** for
secrets and private-key material. Do not publish the local task-prompt file or raw
journal captures. The configured Git author email will be visible in commit history.
Commands (run only when ready to publish):

```bash
git status --short
git diff --cached
git grep -n -I -E 'Bearer |PI_NTFY_TOKEN|PI_NTFY_TOPIC|PRIVATE KEY'
git log --all --format=fuller --stat
git log --all -p -- . ':!LICENSE'
# Review matches: variable names and fake test credentials are expected.
gh auth status
gh repo create raspberry-pi-ntfy-monitor --public --source=. --remote=origin
git push -u origin main
```

Licensed under the [MIT license](LICENSE).
