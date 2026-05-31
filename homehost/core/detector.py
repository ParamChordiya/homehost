"""OS/environment detection and pre-flight checks for HomeHost."""

from __future__ import annotations

import platform
import shutil
import socket
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import structlog

log = structlog.get_logger(__name__)

# ── Data models ────────────────────────────────────────────────────────────────


@dataclass
class SystemInfo:
    os_name: str                    # "macOS" | "Windows" | "Linux"
    os_version: str                 # e.g. "15.1"
    arch: str                       # "arm64" | "x86_64"
    python_version: str
    node_version: str               # "" if not found
    git_version: str                # "" if not found
    caddy_path: str                 # "" if not found
    cloudflared_path: str           # "" if not found
    homebrew_available: bool        # macOS only
    winget_available: bool          # Windows only
    choco_available: bool           # Windows only
    available_ports: list[int]      # ports free in 8080-8099
    local_ip: str
    has_internet: bool
    disk_free_gb: float


@dataclass
class CheckResult:
    name: str
    status: str          # "ok" | "warning" | "error" | "missing"
    message: str
    fix_hint: str = ""   # actionable hint shown to user on non-ok status


# ── Internal helpers ───────────────────────────────────────────────────────────


def _run(args: list[str], timeout: int = 10) -> tuple[int, str, str]:
    """Run a subprocess; return (returncode, stdout, stderr). Never raises."""
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except FileNotFoundError:
        return 127, "", f"{args[0]!r} not found"
    except subprocess.TimeoutExpired:
        return -1, "", f"timed out after {timeout}s"
    except Exception as exc:  # noqa: BLE001
        return -1, "", str(exc)


def find_executable(name: str) -> str:
    """Return the full path of *name* if found in PATH, else ""."""
    path = shutil.which(name)
    return path if path is not None else ""


def is_port_in_use(port: int) -> bool:
    """Return True if *port* is already bound on 0.0.0.0 or 127.0.0.1."""
    for host in ("127.0.0.1", "0.0.0.0"):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind((host, port))
            # bind succeeded → port is free on this interface
        except OSError:
            return True
    return False


def find_available_port(start: int = 8080, end: int = 8099) -> int | None:
    """Return the first free port in [start, end], or None if all taken."""
    for port in range(start, end + 1):
        if not is_port_in_use(port):
            return port
    return None


def get_local_ip() -> str:
    """Return the machine's primary LAN IP address, or "127.0.0.1" on failure."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            # connect to an external address without sending any data
            s.connect(("1.1.1.1", 53))
            return s.getsockname()[0]
    except Exception:  # noqa: BLE001
        return "127.0.0.1"


def _os_name() -> str:
    system = platform.system()
    if system == "Darwin":
        return "macOS"
    if system == "Windows":
        return "Windows"
    return system  # "Linux" etc.


def _os_version() -> str:
    os_name = _os_name()
    if os_name == "macOS":
        code, out, _ = _run(["sw_vers", "-productVersion"])
        if code == 0 and out:
            return out
        return platform.mac_ver()[0]
    if os_name == "Windows":
        return platform.version()
    return platform.release()


def _arch() -> str:
    machine = platform.machine().lower()
    if machine in ("arm64", "aarch64"):
        return "arm64"
    if machine in ("amd64", "x86_64"):
        return "x86_64"
    return machine


def _node_version() -> str:
    code, out, _ = _run(["node", "--version"])
    if code == 0 and out:
        return out.lstrip("v")
    return ""


def _git_version() -> str:
    code, out, _ = _run(["git", "--version"])
    if code == 0 and out:
        # "git version 2.45.0" → "2.45.0"
        parts = out.split()
        return parts[-1] if parts else out
    return ""


def _caddy_path() -> str:
    return find_executable("caddy")


def _cloudflared_path() -> str:
    return find_executable("cloudflared")


def _homebrew_available() -> bool:
    return _os_name() == "macOS" and bool(find_executable("brew"))


def _winget_available() -> bool:
    return _os_name() == "Windows" and bool(find_executable("winget"))


def _choco_available() -> bool:
    return _os_name() == "Windows" and bool(find_executable("choco"))


def _disk_free_gb() -> float:
    try:
        usage = shutil.disk_usage(Path.home())
        return usage.free / (1024 ** 3)
    except Exception:  # noqa: BLE001
        return 0.0


# ── Public API ─────────────────────────────────────────────────────────────────


def detect_system() -> SystemInfo:
    """Gather comprehensive system information. Never raises."""
    log.debug("detecting system info")
    available_ports = [
        p for p in range(8080, 8100) if not is_port_in_use(p)
    ]
    return SystemInfo(
        os_name=_os_name(),
        os_version=_os_version(),
        arch=_arch(),
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        node_version=_node_version(),
        git_version=_git_version(),
        caddy_path=_caddy_path(),
        cloudflared_path=_cloudflared_path(),
        homebrew_available=_homebrew_available(),
        winget_available=_winget_available(),
        choco_available=_choco_available(),
        available_ports=available_ports,
        local_ip=get_local_ip(),
        has_internet=check_internet().status == "ok",
        disk_free_gb=_disk_free_gb(),
    )


# ── Individual checks ──────────────────────────────────────────────────────────


def check_python_version() -> CheckResult:
    """Require Python 3.10+."""
    vi = sys.version_info
    ver = f"{vi.major}.{vi.minor}.{vi.micro}"
    if vi >= (3, 10):
        return CheckResult(
            name="python",
            status="ok",
            message=f"Python {ver}",
        )
    return CheckResult(
        name="python",
        status="error",
        message=f"Python {ver} is too old (need 3.10+)",
        fix_hint="Install Python 3.10 or newer from https://python.org",
    )


def check_node() -> CheckResult:
    """Check that Node.js is available."""
    code, out, err = _run(["node", "--version"])
    if code == 0 and out:
        ver = out.lstrip("v")
        return CheckResult(name="node", status="ok", message=f"Node.js {ver}")
    return CheckResult(
        name="node",
        status="missing",
        message="Node.js not found",
        fix_hint=(
            "Install Node.js from https://nodejs.org  "
            "(macOS: `brew install node`  Windows: `winget install OpenJS.NodeJS`)"
        ),
    )


def check_git() -> CheckResult:
    """Check that git is available."""
    code, out, _ = _run(["git", "--version"])
    if code == 0 and out:
        parts = out.split()
        ver = parts[-1] if parts else out
        return CheckResult(name="git", status="ok", message=f"git {ver}")
    return CheckResult(
        name="git",
        status="missing",
        message="git not found",
        fix_hint=(
            "Install git from https://git-scm.com  "
            "(macOS: `brew install git`  Windows: `winget install Git.Git`)"
        ),
    )


def check_caddy() -> CheckResult:
    """Check that Caddy web server is available."""
    path = _caddy_path()
    if not path:
        return CheckResult(
            name="caddy",
            status="missing",
            message="Caddy not found",
            fix_hint=(
                "Install Caddy from https://caddyserver.com  "
                "(macOS: `brew install caddy`  Windows: `winget install CaddyServer.Caddy`)"
            ),
        )
    code, out, _ = _run(["caddy", "version"])
    ver = out.split()[0] if (code == 0 and out) else "unknown"
    return CheckResult(
        name="caddy",
        status="ok",
        message=f"Caddy {ver} at {path}",
    )


def check_cloudflared() -> CheckResult:
    """Check that cloudflared is available."""
    path = _cloudflared_path()
    if not path:
        return CheckResult(
            name="cloudflared",
            status="missing",
            message="cloudflared not found (needed for public tunnels)",
            fix_hint=(
                "Install cloudflared from https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/installation  "
                "(macOS: `brew install cloudflare/cloudflare/cloudflared`)"
            ),
        )
    code, out, _ = _run(["cloudflared", "--version"])
    ver = out.split()[-1] if (code == 0 and out) else "unknown"
    return CheckResult(
        name="cloudflared",
        status="ok",
        message=f"cloudflared {ver} at {path}",
    )


def check_internet() -> CheckResult:
    """Test connectivity by connecting to Cloudflare DNS (1.1.1.1:53)."""
    try:
        with socket.create_connection(("1.1.1.1", 53), timeout=5):
            pass
        return CheckResult(name="internet", status="ok", message="Internet reachable")
    except OSError as exc:
        return CheckResult(
            name="internet",
            status="error",
            message=f"No internet connection: {exc}",
            fix_hint="Check your network connection and firewall settings.",
        )


def check_disk_space(min_gb: float = 1.0) -> CheckResult:
    """Warn if less than *min_gb* GB of disk space is free."""
    try:
        free_gb = _disk_free_gb()
    except Exception as exc:  # noqa: BLE001
        return CheckResult(
            name="disk",
            status="error",
            message=f"Could not determine disk space: {exc}",
            fix_hint="Ensure the home directory is accessible.",
        )

    if free_gb >= min_gb:
        return CheckResult(
            name="disk",
            status="ok",
            message=f"{free_gb:.1f} GB free",
        )
    if free_gb > 0:
        return CheckResult(
            name="disk",
            status="warning",
            message=f"Only {free_gb:.1f} GB free (need {min_gb:.1f} GB)",
            fix_hint="Free up disk space before hosting large projects.",
        )
    return CheckResult(
        name="disk",
        status="error",
        message="Disk appears full",
        fix_hint="Free up disk space immediately.",
    )


def run_all_checks() -> list[CheckResult]:
    """Run every check and return results in display order."""
    checks: list[CheckResult] = [
        check_python_version(),
        check_internet(),
        check_disk_space(),
        check_git(),
        check_node(),
        check_caddy(),
        check_cloudflared(),
    ]
    for result in checks:
        log.debug(
            "check result",
            name=result.name,
            status=result.status,
            message=result.message,
        )
    return checks
