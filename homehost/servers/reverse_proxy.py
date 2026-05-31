"""Start application servers and configure Caddy to proxy to them.

Supports Flask, FastAPI, Django (Python WSGI/ASGI) and Node.js variants
(Next.js, React served via npx serve, generic Node).
"""

from __future__ import annotations

import logging
import os
import shutil
import socket
import subprocess
import sys
import time
import venv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Port allocation ────────────────────────────────────────────────────────────

_DEFAULT_APP_PORT_START = 9000
_CADDY_PORT_START = 8080


def _find_free_port(start: int = _DEFAULT_APP_PORT_START) -> int:
    """Find an available TCP port starting from *start*."""
    for port in range(start, start + 200):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"No free port found in range {start}–{start + 200}")


# ── AppServerInfo ──────────────────────────────────────────────────────────────


@dataclass
class AppServerInfo:
    project_name: str
    project_type: str          # from ProjectType enum values
    app_port: int              # port the app server runs on
    caddy_port: int            # port Caddy listens on (public-facing)
    process_name: str          # name in ProcessManager
    start_command: list[str] = field(default_factory=list)
    cwd: Path = field(default_factory=Path)


# ── ReverseProxyManager ────────────────────────────────────────────────────────


class ReverseProxyManager:
    """Manages per-project app server processes and their Caddy proxy entries."""

    def __init__(self, process_manager: Any, caddy_manager: Any) -> None:
        self._pm = process_manager
        self._caddy = caddy_manager
        # project_name → AppServerInfo
        self._servers: dict[str, AppServerInfo] = {}

    # ── Public API ─────────────────────────────────────────────────────────────

    def start_app_server(self, project_config: Any) -> AppServerInfo:
        """Start the app server process for a project.

        For Flask/Django: gunicorn
        For FastAPI: uvicorn
        For Node.js / Next.js / React: npm/npx-based commands
        Waits up to 30s for the app to be ready (health-check on port).
        Raises RuntimeError if the server does not start in time.
        """
        name: str = project_config.name
        project_type: str = project_config.type
        project_path = Path(project_config.path)

        app_port = self.get_app_port(project_config)
        caddy_port = _find_free_port(_CADDY_PORT_START)

        cmd = self._build_start_command(project_config, app_port, project_path)
        process_name = f"app:{name}"

        env = self._build_env(project_type, project_path, app_port)

        logger.info(
            "Starting app server for %s (%s) on port %d", name, project_type, app_port
        )
        logger.debug("Command: %s", cmd)

        try:
            proc = subprocess.Popen(
                cmd,
                cwd=project_path,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                close_fds=True,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(
                f"Could not start app server for {name}: executable not found — {exc}"
            ) from exc
        except OSError as exc:
            raise RuntimeError(f"Could not start app server for {name}: {exc}") from exc

        # Register with process manager if it supports it
        if hasattr(self._pm, "register"):
            self._pm.register(process_name, proc)

        if not self.wait_for_ready(app_port, timeout=30):
            proc.kill()
            raise RuntimeError(
                f"App server for '{name}' did not become ready on port {app_port} within 30 s"
            )

        info = AppServerInfo(
            project_name=name,
            project_type=project_type,
            app_port=app_port,
            caddy_port=caddy_port,
            process_name=process_name,
            start_command=cmd,
            cwd=project_path,
        )
        self._servers[name] = info
        logger.info("App server for %s is ready (pid=%d)", name, proc.pid)
        return info

    def stop_app_server(self, project_name: str) -> bool:
        """Stop the app server for the given project. Return True on success."""
        info = self._servers.get(project_name)
        if info is None:
            logger.warning("No tracked app server for project '%s'", project_name)
            return False

        # Delegate to process manager if available
        if hasattr(self._pm, "stop"):
            try:
                self._pm.stop(info.process_name)
                self._servers.pop(project_name, None)
                return True
            except Exception as exc:  # noqa: BLE001
                logger.error("ProcessManager.stop failed for %s: %s", project_name, exc)
                return False

        self._servers.pop(project_name, None)
        return True

    def wait_for_ready(self, port: int, timeout: int = 30) -> bool:
        """Poll *port* until the app accepts TCP connections or *timeout* seconds elapse."""
        deadline = time.monotonic() + timeout
        interval = 0.25
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=1):
                    return True
            except OSError:
                time.sleep(interval)
                interval = min(interval * 1.5, 2.0)
        return False

    def get_app_port(self, project_config: Any) -> int:
        """Determine which port the app runs on based on project type and config."""
        # Honour explicit config first
        if hasattr(project_config, "server") and project_config.server.port:
            return project_config.server.port

        _type_ports: dict[str, int] = {
            "flask": 5000,
            "fastapi": 8000,
            "django": 8000,
            "nextjs": 3000,
            "react": 5173,
            "node": 3000,
            "static": 8080,
            "docker": 8080,
            "custom": 8080,
        }
        project_type: str = getattr(project_config, "type", "custom")
        base_port = _type_ports.get(project_type, 8080)

        # Make sure the port is actually free
        if _port_is_free(base_port):
            return base_port
        return _find_free_port(base_port)

    def ensure_dependencies(self, project_config: Any) -> tuple[bool, str]:
        """Run dependency install if needed.

        - Python projects: pip install -r requirements.txt inside a venv
        - Node projects:   npm install
        Returns (success, error_message).
        """
        project_type: str = getattr(project_config, "type", "custom")
        project_path = Path(project_config.path)

        if project_type in ("flask", "fastapi", "django"):
            return self._install_python_deps(project_path)
        elif project_type in ("nextjs", "react", "node"):
            return self._install_node_deps(project_path)

        return True, ""

    def create_venv_if_needed(self, project_path: Path) -> Path:
        """Create .venv in *project_path* if it does not exist. Return venv path."""
        venv_path = project_path / ".venv"
        if not venv_path.exists():
            logger.info("Creating virtual environment at %s", venv_path)
            venv.create(str(venv_path), with_pip=True, clear=False)
        return venv_path

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _build_start_command(
        self,
        project_config: Any,
        app_port: int,
        project_path: Path,
    ) -> list[str]:
        """Build the subprocess command list for the given project type."""
        project_type: str = getattr(project_config, "type", "custom")

        # Respect an explicit start_command override
        if (
            hasattr(project_config, "server")
            and project_config.server.start_command
        ):
            raw: str = project_config.server.start_command
            return _expand_command(raw, project_path)

        if project_type == "flask":
            return self._flask_command(project_path, app_port)
        elif project_type == "fastapi":
            return self._fastapi_command(project_path, app_port)
        elif project_type == "django":
            return self._django_command(project_path, app_port)
        elif project_type == "nextjs":
            return self._nextjs_command(project_path, app_port)
        elif project_type == "react":
            return self._react_command(project_path, app_port)
        elif project_type == "node":
            return self._node_command(project_path, app_port)
        else:
            raise RuntimeError(
                f"Cannot auto-determine start command for project type '{project_type}'. "
                "Set server.start_command in project.toml."
            )

    def _build_env(
        self, project_type: str, project_path: Path, app_port: int
    ) -> dict[str, str]:
        """Build the environment dict for the app server process."""
        env = os.environ.copy()
        env["PORT"] = str(app_port)
        env["HOME"] = str(Path.home())

        if project_type in ("flask", "fastapi", "django"):
            venv_path = project_path / ".venv"
            if venv_path.exists():
                if sys.platform == "win32":
                    bin_dir = str(venv_path / "Scripts")
                else:
                    bin_dir = str(venv_path / "bin")
                env["PATH"] = bin_dir + os.pathsep + env.get("PATH", "")
                env["VIRTUAL_ENV"] = str(venv_path)

        if project_type == "flask":
            env.setdefault("FLASK_ENV", "production")
        if project_type == "django":
            env.setdefault("DJANGO_SETTINGS_MODULE", "settings")

        return env

    # ── Framework-specific commands ────────────────────────────────────────────

    def _flask_command(self, project_path: Path, port: int) -> list[str]:
        """Prefer gunicorn; fall back to flask run."""
        venv_bin = _venv_bin(project_path)
        gunicorn = _pick_executable("gunicorn", venv_bin)
        if gunicorn:
            app_module = _detect_flask_app(project_path)
            return [gunicorn, "--bind", f"0.0.0.0:{port}", "--workers", "2", app_module]

        flask_exe = _pick_executable("flask", venv_bin)
        if flask_exe:
            return [flask_exe, "run", "--host", "0.0.0.0", "--port", str(port)]

        # Last resort: python -m flask
        python = _pick_executable("python", venv_bin) or sys.executable
        return [python, "-m", "flask", "run", "--host", "0.0.0.0", "--port", str(port)]

    def _fastapi_command(self, project_path: Path, port: int) -> list[str]:
        """Use uvicorn for FastAPI."""
        venv_bin = _venv_bin(project_path)
        uvicorn = _pick_executable("uvicorn", venv_bin)
        app_module = _detect_asgi_app(project_path)
        if uvicorn:
            return [uvicorn, app_module, "--host", "0.0.0.0", "--port", str(port)]
        python = _pick_executable("python", venv_bin) or sys.executable
        return [python, "-m", "uvicorn", app_module, "--host", "0.0.0.0", "--port", str(port)]

    def _django_command(self, project_path: Path, port: int) -> list[str]:
        """Use gunicorn for Django; fall back to manage.py runserver (not for production)."""
        venv_bin = _venv_bin(project_path)
        gunicorn = _pick_executable("gunicorn", venv_bin)
        if gunicorn:
            wsgi_module = _detect_django_wsgi(project_path)
            return [gunicorn, "--bind", f"0.0.0.0:{port}", "--workers", "2", wsgi_module]

        python = _pick_executable("python", venv_bin) or sys.executable
        manage = project_path / "manage.py"
        return [python, str(manage), "runserver", f"0.0.0.0:{port}"]

    def _nextjs_command(self, project_path: Path, port: int) -> list[str]:
        npm = shutil.which("npm") or "npm"
        npx = shutil.which("npx") or "npx"
        # If `next` is a local binary, use npx
        if (project_path / "node_modules" / ".bin" / "next").exists():
            return [npx, "next", "start", "--port", str(port)]
        return [npm, "start", "--", "--port", str(port)]

    def _react_command(self, project_path: Path, port: int) -> list[str]:
        """Serve the built output from dist/ or build/ using npx serve."""
        npx = shutil.which("npx") or "npx"
        dist = project_path / "dist"
        build = project_path / "build"
        serve_dir = str(dist) if dist.exists() else str(build) if build.exists() else "dist"
        return [npx, "serve", "-s", serve_dir, "-l", str(port)]

    def _node_command(self, project_path: Path, port: int) -> list[str]:
        npm = shutil.which("npm") or "npm"
        return [npm, "start"]

    # ── Dependency installation ────────────────────────────────────────────────

    def _install_python_deps(self, project_path: Path) -> tuple[bool, str]:
        req = project_path / "requirements.txt"
        if not req.exists():
            logger.debug("No requirements.txt in %s — skipping pip install", project_path)
            return True, ""

        venv_path = self.create_venv_if_needed(project_path)
        venv_bin = venv_path / ("Scripts" if sys.platform == "win32" else "bin")
        pip = venv_bin / ("pip.exe" if sys.platform == "win32" else "pip")

        logger.info("Installing Python deps for %s", project_path)
        try:
            result = subprocess.run(
                [str(pip), "install", "-r", str(req), "--quiet"],
                capture_output=True,
                text=True,
                timeout=300,
                cwd=project_path,
            )
        except subprocess.TimeoutExpired:
            return False, "pip install timed out after 300 s"
        except OSError as exc:
            return False, f"pip install failed: {exc}"

        if result.returncode != 0:
            return False, result.stderr.strip() or result.stdout.strip()

        return True, ""

    def _install_node_deps(self, project_path: Path) -> tuple[bool, str]:
        pkg_json = project_path / "package.json"
        if not pkg_json.exists():
            return True, ""

        node_modules = project_path / "node_modules"
        if node_modules.exists():
            logger.debug("node_modules already present in %s — skipping npm install", project_path)
            return True, ""

        npm = shutil.which("npm")
        if not npm:
            return False, "npm not found on PATH"

        logger.info("Running npm install in %s", project_path)
        try:
            result = subprocess.run(
                [npm, "install", "--silent"],
                capture_output=True,
                text=True,
                timeout=300,
                cwd=project_path,
            )
        except subprocess.TimeoutExpired:
            return False, "npm install timed out after 300 s"
        except OSError as exc:
            return False, f"npm install failed: {exc}"

        if result.returncode != 0:
            return False, result.stderr.strip() or result.stdout.strip()

        return True, ""


# ── Module-level helpers ───────────────────────────────────────────────────────


def _port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _venv_bin(project_path: Path) -> Path | None:
    venv_path = project_path / ".venv"
    if not venv_path.exists():
        return None
    return venv_path / ("Scripts" if sys.platform == "win32" else "bin")


def _pick_executable(name: str, venv_bin: Path | None) -> str | None:
    """Return the full path to *name*, preferring the venv copy."""
    if venv_bin is not None:
        candidate = venv_bin / (f"{name}.exe" if sys.platform == "win32" else name)
        if candidate.exists():
            return str(candidate)
    return shutil.which(name)


def _expand_command(raw: str, project_path: Path) -> list[str]:
    """Split a shell command string into a list, expanding ${project_dir}."""
    raw = raw.replace("${project_dir}", str(project_path))
    import shlex
    return shlex.split(raw)


def _detect_flask_app(project_path: Path) -> str:
    """Heuristically find the Flask WSGI entrypoint (e.g. 'app:app')."""
    candidates = ["app", "main", "run", "wsgi", "server"]
    for candidate in candidates:
        py = project_path / f"{candidate}.py"
        if py.exists():
            try:
                text = py.read_text(encoding="utf-8", errors="ignore")
                if "Flask(" in text:
                    # Try to find the Flask instance name
                    for line in text.splitlines():
                        line = line.strip()
                        if "Flask(" in line and "=" in line:
                            var_name = line.split("=")[0].strip()
                            return f"{candidate}:{var_name}"
                    return f"{candidate}:app"
            except OSError:
                continue
    return "app:app"


def _detect_asgi_app(project_path: Path) -> str:
    """Heuristically find the ASGI app module (e.g. 'main:app')."""
    candidates = ["main", "app", "asgi", "server"]
    for candidate in candidates:
        py = project_path / f"{candidate}.py"
        if py.exists():
            try:
                text = py.read_text(encoding="utf-8", errors="ignore")
                if "FastAPI(" in text or "Starlette(" in text:
                    for line in text.splitlines():
                        line = line.strip()
                        if ("FastAPI(" in line or "Starlette(" in line) and "=" in line:
                            var_name = line.split("=")[0].strip()
                            return f"{candidate}:{var_name}"
                    return f"{candidate}:app"
            except OSError:
                continue
    return "main:app"


def _detect_django_wsgi(project_path: Path) -> str:
    """Find the Django project package name for the wsgi module."""
    # Look for manage.py to infer project name
    manage = project_path / "manage.py"
    if manage.exists():
        try:
            text = manage.read_text(encoding="utf-8", errors="ignore")
            for line in text.splitlines():
                if "DJANGO_SETTINGS_MODULE" in line and "=" in line:
                    value = line.split("=")[-1].strip().strip("'\")")
                    # value is e.g. "myproject.settings"
                    package = value.split(".")[0]
                    return f"{package}.wsgi"
        except OSError:
            pass

    # Scan for wsgi.py files
    wsgi_files = list(project_path.glob("*/wsgi.py"))
    if wsgi_files:
        package = wsgi_files[0].parent.name
        return f"{package}.wsgi"

    return "wsgi:application"
