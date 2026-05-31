"""UrlDisplay widget — shows a URL with copy button and optional QR code."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Button, Label, Static


class UrlDisplay(Widget):
    """Shows a labeled URL with [Copy] and [QR] buttons.

    When [Copy] is pressed, the URL is copied to the clipboard (via pyperclip
    if available; falls back to a prominent toast notification).

    When [QR] is pressed, a QR code is rendered in the terminal using the
    ``qrcode`` library (also optional).
    """

    url: reactive[str] = reactive("")
    label: reactive[str] = reactive("URL")
    show_qr: reactive[bool] = reactive(False)

    DEFAULT_CSS = """
    UrlDisplay {
        height: auto;
        width: 100%;
        background: #16213e;
        border: solid #334155;
        padding: 1 2;
        margin: 0 0 1 0;
    }

    UrlDisplay:hover {
        border: solid #4c9be8;
    }

    #url-row {
        height: 3;
        width: 100%;
        align: left middle;
    }

    #url-icon-label {
        color: #94a3b8;
        width: auto;
        margin: 0 2 0 0;
    }

    #url-value {
        color: #4c9be8;
        text-style: bold underline;
        width: 1fr;
    }

    #url-row Button {
        width: 10;
        height: 3;
        margin: 0 0 0 1;
    }

    #qr-area {
        width: 100%;
        padding: 1 0 0 0;
        color: #f8fafc;
    }

    #qr-label {
        color: #94a3b8;
        padding: 0 0 1 0;
    }

    #qr-code {
        color: #f8fafc;
    }

    #no-url-hint {
        color: #334155;
        text-style: italic;
    }
    """

    def __init__(
        self,
        url: str = "",
        label: str = "URL",
        prefix_emoji: str = "🔗",
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.url = url
        self.label = label
        self._prefix_emoji = prefix_emoji
        self._qr_lines: list[str] = []

    def compose(self) -> ComposeResult:
        with Horizontal(id="url-row"):
            yield Label(f"{self._prefix_emoji} {self.label}:", id="url-icon-label")
            if self.url:
                yield Label(self.url, id="url-value")
                yield Button("Copy", id="btn-copy")
                yield Button("QR",   id="btn-qr")
            else:
                yield Label("(not set)", id="no-url-hint")
        with Vertical(id="qr-area"):
            yield Label("QR Code:", id="qr-label")
            yield Static("", id="qr-code")
        # Hide QR area initially
        self.query_one("#qr-area").display = False

    # ── Reactive watchers ─────────────────────────────────────────────────────

    def watch_url(self, new_url: str) -> None:
        try:
            val_lbl = self.query_one("#url-value", Label)
            val_lbl.update(new_url or "(not set)")
        except Exception:
            pass
        # Clear QR cache when URL changes
        self._qr_lines = []
        try:
            self.query_one("#qr-area").display = False
            self.query_one("#qr-code", Static).update("")
        except Exception:
            pass

    def watch_show_qr(self, show: bool) -> None:
        try:
            self.query_one("#qr-area").display = show
        except Exception:
            pass

    # ── Events ────────────────────────────────────────────────────────────────

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-copy":
            self._copy_url()
        elif event.button.id == "btn-qr":
            self._toggle_qr()

    # ── Copy logic ────────────────────────────────────────────────────────────

    def _copy_url(self) -> None:
        if not self.url:
            self.app.notify("No URL to copy.", severity="warning")
            return
        try:
            import pyperclip  # type: ignore[import]
            pyperclip.copy(self.url)
            self.app.notify(f"Copied: {self.url}", title="Copied!")
        except ImportError:
            # pyperclip not available — fallback: try pbcopy / xclip
            copied = self._system_copy(self.url)
            if copied:
                self.app.notify(f"Copied: {self.url}", title="Copied!")
            else:
                # Last resort: show prominently
                self.app.notify(
                    f"URL: {self.url}\n(pyperclip not installed — copy manually)",
                    title="Copy URL",
                    severity="information",
                    timeout=8,
                )
        except Exception as exc:
            self.app.notify(f"Copy failed: {exc}", severity="warning")

    @staticmethod
    def _system_copy(text: str) -> bool:
        """Attempt clipboard copy via pbcopy (macOS) or xclip (Linux)."""
        import subprocess, platform
        cmds = []
        if platform.system() == "Darwin":
            cmds = [["pbcopy"]]
        elif platform.system() == "Linux":
            cmds = [["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]]

        for cmd in cmds:
            try:
                proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
                proc.communicate(input=text.encode())
                if proc.returncode == 0:
                    return True
            except Exception:
                continue
        return False

    # ── QR code logic ─────────────────────────────────────────────────────────

    def _toggle_qr(self) -> None:
        if not self.url:
            self.app.notify("No URL to generate QR for.", severity="warning")
            return

        qr_area = self.query_one("#qr-area")
        if qr_area.display:
            # Hide
            qr_area.display = False
            self.show_qr = False
            return

        # Generate (or use cached)
        if not self._qr_lines:
            self._generate_qr()

        if self._qr_lines:
            qr_text = "\n".join(self._qr_lines)
            try:
                self.query_one("#qr-code", Static).update(qr_text)
            except Exception:
                pass
            qr_area.display = True
            self.show_qr = True

    def _generate_qr(self) -> None:
        """Render QR code as ASCII art using the qrcode library."""
        try:
            import qrcode  # type: ignore[import]
            qr = qrcode.QRCode(
                version=None,
                error_correction=qrcode.constants.ERROR_CORRECT_L,
                box_size=1,
                border=1,
            )
            qr.add_data(self.url)
            qr.make(fit=True)
            matrix = qr.get_matrix()
            lines: list[str] = []
            for row in matrix:
                line = "".join("██" if cell else "  " for cell in row)
                lines.append(line)
            self._qr_lines = lines
        except ImportError:
            self.app.notify(
                "qrcode library not available. Install with: pip install qrcode[pil]",
                severity="warning",
            )
            self._qr_lines = []
        except Exception as exc:
            self.app.notify(f"QR generation failed: {exc}", severity="error")
            self._qr_lines = []
