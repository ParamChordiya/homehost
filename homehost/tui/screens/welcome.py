"""Welcome screen — ASCII logo, system checks, and main menu."""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

from textual import work
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Label, LoadingIndicator, Static

if TYPE_CHECKING:
    from textual.app import ComposeResult

LOGO = r"""
 ██╗  ██╗ ██████╗ ███╗   ███╗███████╗██╗  ██╗ ██████╗ ███████╗████████╗
 ██║  ██║██╔═══██╗████╗ ████║██╔════╝██║  ██║██╔═══██╗██╔════╝╚══██╔══╝
 ███████║██║   ██║██╔████╔██║█████╗  ███████║██║   ██║███████╗   ██║
 ██╔══██║██║   ██║██║╚██╔╝██║██╔══╝  ██╔══██║██║   ██║╚════██║   ██║
 ██║  ██║╚██████╔╝██║ ╚═╝ ██║███████╗██║  ██║╚██████╔╝███████║   ██║
 ╚═╝  ╚═╝ ╚═════╝ ╚═╝     ╚═╝╚══════╝╚═╝  ╚═╝ ╚═════╝ ╚══════╝   ╚═╝
"""

LOGO_COMPACT = r"""
  _  _  ___  __  __ ___ _  _  ___  ___ _____
 | || |/ _ \|  \/  | __| || |/ _ \/ __|_   _|
 | __ | (_) | |\/| | _|| __ | (_) \__ \ | |
 |_||_|\___/|_|  |_|___|_||_|\___/|___/ |_|
"""


_CHECK_LABELS = {
    "python": "Python 3.10+",
    "internet": "Internet",
    "disk": "Disk Space",
    "git": "Git",
    "node": "Node.js",
    "caddy": "Caddy Server",
    "cloudflared": "cloudflared",
}

_STATUS_ICONS = {
    "ok": ("✅", "label-success"),
    "warning": ("⚠️ ", "label-warning"),
    "error": ("❌", "label-error"),
    "missing": ("⚠️ ", "label-warning"),
    "pending": ("⏳", "label-dim"),
}


class CheckRow(Static):
    """One system-check row with an icon and message."""

    DEFAULT_CSS = """
    CheckRow {
        layout: horizontal;
        height: 1;
        margin: 0 0;
    }
    CheckRow .check-icon  { width: 4; }
    CheckRow .check-name  { width: 20; color: #94a3b8; }
    CheckRow .check-msg   { color: #f8fafc; }
    """

    def __init__(self, check_name: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self._check_name = check_name

    def compose(self) -> ComposeResult:
        label = _CHECK_LABELS.get(self._check_name, self._check_name)
        yield Label("⏳", id=f"icon-{self._check_name}", classes="check-icon")
        yield Label(label, classes="check-name")
        yield Label("Checking…", id=f"msg-{self._check_name}", classes="check-msg label-dim")

    def update_result(self, status: str, message: str) -> None:
        icon_str, icon_cls = _STATUS_ICONS.get(status, ("❓", "label-dim"))
        msg_cls = {
            "ok": "label-success",
            "warning": "label-warning",
            "error": "label-error",
            "missing": "label-warning",
        }.get(status, "label-dim")

        icon_widget = self.query_one(f"#icon-{self._check_name}", Label)
        icon_widget.update(icon_str)
        icon_widget.set_classes(f"check-icon {icon_cls}")

        msg_widget = self.query_one(f"#msg-{self._check_name}", Label)
        msg_widget.update(message)
        msg_widget.set_classes(f"check-msg {msg_cls}")


class WelcomeScreen(Screen):
    """The landing screen shown when HomeHost starts."""

    BINDINGS = [
        Binding("1", "menu_new", "New Project"),
        Binding("2", "menu_manage", "Manage"),
        Binding("3", "menu_dashboard", "Dashboard"),
        Binding("4", "menu_settings", "Settings"),
        Binding("5", "menu_uninstall", "Uninstall"),
        Binding("escape", "app.quit", "Quit"),
    ]

    DEFAULT_CSS = """
    WelcomeScreen {
        align: center top;
        overflow-y: auto;
    }

    #logo-container {
        align: center middle;
        width: 100%;
        padding: 1 0 0 0;
    }

    #logo {
        color: #4c9be8;
        text-style: bold;
        text-align: center;
        width: 100%;
    }

    #tagline {
        color: #94a3b8;
        text-align: center;
        width: 100%;
        padding: 0 0 1 0;
        text-style: italic;
    }

    #content-row {
        width: 100%;
        height: auto;
        padding: 0 4;
    }

    #checks-panel {
        width: 1fr;
        background: #16213e;
        border: solid #334155;
        padding: 1 2;
        margin: 0 1 0 0;
        height: auto;
    }

    #menu-panel {
        width: 1fr;
        background: #16213e;
        border: solid #334155;
        padding: 1 2;
        margin: 0 0 0 1;
        height: auto;
    }

    .panel-title {
        color: #4c9be8;
        text-style: bold;
        padding: 0 0 1 0;
    }

    #loading-row {
        height: 1;
        margin: 1 0 0 0;
        align: left middle;
    }

    #loading-indicator {
        width: 3;
        height: 1;
    }

    #loading-label {
        color: #94a3b8;
        margin: 0 0 0 1;
    }

    .menu-button {
        width: 100%;
        margin: 0 0 1 0;
        height: 3;
    }

    #version-label {
        color: #334155;
        text-align: center;
        width: 100%;
        padding: 1 0;
    }
    """

    def compose(self) -> ComposeResult:
        # Detect terminal width to pick logo size
        yield Static(LOGO, id="logo")
        yield Static("Your laptop. Your server. Your rules.", id="tagline")

        with Horizontal(id="content-row"):
            # ── System checks panel ──────────────────────────────────────────
            with Vertical(id="checks-panel"):
                yield Label("System Checks", classes="panel-title")
                for name in _CHECK_LABELS:
                    yield CheckRow(name, id=f"check-row-{name}")
                with Horizontal(id="loading-row"):
                    yield LoadingIndicator(id="loading-indicator")
                    yield Label("Running checks…", id="loading-label")

            # ── Main menu panel ───────────────────────────────────────────────
            with Vertical(id="menu-panel"):
                yield Label("Main Menu", classes="panel-title")
                yield Button("[1] 🚀  New Project", id="new-project", classes="menu-button -primary")
                yield Button("[2] 📂  Manage Projects", id="manage", classes="menu-button")
                yield Button("[3] 📊  Open Dashboard", id="dashboard", classes="menu-button")
                yield Button("[4] ⚙️   Settings", id="settings", classes="menu-button")
                yield Button("[5] 🗑️   Uninstall HomeHost", id="uninstall", classes="menu-button -error")

        yield Static("HomeHost v0.1.0  •  Press ? for help", id="version-label")
        yield Footer()

    def on_mount(self) -> None:
        self.run_system_checks()

    @work(exclusive=True, thread=True)
    def run_system_checks(self) -> None:
        """Run all system checks in a background thread and update UI."""
        try:
            from homehost.core.detector import run_all_checks

            results = run_all_checks()
        except Exception as exc:  # noqa: BLE001
            self.app.call_from_thread(
                self.query_one("#loading-label", Label).update,
                f"Check error: {exc}",
            )
            return

        for result in results:
            name = result.name
            # Guard: only update rows we rendered
            if name not in _CHECK_LABELS:
                continue
            status = result.status
            message = result.message
            if result.fix_hint and status != "ok":
                message = f"{message}  [{result.fix_hint[:60]}]"

            def _update(n=name, s=status, m=message) -> None:
                try:
                    row = self.query_one(f"#check-row-{n}", CheckRow)
                    row.update_result(s, m)
                except Exception:
                    pass

            self.app.call_from_thread(_update)

        # Hide loading indicator when done
        def _done() -> None:
            with contextlib.suppress(Exception):
                self.query_one("#loading-row").display = False

        self.app.call_from_thread(_done)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id == "new-project":
            self._go_new_project()
        elif btn_id == "manage":
            self._go_manage()
        elif btn_id == "dashboard":
            self.action_menu_dashboard()
        elif btn_id == "settings":
            self._go_settings()
        elif btn_id == "uninstall":
            self._go_uninstall()

    # ── Action handlers (keyboard shortcuts) ──────────────────────────────────

    def action_menu_new(self) -> None:
        self._go_new_project()

    def action_menu_manage(self) -> None:
        self._go_manage()

    def action_menu_dashboard(self) -> None:
        import webbrowser

        webbrowser.open("http://localhost:9111")
        self.app.notify("Opening dashboard in browser…")

    def action_menu_settings(self) -> None:
        self._go_settings()

    def action_menu_uninstall(self) -> None:
        self._go_uninstall()

    # ── Navigation helpers ────────────────────────────────────────────────────

    def _go_new_project(self) -> None:
        try:
            from homehost.tui.screens.setup import SetupScreen

            self.app.push_screen(SetupScreen())
        except ImportError as exc:
            self.app.notify(f"Cannot open setup screen: {exc}", severity="error")

    def _go_manage(self) -> None:
        try:
            from homehost.tui.screens.manage import ManageScreen

            self.app.push_screen(ManageScreen())
        except ImportError as exc:
            self.app.notify(f"Cannot open manage screen: {exc}", severity="error")

    def _go_settings(self) -> None:
        self.app.notify("Settings screen coming soon!", severity="information")

    def _go_uninstall(self) -> None:
        try:
            from homehost.tui.screens.uninstall import UninstallScreen

            self.app.push_screen(UninstallScreen())
        except ImportError as exc:
            self.app.notify(f"Cannot open uninstall screen: {exc}", severity="error")
