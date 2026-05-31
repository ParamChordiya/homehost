"""Project management screen — list, start, stop, delete projects."""

from __future__ import annotations

import contextlib
import webbrowser
from pathlib import Path
from typing import TYPE_CHECKING

from textual import work
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Label,
    RichLog,
)

if TYPE_CHECKING:
    from textual.app import ComposeResult

_STATUS_STYLE = {
    "running": ("[#4ade80]● running[/]", "#4ade80"),
    "stopped": ("[#94a3b8]○ stopped[/]", "#94a3b8"),
    "error": ("[#f87171]✖ error[/]", "#f87171"),
    "unknown": ("[#fbbf24]? unknown[/]", "#fbbf24"),
}


class ManageScreen(Screen):
    """Full project management table with per-row actions."""

    BINDINGS = [
        Binding("r", "refresh", "Refresh"),
        Binding("s", "start_selected", "Start"),
        Binding("p", "stop_selected", "Stop"),
        Binding("x", "restart_selected", "Restart"),
        Binding("l", "logs_selected", "Logs"),
        Binding("d", "delete_selected", "Delete"),
        Binding("o", "open_selected", "Open URL"),
        Binding("escape", "go_back", "Back"),
        Binding("q", "app.quit", "Quit"),
    ]

    DEFAULT_CSS = """
    ManageScreen {
        background: #1a1a2e;
    }

    #manage-header {
        width: 100%;
        height: 3;
        background: #16213e;
        border-bottom: solid #334155;
        align: left middle;
        padding: 0 2;
    }

    #manage-title {
        color: #4c9be8;
        text-style: bold;
    }

    #manage-count {
        color: #94a3b8;
        margin: 0 0 0 4;
    }

    #project-table {
        height: 1fr;
        margin: 1 2;
        border: solid #334155;
    }

    #action-bar {
        height: 5;
        background: #16213e;
        border-top: solid #334155;
        align: center middle;
        padding: 0 2;
    }

    #action-bar Button {
        width: 14;
        height: 3;
        margin: 0 1;
    }

    #empty-label {
        width: 100%;
        text-align: center;
        color: #94a3b8;
        padding: 4 0;
    }
    """

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="manage-header"):
            yield Label("📂  Manage Projects", id="manage-title")
            yield Label("", id="manage-count")
        table: DataTable = DataTable(id="project-table", zebra_stripes=True, cursor_type="row")
        table.add_columns("Name", "Type", "Status", "Port", "Local URL", "Public URL")
        yield table
        with Horizontal(id="action-bar"):
            yield Button("▶ Start", id="btn-start", classes="-success")
            yield Button("■ Stop", id="btn-stop", classes="-warning")
            yield Button("↺ Restart", id="btn-restart")
            yield Button("📋 Logs", id="btn-logs")
            yield Button("🌐 Open", id="btn-open")
            yield Button("🗑 Delete", id="btn-delete", classes="-error")
            yield Button("← Back", id="btn-back")
        yield Footer()

    def on_mount(self) -> None:
        self.load_projects()

    @work(thread=True)
    def load_projects(self) -> None:
        """Load all projects and populate the table."""
        try:
            from homehost.core.config import list_projects, load_project_config

            names = list_projects()
        except Exception:
            names = []

        rows: list[tuple] = []
        for name in names:
            try:
                cfg = load_project_config(name)
            except Exception:
                continue
            status = self._get_status(name)
            status_text, _ = _STATUS_STYLE.get(status, ("? unknown", "#fbbf24"))
            local_url = f"http://localhost:{cfg.server.port}"
            public_url = ""
            if cfg.network.access == "public":
                if cfg.network.subdomain:
                    public_url = f"https://{cfg.network.subdomain}.trycloudflare.com"
                elif cfg.network.custom_domain:
                    public_url = f"https://{cfg.network.custom_domain}"
                else:
                    public_url = "(tunnel not active)"
            rows.append((name, cfg.type, status_text, str(cfg.server.port), local_url, public_url or "—"))

        def _populate() -> None:
            table = self.query_one("#project-table", DataTable)
            table.clear()
            for row in rows:
                table.add_row(*row, key=row[0])
            count_lbl = self.query_one("#manage-count", Label)
            count_lbl.update(f"  {len(rows)} project(s)")

        self.app.call_from_thread(_populate)

    def _get_status(self, name: str) -> str:
        try:
            from homehost.core.config import homehost_dir
            from homehost.core.process import ProcessManager

            run_dir = homehost_dir() / "run"
            pm = ProcessManager(run_dir)
            return pm.status(name).value
        except Exception:
            return "unknown"

    def _selected_name(self) -> str | None:
        table = self.query_one("#project-table", DataTable)
        if table.cursor_row < 0:
            return None
        try:
            row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
            return str(row_key.value)
        except Exception:
            return None

    # ── Button events ─────────────────────────────────────────────────────────

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id == "btn-start":
            self.action_start_selected()
        elif btn_id == "btn-stop":
            self.action_stop_selected()
        elif btn_id == "btn-restart":
            self.action_restart_selected()
        elif btn_id == "btn-logs":
            self.action_logs_selected()
        elif btn_id == "btn-open":
            self.action_open_selected()
        elif btn_id == "btn-delete":
            self.action_delete_selected()
        elif btn_id == "btn-back":
            self.action_go_back()

    # ── Actions ───────────────────────────────────────────────────────────────

    def action_refresh(self) -> None:
        self.load_projects()

    def action_start_selected(self) -> None:
        name = self._selected_name()
        if not name:
            self.app.notify("No project selected.", severity="warning")
            return
        self._start_project(name)

    def action_stop_selected(self) -> None:
        name = self._selected_name()
        if not name:
            self.app.notify("No project selected.", severity="warning")
            return
        self._stop_project(name)

    def action_restart_selected(self) -> None:
        name = self._selected_name()
        if not name:
            self.app.notify("No project selected.", severity="warning")
            return
        self._restart_project(name)

    def action_logs_selected(self) -> None:
        name = self._selected_name()
        if not name:
            self.app.notify("No project selected.", severity="warning")
            return
        self.app.push_screen(LogScreen(project_name=name))

    def action_delete_selected(self) -> None:
        name = self._selected_name()
        if not name:
            self.app.notify("No project selected.", severity="warning")
            return
        self.app.push_screen(ConfirmDeleteScreen(project_name=name, manage_screen=self))

    def action_open_selected(self) -> None:
        name = self._selected_name()
        if not name:
            self.app.notify("No project selected.", severity="warning")
            return
        try:
            from homehost.core.config import load_project_config

            cfg = load_project_config(name)
            url = f"http://localhost:{cfg.server.port}"
            webbrowser.open(url)
            self.app.notify(f"Opening {url}")
        except Exception as exc:
            self.app.notify(f"Cannot open URL: {exc}", severity="error")

    def action_go_back(self) -> None:
        self.app.pop_screen()

    # ── Workers ───────────────────────────────────────────────────────────────

    @work(thread=True)
    def _start_project(self, name: str) -> None:
        try:
            from homehost.core.config import homehost_dir, load_project_config
            from homehost.core.process import ProcessManager

            cfg = load_project_config(name)
            run_dir = homehost_dir() / "run"
            pm = ProcessManager(run_dir)
            cmd = (
                cfg.server.start_command.split()
                if cfg.server.start_command
                else ["python", "-m", "http.server", str(cfg.server.port)]
            )
            pm.start(name, cmd, Path(cfg.path))
            self.app.call_from_thread(self.app.notify, f"Started: {name}")
        except Exception as exc:
            self.app.call_from_thread(self.app.notify, f"Start failed: {exc}", severity="error")
        self.app.call_from_thread(self.load_projects)

    @work(thread=True)
    def _stop_project(self, name: str) -> None:
        try:
            from homehost.core.config import homehost_dir
            from homehost.core.process import ProcessManager

            run_dir = homehost_dir() / "run"
            pm = ProcessManager(run_dir)
            pm.stop(name)
            self.app.call_from_thread(self.app.notify, f"Stopped: {name}")
        except Exception as exc:
            self.app.call_from_thread(self.app.notify, f"Stop failed: {exc}", severity="error")
        self.app.call_from_thread(self.load_projects)

    @work(thread=True)
    def _restart_project(self, name: str) -> None:
        try:
            from homehost.core.config import homehost_dir
            from homehost.core.process import ProcessManager

            run_dir = homehost_dir() / "run"
            pm = ProcessManager(run_dir)
            pm.restart(name)
            self.app.call_from_thread(self.app.notify, f"Restarted: {name}")
        except Exception as exc:
            self.app.call_from_thread(self.app.notify, f"Restart failed: {exc}", severity="error")
        self.app.call_from_thread(self.load_projects)


# ── Confirm delete modal ──────────────────────────────────────────────────────


class ConfirmDeleteScreen(Screen):
    """Confirmation modal before deleting a project."""

    DEFAULT_CSS = """
    ConfirmDeleteScreen {
        align: center middle;
        background: rgba(0, 0, 0, 0.7);
    }

    #confirm-box {
        width: 60;
        height: auto;
        background: #16213e;
        border: solid #f87171;
        padding: 2 4;
        align: center middle;
    }

    #confirm-title {
        color: #f87171;
        text-style: bold;
        text-align: center;
        width: 100%;
        padding: 0 0 1 0;
    }

    #confirm-msg {
        color: #f8fafc;
        text-align: center;
        width: 100%;
        padding: 0 0 2 0;
    }

    #confirm-warning {
        color: #fbbf24;
        text-align: center;
        width: 100%;
        padding: 0 0 2 0;
    }

    #confirm-buttons {
        width: 100%;
        align: center middle;
    }

    #confirm-buttons Button {
        width: 16;
        margin: 0 2;
    }
    """

    def __init__(self, project_name: str, manage_screen: ManageScreen, **kwargs) -> None:
        super().__init__(**kwargs)
        self._project_name = project_name
        self._manage = manage_screen

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-box"):
            yield Label("⚠️  Delete Project", id="confirm-title")
            yield Label(
                f'Are you sure you want to delete "{self._project_name}"?',
                id="confirm-msg",
            )
            yield Label(
                "This will remove the HomeHost configuration.\n" "Your project files will NOT be deleted.",
                id="confirm-warning",
            )
            with Horizontal(id="confirm-buttons"):
                yield Button("🗑  Delete", id="btn-confirm-delete", classes="-error")
                yield Button("Cancel", id="btn-confirm-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-confirm-delete":
            self._do_delete()
        else:
            self.app.pop_screen()

    @work(thread=True)
    def _do_delete(self) -> None:
        name = self._project_name
        try:
            # Stop first
            from homehost.core.config import delete_project_config, homehost_dir
            from homehost.core.process import ProcessManager

            run_dir = homehost_dir() / "run"
            pm = ProcessManager(run_dir)
            pm.stop(name)
            delete_project_config(name)
            self.app.call_from_thread(self.app.notify, f"Deleted: {name}", severity="information")
        except Exception as exc:
            self.app.call_from_thread(self.app.notify, f"Delete failed: {exc}", severity="error")

        def _done() -> None:
            self.app.pop_screen()  # close confirm dialog
            self._manage.load_projects()

        self.app.call_from_thread(_done)


# ── Log viewer screen ─────────────────────────────────────────────────────────


class LogScreen(Screen):
    """Full-screen log viewer for a single project."""

    BINDINGS = [
        Binding("c", "clear_logs", "Clear"),
        Binding("escape", "go_back", "Back"),
        Binding("q", "go_back", "Back"),
    ]

    DEFAULT_CSS = """
    LogScreen {
        background: #1a1a2e;
    }

    #log-header {
        width: 100%;
        height: 3;
        background: #16213e;
        border-bottom: solid #334155;
        align: left middle;
        padding: 0 2;
    }

    #log-title {
        color: #4c9be8;
        text-style: bold;
    }

    #log-view {
        height: 1fr;
        margin: 1 2;
        border: solid #334155;
    }

    #log-footer-bar {
        height: 3;
        background: #16213e;
        border-top: solid #334155;
        align: left middle;
        padding: 0 2;
    }

    #log-hint {
        color: #94a3b8;
    }
    """

    def __init__(self, project_name: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self._project_name = project_name

    def compose(self) -> ComposeResult:
        with Horizontal(id="log-header"):
            yield Label(f"📋  Logs: {self._project_name}", id="log-title")
        yield RichLog(
            id="log-view",
            wrap=True,
            highlight=True,
            markup=True,
            auto_scroll=True,
        )
        with Horizontal(id="log-footer-bar"):
            yield Label("C to clear  •  ESC/Q to go back", id="log-hint")

    def on_mount(self) -> None:
        self._load_logs()
        self.set_interval(2.0, self._load_logs_tail)

    @work(thread=True)
    def _load_logs(self) -> None:
        """Load the full log file for the project."""
        try:
            from homehost.core.config import homehost_dir

            log_path = homehost_dir() / "run" / f"{self._project_name}.log"
            if not log_path.exists():
                self.app.call_from_thread(
                    self.query_one("#log-view", RichLog).write,
                    "[#94a3b8]No log file found yet. Start the project to generate logs.[/]",
                )
                return
            lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
            # Load last 200 lines
            lines = lines[-200:]

            def _populate() -> None:
                log_widget = self.query_one("#log-view", RichLog)
                log_widget.clear()
                for line in lines:
                    log_widget.write(self._colorize_line(line))

            self.app.call_from_thread(_populate)
        except Exception as exc:
            self.app.call_from_thread(
                self.query_one("#log-view", RichLog).write,
                f"[#f87171]Error loading logs: {exc}[/]",
            )

    @work(thread=True)
    def _load_logs_tail(self) -> None:
        """Append newly written lines since last read."""
        try:
            from homehost.core.config import homehost_dir

            log_path = homehost_dir() / "run" / f"{self._project_name}.log"
            if not log_path.exists():
                return
            # Read the very last line as a quick refresh
            lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
            if not lines:
                return
            last = lines[-1]

            def _append() -> None:
                try:
                    log_widget = self.query_one("#log-view", RichLog)
                    log_widget.write(self._colorize_line(last))
                except Exception:
                    pass

            self.app.call_from_thread(_append)
        except Exception:
            pass

    @staticmethod
    def _colorize_line(line: str) -> str:
        lower = line.lower()
        if "error" in lower or "exception" in lower or "critical" in lower:
            return f"[#f87171]{line}[/]"
        if "warning" in lower or "warn" in lower:
            return f"[#fbbf24]{line}[/]"
        if "debug" in lower:
            return f"[#94a3b8]{line}[/]"
        return line

    def action_clear_logs(self) -> None:
        with contextlib.suppress(Exception):
            self.query_one("#log-view", RichLog).clear()

    def action_go_back(self) -> None:
        self.app.pop_screen()
