"""Reusable hysteresis with sustained-entry timing and persisted extremes."""

from dataclasses import dataclass

from pi_monitor.state import section


@dataclass(frozen=True)
class Transition:
    active: bool
    value: float
    worst: float
    duration: float


class Threshold:
    def __init__(
        self,
        state: dict,
        key: str,
        alert: float,
        clear: float,
        *,
        low: bool = False,
        sustain: float = 0,
        inclusive: bool = True,
    ):
        self.data = section(
            state,
            key,
            {
                "active": False,
                "started": 0.0,
                "pending": 0.0,
                "worst": 0.0,
            },
        )
        self.alert, self.clear = alert, clear
        self.low, self.sustain, self.inclusive = low, sustain, inclusive
        if sustain and not self.data["active"]:
            # A monitoring gap cannot establish continuously high load.
            self.data["pending"] = 0.0

    def sample(self, value: float, now: float) -> Transition | None:
        if self.low:
            bad = value <= self.alert if self.inclusive else value < self.alert
            good = value >= self.clear if self.inclusive else value > self.clear
        else:
            bad = value >= self.alert if self.inclusive else value > self.alert
            good = value <= self.clear if self.inclusive else value < self.clear
        d = self.data
        if d["active"]:
            d["worst"] = min(d["worst"], value) if self.low else max(d["worst"], value)
            if good:
                event = Transition(False, value, d["worst"], max(0, now - d["started"]))
                d.update(active=False, pending=0.0)
                return event
        elif bad:
            if not d["pending"] or d["pending"] > now:
                d["pending"] = now
                d["worst"] = value
            d["worst"] = min(d["worst"], value) if self.low else max(d["worst"], value)
            if now - d["pending"] >= self.sustain:
                d.update(active=True, started=d["pending"], pending=0.0)
                return Transition(True, value, d["worst"], 0)
        else:
            d["pending"] = 0.0
        return None


def describe(event: Transition, unit: str) -> str:
    return (
        f"Current: {event.value:.1f} {unit}\nWorst: {event.worst:.1f} {unit}"
        f"\nDuration: {event.duration:.0f}s"
    )
