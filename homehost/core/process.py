"""Cross-platform process management with PID-file tracking."""

from __future__ import annotations

import contextlib
import json
import os
import platform
import signal
import subprocess
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import psutil
import structlog

log = structlog.get_logger(__name__)

_IS_WINDOWS = platform.system() == "Windows"

# ── Data models ────────────────────────────────────────────────────────────────


class ProcessState(str, Enum):
    RUNNING = "running"
    STOPPED = "stopped"
    ERROR = "error"
    UNKNOWN = "unknown"


@dataclass
class ManagedProcess:
    name: str
    pid: int
    state: ProcessState
    start_time: float
    command: list[str]
    log_file: Path

    # Keep a reference to the live Popen object (not serialised to PID file).
    _popen: subprocess.Popen[bytes] | None = field(default=None, repr=False, compare=False)


# ── PID-file helpers ───────────────────────────────────────────────────────────

_PidData = dict[str, Any]


def _pid_path(run_dir: Path, name: str) -> Path:
    return run_dir / f"{name}.pid"


def _write_pid_file(run_dir: Path, name: str, pid: int, command: list[str], start_time: float) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    data: _PidData = {"pid": pid, "command": command, "start_time": start_time}
    _pid_path(run_dir, name).write_text(json.dumps(data), encoding="utf-8")


def _read_pid_file(run_dir: Path, name: str) -> _PidData | None:
    path = _pid_path(run_dir, name)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _delete_pid_file(run_dir: Path, name: str) -> None:
    with contextlib.suppress(OSError):
        _pid_path(run_dir, name).unlink(missing_ok=True)


# ── Process-liveness check ────────────────────────────────────────────────────


def _pid_alive(pid: int) -> bool:
    """Return True if the process with *pid* is alive."""
    if _IS_WINDOWS:
        return psutil.pid_exists(pid)
    try:
        os.kill(pid, 0)  # signal 0 = existence check only
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # process exists but is owned by another user
        return True


# ── ProcessManager ────────────────────────────────────────────────────────────


class ProcessManager:
    """Manage named child processes with PID-file persistence."""

    def __init__(self, run_dir: Path) -> None:
        self._run_dir = run_dir
        self._run_dir.mkdir(parents=True, exist_ok=True)
        # name → live ManagedProcess (populated on start or rediscovered)
        self._processes: dict[str, ManagedProcess] = {}

    # ── Internal ──────────────────────────────────────────────────────────────

    def _log_path(self, name: str) -> Path:
        return self._run_dir / f"{name}.log"

    def _build_managed_process(
        self,
        name: str,
        pid: int,
        command: list[str],
        start_time: float,
        popen: subprocess.Popen[bytes] | None = None,
    ) -> ManagedProcess:
        state = ProcessState.RUNNING if _pid_alive(pid) else ProcessState.STOPPED
        return ManagedProcess(
            name=name,
            pid=pid,
            state=state,
            start_time=start_time,
            command=command,
            log_file=self._log_path(name),
            _popen=popen,
        )

    def _load_from_pid_file(self, name: str) -> ManagedProcess | None:
        data = _read_pid_file(self._run_dir, name)
        if data is None:
            return None
        pid: int = data["pid"]
        command: list[str] = data.get("command", [])
        start_time: float = data.get("start_time", 0.0)
        return self._build_managed_process(name, pid, command, start_time)

    # ── Public API ────────────────────────────────────────────────────────────

    def start(
        self,
        name: str,
        command: list[str],
        cwd: Path,
        env: dict[str, str] | None = None,
        log_file: Path | None = None,
    ) -> ManagedProcess:
        """Start *command* as a background process named *name*.

        Raises RuntimeError if a process with that name is already running.
        """
        if self.is_running(name):
            raise RuntimeError(f"Process '{name}' is already running (PID {self._processes[name].pid})")

        effective_log = log_file or self._log_path(name)
        effective_log.parent.mkdir(parents=True, exist_ok=True)

        log.info("starting process", name=name, command=command, cwd=str(cwd))

        try:
            log_handle = effective_log.open("ab")
            popen = subprocess.Popen(
                command,
                cwd=cwd,
                env=env,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                close_fds=not _IS_WINDOWS,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(f"Command not found: {command[0]!r}") from exc
        except OSError as exc:
            raise RuntimeError(f"Failed to start '{name}': {exc}") from exc

        start_time = time.time()
        _write_pid_file(self._run_dir, name, popen.pid, command, start_time)

        mp = self._build_managed_process(name, popen.pid, command, start_time, popen)
        self._processes[name] = mp
        log.info("process started", name=name, pid=popen.pid)
        return mp

    def stop(self, name: str, timeout: int = 10) -> bool:
        """Stop a process by name.

        Sends SIGTERM (Unix) / terminate() (Windows), waits *timeout* seconds,
        then sends SIGKILL / kill() if the process is still alive.

        Returns True if the process stopped, False if it was not found.
        """
        mp = self.get_process(name)
        if mp is None:
            log.debug("stop called for unknown process", name=name)
            return False

        pid = mp.pid
        log.info("stopping process", name=name, pid=pid)

        if not _pid_alive(pid):
            _delete_pid_file(self._run_dir, name)
            self._processes.pop(name, None)
            return True

        # Graceful termination
        popen = mp._popen
        try:
            if popen is not None:
                popen.terminate()
            elif _IS_WINDOWS:
                psutil.Process(pid).terminate()
            else:
                os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, psutil.NoSuchProcess):
            pass  # already gone
        except Exception as exc:  # noqa: BLE001
            log.warning("error sending SIGTERM", name=name, pid=pid, error=str(exc))

        def _is_alive() -> bool:
            """Check liveness, reaping zombies when we own the Popen."""
            if popen is not None:
                return popen.poll() is None
            return _pid_alive(pid)

        # Wait for graceful exit
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not _is_alive():
                break
            time.sleep(0.2)

        # Force kill if still alive
        if _is_alive():
            log.warning("process did not stop gracefully, force-killing", name=name, pid=pid)
            try:
                if popen is not None:
                    popen.kill()
                    popen.wait()
                elif _IS_WINDOWS:
                    psutil.Process(pid).kill()
                else:
                    os.kill(pid, signal.SIGKILL)
            except (ProcessLookupError, psutil.NoSuchProcess):
                pass
            except Exception as exc:  # noqa: BLE001
                log.error("error force-killing process", name=name, pid=pid, error=str(exc))
        elif popen is not None:
            # Reap the zombie so the OS frees the PID entry
            with contextlib.suppress(subprocess.TimeoutExpired):
                popen.wait(timeout=1)

        _delete_pid_file(self._run_dir, name)
        self._processes.pop(name, None)
        log.info("process stopped", name=name, pid=pid)
        return True

    def restart(self, name: str) -> ManagedProcess | None:
        """Stop then re-start a process using the same command and cwd."""
        mp = self.get_process(name)
        if mp is None:
            log.warning("restart called for unknown process", name=name)
            return None

        command = mp.command
        # Reconstruct cwd best-effort from psutil if popen is gone
        try:
            cwd = Path(psutil.Process(mp.pid).cwd())
        except Exception:  # noqa: BLE001
            cwd = Path.cwd()

        self.stop(name)
        return self.start(name, command, cwd)

    def status(self, name: str) -> ProcessState:
        """Return the current state of the named process."""
        mp = self.get_process(name)
        if mp is None:
            return ProcessState.STOPPED
        if _pid_alive(mp.pid):
            mp.state = ProcessState.RUNNING
            return ProcessState.RUNNING
        mp.state = ProcessState.STOPPED
        return ProcessState.STOPPED

    def get_process(self, name: str) -> ManagedProcess | None:
        """Return the ManagedProcess for *name*, loading from PID file if needed."""
        if name in self._processes:
            return self._processes[name]
        # Try loading from PID file (survives restarts of ProcessManager itself)
        mp = self._load_from_pid_file(name)
        if mp is not None:
            self._processes[name] = mp
        return mp

    def list_processes(self) -> list[ManagedProcess]:
        """Return all known processes, refreshing state from PID files."""
        # Discover any PID files not yet in memory
        for pid_file in self._run_dir.glob("*.pid"):
            name = pid_file.stem
            if name not in self._processes:
                mp = self._load_from_pid_file(name)
                if mp is not None:
                    self._processes[name] = mp

        # Refresh state
        for mp in list(self._processes.values()):
            mp.state = ProcessState.RUNNING if _pid_alive(mp.pid) else ProcessState.STOPPED

        return list(self._processes.values())

    def cleanup_orphans(self) -> list[str]:
        """Remove PID files for processes that are no longer alive.

        Returns a list of names that were cleaned up.
        """
        cleaned: list[str] = []
        for pid_file in self._run_dir.glob("*.pid"):
            name = pid_file.stem
            data = _read_pid_file(self._run_dir, name)
            if data is None:
                pid_file.unlink(missing_ok=True)
                cleaned.append(name)
                continue
            pid = data.get("pid", -1)
            if not _pid_alive(pid):
                log.info("cleaning up orphan PID file", name=name, pid=pid)
                pid_file.unlink(missing_ok=True)
                self._processes.pop(name, None)
                cleaned.append(name)
        return cleaned

    def stop_all(self) -> None:
        """Stop every known process."""
        for mp in self.list_processes():
            try:
                self.stop(mp.name)
            except Exception as exc:  # noqa: BLE001
                log.error("error stopping process", name=mp.name, error=str(exc))

    def is_running(self, name: str) -> bool:
        """Return True if the named process is currently alive."""
        return self.status(name) == ProcessState.RUNNING
