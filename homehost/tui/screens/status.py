"""Live status dashboard — shows all running projects as cards."""

from __future__ import annotations

import webbrowser
from pathlib import Path
from typing import TYPE_CHECKING

from textual import work
from textual.binding import Binding
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Label

if TYPE_CHECKING:
    from textual.app import ComposeResult


class StatusScreen(Screen):
    """Persistent live status view — updates every 3 seconds."""

    BINDINGS = [
        Binding("s", "start_project", "Start"),
        Binding("p", "stop_project", "Stop"),
        Binding("r", "restart_project", "Restart"),
        Binding("l", "view_logs", "Logs"),
        Binding("d", "open_dashboard", "Dashboard"),
        Binding("n", "new_project", "New Project"),
        Binding("escape", "go_back", "Back"),
        Binding("q", "app.quit", "Quit"),
    ]

    DEFAULT_CSS = """
    StatusScreen {
        background: #1a1a2e;
    }

    #status-header {
        width: 100%;
        height: 3;
        background: #16213e;
        border-bottom: solid #334155;
        align: left middle;
        padding: 0 2;
    }

    #header-title {
        color: #4c9be8;
        text-style: bold;
    }

    #header-stats {
        color: #94a3b8;
        margin: 0 0 0 4;
    }

    #cards-container {
        width: 100%;
        height: 1fr;
        padding: 1 2;
        overflow-y: auto;
    }

    #empty-state {
        width: 100%;
        height: 100%;
        align: center middle;
        padding: 4;
    }

    #empty-title {
        color: #94a3b8;
        text-align: center;
        width: 100%;
        text-style: bold;
    }

    #empty-hint {
        color: #334155;
        text-align: center;
        width: 100%;
        padding: 1 0;
    }
    """

    _selected_project: str = ""

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="status-header"):
            yield Label("📊  Live Status", id="header-title")
            yield Label("Loading…", id="header-stats")
        with ScrollableContainer(id="cards-container"):
            yield Label("Loading projects…", id="loading-placeholder")
        yield Footer()

    def on_mount(self) -> None:
        self.set_interval(3.0, self.refresh_status)
        self.call_after_refresh(self.refresh_status)

    async def refresh_status(self) -> None:
        """Reload project configs and rebuild cards."""
        try:
            from homehost.core.config import list_projects, load_project_config

            names = list_projects()
        except Exception:
            names = []

        container = self.query_one("#cards-container", ScrollableContainer)
        container.remove_children()

        if not names:
            self._render_empty_state(container)
            self._update_header_stats(0, 0)
            return

        from homehost.tui.widgets.server_card import ServerCard

        running_count = 0
        for name in names:
            try:
                cfg = load_project_config(name)
            except Exception:
                continue

            status = self._get_process_status(name)
            if status == "running":
                running_count += 1

            local_url = f"http://localhost:{cfg.server.port}"
            public_url = ""
            if cfg.network.access == "public":
                if cfg.network.subdomain:
                    public_url = f"https://{cfg.network.subdomain}.trycloudflare.com"
                elif cfg.network.custom_domain:
                    public_url = f"https://{cfg.network.custom_domain}"
                else:
                    public_url = f"https://{name}.trycloudflare.com"

            card = ServerCard(
                project_name=name,
                project_type=cfg.type,
                status=status,
                local_url=local_url,
                public_url=public_url,
                port=cfg.server.port,
            )
            container.mount(card)

        self._update_header_stats(len(names), running_count)

    def _render_empty_state(self, container: ScrollableContainer) -> None:
        with Vertical(id="empty-state") as v:
            container.mount(v)
            v.mount(Label("No projects yet.", id="empty-title"))
            v.mount(
                Label(
                    "Press N to set up a new project, or run `homehost new` from the terminal.",
                    id="empty-hint",
                )
            )

    def _update_header_stats(self, total: int, running: int) -> None:
        try:
            lbl = self.query_one("#header-stats", Label)
            stopped = total - running
            lbl.update(
                f"  {total} project(s)  •  " f"[#4ade80]{running} running[/]  •  " f"[#94a3b8]{stopped} stopped[/]"
            )
        except Exception:
            pass

    def _get_process_status(self, name: str) -> str:
        try:
            from homehost.core.config import homehost_dir
            from homehost.core.process import ProcessManager

            run_dir = homehost_dir() / "run"
            pm = ProcessManager(run_dir)
            state = pm.status(name)
            return state.value  # "running" | "stopped" | "error" | "unknown"
        except Exception:
            return "unknown"

    def _get_selected_name(self) -> str:
        """Return the currently focused/selected project name."""
        if self._selected_project:
            return self._selected_project
        # Fallback: first project card
        try:
            cards = self.query("ServerCard")
            if cards:
                from homehost.tui.widgets.server_card import ServerCard

                first = cards.first(ServerCard)
                return first.project_name
        except Exception:
            pass
        return ""

    # ── Actions ───────────────────────────────────────────────────────────────

    def action_start_project(self) -> None:
        name = self._get_selected_name()
        if not name:
            self.app.notify("No project selected.", severity="warning")
            return
        self._do_start(name)

    def action_stop_project(self) -> None:
        name = self._get_selected_name()
        if not name:
            self.app.notify("No project selected.", severity="warning")
            return
        self._do_stop(name)

    def action_restart_project(self) -> None:
        name = self._get_selected_name()
        if not name:
            self.app.notify("No project selected.", severity="warning")
            return
        self._do_restart(name)

    def action_view_logs(self) -> None:
        name = self._get_selected_name()
        if not name:
            self.app.notify("No project selected.", severity="warning")
            return
        try:
            from homehost.tui.screens.manage import LogScreen

            self.app.push_screen(LogScreen(project_name=name))
        except Exception as exc:
            self.app.notify(f"Cannot open logs: {exc}", severity="error")

    def action_open_dashboard(self) -> None:
        webbrowser.open("http://localhost:9111")
        self.app.notify("Opening dashboard in browser…")

    def action_new_project(self) -> None:
        try:
            from homehost.tui.screens.setup import SetupScreen

            self.app.push_screen(SetupScreen())
        except Exception as exc:
            self.app.notify(f"Cannot open setup: {exc}", severity="error")

    def action_go_back(self) -> None:
        self.app.pop_screen()

    # ── Background process controls ───────────────────────────────────────────

    @work(thread=True)
    def _do_start(self, name: str) -> None:
        try:
            from homehost.core.config import homehost_dir, load_project_config
            from homehost.core.process import ProcessManager

            cfg = load_project_config(name)
            run_dir = homehost_dir() / "run"
            pm = ProcessManager(run_dir)
            project_path = Path(cfg.path)
            cmd = ["python", "-m", "http.server", str(cfg.server.port)]
            if cfg.server.start_command:
                cmd = cfg.server.start_command.split()
            pm.start(name, cmd, project_path)
            self.app.call_from_thread(self.app.notify, f"Started: {name}", severity="information")
        except Exception as exc:
            self.app.call_from_thread(self.app.notify, f"Start failed: {exc}", severity="error")
        self.app.call_from_thread(self.refresh_status)  # type: ignore[arg-type]

    @work(thread=True)
    def _do_stop(self, name: str) -> None:
        try:
            from homehost.core.config import homehost_dir
            from homehost.core.process import ProcessManager

            run_dir = homehost_dir() / "run"
            pm = ProcessManager(run_dir)
            pm.stop(name)
            self.app.call_from_thread(self.app.notify, f"Stopped: {name}", severity="information")
        except Exception as exc:
            self.app.call_from_thread(self.app.notify, f"Stop failed: {exc}", severity="error")
        self.app.call_from_thread(self.refresh_status)  # type: ignore[arg-type]

    @work(thread=True)
    def _do_restart(self, name: str) -> None:
        try:
            from homehost.core.config import homehost_dir
            from homehost.core.process import ProcessManager

            run_dir = homehost_dir() / "run"
            pm = ProcessManager(run_dir)
            pm.restart(name)
            self.app.call_from_thread(self.app.notify, f"Restarted: {name}", severity="information")
        except Exception as exc:
            self.app.call_from_thread(self.app.notify, f"Restart failed: {exc}", severity="error")
        self.app.call_from_thread(self.refresh_status)  # type: ignore[arg-type]
