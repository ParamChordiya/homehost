"""HomeHost TUI — main Textual application with screen routing."""

from __future__ import annotations

import webbrowser

from textual.app import App, ComposeResult
from textual.binding import Binding


class HomeHostApp(App):
    """The main HomeHost TUI application."""

    CSS_PATH = None  # inline CSS only

    BINDINGS = [
        Binding("q", "quit", "Quit", priority=True),
        Binding("d", "open_dashboard", "Dashboard"),
        Binding("question_mark", "help", "Help", key_display="?"),
    ]

    CSS = """
    /* ── Global palette ──────────────────────────────────────────────────── */
    $bg:        #1a1a2e;
    $bg-panel:  #16213e;
    $bg-card:   #0f3460;
    $accent:    #4c9be8;
    $success:   #4ade80;
    $warning:   #fbbf24;
    $error:     #f87171;
    $text:      #f8fafc;
    $text-dim:  #94a3b8;
    $border:    #334155;

    /* ── App shell ───────────────────────────────────────────────────────── */
    Screen {
        background: $bg;
        color: $text;
    }

    Header {
        background: $bg-panel;
        color: $accent;
        text-style: bold;
        border-bottom: solid $border;
    }

    Footer {
        background: $bg-panel;
        color: $text-dim;
        border-top: solid $border;
    }

    /* ── Buttons ─────────────────────────────────────────────────────────── */
    Button {
        background: $bg-card;
        color: $text;
        border: solid $border;
        margin: 0 1;
    }

    Button:hover {
        background: $accent;
        color: $bg;
        border: solid $accent;
    }

    Button:focus {
        border: solid $accent;
    }

    Button.-primary {
        background: $accent;
        color: $bg;
        border: solid $accent;
        text-style: bold;
    }

    Button.-primary:hover {
        background: $text;
        color: $bg;
        border: solid $text;
    }

    Button.-success {
        background: $success;
        color: $bg;
        border: solid $success;
        text-style: bold;
    }

    Button.-warning {
        background: $warning;
        color: $bg;
        border: solid $warning;
    }

    Button.-error {
        background: $error;
        color: $bg;
        border: solid $error;
    }

    /* ── Input ───────────────────────────────────────────────────────────── */
    Input {
        background: $bg-card;
        color: $text;
        border: solid $border;
    }

    Input:focus {
        border: solid $accent;
    }

    /* ── Labels / Static ─────────────────────────────────────────────────── */
    .label-dim {
        color: $text-dim;
    }

    .label-accent {
        color: $accent;
        text-style: bold;
    }

    .label-success {
        color: $success;
    }

    .label-warning {
        color: $warning;
    }

    .label-error {
        color: $error;
    }

    /* ── Containers ──────────────────────────────────────────────────────── */
    .panel {
        background: $bg-panel;
        border: solid $border;
        padding: 1 2;
        margin: 1 2;
    }

    .card {
        background: $bg-card;
        border: solid $border;
        padding: 1 2;
        margin: 1;
    }

    .card:hover {
        border: solid $accent;
    }

    /* ── Section headings ────────────────────────────────────────────────── */
    .section-title {
        color: $accent;
        text-style: bold;
        padding: 0 0 1 0;
    }

    /* ── Progress bar ────────────────────────────────────────────────────── */
    ProgressBar {
        color: $accent;
    }

    ProgressBar > .bar--bar {
        color: $accent;
    }

    ProgressBar > .bar--complete {
        color: $success;
    }

    /* ── DataTable ───────────────────────────────────────────────────────── */
    DataTable {
        background: $bg-panel;
        color: $text;
        border: solid $border;
    }

    DataTable > .datatable--header {
        background: $bg-card;
        color: $accent;
        text-style: bold;
    }

    DataTable > .datatable--cursor {
        background: $accent;
        color: $bg;
    }

    /* ── LoadingIndicator ────────────────────────────────────────────────── */
    LoadingIndicator {
        color: $accent;
        background: $bg;
    }

    /* ── RichLog ─────────────────────────────────────────────────────────── */
    RichLog {
        background: #0a0a14;
        color: $text;
        border: solid $border;
        padding: 0 1;
    }
    """

    def on_mount(self) -> None:
        from homehost.tui.screens.welcome import WelcomeScreen
        self.push_screen(WelcomeScreen())

    def action_open_dashboard(self) -> None:
        webbrowser.open("http://localhost:9111")

    def action_help(self) -> None:
        self.notify(
            "HomeHost v0.1.0\n"
            "Q → Quit  D → Dashboard  ? → Help\n"
            "Use the menu or keyboard shortcuts to navigate.",
            title="HomeHost Help",
            severity="information",
            timeout=6,
        )


def run() -> None:
    """Entry point — launch the TUI."""
    app = HomeHostApp()
    app.run()


if __name__ == "__main__":
    run()
