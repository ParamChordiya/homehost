"""FastAPI REST API and WebSocket endpoints for the HomeHost dashboard."""

from __future__ import annotations

import asyncio
import platform
import subprocess
import time
from pathlib import Path
from typing import Any

import aiosqlite
import psutil
import structlog
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from homehost import __version__
from homehost.core.config import (
    GlobalConfig,
    load_global_config,
    load_project_config,
    list_projects,
    save_global_config,
    save_project_config,
)
from homehost.core.process import ProcessManager, ProcessState

log = structlog.get_logger(__name__)

# ── Paths ──────────────────────────────────────────────────────────────────────

_HOMEHOST_DIR = Path.home() / ".homehost"
_DB_PATH = _HOMEHOST_DIR / "dashboard" / "metrics.db"
_RUN_DIR = _HOMEHOST_DIR / "run"
_STATIC_DIR = Path(__file__).parent / "static"

# ── Global process manager (shared with the rest of the app if imported early) ─

_process_manager: ProcessManager | None = None


def get_process_manager() -> ProcessManager:
    global _process_manager
    if _process_manager is None:
        _process_manager = ProcessManager(_RUN_DIR)
    return _process_manager


# ── Pydantic models ────────────────────────────────────────────────────────────


class ProjectStatus(BaseModel):
    name: str
    type: str
    status: str  # "running" | "stopped" | "error"
    port: int
    public_url: str
    local_url: str
    uptime_seconds: int
    request_count_today: int
    request_count_total: int
    error_count_today: int
    auto_start: bool


class ProjectAction(BaseModel):
    action: str  # "start" | "stop" | "restart"


class ActionResponse(BaseModel):
    success: bool
    message: str


class LogsResponse(BaseModel):
    lines: list[str]


class MetricsResponse(BaseModel):
    requests_per_hour: list[int]
    response_times: list[float]


class SystemInfo(BaseModel):
    os: str
    caddy_version: str
    uptime: int
    version: str


class HealthResponse(BaseModel):
    status: str


# ── FastAPI app ────────────────────────────────────────────────────────────────

app = FastAPI(title="HomeHost Dashboard", version="0.1.0")


# ── DB helpers ─────────────────────────────────────────────────────────────────

async def _ensure_db() -> None:
    """Create metrics DB and table if they don't exist."""
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(_DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_name TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                status_code INTEGER,
                response_time_ms INTEGER,
                path TEXT
            )
            """
        )
        await db.commit()


async def _count_requests(project_name: str, since: int | None = None) -> int:
    async with aiosqlite.connect(_DB_PATH) as db:
        if since is not None:
            cursor = await db.execute(
                "SELECT COUNT(*) FROM requests WHERE project_name = ? AND timestamp >= ?",
                (project_name, since),
            )
        else:
            cursor = await db.execute(
                "SELECT COUNT(*) FROM requests WHERE project_name = ?",
                (project_name,),
            )
        row = await cursor.fetchone()
        return int(row[0]) if row else 0


async def _count_errors(project_name: str, since: int | None = None) -> int:
    async with aiosqlite.connect(_DB_PATH) as db:
        if since is not None:
            cursor = await db.execute(
                "SELECT COUNT(*) FROM requests WHERE project_name = ? AND timestamp >= ? AND status_code >= 500",
                (project_name, since),
            )
        else:
            cursor = await db.execute(
                "SELECT COUNT(*) FROM requests WHERE project_name = ? AND status_code >= 500",
                (project_name,),
            )
        row = await cursor.fetchone()
        return int(row[0]) if row else 0


# ── Project status helper ──────────────────────────────────────────────────────

def _day_start_ts() -> int:
    """Unix timestamp for midnight today (UTC)."""
    now = int(time.time())
    return now - (now % 86400)


async def _build_project_status(name: str) -> ProjectStatus:
    cfg = load_project_config(name)
    pm = get_process_manager()
    state = pm.status(name)

    if state == ProcessState.RUNNING:
        status_str = "running"
        # Estimate uptime from PID file start_time
        mp = pm.get_process(name)
        uptime = int(time.time() - mp.start_time) if mp else 0
    elif state == ProcessState.ERROR:
        status_str = "error"
        uptime = 0
    else:
        status_str = "stopped"
        uptime = 0

    day_start = _day_start_ts()
    req_today = await _count_requests(name, since=day_start)
    req_total = await _count_requests(name)
    err_today = await _count_errors(name, since=day_start)

    local_url = f"http://localhost:{cfg.server.port}"
    public_url = ""
    if cfg.network.custom_domain:
        public_url = f"https://{cfg.network.custom_domain}"
    elif cfg.network.subdomain:
        public_url = f"https://{cfg.network.subdomain}.homehost.app"

    return ProjectStatus(
        name=name,
        type=cfg.type,
        status=status_str,
        port=cfg.server.port,
        public_url=public_url,
        local_url=local_url,
        uptime_seconds=uptime,
        request_count_today=req_today,
        request_count_total=req_total,
        error_count_today=err_today,
        auto_start=cfg.server.auto_start,
    )


# ── WebSocket connection manager ───────────────────────────────────────────────

class _ConnectionManager:
    def __init__(self) -> None:
        self._clients: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._clients.append(ws)
        log.debug("ws client connected", total=len(self._clients))

    def disconnect(self, ws: WebSocket) -> None:
        self._clients.discard_if_present(ws)
        try:
            self._clients.remove(ws)
        except ValueError:
            pass
        log.debug("ws client disconnected", total=len(self._clients))

    async def broadcast(self, payload: Any) -> None:
        dead: list[WebSocket] = []
        for ws in list(self._clients):
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            try:
                self._clients.remove(ws)
            except ValueError:
                pass


_manager = _ConnectionManager()


# ── Background broadcast task ──────────────────────────────────────────────────

async def _broadcast_loop() -> None:
    await _ensure_db()
    while True:
        try:
            if _manager._clients:
                names = list_projects()
                statuses = []
                for name in names:
                    try:
                        s = await _build_project_status(name)
                        statuses.append(s.model_dump())
                    except Exception as exc:
                        log.warning("error building project status", name=name, error=str(exc))
                await _manager.broadcast({"type": "projects_update", "projects": statuses})
        except Exception as exc:
            log.warning("broadcast loop error", error=str(exc))
        await asyncio.sleep(2)


@app.on_event("startup")
async def _startup() -> None:
    await _ensure_db()
    asyncio.create_task(_broadcast_loop())


# ── REST endpoints ─────────────────────────────────────────────────────────────

@app.get("/api/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok")


@app.get("/api/projects", response_model=list[ProjectStatus])
async def list_project_statuses() -> list[ProjectStatus]:
    names = list_projects()
    results = []
    for name in names:
        try:
            results.append(await _build_project_status(name))
        except Exception as exc:
            log.warning("failed to build status", name=name, error=str(exc))
    return results


@app.get("/api/projects/{name}", response_model=ProjectStatus)
async def get_project_status(name: str) -> ProjectStatus:
    names = list_projects()
    if name not in names:
        raise HTTPException(status_code=404, detail=f"Project '{name}' not found")
    return await _build_project_status(name)


@app.post("/api/projects/{name}/action", response_model=ActionResponse)
async def project_action(name: str, body: ProjectAction) -> ActionResponse:
    names = list_projects()
    if name not in names:
        raise HTTPException(status_code=404, detail=f"Project '{name}' not found")

    pm = get_process_manager()
    cfg = load_project_config(name)
    action = body.action.lower()

    try:
        if action == "stop":
            stopped = pm.stop(name)
            if stopped:
                return ActionResponse(success=True, message=f"Project '{name}' stopped.")
            return ActionResponse(success=False, message=f"Project '{name}' was not running.")

        elif action == "start":
            if pm.is_running(name):
                return ActionResponse(success=False, message=f"Project '{name}' is already running.")
            cmd_str = cfg.server.start_command
            if not cmd_str:
                return ActionResponse(success=False, message=f"No start command configured for '{name}'.")
            import shlex
            command = shlex.split(cmd_str)
            project_path = Path(cfg.path) if cfg.path else Path.cwd()
            pm.start(name, command, cwd=project_path)
            return ActionResponse(success=True, message=f"Project '{name}' started.")

        elif action == "restart":
            if pm.is_running(name):
                result = pm.restart(name)
                if result:
                    return ActionResponse(success=True, message=f"Project '{name}' restarted.")
                return ActionResponse(success=False, message=f"Failed to restart '{name}'.")
            else:
                cmd_str = cfg.server.start_command
                if not cmd_str:
                    return ActionResponse(success=False, message=f"No start command configured for '{name}'.")
                import shlex
                command = shlex.split(cmd_str)
                project_path = Path(cfg.path) if cfg.path else Path.cwd()
                pm.start(name, command, cwd=project_path)
                return ActionResponse(success=True, message=f"Project '{name}' started.")

        else:
            raise HTTPException(status_code=400, detail=f"Unknown action: '{action}'. Use start/stop/restart.")

    except RuntimeError as exc:
        return ActionResponse(success=False, message=str(exc))


@app.get("/api/projects/{name}/logs", response_model=LogsResponse)
async def get_project_logs(name: str, lines: int = 100) -> LogsResponse:
    names = list_projects()
    if name not in names:
        raise HTTPException(status_code=404, detail=f"Project '{name}' not found")

    log_path = _RUN_DIR / f"{name}.log"
    if not log_path.exists():
        return LogsResponse(lines=[f"No log file found for '{name}'."])

    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
        all_lines = text.splitlines()
        return LogsResponse(lines=all_lines[-lines:])
    except OSError as exc:
        return LogsResponse(lines=[f"Error reading log: {exc}"])


@app.get("/api/projects/{name}/metrics", response_model=MetricsResponse)
async def get_project_metrics(name: str) -> MetricsResponse:
    names = list_projects()
    if name not in names:
        raise HTTPException(status_code=404, detail=f"Project '{name}' not found")

    now = int(time.time())
    # Last 24 hours, bucketed by hour
    hours_start = now - 86400
    requests_per_hour = []
    async with aiosqlite.connect(_DB_PATH) as db:
        for i in range(24):
            bucket_start = hours_start + i * 3600
            bucket_end = bucket_start + 3600
            cursor = await db.execute(
                "SELECT COUNT(*) FROM requests WHERE project_name = ? AND timestamp >= ? AND timestamp < ?",
                (name, bucket_start, bucket_end),
            )
            row = await cursor.fetchone()
            requests_per_hour.append(int(row[0]) if row else 0)

        # Last 100 response times
        cursor = await db.execute(
            "SELECT response_time_ms FROM requests WHERE project_name = ? AND response_time_ms IS NOT NULL ORDER BY timestamp DESC LIMIT 100",
            (name,),
        )
        rows = await cursor.fetchall()
        response_times = [float(r[0]) for r in rows]

    return MetricsResponse(
        requests_per_hour=requests_per_hour,
        response_times=response_times,
    )


@app.get("/api/system", response_model=SystemInfo)
async def get_system_info() -> SystemInfo:
    os_str = f"{platform.system()} {platform.release()}"
    caddy_version = ""
    try:
        result = subprocess.run(
            ["caddy", "version"], capture_output=True, text=True, timeout=3
        )
        caddy_version = result.stdout.strip().split()[0] if result.returncode == 0 else "not installed"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        caddy_version = "not installed"

    boot_time = psutil.boot_time()
    uptime = int(time.time() - boot_time)

    return SystemInfo(
        os=os_str,
        caddy_version=caddy_version,
        uptime=uptime,
        version=__version__,
    )


# ── WebSocket endpoint ─────────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await _manager.connect(ws)
    try:
        # Send an immediate snapshot on connect
        names = list_projects()
        statuses = []
        for name in names:
            try:
                s = await _build_project_status(name)
                statuses.append(s.model_dump())
            except Exception:
                pass
        await ws.send_json({"type": "projects_update", "projects": statuses})

        # Keep connection alive — reads are just for detecting disconnects
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        log.debug("ws connection closed", reason=str(exc))
    finally:
        _manager.disconnect(ws)


# ── Static file serving ────────────────────────────────────────────────────────

if _STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(_STATIC_DIR), html=True), name="static")
else:
    @app.get("/", response_class=HTMLResponse)
    async def root() -> HTMLResponse:
        return HTMLResponse("<h1>HomeHost Dashboard — static files not found</h1>")
