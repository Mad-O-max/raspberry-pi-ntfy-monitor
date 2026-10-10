"""One configuration source: PI_* environment variables (systemd EnvironmentFile)."""

import math
import os
import re
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from urllib.parse import urlsplit


def https_url(value: str) -> bool:
    try:
        url = urlsplit(value)
        if url.port is not None and not 1 <= url.port <= 65535:
            return False
        return bool(
            url.scheme == "https"
            and url.hostname
            and not url.username
            and not url.password
            and not url.query
            and not url.fragment
            and not any(c.isspace() for c in value)
        )
    except ValueError:
        return False


@dataclass(frozen=True)
class Config:
    ntfy_url: str = "https://ntfy.sh"
    ntfy_topic: str = field(default="", repr=False)
    ntfy_token: str = field(default="", repr=False)
    http_timeout: float = 8.0
    retries: int = 3
    retry_backoff: float = 2.0
    queue_size: int = 32
    notification_ttl: float = 900.0
    notification_interval: float = 5.0
    dedup_interval: float = 60.0
    state_dir: str = "/var/lib/pi-monitor"
    poll_interval: float = 30.0
    network_interval: float = 15.0
    service_interval: float = 60.0
    public_ip_interval: float = 3600.0
    updates_interval: float = 86400.0
    temperature_alert: float = 80.0
    temperature_clear: float = 75.0
    temperature_path: str = "/sys/class/thermal/thermal_zone0/temp"
    disk_alert: float = 10.0
    disk_clear: float = 15.0
    disk_paths: tuple[str, ...] = ("/",)
    memory_alert_percent: float = 5.0
    memory_clear_percent: float = 10.0
    memory_alert_mib: float = 100.0
    memory_clear_mib: float = 200.0
    load_alert: float = 1.5
    load_clear: float = 1.0
    load_sustain: float = 300.0
    network_failures: int = 3
    network_successes: int = 2
    connectivity_targets: tuple[str, ...] = ("1.1.1.1:443", "8.8.8.8:443")
    ssh_window: float = 300.0
    ssh_min_events: int = 5
    ssh_top_n: int = 5
    ssh_max_keys: int = 2048
    critical_services: tuple[str, ...] = ("ssh.service", "fail2ban.service")
    public_ip_enabled: bool = True
    public_ip_url: str = "https://api.ipify.org"
    updates_enabled: bool = True
    log_level: str = "INFO"

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "Config":
        env = dict(os.environ) if env is None else env
        defaults = cls()
        values = {}
        known = {"PI_" + f.name.upper() for f in fields(cls)}
        unknown = sorted(k for k in env if k.startswith("PI_") and k not in known)
        if unknown:
            raise ValueError("Unknown configuration variable(s): " + ", ".join(unknown))
        for f in fields(cls):
            key = "PI_" + f.name.upper()
            if key not in env:
                continue
            raw = env[key]
            default = getattr(defaults, f.name)
            try:
                if isinstance(default, bool):
                    if raw.lower() not in {"true", "false", "1", "0"}:
                        raise ValueError
                    value = raw.lower() in {"true", "1"}
                elif isinstance(default, tuple):
                    value = tuple(x.strip() for x in raw.split(",") if x.strip())
                else:
                    value = type(default)(raw)
            except ValueError:
                raise ValueError(f"Invalid value for {key}") from None
            values[f.name] = value
        config = cls(**values)
        config.validate()
        return config

    def validate(self) -> None:
        if not https_url(self.ntfy_url) or not https_url(self.public_ip_url):
            raise ValueError(
                "PI_NTFY_URL and PI_PUBLIC_IP_URL must be HTTPS URLs without credentials"
            )
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", self.ntfy_topic):
            raise ValueError("PI_NTFY_TOPIC must be a nonempty topic (letters, digits, _ or -)")
        if self.ntfy_topic.lower().startswith(("replace", "change", "your_")):
            raise ValueError("Replace the PI_NTFY_TOPIC placeholder")
        if any(ord(c) < 33 or ord(c) > 126 for c in self.ntfy_token):
            raise ValueError("PI_NTFY_TOKEN contains invalid characters")
        for f in fields(self):
            v = getattr(self, f.name)
            if type(v) in (int, float) and (not math.isfinite(v) or v <= 0):
                raise ValueError(f"PI_{f.name.upper()} must be finite and positive")
        if self.retries > 8 or self.http_timeout > 30 or self.queue_size > 256:
            raise ValueError("Maximum retries=8, http_timeout=30, queue_size=256")
        if self.ssh_max_keys > 10000 or self.ssh_top_n > 20:
            raise ValueError("Maximum ssh_max_keys=10000, ssh_top_n=20")
        if self.temperature_clear >= self.temperature_alert:
            raise ValueError("Temperature clear threshold must be below alert threshold")
        if self.load_clear >= self.load_alert:
            raise ValueError("Load clear threshold must be below alert threshold")
        for low, high in (
            (self.disk_alert, self.disk_clear),
            (self.memory_alert_percent, self.memory_clear_percent),
        ):
            if not 0 < low < high < 100:
                raise ValueError("Percentage thresholds require 0 < alert < clear < 100")
        if self.memory_alert_mib >= self.memory_clear_mib:
            raise ValueError("Memory MiB clear must exceed alert")
        if not Path(self.state_dir).is_absolute() or not Path(self.temperature_path).is_absolute():
            raise ValueError("State and temperature paths must be absolute")
        if not self.disk_paths or any(not Path(p).is_absolute() for p in self.disk_paths):
            raise ValueError("PI_DISK_PATHS must contain absolute paths")
        if any(not re.fullmatch(r"[A-Za-z0-9_.@:-]+\.service", s) for s in self.critical_services):
            raise ValueError("Invalid critical service name")
        if not self.connectivity_targets:
            raise ValueError("At least one connectivity target is required")
        import ipaddress

        for target in self.connectivity_targets:
            try:
                host, port = target.rsplit(":", 1)
                ipaddress.ip_address(host.strip("[]"))
                if not 1 <= int(port) <= 65535:
                    raise ValueError
            except ValueError:
                raise ValueError("Connectivity targets require numeric IP:port") from None
        if self.log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("Invalid PI_LOG_LEVEL")

    def redacted(self) -> dict:
        result = asdict(self)
        result["ntfy_token"] = "<redacted>" if self.ntfy_token else "<unset>"
        result["ntfy_topic"] = "<redacted>"
        return result
