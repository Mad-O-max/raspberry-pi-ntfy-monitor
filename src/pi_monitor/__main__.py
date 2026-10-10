import argparse
import json
import logging
import shutil

from .app import run
from .config import Config
from .logging_setup import configure
from .notifier import Notification, Notifier
from .state import StateStore


def main() -> int:
    parser = argparse.ArgumentParser(description="Raspberry Pi system monitor with ntfy alerts")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check-config", action="store_true")
    group.add_argument("--show-effective-config", action="store_true")
    group.add_argument("--test-notification", action="store_true")
    group.add_argument("--status", action="store_true")
    group.add_argument("--diagnostics", action="store_true")
    group.add_argument("--foreground", action="store_true")
    args = parser.parse_args()
    try:
        config = Config.from_env()
    except ValueError as exc:
        parser.error(str(exc))
    configure(config.log_level)
    if args.check_config:
        print("Configuration valid")
    elif args.show_effective_config:
        print(json.dumps(config.redacted(), indent=2))
    elif args.status:
        # Deliberately omit source IPs, usernames, public IP, cursor and topic.
        state = StateStore(config.state_dir).load()
        print(
            json.dumps(
                {
                    key: state.get(key)
                    for key in ("boot_id", "clean_exit", "last_uptime", "heartbeat", "network")
                },
                indent=2,
            )
        )
    elif args.diagnostics:
        print(
            json.dumps(
                {
                    name: bool(shutil.which(name))
                    for name in ("journalctl", "systemctl", "vcgencmd")
                },
                indent=2,
            )
        )
    elif args.test_notification:
        notifier = Notifier(config)
        if not notifier.deliver(
            Notification("Pi monitor test", "Notification transport is working")
        ):
            return 1
        print("Test notification sent")
    else:
        try:
            run(config)
        except Exception as exc:
            # Some underlying exception messages include remote URLs or log content.
            logging.getLogger(__name__).critical("Monitor terminated (%s)", type(exc).__name__)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
