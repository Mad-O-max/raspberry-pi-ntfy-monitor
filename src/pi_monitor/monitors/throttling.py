import logging
import re
import shutil
import subprocess

from pi_monitor.state import section

LOG = logging.getLogger(__name__)
FLAGS = {0: "undervoltage", 1: "ARM frequency capped", 2: "throttling", 3: "soft temperature limit"}


def decode_throttled(mask: int) -> tuple[list[str], list[str]]:
    return (
        [label for bit, label in FLAGS.items() if mask & (1 << bit)],
        [label for bit, label in FLAGS.items() if mask & (1 << (bit + 16))],
    )


class ThrottlingMonitor:
    def __init__(self, config, state, notify):
        self.notify = notify
        self.data = section(state, "throttling", {"mask": 0})
        self.command = shutil.which("vcgencmd")
        if not self.command:
            LOG.info("vcgencmd absent; throttling monitor disabled")

    def sample(self, mask: int) -> None:
        mask &= 0xF000F
        if mask == self.data["mask"]:
            return
        previous_current = bool(self.data["mask"] & 0xF)
        current, historical = decode_throttled(mask)
        self.data["mask"] = mask
        title = (
            "Raspberry Pi power/thermal warning" if current else "Raspberry Pi power/thermal normal"
        )
        if not current and historical and not previous_current:
            title = "Raspberry Pi power/thermal history changed"
        self.notify(
            title,
            "Current: "
            + (", ".join(current) or "normal")
            + "\nSince boot: "
            + (", ".join(historical) or "none")
            + "\nHistorical flags do not indicate a current fault.",
            "high" if current else "default",
        )

    def read(self) -> int | None:
        if not self.command:
            return
        result = subprocess.run(
            [self.command, "get_throttled"], capture_output=True, text=True, timeout=5, check=True
        )
        match = re.fullmatch(r"throttled=(0x[0-9a-fA-F]+)\s*", result.stdout)
        if not match:
            raise ValueError("Unrecognized vcgencmd response")
        return int(match[1], 16)

    def apply(self, result: int | None, now: float) -> None:
        if result is not None:
            self.sample(result)
