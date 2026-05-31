"""Self-update mechanism for HomeHost via PyPI."""

from __future__ import annotations

import subprocess
import sys
import time
import urllib.error
import urllib.request
from typing import NamedTuple

from homehost import __version__


class UpdateInfo(NamedTuple):
    current_version: str
    latest_version: str
    update_available: bool
    changelog_url: str
    download_url: str


_PYPI_URL = "https://pypi.org/pypi/homehost/json"
_CHANGELOG_BASE = "https://github.com/homehost-dev/homehost/blob/main/CHANGELOG.md"
_PYPI_FILES_BASE = "https://files.pythonhosted.org/packages"


def _parse_version(version: str) -> tuple[int, ...]:
    """Parse a PEP 440 version string into a comparable tuple of ints."""
    try:
        return tuple(int(x) for x in version.split(".")[:3])
    except ValueError:
        return (0,)


def check_for_updates(timeout: int = 8) -> UpdateInfo:
    """Check PyPI for the latest *homehost* package version.

    On any network or parse failure returns an ``UpdateInfo`` with
    ``update_available=False`` so callers can continue without crashing.
    """
    current = __version__

    try:
        req = urllib.request.Request(
            _PYPI_URL,
            headers={"User-Agent": f"homehost/{current}"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            import json

            data: dict = json.loads(resp.read())

        latest: str = data["info"]["version"]
        update_available = _parse_version(latest) > _parse_version(current)

        # Build a direct wheel/sdist download URL when available
        releases: dict = data.get("releases", {})
        download_url = ""
        if latest in releases:
            files: list[dict] = releases[latest]
            # Prefer wheel; fall back to sdist
            for f in files:
                if f.get("packagetype") == "bdist_wheel":
                    download_url = f.get("url", "")
                    break
            if not download_url and files:
                download_url = files[0].get("url", "")

        changelog_url = f"{_CHANGELOG_BASE}#v{latest.replace('.', '')}"

        return UpdateInfo(
            current_version=current,
            latest_version=latest,
            update_available=update_available,
            changelog_url=changelog_url,
            download_url=download_url,
        )

    except Exception:
        return UpdateInfo(
            current_version=current,
            latest_version=current,
            update_available=False,
            changelog_url=_CHANGELOG_BASE,
            download_url="",
        )


def perform_update() -> tuple[bool, str]:
    """Upgrade the *homehost* package via pip.

    Returns ``(success, output)`` where *output* is combined stdout + stderr.
    """
    cmd = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--upgrade",
        "homehost",
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
        )
        output = (result.stdout + result.stderr).strip()
        return result.returncode == 0, output
    except subprocess.TimeoutExpired:
        return False, "pip upgrade timed out after 5 minutes"
    except Exception as exc:
        return False, str(exc)


def should_check_for_updates(
    last_check: float,
    interval_hours: int = 24,
) -> bool:
    """Return True if more than *interval_hours* have passed since *last_check*.

    *last_check* is a Unix timestamp (e.g. from ``time.time()``).  Pass
    ``0.0`` to force a check on first run.
    """
    if last_check <= 0:
        return True
    elapsed_hours = (time.time() - last_check) / 3600
    return elapsed_hours >= interval_hours
