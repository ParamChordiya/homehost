"""Named Cloudflare Tunnel management — stable public URLs that persist across restarts."""

from __future__ import annotations

import json
import logging
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# UUID pattern used in tunnel IDs
_UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE)


@dataclass
class NamedTunnelInfo:
    tunnel_id: str
    tunnel_name: str
    hostname: str  # e.g. api.paramchordiya.dev
    credentials_file: str  # absolute path to cloudflared credentials JSON
    config_file: str  # absolute path to generated cloudflared config YAML
    local_port: int

    @property
    def public_url(self) -> str:
        return f"https://{self.hostname}"


class NamedTunnelManager:
    """Create, configure, and run named Cloudflare Tunnels.

    Named tunnels give a project a stable, permanent public URL (e.g.
    ``api.yoursite.dev``) that survives restarts — unlike quick tunnels
    which generate a random ``trycloudflare.com`` URL each time.

    Prerequisites
    -------------
    - ``cloudflared`` installed (``homehost doctor`` checks this)
    - A Cloudflare account (free tier works)
    - The target domain's DNS managed by Cloudflare (for automatic DNS routing)
    """

    def __init__(self, cloudflared_path: str, homehost_dir: Path) -> None:
        self._cloudflared = cloudflared_path
        self._tunnels_dir = homehost_dir / "tunnels"
        self._tunnels_dir.mkdir(parents=True, exist_ok=True)

    # ── Cloudflare account ────────────────────────────────────────────────────

    def login(self) -> bool:
        """Run ``cloudflared login`` to authorise this machine.

        Opens a browser window.  Returns ``True`` if the cert was saved.
        """
        try:
            result = subprocess.run(
                [self._cloudflared, "login"],
                timeout=120,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, OSError):
            return False

    def is_logged_in(self) -> bool:
        """Return True if a Cloudflare cert already exists."""
        cert = Path.home() / ".cloudflared" / "cert.pem"
        return cert.exists()

    # ── Tunnel CRUD ───────────────────────────────────────────────────────────

    def create_tunnel(self, name: str) -> tuple[str, Path]:
        """Run ``cloudflared tunnel create <name>``.

        Returns ``(tunnel_id, credentials_file_path)``.

        Raises
        ------
        RuntimeError
            If cloudflared returns non-zero or the output cannot be parsed.
        """
        result = subprocess.run(
            [self._cloudflared, "tunnel", "create", "--output", "json", name],
            capture_output=True,
            text=True,
            timeout=30,
        )

        # Try JSON output first (cloudflared ≥ 2022)
        if result.returncode == 0:
            try:
                data = json.loads(result.stdout)
                tunnel_id: str = data["id"]
                creds_raw: str = data.get("credentials_file", "")
                creds_path = (
                    Path(creds_raw).expanduser() if creds_raw else Path.home() / ".cloudflared" / f"{tunnel_id}.json"
                )
                if creds_path.exists():
                    return tunnel_id, creds_path
            except (json.JSONDecodeError, KeyError):
                pass  # fall through to text parsing

        # Fallback: parse text output
        combined = result.stdout + result.stderr
        match = _UUID_RE.search(combined)
        if result.returncode == 0 and match:
            tunnel_id = match.group(0)
            creds_path = Path.home() / ".cloudflared" / f"{tunnel_id}.json"
            return tunnel_id, creds_path

        raise RuntimeError(f"cloudflared tunnel create failed (exit {result.returncode}):\n{result.stderr.strip()}")

    def route_dns(self, tunnel_id: str, hostname: str) -> None:
        """Create a DNS CNAME at Cloudflare routing ``hostname`` → this tunnel.

        Raises
        ------
        RuntimeError
            If the DNS route could not be created.
        """
        result = subprocess.run(
            [self._cloudflared, "tunnel", "route", "dns", tunnel_id, hostname],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(f"DNS route setup failed (exit {result.returncode}):\n{result.stderr.strip()}")

    def list_tunnels(self) -> list[dict[str, str]]:
        """Return tunnels registered in the Cloudflare account."""
        try:
            result = subprocess.run(
                [self._cloudflared, "tunnel", "list", "--output", "json"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if result.returncode != 0:
                return []
            items = json.loads(result.stdout)
            return [
                {
                    "id": t.get("id", ""),
                    "name": t.get("name", ""),
                    "created": t.get("created_at", ""),
                    "status": t.get("status", ""),
                }
                for t in items
            ]
        except Exception:
            return []

    # ── Config generation ─────────────────────────────────────────────────────

    def generate_config(
        self,
        tunnel_id: str,
        credentials_file: Path,
        hostname: str,
        local_port: int,
    ) -> Path:
        """Write a cloudflared YAML config file and return its path.

        The config routes ``https://<hostname>`` → ``http://127.0.0.1:<local_port>``.
        All unmatched ingress returns HTTP 404.
        """
        config_path = self._tunnels_dir / f"{tunnel_id}.yml"

        # Written without PyYAML to avoid adding a dependency
        lines = [
            f"tunnel: {tunnel_id}",
            f"credentials-file: {credentials_file}",
            "",
            "ingress:",
            f"  - hostname: {hostname}",
            f"    service: http://127.0.0.1:{local_port}",
            "  - service: http_status:404",
            "",
        ]
        config_path.write_text("\n".join(lines), encoding="utf-8")
        log.debug("Wrote cloudflared config to %s", config_path)
        return config_path

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(
        self,
        project_name: str,
        tunnel_id: str,
        credentials_file: Path,
        hostname: str,
        local_port: int,
        process_manager: Any,
    ) -> NamedTunnelInfo:
        """Generate config and launch ``cloudflared tunnel run``."""
        config_path = self.generate_config(tunnel_id, credentials_file, hostname, local_port)

        cmd = [
            self._cloudflared,
            "tunnel",
            "--no-autoupdate",
            "--config",
            str(config_path),
            "run",
            tunnel_id,
        ]

        log_file = self._tunnels_dir / f"{project_name}.log"
        process_manager.start(
            f"tunnel_{project_name}",
            cmd,
            cwd=self._tunnels_dir,
            log_file=log_file,
        )

        log.info("Named tunnel started: %s → https://%s", project_name, hostname)

        return NamedTunnelInfo(
            tunnel_id=tunnel_id,
            tunnel_name=project_name,
            hostname=hostname,
            credentials_file=str(credentials_file),
            config_file=str(config_path),
            local_port=local_port,
        )

    @staticmethod
    def cname_target(tunnel_id: str) -> str:
        """Return the CNAME value users must create if DNS routing fails."""
        return f"{tunnel_id}.cfargotunnel.com"
