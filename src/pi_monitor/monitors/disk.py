import os

from .filesystem import PSEUDO, mount_type
from .threshold import Threshold, describe


class DiskMonitor:
    def __init__(self, config, state, notify):
        self.thresholds = {
            path: Threshold(
                state,
                "disk:" + path,
                config.disk_alert,
                config.disk_clear,
                low=True,
                inclusive=False,
            )
            for path in config.disk_paths
        }
        self.notify = notify

    def sample(self, path: str, available: int, total: int, now: float) -> None:
        if total <= 0:
            return
        event = self.thresholds[path].sample(100 * available / total, now)
        if event:
            self.notify(
                "Low disk space" if event.active else "Disk space recovered",
                f"Filesystem: {path}\n{describe(event, '% free')}\n"
                f"Available: {available / 2**30:.1f} GiB\nTotal: {total / 2**30:.1f} GiB",
                "high" if event.active else "default",
            )

    def read(self) -> list[tuple[str, int, int]]:
        result = []
        for path in self.thresholds:
            if mount_type(path) in PSEUDO:
                continue
            fs = os.statvfs(path)
            result.append((path, fs.f_bavail * fs.f_frsize, fs.f_blocks * fs.f_frsize))
        return result

    def apply(self, result: list[tuple[str, int, int]], now: float) -> None:
        for path, available, total in result:
            self.sample(path, available, total, now)
