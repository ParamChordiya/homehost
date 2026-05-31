"""Uninstall confirmation and progress screen."""

from __future__ import annotations

import asyncio
import contextlib
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from textual import work
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Label, ProgressBar, RichLog, Static

if TYPE_CHECKING:
    from textual.app import ComposeResult

_REMOVAL_CHECKLIST = [
    ("stop_processes", "Stop all running projects"),
    ("remove_configs", "Remove ~/.homehost configuration directory"),
    ("remove_caddy_cfg", "Remove Caddy config snippets (if any)"),
    ("remove_tunnels", "Terminate active Cloudflare tunnels"),
    ("remove_pip", "Uninstall homehost Python package"),
]


class UninstallScreen(Screen):
    """Two-phase uninstall: confirm → progress → done."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("q", "cancel", "Cancel"),
    ]

    DEFAULT_CSS = """
    UninstallScreen {
        align: center middle;
        background: #1a1a2e;
    }

    #uninstall-box {
        width: 70;
        height: auto;
        background: #16213e;
        border: solid #f87171;
        padding: 2 4;
    }

    #uninstall-title {
        color: #f87171;
        text-style: bold;
        text-align: center;
        width: 100%;
        padding: 0 0 1 0;
    }

    #uninstall-subtitle {
        color: #94a3b8;
        text-align: center;
        width: 100%;
        padding: 0 0 2 0;
    }

    .checklist-item {
        color: #f8fafc;
        padding: 0 0 0 2;
        height: 1;
    }

    .checklist-item .item-icon {
        color: #fbbf24;
        width: 4;
    }

    #checklist-container {
        background: #0f3460;
        border: solid #334155;
        padding: 1 2;
        margin: 1 0;
        width: 100%;
    }

    #confirm-warning {
        color: #fbbf24;
        text-align: center;
        width: 100%;
        padding: 1 0;
    }

    #confirm-buttons {
        width: 100%;
        align: center middle;
        padding: 1 0 0 0;
    }

    #confirm-buttons Button {
        width: 20;
        height: 3;
        margin: 0 2;
    }

    #progress-bar {
        width: 100%;
        margin: 1 0;
    }

    #progress-log {
        height: 12;
        width: 100%;
        margin: 1 0;
        border: solid #334155;
    }

    #done-title {
        color: #4ade80;
        text-style: bold;
        text-align: center;
        width: 100%;
        padding: 1 0;
    }

    #done-msg {
        color: #94a3b8;
        text-align: center;
        width: 100%;
        padding: 0 0 1 0;
    }

    #done-buttons {
        width: 100%;
        align: center middle;
        padding: 1 0 0 0;
    }
    """

    _phase: str = "confirm"  # "confirm" | "progress" | "done"

    def compose(self) -> ComposeResult:
        with Vertical(id="uninstall-box"):
            yield Static("", id="uninstall-body")
        yield Footer()

    def on_mount(self) -> None:
        self._render_confirm()

    # ── Phase renders ─────────────────────────────────────────────────────────

    def _render_confirm(self) -> None:
        self._phase = "confirm"
        body = self.query_one("#uninstall-body", Static)
        body.remove_children()

        body.mount(Label("🗑️  Uninstall HomeHost", id="uninstall-title"))
        body.mount(
            Label(
                "The following items will be removed from your system:",
                id="uninstall-subtitle",
            )
        )

        with Vertical(id="checklist-container") as cl:
            body.mount(cl)
            for _key, desc in _REMOVAL_CHECKLIST:
                with Horizontal(classes="checklist-item") as row:
                    cl.mount(row)
                    row.mount(Label("⚠️ ", classes="item-icon"))
                    row.mount(Label(desc))

        body.mount(
            Label(
                "⚠️  This action cannot be undone.\n" "Your project source files will NOT be deleted.",
                id="confirm-warning",
            )
        )

        with Horizontal(id="confirm-buttons") as btns:
            body.mount(btns)
            btns.mount(Button("🗑  Yes, Uninstall", id="btn-uninstall-go", classes="-error"))
            btns.mount(Button("Cancel", id="btn-uninstall-cancel"))

    def _render_progress(self) -> None:
        self._phase = "progress"
        body = self.query_one("#uninstall-body", Static)
        body.remove_children()

        body.mount(Label("Uninstalling HomeHost…", id="uninstall-title"))
        body.mount(ProgressBar(total=100, id="progress-bar", show_eta=False))
        log = RichLog(id="progress-log", wrap=True, highlight=True, markup=True)
        body.mount(log)

        self.run_uninstall()

    def _render_done(self, success: bool) -> None:
        self._phase = "done"
        body = self.query_one("#uninstall-body", Static)
        body.remove_children()

        if success:
            body.mount(Label("✅  HomeHost Uninstalled", id="done-title"))
            body.mount(
                Label(
                    "HomeHost has been removed from your system.\n"
                    "Thank you for using HomeHost! Run `pip install homehost` to reinstall.",
                    id="done-msg",
                )
            )
        else:
            body.mount(Label("⚠️  Uninstall Incomplete", id="uninstall-title"))
            body.mount(
                Label(
                    "Some components could not be removed automatically.\n" "Check the log above for details.",
                    id="done-msg",
                )
            )

        with Horizontal(id="done-buttons") as btns:
            body.mount(btns)
            btns.mount(Button("Close", id="btn-done-close", classes="-primary"))

    # ── Events ────────────────────────────────────────────────────────────────

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id == "btn-uninstall-go":
            self._render_progress()
        elif btn_id in ("btn-uninstall-cancel", "btn-done-close"):
            self.app.pop_screen()

    def action_cancel(self) -> None:
        if self._phase != "progress":
            self.app.pop_screen()

    # ── Uninstall worker ──────────────────────────────────────────────────────

    def _log(self, msg: str) -> None:
        with contextlib.suppress(Exception):
            self.query_one("#progress-log", RichLog).write(msg)

    def _set_progress(self, pct: float) -> None:
        try:
            pb = self.query_one("#progress-bar", ProgressBar)
            pb.advance(pct - (pb.progress or 0))
        except Exception:
            pass

    @work(exclusive=True)
    async def run_uninstall(self) -> None:
        """Async uninstall pipeline."""
        await asyncio.sleep(0.3)
        success = True

        # 1. Stop all processes
        self._log("[bold #4c9be8]Step 1/5 — Stopping all projects…[/]")
        try:
            from homehost.core.config import homehost_dir
            from homehost.core.process import ProcessManager

            run_dir = homehost_dir() / "run"
            pm = ProcessManager(run_dir)
            pm.stop_all()
            self._log("   [#4ade80]All processes stopped.[/]")
        except Exception as exc:
            self._log(f"   [#fbbf24]Warning: {exc}[/]")
        self._set_progress(20)
        await asyncio.sleep(0.4)

        # 2. Remove ~/.homehost directory
        self._log("[bold #4c9be8]Step 2/5 — Removing configuration directory…[/]")
        try:
            from homehost.core.config import homehost_dir

            hh_dir = homehost_dir()
            if hh_dir.exists():
                shutil.rmtree(hh_dir)
                self._log(f"   [#4ade80]Removed: {hh_dir}[/]")
            else:
                self._log("   [#94a3b8]Not found — already clean.[/]")
        except Exception as exc:
            self._log(f"   [#f87171]Error: {exc}[/]")
            success = False
        self._set_progress(40)
        await asyncio.sleep(0.4)

        # 3. Remove Caddy config snippets
        self._log("[bold #4c9be8]Step 3/5 — Removing Caddy config snippets…[/]")
        try:
            caddy_conf_dir = Path("/etc/caddy/conf.d")
            removed = 0
            if caddy_conf_dir.exists():
                for f in caddy_conf_dir.glob("homehost-*.conf"):
                    f.unlink()
                    removed += 1
            self._log(f"   [#4ade80]Removed {removed} Caddy config file(s).[/]")
        except PermissionError:
            self._log("   [#fbbf24]No permission to remove Caddy configs (may need sudo).[/]")
        except Exception as exc:
            self._log(f"   [#fbbf24]Warning: {exc}[/]")
        self._set_progress(60)
        await asyncio.sleep(0.4)

        # 4. Terminate cloudflared tunnels
        self._log("[bold #4c9be8]Step 4/5 — Terminating Cloudflare tunnels…[/]")
        try:
            import subprocess

            subprocess.run(
                ["pkill", "-f", "cloudflared tunnel"],
                capture_output=True,
                timeout=5,
            )
            self._log("   [#4ade80]Tunnel processes terminated.[/]")
        except FileNotFoundError:
            self._log("   [#94a3b8]pkill not available — skipping.[/]")
        except Exception as exc:
            self._log(f"   [#fbbf24]Warning: {exc}[/]")
        self._set_progress(80)
        await asyncio.sleep(0.4)

        # 5. Pip uninstall
        self._log("[bold #4c9be8]Step 5/5 — Uninstalling homehost package…[/]")
        try:
            import subprocess
            import sys

            pip_result = subprocess.run(
                [sys.executable, "-m", "pip", "uninstall", "-y", "homehost"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if pip_result.returncode == 0:
                self._log("   [#4ade80]Package uninstalled.[/]")
            else:
                self._log(f"   [#fbbf24]pip uninstall returned {pip_result.returncode}: {pip_result.stderr.strip()}[/]")
        except Exception as exc:
            self._log(f"   [#f87171]Error: {exc}[/]")
            success = False
        self._set_progress(100)
        await asyncio.sleep(0.5)

        if success:
            self._log("[bold #4ade80]✅  Uninstall complete.[/]")
        else:
            self._log("[bold #fbbf24]⚠️  Uninstall finished with some errors.[/]")

        await asyncio.sleep(0.8)
        self._render_done(success)
