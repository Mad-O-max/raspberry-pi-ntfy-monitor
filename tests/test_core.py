from dataclasses import replace

import pytest

from pi_monitor.config import Config
from pi_monitor.monitors.boot import classify_reboot, startup
from pi_monitor.monitors.disk import DiskMonitor
from pi_monitor.monitors.load import LoadMonitor
from pi_monitor.monitors.memory import MemoryMonitor
from pi_monitor.monitors.network import NetworkMonitor
from pi_monitor.monitors.temperature import TemperatureMonitor


def collector():
    calls = []
    return calls, lambda *args: calls.append(args)


def test_temperature_peak_hysteresis_and_restart():
    calls, notify = collector()
    state = {}
    monitor = TemperatureMonitor(Config(), state, notify)
    for now, value in enumerate([79, 80, 85, 79], 100):
        monitor.sample(value, now)
    assert len(calls) == 1
    TemperatureMonitor(Config(), state, notify).sample(75, 120)
    assert len(calls) == 2
    assert "85.0" in calls[1][1] and "19s" in calls[1][1]


def test_disk_strict_thresholds():
    calls, notify = collector()
    monitor = DiskMonitor(Config(), {}, notify)
    for now, free in enumerate([10, 9, 8, 12, 15, 16], 100):
        monitor.sample("/", free, 100, now)
    assert len(calls) == 2
    assert calls[0][0] == "Low disk space"
    assert "8.0" in calls[1][1]


def test_network_flapping_and_restart():
    calls, notify = collector()
    state = {}
    monitor = NetworkMonitor(Config(), state, notify)
    for now, success in enumerate([False, True, False, False, False, True, False], 100):
        monitor.sample(success, now)
    assert calls == [] and state["network"]["down"]
    monitor = NetworkMonitor(Config(), state, notify)
    monitor.sample(True, 120)
    monitor.sample(True, 121)
    assert len(calls) == 1 and "19s" in calls[0][1]
    assert not state["network"]["down"]


def test_load_requires_sustained_high():
    calls, notify = collector()
    monitor = LoadMonitor(replace(Config(), load_sustain=10), {}, notify)
    for now, load in [(100, 8), (105, 2), (110, 8), (119, 9), (120, 8), (125, 4)]:
        monitor.sample(load, 4, now)
    assert len(calls) == 2


def test_memory_available_absolute_and_percent():
    calls, notify = collector()
    monitor = MemoryMonitor(Config(), {}, notify)
    monitor.sample(150 * 2**20, 8 * 2**30, 100)  # low percentage, enough absolute memory
    assert not calls
    monitor.sample(80 * 2**20, 8 * 2**30, 110)
    monitor.sample(90 * 2**20, 8 * 2**30, 120)
    monitor.sample(220 * 2**20, 8 * 2**30, 130)
    assert len(calls) == 2


@pytest.mark.parametrize(
    "lines,fragment,confidence",
    [
        ([], "unknown", "low"),
        (["watchdog initialized"], "abrupt", "low"),
        (["systemd-shutdown: Syncing filesystems"], "clean", "medium"),
        (["Kernel panic - not syncing: fatal"], "panic", "medium"),
        (["Out of memory: Killed process 100"], "OOM", "low"),
        (["Under-voltage detected!"], "power", "low"),
        (["critical temperature reached"], "thermal", "medium"),
    ],
)
def test_boot_reason(lines, fragment, confidence):
    reason = classify_reboot(lines)
    assert fragment in reason.classification
    assert reason.confidence == confidence


def test_boot_vs_application_restart():
    calls, notify = collector()
    state = {}
    startup(state, "boot-a", 10, 100, notify, [])
    startup(state, "boot-a", 15, 105, notify, [])
    state["clean_exit"] = True
    startup(state, "boot-a", 20, 110, notify, [])
    startup(state, "boot-b", 5, 120, notify, [])
    assert [call[0] for call in calls] == [
        "Raspberry Pi started",
        "Pi monitor restarted",
        "Raspberry Pi started",
    ]
