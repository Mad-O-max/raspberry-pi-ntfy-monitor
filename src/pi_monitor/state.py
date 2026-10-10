"""Versioned, size-bounded JSON and durable atomic replacement."""

import fcntl
import json
import logging
import math
import os
import tempfile
from pathlib import Path

LOG = logging.getLogger(__name__)
MAX_BYTES = 2_000_000


def valid_tree(value, depth: int = 0) -> bool:
    if depth > 12:
        return False
    if value is None or type(value) in (str, bool, int):
        return not isinstance(value, str) or len(value) < 65536
    if type(value) is float:
        return math.isfinite(value)
    if isinstance(value, dict):
        return len(value) <= 20000 and all(
            isinstance(k, str) and valid_tree(v, depth + 1) for k, v in value.items()
        )
    if isinstance(value, list):
        return len(value) <= 10000 and all(valid_tree(v, depth + 1) for v in value)
    return False


class StateStore:
    def __init__(self, directory: str):
        self.directory = Path(directory)
        self.path = self.directory / "state.json"
        self.lock_file = None

    def lock(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock_file = (self.directory / "daemon.lock").open("a")
        try:
            fcntl.flock(self.lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock_file.close()
            self.lock_file = None
            raise RuntimeError("Another monitor instance holds the state lock") from None

    def close(self) -> None:
        if self.lock_file:
            self.lock_file.close()
            self.lock_file = None

    def load(self) -> dict:
        try:
            with self.path.open("rb") as handle:
                raw = handle.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise ValueError("oversized state")
            value = json.loads(raw)
            if (
                not isinstance(value, dict)
                or value.get("version") != 1
                or not isinstance(value.get("data"), dict)
                or not valid_tree(value)
            ):
                raise ValueError("invalid state structure")
            return value["data"]
        except FileNotFoundError:
            return {}
        except (OSError, ValueError, RecursionError):
            LOG.warning("State unavailable or corrupt; using safe defaults")
            return {}

    def save(self, data: dict) -> None:
        if not valid_tree(data):
            raise ValueError("Invalid runtime state")
        raw = json.dumps({"version": 1, "data": data}, allow_nan=False).encode()
        if len(raw) > MAX_BYTES:
            raise ValueError("State size limit exceeded")
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, name = tempfile.mkstemp(prefix=".state-", dir=self.directory)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(name, self.path)
            directory_fd = os.open(self.directory, os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            Path(name).unlink(missing_ok=True)


def section(state: dict, key: str, defaults: dict) -> dict:
    """Discard malformed fields before consumers use persisted values."""
    old = state.get(key)
    old = old if isinstance(old, dict) else {}
    result = {}
    for name, default in defaults.items():
        value = old.get(name, default)
        if type(default) is float:
            ok = type(value) in (int, float) and math.isfinite(value) and value >= 0
        else:
            ok = type(value) is type(default)
        result[name] = value if ok else default
    state[key] = result
    return result
