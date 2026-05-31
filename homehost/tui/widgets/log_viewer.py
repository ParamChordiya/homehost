"""LogViewer widget — scrollable log display with level-based color coding."""

from __future__ import annotations

from collections import deque
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Button, Input, Label, RichLog, Static


_LEVEL_COLORS = {
    "DEBUG":    "#94a3b8",   # dim blue-grey
    "INFO":     "#f8fafc",   # white
    "WARNING":  "#fbbf24",   # amber
    "WARN":     "#fbbf24",
    "ERROR":    "#f87171",   # red
    "CRITICAL": "#f87171",
    "SUCCESS":  "#4ade80",   # green
}


def _detect_level(line: str) -> str:
    upper = line.upper()
    for level in ("CRITICAL", "ERROR", "WARNING", "WARN", "DEBUG", "SUCCESS", "INFO"):
        if level in upper:
            return level
    return "INFO"


def _colorize(line: str, level: str) -> str:
    color = _LEVEL_COLORS.get(level, "#f8fafc")
    return f"[{color}]{line}[/]"


class LogViewer(Widget):
    """Scrollable log viewer with level-based coloring, filtering, and a circular buffer.

    Usage::

        viewer = LogViewer(max_lines=500)
        viewer.add_line("Server started", level="INFO")
        viewer.load_from_file(Path("/path/to/server.log"))
    """

    max_lines: int = 500
    filter_text: reactive[str] = reactive("")

    DEFAULT_CSS = """
    LogViewer {
        height: 1fr;
        width: 100%;
    }

    #log-toolbar {
        height: 3;
        width: 100%;
        background: #16213e;
        border-bottom: solid #334155;
        align: left middle;
        padding: 0 1;
    }

    #filter-label {
        color: #94a3b8;
        width: auto;
        margin: 0 1 0 0;
    }

    #filter-input {
        width: 1fr;
        background: #0f3460;
        border: solid #334155;
        height: 3;
    }

    #filter-input:focus {
        border: solid #4c9be8;
    }

    #btn-clear {
        width: 10;
        height: 3;
        margin: 0 0 0 1;
    }

    #btn-scroll-bottom {
        width: 14;
        height: 3;
        margin: 0 0 0 1;
    }

    #log-body {
        height: 1fr;
        width: 100%;
        background: #0a0a14;
        border: solid #334155;
    }

    #level-legend {
        height: 1;
        width: 100%;
        background: #16213e;
        padding: 0 1;
        align: left middle;
    }

    #legend-label {
        color: #334155;
    }
    """

    def __init__(self, max_lines: int = 500, **kwargs) -> None:
        super().__init__(**kwargs)
        self.max_lines = max_lines
        self._buffer: deque[tuple[str, str]] = deque(maxlen=max_lines)  # (raw_line, level)

    def compose(self) -> ComposeResult:
        with Horizontal(id="log-toolbar"):
            yield Label("🔍 Filter:", id="filter-label")
            yield Input(placeholder="Type to filter…", id="filter-input")
            yield Button("Clear",         id="btn-clear",         classes="-warning")
            yield Button("↓ Bottom",      id="btn-scroll-bottom")
        yield RichLog(
            id="log-body",
            wrap=True,
            highlight=False,
            markup=True,
            auto_scroll=True,
        )
        with Horizontal(id="level-legend"):
            yield Label(
                "[#94a3b8]DEBUG[/]  [#f8fafc]INFO[/]  "
                "[#fbbf24]WARNING[/]  [#f87171]ERROR/CRITICAL[/]  "
                "[#4ade80]SUCCESS[/]",
                id="legend-label",
            )

    # ── Public API ────────────────────────────────────────────────────────────

    def add_line(self, line: str, level: str = "INFO") -> None:
        """Append a single line to the log buffer and display it."""
        level = level.upper()
        self._buffer.append((line, level))

        if self.filter_text and self.filter_text.lower() not in line.lower():
            return

        try:
            rlog = self.query_one("#log-body", RichLog)
            rlog.write(_colorize(line, level))
        except Exception:
            pass

    def clear(self) -> None:
        """Clear the buffer and the displayed log."""
        self._buffer.clear()
        try:
            self.query_one("#log-body", RichLog).clear()
        except Exception:
            pass

    def load_from_file(self, path: Path) -> None:
        """Read the last ``max_lines`` lines from *path* and display them."""
        if not path.exists():
            self.add_line(f"Log file not found: {path}", level="WARNING")
            return
        try:
            raw_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as exc:
            self.add_line(f"Error reading log: {exc}", level="ERROR")
            return

        # Only keep the tail up to max_lines
        tail = raw_lines[-self.max_lines :]
        self.clear()
        for line in tail:
            level = _detect_level(line)
            self._buffer.append((line, level))

        self._redraw()

    def reload_tail(self, path: Path, n_lines: int = 20) -> None:
        """Append the last *n_lines* from *path* (for polling updates)."""
        if not path.exists():
            return
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return
        for line in lines[-n_lines:]:
            level = _detect_level(line)
            self.add_line(line, level)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _redraw(self) -> None:
        """Repopulate the RichLog from the current buffer (respecting filter)."""
        try:
            rlog = self.query_one("#log-body", RichLog)
            rlog.clear()
            fil = self.filter_text.lower()
            for line, level in self._buffer:
                if fil and fil not in line.lower():
                    continue
                rlog.write(_colorize(line, level))
        except Exception:
            pass

    def watch_filter_text(self, new_filter: str) -> None:
        self._redraw()

    # ── Events ────────────────────────────────────────────────────────────────

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "filter-input":
            self.filter_text = event.value

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-clear":
            self.clear()
        elif event.button.id == "btn-scroll-bottom":
            try:
                rlog = self.query_one("#log-body", RichLog)
                rlog.scroll_end(animate=True)
            except Exception:
                pass
