import ipaddress
from urllib.request import build_opener

from pi_monitor.notifier import NoRedirect
from pi_monitor.state import section


class PublicIpMonitor:
    def __init__(self, config, state, notify, opener=None):
        self.config, self.notify = config, notify
        self.opener = opener or build_opener(NoRedirect())
        self.data = section(state, "public_ip", {"address": ""})

    def sample(self, value: str) -> None:
        address = str(ipaddress.IPv4Address(value.strip()))
        previous = self.data["address"]
        if previous and previous != address:
            self.notify("Public IP changed", f"Old: {previous}\nNew: {address}")
        self.data["address"] = address

    def read(self) -> str:
        with self.opener.open(
            self.config.public_ip_url, timeout=self.config.http_timeout
        ) as response:
            return response.read(128).decode("ascii")

    def apply(self, result: str, now: float) -> None:
        self.sample(result)
