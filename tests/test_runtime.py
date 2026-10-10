import io
import json
import os
import signal
import subprocess
import sys
import threading
import time
from dataclasses import replace
from unittest.mock import Mock
from urllib.error import HTTPError, URLError

import pytest

from pi_monitor.app import PollJob
from pi_monitor.config import Config
from pi_monitor.journal import JournalFollower
from pi_monitor.notifier import NoRedirect, Notification, Notifier
from pi_monitor.state import StateStore, section


def test_notifier_retries_without_credentials_in_logs(caplog):
    opener = Mock()
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    opener.open.side_effect = [URLError("secret-topic fake-token"), response]
    notifier = Notifier(replace(Config(), retries=2, retry_backoff=0.001), opener=opener)
    assert notifier.deliver(Notification("test", "message"))
    assert opener.open.call_count == 2
    assert "fake-token" not in caplog.text and "secret-topic" not in caplog.text


def test_http_permanent_failure_no_retry():
    opener = Mock()
    opener.open.side_effect = HTTPError("https://example.org", 401, "denied", {}, io.BytesIO())
    notifier = Notifier(Config(), opener=opener)
    assert not notifier.deliver(Notification("test", "message"))
    assert opener.open.call_count == 1
    assert NoRedirect().redirect_request(None, None, 302, "", {}, "https://other.invalid") is None


def test_notification_rate_limit_and_expiry():
    config = replace(Config(), notification_interval=0.05, notification_ttl=0.1, retries=1)
    notifier = Notifier(config)
    sent = []
    finished = threading.Event()

    def deliver(note):
        sent.append(time.monotonic())
        if len(sent) == 2:
            finished.set()
        return True

    notifier.deliver = deliver
    notifier.pending.append(Notification("expired", "message", created=time.monotonic() - 1))
    notifier.notify("first", "a")
    notifier.notify("second", "b")
    notifier.start()
    try:
        assert finished.wait(2)
        assert len(sent) == 2 and sent[1] - sent[0] >= 0.045
    finally:
        notifier.close()


def test_poll_job_slow_read_does_not_block_or_overlap():
    release = threading.Event()
    read_started = threading.Event()
    applied = []

    class Monitor:
        def read(self):
            read_started.set()
            release.wait(2)
            return 42

        def apply(self, result, now):
            applied.append(result)

    job = PollJob("fake", Monitor(), 30)
    job.step(100, 100)
    assert read_started.wait(1)
    thread = job.thread
    job.step(110, 110)
    assert job.thread is thread and not applied
    release.set()
    thread.join(1)
    job.step(111, 111)
    assert applied == [42] and job.next_due == 141


def test_journal_filter_is_disjunction_and_cursor_used(monkeypatch):
    process = Mock()
    process.stdout.fileno.return_value = 1
    popen = Mock(return_value=process)
    monkeypatch.setattr("pi_monitor.journal.subprocess.Popen", popen)
    monkeypatch.setattr("pi_monitor.journal.os.set_blocking", lambda *args: None)
    journal = JournalFollower({"journal_cursor": "synthetic-cursor"})
    journal._start(100)
    command = popen.call_args.args[0]
    assert "--after-cursor=synthetic-cursor" in command
    assert command.count("+") == 6


def test_journal_partial_lines_and_corruption():
    read_fd, write_fd = os.pipe()
    os.set_blocking(read_fd, False)
    process = Mock()
    process.stdout.fileno.return_value = read_fd
    journal = JournalFollower({})
    journal.process = process
    try:
        os.write(write_fd, b'{"MESSAGE":"hello')
        assert journal.poll(1) == []
        os.write(write_fd, b'"}\nbroken\n{"MESSAGE":"next"}\n')
        assert [e["MESSAGE"] for e in journal.poll(2)] == ["hello", "next"]
        os.write(write_fd, b'{"MESSAGE":[1,2,3]}\n')
        assert journal.poll(3) == []
    finally:
        os.close(write_fd)
        os.close(read_fd)


def test_atomic_failure_preserves_previous_file(tmp_path, monkeypatch):
    store = StateStore(str(tmp_path))
    store.save({"value": 1})
    monkeypatch.setattr("pi_monitor.state.os.replace", Mock(side_effect=OSError("full")))
    with pytest.raises(OSError):
        store.save({"value": 2})
    assert store.load() == {"value": 1}
    assert not list(tmp_path.glob(".state-*"))


def test_malformed_monitor_state():
    state = {"temperature": {"active": "yes", "started": -5, "worst": []}}
    assert section(state, "temperature", {"active": False, "started": 0.0, "worst": 0.0}) == {
        "active": False,
        "started": 0.0,
        "worst": 0.0,
    }


def test_daemon_sigterm_clean_restart_without_network(tmp_path):
    # Integration runs a real daemon loop but replaces all IO adapters before run.
    code = """
import dataclasses, sys
import pi_monitor.app as app
from pi_monitor.config import Config
class QuietMonitor:
    def __init__(self, *args): pass
    def read(self): return None
    def apply(self, value, now): pass
class QuietNotifier:
    def __init__(self, *args): pass
    def notify(self, *args): return True
    def start(self): pass
    def close(self): pass
class QuietJournal:
    def __init__(self, *args): pass
    def poll(self, now): return []
    def close(self): pass
for name in ['TemperatureMonitor', 'DiskMonitor', 'MemoryMonitor', 'LoadMonitor',
             'NetworkMonitor', 'ServicesMonitor', 'ThrottlingMonitor', 'FilesystemMonitor']:
    setattr(app, name, QuietMonitor)
app.Notifier = QuietNotifier
app.JournalFollower = QuietJournal
app.boot_identity = lambda: ('test-boot', 123.0)
import pi_monitor.monitors.boot as boot
boot.previous_boot_messages = lambda: []
app.run(dataclasses.replace(Config(), state_dir=sys.argv[1],
        ntfy_topic='test', public_ip_enabled=False, updates_enabled=False))
"""
    process = subprocess.Popen([sys.executable, "-c", code, str(tmp_path)])
    try:
        deadline = time.monotonic() + 5
        store = StateStore(str(tmp_path))
        while not store.load().get("heartbeat") and time.monotonic() < deadline:
            time.sleep(0.02)
        assert store.load()["clean_exit"] is False
        process.send_signal(signal.SIGTERM)
        assert process.wait(timeout=5) == 0
        assert store.load()["clean_exit"] is True
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def test_cli_effective_config_redacts():
    environment = {key: value for key, value in os.environ.items() if not key.startswith("PI_")}
    environment.update(PI_NTFY_TOPIC="synthetic-topic", PI_NTFY_TOKEN="synthetic-token")
    result = subprocess.run(
        [sys.executable, "-m", "pi_monitor", "--show-effective-config"],
        env=environment,
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(result.stdout)["ntfy_token"] == "<redacted>"
    assert "synthetic-token" not in result.stdout and "synthetic-topic" not in result.stdout


def test_notifier_malformed_http_response_is_retried():
    from http.client import BadStatusLine

    opener = Mock()
    opener.open.side_effect = BadStatusLine("synthetic malformed response")
    config = replace(Config(), retries=2, retry_backoff=0.001)
    assert not Notifier(config, opener=opener).deliver(Notification("test", "message"))
    assert opener.open.call_count == 2


def test_previous_boot_preserves_shutdown_identifier(monkeypatch):
    from pi_monitor.monitors.boot import classify_reboot, previous_boot_messages

    response = Mock(
        returncode=0,
        stdout=json.dumps(
            {
                "SYSLOG_IDENTIFIER": "systemd-shutdown",
                "MESSAGE": "Syncing filesystems and block devices.",
            }
        ),
    )
    monkeypatch.setattr("pi_monitor.monitors.boot.subprocess.run", Mock(return_value=response))
    assert "clean" in classify_reboot(previous_boot_messages()).classification
