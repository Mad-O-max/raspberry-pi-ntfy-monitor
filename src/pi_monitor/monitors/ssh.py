"""OpenSSH parsing and fixed windows with bounded cardinality counters."""

import ipaddress
import re
from collections import Counter
from datetime import datetime

from pi_monitor.models import SshEvent
from pi_monitor.state import section


def parse_ssh(message: str, timestamp: datetime) -> SshEvent | None:
    message = message[:8192]
    success = re.search(r"Accepted (\S+) for (\S+) from (\S+)", message)
    if success:
        method, user, ip = success.groups()
        try:
            ip = str(ipaddress.ip_address(ip))
        except ValueError:
            return None
        return SshEvent(timestamp, "success", user[:128], ip, method[:64])
    kind = None
    if "Failed password" in message or "Failed publickey" in message:
        kind = "password_failure" if "Failed password" in message else "key_failure"
    elif message.startswith("Invalid user "):
        kind = "invalid_user"
    elif "authentication failure" in message:
        kind = "authentication_failure"
    elif any(
        x in message.lower()
        for x in (
            "unable to negotiate",
            "kex_exchange_identification",
            "banner exchange",
            "bad protocol",
            "invalid format",
            "no matching key exchange",
            "bad banner",
        )
    ):
        kind = "protocol"
    elif "[preauth]" in message and any(
        x in message.lower()
        for x in (
            "disconnect",
            "connection closed",
            "connection reset",
            "connection dropped",
        )
    ):
        kind = "preauth_disconnect"
    if not kind:
        return None
    # Match both legacy sshd and newer sshd-session formats, plus PAM fields.
    user_match = re.search(
        r"(?:for (?:invalid user )?|[Ii]nvalid user |authenticating user )([^\s]+)", message
    ) or re.search(r"\buser=([^\s]+)", message)
    username = user_match[1][:128] if user_match else None
    source = re.search(r"\bfrom (\S+)", message, re.I) or re.search(r"\brhost=(\S+)", message)
    ip = None
    candidates = [source[1]] if source else message.split()
    for candidate in candidates:
        try:
            ip = str(ipaddress.ip_address(candidate.strip("[],")))
            break
        except ValueError:
            continue
    return SshEvent(timestamp, kind, username, ip)


class SshAggregator:
    def __init__(self, config, state, notify, now: float):
        self.config, self.notify = config, notify
        self.data = section(
            state,
            "ssh",
            {
                "start": float(now),
                "total": 0,
                "ips": {},
                "users": {},
                "types": {},
                "ip_overflow": 0,
                "user_overflow": 0,
            },
        )
        for key in ("ips", "users", "types"):
            counters = self.data[key]
            self.data[key] = {
                k: min(v, 10**15)
                for k, v in list(counters.items())[: config.ssh_max_keys]
                if isinstance(k, str) and len(k) <= 128 and type(v) is int and v >= 0
            }
        if self.data["total"] < 0:
            self.data["total"] = 0
        if self.data["start"] > now:
            self.data["start"] = now

    def _count(self, key: str, value: str | None, overflow: str | None = None) -> None:
        if not value:
            return
        counters = self.data[key]
        if value in counters or len(counters) < self.config.ssh_max_keys:
            counters[value] = min(counters.get(value, 0) + 1, 10**15)
        elif overflow:
            self.data[overflow] = min(self.data[overflow] + 1, 10**15)

    def accept(self, event: SshEvent, now: float) -> None:
        self.tick(now)  # Boundary event belongs to the new window.
        if event.event_type == "success":
            self.notify(
                "SSH login",
                f"User: {event.username}\nFrom: {event.source_ip}\n"
                f"Authentication: {event.auth_method}\nTime: {event.timestamp.isoformat()}",
            )
            return
        self.data["total"] = min(self.data["total"] + 1, 10**15)
        self._count("ips", event.source_ip, "ip_overflow")
        self._count("users", event.username, "user_overflow")
        self._count("types", event.event_type)

    def tick(self, now: float) -> None:
        d = self.data
        if now < d["start"]:
            d["start"] = now
        elapsed = now - d["start"]
        if elapsed < self.config.ssh_window:
            return
        if d["total"] >= self.config.ssh_min_events:
            bounded = bool(d["ip_overflow"] or d["user_overflow"])
            unique = ("at least " if d["ip_overflow"] else "") + str(len(d["ips"]))
            lines = [f"{d['total']} events in {elapsed:.0f}s", f"{unique} unique source IPs"]
            for key, label in (
                ("ips", "Top sources"),
                ("users", "Top usernames"),
                ("types", "Event types"),
            ):
                lines.append("\n" + label + ":")
                lines.extend(
                    f"{k}: {v}" for k, v in Counter(d[key]).most_common(self.config.ssh_top_n)
                )
            if bounded:
                lines.append("Cardinality limit reached; top lists cover retained keys only.")
            self.notify("SSH suspicious activity", "\n".join(lines), "high")
        d.update(start=now, total=0, ips={}, users={}, types={}, ip_overflow=0, user_overflow=0)
