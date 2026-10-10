import json
from dataclasses import replace

import pytest

from pi_monitor.config import Config
from pi_monitor.notifier import Notification, Notifier
from pi_monitor.state import StateStore


def test_config_and_redaction():
    c = Config.from_env({"PI_NTFY_TOPIC": "test-topic", "PI_NTFY_TOKEN": "synthetic-token"})
    assert "synthetic-token" not in repr(c)
    assert "synthetic-token" not in json.dumps(c.redacted())


@pytest.mark.parametrize(
    "setting,value",
    [
        ("HTTP_TIMEOUT", "nan"),
        ("DISK_CLEAR", "5"),
        ("NTFY_URL", "http://example.org"),
        ("NETWORK_FAILURES", "0"),
        ("PUBLIC_IP_ENABLED", "perhaps"),
        ("NTFY_TOPIC", ""),
        ("NTFY_TOKEN", "bad\nheader"),
        ("LOAD_CLEAR", "2"),
        ("UNKNOWN", "x"),
    ],
)
def test_bad_config(setting, value):
    with pytest.raises(ValueError):
        Config.from_env({"PI_NTFY_TOPIC": "test-topic", "PI_" + setting: value})


def test_state_roundtrip_corruption_and_lock(tmp_path):
    store = StateStore(str(tmp_path))
    assert store.load() == {}
    store.lock()
    with pytest.raises(RuntimeError):
        StateStore(str(tmp_path)).lock()
    store.save({"boot_id": "synthetic", "temperature": {"active": True}})
    assert store.load()["temperature"]["active"]
    assert store.path.stat().st_mode & 0o777 == 0o600
    store.path.write_text('{"version":1,"data":[] }')
    assert store.load() == {}
    store.path.write_text("broken")
    assert store.load() == {}
    store.close()


def test_ntfy_request_and_queue():
    config = replace(Config(), ntfy_topic="test-topic", ntfy_token="fake", queue_size=2)
    clock = [100.0]
    notifier = Notifier(config, clock=lambda: clock[0])
    request = notifier.request(Notification("CPU °C", "hello", "high"))
    assert request.full_url == "https://ntfy.sh/"
    assert request.get_header("Authorization") == "Bearer fake"
    assert json.loads(request.data)["priority"] == 4
    assert notifier.notify("same", "message")
    assert not notifier.notify("same", "message")
    notifier.notify("second", "message")
    notifier.notify("third", "message")
    assert len(notifier.pending) == 2
    assert notifier.dropped == 1
    clock[0] += 61
    assert notifier.notify("same", "message")


def test_invalid_url_port():
    with pytest.raises(ValueError):
        Config.from_env({"PI_NTFY_TOPIC": "test", "PI_NTFY_URL": "https://example.org:bad"})
