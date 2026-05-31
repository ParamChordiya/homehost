"""Caddy configuration generation and lifecycle management.

Generates per-project Caddyfiles, a master importer Caddyfile, and manages
the Caddy process (start / stop / reload / status).
"""

from __future__ import annotations

import contextlib
import logging
import signal
import subprocess
import sys
import time
from typing import IO, TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)


# ── Helpers ────────────────────────────────────────────────────────────────────


def _projects_subdir(data_dir: Path) -> Path:
    p = data_dir / "projects"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _log_dir(data_dir: Path, project_name: str) -> Path:
    p = data_dir / "projects" / project_name / "logs"
    p.mkdir(parents=True, exist_ok=True)
    return p


# ── CaddyManager ──────────────────────────────────────────────────────────────


class CaddyManager:
    """Manages Caddy installation, Caddyfile generation, and process lifecycle."""

    def __init__(self, caddy_path: str, data_dir: Path) -> None:
        self._caddy_path = caddy_path
        self._data_dir = data_dir
        self._master_caddyfile = data_dir / "Caddyfile"
        self._process: subprocess.Popen[bytes] | None = None
        self._log_file: IO[bytes] | None = None

    # ── Caddyfile generation ───────────────────────────────────────────────────

    def generate_static_caddyfile(
        self,
        project_name: str,
        serve_dir: Path,
        port: int,
        domain: str = "",
        security_headers: bool = True,
        rate_limit: int = 100,
        basic_auth: bool = False,
        username: str = "",
        password_hash: str = "",
    ) -> str:
        """Generate Caddyfile content for a static site."""
        site_addr = domain.strip() if domain.strip() else f":{port}"
        log_file = _log_dir(self._data_dir, project_name) / "access.log"

        lines: list[str] = [f"{site_addr} {{"]

        lines += [
            f"    root * {serve_dir}",
            "    file_server",
            "",
        ]

        # Block dotfiles
        lines += [
            "    @dotfiles path */.*",
            "    respond @dotfiles 403",
            "",
        ]

        # Security headers
        if security_headers:
            lines += [
                "    header {",
                "        X-Content-Type-Options nosniff",
                "        X-Frame-Options DENY",
                '        Strict-Transport-Security "max-age=31536000; includeSubDomains; preload"',
                "        Referrer-Policy strict-origin-when-cross-origin",
                "        Content-Security-Policy \"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'\"",
                "        -Server",
                "    }",
                "",
            ]

        # Basic auth
        if basic_auth and username and password_hash:
            lines += [
                "    basicauth {",
                f"        {username} {password_hash}",
                "    }",
                "",
            ]

        # Rate limiting (caddy-ratelimit module, skipped with comment if not available)
        lines += [
            "    # Rate limiting requires the caddy-ratelimit plugin.",
            f"    # If installed: rate_limit {{events {rate_limit} / 1m}}",
            "",
        ]

        # Encode (gzip/zstd)
        lines += ["    encode gzip zstd", ""]

        # Access log
        lines += [
            "    log {",
            "        output file " + str(log_file),
            "        format json",
            "    }",
        ]

        lines.append("}")
        return "\n".join(lines) + "\n"

    def generate_proxy_caddyfile(
        self,
        project_name: str,
        upstream_port: int,
        port: int,
        domain: str = "",
        security_headers: bool = True,
        rate_limit: int = 100,
    ) -> str:
        """Generate Caddyfile content for reverse proxy to app server."""
        site_addr = domain.strip() if domain.strip() else f":{port}"
        log_file = _log_dir(self._data_dir, project_name) / "access.log"

        lines: list[str] = [f"{site_addr} {{"]

        lines += [
            f"    reverse_proxy localhost:{upstream_port} {{",
            "        header_up X-Real-IP {remote_host}",
            "        header_up X-Forwarded-For {remote_host}",
            "        header_up X-Forwarded-Proto {scheme}",
            "        health_uri /",
            "        health_interval 10s",
            "        health_timeout 5s",
            "    }",
            "",
        ]

        # Block dotfiles
        lines += [
            "    @dotfiles path */.*",
            "    respond @dotfiles 403",
            "",
        ]

        # Security headers
        if security_headers:
            lines += [
                "    header {",
                "        X-Content-Type-Options nosniff",
                "        X-Frame-Options DENY",
                '        Strict-Transport-Security "max-age=31536000; includeSubDomains; preload"',
                "        Referrer-Policy strict-origin-when-cross-origin",
                "        -Server",
                "    }",
                "",
            ]

        # Rate limiting comment
        lines += [
            "    # Rate limiting requires the caddy-ratelimit plugin.",
            f"    # If installed: rate_limit {{events {rate_limit} / 1m}}",
            "",
        ]

        # Encode
        lines += ["    encode gzip zstd", ""]

        # Access log
        lines += [
            "    log {",
            "        output file " + str(log_file),
            "        format json",
            "    }",
        ]

        lines.append("}")
        return "\n".join(lines) + "\n"

    def write_project_caddyfile(self, project_name: str, content: str) -> Path:
        """Write to ~/.homehost/projects/<name>/Caddyfile."""
        project_dir = _projects_subdir(self._data_dir) / project_name
        project_dir.mkdir(parents=True, exist_ok=True)
        caddyfile = project_dir / "Caddyfile"
        caddyfile.write_text(content, encoding="utf-8")
        logger.debug("Wrote Caddyfile for %s at %s", project_name, caddyfile)
        return caddyfile

    def write_master_caddyfile(self, project_names: list[str]) -> Path:
        """Write master Caddyfile that imports all per-project ones."""
        projects_base = _projects_subdir(self._data_dir)
        lines: list[str] = [
            "# HomeHost — master Caddyfile",
            "# Auto-generated. Do not edit manually.",
            "",
        ]
        for name in project_names:
            caddyfile_path = projects_base / name / "Caddyfile"
            if caddyfile_path.exists():
                lines.append(f"import {caddyfile_path}")

        content = "\n".join(lines) + "\n"
        self._master_caddyfile.write_text(content, encoding="utf-8")
        logger.debug("Wrote master Caddyfile at %s", self._master_caddyfile)
        return self._master_caddyfile

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def start(self) -> bool:
        """Start Caddy with the master Caddyfile. Return True on success."""
        if self.is_running():
            logger.info("Caddy is already running")
            return True

        if not self._master_caddyfile.exists():
            logger.error("Master Caddyfile does not exist: %s", self._master_caddyfile)
            return False

        # Validate config before starting
        rc = subprocess.run(
            [self._caddy_path, "validate", "--config", str(self._master_caddyfile)],
            capture_output=True,
        ).returncode
        if rc != 0:
            logger.error("Caddy config validation failed — refusing to start")
            return False

        caddy_log = self._data_dir / "caddy.log"
        try:
            self._log_file = open(caddy_log, "ab")  # noqa: SIM115
            self._process = subprocess.Popen(
                [
                    self._caddy_path,
                    "run",
                    "--config",
                    str(self._master_caddyfile),
                    "--adapter",
                    "caddyfile",
                ],
                stdout=self._log_file,
                stderr=self._log_file,
                close_fds=True,
            )
        except OSError as exc:
            logger.exception("Failed to start Caddy: %s", exc)
            return False

        # Give Caddy a moment to fail fast (e.g. port already in use)
        time.sleep(0.5)
        if self._process.poll() is not None:
            logger.error("Caddy exited immediately (rc=%d)", self._process.returncode)
            return False

        logger.info("Caddy started (pid=%d)", self._process.pid)
        return True

    def stop(self) -> bool:
        """Gracefully stop Caddy."""
        if self._process is None:
            # Try to find and stop an externally started Caddy
            return self._stop_external_caddy()

        if self._process.poll() is not None:
            self._process = None
            return True

        try:
            if sys.platform == "win32":
                self._process.terminate()
            else:
                self._process.send_signal(signal.SIGTERM)

            try:
                self._process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                logger.warning("Caddy did not exit gracefully; killing")
                self._process.kill()
                self._process.wait(timeout=5)
        except OSError as exc:
            logger.error("Error stopping Caddy: %s", exc)
            return False
        finally:
            if self._log_file is not None:
                with contextlib.suppress(OSError):
                    self._log_file.close()
                self._log_file = None
            self._process = None

        logger.info("Caddy stopped")
        return True

    def _stop_external_caddy(self) -> bool:
        """Send `caddy stop` to any running Caddy instance via its admin API."""
        try:
            result = subprocess.run(
                [self._caddy_path, "stop"],
                capture_output=True,
                timeout=10,
            )
            return result.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            return False

    def reload(self) -> bool:
        """Reload Caddy config without downtime (`caddy reload`)."""
        if not self._master_caddyfile.exists():
            logger.error("Master Caddyfile does not exist: %s", self._master_caddyfile)
            return False

        try:
            result = subprocess.run(
                [
                    self._caddy_path,
                    "reload",
                    "--config",
                    str(self._master_caddyfile),
                    "--adapter",
                    "caddyfile",
                ],
                capture_output=True,
                timeout=15,
            )
            if result.returncode != 0:
                logger.error(
                    "caddy reload failed (rc=%d): %s",
                    result.returncode,
                    result.stderr.decode(errors="replace"),
                )
                return False
        except (OSError, subprocess.TimeoutExpired) as exc:
            logger.error("caddy reload error: %s", exc)
            return False

        logger.info("Caddy reloaded successfully")
        return True

    def is_running(self) -> bool:
        """Check if Caddy process is alive."""
        if self._process is not None:
            return self._process.poll() is None

        # Check for any caddy process via admin API
        try:
            subprocess.run(
                [self._caddy_path, "environ"],
                capture_output=True,
                timeout=3,
            )
            # If caddy is running, `caddy environ` returns 0
            # But the most reliable way without psutil is to check via admin API
            # We'll use a lightweight approach: check if admin socket responds
            return self._ping_admin_api()
        except (OSError, subprocess.TimeoutExpired):
            return False

    def _ping_admin_api(self) -> bool:
        """Ping the Caddy admin API (localhost:2019) to check if it's alive."""
        import socket

        try:
            with socket.create_connection(("127.0.0.1", 2019), timeout=1):
                return True
        except OSError:
            return False

    def get_version(self) -> str:
        """Return Caddy version string."""
        try:
            result = subprocess.run(
                [self._caddy_path, "version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return result.stdout.strip().split("\n")[0]
        except (OSError, subprocess.TimeoutExpired):
            pass
        return ""
