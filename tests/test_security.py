from dataclasses import replace
from datetime import UTC, datetime

import pytest

from pi_monitor.config import Config
from pi_monitor.journal import JournalRouter
from pi_monitor.monitors.fail2ban import parse_ban
from pi_monitor.monitors.services import ServicesMonitor
from pi_monitor.monitors.ssh import SshAggregator, parse_ssh

NOW = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.mark.parametrize(
    "message,kind,user,ip",
    [
        (
            "Accepted publickey for tester from 192.0.2.1 port 22 ssh2",
            "success",
            "tester",
            "192.0.2.1",
        ),
        (
            "Failed password for invalid user admin from 192.0.2.2 port 22",
            "password_failure",
            "admin",
            "192.0.2.2",
        ),
        ("Invalid user guest from 2001:db8::1 port 22", "invalid_user", "guest", "2001:db8::1"),
        (
            "Connection closed by authenticating user root 192.0.2.3 port 22 [preauth]",
            "preauth_disconnect",
            "root",
            "192.0.2.3",
        ),
        (
            "Connection reset by invalid user user 192.0.2.4 port 22 [preauth]",
            "preauth_disconnect",
            "user",
            "192.0.2.4",
        ),
        (
            "banner exchange: Connection from 192.0.2.5 port 22: invalid format",
            "protocol",
            None,
            "192.0.2.5",
        ),
        (
            "Unable to negotiate with 192.0.2.6 port 22: no matching key exchange method [preauth]",
            "protocol",
            None,
            "192.0.2.6",
        ),
        (
            "pam_unix(sshd:auth): authentication failure; rhost=192.0.2.7 user=root",
            "authentication_failure",
            "root",
            "192.0.2.7",
        ),
    ],
)
def test_ssh_parser(message, kind, user, ip):
    event = parse_ssh(message, NOW)
    assert (event.event_type, event.username, event.source_ip) == (kind, user, ip)
    if kind == "success":
        assert event.auth_method == "publickey"


def test_normal_disconnect_ignored():
    assert parse_ssh("Disconnected from user tester 192.0.2.1 port 22", NOW) is None


def test_fail2ban():
    event = parse_ban("fail2ban.actions [100]: NOTICE [sshd] Ban 192.0.2.1")
    assert (event.source_ip, event.jail) == ("192.0.2.1", "sshd")
    assert parse_ban("[sshd] Unban 192.0.2.1") is None
    assert parse_ban("[sshd] Ban invalid") is None


def test_aggregation_rollover_and_bounded_cardinality():
    config = replace(Config(), ssh_window=10, ssh_min_events=2, ssh_max_keys=2)
    calls, state = [], {}
    notify = lambda *args: calls.append(args)  # noqa: E731
    agg = SshAggregator(config, state, notify, 100)
    for number in range(1, 6):
        event = parse_ssh(f"Invalid user u{number} from 192.0.2.{number} port 22", NOW)
        agg.accept(event, 101)
    assert len(agg.data["ips"]) == 2 and agg.data["total"] == 5
    agg = SshAggregator(config, state, notify, 109)
    agg.accept(parse_ssh("Invalid user u from 192.0.2.9 port 22", NOW), 110)
    assert len(calls) == 1 and "at least 2 unique" in calls[0][1]
    assert agg.data["total"] == 1
    agg.tick(120)
    assert len(calls) == 1 and agg.data["total"] == 0


def test_router_trust_dedup_and_oom_rate_limit():
    calls, state = [], {}
    notify = lambda *args: calls.append(args)  # noqa: E731
    agg = SshAggregator(Config(), state, notify, 100)
    router = JournalRouter(state, agg, notify)
    entry = {"MESSAGE": "Accepted publickey for tester from 192.0.2.1 port 22", "__CURSOR": "a"}
    router.handle(entry, 100)
    assert not calls
    entry.update(SYSLOG_IDENTIFIER="sshd-session", __CURSOR="b")
    router.handle(entry, 101)
    router.handle(entry, 102)
    assert len(calls) == 1
    for i in range(10):
        router.handle({"_TRANSPORT": "kernel", "MESSAGE": f"oom-kill: process {i}"}, 110 + i)
    assert len(calls) == 2


def test_services_shutdown_and_recovery():
    calls = []
    monitor = ServicesMonitor(Config(), {}, lambda *args: calls.append(args))
    monitor.sample("ssh.service", "inactive", shutdown=True)
    assert not calls
    monitor.sample("ssh.service", "failed")
    monitor.sample("ssh.service", "failed")
    monitor.sample("ssh.service", "active")
    assert len(calls) == 2
