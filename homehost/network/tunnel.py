"""Cloudflare Tunnel integration for public internet access via cloudflared."""

from __future__ import annotations

import logging
import queue
import re
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

log = logging.getLogger(__name__)

# Pattern that matches a trycloudflare.com HTTPS URL in cloudflared output
_TUNNEL_URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")

# How long (seconds) to wait for the tunnel URL to appear in output
_TUNNEL_STARTUP_TIMEOUT: float = 30.0
# How often (seconds) to poll the process when monitoring
_MONITOR_POLL_INTERVAL: float = 5.0


@dataclass
class TunnelInfo:
    """Metadata for a running Cloudflare tunnel."""

    url: str  # e.g. "https://abc-def.trycloudflare.com"
    tunnel_id: str  # "" for quick tunnels (no account)
    is_quick: bool  # True = no Cloudflare account, random URL
    project_name: str
    local_port: int
    process_name: str  # key inside ProcessManager


class TunnelManager:
    """Manage Cloudflare Tunnel processes for one or more HomeHost projects.

    Parameters
    ----------
    cloudflared_path:
        Absolute path to the ``cloudflared`` binary.
    process_manager:
        An object that provides ``start(name, cmd)`` and ``stop(name)`` methods
        consistent with HomeHost's ProcessManager contract.  The ``Any`` type
        allows this module to be used without a hard import cycle.
    """

    def __init__(self, cloudflared_path: str, process_manager: Any) -> None:
        self._cloudflared = cloudflared_path
        self._pm = process_manager

        # project_name → TunnelInfo
        self._tunnels: dict[str, TunnelInfo] = {}
        # project_name → raw subprocess.Popen (owned by us, not process_manager)
        self._procs: dict[str, subprocess.Popen[bytes]] = {}
        self._lock = threading.Lock()

    # ── Public API ─────────────────────────────────────────────────────────────

    def start_quick_tunnel(self, project_name: str, local_port: int) -> TunnelInfo:
        """Start a quick tunnel (no Cloudflare account required).

        Runs::

            cloudflared tunnel --url http://localhost:<port>

        Reads stderr in a background thread and waits up to 30 s for a
        ``trycloudflare.com`` URL to appear.

        Returns a populated :class:`TunnelInfo`.

        Raises
        ------
        RuntimeError
            If the tunnel URL is not found within the startup timeout, or if
            ``cloudflared`` exits before producing a URL.
        """
        process_name = f"tunnel_{project_name}"
        cmd = [
            self._cloudflared,
            "tunnel",
            "--url",
            f"http://localhost:{local_port}",
            "--no-autoupdate",
        ]

        log.info(
            "Starting quick tunnel for project %r on port %d", project_name, local_port
        )

        url_queue: queue.Queue[str] = queue.Queue(maxsize=1)

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=False,  # bytes — we decode per line
            )
        except FileNotFoundError as exc:
            raise RuntimeError(
                f"cloudflared binary not found at {self._cloudflared!r}: {exc}"
            ) from exc
        except OSError as exc:
            raise RuntimeError(f"Failed to launch cloudflared: {exc}") from exc

        # Drain stderr in a background thread so the pipe never blocks
        stderr_thread = threading.Thread(
            target=self._read_stderr_for_url,
            args=(proc, url_queue),
            daemon=True,
            name=f"cloudflared-stderr-{project_name}",
        )
        stderr_thread.start()

        # Wait for URL or timeout
        deadline = time.monotonic() + _TUNNEL_STARTUP_TIMEOUT
        url = ""
        while time.monotonic() < deadline:
            # Check if process died early
            if proc.poll() is not None:
                log.error("cloudflared exited early (returncode=%d)", proc.returncode)
                raise RuntimeError(
                    f"cloudflared exited before producing a tunnel URL "
                    f"(returncode={proc.returncode})"
                )
            try:
                url = url_queue.get(timeout=0.5)
                break
            except queue.Empty:
                continue

        if not url:
            proc.terminate()
            raise RuntimeError(
                f"Tunnel URL not found within {_TUNNEL_STARTUP_TIMEOUT:.0f} s. "
                "Is cloudflared configured correctly?"
            )

        info = TunnelInfo(
            url=url,
            tunnel_id="",
            is_quick=True,
            project_name=project_name,
            local_port=local_port,
            process_name=process_name,
        )

        with self._lock:
            self._tunnels[project_name] = info
            self._procs[project_name] = proc

        log.info("Tunnel started for %r: %s", project_name, url)
        return info

    def stop_tunnel(self, project_name: str) -> bool:
        """Terminate the tunnel process for *project_name*.

        Returns ``True`` if a process was found and stopped, ``False`` if no
        tunnel was registered for this project.
        """
        with self._lock:
            proc = self._procs.pop(project_name, None)
            self._tunnels.pop(project_name, None)

        if proc is None:
            log.debug("No tunnel process found for project %r", project_name)
            return False

        return self._terminate_proc(proc, project_name)

    def get_tunnel_url(self, project_name: str) -> str:
        """Return the current tunnel URL for *project_name*, or ``''``."""
        with self._lock:
            info = self._tunnels.get(project_name)
        return info.url if info else ""

    def is_tunnel_running(self, project_name: str) -> bool:
        """Return ``True`` if the cloudflared process is alive."""
        with self._lock:
            proc = self._procs.get(project_name)
        if proc is None:
            return False
        return proc.poll() is None

    def restart_tunnel(self, project_name: str) -> TunnelInfo | None:
        """Stop the existing tunnel and start a fresh one.

        Returns the new :class:`TunnelInfo`, or ``None`` if no previous tunnel
        info is available to reconstruct the parameters.
        """
        with self._lock:
            old_info = self._tunnels.get(project_name)

        if old_info is None:
            log.warning("Cannot restart tunnel for %r: no prior TunnelInfo found", project_name)
            return None

        local_port = old_info.local_port
        self.stop_tunnel(project_name)

        # Brief pause to let the OS release the connection
        time.sleep(1)

        return self.start_quick_tunnel(project_name, local_port)

    def monitor_tunnel(
        self,
        project_name: str,
        on_disconnect: Callable[[], None],
    ) -> None:
        """Start a background thread that invokes *on_disconnect* if the tunnel dies.

        The thread polls the cloudflared process every
        :data:`_MONITOR_POLL_INTERVAL` seconds.  It exits cleanly when the
        process is no longer tracked (e.g. after :meth:`stop_tunnel`).
        """
        thread = threading.Thread(
            target=self._monitor_loop,
            args=(project_name, on_disconnect),
            daemon=True,
            name=f"tunnel-monitor-{project_name}",
        )
        thread.start()
        log.debug("Tunnel monitor started for project %r", project_name)

    def extract_tunnel_url(self, output: str) -> str:
        """Parse *output* (cloudflared stderr) and return the tunnel URL, or ``''``."""
        match = _TUNNEL_URL_RE.search(output)
        return match.group(0) if match else ""

    # ── Private helpers ────────────────────────────────────────────────────────

    def _read_stderr_for_url(
        self,
        proc: subprocess.Popen[bytes],
        url_queue: "queue.Queue[str]",
    ) -> None:
        """Thread target: read stderr line-by-line and push the URL when found."""
        assert proc.stderr is not None
        try:
            for raw_line in proc.stderr:
                line = raw_line.decode(errors="replace").rstrip()
                log.debug("cloudflared: %s", line)
                match = _TUNNEL_URL_RE.search(line)
                if match:
                    url = match.group(0)
                    try:
                        url_queue.put_nowait(url)
                    except queue.Full:
                        pass  # already sent
                    # Continue draining stderr so the pipe never blocks
        except (OSError, ValueError):
            pass  # process closed its stderr

    def _monitor_loop(
        self,
        project_name: str,
        on_disconnect: Callable[[], None],
    ) -> None:
        """Poll the tunnel process; fire *on_disconnect* if it dies unexpectedly."""
        while True:
            time.sleep(_MONITOR_POLL_INTERVAL)

            with self._lock:
                proc = self._procs.get(project_name)

            if proc is None:
                # Tunnel was explicitly stopped — normal exit
                log.debug("Monitor: tunnel %r was removed; stopping monitor", project_name)
                return

            if proc.poll() is not None:
                log.warning(
                    "Tunnel process for %r exited unexpectedly (returncode=%s)",
                    project_name,
                    proc.returncode,
                )
                # Clean up stale state
                with self._lock:
                    self._procs.pop(project_name, None)
                    self._tunnels.pop(project_name, None)

                try:
                    on_disconnect()
                except Exception as exc:
                    log.error("on_disconnect callback raised: %s", exc)

                return  # Monitor job done

    @staticmethod
    def _terminate_proc(proc: subprocess.Popen[bytes], label: str) -> bool:
        """Send SIGTERM, wait 5 s, then SIGKILL if necessary."""
        if proc.poll() is not None:
            return True  # already dead

        try:
            proc.terminate()
            proc.wait(timeout=5)
            log.info("Tunnel process %r terminated gracefully", label)
            return True
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            log.warning("Tunnel process %r did not terminate in 5 s; killed", label)
            return True
        except OSError as exc:
            log.error("Error stopping tunnel process %r: %s", label, exc)
            return False
