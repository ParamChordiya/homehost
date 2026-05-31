"""Dashboard server lifecycle management."""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any

import structlog
import uvicorn

log = structlog.get_logger(__name__)

# Silence uvicorn's access logger unless the app is in debug mode.
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


class DashboardServer:
    """Manages the lifecycle of the FastAPI dashboard server."""

    def __init__(self, port: int = 9111, host: str = "127.0.0.1") -> None:
        self.port = port
        self.host = host
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._started_event = threading.Event()

    # ── Public API ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Start the FastAPI server in a background thread using uvicorn."""
        if self.is_running():
            log.debug("dashboard already running", url=self.url)
            return

        from homehost.dashboard.api import app  # local import avoids circular dep

        config = uvicorn.Config(
            app=app,
            host=self.host,
            port=self.port,
            log_level="warning",
            access_log=False,
            loop="asyncio",
        )
        self._server = uvicorn.Server(config)

        # uvicorn must run in its own thread with its own event loop so that it
        # does not block the caller's event loop (e.g. the TUI).
        self._started_event.clear()
        self._thread = threading.Thread(
            target=self._run_server,
            daemon=True,
            name="homehost-dashboard",
        )
        self._thread.start()

        # Wait up to 5 seconds for the server to signal it is ready.
        ready = self._started_event.wait(timeout=5.0)
        if ready:
            log.info("dashboard started", url=self.url)
        else:
            log.warning("dashboard did not confirm startup within 5 s", url=self.url)

    async def stop(self) -> None:
        """Gracefully stop the dashboard server."""
        if self._server is None or not self.is_running():
            return

        log.info("stopping dashboard server")
        self._server.should_exit = True

        if self._thread is not None:
            self._thread.join(timeout=8.0)
            if self._thread.is_alive():
                log.warning("dashboard thread did not exit cleanly")
            self._thread = None

        self._server = None
        log.info("dashboard server stopped")

    def is_running(self) -> bool:
        """Return True if the server thread is alive and the server is started."""
        return (
            self._thread is not None
            and self._thread.is_alive()
            and self._server is not None
            and self._server.started
        )

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    # ── Internal ───────────────────────────────────────────────────────────────

    def _run_server(self) -> None:
        """Entry point for the background thread — runs uvicorn synchronously."""
        # Each background thread needs its own event loop.
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        try:
            loop.run_until_complete(self._serve())
        finally:
            loop.close()
            self._loop = None

    async def _serve(self) -> None:
        """Async wrapper that signals readiness once the server is accepting connections."""
        assert self._server is not None  # kept for type narrowing

        # Monkey-patch startup hook to fire the threading.Event
        original_startup = self._server.startup

        async def _patched_startup(sockets: Any = None) -> None:
            await original_startup(sockets=sockets)
            self._started_event.set()

        self._server.startup = _patched_startup  # type: ignore[method-assign]
        await self._server.serve()


# ── Convenience factory ────────────────────────────────────────────────────────


def start_dashboard_in_background(port: int = 9111, host: str = "127.0.0.1") -> DashboardServer:
    """Start the dashboard server in a daemon thread.

    This function is synchronous so it can be called from non-async contexts
    (e.g. a CLI command). Internally it creates a temporary event loop just
    long enough to call DashboardServer.start().

    Returns the running DashboardServer instance.
    """
    server = DashboardServer(port=port, host=host)

    # If there is already a running event loop (inside an async context),
    # schedule the coroutine on it; otherwise create a temporary one.
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None and loop.is_running():
        # We're inside an async context — cannot call run_until_complete.
        # Schedule it as a fire-and-forget task instead.
        loop.create_task(server.start())
        # Give the thread a moment to spin up.
        import time
        time.sleep(0.5)
    else:
        asyncio.run(server.start())

    return server
