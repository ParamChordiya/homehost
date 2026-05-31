"""Caddy configuration generation and lifecycle management.

Generates per-project Caddyfiles, a master importer Caddyfile, and manages
the Caddy process (start / stop / reload / status).
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
from typing import IO, TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

# Only alphanumeric, underscore, dot, hyphen — safe to inject into Caddyfile
_SAFE_USERNAME_RE = re.compile(r"^[A-Za-z0-9_.@-]{1,64}$")


# ── Helpers ────────────────────────────────────────────────────────────────────


def _projects_subdir(data_dir: Path) -> Path:
    p = data_dir / "projects"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _log_dir(data_dir: Path, project_name: str) -> Path:
    p = data_dir / "projects" / project_name / "logs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _validate_username(username: str) -> str:
    """Validate and return username, raising ValueError if unsafe."""
    if not _SAFE_USERNAME_RE.match(username):
        raise ValueError(
            f"Invalid username {username!r}. Only letters, digits, _, ., @, and - are allowed (max 64 chars)."
        )
    return username


def _cors_block(origins: list[str]) -> list[str]:
    """Return Caddyfile lines for CORS support.

    Handles preflight (OPTIONS) correctly: the ``handle @cors_preflight``
    block terminates the chain for OPTIONS requests so the ``basicauth``
    directive below it is never evaluated for preflights.  Without this,
    browsers reject cross-origin requests before even sending credentials.
    """
    if not origins:
        return []

    origin = origins[0]  # primary allowed origin
    return [
        "    # CORS — preflight must resolve before auth",
        "    @cors_preflight method OPTIONS",
        "    handle @cors_preflight {",
        f'        header Access-Control-Allow-Origin "{origin}"',
        '        header Access-Control-Allow-Methods "GET, POST, PUT, DELETE, PATCH, OPTIONS"',
        '        header Access-Control-Allow-Headers "Content-Type, Authorization, X-Requested-With"',
        '        header Access-Control-Max-Age "7200"',
        '        header Access-Control-Allow-Credentials "true"',
        "        respond 204",
        "    }",
        f'    header Access-Control-Allow-Origin "{origin}"',
        '    header Access-Control-Allow-Credentials "true"',
        "",
    ]


def _auth_block(auth_mode: str, username: str, password_hash: str, api_key_hash: str) -> list[str]:
    """Return Caddyfile lines for authentication.

    Uses a ``@non_preflight`` matcher so CORS preflight (OPTIONS) requests
    are exempt — the CORS preflight ``handle`` block above terminates first.

    Both modes use Caddy's ``basicauth`` directive with a ``$2a$`` bcrypt
    hash.  For ``apikey`` mode the username is fixed to ``api`` and the
    hash is of the API key; clients send ``Authorization: Basic base64(api:<key>)``.
    """
    if auth_mode == "none":
        return []

    if auth_mode == "basic":
        if not username or not password_hash:
            return []
        safe_user = _validate_username(username)
        return [
            "    # Auth — OPTIONS exempt (CORS preflight handled above)",
            "    @non_preflight not method OPTIONS",
            "    basicauth @non_preflight {",
            f"        {safe_user} {password_hash}",
            "    }",
            "",
        ]

    if auth_mode == "apikey":
        if not api_key_hash:
            return []
        return [
            "    # API key auth — clients send: Authorization: Basic base64(api:<key>)",
            "    @non_preflight not method OPTIONS",
            "    basicauth @non_preflight {",
            f"        api {api_key_hash}",
            "    }",
            "",
        ]

    return []


def _log_block(log_file_path: str, strip_auth: bool = False) -> list[str]:
    """Return Caddyfile log block, optionally stripping the Authorization header."""
    if not strip_auth:
        return [
            "    log {",
            f"        output file {log_file_path}",
            "        format json",
            "    }",
        ]
    # Filter out Authorization header so API keys are never written to disk
    return [
        "    log {",
        f"        output file {log_file_path}",
        "        format filter {",
        "            wrap json",
        "            fields {",
        "                request>headers>Authorization delete",
        "            }",
        "        }",
        "    }",
    ]


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
        auth_mode: str = "none",
        username: str = "",
        password_hash: str = "",
        api_key_hash: str = "",
        cors_origins: list[str] | None = None,
    ) -> str:
        """Generate Caddyfile content for a static site."""
        site_addr = domain.strip() if domain.strip() else f":{port}"
        log_file = _log_dir(self._data_dir, project_name) / "access.log"
        origins = cors_origins or []
        has_auth = auth_mode in ("basic", "apikey")

        lines: list[str] = [f"{site_addr} {{"]

        # CORS must come first so preflight terminates before auth check
        lines += _cors_block(origins)

        # Auth block (exempt OPTIONS via @non_preflight matcher)
        lines += _auth_block(auth_mode, username, password_hash, api_key_hash)

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

        lines += [
            "    # Rate limiting requires the caddy-ratelimit plugin.",
            f"    # If installed: rate_limit {{events {rate_limit} / 1m}}",
            "",
            "    encode gzip zstd",
            "",
        ]

        lines += _log_block(str(log_file), strip_auth=has_auth)
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
        auth_mode: str = "none",
        username: str = "",
        password_hash: str = "",
        api_key_hash: str = "",
        cors_origins: list[str] | None = None,
    ) -> str:
        """Generate Caddyfile content for reverse proxy to app server."""
        site_addr = domain.strip() if domain.strip() else f":{port}"
        log_file = _log_dir(self._data_dir, project_name) / "access.log"
        origins = cors_origins or []
        has_auth = auth_mode in ("basic", "apikey")

        lines: list[str] = [f"{site_addr} {{"]

        # CORS must come first so preflight terminates before auth check
        lines += _cors_block(origins)

        # Auth block (exempt OPTIONS via @non_preflight matcher)
        lines += _auth_block(auth_mode, username, password_hash, api_key_hash)

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

        lines += [
            "    # Rate limiting requires the caddy-ratelimit plugin.",
            f"    # If installed: rate_limit {{events {rate_limit} / 1m}}",
            "",
            "    encode gzip zstd",
            "",
        ]

        lines += _log_block(str(log_file), strip_auth=has_auth)
        lines.append("}")
        return "\n".join(lines) + "\n"

    def write_project_caddyfile(self, project_name: str, content: str) -> Path:
        """Write to ~/.homehost/projects/<name>/Caddyfile with 0600 permissions.

        Restrictive permissions prevent other local users from reading the
        bcrypt hashes stored in the basicauth block.
        """
        project_dir = _projects_subdir(self._data_dir) / project_name
        project_dir.mkdir(parents=True, exist_ok=True)
        caddyfile = project_dir / "Caddyfile"

        # Atomic write with restricted permissions
        data = content.encode("utf-8")
        fd, tmp = tempfile.mkstemp(dir=project_dir, suffix=".tmp")
        try:
            os.write(fd, data)
            os.close(fd)
            os.chmod(tmp, 0o600)
            os.replace(tmp, caddyfile)
        except Exception:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise

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
