"""Cross-platform OS abstractions for HomeHost."""

from __future__ import annotations

import os
import platform
import subprocess
import sys
import tempfile
from pathlib import Path

# ---------------------------------------------------------------------------
# OS / Architecture detection
# ---------------------------------------------------------------------------


def get_os() -> str:
    """Return 'macOS' | 'Windows' | 'Linux' | 'unknown'."""
    system = platform.system()
    if system == "Darwin":
        return "macOS"
    if system == "Windows":
        return "Windows"
    if system == "Linux":
        return "Linux"
    return "unknown"


def get_arch() -> str:
    """Return 'arm64' | 'x86_64' | 'unknown'."""
    machine = platform.machine().lower()
    if machine in ("arm64", "aarch64"):
        return "arm64"
    if machine in ("x86_64", "amd64", "x64"):
        return "x86_64"
    return "unknown"


def is_macos() -> bool:
    return platform.system() == "Darwin"


def is_windows() -> bool:
    return platform.system() == "Windows"


def is_linux() -> bool:
    return platform.system() == "Linux"


# ---------------------------------------------------------------------------
# OS version
# ---------------------------------------------------------------------------

_MACOS_VERSION_NAMES: dict[str, str] = {
    "15": "Sequoia",
    "14": "Sonoma",
    "13": "Ventura",
    "12": "Monterey",
    "11": "Big Sur",
    "10.15": "Catalina",
    "10.14": "Mojave",
    "10.13": "High Sierra",
    "10.12": "Sierra",
}


def _macos_version_name(version: str) -> str:
    major = version.split(".")[0]
    minor_key = ".".join(version.split(".")[:2])
    return _MACOS_VERSION_NAMES.get(major) or _MACOS_VERSION_NAMES.get(minor_key) or ""


def get_os_version() -> str:
    """Return a human-readable OS version string.

    Examples:
        macOS  → '15.1 Sequoia'
        Windows → '11 (22H2)'
        Linux   → 'Ubuntu 22.04.3 LTS'
    """
    if is_macos():
        ver = platform.mac_ver()[0]  # e.g. '15.1.0'
        short = ".".join(ver.split(".")[:2])  # '15.1'
        name = _macos_version_name(ver)
        return f"{short} {name}".strip()

    if is_windows():
        try:
            platform.version()  # e.g. '10.0.22621'
            release = platform.release()  # e.g. '10' or '11'
            # Attempt to get the friendly release name from winver
            import winreg  # type: ignore[import]

            with winreg.OpenKey(  # type: ignore[attr-defined]
                winreg.HKEY_LOCAL_MACHINE,  # type: ignore[attr-defined]
                r"SOFTWARE\Microsoft\Windows NT\CurrentVersion",
            ) as key:
                display_ver = winreg.QueryValueEx(key, "DisplayVersion")[0]  # type: ignore[attr-defined]
            return f"{release} ({display_ver})"
        except Exception:
            return platform.version()

    if is_linux():
        try:
            with open("/etc/os-release") as f:
                data: dict[str, str] = {}
                for line in f:
                    line = line.strip()
                    if "=" in line:
                        k, _, v = line.partition("=")
                        data[k] = v.strip('"')
            return data.get("PRETTY_NAME") or data.get("NAME", platform.release())
        except OSError:
            return platform.release()

    return platform.version()


# ---------------------------------------------------------------------------
# Browser / File manager
# ---------------------------------------------------------------------------


def open_in_browser(url: str) -> None:
    """Open a URL in the system's default browser."""
    import webbrowser

    webbrowser.open(url)


def open_file_manager(path: Path) -> None:
    """Open a directory in Finder (macOS), Explorer (Windows), or xdg-open (Linux)."""
    resolved = path.resolve()
    if is_macos():
        subprocess.Popen(["open", str(resolved)])
    elif is_windows():
        subprocess.Popen(["explorer", str(resolved)])
    elif is_linux():
        subprocess.Popen(["xdg-open", str(resolved)])


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------


def get_home_dir() -> Path:
    """Return the current user's home directory."""
    return Path.home()


def get_temp_dir() -> Path:
    """Return the system temporary directory."""
    return Path(tempfile.gettempdir())


# ---------------------------------------------------------------------------
# Privileges
# ---------------------------------------------------------------------------


def is_admin() -> bool:
    """Return True if running with admin/root privileges."""
    if is_windows():
        try:
            import ctypes

            return bool(ctypes.windll.shell32.IsUserAnAdmin())  # type: ignore[attr-defined]
        except Exception:
            return False
    # POSIX: root uid == 0
    return os.geteuid() == 0  # type: ignore[attr-defined]


def run_elevated(command: list[str]) -> tuple[int, str]:
    """Run a command with elevated privileges.

    macOS / Linux: prepend ``sudo``.
    Windows: use ``runas`` via PowerShell.

    Returns (returncode, combined stdout+stderr output).
    """
    if is_windows():
        # PowerShell: Start-Process with -Verb RunAs is non-blocking and
        # cannot easily capture output.  Fall back to a simple runas wrapper
        # that writes output to a temp file.
        tmp = Path(tempfile.mktemp(suffix=".txt"))
        ps_cmd = (
            f"Start-Process -Wait -FilePath '{command[0]}' "
            f"-ArgumentList '{' '.join(command[1:])}' "
            f"-Verb RunAs -RedirectStandardOutput '{tmp}'"
        )
        ret = subprocess.run(
            ["powershell", "-Command", ps_cmd],
            capture_output=True,
            text=True,
        )
        output = tmp.read_text() if tmp.exists() else ret.stderr
        tmp.unlink(missing_ok=True)
        return ret.returncode, output

    # macOS / Linux – prepend sudo
    elevated = ["sudo", *command]
    try:
        result = subprocess.run(
            elevated,
            capture_output=True,
            text=True,
            timeout=120,
        )
        output = (result.stdout + result.stderr).strip()
        return result.returncode, output
    except subprocess.TimeoutExpired:
        return 1, "Command timed out"
    except FileNotFoundError:
        return 1, "sudo not found"


# ---------------------------------------------------------------------------
# System info summary
# ---------------------------------------------------------------------------


def get_system_info_string() -> str:
    """Return a human-readable system info summary for display."""
    lines: list[str] = [
        f"OS:           {get_os()} {get_os_version()}",
        f"Architecture: {get_arch()}",
        f"Python:       {sys.version.split()[0]}",
        f"Home:         {get_home_dir()}",
        f"Admin/root:   {'yes' if is_admin() else 'no'}",
    ]

    # CPU / memory via psutil if available
    try:
        import psutil  # type: ignore[import]

        mem = psutil.virtual_memory()
        total_gb = mem.total / (1024**3)
        avail_gb = mem.available / (1024**3)
        lines.append(f"Memory:       {avail_gb:.1f} GB free / {total_gb:.1f} GB total")
        cpu_count = psutil.cpu_count(logical=True)
        lines.append(f"CPU cores:    {cpu_count}")
    except ImportError:
        pass

    return "\n".join(lines)
