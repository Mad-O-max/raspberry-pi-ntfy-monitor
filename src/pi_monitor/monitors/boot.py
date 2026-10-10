import json
import logging
import subprocess
from datetime import datetime
from pathlib import Path

from pi_monitor.models import RebootReason

LOG = logging.getLogger(__name__)


def classify_reboot(messages: list[str]) -> RebootReason:
    if not messages:
        return RebootReason("unknown", "low", ("Previous boot journal unavailable",))
    text = "\n".join(messages).lower()
    # Explicit fatal/reset evidence outranks routine warnings, but ordinary watchdog
    # initialization and historical voltage bits are not proof of a reset.
    for words, label in [
        (("kernel panic -", "not syncing:"), "kernel panic indication"),
        (
            ("watchdog reset", "watchdog: hard lockup", "watchdog: soft lockup"),
            "watchdog/lockup indication",
        ),
        (("critical temperature reached", "thermal shutdown"), "thermal problem indication"),
    ]:
        if any(word in text for word in words):
            return RebootReason(label, "medium", ("Fatal indication in previous boot journal",))
    if any(
        word in text
        for word in (
            "reboot: restarting system",
            "systemd-shutdown",
            "reached target system reboot",
            "reached target system power off",
        )
    ):
        return RebootReason(
            "probable clean shutdown/reboot",
            "medium",
            ("Shutdown sequence present; completed power transition unverified",),
        )
    if any(word in text for word in ("reboot requested", "the system will reboot now")):
        return RebootReason("user/system requested reboot", "low", ("Reboot request recorded",))
    if "out of memory: killed process" in text or "oom-kill:" in text:
        return RebootReason(
            "possible OOM-related crash",
            "low",
            ("OOM event present, but does not prove the reboot cause",),
        )
    if "under-voltage detected" in text or "undervoltage detected" in text:
        return RebootReason(
            "possible power-related interruption",
            "low",
            ("Undervoltage recorded without a visible shutdown sequence",),
        )
    return RebootReason(
        "abrupt shutdown / possible power loss or hard reset",
        "low",
        ("No shutdown sequence in available journal tail; logs may be incomplete",),
    )


def previous_boot_messages() -> list[str]:
    try:
        result = subprocess.run(
            ["journalctl", "-b", "-1", "-n", "1000", "-o", "json", "--no-pager"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        if result.returncode:
            return []
        messages = []
        for line in result.stdout.splitlines():
            try:
                entry = json.loads(line)
                if isinstance(entry.get("MESSAGE"), str):
                    identifier = entry.get("SYSLOG_IDENTIFIER", "")
                    prefix = identifier + ": " if isinstance(identifier, str) else ""
                    messages.append(prefix + entry["MESSAGE"][:4096])
            except (ValueError, AttributeError):
                continue
        return messages
    except (OSError, subprocess.TimeoutExpired):
        return []


def startup(state: dict, boot_id: str, uptime: float, now: float, notify, messages=None) -> None:
    previous_id = state.get("boot_id")
    if previous_id != boot_id:
        reason = classify_reboot(previous_boot_messages() if messages is None else messages)
        previous = state.get("last_uptime")
        previous_text = f"at least {previous:.0f}s" if type(previous) in (float, int) else "unknown"
        boot_time = datetime.fromtimestamp(now - uptime).astimezone().isoformat()
        notify(
            "Raspberry Pi started",
            f"Boot time: {boot_time}\nPrevious uptime: {previous_text}\n"
            f"Previous shutdown: {reason.classification}\nConfidence: {reason.confidence}\n"
            + "\n".join(reason.evidence),
        )
        # Boot-scoped state must not mix metrics/cursors across different boots.
        for key in list(state):
            if key not in {"public_ip", "updates", "network"}:
                state.pop(key)
    elif state.get("clean_exit") is False:
        notify(
            "Pi monitor restarted",
            "Previous monitor instance appears to have terminated unexpectedly",
            "high",
        )
    state.update(boot_id=boot_id, clean_exit=False, last_uptime=uptime)


def boot_identity() -> tuple[str, float]:
    return (
        Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        float(Path("/proc/uptime").read_text().split()[0]),
    )
