from pathlib import Path

from .threshold import Threshold


def read_memory() -> tuple[int, int]:
    values = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        name, value = line.split(":", 1)
        values[name] = int(value.split()[0]) * 1024
    # MemAvailable accounts for reclaimable cache; MemFree alone is misleading.
    return values["MemAvailable"], values["MemTotal"]


class MemoryMonitor:
    def __init__(self, config, state, notify):
        self.config, self.notify = config, notify
        # A normalized margin combines percent AND absolute critical thresholds.
        self.threshold = Threshold(state, "memory", 1, 2, low=True)

    def sample(self, available: int, total: int, now: float) -> None:
        c = self.config
        percent, mib = 100 * available / total, available / 2**20
        bad = percent <= c.memory_alert_percent and mib <= c.memory_alert_mib
        good = percent >= c.memory_clear_percent or mib >= c.memory_clear_mib
        marker = 0 if bad else 2 if good else 1.5
        event = self.threshold.sample(marker, now)
        if event:
            self.notify(
                "Critical memory pressure" if event.active else "Memory recovered",
                f"MemAvailable: {mib:.1f} MiB ({percent:.1f}%)\nDuration: {event.duration:.0f}s",
                "high" if event.active else "default",
            )

    def read(self) -> tuple[int, int]:
        return read_memory()

    def apply(self, result: tuple[int, int], now: float) -> None:
        self.sample(*result, now)
