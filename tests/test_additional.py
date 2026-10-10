from pi_monitor.config import Config
from pi_monitor.monitors.filesystem import FilesystemMonitor, mount_type
from pi_monitor.monitors.public_ip import PublicIpMonitor
from pi_monitor.monitors.throttling import ThrottlingMonitor, decode_throttled
from pi_monitor.monitors.updates import UpdatesMonitor


def test_voltage_bits_and_transitions():
    current, history = decode_throttled(0x50005)
    assert current == history == ["undervoltage", "throttling"]
    calls = []
    monitor = ThrottlingMonitor(Config(), {}, lambda *args: calls.append(args))
    for mask in [0, 0x50005, 0x50005, 0x50000, 0x50000]:
        monitor.sample(mask)
    assert len(calls) == 2 and "Current: normal" in calls[-1][1]


def test_filesystem_transition_and_mounts():
    calls = []
    monitor = FilesystemMonitor(Config(), {}, lambda *args: calls.append(args))
    for value in [False, True, True, False]:
        monitor.sample("/", value)
    assert len(calls) == 2
    text = "1 0 8:1 / / rw - ext4 /dev/root rw\n2 1 0:1 / /proc rw - proc proc rw"
    assert mount_type("/proc/meminfo", text) == "proc"
    assert mount_type("/var", text) == "ext4"


def test_public_ip_errors_are_not_changes():
    import pytest

    calls, state = [], {}
    monitor = PublicIpMonitor(Config(), state, lambda *args: calls.append(args))
    monitor.sample("192.0.2.1\n")
    with pytest.raises(ValueError):
        monitor.sample("upstream error")
    assert state["public_ip"]["address"] == "192.0.2.1" and not calls
    monitor.sample("192.0.2.2")
    monitor.sample("192.0.2.2")
    assert len(calls) == 1


def test_updates_daily_and_restart():
    calls, state = [], {}
    notify = lambda *args: calls.append(args)  # noqa: E731
    monitor = UpdatesMonitor(Config(), state, notify)
    monitor.sample(0, 5, 100000)
    monitor.sample(3, 5, 100000)
    UpdatesMonitor(Config(), state, notify).sample(4, 5, 100001)
    monitor.sample(3, 5, 200000)
    assert len(calls) == 2
