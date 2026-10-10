import os
from pathlib import Path

from pi_monitor.state import section

PSEUDO = {
    "proc",
    "sysfs",
    "devtmpfs",
    "devpts",
    "tmpfs",
    "cgroup",
    "cgroup2",
    "debugfs",
    "tracefs",
    "securityfs",
    "pstore",
    "mqueue",
    "hugetlbfs",
    "fusectl",
}


def unescape_mount(text: str) -> str:
    for old, new in (("\\040", " "), ("\\011", "\t"), ("\\012", "\n"), ("\\134", "\\")):
        text = text.replace(old, new)
    return text


def mount_type(path: str, mountinfo: str | None = None) -> str | None:
    """Resolve the longest containing mount, including escaped spaces."""
    text = Path("/proc/self/mountinfo").read_text() if mountinfo is None else mountinfo
    target = str(Path(path).resolve())
    best = (0, None)
    for line in text.splitlines():
        try:
            left, right = line.split(" - ", 1)
            mount = unescape_mount(left.split()[4])
            if target == mount or target.startswith(mount.rstrip("/") + "/"):
                if len(mount) >= best[0]:
                    best = (len(mount), right.split()[0])
        except (ValueError, IndexError):
            continue
    return best[1]


class FilesystemMonitor:
    def __init__(self, config, state, notify):
        self.notify = notify
        self.paths = config.disk_paths
        self.states = {
            p: section(state, "filesystem:" + p, {"readonly": False}) for p in self.paths
        }

    def sample(self, path: str, readonly: bool) -> None:
        if readonly != self.states[path]["readonly"]:
            self.states[path]["readonly"] = readonly
            self.notify(
                "Filesystem is read-only" if readonly else "Filesystem writable again",
                f"Filesystem: {path}",
                "high" if readonly else "default",
            )

    def read(self) -> list[tuple[str, bool]]:
        return [
            (path, bool(os.statvfs(path).f_flag & os.ST_RDONLY))
            for path in self.paths
            if mount_type(path) not in PSEUDO
        ]

    def apply(self, result: list[tuple[str, bool]], now: float) -> None:
        for path, readonly in result:
            self.sample(path, readonly)
