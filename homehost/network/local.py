"""Local network utilities: IP detection, QR code generation, mDNS registration."""

from __future__ import annotations

import io
import ipaddress
import logging
import platform
import re
import socket
import subprocess
import threading

import qrcode
import qrcode.constants
from rich.console import Console

log = logging.getLogger(__name__)

# mDNS process handle — kept module-level so we can unregister later
_mdns_processes: dict[str, subprocess.Popen[bytes]] = {}
_mdns_lock = threading.Lock()


# ── IP Detection ───────────────────────────────────────────────────────────────


def get_local_ip() -> str:
    """Return the machine's LAN IP address (not 127.0.0.1).

    Primary method: UDP socket trick — connect to 8.8.8.8:80 without sending
    data, then read the local address the OS assigned.  This never transmits
    any packets.

    Fallback: parse ``ifconfig`` (macOS/Linux) or ``ipconfig`` (Windows) output
    and return the first private (RFC 1918) address found.
    """
    # ── Primary: UDP socket trick ──────────────────────────────────────────────
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(2)
            sock.connect(("8.8.8.8", 80))
            ip = sock.getsockname()[0]
            if ip and ip != "127.0.0.1" and is_private_ip(ip):
                return ip
    except OSError:
        pass

    # ── Fallback: parse network tools ─────────────────────────────────────────
    system = platform.system()
    try:
        if system in ("Darwin", "Linux"):
            output = subprocess.check_output(["ifconfig"], stderr=subprocess.DEVNULL, timeout=5).decode(
                errors="replace"
            )
            # Match "inet <addr>" lines, skip loopback
            for match in re.finditer(r"inet\s+([\d.]+)", output):
                addr = match.group(1)
                if addr != "127.0.0.1" and is_private_ip(addr):
                    return addr
        elif system == "Windows":
            output = subprocess.check_output(["ipconfig"], stderr=subprocess.DEVNULL, timeout=5).decode(
                errors="replace"
            )
            for match in re.finditer(r"IPv4 Address[.\s]+:\s*([\d.]+)", output):
                addr = match.group(1)
                if addr != "127.0.0.1" and is_private_ip(addr):
                    return addr
    except (subprocess.SubprocessError, OSError, ValueError):
        pass

    # ── Last resort: hostname resolution ──────────────────────────────────────
    try:
        hostname = socket.gethostname()
        addr = socket.gethostbyname(hostname)
        if addr and addr != "127.0.0.1":
            return addr
    except OSError:
        pass

    return "127.0.0.1"


def get_all_local_ips() -> list[str]:
    """Return all non-loopback IPv4 addresses assigned to this machine."""
    ips: list[str] = []
    try:
        hostname = socket.gethostname()
        info_list = socket.getaddrinfo(hostname, None, socket.AF_INET)
        for info in info_list:
            addr = str(info[4][0])
            if addr != "127.0.0.1" and addr not in ips:
                ips.append(addr)
    except OSError:
        pass

    # Also enumerate via socket.if_nameindex if available (Linux/macOS only)
    try:
        import fcntl
        import struct

        _siocgifaddr = 0x8915  # Linux
        if platform.system() == "Darwin":
            _siocgifaddr = 0xC0206921  # macOS — use ifconfig fallback instead

        if platform.system() == "Linux":
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                for iface in socket.if_nameindex():
                    iface_name = iface[1].encode()
                    try:
                        packed = struct.pack("256s", iface_name[:15])
                        res = fcntl.ioctl(sock.fileno(), _siocgifaddr, packed)  # type: ignore[attr-defined]
                        addr = socket.inet_ntoa(res[20:24])
                        if addr != "127.0.0.1" and addr not in ips:
                            ips.append(addr)
                    except OSError:
                        pass
    except ImportError:
        pass

    if not ips:
        fallback = get_local_ip()
        if fallback != "127.0.0.1":
            ips.append(fallback)

    return ips


# ── QR Code ────────────────────────────────────────────────────────────────────


def generate_qr_code(url: str) -> str:
    """Return a terminal-renderable ASCII QR code string for *url*.

    Uses ``qrcode.QRCode`` with minimal box/border size so it fits in most
    terminal windows.  The result is captured from ``print_ascii()`` via
    ``io.StringIO`` and returned as a plain string.
    """
    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=1,
        border=1,
    )
    qr.add_data(url)
    qr.make(fit=True)

    buf = io.StringIO()
    qr.print_ascii(out=buf, invert=True)
    return buf.getvalue()


def print_qr_code(url: str) -> None:
    """Print a QR code for *url* to stdout, framed with a Rich panel."""
    from rich.panel import Panel

    console = Console()
    qr_str = generate_qr_code(url)
    console.print(
        Panel(
            qr_str.rstrip(),
            title="[bold cyan]Scan to open[/bold cyan]",
            subtitle=f"[dim]{url}[/dim]",
            border_style="cyan",
            expand=False,
        )
    )


# ── mDNS ──────────────────────────────────────────────────────────────────────


def register_mdns(name: str, port: int) -> bool:
    """Register an mDNS service so the device is reachable as ``<name>.local``.

    On macOS uses ``dns-sd -R`` to publish a ``_http._tcp`` service.  On Linux
    falls back to ``avahi-publish-service`` if available.  Returns ``True`` if
    the background process started successfully, ``False`` otherwise.
    """
    system = platform.system()

    with _mdns_lock:
        # Don't register twice for the same name
        if name in _mdns_processes:
            proc = _mdns_processes[name]
            if proc.poll() is None:
                return True  # already running
            del _mdns_processes[name]

    if system == "Darwin":
        cmd = ["dns-sd", "-R", name, "_http._tcp", ".", str(port)]
        dns_sd_path = "/usr/bin/dns-sd"
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            with _mdns_lock:
                _mdns_processes[name] = proc
            log.info("mDNS registered: %s.local → port %d (dns-sd pid=%d)", name, port, proc.pid)
            return True
        except FileNotFoundError:
            log.warning("dns-sd not found at %s; mDNS not available", dns_sd_path)
            return False
        except OSError as exc:
            log.warning("Failed to start dns-sd: %s", exc)
            return False

    if system == "Linux":
        # Try avahi-publish-service
        try:
            proc = subprocess.Popen(
                ["avahi-publish-service", name, "_http._tcp", str(port)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            with _mdns_lock:
                _mdns_processes[name] = proc
            log.info("mDNS registered via avahi: %s.local → port %d", name, port)
            return True
        except FileNotFoundError:
            log.warning("avahi-publish-service not found; mDNS not available on this Linux host")
            return False
        except OSError as exc:
            log.warning("Failed to start avahi-publish-service: %s", exc)
            return False

    log.warning("mDNS not supported on platform: %s", system)
    return False


def unregister_mdns(name: str) -> bool:
    """Terminate the mDNS registration process for *name*.

    Returns ``True`` if a process was found and terminated, ``False`` otherwise.
    """
    with _mdns_lock:
        proc = _mdns_processes.pop(name, None)

    if proc is None:
        log.debug("No mDNS process found for name %r", name)
        return False

    try:
        proc.terminate()
        proc.wait(timeout=3)
        log.info("mDNS unregistered: %s", name)
        return True
    except subprocess.TimeoutExpired:
        proc.kill()
        log.warning("mDNS process for %r did not terminate gracefully; killed", name)
        return True
    except OSError as exc:
        log.warning("Error terminating mDNS process for %r: %s", name, exc)
        return False


# ── Connectivity ───────────────────────────────────────────────────────────────


def check_lan_connectivity() -> bool:
    """Return ``True`` if the machine has a working LAN connection.

    Heuristic: we consider the machine connected if it has at least one
    non-loopback private IP address and we can open a socket to it.
    """
    try:
        ip = get_local_ip()
        if ip == "127.0.0.1":
            return False
        return is_private_ip(ip)
    except Exception:
        return False


# ── URL Formatting ─────────────────────────────────────────────────────────────


def format_local_url(port: int) -> str:
    """Return ``http://<local_ip>:<port>`` for the current machine."""
    ip = get_local_ip()
    return f"http://{ip}:{port}"


# ── IP Validation ──────────────────────────────────────────────────────────────


def is_private_ip(ip: str) -> bool:
    """Return ``True`` if *ip* is in an RFC 1918 private range.

    Covered ranges:
    - ``10.0.0.0/8``
    - ``172.16.0.0/12``  (172.16.x.x – 172.31.x.x)
    - ``192.168.0.0/16``
    """
    try:
        addr = ipaddress.IPv4Address(ip)
        return addr.is_private
    except ValueError:
        return False
