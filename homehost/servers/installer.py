"""Auto-install Caddy and cloudflared on macOS and Windows.

Install order (each binary):
  1. Check if already present on PATH or in ~/.homehost/bin/
  2. macOS  → brew, then direct GitHub release download
  3. Windows → winget, then choco, then direct GitHub release download
"""

from __future__ import annotations

import os
import platform
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from urllib.error import URLError


# ── Constants ──────────────────────────────────────────────────────────────────

_HOMEHOST_BIN = Path.home() / ".homehost" / "bin"

_CADDY_GITHUB_API = "https://api.github.com/repos/caddyserver/caddy/releases/latest"
_CLOUDFLARED_GITHUB_API = (
    "https://api.github.com/repos/cloudflare/cloudflared/releases/latest"
)


# ── Result dataclass ───────────────────────────────────────────────────────────


@dataclass
class InstallResult:
    success: bool
    path: str = ""         # full path to installed binary
    version: str = ""      # version string (e.g. "v2.8.4")
    method: str = ""       # "brew" | "winget" | "choco" | "direct" | "existing"
    error: str = ""        # "" if success


# ── Platform helpers ───────────────────────────────────────────────────────────


def _is_macos() -> bool:
    return sys.platform == "darwin"


def _is_windows() -> bool:
    return sys.platform == "win32"


def _machine_arch() -> str:
    """Return normalised arch string: 'amd64' or 'arm64'."""
    machine = platform.machine().lower()
    if machine in ("arm64", "aarch64"):
        return "arm64"
    return "amd64"


def _run(
    cmd: list[str],
    timeout: int = 120,
    env: dict[str, str] | None = None,
) -> tuple[int, str, str]:
    """Run a command, return (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except FileNotFoundError:
        return 1, "", f"Command not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return 1, "", f"Command timed out after {timeout}s"
    except OSError as exc:
        return 1, "", str(exc)


def _command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def _ensure_bin_dir() -> Path:
    _HOMEHOST_BIN.mkdir(parents=True, exist_ok=True)
    return _HOMEHOST_BIN


# ── Binary verification ────────────────────────────────────────────────────────


def verify_caddy(path: str) -> tuple[bool, str]:
    """Run `caddy version`, return (ok, version_string)."""
    rc, stdout, stderr = _run([path, "version"])
    if rc == 0 and stdout:
        return True, stdout.split("\n")[0].strip()
    return False, stderr or "caddy version returned no output"


def verify_cloudflared(path: str) -> tuple[bool, str]:
    """Run `cloudflared --version`, return (ok, version_string)."""
    rc, stdout, stderr = _run([path, "--version"])
    if rc == 0:
        version_line = stdout.split("\n")[0].strip()
        return True, version_line
    return False, stderr or "cloudflared --version returned no output"


# ── Path discovery ─────────────────────────────────────────────────────────────


def get_caddy_path() -> str:
    """Return path to caddy binary, or '' if not found."""
    # Check ~/.homehost/bin first
    local = _HOMEHOST_BIN / ("caddy.exe" if _is_windows() else "caddy")
    if local.exists():
        return str(local)
    found = shutil.which("caddy")
    return found or ""


def get_cloudflared_path() -> str:
    """Return path to cloudflared binary, or '' if not found."""
    local = _HOMEHOST_BIN / ("cloudflared.exe" if _is_windows() else "cloudflared")
    if local.exists():
        return str(local)
    found = shutil.which("cloudflared")
    return found or ""


# ── GitHub release helpers ─────────────────────────────────────────────────────


def _fetch_latest_release_tag(api_url: str) -> str:
    """Return the latest release tag name from the GitHub API."""
    req = urllib.request.Request(
        api_url,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "homehost/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            import json
            data = json.loads(resp.read().decode())
            return data.get("tag_name", "")
    except (URLError, OSError, ValueError):
        return ""


def _download_with_progress(
    url: str,
    dest: Path,
    callback: Callable[[str], None] | None,
) -> None:
    """Download *url* to *dest*, reporting progress via callback."""
    if callback:
        callback(f"Downloading {url}")

    req = urllib.request.Request(url, headers={"User-Agent": "homehost/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            total_str = resp.headers.get("Content-Length", "0")
            total = int(total_str) if total_str.isdigit() else 0
            downloaded = 0
            chunk_size = 65536  # 64 KiB

            with open(dest, "wb") as fh:
                while True:
                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break
                    fh.write(chunk)
                    downloaded += len(chunk)
                    if callback and total:
                        pct = int(downloaded * 100 / total)
                        callback(f"Downloading… {pct}% ({downloaded // 1024} KB / {total // 1024} KB)")
    except URLError as exc:
        raise OSError(f"Download failed: {exc}") from exc


# ── macOS installation helpers ─────────────────────────────────────────────────


def _install_via_brew(
    formula: str,
    callback: Callable[[str], None] | None,
) -> tuple[bool, str]:
    """Install *formula* via Homebrew. Return (success, error)."""
    if not _command_exists("brew"):
        return False, "Homebrew not installed"
    if callback:
        callback(f"Installing {formula} via Homebrew…")
    rc, stdout, stderr = _run(["brew", "install", formula], timeout=300)
    if rc != 0:
        return False, stderr or f"brew install {formula} failed (rc={rc})"
    found = shutil.which(formula.split("/")[-1])  # handle taps like user/tap/pkg
    return True, found or ""


# ── Windows installation helpers ───────────────────────────────────────────────


def _install_via_winget(
    package_id: str,
    callback: Callable[[str], None] | None,
) -> tuple[bool, str]:
    """Install via winget. Return (success, error)."""
    if not _command_exists("winget"):
        return False, "winget not available"
    if callback:
        callback(f"Installing {package_id} via winget…")
    rc, stdout, stderr = _run(
        ["winget", "install", "--id", package_id, "--silent", "--accept-source-agreements",
         "--accept-package-agreements"],
        timeout=300,
    )
    return (rc == 0, "" if rc == 0 else (stderr or stdout))


def _install_via_choco(
    package: str,
    callback: Callable[[str], None] | None,
) -> tuple[bool, str]:
    """Install via Chocolatey. Return (success, error)."""
    if not _command_exists("choco"):
        return False, "Chocolatey not installed"
    if callback:
        callback(f"Installing {package} via Chocolatey…")
    rc, stdout, stderr = _run(["choco", "install", package, "-y"], timeout=300)
    return (rc == 0, "" if rc == 0 else (stderr or stdout))


# ── Direct download: Caddy ─────────────────────────────────────────────────────


def _direct_install_caddy(callback: Callable[[str], None] | None) -> InstallResult:
    """Download the Caddy binary directly from GitHub releases."""
    bin_dir = _ensure_bin_dir()

    if callback:
        callback("Fetching latest Caddy release info…")

    tag = _fetch_latest_release_tag(_CADDY_GITHUB_API)
    if not tag:
        return InstallResult(
            success=False,
            error="Could not determine latest Caddy release from GitHub API",
        )

    # tag is e.g. "v2.8.4"; the archive name uses "2.8.4" (no 'v')
    version = tag.lstrip("v")
    arch = _machine_arch()

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        if _is_macos():
            mac_arch = "arm64" if arch == "arm64" else "amd64"
            archive_name = f"caddy_{version}_mac_{mac_arch}.tar.gz"
            url = (
                f"https://github.com/caddyserver/caddy/releases/download/{tag}/{archive_name}"
            )
            archive_path = tmp / archive_name
            try:
                _download_with_progress(url, archive_path, callback)
            except OSError as exc:
                return InstallResult(success=False, error=str(exc))

            if callback:
                callback("Extracting Caddy…")
            try:
                with tarfile.open(archive_path, "r:gz") as tf:
                    tf.extractall(tmp)
            except (tarfile.TarError, OSError) as exc:
                return InstallResult(success=False, error=f"Extraction failed: {exc}")

            extracted = tmp / "caddy"

        elif _is_windows():
            archive_name = f"caddy_{version}_windows_amd64.zip"
            url = (
                f"https://github.com/caddyserver/caddy/releases/download/{tag}/{archive_name}"
            )
            archive_path = tmp / archive_name
            try:
                _download_with_progress(url, archive_path, callback)
            except OSError as exc:
                return InstallResult(success=False, error=str(exc))

            if callback:
                callback("Extracting Caddy…")
            try:
                with zipfile.ZipFile(archive_path) as zf:
                    zf.extractall(tmp)
            except (zipfile.BadZipFile, OSError) as exc:
                return InstallResult(success=False, error=f"Extraction failed: {exc}")

            extracted = tmp / "caddy.exe"
        else:
            return InstallResult(success=False, error=f"Unsupported platform: {sys.platform}")

        if not extracted.exists():
            return InstallResult(
                success=False,
                error=f"Expected binary not found after extraction: {extracted}",
            )

        dest_name = "caddy.exe" if _is_windows() else "caddy"
        dest = bin_dir / dest_name
        shutil.copy2(extracted, dest)

        if not _is_windows():
            dest.chmod(dest.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    ok, ver_str = verify_caddy(str(dest))
    if not ok:
        return InstallResult(success=False, path=str(dest), error=f"Binary installed but verify failed: {ver_str}")

    if callback:
        callback(f"Caddy {ver_str} installed at {dest}")
    return InstallResult(success=True, path=str(dest), version=ver_str, method="direct")


# ── Direct download: cloudflared ──────────────────────────────────────────────


def _direct_install_cloudflared(callback: Callable[[str], None] | None) -> InstallResult:
    """Download the cloudflared binary directly from GitHub releases."""
    bin_dir = _ensure_bin_dir()

    if callback:
        callback("Fetching latest cloudflared release info…")

    tag = _fetch_latest_release_tag(_CLOUDFLARED_GITHUB_API)
    if not tag:
        return InstallResult(
            success=False,
            error="Could not determine latest cloudflared release from GitHub API",
        )

    arch = _machine_arch()

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        if _is_macos():
            # e.g. cloudflared-darwin-arm64 or cloudflared-darwin-amd64
            filename = f"cloudflared-darwin-{arch}"
            url = (
                f"https://github.com/cloudflare/cloudflared/releases/download/{tag}/{filename}"
            )
            dest = bin_dir / "cloudflared"
            tmp_bin = tmp / "cloudflared"
            try:
                _download_with_progress(url, tmp_bin, callback)
            except OSError as exc:
                return InstallResult(success=False, error=str(exc))
            shutil.copy2(tmp_bin, dest)
            dest.chmod(dest.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

        elif _is_windows():
            filename = "cloudflared-windows-amd64.exe"
            url = (
                f"https://github.com/cloudflare/cloudflared/releases/download/{tag}/{filename}"
            )
            dest = bin_dir / "cloudflared.exe"
            tmp_bin = tmp / "cloudflared.exe"
            try:
                _download_with_progress(url, tmp_bin, callback)
            except OSError as exc:
                return InstallResult(success=False, error=str(exc))
            shutil.copy2(tmp_bin, dest)
        else:
            return InstallResult(success=False, error=f"Unsupported platform: {sys.platform}")

    ok, ver_str = verify_cloudflared(str(dest))
    if not ok:
        return InstallResult(success=False, path=str(dest), error=f"Binary installed but verify failed: {ver_str}")

    if callback:
        callback(f"cloudflared {ver_str} installed at {dest}")
    return InstallResult(success=True, path=str(dest), version=ver_str, method="direct")


# ── Public API ─────────────────────────────────────────────────────────────────


def install_caddy(
    progress_callback: Callable[[str], None] | None = None,
) -> InstallResult:
    """Install Caddy.

    Try order: existing → brew (mac) / winget + choco (win) → direct binary download.
    """
    cb = progress_callback

    # 1. Already present?
    existing = get_caddy_path()
    if existing:
        ok, ver = verify_caddy(existing)
        if ok:
            if cb:
                cb(f"Caddy already installed at {existing} ({ver})")
            return InstallResult(success=True, path=existing, version=ver, method="existing")

    # 2. Package managers
    if _is_macos():
        ok, result = _install_via_brew("caddy", cb)
        if ok:
            found = shutil.which("caddy") or result
            v_ok, ver = verify_caddy(found)
            if v_ok:
                return InstallResult(success=True, path=found, version=ver, method="brew")

    elif _is_windows():
        ok, _err = _install_via_winget("Caddy.Caddy", cb)
        if ok:
            found = shutil.which("caddy") or ""
            if found:
                v_ok, ver = verify_caddy(found)
                if v_ok:
                    return InstallResult(success=True, path=found, version=ver, method="winget")

        ok, _err = _install_via_choco("caddy", cb)
        if ok:
            found = shutil.which("caddy") or ""
            if found:
                v_ok, ver = verify_caddy(found)
                if v_ok:
                    return InstallResult(success=True, path=found, version=ver, method="choco")

    # 3. Direct download
    if cb:
        cb("Falling back to direct binary download…")
    return _direct_install_caddy(cb)


def install_cloudflared(
    progress_callback: Callable[[str], None] | None = None,
) -> InstallResult:
    """Install cloudflared.

    Try order: existing → brew (mac) / winget + choco (win) → direct binary download.
    """
    cb = progress_callback

    # 1. Already present?
    existing = get_cloudflared_path()
    if existing:
        ok, ver = verify_cloudflared(existing)
        if ok:
            if cb:
                cb(f"cloudflared already installed at {existing} ({ver})")
            return InstallResult(success=True, path=existing, version=ver, method="existing")

    # 2. Package managers
    if _is_macos():
        ok, result = _install_via_brew("cloudflared", cb)
        if ok:
            found = shutil.which("cloudflared") or result
            v_ok, ver = verify_cloudflared(found)
            if v_ok:
                return InstallResult(success=True, path=found, version=ver, method="brew")

    elif _is_windows():
        ok, _err = _install_via_winget("Cloudflare.cloudflared", cb)
        if ok:
            found = shutil.which("cloudflared") or ""
            if found:
                v_ok, ver = verify_cloudflared(found)
                if v_ok:
                    return InstallResult(success=True, path=found, version=ver, method="winget")

        ok, _err = _install_via_choco("cloudflared", cb)
        if ok:
            found = shutil.which("cloudflared") or ""
            if found:
                v_ok, ver = verify_cloudflared(found)
                if v_ok:
                    return InstallResult(success=True, path=found, version=ver, method="choco")

    # 3. Direct download
    if cb:
        cb("Falling back to direct binary download…")
    return _direct_install_cloudflared(cb)
