"""Central bounded notification worker; HTTP never blocks the monitor loop."""

import hashlib
import json
import logging
import threading
import time
from collections import OrderedDict, deque
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .config import Config

LOG = logging.getLogger(__name__)
PRIORITIES = {"min": 1, "low": 2, "default": 3, "high": 4, "urgent": 5}


class NoRedirect(HTTPRedirectHandler):
    """Never forward the bearer token or topic to another endpoint."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass(frozen=True)
class Notification:
    title: str
    message: str
    priority: str = "default"
    tags: tuple[str, ...] = ()
    created: float = 0.0


class Notifier:
    def __init__(self, config: Config, opener=None, clock=time.monotonic):
        self.config = config
        self.opener = opener or build_opener(NoRedirect())
        self.clock = clock
        self.pending: deque[Notification] = deque()
        self.recent: OrderedDict[str, float] = OrderedDict()
        self.condition = threading.Condition()
        self.stop_event = threading.Event()
        self.thread = None
        self.dropped = 0
        self.next_send = 0.0

    def request(self, note: Notification) -> Request:
        body = json.dumps({
            "topic": self.config.ntfy_topic,
            "title": note.title[:200], "message": note.message[:3000],
            "priority": PRIORITIES[note.priority], "tags": list(note.tags),
        }).encode()
        headers = {"Content-Type": "application/json"}
        if self.config.ntfy_token:
            headers["Authorization"] = "Bearer " + self.config.ntfy_token
        return Request(self.config.ntfy_url.rstrip("/") + "/", body, headers, method="POST")

    def notify(self, title: str, message: str, priority: str = "default",
               tags: list[str] | None = None) -> bool:
        if priority not in PRIORITIES:
            raise ValueError("Unknown notification priority")
        title, message = title[:200], message[:3000]
        key = hashlib.sha256((title + "\0" + message).encode()).hexdigest()
        now = self.clock()
        with self.condition:
            if now - self.recent.get(key, -float("inf")) < self.config.dedup_interval:
                return False
            self.recent[key] = now
            self.recent.move_to_end(key)
            while len(self.recent) > 512:
                self.recent.popitem(last=False)
            if len(self.pending) >= self.config.queue_size:
                # Preserve urgent events in preference to ordinary backlog.
                victim = next((n for n in self.pending if PRIORITIES[n.priority] < 4), None)
                if victim:
                    self.pending.remove(victim)
                elif PRIORITIES[priority] < 4:
                    self.dropped += 1
                    return False
                else:
                    self.pending.popleft()
                self.dropped += 1
            self.pending.append(Notification(title, message, priority, tuple(tags or ()), now))
            self.condition.notify()
        return True

    def deliver(self, note: Notification) -> bool:
        for attempt in range(self.config.retries):
            try:
                with self.opener.open(self.request(note), timeout=self.config.http_timeout):
                    pass
                return True
            except HTTPError as exc:
                retry = exc.code == 429 or exc.code >= 500
                LOG.warning("ntfy delivery failed (HTTP %d)", exc.code)
                exc.close()
                if not retry:
                    return False
            except (OSError, URLError, ValueError):
                # Exceptions can contain URLs/credentials: deliberately omit their text.
                LOG.warning("ntfy delivery failed (transport error)")
            if attempt + 1 < self.config.retries and self.stop_event.wait(
                min(30.0, self.config.retry_backoff * 2 ** attempt)
            ):
                return False
        return False

    def start(self) -> None:
        self.thread = threading.Thread(target=self._run, name="ntfy", daemon=True)
        self.thread.start()

    def _run(self) -> None:
        while not self.stop_event.is_set():
            with self.condition:
                self.condition.wait_for(lambda: self.pending or self.stop_event.is_set(), timeout=1)
                if self.stop_event.is_set():
                    break
                if not self.pending:
                    continue
                note = self.pending.popleft()
            if self.stop_event.wait(max(0, self.next_send - self.clock())):
                break
            if self.clock() - note.created > self.config.notification_ttl:
                self.dropped += 1
                continue
            if self.deliver(note):
                if self.dropped:
                    LOG.warning("Notifications dropped/expired: %d", self.dropped)
                    self.dropped = 0
            else:
                self.dropped += 1
            self.next_send = self.clock() + self.config.notification_interval

    def close(self) -> None:
        self.stop_event.set()
        with self.condition:
            self.condition.notify_all()
        if self.thread:
            self.thread.join(timeout=self.config.http_timeout + 1)
