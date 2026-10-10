import os

from .threshold import Threshold, describe


class LoadMonitor:
    def __init__(self, config, state, notify):
        self.threshold = Threshold(
            state, "load", config.load_alert, config.load_clear, sustain=config.load_sustain
        )
        self.notify = notify

    def sample(self, load: float, cores: int, now: float) -> None:
        event = self.threshold.sample(load / max(1, cores), now)
        if event:
            self.notify(
                "Sustained high load" if event.active else "System load normal",
                f"Cores: {cores}\n{describe(event, 'load/core')}",
            )

    def read(self) -> tuple[float, int]:
        return os.getloadavg()[0], os.cpu_count() or 1

    def apply(self, result: tuple[float, int], now: float) -> None:
        self.sample(*result, now)
