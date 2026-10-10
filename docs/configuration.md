# Configuration

The only configuration mechanism is `PI_*` environment variables. systemd reads
`/etc/pi-monitor/pi-monitor.env`. Unknown PI_* variables, malformed values, invalid
threshold ordering, nonpositive numeric settings and non-HTTPS URLs fail startup.
No secret values are included in validation errors. A restarted service is required
after edits. Examples use systemd EnvironmentFile syntax, not shell expansion.

All intervals are seconds. Polling intervals are measured from completion of the
previous read; slow checks do not overlap. Percentages range strictly between 0 and
100; booleans accept true/false or 1/0. Lists are comma-separated. Numeric settings
must be finite and positive. See architecture for delivery and cardinality bounds.

| Variable | Default | Meaning |
| --- | --- | --- |
| `PI_NTFY_URL` | `https://ntfy.sh` | HTTPS server base URL; no embedded credentials, query or fragment. |
| `PI_NTFY_TOPIC` | `(empty)` | Required private/protected topic. Empty and placeholder values are rejected. |
| `PI_NTFY_TOKEN` | `(empty)` | Optional bearer token; keep in the root-owned environment file. |
| `PI_HTTP_TIMEOUT` | `8.0` | HTTP/socket timeout seconds, maximum 30. libc DNS may take longer. |
| `PI_RETRIES` | `3` | Total delivery attempts per notification, 1–8 (includes first attempt). |
| `PI_RETRY_BACKOFF` | `2.0` | Initial retry delay seconds, exponential, capped at 30 seconds. |
| `PI_QUEUE_SIZE` | `32` | Maximum pending notifications, 1–256. Overflow is intentionally dropped. |
| `PI_NOTIFICATION_TTL` | `900.0` | Maximum age in seconds before a queued notification expires. |
| `PI_NOTIFICATION_INTERVAL` | `5.0` | Minimum seconds between notifications, excluding retry attempts. |
| `PI_DEDUP_INTERVAL` | `60.0` | Identical title/message suppression interval in seconds. |
| `PI_STATE_DIR` | `/var/lib/pi-monitor` | Absolute path for private JSON state and single-instance lock. |
| `PI_POLL_INTERVAL` | `30.0` | Seconds between metric, firmware and filesystem reads. |
| `PI_NETWORK_INTERVAL` | `15.0` | Seconds between connectivity rounds. |
| `PI_SERVICE_INTERVAL` | `60.0` | Seconds between critical-service checks. |
| `PI_PUBLIC_IP_INTERVAL` | `3600.0` | Seconds between public IPv4 checks; hourly by default. |
| `PI_UPDATES_INTERVAL` | `86400.0` | Seconds between cached APT checks. Alerts still limited to once/day and 24h. |
| `PI_TEMPERATURE_ALERT` | `80.0` | Alert at or above this CPU temperature in Celsius. |
| `PI_TEMPERATURE_CLEAR` | `75.0` | Recover at or below this Celsius value; must be lower than alert. |
| `PI_TEMPERATURE_PATH` | `/sys/class/thermal/thermal_zone0/temp` | Absolute sysfs temperature path. Value must be millidegrees Celsius. |
| `PI_DISK_ALERT` | `10.0` | Alert strictly below this percentage of available filesystem space. |
| `PI_DISK_CLEAR` | `15.0` | Recover strictly above this free percentage; must exceed alert. |
| `PI_DISK_PATHS` | `/` | Comma-separated absolute paths on local, normally writable filesystems. |
| `PI_MEMORY_ALERT_PERCENT` | `5.0` | Critical MemAvailable percentage; AND absolute MiB condition. |
| `PI_MEMORY_CLEAR_PERCENT` | `10.0` | Recovery MemAvailable percentage; OR absolute MiB condition. |
| `PI_MEMORY_ALERT_MIB` | `100.0` | Critical MemAvailable MiB; AND percentage condition. |
| `PI_MEMORY_CLEAR_MIB` | `200.0` | Recovery MemAvailable MiB; OR percentage condition. |
| `PI_LOAD_ALERT` | `1.5` | Alert load/core ratio (one-minute load). |
| `PI_LOAD_CLEAR` | `1.0` | Recovery load/core ratio, below alert. |
| `PI_LOAD_SUSTAIN` | `300.0` | High-load observation duration required before alert, seconds. |
| `PI_NETWORK_FAILURES` | `3` | Consecutive failed rounds to establish outage. |
| `PI_NETWORK_SUCCESSES` | `2` | Consecutive successful rounds to establish recovery. |
| `PI_CONNECTIVITY_TARGETS` | `1.1.1.1:443, 8.8.8.8:443` | Comma-separated numeric IP:port probes; any successful TCP connection wins. Bracketed IPv6 is supported. |
| `PI_SSH_WINDOW` | `300.0` | Aggregation window duration in seconds, based on receipt time. |
| `PI_SSH_MIN_EVENTS` | `5` | Minimum suspicious log-record count to notify per window. |
| `PI_SSH_TOP_N` | `5` | Number of top IPs/usernames/types shown, maximum 20. |
| `PI_SSH_MAX_KEYS` | `2048` | Per-counter cardinality cap, maximum 10000; saturated lists become partial. |
| `PI_CRITICAL_SERVICES` | `ssh.service, fail2ban.service` | Comma-separated systemd service names; blank disables service checks. |
| `PI_PUBLIC_IP_ENABLED` | `true` | Whether to contact the public IPv4 service. true/false or 1/0. |
| `PI_PUBLIC_IP_URL` | `https://api.ipify.org` | HTTPS endpoint returning a plain IPv4 address; no redirects. |
| `PI_UPDATES_ENABLED` | `true` | Whether to run cached APT security checks. true/false or 1/0. |
| `PI_LOG_LEVEL` | `INFO` | DEBUG, INFO, WARNING, ERROR or CRITICAL. |

Example: disable external address lookups and monitor an additional mount:

```ini
PI_PUBLIC_IP_ENABLED=false
PI_DISK_PATHS=/,/srv/data
PI_CRITICAL_SERVICES=ssh.service,fail2ban.service
```

Optional firmware checks automatically disable if vcgencmd is missing. Other failed
checks log degraded status once and recovery once, retrying at their normal interval.
Inspect logs after installation to establish which capabilities are available.
