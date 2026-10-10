# Working on pi-monitor

Python 3.11+ daemon for Raspberry Pi, journald and ntfy. Runtime uses the standard
library; optional distro python3-apt runs in a separate read-only helper.

- `src/pi_monitor/app.py` owns state. Polling `read()` runs in a bounded worker;
  `apply()` and event parsers run on the daemon thread. Never mutate state in read().
- Keep parsers independent, use typed events, and use Threshold for hysteresis.
- Route all notifications through Notifier. Bound queues, counters, retries and IO.
- Preserve atomic, versioned state and boot versus process restart semantics.
- Never commit secrets, actual topics/tokens, private keys or personal log captures.
  Avoid logging exceptions containing URLs, bearer tokens or authentication data.
- HTTPS verification stays enabled. No shell=True or security configuration changes.
- Use type hints, Ruff, synthetic RFC 5737/3849 addresses and offline tests.
- Commands: `.venv/bin/pytest`, `.venv/bin/ruff check .`,
  `.venv/bin/ruff format --check .`, `.venv/bin/python -m build`.
- Behaviour changes require tests and documentation. Installation, daemon activation
  and GitHub publication are separate from local development; do not publish silently.
