"""ServerCard widget — per-project status card displayed in the status screen."""

from __future__ import annotations

import time
import webbrowser

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Button, Label, Static


_TYPE_BADGES = {
    "static":  ("[#94a3b8]HTML[/]",    "#94a3b8"),
    "flask":   ("[#4c9be8]Flask[/]",   "#4c9be8"),
    "fastapi": ("[#4ade80]FastAPI[/]", "#4ade80"),
    "django":  ("[#4ade80]Django[/]",  "#4ade80"),
    "nextjs":  ("[#fbbf24]Next.js[/]", "#fbbf24"),
    "react":   ("[#4c9be8]React[/]",   "#4c9be8"),
    "node":    ("[#4ade80]Node[/]",    "#4ade80"),
    "docker":  ("[#4c9be8]Docker[/]",  "#4c9be8"),
    "custom":  ("[#94a3b8]Custom[/]",  "#94a3b8"),
}

_STATUS_DOT = {
    "running": ("●", "#4ade80"),
    "stopped": ("○", "#94a3b8"),
    "error":   ("✖", "#f87171"),
    "unknown": ("?", "#fbbf24"),
}


def _format_uptime(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    h = seconds // 3600
    m = (seconds % 3600) // 60
    return f"{h}h {m}m"


class ServerCard(Widget):
    """Displays status for one hosted project."""

    project_name: reactive[str] = reactive("")
    project_type: reactive[str] = reactive("static")
    status: reactive[str] = reactive("stopped")
    local_url: reactive[str] = reactive("")
    public_url: reactive[str] = reactive("")
    port: reactive[int] = reactive(8080)
    request_count: reactive[int] = reactive(0)
    uptime_seconds: reactive[int] = reactive(0)

    DEFAULT_CSS = """
    ServerCard {
        height: auto;
        width: 100%;
        background: #0f3460;
        border: solid #334155;
        padding: 1 2;
        margin: 0 0 1 0;
    }

    ServerCard:hover {
        border: solid #4c9be8;
    }

    ServerCard.-selected {
        border: solid #4c9be8;
        background: #16213e;
    }

    /* Card header row */
    #card-header {
        height: 2;
        width: 100%;
    }

    #card-name {
        color: #f8fafc;
        text-style: bold;
        width: 1fr;
    }

    #card-badge {
        width: auto;
        margin: 0 2 0 0;
    }

    #card-status {
        width: auto;
    }

    /* URL rows */
    #card-urls {
        height: auto;
        width: 100%;
        padding: 1 0 0 0;
    }

    .url-row {
        height: 1;
        width: 100%;
    }

    .url-label {
        color: #94a3b8;
        width: 12;
    }

    .url-value {
        color: #4c9be8;
        width: 1fr;
    }

    /* Stats row */
    #card-stats {
        height: 1;
        width: 100%;
        padding: 1 0 0 0;
    }

    .stat-item {
        color: #94a3b8;
        width: auto;
        margin: 0 3 0 0;
    }

    /* Action buttons */
    #card-actions {
        height: 3;
        width: 100%;
        padding: 1 0 0 0;
    }

    #card-actions Button {
        width: 12;
        height: 3;
        margin: 0 1 0 0;
    }
    """

    def __init__(
        self,
        project_name: str,
        project_type: str = "static",
        status: str = "stopped",
        local_url: str = "",
        public_url: str = "",
        port: int = 8080,
        request_count: int = 0,
        uptime_seconds: int = 0,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.project_name = project_name
        self.project_type = project_type
        self.status = status
        self.local_url = local_url
        self.public_url = public_url
        self.port = port
        self.request_count = request_count
        self.uptime_seconds = uptime_seconds

    def compose(self) -> ComposeResult:
        dot, dot_color = _STATUS_DOT.get(self.status, ("?", "#fbbf24"))
        badge_text, _ = _TYPE_BADGES.get(self.project_type, ("[#94a3b8]Custom[/]", "#94a3b8"))

        with Horizontal(id="card-header"):
            yield Label(self.project_name, id="card-name")
            yield Label(badge_text,        id="card-badge")
            yield Label(
                f"[{dot_color}]{dot}[/] [{dot_color}]{self.status}[/]",
                id="card-status",
            )

        with Vertical(id="card-urls"):
            with Horizontal(classes="url-row"):
                yield Label("🏠 Local:",  classes="url-label")
                yield Label(self.local_url or "—", classes="url-value", id="local-url-lbl")
            if self.public_url:
                with Horizontal(classes="url-row"):
                    yield Label("🌍 Public:", classes="url-label")
                    yield Label(self.public_url,    classes="url-value", id="public-url-lbl")

        with Horizontal(id="card-stats"):
            if self.uptime_seconds > 0:
                yield Label(
                    f"⏱ Uptime: {_format_uptime(self.uptime_seconds)}",
                    classes="stat-item",
                )
            yield Label(
                f"📥 Port: {self.port}",
                classes="stat-item",
            )
            if self.request_count > 0:
                yield Label(
                    f"🔁 Requests: {self.request_count}",
                    classes="stat-item",
                )

        with Horizontal(id="card-actions"):
            if self.status == "running":
                yield Button("■ Stop",    id=f"card-stop-{self.project_name}",    classes="-warning")
                yield Button("↺ Restart", id=f"card-restart-{self.project_name}")
            else:
                yield Button("▶ Start",  id=f"card-start-{self.project_name}",   classes="-success")
            yield Button("📋 Logs",  id=f"card-logs-{self.project_name}")
            yield Button("🌐 Open",  id=f"card-open-{self.project_name}")

    # ── Reactive watchers — rebuild relevant parts ─────────────────────────────

    def watch_status(self, new_status: str) -> None:
        """Called when status reactive changes."""
        try:
            dot, dot_color = _STATUS_DOT.get(new_status, ("?", "#fbbf24"))
            lbl = self.query_one("#card-status", Label)
            lbl.update(f"[{dot_color}]{dot}[/] [{dot_color}]{new_status}[/]")
        except Exception:
            pass

    def watch_local_url(self, new_url: str) -> None:
        try:
            lbl = self.query_one("#local-url-lbl", Label)
            lbl.update(new_url or "—")
        except Exception:
            pass

    def render_status_dot(self) -> str:
        dot, color = _STATUS_DOT.get(self.status, ("?", "#fbbf24"))
        return f"[{color}]{dot}[/]"

    # ── Button events ─────────────────────────────────────────────────────────

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id or ""
        name = self.project_name

        if btn_id == f"card-start-{name}":
            event.stop()
            self._action_start()
        elif btn_id == f"card-stop-{name}":
            event.stop()
            self._action_stop()
        elif btn_id == f"card-restart-{name}":
            event.stop()
            self._action_restart()
        elif btn_id == f"card-logs-{name}":
            event.stop()
            self._action_logs()
        elif btn_id == f"card-open-{name}":
            event.stop()
            self._action_open()

    def _action_start(self) -> None:
        try:
            from homehost.core.config import homehost_dir, load_project_config
            from homehost.core.process import ProcessManager
            from pathlib import Path
            cfg = load_project_config(self.project_name)
            run_dir = homehost_dir() / "run"
            pm = ProcessManager(run_dir)
            cmd = cfg.server.start_command.split() if cfg.server.start_command else [
                "python", "-m", "http.server", str(cfg.server.port)
            ]
            pm.start(self.project_name, cmd, Path(cfg.path))
            self.status = "running"
            self.app.notify(f"Started: {self.project_name}")
        except Exception as exc:
            self.app.notify(f"Start failed: {exc}", severity="error")

    def _action_stop(self) -> None:
        try:
            from homehost.core.config import homehost_dir
            from homehost.core.process import ProcessManager
            run_dir = homehost_dir() / "run"
            pm = ProcessManager(run_dir)
            pm.stop(self.project_name)
            self.status = "stopped"
            self.app.notify(f"Stopped: {self.project_name}")
        except Exception as exc:
            self.app.notify(f"Stop failed: {exc}", severity="error")

    def _action_restart(self) -> None:
        try:
            from homehost.core.config import homehost_dir
            from homehost.core.process import ProcessManager
            run_dir = homehost_dir() / "run"
            pm = ProcessManager(run_dir)
            pm.restart(self.project_name)
            self.app.notify(f"Restarted: {self.project_name}")
        except Exception as exc:
            self.app.notify(f"Restart failed: {exc}", severity="error")

    def _action_logs(self) -> None:
        try:
            from homehost.tui.screens.manage import LogScreen
            self.app.push_screen(LogScreen(project_name=self.project_name))
        except Exception as exc:
            self.app.notify(f"Cannot open logs: {exc}", severity="error")

    def _action_open(self) -> None:
        url = self.public_url or self.local_url
        if url:
            webbrowser.open(url)
            self.app.notify(f"Opening {url}")
        else:
            self.app.notify("No URL available.", severity="warning")
