import ipaddress
import re

from pi_monitor.models import BanEvent


def parse_ban(message: str) -> BanEvent | None:
    match = re.search(r"\[([\w.-]+)\]\s+Ban\s+(\S+)", message[:8192])
    if not match:
        return None
    try:
        return BanEvent(str(ipaddress.ip_address(match[2])), match[1][:128])
    except ValueError:
        return None


def handle_ban(event: BanEvent, aggregator, notify) -> None:
    count = aggregator.data["ips"].get(event.source_ip, 0)
    notify(
        "fail2ban",
        f"IP banned: {event.source_ip}\nJail: {event.jail}\n"
        f"Recent journal events from IP: {count}\nBan duration: unavailable from journal",
        "high",
    )
