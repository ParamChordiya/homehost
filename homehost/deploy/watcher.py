"""File-system watcher with debouncing for HomeHost auto-reload."""

from __future__ import annotations

import fnmatch
import threading
import time
from pathlib import Path
from typing import Callable, NamedTuple

from watchdog.events import (
    DirCreatedEvent,
    DirDeletedEvent,
    DirModifiedEvent,
    FileCreatedEvent,
    FileDeletedEvent,
    FileModifiedEvent,
    FileSystemEvent,
    FileSystemEventHandler,
)
from watchdog.observers import Observer


class ChangeEvent(NamedTuple):
    paths: list[Path]
    event_type: str  # "modified" | "created" | "deleted"
    timestamp: float


_DEFAULT_IGNORE: list[str] = [
    ".git",
    ".git/*",
    "node_modules",
    "node_modules/*",
    "__pycache__",
    "__pycache__/*",
    "*.pyc",
    ".DS_Store",
    "*.log",
    ".venv",
    ".venv/*",
    "*.egg-info",
    "*.egg-info/*",
    "dist",
    "dist/*",
    "build",
    "build/*",
    ".mypy_cache",
    ".ruff_cache",
]


class _DebouncedHandler(FileSystemEventHandler):
    """Watchdog handler that collects events and fires a callback after a quiet period."""

    def __init__(
        self,
        on_change: Callable[[list[Path]], None],
        debounce_ms: int,
        ignore_patterns: list[str],
        project_path: Path,
    ) -> None:
        super().__init__()
        self._on_change = on_change
        self._debounce_s = debounce_ms / 1000.0
        self._ignore_patterns = ignore_patterns
        self._project_path = project_path

        self._pending: list[Path] = []
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Watchdog event hooks
    # ------------------------------------------------------------------

    def on_modified(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._handle(event.src_path, "modified")

    def on_created(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._handle(event.src_path, "created")

    def on_deleted(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self._handle(event.src_path, "deleted")

    def on_moved(self, event: FileSystemEvent) -> None:  # type: ignore[override]
        # Treat dest as "created" so callers get the new path
        if hasattr(event, "dest_path") and not event.is_directory:
            self._handle(event.dest_path, "created")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _should_ignore(self, path: str) -> bool:
        p = Path(path)
        # Check each part of the path and each pattern
        for pattern in self._ignore_patterns:
            # Match against full relative path
            try:
                rel = p.relative_to(self._project_path)
            except ValueError:
                rel = p
            rel_str = str(rel)
            if fnmatch.fnmatch(rel_str, pattern):
                return True
            # Also match against any single component
            for part in p.parts:
                if fnmatch.fnmatch(part, pattern):
                    return True
            # Match against filename only
            if fnmatch.fnmatch(p.name, pattern):
                return True
        return False

    def _handle(self, src_path: str, event_type: str) -> None:
        if self._should_ignore(src_path):
            return

        with self._lock:
            path = Path(src_path)
            if path not in self._pending:
                self._pending.append(path)

            # Reset the debounce timer
            if self._timer is not None:
                self._timer.cancel()

            self._timer = threading.Timer(self._debounce_s, self._fire)
            self._timer.daemon = True
            self._timer.start()

    def _fire(self) -> None:
        with self._lock:
            paths = list(self._pending)
            self._pending.clear()
            self._timer = None

        if paths:
            try:
                self._on_change(paths)
            except Exception:
                pass  # Never let a callback crash the watcher thread


class ProjectWatcher:
    """Watch a project directory and call *on_change* when files change.

    Debounce: collect rapid filesystem events and emit them as a single
    batched call after a quiet period (default 500 ms).

    Default ignored patterns (extend with :meth:`add_ignore_pattern`):
        ``.git/``, ``node_modules/``, ``__pycache__/``, ``*.pyc``,
        ``.DS_Store``, ``*.log``
    """

    def __init__(
        self,
        project_path: Path,
        on_change: Callable[[list[Path]], None],
        debounce_ms: int = 500,
        ignore_patterns: list[str] | None = None,
    ) -> None:
        self._project_path = project_path.resolve()
        self._on_change = on_change
        self._debounce_ms = debounce_ms
        self._ignore_patterns: list[str] = list(
            ignore_patterns if ignore_patterns is not None else _DEFAULT_IGNORE
        )

        self._handler = _DebouncedHandler(
            on_change=self._on_change,
            debounce_ms=self._debounce_ms,
            ignore_patterns=self._ignore_patterns,
            project_path=self._project_path,
        )
        self._observer: Observer = Observer()
        self._running = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the watchdog observer thread."""
        if self._running:
            return
        self._observer.schedule(
            self._handler,
            str(self._project_path),
            recursive=True,
        )
        self._observer.start()
        self._running = True

    def stop(self) -> None:
        """Stop the file-system observer."""
        if not self._running:
            return
        self._observer.stop()
        self._observer.join(timeout=5)
        self._running = False

    def is_running(self) -> bool:
        """Return True if the observer is active."""
        return self._running and self._observer.is_alive()

    def add_ignore_pattern(self, pattern: str) -> None:
        """Add a glob pattern to the ignore list (e.g. ``'*.tmp'``)."""
        if pattern not in self._ignore_patterns:
            self._ignore_patterns.append(pattern)
            # Propagate to the live handler
            self._handler._ignore_patterns = list(self._ignore_patterns)
