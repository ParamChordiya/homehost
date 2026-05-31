"""Structured logging with Rich output for HomeHost."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

import structlog
from rich.console import Console
from rich.logging import RichHandler
from rich.text import Text

_console = Console(stderr=True)
_out_console = Console()


def setup_logging(level: str = "info", log_file: Path | None = None) -> None:
    """Configure structlog with Rich for terminal + optional file output."""
    log_level = getattr(logging, level.upper(), logging.INFO)

    handlers: list[logging.Handler] = [
        RichHandler(
            console=_console,
            show_time=True,
            show_path=False,
            markup=True,
            rich_tracebacks=True,
            tracebacks_show_locals=False,
            omit_repeated_times=False,
        )
    ]

    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        handlers.append(file_handler)

    logging.basicConfig(
        level=log_level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=handlers,
        force=True,
    )

    # Suppress noisy third-party loggers
    for noisy in ("uvicorn.access", "watchdog", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="%H:%M:%S", utc=False),
        structlog.processors.StackInfoRenderer(),
    ]

    if sys.stderr.isatty():
        renderer: structlog.types.Processor = structlog.dev.ConsoleRenderer(
            colors=True,
            exception_formatter=structlog.dev.better_traceback,
        )
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
        foreign_pre_chain=shared_processors,
    )

    # Apply structlog formatter to all root handlers
    root_logger = logging.getLogger()
    for handler in root_logger.handlers:
        if isinstance(handler, RichHandler):
            # RichHandler handles its own formatting; skip structlog wrapping
            continue
        handler.setFormatter(formatter)


def get_logger(name: str = "homehost") -> Any:
    """Return a structlog logger instance bound to the given name."""
    return structlog.get_logger(name)


class HomeHostLogger:
    """Wrapper with HomeHost-specific log methods and Rich-formatted user errors."""

    # Error code ranges:
    # HH-1xx  Network errors
    # HH-2xx  Server errors
    # HH-3xx  Project errors
    # HH-4xx  System errors
    # HH-5xx  Config errors

    def __init__(self, name: str = "homehost") -> None:
        self._log = structlog.get_logger(name)
        self._console = _out_console

    # ------------------------------------------------------------------
    # Standard log methods
    # ------------------------------------------------------------------

    def success(self, msg: str, **kwargs: Any) -> None:
        """Log a success message (shown as INFO with a green tick)."""
        self._log.info(f"[green]✓[/green] {msg}", **kwargs)
        self._console.print(f"[bold green]✓[/bold green] {msg}")

    def info(self, msg: str, **kwargs: Any) -> None:
        self._log.info(msg, **kwargs)

    def warning(self, msg: str, **kwargs: Any) -> None:
        self._log.warning(msg, **kwargs)
        self._console.print(f"[bold yellow]⚠[/bold yellow]  {msg}")

    def error(self, msg: str, code: str = "", **kwargs: Any) -> None:
        prefix = f"[{code}] " if code else ""
        self._log.error(f"{prefix}{msg}", **kwargs)
        self._console.print(f"[bold red]✗[/bold red]  {prefix}{msg}")

    def debug(self, msg: str, **kwargs: Any) -> None:
        self._log.debug(msg, **kwargs)

    # ------------------------------------------------------------------
    # User-facing formatted error
    # ------------------------------------------------------------------

    def user_error(self, code: str, message: str, fix: str = "") -> None:
        """Display a formatted user-facing error with optional fix hint.

        Output format:
            [HH-101] Port 8080 is in use → Try port 8081 instead
        """
        self._log.error(message, error_code=code, fix=fix)

        parts: list[str] = [f"[bold red][{code}][/bold red] {message}"]
        if fix:
            parts.append(f"[dim]→[/dim] [italic]{fix}[/italic]")

        self._console.print("  ".join(parts))
