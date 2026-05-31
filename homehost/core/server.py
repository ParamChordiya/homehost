"""High-level server lifecycle — orchestrates Caddy, app processes, and tunnels."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

from homehost.core.config import (
    GlobalConfig,
    ProjectConfig,
    list_projects,
    load_global_config,
    load_project_config,
    save_project_config,
)
from homehost.core.process import ProcessManager, ProcessState
from homehost.core.project import ProjectType
from homehost.utils.network import find_free_port, get_local_ip, wait_for_port

if TYPE_CHECKING:
    from collections.abc import Callable


class ServerStatus(str, Enum):
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass
class RunningProject:
    name: str
    project_type: str
    status: ServerStatus
    local_port: int
    local_url: str
    public_url: str
    start_time: float = field(default_factory=time.time)
    request_count: int = 0
    error_message: str = ""

    @property
    def uptime_seconds(self) -> int:
        if self.status == ServerStatus.RUNNING:
            return int(time.time() - self.start_time)
        return 0

    @property
    def uptime_human(self) -> str:
        s = self.uptime_seconds
        if s < 60:
            return f"{s}s"
        if s < 3600:
            return f"{s // 60}m {s % 60}s"
        h = s // 3600
        m = (s % 3600) // 60
        return f"{h}h {m}m"


class ServerManager:
    """Orchestrates the lifecycle of all HomeHost projects.

    Coordinates: ProcessManager (raw processes), CaddyManager, TunnelManager.
    """

    def __init__(self, global_config: GlobalConfig | None = None) -> None:
        self._global_config = global_config or load_global_config()
        self._run_dir = Path.home() / ".homehost" / "run"
        self._run_dir.mkdir(parents=True, exist_ok=True)
        self._process_manager = ProcessManager(self._run_dir)
        self._running: dict[str, RunningProject] = {}

    # ── Public API ────────────────────────────────────────────────────────────

    def start_project(
        self,
        name: str,
        progress: Callable[[str], None] | None = None,
    ) -> RunningProject:
        """Start a registered project end-to-end.

        Steps:
        1. Load project config
        2. Find a free port
        3. Start the appropriate server (static or app via reverse proxy)
        4. Configure Caddy to serve it
        5. Start tunnel if public access requested
        6. Return RunningProject with all URLs
        """

        def _log(msg: str) -> None:
            if progress:
                progress(msg)

        cfg = load_project_config(name)
        _log(f"Loading config for '{name}'")

        # ── Pick port ─────────────────────────────────────────────────────────
        port = cfg.server.port
        if self._is_port_taken(port):
            start, end = self._global_config.general.default_port_range
            port = find_free_port(start, end)
            cfg.server.port = port
            save_project_config(cfg)
            _log(f"Port {cfg.server.port} was in use, switched to {port}")

        project_dir = Path(cfg.path)
        project_type = ProjectType(cfg.type)

        running = RunningProject(
            name=name,
            project_type=cfg.type,
            status=ServerStatus.STARTING,
            local_port=port,
            local_url=f"http://{get_local_ip()}:{port}",
            public_url="",
        )
        self._running[name] = running

        # ── Start server ──────────────────────────────────────────────────────
        try:
            if project_type == ProjectType.STATIC:
                _log("Starting static file server…")
                self._start_static(name, project_dir, port, cfg)
            else:
                _log(f"Starting {project_type.label} app server…")
                self._start_app_server(name, project_dir, port, cfg, project_type)

            _log(f"Waiting for server to be ready on port {port}…")
            if not wait_for_port("127.0.0.1", port, timeout=30):
                raise RuntimeError(f"Server did not start on port {port} within 30 seconds")

            running.status = ServerStatus.RUNNING
            _log(f"Server is live at http://localhost:{port}")

        except Exception as exc:
            running.status = ServerStatus.ERROR
            running.error_message = str(exc)
            raise

        # ── Start tunnel ──────────────────────────────────────────────────────
        if cfg.network.access == "public":
            use_named = bool(cfg.network.tunnel_hostname and cfg.network.tunnel_credentials_file)
            if use_named:
                _log(f"Starting named tunnel → https://{cfg.network.tunnel_hostname}…")
            else:
                _log("Starting Cloudflare quick tunnel for public access…")
            try:
                if use_named:
                    tunnel_url = self._start_named_tunnel(name, port, cfg)
                else:
                    tunnel_url = self._start_quick_tunnel(name, port, cfg)
                running.public_url = tunnel_url
                _log(f"Public URL: {tunnel_url}")
            except Exception as exc:
                _log(f"Warning: tunnel failed ({exc}). Site is local-only.")

        return running

    def stop_project(self, name: str) -> bool:
        """Stop all processes for a project. Returns True on success."""
        stopped = self._process_manager.stop(name)
        # Also stop the tunnel process if running
        self._process_manager.stop(f"{name}_tunnel")

        if name in self._running:
            self._running[name].status = ServerStatus.STOPPED

        return stopped

    def restart_project(
        self,
        name: str,
        progress: Callable[[str], None] | None = None,
    ) -> RunningProject:
        """Stop then start a project."""
        self.stop_project(name)
        time.sleep(1)
        return self.start_project(name, progress)

    def get_status(self, name: str) -> ServerStatus:
        """Return current status for a project."""
        if name in self._running:
            state = self._process_manager.status(name)
            if state == ProcessState.RUNNING:
                return ServerStatus.RUNNING
            if state == ProcessState.STOPPED:
                return ServerStatus.STOPPED
            if state == ProcessState.ERROR:
                return ServerStatus.ERROR
        return ServerStatus.STOPPED

    def get_project(self, name: str) -> RunningProject | None:
        return self._running.get(name)

    def get_all_projects(self) -> list[RunningProject]:
        """Return status for all registered projects."""
        projects = []
        for name in list_projects():
            cfg = load_project_config(name)
            state = self.get_status(name)
            local_ip = get_local_ip()

            if name in self._running:
                rp = self._running[name]
                rp.status = state
                projects.append(rp)
            else:
                projects.append(
                    RunningProject(
                        name=name,
                        project_type=cfg.type,
                        status=state,
                        local_port=cfg.server.port,
                        local_url=f"http://{local_ip}:{cfg.server.port}",
                        public_url=cfg.network.subdomain or "",
                        start_time=0.0,
                    )
                )
        return projects

    def stop_all(self) -> None:
        """Stop all running projects."""
        for name in list(self._running.keys()):
            self.stop_project(name)
        self._process_manager.stop_all()

    def cleanup_orphans(self) -> list[str]:
        """Detect and clean up orphaned processes from a previous session."""
        return self._process_manager.cleanup_orphans()

    # ── Private helpers ───────────────────────────────────────────────────────

    def _start_static(self, name: str, project_dir: Path, port: int, cfg: ProjectConfig) -> None:
        """Start Python's built-in http.server for a static site."""
        import sys

        command = [
            sys.executable,
            "-m",
            "http.server",
            str(port),
            "--directory",
            str(project_dir),
            "--bind",
            "0.0.0.0",
        ]
        log_file = self._log_file(name)
        self._process_manager.start(name, command, project_dir, log_file=log_file)

    def _start_app_server(
        self,
        name: str,
        project_dir: Path,
        port: int,
        cfg: ProjectConfig,
        project_type: ProjectType,
    ) -> None:
        """Start an application server process."""
        import sys

        env = {"PORT": str(port), "HOST": "0.0.0.0"}

        if cfg.server.start_command:
            import shlex

            command = shlex.split(cfg.server.start_command)
        elif project_type == ProjectType.FLASK:
            command = [sys.executable, "-m", "flask", "run", "--host=0.0.0.0", f"--port={port}"]
            env["FLASK_APP"] = "app.py"
            env["FLASK_ENV"] = "production"
        elif project_type == ProjectType.FASTAPI:
            command = [sys.executable, "-m", "uvicorn", "main:app", "--host", "0.0.0.0", f"--port={port}"]
        elif project_type == ProjectType.DJANGO:
            command = [sys.executable, "manage.py", "runserver", f"0.0.0.0:{port}"]
        elif project_type in (ProjectType.NEXTJS, ProjectType.REACT, ProjectType.NODE):
            command = ["npm", "start"]
            env["PORT"] = str(port)
        else:
            raise ValueError(f"Cannot determine start command for project type: {project_type}")

        log_file = self._log_file(name)
        self._process_manager.start(name, command, project_dir, env=env, log_file=log_file)

    def _start_quick_tunnel(self, name: str, port: int, cfg: ProjectConfig) -> str:
        """Start a Cloudflare quick tunnel. Returns the public URL."""
        from homehost.core.config import load_global_config
        from homehost.network.tunnel import TunnelManager

        global_cfg = load_global_config()
        cloudflared_path = global_cfg.server.cloudflared_path or "cloudflared"
        tm = TunnelManager(cloudflared_path, self._process_manager)
        info = tm.start_quick_tunnel(name, port)
        return info.url

    def _start_named_tunnel(self, name: str, port: int, cfg: ProjectConfig) -> str:
        """Start a named Cloudflare Tunnel. Returns the stable public URL."""
        from pathlib import Path as _Path

        from homehost.core.config import load_global_config
        from homehost.network.named_tunnel import NamedTunnelManager

        global_cfg = load_global_config()
        cloudflared_path = global_cfg.server.cloudflared_path or "cloudflared"
        manager = NamedTunnelManager(cloudflared_path, _Path.home() / ".homehost")
        info = manager.start(
            project_name=name,
            tunnel_id=cfg.network.tunnel_id,
            credentials_file=_Path(cfg.network.tunnel_credentials_file),
            hostname=cfg.network.tunnel_hostname,
            local_port=port,
            process_manager=self._process_manager,
        )
        return info.public_url

    def _log_file(self, name: str) -> Path:
        log_dir = Path.home() / ".homehost" / "projects" / name / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        return log_dir / "server.log"

    def _is_port_taken(self, port: int) -> bool:
        from homehost.utils.network import is_port_in_use

        return is_port_in_use(port)
