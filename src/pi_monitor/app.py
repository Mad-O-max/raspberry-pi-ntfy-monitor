"""Single owner of runtime state; bounded background I/O, one journal reader."""

import logging
import queue
import signal
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from .config import Config
from .journal import JournalFollower, JournalRouter
from .monitors.boot import boot_identity, startup
from .monitors.disk import DiskMonitor
from .monitors.filesystem import FilesystemMonitor
from .monitors.load import LoadMonitor
from .monitors.memory import MemoryMonitor
from .monitors.network import NetworkMonitor
from .monitors.public_ip import PublicIpMonitor
from .monitors.services import ServicesMonitor
from .monitors.ssh import SshAggregator
from .monitors.temperature import TemperatureMonitor
from .monitors.throttling import ThrottlingMonitor
from .monitors.updates import UpdatesMonitor
from .notifier import Notifier
from .state import StateStore

LOG = logging.getLogger(__name__)


class Monitor(Protocol):
    def read(self) -> Any: ...
    def apply(self, result: Any, now: float) -> None: ...


@dataclass
class PollJob:
    """One outstanding read per monitor: no executor queue or state races.

    Daemon threads allow bounded shutdown even if libc DNS resolution hangs;
    worker threads never change persistent state or send notifications.
    """

    name: str
    monitor: Monitor
    interval: float
    next_due: float = 0.0
    failed: bool = False
    thread: threading.Thread | None = None
    result: queue.Queue = field(default_factory=lambda: queue.Queue(maxsize=1))

    def step(self, monotonic: float, wall_time: float) -> bool:
        changed = False
        if self.thread is not None:
            try:
                ok, value = self.result.get_nowait()
            except queue.Empty:
                return False
            self.thread = None
            self.next_due = monotonic + self.interval
            if ok:
                try:
                    self.monitor.apply(value, wall_time)
                    changed = True
                except Exception as exc:
                    ok, value = False, type(exc).__name__
            if not ok and not self.failed:
                LOG.warning("%s check unavailable (%s); retrying", self.name, value)
            elif ok and self.failed:
                LOG.info("%s checks recovered", self.name)
            self.failed = not ok
        if self.thread is None and monotonic >= self.next_due:
            self.thread = threading.Thread(target=self._read, name=self.name, daemon=True)
            self.thread.start()
        return changed

    def _read(self) -> None:
        try:
            self.result.put((True, self.monitor.read()))
        except Exception as exc:
            self.result.put((False, type(exc).__name__))


class App:
    def __init__(self, config: Config):
        self.config = config
        self.store = StateStore(config.state_dir)
        self.notifier = Notifier(config)
        self.stop_event = threading.Event()
        self.journal = None
        self.jobs: list[PollJob] = []

    def stop(self, signum=None, frame=None) -> None:
        self.stop_event.set()

    def run(self) -> None:
        self.store.lock()
        state = self.store.load()
        clean = False
        try:
            boot_id, uptime = boot_identity()
            startup(state, boot_id, uptime, time.time(), self.notifier.notify)
            self.store.save(state)
            self.notifier.start()
            c = self.config
            common = (c, state, self.notifier.notify)
            self.jobs = [
                PollJob("temperature", TemperatureMonitor(*common), c.poll_interval),
                PollJob("disk", DiskMonitor(*common), c.poll_interval),
                PollJob("memory", MemoryMonitor(*common), c.poll_interval),
                PollJob("load", LoadMonitor(*common), c.poll_interval),
                PollJob("network", NetworkMonitor(*common), c.network_interval),
                PollJob(
                    "services",
                    ServicesMonitor(*common),
                    c.service_interval,
                    next_due=time.monotonic() + c.service_interval,
                ),
                PollJob("throttling", ThrottlingMonitor(*common), c.poll_interval),
                PollJob("filesystem", FilesystemMonitor(*common), c.poll_interval),
            ]
            if c.public_ip_enabled:
                self.jobs.append(
                    PollJob("public_ip", PublicIpMonitor(*common), c.public_ip_interval)
                )
            if c.updates_enabled:
                self.jobs.append(PollJob("updates", UpdatesMonitor(*common), c.updates_interval))
            aggregator = SshAggregator(*common, time.time())
            self.journal = JournalFollower(state)
            router = JournalRouter(state, aggregator, self.notifier.notify)
            next_save = 0.0
            save_failed = False
            LOG.info("Monitor started (%d polling monitors)", len(self.jobs))
            while not self.stop_event.is_set():
                now, monotonic = time.time(), time.monotonic()
                for entry in self.journal.poll(monotonic):
                    router.handle(entry, now)
                aggregator.tick(now)
                for job in self.jobs:
                    job.step(monotonic, now)
                if monotonic >= next_save:
                    state["last_uptime"] = boot_identity()[1]
                    state["heartbeat"] = now
                    try:
                        self.store.save(state)
                        if save_failed:
                            LOG.info("Persistent state writes recovered")
                        save_failed = False
                    except OSError:
                        # A read-only root must still be reported, not crash-loop.
                        if not save_failed:
                            LOG.error("Cannot persist state; monitoring continues in memory")
                            self.notifier.notify(
                                "Pi monitor state unavailable",
                                "Cannot write persistent state",
                                "high",
                            )
                        save_failed = True
                    next_save = monotonic + 10
                self.stop_event.wait(0.2)
            clean = True
        finally:
            if self.journal:
                self.journal.close()
            self.notifier.close()
            state["clean_exit"] = clean
            try:
                self.store.save(state)
            finally:
                self.store.close()
            LOG.info("Monitor stopped (clean=%s)", clean)


def run(config: Config) -> None:
    app = App(config)
    signal.signal(signal.SIGTERM, app.stop)
    signal.signal(signal.SIGINT, app.stop)
    app.run()
