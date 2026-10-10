"""Run with /usr/bin/python3 to access optional distro-provided python3-apt.

Read existing package metadata only. Never refresh caches or install packages.
"""

import json
import sys
from pathlib import Path


def main() -> int:
    try:
        import apt
        import apt_pkg

        lists = Path("/var/lib/apt/lists")
        if not any(lists.glob("*InRelease")) and not any(lists.glob("*Release")):
            raise RuntimeError("No release metadata")
        cache = apt.Cache()
        security = other = 0
        for package in cache:
            if not package.is_upgradable or not package.installed or not package.candidate:
                continue
            # Security fixes may be included in a newer candidate from -updates.
            # Inspect every available version newer than installed up to candidate.
            secure = any(
                apt_pkg.version_compare(version.version, package.installed.version) > 0
                and apt_pkg.version_compare(version.version, package.candidate.version) <= 0
                and any(
                    origin.origin in {"Ubuntu", "Debian"}
                    and (origin.archive.endswith("-security") or origin.label == "Debian-Security")
                    for origin in version.origins
                )
                for version in package.versions
            )
            if secure:
                security += 1
            else:
                other += 1
        print(json.dumps({"security": security, "other": other}))
        return 0
    except Exception:
        # Keep package sources and potentially private repository URLs out of logs.
        print("APT metadata or python3-apt unavailable", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
