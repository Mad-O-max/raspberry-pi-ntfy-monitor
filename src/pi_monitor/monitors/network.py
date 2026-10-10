import socket
from datetime import datetime

from pi_monitor.state import section


def probe(targets: tuple[str, ...], timeout: float) -> bool:
    for target in targets:
        host, port = target.rsplit(":", 1)
        try:
            with socket.create_connection((host.strip("[]"), int(port)), timeout=timeout):
                return True
        except OSError:
            continue
    return False


class NetworkMonitor:
    def __init__(self, config, state, notify):
        self.config, self.notify = config, notify
        self.data = section(
            state,
            "network",
            {
                "down": False,
                "started": 0.0,
                "first_failure": 0.0,
                "failures": 0,
                "successes": 0,
            },
        )

    def sample(self, success: bool, now: float) -> None:
        d = self.data
        if success:
            d["failures"] = 0
            d["successes"] = min(d["successes"] + 1, self.config.network_successes)
            if d["down"] and d["successes"] >= self.config.network_successes:
                started = datetime.fromtimestamp(d["started"]).astimezone().isoformat()
                restored = datetime.fromtimestamp(now).astimezone().isoformat()
                self.notify(
                    "Internet connection restored",
                    f"Down for: {max(0, now - d['started']):.0f}s\n"
                    f"Started: {started}\nRestored: {restored}",
                )
                d.update(down=False, started=0.0)
            if not d["down"]:
                d["first_failure"] = 0.0
        else:
            d["successes"] = 0
            if not d["failures"]:
                d["first_failure"] = now
            d["failures"] = min(d["failures"] + 1, self.config.network_failures)
            if not d["down"] and d["failures"] >= self.config.network_failures:
                d.update(down=True, started=d["first_failure"])

    def read(self) -> bool:
        return probe(self.config.connectivity_targets, min(3, self.config.http_timeout))

    def apply(self, result: bool, now: float) -> None:
        self.sample(result, now)
