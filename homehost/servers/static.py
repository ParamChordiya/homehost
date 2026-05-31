"""Static file server backed by Python's built-in http.server."""

from __future__ import annotations

import asyncio
import http.server
import os
import socket
import threading
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger(__name__)

# ── Security / logging handler ─────────────────────────────────────────────────

_BLOCKED_PREFIXES = (".git", ".env", ".htaccess", ".htpasswd", ".DS_Store")

_SECURITY_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "SAMEORIGIN",
    "X-XSS-Protection": "1; mode=block",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Cache-Control": "no-cache",
}


def _make_handler(
    directory: Path,
    request_counter: _Counter,
) -> type[http.server.BaseHTTPRequestHandler]:
    """Return a custom request handler class closed over *directory* and *request_counter*."""

    class _Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            # SimpleHTTPRequestHandler.directory controls the doc root
            super().__init__(*args, directory=str(directory), **kwargs)

        # ── Dotfile / security guard ───────────────────────────────────────────

        def _is_blocked(self) -> bool:
            """Return True if the request path references a blocked resource."""
            # Strip query string and leading slash
            clean = self.path.split("?", 1)[0].lstrip("/")
            parts = Path(clean).parts
            for part in parts:
                if any(part == prefix or part.startswith(prefix) for prefix in _BLOCKED_PREFIXES):
                    return True
                if part.startswith("."):
                    return True
            return False

        # ── Directory listing disabled ─────────────────────────────────────────

        def list_directory(self, path: str) -> None:  # type: ignore[override]
            """Refuse directory listings with 403 Forbidden."""
            self.send_error(403, "Directory listing disabled")
            return None

        def _is_directory_path(self) -> bool:
            """Return True if the requested path resolves to a directory."""
            try:
                # Replicate SimpleHTTPRequestHandler's path translation
                translated = self.translate_path(self.path)
                return os.path.isdir(translated)
            except Exception:  # noqa: BLE001
                return False

        # ── Security headers on every response ────────────────────────────────

        def end_headers(self) -> None:
            for header, value in _SECURITY_HEADERS.items():
                self.send_header(header, value)
            super().end_headers()

        # ── Request dispatch ──────────────────────────────────────────────────

        def do_GET(self) -> None:
            if self._is_blocked():
                self.send_error(403, "Forbidden")
                return
            if self._is_directory_path():
                self.send_error(403, "Directory listing disabled")
                return
            request_counter.increment()
            super().do_GET()

        def do_HEAD(self) -> None:
            if self._is_blocked():
                self.send_error(403, "Forbidden")
                return
            if self._is_directory_path():
                self.send_error(403, "Directory listing disabled")
                return
            super().do_HEAD()

        # ── Structured logging ─────────────────────────────────────────────────

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            log.info(
                "static request",
                client=self.address_string(),
                method=self.command,
                path=self.path,
                status=args[1] if len(args) > 1 else "-",
            )

        def log_error(self, format: str, *args: Any) -> None:  # noqa: A002
            log.warning(
                "static server error",
                client=self.address_string(),
                detail=format % args,
            )

    return _Handler


# ── Thread-safe request counter ────────────────────────────────────────────────


class _Counter:
    def __init__(self) -> None:
        self._value: int = 0
        self._lock = threading.Lock()

    def increment(self) -> None:
        with self._lock:
            self._value += 1

    @property
    def value(self) -> int:
        with self._lock:
            return self._value


# ── Port utility ───────────────────────────────────────────────────────────────


def find_free_port(start: int = 8080, end: int = 8099) -> int:
    """Return the first unused port in [start, end].

    Raises RuntimeError if every port in the range is in use.
    """
    for port in range(start, end + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("0.0.0.0", port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"No free port found in range {start}–{end}")


# ── StaticServer ───────────────────────────────────────────────────────────────


def _get_local_ip() -> str:
    """Return the machine's primary LAN IP, or 127.0.0.1 on failure."""
    # Lazy import to avoid circular dependency; fall back to socket trick.
    try:
        from homehost.utils.network import get_local_ip  # type: ignore[import]
        return get_local_ip()
    except Exception:  # noqa: BLE001
        pass
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("1.1.1.1", 53))
            return s.getsockname()[0]
    except Exception:  # noqa: BLE001
        return "127.0.0.1"


class StaticServer:
    """Serve a static directory over HTTP using Python's built-in http.server.

    The server runs in a daemon thread so it does not block the event loop.
    """

    def __init__(
        self,
        directory: Path,
        port: int,
        host: str = "0.0.0.0",
    ) -> None:
        if not directory.is_dir():
            raise ValueError(f"directory does not exist or is not a directory: {directory}")

        self._directory = directory.resolve()
        self._port = port
        self._host = host
        self._counter = _Counter()
        self._server: http.server.HTTPServer | None = None
        self._thread: threading.Thread | None = None

    # ── Async lifecycle ───────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the HTTP server in a background daemon thread."""
        if self._server is not None:
            log.warning("static server already running", port=self._port)
            return

        handler_cls = _make_handler(self._directory, self._counter)

        # Allow the OS to reuse the address immediately after restart
        http.server.HTTPServer.allow_reuse_address = True

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._create_server, handler_cls)

        self._thread = threading.Thread(
            target=self._server.serve_forever,  # type: ignore[union-attr]
            daemon=True,
            name=f"homehost-static-{self._port}",
        )
        self._thread.start()

        log.info(
            "static server started",
            directory=str(self._directory),
            host=self._host,
            port=self._port,
            url=self.url,
        )

    def _create_server(self, handler_cls: type[http.server.BaseHTTPRequestHandler]) -> None:
        """Blocking — called from executor thread."""
        self._server = http.server.HTTPServer((self._host, self._port), handler_cls)

    async def stop(self) -> None:
        """Shut down the server and wait for the thread to finish."""
        if self._server is None:
            return

        log.info("stopping static server", port=self._port)
        loop = asyncio.get_running_loop()
        server = self._server
        self._server = None

        # shutdown() blocks until serve_forever() returns; run in executor
        await loop.run_in_executor(None, server.shutdown)

        if self._thread is not None:
            thread = self._thread
            self._thread = None
            await loop.run_in_executor(None, lambda: thread.join(timeout=5))

        log.info("static server stopped", port=self._port)

    # ── Status ────────────────────────────────────────────────────────────────

    def is_running(self) -> bool:
        """Return True if the server thread is alive."""
        return (
            self._server is not None
            and self._thread is not None
            and self._thread.is_alive()
        )

    @property
    def request_count(self) -> int:
        """Total number of GET requests served since start."""
        return self._counter.value

    # ── URL helpers ───────────────────────────────────────────────────────────

    @property
    def url(self) -> str:
        """Public-facing URL (bound host or 0.0.0.0 → localhost)."""
        display_host = "localhost" if self._host in ("0.0.0.0", "") else self._host
        return f"http://{display_host}:{self._port}"

    @property
    def local_url(self) -> str:
        """LAN URL using the machine's primary IP address."""
        return f"http://{_get_local_ip()}:{self._port}"

    # ── Repr ──────────────────────────────────────────────────────────────────

    def __repr__(self) -> str:
        state = "running" if self.is_running() else "stopped"
        return (
            f"StaticServer(directory={self._directory!r}, "
            f"port={self._port}, state={state!r})"
        )
