import json
import subprocess
from datetime import datetime
from pathlib import Path

from pi_monitor.state import section


class UpdatesMonitor:
    def __init__(self, config, state, notify):
        self.notify = notify
        self.data = section(state, "updates", {"last_notification": 0.0, "day": ""})

    def sample(self, security: int, other: int, now: float) -> None:
        day = datetime.fromtimestamp(now).astimezone().date().isoformat()
        if security <= 0 or day == self.data["day"]:
            return
        if now - self.data["last_notification"] < 86400:
            return
        self.notify(
            "Security updates available",
            f"{security} security updates\n"
            f"{other} other package updates\nBased on locally cached APT metadata.",
        )
        self.data.update(last_notification=now, day=day)

    def read(self) -> tuple[int, int]:
        helper = Path(__file__).resolve().parents[1] / "apt_helper.py"
        result = subprocess.run(
            ["/usr/bin/python3", str(helper)],
            capture_output=True,
            text=True,
            timeout=45,
            check=True,
        )
        counts = json.loads(result.stdout)
        if not all(type(counts.get(k)) is int and counts[k] >= 0 for k in ("security", "other")):
            raise ValueError("Invalid APT counts")
        return counts["security"], counts["other"]

    def apply(self, result: tuple[int, int], now: float) -> None:
        self.sample(*result, now)
