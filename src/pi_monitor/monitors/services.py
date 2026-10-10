import subprocess
from pathlib import Path

from pi_monitor.state import section


def shutting_down() -> bool:
    if Path("/run/systemd/shutdown/scheduled").exists():
        return True
    result = subprocess.run(
        ["systemctl", "is-system-running"], capture_output=True, text=True, timeout=5, check=False
    )
    return result.stdout.strip() in {"stopping", "offline"}


class ServicesMonitor:
    def __init__(self, config, state, notify):
        self.services, self.notify = config.critical_services, notify
        self.states = {s: section(state, "service:" + s, {"failed": False}) for s in self.services}

    def sample(self, service: str, active: str, shutdown: bool = False) -> None:
        if shutdown or active in {"activating", "deactivating", "reloading", "refreshing", ""}:
            return
        failed = active != "active"
        if failed != self.states[service]["failed"]:
            self.states[service]["failed"] = failed
            self.notify(
                "Critical service unhealthy" if failed else "Critical service recovered",
                f"Service: {service}\nState: {active}",
                "high" if failed else "default",
            )

    def read(self) -> list[tuple[str, str]]:
        if shutting_down():
            return []
        result = []
        for service in self.services:
            command = ["systemctl", "show", "--property=ActiveState", "--value", service]
            response = subprocess.run(
                command, capture_output=True, text=True, timeout=5, check=True
            )
            result.append((service, response.stdout.strip()))
        return [] if shutting_down() else result

    def apply(self, result: list[tuple[str, str]], now: float) -> None:
        for service, active in result:
            self.sample(service, active)
