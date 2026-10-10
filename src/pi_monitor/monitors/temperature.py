from pathlib import Path

from .threshold import Threshold, describe


class TemperatureMonitor:
    def __init__(self, config, state, notify):
        self.path = Path(config.temperature_path)
        self.threshold = Threshold(
            state, "temperature", config.temperature_alert, config.temperature_clear
        )
        self.notify = notify

    def sample(self, celsius: float, now: float) -> None:
        event = self.threshold.sample(celsius, now)
        if event:
            self.notify(
                "High CPU temperature" if event.active else "CPU temperature normal",
                describe(event, "°C"),
                "high" if event.active else "default",
            )

    def read(self) -> float:
        return float(self.path.read_text()) / 1000

    def apply(self, result: float, now: float) -> None:
        self.sample(result, now)
