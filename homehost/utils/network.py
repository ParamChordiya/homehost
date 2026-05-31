"""Network utility functions for HomeHost."""

from __future__ import annotations

import socket
import time
import urllib.error
import urllib.request
from typing import Optional


# ---------------------------------------------------------------------------
# Local IP detection
# ---------------------------------------------------------------------------


def get_local_ip() -> str:
    """Return the machine's LAN IP address.

    Uses the UDP connect trick (no data is actually sent) with a fallback to
    ``gethostbyname``.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            # Doesn't actually send anything; just sets the source address.
            s.connect(("1.1.1.1", 80))
            return s.getsockname()[0]
    except OSError:
        pass

    try:
        return socket.gethostbyname(socket.gethostname())
    except socket.gaierror:
        return "127.0.0.1"


def get_all_interfaces() -> list[dict[str, str]]:
    """Return a list of network interfaces with their IP addresses.

    Each entry: ``{"name": str, "ip": str, "family": "IPv4" | "IPv6"}``.
    Uses ``psutil`` when available; falls back to a minimal socket-based probe.
    """
    try:
        import psutil  # type: ignore[import]

        results: list[dict[str, str]] = []
        for iface, addrs in psutil.net_if_addrs().items():
            for addr in addrs:
                if addr.family == socket.AF_INET:
                    results.append({"name": iface, "ip": addr.address, "family": "IPv4"})
                elif addr.family == socket.AF_INET6:
                    # Strip scope_id (e.g. '%en0') from link-local addresses
                    ip = addr.address.split("%")[0]
                    results.append({"name": iface, "ip": ip, "family": "IPv6"})
        return results
    except ImportError:
        # Minimal fallback
        local = get_local_ip()
        return [{"name": "eth0", "ip": local, "family": "IPv4"}]


# ---------------------------------------------------------------------------
# Port utilities
# ---------------------------------------------------------------------------


def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """Return True if a port is currently in use."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
            return False
        except OSError:
            return True


def find_free_port(start: int = 8080, end: int = 8099, host: str = "0.0.0.0") -> int:
    """Find the first unused TCP port in the inclusive range [start, end].

    Raises ``RuntimeError`` if no free port is found.
    """
    for port in range(start, end + 1):
        if not is_port_in_use(port, host=host):
            return port
    raise RuntimeError(
        f"No free port found in range {start}–{end}. "
        "Try freeing a port or expanding the search range."
    )


# ---------------------------------------------------------------------------
# Connectivity checks
# ---------------------------------------------------------------------------


def check_internet(timeout: int = 5) -> bool:
    """Return True if the machine has internet access.

    Connects to Cloudflare's public DNS (1.1.1.1:53) as a lightweight probe.
    """
    try:
        with socket.create_connection(("1.1.1.1", 53), timeout=timeout):
            return True
    except OSError:
        return False


def wait_for_port(
    host: str,
    port: int,
    timeout: int = 30,
    interval: float = 0.5,
) -> bool:
    """Poll until a port accepts TCP connections or the timeout is reached.

    Returns ``True`` if the port became available within *timeout* seconds,
    ``False`` otherwise.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=interval):
                return True
        except OSError:
            time.sleep(interval)
    return False


# ---------------------------------------------------------------------------
# Public IP
# ---------------------------------------------------------------------------


def get_public_ip(timeout: int = 5) -> str:
    """Fetch the machine's public IP address from api.ipify.org.

    Returns an empty string on failure.
    """
    try:
        req = urllib.request.Request(
            "https://api.ipify.org",
            headers={"User-Agent": "homehost/0.1"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode().strip()
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def format_bytes(num_bytes: int) -> str:
    """Return a human-readable byte count string.

    Examples:
        512         → '512 B'
        1536        → '1.5 KB'
        1_572_864   → '1.5 MB'
    """
    if num_bytes < 1024:
        return f"{num_bytes} B"
    for unit in ("KB", "MB", "GB", "TB", "PB"):
        num_bytes /= 1024.0
        if num_bytes < 1024 or unit == "PB":
            return f"{num_bytes:.1f} {unit}"
    return f"{num_bytes:.1f} PB"  # unreachable in practice


# ---------------------------------------------------------------------------
# External port accessibility
# ---------------------------------------------------------------------------


def check_port_externally_accessible(port: int) -> bool:
    """Check whether a local TCP port is reachable from the public internet.

    Uses the portchecker.co open API.  Returns ``False`` on any network or
    parse failure to avoid false positives blocking normal operation.
    """
    try:
        url = f"https://portchecker.co/api/v1/query"
        body = f'{{"host": "auto", "ports": [{port}]}}'.encode()
        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "homehost/0.1",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            import json

            data = json.loads(resp.read())
            # Response: {"check": [{"port": 8080, "status": true}]}
            checks: list[dict[str, object]] = data.get("check", [])
            for entry in checks:
                if entry.get("port") == port:
                    return bool(entry.get("status"))
    except Exception:
        pass
    return False
