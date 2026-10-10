# Architecture

```text
journald -> one JSON follower -> typed parsers -> event monitors --+
                                                                 |
bounded background polling reads -> main-thread apply() ----------+
                                                                 v
                                                       alert/state logic
                                                                 v
                                                        bounded notifier
                                                                 v
                                                           HTTPS ntfy
```

## Scheduling and state ownership

The daemon loop runs every 200 ms. All alert decisions and persistent-state changes
happen on that thread. One short-lived daemon thread per due polling job reads
external data and places a single result in a queue; the job cannot overlap itself.
There are at most ten simultaneous polling reads and no accumulating task queue.
Network timeouts and command timeouts bound normal IO. OS DNS resolution can exceed
socket timeout on some systems; daemon workers prevent this from stopping event
handling or process shutdown. A hung read affects its own monitor until restart.

Journal IO uses a nonblocking pipe, 64 KiB reads, 128 KiB maximum JSON lines and
pipe backpressure. Unit/identifier/kernel filters are joined by explicit OR
expressions. Journal cursor resumes across application restarts; new boots clear
boot-scoped state. Without a cursor the follower reads the last two minutes.
Invalid/vacuumed cursors fall back to that recent window, so duplicates or missing
older events are possible. A dead journal process retries every 30 seconds.

`StateStore` writes compact versioned JSON, flushes/fsyncs a mode-0600 temporary
file, atomically replaces the destination, then fsyncs the directory. A process
lock prevents two writers. JSON is bounded to 2 MB and malformed data/fields fall
back to defaults. Snapshots occur every ten seconds and on clean exit. An abrupt
crash can lose up to ten seconds of cursor/counters; delivery and cursor storage
are not transactional. Read-only/full disks are logged and monitoring continues
in memory; failure to write the final clean marker may cause a restart warning.

Boot ID distinguishes a process restart from a reboot. Only an explicitly unclean
instance on the same boot generates a crash warning. Missing state establishes a
fresh boot baseline. Boot evidence examines at most 1,000 previous-boot journal
entries. It cannot prove cause; a normal watchdog initialization is not a reset.
Public IP, update notification date and established network outages survive reboots.

## Alerts and bounds

Threshold stores entry time, worst value, active flag and pending sustained entry.
Temperature: alert >=80, recovery <=75 °C. Disk free: alert <10%, recovery >15%.
Memory uses MemAvailable (including reclaimable cache), with both percentage and
MiB thresholds required for critical entry and either recovery margin sufficient
to clear. Load is the one-minute load divided by online CPU count, sustained for
five minutes. Pending high-load entry restarts after a monitoring restart. Hysteresis and active state prevent repeated identical alarms.

SSH counts **log records, not distinct login attempts**: one attempt can generate
both an invalid-user and a failed-password record. Windows use receipt time, have
configurable length and threshold, flush even when idle, and reset below-threshold
counters. An event exactly at rollover enters the new window. Persisted counters
survive application restart. Each IP/username counter holds at most 2,048 keys by
default; after saturation unique count is reported as a lower bound and top lists
are explicitly marked partial. Counters saturate at 10^15. No attacker-controlled
cardinality causes unbounded memory. Successful logins bypass SSH aggregation.
Kernel alert classes are limited to one notification per minute.

Notifier accepts typed content via one method and JSON-encodes it to the ntfy root
endpoint, following [ntfy's publishing API](https://docs.ntfy.sh/publish/).
HTTPS verification stays enabled; redirects are refused to avoid forwarding
credentials. Token is never logged; topic is also redacted in configuration output.
Defaults: 32 pending messages, 512 dedup hashes, 60-second identical-message
suppression, 5 seconds between notifications, 15-minute TTL and three total delivery
attempts with 2/4-second backoff. Retries for network errors, HTTP 429 and 5xx are
bounded; other HTTP failures are final. HTTP response content is never logged.
A response lost after successful POST may produce a duplicate on retry.

Queue overflow evicts ordinary messages before high-priority ones; if all queued
messages are important, ordinary incoming messages are discarded. Exhausted
retries discard the message. Queue and dedup hashes are in memory only; they are
not replayed after restart. Dropped/expired counts are logged after successful
transport recovery. Alert-state transitions reflect observations, not confirmed
delivery. Outage recovery is generated from persistent outage state even if ntfy
was unreachable during the outage. There is no promise of exactly-once delivery.
A sustained event flood may suppress or delay individual successful-login/ban
alerts; bounded delivery intentionally takes precedence over unlimited floods.

## OS adapters and limitations

- `/proc/meminfo`, `/proc/uptime`, boot ID and load averages are Linux interfaces.
- Temperature defaults to thermal_zone0; verify its type before deployment.
- Explicit disk paths only, minimum `/`; pseudo filesystems are excluded using
  `/proc/self/mountinfo`. Available space uses f_bavail, respecting reserved blocks.
- Read-only flags are the configured mount's current statvfs flags. Configure only
  filesystems expected to be writable. Critical storage errors also use journald.
- Firmware bit positions 0..3 (current) and 16..19 (since boot) mean undervoltage,
  frequency cap, throttling and soft temperature limit. See
  [Raspberry Pi documentation](https://www.raspberrypi.com/documentation/computers/os.html).
- Service checks wait one service interval after startup to allow boot activation.
  Services in failed/inactive states alert once; transitions and scheduled/stopping
  shutdowns are ignored. Manual service stops outside shutdown count as unhealthy.
- fail2ban ban duration is not inferred: journal records usually do not provide
  the effective duration (which may be incremental). Recent SSH count is contextual.
- APT helper runs the OS Python read-only; unavailable metadata or python3-apt
  produces a logged degraded check. Counts are based on cached security origins.
- Public-IP checks contact an external HTTPS service hourly by default, exposing
  the Pi's address to that service. Disable for privacy with PI_PUBLIC_IP_ENABLED=false.

## systemd hardening

Dedicated account, empty capability sets and NoNewPrivileges prevent acquiring
root. ProtectHome hides personal files. Kernel tunables/modules/control groups
are protected; real-time and setuid/setgid operations are restricted.
LockPersonality prevents changing the execution domain. Address families allow
local systemd/journal IPC and ordinary network IO. StateDirectory creates a private
writable state directory; UMask restricts newly created files. The code and venv
remain root-owned. Journal group membership grants broad log-read access; use the
account only for this service.

ProtectSystem is deliberately omitted: its mount namespace would make normally
writable filesystems appear read-only to statvfs. PrivateDevices is omitted for
firmware access. No service tries to install packages or repair security settings.
SIGTERM/SIGINT stops scheduling, terminates the journal follower, closes the notifier,
and writes a clean-exit marker. Outstanding notification work is best effort and
may be discarded. systemd's cgroup terminates remaining helper processes on stop.
