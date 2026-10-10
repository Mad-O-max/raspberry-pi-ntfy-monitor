"""One nonblocking journal follower with cursor resume and bounded line buffering."""

import json
import logging
import os
import subprocess
from datetime import UTC, datetime

from .monitors.fail2ban import handle_ban, parse_ban
from .monitors.ssh import parse_ssh

LOG = logging.getLogger(__name__)
FILTER = [
    "_SYSTEMD_UNIT=ssh.service",
    "_SYSTEMD_UNIT=sshd.service",
    "_SYSTEMD_UNIT=fail2ban.service",
    "SYSLOG_IDENTIFIER=sshd",
    "SYSLOG_IDENTIFIER=sshd-session",
    "SYSLOG_IDENTIFIER=fail2ban",
    "_TRANSPORT=kernel",
]


class JournalFollower:
    def __init__(self, state: dict):
        self.state = state
        self.process = None
        self.buffer = b""
        self.discard_line = False
        self.next_start = 0.0
        self.started = 0.0
        self.used_cursor = False

    def _start(self, now: float) -> None:
        command = ["journalctl", "--follow", "--output=json", "--no-pager", "--all"]
        cursor = self.state.get("journal_cursor")
        self.used_cursor = isinstance(cursor, str) and bool(cursor) and len(cursor) < 4096
        if self.used_cursor:
            command += ["--after-cursor=" + cursor]
        else:
            command += ["--since=-2min"]
        for index, expression in enumerate(FILTER):
            if index:
                command.append("+")
            command.append(expression)
        self.process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        os.set_blocking(self.process.stdout.fileno(), False)
        self.started = now
        self.buffer = b""
        self.discard_line = False

    def poll(self, now: float) -> list[dict]:
        if self.process is None:
            if now < self.next_start:
                return []
            try:
                self._start(now)
            except OSError:
                LOG.warning("Cannot start journal follower; retrying in 30s")
                self.next_start = now + 30
                return []
        entries = []
        # Read a bounded chunk per loop; pipe backpressure bounds producer memory.
        try:
            chunk = os.read(self.process.stdout.fileno(), 65536)
        except BlockingIOError:
            return []
        if not chunk:
            code = self.process.poll()
            if code is not None:
                LOG.warning("Journal follower exited (%s); retrying in 30s", code)
                if self.used_cursor and code != 0 and now - self.started < 5:
                    self.state.pop("journal_cursor", None)
                    LOG.warning("Journal cursor may be unavailable; falling back to recent entries")
                self.close()
                self.next_start = now + 30
            return []
        if self.discard_line:
            pos = chunk.find(b"\n")
            if pos == -1:
                return []
            chunk = chunk[pos + 1 :]
            self.discard_line = False
        self.buffer += chunk
        lines = self.buffer.split(b"\n")
        self.buffer = lines.pop()
        if len(self.buffer) > 131072:
            self.buffer = b""
            self.discard_line = True
            LOG.warning("Oversized journal entry discarded")
        for line in lines:
            if len(line) > 131072:
                continue
            try:
                entry = json.loads(line)
                if isinstance(entry, dict) and isinstance(entry.get("MESSAGE"), str):
                    entries.append(entry)
            except (ValueError, UnicodeError):
                LOG.debug("Invalid journal entry skipped")
        return entries

    def close(self) -> None:
        if self.process:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=3)
            self.process.stdout.close()
            self.process = None


class JournalRouter:
    def __init__(self, state, aggregator, notify):
        self.state, self.aggregator, self.notify = state, aggregator, notify
        self.last_kernel = {}

    def handle(self, entry: dict, now: float) -> None:
        cursor = entry.get("__CURSOR")
        if cursor and cursor == self.state.get("journal_cursor"):
            return
        message = entry.get("MESSAGE", "")
        identifier = entry.get("SYSLOG_IDENTIFIER", "")
        unit = entry.get("_SYSTEMD_UNIT", "")
        if not isinstance(identifier, str):
            identifier = ""
        if not isinstance(unit, str):
            unit = ""
        try:
            timestamp = datetime.fromtimestamp(int(entry["__REALTIME_TIMESTAMP"]) / 1e6, UTC)
        except (KeyError, ValueError, TypeError, OverflowError, OSError):
            timestamp = datetime.fromtimestamp(now, UTC)
        if identifier in {"sshd", "sshd-session"} or unit in {"ssh.service", "sshd.service"}:
            event = parse_ssh(message, timestamp)
            if event:
                self.aggregator.accept(event, now)
        if identifier.startswith("fail2ban") or unit == "fail2ban.service":
            event = parse_ban(message)
            if event:
                handle_ban(event, self.aggregator, self.notify)
        if entry.get("_TRANSPORT") == "kernel":
            lower = message.lower()
            title = None
            if any(
                s in lower
                for s in ("out of memory: killed process", "oom-kill:", "invoked oom-killer")
            ):
                title = "OOM killer activated"
            elif any(
                s in lower
                for s in (
                    "ext4-fs error",
                    "btrfs error",
                    "xfs corruption",
                    "remounting filesystem read-only",
                    "i/o error",
                )
            ):
                title = "Kernel filesystem/storage error"
            elif any(
                s in lower
                for s in (
                    "kernel panic",
                    "hard lockup",
                    "soft lockup",
                    "critical temperature",
                    "under-voltage detected",
                )
            ):
                title = "Kernel hardware/system warning"
            if title and now - self.last_kernel.get(title, -float("inf")) >= 60:
                self.notify(title, message[:2000], "high")
                self.last_kernel[title] = now
        if isinstance(cursor, str) and len(cursor) < 4096:
            self.state["journal_cursor"] = cursor
