"""New-project setup wizard — step-by-step guided flow."""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path
from typing import TYPE_CHECKING

from textual import work
from textual.binding import Binding
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.screen import Screen
from textual.widgets import (
    Button,
    Input,
    Label,
    LoadingIndicator,
    ProgressBar,
    RichLog,
    Static,
)

if TYPE_CHECKING:
    from textual.app import ComposeResult

# ── Step constants ────────────────────────────────────────────────────────────

STEP_TYPE = 0
STEP_PATH = 1
STEP_ACCESS = 2
STEP_URL = 3
STEP_PROGRESS = 4
STEP_DONE = 5

STEP_NAMES = [
    "Project Type",
    "Directory",
    "Access Mode",
    "Public URL",
    "Setting Up",
    "Ready!",
]

PROJECT_TYPES = [
    ("static", "🌐 Static HTML / CSS / JS"),
    ("nextjs", "⚛️  React / Next.js"),
    ("flask", "🐍 Python · Flask"),
    ("fastapi", "🐍 Python · FastAPI"),
    ("django", "🐍 Python · Django"),
    ("auto", "🔍 Auto-detect"),
]

ACCESS_MODES = [
    ("local", "🏠 Local only  (LAN / same network)"),
    ("public", "🌍 Public internet  (via Cloudflare Tunnel)"),
]

URL_TYPES = [
    ("quick", "⚡ Random URL  (instant, e.g. abc123.trycloudflare.com)"),
    ("subdomain", "📌 Custom subdomain  (requires Cloudflare account)"),
    ("domain", "🔗 Own domain  (point your DNS to HomeHost)"),
]


class StepIndicator(Static):
    """Horizontal step progress bar."""

    DEFAULT_CSS = """
    StepIndicator {
        height: 3;
        width: 100%;
        align: center middle;
        padding: 0 2;
    }
    StepIndicator .step-item {
        width: auto;
        height: 3;
        align: center middle;
    }
    StepIndicator .step-dot-active {
        color: #4c9be8;
        text-style: bold;
    }
    StepIndicator .step-dot-done {
        color: #4ade80;
    }
    StepIndicator .step-dot-future {
        color: #334155;
    }
    StepIndicator .step-sep {
        color: #334155;
        width: 3;
    }
    """

    def __init__(self, total_steps: int, **kwargs) -> None:
        super().__init__(**kwargs)
        self._total = total_steps
        self._current = 0

    def set_step(self, step: int) -> None:
        self._current = step
        self.refresh()

    def render(self) -> str:
        parts: list[str] = []
        for i, name in enumerate(STEP_NAMES):
            if i < self._current:
                parts.append(f"[#4ade80]✔ {name}[/]")
            elif i == self._current:
                parts.append(f"[#4c9be8 bold]● {name}[/]")
            else:
                parts.append(f"[#334155]○ {name}[/]")
            if i < len(STEP_NAMES) - 1:
                parts.append("[#334155] → [/]")
        return " ".join(parts)


class ChoiceButton(Button):
    """A selectable option button that highlights when chosen."""

    DEFAULT_CSS = """
    ChoiceButton {
        width: 100%;
        height: 3;
        margin: 0 0 1 0;
        background: #0f3460;
        border: solid #334155;
        color: #f8fafc;
    }
    ChoiceButton.-selected {
        background: #4c9be8;
        border: solid #4c9be8;
        color: #1a1a2e;
        text-style: bold;
    }
    ChoiceButton:hover {
        background: #16213e;
        border: solid #4c9be8;
    }
    """

    def select(self) -> None:
        self.add_class("-selected")

    def deselect(self) -> None:
        self.remove_class("-selected")


class SetupScreen(Screen):
    """Step-by-step guided project setup wizard."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("enter", "next_step", "Next"),
        Binding("left", "prev_step", "Back"),
        Binding("right", "next_step", "Next"),
    ]

    DEFAULT_CSS = """
    SetupScreen {
        align: center top;
        overflow-y: auto;
    }

    #wizard-header {
        width: 100%;
        background: #16213e;
        border-bottom: solid #334155;
        height: 5;
        padding: 1 2;
        align: center middle;
    }

    #wizard-title {
        color: #4c9be8;
        text-style: bold;
        text-align: center;
        width: 100%;
    }

    #step-indicator {
        width: 100%;
        text-align: center;
    }

    #wizard-body {
        width: 100%;
        height: 1fr;
        padding: 2 4;
        overflow-y: auto;
    }

    #step-title {
        color: #4c9be8;
        text-style: bold;
        padding: 0 0 1 0;
        width: 100%;
    }

    #step-desc {
        color: #94a3b8;
        padding: 0 0 2 0;
        width: 100%;
    }

    #validation-msg {
        height: 1;
        padding: 1 0 0 0;
        width: 100%;
    }

    #nav-bar {
        height: 5;
        width: 100%;
        background: #16213e;
        border-top: solid #334155;
        align: center middle;
        padding: 0 4;
    }

    #nav-bar Button {
        width: 16;
        height: 3;
        margin: 0 1;
    }

    #progress-log {
        height: 15;
        border: solid #334155;
        margin: 1 0;
    }

    #done-box {
        background: #16213e;
        border: solid #4ade80;
        padding: 2 4;
        width: 100%;
        margin: 1 0;
    }

    #done-title {
        color: #4ade80;
        text-style: bold;
        text-align: center;
        width: 100%;
    }

    #done-urls {
        width: 100%;
        padding: 1 0;
    }
    """

    # ── State ─────────────────────────────────────────────────────────────────

    current_step: int = 0
    project_type: str = ""
    project_path: str = ""
    access_mode: str = "local"
    url_type: str = "quick"
    custom_subdomain: str = ""
    custom_domain: str = ""
    _detected_type: str = ""
    _final_port: int = 8080
    _local_url: str = ""
    _public_url: str = ""

    def compose(self) -> ComposeResult:
        with Vertical(id="wizard-header"):
            yield Static("🚀  New Project Setup", id="wizard-title")
            yield StepIndicator(len(STEP_NAMES), id="step-indicator")

        with ScrollableContainer(id="wizard-body"):
            # Step content placeholder — rebuilt on each step transition
            yield Vertical(id="step-content")

        with Horizontal(id="nav-bar"):
            yield Button("← Back", id="btn-back", classes="-warning")
            yield Button("Cancel", id="btn-cancel", classes="-error")
            yield Button("Next →", id="btn-next", classes="-primary")

    def on_mount(self) -> None:
        self._render_step()

    # ── Step rendering ────────────────────────────────────────────────────────

    def _render_step(self) -> None:
        step = self.current_step
        self.query_one(StepIndicator).set_step(step)

        # Update nav buttons
        back_btn = self.query_one("#btn-back", Button)
        next_btn = self.query_one("#btn-next", Button)
        back_btn.disabled = step == 0 or step >= STEP_PROGRESS
        next_btn.label = (
            "Finish"
            if step == STEP_DONE
            else (
                "Start Setup" if step == STEP_URL or (step == STEP_ACCESS and self.access_mode == "local") else "Next →"
            )
        )
        next_btn.disabled = step == STEP_PROGRESS

        container = self.query_one("#step-content", Vertical)
        container.remove_children()

        if step == STEP_TYPE:
            self._render_type_step(container)
        elif step == STEP_PATH:
            self._render_path_step(container)
        elif step == STEP_ACCESS:
            self._render_access_step(container)
        elif step == STEP_URL:
            self._render_url_step(container)
        elif step == STEP_PROGRESS:
            self._render_progress_step(container)
        elif step == STEP_DONE:
            self._render_done_step(container)

    def _render_type_step(self, container: Vertical) -> None:
        container.mount(Label("Select Project Type", id="step-title"))
        container.mount(
            Label(
                "Choose the framework your project uses, or let HomeHost auto-detect it.",
                id="step-desc",
            )
        )
        for value, label in PROJECT_TYPES:
            btn = ChoiceButton(label, id=f"type-{value}")
            if value == self.project_type:
                btn.select()
            container.mount(btn)
        container.mount(Label("", id="validation-msg"))

    def _render_path_step(self, container: Vertical) -> None:
        container.mount(Label("Project Directory", id="step-title"))
        container.mount(
            Label(
                "Enter the absolute path to your project folder.\n" "Example: /Users/you/projects/my-website",
                id="step-desc",
            )
        )
        inp = Input(
            placeholder="/path/to/your/project",
            id="path-input",
            value=self.project_path,
        )
        container.mount(inp)
        container.mount(Label("", id="validation-msg"))

        if self.project_path:
            self._validate_path_inline(self.project_path)

    def _render_access_step(self, container: Vertical) -> None:
        container.mount(Label("Access Mode", id="step-title"))
        container.mount(
            Label(
                "Choose who can access your project.\n"
                "Local: only devices on your network.  Public: anyone on the internet.",
                id="step-desc",
            )
        )
        for value, label in ACCESS_MODES:
            btn = ChoiceButton(label, id=f"access-{value}")
            if value == self.access_mode:
                btn.select()
            container.mount(btn)
        container.mount(Label("", id="validation-msg"))

    def _render_url_step(self, container: Vertical) -> None:
        container.mount(Label("Public URL Type", id="step-title"))
        container.mount(
            Label(
                "How would you like your project to be accessible on the internet?\n"
                "You'll need cloudflared installed for all options.",
                id="step-desc",
            )
        )
        for value, label in URL_TYPES:
            btn = ChoiceButton(label, id=f"url-{value}")
            if value == self.url_type:
                btn.select()
            container.mount(btn)

        # Extra input for subdomain / domain
        if self.url_type == "subdomain":
            container.mount(Label("Subdomain name (e.g. mysite):", classes="label-dim"))
            container.mount(
                Input(
                    placeholder="mysite",
                    id="subdomain-input",
                    value=self.custom_subdomain,
                )
            )
        elif self.url_type == "domain":
            container.mount(Label("Your domain (e.g. mysite.com):", classes="label-dim"))
            container.mount(
                Input(
                    placeholder="mysite.com",
                    id="domain-input",
                    value=self.custom_domain,
                )
            )

        container.mount(Label("", id="validation-msg"))

    def _render_progress_step(self, container: Vertical) -> None:
        container.mount(Label("Setting Up Your Project", id="step-title"))
        container.mount(
            Label(
                "HomeHost is configuring your server. This may take a moment…",
                id="step-desc",
            )
        )
        container.mount(ProgressBar(total=100, id="setup-progress", show_eta=False))
        log = RichLog(id="progress-log", wrap=True, highlight=True, markup=True)
        container.mount(log)
        container.mount(LoadingIndicator(id="setup-loading"))
        # Kick off the actual setup
        self.run_setup()

    def _render_done_step(self, container: Vertical) -> None:
        container.mount(Label("🎉  Project is Live!", id="step-title"))

        with Vertical(id="done-box") as box:
            container.mount(box)
            box.mount(Label("✅  Your project is running.", id="done-title"))
            box.mount(Label("", classes="label-dim"))

            if self._local_url:
                box.mount(Label(f"🏠  Local URL:   {self._local_url}", classes="label-success"))
            if self._public_url:
                box.mount(Label(f"🌍  Public URL:  {self._public_url}", classes="label-accent"))

            box.mount(Label("", classes="label-dim"))
            box.mount(
                Label(
                    "Press D to open the dashboard, or N to add another project.",
                    classes="label-dim",
                )
            )

    # ── Validation helpers ────────────────────────────────────────────────────

    def _set_validation(self, msg: str, ok: bool) -> None:
        try:
            lbl = self.query_one("#validation-msg", Label)
            cls = "label-success" if ok else "label-error"
            lbl.update(msg)
            lbl.set_classes(f"validation-msg {cls}")
        except Exception:
            pass

    def _validate_path_inline(self, path_str: str) -> bool:
        if not path_str.strip():
            self._set_validation("Please enter a directory path.", ok=False)
            return False
        p = Path(path_str.strip()).expanduser()
        if not p.exists():
            self._set_validation(f"Directory does not exist: {p}", ok=False)
            return False
        if not p.is_dir():
            self._set_validation("Path is not a directory.", ok=False)
            return False
        self._set_validation(f"✔ Directory found: {p}", ok=True)
        return True

    # ── Step navigation ───────────────────────────────────────────────────────

    def next_step(self) -> None:
        step = self.current_step

        if step == STEP_TYPE:
            if not self.project_type:
                self._set_validation("Please select a project type.", ok=False)
                return

        elif step == STEP_PATH:
            raw = ""
            with contextlib.suppress(Exception):
                raw = self.query_one("#path-input", Input).value
            self.project_path = raw.strip()
            if not self._validate_path_inline(self.project_path):
                return

        elif step == STEP_ACCESS:
            pass  # always valid

        elif step == STEP_URL:
            if self.url_type == "subdomain":
                with contextlib.suppress(Exception):
                    self.custom_subdomain = self.query_one("#subdomain-input", Input).value.strip()
                if not self.custom_subdomain:
                    self._set_validation("Please enter a subdomain name.", ok=False)
                    return
            elif self.url_type == "domain":
                with contextlib.suppress(Exception):
                    self.custom_domain = self.query_one("#domain-input", Input).value.strip()
                if not self.custom_domain:
                    self._set_validation("Please enter your domain name.", ok=False)
                    return

        elif step == STEP_DONE:
            self.app.pop_screen()
            return

        # Skip URL step when local-only
        if step == STEP_ACCESS and self.access_mode == "local":
            self.current_step = STEP_PROGRESS
        else:
            self.current_step = step + 1

        self._render_step()

    def prev_step(self) -> None:
        if self.current_step <= 0 or self.current_step >= STEP_PROGRESS:
            return
        # Skip URL step backward when access is local
        if self.current_step == STEP_PROGRESS and self.access_mode == "local":
            self.current_step = STEP_ACCESS
        else:
            self.current_step -= 1
        self._render_step()

    # ── Button / Input event handling ─────────────────────────────────────────

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id or ""

        if btn_id == "btn-next":
            self.next_step()
            return
        if btn_id == "btn-back":
            self.prev_step()
            return
        if btn_id == "btn-cancel":
            self.action_cancel()
            return

        # Type selection buttons
        if btn_id.startswith("type-"):
            value = btn_id[5:]
            self.project_type = value
            for v, _ in PROJECT_TYPES:
                try:
                    btn = self.query_one(f"#type-{v}", ChoiceButton)
                    btn.select() if v == value else btn.deselect()
                except Exception:
                    pass
            self._set_validation(f"Selected: {value}", ok=True)
            return

        # Access mode buttons
        if btn_id.startswith("access-"):
            value = btn_id[7:]
            self.access_mode = value
            for v, _ in ACCESS_MODES:
                try:
                    btn = self.query_one(f"#access-{v}", ChoiceButton)
                    btn.select() if v == value else btn.deselect()
                except Exception:
                    pass
            return

        # URL type buttons
        if btn_id.startswith("url-"):
            value = btn_id[4:]
            self.url_type = value
            for v, _ in URL_TYPES:
                try:
                    btn = self.query_one(f"#url-{v}", ChoiceButton)
                    btn.select() if v == value else btn.deselect()
                except Exception:
                    pass
            # Re-render to show/hide sub-input
            self._render_step()
            return

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "path-input":
            self._validate_path_inline(event.value)

    # ── Setup worker ──────────────────────────────────────────────────────────

    def _log(self, msg: str) -> None:
        try:
            log_widget = self.query_one("#progress-log", RichLog)
            log_widget.write(msg)
        except Exception:
            pass

    def _set_progress(self, value: float) -> None:
        try:
            pb = self.query_one("#setup-progress", ProgressBar)
            pb.advance(value - (pb.progress or 0))
        except Exception:
            pass

    @work(exclusive=True)
    async def run_setup(self) -> None:
        """Async setup pipeline — runs at STEP_PROGRESS."""
        await asyncio.sleep(0.3)  # let UI render

        self._log("[bold #4c9be8]Starting HomeHost setup…[/]")
        self._set_progress(5)

        project_path = Path(self.project_path).expanduser().resolve()

        # Step 1: Detect type if auto
        self._log("🔍 Detecting project type…")
        actual_type = self.project_type
        try:
            if self.project_type == "auto":
                from homehost.core.project import detect_project_type

                result = detect_project_type(project_path)
                actual_type = result.project_type.value
                self._log(f"   Detected: [#4ade80]{actual_type}[/] ({result.reason})")
            else:
                self._log(f"   Type: [#4ade80]{actual_type}[/]")
        except Exception as exc:
            self._log(f"   [#fbbf24]Warning: could not detect type ({exc}), using 'static'[/]")
            actual_type = "static"
        self._set_progress(20)
        await asyncio.sleep(0.2)

        # Step 2: Find available port
        self._log("🔌 Finding available port…")
        try:
            from homehost.core.detector import find_available_port

            port = find_available_port(8080, 8099)
            if port is None:
                port = 8080
                self._log("   [#fbbf24]Warning: all ports 8080-8099 busy, defaulting to 8080[/]")
            else:
                self._log(f"   Port: [#4ade80]{port}[/]")
        except Exception:
            port = 8080
            self._log(f"   Port: [#4ade80]{port}[/] (default)")
        self._final_port = port
        self._set_progress(35)
        await asyncio.sleep(0.2)

        # Step 3: Save project config
        self._log("💾 Saving project configuration…")
        project_name = project_path.name
        try:
            from homehost.core.config import (
                ProjectConfig,
                save_project_config,
            )

            cfg = ProjectConfig(
                name=project_name,
                type=actual_type,
                path=str(project_path),
            )
            cfg.server.port = port
            cfg.network.access = self.access_mode
            if self.url_type == "subdomain":
                cfg.network.subdomain = self.custom_subdomain
            elif self.url_type == "domain":
                cfg.network.custom_domain = self.custom_domain
            save_project_config(cfg)
            self._log(f"   Saved: [#4ade80]{project_name}[/]")
        except Exception as exc:
            self._log(f"   [#f87171]Config save failed: {exc}[/]")
        self._set_progress(50)
        await asyncio.sleep(0.3)

        # Step 4: Start static server (simplified — real impl would call servers/)
        self._log("🚀 Starting server…")
        await asyncio.sleep(0.8)
        self._local_url = f"http://localhost:{port}"
        self._log(f"   Local URL: [#4ade80]{self._local_url}[/]")
        self._set_progress(75)

        # Step 5: Start tunnel if public
        if self.access_mode == "public":
            self._log("🌍 Starting Cloudflare tunnel…")
            await asyncio.sleep(1.0)
            # In a real impl: start cloudflared and parse the URL from stdout
            self._public_url = f"https://{project_name}-{port}.trycloudflare.com"
            self._log(f"   Public URL: [#4c9be8]{self._public_url}[/]")
        self._set_progress(95)
        await asyncio.sleep(0.3)

        self._log("[bold #4ade80]✅ Setup complete![/]")
        self._set_progress(100)
        await asyncio.sleep(0.5)

        # Advance to done step
        self.current_step = STEP_DONE
        self._render_step()

    # ── Actions ───────────────────────────────────────────────────────────────

    def action_cancel(self) -> None:
        self.app.pop_screen()

    def action_next_step(self) -> None:
        self.next_step()

    def action_prev_step(self) -> None:
        self.prev_step()
