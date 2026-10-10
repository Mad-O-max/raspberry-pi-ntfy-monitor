# Troubleshooting

```bash
systemctl status pi-monitor
journalctl -u pi-monitor -n 100
journalctl -u pi-monitor -f
sudo sshd -T
sudo fail2ban-client status sshd
vcgencmd get_throttled
```

## Service exits immediately

Check Python >=3.11, the root-owned `/opt/pi-monitor/.venv`, the mandatory
`/etc/pi-monitor/pi-monitor.env`, a real topic, and the dedicated account/groups.
Unknown PI_* variables are rejected to catch misspellings. Start-limit protection
stops crash loops; fix the cause, then use `sudo systemctl reset-failed pi-monitor`
and `sudo systemctl restart pi-monitor`. Validate using the systemd-run command in
README; the current interactive shell does not inherit the service environment.

## No SSH/fail2ban events

```bash
sudo -u pi-monitor journalctl -u ssh.service -u sshd.service -n 20 -o json
sudo -u pi-monitor journalctl -u fail2ban.service -n 20 -o json
sudo -u pi-monitor journalctl SYSLOG_IDENTIFIER=fail2ban -n 20 -o json
getent group systemd-journal
```

`sshd` and `sshd-session` are supported. A successful login is an `Accepted ...`
record; session close records are ignored. SSH aggregation counts several log
records per attempt, and does not claim they are separate attackers. Do not share
raw output publicly: it can contain real IP addresses and usernames.

fail2ban commonly logs bans only to `/var/log/fail2ban.log`. This application
requires bans to appear in journald. Inspect `sudo fail2ban-client get logtarget`
and the local distribution's supported logging configuration. If necessary,
configure syslog/journal logging according to fail2ban's installed documentation,
then verify a real ban appears in the journal. This project does not change
fail2ban's backend, jails, logging or blocking rules automatically. A healthy
fail2ban service alone does not establish that ban messages reach the monitor.

## Previous reboot cause is unknown / possible power loss

```bash
journalctl --list-boots
journalctl -b -1 -n 100
```

Previous logs may be unavailable, volatile, rotated, incomplete or inaccessible.
Missing shutdown evidence does not prove power failure. Enable persistent journals
only as an explicit OS administration decision, considering SD-card wear.
The monitor's previous uptime is sampled, so it is a lower bound.

## ntfy delivery fails

Verify server, topic permissions and token using `--test-notification` as shown
in README. TLS CA certificates and the system clock must be correct. HTTP status
is logged without response text or credentials. Redirects are refused. A wrong
URL/path, 401/403 or 404 is not retried; network errors, 429 and 5xx have bounded
retries. No retries continue forever. After extended outages old/failed messages
are discarded. Once connectivity stabilizes, an outage-duration event is generated.

## Hardware or package checks unavailable

```bash
cat /sys/class/thermal/thermal_zone0/type
cat /sys/class/thermal/thermal_zone0/temp
sudo -u pi-monitor vcgencmd get_throttled
ls -l /dev/vcio /dev/vchiq
/usr/bin/python3 -c 'import apt; print("python3-apt available")'
systemctl status apt-daily.timer
```

Missing device paths are normal on some OS/kernel combinations. Do not chmod
firmware devices globally. Select the right thermal zone with PI_TEMPERATURE_PATH.
Ubuntu may not include vcgencmd: install the distribution-supported firmware tool
only if wanted; otherwise that check remains disabled. APT metadata is read without
refreshing it; use the OS's normal package administration to correct stale metadata.
Security reporting does not cover every vendor/ESM policy.

## Disk / state issues

```bash
findmnt -no TARGET,FSTYPE,OPTIONS /
df -h /
sudo ls -ld /var/lib/pi-monitor
```

Do not add permanently read-only or virtual mounts to PI_DISK_PATHS. The service
needs exclusive write access to its state directory. Corrupt state resets safe
fields and logs a warning; this can repeat baseline/active alerts. If the state
partition is full/read-only, monitoring continues in memory, but cannot guarantee
restart continuity. Stop the service before manually repairing or deleting state.
Never run two daemons with the same state directory.

## Network or public-IP checks

Default probes use TCP/443 to two numeric addresses; firewalls may require
site-specific targets. Any one successful target is sufficient. DNS failure alone
therefore does not imply internet loss. IPv4-only public-IP validation rejects
HTML error pages and IPv6 responses. Disable external address checks if unwanted.
A hanging resolver affects only that polling worker. Restart after correcting
resolver issues if a worker remains stuck.
