"""Configuration system — read/write TOML configs for global and per-project settings."""

from __future__ import annotations

import contextlib
import os
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

import tomli_w

# ── Paths ──────────────────────────────────────────────────────────────────────


def homehost_dir() -> Path:
    """Return ~/.homehost, creating it if needed."""
    path = Path.home() / ".homehost"
    path.mkdir(parents=True, exist_ok=True)
    return path


def projects_dir() -> Path:
    """Return ~/.homehost/projects, creating it if needed."""
    path = homehost_dir() / "projects"
    path.mkdir(parents=True, exist_ok=True)
    return path


def global_config_path() -> Path:
    return homehost_dir() / "config.toml"


def project_config_path(name: str) -> Path:
    p = projects_dir() / name
    p.mkdir(parents=True, exist_ok=True)
    return p / "project.toml"


# ── Dataclasses ────────────────────────────────────────────────────────────────


@dataclass
class GeneralConfig:
    default_port_range: list[int] = field(default_factory=lambda: [8080, 8099])
    dashboard_port: int = 9111
    auto_start_on_boot: bool = False
    check_for_updates: bool = True
    log_level: str = "info"
    log_retention_days: int = 7


@dataclass
class ServerConfig:
    engine: str = "caddy"  # "caddy" | "builtin"
    caddy_path: str = ""
    cloudflared_path: str = ""


@dataclass
class NetworkConfig:
    default_access: str = "local"  # "local" | "public"
    tunnel_provider: str = "cloudflare"  # "cloudflare" | "duckdns"


@dataclass
class SecurityConfig:
    rate_limit: int = 100
    enable_security_headers: bool = True
    block_dotfiles: bool = True


@dataclass
class DashboardConfig:
    enabled: bool = True
    theme: str = "dark"


@dataclass
class GlobalConfig:
    general: GeneralConfig = field(default_factory=GeneralConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    network: NetworkConfig = field(default_factory=NetworkConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    dashboard: DashboardConfig = field(default_factory=DashboardConfig)


@dataclass
class ProjectServerConfig:
    port: int = 8080
    auto_start: bool = True
    build_command: str = ""
    start_command: str = ""
    output_directory: str = ""


@dataclass
class ProjectNetworkConfig:
    access: str = "local"  # "local" | "public"
    subdomain: str = ""
    custom_domain: str = ""
    # Quick tunnel (ephemeral, no account needed)
    tunnel_id: str = ""
    # Named tunnel (stable URL, requires Cloudflare account)
    tunnel_name: str = ""
    tunnel_hostname: str = ""  # e.g. api.paramchordiya.dev
    tunnel_credentials_file: str = ""  # path to ~/.cloudflared/<id>.json


@dataclass
class ProjectSecurityConfig:
    # Auth mode: "none" | "basic" | "apikey"
    auth_mode: str = "none"
    username: str = ""
    password_hash: str = ""  # $2a$ bcrypt hash (Caddy-compatible)
    api_key_hash: str = ""  # $2a$ bcrypt hash of the API key
    rate_limit: int = 100
    cors_origins: list[str] = field(default_factory=list)  # e.g. ["https://user.github.io"]
    # Legacy field — kept for backwards compatibility, maps to auth_mode == "basic"
    basic_auth: bool = False


@dataclass
class ProjectWatcherConfig:
    enabled: bool = True
    ignore: list[str] = field(default_factory=lambda: [".git", "node_modules", "__pycache__", ".DS_Store"])


@dataclass
class ProjectConfig:
    name: str = ""
    type: str = "static"  # static|flask|fastapi|django|nextjs|react|node|custom
    path: str = ""
    created: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    server: ProjectServerConfig = field(default_factory=ProjectServerConfig)
    network: ProjectNetworkConfig = field(default_factory=ProjectNetworkConfig)
    security: ProjectSecurityConfig = field(default_factory=ProjectSecurityConfig)
    watcher: ProjectWatcherConfig = field(default_factory=ProjectWatcherConfig)


# ── Read helpers ───────────────────────────────────────────────────────────────


def _load_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with open(path, "rb") as f:
        return tomllib.load(f)


def _atomic_write(path: Path, data: bytes, mode: int = 0o600) -> None:
    """Write atomically via a temp file in the same directory.

    Files are written with restrictive permissions (default 0600 — owner
    read/write only) since config files may contain bcrypt hashes.
    """
    dir_ = path.parent
    dir_.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dir_, suffix=".tmp")
    try:
        os.write(fd, data)
        os.close(fd)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


# ── GlobalConfig ───────────────────────────────────────────────────────────────


def load_global_config() -> GlobalConfig:
    """Load global config from disk, merging with defaults."""
    raw = _load_toml(global_config_path())

    cfg = GlobalConfig()

    g = raw.get("general", {})
    cfg.general.default_port_range = g.get("default_port_range", cfg.general.default_port_range)
    cfg.general.dashboard_port = g.get("dashboard_port", cfg.general.dashboard_port)
    cfg.general.auto_start_on_boot = g.get("auto_start_on_boot", cfg.general.auto_start_on_boot)
    cfg.general.check_for_updates = g.get("check_for_updates", cfg.general.check_for_updates)
    cfg.general.log_level = g.get("log_level", cfg.general.log_level)
    cfg.general.log_retention_days = g.get("log_retention_days", cfg.general.log_retention_days)

    s = raw.get("server", {})
    cfg.server.engine = s.get("engine", cfg.server.engine)
    cfg.server.caddy_path = s.get("caddy_path", cfg.server.caddy_path)
    cfg.server.cloudflared_path = s.get("cloudflared_path", cfg.server.cloudflared_path)

    n = raw.get("network", {})
    cfg.network.default_access = n.get("default_access", cfg.network.default_access)
    cfg.network.tunnel_provider = n.get("tunnel_provider", cfg.network.tunnel_provider)

    sec = raw.get("security", {})
    cfg.security.rate_limit = sec.get("rate_limit", cfg.security.rate_limit)
    cfg.security.enable_security_headers = sec.get("enable_security_headers", cfg.security.enable_security_headers)
    cfg.security.block_dotfiles = sec.get("block_dotfiles", cfg.security.block_dotfiles)

    d = raw.get("dashboard", {})
    cfg.dashboard.enabled = d.get("enabled", cfg.dashboard.enabled)
    cfg.dashboard.theme = d.get("theme", cfg.dashboard.theme)

    return cfg


def save_global_config(cfg: GlobalConfig) -> None:
    """Persist global config to disk atomically."""
    data: dict[str, Any] = {
        "general": {
            "default_port_range": cfg.general.default_port_range,
            "dashboard_port": cfg.general.dashboard_port,
            "auto_start_on_boot": cfg.general.auto_start_on_boot,
            "check_for_updates": cfg.general.check_for_updates,
            "log_level": cfg.general.log_level,
            "log_retention_days": cfg.general.log_retention_days,
        },
        "server": {
            "engine": cfg.server.engine,
            "caddy_path": cfg.server.caddy_path,
            "cloudflared_path": cfg.server.cloudflared_path,
        },
        "network": {
            "default_access": cfg.network.default_access,
            "tunnel_provider": cfg.network.tunnel_provider,
        },
        "security": {
            "rate_limit": cfg.security.rate_limit,
            "enable_security_headers": cfg.security.enable_security_headers,
            "block_dotfiles": cfg.security.block_dotfiles,
        },
        "dashboard": {
            "enabled": cfg.dashboard.enabled,
            "theme": cfg.dashboard.theme,
        },
    }
    _atomic_write(global_config_path(), tomli_w.dumps(data).encode())


# ── ProjectConfig ──────────────────────────────────────────────────────────────


def load_project_config(name: str) -> ProjectConfig:
    """Load a project's config from disk."""
    raw = _load_toml(project_config_path(name))

    cfg = ProjectConfig()

    p = raw.get("project", {})
    cfg.name = p.get("name", name)
    cfg.type = p.get("type", cfg.type)
    cfg.path = p.get("path", cfg.path)
    cfg.created = p.get("created", cfg.created)

    s = raw.get("server", {})
    cfg.server.port = s.get("port", cfg.server.port)
    cfg.server.auto_start = s.get("auto_start", cfg.server.auto_start)
    cfg.server.build_command = s.get("build_command", cfg.server.build_command)
    cfg.server.start_command = s.get("start_command", cfg.server.start_command)
    cfg.server.output_directory = s.get("output_directory", cfg.server.output_directory)

    n = raw.get("network", {})
    cfg.network.access = n.get("access", cfg.network.access)
    cfg.network.subdomain = n.get("subdomain", cfg.network.subdomain)
    cfg.network.custom_domain = n.get("custom_domain", cfg.network.custom_domain)
    cfg.network.tunnel_id = n.get("tunnel_id", cfg.network.tunnel_id)
    cfg.network.tunnel_name = n.get("tunnel_name", cfg.network.tunnel_name)
    cfg.network.tunnel_hostname = n.get("tunnel_hostname", cfg.network.tunnel_hostname)
    cfg.network.tunnel_credentials_file = n.get("tunnel_credentials_file", cfg.network.tunnel_credentials_file)

    sec = raw.get("security", {})
    cfg.security.auth_mode = sec.get("auth_mode", cfg.security.auth_mode)
    cfg.security.basic_auth = sec.get("basic_auth", cfg.security.basic_auth)
    cfg.security.username = sec.get("username", cfg.security.username)
    cfg.security.password_hash = sec.get("password_hash", cfg.security.password_hash)
    cfg.security.api_key_hash = sec.get("api_key_hash", cfg.security.api_key_hash)
    cfg.security.rate_limit = sec.get("rate_limit", cfg.security.rate_limit)
    cfg.security.cors_origins = sec.get("cors_origins", cfg.security.cors_origins)
    # Backwards compat: migrate basic_auth bool → auth_mode
    if cfg.security.basic_auth and cfg.security.auth_mode == "none":
        cfg.security.auth_mode = "basic"

    w = raw.get("watcher", {})
    cfg.watcher.enabled = w.get("enabled", cfg.watcher.enabled)
    cfg.watcher.ignore = w.get("ignore", cfg.watcher.ignore)

    return cfg


def save_project_config(cfg: ProjectConfig) -> None:
    """Persist a project's config to disk atomically."""
    data: dict[str, Any] = {
        "project": {
            "name": cfg.name,
            "type": cfg.type,
            "path": cfg.path,
            "created": cfg.created,
        },
        "server": {
            "port": cfg.server.port,
            "auto_start": cfg.server.auto_start,
            "build_command": cfg.server.build_command,
            "start_command": cfg.server.start_command,
            "output_directory": cfg.server.output_directory,
        },
        "network": {
            "access": cfg.network.access,
            "subdomain": cfg.network.subdomain,
            "custom_domain": cfg.network.custom_domain,
            "tunnel_id": cfg.network.tunnel_id,
            "tunnel_name": cfg.network.tunnel_name,
            "tunnel_hostname": cfg.network.tunnel_hostname,
            "tunnel_credentials_file": cfg.network.tunnel_credentials_file,
        },
        "security": {
            "auth_mode": cfg.security.auth_mode,
            "basic_auth": cfg.security.basic_auth,
            "username": cfg.security.username,
            "password_hash": cfg.security.password_hash,
            "api_key_hash": cfg.security.api_key_hash,
            "rate_limit": cfg.security.rate_limit,
            "cors_origins": cfg.security.cors_origins,
        },
        "watcher": {
            "enabled": cfg.watcher.enabled,
            "ignore": cfg.watcher.ignore,
        },
    }
    _atomic_write(project_config_path(cfg.name), tomli_w.dumps(data).encode())


def delete_project_config(name: str) -> None:
    """Remove a project's config directory from ~/.homehost/projects/."""
    import shutil

    p = projects_dir() / name
    if p.exists():
        shutil.rmtree(p)


def list_projects() -> list[str]:
    """Return names of all registered projects."""
    return [d.name for d in sorted(projects_dir().iterdir()) if d.is_dir()]
